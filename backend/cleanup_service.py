"""Asset-level expiration and owner-aware cleanup services."""

from core.logging import get_logger
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    AssetMarker,
    AssetTag,
    Board,
    BoardAssetItem,
    BoardSection,
    MediaItem,
    Project,
    ProjectAsset,
)

log = get_logger(__name__)


class CleanupService:
    """Handles automatic marking of expired generated images as deleted."""

    async def cleanup_ephemeral_media(
        self, session: AsyncSession, older_than_minutes: int = 30
    ) -> int:
        """Crash sweeper: hard-delete orphaned ephemeral one-shot-run media.

        Ephemeral media (``ephemeral_run_id`` set) are normally hard-deleted by the
        one-shot runner in a ``finally`` block at run end. If a run crashes hard (or the
        process dies mid-run) its rows + files can be left behind. This sweeper reclaims
        them: every ``ephemeral_run_id`` whose oldest row is older than the grace period
        is purged (files + DB rows) via ``purge_ephemeral_run``.

        The cutoff is by ``indexed_date`` (creation time) so an in-flight run — whose
        media are all recent — is never swept out from under it.

        Returns the number of media rows hard-deleted.
        """
        from flow_runtime.ephemeral import purge_ephemeral_run

        cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)

        # Distinct run ids whose ENTIRE set of rows predates the cutoff. Using max()
        # of indexed_date per run guarantees we never touch a run with any recent
        # (possibly in-flight) media.
        result = await session.execute(
            select(MediaItem.ephemeral_run_id)
            .where(MediaItem.ephemeral_run_id.isnot(None))
            .group_by(MediaItem.ephemeral_run_id)
            .having(func.max(MediaItem.indexed_date) < cutoff)
        )
        run_ids = [rid for (rid,) in result.all() if rid]

        if not run_ids:
            return 0

        total = 0
        for run_id in run_ids:
            try:
                total += await purge_ephemeral_run(session, run_id)
            except Exception as e:
                log.error(
                    f"EPHEMERAL CLEANUP: failed to purge run {run_id}: {e}",
                    exc_info=True,
                )
                await session.rollback()
                continue

        if total:
            log.info(
                f"EPHEMERAL CLEANUP: swept {total} orphaned ephemeral media "
                f"across {len(run_ids)} run(s) older than {older_than_minutes}m"
            )
        return total

    async def cleanup_expired_images(
        self, db: AsyncSession, folder_configs: Dict[str, Any]
    ) -> tuple[list[int], list[int], datetime | None]:
        """
        Find and mark expired generated images as deleted.
        Images with tags, boards, or markers are preserved.

        Args:
            db: Database session
            folder_configs: Dictionary mapping folder paths to their configurations (unused but kept for API compatibility)

        Returns:
            Tuple of (trashed Asset IDs, empty legacy Media list, next expiration)
        """
        now = datetime.utcnow()
        trashed_asset_ids: list[int] = []
        deleted_ids: list[int] = []

        # Repair lifecycle drift from older builds before considering expiry.
        # Any explicit curation makes the Asset durable immediately. The helper
        # also scrubs historical Media deadline residue.
        curated_asset_ids = (
            select(AssetTag.asset_id)
            .where(AssetTag.deleted_at.is_(None))
            .union(
                select(AssetMarker.asset_id).where(
                    AssetMarker.deleted_at.is_(None),
                    AssetMarker.source != "suppressed",
                ),
                select(BoardAssetItem.asset_id)
                .join(
                    BoardSection,
                    BoardSection.id == BoardAssetItem.board_section_id,
                )
                .join(Board, Board.id == BoardSection.board_id)
                .where(
                    BoardAssetItem.deleted_at.is_(None),
                    BoardSection.deleted_at.is_(None),
                    Board.deleted_at.is_(None),
                ),
                select(ProjectAsset.asset_id)
                .join(Project, Project.id == ProjectAsset.project_id)
                .where(
                    ProjectAsset.deleted_at.is_(None),
                    Project.deleted_at.is_(None),
                ),
            )
        )
        curated_expiring_asset_id = await db.scalar(
            select(Asset.id)
            .where(
                Asset.state == "active",
                Asset.deleted_at.is_(None),
                Asset.expires_at.is_not(None),
                Asset.id.in_(curated_asset_ids),
            )
            .limit(1)
        )
        await db.commit()
        if curated_expiring_asset_id is not None:
            repaired_expiration = await db.execute(
                update(Asset)
                .where(
                    Asset.state == "active",
                    Asset.deleted_at.is_(None),
                    Asset.expires_at.is_not(None),
                    Asset.id.in_(curated_asset_ids),
                )
                .values(expires_at=None)
            )
            if repaired_expiration.rowcount and repaired_expiration.rowcount > 0:
                await db.commit()

        expired_assets = list(
            await db.scalars(
                select(Asset).where(
                    Asset.state == "active",
                    Asset.deleted_at.is_(None),
                    Asset.expires_at.is_not(None),
                    Asset.expires_at <= now,
                )
            )
        )
        for asset in expired_assets:
            try:
                if await self._should_keep_asset(db, asset.id):
                    from asset_association_service import clear_asset_expiration

                    await clear_asset_expiration(db, asset.id)
                    await db.commit()
                    continue
                from asset_service import trash_asset

                await trash_asset(db, asset_id=asset.id)
                asset.expires_at = None
                await db.commit()
                trashed_asset_ids.append(asset.id)
            except Exception:
                log.exception("CLEANUP: failed to trash expired Asset %s", asset.id)
                await db.rollback()

        # Historical Media deadlines are inert. Scrub them automatically so
        # old profiles converge on the Asset-only lifecycle without presenting
        # stale status in legacy payloads.
        legacy_deadline_media_id = await db.scalar(
            select(MediaItem.id)
            .where(MediaItem.auto_delete_at.is_not(None))
            .limit(1)
        )
        await db.commit()
        if legacy_deadline_media_id is not None:
            scrubbed_media = await db.execute(
                update(MediaItem)
                .where(MediaItem.auto_delete_at.is_not(None))
                .values(auto_delete_at=None)
            )
            if scrubbed_media.rowcount and scrubbed_media.rowcount > 0:
                log.info(
                    "CLEANUP: Cleared %s legacy Media auto-delete deadlines",
                    scrubbed_media.rowcount,
                )
                await db.commit()

        # Find the next expiration time for scheduling
        next_expiration = await self._get_next_expiration(db)

        return trashed_asset_ids, deleted_ids, next_expiration

    async def _get_next_expiration(self, db: AsyncSession) -> datetime | None:
        """
        Find the earliest Asset expiration time.

        Args:
            db: Database session

        Returns:
            The next expiration datetime, or None if no pending expirations
        """
        asset_query = select(func.min(Asset.expires_at)).where(
            Asset.state == "active",
            Asset.deleted_at.is_(None),
            Asset.expires_at.is_not(None),
        )
        return await db.scalar(asset_query)

    async def _should_keep_asset(self, db: AsyncSession, asset_id: int) -> bool:
        has_tag = await db.scalar(
            select(AssetTag.id).where(
                AssetTag.asset_id == asset_id,
                AssetTag.deleted_at.is_(None),
            ).limit(1)
        )
        if has_tag is not None:
            return True
        has_marker = await db.scalar(
            select(AssetMarker.id).where(
                AssetMarker.asset_id == asset_id,
                AssetMarker.deleted_at.is_(None),
                AssetMarker.source != "suppressed",
            ).limit(1)
        )
        if has_marker is not None:
            return True
        has_board = await db.scalar(
            select(BoardAssetItem.id)
            .join(BoardSection, BoardSection.id == BoardAssetItem.board_section_id)
            .join(Board, Board.id == BoardSection.board_id)
            .where(
                BoardAssetItem.asset_id == asset_id,
                BoardAssetItem.deleted_at.is_(None),
                BoardSection.deleted_at.is_(None),
                Board.deleted_at.is_(None),
            )
            .limit(1)
        )
        if has_board is not None:
            return True
        has_project = await db.scalar(
            select(ProjectAsset.id)
            .join(Project, Project.id == ProjectAsset.project_id)
            .where(
                ProjectAsset.asset_id == asset_id,
                ProjectAsset.deleted_at.is_(None),
                Project.deleted_at.is_(None),
            )
            .limit(1)
        )
        return has_project is not None

"""Asset-level expiration and owner-aware cleanup services."""

from core.logging import get_logger
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy import select, func, update, delete, or_
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

    async def cleanup_empty_unnamed_entities(
        self, session: AsyncSession, older_than_hours: int = 12
    ) -> Dict[str, list[int]]:
        """Reap abandoned empty, unnamed boards/flows/chats past the cutoff.

        These are the useless husks a misclick or an abandoned start leaves
        behind: a board with no name and no assets, a flow with no name whose
        program is still the untouched placeholder and whose agent chat has no
        messages, or a standalone chat with an auto-generated name and no
        messages. Anything the user actually touched — named it, added an
        asset, edited the program, sent a message — is never eligible.

        This is a hard evaporation, not a trip to the trash:
          - boards: the row and its (empty) sections/items are hard-deleted.
          - flows: the row is hard-deleted and the on-disk program/state dir
            removed.
          - chats: soft-deleted so the existing two-phase deletion pipeline
            purges them; an empty chat has nothing to finalize, so it
            evaporates on the next delete-worker pass.

        Gated on ``created_at`` (stable) rather than ``updated_at`` (bumped by
        incidental reconcile / default-section writes) so an actively-built
        scaffold a user just opened is never reaped.

        Returns ``{"boards": [...], "flows": [...], "chats": [...]}`` of the
        ids that were reaped. Each entity is committed independently so one
        failure never rolls back the rest.
        """
        from database import (
            Board,
            BoardSection,
            BoardAssetItem,
            BoardItem,
            Flow,
            Chat,
            ChatItem,
            UserTool,
        )
        from flow_runtime.directory import is_empty_flow_program, delete_flow_directory
        from flow_runtime.paths import get_flow_program_path
        from routes.chats import is_auto_generated_name
        import flow_lifecycle

        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
        reaped: Dict[str, list[int]] = {"boards": [], "flows": [], "chats": []}

        # --- Boards: blank name + zero live assets ---
        boards = list(
            await session.scalars(
                select(Board).where(
                    Board.deleted_at.is_(None),
                    Board.created_at <= cutoff,
                    func.trim(Board.name) == "",
                )
            )
        )
        for board in boards:
            try:
                # Fail-closed emptiness: reap only a board that has *never* held
                # content. Any BoardAssetItem or legacy BoardItem row — even one
                # that's soft-deleted or sits in a soft-deleted section — keeps
                # the board alive, so a permanent delete can never take
                # restorable curation (or the assets' "keep-forever" signal)
                # with it. A misclick husk has zero rows either way.
                asset_item_count = await session.scalar(
                    select(func.count(BoardAssetItem.id))
                    .join(
                        BoardSection,
                        BoardSection.id == BoardAssetItem.board_section_id,
                    )
                    .where(BoardSection.board_id == board.id)
                )
                legacy_item_count = await session.scalar(
                    select(func.count())
                    .select_from(BoardItem)
                    .join(
                        BoardSection,
                        BoardSection.id == BoardItem.board_section_id,
                    )
                    .where(BoardSection.board_id == board.id)
                )
                if asset_item_count or legacy_item_count:
                    continue
                # Hard-delete children explicitly — don't rely on the SQLite FK
                # pragma being enabled — then the board itself.
                section_ids = list(
                    await session.scalars(
                        select(BoardSection.id).where(BoardSection.board_id == board.id)
                    )
                )
                if section_ids:
                    await session.execute(
                        delete(BoardItem).where(
                            BoardItem.board_section_id.in_(section_ids)
                        )
                    )
                    await session.execute(
                        delete(BoardAssetItem).where(
                            BoardAssetItem.board_section_id.in_(section_ids)
                        )
                    )
                    await session.execute(
                        delete(BoardSection).where(BoardSection.id.in_(section_ids))
                    )
                await session.delete(board)
                await session.commit()
                reaped["boards"].append(board.id)
            except Exception:
                log.exception("HUSK CLEANUP: failed to reap empty board %s", board.id)
                await session.rollback()

        # --- Flows: blank name + untouched program + no chat messages ---
        flows = list(
            await session.scalars(
                select(Flow).where(
                    Flow.deleted_at.is_(None),
                    Flow.created_at <= cutoff,
                    func.trim(Flow.name) == "",
                )
            )
        )
        for flow in flows:
            try:
                # Program must still be the untouched new-flow placeholder. If
                # the file is unreadable we can't prove it's untouched — skip.
                try:
                    program_text = get_flow_program_path(flow.id).read_text()
                except OSError:
                    continue
                if not is_empty_flow_program(program_text):
                    continue
                # Its agent chat(s) must carry no messages.
                flow_chat_ids = list(
                    await session.scalars(
                        select(Chat.id).where(
                            Chat.flow_id == flow.id, Chat.deleted_at.is_(None)
                        )
                    )
                )
                has_message = False
                for cid in flow_chat_ids:
                    if await session.scalar(
                        select(func.count(ChatItem.id)).where(ChatItem.chat_id == cid)
                    ):
                        has_message = True
                        break
                if has_message:
                    continue
                # Reap. Soft-delete the (empty) agent chats so the vetted
                # two-phase pipeline tears them down — it handles LLMTrace /
                # GenerationJob / media, which a hand-rolled DELETE would leave
                # to trip a NOT NULL FK and get the whole flow stuck. Then drop
                # editing/parent handles and hard-delete the flow row.
                now = datetime.utcnow()
                for cid in flow_chat_ids:
                    await session.execute(
                        update(Chat).where(Chat.id == cid).values(deleted_at=now)
                    )
                await session.execute(
                    update(UserTool)
                    .where(UserTool.flow_id == flow.id)
                    .values(flow_id=None)
                )
                await session.execute(
                    update(Flow)
                    .where(Flow.parent_id == flow.id)
                    .values(parent_id=None)
                )
                await session.delete(flow)
                await session.commit()
                # Row is gone — record it before best-effort teardown so a
                # failure stopping the scheduler / removing the dir can't
                # silently un-report the reap (and lose the WS broadcast).
                reaped["flows"].append(flow.id)
                try:
                    await flow_lifecycle.stop_and_unregister(flow.id)
                    delete_flow_directory(flow.id)
                except Exception:
                    log.exception(
                        "HUSK CLEANUP: post-delete teardown failed for flow %s",
                        flow.id,
                    )
            except Exception:
                log.exception("HUSK CLEANUP: failed to reap empty flow %s", flow.id)
                await session.rollback()

        # --- Chats: auto-generated name + no messages + standalone ---
        chats = list(
            await session.scalars(
                select(Chat).where(
                    Chat.deleted_at.is_(None),
                    Chat.flow_id.is_(None),
                    Chat.created_at <= cutoff,
                    or_(
                        Chat.name == "",
                        Chat.name == "Untitled",
                        Chat.name.like("Untitled %"),
                    ),
                )
            )
        )
        for chat in chats:
            try:
                if not is_auto_generated_name(chat.name):
                    continue
                if await session.scalar(
                    select(func.count(ChatItem.id)).where(ChatItem.chat_id == chat.id)
                ):
                    continue
                # Soft-delete; the existing two-phase pipeline hard-purges it.
                chat.deleted_at = datetime.utcnow()
                await session.commit()
                reaped["chats"].append(chat.id)
            except Exception:
                log.exception("HUSK CLEANUP: failed to reap empty chat %s", chat.id)
                await session.rollback()

        return reaped

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

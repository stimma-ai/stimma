"""Service for automatic cleanup of expired generated images.

When images expire (auto_delete_at), they are marked as deleted (deleted_at set)
but the file stays in place until trash is emptied.
"""

import os
from core.logging import get_logger
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy import and_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem

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

    async def cleanup_expired_images(self, db: AsyncSession, folder_configs: Dict[str, Any]) -> tuple[list[int], datetime | None]:
        """
        Find and mark expired generated images as deleted.
        Images with tags, boards, or markers are preserved.

        Args:
            db: Database session
            folder_configs: Dictionary mapping folder paths to their configurations (unused but kept for API compatibility)

        Returns:
            Tuple of (list of deleted media IDs, next expiration datetime or None)
        """
        now = datetime.utcnow()
        deleted_ids: list[int] = []

        # First, check how many items have auto_delete_at set (for debugging)
        pending_query = (
            select(func.count())
            .select_from(MediaItem)
            .where(
                and_(
                    MediaItem.auto_delete_at.isnot(None),
                    MediaItem.deleted_at.is_(None)
                )
            )
        )
        pending_result = await db.execute(pending_query)
        pending_count = pending_result.scalar() or 0

        # Query for expired media items directly
        query = (
            select(MediaItem)
            .where(
                and_(
                    MediaItem.auto_delete_at.isnot(None),
                    MediaItem.auto_delete_at <= now,
                    MediaItem.deleted_at.is_(None)  # Not already deleted
                )
            )
        )

        result = await db.execute(query)
        expired_items = result.scalars().all()

        # Only log if there's something to report
        if expired_items or pending_count > 0:
            log.info(f"CLEANUP: Found {len(expired_items)} expired items out of {pending_count} pending auto-delete items (now={now.isoformat()})")

        # Log details of expired items for debugging
        if expired_items:
            for item in expired_items[:5]:  # Log first 5 for brevity
                log.info(f"CLEANUP: Expired item {item.id}: auto_delete_at={item.auto_delete_at.isoformat() if item.auto_delete_at else 'None'}")
        elif pending_count > 0:
            # There are pending items but none are expired - log the next few to see when they expire
            sample_query = (
                select(MediaItem.id, MediaItem.auto_delete_at)
                .where(
                    and_(
                        MediaItem.auto_delete_at.isnot(None),
                        MediaItem.deleted_at.is_(None)
                    )
                )
                .order_by(MediaItem.auto_delete_at)
                .limit(3)
            )
            sample_result = await db.execute(sample_query)
            samples = sample_result.all()
            for sample_id, sample_time in samples:
                log.info(f"CLEANUP: Pending item {sample_id}: auto_delete_at={sample_time.isoformat() if sample_time else 'None'} (in {(sample_time - now).total_seconds():.0f}s)")

        for media_item in expired_items:
            try:
                # Re-fetch to avoid stale data (item may have been manually trashed)
                result = await db.execute(
                    select(MediaItem).where(MediaItem.id == media_item.id)
                )
                media_item = result.scalar_one_or_none()
                if not media_item or media_item.deleted_at is not None or media_item.auto_delete_at is None:
                    # Item was deleted/trashed while we were processing, skip it
                    continue

                # Check if file exists - if missing, just mark as deleted
                if not os.path.exists(media_item.file_path):
                    log.info(
                        f"File already missing, marking media {media_item.id} as deleted: {media_item.file_path}"
                    )
                    media_item.deleted_at = datetime.utcnow()
                    media_item.auto_delete_at = None
                    await db.commit()
                    deleted_ids.append(media_item.id)
                    continue

                # Check if the image has tags, boards, or markers
                should_keep = await self._should_keep_image(db, media_item.id)

                if should_keep:
                    log.info(
                        f"Skipping deletion of media {media_item.id} (file: {media_item.file_path}) "
                        f"- has tags, boards, or markers"
                    )
                    # Clear the auto_delete_at since user has shown interest in keeping it
                    media_item.auto_delete_at = None
                    await db.commit()
                    continue

                # Mark as deleted - file stays in place
                log.info(
                    f"Marking expired image as deleted: {media_item.file_path} "
                    f"(expired at {media_item.auto_delete_at.isoformat()})"
                )

                deleted_media_id = media_item.id
                media_item.deleted_at = datetime.utcnow()
                media_item.auto_delete_at = None  # Clear expiration so it doesn't immediately expire again if restored
                await db.commit()

                deleted_ids.append(deleted_media_id)
                log.info(f"Successfully marked as deleted: {media_item.file_path}")

            except Exception as e:
                log.error(
                    f"Error deleting expired media {media_item.id} ({media_item.file_path}): {e}",
                    exc_info=True
                )
                await db.rollback()
                continue

        if deleted_ids:
            log.info(f"Cleanup complete: marked {len(deleted_ids)} expired images as deleted (IDs: {deleted_ids[:10]}{'...' if len(deleted_ids) > 10 else ''})")

        # Find the next expiration time for scheduling
        next_expiration = await self._get_next_expiration(db)

        return deleted_ids, next_expiration

    async def _get_next_expiration(self, db: AsyncSession) -> datetime | None:
        """
        Find the earliest auto_delete_at time for pending deletions.

        Args:
            db: Database session

        Returns:
            The next expiration datetime, or None if no pending expirations
        """
        query = (
            select(func.min(MediaItem.auto_delete_at))
            .where(
                and_(
                    MediaItem.auto_delete_at.isnot(None),
                    MediaItem.deleted_at.is_(None)
                )
            )
        )

        result = await db.execute(query)
        next_expiration = result.scalar()

        return next_expiration

    async def _should_keep_image(self, db: AsyncSession, media_id: int) -> bool:
        """
        Check if an image has tags, boards, or markers that indicate it should be kept.

        Args:
            db: Database session
            media_id: ID of the media item to check

        Returns:
            True if the image should be kept, False if it can be deleted
        """
        # Check for tags
        tag_query = text("SELECT COUNT(*) FROM media_tags WHERE media_id = :media_id")
        tag_result = await db.execute(tag_query, {"media_id": media_id})
        tag_count = tag_result.scalar()
        if tag_count and tag_count > 0:
            return True

        # Check for boards
        board_query = text(
            "SELECT COUNT(*) FROM board_items bi "
            "JOIN board_sections bs ON bs.id = bi.board_section_id "
            "JOIN boards b ON b.id = bs.board_id "
            "WHERE bi.media_id = :media_id AND bs.deleted_at IS NULL AND b.deleted_at IS NULL"
        )
        board_result = await db.execute(board_query, {"media_id": media_id})
        board_count = board_result.scalar()
        if board_count and board_count > 0:
            return True

        # Check for markers
        marker_query = text("SELECT COUNT(*) FROM media_markers WHERE media_id = :media_id")
        marker_result = await db.execute(marker_query, {"media_id": media_id})
        marker_count = marker_result.scalar()
        if marker_count and marker_count > 0:
            return True

        return False

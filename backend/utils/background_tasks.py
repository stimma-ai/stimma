"""Background tasks for media monitoring and cleanup."""
import asyncio
from core.logging import get_logger
from datetime import datetime
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset, AssetRevision, MediaItem
from database_registry import get_database_registry
from config import get_settings

log = get_logger(__name__)

# Processing phases to monitor
BROADCAST_PHASES = ['metadata', 'clip', 'face_detection', 'vlm_caption']


async def monitor_media_changes(ws_manager):
    """
    Background task to monitor for new media additions and broadcast via WebSocket.
    Checks database periodically and emits 'media_added' events when new items are detected.
    """
    last_total_count = 0

    while True:
        try:
            await asyncio.sleep(5)  # Check every 5 seconds

            # Get current total count across ALL profile databases
            settings = get_settings()
            registry = get_database_registry()
            current_total = 0

            for profile in settings.profiles:
                # Skip profiles not in registry (may have been removed)
                if not registry.has_profile(profile.id):
                    continue
                db = registry.get_database(profile.id)
                async with db.async_session_maker() as session:
                    result = await session.execute(select(func.count()).select_from(MediaItem))
                    current_total += result.scalar() or 0

            # Check if new items were added
            if current_total > last_total_count and last_total_count > 0:
                new_count = current_total - last_total_count
                log.info(f"MEDIA MONITOR: Detected {new_count} new items (total: {current_total})")

                # Broadcast to all connected WebSocket clients (global event)
                await ws_manager.broadcast('media_added', {
                    'count': new_count,
                    'total': current_total,
                    'timestamp': datetime.now().isoformat()
                }, include_profile=False)

            last_total_count = current_total

        except asyncio.CancelledError:
            log.info("MEDIA MONITOR: Shutting down")
            break
        except Exception as e:
            log.error(f"MEDIA MONITOR: Error: {e}", exc_info=True)
            await asyncio.sleep(30)  # Longer sleep on error


async def cleanup_expired_images(ws_manager):
    """
    Background task to automatically mark expired generated images as deleted.
    Dynamically schedules based on next expiration time, with fallback to periodic checks.

    """
    from cleanup_service import CleanupService

    cleanup_service = CleanupService()

    log.info("CLEANUP: Auto-delete cleanup task started, waiting 5 seconds before first check...")

    # Initial delay before first check
    await asyncio.sleep(5)

    log.info("CLEANUP: Beginning cleanup loop")

    while True:
        try:
            # Run cleanup for ALL profile databases
            settings = get_settings()
            registry = get_database_registry()

            expired_assets_by_profile: dict[str, list[int]] = {}
            legacy_media_by_profile: dict[str, list[int]] = {}
            earliest_expiration = None

            for profile in settings.profiles:
                # Skip profiles not in registry (may have been removed)
                if not registry.has_profile(profile.id):
                    continue

                # Get folder configs for this profile
                folder_configs = {folder.path: folder for folder in profile.folders}

                # Run cleanup on this profile's database
                db = registry.get_database(profile.id)
                async with db.async_session_maker() as session:
                    asset_ids, media_ids, next_expiration = (
                        await cleanup_service.cleanup_expired_images(session, folder_configs)
                    )
                    if asset_ids:
                        expired_assets_by_profile[profile.id] = asset_ids
                    if media_ids:
                        legacy_media_by_profile[profile.id] = media_ids

                    # Track earliest expiration across all profiles
                    if next_expiration:
                        if earliest_expiration is None or next_expiration < earliest_expiration:
                            earliest_expiration = next_expiration

            next_expiration = earliest_expiration

            for profile_id, asset_ids in expired_assets_by_profile.items():
                for asset_id in asset_ids:
                    await ws_manager.broadcast(
                        "asset_deleted",
                        {
                            "asset_id": asset_id,
                            "reason": "auto_delete_expired",
                            "profile_id": profile_id,
                        },
                        include_profile=False,
                    )
            for profile_id, media_ids in legacy_media_by_profile.items():
                event = "media_bulk_deleted" if len(media_ids) > 1 else "media_deleted"
                payload = (
                    {"media_ids": media_ids}
                    if len(media_ids) > 1
                    else {"media_id": media_ids[0]}
                )
                await ws_manager.broadcast(
                    event,
                    {
                        **payload,
                        "reason": "auto_delete_expired",
                        "profile_id": profile_id,
                    },
                    include_profile=False,
                )

            # Calculate next sleep duration
            if next_expiration:
                # Sleep until next expiration, with a small buffer
                now = datetime.utcnow()
                sleep_seconds = (next_expiration - now).total_seconds() + 1  # +1 second buffer

                # If already expired or very soon, check immediately (but at least 1 second)
                # Otherwise clamp between 1 second and 300 seconds (5 minutes max)
                if sleep_seconds < 1:
                    sleep_seconds = 1
                else:
                    sleep_seconds = min(sleep_seconds, 300)

                log.info(f"CLEANUP: Next expiration in {sleep_seconds:.1f} seconds at {next_expiration.isoformat()}")
            else:
                # No pending expirations, check again in 60 seconds
                sleep_seconds = 60
                log.debug("CLEANUP: No pending expirations, checking again in 60 seconds")

            await asyncio.sleep(sleep_seconds)

        except asyncio.CancelledError:
            log.info("CLEANUP: Shutting down")
            break
        except Exception as e:
            log.error(f"CLEANUP: Error during cleanup: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait 60 seconds on error before retrying


async def cleanup_ephemeral_media():
    """Crash sweeper for orphaned one-shot flow-as-tool ephemeral media.

    Ephemeral media are hard-deleted by the one-shot runner at run end; this sweeps
    anything a crashed run left behind (rows + files), per profile, at startup and
    periodically. The grace period in cleanup_ephemeral_media protects in-flight runs.
    """
    from cleanup_service import CleanupService

    cleanup_service = CleanupService()

    # Small initial delay so it doesn't compete with startup migrations/init.
    await asyncio.sleep(15)

    log.info("EPHEMERAL CLEANUP: sweeper started")

    while True:
        try:
            settings = get_settings()
            registry = get_database_registry()

            total = 0
            for profile in settings.profiles:
                if not registry.has_profile(profile.id):
                    continue
                db = registry.get_database(profile.id)
                async with db.async_session_maker() as session:
                    total += await cleanup_service.cleanup_ephemeral_media(session)

            if total:
                log.info(f"EPHEMERAL CLEANUP: swept {total} orphaned ephemeral media")

            # Run every 10 minutes — orphans are rare and the grace period is 30m.
            await asyncio.sleep(600)

        except asyncio.CancelledError:
            log.info("EPHEMERAL CLEANUP: Shutting down")
            break
        except Exception as e:
            log.error(f"EPHEMERAL CLEANUP: Error during sweep: {e}", exc_info=True)
            await asyncio.sleep(600)


async def monitor_processing_stats(ws_manager):
    """
    Background task to monitor processing stats and broadcast via WebSocket.
    This bridges the multiprocessing gap - the ingestion worker runs in a separate
    process and can't access WebSocket connections, so this task queries the DB
    and broadcasts stats from the main web server process.

    Uses a single aggregated query and 2-second interval to minimize DB load.
    Aggregates stats across ALL profile databases.
    """
    from sqlalchemy import case

    while True:
        try:
            await asyncio.sleep(5)  # Update every 5 seconds - stats don't need real-time updates

            # Query stats from ALL profile databases
            settings = get_settings()
            registry = get_database_registry()

            # Initialize aggregated phase_stats
            phase_stats = {}
            for phase in BROADCAST_PHASES:
                phase_stats[phase] = {status: 0 for status in ['pending', 'processing', 'completed', 'failed']}

            for profile in settings.profiles:
                # Skip profiles not in registry (may have been removed)
                if not registry.has_profile(profile.id):
                    continue
                db = registry.get_database(profile.id)
                async with db.async_session_maker() as session:
                    # Build a single query that counts all phase/status combinations
                    columns = []
                    for phase in BROADCAST_PHASES:
                        status_col = getattr(MediaItem, f"{phase}_status")
                        for status in ['pending', 'processing', 'completed', 'failed']:
                            columns.append(
                                func.sum(case((status_col == status, 1), else_=0)).label(f"{phase}_{status}")
                            )

                    result = await session.execute(select(*columns))
                    row = result.one()

                    # Aggregate results from this profile
                    for phase in BROADCAST_PHASES:
                        for status in ['pending', 'processing', 'completed', 'failed']:
                            phase_stats[phase][status] += getattr(row, f"{phase}_{status}") or 0

            # Broadcast to all connected WebSocket clients (global event, no profile filtering)
            await ws_manager.broadcast('processing_stats', {'phase_stats': phase_stats}, include_profile=False)

        except asyncio.CancelledError:
            log.info("PROCESSING STATS MONITOR: Shutting down")
            break
        except Exception as e:
            log.error(f"PROCESSING STATS MONITOR: Error: {e}", exc_info=True)
            await asyncio.sleep(5)  # Longer sleep on error


async def clear_auto_delete_for_media(session: AsyncSession, media_ids: list[int], ws_manager):
    """
    Clear auto-delete settings for media items when they are tagged, marked, or collected.
    This prevents auto-deletion of images that the user has actively curated.

    Args:
        session: Database session
        media_ids: List of media item IDs to clear auto-delete for
        ws_manager: WebSocket manager for broadcasting events
    """
    if not media_ids:
        return

    # Fetch every requested Media: the Asset deadline may still be populated
    # even when the legacy Media deadline has already been cleared.
    query = select(MediaItem).where(MediaItem.id.in_(media_ids))
    result = await session.execute(query)
    media_items = result.scalars().all()

    # Clear both the legacy payload deadline and canonical Asset deadline.
    affected_media_ids = []
    for media_item in media_items:
        if media_item.auto_delete_at is not None:
            media_item.auto_delete_at = None
            affected_media_ids.append(media_item.id)
            log.info(f"Cleared auto-delete for media {media_item.id}")

    asset_rows = (
        await session.execute(
            select(Asset, AssetRevision.primary_media_id)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .where(
                AssetRevision.primary_media_id.in_(media_ids),
                Asset.deleted_at.is_(None),
            )
        )
    ).all()
    affected_asset_ids = []
    for asset, media_id in asset_rows:
        if asset.expires_at is not None:
            asset.expires_at = None
            affected_asset_ids.append(asset.id)
        if media_id not in affected_media_ids:
            affected_media_ids.append(media_id)

    if not affected_media_ids and not affected_asset_ids:
        return

    await session.commit()

    # Broadcast WebSocket events to update UI
    for media_id in affected_media_ids:
        await ws_manager.broadcast('auto_delete_removed', {
            'media_id': media_id
        })
    if affected_asset_ids:
        await ws_manager.broadcast('assets_updated', {
            'asset_ids': affected_asset_ids,
            'fields': ['expires_at'],
        })


async def monitor_system_warnings(ws_manager):
    """
    Background task to monitor system requirements and broadcast warnings.
    Checks FFmpeg availability every 5 minutes and broadcasts events when status changes.
    """
    from ffmpeg_checker import get_ffmpeg_checker

    # Track active warnings to detect state changes
    active_warnings = set()

    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes

            checker = get_ffmpeg_checker()
            ffmpeg_available, ffprobe_available = checker.check_availability()

            warning_key = "ffmpeg_missing"

            # Check if FFmpeg is missing
            if not ffmpeg_available or not ffprobe_available:
                # FFmpeg is missing
                if warning_key not in active_warnings:
                    # New warning - broadcast it
                    active_warnings.add(warning_key)

                    missing_tools = []
                    if not ffmpeg_available:
                        missing_tools.append("ffmpeg")
                    if not ffprobe_available:
                        missing_tools.append("ffprobe")

                    log.warning(f"SYSTEM WARNING: FFmpeg components missing: {', '.join(missing_tools)}")

                    await ws_manager.broadcast('system_warning', {
                        'type': 'ffmpeg_missing',
                        'title': 'FFmpeg Required',
                        'message': f'FFmpeg is not installed on your system. Missing: {", ".join(missing_tools)}',
                        'action_url': 'https://stimma.ai/link/ffmpeg'
                    }, include_profile=False)
            else:
                # FFmpeg is available
                if warning_key in active_warnings:
                    # Warning cleared - broadcast cleared event
                    active_warnings.remove(warning_key)
                    log.info("SYSTEM WARNING: FFmpeg is now available")

                    await ws_manager.broadcast('system_warning_cleared', {
                        'type': 'ffmpeg_missing'
                    }, include_profile=False)

        except asyncio.CancelledError:
            log.info("SYSTEM WARNINGS MONITOR: Shutting down")
            break
        except Exception as e:
            log.error(f"SYSTEM WARNINGS MONITOR: Error: {e}", exc_info=True)
            await asyncio.sleep(300)  # Wait 5 minutes on error before retrying

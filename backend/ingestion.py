import asyncio
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from concurrent.futures import ThreadPoolExecutor
import random
import json

from database import MediaItem, Keyword, MediaKeyword, Face, MediaMarker, Marker
from database_registry import get_database_registry
from media_scanner import (
    scan_directories, fast_scan_directories, extract_metadata,
    VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, STRUCTURED_EXTENSIONS, IMAGE_EXTENSIONS,
    get_file_extension
)
from exif_extractor import extract_prompt_from_exif, extract_stimma_metadata
from vlm_service import VLMService
from config import get_settings
from config_version import get_config_version_manager
from core.logging import get_logger
from prompts import get_prompt
from PIL import Image

log = get_logger(__name__)

# Thread pool for CPU-bound operations (file I/O, hashing)
_io_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="file_io")

# Processing phases (metadata must come first - others depend on it)
PHASES = ['metadata', 'clip', 'face_detection', 'vlm_caption']

# Retry policy
MAX_RETRIES = 5
RETRY_BACKOFF = [60, 300, 1800, 7200, 86400]  # 1min, 5min, 30min, 2hr, 24hr

# Visual media types that can be CLIP analyzed, face detected, and captioned
VISUAL_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def is_visual_media(file_path: Path) -> bool:
    """Check if a file is visual media (image or video) that can be AI-processed.

    Non-visual types (audio, text, sets, grids) should skip CLIP, face detection, and VLM captioning.
    """
    ext = get_file_extension(file_path)
    return ext in VISUAL_EXTENSIONS


async def save_keywords_to_normalized_tables(session: AsyncSession, media_id: int, keywords_str: str):
    """
    Save keywords from comma-separated string to normalized keywords tables.

    Args:
        session: AsyncSession for database operations
        media_id: ID of the media item
        keywords_str: Comma-separated keywords string
    """
    if not keywords_str:
        return

    # Parse and normalize keywords
    keyword_list = list(set(kw.strip().lower() for kw in keywords_str.split(',') if kw.strip()))

    # Clear existing keywords for this media item
    from sqlalchemy import delete
    await session.execute(
        delete(MediaKeyword).where(MediaKeyword.media_id == media_id)
    )

    for keyword_text in keyword_list:
        # Get or create keyword
        result = await session.execute(
            select(Keyword).where(Keyword.keyword_text == keyword_text)
        )
        keyword = result.scalar_one_or_none()

        if not keyword:
            # Create new keyword
            keyword = Keyword(keyword_text=keyword_text)
            session.add(keyword)
            await session.flush()  # Get the ID

        # Create media_keyword relationship
        media_keyword = MediaKeyword(media_id=media_id, keyword_id=keyword.id)
        session.add(media_keyword)


async def sync_auto_markers_for_items(
    session: AsyncSession,
    media_items: list[tuple[int, str]],  # List of (media_id, file_path)
    profile_folders: list,  # List of FolderConfig objects
    remove_only: bool = False,  # If True, only remove auto-markers (for cleanup)
):
    """
    Sync auto-markers for media items based on folder config.

    - Adds auto-markers for markers configured on the folder
    - Removes auto-markers for markers no longer in folder config
    - Skips if manual or suppressed marker already exists
    """
    if not media_items:
        return

    # Build folder-to-markers mapping
    folder_markers = {}
    all_marker_names = set()
    for folder in profile_folders:
        if folder.markers:
            folder_markers[folder.path] = set(folder.markers)
            all_marker_names.update(folder.markers)

    log.info(f"AUTO-MARKERS: Folder markers config: {folder_markers}")
    log.info(f"AUTO-MARKERS: All marker names needed: {all_marker_names}")

    # Get marker IDs from database (for adding new auto-markers)
    markers_by_name = {}
    if all_marker_names:
        result = await session.execute(
            select(Marker).where(Marker.name.in_(all_marker_names))
        )
        markers_by_name = {m.name: m.id for m in result.scalars().all()}
        log.info(f"AUTO-MARKERS: Found markers in DB: {markers_by_name}")

        if not markers_by_name and not remove_only:
            log.warning(f"AUTO-MARKERS: None of configured markers found in DB: {all_marker_names}")
            return

    # For each media item, determine what auto-markers it should have
    added_count = 0
    removed_count = 0
    for media_id, file_path in media_items:
        # Find which folder this file is in
        target_markers = set()
        for folder_path, marker_names in folder_markers.items():
            if file_path.startswith(folder_path):
                target_markers = marker_names
                break

        # Get existing markers for this media item
        existing_result = await session.execute(
            select(MediaMarker).where(MediaMarker.media_id == media_id)
        )
        existing_markers = {mm.marker_id: mm for mm in existing_result.scalars().all()}

        # Add auto-markers that should exist
        for marker_name in target_markers:
            marker_id = markers_by_name.get(marker_name)
            if not marker_id:
                continue

            if marker_id in existing_markers:
                # Already exists (manual, auto, or suppressed) - don't change
                continue

            # Add new auto-marker
            media_marker = MediaMarker(media_id=media_id, marker_id=marker_id, source='auto')
            session.add(media_marker)
            added_count += 1

        # Remove auto-markers that should no longer exist
        # If target_markers is empty, all auto-markers should be removed
        target_marker_ids = {markers_by_name.get(n) for n in target_markers if markers_by_name.get(n)}
        for marker_id, media_marker in existing_markers.items():
            if media_marker.source == 'auto' and marker_id not in target_marker_ids:
                await session.delete(media_marker)
                removed_count += 1

    log.info(f"AUTO-MARKERS: Added {added_count}, removed {removed_count} auto-markers")


class IngestionProgress:
    """Track progress of media ingestion."""

    def __init__(self):
        self.phase_stats = {
            'metadata': {'pending': 0, 'processing': 0, 'completed': 0, 'failed': 0},
            'clip': {'pending': 0, 'processing': 0, 'completed': 0, 'failed': 0},
            'face_detection': {'pending': 0, 'processing': 0, 'completed': 0, 'failed': 0},
            'vlm_caption': {'pending': 0, 'processing': 0, 'completed': 0, 'failed': 0},
        }
        self.current_operation = "Idle"
        self.current_file = ""
        self.start_time = datetime.now()
        self.errors = []
        self.last_processed_count = 0
        self.last_update_time = datetime.now()

    def to_dict(self) -> dict:
        # Calculate overall totals across all phases
        total_files = 0
        processed_files = 0

        for phase, stats in self.phase_stats.items():
            # Total is everything we know about
            phase_total = stats['pending'] + stats['processing'] + stats['completed'] + stats['failed']
            total_files = max(total_files, phase_total)

            # Processed is completed + failed (we're done with them)
            phase_processed = stats['completed'] + stats['failed']
            processed_files = max(processed_files, phase_processed)

        # Calculate progress percentage
        if total_files > 0:
            progress_percent = round((processed_files / total_files) * 100, 1)
        else:
            progress_percent = 0

        # Calculate processing rate (files/sec)
        now = datetime.now()
        elapsed = (now - self.last_update_time).total_seconds()
        if elapsed > 0:
            processed_delta = processed_files - self.last_processed_count
            rate = round(processed_delta / elapsed, 2) if processed_delta > 0 else 0
        else:
            rate = 0

        # Update tracking for next calculation
        self.last_processed_count = processed_files
        self.last_update_time = now

        # Calculate ETA
        remaining_files = total_files - processed_files
        if rate > 0 and remaining_files > 0:
            eta_seconds = remaining_files / rate
        else:
            eta_seconds = None

        return {
            "phase_stats": self.phase_stats,
            "current_operation": self.current_operation,
            "current_file": self.current_file,
            "errors_count": len(self.errors),
            "total_files": total_files,
            "processed_files": processed_files,
            "progress_percent": progress_percent,
            "rate": rate,
            "eta_seconds": eta_seconds,
        }


class MediaIngestion:
    """Coordinates continuous media file ingestion and processing."""

    def __init__(self):
        # Lazy import ML services to avoid loading torch/open_clip at module level
        from clip_service import get_clip_service
        from face_detection_service import get_face_detection_service

        log.info("INGESTION INIT: Initializing MediaIngestion coordinator...")
        self.settings = get_settings()
        self.registry = get_database_registry()
        self.config_mgr = get_config_version_manager()

        # Build folder-to-profile mapping
        self.folder_to_profile = {}
        for profile in self.settings.profiles:
            for folder in profile.folders:
                self.folder_to_profile[folder.path] = profile.id
        log.info(f"INGESTION INIT: Folder-to-profile mapping: {self.folder_to_profile}")

        log.info("INGESTION INIT: Getting CLIP service...")
        self.clip_service = get_clip_service(
            self.settings.clip.model,
            self.settings.clip.pretrained,
            auto_load=False  # Load on first use
        )

        log.info("INGESTION INIT: Getting face detection service...")
        self.face_detection_service = get_face_detection_service(
            min_confidence=self.settings.face_detection.min_confidence,
            max_faces=self.settings.face_detection.max_faces,
            auto_load=False  # Load on first use
        )

        # VLM service is initialized lazily in init_async() to support Stimma Cloud
        # which requires async token resolution
        self.caption_service = None
        self._vlm_analysis_prompt = get_prompt("visual_analysis")
        self._vlm_parallelism = self.settings.captioning.parallelism

        self.progress = IngestionProgress()
        self.is_running = False
        self.is_paused = False  # Pause flag for background processing
        self.last_scan_time = None
        self.last_progress_update_time = None  # Rate limit progress stats updates
        self.last_stale_check_time = None  # Rate limit stale processing checks

        # Event-driven work signaling - worker sleeps until work is available
        self._work_available = asyncio.Event()

        # Flag for IPC-triggered rescan (set by _monitor_rescan_event)
        self._ipc_rescan_requested = False

        # Slot-based concurrency tracking - track active worker tasks
        self.active_workers = {
            'metadata': set(),
            'clip': set(),
            'face_detection': set(),
            'vlm_caption': set(),
        }

        # Slot limits per phase
        self.slots = {
            'metadata': 16,                                     # Increased for parallel I/O
            'clip': 4,                                          # ThreadPool workers
            'face_detection': self.settings.face_detection.parallelism,  # GPU workers
            'vlm_caption': self.settings.captioning.parallelism,
        }

        # Semaphore to limit concurrent SQLite writes (SQLite only allows one writer at a time)
        # This prevents blocking when many VLM tasks try to update status simultaneously
        self._db_write_semaphore = asyncio.Semaphore(10)

        # Timeout for stale 'processing' items (minutes)
        self.processing_timeout_minutes = 5

        # Multiprocessing event for pause/resume (set by run_continuous_ingestion)
        # When set: processing is paused. When cleared: processing runs.
        self._pause_event = None

        log.info("INGESTION INIT: MediaIngestion coordinator ready (VLM pending async init)")

    async def init_async(self):
        """Initialize async components like VLM service that require token resolution.

        This must be called before using the caption_service.
        """
        from llm_resolver import get_effective_llm_config

        log.info("INGESTION INIT: Resolving LLM config for captioning...")
        try:
            llm_config = await get_effective_llm_config('agent-fast')
            log.info(f"INGESTION INIT: Captioning config resolved: model={llm_config.get_model()}, base={llm_config.get_api_base()}")

            self.caption_service = VLMService(
                config=llm_config,
                analysis_prompt=self._vlm_analysis_prompt,
                max_parallelism=self._vlm_parallelism
            )
            log.info("INGESTION INIT: Visual analysis service initialized ✓")
        except ValueError:
            # No LLM config available (e.g. not logged in to Stimma Cloud and no local endpoint)
            # Captioning will be unavailable until config is reloaded after login
            log.warning("INGESTION INIT: No LLM config available - captioning disabled until cloud connection or endpoint configured")
            self.caption_service = None

        # Fix any inconsistent non-visual items from before defensive guards were added
        await self._fix_non_visual_statuses()

    async def _fix_non_visual_statuses(self):
        """Fix items where some AI phases are 'skipped' but others are still 'pending'.

        This handles items that were created before the defensive guards were added,
        where clip_status='skipped' but vlm_caption_status or face_detection_status
        are still 'pending'.
        """
        for profile in self.settings.profiles:
            try:
                db = await self._get_profile_db(profile.id)
            except ValueError:
                continue

            async with db.async_session_maker() as session:
                # Find items where any AI status is 'skipped' but others are still 'pending'
                result = await session.execute(
                    select(MediaItem).where(
                        and_(
                            MediaItem.deleted_at.is_(None),
                            or_(
                                # clip_status is 'skipped' but others are 'pending'
                                and_(
                                    MediaItem.clip_status == 'skipped',
                                    or_(
                                        MediaItem.face_detection_status == 'pending',
                                        MediaItem.vlm_caption_status == 'pending'
                                    )
                                ),
                                # face_detection_status is 'skipped' but vlm_caption is 'pending'
                                and_(
                                    MediaItem.face_detection_status == 'skipped',
                                    MediaItem.vlm_caption_status == 'pending'
                                )
                            )
                        )
                    )
                )
                items = result.scalars().all()

                if items:
                    log.info(f"INGESTION INIT: Fixing {len(items)} non-visual items with inconsistent statuses in profile {profile.id}")
                    for item in items:
                        # If any AI status is 'skipped', set all AI statuses to 'skipped'
                        if item.clip_status == 'skipped' or item.face_detection_status == 'skipped' or item.vlm_caption_status == 'skipped':
                            item.clip_status = 'skipped'
                            item.face_detection_status = 'skipped'
                            item.vlm_caption_status = 'skipped'
                    await session.commit()
                    log.info(f"INGESTION INIT: Fixed {len(items)} non-visual items in profile {profile.id}")

    async def _get_profile_db(self, profile_id: str):
        """Get database for a profile, initializing registry if needed."""
        # Ensure registry is initialized (for subprocess that runs separately from main app)
        if not self.registry._configs:
            for profile in self.settings.profiles:
                self.registry.register_profile(profile)
            # Initialize all databases
            await self.registry.init_all_databases()
        return self.registry.get_database(profile_id)

    def _get_active_profile_ids(self) -> list[str]:
        """Get currently configured profile IDs that are registered in the database registry."""
        return [
            profile.id
            for profile in self.settings.profiles
            if self.registry.has_profile(profile.id)
        ]

    def pause(self):
        """Pause background processing."""
        self.is_paused = True
        log.info("INGESTION: Background processing PAUSED")

    def resume(self):
        """Resume background processing."""
        self.is_paused = False
        log.info("INGESTION: Background processing RESUMED")

    def is_processing_paused(self) -> bool:
        """Check if processing is paused.

        Checks the multiprocessing event if available (for worker process),
        otherwise falls back to local is_paused flag (for web server process).
        """
        if self._pause_event is not None:
            return self._pause_event.is_set()
        return self.is_paused

    def _on_task_complete(self, phase: str):
        """Return a callback that removes task from active workers and signals work available.

        This is critical for dependent phases - when CLIP completes, VLM caption
        can now process those items. Without this signal, the main loop would sleep
        and never check for newly-eligible work.
        """
        def callback(task):
            self.active_workers[phase].discard(task)
            self._work_available.set()
        return callback

    async def _init_metadata_version(self):
        """Reset metadata for items with outdated config version across all profiles."""
        current_version = self.config_mgr.get_version('metadata')

        for profile in self.settings.profiles:
            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                # Find completed metadata items that have stale/NULL versions
                result = await session.execute(
                    select(MediaItem).where(
                        and_(
                            MediaItem.metadata_status == 'completed',
                            or_(
                                MediaItem.metadata_config_version != current_version,
                                MediaItem.metadata_config_version == None
                            )
                        )
                    )
                )
                items = result.scalars().all()

                if items:
                    for item in items:
                        # Reset to pending to trigger reprocessing with new version
                        item.metadata_status = 'pending'
                        item.metadata_config_version = None
                    await session.commit()
                    log.info(f"INGESTION INIT [{profile.id}]: Reset {len(items)} items for metadata reprocessing (version {current_version})")

    async def run_continuous(self):
        """Run continuous ingestion loop - event-driven, not polling.

        The worker sleeps until work is available, signaled via _work_available event.
        This eliminates idle CPU usage from constant database polling.
        """
        log.info("INGESTION: Starting event-driven processing loop")
        self.is_running = True

        # One-time initialization: update config versions for completed items
        await self._init_metadata_version()

        # Signal initial work check on startup
        self._work_available.set()

        while self.is_running:
            try:
                # Wait for work signal (with 5-minute timeout for periodic file scan)
                try:
                    await asyncio.wait_for(self._work_available.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    pass  # Timeout triggers periodic file scan

                self._work_available.clear()
                now = datetime.now()

                # Check for rescan request (from API via database flag OR IPC event)
                rescan_requested = await self._check_rescan_flag() or self._ipc_rescan_requested
                if self._ipc_rescan_requested:
                    self._ipc_rescan_requested = False  # Clear the IPC flag

                # File discovery: on timeout, first run, or API request
                if self.last_scan_time is None or rescan_requested or \
                   (now - self.last_scan_time).total_seconds() >= 300:
                    if rescan_requested:
                        log.info("INGESTION: Rescan requested via API/IPC")
                    self.progress.current_operation = "Scanning"
                    files_found = await self._scan_and_sync_files()
                    self.last_scan_time = now

                    if rescan_requested:
                        await self._clear_rescan_flag()

                    if files_found > 0:
                        log.info(f"INGESTION: Found {files_found} new/modified files")
                        self._work_available.set()

                # Reset stale items (rate limited to every 30s)
                if self.last_stale_check_time is None or \
                   (now - self.last_stale_check_time).total_seconds() >= 30.0:
                    stale_count = await self._reset_stale_processing()
                    self.last_stale_check_time = now
                    if stale_count > 0:
                        self._work_available.set()

                # Skip processing if paused (but allow metadata processing)
                paused = self.is_processing_paused()
                if paused:
                    log.debug("INGESTION: Paused - skipping AI processing, allowing metadata only")
                    # Still process metadata even when paused
                    await self._process_metadata()
                    await self._update_progress_stats()
                    continue

                # Process pending items
                work_done = await self._process_pending_items()

                if work_done:
                    self.progress.current_operation = "Processing"
                    self._work_available.set()  # More work likely available
                    await self._update_progress_stats()
                else:
                    self.progress.current_operation = "Idle"
                    # No work - will block on Event.wait() at top of loop

            except Exception as e:
                log.error(f"INGESTION WORKER: Error in processing loop: {e}", exc_info=True)
                await asyncio.sleep(30)  # Backoff on error

    async def _monitor_rescan_event(self, mp_event):
        """Monitor multiprocessing.Event from web server for rescan requests.

        This runs as a background task and signals _work_available when the
        web server sets the rescan event (e.g., from POST /api/rescan).
        """
        loop = asyncio.get_event_loop()
        # Wait for run_continuous to set is_running
        while not self.is_running:
            await asyncio.sleep(0.1)
        while self.is_running:
            try:
                # Check mp event in executor (it's a blocking call with timeout)
                signaled = await loop.run_in_executor(None, mp_event.wait, 1.0)
                if signaled:
                    mp_event.clear()
                    log.info("INGESTION: Rescan triggered via IPC event")
                    self._ipc_rescan_requested = True  # Set flag so main loop forces a scan
                    self._work_available.set()
            except Exception as e:
                log.error(f"INGESTION: Error monitoring rescan event: {e}")
                await asyncio.sleep(1.0)

    async def _monitor_process_pending_event(self, mp_event):
        """Monitor multiprocessing.Event for 'process pending items' requests.

        Unlike rescan, this just wakes the worker to process pending items WITHOUT
        triggering a filesystem scan. Used after generated images are inserted directly.
        """
        loop = asyncio.get_event_loop()
        # Wait for run_continuous to set is_running
        while not self.is_running:
            await asyncio.sleep(0.1)
        while self.is_running:
            try:
                # Check mp event in executor (it's a blocking call with timeout)
                signaled = await loop.run_in_executor(None, mp_event.wait, 1.0)
                if signaled:
                    mp_event.clear()
                    log.info("INGESTION: Process-pending triggered via IPC event")
                    # Just wake the worker - don't set _ipc_rescan_requested
                    self._work_available.set()
            except Exception as e:
                log.error(f"INGESTION: Error monitoring process-pending event: {e}")
                await asyncio.sleep(1.0)

    async def _monitor_reload_config_event(self, mp_event):
        """Monitor multiprocessing.Event for config reload requests.

        When profiles are added/removed in the main process, this event is signaled
        so we can reload config and update our registry to match.
        """
        loop = asyncio.get_event_loop()
        # Wait for run_continuous to set is_running
        while not self.is_running:
            await asyncio.sleep(0.1)
        while self.is_running:
            try:
                # Check mp event in executor (it's a blocking call with timeout)
                signaled = await loop.run_in_executor(None, mp_event.wait, 1.0)
                if signaled:
                    mp_event.clear()
                    log.info("INGESTION: Config reload triggered via IPC event")
                    await self._reload_config()
            except Exception as e:
                log.error(f"INGESTION: Error monitoring reload-config event: {e}")
                await asyncio.sleep(1.0)

    async def _reload_config(self):
        """Reload config and update registry to match current profiles."""
        from config import reload_settings

        log.info("INGESTION: Reloading config...")

        # Reload settings from disk
        new_settings = reload_settings()

        # Find added and removed profiles
        old_profile_ids = {p.id for p in self.settings.profiles}
        new_profile_ids = {p.id for p in new_settings.profiles}

        removed_ids = old_profile_ids - new_profile_ids
        added_ids = new_profile_ids - old_profile_ids

        # Unregister removed profiles
        for profile_id in removed_ids:
            log.info(f"INGESTION: Unregistering removed profile: {profile_id}")
            await self.registry.unregister_profile(profile_id)

        # Register new profiles (run migrations first)
        from utils.migrations import run_migrations_for_profile
        for profile in new_settings.profiles:
            if profile.id in added_ids:
                log.info(f"INGESTION: Registering new profile: {profile.id}")
                run_migrations_for_profile(profile.id, profile.database)
                self.registry.register_profile(profile)
                await self.registry.init_database(profile.id)

        # Rebuild folder-to-profile mapping
        self.folder_to_profile = {}
        for profile in new_settings.profiles:
            for folder in profile.folders:
                self.folder_to_profile[folder.path] = profile.id

        # Update settings reference
        self.settings = new_settings

        # If profiles were added, trigger work check and file scan
        if added_ids:
            log.info(f"INGESTION: New profiles added, triggering scan: {added_ids}")
            self.last_scan_time = None  # Force file scan on next loop iteration
            self._work_available.set()

        log.info(f"INGESTION: Config reloaded. Profiles: {list(new_profile_ids)}, Folders: {list(self.folder_to_profile.keys())}")

    async def _check_rescan_flag(self) -> bool:
        """Check if a rescan has been requested via the API in any active profile DB."""
        from database import ControlFlag
        from sqlalchemy import select

        try:
            for profile_id in self._get_active_profile_ids():
                db = await self._get_profile_db(profile_id)
                async with db.async_session_maker() as session:
                    result = await session.execute(
                        select(ControlFlag).where(ControlFlag.key == 'rescan_requested')
                    )
                    flag = result.scalar_one_or_none()
                    if flag is not None and flag.value == 'true':
                        return True
            return False
        except Exception as e:
            log.error(f"Failed to check rescan flag: {e}")
            return False

    async def _clear_rescan_flag(self):
        """Clear the rescan requested flag from all active profile DBs."""
        from database import ControlFlag
        from sqlalchemy import delete

        try:
            for profile_id in self._get_active_profile_ids():
                db = await self._get_profile_db(profile_id)
                async with db.async_session_maker() as session:
                    await session.execute(
                        delete(ControlFlag).where(ControlFlag.key == 'rescan_requested')
                    )
                    await session.commit()
            log.info("INGESTION: Rescan flag cleared")
        except Exception as e:
            log.error(f"Failed to clear rescan flag: {e}")

    async def _update_progress_stats(self):
        """Update progress statistics for all phases across all profiles.

        Uses a single query per profile to count all phase/status combinations efficiently.
        """
        from sqlalchemy import func, case, literal_column

        # Reset counters before aggregating
        for phase in PHASES:
            for status in ['pending', 'processing', 'completed', 'failed']:
                self.progress.phase_stats[phase][status] = 0

        # Aggregate stats from all profile databases with a single query per profile
        for profile in self.settings.profiles:
            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                # Build a single query that counts all phase/status combinations
                # Using conditional aggregation: SUM(CASE WHEN status = 'x' THEN 1 ELSE 0 END)
                columns = []
                for phase in PHASES:
                    status_col = getattr(MediaItem, f"{phase}_status")
                    for status in ['pending', 'processing', 'completed', 'failed']:
                        columns.append(
                            func.sum(case((status_col == status, 1), else_=0)).label(f"{phase}_{status}")
                        )

                result = await session.execute(select(*columns))
                row = result.one()

                # Parse results back into phase_stats
                for phase in PHASES:
                    for status in ['pending', 'processing', 'completed', 'failed']:
                        count = getattr(row, f"{phase}_{status}") or 0
                        self.progress.phase_stats[phase][status] += count

        # Add the count of in-memory active workers to 'processing' counts
        for phase in PHASES:
            self.progress.phase_stats[phase]['processing'] += len(self.active_workers[phase])

        # Note: WebSocket broadcasting happens from the main web server process
        # via the monitor_processing_stats background task, not from this worker process.
        # This is because the ingestion worker runs in a separate process and can't
        # access WebSocket connections held by the main process.

    async def _scan_and_sync_files(self) -> int:
        """
        Profile-aware file discovery - scans each profile's folders and syncs to the correct database.
        Returns the total number of new files found across all profiles.
        """
        log.debug("FAST DISCOVERY: Starting profile-aware file scan...")
        total_new = 0
        for profile in self.settings.profiles:
            total_new += await self._scan_and_sync_profile(profile.id)
        return total_new

    async def _scan_and_sync_profile(self, profile_id: str) -> int:
        """
        Scan and sync files for a single profile.
        Returns the number of new files found.

        Only removes files that are in folders we scanned - safe if folder is
        temporarily unavailable, removed from config, or empty.
        """
        profile_folders = self.settings.get_folders_for_profile(profile_id)
        if not profile_folders:
            log.debug(f"FAST DISCOVERY [{profile_id}]: No folders configured, skipping")
            return 0

        folder_paths = [f.path for f in profile_folders]
        log.debug(f"FAST DISCOVERY [{profile_id}]: Scanning {len(folder_paths)} folders...")

        # Step 1: Scan filesystem into RAM
        scanned_files = await fast_scan_directories(folder_paths)
        log.debug(f"FAST DISCOVERY [{profile_id}]: Loaded {len(scanned_files)} files into RAM")

        # Step 2: Get database for this profile
        db = await self._get_profile_db(profile_id)

        async with db.async_session_maker() as session:
            # Get all existing files in this profile's DB
            result = await session.execute(
                select(MediaItem.file_path, MediaItem.modified_date)
            )
            existing_files = {row[0]: row[1] for row in result.fetchall()}
            log.debug(f"FAST DISCOVERY [{profile_id}]: Found {len(existing_files)} existing files in DB")

            # Step 3: Diff in RAM
            new_files = []
            modified_files = []
            scanned_paths = set()

            for file_info in scanned_files:
                file_path = file_info['file_path']
                scanned_paths.add(file_path)

                if file_path not in existing_files:
                    # New file
                    new_files.append({
                        'file_path': file_path,
                        'file_hash': '',
                        'file_size': file_info['file_size'],
                        'file_format': file_info['file_format'],
                        'created_date': file_info['created_date'],
                        'modified_date': file_info['modified_date'],
                        'metadata_status': 'pending',
                        'width': 0,
                        'height': 0,
                        'megapixels': 0.0,
                    })
                else:
                    # Check if modified - use 1 second tolerance to avoid floating-point/microsecond precision issues
                    # SQLite may truncate or round microseconds, causing false positives on each scan
                    db_mtime = existing_files[file_path]
                    file_mtime = file_info['modified_date']
                    if db_mtime is not None and file_mtime is not None:
                        time_diff = (file_mtime - db_mtime).total_seconds()
                        if time_diff > 1.0:  # More than 1 second newer = actually modified
                            modified_files.append((file_path, file_mtime))

            log.debug(f"FAST DISCOVERY [{profile_id}]: {len(new_files)} new, {len(modified_files)} modified")

            # Step 4: Batch insert new files
            if new_files:
                log.info(f"FAST DISCOVERY [{profile_id}]: Batch inserting {len(new_files)} new files...")
                await self._insert_batch(session, new_files)
                log.debug(f"FAST DISCOVERY [{profile_id}]: Batch insert complete ✓")

                # Apply auto-markers to new files
                new_file_paths = [f['file_path'] for f in new_files]
                result = await session.execute(
                    select(MediaItem.id, MediaItem.file_path).where(MediaItem.file_path.in_(new_file_paths))
                )
                new_media_items = [(row[0], row[1]) for row in result.fetchall()]
                if new_media_items:
                    log.debug(f"FAST DISCOVERY [{profile_id}]: Applying auto-markers to {len(new_media_items)} new files...")
                    await sync_auto_markers_for_items(session, new_media_items, profile_folders)

            # Step 5: Reset modified files
            if modified_files:
                log.info(f"FAST DISCOVERY [{profile_id}]: Marking {len(modified_files)} modified files for re-processing...")
                for file_path, file_mtime in modified_files:
                    result = await session.execute(
                        select(MediaItem).where(MediaItem.file_path == file_path)
                    )
                    item = result.scalar_one_or_none()
                    if item:
                        item.modified_date = file_mtime
                        item.metadata_status = 'pending'
                        item.clip_status = 'pending'
                        item.vlm_caption_status = 'pending'
                        item.clip_embedding = None
                        item.vlm_caption = None
                        item.keywords = None
                        item.raw_metadata = None
                        item.extracted_prompt = None

            # Step 6: Mark missing files as unavailable (SOFT - preserves user data)
            # This protects against data loss if a folder is temporarily unavailable
            files_in_scanned_folders = {
                path for path in existing_files.keys()
                if any(path.startswith(folder_path) for folder_path in folder_paths)
            }
            files_now_missing = files_in_scanned_folders - scanned_paths

            unavailable_count = 0
            if files_now_missing:
                log.info(f"FAST DISCOVERY [{profile_id}]: Marking {len(files_now_missing)} files as unavailable...")
                for file_path in files_now_missing:
                    result = await session.execute(
                        select(MediaItem).where(MediaItem.file_path == file_path)
                    )
                    item = result.scalar_one_or_none()
                    if item and not item.file_unavailable:
                        item.file_unavailable = True
                        item.file_unavailable_since = datetime.utcnow()
                        unavailable_count += 1
                        log.info(f"UNAVAILABLE: {file_path}")

            # Step 7: Restore files that were unavailable but now exist
            # Get all unavailable items in scanned folders
            restored_count = 0
            result = await session.execute(
                select(MediaItem).where(MediaItem.file_unavailable == True)
            )
            unavailable_items = result.scalars().all()

            for item in unavailable_items:
                # Only check items in folders we scanned
                if any(item.file_path.startswith(folder_path) for folder_path in folder_paths):
                    if item.file_path in scanned_paths:
                        item.file_unavailable = False
                        item.file_unavailable_since = None
                        restored_count += 1
                        log.info(f"RESTORED: {item.file_path}")

            # Step 8: Sync auto-markers for all existing files (handles config changes)
            # Only sync if any folder has markers configured
            has_folder_markers = any(f.markers for f in profile_folders)
            log.debug(f"FAST DISCOVERY [{profile_id}]: has_folder_markers={has_folder_markers}, folders={[(f.path, f.markers) for f in profile_folders]}")
            if has_folder_markers:
                log.debug(f"FAST DISCOVERY [{profile_id}]: Syncing auto-markers for existing files...")
                # Get all existing items in scanned folders (batch to avoid SQLite parameter limit)
                existing_paths = list(scanned_paths)
                existing_media_items = []
                batch_size = 500
                for i in range(0, len(existing_paths), batch_size):
                    batch = existing_paths[i:i+batch_size]
                    result = await session.execute(
                        select(MediaItem.id, MediaItem.file_path).where(MediaItem.file_path.in_(batch))
                    )
                    existing_media_items.extend([(row[0], row[1]) for row in result.fetchall()])
                if existing_media_items:
                    await sync_auto_markers_for_items(session, existing_media_items, profile_folders)
                    log.debug(f"FAST DISCOVERY [{profile_id}]: Auto-marker sync complete for {len(existing_media_items)} files")

            await session.commit()
            # Only log at info level if something actually changed
            changes = len(new_files) + len(modified_files) + unavailable_count + restored_count
            if changes > 0:
                log.info(f"FAST DISCOVERY [{profile_id}]: Added {len(new_files)}, updated {len(modified_files)}, unavailable {unavailable_count}, restored {restored_count}")
            else:
                log.debug(f"FAST DISCOVERY [{profile_id}]: No changes")
            return len(new_files) + len(modified_files)

    def _check_file_modified_simple(self, file_path: Path, db_mtime: Optional[datetime]) -> tuple[bool, Optional[datetime]]:
        """Quick timestamp check - runs in thread pool. Returns (modified, mtime)."""
        try:
            file_mtime = datetime.utcfromtimestamp(file_path.stat().st_mtime)
            # Use 1 second tolerance to avoid floating-point/microsecond precision issues
            if db_mtime is None:
                is_modified = True
            else:
                time_diff = (file_mtime - db_mtime).total_seconds()
                is_modified = time_diff > 1.0
            return (is_modified, file_mtime)
        except Exception as e:
            log.error(f"Error checking file {file_path}: {e}")
            return (False, None)

    async def _insert_batch(self, session: AsyncSession, files_metadata: list[dict]):
        """Insert a batch of files into the database."""
        for metadata in files_metadata:
            # Add random sort value for stable random sorting
            metadata['random_sort_value'] = random.random()
            item = MediaItem(**metadata)
            session.add(item)
        await session.flush()

    async def _process_pending_items(self) -> bool:
        """Process items needing work for each phase IN PARALLEL. Returns True if any work was done."""
        # Run all phases concurrently - each will grab what it needs and process
        # Metadata must run first to unblock other phases
        results = await asyncio.gather(
            self._process_metadata(),
            self._process_clip(),
            self._process_face_detection(),
            self._process_vlm_captions(),
            return_exceptions=True
        )

        # Count total processed and log any exceptions
        phase_names = ['metadata', 'clip', 'face_detection', 'vlm_caption']
        total_processed = 0
        phase_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.error(f"Error in phase {phase_names[i]}: {result}", exc_info=result)
                phase_results.append(f"{phase_names[i]}=ERROR")
            else:
                total_processed += result
                phase_results.append(f"{phase_names[i]}={result}")

        if total_processed > 0:
            log.debug(f"PROCESS_PENDING: {', '.join(phase_results)} -> total={total_processed}")
            # TODO: Track ingestion_completed / ingestion_failed telemetry here.
            # Needs per-phase success/failure counts from the results to be meaningful.
            # E.g.: get_telemetry_client().track("ingestion_completed", {"count": total_processed})
        return total_processed > 0

    async def _reset_stale_processing(self) -> int:
        """Reset items stuck in 'processing' status due to crashes or timeouts across all profiles.
        Returns the number of items reset."""
        stale_threshold = datetime.utcnow() - timedelta(minutes=self.processing_timeout_minutes)
        total_reset_count = 0

        for profile in self.settings.profiles:
            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                reset_count = 0
                for phase in PHASES:
                    status_col = f"{phase}_status"
                    timestamp_col = f"{phase}_processed_at"

                    # Find stale processing items
                    result = await session.execute(
                        select(MediaItem).where(
                            and_(
                                getattr(MediaItem, status_col) == 'processing',
                                or_(
                                    getattr(MediaItem, timestamp_col) < stale_threshold,
                                    getattr(MediaItem, timestamp_col) == None
                                )
                            )
                        )
                    )
                    stale_items = result.scalars().all()

                    # Reset to pending
                    for item in stale_items:
                        setattr(item, status_col, 'pending')
                        reset_count += 1

                if reset_count > 0:
                    await session.commit()
                    total_reset_count += reset_count

        if total_reset_count > 0:
            log.info(f"RECOVERY: Reset {total_reset_count} stale processing items across all profiles")

        return total_reset_count

    async def _get_backoff_time(self, retry_count: int) -> datetime:
        """Get backoff time for retry."""
        if retry_count >= len(RETRY_BACKOFF):
            backoff_seconds = RETRY_BACKOFF[-1]
        else:
            backoff_seconds = RETRY_BACKOFF[retry_count]
        return datetime.utcnow() - timedelta(seconds=backoff_seconds)

    async def _process_metadata(self):
        """
        Process metadata extraction phase - hash, dimensions, EXIF.
        This is the heavy I/O that was previously done during file discovery.
        Processes items across all profiles.
        """
        # Calculate available slots
        available_slots = self.slots['metadata'] - len(self.active_workers['metadata'])
        if available_slots <= 0:
            return 0

        total_processed = 0
        tasks = []

        # Process items from each profile's database
        for profile in self.settings.profiles:
            if available_slots <= 0:
                break

            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem)
                    .where(and_(
                        MediaItem.metadata_status == 'pending',
                        MediaItem.deleted_at.is_(None),  # Skip trashed items
                        MediaItem.file_unavailable != True,  # Skip missing files
                    ))
                    .limit(available_slots)
                )
                items = result.scalars().all()

                if not items:
                    continue

                # Mark as processing with timestamp for stale detection
                for item in items:
                    item.metadata_status = 'processing'
                    item.metadata_processed_at = datetime.utcnow()
                await session.commit()

                # Create tasks for this profile's items
                for item in items:
                    task = asyncio.create_task(self._extract_metadata_for_item(profile.id, item.id, item.file_path))
                    self.active_workers['metadata'].add(task)
                    tasks.append(task)

                available_slots -= len(items)
                total_processed += len(items)

        if tasks:
            # Wait for completion
            await asyncio.gather(*tasks, return_exceptions=True)

            # Remove from active workers
            for task in tasks:
                self.active_workers['metadata'].discard(task)

            # Signal work available for dependent phases (CLIP, Face, VLM)
            # These phases depend on metadata being complete, so they may now have work
            self._work_available.set()

        return total_processed

    async def _extract_metadata_for_item(self, profile_id: str, item_id: int, file_path_str: str):
        """Extract metadata for a single item (runs in background)."""
        try:
            db = await self._get_profile_db(profile_id)
        except ValueError:
            # Profile was removed while task was queued - expected during config reload
            log.debug(f"METADATA: Skipping item {item_id}, profile '{profile_id}' was removed")
            return
        try:
            file_path = Path(file_path_str)
            loop = asyncio.get_event_loop()

            # Extract metadata (hash, dimensions) in thread pool
            metadata = await loop.run_in_executor(
                _io_executor,
                extract_metadata,
                file_path
            )

            if metadata is None:
                raise ValueError("Failed to extract metadata")

            # Extract EXIF prompt if available
            raw_metadata, parsed_prompt = await loop.run_in_executor(
                _io_executor,
                extract_prompt_from_exif,
                file_path
            )

            # Extract stimma generation metadata if available
            stimma_metadata = await loop.run_in_executor(
                _io_executor,
                extract_stimma_metadata,
                file_path
            )

            # Update database
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == item_id)
                )
                item = result.scalar_one_or_none()

                if item:
                    # Update metadata fields
                    item.file_hash = metadata['file_hash']
                    item.width = metadata['width']
                    item.height = metadata['height']
                    item.megapixels = metadata['megapixels']
                    item.duration = metadata.get('duration')

                    # Update audio-specific metadata
                    item.audio_sample_rate = metadata.get('audio_sample_rate')
                    item.audio_channels = metadata.get('audio_channels')
                    item.audio_bit_depth = metadata.get('audio_bit_depth')
                    item.audio_bitrate = metadata.get('audio_bitrate')
                    item.audio_codec = metadata.get('audio_codec')

                    # Update EXIF if found
                    if raw_metadata:
                        item.raw_metadata = raw_metadata
                    if parsed_prompt:
                        item.extracted_prompt = parsed_prompt

                    # Update generation metadata if found
                    if stimma_metadata:
                        item.generation_metadata = stimma_metadata
                    elif raw_metadata and not item.generation_metadata:
                        # Parse external metadata (A1111, etc.) if no stimma metadata
                        from exif_extractor import parse_external_metadata
                        parsed_external = parse_external_metadata(raw_metadata)
                        if parsed_external:
                            item.generation_metadata = json.dumps(parsed_external)

                    # Mark metadata as completed with current config version
                    item.metadata_status = 'completed'
                    item.metadata_config_version = self.config_mgr.get_version('metadata')
                    item.metadata_processed_at = datetime.utcnow()

                    # Check if this file type should skip AI processing
                    # Audio and structured types (text, sets, grids) don't have visual content
                    file_ext = file_path.suffix.lower()
                    # Also check compound extensions for structured types
                    file_name = file_path.name.lower()
                    is_non_visual = (
                        file_ext in AUDIO_EXTENSIONS or
                        any(file_name.endswith(ext) for ext in STRUCTURED_EXTENSIONS)
                    )

                    if is_non_visual:
                        # Skip all AI processing phases
                        item.clip_status = 'skipped'
                        item.face_detection_status = 'skipped'
                        item.vlm_caption_status = 'skipped'
                        log.debug(f"METADATA: Skipping AI processing for non-visual type: {file_path_str}")

                        # For structured types, store parsed JSON in raw_metadata
                        if metadata.get('raw_metadata'):
                            item.raw_metadata = metadata['raw_metadata']

                    await session.commit()
                    log.debug(f"METADATA: Extracted for {file_path_str}")

        except Exception as e:
            log.error(f"METADATA: Failed to extract for {file_path_str}: {e}")
            # Mark as failed
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == item_id)
                )
                item = result.scalar_one_or_none()
                if item:
                    item.metadata_status = 'failed'
                    item.metadata_error = str(e)
                    item.metadata_retry_count += 1

                    # Also mark downstream phases as skipped since metadata failed
                    item.clip_status = 'failed'
                    item.vlm_caption_status = 'failed'

                    await session.commit()

    async def _process_clip(self):
        """Process CLIP embeddings using slot-based concurrency across all profiles."""
        # Check if CLIP is enabled
        if not self.settings.clip.enabled:
            return 0

        # Calculate available slots
        available_slots = self.slots['clip'] - len(self.active_workers['clip'])
        if available_slots <= 0:
            return 0

        # Select work (newest first)
        current_version = self.config_mgr.get_version('clip')
        backoff_time = await self._get_backoff_time(0)
        total_processed = 0

        for profile in self.settings.profiles:
            if available_slots <= 0:
                break

            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem).where(
                        and_(
                            # DEPENDENCY: Only process items with completed metadata
                            MediaItem.metadata_status == 'completed',
                            MediaItem.deleted_at.is_(None),  # Skip trashed items
                            MediaItem.file_unavailable != True,  # Skip missing files
                            or_(
                                # Process pending items regardless of version
                                MediaItem.clip_status == 'pending',
                                # Also process failed items with retry logic
                                and_(
                                    MediaItem.clip_status == 'failed',
                                    MediaItem.clip_retry_count < MAX_RETRIES,
                                    or_(
                                        MediaItem.clip_processed_at == None,
                                        MediaItem.clip_processed_at < backoff_time
                                    )
                                ),
                                # Reprocess completed items if config changed
                                and_(
                                    MediaItem.clip_status == 'completed',
                                    or_(
                                        MediaItem.clip_config_version != current_version,
                                        MediaItem.clip_config_version == None
                                    )
                                )
                            ),
                            MediaItem.clip_status != 'processing'  # Exclude in-flight items
                        )
                    ).order_by(MediaItem.indexed_date.desc()).limit(available_slots)
                )
                items = result.scalars().all()

            log.debug(f"CLIP: profile={profile.id}, found {len(items)} items, slots={available_slots}")
            if not items:
                continue

            # Log what we're processing and why
            for item in items:
                if item.clip_status == 'completed':
                    log.info(f"CLIP: Reprocessing {item.file_path} due to config version change (has: {item.clip_config_version}, need: {current_version})")
                else:
                    log.debug(f"CLIP: Processing {item.file_path} (status: {item.clip_status})")

            # Spawn workers for each item
            for item in items:
                task = asyncio.create_task(self._process_one_clip(profile.id, item.id))
                self.active_workers['clip'].add(task)
                # Signal work available when task completes (for dependent phases)
                task.add_done_callback(self._on_task_complete('clip'))

            available_slots -= len(items)
            total_processed += len(items)

        return total_processed

    async def _process_one_clip(self, profile_id: str, item_id: int):
        """Process a single CLIP embedding."""
        try:
            db = await self._get_profile_db(profile_id)
        except ValueError:
            # Profile was removed while task was queued - expected during config reload
            log.debug(f"CLIP: Skipping item {item_id}, profile '{profile_id}' was removed")
            return
        current_version = self.config_mgr.get_version('clip')

        try:
            # Mark as processing
            async with db.async_session_maker() as session:
                result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                item = result.scalar_one_or_none()
                if not item or item.clip_status == 'processing':
                    return  # Already being processed or deleted

                file_path = item.file_path
                file_path_obj = Path(file_path)

                # Defensive check: skip non-visual media types (audio, text, sets, grids)
                # These should already be marked 'skipped' by metadata processing, but check anyway
                # Set all AI phase statuses to 'skipped' to prevent them being counted as pending
                if not is_visual_media(file_path_obj):
                    item.clip_status = 'skipped'
                    item.face_detection_status = 'skipped'
                    item.vlm_caption_status = 'skipped'
                    await session.commit()
                    log.debug(f"CLIP: Skipping non-visual media (all AI phases): {file_path}")
                    return

                item.clip_status = 'processing'
                item.clip_processed_at = datetime.utcnow()
                await session.commit()

            # Process (outside session to avoid holding locks)

            # For videos, extract first frame
            video_frame = None
            if file_path_obj.suffix.lower() in VIDEO_EXTENSIONS:
                image = await self._extract_video_frame(file_path_obj)
                video_frame = image  # Track for cleanup
            else:
                image = file_path_obj

            try:
                # Generate embedding (CPU-bound, use thread pool)
                loop = asyncio.get_event_loop()
                embedding = await loop.run_in_executor(
                    _io_executor,
                    self.clip_service.encode_image,
                    image
                )
            finally:
                # Close video frame if we extracted one
                if video_frame is not None:
                    video_frame.close()

            # Update result
            async with db.async_session_maker() as session:
                result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                item = result.scalar_one_or_none()
                if item:
                    item.set_embedding(embedding)
                    item.clip_status = 'completed'
                    item.clip_config_version = current_version
                    item.clip_processed_at = datetime.utcnow()
                    item.clip_error = None
                    await session.commit()
                    log.debug(f"CLIP: ✓ {file_path}")

        except Exception as e:
            log.error(f"CLIP: ✗ {file_path}: {e}")
            async with db.async_session_maker() as session:
                result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                item = result.scalar_one_or_none()
                if item:
                    item.clip_status = 'failed'
                    item.clip_error = str(e)
                    item.clip_retry_count += 1
                    item.clip_processed_at = datetime.utcnow()
                    await session.commit()


    async def _process_face_detection(self):
        """Process face detection using slot-based concurrency across all profiles."""
        # Check if face detection is enabled
        if not self.settings.face_detection.enabled:
            return 0

        # Calculate available slots
        available_slots = self.slots['face_detection'] - len(self.active_workers['face_detection'])
        if available_slots <= 0:
            return 0

        # Select work (newest first)
        current_version = self.config_mgr.get_version('face_detection')
        backoff_time = await self._get_backoff_time(0)
        total_processed = 0

        for profile in self.settings.profiles:
            if available_slots <= 0:
                break

            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem).where(
                        and_(
                            # DEPENDENCY: Only process items with completed metadata
                            MediaItem.metadata_status == 'completed',
                            MediaItem.deleted_at.is_(None),  # Skip trashed items
                            MediaItem.file_unavailable != True,  # Skip missing files
                            or_(
                                # Process pending items regardless of version
                                MediaItem.face_detection_status == 'pending',
                                # Also process failed items with retry logic
                                and_(
                                    MediaItem.face_detection_status == 'failed',
                                    MediaItem.face_detection_retry_count < MAX_RETRIES,
                                    or_(
                                        MediaItem.face_detection_processed_at == None,
                                        MediaItem.face_detection_processed_at < backoff_time
                                    )
                                ),
                                # Reprocess completed items if config changed
                                and_(
                                    MediaItem.face_detection_status == 'completed',
                                    or_(
                                        MediaItem.face_detection_config_version != current_version,
                                        MediaItem.face_detection_config_version == None
                                    )
                                )
                            ),
                            MediaItem.face_detection_status != 'processing'  # Exclude in-flight items
                        )
                    ).order_by(MediaItem.indexed_date.desc()).limit(available_slots)
                )
                items = result.scalars().all()

            if not items:
                continue

            # Log what we're processing and why
            for item in items:
                if item.face_detection_status == 'completed':
                    log.info(f"FACE DETECTION: Reprocessing {item.file_path} due to config version change (has: {item.face_detection_config_version}, need: {current_version})")
                else:
                    log.debug(f"FACE DETECTION: Processing {item.file_path} (status: {item.face_detection_status})")

            # Spawn workers for each item
            for item in items:
                task = asyncio.create_task(self._process_one_face_detection(profile.id, item.id))
                self.active_workers['face_detection'].add(task)
                # Signal work available when task completes (for dependent phases)
                task.add_done_callback(self._on_task_complete('face_detection'))

            available_slots -= len(items)
            total_processed += len(items)

        return total_processed

    async def _process_one_face_detection(self, profile_id: str, item_id: int):
        """Process face detection for a single image or video (first frame)."""
        try:
            db = await self._get_profile_db(profile_id)
        except ValueError:
            # Profile was removed while task was queued - expected during config reload
            log.debug(f"FACE: Skipping item {item_id}, profile '{profile_id}' was removed")
            return
        current_version = self.config_mgr.get_version('face_detection')

        try:
            # Mark as processing
            async with db.async_session_maker() as session:
                result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                item = result.scalar_one_or_none()
                if not item or item.face_detection_status == 'processing':
                    return  # Already being processed or deleted

                file_path = item.file_path
                file_path_obj = Path(file_path)

                # Defensive check: skip non-visual media types (audio, text, sets, grids)
                # These should already be marked 'skipped' by metadata processing, but check anyway
                if not is_visual_media(file_path_obj):
                    item.face_detection_status = 'skipped'
                    await session.commit()
                    log.debug(f"FACE DETECTION: Skipping non-visual media: {file_path}")
                    return

                item.face_detection_status = 'processing'
                item.face_detection_processed_at = datetime.utcnow()
                await session.commit()

            # Process (outside session to avoid holding locks)

            # For videos, extract first frame
            video_frame = None
            if file_path_obj.suffix.lower() in VIDEO_EXTENSIONS:
                image = await self._extract_video_frame(file_path_obj)
                video_frame = image  # Track for cleanup
            else:
                image = file_path_obj

            try:
                # Detect faces (CPU/GPU-bound, use thread pool)
                loop = asyncio.get_event_loop()
                faces = await loop.run_in_executor(
                    _io_executor,
                    self.face_detection_service.detect_faces,
                    image
                )
            finally:
                # Close video frame if we extracted one
                if video_frame is not None:
                    video_frame.close()

            # Delete old face detections for this media item
            async with db.async_session_maker() as session:
                from sqlalchemy import delete
                await session.execute(
                    delete(Face).where(Face.media_id == item_id)
                )
                await session.commit()

            # Store new face detections
            if faces and len(faces) > 0:
                async with db.async_session_maker() as session:
                    for face_data in faces:
                        face = Face(
                            media_id=item_id,
                            bbox_x=face_data['bbox']['x'],
                            bbox_y=face_data['bbox']['y'],
                            bbox_width=face_data['bbox']['width'],
                            bbox_height=face_data['bbox']['height'],
                            confidence=face_data['confidence'],
                            landmarks=face_data.get('landmarks')
                        )
                        # Set embedding if available
                        if face_data.get('embedding') is not None:
                            face.set_embedding(face_data['embedding'])

                        session.add(face)
                    await session.commit()

            # Update result
            async with db.async_session_maker() as session:
                result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                item = result.scalar_one_or_none()
                if item:
                    item.face_detection_status = 'completed'
                    item.face_detection_config_version = current_version
                    item.face_detection_processed_at = datetime.utcnow()
                    item.face_detection_error = None
                    await session.commit()
                    log.debug(f"FACE DETECTION: ✓ {file_path} ({len(faces)} faces)")

        except Exception as e:
            log.error(f"FACE DETECTION: ✗ {file_path}: {e}")
            async with db.async_session_maker() as session:
                result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                item = result.scalar_one_or_none()
                if item:
                    item.face_detection_status = 'failed'
                    item.face_detection_error = str(e)
                    item.face_detection_retry_count += 1
                    item.face_detection_processed_at = datetime.utcnow()
                    await session.commit()


    async def _process_vlm_captions(self):
        """Process VLM captions using slot-based concurrency across all profiles."""
        # Check if captioning is enabled and VLM service is available
        if not self.settings.captioning.enabled or self.caption_service is None:
            return 0

        # Calculate available slots
        available_slots = self.slots['vlm_caption'] - len(self.active_workers['vlm_caption'])
        if available_slots <= 0:
            return 0

        # Select work (newest first)
        current_version = self.config_mgr.get_version('vlm_caption')
        total_processed = 0

        for profile in self.settings.profiles:
            if available_slots <= 0:
                break

            db = await self._get_profile_db(profile.id)
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(MediaItem).where(
                        and_(
                            MediaItem.metadata_status == 'completed',  # Dependency: need metadata first
                            MediaItem.clip_status == 'completed',  # Dependency
                            MediaItem.deleted_at.is_(None),  # Skip trashed items
                            MediaItem.file_unavailable != True,  # Skip missing files
                            or_(
                                # Process pending items regardless of version
                                MediaItem.vlm_caption_status == 'pending',
                                # Reprocess completed items if config changed
                                and_(
                                    MediaItem.vlm_caption_status == 'completed',
                                    or_(
                                        MediaItem.vlm_caption_config_version != current_version,
                                        MediaItem.vlm_caption_config_version == None
                                    )
                                )
                            ),
                            MediaItem.vlm_caption_status != 'processing'  # Exclude in-flight
                        )
                    ).order_by(MediaItem.indexed_date.desc()).limit(available_slots)
                )
                items = result.scalars().all()

            if not items:
                continue

            # Spawn workers for each item
            for item in items:
                task = asyncio.create_task(self._process_one_vlm_caption(profile.id, item.id))
                self.active_workers['vlm_caption'].add(task)
                # Signal work available when task completes (for dependent phases)
                task.add_done_callback(self._on_task_complete('vlm_caption'))
            # Yield to let tasks start running
            await asyncio.sleep(0)

            available_slots -= len(items)
            total_processed += len(items)

        return total_processed

    async def _process_one_vlm_caption(self, profile_id: str, item_id: int):
        """Process visual analysis (caption + keywords) for a single item."""
        try:
            db = await self._get_profile_db(profile_id)
        except ValueError:
            # Profile was removed while task was queued - expected during config reload
            log.debug(f"VLM: Skipping item {item_id}, profile '{profile_id}' was removed")
            return
        current_version = self.config_mgr.get_version('vlm_caption')
        file_path = None

        try:
            # Mark as processing (use semaphore to limit concurrent DB writes)
            async with self._db_write_semaphore:
                async with db.async_session_maker() as session:
                    result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                    item = result.scalar_one_or_none()
                    if not item or item.vlm_caption_status == 'processing':
                        return  # Already being processed or deleted

                    file_path = item.file_path
                    file_path_obj = Path(file_path)

                    # Defensive check: skip non-visual media types (audio, text, sets, grids)
                    # These should already be marked 'skipped' by metadata processing, but check anyway
                    if not is_visual_media(file_path_obj):
                        item.vlm_caption_status = 'skipped'
                        await session.commit()
                        log.debug(f"VLM: Skipping non-visual media: {file_path}")
                        return

                    item.vlm_caption_status = 'processing'
                    item.vlm_caption_processed_at = datetime.utcnow()
                    await session.commit()

            # Process (outside session)

            # Check file exists before processing - mark unavailable if missing
            if not file_path_obj.exists():
                async with self._db_write_semaphore:
                    async with db.async_session_maker() as session:
                        result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                        item = result.scalar_one_or_none()
                        if item:
                            item.file_unavailable = True
                            item.file_unavailable_since = datetime.utcnow()
                            item.vlm_caption_status = 'pending'  # Reset so it can be retried if file returns
                            await session.commit()
                            log.warning(f"VISUAL ANALYSIS: File missing, marked unavailable: {file_path}")
                return

            # For videos, extract first frame for analysis
            video_frame = None
            if file_path_obj.suffix.lower() in VIDEO_EXTENSIONS:
                image = await self._extract_video_frame(file_path_obj)
                video_frame = image  # Track for cleanup
            else:
                image = file_path_obj

            try:
                # Visual analysis returns caption + keywords in one call
                caption, keywords, error = await self.caption_service.analyze_image(image)
            finally:
                # Close video frame if we extracted one
                if video_frame is not None:
                    video_frame.close()

            # Update result (use semaphore to limit concurrent DB writes)
            async with self._db_write_semaphore:
                async with db.async_session_maker() as session:
                    result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                    item = result.scalar_one_or_none()
                    if item:
                        if caption:
                            item.vlm_caption = caption
                            # Store keywords as comma-separated string
                            if keywords:
                                keywords_str = ', '.join(keywords)
                                item.keywords = keywords_str
                                # Save to normalized keywords tables
                                await save_keywords_to_normalized_tables(session, item_id, keywords_str)
                            item.vlm_caption_status = 'completed'
                            item.vlm_caption_config_version = current_version
                            item.vlm_caption_processed_at = datetime.utcnow()
                            item.vlm_caption_error = None
                            await session.commit()
                            kw_count = len(keywords) if keywords else 0
                            log.debug(f"VISUAL ANALYSIS: ✓ {file_path} ({kw_count} keywords)")
                        else:
                            # Check if error indicates file not found - mark unavailable instead of failed
                            if error and "FileNotFoundError" in error:
                                item.file_unavailable = True
                                item.file_unavailable_since = datetime.utcnow()
                                item.vlm_caption_status = 'pending'  # Reset for retry if file returns
                                await session.commit()
                                log.warning(f"VISUAL ANALYSIS: File missing, marked unavailable: {file_path}")
                            else:
                                item.vlm_caption_status = 'failed'
                                item.vlm_caption_retry_count += 1
                                item.vlm_caption_error = error or "Unknown error"
                                item.vlm_caption_processed_at = datetime.utcnow()
                                await session.commit()
                                # Note: vlm_service already logged the error, no need to log again

        except FileNotFoundError:
            # File was deleted between query and processing - mark unavailable
            async with self._db_write_semaphore:
                async with db.async_session_maker() as session:
                    result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                    item = result.scalar_one_or_none()
                    if item:
                        item.file_unavailable = True
                        item.file_unavailable_since = datetime.utcnow()
                        item.vlm_caption_status = 'pending'  # Reset for retry if file returns
                        await session.commit()
                        log.warning(f"VISUAL ANALYSIS: File missing, marked unavailable: {file_path}")

        except Exception as e:
            # vlm_service logs its own errors, this catches other exceptions (video extraction, etc.)
            log.error(f"VISUAL ANALYSIS: ✗ {file_path}: {e}")
            async with self._db_write_semaphore:
                async with db.async_session_maker() as session:
                    result = await session.execute(select(MediaItem).where(MediaItem.id == item_id))
                    item = result.scalar_one_or_none()
                    if item:
                        item.vlm_caption_status = 'failed'
                        item.vlm_caption_error = str(e)
                        item.vlm_caption_retry_count += 1
                        item.vlm_caption_processed_at = datetime.utcnow()
                        await session.commit()

    async def _extract_video_frame(self, video_path: Path) -> Image.Image:
        """Extract first frame from video."""
        import ffmpeg
        from io import BytesIO
        from ffmpeg_checker import get_ffmpeg_checker

        # Check FFmpeg availability before attempting to use it
        checker = get_ffmpeg_checker()
        ffmpeg_available, ffprobe_available = checker.check_availability()

        if not ffmpeg_available or not ffprobe_available:
            # Log warning and set flag for first-time detection
            if not checker.is_warning_shown():
                log.warning("ffmpeg not found in PATH - video frame extraction will fail")
                checker.mark_warning_shown()

                # Store flag in database for API to detect and broadcast
                try:
                    from database import ControlFlag
                    from sqlalchemy.dialects.sqlite import insert
                    for profile_id in self._get_active_profile_ids():
                        db = await self._get_profile_db(profile_id)
                        async with db.async_session_maker() as session:
                            stmt = insert(ControlFlag).values(
                                key='ffmpeg_missing_warning',
                                value='true',
                                updated_at=datetime.utcnow()
                            ).on_conflict_do_update(
                                index_elements=['key'],
                                set_=dict(value='true', updated_at=datetime.utcnow())
                            )
                            await session.execute(stmt)
                            await session.commit()
                    log.info("FFmpeg missing flag stored in database for frontend notification")
                except Exception as e:
                    log.error(f"Failed to store ffmpeg_missing_warning flag: {e}")

            # Raise exception to fail gracefully (existing try/except in caller handles it)
            raise RuntimeError(f"FFmpeg is not available on this system. Missing: ffmpeg={not ffmpeg_available}, ffprobe={not ffprobe_available}")

        try:
            out, _ = (
                ffmpeg
                .input(str(video_path), ss=0)
                .output('pipe:', vframes=1, format='image2', vcodec='mjpeg')
                .run(capture_stdout=True, capture_stderr=True)
            )
            return Image.open(BytesIO(out))
        except Exception as e:
            log.error(f"VIDEO THUMBNAIL: Failed to extract frame from {video_path}: {e}")
            raise

    async def cleanup(self):
        """Clean up all resources (HTTP sessions, thread pools, etc.)."""
        log.info("INGESTION CLEANUP: Starting resource cleanup...")

        try:
            # Close HTTP sessions
            log.info("INGESTION CLEANUP: Closing HTTP sessions...")
            if self.caption_service is not None:
                await self.caption_service.close()
            log.info("INGESTION CLEANUP: HTTP sessions closed ✓")
        except Exception as e:
            log.error(f"INGESTION CLEANUP: Error closing HTTP sessions: {e}", exc_info=True)

        try:
            # Shutdown thread pool executor
            log.info("INGESTION CLEANUP: Shutting down I/O thread pool...")
            _io_executor.shutdown(wait=False, cancel_futures=True)  # Changed to non-blocking for fast shutdown
            log.info("INGESTION CLEANUP: I/O thread pool shutdown ✓")
        except Exception as e:
            log.error(f"INGESTION CLEANUP: Error shutting down thread pool: {e}", exc_info=True)

        log.info("INGESTION CLEANUP: Complete ✓")

    def stop(self):
        """Stop the continuous processing loop."""
        log.info("INGESTION: Stopping continuous processing")
        self.is_running = False


# Global ingestion instance
_ingestion: Optional[MediaIngestion] = None


def get_ingestion() -> MediaIngestion:
    """Get or create ingestion singleton."""
    global _ingestion
    if _ingestion is None:
        _ingestion = MediaIngestion()
    return _ingestion


async def run_continuous_ingestion(rescan_event=None, process_pending_event=None, pause_event=None, reload_config_event=None):
    """Run continuous ingestion loop - entry point for multiprocessing.

    Args:
        rescan_event: Optional multiprocessing.Event for cross-process rescan signaling
        process_pending_event: Optional multiprocessing.Event to wake worker for pending items (no scan)
        pause_event: Optional multiprocessing.Event for pause/resume (set = paused, clear = running)
        reload_config_event: Optional multiprocessing.Event for config reload (profiles changed)
    """
    import os
    import signal

    # Increase httpx connection limits before any LLM calls
    # httpx default max_keepalive_connections=20 causes hangs when parallelism > 20
    import httpx
    httpx._config.DEFAULT_LIMITS = httpx.Limits(
        max_connections=500,
        max_keepalive_connections=200,
    )

    log.info("INGESTION WORKER: Starting continuous ingestion worker")
    log.info(f"INGESTION WORKER: httpx limits set to max_conn=500, max_keepalive=200")
    log.info(f"INGESTION WORKER: AIOHTTP_CONNECTOR_LIMIT_PER_HOST={os.environ.get('AIOHTTP_CONNECTOR_LIMIT_PER_HOST')}")

    # With 'spawn' multiprocessing, this subprocess starts fresh without any inherited state
    # No need to reset singletons - they don't exist yet in this fresh process

    from config import get_settings
    from database_registry import get_database_registry
    settings = get_settings()
    registry = get_database_registry()
    log.info("INGESTION WORKER: Registering profiles...")
    for profile in settings.profiles:
        registry.register_profile(profile)
    log.info("INGESTION WORKER: Initializing databases...")
    await registry.init_all_databases()
    log.info("INGESTION WORKER: Databases initialized")

    ingestion = MediaIngestion()
    await ingestion.init_async()  # Initialize async components (VLM with Stimma Cloud support)

    # Handle SIGTERM for graceful subprocess shutdown
    def shutdown_handler(sig, frame):
        log.info(f"INGESTION WORKER: Received signal {sig}, initiating shutdown")
        ingestion.is_running = False
        # Wake the work loop so it can exit
        ingestion._work_available.set()

    signal.signal(signal.SIGTERM, shutdown_handler)

    # Store pause event for checking in processing loop
    if pause_event:
        ingestion._pause_event = pause_event
        log.info("INGESTION WORKER: Pause event registered")

    # Start rescan event monitor if provided
    if rescan_event:
        asyncio.create_task(ingestion._monitor_rescan_event(rescan_event))
        log.info("INGESTION WORKER: Rescan event monitor started")

    # Start process-pending event monitor if provided
    if process_pending_event:
        asyncio.create_task(ingestion._monitor_process_pending_event(process_pending_event))
        log.info("INGESTION WORKER: Process-pending event monitor started")

    # Start reload-config event monitor if provided
    if reload_config_event:
        asyncio.create_task(ingestion._monitor_reload_config_event(reload_config_event))
        log.info("INGESTION WORKER: Reload-config event monitor started")

    await ingestion.run_continuous()

"""FastAPI application setup with lifespan management."""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings, reload_settings, detect_config_changes
from database import Marker, SavedView, MediaItem
from database_registry import get_database_registry
from delete_operations import ensure_delete_worker_started
import json
from core.profile_context import get_current_profile
from core.middleware import ProfileMiddleware
from core.session_middleware import SessionIdMiddleware
from core.slowtrace import SlowtraceMiddleware
from core.logging import get_logger
from utils.websocket import ws_manager
from utils.background_tasks import monitor_media_changes, cleanup_expired_images, cleanup_ephemeral_media, monitor_processing_stats, monitor_system_warnings
from utils.migrations import run_all_migrations, run_migrations_for_profile
from tool_provider_identity import STIMMA_TOOL_PROVIDER_ID
from sqlalchemy import select

log = get_logger(__name__)

# Multiprocessing setup - use spawn context for clean subprocess without inherited async state
# Fork causes issues with asyncio/aiosqlite - the forked process inherits corrupted internal state
import multiprocessing
_mp_context = multiprocessing.get_context('spawn')


class SimpleEvent:
    """A semaphore-free Event using shared memory Value.

    multiprocessing.Event uses POSIX named semaphores which can be exhausted
    on macOS and leave orphaned resources after crashes. This uses mmap-based
    shared memory with polling instead.
    """

    def __init__(self, ctx=None):
        ctx = ctx or multiprocessing
        # lock=False avoids using semaphores - safe for single int flag
        self._flag = ctx.Value('i', 0, lock=False)

    def set(self):
        self._flag.value = 1

    def clear(self):
        self._flag.value = 0

    def is_set(self):
        return self._flag.value == 1

    def wait(self, timeout=None):
        """Wait for the event to be set. Returns True if set, False on timeout."""
        import time
        if timeout is None:
            while not self.is_set():
                time.sleep(0.05)
            return True
        else:
            deadline = time.time() + timeout
            while not self.is_set():
                if time.time() >= deadline:
                    return False
                time.sleep(min(0.05, deadline - time.time()))
            return True

# These will be initialized lazily in lifespan to avoid import-time issues
_rescan_event = None
_process_pending_event = None
_pause_event = None
_reload_config_event = None


def _saved_jsonrpc_provider_configs(settings) -> list[dict]:
    """Configs owned by the generic provider manager at startup.

    Stimma Cloud is deliberately excluded because its lifecycle is owned by
    account authentication and ``reconcile_cloud_connection``.
    """
    return [
        provider.model_dump()
        for provider in settings.tool_providers
        if provider.type != "builtin" and provider.id != STIMMA_TOOL_PROVIDER_ID
    ]


async def check_and_reset_stale_clip_embeddings(profile_id: str) -> int:
    """Check for and reset CLIP embeddings with wrong dimensions.

    This handles cases where the CLIP model changed (e.g., from PyTorch ViT-g-14 to ONNX ViT-B/32)
    but old embeddings weren't cleared by the migration.

    Returns the number of items reset.
    """
    from sqlalchemy import func, select, update
    from database import MediaItem
    from clip_service import CLIP_EMBEDDING_DIM

    registry = get_database_registry()
    db = registry.get_database(profile_id)

    reset_count = 0

    async with db.async_session_maker() as session:
        # Float32 embeddings use four bytes per dimension. Let SQLite inspect
        # the BLOB length so startup does not load and NumPy-decode every
        # embedding in a large profile.
        expected_bytes = CLIP_EMBEDDING_DIM * 4
        result = await session.execute(
            select(MediaItem.id).where(
                MediaItem.clip_embedding.isnot(None),
                func.length(MediaItem.clip_embedding) != expected_bytes,
            )
        )
        items_to_reset = list(result.scalars())

        if items_to_reset:
            log.warning(
                f"STARTUP [{profile_id}]: Found {len(items_to_reset)} items with stale CLIP embeddings "
                f"(expected {CLIP_EMBEDDING_DIM} dims), resetting for re-indexing"
            )
            # Reset in batches of 500
            batch_size = 500
            for i in range(0, len(items_to_reset), batch_size):
                batch = items_to_reset[i:i + batch_size]
                await session.execute(
                    update(MediaItem)
                    .where(MediaItem.id.in_(batch))
                    .values(clip_embedding=None, clip_status='pending')
                )
            await session.commit()
            reset_count = len(items_to_reset)
            log.info(f"STARTUP [{profile_id}]: Reset {reset_count} items for CLIP re-indexing")

    return reset_count


async def backfill_structured_media_raw_metadata(profile_id: str) -> int:
    """Backfill raw_metadata for structured media files that are missing it.

    Older structured media (sets, grids, markdown) may have been indexed before
    raw_metadata population was added. This reads the file content and populates
    the field so member_count can be computed in to_dict().

    Returns the number of items backfilled.
    """
    from sqlalchemy import select, update
    from pathlib import Path
    import json
    from media_scanner import parse_structured_media, parse_markdown_frontmatter

    registry = get_database_registry()
    db = registry.get_database(profile_id)

    async with db.async_session_maker() as session:
        # Find structured media with no raw_metadata
        result = await session.execute(
            select(MediaItem).where(
                MediaItem.deleted_at.is_(None),
                MediaItem.raw_metadata.is_(None),
                MediaItem.file_format.in_(['stimmaset.json', 'stimmagrid.json', 'md'])
            )
        )
        items = result.scalars().all()

        if not items:
            return 0

        backfilled = 0
        for item in items:
            try:
                file_path = Path(item.file_path)
                if not file_path.exists():
                    continue

                ext = file_path.suffix.lower()
                raw_metadata = None

                if ext == '.md':
                    # Markdown: store frontmatter
                    frontmatter = parse_markdown_frontmatter(file_path)
                    if frontmatter:
                        raw_metadata = json.dumps({'frontmatter': frontmatter})
                elif ext == '.stimmalayout':
                    # Layout bundles are directories (index.html + assets), not flat JSON files
                    pass
                else:
                    # JSON-based: store full parsed content
                    parsed = parse_structured_media(file_path)
                    if parsed:
                        raw_metadata = json.dumps(parsed)

                if raw_metadata:
                    item.raw_metadata = raw_metadata
                    backfilled += 1
            except Exception as e:
                log.warning(f"Failed to backfill raw_metadata for {item.file_path}: {e}")

        if backfilled > 0:
            await session.commit()
            log.info(f"backfilled raw_metadata for {backfilled} structured media items", profile=profile_id)

        return backfilled


async def fix_pending_items_with_metadata(profile_id: str) -> int:
    """Fix items stuck in 'pending' that already have metadata computed.

    Agent v2's library save previously created items with metadata_status='pending'
    even though file_hash and dimensions were already computed inline. This promotes
    them to 'completed' so they appear in All Assets.

    Returns the number of items fixed.
    """
    from sqlalchemy import select, and_
    from datetime import datetime
    from config_version import get_config_version_manager
    from media_scanner import AUDIO_EXTENSIONS, STRUCTURED_EXTENSIONS
    from pathlib import Path

    registry = get_database_registry()
    db = registry.get_database(profile_id)

    async with db.async_session_maker() as session:
        result = await session.execute(
            select(MediaItem).where(
                and_(
                    MediaItem.metadata_status == 'pending',
                    MediaItem.file_hash != '',
                    MediaItem.deleted_at.is_(None),
                )
            )
        )
        items = result.scalars().all()

        if not items:
            return 0

        current_version = get_config_version_manager().get_version('metadata')
        for item in items:
            item.metadata_status = 'completed'
            item.metadata_processed_at = datetime.utcnow()
            item.metadata_config_version = current_version
            # Skip AI phases for non-visual media
            file_ext = Path(item.file_path).suffix.lower() if item.file_path else ''
            file_name = Path(item.file_path).name.lower() if item.file_path else ''
            is_non_visual = (
                file_ext in AUDIO_EXTENSIONS or
                any(file_name.endswith(ext) for ext in STRUCTURED_EXTENSIONS)
            )
            if is_non_visual:
                item.clip_status = 'skipped'
                item.face_detection_status = 'skipped'
                item.vlm_caption_status = 'skipped'

        await session.commit()
        log.info(f"STARTUP [{profile_id}]: Fixed {len(items)} items stuck in 'pending' with metadata already computed")

    return len(items)


async def sync_markers_for_profile(profile_id: str, markers: list):
    """Sync markers from config to a profile's database.

    This is extracted from lifespan for reuse during hot reload.

    Markers are matched by config_id (stable ID from config file) rather than name,
    allowing names to be safely renamed without losing marker associations.
    """
    from heroicons import resolve_icon_svg
    from sqlalchemy import select

    registry = get_database_registry()
    db = registry.get_database(profile_id)

    async with db.async_session_maker() as session:
        # Build set of config_ids from config for determining stale markers
        config_marker_ids = {m.id for m in markers if m.id}

        # Add/update markers from config
        for marker_config in markers:
            resolved_svg = resolve_icon_svg(marker_config.icon_svg)

            # Try to find existing marker by config_id first (preferred)
            existing = None
            if marker_config.id:
                result = await session.execute(
                    select(Marker).where(Marker.config_id == marker_config.id)
                )
                existing = result.scalar_one_or_none()

            # Fallback: try to find by name (for migration from old data)
            if not existing:
                result = await session.execute(
                    select(Marker).where(Marker.name == marker_config.name)
                )
                existing = result.scalar_one_or_none()

            if existing:
                # Update existing marker (including name which can now change)
                existing.name = marker_config.name
                existing.icon_svg = resolved_svg
                existing.color = marker_config.color
                if marker_config.id:
                    existing.config_id = marker_config.id
            else:
                new_marker = Marker(
                    name=marker_config.name,
                    icon_svg=resolved_svg,
                    color=marker_config.color,
                    config_id=marker_config.id
                )
                session.add(new_marker)

        # Remove stale markers (those whose config_id is not in config)
        all_markers_result = await session.execute(select(Marker))
        all_markers = all_markers_result.scalars().all()
        for marker in all_markers:
            # If marker has config_id, check if it's in config
            # If marker has no config_id (legacy), check by name
            if marker.config_id:
                if marker.config_id not in config_marker_ids:
                    log.info("removing stale marker", marker=marker.name, config_id=marker.config_id, profile=profile_id)
                    await session.delete(marker)
            else:
                # Legacy marker without config_id - check by name
                config_names = {m.name for m in markers}
                if marker.name not in config_names:
                    log.info("removing stale marker (legacy)", marker=marker.name, profile=profile_id)
                    await session.delete(marker)

        await session.commit()


async def watch_config_file():
    """Watch config.yaml for changes and reload settings automatically.

    Uses detect_config_changes() to identify what changed and calls
    appropriate subsystem hooks for each changed section.
    """
    import os
    import sys
    from pathlib import Path
    import app_dirs

    config_path = app_dirs.get_config_path()
    last_mtime = config_path.stat().st_mtime if config_path.exists() else 0

    while True:
        await asyncio.sleep(1)  # Check every second
        try:
            current_mtime = config_path.stat().st_mtime
            if current_mtime != last_mtime:
                last_mtime = current_mtime

                # Get old settings before reload
                old_settings = get_settings()

                # Reload config
                new_settings = reload_settings()

                # Detect what changed
                changed_sections = detect_config_changes(old_settings, new_settings)
                if not changed_sections:
                    log.info("config file touched but no changes detected")
                    continue

                log.info("config reloaded", changed=list(changed_sections))

                # Track what we refreshed for the toast message
                refreshed = []

                # Handle each changed section with appropriate hooks
                for section in changed_sections:
                    try:
                        if section == 'profiles':
                            # Refresh database registry with new/updated profiles
                            registry = get_database_registry()

                            # Handle removed profiles
                            old_profile_ids = {p.id for p in old_settings.profiles}
                            new_profile_ids = {p.id for p in new_settings.profiles}
                            removed_profile_ids = old_profile_ids - new_profile_ids
                            added_profile_ids = new_profile_ids - old_profile_ids

                            if removed_profile_ids:
                                log.info("profiles removed from config", removed=list(removed_profile_ids))
                                for profile_id in removed_profile_ids:
                                    await registry.unregister_profile(profile_id)

                            # Handle new and updated profiles
                            for profile in new_settings.profiles:
                                if not registry.has_profile(profile.id):
                                    log.info("registering new profile", profile=profile.id)
                                    # Run migrations FIRST to create schema via alembic
                                    # This ensures alembic_version table exists before init_db
                                    run_migrations_for_profile(profile.id, profile.database)
                                    registry.register_profile(profile)
                                    await registry.init_database(profile.id)
                                else:
                                    # Update existing profile config (handles renames, etc.)
                                    registry.register_profile(profile)
                                # Sync markers for all profiles (they may have changed)
                                await sync_markers_for_profile(profile.id, profile.markers or [])

                            # Signal ingestion subprocess to reload config when any profile content changes
                            # (folders, markers, etc.) - not just when profiles are added/removed
                            if _reload_config_event:
                                log.info("signaling ingestion subprocess to reload config")
                                _reload_config_event.set()

                            # Broadcast profiles_updated so frontend refreshes sidebar
                            await ws_manager.broadcast("profiles_updated", {}, include_profile=False)
                            # Broadcast markers_updated so frontend refreshes marker UI
                            await ws_manager.broadcast("markers_updated", {}, include_profile=False)
                            refreshed.append("profiles")

                        elif section == 'generators':
                            # Generators don't have a cache to invalidate currently
                            # The next request will use the new config
                            log.info("generators config updated - will apply on next request")
                            refreshed.append("generators")

                        elif section == 'tool_providers':
                            # Handle added/removed/changed providers
                            old_providers_by_id = {p.id: p for p in old_settings.tool_providers}
                            new_providers_by_id = {p.id: p for p in new_settings.tool_providers}
                            old_provider_ids = set(old_providers_by_id.keys())
                            new_provider_ids = set(new_providers_by_id.keys())

                            from providers import ProviderRegistry
                            from providers.jsonrpc_manager import get_jsonrpc_manager

                            provider_registry = ProviderRegistry.get_instance()
                            jsonrpc_manager = get_jsonrpc_manager()

                            # Handle removed providers
                            removed_provider_ids = old_provider_ids - new_provider_ids
                            removed_provider_ids.discard(STIMMA_TOOL_PROVIDER_ID)
                            if removed_provider_ids:
                                log.info("providers removed from config", removed=list(removed_provider_ids))
                                for provider_id in removed_provider_ids:
                                    old_config = old_providers_by_id[provider_id]
                                    try:
                                        if old_config.type in ("stdio", "websocket"):
                                            # Use manager to remove (handles cleanup)
                                            await jsonrpc_manager.remove_provider(provider_id)
                                        else:
                                            # Builtin provider - just unregister from registry
                                            await provider_registry.unregister(provider_id)
                                        # Also soft-delete from DB cache
                                        await provider_registry.soft_delete_provider_tools(provider_id)
                                    except Exception as e:
                                        log.error("failed to unregister provider", provider=provider_id, error=str(e))

                            # Handle added providers
                            added_provider_ids = new_provider_ids - old_provider_ids
                            for provider_id in added_provider_ids:
                                if provider_id == STIMMA_TOOL_PROVIDER_ID:
                                    continue
                                new_config = new_providers_by_id[provider_id]
                                if new_config.type in ("stdio", "websocket") and new_config.enabled:
                                    log.info("connecting new provider", provider=provider_id)
                                    try:
                                        config_dict = new_config.model_dump()
                                        await jsonrpc_manager.add_provider(config_dict)
                                    except Exception as e:
                                        log.error("failed to connect new provider", provider=provider_id, error=str(e))

                            # Handle changed providers (reconnect if connection settings changed)
                            common_provider_ids = old_provider_ids & new_provider_ids
                            for provider_id in common_provider_ids:
                                if provider_id == STIMMA_TOOL_PROVIDER_ID:
                                    continue
                                old_config = old_providers_by_id[provider_id]
                                new_config = new_providers_by_id[provider_id]

                                # Skip builtin providers
                                if new_config.type == "builtin":
                                    continue

                                # Check if connection-critical settings changed
                                connection_changed = False
                                if new_config.type == "websocket":
                                    connection_changed = old_config.url != new_config.url
                                elif new_config.type == "stdio":
                                    connection_changed = (
                                        old_config.command != new_config.command or
                                        old_config.args != new_config.args or
                                        old_config.working_dir != new_config.working_dir
                                    )

                                # Check if enabled status changed
                                enabled_changed = old_config.enabled != new_config.enabled

                                if connection_changed or enabled_changed:
                                    log.info("provider config changed, reconnecting", provider=provider_id,
                                             connection_changed=connection_changed, enabled_changed=enabled_changed)
                                    try:
                                        config_dict = new_config.model_dump()
                                        if new_config.enabled:
                                            # Reconnect with new config (preserves logs)
                                            await jsonrpc_manager.reconnect_provider(provider_id, config_dict)
                                        else:
                                            # Provider disabled - remove from manager
                                            await jsonrpc_manager.remove_provider(provider_id)
                                    except Exception as e:
                                        log.error("failed to reconnect provider", provider=provider_id, error=str(e))

                            # Stimma Cloud follows account state rather than
                            # the generic saved-provider lifecycle.
                            from routes.cloud import reconcile_cloud_connection
                            await reconcile_cloud_connection()

                            # Broadcast tools_updated so frontend refreshes
                            await ws_manager.broadcast("tools_updated", {}, include_profile=False)
                            refreshed.append("tool providers")

                        elif section == 'clip':
                            # CLIP model can't be reloaded without restart
                            log.warning("CLIP config changed - restart required to apply")
                            refreshed.append("CLIP (restart required)")

                        elif section == 'face_detection':
                            # Face detection model can't be reloaded without restart
                            log.warning("face_detection config changed - restart required to apply")
                            refreshed.append("face detection (restart required)")

                        elif section == 'server':
                            # Server host/port change requires restart via watchdog
                            log.warning("server config changed - triggering restart")
                            await ws_manager.broadcast("toast_notification", {
                                "message": "Server config changed - restarting...",
                                "type": "warning",
                                "duration": 3000
                            }, include_profile=False)
                            # Exit with code 3 to signal watchdog to restart
                            await asyncio.sleep(0.5)  # Let toast broadcast complete
                            sys.exit(3)

                        elif section == 'llms':
                            # LLM configs are read fresh on each request
                            log.info("LLM config updated - will apply on next request")
                            refreshed.append("LLMs")

                        elif section == 'agent':
                            # Agent config is read fresh on each request
                            log.info("agent config updated - will apply on next request")
                            refreshed.append("agent")

                        elif section == 'captioning':
                            # Captioning config is read fresh on each request
                            log.info("captioning config updated - will apply on next request")
                            refreshed.append("captioning")

                    except Exception as e:
                        log.error(f"failed to refresh {section}", error=str(e))

                # Broadcast toast notification (only for external changes)
                if refreshed:
                    import config_writer
                    if config_writer._app_initiated_write:
                        config_writer._app_initiated_write = False
                        log.info("suppressing config reload toast (app-initiated write)")
                    else:
                        message = f"Config reloaded: {', '.join(refreshed)}"
                        await ws_manager.broadcast("toast_notification", {
                            "message": message,
                            "type": "success",
                            "duration": 4000
                        }, include_profile=False)

        except Exception as e:
            log.error("config watch error", error=str(e))


def _log_queue_listener(log_queue, stop_event):
    """Listen for log records from subprocess and emit them in main process.

    Runs in a separate thread in the main process.
    """
    import ast
    from core.logging import get_logger

    # Get a structlog logger for re-emitting subprocess logs
    ingestion_log = get_logger("ingestion")

    while not stop_event.is_set():
        try:
            # Block with timeout so we can check stop_event
            record = log_queue.get(timeout=0.5)
            if record is None:  # Sentinel to stop
                break

            # The subprocess uses structlog which produces dict-like strings.
            # Parse out the event and re-log through main process structlog.
            try:
                msg = record.getMessage()
                level = record.levelname.lower()

                # Try to parse the structlog dict string format
                # e.g. "{'event': 'message here', 'level': 'info', ...}"
                if msg.startswith('{') and 'event' in msg:
                    try:
                        data = ast.literal_eval(msg)
                        event = data.get('event', msg)
                    except (ValueError, SyntaxError):
                        event = msg
                else:
                    event = msg

                # Re-emit through structlog at appropriate level
                if level == 'debug':
                    ingestion_log.debug(event)
                elif level == 'warning':
                    ingestion_log.warning(event)
                elif level == 'error':
                    ingestion_log.error(event)
                elif level == 'critical':
                    ingestion_log.critical(event)
                else:
                    ingestion_log.info(event)
            except Exception:
                # Fallback: log raw message
                ingestion_log.info(str(record.msg))
        except Exception:
            # Queue.get timeout or other error, just continue
            pass


def run_ingestion_worker(rescan_event=None, process_pending_event=None, pause_event=None, reload_config_event=None, bundle_id: str = "", log_queue=None, sandbox: str = "default"):
    """Run continuous ingestion in a separate process.

    IMPORTANT: This runs in a separate process spawned via multiprocessing.
    The subprocess does NOT inherit the logging config from the parent process,
    so we must call setup_logging() here to ensure logs are properly formatted
    and visible.

    Args:
        rescan_event: Event to trigger folder rescan
        process_pending_event: Event to wake worker for pending items
        pause_event: Event for pause/resume (set = paused)
        reload_config_event: Event to reload config (profiles changed)
        bundle_id: Bundle ID for environment separation (e.g., "ai.stimma.stimma.debug")
        log_queue: multiprocessing.Queue to send log records to parent process
        sandbox: Sandbox name within the bundle (e.g., "default", "oobe5"). MUST match
            the web server's sandbox or the worker processes the wrong profile DBs.
    """
    import os
    import sys
    import logging
    from logging.handlers import QueueHandler
    import threading
    import time

    # Force unbuffered output for real-time logging visibility in Tauri/PyInstaller
    os.environ['PYTHONUNBUFFERED'] = '1'
    # Make stderr line-buffered if possible
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(line_buffering=True)

    # Watch for parent death - exit if parent process dies
    parent_pid = os.getppid()
    def _check_parent():
        while True:
            if os.getppid() != parent_pid:
                os._exit(0)  # Parent died, exit immediately
            time.sleep(0.5)
    threading.Thread(target=_check_parent, daemon=True).start()

    import asyncio
    import yaml
    from pathlib import Path
    from core.logging import setup_logging
    from app_context import set_app_context
    import app_dirs
    # Lazy import to avoid loading torch at module level
    from ingestion import run_continuous_ingestion

    # Set app context in subprocess before any config loading.
    # Both bundle_id AND sandbox must be restored here: this runs in a fresh
    # interpreter (multiprocessing 'spawn'), so the parent's app context globals
    # are not inherited. Omitting sandbox makes the worker operate on the wrong
    # sandbox's profile databases (it defaults to "default").
    set_app_context(bundle_id, sandbox)

    # Read log level from config (can't use get_settings() before logging is set up)
    log_level = "INFO"
    config_path = app_dirs.get_config_path()
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
                log_level = config.get("server", {}).get("log_level", "INFO")
        except Exception:
            pass

    # Initialize logging in the subprocess
    # We DON'T set up file/console handlers here - instead we send all logs
    # to the parent process via the queue, which handles formatting and output
    if log_queue is not None:
        # Configure root logger to send everything to the queue
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))
        # Remove any existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        # Add queue handler to send logs to parent process
        queue_handler = QueueHandler(log_queue)
        root_logger.addHandler(queue_handler)
    else:
        # Fallback: no queue, set up local logging (shouldn't happen in normal use)
        setup_logging(log_level=log_level)

    try:
        asyncio.run(run_continuous_ingestion(rescan_event, process_pending_event, pause_event, reload_config_event))
    except Exception as e:
        # Log with full traceback so we can see what's failing
        import traceback
        from core.logging import get_logger
        log = get_logger(__name__)
        log.exception("INGESTION WORKER CRASHED")
        traceback.print_exc(file=sys.stderr)
        raise


# Global thread pool for thumbnail generation
thumbnail_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="thumbnail")


def get_rescan_event():
    """Get the multiprocessing.Event used to signal rescan to ingestion worker."""
    return _rescan_event

def get_process_pending_event():
    """Get the multiprocessing.Event used to signal ingestion worker to process pending items (no scan)."""
    return _process_pending_event

def get_pause_event():
    """Get the multiprocessing.Event used to pause/resume ingestion worker.

    When set: processing is paused
    When cleared: processing is running
    """
    return _pause_event

def get_reload_config_event():
    """Get the multiprocessing.Event used to signal config reload to ingestion worker.

    When set: ingestion worker should reload its settings from disk.
    Used when background work settings change (enabled flags, parallelism, etc.).
    """
    return _reload_config_event


async def load_pause_state_from_db(registry) -> bool:
    """Load the persisted pause state from the database.

    Returns True if processing should be paused, False otherwise.
    """
    from database import ControlFlag
    from sqlalchemy import select
    from config import get_settings

    try:
        settings = get_settings()
        for profile in settings.profiles:
            if not registry.has_profile(profile.id):
                continue

            db = registry.get_database(profile.id)
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(ControlFlag).where(ControlFlag.key == 'processing_paused')
                )
                flag = result.scalar_one_or_none()
                if flag is not None and flag.value == 'true':
                    return True
        return False
    except Exception as e:
        log.error(f"Failed to load pause state from DB: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup.

    The lifespan is structured for fast startup:
    1. Essential DB setup (migrations, registry, markers, saved views)
    2. yield immediately (server starts accepting requests)
    3. Heavy initialization runs in background AFTER server is ready
    """
    # Track background tasks and processes for cleanup
    background_tasks = []
    ingestion_process = None
    generation_queue = None
    tool_provider_init_task = None
    log_queue = None
    log_listener_thread = None
    log_listener_stop_event = None

    async def initialize_tool_providers(settings):
        """Initialize builtin + JSON-RPC tool providers."""
        try:
            log.info("initializing tool providers")
            from providers import ProviderRegistry
            provider_registry = ProviderRegistry.get_instance()

            from backend_registry import get_backend_registry
            backend_registry = get_backend_registry()

            # Initialize builtin provider (in-process tools like remove-background, detect-objects, etc.)
            from providers import get_lightweight_provider
            builtin_provider = get_lightweight_provider()
            await builtin_provider.connect()
            await provider_registry.register(builtin_provider)
            # Register with backend_registry so scheduler can process jobs
            await backend_registry.register_backend(
                builtin_provider.provider_id,
                builtin_provider.max_concurrent
            )
            log.info("builtin provider registered", tool_count=len(await builtin_provider.list_tools()))

            # Initialize user-tools provider (flows frozen into first-class tools)
            from providers import get_user_tools_provider
            user_tools_provider = get_user_tools_provider()
            await user_tools_provider.connect()
            await provider_registry.register(user_tools_provider)
            await backend_registry.register_backend(
                user_tools_provider.provider_id,
                user_tools_provider.max_concurrent
            )
            log.info("user-tools provider registered", tool_count=len(await user_tools_provider.list_tools()))

            # Register test provider if enabled (for e2e testing)
            if os.environ.get("STIMMA_TEST_PROVIDER"):
                from providers.test_provider import get_test_provider
                test_provider = get_test_provider()
                await test_provider.connect()
                await provider_registry.register(test_provider)
                await backend_registry.register_backend(
                    test_provider.provider_id,
                    test_provider.max_concurrent
                )
                log.info("test provider registered (STIMMA_TEST_PROVIDER=1)")

            # Initialize any other builtin providers from config
            for provider_config in settings.tool_providers:
                if provider_config.type == "builtin":
                    log.warning(f"unknown builtin provider: {provider_config.id}")

            # Initialize JSON-RPC providers via manager (handles retries and health monitoring)
            from providers.jsonrpc_manager import get_jsonrpc_manager

            jsonrpc_manager = get_jsonrpc_manager()

            # Convert pydantic models to dicts, filter out builtin providers
            provider_configs = _saved_jsonrpc_provider_configs(settings)

            jsonrpc_count = await jsonrpc_manager.start(
                provider_configs=provider_configs,
                provider_registry=provider_registry,
                backend_registry=backend_registry,
            )

            if jsonrpc_count > 0:
                log.info("jsonrpc providers initialized", count=jsonrpc_count)
        except Exception:
            log.exception("tool provider initialization failed (non-fatal)")

    # Wrap entire startup in try/except to ensure exceptions are logged
    # (FastAPI/Starlette can swallow lifespan exceptions silently)
    try:
        log.info("startup begin")

        # Run database migrations for all profiles FIRST
        log.info("running migrations")
        run_all_migrations()

        # Initialize database registry with profiles
        log.info("initializing database registry")
        settings = get_settings()
        registry = get_database_registry()

        # Register all profiles
        for profile in settings.profiles:
            log.info("registering profile", profile=profile.id, database=profile.database)
            registry.register_profile(profile)

        # Initialize all profile databases
        await registry.init_all_databases()
        log.info("databases initialized", count=len(settings.profiles))

        # Structured manifests must be readable before automatic Asset
        # classification determines linked versus embedded membership.
        for profile in settings.profiles:
            started = time.monotonic()
            log.info("structured metadata backfill checking", profile=profile.id)
            backfilled = await backfill_structured_media_raw_metadata(profile.id)
            log.info(
                "structured metadata backfill checked",
                profile=profile.id,
                backfilled=backfilled,
                elapsed_seconds=round(time.monotonic() - started, 1),
            )

        # Asset browsers are authoritative in this release. Conservatively
        # materialize roots for historical Media before accepting requests;
        # ambiguous historical rows become Assets, so this migration cannot
        # make prior user-visible content disappear.
        from asset_migration import ensure_asset_backfill
        for profile in settings.profiles:
            db = registry.get_database(profile.id)
            for attempt in range(1, 4):
                try:
                    async with db.async_session_maker() as session:
                        migration = await ensure_asset_backfill(
                            session,
                            profile_id=profile.id,
                        )
                    break
                except Exception as exc:
                    is_locked = (
                        "database is locked" in str(exc).lower()
                        and attempt < 3
                    )
                    if not is_locked:
                        raise
                    delay = 2 ** (attempt - 1)
                    log.warning(
                        "asset media backfill database busy; retrying",
                        profile=profile.id,
                        attempt=attempt,
                        delay_seconds=delay,
                    )
                    await asyncio.sleep(delay)
            if not migration["already_complete"]:
                log.info(
                    "asset media backfill completed",
                    profile=profile.id,
                    assets=migration["assets"],
                    records=migration["records"],
                    digest=migration["digest"],
                )

        # Adopt Stimma-native manifests/bundles from historical writable roots
        # after membership has been normalized. Other watched paths remain
        # external Sources.
        from pathlib import Path
        from storage_service import migrate_legacy_managed_media
        for profile in settings.profiles:
            managed_roots = [
                Path(path)
                for path in profile.legacy_managed_roots
            ]
            if not managed_roots:
                continue
            db = registry.get_database(profile.id)
            migration_complete = False
            while True:
                async with db.async_session_maker() as session:
                    report = await migrate_legacy_managed_media(
                        session,
                        profile_id=profile.id,
                        managed_roots=managed_roots,
                        formats={
                            "stimmaset.json",
                            "stimmagrid.json",
                            "stimmalayout",
                        },
                        limit=100,
                    )
                if report["errors"]:
                    log.warning(
                        "structured managed-storage migration deferred",
                        profile=profile.id,
                        errors=len(report["errors"]),
                    )
                    break
                if report["missing"]:
                    log.warning(
                        "structured managed-storage migration waiting on files",
                        profile=profile.id,
                        missing=report["missing"],
                    )
                    break
                if report["migrated"] < 100:
                    migration_complete = True
                    break
            if migration_complete:
                from config_writer import remove_profile_section
                if remove_profile_section(profile.id, "legacy_managed_roots"):
                    profile.legacy_managed_roots = []

        # Check for and reset stale CLIP embeddings (from old model with different dimensions)
        for profile in settings.profiles:
            started = time.monotonic()
            log.info("CLIP embedding compatibility check started", profile=profile.id)
            reset_count = await check_and_reset_stale_clip_embeddings(profile.id)
            log.info(
                "CLIP embedding compatibility check completed",
                profile=profile.id,
                reset=reset_count,
                elapsed_seconds=round(time.monotonic() - started, 1),
            )

        # Fix items created by agent with metadata already computed but stuck as 'pending'
        for profile in settings.profiles:
            started = time.monotonic()
            log.info("pending metadata repair started", profile=profile.id)
            fixed_count = await fix_pending_items_with_metadata(profile.id)
            log.info(
                "pending metadata repair completed",
                profile=profile.id,
                fixed=fixed_count,
                elapsed_seconds=round(time.monotonic() - started, 1),
            )


        # Sync markers from config to each profile's database
        for profile in settings.profiles:
            profile_markers = profile.markers or []
            log.debug("syncing markers", profile=profile.id, count=len(profile_markers))
            await sync_markers_for_profile(profile.id, profile_markers)

            # Need to continue with saved views in same session
            db = registry.get_database(profile.id)
            async with db.async_session_maker() as session:

                # Create default saved views if none exist
                views_result = await session.execute(
                    select(SavedView)
                )
                existing_views = views_result.scalars().all()
                if not existing_views:
                    # Look up marker IDs by name
                    markers_result = await session.execute(select(Marker))
                    markers_by_name = {m.name: m.id for m in markers_result.scalars().all()}
                    favorite_id = markers_by_name.get('favorite')
                    library_id = markers_by_name.get('library')

                    # Create default saved views
                    default_views = []

                    # Default filter state (empty filters)
                    base_filters = {
                        "captionQuery": "",
                        "selectedFolderIds": [],
                        "selectedMarkers": [],
                        "excludedMarkers": [],
                        "selectedClusterIds": [],
                        "mediaType": "all",
                        "showExpiring": False,
                        "aspectRatioFilter": None,
                        "minWidth": None,
                        "minHeight": None,
                        "maxWidth": None,
                        "maxHeight": None,
                    }

                    # Favorites view - shows items marked as favorite
                    if favorite_id:
                        favorites_filters = {**base_filters, "selectedMarkers": [favorite_id]}
                        default_views.append(SavedView(
                            name="Favorites",
                            filters=json.dumps(favorites_filters),
                            sort_by="created_desc",
                            display_order=0
                        ))

                    # My Library view - shows items marked as favorite OR library
                    marker_ids = [mid for mid in [favorite_id, library_id] if mid]
                    if marker_ids:
                        library_filters = {**base_filters, "selectedMarkers": marker_ids}
                        default_views.append(SavedView(
                            name="My Library",
                            filters=json.dumps(library_filters),
                            sort_by="created_desc",
                            display_order=1
                        ))

                    # Expiring Soon view - shows items about to expire
                    expiring_filters = {**base_filters, "showExpiring": True}
                    # Exclude favorites and library from expiring view (keep them)
                    exclude_ids = [mid for mid in [favorite_id, library_id] if mid]
                    if exclude_ids:
                        expiring_filters["excludedMarkers"] = exclude_ids
                    default_views.append(SavedView(
                        name="Expiring Soon",
                        filters=json.dumps(expiring_filters),
                        sort_by="created_desc",
                        display_order=2
                    ))

                    for view in default_views:
                        session.add(view)
                    await session.commit()
                    log.info("created default saved views", profile=profile.id, count=len(default_views))

        # Clean up stale generation jobs BEFORE accepting connections
        # This must run before yield so clients don't see phantom jobs from a previous session
        log.info("cleaning up stale generation jobs")
        from generation_queue import get_generation_queue
        generation_queue = get_generation_queue()
        await generation_queue.cleanup_stale_jobs()

        # Post-processing chain runs are in-memory tasks with no resume; mark any
        # left 'running' by a previous process as paused so they aren't stuck
        # in-flight bars after a restart.
        try:
            from postprocessing.executor import reconcile_interrupted_runs
            for profile in settings.profiles:
                reconciled = await reconcile_interrupted_runs(profile.id)
                if reconciled:
                    log.info("paused interrupted chain runs", profile=profile.id, count=reconciled)
        except Exception:
            log.exception("failed to reconcile interrupted chain runs")

        # Reconcile denormalized flow.pending_task_count from each profile's
        # per-flow state.db. Catches drift from any missed WebSocket events
        # across an ungraceful shutdown so the landing view and sidebar
        # badges read correct counts on first load.
        try:
            from core.profile_context import ProfileScope
            from flow_lifecycle import (
                reconcile_pending_task_counts,
                recover_running_flows,
            )
            from flow_runtime.paths import migrate_legacy_flow_dirs
            for profile in settings.profiles:
                db = registry.get_database(profile.id)
                async with db.async_session_maker() as session:
                    with ProfileScope(profile.id):
                        # Legacy recipes/ -> flows/ on-disk migration (the
                        # recipe→flow rename moved the DB table but not the
                        # flow data dir). Must run before flow recovery.
                        migrate_legacy_flow_dirs()
                        reconciled = await reconcile_pending_task_counts(session)
                        recovered = await recover_running_flows(session)
                if reconciled:
                    log.info(
                        "flow task counts reconciled",
                        profile=profile.id, flows=len(reconciled),
                    )
                if recovered:
                    log.info(
                        "flow runtimes recovered",
                        profile=profile.id, flows=len(recovered),
                    )
        except Exception:
            log.exception("flow task count reconciliation failed (non-fatal)")

        # Start provider connections as early as possible, then give them a short
        # grace window before the server starts accepting requests.
        tool_provider_init_task = asyncio.create_task(initialize_tool_providers(settings))
        background_tasks.append(tool_provider_init_task)
        try:
            await asyncio.wait_for(asyncio.shield(tool_provider_init_task), timeout=0.5)
            log.info("tool provider initialization completed during startup grace period")
        except asyncio.TimeoutError:
            log.info("tool provider initialization still in progress after 500ms grace period")
        except Exception:
            # initialize_tool_providers logs exceptions internally; keep startup moving
            pass

        log.info("startup complete - server ready")

        # === DEFERRED INITIALIZATION ===
        # Start background tasks that run concurrently with the server.
        # These don't block the yield - the server starts accepting requests immediately.

        async def deferred_heavy_init():
            """Initialize heavy services after server is accepting requests."""
            nonlocal ingestion_process, generation_queue, log_queue, log_listener_thread, log_listener_stop_event

            # Wait for server to be fully ready and clients to connect
            await asyncio.sleep(5)

            try:
                log.info("deferred init begin")

                # Start telemetry (lightweight, non-blocking).
                # `app_launched` and `session_started` are now triggered by
                # the frontend's $session_id arriving via X-Stimma-Session-Id.
                from telemetry import get_telemetry_client
                _telemetry = get_telemetry_client()
                await _telemetry.start()

                # Crash reports (official builds only): chain the pending-
                # report writer onto the process exception hooks (additive
                # next to telemetry's app_error hooks — separate consent),
                # and handle reports left by a previous run (auto-send under
                # 'always'; 'ask' is driven by the frontend on launch).
                import crash_reports
                crash_reports.install_crash_hooks()
                await crash_reports.startup_check()

                # Start feature flag poller (cheap; uses cached values until
                # the first /decide response lands).
                from feature_flags import get_feature_flags

                async def _broadcast_flags(flags):
                    try:
                        await ws_manager.broadcast(
                            "flags_updated", {"flags": flags}, include_profile=False
                        )
                    except Exception:
                        pass

                _flags = get_feature_flags()
                _flags.subscribe(_broadcast_flags)
                await _flags.start()

                # Daily update check (official builds on an update branch
                # only; off under Privacy Lockdown / disable_update_check).
                import update_check
                update_check.start()

                # Lazy import to avoid loading torch at module level
                from ingestion import get_ingestion

                # Initialize ingestion coordinator (models load on first use)
                log.info("initializing ingestion coordinator")
                get_ingestion()

                # Create IPC events using SimpleEvent (shared memory, no semaphores)
                global _rescan_event, _process_pending_event, _pause_event, _reload_config_event
                _rescan_event = SimpleEvent(_mp_context)
                _process_pending_event = SimpleEvent(_mp_context)
                _pause_event = SimpleEvent(_mp_context)  # Clear = running, Set = paused
                _reload_config_event = SimpleEvent(_mp_context)  # Signal config reload

                # Load persisted pause state from database
                pause_state = await load_pause_state_from_db(registry)
                if pause_state:
                    _pause_event.set()
                    log.info("Restored paused state from database")

                # Start ingestion subprocess with log queue for piping logs back
                from app_context import get_bundle_id, get_sandbox
                import threading
                bundle_id = get_bundle_id()
                # The worker is spawned in a fresh interpreter (mp 'spawn'), so it does
                # NOT inherit the app context globals. We must pass BOTH bundle_id and
                # sandbox explicitly, or the worker silently falls back to the "default"
                # sandbox and processes the wrong profile databases.
                sandbox = get_sandbox()
                log.info(f"starting ingestion process (bundle={bundle_id}, sandbox={sandbox})")

                # Create log queue and listener thread to receive logs from subprocess
                log_queue = _mp_context.Queue()
                log_listener_stop_event = threading.Event()
                log_listener_thread = threading.Thread(
                    target=_log_queue_listener,
                    args=(log_queue, log_listener_stop_event),
                    daemon=True,
                    name="ingestion-log-listener"
                )
                log_listener_thread.start()

                ingestion_process = _mp_context.Process(
                    target=run_ingestion_worker,
                    args=(_rescan_event, _process_pending_event, _pause_event, _reload_config_event, bundle_id, log_queue, sandbox),
                    daemon=True
                )
                ingestion_process.start()

                # Initialize generation queue (cleanup already ran pre-yield)
                log.info("initializing generation queue")
                generation_queue.set_websocket_manager(ws_manager)
                ws_manager.set_on_generator_disconnect(generation_queue.cleanup_disconnected_client)
                # Start enough workers to handle concurrent jobs across all backends
                # Most providers report their concurrency on connect, so use a generous default
                await generation_queue.start_workers(num_workers=16)

                # Ensure early provider init has finished (or failed) before cloud auto-connect.
                if tool_provider_init_task is not None:
                    try:
                        await tool_provider_init_task
                    except Exception:
                        pass

                # Stimma Cloud is auth-managed, unlike saved JSON-RPC providers.
                try:
                    from routes.cloud import reconcile_cloud_connection
                    await reconcile_cloud_connection()

                except Exception as e:
                    log.warning("failed to auto-connect to stimma cloud", error=str(e))

                # Open the account-events push channel for any signed-in user.
                # Its on-connect refresh also discovers balance added while
                # the app was closed.
                try:
                    from cloud_events import get_cloud_events_client
                    get_cloud_events_client().start()
                except Exception as e:
                    log.warning("failed to start account-events client", error=str(e))

                log.info("deferred init complete")

            except Exception as e:
                log.exception("deferred init failed")

        # Start deferred initialization (runs concurrently, doesn't block yield)
        deferred_init_task = asyncio.create_task(deferred_heavy_init())
        background_tasks.append(deferred_init_task)

        # Start background monitoring tasks
        monitor_task = asyncio.create_task(monitor_media_changes(ws_manager))
        background_tasks.append(monitor_task)

        stats_monitor_task = asyncio.create_task(monitor_processing_stats(ws_manager))
        background_tasks.append(stats_monitor_task)

        cleanup_task = asyncio.create_task(cleanup_expired_images(ws_manager))
        background_tasks.append(cleanup_task)

        # Crash sweeper for orphaned one-shot flow-as-tool ephemeral media
        ephemeral_cleanup_task = asyncio.create_task(cleanup_ephemeral_media())
        background_tasks.append(ephemeral_cleanup_task)

        system_warnings_task = asyncio.create_task(monitor_system_warnings(ws_manager))
        background_tasks.append(system_warnings_task)

        config_watcher_task = asyncio.create_task(watch_config_file())
        background_tasks.append(config_watcher_task)

        await ensure_delete_worker_started()

    except Exception as e:
        # Log the full exception with traceback before re-raising
        # This ensures startup failures are visible even if FastAPI swallows them
        log.exception("startup failed")
        raise

    # Yield - server starts accepting requests
    # Background tasks are already running concurrently
    yield

    # === SHUTDOWN ===
    log.info("shutdown begin")

    # Flush telemetry before anything else shuts down
    try:
        from telemetry import get_telemetry_client
        await get_telemetry_client().stop()
    except Exception:
        pass

    # Stop feature-flag poller
    try:
        from feature_flags import get_feature_flags
        await get_feature_flags().stop()
    except Exception:
        pass

    # Stop the update-check task
    try:
        import update_check
        await update_check.stop()
    except Exception:
        pass

    # Close the account-events channel
    try:
        from cloud_events import get_cloud_events_client
        await get_cloud_events_client().stop()
    except Exception:
        pass

    # Wait for deferred init to complete (or timeout)
    try:
        await asyncio.wait_for(deferred_init_task, timeout=1.0)
    except asyncio.TimeoutError:
        log.warning("deferred init still running during shutdown")
    except Exception:
        pass

    # Stop generation workers (with timeout to avoid blocking shutdown)
    if generation_queue is not None:
        try:
            await asyncio.wait_for(generation_queue.stop_workers(), timeout=5.0)
            log.info("generation workers stopped")
        except asyncio.TimeoutError:
            log.warning("generation workers stop timed out")
        except Exception as e:
            log.exception("error stopping generation workers")

    # Cancel all background tasks
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # Stop and clean up ingestion process
    if ingestion_process is not None:
        try:
            if ingestion_process.is_alive():
                ingestion_process.terminate()
                ingestion_process.join(timeout=2)
                if ingestion_process.is_alive():
                    log.warning("ingestion process did not terminate, killing")
                    ingestion_process.kill()
                    ingestion_process.join(timeout=1)
            log.info("ingestion process terminated")
        except Exception as e:
            log.exception("error terminating ingestion process")

    # Stop log listener thread
    if log_listener_stop_event is not None:
        log_listener_stop_event.set()
    if log_queue is not None:
        try:
            log_queue.put(None)  # Sentinel to wake up listener
        except Exception:
            pass
    if log_listener_thread is not None:
        try:
            log_listener_thread.join(timeout=1)
            log.info("log listener thread stopped")
        except Exception:
            pass

    # Clean up ingestion coordinator resources (with timeout)
    try:
        from ingestion import get_ingestion
        ingestion = get_ingestion()
        await asyncio.wait_for(ingestion.cleanup(), timeout=2.0)
        log.info("ingestion resources cleaned up")
    except asyncio.TimeoutError:
        log.warning("ingestion cleanup timed out")
    except Exception as e:
        log.exception("error cleaning up ingestion")

    # Shutdown thumbnail thread pool
    try:
        thumbnail_executor.shutdown(wait=False, cancel_futures=True)
        log.info("thumbnail executor shutdown")
    except Exception as e:
        log.exception("error shutting down thumbnail executor")

    # Stop JSON-RPC provider manager (stops health monitoring and restart tasks)
    try:
        from providers.jsonrpc_manager import get_jsonrpc_manager
        jsonrpc_manager = get_jsonrpc_manager()
        await asyncio.wait_for(jsonrpc_manager.stop(), timeout=2.0)
        log.info("jsonrpc provider manager stopped")
    except asyncio.TimeoutError:
        log.warning("jsonrpc provider manager stop timed out")
    except Exception as e:
        log.exception("error stopping jsonrpc provider manager")

    # Shutdown tool providers (toolsv3)
    try:
        from providers import ProviderRegistry
        provider_registry = ProviderRegistry.get_instance()
        await asyncio.wait_for(provider_registry.shutdown(), timeout=2.0)
        log.info("provider registry shutdown")
    except asyncio.TimeoutError:
        log.warning("provider registry shutdown timed out")
    except Exception as e:
        log.exception("error shutting down provider registry")

    # Dispose all database engines (with timeout)
    try:
        registry = get_database_registry()
        await asyncio.wait_for(registry.dispose_all(), timeout=2.0)
        log.info("database engines disposed")
    except asyncio.TimeoutError:
        log.warning("database dispose timed out")
    except Exception as e:
        log.exception("error disposing databases")

    log.info("shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Stimma API",
        description="AI-powered image browser backend",
        version="1.0.0",
        lifespan=lifespan
    )

    # Request logging + slowtrace middleware
    app.add_middleware(SlowtraceMiddleware)

    # Global exception handler to log all unhandled exceptions with full traceback
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log.exception(
            "unhandled exception",
            method=request.method,
            path=request.url.path,
        )
        try:
            # Categorical app_error only (errorType + stack hash + module) —
            # no request paths, which can embed media/entity ids.
            from telemetry import get_telemetry_client
            get_telemetry_client().capture_exception(exc)
        except Exception:
            pass
        try:
            # Consented crash-report path (content-bearing, official builds
            # only, gated in crash_reports) — additive next to app_error.
            import crash_reports
            crash_reports.record_crash(exc)
        except Exception:
            pass
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )

    # Profile middleware (must be added before CORS so it runs after CORS in request processing)
    # Note: Starlette middleware order is reverse - last added runs first
    app.add_middleware(ProfileMiddleware)

    # Pick up the frontend's session id from X-Stimma-Session-Id on every
    # request. Runs before ProfileMiddleware so the session is recorded
    # even on routes that fail profile validation.
    app.add_middleware(SessionIdMiddleware)

    # CORS middleware - allow Tauri and development origins
    # Note: "*" doesn't work with allow_credentials=True, so we list explicit origins
    # Tauri v2 uses different origin schemes per platform:
    #   - macOS/Linux: tauri://localhost
    #   - Windows: https://tauri.localhost
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",           # Tauri v2 production (macOS/Linux)
            "https://tauri.localhost",     # Tauri v2 production (Windows)
            "http://tauri.localhost",      # Tauri v2 fallback
            "http://localhost:9192",       # Vite dev server
            "http://127.0.0.1:9192",       # Vite dev server (alt)
        ],
        allow_origin_regex=r"http://127\.0\.0\.1:\d+",  # Dynamic backend ports
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Profile-ID", "Content-Disposition"],  # Expose headers to frontend
    )

    return app

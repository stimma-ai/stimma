"""Lifecycle for native drag copies, indexed alongside other derived media caches.

The backend reserves a unique directory before handing work to the native helper.
The helper must never recreate it: removing the directory revokes an in-flight
writer as well as deleting finished copies (including temporary files).
"""

import asyncio
import shutil
import time
import uuid
from pathlib import Path

from sqlalchemy import delete, select, update

import app_dirs
from app_context import get_sandbox
from core.logging import get_logger
from database import MediaItem, MediaThumbnailCache

log = get_logger(__name__)
MAX_AGE_SECONDS = 60 * 60
MIN_IDLE_SECONDS = 10 * 60
MAX_CACHE_BYTES = 512 * 1024 * 1024


def snapshot_root() -> Path:
    return app_dirs.get_cache_dir() / "drag_snapshots"


def remove_snapshot_directory(directory: Path) -> None:
    try:
        if directory.is_symlink():
            directory.unlink(missing_ok=True)
        else:
            shutil.rmtree(directory)
    except FileNotFoundError:
        if directory.exists() or directory.is_symlink():
            raise


def purge_cached_path(path: Path) -> None:
    if path.parent.parent == snapshot_root() and path.name.startswith("snapshot."):
        remove_snapshot_directory(path.parent)
    else:
        path.unlink(missing_ok=True)


def purge_legacy_snapshots() -> None:
    # The old Tauri shell used the bundle cache; Electron uses the sandbox.
    # Only flat files are legacy. Never traverse other sandboxes or caches.
    roots = {snapshot_root()}
    bundle_root = app_dirs.get_bundle_cache_root()
    # Explicit cache overrides (including tests/headless instances) own only
    # their selected directory, never the desktop installation's cache.
    if app_dirs.get_cache_dir() == bundle_root / get_sandbox():
        roots.add(bundle_root / "drag_snapshots")
    for root in roots:
        if root.is_symlink():
            raise OSError("Drag snapshot cache must not be a symlink")
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)


async def reserve_snapshot(session, media_id: int, extension: str) -> Path:
    # Serialize with the durable deletion barrier before creating or indexing
    # anything. A stale SQLite reader fails instead of resurrecting a cache.
    result = await session.execute(
        update(MediaItem)
        .where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.deletion_pending_at.is_(None),
        )
        .values(indexed_date=MediaItem.indexed_date)
        .returning(MediaItem.id)
    )
    if result.scalar_one_or_none() is None:
        raise ValueError("Media is being deleted")

    # Retire index entries left by expiry, keeping repeated prewarming bounded.
    old_paths = (await session.scalars(select(MediaThumbnailCache.cache_path).where(
        MediaThumbnailCache.media_id == media_id,
    ))).all()
    for old in old_paths:
        path = Path(old)
        if path.parent.parent == snapshot_root() and not path.parent.exists():
            await session.execute(delete(MediaThumbnailCache).where(
                MediaThumbnailCache.media_id == media_id,
                MediaThumbnailCache.cache_path == old,
            ))

    directory = snapshot_root() / uuid.uuid4().hex
    path = directory / f"snapshot.{extension}"
    directory.mkdir(parents=True)
    try:
        session.add(MediaThumbnailCache(media_id=media_id, cache_path=str(path)))
        await session.commit()
    except BaseException:
        remove_snapshot_directory(directory)
        raise
    return path


def cleanup_snapshots() -> None:
    purge_legacy_snapshots()
    root = snapshot_root()
    if not root.exists():
        return
    now = time.time()
    entries = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            created = directory.stat().st_mtime
            size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
            entries.append((created, size, directory))
        except FileNotFoundError:
            continue
    total = sum(size for _, size, _ in entries)
    for created, size, directory in sorted(entries):
        age = now - created
        # Keep recent drag targets alive while another application consumes them.
        if age >= MAX_AGE_SECONDS or (total > MAX_CACHE_BYTES and age >= MIN_IDLE_SECONDS):
            remove_snapshot_directory(directory)
            total -= size


async def cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup_snapshots)
        except Exception:
            log.exception("drag snapshot cleanup failed; will retry")
        await asyncio.sleep(60)

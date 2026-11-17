"""Named image delivery variants: ``screen`` and ``full``.

A large original (a 16 MP PNG is about 20 MB) is the wrong thing to send for a
picture shown at fit-to-screen. Viewers ask for a named variant instead:

``screen``
    Fit to a 2560 px long side, WebP q90. Covers full-screen fit on common
    displays at a fraction of the bytes and decoded memory.
``full``
    Full resolution, lossy but high quality: JPEG q92 with 4:4:4 chroma for
    opaque images, WebP q92 when the image has alpha. Used when a remote viewer
    zooms past what ``screen`` holds.

Variants are named rather than sized so the cache cannot grow without bound.
They keep orientation (EXIF transpose), alpha and the ICC profile so that
swapping one for the original changes sharpness and nothing else.

When a variant would not help (the original is barely larger than the tier, or
already a small or lossy file) the route serves the original bytes instead.
The frontend applies the same rule from ``width``/``height``/``file_size``
(frontend/src/utils/imageTiers.js), so a client never fetches the same pixels
twice. Keep the two in step.

This module has no route or worker-pool imports so the ingestion process can
use it for eager generation.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import threading
import uuid
from concurrent.futures import Future
from pathlib import Path

from PIL import Image, ImageOps

from core.logging import get_logger

log = get_logger(__name__)

VARIANT_VERSION = 1
VARIANT_TIERS = ("screen", "full")

SCREEN_LONG_SIDE = 2560
# A variant only pays off when it is meaningfully smaller than the original.
SCREEN_SKIP_LONG_SIDE = int(SCREEN_LONG_SIDE * 1.25)  # 3200
# Below this an original is already cheap to send and decode.
SCREEN_SKIP_BYTES = 512 * 1024
# A `full` re-encode only helps a big lossless file.
FULL_SKIP_BYTES = 3 * 1024 * 1024

# Formats a variant can be derived from. GIF is excluded so animation survives.
VARIANT_SOURCE_FORMATS = {"jpg", "jpeg", "png", "webp", "bmp"}
IMAGE_FORMATS = VARIANT_SOURCE_FORMATS | {"gif"}
LOSSY_FORMATS = {"jpg", "jpeg", "webp"}

SCREEN_QUALITY = 90
FULL_QUALITY = 92
WEBP_MAX_SIDE = 16383

# Source modes a variant reproduces exactly (after EXIF transpose).
_VARIANT_MODES = {"RGB", "RGBA", "L", "LA", "P", "PA", "1"}
_VARIANT_EXTENSIONS = {"screen": ("webp",), "full": ("jpg", "webp")}
MEDIA_TYPES = {"webp": "image/webp", "jpg": "image/jpeg"}


def is_image_format(file_format: str | None) -> bool:
    return (file_format or "").lower() in IMAGE_FORMATS


def variant_serves_original(
    tier: str,
    file_format: str | None,
    width: int | None,
    height: int | None,
    file_size: int | None,
) -> bool:
    """True when ``tier`` is just the original file for this image.

    Mirrors ``tierServesOriginal`` in frontend/src/utils/imageTiers.js.
    Unknown dimensions are not a reason to skip: the generator decides from
    the decoded image and falls back to the original itself.
    """
    fmt = (file_format or "").lower()
    if fmt not in VARIANT_SOURCE_FORMATS:
        return True
    if file_size and file_size <= SCREEN_SKIP_BYTES:
        return True
    if width and height and max(width, height) <= SCREEN_SKIP_LONG_SIDE:
        return True
    if tier == "full":
        if fmt in LOSSY_FORMATS:
            return True
        if file_size and file_size <= FULL_SKIP_BYTES:
            return True
    return False


def variant_cache_key(db_guid: str | None, file_hash: str, tier: str) -> str:
    identity = ("variant", db_guid, file_hash, tier, VARIANT_VERSION)
    return hashlib.md5(json.dumps(identity).encode()).hexdigest()


def variant_cache_paths(cache_dir: Path, cache_key: str, tier: str) -> list[Path]:
    """Every path this variant may be stored at (``full`` is JPEG or WebP)."""
    shard = cache_dir / cache_key[:2] / cache_key[2:4]
    return [shard / f"{cache_key}.{tier}.{ext}" for ext in _VARIANT_EXTENSIONS[tier]]


def existing_variant(cache_dir: Path, cache_key: str, tier: str) -> Path | None:
    for path in variant_cache_paths(cache_dir, cache_key, tier):
        if path.exists():
            return path
    return None


def _rgb_icc_profile(img: Image.Image) -> bytes | None:
    """The source ICC profile, when it still describes the encoded pixels."""
    icc = img.info.get("icc_profile")
    # Bytes 16-20 of an ICC header name its color space. A CMYK or gray
    # profile would be wrong once the pixels are converted to RGB.
    if icc and len(icc) >= 20 and icc[16:20] == b"RGB ":
        return icc
    return None


def _atomic_write(img: Image.Image, path: Path, fmt: str, **kwargs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".tmp_{uuid.uuid4().hex}_{path.name}"
    try:
        img.save(temp_path, fmt, **kwargs)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def generate_variant_sync(file_path: str, tier: str, cache_dir: Path, cache_key: str) -> Path | None:
    """Write ``tier`` for ``file_path`` into the cache and return its path.

    Returns None when the original should be served instead (the decoded image
    turned out small, animated, or in a color mode a variant cannot carry
    exactly). Raises on unreadable sources so the caller can tell a failure
    from a skip.
    """
    if tier not in VARIANT_TIERS:
        raise ValueError(f"Unknown image variant: {tier}")
    existing = existing_variant(cache_dir, cache_key, tier)
    if existing is not None:
        return existing

    with Image.open(file_path) as source:
        if getattr(source, "is_animated", False):
            return None
        if source.mode not in _VARIANT_MODES:
            # CMYK, high bit depth and other modes: converting would change
            # colors or tones, so the original is the exact answer.
            return None
        if source.info.get("icc_profile") and _rgb_icc_profile(source) is None:
            # A gray (or other non-RGB) profile cannot ride along on RGB pixels.
            return None
        long_side = max(source.size)
        if long_side <= SCREEN_SKIP_LONG_SIDE:
            return None
        icc = _rgb_icc_profile(source)
        if tier == "screen" and source.format == "JPEG":
            # Let libjpeg decode at a reduced DCT scale that still exceeds the target.
            scale = SCREEN_LONG_SIDE / long_side
            source.draft(source.mode, (int(source.width * scale) + 1, int(source.height * scale) + 1))
        img = ImageOps.exif_transpose(source)
        # Covers alpha bands, palette transparency and RGB/L tRNS colors.
        has_alpha = img.has_transparency_data
        if has_alpha:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        extra = {"icc_profile": icc} if icc else {}
        if tier == "screen":
            scale = SCREEN_LONG_SIDE / max(img.size)
            size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            img = img.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
            path = variant_cache_paths(cache_dir, cache_key, tier)[0]
            _atomic_write(img, path, "WEBP", quality=SCREEN_QUALITY, method=4, alpha_quality=100, **extra)
            return path

        # full: JPEG encodes about 8x faster than WebP at this size, and this
        # tier is generated while a remote viewer is waiting on a zoom.
        if has_alpha:
            if max(img.size) > WEBP_MAX_SIDE:
                return None
            path = variant_cache_paths(cache_dir, cache_key, tier)[1]
            _atomic_write(img, path, "WEBP", quality=FULL_QUALITY, method=4, alpha_quality=100, **extra)
        else:
            path = variant_cache_paths(cache_dir, cache_key, tier)[0]
            _atomic_write(img, path, "JPEG", quality=FULL_QUALITY, subsampling=0, optimize=True, **extra)
        return path


async def media_is_live(session, media_id: int) -> bool:
    """The media row exists and no permanent delete is queued or running for it."""
    from sqlalchemy import select
    from database import DeleteOperation, DeleteOperationItem, MediaItem

    exists = await session.scalar(select(MediaItem.id).where(MediaItem.id == media_id).limit(1))
    if exists is None:
        return False
    deleting = await session.scalar(
        select(DeleteOperationItem.media_id)
        .join(DeleteOperation, DeleteOperation.id == DeleteOperationItem.operation_id)
        .where(
            DeleteOperationItem.media_id == media_id,
            DeleteOperation.status.in_(["queued", "running"]),
            DeleteOperationItem.state.not_in(["done", "failed"]),
        )
        .limit(1)
    )
    return deleting is None


# ---------------------------------------------------------------------------
# Eager `screen` generation
#
# After a generation saves, an upload lands or ingest reads a large image, its
# `screen` variant is built in the background so the slideshow finds it on
# disk. One daemon thread works a bounded queue: it never competes with
# interactive work for more than one core, never holds up shutdown, and drops
# new work past the bound (those images are generated on first view). A viewer
# who asks before a queued job has started generates it on the interactive
# pool instead of waiting; the eager job then finds the file and returns.

EAGER_MAX_PENDING = 64


class EagerJob:
    def __init__(self, file_path: str, cache_dir: Path, cache_key: str):
        self.args = (file_path, "screen", cache_dir, cache_key)
        self.future: Future = Future()
        self.started = threading.Event()


_eager_queue: "queue.Queue[EagerJob]" = queue.Queue(maxsize=EAGER_MAX_PENDING)
_eager_thread: threading.Thread | None = None
_eager_lock = threading.Lock()
# cache_key -> queued or running eager job.
eager_jobs: dict[str, EagerJob] = {}


def _eager_worker() -> None:
    while True:
        job = _eager_queue.get()
        if not job.future.set_running_or_notify_cancel():
            continue
        job.started.set()
        try:
            file_path = job.args[0]
            # Permanently deleted while queued: nothing to build.
            result = generate_variant_sync(*job.args) if Path(file_path).is_file() else None
        except BaseException as exc:  # noqa: BLE001 - reported through the future
            job.future.set_exception(exc)
        else:
            job.future.set_result(result)


def _submit_eager(job: EagerJob) -> bool:
    global _eager_thread
    with _eager_lock:
        if _eager_thread is None:
            _eager_thread = threading.Thread(target=_eager_worker, name="image-variant-eager", daemon=True)
            _eager_thread.start()
    try:
        _eager_queue.put_nowait(job)
    except queue.Full:
        return False
    return True


def wants_eager_screen(item) -> bool:
    fmt = (getattr(item, "file_format", None) or "").lower()
    if fmt not in VARIANT_SOURCE_FORMATS or not getattr(item, "file_hash", None):
        return False
    if getattr(item, "ephemeral_run_id", None):
        return False
    width, height = getattr(item, "width", None), getattr(item, "height", None)
    if not width or not height:
        return False
    return not variant_serves_original(
        "screen", fmt, width, height, getattr(item, "file_size", None),
    )


async def _finish_eager(db, media_id: int, job: EagerJob, cache_key: str) -> None:
    """After an eager write, drop the file if its media was deleted meanwhile."""
    try:
        path = await asyncio.wrap_future(job.future)
    except Exception as exc:
        log.info("Eager screen variant deferred to first view", media_id=media_id, error=type(exc).__name__)
        return
    finally:
        if eager_jobs.get(cache_key) is job:
            eager_jobs.pop(cache_key, None)
    if path is None:
        return
    try:
        async with db.async_session_maker() as session:
            live = await media_is_live(session, media_id)
    except Exception:
        return
    if not live:
        Path(path).unlink(missing_ok=True)


async def queue_eager_screen_for_media(db, media_ids) -> int:
    """Record and queue `screen` variants for the large images in ``media_ids``.

    ``db`` is the profile database. Opens its own session so it can run after
    the caller's commit, and never raises: a failure here must not turn a save
    into an error. Returns how many were queued.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from config import get_settings
    from database import MediaItem, MediaThumbnailCache

    ids = [media_id for media_id in media_ids if media_id is not None]
    if not ids:
        return 0
    queued = 0
    try:
        db_guid = getattr(db, "db_guid", None)
        cache_dir = get_settings().get_thumbnail_cache_dir()
        async with db.async_session_maker() as session:
            rows = list(await session.scalars(select(MediaItem).where(MediaItem.id.in_(ids))))
            jobs = []
            for item in rows:
                if not wants_eager_screen(item):
                    continue
                cache_key = variant_cache_key(db_guid, item.file_hash, "screen")
                if existing_variant(cache_dir, cache_key, "screen") is not None or cache_key in eager_jobs:
                    continue
                if len(eager_jobs) + len(jobs) >= EAGER_MAX_PENDING:
                    break
                path = variant_cache_paths(cache_dir, cache_key, "screen")[0]
                # Index the derived file before it exists so a permanent delete
                # that races generation still purges it.
                await session.execute(
                    sqlite_insert(MediaThumbnailCache)
                    .values(media_id=item.id, cache_path=str(path))
                    .on_conflict_do_nothing(index_elements=["media_id", "cache_path"])
                )
                jobs.append((str(item.file_path), cache_key, item.id))
            if not jobs:
                return 0
            await session.commit()
        for file_path, cache_key, media_id in jobs:
            job = EagerJob(file_path, cache_dir, cache_key)
            if not _submit_eager(job):
                break
            eager_jobs[cache_key] = job
            _track(asyncio.get_running_loop().create_task(_finish_eager(db, media_id, job, cache_key)))
            queued += 1
    except Exception as exc:
        log.warning("Eager screen variants skipped", error=type(exc).__name__)
    return queued


_background_tasks: set = set()


def _track(task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def schedule_eager_screen_for_media(db, media_ids) -> None:
    """Fire-and-forget form of queue_eager_screen_for_media for save paths."""
    try:
        task = asyncio.get_running_loop().create_task(queue_eager_screen_for_media(db, list(media_ids)))
    except Exception as exc:
        log.debug("Eager screen variants not scheduled", error=type(exc).__name__)
        return
    _track(task)

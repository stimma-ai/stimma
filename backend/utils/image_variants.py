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

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
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
    turned out small, animated, or in a mode a variant cannot carry). Raises on
    unreadable sources so the caller can tell a failure from a skip.
    """
    if tier not in VARIANT_TIERS:
        raise ValueError(f"Unknown image variant: {tier}")
    existing = existing_variant(cache_dir, cache_key, tier)
    if existing is not None:
        return existing

    with Image.open(file_path) as source:
        if getattr(source, "is_animated", False):
            return None
        if source.mode in ("I", "I;16", "I;16B", "I;16L", "F"):
            # High bit depth: leave tone mapping to the browser and the original.
            return None
        long_side = max(source.size)
        if long_side <= SCREEN_SKIP_LONG_SIDE:
            return None
        icc = _rgb_icc_profile(source)
        if tier == "screen" and source.format == "JPEG":
            # Let libjpeg decode at a reduced DCT scale that still exceeds the target.
            scale = SCREEN_LONG_SIDE / long_side
            source.draft("RGB", (int(source.width * scale) + 1, int(source.height * scale) + 1))
        img = ImageOps.exif_transpose(source)
        has_alpha = img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
            img.mode == "P" and "transparency" in img.info
        )
        if has_alpha:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
        elif img.mode != "RGB":
            if img.mode not in ("L", "P", "1", "CMYK", "YCbCr", "LAB", "HSV"):
                return None
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


# ---------------------------------------------------------------------------
# Eager `screen` generation
#
# After a generation saves or ingest reads a large image, its `screen` variant
# is built in the background so the slideshow finds it on disk. One low
# priority thread keeps this from competing with interactive thumbnail work;
# a failure only means the first viewer generates it lazily.

_eager_executor: ThreadPoolExecutor | None = None
_eager_lock = threading.Lock()
# cache_key -> running eager job, so an interactive request can join it.
eager_jobs: dict[str, Future] = {}


def _eager_pool() -> ThreadPoolExecutor:
    global _eager_executor
    with _eager_lock:
        if _eager_executor is None:
            _eager_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="image-variant-eager")
        return _eager_executor


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


async def queue_eager_screen_variants(session, db_guid: str | None, items) -> int:
    """Record and queue `screen` variants for the large images in ``items``.

    Never raises: this runs after a save has already committed, and a failure
    here must not turn that save into an error. Returns how many were queued.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from config import get_settings
    from database import MediaThumbnailCache

    queued = 0
    try:
        cache_dir = get_settings().get_thumbnail_cache_dir()
        jobs = []
        for item in items:
            if not wants_eager_screen(item):
                continue
            cache_key = variant_cache_key(db_guid, item.file_hash, "screen")
            if existing_variant(cache_dir, cache_key, "screen") is not None or cache_key in eager_jobs:
                continue
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
        pool = _eager_pool()
        for file_path, cache_key, media_id in jobs:
            future = pool.submit(generate_variant_sync, file_path, "screen", cache_dir, cache_key)
            eager_jobs[cache_key] = future

            def _done(f: Future, key=cache_key, media_id=media_id):
                if eager_jobs.get(key) is f:
                    eager_jobs.pop(key, None)
                exc = f.exception()
                if exc is not None:
                    log.info("Eager screen variant deferred to first view", media_id=media_id, error=type(exc).__name__)

            future.add_done_callback(_done)
            queued += 1
    except Exception as exc:
        try:
            await session.rollback()
        except Exception:
            pass
        log.warning("Eager screen variants skipped", error=type(exc).__name__)
    return queued


async def queue_eager_screen_for_media(db, media_ids) -> int:
    """Queue eager `screen` variants for ``media_ids`` in profile database ``db``.

    Opens its own session so it can run after the caller's commit. Never raises.
    """
    ids = [media_id for media_id in media_ids if media_id is not None]
    if not ids:
        return 0
    try:
        from sqlalchemy import select
        from database import MediaItem

        async with db.async_session_maker() as session:
            rows = list(await session.scalars(select(MediaItem).where(MediaItem.id.in_(ids))))
            return await queue_eager_screen_variants(session, getattr(db, "db_guid", None), rows)
    except Exception as exc:
        log.warning("Eager screen variants skipped", error=type(exc).__name__)
        return 0


_background_tasks: set = set()


def schedule_eager_screen_for_media(db, media_ids) -> None:
    """Fire-and-forget form of queue_eager_screen_for_media for save paths."""
    import asyncio

    try:
        task = asyncio.get_running_loop().create_task(queue_eager_screen_for_media(db, list(media_ids)))
    except Exception as exc:
        log.debug("Eager screen variants not scheduled", error=type(exc).__name__)
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

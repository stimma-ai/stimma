"""Public provenance ("how it was made") for share links: sidecar v2.

The frontend builds a display-ready provenance object and sends it with the
share request. This module is the desktop-side gate before anything leaves the
machine:

- validates it with pydantic (types strict, unknown fields ignored, strings and
  lists capped to the published contract);
- drops any string that looks like an absolute filesystem path;
- resolves each input ``ref`` (media id first, then hash) to a small WebP
  thumbnail and replaces the ref with an opaque key (``t0``, ``t1``...), so no
  ids or hashes are published.

The result is the ``historySidecar`` form field the cloud stores and serves at
``/api/s/:code/history``.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import MediaItem

log = get_logger(__name__)

SIDECAR_VERSION = 2

# Caps from the published contract.
MAX_STEPS = 32
MAX_FACTS = 40
MAX_LORAS = 20
MAX_INPUTS = 16
MAX_EDITS = 40
MAX_PROMPT = 8000
MAX_FACT_VALUE = 200
MAX_LABEL = 60
MAX_NAME = 120
MAX_DATE = 40
MAX_HASH = 128

THUMB_SIZE = 128
THUMB_QUALITY = 75
# A sidecar above this drops its thumbnails rather than fail the share.
MAX_SIDECAR_BYTES = 2 * 1024 * 1024

VIDEO_FORMATS = {"mp4", "webm", "mov", "avi", "mkv"}

# Absolute filesystem paths, as they appear on macOS, Linux and Windows.
_PATH_PATTERNS = [
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"(?:^|[\s\"'(=\[,;:])/(?:Users|home|root|Volumes|private/var|var/folders|mnt|media)/"),
    # Any other absolute POSIX path with at least two directory levels.
    re.compile(r"(?:^|[\s\"'(=\[,;:])/[\w.@~-]+/[\w.@~-]+/"),
    re.compile(r"(?:^|[\s\"'(=\[,;])[A-Za-z]:[\\/]"),
    re.compile(r"(?:^|[\s\"'(=\[,;])\\\\[^\\\s]+\\"),
]


def looks_like_path(value: Any) -> bool:
    """True when a string contains something that looks like an absolute local path."""
    if not isinstance(value, str):
        return False
    return any(p.search(value) for p in _PATH_PATTERNS)


def _clean_text(value: Any, cap: int) -> Optional[str]:
    """Trimmed, capped, path-free text, or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value or looks_like_path(value):
        return None
    return value[:cap]


# Request models (frontend -> desktop backend) ────────────────────────────────

class _Lenient(BaseModel):
    """Unknown fields are ignored: only what we model can ever be published."""

    model_config = ConfigDict(extra="ignore")


class ProvenanceRef(_Lenient):
    mediaId: Optional[int] = None
    hash: Optional[str] = Field(default=None, max_length=MAX_HASH)


class ProvenanceInput(_Lenient):
    role: Optional[str] = None
    ref: Optional[ProvenanceRef] = None


class ProvenanceFact(_Lenient):
    label: str
    value: Optional[str | int | float | bool] = None


class ProvenanceLora(_Lenient):
    name: str
    weight: Optional[float] = None

    @field_validator("weight")
    @classmethod
    def _finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            return None
        return v


class ProvenanceStep(_Lenient):
    tool: str
    model: Optional[str] = None
    date: Optional[str] = None
    prompt: Optional[str] = None
    negativePrompt: Optional[str] = None
    originalPrompt: Optional[str] = None
    facts: list[ProvenanceFact] = Field(default_factory=list)
    loras: list[ProvenanceLora] = Field(default_factory=list)
    inputs: list[ProvenanceInput] = Field(default_factory=list)
    edits: list[str] = Field(default_factory=list)


class ProvenanceRequest(_Lenient):
    version: int = SIDECAR_VERSION
    steps: list[ProvenanceStep] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _v2(cls, v: int) -> int:
        if v != SIDECAR_VERSION:
            raise ValueError("provenance version must be 2")
        return v


class ProvenanceError(ValueError):
    """The provenance object could not be validated (user-facing message)."""


def parse_provenance(raw: Any) -> Optional[ProvenanceRequest]:
    """Validate the request's ``provenance``. None means "do not publish"."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProvenanceError("“How it was made” could not be read. Turn it off to share without it.")
    try:
        return ProvenanceRequest.model_validate(raw)
    except ValidationError as exc:
        log.info("share provenance rejected", errors=exc.error_count())
        raise ProvenanceError("“How it was made” could not be read. Turn it off to share without it.") from exc


# Thumbnails ───────────────────────────────────────────────────────────────────

async def _media_for_ref(session: AsyncSession, ref: ProvenanceRef) -> Optional[MediaItem]:
    """Media id first, hash second (latest live match)."""
    if ref.mediaId is not None:
        media = await session.get(MediaItem, ref.mediaId)
        if media is not None and media.deleted_at is None and media.ephemeral_run_id is None:
            if not ref.hash or ref.hash == media.file_hash:
                return media
    if ref.hash:
        return await session.scalar(
            select(MediaItem)
            .where(
                MediaItem.file_hash == ref.hash,
                MediaItem.deleted_at.is_(None),
                MediaItem.ephemeral_run_id.is_(None),
            )
            .order_by(MediaItem.id.desc())
            .limit(1)
        )
    return None


def thumbnail_data_uri(media: MediaItem, size: int = THUMB_SIZE) -> Optional[str]:
    """A small WebP data URI for an image or video media item, or None."""
    from PIL import Image

    path = Path(media.file_path)
    if not path.is_file():
        return None
    fmt = (media.file_format or "").lower()
    try:
        if fmt in VIDEO_FORMATS:
            import ffmpeg

            out, _ = (
                ffmpeg.input(str(path), ss=0)
                .output("pipe:", vframes=1, format="image2", vcodec="mjpeg")
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            img = Image.open(io.BytesIO(out))
        elif fmt == "svg" or "." in fmt:
            # Vectors and structured documents have no cheap raster here.
            return None
        else:
            from utils.image_ops import open_oriented

            img = open_oriented(path)
        return _encode_thumb(img, size)
    except Exception as exc:  # noqa: BLE001
        log.debug("provenance thumbnail failed", media_id=media.id, error=type(exc).__name__)
        return None


def _encode_thumb(img, size: int = THUMB_SIZE) -> str:
    from PIL import Image

    img.thumbnail((size, size), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode or img.mode == "P" else "RGB")
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=THUMB_QUALITY)
    img.close()
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


async def input_thumbnail_data_uri(session: AsyncSession, media: MediaItem) -> Optional[str]:
    """Thumbnail for a provenance input of any type.

    Rasters and videos are read directly. Vectors go through the same local
    renderer the library uses; anything else (documents, containers) reuses a
    thumbnail the library has already cached for it.
    """
    fmt = (media.file_format or "").lower()
    if fmt == "svg":
        from share_payloads import rasterize_svg

        img = await rasterize_svg(Path(media.file_path), long_side=THUMB_SIZE * 2)
        if img is not None:
            try:
                return await asyncio.to_thread(_encode_thumb, img)
            except Exception:  # noqa: BLE001
                pass
    else:
        uri = await asyncio.to_thread(thumbnail_data_uri, media)
        if uri:
            return uri
    return await _cached_library_thumbnail(session, media)


async def _cached_library_thumbnail(session: AsyncSession, media: MediaItem) -> Optional[str]:
    from PIL import Image
    from sqlalchemy import select

    from database import MediaThumbnailCache

    rows = await session.execute(
        select(MediaThumbnailCache.cache_path).where(MediaThumbnailCache.media_id == media.id)
    )
    for cache_path in rows.scalars():
        path = Path(cache_path)
        if not path.is_file():
            continue
        try:
            return await asyncio.to_thread(lambda: _encode_thumb(Image.open(path)))
        except Exception:  # noqa: BLE001
            continue
    return None


# Published shape (desktop backend -> cloud) ───────────────────────────────────

async def build_public_sidecar(
    session: AsyncSession, provenance: ProvenanceRequest
) -> Optional[dict[str, Any]]:
    """The published v2 sidecar, or None when nothing publishable remains."""
    thumbnails: dict[str, str] = {}
    key_by_media: dict[int, Optional[str]] = {}
    steps_out: list[dict[str, Any]] = []

    for step in provenance.steps[:MAX_STEPS]:
        tool = _clean_text(step.tool, MAX_NAME)
        if not tool:
            continue
        out: dict[str, Any] = {"tool": tool}
        for field, cap in (
            ("model", MAX_NAME),
            ("date", MAX_DATE),
            ("prompt", MAX_PROMPT),
            ("negativePrompt", MAX_PROMPT),
            ("originalPrompt", MAX_PROMPT),
        ):
            value = _clean_text(getattr(step, field), cap)
            if value:
                out[field] = value

        facts = []
        for fact in step.facts:
            label = _clean_text(fact.label, MAX_LABEL)
            value = fact.value
            if isinstance(value, bool):
                value = "Yes" if value else "No"
            value = _clean_text(value, MAX_FACT_VALUE)
            if label and value:
                facts.append({"label": label, "value": value})
            if len(facts) >= MAX_FACTS:
                break
        if facts:
            out["facts"] = facts

        loras = []
        for lora in step.loras:
            name = _clean_text(lora.name, MAX_NAME)
            if not name:
                continue
            entry: dict[str, Any] = {"name": name}
            if lora.weight is not None:
                entry["weight"] = round(float(lora.weight), 4)
            loras.append(entry)
            if len(loras) >= MAX_LORAS:
                break
        if loras:
            out["loras"] = loras

        inputs = []
        for item in step.inputs[:MAX_INPUTS]:
            entry = {}
            role = _clean_text(item.role, MAX_LABEL)
            if role:
                entry["role"] = role
            if item.ref is not None:
                media = await _media_for_ref(session, item.ref)
                if media is not None:
                    if media.id not in key_by_media:
                        uri = await input_thumbnail_data_uri(session, media)
                        key = None
                        if uri:
                            key = f"t{len(thumbnails)}"
                            thumbnails[key] = uri
                        key_by_media[media.id] = key
                    if key_by_media[media.id]:
                        entry["thumb"] = key_by_media[media.id]
            if entry:
                inputs.append(entry)
        if inputs:
            out["inputs"] = inputs

        edits = [e for e in (_clean_text(x, MAX_LABEL) for x in step.edits) if e][:MAX_EDITS]
        if edits:
            out["edits"] = edits

        steps_out.append(out)

    if not steps_out:
        return None
    sidecar = {"version": SIDECAR_VERSION, "steps": steps_out, "thumbnails": thumbnails}
    if len(json.dumps(sidecar)) > MAX_SIDECAR_BYTES:
        log.info("share provenance sidecar too large, dropping thumbnails")
        for step in steps_out:
            for entry in step.get("inputs") or []:
                entry.pop("thumb", None)
            step["inputs"] = [e for e in step.get("inputs") or [] if e]
            if not step["inputs"]:
                step.pop("inputs")
        sidecar["thumbnails"] = {}
    return sidecar

"""Agent-bound vision payload encoding and cache helpers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from app_dirs import get_cache_dir


AGENT_IMAGE_JPEG_QUALITY = 85
AGENT_IMAGE_CACHE_VERSION = 1


def encode_agent_jpeg(img: Image.Image) -> bytes:
    """Encode pixels for model vision input using the app-wide lossy policy."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=AGENT_IMAGE_JPEG_QUALITY,
        optimize=True,
    )
    return buf.getvalue()


def media_agent_jpeg_cache_path(
    *,
    media_id: int,
    file_hash: str,
    max_side: int,
) -> Path:
    """Return the persistent JPEG cache path for one immutable library Media."""
    key = hashlib.sha256(
        (
            f"{file_hash}:{media_id}:{max_side}:"
            f"q{AGENT_IMAGE_JPEG_QUALITY}:v{AGENT_IMAGE_CACHE_VERSION}"
        ).encode("utf-8")
    ).hexdigest()
    return get_cache_dir() / "agent-vision" / key[:2] / key[2:4] / f"{key}.jpg"


def write_agent_jpeg(img: Image.Image, destination: Path | None = None) -> Path:
    """Write a JPEG snapshot atomically, or return an existing cached result."""
    if destination is not None and destination.exists():
        return destination

    if destination is None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            destination = Path(handle.name)
        destination.write_bytes(encode_agent_jpeg(img))
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".jpg.tmp",
        dir=destination.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        temporary.write_bytes(encode_agent_jpeg(img))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination

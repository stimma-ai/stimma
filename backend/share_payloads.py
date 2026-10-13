"""Build what a share link uploads, for every media type.

One entry point, :func:`build_payload`, turns a library item into a
:class:`SharePayload`: the primary file, ordered members, an OG thumbnail and
the public ``structuredContent``. Everything it produces is meant to be
published, so the rules here are privacy rules first:

- No absolute paths, file paths, library ids or hashes in anything public.
  Members are addressed by index (``members/<n>.<ext>`` on the cloud side).
- Embedded file metadata (EXIF/XMP, PNG text chunks such as generator
  workflows, container tags) is stripped, so "how it was made" stays the
  user's choice instead of riding along inside the file.
- Upload filenames are generic (``original.<ext>``, ``<n>.<ext>``).

Formats the share viewer cannot play are converted: BMP/TIFF to PNG, AVI/MKV to
H.264/AAC MP4.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import shutil
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import MediaItem
from share_provenance import looks_like_path

log = get_logger(__name__)

# Workers request-body limit is 100 MB; keep headroom for multipart framing.
MAX_UPLOAD_BYTES = 95 * 1000 * 1000

# Per-part limits the cloud enforces (mirrored so failures are explained here).
_MiB = 1024 * 1024
CLOUD_LIMITS = {
    "thumbnail": 5 * _MiB,
    "text/markdown": 2 * _MiB,
    "image/svg+xml": 10 * _MiB,
    "text/html": 25 * _MiB,
    "historySidecar": 8 * _MiB,
    "structuredContent": 1 * _MiB,
}
MAX_TEXT_MEMBERS = 200
MAX_SPRITE_ANIMATIONS = 64

OG_WIDTH = 1200
OG_HEIGHT = 630
OG_QUALITY = 80
MATTE = (7, 9, 13)  # #07090d
WAVE_INK = (226, 232, 240)
WAVE_RULE = (31, 36, 45)

TRANSCODE_TIMEOUT_S = 600
REMUX_TIMEOUT_S = 120

IMAGE_FORMATS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff"}
WEB_IMAGE_FORMATS = {"jpg", "jpeg", "png", "gif", "webp"}
VIDEO_FORMATS = {"mp4", "webm", "mov", "avi", "mkv"}
WEB_VIDEO_FORMATS = {"mp4", "webm", "mov"}
AUDIO_FORMATS = {"mp3", "wav", "flac", "aac", "m4a", "ogg"}

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "md": "text/markdown",
    "html": "text/html",
    "zip": "application/zip",
}

# ffmpeg muxer per audio container, for metadata-stripping remuxes.
_AUDIO_MUXERS = {"mp3": "mp3", "wav": "wav", "flac": "flac", "aac": "adts", "m4a": "ipod", "ogg": "ogg"}
_VIDEO_MUXERS = {"mp4": "mp4", "mov": "mov", "webm": "webm"}


class ShareBuildError(Exception):
    """The item cannot be turned into a share payload (user-facing message)."""


@dataclass
class Part:
    filename: str
    data: bytes
    content_type: str


@dataclass
class SharePayload:
    media_type: str
    file: Optional[Part] = None
    members: list[Part] = field(default_factory=list)
    thumbnail: Optional[bytes] = None
    structured_content: Optional[dict] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    moderation_text: Optional[str] = None

    def files(self) -> list[tuple[str, tuple[str, bytes, str]]]:
        out = []
        if self.file is not None:
            out.append(("file", (self.file.filename, self.file.data, self.file.content_type)))
        for m in self.members:
            out.append(("members", (m.filename, m.data, m.content_type)))
        if self.thumbnail:
            out.append(("thumbnail", ("thumb.webp", self.thumbnail, "image/webp")))
        return out


def share_media_type(file_format: Optional[str]) -> Optional[str]:
    """Cloud ``mediaType`` for a library format, or None when it can't be shared."""
    fmt = (file_format or "").lower()
    if fmt == "stimmaset.json":
        return "set"
    if fmt == "stimmagrid.json":
        return "grid"
    if fmt == "stimmasprite.json":
        return "sprite"
    if fmt == "stimmapackage":
        return "package"
    if fmt == "stimmalayout":
        return "layout"
    if fmt in VIDEO_FORMATS:
        return "video"
    if fmt in AUDIO_FORMATS:
        return "audio"
    if fmt in IMAGE_FORMATS:
        return "image"
    if fmt == "md":
        return "text"
    if fmt == "svg":
        return "vector"
    return None


def form_bytes(payload: SharePayload, data: dict[str, str]) -> int:
    """Total bytes of the multipart body's content (files plus text fields)."""
    total = sum(len(f[1][1]) for f in payload.files())
    total += sum(len(v.encode("utf-8")) for v in data.values() if isinstance(v, str))
    return total


def cloud_limit_problem(payload: SharePayload, data: dict[str, str]) -> Optional[str]:
    """A friendly message when a part exceeds a cloud per-part limit, else None."""
    if payload.thumbnail and len(payload.thumbnail) > CLOUD_LIMITS["thumbnail"]:
        return "The preview image for this item is too large to share."
    if payload.file is not None:
        cap = CLOUD_LIMITS.get(payload.file.content_type)
        if cap and len(payload.file.data) > cap:
            kind = {"text/markdown": "document", "image/svg+xml": "SVG", "text/html": "page"}[payload.file.content_type]
            return f"This {kind} is too large to share as a link (limit {cap // _MiB} MB)."
    if len(data.get("structuredContent", "").encode("utf-8")) > CLOUD_LIMITS["structuredContent"]:
        return "This item has too many parts to share as a link."
    return None


def too_large_message(size_bytes: int) -> str:
    mb = size_bytes / 1_000_000
    return (
        f"This is too large to share as a link ({mb:.0f} MB). "
        f"Links can hold up to {MAX_UPLOAD_BYTES // 1_000_000} MB."
    )


# Public-content sanitizing ────────────────────────────────────────────────────

_PRIVATE_KEYS = {
    "id", "media_id", "mediaId", "asset_id", "assetId", "saved_asset_id", "revision_id",
    "file_path", "filePath", "path", "hash", "file_hash", "fileHash", "resolved",
    "generation_metadata", "source", "source_path",
}


def scrub_public(value: Any) -> Any:
    """Recursively drop id/path/hash keys and path-looking strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _PRIVATE_KEYS:
                continue
            v = scrub_public(v)
            if v is None and isinstance(value.get(k), str):
                continue
            out[k] = v
        return out
    if isinstance(value, list):
        return [scrub_public(v) for v in value if not (isinstance(v, str) and looks_like_path(v))]
    if isinstance(value, str) and looks_like_path(value):
        return None
    return value


def _clean_label(value: Any, cap: int = 200) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or looks_like_path(value):
        return None
    return value[:cap]


# Embedded metadata stripping ──────────────────────────────────────────────────

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}


def strip_png_metadata(data: bytes) -> bytes:
    """Drop text/EXIF/time chunks; pixels untouched."""
    if not data.startswith(_PNG_SIG):
        return data
    out = bytearray(_PNG_SIG)
    pos = len(_PNG_SIG)
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return data
        if ctype not in _PNG_DROP:
            out += data[pos:end]
        pos = end
        if ctype == b"IEND":
            break
    return bytes(out)


def _jpeg_orientation(data: bytes) -> int:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return int(im.getexif().get(0x0112, 1) or 1)
    except Exception:  # noqa: BLE001
        return 1


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Drop EXIF/XMP/IPTC/comments without recompressing; keep orientation."""
    if not data.startswith(b"\xff\xd8"):
        return data
    orientation = _jpeg_orientation(data)
    out = bytearray(b"\xff\xd8")
    if orientation != 1:
        exif = Image.Exif()
        exif[0x0112] = orientation
        blob = exif.tobytes()
        if not blob.startswith(b"Exif\x00\x00"):
            blob = b"Exif\x00\x00" + blob
        out += b"\xff\xe1" + struct.pack(">H", len(blob) + 2) + blob
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return data
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xDA:  # start of scan: the rest is image data
            out += data[pos:]
            return bytes(out)
        if marker in (0x01,) or 0xD0 <= marker <= 0xD7:
            out += data[pos:pos + 2]
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        end = pos + 2 + length
        # APP1 (EXIF/XMP), APP13 (IPTC), COM: dropped. APP0/APP2(ICC)/APP14 kept.
        if marker not in (0xE1, 0xED, 0xFE):
            out += data[pos:end]
        pos = end
    return data


def strip_webp_metadata(data: bytes) -> bytes:
    """Drop EXIF and XMP chunks from a RIFF WebP."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return data
    chunks = []
    pos = 12
    while pos + 8 <= len(data):
        ctype = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        end = pos + 8 + size + (size & 1)
        if end > len(data) + 1:
            return data
        if ctype not in (b"EXIF", b"XMP "):
            chunk = bytearray(data[pos:min(end, len(data))])
            if ctype == b"VP8X" and len(chunk) > 8:
                chunk[8] &= ~0x0C & 0xFF  # clear EXIF and XMP flags
            chunks.append(bytes(chunk))
        pos = end
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


# Process helpers ──────────────────────────────────────────────────────────────

def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


async def _run(args: list[str], timeout: float) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError((stderr or b"").decode("utf-8", "replace")[-500:])


async def _remux_stripped(path: Path, muxer: str, streams: list[str]) -> Optional[bytes]:
    """Stream-copy into the same container without global metadata. None on failure."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory(prefix="stimma-share-") as tmp:
        out = Path(tmp) / f"out.{muxer}"
        args = [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(path)]
        for s in streams:
            args += ["-map", s]
        args += ["-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1"]
        if muxer in ("mp4", "mov", "ipod"):
            args += ["-movflags", "+faststart"]
        args += ["-f", muxer, str(out)]
        try:
            await _run(args, REMUX_TIMEOUT_S)
            data = out.read_bytes()
            return data or None
        except Exception as exc:  # noqa: BLE001
            log.info("share remux failed, sending original", error=type(exc).__name__)
            return None


async def transcode_to_mp4(path: Path) -> bytes:
    """H.264/AAC MP4 with faststart for formats browsers cannot play."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise ShareBuildError(
            "Sharing this video needs FFmpeg to convert it to MP4, and FFmpeg isn't installed."
        )
    with tempfile.TemporaryDirectory(prefix="stimma-share-") as tmp:
        out = Path(tmp) / "out.mp4"
        args = [
            ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:a", "aac", "-b:a", "160k",
            "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(out),
        ]
        try:
            await _run(args, TRANSCODE_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise ShareBuildError("Converting this video took too long. Try a shorter clip or export it as MP4 first.")
        except Exception as exc:  # noqa: BLE001
            log.warning("share transcode failed", error=str(exc)[:200])
            raise ShareBuildError("This video couldn't be converted for sharing.")
        return out.read_bytes()


# Atomic files ─────────────────────────────────────────────────────────────────

def _ext(path: Path, fmt: Optional[str] = None) -> str:
    return (fmt or path.suffix.lstrip(".")).lower()


def image_part(path: Path, filename_stem: str, fmt: Optional[str] = None) -> Part:
    """A web-safe image with embedded metadata removed."""
    ext = _ext(path, fmt)
    data = path.read_bytes()
    if ext in ("jpg", "jpeg"):
        return Part(f"{filename_stem}.jpg", strip_jpeg_metadata(data), "image/jpeg")
    if ext == "png":
        return Part(f"{filename_stem}.png", strip_png_metadata(data), "image/png")
    if ext == "webp":
        return Part(f"{filename_stem}.webp", strip_webp_metadata(data), "image/webp")
    if ext == "gif":
        return Part(f"{filename_stem}.gif", data, "image/gif")
    # BMP, TIFF and anything else Pillow reads: re-encode as PNG.
    from utils.image_ops import open_oriented

    img = open_oriented(path)
    try:
        if img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
    finally:
        img.close()
    return Part(f"{filename_stem}.png", buf.getvalue(), "image/png")


async def video_part(path: Path, filename_stem: str, fmt: Optional[str] = None) -> Part:
    ext = _ext(path, fmt)
    if ext in WEB_VIDEO_FORMATS:
        stripped = await _remux_stripped(path, _VIDEO_MUXERS[ext], ["0:v?", "0:a?"])
        return Part(f"{filename_stem}.{ext}", stripped or path.read_bytes(), CONTENT_TYPES[ext])
    return Part(f"{filename_stem}.mp4", await transcode_to_mp4(path), "video/mp4")


async def audio_part(path: Path, filename_stem: str, fmt: Optional[str] = None) -> Part:
    ext = _ext(path, fmt)
    stripped = await _remux_stripped(path, _AUDIO_MUXERS.get(ext, ext), ["0:a"])
    return Part(f"{filename_stem}.{ext}", stripped or path.read_bytes(), CONTENT_TYPES.get(ext, "application/octet-stream"))


async def atomic_part(path: Path, filename_stem: str, fmt: Optional[str] = None) -> Optional[Part]:
    """Image or video member/primary. None for anything else."""
    ext = _ext(path, fmt)
    if ext in IMAGE_FORMATS:
        return await asyncio.to_thread(image_part, path, filename_stem, ext)
    if ext in VIDEO_FORMATS:
        return await video_part(path, filename_stem, ext)
    return None


# Thumbnails ───────────────────────────────────────────────────────────────────

def _webp(img: Image.Image, quality: int = OG_QUALITY) -> bytes:
    if img.mode not in ("RGB",):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def og_from_image(img: Image.Image) -> bytes:
    """Fit inside 1200x630 (no upscaling), alpha flattened onto the matte."""
    if img.mode in ("RGBA", "LA", "PA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, MATTE)
        flat.paste(rgba, (0, 0), rgba)
        img = flat
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img = img.copy()
    img.thumbnail((OG_WIDTH, OG_HEIGHT), Image.LANCZOS)
    return _webp(img)


def og_card(art: Image.Image, *, background=MATTE, pixelated: bool = False, fill: float = 0.82) -> bytes:
    """Artwork centered on a 1200x630 card."""
    canvas = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), background)
    art = art.convert("RGBA")
    max_w, max_h = int(OG_WIDTH * fill), int(OG_HEIGHT * fill)
    scale = min(max_w / max(1, art.width), max_h / max(1, art.height))
    if pixelated:
        scale = max(1, int(scale)) if scale >= 1 else scale
    size = (max(1, round(art.width * scale)), max(1, round(art.height * scale)))
    art = art.resize(size, Image.NEAREST if pixelated else Image.LANCZOS)
    canvas.paste(art, ((OG_WIDTH - size[0]) // 2, (OG_HEIGHT - size[1]) // 2), art)
    return _webp(canvas)


def image_og_thumbnail(path: Path) -> Optional[bytes]:
    try:
        from utils.image_ops import open_oriented

        img = open_oriented(path)
        try:
            return og_from_image(img)
        finally:
            img.close()
    except Exception as exc:  # noqa: BLE001
        log.debug("share image thumbnail failed", error=type(exc).__name__)
        return None


def video_og_thumbnail(path: Path) -> Optional[bytes]:
    try:
        import ffmpeg

        out, _ = (
            ffmpeg.input(str(path), ss=0)
            .output("pipe:", vframes=1, format="image2", vcodec="mjpeg")
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )
        with Image.open(io.BytesIO(out)) as img:
            img.load()
            return og_from_image(img)
    except Exception as exc:  # noqa: BLE001
        log.debug("share video thumbnail failed", error=type(exc).__name__)
        return None


def _audio_peaks(path: Path, buckets: int) -> list[float]:
    """Per-bucket peak amplitude in [0, 1]; empty when the audio can't be decoded."""
    import numpy as np

    try:
        import ffmpeg

        out, _ = (
            ffmpeg.input(str(path))
            .output("pipe:", format="s16le", acodec="pcm_s16le", ac=1, ar=8000)
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("share waveform decode failed", error=type(exc).__name__)
        return []
    samples = np.frombuffer(out, dtype="<i2").astype(np.float32)
    if samples.size == 0:
        return []
    samples = np.abs(samples) / 32768.0
    per = max(1, samples.size // buckets)
    usable = samples[: per * min(buckets, max(1, samples.size // per))]
    peaks = usable.reshape(-1, per).max(axis=1)
    top = float(peaks.max()) or 1.0
    # Normalize to the loudest bucket, then lift quiet passages a little.
    return [float(min(1.0, (p / top) ** 0.7)) for p in peaks]


def audio_waveform_thumbnail(path: Path) -> bytes:
    """A light waveform on the matte, 1200x630 WebP. Flat line when undecodable."""
    from PIL import ImageDraw

    ss = 2  # supersample for smooth bar ends
    w, h = OG_WIDTH * ss, OG_HEIGHT * ss
    canvas = Image.new("RGB", (w, h), MATTE)
    draw = ImageDraw.Draw(canvas)
    margin_x = 96 * ss
    bar_w, gap = 4 * ss, 3 * ss
    count = (w - 2 * margin_x) // (bar_w + gap)
    peaks = _audio_peaks(path, count)
    mid = h // 2
    max_half = int(h * 0.30)
    draw.line([(margin_x, mid), (w - margin_x, mid)], fill=WAVE_RULE, width=ss)
    for i in range(count):
        p = peaks[i] if i < len(peaks) else 0.0
        half = max(ss, int(p * max_half))
        x = margin_x + i * (bar_w + gap)
        draw.rounded_rectangle([x, mid - half, x + bar_w, mid + half], radius=bar_w // 2, fill=WAVE_INK)
    canvas = canvas.resize((OG_WIDTH, OG_HEIGHT), Image.LANCZOS)
    return _webp(canvas, quality=85)


async def rasterize_svg(path: Path, long_side: int = 560) -> Optional[Image.Image]:
    """Render an SVG with the local renderer (same path as library thumbnails)."""
    from routes.media_files import _generate_svg_preview

    try:
        return await _generate_svg_preview(str(path), long_side, queue_timeout_s=10.0)
    except Exception as exc:  # noqa: BLE001
        log.debug("share svg rasterize failed", error=type(exc).__name__)
        return None


# Builders ─────────────────────────────────────────────────────────────────────

def _base_metadata(media: MediaItem, media_type: str) -> dict[str, Any]:
    return {
        "mediaType": media_type,
        "width": media.width or None,
        "height": media.height or None,
        "duration": media.duration,
        "sourceHash": media.file_hash,
    }


def _require_file(path: Path) -> None:
    if not path.exists():
        raise ShareBuildError("The file for this item is missing from disk.")


async def _build_image(media: MediaItem, path: Path) -> SharePayload:
    _require_file(path)
    part = await asyncio.to_thread(image_part, path, "original", media.file_format)
    return SharePayload(
        media_type="image",
        file=part,
        thumbnail=await asyncio.to_thread(image_og_thumbnail, path),
    )


async def _build_video(media: MediaItem, path: Path) -> SharePayload:
    _require_file(path)
    part = await video_part(path, "original", media.file_format)
    return SharePayload(
        media_type="video",
        file=part,
        thumbnail=await asyncio.to_thread(video_og_thumbnail, path),
    )


async def _build_audio(media: MediaItem, path: Path) -> SharePayload:
    _require_file(path)
    part = await audio_part(path, "original", media.file_format)
    return SharePayload(
        media_type="audio",
        file=part,
        thumbnail=await asyncio.to_thread(audio_waveform_thumbnail, path),
    )


async def _build_vector(media: MediaItem, path: Path) -> SharePayload:
    from utils.svg_doc import SvgParseError, ink_tone, prepare_text, read_svg_file

    _require_file(path)
    try:
        clean, doc = prepare_text(read_svg_file(path))
    except SvgParseError:
        raise ShareBuildError("This SVG couldn't be read.")
    thumb = None
    img = await rasterize_svg(path)
    if img is not None:
        try:
            tone = ink_tone(doc.root)
        except Exception:  # noqa: BLE001
            tone = "mixed"
        background = (244, 244, 245) if tone == "dark" else MATTE
        thumb = og_card(img, background=background, fill=0.78)
    return SharePayload(
        media_type="vector",
        file=Part("original.svg", clean.encode("utf-8"), "image/svg+xml"),
        thumbnail=thumb,
    )


# Markdown ---------------------------------------------------------------------

_INLINE_LINK = re.compile(r'(!?)\[((?:[^\[\]]|\[[^\]]*\])*)\]\(\s*(<[^>]*>|[^)\s]+)((?:\s+(?:"[^"]*"|\'[^\']*\'|\([^)]*\)))?)\s*\)')
_REF_DEF = re.compile(r'^( {0,3}\[[^\]]+\]:[ \t]*)(<[^>]*>|\S+)(.*)$', re.MULTILINE)
_HTML_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*)(["\'])([^"\']+)\2', re.IGNORECASE)
_API_MEDIA_ID = re.compile(r'/api/(?:db/[^/]+/)?media/(\d+)(?:/|$)')
_API_MEDIA_HASH = re.compile(r'/api/(?:db/[^/]+/)?media/by-hash/([0-9a-fA-F]{16,128})(?:/|$)')
_SCHEME = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*:')


def _is_local_ref(target: str) -> bool:
    if not target or target.startswith("#"):
        return False
    if target.lower().startswith("file:"):
        return True
    if _SCHEME.match(target) and not re.match(r"^[A-Za-z]:[\\/]", target):
        return False  # http(s), data:, mailto: …
    return True


async def _media_for_markdown_ref(session: AsyncSession, target: str, base_path: Path) -> Optional[MediaItem]:
    from structured_media import resolve_path
    from utils.query_builder import not_due_for_autodelete

    live = (MediaItem.deleted_at.is_(None), MediaItem.ephemeral_run_id.is_(None), not_due_for_autodelete())
    m = _API_MEDIA_HASH.search(target)
    if m:
        return await session.scalar(
            select(MediaItem).where(MediaItem.file_hash == m.group(1), *live).order_by(MediaItem.id.desc()).limit(1)
        )
    m = _API_MEDIA_ID.search(target)
    if m:
        media = await session.get(MediaItem, int(m.group(1)))
        if media is not None and media.deleted_at is None:
            return media
        return None
    raw = unquote(target)
    if raw.lower().startswith("file://"):
        raw = raw[7:]
    try:
        full = resolve_path(base_path, raw)
    except (OSError, ValueError):
        return None
    return await session.scalar(
        select(MediaItem).where(MediaItem.file_path == str(full), *live).order_by(MediaItem.id.desc()).limit(1)
    )


async def rewrite_markdown(
    session: AsyncSession, text: str, base_path: Path
) -> tuple[str, list[Part]]:
    """Point library image refs at ``members/<n>.<ext>``; neutralise other local refs.

    External http(s) and data: targets are left as they are. Local targets that
    don't resolve to library media are dropped: an image keeps only its alt
    text, a link keeps only its label.
    """
    members: list[Part] = []
    by_media: dict[int, str] = {}

    async def member_for(target: str) -> Optional[str]:
        media = await _media_for_markdown_ref(session, target, base_path)
        if media is None:
            return None
        if media.id in by_media:
            return by_media[media.id]
        if len(members) >= MAX_TEXT_MEMBERS:
            return None
        fmt = (media.file_format or "").lower()
        path = Path(media.file_path)
        if not path.is_file():
            return None
        if fmt in IMAGE_FORMATS:
            part = await asyncio.to_thread(image_part, path, str(len(members)), fmt)
        elif fmt == "svg":
            from utils.svg_doc import SvgParseError, prepare_text, read_svg_file

            try:
                clean, _ = prepare_text(read_svg_file(path))
            except SvgParseError:
                return None
            part = Part(f"{len(members)}.svg", clean.encode("utf-8"), "image/svg+xml")
        else:
            return None
        members.append(part)
        by_media[media.id] = f"members/{part.filename}"
        return by_media[media.id]

    async def sub_async(pattern: re.Pattern, string: str, repl) -> str:
        out, last = [], 0
        for m in pattern.finditer(string):
            out.append(string[last:m.start()])
            out.append(await repl(m))
            last = m.end()
        out.append(string[last:])
        return "".join(out)

    async def inline(m: re.Match) -> str:
        bang, label, target, title = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        bare = target[1:-1] if target.startswith("<") else target
        if not _is_local_ref(bare):
            return m.group(0)
        if bang:
            new = await member_for(bare)
            if new:
                return f"![{label}]({new}{title})"
            return label
        return label

    async def refdef(m: re.Match) -> str:
        prefix, target, rest = m.group(1), m.group(2), m.group(3)
        bare = target[1:-1] if target.startswith("<") else target
        if not _is_local_ref(bare):
            return m.group(0)
        new = await member_for(bare)
        return f"{prefix}{new}{rest}" if new else f"{prefix}#"

    async def html_img(m: re.Match) -> str:
        prefix, quote, target = m.group(1), m.group(2), m.group(3)
        if not _is_local_ref(target):
            return m.group(0)
        new = await member_for(target)
        return f"{prefix}{quote}{new or ''}{quote}"

    text = await sub_async(_INLINE_LINK, text, inline)
    text = await sub_async(_REF_DEF, text, refdef)
    text = await sub_async(_HTML_IMG_SRC, text, html_img)
    return text, members


async def _build_text(session: AsyncSession, media: MediaItem, path: Path) -> SharePayload:
    from structured_media import read_markdown_file

    _require_file(path)
    parsed = await asyncio.to_thread(read_markdown_file, path)
    if parsed is None:
        raise ShareBuildError("This document couldn't be read.")
    # Front matter is local bookkeeping; only the body is published.
    body, members = await rewrite_markdown(session, parsed.get("content") or "", path)
    thumb = None
    for part in members:
        if part.content_type != "image/svg+xml":
            try:
                with Image.open(io.BytesIO(part.data)) as img:
                    img.load()
                    thumb = og_from_image(img)
            except Exception:  # noqa: BLE001
                thumb = None
            if thumb:
                break
    return SharePayload(
        media_type="text",
        file=Part("original.md", body.encode("utf-8"), "text/markdown"),
        members=members,
        thumbnail=thumb,
        structured_content={"version": 1, "images": len(members)},
        moderation_text=body[:4000],
    )


# Sprite -----------------------------------------------------------------------

def _encode_animation(frames: list, durations: list[int], loop: str) -> bytes:
    buf = io.BytesIO()
    frames[0].save(
        buf, format="WEBP", save_all=True, append_images=frames[1:],
        duration=durations, loop=1 if loop == "once" else 0, lossless=True, quality=100, method=4,
    )
    return buf.getvalue()


async def _build_sprite(session: AsyncSession, media: MediaItem) -> SharePayload:
    from sprite_export import SpriteExportError, load_sprite_source

    try:
        source = await load_sprite_source(session, media)
    except SpriteExportError as exc:
        log.info("share sprite unavailable", error=str(exc)[:200])
        raise ShareBuildError("This sprite's animations aren't available on disk yet.")
    if not source.animations:
        raise ShareBuildError("This sprite has no animations to share yet.")
    if len(source.animations) > MAX_SPRITE_ANIMATIONS:
        raise ShareBuildError(
            f"This sprite has {len(source.animations)} animations; links can hold up to {MAX_SPRITE_ANIMATIONS}."
        )

    members: list[Part] = []
    animations: list[dict[str, Any]] = []
    for i, anim in enumerate(source.animations):
        data = await asyncio.to_thread(_encode_animation, anim.frames, anim.durations_ms, anim.loop)
        members.append(Part(f"{i}.webp", data, "image/webp"))
        animations.append({
            "name": _clean_label(anim.name, 60) or f"animation {i + 1}",
            "direction": anim.direction,
            "fps": anim.fps,
            "loop": anim.loop,
            "loopStart": anim.loop_start,
            "loopEnd": anim.loop_end,
            "frameCount": len(anim.frames),
            "durationsMs": list(anim.durations_ms),
            "member": i,
        })

    first = next((a for a in source.animations if a.name.lower() == "idle"), source.animations[0])
    thumb = await asyncio.to_thread(og_card, first.frames[0], pixelated=source.pixelated, fill=0.8)
    structured = {
        "version": 1,
        "title": _clean_label(source.title, 100) or "Sprite",
        "pixelated": bool(source.pixelated),
        "anchor": {"x": float(source.anchor[0]), "y": float(source.anchor[1])},
        "animations": animations,
    }
    return SharePayload(media_type="sprite", members=members, thumbnail=thumb, structured_content=structured)


# Package ----------------------------------------------------------------------

_PATHISH_TEXT = re.compile(r'file://[^\s"\'<>)]*', re.IGNORECASE)


def _scrub_package_zip(data: bytes) -> bytes:
    """Rewrite the zip with its manifest free of library ids and local paths."""
    from packages.manifest import MANIFEST_NAME

    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            payload = src.read(info)
            if info.filename.rsplit("/", 1)[-1] == MANIFEST_NAME:
                try:
                    manifest = json.loads(payload)
                    payload = json.dumps(_scrub_manifest(manifest), indent=2).encode("utf-8")
                except (ValueError, TypeError):
                    pass
            dst.writestr(info, payload)
    return buf.getvalue()


def _scrub_manifest(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _scrub_manifest(v)
            for k, v in value.items()
            if k not in {"media_id", "asset_id", "revision_id"} and not (isinstance(v, str) and looks_like_path(v))
        }
    if isinstance(value, list):
        return [_scrub_manifest(v) for v in value if not (isinstance(v, str) and looks_like_path(v))]
    return value


def _package_zip(bundle: Path, manifest: dict, slug: str) -> bytes:
    from packages.export import export_zip

    return _scrub_package_zip(export_zip(bundle, manifest, folder_name=slug))


def _package_thumbnail(bundle: Path) -> Optional[bytes]:
    from routes.media_files import _generate_package_preview

    try:
        tile = _generate_package_preview(str(bundle), OG_HEIGHT)
        return og_card(tile, fill=1.0)
    except Exception as exc:  # noqa: BLE001
        log.debug("share package thumbnail failed", error=type(exc).__name__)
        return None


async def _build_package(session: AsyncSession, media: MediaItem, path: Path) -> SharePayload:
    from packages.bundle import manifest_for_media
    from packages.export import export_single_html
    from packages.manifest import COVER_NAME, slugify

    if not path.is_dir() or not (path / COVER_NAME).is_file():
        raise ShareBuildError("This package's files are missing from disk.")
    manifest = await manifest_for_media(session, media)
    if manifest is None:
        raise ShareBuildError("This package couldn't be read.")
    slug = slugify(manifest.get("slug") or manifest.get("title") or "package")
    html = await asyncio.to_thread(export_single_html, path)
    html = _PATHISH_TEXT.sub("#", html)
    zip_bytes = await asyncio.to_thread(_package_zip, path, manifest, slug)
    thumb = await asyncio.to_thread(_package_thumbnail, path)
    return SharePayload(
        media_type="package",
        file=Part("index.html", html.encode("utf-8"), "text/html"),
        members=[Part(f"{slug}.zip", zip_bytes, "application/zip")],
        thumbnail=thumb,
        structured_content={
            "version": 1,
            "zip": f"{slug}.zip",
            "zipBytes": len(zip_bytes),
            "memberCount": len(manifest.get("members") or []),
        },
    )


# Sets and grids ---------------------------------------------------------------

async def _composite_content(session: AsyncSession, media: MediaItem, media_type: str) -> dict:
    from container_service import get_normalized_container_content
    from structured_media import read_composite_content, resolve_grid_references, resolve_set_references

    content = await get_normalized_container_content(session, container_media=media)
    if content is not None:
        return content
    raw = await read_composite_content(session, media)
    if not raw:
        raise ShareBuildError(f"This {media_type} couldn't be read.")
    base = Path(media.file_path)
    if media_type == "set":
        return await resolve_set_references(session, raw, base)
    return await resolve_grid_references(session, raw, base)


def composite_member_path(entry: dict, base: Path) -> Optional[Path]:
    from structured_media import resolve_path

    resolved = entry.get("resolved") or {}
    candidate = resolved.get("file_path")
    if candidate and Path(candidate).is_file():
        return Path(candidate)
    ref = entry.get("path")
    if ref:
        p = resolve_path(base, ref)
        if p.is_file():
            return p
    return None


def _composite_sheet(paths: list[Path]) -> Optional[bytes]:
    """Contact sheet of the first members, on the matte."""
    import math

    from utils.image_ops import open_oriented

    images = [p for p in paths if p.suffix.lower().lstrip(".") in IMAGE_FORMATS][:16]
    if not images:
        return None
    n = len(images)
    cols = min(n, math.ceil(math.sqrt(n * OG_WIDTH / OG_HEIGHT)))
    rows = math.ceil(n / cols)
    gap = 8
    cell_w = (OG_WIDTH - gap * (cols + 1)) // cols
    cell_h = (OG_HEIGHT - gap * (rows + 1)) // rows
    canvas = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), MATTE)
    for i, p in enumerate(images):
        try:
            img = open_oriented(p)
            img.thumbnail((cell_w, cell_h), Image.LANCZOS)
            img = img.convert("RGBA")
            x = gap + (i % cols) * (cell_w + gap) + (cell_w - img.width) // 2
            y = gap + (i // cols) * (cell_h + gap) + (cell_h - img.height) // 2
            canvas.paste(img, (x, y), img)
            img.close()
        except Exception:  # noqa: BLE001
            continue
    return _webp(canvas)


async def _build_composite(session: AsyncSession, media: MediaItem, media_type: str) -> SharePayload:
    content = await _composite_content(session, media, media_type)
    base = Path(media.file_path)
    entries = content.get("items" if media_type == "set" else "cells") or []
    members: list[Part] = []
    sources: list[Path] = []
    public_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = composite_member_path(entry, base)
        if path is None:
            continue
        part = await atomic_part(path, str(len(members)))
        if part is None:
            continue
        public: dict[str, Any] = {}
        if media_type == "grid":
            try:
                public["row"] = int(entry.get("row"))
                public["col"] = int(entry.get("col"))
            except (TypeError, ValueError):
                continue
        public["member"] = len(members)
        for key in ("title", "caption"):
            label = _clean_label(entry.get(key))
            if label:
                public[key] = label
        members.append(part)
        sources.append(path)
        public_entries.append(public)
    if not members:
        raise ShareBuildError(f"None of this {media_type}'s items are available on disk.")

    structured: dict[str, Any] = {"version": 1}
    title = _clean_label(content.get("title"), 100)
    if title:
        structured["title"] = title
    description = _clean_label(content.get("description"), 500)
    if description:
        structured["description"] = description
    metadata: dict[str, Any] = {}
    if media_type == "set":
        structured["items"] = public_entries
    else:
        structured["rows"] = int(content.get("rows") or (max(e["row"] for e in public_entries) + 1))
        structured["cols"] = int(content.get("cols") or (max(e["col"] for e in public_entries) + 1))
        for key, meta_key in (("row_headers", "rowHeaders"), ("col_headers", "colHeaders")):
            headers = [(_clean_label(h, 100) or "") for h in (content.get(key) or []) if isinstance(h, (str, int, float))]
            if headers:
                structured[key] = headers
                metadata[meta_key] = headers
        structured["cells"] = public_entries
    return SharePayload(
        media_type=media_type,
        members=members,
        thumbnail=await asyncio.to_thread(_composite_sheet, sources),
        structured_content=structured,
        metadata=metadata,
    )


# Layout -----------------------------------------------------------------------

async def _build_layout(media: MediaItem, path: Path) -> SharePayload:
    index_html = path / "index.html"
    if not index_html.is_file():
        raise ShareBuildError("This layout's files are missing from disk.")
    html = _PATHISH_TEXT.sub("#", index_html.read_text(encoding="utf-8", errors="replace"))
    members: list[Part] = []
    thumb = None
    for child in sorted(path.iterdir()):
        ext = child.suffix.lower().lstrip(".")
        # The cloud inlines raster members only; Layout HTML references them by file name.
        if not child.is_file() or ext not in WEB_IMAGE_FORMATS:
            continue
        part = await asyncio.to_thread(image_part, child, child.stem, ext)
        members.append(Part(child.name, part.data, part.content_type))
        if thumb is None:
            thumb = await asyncio.to_thread(image_og_thumbnail, child)
    return SharePayload(
        media_type="layout",
        file=Part("index.html", html.encode("utf-8"), "text/html"),
        members=members,
        thumbnail=thumb,
    )


# Entry points ─────────────────────────────────────────────────────────────────

async def build_payload(session: AsyncSession, media: MediaItem) -> SharePayload:
    """Everything a share of ``media`` uploads, ready for the cloud form."""
    media_type = share_media_type(media.file_format)
    if media_type is None:
        raise ShareBuildError("This kind of file can't be shared as a link yet.")
    path = Path(media.file_path)
    if media_type == "image":
        payload = await _build_image(media, path)
    elif media_type == "video":
        payload = await _build_video(media, path)
    elif media_type == "audio":
        payload = await _build_audio(media, path)
    elif media_type == "vector":
        payload = await _build_vector(media, path)
    elif media_type == "text":
        payload = await _build_text(session, media, path)
    elif media_type == "sprite":
        payload = await _build_sprite(session, media)
    elif media_type == "package":
        payload = await _build_package(session, media, path)
    elif media_type == "layout":
        payload = await _build_layout(media, path)
    else:
        payload = await _build_composite(session, media, media_type)
    payload.metadata = {**_base_metadata(media, media_type), **payload.metadata}
    if payload.structured_content is not None:
        payload.structured_content = scrub_public(payload.structured_content)
    return payload


def _dir_bytes(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def _file_bytes(path: Optional[Path]) -> int:
    try:
        return path.stat().st_size if path is not None and path.is_file() else 0
    except OSError:
        return 0


async def estimate_upload_bytes(session: AsyncSession, media: MediaItem) -> int:
    """Cheap estimate of the upload size, for pre-check (no encoding or transcoding)."""
    media_type = share_media_type(media.file_format)
    path = Path(media.file_path)
    if media_type in ("image", "video", "audio", "vector"):
        return _file_bytes(path)
    if media_type == "text":
        from structured_media import read_markdown_file

        total = _file_bytes(path)
        parsed = read_markdown_file(path) if path.is_file() else None
        seen: set[int] = set()
        for m in _INLINE_LINK.finditer((parsed or {}).get("content") or ""):
            target = m.group(3).strip("<>")
            if m.group(1) and _is_local_ref(target):
                ref = await _media_for_markdown_ref(session, target, path)
                if ref is not None and ref.id not in seen:
                    seen.add(ref.id)
                    total += _file_bytes(Path(ref.file_path))
        return total
    if media_type in ("set", "grid"):
        try:
            content = await _composite_content(session, media, media_type)
        except ShareBuildError:
            return 0
        entries = content.get("items" if media_type == "set" else "cells") or []
        return sum(_file_bytes(composite_member_path(e, path)) for e in entries if isinstance(e, dict))
    if media_type == "sprite":
        from sprite_document import resolved_sprite_content_for_media

        content = await resolved_sprite_content_for_media(session, media) or {}
        total = 0
        for entry in content.get("animations") or []:
            if isinstance(entry, dict):
                resolved = (entry.get("animation") or {}).get("resolved") or {}
                fp = resolved.get("file_path")
                total += _file_bytes(Path(fp)) if fp else 0
        return total
    if media_type == "package":
        # The zip holds the bundle; the cover inlines a subset of it again.
        return _dir_bytes(path) + _file_bytes(path / "index.html")
    if media_type == "layout":
        return _dir_bytes(path)
    return 0

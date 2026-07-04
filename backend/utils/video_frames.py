"""Extract a still frame from a video using ffmpeg.

Frame grab happens at the UI ingestion point (when a video is dropped into an
image slot): we turn the video into a still image, cache it in the
reference-prep cache, and from then on it behaves exactly like an image. We use
ffmpeg (bundled) rather than client-side canvas capture so it works for any
codec the web view can't decode and never depends on the browser.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Literal, Tuple

from PIL import Image

from ffmpeg_checker import FFmpegChecker
from core.logging import get_logger

log = get_logger(__name__)

FramePosition = Literal["first", "last", "middle", "custom"]

# Backing off a touch from the very end so "last" lands on real decoded pixels
# rather than past-the-end emptiness.
_LAST_FRAME_BACKOFF = 0.1


def _parse_fps(rate: str | None) -> float:
    """Parse an ffprobe frame-rate string like '30000/1001' into fps."""
    if not rate:
        return 0.0
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _probe(video_path: str | Path) -> Tuple[float, float]:
    """Best-effort (duration_seconds, fps); either may be 0.0 if unknown."""
    import ffmpeg

    try:
        info = ffmpeg.probe(str(video_path))
    except Exception as e:  # ffprobe missing or unreadable file
        log.debug(f"ffprobe failed for {video_path}: {e}")
        return 0.0, 0.0

    duration = 0.0
    fmt_dur = info.get("format", {}).get("duration")
    if fmt_dur:
        try:
            duration = float(fmt_dur)
        except (TypeError, ValueError):
            duration = 0.0

    fps = 0.0
    for stream in info.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        if not duration and stream.get("duration"):
            try:
                duration = float(stream["duration"])
            except (TypeError, ValueError):
                pass
        # Prefer average frame rate; fall back to the (possibly variable) base rate.
        fps = _parse_fps(stream.get("avg_frame_rate")) or _parse_fps(stream.get("r_frame_rate"))
        break
    return duration, fps


def _probe_duration(video_path: str | Path) -> float:
    return _probe(video_path)[0]


def probe_video_info(video_path: str | Path) -> Tuple[float, float]:
    """Best-effort (duration_seconds, fps) for a video; either may be 0.0 if unknown."""
    return _probe(video_path)


def _resolve_time(position: FramePosition, duration: float, time_seconds: float | None, fps: float = 0.0) -> float:
    """Map a position/time request to a concrete seek timestamp."""
    if position == "first":
        return 0.0
    if position == "last":
        # Back off by exactly one frame (matches the frontend's optimistic preview)
        # so the committed timestamp still rounds to the last frame index, not the
        # one before it. Fall back to a fixed backoff if fps is unknown.
        backoff = (1.0 / fps) if fps > 0 else _LAST_FRAME_BACKOFF
        return max(0.0, duration - backoff) if duration else 0.0
    if position == "middle":
        return duration / 2 if duration else 0.0
    # custom
    t = float(time_seconds or 0.0)
    if duration:
        t = min(t, max(0.0, duration - 0.05))
    return max(0.0, t)


def extract_frame_to_image(
    video_path: str | Path,
    position: FramePosition = "first",
    time_seconds: float | None = None,
) -> Tuple[Image.Image, float, float, float]:
    """Decode a single full-resolution frame from a video.

    Returns (image, time_used_seconds, duration_seconds, fps). Raises RuntimeError
    if ffmpeg is unavailable, and ValueError if no frame could be decoded.
    """
    import ffmpeg

    ffmpeg_available, _ = FFmpegChecker().check_availability()
    if not ffmpeg_available:
        raise RuntimeError(
            "FFmpeg is required to read a frame from a video. " + FFmpegChecker().get_install_instructions()
        )

    duration, fps = _probe(video_path)
    t = _resolve_time(position, duration, time_seconds, fps)

    def _grab(seek: float) -> bytes | None:
        # Input-side seek (fast); accurate enough for first/last/scrub MVP.
        try:
            out, _ = (
                ffmpeg.input(str(video_path), ss=seek)
                .output("pipe:", vframes=1, format="image2", vcodec="mjpeg")
                .run(capture_stdout=True, capture_stderr=True)
            )
            return out
        except ffmpeg.Error as e:
            # ffmpeg-python's Error.__str__ is a fixed "see stderr" placeholder;
            # the actual diagnostic only lives on e.stderr, so log it explicitly
            # or it's lost entirely.
            stderr = (e.stderr or b"").decode(errors="replace").strip()
            log.error(f"ffmpeg failed to grab frame at t={seek:.3f}s from {video_path}: {stderr}")
            return None

    out = _grab(t)
    if not out and t > 0.0:
        # Seeking near the end can land past the last decodable frame; fall back.
        log.debug(f"No frame at t={t} for {video_path}; falling back to first frame")
        out = _grab(0.0)
        t = 0.0
    if not out:
        raise ValueError("Could not decode a frame from the video.")

    img = Image.open(BytesIO(out))
    img.load()
    return img, t, duration, fps


def build_filmstrip(video_path: str | Path, count: int = 12, cell_w: int = 96) -> Image.Image:
    """Build a horizontal montage of `count` frames sampled evenly across the clip.

    Returns one RGB image (count * cell_w wide). Used as the frame-picker timeline.
    Raises RuntimeError if ffmpeg is unavailable, ValueError if nothing decoded.
    """
    ffmpeg_available, _ = FFmpegChecker().check_availability()
    if not ffmpeg_available:
        raise RuntimeError("FFmpeg is required to build a frame strip.")

    duration, _ = _probe(video_path)
    count = max(2, min(count, 24))
    if duration > 0:
        times = [duration * (i + 0.5) / count for i in range(count)]
    else:
        times = [0.0]

    # Square, center-cropped cells (cover) so frames aren't horizontally squished
    # into "portrait slices" — they read as proper thumbnails in the timeline.
    cells: list[Image.Image] = []
    for t in times:
        try:
            img, _, _, _ = extract_frame_to_image(video_path, "custom", t)
        except Exception as e:
            log.debug(f"filmstrip cell at {t:.2f}s failed: {e}")
            continue
        rgb = img.convert("RGB")
        side = min(rgb.width, rgb.height)
        left = (rgb.width - side) // 2
        top = (rgb.height - side) // 2
        square = rgb.crop((left, top, left + side, top + side)).resize((cell_w, cell_w), Image.LANCZOS)
        cells.append(square)

    if not cells:
        raise ValueError("Could not build a frame strip from this video.")

    strip = Image.new("RGB", (cell_w * len(cells), cell_w), (8, 11, 16))
    for i, c in enumerate(cells):
        strip.paste(c, (i * cell_w, 0))
    return strip

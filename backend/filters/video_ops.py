"""Apply built-in chain filters to videos, frame by frame.

The built-in filters (blur, levels, vignette, …) are per-pixel/geometry
operations defined for a single PIL image in ``filters.ops``. To run them on a
video we decode the input with ffmpeg into raw RGB frames, push each frame
through the *same* ``apply_builtin_filter`` the image path uses, and re-encode
with ffmpeg — muxing the original audio back in.

Output dimensions are taken from the first processed frame, so geometry filters
(crop / resize) that change size still produce a consistent stream. The work is
streamed (one frame in memory at a time) so long clips don't blow up RAM.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import numpy as np
from PIL import Image

from core.logging import get_logger

from .ops import apply_builtin_filter

log = get_logger(__name__)


def _ensure_ffmpeg() -> None:
    from ffmpeg_checker import get_ffmpeg_checker

    checker = get_ffmpeg_checker()
    ffmpeg_ok, ffprobe_ok = checker.check_availability()
    if not ffmpeg_ok or not ffprobe_ok:
        raise RuntimeError(
            "FFmpeg is required to apply filters to video but was not found.\n\n"
            + checker.get_install_instructions()
        )


def _probe(input_path: str) -> Dict[str, Any]:
    """Return width, height, fps and audio presence for a video."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "csv=p=0", input_path],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"Could not read video stream: {input_path}")
    parts = out.stdout.strip().split(",")
    width, height = int(parts[0]), int(parts[1])

    fps = 30.0
    if len(parts) > 2 and parts[2] and "/" in parts[2]:
        num, den = parts[2].split("/")
        try:
            fps = float(num) / float(den) if float(den) else 30.0
        except (ValueError, ZeroDivisionError):
            fps = 30.0

    audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", input_path],
        capture_output=True, text=True, timeout=30,
    )
    has_audio = bool(audio.stdout.strip())

    return {"width": width, "height": height, "fps": fps, "has_audio": has_audio}


def _read_exact(stream, n: int) -> Optional[bytes]:
    """Read exactly ``n`` bytes from a pipe; None at EOF / incomplete frame."""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None  # EOF (a partial trailing frame is discarded)
        buf.extend(chunk)
    return bytes(buf)


def _spawn_encoder(
    output_path: str,
    width: int,
    height: int,
    fps: float,
    audio_src: str,
    has_audio: bool,
    stderr_file,
) -> subprocess.Popen:
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "-",
    ]
    if has_audio:
        # Second input supplies the original audio track; map it alongside the
        # filtered video and stop at the shorter stream so A/V stay in sync.
        cmd += ["-i", audio_src, "-map", "0:v:0", "-map", "1:a:0?",
                "-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-map", "0:v:0"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=stderr_file)


def apply_builtin_filter_video(
    filter_id: str,
    input_path: str,
    output_path: str,
    settings: Dict[str, Any],
    *,
    interrupt_checker: Optional[Callable[[], bool]] = None,
) -> str:
    """Apply one built-in filter to every frame of ``input_path`` -> ``output_path``.

    Settings overlay the filter def's defaults (handled per-frame by
    ``apply_builtin_filter``). Returns ``output_path``.
    """
    _ensure_ffmpeg()
    info = _probe(input_path)
    in_w, in_h, fps, has_audio = info["width"], info["height"], info["fps"], info["has_audio"]
    frame_bytes = in_w * in_h * 3

    decoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", input_path,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    encoder: Optional[subprocess.Popen] = None
    out_w = out_h = 0
    frame_count = 0
    enc_stderr = tempfile.TemporaryFile()

    try:
        while True:
            if interrupt_checker is not None and interrupt_checker():
                raise RuntimeError("Video filtering cancelled")

            raw = _read_exact(decoder.stdout, frame_bytes)
            if raw is None:
                break

            frame = np.frombuffer(raw, dtype=np.uint8).reshape(in_h, in_w, 3)
            out_img = apply_builtin_filter(filter_id, Image.fromarray(frame, mode="RGB"), settings)
            out_arr = np.asarray(out_img.convert("RGB"), dtype=np.uint8)

            if encoder is None:
                # First frame fixes the output geometry. libx264 + yuv420p needs
                # even dimensions, so trim at most one pixel per axis.
                h0, w0 = out_arr.shape[:2]
                out_w, out_h = w0 - (w0 % 2), h0 - (h0 % 2)
                encoder = _spawn_encoder(
                    output_path, out_w, out_h, fps, input_path, has_audio, enc_stderr
                )

            # Keep every frame at the locked-in size (defensive — the filters are
            # deterministic, so this only ever crops the even-dimension pixel).
            if out_arr.shape[0] != out_h or out_arr.shape[1] != out_w:
                out_arr = out_arr[:out_h, :out_w]
            encoder.stdin.write(out_arr.tobytes())
            frame_count += 1

        decoder.stdout.close()
        decoder.wait()

        if encoder is None or frame_count == 0:
            raise RuntimeError(f"No frames decoded from video: {input_path}")

        encoder.stdin.close()
        if encoder.wait() != 0:
            enc_stderr.seek(0)
            detail = enc_stderr.read().decode("utf-8", "replace").strip()
            raise RuntimeError(f"ffmpeg failed to encode filtered video: {detail}")

        log.info(f"[filter:video] {filter_id}: {frame_count} frames -> {out_w}x{out_h} {output_path}")
        return output_path

    finally:
        enc_stderr.close()
        for proc in (decoder, encoder):
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass


def apply_reverse_video(input_path: str, output_path: str) -> str:
    """Reverse a video's frames (and its audio track, if present) end-to-end.

    Every filter above is per-frame: it reads one frame, transforms it, writes
    it, and never needs to see another frame. Reverse can't work that way —
    the first output frame is the *last* input frame, so nothing can be
    emitted until the whole clip has been read. That rules out the streaming
    pipeline in ``apply_builtin_filter_video``, so this shells out to ffmpeg's
    own ``reverse``/``areverse`` filters, which buffer the full clip
    internally. Returns ``output_path``.
    """
    _ensure_ffmpeg()
    has_audio = _probe(input_path)["has_audio"]

    cmd = ["ffmpeg", "-v", "error", "-y", "-i", input_path, "-vf", "reverse"]
    cmd += ["-af", "areverse"] if has_audio else ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to reverse video: {result.stderr.strip()}")

    log.info(f"[filter:video] reverse: {input_path} -> {output_path}")
    return output_path


# Filters that operate on the whole clip at once rather than frame-by-frame —
# apply_builtin_filter_video's per-frame pipeline can't express them, so each
# gets its own whole-clip function here instead of an entry in
# filters.ops.FILTER_HANDLERS. Every def with no per-frame handler must have
# one here (asserted in tests/test_postprocessing_filters.py).
WHOLE_CLIP_VIDEO_FILTERS: Dict[str, Callable[[str, str], str]] = {
    "reverse": apply_reverse_video,
}

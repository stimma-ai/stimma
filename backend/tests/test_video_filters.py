"""Built-in chain filters applied to video (filters/video_ops.py).

Filters are media-agnostic: the same per-frame PIL math runs on every decoded
frame and the clip is re-encoded. These tests synthesize a tiny clip with
ffmpeg, run a few representative filters, and assert the output is a valid video
with the expected geometry. Skipped when ffmpeg/ffprobe aren't installed.
"""

import shutil
import subprocess

import pytest

from filters.video_ops import apply_builtin_filter_video

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def _make_clip(path, size="64x48", rate=10, duration=1, audio=False) -> str:
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={duration}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


def _probe_dims(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_read_packets",
         "-count_packets", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip().split(",")
    return int(out[0]), int(out[1]), int(out[2])


def _has_audio(path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return bool(out)


@requires_ffmpeg
def test_blur_preserves_geometry_and_frames(tmp_path):
    src = _make_clip(tmp_path / "in.mp4")
    out = apply_builtin_filter_video("blur", src, str(tmp_path / "out.mp4"), {"amount": 40})

    w, h, frames = _probe_dims(out)
    assert (w, h) == (64, 48)
    assert frames >= 9  # ~10 frames for a 1s @ 10fps clip


@requires_ffmpeg
def test_levels_runs(tmp_path):
    src = _make_clip(tmp_path / "in.mp4")
    out = apply_builtin_filter_video(
        "levels", src, str(tmp_path / "out.mp4"),
        {"brightness": 20, "contrast": 10, "saturation": -30},
    )
    w, h, frames = _probe_dims(out)
    assert (w, h) == (64, 48)
    assert frames >= 9


@requires_ffmpeg
def test_resize_changes_dimensions(tmp_path):
    src = _make_clip(tmp_path / "in.mp4")
    out = apply_builtin_filter_video("resize", src, str(tmp_path / "out.mp4"), {"long_edge": 32})
    w, h, _ = _probe_dims(out)
    # 64x48 scaled so the long edge is 32 -> 32x24 (both already even).
    assert (w, h) == (32, 24)


@requires_ffmpeg
def test_crop_changes_aspect(tmp_path):
    src = _make_clip(tmp_path / "in.mp4")
    out = apply_builtin_filter_video("crop", src, str(tmp_path / "out.mp4"), {"aspect": "1:1"})
    w, h, _ = _probe_dims(out)
    # 64x48 cropped to 1:1 -> 48x48.
    assert (w, h) == (48, 48)


@requires_ffmpeg
def test_audio_is_preserved(tmp_path):
    src = _make_clip(tmp_path / "in.mp4", audio=True)
    assert _has_audio(src)
    out = apply_builtin_filter_video("vignette", src, str(tmp_path / "out.mp4"), {"amount": 50})
    assert _has_audio(out)


@requires_ffmpeg
def test_odd_dimensions_are_evened(tmp_path):
    # 65x49 -> filters keep size; encoder needs even dims, so output trims to 64x48.
    src = _make_clip(tmp_path / "in.mp4", size="65x49")
    out = apply_builtin_filter_video("glow", src, str(tmp_path / "out.mp4"), {"amount": 30})
    w, h, _ = _probe_dims(out)
    assert w % 2 == 0 and h % 2 == 0
    assert (w, h) == (64, 48)

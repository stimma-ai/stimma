"""Built-in chain filters applied to video (filters/video_ops.py).

Most filters are media-agnostic: the same per-frame PIL math runs on every
decoded frame and the clip is re-encoded (apply_builtin_filter_video). Reverse
is the exception — a whole-clip temporal op with no per-frame handler, applied
via apply_reverse_video instead (see WHOLE_CLIP_VIDEO_FILTERS). These tests
synthesize a tiny clip with ffmpeg, run a few representative filters, and
assert the output is a valid video with the expected geometry. Skipped when
ffmpeg/ffprobe aren't installed.
"""

import shutil
import subprocess

import pytest

from filters.video_ops import apply_builtin_filter_video, apply_reverse_video

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


def _make_fade_clip(path, size="64x48", rate=10, duration=1) -> str:
    """A clip that fades black -> white over its duration — a deterministic,
    monotonic brightness ramp so reversal is checkable without decoding
    against exact source bytes (the encoder is lossy). fade=in on a white
    source ramps from black up to white; on a black source it would stay
    black throughout, since "fade in" means "from black to the source".
    """
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
           f"color=c=white:s={size}:d={duration}:r={rate},fade=t=in:st=0:d={duration}",
           str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


def _decode_frames(path, w, h):
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    )
    frame_bytes = w * h * 3
    raw = proc.stdout
    n = len(raw) // frame_bytes
    return [raw[i * frame_bytes:(i + 1) * frame_bytes] for i in range(n)]


def _mean(frame: bytes) -> float:
    return sum(frame) / len(frame)


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


# --- reverse: a whole-clip op, not a per-frame one (see WHOLE_CLIP_VIDEO_FILTERS) ---

@requires_ffmpeg
def test_reverse_flips_frame_order(tmp_path):
    src = _make_fade_clip(tmp_path / "in.mp4", size="64x48", rate=10, duration=1)
    out = apply_reverse_video(str(src), str(tmp_path / "out.mp4"))

    w, h, in_frame_count = _probe_dims(src)
    _, _, out_frame_count = _probe_dims(out)
    assert out_frame_count == in_frame_count

    in_means = [_mean(f) for f in _decode_frames(src, w, h)]
    out_means = [_mean(f) for f in _decode_frames(out, w, h)]
    # Source ramps dark -> bright; reversed should ramp bright -> dark.
    assert out_means[0] == pytest.approx(in_means[-1], abs=8)
    assert out_means[-1] == pytest.approx(in_means[0], abs=8)
    assert out_means[0] > out_means[-1]


@requires_ffmpeg
def test_reverse_reverses_audio(tmp_path):
    src = _make_clip(tmp_path / "in.mp4", audio=True)
    assert _has_audio(src)
    out = apply_reverse_video(str(src), str(tmp_path / "out.mp4"))
    assert _has_audio(out)


@requires_ffmpeg
def test_reverse_handles_clip_with_no_audio(tmp_path):
    src = _make_clip(tmp_path / "in.mp4", audio=False)
    assert not _has_audio(src)
    out = apply_reverse_video(str(src), str(tmp_path / "out.mp4"))
    assert not _has_audio(out)

"""Audio metadata extraction across every supported audio format.

Policy: all audio media must get duration, sample rate, channels, and codec
extracted. bit_depth is only meaningful for PCM/lossless formats (wav/flac);
lossy codecs (aac/mp3/ogg) legitimately report none.

These tests synthesize a tiny real audio file per format with ffmpeg and assert
the extractor (media_scanner.get_audio_metadata) populates the fields. This is
the surveillance layer: if a format regresses (e.g. m4a/aac stops yielding
sample rate), a test here goes red instead of the gap being discovered by hand.

Skipped when ffmpeg/ffprobe aren't installed.
"""

import shutil
import subprocess

import pytest

from media_scanner import get_audio_metadata

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)

# (extension, extra encoder args) for each supported audio format.
# Matches media_scanner.AUDIO_EXTENSIONS.
AUDIO_FORMATS = [
    ("wav", []),
    ("mp3", []),
    ("flac", []),
    ("aac", []),
    ("m4a", []),
    ("ogg", []),
]

# Codecs that carry a real per-sample bit depth (PCM / lossless).
BIT_DEPTH_FORMATS = {"wav", "flac"}


def _make_audio(path, ext, duration=1, sample_rate=44100, channels=2) -> str:
    """Synthesize a real audio file of the given format with ffmpeg."""
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}:sample_rate={sample_rate}",
        "-ac", str(channels),
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


@requires_ffmpeg
@pytest.mark.parametrize("ext,_extra", AUDIO_FORMATS)
def test_get_audio_metadata_populates_core_fields(tmp_path, ext, _extra):
    """Every supported audio format yields duration, sample rate, channels, codec."""
    src = _make_audio(tmp_path / f"clip.{ext}", ext, duration=1, sample_rate=44100, channels=2)

    meta = get_audio_metadata(src)

    # Duration ~1s (encoder priming can shift it slightly).
    assert meta["duration"] is not None, f"{ext}: missing duration"
    assert 0.5 < meta["duration"] < 2.0, f"{ext}: implausible duration {meta['duration']}"

    assert meta["sample_rate"] == 44100, f"{ext}: sample_rate={meta['sample_rate']}"
    assert meta["channels"] == 2, f"{ext}: channels={meta['channels']}"
    assert meta["codec"], f"{ext}: missing codec"
    assert meta["bitrate"] is not None, f"{ext}: missing bitrate"

    if ext in BIT_DEPTH_FORMATS:
        assert meta["bit_depth"] and meta["bit_depth"] > 0, f"{ext}: missing bit_depth"


@requires_ffmpeg
def test_get_audio_metadata_mono_m4a():
    """Regression: mono m4a (Apple Voice Memos) — the reported broken case.

    A 48kHz mono AAC-in-MP4 file (the shape iOS Voice Memos produces) must
    still yield duration, sample rate, and channels even though bit_depth is
    absent for AAC.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path
        src = _make_audio(Path(d) / "memo.m4a", "m4a",
                          duration=3, sample_rate=48000, channels=1)
        meta = get_audio_metadata(src)

    assert meta["sample_rate"] == 48000
    assert meta["channels"] == 1
    assert meta["duration"] is not None and 2.0 < meta["duration"] < 4.0
    assert meta["codec"] == "aac"


@requires_ffmpeg
async def test_upload_audio_extracts_metadata(generation_app, tmp_path):
    """End-to-end: uploading audio persists duration + sample rate + channels.

    Uploads set metadata_status='completed', so the background metadata pass
    never backfills audio fields — the upload path itself must extract them.
    This guards the wiring that was missing for uploaded audio (the reported
    m4a bug). Uses the generation_app fixture, which configures a real uploads
    folder + DB registry in a temp dir.
    """
    from upload_service import UploadService

    src = _make_audio(tmp_path / "voice.m4a", "m4a",
                      duration=2, sample_rate=48000, channels=1)
    with open(src, "rb") as f:
        content = f.read()

    service = UploadService(profile_id="default")
    media_item, _path = await service.upload_file(content, "voice.m4a")

    assert media_item.duration is not None and media_item.duration > 0
    assert media_item.audio_sample_rate == 48000
    assert media_item.audio_channels == 1
    assert media_item.audio_codec == "aac"

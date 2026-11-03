"""Real encoding and HTTP proof for long-video playback derivatives."""
import asyncio
import hashlib
import json
import shutil
import subprocess
import time

import pytest

from tests.helpers.media import create_media_item
from utils import video_playback

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def make_video(path, *, fps="25", audio=True):
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=duration=16.4:size=320x180:rate={fps}"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=duration=16.4:sample_rate=48000"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    subprocess.run([*command, "-metadata", f"comment={path.name}", str(path)], check=True, capture_output=True, timeout=20)
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_serves_segmented_video_and_native_hls(client, db_session, tmp_path):
    source = tmp_path / "long.mp4"
    file_hash = await asyncio.to_thread(make_video, source)
    async with db_session() as session:
        await create_media_item(session, file_path=source, file_hash=file_hash, file_format="mp4", duration=16.4)
    base = f"/api/media/by-hash/{file_hash}/playback"
    response = await client.get(base, params={"profile": "default"})
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert manifest["streaming"] is True
    assert manifest["segment_count"] == 9
    assert manifest["segment_duration"] == 2
    assert manifest["has_audio"] is True
    assert "avc1." in manifest["mime_type"]
    init = await client.get(f"{base}/v1/small/init.mp4", params={"profile": "default"})
    segments = []
    for i in range(manifest["segment_count"]):
        segment = await client.get(f"{base}/v1/small/segment-{i}.m4s", params={"profile": "default"})
        assert segment.status_code == 200
        assert "immutable" in segment.headers["cache-control"]
        segments.append(segment.content)
    joined = tmp_path / "joined.mp4"
    joined.write_bytes(init.content + b"".join(segments))
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_packets", "-show_entries",
        "packet=codec_type,pts_time,duration_time", "-of", "json", str(joined),
    ], timeout=10))
    for kind in ("video", "audio"):
        packets = [p for p in probe["packets"] if p["codec_type"] == kind]
        assert float(packets[0]["pts_time"]) == pytest.approx(0, abs=0.001)
        end = float(packets[-1]["pts_time"]) + float(packets[-1]["duration_time"])
        # AAC's final packet can extend past the video by less than one frame;
        # older FFmpeg versions retain that packet's full duration.
        tolerance = 1024 / manifest["sample_rate"] if kind == "audio" else 0.001
        assert end == pytest.approx(manifest["duration"], abs=tolerance)
    assert len(segments[0]) < sum(map(len, segments)) / 3
    playlist = await client.get(f"{base}/v1/small/index.m3u8", params={"profile": "default"})
    assert playlist.status_code == 200
    assert '#EXT-X-MAP:URI="init.mp4?profile=default"' in playlist.text
    assert "segment-8.m4s?profile=default" in playlist.text
    master = await client.get(f"{base}/v1/auto/index.m3u8", params={"profile": "default"})
    assert "../small/index.m3u8?profile=default" in master.text
    for invalid in ("small/segment-999.m4s", "bogus/init.mp4", "small/error.log"):
        result = await client.get(f"{base}/v1/{invalid}", params={"profile": "default"})
        assert result.status_code == 404
    # Cache hits must not probe or re-encode the original.
    root = video_playback.cache_dir(file_hash)
    before = (root / "small" / "segment-0.m4s").stat().st_mtime_ns
    assert (await client.get(base, params={"profile": "default"})).status_code == 200
    assert (root / "small" / "segment-0.m4s").stat().st_mtime_ns == before


@pytest.mark.parametrize("fps", ["30000/1001", "24"])
async def test_fractional_frame_rates_and_silent_video(tmp_path, monkeypatch, fps):
    monkeypatch.setenv("STIMMA_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "silent.mp4"
    file_hash = await asyncio.to_thread(make_video, source, fps=fps, audio=False)
    manifest = await asyncio.to_thread(video_playback.describe, source, file_hash)
    assert manifest["has_audio"] is False
    last = await video_playback.part(source, file_hash, "small", f"segment-{manifest['segment_count'] - 1}.m4s")
    assert last.is_file()
    init = await video_playback.part(source, file_hash, "small", "init.mp4")
    assert 'mp4a' not in video_playback.mime_type(init.read_bytes(), False)


def test_threshold_preserves_small_loops():
    assert not video_playback.needs_streaming(2, 100_000)
    assert video_playback.needs_streaming(120, 100_000)
    assert video_playback.needs_streaming(2, 6 * 1024 * 1024)


async def test_fragments_are_published_before_completion_and_deletion_stops_writers(tmp_path, monkeypatch):
    monkeypatch.setenv("STIMMA_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "incremental.mp4"
    file_hash = await asyncio.to_thread(make_video, source)
    await asyncio.to_thread(video_playback.describe, source, file_hash)
    original = video_playback._read_box
    def slow_read(stream):
        time.sleep(0.025)
        return original(stream)
    monkeypatch.setattr(video_playback, "_read_box", slow_read)
    first, same = await asyncio.gather(*[
        video_playback.part(source, file_hash, "small", "segment-0.m4s") for _ in range(2)
    ])
    assert first == same
    root = video_playback.cache_dir(file_hash)
    assert not (root / "small" / "complete").exists(), "first segment must not wait for the whole encode"
    await asyncio.to_thread(video_playback.stop, file_hash)
    files = set(root.rglob("*.m4s"))
    await asyncio.sleep(0.1)
    assert set(root.rglob("*.m4s")) == files, "cancelled encoder must not recreate deleted fragments"
    assert not (root / "small" / "complete").exists()

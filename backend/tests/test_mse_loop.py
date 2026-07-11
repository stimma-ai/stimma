"""Integration tests for seamless MSE loop preparation and serving."""

import hashlib
import shutil
import subprocess

import pytest
from httpx import AsyncClient

from tests.helpers.media import create_media_item, generate_test_image


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)


def _make_av_loop(path) -> str:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=duration=1.2:size=128x128:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1.22:sample_rate=48000",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestMseLoopPlayback:
    async def test_prepares_multiplexed_fragmented_mp4(
        self,
        client: AsyncClient,
        db_session,
        tmp_path,
    ):
        video_path = tmp_path / "loop.mp4"
        file_hash = _make_av_loop(video_path)
        async with db_session() as session:
            await create_media_item(
                session,
                file_path=video_path,
                file_hash=file_hash,
                file_format="mp4",
                duration=1.2,
            )

        manifest_response = await client.get(
            f"/api/media/by-hash/{file_hash}/mse-loop",
            params={"profile": "default"},
        )
        assert manifest_response.status_code == 200
        manifest = manifest_response.json()
        assert manifest["duration"] == pytest.approx(1.2, abs=0.05)
        assert manifest["has_audio"] is True
        assert "avc1." in manifest["mime_type"]
        assert "mp4a.40.2" in manifest["mime_type"]

        init_response = await client.get(
            f"/api/media/by-hash/{file_hash}/mse-loop/init",
            params={"profile": "default"},
        )
        segment_response = await client.get(
            f"/api/media/by-hash/{file_hash}/mse-loop/segment",
            params={"profile": "default"},
        )
        assert init_response.status_code == 200
        assert segment_response.status_code == 200
        assert b"ftyp" in init_response.content
        assert b"moov" in init_response.content
        assert b"moof" not in init_response.content
        assert b"moof" in segment_response.content

    async def test_rejects_non_video_assets(self, client: AsyncClient, db_session, tmp_path):
        image_path = tmp_path / "image.png"
        file_hash = generate_test_image(image_path)
        async with db_session() as session:
            await create_media_item(
                session,
                file_path=image_path,
                file_hash=file_hash,
                file_format="png",
            )

        response = await client.get(
            f"/api/media/by-hash/{file_hash}/mse-loop",
            params={"profile": "default"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Asset is not a video"

    async def test_unknown_asset_returns_404(self, client: AsyncClient):
        response = await client.get(
            "/api/media/by-hash/does-not-exist/mse-loop",
            params={"profile": "default"},
        )
        assert response.status_code == 404

"""
Tests for providers.lightweight.LightweightProvider.

Covers:
- Lifecycle (connect, disconnect, status transitions)
- Tool registration and listing
- Asset management (upload, download)
- Execution flow (mocking SAM3 dependency)
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import List, Optional

from PIL import Image

from providers.base import ExecutionProgress, ExecutionResult, ProviderStatus
from providers.lightweight import LightweightProvider, get_lightweight_provider
import providers.lightweight as lightweight_module


# ---------------------------------------------------------------------------
# SAM3 Mock Structures
# ---------------------------------------------------------------------------


@dataclass
class FakeBBox:
    x: float
    y: float
    width: float
    height: float


@dataclass
class FakeDetection:
    bbox: FakeBBox
    score: float
    area_percent: float = 5.0


@dataclass
class FakeSegmentResult:
    detections: List[FakeDetection]
    original_width: int
    original_height: int
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton."""
    lightweight_module._lightweight_provider = None
    yield
    lightweight_module._lightweight_provider = None


@pytest.fixture
def provider():
    return LightweightProvider()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_connect_sets_connected(self, provider):
        assert provider.status == ProviderStatus.DISCONNECTED
        await provider.connect()
        assert provider.status == ProviderStatus.CONNECTED

    async def test_disconnect_clears_state(self, provider):
        await provider.connect()
        # Add an asset
        await provider.upload_asset(b"data", "image/png")

        await provider.disconnect()

        assert provider.status == ProviderStatus.DISCONNECTED
        assert len(provider._tools) == 0
        assert len(provider._descriptors) == 0
        assert len(provider._assets) == 0

    def test_properties(self, provider):
        assert provider.provider_id == "builtin"
        assert provider.provider_name == "Built-in Tools"
        assert provider.provider_type == "builtin"
        assert provider.max_concurrent == 4


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    async def test_tools_registered_on_connect(self, provider):
        await provider.connect()
        tools = await provider.list_tools()
        tool_ids = {t.id for t in tools}
        assert "detect-objects" in tool_ids

    async def test_get_tool_by_id(self, provider):
        await provider.connect()
        tool = await provider.get_tool("detect-objects")
        assert tool is not None
        assert tool.name == "Detect Objects"
        assert tool.metadata.get("lightweight") is True

    async def test_get_tool_not_found(self, provider):
        await provider.connect()
        assert await provider.get_tool("nonexistent") is None

    async def test_tool_has_correct_task_type(self, provider):
        await provider.connect()
        detect = await provider.get_tool("detect-objects")
        assert detect.task_type == "detect-objects"


# ---------------------------------------------------------------------------
# Asset Management
# ---------------------------------------------------------------------------


class TestAssetManagement:
    async def test_upload_and_download(self, provider):
        await provider.connect()

        data = b"\x89PNG fake image data"
        asset_id = await provider.upload_asset(data, "image/png")

        assert asset_id.startswith("lightweight_")
        downloaded = await provider.download_asset(asset_id)
        assert downloaded == data

    async def test_download_missing_asset_raises(self, provider):
        await provider.connect()
        with pytest.raises(ValueError, match="Asset not found"):
            await provider.download_asset("nonexistent")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _create_test_image(tmp_path, width=100, height=100, color=(255, 0, 0)):
    """Create a test image and return its path."""
    img = Image.new("RGB", (width, height), color)
    path = tmp_path / "test_input.png"
    img.save(path)
    return str(path)


class TestExecution:
    async def test_unknown_tool_returns_error(self, provider):
        await provider.connect()

        results = []
        async for item in provider.execute("nonexistent", {}):
            results.append(item)

        # Should have starting progress + error result
        assert any(isinstance(r, ExecutionResult) and not r.success for r in results)

    async def test_detect_objects_success(self, provider, tmp_path):
        await provider.connect()
        image_path = _create_test_image(tmp_path, 300, 300)

        fake_result = FakeSegmentResult(
            detections=[
                FakeDetection(bbox=FakeBBox(10, 10, 50, 50), score=0.95, area_percent=8.0),
                FakeDetection(bbox=FakeBBox(100, 100, 30, 30), score=0.7, area_percent=3.0),
            ],
            original_width=300,
            original_height=300,
        )
        mock_sam3 = MagicMock()
        mock_sam3.segment = AsyncMock(return_value=fake_result)

        with patch("sam3_service.get_sam3_service", return_value=mock_sam3):
            results = []
            async for item in provider.execute(
                "detect-objects",
                {"input_images": [image_path], "subject": "cat"},
            ):
                results.append(item)

        final = results[-1]
        assert final.success is True
        assert final.metadata["count"] == 2
        # Sorted by score descending
        assert final.metadata["detections"][0]["score"] >= final.metadata["detections"][1]["score"]

    async def test_detect_objects_segmentation_error(self, provider, tmp_path):
        await provider.connect()
        image_path = _create_test_image(tmp_path)

        fake_result = FakeSegmentResult(
            detections=[],
            original_width=100,
            original_height=100,
            error="Model failed to load",
        )
        mock_sam3 = MagicMock()
        mock_sam3.segment = AsyncMock(return_value=fake_result)

        with patch("sam3_service.get_sam3_service", return_value=mock_sam3):
            results = []
            async for item in provider.execute(
                "detect-objects",
                {"input_images": [image_path], "subject": "dog"},
            ):
                results.append(item)

        final = results[-1]
        assert final.success is False
        assert "Segmentation failed" in final.error

    async def test_execution_yields_progress_events(self, provider, tmp_path):
        """Verify we get starting → complete → result events."""
        await provider.connect()
        image_path = _create_test_image(tmp_path, 200, 200)

        fake_result = FakeSegmentResult(
            detections=[FakeDetection(
                bbox=FakeBBox(x=10, y=10, width=50, height=50),
                score=0.9,
            )],
            original_width=200,
            original_height=200,
        )
        mock_sam3 = MagicMock()
        mock_sam3.segment = AsyncMock(return_value=fake_result)

        with patch("sam3_service.get_sam3_service", return_value=mock_sam3):
            results = []
            async for item in provider.execute(
                "detect-objects",
                {"input_images": [image_path], "subject": "face"},
            ):
                results.append(item)

        progress_events = [r for r in results if isinstance(r, ExecutionProgress)]
        assert len(progress_events) >= 2  # starting + complete
        assert progress_events[0].stage == "starting"
        assert progress_events[-1].stage == "complete"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_lightweight_provider_returns_same_instance(self):
        a = get_lightweight_provider()
        b = get_lightweight_provider()
        assert a is b


# ---------------------------------------------------------------------------
# Filter media-type gating — reverse is video-only (see filters/defs.py
# CHAIN_FILTER_DEFS "accepts"), unlike every other built-in filter.
# ---------------------------------------------------------------------------


def _create_test_video(tmp_path, duration=1, audio=False) -> str:
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "test_input.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"testsrc=size=32x32:rate=10:duration={duration}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(path)


def _video_has_audio(path) -> bool:
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return bool(out)


class TestFilterMediaTypeValidation:
    async def test_reverse_rejects_image_input(self, provider, tmp_path):
        await provider.connect()
        image_path = _create_test_image(tmp_path)

        results = []
        async for item in provider.execute("reverse", {"input_images": [image_path]}):
            results.append(item)

        final = results[-1]
        assert final.success is False
        assert "does not support image input" in final.error

    async def test_reverse_accepts_video_input(self, provider, tmp_path):
        await provider.connect()
        video_path = _create_test_video(tmp_path)

        results = []
        async for item in provider.execute("reverse", {"input_images": [video_path]}):
            results.append(item)

        final = results[-1]
        assert final.success is True

    async def test_blur_still_accepts_image_input(self, provider, tmp_path):
        """Regression: gating a video-only filter must not affect a dual-media one."""
        await provider.connect()
        image_path = _create_test_image(tmp_path)

        results = []
        async for item in provider.execute("blur", {"input_images": [image_path], "amount": 20}):
            results.append(item)

        final = results[-1]
        assert final.success is True

    async def test_reverse_audio_setting_reaches_the_whole_clip_handler(self, provider, tmp_path):
        """Wiring check: the "audio" param travels from tool parameters through
        WHOLE_CLIP_VIDEO_FILTERS into apply_reverse_video (the ffmpeg-level
        behavior itself is covered by tests/test_video_filters.py)."""
        await provider.connect()
        video_path = _create_test_video(tmp_path, audio=True)
        assert _video_has_audio(video_path)

        results = []
        async for item in provider.execute("reverse", {"input_images": [video_path], "audio": "remove"}):
            results.append(item)

        final = results[-1]
        assert final.success is True
        assert not _video_has_audio(final.metadata["output_path"])

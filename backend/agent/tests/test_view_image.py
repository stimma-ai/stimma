"""Tests for view_image: native-dimension reporting and snapshot immutability.

The agent estimates crop/bbox coordinates from what view_image shows it. Two
properties are load-bearing:

1. The reported size must be the file's NATIVE size (with the displayed,
   downscaled size stated separately) — reporting only the downscaled size
   sends every coordinate the model derives into the wrong frame.
2. The marker must point at a SNAPSHOT of the rendered pixels, not the live
   file. The conversation builder re-reads the marker path on every message
   build, so pointing at the live file means overwriting it silently rewrites
   what earlier views appear to show.
"""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from agent.v2 import conversation as conversation_module
from agent.v2.conversation import _build_view_image_result
from agent.v2.tools.view_image import view_image
from agent.v2 import vision_payload


def _write_png(path, size, color):
    Image.new("RGB", size, color).save(path, format="PNG")


@pytest.mark.asyncio
async def test_marker_reports_native_size_and_snapshots_pixels(tmp_path):
    src = tmp_path / "photo.png"
    _write_png(src, (900, 1350), (200, 30, 30))

    result = await view_image(path=str(src), detail="low", workspace_dir=str(tmp_path))
    marker = json.loads(result)

    assert marker["__view_image__"] is True
    assert marker["native_size"] == [900, 1350]
    # Displayed size is downscaled to max 512 on the long side
    assert max(marker["size"]) <= 512
    assert marker["source_path"] == str(src)
    # Marker points at a snapshot, not the source file
    assert marker["path"] != str(src)

    # Overwrite the source — the snapshot must still show the ORIGINAL pixels
    _write_png(src, (900, 1350), (30, 30, 200))
    snap = Image.open(marker["path"]).convert("RGB")
    pixel = snap.getpixel((10, 10))
    assert all(abs(actual - expected) <= 2 for actual, expected in zip(pixel, (200, 30, 30)))
    assert marker["media_type"] == "image/jpeg"
    assert marker["path"].endswith(".jpg")


@pytest.mark.asyncio
async def test_builder_text_states_native_and_displayed_size(tmp_path, monkeypatch):
    src = tmp_path / "photo.png"
    _write_png(src, (900, 1350), (10, 120, 10))

    marker = json.loads(await view_image(path=str(src), detail="low", workspace_dir=str(tmp_path)))
    monkeypatch.setattr(
        conversation_module,
        "encode_agent_jpeg",
        lambda image: pytest.fail("cached JPEG should not be re-encoded during conversation rebuild"),
    )
    built = _build_view_image_result("t1", marker)

    text_block = next(b for b in built["content"] if b["type"] == "text")
    assert "native size 900x1350px" in text_block["text"]
    assert "900x1350 frame" in text_block["text"]
    # And the image itself is attached
    image_block = next(b for b in built["content"] if b["type"] == "image_url")
    url = image_block["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]).startswith(b"\xff\xd8")


@pytest.mark.asyncio
async def test_builder_handles_legacy_marker_without_native_size(tmp_path):
    """Old markers point at the source file and carry no native_size — the
    builder derives the native size from the file's pre-resize dimensions."""
    src = tmp_path / "legacy.png"
    _write_png(src, (900, 1350), (10, 10, 10))

    marker = {"__view_image__": True, "path": str(src), "detail": "low"}
    built = _build_view_image_result("t1", marker)

    text_block = next(b for b in built["content"] if b["type"] == "text")
    assert "native size 900x1350px" in text_block["text"]


@pytest.mark.asyncio
async def test_small_image_reports_plain_size(tmp_path):
    """An image under the downscale threshold is shown as-is; no scale caveat."""
    src = tmp_path / "small.png"
    _write_png(src, (300, 200), (10, 10, 10))

    marker = json.loads(await view_image(path=str(src), detail="low", workspace_dir=str(tmp_path)))
    assert marker["native_size"] == [300, 200]
    assert marker["size"] == [300, 200]

    built = _build_view_image_result("t1", marker)
    text_block = next(b for b in built["content"] if b["type"] == "text")
    assert text_block["text"].startswith("Image loaded (300x200px)")


@pytest.mark.asyncio
async def test_library_media_reuses_persistent_jpeg_conversion(tmp_path, monkeypatch):
    assert vision_payload.AGENT_IMAGE_JPEG_QUALITY == 85
    src = tmp_path / "library.png"
    _write_png(src, (900, 1350), (80, 100, 120))
    media = SimpleNamespace(
        id=42,
        file_path=str(src),
        file_hash="a" * 64,
        width=900,
        height=1350,
        deleted_at=None,
        deletion_pending_at=None,
        face_detection_status=None,
    )

    class _Result:
        def scalar_one_or_none(self):
            return media

    class _Session:
        async def execute(self, statement):
            if statement.is_select:
                return _Result()
            return None

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(vision_payload, "get_cache_dir", lambda: cache_dir)
    session = _Session()

    first = json.loads(await view_image(media_id=42, detail="high", session=session))
    first_path = first["path"]
    first_bytes = Path(first_path).read_bytes()

    # A second view of the same immutable Media should point at the exact same
    # cached conversion rather than producing or encoding another snapshot.
    second = json.loads(await view_image(media_id=42, detail="high", session=session))
    assert second["path"] == first_path
    assert Path(first_path).read_bytes() == first_bytes
    assert first_path.startswith(str(cache_dir / "agent-vision"))

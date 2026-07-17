"""Tests for GenerationQueue.input_images / mask media-id resolution.

LLM tool calls sometimes JSON-serialize integer media IDs as strings
(``input_images=["7658"]``). The centralized resolver should treat both
shapes the same so providers always receive a real file path.
"""

import pytest
from unittest.mock import AsyncMock, patch

from generation_queue import GenerationQueue


@pytest.fixture
def queue():
    """Bare GenerationQueue — no scheduler interaction needed here."""
    return GenerationQueue()


async def _resolve(queue, task_input):
    """Run the resolver with a fake path lookup that maps ids 7658→a.png, 999→b.png."""
    async def fake_lookup(_session, media_id):
        return {7658: "/tmp/a.png", 999: "/tmp/b.png"}.get(media_id)

    with patch.object(queue, "_resolve_media_id_to_path", new=AsyncMock(side_effect=fake_lookup)):
        return await queue._resolve_media_ids_in_params(session=None, parameters=task_input)


@pytest.mark.asyncio
async def test_resolves_int_media_id_in_input_images(queue):
    out = await _resolve(queue, {"input_images": [7658]})
    assert out["input_images"] == ["/tmp/a.png"]


@pytest.mark.asyncio
async def test_resolves_digit_string_media_id_in_input_images(queue):
    """The bug: agent passes ``["7658"]`` and the provider rejects it as
    "Asset not found: 7658". Strings of digits must resolve identically to ints."""
    out = await _resolve(queue, {"input_images": ["7658"]})
    assert out["input_images"] == ["/tmp/a.png"]


@pytest.mark.asyncio
async def test_mixes_int_string_and_path_in_input_images(queue):
    """A real-world list can contain media-id ints, digit-strings, and already-resolved
    paths. Only the first two should be looked up; paths pass through."""
    out = await _resolve(queue, {"input_images": [7658, "999", "/already/path.png"]})
    assert out["input_images"] == ["/tmp/a.png", "/tmp/b.png", "/already/path.png"]


@pytest.mark.asyncio
async def test_resolves_digit_string_in_mask(queue):
    out = await _resolve(queue, {"mask": "7658"})
    assert out["mask"] == "/tmp/a.png"


@pytest.mark.asyncio
async def test_bool_is_not_treated_as_media_id(queue):
    """``isinstance(True, int)`` is True in Python — guard the coercion so a stray
    boolean doesn't try to look up media-id 1."""
    out = await _resolve(queue, {"input_images": [True]})
    assert out["input_images"] == [True]  # passes through unchanged


@pytest.mark.asyncio
async def test_unresolvable_id_is_dropped(queue):
    """Legacy behavior: when the lookup returns no row, the entry drops out of
    the list and a warning is logged. The string-coercion change preserves
    that — strings of digits behave the same as ints, including the drop."""
    out = await _resolve(queue, {"input_images": ["12345", "7658"]})
    assert out["input_images"] == ["/tmp/a.png"]


class _FakeSessionCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class _FakeDB:
    def async_session_maker(self):
        return _FakeSessionCtx()


@pytest.mark.asyncio
async def test_lineage_resolves_int_media_id_in_input_videos(queue):
    """Agents pass library media ids directly in input_videos. The lineage
    builder used to hand the raw int to os.path.basename (TypeError: expected
    str, bytes or os.PathLike object, not int) and fail the whole job."""
    async def fake_id_to_path(_session, media_id):
        return {9651: "/tmp/vid.mp4"}.get(media_id)

    with patch.object(queue, "_get_db", return_value=_FakeDB()), \
         patch.object(queue, "_resolve_media_id_to_path", new=AsyncMock(side_effect=fake_id_to_path)), \
         patch.object(queue, "_get_inherited_lineage", new=AsyncMock(return_value=[])):
        out = await queue._resolve_lineage(
            {"input_videos": [9651]}, "video-to-video", "default"
        )

    assert out["source_inputs"] == [
        {"media_id": 9651, "file_path": "/tmp/vid.mp4", "role": "input_video"}
    ]


@pytest.mark.asyncio
async def test_lineage_resolves_digit_string_media_id_in_input_videos(queue):
    async def fake_id_to_path(_session, media_id):
        return {9651: "/tmp/vid.mp4"}.get(media_id)

    with patch.object(queue, "_get_db", return_value=_FakeDB()), \
         patch.object(queue, "_resolve_media_id_to_path", new=AsyncMock(side_effect=fake_id_to_path)), \
         patch.object(queue, "_get_inherited_lineage", new=AsyncMock(return_value=[])):
        out = await queue._resolve_lineage(
            {"input_videos": ["9651"]}, "video-to-video", "default"
        )

    assert out["source_inputs"][0]["media_id"] == 9651
    assert out["source_inputs"][0]["file_path"] == "/tmp/vid.mp4"

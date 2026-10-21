"""Media nested in structured tool params (STP `x-media`), e.g. keyframes[].media."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from generation_queue import GenerationQueue
from providers.jsonrpc import JsonRpcProvider, StdioProviderConfig
from utils.schema_media import iter_media_leaves, map_media_leaves, media_kinds

KEYFRAMES_SCHEMA = {
    "properties": {
        "prompt": {"type": "string"},
        "input_images": {"type": "array", "items": {"type": "string"}, "x-control": "image_picker"},
        "keyframes": {
            "type": "array",
            "x-control": "keyframes",
            "items": {
                "type": "object",
                "required": ["media", "at"],
                "properties": {
                    "media": {"type": "string", "x-media": ["image", "video"]},
                    "at": {"type": "number"},
                    "length": {"type": "number"},
                },
            },
        },
        "voice": {"type": "string", "x-media": "audio"},
    }
}


def test_walker_finds_only_x_media_leaves():
    params = {
        "prompt": "hi",
        "input_images": ["/a.png"],
        "keyframes": [{"media": "/k0.png", "at": 0}, {"media": 7, "at": 2, "length": 0.9}],
        "voice": "/v.wav",
    }
    leaves = [(path, value) for path, value, _ in iter_media_leaves(params, KEYFRAMES_SCHEMA)]
    assert leaves == [
        (("keyframes", 0, "media"), "/k0.png"),
        (("keyframes", 1, "media"), 7),
        (("voice",), "/v.wav"),
    ]


@pytest.mark.asyncio
async def test_map_copies_instead_of_mutating():
    params = {"keyframes": [{"media": "/k0.png", "at": 0}]}
    out = await map_media_leaves(params, KEYFRAMES_SCHEMA, lambda v, _leaf, _path: v.upper())
    assert out["keyframes"] == [{"media": "/K0.PNG", "at": 0}]
    assert params["keyframes"] == [{"media": "/k0.png", "at": 0}]


def test_media_kinds():
    assert media_kinds({"x-media": "audio"}) == ("audio",)
    assert media_kinds({"x-media": ["image", "video"]}) == ("image", "video")
    assert media_kinds({"x-control": "audio_picker"}) == ("audio",)
    assert media_kinds({"type": "string"}) == ()


@pytest.mark.asyncio
async def test_provider_uploads_nested_media(tmp_path):
    still = tmp_path / "k0.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    provider = JsonRpcProvider(StdioProviderConfig(id="test", command="noop"))
    provider.upload_asset = AsyncMock(return_value="asset-k0.png")

    out = await provider._upload_input_assets(
        {"keyframes": [{"media": str(still), "at": 1.5}], "prompt": "x"}, KEYFRAMES_SCHEMA)

    assert out["keyframes"] == [{"media": "asset-k0.png", "at": 1.5}]
    provider.upload_asset.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["input_audios", "voice"])
async def test_video_in_an_audio_field_sends_its_soundtrack(tmp_path, field):
    video = tmp_path / "take.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 32)
    schema = {"properties": {
        "input_audios": {"type": "array", "items": {"type": "string"}, "x-control": "audio_picker"},
        "voice": {"type": "string", "x-media": "audio"},
    }}
    provider = JsonRpcProvider(StdioProviderConfig(id="test", command="noop"))
    provider.upload_asset = AsyncMock(return_value="asset.wav")
    value = [str(video)] if field == "input_audios" else str(video)

    with patch("providers.jsonrpc._transcode_av_to", new=AsyncMock(return_value=b"RIFFwav")) as transcode:
        out = await provider._upload_input_assets({field: value}, schema)

    assert out[field] == (["asset.wav"] if field == "input_audios" else "asset.wav")
    transcode.assert_awaited_once()
    assert transcode.await_args.args[1] == "audio/wav"
    provider.upload_asset.assert_awaited_once_with(b"RIFFwav", "audio/wav")


@pytest.mark.asyncio
async def test_queue_resolves_nested_library_ids():
    queue = GenerationQueue()

    async def fake_lookup(_session, media_id):
        return {41: "/lib/a.png", 42: "/lib/b.mp4"}.get(media_id)

    with patch.object(queue, "_resolve_media_id_to_path", new=AsyncMock(side_effect=fake_lookup)):
        out = await queue._resolve_nested_media_ids(None, {"keyframes": [
            {"media": 41, "at": 0}, {"media": "media:42", "at": 1}, {"media": "/x.png", "at": 2},
        ]}, KEYFRAMES_SCHEMA)

    assert [k["media"] for k in out["keyframes"]] == ["/lib/a.png", "/lib/b.mp4", "/x.png"]


@pytest.mark.asyncio
async def test_queue_records_keyframe_lineage():
    queue = GenerationQueue()

    @asynccontextmanager
    async def session_maker():
        yield None

    db = type("Db", (), {"async_session_maker": staticmethod(session_maker)})()
    params = {
        "keyframes": [{"media": "/lib/a.png", "at": 0}, {"media": "/lib/b.mp4", "at": 3}],
        "keyframes_media_ids": [41, None],
    }
    with patch.object(queue, "_get_db", return_value=db), \
            patch.object(queue, "_resolve_path_to_media_id", new=AsyncMock(return_value=42)), \
            patch.object(queue, "_get_inherited_lineage", new=AsyncMock(return_value=[])):
        out = await queue._nested_lineage(params, KEYFRAMES_SCHEMA, "profile")

    assert out["source_inputs"] == [
        {"media_id": 41, "file_path": "/lib/a.png", "role": "keyframe"},
        {"media_id": 42, "file_path": "/lib/b.mp4", "role": "keyframe"},
    ]

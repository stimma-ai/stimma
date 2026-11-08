"""Regression tests for STP JSON-RPC outbound parameter shaping."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.base import ProviderStatus, ToolDescriptor
from providers.jsonrpc import JsonRpcProvider, StdioProviderConfig, _strip_undeclared_parameters


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["contenthash", "image.png", "image.webp"])
@pytest.mark.parametrize("accepted", [False, True])
async def test_upload_detects_webp_from_bytes(tmp_path, filename, accepted):
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (2, 2), "orange").save(buffer, format="WEBP")
    payload = buffer.getvalue()
    path = tmp_path / filename
    path.write_bytes(payload)
    provider = JsonRpcProvider(StdioProviderConfig(id="test", command="noop"))
    provider.upload_asset = AsyncMock(return_value="uploaded.webp")
    prop = {"type": "array", "x-control": "image_picker"}
    if accepted:
        prop["x-accept-media"] = {"mime_types": ["image/webp"]}

    result = await provider._upload_input_assets(
        {"input_images": [str(path)]},
        {"properties": {"input_images": prop}},
    )

    assert result == {"input_images": ["uploaded.webp"]}
    provider.upload_asset.assert_awaited_once_with(payload, "image/webp")


@pytest.mark.asyncio
async def test_provider_accepts_in_progress_state():
    provider = JsonRpcProvider(StdioProviderConfig(id="comfyui", command="noop"))

    await provider._process_message({
        "jsonrpc": "2.0",
        "method": "provider.state",
        "params": {"state": "in_progress", "summary": "Downloading models"},
    })

    assert provider.provider_state == "in_progress"
    assert provider.provider_state_summary == "Downloading models"


@pytest.mark.asyncio
async def test_provider_tracks_update_attention_independently_of_health():
    provider = JsonRpcProvider(StdioProviderConfig(id="comfyui", command="noop"))

    await provider._process_message({
        "jsonrpc": "2.0",
        "method": "provider.state",
        "params": {"state": "ready", "attention": "update_available"},
    })

    assert provider.provider_state == "ready"
    assert provider.provider_attention == "update_available"

    await provider._process_message({
        "jsonrpc": "2.0",
        "method": "provider.state",
        "params": {"state": "ready"},
    })

    assert provider.provider_attention is None


def test_strip_undeclared_parameters_keeps_cloud_schema_fields_only():
    schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "steps": {"type": "integer", "default": 4},
            "seed": {"type": "integer"},
            "input_images": {
                "type": "array",
                "items": {"type": "string"},
                "x-control": "image_picker",
            },
        },
        "required": ["prompt"],
    }

    result = _strip_undeclared_parameters(
        {
            "prompt": "dog",
            "width": 1024,
            "height": 1024,
            "steps": 4,
            "seed": 42,
            "input_images": ["asset-id"],
            "prompt_metadata": {"original_prompt": "dog"},
            "auto_marker_ids": [1, 2],
            "input_media_ids": [123],
            "_original_input_paths": ["/tmp/source.png"],
        },
        schema,
    )

    assert result == {
        "prompt": "dog",
        "width": 1024,
        "height": 1024,
        "steps": 4,
        "seed": 42,
        "input_images": ["asset-id"],
    }


def test_strip_undeclared_parameters_is_noop_without_schema_properties():
    params = {"prompt": "dog", "prompt_metadata": {"original_prompt": "dog"}}

    assert _strip_undeclared_parameters(params, None) == params
    assert _strip_undeclared_parameters(params, {"type": "object"}) == params


@pytest.mark.asyncio
async def test_search_options_uses_stp_catalog_method(monkeypatch):
    provider = JsonRpcProvider(StdioProviderConfig(id="generic-speech", command="noop"))
    provider._status = ProviderStatus.CONNECTED
    provider._capabilities = {"parameter_options": True}
    captured = {}

    async def fake_send_request(method, params=None, timeout=30.0):
        captured["method"] = method
        captured["params"] = params
        return {"options": [{"value": "voice-1", "label": "Voice One"}]}

    monkeypatch.setattr(provider, "_send_request", fake_send_request)

    options = await provider.search_options("speech-v1", "voice", "warm", 500)

    assert options == [{"value": "voice-1", "label": "Voice One"}]
    assert captured == {
        "method": "tools.search_options",
        "params": {
            "tool_id": "speech-v1",
            "parameter": "voice",
            "query": "warm",
            "limit": 100,
        },
    }


@pytest.mark.asyncio
async def test_search_options_route_validates_schema_and_forwards_query():
    from routes.tools import SearchToolOptionsRequest, search_tool_options

    provider = MagicMock()
    provider.search_options = AsyncMock(return_value=[{"value": "voice-1", "label": "Voice One"}])
    tool = ToolDescriptor(
        id="speech-v1",
        name="Generic Speech v1",
        parameter_schema={
            "type": "object",
            "properties": {
                "voice": {
                    "type": "string",
                    "x-control": "voice_picker",
                    "x-search-options": True,
                },
            },
        },
        output_schema={},
    )
    registry = MagicMock()
    registry.get_tool.return_value = (provider, tool)

    with patch("providers.ProviderRegistry.get_instance", return_value=registry):
        result = await search_tool_options(SearchToolOptionsRequest(
            full_tool_id="generic-speech:speech-v1",
            parameter="voice",
            query="warm",
            limit=500,
        ))

    assert result == {"options": [{"value": "voice-1", "label": "Voice One"}]}
    provider.search_options.assert_awaited_once_with("speech-v1", "voice", "warm", 100)


@pytest.mark.asyncio
async def test_search_options_requires_advertised_stp_capability():
    provider = JsonRpcProvider(StdioProviderConfig(id="legacy-speech", command="noop"))
    provider._status = ProviderStatus.CONNECTED

    with pytest.raises(RuntimeError, match="parameter_options"):
        await provider.search_options("speech-v1", "voice", "warm")


@pytest.mark.asyncio
async def test_execute_sends_only_declared_parameters(monkeypatch):
    schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "steps": {"type": "integer", "default": 4},
        },
        "required": ["prompt"],
    }
    provider = JsonRpcProvider(StdioProviderConfig(id="stimma-cloud", command="noop"))
    provider._status = ProviderStatus.CONNECTED
    provider._tools = [
        ToolDescriptor(
            id="flux2-klein-9b",
            name="Flux2 Klein 9B",
            parameter_schema=schema,
            output_schema={},
        )
    ]

    captured = {}

    async def fake_send_request(method, params=None, timeout=30.0):
        captured["method"] = method
        captured["params"] = params
        await provider._pending_executions[params["request_id"]].put((
            "result",
            {
                "success": False,
                "error": {"message": "__stop__"},
            },
        ))
        return {"accepted": True}

    monkeypatch.setattr(provider, "_send_request", fake_send_request)

    results = [
        item
        async for item in provider.execute(
            "flux2-klein-9b",
            {
                "prompt": "dog",
                "width": 1024,
                "height": 1024,
                "steps": 4,
                "prompt_metadata": {"original_prompt": "dog"},
                "input_media_ids": [123],
            },
            request_id="job-232313",
        )
    ]

    assert results[-1].error == "__stop__"
    assert captured["method"] == "tools.execute"
    # The subject here is the `parameters` namespace: Stimma-internal keys
    # (prompt_metadata, input_media_ids) must not reach the provider. Assert
    # that exactly, plus the fields identifying the job — but don't pin the
    # envelope to an exhaustive key set, or every optional top-level field
    # (preview_frames, and whatever follows) breaks a test that isn't about it.
    assert captured["params"]["request_id"] == "job-232313"
    assert captured["params"]["tool_id"] == "flux2-klein-9b"
    assert captured["params"]["parameters"] == {
        "prompt": "dog",
        "width": 1024,
        "height": 1024,
        "steps": 4,
    }


@pytest.mark.asyncio
async def test_execute_preserves_primary_output_asset_extension(monkeypatch):
    provider = JsonRpcProvider(StdioProviderConfig(id="stimma-cloud", command="noop"))
    provider._status = ProviderStatus.CONNECTED
    provider._tools = [
        ToolDescriptor(
            id="scribe",
            name="Scribe",
            parameter_schema={"type": "object", "properties": {}},
            output_schema={},
        )
    ]

    async def fake_send_request(_method, params=None, _timeout=30.0):
        await provider._pending_executions[params["request_id"]].put((
            "result",
            {
                "success": True,
                "output": {"assets": [{"asset_id": "transcript123.json", "type": "document", "role": "primary"}]},
                "metadata": {"model": "scribe_v2"},
            },
        ))
        return {"accepted": True}

    async def fake_download(asset_id):
        assert asset_id == "transcript123.json"
        return b'{"text":"hello"}'

    monkeypatch.setattr(provider, "_send_request", fake_send_request)
    monkeypatch.setattr(provider, "download_asset", fake_download)

    results = [item async for item in provider.execute("scribe", {}, request_id="job-stt")]
    assert results[-1].success
    assert results[-1].metadata["_output_asset_id"] == "transcript123.json"
    assert results[-1].output_data == b'{"text":"hello"}'


@pytest.mark.asyncio
async def test_companion_upload_failure_keeps_primary_and_mapping(tmp_path):
    from unittest.mock import AsyncMock
    video, state = tmp_path / "source.mp4", tmp_path / "state.bin"
    video.write_bytes(b"render")
    state.write_bytes(b"opaque")
    provider = JsonRpcProvider(StdioProviderConfig(id="fixture", command="noop"))
    provider._capabilities = {"media_sidecars": True}
    provider.upload_asset = AsyncMock(side_effect=["wire.mp4", OSError("optional transfer failed")])
    schema = {"type": "object", "properties": {"pins": {"type": "array", "items": {"type": "object", "properties": {
        "media": {"type": "string", "x-media": "video", "x-accept-sidecars": [{"format": "unknown", "format_version": 2}]}}}}}}
    mapping = {"custom": "retained without interpretation"}
    envelope = {}
    result = await provider._upload_input_assets({"pins": [{"media": str(video)}]}, schema,
        {str(video): [{"file": str(state), "format": "unknown", "format_version": 2, "media_mapping": mapping}]}, envelope)
    assert result == {"pins": [{"media": "wire.mp4"}]}
    assert envelope["wire.mp4"][0]["status"] == "unavailable"
    assert envelope["wire.mp4"][0]["media_mapping"] == mapping


@pytest.mark.asyncio
async def test_execute_download_retry_does_not_resubmit_generation(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    provider = JsonRpcProvider(StdioProviderConfig(id="fixture", command="noop"))
    provider._status = ProviderStatus.CONNECTED
    async def send(method, params):
        await provider._pending_executions[params["request_id"]].put(("result", {"success": True, "output": {"assets": [
            {"asset_id": "one.mp4", "type": "video"}, {"asset_id": "two.mp4", "type": "video"}]}}))
        return {"accepted": True}
    provider._send_request = AsyncMock(side_effect=send)
    provider.download_asset = AsyncMock(side_effect=[b"one", OSError("disconnected")])
    kwargs = dict(tool_id="fixture", parameters={}, request_id="same-job", output_path=str(tmp_path / "out.mp4"))
    with pytest.raises(OSError):
        _ = [item async for item in provider.execute(**kwargs)]
    provider.download_asset = AsyncMock(return_value=b"two")
    [result] = [item async for item in provider.execute(**kwargs)]
    provider._send_request.assert_awaited_once()
    provider.download_asset.assert_awaited_once_with("two.mp4")
    assert [o.data for o in result.outputs] == [b"one", b"two"]


@pytest.mark.asyncio
async def test_reply_to_another_hosts_request_does_not_resolve_ours():
    # A provider shared with other hosts can echo their replies to us; they
    # number requests from 1, so our ids must never collide with theirs.
    provider = JsonRpcProvider(StdioProviderConfig(id="comfyui", command="noop"))
    sent = []
    transport = MagicMock(is_connected=True)
    transport.send = AsyncMock(side_effect=sent.append)
    provider._transport = transport

    reply = asyncio.create_task(provider._send_request("tools.list", timeout=5))
    while not sent:
        await asyncio.sleep(0)
    for stray_id in (1, 2, "1"):
        await provider._process_message({"jsonrpc": "2.0", "id": stray_id, "result": {"tools": ["theirs"]}})
    assert not reply.done()

    await provider._process_message({"jsonrpc": "2.0", "id": sent[0]["id"], "result": {"tools": ["ours"]}})
    assert await reply == {"tools": ["ours"]}

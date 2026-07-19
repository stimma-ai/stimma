"""Regression tests for STP JSON-RPC outbound parameter shaping."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.base import ProviderStatus, ToolDescriptor
from providers.jsonrpc import JsonRpcProvider, StdioProviderConfig, _strip_undeclared_parameters


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
    provider = JsonRpcProvider(StdioProviderConfig(id="stimma-cloud", command="noop"))
    provider._status = ProviderStatus.CONNECTED
    captured = {}

    async def fake_send_request(method, params=None, timeout=30.0):
        captured["method"] = method
        captured["params"] = params
        return {"options": [{"value": "voice-1", "label": "Voice One"}]}

    monkeypatch.setattr(provider, "_send_request", fake_send_request)

    options = await provider.search_options("eleven-v3", "voice", "warm", 500)

    assert options == [{"value": "voice-1", "label": "Voice One"}]
    assert captured == {
        "method": "tools.search_options",
        "params": {
            "tool_id": "eleven-v3",
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
        id="eleven-v3",
        name="Eleven v3",
        parameter_schema={
            "type": "object",
            "properties": {"voice": {"type": "string", "x-search-options": True}},
        },
        output_schema={},
    )
    registry = MagicMock()
    registry.get_tool.return_value = (provider, tool)

    with patch("providers.ProviderRegistry.get_instance", return_value=registry):
        result = await search_tool_options(SearchToolOptionsRequest(
            full_tool_id="stimma-cloud:eleven-v3",
            parameter="voice",
            query="warm",
            limit=500,
        ))

    assert result == {"options": [{"value": "voice-1", "label": "Voice One"}]}
    provider.search_options.assert_awaited_once_with("eleven-v3", "voice", "warm", 100)


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
    assert captured["params"] == {
        "request_id": "job-232313",
        "tool_id": "flux2-klein-9b",
        "parameters": {
            "prompt": "dog",
            "width": 1024,
            "height": 1024,
            "steps": 4,
        },
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

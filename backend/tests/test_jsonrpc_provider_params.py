"""Regression tests for STP JSON-RPC outbound parameter shaping."""

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

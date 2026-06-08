"""Tests for call_tool argument-shape recovery.

Some models wrap every argument under ``parameters`` so the dispatcher receives
``{"parameters": {"tool_id": ..., "prompt": ..., ...}}`` and Python raises a
TypeError for the missing positional ``tool_id``. The wrapper must lift
tool_id back out before invoking the real generator. STP tools use a single
``parameters`` namespace, so there is no separate ``inputs`` bucket to recover.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agent.v2.tools.call_tool import call_tool


@pytest.mark.asyncio
async def test_call_tool_lifts_tool_id_nested_under_parameters():
    """A model that puts tool_id inside ``parameters`` should still succeed —
    we extract it back to the top level before dispatch so the call doesn't
    fail with "missing required argument: 'tool_id'"."""
    fake_result = {
        "media_id": 999,
        "path": "/tmp/out.png",
        "width": 1024,
        "height": 1024,
    }
    with patch(
        "agent.v2.tools.call_tool.execute_call_tool",
        new=AsyncMock(return_value=fake_result),
    ) as mock_exec:
        result = await call_tool(
            parameters={
                "tool_id": "comfyui:flux-schnell",
                "prompt": "a golden dragon",
                "input_images": ["7658"],
                "guidance": 18,
            },
        )

    assert "Error" not in result
    mock_exec.assert_awaited_once()
    kwargs = mock_exec.await_args.kwargs
    # tool_id lifted to top level, no longer present inside parameters
    assert kwargs["tool_id"] == "comfyui:flux-schnell"
    assert "tool_id" not in kwargs["parameters"]
    # Every other field stays in the single parameters namespace
    assert kwargs["parameters"]["prompt"] == "a golden dragon"
    assert kwargs["parameters"]["input_images"] == ["7658"]
    assert kwargs["parameters"]["guidance"] == 18


@pytest.mark.asyncio
async def test_call_tool_missing_tool_id_returns_friendly_error():
    """Without tool_id anywhere, return a readable error instead of a
    TypeError from the Python dispatcher."""
    result = await call_tool(parameters={"prompt": "hi"})
    assert result.startswith("Error:")
    assert "tool_id" in result


@pytest.mark.asyncio
async def test_call_tool_normal_top_level_args_unchanged():
    """The recovery must be invisible when the model gets the shape right —
    tool_id at the top level should reach execute_call_tool untouched."""
    fake_result = {"media_id": 1, "path": "/tmp/x.png"}
    with patch(
        "agent.v2.tools.call_tool.execute_call_tool",
        new=AsyncMock(return_value=fake_result),
    ) as mock_exec:
        await call_tool(
            tool_id="comfyui:flux-schnell",
            parameters={"prompt": "ok"},
        )

    kwargs = mock_exec.await_args.kwargs
    assert kwargs["tool_id"] == "comfyui:flux-schnell"
    assert kwargs["parameters"] == {"prompt": "ok"}


@pytest.mark.asyncio
async def test_call_tool_flattened_top_level_args_recovered():
    """Some models flatten parameters to top-level kwargs instead of nesting
    under ``parameters``. Known fields are gathered back into the parameters
    object so the call still succeeds."""
    fake_result = {"media_id": 2, "path": "/tmp/x.png"}
    with patch(
        "agent.v2.tools.call_tool.execute_call_tool",
        new=AsyncMock(return_value=fake_result),
    ) as mock_exec:
        result = await call_tool(
            tool_id="comfyui:flux-schnell",
            prompt="a flattened prompt",
            width=1024,
            height=1024,
        )

    assert "Error" not in result
    kwargs = mock_exec.await_args.kwargs
    assert kwargs["parameters"] == {
        "prompt": "a flattened prompt",
        "width": 1024,
        "height": 1024,
    }


@pytest.mark.asyncio
async def test_call_tool_decodes_json_string_parameters():
    """vLLM tool-call templates sometimes deliver dict-valued args as JSON
    strings. Decode and proceed instead of crashing on ``str.pop`` deep in
    controlnet extraction."""
    fake_result = {"media_id": 5, "path": "/tmp/x.png"}
    with patch(
        "agent.v2.tools.call_tool.execute_call_tool",
        new=AsyncMock(return_value=fake_result),
    ) as mock_exec:
        result = await call_tool(
            tool_id="comfyui:flux-klein-9b",
            parameters='{"prompt": "hi", "guidance": 1, "steps": 8, "sampler": "euler"}',
        )

    assert "Error" not in result
    kwargs = mock_exec.await_args.kwargs
    assert kwargs["parameters"] == {
        "prompt": "hi", "guidance": 1, "steps": 8, "sampler": "euler",
    }


@pytest.mark.asyncio
async def test_call_tool_truncated_json_parameters_returns_friendly_error():
    """When the JSON string is truncated (vLLM mid-stream cutoff), we can't
    recover — but we shouldn't crash with str.pop either. The model should see
    a readable error so it can retry with a proper dict."""
    truncated = '{"guidance": 1, "loras": [{"path": "x.safetensors", "seed": 1234, "ste'
    result = await call_tool(
        tool_id="comfyui:flux-klein-9b",
        parameters=truncated,
    )
    assert result.startswith("Error:")
    assert "parameters" in result


@pytest.mark.asyncio
async def test_call_tool_non_dict_parameters_returns_friendly_error():
    """``parameters=42`` is nonsense; tell the model the expected shape rather
    than crashing on the first .pop()."""
    result = await call_tool(
        tool_id="comfyui:flux-klein-9b",
        parameters=42,
    )
    assert result.startswith("Error:")
    assert "parameters" in result and "int" in result

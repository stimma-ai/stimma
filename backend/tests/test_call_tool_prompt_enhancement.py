"""Agent tool calls get the same prompt enhancement as ToolView's Enhance.

Default ("auto") rewrites only for models with their own prompt format; the
agent can force it on or off, and is told whenever its prompt was rewritten.
"""

import pytest
from unittest.mock import AsyncMock, patch

from agent.v2.tools.call_tool import _coerce_enhance_flag, _enhance_prompt_for_tool, call_tool


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "auto"), (True, True), (False, False), ("false", False), ("true", True), ("maybe", "auto")],
)
def test_coerce_enhance_flag(value, expected):
    assert _coerce_enhance_flag(value) == expected


async def _run(enhance_prompt, prompt_format, rewritten="REWRITTEN"):
    enhance = AsyncMock(side_effect=lambda params, **_: {**params, "prompt": rewritten})
    with patch("routes.generation.native_prompt_format", return_value=prompt_format), \
            patch("routes.generation.enhance_tool_prompt", new=enhance):
        params, note = await _enhance_prompt_for_tool(
            {"prompt": "a tea shop poster", "seed": 1},
            tool_id="comfyui:qwen-image-2.1",
            task_type="text-to-image",
            enhance_prompt=enhance_prompt,
            project_id=None,
        )
    return params, note, enhance


@pytest.mark.asyncio
async def test_auto_enhances_models_with_their_own_format_and_says_so():
    params, note, enhance = await _run("auto", "Qwen-Image-2.1")
    enhance.assert_awaited_once()
    assert params == {"prompt": "REWRITTEN", "seed": 1}
    assert "Qwen-Image-2.1's prompt format" in note
    assert "enhance_prompt=false" in note


@pytest.mark.asyncio
async def test_auto_leaves_plain_prose_models_alone():
    params, note, enhance = await _run("auto", None)
    enhance.assert_not_awaited()
    assert params["prompt"] == "a tea shop poster"
    assert note is None


@pytest.mark.asyncio
async def test_explicit_false_and_internal_default_never_enhance():
    for flag in (False, None):
        params, note, enhance = await _run(flag, "Qwen-Image-2.1")
        enhance.assert_not_awaited()
        assert params["prompt"] == "a tea shop poster" and note is None


@pytest.mark.asyncio
async def test_explicit_true_enhances_any_model():
    params, note, enhance = await _run(True, None)
    enhance.assert_awaited_once()
    assert params["prompt"] == "REWRITTEN"
    assert "rewritten for this model" in note


@pytest.mark.asyncio
async def test_enhancement_failure_sends_the_prompt_as_written():
    with patch("routes.generation.native_prompt_format", return_value="MiniMax H3"), \
            patch("routes.generation.enhance_tool_prompt", new=AsyncMock(side_effect=RuntimeError("no LLM"))):
        params, note = await _enhance_prompt_for_tool(
            {"prompt": "a baker opens the shop"},
            tool_id="x", task_type="text-to-video", enhance_prompt="auto", project_id=None,
        )
    assert params["prompt"] == "a baker opens the shop"
    assert "sent as written" in note


@pytest.mark.asyncio
async def test_call_tool_defaults_to_auto_and_reports_the_sent_prompt():
    fake_result = {
        "media_id": 5, "path": "/tmp/out.png",
        "prompt_note": "Your prompt was rewritten for Qwen-Image-2.1's prompt format before generating.",
        "sent_prompt": "The image is a vertical poster ...",
    }
    with patch("agent.v2.tools.call_tool.execute_call_tool", new=AsyncMock(return_value=fake_result)) as mock_exec:
        result = await call_tool(tool_id="comfyui:qwen-image-2.1", parameters={"prompt": "poster"})
    assert mock_exec.await_args.kwargs["enhance_prompt"] == "auto"
    assert "rewritten for Qwen-Image-2.1" in result
    assert "Prompt sent to the model:\nThe image is a vertical poster ..." in result


@pytest.mark.asyncio
async def test_call_tool_accepts_the_flag_nested_in_parameters():
    with patch("agent.v2.tools.call_tool.execute_call_tool",
               new=AsyncMock(return_value={"media_id": 5, "path": "/tmp/out.png"})) as mock_exec:
        await call_tool(tool_id="t", parameters={"prompt": "p", "enhance_prompt": False})
    kwargs = mock_exec.await_args.kwargs
    assert kwargs["enhance_prompt"] is False
    assert "enhance_prompt" not in kwargs["parameters"]


@pytest.mark.parametrize(
    ("model", "vendor", "task", "expected"),
    [
        ("qwen-image-2.1", None, "text-to-image", "Qwen-Image-2.1"),
        ("qwen-image-2.1", None, "image-to-image", "Qwen-Image-2.1"),
        ("minimax_h3_fl2va_pruned_fp8_scaled", None, "image-to-video", "MiniMax H3"),
        ("ideogram:4@0", "ideogram", "text-to-image", "Ideogram 4"),
        ("flux1-dev", None, "text-to-image", None),
        ("qwen-image-2512", None, "text-to-image", None),
        ("sdxl_base_1.0", None, "text-to-image", None),
        ("ltx-2", None, "text-to-video", None),
    ],
)
def test_native_prompt_format(model, vendor, task, expected):
    import routes.generation as gen

    with patch.object(gen, "_prompt_pipeline_context", return_value=(model, vendor, task, {})):
        assert gen.native_prompt_format("some:tool", task) == expected

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
    assert "rewritten for Qwen-Image-2.1 before generating" in note
    assert "exact prompt sent" in note
    assert "enhance_prompt" not in note


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
async def test_h3_manual_prompt_can_still_bypass_enhancement():
    prompt = (
        "integrated_multimodal_description: [Shot 1] A baker opens the shop.\n\n"
        "overall_soundscape: A bell rings.\n\nnon_diegetic_music: N/A"
    )
    with patch("routes.generation.enhance_tool_prompt", new=AsyncMock()) as enhance:
        params, note = await _enhance_prompt_for_tool(
            {"prompt": prompt}, tool_id="comfyui:minimax-h3-t2v",
            task_type="text-to-video", enhance_prompt=False, project_id=None,
        )
    enhance.assert_not_awaited()
    assert params["prompt"] == prompt
    assert note is None


@pytest.mark.asyncio
async def test_sdk_keeps_enhancement_a_per_call_choice(tmp_path):
    from types import SimpleNamespace
    from agent.v2.code_runtime import StimmaSDK

    sdk = StimmaSDK(
        session=SimpleNamespace(bind=None), chat_id=None, workspace_dir=tmp_path,
        project_workspace_dir=tmp_path,
        interrupt_checker=lambda: False,
    )
    with patch("agent.v2.tool_permission_gate.ensure_tool_permission", new=AsyncMock()), \
            patch("agent.v2.code_runtime.execute_call_tool", new=AsyncMock(return_value={
                "path": str(tmp_path / "video.mp4"), "tool_id": "comfyui:minimax-h3-t2v",
            })) as execute:
        for flag in (True, False, None):
            await sdk._dispatch_tool(
                "comfyui:minimax-h3-t2v", _task_type="text-to-video",
                prompt="An authored prompt", enhance_prompt=flag,
            )
    assert [call.kwargs["enhance_prompt"] for call in execute.await_args_list] == [True, False, "auto"]
    assert all("enhance_prompt" not in call.kwargs["parameters"] for call in execute.await_args_list)


@pytest.mark.parametrize(
    ("label", "required"),
    [("MiniMax H3", True), ("Qwen-Image-2.1", False), ("LTX-2.5", False)],
)
def test_schema_separates_format_requirements_from_enhancement(label, required):
    import json
    from types import SimpleNamespace
    from agent.v2.tools.discover import _get_schema

    descriptor = SimpleNamespace(
        name=label, task_types=["text-to-video"],
        parameter_schema={"properties": {"prompt": {"type": "string"}}},
    )
    registry = SimpleNamespace(get_tool=lambda _: (None, descriptor))
    with patch("routes.generation.native_prompt_format", return_value=label):
        schema = json.loads(_get_schema(registry, "test:tool"))
    assert schema["prompt_format_requirements"]["required"] is required
    assert "enhance_prompt=False" in schema["prompt_format"]
    if required:
        assert schema["prompt_format_requirements"]["reference"] in schema["prompt_format"]
    else:
        assert "recommended" in schema["prompt_format"]


@pytest.mark.asyncio
async def test_explicit_true_enhances_any_model():
    params, note, enhance = await _run(True, None)
    enhance.assert_awaited_once()
    assert params["prompt"] == "REWRITTEN"
    assert "rewritten for this model" in note


@pytest.mark.asyncio
async def test_enhancement_failure_blocks_generation():
    with patch("routes.generation.native_prompt_format", return_value="MiniMax H3"), \
            patch("routes.generation.enhance_tool_prompt", new=AsyncMock(side_effect=RuntimeError("no LLM"))):
        with pytest.raises(ValueError, match="No generation was started"):
            await _enhance_prompt_for_tool(
                {"prompt": "a baker opens the shop"},
                tool_id="x", task_type="text-to-video", enhance_prompt="auto", project_id=None,
            )


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
        ("flux3-klein", None, "text-to-image", "FLUX.3 Klein"),
        ("flux3-klein-base", None, "image-to-image", "FLUX.3 Klein"),
        ("flux2-klein-9b", None, "text-to-image", None),
        ("minimax_h3_fl2va_pruned_fp8_scaled", None, "image-to-video", "MiniMax H3"),
        ("ideogram:4@0", "ideogram", "text-to-image", "Ideogram 4"),
        ("flux1-dev", None, "text-to-image", None),
        ("qwen-image-2512", None, "text-to-image", None),
        ("sdxl_base_1.0", None, "text-to-image", None),
        ("ltx-2", None, "text-to-video", None),
        ("ltx-2.3", None, "image-to-video", None),
        ("ltx-2.5", None, "text-to-video", "LTX-2.5"),
        ("ltx-2.5", None, "image-to-video", "LTX-2.5"),
    ],
)
def test_native_prompt_format(model, vendor, task, expected):
    import routes.generation as gen

    with patch.object(gen, "_prompt_pipeline_context", return_value=(model, vendor, task, {})):
        assert gen.native_prompt_format("some:tool", task) == expected

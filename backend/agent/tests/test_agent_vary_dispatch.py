"""vary / keep_choices / draw_seed on the generated tool functions (run_code), the
receipt line that reports what each image drew, and params_from + vary starting from
a varied image's prompt as written."""

import json

import pytest

from agent.tests.test_run_code_v2 import _patch_mock_registry
from agent.v2.tools.run_code import run_code
from tests.helpers.media import create_media_item, generate_test_image


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def harness(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    out = workspace / "out.png"
    generate_test_image(out, width=16, height=16)
    calls = []

    async def fake_execute_call_tool(*, tool_id, parameters=None, **kwargs):
        calls.append({"parameters": dict(parameters or {}), "request": kwargs.get("prompt_request")})
        return {
            "media_id": 900 + len(calls), "path": str(out), "width": 16, "height": 16, "seed": 11,
            "tool_id": tool_id, "tool_name": "Mock Tool", "task_type": "text-to-image",
            "parameters": {}, "input_media_ids": [], "duration_ms": 1,
            "choices": {"outfit": "a nun's habit", "age": "early forties"}, "draw_seed": 81723,
        }

    monkeypatch.setattr("agent.v2.code_runtime.execute_call_tool", fake_execute_call_tool)
    _patch_mock_registry(monkeypatch)
    monkeypatch.setattr("database_registry.get_database_registry", lambda: type("R", (), {
        "get_database": lambda self, p: type("D", (), {"async_session_maker": lambda self: _SessionCtx(session)})()})())

    async def _noop_validate(*args, **kwargs):
        return []
    monkeypatch.setattr("agent.v2.code_lint.validate_hardcoded_refs", _noop_validate)

    async def run(code):
        test_chat.agent_tool_config = json.dumps({"allowed_tools": ["mock:gen"]})
        await session.commit()
        return await run_code(code=code, session=session, chat_id=test_chat.id, workspace_dir=workspace)

    return calls, run


async def test_vary_arguments_reach_the_prompt_not_the_tool(harness):
    calls, run = harness
    result = await run(
        "from stimma.tools.text_to_image import gen\n"
        "r = await gen(prompt='a {{outfit}} in a garden', vary=True, keep_choices={'age': 'early forties'}, draw_seed=3)\n"
        "print(r.choices, r.draw_seed)\n"
    )
    params, request = calls[0]["parameters"], calls[0]["request"]
    assert "vary" not in params and "keep_choices" not in params and "draw_seed" not in params
    assert request.vary is True and request.keep_choices == {"age": "early forties"} and request.draw_seed == 3
    assert request.enhance == "auto"
    assert "{'outfit': \"a nun's habit\", 'age': 'early forties'} 81723" in result
    assert "choices: outfit = a nun's habit · age = early forties  (draw_seed 81723)" in result


async def test_plain_call_carries_no_vary(harness):
    calls, run = harness
    await run("from stimma.tools.text_to_image import gen\nawait gen(prompt='a cat', enhance_prompt=False)\n")
    request = calls[0]["request"]
    assert request.vary is False and request.keep_choices is None and request.draw_seed is None
    assert request.enhance is False


async def _varied_image(session, tmp_path, *, varied=True):
    path = tmp_path / ("varied.png" if varied else "plain.png")
    file_hash = generate_test_image(path, width=8, height=8)
    meta = {
        "version": 3, "tool_id": "mock:gen", "task_type": "text-to-image", "prompt": "a nun in a cloister garden",
        "parameters": {"seed": 5, "steps": 9},
        "prompt_metadata": {"original_prompt": "a {nun|nurse} in {{setting}}", "auto_improve_enabled": True},
    }
    if varied:
        meta["prompt_program"] = {"key": "k", "enhance": "fill", "draw_seed": 44,
                                  "draws": [{"id": "role", "value": "nun"}, {"id": "setting", "value": "a cloister garden"}]}
    item = await create_media_item(session, file_path=path, file_hash=file_hash, tool_id="mock:gen",
                                   generation_metadata=json.dumps(meta))
    return item.id


async def test_params_from_and_vary_start_from_the_written_prompt(harness, session, tmp_path):
    calls, run = harness
    media_id = await _varied_image(session, tmp_path)
    await run(f"from stimma.tools.text_to_image import gen\nawait gen(params_from={media_id}, vary=True, "
              "keep_choices={'setting': 'a cloister garden'})\n")
    assert calls[0]["parameters"]["prompt"] == "a {nun|nurse} in {{setting}}"
    assert calls[0]["parameters"]["steps"] == 9
    assert calls[0]["request"].enhance == "fill"  # the image's own detail level
    # Without vary, reproduction stays exact.
    await run(f"from stimma.tools.text_to_image import gen\nawait gen(params_from={media_id})\n")
    assert calls[1]["parameters"]["prompt"] == "a nun in a cloister garden"
    # An explicit prompt or enhance_prompt wins.
    await run(f"from stimma.tools.text_to_image import gen\nawait gen(params_from={media_id}, vary=True, "
              "prompt='a {monk|nun}', enhance_prompt=True)\n")
    assert calls[2]["parameters"]["prompt"] == "a {monk|nun}" and calls[2]["request"].enhance is True


async def test_params_from_and_vary_on_an_unvaried_image_keeps_its_prompt(harness, session, tmp_path):
    calls, run = harness
    media_id = await _varied_image(session, tmp_path, varied=False)
    await run(f"from stimma.tools.text_to_image import gen\nawait gen(params_from={media_id}, vary=True)\n")
    assert calls[0]["parameters"]["prompt"] == "a nun in a cloister garden"
    assert calls[0]["request"].enhance == "auto"


async def test_media_info_lists_choices(session, tmp_path):
    from agent.v2.tools.media_info import build_media_info
    info = await build_media_info(session, await _varied_image(session, tmp_path))
    assert info["choices"] == {"role": "nun", "setting": "a cloister garden"}
    assert info["draw_seed"] == 44
    assert info["written_prompt"] == "a {nun|nurse} in {{setting}}"

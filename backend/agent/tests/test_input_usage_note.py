"""A pinned input whose stored state was skipped for a reason nobody chose is reported
in plain words: on the generation's metadata (the info panel) and in what the agent
gets back from call_tool and run_code. The generation itself still succeeds."""

import json

import pytest

import agent.v2.code_runtime as code_runtime
import agent.v2.tools.call_tool as ct
from agent.tests.test_run_code_concurrency import (
    _FakeDbRegistry, _FakeQueue, _FakeRegistry, _MockDescriptor,
)
from agent.v2.tools.run_code import run_code
from database import Chat
from media_sidecars import input_usage_note
from tests.helpers.media import create_media_item, generate_test_image

UPLOAD_FAILED = [{"source": "rendered_video", "reason": "upload_failed", "from": 4.4, "length": 1.625}]
NOTE = "Stored generation state wasn't used for keyframe 1 (upload failed), so it was re-encoded from the video."


def test_note_names_the_keyframe_and_the_reason():
    assert input_usage_note(UPLOAD_FAILED) == NOTE


@pytest.mark.parametrize("reason", ["no_stored_state", "no_compatible_sidecar", "unsupported_interval",
                                    "coverage_unavailable", "encoding_mismatch"])
def test_intended_pixel_paths_need_no_note(reason):
    assert input_usage_note([{"source": "rendered_video", "reason": reason}]) is None


def test_state_that_was_used_needs_no_note():
    assert input_usage_note([{"source": "native_latent", "format": "h3"}]) is None
    assert input_usage_note(None) is None and input_usage_note([]) is None


def test_reasons_group_and_unknown_reasons_still_surface():
    usage = [
        {"source": "native_latent"},
        {"source": "rendered_video", "reason": "upload_failed"},
        {"source": "rendered_video", "reason": "no_stored_state"},
        {"source": "rendered_video", "reason": "upload_failed"},
        {"source": "rendered_video", "reason": "tensor_shape_changed"},
    ]
    assert input_usage_note(usage) == (
        "Stored generation state wasn't used for keyframes 2 and 4 (upload failed), so it was "
        "re-encoded from the video. Stored generation state wasn't used for keyframe 5 "
        "(tensor shape changed), so it was re-encoded from the video.")


async def _harness(session_factory, tmp_path, monkeypatch, generation_metadata):
    tool_id = "mock:gen"
    workspace, output_dir = tmp_path / "workspace", tmp_path / "output"
    workspace.mkdir()
    output_dir.mkdir()
    async with session_factory() as setup:
        chat = Chat(name="Note chat", agent_tool_config=json.dumps({"allowed_tools": [tool_id]}))
        setup.add(chat)
        await setup.commit()
        await setup.refresh(chat)
        out = output_dir / "out.png"
        media = await create_media_item(setup, file_path=out, file_hash=generate_test_image(out, width=8, height=8),
                                        width=8, height=8, generation_metadata=json.dumps(generation_metadata))
        chat_id, media_id = chat.id, media.id
    monkeypatch.setattr("database_registry.get_database_registry", lambda: _FakeDbRegistry(session_factory))
    monkeypatch.setattr(ct, "get_current_profile", lambda: "test-profile")
    monkeypatch.setattr(code_runtime, "get_current_profile", lambda: "test-profile")
    registry = _FakeRegistry(tool_id, _MockDescriptor())
    monkeypatch.setattr("providers.registry.ProviderRegistry.get_instance", staticmethod(lambda: registry))
    monkeypatch.setattr(ct, "get_generation_queue", lambda: _FakeQueue())
    monkeypatch.setattr(ct, "_get_default_folder", lambda *_a, **_k: str(output_dir))

    async def finished(job_ids, _session, status_checker=None, **_kwargs):
        return [media_id], [], 0, {job_ids[0]: media_id}

    monkeypatch.setattr(ct, "wait_for_jobs", finished)
    return tool_id, chat_id, workspace


@pytest.mark.asyncio
async def test_run_code_and_call_tool_report_the_note(session, session_factory, tmp_path, monkeypatch):
    meta = {"tool_id": "mock:gen", "input_usage": UPLOAD_FAILED, "input_usage_note": NOTE}
    tool_id, chat_id, workspace = await _harness(session_factory, tmp_path, monkeypatch, meta)

    printed = await run_code(code="from stimma.tools.text_to_image import gen\nr = await gen(prompt='a cat')\nprint(r.media_id)\n",
                             session=session, chat_id=chat_id, workspace_dir=workspace)
    assert not printed.startswith("Error"), printed
    assert f"[{tool_id}] {NOTE}" in printed

    returned = await ct.call_tool(tool_id=tool_id, parameters={"prompt": "a cat"}, enhance_prompt=False,
                                  session=session, chat_id=chat_id, workspace_dir=workspace)
    assert returned.startswith("<result media_id="), returned
    assert NOTE in returned


@pytest.mark.asyncio
async def test_no_note_when_state_was_used(session, session_factory, tmp_path, monkeypatch):
    meta = {"tool_id": "mock:gen", "input_usage": [{"source": "native_latent"}]}
    tool_id, chat_id, workspace = await _harness(session_factory, tmp_path, monkeypatch, meta)
    returned = await ct.call_tool(tool_id=tool_id, parameters={"prompt": "a cat"}, enhance_prompt=False,
                                  session=session, chat_id=chat_id, workspace_dir=workspace)
    assert "Stored generation state" not in returned


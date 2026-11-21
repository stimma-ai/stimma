"""The background strip's peek: what a running task has made so far, with inputs.

Looking is read-only: the endpoint reports the task's calls (newest first) and
never saves their outputs anywhere.
"""
import asyncio

import pytest

import agent.v2.background as bg
import agent.v2.code_runtime as code_runtime
from agent.v2.background import BackgroundRun, RunControl
from agent.v2.code_runtime import StimmaSDK
from agent.v2.tools.call_tool import describe_inputs


def test_describe_inputs_names_each_inputs_part():
    params = {
        "input_media_ids": [11, None, 12],
        "keyframes": [{"media": "x", "at": 0}, {"media": "y"}],
    }
    assert describe_inputs(params, {"keyframes": [21, 22]}, "image-to-video") == [
        {"media_id": 11, "role": "start"},
        {"media_id": 12, "role": "input"},
        {"media_id": 21, "role": "pinned"},
        {"media_id": 22, "role": "input"},
    ]
    # Only a video's first image is its start frame; repeats are listed once.
    assert describe_inputs({"input_media_ids": [5, 5]}, {}, "image-to-image") == [
        {"media_id": 5, "role": "input"},
    ]


@pytest.fixture
def generation(monkeypatch):
    held: dict[str, asyncio.Event] = {}
    failing: set[str] = set()
    next_job = iter(range(1, 1000))

    async def fake_execute_call_tool(*, tool_id, parameters, cancel_checker, on_job_submitted, on_inputs, **kwargs):
        on_inputs([{"media_id": m, "role": "start"} for m in parameters.get("input_media_ids", [])])
        job_id = next(next_job)
        on_job_submitted(job_id)
        prompt = parameters.get("prompt")
        if prompt in held:
            await held[prompt].wait()
        if prompt in failing:
            raise RuntimeError("out of memory")
        return {"path": f"out-{job_id}.mp4", "media_id": 500 + job_id, "tool_id": tool_id}

    async def allow(**kwargs):
        return None

    monkeypatch.setattr(code_runtime, "execute_call_tool", fake_execute_call_tool)
    monkeypatch.setattr("agent.v2.tool_permission_gate.ensure_tool_permission", allow)
    monkeypatch.setattr("mcp_server.jobs.check_execution", lambda: None)
    return held, failing


async def _settle():
    for _ in range(50):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_items_endpoint_lists_newest_first_with_inputs(client, db_session, tmp_path, generation):
    from database import Chat
    held, failing = generation
    async with db_session() as s:
        chat = Chat(name="Long take")
        s.add(chat)
        await s.commit()
        chat_id = chat.id

    control = RunControl()
    sdk = StimmaSDK(session=db_session(), chat_id=chat_id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=control)
    failing.add("second")
    held["third"] = asyncio.Event()

    async def serial():
        # Each call follows the last, as a continuation does.
        first = await sdk._dispatch_tool("mock:i2v", prompt="first", input_media_ids=[7])
        try:
            await sdk._dispatch_tool("mock:i2v", prompt="second", input_media_ids=[first.media_id])
        except RuntimeError:
            pass
        await sdk._dispatch_tool("mock:i2v", prompt="third", input_media_ids=[first.media_id])

    task = asyncio.create_task(serial())
    await _settle()
    key = bg._key(chat_id)
    run = BackgroundRun(id="bg-1", profile=key[0], chat_id=chat_id, label="", control=control,
                        task=task, reason="test")
    bg._runs.setdefault(key, {})[run.id] = run
    try:
        response = await client.get(f"/api/chats/{chat_id}/background/bg-1/items")
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 3
        items = data["items"]
        assert [i["prompt"] for i in items] == ["third", "second", "first"]
        assert [i["state"] for i in items] == ["preparing", "failed", "done"]
        assert items[0]["inputs"] == [{"media_id": 501, "role": "start"}]
        assert "out of memory" in items[1]["error"]
        assert items[2]["media_id"] == 501 and items[2]["file_format"] == "mp4"
        assert items[2]["inputs"] == [{"media_id": 7, "role": "start"}]

        # The agent's own view stays lean: no inputs there.
        assert "inputs" not in (await control.snapshot_items())[0]

        missing = await client.get(f"/api/chats/{chat_id}/background/bg-9/items")
        assert missing.status_code == 404
    finally:
        held["third"].set()
        await asyncio.wait_for(task, 3)
        bg._runs.get(key, {}).pop("bg-1", None)

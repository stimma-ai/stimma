"""Background work: run_code that outlives its turn, and stimma.tasks controls."""
import asyncio
from pathlib import Path

import pytest

import agent.v2.background as bg
import agent.v2.code_runtime as code_runtime
from agent.v2.background import GenerationCancelled, RunControl
from agent.v2.code_runtime import StimmaSDK, _code_workspace
from agent.v2.tools.run_code import run_code_detachable


class _FakeQueue:
    def __init__(self):
        self.cancelled = []

    async def cancel_job(self, job_id, **kwargs):
        self.cancelled.append(job_id)
        return True


@pytest.fixture
def fake_generation(monkeypatch):
    """execute_call_tool stand-in: each call is a job that runs until released
    or cancelled through its job id, like a real queued generation."""
    queue = _FakeQueue()
    releases: dict[int, asyncio.Event] = {}
    next_id = iter(range(1, 1000))

    async def fake_execute_call_tool(*, tool_id, parameters, cancel_checker, on_job_submitted, **kwargs):
        if cancel_checker():
            raise GenerationCancelled("Cancelled before it started")
        job_id = next(next_id)
        releases[job_id] = asyncio.Event()
        on_job_submitted(job_id)
        while not releases[job_id].is_set():
            if job_id in queue.cancelled:
                raise GenerationCancelled("Cancelled while it was running")
            await asyncio.sleep(0.01)
        return {"path": f"out-{job_id}.png", "media_id": 100 + job_id, "tool_id": tool_id}

    async def allow(**kwargs):
        return None

    monkeypatch.setattr(code_runtime, "execute_call_tool", fake_execute_call_tool)
    monkeypatch.setattr("agent.v2.tool_permission_gate.ensure_tool_permission", allow)
    monkeypatch.setattr("mcp_server.jobs.check_execution", lambda: None)
    monkeypatch.setattr("generation_queue.get_generation_queue", lambda: queue)
    return queue, releases


async def _until(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancelling_chosen_items_keeps_the_rest_of_the_batch(session, test_chat, tmp_path, fake_generation):
    queue, releases = fake_generation
    control = RunControl()
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=control)
    batch = asyncio.create_task(sdk._gather(
        *[sdk._dispatch_tool("mock:gen", prompt=f"shot {n}") for n in range(1, 5)]
    ))
    await _until(lambda: len([i for i in control.items if i.job_id]) == 4)

    # Item 2 is generating and item 4 is queued as far as the agent is concerned:
    # both can be cancelled. The others finish and are delivered.
    assert await control.cancel(items=[2, 4]) == [2, 4]
    releases[1].set()
    releases[3].set()
    results = await asyncio.wait_for(batch, 3)

    assert [r.media_id for r in results] == [101, 103]
    assert sorted(queue.cancelled) == [2, 4]
    assert [i.state for i in control.items] == ["done", "cancelled", "done", "cancelled"]
    assert len(sdk._tool_cancellations) == 2 and not sdk._tool_failures


@pytest.mark.asyncio
async def test_cancel_everything_left_also_refuses_calls_not_made_yet(session, test_chat, tmp_path, fake_generation):
    queue, releases = fake_generation
    control = RunControl()
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=control)
    first = asyncio.create_task(sdk._dispatch_tool("mock:gen", prompt="first"))
    await _until(lambda: control.items and control.items[0].job_id)
    await control.cancel()
    with pytest.raises(GenerationCancelled):
        await asyncio.wait_for(first, 3)
    with pytest.raises(GenerationCancelled):
        await sdk._dispatch_tool("mock:gen", prompt="second")
    assert len(control.items) == 1
    # A batch that ended up empty shows nothing rather than failing the run.
    sdk.show([], role="final")
    assert not sdk._pending_display_calls


@pytest.mark.asyncio
async def test_steer_moves_running_code_to_the_background(session, test_chat, tmp_path, monkeypatch):
    monkeypatch.setattr(bg, "STEER_DETACH_GRACE_SECONDS", 0.1)
    finished = asyncio.get_running_loop().create_future()

    async def on_finished(run, output):
        finished.set_result((run, output))

    steering = {"pending": False}
    turn = asyncio.create_task(run_code_detachable(
        "import asyncio\nawait asyncio.sleep(0.8)\nprint('all shots done')",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
        label="Generating shots",
        _has_pending_input=lambda: steering["pending"],
        _on_background_finished=on_finished,
    ))
    await asyncio.sleep(0.3)
    assert not turn.done()
    steering["pending"] = True
    message = await asyncio.wait_for(turn, 2)

    # The turn hears the user now; the code is still going.
    assert "in the background as task bg-" in message
    assert not finished.done()
    run, output = await asyncio.wait_for(finished, 3)
    assert "all shots done" in output
    assert run.state == "completed" and run.wake is True
    assert bg.get_foreground(test_chat.id) is None


class _RecordingWs:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data, **kwargs):
        self.events.append((event, data))


@pytest.mark.asyncio
async def test_stop_can_keep_the_code_running(session, test_chat, tmp_path):
    import project_activity
    from agent.v2 import service

    finished = asyncio.get_running_loop().create_future()
    ws = _RecordingWs()

    async def on_finished(run, output):
        finished.set_result((run, output))

    turn = asyncio.create_task(run_code_detachable(
        "import asyncio\nawait asyncio.sleep(0.6)\nprint('kept going')",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
        _on_background_finished=on_finished, _ws_manager=ws,
    ))
    await _until(lambda: bg.get_foreground(test_chat.id) is not None)
    run_id = await bg.request_detach(test_chat.id, wake=False)
    assert run_id and run_id in await asyncio.wait_for(turn, 2)

    # The turn is over, but the chat still shows as working while the code runs.
    assert test_chat.id not in service.get_active_chat_ids()
    assert bg.running_task_ids_by_chat() == {test_chat.id: [run_id]}
    assert test_chat.id in project_activity._active_chat_ids()

    run, output = await asyncio.wait_for(finished, 3)
    assert "kept going" in output
    # After a Stop, the receipt waits for the user instead of starting a turn.
    assert run.wake is False
    assert test_chat.id not in bg.running_task_ids_by_chat()
    assert test_chat.id not in project_activity._active_chat_ids()
    # Every client hears the start and the end, not only views of this chat.
    states = [d for e, d in ws.events if e == "background_task_state"]
    assert states == [
        {"chat_id": test_chat.id, "task_id": run_id, "state": "running"},
        {"chat_id": test_chat.id, "task_id": run_id, "state": "completed"},
    ]


@pytest.mark.asyncio
async def test_hard_stop_still_ends_the_code(session, test_chat, tmp_path):
    turn = asyncio.create_task(run_code_detachable(
        "import asyncio\nawait asyncio.sleep(30)",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    ))
    await _until(lambda: bg.get_foreground(test_chat.id) is not None)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(turn, 3)
    assert bg.get_foreground(test_chat.id) is None
    assert not bg.list_runs(test_chat.id, include_finished=False)


@pytest.mark.asyncio
async def test_runs_in_one_workspace_share_cwd_while_others_wait(tmp_path):
    original = Path.cwd()
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    held = asyncio.Event()
    release = asyncio.Event()

    async def long_run():
        async with _code_workspace(first):
            held.set()
            await release.wait()

    background = asyncio.create_task(long_run())
    await held.wait()
    # Same workspace: in straight away.
    async with _code_workspace(first):
        assert Path.cwd() == first.resolve()
    # Another workspace waits for the cwd to be free.
    seen = []

    async def other_run():
        async with _code_workspace(second):
            seen.append(Path.cwd())

    other = asyncio.create_task(other_run())
    await asyncio.sleep(0.05)
    assert not other.done()
    release.set()
    await background
    await asyncio.wait_for(other, 2)
    assert seen == [second.resolve()]
    assert Path.cwd() == original


@pytest.mark.asyncio
async def test_a_run_waiting_for_the_cwd_stops_when_cancelled_and_says_why_it_waits(tmp_path):
    from agent.v2.code_runtime import CodeRunStopped
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    held, release = asyncio.Event(), asyncio.Event()

    async def long_run():
        async with _code_workspace(first):
            held.set()
            await release.wait()

    background = asyncio.create_task(long_run())
    await held.wait()
    control = RunControl()

    async def other_run():
        async with _code_workspace(second, should_stop=lambda: control.stop_requested,
                                   on_wait=control.set_waiting_for_workspace):
            pass

    other = asyncio.create_task(other_run())
    await asyncio.sleep(0.05)
    assert "another chat" in control.waiting_for
    await control.cancel()
    with pytest.raises(CodeRunStopped):
        await asyncio.wait_for(other, 2)  # ends while the other chat still holds the cwd
    assert control.waiting_for is None
    assert not background.done()
    release.set()
    await background


@pytest.mark.asyncio
async def test_items_say_what_they_make_for_the_task_bar(session, test_chat, tmp_path, fake_generation):
    _, releases = fake_generation
    control = RunControl()
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=control)
    batch = asyncio.create_task(sdk._gather(
        sdk._dispatch_tool("mock:gen", _task_type="text-to-image", prompt="a"),
        sdk._dispatch_tool("mock:gen", _task_type="image-to-video", prompt="b"),
        sdk._dispatch_tool("mock:gen", _task_type="speech-to-text", prompt="c"),
    ))
    await _until(lambda: len([i for i in control.items if i.job_id]) == 3)
    for release in releases.values():
        release.set()
    await asyncio.wait_for(batch, 3)
    assert [i.get("kind") for i in await control.snapshot_items()] == ["image", "video", None]


def test_unlabeled_runs_read_cleanly_to_the_model():
    run = bg.BackgroundRun(id="bg-1", profile="p", chat_id=1, label="", control=RunControl(),
                           task=None, reason="steer", state="completed")
    assert bg.notification_text(run, "ok").splitlines()[1] == "Background task bg-1 finished."
    assert 'task bg-2 ("Upscaling"):' in bg.describe_detached("bg-2", "Upscaling", [], 0)
    assert "task bg-2: no generation calls yet" in bg.describe_detached("bg-2", "", [], 0)


@pytest.mark.asyncio
async def test_cancelling_a_whole_task_stops_its_code(session, test_chat, tmp_path):
    # A loop that keeps generating never ends on its own; cancelling the task
    # must end it, not leave it spinning with every new call canceled.
    finished = asyncio.get_running_loop().create_future()

    async def on_finished(run, output):
        finished.set_result((run, output))

    message = await asyncio.wait_for(run_code_detachable(
        "import asyncio\nwhile True:\n    await asyncio.sleep(0.05)",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path, background=True,
        _on_background_finished=on_finished,
    ), 5)
    assert "in the background as task bg-" in message
    (run,) = bg.list_runs(test_chat.id, include_finished=False)
    await run.control.cancel()
    run, output = await asyncio.wait_for(finished, 3)
    assert output.startswith("Stopped:")
    assert run.state == "completed"


@pytest.mark.asyncio
async def test_consecutive_untitled_batches_share_one_card(session, test_chat, tmp_path, fake_generation):
    _, releases = fake_generation
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=RunControl())
    for batch in range(2):
        task = asyncio.create_task(sdk._gather(
            *[sdk._dispatch_tool("mock:gen", prompt=f"shot {batch}-{n}") for n in range(3)]
        ))
        await _until(lambda: sum(1 for e in releases.values() if not e.is_set()) == 3)
        for event in releases.values():
            event.set()
        await asyncio.wait_for(task, 3)

    (card,) = sdk._cards
    state = card.display_data()
    # A loop of batches has no end in sight, so its card has no count.
    assert state["mode"] == "stream" and "total" not in state
    assert sorted(row["output"]["media_id"] for row in state["rows"]) == [101, 102, 103, 104, 105, 106]


@pytest.mark.asyncio
async def test_global_in_a_worker_means_the_top_level_name(session, test_chat, tmp_path):
    # Agent code is written as a module but runs inside a function; `global`
    # must still reach its top-level variables.
    message = await asyncio.wait_for(run_code_detachable(
        "import asyncio\n"
        "count = 0\n"
        "async def worker():\n"
        "    global count\n"
        "    count += 1\n"
        "async with asyncio.TaskGroup() as group:\n"
        "    for _ in range(3):\n"
        "        group.create_task(worker())\n"
        "print('count', count)",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    ), 5)
    assert "count 3" in message


@pytest.mark.asyncio
async def test_a_failed_task_group_names_what_failed(session, test_chat, tmp_path):
    message = await asyncio.wait_for(run_code_detachable(
        "import asyncio\n"
        "async def worker():\n"
        "    raise ValueError('no such style')\n"
        "async with asyncio.TaskGroup() as group:\n"
        "    group.create_task(worker())",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    ), 5)
    assert "Inside it: ValueError: no such style" in message


@pytest.mark.asyncio
async def test_stopping_a_whole_task_from_the_bar_does_not_wake_the_agent(session, test_chat, tmp_path):
    from routes import chats

    finished = asyncio.get_running_loop().create_future()

    async def on_finished(run, output):
        finished.set_result((run, output))

    await asyncio.wait_for(run_code_detachable(
        "import asyncio\nwhile True:\n    await asyncio.sleep(0.05)",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path, background=True,
        _on_background_finished=on_finished,
    ), 5)
    (run,) = bg.list_runs(test_chat.id, include_finished=False)
    assert run.wake is True
    await chats.cancel_background_task(test_chat.id, run.id, None)
    run, output = await asyncio.wait_for(finished, 3)
    assert run.wake is False and output.startswith("Stopped:")


def test_a_long_task_lists_only_its_latest_finished_items():
    items = [{"item": n, "state": "done"} for n in range(1, 101)] + [{"item": 101, "state": "generating"}]
    kept = bg._recent(items)
    assert [i["item"] for i in kept] == list(range(81, 102))
    assert bg._counts(items, 0)["done"] == 100


@pytest.mark.asyncio
async def test_a_gather_of_workers_has_no_count(session, test_chat, tmp_path, fake_generation):
    _, releases = fake_generation
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=RunControl())
    prompts = [f"shot {n}" for n in range(5)]

    async def worker():
        while prompts:
            await sdk._dispatch_tool("mock:gen", prompt=prompts.pop())

    task = asyncio.create_task(sdk._gather(worker(), worker()))
    await _until(lambda: sdk._cards and sdk._cards[0].live)
    while not task.done():
        for event in releases.values():
            event.set()
        await asyncio.sleep(0.01)
    await task
    (card,) = sdk._cards
    # Its total would be the calls started so far (3, then 4 of 7...), so it shows none.
    assert card.summary() == {"title": "Results", "open": True}
    assert len(card.display_data()["rows"]) == 5


@pytest.mark.asyncio
async def test_a_failed_task_reads_as_failed_with_its_reason(session, test_chat, tmp_path):
    from agent.v2.code_runtime import StimmaTasksAPI

    finished = asyncio.get_running_loop().create_future()

    async def on_finished(run, output):
        finished.set_result(run)

    turn = asyncio.create_task(run_code_detachable(
        "import asyncio\nawait asyncio.sleep(0.3)\nraise ValueError('no_such_tool is gone')",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
        _on_background_finished=on_finished, _ws_manager=_RecordingWs(),
    ))
    await _until(lambda: bg.get_foreground(test_chat.id) is not None)
    run_id = await bg.request_detach(test_chat.id, wake=False)
    await asyncio.wait_for(turn, 2)
    await asyncio.wait_for(finished, 3)

    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    task = await asyncio.wait_for(StimmaTasksAPI(sdk).get(run_id), 1)
    assert task["state"] == "failed"
    assert "no_such_tool" in task["error"] and "quick reference" not in task["error"]


@pytest.mark.asyncio
async def test_capacity_reads_the_tools_backend(monkeypatch, session, test_chat, tmp_path):
    from agent.v2.code_runtime import StimmaTasksAPI

    class _Registry:
        async def list_backends(self):
            return {"comfyui": {"max_concurrent": 2}}

    class _Provider:
        def __init__(self, provider_id):
            self.provider_id = provider_id

    class _Providers:
        tools = {
            "comfyui:flux-klein-9b": _Provider("comfyui"),
            "builtin:comfyui:qwen-image:text-to-image": _Provider("builtin:comfyui"),
        }

        def get_tool(self, tool_id):
            p = self.tools.get(tool_id)
            return (p, object()) if p else None

    monkeypatch.setattr("backend_registry.get_backend_registry", lambda: _Registry())
    monkeypatch.setattr("providers.registry.ProviderRegistry.get_instance", lambda: _Providers())
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    tasks = StimmaTasksAPI(sdk)
    assert await tasks.capacity("comfyui:flux-klein-9b") == 2
    assert await tasks.capacity("builtin:comfyui:qwen-image:text-to-image") == 2
    assert await tasks.capacity("elsewhere:tool") == 1
    # One waiting call per GPU, so GPUs that finish together each have their next job.
    assert await tasks.workers("comfyui:flux-klein-9b") == 4



def test_a_walrus_in_a_comprehension_binds_at_the_top_level():
    import ast
    from agent.v2.code_runtime import _globals_to_nonlocals, _wrap_run_code
    tree = ast.parse(_wrap_run_code(
        "[(counter := v) for v in range(1)]\n"
        "def bump():\n    global counter, v\n    counter += 1\n"
    ))
    _globals_to_nonlocals(tree.body[0])
    text = ast.unparse(tree)
    assert "nonlocal counter" in text and "global v" in text


@pytest.mark.asyncio
async def test_code_the_global_rewrite_would_break_still_runs(session, test_chat, tmp_path):
    message = await asyncio.wait_for(run_code_detachable(
        "fs = [lambda: (x := 1) for _ in range(1)]\n"
        "def g():\n    global x\n    return 1\n"
        "print('ran', g())",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    ), 5)
    assert "ran 1" in message



def test_a_walrus_inside_a_lambda_is_not_a_top_level_name():
    import ast
    from agent.v2.code_runtime import _globals_to_nonlocals, _wrap_run_code
    tree = ast.parse(_wrap_run_code(
        "fs = [lambda: (x := 1) for _ in range(1)]\n"
        "def g():\n    global x\n    x = 2\n"
    ))
    _globals_to_nonlocals(tree.body[0])
    assert "nonlocal x" not in ast.unparse(tree)


@pytest.mark.asyncio
async def test_run_time_reads_recent_generation_times(session, test_chat, tmp_path):
    import json
    from datetime import datetime, timedelta
    from database import GenerationJob, MediaItem
    from agent.v2.code_runtime import StimmaTasksAPI

    start = datetime(2026, 1, 1)

    async def finished_run(n, tool_id, seconds, **params):
        media = MediaItem(file_path=f"/tmp/run-time-{n}.mp4", file_hash=f"run-time-{n}", file_size=1,
                          file_format="mp4", width=960, height=544, megapixels=0.5,
                          generation_metadata=json.dumps({"parameters": {"generation_time": seconds, **params}}))
        session.add(media)
        await session.flush()
        session.add(GenerationJob(status="completed", task_type="image-to-video", generator_type="stp",
                                  generator_name="box", model_name="h3", parameters="{}", folder_path="/tmp",
                                  tool_id=tool_id, result_media_id=media.id,
                                  completed_at=start + timedelta(minutes=n)))

    await finished_run(1, "gpu0:h3-i2v", 100, duration=5)
    await finished_run(2, "gpu0:h3-i2v", 120, duration=5)
    await finished_run(3, "gpu0:h3-i2v", 300, duration=10)
    await finished_run(4, "gpu0:other", 9)
    await session.commit()

    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False)
    tasks = StimmaTasksAPI(sdk)
    t = await tasks.run_time("gpu0:h3-i2v")
    assert (t["typical_s"], t["fastest_s"], t["slowest_s"], t["runs"]) == (120, 100, 300, 3)
    assert t["recent"][0] == {"seconds": 300, "duration": 10}  # newest first, with its settings
    assert "note" not in t

    # The same tool on another GPU box borrows those runs, and says so.
    other_box = await tasks.run_time("gpu1:h3-i2v")
    assert other_box["typical_s"] == 120 and "another" in other_box["note"]

    none = await tasks.run_time("gpu0:never-run")
    assert none["typical_s"] is None and none["runs"] == 0 and none["note"]

    # Planned settings pick out matching runs; a string setting matches a number.
    five = await tasks.run_time("gpu0:h3-i2v", duration="5")
    assert (five["typical_s"], five["runs"], five["matched_settings"]) == (110, 2, True)
    assert "note" not in five

    # No run with those settings: the overall figures, and a note that says so.
    fifteen = await tasks.run_time("gpu0:h3-i2v", duration=15, width=960)
    assert (fifteen["typical_s"], fifteen["runs"], fifteen["matched_settings"]) == (120, 3, False)
    assert "duration=15" in fifteen["note"]

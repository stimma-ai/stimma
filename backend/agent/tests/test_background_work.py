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
async def test_consecutive_untitled_batches_share_one_progress_card(session, test_chat, tmp_path, fake_generation):
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
        # The run loop has flushed the card by now: it has a chat item.
        for tracker in sdk._progress_trackers:
            tracker._item_id = tracker._item_id or 1

    (tracker,) = sdk._progress_trackers
    state = tracker._build_state()["display_data"]
    assert state["total"] == 6 and state["current"] == 6
    assert state["title"] == "Generating (6)"
    assert sorted(state["previews"]) == [101, 102, 103, 104, 105, 106]


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
async def test_a_gather_of_workers_counts_generations_not_workers(session, test_chat, tmp_path, fake_generation):
    _, releases = fake_generation
    sdk = StimmaSDK(session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=RunControl())
    prompts = [f"shot {n}" for n in range(5)]

    async def worker():
        while prompts:
            await sdk._dispatch_tool("mock:gen", prompt=prompts.pop())

    task = asyncio.create_task(sdk._gather(worker(), worker()))
    await _until(lambda: sdk._progress_trackers)
    seen = []
    while not task.done():
        for event in releases.values():
            event.set()
        (tracker,) = sdk._progress_trackers
        seen.append(tracker._build_state()["display_data"])
        await asyncio.sleep(0.01)
    await task
    final = sdk._progress_trackers[0]._build_state()["display_data"]
    assert (final["title"], final["current"], final["total"]) == ("Generating", 5, 5)
    # While it ran, the bar moved with each finished image, not with each worker.
    assert any(0 < s["current"] < 5 and s["total"] >= 3 for s in seen)

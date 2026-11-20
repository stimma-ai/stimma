"""Background work for the chat agent.

A ``run_code`` execution can leave its turn and keep running: when the user
steers mid-run, when they press Stop and choose to keep generating, or when the
agent asks for ``background=true``. The execution itself doesn't change. It keeps
its worker, its gather and its generation jobs; only the turn stops waiting
for it. When it finishes, the owning chat gets a notification message, which
wakes the agent (see ``service.deliver_background_notification``).

The agent sees and controls this work through ``stimma.tasks``: every
generation call is an item it can inspect and cancel, queued or generating.
What to cancel is the agent's call; this module only gives it the controls.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.logging import get_logger

log = get_logger(__name__)

# A steer waits this long for a run_code to finish on its own before the run
# is moved to the background, so quick code still answers in-turn.
STEER_DETACH_GRACE_SECONDS = 3.0
# With background=true, a run that finishes this fast returns its result
# directly (lint errors, quick code) instead of a background handle.
EXPLICIT_DETACH_GRACE_SECONDS = 1.5
# How often a background run's status is broadcast to the UI.
STATUS_BROADCAST_SECONDS = 2.0
# Finished runs stay inspectable through stimma.tasks for a while.
_FINISHED_KEEP = 20


class GenerationCancelled(RuntimeError):
    """A generation call cancelled on purpose, by the agent or the user."""


_FINAL_ITEM_STATES = {"done", "failed", "cancelled"}


@dataclass
class CallItem:
    """One generation call inside a run_code execution."""

    item: int
    tool: str
    prompt: Optional[str]
    task: Optional[str] = None  # e.g. "text-to-image"
    state: str = "preparing"  # preparing -> submitted -> done | failed | cancelled
    job_id: Optional[int] = None
    media_id: Optional[int] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    began: float = field(default_factory=time.monotonic)

    @property
    def final(self) -> bool:
        return self.state in _FINAL_ITEM_STATES


class RunControl:
    """Shared by one run_code execution and whatever manages it."""

    def __init__(self, session_maker=None):
        self.items: list[CallItem] = []
        # Gather branches that haven't reached their generation call yet.
        self.waiting = 0
        # No new generation call may start (cancel without an item list).
        self.cancel_new = False
        self.detached = False
        self.session_maker = session_maker
        # Job ids are profile-local; cancels must stay in the owning profile.
        from core.profile_context import get_current_profile
        self.profile_id = get_current_profile()

    # -- hooks used by the SDK ------------------------------------------------

    def begin_call(self, tool: str, prompt: Optional[str], task: Optional[str] = None) -> CallItem:
        if self.cancel_new:
            raise GenerationCancelled("Cancelled before it started")
        item = CallItem(item=len(self.items) + 1, tool=tool, prompt=_short(prompt), task=task)
        self.items.append(item)
        return item

    @staticmethod
    def end_call(item: CallItem, *, media_id: Optional[int] = None, error: BaseException | None = None) -> None:
        if error is None:
            item.state = "done"
            item.media_id = media_id
        elif isinstance(error, GenerationCancelled) or item.cancel_requested or isinstance(error, asyncio.CancelledError):
            item.state = "cancelled"
        else:
            item.state = "failed"
            item.error = f"{type(error).__name__}: {error}"[:300]

    def should_cancel(self, item: CallItem) -> bool:
        return item.cancel_requested or self.cancel_new

    @property
    def has_generation_work(self) -> bool:
        return self.waiting > 0 or any(not i.final for i in self.items)

    # -- control ---------------------------------------------------------------

    async def cancel(self, items: Optional[list[int]] = None) -> list[int]:
        """Cancel the given items, or everything left when ``items`` is None.

        Works on queued and generating items alike. Returns the item numbers
        that were asked to stop.
        """
        if items is None:
            self.cancel_new = True
            targets = [i for i in self.items if not i.final]
        else:
            wanted = {int(n) for n in items}
            unknown = wanted - {i.item for i in self.items}
            if unknown:
                raise ValueError(f"No such item(s): {sorted(unknown)}")
            targets = [i for i in self.items if i.item in wanted and not i.final]
        from generation_queue import get_generation_queue
        queue = get_generation_queue()
        for item in targets:
            item.cancel_requested = True
            if item.job_id is not None:
                try:
                    await queue.cancel_job(item.job_id, profile_id=self.profile_id, error="Cancelled by the agent")
                except Exception as e:  # the item may finish in the meantime
                    log.warning(f"background: cancel job {item.job_id} failed: {e}")
        return [i.item for i in targets]

    async def snapshot_items(self) -> list[dict[str, Any]]:
        jobs: dict[int, Any] = {}
        job_ids = [i.job_id for i in self.items if i.job_id is not None and not i.final]
        if job_ids and self.session_maker is not None:
            try:
                from sqlalchemy import select
                from database import GenerationJob
                async with self.session_maker() as s:
                    rows = (await s.execute(select(GenerationJob).where(GenerationJob.id.in_(job_ids)))).scalars().all()
                    jobs = {j.id: j for j in rows}
            except Exception as e:
                log.debug(f"background: job status lookup failed: {e}")
        now = time.monotonic()
        out = []
        for item in self.items:
            entry: dict[str, Any] = {"item": item.item, "tool": item.tool, "state": item.state}
            kind = _media_kind(item.task)
            if kind:
                entry["kind"] = kind
            if item.prompt:
                entry["prompt"] = item.prompt
            job = jobs.get(item.job_id) if item.job_id is not None else None
            if not item.final:
                if job is not None:
                    entry["state"] = "generating" if job.status == "processing" else "queued"
                    entry["runs_on"] = job.generator_type or job.backend_name
                    if job.status == "processing" and job.started_at is not None:
                        from datetime import datetime
                        entry["generating_for_s"] = max(0, int((datetime.utcnow() - job.started_at).total_seconds()))
                else:
                    entry["state"] = "preparing"
                if item.cancel_requested:
                    entry["cancel_requested"] = True
            entry["elapsed_s"] = int(now - item.began)
            if item.media_id is not None:
                entry["media_id"] = item.media_id
            if item.error:
                entry["error"] = item.error
            out.append(entry)
        return out


def _short(text: Optional[str], limit: int = 80) -> Optional[str]:
    if not text:
        return None
    s = str(text).strip().replace("\n", " ")
    return s if len(s) <= limit else s[: limit - 3] + "..."


_AUDIO_TASKS = {"text-to-audio", "text-to-music", "text-to-speech", "audio-to-audio"}
_NON_MEDIA_TASKS = {"speech-to-text", "detect-objects"}


def _media_kind(task: Optional[str]) -> Optional[str]:
    """What a call makes, in the user's words: image, video or audio."""
    if not task or task in _NON_MEDIA_TASKS:
        return None
    if "video" in task or task == "lip-sync":
        return "video"
    if task in _AUDIO_TASKS:
        return "audio"
    return "image"


def _counts(items: list[dict[str, Any]], waiting: int) -> dict[str, int]:
    counts = {"done": 0, "failed": 0, "cancelled": 0, "generating": 0, "queued": 0, "preparing": 0}
    for item in items:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    counts["waiting"] = waiting
    return counts


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@dataclass
class ForegroundRun:
    """A run_code execution its turn is still waiting on."""

    control: RunControl
    label: str
    detach_requested: asyncio.Event = field(default_factory=asyncio.Event)
    detach_wake: bool = True
    # Set once the turn has saved the detached call's tool result.
    result_saved: asyncio.Event = field(default_factory=asyncio.Event)
    detached_id: Optional[str] = None


@dataclass
class BackgroundRun:
    id: str
    profile: str
    chat_id: int
    label: str
    control: RunControl
    task: asyncio.Task
    reason: str
    wake: bool = True
    state: str = "running"  # running -> completed | failed
    started_at: float = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None
    ws_manager: Any = None

    async def snapshot(self) -> dict[str, Any]:
        items = await self.control.snapshot_items()
        return {
            "id": self.id,
            "label": self.label,
            "state": self.state,
            "elapsed_s": int((self.finished_at or time.monotonic()) - self.started_at),
            "counts": _counts(items, self.control.waiting),
            "items": items,
        }


_foreground: dict[tuple[str, int], ForegroundRun] = {}
_runs: dict[tuple[str, int], dict[str, BackgroundRun]] = {}
_next_id: dict[tuple[str, int], int] = {}
# Every task id this process has started, kept after _runs prunes it. A task
# the chat history calls running but that isn't here was started by an earlier
# server process: a restart lost it, and its notification will never come.
_started_here: set[tuple[str, int, str]] = set()

# How describe_detached names a task in its tool result.
DETACHED_CLAIM_RE = re.compile(r'in the background as task (bg-(\d+))(?: \("([^"]*)"\))?')


def _key(chat_id: int) -> tuple[str, int]:
    from core.profile_context import get_current_profile
    return get_current_profile(), chat_id


def set_foreground(chat_id: int, run: Optional[ForegroundRun]) -> None:
    key = _key(chat_id)
    if run is None:
        _foreground.pop(key, None)
    else:
        _foreground[key] = run


def get_foreground(chat_id: int) -> Optional[ForegroundRun]:
    return _foreground.get(_key(chat_id))


async def request_detach(chat_id: int, *, wake: bool, timeout: float = 3.0) -> Optional[str]:
    """Ask the chat's running run_code to move to the background.

    Returns the background id once the turn has saved the call's result, or
    None when there was nothing to move.
    """
    fg = get_foreground(chat_id)
    if fg is None:
        return None
    fg.detach_wake = wake
    fg.detach_requested.set()
    try:
        await asyncio.wait_for(fg.result_saved.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning(f"Chat {chat_id}: run_code didn't move to the background within {timeout}s")
    return fg.detached_id


def detach(
    chat_id: int,
    fg: ForegroundRun,
    task: asyncio.Task,
    *,
    reason: str,
    wake: bool,
    ws_manager=None,
    on_finished: Optional[Callable[["BackgroundRun"], Any]] = None,
) -> BackgroundRun:
    key = _key(chat_id)
    n = _next_id.get(key, 0) + 1
    _next_id[key] = n
    run = BackgroundRun(
        id=f"bg-{n}",
        profile=key[0],
        chat_id=chat_id,
        label=fg.label,
        control=fg.control,
        task=task,
        reason=reason,
        wake=wake,
        ws_manager=ws_manager,
    )
    fg.control.detached = True
    fg.detached_id = run.id
    _started_here.add((key[0], chat_id, run.id))
    _runs.setdefault(key, {})[run.id] = run
    asyncio.create_task(_watch(run, on_finished))
    return run


def started_here(chat_id: int, run_id: str) -> bool:
    return (*_key(chat_id), run_id) in _started_here


def reserve_ids_through(chat_id: int, n: int) -> None:
    """Never hand out an id the chat's history already used, even after a restart."""
    key = _key(chat_id)
    if _next_id.get(key, 0) < n:
        _next_id[key] = n


def list_runs(chat_id: int, *, include_finished: bool = True) -> list[BackgroundRun]:
    runs = list(_runs.get(_key(chat_id), {}).values())
    if not include_finished:
        runs = [r for r in runs if r.state == "running"]
    return runs


def running_task_ids_by_chat() -> dict[int, list[str]]:
    """Background tasks still running, by chat (current profile).

    The agent's turn has ended for these chats, but work it started goes on,
    so they still show as working.
    """
    from core.profile_context import get_current_profile
    profile_id = get_current_profile()
    out: dict[int, list[str]] = {}
    for (profile, chat_id), runs in list(_runs.items()):
        if profile != profile_id:
            continue
        ids = [r.id for r in runs.values() if r.state == "running"]
        if ids:
            out[chat_id] = ids
    return out


def get_run(chat_id: int, run_id: str) -> Optional[BackgroundRun]:
    return _runs.get(_key(chat_id), {}).get(run_id)


async def _broadcast(run: BackgroundRun, event: str) -> None:
    if run.ws_manager is None:
        return
    try:
        await run.ws_manager.broadcast(event, {"chat_id": run.chat_id, "task": await run.snapshot()})
    except Exception as e:
        log.debug(f"background: broadcast {event} failed: {e}")


async def _watch(run: BackgroundRun, on_finished) -> None:
    await _broadcast(run, "background_task_updated")
    last = None
    while not run.task.done():
        await asyncio.wait({run.task}, timeout=STATUS_BROADCAST_SECONDS)
        if run.task.done():
            break
        snap = await run.snapshot()
        marker = json.dumps(snap["counts"], sort_keys=True)
        if marker != last:
            last = marker
            await _broadcast(run, "background_task_updated")

    output = ""
    try:
        result = run.task.result()
        output = result[0] if isinstance(result, tuple) else str(result)
        run.state = "failed" if output.startswith("Error") else "completed"
    except asyncio.CancelledError:
        output = "Error: the background task was cancelled."
        run.state = "failed"
    except Exception as e:
        output = f"Error: {type(e).__name__}: {e}"
        run.state = "failed"
    run.finished_at = time.monotonic()
    await _broadcast(run, "background_task_finished")

    finished = [r for r in _runs.get((run.profile, run.chat_id), {}).values() if r.state != "running"]
    for stale in finished[:-_FINISHED_KEEP]:
        _runs[(run.profile, run.chat_id)].pop(stale.id, None)

    if on_finished is not None:
        try:
            await on_finished(run, output)
        except Exception as e:
            log.error(f"Chat {run.chat_id}: background task {run.id} notification failed: {e}", exc_info=True)


def _quoted(label: str) -> str:
    return f' ("{label}")' if label else ""


def describe_detached(run_id: str, label: str, items: list[dict[str, Any]], waiting: int) -> str:
    """The tool result for a call that moved to the background."""
    counts = _counts(items, waiting)
    done_ids = [str(i["media_id"]) for i in items if i.get("media_id") is not None]
    parts = []
    if counts["done"]:
        parts.append(f"{counts['done']} done (media_id {', '.join(done_ids)})" if done_ids else f"{counts['done']} done")
    for state in ("generating", "queued", "preparing", "failed", "cancelled"):
        if counts[state]:
            parts.append(f"{counts[state]} {state}")
    if waiting:
        parts.append(f"{waiting} not submitted yet")
    status = "; ".join(parts) if parts else "no generation calls yet"
    return (
        f'This code is still running, in the background as task {run_id}{_quoted(label)}: {status}. '
        "Its results keep appearing in the chat, and you'll get a notification with the full "
        "receipt when it finishes, so there's no need to check on it. "
        f'In run_code, `await stimma.tasks.get("{run_id}")` lists each generation (state, '
        "where it runs, how long it has been generating), and "
        f'`await stimma.tasks.cancel("{run_id}", items=[...])` cancels chosen items, queued or '
        "generating; leave out items to cancel everything left."
    )


def notification_text(run: BackgroundRun, output: str) -> str:
    verb = "failed" if run.state == "failed" else "finished"
    return (
        "<task-notification>\n"
        f"Background task {run.id}{_quoted(run.label)} {verb}.\n"
        f"{output}\n"
        "</task-notification>"
    )


def lost_notification_text(run_id: str, label: str) -> str:
    """For a task a server restart killed: its own notification never comes."""
    return (
        "<task-notification>\n"
        f"Background task {run_id}{_quoted(label)} was interrupted: the Stimma server "
        "restarted while it was running. Its code is no longer running and will not "
        "resume, and no other notification will come for it. Generations it had already "
        "submitted may still finish on their own and appear in the chat; anything its "
        "code hadn't submitted yet will not happen. Check what's in the chat before "
        "starting any of it again.\n"
        "</task-notification>"
    )

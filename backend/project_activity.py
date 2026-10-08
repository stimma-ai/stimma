"""Running work per project, for activity indicators on project rows.

``compute_project_activity`` counts running generation jobs, agent runs and
flow evaluations, grouped by project (``None`` is the top level).
``schedule_project_activity_broadcast`` coalesces bursts of start/finish
events into one ``project_activity`` broadcast per profile, sent only when
the snapshot changed.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.profile_context import ProfileScope, get_current_profile

log = get_logger(__name__)

ACTIVE_JOB_STATUSES = ("queued", "assigned", "processing")
DEBOUNCE_SECONDS = 0.5

# Broadcast events that mean work started or finished somewhere.
ACTIVITY_TRIGGER_EVENTS = frozenset({
    "generation_job_queued",
    "generation_job_started",
    "generation_job_completed",
    "generation_job_failed",
    "generation_job_cancelled",
    "generation_job_deleted",
    "batch_completed",
    "agent_started",
    "agent_stopped",
    "flow_updated",
    "flow_deleted",
    "flow_equation_updated",
    "project_deleted",
})

_pending: dict[str, asyncio.Task] = {}
_last_sent: dict[str, list[dict]] = {}


def _running_flow_ids() -> list[int]:
    """Flows (current profile) with evaluations in flight right now."""
    import flow_registry

    profile_id = get_current_profile()
    flow_ids = []
    for (profile, flow_id), runtime in list(flow_registry._RUNTIMES.items()):
        if profile != profile_id:
            continue
        run = getattr(runtime, "run", None)
        try:
            busy = run is not None and run.active_evaluation_count > 0
        except Exception:  # pragma: no cover - defensive
            busy = False
        if busy:
            flow_ids.append(flow_id)
    return flow_ids


def _active_chat_ids() -> list[int]:
    try:
        from agent.v2.service import get_active_chat_ids
    except Exception:  # pragma: no cover - agent module unavailable
        return []
    return get_active_chat_ids()


async def compute_project_activity(session: AsyncSession) -> list[dict]:
    """Nonzero activity counts per project; ``project_id`` None is the top level."""
    from database import Chat, Flow, GenerationJob, Project

    counts: dict[Optional[int], dict[str, int]] = defaultdict(
        lambda: {"running_jobs": 0, "running_chats": 0, "running_flows": 0}
    )

    job_rows = await session.execute(
        select(GenerationJob.project_id, func.count(GenerationJob.id))
        .where(GenerationJob.status.in_(ACTIVE_JOB_STATUSES))
        .group_by(GenerationJob.project_id)
    )
    for project_id, count in job_rows.all():
        counts[project_id]["running_jobs"] += int(count or 0)

    chat_ids = _active_chat_ids()
    if chat_ids:
        chat_rows = await session.execute(
            select(Chat.project_id, func.count(Chat.id))
            .where(Chat.id.in_(chat_ids), Chat.deleted_at.is_(None))
            .group_by(Chat.project_id)
        )
        for project_id, count in chat_rows.all():
            counts[project_id]["running_chats"] += int(count or 0)

    flow_ids = _running_flow_ids()
    if flow_ids:
        flow_rows = await session.execute(
            select(Flow.project_id, func.count(Flow.id))
            .where(Flow.id.in_(flow_ids), Flow.deleted_at.is_(None))
            .group_by(Flow.project_id)
        )
        for project_id, count in flow_rows.all():
            counts[project_id]["running_flows"] += int(count or 0)

    project_ids = [pid for pid in counts if pid is not None]
    live = set()
    if project_ids:
        live = set(await session.scalars(
            select(Project.id).where(Project.id.in_(project_ids), Project.deleted_at.is_(None))
        ))

    activity = []
    for project_id, values in counts.items():
        if project_id is not None and project_id not in live:
            continue
        if not any(values.values()):
            continue
        activity.append({"project_id": project_id, **values})
    activity.sort(key=lambda entry: (entry["project_id"] is not None, entry["project_id"] or 0))
    return activity


async def _compute_for_profile(profile_id: str) -> list[dict]:
    from database_registry import get_database_registry

    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        return await compute_project_activity(session)


async def broadcast_project_activity_now(profile_id: Optional[str] = None, *, force: bool = False) -> None:
    from utils.websocket import ws_manager

    profile_id = profile_id or get_current_profile()
    with ProfileScope(profile_id):
        activity = await _compute_for_profile(profile_id)
        if not force and _last_sent.get(profile_id) == activity:
            return
        _last_sent[profile_id] = activity
        await ws_manager.broadcast("project_activity", {"activity": activity})


async def _debounced(profile_id: str) -> None:
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
        _pending.pop(profile_id, None)
        await broadcast_project_activity_now(profile_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning(f"project_activity broadcast failed: {type(exc).__name__}: {exc}")
    finally:
        if _pending.get(profile_id) is asyncio.current_task():
            _pending.pop(profile_id, None)


def schedule_project_activity_broadcast(profile_id: Optional[str] = None) -> None:
    """Coalesce activity changes into one broadcast about 500ms later."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        profile_id = profile_id or get_current_profile()
    except Exception:
        return
    task = _pending.get(profile_id)
    if task is not None and not task.done():
        return
    _pending[profile_id] = loop.create_task(_debounced(profile_id))


def reset() -> None:
    """Test-only: forget pending broadcasts and the last snapshot."""
    for task in _pending.values():
        task.cancel()
    _pending.clear()
    _last_sent.clear()

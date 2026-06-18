"""Ephemeral media scope for one-shot flow-as-tool runs.

When a flow runs *behind the tool abstraction* (a frozen flow invoked as a tool),
the media its internal ``tool()`` calls produce are implementation detail — they
must NEVER enter the user's library. They are tagged with an ephemeral run id,
born hidden + un-ingested at the creation choke point (``generation_queue``), and
hard-deleted when the run ends (or swept if the run crashes).

This module is the small, dependency-light core:

- an ambient ``ContextVar`` carrying the current ephemeral run id. The one-shot
  runner sets it for the duration of the run; the scheduler's per-equation tasks
  inherit it (asyncio copies the context at ``create_task`` time), so the tool
  evaluator → ``execute_call_tool`` → job submission all see it. The job carries
  the id forward into the (separate) generation-queue worker via its params.
- ``purge_ephemeral_run`` — the hard-delete used both at run end and by the sweeper.

See plans/FLOW_TO_TOOL.md §7 and plans/CUSTOM_TOOLS_BUILD.md.
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from contextvars import ContextVar
from typing import Iterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem

log = logging.getLogger(__name__)


# Ambient ephemeral run id. ``None`` => normal, permanent media (the default for
# every code path that isn't a one-shot flow-as-tool run).
_ephemeral_run_id: ContextVar[Optional[str]] = ContextVar(
    "stimma_ephemeral_run_id", default=None
)


def new_ephemeral_run_id() -> str:
    """A fresh, unique id for one ephemeral run."""
    return f"eph_{uuid.uuid4().hex}"


def current_ephemeral_run_id() -> Optional[str]:
    """The ephemeral run id in scope, or ``None`` outside a one-shot run.

    Read this at the generation-job *submission* point (which runs inside the
    runner's inherited context) to stamp the job; the worker then reads it from
    the job, not from this contextvar (the worker is a separate, pre-existing
    task that does not inherit the context).
    """
    return _ephemeral_run_id.get()


@contextlib.contextmanager
def ephemeral_run(run_id: str) -> Iterator[str]:
    """Mark everything created within this scope as ephemeral run ``run_id``.

    Synchronous context manager — the contextvar is set before any ``await``
    inside the ``with`` body and reset after, and the value persists across
    awaits within the task (and into child tasks spawned inside the body).
    """
    token = _ephemeral_run_id.set(run_id)
    try:
        yield run_id
    finally:
        _ephemeral_run_id.reset(token)


async def purge_ephemeral_run(session: AsyncSession, run_id: str) -> int:
    """Hard-delete every media item (file + DB row) for one ephemeral run.

    Used at run end (after the declared outputs have been read out as bytes) and
    by the crash sweeper. Hard delete, not soft delete — ephemeral media never go
    to trash. Returns the number of rows deleted.

    Self-referential ``superseded_by`` links *within the run* are broken first so
    the row deletes don't trip a foreign-key constraint regardless of delete order.
    """
    rows = (
        await session.execute(
            select(MediaItem).where(MediaItem.ephemeral_run_id == run_id)
        )
    ).scalars().all()
    if not rows:
        return 0

    ids = {m.id for m in rows}
    for m in rows:
        if m.superseded_by in ids:
            m.superseded_by = None
    await session.flush()

    for m in rows:
        path = m.file_path
        if path:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:  # best-effort file cleanup; row delete still proceeds
                log.warning("ephemeral purge: could not remove %s: %s", path, exc)
        await session.delete(m)

    await session.commit()
    log.info("ephemeral purge: hard-deleted %d media for run %s", len(rows), run_id)
    return len(rows)

"""One-shot flow execution — run a flow *behind the tool abstraction*.

A frozen flow, invoked as a tool, must behave EXACTLY like an STP tool: inputs
in, declared outputs out (as bytes), transactional, with **zero** library side
effects. This module is that runner.

It reuses the real graph builder + FRP scheduler + production evaluators (so a
frozen flow runs identically to editing mode), but:

- runs against an ephemeral temp ``state.db`` + a fresh ``EquationStore``
  (no persistence, no caching across runs);
- runs inside an ``ephemeral_run`` scope, so every media the flow's internal
  ``tool()`` calls create is tagged ephemeral, born hidden + un-ingested, and
  **hard-deleted when the run ends** (see ``ephemeral.py`` + the generation-queue
  creation choke point);
- resolves HITL nodes via a deterministic policy (a frozen flow can't pause);
- reads the declared outputs' **bytes** out of the library *before* the purge,
  and returns them — the single canonical output media item is created by the
  normal outer tool-invocation path, never by the flow itself.

See plans/FLOW_TO_TOOL.md §7.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from database import MediaItem
from flow_dsl.loader import build_graph_from_callable, build_graph_from_program_file

from .engine import FlowRun, FlowRunConfig
from .ephemeral import ephemeral_run, new_ephemeral_run_id, purge_ephemeral_run
from .equation_store import EquationStore
from .graph import Equation, EquationGraph, EquationStatus
from .production_evaluators import _open_session, build_production_registry
from .state_db import create_flow_state_db

log = logging.getLogger(__name__)


class OneShotError(RuntimeError):
    """A flow failed to run to completion as a one-shot tool."""


@dataclass
class OneShotMedia:
    media_id: int
    file_format: str
    data: bytes


@dataclass
class OneShotValue:
    """One declared output of the flow."""
    name: str
    value: Any                       # eq.result (a media id for assets; scalar/json otherwise)
    media: list[OneShotMedia] = field(default_factory=list)
    status: str = ""
    error: Optional[str] = None


@dataclass
class OneShotResult:
    outputs: dict[str, OneShotValue]
    run_id: str


# Resolver signature: (Equation, resolved_inputs) -> resolution value.
HitlResolver = Callable[[Equation, dict[str, Any]], Any]


def _default_hitl_resolver(eq: Equation, resolved_inputs: dict[str, Any]) -> Any:
    """Deterministic fallback: select -> first(s), approve -> accept.

    Frozen flows carry per-node policies (first / random / accept-first / lift),
    which the freezer compiles into a resolver passed to ``run_flow_once``. This
    default is the safe baseline when no policy map is supplied.
    """
    hitl_type = eq.definition.get("hitl_type")
    if hitl_type == "select":
        candidates = resolved_inputs.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise OneShotError(f"{eq.key}: hitl.select had no candidates to resolve")
        count = int(eq.definition.get("count", 1) or 1)
        return candidates[0] if count == 1 else candidates[:count]
    if hitl_type == "approve":
        return True
    raise OneShotError(f"{eq.key}: cannot auto-resolve hitl type {hitl_type!r}")


async def run_flow_once(
    *,
    flow_id: int,
    inputs: dict[str, Any],
    program_path: Optional[Path] = None,
    program_text: Optional[str] = None,
    flow_callable: Optional[Callable[..., Any]] = None,
    project_id: Optional[int] = None,
    hitl_resolver: Optional[HitlResolver] = None,
    timeout_seconds: float = 180.0,
) -> OneShotResult:
    """Run a flow to completion once and return its declared outputs (bytes).

    Exactly one of ``program_path`` / ``program_text`` / ``flow_callable`` must
    be given. ``program_text`` is a self-contained program body (a frozen flow's
    ``program_text`` snapshot); it is written into the run's tempdir as
    ``program.py`` and run from there, so a frozen tool runs even after its
    source flow is deleted. Any media produced internally is hard-deleted before
    this returns — the library is left untouched.
    """
    sources = [program_path is not None, program_text is not None, flow_callable is not None]
    if sum(sources) != 1:
        raise ValueError(
            "run_flow_once requires exactly one of program_path / program_text / flow_callable"
        )

    run_id = new_ephemeral_run_id()
    resolver = hitl_resolver or _default_hitl_resolver

    try:
        with ephemeral_run(run_id), tempfile.TemporaryDirectory(
            prefix=f"stimma-flow-oneshot-{flow_id}-"
        ) as td:
            root = Path(td)
            state_db = root / "state.db"
            create_flow_state_db(state_db)
            store = EquationStore(root / "store")
            store.initialize()

            if flow_callable is not None:
                graph = build_graph_from_callable(flow_callable, inputs=inputs)
            else:
                prog_path = program_path
                if program_text is not None:
                    prog_path = root / "program.py"
                    prog_path.write_text(program_text)
                graph = build_graph_from_program_file(prog_path, inputs=inputs)

            run = FlowRun(
                graph,
                FlowRunConfig(
                    flow_id=flow_id,
                    project_id=project_id,
                    state_db_path=state_db,
                    retry_backoff_seconds=0.0,
                    broadcast=None,                 # no websocket from a tool run
                    hitl_auto_resolve=resolver,
                ),
                evaluators=build_production_registry(),
                store=store,
            )

            try:
                await run.start()
                await _wait_quiescent(run, timeout_seconds)
            finally:
                await run.stop()

            _raise_on_failure(graph)
            outputs = await _collect_outputs(graph)

        return OneShotResult(outputs=outputs, run_id=run_id)
    finally:
        # Always reclaim the run's media — on success (after bytes are read) and
        # on failure (partial run). The sweeper is the backstop if this trips.
        await _purge(run_id)


async def _wait_quiescent(run: FlowRun, timeout_seconds: float) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        if run._is_quiescent():  # scheduler-adjacent, same as dry_run
            return
        if loop.time() >= deadline:
            raise OneShotError(f"flow did not finish within {timeout_seconds:.0f}s")
        await asyncio.sleep(0.05)


def _raise_on_failure(graph: EquationGraph) -> None:
    for eq in graph.all_equations():
        if eq.status in (EquationStatus.FAILED, EquationStatus.WAITING_FOR_TOOL):
            raise OneShotError(f"{eq.key}: {eq.error or eq.status.value}")
        if eq.status == EquationStatus.AWAITING_INPUT:
            raise OneShotError(
                f"{eq.key}: flow paused for human input — a frozen tool can't pause"
            )


async def _collect_outputs(graph: EquationGraph) -> dict[str, OneShotValue]:
    out: dict[str, OneShotValue] = {}
    async with _open_session() as session:
        for eq_key in graph.output_keys:
            eq = graph.get(eq_key)
            name = graph.output_name_by_key.get(eq_key, eq_key)
            media: list[OneShotMedia] = []
            for mid in (eq.result_media_ids or []):
                row = (
                    await session.execute(select(MediaItem).where(MediaItem.id == mid))
                ).scalar_one_or_none()
                if row and row.file_path and os.path.exists(row.file_path):
                    with open(row.file_path, "rb") as f:
                        media.append(
                            OneShotMedia(
                                media_id=mid,
                                file_format=row.file_format,
                                data=f.read(),
                            )
                        )
            out[name] = OneShotValue(
                name=name,
                value=eq.result,
                media=media,
                status=eq.status.value,
                error=eq.error,
            )
    return out


async def _purge(run_id: str) -> None:
    try:
        async with _open_session() as session:
            await purge_ephemeral_run(session, run_id)
    except Exception:  # noqa: BLE001 — sweeper is the backstop
        log.exception("ephemeral purge failed for run %s; sweeper will reclaim", run_id)

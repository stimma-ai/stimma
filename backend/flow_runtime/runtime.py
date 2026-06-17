"""Top-level runtime orchestrator.

Wires the in-memory `EquationGraph` + `FlowRun` to the flow's
per-flow state.db and program.py. Intended to be the single entry point
other parts of the backend use to start/pause/resume/invalidate/edit a
flow.

One `FlowRuntime` per flow. Tests construct them directly; production
code (Phase 3 API wiring) will keep a registry of active runtimes keyed by
flow_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from flow_dsl.errors import ProgramLoadError
from flow_dsl.loader import (
    build_graph_from_callable,
    build_graph_from_program_file,
    load_program_with_error_classification,
)
from flow_dsl.versions import ProgramVersionStore, get_version_store

from . import graph_db
from .engine import FlowRun, FlowRunConfig
from .equation_store import EquationStore, get_equation_store
from .evaluators import EvaluatorRegistry
from .graph import Equation, EquationGraph, EquationStatus, EquationType
from .graph_diff import GraphDiff, diff_graphs


log = logging.getLogger(__name__)


class FlowRuntime:
    """Owns the graph + scheduler for one flow.

    Typical lifecycle:

        runtime = FlowRuntime(flow_id, state_db_path, program_path, inputs,
                                evaluators=registry)
        runtime.build_initial_graph()
        await runtime.start()
        # ... user interactions ...
        await runtime.pause()
        await runtime.resume()
        await runtime.stop()

    Editing a program:

        runtime.reload_program()   # rebuilds graph, diffs, resets changed
        await runtime.start()      # or leave it running — resume picks up
    """

    def __init__(
        self,
        flow_id: int,
        state_db_path: Path,
        *,
        program_path: Optional[Path] = None,
        flow_callable: Optional[Callable[..., Any]] = None,
        inputs: Optional[dict[str, Any]] = None,
        evaluators: Optional[EvaluatorRegistry] = None,
        store: Optional[EquationStore] = None,
        concurrency: int = 10,
        retry_backoff_seconds: float = 0.0,
        version_store: Optional[ProgramVersionStore] = None,
        broadcast: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        project_id: Optional[int] = None,
    ) -> None:
        if program_path is None and flow_callable is None:
            raise ValueError("program_path or flow_callable is required")
        self.flow_id = flow_id
        self.project_id = project_id
        self.state_db_path = state_db_path
        self.program_path = program_path
        self.flow_callable = flow_callable
        self.inputs = dict(inputs or {})
        self.evaluators = evaluators or EvaluatorRegistry()
        # Wire any LLM slot evaluators to read from our graph — slots do
        # peer-aware solo-gen by reading sibling slot .result fields at eval
        # time, and the evaluator needs a handle to find them. The registry
        # is typically built before the runtime exists (so the graph getter
        # can't be a constructor arg there); we inject it here.
        for _eval in self.evaluators.evaluators.values():
            setter = getattr(_eval, "set_graph_getter", None)
            if callable(setter):
                setter(lambda: self.graph)
        self.store = store if store is not None else get_equation_store()
        self._concurrency = concurrency
        self._retry_backoff = retry_backoff_seconds
        # Version tracking is file-based next to program.py; derive the dir
        # from the program path when not passed in. Runtimes driven by a
        # direct callable (tests) don't need versions.
        if version_store is not None:
            self._version_store: Optional[ProgramVersionStore] = version_store
        elif program_path is not None:
            self._version_store = get_version_store(program_path.parent)
        else:
            self._version_store = None
        # Broadcaster for flow_updated / flow_phase_updated events.
        # Defaults to a no-op so tests don't need an asyncio broadcaster.
        self._broadcast = broadcast

        self.graph: Optional[EquationGraph] = None
        self.run: Optional[FlowRun] = None
        # Last program-load error, or None if the current graph is good.
        self.last_load_error: Optional[ProgramLoadError] = None

    # ------------------------------------------------------------------
    # Graph lifecycle

    def _settle_flow_input_equations(self, graph: EquationGraph) -> None:
        """Eagerly complete flow inputs whose values are already present.

        The scheduler also completes FLOW_INPUT control equations, but a
        flow can have a live graph while idle or paused (e.g. after a
        reparse, or after invalidation while paused). In those states a
        populated input should not sit in ``pending`` and render as
        "waiting" — its value is already known from ``runtime.inputs``.
        """
        for eq in graph.all_equations():
            if eq.equation_type != EquationType.FLOW_INPUT:
                continue
            if eq.is_waiting_for_flow_input():
                continue
            if eq.definition.get("is_collection", True):
                stored_values = eq.definition.get("values")
                value = list(stored_values) if stored_values is not None else []
            else:
                value = eq.definition.get("value")
            was_already_settled = (
                eq.status == EquationStatus.COMPLETED
                and eq.error is None
                and eq.result == value
                and list(eq.result_media_ids) == []
            )
            eq.status = EquationStatus.COMPLETED
            eq.result = value
            eq.result_media_ids = []
            eq.execution_duration_ms = None
            eq.error = None
            graph_db.update_equation_status(
                self.state_db_path,
                eq.key,
                EquationStatus.COMPLETED,
                result=value,
                result_media_ids=[],
                execution_duration_ms=None,
                mark_completed=True,
            )
            if not was_already_settled:
                self._broadcast_equation_updated(graph, eq)

    def build_initial_graph(self, inputs: Optional[dict[str, Any]] = None) -> EquationGraph:
        if inputs is not None:
            self.inputs = dict(inputs)
        if self.flow_callable is not None:
            graph = build_graph_from_callable(self.flow_callable, inputs=self.inputs)
        else:
            graph = build_graph_from_program_file(self.program_path, inputs=self.inputs)
        # Hydrate any stored results from state.db (covers app-restart
        # recovery and store-hit shortcuts).
        graph_db.hydrate_results_into_graph(self.state_db_path, graph)
        # Any 'computing' rows in state.db are stale; reset to pending.
        graph_db.reset_computing_to_pending(self.state_db_path)
        # Drop equations that exist in state.db but not in the freshly-built
        # graph. ``reload_program`` runs a graph diff and prunes removed
        # rows, but ``build_initial_graph`` (called on app/runtime startup)
        # never had that step — so any equation whose primitive was
        # renamed/replaced between runtime instances stuck around forever
        # and rendered as a ghost row in its phase. The graph just built
        # from program.py is the source of truth: anything else in the DB
        # is a leftover from a prior version of the program.
        live_keys = {eq.key for eq in graph.all_equations()}
        orphan_keys = graph_db.load_equation_keys(self.state_db_path) - live_keys
        if orphan_keys:
            for key in orphan_keys:
                graph_db.cancel_pending_tasks_for_equation(self.state_db_path, key)
            graph_db.delete_equations_by_keys(self.state_db_path, orphan_keys)
            log.info(
                "build_initial_graph: pruned %d orphan equation(s) from state.db "
                "for flow %s (program edited between runtime instances)",
                len(orphan_keys), self.flow_id,
            )
        self.graph = graph
        graph_db.upsert_equations(self.state_db_path, graph.all_equations())
        # INSERT OR IGNORE above leaves pre-existing rows with stale
        # definitions — program.py may have been edited between runtime
        # instances (DSL upgrades, input flag flips like `optional=True`).
        # Rewrite definitions from the just-built graph so the DB reflects
        # the program on disk.
        graph_db.sync_equation_definitions(
            self.state_db_path, graph.all_equations(),
        )
        self._settle_flow_input_equations(graph)
        self.last_load_error = None
        # Snapshot the initial program source so the agent can roll back to
        # it later. Idempotent — if the same source is already recorded,
        # record() simply appends a manifest entry without re-writing.
        self._snapshot_program(note="initial")
        return graph

    def reload_program(self) -> GraphDiff:
        """Rebuild the graph from program.py and diff against the running one.

        Preserves equations whose key + definition_hash match the old
        graph. Resets changed equations to pending. Removes equations that
        no longer exist in the new graph (from state.db). Returns the
        GraphDiff.

        If the new program fails to load, the previous graph stays active,
        ``last_load_error`` is populated, and ``ProgramLoadError`` is raised
        so the caller can surface the error to the user/agent. Callers that
        want a non-raising variant should use ``try_reload_program``.
        """
        diff, error = self.try_reload_program()
        if error is not None:
            raise error
        assert diff is not None
        return diff

    def try_reload_program(self) -> tuple[Optional[GraphDiff], Optional[ProgramLoadError]]:
        """Non-raising variant of ``reload_program``.

        Returns ``(GraphDiff, None)`` on success or ``(None, ProgramLoadError)``
        on failure. In the failure case the previous graph is preserved and
        ``last_load_error`` is updated.
        """
        if self.graph is None:
            raise RuntimeError("reload_program: call build_initial_graph first")

        old_graph = self.graph
        try:
            if self.flow_callable is not None:
                new_graph = build_graph_from_callable(
                    self.flow_callable, inputs=self.inputs
                )
            else:
                new_graph = build_graph_from_program_file(
                    self.program_path, inputs=self.inputs
                )
        except ProgramLoadError as exc:
            self.last_load_error = exc
            self._snapshot_program(note=f"failed: {exc.category}", is_good=False)
            self._broadcast_now(
                "flow_updated",
                {
                    "flow_id": self.flow_id,
                    "load_error": {
                        "category": exc.category,
                        "message": str(exc),
                        "suggestion": exc.suggestion,
                    },
                },
            )
            return None, exc

        diff = diff_graphs(old_graph, new_graph)

        for key in diff.unchanged:
            old_eq = old_graph.get(key)
            new_eq = new_graph.get(key)
            new_eq.status = old_eq.status
            new_eq.result = old_eq.result
            new_eq.result_media_ids = list(old_eq.result_media_ids)
            new_eq.execution_duration_ms = old_eq.execution_duration_ms
            new_eq.compute_duration_ms = old_eq.compute_duration_ms
            new_eq.attempt = old_eq.attempt
            new_eq.inputs_hash = old_eq.inputs_hash
            new_eq.error = old_eq.error
            cached = getattr(old_eq, "_iteration_keys_cache", None)
            if cached is not None:
                setattr(new_eq, "_iteration_keys_cache", list(cached))

        # Cascade invalidation from changed equations to their downstream
        # descendants. The descendants themselves are structurally unchanged
        # (their definition_hash still matches), so the loop above just
        # inherited their old COMPLETED status + cached result. But the
        # upstream input they consume just changed — that cache is stale.
        # Reset them to PENDING so the engine recomputes with the new
        # upstream value.
        cascade_invalidate: set[str] = set()
        for changed_key in diff.changed:
            cascade_invalidate.add(changed_key)
            cascade_invalidate.update(new_graph.descendants(changed_key))

        for key in cascade_invalidate:
            new_eq = new_graph.try_get(key)
            if new_eq is None:
                continue
            # If this was a completed HITL, drop the cached resolution so
            # re-eval re-asks instead of silently reusing the stale pick
            # (same reasoning as engine._reset_equation_to_pending).
            old_eq = old_graph.try_get(key)
            if (
                old_eq is not None
                and old_eq.equation_type.value == "hitl"
                and old_eq.inputs_hash
            ):
                graph_db.delete_hitl_result(
                    self.state_db_path, key, old_eq.inputs_hash,
                )
            new_eq.status = EquationStatus.PENDING
            new_eq.result = None
            new_eq.result_media_ids = []
            new_eq.execution_duration_ms = None
            new_eq.compute_duration_ms = None
            new_eq.inputs_hash = None
            new_eq.error = None

        # Clean up stale pending HITL tasks before touching the DB.
        #
        # Removed equations: the FK cascade from delete_equations_by_keys will
        # drop their tasks silently — but "silently" means no
        # flow_task_resolved event fires, so the denormalized
        # pending_task_count column drifts. Gather the task ids explicitly
        # first, cancel them, then broadcast per task so listeners stay
        # consistent.
        #
        # Changed equations and their descendants: a descendant may have
        # been AWAITING_INPUT in the old graph, which means there's a pending
        # HITL task bound to a now-stale inputs_hash. Cancel + broadcast so
        # per-flow task views don't drift.
        tasks_to_notify: list[dict[str, Any]] = []
        hitl_cleanup_keys = set(diff.removed) | cascade_invalidate
        for key in hitl_cleanup_keys:
            tasks_to_notify.extend(
                graph_db.list_pending_tasks_for_equation(
                    self.state_db_path, key,
                )
            )
            graph_db.cancel_pending_tasks_for_equation(self.state_db_path, key)

        graph_db.delete_equations_by_keys(self.state_db_path, diff.removed)
        graph_db.upsert_equations(self.state_db_path, new_graph.all_equations())
        # INSERT OR IGNORE above leaves pre-existing rows with stale
        # structural columns (definition/phase_path/dependencies). Refresh
        # them from the just-rebuilt graph — a program edit may have moved
        # an equation into a different `with phase(...)` block or added a
        # dependency without changing the equation's definition hash, and
        # the phase-tree sort relies on phase_path + dependencies being
        # current.
        graph_db.sync_equation_definitions(
            self.state_db_path, new_graph.all_equations(),
        )

        # upsert_equations is INSERT OR IGNORE — existing rows (for changed
        # keys and unchanged descendants of changed keys) keep their stale
        # status/result in state.db. Force the reset here so the DB matches
        # the in-memory graph we just invalidated.
        changed_keys = set(diff.changed)
        for key in cascade_invalidate:
            new_eq = new_graph.try_get(key)
            if new_eq is None:
                continue
            update_kwargs: dict[str, Any] = {
                "result": None,
                "result_media_ids": [],
                "execution_duration_ms": None,
                "compute_duration_ms": None,
                "error": None,
                "inputs_hash": None,
                "completed_at": None,
                "attempt": new_eq.attempt,
                "mark_invalidated": True,
            }
            if key in changed_keys:
                update_kwargs["definition"] = new_eq.definition
            graph_db.update_equation_status(
                self.state_db_path,
                key,
                EquationStatus.PENDING,
                **update_kwargs,
            )
            self._broadcast_now(
                "flow_equation_updated",
                {
                    "flow_id": self.flow_id,
                    "equation_key": key,
                    "equation_type": new_eq.equation_type.value,
                    "status": new_eq.status.value,
                    "phase_path": list(new_eq.phase_path),
                    "attempt": new_eq.attempt,
                    "result_media_ids": list(new_eq.result_media_ids),
                    "execution_duration_ms": new_eq.execution_duration_ms,
                    "compute_duration_ms": new_eq.compute_duration_ms,
                    "error": new_eq.error,
                    "root_status_summary": self._root_status_summary(new_graph),
                },
            )

        # Fire a flow_task_resolved for each stale task so the pending
        # counter and per-flow task view refresh. We do this after the DB
        # writes settle so any listener that re-reads state.db sees the
        # cancelled rows.
        for task_row in tasks_to_notify:
            self._broadcast_now(
                "flow_task_resolved",
                {
                    "flow_id": self.flow_id,
                    "task_id": task_row.get("id"),
                    "task_type": task_row.get("task_type"),
                    "equation_key": task_row.get("equation_key"),
                    "reason": "program_edit",
                },
            )

        self._settle_flow_input_equations(new_graph)
        self.graph = new_graph
        if self.run is not None:
            self.run.graph = new_graph
            # Drop any in-memory pending-HITL records that reference equations
            # the reload just removed or invalidated — the tasks they map to
            # were cancelled above, and the lookup would otherwise linger as
            # a memory leak for the lifetime of the run.
            stale_keys = set(diff.removed) | cascade_invalidate
            pending_hitl = getattr(self.run, "_pending_hitl", None)
            if stale_keys and isinstance(pending_hitl, dict):
                for tid, rec in list(pending_hitl.items()):
                    if getattr(rec, "equation_key", None) in stale_keys:
                        pending_hitl.pop(tid, None)
            self.run._wakeup.set()

        self.last_load_error = None
        self._snapshot_program(note="edit")
        self._broadcast_now(
            "flow_updated",
            {
                "flow_id": self.flow_id,
                "graph_diff": {
                    "unchanged": diff.unchanged,
                    "changed": diff.changed,
                    "added": diff.added,
                    "removed": diff.removed,
                },
                # Explicit None clears any prior load_error flag in the
                # frontend singleton. Without this, a successful rollback
                # leaves the status pill stuck on Error.
                "load_error": None,
            },
        )
        self._broadcast_phase_updates(old_graph, new_graph)

        return diff, None

    # ------------------------------------------------------------------
    # Version tracking

    def rollback_to_latest_good_program(self) -> Optional[GraphDiff]:
        """Overwrite program.py with the last known-good version and rebuild.

        Returns the GraphDiff from the rollback, or None if no good version
        was recorded (e.g. the very first program.py failed to load).
        """
        if self._version_store is None:
            return None
        record = self._version_store.rollback_to_latest_good(note="rollback after failure")
        if record is None:
            return None
        diff, error = self.try_reload_program()
        if error is not None:
            raise error
        return diff

    def list_program_versions(self):
        if self._version_store is None:
            return []
        return self._version_store.list_versions()

    def rollback_to_program_version(self, version_hash: str) -> GraphDiff:
        if self._version_store is None:
            raise RuntimeError("no version store configured for this runtime")
        self._version_store.rollback_to(version_hash, note=f"explicit rollback")
        diff, error = self.try_reload_program()
        if error is not None:
            raise error
        assert diff is not None
        return diff

    # ------------------------------------------------------------------
    # Internals

    def _snapshot_program(self, *, note: str = "", is_good: bool = True) -> None:
        if self._version_store is None or self.program_path is None:
            return
        try:
            self._version_store.snapshot_current(note=note, is_good=is_good)
        except Exception as exc:  # pragma: no cover — best-effort bookkeeping
            log.warning(f"program version snapshot failed: {exc}")

    def _broadcast_now(self, event: str, payload: dict) -> None:
        """Schedule the broadcast if we're in an event loop; else drop it.

        Runtime reload_program is called from both async contexts (HTTP
        handlers) and sync contexts (direct test drivers). We detect and
        adapt instead of making the whole method async.
        """
        if self._broadcast is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop — likely a sync test path
        try:
            loop.create_task(self._broadcast(event, payload))
        except Exception as exc:  # pragma: no cover
            log.warning(f"broadcast({event}) failed: {exc}")

    def _root_status_summary(self, graph: EquationGraph) -> dict[str, int]:
        from .summary import compute_root_summary_from_equations
        return compute_root_summary_from_equations(graph.all_equations())

    def _broadcast_equation_updated(
        self, graph: EquationGraph, eq: Equation,
    ) -> None:
        self._broadcast_now(
            "flow_equation_updated",
            {
                "flow_id": self.flow_id,
                "equation_key": eq.key,
                "equation_type": eq.equation_type.value,
                "status": eq.status.value,
                "phase_path": list(eq.phase_path),
                "attempt": eq.attempt,
                "result_media_ids": list(eq.result_media_ids),
                "execution_duration_ms": eq.execution_duration_ms,
                "compute_duration_ms": eq.compute_duration_ms,
                "error": eq.error,
                "root_status_summary": self._root_status_summary(graph),
            },
        )

    def _broadcast_phase_updates(
        self, old_graph: EquationGraph, new_graph: EquationGraph
    ) -> None:
        """Broadcast flow_phase_updated for each distinct phase touched by diff.

        Phase path is stored per-equation; we collect the union of phase
        paths across changed/added/removed equations and emit one event per
        unique path.
        """
        if self._broadcast is None:
            return
        touched: set[tuple[str, ...]] = set()
        for graph, keys in (
            (new_graph, set(new_graph.keys()) - set(old_graph.keys())),
            (old_graph, set(old_graph.keys()) - set(new_graph.keys())),
        ):
            for key in keys:
                eq = graph.try_get(key)
                if eq is None:
                    continue
                touched.add(tuple(eq.phase_path))
        for key in set(new_graph.keys()) & set(old_graph.keys()):
            if old_graph.get(key).phase_path != new_graph.get(key).phase_path:
                touched.add(tuple(new_graph.get(key).phase_path))
        for path in touched:
            self._broadcast_now(
                "flow_phase_updated",
                {
                    "flow_id": self.flow_id,
                    "phase_path": list(path),
                },
            )

    # ------------------------------------------------------------------
    # Run control

    async def start(self) -> None:
        if self.graph is None:
            self.build_initial_graph()
        if self.run is None:
            self.run = FlowRun(
                self.graph,
                FlowRunConfig(
                    flow_id=self.flow_id,
                    project_id=self.project_id,
                    state_db_path=self.state_db_path,
                    concurrency=self._concurrency,
                    retry_backoff_seconds=self._retry_backoff,
                    broadcast=self._broadcast,
                ),
                evaluators=self.evaluators,
                store=self.store,
            )
        await self.run.start()

    async def pause(self) -> None:
        if self.run is None:
            return
        await self.run.pause()

    async def resume(self) -> None:
        if self.run is None:
            return
        await self.run.resume()

    def recover_orphaned_work(self) -> None:
        if self.run is None:
            return
        self.run.recover_orphaned_work()

    async def stop(self) -> None:
        if self.run is None:
            return
        await self.run.stop()

    async def wait_quiescent(self, timeout: Optional[float] = None) -> None:
        if self.run is None:
            return
        await self.run.wait_quiescent(timeout=timeout)

    def invalidate(self, equation_key: str) -> int:
        if self.run is None:
            raise RuntimeError("invalidate: FlowRun not started")
        return self.run.invalidate(equation_key)

    async def reselect_hitl(self, equation_key: str, new_resolution: Any) -> int:
        if self.run is None:
            raise RuntimeError("reselect_hitl: FlowRun not started")
        return await self.run.reselect_hitl(equation_key, new_resolution)

    async def resolve_task(self, task_id: int, resolution: Any) -> None:
        if self.run is None:
            raise RuntimeError("resolve_task: FlowRun not started")
        await self.run.resolve_task(task_id, resolution)

    async def resolve_error_task(
        self, task_id: int, action: str, *, value: Any = None,
    ) -> None:
        if self.run is None:
            raise RuntimeError("resolve_error_task: FlowRun not started")
        await self.run.resolve_error_task(task_id, action, value=value)

    def list_tasks(
        self,
        *,
        status: str = "pending",
        task_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        if self.run is not None:
            return self.run.list_tasks(status=status, task_types=task_types)
        # Not started — read directly; downstream_count is unavailable.
        rows = graph_db.list_tasks(
            self.state_db_path, status=status, task_types=task_types,
        )
        for row in rows:
            row["downstream_count"] = 0
        return rows


# ----- App restart recovery --------------------------------------------------


def recover_all_running_flows(
    flow_rows: list[dict[str, Any]],
    build_runtime: Callable[[dict[str, Any]], FlowRuntime],
) -> list[FlowRuntime]:
    """Reset `computing` rows to `pending` and return runtimes ready to start.

    Called at backend startup (FLOWS_TECH §Implementation Notes). Caller
    supplies `flow_rows` (list of row-dicts with at least id and
    state_db_path accessible), and a builder that constructs a configured
    `FlowRuntime` for each.

    The function itself is pure — it doesn't start the runtimes. That
    decision belongs to the caller (some callers may want to leave
    previously-running flows paused until the user confirms).
    """
    runtimes: list[FlowRuntime] = []
    for row in flow_rows:
        runtime = build_runtime(row)
        runtime.build_initial_graph()
        runtimes.append(runtime)
    return runtimes

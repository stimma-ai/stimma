"""Flow execution engine — the FRP scheduler.

Owns one `FlowRun` per running flow. Responsibilities:

  - resolve ready equations (dependencies satisfied, status=pending)
  - expand deferred foreach nodes as their inputs resolve
  - run up to N evaluations in parallel (N = CONCURRENCY_CAP, default 10)
  - route evaluation to the registered evaluator per equation type
  - apply store-lookup / HITL-result lookup before evaluating
  - invalidate + cascade downstream on user request
  - pause / resume
  - classify errors and retry within the policy budget

Tool invocations submitted by evaluators are expected to go through the
existing generation queue, which handles provider-side concurrency below
the flow's cap (FLOWS_TECH §FRP Runtime).

All state changes write through to the per-flow state.db via
`graph_db.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Awaitable, Callable, Iterable, Optional

from . import foreach_expansion, graph_db
from .foreach_expansion import EarlyExpansionUnsupported as _EarlyExpansionUnsupported
from .equation_store import EquationStore, get_equation_store
from .evaluators import (
    CODE_ERROR,
    EvaluationRequest,
    EvaluationResult,
    EvaluatorError,
    EvaluatorRegistry,
    LLM_ERROR,
    RESOURCE_ERROR,
    TOOL_ERROR,
    TOOL_UNAVAILABLE,
    TRANSIENT,
    classify_exception,
    retry_budget,
)
from .graph import (
    DeferredExpansion,
    Equation,
    EquationGraph,
    EquationStatus,
    EquationType,
    NodeRef,
)
from .keys import (
    make_nested_foreach_iteration_key,
)
from .store_key import (
    compute_store_key,
    derive_seed,
    inputs_hash_for_values,
)


log = logging.getLogger(__name__)


# Equation types whose outputs are stochastic (the evaluator pulls a
# per-equation seed derived from equation_key+attempt). These need the seed
# folded into inputs_hash, otherwise two equations with identical resolved
# inputs — e.g. `foreach(range(4), lambda _: tool("flux", prompt="x"))` —
# collapse to one store key and the cache serves iteration 0's result for
# every iteration, so the tool is never actually invoked with each
# iteration's distinct seed.
_SEED_KEYED_EQUATION_TYPES = frozenset({
    EquationType.TOOL_CALL,
    EquationType.LLM_CALL,
    EquationType.LLM_BATCH,
    EquationType.LLM_SLOT,
})


_TERMINAL_DEFERRED_OWNER_STATUSES = frozenset({
    EquationStatus.COMPLETED,
    EquationStatus.SKIPPED,
})


def _walk_noderefs(value: Any) -> Iterable[NodeRef]:
    """Yield every NodeRef in a (possibly nested) dynamic binding value."""
    if isinstance(value, NodeRef):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_noderefs(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_noderefs(item)


CONCURRENCY_CAP = 10


class RunState:
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class FlowRunConfig:
    """Fixed configuration for a single FlowRun (never mutated)."""
    flow_id: int
    state_db_path: Path
    project_id: Optional[int] = None
    concurrency: int = CONCURRENCY_CAP
    # Retry backoff base; doubled per attempt. Kept tiny so tests run fast.
    retry_backoff_seconds: float = 0.0
    # Optional async broadcaster: fn(event_name, payload) -> awaitable. The
    # runtime/engine uses this to emit flow_task_created /
    # flow_task_resolved / flow_equation_updated events. Defaults to a
    # no-op so tests that don't need WS events can skip wiring.
    broadcast: Optional[Callable[[str, dict[str, Any]], Awaitable[None]]] = None
    finalize_media_results: Optional[
        Callable[[str, list[int], str], Awaitable[None]]
    ] = None
    release_media_results: Optional[
        Callable[[list[str], bool], Awaitable[None]]
    ] = None
    # Optional non-production hook used by dry-run/preflight execution. When
    # present, HITL equations are completed with this resolver's synthetic
    # resolution instead of creating durable user tasks.
    hitl_auto_resolve: Optional[Callable[[Equation, dict[str, Any]], Any]] = None


@dataclass
class PendingHitl:
    equation_key: str
    task_id: int
    task_type: str
    payload: dict[str, Any]
    instructions: str
    inputs_hash: str


class FlowRun:
    """Execution state for a single running flow.

    Usage:
        run = FlowRun(graph, config, evaluators=registry, store=store)
        await run.start()   # starts the background scheduler
        ...                 # other code may invalidate, resolve tasks, etc.
        await run.pause()   # or .wait_quiescent() / .stop()

    The scheduler runs on the event loop of the task that called start().
    """

    def __init__(
        self,
        graph: EquationGraph,
        config: FlowRunConfig,
        *,
        evaluators: EvaluatorRegistry,
        store: Optional[EquationStore] = None,
        rebuild_graph: Optional[Callable[[], EquationGraph]] = None,
    ) -> None:
        self.graph = graph
        self.config = config
        self.evaluators = evaluators
        self.store = store if store is not None else get_equation_store()
        self._rebuild_graph = rebuild_graph

        self._state = RunState.IDLE
        self._task: Optional[asyncio.Task[None]] = None
        self._sem = asyncio.Semaphore(config.concurrency)
        self._wakeup = asyncio.Event()
        self._in_flight: dict[str, asyncio.Task[None]] = {}
        self._pending_hitl: dict[int, PendingHitl] = {}  # task_id -> record
        self._paused_event = asyncio.Event()
        self._paused_event.set()  # not paused by default
        self._stopped_event = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tools_changed_cb: Optional[Callable[[], None]] = None
        # Correlation run id for this flow run — stable across pause/resume
        # so all of the run's Stimma Cloud LLM calls group together.
        self._correlation_run_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Public control API

    @property
    def state(self) -> str:
        return self._state

    async def start(self) -> None:
        if (
            self._state == RunState.RUNNING
            and self._task is not None
            and not self._task.done()
        ):
            return
        if self._state == RunState.RUNNING:
            log.warning(
                "flow %s: scheduler was marked RUNNING but task is dead; restarting",
                self.config.flow_id,
            )
            self._state = RunState.IDLE
        # Any equation marked COMPUTING at this point isn't really — no task
        # is in flight yet. This happens when a backend restart interrupted
        # a previous run mid-evaluation, or when nodemon killed the process
        # during dev. Reset those rows so the scheduler re-picks them.
        self._reset_stale_computing()
        # Persist initial graph rows (no-op if already persisted).
        graph_db.upsert_equations(self.config.state_db_path, self.graph.all_equations())
        self._state = RunState.RUNNING
        self._stopped_event.clear()
        self._wakeup.set()
        self._loop = asyncio.get_running_loop()
        self._subscribe_tools_changed()
        self._start_loop_task()

    async def pause(self) -> None:
        """Stop scheduling new work. Returns immediately; in-flight
        evaluations keep running and finish naturally (their results are
        written through to state.db on completion). Per FLOWS_TECH
        §Pause / Resume.
        """
        if self._state != RunState.RUNNING:
            return
        self._state = RunState.PAUSED
        self._paused_event.clear()
        self._wakeup.set()

    async def resume(self) -> None:
        if self._state != RunState.PAUSED:
            return
        # Same rationale as start(): a pause held through a restart may leave
        # COMPUTING rows with no owning task. Reset those so resume actually
        # makes progress rather than just flipping a state flag.
        self._reset_stale_computing()
        self._state = RunState.RUNNING
        self._paused_event.set()
        self._wakeup.set()
        if self._task is None or self._task.done():
            self._start_loop_task()

    def _start_loop_task(self) -> None:
        self._task = asyncio.create_task(
            self._run_loop(), name=f"flow-run-{self.config.flow_id}"
        )
        self._task.add_done_callback(self._on_loop_done)

    def _on_loop_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            return
        log.exception(
            "flow %s: scheduler task exited unexpectedly",
            self.config.flow_id,
            exc_info=exc,
        )
        if self._state == RunState.RUNNING:
            # Let the next start/resume/invalidate/task-resolution wakeup
            # recreate the scheduler instead of reporting a zombie "running"
            # loop that will never consume wakeup events.
            self._state = RunState.IDLE

    def _subscribe_tools_changed(self) -> None:
        """Self-heal WAITING_FOR_TOOL equations when tools register.

        Registry subscribers are called synchronously from the registry's
        mutators (off the scheduler's event loop). We bounce the work back
        onto the scheduler loop via ``call_soon_threadsafe`` so graph / DB
        mutations only happen on the loop they belong to.
        """
        if self._tools_changed_cb is not None:
            return
        try:
            from providers.registry import ProviderRegistry
        except Exception:
            return
        try:
            registry = ProviderRegistry.get_instance()
        except Exception:
            return
        loop = self._loop

        def _on_tools_changed() -> None:
            if loop is None:
                return
            try:
                loop.call_soon_threadsafe(self._handle_tools_changed)
            except RuntimeError:
                # Loop is closed (happens during shutdown). Ignore — we're
                # about to be unsubscribed anyway.
                pass

        self._tools_changed_cb = _on_tools_changed
        try:
            registry.subscribe_tools_changed(_on_tools_changed)
        except Exception:
            log.exception("failed to subscribe to tools-changed for flow %s",
                          self.config.flow_id)
            self._tools_changed_cb = None

    def _unsubscribe_tools_changed(self) -> None:
        cb = self._tools_changed_cb
        if cb is None:
            return
        self._tools_changed_cb = None
        try:
            from providers.registry import ProviderRegistry
            registry = ProviderRegistry.get_instance()
            registry.unsubscribe_tools_changed(cb)
        except Exception:
            pass

    def _handle_tools_changed(self) -> None:
        """Reset any WAITING_FOR_TOOL equations whose tool is now available."""
        if self.graph is None or self._state != RunState.RUNNING:
            return
        try:
            from providers.registry import ProviderRegistry
            registry = ProviderRegistry.get_instance()
        except Exception:
            return
        reset_any = False
        for eq in self.graph.all_equations():
            if eq.status != EquationStatus.WAITING_FOR_TOOL:
                continue
            tool_id = eq.definition.get("tool_id") or eq.definition.get("tool")
            if not tool_id:
                continue
            try:
                if registry.get_tool(tool_id) is None:
                    continue
            except Exception:
                continue
            self._cancel_and_broadcast_pending_tasks(eq.key, reason="tool_available")
            eq.error = None
            eq.transition_to(EquationStatus.PENDING)
            self._persist_status(eq.key, EquationStatus.PENDING, error=None)
            reset_any = True
            log.info(
                "flow %s: tool %s now available — resetting %s to PENDING",
                self.config.flow_id, tool_id, eq.key,
            )
        if reset_any:
            self._wakeup.set()

    def _reset_stale_computing(self) -> None:
        """Reset COMPUTING equations that aren't backed by a live task.

        A COMPUTING row with no entry in ``self._in_flight`` was either
        never scheduled by this FlowRun instance (i.e. left behind by a
        previous process) or got orphaned somehow. Either way, it won't
        complete on its own — the scheduler only moves PENDING into
        COMPUTING, so we bounce it back.
        """
        to_reset: list[str] = []
        for eq in self.graph.all_equations():
            if eq.status != EquationStatus.COMPUTING:
                continue
            if eq.key in self._in_flight:
                continue
            to_reset.append(eq.key)
        for key in to_reset:
            eq = self.graph.get(key)
            eq.status = EquationStatus.PENDING
            eq.error = None
            self._persist_status(key, EquationStatus.PENDING)
            log.info(
                "flow %s: reset stale COMPUTING equation %s to PENDING",
                self.config.flow_id, key,
            )

    def recover_orphaned_work(self) -> None:
        """Best-effort recovery for durable/in-memory work drift.

        Backend restarts and dev-server reloads can leave persisted or
        in-memory equations in COMPUTING even though this FlowRun has no
        live evaluator task for them. The scheduler only picks PENDING work,
        so reset those rows before status reads or idle loop waits.
        """
        self._reset_stale_computing()

    async def stop(self) -> None:
        """Stop scheduling and end the loop. Awaits in-flight equations."""
        self._state = RunState.FINISHED
        self._wakeup.set()
        self._paused_event.set()
        self._unsubscribe_tools_changed()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._drain_in_flight()
        ephemeral_keys = [
            key
            for key in self.graph.output_keys
            if (
                self.graph.output_specs.get(self.graph.output_name_by_key.get(key, ""))
                or {}
            ).get("disposition")
            == "ephemeral"
        ]
        for key in ephemeral_keys:
            self._invalidate_equation(key, direct=True)
        if self.config.release_media_results is not None:
            await self.config.release_media_results([], True)
        self._stopped_event.set()

    async def wait_quiescent(self, timeout: Optional[float] = None) -> None:
        """Block until the scheduler is idle (no ready or in-flight work)."""
        deadline = None if timeout is None else asyncio.get_event_loop().time() + timeout
        while True:
            if self._is_quiescent():
                return
            remaining = None if deadline is None else max(0.0, deadline - asyncio.get_event_loop().time())
            if remaining == 0.0:
                raise asyncio.TimeoutError("wait_quiescent timed out")
            # Tick the wakeup event with a short sleep so progress signals
            # reach us.
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=min(remaining or 0.1, 0.1))
            except asyncio.TimeoutError:
                pass
            self._wakeup.clear()

    def _is_quiescent(self) -> bool:
        if self._in_flight:
            return False
        if self.graph.ready_equations():
            return False
        for eq in self.graph.all_equations():
            if eq.status == EquationStatus.COMPUTING:
                return False
        # A foreach wrapper whose input is ready but has not been
        # expanded still has work to do: `_try_expand_deferred` will
        # materialize its children next tick. Don't report quiescence
        # while that is pending — otherwise ``wait_quiescent`` returns
        # early and external observers (tests, HTTP) see the flow as
        # done before the children exist.
        for deferred in self.graph.all_deferred():
            if deferred.expanded:
                continue
            wrapper = self.graph.try_get(deferred.owner_key)
            if wrapper is None:
                continue
            if wrapper.status != EquationStatus.PENDING:
                if wrapper.status in _TERMINAL_DEFERRED_OWNER_STATUSES:
                    deferred.expanded = True
                continue
            input_eq = self.graph.try_get(deferred.input_equation_key)
            if input_eq is None:
                continue
            if input_eq.status == EquationStatus.COMPLETED:
                return False
            # Early-expansion candidate: upstream foreach has materialized
            # its iteration wrappers but hasn't finished. We can still
            # expand downstream now; the next tick will do it.
            if (
                deferred.kind == "foreach"
                and not deferred.early_blocked
                and input_eq.definition.get("control_kind") == "foreach"
                and getattr(input_eq, "_iteration_keys_cache", None) is not None
            ):
                return False
        return True

    # ------------------------------------------------------------------
    # Task resolution (HITL)

    def _hitl_completion_value(self, eq: Equation, raw_resolution: Any) -> Any:
        """The value an HITL equation exposes downstream when it completes.

        For every HITL type except ``approve`` this is the raw resolution:
        ``select`` picks a media id. ``approve`` is a pass-through gate
        — the DSL declares it returns the *asset*, not the yes/no decision —
        so on ``True`` we forward the upstream equation's resolved value.
        Without this, piping an approved node into a downstream ``tool()``
        leaks the boolean into tool inputs (e.g. ``input_images=[True, 7]``)
        and later queries blow up on type mismatches.

        Returns ``raw_resolution`` unchanged when the upstream isn't
        available yet (recovery paths); the caller's flow still completes
        the equation, and re-evaluation picks the asset up next time.
        """
        if eq.definition.get("hitl_type") == "approve" and raw_resolution is True:
            upstream_key = eq.dependencies[0] if eq.dependencies else None
            if upstream_key is not None:
                upstream = self.graph.try_get(upstream_key)
                if upstream is not None and upstream.result is not None:
                    return upstream.result
        return raw_resolution

    def has_pending_task(self, task_id: int) -> bool:
        return task_id in self._pending_hitl

    async def resolve_task(self, task_id: int, resolution: Any) -> None:
        """Mark an HITL task resolved. Idempotent.

        Writes to hitl_results unconditionally (so the decision is durable
        even if the equation was invalidated by a concurrent program edit);
        only completes the equation when it is still AWAITING_INPUT.
        """
        record = self._pending_hitl.pop(task_id, None)
        task_row = graph_db.get_task(self.config.state_db_path, task_id)
        # URL-media promotion is the only step that can fail with the
        # resolution already in hand — and when it does (e.g. a hitl.select
        # pick whose URL 403s on download), the failure is an equation-
        # execution failure, not a "rejected resolution." Route it through
        # the normal _finalize_failure path so the user sees a standard
        # FAILED equation with retry/skip/edit-flow affordances, instead
        # of bouncing a 400 back to the picker.
        try:
            resolution = await self._promote_hitl_resolution(task_row, resolution)
        except Exception as exc:  # noqa: BLE001 — pivot to error-task on any promotion failure
            from .evaluators import EvaluatorError
            if not isinstance(exc, EvaluatorError):
                raise
            equation_key = (
                record.equation_key if record else (task_row or {}).get("equation_key") or ""
            )
            eq = self.graph.try_get(equation_key) if equation_key else None
            if eq is not None:
                category = getattr(exc, "category", TOOL_ERROR) or TOOL_ERROR
                # _finalize_failure → _create_error_task already cancels the
                # awaiting HITL task and broadcasts both the cancellation and
                # the new error task, so we don't call _broadcast_task_resolved
                # here (would emit a misleading "resolved" event for a task
                # the runtime just superseded).
                self._finalize_failure(eq, str(exc), category=category)
                self._ensure_scheduler_active()
                self._wakeup.set()
                return
            # Fallback: no equation to mark failed (rare — task row missing
            # or graph mid-edit). Surface the error normally so the API
            # layer can decide what to do.
            raise
        graph_db.resolve_task(self.config.state_db_path, task_id, resolution)
        if record is None:
            # Task was already resolved, or equation was invalidated between
            # task creation and this resolution call (the idempotent-under-
            # concurrent-edit path). Still store HITL durably when we have
            # the inputs_hash from the row so re-evaluation can pick it up.
            #
            # After app/backend restart recovery, the task row can exist in
            # state.db while this new FlowRun has no in-memory PendingHitl
            # record for it. In that case, complete the hydrated AWAITING_INPUT
            # equation directly so downstream work continues without requiring
            # a manual restart.
            if task_row is not None and task_row.get("inputs_hash"):
                eq = self.graph.try_get(task_row["equation_key"])
                is_approve_reject = task_row.get("task_type") == "approve" and resolution is False
                if is_approve_reject:
                    if eq is not None and eq.status == EquationStatus.AWAITING_INPUT:
                        for root_key in self._approve_reject_regen_roots(eq):
                            self._invalidate_equation(root_key, direct=True)
                        eq.transition_to(EquationStatus.INVALIDATED)
                        eq.transition_to(EquationStatus.PENDING)
                        eq.result = None
                        self._persist_status(
                            eq.key,
                            EquationStatus.PENDING,
                            result=None,
                            mark_invalidated=True,
                        )
                else:
                    graph_db.insert_hitl_result(
                        self.config.state_db_path,
                        task_row["equation_key"],
                        task_row["inputs_hash"],
                        resolution,
                    )
                    if eq is not None and eq.status == EquationStatus.AWAITING_INPUT:
                        completion_value = self._hitl_completion_value(eq, resolution)
                        await self._complete_success(
                            eq,
                            result=completion_value,
                            media_ids=_extract_media_ids(completion_value),
                        )
            self._broadcast_task_resolved(task_id, task_row)
            self._ensure_scheduler_active()
            self._wakeup.set()
            return
        eq = self.graph.try_get(record.equation_key)
        if eq is None or eq.status != EquationStatus.AWAITING_INPUT:
            # Equation was invalidated while awaiting input. Still persist
            # the HITL result durably — the re-evaluation will pick it up
            # via the inputs_hash match, so no human work is lost.
            graph_db.insert_hitl_result(
                self.config.state_db_path,
                record.equation_key,
                record.inputs_hash,
                resolution,
            )
            self._broadcast_task_resolved(task_id, task_row)
            self._ensure_scheduler_active()
            self._wakeup.set()
            return

        # For hitl.approve, "reject" is invalidation of the upstream asset.
        # We deliberately do NOT store the rejection in hitl_results — the
        # rejection is the answer to this specific candidate, not a durable
        # decision. When the upstream recomputes and the approve equation
        # re-evaluates, it should surface a fresh task.
        if record.task_type == "approve" and resolution is False:
            for root_key in self._approve_reject_regen_roots(eq):
                self._invalidate_equation(root_key, direct=True)
            eq.transition_to(EquationStatus.INVALIDATED)
            eq.transition_to(EquationStatus.PENDING)
            eq.result = None
            self._persist_status(eq.key, EquationStatus.PENDING,
                result=None,
                mark_invalidated=True,
            )
        else:
            # Durable per-flow HITL result.
            graph_db.insert_hitl_result(
                self.config.state_db_path,
                eq.key,
                record.inputs_hash,
                resolution,
            )
            completion_value = self._hitl_completion_value(eq, resolution)
            await self._complete_success(
                eq,
                result=completion_value,
                media_ids=_extract_media_ids(completion_value),
            )

        self._broadcast_task_resolved(task_id, task_row)
        self._ensure_scheduler_active()
        self._wakeup.set()

    async def resolve_error_task(
        self,
        task_id: int,
        action: str,
        *,
        value: Any = None,
    ) -> None:
        """Handle a resolution on an error task (task_type='error').

        Actions:
            retry         — equation back to PENDING, same attempt, eval loop picks up
            skip          — only valid inside foreach; equation -> SKIPPED
            edit_flow   — no-op on the runtime; just mark task resolved
        """
        task_row = graph_db.get_task(self.config.state_db_path, task_id)
        if task_row is None:
            raise KeyError(f"no task with id {task_id}")
        task_type = task_row["task_type"]
        if task_type not in {"error", "waiting_for_tool"}:
            raise ValueError(
                f"resolve_error_task called on task {task_id} with task_type "
                f"{task_type!r}"
            )
        equation_key = task_row["equation_key"]
        eq = self.graph.try_get(equation_key)

        resolution_record = {"action": action, "value": value}
        if task_type == "waiting_for_tool" and action not in {"skip", "edit_flow"}:
            raise ValueError(
                f"unknown waiting-for-tool action {action!r}; expected skip | edit_flow"
            )

        if action == "retry":
            if eq is not None and eq.status == EquationStatus.FAILED:
                # Back to pending without bumping attempt — same inputs_hash.
                eq.transition_to(EquationStatus.PENDING)
                eq.error = None
                self._persist_status(eq.key, EquationStatus.PENDING,
                    error=None,
                )
                # Drop any lingering pending tasks on the equation. The task
                # being resolved below is one of them; resolving the row
                # through the main path emits a single resolve event, but
                # any siblings (e.g. stragglers from a race before dedup
                # landed) should evaporate too.
                self._cancel_and_broadcast_pending_tasks(
                    eq.key, reason="retrying",
                )
        elif action == "skip":
            if eq is None:
                raise KeyError(f"equation {equation_key!r} not in graph")
            if task_type == "waiting_for_tool":
                self._force_skip_equation(equation_key)
            else:
                if not _is_inside_foreach_iteration(equation_key):
                    raise ValueError(
                        f"cannot skip non-loop equation {equation_key!r}; "
                        f"skip is only valid for failures inside a foreach iteration"
                    )
                iteration_prefix = _iteration_prefix_for(equation_key) or ""
                iteration_wrapper_key = iteration_prefix.rstrip("/")
                # Collect every equation that lives inside this iteration's
                # sub-graph, plus the iteration wrapper itself. Siblings
                # (other iterations) are untouched by construction because their
                # keys share only the foreach-wrapper prefix, not the
                # iteration prefix.
                in_scope = {
                    k for k in self.graph.keys()
                    if k == iteration_wrapper_key or k.startswith(iteration_prefix)
                }
                for k in in_scope:
                    self._force_skip_equation(k)
        elif action == "edit_flow":
            # No-op on the runtime. The user opens chat and the agent will
            # modify the program; the graph-diff-and-recompute flow handles
            # the rest. We just resolve the task.
            pass
        else:
            raise ValueError(
                f"unknown error-task action {action!r}; expected "
                f"retry | skip | edit_flow"
            )

        graph_db.resolve_task(self.config.state_db_path, task_id, resolution_record)
        self._broadcast_task_resolved(task_id, task_row)
        self._ensure_scheduler_active()
        self._wakeup.set()

    def list_tasks(
        self,
        *,
        status: str = "pending",
        task_types: Optional[Iterable[str]] = None,
        include_downstream_count: bool = True,
    ) -> list[dict[str, Any]]:
        """List tasks joined with their equations and enriched with a
        freshly-computed downstream count when the graph is still in memory.
        """
        rows = graph_db.list_tasks(
            self.config.state_db_path, status=status, task_types=task_types,
        )
        if include_downstream_count:
            for row in rows:
                row["downstream_count"] = self._downstream_count(row["equation_key"])
        return rows

    def _downstream_count(self, equation_key: str) -> int:
        if self.graph is None:
            return 0
        return len(self.graph.descendants(equation_key))

    def _force_skip_equation(self, equation_key: str) -> None:
        """Mark an equation as SKIPPED, normalizing transient states first.

        SKIPPED is reachable only from PENDING or FAILED in the state
        machine. Transient statuses (COMPUTING, AWAITING_INPUT,
        WAITING_FOR_TOOL) go through INVALIDATED → PENDING first.
        COMPLETED iterations are left alone — skip semantics apply to work
        that was pending or failed; already-computed upstream results keep
        their value.
        """
        eq = self.graph.try_get(equation_key)
        if eq is None:
            return
        if eq.status in (EquationStatus.SKIPPED, EquationStatus.COMPLETED):
            return
        if eq.status in (
            EquationStatus.COMPUTING,
            EquationStatus.AWAITING_INPUT,
            EquationStatus.WAITING_FOR_TOOL,
        ):
            eq.status = EquationStatus.INVALIDATED
            eq.transition_to(EquationStatus.PENDING)
        if eq.status == EquationStatus.INVALIDATED:
            eq.transition_to(EquationStatus.PENDING)
        if eq.status in (EquationStatus.PENDING, EquationStatus.FAILED):
            eq.transition_to(EquationStatus.SKIPPED)
        eq.result = None
        eq.result_media_ids = []
        self._persist_status(eq.key,
            eq.status,
            result=None,
            result_media_ids=[],
        )
        self._cancel_and_broadcast_pending_tasks(eq.key, reason="skipped")

    # ------------------------------------------------------------------
    # Invalidation

    def invalidate(self, equation_key: str) -> int:
        """Direct invalidation: bumps attempt, cascades downstream.

        Returns the number of equations reset.
        """
        n = self._invalidate_equation(equation_key, direct=True)
        if n:
            self._ensure_scheduler_active()
        self._wakeup.set()
        return n

    def _ensure_scheduler_active(self) -> None:
        """Restart the scheduler if a previous loop task died.

        Invalidation and task resolution are both wakeup-style APIs. If the
        background scheduler crashed earlier, merely setting the event leaves
        reset equations pending forever. Keeping this synchronous lets the
        HTTP invalidation path self-heal without needing to await start().
        """
        if self._state == RunState.PAUSED:
            return
        if self._task is not None and not self._task.done():
            return
        self._state = RunState.RUNNING
        self._paused_event.set()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._start_loop_task()

    async def reselect_hitl(self, equation_key: str, new_resolution: Any) -> int:
        """Atomically replace a completed HITL-select result and cascade
        downstream invalidation.

        Avoids the invalidate→wait-for-task→resolve-task roundtrip so the
        user's click-a-different-image feels instantaneous in the UI.
        Returns the number of downstream equations reset.
        """
        eq = self.graph.try_get(equation_key)
        if eq is None:
            raise ValueError(f"unknown equation {equation_key!r}")
        if eq.equation_type != EquationType.HITL:
            raise ValueError(f"equation {equation_key!r} is not HITL")
        if eq.definition.get("hitl_type") != "select":
            raise ValueError(f"equation {equation_key!r} is not a select HITL")
        if eq.status != EquationStatus.COMPLETED:
            raise ValueError(
                f"equation {equation_key!r} is not completed "
                f"(status={eq.status.value})"
            )
        new_resolution = await self._promote_hitl_resolution(
            {
                "task_type": "select",
                "equation_key": equation_key,
            },
            new_resolution,
            eq=eq,
        )

        # Cascade-reset descendants first so stale downstream rows don't
        # briefly show completed after the new pick lands.
        descendants = self.graph.descendants(equation_key)
        invalidated_keys = {equation_key, *descendants}
        count = 0
        for dep_key in descendants:
            dep = self.graph.try_get(dep_key)
            if dep is None:
                continue
            self._reset_equation_to_pending(
                dep,
                bump_already_applied=True,
                invalidated_keys=invalidated_keys,
                direct_target_key=equation_key,
            )
            count += 1

        # Swap the stored result + broadcast the update.
        mids = _extract_media_ids(new_resolution)
        try:
            await self._finalize_flow_media_result(eq, mids)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Unable to retain selected media: {exc}") from exc
        eq.result = new_resolution
        eq.result_media_ids = mids
        self._persist_status(
            eq.key,
            EquationStatus.COMPLETED,
            result=new_resolution,
            result_media_ids=mids,
            mark_completed=True,
        )

        # Replace the hitl_results cache so a future invalidate→re-eval still
        # re-asks rather than restoring the old pick.
        if eq.inputs_hash:
            graph_db.insert_hitl_result(
                self.config.state_db_path, eq.key, eq.inputs_hash, new_resolution,
            )

        self._wakeup.set()
        return count

    async def _promote_hitl_resolution(
        self,
        task_row: Optional[dict[str, Any]],
        resolution: Any,
        *,
        eq: Optional[Equation] = None,
    ) -> Any:
        """Promote selected URL media to library media before storing HITL."""
        task_type = (task_row or {}).get("task_type")
        if task_type not in {"select", "approve"}:
            return resolution
        if isinstance(resolution, bool):
            return resolution
        equation_key = (task_row or {}).get("equation_key") or (eq.key if eq else "")
        if eq is None and equation_key:
            eq = self.graph.try_get(equation_key)
        phase_path = list(eq.phase_path) if eq is not None else []
        try:
            from .production_evaluators import promote_url_media_value
            return await promote_url_media_value(
                resolution,
                flow_id=self.config.flow_id,
                project_id=self.config.project_id,
                equation_key=equation_key,
                phase_path=phase_path,
            )
        except ImportError:
            return resolution

    def _invalidate_equation(self, equation_key: str, *, direct: bool) -> int:
        eq = self.graph.try_get(equation_key)
        if eq is None:
            return 0
        if direct:
            scoped_roots = self._approve_candidate_direct_regen_roots(eq.key)
            if scoped_roots:
                reset: set[str] = set()
                for root_key in scoped_roots:
                    self._invalidate_equation(root_key, direct=True)
                    reset.add(root_key)
                    reset.update(self.graph.descendants(root_key))
                return len(reset)
        if direct and eq.equation_type == EquationType.CONTROL and eq.definition.get("control_kind") in {"slot", "foreach_iteration"}:
            roots = self._iteration_regen_roots(eq.key)
            if roots:
                reset: set[str] = set()
                for root_key in roots:
                    self._invalidate_equation(root_key, direct=True)
                    reset.add(root_key)
                    reset.update(self.graph.descendants(root_key))
                return len(reset)
        # Gather downstream BEFORE we mutate so cascade is deterministic.
        descendants = self.graph.descendants(equation_key)
        invalidated_keys = {equation_key, *descendants}

        # Direct target gets attempt bumped.
        if direct and eq.status != EquationStatus.INVALIDATED:
            eq.attempt += 1
        self._reset_equation_to_pending(
            eq,
            bump_already_applied=True,
            invalidated_keys=invalidated_keys,
            direct_target_key=equation_key,
        )

        # LLM_BATCH invalidation: the cascade below will reset slot children
        # to PENDING, but we also need their attempts back at 1 so their
        # re-eval takes from the fresh batch result instead of doing
        # peer-aware solo-gen (which is the attempt>1 path). Solo-gen is
        # only correct when the user directly invalidates ONE slot.
        if direct and eq.equation_type == EquationType.LLM_BATCH:
            for child_key in self.graph.dependents_of(equation_key):
                child = self.graph.try_get(child_key)
                if child is not None and child.equation_type == EquationType.LLM_SLOT:
                    child.attempt = 1

        count = 1
        for dep_key in descendants:
            dep = self.graph.try_get(dep_key)
            if dep is None:
                continue
            self._reset_equation_to_pending(
                dep,
                bump_already_applied=True,
                invalidated_keys=invalidated_keys,
                direct_target_key=equation_key,
            )
            count += 1
        return count

    def _iteration_regen_roots(self, wrapper_key: str) -> list[str]:
        """Root equations inside an iteration/slot body.

        Invalidating an iteration wrapper directly should rerun the body, not
        just the wrapper that mirrors the body result. Body roots are child
        equations under the wrapper that do not depend on another equation in
        the same wrapper subtree.
        """
        prefix = f"{wrapper_key}/"
        child_keys = {
            key for key in self.graph.keys()
            if key.startswith(prefix)
        }
        roots: list[str] = []
        for key in sorted(child_keys):
            eq = self.graph.try_get(key)
            if eq is None:
                continue
            if any(dep in child_keys for dep in eq.dependencies):
                continue
            roots.append(key)
        return roots

    def _approve_reject_regen_roots(self, approve_eq: Equation) -> list[str]:
        """Return the slot-local roots that must rerun when approving rejects.

        The approve equation depends on the candidate asset. For a scoped
        generator like ``llm -> code -> tool -> approve``, rejecting the image
        must rerun the prompt LLM too. Walk upstream from the candidate while
        staying inside the same slot wrapper and invalidate the earliest
        slot-local producers.
        """
        slash = approve_eq.key.rfind("/")
        if slash < 0:
            return list(approve_eq.dependencies)
        slot_key = approve_eq.key[:slash]
        slot_prefix = f"{slot_key}/"
        roots: set[str] = set()

        def visit(key: str, seen: set[str]) -> None:
            if key in seen:
                return
            seen.add(key)
            eq = self.graph.try_get(key)
            if eq is None or not key.startswith(slot_prefix):
                roots.add(key)
                return
            local_deps = [
                dep for dep in eq.dependencies
                if dep.startswith(slot_prefix)
            ]
            if not local_deps:
                roots.add(key)
                return
            for dep in local_deps:
                visit(dep, seen)

        for dep_key in approve_eq.dependencies:
            visit(dep_key, set())
        return sorted(roots)

    def _approve_candidate_direct_regen_roots(self, equation_key: str) -> list[str]:
        """Expand direct invalidation of a visible approve candidate to its scope.

        UI surfaces often put the replace button on the generated media node
        because that is what the user sees. For ``hitl.approve`` slots, the
        semantic replacement unit is the whole generator body that feeds the
        slot's auto-injected approve equation. If that body is
        ``llm -> code -> tool -> approve``, invalidating only the visible
        tool keeps the old prompt. Redirect candidate invalidation to the same
        roots used by an explicit HITL reject.
        """
        slash = equation_key.rfind("/")
        if slash < 0:
            return []
        slot_key = equation_key[:slash]
        slot_prefix = f"{slot_key}/"
        approve_eq: Equation | None = None
        for key in self.graph.keys():
            if not key.startswith(slot_prefix):
                continue
            eq = self.graph.try_get(key)
            if (
                eq is not None
                and eq.equation_type == EquationType.HITL
                and eq.definition.get("hitl_type") == "approve"
                and equation_key in eq.dependencies
            ):
                approve_eq = eq
                break
        if approve_eq is None:
            return []
        roots = self._approve_reject_regen_roots(approve_eq)
        if not roots or roots == [equation_key]:
            return []
        return roots

    def _reset_deferred_subgraph(
        self,
        eq: Equation,
        *,
        invalidated_keys: set[str],
        direct_target_key: str | None,
    ) -> None:
        """Drop any materialized foreach subtree under ``eq``.

        Deferred expansions are stateful: once a wrapper expands, its
        ``DeferredExpansion.expanded`` flag suppresses future expansion.
        On invalidation that behavior is wrong for dynamic wrappers because
        upstream inputs may have changed. We must:

          1. remove the stale child equations from graph + state.db
          2. strip the wrapper's temporary child dependencies
          3. flip the deferred back to "not expanded" so it rebuilds

        Without this, nested foreach graphs keep reusing the old image/tool
        subgraph after an upstream list regenerates.
        """
        deferred = self.graph.deferred(eq.key)
        if deferred is None:
            return

        subtree_prefix = f"{eq.key}/"
        base_deps = [dep for dep in eq.dependencies if not dep.startswith(subtree_prefix)]
        needs_rebuild = (
            eq.key == direct_target_key
            or any(dep in invalidated_keys for dep in base_deps)
        )
        if not needs_rebuild:
            return

        subtree_keys = sorted(
            (k for k in self.graph.keys() if k.startswith(subtree_prefix)),
            key=lambda k: k.count("/"),
            reverse=True,
        )
        if subtree_keys:
            self._delete_dynamic_subgraph(subtree_keys)

        live_deps = [dep for dep in eq.dependencies if not dep.startswith(subtree_prefix)]
        if live_deps != eq.dependencies:
            self.graph.replace_dependencies(eq.key, live_deps)

        if hasattr(eq, "_iteration_keys_cache"):
            delattr(eq, "_iteration_keys_cache")

        deferred.expanded = False
        deferred.early_blocked = False

    def _delete_dynamic_subgraph(self, keys: list[str]) -> None:
        """Remove previously-expanded dynamic equations and any stale tasks."""
        if not keys:
            return

        self._schedule_media_release(keys)

        tasks_to_notify: list[dict[str, Any]] = []
        for key in keys:
            task = self._in_flight.pop(key, None)
            if task is not None:
                task.cancel()

            for task_id, rec in list(self._pending_hitl.items()):
                if rec.equation_key == key:
                    self._pending_hitl.pop(task_id, None)

            eq = self.graph.try_get(key)
            if (
                eq is not None
                and eq.equation_type == EquationType.HITL
                and eq.inputs_hash
            ):
                graph_db.delete_hitl_result(
                    self.config.state_db_path, key, eq.inputs_hash,
                )

            tasks_to_notify.extend(
                graph_db.list_pending_tasks_for_equation(
                    self.config.state_db_path, key,
                )
            )
            graph_db.cancel_pending_tasks_for_equation(
                self.config.state_db_path, key,
            )

        graph_db.delete_equations_by_keys(self.config.state_db_path, keys)

        for key in keys:
            self.graph.pop_deferred(key)
            self.graph.remove_equation(key)

        for task_row in tasks_to_notify:
            self._broadcast_task_resolved(
                int(task_row["id"]),
                task_row,
            )

    def _reset_equation_to_pending(
        self,
        eq: Equation,
        *,
        bump_already_applied: bool,
        invalidated_keys: set[str],
        direct_target_key: str | None,
    ) -> None:
        """Move `eq` to INVALIDATED -> PENDING, clear result, persist.

        Transient states (COMPUTING, AWAITING_INPUT) transition via
        INVALIDATED first to satisfy the state machine in graph.py.
        """
        if eq.result_media_ids:
            self._schedule_media_release([eq.key])
        old_status = eq.status
        if old_status == EquationStatus.COMPUTING:
            # The in-flight task will see the INVALIDATED state and discard
            # its result when it completes. Also cancel + clear the in-flight
            # slot now so a redo can schedule immediately instead of waiting
            # for the stale task to time out.
            eq.status = EquationStatus.INVALIDATED
            task = self._in_flight.pop(eq.key, None)
            if task is not None:
                task.cancel()
        elif old_status not in (
            EquationStatus.PENDING,
            EquationStatus.INVALIDATED,
        ):
            eq.transition_to(EquationStatus.INVALIDATED)

        eq.result = None
        eq.result_media_ids = []
        eq.execution_duration_ms = None
        eq.compute_duration_ms = None
        eq.error = None

        # If this was HITL awaiting input, drop the pending task record.
        for task_id, rec in list(self._pending_hitl.items()):
            if rec.equation_key == eq.key:
                self._pending_hitl.pop(task_id, None)

        # Cancel any still-pending task rows for this equation and notify
        # listeners. Without this, the DB row stays status='pending' and the
        # next HITL (after re-evaluation) renders alongside the stale one —
        # producing duplicate cards and an inflated pending count.
        cancelled_ids = graph_db.cancel_pending_tasks_for_equation(
            self.config.state_db_path, eq.key,
        )
        for tid in cancelled_ids:
            self._broadcast_task_resolved(
                tid,
                {"task_type": None, "equation_key": eq.key},
            )

        # HITL: drop the cached resolution so re-evaluation re-asks the user.
        # Without this, the re-eval path hits lookup_hitl_result by
        # (equation_key, inputs_hash) and silently re-applies the old pick —
        # the "Redo does nothing" bug.
        if eq.equation_type == EquationType.HITL and eq.inputs_hash:
            graph_db.delete_hitl_result(
                self.config.state_db_path, eq.key, eq.inputs_hash,
            )

        # Dynamic wrappers (foreach) need their old materialized
        # subtree removed before they can expand again with fresh upstream
        # values. Keep the wrapper row itself; drop only its generated
        # descendants and re-arm the deferred expansion.
        self._reset_deferred_subgraph(
            eq,
            invalidated_keys=invalidated_keys,
            direct_target_key=direct_target_key,
        )

        eq.transition_to(EquationStatus.PENDING)
        self._persist_status(eq.key,
            EquationStatus.PENDING,
            result=None,
            result_media_ids=[],
            execution_duration_ms=None,
            compute_duration_ms=None,
            error=None,
            completed_at=None,
            attempt=eq.attempt,
            dependencies=eq.dependencies,
            mark_invalidated=True,
        )
        if (
            eq.equation_type == EquationType.FLOW_INPUT
            and not eq.is_waiting_for_flow_input()
        ):
            if eq.definition.get("is_collection", True):
                values = eq.definition.get("values")
                eq.result = list(values) if values is not None else []
            else:
                eq.result = eq.definition.get("value")
            eq.result_media_ids = []
            eq.transition_to(EquationStatus.COMPLETED)
            self._persist_status(
                eq.key,
                EquationStatus.COMPLETED,
                result=eq.result,
                result_media_ids=[],
                mark_completed=True,
            )

    def _schedule_media_release(
        self,
        equation_keys: list[str],
        *,
        ephemeral_only: bool = False,
    ) -> None:
        callback = self.config.release_media_results
        if callback is None:
            return

        async def release() -> None:
            try:
                await callback(equation_keys, ephemeral_only)
            except Exception:  # noqa: BLE001
                log.exception(
                    "flow %s: failed to release media owners for %s",
                    self.config.flow_id,
                    equation_keys,
                )

        asyncio.create_task(release())

    # ------------------------------------------------------------------
    # Scheduler loop

    async def _run_loop(self) -> None:
        # Correlation scope for Stimma Cloud LLM requests: equation
        # evaluations (llm_call nodes etc.) run in tasks created inside this
        # loop and inherit the flow context + run id via contextvars.
        from llm_correlation import llm_correlation_context

        with llm_correlation_context("flow", run_id=self._correlation_run_id):
            await self._run_loop_inner()

    async def _run_loop_inner(self) -> None:
        try:
            while self._state in (RunState.RUNNING,):
                # Pause check: block here until resumed.
                await self._paused_event.wait()
                if self._state != RunState.RUNNING:
                    break

                self._reset_stale_computing()

                # Expand any deferred nodes whose inputs have resolved.
                expanded = self._try_expand_deferred()

                # Fire up to N ready equations.
                scheduled = await self._schedule_ready()

                if not expanded and not scheduled:
                    # Nothing to do right now — sleep on wakeup signal.
                    if self._is_quiescent():
                        # Truly nothing pending. Keep the loop alive so
                        # late events (task resolution, invalidation) can
                        # reactivate us.
                        try:
                            await asyncio.wait_for(self._wakeup.wait(), timeout=0.05)
                        except asyncio.TimeoutError:
                            pass
                        self._wakeup.clear()
                        if self._is_quiescent() and self._state == RunState.RUNNING:
                            # Short pause, otherwise we'd busy-loop.
                            await asyncio.sleep(0.01)
                    else:
                        try:
                            await asyncio.wait_for(self._wakeup.wait(), timeout=0.1)
                        except asyncio.TimeoutError:
                            pass
                        self._wakeup.clear()
        except Exception:
            log.exception("flow run loop crashed")
            raise

    async def _schedule_ready(self) -> int:
        ready = self.graph.ready_equations()
        # Keep cap: only schedule up to (concurrency - in_flight) this tick.
        available = self.config.concurrency - len(self._in_flight)
        if available <= 0:
            return 0

        scheduled = 0
        for eq in ready[:available]:
            if eq.key in self._in_flight:
                continue
            # Move to COMPUTING before handing off. Control equations
            # (wrappers with no evaluator) complete immediately.
            if eq.equation_type == EquationType.CONTROL or eq.equation_type == EquationType.FLOW_INPUT:
                await self._complete_control_equation(eq)
                scheduled += 1
                continue

            eq.transition_to(EquationStatus.COMPUTING)
            self._persist_status(eq.key, EquationStatus.COMPUTING
            )
            task = asyncio.create_task(
                self._evaluate_with_cap(eq),
                name=f"eval-{eq.key}",
            )
            self._in_flight[eq.key] = task
            scheduled += 1
        return scheduled

    async def _evaluate_with_cap(self, eq: Equation) -> None:
        current = asyncio.current_task()
        async with self._sem:
            try:
                await self._evaluate_equation(eq)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "flow %s: evaluator task crashed for %s",
                    self.config.flow_id,
                    eq.key,
                )
                if eq.status == EquationStatus.COMPUTING:
                    self._finalize_failure(
                        eq,
                        f"internal runtime error: {type(exc).__name__}: {exc}",
                        category=CODE_ERROR,
                    )
            finally:
                if self._in_flight.get(eq.key) is current:
                    self._in_flight.pop(eq.key, None)
                self._wakeup.set()

    async def _finalize_flow_media_result(
        self,
        eq: Equation,
        media_ids: list[int],
    ) -> None:
        if not media_ids:
            return
        output_name = self.graph.output_name_by_key.get(eq.key)
        if output_name is None:
            disposition = "internal"
        else:
            spec = self.graph.output_specs.get(output_name) or {}
            disposition = spec.get("disposition") or "independent"

        if self.config.finalize_media_results is not None:
            await self.config.finalize_media_results(
                eq.key, media_ids, disposition
            )

    async def _complete_success(
        self,
        eq: Equation,
        *,
        result: Any,
        media_ids: list[int],
        **persist_kwargs: Any,
    ) -> bool:
        """Finalize Media ownership before exposing an equation as completed."""
        if eq.status == EquationStatus.INVALIDATED:
            return False
        try:
            await self._finalize_flow_media_result(eq, media_ids)
        except Exception as exc:  # noqa: BLE001
            self._finalize_failure(eq, str(exc), category=TOOL_ERROR)
            return False
        eq.result = result
        eq.result_media_ids = list(media_ids)
        eq.transition_to(EquationStatus.COMPLETED)
        self._persist_status(
            eq.key,
            EquationStatus.COMPLETED,
            result=result,
            result_media_ids=list(media_ids),
            mark_completed=True,
            **persist_kwargs,
        )
        return True

    async def _evaluate_equation(self, eq: Equation) -> None:
        """Evaluate a single non-control equation. Handles store/HITL lookup."""
        try:
            resolved_inputs = self._resolve_dynamic_bindings(eq)
        except Exception as exc:
            self._finalize_failure(eq, str(exc), category=CODE_ERROR)
            return

        # Inputs hash (canonical JSON of resolved inputs). For HITL, include
        # the resolved instructions string per §4.
        canon_inputs = self._normalize_inputs_for_hash(eq, resolved_inputs)
        inputs_hash = inputs_hash_for_values(canon_inputs)
        eq.inputs_hash = inputs_hash

        # HITL path: check per-flow hitl_results first.
        if eq.equation_type == EquationType.HITL:
            if self.config.hitl_auto_resolve is not None:
                try:
                    resolution = self.config.hitl_auto_resolve(eq, resolved_inputs)
                    completion_value = self._hitl_completion_value(eq, resolution)
                except Exception as exc:
                    self._finalize_failure(eq, str(exc), category=CODE_ERROR)
                    return
                await self._complete_success(
                    eq,
                    result=completion_value,
                    media_ids=_extract_media_ids(completion_value),
                    inputs_hash=inputs_hash,
                )
                return
            existing = graph_db.lookup_hitl_result(
                self.config.state_db_path, eq.key, inputs_hash
            )
            if existing is None:
                # §I5 best-effort: try matching by inputs_hash alone.
                existing = graph_db.lookup_hitl_by_inputs_hash(
                    self.config.state_db_path, inputs_hash
                )
            if existing is not None:
                completion_value = self._hitl_completion_value(eq, existing)
                await self._complete_success(
                    eq,
                    result=completion_value,
                    media_ids=_extract_media_ids(completion_value),
                    inputs_hash=inputs_hash,
                )
                return
            # Miss: create a task row + mark awaiting_input.
            await self._create_hitl_task(eq, resolved_inputs, inputs_hash)
            return

        # Computational path: check global store.
        definition_hash = eq.definition.get("definition_hash")
        if definition_hash is None:
            self._finalize_failure(
                eq, "evaluator missing definition_hash", category=TOOL_ERROR,
            )
            return
        equation_type_str = eq.equation_type.value
        store_key = compute_store_key(
            equation_type_str, definition_hash, inputs_hash, eq.attempt,
        )
        hit = self.store.lookup(store_key)
        if hit is not None:
            cached = hit.get("result_small")
            # A None result in the store for a collection equation (code list[…])
            # means a previous run stored a bad value. Treat as a miss so the
            # equation re-evaluates rather than silently producing 0 items.
            is_list_output = (
                eq.equation_type == EquationType.CODE
                and eq.definition.get("output_type", "").startswith("list[")
            )
            if cached is None and is_list_output:
                hit = None
            # Durable global caching of Media identities aliases ownership and
            # provenance across flows. Persistent runtimes cache pure values,
            # but recompute Media-producing equations in their own context.
            if hit is not None and hit.get("result_media_ids") and self.config.finalize_media_results:
                hit = None
        if hit is not None:
            self.store.touch(store_key)
            eq.result = hit.get("result_small")
            eq.result_media_ids = list(hit.get("result_media_ids") or [])
            eq.execution_duration_ms = hit.get("execution_duration_ms")
            eq.compute_duration_ms = hit.get("compute_duration_ms")
            if eq.status == EquationStatus.INVALIDATED:
                return
            await self._complete_success(
                eq,
                result=eq.result,
                media_ids=list(eq.result_media_ids),
                execution_duration_ms=eq.execution_duration_ms,
                compute_duration_ms=eq.compute_duration_ms,
                inputs_hash=inputs_hash,
            )
            return

        # Dispatch to the registered evaluator, with retries.
        eval_started = perf_counter()
        seed = derive_seed(eq.key, eq.attempt)
        request = EvaluationRequest(
            equation_key=eq.key,
            equation_type=equation_type_str,
            attempt=eq.attempt,
            definition=eq.definition,
            resolved_inputs=resolved_inputs,
            seed=seed,
            flow_id=self.config.flow_id,
            project_id=self.config.project_id,
            phase_path=list(eq.phase_path),
        )

        result: Optional[EvaluationResult] = None
        last_exc: Optional[BaseException] = None
        category = TOOL_ERROR
        attempts_made = 0
        while True:
            if eq.status == EquationStatus.INVALIDATED:
                return
            try:
                evaluator = self.evaluators.resolve(
                    equation_type_str,
                    hitl_type=eq.definition.get("hitl_type"),
                )
                result = await evaluator(request)
                last_exc = None
                break
            except asyncio.CancelledError:
                # Invalidation cancels stale in-flight work so a fresh attempt
                # can start immediately. Treat that as discarded work, not a
                # failed equation.
                return
            except BaseException as exc:  # noqa: BLE001 — classify + retry
                last_exc = exc
                category = classify_exception(exc)
                budget = retry_budget(category)
                if attempts_made >= budget:
                    break
                backoff = self.config.retry_backoff_seconds * (2 ** attempts_made)
                attempts_made += 1
                if backoff > 0:
                    await asyncio.sleep(backoff)

        if last_exc is not None:
            if category == RESOURCE_ERROR:
                self._finalize_failure(eq, str(last_exc), category=category)
                log.warning(
                    "flow %s: resource exhaustion, pausing", self.config.flow_id
                )
                await self.pause()
                return
            self._finalize_failure(eq, str(last_exc), category=category)
            return

        assert result is not None
        # Success.
        if eq.status == EquationStatus.INVALIDATED:
            # Discard: user invalidated before we saved.
            return

        # Persist to store and per-flow DB.
        small_payload = result.value
        duration_ms = max(0, int((perf_counter() - eval_started) * 1000))
        compute_duration_ms = result.compute_duration_ms
        # media_ids are small — keep them in result_small too.
        size_bytes = _approx_size(small_payload)
        if not (result.media_ids and self.config.finalize_media_results):
            try:
                self.store.insert(
                    store_key,
                    equation_type_str,
                    result_small=small_payload,
                    result_media_ids=list(result.media_ids),
                    execution_duration_ms=duration_ms,
                    compute_duration_ms=compute_duration_ms,
                    size_bytes=size_bytes,
                )
            except Exception:
                log.exception("equation_store.insert failed for %s", eq.key)

        eq.execution_duration_ms = duration_ms
        eq.compute_duration_ms = compute_duration_ms
        await self._complete_success(
            eq,
            result=small_payload,
            media_ids=list(result.media_ids),
            execution_duration_ms=duration_ms,
            compute_duration_ms=compute_duration_ms,
            inputs_hash=inputs_hash,
        )

    def _finalize_failure(self, eq: Equation, message: str, *, category: str) -> None:
        if eq.status == EquationStatus.INVALIDATED:
            return
        if category == TOOL_UNAVAILABLE:
            self._park_waiting_for_tool(eq, message=message)
            return
        eq.error = f"[{category}] {message}"
        eq.transition_to(EquationStatus.FAILED)
        self._persist_status(eq.key,
            EquationStatus.FAILED,
            error=eq.error,
        )
        self._create_error_task(eq, category=category, message=message)

    def _park_waiting_for_tool(self, eq: Equation, *, message: str) -> None:
        """Move a tool_call equation into WAITING_FOR_TOOL and surface a
        non-error task for it. Resets when the tool's provider registers.
        """
        tool_id = eq.definition.get("tool_id") or eq.definition.get("tool") or ""
        eq.error = None
        eq.transition_to(EquationStatus.WAITING_FOR_TOOL)
        self._persist_status(eq.key,
            EquationStatus.WAITING_FOR_TOOL,
            error=None,
        )
        # Resolve any existing pending tasks for this equation (dedup: a
        # prior run's error task would otherwise sit forever in the global
        # panel alongside the new waiting task).
        self._cancel_and_broadcast_pending_tasks(eq.key, reason="superseded")
        payload: dict[str, Any] = {
            "tool_id": tool_id,
            "message": message,
            "phase_path": list(eq.phase_path),
            "equation_type": eq.equation_type.value,
            "attempt": eq.attempt,
            "available_actions": ["skip", "edit_flow"],
            "downstream_count": self._downstream_count(eq.key),
        }
        try:
            task_id = graph_db.insert_task(
                self.config.state_db_path,
                eq.key,
                "waiting_for_tool",
                message,
                payload,
            )
        except Exception:
            log.exception("failed to insert waiting_for_tool task for %s", eq.key)
            return
        self._broadcast_task_created(
            task_id=task_id,
            task_type="waiting_for_tool",
            instructions=message,
            equation_key=eq.key,
        )

    def _create_error_task(
        self,
        eq: Equation,
        *,
        category: str,
        message: str,
    ) -> None:
        """Surface a failed equation as a task in the task panel.

        Error tasks carry enough context for the user to decide:
          - error type and message
          - phase path
          - upstream chain (the dependency keys that fed this equation)
          - available actions (retry, skip if in a foreach, edit_flow)
        """
        # Replace any prior pending task on this equation. Without this, each
        # retry accumulates a fresh row and the flow shows the same error N
        # times — tasks represent current flow state, not history, so a new
        # error supersedes the previous one.
        self._cancel_and_broadcast_pending_tasks(eq.key, reason="superseded")
        in_loop = _is_inside_foreach_iteration(eq.key)
        payload: dict[str, Any] = {
            "error_type": category,
            "error_message": message,
            "phase_path": list(eq.phase_path),
            "equation_type": eq.equation_type.value,
            "attempt": eq.attempt,
            "upstream_chain": list(eq.dependencies),
            "available_actions": _error_actions_for(in_loop),
            "downstream_count": self._downstream_count(eq.key),
        }
        try:
            task_id = graph_db.insert_task(
                self.config.state_db_path,
                eq.key,
                "error",
                # Use the error message as the displayed "instructions" — the
                # frontend will render the error-card layout when task_type
                # is 'error'.
                message,
                payload,
            )
        except Exception:
            log.exception("failed to insert error task for %s", eq.key)
            return
        self._broadcast_task_created(
            task_id=task_id,
            task_type="error",
            instructions=message,
            equation_key=eq.key,
        )

    def _cancel_and_broadcast_pending_tasks(
        self, equation_key: str, *, reason: str,
    ) -> list[int]:
        """Cancel every pending task row on an equation and fire resolve events.

        Used anywhere the equation's state changes in a way that invalidates
        its current tasks — a superseding error, a retry, a user-initiated
        resolution, or the tool becoming available. Without this, tasks
        accumulate across retries and the per-flow pending-task count
        reports an inflated number plus duplicate rows.

        Returns the cancelled task ids.
        """
        cancelled_ids = graph_db.cancel_pending_tasks_for_equation(
            self.config.state_db_path, equation_key,
        )
        if not cancelled_ids:
            return []
        for tid in cancelled_ids:
            self._pending_hitl.pop(tid, None)
            self._broadcast_task_resolved(
                tid,
                {
                    "task_type": None,
                    "equation_key": equation_key,
                    "reason": reason,
                },
            )
        return cancelled_ids

    async def _create_hitl_task(
        self, eq: Equation, resolved_inputs: dict[str, Any], inputs_hash: str,
    ) -> None:
        hitl_type = eq.definition.get("hitl_type", "")
        instructions = eq.definition.get("instructions", "")
        payload = self._build_task_payload(eq, resolved_inputs)
        payload["downstream_count"] = self._downstream_count(eq.key)
        task_id = graph_db.insert_task(
            self.config.state_db_path,
            eq.key,
            hitl_type,
            instructions,
            payload,
        )
        self._pending_hitl[task_id] = PendingHitl(
            equation_key=eq.key,
            task_id=task_id,
            task_type=hitl_type,
            payload=payload,
            instructions=instructions,
            inputs_hash=inputs_hash,
        )
        eq.transition_to(EquationStatus.AWAITING_INPUT)
        self._persist_status(eq.key, EquationStatus.AWAITING_INPUT,
            inputs_hash=inputs_hash,
        )
        self._broadcast_task_created(
            task_id=task_id,
            task_type=hitl_type,
            instructions=instructions,
            equation_key=eq.key,
        )

    def _build_task_payload(self, eq: Equation, resolved_inputs: dict[str, Any]) -> dict[str, Any]:
        hitl_type = eq.definition.get("hitl_type", "")
        if hitl_type == "select":
            return {
                "candidates": resolved_inputs.get("candidates", []),
                "count": eq.definition.get("count", 1),
            }
        if hitl_type == "approve":
            return {"asset": resolved_inputs.get("asset")}
        return {}

    # ------------------------------------------------------------------
    # WebSocket broadcasts (best-effort; no-op when no broadcaster wired)

    def _broadcast_task_created(
        self,
        *,
        task_id: int,
        task_type: str,
        instructions: str,
        equation_key: str,
    ) -> None:
        self._fire_broadcast(
            "flow_task_created",
            {
                "flow_id": self.config.flow_id,
                "task_id": task_id,
                "task_type": task_type,
                "instructions": instructions,
                "equation_key": equation_key,
            },
        )

    def _broadcast_task_resolved(
        self, task_id: int, task_row: Optional[dict[str, Any]]
    ) -> None:
        payload = {
            "flow_id": self.config.flow_id,
            "task_id": task_id,
        }
        if task_row is not None:
            payload["task_type"] = task_row.get("task_type")
            payload["equation_key"] = task_row.get("equation_key")
        self._fire_broadcast("flow_task_resolved", payload)

    def _fire_broadcast(self, event: str, payload: dict[str, Any]) -> None:
        fn = self.config.broadcast
        if fn is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            loop.create_task(fn(event, payload))
        except Exception:  # pragma: no cover — best-effort
            log.exception("broadcast(%s) failed", event)

    def _broadcast_equation_updated(self, equation_key: str) -> None:
        """Fire flow_equation_updated for the current in-memory equation.

        Called from _persist_status after the state.db write so every
        persisted status transition produces a WS event. The payload follows
        FLOWS_TECH §WebSocket Events and includes enough state for the
        phase tree to rerender without a refetch.

        We also piggyback the root-phase status_summary so non-active
        surfaces (sidebar, flows landing, project overview) can derive an
        accurate Running / Done / Your Turn / Error label without having to
        open the flow first.
        """
        if self.config.broadcast is None:
            return
        eq = self.graph.try_get(equation_key) if self.graph is not None else None
        if eq is None:
            return
        from .summary import compute_root_summary_from_equations
        root_summary = (
            compute_root_summary_from_equations(self.graph.all_equations())
            if self.graph is not None
            else {}
        )
        self._fire_broadcast(
            "flow_equation_updated",
            {
                "flow_id": self.config.flow_id,
                "equation_key": equation_key,
                "equation_type": eq.equation_type.value,
                "status": eq.status.value,
                "phase_path": list(eq.phase_path),
                "attempt": eq.attempt,
                "result_media_ids": list(eq.result_media_ids),
                "execution_duration_ms": eq.execution_duration_ms,
                "compute_duration_ms": eq.compute_duration_ms,
                "error": eq.error,
                "root_status_summary": root_summary,
            },
        )

    def _persist_status(
        self,
        equation_key: str,
        status: EquationStatus,
        **kwargs: Any,
    ) -> None:
        """Write a status change to state.db and broadcast flow_equation_updated.

        Centralizes the graph_db write + WS emit so callers don't have to
        remember both. Every equation-status transition in the engine flows
        through here.
        """
        graph_db.update_equation_status(
            self.config.state_db_path, equation_key, status, **kwargs
        )
        self._broadcast_equation_updated(equation_key)

    # ------------------------------------------------------------------
    # Control-equation completion

    async def _complete_control_equation(self, eq: Equation) -> None:
        """Control equations (flow_input, literal_list, foreach wrapper,
        zip_nodes) have no evaluator. They complete with a
        derived value once their dependencies are completed.
        """
        kind = eq.definition.get("control_kind")
        try:
            if kind == "flow_input":
                # Scalar inputs carry a single "value"; list inputs carry
                # "values". is_collection disambiguates; absent means legacy
                # collection-only form.
                if eq.definition.get("is_collection", True):
                    stored_values = eq.definition.get("values")
                    # An optional collection input with no provided value
                    # completes as an empty list — the absence of the input
                    # is expressed as "no items", not as a blocker.
                    eq.result = list(stored_values) if stored_values is not None else []
                else:
                    eq.result = eq.definition.get("value")
            elif kind == "literal_list":
                eq.result = list(eq.definition.get("values", []))
            elif kind == "foreach" or kind == "approve":
                # hitl.approve and foreach both produce a list of per-iteration
                # results; the only difference (auto-injected approve task)
                # is invisible at result-collection time. count==1 approve
                # unwraps to scalar — the DSL surface returned a scalar
                # NodeRef and downstream consumers expect T, not list[T].
                results = self._collect_foreach_result(eq)
                if kind == "approve" and eq.definition.get("count") == 1:
                    eq.result = results[0] if results else None
                else:
                    eq.result = results
                eq.result_media_ids = self._collect_foreach_media_ids(eq)
            elif kind == "llm_gather":
                # Assemble the llm(n=N) list from the slot equations, in
                # slot order. Runs only once every slot dependency is
                # COMPLETED, so results are always present.
                batch_key = eq.definition["batch_key"]
                n = int(eq.definition.get("n") or 0)
                eq.result = [
                    self.graph.get(f"{batch_key}/slot:{i}").result
                    for i in range(n)
                ]
            elif kind == "zip_nodes":
                eq.result = self._collect_zip_result(eq)
                eq.result_media_ids = list(dict.fromkeys(
                    media_id
                    for dependency in eq.dependencies
                    for media_id in self.graph.get(dependency).result_media_ids
                ))
            elif kind == "foreach_iteration" or kind == "slot":
                # An iteration wrapper mirrors the last DSL call's result via
                # `_result_from`. If _result_from is absent, the
                # callback returned a plain value (already stored) or None.
                result_from = eq.definition.get("_result_from")
                if result_from is not None:
                    inner = self.graph.try_get(result_from)
                    if inner is None:
                        raise RuntimeError(
                            f"iteration wrapper {eq.key!r}: _result_from {result_from!r} missing"
                        )
                    eq.result = inner.result
                    eq.result_media_ids = list(inner.result_media_ids)
            else:
                eq.result = None
        except Exception as exc:
            self._finalize_failure(eq, f"control equation {kind!r}: {exc}", category=CODE_ERROR)
            return

        await self._complete_success(
            eq,
            result=eq.result,
            media_ids=list(eq.result_media_ids),
        )

    def _collect_foreach_media_ids(self, wrapper: Equation) -> list[int]:
        prefix = f"{wrapper.key}/"
        media_ids: list[int] = []
        for child_key in self.graph.keys():
            if not child_key.startswith(prefix):
                continue
            rest = child_key[len(prefix):]
            if "/" in rest:
                continue
            child = self.graph.get(child_key)
            if child.status == EquationStatus.COMPLETED:
                media_ids.extend(child.result_media_ids)
        return list(dict.fromkeys(media_ids))

    def _collect_foreach_result(self, wrapper: Equation) -> list[Any]:
        """For a completed foreach, gather results from child per-iteration wrappers.

        Skipped iterations (per FLOWS_TECH §Failure Isolation and §User
        Response to Failures: "The loop's output collection omits the
        skipped item.") are dropped from the output collection; the rest of
        the scheduler must only call this once all children are terminal.
        """
        out: list[Any] = []
        prefix = f"{wrapper.key}/"
        for child_key in self.graph.keys():
            if not child_key.startswith(prefix):
                continue
            # Only collect direct child wrappers (one `/` after prefix).
            rest = child_key[len(prefix):]
            if "/" in rest:
                continue
            child = self.graph.get(child_key)
            if child.status == EquationStatus.SKIPPED:
                continue
            if child.status != EquationStatus.COMPLETED:
                # All deps should be complete; this is a programming error.
                raise RuntimeError(
                    f"foreach wrapper {wrapper.key!r} has non-completed child {child_key!r}"
                )
            out.append(child.result)
        return out

    def _collect_zip_result(self, wrapper: Equation) -> list[Any]:
        sources = wrapper.definition.get("sources", [])
        resolved = [self.graph.get(s).result for s in sources]
        # Align by iteration key when all sources are dicts; otherwise fall
        # back to positional. For Phase 2 we store each foreach result as a
        # positional list (the per-iteration order is deterministic via
        # graph.keys()). Inner join on length.
        min_len = min(len(r) for r in resolved) if resolved else 0
        return [tuple(r[i] for r in resolved) for i in range(min_len)]

    # ------------------------------------------------------------------
    # Dynamic input resolution

    def _resolve_dynamic_bindings(self, eq: Equation) -> dict[str, Any]:
        """Walk the equation's `_dynamic` structure and resolve NodeRefs."""
        dynamic = eq.definition.get("_dynamic") or {}
        resolved: dict[str, Any] = {}

        # code() and info() always need their inputs dict populated —
        # even when every input is a resolved value (no NodeRefs), the
        # sandbox still needs those names bound. The DSL only adds
        # `_dynamic['inputs']` when at least one input is a NodeRef, so
        # we fall back to static_inputs alone in the all-resolved case.
        if eq.equation_type in (
            EquationType.CODE,
            EquationType.INFO,
            EquationType.CREATE_IMAGE,
            EquationType.CREATE_LAYOUT,
        ):
            dynamic_inputs = dynamic.get("inputs") or {}
            inputs_map = {
                k: self._resolve_value(v) for k, v in dynamic_inputs.items()
            }
            static_inputs = eq.definition.get("static_inputs") or {}
            resolved["inputs"] = {**static_inputs, **inputs_map}
            # info() cards surface upstream media as thumbnails. Collect media
            # ids from every NodeRef input's producing equation so the card
            # shows what the agent was looking at when it wrote the note.
            if eq.equation_type == EquationType.INFO:
                media_ids: list[int] = []
                seen: set[int] = set()
                for v in dynamic_inputs.values():
                    for ref in _walk_noderefs(v):
                        upstream = self.graph.try_get(ref.equation_key)
                        if upstream is None:
                            continue
                        for mid in upstream.result_media_ids or []:
                            if mid in seen:
                                continue
                            seen.add(mid)
                            media_ids.append(mid)
                resolved["__upstream_media_ids"] = media_ids
            return resolved

        for k, v in dynamic.items():
            resolved[k] = self._resolve_value(v)
        return resolved

    def _resolve_value(self, value: Any) -> Any:
        if isinstance(value, NodeRef):
            eq = self.graph.try_get(value.equation_key)
            if eq is None:
                raise RuntimeError(f"unknown upstream equation {value.equation_key!r}")
            if eq.status != EquationStatus.COMPLETED:
                raise RuntimeError(
                    f"upstream equation {value.equation_key!r} is {eq.status.value}, not completed"
                )
            return eq.result
        if isinstance(value, list):
            return [self._resolve_value(x) for x in value]
        if isinstance(value, tuple):
            return tuple(self._resolve_value(x) for x in value)
        if isinstance(value, dict):
            return {k: self._resolve_value(v) for k, v in value.items()}
        return value

    def _normalize_inputs_for_hash(
        self, eq: Equation, resolved: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce a hash-stable dict of inputs.

        For HITL we also embed the resolved instructions string (§4).
        For stochastic equation types we fold in the per-equation seed so
        foreach iterations with identical resolved inputs get distinct
        store keys (otherwise they all alias to iteration 0's cached
        result and the tool never runs with their distinct seeds).
        """
        hashable = dict(resolved)
        if eq.equation_type == EquationType.HITL:
            hashable["__instructions__"] = eq.definition.get("instructions", "")
        if eq.equation_type in _SEED_KEYED_EQUATION_TYPES:
            hashable["__seed__"] = derive_seed(eq.key, eq.attempt)
        return hashable

    # ------------------------------------------------------------------
    # Deferred-expansion (foreach) materialization

    def _try_expand_deferred(self) -> bool:
        expanded_any = False
        for deferred in self.graph.all_deferred():
            if deferred.expanded:
                continue
            wrapper = self.graph.try_get(deferred.owner_key)
            if wrapper is None:
                continue
            if wrapper.status != EquationStatus.PENDING:
                if wrapper.status in _TERMINAL_DEFERRED_OWNER_STATUSES:
                    deferred.expanded = True
                continue
            input_eq = self.graph.try_get(deferred.input_equation_key)
            if input_eq is None:
                continue

            # Two triggers for foreach expansion:
            #   "early"    — input is itself a foreach whose iteration wrappers
            #                exist (completed or in-flight). Downstream items
            #                become NodeRefs at upstream iteration wrappers,
            #                preserving the per-iteration provenance edge so
            #                the viz can draw upstream→downstream and the
            #                store key captures the specific upstream iteration.
            #   "resolved" — input has COMPLETED and its result list is
            #                available as bare values. Used when early mode
            #                doesn't apply (upstream isn't a foreach, probe
            #                detected build-time item access, etc.).
            #
            # Early is preferred whenever available: resolving-first would
            # strip NodeRef identity from each item, leaving downstream tool
            # calls with ``dependencies=[]`` even though they semantically
            # depend on the corresponding upstream iteration. The viz then
            # shows downstream nodes with no incoming edges.
            mode: Optional[str] = None
            if (
                deferred.kind == "foreach"
                and not deferred.early_blocked
                and (
                    input_eq.definition.get("control_kind")
                    in ("foreach", "approve", "llm_gather")
                    or input_eq.equation_type == EquationType.LLM_BATCH
                )
                and getattr(input_eq, "_iteration_keys_cache", None) is not None
            ):
                mode = "early"
            elif input_eq.status == EquationStatus.COMPLETED:
                mode = "resolved"
            if mode is None:
                continue

            try:
                if deferred.kind not in ("foreach", "approve"):
                    raise RuntimeError(f"unknown deferred kind: {deferred.kind!r}")
                self._expand_foreach(deferred, input_eq, mode=mode)
                deferred.expanded = True
                expanded_any = True
            except _EarlyExpansionUnsupported:
                # Callback inspected the item at build time; wait for the
                # upstream to fully COMPLETE before materializing children.
                deferred.early_blocked = True
                continue
            except Exception as exc:
                log.exception("deferred expansion failed for %s", deferred.owner_key)
                self._finalize_failure(wrapper, f"expansion failed: {exc}", category=CODE_ERROR)
                deferred.expanded = True  # don't retry
        return expanded_any

    def _expand_foreach(
        self,
        deferred: DeferredExpansion,
        input_eq: Equation,
        *,
        mode: str = "resolved",
    ) -> None:
        """Materialize a per-iteration sub-graph for a foreach wrapper.

        Thin wrapper over :mod:`flow_runtime.foreach_expansion`. The pure
        graph-shaping work lives there so the loader can call it for
        eager build-time expansion when iteration counts are statically
        knowable. Here we wire in the scheduler's persistence + failure
        hooks so per-row state.db writes and error-task creation continue
        to work the way the engine has always done them.
        """
        items, iter_keys = foreach_expansion.resolve_items_and_keys(
            self.graph, deferred, input_eq, mode=mode,
        )
        foreach_expansion.expand_foreach(
            self.graph,
            deferred,
            items=items,
            iter_keys=iter_keys,
            persistor=self._build_expansion_persistor(),
        )

    def _build_expansion_persistor(self) -> foreach_expansion.ExpansionPersistor:
        """Wire scheduler-side persistence into the expansion module."""

        def _bulk_upsert_new(equations: list[Equation]) -> None:
            graph_db.upsert_equations(self.config.state_db_path, equations)

        def _persist_wrapper_update(eq: Equation) -> None:
            kwargs: dict[str, Any] = {
                "dependencies": list(eq.dependencies),
                "definition": dict(eq.definition),
            }
            if eq.status == EquationStatus.COMPLETED:
                kwargs["result"] = eq.result
                kwargs["mark_completed"] = True
            self._persist_status(eq.key, eq.status, **kwargs)

        def _finalize_failure(eq: Equation, message: str) -> None:
            self._finalize_failure(eq, message, category=CODE_ERROR)

        return foreach_expansion.ExpansionPersistor(
            bulk_upsert_new=_bulk_upsert_new,
            persist_wrapper_update=_persist_wrapper_update,
            finalize_failure=_finalize_failure,
        )

    # ------------------------------------------------------------------
    # Helpers

    async def _drain_in_flight(self) -> None:
        if not self._in_flight:
            return
        await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
        self._in_flight.clear()


# ----------------------------------------------------------------------
# Helpers (module-level)


def _extract_media_ids(value: Any) -> list[int]:
    """Best-effort extraction of media_ids from a HITL-select resolution.

    select results take a few shapes depending on how candidates were shaped
    upstream: a bare int (one pick), a list of ints (count>1), or dicts
    carrying a media_id field. Anything else yields an empty list so
    result_media_ids stays consistent with what the frontend can render.
    """
    out: list[int] = []
    if isinstance(value, int):
        out.append(value)
    elif isinstance(value, dict):
        mid = value.get("media_id")
        if isinstance(mid, int):
            out.append(mid)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, dict):
                mid = item.get("media_id")
                if isinstance(mid, int):
                    out.append(mid)
    return out


def _approx_size(payload: Any) -> int:
    if payload is None:
        return 0
    try:
        import json
        return len(json.dumps(payload, default=str).encode("utf-8"))
    except Exception:
        return 0


_ERROR_ACTIONS_IN_LOOP = ["retry", "skip", "edit_flow"]
_ERROR_ACTIONS_NOT_IN_LOOP = ["retry", "edit_flow"]


def _error_actions_for(in_loop: bool) -> list[str]:
    return list(_ERROR_ACTIONS_IN_LOOP if in_loop else _ERROR_ACTIONS_NOT_IN_LOOP)


def _is_inside_foreach_iteration(equation_key: str) -> bool:
    """True when the key has at least one `fn:iter_key` segment, meaning it
    sits inside (or is) a foreach-iteration wrapper. The FLOWS_EQUATION_KEYS
    §3 format uses `:` to separate a function name from its iteration key,
    while `/` separates nesting levels.

    LLM slots use `slot:N`; they are not foreach iterations and should not
    expose the foreach-only "skip" action.
    """
    if not equation_key:
        return False
    for segment in equation_key.split("/"):
        if _is_foreach_iteration_segment(segment):
            return True
    return False


def _is_foreach_iteration_segment(segment: str) -> bool:
    if ":" not in segment:
        return False
    if segment.startswith("slot:"):
        return False
    return True


def _iteration_prefix_for(equation_key: str) -> Optional[str]:
    """Return the longest ancestor key prefix that ends at a foreach-iteration
    boundary (a segment containing `:`). Used to identify the sub-graph that
    belongs to one iteration so 'skip' cancels only within it.
    """
    parts = equation_key.split("/")
    # Walk from the outside in; the first segment is the flow-function
    # wrapper (no `:`), the next segments may include foreach iteration
    # wrappers like `fn:iter`. The innermost iteration scope is the longest
    # prefix ending in such a segment.
    prefix: Optional[str] = None
    acc: list[str] = []
    for p in parts:
        acc.append(p)
        if _is_foreach_iteration_segment(p):
            prefix = "/".join(acc)
    return prefix + "/" if prefix else None

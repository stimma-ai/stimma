"""Production lifecycle helpers for FlowRuntime instances.

Phase 4 closed the HITL / task API but left runtime creation implicit —
tests construct `FlowRuntime` directly, and nothing in the production
HTTP layer spins one up. Phase 5's UI needs start / pause / resume /
invalidate, so this module gives the routes a single entry point to:

  - lazily instantiate a FlowRuntime for a flow_id
  - wire `ws_manager.broadcast` as the runtime's event sink
  - register / unregister with `flow_registry`
  - tear the runtime down when stopping

The registry already caches the runtime per flow_id (so task resolution
can find the active scheduler). We layer lifecycle on top of it.

Evaluators come from ``flow_runtime.production_evaluators`` — the single
wiring point for the generation-queue / LLM / code-sandbox paths. Tests
still construct ``FlowRuntime`` directly with stub evaluators, so that
seam is preserved.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select, update

import flow_registry
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import Flow
from database_registry import get_database_registry
from flow_dsl.errors import ProgramLoadError
from flow_runtime import (
    DryRunReport,
    FlowRuntime,
    dry_run_flow,
    get_equation_store,
    get_flow_program_path,
    get_flow_state_db_path,
    graph_db,
)
from flow_runtime.production_evaluators import build_production_registry
from utils.websocket import ws_manager


log = get_logger(__name__)


# Transient cache of the most recent program-load failure per flow. Populated
# by apply_program_edit when a rebuild raises ProgramLoadError, consumed by
# routes/flows.py::get_phase_tree so the error surfaces on plain GETs (not
# just on the immediate flow_updated broadcast). Cleared on any successful
# build. In-memory is fine — the error reconstructs deterministically from the
# program file, so a backend restart just needs the next edit or GET to re-raise.
_last_load_errors: dict[tuple[str, int], dict[str, Any]] = {}


def _profile_flow_key(flow_id: int) -> tuple[str, int]:
    return (get_current_profile(), flow_id)


def get_cached_load_error(flow_id: int) -> Optional[dict[str, Any]]:
    """Return the last cached program-load error for this flow, if any."""
    return _last_load_errors.get(_profile_flow_key(flow_id))


def clear_cached_load_error(flow_id: int) -> None:
    _last_load_errors.pop(_profile_flow_key(flow_id), None)


def _flow_inputs(flow: Flow) -> dict[str, Any]:
    if not flow.inputs:
        return {}
    try:
        parsed = json.loads(flow.inputs)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _apply_task_count_delta(flow_id: int, delta: int) -> Optional[int]:
    """Apply a signed delta to flows.pending_task_count atomically.

    Runs in whatever profile context the broadcast was fired under (the
    engine is started from a profile-scoped request, and contextvars
    propagate through loop.create_task). Returns the new count, or None
    when we couldn't resolve a DB session.

    Clamps at zero so an out-of-order resolved event can't push the
    counter negative if the corresponding created event hasn't committed
    yet. The reconciliation pass will correct any drift regardless.
    """
    try:
        profile_id = get_current_profile()
        registry = get_database_registry()
        db = registry.get_database(profile_id)
    except Exception:  # noqa: BLE001
        log.debug("task count delta skipped; no DB context", flow_id=flow_id)
        return None

    async with db.async_session_maker() as session:
        # UPDATE with arithmetic keeps this race-free across concurrent
        # increments. The clamp is applied after-the-fact via a second
        # read because SQLite lacks a portable GREATEST on UPDATE ... SET.
        await session.execute(
            update(Flow)
            .where(Flow.id == flow_id)
            .values(pending_task_count=Flow.pending_task_count + delta)
        )
        if delta < 0:
            # Clamp any negative value back to zero in the same tx.
            await session.execute(
                update(Flow)
                .where(Flow.id == flow_id, Flow.pending_task_count < 0)
                .values(pending_task_count=0)
            )
        await session.commit()
        result = await session.execute(
            select(Flow.pending_task_count).where(Flow.id == flow_id)
        )
        return result.scalar_one_or_none()


async def _broadcast(event: str, payload: dict[str, Any]) -> None:
    # Maintain the denormalized counter before broadcasting so listeners
    # that refetch on the event see the updated number.
    flow_id = payload.get("flow_id") if isinstance(payload, dict) else None
    if isinstance(flow_id, int):
        if event == "flow_task_created":
            new_count = await _apply_task_count_delta(flow_id, +1)
            if new_count is not None:
                payload["pending_task_count"] = new_count
        elif event == "flow_task_resolved":
            new_count = await _apply_task_count_delta(flow_id, -1)
            if new_count is not None:
                payload["pending_task_count"] = new_count
    # Telemetry tap: flow run outcomes + HITL resolution latency derive
    # from the same broadcast stream every runtime event flows through.
    try:
        import flow_telemetry
        flow_telemetry.on_runtime_broadcast(event, payload)
    except Exception:  # noqa: BLE001 — telemetry never affects the app
        pass
    await ws_manager.broadcast(event, payload)


async def reconcile_pending_task_counts(session) -> dict[int, int]:
    """Recompute pending_task_count for every non-deleted flow.

    Reads each flow's per-flow state.db (the authoritative source of
    tasks) and overwrites the denormalized column on the main DB. Called
    at backend startup so any drift from missed WebSocket events — e.g.,
    an ungraceful shutdown between task creation and event broadcast — is
    corrected before the UI consults the counter.

    Returns a map of {flow_id: reconciled_count} for logging.
    """
    result = await session.execute(
        select(Flow).where(Flow.deleted_at.is_(None))
    )
    reconciled: dict[int, int] = {}
    for flow in result.scalars().all():
        db_path = get_flow_state_db_path(flow.id)
        if not db_path.exists():
            count = 0
        else:
            try:
                rows = graph_db.list_tasks(db_path, status="pending")
                count = len(rows)
            except Exception:  # noqa: BLE001 — never let one bad DB block startup
                log.exception("reconcile: failed to read state.db", flow_id=flow.id)
                continue
        if (flow.pending_task_count or 0) != count:
            await session.execute(
                update(Flow).where(Flow.id == flow.id).values(pending_task_count=count)
            )
        reconciled[flow.id] = count
    await session.commit()
    return reconciled


async def recover_running_flows(session) -> list[int]:
    """Recreate + restart runtimes for flows marked running in the DB.

    Backend restart clears the in-memory flow_registry, but the main DB still
    records which flows were running. Rebuild those runtimes and re-enter the
    scheduler loop so interrupted work resumes without a manual pause/resume.
    Returns the recovered flow ids for logging.
    """
    result = await session.execute(
        select(Flow).where(
            Flow.deleted_at.is_(None),
            Flow.execution_state == "running",
        )
    )
    recovered: list[int] = []
    for flow in result.scalars().all():
        try:
            runtime = get_or_create_runtime(flow)
            await runtime.start()
            recovered.append(flow.id)
            try:
                import flow_telemetry
                flow_telemetry.note_started(flow.id)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 — startup should keep going
            log.exception("failed to recover running flow %s", flow.id)
    return recovered


def _build_runtime(flow: Flow) -> FlowRuntime:
    """Construct a FlowRuntime for a flow row, wired to ws_manager."""
    program_path = get_flow_program_path(flow.id)
    state_db_path = get_flow_state_db_path(flow.id)
    return FlowRuntime(
        flow.id,
        state_db_path,
        program_path=program_path,
        inputs=_flow_inputs(flow),
        evaluators=build_production_registry(),
        store=get_equation_store(),
        broadcast=_broadcast,
        project_id=flow.project_id,
        persist_media_results=True,
    )


def get_or_create_runtime(flow: Flow) -> FlowRuntime:
    """Return the active runtime for this flow, creating one if needed.

    The returned runtime always has its initial graph built so callers can
    inspect phases/equations without starting the scheduler. Graph-build
    errors surface as HTTP 400 with the DSL error's classification.

    If a runtime is already registered but the flow's ``inputs`` have
    changed since the graph was built (common flow: the agent writes
    program.py before the user fills the form, so the first graph was built
    with placeholder Nones), refresh the runtime's inputs and diff-rebuild
    via ``try_reload_program`` so the FLOW_INPUT equations complete with
    the real values. Without this, a ``code()`` block reading ``num_poses``
    sees ``None`` and the user gets an opaque TypeError.
    """
    current_inputs = _flow_inputs(flow)
    runtime = flow_registry.get_runtime(flow.id)
    if runtime is not None:
        if runtime.inputs != current_inputs:
            runtime.inputs = dict(current_inputs)
            try:
                runtime.try_reload_program()
            except Exception:  # noqa: BLE001 — best-effort; keep the runtime
                log.exception("input-change rebuild failed for flow %s", flow.id)
        return runtime
    runtime = _build_runtime(flow)
    try:
        runtime.build_initial_graph()
    except Exception as exc:  # noqa: BLE001 — surface as 400 with context
        log.exception("failed to build graph for flow %s", flow.id)
        raise HTTPException(
            status_code=400,
            detail=f"failed to load flow program: {exc}",
        ) from exc
    flow_registry.register(flow.id, runtime)
    # A successful build supersedes any stale error from an earlier
    # write-hook attempt that couldn't build (e.g. before inputs were set).
    _last_load_errors.pop(_profile_flow_key(flow.id), None)
    return runtime


async def apply_program_edit(
    session, flow_id: int, *, auto_start: bool = False,
) -> Optional[dict[str, Any]]:
    """Sync the compiled graph after an external writer (the agent's
    ``write_file`` / ``edit_file`` tools) modifies ``program.py`` for this flow.

    Without this step the agent's edits stay on disk until the user hits
    Start, because ``GET /flows/{id}/phases`` reads from ``state.db``
    which is only populated at graph-build time. That produces the
    "flow says it was created but the phase tree is empty" UX bug.

    Steps:
      1. Rehash ``program.py`` and persist ``Flow.program_hash``.
      2. If a runtime is already registered (user started the flow
         earlier), call ``try_reload_program`` so the live graph diffs
         against the new program; it broadcasts its own
         ``flow_updated`` + ``flow_phase_updated`` events.
      3. Otherwise build an initial graph and register it, so the phase
         tree endpoint has equations to return.
      4. Broadcast a final ``flow_updated`` carrying the refreshed
         Flow row (with the new ``program_hash``) so clients whose
         handlers key off ``program_hash`` refresh the tree.

    Load errors are captured and surfaced via ``flow_updated`` so the
    frontend can render them inline rather than silently showing an
    empty tree.
    """
    program_path = get_flow_program_path(flow_id)
    if not program_path.exists():
        return

    result = await session.execute(
        select(Flow).where(Flow.id == flow_id, Flow.deleted_at.is_(None))
    )
    flow = result.scalar_one_or_none()
    if flow is None:
        return

    try:
        program_bytes = program_path.read_bytes()
    except OSError:
        log.exception("apply_program_edit: could not read program.py", flow_id=flow_id)
        return

    new_hash = hashlib.sha256(program_bytes).hexdigest()
    if flow.program_hash != new_hash:
        flow.program_hash = new_hash
        flow.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(flow)

    load_error: Optional[dict[str, Any]] = None
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None:
        try:
            runtime = _build_runtime(flow)
            runtime.build_initial_graph()
            flow_registry.register(flow_id, runtime)
        except ProgramLoadError as exc:
            load_error = {
                "category": exc.category,
                "message": str(exc),
                "suggestion": exc.suggestion,
                "program_traceback": exc.program_traceback or None,
            }
        except Exception as exc:  # noqa: BLE001 — surface as a soft error
            log.exception("apply_program_edit: build_initial_graph failed", flow_id=flow_id)
            load_error = {"category": "build_error", "message": str(exc), "suggestion": None}
    else:
        # Refresh runtime.inputs before the diff-rebuild so changed input
        # values propagate into the new graph's FLOW_INPUT equations.
        runtime.inputs = dict(_flow_inputs(flow))
        _, err = runtime.try_reload_program()
        if err is not None:
            load_error = {
                "category": err.category,
                "message": str(err),
                "suggestion": err.suggestion,
                "program_traceback": err.program_traceback or None,
            }

    # Mirror the program's @flow(inputs=..., outputs=...) declarations into
    # Flow.input_schema / Flow.output_schema so the UI stays in sync with
    # program.py. program.py is the single source of truth; the DB columns
    # are denormalized copies the frontend reads. Run this before the dry-run
    # preflight so even a flow with deferred-callback bugs still has its
    # input/output schema reflected in the UI.
    if load_error is None and runtime is not None and runtime.graph is not None:
        await _sync_schemas_from_graph(session, flow, runtime.graph)

    # Preflight dry-run after a successful build. The graph builder only
    # exercises eagerly-bound code; deferred callbacks inside foreach /
    # hitl.approve (and tool() schema mismatches inside them) don't surface
    # until evaluation. Running dry-run here means the agent's edit cycle
    # gets the same structural errors the user would otherwise see only
    # after clicking Start. Best-effort: if dry-run itself crashes, log
    # and let the build pass — never block an edit on preflight infra.
    if load_error is None and runtime is not None and runtime.graph is not None:
        try:
            report = await dry_run_flow(
                flow_id=flow_id,
                program_path=program_path,
                inputs=_flow_inputs(flow),
                project_id=flow.project_id,
            )
            dry_run_error = _dry_run_load_error(report)
            if dry_run_error is not None:
                load_error = dry_run_error
        except Exception:  # noqa: BLE001 — preflight must never block edits
            log.exception(
                "apply_program_edit: dry-run preflight crashed",
                extra={"flow_id": flow_id},
            )

    # Cache/clear the load_error so a subsequent plain GET /phases (e.g. after
    # a browser reload with no websocket event in hand) still surfaces it.
    # Done after dry-run so a preflight failure participates in the cache.
    if load_error is not None:
        _last_load_errors[_profile_flow_key(flow_id)] = load_error
    else:
        _last_load_errors.pop(_profile_flow_key(flow_id), None)

    # Auto-start the scheduler after a successful agent-authored edit. Flows
    # should run by default — requiring a manual "play" click every time the
    # agent ships a program is a papercut, and a flow that builds but sits
    # idle is confusing. Respect an explicit "paused" state (user paused on
    # purpose) and don't stomp on a runtime that's already running.
    # Gated by `auto_start` so manual reparse doesn't surprise the user.
    if (
        auto_start
        and load_error is None
        and runtime is not None
        and runtime.graph is not None
        and flow.execution_state == "idle"
    ):
        try:
            await runtime.start()
            flow.execution_state = "running"
            flow.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(flow)
            try:
                import flow_telemetry
                from object_hash import salted_hash
                from telemetry import get_telemetry_client
                flow_telemetry.note_started(flow_id)
                get_telemetry_client().track("flow_started", {
                    "flowHash": salted_hash(f"flow:{flow_id}"),
                    "dryRun": False,
                }, category="flow")
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001 — best-effort auto-start
            log.exception("auto-start after program edit failed", extra={"flow_id": flow_id})

    flow_payload = flow.to_dict()
    # Surface the load_error flag on the flow blob so the sidebar / flows
    # landing's status pill flips to Error without having to open the flow
    # to hydrate the phase tree.
    flow_payload["has_load_error"] = load_error is not None
    payload: dict[str, Any] = {"flow": flow_payload, "flow_id": flow_id}
    if load_error is not None:
        payload["load_error"] = load_error
    await ws_manager.broadcast("flow_updated", payload)
    return load_error


def _dry_run_load_error(report: DryRunReport) -> Optional[dict[str, Any]]:
    """Translate a DryRunReport into the load_error dict shape, or None.

    Truncation alone (timeout / equation budget exceeded) is not a flow
    bug — preflight ran out of room to fully exercise the graph, but the
    code we did exercise was clean. Don't block edits on that.
    """
    if report.ok:
        return None
    hard = [issue for issue in report.issues if issue.category != "truncated"]
    if not hard:
        return None
    primary = hard[0]
    extra = f" (+{len(hard) - 1} more)" if len(hard) > 1 else ""
    return {
        "category": primary.category or "dry_run_error",
        "message": f"dry-run: {primary.message}{extra}",
        "suggestion": None,
        "issues": [
            {
                "equation_key": issue.equation_key,
                "equation_type": issue.equation_type,
                "status": issue.status,
                "message": issue.message,
                "category": issue.category,
                "phase_path": list(issue.phase_path),
            }
            for issue in hard
        ],
    }


async def _sync_schemas_from_graph(session, flow: Flow, graph) -> None:
    """Persist ``graph.input_specs`` / ``graph.output_specs`` into the DB.

    The graph builder serializes the @flow(inputs=..., outputs=...)
    declarations in the shape the frontend expects. We compare against the
    stored JSON and only write+commit when something differs, so identity
    round-trips don't churn the DB or broadcast spurious diffs.
    """
    new_inputs = graph.input_specs or {}
    new_outputs = graph.output_specs or {}

    def _loads(raw):
        try:
            return json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            return {}

    current_inputs = _loads(flow.input_schema)
    current_outputs = _loads(flow.output_schema)

    inputs_changed = current_inputs != new_inputs
    outputs_changed = current_outputs != new_outputs
    if not (inputs_changed or outputs_changed):
        return
    if inputs_changed:
        flow.input_schema = json.dumps(new_inputs) if new_inputs else None
    if outputs_changed:
        flow.output_schema = json.dumps(new_outputs) if new_outputs else None
    flow.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(flow)


async def stop_and_unregister(flow_id: int) -> None:
    """Tear down the scheduler for a flow (pause → stop → drop from registry)."""
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None:
        return
    try:
        await runtime.stop()
    finally:
        flow_registry.unregister(flow_id)

"""Flow CRUD and fork routes.

See docs/FLOWS_TECH.md §API. Execution, DSL, and HITL resolution live
in their own route modules.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

import flow_lifecycle
import flow_registry
from core.dependencies import get_db_session
from core.logging import get_logger
from database import Flow
from models.api_models import (
    PhaseInvalidateRequest,
    EquationReselectRequest,
    FlowCreateRequest,
    FlowEquationResponse,
    FlowForkRequest,
    FlowPhaseNodeResponse,
    FlowPhaseTreeResponse,
    FlowResponse,
    FlowTaskResponse,
    FlowUpdateRequest,
)
from project_service import get_project_or_404
from flow_runtime import (
    DryRunConfig,
    EquationStatus,
    create_flow_directory,
    dry_run_flow,
    fork_flow_directory,
    get_flow_dir,
    get_empty_flow_program,
    get_flow_program_path,
    get_flow_state_db_path,
    graph_db,
    is_empty_flow_program,
    mark_user_program_edit,
    write_empty_flow_program,
)
from flow_service import get_flow_or_404
from utils.websocket import ws_manager


def _track_flow_event(event: str, flow_id: int, extra: Optional[dict] = None) -> None:
    """Emit a flow lifecycle event carrying flowHash (never ids/names)."""
    try:
        from object_hash import salted_hash
        from telemetry import get_telemetry_client
        props = {"flowHash": salted_hash(f"flow:{flow_id}")}
        if extra:
            props.update(extra)
        get_telemetry_client().track(event, props, category="flow")
    except Exception:  # noqa: BLE001 — telemetry never affects the app
        pass

log = get_logger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flows"])

_VALID_EXECUTION_STATES = {"idle", "running", "paused"}


def _json_safe_flow_value(value: Any) -> Any:
    """Coerce live flow values into JSON-safe API payloads.

    Persisted equation rows have already gone through JSON serialization, but
    active runtimes overlay raw in-memory results. In particular, callable
    code can return Media wrappers that are useful inside the flow sandbox
    but cannot be serialized by Pydantic/FastAPI.
    """
    try:
        from flow_runtime.media_arg import Media
    except ImportError:  # pragma: no cover - defensive for partial imports
        Media = None  # type: ignore[assignment]

    if Media is not None and isinstance(value, Media):
        return {"id": value.id, "filename": value.filename}
    if isinstance(value, dict):
        return {str(k): _json_safe_flow_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_flow_value(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _root_status_summary_for_flow(flow_id: int) -> dict[str, int]:
    """Root-phase status_summary for a flow, matching phase-tree filtering.

    Prefers the in-memory runtime graph when loaded (cheapest + most current);
    falls back to state.db rows otherwise. Used by list/update responses and
    by the equation-update broadcast so the sidebar / flows page / project
    overview can derive `Running / Done / Your Turn / Error` without having
    to open the flow to hydrate the summary cache.
    """
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None and runtime.graph is not None:
        return compute_root_summary_from_equations(runtime.graph.all_equations())
    rows = _load_equations_for_flow(flow_id)
    if not rows:
        return {}
    return compute_root_summary_from_rows(rows)


def _flow_has_load_error(flow_id: int) -> bool:
    """Return True when the flow's program is currently parked behind a
    load_error. Mirrors the precedence used by ``get_phase_tree``: trust the
    live runtime when registered, otherwise fall back to the cached error.
    """
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None:
        return runtime.last_load_error is not None
    return flow_lifecycle.get_cached_load_error(flow_id) is not None


def _serialize(flow: Flow) -> FlowResponse:
    data = flow.to_dict()
    data["root_status_summary"] = _root_status_summary_for_flow(flow.id)
    data["has_load_error"] = _flow_has_load_error(flow.id)
    return FlowResponse(**data)


def _program_hash(program_text: str) -> str:
    return hashlib.sha256(program_text.encode("utf-8")).hexdigest()


async def _uniquify_flow_name(
    session: AsyncSession,
    base_name: str,
    project_id: Optional[int],
) -> str:
    """Return `base_name` with a numeric suffix (" 1", " 2", …) appended until
    no non-deleted flow in the same project scope shares the name.

    If `base_name` itself already ends in " N", the suffix search starts at
    N+1 so copying "Foo 3" yields "Foo 4" rather than "Foo 3 1".
    """
    match = re.match(r"^(.*?) (\d+)$", base_name)
    if match:
        stem = match.group(1)
        start = int(match.group(2)) + 1
    else:
        stem = base_name
        start = 1

    stmt = select(Flow.name).where(
        Flow.deleted_at.is_(None),
        Flow.name.like(f"{stem}%"),
    )
    if project_id is None:
        stmt = stmt.where(Flow.project_id.is_(None))
    else:
        stmt = stmt.where(Flow.project_id == project_id)

    taken = set((await session.execute(stmt)).scalars().all())

    if base_name not in taken:
        return base_name
    n = start
    while f"{stem} {n}" in taken:
        n += 1
    return f"{stem} {n}"


def _build_metadata(flow: Flow) -> dict:
    return {
        "flow_id": flow.id,
        "name": flow.name,
        "description": flow.description,
        "parent_id": flow.parent_id,
        "project_id": flow.project_id,
        "input_schema": json.loads(flow.input_schema) if flow.input_schema else None,
        "output_schema": json.loads(flow.output_schema) if flow.output_schema else None,
        "inputs": json.loads(flow.inputs) if flow.inputs else None,
        "execution_state": flow.execution_state,
        "created_at": flow.created_at.isoformat(),
    }


@router.post("", response_model=FlowResponse)
async def create_flow(
    request: FlowCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if request.project_id is not None:
        await get_project_or_404(session, request.project_id)

    name = (request.name or "").strip()

    flow = Flow(
        name=name,
        description=request.description,
        project_id=request.project_id,
        input_schema=json.dumps(request.input_schema) if request.input_schema is not None else None,
        output_schema=json.dumps(request.output_schema) if request.output_schema is not None else None,
        inputs=json.dumps(request.inputs) if request.inputs is not None else None,
        execution_state="idle",
    )
    session.add(flow)
    await session.flush()  # assign flow.id before we create the on-disk dir

    # Create on-disk layout. If this fails, the transaction rolls back and no
    # row is committed — directory and DB row stay consistent.
    create_flow_directory(flow.id, metadata=_build_metadata(flow))

    # Hash the (empty) program file we just wrote; stored for future store keying.
    program_path = get_flow_program_path(flow.id)
    flow.program_hash = _program_hash(program_path.read_text())

    await session.commit()
    await session.refresh(flow)

    _created_extra: dict = {"forked": False}
    if flow.project_id:
        from object_hash import salted_hash
        _created_extra["projectHash"] = salted_hash(f"project:{flow.project_id}")
    _track_flow_event("flow_created", flow.id, _created_extra)

    response = _serialize(flow)
    await ws_manager.broadcast("flow_created", {"flow": response.model_dump()})
    return response


@router.get("", response_model=list[FlowResponse])
async def list_flows(
    execution_state: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    parent_id: Optional[int] = Query(None),
    include_deleted: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
):
    conditions = []
    if not include_deleted:
        conditions.append(Flow.deleted_at.is_(None))
    if execution_state is not None:
        if execution_state not in _VALID_EXECUTION_STATES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid execution_state; expected one of {sorted(_VALID_EXECUTION_STATES)}",
            )
        conditions.append(Flow.execution_state == execution_state)
    if project_id is not None:
        conditions.append(Flow.project_id == project_id)
    else:
        conditions.append(Flow.project_id.is_(None))
    if parent_id is not None:
        conditions.append(Flow.parent_id == parent_id)

    query = select(Flow)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(desc(Flow.updated_at), desc(Flow.id))

    result = await session.execute(query)
    return [_serialize(r) for r in result.scalars().all()]


@router.get("/{flow_id}", response_model=FlowResponse)
async def get_flow(flow_id: int, session: AsyncSession = Depends(get_db_session)):
    flow = await get_flow_or_404(session, flow_id)
    return _serialize(flow)


@router.patch("/{flow_id}", response_model=FlowResponse)
async def update_flow(
    flow_id: int,
    request: FlowUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    flow = await get_flow_or_404(session, flow_id)

    if request.name is not None:
        flow.name = request.name.strip()
    if request.description is not None:
        flow.description = request.description
    if "project_id" in request.model_fields_set:
        if request.project_id is not None:
            await get_project_or_404(session, request.project_id)
        flow.project_id = request.project_id
    if request.input_schema is not None:
        flow.input_schema = json.dumps(request.input_schema)
    if request.output_schema is not None:
        flow.output_schema = json.dumps(request.output_schema)
    if request.inputs is not None:
        flow.inputs = json.dumps(request.inputs)
    if request.execution_state is not None:
        if request.execution_state not in _VALID_EXECUTION_STATES:
            raise HTTPException(
                status_code=400,
                detail=f"invalid execution_state; expected one of {sorted(_VALID_EXECUTION_STATES)}",
            )
        flow.execution_state = request.execution_state

    flow.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(flow)

    # If the user just changed the flow's `inputs` and a runtime is live,
    # push the new values into the runtime and diff-rebuild. Otherwise the
    # running graph keeps using the stale input values from build time and
    # downstream code() blocks resolve inputs to None → opaque TypeError.
    if request.inputs is not None:
        runtime = flow_registry.get_runtime(flow_id)
        if runtime is not None:
            new_inputs = json.loads(flow.inputs) if flow.inputs else {}
            if runtime.inputs != new_inputs:
                runtime.inputs = dict(new_inputs)
                try:
                    runtime.try_reload_program()
                except Exception:  # noqa: BLE001 — best-effort
                    log.exception("inputs-change reload failed", extra={"flow_id": flow_id})
        # Auto-start if the user submitted inputs on an idle flow — filling
        # the form is the "run this now" gesture, no separate play click.
        if flow.execution_state == "idle":
            try:
                runtime = flow_lifecycle.get_or_create_runtime(flow)
                await runtime.start()
                flow.execution_state = "running"
                flow.updated_at = datetime.utcnow()
                await session.commit()
                await session.refresh(flow)
                import flow_telemetry
                flow_telemetry.note_started(flow_id)
                _track_flow_event("flow_started", flow_id, {"dryRun": False})
            except HTTPException:
                # Graph doesn't build yet — leave idle so the user sees the
                # error banner rather than a phantom "running" state.
                pass
            except Exception:  # noqa: BLE001
                log.exception("auto-start on inputs PATCH failed", extra={"flow_id": flow_id})

    response = _serialize(flow)
    await ws_manager.broadcast("flow_updated", {"flow": response.model_dump()})
    return response


@router.delete("/{flow_id}")
async def delete_flow(flow_id: int, session: AsyncSession = Depends(get_db_session)):
    """Soft delete. Media is associated, not owned — not touched."""
    flow = await get_flow_or_404(session, flow_id)
    deleted_at = datetime.utcnow()
    flow.deleted_at = deleted_at
    flow.updated_at = deleted_at
    flow.execution_state = "idle"
    await session.commit()
    # Stop any in-memory scheduler so a deleted flow can't keep firing
    # WS events or writing to its state.db.
    await flow_lifecycle.stop_and_unregister(flow_id)
    await ws_manager.broadcast("flow_deleted", {"flow_id": flow_id})
    _track_flow_event("flow_deleted", flow_id)
    return {"status": "success"}


@router.post("/{flow_id}/restore", response_model=FlowResponse)
async def restore_flow(flow_id: int, session: AsyncSession = Depends(get_db_session)):
    """Clear the soft-delete tombstone — pairs with DELETE for undo."""
    result = await session.execute(select(Flow).where(Flow.id == flow_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    if flow.deleted_at is None:
        raise HTTPException(status_code=400, detail="Flow is not deleted")
    flow.deleted_at = None
    flow.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(flow)
    response = _serialize(flow)
    await ws_manager.broadcast("flow_restored", {"flow": response.model_dump()})
    return response


@router.post("/{flow_id}/fork", response_model=FlowResponse)
async def fork_flow(
    flow_id: int,
    request: FlowForkRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Fork a flow (primary "Run" operation).

    Creates a new flow row with parent_id set, copies the on-disk directory
    (APFS clonefile when possible), snapshots the parent's program.py as
    program_base.py in the fork, and resets transient equation states.
    Equation store entries are shared — nothing is cloned there.
    """
    parent = await get_flow_or_404(session, flow_id)

    if request.project_id is not None:
        await get_project_or_404(session, request.project_id)

    # Inherit from parent unless overridden.
    base_name = request.name.strip() if request.name else parent.name
    description = request.description if request.description is not None else parent.description
    project_id = request.project_id if request.project_id is not None else parent.project_id
    inputs_json = (
        json.dumps(request.inputs) if request.inputs is not None else parent.inputs
    )

    name = await _uniquify_flow_name(session, base_name, project_id)

    fork = Flow(
        name=name,
        description=description,
        parent_id=parent.id,
        project_id=project_id,
        input_schema=parent.input_schema,
        output_schema=parent.output_schema,
        inputs=inputs_json,
        program_hash=parent.program_hash,
        execution_state="idle",
    )
    session.add(fork)
    await session.flush()  # assign fork.id

    parent_dir = get_flow_dir(parent.id)
    if not parent_dir.exists():
        # Defensive: a deleted or corrupted parent directory. Rolling back the
        # flush is handled by the session — bail with 500 so the caller knows.
        raise HTTPException(
            status_code=500,
            detail=f"parent flow {parent.id} directory missing; cannot fork",
        )

    fork_flow_directory(parent.id, fork.id, metadata=_build_metadata(fork))

    await session.commit()
    await session.refresh(fork)

    _fork_extra: dict = {"forked": True}
    if fork.project_id:
        from object_hash import salted_hash
        _fork_extra["projectHash"] = salted_hash(f"project:{fork.project_id}")
    _track_flow_event("flow_created", fork.id, _fork_extra)

    response = _serialize(fork)
    await ws_manager.broadcast("flow_created", {"flow": response.model_dump()})
    return response


# ---------------------------------------------------------------------------
# Phase 4 — Per-flow tasks listing
# ---------------------------------------------------------------------------


_VALID_SORT_MODES = {
    "oldest_first",
    "newest_first",
    "unblocks_most_work",
    "by_type",
}


def _sort_tasks(rows: list[dict], sort: str) -> list[dict]:
    if sort == "oldest_first":
        return sorted(rows, key=lambda t: (t.get("created_at") or "", t.get("task_id", 0)))
    if sort == "newest_first":
        return sorted(
            rows, key=lambda t: (t.get("created_at") or "", t.get("task_id", 0)), reverse=True,
        )
    if sort == "unblocks_most_work":
        return sorted(
            rows,
            key=lambda t: (-int(t.get("downstream_count") or 0), t.get("created_at") or ""),
        )
    if sort == "by_type":
        return sorted(
            rows, key=lambda t: (t.get("task_type") or "", t.get("created_at") or ""),
        )
    raise HTTPException(
        status_code=400,
        detail=f"invalid sort; expected one of {sorted(_VALID_SORT_MODES)}",
    )


@router.get("/{flow_id}/tasks", response_model=list[FlowTaskResponse])
async def list_flow_tasks(
    flow_id: int,
    sort: str = Query("oldest_first"),
    task_type: Optional[str] = Query(None, description="Comma-separated filter"),
    status: str = Query("pending"),
    session: AsyncSession = Depends(get_db_session),
):
    flow = await get_flow_or_404(session, flow_id)
    if sort not in _VALID_SORT_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid sort; expected one of {sorted(_VALID_SORT_MODES)}",
        )
    task_types = None
    if task_type:
        task_types = [t.strip() for t in task_type.split(",") if t.strip()]

    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None:
        rows = runtime.list_tasks(status=status, task_types=task_types)
    else:
        state_db = get_flow_state_db_path(flow_id)
        rows = graph_db.list_tasks(state_db, status=status, task_types=task_types)
        for r in rows:
            payload = r.get("payload") or {}
            r["downstream_count"] = int(payload.get("downstream_count") or 0)

    for r in rows:
        r["flow_id"] = flow.id
        r["flow_name"] = flow.name

    rows = _sort_tasks(rows, sort)
    return [
        FlowTaskResponse(
            task_id=f"{flow.id}:{r['task_id']}",
            task_type=r["task_type"],
            status=r["status"],
            instructions=r.get("instructions"),
            payload=r.get("payload"),
            resolution=r.get("resolution"),
            created_at=r["created_at"],
            resolved_at=r.get("resolved_at"),
            equation_key=r["equation_key"],
            equation_type=r["equation_type"],
            equation_status=r["equation_status"],
            phase_path=r.get("phase_path") or [],
            inputs_hash=r.get("inputs_hash"),
            attempt=r.get("attempt") or 1,
            error=r.get("error"),
            dependencies=r.get("dependencies") or [],
            downstream_count=int(r.get("downstream_count") or 0),
            flow_id=r["flow_id"],
            flow_name=r["flow_name"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Phase 5 — Execution control, phase tree, equations, invalidation
# ---------------------------------------------------------------------------


async def _set_execution_state(
    session: AsyncSession, flow: Flow, new_state: str,
) -> FlowResponse:
    flow.execution_state = new_state
    flow.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(flow)
    response = _serialize(flow)
    await ws_manager.broadcast("flow_updated", {"flow": response.model_dump()})
    return response


@router.post("/{flow_id}/start", response_model=FlowResponse)
async def start_flow(
    flow_id: int,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
):
    """Begin execution. Idempotent — already-running flows return OK.

    Builds the graph from program.py (registering the runtime in
    `flow_registry`), then starts the FRP scheduler.
    """
    flow = await get_flow_or_404(session, flow_id)
    try:
        runtime = flow_lifecycle.get_or_create_runtime(flow)
    except HTTPException as http_exc:
        # Graph build failed — broadcast a load_error so the PhaseTree banner
        # shows the problem instead of silently returning a 400.
        cause = http_exc.__cause__
        load_error: dict[str, Any] = {
            "category": getattr(cause, "category", "build_error"),
            "message": getattr(cause, "message", None) or http_exc.detail,
            "suggestion": getattr(cause, "suggestion", None),
        }
        await ws_manager.broadcast("flow_updated", {
            "flow": _serialize(flow).model_dump(),
            "load_error": load_error,
            "flow_id": flow_id,
        })
        raise
    try:
        if dry_run:
            report = await dry_run_flow(
                flow_id=flow.id,
                program_path=get_flow_program_path(flow.id),
                inputs=json.loads(flow.inputs) if flow.inputs else {},
                project_id=flow.project_id,
            )
            if not report.ok:
                raise HTTPException(
                    status_code=400,
                    detail={"message": "flow dry-run failed", "dry_run": report.to_dict()},
                )
        await runtime.start()
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"start failed: {exc}") from exc
    import flow_telemetry
    flow_telemetry.note_started(flow_id)
    _track_flow_event("flow_started", flow_id, {"dryRun": dry_run})
    return await _set_execution_state(session, flow, "running")


@router.post("/{flow_id}/dry-run")
async def dry_run_flow_route(
    flow_id: int,
    max_items_per_collection: int = Query(2, ge=1, le=10),
    max_equations: int = Query(200, ge=10, le=2000),
    timeout_seconds: float = Query(5.0, gt=0.0, le=30.0),
    session: AsyncSession = Depends(get_db_session),
):
    flow = await get_flow_or_404(session, flow_id)
    report = await dry_run_flow(
        flow_id=flow.id,
        program_path=get_flow_program_path(flow.id),
        inputs=json.loads(flow.inputs) if flow.inputs else {},
        project_id=flow.project_id,
        config=DryRunConfig(
            max_items_per_collection=max_items_per_collection,
            max_equations=max_equations,
            timeout_seconds=timeout_seconds,
        ),
    )
    return report.to_dict()


@router.post("/{flow_id}/pause", response_model=FlowResponse)
async def pause_flow(
    flow_id: int, session: AsyncSession = Depends(get_db_session),
):
    flow = await get_flow_or_404(session, flow_id)
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None:
        await runtime.pause()
    _track_flow_event("flow_paused", flow_id)
    return await _set_execution_state(session, flow, "paused")


@router.post("/{flow_id}/resume", response_model=FlowResponse)
async def resume_flow(
    flow_id: int, session: AsyncSession = Depends(get_db_session),
):
    flow = await get_flow_or_404(session, flow_id)
    runtime = flow_lifecycle.get_or_create_runtime(flow)
    if runtime.run is None:
        # First-time resume after app restart: start() re-enters the loop
        # with hydrated state, which is the same effect users expect.
        await runtime.start()
    else:
        await runtime.resume()
    import flow_telemetry
    flow_telemetry.note_started(flow_id)
    _track_flow_event("flow_resumed", flow_id)
    return await _set_execution_state(session, flow, "running")


@router.post("/{flow_id}/clear", response_model=FlowResponse)
async def clear_flow_runtime_state(
    flow_id: int, session: AsyncSession = Depends(get_db_session),
):
    """Reset a flow back to an empty program and empty compiled state."""
    flow = await get_flow_or_404(session, flow_id)
    await flow_lifecycle.stop_and_unregister(flow_id)
    write_empty_flow_program(flow_id)
    graph_db.clear_flow_state(get_flow_state_db_path(flow_id))
    flow.program_hash = _program_hash(get_empty_flow_program())
    flow.input_schema = None
    flow.execution_state = "idle"
    flow.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(flow)
    flow_lifecycle.clear_cached_load_error(flow_id)
    _track_flow_event("flow_cleared", flow_id)
    response = _serialize(flow)
    await ws_manager.broadcast("flow_updated", {"flow": response.model_dump(), "flow_id": flow_id})
    await ws_manager.broadcast("flow_phase_updated", {"flow_id": flow_id})
    return response


@router.post("/{flow_id}/reparse", response_model=FlowResponse)
async def reparse_flow(
    flow_id: int, session: AsyncSession = Depends(get_db_session),
):
    """Force a rebuild/reload of the flow graph from program.py."""
    flow = await get_flow_or_404(session, flow_id)
    await flow_lifecycle.apply_program_edit(session, flow_id)
    await session.refresh(flow)
    return _serialize(flow)


# ----- Phase tree -----------------------------------------------------------


from flow_runtime.summary import (
    compute_root_summary_from_equations,
    compute_root_summary_from_rows,
    include_equation_in_status_summary,
    is_scaffolding_equation,
)
from flow_runtime.step_timeline import build_phase_steps


def _friendly_tool_name(tool_id: str) -> str:
    """Turn 'comfyui:flux-dev:text-to-image' into 'Flux dev — text-to-image'."""
    if not tool_id:
        return "tool"
    parts = [p for p in tool_id.split(":") if p]
    if len(parts) >= 3:
        # provider:model:task → 'Model — task'
        return f"{parts[-2].replace('-', ' ').title()} — {parts[-1].replace('-', ' ')}"
    return tool_id.replace(":", " — ").replace("-", " ")


def _humanize_input_name(name: Optional[str]) -> str:
    """Fallback when a flow input has no explicit display_name.

    ``product_image`` → ``Product image``. Matches FlowInputForm.vue's
    ``humanizeName`` so the label reads the same in the form and the graph.
    """
    if not name:
        return ""
    spaced = " ".join(part for part in name.replace("_", " ").split() if part)
    if not spaced:
        return name
    return spaced[0].upper() + spaced[1:].lower()


def _display_name_for_equation(
    equation_type: str, definition: Optional[dict[str, Any]],
) -> Optional[str]:
    """Derive a user-visible label from an equation's type + definition.

    Returns None if there's nothing better than the raw key (caller falls
    back to a shortened key). Definition may be None when the live graph
    isn't available — we still produce type-level labels in that case.
    """
    d = definition or {}
    if equation_type == "flow_input":
        if d.get("control_kind") == "literal_list":
            return "List"
        display = d.get("input_display_name")
        if isinstance(display, str) and display.strip():
            return display.strip()
        name = d.get("input_name")
        return _humanize_input_name(name) if name else "Input"
    if equation_type == "tool_call":
        tool_id = d.get("tool_id", "")
        n = d.get("n", 1)
        label = _friendly_tool_name(tool_id) if tool_id else "Tool call"
        if isinstance(n, int) and n > 1:
            label = f"{label} (×{n})"
        return label
    if equation_type == "llm_call":
        return "LLM"
    if equation_type == "code":
        routing_kind = d.get("routing_kind")
        if routing_kind == "switch":
            return "Choose Value"
        if routing_kind == "filter":
            return "Filter Items"
        if routing_kind == "partition":
            return "Split Items"
        if routing_kind == "take":
            return "Take First Items"
        if routing_kind in ("when", "gate"):
            return "Gate Value"
        # The agent-authored description (when present) carries the meaning —
        # it's exposed separately on the response. The display_name is a
        # plain type-level label used as a title by clients that don't
        # render the description as a subtitle.
        return "Code"
    if equation_type == "info":
        title = d.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return None
    if equation_type == "create_set":
        title = d.get("title")
        if isinstance(title, str) and title.strip():
            return f"Set: {title.strip()}"
        return "Set"
    if equation_type == "create_grid":
        title = d.get("title")
        rows = d.get("rows")
        cols = d.get("cols")
        if isinstance(title, str) and title.strip():
            return f"Grid: {title.strip()}"
        if isinstance(rows, int) and isinstance(cols, int):
            return f"Grid ({rows}×{cols})"
        return "Grid"
    if equation_type == "create_document":
        title = d.get("title")
        if isinstance(title, str) and title.strip():
            return f"Document: {title.strip()}"
        return "Document"
    if equation_type == "create_image":
        title = d.get("title")
        if isinstance(title, str) and title.strip():
            return f"Image: {title.strip()}"
        return "Image"
    if equation_type == "create_layout":
        title = d.get("title")
        if isinstance(title, str) and title.strip():
            return f"Layout: {title.strip()}"
        return "Layout"
    if equation_type == "rasterize_layout":
        return "Rasterize layout"
    if equation_type == "web_search":
        return "Web Search"
    if equation_type == "fetch_media":
        return "Fetch Media"
    if equation_type == "hitl":
        kind = d.get("hitl_type")
        count = d.get("count")
        # No "You …" prefix here — the frontend composes "Your Turn: {label}"
        # (or splits into a title/subtitle) when the step is actionable, so
        # labels should stand alone as imperatives.
        if kind == "select":
            if isinstance(count, int) and count > 1:
                return f"Pick {count}"
            return "Pick one"
        if kind == "approve":
            return "Approve"
        return "Human step"
    if equation_type == "control":
        kind = d.get("control_kind", "")
        if kind == "foreach":
            return "Loop"
        if kind == "foreach_iteration":
            iter_key = d.get("iteration_key")
            if iter_key is None or iter_key == "":
                return "Iteration"
            try:
                return f"Iteration {int(iter_key) + 1}"
            except (TypeError, ValueError):
                return f"Iteration: {iter_key}"
        if kind == "zip_nodes":
            return "Combine"
        if kind == "literal_list":
            return "List"
        return kind.replace("_", " ").title() or None
    return None


def _is_scaffolding(equation_type: str, definition: Optional[dict[str, Any]]) -> bool:
    return is_scaffolding_equation(equation_type, definition)


def _definition_from_runtime(flow_id: int, equation_key: str) -> Optional[dict[str, Any]]:
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None or runtime.graph is None:
        return None
    eq = runtime.graph.try_get(equation_key)
    if eq is None:
        return None
    return eq.definition


def _resolve_live_dynamic_value(flow_id: int, value: Any) -> Any:
    """Resolve NodeRefs from the live flow graph for lightweight previews."""
    try:
        from flow_runtime.graph import NodeRef
    except ImportError:  # pragma: no cover
        NodeRef = None  # type: ignore

    if NodeRef is not None and isinstance(value, NodeRef):
        runtime = flow_registry.get_runtime(flow_id)
        if runtime is None or runtime.graph is None:
            return None
        dep = runtime.graph.try_get(value.equation_key)
        if dep is None or dep.result is None:
            return None
        return dep.result
    if isinstance(value, list):
        return [_resolve_live_dynamic_value(flow_id, item) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_live_dynamic_value(flow_id, item) for item in value)
    if isinstance(value, dict):
        return {k: _resolve_live_dynamic_value(flow_id, v) for k, v in value.items()}
    return value


def _render_prompt_preview(
    flow_id: Optional[int],
    prompt_template: str,
    prompt_dynamic: dict[str, Any],
) -> str:
    if not prompt_template:
        return ""
    if flow_id is None or not prompt_dynamic:
        return prompt_template

    bindings = _resolve_live_dynamic_value(flow_id, prompt_dynamic) or {}
    if not isinstance(bindings, dict) or not bindings:
        return prompt_template

    positional = [
        v for _, v in sorted(
            ((int(k), v) for k, v in bindings.items() if str(k).isdigit()),
            key=lambda kv: kv[0],
        )
    ]
    named = {k: v for k, v in bindings.items() if not str(k).isdigit()}
    try:
        return prompt_template.format(*positional, **named)
    except Exception:  # noqa: BLE001 - preview should never break the route
        return prompt_template


def _output_name_by_key_for_flow(flow_id: int) -> dict[str, str]:
    """Equation keys surfaced by the flow's return, keyed to output name.

    Pulled from the live graph since ``output_keys`` is set by the builder
    each time program.py is re-parsed and isn't persisted to state.db.
    Returns an empty dict when the runtime isn't registered.
    """
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None or runtime.graph is None:
        return {}
    return dict(runtime.graph.output_name_by_key or {})


def _output_type_by_key_for_flow(flow_id: int) -> dict[str, str]:
    """Declared output type for each surfaced equation key."""
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None or runtime.graph is None:
        return {}
    name_by_key = dict(runtime.graph.output_name_by_key or {})
    specs = dict(getattr(runtime.graph, "output_specs", None) or {})
    out: dict[str, str] = {}
    for equation_key, output_name in name_by_key.items():
        spec = specs.get(output_name)
        if isinstance(spec, dict):
            typ = spec.get("type")
            if isinstance(typ, str) and typ:
                out[equation_key] = typ
    return out


def _media_ids_from_declared_output(result: Any, output_type: Optional[str]) -> list[int]:
    """Recover media ids for surfaced media outputs from older result rows.

    Newer code() evaluations store media ids in result_media_ids, but existing
    completed rows may only have the scalar result (for example 1288). The
    declared output type lets the API safely interpret that scalar as media.
    """
    if output_type == "media":
        if isinstance(result, int) and not isinstance(result, bool):
            return [result]
        if isinstance(result, dict):
            mid = result.get("media_id") or result.get("mediaId") or result.get("id")
            if isinstance(mid, int) and not isinstance(mid, bool):
                return [mid]
    if output_type == "list[media]" and isinstance(result, list):
        ids: list[int] = []
        for item in result:
            if isinstance(item, int) and not isinstance(item, bool):
                ids.append(item)
            elif isinstance(item, dict):
                mid = item.get("media_id") or item.get("mediaId") or item.get("id")
                if isinstance(mid, int) and not isinstance(mid, bool):
                    ids.append(mid)
        return ids
    return []


def _equation_to_response(
    row: dict[str, Any],
    *,
    live: Optional[dict[str, Any]] = None,
    definition: Optional[dict[str, Any]] = None,
    flow_id: Optional[int] = None,
    output_name_by_key: Optional[dict[str, str]] = None,
    output_type_by_key: Optional[dict[str, str]] = None,
) -> FlowEquationResponse:
    """Build an equation response from a state.db row, overlaying live state.

    `live` is the in-memory engine view (status / result_media_ids / etc.)
    when a runtime is active. Persisted rows are the source of truth when
    no runtime is registered. `definition` comes from the live graph — used
    to compute a human-friendly display_name; None when the graph is idle.
    `output_name_by_key` maps surfaced equation keys to declared output names,
    so the graph viz and delivery panel can render explicit outputs.
    """
    data = dict(row)
    if live is not None:
        data.update(live)
    if definition is None and isinstance(data.get("definition"), dict):
        definition = data["definition"]
    equation_type = data["equation_type"]
    display_name = _display_name_for_equation(equation_type, definition)
    hitl_kind: Optional[str] = None
    hitl_count: Optional[int] = None
    if equation_type == "hitl" and definition:
        hitl_kind = definition.get("hitl_type")
        raw_count = definition.get("count")
        if isinstance(raw_count, int):
            hitl_count = raw_count
    tool_id: Optional[str] = None
    task_type: Optional[str] = None
    if equation_type == "tool_call" and definition:
        raw_tool_id = definition.get("tool_id")
        if isinstance(raw_tool_id, str) and raw_tool_id:
            tool_id = raw_tool_id
        # task_type is required at the DSL layer (flow_dsl.primitives.tool()
        # rejects calls without it), so we read it straight from the
        # definition. No more reverse-engineering it from the tool_id slug —
        # that was wrong for tools whose ids don't carry the task and unsafe
        # for multi-task tools.
        raw_task_type = definition.get("task_type")
        if isinstance(raw_task_type, str) and raw_task_type:
            task_type = raw_task_type
    control_kind: Optional[str] = None
    result_from: Optional[str] = None
    slot_count: Optional[int] = None
    approve_instructions: Optional[str] = None
    if equation_type == "control" and definition:
        raw_kind = definition.get("control_kind")
        if isinstance(raw_kind, str) and raw_kind:
            control_kind = raw_kind
        raw_result_from = definition.get("_result_from")
        if isinstance(raw_result_from, str) and raw_result_from:
            result_from = raw_result_from
        # Surface hitl.approve-only fields explicitly so the SlotGroup UI can
        # render its instructions strip + count badge without needing access
        # to raw definition JSON. Other control kinds ignore these.
        if control_kind == "approve":
            raw_count = definition.get("count")
            if isinstance(raw_count, int):
                slot_count = raw_count
            raw_instructions = definition.get("instructions")
            if isinstance(raw_instructions, str):
                approve_instructions = raw_instructions
    input_name: Optional[str] = None
    if equation_type == "flow_input" and definition:
        raw_input_name = definition.get("input_name")
        if isinstance(raw_input_name, str) and raw_input_name:
            input_name = raw_input_name
    description: Optional[str] = None
    subtitle: Optional[str] = None
    routing_kind: Optional[str] = None
    if equation_type == "code" and definition:
        raw_routing_kind = definition.get("routing_kind")
        if isinstance(raw_routing_kind, str) and raw_routing_kind.strip():
            routing_kind = raw_routing_kind.strip()
        raw_description = definition.get("description")
        if isinstance(raw_description, str) and raw_description.strip():
            description = raw_description.strip()
        raw_subtitle = definition.get("subtitle")
        if isinstance(raw_subtitle, str) and raw_subtitle.strip():
            subtitle = raw_subtitle.strip()
    elif equation_type == "info" and definition:
        raw_subtitle = definition.get("subtitle")
        if isinstance(raw_subtitle, str) and raw_subtitle.strip():
            description = raw_subtitle.strip()
    elif equation_type in ("llm_call", "llm_batch", "llm_slot") and definition:
        # Surface a prompt preview so graph nodes can show "what this LLM
        # is being asked" in the body. Literal prompts render as-is; dynamic
        # NodeRef prompts resolve from the live graph when possible.
        raw_prompt = definition.get("prompt_template")
        if isinstance(raw_prompt, str) and raw_prompt.strip():
            dynamic = definition.get("_dynamic") or {}
            prompt_dynamic = dynamic.get("prompt") if isinstance(dynamic, dict) else None
            if not isinstance(prompt_dynamic, dict):
                prompt_dynamic = {}
            description = _render_prompt_preview(
                flow_id,
                raw_prompt,
                prompt_dynamic,
            ).strip()
    surfaced_output_name = None
    surfaced_output_type = None
    if output_name_by_key:
        surfaced_output_name = output_name_by_key.get(data["equation_key"])
    if output_type_by_key:
        surfaced_output_type = output_type_by_key.get(data["equation_key"])
    result_value = _json_safe_flow_value(data.get("result"))
    result_media_ids = data.get("result_media_ids") or []
    if not result_media_ids and surfaced_output_type:
        result_media_ids = _media_ids_from_declared_output(result_value, surfaced_output_type)
    return FlowEquationResponse(
        equation_key=data["equation_key"],
        equation_type=equation_type,
        status=data["status"],
        display_name=display_name,
        phase_path=data.get("phase_path") or [],
        inputs_hash=data.get("inputs_hash"),
        attempt=data.get("attempt") or 1,
        result=result_value,
        result_media_ids=result_media_ids,
        execution_duration_ms=data.get("execution_duration_ms"),
        compute_duration_ms=data.get("compute_duration_ms"),
        error=data.get("error"),
        dependencies=data.get("dependencies") or [],
        created_at=data.get("created_at"),
        completed_at=data.get("completed_at"),
        invalidated_at=data.get("invalidated_at"),
        is_scaffolding=_is_scaffolding(equation_type, definition),
        hitl_kind=hitl_kind,
        hitl_count=hitl_count,
        tool_id=tool_id,
        task_type=task_type,
        control_kind=control_kind,
        result_from=result_from,
        description=description,
        subtitle=subtitle,
        routing_kind=routing_kind,
        is_output=surfaced_output_name is not None,
        output_name=surfaced_output_name,
        output_type=surfaced_output_type,
        slot_count=slot_count,
        instructions=approve_instructions,
        input_name=input_name,
    )


def _load_equations_for_flow(flow_id: int) -> list[dict[str, Any]]:
    """Load equation rows from state.db, parsing JSON columns.

    Falls back to an empty list when the state.db doesn't exist yet (a
    freshly-created flow whose program.py has never been run).
    """
    db_path = get_flow_state_db_path(flow_id)
    if not db_path.exists():
        return []
    rows = graph_db.load_equation_rows(db_path)
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "equation_key": row["equation_key"],
                "equation_type": row["equation_type"],
                "definition": json.loads(row["definition"]) if row.get("definition") else None,
                "status": row["status"],
                "phase_path": json.loads(row["phase_path"]) if row["phase_path"] else [],
                "inputs_hash": row["inputs_hash"],
                "attempt": row["attempt"] or 1,
                "result": json.loads(row["result"]) if row["result"] else None,
                "result_media_ids": json.loads(row["result_media_ids"]) if row["result_media_ids"] else [],
                "execution_duration_ms": row["execution_duration_ms"],
                "compute_duration_ms": row["compute_duration_ms"],
                "error": row["error"],
                "dependencies": json.loads(row["dependencies"]) if row["dependencies"] else [],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
                "invalidated_at": row["invalidated_at"],
            }
        )
    return out


def _apply_runtime_overlay(
    rows: list[dict[str, Any]], flow_id: int,
) -> list[dict[str, Any]]:
    """Overlay in-memory runtime state onto persisted rows when running.

    The engine may have mutated an equation in-memory before the scheduler
    tick that persists it — the overlay keeps the API reading current.
    """
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None or runtime.graph is None:
        return rows
    for row in rows:
        eq = runtime.graph.try_get(row["equation_key"])
        if eq is None:
            continue
        row["status"] = eq.status.value
        row["attempt"] = eq.attempt
        row["result_media_ids"] = list(eq.result_media_ids)
        row["execution_duration_ms"] = eq.execution_duration_ms
        row["compute_duration_ms"] = eq.compute_duration_ms
        row["error"] = eq.error
        if eq.result is not None:
            row["result"] = eq.result
    return rows


def _phase_tree_from_equations(
    rows: list[dict[str, Any]],
    task_counts: dict[str, int],
    steps_by_phase: Optional[dict[tuple[str, ...], list[dict[str, Any]]]] = None,
) -> FlowPhaseNodeResponse:
    """Build the recursive phase tree from equation rows.

    The tree's root is an implicit "" node that owns equations whose
    phase_path is empty. Each child level is named by the next path
    segment. `status_summary` rolls equation counts up the tree.

    `task_counts` maps equation_key → pending task count. We sum it up per
    node so the UI can badge phases with their task load without a second
    query.
    """
    root_path: list[str] = []

    def new_node(name: str, path: list[str]) -> FlowPhaseNodeResponse:
        return FlowPhaseNodeResponse(
            name=name,
            path=path,
            children=[],
            equation_keys=[],
            steps=[],
            status_summary={},
            pending_task_count=0,
        )

    root = new_node("", root_path)
    index: dict[tuple[str, ...], FlowPhaseNodeResponse] = {(): root}

    def include_in_phase_row(row: dict[str, Any]) -> bool:
        return include_equation_in_status_summary(
            row["equation_type"],
            row.get("definition"),
            row["status"],
        )

    def ensure_node(path: list[str]) -> FlowPhaseNodeResponse:
        key = tuple(path)
        if key in index:
            return index[key]
        parent = ensure_node(path[:-1])
        node = new_node(path[-1], list(path))
        parent.children.append(node)
        index[key] = node
        return node

    for row in rows:
        node = ensure_node(row.get("phase_path") or [])
        if include_in_phase_row(row):
            node.equation_keys.append(row["equation_key"])

    rows_by_key = {row["equation_key"]: row for row in rows}

    def collect_subtree_equation_keys(node: FlowPhaseNodeResponse) -> set[str]:
        node_path = tuple(node.path)
        depth = len(node_path)
        return {
            row["equation_key"]
            for row in rows
            if tuple(row.get("phase_path") or [])[:depth] == node_path
        }

    def sort_children_by_dependencies(node: FlowPhaseNodeResponse) -> None:
        for child in node.children:
            sort_children_by_dependencies(child)

        children = node.children
        if len(children) <= 1:
            return

        child_equation_keys = [collect_subtree_equation_keys(child) for child in children]
        order_index = {idx: idx for idx in range(len(children))}
        equation_to_child_index: dict[str, int] = {}
        for child_index, keys in enumerate(child_equation_keys):
            for equation_key in keys:
                equation_to_child_index[equation_key] = child_index

        in_degree = [0] * len(children)
        outgoing: list[set[int]] = [set() for _ in children]

        for target_index, equation_keys in enumerate(child_equation_keys):
            for equation_key in equation_keys:
                row = rows_by_key.get(equation_key)
                if row is None:
                    continue
                for dependency_key in row.get("dependencies") or []:
                    source_index = equation_to_child_index.get(dependency_key)
                    if source_index is None or source_index == target_index:
                        continue
                    if target_index in outgoing[source_index]:
                        continue
                    outgoing[source_index].add(target_index)
                    in_degree[target_index] += 1

        ready = [idx for idx in range(len(children)) if in_degree[idx] == 0]
        ordered_indices: list[int] = []
        while ready:
            current = ready.pop(0)
            ordered_indices.append(current)
            for nxt in sorted(outgoing[current], key=lambda idx: order_index[idx]):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    insert_at = 0
                    while insert_at < len(ready) and order_index[ready[insert_at]] < order_index[nxt]:
                        insert_at += 1
                    ready.insert(insert_at, nxt)

        if len(ordered_indices) != len(children):
            remaining = [idx for idx in range(len(children)) if idx not in ordered_indices]
            ordered_indices.extend(remaining)

        node.children = [children[idx] for idx in ordered_indices]

    # Roll up status_summary and pending_task_count from leaves to root.
    def rollup(node: FlowPhaseNodeResponse) -> tuple[dict[str, int], int]:
        summary: dict[str, int] = {}
        total_tasks = 0
        # Child aggregates first.
        for child in node.children:
            child_summary, child_tasks = rollup(child)
            for k, v in child_summary.items():
                summary[k] = summary.get(k, 0) + v
            total_tasks += child_tasks
        # This node's direct equations.
        for row in rows:
            if tuple(row.get("phase_path") or []) != tuple(node.path):
                continue
            if not include_in_phase_row(row):
                continue
            s = row["status"]
            summary[s] = summary.get(s, 0) + 1
            total_tasks += task_counts.get(row["equation_key"], 0)
        node.status_summary = summary
        node.pending_task_count = total_tasks
        return summary, total_tasks

    sort_children_by_dependencies(root)
    rollup(root)
    if steps_by_phase:
        def attach_steps(node: FlowPhaseNodeResponse) -> None:
            node.steps = steps_by_phase.get(tuple(node.path), [])
            for child in node.children:
                attach_steps(child)
        attach_steps(root)
    return root


def _pending_task_counts_by_equation(flow_id: int) -> dict[str, int]:
    """Count pending tasks per equation_key for phase-tree roll-up."""
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None:
        rows = runtime.list_tasks(status="pending")
    else:
        db_path = get_flow_state_db_path(flow_id)
        rows = graph_db.list_tasks(db_path, status="pending")
    out: dict[str, int] = {}
    for r in rows:
        key = r["equation_key"]
        out[key] = out.get(key, 0) + 1
    return out


def _flow_program_can_inflate(flow_id: int) -> bool:
    """Return True when program.py has real flow code to build."""
    program_path = get_flow_program_path(flow_id)
    if not program_path.exists():
        return False
    try:
        program_text = program_path.read_text()
    except OSError:
        return False
    return bool(program_text.strip()) and not is_empty_flow_program(program_text)


def _inflate_runtime_for_read(flow: Flow):
    """Hydrate the in-memory graph for read paths that need live definitions.

    This does not start the scheduler; it only loads program.py into the
    registry so dependency rendering and definition lookup can use the graph.
    If the program cannot load, callers can still fall back to persisted rows.
    """
    runtime = flow_registry.get_runtime(flow.id)
    if runtime is not None:
        return runtime
    if not _flow_program_can_inflate(flow.id):
        return None
    try:
        return flow_lifecycle.get_or_create_runtime(flow)
    except Exception:  # noqa: BLE001 — read paths should still serve saved state
        log.exception("read-path runtime inflation failed", extra={"flow_id": flow.id})
        return None


async def _recover_running_runtime_for_read(flow: Flow):
    runtime = _inflate_runtime_for_read(flow)
    if runtime is None:
        return None
    if flow.execution_state == "running":
        await runtime.start()
    runtime.recover_orphaned_work()
    return runtime


@router.get("/{flow_id}/phases", response_model=FlowPhaseTreeResponse)
async def get_phase_tree(
    flow_id: int, session: AsyncSession = Depends(get_db_session),
):
    flow = await get_flow_or_404(session, flow_id)

    # Lazy-build on read when the compiled cache (state.db) is empty but the
    # program.py exists. This catches the case where the agent wrote a
    # program between sessions (or before the write-hook existed) — without
    # this, a browser reload shows an empty tree with no explanation until
    # the user hits Start. Skip when a previous attempt already cached a
    # load_error so we don't retry the same failing build on every GET.
    if (
        not _load_equations_for_flow(flow_id)
        and flow_lifecycle.get_cached_load_error(flow_id) is None
    ):
        program_path = get_flow_program_path(flow_id)
        if program_path.exists() and program_path.stat().st_size > 0:
            try:
                program_text = program_path.read_text()
            except OSError:
                program_text = ""
            if is_empty_flow_program(program_text):
                flow_lifecycle.clear_cached_load_error(flow_id)
            else:
                try:
                    await flow_lifecycle.apply_program_edit(session, flow_id)
                except Exception:  # noqa: BLE001 — never let lazy-build 500 the read
                    log.exception("lazy apply_program_edit failed", extra={"flow_id": flow_id})

    await _recover_running_runtime_for_read(flow)

    rows = _apply_runtime_overlay(_load_equations_for_flow(flow_id), flow_id)
    task_counts = _pending_task_counts_by_equation(flow_id)
    output_name_by_key = _output_name_by_key_for_flow(flow_id)
    output_type_by_key = _output_type_by_key_for_flow(flow_id)
    equation_responses = [
        _equation_to_response(
            r,
            definition=_definition_from_runtime(flow_id, r["equation_key"]),
            flow_id=flow_id,
            output_name_by_key=output_name_by_key,
            output_type_by_key=output_type_by_key,
        )
        for r in rows
    ]
    steps_by_phase = build_phase_steps(
        [r.model_dump(mode="json") for r in equation_responses]
    )
    root = _phase_tree_from_equations(rows, task_counts, steps_by_phase)

    # Surface a graph-build failure so the UI can display it inline without
    # a separate endpoint. The live runtime is the source of truth once it
    # exists (its last_load_error is None after a successful build). Only
    # fall back to the cache when we never managed to register a runtime;
    # if we did register one and it's currently healthy, the cache is stale
    # (e.g. an earlier failed write-hook rebuild that a subsequent /start
    # superseded) and must be cleared so the banner disappears.
    load_error_payload = None
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None:
        if runtime.last_load_error is not None:
            exc = runtime.last_load_error
            load_error_payload = {
                "category": exc.category,
                "message": str(exc),
                "suggestion": exc.suggestion,
                "program_traceback": exc.program_traceback or None,
            }
        else:
            flow_lifecycle.clear_cached_load_error(flow_id)
    else:
        program_path = get_flow_program_path(flow_id)
        try:
            is_empty_program = program_path.exists() and is_empty_flow_program(program_path.read_text())
        except OSError:
            is_empty_program = False
        load_error_payload = None if is_empty_program else flow_lifecycle.get_cached_load_error(flow_id)

    return FlowPhaseTreeResponse(
        flow_id=flow.id,
        execution_state=flow.execution_state,
        root=root,
        load_error=load_error_payload,
    )


# ----- Equations ------------------------------------------------------------


@router.get("/{flow_id}/program")
async def get_flow_program(
    flow_id: int, session: AsyncSession = Depends(get_db_session),
):
    await get_flow_or_404(session, flow_id)
    program_path = get_flow_program_path(flow_id)
    if not program_path.exists():
        return {"code": ""}
    try:
        return {"code": program_path.read_text()}
    except OSError:
        return {"code": ""}


class _UpdateProgramRequest(BaseModel):
    code: str


@router.put("/{flow_id}/program")
async def update_flow_program(
    flow_id: int,
    body: _UpdateProgramRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Persist a user-authored program.py edit and rebuild the flow graph.

    Drops a sentinel marker so the agent's next turn gets a system reminder
    that the user touched the file out-of-band.
    """
    await get_flow_or_404(session, flow_id)
    program_path = get_flow_program_path(flow_id)
    program_path.parent.mkdir(parents=True, exist_ok=True)
    program_path.write_text(body.code)
    mark_user_program_edit(flow_id)
    load_error = await flow_lifecycle.apply_program_edit(session, flow_id)
    return {
        "code": body.code,
        "load_error": load_error,
    }


@router.get("/{flow_id}/equations", response_model=list[FlowEquationResponse])
async def list_equations(
    flow_id: int,
    status: Optional[str] = Query(None, description="Filter by equation status"),
    phase_path: Optional[str] = Query(
        None, description="JSON-encoded phase_path prefix filter",
    ),
    session: AsyncSession = Depends(get_db_session),
):
    await get_flow_or_404(session, flow_id)
    rows = _apply_runtime_overlay(_load_equations_for_flow(flow_id), flow_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if phase_path is not None:
        try:
            prefix = json.loads(phase_path)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="phase_path must be a JSON-encoded list",
            )
        if not isinstance(prefix, list):
            raise HTTPException(
                status_code=400, detail="phase_path must be a JSON-encoded list",
            )
        rows = [
            r for r in rows
            if (r.get("phase_path") or [])[: len(prefix)] == prefix
        ]
    output_name_by_key = _output_name_by_key_for_flow(flow_id)
    output_type_by_key = _output_type_by_key_for_flow(flow_id)
    return [
        _equation_to_response(
            r,
            definition=_definition_from_runtime(flow_id, r["equation_key"]),
            flow_id=flow_id,
            output_name_by_key=output_name_by_key,
            output_type_by_key=output_type_by_key,
        )
        for r in rows
    ]


# ----- Trace (prompt/response inspection) ----------------------------------
# Declared before the generic GET /equations/{key:path} so it wins the match
# for GET requests ending in /trace — otherwise the greedy :path converter
# on the generic route swallows the /trace suffix into equation_key and 404s.


@router.get("/{flow_id}/equations/{equation_key:path}/trace")
async def get_equation_trace(
    flow_id: int,
    equation_key: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Return the rendered prompt/source and result for an LLM or code equation.

    Intended to answer "what is this LLM actually doing?" while it's running.
    Requires a live runtime — the rendered prompt is computed by resolving
    upstream results on demand (we don't persist the rendered form). For an
    idle flow we return the template with placeholders unrendered.
    """
    flow = await get_flow_or_404(session, flow_id)
    runtime = _inflate_runtime_for_read(flow)
    state_db_path = get_flow_state_db_path(flow_id)
    persisted_row = next(
        (row for row in _load_equations_for_flow(flow_id) if row["equation_key"] == equation_key),
        None,
    )
    if runtime is None:
        runtime = flow_registry.get_runtime(flow_id)
    eq = runtime.graph.try_get(equation_key) if runtime is not None and runtime.graph is not None else None
    if eq is None and persisted_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"equation {equation_key!r} not found in flow {flow_id}",
        )

    if eq is not None:
        etype = eq.equation_type.value
        status = eq.status.value
        error = eq.error
        result = eq.result
        definition = eq.definition or {}
        detail_availability = "live"
    else:
        assert persisted_row is not None
        etype = persisted_row["equation_type"]
        status = persisted_row["status"]
        error = persisted_row.get("error")
        result = persisted_row.get("result")
        definition = persisted_row.get("definition") or {}
        detail_availability = "serialized"

    out: dict[str, Any] = {
        "equation_key": equation_key,
        "equation_type": etype,
        "status": status,
        "display_name": _display_name_for_equation(etype, definition),
        "error": error,
        "detail_availability": detail_availability,
    }

    # Best-effort resolution of upstream values. When a dep hasn't completed
    # yet we swap in a placeholder so the template still renders something.
    def _safe_resolve(value: Any) -> Any:
        try:
            from flow_runtime.graph import NodeRef
        except ImportError:  # pragma: no cover
            NodeRef = None  # type: ignore
        if NodeRef is not None and isinstance(value, NodeRef):
            if runtime is None or runtime.graph is None:
                return f"<unavailable: {value.equation_key}>"
            dep = runtime.graph.try_get(value.equation_key)
            if dep is None:
                return f"<unresolved: {value.equation_key}>"
            if dep.status.value != "completed":
                return f"<{dep.status.value}: {value.equation_key}>"
            return dep.result
        if isinstance(value, list):
            return [_safe_resolve(x) for x in value]
        if isinstance(value, tuple):
            return tuple(_safe_resolve(x) for x in value)
        if isinstance(value, dict):
            return {k: _safe_resolve(v) for k, v in value.items()}
        return value

    def _render(template: str, bindings: dict[str, Any]) -> str:
        if not template:
            return ""
        if not bindings:
            return template
        positional = [
            v for _, v in sorted(
                ((int(k), v) for k, v in bindings.items() if str(k).isdigit()),
                key=lambda kv: kv[0],
            )
        ]
        named = {k: v for k, v in bindings.items() if not str(k).isdigit()}
        try:
            return template.format(*positional, **named)
        except Exception as exc:  # noqa: BLE001 — best-effort preview
            return f"{template}\n\n[render error: {exc}]"

    d = definition
    dynamic = d.get("_dynamic") or {}

    if etype == "llm_call":
        prompt_tmpl = d.get("prompt_template", "") or ""
        system_tmpl = d.get("system_template", "") or ""
        prompt_bindings = (
            _safe_resolve(dynamic.get("prompt") or {}) or {}
            if detail_availability == "live"
            else {}
        )
        system_bindings = (
            _safe_resolve(dynamic.get("system") or {}) or {}
            if detail_availability == "live"
            else {}
        )
        out["prompt_template"] = prompt_tmpl
        out["system_template"] = system_tmpl
        out["prompt"] = (
            _render(prompt_tmpl, prompt_bindings)
            if detail_availability == "live"
            else prompt_tmpl
        )
        out["system"] = (
            _render(system_tmpl, system_bindings) if detail_availability == "live" and system_tmpl else system_tmpl
        )
        out["model"] = d.get("model")
        out["response_format"] = d.get("response_format")
        if status == "completed":
            out["result"] = result

    elif etype == "code":
        static_inputs = d.get("static_inputs") or {}
        dyn_inputs = (
            _safe_resolve(dynamic.get("inputs") or {}) or {}
            if detail_availability == "live"
            else {}
        )
        merged = {**static_inputs, **dyn_inputs}
        out["source"] = d.get("source", "")
        out["inputs"] = merged
        out["output_type"] = d.get("output_type", "json")
        if status == "completed":
            out["result"] = result

    elif etype in ("create_image", "create_layout", "rasterize_layout"):
        # User-facing view: merge static + resolved dynamic inputs with the
        # user-visible metadata fields. Hide internals (callable source,
        # definition_hash, raw static_inputs container) so the details modal
        # doesn't leak plumbing.
        static_inputs = d.get("static_inputs") or {}
        if etype == "rasterize_layout":
            merged: dict[str, Any] = {}
            if detail_availability == "live":
                layout_val = _safe_resolve(dynamic.get("layout"))
                if layout_val is not None:
                    merged["layout"] = layout_val
        else:
            dyn_inputs = (
                _safe_resolve(dynamic.get("inputs") or {}) or {}
                if detail_availability == "live"
                else {}
            )
            merged = {**static_inputs, **dyn_inputs}
        meta: dict[str, Any] = {}
        for key in ("title", "description", "width", "height", "format"):
            val = d.get(key)
            if val not in (None, ""):
                meta[key] = val
        # Metadata first so the modal reads naturally (title / size / params).
        out["inputs"] = {**meta, **merged}
        if status == "completed":
            out["result"] = result

    elif etype == "hitl":
        hitl_type = d.get("hitl_type", "")
        out["hitl_type"] = hitl_type
        out["instructions"] = d.get("instructions", "")
        # Resolve the candidate set so the UI can render the grid the user
        # was shown. Each item is whatever the candidates node resolved to
        # (typically a media_id int; the frontend handles dict/string too).
        if hitl_type == "select":
            if detail_availability == "live":
                cand_ref = dynamic.get("candidates")
                candidates = _safe_resolve(cand_ref) if cand_ref is not None else []
                out["candidates"] = candidates if isinstance(candidates, list) else []
                out["count"] = d.get("count", 1)
            else:
                task = graph_db.get_latest_task_for_equation(state_db_path, equation_key)
                payload = task.get("payload") if task else {}
                out["candidates"] = payload.get("candidates") or []
                out["count"] = payload.get("count") or d.get("count", 1)
        elif hitl_type == "approve":
            if detail_availability == "live":
                out["asset"] = _safe_resolve(dynamic.get("asset"))
            else:
                task = graph_db.get_latest_task_for_equation(state_db_path, equation_key)
                payload = task.get("payload") if task else {}
                out["asset"] = payload.get("asset")
        public_def = {k: v for k, v in d.items() if k != "_dynamic"}
        out["definition"] = public_def
        if status == "completed":
            out["result"] = result

    elif etype == "web_search":
        public_def = {k: v for k, v in d.items() if k != "_dynamic"}
        out["definition"] = public_def
        query_tmpl = d.get("query_template", "") or ""
        out["query_template"] = query_tmpl
        if detail_availability == "live":
            query_bindings = _safe_resolve(dynamic.get("query") or {}) or {}
            out["query"] = _render(query_tmpl, query_bindings).strip()
        if status == "completed":
            out["result"] = result

    else:
        # For other types (tool_call, control) return the raw definition
        # minus the _dynamic node refs (which don't serialize).
        public_def = {k: v for k, v in d.items() if k != "_dynamic"}
        out["definition"] = public_def
        if status == "completed":
            out["result"] = result

    return _json_safe_flow_value(out)


# Generic equation GET — MUST come after the /trace route above, otherwise its
# greedy {equation_key:path} swallows the /trace suffix.
@router.get(
    "/{flow_id}/equations/{equation_key:path}",
    response_model=FlowEquationResponse,
)
async def get_equation(
    flow_id: int,
    equation_key: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single equation. `equation_key` may contain '/' (iteration keys)
    so we accept it as a path-capturing parameter.
    """
    await get_flow_or_404(session, flow_id)
    rows = _apply_runtime_overlay(_load_equations_for_flow(flow_id), flow_id)
    for row in rows:
        if row["equation_key"] == equation_key:
            return _equation_to_response(
                row,
                definition=_definition_from_runtime(flow_id, equation_key),
                flow_id=flow_id,
                output_name_by_key=_output_name_by_key_for_flow(flow_id),
                output_type_by_key=_output_type_by_key_for_flow(flow_id),
            )
    raise HTTPException(
        status_code=404,
        detail=f"equation {equation_key!r} not found in flow {flow_id}",
    )


# ----- Invalidation ---------------------------------------------------------


@router.post(
    "/{flow_id}/equations/{equation_key:path}/invalidate",
    response_model=dict,
)
async def invalidate_equation(
    flow_id: int,
    equation_key: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Bump attempt on this equation and cascade-reset downstream.

    Requires an active runtime; callers should start the flow first (the
    engine needs an in-memory graph to walk dependents).
    """
    flow = await get_flow_or_404(session, flow_id)
    runtime = flow_lifecycle.get_or_create_runtime(flow)
    if runtime.run is None:
        if flow.execution_state != "running":
            raise HTTPException(
                status_code=409,
                detail="flow is not running; call /start before invalidating",
            )
        await runtime.start()
        await _set_execution_state(session, flow, "running")
    if runtime.graph is None or runtime.graph.try_get(equation_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"equation {equation_key!r} not found in flow {flow_id}",
        )
    reset = runtime.invalidate(equation_key)
    return {"flow_id": flow_id, "equation_key": equation_key, "reset": reset}


@router.post(
    "/{flow_id}/equations/{equation_key:path}/reselect",
    response_model=dict,
)
async def reselect_equation(
    flow_id: int,
    equation_key: str,
    body: EquationReselectRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Replace a completed HITL-select result and cascade downstream.

    Enables the inline re-pick UX in the Steps view: clicking a different
    candidate thumbnail immediately swaps the stored pick and invalidates
    everything that depends on it, without a round-trip through the pending-
    task queue.
    """
    flow = await get_flow_or_404(session, flow_id)
    runtime = flow_lifecycle.get_or_create_runtime(flow)
    if runtime.run is None:
        if flow.execution_state != "running":
            raise HTTPException(
                status_code=409,
                detail="flow is not running; call /start before reselecting",
            )
        await runtime.start()
        await _set_execution_state(session, flow, "running")
    if runtime.graph is None or runtime.graph.try_get(equation_key) is None:
        raise HTTPException(
            status_code=404,
            detail=f"equation {equation_key!r} not found in flow {flow_id}",
        )
    try:
        reset = await runtime.reselect_hitl(equation_key, body.resolution)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        from flow_runtime.evaluators import EvaluatorError
        if isinstance(exc, EvaluatorError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise
    return {"flow_id": flow_id, "equation_key": equation_key, "reset": reset}


@router.post("/{flow_id}/phases/invalidate", response_model=dict)
async def invalidate_phase(
    flow_id: int,
    body: PhaseInvalidateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Invalidate every equation whose phase_path matches the given prefix.

    Each matching equation gets its attempt bumped and downstream cascade,
    so a single invalidate_phase may reset many equations. Returns a count.
    """
    flow = await get_flow_or_404(session, flow_id)
    runtime = flow_lifecycle.get_or_create_runtime(flow)
    if runtime.run is None:
        if flow.execution_state != "running":
            raise HTTPException(
                status_code=409,
                detail="flow is not running; call /start before invalidating",
            )
        await runtime.start()
        await _set_execution_state(session, flow, "running")
    prefix = body.phase_path
    matching = [
        eq for eq in runtime.graph.all_equations()
        if eq.phase_path[: len(prefix)] == prefix
    ]
    if not matching:
        return {"flow_id": flow_id, "phase_path": prefix, "reset": 0, "matched": 0}

    total_reset = 0
    for eq in matching:
        # Skip equations already in transient/reset states; invalidate()
        # tolerates them but we want an accurate matched count.
        if eq.status == EquationStatus.INVALIDATED:
            continue
        total_reset += runtime.invalidate(eq.key)
    return {
        "flow_id": flow_id,
        "phase_path": prefix,
        "matched": len(matching),
        "reset": total_reset,
    }

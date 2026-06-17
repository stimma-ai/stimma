"""HITL + error tasks API.

    POST /api/tasks/:id/resolve      — resolve (HITL) or action (error)
    GET  /api/flows/:id/tasks      — per-flow listing (routed from flows.py)

Task data lives in per-flow state.db files. Resolution takes a composite
`flow_id:task_id` so the route stays flow-agnostic without needing a
centralized tasks table.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import flow_lifecycle
import flow_registry
from core.dependencies import get_db_session
from core.logging import get_logger
from database import Flow
from models.api_models import FlowTaskResponse, TaskResolveRequest
from flow_runtime import (
    EquationStatus,
    get_flow_state_db_path,
    graph_db,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["flow-tasks"])


def _parse_composite_task_id(raw: str) -> tuple[int, int]:
    """Decode a composite task id of the form `{flow_id}:{task_id}`.

    Task IDs live inside per-flow SQLite files and aren't globally
    unique, so the HTTP API encodes ownership into the path.
    """
    if ":" not in raw:
        raise HTTPException(
            status_code=400,
            detail=(
                f"task id {raw!r} must be 'flow_id:task_id' "
                f"(e.g. '42:7')"
            ),
        )
    rid_str, tid_str = raw.split(":", 1)
    try:
        return int(rid_str), int(tid_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"task id {raw!r} must be two integers separated by ':'",
        )


def _composite_task_id(flow_id: int, task_id: int) -> str:
    return f"{flow_id}:{task_id}"


_VALID_ERROR_ACTIONS = {"retry", "skip", "edit_flow"}
_VALID_WAITING_FOR_TOOL_ACTIONS = {"skip", "edit_flow"}
_HITL_TASK_TYPES = {"select", "approve"}


def _task_to_response(row: dict[str, Any]) -> FlowTaskResponse:
    # For API consumers, task_id is exposed as the composite "rid:tid" so
    # resolve/get operations can round-trip it unambiguously across all
    # flows. The numeric per-flow id is kept in payload for debugging.
    composite = _composite_task_id(
        int(row["flow_id"]) if row.get("flow_id") is not None else 0,
        int(row["task_id"]),
    )
    return FlowTaskResponse(
        task_id=composite,  # type: ignore[arg-type] — model now accepts str
        task_type=row["task_type"],
        status=row["status"],
        instructions=row.get("instructions"),
        payload=row.get("payload"),
        resolution=row.get("resolution"),
        created_at=row["created_at"],
        resolved_at=row.get("resolved_at"),
        equation_key=row["equation_key"],
        equation_type=row["equation_type"],
        equation_status=row["equation_status"],
        phase_path=row.get("phase_path") or [],
        inputs_hash=row.get("inputs_hash"),
        attempt=row.get("attempt") or 1,
        error=row.get("error"),
        dependencies=row.get("dependencies") or [],
        downstream_count=int(row.get("downstream_count") or 0),
        flow_id=row.get("flow_id"),
        flow_name=row.get("flow_name"),
    )


async def _find_task_flow(
    session: AsyncSession, composite_id: str,
) -> tuple[Flow, int, dict[str, Any]]:
    """Locate the flow_id + row for a composite task id."""
    flow_id, tid = _parse_composite_task_id(composite_id)
    stmt = select(Flow).where(
        Flow.id == flow_id, Flow.deleted_at.is_(None),
    )
    flow = (await session.execute(stmt)).scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail=f"flow {flow_id} not found")
    state_db = get_flow_state_db_path(flow_id)
    row = graph_db.get_task(state_db, tid)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"task {composite_id} not found",
        )
    return flow, tid, row


def _validate_hitl_resolution(task_row: dict[str, Any], resolution: Any) -> None:
    task_type = task_row["task_type"]
    if task_type == "select":
        payload = task_row.get("payload") or {}
        count = int(payload.get("count") or 1)
        if count == 1:
            # Accept a single value or a 1-element list.
            if isinstance(resolution, list):
                if len(resolution) != 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"select task expects 1 selection, got {len(resolution)}",
                    )
        else:
            if not isinstance(resolution, list):
                raise HTTPException(
                    status_code=400,
                    detail=f"select task with count={count} expects a list resolution",
                )
            if len(resolution) != count:
                raise HTTPException(
                    status_code=400,
                    detail=f"select task expects {count} selections, got {len(resolution)}",
                )
    elif task_type == "approve":
        if not isinstance(resolution, bool) and resolution not in ("approved", "rejected"):
            raise HTTPException(
                status_code=400,
                detail="approve task expects boolean (true/false) or 'approved'/'rejected'",
            )
    # error task shape is validated in _resolve_error_task.


def _coerce_approve_resolution(resolution: Any) -> bool:
    if isinstance(resolution, bool):
        return resolution
    if resolution == "approved":
        return True
    if resolution == "rejected":
        return False
    # Validated earlier; defensive fallback.
    raise HTTPException(status_code=400, detail="invalid approve resolution")


@router.post("/{task_id}/resolve", response_model=FlowTaskResponse)
async def resolve_task(
    task_id: str,
    body: TaskResolveRequest,
    session: AsyncSession = Depends(get_db_session),
):
    flow, tid, task_row = await _find_task_flow(session, task_id)
    flow_id = flow.id

    if task_row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"task {task_id} is {task_row['status']!r}, not pending",
        )

    task_type = task_row["task_type"]
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is None:
        try:
            runtime = flow_lifecycle.get_or_create_runtime(flow)
        except Exception:  # noqa: BLE001 — idle flows may still resolve HITL offline
            log.exception("task resolution runtime inflation failed", flow_id=flow_id)
            runtime = None

    if runtime is not None and runtime.run is None and flow.execution_state == "running":
        try:
            await runtime.start()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"failed to resume flow runtime: {exc}",
            ) from exc

    if task_type == "error":
        action = body.action
        if action is None:
            raise HTTPException(
                status_code=400,
                detail="error-task resolution requires 'action'",
            )
        if action not in _VALID_ERROR_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"invalid action; expected one of {sorted(_VALID_ERROR_ACTIONS)}",
            )
        # Skip is only valid for equations inside a foreach iteration. The
        # runtime enforces this; we surface the error before dispatching.
        if runtime is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"flow {flow_id} is not running; error-task actions "
                    f"require an active runtime"
                ),
            )
        if runtime.run is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"flow {flow_id} is not running; error-task actions "
                    f"require an active runtime"
                ),
            )
        try:
            await runtime.resolve_error_task(tid, action, value=body.value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    elif task_type == "waiting_for_tool":
        action = body.action
        if action is None:
            raise HTTPException(
                status_code=400,
                detail="waiting-for-tool task resolution requires 'action'",
            )
        if action not in _VALID_WAITING_FOR_TOOL_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "invalid action; expected one of "
                    f"{sorted(_VALID_WAITING_FOR_TOOL_ACTIONS)}"
                ),
            )
        if runtime is not None and runtime.run is not None:
            try:
                await runtime.resolve_error_task(tid, action, value=body.value)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        else:
            state_db = get_flow_state_db_path(flow_id)
            if action == "skip":
                graph_db.update_equation_status(
                    state_db,
                    task_row["equation_key"],
                    EquationStatus.SKIPPED,
                    result=None,
                    result_media_ids=[],
                    error=None,
                )
            graph_db.resolve_task(
                state_db, tid, {"action": action, "value": body.value},
            )
    elif task_type in _HITL_TASK_TYPES:
        if body.resolution is None and body.action is None:
            # hitl.approve reject-via-bool=False is the common "missing-ish" case;
            # we require resolution to be set explicitly.
            raise HTTPException(
                status_code=400,
                detail=f"HITL task resolution requires 'resolution'",
            )
        resolution = body.resolution
        _validate_hitl_resolution(task_row, resolution)
        if task_type == "approve":
            resolution = _coerce_approve_resolution(resolution)
        if runtime is None or runtime.run is None:
            # Offline resolution: persist HITL + mark completed in state.db
            # directly. The next flow start will pick up the stored result
            # via the existing inputs_hash lookup — no state is lost.
            if task_type in {"select", "approve"} and not isinstance(resolution, bool):
                try:
                    from flow_runtime.evaluators import EvaluatorError
                    from flow_runtime.production_evaluators import promote_url_media_value
                    resolution = await promote_url_media_value(
                        resolution,
                        flow_id=flow_id,
                        project_id=getattr(flow, "project_id", None),
                        equation_key=task_row.get("equation_key") or "",
                        phase_path=[],
                    )
                except ImportError:
                    pass
                except EvaluatorError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            _resolve_offline(flow_id, tid, task_row, resolution, task_type)
        else:
            try:
                await runtime.resolve_task(tid, resolution)
            except Exception as exc:
                from flow_runtime.evaluators import EvaluatorError
                if isinstance(exc, EvaluatorError):
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                raise
    else:
        raise HTTPException(
            status_code=400,
            detail=f"unknown task_type {task_type!r}",
        )

    # Return the updated row.
    state_db = get_flow_state_db_path(flow_id)
    updated = graph_db.get_task(state_db, tid)
    if updated is None:
        raise HTTPException(status_code=500, detail="task disappeared mid-resolve")
    updated["flow_id"] = flow_id
    return _task_to_response(updated)


def _resolve_offline(
    flow_id: int,
    tid: int,
    task_row: dict[str, Any],
    resolution: Any,
    task_type: str,
) -> None:
    """Resolution path when no FlowRuntime is in memory.

    Writes the HITL result durably and marks the task resolved. The
    equation stays AWAITING_INPUT in state.db; next start() hydrates and
    re-enters the eval loop, which matches the stored result by
    (equation_key, inputs_hash) and unblocks naturally.

    For approve+reject specifically, we DO NOT mark equations completed —
    the upstream equation gets invalidated on next runtime start via the
    task row recording `resolution=false` plus the existing approve-reject
    logic in resolve_task(). For Phase 4 we keep the reject path narrow:
    require the runtime to be active, so the cascade is transactional.
    """
    from flow_runtime import graph_db as _gdb
    if task_type == "approve" and resolution is False:
        raise HTTPException(
            status_code=409,
            detail=(
                f"flow {flow_id} is not running; approve-rejection "
                f"requires an active runtime so upstream invalidation can cascade"
            ),
        )
    state_db = get_flow_state_db_path(flow_id)
    inputs_hash = task_row.get("inputs_hash")
    if inputs_hash:
        _gdb.insert_hitl_result(
            state_db, task_row["equation_key"], inputs_hash, resolution,
        )
    _gdb.resolve_task(state_db, tid, resolution)

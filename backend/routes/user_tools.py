"""Freeze + user-tools routes.

Freezing a flow turns it into a first-class ``UserTool`` (see
``user_tools_service``). These routes expose the freeze operation (plus its
inferred defaults) and CRUD over the resulting frozen tools.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from core.logging import get_logger
from database import UserTool
from flow_service import get_flow_or_404
from user_tools_service import (
    freeze_flow_to_tool,
    infer_freeze_defaults,
    list_backing_tools_with_drift,
    update_user_tool,
)

log = get_logger(__name__)

router = APIRouter(tags=["user-tools"])


class FreezeFlowRequest(BaseModel):
    name: str
    description: Optional[str] = None
    task_types: List[str]
    output_map: Dict[str, str] = {}
    hitl_policies: Dict[str, Any] = {}


class UpdateUserToolRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    task_types: Optional[List[str]] = None
    output_map: Optional[Dict[str, str]] = None
    hitl_policies: Optional[Dict[str, Any]] = None
    # When true, re-capture the backing flow's program + inputs (logic changes
    # made in the flow propagate into the tool). Keeps the stable tool id.
    resync_from_flow: bool = False


@router.post("/api/flows/{flow_id}/freeze")
async def freeze_flow(
    flow_id: int,
    request: FreezeFlowRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Freeze a flow into a first-class tool. 400 on validation errors."""
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not request.task_types:
        raise HTTPException(status_code=400, detail="task_types is required")

    try:
        tool = await freeze_flow_to_tool(
            session,
            flow_id=flow_id,
            name=name,
            description=request.description,
            task_types=request.task_types,
            output_map=request.output_map,
            hitl_policies=request.hitl_policies,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return tool.to_dict()


@router.get("/api/flows/{flow_id}/freeze-defaults")
async def freeze_defaults(
    flow_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Best-effort inferred freeze settings (task_types + output_map)."""
    flow = await get_flow_or_404(session, flow_id)
    return infer_freeze_defaults(flow.to_dict())


@router.get("/api/flows/{flow_id}/tools")
async def list_flow_backing_tools(
    flow_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """List the frozen tools backed by this flow, each annotated with
    ``has_changes`` (the flow drifted from the tool's snapshot). Lets the flow
    view surface an unsaved-changes dot + offer 'Update <tool>' only when there
    is actually something to resync."""
    return await list_backing_tools_with_drift(session, flow_id)


@router.get("/api/user-tools")
async def list_user_tools(
    session: AsyncSession = Depends(get_db_session),
):
    """List all frozen tools (deleted_at IS NULL)."""
    result = await session.execute(
        select(UserTool)
        .where(UserTool.deleted_at.is_(None))
        .order_by(UserTool.created_at.desc())
    )
    return [row.to_dict() for row in result.scalars().all()]


@router.get("/api/user-tools/{tool_id}")
async def get_user_tool(
    tool_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Fetch a single frozen tool (for the editor)."""
    tool = (
        await session.execute(
            select(UserTool).where(
                UserTool.id == tool_id, UserTool.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="User tool not found")
    return tool.to_dict()


@router.delete("/api/user-tools/{tool_id}")
async def delete_user_tool(
    tool_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Soft-delete a frozen tool and refresh the provider."""
    result = await session.execute(
        select(UserTool).where(
            UserTool.id == tool_id, UserTool.deleted_at.is_(None)
        )
    )
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="User tool not found")

    tool.deleted_at = datetime.utcnow()
    await session.commit()

    # Drop the tool from the live tool namespace.
    try:
        from providers import user_tools as user_tools_provider

        await user_tools_provider.refresh()
    except Exception as e:  # noqa: BLE001 — provider refresh is best-effort
        log.warning(f"UserToolsProvider refresh after delete skipped: {e}")

    return {"success": True, "id": tool_id}


@router.patch("/api/user-tools/{tool_id}")
async def patch_user_tool(
    tool_id: int,
    request: UpdateUserToolRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Update a frozen tool's freeze settings **in place** (stable id). 400 on invalid."""
    if request.name is not None and not request.name.strip():
        raise HTTPException(status_code=400, detail="name cannot be empty")
    try:
        tool = await update_user_tool(
            session,
            user_tool_id=tool_id,
            name=request.name.strip() if request.name is not None else None,
            description=request.description,
            task_types=request.task_types,
            output_map=request.output_map,
            hitl_policies=request.hitl_policies,
            resync_from_flow=request.resync_from_flow,
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    return tool.to_dict()


@router.post("/api/user-tools/{tool_id}/resync")
async def resync_user_tool(
    tool_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Re-capture the backing flow's program + inputs into this tool, in place.

    One-click 'update tool from this flow' — keeps the tool's settings, name,
    and stable id (so pins / presets survive). 400 if the tool has no backing
    flow or the refreshed interface is invalid; 404 if the tool is gone."""
    try:
        tool = await update_user_tool(
            session, user_tool_id=tool_id, resync_from_flow=True
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    return tool.to_dict()

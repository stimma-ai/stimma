"""Timeline document routes: create, read working state, append ops, undo/redo, save."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from asset_service import AssetServiceError
from core.dependencies import get_db_session
from core.logging import get_logger
from database import Asset, MediaItem
from timeline import TimelineOpError, TimelineStoreError
from timeline import service as timeline_service
from timeline.store import run_store

router = APIRouter(prefix="/api/timelines", tags=["timelines"])
log = get_logger(__name__)


class TimelineCreateRequest(BaseModel):
    title: str = ""
    fps: float = 30
    width: int = 1920
    height: int = 1080


class TimelineOpRequest(BaseModel):
    op: str
    args: Dict[str, Any] = Field(default_factory=dict)


class TimelineOpsRequest(BaseModel):
    ops: List[TimelineOpRequest]
    label: Optional[str] = None


class TimelineSaveRequest(BaseModel):
    note: Optional[str] = None


def _raise_for(error: Exception) -> None:
    if isinstance(error, (TimelineOpError, TimelineStoreError)):
        raise HTTPException(status_code=400, detail=str(error))
    if isinstance(error, AssetServiceError):
        raise HTTPException(status_code=404, detail=str(error))
    raise error


async def _media_summaries(session: AsyncSession, state: Optional[dict]) -> dict:
    if not state:
        return {}
    media_ids = {
        entry["media"]["media_id"]
        for track in state["tracks"]
        for entry in track["entries"]
        if entry["kind"] == "clip"
    }
    if not media_ids:
        return {}
    rows = await session.execute(select(MediaItem).where(MediaItem.id.in_(media_ids)))
    return {
        str(item.id): {
            "id": item.id,
            "file_hash": item.file_hash,
            "file_format": item.file_format,
            "width": item.width,
            "height": item.height,
            "duration": item.duration,
        }
        for item in rows.scalars().all()
    }


@router.post("")
async def create_timeline(
    request: TimelineCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        result = await timeline_service.create_timeline_asset(
            session,
            title=request.title,
            fps=request.fps,
            width=request.width,
            height=request.height,
            author="user",
        )
    except (TimelineOpError, TimelineStoreError, AssetServiceError) as error:
        _raise_for(error)
    from telemetry import get_telemetry_client

    get_telemetry_client().track("timeline_created", {"actor": "user"}, category="library")
    return result


@router.get("/{asset_id}")
async def get_timeline(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.asset_type != "timeline":
        raise HTTPException(status_code=404, detail=f"No timeline asset {asset_id}")
    try:
        _, project = await timeline_service.get_project_for_asset(session, asset_id)
        state = await run_store(project.state)
        status = await run_store(project.status)
    except (TimelineOpError, TimelineStoreError, AssetServiceError) as error:
        _raise_for(error)
    return {
        "asset_id": asset_id,
        "state": state,
        "media": await _media_summaries(session, state),
        **status,
    }


@router.post("/{asset_id}/ops")
async def append_timeline_ops(
    asset_id: int,
    request: TimelineOpsRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if not request.ops:
        raise HTTPException(status_code=400, detail="No ops provided")
    try:
        result = await timeline_service.apply_ops(
            session,
            asset_id=asset_id,
            ops=[(item.op, item.args) for item in request.ops],
            author="user",
            label=request.label,
        )
    except (TimelineOpError, TimelineStoreError, AssetServiceError) as error:
        _raise_for(error)
    result["media"] = await _media_summaries(session, result.get("state"))
    return result


@router.post("/{asset_id}/undo")
async def undo_timeline(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        result = await timeline_service.undo(session, asset_id=asset_id)
    except (TimelineOpError, TimelineStoreError, AssetServiceError) as error:
        _raise_for(error)
    result["media"] = await _media_summaries(session, result.get("state"))
    return result


@router.post("/{asset_id}/redo")
async def redo_timeline(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        result = await timeline_service.redo(session, asset_id=asset_id)
    except (TimelineOpError, TimelineStoreError, AssetServiceError) as error:
        _raise_for(error)
    result["media"] = await _media_summaries(session, result.get("state"))
    return result


@router.post("/{asset_id}/save")
async def save_timeline(
    asset_id: int,
    request: TimelineSaveRequest,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        return await timeline_service.save_revision(
            session, asset_id=asset_id, note=request.note
        )
    except (TimelineOpError, TimelineStoreError, AssetServiceError) as error:
        _raise_for(error)

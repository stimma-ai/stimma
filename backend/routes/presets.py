"""
API routes for preset management (Toolsv3).

Presets are saved parameter configurations for tools.
"""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import Preset, MediaItem
from core.dependencies import get_db_session
from core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/presets", tags=["presets"])


# --- Request/Response Models ---

class PresetCreate(BaseModel):
    """Request body for creating a preset."""
    name: str
    tool_id: str  # Full tool ID: "builtin:ComfyUI:qwen-image:text-to-image"
    state: Optional[dict] = None
    pinned: bool = False


class PresetUpdate(BaseModel):
    """Request body for updating a preset."""
    name: Optional[str] = None
    state: Optional[dict] = None
    pinned: Optional[bool] = None
    pin_order: Optional[int] = None


class PresetResponse(BaseModel):
    """Response model for a preset."""
    id: int
    name: str
    tool_id: str
    state: dict
    pinned: bool
    pin_order: Optional[int]
    created_at: str
    updated_at: str
    last_used_at: Optional[str]
    usage_count: int


# --- Routes ---

@router.get("", response_model=List[PresetResponse])
async def list_presets(
    tool_id: Optional[str] = Query(None, description="Filter by tool ID"),
    pinned_only: bool = Query(False, description="Only return pinned presets"),
    session: AsyncSession = Depends(get_db_session),
):
    """List all presets."""
    query = select(Preset).where(
        Preset.deleted_at.is_(None),
    )

    if tool_id:
        query = query.where(Preset.tool_id == tool_id)

    if pinned_only:
        query = query.where(Preset.pinned == True)

    # Order by pin_order for pinned, then by last_used_at
    query = query.order_by(
        Preset.pinned.desc(),
        Preset.pin_order.asc().nulls_last(),
        Preset.last_used_at.desc().nulls_last(),
    )

    result = await session.execute(query)
    presets = result.scalars().all()

    return [preset.to_dict() for preset in presets]


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a specific preset by ID."""
    result = await session.execute(
        select(Preset).where(
            and_(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None),
            )
        )
    )
    preset = result.scalar_one_or_none()

    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    return preset.to_dict()


@router.post("", response_model=PresetResponse)
async def create_preset(
    data: PresetCreate,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new preset."""
    preset = Preset(
        name=data.name,
        tool_id=data.tool_id,
        state=json.dumps(data.state) if data.state else None,
        pinned=data.pinned,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    session.add(preset)
    await session.commit()
    await session.refresh(preset)

    log.info("preset created", preset_id=preset.id, tool_id=data.tool_id)

    from telemetry import get_telemetry_client
    get_telemetry_client().track("tool_preset_saved", {"toolId": data.tool_id})

    return preset.to_dict()


@router.put("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: int,
    data: PresetUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    """Update an existing preset."""
    result = await session.execute(
        select(Preset).where(
            and_(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None),
            )
        )
    )
    preset = result.scalar_one_or_none()

    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Update fields if provided
    if data.name is not None:
        preset.name = data.name
    if data.state is not None:
        preset.state = json.dumps(data.state)
    if data.pinned is not None:
        preset.pinned = data.pinned
    if data.pin_order is not None:
        preset.pin_order = data.pin_order

    preset.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(preset)

    log.info("preset updated", preset_id=preset_id)
    return preset.to_dict()


@router.delete("/{preset_id}")
async def delete_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Soft delete a preset."""
    result = await session.execute(
        select(Preset).where(
            and_(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None),
            )
        )
    )
    preset = result.scalar_one_or_none()

    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Soft delete
    preset.deleted_at = datetime.utcnow()
    await session.commit()

    log.info("preset deleted", preset_id=preset_id)
    return {"status": "deleted", "id": preset_id}


@router.post("/{preset_id}/use")
async def use_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Mark a preset as used (updates last_used_at and usage_count).

    Call this when the user loads/applies a preset.
    """
    result = await session.execute(
        select(Preset).where(
            and_(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None),
            )
        )
    )
    preset = result.scalar_one_or_none()

    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    preset.last_used_at = datetime.utcnow()
    preset.usage_count = (preset.usage_count or 0) + 1
    await session.commit()

    from telemetry import get_telemetry_client
    get_telemetry_client().track("tool_preset_applied", {"toolId": preset.tool_id})

    return {"status": "ok", "usage_count": preset.usage_count}


@router.post("/{preset_id}/duplicate", response_model=PresetResponse)
async def duplicate_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Create a copy of an existing preset."""
    result = await session.execute(
        select(Preset).where(
            and_(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None),
            )
        )
    )
    original = result.scalar_one_or_none()

    if not original:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Create copy with new name
    new_preset = Preset(
        name=f"{original.name} (copy)",
        tool_id=original.tool_id,
        state=original.state,
        pinned=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    session.add(new_preset)
    await session.commit()
    await session.refresh(new_preset)

    log.info("preset duplicated", original_id=preset_id, new_id=new_preset.id)
    return new_preset.to_dict()


class PresetStatsResponse(BaseModel):
    """Response for preset usage statistics."""
    preset_id: int
    applied_count: int  # Existing: how many times the preset was loaded/applied
    generated_count: int  # New: how many media items were created with this preset
    last_generated_at: Optional[str] = None


@router.get("/{preset_id}/stats", response_model=PresetStatsResponse)
async def get_preset_stats(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """
    Get usage statistics for a preset.

    Returns:
        - applied_count: Number of times the preset was loaded/applied (existing usage_count)
        - generated_count: Number of media items created with this preset active
        - last_generated_at: Timestamp of most recent generation with this preset
    """
    # Get the preset to access its usage_count
    result = await session.execute(
        select(Preset).where(
            and_(
                Preset.id == preset_id,
                Preset.deleted_at.is_(None),
            )
        )
    )
    preset = result.scalar_one_or_none()

    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    # Count media items created with this preset
    count_result = await session.execute(
        select(func.count(MediaItem.id))
        .where(MediaItem.preset_id == preset_id)
        .where(MediaItem.deleted_at.is_(None))
    )
    generated_count = count_result.scalar() or 0

    # Get most recent generation with this preset
    last_result = await session.execute(
        select(MediaItem.indexed_date)
        .where(MediaItem.preset_id == preset_id)
        .where(MediaItem.deleted_at.is_(None))
        .order_by(MediaItem.indexed_date.desc())
        .limit(1)
    )
    last_row = last_result.first()
    last_generated_at = last_row[0].isoformat() if last_row and last_row[0] else None

    return PresetStatsResponse(
        preset_id=preset_id,
        applied_count=preset.usage_count or 0,
        generated_count=generated_count,
        last_generated_at=last_generated_at,
    )

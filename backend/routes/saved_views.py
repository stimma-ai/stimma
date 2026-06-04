"""Saved views management routes."""
import json
from core.logging import get_logger
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SavedView
from core.dependencies import get_db_session
from models.api_models import SavedViewResponse, SavedViewCreateRequest, SavedViewUpdateRequest, SavedViewReorderRequest
from sqlalchemy import func
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/saved-views", tags=["saved-views"])
log = get_logger(__name__)


@router.get("", response_model=List[SavedViewResponse])
async def get_saved_views(
    session: AsyncSession = Depends(get_db_session)
):
    """Get all saved views, sorted by display_order."""
    result = await session.execute(
        select(SavedView)
        .order_by(SavedView.display_order.asc(), SavedView.name.asc())
    )
    saved_views = result.scalars().all()

    return [SavedViewResponse(**sv.to_dict()) for sv in saved_views]


@router.post("", response_model=SavedViewResponse)
async def create_saved_view(
    request: SavedViewCreateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Create a new saved view."""
    try:
        log.debug(f"Creating saved view: {request}")

        # Check for duplicate name
        existing = await session.execute(
            select(SavedView)
            .where(SavedView.name == request.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="A view with this name already exists")

        # Get the max display_order to add at the end
        max_order_result = await session.execute(
            select(func.max(SavedView.display_order))
        )
        max_order = max_order_result.scalar() or 0

        saved_view = SavedView(
            name=request.name,
            filters=json.dumps(request.filters),
            sort_by=request.sort_by,
            display_order=max_order + 1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(saved_view)
        await session.commit()
        await session.refresh(saved_view)
        log.info(f"Saved view created: {saved_view.id}")

        response = SavedViewResponse(**saved_view.to_dict())

        # Broadcast WebSocket event
        await ws_manager.broadcast("saved_view_created", {
            "saved_view": response.model_dump()
        })

        from telemetry import get_telemetry_client
        get_telemetry_client().track("saved_view_created")

        return response
    except Exception as e:
        log.error(f"Error creating saved view: {e}", exc_info=True)
        raise


@router.get("/{view_id}", response_model=SavedViewResponse)
async def get_saved_view(
    view_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get a specific saved view."""
    result = await session.execute(
        select(SavedView)
        .where(SavedView.id == view_id)
    )
    saved_view = result.scalar_one_or_none()

    if not saved_view:
        raise HTTPException(status_code=404, detail="Saved view not found")

    return SavedViewResponse(**saved_view.to_dict())


@router.put("/{view_id}", response_model=SavedViewResponse)
async def update_saved_view(
    view_id: int,
    request: SavedViewUpdateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Update a saved view."""
    result = await session.execute(
        select(SavedView)
        .where(SavedView.id == view_id)
    )
    saved_view = result.scalar_one_or_none()

    if not saved_view:
        raise HTTPException(status_code=404, detail="Saved view not found")

    if request.name is not None and request.name != saved_view.name:
        # Check for duplicate name
        existing = await session.execute(
            select(SavedView)
            .where(SavedView.name == request.name)
            .where(SavedView.id != view_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="A view with this name already exists")
        saved_view.name = request.name
    if request.filters is not None:
        saved_view.filters = json.dumps(request.filters)
    if request.sort_by is not None:
        saved_view.sort_by = request.sort_by

    saved_view.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(saved_view)

    response = SavedViewResponse(**saved_view.to_dict())

    # Broadcast WebSocket event
    await ws_manager.broadcast("saved_view_updated", {
        "saved_view": response.model_dump()
    })

    return response


@router.delete("/{view_id}")
async def delete_saved_view(
    view_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Delete a saved view."""
    try:
        log.debug(f"Deleting saved view: {view_id}")

        result = await session.execute(
            select(SavedView)
            .where(SavedView.id == view_id)
        )
        saved_view = result.scalar_one_or_none()
        log.debug(f"Found saved view: {saved_view}")

        if not saved_view:
            raise HTTPException(status_code=404, detail="Saved view not found")

        await session.delete(saved_view)
        await session.commit()
        log.info(f"Deleted saved view: {view_id}")

        # Broadcast WebSocket event
        await ws_manager.broadcast("saved_view_deleted", {
            "view_id": view_id
        })

        return {"status": "success", "message": "Saved view deleted"}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting saved view: {e}", exc_info=True)
        raise


@router.post("/{view_id}/reorder", response_model=List[SavedViewResponse])
async def reorder_saved_view(
    view_id: int,
    request: SavedViewReorderRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Move a saved view up or down in the display order."""
    if request.direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="Direction must be 'up' or 'down'")

    # Get all saved views, ordered by display_order
    result = await session.execute(
        select(SavedView)
        .order_by(SavedView.display_order.asc(), SavedView.name.asc())
    )
    views = list(result.scalars().all())

    # Find the view to move
    current_index = None
    for i, v in enumerate(views):
        if v.id == view_id:
            current_index = i
            break

    if current_index is None:
        raise HTTPException(status_code=404, detail="Saved view not found")

    # Calculate new index
    if request.direction == "up" and current_index > 0:
        new_index = current_index - 1
    elif request.direction == "down" and current_index < len(views) - 1:
        new_index = current_index + 1
    else:
        # Already at top/bottom, no change needed
        return [SavedViewResponse(**v.to_dict()) for v in views]

    # Swap the views
    views[current_index], views[new_index] = views[new_index], views[current_index]

    # Update display_order for all views
    for i, v in enumerate(views):
        v.display_order = i

    await session.commit()

    # Broadcast reorder event with updated list
    await ws_manager.broadcast("saved_views_reordered", {
        "saved_views": [SavedViewResponse(**v.to_dict()).model_dump() for v in views]
    })

    return [SavedViewResponse(**v.to_dict()) for v in views]

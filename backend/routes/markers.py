"""Marker management routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from database import MediaMarker, Marker, MediaItem
from config import get_settings
from core.dependencies import get_db_session
from core.profile_context import get_current_profile
from models.api_models import MarkerResponse, BulkMarkerRequest
from utils.websocket import ws_manager, broadcast_media_updated
from utils.background_tasks import clear_auto_delete_for_media


async def _get_active_markers(session, media_id: int) -> list:
    """Get active (non-suppressed) markers for a media item."""
    result = await session.execute(
        select(Marker)
        .join(MediaMarker, MediaMarker.marker_id == Marker.id)
        .where(MediaMarker.media_id == media_id)
        .where(MediaMarker.source != 'suppressed')
    )
    return [MarkerResponse(**m.to_dict()).dict() for m in result.scalars().all()]

router = APIRouter(prefix="/api", tags=["markers"])

@router.get("/markers", response_model=List[MarkerResponse])
async def get_markers(session: AsyncSession = Depends(get_db_session)):
    """Get all available markers in config order."""
    # Get markers from database
    result = await session.execute(select(Marker))
    db_markers = {m.config_id: m for m in result.scalars().all()}

    # Get config order for current profile
    settings = get_settings()
    profile_id = get_current_profile()
    config_markers = settings.get_markers_for_profile(profile_id)

    # Return markers in config order
    ordered_markers = []
    for config_marker in config_markers:
        db_marker = db_markers.get(config_marker.id)
        if db_marker:
            ordered_markers.append(MarkerResponse(**db_marker.to_dict()))

    return ordered_markers


@router.get("/markers/recently-marked-media")
async def get_recently_marked_media(
    page_size: int = Query(default=12, le=50),
    session: AsyncSession = Depends(get_db_session)
):
    """Get media items sorted by most recent marker assignment date."""
    from routes.media import MediaItemResponse

    # Subquery: for each media item, get the most recent marker assignment time
    latest_mark = (
        select(
            MediaMarker.media_id,
            func.max(MediaMarker.created_at).label('latest_marked_at')
        )
        .where(MediaMarker.source != 'suppressed')
        .group_by(MediaMarker.media_id)
        .subquery()
    )

    # Join with MediaItem, exclude deleted/hidden, order by most recently marked
    query = (
        select(MediaItem)
        .join(latest_mark, MediaItem.id == latest_mark.c.media_id)
        .where(MediaItem.deleted_at.is_(None))
        .where(MediaItem.superseded_by.is_(None))
        .where(MediaItem.file_hash.isnot(None))
        .order_by(latest_mark.c.latest_marked_at.desc())
        .limit(page_size)
    )

    result = await session.execute(query)
    items = result.scalars().all()

    media_items = [MediaItemResponse(**item.to_dict()) for item in items]
    return {"items": media_items}


@router.get("/media/{media_id}/markers")
async def get_media_markers(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get all markers for a specific media item."""
    result = await session.execute(
        select(Marker)
        .join(MediaMarker, MediaMarker.marker_id == Marker.id)
        .where(MediaMarker.media_id == media_id)
        .where(MediaMarker.source != 'suppressed')
    )
    markers = result.scalars().all()
    return [MarkerResponse(**m.to_dict()) for m in markers]


@router.post("/media/markers/batch-get")
async def batch_get_media_markers(
    media_ids: List[int],
    session: AsyncSession = Depends(get_db_session)
):
    """Get markers for multiple media items at once. Returns {media_id: [markers]}."""
    if not media_ids:
        return {}

    result = await session.execute(
        select(MediaMarker.media_id, Marker)
        .join(Marker, MediaMarker.marker_id == Marker.id)
        .where(MediaMarker.media_id.in_(media_ids))
        .where(MediaMarker.source != 'suppressed')
    )
    rows = result.all()

    # Group markers by media_id
    markers_by_media = {mid: [] for mid in media_ids}
    for media_id, marker in rows:
        markers_by_media[media_id].append(MarkerResponse(**marker.to_dict()).dict())

    return markers_by_media


@router.post("/media/{media_id}/markers/{marker_id}")
async def add_marker_to_media(
    media_id: int,
    marker_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Add a marker to a media item."""
    # Verify media exists (lightweight check - don't load full row with clip_embedding)
    media_exists = await session.execute(
        select(MediaItem.id).where(MediaItem.id == media_id)
    )
    if not media_exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")

    # Verify marker exists
    marker_result = await session.execute(select(Marker).where(Marker.id == marker_id))
    marker = marker_result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    # Check if already exists
    existing_result = await session.execute(
        select(MediaMarker).where(
            and_(MediaMarker.media_id == media_id, MediaMarker.marker_id == marker_id)
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        if existing.source == 'manual':
            markers = await _get_active_markers(session, media_id)
            return {"status": "already_exists", "message": "Marker already added to media", "markers": markers}
        # If suppressed or auto, upgrade to manual
        existing.source = 'manual'
        await session.commit()
    else:
        # Add marker with manual source
        media_marker = MediaMarker(media_id=media_id, marker_id=marker_id, source='manual')
        session.add(media_marker)
        await session.commit()

    # Clear auto-delete for marked item
    await clear_auto_delete_for_media(session, [media_id], ws_manager)

    # Broadcast media_updated event with full media object
    media_result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = media_result.scalar_one_or_none()
    if media:
        await broadcast_media_updated(media, ["markers"], session)

    # Return updated markers so frontend can skip a separate GET
    markers = await _get_active_markers(session, media_id)
    return {"status": "success", "message": "Marker added to media", "markers": markers}


@router.delete("/media/{media_id}/markers/{marker_id}")
async def remove_marker_from_media(
    media_id: int,
    marker_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Remove a marker from a media item."""
    # Get marker info before deletion for the broadcast
    marker_result = await session.execute(select(Marker).where(Marker.id == marker_id))
    marker = marker_result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    result = await session.execute(
        select(MediaMarker).where(
            and_(MediaMarker.media_id == media_id, MediaMarker.marker_id == marker_id)
        )
    )
    media_marker = result.scalar_one_or_none()

    if not media_marker:
        raise HTTPException(status_code=404, detail="Marker not found on media")

    if media_marker.source == 'auto':
        # Auto-marker: suppress instead of delete
        media_marker.source = 'suppressed'
        await session.commit()
    else:
        # Manual or suppressed: delete entirely
        await session.delete(media_marker)
        await session.commit()

    # Fetch the media item for the broadcast
    media_result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = media_result.scalar_one_or_none()

    # Broadcast media_updated event with full media object
    if media:
        await broadcast_media_updated(media, ["markers"], session)

    # Return updated markers so frontend can skip a separate GET
    markers = await _get_active_markers(session, media_id)
    return {"status": "success", "message": "Marker removed from media", "markers": markers}


@router.post("/media/batch/markers")
async def bulk_marker_operation(
    request: BulkMarkerRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Bulk add or remove markers from multiple media items."""
    # Verify marker exists
    marker_result = await session.execute(select(Marker).where(Marker.id == request.marker_id))
    marker = marker_result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    if request.add:
        # Add markers
        added = 0
        for media_id in request.media_ids:
            # Check if already exists
            existing_result = await session.execute(
                select(MediaMarker).where(
                    and_(MediaMarker.media_id == media_id, MediaMarker.marker_id == request.marker_id)
                )
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                if existing.source != 'manual':
                    # Upgrade suppressed/auto to manual
                    existing.source = 'manual'
                    added += 1
            else:
                media_marker = MediaMarker(media_id=media_id, marker_id=request.marker_id, source='manual')
                session.add(media_marker)
                added += 1

        await session.commit()

        # Clear auto-delete for marked items (only if markers were added)
        if added > 0:
            await clear_auto_delete_for_media(session, request.media_ids, ws_manager)

        # Fetch all affected media items and broadcast updates
        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(request.media_ids))
        )
        media_items = media_result.scalars().all()
        await broadcast_media_updated(media_items, ["markers"], session)

        if added > 0:
            from telemetry import get_telemetry_client
            get_telemetry_client().track("media_marked", {
                "count": added,
                "markerName": marker.name,
            })

        return {"status": "success", "added": added, "total": len(request.media_ids)}
    else:
        # Remove markers
        removed = 0
        for media_id in request.media_ids:
            result = await session.execute(
                select(MediaMarker).where(
                    and_(MediaMarker.media_id == media_id, MediaMarker.marker_id == request.marker_id)
                )
            )
            media_marker = result.scalar_one_or_none()
            if media_marker:
                if media_marker.source == 'auto':
                    # Auto-marker: suppress instead of delete
                    media_marker.source = 'suppressed'
                else:
                    # Manual or suppressed: delete entirely
                    await session.delete(media_marker)
                removed += 1

        await session.commit()

        # Fetch all affected media items and broadcast updates
        media_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(request.media_ids))
        )
        media_items = media_result.scalars().all()
        await broadcast_media_updated(media_items, ["markers"], session)

        return {"status": "success", "removed": removed, "total": len(request.media_ids)}


# ===== TAGS =====


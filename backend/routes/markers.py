"""Marker management routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from database import Asset, AssetMarker, AssetRevision, Marker, MediaItem, MediaMarker
from config import get_settings
from core.dependencies import get_db_session
from core.profile_context import get_current_profile
from models.api_models import MarkerResponse, BulkMarkerRequest
from utils.websocket import ws_manager
from asset_association_service import media_compatibility_projections


async def _get_active_markers(session, media_id: int) -> list:
    """Compatibility projection of canonical Asset markers by Media id."""
    from asset_association_service import asset_for_media

    asset = await asset_for_media(session, media_id)
    if asset is None:
        return []
    rows = (
        await session.execute(
            select(AssetMarker, Marker)
            .join(Marker, Marker.id == AssetMarker.marker_id)
            .where(
                AssetMarker.asset_id == asset.id,
                AssetMarker.deleted_at.is_(None),
                AssetMarker.source != "suppressed",
            )
        )
    ).all()
    return [
        {**MarkerResponse(**marker.to_dict()).dict(), "source": association.source}
        for association, marker in rows
    ]

router = APIRouter(prefix="/api", tags=["markers"])


async def _broadcast_marker_update(
    session: AsyncSession, media_id: int, asset_id: int, markers: list[dict]
) -> None:
    media = await session.get(MediaItem, media_id)
    if media is not None:
        projection = (await media_compatibility_projections(session, [media]))[0]
        await ws_manager.broadcast(
            "media_updated",
            {
                "media_id": media_id,
                "asset_id": asset_id,
                "fields": ["markers"],
                "media": {**projection, "asset_id": asset_id, "markers": markers},
            },
        )
    await ws_manager.broadcast(
        "assets_updated", {"asset_ids": [asset_id], "fields": ["markers"]}
    )

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

    # Subquery: for each Asset, get the most recent marker assignment time.
    latest_mark = (
        select(
            AssetMarker.asset_id,
            func.max(AssetMarker.created_at).label('latest_marked_at')
        )
        .where(
            AssetMarker.deleted_at.is_(None),
            AssetMarker.source != "suppressed",
        )
        .group_by(AssetMarker.asset_id)
        .subquery()
    )

    # Return current payloads while retaining explicit Asset identity.
    query = (
        select(Asset, AssetRevision, MediaItem)
        .join(latest_mark, Asset.id == latest_mark.c.asset_id)
        .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
        .where(
            Asset.state == "active",
            Asset.deleted_at.is_(None),
            AssetRevision.deleted_at.is_(None),
            MediaItem.deleted_at.is_(None),
        )
        .where(MediaItem.file_hash.isnot(None))
        .order_by(latest_mark.c.latest_marked_at.desc())
        .limit(page_size)
    )

    rows = (await session.execute(query)).all()
    projections = await media_compatibility_projections(
        session, [media for _, _, media in rows]
    )
    media_items = [MediaItemResponse(**item) for item in projections]
    return {"items": media_items}


@router.get("/media/{media_id}/markers")
async def get_media_markers(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get all markers for a specific media item."""
    return await _get_active_markers(session, media_id)


@router.post("/media/markers/batch-get")
async def batch_get_media_markers(
    media_ids: List[int],
    session: AsyncSession = Depends(get_db_session)
):
    """Get markers for multiple media items at once. Returns {media_id: [markers]}."""
    if not media_ids:
        return {}

    return {
        media_id: await _get_active_markers(session, media_id)
        for media_id in media_ids
    }


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

    from asset_association_service import (
        asset_for_media,
        mirror_media_associations_to_asset,
        set_asset_marker,
    )

    asset = await asset_for_media(
        session, media_id, promote=True, origin_type="marker_promotion"
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    await mirror_media_associations_to_asset(
        session, media_id=media_id, asset_id=asset.id
    )
    changed = await set_asset_marker(
        session, asset_id=asset.id, marker_id=marker_id, add=True
    )
    await session.commit()
    markers = await _get_active_markers(session, media_id)
    await _broadcast_marker_update(session, media_id, asset.id, markers)
    return {
        "status": "success" if changed else "already_exists",
        "message": "Marker added to Asset",
        "asset_id": asset.id,
        "markers": markers,
    }


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

    from asset_association_service import (
        asset_for_media,
        mirror_media_associations_to_asset,
        set_asset_marker,
    )

    legacy_row = await session.scalar(
        select(MediaMarker).where(
            MediaMarker.media_id == media_id,
            MediaMarker.marker_id == marker_id,
        )
    )
    asset = await asset_for_media(
        session,
        media_id,
        promote=legacy_row is not None,
        origin_type="marker_migration",
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Marker not found on Asset")
    await mirror_media_associations_to_asset(
        session, media_id=media_id, asset_id=asset.id
    )
    if not await set_asset_marker(
        session, asset_id=asset.id, marker_id=marker_id, add=False
    ):
        raise HTTPException(status_code=404, detail="Marker not found on Asset")
    await session.commit()
    markers = await _get_active_markers(session, media_id)
    await _broadcast_marker_update(session, media_id, asset.id, markers)
    return {"status": "success", "message": "Marker removed from Asset", "markers": markers}


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

    from asset_association_service import (
        asset_ids_for_media_ids,
        mirror_media_associations_to_asset,
        set_asset_marker,
    )

    mapping = await asset_ids_for_media_ids(
        session,
        request.media_ids,
        promote=request.add,
        origin_type="marker_promotion",
    )
    changed = 0
    for media_id, asset_id in mapping.items():
        await mirror_media_associations_to_asset(
            session, media_id=media_id, asset_id=asset_id
        )
        changed += int(
            await set_asset_marker(
                session,
                asset_id=asset_id,
                marker_id=request.marker_id,
                add=request.add,
            )
        )
    await session.commit()
    for media_id, asset_id in mapping.items():
        markers = await _get_active_markers(session, media_id)
        await _broadcast_marker_update(session, media_id, asset_id, markers)

    if request.add:
        if changed > 0:
            from telemetry import get_telemetry_client
            from telemetry_props import marker_name_for_telemetry
            get_telemetry_client().track("media_marked", {
                "count": changed,
                # Catalog fix #4: shipped default names pass literally,
                # user-created/renamed markers egress as "custom".
                "markerName": marker_name_for_telemetry(marker.name),
            })

        return {"status": "success", "added": changed, "total": len(mapping)}
    return {"status": "success", "removed": changed, "total": len(mapping)}


# ===== TAGS =====

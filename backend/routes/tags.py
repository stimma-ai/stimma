"""Tag management routes."""
from core.logging import get_logger
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import AssetTag, MediaItem, MediaTag, Tag
from core.dependencies import get_db_session
from models.api_models import TagResponse, TagCreateRequest, BulkTagRequest
from utils.websocket import ws_manager
from asset_association_service import media_compatibility_projections

router = APIRouter(prefix="/api", tags=["tags"])
log = get_logger(__name__)


async def _asset_tags_for_media(session: AsyncSession, media_id: int) -> list[dict]:
    from asset_association_service import asset_for_media

    asset = await asset_for_media(session, media_id)
    if asset is None:
        return []
    tags = list(
        await session.scalars(
            select(Tag)
            .join(AssetTag, AssetTag.tag_id == Tag.id)
            .where(
                AssetTag.asset_id == asset.id,
                AssetTag.deleted_at.is_(None),
            )
            .order_by(Tag.tag_text)
        )
    )
    return [tag.to_dict() for tag in tags]


async def _broadcast_tag_update(
    session: AsyncSession, media_id: int, asset_id: int, tags: list[dict]
) -> None:
    media = await session.get(MediaItem, media_id)
    if media is not None:
        projection = (await media_compatibility_projections(session, [media]))[0]
        await ws_manager.broadcast(
            "media_updated",
            {
                "media_id": media_id,
                "asset_id": asset_id,
                "fields": ["tags"],
                "media": {**projection, "asset_id": asset_id, "tags": tags},
            },
        )
    await ws_manager.broadcast(
        "assets_updated", {"asset_ids": [asset_id], "fields": ["tags"]}
    )

@router.get("/tags", response_model=List[TagResponse])
async def get_tags(
    with_counts: bool = Query(False),
    session: AsyncSession = Depends(get_db_session)
):
    """Get all tags, optionally with usage counts."""
    if with_counts:
        # Get tags with usage counts
        query = select(
            Tag, func.count(AssetTag.asset_id).label("usage_count")
        ).outerjoin(
            AssetTag,
            (AssetTag.tag_id == Tag.id) & AssetTag.deleted_at.is_(None),
        )

        query = query.group_by(Tag.id).order_by(func.count(AssetTag.asset_id).desc())

        result = await session.execute(query)
        tags_with_counts = result.all()
        return [
            TagResponse(id=tag.id, tag=tag.tag_text, created_at=tag.created_at.isoformat(), usage_count=count)
            for tag, count in tags_with_counts
        ]
    else:
        # Simple tag list
        result = await session.execute(select(Tag).order_by(Tag.tag_text))
        tags = result.scalars().all()
        return [TagResponse(**t.to_dict()) for t in tags]


@router.post("/tags")
async def create_tag(
    tag_text: str = Body(..., embed=True),
    session: AsyncSession = Depends(get_db_session)
):
    """Create a new tag."""
    tag_text = tag_text.strip().lower()

    # Check if already exists
    result = await session.execute(select(Tag).where(Tag.tag_text == tag_text))
    existing_tag = result.scalar_one_or_none()

    if existing_tag:
        return TagResponse(**existing_tag.to_dict())

    # Create new tag
    tag = Tag(tag_text=tag_text)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    return TagResponse(**tag.to_dict())


@router.post("/media/batch/tags")
async def bulk_tag_operation(
    request: BulkTagRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Bulk add or remove tags from multiple media items."""
    log.info(f"Bulk tag operation: {request.media_ids}, add={request.tag_texts}, remove={request.remove_tag_ids}")
    from asset_association_service import (
        asset_ids_for_media_ids,
        mirror_media_associations_to_asset,
        set_asset_tag,
    )

    mapping = await asset_ids_for_media_ids(
        session,
        request.media_ids,
        promote=bool(request.tag_texts),
        origin_type="tag_promotion",
    )
    tags_to_add: list[Tag] = []
    for tag_text in request.tag_texts:
        normalized = tag_text.strip().lower()
        if not normalized:
            continue
        tag = await session.scalar(select(Tag).where(Tag.tag_text == normalized))
        if tag is None:
            tag = Tag(tag_text=normalized)
            session.add(tag)
            await session.flush()
        tags_to_add.append(tag)

    added_count = removed_count = 0
    for media_id, asset_id in mapping.items():
        await mirror_media_associations_to_asset(
            session, media_id=media_id, asset_id=asset_id
        )
        for tag in tags_to_add:
            added_count += int(
                await set_asset_tag(
                    session, asset_id=asset_id, tag_id=tag.id, add=True
                )
            )
        for tag_id in request.remove_tag_ids:
            removed_count += int(
                await set_asset_tag(
                    session, asset_id=asset_id, tag_id=tag_id, add=False
                )
            )
    await session.commit()
    for media_id, asset_id in mapping.items():
        await _broadcast_tag_update(
            session, media_id, asset_id, await _asset_tags_for_media(session, media_id)
        )

    if added_count > 0 or removed_count > 0:
        from telemetry import get_telemetry_client
        get_telemetry_client().track("media_tagged", {
            "added": added_count,
            "removed": removed_count,
        })

    return {
        "status": "success",
        "added": added_count,
        "removed": removed_count,
        "media_count": len(mapping)
    }


@router.post("/media/{media_id}/tags")
async def add_tags_to_media(
    media_id: int,
    request: TagCreateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Add tags to a media item, creating them if they don't exist."""
    # Verify media exists
    media_result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = media_result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Asset not found")

    from asset_association_service import (
        asset_for_media,
        mirror_media_associations_to_asset,
        set_asset_tag,
    )

    asset = await asset_for_media(
        session, media_id, promote=True, origin_type="tag_promotion"
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    await mirror_media_associations_to_asset(
        session, media_id=media_id, asset_id=asset.id
    )
    added_tags = []
    for tag_text in request.tags:
        tag_text = tag_text.strip().lower()
        if not tag_text:
            continue

        # Get or create tag
        result = await session.execute(select(Tag).where(Tag.tag_text == tag_text))
        tag = result.scalar_one_or_none()

        if not tag:
            tag = Tag(tag_text=tag_text)
            session.add(tag)
            await session.flush()  # Get the tag ID

        if await set_asset_tag(
            session, asset_id=asset.id, tag_id=tag.id, add=True
        ):
            added_tags.append(tag_text)

    await session.commit()
    await _broadcast_tag_update(
        session, media_id, asset.id, await _asset_tags_for_media(session, media_id)
    )
    return {
        "status": "success",
        "asset_id": asset.id,
        "added": added_tags,
        "total": len(request.tags),
    }


@router.delete("/media/{media_id}/tags/{tag_id}")
async def remove_tag_from_media(
    media_id: int,
    tag_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Remove a tag from a media item."""
    from asset_association_service import (
        asset_for_media,
        mirror_media_associations_to_asset,
        set_asset_tag,
    )

    legacy_row = await session.scalar(
        select(MediaTag).where(
            MediaTag.media_id == media_id,
            MediaTag.tag_id == tag_id,
        )
    )
    asset = await asset_for_media(
        session,
        media_id,
        promote=legacy_row is not None,
        origin_type="tag_migration",
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Tag not found on Asset")
    await mirror_media_associations_to_asset(
        session, media_id=media_id, asset_id=asset.id
    )
    if not await set_asset_tag(
        session, asset_id=asset.id, tag_id=tag_id, add=False
    ):
        raise HTTPException(status_code=404, detail="Tag not found on Asset")
    await session.commit()
    await _broadcast_tag_update(
        session, media_id, asset.id, await _asset_tags_for_media(session, media_id)
    )
    return {"status": "success", "message": "Tag removed from Asset"}


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Delete a tag (only if not in use)."""
    # Check if tag is in use
    result = await session.execute(
        select(func.count(AssetTag.asset_id)).where(
            AssetTag.tag_id == tag_id,
            AssetTag.deleted_at.is_(None),
        )
    )
    usage_count = result.scalar()

    if usage_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete tag: it is used by {usage_count} media items"
        )

    # Delete the tag
    tag_result = await session.execute(select(Tag).where(Tag.id == tag_id))
    tag = tag_result.scalar_one_or_none()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    await session.delete(tag)
    await session.commit()

    return {"status": "success", "message": "Tag deleted"}


# ===== COLLECTIONS =====

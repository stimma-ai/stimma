"""Tag management routes."""
from core.logging import get_logger
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select, func, delete as sql_delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem, MediaTag, Tag
from core.dependencies import get_db_session
from models.api_models import TagResponse, TagCreateRequest, BulkTagRequest
from utils.websocket import ws_manager, broadcast_media_updated
from utils.background_tasks import clear_auto_delete_for_media

router = APIRouter(prefix="/api", tags=["tags"])
log = get_logger(__name__)

@router.get("/tags", response_model=List[TagResponse])
async def get_tags(
    with_counts: bool = Query(False),
    session: AsyncSession = Depends(get_db_session)
):
    """Get all tags, optionally with usage counts."""
    if with_counts:
        # Get tags with usage counts
        query = (
            select(Tag, func.count(MediaTag.media_id).label('usage_count'))
            .outerjoin(MediaTag, Tag.id == MediaTag.tag_id)
        )

        query = query.group_by(Tag.id).order_by(func.count(MediaTag.media_id).desc())

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
    added_count = 0
    removed_count = 0

    # Add tags
    if request.tag_texts:
        for tag_text in request.tag_texts:
            tag_text = tag_text.strip().lower()
            if not tag_text:
                continue

            # Get or create tag
            result = await session.execute(select(Tag).where(Tag.tag_text == tag_text))
            tag = result.scalar_one_or_none()

            if not tag:
                tag = Tag(tag_text=tag_text)
                session.add(tag)
                await session.flush()

            # Add to all media items
            for media_id in request.media_ids:
                existing = await session.execute(
                    select(MediaTag).where(
                        and_(MediaTag.media_id == media_id, MediaTag.tag_id == tag.id)
                    )
                )
                if not existing.scalar_one_or_none():
                    media_tag = MediaTag(media_id=media_id, tag_id=tag.id)
                    session.add(media_tag)
                    added_count += 1

    # Remove tags
    if request.remove_tag_ids:
        for tag_id in request.remove_tag_ids:
            for media_id in request.media_ids:
                result = await session.execute(
                    select(MediaTag).where(
                        and_(MediaTag.media_id == media_id, MediaTag.tag_id == tag_id)
                    )
                )
                media_tag = result.scalar_one_or_none()
                if media_tag:
                    await session.delete(media_tag)
                    removed_count += 1

    await session.commit()

    # Clear auto-delete for tagged items (only if tags were added)
    if request.tag_texts and added_count > 0:
        await clear_auto_delete_for_media(session, request.media_ids, ws_manager)

    # Fetch all affected media items and broadcast updates
    media_result = await session.execute(
        select(MediaItem).where(MediaItem.id.in_(request.media_ids))
    )
    media_items = media_result.scalars().all()
    await broadcast_media_updated(media_items, ["tags"], session)

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
        "media_count": len(request.media_ids)
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

        # Check if already associated
        existing = await session.execute(
            select(MediaTag).where(
                and_(MediaTag.media_id == media_id, MediaTag.tag_id == tag.id)
            )
        )
        if not existing.scalar_one_or_none():
            media_tag = MediaTag(media_id=media_id, tag_id=tag.id)
            session.add(media_tag)
            added_tags.append(tag_text)

    await session.commit()

    # Clear auto-delete for tagged item (only if tags were added)
    if added_tags:
        await clear_auto_delete_for_media(session, [media_id], ws_manager)

    # Broadcast media_updated event
    await broadcast_media_updated(media, ["tags"], session)

    return {"status": "success", "added": added_tags, "total": len(request.tags)}


@router.delete("/media/{media_id}/tags/{tag_id}")
async def remove_tag_from_media(
    media_id: int,
    tag_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Remove a tag from a media item."""
    result = await session.execute(
        select(MediaTag).where(
            and_(MediaTag.media_id == media_id, MediaTag.tag_id == tag_id)
        )
    )
    media_tag = result.scalar_one_or_none()

    if not media_tag:
        raise HTTPException(status_code=404, detail="Tag not found on media")

    await session.delete(media_tag)
    await session.commit()

    # Fetch the media item and broadcast update
    media_result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = media_result.scalar_one_or_none()
    if media:
        await broadcast_media_updated(media, ["tags"], session)

    return {"status": "success", "message": "Tag removed from media"}


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Delete a tag (only if not in use)."""
    # Check if tag is in use
    result = await session.execute(
        select(func.count(MediaTag.media_id)).where(MediaTag.tag_id == tag_id)
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

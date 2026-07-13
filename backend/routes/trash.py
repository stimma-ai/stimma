"""Trash and delete management routes.

Simplified implementation: trashed files stay in place until trash is emptied.
The deleted_at timestamp marks items as trashed.
"""
from core.logging import get_logger
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, and_, literal, Integer, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.profile_context import get_current_profile
from database import AssetRevision, DeleteOperation, MediaItem, MediaMarker, MediaKeyword, Keyword, MediaTag, Tag
from core.dependencies import get_db_session
from delete_operations import (
    create_delete_operation,
    ensure_delete_worker_started,
    get_active_delete_operation,
    get_delete_operation,
    retry_delete_operation,
)
from models.api_models import BulkDeleteRequest, MediaListResponse, MediaItemResponse, BulkTrashRequest
from utils.query_builder import (
    build_filtered_query,
    IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS, TEXT_FORMATS,
    SET_FORMATS, GRID_FORMATS, LAYOUT_FORMATS, STRUCTURED_FORMATS,
    RESOLUTION_MAP,
)
from utils.websocket import ws_manager

router = APIRouter(prefix="/api", tags=["trash"])
log = get_logger(__name__)


async def _asset_revision_for_media(session: AsyncSession, media_id: int):
    return await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
        )
    )


@router.delete("/media/{media_id}")
async def delete_media(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Compatibility soft-delete for a payload or its uniquely mapped Asset."""
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = result.scalar_one_or_none()

    if not media:
        raise HTTPException(status_code=404, detail="Asset not found")

    if media.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Asset already deleted")

    deleted_ids = [media_id]

    asset_revision = await _asset_revision_for_media(session, media_id)
    if asset_revision is not None:
        from asset_service import trash_asset
        await trash_asset(session, asset_id=asset_revision.asset_id)

    # Soft delete the main item
    media.deleted_at = datetime.utcnow()
    media.auto_delete_at = None  # Clear expiration time
    await session.commit()

    # Broadcast delete events for all deleted items
    if len(deleted_ids) > 1:
        await ws_manager.broadcast("media_bulk_deleted", {"media_ids": deleted_ids})
    else:
        await ws_manager.broadcast("media_deleted", {"media_id": media_id})

    return {"status": "success", "message": "Asset moved to trash", "deleted_count": len(deleted_ids)}


@router.post("/media/batch/delete")
async def bulk_delete_media(
    request: BulkDeleteRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Compatibility bulk soft-delete without implicit containment cascades."""
    all_deleted_ids = []
    errors = []
    BATCH_SIZE = 500

    # Fetch all requested items in batches
    items_map = {}
    for i in range(0, len(request.media_ids), BATCH_SIZE):
        batch_ids = request.media_ids[i:i + BATCH_SIZE]
        result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(batch_ids))
        )
        items_map.update({m.id: m for m in result.scalars().all()})

    for media_id in request.media_ids:
        media = items_map.get(media_id)
        if not media:
            errors.append({"media_id": media_id, "error": "Not found"})
            continue
        if media.deleted_at is not None:
            errors.append({"media_id": media_id, "error": "Already deleted"})
            continue

        all_deleted_ids.append(media_id)

        asset_revision = await _asset_revision_for_media(session, media_id)
        if asset_revision is not None:
            from asset_service import trash_asset
            await trash_asset(session, asset_id=asset_revision.asset_id)

        # Soft delete - just set the timestamp
        media.deleted_at = datetime.utcnow()
        media.auto_delete_at = None

    await session.commit()

    # Broadcast event with all deleted IDs (including cascade deleted members)
    if all_deleted_ids:
        await ws_manager.broadcast("media_bulk_deleted", {
            "count": len(all_deleted_ids),
            "media_ids": all_deleted_ids
        })

        from telemetry import get_telemetry_client
        get_telemetry_client().track("media_deleted", {"count": len(all_deleted_ids)})

    return {
        "status": "success",
        "deleted": len(all_deleted_ids),
        "total": len(request.media_ids),
        "errors": errors
    }


@router.get("/trash", response_model=MediaListResponse)
async def get_trash(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=200),
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    similar_to_text: Optional[str] = Query(None, description="Text query to find visually similar images using CLIP text encoding"),
    similarity_threshold: Optional[float] = Query(None, description="Similarity threshold for filtering results (0.0-1.0)"),
    media_types: Optional[str] = Query(None, description="Comma-separated media types (images,videos,audio,text,sets,grids,layouts,structured) - OR logic"),
    excluded_media_types: Optional[str] = Query(None, description="Comma-separated media types to exclude - NOT logic"),
    resolutions: Optional[str] = Query(None, description="Comma-separated resolutions (small,medium,large,huge) - OR logic"),
    excluded_resolutions: Optional[str] = Query(None, description="Comma-separated resolutions to exclude (small,medium,large,huge) - NOT logic"),
    keywords: Optional[str] = Query(None, description="Comma-separated keywords to filter by (AND logic)"),
    excluded_keywords: Optional[str] = Query(None, description="Comma-separated keywords to exclude (NOT logic)"),
    folders: Optional[str] = Query(None, description="Comma-separated folder paths to filter by (OR logic)"),
    excluded_folders: Optional[str] = Query(None, description="Comma-separated folder paths to exclude"),
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    is_generated: Optional[bool] = Query(None, description="Filter for generated images (true) or non-generated (false)"),
    marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to filter by (OR logic - item must have at least one)"),
    excluded_marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to exclude (NOT logic - item must NOT have any)"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic - item must have at least one)"),
    excluded_tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to exclude (NOT logic - item must NOT have any)"),
    tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to filter by via lineage (OR logic)"),
    excluded_tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to exclude via lineage"),
    sort_by: str = Query("deleted_desc", pattern="^(deleted_desc|deleted_asc|created_desc|created_asc|random|similarity)$"),
    random_seed: Optional[int] = Query(None, description="Seed for stable random ordering"),
    session: AsyncSession = Depends(get_db_session)
):
    """Get deleted media items (trash) with optional filters."""
    # Trash-specific pre-filter: only deleted items, and (per longstanding behavior) include
    # items that have been superseded by sets/grids so users can see everything in the bin.
    query = select(MediaItem).where(MediaItem.deleted_at.isnot(None))

    # All shared filter logic lives in the helper to keep semantics in lockstep with the
    # library list, find-index, and filter-counts endpoints.
    query = build_filtered_query(
        query,
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        resolutions=resolutions,
        excluded_resolutions=excluded_resolutions,
        keywords=keywords,
        excluded_keywords=excluded_keywords,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        created_after=created_after,
        created_before=created_before,
        exclude_expired=False,
    )

    # Handle similarity search separately (requires in-memory processing)
    if similar_to_text is not None:
        from config import get_settings
        from clip_service import get_clip_service, CLIP_EMBEDDING_DIM

        if not similar_to_text.strip():
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="similar_to_text cannot be empty")

        # Add filter to only include items with embeddings
        query = query.where(MediaItem.clip_embedding.isnot(None))

        # Eager load associations before executing
        query = query.options(
            selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
            selectinload(MediaItem.tags)
        )

        # Execute query to get all filtered items
        result = await session.execute(query)
        all_items = result.scalars().all()

        # Encode the text using CLIP
        clip_service = get_clip_service()
        query_embedding = clip_service.encode_text(similar_to_text.strip())

        # Compute similarities
        threshold = similarity_threshold if similarity_threshold is not None else get_settings().clip_text_similarity_threshold
        similarity_scores = {}
        filtered_items = []

        for item in all_items:
            embedding = item.get_embedding()
            if embedding is not None:
                # Check embedding dimensions - skip items with old model embeddings
                if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    continue
                similarity = clip_service.compute_similarity(query_embedding, embedding)
                if similarity >= threshold:
                    similarity_scores[item.id] = float(similarity)
                    filtered_items.append(item)

        # Sort filtered items
        if sort_by == "similarity":
            filtered_items.sort(key=lambda x: similarity_scores.get(x.id, 0), reverse=True)
        elif sort_by == "deleted_desc":
            filtered_items.sort(key=lambda x: x.deleted_at if x.deleted_at else datetime.min, reverse=True)
        elif sort_by == "deleted_asc":
            filtered_items.sort(key=lambda x: x.deleted_at if x.deleted_at else datetime.min, reverse=False)
        elif sort_by == "created_desc":
            filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=True)
        elif sort_by == "created_asc":
            filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=False)
        elif sort_by == "random":
            if random_seed is not None:
                import random as py_random
                py_random.Random(random_seed).shuffle(filtered_items)

        # Apply pagination
        total = len(filtered_items)
        offset = (page - 1) * page_size
        items = filtered_items[offset:offset + page_size]

        media_items = [MediaItemResponse(**item.to_dict()) for item in items]

        return MediaListResponse(
            items=media_items,
            total=total,
            page=page,
            page_size=page_size
        )

    # Non-similarity search path: use DB sorting and pagination
    # Get total count with filters applied
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar()

    # Apply sorting
    if sort_by == "deleted_desc":
        query = query.order_by(MediaItem.deleted_at.desc(), MediaItem.id.desc())
    elif sort_by == "deleted_asc":
        query = query.order_by(MediaItem.deleted_at.asc(), MediaItem.id.asc())
    elif sort_by == "created_desc":
        query = query.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())
    elif sort_by == "created_asc":
        query = query.order_by(MediaItem.created_date.asc().nulls_last(), MediaItem.id.asc())
    elif sort_by == "random":
        seed = random_seed if random_seed is not None else 42
        seed_multiplier = literal(seed | 1)
        product = MediaItem.random_sort_value * seed_multiplier
        transformed_value = product - func.cast(product, Integer)
        query = query.order_by(transformed_value, MediaItem.id)
    elif sort_by == "similarity":
        # Without similar_to_text, fall back to deleted_desc
        query = query.order_by(MediaItem.deleted_at.desc(), MediaItem.id.desc())

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    # Eager load marker_associations and tags
    query = query.options(
        selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
        selectinload(MediaItem.tags)
    )

    result = await session.execute(query)
    items = result.scalars().all()

    media_items = [MediaItemResponse(**item.to_dict()) for item in items]

    return MediaListResponse(
        items=media_items,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/trash/filter-counts")
async def get_trash_filter_counts(
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    media_types: Optional[str] = Query(None, description="Comma-separated currently selected media types"),
    excluded_media_types: Optional[str] = Query(None, description="Comma-separated excluded media types"),
    resolutions: Optional[str] = Query(None, description="Comma-separated currently selected resolutions"),
    excluded_resolutions: Optional[str] = Query(None, description="Comma-separated excluded resolutions"),
    keywords: Optional[str] = Query(None, description="Comma-separated currently selected keywords"),
    excluded_keywords: Optional[str] = Query(None, description="Comma-separated excluded keywords"),
    folders: Optional[str] = Query(None, description="Comma-separated currently selected folders"),
    excluded_folders: Optional[str] = Query(None, description="Comma-separated excluded folders"),
    is_generated: Optional[bool] = Query(None, description="Filter for generated images"),
    marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to filter by (OR logic)"),
    excluded_marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to exclude (NOT logic)"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic)"),
    excluded_tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to exclude (NOT logic)"),
    keyword_limit: int = Query(5, ge=1, le=200, description="Number of top keywords to include with counts"),
    tag_limit: int = Query(50, ge=1, le=200, description="Number of top tags to include with counts"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get preview counts for each filter option in the trash view.
    Returns counts showing how many trashed items would match if that option were selected,
    based on current filters.
    """
    from config import get_settings
    from utils.query_builder import build_filtered_query

    settings = get_settings()

    # Helper to build base query for trash items.
    # Trash includes superseded items (matches get_trash behavior so badge counts agree
    # with what users actually see in the list).
    def get_base_query():
        q = select(func.count(MediaItem.id)).select_from(MediaItem)
        q = q.where(MediaItem.deleted_at.isnot(None))
        return q

    # Compute "if I click this media type" preview count for every supported type.
    # Without all 8, badges silently disappear from the UI for newer types.
    media_type_format_map = {
        'images': IMAGE_FORMATS,
        'videos': VIDEO_FORMATS,
        'audio': AUDIO_FORMATS,
        'text': TEXT_FORMATS,
        'sets': SET_FORMATS,
        'grids': GRID_FORMATS,
        'layouts': LAYOUT_FORMATS,
        'structured': STRUCTURED_FORMATS,
    }
    media_type_counts = {}
    for type_name, formats in media_type_format_map.items():
        type_query = get_base_query()
        type_query = build_filtered_query(
            type_query,
            caption_query=caption_query,
            prompt_query=prompt_query,
            resolutions=resolutions,
            excluded_resolutions=excluded_resolutions,
            keywords=keywords,
            excluded_keywords=excluded_keywords,
            folders=folders,
            excluded_folders=excluded_folders,
            is_generated=is_generated,
            marker_ids=marker_ids,
            excluded_marker_ids=excluded_marker_ids,
            tag_ids=tag_ids,
            excluded_tag_ids=excluded_tag_ids,
            exclude_category='media_types',
            exclude_expired=False,
        )
        type_query = type_query.where(MediaItem.file_format.in_(formats))
        type_result = await session.execute(type_query)
        media_type_counts[type_name] = type_result.scalar()

    # Resolution preview counts (exclude resolutions category from filters)
    small_query = get_base_query()
    small_query = build_filtered_query(
        small_query,
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        keywords=keywords,
        excluded_keywords=excluded_keywords,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        exclude_category='resolutions',
        exclude_expired=False,
    )
    small_query = small_query.where(MediaItem.megapixels < 0.8)
    small_result = await session.execute(small_query)
    small_count = small_result.scalar()

    medium_query = get_base_query()
    medium_query = build_filtered_query(
        medium_query,
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        keywords=keywords,
        excluded_keywords=excluded_keywords,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        exclude_category='resolutions',
        exclude_expired=False,
    )
    medium_query = medium_query.where(and_(
        MediaItem.megapixels >= 0.8,
        MediaItem.megapixels < 1.5
    ))
    medium_result = await session.execute(medium_query)
    medium_count = medium_result.scalar()

    large_query = get_base_query()
    large_query = build_filtered_query(
        large_query,
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        keywords=keywords,
        excluded_keywords=excluded_keywords,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        exclude_category='resolutions',
        exclude_expired=False,
    )
    large_query = large_query.where(MediaItem.megapixels >= 1.5)
    large_result = await session.execute(large_query)
    large_count = large_result.scalar()

    # Folder preview counts (exclude folders category from filters)
    folder_counts = {}
    for folder in settings.media_paths:
        folder_query = get_base_query()
        folder_query = build_filtered_query(
            folder_query,
            caption_query=caption_query,
            prompt_query=prompt_query,
            media_types=media_types,
            excluded_media_types=excluded_media_types,
            resolutions=resolutions,
            excluded_resolutions=excluded_resolutions,
            keywords=keywords,
            excluded_keywords=excluded_keywords,
            is_generated=is_generated,
            marker_ids=marker_ids,
            excluded_marker_ids=excluded_marker_ids,
            tag_ids=tag_ids,
            excluded_tag_ids=excluded_tag_ids,
            exclude_category='folders',
            exclude_expired=False,
        )
        # Ensure folder path ends with / to avoid partial matches
        folder_with_slash = folder.rstrip('/') + '/'
        folder_query = folder_query.where(MediaItem.file_path.startswith(folder_with_slash))
        result = await session.execute(folder_query)
        folder_counts[folder] = result.scalar()

    # Keyword preview counts using efficient JOIN query
    keyword_counts_dict = {}

    # Build base query that JOINs media_items with keywords through media_keywords
    keyword_query = select(
        Keyword.keyword_text,
        func.count(func.distinct(MediaItem.id)).label('count')
    ).select_from(Keyword).join(
        MediaKeyword, Keyword.id == MediaKeyword.keyword_id
    ).join(
        MediaItem, MediaKeyword.media_id == MediaItem.id
    )

    # Only count trashed items
    keyword_query = keyword_query.where(MediaItem.deleted_at.isnot(None))

    # Apply all non-keyword filters to show preview counts
    keyword_query = build_filtered_query(
        keyword_query,
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        resolutions=resolutions,
        excluded_resolutions=excluded_resolutions,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        exclude_category='keywords',
        exclude_expired=False,
    )

    # Group by keyword and order by count
    keyword_query = keyword_query.group_by(Keyword.keyword_text).order_by(
        func.count(func.distinct(MediaItem.id)).desc()
    ).limit(keyword_limit)

    # Execute single query to get top keywords with their counts
    result = await session.execute(keyword_query)
    keyword_results = result.all()

    for keyword_text, count in keyword_results:
        keyword_counts_dict[keyword_text] = count

    # Tag preview counts using efficient JOIN query (similar to keywords)
    tag_counts_list = []

    tag_query = select(
        Tag.id,
        Tag.tag_text,
        func.count(func.distinct(MediaItem.id)).label('count')
    ).select_from(Tag).join(
        MediaTag, Tag.id == MediaTag.tag_id
    ).join(
        MediaItem, MediaTag.media_id == MediaItem.id
    )

    # Only count trashed items
    tag_query = tag_query.where(MediaItem.deleted_at.isnot(None))

    # Apply all non-tag filters to show preview counts
    tag_query = build_filtered_query(
        tag_query,
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        resolutions=resolutions,
        excluded_resolutions=excluded_resolutions,
        keywords=keywords,
        excluded_keywords=excluded_keywords,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        exclude_category='tags',
        exclude_expired=False,
    )

    # Group by tag and order by count
    tag_query = tag_query.group_by(Tag.id, Tag.tag_text).order_by(
        func.count(func.distinct(MediaItem.id)).desc()
    ).limit(tag_limit)

    # Execute query
    result = await session.execute(tag_query)
    tag_results = result.all()

    for tag_id, tag_text, count in tag_results:
        tag_counts_list.append({
            "id": tag_id,
            "tag": tag_text,
            "usage_count": count
        })

    # Calculate date range counts based on file creation date
    date_range_counts = {}
    from datetime import timedelta
    now = datetime.utcnow()

    date_ranges = [
        ('2hrs', timedelta(hours=2)),
        ('24hrs', timedelta(hours=24)),
        ('72hrs', timedelta(hours=72)),
        ('7d', timedelta(days=7)),
        ('30d', timedelta(days=30)),
        ('90d', timedelta(days=90)),
        ('365d', timedelta(days=365))
    ]

    for range_key, delta in date_ranges:
        after_date = now - delta
        range_query = get_base_query()
        range_query = build_filtered_query(
            range_query,
            caption_query=caption_query,
            prompt_query=prompt_query,
            media_types=media_types,
            excluded_media_types=excluded_media_types,
            resolutions=resolutions,
            excluded_resolutions=excluded_resolutions,
            keywords=keywords,
            excluded_keywords=excluded_keywords,
            folders=folders,
            excluded_folders=excluded_folders,
            marker_ids=marker_ids,
            excluded_marker_ids=excluded_marker_ids,
            tag_ids=tag_ids,
            excluded_tag_ids=excluded_tag_ids,
            exclude_category='date_ranges',
            exclude_expired=False,
        )
        # Add created date filter (file creation date)
        range_query = range_query.where(MediaItem.created_date >= after_date)
        range_result = await session.execute(range_query)
        date_range_counts[range_key] = range_result.scalar()

    return {
        "media_type": media_type_counts,
        "resolution": {
            "small": small_count,
            "medium": medium_count,
            "large": large_count
        },
        "folders": folder_counts,
        "keywords": keyword_counts_dict,
        "tags": tag_counts_list,
        "date_ranges": date_range_counts
    }


# Batch operations must come BEFORE parameterized routes to avoid route conflicts
@router.post("/trash/batch/restore")
async def bulk_restore_from_trash(
    request: BulkTrashRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Restore multiple items from trash."""
    restored_count = 0
    errors = []
    BATCH_SIZE = 500

    # Fetch all requested items in batches
    items_map = {}
    for i in range(0, len(request.media_ids), BATCH_SIZE):
        batch_ids = request.media_ids[i:i + BATCH_SIZE]
        result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(batch_ids))
        )
        items_map.update({m.id: m for m in result.scalars().all()})

    for media_id in request.media_ids:
        media = items_map.get(media_id)
        if not media:
            errors.append({"media_id": media_id, "error": "Not found"})
            continue
        if media.deleted_at is None:
            errors.append({"media_id": media_id, "error": "Not in trash"})
            continue
        if media.deletion_pending_at is not None:
            errors.append({"media_id": media_id, "error": "Deletion is in progress"})
            continue

        # Restore - just clear the timestamp
        media.deleted_at = None
        asset_revision = await _asset_revision_for_media(session, media_id)
        if asset_revision is not None:
            from asset_service import restore_asset
            await restore_asset(session, asset_id=asset_revision.asset_id)
        restored_count += 1

    await session.commit()

    # Broadcast bulk restore event
    restored_ids = [mid for mid in request.media_ids if mid not in [e["media_id"] for e in errors]]
    if restored_ids:
        await ws_manager.broadcast("media_bulk_restored", {
            "count": len(restored_ids),
            "media_ids": restored_ids
        })

        from telemetry import get_telemetry_client
        get_telemetry_client().track("media_restored", {"count": len(restored_ids)})

    return {
        "status": "success",
        "restored": restored_count,
        "total": len(request.media_ids),
        "errors": errors
    }


@router.post("/trash/batch/delete", status_code=202)
async def bulk_permanently_delete(
    request: BulkTrashRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Queue permanent deletion for multiple items from trash."""
    BATCH_SIZE = 500
    errors = []
    items_to_delete = []
    profile_id = get_current_profile()

    for i in range(0, len(request.media_ids), BATCH_SIZE):
        batch_ids = request.media_ids[i:i + BATCH_SIZE]

        result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(batch_ids))
        )
        items_map = {m.id: m for m in result.scalars().all()}

        batch_deleted_ids = []
        for media_id in batch_ids:
            media = items_map.get(media_id)
            if not media:
                errors.append({"media_id": media_id, "error": "Not found"})
                continue
            if media.deleted_at is None:
                errors.append({"media_id": media_id, "error": "Not in trash"})
                continue
            if media.deletion_pending_at is not None:
                errors.append({"media_id": media_id, "error": "Deletion is already in progress"})
                continue
            items_to_delete.append(media)

    if not items_to_delete:
        return {
            "status": "accepted",
            "operation": None,
            "accepted": 0,
            "total": len(request.media_ids),
            "errors": errors
        }

    operation = await create_delete_operation(
        session,
        profile_id=profile_id,
        kind="batch",
        media_items=items_to_delete,
    )
    await ensure_delete_worker_started()

    return {
        "status": "accepted",
        "operation": operation.to_dict(),
        "accepted": len(items_to_delete),
        "total": len(request.media_ids),
        "errors": errors
    }


@router.post("/trash/{media_id}/restore")
async def restore_from_trash(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Restore a media item from trash."""
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = result.scalar_one_or_none()

    if not media:
        raise HTTPException(status_code=404, detail="Asset not found")

    if media.deleted_at is None:
        raise HTTPException(status_code=400, detail="Asset is not deleted")
    if media.deletion_pending_at is not None:
        raise HTTPException(status_code=409, detail="Asset deletion is in progress")

    # Restore - just clear the timestamp
    media.deleted_at = None
    asset_revision = await _asset_revision_for_media(session, media_id)
    if asset_revision is not None:
        from asset_service import restore_asset
        await restore_asset(session, asset_id=asset_revision.asset_id)
    await session.commit()

    # Broadcast restore event
    await ws_manager.broadcast("media_restored", {"media_id": media_id})

    return {"status": "success", "message": "Asset restored"}


@router.delete("/trash/{media_id}", status_code=202)
async def permanently_delete_media(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Queue permanent deletion for a media item in trash."""
    result = await session.execute(select(MediaItem).where(MediaItem.id == media_id))
    media = result.scalar_one_or_none()

    if not media:
        raise HTTPException(status_code=404, detail="Asset not found")

    if media.deleted_at is None:
        raise HTTPException(status_code=400, detail="Asset is not in trash")
    if media.deletion_pending_at is not None:
        raise HTTPException(status_code=409, detail="Asset deletion is already in progress")

    operation = await create_delete_operation(
        session,
        profile_id=get_current_profile(),
        kind="single",
        media_items=[media],
    )
    await ensure_delete_worker_started()

    return {"status": "accepted", "operation": operation.to_dict(), "message": "Permanent delete queued"}


@router.delete("/trash", status_code=202)
async def empty_trash(
    session: AsyncSession = Depends(get_db_session)
):
    """Queue permanent deletion for all items currently in trash."""
    count_result = await session.execute(
        select(func.count()).select_from(MediaItem).where(
            MediaItem.deleted_at.isnot(None),
            MediaItem.deletion_pending_at.is_(None),
        )
    )
    total_count = count_result.scalar()

    if total_count == 0:
        return {"status": "accepted", "operation": None, "accepted": 0, "message": "Trash is already empty"}

    result = await session.execute(
        select(MediaItem)
        .where(
            MediaItem.deleted_at.isnot(None),
            MediaItem.deletion_pending_at.is_(None),
        )
        .order_by(MediaItem.id.asc())
    )
    items_to_delete = list(result.scalars().all())
    operation = await create_delete_operation(
        session,
        profile_id=get_current_profile(),
        kind="empty_trash",
        media_items=items_to_delete,
    )
    await ensure_delete_worker_started()

    return {
        "status": "accepted",
        "operation": operation.to_dict(),
        "accepted": len(items_to_delete),
        "total": total_count,
        "message": f"Permanent deletion started for {len(items_to_delete)} items"
    }


@router.get("/delete-operations/active")
async def get_active_delete_operation_route(
    session: AsyncSession = Depends(get_db_session)
):
    operation = await get_active_delete_operation(session, get_current_profile())
    return {"operation": operation.to_dict() if operation else None}


@router.get("/deletion-status/media/{media_id}")
async def get_media_deletion_status(
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    media = await session.get(MediaItem, media_id)
    if media is None:
        return {"status": "deleted"}
    if media.deletion_pending_at is not None:
        return {"status": "pending"}
    if media.deleted_at is not None:
        return {"status": "trashed"}
    return {"status": "live"}


@router.get("/delete-operations/{operation_id}")
async def get_delete_operation_route(
    operation_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    operation = await get_delete_operation(session, operation_id)
    if not operation or operation.profile_id != get_current_profile():
        raise HTTPException(status_code=404, detail="Delete operation not found")
    return operation.to_dict()


@router.post("/delete-operations/{operation_id}/retry", status_code=202)
async def retry_delete_operation_route(
    operation_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    operation = await get_delete_operation(session, operation_id)
    if not operation or operation.profile_id != get_current_profile():
        raise HTTPException(status_code=404, detail="Delete operation not found")
    try:
        operation = await retry_delete_operation(session, operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await ensure_delete_worker_started()
    return {"status": "accepted", "operation": operation.to_dict()}

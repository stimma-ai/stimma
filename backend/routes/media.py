"""Core media browsing and search routes."""
from core.logging import get_logger
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, Query, HTTPException, Form, UploadFile, Body
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, and_, func, literal, Integer, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import Asset, AssetRevision, Board, BoardItem, BoardSection, MediaItem, Keyword, MediaKeyword, MediaMarker, MediaTag, MediaToolLineage, Face, Project, ProjectAsset, ProjectMedia
from core.dependencies import get_db_session
from models.api_models import BoardSummaryResponse, MediaListResponse, MediaItemResponse, MediaIndexResponse, SimilaritySearchRequest, TagResponse, MediaMarkerInfo, StructuredContentUpdateRequest
from config import get_settings
from utils.query_builder import (
    build_filtered_query, not_due_for_autodelete, VIDEO_FORMATS, IMAGE_FORMATS, AUDIO_FORMATS,
    TEXT_FORMATS, SET_FORMATS, GRID_FORMATS, LAYOUT_FORMATS, STRUCTURED_FORMATS, RESOLUTION_MAP
)
from utils.similarity import (
    compute_relevance_cutoff,
    filter_items_by_face_similarity,
    parse_similarity_ids,
    sort_similarity_items,
)
from utils.websocket import ws_manager

router = APIRouter(tags=["media"])
log = get_logger(__name__)


async def _reset_stale_clip_embeddings(session: AsyncSession, item_ids: list[int]) -> None:
    """
    Reset CLIP embeddings for items with stale (wrong dimension) embeddings.
    Sets clip_embedding to NULL and clip_status to 'pending' for re-indexing.
    """
    from sqlalchemy import update
    if not item_ids:
        return

    await session.execute(
        update(MediaItem)
        .where(MediaItem.id.in_(item_ids))
        .values(clip_embedding=None, clip_status='pending')
    )
    await session.commit()
    log.info(f"Reset {len(item_ids)} items with stale CLIP embeddings for re-indexing")


@router.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "Stimma API"}


@router.get("/api/media", response_model=MediaListResponse)
async def get_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    text_query: Optional[str] = None,  # Deprecated, kept for backwards compatibility
    search_in: str = Query("both", pattern="^(caption|prompt|both)$"),  # Deprecated
    media_types: Optional[str] = Query(None, description="Comma-separated media types (images,videos,audio,text,sets,grids,layouts,structured) - OR logic"),
    excluded_media_types: Optional[str] = Query(None, description="Comma-separated media types to exclude (images,videos,audio,text,sets,grids,layouts,structured) - NOT logic"),
    media_type: str = Query("both", pattern="^(images|videos|both)$"),  # Deprecated
    resolutions: Optional[str] = Query(None, description="Comma-separated resolutions (small,medium,large,huge) - OR logic"),
    excluded_resolutions: Optional[str] = Query(None, description="Comma-separated resolutions to exclude (small,medium,large,huge) - NOT logic"),
    keywords: Optional[str] = Query(None, description="Comma-separated keywords to filter by (AND logic)"),
    excluded_keywords: Optional[str] = Query(None, description="Comma-separated keywords to exclude (NOT logic)"),
    exclude_media_type: bool = Query(False, description="Exclude the specified media type instead of including it"),
    exclude_resolution: bool = Query(False, description="Exclude the specified resolution range instead of including it"),
    folders: Optional[str] = Query(None, description="Comma-separated folder paths to filter by (OR logic)"),
    excluded_folders: Optional[str] = Query(None, description="Comma-separated folder paths to exclude"),
    min_mp: Optional[float] = None,
    max_mp: Optional[float] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    similar_to: Optional[str] = Query(None, description="Comma-separated media IDs to find similar items to (supports 1-3 IDs for embedding interpolation)"),
    similar_face_to: Optional[str] = Query(None, description="Comma-separated media IDs to find images with similar faces (supports 1-3 IDs)"),
    similar_to_text: Optional[str] = Query(None, description="Text query to find visually similar images using CLIP text encoding"),
    similarity_threshold: Optional[float] = Query(None, description="Similarity threshold for filtering results (0.0-1.0, default from settings)"),
    similarity_cutoff: Optional[str] = Query(None, pattern="^(auto)$", description="For similar_to_text: 'auto' replaces the flat threshold with a per-query cutoff derived from the score distribution's shape"),
    is_generated: Optional[bool] = Query(None, description="Filter for generated images (true) or non-generated (false)"),
    marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to filter by (OR logic - item must have at least one)"),
    excluded_marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to exclude (NOT logic - item must NOT have any)"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic - item must have at least one)"),
    excluded_tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to exclude (NOT logic - item must NOT have any)"),
    tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to filter by via lineage (OR logic)"),
    excluded_tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to exclude via lineage"),
    tool_id: Optional[str] = Query(None, description="Filter by tool ID that created the media"),
    preset_id: Optional[int] = Query(None, description="Filter by preset ID that was active during generation"),
    show_expiring: Optional[bool] = Query(None, description="Filter for images with auto_delete_at set (expiring generated images)"),
    exclude_expiring: Optional[bool] = Query(None, description="Exclude images with auto_delete_at set (non-expiring images)"),
    project_id: Optional[int] = Query(None, description="Filter to assets attached to a project"),
    project_ids: Optional[str] = Query(None, description="Comma-separated project IDs - item must be in at least one (OR logic)"),
    excluded_project_ids: Optional[str] = Query(None, description="Comma-separated project IDs to exclude - item must not be in any"),
    has_project: Optional[bool] = Query(None, description="True = in any project, False = in no project (library only)"),
    sort_by: str = Query("created_desc", pattern="^(created_desc|created_asc|indexed_desc|indexed_asc|added_desc|added_asc|random|similarity)$"),
    random_seed: Optional[int] = Query(None, description="Seed for stable random ordering"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get paginated list of media items with optional filters.
    """
    # Build query
    query = select(MediaItem)

    # Exclude soft-deleted items by default
    query = query.where(MediaItem.deleted_at.is_(None))

    # Filter out items owned by sets/grids (superseded_by is set)
    query = query.where(MediaItem.superseded_by.is_(None))

    # Only show items with completed metadata (have file_hash for thumbnails)
    query = query.where(MediaItem.metadata_status == 'completed')

    # Exclude unavailable files (files not found on disk)
    query = query.where(
        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
    )

    if project_id is not None:
        if sort_by in ("added_desc", "added_asc"):
            # Join with ProjectMedia so we can sort by added_at
            query = query.join(ProjectMedia, (ProjectMedia.media_id == MediaItem.id) & (ProjectMedia.project_id == project_id))
        else:
            project_media_subquery = select(ProjectMedia.media_id).where(ProjectMedia.project_id == project_id)
            query = query.where(MediaItem.id.in_(project_media_subquery))

    # Backward-compat shim: old text_query+search_in is rewritten into caption_query/prompt_query
    # so the helper can handle them uniformly.
    if text_query and not caption_query and not prompt_query:
        text_filter = []
        if search_in in ("caption", "both"):
            text_filter.append(MediaItem.vlm_caption.ilike(f"%{text_query}%"))
        if search_in in ("prompt", "both"):
            text_filter.append(MediaItem.extracted_prompt.ilike(f"%{text_query}%"))
        if text_filter:
            query = query.where(or_(*text_filter))

    # Backward-compat shim: legacy single-select media_type with optional exclude flag.
    # Only applied when the modern multi-select media_types is not provided.
    if not media_types and media_type != "both":
        if media_type == "videos":
            if exclude_media_type:
                query = query.where(MediaItem.file_format.in_(IMAGE_FORMATS))
            else:
                query = query.where(MediaItem.file_format.in_(VIDEO_FORMATS))
        elif media_type == "images":
            if exclude_media_type:
                query = query.where(MediaItem.file_format.in_(VIDEO_FORMATS))
            else:
                query = query.where(MediaItem.file_format.in_(IMAGE_FORMATS))

    # Backward-compat shim: legacy direct min_mp/max_mp behavior, only when modern resolutions
    # multi-select isn't used. Inverted-range form when exclude_resolution=True.
    legacy_mp = not resolutions and (min_mp is not None or max_mp is not None)
    if legacy_mp:
        if exclude_resolution:
            if min_mp is not None and max_mp is not None:
                query = query.where(or_(
                    MediaItem.megapixels < min_mp,
                    MediaItem.megapixels > max_mp,
                ))
            elif min_mp is not None:
                query = query.where(MediaItem.megapixels < min_mp)
            elif max_mp is not None:
                query = query.where(MediaItem.megapixels > max_mp)
        else:
            if min_mp is not None:
                query = query.where(MediaItem.megapixels >= min_mp)
            if max_mp is not None:
                query = query.where(MediaItem.megapixels <= max_mp)

    # All shared filter semantics live in build_filtered_query so list, find-index, trash,
    # and filter-counts can never disagree.
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
        project_ids=project_ids,
        excluded_project_ids=excluded_project_ids,
        has_project=has_project,
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        tool_id=tool_id,
        preset_id=preset_id,
        created_after=created_after,
        created_before=created_before,
        show_expiring=show_expiring,
        exclude_expiring=exclude_expiring,
        # Helper handles superseded_by IS NULL; we already added that pre-filter above
        # but it's idempotent.
    )

    # Handle similarity search
    similarity_scores = {}
    reference_ids = []

    if similar_to is not None or similar_to_text is not None or similar_face_to is not None:
        from telemetry import get_telemetry_client
        get_telemetry_client().track("similarity_search_used")

    similarity_mode_count = sum(
        value is not None
        for value in (similar_to, similar_to_text, similar_face_to)
    )
    if similarity_mode_count > 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine similar_to, similar_to_text, and similar_face_to",
        )

    if similar_to_text is not None:
        # Text-based similarity search using CLIP text encoding
        if not similar_to_text.strip():
            raise HTTPException(status_code=400, detail="similar_to_text cannot be empty")

        # Encode the text using CLIP
        from clip_service import get_clip_service, CLIP_EMBEDDING_DIM
        clip_service = get_clip_service()
        query_embedding = clip_service.encode_text(similar_to_text.strip())

        # Add filter to only include items with embeddings
        query = query.where(MediaItem.clip_embedding.isnot(None))

        # Execute query to get all filtered items (no pagination yet)
        result = await session.execute(query)
        all_items = result.scalars().all()

        # Compute similarities - use lower threshold for text-to-image (scores are typically 0.2-0.4)
        threshold = similarity_threshold if similarity_threshold is not None else get_settings().clip_text_similarity_threshold
        all_scores: dict[int, float] = {}
        scored_items = []
        stale_embedding_ids = []  # Items with wrong dimension embeddings

        for item in all_items:
            embedding = item.get_embedding()
            if embedding is not None:
                # Check embedding dimensions - skip items with old model embeddings
                if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    stale_embedding_ids.append(item.id)
                    continue
                all_scores[item.id] = float(clip_service.compute_similarity(query_embedding, embedding))
                scored_items.append(item)

        # Schedule re-indexing for items with stale embeddings (wrong dimensions)
        if stale_embedding_ids:
            log.warning(f"Found {len(stale_embedding_ids)} items with stale CLIP embeddings (wrong dimensions), scheduling re-index")
            await _reset_stale_clip_embeddings(session, stale_embedding_ids)

        # An explicit similarity_threshold always wins. Otherwise 'auto' replaces the flat
        # default with a cutoff derived from this query's own score distribution, so
        # non-visual/absent-concept queries (a flat distribution) return little to nothing
        # while still keeping a homogeneous-but-relevant library (flat-but-high) intact.
        if similarity_cutoff == "auto" and similarity_threshold is None:
            effective_threshold = compute_relevance_cutoff(list(all_scores.values()), absolute_floor=threshold)
        else:
            effective_threshold = threshold

        filtered_items = []
        for item in scored_items:
            score = all_scores[item.id]
            if score >= effective_threshold:
                similarity_scores[item.id] = score
                filtered_items.append(item)

        # Sort filtered items based on sort_by parameter
        if sort_by == "similarity":
            # Sort by similarity (highest first)
            filtered_items.sort(key=lambda x: similarity_scores[x.id], reverse=True)
        elif sort_by == "created_desc":
            filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=True)
        elif sort_by == "created_asc":
            filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=False)
        elif sort_by == "indexed_desc":
            filtered_items.sort(key=lambda x: x.indexed_date, reverse=True)
        elif sort_by == "indexed_asc":
            filtered_items.sort(key=lambda x: x.indexed_date, reverse=False)
        elif sort_by == "random":
            # For random sort with similarity search, use Python's random with seed
            if random_seed is not None:
                import random as py_random
                temp_items = list(filtered_items)
                py_random.Random(random_seed).shuffle(temp_items)
                filtered_items = temp_items

        # Apply pagination to filtered results
        total = len(filtered_items)
        offset = (page - 1) * page_size
        items = filtered_items[offset:offset + page_size]

        # Reload paginated items with marker associations for display
        if items:
            item_ids = [item.id for item in items]
            items_query = select(MediaItem).where(MediaItem.id.in_(item_ids)).options(
                selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
                selectinload(MediaItem.tags)
            )
            result = await session.execute(items_query)
            items_with_markers = {item.id: item for item in result.scalars().all()}
            # Preserve ordering from similarity search
            items = [items_with_markers[item_id] for item_id in item_ids if item_id in items_with_markers]
    elif similar_face_to is not None:
        similar_face_to_ids = parse_similarity_ids(similar_face_to, "similar_face_to")
        reference_ids = similar_face_to_ids

        result = await session.execute(query)
        all_items = result.scalars().all()

        filtered_items, similarity_scores = await filter_items_by_face_similarity(
            session,
            all_items,
            similar_face_to_ids,
            similarity_threshold,
        )

        sort_similarity_items(filtered_items, similarity_scores, sort_by, random_seed)

        total = len(filtered_items)
        offset = (page - 1) * page_size
        items = filtered_items[offset:offset + page_size]

        # Reload paginated items with marker associations for display.
        if items:
            item_ids = [item.id for item in items]
            items_query = select(MediaItem).where(MediaItem.id.in_(item_ids)).options(
                selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
                selectinload(MediaItem.tags)
            )
            result = await session.execute(items_query)
            items_with_markers = {item.id: item for item in result.scalars().all()}
            items = [items_with_markers[item_id] for item_id in item_ids if item_id in items_with_markers]
    elif similar_to is not None:
        # Parse comma-separated IDs
        similar_to_ids = parse_similarity_ids(similar_to, "similar_to")

        # Get all reference items
        result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(similar_to_ids))
        )
        reference_items = result.scalars().all()

        if len(reference_items) != len(similar_to_ids):
            raise HTTPException(status_code=404, detail="One or more reference assets not found")

        # Collect embeddings from all reference items
        from clip_service import CLIP_EMBEDDING_DIM
        reference_embeddings = []
        stale_reference_ids = []
        for item in reference_items:
            if item.clip_embedding is None:
                raise HTTPException(status_code=400, detail=f"Reference asset {item.id} has no CLIP embedding")
            embedding = item.get_embedding()
            # Check embedding dimensions - reject stale embeddings
            if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                stale_reference_ids.append(item.id)
                continue
            reference_embeddings.append(embedding)
            reference_ids.append(item.id)

        # If any reference items have stale embeddings, reset them and return error
        if stale_reference_ids:
            await _reset_stale_clip_embeddings(session, stale_reference_ids)
            raise HTTPException(
                status_code=400,
                detail=f"Reference assets {stale_reference_ids} have outdated CLIP embeddings. They have been scheduled for re-indexing. Please try again after CLIP indexing completes."
            )

        if not reference_embeddings:
            raise HTTPException(status_code=400, detail="No valid reference embeddings found")

        # If multiple references, average and normalize the embeddings
        if len(reference_embeddings) == 1:
            query_embedding = reference_embeddings[0]
        else:
            # Average embeddings (interpolation)
            import numpy as np
            avg_embedding = np.mean(reference_embeddings, axis=0)
            # Re-normalize (important for cosine similarity)
            query_embedding = avg_embedding / np.linalg.norm(avg_embedding)

        # Add filter to only include items with embeddings
        query = query.where(MediaItem.clip_embedding.isnot(None))

        # Execute query to get all filtered items (no pagination yet)
        result = await session.execute(query)
        all_items = result.scalars().all()

        # Compute similarities
        from clip_service import get_clip_service
        clip_service = get_clip_service()
        # Use provided threshold or fall back to settings
        threshold = similarity_threshold if similarity_threshold is not None else get_settings().clip_similarity_threshold
        filtered_items = []
        stale_embedding_ids = []  # Items with wrong dimension embeddings

        for item in all_items:
            embedding = item.get_embedding()
            if embedding is not None:
                # Check embedding dimensions - skip items with old model embeddings
                if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    stale_embedding_ids.append(item.id)
                    continue
                similarity = clip_service.compute_similarity(query_embedding, embedding)
                # Include reference items regardless of threshold, others must meet threshold
                if item.id in reference_ids or similarity >= threshold:
                    similarity_scores[item.id] = float(similarity)
                    filtered_items.append(item)

        # Schedule re-indexing for items with stale embeddings (wrong dimensions)
        if stale_embedding_ids:
            log.warning(f"Found {len(stale_embedding_ids)} items with stale CLIP embeddings (wrong dimensions), scheduling re-index")
            await _reset_stale_clip_embeddings(session, stale_embedding_ids)

        # Sort filtered items based on sort_by parameter
        if sort_by == "similarity":
            # Sort by similarity (highest first)
            filtered_items.sort(key=lambda x: similarity_scores[x.id], reverse=True)
        elif sort_by == "created_desc":
            filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=True)
        elif sort_by == "created_asc":
            filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=False)
        elif sort_by == "indexed_desc":
            filtered_items.sort(key=lambda x: x.indexed_date, reverse=True)
        elif sort_by == "indexed_asc":
            filtered_items.sort(key=lambda x: x.indexed_date, reverse=False)
        elif sort_by == "random":
            # For random sort with similarity search, use Python's random with seed
            if random_seed is not None:
                import random as py_random
                temp_items = list(filtered_items)
                py_random.Random(random_seed).shuffle(temp_items)
                filtered_items = temp_items

        # Apply pagination to filtered results
        total = len(filtered_items)
        offset = (page - 1) * page_size
        items = filtered_items[offset:offset + page_size]

        # Reload paginated items with marker associations for display
        if items:
            item_ids = [item.id for item in items]
            items_query = select(MediaItem).where(MediaItem.id.in_(item_ids)).options(
                selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
                selectinload(MediaItem.tags)
            )
            result = await session.execute(items_query)
            items_with_markers = {item.id: item for item in result.scalars().all()}
            # Preserve ordering from similarity search
            items = [items_with_markers[item_id] for item_id in item_ids if item_id in items_with_markers]
    else:
        # Normal flow without similarity search
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        result = await session.execute(count_query)
        total = result.scalar()

        # Sorting (similarity sort requires an active similarity search, fall back to created_desc)
        if sort_by == "similarity":
            # Can't sort by similarity without a similarity search active
            # Fall back to created_desc
            sort_by = "created_desc"

        if sort_by == "created_desc":
            query = query.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())
        elif sort_by == "created_asc":
            query = query.order_by(MediaItem.created_date.asc().nulls_last(), MediaItem.id.asc())
        elif sort_by == "indexed_desc":
            query = query.order_by(MediaItem.indexed_date.desc(), MediaItem.id.desc())
        elif sort_by == "indexed_asc":
            query = query.order_by(MediaItem.indexed_date.asc(), MediaItem.id.asc())
        elif sort_by == "added_desc":
            query = query.order_by(ProjectMedia.added_at.desc(), MediaItem.id.desc())
        elif sort_by == "added_asc":
            query = query.order_by(ProjectMedia.added_at.asc(), MediaItem.id.asc())
        elif sort_by == "random":
            # Use stable random value with seed transformation
            # Each item has a fixed random_sort_value (0-1) set on creation
            # The seed transforms this value to produce different orderings
            # Formula: (random_value * seed_multiplier) - FLOOR(random_value * seed_multiplier)
            # This gives serendipity (different seed = different order)
            # with stability (same seed = same order, pagination works)
            seed = random_seed if random_seed is not None else 42
            # Use multiplicative hashing: multiply by seed, take fractional part
            # This creates much better distribution than additive shifting
            # We use a large odd number (seed | 1) to ensure good mixing
            seed_multiplier = literal(seed | 1)  # Ensure odd number for better distribution
            product = MediaItem.random_sort_value * seed_multiplier
            transformed_value = product - func.cast(product, Integer)
            query = query.order_by(
                transformed_value,
                MediaItem.id  # Stable tiebreaker
            )

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # Eager load marker_associations (with source) and tags for display in the grid
        query = query.options(
            selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
            selectinload(MediaItem.tags)
        )

        # Execute query
        result = await session.execute(query)
        items = result.scalars().all()

    # Track search telemetry
    if caption_query or prompt_query or text_query:
        from telemetry import get_telemetry_client
        query_type = "caption" if caption_query else ("prompt" if prompt_query else "text")
        get_telemetry_client().track("search_used", {
            "queryType": query_type,
            "hasResults": total > 0,
        })

    # Fetch auto_delete_at for all items in one query
    # Convert to response model
    media_items = []
    for item in items:
        item_dict = item.to_dict()
        # Add similarity score if available
        if item.id in similarity_scores:
            item_dict['similarity_score'] = similarity_scores[item.id]
        # Add auto_delete_at from media item itself
        if item.auto_delete_at:
            item_dict['auto_delete_at'] = item.auto_delete_at.isoformat()
        media_items.append(MediaItemResponse(**item_dict))

    return MediaListResponse(
        items=media_items,
        total=total,
        page=page,
        page_size=page_size,
        reference_ids=reference_ids if reference_ids else None
    )


@router.get("/api/media/ids")
async def get_media_ids(
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    text_query: Optional[str] = None,
    search_in: str = Query("both", pattern="^(caption|prompt|both)$"),
    media_types: Optional[str] = Query(None, description="Comma-separated media types (images,videos,audio,text,sets,grids,layouts,structured) - OR logic"),
    excluded_media_types: Optional[str] = Query(None, description="Comma-separated media types to exclude (images,videos,audio,text,sets,grids,layouts,structured) - NOT logic"),
    media_type: str = Query("both", pattern="^(images|videos|both)$"),
    resolutions: Optional[str] = Query(None, description="Comma-separated resolutions (small,medium,large,huge) - OR logic"),
    excluded_resolutions: Optional[str] = Query(None, description="Comma-separated resolutions to exclude (small,medium,large,huge) - NOT logic"),
    keywords: Optional[str] = Query(None, description="Comma-separated keywords to filter by (AND logic)"),
    excluded_keywords: Optional[str] = Query(None, description="Comma-separated keywords to exclude (NOT logic)"),
    exclude_media_type: bool = Query(False, description="Exclude the specified media type instead of including it"),
    exclude_resolution: bool = Query(False, description="Exclude the specified resolution range instead of including it"),
    folders: Optional[str] = Query(None, description="Comma-separated folder paths to filter by (OR logic)"),
    excluded_folders: Optional[str] = Query(None, description="Comma-separated folder paths to exclude"),
    min_mp: Optional[float] = None,
    max_mp: Optional[float] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    similar_to: Optional[str] = Query(None, description="Comma-separated media IDs to find similar items to (supports 1-3 IDs for embedding interpolation)"),
    similar_face_to: Optional[str] = Query(None, description="Comma-separated media IDs to find images with similar faces (supports 1-3 IDs)"),
    similarity_threshold: Optional[float] = Query(None, description="Similarity threshold for filtering results (0.0-1.0, default from settings)"),
    marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to filter by (OR logic - item must have at least one)"),
    excluded_marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to exclude (NOT logic - item must NOT have any)"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic - item must have at least one)"),
    excluded_tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to exclude (NOT logic - item must NOT have any)"),
    tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to filter by via lineage (OR logic)"),
    excluded_tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to exclude via lineage"),
    show_expiring: Optional[bool] = Query(None, description="Filter for images with auto_delete_at set (expiring generated images)"),
    exclude_expiring: Optional[bool] = Query(None, description="Exclude images with auto_delete_at set (non-expiring images)"),
    project_id: Optional[int] = Query(None, description="Filter to assets attached to a project"),
    project_ids: Optional[str] = Query(None, description="Comma-separated project IDs - item must be in at least one (OR logic)"),
    excluded_project_ids: Optional[str] = Query(None, description="Comma-separated project IDs to exclude - item must not be in any"),
    has_project: Optional[bool] = Query(None, description="True = in any project, False = in no project (library only)"),
    sort_by: str = Query("created_desc", pattern="^(created_desc|created_asc|indexed_desc|indexed_asc|added_desc|added_asc|random|similarity)$"),
    random_seed: Optional[int] = Query(None, description="Seed for stable random ordering"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get list of all media item IDs matching the current filters (no pagination).
    Returns IDs in the order specified by sort_by.
    """
    # This endpoint reuses the same filter logic as /api/media but returns only IDs
    # We'll build the same query and return just the IDs

    query = select(MediaItem.id)

    # Exclude soft-deleted items by default
    query = query.where(MediaItem.deleted_at.is_(None))
    # Never surface ephemeral one-shot-run intermediates
    query = query.where(MediaItem.ephemeral_run_id.is_(None))

    # Only show items with completed metadata (have file_hash for thumbnails)
    query = query.where(MediaItem.metadata_status == 'completed')

    # Exclude unavailable files (files not found on disk)
    query = query.where(
        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
    )

    if project_id is not None:
        if sort_by in ("added_desc", "added_asc"):
            query = query.join(ProjectMedia, (ProjectMedia.media_id == MediaItem.id) & (ProjectMedia.project_id == project_id))
        else:
            project_media_subquery = select(ProjectMedia.media_id).where(ProjectMedia.project_id == project_id)
            query = query.where(MediaItem.id.in_(project_media_subquery))

    # text_query backwards compat (deprecated)
    if text_query and not caption_query and not prompt_query:
        text_filter = []
        if search_in in ("caption", "both"):
            text_filter.append(MediaItem.vlm_caption.ilike(f"%{text_query}%"))
        if search_in in ("prompt", "both"):
            text_filter.append(MediaItem.extracted_prompt.ilike(f"%{text_query}%"))
        if text_filter:
            query = query.where(or_(*text_filter))

    # Legacy single-select media_type backwards compat (only when modern multi-select isn't used)
    if not media_types and media_type != "both":
        if media_type == "videos":
            if exclude_media_type:
                query = query.where(MediaItem.file_format.in_(IMAGE_FORMATS))
            else:
                query = query.where(MediaItem.file_format.in_(VIDEO_FORMATS))
        elif media_type == "images":
            if exclude_media_type:
                query = query.where(MediaItem.file_format.in_(VIDEO_FORMATS))
            else:
                query = query.where(MediaItem.file_format.in_(IMAGE_FORMATS))

    # Legacy direct min_mp/max_mp behavior, only when modern resolutions multi-select isn't used
    if not resolutions and (min_mp is not None or max_mp is not None):
        if exclude_resolution:
            if min_mp is not None and max_mp is not None:
                query = query.where(or_(MediaItem.megapixels < min_mp, MediaItem.megapixels > max_mp))
            elif min_mp is not None:
                query = query.where(MediaItem.megapixels < min_mp)
            elif max_mp is not None:
                query = query.where(MediaItem.megapixels > max_mp)
        else:
            if min_mp is not None:
                query = query.where(MediaItem.megapixels >= min_mp)
            if max_mp is not None:
                query = query.where(MediaItem.megapixels <= max_mp)

    # All shared filter semantics (incl. superseded_by IS NULL) come from the helper
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
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        project_ids=project_ids,
        excluded_project_ids=excluded_project_ids,
        has_project=has_project,
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        show_expiring=show_expiring,
        exclude_expiring=exclude_expiring,
    )

    if similar_to is not None and similar_face_to is not None:
        raise HTTPException(status_code=400, detail="Cannot combine similar_to and similar_face_to")

    # For similarity search, we need to handle it differently
    if similar_face_to is not None:
        similar_face_to_ids = parse_similarity_ids(similar_face_to, "similar_face_to")

        result = await session.execute(query)
        all_ids = [row[0] for row in result.all()]

        items_result = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(all_ids))
        )
        all_items = items_result.scalars().all()

        filtered_items, similarity_scores = await filter_items_by_face_similarity(
            session,
            all_items,
            similar_face_to_ids,
            similarity_threshold,
        )

        sort_similarity_items(filtered_items, similarity_scores, sort_by, random_seed)

        return {"ids": [item.id for item in filtered_items]}

    if similar_to is not None:
        # Parse comma-separated IDs
        similar_to_ids = parse_similarity_ids(similar_to, "similar_to")

        if similar_to_ids:
            # Get reference items and compute similarities
            result = await session.execute(
                select(MediaItem).where(MediaItem.id.in_(similar_to_ids))
            )
            reference_items = result.scalars().all()

            if len(reference_items) != len(similar_to_ids):
                raise HTTPException(status_code=404, detail="One or more reference assets not found")

            # Collect embeddings
            from clip_service import CLIP_EMBEDDING_DIM
            reference_embeddings = []
            stale_reference_ids = []
            for item in reference_items:
                if item.clip_embedding is None:
                    raise HTTPException(status_code=400, detail=f"Reference asset {item.id} has no CLIP embedding")
                embedding = item.get_embedding()
                if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    stale_reference_ids.append(item.id)
                    continue
                reference_embeddings.append(embedding)

            if stale_reference_ids:
                await _reset_stale_clip_embeddings(session, stale_reference_ids)
                raise HTTPException(
                    status_code=400,
                    detail=f"Reference assets {stale_reference_ids} have outdated CLIP embeddings. They have been scheduled for re-indexing. Please try again after CLIP indexing completes."
                )

            if not reference_embeddings:
                raise HTTPException(status_code=400, detail="No valid reference embeddings found")

            # Average and normalize if multiple references
            if len(reference_embeddings) == 1:
                query_embedding = reference_embeddings[0]
            else:
                import numpy as np
                avg_embedding = np.mean(reference_embeddings, axis=0)
                query_embedding = avg_embedding / np.linalg.norm(avg_embedding)

            # Get all items with embeddings
            query = query.where(MediaItem.clip_embedding.isnot(None))
            result = await session.execute(query)
            all_ids = [row[0] for row in result.all()]

            # Fetch full items to compute similarities
            items_result = await session.execute(
                select(MediaItem).where(MediaItem.id.in_(all_ids))
            )
            all_items = items_result.scalars().all()

            # Compute similarities
            from clip_service import get_clip_service
            clip_service = get_clip_service()
            threshold = similarity_threshold if similarity_threshold is not None else get_settings().clip_similarity_threshold
            filtered_items = []
            similarity_scores = {}
            stale_embedding_ids = []

            for item in all_items:
                embedding = item.get_embedding()
                if embedding is not None:
                    # Check embedding dimensions - skip items with old model embeddings
                    if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                        stale_embedding_ids.append(item.id)
                        continue
                    similarity = clip_service.compute_similarity(query_embedding, embedding)
                    # Include reference items regardless of threshold
                    if item.id in similar_to_ids or similarity >= threshold:
                        similarity_scores[item.id] = float(similarity)
                        filtered_items.append(item)

            # Schedule re-indexing for items with stale embeddings
            if stale_embedding_ids:
                log.warning(f"Found {len(stale_embedding_ids)} items with stale CLIP embeddings, scheduling re-index")
                await _reset_stale_clip_embeddings(session, stale_embedding_ids)

            # Sort by similarity or other criteria
            if sort_by == "similarity":
                filtered_items.sort(key=lambda x: similarity_scores[x.id], reverse=True)
            elif sort_by == "created_desc":
                filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=True)
            elif sort_by == "created_asc":
                filtered_items.sort(key=lambda x: x.created_date if x.created_date else datetime.min, reverse=False)
            elif sort_by == "indexed_desc":
                filtered_items.sort(key=lambda x: x.indexed_date, reverse=True)
            elif sort_by == "indexed_asc":
                filtered_items.sort(key=lambda x: x.indexed_date, reverse=False)
            elif sort_by == "random":
                if random_seed is not None:
                    import random as py_random
                    temp_items = list(filtered_items)
                    py_random.Random(random_seed).shuffle(temp_items)
                    filtered_items = temp_items

            return {"ids": [item.id for item in filtered_items]}

    # Normal sorting (non-similarity) - use ID as tiebreaker for stable ordering
    if sort_by == "created_desc":
        query = query.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())
    elif sort_by == "created_asc":
        query = query.order_by(MediaItem.created_date.asc().nulls_last(), MediaItem.id.asc())
    elif sort_by == "indexed_desc":
        query = query.order_by(MediaItem.indexed_date.desc(), MediaItem.id.desc())
    elif sort_by == "indexed_asc":
        query = query.order_by(MediaItem.indexed_date.asc(), MediaItem.id.asc())
    elif sort_by == "added_desc":
        query = query.order_by(ProjectMedia.added_at.desc(), MediaItem.id.desc())
    elif sort_by == "added_asc":
        query = query.order_by(ProjectMedia.added_at.asc(), MediaItem.id.asc())
    elif sort_by == "random":
        if random_seed is not None:
            query = query.order_by(func.random())  # Note: This won't use seed properly, would need DB-specific handling

    # Execute query
    result = await session.execute(query)
    ids = [row[0] for row in result.all()]

    return {"ids": ids}


@router.post("/api/media/check-existence")
async def check_media_existence(
    media_ids: List[int],
    session: AsyncSession = Depends(get_db_session)
):
    """
    Check which media IDs still exist (not permanently deleted).
    Returns the subset of IDs that exist in the database.
    Useful for validating cached references (e.g., chat attachments).
    """
    if not media_ids:
        return {"existing_ids": [], "missing_ids": []}

    # Query for existing IDs (including trashed - they still exist, just in trash)
    result = await session.execute(
        select(MediaItem.id).where(MediaItem.id.in_(media_ids))
    )
    existing_set = set(row[0] for row in result.all())

    existing_ids = [mid for mid in media_ids if mid in existing_set]
    missing_ids = [mid for mid in media_ids if mid not in existing_set]

    return {"existing_ids": existing_ids, "missing_ids": missing_ids}


@router.get("/api/media/{media_id}", response_model=MediaItemResponse)
async def get_media_item(
    media_id: int,
    include_trashed: bool = Query(False, description="Include trashed items"),
    session: AsyncSession = Depends(get_db_session)
):
    """Get a single media item by ID."""
    query = select(MediaItem).where(MediaItem.id == media_id)

    if not include_trashed:
        query = query.where(MediaItem.deleted_at.is_(None))
        # An item past its auto-delete deadline must read as gone even before the worker runs.
        query = query.where(not_due_for_autodelete())
    # Ephemeral one-shot-run intermediates never resolve, even with include_trashed.
    query = query.where(MediaItem.ephemeral_run_id.is_(None))

    query = query.options(
        selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
        selectinload(MediaItem.tags)
    )

    result = await session.execute(query)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    item_dict = item.to_dict()
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == item.id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if revision is not None:
        item_dict["asset_id"] = revision.asset_id
        item_dict["revision_id"] = revision.id
    return MediaItemResponse(**item_dict)


@router.get("/api/media/{media_id}/content")
async def get_media_content(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get parsed content for structured media types (text, sets, grids).

    For sets and grids, file references are resolved to their MediaItem records.
    Returns 404 for non-structured media types (images, videos, audio).

    Response format varies by type:
    - .md: {format: 'markdown', frontmatter, content, images: [{alt, path, resolved: {...}}, ...]}
    - .stimmaset.json: {version, title?, items: [{path, resolved: {media_id, file_hash, ...}}, ...]}
    - .stimmagrid.json: {version, rows, cols, row_headers?, col_headers?, cells: [{row, col, path, resolved: {...}}, ...]}
    """
    from structured_media import get_structured_content, parse_structured_content

    # Fetch the media item
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
            not_due_for_autodelete(),
        )
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Check if this is a structured type
    structured_formats = {'md', 'stimmaset.json', 'stimmagrid.json'}
    if item.file_format.lower() not in structured_formats:
        raise HTTPException(
            status_code=404,
            detail=f"Content endpoint not available for media type: {item.file_format}"
        )

    # Normalized containers resolve linked Assets through their current heads;
    # legacy manifests remain the compatibility fallback during migration.
    content = None
    if item.file_format.lower() in {"stimmaset.json", "stimmagrid.json"}:
        from container_service import get_normalized_container_content
        content = await get_normalized_container_content(
            session, container_media=item
        )
    if content is None:
        content = await get_structured_content(session, item)

    if content is None:
        log.error(f"Failed to get structured content for media {media_id} (format={item.file_format}, raw_metadata_len={len(item.raw_metadata) if item.raw_metadata else 0})")
        raise HTTPException(
            status_code=500,
            detail="Failed to parse structured content"
        )

    return content


@router.patch("/api/media/{media_id}/content")
async def update_media_content(
    media_id: int,
    update_data: StructuredContentUpdateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Update metadata for structured media types (sets, grids).

    Currently supports updating the title field.
    Uses centralized helpers with locking to ensure atomic disk/DB updates.
    """
    from structured_media import (
        read_composite_content,
        write_composite_content,
        _get_modification_lock,
    )

    # Fetch the media item
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
        )
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Check if this is a structured type that supports titles
    supported_formats = {'stimmaset.json', 'stimmagrid.json'}
    if item.file_format.lower() not in supported_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Content update not supported for media type: {item.file_format}"
        )

    # Use locking to prevent concurrent modification race conditions
    async with _get_modification_lock(media_id):
        # Read existing content with cache validation
        content = await read_composite_content(session, item)
        if not content:
            log.error(f"Failed to read structured content for media {media_id}")
            raise HTTPException(
                status_code=500,
                detail="Failed to read structured content"
            )

        # Update title if provided
        if update_data.title is not None:
            content['title'] = update_data.title if update_data.title else None

        # Write back atomically (updates disk + DB cache including file_hash)
        try:
            await write_composite_content(session, item, content)
        except Exception as e:
            log.error(f"Failed to write structured content for media {media_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail="Failed to save structured content to disk"
            )

    await session.commit()

    # Broadcast update with full media object
    await ws_manager.broadcast('media_updated', {
        'media_id': media_id,
        'fields': ['title'],
        'media': item.to_dict()
    })

    return {"status": "success", "title": content.get('title')}


@router.delete("/api/media/{media_id}/auto-delete")
async def remove_auto_delete(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """Remove auto-delete from a media item."""
    # Find the media item
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    media_item = result.scalar_one_or_none()

    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Clear auto-delete setting
    media_item.auto_delete_at = None
    await session.commit()

    # Broadcast update to refresh UI
    await ws_manager.broadcast('auto_delete_removed', {
        'media_id': media_id
    })

    return {"status": "success", "message": "Auto-delete removed"}


@router.get("/api/media/{media_id}/boards", response_model=List[BoardSummaryResponse])
async def get_media_boards(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get all boards that contain this media item."""
    # First verify the media item exists (ephemeral one-shot intermediates read as gone)
    media_result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.ephemeral_run_id.is_(None),
        )
    )
    media_item = media_result.scalar_one_or_none()

    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get all boards containing this media item
    result = await session.execute(
        select(Board)
        .join(BoardSection, and_(BoardSection.board_id == Board.id, BoardSection.deleted_at.is_(None)))
        .join(BoardItem, BoardItem.board_section_id == BoardSection.id)
        .where(BoardItem.media_id == media_id)
        .where(Board.deleted_at.is_(None))
        .order_by(Board.name)
    )
    boards = result.scalars().all()

    return [BoardSummaryResponse(**board.to_dict()) for board in boards]


@router.get("/api/media/{media_id}/projects")
async def get_media_projects(
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get all projects that contain this media item."""
    media_result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.ephemeral_run_id.is_(None),
        )
    )
    media_item = media_result.scalar_one_or_none()

    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    result = await session.execute(
        select(Project)
        .join(ProjectMedia, ProjectMedia.project_id == Project.id)
        .where(
            ProjectMedia.media_id == media_id,
            Project.deleted_at.is_(None),
        )
        .order_by(Project.name.asc())
    )
    projects = result.scalars().all()
    return [{"id": p.id, "name": p.name} for p in projects]


@router.get("/api/media/{media_id}/faces")
async def get_media_faces(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """Get all detected faces for a media item."""
    # Verify media item exists
    media_result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    media_item = media_result.scalar_one_or_none()

    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get faces for this media item
    from database import Face
    result = await session.execute(
        select(Face)
        .where(Face.media_id == media_id)
        .order_by(Face.confidence.desc())
    )
    faces = result.scalars().all()

    return {"faces": [face.to_dict() for face in faces]}


@router.get("/api/media/{media_id}/find-index", response_model=MediaIndexResponse)
async def find_media_index(
    media_id: int,
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    media_types: Optional[str] = Query(None, description="Comma-separated media types (images,videos,audio,text,sets,grids,layouts,structured) - OR logic"),
    excluded_media_types: Optional[str] = Query(None, description="Comma-separated media types to exclude - NOT logic"),
    resolutions: Optional[str] = Query(None, description="Comma-separated resolutions (small,medium,large,huge)"),
    excluded_resolutions: Optional[str] = Query(None, description="Comma-separated resolutions to exclude (small,medium,large,huge)"),
    keywords: Optional[str] = Query(None, description="Comma-separated keywords to filter by"),
    excluded_keywords: Optional[str] = Query(None, description="Comma-separated keywords to exclude"),
    folders: Optional[str] = Query(None, description="Comma-separated folder paths"),
    excluded_folders: Optional[str] = Query(None, description="Comma-separated folder paths to exclude"),
    min_mp: Optional[float] = None,
    max_mp: Optional[float] = None,
    similar_to: Optional[str] = Query(None, description="Comma-separated media IDs for similarity search (rejected — see below)"),
    similar_face_to: Optional[str] = Query(None, description="Comma-separated media IDs for face similarity search (rejected — see below)"),
    similar_to_text: Optional[str] = Query(None, description="Text query for CLIP-based similarity (rejected — see below)"),
    similarity_threshold: Optional[float] = Query(None, description="Similarity threshold (0.0-1.0)"),
    is_generated: Optional[bool] = Query(None, description="Filter for generated images (true) or non-generated (false)"),
    marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to filter by (OR logic)"),
    excluded_marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to exclude (NOT logic)"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic)"),
    excluded_tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to exclude (NOT logic)"),
    tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to filter by via lineage (OR logic)"),
    excluded_tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to exclude via lineage"),
    tool_id: Optional[str] = Query(None, description="Filter by tool ID that created the media"),
    preset_id: Optional[int] = Query(None, description="Filter by preset ID that was active during generation"),
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    show_expiring: Optional[bool] = Query(None, description="Filter for images with auto_delete_at set"),
    exclude_expiring: Optional[bool] = Query(None, description="Exclude images with auto_delete_at set"),
    project_id: Optional[int] = Query(None, description="Filter to assets attached to a project"),
    project_ids: Optional[str] = Query(None, description="Comma-separated project IDs - item must be in at least one (OR logic)"),
    excluded_project_ids: Optional[str] = Query(None, description="Comma-separated project IDs to exclude - item must not be in any"),
    has_project: Optional[bool] = Query(None, description="True = in any project, False = in no project (library only)"),
    sort_by: str = Query("created_desc", pattern="^(created_desc|created_asc|indexed_desc|indexed_asc|added_desc|added_asc|random|similarity)$"),
    random_seed: Optional[int] = Query(None, description="Seed for stable random ordering"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Find the index position of a media item within the current filtered/sorted result set.
    Used by the grid → slideshow handoff so the slideshow opens at the right item even
    after background DB changes.

    Similarity search (similar_to, similar_to_text, similar_face_to) is rejected with HTTP 400: indices are
    unstable in similarity mode, and the slideshow handoff for similarity uses the shared
    in-memory mediaList cache instead.
    """
    # Reject similarity modes — caller must use cache-based lookup instead.
    if similar_to is not None or similar_to_text is not None or similar_face_to is not None:
        raise HTTPException(
            status_code=400,
            detail="find-index does not support similarity search (indices are unstable in similarity mode)"
        )

    # First verify the item exists
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id)
    )
    target_item = result.scalar_one_or_none()
    if not target_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Build the same query as get_media (without pagination), routed through the shared
    # filter helper so semantics can never drift between list and find-index.
    query = select(MediaItem.id)

    # Endpoint-specific pre-filters (mirror get_media)
    query = query.where(MediaItem.deleted_at.is_(None))
    query = query.where(MediaItem.ephemeral_run_id.is_(None))
    query = query.where(MediaItem.metadata_status == 'completed')
    query = query.where(
        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
    )

    # Project membership: when sorting by added_at we need a join so the sort column is available
    if project_id is not None:
        if sort_by in ("added_desc", "added_asc"):
            query = query.join(
                ProjectMedia,
                (ProjectMedia.media_id == MediaItem.id) & (ProjectMedia.project_id == project_id),
            )
        else:
            project_media_subquery = select(ProjectMedia.media_id).where(ProjectMedia.project_id == project_id)
            query = query.where(MediaItem.id.in_(project_media_subquery))

    # All shared filters
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
        project_ids=project_ids,
        excluded_project_ids=excluded_project_ids,
        has_project=has_project,
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        tool_id=tool_id,
        preset_id=preset_id,
        created_after=created_after,
        created_before=created_before,
        show_expiring=show_expiring,
        exclude_expiring=exclude_expiring,
        min_mp=min_mp,
        max_mp=max_mp,
    )

    # similarity sort can't be ordered by SQL — caller already rejected via similar_to/similar_to_text.
    # Treat sort_by="similarity" as created_desc for safety.
    if sort_by == "similarity":
        sort_by = "created_desc"

    # Apply sorting — must match get_media so the index is meaningful.
    if sort_by == "created_desc":
        query = query.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())
    elif sort_by == "created_asc":
        query = query.order_by(MediaItem.created_date.asc().nulls_last(), MediaItem.id.asc())
    elif sort_by == "indexed_desc":
        query = query.order_by(MediaItem.indexed_date.desc(), MediaItem.id.desc())
    elif sort_by == "indexed_asc":
        query = query.order_by(MediaItem.indexed_date.asc(), MediaItem.id.asc())
    elif sort_by == "added_desc":
        if project_id is not None:
            query = query.order_by(ProjectMedia.added_at.desc(), MediaItem.id.desc())
        else:
            query = query.order_by(MediaItem.created_date.desc().nulls_last(), MediaItem.id.desc())
    elif sort_by == "added_asc":
        if project_id is not None:
            query = query.order_by(ProjectMedia.added_at.asc(), MediaItem.id.asc())
        else:
            query = query.order_by(MediaItem.created_date.asc().nulls_last(), MediaItem.id.asc())
    elif sort_by == "random":
        # Mirror get_media: stable seeded ordering using each item's random_sort_value.
        # MUST match get_media exactly or the index will be wrong.
        seed = random_seed if random_seed is not None else 42
        seed_multiplier = literal(seed | 1)
        product = MediaItem.random_sort_value * seed_multiplier
        transformed_value = product - func.cast(product, Integer)
        query = query.order_by(transformed_value, MediaItem.id)

    result = await session.execute(query)
    all_ids = [row[0] for row in result.fetchall()]

    try:
        index = all_ids.index(media_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="Item not found in current filtered result set"
        )

    return MediaIndexResponse(
        media_id=media_id,
        index=index,
        total=len(all_ids)
    )


@router.post("/api/search/similar", response_model=MediaListResponse)
async def search_similar(
    request: SimilaritySearchRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Find similar images using CLIP embeddings.
    """
    # Get the query item
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == request.media_id)
    )
    query_item = result.scalar_one_or_none()

    if not query_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    if query_item.clip_embedding is None:
        raise HTTPException(status_code=400, detail="Asset has no CLIP embedding")

    from clip_service import CLIP_EMBEDDING_DIM
    query_embedding = query_item.get_embedding()

    # Check if query item has stale embedding
    if query_embedding.shape[0] != CLIP_EMBEDDING_DIM:
        await _reset_stale_clip_embeddings(session, [request.media_id])
        raise HTTPException(
            status_code=400,
            detail="Reference asset has outdated CLIP embedding. It has been scheduled for re-indexing. Please try again after CLIP indexing completes."
        )

    # Get all items with embeddings
    result = await session.execute(
        select(MediaItem).where(MediaItem.clip_embedding.isnot(None))
    )
    all_items = result.scalars().all()

    # Compute similarities
    from clip_service import get_clip_service
    clip_service = get_clip_service()
    similarities = []
    stale_embedding_ids = []
    for item in all_items:
        if item.id == request.media_id:
            continue  # Skip the query item itself

        embedding = item.get_embedding()
        if embedding is not None:
            # Check embedding dimensions - skip items with old model embeddings
            if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                stale_embedding_ids.append(item.id)
                continue
            similarity = clip_service.compute_similarity(query_embedding, embedding)
            similarities.append((item, similarity))

    # Schedule re-indexing for items with stale embeddings
    if stale_embedding_ids:
        log.warning(f"Found {len(stale_embedding_ids)} items with stale CLIP embeddings, scheduling re-index")
        await _reset_stale_clip_embeddings(session, stale_embedding_ids)

    # Sort by similarity
    similarities.sort(key=lambda x: x[1], reverse=True)

    # Filter by threshold
    threshold = get_settings().clip_similarity_threshold
    filtered_similarities = [(item, score) for item, score in similarities if score >= threshold]

    # Convert to response with similarity scores
    media_items = []
    for item, score in filtered_similarities:
        item_dict = item.to_dict()
        item_dict['similarity_score'] = float(score)
        media_items.append(MediaItemResponse(**item_dict))

    return MediaListResponse(
        items=media_items,
        total=len(media_items),
        page=1,
        page_size=len(media_items)
    )


# ============================================================================
# STRUCTURED MEDIA CREATION ENDPOINTS
# ============================================================================

class CreateSetRequest(BaseModel):
    """Request body for creating a set from media items."""
    media_ids: List[int] = Field(default_factory=list)
    asset_ids: List[int] = Field(default_factory=list)
    title: Optional[str] = None
    project_id: Optional[int] = None


class CreateSetResponse(BaseModel):
    """Response when creating a set."""
    media_id: int
    asset_id: int
    file_path: str
    title: str
    item_count: int


@router.post("/api/media/sets", response_model=CreateSetResponse)
async def create_set_from_media(
    request: CreateSetRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Create a .stimmaset.json file from selected media items.

    The set file will be created in the profile's generation folder.
    Paths are relative when items are in the same folder as the set file,
    otherwise absolute paths are used.

    After creation, triggers a rescan to immediately import the set.
    """
    import json
    import os
    from pathlib import Path
    from datetime import datetime as dt

    if bool(request.media_ids) == bool(request.asset_ids):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of media_ids or asset_ids",
        )

    member_assets = []
    if request.asset_ids:
        rows = (
            await session.execute(
                select(Asset, AssetRevision, MediaItem)
                .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
                .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
                .where(
                    Asset.id.in_(request.asset_ids),
                    Asset.state == "active",
                    Asset.deleted_at.is_(None),
                    AssetRevision.deleted_at.is_(None),
                    MediaItem.deleted_at.is_(None),
                    MediaItem.ephemeral_run_id.is_(None),
                )
            )
        ).all()
        rows_by_id = {asset.id: (asset, media) for asset, _, media in rows}
        if any(asset_id not in rows_by_id for asset_id in request.asset_ids):
            raise HTTPException(status_code=404, detail="One or more assets are unavailable")
        ordered_pairs = [rows_by_id[asset_id] for asset_id in request.asset_ids]
        member_assets = [pair[0] for pair in ordered_pairs]
        ordered_items = [pair[1] for pair in ordered_pairs]
    else:
        result = await session.execute(
            select(MediaItem).where(
                MediaItem.id.in_(request.media_ids),
                MediaItem.deleted_at.is_(None),
                MediaItem.ephemeral_run_id.is_(None),
            )
        )
        items = result.scalars().all()
        items_by_id = {item.id: item for item in items}
        ordered_items = [items_by_id[mid] for mid in request.media_ids if mid in items_by_id]
        if len(ordered_items) != len(request.media_ids):
            raise HTTPException(status_code=404, detail="One or more media items are unavailable")

    # Validate that all items are atomic types (not sets or grids)
    for index, item in enumerate(ordered_items):
        if item.file_format in ('stimmaset.json', 'stimmagrid.json'):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot create a set from structured media types (item {item.id} is a {item.file_format})"
            )

    # Validate the project before any file is written
    if request.project_id is not None:
        from project_service import get_project_or_404
        await get_project_or_404(session, request.project_id)

    # Get the generation folder for the current profile
    from core.profile_context import get_current_profile
    settings = get_settings()
    profile_id = get_current_profile()
    try:
        folder_config = settings.get_generation_folder_for_profile(profile_id)
        output_folder = Path(folder_config.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"No generation folder configured: {e}")

    # Ensure output folder exists
    output_folder.mkdir(parents=True, exist_ok=True)

    # Generate a unique filename
    timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
    base_name = request.title.replace(" ", "_").replace("/", "-")[:50] if request.title else "set"
    filename = f"{base_name}_{timestamp}.stimmaset.json"
    set_file_path = output_folder / filename

    # Ensure unique filename
    counter = 1
    while set_file_path.exists():
        filename = f"{base_name}_{timestamp}_{counter}.stimmaset.json"
        set_file_path = output_folder / filename
        counter += 1

    # Build the set content with paths
    set_items = []
    for item in ordered_items:
        item_path = Path(item.file_path)
        item_folder = item_path.parent

        # Use relative path if in the same folder, otherwise absolute
        if item_folder == output_folder:
            path_str = item_path.name
        else:
            # Check if we can make a reasonable relative path (same root folder tree)
            try:
                rel_path = item_path.relative_to(output_folder)
                path_str = str(rel_path)
            except ValueError:
                # Different folder tree - use absolute path
                path_str = str(item_path)

        set_items.append({
            "asset_id": member_assets[index].id if member_assets else None,
            "path": path_str,
        })

    # Build the set JSON
    set_data = {
        "version": 1,
        "items": set_items
    }
    if request.title:
        set_data["title"] = request.title

    # Write the file
    try:
        with open(set_file_path, 'w', encoding='utf-8') as f:
            json.dump(set_data, f, indent=2)
    except Exception as e:
        log.error(f"Failed to write set file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create set file: {e}")

    # Read file for hash computation
    import hashlib
    with open(set_file_path, 'rb') as f:
        file_content = f.read()
    file_hash = hashlib.sha256(file_content).hexdigest()

    # Get file stats
    stat_info = set_file_path.stat()

    # Get source IDs for lineage tracking (database relationship)
    source_ids = [item.id for item in ordered_items]

    # Create MediaItem for the set directly (don't rely on rescan)
    # Note: source_inputs is intentionally NOT included in generation_metadata
    # because sets are grouping operations, not transformations. The member
    # items are tracked via record_lineage() for database queries, but we don't
    # display them as "Input Media" in the UI.
    from config_version import get_config_version_manager
    from utils.lineage import record_lineage, propagate_tool_lineage

    set_media_item = MediaItem(
        file_path=str(set_file_path),
        file_hash=file_hash,
        file_size=stat_info.st_size,
        file_format='stimmaset.json',
        created_date=dt.utcfromtimestamp(stat_info.st_ctime),
        modified_date=dt.utcfromtimestamp(stat_info.st_mtime),
        indexed_date=dt.utcnow(),
        metadata_status='completed',
        metadata_processed_at=dt.utcnow(),
        metadata_config_version=get_config_version_manager().get_version('metadata'),
        width=0,
        height=0,
        megapixels=0,
        raw_metadata=json.dumps(set_data),
        # Note: vlm_caption is intentionally NOT set for sets - it's for AI captions of visual media
        generation_metadata=json.dumps({
            'version': 3,
            'task_type': 'set-creation',
            'item_count': len(ordered_items),
            'generated_at': dt.utcnow().isoformat(),
        }),
    )

    session.add(set_media_item)
    await session.commit()
    await session.refresh(set_media_item)

    # Record lineage from set member items
    await record_lineage(session, set_media_item.id, source_ids, "set-creation")
    await propagate_tool_lineage(session, set_media_item.id, source_ids)

    # A set is an additional root, not an owner or replacement for its members.
    # Give it the union of member project memberships plus the explicit context.
    from project_service import attach_media_to_project
    project_result = await session.execute(
        select(ProjectMedia.project_id)
        .where(ProjectMedia.media_id.in_(source_ids))
        .distinct()
    )
    set_project_ids = {row[0] for row in project_result.all()}
    if member_assets:
        asset_project_result = await session.execute(
            select(ProjectAsset.project_id)
            .where(
                ProjectAsset.asset_id.in_([asset.id for asset in member_assets]),
                ProjectAsset.deleted_at.is_(None),
            )
            .distinct()
        )
        set_project_ids.update(row[0] for row in asset_project_result.all())
    if request.project_id is not None:
        set_project_ids.add(request.project_id)
    for pid in sorted(set_project_ids):
        await attach_media_to_project(session, pid, set_media_item.id)

    # User-selected members stand on their own and are linked, never owned by
    # this set. This is what enables genuine multiple membership.
    from asset_service import create_asset_from_media
    from container_service import create_container_asset_from_media
    if not member_assets:
        member_assets = [
            await create_asset_from_media(session, media_id=item.id)
            for item in ordered_items
        ]
    set_asset = await create_container_asset_from_media(
        session,
        media_id=set_media_item.id,
        container_type='set',
        members=[{'linked_asset_id': asset.id} for asset in member_assets],
        title=request.title,
        origin_type='manual_set',
    )
    from asset_association_service import mirror_media_associations_to_asset
    await mirror_media_associations_to_asset(
        session, media_id=set_media_item.id, asset_id=set_asset.id
    )
    await session.commit()

    # Broadcast media_added for the new set
    await ws_manager.broadcast('media_added', {
        'media_id': set_media_item.id,
        'count': 1
    })
    await ws_manager.broadcast('asset_created', {
        'asset_id': set_asset.id,
        'media_id': set_media_item.id,
        'revision_id': set_asset.current_revision_id,
    })

    log.info(f"Set Asset {set_asset.id} created at {set_file_path} with linked members: {source_ids}")

    from telemetry import get_telemetry_client
    get_telemetry_client().track("set_created", {
        "count": len(ordered_items),
        "actor": "user",
    }, category="library")

    return CreateSetResponse(
        media_id=set_media_item.id,
        asset_id=set_asset.id,
        file_path=str(set_file_path),
        title=request.title or "Untitled Set",
        item_count=len(ordered_items)
    )


# ============================================================================
# IMAGE EDITOR ENDPOINTS
# ============================================================================

class SaveEditResponse(BaseModel):
    """Response for saving an edited image."""
    media_id: int
    file_hash: str
    asset_id: int
    revision_id: int


@router.post("/api/media/save-edit", response_model=SaveEditResponse)
async def save_edited_image(
    file: UploadFile,
    source_media_id: int = Form(...),
    asset_id: Optional[int] = Form(None),
    editor_project: Optional[str] = Form(None),
    save_as_new: bool = Form(False),
    base_revision_id: Optional[int] = Form(None),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Commit an edited image as a Revision, or as a new Asset for Save As New.

    This endpoint:
    1. Validates the source media exists
    2. Uploads the edited image via UploadService
    3. Records lineage with task_type="image-to-image"
    4. Returns the new media item ID and file hash
    """
    from upload_service import UploadService, UploadError, NoUploadsFolderError
    from utils.lineage import record_lineage, propagate_tool_lineage
    import json

    # Verify source media exists
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == source_media_id)
    )
    source_item = result.scalars().first()
    if not source_item:
        raise HTTPException(status_code=404, detail=f"Source asset {source_media_id} not found")

    parsed_project = None
    if editor_project:
        try:
            parsed_project = json.loads(editor_project)
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid editor project JSON") from exc

    # Read file content
    try:
        file_content = await file.read()
    except Exception as e:
        log.error(f"Failed to read uploaded file: {e}")
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")

    # Upload via UploadService
    try:
        upload_service = UploadService()
        media_item, file_path = await upload_service.upload_file(
            file_content,
            file.filename or f"edited_{source_media_id}.png",
            materialize_asset=False,
            managed_staging=True,
        )
    except NoUploadsFolderError as e:
        log.error(f"No uploads folder configured: {e}")
        raise HTTPException(
            status_code=400,
            detail="No uploads folder configured. Add 'is_uploads_folder: true' to a folder in config.yaml."
        )
    except UploadError as e:
        log.error(f"Upload error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error(f"Unexpected upload error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save edited image")

    # Record exact Media lineage, commit Asset versioning, and persist the
    # non-destructive WorkingDocument. Any failure leaves the upload under its
    # provisional owner for reconciliation rather than ownerless.
    try:
        db_media_item = await session.get(MediaItem, media_item.id)
        if not db_media_item:
            raise RuntimeError(f"Media item {media_item.id} not found after upload")

        from database import Asset, AssetRevision, AssetSnapshot, MediaOwner
        source_asset = await session.get(Asset, asset_id) if asset_id is not None else None
        source_revision = None
        if source_asset is not None:
            source_revision = await session.get(
                AssetRevision, source_asset.current_revision_id
            )
        else:
            source_revision = await session.scalar(
                select(AssetRevision).where(
                    AssetRevision.primary_media_id == source_media_id,
                    AssetRevision.deleted_at.is_(None),
                )
            )
        if asset_id is not None and source_asset is None:
            raise HTTPException(status_code=404, detail="Target Asset not found")
        if source_revision is None:
            from asset_service import create_asset_from_media
            source_asset = await create_asset_from_media(
                session,
                media_id=source_media_id,
                origin_type="editor_legacy_source",
            )
            source_revision = await session.get(
                AssetRevision, source_asset.current_revision_id
            )
        elif source_asset is None:
            source_asset = await session.get(Asset, source_revision.asset_id)
        if source_asset is None or source_asset.state != "active":
            raise HTTPException(status_code=400, detail="Source Asset is unavailable")

        parent_revision = source_revision
        if base_revision_id is not None:
            requested_parent = await session.get(AssetRevision, base_revision_id)
            if (
                requested_parent is None
                or requested_parent.asset_id != source_asset.id
                or requested_parent.deleted_at is not None
            ):
                raise HTTPException(status_code=400, detail="Invalid base Revision")
            parent_revision = requested_parent

        await record_lineage(
            session=session,
            media_id=db_media_item.id,
            source_media_ids=[source_media_id],
            task_type="image-to-image"
        )
        db_media_item.tool_id = "builtin:stimma:image-editor"
        await propagate_tool_lineage(session, db_media_item.id, [source_media_id], own_tool_id="builtin:stimma:image-editor")

        # Set generation_metadata for lineage display in frontend
        from generation_metadata import dump_generation_metadata
        db_media_item.generation_metadata = dump_generation_metadata(
            task_type="image-to-image",
            source="stimma",
            tool_id="builtin:stimma:image-editor",
            source_inputs=[{
                "media_id": source_media_id,
                "role": "source_image",
            }],
            lineage_trace=[{
                "media_id": db_media_item.id,
                "task_type": "image-to-image",
                "source_media_ids": [source_media_id],
            }],
        )

        from asset_service import (
            commit_revision,
            create_asset_from_media,
            create_asset_snapshot,
            create_working_document,
        )
        if save_as_new:
            target_asset = await create_asset_from_media(
                session,
                media_id=db_media_item.id,
                origin_type="editor_save_as_new",
                origin_id=str(source_asset.id),
                idempotency_key=f"editor-output:{db_media_item.id}:new-asset",
            )
            committed_revision = await session.get(
                AssetRevision, target_asset.current_revision_id
            )
        else:
            committed_revision = await commit_revision(
                session,
                asset_id=source_asset.id,
                media_id=db_media_item.id,
                parent_revision_id=parent_revision.id,
                note="Image editor save",
                idempotency_key=f"editor-output:{db_media_item.id}:revision",
            )
            target_asset = source_asset

        document = await create_working_document(
            session,
            asset_id=target_asset.id,
            editor_type="image",
            base_revision_id=committed_revision.id,
            branch_key=f"revision-{parent_revision.id}",
        )
        if parsed_project is not None:
            from core.profile_context import get_current_profile
            from editor_service import save_working_document_state
            await save_working_document_state(
                session,
                document=document,
                profile_id=get_current_profile(),
                project=parsed_project,
            )
        from core.profile_context import get_current_profile
        existing_source_snapshot = await session.scalar(
            select(AssetSnapshot).where(
                AssetSnapshot.owner_kind == "working_document",
                AssetSnapshot.owner_id == str(document.id),
                AssetSnapshot.role == "source",
                AssetSnapshot.deleted_at.is_(None),
            )
        )
        snapshot_media_id = (
            existing_source_snapshot.media_id if existing_source_snapshot else None
        )
        if snapshot_media_id is None:
            from storage_service import ensure_durable_snapshot_media
            durable_source = await ensure_durable_snapshot_media(
                session,
                media=source_item,
                profile_id=get_current_profile(),
            )
            snapshot_media_id = durable_source.id

        await create_asset_snapshot(
            session,
            owner_kind="working_document",
            owner_id=document.id,
            media_id=snapshot_media_id,
            source_asset_id=source_asset.id,
            source_revision_id=parent_revision.id,
            role="source",
        )
        await create_asset_snapshot(
            session,
            owner_kind="revision",
            owner_id=committed_revision.id,
            media_id=snapshot_media_id,
            source_asset_id=source_asset.id,
            source_revision_id=parent_revision.id,
            role="editor_source",
        )
        document.base_revision_id = committed_revision.id
        db_media_item.has_editor_sidecar = False

        provisional_owners = list(await session.scalars(
            select(MediaOwner).where(
                MediaOwner.media_id == db_media_item.id,
                MediaOwner.root_kind == "upload",
                MediaOwner.root_id == str(db_media_item.id),
                MediaOwner.deleted_at.is_(None),
            )
        ))
        for owner in provisional_owners:
            await session.delete(owner)
        await session.commit()
        if snapshot_media_id != source_media_id:
            try:
                from storage_service import cleanup_staged_source
                await cleanup_staged_source(session, media_id=snapshot_media_id)
            except Exception as exc:
                log.warning(
                    f"Deferred editor snapshot-source cleanup: {type(exc).__name__}"
                )

    except Exception as e:
        await session.rollback()
        log.error(f"Failed to commit editor Revision: {e}", exc_info=True)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to commit edited Revision") from e

    await ws_manager.broadcast(
        "asset_created" if save_as_new else "asset_current_revision_changed",
        {
            "asset_id": target_asset.id,
            "revision_id": committed_revision.id,
            "media_id": media_item.id,
        },
    )

    return SaveEditResponse(
        media_id=media_item.id,
        file_hash=media_item.file_hash,
        asset_id=target_asset.id,
        revision_id=committed_revision.id,
    )


@router.get("/api/media/{media_id}/editor-project")
async def get_editor_project(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get the editor project state for a media item from its sidecar file.

    Returns the project content from the .stimmaedit.json sidecar file.
    Returns 404 if the media item doesn't exist or has no sidecar file.
    """
    import json as json_module
    import os

    # Get the media item
    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
        )
    )
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")

    from database import AssetRevision, AssetSnapshot, WorkingDocument
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if revision is not None:
        document = await session.scalar(
            select(WorkingDocument)
            .where(
                WorkingDocument.asset_id == revision.asset_id,
                WorkingDocument.editor_type == "image",
                WorkingDocument.deleted_at.is_(None),
            )
            .order_by(WorkingDocument.updated_at.desc(), WorkingDocument.id.desc())
        )
        if document is not None and document.state_locator:
            from editor_service import load_working_document_state
            try:
                project = await load_working_document_state(document)
            except (OSError, json_module.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=500, detail="Editor working document is unavailable"
                ) from exc
            source_snapshot = await session.scalar(
                select(AssetSnapshot).where(
                    AssetSnapshot.owner_kind == "working_document",
                    AssetSnapshot.owner_id == str(document.id),
                    AssetSnapshot.role == "source",
                    AssetSnapshot.deleted_at.is_(None),
                )
            )
            return {
                "version": 2,
                "asset_id": revision.asset_id,
                "revision_id": revision.id,
                "working_document_id": document.id,
                "source_media_id": source_snapshot.media_id if source_snapshot else None,
                "project": project,
            }

    if not item.has_editor_sidecar:
        raise HTTPException(status_code=404, detail="No editor project found for this asset")

    # Read the sidecar file
    sidecar_path = item.file_path + '.stimmaedit.json'

    if not os.path.exists(sidecar_path):
        # Sidecar flag is set but file doesn't exist - clear the flag
        item.has_editor_sidecar = False
        await session.commit()
        raise HTTPException(status_code=404, detail="Editor sidecar file not found")

    try:
        with open(sidecar_path, 'r', encoding='utf-8') as f:
            sidecar_data = json_module.load(f)

        return {
            "version": sidecar_data.get("version", 1),
            "source_media_id": sidecar_data.get("source_media_id"),  # Original image to load for re-editing
            "project": sidecar_data.get("project")
        }
    except Exception as e:
        log.error(f"Failed to read editor sidecar {sidecar_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read editor project")


# ============================================================================
# SET/GRID MANAGEMENT
# ============================================================================

@router.post("/api/media/{media_id}/explode")
async def explode_set_or_grid(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Explode a set or grid: remove superseded_by from all members and delete the set/grid itself.
    This makes all member items visible again in the library.
    """
    from utils.websocket import broadcast_media_updated
    import os

    result = await session.execute(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
        )
    )
    media = result.scalar_one_or_none()

    if not media:
        raise HTTPException(status_code=404, detail="Asset not found")

    if media.file_format not in ('stimmaset.json', 'stimmagrid.json'):
        raise HTTPException(status_code=400, detail="Can only explode sets or grids")

    # New-model containers explode transactionally: linked Assets remain roots,
    # embedded Media is promoted, and the container moves to Trash.
    from database import AssetRevision
    container_revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if container_revision is not None:
        from container_service import explode_container
        promoted_asset_ids = await explode_container(
            session, asset_id=container_revision.asset_id
        )
        promoted_revisions = list(await session.scalars(
            select(AssetRevision).where(
                AssetRevision.asset_id.in_(promoted_asset_ids),
                AssetRevision.deleted_at.is_(None),
            )
        ))
        current_by_asset = {}
        from database import Asset
        promoted_assets = list(await session.scalars(
            select(Asset).where(Asset.id.in_(promoted_asset_ids))
        ))
        revision_by_id = {revision.id: revision for revision in promoted_revisions}
        for promoted_asset in promoted_assets:
            revision = revision_by_id.get(promoted_asset.current_revision_id)
            if revision is not None:
                current_by_asset[promoted_asset.id] = revision.primary_media_id
        member_ids = [current_by_asset[asset_id] for asset_id in promoted_asset_ids if asset_id in current_by_asset]

        await session.execute(
            update(MediaItem)
            .where(MediaItem.superseded_by == media_id)
            .values(superseded_by=None)
        )
        media.deleted_at = datetime.utcnow()
        media.auto_delete_at = None

        from project_service import attach_media_to_project
        project_result = await session.execute(
            select(ProjectMedia.project_id).where(ProjectMedia.media_id == media_id)
        )
        for pid in [row[0] for row in project_result.all()]:
            for member_id in member_ids:
                await attach_media_to_project(session, pid, member_id)
        await session.execute(
            delete(ProjectMedia).where(ProjectMedia.media_id == media_id)
        )
        await session.commit()

        await ws_manager.broadcast("media_deleted", {"media_id": media_id})
        if member_ids:
            await ws_manager.broadcast('media_added', {
                'count': len(member_ids), 'media_ids': member_ids
            })
        return {"success": True, "exploded_count": len(member_ids)}

    # Legacy fallback: find all items superseded by this set/grid.
    result = await session.execute(
        select(MediaItem).where(MediaItem.superseded_by == media_id)
    )
    members = result.scalars().all()
    member_ids = [m.id for m in members]

    if members:
        # Clear superseded_by on all members
        await session.execute(
            update(MediaItem)
            .where(MediaItem.superseded_by == media_id)
            .values(superseded_by=None)
        )

    # Freed members take over the set/grid's project memberships so they
    # stay visible in the projects where the set lived.
    from project_service import attach_media_to_project
    project_result = await session.execute(
        select(ProjectMedia.project_id).where(ProjectMedia.media_id == media_id)
    )
    set_project_ids = [row[0] for row in project_result.all()]
    for pid in set_project_ids:
        for mid in member_ids:
            await attach_media_to_project(session, pid, mid)
    await session.execute(
        delete(ProjectMedia).where(ProjectMedia.media_id == media_id)
    )

    # Delete the set/grid file from disk
    try:
        if os.path.exists(media.file_path):
            os.remove(media.file_path)
            log.info(f"Deleted set/grid file: {media.file_path}")
    except Exception as e:
        log.warning(f"Failed to delete set/grid file {media.file_path}: {e}")

    # Delete the set/grid MediaItem from database
    await session.delete(media)
    await session.commit()

    # Broadcast deletion of the set/grid first
    await ws_manager.broadcast("media_deleted", {"media_id": media_id})

    # Broadcast media_added for the freed members so they appear in the grid
    # (media_updated won't work because the items weren't in the grid cache when hidden)
    if member_ids:
        await ws_manager.broadcast('media_added', {
            'count': len(member_ids),
            'media_ids': member_ids
        })

    from telemetry import get_telemetry_client
    event_name = "set_exploded" if media.file_format == 'stimmaset.json' else "grid_exploded"
    count_key = "count" if event_name == "set_exploded" else "cellCount"
    get_telemetry_client().track(event_name, {
        count_key: len(member_ids),
        "actor": "user",
    }, category="library")

    log.info(f"Exploded set/grid {media_id}, freed {len(member_ids)} members")
    return {"success": True, "exploded_count": len(member_ids)}


# ============================================================================
# LIBRARY MANAGEMENT ENDPOINTS (Markers, Tags, Boards, Delete/Trash)
# ============================================================================

# ===== MARKERS =====

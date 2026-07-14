"""Processing and system status routes."""
from core.logging import get_logger
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_, literal, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem, Keyword, MediaKeyword, Tag, MediaTag, MediaToolLineage, CachedProviderTool, Project, ProjectMedia
from core.dependencies import get_db_session
from core.profile_context import get_current_profile
from database_registry import get_database_registry
from models.api_models import StatsResponse
from config import get_settings
from utils.query_builder import build_filtered_query, VIDEO_FORMATS, IMAGE_FORMATS, RESOLUTION_MAP
from utils.similarity import filter_media_query_by_face_similarity, parse_similarity_ids

router = APIRouter(prefix="/api", tags=["processing"])
log = get_logger(__name__)

@router.post("/rescan")
async def trigger_rescan(session: AsyncSession = Depends(get_db_session)):
    """Manually trigger a file system rescan."""
    try:
        from database import ControlFlag
        from sqlalchemy import select
        from sqlalchemy.dialects.sqlite import insert
        from core.app import get_rescan_event

        # Set a flag in the database that the worker process will check
        stmt = insert(ControlFlag).values(
            key='rescan_requested',
            value='true',
            updated_at=datetime.utcnow()
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value='true', updated_at=datetime.utcnow())
        )
        await session.execute(stmt)
        await session.commit()

        # Also signal via multiprocessing event for immediate notification
        rescan_event = get_rescan_event()
        if rescan_event:
            rescan_event.set()
            log.info("Rescan requested via API - event signaled for immediate processing")
        else:
            log.info("Rescan requested via API - flag set in database (event not available)")

        # Rescan is asynchronous — the imported-file count isn't known at the
        # trigger point, so this stays a count-less usage marker.
        from telemetry import get_telemetry_client
        get_telemetry_client().track("media_imported", category="library")

        return {"status": "success", "message": "File rescan triggered"}
    except Exception as e:
        log.error(f"Failed to trigger rescan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/processing/pause")
async def pause_processing(session: AsyncSession = Depends(get_db_session)):
    """Pause background processing (except metadata extraction)."""
    try:
        from core.app import get_pause_event
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert

        # Persist to database so it survives restarts
        stmt = insert(ControlFlag).values(
            key='processing_paused',
            value='true',
            updated_at=datetime.utcnow()
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value='true', updated_at=datetime.utcnow())
        )
        await session.execute(stmt)
        await session.commit()

        # Signal the worker process via IPC
        pause_event = get_pause_event()
        if pause_event:
            pause_event.set()  # Set = paused
            log.info("Background processing paused via IPC event (persisted to DB)")
        else:
            # Fallback to local instance (shouldn't happen in normal operation)
            from ingestion import get_ingestion
            ingestion = get_ingestion()
            ingestion.pause()
        return {"status": "success", "message": "Background processing paused", "paused": True}
    except Exception as e:
        log.error(f"Failed to pause processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/processing/resume")
async def resume_processing(session: AsyncSession = Depends(get_db_session)):
    """Resume background processing."""
    try:
        from core.app import get_pause_event
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert

        # Persist to database so it survives restarts
        stmt = insert(ControlFlag).values(
            key='processing_paused',
            value='false',
            updated_at=datetime.utcnow()
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value='false', updated_at=datetime.utcnow())
        )
        await session.execute(stmt)
        await session.commit()

        # Signal the worker process via IPC
        pause_event = get_pause_event()
        if pause_event:
            pause_event.clear()  # Clear = running
            log.info("Background processing resumed via IPC event (persisted to DB)")
        else:
            # Fallback to local instance (shouldn't happen in normal operation)
            from ingestion import get_ingestion
            ingestion = get_ingestion()
            ingestion.resume()
        return {"status": "success", "message": "Background processing resumed", "paused": False}
    except Exception as e:
        log.error(f"Failed to resume processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/processing/status")
async def get_processing_status():
    """Get processing pause status."""
    try:
        from core.app import get_pause_event
        pause_event = get_pause_event()
        if pause_event:
            paused = pause_event.is_set()
        else:
            # Fallback to local instance
            from ingestion import get_ingestion
            ingestion = get_ingestion()
            paused = ingestion.is_processing_paused()
        return {"paused": paused}
    except Exception as e:
        log.error(f"Failed to get processing status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_db_session)):
    """Get database statistics."""
    # Total items
    result = await session.execute(select(func.count(MediaItem.id)))
    total_items = result.scalar()

    # Items with embeddings
    result = await session.execute(
        select(func.count(MediaItem.id)).where(MediaItem.has_clip_embedding == True)
    )
    total_with_embeddings = result.scalar()

    # Items with captions
    result = await session.execute(
        select(func.count(MediaItem.id)).where(MediaItem.has_vlm_caption == True)
    )
    total_with_captions = result.scalar()

    # Total size
    result = await session.execute(select(func.sum(MediaItem.file_size)))
    total_size = result.scalar() or 0

    return StatsResponse(
        total_items=total_items,
        total_with_embeddings=total_with_embeddings,
        total_with_captions=total_with_captions,
        total_size_bytes=total_size
    )


@router.get("/processing/stats")
async def get_processing_stats(session: AsyncSession = Depends(get_db_session)):
    """
    Get processing statistics for each phase.
    Returns counts of pending/processing/completed/failed for each phase.
    Also includes slot utilization information.
    Excludes trashed items (deleted_at is not None).
    """
    from ingestion import PHASES, get_ingestion

    ingestion = get_ingestion()

    # Base condition to exclude trashed and unavailable items
    not_trashed = MediaItem.deleted_at.is_(None)
    available = or_(MediaItem.file_unavailable == False, MediaItem.file_unavailable.is_(None))
    base_filter = and_(not_trashed, available)

    stats = {}
    for phase in PHASES:
        status_col = f"{phase}_status"
        version_col = f"{phase}_config_version"

        phase_stats = {}

        # Get current config version
        current_version = ingestion.config_mgr.get_version(phase) if ingestion else None

        # Get DB counts
        # Pending: items with status 'pending' OR items that need reprocessing (out-of-version)
        result = await session.execute(
            select(func.count()).where(and_(
                getattr(MediaItem, status_col) == 'pending',
                base_filter
            ))
        )
        pending_count = result.scalar()

        # Out-of-version completed items also count as pending (need work)
        if current_version:
            result = await session.execute(
                select(func.count()).where(and_(
                    getattr(MediaItem, status_col) == 'completed',
                    or_(
                        getattr(MediaItem, version_col) != current_version,
                        getattr(MediaItem, version_col) == None
                    ),
                    base_filter
                ))
            )
            out_of_version_count = result.scalar()
        else:
            out_of_version_count = 0

        # Total pending = actually pending + out-of-version items
        phase_stats['pending'] = pending_count + out_of_version_count

        # Completed: only items with current version (exclude trashed and unavailable)
        if current_version:
            result = await session.execute(
                select(func.count()).where(
                    and_(
                        getattr(MediaItem, status_col) == 'completed',
                        getattr(MediaItem, version_col) == current_version,
                        base_filter
                    )
                )
            )
            phase_stats['completed'] = result.scalar()
        else:
            result = await session.execute(
                select(func.count()).where(and_(
                    getattr(MediaItem, status_col) == 'completed',
                    base_filter
                ))
            )
            phase_stats['completed'] = result.scalar()

        # Failed (exclude trashed and unavailable - unavailable is a separate concern)
        result = await session.execute(
            select(func.count()).where(and_(
                getattr(MediaItem, status_col) == 'failed',
                base_filter
            ))
        )
        phase_stats['failed'] = result.scalar()

        # Get DB processing count (exclude trashed and unavailable)
        result = await session.execute(
            select(func.count()).where(and_(
                getattr(MediaItem, status_col) == 'processing',
                base_filter
            ))
        )
        db_processing = result.scalar()

        # Get active worker count from in-memory tracking
        active_workers = len(ingestion.active_workers.get(phase, set())) if ingestion else 0

        # Total processing = DB processing + active workers
        phase_stats['processing'] = db_processing + active_workers

        # Add slot information for visibility
        if ingestion:
            phase_stats['slots_total'] = ingestion.slots.get(phase, 0)
            phase_stats['slots_used'] = active_workers
            phase_stats['slots_available'] = ingestion.slots.get(phase, 0) - active_workers

        stats[phase] = phase_stats

    return {"phase_stats": stats}


@router.get("/processing/failed/{phase}")
async def get_failed_items(
    phase: str,
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get failed items for a specific processing phase.
    Returns file paths, error messages, and retry counts.
    """
    from ingestion import PHASES

    if phase not in PHASES:
        raise HTTPException(status_code=400, detail=f"Invalid phase. Must be one of: {PHASES}")

    status_col = f"{phase}_status"
    error_col = f"{phase}_error"
    retry_col = f"{phase}_retry_count"

    # Build query for failed items (exclude trashed and unavailable)
    # Unavailable files are a separate concern - they failed because the file is missing,
    # not because of a processing error
    available = or_(MediaItem.file_unavailable == False, MediaItem.file_unavailable.is_(None))
    result = await session.execute(
        select(
            MediaItem.id,
            MediaItem.file_path,
            MediaItem.file_hash,
            getattr(MediaItem, error_col).label('error'),
            getattr(MediaItem, retry_col).label('retry_count')
        )
        .where(and_(
            getattr(MediaItem, status_col) == 'failed',
            MediaItem.deleted_at.is_(None),
            available
        ))
        .order_by(MediaItem.id.desc())
        .limit(limit)
    )

    items = result.fetchall()

    return {
        "phase": phase,
        "count": len(items),
        "items": [
            {
                "id": item.id,
                "file_path": item.file_path,
                "file_hash": item.file_hash,
                "error": item.error,
                "retry_count": item.retry_count
            }
            for item in items
        ]
    }


@router.post("/processing/retry/{phase}")
async def retry_failed_items(
    phase: str,
    item_ids: list[int] = None,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Retry failed items for a specific processing phase.
    If item_ids is provided, retry only those specific items.
    If item_ids is None or empty, retry ALL failed items for the phase.
    """
    from ingestion import PHASES

    if phase not in PHASES:
        raise HTTPException(status_code=400, detail=f"Invalid phase. Must be one of: {PHASES}")

    status_col = f"{phase}_status"
    error_col = f"{phase}_error"
    retry_col = f"{phase}_retry_count"

    # Build query for failed items
    query = select(MediaItem).where(getattr(MediaItem, status_col) == 'failed')

    # Filter by specific item IDs if provided
    if item_ids:
        query = query.where(MediaItem.id.in_(item_ids))

    result = await session.execute(query)
    items = result.scalars().all()

    if not items:
        return {
            "phase": phase,
            "retried_count": 0,
            "message": "No failed items found"
        }

    # Reset items to pending status
    for item in items:
        setattr(item, status_col, 'pending')
        setattr(item, retry_col, 0)
        setattr(item, error_col, None)

    await session.commit()

    log.info(f"RETRY: Reset {len(items)} failed {phase} items to pending")

    # Signal the worker to process pending items immediately
    from core.app import get_process_pending_event
    process_pending_event = get_process_pending_event()
    if process_pending_event:
        process_pending_event.set()
        log.info(f"RETRY: Signaled worker to process pending items")

    return {
        "phase": phase,
        "retried_count": len(items),
        "message": f"Successfully reset {len(items)} items to pending"
    }


@router.post("/processing/trash/{phase}")
async def trash_failed_items(
    phase: str,
    item_ids: list[int] = None,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Move failed items for a specific processing phase to trash.
    If item_ids is provided, trash only those specific items.
    If item_ids is None or empty, trash ALL failed items for the phase.
    Uses the existing trash system (soft delete with deleted_at timestamp).
    """
    from ingestion import PHASES

    if phase not in PHASES:
        raise HTTPException(status_code=400, detail=f"Invalid phase. Must be one of: {PHASES}")

    status_col = f"{phase}_status"

    # Build query for failed items
    query = select(MediaItem).where(
        and_(
            getattr(MediaItem, status_col) == 'failed',
            MediaItem.deleted_at.is_(None)  # Not already trashed
        )
    )

    # Filter by specific item IDs if provided
    if item_ids:
        query = query.where(MediaItem.id.in_(item_ids))

    result = await session.execute(query)
    items = result.scalars().all()

    if not items:
        return {
            "phase": phase,
            "trashed_count": 0,
            "message": "No failed items found to trash"
        }

    # Soft delete items by setting deleted_at timestamp
    now = datetime.utcnow()
    for item in items:
        item.deleted_at = now

    await session.commit()

    log.info(f"TRASH: Moved {len(items)} failed {phase} items to trash")

    return {
        "phase": phase,
        "trashed_count": len(items),
        "message": f"Successfully moved {len(items)} items to trash"
    }


@router.get("/keywords/top")
async def get_top_keywords(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, description="Search/filter keywords by text"),
    caption_query: Optional[str] = None,
    prompt_query: Optional[str] = None,
    media_types: Optional[str] = Query(None, description="Comma-separated currently selected media types"),
    excluded_media_types: Optional[str] = Query(None, description="Comma-separated excluded media types"),
    resolutions: Optional[str] = Query(None, description="Comma-separated currently selected resolutions"),
    excluded_resolutions: Optional[str] = Query(None, description="Comma-separated excluded resolutions"),
    folders: Optional[str] = Query(None, description="Comma-separated currently selected folders"),
    excluded_folders: Optional[str] = Query(None, description="Comma-separated excluded folders"),
    is_generated: Optional[bool] = Query(None, description="Filter for generated images"),
    marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to filter by (OR logic)"),
    excluded_marker_ids: Optional[str] = Query(None, description="Comma-separated marker IDs to exclude (NOT logic)"),
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic)"),
    excluded_tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to exclude (NOT logic)"),
    similar_to: Optional[str] = Query(None, description="Comma-separated media IDs for similarity search"),
    similar_face_to: Optional[str] = Query(None, description="Comma-separated media IDs for face similarity search"),
    similarity_threshold: Optional[float] = Query(None, description="Similarity threshold (0.0-1.0)"),
    use_preview_counts: bool = Query(False, description="If true, returns preview counts based on current filters"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get top keywords across all media items.
    Returns keywords sorted by frequency.
    If use_preview_counts=true, returns preview counts showing how many items would match
    if that keyword were selected (based on current filters).
    """
    if not use_preview_counts:
        # Get all keywords with unfiltered counts using normalized tables
        keyword_query = select(
            Keyword.keyword_text,
            func.count(func.distinct(MediaKeyword.media_id)).label('count')
        ).select_from(Keyword).join(
            MediaKeyword, Keyword.id == MediaKeyword.keyword_id
        ).join(
            MediaItem, MediaKeyword.media_id == MediaItem.id
        )

        # Exclude trashed items
        keyword_query = keyword_query.where(MediaItem.deleted_at.is_(None))

        # Apply marker and tag filters
        keyword_query = build_filtered_query(
            keyword_query,
            marker_ids=marker_ids,
            tag_ids=tag_ids
        )

        # Apply search filter if provided
        if search:
            keyword_query = keyword_query.where(Keyword.keyword_text.ilike(f"%{search}%"))

        keyword_query = keyword_query.group_by(Keyword.keyword_text).order_by(
            func.count(func.distinct(MediaKeyword.media_id)).desc()
        ).offset(offset).limit(limit)

        result = await session.execute(keyword_query)
        keyword_results = result.all()

        top_keywords = [
            {"keyword": keyword_text, "count": count}
            for keyword_text, count in keyword_results
        ]

        # Get total count (with search filter if applicable)
        count_query = select(func.count(Keyword.id))
        if search:
            count_query = count_query.where(Keyword.keyword_text.ilike(f"%{search}%"))
        total_count_result = await session.execute(count_query)
        total_unique = total_count_result.scalar()

        return {
            "keywords": top_keywords,
            "total_unique": total_unique,
            "offset": offset,
            "limit": limit
        }
    else:
        # Preview counts behavior using normalized keyword tables
        settings = get_settings()

        # Handle similarity search
        base_item_ids = None
        if similar_to is not None and similar_face_to is not None:
            raise HTTPException(status_code=400, detail="Cannot combine similar_to and similar_face_to")

        if similar_face_to is not None:
            similar_face_to_ids = parse_similarity_ids(similar_face_to, "similar_face_to")
            query = select(MediaItem).where(MediaItem.deleted_at.is_(None))
            query = query.where(MediaItem.metadata_status == 'completed')
            query = query.where(
                (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
            )
            similar_items, _ = await filter_media_query_by_face_similarity(
                session,
                query,
                similar_face_to_ids,
                similarity_threshold,
            )
            similar_ids = {item.id for item in similar_items}
            base_item_ids = list(similar_ids) if similar_ids else [0]
        elif similar_to is not None:
            similar_to_ids = [int(id_str.strip()) for id_str in similar_to.split(',') if id_str.strip()]

            if similar_to_ids:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id.in_(similar_to_ids))
                )
                reference_items = result.scalars().all()

                if reference_items and all(item.clip_embedding is not None for item in reference_items):
                    from clip_service import CLIP_EMBEDDING_DIM
                    import numpy as np

                    # Filter out reference items with stale embeddings
                    reference_embeddings = []
                    for item in reference_items:
                        emb = item.get_embedding()
                        if emb is not None and emb.shape[0] == CLIP_EMBEDDING_DIM:
                            reference_embeddings.append(emb)

                    if reference_embeddings:
                        if len(reference_embeddings) == 1:
                            query_embedding = reference_embeddings[0]
                        else:
                            avg_embedding = np.mean(reference_embeddings, axis=0)
                            query_embedding = avg_embedding / np.linalg.norm(avg_embedding)

                        result = await session.execute(
                            select(MediaItem).where(MediaItem.clip_embedding.isnot(None))
                        )
                        all_items = result.scalars().all()

                        from clip_service import get_clip_service
                        clip_service = get_clip_service()
                        threshold = similarity_threshold if similarity_threshold is not None else settings.clip_similarity_threshold
                        similar_ids = set()

                        for item in all_items:
                            embedding = item.get_embedding()
                            if embedding is not None:
                                # Skip items with stale embeddings (wrong dimensions)
                                if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                                    continue
                                similarity = clip_service.compute_similarity(query_embedding, embedding)
                                if similarity >= threshold or item.id in similar_to_ids:
                                    similar_ids.add(item.id)

                        base_item_ids = list(similar_ids) if similar_ids else [0]

        # Build efficient keyword query using JOIN and GROUP BY
        keyword_query = select(
            Keyword.keyword_text,
            func.count(func.distinct(MediaItem.id)).label('count')
        ).select_from(Keyword).join(
            MediaKeyword, Keyword.id == MediaKeyword.keyword_id
        ).join(
            MediaItem, MediaKeyword.media_id == MediaItem.id
        )

        # Exclude trashed items
        keyword_query = keyword_query.where(MediaItem.deleted_at.is_(None))

        # Apply similarity filter if needed
        if base_item_ids is not None:
            keyword_query = keyword_query.where(MediaItem.id.in_(base_item_ids))

        # Apply search filter if provided
        if search:
            keyword_query = keyword_query.where(Keyword.keyword_text.ilike(f"%{search}%"))

        # Apply all non-keyword filters for preview counts
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
            exclude_category='keywords'  # Don't apply keyword filters for preview
        )

        # Group by keyword and order by count
        keyword_query = keyword_query.group_by(Keyword.keyword_text).order_by(
            func.count(func.distinct(MediaItem.id)).desc()
        ).offset(offset).limit(limit)

        # Execute single query to get top keywords with their preview counts
        result = await session.execute(keyword_query)
        keyword_results = result.all()

        top_keywords = [
            {"keyword": keyword_text, "count": count}
            for keyword_text, count in keyword_results
        ]

        # Get total count (with search filter if applicable)
        count_query = select(func.count(Keyword.id))
        if search:
            count_query = count_query.where(Keyword.keyword_text.ilike(f"%{search}%"))
        total_count_result = await session.execute(count_query)
        total_unique = total_count_result.scalar()

        return {
            "keywords": top_keywords,
            "total_unique": total_unique,
            "offset": offset,
            "limit": limit
        }


@router.get("/config")
async def get_config():
    """
    Get configuration information for the frontend.
    Returns media paths (folders) for filtering.
    Uses profile-specific folders when available.
    """
    profile_id = get_current_profile()
    registry = get_database_registry()
    profile_config = registry.get_profile_config(profile_id)

    if profile_config and profile_config.folders:
        # Return profile-specific folders
        media_paths = [folder.path for folder in profile_config.folders]
    else:
        # Fall back to global settings for backward compatibility
        settings = get_settings()
        media_paths = settings.media_paths

    return {
        "media_paths": media_paths
    }


@router.get("/filter-counts")
async def get_filter_counts(
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
    similar_to: Optional[str] = Query(None, description="Comma-separated media IDs for similarity search"),
    similar_face_to: Optional[str] = Query(None, description="Comma-separated media IDs for face similarity search"),
    similarity_threshold: Optional[float] = Query(None, description="Similarity threshold (0.0-1.0)"),
    keyword_limit: int = Query(5, ge=1, le=200, description="Number of top keywords to include with counts"),
    tag_limit: int = Query(50, ge=1, le=200, description="Number of top tags to include with counts"),
    project_ids: Optional[str] = Query(None, description="Comma-separated project IDs currently selected (OR logic)"),
    excluded_project_ids: Optional[str] = Query(None, description="Comma-separated project IDs to exclude"),
    has_project: Optional[bool] = Query(None, description="True = in any project, False = in no project"),
    tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids currently selected"),
    excluded_tool_ids: Optional[str] = Query(None, description="Comma-separated full_tool_ids to exclude"),
    tool_limit: int = Query(50, ge=1, le=200, description="Number of top tools to include with counts"),
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get preview counts for each filter option.
    Returns counts showing how many items would match if that option were selected,
    based on current filters.
    """
    settings = get_settings()
    video_formats = ['mp4', 'webm', 'mov', 'avi', 'mkv']
    image_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
    audio_formats = ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']
    text_formats = ['md']
    set_formats = ['stimmaset.json']
    grid_formats = ['stimmagrid.json']

    # Handle similarity search to get base item IDs
    base_item_ids = None
    if similar_to is not None and similar_face_to is not None:
        raise HTTPException(status_code=400, detail="Cannot combine similar_to and similar_face_to")

    if similar_face_to is not None:
        similar_face_to_ids = parse_similarity_ids(similar_face_to, "similar_face_to")

        query = select(MediaItem).where(MediaItem.deleted_at.is_(None))
        query = query.where(MediaItem.metadata_status == 'completed')
        query = query.where(
            (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
        )
        similar_items, _ = await filter_media_query_by_face_similarity(
            session,
            query,
            similar_face_to_ids,
            similarity_threshold,
        )
        similar_ids = {item.id for item in similar_items}
        base_item_ids = list(similar_ids) if similar_ids else [0]
    elif similar_to is not None:
        similar_to_ids = [int(id_str.strip()) for id_str in similar_to.split(',') if id_str.strip()]

        if similar_to_ids:
            # Get reference items
            result = await session.execute(
                select(MediaItem).where(MediaItem.id.in_(similar_to_ids))
            )
            reference_items = result.scalars().all()

            if reference_items and all(item.clip_embedding is not None for item in reference_items):
                from clip_service import CLIP_EMBEDDING_DIM
                import numpy as np

                # Filter out reference items with stale embeddings
                reference_embeddings = []
                for item in reference_items:
                    emb = item.get_embedding()
                    if emb is not None and emb.shape[0] == CLIP_EMBEDDING_DIM:
                        reference_embeddings.append(emb)

                if reference_embeddings:
                    # Average if multiple references
                    if len(reference_embeddings) == 1:
                        query_embedding = reference_embeddings[0]
                    else:
                        avg_embedding = np.mean(reference_embeddings, axis=0)
                        query_embedding = avg_embedding / np.linalg.norm(avg_embedding)

                    # Get all items with embeddings
                    query = select(MediaItem).where(MediaItem.clip_embedding.isnot(None))
                    query = query.where(MediaItem.deleted_at.is_(None))
                    query = query.where(MediaItem.metadata_status == 'completed')
                    query = query.where(
                        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
                    )
                    result = await session.execute(query)
                    all_items = result.scalars().all()

                    # Compute similarities
                    from clip_service import get_clip_service
                    clip_service = get_clip_service()
                    threshold = similarity_threshold if similarity_threshold is not None else settings.clip_similarity_threshold
                    similar_ids = set()

                    for item in all_items:
                        embedding = item.get_embedding()
                        if embedding is not None:
                            # Skip items with stale embeddings (wrong dimensions)
                            if embedding.shape[0] != CLIP_EMBEDDING_DIM:
                                continue
                            similarity = clip_service.compute_similarity(query_embedding, embedding)
                            if similarity >= threshold or item.id in similar_to_ids:
                                similar_ids.add(item.id)

                    base_item_ids = list(similar_ids) if similar_ids else [0]

    # Helper to build base query with similarity filter
    def get_base_query():
        q = select(func.count(MediaItem.id)).select_from(MediaItem)

        # Exclude trashed items
        q = q.where(MediaItem.deleted_at.is_(None))

        # Only count items with completed metadata (have file_hash for thumbnails)
        q = q.where(MediaItem.metadata_status == 'completed')

        # Exclude unavailable files (files not found on disk)
        q = q.where(
            (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
        )

        if base_item_ids is not None:
            q = q.where(MediaItem.id.in_(base_item_ids))
        return q

    # Media type preview counts (exclude media_types category from filters)
    images_query = get_base_query()
    images_query = build_filtered_query(
        images_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    # Add the "if I click images" condition
    images_query = images_query.where(MediaItem.file_format.in_(image_formats))
    images_result = await session.execute(images_query)
    images_count = images_result.scalar()
    videos_query = get_base_query()
    videos_query = build_filtered_query(
        videos_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    # Add the "if I click videos" condition
    videos_query = videos_query.where(MediaItem.file_format.in_(video_formats))
    videos_result = await session.execute(videos_query)
    videos_count = videos_result.scalar()
    # Audio count
    audio_query = get_base_query()
    audio_query = build_filtered_query(
        audio_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    audio_query = audio_query.where(MediaItem.file_format.in_(audio_formats))
    audio_result = await session.execute(audio_query)
    audio_count = audio_result.scalar()

    # Text count
    text_query = get_base_query()
    text_query = build_filtered_query(
        text_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    text_query = text_query.where(MediaItem.file_format.in_(text_formats))
    text_result = await session.execute(text_query)
    text_count = text_result.scalar()

    # Sets count
    sets_query = get_base_query()
    sets_query = build_filtered_query(
        sets_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    sets_query = sets_query.where(MediaItem.file_format.in_(set_formats))
    sets_result = await session.execute(sets_query)
    sets_count = sets_result.scalar()

    # Grids count
    grids_query = get_base_query()
    grids_query = build_filtered_query(
        grids_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    grids_query = grids_query.where(MediaItem.file_format.in_(grid_formats))
    grids_result = await session.execute(grids_query)
    grids_count = grids_result.scalar()

    # Layouts count
    layout_formats = ['stimmalayout']
    layouts_query = get_base_query()
    layouts_query = build_filtered_query(
        layouts_query,
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='media_types'
    )
    layouts_query = layouts_query.where(MediaItem.file_format.in_(layout_formats))
    layouts_result = await session.execute(layouts_query)
    layouts_count = layouts_result.scalar()

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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='resolutions'
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='resolutions'
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='resolutions'
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
            tool_ids=tool_ids,
            excluded_tool_ids=excluded_tool_ids,
            exclude_category='folders'
        )
        # Ensure folder path ends with / to avoid partial matches
        folder_with_slash = folder.rstrip('/') + '/'
        folder_query = folder_query.where(MediaItem.file_path.startswith(folder_with_slash))
        result = await session.execute(folder_query)
        folder_counts[folder] = result.scalar()

    # Keyword preview counts using efficient JOIN query
    # This replaces the N+1 query pattern with a single GROUP BY query
    keyword_counts_dict = {}

    # Build base query that JOINs media_items with keywords through media_keywords
    # Start with the keywords table
    keyword_query = select(
        Keyword.keyword_text,
        func.count(func.distinct(MediaItem.id)).label('count')
    ).select_from(Keyword).join(
        MediaKeyword, Keyword.id == MediaKeyword.keyword_id
    ).join(
        MediaItem, MediaKeyword.media_id == MediaItem.id
    )

    # Exclude trashed items
    keyword_query = keyword_query.where(MediaItem.deleted_at.is_(None))

    # Apply similarity filter if needed
    if base_item_ids is not None:
        keyword_query = keyword_query.where(MediaItem.id.in_(base_item_ids))

    # Apply all non-keyword filters to show preview counts
    # This shows: "Of items matching my current non-keyword filters, how many have each keyword?"
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        exclude_category='keywords'  # Don't apply keyword filters for preview
    )

    # Group by keyword and order by count
    keyword_query = keyword_query.group_by(Keyword.keyword_text).order_by(
        func.count(func.distinct(MediaItem.id)).desc()
    ).limit(keyword_limit)

    # Execute single query to get top keywords with their counts
    result = await session.execute(keyword_query)
    keyword_results = result.all()

    log.info(f"Found {len(keyword_results)} keywords for preview counts")
    for keyword_text, count in keyword_results:
        keyword_counts_dict[keyword_text] = count

    # Tag preview counts using efficient JOIN query (similar to keywords)
    # Returns list of {id, tag, usage_count} for top tags
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

    # Exclude trashed items
    tag_query = tag_query.where(MediaItem.deleted_at.is_(None))

    # Apply similarity filter if needed
    if base_item_ids is not None:
        tag_query = tag_query.where(MediaItem.id.in_(base_item_ids))

    # Apply all non-tag filters to show preview counts
    # This shows: "Of items matching my current non-tag filters, how many have each tag?"
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
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        # Don't apply tag_ids filter - we want preview counts for all tags
        exclude_category='tags'
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
    from datetime import datetime, timedelta
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
            tool_ids=tool_ids,
            excluded_tool_ids=excluded_tool_ids,
            exclude_category='date_ranges'
        )
        # Add created date filter (file creation date)
        range_query = range_query.where(MediaItem.created_date >= after_date)
        range_result = await session.execute(range_query)
        date_range_counts[range_key] = range_result.scalar()

    # This is the legacy Media filter-count endpoint. Expiration belongs to
    # Assets, whose browser uses /api/assets/filter-counts; bare Media has no
    # expiring population.
    expiring_count = 0

    # Tool lineage preview counts (exclude tools category from filters)
    tool_counts_list = []

    tool_query = select(
        MediaToolLineage.full_tool_id,
        func.count(func.distinct(MediaItem.id)).label('count')
    ).select_from(MediaToolLineage).join(
        MediaItem, MediaToolLineage.media_id == MediaItem.id
    )

    # Exclude trashed items
    tool_query = tool_query.where(MediaItem.deleted_at.is_(None))

    # Only count items with completed metadata
    tool_query = tool_query.where(MediaItem.metadata_status == 'completed')

    # Exclude unavailable files
    tool_query = tool_query.where(
        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None))
    )

    # Apply similarity filter if needed
    if base_item_ids is not None:
        tool_query = tool_query.where(MediaItem.id.in_(base_item_ids))

    # Apply all non-tool filters
    tool_query = build_filtered_query(
        tool_query,
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
        # Don't apply tool_ids filter - we want preview counts for all tools
        exclude_category='tools'
    )

    # Group by tool and order by count
    tool_query = tool_query.group_by(MediaToolLineage.full_tool_id).order_by(
        func.count(func.distinct(MediaItem.id)).desc()
    ).limit(tool_limit)

    # Execute query
    result = await session.execute(tool_query)
    tool_results = result.all()

    # Batch-fetch tool metadata from CachedProviderTool for display names
    tool_id_list = [row[0] for row in tool_results]
    tool_metadata = {}
    if tool_id_list:
        cached_result = await session.execute(
            select(CachedProviderTool.full_tool_id, CachedProviderTool.name, CachedProviderTool.provider_name, CachedProviderTool.provider_id)
            .where(CachedProviderTool.full_tool_id.in_(tool_id_list))
            .where(CachedProviderTool.deleted_at.is_(None))
        )
        for full_id, name, provider_name, provider_id in cached_result.all():
            tool_metadata[full_id] = {"name": name, "provider_name": provider_name, "provider_id": provider_id}

    # Built-in tools that don't have CachedProviderTool entries
    BUILTIN_TOOL_NAMES = {
        "builtin:stimma:image-editor": {"name": "Image Editor", "provider_name": "Stimma", "provider_id": "builtin:stimma"},
    }

    for full_tool_id, count in tool_results:
        meta = tool_metadata.get(full_tool_id) or BUILTIN_TOOL_NAMES.get(full_tool_id, {})
        tool_counts_list.append({
            "full_tool_id": full_tool_id,
            "name": meta.get("name", full_tool_id),
            "provider_name": meta.get("provider_name", ""),
            "provider_id": meta.get("provider_id", ""),
            "count": count
        })

    # Project membership preview counts. Mirrors the tags facet: shows, for items matching the
    # current non-project filters, how many are in each project, plus the "in a project" /
    # "not in a project" membership totals. exclude_category='projects' drops the project
    # predicates from the helper so these counts ignore the user's current project selection.
    project_facet_filters = dict(
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
        exclude_category='projects',
    )

    project_counts = {}
    project_query = select(
        ProjectMedia.project_id,
        func.count(func.distinct(MediaItem.id)).label('count')
    ).select_from(ProjectMedia).join(
        Project, Project.id == ProjectMedia.project_id
    ).join(
        MediaItem, ProjectMedia.media_id == MediaItem.id
    ).where(
        Project.deleted_at.is_(None),
        MediaItem.deleted_at.is_(None),
        MediaItem.metadata_status == 'completed',
        (MediaItem.file_unavailable == False) | (MediaItem.file_unavailable.is_(None)),
    )
    if base_item_ids is not None:
        project_query = project_query.where(MediaItem.id.in_(base_item_ids))
    project_query = build_filtered_query(project_query, **project_facet_filters)
    project_query = project_query.group_by(ProjectMedia.project_id)
    for pid, count in (await session.execute(project_query)).all():
        project_counts[str(pid)] = count

    # "In a project" / "Not in a project" membership totals (soft-deleted projects don't count)
    membership_exists = (
        select(1).select_from(ProjectMedia)
        .join(Project, Project.id == ProjectMedia.project_id)
        .where(ProjectMedia.media_id == MediaItem.id, Project.deleted_at.is_(None))
        .correlate(MediaItem)
        .exists()
    )
    in_any_query = build_filtered_query(get_base_query(), **project_facet_filters).where(membership_exists)
    in_any_count = (await session.execute(in_any_query)).scalar()
    not_in_any_query = build_filtered_query(get_base_query(), **project_facet_filters).where(~membership_exists)
    not_in_any_count = (await session.execute(not_in_any_query)).scalar()

    return {
        "media_type": {
            "images": images_count,
            "videos": videos_count,
            "audio": audio_count,
            "text": text_count,
            "sets": sets_count,
            "grids": grids_count,
            "layouts": layouts_count
        },
        "resolution": {
            "small": small_count,
            "medium": medium_count,
            "large": large_count
        },
        "folders": folder_counts,
        "keywords": keyword_counts_dict,
        "tags": tag_counts_list,
        "tools": tool_counts_list,
        "projects": project_counts,
        "project_membership": {"any": in_any_count, "none": not_in_any_count},
        "date_ranges": date_range_counts,
        "expiring": expiring_count
    }


@router.get("/processing/warnings")
async def get_system_warnings():
    """
    Get list of active system warnings.
    Checks FFmpeg availability and returns warning objects if missing.
    """
    from ffmpeg_checker import get_ffmpeg_checker

    warnings = []

    # Check FFmpeg availability
    checker = get_ffmpeg_checker()
    ffmpeg_available, ffprobe_available = checker.check_availability()

    if not ffmpeg_available or not ffprobe_available:
        warnings.append({
            "type": "ffmpeg_missing",
            "title": "Video tools unavailable",
            "message": "A required video component isn't installed, so video import and export won't work.",
            "action_url": "https://stimma.ai/link/ffmpeg",
            "action_label": "Install"
        })

    return {"warnings": warnings}


@router.post("/processing/recheck-ffmpeg")
async def recheck_ffmpeg():
    """
    Manually trigger FFmpeg detection check.
    Forces immediate re-check and broadcasts result via WebSocket.
    """
    from ffmpeg_checker import get_ffmpeg_checker
    from utils.websocket import ws_manager

    # Force cache invalidation for fresh check
    checker = get_ffmpeg_checker()
    checker.clear_cache()

    # Perform fresh check
    ffmpeg_available, ffprobe_available = checker.check_availability(use_cache=False)

    if not ffmpeg_available or not ffprobe_available:
        # FFmpeg is missing - broadcast warning
        missing_tools = []
        if not ffmpeg_available:
            missing_tools.append("ffmpeg")
        if not ffprobe_available:
            missing_tools.append("ffprobe")

        log.info(f"FFmpeg recheck: Missing {', '.join(missing_tools)}")

        await ws_manager.broadcast('system_warning', {
            'type': 'ffmpeg_missing',
            'title': 'Video tools unavailable',
            'message': "A required video component isn't installed, so video import and export won't work.",
            'action_url': 'https://stimma.ai/link/ffmpeg'
        }, include_profile=False)

        return {
            "status": "warning",
            "ffmpeg_available": ffmpeg_available,
            "ffprobe_available": ffprobe_available,
            "message": f"FFmpeg components missing: {', '.join(missing_tools)}"
        }
    else:
        # FFmpeg is available - broadcast cleared event
        log.info("FFmpeg recheck: All components available")

        await ws_manager.broadcast('system_warning_cleared', {
            'type': 'ffmpeg_missing'
        }, include_profile=False)

        return {
            "status": "ok",
            "ffmpeg_available": ffmpeg_available,
            "ffprobe_available": ffprobe_available,
            "message": "FFmpeg is available"
        }


class MarkWarningShownRequest(BaseModel):
    warning_type: str


@router.post("/system/warning-shown")
async def mark_system_warning_shown(request: MarkWarningShownRequest):
    """Mark a system warning as dismissed so it isn't re-shown unprompted."""
    from ffmpeg_checker import get_ffmpeg_checker

    if request.warning_type == "ffmpeg_missing":
        get_ffmpeg_checker().mark_warning_shown()

    return {"status": "success"}

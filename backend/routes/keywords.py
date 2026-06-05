"""Keyword routes."""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, literal, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem, Keyword, MediaKeyword
from core.dependencies import get_db_session
from config import get_settings
from utils.query_builder import build_filtered_query

router = APIRouter(prefix="/api/keywords", tags=["keywords"])

@router.get("/top")
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
    tag_ids: Optional[str] = Query(None, description="Comma-separated tag IDs to filter by (OR logic)"),
    similar_to: Optional[str] = Query(None, description="Comma-separated media IDs for similarity search"),
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
        if similar_to is not None:
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
            tag_ids=tag_ids,
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


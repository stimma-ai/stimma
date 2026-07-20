"""Asset-first identity and contextual-Media APIs used during cutover."""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from asset_service import (
    AssetServiceError,
    create_asset_from_media,
    restore_asset,
    restore_revision_as_latest,
    trash_asset,
)
from asset_association_service import (
    attach_asset_to_project,
    broadcast_asset_organization_updated,
    detach_asset_from_project,
    set_asset_marker,
    set_asset_tag,
)
from core.profile_context import get_current_profile
from core.logging import get_logger
from database import (
    Asset,
    AssetMarker,
    AssetRevision,
    AssetTag,
    Board,
    BoardAssetItem,
    BoardSection,
    Chat,
    ContainerMember,
    Marker,
    MediaItem,
    MediaOwner,
    StorageObject,
    Tag,
    Keyword,
    MediaKeyword,
    MediaToolLineage,
    CachedProviderTool,
    Project,
    ProjectAsset,
)
from core.dependencies import get_db_session
from utils.query_builder import (
    AUDIO_FORMATS,
    GRID_FORMATS,
    IMAGE_FORMATS,
    LAYOUT_FORMATS,
    RESOLUTION_MAP,
    SET_FORMATS,
    TEXT_FORMATS,
    VIDEO_FORMATS,
    asset_unused_predicate,
    build_filtered_query,
    media_is_imported,
)
from utils.websocket import ws_manager


router = APIRouter(prefix="/api/assets", tags=["assets"])
log = get_logger(__name__)


class AssetIdsRequest(BaseModel):
    asset_ids: list[int]


class AssetMarkerBatchRequest(AssetIdsRequest):
    marker_id: int
    add: bool = True


class AssetTagsRequest(BaseModel):
    tags: list[str]


class AssetTagBatchRequest(AssetIdsRequest):
    tag_texts: list[str] = []
    remove_tag_ids: list[int] = []


def _projection(asset: Asset, revision: AssetRevision, media: MediaItem) -> dict:
    return {
        "asset": asset.to_dict(),
        "revision": revision.to_dict(),
        "media": media.to_dict(),
    }


async def _browser_projections(session: AsyncSession, rows) -> list[dict]:
    """Flatten Asset identity over its current Media payload for shared browsers."""
    asset_ids = [asset.id for asset, _, _ in rows]
    markers: dict[int, list[dict]] = defaultdict(list)
    tags: dict[int, list[dict]] = defaultdict(list)
    revision_counts: dict[int, int] = {}
    if asset_ids:
        revision_counts = dict(
            (
                await session.execute(
                    select(AssetRevision.asset_id, func.count(AssetRevision.id))
                    .where(
                        AssetRevision.asset_id.in_(asset_ids),
                        AssetRevision.deleted_at.is_(None),
                    )
                    .group_by(AssetRevision.asset_id)
                )
            ).all()
        )
        marker_rows = (
            await session.execute(
                select(AssetMarker, Marker)
                .join(Marker, Marker.id == AssetMarker.marker_id)
                .where(
                    AssetMarker.asset_id.in_(asset_ids),
                    AssetMarker.deleted_at.is_(None),
                    AssetMarker.source != "suppressed",
                )
            )
        ).all()
        for association, marker in marker_rows:
            markers[association.asset_id].append(
                {**marker.to_dict(), "source": association.source}
            )
        tag_rows = (
            await session.execute(
                select(AssetTag, Tag)
                .join(Tag, Tag.id == AssetTag.tag_id)
                .where(
                    AssetTag.asset_id.in_(asset_ids),
                    AssetTag.deleted_at.is_(None),
                )
            )
        ).all()
        for association, tag in tag_rows:
            tags[association.asset_id].append(tag.to_dict())

    result = []
    for asset, revision, media in rows:
        item = media.to_dict()
        item.update(
            {
                "id": asset.id,
                "asset_id": asset.id,
                "media_id": media.id,
                "revision_id": revision.id,
                "revision_number": revision.revision_number,
                "revision_count": revision_counts.get(asset.id, 1),
                "asset_state": asset.state,
                "asset_title": asset.title,
                "asset_created_at": asset.created_at.isoformat(),
                "asset_updated_at": asset.updated_at.isoformat(),
                "media_deleted_at": item.get("deleted_at"),
                "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
                "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
                "markers": markers[asset.id],
                "tags": tags[asset.id],
            }
        )
        result.append(item)
    return result


def _asset_browser_base(state: str):
    deleted_condition = (
        Asset.deleted_at.is_(None) if state == "active" else Asset.deleted_at.is_not(None)
    )
    query = (
        select(Asset, AssetRevision, MediaItem)
        .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
        .outerjoin(StorageObject, StorageObject.id == MediaItem.storage_object_id)
        .where(
            Asset.state == state,
            deleted_condition,
            AssetRevision.deleted_at.is_(None),
            MediaItem.deleted_at.is_(None),
            MediaItem.metadata_status == "completed",
            or_(MediaItem.file_unavailable.is_(False), MediaItem.file_unavailable.is_(None)),
        )
    )
    if state == "active":
        query = query.where(
            or_(Asset.expires_at.is_(None), Asset.expires_at > datetime.utcnow())
        )
    return query


def _apply_asset_filters(query, **filters):
    return build_filtered_query(
        query,
        caption_query=filters.get("caption_query"),
        prompt_query=filters.get("prompt_query"),
        media_types=filters.get("media_types"),
        excluded_media_types=filters.get("excluded_media_types"),
        resolutions=filters.get("resolutions"),
        excluded_resolutions=filters.get("excluded_resolutions"),
        keywords=filters.get("keywords"),
        excluded_keywords=filters.get("excluded_keywords"),
        folders=filters.get("folders"),
        excluded_folders=filters.get("excluded_folders"),
        is_generated=filters.get("is_generated"),
        is_imported=filters.get("is_imported"),
        marker_ids=filters.get("marker_ids"),
        excluded_marker_ids=filters.get("excluded_marker_ids"),
        tag_ids=filters.get("tag_ids"),
        excluded_tag_ids=filters.get("excluded_tag_ids"),
        project_ids=filters.get("project_ids"),
        excluded_project_ids=filters.get("excluded_project_ids"),
        has_project=filters.get("has_project"),
        tool_ids=filters.get("tool_ids"),
        excluded_tool_ids=filters.get("excluded_tool_ids"),
        tool_id=filters.get("tool_id"),
        preset_id=filters.get("preset_id"),
        created_after=filters.get("created_after"),
        created_before=filters.get("created_before"),
        show_expiring=filters.get("show_expiring"),
        exclude_expiring=filters.get("exclude_expiring"),
        is_unused=filters.get("is_unused"),
        min_mp=filters.get("min_mp"),
        max_mp=filters.get("max_mp"),
        exclude_expired=False,
        exclude_category=filters.get("exclude_category"),
        asset_id_column=Asset.id,
        expiration_column=Asset.expires_at,
    )
@router.get("")
async def list_assets(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: str = Query("active", pattern="^(active|trashed)$"),
    session: AsyncSession = Depends(get_db_session),
):
    conditions = [Asset.state == state]
    conditions.append(Asset.deleted_at.is_(None) if state == "active" else Asset.deleted_at.is_not(None))
    base = (
        select(Asset, AssetRevision, MediaItem)
        .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
        .where(
            *conditions,
            AssetRevision.deleted_at.is_(None),
            MediaItem.deleted_at.is_(None),
        )
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.execute(
            base.order_by(Asset.updated_at.desc(), Asset.id.desc()).offset(offset).limit(limit)
        )
    ).all()
    return {
        "items": [_projection(*row) for row in rows],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/browse")
async def browse_assets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    state: str = Query("active", pattern="^(active|trashed)$"),
    caption_query: str | None = None,
    prompt_query: str | None = None,
    media_types: str | None = None,
    excluded_media_types: str | None = None,
    resolutions: str | None = None,
    excluded_resolutions: str | None = None,
    keywords: str | None = None,
    excluded_keywords: str | None = None,
    folders: str | None = None,
    excluded_folders: str | None = None,
    similar_to: str | None = None,
    similar_face_to: str | None = None,
    similar_to_text: str | None = None,
    similarity_threshold: float | None = None,
    similarity_cutoff: str | None = Query(None, pattern="^(auto)$"),
    is_generated: bool | None = None,
    is_imported: bool | None = None,
    marker_ids: str | None = None,
    excluded_marker_ids: str | None = None,
    tag_ids: str | None = None,
    excluded_tag_ids: str | None = None,
    project_id: int | None = None,
    project_ids: str | None = None,
    excluded_project_ids: str | None = None,
    has_project: bool | None = None,
    tool_ids: str | None = None,
    excluded_tool_ids: str | None = None,
    tool_id: str | None = None,
    preset_id: int | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    show_expiring: bool | None = None,
    exclude_expiring: bool | None = None,
    is_unused: bool | None = None,
    min_mp: float | None = None,
    max_mp: float | None = None,
    sort_by: str = Query(
        "created_desc",
        pattern="^(created_desc|created_asc|indexed_desc|indexed_asc|deleted_desc|deleted_asc|random|similarity)$",
    ),
    random_seed: int | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Asset browser projection; identity is Asset, payload fields are current Media."""
    effective_projects = project_ids
    if project_id is not None:
        effective_projects = ",".join(
            part for part in (project_ids, str(project_id)) if part
        )
    query = _apply_asset_filters(
        _asset_browser_base(state),
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
        is_imported=is_imported,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        project_ids=effective_projects,
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
        is_unused=is_unused,
        min_mp=min_mp,
        max_mp=max_mp,
        state=state,
    )
    if folders:
        query = query.where(StorageObject.kind == "external")

    similarity_modes = sum(
        value is not None for value in (similar_to, similar_face_to, similar_to_text)
    )
    if similarity_modes > 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine similarity search modes",
        )

    if similarity_modes:
        from config import get_settings
        from utils.similarity import (
            compute_relevance_cutoff,
            filter_items_by_face_similarity,
            parse_similarity_ids,
        )

        rows = (await session.execute(query)).all()
        media_items = [row[2] for row in rows]
        scores: dict[int, float] = {}
        reference_ids: list[int] = []
        if similar_face_to is not None:
            reference_ids = parse_similarity_ids(similar_face_to, "similar_face_to")
            matched, scores = await filter_items_by_face_similarity(
                session, media_items, reference_ids, similarity_threshold
            )
            matched_ids = {media.id for media in matched}
            rows = [row for row in rows if row[2].id in matched_ids]
        else:
            from clip_service import CLIP_EMBEDDING_DIM, get_clip_service
            import numpy as np

            clip = get_clip_service()
            if similar_to_text is not None:
                if not similar_to_text.strip():
                    raise HTTPException(
                        status_code=400, detail="similar_to_text cannot be empty"
                    )
                query_embedding = clip.encode_text(similar_to_text.strip())
                floor = get_settings().clip_text_similarity_threshold
            else:
                reference_ids = parse_similarity_ids(similar_to or "", "similar_to")
                references = list(
                    await session.scalars(
                        select(MediaItem).where(MediaItem.id.in_(reference_ids))
                    )
                )
                if len(references) != len(reference_ids):
                    raise HTTPException(
                        status_code=404, detail="One or more reference assets not found"
                    )
                embeddings = []
                for reference in references:
                    embedding = reference.get_embedding()
                    if embedding is None or embedding.shape[0] != CLIP_EMBEDDING_DIM:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Reference asset {reference.id} has no current CLIP embedding",
                        )
                    embeddings.append(embedding)
                query_embedding = np.mean(embeddings, axis=0)
                query_embedding = query_embedding / np.linalg.norm(query_embedding)
                floor = get_settings().clip_similarity_threshold

            valid_rows = []
            raw_scores = []
            for row in rows:
                media = row[2]
                embedding = media.get_embedding()
                if embedding is None or embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    continue
                score = float(clip.compute_similarity(query_embedding, embedding))
                scores[media.id] = score
                raw_scores.append(score)
                valid_rows.append(row)
            threshold = similarity_threshold if similarity_threshold is not None else floor
            if (
                similar_to_text is not None
                and similarity_cutoff == "auto"
                and similarity_threshold is None
            ):
                threshold = compute_relevance_cutoff(
                    raw_scores, absolute_floor=threshold
                )
            rows = [
                row
                for row in valid_rows
                if row[2].id in reference_ids or scores[row[2].id] >= threshold
            ]

        if sort_by == "created_asc":
            rows.sort(key=lambda row: row[2].created_date or row[2].indexed_date)
        elif sort_by == "created_desc":
            rows.sort(
                key=lambda row: row[2].created_date or row[2].indexed_date,
                reverse=True,
            )
        else:
            rows.sort(key=lambda row: scores.get(row[2].id, -1), reverse=True)
        total = len(rows)
        offset = (page - 1) * page_size
        page_rows = rows[offset:offset + page_size]
        items = await _browser_projections(session, page_rows)
        for item in items:
            if item["media_id"] in scores:
                item["similarity_score"] = scores[item["media_id"]]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "reference_ids": reference_ids or None,
        }

    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort_by == "created_asc":
        query = query.order_by(MediaItem.created_date.asc().nulls_last(), Asset.id.asc())
    elif sort_by == "indexed_desc":
        query = query.order_by(MediaItem.indexed_date.desc(), Asset.id.desc())
    elif sort_by == "indexed_asc":
        query = query.order_by(MediaItem.indexed_date.asc(), Asset.id.asc())
    elif sort_by == "deleted_desc":
        query = query.order_by(Asset.deleted_at.desc(), Asset.id.desc())
    elif sort_by == "deleted_asc":
        query = query.order_by(Asset.deleted_at.asc(), Asset.id.asc())
    elif sort_by == "random":
        multiplier = literal((random_seed if random_seed is not None else 42) | 1)
        product = MediaItem.random_sort_value * multiplier
        query = query.order_by(product - func.cast(product, Integer), Asset.id)
    else:
        query = query.order_by(MediaItem.created_date.desc().nulls_last(), Asset.id.desc())

    rows = (
        await session.execute(query.offset((page - 1) * page_size).limit(page_size))
    ).all()
    return {
        "items": await _browser_projections(session, rows),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/browse/ids")
async def browse_asset_ids(
    state: str = Query("active", pattern="^(active|trashed)$"),
    caption_query: str | None = None,
    prompt_query: str | None = None,
    media_types: str | None = None,
    excluded_media_types: str | None = None,
    resolutions: str | None = None,
    excluded_resolutions: str | None = None,
    keywords: str | None = None,
    excluded_keywords: str | None = None,
    folders: str | None = None,
    excluded_folders: str | None = None,
    similar_to: str | None = None,
    similar_face_to: str | None = None,
    similar_to_text: str | None = None,
    similarity_threshold: float | None = None,
    similarity_cutoff: str | None = Query(None, pattern="^(auto)$"),
    is_generated: bool | None = None,
    is_imported: bool | None = None,
    marker_ids: str | None = None,
    excluded_marker_ids: str | None = None,
    tag_ids: str | None = None,
    excluded_tag_ids: str | None = None,
    project_id: int | None = None,
    project_ids: str | None = None,
    excluded_project_ids: str | None = None,
    has_project: bool | None = None,
    tool_ids: str | None = None,
    excluded_tool_ids: str | None = None,
    tool_id: str | None = None,
    preset_id: int | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    show_expiring: bool | None = None,
    exclude_expiring: bool | None = None,
    is_unused: bool | None = None,
    min_mp: float | None = None,
    max_mp: float | None = None,
    sort_by: str = Query("created_desc"),
    random_seed: int | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Ordered Asset IDs for select-all; deliberately never returns Media IDs."""
    if any(value is not None for value in (similar_to, similar_face_to, similar_to_text)):
        # Keep select-all semantics exactly aligned with the projected browser.
        # This is an internal call, so the large page bypasses the HTTP page-size
        # guard and computes/ranks similarity only once.
        result = await browse_assets(
            page=1,
            page_size=10_000_000,
            state=state,
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
            similar_to=similar_to,
            similar_face_to=similar_face_to,
            similar_to_text=similar_to_text,
            similarity_threshold=similarity_threshold,
            similarity_cutoff=similarity_cutoff,
            is_generated=is_generated,
            is_imported=is_imported,
            marker_ids=marker_ids,
            excluded_marker_ids=excluded_marker_ids,
            tag_ids=tag_ids,
            excluded_tag_ids=excluded_tag_ids,
            project_id=project_id,
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
            is_unused=is_unused,
            min_mp=min_mp,
            max_mp=max_mp,
            sort_by=sort_by,
            random_seed=random_seed,
            session=session,
        )
        return {"ids": [item["asset_id"] for item in result["items"]]}

    effective_projects = ",".join(
        part for part in (project_ids, str(project_id) if project_id is not None else None) if part
    ) or None
    query = _apply_asset_filters(
        _asset_browser_base(state),
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
        is_imported=is_imported,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        project_ids=effective_projects,
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
        is_unused=is_unused,
        state=state,
    )
    if folders:
        query = query.where(StorageObject.kind == "external")
    query = query.with_only_columns(Asset.id)
    if sort_by == "created_asc":
        query = query.order_by(MediaItem.created_date.asc().nulls_last(), Asset.id.asc())
    elif sort_by == "indexed_desc":
        query = query.order_by(MediaItem.indexed_date.desc(), Asset.id.desc())
    elif sort_by == "indexed_asc":
        query = query.order_by(MediaItem.indexed_date.asc(), Asset.id.asc())
    elif sort_by == "deleted_desc":
        query = query.order_by(Asset.deleted_at.desc(), Asset.id.desc())
    elif sort_by == "deleted_asc":
        query = query.order_by(Asset.deleted_at.asc(), Asset.id.asc())
    else:
        query = query.order_by(MediaItem.created_date.desc().nulls_last(), Asset.id.desc())
    return {"ids": list(await session.scalars(query))}


async def _similarity_media_ids_for_facets(
    session: AsyncSession,
    *,
    state: str,
    similar_to: str | None,
    similar_face_to: str | None,
    similar_to_text: str | None,
    similarity_threshold: float | None,
) -> list[int] | None:
    if not any(value is not None for value in (similar_to, similar_face_to, similar_to_text)):
        return None
    result = await browse_assets(
        page=1,
        page_size=10_000_000,
        state=state,
        similar_to=similar_to,
        similar_face_to=similar_face_to,
        similar_to_text=similar_to_text,
        similarity_threshold=similarity_threshold,
        similarity_cutoff=None,
        sort_by="created_desc",
        session=session,
    )
    return [item["media_id"] for item in result["items"]]


def _asset_facet_query(
    *,
    state: str,
    filters: dict,
    exclude_category: str | None = None,
    similarity_media_ids: list[int] | None = None,
):
    query = _apply_asset_filters(
        _asset_browser_base(state),
        **filters,
        state=state,
        exclude_category=exclude_category,
    )
    if filters.get("folders") and exclude_category != "folders":
        query = query.where(StorageObject.kind == "external")
    if similarity_media_ids is not None:
        query = query.where(MediaItem.id.in_(similarity_media_ids or [0]))
    return query


async def _count_assets(session: AsyncSession, query) -> int:
    count_query = query.with_only_columns(
        func.count(func.distinct(Asset.id))
    ).order_by(None)
    return await session.scalar(count_query) or 0


def _facet_filters(**values) -> dict:
    return {key: value for key, value in values.items() if value is not None}


@router.get("/keywords/top")
async def get_asset_top_keywords(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    state: str = Query("active", pattern="^(active|trashed)$"),
    caption_query: str | None = None,
    prompt_query: str | None = None,
    media_types: str | None = None,
    excluded_media_types: str | None = None,
    resolutions: str | None = None,
    excluded_resolutions: str | None = None,
    folders: str | None = None,
    excluded_folders: str | None = None,
    is_generated: bool | None = None,
    is_imported: bool | None = None,
    marker_ids: str | None = None,
    excluded_marker_ids: str | None = None,
    tag_ids: str | None = None,
    excluded_tag_ids: str | None = None,
    project_ids: str | None = None,
    excluded_project_ids: str | None = None,
    has_project: bool | None = None,
    tool_ids: str | None = None,
    excluded_tool_ids: str | None = None,
    similar_to: str | None = None,
    similar_face_to: str | None = None,
    similar_to_text: str | None = None,
    similarity_threshold: float | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """Keyword vocabulary/counts over current Asset revisions only."""
    filters = _facet_filters(
        caption_query=caption_query,
        prompt_query=prompt_query,
        media_types=media_types,
        excluded_media_types=excluded_media_types,
        resolutions=resolutions,
        excluded_resolutions=excluded_resolutions,
        folders=folders,
        excluded_folders=excluded_folders,
        is_generated=is_generated,
        is_imported=is_imported,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        project_ids=project_ids,
        excluded_project_ids=excluded_project_ids,
        has_project=has_project,
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
    )
    similarity_ids = await _similarity_media_ids_for_facets(
        session,
        state=state,
        similar_to=similar_to,
        similar_face_to=similar_face_to,
        similar_to_text=similar_to_text,
        similarity_threshold=similarity_threshold,
    )
    query = _asset_facet_query(
        state=state,
        filters=filters,
        exclude_category="keywords",
        similarity_media_ids=similarity_ids,
    ).join(MediaKeyword, MediaKeyword.media_id == MediaItem.id).join(
        Keyword, Keyword.id == MediaKeyword.keyword_id
    )
    if search:
        query = query.where(Keyword.keyword_text.ilike(f"%{search}%"))
    rows = (
        await session.execute(
            query.with_only_columns(
                Keyword.keyword_text,
                func.count(func.distinct(Asset.id)).label("count"),
            )
            .group_by(Keyword.keyword_text)
            .order_by(func.count(func.distinct(Asset.id)).desc(), Keyword.keyword_text)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    total_query = query.with_only_columns(
        func.count(func.distinct(Keyword.id))
    ).order_by(None)
    return {
        "keywords": [
            {"keyword": keyword_text, "count": count}
            for keyword_text, count in rows
        ],
        "total_unique": await session.scalar(total_query) or 0,
        "offset": offset,
        "limit": limit,
    }


@router.get("/filter-counts")
async def get_asset_filter_counts(
    state: str = Query("active", pattern="^(active|trashed)$"),
    caption_query: str | None = None,
    prompt_query: str | None = None,
    media_types: str | None = None,
    excluded_media_types: str | None = None,
    resolutions: str | None = None,
    excluded_resolutions: str | None = None,
    keywords: str | None = None,
    excluded_keywords: str | None = None,
    folders: str | None = None,
    excluded_folders: str | None = None,
    is_generated: bool | None = None,
    is_imported: bool | None = None,
    marker_ids: str | None = None,
    excluded_marker_ids: str | None = None,
    tag_ids: str | None = None,
    excluded_tag_ids: str | None = None,
    project_ids: str | None = None,
    excluded_project_ids: str | None = None,
    has_project: bool | None = None,
    tool_ids: str | None = None,
    excluded_tool_ids: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    show_expiring: bool | None = None,
    exclude_expiring: bool | None = None,
    is_unused: bool | None = None,
    similar_to: str | None = None,
    similar_face_to: str | None = None,
    similar_to_text: str | None = None,
    similarity_threshold: float | None = None,
    keyword_limit: int = Query(50, ge=1, le=200),
    tag_limit: int = Query(50, ge=1, le=200),
    tool_limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
):
    """Facet preview counts over Asset identity and current Revision payloads."""
    filters = _facet_filters(
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
        is_imported=is_imported,
        marker_ids=marker_ids,
        excluded_marker_ids=excluded_marker_ids,
        tag_ids=tag_ids,
        excluded_tag_ids=excluded_tag_ids,
        project_ids=project_ids,
        excluded_project_ids=excluded_project_ids,
        has_project=has_project,
        tool_ids=tool_ids,
        excluded_tool_ids=excluded_tool_ids,
        created_after=created_after,
        created_before=created_before,
        show_expiring=show_expiring,
        exclude_expiring=exclude_expiring,
        is_unused=is_unused,
    )
    similarity_ids = await _similarity_media_ids_for_facets(
        session,
        state=state,
        similar_to=similar_to,
        similar_face_to=similar_face_to,
        similar_to_text=similar_to_text,
        similarity_threshold=similarity_threshold,
    )

    def facet(category: str | None = None):
        return _asset_facet_query(
            state=state,
            filters=filters,
            exclude_category=category,
            similarity_media_ids=similarity_ids,
        )

    type_formats = {
        "images": IMAGE_FORMATS,
        "videos": VIDEO_FORMATS,
        "audio": AUDIO_FORMATS,
        "text": TEXT_FORMATS,
        "sets": SET_FORMATS,
        "grids": GRID_FORMATS,
        "layouts": LAYOUT_FORMATS,
    }
    media_type_counts = {
        name: await _count_assets(
            session,
            facet("media_types").where(MediaItem.file_format.in_(formats)),
        )
        for name, formats in type_formats.items()
    }
    resolution_counts = {}
    for name, (minimum, maximum) in RESOLUTION_MAP.items():
        query = facet("resolutions")
        if minimum is not None:
            query = query.where(MediaItem.megapixels >= minimum)
        if maximum is not None:
            query = query.where(MediaItem.megapixels < maximum)
        resolution_counts[name] = await _count_assets(session, query)

    keyword_query = facet("keywords").join(
        MediaKeyword, MediaKeyword.media_id == MediaItem.id
    ).join(Keyword, Keyword.id == MediaKeyword.keyword_id)
    keyword_rows = (
        await session.execute(
            keyword_query.with_only_columns(
                Keyword.keyword_text,
                func.count(func.distinct(Asset.id)),
            )
            .group_by(Keyword.keyword_text)
            .order_by(func.count(func.distinct(Asset.id)).desc())
            .limit(keyword_limit)
        )
    ).all()

    tag_query = facet("tags").join(
        AssetTag,
        (AssetTag.asset_id == Asset.id) & AssetTag.deleted_at.is_(None),
    ).join(Tag, Tag.id == AssetTag.tag_id)
    tag_rows = (
        await session.execute(
            tag_query.with_only_columns(
                Tag.id,
                Tag.tag_text,
                func.count(func.distinct(Asset.id)),
            )
            .group_by(Tag.id, Tag.tag_text)
            .order_by(func.count(func.distinct(Asset.id)).desc())
            .limit(tag_limit)
        )
    ).all()

    tool_query = facet("tools").join(
        MediaToolLineage, MediaToolLineage.media_id == MediaItem.id
    )
    tool_rows = (
        await session.execute(
            tool_query.with_only_columns(
                MediaToolLineage.full_tool_id,
                func.count(func.distinct(Asset.id)),
            )
            .group_by(MediaToolLineage.full_tool_id)
            .order_by(func.count(func.distinct(Asset.id)).desc())
            .limit(tool_limit)
        )
    ).all()
    tool_metadata = {}
    tool_ids_found = [full_tool_id for full_tool_id, _ in tool_rows]
    if tool_ids_found:
        metadata_rows = (
            await session.execute(
                select(
                    CachedProviderTool.full_tool_id,
                    CachedProviderTool.name,
                    CachedProviderTool.provider_name,
                    CachedProviderTool.provider_id,
                ).where(
                    CachedProviderTool.full_tool_id.in_(tool_ids_found),
                    CachedProviderTool.deleted_at.is_(None),
                )
            )
        ).all()
        tool_metadata = {
            full_id: {
                "name": name,
                "provider_name": provider_name,
                "provider_id": provider_id,
            }
            for full_id, name, provider_name, provider_id in metadata_rows
        }

    project_query = facet("projects").join(
        ProjectAsset,
        (ProjectAsset.asset_id == Asset.id) & ProjectAsset.deleted_at.is_(None),
    ).join(
        Project,
        (Project.id == ProjectAsset.project_id) & Project.deleted_at.is_(None),
    )
    project_rows = (
        await session.execute(
            project_query.with_only_columns(
                ProjectAsset.project_id,
                func.count(func.distinct(Asset.id)),
            ).group_by(ProjectAsset.project_id)
        )
    ).all()
    project_exists = (
        select(1)
        .select_from(ProjectAsset)
        .join(Project, Project.id == ProjectAsset.project_id)
        .where(
            ProjectAsset.asset_id == Asset.id,
            ProjectAsset.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
        .correlate(Asset)
        .exists()
    )

    date_ranges = {
        "2hrs": timedelta(hours=2),
        "24hrs": timedelta(hours=24),
        "72hrs": timedelta(hours=72),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "365d": timedelta(days=365),
    }
    now = datetime.utcnow()
    date_counts = {
        name: await _count_assets(
            session,
            facet("date_ranges").where(MediaItem.created_date >= now - delta),
        )
        for name, delta in date_ranges.items()
    }

    folder_counts = {}
    from database_registry import get_database_registry
    profile_config = get_database_registry().get_profile_config(get_current_profile())
    folder_paths = [folder.path for folder in (profile_config.folders if profile_config else [])]
    for folder in folder_paths:
        prefix = folder.rstrip("/") + "/"
        folder_counts[folder] = await _count_assets(
            session,
            facet("folders").where(
                StorageObject.kind == "external",
                MediaItem.file_path.startswith(prefix),
            ),
        )

    return {
        "media_type": media_type_counts,
        "resolution": resolution_counts,
        "folders": folder_counts,
        "keywords": {text: count for text, count in keyword_rows},
        "tags": [
            {"id": tag_id, "tag": text, "usage_count": count}
            for tag_id, text, count in tag_rows
        ],
        "tools": [
            {
                "full_tool_id": full_id,
                "name": tool_metadata.get(full_id, {}).get("name", full_id),
                "provider_name": tool_metadata.get(full_id, {}).get("provider_name", ""),
                "provider_id": tool_metadata.get(full_id, {}).get("provider_id", ""),
                "count": count,
            }
            for full_id, count in tool_rows
        ],
        "projects": {str(project_id): count for project_id, count in project_rows},
        "project_membership": {
            "any": await _count_assets(session, facet("projects").where(project_exists)),
            "none": await _count_assets(session, facet("projects").where(~project_exists)),
        },
        "date_ranges": date_counts,
        "imported": await _count_assets(
            session,
            facet("imported").where(media_is_imported()),
        ),
        "expiring": await _count_assets(
            session,
            facet("expiring").where(Asset.expires_at.is_not(None)),
        ),
        "unused": await _count_assets(
            session,
            facet("unused").where(asset_unused_predicate(Asset.id)),
        ),
    }


async def _live_asset_or_404(session: AsyncSession, asset_id: int) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.state != "active":
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


async def _asset_markers(session: AsyncSession, asset_id: int) -> list[dict]:
    rows = (
        await session.execute(
            select(AssetMarker, Marker)
            .join(Marker, Marker.id == AssetMarker.marker_id)
            .where(
                AssetMarker.asset_id == asset_id,
                AssetMarker.deleted_at.is_(None),
                AssetMarker.source != "suppressed",
            )
        )
    ).all()
    return [{**marker.to_dict(), "source": row.source} for row, marker in rows]


@router.get("/item/{asset_id}/markers")
async def get_asset_markers(asset_id: int, session: AsyncSession = Depends(get_db_session)):
    await _live_asset_or_404(session, asset_id)
    return await _asset_markers(session, asset_id)


@router.get("/tags")
async def get_asset_tags(
    with_counts: bool = Query(False),
    session: AsyncSession = Depends(get_db_session),
):
    if not with_counts:
        tags = list(await session.scalars(select(Tag).order_by(Tag.tag_text.asc())))
        return [tag.to_dict() for tag in tags]
    rows = (
        await session.execute(
            select(Tag, func.count(Asset.id).label("usage_count"))
            .outerjoin(
                AssetTag,
                (AssetTag.tag_id == Tag.id) & AssetTag.deleted_at.is_(None),
            )
            .outerjoin(
                Asset,
                (Asset.id == AssetTag.asset_id)
                & (Asset.state == "active")
                & Asset.deleted_at.is_(None),
            )
            .group_by(Tag.id)
            .order_by(func.count(Asset.id).desc(), Tag.tag_text.asc())
        )
    ).all()
    return [
        {**tag.to_dict(), "usage_count": count}
        for tag, count in rows
    ]


@router.post("/batch/markers/get")
async def batch_get_asset_markers(
    request: AssetIdsRequest, session: AsyncSession = Depends(get_db_session)
):
    result = {asset_id: [] for asset_id in request.asset_ids}
    if not request.asset_ids:
        return result
    rows = (
        await session.execute(
            select(AssetMarker, Marker)
            .join(Marker, Marker.id == AssetMarker.marker_id)
            .where(
                AssetMarker.asset_id.in_(request.asset_ids),
                AssetMarker.deleted_at.is_(None),
                AssetMarker.source != "suppressed",
            )
        )
    ).all()
    for association, marker in rows:
        result[association.asset_id].append(
            {**marker.to_dict(), "source": association.source}
        )
    return result


@router.post("/item/{asset_id}/markers/{marker_id}")
async def add_asset_marker(
    asset_id: int, marker_id: int, session: AsyncSession = Depends(get_db_session)
):
    asset = await _live_asset_or_404(session, asset_id)
    if await session.get(Marker, marker_id) is None:
        raise HTTPException(status_code=404, detail="Marker not found")
    await set_asset_marker(
        session, asset_id=asset_id, marker_id=marker_id, add=True
    )
    await session.commit()
    markers = await _asset_markers(session, asset_id)
    # Broadcast even for an idempotent add: it may have repaired stale
    # expiration left by an older build.
    await broadcast_asset_organization_updated(
        session, [asset_id], ws_manager, fields=("markers", "expires_at")
    )
    return {"status": "success", "markers": markers}


@router.delete("/item/{asset_id}/markers/{marker_id}")
async def remove_asset_marker(
    asset_id: int, marker_id: int, session: AsyncSession = Depends(get_db_session)
):
    await _live_asset_or_404(session, asset_id)
    changed = await set_asset_marker(
        session, asset_id=asset_id, marker_id=marker_id, add=False
    )
    if not changed:
        raise HTTPException(status_code=404, detail="Marker not found on Asset")
    await session.commit()
    markers = await _asset_markers(session, asset_id)
    await broadcast_asset_organization_updated(session, [asset_id], ws_manager)
    return {"status": "success", "markers": markers}


@router.post("/batch/markers")
async def bulk_asset_markers(
    request: AssetMarkerBatchRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if await session.get(Marker, request.marker_id) is None:
        raise HTTPException(status_code=404, detail="Marker not found")
    valid_ids = set(
        await session.scalars(
            select(Asset.id).where(
                Asset.id.in_(request.asset_ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    )
    changed = 0
    for asset_id in valid_ids:
        changed += int(
            await set_asset_marker(
                session,
                asset_id=asset_id,
                marker_id=request.marker_id,
                add=request.add,
            )
        )
    await session.commit()
    if changed or request.add:
        await broadcast_asset_organization_updated(
            session,
            valid_ids,
            ws_manager,
            fields=("markers", "expires_at") if request.add else ("markers",),
        )
    return {"status": "success", "changed": changed, "total": len(valid_ids)}


async def _find_or_create_tag(session: AsyncSession, text: str) -> Tag | None:
    normalized = text.strip().lower()
    if not normalized:
        return None
    tag = await session.scalar(select(Tag).where(Tag.tag_text == normalized))
    if tag is None:
        tag = Tag(tag_text=normalized)
        session.add(tag)
        await session.flush()
    return tag


@router.post("/item/{asset_id}/tags")
async def add_asset_tags(
    asset_id: int,
    request: AssetTagsRequest,
    session: AsyncSession = Depends(get_db_session),
):
    asset = await _live_asset_or_404(session, asset_id)
    added = []
    requested_add = False
    for text in request.tags:
        tag = await _find_or_create_tag(session, text)
        if tag is not None:
            requested_add = True
            if await set_asset_tag(
                session, asset_id=asset_id, tag_id=tag.id, add=True
            ):
                added.append(tag.tag_text)
    await session.commit()
    if requested_add:
        await broadcast_asset_organization_updated(
            session, [asset_id], ws_manager, fields=("tags", "expires_at")
        )
    return {"status": "success", "added": added}


@router.delete("/item/{asset_id}/tags/{tag_id}")
async def remove_asset_tag(
    asset_id: int, tag_id: int, session: AsyncSession = Depends(get_db_session)
):
    await _live_asset_or_404(session, asset_id)
    if not await set_asset_tag(session, asset_id=asset_id, tag_id=tag_id, add=False):
        raise HTTPException(status_code=404, detail="Tag not found on Asset")
    await session.commit()
    await broadcast_asset_organization_updated(
        session, [asset_id], ws_manager, fields=("tags",)
    )
    return {"status": "success"}


@router.post("/batch/tags")
async def bulk_asset_tags(
    request: AssetTagBatchRequest,
    session: AsyncSession = Depends(get_db_session),
):
    valid_ids = list(
        await session.scalars(
            select(Asset.id).where(
                Asset.id.in_(request.asset_ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    )
    tags = [await _find_or_create_tag(session, text) for text in request.tag_texts]
    requested_add = any(tag is not None for tag in tags)
    added = removed = 0
    for asset_id in valid_ids:
        for tag in tags:
            if tag is not None:
                added += int(
                    await set_asset_tag(
                        session, asset_id=asset_id, tag_id=tag.id, add=True
                    )
                )
        for tag_id in request.remove_tag_ids:
            removed += int(
                await set_asset_tag(
                    session, asset_id=asset_id, tag_id=tag_id, add=False
                )
            )
    await session.commit()
    if added or removed or requested_add:
        await broadcast_asset_organization_updated(
            session,
            valid_ids,
            ws_manager,
            fields=("tags", "expires_at") if requested_add else ("tags",),
        )
    return {"status": "success", "added": added, "removed": removed}


@router.post("/batch/projects/{project_id}")
async def add_assets_to_project(
    project_id: int,
    request: AssetIdsRequest,
    session: AsyncSession = Depends(get_db_session),
):
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Project not found")
    valid_ids = list(
        await session.scalars(
            select(Asset.id).where(
                Asset.id.in_(request.asset_ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    )
    for asset_id in valid_ids:
        await attach_asset_to_project(session, project_id, asset_id)
    await session.commit()
    if valid_ids:
        from asset_association_service import broadcast_assets_retained

        await broadcast_assets_retained(session, valid_ids, ws_manager)
    return {"status": "success", "added": len(valid_ids)}


@router.post("/batch/trash")
async def trash_assets(
    request: AssetIdsRequest, session: AsyncSession = Depends(get_db_session)
):
    changed = []
    for asset_id in request.asset_ids:
        try:
            await trash_asset(session, asset_id=asset_id)
            changed.append(asset_id)
        except AssetServiceError:
            continue
    await session.commit()
    if changed:
        await ws_manager.broadcast("assets_trashed", {"asset_ids": changed})
    return {"status": "success", "asset_ids": changed}


@router.post("/batch/restore")
async def restore_assets(
    request: AssetIdsRequest, session: AsyncSession = Depends(get_db_session)
):
    changed = []
    for asset_id in request.asset_ids:
        try:
            await restore_asset(session, asset_id=asset_id)
            changed.append(asset_id)
        except AssetServiceError:
            continue
    await session.commit()
    if changed:
        await ws_manager.broadcast("assets_restored", {"asset_ids": changed})
    return {"status": "success", "asset_ids": changed}


@router.post("/batch/deletion-manifest")
async def get_asset_batch_deletion_manifest(
    request: AssetIdsRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Return editor-project cleanup keys for one delete selection."""
    asset_ids = list(dict.fromkeys(request.asset_ids))
    rows = (
        await session.execute(
            select(AssetRevision.asset_id, AssetRevision.primary_media_id)
            .join(Asset, Asset.id == AssetRevision.asset_id)
            .where(
                AssetRevision.asset_id.in_(asset_ids),
                Asset.state.in_(("trashed", "deleting")),
            )
            .order_by(AssetRevision.asset_id, AssetRevision.id)
        )
    ).all()
    grouped: dict[int, list[int]] = defaultdict(list)
    for asset_id, media_id in rows:
        grouped[asset_id].append(media_id)
    return {
        "items": [
            {"asset_id": asset_id, "media_ids": grouped.get(asset_id, [])}
            for asset_id in asset_ids
        ]
    }


@router.post("/batch/permanent", status_code=202)
async def permanently_delete_assets(
    request: AssetIdsRequest, session: AsyncSession = Depends(get_db_session)
):
    """Permanently delete selected Asset roots through the global queue."""
    from delete_operations import (
        broadcast_asset_delete_queue_enqueued,
        enqueue_asset_delete_operations,
        ensure_delete_worker_started,
    )

    asset_ids = list(dict.fromkeys(request.asset_ids))
    assets = {
        asset.id: asset
        for asset in await session.scalars(
            select(Asset).where(Asset.id.in_(asset_ids))
        )
    }
    invalid_ids = [
        asset_id
        for asset_id in asset_ids
        if asset_id not in assets
        or assets[asset_id].state not in {"trashed", "deleting"}
    ]
    if invalid_ids:
        raise HTTPException(
            status_code=400,
            detail="All assets must be in Trash before permanent deletion",
        )

    profile_id = get_current_profile()
    revisions = list(await session.scalars(
        select(AssetRevision).where(AssetRevision.asset_id.in_(asset_ids))
    ))
    all_media_ids = [revision.primary_media_id for revision in revisions]
    queued = await enqueue_asset_delete_operations(
        session,
        profile_id=profile_id,
        asset_ids=asset_ids,
    )
    await broadcast_asset_delete_queue_enqueued(session, queued)
    if queued:
        await ensure_delete_worker_started()
    return {
        "status": "accepted",
        "accepted": len(asset_ids),
        "total": len(asset_ids),
        "asset_ids": asset_ids,
        "operation": queued[-1].to_dict() if queued else None,
        "retained_media_ids": [],
        "media_ids": all_media_ids,
    }


@router.delete("", status_code=202)
async def empty_asset_trash(session: AsyncSession = Depends(get_db_session)):
    from delete_operations import (
        broadcast_asset_delete_queue_enqueued,
        enqueue_asset_delete_operations,
        ensure_delete_worker_started,
    )

    asset_ids = list(
        await session.scalars(
            select(Asset.id).where(
                Asset.state == "trashed", Asset.deleted_at.is_not(None)
            )
        )
    )
    revisions = list(
        await session.scalars(
            select(AssetRevision).where(AssetRevision.asset_id.in_(asset_ids))
        )
    ) if asset_ids else []
    revision_media_ids = [revision.primary_media_id for revision in revisions]
    profile_id = get_current_profile()
    queued = await enqueue_asset_delete_operations(
        session,
        profile_id=profile_id,
        asset_ids=asset_ids,
    )
    await broadcast_asset_delete_queue_enqueued(session, queued)
    if queued:
        await ensure_delete_worker_started()
    return {
        "status": "accepted" if queued else "completed",
        "identity_status": "pending" if queued else "completed",
        "cleanup_status": "pending" if queued else "completed",
        "privacy_status": "pending" if queued else "completed",
        "retained_media_ids": [],
        "media_ids": revision_media_ids,
        "accepted": len(asset_ids),
        "operation": queued[-1].to_dict() if queued else None,
    }


@router.delete("/item/{asset_id}/projects/{project_id}")
async def remove_asset_from_project(
    asset_id: int,
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    await _live_asset_or_404(session, asset_id)
    removed = await detach_asset_from_project(session, project_id, asset_id)
    await session.commit()
    if not removed:
        raise HTTPException(status_code=404, detail="Asset not in project")
    return {"status": "success"}


@router.get("/item/{asset_id}/projects")
async def get_asset_projects(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    await _live_asset_or_404(session, asset_id)
    projects = list(
        await session.scalars(
            select(Project)
            .join(ProjectAsset, ProjectAsset.project_id == Project.id)
            .where(
                ProjectAsset.asset_id == asset_id,
                ProjectAsset.deleted_at.is_(None),
                Project.deleted_at.is_(None),
            )
            .order_by(Project.name.asc())
        )
    )
    return [{"id": project.id, "name": project.name} for project in projects]


@router.delete("/item/{asset_id}/expiration")
async def clear_asset_expiration(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    asset = await _live_asset_or_404(session, asset_id)
    from asset_association_service import clear_asset_expiration as clear_deadline

    await clear_deadline(session, asset.id)
    await session.commit()
    revision = await session.get(AssetRevision, asset.current_revision_id)
    if revision is not None:
        await ws_manager.broadcast(
            "auto_delete_removed", {"media_id": revision.primary_media_id}
        )
    await ws_manager.broadcast(
        "assets_updated", {"asset_ids": [asset_id], "fields": ["expires_at"]}
    )
    return {"status": "success"}


@router.get("/item/{asset_id}/boards")
async def get_asset_boards(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    await _live_asset_or_404(session, asset_id)
    boards = list(
        await session.scalars(
            select(Board)
            .join(
                BoardSection,
                (BoardSection.board_id == Board.id)
                & BoardSection.deleted_at.is_(None),
            )
            .join(
                BoardAssetItem,
                (BoardAssetItem.board_section_id == BoardSection.id)
                & BoardAssetItem.deleted_at.is_(None),
            )
            .where(
                BoardAssetItem.asset_id == asset_id,
                Board.deleted_at.is_(None),
            )
            .order_by(Board.name.asc())
            .distinct()
        )
    )
    return [board.to_dict() for board in boards]


@router.get("/item/{asset_id}/containers")
async def get_asset_containers(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """List current containers that link to this Asset (multiple membership)."""
    await _live_asset_or_404(session, asset_id)
    rows = (
        await session.execute(
            select(Asset, AssetRevision, MediaItem, ContainerMember)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .join(
                ContainerMember,
                ContainerMember.container_revision_id == AssetRevision.id,
            )
            .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
            .where(
                ContainerMember.linked_asset_id == asset_id,
                ContainerMember.deleted_at.is_(None),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
            .order_by(Asset.updated_at.desc(), ContainerMember.member_order)
        )
    ).all()
    return [
        {
            "asset_id": container.id,
            "media_id": media.id,
            "asset_type": container.asset_type,
            "title": container.title or media.to_dict().get("title"),
            "member_order": member.member_order,
            "row_index": member.row_index,
            "column_index": member.column_index,
        }
        for container, _revision, media, member in rows
    ]


@router.post("/item/{asset_id}/container-members/promote")
async def promote_container_members(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    from container_service import save_container_members_as_assets

    try:
        promoted_ids = await save_container_members_as_assets(
            session, asset_id=asset_id
        )
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await ws_manager.broadcast(
        "assets_created",
        {"asset_ids": promoted_ids, "source_container_asset_id": asset_id},
    )
    return {"asset_ids": promoted_ids, "count": len(promoted_ids)}


@router.get("/item/{asset_id}/container-members/summary")
async def container_member_summary(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    from container_service import get_container_member_summary

    try:
        return await get_container_member_summary(session, asset_id=asset_id)
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/item/{asset_id}/explode")
async def explode_container_asset(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    from container_service import explode_container, get_container_member_summary

    try:
        summary = await get_container_member_summary(session, asset_id=asset_id)
        promoted_ids = await explode_container(session, asset_id=asset_id)
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await ws_manager.broadcast("asset_trashed", {"asset_id": asset_id})
    if promoted_ids:
        await ws_manager.broadcast(
            "assets_created",
            {"asset_ids": promoted_ids, "source_container_asset_id": asset_id},
        )
    return {
        "asset_id": asset_id,
        "asset_ids": promoted_ids,
        "count": len(promoted_ids),
        "created_count": summary["to_create"],
        "reused_count": summary["linked"] + summary["already_saved"],
        "moved_to_trash": True,
    }


@router.get("/contextual-media")
async def list_contextual_media(
    q: str | None = Query(None, min_length=1, max_length=300),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_db_session),
):
    """Discover retained non-Asset Media, grouped by its retaining content.

    A query matches both literal metadata and CLIP visual similarity. Working
    results therefore remain findable without becoming top-level Assets.
    """
    query = (
        select(MediaOwner, MediaItem)
            .join(MediaItem, MediaItem.id == MediaOwner.media_id)
            .outerjoin(
                AssetRevision,
                (AssetRevision.primary_media_id == MediaItem.id)
                & AssetRevision.deleted_at.is_(None),
            )
            .where(
                MediaOwner.deleted_at.is_(None),
                MediaOwner.root_kind.not_in(("asset_revision", "asset_snapshot", "container_revision")),
                MediaItem.deleted_at.is_(None),
                AssetRevision.id.is_(None),
            )
        .order_by(MediaOwner.root_kind, MediaOwner.root_id, MediaOwner.id)
    )
    rows = (await session.execute(query)).all()

    # Deleted chats are restorable and retain their Media, but they are no
    # longer live search surfaces.
    chat_root_ids = {
        int(owner.root_id)
        for owner, _media in rows
        if owner.root_kind == "chat" and owner.root_id.isdigit()
    }
    deleted_chat_ids = (
        set(
            await session.scalars(
                select(Chat.id).where(
                    Chat.id.in_(chat_root_ids), Chat.deleted_at.is_not(None)
                )
            )
        )
        if chat_root_ids
        else set()
    )
    rows = [
        (owner, media)
        for owner, media in rows
        if owner.root_kind != "chat"
        or not owner.root_id.isdigit()
        or int(owner.root_id) not in deleted_chat_ids
    ]

    scores: dict[int, float] = {}
    if q:
        search_text = q.strip()
        pattern = f"%{search_text}%"
        candidate_media = {media.id: media for _owner, media in rows}
        literal_ids = (
            set(
                await session.scalars(
                    select(MediaItem.id).where(
                        MediaItem.id.in_(candidate_media),
                        or_(
                            MediaItem.original_filename.ilike(pattern),
                            MediaItem.extracted_prompt.ilike(pattern),
                            MediaItem.vlm_caption.ilike(pattern),
                            MediaItem.keywords.ilike(pattern),
                            MediaItem.id.in_(
                                select(MediaKeyword.media_id)
                                .join(Keyword, Keyword.id == MediaKeyword.keyword_id)
                                .where(Keyword.keyword_text.ilike(pattern))
                            ),
                        ),
                    )
                )
            )
            if candidate_media
            else set()
        )

        visual_ids: set[int] = set()
        try:
            from clip_service import CLIP_EMBEDDING_DIM, get_clip_service
            from config import get_settings
            from utils.similarity import compute_relevance_cutoff

            clip = get_clip_service()
            query_embedding = clip.encode_text(search_text)
            for media in candidate_media.values():
                embedding = media.get_embedding()
                if embedding is None or embedding.shape[0] != CLIP_EMBEDDING_DIM:
                    continue
                scores[media.id] = float(
                    clip.compute_similarity(query_embedding, embedding)
                )
            cutoff = compute_relevance_cutoff(
                list(scores.values()),
                absolute_floor=get_settings().clip_text_similarity_threshold,
            )
            visual_ids = {
                media_id for media_id, score in scores.items() if score >= cutoff
            }
        except Exception as exc:
            # Literal search remains useful when the local visual-search model
            # is unavailable or not configured.
            log.warning("Contextual visual search unavailable: %s", exc)

        matching_ids = literal_ids | visual_ids
        rows = [row for row in rows if row[1].id in matching_ids]
        rows.sort(
            key=lambda row: (
                row[1].id not in literal_ids,
                -scores.get(row[1].id, -1.0),
                row[0].id,
            )
        )

    rows = rows[:limit]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for owner, media in rows:
        item = media.to_dict()
        if media.id in scores:
            item["similarity_score"] = scores[media.id]
        grouped[(owner.root_kind, owner.root_id)].append(item)
    return {
        "groups": [
            {"root_kind": kind, "root_id": root_id, "items": items}
            for (kind, root_id), items in grouped.items()
        ],
        "count": len(rows),
    }


@router.post("/contextual-media/{media_id}/promote")
async def promote_contextual_media(
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Explicitly save a contextual/intermediate Media result as an Asset."""
    try:
        asset = await create_asset_from_media(
            session,
            media_id=media_id,
            origin_type="contextual_promotion",
            origin_id=str(media_id),
        )
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    item = await get_asset_browser_item(asset.id, session=session)
    await ws_manager.broadcast("asset_created", {"asset": item})
    return {"asset": item}


@router.get("/trash-deletion-manifest")
async def get_asset_trash_deletion_manifest(
    session: AsyncSession = Depends(get_db_session),
):
    rows = (
        await session.execute(
            select(AssetRevision.asset_id, AssetRevision.primary_media_id)
            .join(Asset, Asset.id == AssetRevision.asset_id)
            .where(Asset.state == "trashed", Asset.deleted_at.is_not(None))
            .order_by(AssetRevision.asset_id, AssetRevision.id)
        )
    ).all()
    grouped: dict[int, list[int]] = defaultdict(list)
    for asset_id, media_id in rows:
        grouped[asset_id].append(media_id)
    return {
        "items": [
            {"asset_id": asset_id, "media_ids": media_ids}
            for asset_id, media_ids in grouped.items()
        ]
    }


@router.get("/item/{asset_id}/browser")
async def get_asset_browser_item(
    asset_id: int,
    include_trashed: bool = False,
    session: AsyncSession = Depends(get_db_session),
):
    row = (
        await session.execute(
            select(Asset, AssetRevision, MediaItem)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
            .where(
                Asset.id == asset_id,
                AssetRevision.deleted_at.is_(None),
                MediaItem.deleted_at.is_(None),
                *([] if include_trashed else [Asset.state == "active", Asset.deleted_at.is_(None)]),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return (await _browser_projections(session, [row]))[0]


@router.get("/{asset_id}")
async def get_asset(asset_id: int, session: AsyncSession = Depends(get_db_session)):
    row = (
        await session.execute(
            select(Asset, AssetRevision, MediaItem)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
            .where(Asset.id == asset_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _projection(*row)


def _revision_entry(revision: AssetRevision, media: MediaItem) -> dict:
    """Flattened revision + primary-media projection used by revision pickers."""
    return {
        "id": revision.id,
        "revision_number": revision.revision_number,
        "parent_revision_id": revision.parent_revision_id,
        "note": revision.note,
        "created_at": revision.created_at.isoformat(),
        "media_id": media.id,
        "media_hash": media.file_hash,
        "file_format": media.file_format,
        "width": media.width,
        "height": media.height,
    }


@router.get("/{asset_id}/revisions")
async def list_asset_revisions(
    asset_id: int, session: AsyncSession = Depends(get_db_session)
):
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    rows = (
        await session.execute(
            select(AssetRevision, MediaItem)
            .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
            .where(AssetRevision.asset_id == asset_id, AssetRevision.deleted_at.is_(None))
            .order_by(AssetRevision.revision_number.desc())
        )
    ).all()
    return {
        # Legacy shape (descending, nested media) — kept for existing consumers
        # (ImageEditorView, SlideshowInfoPanel version pickers).
        "current_revision_id": asset.current_revision_id,
        "items": [
            {**revision.to_dict(), "media": media.to_dict()}
            for revision, media in rows
        ],
        # Artifact-revisions shape: ascending, flattened.
        "asset": {
            "id": asset.id,
            "title": asset.title,
            "current_revision_id": asset.current_revision_id,
        },
        "revisions": [
            _revision_entry(revision, media)
            for revision, media in sorted(rows, key=lambda pair: pair[0].revision_number)
        ],
    }


@router.post("/{asset_id}/revisions/{revision_id}/restore")
async def restore_asset_revision_route(
    asset_id: int,
    revision_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        revision = await restore_revision_as_latest(
            session,
            asset_id=asset_id,
            revision_id=revision_id,
        )
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    item = await get_asset_browser_item(asset_id, session=session)
    await ws_manager.broadcast(
        "asset_current_revision_changed",
        {"asset_id": asset_id, "revision_id": revision.id, "asset": item},
    )
    restored_media = await session.get(MediaItem, revision.primary_media_id)
    revision_payload = revision.to_dict()
    if restored_media is not None:
        revision_payload.update(_revision_entry(revision, restored_media))
    return {"revision": revision_payload, "asset": item}


@router.get("/{asset_id}/deletion-preview")
async def get_asset_deletion_preview(
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    from asset_deletion_service import preview_asset_deletion

    try:
        preview = await preview_asset_deletion(session, asset_id=asset_id)
    except AssetServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "revision_count": preview.revision_count,
        "candidate_media_ids": preview.candidate_media_ids,
        "collectible_media_ids": preview.collectible_media_ids,
        "retained_media_ids": preview.retained_media_ids,
        "retained_by_kind": preview.retained_by_kind,
        "source_file_count": preview.source_file_count,
    }


@router.delete("/{asset_id}")
async def delete_asset(asset_id: int, session: AsyncSession = Depends(get_db_session)):
    try:
        asset = await trash_asset(session, asset_id=asset_id)
    except AssetServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await ws_manager.broadcast("asset_deleted", {"asset_id": asset_id})
    return {"asset": asset.to_dict()}


@router.post("/{asset_id}/restore")
async def restore_asset_route(
    asset_id: int, session: AsyncSession = Depends(get_db_session)
):
    try:
        asset = await restore_asset(session, asset_id=asset_id)
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    # Carry asset_id at top level: lifecycle listeners key on asset_id/asset_ids
    # (useMediaState.updateAssetLifecycle) and never unwrap the full dict.
    await ws_manager.broadcast(
        "asset_restored", {"asset_id": asset.id, "asset": asset.to_dict()}
    )
    return {"asset": asset.to_dict()}


@router.delete("/{asset_id}/permanent", status_code=202)
async def permanently_delete_asset_route(
    asset_id: int, session: AsyncSession = Depends(get_db_session)
):
    from delete_operations import (
        broadcast_asset_delete_queue_enqueued,
        enqueue_asset_delete_operations,
        ensure_delete_worker_started,
    )
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.state not in {"trashed", "deleting"}:
        raise HTTPException(
            status_code=400,
            detail="Asset must be in Trash before permanent deletion",
        )
    revision_media_ids = list(
        await session.scalars(
            select(AssetRevision.primary_media_id).where(
                AssetRevision.asset_id == asset_id
            )
        )
    )
    queued = await enqueue_asset_delete_operations(
        session,
        profile_id=get_current_profile(),
        asset_ids=[asset_id],
    )
    await broadcast_asset_delete_queue_enqueued(session, queued)
    operation = queued[0]
    if queued:
        await ensure_delete_worker_started()
    return {
        "status": "accepted",
        "identity_status": "pending",
        "cleanup_status": "pending",
        "privacy_status": "pending",
        "retained_media_ids": [],
        "media_ids": revision_media_ids,
        "operation": operation.to_dict(),
    }

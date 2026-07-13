"""Asset-first identity and contextual-Media APIs used during cutover."""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from asset_service import AssetServiceError, restore_asset, trash_asset
from asset_association_service import (
    attach_asset_to_project,
    detach_asset_from_project,
    set_asset_marker,
    set_asset_tag,
)
from core.profile_context import get_current_profile
from database import (
    Asset,
    AssetMarker,
    AssetRevision,
    AssetTag,
    Marker,
    MediaItem,
    MediaOwner,
    StorageObject,
    Tag,
    Project,
)
from core.dependencies import get_db_session
from utils.query_builder import build_filtered_query
from utils.websocket import ws_manager


router = APIRouter(prefix="/api/assets", tags=["assets"])


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
    if asset_ids:
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
                "asset_state": asset.state,
                "asset_title": asset.title,
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
    return (
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
        min_mp=filters.get("min_mp"),
        max_mp=filters.get("max_mp"),
        include_superseded=True,
        exclude_expired=filters.get("state", "active") == "active",
        asset_id_column=Asset.id,
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
    min_mp: float | None = None,
    max_mp: float | None = None,
    sort_by: str = Query(
        "created_desc",
        pattern="^(created_desc|created_asc|indexed_desc|indexed_asc|random|similarity)$",
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
    is_generated: bool | None = None,
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
    sort_by: str = Query("created_desc"),
    session: AsyncSession = Depends(get_db_session),
):
    """Ordered Asset IDs for select-all; deliberately never returns Media IDs."""
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
    else:
        query = query.order_by(MediaItem.created_date.desc().nulls_last(), Asset.id.desc())
    return {"ids": list(await session.scalars(query))}


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
    await _live_asset_or_404(session, asset_id)
    if await session.get(Marker, marker_id) is None:
        raise HTTPException(status_code=404, detail="Marker not found")
    changed = await set_asset_marker(
        session, asset_id=asset_id, marker_id=marker_id, add=True
    )
    await session.commit()
    markers = await _asset_markers(session, asset_id)
    if changed:
        await ws_manager.broadcast(
            "asset_updated", {"asset_id": asset_id, "fields": ["markers"]}
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
    await ws_manager.broadcast(
        "asset_updated", {"asset_id": asset_id, "fields": ["markers"]}
    )
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
    if changed:
        await ws_manager.broadcast(
            "assets_updated",
            {"asset_ids": sorted(valid_ids), "fields": ["markers"]},
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
    await _live_asset_or_404(session, asset_id)
    added = []
    for text in request.tags:
        tag = await _find_or_create_tag(session, text)
        if tag is not None and await set_asset_tag(
            session, asset_id=asset_id, tag_id=tag.id, add=True
        ):
            added.append(tag.tag_text)
    await session.commit()
    if added:
        await ws_manager.broadcast(
            "asset_updated", {"asset_id": asset_id, "fields": ["tags"]}
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
    await ws_manager.broadcast(
        "asset_updated", {"asset_id": asset_id, "fields": ["tags"]}
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
    if added or removed:
        await ws_manager.broadcast(
            "assets_updated", {"asset_ids": valid_ids, "fields": ["tags"]}
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


@router.get("/contextual-media")
async def list_contextual_media(
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_db_session),
):
    """Forensic discovery for retained non-Asset Media, grouped by root."""
    rows = (
        await session.execute(
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
            .limit(limit)
        )
    ).all()
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for owner, media in rows:
        grouped[(owner.root_kind, owner.root_id)].append(media.to_dict())
    return {
        "groups": [
            {"root_kind": kind, "root_id": root_id, "items": items}
            for (kind, root_id), items in grouped.items()
        ],
        "count": len(rows),
    }


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


@router.get("/{asset_id}/revisions")
async def list_asset_revisions(
    asset_id: int, session: AsyncSession = Depends(get_db_session)
):
    if await session.get(Asset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    revisions = list(
        await session.scalars(
            select(AssetRevision)
            .where(AssetRevision.asset_id == asset_id, AssetRevision.deleted_at.is_(None))
            .order_by(AssetRevision.revision_number.desc())
        )
    )
    return {"items": [revision.to_dict() for revision in revisions]}


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
    await ws_manager.broadcast("asset_restored", {"asset": asset.to_dict()})
    return {"asset": asset.to_dict()}


@router.delete("/{asset_id}/permanent", status_code=202)
async def permanently_delete_asset_route(
    asset_id: int, session: AsyncSession = Depends(get_db_session)
):
    from asset_deletion_service import permanently_delete_asset
    from delete_operations import ensure_delete_worker_started
    try:
        operation = await permanently_delete_asset(
            session,
            asset_id=asset_id,
            profile_id=get_current_profile(),
        )
    except AssetServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if operation is not None:
        await ensure_delete_worker_started()
    await ws_manager.broadcast("asset_permanently_deleted", {"asset_id": asset_id})
    return {
        "status": "accepted" if operation is not None else "completed",
        "operation": operation.to_dict() if operation is not None else None,
    }

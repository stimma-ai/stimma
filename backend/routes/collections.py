"""Collection management routes."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from collection_service import collection_summaries_query, serialize_collection
from core.dependencies import get_db_session
from core.logging import get_logger
from database import (
    Asset,
    AssetRevision,
    Collection,
    CollectionAssetItem,
    CollectionItem,
    CollectionSection,
    MediaItem,
)
from models.api_models import (
    CollectionAddItemsRequest,
    CollectionBulkMoveRequest,
    CollectionBulkRemoveRequest,
    CollectionCreateRequest,
    CollectionMoveItemRequest,
    CollectionResponse,
    CollectionSectionCreateRequest,
    CollectionSectionReorderRequest,
    CollectionSectionResponse,
    CollectionSectionUpdateRequest,
    CollectionSummaryResponse,
    CollectionUpdateRequest,
)
from project_service import (
    PROJECT_NONE,
    broadcast_project_assets_changed_for_assets,
    get_project_or_404,
    parse_project_filter,
)
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/collections", tags=["collections"])
log = get_logger(__name__)


def _track_collection_event(event: str, collection_id: int, extra: dict | None = None) -> None:
    """Emit a collection event carrying collectionHash (install-salted; never ids/names)."""
    try:
        from object_hash import salted_hash
        from telemetry import get_telemetry_client
        props = {"collectionHash": salted_hash(f"collection:{collection_id}")}
        if extra:
            props.update(extra)
        get_telemetry_client().track(event, props, category="organize")
    except Exception:  # noqa: BLE001 — telemetry never affects the app
        pass


async def _get_collection_or_404(collection_id: int, session: AsyncSession) -> Collection:
    result = await session.execute(
        select(Collection).where(Collection.id == collection_id, Collection.deleted_at.is_(None))
    )
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


async def _get_section_or_404(section_id: int, session: AsyncSession) -> CollectionSection:
    result = await session.execute(
        select(CollectionSection).where(CollectionSection.id == section_id, CollectionSection.deleted_at.is_(None))
    )
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Collection section not found")
    return section


async def _ensure_default_section(collection_id: int, session: AsyncSession) -> CollectionSection:
    result = await session.execute(
        select(CollectionSection)
        .where(
            CollectionSection.collection_id == collection_id,
            CollectionSection.is_default.is_(True),
            CollectionSection.deleted_at.is_(None),
        )
        .limit(1)
    )
    section = result.scalar_one_or_none()
    if section:
        return section

    max_order = await session.scalar(
        select(func.coalesce(func.max(CollectionSection.display_order), -1)).where(
            CollectionSection.collection_id == collection_id,
            CollectionSection.deleted_at.is_(None),
        )
    )
    section = CollectionSection(
        collection_id=collection_id,
        name=None,
        is_default=True,
        display_order=(max_order or -1) + 1,
    )
    session.add(section)
    await session.flush()
    return section


async def _compact_section_orders(collection_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(CollectionSection)
        .where(CollectionSection.collection_id == collection_id, CollectionSection.deleted_at.is_(None))
        .order_by(CollectionSection.display_order.asc(), CollectionSection.id.asc())
    )
    for index, section in enumerate(result.scalars().all()):
        section.display_order = index


async def _compact_asset_item_orders(section_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(CollectionAssetItem)
        .where(
            CollectionAssetItem.collection_section_id == section_id,
            CollectionAssetItem.deleted_at.is_(None),
        )
        .order_by(CollectionAssetItem.display_order.asc(), CollectionAssetItem.added_at.asc())
    )
    for index, item in enumerate(result.scalars().all()):
        item.display_order = index


async def _delete_section_if_empty(section: CollectionSection, session: AsyncSession) -> None:
    if section.is_default:
        return

    asset_item_count = await session.scalar(
        select(func.count()).select_from(CollectionAssetItem).where(
            CollectionAssetItem.collection_section_id == section.id,
            CollectionAssetItem.deleted_at.is_(None),
        )
    )
    if asset_item_count:
        return

    section.deleted_at = datetime.utcnow()
    section.updated_at = datetime.utcnow()
    await session.flush()
    await _compact_section_orders(section.collection_id, session)


async def _serialize_collection(collection: Collection, session: AsyncSession) -> CollectionResponse:
    return await serialize_collection(collection, session)


@router.get("", response_model=List[CollectionSummaryResponse])
async def get_collections(
    project_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    query = collection_summaries_query().order_by(Collection.updated_at.desc())
    # No project_id (back-compat) and project_id=none both mean unscoped collections.
    project_filter = parse_project_filter(project_id)
    if project_filter is None or project_filter == PROJECT_NONE:
        query = query.where(Collection.project_id.is_(None))
    else:
        query = query.where(Collection.project_id == project_filter)
    result = await session.execute(query)
    return [
        CollectionSummaryResponse(**collection.to_dict(), asset_count=asset_count)
        for collection, asset_count in result.all()
    ]


@router.post("", response_model=CollectionResponse)
async def create_collection(
    request: CollectionCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if request.project_id is not None:
        await get_project_or_404(session, request.project_id)
    collection = Collection(name=request.name or "", project_id=request.project_id)
    session.add(collection)
    await session.flush()
    await _ensure_default_section(collection.id, session)
    await session.commit()
    await session.refresh(collection)
    _created_extra: dict = {}
    if collection.project_id:
        from object_hash import salted_hash
        _created_extra["projectHash"] = salted_hash(f"project:{collection.project_id}")
    _track_collection_event("collection_created", collection.id, _created_extra)
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_created", {"collection": payload.model_dump()})
    return payload


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(collection_id: int, session: AsyncSession = Depends(get_db_session)):
    collection = await _get_collection_or_404(collection_id, session)
    await _ensure_default_section(collection.id, session)
    await session.commit()
    return await _serialize_collection(collection, session)


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: int,
    request: CollectionUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    collection = await _get_collection_or_404(collection_id, session)
    if request.name is not None:
        collection.name = request.name
    attached_asset_ids: list[int] = []
    if 'project_id' in request.model_fields_set and request.project_id != collection.project_id:
        if request.project_id is not None:
            await get_project_or_404(session, request.project_id)
        collection.project_id = request.project_id
        # A collection moving into a project brings its assets with it.
        attached_asset_ids = await _attach_assets_to_collection_project(
            session, collection, await _collection_asset_ids(session, collection.id)
        )
    collection.updated_at = datetime.utcnow()
    await session.commit()
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_updated", {"collection": payload.model_dump()})
    if attached_asset_ids:
        await broadcast_project_assets_changed_for_assets(
            session, collection.project_id, attached_asset_ids, action="added"
        )
    return payload


async def _collection_asset_ids(session: AsyncSession, collection_id: int) -> list[int]:
    rows = await session.scalars(
        select(CollectionAssetItem.asset_id)
        .join(CollectionSection, CollectionSection.id == CollectionAssetItem.collection_section_id)
        .where(
            CollectionSection.collection_id == collection_id,
            CollectionSection.deleted_at.is_(None),
            CollectionAssetItem.deleted_at.is_(None),
        )
        .order_by(CollectionSection.display_order, CollectionAssetItem.display_order)
    )
    return list(dict.fromkeys(rows))


async def _attach_assets_to_collection_project(
    session: AsyncSession, collection: Collection, asset_ids
) -> list[int]:
    """Attach live Assets to the collection's project; returns the ids attached."""
    if collection.project_id is None:
        return []
    ids = list(dict.fromkeys(asset_ids))
    if not ids:
        return []
    from asset_association_service import attach_asset_to_project

    live_ids = set(
        await session.scalars(
            select(Asset.id).where(
                Asset.id.in_(ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    )
    attached = []
    for asset_id in ids:
        if asset_id in live_ids:
            await attach_asset_to_project(session, collection.project_id, asset_id)
            attached.append(asset_id)
    return attached


@router.delete("/{collection_id}")
async def delete_collection(collection_id: int, session: AsyncSession = Depends(get_db_session)):
    collection = await _get_collection_or_404(collection_id, session)
    collection.deleted_at = datetime.utcnow()
    collection.updated_at = datetime.utcnow()
    await session.commit()
    await ws_manager.broadcast("collection_deleted", {"collection_id": collection_id})
    _track_collection_event("collection_deleted", collection_id)
    return {"status": "success", "message": "Collection deleted"}


@router.post("/{collection_id}/restore", response_model=CollectionResponse)
async def restore_collection(collection_id: int, session: AsyncSession = Depends(get_db_session)):
    """Clear the soft-delete tombstone — pairs with DELETE for undo."""
    result = await session.execute(select(Collection).where(Collection.id == collection_id))
    collection = result.scalar_one_or_none()
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    if collection.deleted_at is None:
        raise HTTPException(status_code=400, detail="Collection is not deleted")
    collection.deleted_at = None
    collection.updated_at = datetime.utcnow()
    await session.commit()
    await _ensure_default_section(collection.id, session)
    await session.commit()
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_restored", {"collection": payload.model_dump()})
    return payload


@router.post("/{collection_id}/sections", response_model=CollectionSectionResponse)
async def create_collection_section(
    collection_id: int,
    request: CollectionSectionCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    collection = await _get_collection_or_404(collection_id, session)
    max_order = await session.scalar(
        select(func.coalesce(func.max(CollectionSection.display_order), -1)).where(
            CollectionSection.collection_id == collection.id,
            CollectionSection.deleted_at.is_(None),
        )
    )
    section = CollectionSection(
        collection_id=collection.id,
        name=request.name,
        is_default=False,
        display_order=(max_order or -1) + 1,
    )
    session.add(section)
    collection.updated_at = datetime.utcnow()
    await session.commit()
    _track_collection_event("collection_section_added", collection_id)
    payload = CollectionSectionResponse(**section.to_dict(), items=[], item_count=0)
    await ws_manager.broadcast("collection_section_created", {"collection_id": collection_id, "section": payload.model_dump()})
    await ws_manager.broadcast("collection_updated", {"collection": (await _serialize_collection(collection, session)).model_dump()})
    return payload


@router.put("/sections/{section_id}", response_model=CollectionSectionResponse)
async def update_collection_section(
    section_id: int,
    request: CollectionSectionUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    section = await _get_section_or_404(section_id, session)
    if request.name is not None:
        section.name = request.name
        if section.is_default and (request.name or "").strip():
            section.is_default = False
    if request.is_collapsed is not None:
        section.is_collapsed = request.is_collapsed
    section.updated_at = datetime.utcnow()
    collection = await _get_collection_or_404(section.collection_id, session)
    collection.updated_at = datetime.utcnow()
    await session.commit()

    item_count = await session.scalar(
        select(func.count()).select_from(CollectionAssetItem).where(
            CollectionAssetItem.collection_section_id == section.id,
            CollectionAssetItem.deleted_at.is_(None),
        )
    )
    payload = CollectionSectionResponse(**section.to_dict(), items=[], item_count=item_count or 0)
    await ws_manager.broadcast("collection_section_updated", {"collection_id": collection.id, "section": payload.model_dump()})
    await ws_manager.broadcast("collection_updated", {"collection": (await _serialize_collection(collection, session)).model_dump()})
    return payload


@router.delete("/sections/{section_id}")
async def delete_collection_section(section_id: int, session: AsyncSession = Depends(get_db_session)):
    section = await _get_section_or_404(section_id, session)
    collection = await _get_collection_or_404(section.collection_id, session)
    was_default = section.is_default
    await session.execute(delete(CollectionItem).where(CollectionItem.collection_section_id == section.id))
    await session.execute(
        CollectionAssetItem.__table__.update()
        .where(
            CollectionAssetItem.collection_section_id == section.id,
            CollectionAssetItem.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.utcnow())
    )
    section.deleted_at = datetime.utcnow()
    section.updated_at = datetime.utcnow()
    section.is_default = False
    await session.flush()
    if was_default:
        # Promote the next remaining section (lowest display_order) to default so the
        # collection always has one. If none remain, _ensure_default_section will create one.
        result = await session.execute(
            select(CollectionSection)
            .where(CollectionSection.collection_id == collection.id, CollectionSection.deleted_at.is_(None))
            .order_by(CollectionSection.display_order.asc(), CollectionSection.id.asc())
            .limit(1)
        )
        promoted = result.scalar_one_or_none()
        if promoted is not None:
            promoted.is_default = True
        else:
            await _ensure_default_section(collection.id, session)
    await _compact_section_orders(collection.id, session)
    collection.updated_at = datetime.utcnow()
    await session.commit()
    _track_collection_event("collection_section_removed", collection.id)
    await ws_manager.broadcast("collection_section_deleted", {"collection_id": collection.id, "section_id": section_id})
    await ws_manager.broadcast("collection_updated", {"collection": (await _serialize_collection(collection, session)).model_dump()})
    return {"status": "success"}


@router.post("/{collection_id}/sections/reorder")
async def reorder_collection_sections(
    collection_id: int,
    request: CollectionSectionReorderRequest,
    session: AsyncSession = Depends(get_db_session),
):
    collection = await _get_collection_or_404(collection_id, session)
    result = await session.execute(
        select(CollectionSection).where(
            CollectionSection.collection_id == collection.id,
            CollectionSection.deleted_at.is_(None),
        )
    )
    sections_by_id = {section.id: section for section in result.scalars().all()}
    for index, section_id in enumerate(request.section_ids):
        section = sections_by_id.get(section_id)
        if section:
            section.display_order = index
    collection.updated_at = datetime.utcnow()
    await session.commit()
    _track_collection_event("collection_sections_reordered", collection.id)
    await ws_manager.broadcast("collection_updated", {"collection": (await _serialize_collection(collection, session)).model_dump()})
    return {"status": "success"}


@router.post("/{collection_id}/items")
async def add_collection_items(
    collection_id: int,
    request: CollectionAddItemsRequest,
    session: AsyncSession = Depends(get_db_session),
):
    collection = await _get_collection_or_404(collection_id, session)
    if request.section_id is not None:
        section = await _get_section_or_404(request.section_id, session)
        if section.collection_id != collection.id:
            raise HTTPException(status_code=400, detail="Section does not belong to collection")
    else:
        section = await _ensure_default_section(collection.id, session)

    max_asset_order = await session.scalar(
        select(func.coalesce(func.max(CollectionAssetItem.display_order), -1)).where(
            CollectionAssetItem.collection_section_id == section.id,
            CollectionAssetItem.deleted_at.is_(None),
        )
    )
    next_order = (max_asset_order or -1) + 1
    added = 0
    from asset_association_service import (
        asset_ids_for_media_ids,
        attach_asset_to_collection_section,
        mirror_media_associations_to_asset,
    )

    promoted = await asset_ids_for_media_ids(
        session,
        request.media_ids,
        promote=True,
        origin_type="collection_promotion",
    )
    for media_id, asset_id in promoted.items():
        await mirror_media_associations_to_asset(
            session, media_id=media_id, asset_id=asset_id
        )
    requested_asset_ids = list(dict.fromkeys([*request.asset_ids, *promoted.values()]))
    valid_asset_ids = set(
        await session.scalars(
            select(Asset.id).where(
                Asset.id.in_(requested_asset_ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    )
    for asset_id in requested_asset_ids:
        if asset_id not in valid_asset_ids:
            continue
        _, was_added = await attach_asset_to_collection_section(
            session,
            collection=collection,
            section_id=section.id,
            asset_id=asset_id,
            display_order=next_order,
        )
        if was_added:
            next_order += 1
            added += 1
    collection.updated_at = datetime.utcnow()
    await session.commit()
    if valid_asset_ids:
        from asset_association_service import broadcast_assets_retained

        await broadcast_assets_retained(session, valid_asset_ids, ws_manager)
        if collection.project_id is not None:
            await broadcast_project_assets_changed_for_assets(
                session,
                collection.project_id,
                [a for a in requested_asset_ids if a in valid_asset_ids],
                action="added",
            )
    if added > 0:
        _track_collection_event("collection_items_added", collection.id, {"count": added})
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_items_changed", {"collection_id": collection.id, "collection": payload.model_dump()})
    await ws_manager.broadcast("collection_updated", {"collection": payload.model_dump()})
    return {"status": "success", "added": added}


@router.delete("/sections/{section_id}/items/{media_id}")
async def remove_collection_item(
    section_id: int,
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    section = await _get_section_or_404(section_id, session)
    collection = await _get_collection_or_404(section.collection_id, session)
    from asset_association_service import asset_for_media

    asset = await asset_for_media(session, media_id)
    if asset is not None:
        row = await session.scalar(
            select(CollectionAssetItem).where(
                CollectionAssetItem.collection_section_id == section.id,
                CollectionAssetItem.asset_id == asset.id,
                CollectionAssetItem.deleted_at.is_(None),
            )
        )
        if row is not None:
            row.deleted_at = datetime.utcnow()
    # Remove any historical edge left by an interrupted migration.
    await session.execute(
        delete(CollectionItem).where(CollectionItem.collection_section_id == section.id, CollectionItem.media_id == media_id)
    )
    await _compact_asset_item_orders(section.id, session)
    await _delete_section_if_empty(section, session)
    collection.updated_at = datetime.utcnow()
    await session.commit()
    _track_collection_event("collection_items_removed", collection.id, {"count": 1})
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_items_changed", {"collection_id": collection.id, "collection": payload.model_dump()})
    await ws_manager.broadcast("collection_updated", {"collection": payload.model_dump()})
    return {"status": "success"}


@router.delete("/sections/{section_id}/asset-items/{asset_id}")
async def remove_collection_asset_item(
    section_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    section = await _get_section_or_404(section_id, session)
    collection = await _get_collection_or_404(section.collection_id, session)
    row = await session.scalar(
        select(CollectionAssetItem).where(
            CollectionAssetItem.collection_section_id == section.id,
            CollectionAssetItem.asset_id == asset_id,
            CollectionAssetItem.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Collection Asset not found")
    row.deleted_at = datetime.utcnow()
    await _compact_asset_item_orders(section.id, session)
    await _delete_section_if_empty(section, session)
    collection.updated_at = datetime.utcnow()
    await session.commit()
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast(
        "collection_items_changed", {"collection_id": collection.id, "collection": payload.model_dump()}
    )
    return {"status": "success"}


@router.post("/{collection_id}/items/move")
async def move_collection_item(
    collection_id: int,
    request: CollectionMoveItemRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if request.media_id is None:
        raise HTTPException(status_code=400, detail="media_id is required")
    from asset_association_service import asset_for_media, mirror_media_associations_to_asset

    asset = await asset_for_media(
        session,
        request.media_id,
        promote=True,
        origin_type="collection_promotion",
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Collection Asset not found")
    await mirror_media_associations_to_asset(
        session, media_id=request.media_id, asset_id=asset.id
    )
    return await move_collection_asset_item(
        collection_id,
        request.model_copy(update={"asset_id": asset.id}),
        session,
    )


@router.post("/{collection_id}/asset-items/move")
async def move_collection_asset_item(
    collection_id: int,
    request: CollectionMoveItemRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if request.asset_id is None:
        raise HTTPException(status_code=400, detail="asset_id is required")
    collection = await _get_collection_or_404(collection_id, session)
    source_section = await _get_section_or_404(request.from_section_id, session)
    target_section = await _get_section_or_404(request.to_section_id, session)
    if source_section.collection_id != collection.id or target_section.collection_id != collection.id:
        raise HTTPException(status_code=400, detail="Sections do not belong to collection")
    collection_item = await session.scalar(
        select(CollectionAssetItem).where(
            CollectionAssetItem.collection_section_id == source_section.id,
            CollectionAssetItem.asset_id == request.asset_id,
            CollectionAssetItem.deleted_at.is_(None),
        )
    )
    if collection_item is None:
        raise HTTPException(status_code=404, detail="Collection Asset not found")
    target_items = list(
        await session.scalars(
            select(CollectionAssetItem)
            .where(
                CollectionAssetItem.collection_section_id == target_section.id,
                CollectionAssetItem.deleted_at.is_(None),
            )
            .order_by(CollectionAssetItem.display_order, CollectionAssetItem.added_at)
        )
    )
    target_items = [item for item in target_items if item.asset_id != request.asset_id]
    if source_section.id != target_section.id:
        duplicate = await session.scalar(
            select(CollectionAssetItem).where(
                CollectionAssetItem.collection_section_id == target_section.id,
                CollectionAssetItem.asset_id == request.asset_id,
                CollectionAssetItem.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            collection_item.deleted_at = datetime.utcnow()
            moved_item = duplicate
        else:
            collection_item.collection_section_id = target_section.id
            moved_item = collection_item
        await _compact_asset_item_orders(source_section.id, session)
        await _delete_section_if_empty(source_section, session)
    else:
        moved_item = collection_item
    target_index = max(0, min(request.target_index, len(target_items)))
    target_items.insert(target_index, moved_item)
    for index, item in enumerate(target_items):
        item.display_order = index
    collection.updated_at = datetime.utcnow()
    await session.commit()
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast(
        "collection_items_changed", {"collection_id": collection.id, "collection": payload.model_dump()}
    )
    return {"status": "success"}


@router.post("/{collection_id}/items/bulk-remove")
async def bulk_remove_collection_items(
    collection_id: int,
    request: CollectionBulkRemoveRequest,
    session: AsyncSession = Depends(get_db_session),
):
    collection = await _get_collection_or_404(collection_id, session)
    from asset_association_service import asset_ids_for_media_ids

    mapped = await asset_ids_for_media_ids(session, request.media_ids)
    media_ids_set = set(request.media_ids)
    asset_ids_set = set(request.asset_ids) | set(mapped.values())

    sections_result = await session.execute(
        select(CollectionSection).where(
            CollectionSection.collection_id == collection.id,
            CollectionSection.deleted_at.is_(None),
        )
    )
    sections = sections_result.scalars().all()

    for section in sections:
        await session.execute(
            delete(CollectionItem).where(
                CollectionItem.collection_section_id == section.id,
                CollectionItem.media_id.in_(media_ids_set),
            )
        )
        if asset_ids_set:
            rows = list(
                await session.scalars(
                    select(CollectionAssetItem).where(
                        CollectionAssetItem.collection_section_id == section.id,
                        CollectionAssetItem.asset_id.in_(asset_ids_set),
                        CollectionAssetItem.deleted_at.is_(None),
                    )
                )
            )
            for row in rows:
                row.deleted_at = datetime.utcnow()
        await _compact_asset_item_orders(section.id, session)
        await _delete_section_if_empty(section, session)

    collection.updated_at = datetime.utcnow()
    await session.commit()
    _track_collection_event(
        "collection_items_removed", collection.id,
        {"count": len(asset_ids_set)},
    )
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_items_changed", {"collection_id": collection.id, "collection": payload.model_dump()})
    await ws_manager.broadcast("collection_updated", {"collection": payload.model_dump()})
    return {"status": "success"}


@router.post("/{collection_id}/items/bulk-move")
async def bulk_move_collection_items(
    collection_id: int,
    request: CollectionBulkMoveRequest,
    session: AsyncSession = Depends(get_db_session),
):
    collection = await _get_collection_or_404(collection_id, session)
    target_section = await _get_section_or_404(request.to_section_id, session)
    if target_section.collection_id != collection.id:
        raise HTTPException(status_code=400, detail="Section does not belong to collection")

    from asset_association_service import (
        asset_ids_for_media_ids,
        mirror_media_associations_to_asset,
    )

    mapped = await asset_ids_for_media_ids(
        session,
        request.media_ids,
        promote=True,
        origin_type="collection_promotion",
    )
    for media_id, asset_id in mapped.items():
        await mirror_media_associations_to_asset(
            session, media_id=media_id, asset_id=asset_id
        )
    media_ids_set = set(request.media_ids)
    asset_ids_set = set(request.asset_ids) | set(mapped.values())

    sections_result = await session.execute(
        select(CollectionSection).where(
            CollectionSection.collection_id == collection.id,
            CollectionSection.deleted_at.is_(None),
        )
    )
    sections = sections_result.scalars().all()

    for section in sections:
        if section.id == target_section.id:
            continue
        await session.execute(
            delete(CollectionItem).where(
                CollectionItem.collection_section_id == section.id,
                CollectionItem.media_id.in_(media_ids_set),
            )
        )
        if asset_ids_set:
            asset_rows = list(
                await session.scalars(
                    select(CollectionAssetItem).where(
                        CollectionAssetItem.collection_section_id == section.id,
                        CollectionAssetItem.asset_id.in_(asset_ids_set),
                        CollectionAssetItem.deleted_at.is_(None),
                    )
                )
            )
            for row in asset_rows:
                row.deleted_at = datetime.utcnow()
            await _compact_asset_item_orders(section.id, session)
        await _delete_section_if_empty(section, session)

    max_asset_order = await session.scalar(
        select(func.coalesce(func.max(CollectionAssetItem.display_order), -1)).where(
            CollectionAssetItem.collection_section_id == target_section.id,
            CollectionAssetItem.deleted_at.is_(None),
        )
    )
    next_asset_order = (max_asset_order or -1) + 1
    existing_asset_ids = set(
        await session.scalars(
            select(CollectionAssetItem.asset_id).where(
                CollectionAssetItem.collection_section_id == target_section.id,
                CollectionAssetItem.asset_id.in_(asset_ids_set),
                CollectionAssetItem.deleted_at.is_(None),
            )
        )
    )
    for asset_id in asset_ids_set:
        if asset_id in existing_asset_ids:
            continue
        session.add(
            CollectionAssetItem(
                collection_section_id=target_section.id,
                asset_id=asset_id,
                display_order=next_asset_order,
            )
        )
        next_asset_order += 1

    attached_asset_ids = await _attach_assets_to_collection_project(
        session, collection, asset_ids_set
    )
    collection.updated_at = datetime.utcnow()
    await session.commit()
    if attached_asset_ids:
        await broadcast_project_assets_changed_for_assets(
            session, collection.project_id, attached_asset_ids, action="added"
        )
    _track_collection_event(
        "collection_items_moved", collection.id,
        {"count": len(asset_ids_set)},
    )
    payload = await _serialize_collection(collection, session)
    await ws_manager.broadcast("collection_items_changed", {"collection_id": collection.id, "collection": payload.model_dump()})
    await ws_manager.broadcast("collection_updated", {"collection": payload.model_dump()})
    return {"status": "success"}

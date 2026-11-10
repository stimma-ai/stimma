"""Shared collection serialization helpers."""
from typing import Any, List

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    AssetRevision,
    Collection,
    CollectionAssetItem,
    CollectionSection,
    MediaItem,
)
from models.api_models import CollectionResponse, CollectionSectionResponse
from implicit_markers import implicit_markers_by_media


async def serialize_collection(collection: Collection, session: AsyncSession) -> CollectionResponse:
    """Serialize a collection with sections, items, and computed asset_count."""
    sections_result = await session.execute(
        select(CollectionSection)
        .where(CollectionSection.collection_id == collection.id, CollectionSection.deleted_at.is_(None))
        .order_by(CollectionSection.display_order.asc(), CollectionSection.id.asc())
    )
    sections = sections_result.scalars().all()
    payload_sections: List[CollectionSectionResponse] = []
    total_asset_count = 0

    for section in sections:
        asset_items_result = await session.execute(
            select(Asset, AssetRevision, MediaItem, CollectionAssetItem.display_order)
            .join(CollectionAssetItem, CollectionAssetItem.asset_id == Asset.id)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
            .where(
                CollectionAssetItem.collection_section_id == section.id,
                CollectionAssetItem.deleted_at.is_(None),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
                MediaItem.deleted_at.is_(None),
                or_(
                    MediaItem.file_unavailable.is_(False),
                    MediaItem.file_unavailable.is_(None),
                ),
            )
            .order_by(CollectionAssetItem.display_order.asc(), CollectionAssetItem.added_at.asc())
        )
        asset_rows = asset_items_result.all()
        implicit_markers = await implicit_markers_by_media(
            session, [media.id for _, _, media, _ in asset_rows]
        )
        projected_items = []
        for asset, revision, media, _ in asset_rows:
            item = media.to_dict()
            item.update({
                "id": asset.id,
                "asset_id": asset.id,
                "media_id": media.id,
                "revision_id": revision.id,
                "markers": implicit_markers[media.id],
            })
            projected_items.append(item)
        items = projected_items
        total_asset_count += len(items)
        payload_sections.append(
            CollectionSectionResponse(
                **section.to_dict(),
                items=items,
                item_count=len(items),
            )
        )

    return CollectionResponse(
        **collection.to_dict(),
        sections=payload_sections,
        asset_count=total_asset_count,
    )


def _live_media_condition():
    return and_(
        MediaItem.deleted_at.is_(None),
        or_(
            MediaItem.file_unavailable.is_(False),
            MediaItem.file_unavailable.is_(None),
        ),
    )


def collection_asset_count_column():
    """Live Assets on a collection, for ``collection_summaries_query``."""
    return func.count(func.distinct(MediaItem.id)).label("asset_count")


def collection_summaries_query():
    """``(Collection, asset_count)`` rows for live collections, grouped by collection.

    Counts each live Asset whose current revision has an available primary
    payload — the same Assets ``serialize_collection`` lists. Callers add the
    scope, order, and any limit.
    """
    return (
        select(Collection, collection_asset_count_column())
        .outerjoin(CollectionSection, and_(CollectionSection.collection_id == Collection.id, CollectionSection.deleted_at.is_(None)))
        .outerjoin(
            CollectionAssetItem,
            and_(
                CollectionAssetItem.collection_section_id == CollectionSection.id,
                CollectionAssetItem.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            Asset,
            and_(
                Asset.id == CollectionAssetItem.asset_id,
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            AssetRevision,
            AssetRevision.id == Asset.current_revision_id,
        )
        .outerjoin(
            MediaItem,
            and_(
                MediaItem.id == AssetRevision.primary_media_id,
                _live_media_condition(),
            ),
        )
        .where(Collection.deleted_at.is_(None))
        .group_by(Collection.id)
    )


async def collection_preview_items(
    session: AsyncSession, collection_id: int, limit: int
) -> list[dict[str, Any]]:
    """The first ``limit`` items of a collection in display order, compactly.

    Carries only what a cover filmstrip draws: Asset and payload identity,
    format, and dimensions. Ordered like ``serialize_collection`` flattens its
    sections, without loading the rest of the collection.
    """
    rows = await session.execute(
        select(
            Asset.id,
            AssetRevision.id,
            MediaItem.id,
            MediaItem.file_hash,
            MediaItem.file_format,
            MediaItem.width,
            MediaItem.height,
        )
        .join(CollectionAssetItem, CollectionAssetItem.asset_id == Asset.id)
        .join(CollectionSection, CollectionSection.id == CollectionAssetItem.collection_section_id)
        .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
        .where(
            CollectionSection.collection_id == collection_id,
            CollectionSection.deleted_at.is_(None),
            CollectionAssetItem.deleted_at.is_(None),
            Asset.state == "active",
            Asset.deleted_at.is_(None),
            _live_media_condition(),
        )
        .order_by(
            CollectionSection.display_order.asc(),
            CollectionSection.id.asc(),
            CollectionAssetItem.display_order.asc(),
            CollectionAssetItem.added_at.asc(),
        )
        .limit(limit)
    )
    return [
        {
            "id": asset_id,
            "asset_id": asset_id,
            "revision_id": revision_id,
            "media_id": media_id,
            "file_hash": file_hash,
            "file_format": file_format,
            "width": width,
            "height": height,
        }
        for asset_id, revision_id, media_id, file_hash, file_format, width, height in rows.all()
    ]

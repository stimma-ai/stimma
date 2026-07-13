"""Shared board serialization helpers."""
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import (
    Asset,
    AssetRevision,
    Board,
    BoardAssetItem,
    BoardItem,
    BoardSection,
    MediaItem,
    MediaMarker,
)
from models.api_models import BoardResponse, BoardSectionResponse


async def serialize_board(board: Board, session: AsyncSession) -> BoardResponse:
    """Serialize a board with sections, items, and computed asset_count."""
    sections_result = await session.execute(
        select(BoardSection)
        .where(BoardSection.board_id == board.id, BoardSection.deleted_at.is_(None))
        .order_by(BoardSection.display_order.asc(), BoardSection.id.asc())
    )
    sections = sections_result.scalars().all()
    payload_sections: List[BoardSectionResponse] = []
    total_asset_count = 0

    for section in sections:
        asset_items_result = await session.execute(
            select(Asset, AssetRevision, MediaItem, BoardAssetItem.display_order)
            .join(BoardAssetItem, BoardAssetItem.asset_id == Asset.id)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
            .where(
                BoardAssetItem.board_section_id == section.id,
                BoardAssetItem.deleted_at.is_(None),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
                MediaItem.deleted_at.is_(None),
            )
            .order_by(BoardAssetItem.display_order.asc(), BoardAssetItem.added_at.asc())
        )
        asset_rows = asset_items_result.all()
        projected_items = []
        projected_media_ids = set()
        for asset, revision, media, _ in asset_rows:
            item = media.to_dict()
            item.update({
                "id": asset.id,
                "asset_id": asset.id,
                "media_id": media.id,
                "revision_id": revision.id,
            })
            projected_items.append(item)
            projected_media_ids.add(media.id)

        # Compatibility fallback for boards not yet backfilled. Do not duplicate
        # a Media item that already has authoritative Asset membership.
        items_result = await session.execute(
            select(MediaItem, BoardItem.display_order)
            .join(BoardItem, BoardItem.media_id == MediaItem.id)
            .where(
                BoardItem.board_section_id == section.id,
                MediaItem.deleted_at.is_(None),
            )
            .options(
                selectinload(MediaItem.marker_associations).selectinload(MediaMarker.marker),
            )
            .order_by(BoardItem.display_order.asc(), BoardItem.added_at.asc())
        )
        media_items = [
            row[0] for row in items_result.all() if row[0].id not in projected_media_ids
        ]
        items = [*projected_items, *(item.to_dict() for item in media_items)]
        total_asset_count += len(items)
        payload_sections.append(
            BoardSectionResponse(
                **section.to_dict(),
                items=items,
                item_count=len(items),
            )
        )

    return BoardResponse(
        **board.to_dict(),
        sections=payload_sections,
        asset_count=total_asset_count,
    )

"""Shared board serialization helpers."""
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import Board, BoardItem, BoardSection, MediaItem, MediaMarker
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
        media_items = [row[0] for row in items_result.all()]
        total_asset_count += len(media_items)
        payload_sections.append(
            BoardSectionResponse(
                **section.to_dict(),
                items=[item.to_dict() for item in media_items],
                item_count=len(media_items),
            )
        )

    return BoardResponse(
        **board.to_dict(),
        sections=payload_sections,
        asset_count=total_asset_count,
    )

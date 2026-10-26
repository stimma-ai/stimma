"""Shared board serialization helpers."""
from typing import Any, List

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    AssetRevision,
    Board,
    BoardAssetItem,
    BoardSection,
    MediaItem,
)
from models.api_models import BoardResponse, BoardSectionResponse
from implicit_markers import implicit_markers_by_media


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
                or_(
                    MediaItem.file_unavailable.is_(False),
                    MediaItem.file_unavailable.is_(None),
                ),
            )
            .order_by(BoardAssetItem.display_order.asc(), BoardAssetItem.added_at.asc())
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


def _live_media_condition():
    return and_(
        MediaItem.deleted_at.is_(None),
        or_(
            MediaItem.file_unavailable.is_(False),
            MediaItem.file_unavailable.is_(None),
        ),
    )


def board_asset_count_column():
    """Live Assets on a board, for ``board_summaries_query``."""
    return func.count(func.distinct(MediaItem.id)).label("asset_count")


def board_summaries_query():
    """``(Board, asset_count)`` rows for live boards, grouped by board.

    Counts each live Asset whose current revision has an available primary
    payload — the same Assets ``serialize_board`` lists. Callers add the
    scope, order, and any limit.
    """
    return (
        select(Board, board_asset_count_column())
        .outerjoin(BoardSection, and_(BoardSection.board_id == Board.id, BoardSection.deleted_at.is_(None)))
        .outerjoin(
            BoardAssetItem,
            and_(
                BoardAssetItem.board_section_id == BoardSection.id,
                BoardAssetItem.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            Asset,
            and_(
                Asset.id == BoardAssetItem.asset_id,
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
        .where(Board.deleted_at.is_(None))
        .group_by(Board.id)
    )


async def board_preview_items(
    session: AsyncSession, board_id: int, limit: int
) -> list[dict[str, Any]]:
    """The first ``limit`` items of a board in display order, compactly.

    Carries only what a cover filmstrip draws: Asset and payload identity,
    format, and dimensions. Ordered like ``serialize_board`` flattens its
    sections, without loading the rest of the board.
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
        .join(BoardAssetItem, BoardAssetItem.asset_id == Asset.id)
        .join(BoardSection, BoardSection.id == BoardAssetItem.board_section_id)
        .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
        .where(
            BoardSection.board_id == board_id,
            BoardSection.deleted_at.is_(None),
            BoardAssetItem.deleted_at.is_(None),
            Asset.state == "active",
            Asset.deleted_at.is_(None),
            _live_media_condition(),
        )
        .order_by(
            BoardSection.display_order.asc(),
            BoardSection.id.asc(),
            BoardAssetItem.display_order.asc(),
            BoardAssetItem.added_at.asc(),
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

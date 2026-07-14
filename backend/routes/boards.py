"""Board management routes."""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from board_service import serialize_board
from core.dependencies import get_db_session
from core.logging import get_logger
from database import Asset, Board, BoardAssetItem, BoardItem, BoardSection, MediaItem, MediaMarker
from models.api_models import (
    BoardAddItemsRequest,
    BoardBulkMoveRequest,
    BoardBulkRemoveRequest,
    BoardCreateRequest,
    BoardMoveItemRequest,
    BoardResponse,
    BoardSectionCreateRequest,
    BoardSectionReorderRequest,
    BoardSectionResponse,
    BoardSectionUpdateRequest,
    BoardSummaryResponse,
    BoardUpdateRequest,
)
from project_service import attach_media_to_project, get_project_or_404
from utils.background_tasks import clear_auto_delete_for_media
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/boards", tags=["boards"])
log = get_logger(__name__)


def _track_board_event(event: str, board_id: int, extra: dict | None = None) -> None:
    """Emit a board event carrying boardHash (install-salted; never ids/names)."""
    try:
        from object_hash import salted_hash
        from telemetry import get_telemetry_client
        props = {"boardHash": salted_hash(f"board:{board_id}")}
        if extra:
            props.update(extra)
        get_telemetry_client().track(event, props, category="organize")
    except Exception:  # noqa: BLE001 — telemetry never affects the app
        pass


async def _get_board_or_404(board_id: int, session: AsyncSession) -> Board:
    result = await session.execute(
        select(Board).where(Board.id == board_id, Board.deleted_at.is_(None))
    )
    board = result.scalar_one_or_none()
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")
    return board


async def _get_section_or_404(section_id: int, session: AsyncSession) -> BoardSection:
    result = await session.execute(
        select(BoardSection).where(BoardSection.id == section_id, BoardSection.deleted_at.is_(None))
    )
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(status_code=404, detail="Board section not found")
    return section


async def _ensure_default_section(board_id: int, session: AsyncSession) -> BoardSection:
    result = await session.execute(
        select(BoardSection)
        .where(
            BoardSection.board_id == board_id,
            BoardSection.is_default.is_(True),
            BoardSection.deleted_at.is_(None),
        )
        .limit(1)
    )
    section = result.scalar_one_or_none()
    if section:
        return section

    max_order = await session.scalar(
        select(func.coalesce(func.max(BoardSection.display_order), -1)).where(
            BoardSection.board_id == board_id,
            BoardSection.deleted_at.is_(None),
        )
    )
    section = BoardSection(
        board_id=board_id,
        name=None,
        is_default=True,
        display_order=(max_order or -1) + 1,
    )
    session.add(section)
    await session.flush()
    return section


async def _compact_section_orders(board_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(BoardSection)
        .where(BoardSection.board_id == board_id, BoardSection.deleted_at.is_(None))
        .order_by(BoardSection.display_order.asc(), BoardSection.id.asc())
    )
    for index, section in enumerate(result.scalars().all()):
        section.display_order = index


async def _compact_item_orders(section_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(BoardItem)
        .where(BoardItem.board_section_id == section_id)
        .order_by(BoardItem.display_order.asc(), BoardItem.added_at.asc())
    )
    for index, item in enumerate(result.scalars().all()):
        item.display_order = index


async def _compact_asset_item_orders(section_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(BoardAssetItem)
        .where(
            BoardAssetItem.board_section_id == section_id,
            BoardAssetItem.deleted_at.is_(None),
        )
        .order_by(BoardAssetItem.display_order.asc(), BoardAssetItem.added_at.asc())
    )
    for index, item in enumerate(result.scalars().all()):
        item.display_order = index


async def _delete_section_if_empty(section: BoardSection, session: AsyncSession) -> None:
    if section.is_default:
        return

    item_count = await session.scalar(
        select(func.count()).select_from(BoardItem).where(BoardItem.board_section_id == section.id)
    )
    asset_item_count = await session.scalar(
        select(func.count()).select_from(BoardAssetItem).where(
            BoardAssetItem.board_section_id == section.id,
            BoardAssetItem.deleted_at.is_(None),
        )
    )
    if item_count or asset_item_count:
        return

    section.deleted_at = datetime.utcnow()
    section.updated_at = datetime.utcnow()
    await session.flush()
    await _compact_section_orders(section.board_id, session)


async def _serialize_board(board: Board, session: AsyncSession) -> BoardResponse:
    return await serialize_board(board, session)


@router.get("", response_model=List[BoardSummaryResponse])
async def get_boards(
    project_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    query = (
        select(
            Board,
            (
                func.count(func.distinct(MediaItem.id))
                + func.count(func.distinct(BoardAssetItem.id))
            ).label("asset_count"),
        )
        .outerjoin(BoardSection, and_(BoardSection.board_id == Board.id, BoardSection.deleted_at.is_(None)))
        .outerjoin(BoardItem, BoardItem.board_section_id == BoardSection.id)
        .outerjoin(MediaItem, and_(MediaItem.id == BoardItem.media_id, MediaItem.deleted_at.is_(None)))
        .outerjoin(
            BoardAssetItem,
            and_(
                BoardAssetItem.board_section_id == BoardSection.id,
                BoardAssetItem.deleted_at.is_(None),
            ),
        )
        .where(Board.deleted_at.is_(None))
        .group_by(Board.id)
        .order_by(Board.updated_at.desc())
    )
    if project_id is None:
        query = query.where(Board.project_id.is_(None))
    else:
        query = query.where(Board.project_id == project_id)
    result = await session.execute(query)
    return [
        BoardSummaryResponse(**board.to_dict(), asset_count=asset_count)
        for board, asset_count in result.all()
    ]


@router.post("", response_model=BoardResponse)
async def create_board(
    request: BoardCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if request.project_id is not None:
        await get_project_or_404(session, request.project_id)
    board = Board(name=request.name or "", project_id=request.project_id)
    session.add(board)
    await session.flush()
    await _ensure_default_section(board.id, session)
    await session.commit()
    await session.refresh(board)
    _created_extra: dict = {}
    if board.project_id:
        from object_hash import salted_hash
        _created_extra["projectHash"] = salted_hash(f"project:{board.project_id}")
    _track_board_event("board_created", board.id, _created_extra)
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_created", {"board": payload.model_dump()})
    return payload


@router.get("/{board_id}", response_model=BoardResponse)
async def get_board(board_id: int, session: AsyncSession = Depends(get_db_session)):
    board = await _get_board_or_404(board_id, session)
    await _ensure_default_section(board.id, session)
    await session.commit()
    return await _serialize_board(board, session)


@router.put("/{board_id}", response_model=BoardResponse)
async def update_board(
    board_id: int,
    request: BoardUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    if request.name is not None:
        board.name = request.name
    if 'project_id' in request.model_fields_set:
        board.project_id = request.project_id
    board.updated_at = datetime.utcnow()
    await session.commit()
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_updated", {"board": payload.model_dump()})
    return payload


@router.delete("/{board_id}")
async def delete_board(board_id: int, session: AsyncSession = Depends(get_db_session)):
    board = await _get_board_or_404(board_id, session)
    board.deleted_at = datetime.utcnow()
    board.updated_at = datetime.utcnow()
    await session.commit()
    await ws_manager.broadcast("board_deleted", {"board_id": board_id})
    _track_board_event("board_deleted", board_id)
    return {"status": "success", "message": "Board deleted"}


@router.post("/{board_id}/restore", response_model=BoardResponse)
async def restore_board(board_id: int, session: AsyncSession = Depends(get_db_session)):
    """Clear the soft-delete tombstone — pairs with DELETE for undo."""
    result = await session.execute(select(Board).where(Board.id == board_id))
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    if board.deleted_at is None:
        raise HTTPException(status_code=400, detail="Board is not deleted")
    board.deleted_at = None
    board.updated_at = datetime.utcnow()
    await session.commit()
    await _ensure_default_section(board.id, session)
    await session.commit()
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_restored", {"board": payload.model_dump()})
    return payload


@router.post("/{board_id}/sections", response_model=BoardSectionResponse)
async def create_board_section(
    board_id: int,
    request: BoardSectionCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    max_order = await session.scalar(
        select(func.coalesce(func.max(BoardSection.display_order), -1)).where(
            BoardSection.board_id == board.id,
            BoardSection.deleted_at.is_(None),
        )
    )
    section = BoardSection(
        board_id=board.id,
        name=request.name,
        is_default=False,
        display_order=(max_order or -1) + 1,
    )
    session.add(section)
    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event("board_section_added", board_id)
    payload = BoardSectionResponse(**section.to_dict(), items=[], item_count=0)
    await ws_manager.broadcast("board_section_created", {"board_id": board_id, "section": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": (await _serialize_board(board, session)).model_dump()})
    return payload


@router.put("/sections/{section_id}", response_model=BoardSectionResponse)
async def update_board_section(
    section_id: int,
    request: BoardSectionUpdateRequest,
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
    board = await _get_board_or_404(section.board_id, session)
    board.updated_at = datetime.utcnow()
    await session.commit()

    item_count = await session.scalar(
        select(func.count()).select_from(BoardItem).where(BoardItem.board_section_id == section.id)
    )
    payload = BoardSectionResponse(**section.to_dict(), items=[], item_count=item_count or 0)
    await ws_manager.broadcast("board_section_updated", {"board_id": board.id, "section": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": (await _serialize_board(board, session)).model_dump()})
    return payload


@router.delete("/sections/{section_id}")
async def delete_board_section(section_id: int, session: AsyncSession = Depends(get_db_session)):
    section = await _get_section_or_404(section_id, session)
    board = await _get_board_or_404(section.board_id, session)
    was_default = section.is_default
    await session.execute(delete(BoardItem).where(BoardItem.board_section_id == section.id))
    await session.execute(
        delete(BoardAssetItem).where(BoardAssetItem.board_section_id == section.id)
    )
    section.deleted_at = datetime.utcnow()
    section.updated_at = datetime.utcnow()
    section.is_default = False
    await session.flush()
    if was_default:
        # Promote the next remaining section (lowest display_order) to default so the
        # board always has one. If none remain, _ensure_default_section will create one.
        result = await session.execute(
            select(BoardSection)
            .where(BoardSection.board_id == board.id, BoardSection.deleted_at.is_(None))
            .order_by(BoardSection.display_order.asc(), BoardSection.id.asc())
            .limit(1)
        )
        promoted = result.scalar_one_or_none()
        if promoted is not None:
            promoted.is_default = True
        else:
            await _ensure_default_section(board.id, session)
    await _compact_section_orders(board.id, session)
    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event("board_section_removed", board.id)
    await ws_manager.broadcast("board_section_deleted", {"board_id": board.id, "section_id": section_id})
    await ws_manager.broadcast("board_updated", {"board": (await _serialize_board(board, session)).model_dump()})
    return {"status": "success"}


@router.post("/{board_id}/sections/reorder")
async def reorder_board_sections(
    board_id: int,
    request: BoardSectionReorderRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    result = await session.execute(
        select(BoardSection).where(
            BoardSection.board_id == board.id,
            BoardSection.deleted_at.is_(None),
        )
    )
    sections_by_id = {section.id: section for section in result.scalars().all()}
    for index, section_id in enumerate(request.section_ids):
        section = sections_by_id.get(section_id)
        if section:
            section.display_order = index
    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event("board_sections_reordered", board.id)
    await ws_manager.broadcast("board_updated", {"board": (await _serialize_board(board, session)).model_dump()})
    return {"status": "success"}


@router.post("/{board_id}/items")
async def add_board_items(
    board_id: int,
    request: BoardAddItemsRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    if request.section_id is not None:
        section = await _get_section_or_404(request.section_id, session)
        if section.board_id != board.id:
            raise HTTPException(status_code=400, detail="Section does not belong to board")
    else:
        section = await _ensure_default_section(board.id, session)

    max_order = await session.scalar(
        select(func.coalesce(func.max(BoardItem.display_order), -1)).where(BoardItem.board_section_id == section.id)
    )
    max_asset_order = await session.scalar(
        select(func.coalesce(func.max(BoardAssetItem.display_order), -1)).where(
            BoardAssetItem.board_section_id == section.id,
            BoardAssetItem.deleted_at.is_(None),
        )
    )
    next_order = max(max_order or -1, max_asset_order or -1) + 1
    added = 0
    valid_asset_ids = set(
        await session.scalars(
            select(Asset.id).where(
                Asset.id.in_(request.asset_ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    )
    from asset_association_service import attach_asset_to_board_section
    for asset_id in request.asset_ids:
        if asset_id not in valid_asset_ids:
            continue
        _, was_added = await attach_asset_to_board_section(
            session,
            board=board,
            section_id=section.id,
            asset_id=asset_id,
            display_order=next_order,
        )
        if was_added:
            next_order += 1
            added += 1
    for media_id in request.media_ids:
        existing = await session.execute(
            select(BoardItem).where(BoardItem.board_section_id == section.id, BoardItem.media_id == media_id)
        )
        if existing.scalar_one_or_none():
            continue
        session.add(BoardItem(board_section_id=section.id, media_id=media_id, display_order=next_order))
        if board.project_id is not None:
            await attach_media_to_project(session, board.project_id, media_id)
        next_order += 1
        added += 1

    board.updated_at = datetime.utcnow()
    await session.commit()
    if valid_asset_ids:
        from asset_association_service import broadcast_assets_retained

        await broadcast_assets_retained(session, valid_asset_ids, ws_manager)
    if added > 0:
        if request.media_ids:
            await clear_auto_delete_for_media(session, request.media_ids, ws_manager)
        _track_board_event("board_items_added", board.id, {"count": added})
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": payload.model_dump()})
    return {"status": "success", "added": added}


@router.delete("/sections/{section_id}/items/{media_id}")
async def remove_board_item(
    section_id: int,
    media_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    section = await _get_section_or_404(section_id, session)
    board = await _get_board_or_404(section.board_id, session)
    await session.execute(
        delete(BoardItem).where(BoardItem.board_section_id == section.id, BoardItem.media_id == media_id)
    )
    await _compact_item_orders(section.id, session)
    await _delete_section_if_empty(section, session)
    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event("board_items_removed", board.id, {"count": 1})
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": payload.model_dump()})
    return {"status": "success"}


@router.delete("/sections/{section_id}/asset-items/{asset_id}")
async def remove_board_asset_item(
    section_id: int,
    asset_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    section = await _get_section_or_404(section_id, session)
    board = await _get_board_or_404(section.board_id, session)
    row = await session.scalar(
        select(BoardAssetItem).where(
            BoardAssetItem.board_section_id == section.id,
            BoardAssetItem.asset_id == asset_id,
            BoardAssetItem.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Board Asset not found")
    row.deleted_at = datetime.utcnow()
    await _compact_asset_item_orders(section.id, session)
    await _delete_section_if_empty(section, session)
    board.updated_at = datetime.utcnow()
    await session.commit()
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast(
        "board_items_changed", {"board_id": board.id, "board": payload.model_dump()}
    )
    return {"status": "success"}


@router.post("/{board_id}/items/move")
async def move_board_item(
    board_id: int,
    request: BoardMoveItemRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    source_section = await _get_section_or_404(request.from_section_id, session)
    target_section = await _get_section_or_404(request.to_section_id, session)
    if source_section.board_id != board.id or target_section.board_id != board.id:
        raise HTTPException(status_code=400, detail="Sections do not belong to board")

    result = await session.execute(
        select(BoardItem).where(
            BoardItem.board_section_id == source_section.id,
            BoardItem.media_id == request.media_id,
        )
    )
    board_item = result.scalar_one_or_none()
    if not board_item:
        raise HTTPException(status_code=404, detail="Board item not found")

    target_items_result = await session.execute(
        select(BoardItem)
        .where(BoardItem.board_section_id == target_section.id)
        .order_by(BoardItem.display_order.asc(), BoardItem.added_at.asc())
    )
    target_items = target_items_result.scalars().all()

    if source_section.id == target_section.id:
        target_items = [item for item in target_items if item.media_id != request.media_id]
        target_index = max(0, min(request.target_index, len(target_items)))
        target_items.insert(target_index, board_item)
        for index, item in enumerate(target_items):
            item.display_order = index
    else:
        existing_target_item = next(
            (item for item in target_items if item.media_id == request.media_id),
            None,
        )

        if existing_target_item is not None:
            await session.delete(board_item)
            moved_item = existing_target_item
        else:
            board_item.board_section_id = target_section.id
            moved_item = board_item

        await session.flush()
        await _compact_item_orders(source_section.id, session)
        await _delete_section_if_empty(source_section, session)

        target_items = [item for item in target_items if item.media_id != request.media_id]
        target_index = max(0, min(request.target_index, len(target_items)))
        target_items.insert(target_index, moved_item)
        for index, item in enumerate(target_items):
            item.board_section_id = target_section.id
            item.display_order = index
            session.add(item)

    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event("board_items_moved", board.id, {"count": 1})
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": payload.model_dump()})
    return {"status": "success"}


@router.post("/{board_id}/asset-items/move")
async def move_board_asset_item(
    board_id: int,
    request: BoardMoveItemRequest,
    session: AsyncSession = Depends(get_db_session),
):
    if request.asset_id is None:
        raise HTTPException(status_code=400, detail="asset_id is required")
    board = await _get_board_or_404(board_id, session)
    source_section = await _get_section_or_404(request.from_section_id, session)
    target_section = await _get_section_or_404(request.to_section_id, session)
    if source_section.board_id != board.id or target_section.board_id != board.id:
        raise HTTPException(status_code=400, detail="Sections do not belong to board")
    board_item = await session.scalar(
        select(BoardAssetItem).where(
            BoardAssetItem.board_section_id == source_section.id,
            BoardAssetItem.asset_id == request.asset_id,
            BoardAssetItem.deleted_at.is_(None),
        )
    )
    if board_item is None:
        raise HTTPException(status_code=404, detail="Board Asset not found")
    target_items = list(
        await session.scalars(
            select(BoardAssetItem)
            .where(
                BoardAssetItem.board_section_id == target_section.id,
                BoardAssetItem.deleted_at.is_(None),
            )
            .order_by(BoardAssetItem.display_order, BoardAssetItem.added_at)
        )
    )
    target_items = [item for item in target_items if item.asset_id != request.asset_id]
    if source_section.id != target_section.id:
        duplicate = await session.scalar(
            select(BoardAssetItem).where(
                BoardAssetItem.board_section_id == target_section.id,
                BoardAssetItem.asset_id == request.asset_id,
                BoardAssetItem.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            board_item.deleted_at = datetime.utcnow()
            moved_item = duplicate
        else:
            board_item.board_section_id = target_section.id
            moved_item = board_item
        await _compact_asset_item_orders(source_section.id, session)
        await _delete_section_if_empty(source_section, session)
    else:
        moved_item = board_item
    target_index = max(0, min(request.target_index, len(target_items)))
    target_items.insert(target_index, moved_item)
    for index, item in enumerate(target_items):
        item.display_order = index
    board.updated_at = datetime.utcnow()
    await session.commit()
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast(
        "board_items_changed", {"board_id": board.id, "board": payload.model_dump()}
    )
    return {"status": "success"}


@router.post("/{board_id}/items/bulk-remove")
async def bulk_remove_board_items(
    board_id: int,
    request: BoardBulkRemoveRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    media_ids_set = set(request.media_ids)
    asset_ids_set = set(request.asset_ids)

    sections_result = await session.execute(
        select(BoardSection).where(
            BoardSection.board_id == board.id,
            BoardSection.deleted_at.is_(None),
        )
    )
    sections = sections_result.scalars().all()

    for section in sections:
        await session.execute(
            delete(BoardItem).where(
                BoardItem.board_section_id == section.id,
                BoardItem.media_id.in_(media_ids_set),
            )
        )
        if asset_ids_set:
            rows = list(
                await session.scalars(
                    select(BoardAssetItem).where(
                        BoardAssetItem.board_section_id == section.id,
                        BoardAssetItem.asset_id.in_(asset_ids_set),
                        BoardAssetItem.deleted_at.is_(None),
                    )
                )
            )
            for row in rows:
                row.deleted_at = datetime.utcnow()
        await _compact_item_orders(section.id, session)
        await _compact_asset_item_orders(section.id, session)
        await _delete_section_if_empty(section, session)

    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event(
        "board_items_removed", board.id,
        {"count": len(media_ids_set) + len(asset_ids_set)},
    )
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": payload.model_dump()})
    return {"status": "success"}


@router.post("/{board_id}/items/bulk-move")
async def bulk_move_board_items(
    board_id: int,
    request: BoardBulkMoveRequest,
    session: AsyncSession = Depends(get_db_session),
):
    board = await _get_board_or_404(board_id, session)
    target_section = await _get_section_or_404(request.to_section_id, session)
    if target_section.board_id != board.id:
        raise HTTPException(status_code=400, detail="Section does not belong to board")

    media_ids_set = set(request.media_ids)
    asset_ids_set = set(request.asset_ids)

    sections_result = await session.execute(
        select(BoardSection).where(
            BoardSection.board_id == board.id,
            BoardSection.deleted_at.is_(None),
        )
    )
    sections = sections_result.scalars().all()

    for section in sections:
        if section.id == target_section.id:
            continue
        await session.execute(
            delete(BoardItem).where(
                BoardItem.board_section_id == section.id,
                BoardItem.media_id.in_(media_ids_set),
            )
        )
        await _compact_item_orders(section.id, session)
        if asset_ids_set:
            asset_rows = list(
                await session.scalars(
                    select(BoardAssetItem).where(
                        BoardAssetItem.board_section_id == section.id,
                        BoardAssetItem.asset_id.in_(asset_ids_set),
                        BoardAssetItem.deleted_at.is_(None),
                    )
                )
            )
            for row in asset_rows:
                row.deleted_at = datetime.utcnow()
            await _compact_asset_item_orders(section.id, session)
        await _delete_section_if_empty(section, session)

    max_order = await session.scalar(
        select(func.coalesce(func.max(BoardItem.display_order), -1)).where(
            BoardItem.board_section_id == target_section.id
        )
    )
    next_order = (max_order or -1) + 1

    existing_result = await session.execute(
        select(BoardItem.media_id).where(
            BoardItem.board_section_id == target_section.id,
            BoardItem.media_id.in_(media_ids_set),
        )
    )
    already_in_target = set(existing_result.scalars().all())

    for media_id in request.media_ids:
        if media_id in already_in_target:
            continue
        session.add(BoardItem(board_section_id=target_section.id, media_id=media_id, display_order=next_order))
        next_order += 1

    max_asset_order = await session.scalar(
        select(func.coalesce(func.max(BoardAssetItem.display_order), -1)).where(
            BoardAssetItem.board_section_id == target_section.id,
            BoardAssetItem.deleted_at.is_(None),
        )
    )
    next_asset_order = (max_asset_order or -1) + 1
    existing_asset_ids = set(
        await session.scalars(
            select(BoardAssetItem.asset_id).where(
                BoardAssetItem.board_section_id == target_section.id,
                BoardAssetItem.asset_id.in_(asset_ids_set),
                BoardAssetItem.deleted_at.is_(None),
            )
        )
    )
    for asset_id in request.asset_ids:
        if asset_id in existing_asset_ids:
            continue
        session.add(
            BoardAssetItem(
                board_section_id=target_section.id,
                asset_id=asset_id,
                display_order=next_asset_order,
            )
        )
        next_asset_order += 1

    board.updated_at = datetime.utcnow()
    await session.commit()
    _track_board_event(
        "board_items_moved", board.id,
        {"count": len(media_ids_set) + len(asset_ids_set)},
    )
    payload = await _serialize_board(board, session)
    await ws_manager.broadcast("board_items_changed", {"board_id": board.id, "board": payload.model_dump()})
    await ws_manager.broadcast("board_updated", {"board": payload.model_dump()})
    return {"status": "success"}

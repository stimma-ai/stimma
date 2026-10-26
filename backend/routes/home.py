"""Home screen read model.

Home shows a few "Jump back in" cards: the most recently updated boards,
flows, and chats in the current scope, each with a little cover artwork.
This endpoint selects those cards on the server and returns only what they
draw, so the response stays the same size however large the boards, flows,
and chats behind them grow. Clients on older servers fall back to the
general list and detail endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from board_service import board_asset_count_column, board_preview_items, board_summaries_query
from core.dependencies import get_db_session
from database import Board, Chat, ChatItem, Flow, MediaItem
from project_service import PROJECT_NONE, parse_project_filter
from routes.chats import ChatPreview, build_chat_previews
from routes.flows import _serialize as serialize_flow, flow_output_media_ids

router = APIRouter(prefix="/api/home", tags=["home"])

# What one card draws: a board filmstrip of up to six tiles, a flow strip of
# up to three outputs, a chat cover of one image and a one-line snippet.
BOARD_PREVIEW_ITEMS = 6
FLOW_PREVIEW_MEDIA = 3
CHAT_PREVIEW_MEDIA = 1
CHAT_SNIPPET_CHARS = 240
# Unnamed flows with no program state are skipped; stop looking after this
# many so a scope full of stray flows can't make the read unbounded.
FLOW_SCAN_LIMIT = 50


class HomeBoardPreviewItem(BaseModel):
    id: int
    asset_id: int
    revision_id: int
    media_id: int
    file_hash: Optional[str] = None
    file_format: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class HomeBoard(BaseModel):
    id: int
    name: str
    project_id: Optional[int] = None
    created_at: str
    updated_at: str
    asset_count: int
    preview_items: list[HomeBoardPreviewItem]


class HomeMediaRef(BaseModel):
    media_id: int
    file_hash: Optional[str] = None


class HomeFlow(BaseModel):
    id: int
    name: str
    project_id: Optional[int] = None
    execution_state: str
    pending_task_count: int = 0
    root_status_summary: dict[str, int] = {}
    has_load_error: bool = False
    created_at: str
    updated_at: str
    preview_media: list[HomeMediaRef]


class HomeBoardCard(BaseModel):
    type: Literal["board"] = "board"
    board: HomeBoard


class HomeFlowCard(BaseModel):
    type: Literal["flow"] = "flow"
    flow: HomeFlow


class HomeChatCard(BaseModel):
    type: Literal["chat"] = "chat"
    chat: ChatPreview


class HomeRecentsResponse(BaseModel):
    # Newest first, at most `limit`.
    items: list[Union[HomeBoardCard, HomeFlowCard, HomeChatCard]]
    # Whether the scope has any boards, flows, or chats at all, including
    # ones too empty to show. Home's first-run welcome needs none.
    has_entities: bool


def _scoped(query, column, project_filter):
    if project_filter is None or project_filter == PROJECT_NONE:
        return query.where(column.is_(None))
    return query.where(column == project_filter)


def _chat_has_messages():
    return exists().where(
        ChatItem.chat_id == Chat.id,
        ChatItem.item_type.in_(["user_message", "assistant_message"]),
        ChatItem.message_text.isnot(None),
        ChatItem.message_text != "",
    )


def _flow_is_empty(flow) -> bool:
    """An unnamed flow with no program state is a stray "New flow" click."""
    if flow.name:
        return False
    if flow.has_load_error or (flow.pending_task_count or 0) > 0:
        return False
    return not flow.root_status_summary


async def _board_candidates(session, project_filter, limit):
    count = board_asset_count_column()
    query = (
        board_summaries_query()
        .having(or_(func.coalesce(Board.name, "") != "", count > 0))
        .order_by(Board.updated_at.desc(), Board.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(_scoped(query, Board.project_id, project_filter))).all()
    return [(board.updated_at, "board", (board, asset_count)) for board, asset_count in rows]


async def _chat_candidates(session, project_filter, limit):
    query = (
        select(Chat)
        .where(
            Chat.deleted_at.is_(None),
            Chat.flow_id.is_(None),
            or_(func.coalesce(Chat.name, "") != "", _chat_has_messages()),
        )
        .order_by(desc(Chat.updated_at), desc(Chat.id))
        .limit(limit)
    )
    chats = (await session.execute(_scoped(query, Chat.project_id, project_filter))).scalars().all()
    return [(chat.updated_at, "chat", chat) for chat in chats]


async def _flow_candidates(session, project_filter, limit):
    query = _scoped(
        select(Flow).where(Flow.deleted_at.is_(None)), Flow.project_id, project_filter,
    ).order_by(desc(Flow.updated_at), desc(Flow.id)).limit(FLOW_SCAN_LIMIT)
    picked = []
    for flow in (await session.execute(query)).scalars().all():
        serialized = serialize_flow(flow)
        if _flow_is_empty(serialized):
            continue
        picked.append((flow.updated_at, "flow", serialized))
        if len(picked) >= limit:
            break
    return picked


async def _scope_has_entities(session, project_filter) -> bool:
    for model, extra in (
        (Board, ()),
        (Flow, ()),
        (Chat, (Chat.flow_id.is_(None),)),
    ):
        query = _scoped(
            select(model.id).where(model.deleted_at.is_(None), *extra),
            model.project_id,
            project_filter,
        ).limit(1)
        if (await session.execute(query)).first() is not None:
            return True
    return False


async def _flow_preview_media(session, flow_id: int) -> list[HomeMediaRef]:
    media_ids = flow_output_media_ids(flow_id)[:FLOW_PREVIEW_MEDIA]
    if not media_ids:
        return []
    hashes = dict(
        (await session.execute(
            select(MediaItem.id, MediaItem.file_hash).where(MediaItem.id.in_(media_ids))
        )).all()
    )
    return [HomeMediaRef(media_id=mid, file_hash=hashes.get(mid)) for mid in media_ids]


@router.get("/recents", response_model=HomeRecentsResponse)
async def get_home_recents(
    project_id: Optional[str] = Query(None),
    limit: int = Query(3, ge=1, le=12),
    session: AsyncSession = Depends(get_db_session),
):
    """The newest boards, flows, and chats worth jumping back into.

    Scoped like the list endpoints: a project's own items, or with no
    ``project_id`` (or ``none``) the items with no project. Empty, unnamed
    entities are skipped, the rest are merged by update time, and only the
    newest ``limit`` are returned, each with just its card artwork.
    """
    project_filter = parse_project_filter(project_id)
    candidates = [
        *await _board_candidates(session, project_filter, limit),
        *await _flow_candidates(session, project_filter, limit),
        *await _chat_candidates(session, project_filter, limit),
    ]
    candidates.sort(key=lambda c: c[0] or datetime.min, reverse=True)
    selected = candidates[:limit]

    chats = [entity for _, kind, entity in selected if kind == "chat"]
    chat_previews = {
        preview.id: preview
        for preview in await build_chat_previews(
            session, chats,
            media_limit=CHAT_PREVIEW_MEDIA,
            last_message_chars=CHAT_SNIPPET_CHARS,
        )
    }

    items: list[Union[HomeBoardCard, HomeFlowCard, HomeChatCard]] = []
    for _, kind, entity in selected:
        if kind == "board":
            board, asset_count = entity
            items.append(HomeBoardCard(board=HomeBoard(
                **board.to_dict(),
                asset_count=asset_count or 0,
                preview_items=await board_preview_items(session, board.id, BOARD_PREVIEW_ITEMS),
            )))
        elif kind == "flow":
            flow = entity
            items.append(HomeFlowCard(flow=HomeFlow(
                **flow.model_dump(include=set(HomeFlow.model_fields) - {"preview_media"}),
                preview_media=await _flow_preview_media(session, flow.id),
            )))
        else:
            items.append(HomeChatCard(chat=chat_previews[entity.id]))

    has_entities = bool(items) or await _scope_has_entities(session, project_filter)
    return HomeRecentsResponse(items=items, has_entities=has_entities)

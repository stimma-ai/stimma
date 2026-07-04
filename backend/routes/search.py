"""
Global search across named entities.

One endpoint powering the omnibox and the full /search page: case-insensitive
name matching over chats, flows, boards, projects, and presets. Tools,
stimpacks, and media are matched elsewhere (tools/stimpacks client-side from
the already-cached catalogs, media via /api/media text search).
"""

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Board, BoardItem, BoardSection, Chat, Flow, MediaItem, Preset, Project
from core.dependencies import get_db_session
from core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

# Hard cap on rows fetched per entity type before matching. Entity tables are
# small (user-scale, not library-scale), so a full scan + Python matching is
# fine and lets matching be punctuation-insensitive ("flux2" ~ "Flux.2").
FETCH_CAP = 10000


class MediaRef(BaseModel):
    media_id: int
    file_hash: Optional[str] = None


class SearchHit(BaseModel):
    id: int
    name: str
    updated_at: Optional[str] = None
    project_id: Optional[int] = None
    # Presets only: the tool the preset belongs to.
    tool_id: Optional[str] = None
    # Chats only: most recent generated media, for the row thumbnail.
    thumbnail: Optional[MediaRef] = None
    # Boards only: first items, for the mosaic preview tile.
    preview_items: Optional[List[MediaRef]] = None


class SearchResponse(BaseModel):
    query: str
    chats: List[SearchHit]
    flows: List[SearchHit]
    boards: List[SearchHit]
    projects: List[SearchHit]
    presets: List[SearchHit]


def _normalize(s: str) -> str:
    """Lowercase and strip separators so "flux2" matches "Flux.2"."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _tokenize(q: str) -> List[str]:
    return [t for t in (_normalize(part) for part in q.split()) if t]


def _match_and_rank(rows, tokens: List[str], limit: int):
    """Every query token must appear in the normalized name (any order).

    Ranking: normalized-prefix matches first, then contiguous matches, then
    scattered token matches; most recently updated breaks ties.
    """
    joined = "".join(tokens)
    scored = []
    for row in rows:
        name = _normalize(row.name or "")
        if not all(t in name for t in tokens):
            continue
        prefix = 0 if name.startswith(joined) else 1
        contiguous = 0 if joined in name else 1
        updated = row.updated_at
        ts = updated.timestamp() if updated is not None else 0.0
        scored.append(((prefix, contiguous, -ts), row))
    scored.sort(key=lambda item: item[0])
    return [row for _, row in scored[:limit]]


def _hit(row, tool_id: bool = False) -> SearchHit:
    return SearchHit(
        id=row.id,
        name=row.name or "",
        updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        project_id=getattr(row, "project_id", None),
        tool_id=row.tool_id if tool_id else None,
    )


async def _chat_thumbnails(session: AsyncSession, chat_ids: List[int]) -> dict:
    """Most recent generated media per chat (matches the sidebar's chat thumbnails)."""
    from routes.chats import collect_chat_media

    media_ids_by_chat, media_info = await collect_chat_media(session, chat_ids)
    thumbnails: dict = {}
    for chat_id, media_ids in media_ids_by_chat.items():
        for media_id in media_ids:
            if media_id in media_info:
                thumbnails[chat_id] = MediaRef(media_id=media_id, file_hash=media_info[media_id])
                break
    return thumbnails


async def _board_previews(session: AsyncSession, board_ids: List[int]) -> dict:
    """First items per board for the 2x2 mosaic (matches sidebar/home boards)."""
    if not board_ids:
        return {}
    query = (
        select(BoardSection.board_id, MediaItem.id, MediaItem.file_hash)
        .join(BoardItem, BoardItem.board_section_id == BoardSection.id)
        .join(MediaItem, MediaItem.id == BoardItem.media_id)
        .where(
            BoardSection.board_id.in_(board_ids),
            BoardSection.deleted_at.is_(None),
            MediaItem.deleted_at.is_(None),
        )
        .order_by(BoardSection.board_id, BoardItem.display_order)
    )
    previews: dict = {}
    for board_id, media_id, file_hash in (await session.execute(query)).all():
        items = previews.setdefault(board_id, [])
        if len(items) < 4:
            items.append(MediaRef(media_id=media_id, file_hash=file_hash))
    return previews


@router.get("", response_model=SearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(8, ge=1, le=50, description="Max results per entity type"),
    project_id: Optional[int] = Query(None, description="Scope chats/flows/boards to a project"),
    session: AsyncSession = Depends(get_db_session),
):
    """Search entity names for the omnibox / search page."""
    tokens = _tokenize(q)
    if not tokens:
        return SearchResponse(query=q, chats=[], flows=[], boards=[], projects=[], presets=[])

    async def fetch(model, *extra_filters):
        query = select(model).where(model.deleted_at.is_(None)).limit(FETCH_CAP)
        for f in extra_filters:
            query = query.where(f)
        result = await session.execute(query)
        return result.scalars().all()

    def scoped(model):
        return [model.project_id == project_id] if project_id is not None else []

    # Flow-backed chats surface through their flow, not as standalone chats.
    chats = await fetch(Chat, Chat.flow_id.is_(None), *scoped(Chat))
    flows = await fetch(Flow, *scoped(Flow))
    boards = await fetch(Board, *scoped(Board))
    # Searching projects makes no sense inside a project scope.
    projects = [] if project_id is not None else await fetch(Project)
    presets = await fetch(Preset)

    chat_hits = [_hit(r) for r in _match_and_rank(chats, tokens, limit)]
    board_hits = [_hit(r) for r in _match_and_rank(boards, tokens, limit)]

    # Preview enrichment for the returned hits only (same treatments as the
    # sidebar: chat thumbnail, board mosaic).
    thumbnails = await _chat_thumbnails(session, [h.id for h in chat_hits])
    previews = await _board_previews(session, [h.id for h in board_hits])
    for hit in chat_hits:
        hit.thumbnail = thumbnails.get(hit.id)
    for hit in board_hits:
        hit.preview_items = previews.get(hit.id)

    return SearchResponse(
        query=q,
        chats=chat_hits,
        flows=[_hit(r) for r in _match_and_rank(flows, tokens, limit)],
        boards=board_hits,
        projects=[_hit(r) for r in _match_and_rank(projects, tokens, limit)],
        presets=[_hit(r, tool_id=True) for r in _match_and_rank(presets, tokens, limit)],
    )

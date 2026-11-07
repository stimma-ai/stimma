"""Contact sheet review: answers and comments the user leaves for the agent.

The sheet itself is ordinary container media (``/api/media/{id}/content``).
These routes hold the review, which lives beside the document, keyed by the
sheet's asset and a component id, and deliver it to the agent as a message.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contact_sheet import (
    SheetError,
    add_comment,
    get_review,
    require_sheet_asset,
    review_row_dict,
    set_answer,
    take_pending_review,
)
from core.dependencies import get_db_session
from core.logging import get_logger
from database import Chat, ContactSheetReview
from utils.websocket import ws_manager

log = get_logger(__name__)

router = APIRouter(prefix="/api/contact-sheets", tags=["contact-sheets"])


class AnswerRequest(BaseModel):
    value: Any = None


class CommentRequest(BaseModel):
    anchor: str
    text: str


class SendRequest(BaseModel):
    chat_id: int


async def _sheet(session: AsyncSession, asset_id: int):
    try:
        return await require_sheet_asset(session, asset_id)
    except SheetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _changed(asset_id: int) -> None:
    await ws_manager.broadcast("contact_sheet_review_changed", {"asset_id": asset_id})


@router.get("/{asset_id}/review")
async def read_review(asset_id: int, session: AsyncSession = Depends(get_db_session)):
    await _sheet(session, asset_id)
    return await get_review(session, asset_id)


@router.put("/{asset_id}/review/answers/{anchor}")
async def put_answer(asset_id: int, anchor: str, request: AnswerRequest,
                     session: AsyncSession = Depends(get_db_session)):
    await _sheet(session, asset_id)
    try:
        row = await set_answer(session, asset_id, anchor, request.value)
    except SheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await _changed(asset_id)
    return review_row_dict(row)


@router.post("/{asset_id}/review/comments")
async def post_comment(asset_id: int, request: CommentRequest,
                       session: AsyncSession = Depends(get_db_session)):
    await _sheet(session, asset_id)
    try:
        row = await add_comment(session, asset_id, request.anchor, request.text)
    except SheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await _changed(asset_id)
    return review_row_dict(row)


@router.delete("/{asset_id}/review/comments/{comment_id}")
async def delete_comment(asset_id: int, comment_id: int,
                         session: AsyncSession = Depends(get_db_session)):
    await _sheet(session, asset_id)
    row = await session.scalar(select(ContactSheetReview).where(
        ContactSheetReview.id == comment_id,
        ContactSheetReview.asset_id == asset_id,
        ContactSheetReview.kind == "comment",
        ContactSheetReview.deleted_at.is_(None),
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    row.deleted_at = datetime.utcnow()
    await session.commit()
    await _changed(asset_id)
    return {"deleted": True}


@router.post("/{asset_id}/review/send")
async def send_review(asset_id: int, request: SendRequest,
                      session: AsyncSession = Depends(get_db_session)):
    """Send everything the agent hasn't seen as one message in the chat.

    A running agent gets it at its next step; otherwise it is posted as an
    ordinary user message, which starts a turn.
    """
    asset = await _sheet(session, asset_id)
    if await session.get(Chat, request.chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    try:
        items, message = await take_pending_review(session, asset_id)
    except SheetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not items or not message:
        return {"sent": 0, "delivery": None}

    metadata = {"contact_sheet_review": {
        "asset_id": asset_id,
        "title": asset.title,
        "items": items,
    }}
    from agent.v2.service import add_steer

    if add_steer(request.chat_id, {
        "steer_id": f"sheet-review-{uuid.uuid4().hex[:12]}",
        "message_text": message,
        "item_metadata": metadata,
        "selected_media_ids": [],
    }):
        await session.commit()
        await _changed(asset_id)
        return {"sent": len(items), "delivery": "steer"}

    from routes.chats import ChatItemCreateRequest, create_chat_item

    await create_chat_item(
        request.chat_id,
        ChatItemCreateRequest(
            item_type="user_message",
            message_text=message,
            item_metadata=json.dumps(metadata),
        ),
        session,
    )
    await _changed(asset_id)
    return {"sent": len(items), "delivery": "message"}

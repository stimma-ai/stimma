"""Durable finalization for chats after the short Undo grace period."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import (
    Asset,
    Chat,
    ChatItem,
    GenerationJob,
    LLMTrace,
    MediaItem,
    MediaOwner,
)

log = get_logger(__name__)

CHAT_DELETE_GRACE_SECONDS = 5
FINALIZE_BATCH_SIZE = 50


@dataclass
class ChatFinalizationResult:
    finalized_chats: int = 0
    queued_media: int = 0


async def _finalize_one_chat(
    session: AsyncSession,
    *,
    chat_id: int,
    cutoff: datetime,
    profile_id: str,
) -> int:
    """Purge one due chat and queue its newly unowned Media atomically."""
    chat = await session.scalar(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.deleted_at.is_not(None),
            Chat.deleted_at <= cutoff,
        )
    )
    if chat is None:
        return 0

    candidate_media_ids = set(
        await session.scalars(
            select(MediaOwner.media_id).where(
                MediaOwner.root_kind == "chat",
                MediaOwner.root_id == str(chat_id),
                MediaOwner.deleted_at.is_(None),
            )
        )
    )
    chat_jobs = list(
        await session.scalars(
            select(GenerationJob).where(
                GenerationJob.output_context_kind == "chat",
                GenerationJob.output_context_id == str(chat_id),
            )
        )
    )
    candidate_media_ids.update(
        job.result_media_id for job in chat_jobs if job.result_media_id is not None
    )
    chat_item_ids = list(
        await session.scalars(
            select(ChatItem.id).where(ChatItem.chat_id == chat_id)
        )
    )

    # Remove every strong edge held by the chat before deciding which Media is
    # collectible. Other roots (Assets, containers, other chats, editors) win.
    await session.execute(
        delete(MediaOwner).where(
            MediaOwner.root_kind == "chat",
            MediaOwner.root_id == str(chat_id),
        )
    )

    if chat_item_ids:
        await session.execute(
            update(MediaItem)
            .where(MediaItem.chat_item_id.in_(chat_item_ids))
            .values(chat_item_id=None)
        )
        await session.execute(
            update(Chat)
            .where(Chat.original_chatitem_id.in_(chat_item_ids))
            .values(original_chatitem_id=None)
        )

    # LLM traces do not have ON DELETE CASCADE. Delete them explicitly, then
    # remove transcript rows and the chat identity under SQLite secure_delete.
    await session.execute(delete(LLMTrace).where(LLMTrace.chat_id == chat_id))
    await session.execute(
        delete(GenerationJob).where(
            GenerationJob.output_context_kind == "chat",
            GenerationJob.output_context_id == str(chat_id),
        )
    )
    await session.execute(
        update(Asset)
        .where(Asset.origin_type == "chat_final", Asset.origin_id == str(chat_id))
        .values(origin_id=None)
    )
    await session.execute(delete(ChatItem).where(ChatItem.chat_id == chat_id))
    await session.execute(delete(Chat).where(Chat.id == chat_id))
    await session.flush()

    collectible = []
    if candidate_media_ids:
        for media in await session.scalars(
            select(MediaItem).where(
                MediaItem.id.in_(candidate_media_ids),
                MediaItem.deletion_pending_at.is_(None),
            )
        ):
            surviving_owner = await session.scalar(
                select(MediaOwner.id).where(
                    MediaOwner.media_id == media.id,
                    MediaOwner.deleted_at.is_(None),
                ).limit(1)
            )
            if surviving_owner is None:
                collectible.append(media)

    # Even a chat with no collectible Media gets a zero-item operation. The
    # deletion worker uses it to truncate historical WAL frames before privacy
    # deletion is considered complete.
    from delete_operations import create_delete_operation

    await create_delete_operation(
        session,
        profile_id=profile_id,
        kind="chat",
        media_items=collectible,
    )
    return len(collectible)


async def finalize_due_chat_deletions(
    session: AsyncSession,
    *,
    profile_id: str,
    now: datetime | None = None,
    grace_seconds: int = CHAT_DELETE_GRACE_SECONDS,
) -> ChatFinalizationResult:
    """Finalize due chat tombstones; failures remain retryable next worker pass."""
    cutoff = (now or datetime.utcnow()) - timedelta(seconds=grace_seconds)
    due_ids = list(
        await session.scalars(
            select(Chat.id)
            .where(Chat.deleted_at.is_not(None), Chat.deleted_at <= cutoff)
            .order_by(Chat.deleted_at, Chat.id)
            .limit(FINALIZE_BATCH_SIZE)
        )
    )
    result = ChatFinalizationResult()
    for chat_id in due_ids:
        try:
            queued = await _finalize_one_chat(
                session,
                chat_id=chat_id,
                cutoff=cutoff,
                profile_id=profile_id,
            )
        except Exception:
            await session.rollback()
            log.exception("Failed to finalize deleted chat", chat_id=chat_id)
            continue
        result.finalized_chats += 1
        result.queued_media += queued
    return result

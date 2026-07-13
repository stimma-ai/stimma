"""Chat Undo finalization and ownership-aware Media collection."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from asset_service import acquire_media_owner, create_asset_from_media
from chat_deletion_service import finalize_due_chat_deletions
from database import (
    Asset,
    Chat,
    ChatItem,
    DeleteOperation,
    GenerationJob,
    LLMTrace,
    MediaItem,
    MediaOwner,
)
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_due_chat_is_purged_and_last_owned_media_is_queued(db_session):
    now = datetime.utcnow()
    async with db_session() as session:
        chat = Chat(name="Delete me", deleted_at=now - timedelta(seconds=10))
        other_chat = Chat(name="Fork")
        session.add_all([chat, other_chat])
        await session.flush()
        item = ChatItem(
            chat_id=chat.id,
            item_type="assistant_message",
            message_text="private transcript",
        )
        session.add(item)
        await session.flush()
        other_chat.original_chatitem_id = item.id
        media = await create_media_item(session)
        media.chat_item_id = item.id
        await acquire_media_owner(
            session,
            media_id=media.id,
            root_kind="chat",
            root_id=chat.id,
            role="intermediate",
        )
        session.add(
            LLMTrace(
                chat_id=chat.id,
                trace_type="planner",
                messages='[{"role":"user","content":"private"}]',
            )
        )
        chat_id = chat.id
        item_id = item.id
        media_id = media.id
        other_chat_id = other_chat.id
        await session.commit()

        result = await finalize_due_chat_deletions(
            session,
            profile_id="default",
            now=now,
            grace_seconds=5,
        )

        assert result.finalized_chats == 1
        assert result.queued_media == 1
        assert await session.get(Chat, chat_id) is None
        assert await session.get(ChatItem, item_id) is None
        assert await session.scalar(
            select(LLMTrace.id).where(LLMTrace.chat_id == chat_id)
        ) is None
        assert await session.scalar(
            select(MediaOwner.id).where(
                MediaOwner.root_kind == "chat",
                MediaOwner.root_id == str(chat_id),
            )
        ) is None
        queued_media = await session.get(MediaItem, media_id)
        assert queued_media.deletion_pending_at is not None
        surviving_chat = await session.get(Chat, other_chat_id)
        assert surviving_chat.original_chatitem_id is None
        operation = await session.scalar(
            select(DeleteOperation)
            .where(DeleteOperation.kind == "chat")
            .order_by(DeleteOperation.id.desc())
        )
        assert operation is not None
        assert operation.total_items == 1


@pytest.mark.asyncio
async def test_due_chat_does_not_collect_media_retained_by_asset(db_session):
    now = datetime.utcnow()
    async with db_session() as session:
        chat = Chat(name="Delete me", deleted_at=now - timedelta(seconds=10))
        session.add(chat)
        await session.flush()
        media = await create_media_item(session)
        asset = await create_asset_from_media(
            session,
            media_id=media.id,
            origin_type="chat_final",
            origin_id=str(chat.id),
        )
        await acquire_media_owner(
            session,
            media_id=media.id,
            root_kind="chat",
            root_id=chat.id,
            role="intermediate",
        )
        job = GenerationJob(
            status="completed",
            task_type="text-to-image",
            generator_type="test",
            generator_name="test",
            model_name="test",
            parameters='{"prompt":"private raccoon"}',
            folder_path="/tmp",
            result_media_id=media.id,
            output_disposition="context",
            output_context_kind="chat",
            output_context_id=str(chat.id),
        )
        session.add(job)
        chat_id = chat.id
        media_id = media.id
        asset_id = asset.id
        await session.flush()
        job_id = job.id
        await session.commit()

        result = await finalize_due_chat_deletions(
            session,
            profile_id="default",
            now=now,
            grace_seconds=5,
        )

        assert result.finalized_chats == 1
        assert result.queued_media == 0
        assert await session.get(Chat, chat_id) is None
        retained = await session.get(MediaItem, media_id)
        assert retained.deletion_pending_at is None
        assert await session.get(GenerationJob, job_id) is None
        surviving_asset = await session.get(Asset, asset_id)
        assert surviving_asset.origin_id is None
        operation = await session.scalar(
            select(DeleteOperation)
            .where(DeleteOperation.kind == "chat")
            .order_by(DeleteOperation.id.desc())
        )
        assert operation is not None
        assert operation.total_items == 0


@pytest.mark.asyncio
async def test_chat_remains_restorable_during_grace_period(db_session):
    now = datetime.utcnow()
    async with db_session() as session:
        chat = Chat(name="Undo me", deleted_at=now)
        session.add(chat)
        await session.commit()
        chat_id = chat.id

        result = await finalize_due_chat_deletions(
            session,
            profile_id="default",
            now=now + timedelta(seconds=4),
            grace_seconds=5,
        )

        assert result.finalized_chats == 0
        assert await session.get(Chat, chat_id) is not None

        chat = await session.get(Chat, chat_id)
        chat.deleted_at = None
        await session.commit()
        result = await finalize_due_chat_deletions(
            session,
            profile_id="default",
            now=now + timedelta(seconds=10),
            grace_seconds=5,
        )
        assert result.finalized_chats == 0
        assert await session.get(Chat, chat_id) is not None

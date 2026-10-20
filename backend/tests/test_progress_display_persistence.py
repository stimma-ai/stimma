"""Progress batches survive reloads and server restarts.

A chat's progress_display item must carry completed previews in the DB (not
only in WebSocket broadcasts), and a batch whose run died with the server must
stop reporting itself as in progress.
"""

import json

import pytest
from sqlalchemy import select

from agent.v2.code_runtime import ProgressTracker, StimmaSDK
from database import Chat, ChatItem


async def _make_chat(db_session) -> int:
    async with db_session() as session:
        chat = Chat(name="Progress persistence chat")
        session.add(chat)
        await session.commit()
        return chat.id


async def _display_data(db_session, item_id: int) -> dict:
    async with db_session() as session:
        item = (await session.execute(select(ChatItem).where(ChatItem.id == item_id))).scalar_one()
        return json.loads(item.item_metadata)["display_data"]


@pytest.mark.asyncio
async def test_flushed_progress_is_persisted(db_session):
    chat_id = await _make_chat(db_session)
    sdk = object.__new__(StimmaSDK)
    sdk.chat_id = chat_id
    sdk._progress_trackers = []
    tracker = ProgressTracker(total=4, desc="Generating", _chat_id=chat_id, _sdk=sdk)

    await sdk._flush_progress()
    tracker.update(1, preview=101)
    tracker.update(1, preview=102)
    await sdk._flush_progress()

    data = await _display_data(db_session, tracker._item_id)
    assert data["status"] == "in_progress"
    assert data["current"] == 2
    assert data["previews"] == [101, 102]


@pytest.mark.asyncio
async def test_plan_status_interrupts_stale_progress(client, db_session):
    chat_id = await _make_chat(db_session)
    async with db_session() as session:
        stale = ChatItem(chat_id=chat_id, item_type="progress_display", item_metadata=json.dumps({
            "display_data": {
                "title": "Generating", "status": "in_progress", "current": 2, "total": 4,
                "previews": [101, 102],
                "preview_slots": [
                    {"media_ids": [101], "status": "completed"},
                    {"media_ids": [102], "status": "completed"},
                    {"media_ids": [], "status": "pending"},
                    {"media_ids": [], "status": "pending"},
                ],
            },
        }))
        done = ChatItem(chat_id=chat_id, item_type="progress_display", item_metadata=json.dumps({
            "display_data": {"title": "Done", "status": "completed", "current": 1, "total": 1, "previews": [7]},
        }))
        session.add_all([stale, done])
        await session.commit()
        stale_id, done_id = stale.id, done.id

    response = await client.get(f"/api/chats/{chat_id}/plan-status")
    assert response.status_code == 200
    assert response.json()["is_stale"] is True

    stale_data = await _display_data(db_session, stale_id)
    assert stale_data["status"] == "interrupted"
    assert stale_data["previews"] == [101, 102]
    assert (await _display_data(db_session, done_id))["status"] == "completed"

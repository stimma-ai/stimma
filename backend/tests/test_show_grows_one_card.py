"""Code that keeps generating shows its results as they land, in one card."""

import json

import pytest
from sqlalchemy import select

from agent.v2.code_runtime import StimmaSDK
from database import Chat, ChatItem
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_shows_with_one_title_grow_one_card_while_code_runs(db_session, tmp_path):
    async with db_session() as session:
        chat = Chat(name="Stream")
        session.add(chat)
        media = [await create_media_item(session) for _ in range(4)]
        await session.commit()
        chat_id, ids = chat.id, [m.id for m in media]

    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        sdk.show(ids[0], role="intermediate", title="Noir portraits")
        await sdk._flush_display_live()  # what the run loop does every half second
        sdk.show(ids[1:3], role="intermediate", title="Noir portraits")
        sdk.show(ids[3], role="intermediate", title="Something else")
        await sdk._flush_display_live()

    async with db_session() as session:
        cards = (await session.execute(
            select(ChatItem).where(ChatItem.chat_id == chat_id, ChatItem.item_type == "media_display")
            .order_by(ChatItem.id)
        )).scalars().all()
    assert [json.loads(c.media_ids) if c.media_ids else [c.media_id] for c in cards] == [ids[:3], [ids[3]]]
    first = json.loads(cards[0].item_metadata)["display_data"]
    assert first["title"] == "Noir portraits" and len(first["rows"]) == 3

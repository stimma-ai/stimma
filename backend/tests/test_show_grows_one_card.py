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


@pytest.mark.asyncio
async def test_a_show_never_grows_another_chats_card(db_session, tmp_path):
    from agent.v2.tools.show import show

    async with db_session() as session:
        mine, other = Chat(name="Mine"), Chat(name="Other")
        session.add_all([mine, other])
        media = [await create_media_item(session) for _ in range(2)]
        await session.commit()
        foreign = ChatItem(chat_id=other.id, item_type="media_display", show_role="intermediate",
                           media_id=media[0].id, item_metadata=json.dumps({"display_data": {"rows": []}}))
        session.add(foreign)
        await session.commit()
        mine_id, foreign_id = mine.id, foreign.id

        await show(role="intermediate", media_ids=[media[1].id], title="T", session=session,
                   chat_id=mine_id, workspace_dir=str(tmp_path), _append_to_item=foreign_id)

    async with db_session() as session:
        untouched = await session.get(ChatItem, foreign_id)
        assert untouched.media_ids is None and untouched.chat_id != mine_id
        cards = (await session.execute(select(ChatItem).where(
            ChatItem.chat_id == mine_id, ChatItem.item_type == "media_display"))).scalars().all()
        assert len(cards) == 1


@pytest.mark.asyncio
async def test_a_shown_workspace_file_does_not_hold_back_later_results(db_session, tmp_path):
    from PIL import Image

    Image.new("RGB", (8, 8), "red").save(tmp_path / "crop.png")
    async with db_session() as session:
        chat = Chat(name="Paths")
        session.add(chat)
        media = await create_media_item(session)
        await session.commit()
        chat_id, media_id = chat.id, media.id

    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        sdk._session_media_ids.append(media_id)  # the file is an edit of it: lineage is looked up
        sdk.show("crop.png", role="intermediate", title="Crops")
        sdk.show(media_id, role="intermediate", title="Generated")
        await sdk._flush_display_live()
        assert not sdk._pending_display_calls

    async with db_session() as session:
        cards = (await session.execute(select(ChatItem).where(
            ChatItem.chat_id == chat_id, ChatItem.item_type == "media_display").order_by(ChatItem.id))).scalars().all()
    titles = [json.loads(c.item_metadata)["display_data"]["title"] for c in cards]
    assert titles == ["Crops", "Generated"]


@pytest.mark.asyncio
async def test_a_show_that_fails_does_not_stop_the_ones_after_it(db_session, tmp_path):
    async with db_session() as session:
        chat = Chat(name="Bad file")
        session.add(chat)
        media = await create_media_item(session)
        await session.commit()
        chat_id, media_id = chat.id, media.id

    printed = []
    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        sdk._stdout_print = printed.append

        async def broken(paths, session=None):
            if paths:
                raise OSError("unreadable")
            return []

        sdk._auto_save_paths = broken
        sdk.show("missing.png", role="intermediate", title="Broken")
        sdk.show(media_id, role="intermediate", title="Fine")
        await sdk._flush_display_live()

    async with db_session() as session:
        cards = (await session.execute(select(ChatItem).where(
            ChatItem.chat_id == chat_id, ChatItem.item_type == "media_display"))).scalars().all()
    assert [json.loads(c.item_metadata)["display_data"]["title"] for c in cards] == ["Fine"]
    assert any("[show]" in line and "unreadable" in line for line in printed)

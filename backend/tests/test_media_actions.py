"""The user's actions on a chat's media reach the agent's next message."""
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from database import Chat, ChatItem, MediaAction
from media_actions import (
    ADDED_TO_COLLECTION,
    EXPORTED,
    MARKED,
    RESTORED,
    TRASHED,
    UNMARKED,
    describe_media_actions_since,
    record_media_action,
    record_media_actions,
)
from tests.helpers.media import create_media_item

FAVORITE = {"marker_id": 1, "marker_name": "Favorite"}
KEEPERS = {"collection_id": 9, "collection_name": "Keepers"}


async def _chat_with_assets(session, count):
    """A chat that displayed ``count`` saved media. Returns (chat, media, asset ids)."""
    from asset_association_service import asset_for_media

    chat = Chat(name="Shots", created_at=datetime.utcnow() - timedelta(hours=1))
    session.add(chat)
    await session.flush()
    media = [await create_media_item(session, materialize_asset=True) for _ in range(count)]
    for m in media:
        session.add(ChatItem(chat_id=chat.id, item_type="assistant_message", media_id=m.id))
    await session.commit()
    assets = [(await asset_for_media(session, m.id)).id for m in media]
    return chat, media, assets


async def _at(session, when, action, **kwargs):
    await record_media_action(session, action, **kwargs)
    await session.flush()
    row = (await session.scalars(select(MediaAction).order_by(MediaAction.id.desc()).limit(1))).one()
    row.created_at = when
    await session.commit()


@pytest.mark.asyncio
async def test_only_net_changes_are_told_and_identical_ones_grouped(db_session):
    async with db_session() as s:
        chat, media, assets = await _chat_with_assets(s, 4)
        a, b, c, d = assets
        since = datetime.utcnow()
        t = since + timedelta(seconds=1)
        await _at(s, t, MARKED, asset_id=a, detail=FAVORITE)
        await _at(s, t, UNMARKED, asset_id=a, detail=FAVORITE)  # cancels
        await _at(s, t, TRASHED, asset_id=b)
        await _at(s, t, RESTORED, asset_id=b)  # cancels
        await _at(s, t, MARKED, media_id=media[2].id, asset_id=c, detail=FAVORITE)
        await _at(s, t, TRASHED, asset_id=c)
        await _at(s, t, TRASHED, asset_id=d)
        await _at(s, t, EXPORTED, asset_id=d)
        await _at(s, t, EXPORTED, asset_id=d)  # once is enough
        await _at(s, t, ADDED_TO_COLLECTION, asset_id=a, detail=KEEPERS)

        note = await describe_media_actions_since(s, chat.id, since, t + timedelta(seconds=1))

    assert note == (
        "[Since the previous message, the user acted on media from this chat: "
        f'media {media[2].id}: marked "Favorite"; '
        f"media {media[2].id}, {media[3].id}: moved to trash; "
        f"media {media[3].id}: exported; "
        f'media {media[0].id}: added to collection "Keepers".]'
    )


@pytest.mark.asyncio
async def test_nothing_left_is_none(db_session):
    async with db_session() as s:
        chat, _, (a,) = await _chat_with_assets(s, 1)
        since = datetime.utcnow()
        t = since + timedelta(seconds=1)
        await _at(s, t, TRASHED, asset_id=a)
        await _at(s, t, RESTORED, asset_id=a)
        assert await describe_media_actions_since(s, chat.id, since, t) is None


@pytest.mark.asyncio
async def test_only_this_chats_media_counts_including_later_revisions(db_session):
    from asset_service import commit_revision

    async with db_session() as s:
        chat, media, (a,) = await _chat_with_assets(s, 1)
        # The user edited it elsewhere: a newer revision the chat never saw.
        newer = await create_media_item(s)
        await commit_revision(s, asset_id=a, media_id=newer.id)
        # Media from some other chat.
        _, other_media, (other,) = await _chat_with_assets(s, 1)
        since = datetime.utcnow()
        t = since + timedelta(seconds=1)
        await _at(s, t, MARKED, media_id=newer.id, asset_id=a, detail=FAVORITE)
        await _at(s, t, TRASHED, media_id=other_media[0].id, asset_id=other)

        note = await describe_media_actions_since(s, chat.id, since, t)

    # Named by the media id the chat knows, not the newer revision's.
    assert note == (
        "[Since the previous message, the user acted on media from this chat: "
        f'media {media[0].id}: marked "Favorite".]'
    )


@pytest.mark.asyncio
async def test_window_is_after_since_through_until(db_session):
    async with db_session() as s:
        chat, media, assets = await _chat_with_assets(s, 4)
        since = datetime.utcnow()
        until = since + timedelta(seconds=10)
        await _at(s, since, EXPORTED, asset_id=assets[0])  # at since: already told
        await _at(s, since + timedelta(seconds=1), EXPORTED, asset_id=assets[1])
        await _at(s, until, EXPORTED, asset_id=assets[2])
        await _at(s, until + timedelta(seconds=1), EXPORTED, asset_id=assets[3])  # next time

        note = await describe_media_actions_since(s, chat.id, since, until)
    assert note == (
        "[Since the previous message, the user acted on media from this chat: "
        f"media {media[1].id}, {media[2].id}: exported.]"
    )


@pytest.mark.asyncio
async def test_batch_record_fills_in_media_and_asset(db_session):
    async with db_session() as s:
        _, media, assets = await _chat_with_assets(s, 2)
        await record_media_actions(s, EXPORTED, [(media[0].id, None), (None, assets[1])])
        await s.commit()
        rows = (await s.scalars(
            select(MediaAction).order_by(MediaAction.id.desc()).limit(2)
        )).all()
    assert {(r.media_id, r.asset_id) for r in rows} == {
        (media[0].id, assets[0]), (media[1].id, assets[1]),
    }


@pytest.mark.asyncio
async def test_marking_through_the_app_reaches_the_next_message(client, db_session, monkeypatch):
    from agent.v2.conversation import _item_to_message

    monkeypatch.setattr("routes.chats._run_agent_background", AsyncMock())
    monkeypatch.setattr("routes.chats.auto_name_chat", AsyncMock())
    favorite = {m["name"]: m["id"] for m in (await client.get("/api/markers")).json()}["favorite"]
    async with db_session() as s:
        chat, media, _ = await _chat_with_assets(s, 1)
        s.add(ChatItem(chat_id=chat.id, item_type="user_message", message_text="Make one.",
                       created_at=datetime.utcnow() - timedelta(minutes=1)))
        await s.commit()

    response = await client.post(f"/api/media/{media[0].id}/markers/{favorite}")
    assert response.status_code == 200
    # Marking again changes nothing, so it isn't recorded twice.
    await client.post(f"/api/media/{media[0].id}/markers/{favorite}")

    response = await client.post(f"/api/chats/{chat.id}/items", json={
        "item_type": "user_message", "message_text": "Do more like that one.",
    })
    assert response.status_code == 200
    async with db_session() as s:
        item = await s.get(ChatItem, response.json()["id"])
        note = json.loads(item.item_metadata)["media_actions"]
        assert note == (
            "[Since the previous message, the user acted on media from this chat: "
            f'media {media[0].id}: marked "favorite".]'
        )
        assert _item_to_message(item)["content"] == f"Do more like that one.\n\n{note}"

        # The message after that starts a new window.
        later = await client.post(f"/api/chats/{chat.id}/items", json={
            "item_type": "user_message", "message_text": "And again.",
        })
        later_item = await s.get(ChatItem, later.json()["id"])
        assert "media_actions" not in json.loads(later_item.item_metadata or "{}")


@pytest.mark.asyncio
async def test_names_are_one_short_quoted_line(db_session):
    async with db_session() as s:
        chat, media, (a,) = await _chat_with_assets(s, 1)
        since = datetime.utcnow()
        t = since + timedelta(seconds=1)
        name = 'Keep\nthis "one"]\x07' + "x" * 80
        await _at(s, t, MARKED, asset_id=a, detail={"marker_id": 5, "marker_name": name})
        note = await describe_media_actions_since(s, chat.id, since, t)
    phrase = note.split(": marked ", 1)[1].removesuffix(".]")
    assert "\n" not in note and "\x07" not in note
    assert phrase.startswith('"Keep this \\"one\\"] xxx') and phrase.endswith('…"')
    assert len(json.loads(phrase)) == 60


@pytest.mark.asyncio
async def test_exports_name_the_media_exported_and_each_save_as_new_shows(db_session):
    from asset_service import commit_revision
    from media_actions import EDITED

    async with db_session() as s:
        chat, media, (a,) = await _chat_with_assets(s, 1)
        newer = await create_media_item(s)
        await commit_revision(s, asset_id=a, media_id=newer.id)
        since = datetime.utcnow()
        t = since + timedelta(seconds=1)
        await _at(s, t, EXPORTED, media_id=newer.id, asset_id=a)
        await _at(s, t, EDITED, media_id=media[0].id, asset_id=a,
                  detail={"result_media_id": 501, "save_as_new": True})
        await _at(s, t, EDITED, media_id=media[0].id, asset_id=a,
                  detail={"result_media_id": 502, "save_as_new": True})
        note = await describe_media_actions_since(s, chat.id, since, t)
    assert note == (
        "[Since the previous message, the user acted on media from this chat: "
        f"media {newer.id}: exported; "
        f"media {media[0].id}: edited and saved as new media 501; "
        f"media {media[0].id}: edited and saved as new media 502.]"
    )


@pytest.mark.asyncio
async def test_moving_between_sections_is_not_membership(client, db_session):
    async with db_session() as s:
        chat, media, _ = await _chat_with_assets(s, 1)
    since = datetime.utcnow()
    collection = (await client.post("/api/collections", json={"name": "Keepers"})).json()
    cid = collection["id"]
    default_section = collection["sections"][0]["id"]
    other = (await client.post(f"/api/collections/{cid}/sections", json={"name": "B"})).json()["id"]
    for section in (default_section, other):
        r = await client.post(f"/api/collections/{cid}/items",
                              json={"media_ids": [media[0].id], "section_id": section})
        assert r.status_code == 200
    # Out of one section, still in the other: still in the collection.
    r = await client.delete(f"/api/collections/sections/{other}/items/{media[0].id}")
    assert r.status_code == 200
    async with db_session() as s:
        note = await describe_media_actions_since(s, chat.id, since, datetime.utcnow())
    assert note == (
        "[Since the previous message, the user acted on media from this chat: "
        f'media {media[0].id}: added to collection "Keepers".]'
    )


@pytest.mark.asyncio
async def test_a_steer_note_ends_when_the_steer_was_sent(db_session, monkeypatch):
    from agent.v2 import service
    from tests.helpers.ws import MockWebSocketManager

    async with db_session() as s:
        chat, media, (a, b) = await _chat_with_assets(s, 2)
        now = datetime.utcnow()
        await _at(s, now - timedelta(seconds=20), EXPORTED, asset_id=a)
        key = service._chat_key(chat.id)
        service._active_chat_executions.add(key)
        try:
            assert service.add_steer(chat.id, {"steer_id": "s1", "message_text": "warmer"})
            service._pending_steers[key][0]["accepted_at"] = now - timedelta(seconds=10)
            # After the steer was sent, before the loop delivers it.
            later = now - timedelta(seconds=5)
            await _at(s, later, TRASHED, asset_id=b)
            assert await service._deliver_steers(chat, s, MockWebSocketManager())
        finally:
            service._active_chat_executions.discard(key)
            service._drop_pending_steers(chat.id)
        steer = (await s.scalars(select(ChatItem).where(
            ChatItem.chat_id == chat.id, ChatItem.item_type == "user_message"))).one()
        assert json.loads(steer.item_metadata)["media_actions"] == (
            "[Since the previous message, the user acted on media from this chat: "
            f"media {media[0].id}: exported.]"
        )
        from media_actions import note_for_next_message
        following = await note_for_next_message(s, chat.id, chat.created_at, later + timedelta(seconds=1))
    assert following == (
        "[Since the previous message, the user acted on media from this chat: "
        f"media {media[1].id}: moved to trash.]"
    )


@pytest.mark.asyncio
async def test_a_late_steer_does_not_move_the_window_back(db_session):
    """A message sent while a steer waited ends a later window than the steer's."""
    from media_actions import WINDOW_END_KEY, note_for_next_message

    async with db_session() as s:
        chat, media, (a,) = await _chat_with_assets(s, 1)
        now = datetime.utcnow()
        await _at(s, now - timedelta(seconds=20), EXPORTED, asset_id=a)
        # A plain message at -10s already told the export; the steer accepted
        # at -30s is delivered afterwards with its earlier cutoff.
        s.add(ChatItem(chat_id=chat.id, item_type="user_message", created_at=now - timedelta(seconds=10)))
        s.add(ChatItem(
            chat_id=chat.id, item_type="user_message", created_at=now - timedelta(seconds=5),
            item_metadata=json.dumps({WINDOW_END_KEY: (now - timedelta(seconds=30)).isoformat()}),
        ))
        await s.commit()
        assert await note_for_next_message(s, chat.id, chat.created_at, now) is None

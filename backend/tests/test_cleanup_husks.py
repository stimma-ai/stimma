"""Tests for the empty/unnamed collection/flow/chat reaper.

CleanupService.cleanup_empty_unnamed_entities hard-evaporates the useless husks
a misclick or an abandoned start leaves behind, but must never touch an object
the user gave identity or content to. These tests pin down both halves.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from cleanup_service import CleanupService
from database import (
    Collection,
    CollectionSection,
    CollectionAssetItem,
    CollectionItem,
    Chat,
    ChatItem,
    Flow,
    LLMTrace,
)
from flow_runtime.directory import (
    create_flow_directory,
    get_empty_flow_program,
    is_empty_flow_program,
)
from flow_runtime.paths import get_flow_program_path
from core.profile_context import ProfileScope
import flow_registry
from asset_service import create_asset_from_media
from tests.helpers.media import create_test_media

OLD = datetime.utcnow() - timedelta(hours=13)
RECENT = datetime.utcnow() - timedelta(hours=1)


async def _add_collection(session, *, name, created_at, with_asset=False):
    collection = Collection(name=name, created_at=created_at, updated_at=created_at)
    session.add(collection)
    await session.flush()
    section = CollectionSection(collection_id=collection.id, is_default=True)
    session.add(section)
    await session.flush()
    if with_asset:
        media = (await create_test_media(session, count=1, materialize_assets=False))[0]
        asset = await create_asset_from_media(session, media_id=media.id)
        session.add(CollectionAssetItem(collection_section_id=section.id, asset_id=asset.id))
    await session.flush()
    return collection


async def _add_flow(session, *, name, created_at, program=None, with_message=False):
    flow = Flow(name=name, created_at=created_at, updated_at=created_at)
    session.add(flow)
    await session.flush()
    create_flow_directory(flow.id)
    if program is not None:
        get_flow_program_path(flow.id).write_text(program)
    if with_message:
        chat = Chat(name="Untitled", flow_id=flow.id,
                    created_at=created_at, updated_at=created_at)
        session.add(chat)
        await session.flush()
        session.add(ChatItem(chat_id=chat.id, item_type="user_message",
                             message_text="hi"))
    await session.flush()
    return flow


async def _add_chat(session, *, name, created_at, flow_id=None, with_message=False):
    chat = Chat(name=name, flow_id=flow_id,
                created_at=created_at, updated_at=created_at)
    session.add(chat)
    await session.flush()
    if with_message:
        session.add(ChatItem(chat_id=chat.id, item_type="user_message",
                             message_text="hello"))
    await session.flush()
    return chat


class TestReapEmptyHusks:
    async def test_reaps_only_abandoned_husks(self, db_session):
        async with db_session() as session:
            # --- reapable: unnamed + empty + old ---
            husk_collection = await _add_collection(session, name="", created_at=OLD)
            husk_flow = await _add_flow(session, name="", created_at=OLD)
            husk_chat = await _add_chat(session, name="", created_at=OLD)
            husk_chat_untitled = await _add_chat(session, name="Untitled 4", created_at=OLD)

            # --- must survive ---
            named_collection = await _add_collection(session, name="Keepers", created_at=OLD)
            content_collection = await _add_collection(session, name="", created_at=OLD, with_asset=True)
            recent_collection = await _add_collection(session, name="", created_at=RECENT)

            named_flow = await _add_flow(session, name="My Flow", created_at=OLD)
            edited_flow = await _add_flow(
                session, name="", created_at=OLD,
                program=get_empty_flow_program() + "\nx = image('cat')\n",
            )
            chatted_flow = await _add_flow(session, name="", created_at=OLD, with_message=True)
            recent_flow = await _add_flow(session, name="", created_at=RECENT)

            named_chat = await _add_chat(session, name="Design ideas", created_at=OLD)
            msg_chat = await _add_chat(session, name="Untitled", created_at=OLD, with_message=True)
            recent_chat = await _add_chat(session, name="", created_at=RECENT)
            await session.commit()

            ids = {
                "husk_collection": husk_collection.id, "husk_flow": husk_flow.id,
                "husk_chat": husk_chat.id, "husk_chat_untitled": husk_chat_untitled.id,
                "named_collection": named_collection.id, "content_collection": content_collection.id,
                "recent_collection": recent_collection.id, "named_flow": named_flow.id,
                "edited_flow": edited_flow.id, "chatted_flow": chatted_flow.id,
                "recent_flow": recent_flow.id, "named_chat": named_chat.id,
                "msg_chat": msg_chat.id, "recent_chat": recent_chat.id,
            }

            reaped = await CleanupService().cleanup_empty_unnamed_entities(session)

        assert set(reaped["collections"]) == {ids["husk_collection"]}
        assert set(reaped["flows"]) == {ids["husk_flow"]}
        assert set(reaped["chats"]) == {ids["husk_chat"], ids["husk_chat_untitled"]}

        async with db_session() as session:
            live_collections = set(await session.scalars(
                select(Collection.id).where(Collection.deleted_at.is_(None))))
            live_flows = set(await session.scalars(
                select(Flow.id).where(Flow.deleted_at.is_(None))))
            live_chats = set(await session.scalars(
                select(Chat.id).where(Chat.deleted_at.is_(None))))

        # Husks gone (collections/flows hard-deleted, chat soft-deleted).
        assert ids["husk_collection"] not in live_collections
        assert await _row_gone(db_session, Collection, ids["husk_collection"])
        assert ids["husk_flow"] not in live_flows
        assert await _row_gone(db_session, Flow, ids["husk_flow"])
        assert ids["husk_chat"] not in live_chats
        assert ids["husk_chat_untitled"] not in live_chats

        # Everything with identity or content survives.
        for key in ("named_collection", "content_collection", "recent_collection"):
            assert ids[key] in live_collections
        for key in ("named_flow", "edited_flow", "chatted_flow", "recent_flow"):
            assert ids[key] in live_flows
        for key in ("named_chat", "msg_chat", "recent_chat"):
            assert ids[key] in live_chats

    async def test_collection_with_any_item_row_survives(self, db_session):
        """Fail-closed emptiness: a blank collection is spared if it holds *any* item
        row — legacy CollectionItem, an asset in a soft-deleted section, or a
        soft-deleted CollectionAssetItem — so a permanent delete never destroys
        restorable curation."""
        async with db_session() as session:
            media = await create_test_media(session, count=3, materialize_assets=False)

            # (a) legacy CollectionItem-only membership
            legacy = Collection(name="", created_at=OLD, updated_at=OLD)
            session.add(legacy)
            await session.flush()
            legacy_sec = CollectionSection(collection_id=legacy.id, is_default=True)
            session.add(legacy_sec)
            await session.flush()
            session.add(CollectionItem(collection_section_id=legacy_sec.id, media_id=media[0].id))

            # (b) asset living only in a SOFT-DELETED section
            soft_sec_collection = Collection(name="", created_at=OLD, updated_at=OLD)
            session.add(soft_sec_collection)
            await session.flush()
            dead_sec = CollectionSection(collection_id=soft_sec_collection.id, is_default=True,
                                    deleted_at=datetime.utcnow())
            session.add(dead_sec)
            await session.flush()
            asset_b = await create_asset_from_media(session, media_id=media[1].id)
            session.add(CollectionAssetItem(collection_section_id=dead_sec.id, asset_id=asset_b.id))

            # (c) an item that was added then removed (soft-deleted item row)
            removed_collection = Collection(name="", created_at=OLD, updated_at=OLD)
            session.add(removed_collection)
            await session.flush()
            rsec = CollectionSection(collection_id=removed_collection.id, is_default=True)
            session.add(rsec)
            await session.flush()
            asset_c = await create_asset_from_media(session, media_id=media[2].id)
            session.add(CollectionAssetItem(collection_section_id=rsec.id, asset_id=asset_c.id,
                                       deleted_at=datetime.utcnow()))
            await session.commit()
            ids = [legacy.id, soft_sec_collection.id, removed_collection.id]

            await CleanupService().cleanup_empty_unnamed_entities(session)

        async with db_session() as session:
            live = set(await session.scalars(
                select(Collection.id).where(Collection.deleted_at.is_(None))))
        for bid in ids:
            assert bid in live, f"collection {bid} was wrongly reaped"

    async def test_whitespace_name_is_reaped(self, db_session):
        """A whitespace-only name is not real identity — trim() → reapable."""
        async with db_session() as session:
            collection = await _add_collection(session, name="   ", created_at=OLD)
            await session.commit()
            bid = collection.id
            reaped = await CleanupService().cleanup_empty_unnamed_entities(session)
        assert bid in reaped["collections"]

    async def test_flow_with_traced_empty_chat_is_reaped_not_stuck(self, db_session):
        """An empty agent chat carrying an LLMTrace (NOT NULL, no cascade) must
        not wedge the flow reap on an FK error — the chat routes through the
        soft-delete pipeline, not a hand-rolled hard delete."""
        async with db_session() as session:
            flow = await _add_flow(session, name="", created_at=OLD)
            chat = Chat(name="Untitled", flow_id=flow.id, created_at=OLD, updated_at=OLD)
            session.add(chat)
            await session.flush()
            session.add(LLMTrace(chat_id=chat.id, trace_type="planner", messages="[]"))
            await session.commit()
            flow_id, chat_id = flow.id, chat.id

            reaped = await CleanupService().cleanup_empty_unnamed_entities(session)

        assert flow_id in reaped["flows"]
        async with db_session() as session:
            assert (await session.get(Flow, flow_id)) is None
            reaped_chat = await session.get(Chat, chat_id)
            assert reaped_chat is not None and reaped_chat.deleted_at is not None

    async def test_flow_ondisk_dir_removed(self, db_session):
        async with db_session() as session:
            flow = await _add_flow(session, name="", created_at=OLD)
            await session.commit()
            flow_id = flow.id

        assert get_flow_program_path(flow_id).exists()

        async with db_session() as session:
            await CleanupService().cleanup_empty_unnamed_entities(session)

        assert not get_flow_program_path(flow_id).parent.exists()

    async def test_reaping_same_id_is_isolated_by_profile(self, db_session):
        """A husk in profile B cannot touch profile A's dir or live runtime."""
        async with db_session() as session:
            flow = Flow(name="", created_at=OLD, updated_at=OLD)
            session.add(flow)
            await session.flush()
            flow_id = flow.id

            with ProfileScope("profile-a"):
                create_flow_directory(flow_id)
                get_flow_program_path(flow_id).write_text("# profile A's live flow\n")

            with ProfileScope("profile-b"):
                create_flow_directory(flow_id)
                assert is_empty_flow_program(get_flow_program_path(flow_id).read_text())
            await session.commit()

        class RuntimeStub:
            stopped = False

            async def stop(self):
                self.stopped = True

        runtime_a = RuntimeStub()
        flow_registry.reset()
        try:
            with ProfileScope("profile-a"):
                flow_registry.register(flow_id, runtime_a)

            with ProfileScope("profile-b"):
                async with db_session() as session:
                    reaped = await CleanupService().cleanup_empty_unnamed_entities(session)

            assert flow_id in reaped["flows"]
            with ProfileScope("profile-b"):
                assert not get_flow_program_path(flow_id).parent.exists()
                assert flow_registry.get_runtime(flow_id) is None
            with ProfileScope("profile-a"):
                assert get_flow_program_path(flow_id).read_text() == "# profile A's live flow\n"
                assert flow_registry.get_runtime(flow_id) is runtime_a
            assert runtime_a.stopped is False
        finally:
            flow_registry.reset()


async def _row_gone(db_session, model, row_id) -> bool:
    async with db_session() as session:
        return (await session.get(model, row_id)) is None

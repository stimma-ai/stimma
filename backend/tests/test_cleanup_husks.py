"""Tests for the empty/unnamed board/flow/chat reaper.

CleanupService.cleanup_empty_unnamed_entities hard-evaporates the useless husks
a misclick or an abandoned start leaves behind, but must never touch an object
the user gave identity or content to. These tests pin down both halves.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from cleanup_service import CleanupService
from database import (
    Board,
    BoardSection,
    BoardAssetItem,
    BoardItem,
    Chat,
    ChatItem,
    Flow,
    LLMTrace,
)
from flow_runtime.directory import create_flow_directory, get_empty_flow_program
from flow_runtime.paths import get_flow_program_path
from asset_service import create_asset_from_media
from tests.helpers.media import create_test_media

OLD = datetime.utcnow() - timedelta(hours=13)
RECENT = datetime.utcnow() - timedelta(hours=1)


async def _add_board(session, *, name, created_at, with_asset=False):
    board = Board(name=name, created_at=created_at, updated_at=created_at)
    session.add(board)
    await session.flush()
    section = BoardSection(board_id=board.id, is_default=True)
    session.add(section)
    await session.flush()
    if with_asset:
        media = (await create_test_media(session, count=1, materialize_assets=False))[0]
        asset = await create_asset_from_media(session, media_id=media.id)
        session.add(BoardAssetItem(board_section_id=section.id, asset_id=asset.id))
    await session.flush()
    return board


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
            husk_board = await _add_board(session, name="", created_at=OLD)
            husk_flow = await _add_flow(session, name="", created_at=OLD)
            husk_chat = await _add_chat(session, name="", created_at=OLD)
            husk_chat_untitled = await _add_chat(session, name="Untitled 4", created_at=OLD)

            # --- must survive ---
            named_board = await _add_board(session, name="Keepers", created_at=OLD)
            content_board = await _add_board(session, name="", created_at=OLD, with_asset=True)
            recent_board = await _add_board(session, name="", created_at=RECENT)

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
                "husk_board": husk_board.id, "husk_flow": husk_flow.id,
                "husk_chat": husk_chat.id, "husk_chat_untitled": husk_chat_untitled.id,
                "named_board": named_board.id, "content_board": content_board.id,
                "recent_board": recent_board.id, "named_flow": named_flow.id,
                "edited_flow": edited_flow.id, "chatted_flow": chatted_flow.id,
                "recent_flow": recent_flow.id, "named_chat": named_chat.id,
                "msg_chat": msg_chat.id, "recent_chat": recent_chat.id,
            }

            reaped = await CleanupService().cleanup_empty_unnamed_entities(session)

        assert set(reaped["boards"]) == {ids["husk_board"]}
        assert set(reaped["flows"]) == {ids["husk_flow"]}
        assert set(reaped["chats"]) == {ids["husk_chat"], ids["husk_chat_untitled"]}

        async with db_session() as session:
            live_boards = set(await session.scalars(
                select(Board.id).where(Board.deleted_at.is_(None))))
            live_flows = set(await session.scalars(
                select(Flow.id).where(Flow.deleted_at.is_(None))))
            live_chats = set(await session.scalars(
                select(Chat.id).where(Chat.deleted_at.is_(None))))

        # Husks gone (boards/flows hard-deleted, chat soft-deleted).
        assert ids["husk_board"] not in live_boards
        assert await _row_gone(db_session, Board, ids["husk_board"])
        assert ids["husk_flow"] not in live_flows
        assert await _row_gone(db_session, Flow, ids["husk_flow"])
        assert ids["husk_chat"] not in live_chats
        assert ids["husk_chat_untitled"] not in live_chats

        # Everything with identity or content survives.
        for key in ("named_board", "content_board", "recent_board"):
            assert ids[key] in live_boards
        for key in ("named_flow", "edited_flow", "chatted_flow", "recent_flow"):
            assert ids[key] in live_flows
        for key in ("named_chat", "msg_chat", "recent_chat"):
            assert ids[key] in live_chats

    async def test_board_with_any_item_row_survives(self, db_session):
        """Fail-closed emptiness: a blank board is spared if it holds *any* item
        row — legacy BoardItem, an asset in a soft-deleted section, or a
        soft-deleted BoardAssetItem — so a permanent delete never destroys
        restorable curation."""
        async with db_session() as session:
            media = await create_test_media(session, count=3, materialize_assets=False)

            # (a) legacy BoardItem-only membership
            legacy = Board(name="", created_at=OLD, updated_at=OLD)
            session.add(legacy)
            await session.flush()
            legacy_sec = BoardSection(board_id=legacy.id, is_default=True)
            session.add(legacy_sec)
            await session.flush()
            session.add(BoardItem(board_section_id=legacy_sec.id, media_id=media[0].id))

            # (b) asset living only in a SOFT-DELETED section
            soft_sec_board = Board(name="", created_at=OLD, updated_at=OLD)
            session.add(soft_sec_board)
            await session.flush()
            dead_sec = BoardSection(board_id=soft_sec_board.id, is_default=True,
                                    deleted_at=datetime.utcnow())
            session.add(dead_sec)
            await session.flush()
            asset_b = await create_asset_from_media(session, media_id=media[1].id)
            session.add(BoardAssetItem(board_section_id=dead_sec.id, asset_id=asset_b.id))

            # (c) an item that was added then removed (soft-deleted item row)
            removed_board = Board(name="", created_at=OLD, updated_at=OLD)
            session.add(removed_board)
            await session.flush()
            rsec = BoardSection(board_id=removed_board.id, is_default=True)
            session.add(rsec)
            await session.flush()
            asset_c = await create_asset_from_media(session, media_id=media[2].id)
            session.add(BoardAssetItem(board_section_id=rsec.id, asset_id=asset_c.id,
                                       deleted_at=datetime.utcnow()))
            await session.commit()
            ids = [legacy.id, soft_sec_board.id, removed_board.id]

            await CleanupService().cleanup_empty_unnamed_entities(session)

        async with db_session() as session:
            live = set(await session.scalars(
                select(Board.id).where(Board.deleted_at.is_(None))))
        for bid in ids:
            assert bid in live, f"board {bid} was wrongly reaped"

    async def test_whitespace_name_is_reaped(self, db_session):
        """A whitespace-only name is not real identity — trim() → reapable."""
        async with db_session() as session:
            board = await _add_board(session, name="   ", created_at=OLD)
            await session.commit()
            bid = board.id
            reaped = await CleanupService().cleanup_empty_unnamed_entities(session)
        assert bid in reaped["boards"]

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


async def _row_gone(db_session, model, row_id) -> bool:
    async with db_session() as session:
        return (await session.get(model, row_id)) is None

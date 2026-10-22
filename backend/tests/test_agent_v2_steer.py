"""Steering: a message sent mid-run is delivered at the loop's next step."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agent.v2 import service
from database import Chat, ChatItem
from llm import LLMResponse
from tests.helpers.ws import MockWebSocketManager


def _stub_loop(monkeypatch, tmp_path, completion):
    monkeypatch.setattr(service, 'get_workspace_dir', lambda *args: tmp_path)
    monkeypatch.setattr(service, 'get_project_workspace', lambda *args: None)
    monkeypatch.setattr(service, 'resolve_agent_config', AsyncMock(return_value=SimpleNamespace(
        additional_instructions='', global_memory='', project_memory='',
    )))
    monkeypatch.setattr(service, '_raise_if_interrupted', lambda *args: None)
    monkeypatch.setattr(service, 'get_chat_llm_config', AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
    build = AsyncMock(return_value=([{'role': 'user', 'content': 'Make four hero shots.'}], 10))
    monkeypatch.setattr(service, 'build_messages', build)
    monkeypatch.setattr(service, 'llm_completion', completion)
    return build


@pytest.mark.asyncio
async def test_steer_sent_during_final_step_reopens_the_turn(db_session, tmp_path, monkeypatch):
    async with db_session() as session:
        chat = Chat(name='Café rebrand')
        session.add(chat)
        await session.commit()
        key = service._chat_key(chat.id)
        service._active_chat_executions.add(key)
        try:
            async def reply(*args, **kwargs):
                if completion.await_count == 1:
                    # The user steers while the model is producing what would
                    # otherwise be its closing message.
                    assert service.add_steer(chat.id, {
                        'steer_id': 'steer-1',
                        'message_text': 'square, not 16:9',
                        'item_metadata': {'attachments': [{'media_id': 7}]},
                        'selected_media_ids': [],
                    })
                    return LLMResponse(content='Here are the four options.')
                return LLMResponse(content='Regenerated them square.')

            completion = AsyncMock(side_effect=reply)
            build = _stub_loop(monkeypatch, tmp_path, completion)
            ws = MockWebSocketManager()
            await service._run_agentic_loop_inner(chat, session, ws, max_turns=5)

            assert completion.await_count == 2
            steers = (await session.execute(select(ChatItem).where(
                ChatItem.chat_id == chat.id, ChatItem.item_type == 'user_message',
            ))).scalars().all()
            assert [s.message_text for s in steers] == ['square, not 16:9']
            metadata = json.loads(steers[0].item_metadata)
            assert metadata['steer_id'] == 'steer-1'
            assert metadata['attachments'] == [{'media_id': 7}]
            assert any(
                data['item']['id'] == steers[0].id
                for _, data in ws.get_broadcasts('chat_item_created')
            )
            # Only the step after the steer carries the steer reminder.
            first, second = build.await_args_list
            assert service.STEER_REMINDER not in first.kwargs['system_reminders']
            assert service.STEER_REMINDER in second.kwargs['system_reminders']
            assert not service._has_pending_steers(chat.id)
        finally:
            service._active_chat_executions.discard(key)
            service._drop_pending_steers(chat.id)


def test_steer_is_refused_when_nothing_is_running():
    assert service.add_steer(987654, {'steer_id': 'x', 'message_text': 'hi'}) is False
    assert not service._has_pending_steers(987654)


def test_a_resent_steer_is_held_once():
    key = service._chat_key(987655)
    service._active_chat_executions.add(key)
    try:
        assert service.add_steer(987655, {'steer_id': 'q-1', 'message_text': 'warmer'})
        assert service.add_steer(987655, {'steer_id': 'q-1', 'message_text': 'warmer'})
        assert service.add_steer(987655, {'steer_id': 'q-2', 'message_text': 'square'})
        assert [s['steer_id'] for s in service._pending_steers[key]] == ['q-1', 'q-2']
    finally:
        service._active_chat_executions.discard(key)
        service._drop_pending_steers(987655)


@pytest.mark.asyncio
async def test_interrupt_drops_pending_steers(db_session):
    async with db_session() as session:
        chat = Chat(name='Stopped')
        session.add(chat)
        await session.commit()
        key = service._chat_key(chat.id)
        service._active_chat_executions.add(key)
        assert service.add_steer(chat.id, {'steer_id': 's', 'message_text': 'wait'})
        ws = MockWebSocketManager()
        await service.interrupt_execution(chat, session, ws)
        assert not service._has_pending_steers(chat.id)
        # No live task to unwind, so interrupt reports the stop itself.
        assert len(ws.get_broadcasts('agent_stopped')) == 1
        service._clear_interrupt(chat.id)


@pytest.mark.asyncio
async def test_steer_route_returns_409_when_idle(client, db_session):
    async with db_session() as session:
        chat = Chat(name='Idle')
        session.add(chat)
        await session.commit()
        chat_id = chat.id
    response = await client.post(f'/api/chats/{chat_id}/steer', json={
        'steer_id': 'abc', 'message_text': 'hello',
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_stop_orders_stragglers_then_marker_then_one_agent_stopped(db_session, monkeypatch):
    """The user's next message, sent once the UI sees agent_stopped, must land
    after the stop marker — so the marker has to be persisted before that
    broadcast, and after anything the dying run persists while unwinding."""
    import asyncio
    ws = MockWebSocketManager()

    async def long_step(*args, **kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await ws.broadcast('chat_item_created', {'chat_id': chat_id, 'item': {'id': -1, 'straggler': True}})
            raise

    monkeypatch.setattr(service, '_run_agentic_loop', long_step)
    async with db_session() as run_session, db_session() as stop_session:
        chat = Chat(name='Stopping')
        run_session.add(chat)
        await run_session.commit()
        chat_id = chat.id
        run = asyncio.create_task(service.run_agent(chat, 'go', run_session, ws))
        while not service.is_execution_active(chat_id):
            await asyncio.sleep(0)
        await asyncio.sleep(0)

        stop_chat = await stop_session.get(Chat, chat_id)
        await service.interrupt_execution(stop_chat, stop_session, ws, stop_marker=True)
        await run

        events = [
            'straggler' if d.get('item', {}).get('straggler')
            else 'marker' if e == 'chat_item_created' and (d['item'].get('item_metadata') or {}).get('stop_event')
            else e
            for e, d in ws.broadcasts
            if e in ('chat_item_created', 'agent_stopped')
        ]
        assert events == ['straggler', 'marker', 'agent_stopped']
        marker = (await stop_session.execute(select(ChatItem).where(
            ChatItem.chat_id == chat_id, ChatItem.item_type == 'user_message',
        ))).scalars().one()
        assert marker.message_text == service.STOP_MARKER_TEXT

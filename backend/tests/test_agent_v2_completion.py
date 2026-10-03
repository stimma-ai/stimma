"""Incomplete provider replies must leave a visible explanation in the chat."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agent.v2 import service
from database import Chat, ChatItem
from llm import LLMResponse, ToolCall
from tests.helpers.ws import MockWebSocketManager


@pytest.mark.asyncio
@pytest.mark.parametrize('replies, incomplete', [
    ([LLMResponse(), LLMResponse()], True),
    ([LLMResponse(), LLMResponse(content='All done.')], False),
    ([LLMResponse(tool_calls=[ToolCall(id='f1', name='finish', arguments='{}')]),
      LLMResponse(tool_calls=[ToolCall(id='f2', name='finish', arguments='{}')])], True),
])
async def test_empty_reply_retry_and_visible_pause(db_session, tmp_path, monkeypatch, replies, incomplete):
    async with db_session() as session:
        chat = Chat(name='Icon package')
        session.add(chat)
        await session.commit()
        monkeypatch.setattr(service, 'get_workspace_dir', lambda *args: tmp_path)
        monkeypatch.setattr(service, 'get_project_workspace', lambda *args: None)
        monkeypatch.setattr(service, 'resolve_agent_config', AsyncMock(return_value=SimpleNamespace(
            additional_instructions='', global_memory='', project_memory='',
        )))
        monkeypatch.setattr(service, '_raise_if_interrupted', lambda *args: None)
        monkeypatch.setattr(service, 'get_chat_llm_config', AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
        monkeypatch.setattr(service, 'build_messages', AsyncMock(return_value=([{'role': 'user', 'content': 'Continue packaging.'}], 10)))
        completion = AsyncMock(side_effect=replies)
        monkeypatch.setattr(service, 'llm_completion', completion)
        ws = MockWebSocketManager()
        await service._run_agentic_loop_inner(chat, session, ws, max_turns=5)
        assert completion.await_count == 2
        items = (await session.execute(select(ChatItem).where(
            ChatItem.chat_id == chat.id, ChatItem.item_type == 'assistant_message',
        ))).scalars().all()
        assert len(items) == 1
        if incomplete:
            assert 'paused' in items[0].message_text
            assert 'incomplete_response' in items[0].item_metadata
            ws.assert_broadcast('chat_item_created', {'chat_id': chat.id})
        else:
            assert items[0].message_text == 'All done.'

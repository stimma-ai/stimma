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


@pytest.mark.parametrize('window,expected', [(32768, 3276), (64000, 6400), (128000, 16384), (1000000, 16384)])
def test_agent_output_limit_is_separate_from_prompt_reserve(window, expected):
    from agent.v2.conversation import max_output_tokens, response_reserve
    assert max_output_tokens(window) == expected
    assert response_reserve(window) <= 8192


async def test_truncated_tool_batch_is_paired_and_never_executed(db_session, tmp_path, monkeypatch):
    from agent.v2.conversation import build_messages
    from llm import FinishReason
    import json

    async with db_session() as session:
        chat = Chat(name='Small steps')
        session.add(chat)
        await session.commit()
        session.add(ChatItem(chat_id=chat.id, item_type='user_message', message_text='Make a file.'))
        await session.commit()
        monkeypatch.setattr(service, 'get_workspace_dir', lambda *args: tmp_path)
        monkeypatch.setattr(service, 'get_project_workspace', lambda *args: None)
        monkeypatch.setattr(service, 'resolve_agent_config', AsyncMock(return_value=SimpleNamespace(
            additional_instructions='', global_memory='', project_memory='',
        )))
        monkeypatch.setattr(service, '_raise_if_interrupted', lambda *args: None)
        monkeypatch.setattr(service, 'get_chat_llm_config', AsyncMock(return_value=SimpleNamespace(max_context_tokens=128000)))
        permission = AsyncMock(return_value=False)
        execute = AsyncMock()
        monkeypatch.setattr(service, '_needs_permission', permission)
        monkeypatch.setattr(service, '_execute_tool_call', execute)
        completion = AsyncMock(side_effect=[
            LLMResponse(finish_reason=FinishReason.LENGTH, tool_calls=[
                ToolCall(id='a', name='write_file', arguments='{"content":"unfinished'),
                ToolCall(id='b', name='ask_user', arguments='{}'),
                ToolCall(id='c', name='finish', arguments='{}'),
            ]),
            LLMResponse(content='I will use smaller steps.'),
        ])
        monkeypatch.setattr(service, 'llm_completion', completion)
        await service._run_agentic_loop_inner(chat, session, MockWebSocketManager(), max_turns=2)
        execute.assert_not_awaited()
        permission.assert_not_awaited()
        assert completion.await_count == 2
        assert completion.await_args_list[0].kwargs['max_tokens'] == 16384
        messages, _ = await build_messages(chat.id, session, 'Be helpful.')
        calls = [m for m in messages if m.get('tool_calls')]
        results = [m for m in messages if m['role'] == 'tool']
        assert [m['tool_call_id'] for m in results] == ['a', 'b', 'c']
        assert len(calls) == 3
        assert all('cut off at the output limit' in m['content'] and 'smaller steps' in m['content'] for m in results)
        assert json.loads(calls[0]['tool_calls'][0]['function']['arguments'])['_malformed_arguments']

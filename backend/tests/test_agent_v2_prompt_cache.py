"""Stable conversation prefixes and direct Anthropic caching controls."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agent.v2 import conversation, service
from agent.v2.conversation import build_messages, _estimate_tokens
from agent.v2.prompts import get_system_prompt
from agent.v2.tools.notepad import format_notepad_for_prompt, notepad
from database import Chat, ChatItem
from llm import LLMResponse, ToolCall
from llm_http import _to_anthropic_request, acompletion
from tests.helpers.ws import MockWebSocketManager


async def test_consecutive_steps_turns_and_reopened_chat_keep_exact_prefix(db_session, tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(conversation, 'datetime', Clock)
    async with db_session() as session:
        chat = Chat(name='Cached conversation')
        session.add(chat)
        await session.commit()
        user = ChatItem(chat_id=chat.id, item_type='user_message', message_text='Make a note.',
                        created_at=now.replace(tzinfo=None),
                        item_metadata=json.dumps({'workspace_refs': [{'path': 'notes.txt'}]}))
        session.add(user)
        await session.commit()
        chat_id = chat.id
        system = get_system_prompt()
        reminders = ['<system-reminder>\n' + format_notepad_for_prompt(str(tmp_path)) + '\n</system-reminder>']
        first, estimate = await build_messages(chat.id, session, system, system_reminders=reminders)
        assert estimate == _estimate_tokens(first)['total']
        original_timestamp = json.loads(user.item_metadata)['prompt_timestamp']
        assert now.astimezone().strftime('%Y-%m-%d') in original_timestamp
        assert json.loads(user.item_metadata)['workspace_refs'] == [{'path': 'notes.txt'}]
        state = {'kind': 'anthropic_message', 'content': [
            {'type': 'thinking', 'thinking': 'I will record a note.', 'signature': 'signed'},
            {'type': 'tool_use', 'id': 'a', 'name': 'note', 'input': {}},
        ]}
        session.add_all([
            ChatItem(chat_id=chat.id, item_type='tool_call', tool_call_id='a', tool_name='note', tool_args='{}',
                     item_metadata=json.dumps({'llm_provider_state': state})),
            ChatItem(chat_id=chat.id, item_type='tool_result', tool_call_id='a', tool_result='Recorded.'),
        ])
        await session.commit()
        now += timedelta(hours=2)
        await notepad(action='write_scratchpad', content='Recorded one note.', workspace_dir=str(tmp_path))
        reminders = ['<system-reminder>\n' + format_notepad_for_prompt(str(tmp_path)) + '\n</system-reminder>']
        assert get_system_prompt() == system
        second, _ = await build_messages(chat.id, session, system, system_reminders=reminders)
        assert len(first) < len(second) and second[:len(first)] == first
        assert second[-1]['name'] == '_stimma_context'
        assert 'Recorded one note.' in second[-1]['content']
        assert json.loads(user.item_metadata)['prompt_timestamp'] == original_timestamp
        assert (await build_messages(chat.id, session, system, system_reminders=reminders))[0] == second
        session.add_all([
            ChatItem(chat_id=chat.id, item_type='assistant_message', message_text='Done.'),
            ChatItem(chat_id=chat.id, item_type='user_message', message_text='Another note.',
                     created_at=(now + timedelta(days=1)).replace(tzinfo=None)),
        ])
        await session.commit()

    # A new session models a later run/server restart: all context comes from storage.
    async with db_session() as session:
        now += timedelta(days=1)
        third, _ = await build_messages(chat_id, session, get_system_prompt(), system_reminders=reminders)
        assert len(second) < len(third) and third[:len(second)] == second
        assert third[0] == second[0] == first[0]
        assert third[1]['content'].startswith(original_timestamp)
        assert now.astimezone().strftime('%Y-%m-%d') in third[-1]['content']
        bodies = [_to_anthropic_request('claude-opus-5-5', messages, {'cacheable': True}, direct=True)
                  for messages in (first, second, third)]
        assert bodies[0]['system'] == bodies[1]['system'] == bodies[2]['system']
        for earlier, later in zip(bodies, bodies[1:]):
            assert later['messages'][:len(earlier['messages'])] == earlier['messages']
        assert bodies[1]['messages'][2]['content'] == state['content']


async def test_agent_appends_notepad_changes_across_steps_and_runs(db_session, tmp_path, monkeypatch):
    async with db_session() as session:
        chat = Chat(name='Notepad changes')
        session.add(chat)
        await session.commit()
        session.add(ChatItem(chat_id=chat.id, item_type='user_message', message_text='Take notes.'))
        await session.commit()
        monkeypatch.setattr(service, 'get_workspace_dir', lambda *args: tmp_path)
        monkeypatch.setattr(service, 'get_project_workspace', lambda *args: None)
        monkeypatch.setattr(service, 'resolve_agent_config', AsyncMock(return_value=SimpleNamespace(
            additional_instructions='', global_memory='', project_memory='',
        )))
        monkeypatch.setattr(service, 'get_chat_llm_config', AsyncMock(return_value=SimpleNamespace(max_context_tokens=128000)))
        monkeypatch.setattr(service, '_raise_if_interrupted', lambda *args: None)
        monkeypatch.setattr(service, '_needs_permission', AsyncMock(return_value=False))
        requests = []

        async def complete(config, messages, **kwargs):
            requests.append(deepcopy(messages))
            if len(requests) == 1:
                return LLMResponse(tool_calls=[ToolCall(id='a', name='notepad', arguments='{}')])
            return LLMResponse(content='Done.')

        async def execute(*args, **kwargs):
            await notepad(action='write_scratchpad', content='Remember this note.', workspace_dir=str(tmp_path))
            session.add(ChatItem(chat_id=chat.id, item_type='tool_result', tool_call_id='a', tool_result='Recorded.'))
            await session.commit()

        monkeypatch.setattr(service, 'llm_completion', complete)
        monkeypatch.setattr(service, '_execute_tool_call', execute)
        await service._run_agentic_loop_inner(chat, session, MockWebSocketManager(), max_turns=2)
        assert 'Remember this note.' in requests[1][-1]['content']
        assert 'Remember this note.' not in requests[1][0]['content']
        assert requests[1][:len(requests[0])] == requests[0]
        session.add(ChatItem(chat_id=chat.id, item_type='user_message', message_text='Continue.'))
        await session.commit()
        await service._run_agentic_loop_inner(chat, session, MockWebSocketManager(), max_turns=1)
        assert requests[2][:len(requests[1])] == requests[1]
        assert requests[0][0] == requests[1][0] == requests[2][0]


def test_direct_cache_breakpoints_are_bounded_and_history_is_not_mutated():
    blocks = [{'type': 'text', 'text': str(n), 'cache_control': {'type': 'ephemeral'}} for n in range(6)]
    blocks.append({'type': 'tool_use', 'id': 'a', 'name': 'note', 'input': {'cache_control': 'tool data'}})
    original = deepcopy(blocks)
    body = _to_anthropic_request('claude-sonnet-5', [
        {'role': 'system', 'content': 'Stable instructions.'},
        {'role': 'assistant', '_stimma_provider_state': {'kind': 'anthropic_message', 'content': blocks}},
    ], {'cacheable': True}, direct=True)
    assert body['cache_control'] == {'type': 'ephemeral'}
    assert body['system'][-1]['cache_control'] == {'type': 'ephemeral'}
    assert sum('cache_control' in b for b in body['messages'][0]['content']) + 2 == 4
    assert body['messages'][0]['content'][-1]['input']['cache_control'] == 'tool data'
    assert blocks == original
    uncached = _to_anthropic_request('claude-sonnet-5', [{'role': 'system', 'content': 'Stable.'}], {})
    assert 'cache_control' not in json.dumps(uncached)


@pytest.mark.parametrize('model', ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1'])
@pytest.mark.parametrize('thinking', [None, {'type': 'adaptive'}, {'type': 'enabled', 'budget_tokens': 10000}, {'type': 'between_tools'}])
async def test_direct_thinking_binding_wire_contract(model, thinking, monkeypatch):
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'Done.'}], 'stop_reason': 'end_turn'})

    client = httpx.AsyncClient
    monkeypatch.setattr('llm_http.httpx.AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(respond)))
    extra = {'thinking': thinking} if thinking else {}
    await acompletion(model=model, messages=[{'role': 'system', 'content': 'Be helpful.'}],
                      provider_kind='anthropic', api_base='https://api.anthropic.com/v1', api_key='test',
                      extra_body=extra, cacheable=True, extra_headers={'Anthropic-Beta': 'existing-beta'})
    request = captured[0]
    body = json.loads(request.content)
    assert body['cache_control'] == {'type': 'ephemeral'}
    assert body['thinking'] == {'type': 'adaptive', 'block_binding': {'prefix_mismatch_behavior': 'drop_block'}}
    assert request.headers['anthropic-beta'] == 'existing-beta,thinking-binding-controls-2026-08-01'
    assert extra == ({'thinking': thinking} if thinking else {})


@pytest.mark.parametrize('model', ['claude-sonnet-5', 'claude-haiku-4-5-20251001'])
def test_other_anthropic_models_keep_their_thinking_options(model):
    thinking = {'type': 'enabled', 'budget_tokens': 10000}
    body = _to_anthropic_request(model, [], {'extra_body': {'thinking': thinking}})
    assert body['thinking'] == thinking
    assert 'block_binding' not in json.dumps(body)
    assert 'thinking' not in _to_anthropic_request(model, [], {'thinking': thinking})


async def test_cloud_request_keeps_its_own_cache_and_thinking_protocol(monkeypatch):
    captured = []
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Done.'}}]})
    client = httpx.AsyncClient
    monkeypatch.setattr('llm_http.httpx.AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(respond)))
    await acompletion(model='claude-opus-5-5', messages=[{'role': 'user', 'content': 'Hello'}],
                      api_base='https://cloud.example/v1', api_key='test', cacheable=True,
                      extra_body={'thinking': {'type': 'adaptive'}})
    body = json.loads(captured[0].content)
    assert body['thinking'] == {'type': 'adaptive'}
    assert 'cache_control' not in body
    assert 'anthropic-beta' not in captured[0].headers
    assert captured[0].headers['X-Stimma-Cacheable'] == 'true'


def test_reminder_updates_do_not_displace_current_user_turn_under_budget_pressure():
    messages = [{'role': 'system', 'content': 'Be helpful.'}]
    for turn in range(8):
        messages.extend([
            {'role': 'user', 'content': f'Request {turn}'},
            {'role': 'assistant', 'content': 'Earlier work. ' * 100},
        ])
    current = {'role': 'user', 'content': 'Finish the current request.'}
    messages.append(current)
    for update in range(7):
        messages.append(conversation._item_to_message(ChatItem(
            item_type='system_reminder', message_text=f'Note update {update}',
        )))
    boundaries = conversation._find_user_turn_boundaries(messages)
    trimmed = conversation._apply_token_budget(messages, budget=100)
    assert len(boundaries) == 9
    assert current in trimmed
    assert all(message in trimmed for message in messages[boundaries[-5]:])


@pytest.mark.parametrize('host', ['proxy.example', 'api.anthropic.com.proxy.example'])
async def test_anthropic_format_proxy_omits_direct_provider_cache_and_binding(host, monkeypatch):
    captured = []
    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': 'Done.'}]})
    client = httpx.AsyncClient
    monkeypatch.setattr('llm_http.httpx.AsyncClient', lambda **kw: client(**kw, transport=httpx.MockTransport(respond)))
    await acompletion(model='claude-opus-5-5', messages=[{'role': 'system', 'content': 'Be helpful.'}],
                      provider_kind='anthropic', api_base=f'https://{host}/v1', api_key='test',
                      cacheable=True, extra_body={'thinking': {'type': 'enabled', 'budget_tokens': 1024}},
                      extra_headers={'Anthropic-Beta': 'existing-beta'})
    body = json.loads(captured[0].content)
    assert 'cache_control' not in json.dumps(body)
    assert body['thinking'] == {'type': 'enabled', 'budget_tokens': 1024}
    assert captured[0].headers['anthropic-beta'] == 'existing-beta'

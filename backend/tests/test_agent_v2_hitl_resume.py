"""Answering permission and ask_user cards, and resuming the agent after."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent.hitl import HumanActionRequest, HumanActionRequired
from agent.v2 import service
from agent.v2.tools import delegate
from database import Chat, ChatItem
from llm import LLMResponse, ToolCall
from tests.helpers.ws import MockWebSocketManager


async def _items(session, chat_id, item_type):
    return (await session.scalars(select(ChatItem).where(
        ChatItem.chat_id == chat_id, ChatItem.item_type == item_type,
    ).order_by(ChatItem.id))).all()


async def _add_request(session, chat_id, action: dict) -> ChatItem:
    item = ChatItem(chat_id=chat_id, item_type="hitl_request", item_metadata=json.dumps(action))
    session.add(item)
    await session.commit()
    return item


@pytest.mark.asyncio
async def test_answer_resolves_the_card_it_names(db_session, monkeypatch):
    """A background permission card and a later question: each answer reaches its own."""
    from agent.v2 import tool_permission_gate
    from routes.chats import HITLResponseRequest, apply_human_response

    async with db_session() as session:
        chat = Chat(name="Two cards", generation_settings=json.dumps({
            "_v2_ask_pending": {"tool_call_id": "ask_1", "turn": 0, "remaining_tool_calls": []},
        }))
        session.add(chat)
        await session.commit()
        permission = await _add_request(session, chat.id, {
            "type": "v2_tool_permission", "tool_call_id": "gen",
            "v2_tool_args": {"tool_id": "test:gen", "_inprocess_request_id": "req-a"},
        })
        question = await _add_request(session, chat.id, {"type": "ask_user", "tool_call_id": "ask_1"})
        future = asyncio.get_event_loop().create_future()
        monkeypatch.setitem(tool_permission_gate._PENDING, "req-a", future)
        resume = AsyncMock()
        monkeypatch.setattr("agent.resume_agent_after_hitl", resume)
        monkeypatch.setattr("routes.chats.ws_manager", MockWebSocketManager())

        await apply_human_response(chat.id, HITLResponseRequest(
            approved=True, scope="once", request_item_id=permission.id,
        ), session, wait=True)
        assert future.result() == {"approved": True, "scope": "once"}
        resume.assert_not_awaited()

        await apply_human_response(chat.id, HITLResponseRequest(
            answer="Blue", request_item_id=question.id,
        ), session, wait=True)
        resume.assert_awaited_once()
        assert resume.await_args.kwargs["action_type"] == "ask_user"
        assert resume.await_args.kwargs["response_data"]["answer"] == "Blue"

        responses = await _items(session, chat.id, "hitl_response")
        assert [json.loads(r.item_metadata)["request_item_id"] for r in responses] == [permission.id, question.id]


@pytest.mark.asyncio
async def test_desktop_answer_is_recorded_then_resumes_in_background(db_session, monkeypatch):
    from routes import chats
    from routes.chats import HITLResponseRequest, submit_human_response

    async with db_session() as session:
        chat = Chat(name="Quick answer", generation_settings=json.dumps({
            "_v2_pending": {"tool_name": "bash", "tool_call_id": "sh", "fn_arguments": "{}"},
        }))
        session.add(chat)
        await session.commit()
        request = await _add_request(session, chat.id, {"type": "v2_tool_permission", "tool_call_id": "sh"})
        started = []

        async def background(*args):
            started.append(args)

        monkeypatch.setattr(chats, "_resume_after_hitl_background", background)
        inline = AsyncMock()
        monkeypatch.setattr("agent.resume_agent_after_hitl", inline)
        monkeypatch.setattr("routes.chats.ws_manager", MockWebSocketManager())

        body = HITLResponseRequest(approved=True, scope="once", request_item_id=request.id)
        assert await submit_human_response(chat.id, body, session) == {"success": True}
        inline.assert_not_awaited()
        responses = await _items(session, chat.id, "hitl_response")
        assert len(responses) == 1
        await asyncio.sleep(0)
        assert len(started) == 1 and started[0][2] == "v2_tool_permission"

        # A second click finds it answered instead of resuming twice.
        with pytest.raises(HTTPException) as error:
            await submit_human_response(chat.id, body, session)
        assert error.value.status_code == 400
        assert len(started) == 1


@pytest.mark.asyncio
async def test_resume_skips_saving_an_answer_already_recorded(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "get_workspace_dir", lambda *args: tmp_path)
    monkeypatch.setattr(service, "get_project_workspace", lambda *args: None)
    monkeypatch.setattr(service, "_run_agentic_loop", AsyncMock())
    async with db_session() as session:
        chat = Chat(name="Answered", generation_settings=json.dumps({
            "_v2_ask_pending": {"tool_call_id": "ask_1", "turn": 0, "remaining_tool_calls": []},
        }))
        session.add(chat)
        await session.commit()
        await service.resume_after_ask_user(
            chat, {"answer": "Yes"}, session, MockWebSocketManager(), response_persisted=True,
        )
        assert await _items(session, chat.id, "hitl_response") == []
        assert [r.tool_result for r in await _items(session, chat.id, "tool_result")] == ["Yes"]


def _delegate_pending(parent_item_id):
    return {
        "tool_name": "bash", "tool_call_id": "inner", "fn_arguments": '{"command": "ls"}',
        "turn": 0, "remaining_tool_calls": [],
        "delegate_state": {
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "t"}],
            "task": "List files", "max_turns": 3, "delegate_turn": 0,
            "parent_item_id": parent_item_id, "parent_turn": 0, "parent_remaining": [],
            "remaining_tools": [],
        },
    }


@pytest.mark.asyncio
async def test_resumed_delegate_answers_the_model_call_and_can_pause_again(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "get_workspace_dir", lambda *args: tmp_path)
    monkeypatch.setattr(service, "get_project_workspace", lambda *args: None)
    loop = AsyncMock()
    monkeypatch.setattr(service, "_run_agentic_loop", loop)
    async with db_session() as session:
        chat = Chat(name="Delegate")
        session.add(chat)
        await session.commit()
        parent = ChatItem(chat_id=chat.id, item_type="tool_call", tool_name="delegate", tool_call_id="call_delegate")
        session.add(parent)
        await session.commit()

        # Finishes: its summary answers the model's own call id.
        chat.generation_settings = json.dumps({"_v2_pending": _delegate_pending(parent.id)})
        await session.commit()
        monkeypatch.setattr(delegate, "_run_delegate_loop", AsyncMock(return_value=("Three files.", {})))
        await service.resume_after_hitl(chat, {"approved": True, "scope": "once"}, session, MockWebSocketManager())
        results = await _items(session, chat.id, "tool_result")
        assert [(r.tool_call_id, r.tool_result) for r in results] == [("call_delegate", "Three files.")]
        loop.assert_awaited_once()

        # Pauses again: that is a new card, not a failed turn.
        chat.generation_settings = json.dumps({"_v2_pending": _delegate_pending(parent.id)})
        await session.commit()
        action = HumanActionRequest(type="v2_tool_permission", prompt="Run it", node_id="inner")
        monkeypatch.setattr(delegate, "_run_delegate_loop", AsyncMock(side_effect=HumanActionRequired(action)))
        ws = MockWebSocketManager()
        await service.resume_after_hitl(chat, {"approved": True, "scope": "once"}, session, ws)
        assert await _items(session, chat.id, "error") == []
        assert all(b[1].get("reason") != "error" for b in ws.get_broadcasts("agent_stopped"))


def _delegate_fakes(monkeypatch, tools, replies=()):
    monkeypatch.setattr(delegate, "get_all_tools", lambda: tools)
    monkeypatch.setattr(delegate, "_get_delegate_tools_schema", lambda: [{"type": "function"}])
    monkeypatch.setattr(delegate, "get_chat_llm_config", AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
    sent, pending = [], list(replies)

    async def completion(config, messages, **kwargs):
        sent.append(json.loads(json.dumps(messages)))
        return pending.pop(0)

    monkeypatch.setattr(delegate, "llm_completion", completion)
    return sent


def _call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.mark.asyncio
async def test_delegate_runs_the_call_allowed_once_then_checks_the_next(db_session, tmp_path, monkeypatch):
    bash = SimpleNamespace(handler=AsyncMock(return_value="file.txt"))
    _delegate_fakes(monkeypatch, {"bash": bash})
    monkeypatch.setattr(delegate, "_delegate_needs_permission", AsyncMock(return_value=True))
    async with db_session() as session:
        chat = Chat(name="Allow once")
        session.add(chat)
        await session.commit()
        first, second = _call("c1", "bash", '{"command": "ls"}'), _call("c2", "bash", '{"command": "rm x"}')
        with pytest.raises(HumanActionRequired):
            await delegate._run_delegate_loop(
                task="Tidy", context=None, specialist=None, max_turns=3, session=session,
                chat_id=chat.id, workspace_dir=str(tmp_path), project_workspace_dir=None,
                interrupt_checker=lambda: False, parent_item_id=None,
                ws_manager=MockWebSocketManager(), chat=chat,
                resume_messages=[
                    {"role": "assistant", "content": None, "tool_calls": [_call("c0", "bash", '{"command": "ls')]},
                    {"role": "tool", "tool_call_id": "c0", "content": "Error"},
                    {"role": "assistant", "content": None, "tool_calls": [first, second]},
                ],
                resume_pending_tool=first, resume_remaining_tools=[second],
            )
        bash.handler.assert_awaited_once()
        pending = json.loads(chat.generation_settings)["_v2_pending"]
        assert pending["tool_call_id"] == "c2"
        # Torn arguments saved by an older build are sanitized on resume.
        saved = pending["delegate_state"]["messages"][0]["tool_calls"][0]["function"]["arguments"]
        assert json.loads(saved)["_malformed_arguments"]


@pytest.mark.asyncio
async def test_delegate_answers_unusable_arguments_and_loads_skills_into_its_history(db_session, tmp_path, monkeypatch):
    seen = []

    async def skill_handler(**kwargs):
        seen.append(set(kwargs["_loaded_skills"]))
        if kwargs["name"] in kwargs["_loaded_skills"]:
            return "already loaded"
        kwargs["_injected_messages"].append({"skill_name": "pack/brand", "content": "Brand rules: teal."})
        return "Loaded skill 'Brand'."

    sent = _delegate_fakes(monkeypatch, {"skill": SimpleNamespace(handler=skill_handler)}, [
        LLMResponse(tool_calls=[
            ToolCall(id="a", name="bash", arguments='{"command": "ls'),
            ToolCall(id="b", name="bash", arguments='["ls"]'),
            ToolCall(id="c", name="skill", arguments='{"name": "brand"}'),
        ]),
        LLMResponse(tool_calls=[ToolCall(id="d", name="skill", arguments='{"name": "brand"}')]),
        LLMResponse(content="Done."),
    ])
    needs_permission = AsyncMock(return_value=True)
    monkeypatch.setattr(delegate, "_delegate_needs_permission", needs_permission)
    async with db_session() as session:
        chat = Chat(name="Torn args")
        session.add(chat)
        await session.commit()
        result, _ = await delegate._run_delegate_loop(
            task="Brand it", context=None, specialist=None, max_turns=4, session=session,
            chat_id=chat.id, workspace_dir=str(tmp_path), project_workspace_dir=None,
            interrupt_checker=lambda: False, ws_manager=MockWebSocketManager(), chat=None,
        )
    assert result == "Done."
    messages = sent[1]
    results = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
    assert "not valid JSON" in results["a"] and "JSON object" in results["b"]
    assert messages[-1] == {"role": "user", "name": "_stimma_context", "content": "Brand rules: teal."}
    # The provider is never sent the torn arguments back.
    replayed = [m for m in messages if m.get("tool_calls")][0]["tool_calls"]
    assert json.loads(replayed[0]["function"]["arguments"])["_malformed_arguments"]
    assert seen == [set(), {"brand", "pack/brand"}]


@pytest.mark.asyncio
async def test_skill_invoke_checks_the_history_it_is_given(monkeypatch):
    from agent.v2.tools import skill

    assert "already loaded" in await skill.skill_tool(action="invoke", name="brand", _loaded_skills={"brand"})
    found = SimpleNamespace(skill=SimpleNamespace(qualified_name="pack/brand"))
    monkeypatch.setattr(skill, "load_skill", lambda name: found)
    assert "already loaded" in await skill.skill_tool(action="invoke", name="brand", _loaded_skills={"pack/brand"})


@pytest.mark.asyncio
async def test_unusable_tool_arguments_get_an_error_result_not_a_prompt(db_session, tmp_path, monkeypatch):
    async with db_session() as session:
        chat = Chat(name="Torn bash")
        session.add(chat)
        await session.commit()
        monkeypatch.setattr(service, "get_workspace_dir", lambda *args: tmp_path)
        monkeypatch.setattr(service, "get_project_workspace", lambda *args: None)
        monkeypatch.setattr(service, "resolve_agent_config", AsyncMock(return_value=SimpleNamespace(
            additional_instructions="", global_memory="", project_memory="",
        )))
        monkeypatch.setattr(service, "_raise_if_interrupted", lambda *args: None)
        monkeypatch.setattr(service, "get_chat_llm_config", AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
        monkeypatch.setattr(service, "build_messages", AsyncMock(return_value=([{"role": "user", "content": "Go."}], 10)))
        monkeypatch.setattr(service, "_needs_permission", AsyncMock(return_value=True))
        completion = AsyncMock(side_effect=[
            LLMResponse(tool_calls=[
                ToolCall(id="a", name="bash", arguments='{"command": "ls'),
                ToolCall(id="b", name="ask_user", arguments='"Which one?"'),
            ]),
            LLMResponse(content="Let me try that again."),
        ])
        monkeypatch.setattr(service, "llm_completion", completion)
        await service._run_agentic_loop_inner(chat, session, MockWebSocketManager(), max_turns=3)
        assert completion.await_count == 2
        assert await _items(session, chat.id, "hitl_request") == []
        results = {r.tool_call_id: r.tool_result for r in await _items(session, chat.id, "tool_result")}
        assert "not valid JSON" in results["a"] and "JSON object" in results["b"]


@pytest.mark.asyncio
async def test_resume_point_of_another_call_is_left_alone(db_session, monkeypatch):
    loop = AsyncMock()
    monkeypatch.setattr(service, "_run_agentic_loop", loop)
    async with db_session() as session:
        slot = {"tool_call_id": "ask_new", "turn": 0, "remaining_tool_calls": []}
        chat = Chat(name="Moved", generation_settings=json.dumps({"_v2_ask_pending": slot}))
        session.add(chat)
        await session.commit()
        await service.resume_after_ask_user(
            chat, {"answer": "Old"}, session, MockWebSocketManager(),
            response_persisted=True, expected_tool_call_id="ask_old",
        )
        loop.assert_not_awaited()
        assert await _items(session, chat.id, "tool_result") == []
        assert json.loads(chat.generation_settings)["_v2_ask_pending"] == slot


@pytest.mark.asyncio
async def test_an_old_gate_card_cannot_release_a_new_gate(monkeypatch):
    from agent.v2 import tool_permission_gate as gate

    async def ask(*args, **kwargs):
        return "ask"

    async def no_card(**kwargs):
        pass

    async def no_close(*args):
        pass

    monkeypatch.setattr(gate, "_configured_decision", ask)
    monkeypatch.setattr(gate, "_create_permission_card", no_card)
    monkeypatch.setattr(gate, "_close_permission_card", no_close)
    first = asyncio.create_task(gate.ensure_tool_permission(chat_id=41, tool_id="p:t", kwargs={}, run_cache={}))
    await asyncio.sleep(0.01)
    old_id = gate._live_request_id(41, "p:t")
    first.cancel()  # e.g. the run stopped; its card stays in history
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(gate.ensure_tool_permission(chat_id=41, tool_id="p:t", kwargs={}, run_cache={}))
    await asyncio.sleep(0.01)
    assert not gate.resolve_pending_permission(old_id, {"approved": True, "scope": "once"})
    assert not second.done()
    assert gate.resolve_pending_permission(gate._live_request_id(41, "p:t"), {"approved": True, "scope": "once"})
    await asyncio.wait_for(second, timeout=1)


@pytest.mark.asyncio
async def test_a_run_waits_for_the_chat_task_it_finds_then_claims_the_chat():
    release = asyncio.Event()

    async def running():
        await service.claim_chat_task(42)
        await release.wait()

    holder = asyncio.create_task(running())
    await asyncio.sleep(0)
    waiter = asyncio.create_task(service.claim_chat_task(42))
    await asyncio.sleep(0.01)
    assert not waiter.done()
    release.set()
    await asyncio.wait_for(waiter, timeout=1)
    assert service.get_active_task(42) is waiter
    await holder


@pytest.mark.asyncio
async def test_stop_while_the_card_is_saved_leaves_no_gate_to_join(monkeypatch):
    from agent.v2 import tool_permission_gate as gate

    async def ask(*args, **kwargs):
        return "ask"

    saving = asyncio.Event()
    closed = []

    async def slow_card(**kwargs):
        saving.set()
        await asyncio.sleep(10)

    async def close(session_maker, chat_id, request_id):
        closed.append(request_id)

    monkeypatch.setattr(gate, "_configured_decision", ask)
    monkeypatch.setattr(gate, "_create_permission_card", slow_card)
    monkeypatch.setattr(gate, "_close_permission_card", close)
    first = asyncio.create_task(gate.ensure_tool_permission(chat_id=43, tool_id="p:t", kwargs={}, run_cache={}))
    await saving.wait()
    old_id = gate._live_request_id(43, "p:t")
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert gate._live_request_id(43, "p:t") is None
    assert not gate.is_pending_permission(old_id)
    assert closed == [old_id]

"""A long run from one prompt must stay inside the context window, and stop if stuck."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from agent.v2 import service
from agent.v2.conversation import (
    MAX_ACTIVE_VIEW_IMAGES,
    RUN_KEEP_RECENT_RESULTS,
    _read_prior_correction,
    _trim_run_steps,
    build_messages,
    compute_history_budget,
)
from database import Chat, ChatItem
from llm import LLMResponse, ToolCall, Usage
from llm_http import _encode_responses_tool_call_id, _to_responses_request
from tests.helpers.ws import MockWebSocketManager

SYSTEM = "You are helpful."
WINDOW = 32_000


def _budget():
    return compute_history_budget(WINDOW, len(SYSTEM) // 4)


def _step(chat_id, n, *, name="bash", args=None, result_chars=3000):
    call_id = f"call-{n}"
    return [
        ChatItem(chat_id=chat_id, item_type="tool_call", tool_name=name, tool_call_id=call_id,
                 tool_args=json.dumps(args or {"command": f"step {n}"})),
        ChatItem(chat_id=chat_id, item_type="tool_result", tool_call_id=call_id,
                 tool_result=f"output {n} " + "x" * result_chars),
    ]


async def _new_chat(session, prompt="Build the whole catalog"):
    chat = Chat(name="Long run")
    session.add(chat)
    await session.commit()
    session.add(ChatItem(chat_id=chat.id, item_type="user_message", message_text=prompt))
    await session.commit()
    return chat


def _assert_pairs_valid(messages):
    pending = set()
    for message in messages:
        if message["role"] == "tool":
            assert message["tool_call_id"] in pending, "unclaimed tool result"
            pending.discard(message["tool_call_id"])
            continue
        assert not pending, f"unanswered tool calls: {pending}"
        if message["role"] == "assistant" and message.get("tool_calls"):
            pending = {call["id"] for call in message["tool_calls"]}
    assert not pending


def _serialized_size(messages):
    return sum(len(json.dumps(message)) for message in messages[1:]) // 4


@pytest.mark.asyncio
@pytest.mark.parametrize("args_chars, must_drop_steps, max_prefix_moves", [(0, False, 100), (3000, True, 200)])
async def test_single_prompt_run_stays_in_budget_for_hundreds_of_steps(
    db_session, args_chars, must_drop_steps, max_prefix_moves,
):
    # Big results compress, but big arguments (say, write_file) can only be dropped.
    async with db_session() as session:
        chat = await _new_chat(session)
        cut_moves = 0
        previous_prefix = None
        for n in range(400):
            args = {"command": f"step {n}", "content": "y" * args_chars}
            session.add_all(_step(chat.id, n, args=args))
            await session.commit()
            messages, estimate = await build_messages(chat.id, session, SYSTEM, max_context_tokens=WINDOW)

            assert estimate <= int(WINDOW * 0.8), f"step {n}: estimate {estimate} over the window limit"
            _assert_pairs_valid(messages)
            assert "Build the whole catalog" in messages[1]["content"]
            newest = [m for m in messages if m.get("role") == "tool"][-1]
            assert newest["content"].startswith(f"output {n} ")

            # Everything before the newest messages should usually stay put, or
            # every step would miss the provider's prompt cache.
            prefix = json.dumps(messages[2:6])
            if previous_prefix is not None and prefix != previous_prefix:
                cut_moves += 1
            previous_prefix = prefix

        # This small a window only holds a few of these steps, so some misses are inherent.
        assert cut_moves < max_prefix_moves, f"prefix moved on {cut_moves} of 400 steps"
        dropped = any("removed to fit the context window" in str(m.get("content")) for m in messages)
        assert dropped == must_drop_steps


@pytest.mark.asyncio
async def test_old_output_is_compressed_before_any_step_is_dropped(db_session):
    async with db_session() as session:
        chat = await _new_chat(session)
        n = 0
        while True:
            session.add_all(_step(chat.id, n))
            await session.commit()
            n += 1
            messages, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=WINDOW)
            results = (await session.execute(select(ChatItem).where(
                ChatItem.chat_id == chat.id, ChatItem.item_type == "tool_result",
            ).order_by(ChatItem.id))).scalars().all()
            if any(r.tool_result.startswith("[bash result:") for r in results):
                break
            assert n < 200, "pressure never compressed anything"

        # Every step is still there, the oldest as placeholders, the newest intact.
        assert not any("removed to fit" in str(m.get("content")) for m in messages)
        assert sum(1 for m in messages if m.get("role") == "tool") == n
        assert all(r.tool_result.startswith("output") for r in results[-RUN_KEEP_RECENT_RESULTS:])


@pytest.mark.asyncio
async def test_short_run_is_left_untouched(db_session):
    async with db_session() as session:
        chat = await _new_chat(session)
        for n in range(5):
            session.add_all(_step(chat.id, n))
        await session.commit()
        messages, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=WINDOW)
        assert sum(1 for m in messages if m["role"] == "tool") == 5
        assert all(m["content"].startswith("output") for m in messages if m["role"] == "tool")


@pytest.mark.asyncio
async def test_answers_and_loaded_skills_survive_pressure(db_session):
    async with db_session() as session:
        chat = await _new_chat(session)
        session.add_all(_step(chat.id, "ask", name="ask_user", args={"question": "Which palette?"}))
        session.add_all(_step(chat.id, "skill", name="skill", args={"name": "layouts"}))
        session.add(ChatItem(chat_id=chat.id, item_type="stimpack_injection", message_text="Layout rules"))
        session.add(ChatItem(chat_id=chat.id, item_type="user_message", message_text="Use the blue one"))
        for n in range(150):
            session.add_all(_step(chat.id, n, args={"content": "y" * 3000}))
        await session.commit()

        messages, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=WINDOW)

        text = json.dumps(messages)
        assert "Which palette?" in text
        assert "output ask " in text
        assert "output skill " in text or "skill result" not in text
        assert "Layout rules" in text
        assert "Use the blue one" in text
        assert "removed to fit the context window" in text
        _assert_pairs_valid(messages)


def test_trim_keeps_parallel_results_with_their_batch():
    calls = [{"id": cid, "type": "function", "function": {"name": "bash", "arguments": "{}"}} for cid in "ab"]
    step = [
        {"role": "assistant", "content": None, "tool_calls": calls},
        {"role": "tool", "tool_call_id": "a", "content": "x" * 3000},
        {"role": "tool", "tool_call_id": "b", "content": "x" * 3000},
    ]
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}, *(step * 6)]
    trimmed = _trim_run_steps(messages, budget=2000)
    assert len(trimmed) < len(messages)
    _assert_pairs_valid([m for m in trimmed if m.get("role")])


def test_context_tokens_does_not_double_count_cached_tokens():
    assert Usage(prompt_tokens=100, cache_read_input_tokens=900).context_tokens == 1000
    assert Usage(prompt_tokens=1000, cache_read_input_tokens=900, cached_tokens_in_prompt=True).context_tokens == 1000


def test_correction_ignores_cumulative_usage_from_older_chats():
    # Old items only carry loop-wide prompt_tokens, which would pin this at the clamp.
    old = ChatItem(item_type="assistant_message", item_metadata=json.dumps({
        "llm_usage": {"prompt_tokens": 500_000, "estimated_prompt_tokens": 10_000},
    }))
    assert _read_prior_correction([old]) == 1.0

    new = ChatItem(item_type="assistant_message", item_metadata=json.dumps({
        "llm_usage": {"prompt_tokens": 500_000, "context_tokens": 12_000, "estimated_prompt_tokens": 10_000},
    }))
    assert _read_prior_correction([old, new]) == pytest.approx(1.2)


def test_correction_learns_from_tool_only_turns():
    call = ChatItem(item_type="tool_call", item_metadata=json.dumps({
        "llm_call_size": {"context_tokens": 15_000, "estimated_prompt_tokens": 10_000},
    }))
    assert _read_prior_correction([call]) == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_compaction_stops_openai_continuing_from_its_stored_history(db_session):
    async with db_session() as session:
        chat = await _new_chat(session)
        for n in range(30):
            call_id = _encode_responses_tool_call_id("resp_1", f"call_{n}")
            step = _step(chat.id, n, args={"content": "y" * 3000})
            step[0].tool_call_id = step[1].tool_call_id = call_id
            session.add_all(step)
        await session.commit()

        short, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=500_000)
        assert _to_responses_request("m", short, {})["previous_response_id"] == "resp_1"

        compacted, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=WINDOW)
        body = _to_responses_request("m", compacted, {})
        assert "previous_response_id" not in body
        assert len(body["input"]) < 2 * 30 + 1


@pytest.mark.asyncio
async def test_replacing_one_message_with_the_notice_still_stops_openai_continuing(db_session):
    async with db_session() as session:
        chat = await _new_chat(session)
        session.add(ChatItem(chat_id=chat.id, item_type="assistant_message", message_text="z" * 100_000))
        step = _step(chat.id, 0)
        step[0].tool_call_id = step[1].tool_call_id = _encode_responses_tool_call_id("resp_1", "call_0")
        session.add_all(step)
        await session.commit()

        messages, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=WINDOW)
        assert "z" * 100 not in json.dumps(messages)
        assert "previous_response_id" not in _to_responses_request("m", messages, {})


@pytest.mark.asyncio
async def test_aging_out_an_image_stops_openai_continuing_from_its_stored_history(db_session):
    async with db_session() as session:
        chat = await _new_chat(session)

        async def view_image(n):
            call_id = _encode_responses_tool_call_id(f"resp_{n}", f"call_{n}")
            session.add(ChatItem(chat_id=chat.id, item_type="tool_call", tool_name="view_image",
                                 tool_call_id=call_id, tool_args="{}"))
            session.add(ChatItem(chat_id=chat.id, item_type="tool_result", tool_call_id=call_id,
                                 tool_result=json.dumps({"__view_image__": True, "path": "/tmp/none.png"})))
            await session.commit()
            messages, _ = await build_messages(chat.id, session, SYSTEM, max_context_tokens=500_000)
            return _to_responses_request("m", messages, {})

        for n in range(MAX_ACTIVE_VIEW_IMAGES):
            assert (await view_image(n))["previous_response_id"] == f"resp_{n}"
        assert "previous_response_id" not in await view_image(MAX_ACTIVE_VIEW_IMAGES)
        assert (await view_image(MAX_ACTIVE_VIEW_IMAGES + 1)).get("previous_response_id") is None


async def _run_loop(db_session, tmp_path, monkeypatch, replies, max_turns):
    async with db_session() as session:
        chat = Chat(name="Stuck")
        session.add(chat)
        await session.commit()
        monkeypatch.setattr(service, "get_workspace_dir", lambda *args: tmp_path)
        monkeypatch.setattr(service, "get_project_workspace", lambda *args: None)
        monkeypatch.setattr(service, "resolve_agent_config", AsyncMock(return_value=SimpleNamespace(
            additional_instructions="", global_memory="", project_memory="",
        )))
        monkeypatch.setattr(service, "_raise_if_interrupted", lambda *args: None)
        monkeypatch.setattr(service, "get_chat_llm_config", AsyncMock(return_value=SimpleNamespace(max_context_tokens=WINDOW)))
        build = AsyncMock(return_value=([{"role": "user", "content": "go"}], 10))
        monkeypatch.setattr(service, "build_messages", build)
        monkeypatch.setattr(service, "_execute_tool_call", AsyncMock())
        monkeypatch.setattr(service, "_needs_permission", AsyncMock(return_value=False))
        completion = AsyncMock(side_effect=replies)
        monkeypatch.setattr(service, "llm_completion", completion)
        await service._run_agentic_loop_inner(chat, session, MockWebSocketManager(), max_turns=max_turns)
        messages = (await session.execute(select(ChatItem).where(
            ChatItem.chat_id == chat.id, ChatItem.item_type == "assistant_message",
        ))).scalars().all()
        reminders = [call.kwargs["system_reminders"] for call in build.await_args_list]
        return completion.await_count, messages, reminders


def _call(n, name="bash", args='{"command": "ls"}'):
    return LLMResponse(tool_calls=[ToolCall(id=f"c{n}", name=name, arguments=args)])


@pytest.mark.asyncio
async def test_repeating_the_same_call_nudges_then_pauses(db_session, tmp_path, monkeypatch):
    replies = [_call(n) for n in range(service._REPEATED_CALL_STOP_AT + 5)]
    count, items, reminders = await _run_loop(db_session, tmp_path, monkeypatch, replies, max_turns=100)

    assert count == service._REPEATED_CALL_STOP_AT
    assert "repeated_calls_stopped" in items[-1].item_metadata
    assert "paused" in items[-1].message_text
    nudged = [i for i, r in enumerate(reminders) if any("same tool call" in text for text in r)]
    assert nudged == [service._REPEATED_CALL_NUDGE_AT]


@pytest.mark.asyncio
async def test_argument_key_order_does_not_hide_a_repeat(db_session, tmp_path, monkeypatch):
    replies = [
        _call(n, args='{"a": 1, "b": 2}' if n % 2 else '{"b": 2, "a": 1}')
        for n in range(service._REPEATED_CALL_STOP_AT + 5)
    ]
    count, items, _ = await _run_loop(db_session, tmp_path, monkeypatch, replies, max_turns=100)
    assert count == service._REPEATED_CALL_STOP_AT
    assert "repeated_calls_stopped" in items[-1].item_metadata


@pytest.mark.asyncio
async def test_varied_calls_run_to_the_turn_cap_with_a_clear_hand_off(db_session, tmp_path, monkeypatch):
    # Alternating is real work (edit, run, edit, run) as far as this check can tell.
    replies = [_call(n, args=json.dumps({"command": f"step {n % 2}"})) for n in range(40)]
    count, items, reminders = await _run_loop(db_session, tmp_path, monkeypatch, replies, max_turns=40)
    assert count == 40
    assert not any("same tool call" in text for r in reminders for text in r)
    assert "max_turns_reached" in items[-1].item_metadata
    assert "40 steps" in items[-1].message_text


def test_turn_cap_is_a_distant_backstop():
    assert service._max_turns_for_chat(Chat(name="Any")) == 1000

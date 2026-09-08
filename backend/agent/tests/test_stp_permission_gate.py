"""Tests for the in-run STP tool permission gate (generation spend gate)."""

import asyncio
import json

import pytest

from database import Chat, ChatItem
from agent.v2 import tool_permission_gate as gate
from agent.v2.permissions import get_stp_permission_decision
from agent.v2.tool_permission_gate import (
    ToolPermissionDenied,
    ensure_tool_permission,
    is_pending_permission,
    resolve_pending_permission,
)


class _FakeToolConfig:
    allowed_tools: list = []
    denied_tools: list = []
    v2_permissions: dict = {}


class _FakeAgentConfig:
    tool_config = _FakeToolConfig()


class _FakeSettings:
    def get_agent_for_profile(self, _profile_id):
        return _FakeAgentConfig()


@pytest.fixture(autouse=True)
def _empty_global(monkeypatch):
    # Neutralize global-profile config so tests exercise chat-level + ask default.
    monkeypatch.setattr("config.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("core.profile_context.get_current_profile", lambda: "default")


# --- resolver ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_allow_when_chat_allows():
    chat = Chat(agent_tool_config=json.dumps({"allowed_tools": ["p:tool"]}))
    assert await get_stp_permission_decision("p:tool", chat, None) == "allow"


@pytest.mark.asyncio
async def test_decision_deny_when_chat_denies():
    chat = Chat(agent_tool_config=json.dumps({"denied_tools": ["p:tool"]}))
    assert await get_stp_permission_decision("p:tool", chat, None) == "deny"


@pytest.mark.asyncio
async def test_decision_ask_when_unconfigured():
    chat = Chat(agent_tool_config=None)
    assert await get_stp_permission_decision("p:tool", chat, None) == "ask"


@pytest.mark.asyncio
async def test_decision_allow_for_empty_tool_id():
    chat = Chat(agent_tool_config=None)
    assert await get_stp_permission_decision("", chat, None) == "allow"


# --- gate: cache + non-blocking decisions -----------------------------------

@pytest.mark.asyncio
async def test_gate_run_cache_allows_without_lookup(monkeypatch):
    called = False

    async def _boom(*a, **k):
        nonlocal called
        called = True
        return "deny"

    monkeypatch.setattr(gate, "_configured_decision", _boom)
    await ensure_tool_permission(chat_id=1, tool_id="p:t", kwargs={}, run_cache={"p:t": True})
    assert called is False  # cache short-circuits the DB lookup


@pytest.mark.asyncio
async def test_gate_run_cache_denies(monkeypatch):
    with pytest.raises(ToolPermissionDenied):
        await ensure_tool_permission(chat_id=1, tool_id="p:t", kwargs={}, run_cache={"p:t": False})


@pytest.mark.asyncio
async def test_gate_allow_sets_cache(monkeypatch):
    async def _allow(*a, **k):
        return "allow"

    monkeypatch.setattr(gate, "_configured_decision", _allow)
    cache: dict = {}
    await ensure_tool_permission(chat_id=1, tool_id="p:t", kwargs={}, run_cache=cache)
    assert cache["p:t"] is True


@pytest.mark.asyncio
async def test_gate_deny_raises_and_caches(monkeypatch):
    async def _deny(*a, **k):
        return "deny"

    monkeypatch.setattr(gate, "_configured_decision", _deny)
    cache: dict = {}
    with pytest.raises(ToolPermissionDenied):
        await ensure_tool_permission(chat_id=1, tool_id="p:t", kwargs={}, run_cache=cache)
    assert cache["p:t"] is False


# --- gate: the blocking "ask" path (in-process future) ----------------------

@pytest.mark.asyncio
async def test_gate_ask_blocks_then_approves(monkeypatch):
    async def _ask(*a, **k):
        return "ask"

    cards: list = []

    async def _fake_card(**kw):
        cards.append(kw["request_id"])

    monkeypatch.setattr(gate, "_configured_decision", _ask)
    monkeypatch.setattr(gate, "_create_permission_card", _fake_card)

    cache: dict = {}
    task = asyncio.create_task(
        ensure_tool_permission(chat_id=7, tool_id="p:t", kwargs={}, run_cache=cache)
    )
    # Let the gate register + raise the card, then confirm it is parked.
    await asyncio.sleep(0.01)
    assert not task.done()
    assert cards == [gate._request_id(7, "p:t")]
    assert is_pending_permission(gate._request_id(7, "p:t"))

    # Resolve as approved → the parked task completes and caches allow.
    assert resolve_pending_permission(gate._request_id(7, "p:t"), {"approved": True, "scope": "once"})
    await asyncio.wait_for(task, timeout=1)
    assert cache["p:t"] is True
    assert not is_pending_permission(gate._request_id(7, "p:t"))  # registry cleaned up


@pytest.mark.asyncio
async def test_gate_ask_blocks_then_denies(monkeypatch):
    async def _ask(*a, **k):
        return "ask"

    async def _fake_card(**kw):
        pass

    monkeypatch.setattr(gate, "_configured_decision", _ask)
    monkeypatch.setattr(gate, "_create_permission_card", _fake_card)

    task = asyncio.create_task(
        ensure_tool_permission(chat_id=8, tool_id="p:t", kwargs={}, run_cache={})
    )
    await asyncio.sleep(0.01)
    resolve_pending_permission(gate._request_id(8, "p:t"), {"approved": False, "scope": "once"})
    with pytest.raises(ToolPermissionDenied):
        await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_gate_ask_dedups_concurrent_calls(monkeypatch):
    """A gather of N calls to the same unapproved tool raises ONE card; all resume together."""
    async def _ask(*a, **k):
        return "ask"

    cards: list = []

    async def _fake_card(**kw):
        cards.append(kw["request_id"])

    monkeypatch.setattr(gate, "_configured_decision", _ask)
    monkeypatch.setattr(gate, "_create_permission_card", _fake_card)

    cache: dict = {}
    tasks = [
        asyncio.create_task(
            ensure_tool_permission(chat_id=9, tool_id="p:t", kwargs={}, run_cache=cache)
        )
        for _ in range(5)
    ]
    await asyncio.sleep(0.01)
    assert len(cards) == 1  # deduped to a single card
    resolve_pending_permission(gate._request_id(9, "p:t"), {"approved": True, "scope": "chat"})
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
    assert cache["p:t"] is True


@pytest.mark.asyncio
async def test_gate_ask_interrupt_cleans_registry(monkeypatch):
    async def _ask(*a, **k):
        return "ask"

    async def _fake_card(**kw):
        pass

    monkeypatch.setattr(gate, "_configured_decision", _ask)
    monkeypatch.setattr(gate, "_create_permission_card", _fake_card)

    task = asyncio.create_task(
        ensure_tool_permission(chat_id=10, tool_id="p:t", kwargs={}, run_cache={})
    )
    await asyncio.sleep(0.01)
    assert is_pending_permission(gate._request_id(10, "p:t"))
    task.cancel()  # simulates interrupt/stop cancelling the run_code task
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not is_pending_permission(gate._request_id(10, "p:t"))  # finally-block cleaned up


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
async def test_human_response_restores_running_before_resuming_turn(
    monkeypatch, session, test_chat, approved,
):
    """Allow and Deny must restore Stop, even when the resumed turn finishes immediately."""
    from routes import chats

    request_id = gate._request_id(test_chat.id, "p:t")
    future = asyncio.get_running_loop().create_future()
    monkeypatch.setattr(gate, "_PENDING", {request_id: future})
    session.add(ChatItem(
        chat_id=test_chat.id,
        item_type="hitl_request",
        item_metadata=json.dumps({
            "type": "v2_tool_permission",
            "v2_tool_args": {"tool_id": "p:t", "_inprocess_request_id": request_id},
        }),
    ))
    await session.commit()

    events = []

    class WebSocketRecorder:
        async def broadcast(self, event, data):
            events.append((event, data))
            # Real broadcasts yield to the resumed agent task.
            await asyncio.sleep(0)

    ws = WebSocketRecorder()
    monkeypatch.setattr(chats, "ws_manager", ws)

    async def finish_turn():
        decision = await future
        await ws.broadcast("agent_stopped", {"chat_id": test_chat.id, "reason": "completed"})
        return decision

    task = asyncio.create_task(finish_turn())
    try:
        result = await chats.submit_human_response(
            test_chat.id,
            chats.HITLResponseRequest(approved=approved, scope="once"),
            session,
        )
        assert result == {"success": True}
        assert await asyncio.wait_for(task, timeout=1) == {"approved": approved, "scope": "once"}
        assert [event for event, _ in events] == [
            "chat_item_created", "agent_started", "agent_stopped",
        ]
        response_item = events[0][1]["item"]
        assert response_item["item_type"] == "hitl_response"
        assert response_item["item_metadata"]["approved"] is approved
        assert events[1][1] == {"chat_id": test_chat.id}
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

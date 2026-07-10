"""Tests for the in-run STP tool permission gate (generation spend gate)."""

import asyncio
import json

import pytest

from database import Chat
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
    assert cards == ["7:p:t"]
    assert is_pending_permission("7:p:t")

    # Resolve as approved → the parked task completes and caches allow.
    assert resolve_pending_permission("7:p:t", {"approved": True, "scope": "once"})
    await asyncio.wait_for(task, timeout=1)
    assert cache["p:t"] is True
    assert not is_pending_permission("7:p:t")  # registry cleaned up


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
    resolve_pending_permission("8:p:t", {"approved": False, "scope": "once"})
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
    resolve_pending_permission("9:p:t", {"approved": True, "scope": "chat"})
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
    assert is_pending_permission("10:p:t")
    task.cancel()  # simulates interrupt/stop cancelling the run_code task
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not is_pending_permission("10:p:t")  # finally-block cleaned up

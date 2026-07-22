"""The flow LLM role → model mapping:

- ``agent``      → the model the flow's chat uses (get_chat_llm_config)
- ``agent-fast`` → the Settings "quick tasks" model (get_effective_llm_config)
"""
from __future__ import annotations

import pytest

import flow_runtime.production_evaluators as pe


@pytest.mark.asyncio
async def test_agent_fast_role_uses_quick_task_model(monkeypatch):
    calls: dict = {}

    async def fake_effective(role):
        calls["effective"] = role
        return {"model": f"eff-{role}"}

    async def fake_chat(slug, role="agent"):
        calls["chat"] = (slug, role)
        return {"model": f"chat-{slug}"}

    monkeypatch.setattr("llm_resolver.get_effective_llm_config", fake_effective)
    monkeypatch.setattr("llm_resolver.get_chat_llm_config", fake_chat)

    resolve = pe.make_flow_llm_resolve_config(flow_id=7, project_id=None)
    cfg = await resolve("agent-fast")

    assert cfg == {"model": "eff-agent-fast"}
    assert calls["effective"] == "agent-fast"
    # agent-fast must NOT go through the per-chat resolver.
    assert "chat" not in calls


@pytest.mark.asyncio
async def test_agent_role_uses_flow_chat_model(monkeypatch):
    calls: dict = {}

    async def fake_chat(slug, role="agent"):
        calls["chat"] = (slug, role)
        return {"model": f"chat-{slug}"}

    async def fake_slug(flow_id, project_id):
        calls["slug_args"] = (flow_id, project_id)
        return "opus"

    monkeypatch.setattr("llm_resolver.get_chat_llm_config", fake_chat)
    monkeypatch.setattr(pe, "_resolve_flow_chat_model_slug", fake_slug)

    resolve = pe.make_flow_llm_resolve_config(flow_id=7, project_id=3)
    cfg = await resolve("agent")

    assert cfg == {"model": "chat-opus"}
    assert calls["chat"] == ("opus", "agent")
    # The flow's own id/project drive the chat lookup.
    assert calls["slug_args"] == (7, 3)


@pytest.mark.asyncio
async def test_chat_model_slug_falls_back_to_global_default_on_db_error(monkeypatch):
    captured: dict = {}

    def fake_resolve_chat_model_slug(chat_slug, project_slug, global_default):
        captured["args"] = (chat_slug, project_slug, global_default)
        return "resolved-default"

    class _Boom:
        def __call__(self):
            raise RuntimeError("no profile context")

    # _open_session raising simulates "no DB / no profile" at eval time.
    monkeypatch.setattr(pe, "_open_session", _Boom())
    monkeypatch.setattr(
        "llm_resolver.resolve_chat_model_slug", fake_resolve_chat_model_slug
    )

    slug = await pe._resolve_flow_chat_model_slug(flow_id=1, project_id=None)

    assert slug == "resolved-default"
    # chat + project slugs are None; the global default is still consulted.
    assert captured["args"][0] is None
    assert captured["args"][1] is None


@pytest.mark.asyncio
async def test_frozen_resolver_none_slug_falls_back_to_default():
    # Nothing captured at freeze time -> no resolver -> evaluators use the
    # plain role resolver (global default). That's the intended fallback.
    assert pe.make_frozen_flow_llm_resolve_config(None) is None
    assert pe.make_frozen_flow_llm_resolve_config("") is None


@pytest.mark.asyncio
async def test_frozen_resolver_agent_uses_captured_model(monkeypatch):
    calls: dict = {}

    async def fake_chat(slug, role="agent"):
        calls["chat"] = (slug, role)
        return {"model": f"chat-{slug}"}

    async def fake_effective(role):
        calls["effective"] = role
        return {"model": f"eff-{role}"}

    monkeypatch.setattr("llm_resolver.get_chat_llm_config", fake_chat)
    monkeypatch.setattr("llm_resolver.get_effective_llm_config", fake_effective)

    resolve = pe.make_frozen_flow_llm_resolve_config("opus")
    # agent -> the captured freeze-time model
    assert await resolve("agent") == {"model": "chat-opus"}
    assert calls["chat"] == ("opus", "agent")
    # agent-fast -> the Settings quick-tasks model (never the captured one)
    assert await resolve("agent-fast") == {"model": "eff-agent-fast"}
    assert calls["effective"] == "agent-fast"

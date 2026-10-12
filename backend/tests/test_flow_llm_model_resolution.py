"""How a flow's ``llm()`` call picks its model.

A flow program names the model it runs on, so a flow keeps working on what it
was built against. The resolver handles three cases:

- a concrete slug   → used as written
- no model at all   → the profile's ``flow`` setting (project override wins)
- ``agent`` / ``agent-fast`` → legacy aliases in programs written before models
  were named; ``agent`` is the flow chat's model, ``agent-fast`` the quick-task
  setting, both exactly as before.
"""
from __future__ import annotations

import pytest

import flow_runtime.production_evaluators as pe


@pytest.fixture
def patched_resolvers(monkeypatch):
    """Record which resolver each call reaches, and with what."""
    calls: dict = {}

    async def fake_chat(slug, role="agent"):
        calls["chat"] = (slug, role)
        return {"model": f"chat-{slug}"}

    async def fake_effective(role, project_id=None):
        calls["effective"] = (role, project_id)
        return {"model": f"eff-{role}"}

    monkeypatch.setattr("llm_resolver.get_chat_llm_config", fake_chat)
    monkeypatch.setattr("llm_resolver.get_effective_llm_config", fake_effective)
    return calls


class TestLiveFlow:
    @pytest.mark.asyncio
    async def test_concrete_slug_is_used_as_written(self, patched_resolvers):
        resolve = pe.make_flow_llm_resolve_config(flow_id=7, project_id=3)

        cfg = await resolve("stimma:claude-sonnet-5")

        assert cfg == {"model": "chat-stimma:claude-sonnet-5"}
        assert patched_resolvers["chat"] == ("stimma:claude-sonnet-5", "flow")
        # A named model never consults Settings — that's the whole point.
        assert "effective" not in patched_resolvers

    @pytest.mark.asyncio
    async def test_no_model_uses_the_flows_setting(self, patched_resolvers):
        resolve = pe.make_flow_llm_resolve_config(flow_id=7, project_id=3)

        cfg = await resolve(None)

        assert cfg == {"model": "eff-flow"}
        # The project's override gets a chance to win.
        assert patched_resolvers["effective"] == ("flow", 3)

    @pytest.mark.asyncio
    async def test_legacy_agent_fast_uses_quick_task_setting(self, patched_resolvers):
        resolve = pe.make_flow_llm_resolve_config(flow_id=7, project_id=None)

        cfg = await resolve("agent-fast")

        assert cfg == {"model": "eff-quick_task"}
        assert patched_resolvers["effective"] == ("quick_task", None)
        assert "chat" not in patched_resolvers

    @pytest.mark.asyncio
    async def test_legacy_agent_uses_the_flow_chat_model(
        self, monkeypatch, patched_resolvers
    ):
        async def fake_slug(flow_id, project_id):
            patched_resolvers["slug_args"] = (flow_id, project_id)
            return "stimma:claude-opus-5-5"

        monkeypatch.setattr(pe, "_resolve_flow_chat_model_slug", fake_slug)

        resolve = pe.make_flow_llm_resolve_config(flow_id=7, project_id=3)
        cfg = await resolve("agent")

        assert cfg == {"model": "chat-stimma:claude-opus-5-5"}
        assert patched_resolvers["chat"] == ("stimma:claude-opus-5-5", "chat")
        # The flow's own id/project drive the chat lookup.
        assert patched_resolvers["slug_args"] == (7, 3)


class TestFrozenFlow:
    @pytest.mark.asyncio
    async def test_none_slug_yields_no_resolver(self):
        # Nothing captured at freeze time -> no resolver -> evaluators use the
        # plain resolver. That's the intended fallback.
        assert pe.make_frozen_flow_llm_resolve_config(None) is None
        assert pe.make_frozen_flow_llm_resolve_config("") is None

    @pytest.mark.asyncio
    async def test_concrete_slug_beats_the_captured_one(self, patched_resolvers):
        resolve = pe.make_frozen_flow_llm_resolve_config("stimma:claude-opus-5-5")

        cfg = await resolve("stimma:claude-haiku-4.5")

        assert cfg == {"model": "chat-stimma:claude-haiku-4.5"}

    @pytest.mark.asyncio
    async def test_unnamed_and_legacy_agent_use_the_captured_model(
        self, patched_resolvers
    ):
        resolve = pe.make_frozen_flow_llm_resolve_config("stimma:claude-opus-5-5")

        assert await resolve(None) == {"model": "chat-stimma:claude-opus-5-5"}
        assert await resolve("agent") == {"model": "chat-stimma:claude-opus-5-5"}
        assert patched_resolvers["chat"] == ("stimma:claude-opus-5-5", "flow")

    @pytest.mark.asyncio
    async def test_legacy_agent_fast_uses_quick_task_setting(self, patched_resolvers):
        resolve = pe.make_frozen_flow_llm_resolve_config("stimma:claude-opus-5-5")

        assert await resolve("agent-fast") == {"model": "eff-quick_task"}
        assert patched_resolvers["effective"] == ("quick_task", None)


@pytest.mark.asyncio
async def test_chat_model_slug_falls_back_to_profile_default_on_db_error(monkeypatch):
    captured: dict = {}

    def fake_resolve_chat_model_slug(chat_slug, project_slug):
        captured["args"] = (chat_slug, project_slug)
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
    # chat + project slugs are None; the profile default fills in downstream.
    assert captured["args"] == (None, None)

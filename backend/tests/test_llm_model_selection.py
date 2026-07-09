from types import SimpleNamespace

import pytest

from config import LLMEndpointConfig, LLMRoleConfig


@pytest.mark.asyncio
async def test_chat_auto_uses_agent_max_when_cloud_available(monkeypatch):
    import llm_resolver

    seen = {}

    async def fake_cloud_config(role, *, max_context_tokens=None):
        seen["role"] = role
        seen["max_context_tokens"] = max_context_tokens
        return LLMEndpointConfig(
            url="https://cloud.example/api/llm/v1",
            model=role,
            max_context_tokens=max_context_tokens or 0,
        )

    monkeypatch.setattr(llm_resolver, "_get_stimma_cloud_config", fake_cloud_config)

    cfg = await llm_resolver.get_chat_llm_config("auto", role="agent")

    assert cfg.model == "agent-max"
    assert seen["role"] == "agent-max"
    assert seen["max_context_tokens"] == llm_resolver.get_max_context_tokens("agent-max")


@pytest.mark.asyncio
async def test_available_models_auto_describes_local_only_fallback(monkeypatch):
    from routes import models as models_route
    import firebase_auth

    endpoint = LLMEndpointConfig(
        url="http://localhost:8000/v1",
        model="local-model",
        max_context_tokens=64_000,
    )
    settings = SimpleNamespace(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        default_model="auto",
        llms={
            "agent": LLMRoleConfig(source="auto", endpoint=endpoint),
            "agent-fast": LLMRoleConfig(source="auto", endpoint=endpoint),
        },
    )

    async def no_cloud_token():
        return None

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)

    payload = await models_route.get_available_models()
    auto_model = payload["models"][0]
    local_model = next(model for model in payload["models"] if model["slug"] == "local")

    assert auto_model["available"] is True
    assert auto_model["resolved_slug"] == "local"
    assert auto_model["name"] == "Auto: Local Endpoint"
    assert auto_model["description"] == "Uses your configured local endpoint."
    assert auto_model["max_context_tokens"] == 64_000
    assert local_model["available"] is True

    slugs = {model["slug"] for model in payload["models"]}
    assert {"agent-max", "default"}.issubset(slugs)
    assert not {"gpt54", "kimi-k2", "opus", "sonnet"} & slugs


@pytest.mark.asyncio
async def test_available_models_setup_state_is_not_a_hidden_model_list(monkeypatch):
    from routes import models as models_route
    import firebase_auth

    settings = SimpleNamespace(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        default_model="auto",
        llms={
            "agent": LLMRoleConfig(source="auto"),
            "agent-fast": LLMRoleConfig(source="auto"),
        },
    )

    async def no_cloud_token():
        return None

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)

    payload = await models_route.get_available_models()
    auto_model = payload["models"][0]
    slugs = {model["slug"] for model in payload["models"]}

    assert auto_model["available"] is False
    assert auto_model["name"] == "Set up AI models"
    assert auto_model["description"] == "Sign in to Stimma Cloud or configure a local endpoint."
    assert {"agent-max", "default", "local", "auto"} == slugs


@pytest.mark.asyncio
async def test_available_models_acceptance_provider_advertises_auto(monkeypatch):
    """The acceptance lane serves a deterministic in-process LLM for every
    role, so the picker must report `auto` as available. Otherwise the chat
    composer treats the model as unavailable and silently no-ops sends."""
    from routes import models as models_route
    import firebase_auth

    settings = SimpleNamespace(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        default_model="auto",
        llms={
            "agent": LLMRoleConfig(source="auto"),
            "agent-fast": LLMRoleConfig(source="auto"),
        },
    )

    async def no_cloud_token():
        return None

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)
    monkeypatch.setenv("STIMMA_TEST_PROVIDER", "1")

    payload = await models_route.get_available_models()
    auto_model = payload["models"][0]

    assert auto_model["slug"] == "auto"
    assert auto_model["available"] is True
    assert auto_model["resolved_slug"] == "auto"
    assert payload["cloud_status"] == "available"

from types import SimpleNamespace

import pytest

from config import LLMEndpointConfig, LLMRoleConfig


def test_chat_cloud_default_becomes_auto_in_privacy_lockdown(monkeypatch):
    import llm_resolver

    monkeypatch.setattr(
        "privacy_lockdown.is_privacy_lockdown_enabled",
        lambda: True,
    )

    assert llm_resolver.resolve_chat_model_slug(None, None, "agent-max") == "auto"
    assert llm_resolver.resolve_chat_model_slug("agent-max", None, "local") == "auto"
    assert llm_resolver.resolve_chat_model_slug(None, None, "local") == "local"


@pytest.mark.asyncio
async def test_chat_lockdown_cloud_default_resolves_to_local_endpoint(monkeypatch):
    import llm_resolver

    endpoint = LLMEndpointConfig(
        url="http://localhost:8000/v1",
        model="local-model",
    )
    settings = SimpleNamespace(
        get_llm_role_config=lambda _role: LLMRoleConfig(
            source="auto",
            endpoint=endpoint,
        ),
    )

    monkeypatch.setattr(
        "privacy_lockdown.is_privacy_lockdown_enabled",
        lambda: True,
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    slug = llm_resolver.resolve_chat_model_slug(None, None, "agent-max")
    cfg = await llm_resolver.get_chat_llm_config(slug, role="agent")

    assert slug == "auto"
    assert cfg is endpoint


@pytest.mark.asyncio
async def test_chat_auto_uses_minimax_when_cloud_available(monkeypatch):
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

    assert cfg.model == "stimma:minimax-m3"
    assert seen["role"] == "stimma:minimax-m3"
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
    assert auto_model["name"] == "Auto: Local LLM"
    assert auto_model["description"] == "Uses your configured local LLM server."
    assert auto_model["max_context_tokens"] == 64_000
    assert local_model["available"] is True

    slugs = {model["slug"] for model in payload["models"]}
    assert "stimma:minimax-m3" in slugs
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
    assert auto_model["description"] == "Sign in to Stimma Cloud or add a local LLM server."
    assert {"stimma:minimax-m3", "local", "auto"} == slugs


@pytest.mark.asyncio
async def test_available_models_lockdown_exposes_only_local_models(monkeypatch):
    from routes import models as models_route
    import firebase_auth

    endpoint = LLMEndpointConfig(
        url="http://localhost:8000/v1",
        model="local-model",
        max_context_tokens=64_000,
    )
    settings = SimpleNamespace(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        default_model="agent-max",
        llms={
            "agent": LLMRoleConfig(source="auto", endpoint=endpoint),
            "agent-fast": LLMRoleConfig(source="auto", endpoint=endpoint),
        },
    )

    async def cloud_auth_must_not_run():
        raise AssertionError("cloud auth was accessed during Privacy Lockdown")

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(models_route, "is_privacy_lockdown_enabled", lambda: True)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", cloud_auth_must_not_run)

    payload = await models_route.get_available_models()

    assert {model["slug"] for model in payload["models"]} == {"auto", "local"}
    assert all(model["source"] != "stimma_cloud" for model in payload["models"])
    assert payload["models"][0]["resolved_slug"] == "local"
    assert payload["global_default"] == "auto"
    assert payload["cloud_status"] == "privacy_lockdown"
    assert payload["cloud_message"] == ""


@pytest.mark.asyncio
async def test_available_models_lockdown_setup_copy_is_local_only(monkeypatch):
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

    async def cloud_auth_must_not_run():
        raise AssertionError("cloud auth was accessed during Privacy Lockdown")

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(models_route, "is_privacy_lockdown_enabled", lambda: True)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", cloud_auth_must_not_run)

    payload = await models_route.get_available_models()
    auto_model = payload["models"][0]

    assert auto_model["available"] is False
    assert auto_model["name"] == "Set up a local LLM"
    assert auto_model["description"] == "Add a local LLM server in Settings > AI Services."
    assert {model["slug"] for model in payload["models"]} == {"auto", "local"}


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

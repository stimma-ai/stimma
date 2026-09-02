from types import SimpleNamespace

import pytest

from config import LLMEndpointConfig, LLMRoleConfig


def _stub_settings(*, role_models=None, role_efforts=None, **overrides):
    """A settings stub with the per-role model accessor the resolver needs.

    ``role_models`` maps a settings role to its saved slug; anything unset is
    ``auto`` (pick the best available model), which is the shipped default.
    """
    models = {
        "quick_task": "auto", "tool_assistant": "auto",
        "chat": "auto", "flow": "auto",
        **(role_models or {}),
    }
    efforts = dict(role_efforts or {})
    defaults = dict(
        llm_providers=[],
        llm_reasoning_levels={},
        llm_model_prompts={},
        get_role_model_slug=lambda role, profile_id=None: models.get(role, "auto"),
        get_role_effort=lambda role, profile_id=None: efforts.get(role),
        get_llm_role_config=lambda _role: LLMRoleConfig(source="auto"),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)



def test_retired_model_aliases_normalize_to_minimax(monkeypatch):
    import llm_resolver

    monkeypatch.setattr(
        "privacy_lockdown.is_privacy_lockdown_enabled",
        lambda: False,
    )

    assert llm_resolver.normalize_model_slug("agent-max") == "stimma:minimax-m3"
    assert llm_resolver.normalize_model_slug("default") == "stimma:minimax-m3"
    assert llm_resolver.normalize_model_slug("stimma:gpt-5.6-sol") == "stimma:gpt-5.6-sol"
    assert (
        llm_resolver.resolve_chat_model_slug("agent-max", None, "auto")
        == "stimma:minimax-m3"
    )


def test_config_migration_rewrites_retired_model_aliases(tmp_path):
    import yaml

    from config import _migrate_legacy_llm_model_slugs

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "default_model: agent-max\n"
        "quick_task_model: default\n"
        "llm_reasoning_levels:\n"
        "  agent-max: high\n"
        "  default: medium\n"
    )

    assert _migrate_legacy_llm_model_slugs(config_path) is True
    migrated = yaml.safe_load(config_path.read_text())

    assert migrated["default_model"] == "stimma:minimax-m3"
    assert migrated["quick_task_model"] == "stimma:minimax-m3"
    assert migrated["llm_reasoning_levels"] == {"stimma:minimax-m3": "high"}
    assert config_path.with_suffix(".yaml.bak").exists()
    assert _migrate_legacy_llm_model_slugs(config_path) is False


def test_config_migration_carries_fable_reasoning_to_its_successor(tmp_path):
    """Fable 5.1 replaced Fable 5 with an identical ladder, so 'xhigh' carries.

    The Opus 4.8 case above proved the mechanism; this pins the Fable mapping,
    where the saved level must survive rather than fall back to the default.
    """
    import yaml

    from config import _migrate_legacy_llm_model_slugs

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "default_model: stimma:claude-fable-5\n"
        "llm_reasoning_levels:\n"
        "  stimma:claude-fable-5: xhigh\n"
    )

    assert _migrate_legacy_llm_model_slugs(config_path) is True
    migrated = yaml.safe_load(config_path.read_text())

    assert migrated["default_model"] == "stimma:claude-fable-5.1"
    assert migrated["llm_reasoning_levels"] == {"stimma:claude-fable-5.1": "xhigh"}


def test_retired_global_model_keys_are_dropped_not_migrated(tmp_path):
    """The old globals do not seed the per-role settings.

    They were a chat model and a background model, picked before roles existed.
    Carrying them forward would pin every upgraded install to yesterday's answer
    — most visibly by putting bulk flow work on whatever model the user had
    chosen for conversation. Dropping them lets each role fall to `auto`.
    """
    from config import Settings

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "default_model: stimma:claude-opus-5\n"
        "quick_task_model: stimma:claude-haiku-4.5\n"
        "profiles:\n"
        "  - id: default\n"
        "    name: Default\n"
        "    database: stimma_v1.db\n"
        "clip: {model: ViT-g-14, pretrained: laion2b}\n"
        "face_detection: {}\n"
        "server: {host: 127.0.0.1, port: 8000}\n"
    )

    settings = Settings.load_config(str(config_path))

    # Loading must not choke on the retired keys...
    assert not hasattr(settings, "default_model")
    # ...and every role starts automatic rather than inheriting them.
    for role in ("quick_task", "tool_assistant", "chat", "flow"):
        assert settings.get_role_model_slug(role, "default") == "auto"
        assert settings.get_role_effort(role, "default") is None


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
async def test_chat_auto_uses_builtin_catalog_before_cloud_fetch(monkeypatch):
    """Before the live catalog is fetched, the built-in fallback is all `auto`
    has to choose from — so it lands on MiniMax rather than failing."""
    import llm_resolver

    seen = {}

    async def fake_cloud_config(role, *, model_slug=None, max_context_tokens=None,
                                settings_role="agent", effort=None):
        seen["role"] = role
        seen["model_slug"] = model_slug
        seen["max_context_tokens"] = max_context_tokens
        return LLMEndpointConfig(
            url="https://cloud.example/api/llm/v1",
            model=role,
            max_context_tokens=max_context_tokens or 0,
        )

    async def cloud_available():
        return True

    monkeypatch.setattr(llm_resolver, "get_settings", lambda: _stub_settings())
    monkeypatch.setattr(llm_resolver, "_get_stimma_cloud_config", fake_cloud_config)
    monkeypatch.setattr(llm_resolver, "_cloud_is_available", cloud_available)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    cfg = await llm_resolver.get_chat_llm_config("auto", role="chat")

    assert cfg.model == "stimma:minimax-m3"
    assert seen["model_slug"] == "stimma:minimax-m3"
    assert seen["max_context_tokens"] == llm_resolver.get_max_context_tokens(
        "stimma:minimax-m3"
    )


@pytest.mark.asyncio
async def test_auto_draws_the_whole_lineup_from_one_family(monkeypatch):
    """With the real cloud catalog loaded, `auto` picks a coherent set from the
    highest-ranked family rather than a per-role mix across vendors."""
    import llm_resolver

    monkeypatch.setattr(llm_resolver, "get_settings", lambda: _stub_settings())
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    llm_resolver.set_catalog_cache([
        {"slug": "stimma:claude-opus-5", "name": "Claude Opus 5", "model_vendor": "anthropic"},
        {"slug": "stimma:claude-sonnet-5", "name": "Claude Sonnet 5", "model_vendor": "anthropic"},
        {"slug": "stimma:claude-haiku-4.5", "name": "Claude Haiku 4.5", "model_vendor": "anthropic"},
        {"slug": "stimma:minimax-m3", "name": "MiniMax M3", "model_vendor": "minimax"},
        {"slug": "stimma:gpt-5.6-sol", "name": "GPT-5.6 Sol", "model_vendor": "openai"},
    ])
    try:
        candidates = llm_resolver.auto_candidates(cloud_available=True)
        from model_tiers import select_auto_models

        chosen = select_auto_models(candidates)
    finally:
        llm_resolver.set_catalog_cache([])

    assert chosen["chat"] == "stimma:claude-opus-5"
    assert chosen["tool_assistant"] == "stimma:claude-sonnet-5"
    assert chosen["flow"] == "stimma:claude-sonnet-5"
    assert chosen["quick_task"] == "stimma:claude-haiku-4.5"


@pytest.mark.asyncio
async def test_auto_excludes_cloud_models_when_signed_out(monkeypatch):
    """A signed-out install must not have `auto` pick a model it cannot call."""
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(llm_providers=[_local_provider()]),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    candidates = llm_resolver.auto_candidates(cloud_available=False)

    assert [c.slug for c in candidates] == ["local-abc123:qwen3-vl"]


@pytest.mark.asyncio
async def test_available_models_auto_describes_local_only_fallback(monkeypatch):
    from routes import models as models_route
    import firebase_auth

    endpoint = LLMEndpointConfig(
        url="http://localhost:8000/v1",
        model="local-model",
        max_context_tokens=64_000,
        input_modalities=["text", "image"],
        supports_tools=True,
    )
    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
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
    assert auto_model["name"] == "Auto: local-model"
    assert auto_model["description"] == "Uses your configured model endpoint."
    assert auto_model["max_context_tokens"] == 64_000
    assert local_model["available"] is True
    assert local_model["input_modalities"] == ["text", "image"]
    assert local_model["supports_tools"] is True

    slugs = {model["slug"] for model in payload["models"]}
    assert "stimma:minimax-m3" not in slugs
    assert not {"gpt54", "kimi-k2", "opus", "sonnet"} & slugs


def test_legacy_endpoint_profile_persists_capabilities_for_both_roles(monkeypatch):
    from routes import settings as settings_route

    endpoint = LLMEndpointConfig(
        url="http://localhost:8000/v1",
        model="vision-model",
    )
    settings = SimpleNamespace(
        llms={
            "agent": LLMRoleConfig(source="auto", endpoint=endpoint),
            "agent-fast": LLMRoleConfig(source="auto", endpoint=endpoint),
        },
    )
    writes = []
    monkeypatch.setattr(settings_route, "get_settings", lambda: settings)
    monkeypatch.setattr(
        settings_route,
        "_update_llm_config",
        lambda role, data: writes.append((role, data)),
    )

    settings_route._persist_test_meta(
        True,
        {
            "vision": SimpleNamespace(passed=True),
            "tools": SimpleNamespace(passed=True),
        },
    )

    assert {role for role, _data in writes} == {"agent", "agent-fast"}
    assert all(
        data["endpoint"]["input_modalities"] == ["text", "image"]
        and data["endpoint"]["supports_tools"] is True
        for _role, data in writes
    )


@pytest.mark.asyncio
async def test_available_models_setup_state_is_not_a_hidden_model_list(monkeypatch):
    from routes import models as models_route
    import firebase_auth

    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
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
    assert auto_model["description"] == "Add a model provider or sign in to your Stimma account."
    assert {"local", "auto"} == slugs


@pytest.mark.asyncio
async def test_available_models_lockdown_exposes_only_local_models(monkeypatch):
    from routes import models as models_route
    import firebase_auth

    endpoint = LLMEndpointConfig(
        url="http://localhost:8000/v1",
        model="local-model",
        max_context_tokens=64_000,
    )
    settings = _stub_settings(
        role_models={"chat": "agent-max"},
        cloud=SimpleNamespace(base_url="https://cloud.example"),
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

    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
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
    assert auto_model["name"] == "Set up a local model"
    assert auto_model["description"] == "Add a model endpoint in Settings > Chat Models."
    assert {model["slug"] for model in payload["models"]} == {"auto", "local"}


@pytest.mark.asyncio
async def test_available_models_acceptance_provider_advertises_auto(monkeypatch):
    """The acceptance lane serves a deterministic in-process LLM for every
    role, so the picker must report `auto` as available. Otherwise the chat
    composer treats the model as unavailable and silently no-ops sends."""
    from routes import models as models_route
    import firebase_auth

    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
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


def _local_provider(**overrides):
    from config import LLMProviderConfig, LLMProviderModelConfig

    provider = LLMProviderConfig(
        id="local-abc123",
        kind="local",
        name="my-llm-box",
        base_url="http://llmbox.local:8080/v1",
        models=[
            LLMProviderModelConfig(
                id="local-abc123:qwen3-vl",
                model_id="qwen3-vl",
                name="Qwen3 VL",
                max_context_tokens=32_000,
            )
        ],
    )
    for key, value in overrides.items():
        setattr(provider, key, value)
    return provider


def _fast_provider():
    """A second local provider whose model is small enough to read as `fast`."""
    from config import LLMProviderConfig, LLMProviderModelConfig

    return LLMProviderConfig(
        id="local-fast",
        kind="local",
        name="little-box",
        base_url="http://little.local:8080/v1",
        models=[LLMProviderModelConfig(
            id="local-fast:tiny-3b",
            model_id="tiny-3b",
            name="Tiny 3B",
            model_vendor="alibaba",
        )],
    )


@pytest.mark.asyncio
async def test_quick_task_falls_back_to_only_provider_model(monkeypatch):
    """A saved cloud quick-task model with no cloud auth must fall back to the
    one configured provider model instead of demanding a sign-in."""
    import llm_resolver

    settings = _stub_settings(
        role_models={"quick_task": "stimma:minimax-m3", "chat": "stimma:minimax-m3"},
        llm_providers=[_local_provider()],
    )

    async def no_cloud(*args, **kwargs):
        return None

    async def no_token():
        return None

    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_resolver, "_get_stimma_cloud_config", no_cloud)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr("auth_storage.load_auth_state", lambda: None)
    monkeypatch.setattr("firebase_auth.get_valid_id_token", no_token)

    cfg = await llm_resolver.get_effective_llm_config("agent-fast")

    assert cfg.model == "qwen3-vl"
    assert cfg.url == "http://llmbox.local:8080/v1"


@pytest.mark.asyncio
async def test_quick_task_fallback_skips_unusable_providers(monkeypatch):
    """Disabled/broken providers are not fallback candidates."""
    import llm_resolver
    from llm_resolver import LLMUnavailableError

    settings = _stub_settings(
        role_models={"quick_task": "stimma:minimax-m3", "chat": "stimma:minimax-m3"},
        llm_providers=[
            _local_provider(enabled=False),
            _local_provider(last_test_passed=False),
        ],
    )

    async def no_cloud(*args, **kwargs):
        return None

    async def no_token():
        return None

    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_resolver, "_get_stimma_cloud_config", no_cloud)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr("auth_storage.load_auth_state", lambda: None)
    monkeypatch.setattr("firebase_auth.get_valid_id_token", no_token)

    with pytest.raises(LLMUnavailableError):
        await llm_resolver.get_effective_llm_config("agent-fast")


@pytest.mark.asyncio
async def test_chat_auto_falls_back_to_provider_model(monkeypatch):
    """'auto' with no cloud auth and no legacy endpoint resolves to the
    configured provider model."""
    import llm_resolver

    settings = _stub_settings(llm_providers=[_local_provider()])

    async def no_cloud(*args, **kwargs):
        return None

    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_resolver, "_get_stimma_cloud_config", no_cloud)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    cfg = await llm_resolver.get_chat_llm_config("auto", role="agent")

    assert cfg.model == "qwen3-vl"
    assert cfg.url == "http://llmbox.local:8080/v1"


@pytest.mark.asyncio
async def test_available_models_auto_and_quick_task_resolve_to_provider_model(monkeypatch):
    """/models/available mirrors the resolver fallback: 'auto' resolves to the
    one provider model and quick_task_model reports the model in effect."""
    from routes import models as models_route
    import firebase_auth

    settings = _stub_settings(
        role_models={"quick_task": "stimma:minimax-m3"},
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        llm_providers=[_local_provider()],
        llms={
            "agent": LLMRoleConfig(source="auto"),
            "agent-fast": LLMRoleConfig(source="auto"),
        },
    )

    async def no_cloud_token():
        return None

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    # The route asks the resolver what each role lands on, and the resolver
    # reads settings itself — both must see the same install.
    monkeypatch.setattr("llm_resolver.get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)

    payload = await models_route.get_available_models()
    auto_model = payload["models"][0]

    assert auto_model["available"] is True
    assert auto_model["resolved_slug"] == "local-abc123:qwen3-vl"
    assert auto_model["name"] == "Auto: Qwen3 VL"
    # The saved cloud slug is still what's stored, but with no cloud auth it
    # can't be called — `resolved` reports the model that actually will be, so
    # the settings UI never shows a dead selection.
    assert payload["role_defaults"]["quick_task"]["profile"] == "stimma:minimax-m3"
    assert payload["role_defaults"]["quick_task"]["resolved"]["model"] == "local-abc123:qwen3-vl"
    assert payload["role_defaults"]["chat"]["resolved"]["model"] == "local-abc123:qwen3-vl"


@pytest.mark.asyncio
async def test_project_override_beats_the_profile_setting(monkeypatch):
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(
            role_models={"tool_assistant": "local-abc123:qwen3-vl"},
            llm_providers=[_local_provider()],
        ),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    async def project_says(role, project_id):
        return "local-abc123:qwen3-vl" if role == "tool_assistant" else None

    # An explicit project override wins outright...
    slug = await llm_resolver.resolve_role_model_slug(
        "tool_assistant", project_slug="local-abc123:qwen3-vl",
    )
    assert slug == "local-abc123:qwen3-vl"

    # ...and with no override the profile setting stands.
    assert await llm_resolver.resolve_role_model_slug("tool_assistant") == (
        "local-abc123:qwen3-vl"
    )


@pytest.mark.asyncio
async def test_unreachable_saved_slug_resolves_to_an_available_model(monkeypatch):
    """A cloud model saved while signed in must not be reported as in effect
    after signing out — the UI would show a selection nothing can honor."""
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(
            role_models={"chat": "stimma:claude-opus-5"},
            llm_providers=[_local_provider()],
        ),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    async def no_cloud():
        return False

    monkeypatch.setattr(llm_resolver, "_cloud_is_available", no_cloud)

    assert await llm_resolver.resolve_role_model_slug("chat") == "local-abc123:qwen3-vl"


@pytest.mark.asyncio
async def test_saved_slug_survives_when_there_is_nothing_to_switch_to(monkeypatch):
    """With no candidates at all (legacy endpoint pair only), the saved
    selection is left alone rather than rewritten to a model that doesn't exist."""
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(role_models={"chat": "stimma:claude-opus-5"}),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    async def no_cloud():
        return False

    monkeypatch.setattr(llm_resolver, "_cloud_is_available", no_cloud)

    assert await llm_resolver.resolve_role_model_slug("chat") == "stimma:claude-opus-5"


@pytest.mark.asyncio
async def test_privacy_lockdown_keeps_auto_off_the_cloud(monkeypatch):
    """Lockdown is the sharpest case for `auto`: it must never surface a hosted
    model, even one the account is signed in for."""
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(llm_providers=[_local_provider()]),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: True)

    llm_resolver.set_catalog_cache([
        {"slug": "stimma:claude-opus-5", "name": "Claude Opus 5",
         "model_vendor": "anthropic"},
    ])
    try:
        # Even told cloud is available, lockdown drops every hosted candidate.
        candidates = llm_resolver.auto_candidates(cloud_available=True)
    finally:
        llm_resolver.set_catalog_cache([])

    assert [c.slug for c in candidates] == ["local-abc123:qwen3-vl"]


@pytest.mark.asyncio
async def test_remote_providers_are_dropped_in_lockdown(monkeypatch):
    """A bring-your-own OpenAI key is still an egress path; lockdown excludes it
    while leaving local servers selectable."""
    import llm_resolver
    from config import LLMProviderConfig, LLMProviderModelConfig

    remote = LLMProviderConfig(
        id="openai-1", kind="openai", name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=[LLMProviderModelConfig(
            id="openai-1:gpt-5.6-sol", model_id="gpt-5.6-sol",
            name="GPT-5.6 Sol", model_vendor="openai",
        )],
    )
    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(llm_providers=[remote, _local_provider()]),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: True)

    candidates = llm_resolver.auto_candidates(cloud_available=False)

    assert [c.slug for c in candidates] == ["local-abc123:qwen3-vl"]


@pytest.mark.asyncio
async def test_role_defaults_carry_the_fallback_outcomes_not_just_the_selection(monkeypatch):
    """A row renders straight from these blocks, so clearing a pin (or resetting
    the section) can repaint in the same frame instead of showing the old value
    until a refetch lands. `auto` must therefore describe what the role falls to
    with nothing saved, independent of what IS saved."""
    from routes import models as models_route
    import firebase_auth

    settings = _stub_settings(
        # Explicitly pinned to a mid-tier model, so `auto` must differ.
        role_models={"quick_task": "local-abc123:qwen3-vl"},
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        llm_providers=[_local_provider(), _fast_provider()],
        llms={
            "agent": LLMRoleConfig(source="auto"),
            "agent-fast": LLMRoleConfig(source="auto"),
        },
    )

    async def no_cloud_token():
        return None

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr("llm_resolver.get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)

    entry = (await models_route.get_available_models())["role_defaults"]["quick_task"]

    assert entry["profile"] == "local-abc123:qwen3-vl"
    # In effect right now: the pin.
    assert entry["resolved"]["model"] == "local-abc123:qwen3-vl"
    # `auto` ignores the pin and reports the tier-matched model for the role.
    assert entry["auto"]["model"] == "local-fast:tiny-3b"
    # `inherited` is what a project row inheriting this profile would land on.
    assert entry["inherited"]["model"] == "local-abc123:qwen3-vl"


@pytest.mark.asyncio
async def test_cold_catalog_does_not_downgrade_a_saved_cloud_model(monkeypatch):
    """Right after startup the live catalog hasn't been fetched, so the only
    cloud models we know of are the compiled-in fallbacks. Absence from that
    list says nothing about whether a saved cloud slug is reachable — treating
    it as unreachable would silently move every caption and flow step off the
    user's chosen model until something happened to fetch the catalog."""
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(
            role_models={"chat": "stimma:claude-opus-5"},
            llm_providers=[_local_provider()],
        ),
    )
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    async def cloud_up():
        return True

    monkeypatch.setattr(llm_resolver, "_cloud_is_available", cloud_up)
    llm_resolver.set_catalog_cache([])  # cold

    assert await llm_resolver.resolve_role_model_slug("chat") == "stimma:claude-opus-5"

    # Once the catalog IS known and the model genuinely isn't in it, the
    # downgrade is correct again.
    llm_resolver.set_catalog_cache([
        {"slug": "stimma:minimax-m3", "name": "MiniMax M3", "model_vendor": "minimax"},
    ])
    try:
        assert await llm_resolver.resolve_role_model_slug("chat") != "stimma:claude-opus-5"
    finally:
        llm_resolver.set_catalog_cache([])


class TestRoleEffort:
    """Effort resolves like the model does — pinned first, then the role's own
    intent — and a pin never leaks across roles the way the old global
    per-model map did."""

    @pytest.mark.asyncio
    async def test_unpinned_roles_seed_from_the_model_own_levels(self, monkeypatch):
        import llm_resolver

        monkeypatch.setattr(llm_resolver, "get_settings", lambda: _stub_settings())

        anthropic = ["off", "low", "medium", "high", "xhigh", "max"]
        fields = {
            role: llm_resolver._resolve_level(
                role, effort=None, levels=anthropic, default="high",
                quick_task_level="off", slug="stimma:claude-sonnet-5",
            )
            for role in ("quick_task", "tool_assistant", "flow", "chat")
        }
        assert fields == {
            "quick_task": "off",
            "tool_assistant": "off",
            "flow": "low",       # cheap by default: flows multiply the cost
            "chat": "high",
        }

    @pytest.mark.asyncio
    async def test_a_pinned_effort_wins(self, monkeypatch):
        import llm_resolver

        monkeypatch.setattr(llm_resolver, "get_settings", lambda: _stub_settings())
        level = llm_resolver._resolve_level(
            "flow", effort="max", levels=["off", "low", "high", "max"],
            default="high", quick_task_level="off", slug="x",
        )
        assert level == "max"

    @pytest.mark.asyncio
    async def test_a_pin_the_model_cannot_honor_is_ignored(self, monkeypatch):
        """A level saved against one model must not be forced onto another that
        has no such rung — it would reach the provider as garbage."""
        import llm_resolver

        monkeypatch.setattr(llm_resolver, "get_settings", lambda: _stub_settings())
        level = llm_resolver._resolve_level(
            "flow", effort="xhigh", levels=["off", "high"],
            default="high", quick_task_level="off", slug="x",
        )
        assert level == "off"  # falls back to the seeded level, not to xhigh

    @pytest.mark.asyncio
    async def test_wire_roles_keep_the_old_behavior(self, monkeypatch):
        """`agent` / `agent-fast` still serve the chat path and the endpoint
        test screen, which must not change under them."""
        import llm_resolver

        monkeypatch.setattr(
            llm_resolver, "get_settings",
            lambda: _stub_settings(llm_reasoning_levels={"x": "max"}),
        )
        levels = ["off", "low", "high", "max"]
        assert llm_resolver._resolve_level(
            "agent-fast", effort=None, levels=levels, default="high",
            quick_task_level="off", slug="x",
        ) == "off"
        assert llm_resolver._resolve_level(
            "agent", effort=None, levels=levels, default="high",
            quick_task_level="off", slug="x",
        ) == "max"

    @pytest.mark.asyncio
    async def test_profile_effort_is_read_per_role(self, monkeypatch):
        import llm_resolver

        monkeypatch.setattr(
            llm_resolver, "get_settings",
            lambda: _stub_settings(role_efforts={"flow": "medium"}),
        )
        assert await llm_resolver.resolve_role_effort("flow") == "medium"
        assert await llm_resolver.resolve_role_effort("chat") is None

    @pytest.mark.asyncio
    async def test_project_effort_beats_the_profile(self, monkeypatch):
        import llm_resolver

        monkeypatch.setattr(
            llm_resolver, "get_settings",
            lambda: _stub_settings(role_efforts={"flow": "medium"}),
        )
        resolved = await llm_resolver.resolve_role_effort("flow", project_effort="off")
        assert resolved == "off"


def test_chat_effort_resolves_chat_then_project_then_profile(monkeypatch):
    import llm_resolver

    monkeypatch.setattr(
        llm_resolver, "get_settings",
        lambda: _stub_settings(role_efforts={"chat": "high"}),
    )
    assert llm_resolver.resolve_chat_effort("max", "low") == "max"
    assert llm_resolver.resolve_chat_effort(None, "low") == "low"
    assert llm_resolver.resolve_chat_effort(None, None) == "high"


class TestCatalogAlias:
    """The catalog spells its keys agent_model / agent_fast_model; the wire role
    is "agent-fast". The hyphen has to be normalized or the lookup misses."""

    def _catalog(self):
        import llm_resolver
        llm_resolver.set_catalog_cache([{
            "slug": "stimma:claude-haiku-4.5",
            "name": "Claude Haiku 4.5",
            "agent_model": "stimma:claude-haiku-4.5",
            "agent_fast_model": "stimma:claude-haiku-4.5",
            "max_context_tokens": 200_000,
        }])

    def test_fast_role_resolves_to_the_model_not_the_role_name(self, monkeypatch):
        """Regression: this returned the literal string "agent-fast" as the
        model. It went unnoticed while no reasoning fields rode along; once they
        did, the provider rejected every background request with a 400."""
        import llm_resolver

        self._catalog()
        try:
            for role in ("agent-fast", "agent"):
                resolved = llm_resolver._resolve_catalog_alias(
                    "stimma:claude-haiku-4.5", role
                )
                assert resolved == "stimma:claude-haiku-4.5", role
        finally:
            llm_resolver.set_catalog_cache([])

    def test_unknown_slug_is_passed_through(self):
        import llm_resolver

        assert llm_resolver._resolve_catalog_alias("mystery", "agent") == "mystery"

    def test_entry_without_the_key_falls_back_to_the_slug(self, monkeypatch):
        """A catalog row missing its role key must still name a model, never a
        role — the same failure in a different disguise."""
        import llm_resolver

        llm_resolver.set_catalog_cache([
            {"slug": "stimma:odd", "name": "Odd", "max_context_tokens": 1000},
        ])
        try:
            assert llm_resolver._resolve_catalog_alias("stimma:odd", "agent-fast") == "stimma:odd"
        finally:
            llm_resolver.set_catalog_cache([])


@pytest.mark.asyncio
async def test_auto_row_names_the_model_the_resolver_picks(monkeypatch):
    """The picker's `auto` row must agree with Settings and with the call that
    actually goes out. It used to be hardcoded to MiniMax M3 whenever cloud was
    reachable, so a profile on `auto` showed MiniMax in chat while Settings and
    the resolver both said Opus 5."""
    from routes import models as models_route
    import firebase_auth
    import llm_resolver

    catalog = [
        {"slug": "stimma:minimax-m3", "name": "MiniMax M3",
         "model_vendor": "minimax", "canonical_model_id": "minimax-m3"},
        {"slug": "stimma:claude-opus-5", "name": "Claude Opus 5",
         "model_vendor": "anthropic", "canonical_model_id": "claude-opus-5"},
        {"slug": "stimma:claude-haiku-4.5", "name": "Claude Haiku 4.5",
         "model_vendor": "anthropic", "canonical_model_id": "claude-haiku-4-5"},
    ]

    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        llm_providers=[],
        llms={
            "agent": LLMRoleConfig(source="auto"),
            "agent-fast": LLMRoleConfig(source="auto"),
        },
    )

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": catalog}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    async def a_token():
        return "token"

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr("llm_resolver.get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", a_token)
    monkeypatch.setattr(models_route.httpx, "AsyncClient", _Client)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr("auth_storage.load_auth_state", lambda: {"credits": 100})

    try:
        payload = await models_route.get_available_models()
    finally:
        llm_resolver.set_catalog_cache([])

    auto_model = payload["models"][0]
    assert auto_model["slug"] == "auto"
    assert auto_model["resolved_slug"] == "stimma:claude-opus-5"
    assert auto_model["name"] == "Auto: Claude Opus 5"
    # The row the picker shows and the row Settings shows are the same model.
    assert payload["role_defaults"]["chat"]["resolved"]["model"] == "stimma:claude-opus-5"


@pytest.mark.asyncio
async def test_auto_warms_the_catalog_before_choosing(monkeypatch):
    """`auto` resolving off a cold cache saw only the compiled-in fallback rows —
    one cloud model — and picked it regardless of what the account can reach."""
    import llm_resolver

    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        llm_providers=[],
    )
    catalog = [
        {"slug": "stimma:minimax-m3", "name": "MiniMax M3", "model_vendor": "minimax"},
        {"slug": "stimma:claude-opus-5", "name": "Claude Opus 5",
         "model_vendor": "anthropic"},
    ]

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": catalog}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    async def cloud_up():
        return True

    async def a_token():
        return "token"

    import httpx as _httpx

    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_resolver, "_cloud_is_available", cloud_up)
    monkeypatch.setattr("firebase_auth.get_valid_id_token", a_token)
    monkeypatch.setattr(_httpx, "AsyncClient", _Client)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)

    llm_resolver.set_catalog_cache([])  # cold
    try:
        assert await llm_resolver.resolve_auto_slug("chat") == "stimma:claude-opus-5"
    finally:
        llm_resolver.set_catalog_cache([])


class TestEverHadCreditsGate:
    """Buying credits (ever) is what opts an account into hosted LLMs: a
    never-credited signed-in account is 'not configured', not 'no balance'."""

    def test_never_credited_account_raises_not_configured(self, monkeypatch):
        import llm_resolver
        from llm_resolver import LLMInsufficientBalanceError, LLMNotConfiguredError

        monkeypatch.setattr(
            "auth_storage.load_auth_state",
            lambda: {"credits": 0, "ever_had_credits": False},
        )
        with pytest.raises(LLMNotConfiguredError) as exc:
            llm_resolver._raise_no_llm_error()
        assert not isinstance(exc.value, LLMInsufficientBalanceError)
        assert exc.value.code == "llm_not_configured"

    def test_previously_credited_account_raises_insufficient_balance(self, monkeypatch):
        import llm_resolver
        from llm_resolver import LLMInsufficientBalanceError

        monkeypatch.setattr(
            "auth_storage.load_auth_state",
            lambda: {"credits": 0, "ever_had_credits": True},
        )
        with pytest.raises(LLMInsufficientBalanceError):
            llm_resolver._raise_no_llm_error()

    def test_missing_flag_keeps_legacy_insufficient_balance(self, monkeypatch):
        """Accounts synced before the cloud reported the flag stay 'configured'."""
        import llm_resolver
        from llm_resolver import LLMInsufficientBalanceError

        monkeypatch.setattr("auth_storage.load_auth_state", lambda: {"credits": 0})
        with pytest.raises(LLMInsufficientBalanceError):
            llm_resolver._raise_no_llm_error()

    def test_signed_out_raises_not_configured(self, monkeypatch):
        import llm_resolver
        from llm_resolver import LLMNotConfiguredError

        monkeypatch.setattr("auth_storage.load_auth_state", lambda: None)
        with pytest.raises(LLMNotConfiguredError):
            llm_resolver._raise_no_llm_error()

    def test_account_ever_had_credits_helper(self):
        from llm_resolver import account_ever_had_credits

        assert account_ever_had_credits(None) is False
        assert account_ever_had_credits({"ever_had_credits": False, "credits": 0}) is False
        assert account_ever_had_credits({"ever_had_credits": True, "credits": 0}) is True
        assert account_ever_had_credits({"credits": 0}) is True  # unknown -> configured
        # A positive balance always proves it, whatever the stale flag says.
        assert account_ever_had_credits({"ever_had_credits": False, "credits": 50}) is True


@pytest.mark.asyncio
async def test_models_available_reports_llm_configured(monkeypatch):
    """llm_configured distinguishes opted-out (hide/gray optional LLM UI) from
    configured-but-broken (keep UI, fail loudly). Signed out with no providers
    and no endpoint = not configured; a never-credited signed-in account is
    likewise not configured."""
    from routes import models as models_route
    import firebase_auth

    settings = _stub_settings(
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        llm_providers=[],
        llms={
            "agent": LLMRoleConfig(source="auto"),
            "agent-fast": LLMRoleConfig(source="auto"),
        },
    )

    async def no_token():
        return None

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr("llm_resolver.get_settings", lambda: settings)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_token)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr("auth_storage.load_auth_state", lambda: None)

    payload = await models_route.get_available_models()
    assert payload["llm_configured"] is False

    # An enabled provider model makes it configured even when its last test
    # failed — that's the broken-not-hidden treatment.
    settings.llm_providers = [_local_provider(last_test_passed=False)]
    payload = await models_route.get_available_models()
    assert payload["llm_configured"] is True

    # Signed in, zero balance, never had credits: still not configured.
    settings.llm_providers = []

    async def a_token():
        return "token"

    class _Response:
        status_code = 403

        @staticmethod
        def json():
            return {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(firebase_auth, "get_valid_id_token", a_token)
    monkeypatch.setattr(models_route.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        "auth_storage.load_auth_state",
        lambda: {"credits": 0, "ever_had_credits": False},
    )
    payload = await models_route.get_available_models()
    assert payload["llm_configured"] is False

    # ...but having EVER held credits flips it: configured forever.
    monkeypatch.setattr(
        "auth_storage.load_auth_state",
        lambda: {"credits": 0, "ever_had_credits": True},
    )
    payload = await models_route.get_available_models()
    assert payload["llm_configured"] is True

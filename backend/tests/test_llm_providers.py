from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from config import (
    LLMEndpointConfig,
    LLMModelPromptConfig,
    LLMProviderConfig,
    LLMProviderModelConfig,
    LLMReasoningConfig,
    LLMRoleConfig,
)
from llm import _apply_endpoint_reasoning
from llm_http import LLMConnectionError, classify_provider_http_error
from llm_provider_catalog import branded_models, discovered_model
import llm_resolver
from routes import models as models_route
from routes import settings as settings_route


def compatible_openrouter_row(model_id="google/gemma-4-31b-it", **overrides):
    row = {
        "id": model_id,
        "context_length": 131_072,
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["tools", "reasoning"],
        "reasoning": {
            "supported_efforts": ["high", "medium", "low"],
            "default_effort": "medium",
            "default_enabled": True,
            "mandatory": False,
        },
    }
    row.update(overrides)
    return row


def test_save_providers_updates_runtime_state_immediately(monkeypatch):
    runtime_settings = SimpleNamespace(llm_providers=[])
    persisted = []
    provider = LLMProviderConfig(
        id="openai-test",
        kind="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="secret",
    )
    monkeypatch.setattr(models_route, "get_settings", lambda: runtime_settings)
    monkeypatch.setattr(
        models_route,
        "patch_global_section",
        lambda section, value: persisted.append((section, value)),
    )

    models_route._save_providers([provider])

    assert runtime_settings.llm_providers == [provider]
    assert persisted[0][0] == "llm_providers"


def test_generation_readiness_ignores_saved_stimma_cloud_transport():
    settings = SimpleNamespace(tool_providers=[
        SimpleNamespace(
            id=settings_route.STIMMA_CLOUD_PROVIDER_ID,
            enabled=True,
            type="websocket",
        ),
    ])

    assert settings_route._has_local_generation_provider_configured(settings) is False


def test_generation_readiness_accepts_configured_external_provider():
    settings = SimpleNamespace(tool_providers=[
        SimpleNamespace(id="comfyui", enabled=True, type="websocket"),
    ])

    assert settings_route._has_local_generation_provider_configured(settings) is True


def test_readiness_carries_setup_wizard_versions(monkeypatch):
    settings = SimpleNamespace(
        tool_providers=[],
        setup_wizard_seen_version=0,
    )
    monkeypatch.setattr(settings_route, "_has_cloud_balance", lambda: False)
    monkeypatch.setattr(
        settings_route, "_has_local_agent_llm_configured", lambda _s: False
    )

    readiness = settings_route._compute_readiness(settings)

    assert readiness.wizard_version == settings_route.SETUP_WIZARD_VERSION
    assert readiness.wizard_seen_version == 0


@pytest.mark.asyncio
async def test_mark_setup_wizard_seen_persists_current_version(monkeypatch):
    runtime_settings = SimpleNamespace(setup_wizard_seen_version=0)
    persisted = []
    monkeypatch.setattr(settings_route, "get_settings", lambda: runtime_settings)
    monkeypatch.setattr(
        settings_route,
        "patch_global_section",
        lambda section, value: persisted.append((section, value)),
    )

    result = await settings_route.mark_setup_wizard_seen()

    assert persisted == [
        ("setup_wizard_seen_version", settings_route.SETUP_WIZARD_VERSION)
    ]
    assert runtime_settings.setup_wizard_seen_version == settings_route.SETUP_WIZARD_VERSION
    assert result["wizard_seen_version"] == settings_route.SETUP_WIZARD_VERSION


@pytest.mark.asyncio
async def test_new_provider_is_visible_to_immediate_followup_read(monkeypatch):
    runtime_settings = SimpleNamespace(llm_providers=[])
    monkeypatch.setattr(models_route, "get_settings", lambda: runtime_settings)
    monkeypatch.setattr(models_route, "patch_global_section", lambda _section, _value: None)

    async def discover(_provider):
        return [
            {"id": model.model_id}
            for model in branded_models("openai", "preview")
        ]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)

    created = await models_route.create_llm_provider(
        models_route.ProviderCreateRequest(
            kind="openai",
            api_key="secret",
            model_ids=[],
        )
    )
    listed = await models_route.list_llm_providers()

    assert listed["providers"][0]["id"] == created["id"]
    assert listed["providers"][0]["last_test_passed"] is True


def test_branded_provider_contracts_match_current_model_series():
    openai = branded_models("openai", "openai-test")
    assert [model.model_id for model in openai] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert openai[0].reasoning.levels == ["off", "low", "medium", "high", "xhigh"]
    assert openai[0].reasoning.quick_task == "off"
    assert openai[0].model_vendor == "openai"

    anthropic = branded_models("anthropic", "anthropic-test")
    assert [model.model_id for model in anthropic] == [
        "claude-sonnet-5",
        "claude-opus-4-8",
        "claude-fable-5",
        "claude-haiku-4-5-20251001",
    ]
    assert anthropic[2].reasoning.mode == "required"
    assert anthropic[2].reasoning.quick_task == "low"
    assert anthropic[0].model_vendor == "anthropic"
    assert discovered_model("openrouter-test", "qwen/qwen3.7-plus").model_vendor == "alibaba"
    assert discovered_model("openrouter-test", "moonshotai/kimi-k2.7").model_vendor == "kimi"
    assert discovered_model("local-test", "gemma-4-31b-it").model_vendor == "google"
    assert discovered_model("local-test", "google/gemma-4-26b-a4b").model_vendor == "google"

    google = branded_models("google", "google-test")
    assert [model.model_id for model in google] == [
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite",
    ]
    assert all(model.max_context_tokens == 1_048_576 for model in google)
    assert google[0].model_vendor == "gemini"
    assert google[0].reasoning.levels == ["minimal", "low", "medium", "high"]
    assert google[0].reasoning.quick_task == "minimal"
    assert google[1].reasoning.levels == ["low", "medium", "high"]


def test_generic_local_provider_name_is_replaced_with_endpoint_identity():
    provider = LLMProviderConfig(
        id="local-test",
        kind="local",
        name="Local LLM · studio-mac.local:1234",
        base_url="http://studio-mac.local:1234/v1",
        models=[],
    )

    response = models_route._provider_response(provider)

    assert response["name"] == "studio-mac.local:1234"


def test_reasoning_config_accepts_yaml_11_off_booleans():
    # This is the exact Python shape produced when PyYAML reads the config that
    # ruamel wrote with unquoted `off` values and keys.
    reasoning = LLMReasoningConfig.model_validate({
        "mode": "none",
        "levels": [False],
        "default": False,
        "quick_task": False,
        "control": "none",
        "wire_levels": {False: False},
    })

    assert reasoning.levels == ["off"]
    assert reasoning.default == "off"
    assert reasoning.quick_task == "off"
    assert reasoning.wire_levels == {"off": False}


@pytest.mark.asyncio
async def test_openrouter_rejects_invalid_key_before_reading_public_model_catalog(monkeypatch):
    real_async_client = httpx.AsyncClient
    requested_paths = []

    def handler(request):
        requested_paths.append(request.url.path)
        if request.url.path == "/api/v1/key":
            return httpx.Response(401, json={"error": "invalid_api_key"})
        return httpx.Response(200, json={"data": [{"id": "qwen/test"}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        models_route.httpx,
        "AsyncClient",
        lambda: real_async_client(transport=transport),
    )
    provider = LLMProviderConfig(
        id="openrouter-test",
        kind="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="abcde",
    )

    with pytest.raises(Exception) as caught:
        await models_route._discover_provider_models(provider)

    assert caught.value.detail == "API key is invalid."
    assert requested_paths == ["/api/v1/key"]


@pytest.mark.asyncio
async def test_google_catalog_ids_are_normalized_for_fixed_contracts(monkeypatch):
    real_async_client = httpx.AsyncClient

    def handler(_request):
        return httpx.Response(200, json={"data": [
            {"id": "models/gemini-3.5-flash"},
            {"id": "models/gemini-3.1-pro-preview"},
            {"id": "models/gemini-3.1-flash-lite"},
        ]})

    monkeypatch.setattr(
        models_route.httpx,
        "AsyncClient",
        lambda: real_async_client(transport=httpx.MockTransport(handler)),
    )
    provider = LLMProviderConfig(
        id="google-test",
        kind="google",
        name="Google",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key="secret",
    )

    rows = await models_route._discover_provider_models(provider)

    assert [row["id"] for row in rows] == [
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite",
    ]


@pytest.mark.asyncio
async def test_together_catalog_only_keeps_documented_vision_models(monkeypatch):
    real_async_client = httpx.AsyncClient

    def handler(_request):
        return httpx.Response(200, json=[
            {"id": "legacy/tiny-model", "display_name": "Tiny", "type": "chat"},
            {
                "id": "MiniMaxAI/MiniMax-M3",
                "display_name": "MiniMax M3",
                "context_length": 524_288,
                "type": "chat",
            },
            {
                "id": "moonshotai/Kimi-K2.7-Code",
                "display_name": "Kimi K2.7 Code",
                "context_length": 262_144,
                "type": "chat",
            },
            {
                "id": "zai-org/GLM-5.2",
                "display_name": "GLM 5.2",
                "context_length": 262_144,
                "type": "chat",
            },
            {"id": "black-forest-labs/FLUX", "display_name": "Flux", "type": "image"},
        ])

    monkeypatch.setattr(
        models_route.httpx,
        "AsyncClient",
        lambda: real_async_client(transport=httpx.MockTransport(handler)),
    )
    provider = LLMProviderConfig(
        id="together-test",
        kind="together",
        name="Together AI",
        base_url="https://api.together.xyz/v1",
        api_key="secret",
    )

    rows = await models_route._discover_provider_models(provider)
    selectable = models_route._selectable_provider_rows(provider, rows)

    assert [(row["id"], row["name"]) for row in selectable] == [
        ("MiniMaxAI/MiniMax-M3", "MiniMax M3"),
        ("moonshotai/Kimi-K2.7-Code", "Kimi K2.7 Code"),
    ]


def test_together_rejects_text_only_glm_5_2():
    assert models_route._together_capability_gaps({
        "id": "zai-org/GLM-5.2",
        "type": "chat",
    }) == ["vision"]


@pytest.mark.asyncio
async def test_fireworks_catalog_filters_to_serverless_vision_tool_models(monkeypatch):
    real_async_client = httpx.AsyncClient

    def handler(_request):
        return httpx.Response(200, json={"models": [
            {
                "name": "accounts/fireworks/models/flux-1-schnell-fp8",
                "displayName": "Flux Schnell",
                "supportsImageInput": False,
                "supportsTools": False,
                "supportsServerless": True,
            },
            {
                "name": "accounts/fireworks/models/kimi-k2p6",
                "displayName": "Kimi K2.6",
                "contextLength": 262_144,
                "supportsImageInput": True,
                "supportsTools": True,
                "supportsServerless": True,
                "status": {"code": "OK"},
            },
            {
                "name": "accounts/fireworks/models/glm-5p2",
                "displayName": "GLM 5.2",
                "contextLength": 1_048_576,
                "supportsImageInput": False,
                "supportsTools": True,
                "supportsServerless": True,
                "status": {"code": "OK"},
            },
        ]})

    monkeypatch.setattr(
        models_route.httpx,
        "AsyncClient",
        lambda: real_async_client(transport=httpx.MockTransport(handler)),
    )
    provider = LLMProviderConfig(
        id="fireworks-test",
        kind="fireworks",
        name="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        api_key="secret",
    )

    rows = await models_route._discover_provider_models(provider)
    selectable = models_route._selectable_provider_rows(provider, rows)

    assert [(row["id"], row["name"]) for row in selectable] == [
        ("accounts/fireworks/models/kimi-k2p6", "Kimi K2.6"),
    ]
    assert selectable[0]["context_length"] == 262_144


def test_legacy_openrouter_catalog_check_does_not_report_connected():
    provider = LLMProviderConfig(
        id="openrouter-test",
        kind="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="abcde",
        last_test_passed=True,
    )

    assert models_route._provider_response(provider)["last_test_passed"] is None


def test_openrouter_catalog_requires_vision_tools_and_reasoning():
    compatible = compatible_openrouter_row()
    missing_vision = compatible_openrouter_row(
        architecture={"input_modalities": ["text"]},
    )
    missing_tools = compatible_openrouter_row(supported_parameters=["reasoning"])
    missing_reasoning = compatible_openrouter_row(reasoning=None)

    assert models_route._openrouter_capability_gaps(compatible) == []
    assert models_route._openrouter_capability_gaps(missing_vision) == ["vision"]
    assert models_route._openrouter_capability_gaps(missing_tools) == ["tools"]
    assert models_route._openrouter_capability_gaps(missing_reasoning) == ["reasoning"]


def test_openrouter_reasoning_levels_come_from_catalog():
    model = discovered_model("openrouter-test", "google/gemini-test")

    models_route._apply_openrouter_reasoning_metadata(
        model,
        compatible_openrouter_row(
            "google/gemini-test",
            reasoning={
                "supported_efforts": ["high", "low"],
                "default_effort": "high",
                "default_enabled": True,
                "mandatory": True,
            },
        ),
    )

    assert model.reasoning.mode == "required"
    assert model.reasoning.levels == ["low", "high"]
    assert model.reasoning.default == "high"
    assert model.reasoning.quick_task == "low"
    assert model.reasoning.control == "openrouter_effort"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, '{"error":{"message":"Incorrect API key provided"}}', "API key is invalid."),
        (402, '{"error":"payment required"}', "This account has insufficient funds."),
        (403, '{"error":"permission denied"}', "This key does not have permission to use this provider."),
        (429, '{"error":"rate limit exceeded"}', "The provider is rate limiting requests. Try again shortly."),
        (503, '{"error":"unavailable"}', "The provider is unavailable."),
    ],
)
def test_provider_connection_errors_have_actionable_copy(status, body, expected):
    response = httpx.Response(status, text=body)

    assert models_route._provider_error_detail(response, models_endpoint=True) == expected


def test_provider_model_resolver_uses_saved_chat_level_and_minimum_for_quick_tasks(monkeypatch):
    model = branded_models("openai", "openai-test")[0]
    model.extra_system_prompt = "Keep answers concise."
    provider = LLMProviderConfig(
        id="openai-test",
        kind="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        models=[model],
    )
    settings = SimpleNamespace(
        llm_providers=[provider],
        llm_reasoning_levels={model.id: "xhigh"},
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    chat = llm_resolver._get_provider_model_config(model.id, quick_task=False)
    assert chat is not None
    assert chat.reasoning_level == "xhigh"
    assert chat.content_policy_enabled is True
    assert chat.extra_system_prompt == "Keep answers concise."

    quick = llm_resolver._get_provider_model_config(model.id, quick_task=True)
    assert quick is not None
    assert quick.reasoning_level == "off"


def test_provider_model_resolver_repairs_removed_reasoning_level(monkeypatch):
    model = branded_models("xai", "xai-test")[0]
    model.content_policy_enabled = False
    provider = LLMProviderConfig(
        id="xai-test",
        kind="xai",
        name="xAI",
        base_url="https://api.x.ai/v1",
        api_key="secret",
        models=[model],
    )
    settings = SimpleNamespace(
        llm_providers=[provider],
        llm_reasoning_levels={model.id: "off"},
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    resolved = llm_resolver._get_provider_model_config(model.id, quick_task=False)
    assert resolved is not None
    assert resolved.reasoning_level == "high"
    assert resolved.content_policy_enabled is False


def test_cloud_prompt_settings_are_read_per_model(monkeypatch):
    monkeypatch.setattr(
        llm_resolver,
        "get_settings",
        lambda: SimpleNamespace(
            llm_model_prompts={
                "stimma:minimax-m3": LLMModelPromptConfig(
                    content_policy_enabled=False,
                    extra_system_prompt="Use terse answers.",
                )
            }
        ),
    )

    assert llm_resolver._model_prompt_fields("stimma:minimax-m3") == {
        "content_policy_enabled": False,
        "extra_system_prompt": "Use terse answers.",
    }


@pytest.mark.asyncio
async def test_failed_provider_is_blocked_without_cloud_fallback(monkeypatch):
    model = branded_models("openai", "openai-test")[0]
    provider = LLMProviderConfig(
        id="openai-test",
        kind="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        models=[model],
        last_test_passed=False,
    )
    settings = SimpleNamespace(
        default_model=model.id,
        quick_task_model=model.id,
        llm_providers=[provider],
        llm_reasoning_levels={},
        llm_content_policy="stimma",
        llm_extra_system_prompt="",
        get_llm_role_config=lambda _role: LLMRoleConfig(source="auto"),
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    with pytest.raises(llm_resolver.LLMUnavailableError, match="OpenAI is unavailable"):
        await llm_resolver.get_effective_llm_config("agent-fast")


@pytest.mark.asyncio
async def test_quick_tasks_respect_explicit_legacy_local_endpoint(monkeypatch):
    endpoint = LLMEndpointConfig(url="http://localhost:1234/v1", model="local-model")
    settings = SimpleNamespace(
        default_model="local",
        quick_task_model="local",
        llm_providers=[],
        get_llm_role_config=lambda _role: LLMRoleConfig(source="auto", endpoint=endpoint),
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    assert await llm_resolver.get_effective_llm_config("agent-fast") is endpoint


def test_cloud_reasoning_repairs_removed_level(monkeypatch):
    llm_resolver.set_catalog_cache([
        {
            "slug": "stimma:test",
            "reasoning": {
                "levels": ["low", "high"],
                "default": "high",
                "quick_task": "low",
            },
        }
    ])
    monkeypatch.setattr(
        llm_resolver,
        "get_settings",
        lambda: SimpleNamespace(llm_reasoning_levels={"stimma:test": "off"}),
    )
    assert llm_resolver._cloud_reasoning_fields("stimma:test", quick_task=False)[
        "reasoning_level"
    ] == "high"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, '{"error":"invalid_api_key"}', "provider_invalid_key"),
        (402, '{"error":"payment required"}', "provider_insufficient_funds"),
        (403, '{"error":"insufficient balance"}', "provider_insufficient_funds"),
        (404, '{"error":"model not found"}', "provider_model_missing"),
        (429, '{"error":"rate limit"}', "provider_rate_limited"),
    ],
)
def test_provider_http_failures_get_actionable_types(status, body, expected):
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    response = httpx.Response(status, request=request, text=body)
    error = httpx.HTTPStatusError("provider failed", request=request, response=response)
    assert classify_provider_http_error(error)[0] == expected


@pytest.mark.asyncio
async def test_remote_model_profile_surfaces_insufficient_funds(monkeypatch):
    import llm

    calls = []

    async def fail_completion(*_args, **_kwargs):
        calls.append(True)
        request = httpx.Request(
            "POST",
            "https://api.together.xyz/v1/chat/completions",
        )
        response = httpx.Response(
            402,
            request=request,
            json={"error": {"message": "Credit limit exceeded."}},
        )
        raise httpx.HTTPStatusError(
            "HTTP 402: Credit limit exceeded.",
            request=request,
            response=response,
        )

    monkeypatch.setattr(llm, "llm_completion", fail_completion)
    scenarios, _detected = await settings_route._profile_endpoint(
        LLMEndpointConfig(
            url="https://api.together.xyz/v1",
            model="MiniMaxAI/MiniMax-M3",
            api_key="secret",
        )
    )

    assert scenarios["text"].error == (
        "The provider declined this request for insufficient funds."
    )
    assert scenarios["tools"].error == (
        "The provider declined this request for insufficient funds."
    )
    assert "context" not in scenarios
    assert len(calls) == 4


def test_byo_connection_failure_gets_service_feedback():
    error = LLMConnectionError(
        "connection refused",
        endpoint="http://localhost:1234/v1",
        is_cloud=False,
    )
    assert classify_provider_http_error(error) == (
        "provider_connection_failed",
        "Could not reach this service.",
    )


def test_local_profile_updates_tools_vision_and_reasoning_contract():
    passed = SimpleNamespace(passed=True)
    model = LLMProviderModelConfig(id="local:m", model_id="m", name="M")
    models_route._apply_local_profile(
        model,
        {"tools": passed, "vision": passed},
        SimpleNamespace(reasoning_method="enable_thinking", reasoning_mode="toggleable"),
    )
    assert model.supports_tools is True
    assert model.input_modalities == ["text", "image"]
    assert model.reasoning.levels == ["off", "high"]
    assert model.reasoning.wire_levels == {"off": False, "high": True}


@pytest.mark.parametrize(
    ("kind", "model_id", "expected"),
    [
        ("openai", "gpt-5.6-sol", "openai:gpt-5.6-sol"),
        ("openrouter", "openai/gpt-5.6-sol", "openai:gpt-5.6-sol"),
        ("openrouter", "x-ai/grok-4.5", "xai:grok-4.5"),
        ("openrouter", "minimax/minimax-m3", "minimax:minimax-m3"),
        ("openrouter", "qwen/qwen3.7-plus", "qwen:qwen-3.7-plus"),
        ("openrouter", "moonshotai/kimi-k2.7-code", "moonshot:kimi-k2.7"),
        ("openrouter", "moonshotai/kimi-k2.7", "moonshot:kimi-k2.7"),
        ("together", "MiniMaxAI/MiniMax-M3", "minimax:minimax-m3"),
        ("together", "Qwen/Qwen3.7-Plus", "qwen:qwen-3.7-plus"),
        ("fireworks", "accounts/fireworks/models/glm-5p2", "zai:glm-5.2"),
    ],
)
def test_duplicate_routes_share_canonical_identity(kind, model_id, expected):
    assert models_route._canonical_model_id(kind, model_id) == expected


def test_reasoning_contract_translates_exact_provider_wire_shape():
    openai_model = branded_models("openai", "openai-test")[0]
    config = SimpleNamespace(
        extra_body=None,
        reasoning_control=openai_model.reasoning.control,
        reasoning_level="xhigh",
        reasoning_default=openai_model.reasoning.default,
        reasoning_quick_task=openai_model.reasoning.quick_task,
        reasoning_wire_levels=openai_model.reasoning.wire_levels,
    )
    assert _apply_endpoint_reasoning(config, None, {"type": "enabled"}) == {
        "reasoning_effort": "xhigh"
    }

    sonnet = branded_models("anthropic", "anthropic-test")[0]
    config.reasoning_control = sonnet.reasoning.control
    config.reasoning_level = "off"
    config.reasoning_default = sonnet.reasoning.default
    config.reasoning_quick_task = sonnet.reasoning.quick_task
    config.reasoning_wire_levels = sonnet.reasoning.wire_levels
    assert _apply_endpoint_reasoning(config, None, None) == {
        "thinking": {"type": "disabled"}
    }


@pytest.mark.asyncio
async def test_adding_openai_key_checks_models_and_stores_branded_contracts(monkeypatch):
    settings = SimpleNamespace(llm_providers=[])
    saved = []

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(models_route, "_save_providers", lambda providers: saved.extend(providers))

    async def discover(_provider):
        return [{"id": model_id} for model_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    response = await models_route.create_llm_provider(
        models_route.ProviderCreateRequest(kind="openai", api_key="secret")
    )
    assert response["api_key"] == "***"
    assert response["api_key_set"] is True
    assert [model["model_id"] for model in response["models"]] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_provider_preview_discovers_models_without_saving(monkeypatch):
    async def discover(provider):
        assert provider.base_url == "http://studio.local:1234/v1"
        return [{"id": "qwen-3.5-122b", "context_length": 131_072}]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    response = await models_route.preview_llm_provider_models(
        models_route.ProviderCreateRequest(
            kind="local",
            name="Studio Mac",
            base_url="http://studio.local:1234/v1",
        )
    )

    assert response == {
        "provider_name": "Studio Mac",
        "models": [
            {
                "id": "qwen-3.5-122b",
                "name": "qwen-3.5-122b",
                "context_length": 131_072,
            }
        ],
    }


@pytest.mark.asyncio
async def test_single_openrouter_model_is_profiled_and_added_automatically(monkeypatch):
    settings = SimpleNamespace(llm_providers=[])
    saved = []
    profiled = []
    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(models_route, "_save_providers", lambda providers: saved.extend(providers))

    async def discover(_provider):
        return [compatible_openrouter_row()]

    async def test_model(provider, model):
        profiled.append((provider.kind, model.model_id))
        model.last_test_passed = True
        model.last_test_results = {
            name: {"passed": True}
            for name in models_route.REQUIRED_MODEL_PROFILE_SCENARIOS
        }
        return model.last_test_results

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    monkeypatch.setattr(models_route, "_test_local_provider_model", test_model)

    response = await models_route.create_llm_provider(
        models_route.ProviderCreateRequest(kind="openrouter", api_key="secret")
    )

    assert profiled == [("openrouter", "google/gemma-4-31b-it")]
    assert [model["model_id"] for model in response["models"]] == ["google/gemma-4-31b-it"]
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_empty_model_selection_stages_single_model_provider_without_profiling(monkeypatch):
    settings = SimpleNamespace(llm_providers=[])
    profiled = []
    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(models_route, "_save_providers", lambda _providers: None)

    async def discover(_provider):
        return [compatible_openrouter_row()]

    async def test_model(_provider, _model):
        profiled.append(True)

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    monkeypatch.setattr(models_route, "_test_local_provider_model", test_model)

    response = await models_route.create_llm_provider(
        models_route.ProviderCreateRequest(
            kind="openrouter",
            api_key="secret",
            model_ids=[],
        )
    )

    assert response["models"] == []
    assert profiled == []


@pytest.mark.asyncio
async def test_updating_branded_provider_key_marks_connection_ready(monkeypatch):
    model = branded_models("xai", "xai-test")[0]
    provider = LLMProviderConfig(
        id="xai-test",
        kind="xai",
        name="xAI",
        base_url="https://api.x.ai/v1",
        api_key="old-key",
        models=[model],
        last_test_passed=False,
        last_error="Old key failed.",
    )
    monkeypatch.setattr(
        models_route,
        "get_settings",
        lambda: SimpleNamespace(llm_providers=[provider]),
    )

    async def discover(_provider):
        return [{"id": "grok-4.5"}]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    monkeypatch.setattr(models_route, "_save_providers", lambda _providers: None)

    response = await models_route.update_llm_provider(
        "xai-test",
        models_route.ProviderUpdateRequest(api_key="new-key"),
    )

    assert response["last_test_passed"] is True
    assert response["last_error"] is None
    assert response["last_tested_at"]


@pytest.mark.asyncio
async def test_local_provider_test_persists_capabilities_and_detection(monkeypatch):
    from routes.settings import LLMDetected, LLMScenarioResult

    provider = LLMProviderConfig(
        id="local-test",
        kind="local",
        name="Studio Mac",
        base_url="http://studio.local:1234/v1",
    )
    model = LLMProviderModelConfig(
        id="local-test:qwen-3.5-122b",
        model_id="qwen-3.5-122b",
        name="Qwen 3.5 122B",
    )

    async def profile(_config):
        return (
            {
                "text": LLMScenarioResult(passed=True, elapsed_ms=12),
                "tools": LLMScenarioResult(passed=True, elapsed_ms=15),
                "vision": LLMScenarioResult(passed=True, elapsed_ms=18),
                "thinking": LLMScenarioResult(passed=True, elapsed_ms=20),
                "context": LLMScenarioResult(passed=True, elapsed_ms=22),
            },
            LLMDetected(
                runtime="vLLM",
                reasoning_method="enable_thinking",
                reasoning_mode="toggleable",
                reasoning_output="field",
            ),
        )

    monkeypatch.setattr(settings_route, "_profile_endpoint", profile)
    results = await models_route._test_local_provider_model(provider, model)

    assert results["text"]["passed"] is True
    assert model.supports_tools is True
    assert model.input_modalities == ["text", "image"]
    assert model.detected_runtime == "vLLM"
    assert model.reasoning.control == "enable_thinking"
    assert model.reasoning.levels == ["off", "high"]
    assert model.last_test_passed is True


@pytest.mark.asyncio
async def test_model_profile_requires_vision(monkeypatch):
    from routes.settings import LLMDetected, LLMScenarioResult

    provider = LLMProviderConfig(
        id="local-test",
        kind="local",
        name="Studio Mac",
        base_url="http://studio.local:1234/v1",
    )
    model = LLMProviderModelConfig(
        id="local-test:qwen-3.5-122b",
        model_id="qwen-3.5-122b",
        name="Qwen 3.5 122B",
    )

    async def profile(_config):
        return (
            {
                "text": LLMScenarioResult(passed=True),
                "tools": LLMScenarioResult(passed=True),
                "vision": LLMScenarioResult(passed=False, error="Vision not supported"),
                "thinking": LLMScenarioResult(passed=True),
                "context": LLMScenarioResult(passed=True),
            },
            LLMDetected(reasoning_method="none", reasoning_mode="none"),
        )

    monkeypatch.setattr(settings_route, "_profile_endpoint", profile)
    results = await models_route._profile_provider_model(provider, model)

    assert results["vision"]["passed"] is False
    assert model.last_test_passed is False
    assert model.last_error == "Vision is required."


@pytest.mark.asyncio
async def test_model_profile_surfaces_text_request_failure(monkeypatch):
    from routes.settings import LLMDetected, LLMScenarioResult

    provider = LLMProviderConfig(
        id="together-test",
        kind="together",
        name="Together AI",
        base_url="https://api.together.xyz/v1",
    )
    model = LLMProviderModelConfig(
        id="together-test:MiniMaxAI/MiniMax-M3",
        model_id="MiniMaxAI/MiniMax-M3",
        name="MiniMax M3",
    )

    async def profile(_config):
        return (
            {
                "text": LLMScenarioResult(
                    passed=False,
                    error="The provider declined this request for insufficient funds.",
                ),
                "tools": LLMScenarioResult(passed=False),
                "vision": LLMScenarioResult(passed=False),
                "thinking": LLMScenarioResult(passed=False),
                "context": LLMScenarioResult(passed=True),
            },
            LLMDetected(reasoning_method="none", reasoning_mode="none"),
        )

    monkeypatch.setattr(settings_route, "_profile_endpoint", profile)
    await models_route._profile_provider_model(provider, model)

    assert model.last_error == "The provider declined this request for insufficient funds."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "base_url"),
    [
        ("local", "http://studio.local:1234/v1"),
        ("together", "https://api.together.xyz/v1"),
        ("fireworks", "https://api.fireworks.ai/inference/v1"),
    ],
)
async def test_profiled_model_requires_detected_reasoning(monkeypatch, kind, base_url):
    from routes.settings import LLMDetected, LLMScenarioResult

    provider = LLMProviderConfig(
        id=f"{kind}-test",
        kind=kind,
        name=kind,
        base_url=base_url,
    )
    model = LLMProviderModelConfig(
        id=f"{kind}-test:qwen-3.5-122b",
        model_id="qwen-3.5-122b",
        name="Qwen 3.5 122B",
    )

    async def profile(_config):
        return (
            {
                scenario: LLMScenarioResult(passed=True)
                for scenario in models_route.REQUIRED_MODEL_PROFILE_SCENARIOS
            },
            LLMDetected(reasoning_method="none", reasoning_mode="none"),
        )

    monkeypatch.setattr(settings_route, "_profile_endpoint", profile)
    await models_route._profile_provider_model(provider, model)

    assert model.last_test_results["thinking"]["passed"] is False
    assert model.last_test_passed is False
    assert model.last_error == "Reasoning is required."


def test_flexible_provider_rejects_an_untested_new_model():
    provider = LLMProviderConfig(
        id="local-test",
        kind="local",
        name="Studio Mac",
        base_url="http://studio.local:1234/v1",
    )
    model = discovered_model(provider.id, "qwen-3.5-122b")
    model.input_modalities = ["text", "image"]
    model.supports_tools = True
    model.reasoning = LLMReasoningConfig(
        mode="optional",
        levels=["off", "high"],
        default="high",
        quick_task="off",
        control="enable_thinking",
        wire_levels={"off": False, "high": True},
    )

    with pytest.raises(Exception) as caught:
        models_route._validated_models(provider, [model.model_dump()])

    assert "must pass its tests" in caught.value.detail


@pytest.mark.asyncio
async def test_openrouter_model_profile_tests_candidate_without_adding_it(monkeypatch):
    provider = LLMProviderConfig(
        id="openrouter-test",
        kind="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="secret",
        models=[],
    )
    monkeypatch.setattr(
        models_route,
        "get_settings",
        lambda: SimpleNamespace(llm_providers=[provider]),
    )

    async def discover(_provider):
        return [compatible_openrouter_row()]

    async def profile(_provider, model):
        model.supports_tools = True
        model.input_modalities = ["text", "image"]
        model.last_test_passed = True
        model.last_test_results = {"text": {"passed": True, "elapsed_ms": 12}}
        return model.last_test_results

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    monkeypatch.setattr(models_route, "_profile_provider_model", profile)

    response = await models_route.profile_llm_provider_model(
        "openrouter-test",
        models_route.ProviderModelProfileRequest(model_id="google/gemma-4-31b-it"),
    )

    assert response["model"]["model_vendor"] == "google"
    assert response["model"]["supports_tools"] is True
    assert response["model"]["input_modalities"] == ["text", "image"]
    assert provider.models == []


@pytest.mark.asyncio
async def test_model_prompt_settings_are_persisted_per_model(monkeypatch):
    saved = {}
    runtime_settings = SimpleNamespace(llm_model_prompts={})
    monkeypatch.setattr(
        settings_route,
        "get_settings",
        lambda: runtime_settings,
    )
    monkeypatch.setattr(
        settings_route,
        "patch_global_section",
        lambda key, value: saved.update({key: value}),
    )

    response = await settings_route.update_model_prompt(
        settings_route.UpdateModelPromptRequest(
            model="stimma:minimax-m3",
            content_policy_enabled=False,
            extra_system_prompt="Use terse answers.",
        )
    )

    assert saved["llm_model_prompts"] == {
        "stimma:minimax-m3": {
            "content_policy_enabled": False,
            "extra_system_prompt": "Use terse answers.",
        }
    }
    assert response["model"] == "stimma:minimax-m3"
    assert runtime_settings.llm_model_prompts["stimma:minimax-m3"].extra_system_prompt == "Use terse answers."


@pytest.mark.asyncio
async def test_content_policy_preview_uses_effective_policy(monkeypatch):
    import content_policy

    async def effective_policy():
        return "Policy text used in requests."

    monkeypatch.setattr(content_policy, "get_content_policy", effective_policy)

    assert await settings_route.read_content_policy() == {
        "text": "Policy text used in requests.",
    }


@pytest.mark.asyncio
async def test_branded_add_fails_if_provider_removed_a_model(monkeypatch):
    monkeypatch.setattr(models_route, "get_settings", lambda: SimpleNamespace(llm_providers=[]))

    async def discover(_provider):
        return [{"id": "gpt-5.6-luna"}]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    with pytest.raises(Exception) as caught:
        await models_route.create_llm_provider(
            models_route.ProviderCreateRequest(kind="openai", api_key="secret")
        )
    assert "Provider does not offer" in caught.value.detail

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
from llm_provider_catalog import branded_models, canonical_model_id, discovered_model
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
        tour_seen_version=0,
    )
    monkeypatch.setattr(settings_route, "_has_cloud_balance", lambda: False)
    monkeypatch.setattr(
        settings_route, "_has_local_agent_llm_configured", lambda _s: False
    )

    readiness = settings_route._compute_readiness(settings)

    assert readiness.wizard_version == settings_route.SETUP_WIZARD_VERSION
    assert readiness.wizard_seen_version == 0
    assert readiness.tour_version == settings_route.FIRST_RUN_TOUR_VERSION
    assert readiness.tour_seen_version == 0


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
async def test_mark_tour_seen_persists_current_version(monkeypatch):
    runtime_settings = SimpleNamespace(tour_seen_version=0)
    persisted = []
    monkeypatch.setattr(settings_route, "get_settings", lambda: runtime_settings)
    monkeypatch.setattr(
        settings_route,
        "patch_global_section",
        lambda section, value: persisted.append((section, value)),
    )

    result = await settings_route.mark_tour_seen()

    assert persisted == [
        ("tour_seen_version", settings_route.FIRST_RUN_TOUR_VERSION)
    ]
    assert runtime_settings.tour_seen_version == settings_route.FIRST_RUN_TOUR_VERSION
    assert result["tour_seen_version"] == settings_route.FIRST_RUN_TOUR_VERSION


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
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6.1-terra",
        "gpt-6-luna",
    ]
    assert openai[0].reasoning.levels == ["low", "medium", "high", "xhigh", "max"]
    assert openai[0].reasoning.quick_task == "low"
    assert openai[0].reasoning.mode == "required"
    assert openai[0].model_vendor == "openai"

    anthropic = branded_models("anthropic", "anthropic-test")
    assert [model.model_id for model in anthropic] == [
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-fable-5-2",
        "claude-haiku-5-5",
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

    chat = llm_resolver._get_provider_model_config(model.id, role='agent')
    assert chat is not None
    assert chat.reasoning_level == "xhigh"
    assert chat.content_policy_enabled is True
    assert chat.extra_system_prompt == "Keep answers concise."

    quick = llm_resolver._get_provider_model_config(model.id, role='quick_task')
    assert quick is not None
    assert quick.reasoning_level == "low"


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

    resolved = llm_resolver._get_provider_model_config(model.id, role='agent')
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
        get_role_model_slug=lambda _role, profile_id=None: model.id,
        get_role_effort=lambda _role, profile_id=None: None,
        llm_providers=[provider],
        llm_reasoning_levels={},
        llm_content_policy="stimma",
        llm_extra_system_prompt="",
        get_llm_role_config=lambda _role: LLMRoleConfig(source="auto"),
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    # This scenario explicitly has no cloud fallback; do not inherit a cached
    # cloud account from other tests or a developer's source-build settings.
    async def cloud_unavailable():
        return False
    monkeypatch.setattr(llm_resolver, "_cloud_is_available", cloud_unavailable)

    # A provider whose last test failed offers no candidates, so the saved slug
    # stands and the user is told which provider is broken rather than being
    # silently moved onto something else.
    with pytest.raises(llm_resolver.LLMUnavailableError, match="OpenAI is unavailable"):
        await llm_resolver.get_effective_llm_config("quick_task")


@pytest.mark.asyncio
async def test_quick_tasks_respect_explicit_legacy_local_endpoint(monkeypatch):
    endpoint = LLMEndpointConfig(url="http://localhost:1234/v1", model="local-model")
    settings = SimpleNamespace(
        get_role_model_slug=lambda _role, profile_id=None: "local",
        get_role_effort=lambda _role, profile_id=None: None,
        llm_providers=[],
        get_llm_role_config=lambda _role: LLMRoleConfig(source="auto", endpoint=endpoint),
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)

    assert await llm_resolver.get_effective_llm_config("quick_task") is endpoint


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
    assert llm_resolver._cloud_reasoning_fields("stimma:test", role='agent')[
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


def test_local_profile_preserves_detected_reasoning_effort_levels():
    passed = SimpleNamespace(passed=True)
    model = LLMProviderModelConfig(id="local:m", model_id="m", name="M")
    models_route._apply_local_profile(
        model,
        {"tools": passed, "vision": passed},
        SimpleNamespace(
            reasoning_method="reasoning_effort",
            reasoning_mode="toggleable",
            reasoning_levels=["low", "medium", "xhigh"],
        ),
    )
    assert model.reasoning.levels == ["off", "low", "medium", "xhigh"]
    assert model.reasoning.default == "xhigh"
    assert model.reasoning.wire_levels == {
        "off": "none", "low": "low", "medium": "medium", "xhigh": "xhigh",
    }


@pytest.mark.asyncio
async def test_profile_retries_provider_advertised_effort_when_high_is_unsupported(monkeypatch):
    import llm

    calls = []

    async def completion(*_args, **kwargs):
        extra = kwargs.get("extra_body") or {}
        calls.append(extra)
        if extra.get("reasoning_effort") == "high":
            request = httpx.Request("POST", "http://studio.local/v1/chat/completions")
            response = httpx.Response(400, request=request, json={
                "error": {"message": "Unexpected reasoning effort high. Supported types are xhigh (default), medium, and low."}
            })
            raise httpx.HTTPStatusError("rejected", request=request, response=response)
        thinking = "worked it out" if extra.get("reasoning_effort") == "xhigh" else None
        tool_calls = [SimpleNamespace(name="get_weather")] if kwargs.get("tools") else []
        return SimpleNamespace(
            content="answer", thinking=thinking, tool_calls=tool_calls,
            _raw=None, usage=SimpleNamespace(prompt_tokens=10),
        )

    monkeypatch.setattr(llm, "llm_completion", completion)
    scenarios, detected = await settings_route._profile_endpoint(
        LLMEndpointConfig(url="http://studio.local/v1", model="m", max_context_tokens=1024)
    )

    assert scenarios["thinking"].passed is True
    assert detected.reasoning_method == "reasoning_effort"
    assert detected.reasoning_levels == ["low", "medium", "xhigh"]
    assert {"reasoning_effort": "xhigh"} in calls
    assert {"reasoning_effort": "none"} in calls


@pytest.mark.parametrize(
    ("kind", "model_id", "expected"),
    [
        ("openai", "gpt-6.1-sol", "openai:gpt-6.1-sol"),
        ("chatgpt", "gpt-6.1-sol", "openai:gpt-6.1-sol"),
        ("openrouter", "openai/gpt-6.1-sol", "openai:gpt-6.1-sol"),
        ("openrouter", "x-ai/grok-4.5", "xai:grok-4.5"),
        ("openrouter", "minimax/minimax-m3", "minimax:minimax-m3"),
        ("openrouter", "qwen/qwen3.7-plus", "qwen:qwen-3.7-plus"),
        ("openrouter", "moonshotai/kimi-k2.7-code", "moonshot:kimi-k2.7"),
        ("openrouter", "moonshotai/kimi-k2.7", "moonshot:kimi-k2.7"),
        ("together", "MiniMaxAI/MiniMax-M3", "minimax:minimax-m3"),
        ("together", "Qwen/Qwen3.7-Plus", "qwen:qwen-3.7-plus"),
        ("fireworks", "accounts/fireworks/models/glm-5p2", "zai:glm-5.2"),
        ("fireworks", "accounts/fireworks/models/glm-5p3-flash", "zai:glm-5.3-flash"),
        (
            "fireworks",
            "accounts/fireworks/models/qwen3p8-flash-next-fp8",
            "qwen:qwen-3.8-flash-next",
        ),
        (
            "fireworks",
            "accounts/fireworks/models/qwen3p8-flash-next-nvfp4",
            "qwen:qwen-3.8-flash-next",
        ),
    ],
)
def test_duplicate_routes_share_canonical_identity(kind, model_id, expected):
    assert canonical_model_id(kind, model_id) == expected


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

    haiku = branded_models("anthropic", "anthropic-test")[-1]
    config.reasoning_control = haiku.reasoning.control
    config.reasoning_level = "off"
    config.reasoning_default = haiku.reasoning.default
    config.reasoning_quick_task = haiku.reasoning.quick_task
    config.reasoning_wire_levels = haiku.reasoning.wire_levels
    assert _apply_endpoint_reasoning(config, None, None) == {
        "thinking": {"type": "disabled"}
    }


def test_reasoning_effort_repairs_stale_boolean_wire_value():
    config = SimpleNamespace(
        extra_body=None,
        reasoning_control="openai_effort",
        reasoning_level="off",
        reasoning_default="medium",
        reasoning_quick_task="off",
        reasoning_wire_levels={
            "off": False, "low": "low", "medium": "medium", "high": "high",
        },
    )

    assert _apply_endpoint_reasoning(config, None, None) == {
        "reasoning_effort": "none"
    }


@pytest.mark.asyncio
async def test_adding_openai_key_checks_models_and_stores_branded_contracts(monkeypatch):
    settings = SimpleNamespace(llm_providers=[])
    saved = []

    monkeypatch.setattr(models_route, "get_settings", lambda: settings)
    monkeypatch.setattr(models_route, "_save_providers", lambda providers, *_: saved.extend(providers))

    async def discover(_provider):
        return [{"id": model_id} for model_id in ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna")]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    response = await models_route.create_llm_provider(
        models_route.ProviderCreateRequest(kind="openai", api_key="secret")
    )
    assert response["api_key"] == "***"
    assert response["api_key_set"] is True
    assert [model["model_id"] for model in response["models"]] == [
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6.1-terra",
        "gpt-6-luna",
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
    monkeypatch.setattr(models_route, "_save_providers", lambda providers, *_: saved.extend(providers))

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
    monkeypatch.setattr(models_route, "_save_providers", lambda _providers, *_: None)

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
    monkeypatch.setattr(models_route, "_save_providers", lambda _providers, *_: None)

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
        return [{"id": "gpt-6-luna"}]

    monkeypatch.setattr(models_route, "_discover_provider_models", discover)
    with pytest.raises(Exception) as caught:
        await models_route.create_llm_provider(
            models_route.ProviderCreateRequest(kind="openai", api_key="secret")
        )
    assert "Provider does not offer" in caught.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("effort_off", ["reasoning", "empty", "answer"])
async def test_profile_classifies_the_verified_off_method(monkeypatch, effort_off):
    import llm
    from llm_http import _Obj

    async def completion(*_args, **kwargs):
        extra = kwargs.get("extra_body") or {}
        is_off_probe = extra.get("reasoning_effort") == "none"
        message = {"content": "Hidden work</think>answer"}
        if is_off_probe and effort_off == "empty":
            message = {"content": ""}
        elif is_off_probe and effort_off == "answer":
            message = {"content": "answer"}
        if kwargs.get("tools"):
            message["tool_calls"] = [{"id": "call1", "function": {"name": "get_weather", "arguments": "{}"}}]
        return llm._normalize_response(_Obj({
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10},
        }))

    monkeypatch.setattr(llm, "llm_completion", completion)
    _, detected = await settings_route._profile_endpoint(
        LLMEndpointConfig(url="http://localhost:1234/v1", model="test", max_context_tokens=1024)
    )
    assert detected.reasoning_method == "reasoning_effort"
    assert detected.reasoning_mode == ("toggleable" if effort_off == "answer" else "always")


def test_saved_openai_provider_gains_astra_and_migrates_retired_models():
    provider = LLMProviderConfig.model_validate({
        "id": "saved", "kind": "openai", "name": "OpenAI",
        "base_url": "https://api.openai.com/v1", "api_key": "test",
        "models": [{"id": "saved:gpt-5.6-sol", "model_id": "gpt-5.6-sol",
                    "name": "Old Sol", "enabled": False,
                    "extra_system_prompt": "Keep this instruction"}],
    })
    assert [m.model_id for m in provider.models] == ["gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"]
    assert provider.models[0].reasoning.mode == "required"
    assert provider.models[1].enabled is False
    assert provider.models[1].extra_system_prompt == "Keep this instruction"


@pytest.mark.asyncio
async def test_stale_chatgpt_catalog_refreshes_from_account(monkeypatch):
    provider = LLMProviderConfig(id="plan", kind="chatgpt", name="ChatGPT",
        base_url="https://chatgpt.com/backend-api/codex",
        models=[LLMProviderModelConfig(id="plan:gpt-5.6-sol", model_id="gpt-5.6-sol", name="Old Sol")])
    monkeypatch.setattr(models_route, "get_settings", lambda: SimpleNamespace(llm_providers=[provider]))
    import chatgpt_auth
    monkeypatch.setattr(chatgpt_auth, "is_signed_in", lambda: True)
    async def token():
        return "test-token"
    calls = []
    async def sync(access_token):
        calls.append(access_token)
    monkeypatch.setattr(chatgpt_auth, "get_access_token", token)
    monkeypatch.setattr(models_route, "_sync_chatgpt_provider", sync)
    monkeypatch.setattr(models_route, "_chatgpt_catalog_refreshed", set())
    await models_route._refresh_stale_chatgpt_catalog()
    assert calls == ["test-token"]


def test_llm_complete_text_supports_enable_thinking():
    import inspect
    from llm import llm_complete_text
    params = inspect.signature(llm_complete_text).parameters
    assert "enable_thinking" in params
    assert params["enable_thinking"].default is False  # off unless asked


# --- A local server that stops serving a saved model -----------------------

def _served_local_model(provider_id: str, model_id: str) -> LLMProviderModelConfig:
    """A model that passed its profile tests, as the add-model flow saves it."""
    return LLMProviderModelConfig(
        id=f"{provider_id}:{model_id}",
        model_id=model_id,
        name=model_id,
        input_modalities=["text", "image"],
        supports_tools=True,
        reasoning=LLMReasoningConfig(
            mode="optional",
            levels=["off", "high"],
            default="high",
            control="enable_thinking",
            wire_levels={"off": False, "high": True},
        ),
        last_test_passed=True,
        last_test_results={
            scenario: {"passed": True}
            for scenario in models_route.REQUIRED_MODEL_PROFILE_SCENARIOS
        },
    )


def _local_provider(**overrides) -> LLMProviderConfig:
    data = dict(
        id="local-gpu",
        kind="local",
        name="gpu-box:8000",
        base_url="http://gpu-box:8000/v1",
        models=[_served_local_model("local-gpu", "old-model")],
        last_test_passed=True,
    )
    data.update(overrides)
    return LLMProviderConfig(**data)


@pytest.fixture
def provider_runtime(monkeypatch):
    """Shared runtime settings for the provider routes and the resolver,
    with the model server, cloud and config file stubbed out."""
    import firebase_auth

    runtime = SimpleNamespace(
        llm_providers=[],
        llm_reasoning_levels={},
        llm_model_prompts={},
        llm_content_policy="stimma",
        llm_extra_system_prompt="",
        llms={},
        cloud=SimpleNamespace(base_url="https://cloud.example"),
        get_role_model_slug=lambda _role, profile_id=None: "auto",
        get_role_effort=lambda _role, profile_id=None: None,
        get_llm_role_config=lambda _role: LLMRoleConfig(source="auto"),
    )
    saved = []
    served = {"models": ["old-model"], "reachable": True}

    real_async_client = httpx.AsyncClient

    async def model_server(request):
        served.setdefault("requests", []).append(request)
        if served.get("while_asked"):
            # Something else happens while the server is being asked.
            await served["while_asked"]()
        if not served["reachable"]:
            raise httpx.ConnectError("Connection refused", request=request)
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200, json={"data": [{"id": model_id} for model_id in served["models"]]}
        )

    async def profile(_provider, model):
        model.last_test_passed = True
        model.last_error = None
        return {"text": {"passed": True}}

    async def no_cloud_token():
        return None

    async def cloud_unavailable():
        return False

    monkeypatch.setattr(models_route, "get_settings", lambda: runtime)
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: runtime)
    monkeypatch.setattr(
        models_route, "patch_global_section", lambda section, value: saved.append(value)
    )
    monkeypatch.setattr(
        models_route.httpx,
        "AsyncClient",
        lambda: real_async_client(transport=httpx.MockTransport(model_server)),
    )
    # Profiling sends real chat requests; its scenarios are covered above.
    monkeypatch.setattr(models_route, "_profile_provider_model", profile)
    monkeypatch.setattr(models_route, "is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)
    monkeypatch.setattr(llm_resolver, "_cloud_is_available", cloud_unavailable)
    return SimpleNamespace(settings=runtime, served=served, saved=saved)


def _available(payload, slug):
    return next(model for model in payload["models"] if model["slug"] == slug)


@pytest.mark.asyncio
async def test_check_with_missing_model_marks_only_that_model(provider_runtime):
    provider = _local_provider(models=[
        _served_local_model("local-gpu", "old-model"),
        _served_local_model("local-gpu", "other-model"),
    ])
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["other-model", "new-model"]

    result = await models_route.test_llm_provider("local-gpu")

    assert result["status"] == "ready"
    assert result["missing_models"] == ["old-model"]
    assert "old-model" in result["detail"]
    assert list(result["model_checks"]) == ["other-model"]
    assert provider.last_test_passed is True
    assert provider.last_error is None
    by_id = {model.model_id: model for model in provider.models}
    assert by_id["old-model"].served is False
    assert by_id["other-model"].served is True

    payload = await models_route.get_available_models()
    old = _available(payload, "local-gpu:old-model")
    assert old["available"] is False
    assert old["status"] == "not_served"
    assert _available(payload, "local-gpu:other-model")["available"] is True


@pytest.mark.asyncio
async def test_swapping_the_served_model_leaves_a_clean_usable_provider(provider_runtime):
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["new-model"]

    await models_route.test_llm_provider("local-gpu")
    response = await models_route.update_llm_provider(
        "local-gpu",
        models_route.ProviderUpdateRequest(models=[
            _served_local_model("local-gpu", "new-model").model_dump(),
        ]),
    )

    assert response["last_test_passed"] is True
    assert response["last_error"] is None
    assert [model["model_id"] for model in response["models"]] == ["new-model"]
    payload = await models_route.get_available_models()
    new = _available(payload, "local-gpu:new-model")
    assert new["available"] is True
    assert new["status"] == "available"
    assert not any(model["slug"] == "local-gpu:old-model" for model in payload["models"])

    config = await llm_resolver.get_chat_llm_config("local-gpu:new-model")
    assert config.model == "new-model"
    assert config.url == "http://gpu-box:8000/v1"
    # `auto` finds it too, since it is the only usable model.
    auto = await llm_resolver.get_effective_llm_config("quick_task")
    assert auto.model == "new-model"


@pytest.mark.asyncio
async def test_resolver_names_a_saved_model_the_server_no_longer_serves(provider_runtime):
    old = _served_local_model("local-gpu", "old-model")
    old.served = False
    provider_runtime.settings.llm_providers = [_local_provider(models=[old])]

    with pytest.raises(llm_resolver.LLMUnavailableError, match="no longer serves old-model"):
        await llm_resolver.get_chat_llm_config("local-gpu:old-model")


@pytest.mark.asyncio
async def test_saved_provider_failed_on_a_missing_model_heals(provider_runtime):
    # How earlier builds left config.yaml after the served model was swapped.
    stored = _local_provider().model_dump()
    stored.update(
        last_test_passed=False,
        last_error="Model no longer available: old-model.",
    )
    provider = LLMProviderConfig.model_validate(stored)
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["new-model"]

    assert provider.last_test_passed is None
    assert provider.last_error is None
    assert provider.models[0].served is False

    response = await models_route.update_llm_provider(
        "local-gpu",
        models_route.ProviderUpdateRequest(models=[
            _served_local_model("local-gpu", "new-model").model_dump(),
        ]),
    )

    assert response["last_test_passed"] is not False
    assert response["last_error"] is None
    payload = await models_route.get_available_models()
    assert _available(payload, "local-gpu:new-model")["available"] is True
    assert provider_runtime.saved[-1][0]["last_error"] is None


def test_saved_provider_with_a_real_failure_is_not_healed():
    provider = _local_provider(last_test_passed=False, last_error="Connection refused.")

    assert provider.last_test_passed is False
    assert provider.last_error == "Connection refused."


@pytest.mark.asyncio
async def test_unreachable_provider_still_fails_as_a_whole(provider_runtime):
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["reachable"] = False

    with pytest.raises(models_route.HTTPException, match="Could not reach"):
        await models_route.test_llm_provider("local-gpu")

    assert provider.last_test_passed is False
    assert provider.last_error == "Could not reach gpu-box:8000."
    payload = await models_route.get_available_models()
    old = _available(payload, "local-gpu:old-model")
    assert old["available"] is False
    assert old["status"] == "provider_unavailable"
    with pytest.raises(llm_resolver.LLMUnavailableError, match="gpu-box:8000 is unavailable"):
        await llm_resolver.get_chat_llm_config("local-gpu:old-model")


@pytest.mark.asyncio
async def test_pointing_a_provider_at_another_server_saves_and_marks_missing_models(provider_runtime):
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["new-model"]

    response = await models_route.update_llm_provider(
        "local-gpu",
        models_route.ProviderUpdateRequest(base_url="http://other-gpu:8000/v1"),
    )

    assert response["base_url"] == "http://other-gpu:8000/v1"
    assert response["last_test_passed"] is True
    assert response["models"][0]["served"] is False


@pytest.mark.asyncio
async def test_pointing_a_provider_at_an_unreachable_server_is_refused(provider_runtime):
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["reachable"] = False

    with pytest.raises(models_route.HTTPException, match="Could not reach"):
        await models_route.update_llm_provider(
            "local-gpu",
            models_route.ProviderUpdateRequest(base_url="http://other-gpu:8000/v1"),
        )

    assert provider.base_url == "http://gpu-box:8000/v1"
    assert provider_runtime.saved == []


@pytest.mark.asyncio
async def test_provider_changes_are_broadcast(provider_runtime, monkeypatch):
    import asyncio

    events = []

    async def broadcast(event, data, include_profile=True):
        events.append((event, include_profile))

    monkeypatch.setattr(models_route.ws_manager, "broadcast", broadcast)
    provider_runtime.settings.llm_providers = [_local_provider()]

    await models_route.test_llm_provider("local-gpu")
    await asyncio.sleep(0)

    assert events == [("llm_providers_updated", False)]


# --- The swap offer: what a local server serves now ------------------------

@pytest.fixture(autouse=True)
def no_cached_discoveries():
    models_route._served_cache.clear()
    yield
    models_route._served_cache.clear()


def _broadcasts(monkeypatch) -> list:
    events = []

    async def broadcast(event, data, include_profile=True):
        events.append(event)

    monkeypatch.setattr(models_route.ws_manager, "broadcast", broadcast)
    return events


async def _probe():
    import asyncio

    result = await models_route.probe_llm_providers()
    await asyncio.sleep(0)  # let a broadcast task run
    return {provider["id"]: provider for provider in result["providers"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("serving, missing, unadded", [
    # One saved model gone, one new one served: a one-step switch.
    (["new-model"], ["old-model"], ["new-model"]),
    # Several new ones: the person picks.
    (["new-model", "step-3.7", "qwen-3.8-flash-next"], ["old-model"],
     ["new-model", "step-3.7", "qwen-3.8-flash-next"]),
    # Nothing else served.
    ([], ["old-model"], []),
    # Healthy.
    (["old-model"], [], []),
])
async def test_served_report_on_a_local_provider(provider_runtime, serving, missing, unadded):
    provider_runtime.settings.llm_providers = [_local_provider()]
    provider_runtime.served["models"] = serving

    probed = await _probe()
    listed = await models_route.list_llm_providers()

    for payload in (probed["local-gpu"], listed["providers"][0]):
        assert payload["served"]["missing"] == missing
        assert [row["id"] for row in payload["served"]["unadded"]] == unadded
        assert all(set(row) == {"id", "name", "context_length"} for row in payload["served"]["unadded"])


@pytest.mark.asyncio
async def test_served_report_without_a_discovery_has_no_offer(provider_runtime):
    old = _served_local_model("local-gpu", "old-model")
    old.served = False
    provider_runtime.settings.llm_providers = [_local_provider(models=[old])]

    listed = await models_route.list_llm_providers()

    assert listed["providers"][0]["served"] == {"missing": ["old-model"], "unadded": []}


@pytest.mark.asyncio
async def test_served_report_is_for_local_providers_only(provider_runtime):
    provider_runtime.settings.llm_providers = [LLMProviderConfig(
        id="openrouter-test", kind="openrouter", name="OpenRouter",
        base_url="https://openrouter.ai/api/v1", api_key="secret",
    )]

    listed = await models_route.list_llm_providers()

    assert "served" not in listed["providers"][0]


@pytest.mark.asyncio
async def test_served_report_forgets_another_servers_models(provider_runtime):
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["old-model", "new-model"]
    await _probe()

    provider.base_url = "http://other-gpu:8000/v1"
    listed = await models_route.list_llm_providers()

    assert listed["providers"][0]["served"]["unadded"] == []


@pytest.mark.asyncio
async def test_deleting_a_provider_drops_its_discovery(provider_runtime):
    provider_runtime.settings.llm_providers = [_local_provider()]
    provider_runtime.served["models"] = ["old-model", "new-model"]
    await _probe()
    assert "local-gpu" in models_route._served_cache

    await models_route.delete_llm_provider("local-gpu")

    assert "local-gpu" not in models_route._served_cache


@pytest.mark.asyncio
async def test_probe_updates_flags_saves_and_broadcasts_on_change(provider_runtime, monkeypatch):
    events = _broadcasts(monkeypatch)
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["new-model"]

    probed = await _probe()

    assert provider.models[0].served is False
    assert probed["local-gpu"]["models"][0]["served"] is False
    assert len(provider_runtime.saved) == 1
    assert provider_runtime.saved[0][0]["models"][0]["served"] is False
    assert events == ["llm_providers_updated"]
    # A probe asks briefly, unlike Check connection.
    timeout = provider_runtime.served["requests"][-1].extensions["timeout"]
    assert timeout["read"] == models_route.PROBE_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_probe_with_nothing_changed_writes_nothing(provider_runtime, monkeypatch):
    events = _broadcasts(monkeypatch)
    provider_runtime.settings.llm_providers = [_local_provider()]
    provider_runtime.served["models"] = ["old-model", "new-model"]

    probed = await _probe()

    assert provider_runtime.saved == []
    assert events == []
    assert probed["local-gpu"]["served"]["unadded"][0]["id"] == "new-model"


@pytest.mark.asyncio
async def test_probe_of_an_unreachable_server_changes_nothing(provider_runtime, monkeypatch):
    events = _broadcasts(monkeypatch)
    provider = _local_provider()
    provider_runtime.settings.llm_providers = [provider]
    provider_runtime.served["models"] = ["old-model", "new-model"]
    await _probe()
    provider_runtime.served["reachable"] = False

    probed = await _probe()

    assert provider.last_test_passed is True
    assert provider.last_error is None
    assert provider.models[0].served is True
    assert provider_runtime.saved == []
    assert events == []
    # What it served when last asked still stands.
    assert probed["local-gpu"]["served"]["unadded"][0]["id"] == "new-model"


@pytest.mark.asyncio
async def test_probe_skips_disabled_and_hosted_providers(provider_runtime):
    provider_runtime.settings.llm_providers = [
        _local_provider(enabled=False),
        LLMProviderConfig(
            id="openai-test", kind="openai", name="OpenAI",
            base_url="https://api.openai.com/v1", api_key="secret",
        ),
    ]
    provider_runtime.served["models"] = ["new-model"]

    await _probe()

    assert provider_runtime.served.get("requests", []) == []
    assert provider_runtime.saved == []


@pytest.mark.asyncio
async def test_probe_applies_flags_to_the_provider_list_saved_meanwhile(provider_runtime):
    import asyncio

    provider_runtime.settings.llm_providers = [_local_provider()]
    provider_runtime.served["models"] = ["new-model"]
    renamed = _local_provider(name="Renamed meanwhile")

    async def another_save():
        provider_runtime.settings.llm_providers = [renamed]
        await asyncio.sleep(0)

    provider_runtime.served["while_asked"] = another_save

    await _probe()

    saved = provider_runtime.saved[-1]
    assert saved[0]["name"] == "Renamed meanwhile"
    assert saved[0]["models"][0]["served"] is False
    assert renamed.models[0].served is False


@pytest.mark.asyncio
async def test_concurrent_probes_save_once(provider_runtime):
    import asyncio

    provider_runtime.settings.llm_providers = [_local_provider()]
    provider_runtime.served["models"] = ["new-model"]

    await asyncio.gather(_probe(), _probe())

    assert len(provider_runtime.saved) == 1


# --- Replacing a model in one save ----------------------------------------

def _replace_request(new_model_id="new-model", replaces=None, models=None):
    new = _served_local_model("local-gpu", new_model_id)
    return models_route.ProviderUpdateRequest(
        models=[new.model_dump()] if models is None else models,
        replaces=replaces if replaces is not None else {
            "local-gpu:old-model": f"local-gpu:{new_model_id}",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("request_kwargs, detail", [
    ({"models": None}, "needs the new model list"),
    ({"replaces": {"local-gpu:gone-model": "local-gpu:new-model"}}, "Model not found"),
    ({"replaces": {"local-gpu:old-model": "local-gpu:other-model"}}, "not in the model list"),
])
async def test_replace_validation(provider_runtime, request_kwargs, detail):
    provider_runtime.settings.llm_providers = [_local_provider()]
    if request_kwargs.get("models", ...) is None:
        request = models_route.ProviderUpdateRequest(
            replaces={"local-gpu:old-model": "local-gpu:new-model"},
        )
    else:
        request = _replace_request(**request_kwargs)

    with pytest.raises(models_route.HTTPException, match=detail) as raised:
        await models_route.update_llm_provider("local-gpu", request)

    assert raised.value.status_code == 400
    assert provider_runtime.saved == []


@pytest.mark.asyncio
async def test_replace_refuses_an_old_model_kept_in_the_list(provider_runtime):
    old = _served_local_model("local-gpu", "old-model")
    provider_runtime.settings.llm_providers = [_local_provider(models=[old])]
    new = _served_local_model("local-gpu", "new-model")

    with pytest.raises(models_route.HTTPException, match="still in the model list"):
        await models_route.update_llm_provider("local-gpu", models_route.ProviderUpdateRequest(
            models=[old.model_dump(), new.model_dump()],
            replaces={"local-gpu:old-model": "local-gpu:new-model"},
        ))
    assert provider_runtime.saved == []


@pytest.mark.asyncio
async def test_replace_keeps_the_rule_that_a_new_model_passed_its_tests(provider_runtime):
    provider_runtime.settings.llm_providers = [_local_provider()]
    untested = _served_local_model("local-gpu", "new-model")
    untested.last_test_passed = None

    with pytest.raises(models_route.HTTPException, match="must pass its tests"):
        await models_route.update_llm_provider("local-gpu", _replace_request(
            models=[untested.model_dump()],
        ))
    assert provider_runtime.saved == []


# --- A replace repoints saved choices (real config file and database) -----

def _model_with_levels(provider_id: str, model_id: str, levels: list[str]) -> LLMProviderModelConfig:
    model = _served_local_model(provider_id, model_id)
    model.reasoning = LLMReasoningConfig(
        mode="optional", levels=levels, default=levels[-1],
        control="reasoning_effort", wire_levels={level: level for level in levels},
    )
    return model


OLD = "local-gpu:old-model"
NEW = "local-gpu:new-model"
OTHER = "other-gpu:step-3.7"


@pytest.fixture
async def swap_app(test_app, client, monkeypatch):
    """The real app, config file and profile database, with a local provider
    serving old-model (levels off/low/high) and an unrelated one."""
    import firebase_auth
    from config import get_settings

    if not any(getattr(route, "path", "") == "/api/models/providers/{provider_id}" for route in test_app.routes):
        test_app.include_router(models_route.router)

    async def no_cloud_token():
        return None

    async def cloud_unavailable():
        return False

    monkeypatch.setattr(models_route, "is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr("privacy_lockdown.is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", no_cloud_token)
    monkeypatch.setattr(llm_resolver, "_cloud_is_available", cloud_unavailable)

    models_route._save_providers([
        _local_provider(models=[_model_with_levels("local-gpu", "old-model", ["off", "low", "high"])]),
        LLMProviderConfig(
            id="other-gpu", kind="local", name="other-gpu:8000",
            base_url="http://other-gpu:8000/v1",
            models=[_model_with_levels("other-gpu", "step-3.7", ["off", "high"])],
            last_test_passed=True,
        ),
    ])
    settings = get_settings()
    settings.llm_reasoning_levels = {}
    settings.llm_model_prompts = {}
    yield SimpleNamespace(client=client, settings=settings)
    await client.patch("/api/settings/agent", json={"models": {
        role: {"model": "auto", "effort": None} for role in ("quick_task", "tool_assistant", "chat", "flow")
    }})
    models_route._save_providers([])


async def _swap(client, levels=("off", "high")):
    """Replace old-model with new-model, which offers `levels`."""
    new = _model_with_levels("local-gpu", "new-model", list(levels))
    response = await client.patch("/api/models/providers/local-gpu", json={
        "models": [new.model_dump()],
        "replaces": {OLD: NEW},
    })
    assert response.status_code == 200, response.text
    assert [model["id"] for model in response.json()["models"]] == [NEW]
    return response.json()


@pytest.mark.asyncio
async def test_replace_repoints_profile_role_selections(swap_app):
    import yaml
    import app_dirs

    client = swap_app.client
    await client.patch("/api/settings/agent", json={"models": {
        "chat": {"model": OLD, "effort": "low"},       # new-model has no "low"
        "tool_assistant": {"model": OLD, "effort": "high"},
        "quick_task": {"model": OLD, "effort": "off"},
        "flow": {"model": OTHER, "effort": "high"},
    }})

    await _swap(client)

    models = (await client.get("/api/settings/agent")).json()["models"]
    assert models["chat"] == {"model": NEW, "effort": None}
    assert models["tool_assistant"] == {"model": NEW, "effort": "high"}
    assert models["quick_task"] == {"model": NEW, "effort": "off"}
    assert models["flow"] == {"model": OTHER, "effort": "high"}
    persisted = yaml.safe_load(app_dirs.get_config_path().read_text())
    assert persisted["profiles"][0]["agent"]["models"]["chat"] == {"model": NEW, "effort": None}
    from config import reload_settings
    reloaded = reload_settings().get_agent_for_profile("default").models
    assert (reloaded.quick_task.model, reloaded.quick_task.effort) == (NEW, "off")


@pytest.mark.asyncio
async def test_replace_repoints_project_role_overrides(swap_app):
    client = swap_app.client
    pinned = (await client.post("/api/projects", json={
        "name": "Pinned",
        "chat_model_slug": OLD, "chat_effort": "low",
        "tool_assistant_model_slug": OLD, "tool_assistant_effort": "high",
        "flow_model_slug": OTHER, "flow_effort": "high",
    })).json()
    unrelated = (await client.post("/api/projects", json={
        "name": "Unrelated", "chat_model_slug": OTHER, "chat_effort": "off",
    })).json()

    await _swap(client)

    project = (await client.get(f"/api/projects/{pinned['id']}")).json()
    assert (project["chat_model_slug"], project["chat_effort"]) == (NEW, None)
    assert (project["tool_assistant_model_slug"], project["tool_assistant_effort"]) == (NEW, "high")
    assert (project["flow_model_slug"], project["flow_effort"]) == (OTHER, "high")
    other = (await client.get(f"/api/projects/{unrelated['id']}")).json()
    assert (other["chat_model_slug"], other["chat_effort"]) == (OTHER, "off")


@pytest.mark.asyncio
async def test_replace_repoints_chat_model_selections(swap_app):
    client = swap_app.client
    kept = (await client.post("/api/chats", json={"name": "Kept effort", "model_slug": OLD})).json()
    await client.patch(f"/api/chats/{kept['id']}", json={"reasoning_effort": "high"})
    dropped = (await client.post("/api/chats", json={"name": "Dropped effort", "model_slug": OLD})).json()
    await client.patch(f"/api/chats/{dropped['id']}", json={"reasoning_effort": "low"})
    unrelated = (await client.post("/api/chats", json={"name": "Unrelated", "model_slug": OTHER})).json()
    await client.patch(f"/api/chats/{unrelated['id']}", json={"reasoning_effort": "high"})

    await _swap(client)

    chat = (await client.get(f"/api/chats/{kept['id']}")).json()
    assert (chat["model_slug"], chat["reasoning_effort"]) == (NEW, "high")
    chat = (await client.get(f"/api/chats/{dropped['id']}")).json()
    assert (chat["model_slug"], chat["reasoning_effort"]) == (NEW, None)
    chat = (await client.get(f"/api/chats/{unrelated['id']}")).json()
    assert (chat["model_slug"], chat["reasoning_effort"]) == (OTHER, "high")


@pytest.mark.asyncio
async def test_replace_repoints_frozen_user_tools(swap_app, db_session):
    from sqlalchemy import select
    from database import UserTool

    async with db_session() as session:
        pinned = UserTool(name="Pinned tool", program_text="x", model_slug=OLD)
        unrelated = UserTool(name="Unrelated tool", program_text="x", model_slug=OTHER)
        session.add_all([pinned, unrelated])
        await session.commit()
        ids = (pinned.id, unrelated.id)

    await _swap(swap_app.client)

    async with db_session() as session:
        rows = {
            tool.id: tool.model_slug
            for tool in (await session.execute(select(UserTool).where(UserTool.id.in_(ids)))).scalars()
        }
    assert rows == {ids[0]: NEW, ids[1]: OTHER}


@pytest.mark.asyncio
async def test_replace_moves_per_model_reasoning_levels(swap_app):
    client = swap_app.client
    assert (await client.patch("/api/settings/model-reasoning", json={"model": OLD, "level": "off"})).status_code == 200
    assert (await client.patch("/api/settings/model-reasoning", json={"model": OTHER, "level": "high"})).status_code == 200

    await _swap(client)

    assert swap_app.settings.llm_reasoning_levels == {OTHER: "high", NEW: "off"}
    levels = (await client.get("/api/settings")).json()["llm_reasoning_levels"]
    assert levels == {OTHER: "high", NEW: "off"}
    # The file keeps `off` unquoted, which YAML 1.1 reads as False.
    from config import reload_settings
    assert reload_settings().llm_reasoning_levels == {OTHER: "high", NEW: "off"}


@pytest.mark.asyncio
async def test_replace_drops_a_per_model_level_the_new_model_lacks(swap_app):
    client = swap_app.client
    await client.patch("/api/settings/model-reasoning", json={"model": OLD, "level": "low"})

    await _swap(client)

    assert OLD not in swap_app.settings.llm_reasoning_levels
    assert NEW not in swap_app.settings.llm_reasoning_levels


@pytest.mark.asyncio
async def test_replace_moves_per_model_prompt_settings(swap_app):
    client = swap_app.client
    await client.patch("/api/settings/model-prompt", json={
        "model": OLD, "content_policy_enabled": False, "extra_system_prompt": "Be brief.",
    })
    await client.patch("/api/settings/model-prompt", json={
        "model": OTHER, "content_policy_enabled": True, "extra_system_prompt": "Other.",
    })

    await _swap(client)

    prompts = (await client.get("/api/settings")).json()["llm_model_prompts"]
    assert OLD not in prompts
    assert prompts[NEW]["content_policy_enabled"] is False
    assert prompts[NEW]["extra_system_prompt"] == "Be brief."
    assert prompts[OTHER]["extra_system_prompt"] == "Other."


@pytest.mark.asyncio
async def test_after_a_replace_the_new_model_is_offered_and_resolves_old_pins(swap_app):
    from core.profile_context import ProfileScope

    client = swap_app.client
    await client.patch("/api/settings/agent", json={"models": {"chat": {"model": OLD, "effort": None}}})

    swapped = await _swap(client)

    assert swapped["served"] == {"missing": [], "unadded": []}
    available = (await client.get("/api/models/available")).json()["models"]
    new = next(model for model in available if model["slug"] == NEW)
    assert new["available"] is True
    assert new["status"] == "available"
    assert not any(model["slug"] == OLD for model in available)
    with ProfileScope("default"):
        config = await llm_resolver.get_effective_llm_config("chat")
    assert config.model == "new-model"
    assert config.url == "http://gpu-box:8000/v1"


@pytest.mark.asyncio
async def test_a_failed_database_repoint_saves_nothing_and_can_be_retried(swap_app, monkeypatch):
    import llm_model_repoint
    from config import get_settings

    client = swap_app.client
    chat = (await client.post("/api/chats", json={"name": "Pinned", "model_slug": OLD})).json()
    await client.patch("/api/settings/agent", json={"models": {"chat": {"model": OLD, "effort": None}}})
    real = llm_model_repoint._repoint_profile_database
    failures = [RuntimeError("database is locked")]

    async def flaky(profile_id, replaces, levels):
        if failures:
            raise failures.pop()
        return await real(profile_id, replaces, levels)

    monkeypatch.setattr(llm_model_repoint, "_repoint_profile_database", flaky)
    new = _model_with_levels("local-gpu", "new-model", ["off", "high"])
    request = {"models": [new.model_dump()], "replaces": {OLD: NEW}}

    response = await client.patch("/api/models/providers/local-gpu", json=request)

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not update saved model choices. Try again."
    provider = next(p for p in get_settings().llm_providers if p.id == "local-gpu")
    assert [model.id for model in provider.models] == [OLD]
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["model_slug"] == OLD
    assert (await client.get("/api/settings/agent")).json()["models"]["chat"]["model"] == OLD

    response = await client.patch("/api/models/providers/local-gpu", json=request)

    assert response.status_code == 200, response.text
    assert [model["id"] for model in response.json()["models"]] == [NEW]
    assert (await client.get(f"/api/chats/{chat['id']}")).json()["model_slug"] == NEW
    assert (await client.get("/api/settings/agent")).json()["models"]["chat"]["model"] == NEW


@pytest.mark.asyncio
async def test_a_replace_is_broadcast_once_with_its_mapping_after_the_repoint(swap_app, monkeypatch):
    import asyncio

    steps = []

    async def broadcast(event, data, include_profile=True):
        steps.append((event, data))

    real_databases = models_route.repoint_profile_databases
    real_config = models_route.repoint_config_selections

    async def databases(replaces, levels):
        result = await real_databases(replaces, levels)
        steps.append("databases")
        return result

    def config(replaces, levels):
        result = real_config(replaces, levels)
        steps.append("config")
        return result

    monkeypatch.setattr(models_route.ws_manager, "broadcast", broadcast)
    monkeypatch.setattr(models_route, "repoint_profile_databases", databases)
    monkeypatch.setattr(models_route, "repoint_config_selections", config)

    await _swap(swap_app.client)
    await asyncio.sleep(0)

    assert steps == ["databases", "config", ("llm_providers_updated", {"replaces": {OLD: NEW}})]

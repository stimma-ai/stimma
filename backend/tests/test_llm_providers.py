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

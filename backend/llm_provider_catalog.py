"""Static contracts for branded BYO LLM integrations.

Dynamic providers (OpenRouter and local servers) can discover model IDs, but
their reasoning behavior is not inferred from names. Branded integrations use
these checked contracts so their controls work immediately after a key is added.
"""
from __future__ import annotations

from typing import Any

from config import LLMProviderModelConfig, LLMReasoningConfig


PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"name": "Anthropic", "base_url": "https://api.anthropic.com/v1"},
    "xai": {"name": "xAI", "base_url": "https://api.x.ai/v1"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    "local": {"name": "Local endpoint", "base_url": "http://localhost:1234/v1"},
}


def _reasoning(
    mode: str,
    levels: list[str],
    default: str,
    quick_task: str,
    control: str,
    wire_levels: dict[str, Any],
) -> LLMReasoningConfig:
    return LLMReasoningConfig(
        mode=mode,
        levels=levels,
        default=default,
        quick_task=quick_task,
        control=control,
        wire_levels=wire_levels,
    )


OPENAI_REASONING = _reasoning(
    "optional",
    ["off", "low", "medium", "high", "xhigh"],
    "medium",
    "off",
    "openai_effort",
    {"off": "none", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh"},
)


BRANDED_MODELS: dict[str, list[dict[str, Any]]] = {
    "openai": [
        {"model_id": "gpt-5.6-sol", "name": "GPT-5.6 Sol", "context": 1_050_000, "reasoning": OPENAI_REASONING},
        {"model_id": "gpt-5.6-terra", "name": "GPT-5.6 Terra", "context": 1_050_000, "reasoning": OPENAI_REASONING},
        {"model_id": "gpt-5.6-luna", "name": "GPT-5.6 Luna", "context": 1_050_000, "reasoning": OPENAI_REASONING},
    ],
    "anthropic": [
        {
            "model_id": "claude-sonnet-5", "name": "Claude Sonnet 5", "context": 1_000_000,
            "reasoning": _reasoning(
                "optional", ["off", "low", "medium", "high", "xhigh", "max"],
                "high", "off", "anthropic_adaptive_default",
                {"off": "off", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            "model_id": "claude-opus-4-8", "name": "Claude Opus 4.8", "context": 1_000_000,
            "reasoning": _reasoning(
                "optional", ["off", "low", "medium", "high", "xhigh", "max"],
                "high", "off", "anthropic_adaptive_optional",
                {"off": "off", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            "model_id": "claude-fable-5", "name": "Claude Fable 5", "context": 1_000_000,
            "reasoning": _reasoning(
                "required", ["low", "medium", "high", "xhigh", "max"],
                "high", "low", "anthropic_adaptive_required",
                {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            "model_id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "context": 200_000,
            "reasoning": _reasoning(
                "optional", ["off", "low", "medium", "high"], "off", "off",
                "anthropic_budget_tokens", {"off": 0, "low": 1024, "medium": 4096, "high": 16384},
            ),
        },
    ],
    "xai": [
        {
            "model_id": "grok-4.5", "name": "Grok 4.5", "context": 500_000,
            "reasoning": _reasoning(
                "required", ["low", "medium", "high"], "high", "low",
                "openai_effort", {"low": "low", "medium": "medium", "high": "high"},
            ),
        },
    ],
}


def branded_models(kind: str, provider_id: str) -> list[LLMProviderModelConfig]:
    return [
        LLMProviderModelConfig(
            id=f"{provider_id}:{row['model_id']}",
            model_id=row["model_id"],
            name=row["name"],
            max_context_tokens=row["context"],
            input_modalities=["text", "image"],
            supports_tools=True,
            reasoning=row["reasoning"],
        )
        for row in BRANDED_MODELS.get(kind, [])
    ]


def discovered_model(
    provider_id: str,
    model_id: str,
    *,
    name: str | None = None,
) -> LLMProviderModelConfig:
    return LLMProviderModelConfig(
        id=f"{provider_id}:{model_id}",
        model_id=model_id,
        name=name or model_id,
        reasoning=LLMReasoningConfig(
            mode="none",
            levels=["off"],
            default="off",
            quick_task="off",
            control="none",
            wire_levels={"off": "off"},
        ),
    )

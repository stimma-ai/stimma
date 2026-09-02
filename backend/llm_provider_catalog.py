"""Static contracts for branded BYO LLM integrations.

Dynamic providers (OpenRouter, Together AI, Fireworks AI, and local servers)
discover model IDs instead of carrying a curated list. Branded integrations use
checked contracts so their controls work immediately after a key is added.
"""
from __future__ import annotations

from typing import Any

from config import LLMProviderModelConfig, LLMReasoningConfig


PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1"},
    # Signed in with a ChatGPT subscription instead of an API key. Kept a
    # separate kind from "openai" on purpose: different billing, different
    # model availability, and only this one can be rate-limited by plan.
    "chatgpt": {"name": "ChatGPT", "base_url": "https://chatgpt.com/backend-api/codex"},
    "anthropic": {"name": "Anthropic", "base_url": "https://api.anthropic.com/v1"},
    "google": {"name": "Google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "xai": {"name": "xAI", "base_url": "https://api.x.ai/v1"},
    "together": {"name": "Together AI", "base_url": "https://api.together.xyz/v1"},
    "fireworks": {"name": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    "local": {"name": "Local endpoint", "base_url": "http://localhost:1234/v1"},
}


FIXED_MODEL_PROVIDERS = {"openai", "anthropic", "google", "xai"}
PROFILED_MODEL_PROVIDERS = {"openrouter", "together", "fireworks", "local"}
# Its catalog comes from the signed-in ChatGPT account, so it is neither a
# fixed branded list nor something we may probe with test completions (every
# probe spends the user's plan quota).
OAUTH_MODEL_PROVIDERS = {"chatgpt"}


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


GEMINI_REASONING = _reasoning(
    "required",
    ["minimal", "low", "medium", "high"],
    "medium",
    "minimal",
    "openai_effort",
    {"minimal": "minimal", "low": "low", "medium": "medium", "high": "high"},
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
            "model_id": "claude-opus-5", "name": "Claude Opus 5", "context": 1_000_000,
            "reasoning": _reasoning(
                "optional", ["off", "low", "medium", "high", "xhigh", "max"],
                "high", "off", "anthropic_adaptive_default",
                {"off": "off", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            # Succeeds Claude Fable 5 in the same tier at the same price. Like
            # its predecessor it always thinks: there is no off rung, and both
            # thinking:disabled and budget_tokens are rejected outright.
            "model_id": "claude-fable-5-1", "name": "Claude Fable 5.1", "context": 1_000_000,
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
    "google": [
        {
            "model_id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash",
            "context": 1_048_576, "reasoning": GEMINI_REASONING,
        },
        {
            "model_id": "gemini-3.1-pro-preview", "name": "Gemini 3.1 Pro",
            "context": 1_048_576,
            "reasoning": _reasoning(
                "required", ["low", "medium", "high"], "medium", "low",
                "openai_effort", {"low": "low", "medium": "medium", "high": "high"},
            ),
        },
        {
            "model_id": "gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite",
            "context": 1_048_576, "reasoning": GEMINI_REASONING,
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


# Only the gpt-5.6 family is offered on the ChatGPT-plan route. A plan may also
# list older families (5.5, 5.4, 5.4-mini) and the Codex-only 5.3 Spark, but
# each additional family is another effort ladder to keep verified against an
# undocumented surface, and they are superseded for every role Stimma uses.
# Restricting the route keeps one ladder true instead of four drifting ones.
CHATGPT_SUPPORTED_PREFIXES = ("gpt-5.6",)

# Efforts for the supported family, hardcoded because the catalog does not
# report them. Verified against api.openai.com on 2026-08-30 by sending a
# valid-but-unsupported effort and reading the per-model rejection:
#
#   gpt-5.6-sol/terra/luna   none, low, medium, high, xhigh, max
#
# 'minimal' appears in the API's global validator list but is rejected by every
# model in this generation, so it is not offered. 'max' is a 5.6 rung — older
# families reject it, which is part of why they are not exposed here.
#
# Anything added to CHATGPT_SUPPORTED_PREFIXES must have its ladder re-verified;
# offering a rung a model rejects is an HTTP 400 on send.
CHATGPT_REASONING_LEVELS = ["off", "low", "medium", "high", "xhigh", "max"]
CHATGPT_REASONING_WIRE = {
    "off": "none",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}
# Wire value -> Stimma level, for reading a reported default back.
_CHATGPT_WIRE_TO_LEVEL = {wire: level for level, wire in CHATGPT_REASONING_WIRE.items()}


def is_supported_chatgpt_model(model_id: str) -> bool:
    """Whether a slug from the plan's catalog is one Stimma exposes."""
    return str(model_id).lower().startswith(CHATGPT_SUPPORTED_PREFIXES)


def chatgpt_model(
    provider_id: str,
    entry: dict[str, Any],
) -> LLMProviderModelConfig:
    """Build a model config from one ``codex/models`` catalog entry."""
    model_id = str(entry["id"])
    reported = [
        _CHATGPT_WIRE_TO_LEVEL.get(str(effort).strip().lower())
        for effort in (entry.get("reasoning_efforts") or [])
    ]
    levels = [
        level for level in CHATGPT_REASONING_LEVELS if level in reported
    ] or list(CHATGPT_REASONING_LEVELS)
    default_effort = _CHATGPT_WIRE_TO_LEVEL.get(
        str(entry.get("default_reasoning_effort") or "").strip().lower()
    )
    if default_effort not in levels:
        default_effort = "medium" if "medium" in levels else levels[0]
    # Quick tasks (auto-title, captioning, prompt enhancement) run on the
    # cheapest rung available — they spend the same plan quota as a chat turn,
    # so they must not default to deep reasoning.
    quick_task = levels[0]
    context = entry.get("context_length")
    return LLMProviderModelConfig(
        id=f"{provider_id}:{model_id}",
        model_id=model_id,
        name=str(entry.get("name") or model_id),
        model_vendor="openai",
        max_context_tokens=int(context) if context else 272_000,
        input_modalities=["text", "image"],
        supports_tools=True,
        reasoning=_reasoning(
            # "optional" because the ladder includes an off rung, matching how
            # the same models behave on the API-key route.
            "optional" if "off" in levels else "required",
            levels,
            default_effort,
            quick_task,
            "openai_effort",
            {level: CHATGPT_REASONING_WIRE[level] for level in levels},
        ),
    )


def branded_models(kind: str, provider_id: str) -> list[LLMProviderModelConfig]:
    return [
        LLMProviderModelConfig(
            id=f"{provider_id}:{row['model_id']}",
            model_id=row["model_id"],
            name=row["name"],
            model_vendor={
                "openai": "openai", "anthropic": "anthropic",
                "google": "gemini", "xai": "xai",
            }.get(kind),
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
    normalized_id = model_id.lower()
    model_vendor = next((vendor for needle, vendor in (
        ("anthropic/", "anthropic"), ("claude", "anthropic"),
        ("openai/", "openai"), ("gpt-", "openai"),
        ("x-ai/", "xai"), ("grok", "xai"),
        ("minimax", "minimax"), ("moonshot", "kimi"), ("kimi", "kimi"),
        ("qwen", "alibaba"), ("stepfun", "stepfun"), ("step-", "stepfun"),
        ("z-ai", "zai"), ("zhipu", "zai"), ("glm", "zai"),
        ("google/", "google"), ("gemma", "google"),
        ("gemini", "gemini"),
        ("deepseek", "deepseek"),
        ("nvidia", "nvidia"), ("nemotron", "nvidia"),
        ("meta-llama", "meta"), ("llama", "meta"),
        ("mistral", "mistral"), ("mixtral", "mistral"),
    ) if needle in normalized_id), None)
    return LLMProviderModelConfig(
        id=f"{provider_id}:{model_id}",
        model_id=model_id,
        name=name or model_id,
        model_vendor=model_vendor,
        reasoning=LLMReasoningConfig(
            mode="none",
            levels=["off"],
            default="off",
            quick_task="off",
            control="none",
            wire_levels={"off": "off"},
        ),
    )

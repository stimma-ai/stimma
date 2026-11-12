"""Static contracts for branded BYO LLM integrations.

Dynamic providers (OpenRouter, Together AI, Fireworks AI, and local servers)
discover model IDs instead of carrying a curated list. Branded integrations use
checked contracts so their controls work immediately after a key is added.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

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
# Resellers: their model IDs name the upstream vendor rather than themselves.
AGGREGATOR_MODEL_PROVIDERS = {"openrouter", "together", "fireworks"}
# The route kind of a model served by the user's Stimma account.
STIMMA_ROUTE = "stimma"


def canonical_model_id(kind: str, model_id: str) -> str:
    """The underlying model, independent of which account serves it."""
    # A ChatGPT plan runs the same OpenAI models an API key does.
    if kind == "chatgpt":
        return f"openai:{model_id}"
    if kind not in AGGREGATOR_MODEL_PROVIDERS:
        return f"{kind}:{model_id}"
    known = {
        "minimax/minimax-m3": "minimax:minimax-m3",
        "minimaxai/minimax-m3": "minimax:minimax-m3",
        "qwen/qwen3.7-plus": "qwen:qwen-3.7-plus",
        "moonshotai/kimi-k2.7-code": "moonshot:kimi-k2.7",
        "moonshotai/kimi-k2.7": "moonshot:kimi-k2.7",
        "stepfun/step-3.7-flash": "stepfun:step-3.7-flash",
        "accounts/fireworks/models/kimi-k2p6": "moonshot:kimi-k2.6",
        "accounts/fireworks/models/glm-5p1": "zai:glm-5.1",
        "accounts/fireworks/models/glm-5p2": "zai:glm-5.2",
        "accounts/fireworks/models/glm-5p3-flash": "zai:glm-5.3-flash",
        "accounts/fireworks/models/qwen3p8-flash-next-fp8": "qwen:qwen-3.8-flash-next",
        "accounts/fireworks/models/qwen3p8-flash-next-nvfp4": "qwen:qwen-3.8-flash-next",
        "accounts/fireworks/models/gpt-oss-120b": "openai:gpt-oss-120b",
        "accounts/fireworks/models/deepseek-v4-pro": "deepseek:deepseek-v4-pro",
    }
    normalized = model_id.lower()
    if normalized in known:
        return known[normalized]
    if "/" not in model_id:
        return f"{kind}:{model_id}"
    upstream, upstream_model = model_id.split("/", 1)
    upstream = {
        "minimaxai": "minimax", "moonshotai": "moonshot",
        "qwen": "qwen", "zai-org": "zai", "x-ai": "xai",
    }.get(upstream.lower(), upstream.lower())
    return f"{upstream}:{upstream_model}"


def _route_rank(kind: str) -> int:
    """Whose account serves a model when several can: the plan already paid for,
    then the user's own key (direct before reseller), then Stimma credits."""
    if kind == "chatgpt":
        return 0
    if kind in AGGREGATOR_MODEL_PROVIDERS:
        return 2
    if kind == STIMMA_ROUTE:
        return 3
    return 1


def shadowed_routes(routes: Iterable[tuple[str, Optional[str], str]]) -> dict[str, str]:
    """Map each losing route's slug to the slug that serves the same model better.

    ``routes`` holds (slug, canonical model id, route kind) for usable routes only,
    so a broken provider never hides a working one. Local servers stay out of it:
    two machines serving the same model name are still two different machines.
    """
    best: dict[str, tuple[int, str]] = {}
    contenders = [
        (slug, canonical_id, _route_rank(kind))
        for slug, canonical_id, kind in routes
        if canonical_id and kind != "local"
    ]
    for slug, canonical_id, rank in contenders:
        if canonical_id not in best or rank < best[canonical_id][0]:
            best[canonical_id] = (rank, slug)
    return {
        slug: best[canonical_id][1]
        for slug, canonical_id, _rank in contenders
        if best[canonical_id][1] != slug
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
    ["off", "low", "medium", "high", "xhigh", "max"],
    "medium",
    "off",
    "openai_effort",
    {"off": "none", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
)

ASTRA_REASONING = _reasoning(
    "required",
    ["low", "medium", "high", "xhigh", "max"],
    "medium",
    "low",
    "openai_effort",
    {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
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
        {"model_id": "gpt-6-astra", "name": "GPT-6 Astra", "context": 1_050_000, "reasoning": ASTRA_REASONING},
        {"model_id": "gpt-6.1-sol", "name": "GPT-6.1 Sol", "context": 1_050_000, "reasoning": ASTRA_REASONING},
        {"model_id": "gpt-6.1-terra", "name": "GPT-6.1 Terra", "context": 1_050_000, "reasoning": OPENAI_REASONING},
        {"model_id": "gpt-6-luna", "name": "GPT-6 Luna", "context": 1_050_000, "reasoning": OPENAI_REASONING},
    ],
    "anthropic": [
        {
            # Rejects thinking:disabled, so there is no off rung.
            "model_id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5", "context": 1_000_000,
            "reasoning": _reasoning(
                "required", ["low", "medium", "high", "xhigh", "max"],
                "high", "low", "anthropic_adaptive_required",
                {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            "model_id": "claude-opus-5-5", "name": "Claude Opus 5.5", "context": 1_000_000,
            "reasoning": _reasoning(
                "required", ["low", "medium", "high", "xhigh", "max"],
                "medium", "low", "anthropic_adaptive_required",
                {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            # Always thinks: there is no off rung, and both thinking:disabled
            # and budget_tokens are rejected outright.
            "model_id": "claude-fable-5-2", "name": "Claude Fable 5.2", "context": 1_000_000,
            "reasoning": _reasoning(
                "required", ["low", "medium", "high", "xhigh", "max"],
                "high", "low", "anthropic_adaptive_required",
                {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
            ),
        },
        {
            # Adaptive thinking with effort, like the other Claude 5 models;
            # a manual thinking budget is rejected. Thinking can be turned off.
            "model_id": "claude-haiku-5-5", "name": "Claude Haiku 5.5", "context": 1_000_000,
            "reasoning": _reasoning(
                "optional", ["off", "low", "medium", "high", "xhigh", "max"],
                "medium", "off", "anthropic_adaptive_default",
                {"off": "off", "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max"},
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


# Only Astra, Sol, and Luna are offered on the ChatGPT-plan route. A plan may also
# list older families (5.5, 5.4, 5.4-mini) and the Codex-only 5.3 Spark, but
# each additional family is another effort ladder to keep verified against an
# undocumented surface, and they are superseded for every role Stimma uses.
# Restricting the route keeps one ladder true instead of four drifting ones.
CHATGPT_SUPPORTED_PREFIXES = ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna")

# Supported effort ladders from the official model contracts. The plan catalog
# may narrow these per account. Astra and Sol require thinking; Terra and Luna permit off.
# Keep these aligned with the API contracts above.
CHATGPT_REASONING_LEVELS = ["off", "low", "medium", "high", "xhigh", "max"]
CHATGPT_REASONING_WIRE = {
    "off": "none",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}
CHATGPT_ASTRA_REASONING_LEVELS = ["low", "medium", "high", "xhigh", "max"]
CHATGPT_MODEL_DEFAULTS: tuple[tuple[str, list[str], int], ...] = (
    ("gpt-6-astra", CHATGPT_ASTRA_REASONING_LEVELS, 1_050_000),
    ("gpt-6.1-sol", CHATGPT_ASTRA_REASONING_LEVELS, 1_050_000),
    ("gpt-6.1-terra", CHATGPT_REASONING_LEVELS, 1_050_000),
    ("gpt-6-luna", CHATGPT_REASONING_LEVELS, 1_050_000),
)
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
    normalized_id = model_id.lower()
    default_levels, default_context = next(
        (
            (levels, context)
            for prefix, levels, context in CHATGPT_MODEL_DEFAULTS
            if normalized_id.startswith(prefix)
        ),
        (CHATGPT_REASONING_LEVELS, 272_000),
    )
    reported = [
        _CHATGPT_WIRE_TO_LEVEL.get(str(effort).strip().lower())
        for effort in (entry.get("reasoning_efforts") or [])
    ]
    levels = [
        level for level in default_levels if level in reported
    ] or list(default_levels)
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
        max_context_tokens=int(context) if context else default_context,
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

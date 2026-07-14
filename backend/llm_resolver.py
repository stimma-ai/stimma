"""
LLM configuration resolver.

Resolves the effective LLM configuration for a role, handling
the two source types: stimma_cloud and endpoint.
"""
import os
from typing import Optional

from config import LEGACY_LLM_MODEL_SLUGS, get_settings, LLMEndpointConfig
from core.logging import get_logger

log = get_logger(__name__)

# Type alias for configs that can be passed to llm_http
LLMEffectiveConfig = LLMEndpointConfig


def normalize_model_slug(model_slug: Optional[str]) -> Optional[str]:
    """Return the current catalog slug for a retired saved alias."""
    return LEGACY_LLM_MODEL_SLUGS.get(model_slug, model_slug)


def _acceptance_llm_config(role: str) -> Optional[LLMEndpointConfig]:
    """Deterministic in-process LLM used by the acceptance lane."""
    if not os.environ.get("STIMMA_TEST_PROVIDER"):
        return None
    return LLMEndpointConfig(
        url="stimma://acceptance-llm",
        model=f"acceptance-{role}",
        api_key="dummy",
        max_context_tokens=32_000,
        content_policy_enabled=False,
        reasoning_method="none",
    )


class LLMUnavailableError(Exception):
    """Raised when an LLM surface cannot resolve to a usable backend."""

    code = "llm_unavailable"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.code = code or self.code
        self.status_code = status_code or self.status_code


class LLMNotConfiguredError(LLMUnavailableError):
    """Raised when no LLM backend is available (no cloud auth, no local endpoint)."""

    code = "llm_not_configured"


class LLMInsufficientBalanceError(LLMUnavailableError):
    """Raised when the user is signed in but has no spendable balance."""

    code = "llm_insufficient_balance"


async def get_effective_llm_config(role: str) -> LLMEffectiveConfig:
    """Get the effective LLM config for a role.

    This is the main entry point for getting LLM configurations. It handles:
    - 'stimma_cloud': Resolves to cloud endpoint with Firebase auth
    - 'endpoint': Returns the custom endpoint config

    Falls back only when the role source is explicitly set to "auto".

    Args:
        role: The LLM role ('agent', 'agent-fast')

    Returns:
        Config object with get_model(), get_api_key(), get_api_base() methods

    Raises:
        ValueError: If no valid config is available for the role
    """
    acceptance_config = _acceptance_llm_config(role)
    if acceptance_config:
        return acceptance_config

    settings = get_settings()
    selected_slug = normalize_model_slug(
        getattr(settings, "quick_task_model", "auto")
        if role == "agent-fast"
        else getattr(settings, "default_model", "auto")
    )
    provider_config = _get_provider_model_config(
        selected_slug,
        quick_task=role == "agent-fast",
    )
    if provider_config:
        return provider_config
    provider = _provider_for_model_slug(selected_slug)
    if provider:
        raise LLMUnavailableError(
            f"{provider.name} is unavailable. Check it in Settings > AI Services or choose another model.",
            code="llm_provider_unavailable",
        )
    if selected_slug == "local":
        role_config = settings.get_llm_role_config(role)
        if role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        raise LLMNotConfiguredError(
            "No local LLM server is configured. Add one in Settings > AI Services.",
            code="llm_local_missing",
        )
    if selected_slug.startswith("stimma:"):
        cloud_config = await _get_stimma_cloud_config(
            _resolve_catalog_alias(selected_slug, role),
            max_context_tokens=get_max_context_tokens(selected_slug),
            quick_task=role == "agent-fast",
        )
        if cloud_config:
            return cloud_config
        await _raise_cloud_llm_error(model_slug=selected_slug)
    role_config = settings.get_llm_role_config(role)

    # For role-based entry points the caller only has a role (agent /
    # agent-fast), not a catalog slug. Use the default slug's context size
    # when falling back to cloud — it's what get_chat_llm_config('auto')
    # lands on anyway.
    default_slug_context = get_max_context_tokens('stimma:minimax-m3')

    if role_config.source == 'auto':
        cloud_config = await _get_stimma_cloud_config(
            role, max_context_tokens=default_slug_context, quick_task=role == "agent-fast"
        )
        if cloud_config:
            return cloud_config
        if role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        await _raise_cloud_llm_error()

    if role_config.source == 'stimma_cloud':
        cloud_config = await _get_stimma_cloud_config(
            role, max_context_tokens=default_slug_context, quick_task=role == "agent-fast"
        )
        if cloud_config:
            return cloud_config
        await _raise_cloud_llm_error()

    if role_config.source == 'endpoint' and role_config.endpoint and role_config.endpoint.url:
        return role_config.endpoint

    _raise_no_llm_error()


async def _get_stimma_cloud_config(
    role: str,
    *,
    max_context_tokens: Optional[int] = None,
    quick_task: bool = False,
) -> Optional[LLMEndpointConfig]:
    """Get Stimma Cloud LLM configuration.

    Args:
        role: The LLM role to use as the model name (already alias-resolved).
        max_context_tokens: Context window stamped onto the returned config.
            Caller is expected to resolve this from the catalog slug before
            dispatching to alias; defaults to the cap when not provided.

    Returns:
        LLMEndpointConfig for Stimma Cloud, or None if not authenticated
    """
    from privacy_lockdown import is_privacy_lockdown_enabled

    if is_privacy_lockdown_enabled():
        log.debug("stimma cloud config skipped in Privacy Lockdown", role=role)
        return None

    from firebase_auth import get_valid_id_token

    settings = get_settings()

    try:
        id_token = await get_valid_id_token()
        if not id_token:
            log.debug("no valid id token for stimma cloud", role=role)
            return None

        # Skip cloud when the account has no balance (cloud will reject) so
        # 'auto' can fall through to a configured local endpoint.
        from auth_storage import load_auth_state
        auth_state = load_auth_state()
        if auth_state and (auth_state.get('credits') or 0) <= 0:
            log.debug("account has no balance, skipping cloud config", role=role)
            return None

        # Construct the Stimma Cloud LLM endpoint
        base_url = settings.cloud.base_url
        llm_url = f"{base_url}/api/llm/v1"

        log.debug("using stimma cloud llm", role=role, endpoint=llm_url)

        return LLMEndpointConfig(
            url=llm_url,
            model=role,  # alias (e.g. 'agent', 'agent-max')
            api_key=id_token,
            max_context_tokens=max_context_tokens if max_context_tokens is not None else MAX_CONTEXT_CAP,
            **_cloud_reasoning_fields(role, quick_task=quick_task),
        )
    except Exception as e:
        log.error("failed to get stimma cloud config", role=role, error=str(e))
        return None


def resolve_chat_model_slug(
    chat_model_slug: Optional[str],
    project_default_slug: Optional[str],
    global_default: Optional[str],
) -> str:
    """Three-level default resolution: chat -> project -> global.

    Privacy Lockdown excludes hosted models, so a saved cloud slug must behave
    like ``auto``.  ``auto`` still respects the normal resolver order and uses
    the configured local endpoint without contacting Stimma Cloud.
    """
    slug = normalize_model_slug(
        chat_model_slug or project_default_slug or global_default or 'stimma:minimax-m3'
    )

    from privacy_lockdown import is_privacy_lockdown_enabled

    if is_privacy_lockdown_enabled() and slug not in {'auto', 'local'}:
        settings = get_settings()
        for provider in getattr(settings, "llm_providers", []):
            if provider.kind == "local" and any(model.id == slug for model in provider.models):
                return slug
        return 'auto'
    return slug


# Client-side cap on context window, applied regardless of what the cloud
# advertises. Models can exceed this (Claude 1M, GPT 400k), but Stimma's
# agent workflows don't need more than 256k and capping keeps latency and
# cost predictable.
MAX_CONTEXT_CAP = 256_000

# Conservative default when we have no catalog info at all (unknown slug,
# cloud unreachable before first fetch).
_FALLBACK_CONTEXT = 128_000


# Cache of cloud model catalog entries (fetched from stimma cloud).
# Format: {slug: {agent_model: str, agent_fast_model: str, max_context_tokens: int}}
_catalog_cache: dict[str, dict] = {}

# Built-in fallback mappings so resolution works even before the cloud catalog
# is fetched. Must be kept in sync with MODEL_CATALOG in stimma-cloud config.ts.
_BUILTIN_CATALOG: dict[str, dict] = {
    'stimma:minimax-m3': {
        'agent_model': 'stimma:minimax-m3',
        'agent_fast_model': 'stimma:minimax-m3',
        'max_context_tokens': 512_000,
        'reasoning': {
            'mode': 'optional',
            'levels': ['off', 'high'],
            'default': 'high',
            'quick_task': 'off',
        },
    },
    'default':   {'agent_model': 'agent', 'agent_fast_model': 'agent-fast', 'max_context_tokens': 262_144},
    'agent-max': {'agent_model': 'agent-max', 'agent_fast_model': 'agent-fast', 'max_context_tokens': 262_144},
    'gpt54':     {'agent_model': 'agent-gpt54', 'agent_fast_model': 'agent-fast-gpt54mini', 'max_context_tokens': 400_000},
    'opus':      {'agent_model': 'agent-opus', 'agent_fast_model': 'agent-fast-haiku', 'max_context_tokens': 1_048_576},
    'sonnet':    {'agent_model': 'agent-sonnet', 'agent_fast_model': 'agent-fast-haiku', 'max_context_tokens': 1_048_576},
    'kimi-k2':   {'agent_model': 'agent-kimi-k2', 'agent_fast_model': 'agent-fast', 'max_context_tokens': 262_144},
}


def set_catalog_cache(entries: list[dict]) -> None:
    """Update the cached catalog entries (called by models route)."""
    global _catalog_cache
    _catalog_cache = {
        e['slug']: {
            'agent_model': e.get('agent_model', 'agent'),
            'agent_fast_model': e.get('agent_fast_model', 'agent-fast'),
            'max_context_tokens': int(e.get('max_context_tokens') or _FALLBACK_CONTEXT),
            'reasoning': e.get('reasoning') or {},
            'is_default': bool(e.get('is_default')),
        }
        for e in entries
    }


def get_known_catalog_slugs() -> set[str]:
    """Return cloud model slugs known from the live cache or built-in fallback."""
    return set(_BUILTIN_CATALOG.keys()) | set(_catalog_cache.keys())


def _lookup_catalog(slug: str) -> Optional[dict]:
    """Look up a catalog entry by slug (live cache first, then built-ins)."""
    return _catalog_cache.get(slug) or _BUILTIN_CATALOG.get(slug)


def _cloud_reasoning_fields(model_slug: str, *, quick_task: bool) -> dict:
    entry = _lookup_catalog(model_slug) or {}
    reasoning = entry.get("reasoning") or {}
    levels = reasoning.get("levels") or []
    if not levels:
        return {}
    settings = get_settings()
    requested_level = (
        reasoning.get("quick_task")
        if quick_task
        else settings.llm_reasoning_levels.get(model_slug, reasoning.get("default"))
    )
    level = requested_level if requested_level in levels else reasoning.get("default")
    if level not in levels:
        level = levels[0]
    return {
        "model_route_id": model_slug,
        "provider_kind": "stimma",
        "reasoning_level": level,
        "reasoning_default": reasoning.get("default"),
        "reasoning_quick_task": reasoning.get("quick_task"),
        "reasoning_control": "stimma_normalized",
        "reasoning_wire_levels": {item: item for item in levels},
    }


def get_max_context_tokens(model_slug: Optional[str]) -> int:
    """Return the (capped) context window for a catalog slug.

    Unknown or missing slugs fall through to a conservative default. The
    client-side cap (MAX_CONTEXT_CAP) is always applied — cloud can advertise
    more but we won't use it.
    """
    if not model_slug:
        return min(MAX_CONTEXT_CAP, _FALLBACK_CONTEXT)
    entry = _lookup_catalog(model_slug)
    raw = (entry or {}).get('max_context_tokens') or _FALLBACK_CONTEXT
    return min(MAX_CONTEXT_CAP, int(raw))


def _resolve_catalog_alias(slug: str, role: str) -> str:
    """Look up the model alias for a catalog slug + role.

    Checks the live cache first (populated from cloud), then falls back
    to built-in mappings.
    """
    key = f'{role}_model'
    entry = _lookup_catalog(slug)
    if entry:
        return entry.get(key, role)
    # Unknown slug — try using it as a direct alias
    return slug


def _auto_chat_catalog_slug() -> str:
    """Catalog slug used by legacy chat auto when Stimma Cloud is available."""
    return 'stimma:minimax-m3'


def _get_provider_model_config(
    model_slug: Optional[str],
    *,
    quick_task: bool,
) -> Optional[LLMEndpointConfig]:
    if not model_slug:
        return None
    settings = get_settings()
    for provider in getattr(settings, "llm_providers", []):
        if provider.deleted_at or not provider.enabled or provider.last_test_passed is False:
            continue
        for model in provider.models:
            if model.id != model_slug or not model.enabled:
                continue
            reasoning = model.reasoning
            selected_level = (
                reasoning.quick_task
                if quick_task
                else settings.llm_reasoning_levels.get(model.id, reasoning.default)
            )
            if selected_level not in reasoning.levels:
                selected_level = (
                    reasoning.default
                    if reasoning.default in reasoning.levels
                    else (reasoning.levels[0] if reasoning.levels else None)
                )
            global_prompt = settings.llm_extra_system_prompt.strip()
            model_prompt = model.extra_system_prompt.strip()
            return LLMEndpointConfig(
                url=provider.base_url,
                model=model.model_id,
                api_key=provider.api_key,
                max_context_tokens=min(MAX_CONTEXT_CAP, model.max_context_tokens),
                content_policy_enabled=settings.llm_content_policy == "stimma",
                extra_system_prompt="\n\n".join(
                    part for part in (global_prompt, model_prompt) if part
                ),
                extra_body=model.extra_body,
                provider_kind=provider.kind,
                model_route_id=model.id,
                reasoning_level=selected_level,
                reasoning_default=reasoning.default,
                reasoning_quick_task=reasoning.quick_task,
                reasoning_control=reasoning.control,
                reasoning_wire_levels=reasoning.wire_levels,
            )
    return None


def _provider_for_model_slug(model_slug: Optional[str]):
    if not model_slug:
        return None
    for provider in getattr(get_settings(), "llm_providers", []):
        if any(model.id == model_slug for model in provider.models):
            return provider
    return None


async def get_chat_llm_config(model_slug: Optional[str], role: str = 'agent') -> LLMEffectiveConfig:
    """Get LLM config for a chat message, respecting per-chat model selection.

    Args:
        model_slug: The resolved model slug (after default inheritance).
                    'local' means use configured local endpoint.
                    Anything else is a stimma cloud catalog slug.
        role: 'agent' or 'agent-fast'

    Returns:
        Config object with get_model(), get_api_key(), get_api_base() methods

    Raises:
        ValueError: If no valid config is available
    """
    acceptance_config = _acceptance_llm_config(role)
    if acceptance_config:
        return acceptance_config

    model_slug = normalize_model_slug(model_slug) or 'auto'

    provider_config = _get_provider_model_config(
        model_slug,
        quick_task=role == "agent-fast",
    )
    if provider_config:
        return provider_config
    provider = _provider_for_model_slug(model_slug)
    if provider:
        raise LLMUnavailableError(
            f"{provider.name} is unavailable. Check it in Settings > AI Services or choose another model.",
            code="llm_provider_unavailable",
        )

    if model_slug == 'auto':
        auto_slug = _auto_chat_catalog_slug()
        cloud_kwargs = {"max_context_tokens": get_max_context_tokens(auto_slug)}
        if role == "agent-fast":
            cloud_kwargs["quick_task"] = True
        cloud_config = await _get_stimma_cloud_config(
            _resolve_catalog_alias(auto_slug, role),
            **cloud_kwargs,
        )
        if cloud_config:
            return cloud_config
        settings = get_settings()
        role_config = settings.get_llm_role_config(role)
        if role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        await _raise_cloud_llm_error()

    if model_slug == 'local':
        settings = get_settings()
        role_config = settings.get_llm_role_config(role)
        if role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        raise LLMNotConfiguredError(
            "No local LLM server is configured. Add one in Settings > AI Services.",
            code="llm_local_missing",
        )

    # Cloud model — resolve catalog slug to model alias, carry catalog context
    alias = _resolve_catalog_alias(model_slug, role)
    cloud_config = await _get_stimma_cloud_config(
        alias,
        max_context_tokens=get_max_context_tokens(model_slug),
        quick_task=role == "agent-fast",
    )
    if cloud_config:
        return cloud_config

    await _raise_cloud_llm_error(model_slug=model_slug)


def _raise_no_llm_error() -> None:
    """Raise the appropriate error based on auth state."""
    from auth_storage import load_auth_state
    auth_state = load_auth_state()
    if auth_state and (auth_state.get('credits') or 0) <= 0:
        raise LLMInsufficientBalanceError(
            "Your Stimma account has no balance."
        )
    raise LLMNotConfiguredError(
        "No AI model is configured. Sign in to Stimma or add a local LLM server in AI Services."
    )


async def _raise_cloud_llm_error(model_slug: str | None = None) -> None:
    """Raise a typed error for an unavailable explicit cloud selection."""
    from auth_storage import load_auth_state
    from firebase_auth import get_valid_id_token

    auth_state = load_auth_state()
    if auth_state and (auth_state.get("credits") or 0) <= 0:
        raise LLMInsufficientBalanceError(
            "Your Stimma account has no balance."
        )

    try:
        id_token = await get_valid_id_token()
    except Exception:
        id_token = None

    if not id_token:
        raise LLMNotConfiguredError(
            "Sign in to Stimma or choose a local LLM.",
            code="llm_not_logged_in",
        )

    if model_slug:
        raise LLMNotConfiguredError(
            f"Cloud model '{model_slug}' is not available right now.",
            code="llm_cloud_unreachable",
            status_code=503,
        )
    raise LLMNotConfiguredError(
        "Stimma\u2019s cloud cannot be reached. Choose Local or try again later.",
        code="llm_cloud_unreachable",
        status_code=503,
    )


def get_effective_llm_config_sync(role: str) -> LLMEffectiveConfig:
    """Synchronous version of get_effective_llm_config.

    This is a convenience function for contexts where async is not available.
    It returns the endpoint config based on source, ignoring
    Stimma Cloud (since that requires async token refresh).

    Args:
        role: The LLM role ('agent', 'agent-fast')

    Returns:
        Config object with get_model(), get_api_key(), get_api_base() methods

    Raises:
        ValueError: If no config is available for the role
    """
    settings = get_settings()
    role_config = settings.get_llm_role_config(role)

    if role_config.source == 'endpoint' and role_config.endpoint:
        return role_config.endpoint

    # Fallback
    if role_config.endpoint and role_config.endpoint.url:
        return role_config.endpoint

    raise LLMNotConfiguredError(
        "No AI model is configured. Please sign in to Stimma Cloud or set up a local LLM endpoint in Settings > AI Services."
    )

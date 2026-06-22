"""
LLM configuration resolver.

Resolves the effective LLM configuration for a role, handling
the two source types: stimma_cloud and endpoint.
"""
import os
from typing import Optional

from config import get_settings, LLMEndpointConfig
from core.logging import get_logger

log = get_logger(__name__)

# Type alias for configs that can be passed to llm_http
LLMEffectiveConfig = LLMEndpointConfig


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


class LLMSubscriptionRequiredError(LLMUnavailableError):
    """Raised when user is signed in but on free tier (no LLM access)."""

    code = "llm_subscription_required"


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
    role_config = settings.get_llm_role_config(role)

    # For role-based entry points the caller only has a role (agent /
    # agent-fast), not a catalog slug. Use the default slug's context size
    # when falling back to cloud — it's what get_chat_llm_config('auto')
    # lands on anyway.
    default_slug_context = get_max_context_tokens('default')

    if role_config.source == 'auto':
        cloud_config = await _get_stimma_cloud_config(
            role, max_context_tokens=default_slug_context
        )
        if cloud_config:
            return cloud_config
        if role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        await _raise_cloud_llm_error()

    if role_config.source == 'stimma_cloud':
        cloud_config = await _get_stimma_cloud_config(
            role, max_context_tokens=default_slug_context
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

        # Check if user is on free tier (cloud will reject)
        from auth_storage import load_auth_state
        auth_state = load_auth_state()
        if auth_state and auth_state.get('tier') == 'free':
            log.debug("user is on free tier, skipping cloud config", role=role)
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
        )
    except Exception as e:
        log.error("failed to get stimma cloud config", role=role, error=str(e))
        return None


def resolve_chat_model_slug(
    chat_model_slug: Optional[str],
    project_default_slug: Optional[str],
    global_default: Optional[str],
) -> str:
    """Three-level default resolution: chat -> project -> global."""
    return chat_model_slug or project_default_slug or global_default or 'default'


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
        }
        for e in entries
    }


def get_known_catalog_slugs() -> set[str]:
    """Return cloud model slugs known from the live cache or built-in fallback."""
    return set(_BUILTIN_CATALOG.keys()) | set(_catalog_cache.keys())


def _lookup_catalog(slug: str) -> Optional[dict]:
    """Look up a catalog entry by slug (live cache first, then built-ins)."""
    return _catalog_cache.get(slug) or _BUILTIN_CATALOG.get(slug)


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
    return 'agent-max'


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

    if model_slug is None:
        model_slug = 'auto'

    if model_slug == 'auto':
        auto_slug = _auto_chat_catalog_slug()
        cloud_config = await _get_stimma_cloud_config(
            _resolve_catalog_alias(auto_slug, role),
            max_context_tokens=get_max_context_tokens(auto_slug),
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
            "No local LLM endpoint is configured. Set one up in Settings > Advanced.",
            code="llm_local_missing",
        )

    # Cloud model — resolve catalog slug to model alias, carry catalog context
    alias = _resolve_catalog_alias(model_slug, role)
    cloud_config = await _get_stimma_cloud_config(
        alias,
        max_context_tokens=get_max_context_tokens(model_slug),
    )
    if cloud_config:
        return cloud_config

    await _raise_cloud_llm_error(model_slug=model_slug)


def _raise_no_llm_error() -> None:
    """Raise the appropriate error based on auth state."""
    from auth_storage import load_auth_state
    auth_state = load_auth_state()
    if auth_state and auth_state.get('tier') == 'free':
        raise LLMSubscriptionRequiredError(
            "Your current plan doesn't include AI chat. Subscribe to Stimma Cloud to get started."
        )
    raise LLMNotConfiguredError(
        "No AI model is configured. Connect Stimma Cloud or set up a local endpoint in Settings."
    )


async def _raise_cloud_llm_error(model_slug: str | None = None) -> None:
    """Raise a typed error for an unavailable explicit cloud selection."""
    from auth_storage import load_auth_state
    from firebase_auth import get_valid_id_token

    auth_state = load_auth_state()
    tier = (auth_state or {}).get("tier")
    if tier == "free":
        raise LLMSubscriptionRequiredError(
            "Your current plan doesn't include AI models. Subscribe to Stimma Cloud or choose a local endpoint."
        )

    try:
        id_token = await get_valid_id_token()
    except Exception:
        id_token = None

    if not id_token:
        raise LLMNotConfiguredError(
            "Sign in to Stimma Cloud or choose a local endpoint.",
            code="llm_not_logged_in",
        )

    if model_slug:
        raise LLMNotConfiguredError(
            f"Stimma Cloud model '{model_slug}' is not available right now.",
            code="llm_cloud_unreachable",
            status_code=503,
        )
    raise LLMNotConfiguredError(
        "Stimma Cloud cannot be reached. Choose Local or try again later.",
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

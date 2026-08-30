"""
LLM configuration resolver.

Resolves the effective LLM configuration for a role, handling
the two source types: stimma_cloud and endpoint.

Two vocabularies meet here and are easy to confuse:

- **Settings roles** — ``quick_task``, ``tool_assistant``, ``chat``, ``flow``.
  These are the four user-facing model selections, stored per profile and
  overridable per project. Call sites ask for these.
- **Wire roles** — ``agent`` and ``agent-fast``. These are Stimma Cloud alias
  names and the keys of the legacy ``settings.llms`` endpoint pair. They are a
  routing detail; nothing user-facing should name them.

Every settings role maps onto one wire role (``WIRE_ROLE``), which decides only
the cloud alias and which reasoning level the model's catalog entry supplies.
"""
import os
from typing import Optional

from config import LEGACY_LLM_MODEL_SLUGS, get_settings, LLMEndpointConfig
from core.logging import get_logger
from model_tiers import ModelCandidate, ROLE_TIERS, seed_effort, select_auto_model

log = get_logger(__name__)

# Settings role -> wire role. `quick_task` and `tool_assistant` run on the
# model's quick-task reasoning level (usually "off"); `chat` and `flow` run on
# its default level.
WIRE_ROLE: dict[str, str] = {
    "quick_task": "agent-fast",
    "tool_assistant": "agent-fast",
    "chat": "agent",
    "flow": "agent",
}

SETTINGS_ROLES = tuple(ROLE_TIERS)


def _wire_role(role: str) -> str:
    """Wire role for a settings role, tolerating a wire role passed straight in."""
    if role in ("agent", "agent-fast"):
        return role
    return WIRE_ROLE.get(role, "agent")


def _is_quick(role: str) -> bool:
    return _wire_role(role) == "agent-fast"

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


async def _get_effective_llm_config_inner(
    role: str,
    project_id: Optional[int] = None,
) -> LLMEffectiveConfig:
    """Get the effective LLM config for a settings role.

    This is the main entry point for the surfaces that have no per-chat model
    selection to honor: background work, the ToolView assistant, flow bodies
    with no captured model. The role's slug resolves project -> profile -> auto,
    then the slug resolves to a concrete endpoint.

    Args:
        role: A settings role ('quick_task', 'tool_assistant', 'chat', 'flow').
            The wire roles 'agent' / 'agent-fast' are still accepted so older
            call sites and stored flow programs keep working.
        project_id: Project whose override should win, when the caller has one.

    Raises:
        LLMUnavailableError: If no usable backend can be resolved.
    """
    try:
        return await _resolve_role_llm_config(role, project_id)
    except LLMUnavailableError:
        # When the saved selection can't resolve — e.g. a cloud model while
        # signed out — any working configured model beats failing the feature.
        fallback = _fallback_provider_model_config(role=role)
        if fallback:
            return fallback
        role_config = _wire_role_config(role)
        if role_config and role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        raise


def _wire_role_config(role: str):
    """The legacy `settings.llms` entry for a role, or None if absent."""
    try:
        return get_settings().get_llm_role_config(_wire_role(role))
    except ValueError:
        return None


async def _resolve_role_llm_config(
    role: str,
    project_id: Optional[int] = None,
) -> LLMEffectiveConfig:
    acceptance_config = _acceptance_llm_config(role)
    if acceptance_config:
        return acceptance_config

    selected_slug = await resolve_role_model_slug(role, project_id)
    effort = await resolve_role_effort(role, project_id)

    provider_config = _get_provider_model_config(selected_slug, role=role, effort=effort)
    if provider_config:
        return provider_config
    provider = _provider_for_model_slug(selected_slug)
    if provider:
        raise LLMUnavailableError(
            f"{provider.name} is unavailable. Check it in Settings > Chat Models or choose another model.",
            code="llm_provider_unavailable",
        )

    role_config = _wire_role_config(role)

    if selected_slug == "local":
        if role_config and role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        raise LLMNotConfiguredError(
            "No local model endpoint is configured. Add one in Settings > Chat Models.",
            code="llm_local_missing",
        )

    if selected_slug.startswith("stimma:"):
        cloud_config = await _get_stimma_cloud_config(
            _resolve_catalog_alias(selected_slug, _wire_role(role)),
            model_slug=selected_slug,
            max_context_tokens=get_max_context_tokens(selected_slug),
            settings_role=role,
            effort=effort,
        )
        if cloud_config:
            return cloud_config
        await _raise_cloud_llm_error(model_slug=selected_slug)

    # `auto` reaching here means the tiering heuristic found nothing to choose
    # from: no cloud, no enabled provider model. The legacy endpoint pair is the
    # last place a working model can be hiding.
    if role_config and role_config.endpoint and role_config.endpoint.url:
        return role_config.endpoint

    _raise_no_llm_error()


async def _get_stimma_cloud_config(
    role: str,
    *,
    model_slug: Optional[str] = None,
    max_context_tokens: Optional[int] = None,
    settings_role: str = "agent",
    effort: Optional[str] = None,
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
            **_model_prompt_fields(model_slug or role),
            **_cloud_reasoning_fields(model_slug or role, role=settings_role, effort=effort),
        )
    except Exception as e:
        log.error("failed to get stimma cloud config", role=role, error=str(e))
        return None


def resolve_chat_effort(
    chat_effort: Optional[str],
    project_effort: Optional[str],
    profile_effort: Optional[str] = None,
) -> Optional[str]:
    """Three-level effort resolution: chat -> project -> profile.

    Mirrors resolve_chat_model_slug exactly. None at every level means nobody
    pinned one, so the `chat` role's intent decides once the model is known.
    """
    if profile_effort is None:
        profile_effort = get_settings().get_role_effort("chat")
    return chat_effort or project_effort or profile_effort


def resolve_chat_model_slug(
    chat_model_slug: Optional[str],
    project_default_slug: Optional[str],
    profile_default: Optional[str] = None,
) -> str:
    """Three-level default resolution: chat -> project -> profile.

    ``profile_default`` defaults to the current profile's ``chat`` setting;
    passing it explicitly is for callers that already read it. The result may be
    ``auto``, which the config resolvers turn into a concrete model.

    Privacy Lockdown excludes hosted models, so a saved cloud slug must behave
    like ``auto``.  ``auto`` still respects the normal resolver order and uses
    the configured local endpoint without contacting Stimma Cloud.
    """
    if profile_default is None:
        profile_default = get_settings().get_role_model_slug("chat")
    slug = normalize_model_slug(
        chat_model_slug or project_default_slug or profile_default or 'auto'
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
            # Default to the slug, never to a role name: a catalog row missing
            # its role key must still resolve to a model. Defaulting to "agent"
            # / "agent-fast" put a routing alias on the wire as if it were a
            # model, which the provider rejects.
            'agent_model': e.get('agent_model') or e['slug'],
            'agent_fast_model': e.get('agent_fast_model') or e['slug'],
            'max_context_tokens': int(e.get('max_context_tokens') or _FALLBACK_CONTEXT),
            'reasoning': e.get('reasoning') or {},
            'is_default': bool(e.get('is_default')),
            # The name the user sees in the model picker. Anything reporting
            # which model is answering has to use this — the resolved alias
            # (`agent-opus`) is a routing detail and means nothing to a reader.
            'name': e.get('name') or '',
            'canonical_model_id': e.get('canonical_model_id') or '',
            # Needed by the `auto` tiering heuristic, which draws a coherent
            # lineup from one vendor family.
            'model_vendor': e.get('model_vendor') or '',
        }
        for e in entries
    }


def model_display_name(slug: Optional[str]) -> Optional[str]:
    """Human-readable name for a model slug, as shown in the model picker.

    Falls back to the user-facing part of the slug when the catalog has no entry
    — a provider-qualified id is still far more legible than the routing alias
    that ends up in ``LLMEndpointConfig.model``.
    """
    if not slug:
        return None
    entry = _lookup_catalog(slug) or {}
    name = entry.get('name')
    if name:
        return name
    for provider in getattr(get_settings(), 'llm_providers', []):
        for model in getattr(provider, 'models', []) or []:
            if model.id == slug:
                return getattr(model, 'name', None) or model.id
    if slug in ('auto', 'local'):
        return None
    return slug.split(':', 1)[-1] or slug


def get_known_catalog_slugs() -> set[str]:
    """Return cloud model slugs known from the live cache or built-in fallback."""
    return set(_BUILTIN_CATALOG.keys()) | set(_catalog_cache.keys())


def _lookup_catalog(slug: str) -> Optional[dict]:
    """Look up a catalog entry by slug (live cache first, then built-ins)."""
    return _catalog_cache.get(slug) or _BUILTIN_CATALOG.get(slug)


def _cloud_reasoning_fields(
    model_slug: str, *, role: str = "agent", effort: Optional[str] = None
) -> dict:
    entry = _lookup_catalog(model_slug) or {}
    reasoning = entry.get("reasoning") or {}
    levels = reasoning.get("levels") or []
    if not levels:
        return {}
    requested_level = _resolve_level(
        role,
        effort=effort,
        levels=levels,
        default=reasoning.get("default"),
        quick_task_level=reasoning.get("quick_task"),
        slug=model_slug,
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


def _model_prompt_fields(model_slug: str) -> dict:
    prompt = getattr(get_settings(), "llm_model_prompts", {}).get(model_slug)
    if not prompt:
        return {"content_policy_enabled": True, "extra_system_prompt": ""}
    return {
        "content_policy_enabled": prompt.content_policy_enabled,
        "extra_system_prompt": prompt.extra_system_prompt,
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
    """Look up the model name for a catalog slug + wire role.

    Checks the live cache first (populated from cloud), then falls back
    to built-in mappings.

    The catalog spells its keys ``agent_model`` / ``agent_fast_model``, while the
    wire role is ``agent-fast`` — so the hyphen has to be normalized. Without
    that, every fast-role call missed the lookup and fell through to sending the
    literal string "agent-fast" as the model, which the provider rejects once
    reasoning fields ride along with it.
    """
    key = f"{role.replace('-', '_')}_model"
    entry = _lookup_catalog(slug)
    if entry:
        return entry.get(key, slug)
    # Unknown slug — try using it as a direct alias
    return slug


def auto_candidates(*, cloud_available: bool) -> list[ModelCandidate]:
    """Every model `auto` is allowed to choose from right now.

    Cloud models are included only when the caller has established that cloud is
    actually usable (authenticated, funded, not in Privacy Lockdown) — offering a
    model we cannot reach would make `auto` resolve to a dead selection. Local
    providers are always eligible; remote ones are dropped under lockdown, the
    same rule resolve_chat_model_slug applies.
    """
    from privacy_lockdown import is_privacy_lockdown_enabled

    lockdown = is_privacy_lockdown_enabled()
    candidates: list[ModelCandidate] = []

    if cloud_available and not lockdown:
        for slug, entry in {**_BUILTIN_CATALOG, **_catalog_cache}.items():
            # Built-in fallback rows keyed by bare alias ('opus', 'sonnet') are
            # routing shims, not selectable models.
            if not slug.startswith("stimma:"):
                continue
            candidates.append(ModelCandidate(
                slug=slug,
                name=entry.get("name") or slug,
                vendor=entry.get("model_vendor"),
                model_id=(entry.get("canonical_model_id") or slug),
            ))

    for provider in getattr(get_settings(), "llm_providers", []):
        if provider.deleted_at or not provider.enabled or provider.last_test_passed is False:
            continue
        if lockdown and provider.kind != "local":
            continue
        for model in provider.models:
            if not model.enabled:
                continue
            candidates.append(ModelCandidate(
                slug=model.id,
                name=model.name or model.model_id,
                vendor=model.model_vendor,
                model_id=model.model_id,
            ))

    return candidates


async def _cloud_is_available() -> bool:
    """True when a Stimma Cloud call would actually succeed."""
    from privacy_lockdown import is_privacy_lockdown_enabled

    if is_privacy_lockdown_enabled():
        return False
    try:
        from firebase_auth import get_valid_id_token
        if not await get_valid_id_token():
            return False
    except Exception:  # noqa: BLE001 — treat any auth failure as "no cloud"
        return False
    from auth_storage import load_auth_state
    auth_state = load_auth_state()
    return not (auth_state and (auth_state.get('credits') or 0) <= 0)


def _settings_role(role: str) -> str:
    """Map any role (settings or wire) onto a settings role for tier lookup."""
    if role in ROLE_TIERS:
        return role
    return "quick_task" if _is_quick(role) else "chat"


async def ensure_catalog_cache() -> None:
    """Populate the cloud catalog if `auto` is about to choose without one.

    The cache is normally filled as a side effect of the models route, which
    means any resolution that happens before the client asks for the model list
    sees only _BUILTIN_CATALOG — one cloud model. `auto` would then pick that
    one model no matter what the install actually has. Fetching here costs one
    request per backend lifetime and only on installs that have cloud at all.
    """
    if _catalog_cache:
        return
    try:
        import httpx
        from cloud_runtime import with_cloud_access_headers
        from firebase_auth import get_valid_id_token

        id_token = await get_valid_id_token()
        if not id_token:
            return
        url = f"{get_settings().cloud.base_url}/api/llm/v1/models"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=with_cloud_access_headers({"Authorization": f"Bearer {id_token}"}),
                timeout=10.0,
            )
        if response.status_code == 200:
            set_catalog_cache(response.json().get("data", []))
    except Exception as e:  # noqa: BLE001 — a cold catalog is not fatal
        log.warning("failed to warm model catalog", error=str(e))


async def resolve_auto_slug(role: str) -> Optional[str]:
    """The concrete model `auto` means for a role on this install right now."""
    cloud_available = await _cloud_is_available()
    if cloud_available:
        await ensure_catalog_cache()
    candidates = auto_candidates(cloud_available=cloud_available)
    return select_auto_model(candidates, _settings_role(role))


async def resolve_role_model_slug(
    role: str,
    project_id: Optional[int] = None,
    *,
    project_slug: Optional[str] = None,
) -> str:
    """Resolve a settings role to a concrete slug: project -> profile -> auto.

    ``project_slug`` lets a caller that already has the project row pass the
    override in instead of paying for a second query; ``project_id`` makes the
    lookup here. Passing neither resolves at profile level, which is correct for
    the surfaces that genuinely have no project (ingestion, share).
    """
    if project_slug is None and project_id is not None:
        project_slug = await _project_role_slug(role, project_id)

    slug = project_slug or get_settings().get_role_model_slug(role)
    slug = normalize_model_slug(slug) or "auto"

    if slug not in ("auto", "local"):
        # Fast path: a saved provider model is verifiable from memory. Checking
        # it first keeps a local-only install off the network — this runs on
        # every captioned image, and a cloud auth probe per quick task would be
        # a real cost for someone who has no cloud.
        if _get_provider_model_config(slug, role=role):
            return slug
        # A saved slug the install can no longer reach — a cloud model after
        # signing out, a provider that was deleted — must not be reported or
        # used as if it were live. Fall through to automatic selection, which is
        # what actually happens downstream anyway; agreeing here keeps the
        # settings UI showing the model that will really be called.
        cloud_available = await _cloud_is_available()

        # Until the live catalog has been fetched, the only cloud models we know
        # about are the compiled-in fallbacks — so "not in the candidate list"
        # says nothing about a cloud slug. Downgrading here would silently move
        # a freshly-started backend off the user's chosen model for every
        # caption and flow step until something happens to fetch the catalog.
        if slug.startswith("stimma:") and cloud_available and not _catalog_cache:
            return slug

        candidates = auto_candidates(cloud_available=cloud_available)
        if any(candidate.slug == slug for candidate in candidates):
            return slug
        if not candidates:
            # Nothing to switch to (legacy endpoint pair only) — leave the saved
            # selection alone and let the endpoint fallback handle it.
            return slug
        return select_auto_model(candidates, _settings_role(role)) or slug

    if slug == "local":
        return slug
    return await resolve_auto_slug(role) or "auto"


PROJECT_ROLE_COLUMNS = {
    "quick_task": "quick_task_model_slug",
    "tool_assistant": "tool_assistant_model_slug",
    "chat": "chat_model_slug",
    "flow": "flow_model_slug",
}

PROJECT_EFFORT_COLUMNS = {
    "quick_task": "quick_task_effort",
    "tool_assistant": "tool_assistant_effort",
    "chat": "chat_effort",
    "flow": "flow_effort",
}


async def resolve_role_effort(
    role: str,
    project_id: Optional[int] = None,
    *,
    project_effort: Optional[str] = None,
) -> Optional[str]:
    """Resolve a role's pinned reasoning effort: project -> profile -> None.

    None means "no one pinned one", which leaves the choice to the role's intent
    (model_tiers.ROLE_EFFORTS) once the model — and therefore its ladder — is
    known. Effort can't be resolved to a level here because two models rarely
    offer the same levels.
    """
    if role not in ROLE_TIERS:
        return None
    if project_effort is None and project_id is not None:
        project_effort = await _project_role_effort(role, project_id)
    if project_effort:
        return project_effort
    return get_settings().get_role_effort(role)


async def _project_role_effort(role: str, project_id: int) -> Optional[str]:
    """A project's effort override for a role, or None. Never fails a caller."""
    return await _project_column(PROJECT_EFFORT_COLUMNS.get(role), project_id, role)


async def _project_role_slug(role: str, project_id: int) -> Optional[str]:
    """A project's model override for a role, or None. Never fails a caller."""
    return await _project_column(PROJECT_ROLE_COLUMNS.get(role), project_id, role)


async def _project_column(
    column_name: Optional[str], project_id: int, role: str
) -> Optional[str]:
    """Read one nullable project column. An override lookup must never break a run."""
    if not column_name:
        return None
    try:
        from core.profile_context import get_current_profile
        from database import Project
        from database_registry import get_database_registry
        from sqlalchemy import select

        db = get_database_registry().get_database(get_current_profile())
        async with db.async_session_maker() as session:
            result = await session.execute(
                select(getattr(Project, column_name)).where(
                    Project.id == project_id,
                    Project.deleted_at.is_(None),
                )
            )
            return result.scalar_one_or_none()
    except Exception:  # noqa: BLE001 — an override lookup must never break a run
        log.debug("project override lookup failed", column=column_name, role=role,
                  project_id=project_id, exc_info=True)
        return None


def _resolve_level(
    role: str,
    *,
    effort: Optional[str],
    levels: list,
    default: Optional[str],
    quick_task_level: Optional[str],
    slug: Optional[str],
) -> Optional[str]:
    """Pick the reasoning level one call runs at.

    A pinned effort wins, but only if this model has that rung — a level saved
    against one model must never be forced onto another that doesn't offer it.
    Otherwise the role seeds from the model's own declared cheap/normal levels.

    Wire roles keep the older behavior so the chat path and the endpoint-test
    screen are unaffected: ``agent-fast`` runs at the model's quick-task level,
    ``agent`` at the globally saved per-model level.
    """
    if effort and effort in levels:
        return effort
    if role in ROLE_TIERS:
        # Nothing pinned (or a pin this model has no rung for): start from what
        # the model itself calls cheap/normal for this kind of work.
        return seed_effort(role, levels, default, quick_task_level)
    if role == "agent-fast":
        return quick_task_level
    if slug:
        return get_settings().llm_reasoning_levels.get(slug, default)
    return default


def _get_provider_model_config(
    model_slug: Optional[str],
    *,
    role: str = "agent",
    effort: Optional[str] = None,
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
            selected_level = _resolve_level(
                role,
                effort=effort,
                levels=reasoning.levels,
                default=reasoning.default,
                quick_task_level=reasoning.quick_task,
                slug=model.id,
            )
            if selected_level not in reasoning.levels:
                selected_level = (
                    reasoning.default
                    if reasoning.default in reasoning.levels
                    else (reasoning.levels[0] if reasoning.levels else None)
                )
            return LLMEndpointConfig(
                url=provider.base_url,
                model=model.model_id,
                api_key=provider.api_key,
                max_context_tokens=min(MAX_CONTEXT_CAP, model.max_context_tokens),
                content_policy_enabled=model.content_policy_enabled,
                extra_system_prompt=model.extra_system_prompt.strip(),
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


def _fallback_provider_model_config(
    *, role: str = "agent", effort: Optional[str] = None
) -> Optional[LLMEndpointConfig]:
    """First enabled, working provider model, for when the saved selection
    can't resolve. A single configured model should be used without making the
    user pick it explicitly. Remote providers are excluded during Privacy
    Lockdown, matching resolve_chat_model_slug."""
    from privacy_lockdown import is_privacy_lockdown_enabled

    lockdown = is_privacy_lockdown_enabled()
    for provider in getattr(get_settings(), "llm_providers", []):
        if provider.deleted_at or not provider.enabled or provider.last_test_passed is False:
            continue
        if lockdown and provider.kind != "local":
            continue
        for model in provider.models:
            if model.enabled:
                return _get_provider_model_config(model.id, role=role, effort=effort)
    return None


async def _get_chat_llm_config_inner(
    model_slug: Optional[str],
    role: str = 'agent',
    effort: Optional[str] = None,
) -> LLMEffectiveConfig:
    """Get LLM config for a chat message, respecting per-chat model selection.

    Args:
        model_slug: The resolved model slug (after default inheritance).
                    'auto' resolves against what's installed, 'local' means the
                    configured local endpoint, anything else names a model.
        role: A settings role, or the wire roles 'agent' / 'agent-fast'. Only
            affects reasoning level and the cloud alias, not which model is used.

    Returns:
        Config object with get_model(), get_api_key(), get_api_base() methods

    Raises:
        LLMUnavailableError: If no valid config is available
    """
    acceptance_config = _acceptance_llm_config(role)
    if acceptance_config:
        return acceptance_config

    model_slug = normalize_model_slug(model_slug) or 'auto'

    provider_config = _get_provider_model_config(model_slug, role=role, effort=effort)
    if provider_config:
        return provider_config
    provider = _provider_for_model_slug(model_slug)
    if provider:
        raise LLMUnavailableError(
            f"{provider.name} is unavailable. Check it in Settings > Chat Models or choose another model.",
            code="llm_provider_unavailable",
        )

    if model_slug == 'auto':
        # `auto` in a chat means the same thing it means in Settings: the best
        # available model for this role, tier-matched against what's installed.
        auto_slug = await resolve_auto_slug(role)
        if auto_slug and auto_slug != 'auto':
            return await _get_chat_llm_config_inner(auto_slug, role=role, effort=effort)
        role_config = _wire_role_config(role)
        if role_config and role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        fallback = _fallback_provider_model_config(role=role, effort=effort)
        if fallback:
            return fallback
        await _raise_cloud_llm_error()

    if model_slug == 'local':
        role_config = _wire_role_config(role)
        if role_config and role_config.endpoint and role_config.endpoint.url:
            return role_config.endpoint
        raise LLMNotConfiguredError(
            "No local model endpoint is configured. Add one in Settings > Chat Models.",
            code="llm_local_missing",
        )

    # Cloud model — resolve catalog slug to model alias, carry catalog context
    alias = _resolve_catalog_alias(model_slug, _wire_role(role))
    cloud_config = await _get_stimma_cloud_config(
        alias,
        model_slug=model_slug,
        max_context_tokens=get_max_context_tokens(model_slug),
        settings_role=role,
        effort=effort,
    )
    if cloud_config:
        return cloud_config

    await _raise_cloud_llm_error(model_slug=model_slug)


async def _apply_runtime_credentials(
    config: LLMEffectiveConfig,
) -> LLMEffectiveConfig:
    """Attach a freshly minted access token to ChatGPT-plan routes.

    Every other provider carries a static API key in its config. ChatGPT-plan
    routes deliberately store no key at all: the access token is short-lived
    and minted here per resolution, and the rotating refresh token behind it
    never leaves the OS credential store.
    """
    if getattr(config, "provider_kind", None) != "chatgpt":
        return config

    import chatgpt_auth

    try:
        config.api_key = await chatgpt_auth.get_access_token()
    except chatgpt_auth.ChatGPTAuthError as e:
        # Surface the typed reason. Collapsing "plan limit reached" into a
        # generic auth failure would tell the user to sign in again when
        # re-authenticating cannot possibly help.
        raise LLMUnavailableError(e.message, code=e.code) from e
    return config


async def get_effective_llm_config(
    role: str,
    project_id: Optional[int] = None,
) -> LLMEffectiveConfig:
    """Get the effective LLM config for a settings role.

    This is the main entry point for the surfaces that have no per-chat model
    selection to honor: background work, the ToolView assistant, flow bodies
    with no captured model.
    """
    return await _apply_runtime_credentials(
        await _get_effective_llm_config_inner(role, project_id)
    )


async def get_chat_llm_config(
    model_slug: Optional[str],
    role: str = 'agent',
    effort: Optional[str] = None,
) -> LLMEffectiveConfig:
    """Get LLM config for a chat message, respecting per-chat model selection."""
    return await _apply_runtime_credentials(
        await _get_chat_llm_config_inner(model_slug, role=role, effort=effort)
    )


def account_ever_had_credits(auth_state: Optional[dict]) -> bool:
    """Whether the signed-in Stimma account has ever held any credits.

    Buying (or redeeming) credits is what opts an account into Stimma-hosted
    LLMs: an account that has EVER had credits stays "configured forever"
    (zero balance = broken, fix by topping up), while one that never had any
    is treated as not configured at all. Accounts synced before the cloud
    reported the flag fall back to configured so nothing disappears on them.
    """
    if not auth_state:
        return False
    ever = auth_state.get('ever_had_credits')
    if ever is None:
        return True
    return bool(ever) or (auth_state.get('credits') or 0) > 0


def _raise_no_llm_error() -> None:
    """Raise the appropriate error based on auth state."""
    from auth_storage import load_auth_state
    auth_state = load_auth_state()
    if auth_state and account_ever_had_credits(auth_state) \
            and (auth_state.get('credits') or 0) <= 0:
        raise LLMInsufficientBalanceError(
            "Your Stimma account has no credits."
        )
    raise LLMNotConfiguredError(
        "No chat model is configured. Set one up in Settings > Chat Models."
    )


async def _raise_cloud_llm_error(model_slug: str | None = None) -> None:
    """Raise a typed error for an unavailable explicit cloud selection."""
    from auth_storage import load_auth_state
    from firebase_auth import get_valid_id_token

    auth_state = load_auth_state()
    if auth_state and (auth_state.get("credits") or 0) <= 0:
        raise LLMInsufficientBalanceError(
            "Your Stimma account has no credits."
        )

    try:
        id_token = await get_valid_id_token()
    except Exception:
        id_token = None

    if not id_token:
        raise LLMNotConfiguredError(
            "No chat model is available. Set one up in Settings > Chat Models.",
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



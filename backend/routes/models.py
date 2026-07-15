"""
Model catalog routes.

Provides the list of available LLM models for the chat model picker,
merging Stimma Cloud catalog entries with locally configured endpoints.
"""
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config import (
    get_settings,
    LLMEndpointConfig,
    LLMProviderConfig,
    LLMProviderModelConfig,
    LLMReasoningConfig,
)
from config_writer import patch_global_section
from core.logging import get_logger
from cloud_runtime import with_cloud_access_headers
from llm_resolver import get_max_context_tokens, normalize_model_slug, set_catalog_cache
from privacy_lockdown import is_privacy_lockdown_enabled
from llm_provider_catalog import PROVIDER_DEFAULTS, branded_models, discovered_model

router = APIRouter(prefix="/api/models", tags=["models"])
log = get_logger(__name__)

PUBLIC_CLOUD_FALLBACK_MODELS = {
    "stimma:minimax-m3": "MiniMax M3",
}


class ProviderCreateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    kind: str
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_ids: list[str] = Field(default_factory=list)


class ProviderUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None
    model_ids: Optional[list[str]] = None
    models: Optional[list[dict]] = None


def _active_providers() -> list[LLMProviderConfig]:
    return [
        provider for provider in getattr(get_settings(), "llm_providers", [])
        if not provider.deleted_at
    ]


def _provider_display_name(provider: LLMProviderConfig) -> str:
    if provider.kind == "local" and provider.name.strip().lower() in {
        "local llm",
        "local ai",
        "local endpoint",
    }:
        # Early provider builds wrote a generic product label into config. A
        # local server is a provider in its own right, so identify it by host.
        return urlparse(provider.base_url).netloc or (
            provider.models[0].name if provider.models else "Model endpoint"
        )
    return provider.name


def _provider_response(provider: LLMProviderConfig) -> dict:
    data = provider.model_dump(exclude={"api_key"})
    data["name"] = _provider_display_name(provider)
    data["api_key_set"] = bool(provider.api_key)
    data["api_key"] = "***" if provider.api_key else None
    return data


def _canonical_model_id(kind: str, model_id: str) -> str:
    if kind != "openrouter":
        return f"{kind}:{model_id}"
    known = {
        "minimax/minimax-m3": "minimax:minimax-m3",
        "qwen/qwen3.7-plus": "qwen:qwen-3.7-plus",
        "moonshotai/kimi-k2.7-code": "moonshot:kimi-k2.7",
        "moonshotai/kimi-k2.7": "moonshot:kimi-k2.7",
        "stepfun/step-3.7-flash": "stepfun:step-3.7-flash",
    }
    if model_id in known:
        return known[model_id]
    if "/" not in model_id:
        return f"openrouter:{model_id}"
    upstream, upstream_model = model_id.split("/", 1)
    upstream = {"x-ai": "xai"}.get(upstream, upstream)
    return f"{upstream}:{upstream_model}"


def _save_providers(providers: list[LLMProviderConfig]) -> None:
    patch_global_section("llm_providers", [provider.model_dump() for provider in providers])


def _validated_models(provider: LLMProviderConfig, rows: list[dict]) -> list[LLMProviderModelConfig]:
    models = [LLMProviderModelConfig.model_validate(row) for row in rows]
    seen: set[str] = set()
    for model in models:
        if not model.model_id.strip():
            raise HTTPException(status_code=400, detail="Model ID is required.")
        expected_id = f"{provider.id}:{model.model_id}"
        if model.id != expected_id or model.id in seen:
            raise HTTPException(status_code=400, detail="Model identifier is invalid.")
        seen.add(model.id)
        if model.max_context_tokens < 1024:
            raise HTTPException(status_code=400, detail="Context window is too small.")
        reasoning = model.reasoning
        if not reasoning.levels:
            raise HTTPException(status_code=400, detail="A reasoning level is required.")
        if reasoning.default not in reasoning.levels:
            reasoning.default = reasoning.levels[0]
        # Quick tasks always use the model's minimum advertised level.
        reasoning.quick_task = reasoning.levels[0]
        missing_wire = [level for level in reasoning.levels if level not in reasoning.wire_levels]
        if reasoning.control != "none" and missing_wire:
            raise HTTPException(status_code=400, detail=f"Missing request value for: {missing_wire[0]}.")
    return models


def _provider_headers(provider: LLMProviderConfig) -> dict[str, str]:
    if provider.kind == "anthropic":
        return {
            "x-api-key": provider.api_key or "",
            "anthropic-version": "2023-06-01",
        }
    return {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}


def _apply_local_profile(model: LLMProviderModelConfig, scenarios, detected) -> None:
    """Carry the existing local-endpoint profiler into the provider model."""
    tools = scenarios.get("tools")
    vision = scenarios.get("vision")
    model.supports_tools = bool(tools and tools.passed)
    model.input_modalities = ["text", "image"] if vision and vision.passed else ["text"]
    method = getattr(detected, "reasoning_method", None) if detected else None
    mode = getattr(detected, "reasoning_mode", None) if detected else None
    model.detected_runtime = getattr(detected, "runtime", None) if detected else None
    model.reasoning_output = getattr(detected, "reasoning_output", None) if detected else None
    control = {
        "reasoning_effort": "openai_effort",
        "enable_thinking": "enable_thinking",
        "openrouter": "openrouter_effort",
        "think": "think",
        "reasoning_budget": "reasoning_budget",
    }.get(method, "none")
    if model.reasoning_control_source == "manual":
        return
    if mode == "always":
        model.reasoning = LLMReasoningConfig(
            mode="required", levels=["high"], default="high", quick_task="high",
            control=control, wire_levels={"high": True if control in {"enable_thinking", "think"} else "high"},
        )
    elif mode == "toggleable":
        model.reasoning = LLMReasoningConfig(
            mode="optional", levels=["off", "high"], default="high", quick_task="off",
            control=control,
            wire_levels={
                "off": False if control in {"enable_thinking", "think"} else "none",
                "high": True if control in {"enable_thinking", "think"} else "high",
            },
        )
    else:
        model.reasoning = LLMReasoningConfig(
            mode="none", levels=["off"], default="off", quick_task="off",
            control="none", wire_levels={"off": "off"},
        )


async def _preview_provider(request: ProviderCreateRequest) -> tuple[LLMProviderConfig, list[dict]]:
    if request.kind not in PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail="Unsupported provider type.")
    defaults = PROVIDER_DEFAULTS[request.kind]
    provider = LLMProviderConfig(
        id=f"{request.kind}-preview",
        kind=request.kind,
        name=(request.name or defaults["name"]).strip(),
        base_url=(request.base_url or defaults["base_url"]).strip().rstrip("/"),
        api_key=request.api_key or None,
    )
    if request.kind != "local" and not provider.api_key:
        raise HTTPException(status_code=400, detail="API key is required.")
    return provider, await _discover_provider_models(provider)


async def _discover_provider_models(provider: LLMProviderConfig) -> list[dict]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{provider.base_url.rstrip('/')}/models",
                headers=_provider_headers(provider),
                timeout=10.0,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=400, detail=f"Could not reach {provider.name}.") from exc
    if response.status_code == 401:
        raise HTTPException(status_code=400, detail="API key is invalid.")
    if response.status_code in (402, 403):
        raise HTTPException(status_code=400, detail="The provider declined this key.")
    if response.status_code == 404:
        raise HTTPException(status_code=400, detail="This server does not have a models endpoint.")
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"Provider returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The models endpoint returned invalid JSON.") from exc
    rows = payload.get("data") or payload.get("models") or []
    return [row for row in rows if isinstance(row, dict) and (row.get("id") or row.get("name"))]


async def _test_local_provider_model(
    provider: LLMProviderConfig,
    model: LLMProviderModelConfig,
) -> dict:
    from routes.settings import _profile_endpoint

    config = LLMEndpointConfig(
        url=provider.base_url,
        model=model.model_id,
        api_key=provider.api_key,
        max_context_tokens=model.max_context_tokens,
        content_policy_enabled=False,
    )
    scenarios, detected = await _profile_endpoint(config)
    _apply_local_profile(model, scenarios, detected)
    results = {name: result.model_dump() for name, result in scenarios.items()}
    model.last_test_results = results
    model.last_tested_at = datetime.now(timezone.utc).isoformat()
    model.last_test_passed = bool(scenarios.get("text") and scenarios["text"].passed)
    model.last_error = None if model.last_test_passed else f"{model.name} did not return a response."
    if not model.last_test_passed:
        raise HTTPException(status_code=400, detail=model.last_error)
    return results


@router.get("/providers")
async def list_llm_providers():
    return {"providers": [_provider_response(provider) for provider in _active_providers()]}


@router.post("/providers/discover")
async def preview_llm_provider_models(request: ProviderCreateRequest):
    provider, rows = await _preview_provider(request)
    return {
        "provider_name": provider.name,
        "models": [
            {
                "id": str(row.get("id") or row.get("name")),
                "name": str(row.get("name") or row.get("id")),
                "context_length": row.get("context_length"),
            }
            for row in rows
        ],
    }


@router.post("/providers")
async def create_llm_provider(request: ProviderCreateRequest):
    if request.kind not in PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail="Unsupported provider type.")
    defaults = PROVIDER_DEFAULTS[request.kind]
    provider_id = f"{request.kind}-{uuid4().hex[:10]}"
    provider = LLMProviderConfig(
        id=provider_id,
        kind=request.kind,
        name=(request.name or defaults["name"]).strip(),
        base_url=(request.base_url or defaults["base_url"]).strip().rstrip("/"),
        api_key=request.api_key or None,
    )
    if request.kind == "local" and not request.name:
        provider.name = urlparse(provider.base_url).netloc or "Local endpoint"
    if request.kind != "local" and not provider.api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    discovered = await _discover_provider_models(provider)
    discovered_by_id = {str(row.get("id") or row.get("name")): row for row in discovered}
    if request.kind in {"openai", "anthropic", "xai"}:
        provider.models = branded_models(request.kind, provider.id)
        missing = [model.model_id for model in provider.models if model.model_id not in discovered_by_id]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Provider does not offer: {', '.join(missing)}.",
            )
    else:
        selected = request.model_ids or ([next(iter(discovered_by_id))] if len(discovered_by_id) == 1 else [])
        unknown = [model_id for model_id in selected if model_id not in discovered_by_id]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Model not found: {unknown[0]}.")
        provider.models = [
            discovered_model(
                provider.id,
                model_id,
                name=str(discovered_by_id[model_id].get("name") or model_id),
            )
            for model_id in selected
        ]
        for model in provider.models:
            advertised_context = discovered_by_id[model.model_id].get("context_length")
            if advertised_context:
                model.max_context_tokens = int(advertised_context)
        if request.kind == "local":
            for model in provider.models:
                await _test_local_provider_model(provider, model)
    provider.last_tested_at = datetime.now(timezone.utc).isoformat()
    provider.last_test_passed = True
    providers = list(get_settings().llm_providers)
    providers.append(provider)
    _save_providers(providers)
    return _provider_response(provider)


def _find_provider(provider_id: str) -> tuple[list[LLMProviderConfig], LLMProviderConfig]:
    providers = list(get_settings().llm_providers)
    for provider in providers:
        if provider.id == provider_id and not provider.deleted_at:
            return providers, provider
    raise HTTPException(status_code=404, detail="Provider not found.")


@router.get("/providers/{provider_id}/models")
async def discover_llm_provider_models(provider_id: str):
    _, provider = _find_provider(provider_id)
    rows = await _discover_provider_models(provider)
    selected = {model.model_id for model in provider.models if model.enabled}
    return {
        "models": [
            {
                "id": str(row.get("id") or row.get("name")),
                "name": str(row.get("name") or row.get("id")),
                "selected": str(row.get("id") or row.get("name")) in selected,
                "context_length": row.get("context_length"),
            }
            for row in rows
        ]
    }


@router.patch("/providers/{provider_id}")
async def update_llm_provider(provider_id: str, request: ProviderUpdateRequest):
    providers, provider = _find_provider(provider_id)
    updates = request.model_dump(exclude_unset=True)
    if "api_key" in updates and str(updates["api_key"] or "").startswith("***"):
        updates.pop("api_key")
    candidate = provider.model_copy(deep=True)
    for field in ("name", "base_url", "api_key", "enabled"):
        if field in updates:
            setattr(candidate, field, updates[field])
    if any(field in updates for field in ("base_url", "api_key")):
        discovered = await _discover_provider_models(candidate)
        advertised = {str(row.get("id") or row.get("name")) for row in discovered}
        missing = [model.model_id for model in candidate.models if model.enabled and model.model_id not in advertised]
        if missing:
            raise HTTPException(status_code=400, detail=f"Model no longer available: {missing[0]}.")
    for field in ("name", "base_url", "api_key", "enabled"):
        if field in updates:
            setattr(provider, field, getattr(candidate, field))
    if request.models is not None:
        provider.models = _validated_models(provider, request.models)
    elif request.model_ids is not None:
        rows = await _discover_provider_models(provider)
        by_id = {str(row.get("id") or row.get("name")): row for row in rows}
        unknown = [model_id for model_id in request.model_ids if model_id not in by_id]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Model not found: {unknown[0]}.")
        existing = {model.model_id: model for model in provider.models}
        provider.models = [
            existing.get(model_id) or discovered_model(
                provider.id, model_id, name=str(by_id[model_id].get("name") or model_id)
            )
            for model_id in request.model_ids
        ]
    _save_providers(providers)
    return _provider_response(provider)


@router.post("/providers/{provider_id}/test")
async def test_llm_provider(provider_id: str):
    providers, provider = _find_provider(provider_id)
    try:
        rows = await _discover_provider_models(provider)
        advertised = {str(row.get("id") or row.get("name")) for row in rows}
        missing = [model.model_id for model in provider.models if model.enabled and model.model_id not in advertised]
        if missing:
            raise HTTPException(status_code=400, detail=f"Model no longer available: {missing[0]}.")
        model_checks = {}
        if provider.kind == "local":
            for model in provider.models:
                if not model.enabled:
                    continue
                model_checks[model.model_id] = await _test_local_provider_model(provider, model)
        provider.last_test_passed = True
        provider.last_error = None
    except HTTPException as exc:
        provider.last_test_passed = False
        provider.last_error = str(exc.detail)
        provider.last_tested_at = datetime.now(timezone.utc).isoformat()
        _save_providers(providers)
        raise
    provider.last_tested_at = datetime.now(timezone.utc).isoformat()
    _save_providers(providers)
    return {
        "status": "ready",
        "model_count": len(rows),
        "tested_at": provider.last_tested_at,
        "model_checks": model_checks,
    }


@router.delete("/providers/{provider_id}")
async def delete_llm_provider(provider_id: str):
    providers, provider = _find_provider(provider_id)
    provider.deleted_at = datetime.now(timezone.utc).isoformat()
    provider.enabled = False
    _save_providers(providers)
    return {"status": "deleted"}


@router.get("/available")
async def get_available_models(project_id: Optional[int] = Query(None)):
    """Get available models for the chat model picker.

    Merges Stimma Cloud catalog with locally configured endpoints.
    Optionally includes project-level default when project_id is provided.
    """
    models = []
    settings = get_settings()
    lockdown = is_privacy_lockdown_enabled()
    cloud_status = "privacy_lockdown" if lockdown else "not_logged_in"
    cloud_message = "" if lockdown else "Sign in to your Stimma account to use hosted models."
    cloud_entries = []

    # 1. Fetch cloud catalog if authenticated
    try:
        from firebase_auth import get_valid_id_token
        id_token = None if lockdown else await get_valid_id_token()
        if id_token:
            cloud_status = "cloud_unreachable"
            cloud_message = "Stimma cannot be reached."
            base_url = settings.cloud.base_url
            url = f"{base_url}/api/llm/v1/models"
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=with_cloud_access_headers({"Authorization": f"Bearer {id_token}"}),
                    timeout=10.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    cloud_entries = data.get('data', [])
                    cloud_status = "available"
                    cloud_message = ""
                    # Update resolver cache
                    set_catalog_cache(cloud_entries)
                    for entry in cloud_entries:
                        models.append({
                            "slug": entry["slug"],
                            "source": "stimma_cloud",
                            "name": entry["name"],
                            "description": entry.get("description", ""),
                            "based_on": entry.get("based_on"),
                            "available": True,
                            "status": "available",
                            "max_context_tokens": get_max_context_tokens(entry["slug"]),
                            "provider_id": "stimma",
                            "provider_name": entry.get("provider_name", "Stimma Cloud"),
                            "upstream_provider": entry.get("upstream_provider"),
                            "canonical_model_id": entry.get("canonical_model_id"),
                            "reasoning": entry.get("reasoning"),
                            "cost_tier": entry.get("cost_tier"),
                            "supports_tools": entry.get("supports_tools", True),
                            "input_modalities": entry.get("input_modalities", ["text"]),
                            "is_default": entry.get("is_default", False),
                        })
                elif response.status_code in (401, 403):
                    cloud_status = "subscription_required"
                    cloud_message = "Your Stimma account does not currently include hosted models."
    except Exception as e:
        log.warning("failed to fetch cloud model catalog", error=str(e))

    # The fallback names are compiled into the app; they do not come from a
    # network request. Even so, Cloud models should be absent—not advertised as
    # unavailable—while Privacy Lockdown is active.
    if not cloud_entries and not lockdown:
        for slug in PUBLIC_CLOUD_FALLBACK_MODELS:
            models.append({
                "slug": slug,
                "source": "stimma_cloud",
                "name": PUBLIC_CLOUD_FALLBACK_MODELS[slug],
                "description": cloud_message,
                "available": False,
                "status": cloud_status,
                "max_context_tokens": get_max_context_tokens(slug),
            })

    # 2. Add user-owned providers. Provider-qualified model IDs avoid actual
    # collisions; canonical IDs let the picker collapse the Stimma route when
    # the same underlying model is available through the user's own key.
    user_canonical_ids: dict[str, str] = {}
    for provider in _active_providers():
        if not provider.enabled:
            continue
        provider_name = _provider_display_name(provider)
        for provider_model in provider.models:
            if not provider_model.enabled:
                continue
            canonical_id = _canonical_model_id(provider.kind, provider_model.model_id)
            user_canonical_ids[canonical_id] = provider_name
            models.append({
                "slug": provider_model.id,
                "source": "provider",
                "provider_id": provider.id,
                "provider_name": provider_name,
                "provider_kind": provider.kind,
                "canonical_model_id": canonical_id,
                "name": provider_model.name,
                "description": f"via {provider_name}",
                "available": provider.last_test_passed is not False,
                "status": "available" if provider.last_test_passed is not False else "provider_unavailable",
                "max_context_tokens": min(256_000, provider_model.max_context_tokens),
                "reasoning": provider_model.reasoning.model_dump(),
                "supports_tools": provider_model.supports_tools,
                "input_modalities": provider_model.input_modalities,
            })
    for model in models:
        if model.get("source") != "stimma_cloud":
            continue
        canonical_id = model.get("canonical_model_id")
        if canonical_id and canonical_id in user_canonical_ids:
            model["collapsed"] = True
            model["shadowed_by_provider"] = user_canonical_ids[canonical_id]

    # 3. Keep the legacy endpoint pair available until it is migrated into a
    # provider. New local servers are represented independently above.
    agent_config = settings.llms.get('agent')
    agent_fast_config = settings.llms.get('agent-fast')
    agent_has_endpoint = (
        agent_config and agent_config.endpoint and agent_config.endpoint.url
    )
    agent_fast_has_endpoint = (
        agent_fast_config and agent_fast_config.endpoint and agent_fast_config.endpoint.url
    )

    if agent_has_endpoint and agent_fast_has_endpoint:
        # Both endpoints configured — offer as a selectable pair
        agent_model = agent_config.endpoint.model or "custom"
        local_max_context_tokens = agent_config.endpoint.max_context_tokens
        models.append({
            "slug": "local",
            "source": "endpoint",
            "name": agent_model,
            # Kept for tooltips and non-picker consumers; the picker renders
            # endpoint_url/endpoint_model as separate truncated lines.
            "description": f"{agent_config.endpoint.url} ({agent_model})",
            "endpoint_url": agent_config.endpoint.url,
            "endpoint_model": agent_model,
            "available": True,
            "status": "available",
            "max_context_tokens": local_max_context_tokens,
        })
    else:
        local_max_context_tokens = 128_000
        models.append({
            "slug": "local",
            "source": "endpoint",
            "name": "Local model endpoint",
            "description": "Add a model endpoint in Settings > AI Services.",
            "available": False,
            "status": "local_missing",
            "max_context_tokens": local_max_context_tokens,
        })

    auto_model = {
        "slug": "auto",
        "source": "auto",
        "name": "Set up a local model" if lockdown else "Set up AI models",
        "description": (
            "Add a model endpoint in Settings > AI Services."
            if lockdown
            else "Sign in to your Stimma account or add a model provider."
        ),
        "available": False,
        "status": "llm_not_configured",
        "resolved_slug": None,
        "max_context_tokens": get_max_context_tokens('stimma:minimax-m3'),
    }
    if cloud_status == "available":
        auto_model.update({
            "name": "Auto: MiniMax M3",
            "description": "Uses MiniMax M3 via Stimma.",
            "available": True,
            "status": "available",
            "resolved_slug": "stimma:minimax-m3",
            "max_context_tokens": get_max_context_tokens('stimma:minimax-m3'),
        })
    elif agent_has_endpoint and agent_fast_has_endpoint:
        auto_model.update({
            "name": f"Auto: {agent_model}",
            "description": "Uses your configured model endpoint.",
            "available": True,
            "status": "available",
            "resolved_slug": "local",
            "max_context_tokens": local_max_context_tokens,
        })

    # Acceptance lane: the resolver (_acceptance_llm_config) serves a
    # deterministic in-process LLM for every role regardless of cloud auth or
    # local endpoint config, so the picker must advertise `auto` as available.
    # Otherwise the model list loads as "unavailable" and the composer silently
    # no-ops sends — a race the acceptance chat tests only win by sending before
    # /models/available resolves.
    if os.environ.get("STIMMA_TEST_PROVIDER"):
        cloud_status = "available"
        cloud_message = ""
        auto_model.update({
            "name": "Auto: Acceptance LLM",
            "description": "Deterministic in-process model used by the acceptance lane.",
            "available": True,
            "status": "available",
            "resolved_slug": "auto",
            "max_context_tokens": get_max_context_tokens('stimma:minimax-m3'),
        })

    models.insert(0, auto_model)

    # 4. Resolve project default if requested
    project_default = None
    if project_id is not None:
        try:
            from database_registry import get_database_registry
            from database import Project
            from sqlalchemy import select

            db_reg = get_database_registry()
            async with db_reg.get_session() as session:
                result = await session.execute(
                    select(Project.default_model_slug).where(
                        Project.id == project_id,
                        Project.deleted_at.is_(None),
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    project_default = row
        except Exception as e:
            log.warning("failed to fetch project default model", error=str(e))

    effective_global_default = normalize_model_slug(settings.default_model)
    effective_project_default = normalize_model_slug(project_default)
    if lockdown:
        if effective_global_default not in {None, "auto", "local"}:
            effective_global_default = "auto"
        if effective_project_default not in {None, "auto", "local"}:
            effective_project_default = "auto"

    saved_slugs = {
        s for s in (effective_global_default, effective_project_default)
        if s and s not in {m["slug"] for m in models}
    }
    for slug in saved_slugs:
        models.append({
            "slug": slug,
            "source": "stimma_cloud" if slug != "local" else "endpoint",
            "name": f"Unknown model: {slug}",
            "description": "This saved model is no longer available.",
            "available": False,
            "status": "model_missing",
            "max_context_tokens": get_max_context_tokens(slug),
        })

    return {
        "models": models,
        "global_default": effective_global_default,
        "quick_task_model": normalize_model_slug(
            getattr(settings, "quick_task_model", "stimma:minimax-m3")
        ),
        "reasoning_levels": getattr(settings, "llm_reasoning_levels", {}),
        "project_default": effective_project_default,
        "cloud_status": cloud_status,
        "cloud_message": cloud_message,
    }

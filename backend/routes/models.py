"""
Model catalog routes.

Provides the list of available LLM models for the chat model picker,
merging Stimma Cloud catalog entries with locally configured endpoints.
"""
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Query

from config import get_settings
from core.logging import get_logger
from cloud_runtime import with_cloud_access_headers
from llm_resolver import set_catalog_cache, get_max_context_tokens
from privacy_lockdown import is_privacy_lockdown_enabled

router = APIRouter(prefix="/api/models", tags=["models"])
log = get_logger(__name__)

PUBLIC_CLOUD_FALLBACK_MODELS = {
    "agent-max": "Stimma Agent Max",
    "default": "Stimma Agent",
}


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
    cloud_message = (
        "Stimma Cloud is unavailable in Privacy Lockdown."
        if lockdown
        else "Sign in to Stimma Cloud to use hosted models."
    )
    cloud_entries = []

    # 1. Fetch cloud catalog if authenticated
    try:
        from firebase_auth import get_valid_id_token
        id_token = None if lockdown else await get_valid_id_token()
        if id_token:
            cloud_status = "cloud_unreachable"
            cloud_message = "Stimma Cloud cannot be reached."
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
                            "available": True,
                            "status": "available",
                            "max_context_tokens": get_max_context_tokens(entry["slug"]),
                        })
                elif response.status_code in (401, 403):
                    cloud_status = "subscription_required"
                    cloud_message = "Your current plan does not include Stimma Cloud AI models."
    except Exception as e:
        log.warning("failed to fetch cloud model catalog", error=str(e))

    if not cloud_entries:
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

    # 2. Check for locally configured endpoints
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
            "name": "Local Endpoint",
            "description": f"{agent_config.endpoint.url} ({agent_model})",
            "available": True,
            "status": "available",
            "max_context_tokens": local_max_context_tokens,
        })
    else:
        local_max_context_tokens = 128_000
        models.append({
            "slug": "local",
            "source": "endpoint",
            "name": "Local Endpoint",
            "description": "Configure a local endpoint in Settings > Advanced.",
            "available": False,
            "status": "local_missing",
            "max_context_tokens": local_max_context_tokens,
        })

    auto_model = {
        "slug": "auto",
        "source": "auto",
        "name": "Set up AI models",
        "description": "Sign in to Stimma Cloud or configure a local endpoint in Settings > Advanced.",
        "available": False,
        "status": "llm_not_configured",
        "resolved_slug": None,
        "max_context_tokens": get_max_context_tokens('agent-max'),
    }
    if cloud_status == "available":
        auto_model.update({
            "name": "Auto: Stimma Agent Max",
            "description": "Uses Stimma Agent Max from Stimma Cloud.",
            "available": True,
            "status": "available",
            "resolved_slug": "agent-max",
            "max_context_tokens": get_max_context_tokens('agent-max'),
        })
    elif agent_has_endpoint and agent_fast_has_endpoint:
        auto_model.update({
            "name": "Auto: Local Endpoint",
            "description": "Uses your configured local endpoint.",
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
            "max_context_tokens": get_max_context_tokens('agent-max'),
        })

    models.insert(0, auto_model)

    # 3. Resolve project default if requested
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

    saved_slugs = {
        s for s in (settings.default_model, project_default)
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
        "global_default": settings.default_model,
        "project_default": project_default,
        "cloud_status": cloud_status,
        "cloud_message": cloud_message,
    }

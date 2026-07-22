"""Durable display identity for tools referenced by Media lineage.

Execution availability is intentionally separate from display identity.  A
tool may be disconnected, disabled, renamed, or retired while its historical
lineage still needs a stable, human-readable facet label.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database import CachedProviderTool
from tasks.schemas import TASK_SCHEMA_REQUIREMENTS, TASK_TYPE_ALIASES


BUILTIN_TOOL_METADATA: dict[str, dict[str, str]] = {
    "builtin:stimma:image-editor": {
        "name": "Image Editor",
        "provider_name": "Stimma",
        "provider_id": "builtin:stimma",
    },
    "builtin:darkroom-film-stock": {
        "name": "Film Stock",
        "provider_name": "Built-in Tools",
        "provider_id": "builtin",
    },
    "builtin:darkroom-develop": {
        "name": "Develop",
        "provider_name": "Built-in Tools",
        "provider_id": "builtin",
    },
    "builtin:darkroom-color-grade": {
        "name": "Color Grade",
        "provider_name": "Built-in Tools",
        "provider_id": "builtin",
    },
}

_LEGACY_TASK_SEGMENTS = frozenset(
    [*TASK_SCHEMA_REQUIREMENTS, *TASK_TYPE_ALIASES]
)


def canonical_tool_id(full_tool_id: str) -> str:
    """Collapse known ComfyUI identity formats to the current stable ID.

    Older ComfyUI registrations included the task in the identity, for
    example ``comfyui:text-to-image:model``.  Current multi-capability tools
    use ``comfyui:model``.  Some still older builds used
    ``builtin:comfyui`` as the provider prefix.
    """
    value = str(full_tool_id or "").strip()
    if value.startswith("builtin:comfyui:"):
        value = value[len("builtin:") :]
    if not value.startswith("comfyui:"):
        return value
    parts = value.split(":")
    if len(parts) >= 3 and parts[1] in _LEGACY_TASK_SEGMENTS:
        return ":".join([parts[0], *parts[2:]])
    return value


def expand_tool_id_aliases(tool_ids: Iterable[str]) -> list[str]:
    """Return exact and historical IDs represented by tool selections."""
    expanded: set[str] = set()
    for raw_tool_id in tool_ids:
        raw = str(raw_tool_id or "").strip()
        if not raw:
            continue
        canonical = canonical_tool_id(raw)
        expanded.update({raw, canonical})
        if not canonical.startswith("comfyui:"):
            continue
        suffix = canonical[len("comfyui:") :]
        expanded.add(f"builtin:comfyui:{suffix}")
        for task_type in _LEGACY_TASK_SEGMENTS:
            expanded.add(f"comfyui:{task_type}:{suffix}")
            expanded.add(f"builtin:comfyui:{task_type}:{suffix}")
    return sorted(expanded)


def _fallback_metadata(full_tool_id: str) -> dict[str, str]:
    canonical = canonical_tool_id(full_tool_id)
    slug = canonical.rsplit(":", 1)[-1]
    name = slug.replace("_", " ").replace("-", " ").title() or canonical
    if canonical.startswith("comfyui:"):
        return {
            "name": name,
            "provider_name": "ComfyUI",
            "provider_id": "comfyui",
        }
    return {"name": name, "provider_name": "", "provider_id": ""}


async def _cached_rows(session, candidate_ids: list[str]):
    if not candidate_ids:
        return []
    return (
        await session.execute(
            select(
                CachedProviderTool.full_tool_id,
                CachedProviderTool.name,
                CachedProviderTool.provider_name,
                CachedProviderTool.provider_id,
                CachedProviderTool.last_registered_at,
            ).where(CachedProviderTool.full_tool_id.in_(candidate_ids))
        )
    ).all()


async def _all_cached_rows(session, candidate_ids: list[str]):
    """Read the local cache plus the historical global-cache authority.

    Tool providers are global, but older builds cached descriptors only in
    the first profile database.  Consult it as a compatibility source while
    newer builds keep every profile cache synchronized.
    """
    rows = list(await _cached_rows(session, candidate_ids))
    try:
        from database_registry import get_database_registry

        registry = get_database_registry()
        profiles = registry.list_profiles()
        if profiles:
            database = registry.get_database(profiles[0]["id"])
            async with database.async_session_maker() as authority_session:
                rows.extend(await _cached_rows(authority_session, candidate_ids))
    except Exception:
        # Facets must remain available during startup or isolated tests even
        # when the registry has not finished initializing.
        pass
    return rows


async def resolve_tool_display_metadata(
    session,
    full_tool_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Resolve lineage IDs through built-ins, live tools, and history."""
    raw_ids = list(dict.fromkeys(
        str(tool_id).strip() for tool_id in full_tool_ids if str(tool_id).strip()
    ))
    candidate_ids = expand_tool_id_aliases(raw_ids)

    cached_by_canonical: dict[str, tuple[datetime, dict[str, str]]] = {}
    for full_id, name, provider_name, provider_id, registered_at in (
        await _all_cached_rows(session, candidate_ids)
    ):
        canonical = canonical_tool_id(full_id)
        metadata = {
            "name": name,
            "provider_name": provider_name or provider_id or "",
            "provider_id": provider_id or "",
        }
        timestamp = registered_at or datetime.min
        prior = cached_by_canonical.get(canonical)
        if prior is None or timestamp >= prior[0]:
            cached_by_canonical[canonical] = (timestamp, metadata)

    live_by_canonical: dict[str, dict[str, str]] = {}
    try:
        from providers import ProviderRegistry

        for full_id, provider, descriptor in (
            ProviderRegistry.get_instance().list_all_tools()
        ):
            live_by_canonical[canonical_tool_id(full_id)] = {
                "name": descriptor.name,
                "provider_name": provider.provider_name,
                "provider_id": provider.provider_id,
            }
    except Exception:
        pass

    resolved: dict[str, dict[str, Any]] = {}
    for raw_id in raw_ids:
        canonical = canonical_tool_id(raw_id)
        metadata = (
            BUILTIN_TOOL_METADATA.get(canonical)
            or live_by_canonical.get(canonical)
            or (
                cached_by_canonical[canonical][1]
                if canonical in cached_by_canonical
                else None
            )
            or _fallback_metadata(canonical)
        )
        resolved[raw_id] = {
            **metadata,
            "canonical_tool_id": canonical,
        }
    return resolved

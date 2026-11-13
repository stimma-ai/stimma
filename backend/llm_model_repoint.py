"""Point saved model choices at a replacement model.

When a person swaps one of a provider's models for another (their own server
now serves a different model at the same URL), every place that remembers the
old model as a choice follows it to the new one: role selections in every
profile, project and chat overrides, frozen user tools, and the per-model
settings keyed by slug. A pinned effort the new model does not offer is
dropped, so the choice falls back to what the new model seeds to.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from config import LLMModelPromptConfig, RoleModelSelection, get_settings
from config_writer import _load_config_yaml, patch_global_section, patch_profile_section
def _kept_effort(effort: Optional[str], levels: list[str]) -> Optional[str]:
    return effort if effort and effort in levels else None


def _repoint_profile_roles(replaces: dict[str, str], levels: dict[str, list[str]]) -> list[str]:
    settings = get_settings()
    changed = []
    for profile in getattr(settings, "profiles", None) or []:
        models = profile.agent.models
        touched = False
        for role in type(models).model_fields:
            selection = getattr(models, role)
            new_slug = replaces.get(selection.model)
            if not new_slug:
                continue
            setattr(models, role, RoleModelSelection(
                model=new_slug,
                effort=_kept_effort(selection.effort, levels.get(new_slug, [])),
            ))
            touched = True
        if touched:
            patch_profile_section(profile.id, "agent", profile.agent.model_dump())
            changed.append(profile.id)
    return changed


def _repoint_slug_map(section: str, replaces: dict[str, str], keep) -> bool:
    """Move per-model settings keyed by slug. An explicit setting already saved
    for the new model wins over the old model's."""
    settings = get_settings()
    current = _saved_section(section)
    if current is None:
        current = {
            slug: value.model_dump() if isinstance(value, LLMModelPromptConfig) else value
            for slug, value in (getattr(settings, section, None) or {}).items()
        }
    changed = False
    for old_slug, new_slug in replaces.items():
        if old_slug not in current:
            continue
        value = current.pop(old_slug)
        changed = True
        if new_slug not in current and keep(new_slug, value):
            current[new_slug] = value
    if changed:
        patch_global_section(section, current)
        if section == "llm_model_prompts":
            setattr(settings, section, {
                slug: LLMModelPromptConfig.model_validate(value) for slug, value in current.items()
            })
        else:
            setattr(settings, section, current)
    return changed


def _saved_section(section: str) -> Optional[dict]:
    """A global section as config.yaml holds it now. Settings routes write these
    maps to the file and leave the in-process copy to the file watcher, so the
    file is the authority."""
    try:
        data, _ = _load_config_yaml()
    except Exception:
        return None
    value = (data or {}).get(section) or {}
    return {
        str(slug): dict(item) if hasattr(item, "items") else item
        for slug, item in value.items()
    } if hasattr(value, "items") else {}


async def _repoint_profile_database(
    profile_id: str, replaces: dict[str, str], levels: dict[str, list[str]],
) -> dict[str, int]:
    from database import Chat, Project, UserTool
    from database_registry import get_database_registry
    from llm_resolver import PROJECT_EFFORT_COLUMNS, PROJECT_ROLE_COLUMNS

    counts = {"projects": 0, "chats": 0, "user_tools": 0}
    db = get_database_registry().get_database(profile_id)
    old_slugs = list(replaces)
    async with db.async_session_maker() as session:
        for role, column in PROJECT_ROLE_COLUMNS.items():
            effort_column = PROJECT_EFFORT_COLUMNS[role]
            rows = (await session.execute(
                select(Project).where(getattr(Project, column).in_(old_slugs))
            )).scalars().all()
            for project in rows:
                new_slug = replaces[getattr(project, column)]
                setattr(project, column, new_slug)
                setattr(project, effort_column, _kept_effort(
                    getattr(project, effort_column), levels.get(new_slug, []),
                ))
                counts["projects"] += 1
        chats = (await session.execute(
            select(Chat).where(Chat.model_slug.in_(old_slugs))
        )).scalars().all()
        for chat in chats:
            chat.model_slug = replaces[chat.model_slug]
            chat.reasoning_effort = _kept_effort(
                chat.reasoning_effort, levels.get(chat.model_slug, []),
            )
            counts["chats"] += 1
        tools = (await session.execute(
            select(UserTool).where(UserTool.model_slug.in_(old_slugs))
        )).scalars().all()
        for tool in tools:
            tool.model_slug = replaces[tool.model_slug]
            counts["user_tools"] += 1
        await session.commit()
    return counts


async def repoint_profile_databases(
    replaces: dict[str, str], levels: dict[str, list[str]],
) -> dict[str, dict[str, int]]:
    """Repoint chats, project overrides and frozen tools in every profile's
    database. Runs before the provider is saved: a failure propagates, nothing
    about the provider has changed yet, and the same request can be retried.
    Each profile commits in one transaction, and a repeat finds nothing left to
    move in a profile that already committed.
    """
    from database_registry import get_database_registry

    registry = get_database_registry()
    counts: dict[str, dict[str, int]] = {}
    for profile in getattr(get_settings(), "profiles", None) or []:
        if registry.has_profile(profile.id):
            counts[profile.id] = await _repoint_profile_database(profile.id, replaces, levels)
    return counts


def repoint_config_selections(replaces: dict[str, str], levels: dict[str, list[str]]) -> dict:
    """Repoint role selections and the per-model settings keyed by slug in
    config.yaml. Repeating it after a partial run is harmless."""
    return {
        "profiles": _repoint_profile_roles(replaces, levels),
        "reasoning_levels": _repoint_slug_map(
            "llm_reasoning_levels", replaces,
            lambda slug, level: level in levels.get(slug, []),
        ),
        "model_prompts": _repoint_slug_map(
            "llm_model_prompts", replaces, lambda _slug, _value: True,
        ),
    }

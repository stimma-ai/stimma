"""Skill tool — list and invoke skills.

Skills are the flat, agent-facing capability units inside stimpacks (the
installable packages). Invoking a skill lands its SKILL.md body into the
conversation. Authoring is filesystem work, not a tool API: the profile's
stimpacks dir is mounted into the workspace as ``skills/`` and the agent
writes ``skills/<slug>/SKILL.md`` with its ordinary file tools. ``list``
shows each skill's path and any loader problems so the agent can confirm
what it wrote actually parsed.
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter
from ..stimpacks import SkillInfo, StimpackInfo, list_installed_stimpacks, list_skills, load_skill, shadowed_skills
from ..stimpack_validate import validate_pack
from ._workspace_files import SKILLS_MOUNT, skills_mount_target

from core.logging import get_logger
from database import Chat, ChatItem

log = get_logger(__name__)


async def _is_skill_already_invoked(name: str, session: AsyncSession, chat_id: int) -> bool:
    """Check if a skill has already been invoked in this chat.

    "stimpack_name" is the legacy metadata key from before skills were
    addressed flat — old history items keep counting as invoked.
    """
    result = await session.execute(
        select(ChatItem)
        .where(
            ChatItem.chat_id == chat_id,
            ChatItem.item_type == "stimpack_injection",
        )
    )
    for item in result.scalars():
        if item.item_metadata:
            try:
                meta = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
                if name in (meta.get("skill_name"), meta.get("stimpack_name")):
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
    return False


async def _chat_environment(session: AsyncSession, chat_id: int) -> str:
    """The skill environment for this chat: "flow" for flow chats, else "chat"."""
    if session is not None and chat_id:
        chat = await session.get(Chat, chat_id)
        if chat is not None and chat.flow_id is not None:
            return "flow"
    return "chat"


def _where(skill: SkillInfo) -> str:
    """Human-readable list of the surfaces a skill is offered on."""
    env = skill.environments
    parts = []
    if env.chat:
        parts.append("chat")
    if env.flow:
        parts.append("flow")
    if env.tool:
        parts.append("tools" if env.tool_task_types is None else f"tools({', '.join(env.tool_task_types)})")
    return ", ".join(parts) or "nowhere"


def _skill_path(pack: StimpackInfo, skill: SkillInfo, skills_root: Path | None) -> str:
    """Workspace-relative path of a skill's SKILL.md, or why it has none."""
    if pack.is_dev:
        return "(dev repo, read-only)"
    if skills_root is not None:
        try:
            return f"{SKILLS_MOUNT}/{skill.skill_md.resolve().relative_to(skills_root)}"
        except ValueError:
            pass
    return "(not under skills/)"


def _notes(pack: StimpackInfo, skill: SkillInfo) -> str:
    if pack.is_dev:
        return "dev repo, read-only"
    if pack.marketplace is not None:
        return f"marketplace, read-only — fork to {SKILLS_MOUNT}/{skill.slug}/"
    if skill.overrides:
        return f"yours, overrides {skill.overrides}"
    return "yours"


def _surfaces(skill: SkillInfo) -> set[str]:
    env = skill.environments
    return {k for k in ("chat", "flow", "tool") if getattr(env, k, False)}


def _precedence_problems(visible: list[SkillInfo], hidden: list[tuple[SkillInfo, SkillInfo]]) -> list[str]:
    """Two local skills claiming one slug; forks offered on fewer surfaces than the original."""
    problems: list[str] = []
    by_slug: dict[str, list[SkillInfo]] = {}
    for s in visible:
        by_slug.setdefault(s.slug, []).append(s)
    for slug, group in sorted(by_slug.items()):
        if len(group) > 1:
            names = " and ".join(f"'{s.qualified_name}'" for s in group)
            problems.append(f"{names} both claim the name '{slug}' — bare-name invoke is ambiguous; rename one")
    for original, fork in hidden:
        missing = _surfaces(original) - _surfaces(fork)
        if missing:
            problems.append(
                f"'{fork.qualified_name}' overrides '{original.qualified_name}' but is not offered in "
                f"{', '.join(sorted(missing))} (the original was) — add those to its environments: block (warning)"
            )
    return problems


def _pack_problems(packs: list[StimpackInfo]) -> list[str]:
    """Validator errors/warnings for editable (profile) packs, one line each."""
    problems: list[str] = []
    for pack in packs:
        if pack.is_dev:
            continue
        try:
            _, warnings, errors = validate_pack(pack.dir_path)
        except Exception as e:  # pragma: no cover - defensive
            errors, warnings = [str(e)], []
        problems.extend(f"{pack.name}: {e}" for e in errors)
        # A missing manifest is normal for hand-written single-skill packs —
        # the loader derives one — so don't nag the agent about it.
        problems.extend(f"{pack.name}: {w} (warning)" for w in warnings if "no stimpack.json" not in w)
    return problems


def _unloadable_dirs(packs: list[StimpackInfo], skills_root: Path | None) -> list[str]:
    """Directories under skills/ that did not load as a stimpack at all."""
    if skills_root is None or not skills_root.is_dir():
        return []
    loaded = {p.dir_path.resolve() for p in packs}
    out = []
    for child in sorted(skills_root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and child.resolve() not in loaded:
            _, _, errors = validate_pack(child)
            detail = errors[0] if errors else "no stimpack.json or SKILL.md found"
            out.append(f"{SKILLS_MOUNT}/{child.name}/: not loaded — {detail}")
    return out


@tool(
    name="skill",
    description=(
        "Load a skill's instructions into context, or list what is installed. Use invoke to load a skill's "
        "expertise for the current task. Skills are files under skills/ in your workspace; list shows each one's "
        "path, where it applies, and any loading problems — run it after writing or editing a skill."
    ),
    parameters=[
        ToolParameter(
            name="action",
            type="string",
            description="list: every installed skill with path/eligibility/problems. invoke: load a skill's body into this conversation.",
            required=True,
            enum=["list", "invoke"],
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Skill name (required for invoke), e.g. product-photo or stimma-essentials/variations",
            required=False,
        ),
    ],
    # Visible in both agent and flow chats; per-environment eligibility is
    # enforced here at invoke time from each skill's `environments` frontmatter.
    scope="both",
)
async def skill_tool(
    action: str,
    name: str | None = None,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    chat_id: int = kwargs.get("chat_id")

    if action == "list":
        environment = await _chat_environment(session, chat_id)
        packs = list_installed_stimpacks()
        packs_by_name = {pack.name: pack for pack in packs}
        skills_root = skills_mount_target()
        visible = list_skills()
        hidden = shadowed_skills()
        lines: list[str] = []
        if visible:
            lines += [
                "| Name | Description | Where | From | Path | Notes |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for s in visible:
                pack = packs_by_name[s.pack_name]
                lines.append(
                    f"| {s.qualified_name} | {s.description} | {_where(s)} | {pack.display_name} | "
                    f"{_skill_path(pack, s, skills_root)} | {_notes(pack, s)} |"
                )
        else:
            lines.append(f"No skills installed. Write one at {SKILLS_MOUNT}/<slug>/SKILL.md.")
        if hidden:
            lines.append("")
            lines.append("Hidden by your forks: " + ", ".join(f"{o.qualified_name} → {f.qualified_name}" for o, f in hidden))
        problems = _precedence_problems(visible, hidden) + _pack_problems(packs) + _unloadable_dirs(packs, skills_root)
        if problems:
            lines.append("")
            lines.append("Problems:")
            lines.extend(f"- {p}" for p in problems)
        lines.append("")
        lines.append(
            f"This conversation is the '{environment}' environment; invoke only applies to skills offered there. "
            f"Skills are files: read or edit them at the paths above, add new ones under {SKILLS_MOUNT}/. "
            f"Marketplace packs are read-only — fork a skill by copying its folder to {SKILLS_MOUNT}/<slug>/ "
            "with the same name; your copy then takes precedence."
        )
        return "\n".join(lines)

    elif action == "invoke":
        if not name:
            return "Error: name is required for invoke"
        # Check if already invoked in this chat
        if session and chat_id:
            if await _is_skill_already_invoked(name, session, chat_id):
                return f"Skill '{name}' is already loaded in this conversation."
        loaded = load_skill(name)
        if not loaded:
            return f"Error: Skill '{name}' not found. Use skill(action=\"list\") to see available skills."
        environment = await _chat_environment(session, chat_id)
        if not getattr(loaded.skill.environments, environment, False):
            return f"Error: Skill '{loaded.skill.qualified_name}' is not available in this environment."
        # Inject the skill body as a conversation message via the
        # _injected_messages mechanism.
        injected = kwargs.get("_injected_messages")
        if injected is not None:
            header = f"## Skill: {loaded.skill.display_name}"
            if loaded.skill.overrides:
                header += f" (your version, overrides {loaded.skill.overrides})"
            injected.append({
                "skill_name": loaded.skill.qualified_name,
                "skill_display_name": loaded.skill.display_name,
                "content": f"{header}\n\n{loaded.content}",
            })
        return f"Loaded skill '{loaded.skill.display_name}'."

    return f"Error: Unknown action '{action}'"

"""Skill tool — list, invoke, create, edit, and delete skills.

Skills are the flat, agent-facing capability units inside stimpacks (the
installable packages). Invoking a skill lands its SKILL.md body into the
conversation. create/edit/delete manage user-authored skills, each stored as
its own single-skill stimpack.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter
from ..stimpacks import list_skills, find_skill, load_skill, save_stimpack, delete_stimpack

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


@tool(
    name="skill",
    description="Load a skill's instructions into context, or manage skills. Use invoke to load a skill's expertise for the current task.",
    parameters=[
        ToolParameter(
            name="action",
            type="string",
            description="Action to perform",
            required=True,
            enum=["list", "invoke", "create", "edit", "delete"],
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Skill name (required for invoke/create/edit/delete)",
            required=False,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Markdown content for the skill (required for create/edit)",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Short description of the skill (for create/edit)",
            required=False,
        ),
        ToolParameter(
            name="tags",
            type="array",
            description="Tags for the skill (for create/edit)",
            required=False,
            items={"type": "string"},
        ),
    ],
    # Visible in both agent and flow chats; per-environment eligibility is
    # enforced here at invoke time from each skill's `environments` frontmatter.
    scope="both",
)
async def skill_tool(
    action: str,
    name: str | None = None,
    content: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    chat_id: int = kwargs.get("chat_id")

    if action == "list":
        environment = await _chat_environment(session, chat_id)
        skills = [
            s for s in list_skills()
            if getattr(s.environments, environment, False)
        ]
        if not skills:
            return "No skills available. Use skill(action=\"create\") to create one."
        lines = ["| Name | Description | From |", "| --- | --- | --- |"]
        for s in skills:
            lines.append(f"| {s.qualified_name} | {s.description} | {s.pack_display_name} |")
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
            injected.append({
                "skill_name": loaded.skill.qualified_name,
                "skill_display_name": loaded.skill.display_name,
                "content": f"## Skill: {loaded.skill.display_name}\n\n{loaded.content}",
            })
        return f"Loaded skill '{loaded.skill.display_name}'."

    elif action == "create":
        if not name:
            return "Error: name is required for create"
        if not content:
            return "Error: content is required for create"
        # Check if already exists
        if find_skill(name):
            return f"Error: Skill '{name}' already exists. Use action=\"edit\" to update it."
        try:
            path = save_stimpack(name, content, description=description or "", tags=tags)
            return f"Created skill '{name}' at {path.name}"
        except ValueError as e:
            return f"Error: {e}"

    elif action == "edit":
        if not name:
            return "Error: name is required for edit"
        if not content:
            return "Error: content is required for edit"
        found = find_skill(name)
        if found and len(found[0].skills) > 1:
            return f"Error: Skill '{name}' is part of the '{found[0].display_name}' stimpack and cannot be edited here."
        try:
            path = save_stimpack(name, content, description=description or "", tags=tags)
            return f"Updated skill '{name}' at {path.name}"
        except ValueError as e:
            return f"Error: {e}"

    elif action == "delete":
        if not name:
            return "Error: name is required for delete"
        found = find_skill(name)
        if not found:
            return f"Error: Skill '{name}' not found"
        pack, _ = found
        if len(pack.skills) > 1:
            return f"Error: Skill '{name}' is part of the '{pack.display_name}' stimpack — uninstall the stimpack instead."
        if delete_stimpack(pack.name):
            return f"Deleted skill '{name}'"
        return f"Error: Skill '{name}' not found"

    return f"Error: Unknown action '{action}'"

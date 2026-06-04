"""Skill tool — list, invoke, create, edit, and delete reusable instruction docs."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter
from ..skills import list_skills, load_skill, save_skill, delete_skill

from core.logging import get_logger
from database import ChatItem

log = get_logger(__name__)


async def _is_skill_already_invoked(name: str, session: AsyncSession, chat_id: int) -> bool:
    """Check if a skill has already been invoked in this chat."""
    result = await session.execute(
        select(ChatItem.id)
        .where(
            ChatItem.chat_id == chat_id,
            ChatItem.item_type == "skill_injection",
        )
        .limit(50)
    )
    for (item_id,) in result:
        # Check metadata for skill_name — but since we store it in metadata,
        # we need to load the full item. For efficiency, use a JSON filter if DB supports it,
        # otherwise scan. Since this is bounded by skill invocations per chat (small), it's fine.
        pass

    # Simpler approach: query with metadata filter
    result = await session.execute(
        select(ChatItem)
        .where(
            ChatItem.chat_id == chat_id,
            ChatItem.item_type == "skill_injection",
        )
    )
    for item in result.scalars():
        if item.item_metadata:
            try:
                meta = json.loads(item.item_metadata) if isinstance(item.item_metadata, str) else item.item_metadata
                if meta.get("skill_name") == name:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
    return False


@tool(
    name="skill",
    description="Load skill instructions into context, or manage skill documents. Use invoke to load a skill's expertise for the current task.",
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
    if action == "list":
        skills = list_skills()
        if not skills:
            return "No skills available. Use skill(action=\"create\") to create one."
        lines = ["| Name | Description | Tier |", "| --- | --- | --- |"]
        for s in skills:
            lines.append(f"| {s.name} | {s.description} | {s.tier} |")
        return "\n".join(lines)

    elif action == "invoke":
        if not name:
            return "Error: name is required for invoke"
        session: AsyncSession = kwargs.get("session")
        chat_id: int = kwargs.get("chat_id")
        # Check if already invoked in this chat
        if session and chat_id:
            if await _is_skill_already_invoked(name, session, chat_id):
                return f"Skill '{name}' is already loaded in this conversation."
        loaded = load_skill(name)
        if not loaded:
            return f"Error: Skill '{name}' not found. Use skill(action=\"list\") to see available skills."
        # Inject skill content as a conversation message via the _injected_messages mechanism
        injected = kwargs.get("_injected_messages")
        if injected is not None:
            injected.append({
                "skill_name": name,
                "skill_display_name": loaded.info.display_name,
                "content": f"## Skill: {loaded.info.display_name}\n\n{loaded.content}",
            })
        return f"Loaded skill '{loaded.info.display_name}'."

    elif action == "create":
        if not name:
            return "Error: name is required for create"
        if not content:
            return "Error: content is required for create"
        # Check if already exists
        existing = load_skill(name)
        if existing:
            return f"Error: Skill '{name}' already exists. Use action=\"edit\" to update it."
        try:
            path = save_skill(name, content, description=description or "", tags=tags)
            return f"Created skill '{name}' at {path.name}"
        except ValueError as e:
            return f"Error: {e}"

    elif action == "edit":
        if not name:
            return "Error: name is required for edit"
        if not content:
            return "Error: content is required for edit"
        # Save to user skills dir
        try:
            path = save_skill(name, content, description=description or "", tags=tags)
            return f"Updated skill '{name}' at {path.name}"
        except ValueError as e:
            return f"Error: {e}"

    elif action == "delete":
        if not name:
            return "Error: name is required for delete"
        if delete_skill(name):
            return f"Deleted skill '{name}'"
        return f"Error: Skill '{name}' not found"

    return f"Error: Unknown action '{action}'"

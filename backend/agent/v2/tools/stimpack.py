"""Stimpack tool — list, invoke, create, edit, and delete stimpacks.

Invoking a stimpack lands its `skill` resource (SKILL.md) into the conversation.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter
from ..stimpacks import list_stimpacks, load_stimpack, save_stimpack, delete_stimpack

from core.logging import get_logger
from database import ChatItem

log = get_logger(__name__)


async def _is_stimpack_already_invoked(name: str, session: AsyncSession, chat_id: int) -> bool:
    """Check if a stimpack has already been invoked in this chat."""
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
                if meta.get("stimpack_name") == name:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
    return False


@tool(
    name="stimpack",
    description="Load a stimpack's instructions into context, or manage stimpacks. Use invoke to load a stimpack's expertise (its skill resource) for the current task.",
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
            description="Stimpack name (required for invoke/create/edit/delete)",
            required=False,
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Markdown content for the stimpack's skill resource (required for create/edit)",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Short description of the stimpack (for create/edit)",
            required=False,
        ),
        ToolParameter(
            name="tags",
            type="array",
            description="Tags for the stimpack (for create/edit)",
            required=False,
            items={"type": "string"},
        ),
    ],
    scope="both",
)
async def stimpack_tool(
    action: str,
    name: str | None = None,
    content: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    **kwargs,
) -> str:
    if action == "list":
        stimpacks = list_stimpacks()
        if not stimpacks:
            return "No stimpacks available. Use stimpack(action=\"create\") to create one."
        lines = ["| Name | Description | Tier |", "| --- | --- | --- |"]
        for s in stimpacks:
            lines.append(f"| {s.name} | {s.description} | {s.tier} |")
        return "\n".join(lines)

    elif action == "invoke":
        if not name:
            return "Error: name is required for invoke"
        session: AsyncSession = kwargs.get("session")
        chat_id: int = kwargs.get("chat_id")
        # Check if already invoked in this chat
        if session and chat_id:
            if await _is_stimpack_already_invoked(name, session, chat_id):
                return f"Stimpack '{name}' is already loaded in this conversation."
        loaded = load_stimpack(name)
        if not loaded:
            return f"Error: Stimpack '{name}' not found. Use stimpack(action=\"list\") to see available stimpacks."
        # Inject the stimpack's skill resource as a conversation message via the
        # _injected_messages mechanism.
        injected = kwargs.get("_injected_messages")
        if injected is not None:
            injected.append({
                "stimpack_name": name,
                "stimpack_display_name": loaded.info.display_name,
                "content": f"## Stimpack: {loaded.info.display_name}\n\n{loaded.content}",
            })
        return f"Loaded stimpack '{loaded.info.display_name}'."

    elif action == "create":
        if not name:
            return "Error: name is required for create"
        if not content:
            return "Error: content is required for create"
        # Check if already exists
        existing = load_stimpack(name)
        if existing:
            return f"Error: Stimpack '{name}' already exists. Use action=\"edit\" to update it."
        try:
            path = save_stimpack(name, content, description=description or "", tags=tags)
            return f"Created stimpack '{name}' at {path.name}"
        except ValueError as e:
            return f"Error: {e}"

    elif action == "edit":
        if not name:
            return "Error: name is required for edit"
        if not content:
            return "Error: content is required for edit"
        # Save to user stimpacks dir
        try:
            path = save_stimpack(name, content, description=description or "", tags=tags)
            return f"Updated stimpack '{name}' at {path.name}"
        except ValueError as e:
            return f"Error: {e}"

    elif action == "delete":
        if not name:
            return "Error: name is required for delete"
        if delete_stimpack(name):
            return f"Deleted stimpack '{name}'"
        return f"Error: Stimpack '{name}' not found"

    return f"Error: Unknown action '{action}'"

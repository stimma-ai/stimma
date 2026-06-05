"""Agent tool for persistent cross-session memory."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter
from core.logging import get_logger

log = get_logger(__name__)


@tool(
    name="save_memory",
    description=(
        "Save persistent memory that survives across conversations. "
        "Use to remember user preferences, project context, important decisions, or learned patterns. "
        "Memory is always visible in your system prompt. Content replaces the entire memory at the chosen scope."
    ),
    parameters=[
        ToolParameter(
            name="scope",
            type="string",
            description="Where to save: 'project' (this project only) or 'global' (all chats in this profile)",
            required=True,
            enum=["global", "project"],
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Full memory contents (replaces existing memory at this scope)",
            required=True,
        ),
    ],
    scope="both",
)
async def save_memory(
    scope: str,
    content: str,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    project_id: int | None = kwargs.get("project_id")

    content = content.strip()

    if scope == "project":
        if not project_id:
            return "Error: Cannot save project memory — this chat is not in a project."

        from database import Project
        result = await session.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        project = result.scalar_one_or_none()
        if not project:
            return f"Error: Project {project_id} not found."

        project.memory = content
        await session.commit()
        log.info("project memory updated", project_id=project_id, length=len(content))
        return f"Project memory saved ({len(content)} chars). It will appear in your system prompt next turn."

    elif scope == "global":
        from core.profile_context import get_current_profile
        from config import get_settings, reload_settings
        from config_writer import patch_profile_section

        profile_id = get_current_profile()
        agent_config = get_settings().get_agent_for_profile(profile_id)

        agent_data = {
            "additional_instructions": agent_config.additional_instructions,
            "memory": content,
            "tool_config": {
                "allowed_tools": agent_config.tool_config.allowed_tools,
                "denied_tools": agent_config.tool_config.denied_tools,
                "v2_permissions": agent_config.tool_config.v2_permissions,
            },
        }

        try:
            patch_profile_section(profile_id, "agent", agent_data)
        except ValueError as e:
            return f"Error: {e}"

        reload_settings()
        log.info("global memory updated", profile=profile_id, length=len(content))
        return f"Global memory saved ({len(content)} chars). It will appear in your system prompt next turn."

    else:
        return f"Error: Unknown scope '{scope}'. Use 'global' or 'project'."

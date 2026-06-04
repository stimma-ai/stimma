"""Resolve merged v2 agent config from profile, project, and chat settings."""

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import AgentToolConfig, get_settings
from core.profile_context import get_current_profile
from database import Chat, Project


@dataclass
class ResolvedAgentConfig:
    additional_instructions: str
    tool_config: AgentToolConfig
    global_memory: str
    project_memory: str


def merge_tool_configs(
    global_config: Optional[AgentToolConfig],
    project_config: Optional[Dict[str, Any]],
    chat_config: Optional[Dict[str, Any]],
) -> AgentToolConfig:
    """Merge tool config from profile -> project -> chat."""
    result = AgentToolConfig(
        allowed_tools=list(global_config.allowed_tools) if global_config else [],
        denied_tools=list(global_config.denied_tools) if global_config else [],
        v2_permissions=dict(global_config.v2_permissions) if global_config else {},
    )

    if project_config:
        if "allowed_tools" in project_config:
            result.allowed_tools = list(project_config.get("allowed_tools") or [])
        if "denied_tools" in project_config:
            result.denied_tools = list(project_config.get("denied_tools") or [])
        if "v2_permissions" in project_config:
            result.v2_permissions = dict(project_config.get("v2_permissions") or {})

    if chat_config:
        if "allowed_tools" in chat_config:
            result.allowed_tools = list(chat_config.get("allowed_tools") or [])
        if "denied_tools" in chat_config:
            result.denied_tools = list(chat_config.get("denied_tools") or [])
        if "v2_permissions" in chat_config:
            result.v2_permissions = dict(chat_config.get("v2_permissions") or {})

    return result


def _parse_json_object(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def resolve_agent_config(chat: Optional[Chat], session: Optional[AsyncSession]) -> ResolvedAgentConfig:
    """Resolve merged agent instructions and tool config for a v2 chat."""
    settings = get_settings()
    profile_id = get_current_profile()
    profile_agent_config = settings.get_agent_for_profile(profile_id)

    project_tool_config = None
    project_additional_instructions = None
    project_memory = ""
    chat_tool_config = None
    chat_additional_instructions = None

    if chat:
        chat_tool_config = _parse_json_object(chat.agent_tool_config)
        chat_additional_instructions = chat.additional_instructions

        if session and chat.project_id:
            project_result = await session.execute(
                select(Project).where(
                    Project.id == chat.project_id,
                    Project.deleted_at.is_(None),
                )
            )
            project = project_result.scalar_one_or_none()
            if project:
                project_tool_config = _parse_json_object(project.agent_tool_config)
                project_additional_instructions = project.additional_instructions
                project_memory = project.memory or ""

    tool_config = merge_tool_configs(
        profile_agent_config.tool_config,
        project_tool_config,
        chat_tool_config,
    )

    additional_parts = []
    if profile_agent_config.additional_instructions:
        additional_parts.append(profile_agent_config.additional_instructions)
    if project_additional_instructions:
        additional_parts.append(project_additional_instructions)
    if chat_additional_instructions is not None:
        additional_parts.append(chat_additional_instructions)

    return ResolvedAgentConfig(
        additional_instructions="\n\n".join(additional_parts),
        tool_config=tool_config,
        global_memory=profile_agent_config.memory,
        project_memory=project_memory,
    )

"""V2 agent permission checking and persistence."""

import json
import re
import shlex
from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import Chat, Project

log = get_logger(__name__)

# Tools that require permission prompts before execution
# Note: call_tool is NOT here — it uses per-STP-tool-id gating via check_stp_permission
GATED_TOOLS = {"bash", "browse_web", "run_code"}

# Legacy aliases — old permission keys that map to current tool names
PERMISSION_ALIASES = {}

PermissionDecision = Literal["allow", "deny", "ask"]

_AUTO_APPROVED_BASH_COMMANDS = {
    "cat",
    "egrep",
    "fgrep",
    "file",
    "find",
    "grep",
    "head",
    "ls",
    "pwd",
    "rg",
    "sed",
    "stat",
    "tail",
    "wc",
}

_BLOCKED_SHELL_CHARS = re.compile(r"[;&|<>`$()\{\}\n\r]")
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_MUTATING_FIND_ACTIONS = {
    "-delete",
    "-exec",
    "-execdir",
    "-fls",
    "-fprint",
    "-fprint0",
    "-fprintf",
    "-ok",
    "-okdir",
}


def _canonical_tool_name(tool_name: str) -> str:
    """Resolve a tool name to its canonical permission key."""
    return PERMISSION_ALIASES.get(tool_name, tool_name)


def _load_json_config(raw_config: str | None) -> dict:
    if not raw_config:
        return {}
    try:
        return json.loads(raw_config)
    except json.JSONDecodeError:
        return {}


async def _get_project_config(session: AsyncSession | None, chat: Chat) -> dict:
    if not session or not chat.project_id:
        return {}
    result = await session.execute(
        select(Project.agent_tool_config).where(
            Project.id == chat.project_id,
            Project.deleted_at.is_(None),
        )
    )
    return _load_json_config(result.scalar_one_or_none())


async def get_permission_decision(
    tool_name: str,
    chat: Chat,
    session: AsyncSession | None = None,
) -> PermissionDecision:
    """Resolve configured permission for a v2 tool.

    Non-gated tools are always allowed. Gated tools return the configured
    decision if one exists, otherwise "ask".
    """
    if tool_name not in GATED_TOOLS:
        return "allow"

    # Collect all keys to check (canonical + any legacy aliases that map here)
    check_keys = [tool_name]
    for alias, canonical in PERMISSION_ALIASES.items():
        if canonical == tool_name and alias not in check_keys:
            check_keys.append(alias)

    # Check chat-level permissions first
    chat_config = _load_json_config(chat.agent_tool_config)
    chat_v2 = chat_config.get("v2_permissions", {})
    for key in check_keys:
        if chat_v2.get(key) == "allow":
            return "allow"
        if chat_v2.get(key) == "deny":
            return "deny"

    # Then check project-level permissions
    project_config = await _get_project_config(session, chat)
    project_v2 = project_config.get("v2_permissions", {})
    for key in check_keys:
        if project_v2.get(key) == "allow":
            return "allow"
        if project_v2.get(key) == "deny":
            return "deny"

    # Check global profile-level permissions
    from config import get_settings
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(profile_id)
    global_v2 = agent_config.tool_config.v2_permissions
    for key in check_keys:
        if global_v2.get(key) == "allow":
            return "allow"
        if global_v2.get(key) == "deny":
            return "deny"

    # Not found — needs prompt
    return "ask"


async def check_permission(tool_name: str, chat: Chat, session: AsyncSession | None = None) -> bool:
    """Check if a v2 tool is permitted.

    Returns True if allowed, False if needs a permission prompt.
    Non-gated tools (e.g. ask_user) are always allowed.
    """
    return await get_permission_decision(tool_name, chat, session) == "allow"


async def check_permission_for_call(
    tool_name: str,
    tool_args: str | Mapping[str, Any] | None,
    chat: Chat,
    session: AsyncSession | None = None,
) -> bool:
    """Check if a concrete v2 tool call is permitted.

    A small class of read-only shell discovery commands is allowed without a
    prompt because it mirrors the already-ungated workspace file tools.
    """
    decision = await get_permission_decision(tool_name, chat, session)
    if decision == "allow":
        return True
    if decision == "deny":
        return False
    return is_auto_approved_tool_call(tool_name, tool_args)


def is_auto_approved_tool_call(
    tool_name: str,
    tool_args: str | Mapping[str, Any] | None,
) -> bool:
    """Return True for harmless discovery calls that should not prompt."""
    if tool_name != "bash":
        return False

    args = _coerce_tool_args(tool_args)
    command = str(args.get("command", "")).strip()
    return _is_read_only_workspace_discovery_command(command)


def _coerce_tool_args(tool_args: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(tool_args, Mapping):
        return dict(tool_args)
    if isinstance(tool_args, str):
        try:
            parsed = json.loads(tool_args) if tool_args else {}
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _is_read_only_workspace_discovery_command(command: str) -> bool:
    if not command or _BLOCKED_SHELL_CHARS.search(command):
        return False

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False

    if not tokens:
        return False

    executable = tokens[0].split("/")[-1]
    if executable not in _AUTO_APPROVED_BASH_COMMANDS:
        return False

    if executable == "find" and any(token in _MUTATING_FIND_ACTIONS for token in tokens[1:]):
        return False

    return all(_is_workspace_relative_token(token) for token in tokens[1:])


def _is_workspace_relative_token(token: str) -> bool:
    """Reject path escapes while allowing ordinary flags, patterns, and terms."""
    if not token:
        return True
    if token.startswith(("/", "~")) or _WINDOWS_ABSOLUTE_PATH.match(token):
        return False

    normalized = token.replace("\\", "/")
    if (
        normalized == ".."
        or normalized.startswith("../")
        or normalized.endswith("/..")
        or "/../" in normalized
    ):
        return False

    return True


async def check_stp_permission(
    stp_tool_id: str,
    chat: Chat,
    session: AsyncSession | None = None,
) -> bool:
    """Check if a specific STP tool is permitted for call_tool.

    Uses allowed_tools/denied_tools (same as V1) so the sidebar
    tool permissions section shows them.
    """
    if not stp_tool_id:
        return True

    # Check chat-level first
    chat_config = _load_json_config(chat.agent_tool_config)
    if stp_tool_id in chat_config.get("allowed_tools", []):
        return True
    if stp_tool_id in chat_config.get("denied_tools", []):
        return False

    # Then check project-level
    project_config = await _get_project_config(session, chat)
    if stp_tool_id in project_config.get("allowed_tools", []):
        return True
    if stp_tool_id in project_config.get("denied_tools", []):
        return False

    # Check global profile-level
    from config import get_settings
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(profile_id)
    if stp_tool_id in (agent_config.tool_config.allowed_tools or []):
        return True
    if stp_tool_id in (agent_config.tool_config.denied_tools or []):
        return False

    # Not found — needs prompt
    return False


async def apply_permission(
    tool_name: str, scope: str, approved: bool, chat: Chat
) -> None:
    """Persist a permission decision based on scope.

    scope: 'once' | 'chat' | 'always'
    """
    tool_name = _canonical_tool_name(tool_name)
    value = "allow" if approved else "deny"

    if scope == "once":
        return  # no-op

    if scope == "chat":
        config = {}
        if chat.agent_tool_config:
            try:
                config = json.loads(chat.agent_tool_config)
            except json.JSONDecodeError:
                pass
        v2 = config.setdefault("v2_permissions", {})
        v2[tool_name] = value
        chat.agent_tool_config = json.dumps(config)
        log.info(f"Set chat v2_permissions.{tool_name}={value}")

    elif scope == "always":
        await _add_to_global_v2_permissions(tool_name, value)
        log.info(f"Set global v2_permissions.{tool_name}={value}")


async def apply_stp_permission(
    stp_tool_id: str, scope: str, approved: bool, chat: Chat
) -> None:
    """Persist an STP tool permission using allowed_tools/denied_tools.

    This stores in the same format as V1 so the sidebar's tool permissions
    section displays them correctly.
    """
    if scope == "once":
        return

    list_key = "allowed_tools" if approved else "denied_tools"
    opposite_key = "denied_tools" if approved else "allowed_tools"

    if scope == "chat":
        config = {}
        if chat.agent_tool_config:
            try:
                config = json.loads(chat.agent_tool_config)
            except json.JSONDecodeError:
                pass

        # Add to the right list, remove from opposite
        tools_list = config.get(list_key, [])
        if stp_tool_id not in tools_list:
            tools_list.append(stp_tool_id)
        config[list_key] = tools_list

        opposite_list = config.get(opposite_key, [])
        if stp_tool_id in opposite_list:
            opposite_list.remove(stp_tool_id)
            config[opposite_key] = opposite_list

        chat.agent_tool_config = json.dumps(config)
        log.info(f"Set chat {list_key} += {stp_tool_id}")

    elif scope == "always":
        await _add_to_global_stp_permission(stp_tool_id, approved)
        log.info(f"Set global {list_key} += {stp_tool_id}")


async def _add_to_global_v2_permissions(tool_name: str, value: str) -> None:
    """Write a v2 permission to profile-level config.yaml."""
    from config import get_settings, reload_settings
    from config_writer import patch_profile_section
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(profile_id)

    current_v2 = dict(agent_config.tool_config.v2_permissions)
    current_v2[tool_name] = value

    agent_data = {
        "additional_instructions": agent_config.additional_instructions,
        "tool_config": {
            "allowed_tools": agent_config.tool_config.allowed_tools,
            "denied_tools": agent_config.tool_config.denied_tools,
                        "v2_permissions": current_v2,
        },
    }

    patch_profile_section(profile_id, "agent", agent_data)
    reload_settings()


async def _add_to_global_stp_permission(stp_tool_id: str, approved: bool) -> None:
    """Write an STP tool permission to profile-level config.yaml."""
    from config import get_settings, reload_settings
    from config_writer import patch_profile_section
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(profile_id)

    allowed = list(agent_config.tool_config.allowed_tools or [])
    denied = list(agent_config.tool_config.denied_tools or [])

    if approved:
        if stp_tool_id not in allowed:
            allowed.append(stp_tool_id)
        if stp_tool_id in denied:
            denied.remove(stp_tool_id)
    else:
        if stp_tool_id not in denied:
            denied.append(stp_tool_id)
        if stp_tool_id in allowed:
            allowed.remove(stp_tool_id)

    agent_data = {
        "additional_instructions": agent_config.additional_instructions,
        "tool_config": {
            "allowed_tools": allowed,
            "denied_tools": denied,
                        "v2_permissions": dict(agent_config.tool_config.v2_permissions),
        },
    }

    patch_profile_section(profile_id, "agent", agent_data)
    reload_settings()

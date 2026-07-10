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

# Tools that require permission prompts before execution.
# Shell (bash) is the only gated capability: it's the one tool that can reach outside the
# workspace sandbox to bring files in or push them out. run_code and browse_web are ungated
# — run_code is confined to its workspace + Stimma APIs (in-app effects are what the agent is
# for), and web browsing is read-only info gathering.
# Note: call_tool is NOT here — it uses per-STP-tool-id gating via check_stp_permission
GATED_TOOLS = {"bash"}

# Legacy aliases — old permission keys that map to current tool names
PERMISSION_ALIASES = {}

PermissionDecision = Literal["allow", "deny", "ask"]

# Shell commands that are auto-approved (no prompt) when every argument stays inside the
# workspace and there are no shell metacharacters. Read-only discovery (including `cd`, which
# only changes the shell's cwd within the one-shot subprocess it runs in) plus the in-workspace
# mutating trio (cp/mv/rm) — destruction is fine as long as it's provably inside the box; the
# workspace-relative path check below is what enforces "inside the box".
_AUTO_APPROVED_BASH_COMMANDS = {
    "cat",
    "cd",
    "cp",
    "egrep",
    "fgrep",
    "file",
    "find",
    "grep",
    "head",
    "echo",
    "ls",
    "mv",
    "pwd",
    "rg",
    "rm",
    "sed",
    "stat",
    "tail",
    "wc",
}

# Constructs that enable arbitrary code execution or expansion — never auto-approved.
_UNSAFE_SHELL_CHARS = re.compile(r"[`$(){}\n\r]")
# Redirections to the null device (or fd duplications) are harmless; stripped before analysis.
_NULL_REDIRECT = re.compile(r"(?:&|\d+)?>\s*/dev/null|\d*>&\d+")
# Pipeline / sequence separators — each segment is analysed independently.
_SEGMENT_SEP = re.compile(r"\|\||&&|[|;]")
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

    A small class of shell commands that provably stay inside the workspace is
    allowed without a prompt because it mirrors the already-ungated workspace
    file tools.
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
    """Return True for trivially-safe in-workspace calls that should not prompt."""
    if tool_name != "bash":
        return False

    args = _coerce_tool_args(tool_args)
    command = str(args.get("command", "")).strip()
    return _is_safe_workspace_command(command)


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


def _is_safe_workspace_command(command: str) -> bool:
    """True for shell that provably stays inside the workspace and cannot run
    arbitrary code.

    Allows read-only discovery plus in-workspace mutation, composed into safe
    pipelines/sequences (``|`` ``||`` ``&&`` ``;``) with redirects to /dev/null —
    the shapes the agent actually uses to browse the tool catalog, e.g.
    ``ls .stimma/tools/text-to-image/ 2>/dev/null || echo "no dir"``. Anything with
    command substitution, expansion, or a redirect to a real path falls through
    to a prompt.
    """
    if not command or _UNSAFE_SHELL_CHARS.search(command):
        return False

    # Drop harmless null-device redirects, then reject any redirect that remains
    # (it targets a real path we can't prove stays in-workspace).
    stripped = _NULL_REDIRECT.sub(" ", command)
    if "<" in stripped or ">" in stripped:
        return False

    # A lone ``&`` (background) is not part of ``&&`` sequencing — reject it.
    if "&" in stripped.replace("&&", ""):
        return False

    segments = [seg.strip() for seg in _SEGMENT_SEP.split(stripped) if seg.strip()]
    if not segments:
        return False

    return all(_is_safe_command_segment(seg) for seg in segments)


def _is_safe_command_segment(segment: str) -> bool:
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return False

    if not tokens:
        return False

    executable = tokens[0].split("/")[-1]
    if executable not in _AUTO_APPROVED_BASH_COMMANDS:
        return False

    # echo only emits its literal arguments (expansion is already rejected above).
    if executable == "echo":
        return True

    if executable == "find" and any(token in _MUTATING_FIND_ACTIONS for token in tokens[1:]):
        return False

    # cd with no argument goes to $HOME, and `cd -` goes to the previous directory —
    # both escape the workspace without tripping the path-token checks below. Require
    # exactly one real (non `-`) argument so the same workspace-relative check applies.
    if executable == "cd":
        if len(tokens) != 2 or tokens[1] == "-":
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


async def get_stp_permission_decision(
    stp_tool_id: str,
    chat: Chat,
    session: AsyncSession | None = None,
) -> PermissionDecision:
    """Resolve the configured permission for a specific STP tool.

    Uses allowed_tools/denied_tools (same as V1) so the settings "Generation
    Tools" list shows them. Resolution order: chat → project → global profile,
    else "ask" (first use of an unconfigured tool). Empty tool id → "allow"
    (nothing to gate).
    """
    if not stp_tool_id:
        return "allow"

    # Check chat-level first
    chat_config = _load_json_config(chat.agent_tool_config)
    if stp_tool_id in chat_config.get("allowed_tools", []):
        return "allow"
    if stp_tool_id in chat_config.get("denied_tools", []):
        return "deny"

    # Then check project-level
    project_config = await _get_project_config(session, chat)
    if stp_tool_id in project_config.get("allowed_tools", []):
        return "allow"
    if stp_tool_id in project_config.get("denied_tools", []):
        return "deny"

    # Check global profile-level
    from config import get_settings
    from core.profile_context import get_current_profile

    settings = get_settings()
    profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(profile_id)
    if stp_tool_id in (agent_config.tool_config.allowed_tools or []):
        return "allow"
    if stp_tool_id in (agent_config.tool_config.denied_tools or []):
        return "deny"

    # Not found — needs prompt
    return "ask"


async def check_stp_permission(
    stp_tool_id: str,
    chat: Chat,
    session: AsyncSession | None = None,
) -> bool:
    """Check if a specific STP tool is permitted for call_tool.

    Thin ``== "allow"`` wrapper over :func:`get_stp_permission_decision`. Legacy
    callers that only distinguish permitted/not-permitted (the top-level
    ``call_tool`` gate) use this; the in-``run_code`` gate uses the 3-state form
    so it can tell "deny" (raise) from "ask" (prompt).
    """
    return await get_stp_permission_decision(stp_tool_id, chat, session) == "allow"


async def apply_permission(
    tool_name: str, scope: str, approved: bool, chat: Chat
) -> None:
    """Persist a shell permission decision based on scope.

    scope: 'once' (no-op) | 'chat'. The chat is the broadest scope — there is no
    global/profile grant for shell, so permission never leaks past the chat where
    it was granted. A legacy 'always' from a stale client is treated as 'chat'.
    """
    if scope == "once":
        return  # no-op

    tool_name = _canonical_tool_name(tool_name)
    value = "allow" if approved else "deny"

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

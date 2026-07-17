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
# workspace-relative path check below is what enforces "inside the box". Plain http(s)
# downloads via curl/wget are handled separately in _is_safe_download_segment.
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
    "mkdir",
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
# Shell operator characters shlex emits as punctuation-run tokens (see
# _split_safe_segments). A token made entirely of these is an operator; a token
# merely containing one (e.g. a quoted URL with `&` in its query string) is a word.
_SHELL_PUNCT_CHARS = set("();<>|&")
# Pipeline / sequence separators — each segment is analysed independently.
_SEGMENT_SEPARATOR_TOKENS = {"&&", "||", "|", ";"}
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

# Read-only downloads into the workspace (same risk class as the ungated
# browse_web: public http(s) GET, output confined to the workspace). Anything
# that sends data (-d/-F/-T), changes the method, adds headers/credentials, or
# reads config falls through to a prompt. Allowlist, not denylist: an
# unrecognized flag rejects the segment.
_DOWNLOAD_COMMANDS = {"curl", "wget"}
_CURL_BARE_FLAGS = {
    "-L", "--location",
    "-s", "--silent",
    "-S", "--show-error",
    "-f", "--fail",
    "-O", "--remote-name",
    "--compressed",
    "-G", "--get",
}
# Single-letter curl flags that may appear combined (e.g. -sSfL, -sLO).
_CURL_COMBINABLE = set("LsSfOG")
_CURL_PATH_VALUE_FLAGS = {"-o", "--output"}
_CURL_NUMERIC_VALUE_FLAGS = {"-m", "--max-time", "--connect-timeout", "--retry"}
_WGET_BARE_FLAGS = {"-q", "--quiet", "-nv", "--no-verbose"}
_WGET_PATH_VALUE_FLAGS = {"-O", "--output-document", "-P", "--directory-prefix"}
_WGET_NUMERIC_VALUE_FLAGS = {"--timeout", "--tries", "-T", "-t"}
_DOWNLOAD_URL = re.compile(r"^https?://", re.IGNORECASE)


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

    segments = _split_safe_segments(command)
    if not segments:
        return False

    return all(_is_safe_command_segment(seg) for seg in segments)


def _split_safe_segments(command: str) -> list[list[str]] | None:
    """Quote-aware split of a command into pipeline/sequence segments.

    Uses shlex with punctuation_chars so operators arrive as their own
    punctuation-run tokens while quoted text stays inside its word — a URL
    like ``"https://x.com/a.jpg?h=1&itok=2"`` is one word token, not a
    background ``&``. Only ``&&`` ``||`` ``|`` ``;`` separators and redirects
    to the null device (``2>/dev/null``, ``2>&1``) are accepted; any other
    operator (``<``, lone ``&``, a redirect to a real path) rejects the whole
    command. Returns None when the command can't be proven safe.
    """
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""  # '#' is data (URL fragments), not a comment
    try:
        tokens = list(lex)
    except ValueError:
        return None

    segments: list[list[str]] = []
    current: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token and all(ch in _SHELL_PUNCT_CHARS for ch in token):
            if token in _SEGMENT_SEPARATOR_TOKENS:
                if current:
                    segments.append(current)
                    current = []
            elif token == ">":
                # Only the null device is a harmless target. shlex splits a
                # leading fd number off as its own word (``2>/dev/null`` →
                # '2', '>', '/dev/null') — drop it before checking.
                if current and current[-1].isdigit():
                    current.pop()
                i += 1
                if i >= len(tokens) or tokens[i] != "/dev/null":
                    return None
            elif token == ">&":
                # fd duplication, e.g. ``2>&1``
                if current and current[-1].isdigit():
                    current.pop()
                i += 1
                if i >= len(tokens) or not tokens[i].isdigit():
                    return None
            else:
                # ``<``, lone ``&``, ``>>``, subshell parens, ... — not provably safe.
                return None
        else:
            current.append(token)
        i += 1
    if current:
        segments.append(current)
    return segments


def _is_safe_command_segment(tokens: list[str]) -> bool:
    if not tokens:
        return False

    executable = tokens[0].split("/")[-1]
    if executable in _DOWNLOAD_COMMANDS:
        return _is_safe_download_segment(executable, tokens[1:])
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


def _is_safe_download_segment(executable: str, args: list[str]) -> bool:
    """True for a curl/wget invocation that is provably a plain GET of http(s)
    URLs with output confined to the workspace."""
    if executable == "curl":
        bare = _CURL_BARE_FLAGS
        path_value = _CURL_PATH_VALUE_FLAGS
        numeric_value = _CURL_NUMERIC_VALUE_FLAGS
        combinable = _CURL_COMBINABLE
    else:
        bare = _WGET_BARE_FLAGS
        path_value = _WGET_PATH_VALUE_FLAGS
        numeric_value = _WGET_NUMERIC_VALUE_FLAGS
        combinable = set()

    saw_url = False
    i = 0
    while i < len(args):
        token = args[i]
        if _DOWNLOAD_URL.match(token):
            saw_url = True
        elif token in bare:
            pass
        elif token in path_value:
            i += 1
            if i >= len(args):
                return False
            value = args[i]
            if value.startswith("-") or not _is_workspace_relative_token(value):
                return False
        elif token in numeric_value:
            i += 1
            if i >= len(args) or not args[i].isdigit():
                return False
        elif (
            combinable
            and len(token) > 2
            and token.startswith("-")
            and not token.startswith("--")
            and set(token[1:]) <= combinable
        ):
            pass  # combined bare flags, e.g. -sSfL
        else:
            # Unrecognized flag, non-http(s) scheme (file:, ftp:), or stray
            # argument — not provably a safe download.
            return False
        i += 1

    return saw_url


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

    # Built-in tools (reverse, resize, crop, ...) run in-process, cost nothing,
    # and only touch library/workspace media — the same surface the ungated
    # run_code already has. Prompting for them reads as noise, so they default
    # to allow. An explicit deny above still wins.
    if _is_builtin_tool(stp_tool_id):
        return "allow"

    # Not found — needs prompt
    return "ask"


def _is_builtin_tool(stp_tool_id: str) -> bool:
    """True when the tool belongs to the in-process builtin provider."""
    try:
        from providers.registry import ProviderRegistry

        pt = ProviderRegistry.get_instance().get_tool(stp_tool_id)
        if pt:
            provider, _descriptor = pt
            return getattr(provider, "provider_type", None) == "builtin"
    except Exception:
        pass
    # Registry unavailable (e.g. unit tests) — the id prefix is the provider id.
    return stp_tool_id.startswith("builtin:")


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

"""Progressive discovery of STP provider tools."""

import copy
import json
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from ..tools_registry import tool, ToolParameter

from config import get_settings
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import ChatItem
from providers.registry import ProviderRegistry
from agent.tools.stp_utils import _normalize_lora_name
from ..agent_config import resolve_agent_config

log = get_logger(__name__)


def _strip_large_enums(schema: Dict[str, Any], tool_id: str, threshold: int = 20) -> Dict[str, Any]:
    """Deep-copy schema and replace large enum arrays with truncated examples + search hint."""
    schema = copy.deepcopy(schema)
    _walk_and_strip(schema, tool_id, threshold)
    return schema


def _walk_and_strip(obj: Any, tool_id: str, threshold: int) -> None:
    """Recursively walk schema and strip large enums in-place."""
    if not isinstance(obj, dict):
        return

    if "enum" in obj and isinstance(obj["enum"], list) and len(obj["enum"]) > threshold:
        total = len(obj["enum"])
        obj["enum"] = obj["enum"][:5]
        obj["x-search-hint"] = (
            f"Showing 5 of {total} options. "
            f"Use search_options(tool_id='{tool_id}', param='...', query='...') to search."
        )

    for key, value in obj.items():
        if isinstance(value, dict):
            _walk_and_strip(value, tool_id, threshold)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _walk_and_strip(item, tool_id, threshold)


def _find_enum_values(descriptor, param: str) -> Optional[List[str]]:
    """Walk parameter_schema to find enum values at a dotted param path.

    E.g. param="loras.path" navigates properties.loras.items.properties.path.enum
    """
    parts = param.split(".")
    return _navigate_schema(descriptor.parameter_schema or {}, parts)


def _navigate_schema(schema: Dict[str, Any], parts: List[str]) -> Optional[List[str]]:
    """Navigate a JSON schema to find enum values at a property path."""
    current = schema
    for i, part in enumerate(parts):
        props = current.get("properties", {})
        if part not in props:
            return None
        current = props[part]

        # If this isn't the last part, we may need to traverse into items (arrays)
        if i < len(parts) - 1:
            if current.get("type") == "array" and "items" in current:
                current = current["items"]

    return current.get("enum")


async def _get_recent_tool_id_for_task(
    session,
    chat_id: int,
    task_type: str,
    registry: ProviderRegistry,
) -> Optional[str]:
    """Return the most recent successful call_tool tool_id for this task type."""
    result = await session.execute(
        select(ChatItem)
        .where(
            ChatItem.chat_id == chat_id,
            ChatItem.item_type.in_(["tool_call", "tool_result"]),
        )
        .order_by(ChatItem.created_at.desc())
        .limit(200)
    )
    items = result.scalars().all()

    tool_results: Dict[str, str] = {}
    tool_calls: Dict[str, str] = {}
    ordered_ids: List[str] = []

    for item in items:
        if item.item_type == "tool_result" and item.tool_call_id and item.tool_result:
            tool_results[item.tool_call_id] = item.tool_result
        elif (
            item.item_type == "tool_call"
            and item.tool_call_id
            and item.tool_name == "call_tool"
            and item.tool_args
        ):
            tool_calls[item.tool_call_id] = item.tool_args
            ordered_ids.append(item.tool_call_id)

    for tool_call_id in ordered_ids:
        result_text = tool_results.get(tool_call_id, "")
        if not result_text or result_text.startswith("Error:"):
            continue

        tool_args = tool_calls.get(tool_call_id)
        if not tool_args:
            continue

        try:
            parsed_args = json.loads(tool_args)
        except (json.JSONDecodeError, TypeError):
            continue

        tool_id = parsed_args.get("tool_id")
        if not tool_id:
            continue

        provider_tool = registry.get_tool(tool_id)
        if not provider_tool:
            continue

        _, descriptor = provider_tool
        inputs = parsed_args.get("inputs", {})

        try:
            from .call_tool import _resolve_effective_task_type

            effective_task_type = _resolve_effective_task_type(descriptor, inputs)
        except Exception:
            task_types = list(descriptor.task_types or [])
            effective_task_type = descriptor.task_type or (task_types[0] if task_types else "")

        if effective_task_type == task_type:
            return tool_id

    return None


def _tool_sort_key(
    tool_id: str,
    recent_tool_id: Optional[str],
    approved_tools: set[str],
) -> tuple[int, int, str]:
    return (
        0 if tool_id == recent_tool_id else 1,
        0 if tool_id in approved_tools else 1,
        tool_id,
    )


async def _resolve_config_and_recent(session, chat_id, task_type, registry):
    """Shared helper to resolve agent config and recent tool ID."""
    resolved_config = None
    recent_tool_id = None
    if session is not None and chat_id is not None:
        try:
            from database import Chat

            chat = await session.get(Chat, chat_id)
            resolved_config = await resolve_agent_config(chat, session)
            if task_type:
                recent_tool_id = await _get_recent_tool_id_for_task(
                    session, chat_id, task_type, registry
                )
        except Exception:
            resolved_config = None
            recent_tool_id = None
    return resolved_config, recent_tool_id


@tool(
    name="list_task_types",
    description=(
        "See available task types (text-to-image, image-to-image, etc.). "
        "Start here, then use list_tools to see tools for a task type."
    ),
    parameters=[],
    scope="both",
)
async def list_task_types(**kwargs) -> str:
    registry = ProviderRegistry.get_instance()
    return _list_task_types(registry)


@tool(
    name="list_tools",
    description=(
        "See tools for a task type. Prefer [preferred] tools. "
        "Use after list_task_types, then get_schema for parameter details."
    ),
    parameters=[
        ToolParameter(
            name="task_type",
            type="string",
            description="Task type to list tools for (e.g. 'text-to-image')",
        ),
    ],
    scope="both",
)
async def list_tools(task_type: str, **kwargs) -> str:
    registry = ProviderRegistry.get_instance()
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")
    resolved_config, recent_tool_id = await _resolve_config_and_recent(
        session, chat_id, task_type, registry
    )
    return _list_tools(registry, task_type, resolved_config, recent_tool_id)


@tool(
    name="get_schema",
    description=(
        "Get a tool's parameter schema. Only when you need param details. "
        "Use after list_tools to pick a tool_id."
    ),
    parameters=[
        ToolParameter(
            name="tool_id",
            type="string",
            description="Full tool ID (e.g. 'comfyui:flux-klein-9b')",
        ),
    ],
    scope="both",
)
async def get_schema(tool_id: str, **kwargs) -> str:
    registry = ProviderRegistry.get_instance()
    return _get_schema(registry, tool_id)


@tool(
    name="search_options",
    description=(
        "Search large enum values for a tool parameter. "
        "Use when get_schema shows truncated options with a search hint."
    ),
    parameters=[
        ToolParameter(
            name="tool_id",
            type="string",
            description="Full tool ID",
        ),
        ToolParameter(
            name="param",
            type="string",
            description="Parameter path to search (e.g. 'loras.path')",
        ),
        ToolParameter(
            name="query",
            type="string",
            description="Search query (e.g. 'anime')",
        ),
    ],
    scope="both",
)
async def search_options_tool(tool_id: str, param: str, query: str, **kwargs) -> str:
    registry = ProviderRegistry.get_instance()
    return _search_options(registry, tool_id, param, query)


def _list_task_types(registry: ProviderRegistry) -> str:
    all_tools = registry.list_all_tools()
    if not all_tools:
        return "No tools available. Check that a provider is connected."

    type_counts: Dict[str, int] = defaultdict(int)
    for full_id, provider, descriptor in all_tools:
        for tt in descriptor.task_types:
            type_counts[tt] += 1

    lines = ["Available task types:\n"]
    for tt, count in sorted(type_counts.items()):
        lines.append(f"- {tt} ({count} tool{'s' if count != 1 else ''})")

    return "\n".join(lines)


def get_tool_display_name(tool_id: str) -> Optional[str]:
    """Look up the human-readable display name for a tool_id like 'comfyui:flux-klein-9b'."""
    try:
        registry = ProviderRegistry()
        all_tools = registry.list_all_tools()
        for full_id, provider, descriptor in all_tools:
            if full_id == tool_id:
                return descriptor.name
    except Exception:
        pass
    return None


def _list_tools(
    registry: ProviderRegistry,
    task_type: str,
    resolved_config=None,
    recent_tool_id: Optional[str] = None,
) -> str:
    tools = registry.list_tools_by_task_type(task_type)
    denied_tools = set()
    approved_tools: set[str] = set()
    if resolved_config is not None:
        denied_tools = set(resolved_config.tool_config.denied_tools or [])
        approved_tools = set(resolved_config.tool_config.allowed_tools or [])
    else:
        try:
            settings = get_settings()
            profile_id = get_current_profile()
            agent_config = settings.get_agent_for_profile(profile_id)
            denied_tools = set(agent_config.tool_config.denied_tools or [])
            approved_tools = set(agent_config.tool_config.allowed_tools or [])
        except Exception:
            pass

    tools = [tool for tool in tools if tool[0] not in denied_tools]
    if not tools:
        return f"No tools found for task type '{task_type}'."

    tools.sort(
        key=lambda item: _tool_sort_key(
            item[0],
            recent_tool_id,
            approved_tools,
        )
    )

    lines = [f"Tools for {task_type}:\n"]
    for full_id, provider, descriptor in tools:
        desc = descriptor.description or descriptor.subtitle or descriptor.name
        # Truncate long descriptions
        if len(desc) > 100:
            desc = desc[:97] + "..."
        badges = []
        if full_id == recent_tool_id:
            badges.append("recent")
        if full_id in approved_tools:
            badges.append("approved")
        badge_text = f" [{' / '.join(badges)}]" if badges else ""
        lines.append(f"- {full_id}: {descriptor.name} — {desc}{badge_text}")

    return "\n".join(lines)


# Parameters the agent should not override unless the user asks.
# Collapsed to a compact summary (type, default, range) so the LLM
# knows they exist but isn't tempted to fill them in unprompted.
_AUTO_DEFAULT_PARAMS = {"steps", "cfg", "guidance", "sampler", "scheduler"}


def _collapse_auto_params(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse auto-default params to a compact summary so the LLM doesn't override them."""
    schema = copy.deepcopy(schema)
    props = schema.get("properties", {})
    for key in _AUTO_DEFAULT_PARAMS:
        if key not in props or "default" not in props[key]:
            continue
        prop = props[key]
        # Build compact summary: "auto-default: 4 (range 1-50). Only pass if user requests."
        summary = f"auto-default: {prop['default']}"
        if "minimum" in prop and "maximum" in prop:
            summary += f" (range {prop['minimum']}-{prop['maximum']})"
        elif "enum" in prop:
            summary += f" (options: {', '.join(str(v) for v in prop['enum'])})"
        summary += ". Only pass if user requests."
        props[key] = {"description": summary}
    return schema


def _get_schema(registry: ProviderRegistry, tool_id: str) -> str:
    if not tool_id:
        return "Error: tool_id is required for get_schema"

    provider_tool = registry.get_tool(tool_id)
    if not provider_tool:
        return f"Error: Tool '{tool_id}' not found."

    provider, descriptor = provider_tool

    import json

    result = {
        "tool_id": tool_id,
        "name": descriptor.name,
        "task_types": descriptor.task_types,
    }

    if descriptor.parameter_schema:
        cleaned = _strip_large_enums(descriptor.parameter_schema, tool_id)
        result["parameter_schema"] = _collapse_auto_params(cleaned)

    # Enrich x-controlnet with human-readable descriptions
    _enrich_controlnet_info(result)

    return json.dumps(result, indent=2, default=str)


_CONTROLNET_DESCRIPTIONS = {
    "canny": "Edge detection — preserves outlines and boundaries. Use for 'same composition' or 'same outline'.",
    "depth": "Depth estimation — preserves spatial layout, foreground/background separation.",
    "lineart": "Line art extraction — basic structural lines.",
    "lineart_realistic": "Realistic line art — neural network, best for photographic sources.",
    "lineart_anime": "Anime-style line art — optimized for illustration/anime.",
    "pose": "Body pose estimation — preserves posture and body position.",
    "pose_hands": "Pose with hands — body position plus hand skeleton detail.",
}


def _enrich_controlnet_info(result: Dict[str, Any]) -> None:
    """Replace bare x-controlnet lists with descriptive objects in schema properties."""
    for schema_key in ("parameter_schema",):
        schema = result.get(schema_key)
        if not isinstance(schema, dict):
            continue
        for prop_name, prop_info in schema.get("properties", {}).items():
            if not isinstance(prop_info, dict):
                continue
            cn_list = prop_info.get("x-controlnet")
            if isinstance(cn_list, list) and cn_list and isinstance(cn_list[0], str):
                prop_info["x-controlnet"] = [
                    {"id": cn_id, "description": _CONTROLNET_DESCRIPTIONS.get(cn_id, cn_id)}
                    for cn_id in cn_list
                ]


def _search_options(
    registry: ProviderRegistry, tool_id: str, param: str, query: str
) -> str:
    if not tool_id or not param or not query:
        return "Error: tool_id, param, and query are all required for search_options"

    provider_tool = registry.get_tool(tool_id)
    if not provider_tool:
        return f"Error: Tool '{tool_id}' not found."

    provider, descriptor = provider_tool

    enum_values = _find_enum_values(descriptor, param)
    if enum_values is None:
        return f"Error: No enum values found for param '{param}' in tool '{tool_id}'."

    # Fuzzy search: substring match + SequenceMatcher
    query_lower = query.lower()
    query_norm = _normalize_lora_name(query)

    scored: List[tuple] = []
    for value in enum_values:
        value_lower = value.lower()
        value_norm = _normalize_lora_name(value)

        # Substring match gets high score
        if query_lower in value_lower or query_lower in value_norm:
            scored.append((value, 1.0))
            continue

        # SequenceMatcher on normalized names
        ratio = SequenceMatcher(None, query_norm, value_norm).ratio()
        if ratio > 0.4:
            scored.append((value, ratio))

    # Sort by score descending, take top 20
    scored.sort(key=lambda x: x[1], reverse=True)
    results = [v for v, s in scored[:20]]

    if not results:
        return f"No matches for '{query}' in {param} ({len(enum_values)} total options)."

    lines = [f"Search results for '{query}' in {param} ({len(results)} of {len(enum_values)} total):\n"]
    for r in results:
        lines.append(f"- {r}")

    return "\n".join(lines)

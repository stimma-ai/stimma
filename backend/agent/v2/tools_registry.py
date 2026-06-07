"""V2 tool registry with @tool decorator."""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Dict, Optional


# Valid scopes for a registered tool. "agent" tools are only visible to the
# main agent loop; "recipe" tools are only visible inside the recipe chat
# (its chat is bound to a recipe_id); "both" tools are shared. The recipe
# chat must not see agent-sandbox tools like run_code / sdk_help / library,
# otherwise the model will pull ``stimma.library`` documentation into
# recipe program.py edits and generate code that can't run in the recipe
# sandbox.
VALID_SCOPES = frozenset({"agent", "recipe", "both"})


# Tools retired from the agent surface in favour of the filesystem tool catalog
# (.stimma/) plus code-only invocation (run_code / run_file). The agent now
# discovers tools by reading .stimma/tools/ with read_file/glob/grep and calls
# them via `from stimma.tools.<task> import <tool>`, instead of this RPC funnel.
#
# The underlying implementations are deliberately NOT deleted — execute_call_tool
# still backs the stimma.tools.* import bindings (via StimmaSDK._dispatch_tool), and
# _get_schema / get_tool_display_name / get_sdk_quick_ref are reused by the lint and
# help paths. They are simply hidden from the model and made uninvocable here, in one
# place, so a stale schema or hallucinated name can't reach them.
RETIRED_TOOLS = frozenset({
    "call_tool",
    "list_task_types",
    "list_tools",
    "get_schema",
    "search_options",
    "sdk_help",
})


@dataclass
class ToolParameter:
    name: str
    type: str  # "string", "integer", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None
    items: Optional[Dict[str, Any]] = None  # For array types: schema of each item


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable
    parameters: List[ToolParameter] = field(default_factory=list)
    scope: str = "agent"

    def visible_in(self, scope: str) -> bool:
        """True if this tool should be exposed in the given chat scope.

        ``scope`` is one of "agent" / "recipe". A tool tagged "both" is
        visible in either; a tool tagged "agent" only shows in agent chats;
        a "recipe" tool only shows in recipe chats.
        """
        if self.scope == "both":
            return True
        return self.scope == scope

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function-calling tool schema."""
        properties = {}
        required = []
        for p in self.parameters:
            prop = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            if p.items:
                prop["items"] = p.items
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }
        if required:
            schema["function"]["parameters"]["required"] = required
        return schema


_tools: Dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: Optional[List[ToolParameter]] = None,
    *,
    scope: str = "agent",
):
    """Decorator to register a v2 tool.

    ``scope`` controls which chat loops see the tool — "agent" (default)
    hides it from recipe chats; "recipe" hides it from the main agent;
    "both" exposes it everywhere.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(
            f"tool({name!r}): invalid scope {scope!r}; must be one of "
            f"{sorted(VALID_SCOPES)}"
        )

    def decorator(func: Callable) -> Callable:
        _tools[name] = Tool(
            name=name,
            description=description,
            handler=func,
            parameters=parameters or [],
            scope=scope,
        )
        return func
    return decorator


def get_tools_schema(scope: str = "agent") -> List[dict]:
    """Return OpenAI-format tool schemas visible in the given chat scope.

    Defaults to the main-agent view so existing callers that don't yet pass
    a scope keep behaving the same. Recipe chats pass ``scope="recipe"``
    to get a narrowed set that excludes ``run_code`` / ``sdk_help`` /
    ``library`` and other agent-sandbox-only tools.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(
            f"get_tools_schema: invalid scope {scope!r}; must be one of "
            f"{sorted(VALID_SCOPES)}"
        )
    return [
        t.to_openai_schema()
        for t in _tools.values()
        if t.visible_in(scope) and t.name not in RETIRED_TOOLS
    ]


def get_tool(name: str, scope: Optional[str] = None) -> Optional[Tool]:
    """Get a tool by name. If ``scope`` is given, return ``None`` when the
    tool exists but isn't visible in that scope — so a stale schema or
    hallucinated name can't slip an agent-only tool into recipe chat.
    """
    if name in RETIRED_TOOLS:
        return None
    t = _tools.get(name)
    if t is None:
        return None
    if scope is not None and not t.visible_in(scope):
        return None
    return t


def get_all_tools() -> Dict[str, Tool]:
    """Get all registered tools."""
    return dict(_tools)

"""Agent-level tool for SDK documentation lookup."""

from ..tools_registry import tool, ToolParameter


@tool(
    name="sdk_help",
    description=(
        "Browse documentation for the stimma Python SDK used inside run_code. "
        "Three levels: no arguments → list method groups, "
        "group name → methods in that group, "
        "method name → full docs with parameters and examples."
    ),
    parameters=[
        ToolParameter(
            name="topic",
            type="string",
            description="A group name (e.g. 'core', 'library', 'image') or method name (e.g. 'generated_tools', 'adjust'). Omit to see available groups.",
            required=False,
        ),
    ],
)
async def sdk_help_tool(topic: str | None = None, **kwargs) -> str:
    from ..sdk_help import get_sdk_overview, get_sdk_method_help

    if topic is None:
        return get_sdk_overview()
    return get_sdk_method_help(topic)

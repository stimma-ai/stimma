"""
Agent tool system for LLM-powered chat agents.

This module provides a decorator-based system for defining tools that the agent can use.
"""
import inspect
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass
import json


@dataclass
class ToolParameter:
    """Represents a tool parameter."""
    name: str
    type: str
    description: str
    required: bool
    default: Any = None
    items_schema: Dict[str, Any] = None  # For array types: schema of array items


@dataclass
class Tool:
    """Represents a tool that can be called by the agent."""
    name: str
    description: str
    parameters: List[ToolParameter]
    function: Callable
    injected_params: List[str] = None  # Params injected at runtime (chat_id, session)


# Global tool registry
_tool_registry: Dict[str, Tool] = {}


def tool(name: str, description: str, injected_params: List[str] = None, param_schemas: Dict[str, Dict[str, Any]] = None):
    """
    Decorator to register a function as a tool.

    Args:
        name: The tool name
        description: Tool description
        injected_params: List of parameter names that should be hidden from the LLM
                        (these will be injected by the system at runtime)
        param_schemas: Optional dict mapping param names to custom schema definitions.
                      Use for complex types like arrays with items schema.
                      Example: {"prompts": {"description": "...", "items_schema": {...}}}

    Example:
        @tool(name="generate_image", description="Generate an image",
              injected_params=["chat_id", "session"])
        async def generate_image(chat_id: int, session: AsyncSession, prompt: str, width: int = 512):
            ...
    """
    if injected_params is None:
        injected_params = []
    if param_schemas is None:
        param_schemas = {}

    def decorator(func: Callable):
        # Extract parameters from function signature
        sig = inspect.signature(func)
        parameters = []

        for param_name, param in sig.parameters.items():
            # Skip 'self' or 'cls'
            if param_name in ('self', 'cls'):
                continue

            # Skip injected parameters
            if param_name in injected_params:
                continue

            # Determine type
            param_type = 'string'
            if param.annotation != inspect.Parameter.empty:
                if param.annotation == int:
                    param_type = 'integer'
                elif param.annotation == float:
                    param_type = 'number'
                elif param.annotation == bool:
                    param_type = 'boolean'
                elif hasattr(param.annotation, '__origin__'):
                    # Handle List, Optional, etc.
                    if param.annotation.__origin__ == list:
                        param_type = 'array'
                    elif param.annotation.__origin__ == dict:
                        param_type = 'object'

            # Determine if required
            required = param.default == inspect.Parameter.empty

            # Check for custom schema override
            custom_schema = param_schemas.get(param_name, {})

            # Generate better descriptions based on parameter name
            param_description_map = {
                "prompt": "Text description of the image to generate",
                "n": "Number of images to generate",
                "name": "The parameter name to change",
                "value": "The new value for the parameter"
            }
            param_description = custom_schema.get("description", param_description_map.get(param_name, f"Parameter {param_name}"))

            # Get items_schema for array types
            items_schema = custom_schema.get("items_schema")

            parameters.append(ToolParameter(
                name=param_name,
                type=param_type,
                description=param_description,
                required=required,
                default=param.default if param.default != inspect.Parameter.empty else None,
                items_schema=items_schema
            ))

        # Register tool
        tool_obj = Tool(
            name=name,
            description=description,
            parameters=parameters,
            function=func,
            injected_params=injected_params
        )
        _tool_registry[name] = tool_obj

        return func

    return decorator


def get_tool(name: str) -> Optional[Tool]:
    """Get a tool by name."""
    return _tool_registry.get(name)


def get_all_tools() -> Dict[str, Tool]:
    """Get all registered tools."""
    return _tool_registry.copy()


def tools_to_anthropic_format() -> List[Dict[str, Any]]:
    """
    Convert tools to Anthropic's tool format.

    Returns a list of tool definitions compatible with Claude's API.
    """
    tools = []
    for tool_obj in _tool_registry.values():
        # Build parameter schema
        properties = {}
        required = []

        for param in tool_obj.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            # Add items schema for array types
            if param.type == 'array' and param.items_schema:
                prop["items"] = param.items_schema
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        tools.append({
            "name": tool_obj.name,
            "description": tool_obj.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        })

    return tools


def tools_to_openai_format(enabled_tool_names: List[str] = None) -> List[Dict[str, Any]]:
    """
    Convert tools to OpenAI's function calling format.

    Args:
        enabled_tool_names: Optional list of tool names to include. If None, all tools are included.

    Returns a list of function definitions compatible with OpenAI's API.
    """
    functions = []
    for tool_obj in _tool_registry.values():
        # Filter by enabled tools if specified
        if enabled_tool_names is not None and tool_obj.name not in enabled_tool_names:
            continue
        # Build parameter schema
        properties = {}
        required = []

        for param in tool_obj.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            # Add items schema for array types
            if param.type == 'array' and param.items_schema:
                prop["items"] = param.items_schema
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        functions.append({
            "type": "function",
            "function": {
                "name": tool_obj.name,
                "description": tool_obj.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        })

    return functions

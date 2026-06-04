"""
Toolsv3 Provider System

This module implements the provider-based tools architecture where tools
can come from multiple sources (built-in, external JSON-RPC).

Hierarchy: Task -> Tool -> Preset
- Task: capability enum (text-to-image, etc.)
- Tool: specific instance from provider (provider_id:tool_id)
- Preset: user-saved parameter set for a tool
"""

from .base import (
    ProviderStatus,
    ToolDescriptor,
    ExecutionProgress,
    ExecutionResult,
    ToolProvider,
)
from .registry import ProviderRegistry
from .jsonrpc import (
    JsonRpcProvider,
    StdioProviderConfig,
    WebSocketProviderConfig,
    create_provider_from_config,
    create_providers_from_config,
)
from .health import (
    ProviderHealth,
    ProviderHealthMonitor,
    get_health_monitor,
)
from .lightweight import (
    LightweightProvider,
    get_lightweight_provider,
)

__all__ = [
    "ProviderStatus",
    "ToolDescriptor",
    "ExecutionProgress",
    "ExecutionResult",
    "ToolProvider",
    "ProviderRegistry",
    "JsonRpcProvider",
    "StdioProviderConfig",
    "WebSocketProviderConfig",
    "create_provider_from_config",
    "create_providers_from_config",
    "ProviderHealth",
    "ProviderHealthMonitor",
    "get_health_monitor",
    "LightweightProvider",
    "get_lightweight_provider",
]

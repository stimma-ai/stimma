"""
Base classes and interfaces for the tool provider system.

Tool identity is `provider_id:tool_id` where each provider has its own namespace.
Multiple providers can offer similar tools; they're distinct (no system-level load balancing).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union


class ProviderStatus(str, Enum):
    """Connection status of a tool provider."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


@dataclass
class ToolDescriptor:
    """
    Describes a tool offered by a provider.

    This is the primary interface for tool discovery and UI generation.
    The parameter_schema is a JSON Schema that the UI uses to render controls.
    """

    id: str  # Unique within provider: "qwen-image:text-to-image"
    name: str  # Human-readable: "Qwen Image Text-to-Image"

    # JSON Schemas for UI generation and validation
    parameter_schema: Dict[str, Any]  # Single schema for ALL parameters (prompt, images, cfg, steps, etc.)
    output_schema: Dict[str, Any]  # Schema for outputs

    # Task type (optional - None means utility tool)
    # For backward compat, task_type is the primary/first type
    task_type: Optional[str] = None  # Task capability: "text-to-image", etc. None = utility

    # Multiple task types - tool can declare multiple capabilities
    # e.g., ["text-to-image", "image-to-image"] for tools that work both ways
    task_types: List[str] = field(default_factory=list)

    # UI layout sections for parameter grouping
    layout: Optional[List[Dict[str, Any]]] = None

    # Provider-specific metadata (model paths, capabilities, etc.)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Optional subtitle/description for UI
    subtitle: Optional[str] = None
    description: Optional[str] = None

    # Raw registration JSON from provider (preserved for debugging/inspection)
    raw_registration: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Auto-populate task_types from task_type if not explicitly set."""
        if not self.task_types and self.task_type:
            self.task_types = [self.task_type]

    def full_id(self, provider_id: str) -> str:
        """Return the full tool ID including provider: 'provider_id:tool_id'."""
        return f"{provider_id}:{self.id}"


@dataclass
class ExecutionProgress:
    """
    Progress update during tool execution.

    Sent by providers to indicate execution progress.
    """

    progress: float  # 0.0 to 1.0
    stage: str  # Human-readable stage: "sampling", "encoding", "upscaling"
    preview_data: Optional[bytes] = None  # Optional preview image (PNG bytes)
    message: Optional[str] = None  # Optional progress message


@dataclass
class ExecutionResult:
    """
    Final result from tool execution.

    Contains either output data (on success) or error information (on failure).
    """

    success: bool
    output_data: Optional[bytes] = None  # Image/video bytes (PNG/MP4)
    generation_time: float = 0.0  # Seconds
    actual_seed: Optional[int] = None  # The seed that was actually used
    metadata: Dict[str, Any] = field(default_factory=dict)  # Tool-specific output metadata
    error: Optional[str] = None  # Error message if success=False

    # For multiple outputs (e.g., batch generation)
    additional_outputs: List[bytes] = field(default_factory=list)

    # Optional workflow/flow for reproduction (e.g., ComfyUI workflow JSON)
    workflow: Optional[Dict[str, Any]] = None


class ToolProvider(ABC):
    """
    Abstract base class for tool providers.

    A provider is a source of tools that can execute generation tasks.
    Examples:
    - JsonRpcProvider: connects to external tools via JSON-RPC over WebSocket/stdio
    - LightweightProvider: in-process tools for lightweight operations

    Tool identity is scoped to the provider: full_tool_id = "provider_id:tool_id"
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """
        Unique identifier for this provider.

        Examples: "builtin:ComfyUI", "jsonrpc:remote-comfy"
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name for display in UI."""
        pass

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """
        Provider type: 'builtin', 'jsonrpc'.

        Used for routing and feature detection.
        """
        pass

    @property
    @abstractmethod
    def status(self) -> ProviderStatus:
        """Current connection status."""
        pass

    @property
    def max_concurrent(self) -> int:
        """
        Provider-level parallelism limit.

        Total concurrent executions across all tools from this provider.
        Default: 1
        """
        return 1

    # --- Lifecycle ---

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to provider.

        For builtin providers, this initializes the backend.
        For JSON-RPC providers, this connects to the remote service.

        Raises:
            ConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Clean disconnect from provider.

        Should release resources and cancel pending operations.
        """
        pass

    # --- Tool Discovery ---

    @abstractmethod
    async def list_tools(self) -> List[ToolDescriptor]:
        """
        List all tools offered by this provider.

        Returns tools that are currently available for execution.
        """
        pass

    async def get_tool(self, tool_id: str) -> Optional[ToolDescriptor]:
        """
        Get a specific tool descriptor by ID.

        Default implementation searches list_tools().
        Override for more efficient lookup.
        """
        for tool in await self.list_tools():
            if tool.id == tool_id:
                return tool
        return None

    async def refresh_tools(self) -> List[ToolDescriptor]:
        """
        Refresh and return updated tool list.

        Called when the user requests a refresh of tool metadata (e.g., LoRA lists).
        Default implementation just returns list_tools().
        Override for providers that support dynamic refresh (e.g., re-querying
        ComfyUI for available LoRAs, or sending tools.refresh over JSON-RPC).
        """
        return await self.list_tools()

    # --- Execution ---

    @abstractmethod
    async def execute(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[ExecutionProgress], None]] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[Union[ExecutionProgress, ExecutionResult]]:
        """
        Execute a tool, yielding progress updates and final result.

        Args:
            tool_id: The tool ID within this provider (not full_tool_id)
            parameters: All parameters (prompt, images, cfg, steps, seed, etc.)
            output_path: Optional path to save output file directly
            progress_callback: Optional callback for progress updates
            request_id: Optional request ID for tracking/cancellation (used by JSON-RPC providers)

        Yields:
            ExecutionProgress: Progress updates during execution
            ExecutionResult: Final result (always last item yielded)

        Raises:
            ValueError: If tool_id is not found
            RuntimeError: If provider is disconnected
        """
        pass

    # --- Asset Management ---

    @abstractmethod
    async def upload_asset(self, data: bytes, mime_type: str) -> str:
        """
        Upload an asset (image/video) and return a reference ID.

        Assets are scoped per-connection and auto-deleted on disconnect.

        Args:
            data: Binary data (image/video bytes)
            mime_type: MIME type (e.g., "image/png", "video/mp4")

        Returns:
            Asset ID that can be used in parameters
        """
        pass

    @abstractmethod
    async def download_asset(self, asset_id: str) -> bytes:
        """
        Download an asset by reference ID.

        Args:
            asset_id: ID returned from upload_asset or execution result

        Returns:
            Binary data

        Raises:
            KeyError: If asset not found
        """
        pass

    async def delete_asset(self, asset_id: str) -> bool:
        """
        Explicitly delete an asset.

        Optional - assets are auto-deleted on disconnect anyway.
        Default implementation does nothing (assets cleaned up on disconnect).
        """
        return True

    # --- Tool File Upload ---

    async def upload_to_tool(
        self,
        tool_id: str,
        parameter: str,
        filename: str,
        file_data: bytes,
    ) -> Dict[str, Any]:
        """
        Upload a file to a tool's parameter (e.g., LoRA upload).

        The provider handles the full upload lifecycle:
        1. Send tools.upload RPC to initiate
        2. Transfer file bytes via asset endpoint
        3. Send tools.upload_complete to finalize
        4. Refresh tools to update enum lists

        Args:
            tool_id: The tool ID within this provider
            parameter: The parameter name (e.g., "loras")
            filename: Original filename
            file_data: Raw file bytes

        Returns:
            Dict with upload result including installed_path

        Raises:
            NotImplementedError: If provider doesn't support uploads
            RuntimeError: If upload fails
        """
        raise NotImplementedError(f"Provider {self.provider_id} does not support file uploads")

    async def upload_prepare(
        self,
        tool_id: str,
        parameter: str,
        filename: str,
        file_size: int,
    ) -> Dict[str, Any]:
        """
        First half of a split upload: send tools.upload RPC and return the
        target URL the client should PUT to (provider-supplied upload_url for
        cloud, asset endpoint URL for desktop). Does NOT receive file bytes.
        """
        raise NotImplementedError(f"Provider {self.provider_id} does not support file uploads")

    async def upload_finalize(self, upload_id: str) -> Dict[str, Any]:
        """
        Second half of a split upload: send tools.upload_complete RPC after the
        client has PUT the bytes. Returns installed_path + any provider-specific
        ids (e.g. cloud LoRA id).
        """
        raise NotImplementedError(f"Provider {self.provider_id} does not support file uploads")

    # --- Health Check ---

    async def ping(self) -> bool:
        """
        Check if provider is healthy.

        Default implementation returns True if status is CONNECTED.
        Override for active health checking.
        """
        return self.status == ProviderStatus.CONNECTED

    # --- Interrupt Control ---

    async def interrupt(self) -> int:
        """
        Interrupt currently executing generations.

        Signals the provider to stop all in-progress generations as quickly
        as possible. Already-completed work is not affected.

        Returns:
            Number of interrupted operations (provider-specific)

        Default implementation does nothing (returns 0).
        Override for providers that support interruption.
        """
        return 0

    async def interrupt_and_clear(self) -> int:
        """
        Interrupt running generations AND clear any pending queue.

        This provides a complete stop - both running generations and any
        queued work are cancelled immediately.

        Returns:
            Number of affected operations (provider-specific)

        Default implementation just calls interrupt().
        Override for providers that have separate queuing.
        """
        return await self.interrupt()

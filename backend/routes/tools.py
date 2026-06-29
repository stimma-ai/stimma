"""Tools management routes (Toolsv3 - Provider-based).

Provider tools are the source of truth. This file provides:
1. Provider listing and tool discovery
2. Pinned tools management (sidebar)
3. Tool state persistence (working parameters)
"""
import json
from datetime import datetime
from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import PinnedTool, ToolState, MediaItem
from core.dependencies import get_db_session
from core.logging import get_logger
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/tools", tags=["tools"])
log = get_logger(__name__)


# =============================================================================
# Response Models
# =============================================================================

class ProviderStatusResponse(BaseModel):
    """Response for provider status."""
    provider_id: str
    provider_name: str
    provider_type: str
    status: str
    tool_count: int
    max_concurrent: int
    queue_status: Optional[Dict[str, int]] = None


class ProviderToolResponse(BaseModel):
    """Response for a tool from a provider."""
    # `model` / `model_vendor` collide with pydantic's protected `model_` namespace;
    # these are STP wire fields, not pydantic internals, so opt out of the guard.
    model_config = ConfigDict(protected_namespaces=())

    full_tool_id: str  # provider_id:tool_id
    tool_id: str
    name: str
    task_type: Optional[str]  # Primary task type (None = utility tool)
    task_types: List[str] = []  # All task types this tool supports
    provider_id: str
    provider_name: str
    parameter_schema: Dict = {}
    output_schema: Dict = {}
    layout: Optional[List] = None
    metadata: Dict = {}
    subtitle: Optional[str] = None
    model_vendor: Optional[str] = None  # STP model_vendor (brand mark hint)
    model: Optional[str] = None  # STP model identifier
    availability: str = "available"  # "available", "disconnected", "unconfigured"


class PinnedToolResponse(BaseModel):
    """Response for a pinned tool."""
    full_tool_id: str
    pin_order: int
    # Tool info (denormalized from provider)
    name: Optional[str] = None
    task_type: Optional[str] = None  # Primary task type
    task_types: List[str] = []  # All task types
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None


class ToolStateResponse(BaseModel):
    """Response for tool working state."""
    full_tool_id: str
    state: Dict = {}
    updated_at: Optional[str] = None


# =============================================================================
# Request Models
# =============================================================================

class PinToolRequest(BaseModel):
    """Request to pin a provider tool."""
    full_tool_id: str


class ReorderPinsRequest(BaseModel):
    """Request to reorder pinned tools."""
    full_tool_ids: List[str]  # Ordered list of tool IDs


class SaveToolStateRequest(BaseModel):
    """Request to save tool working state."""
    state: Dict


class ExecuteToolRequest(BaseModel):
    """Request to execute a lightweight tool."""
    parameters: Dict = {}
    inputs: Dict = {}  # e.g., {"image": "/path/to/image.png"}
    output_folder: str  # Where to save results


class TestConnectionRequest(BaseModel):
    """Request to test a provider connection."""
    type: str  # "stdio" or "websocket"
    command: Optional[str] = None  # For stdio
    args: Optional[List[str]] = None  # For stdio
    working_dir: Optional[str] = None  # For stdio
    url: Optional[str] = None  # For websocket
    auth_token: Optional[str] = None  # For websocket


class TestConnectionResponse(BaseModel):
    """Response from test connection."""
    success: bool
    provider_name: Optional[str] = None
    provider_version: Optional[str] = None
    tool_count: Optional[int] = None
    error: Optional[str] = None
    error_type: Optional[str] = None


# =============================================================================
# Provider Routes
# =============================================================================

@router.get("/task-types")
async def list_task_types():
    """Canonical task-type contracts (required/optional inputs + required output),
    sourced from ``tasks/schemas.py`` so the UI never hardcodes them. Used by the
    freeze dialog to populate the task-type list and validate flow ↔ task fit."""
    from tasks.schemas import TASK_SCHEMA_REQUIREMENTS

    return [
        {
            "task_type": task_type,
            "required_input": req.get("required_input", []),
            "optional_input": req.get("optional_input", []),
            "required_output": req.get("required_output", []),
        }
        for task_type, req in TASK_SCHEMA_REQUIREMENTS.items()
    ]


@router.get("/providers", response_model=List[ProviderStatusResponse])
async def list_providers():
    """List all registered tool providers and their status."""
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    providers = []

    for provider_id, provider in registry._providers.items():
        tools = await provider.list_tools()

        # Get queue status if available (for JsonRpcProvider)
        queue_status = None
        if hasattr(provider, 'queue_status'):
            queue_status = provider.queue_status

        providers.append(ProviderStatusResponse(
            provider_id=provider_id,
            provider_name=provider.provider_name,
            provider_type=provider.provider_type,
            status=provider.status.value,
            tool_count=len(tools),
            max_concurrent=provider.max_concurrent,
            queue_status=queue_status,
        ))

    return providers


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(request: TestConnectionRequest):
    """
    Test connection to a tool provider without registering it.

    For stdio: spawns process, waits for STP handshake, terminates
    For websocket: connects, waits for STP handshake, disconnects

    Returns success/failure with descriptive error messages.
    """
    from providers.jsonrpc import test_provider_connection

    result = await test_provider_connection(
        provider_type=request.type,
        command=request.command,
        args=request.args,
        working_dir=request.working_dir,
        url=request.url,
        auth_token=request.auth_token,
        timeout=10.0,
    )

    # Telemetry: providerType (connection kind) + validated STP product
    # identity only — never user labels or the free-string reported version.
    from stp_identity import parse_server_identity
    from telemetry import get_telemetry_client
    _tested_props = {"success": result.success, "providerType": request.type}
    _identity = parse_server_identity(getattr(result, "server", None))
    if _identity.get("productName") and _identity["productName"] != "unknown":
        _tested_props["productName"] = _identity["productName"]
        if _identity.get("productVersion"):
            _tested_props["productVersion"] = _identity["productVersion"]
    get_telemetry_client().track("tool_provider_tested", _tested_props, category="generation")

    return TestConnectionResponse(
        success=result.success,
        provider_name=result.provider_name,
        provider_version=result.provider_version,
        tool_count=result.tool_count,
        error=result.error,
        error_type=result.error_type,
    )


@router.get("/providers/tools", response_model=List[ProviderToolResponse])
async def list_provider_tools(
    task_type: Optional[str] = Query(None, description="Filter by task type. Use 'utility' for tools without a task type. Tool matches if ANY of its task_types match."),
    provider_id: Optional[str] = Query(None, description="Filter by provider ID"),
    include_unavailable: bool = Query(True, description="Include tools from disconnected providers"),
    session: AsyncSession = Depends(get_db_session),
):
    """List all tools from all providers.

    Use task_type="utility" to get tools without a declared task_type (utility tools).
    When filtering by task_type, tools match if ANY of their task_types match the filter.
    When include_unavailable=True, also includes cached tools from disconnected providers.
    """
    from providers import ProviderRegistry
    from database import CachedProviderTool

    registry = ProviderRegistry.get_instance()
    connected_provider_ids = registry.get_provider_ids()
    enabled_provider_ids = registry.get_enabled_provider_ids()

    tools = []
    seen_tool_ids = set()  # Track which tools we've added (avoid duplicates)

    # First: Add tools from connected providers (availability: "available")
    # Only include tools from providers that are enabled
    for pid, provider in registry._providers.items():
        if provider_id and pid != provider_id:
            continue

        # Skip if provider is disabled (shouldn't happen normally, but safety check)
        if pid not in enabled_provider_ids:
            continue

        provider_tools = await provider.list_tools()
        for tool in provider_tools:
            full_tool_id = f"{pid}:{tool.id}"
            seen_tool_ids.add(full_tool_id)

            # Get task_types list (fallback to [task_type] for backward compat)
            tool_task_types = tool.task_types if tool.task_types else ([tool.task_type] if tool.task_type else [])

            # Filter by task_type - match if ANY of the tool's task_types match
            if task_type:
                if task_type == "utility":
                    if tool_task_types:  # Has any task types = not utility
                        continue
                elif task_type not in tool_task_types:
                    continue

            tools.append(ProviderToolResponse(
                full_tool_id=full_tool_id,
                tool_id=tool.id,
                name=tool.name,
                task_type=tool.task_type,
                task_types=tool_task_types,
                provider_id=pid,
                provider_name=provider.provider_name,
                parameter_schema=tool.parameter_schema or {},
                output_schema=tool.output_schema or {},
                layout=tool.layout or (tool.metadata or {}).get("layout"),
                metadata=tool.metadata or {},
                subtitle=tool.subtitle,
                model_vendor=tool.model_vendor,
                model=tool.model,
                availability="available",
            ))

    # Second: Add cached tools from disconnected but enabled providers
    if include_unavailable:
        # Query cached tools from providers that are NOT currently connected
        # Connected providers are fully represented in Phase 1 above
        query = select(CachedProviderTool).where(
            CachedProviderTool.deleted_at.is_(None),  # Not soft-deleted
        )
        if connected_provider_ids:
            query = query.where(CachedProviderTool.provider_id.notin_(connected_provider_ids))

        if provider_id:
            query = query.where(CachedProviderTool.provider_id == provider_id)

        result = await session.execute(query)
        cached_tools = result.scalars().all()

        for cached in cached_tools:
            # Skip if already added from connected provider
            if cached.full_tool_id in seen_tool_ids:
                continue

            # Skip if provider is not enabled (disabled or removed from config)
            if cached.provider_id not in enabled_provider_ids:
                continue

            # Parse task_types from cached JSON (fallback to [task_type] for backward compat)
            cached_task_types = json.loads(cached.task_types) if cached.task_types else []
            if not cached_task_types and cached.task_type:
                cached_task_types = [cached.task_type]

            # Filter by task_type - match if ANY of the tool's task_types match
            if task_type:
                if task_type == "utility":
                    if cached_task_types:  # Has any task types = not utility
                        continue
                elif task_type not in cached_task_types:
                    continue

            cached_metadata = json.loads(cached.tool_metadata) if cached.tool_metadata else {}
            tools.append(ProviderToolResponse(
                full_tool_id=cached.full_tool_id,
                tool_id=cached.tool_id,
                name=cached.name,
                task_type=cached.task_type,
                task_types=cached_task_types,
                provider_id=cached.provider_id,
                provider_name=cached.provider_name or cached.provider_id,
                parameter_schema=json.loads(cached.parameter_schema) if cached.parameter_schema else {},
                output_schema=json.loads(cached.output_schema) if cached.output_schema else {},
                layout=cached_metadata.get("layout"),
                metadata=cached_metadata,
                subtitle=None,
                model_vendor=cached.model_vendor,
                model=cached.model,
                availability="disconnected",
            ))

    return tools


@router.get("/providers/{provider_id}", response_model=ProviderStatusResponse)
async def get_provider(provider_id: str):
    """Get status of a specific provider."""
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    provider = registry.get_provider(provider_id)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    tools = await provider.list_tools()

    queue_status = None
    if hasattr(provider, 'queue_status'):
        queue_status = provider.queue_status

    return ProviderStatusResponse(
        provider_id=provider_id,
        provider_name=provider.provider_name,
        provider_type=provider.provider_type,
        status=provider.status.value,
        tool_count=len(tools),
        max_concurrent=provider.max_concurrent,
        queue_status=queue_status,
    )


class ProviderLogsResponse(BaseModel):
    """Response for provider stderr logs."""
    lines: List[str]
    total_lines: int


@router.get("/providers/{provider_id}/logs", response_model=ProviderLogsResponse)
async def get_provider_logs(provider_id: str):
    """Get logs from a provider (stdio or websocket).

    Returns the most recent 500 lines of log output, including:
    - Process lifecycle events (starting, exited, connected)
    - Stderr output from the process
    - Connection errors

    The log buffer persists across provider restarts.
    """
    from providers.jsonrpc_manager import get_jsonrpc_manager

    manager = get_jsonrpc_manager()
    lines, total_lines = manager.get_stderr_logs(provider_id)

    return ProviderLogsResponse(lines=lines, total_lines=total_lines)


@router.get("/provider-tool/{full_tool_id:path}/raw-schema")
async def get_provider_tool_raw_schema(full_tool_id: str):
    """Get the raw registration JSON for a provider tool.

    This returns the original JSON that the provider sent during tool registration,
    useful for debugging and inspecting the full tool definition.

    Only available for tools from connected providers (not cached tools).
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Find in connected providers
    for pid, provider in registry._providers.items():
        if full_tool_id.startswith(f"{pid}:"):
            tool_id = full_tool_id[len(pid) + 1:]
            tool = await provider.get_tool(tool_id)
            if tool:
                if tool.raw_registration:
                    return tool.raw_registration
                else:
                    # Tool exists but no raw registration (e.g., builtin provider)
                    # Return constructed schema
                    result = {
                        "id": tool.id,
                        "name": tool.name,
                        "task_type": tool.task_type,
                        "task_types": tool.task_types,
                        "parameter_schema": tool.parameter_schema,
                        "output_schema": tool.output_schema,
                        "metadata": tool.metadata,
                    }
                    tool_layout = tool.layout or (tool.metadata or {}).get("layout")
                    if tool_layout:
                        result["layout"] = tool_layout
                    return result

    raise HTTPException(status_code=404, detail="Tool not found or provider disconnected")


@router.get("/provider-tool/{full_tool_id:path}", response_model=ProviderToolResponse)
async def get_provider_tool(
    full_tool_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Get a specific provider tool by its full ID.

    Returns the tool with availability status. Falls back to cached data
    if the provider is disconnected.
    """
    from providers import ProviderRegistry
    from database import CachedProviderTool

    registry = ProviderRegistry.get_instance()
    enabled_provider_ids = registry.get_enabled_provider_ids()

    # First: Try to find in connected providers (available)
    for pid, provider in registry._providers.items():
        if full_tool_id.startswith(f"{pid}:"):
            # Check if provider is enabled
            if pid not in enabled_provider_ids:
                break  # Skip to cached tools check
            tool_id = full_tool_id[len(pid) + 1:]
            tool = await provider.get_tool(tool_id)
            if tool:
                # Get task_types list (fallback to [task_type] for backward compat)
                tool_task_types = tool.task_types if tool.task_types else ([tool.task_type] if tool.task_type else [])
                return ProviderToolResponse(
                    full_tool_id=full_tool_id,
                    tool_id=tool_id,
                    name=tool.name,
                    task_type=tool.task_type,
                    task_types=tool_task_types,
                    provider_id=pid,
                    provider_name=provider.provider_name,
                    parameter_schema=tool.parameter_schema or {},
                    output_schema=tool.output_schema or {},
                    layout=tool.layout or (tool.metadata or {}).get("layout"),
                    metadata=tool.metadata or {},
                    subtitle=tool.subtitle,
                    model_vendor=tool.model_vendor,
                    model=tool.model,
                    availability="available",
                )

    # Second: Try to find in cached tools (disconnected or disabled)
    result = await session.execute(
        select(CachedProviderTool).where(
            CachedProviderTool.full_tool_id == full_tool_id,
            CachedProviderTool.deleted_at.is_(None),
        )
    )
    cached = result.scalar_one_or_none()

    if cached:
        # Determine availability based on config
        # If provider is enabled but disconnected -> "disconnected"
        # If provider is disabled or not configured -> "unconfigured"
        availability = "disconnected" if cached.provider_id in enabled_provider_ids else "unconfigured"

        # Parse task_types from cached JSON (fallback to [task_type] for backward compat)
        cached_task_types = json.loads(cached.task_types) if cached.task_types else []
        if not cached_task_types and cached.task_type:
            cached_task_types = [cached.task_type]

        cached_metadata = json.loads(cached.tool_metadata) if cached.tool_metadata else {}
        return ProviderToolResponse(
            full_tool_id=cached.full_tool_id,
            tool_id=cached.tool_id,
            name=cached.name,
            task_type=cached.task_type,
            task_types=cached_task_types,
            provider_id=cached.provider_id,
            provider_name=cached.provider_name or cached.provider_id,
            parameter_schema=json.loads(cached.parameter_schema) if cached.parameter_schema else {},
            output_schema=json.loads(cached.output_schema) if cached.output_schema else {},
            layout=cached_metadata.get("layout"),
            metadata=cached_metadata,
            subtitle=None,
            model_vendor=cached.model_vendor,
            model=cached.model,
            availability=availability,
        )

    raise HTTPException(status_code=404, detail="Provider tool not found")


# =============================================================================
# Refresh Routes
# =============================================================================

@router.post("/refresh")
async def refresh_all_tools():
    """
    Refresh tools from all providers.

    This triggers each provider to re-query its backend (e.g., ComfyUI) for
    updated tool metadata, including LoRA lists. Use this after adding new
    LoRAs to ComfyUI's loras folder.

    Returns:
        Status message
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    await registry.refresh_tools()
    log.info("Refreshed tools from all providers")
    return {"status": "refreshed"}


@router.post("/refresh/{provider_id:path}")
async def refresh_provider_tools(provider_id: str):
    """
    Refresh tools from a specific provider.

    Args:
        provider_id: The provider ID (e.g., "builtin:comfyui")

    Returns:
        Status message
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    provider = registry.get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider not found: {provider_id}")

    await registry.refresh_tools(provider_id)
    log.info(f"Refreshed tools from provider: {provider_id}")
    return {"status": "refreshed", "provider_id": provider_id}


# =============================================================================
# Tool Upload Routes
# =============================================================================

class ToolUploadResponse(BaseModel):
    """Response from uploading a file to a tool."""
    success: bool
    installed_path: Optional[str] = None
    # Cloud providers return an opaque per-user LoRA id (uuid). Desktop/ComfyUI
    # providers leave this null and use installed_path as the pool identifier.
    lora_id: Optional[str] = None
    error: Optional[str] = None


class ToolUploadPrepareRequest(BaseModel):
    parameter: str
    filename: str
    file_size: int


class ToolUploadPrepareResponse(BaseModel):
    upload_id: str
    asset_id: str
    upload_url: str
    upload_method: str
    is_presigned: bool


class ToolUploadFinalizeRequest(BaseModel):
    upload_id: str


@router.post("/upload/{full_tool_id:path}", response_model=ToolUploadResponse)
async def upload_to_tool(
    full_tool_id: str,
    file: UploadFile = File(...),
    parameter: str = Form(...),
):
    """
    Upload a file to a tool's parameter (e.g., LoRA upload).

    The tool must declare x-accept-upload on the parameter's schema.
    Validates file extension and size against the schema constraints.

    Args:
        full_tool_id: Full tool ID (provider_id:tool_id)
        file: The file to upload
        parameter: The parameter name (e.g., "loras")
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Find the tool
    tool_entry = registry.get_tool(full_tool_id)
    if not tool_entry:
        raise HTTPException(status_code=404, detail="Tool not found")

    provider, tool = tool_entry

    # Validate that the parameter supports uploads via x-accept-upload
    param_schema = (tool.parameter_schema or {}).get("properties", {}).get(parameter)
    if not param_schema:
        raise HTTPException(status_code=400, detail=f"Parameter '{parameter}' not found in tool schema")

    # Look for x-accept-upload on the parameter or its nested path property
    upload_config = param_schema.get("x-accept-upload")
    if not upload_config:
        # Check nested: loras.items.properties.path.x-accept-upload
        upload_config = (
            param_schema.get("items", {})
            .get("properties", {})
            .get("path", {})
            .get("x-accept-upload")
        )

    if not upload_config:
        raise HTTPException(
            status_code=400,
            detail=f"Parameter '{parameter}' does not accept file uploads"
        )

    # Validate file extension
    allowed_extensions = upload_config.get("extensions", [])
    if allowed_extensions:
        filename_lower = (file.filename or "").lower()
        if not any(filename_lower.endswith(ext.lower()) for ext in allowed_extensions):
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Accepted: {', '.join(allowed_extensions)}"
            )

    # Read file data
    file_data = await file.read()

    # Validate file size
    max_size = upload_config.get("max_size")
    if max_size and len(file_data) > max_size:
        max_mb = max_size / (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {max_mb:.0f} MB"
        )

    # Delegate to registry
    log.info(
        "tool upload starting",
        tool=full_tool_id,
        parameter=parameter,
        filename=file.filename,
        file_size=len(file_data),
    )
    try:
        result = await registry.upload_to_tool(
            full_tool_id=full_tool_id,
            parameter=parameter,
            filename=file.filename or "upload",
            file_data=file_data,
        )
        log.info(
            "tool upload succeeded",
            tool=full_tool_id,
            installed_path=result.get("installed_path"),
        )
        return ToolUploadResponse(
            success=True,
            installed_path=result.get("installed_path"),
            lora_id=result.get("lora_id"),
        )
    except NotImplementedError:
        log.warning("tool upload not supported", tool=full_tool_id)
        raise HTTPException(
            status_code=400,
            detail="This provider does not support file uploads"
        )
    except Exception as e:
        log.error("tool upload failed", tool=full_tool_id, error=str(e), exc_info=True)
        return ToolUploadResponse(
            success=False,
            error=str(e),
        )


@router.post("/upload-prepare/{full_tool_id:path}", response_model=ToolUploadPrepareResponse)
async def upload_prepare(full_tool_id: str, body: ToolUploadPrepareRequest):
    """
    First half of a split tool upload. Validates the tool/parameter accepts
    uploads (via x-accept-upload), calls the provider's upload_prepare to
    initiate via STP, and returns the URL the frontend should PUT bytes to.

    Used to move large-file transfers (multi-GB cloud LoRAs) off the desktop
    backend's HTTP path — the frontend PUTs directly to the upstream presigned
    URL instead of proxying through this process.
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    tool_entry = registry.get_tool(full_tool_id)
    if not tool_entry:
        raise HTTPException(status_code=404, detail="Tool not found")
    _, tool = tool_entry

    # Validate parameter accepts uploads (same schema gate the legacy
    # /upload route enforces) — checks top-level x-accept-upload, then the
    # nested items.properties.path location for desktop-shape schemas.
    param_schema = (tool.parameter_schema or {}).get("properties", {}).get(body.parameter)
    if not param_schema:
        raise HTTPException(status_code=400, detail=f"Parameter '{body.parameter}' not found in tool schema")
    upload_config = param_schema.get("x-accept-upload") or (
        param_schema.get("items", {})
        .get("properties", {})
        .get("path", {})
        .get("x-accept-upload")
    )
    if not upload_config:
        raise HTTPException(status_code=400, detail=f"Parameter '{body.parameter}' does not accept file uploads")

    # Validate extension + size up front so the frontend doesn't waste time
    # trying to PUT a file the upstream will reject.
    allowed_extensions = upload_config.get("extensions", [])
    if allowed_extensions:
        filename_lower = body.filename.lower()
        if not any(filename_lower.endswith(ext.lower()) for ext in allowed_extensions):
            raise HTTPException(status_code=400, detail=f"File type not allowed. Accepted: {', '.join(allowed_extensions)}")
    max_size = upload_config.get("max_size")
    if max_size and body.file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"File too large. Maximum size: {max_mb:.0f} MB")

    try:
        result = await registry.upload_prepare(
            full_tool_id=full_tool_id,
            parameter=body.parameter,
            filename=body.filename,
            file_size=body.file_size,
        )
        log.info("upload-prepare succeeded", tool=full_tool_id, upload_id=result.get("upload_id"))
        return ToolUploadPrepareResponse(**result)
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="This provider does not support file uploads")
    except Exception as e:
        log.error("upload-prepare failed", tool=full_tool_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-finalize/{full_tool_id:path}", response_model=ToolUploadResponse)
async def upload_finalize(full_tool_id: str, body: ToolUploadFinalizeRequest):
    """
    Second half of a split tool upload. Called after the frontend has PUT the
    bytes to the URL returned by /upload-prepare. The provider verifies the
    upload (e.g. server-side sha256) and installs the file.
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()
    if not registry.get_tool(full_tool_id):
        raise HTTPException(status_code=404, detail="Tool not found")

    try:
        result = await registry.upload_finalize(full_tool_id=full_tool_id, upload_id=body.upload_id)
        log.info(
            "upload-finalize succeeded",
            tool=full_tool_id,
            upload_id=body.upload_id,
            installed_path=result.get("installed_path"),
        )
        return ToolUploadResponse(
            success=True,
            installed_path=result.get("installed_path"),
            lora_id=result.get("lora_id"),
        )
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="This provider does not support file uploads")
    except Exception as e:
        log.error("upload-finalize failed", tool=full_tool_id, error=str(e), exc_info=True)
        return ToolUploadResponse(success=False, error=str(e))


# =============================================================================
# Pinned Tools Routes
# =============================================================================

@router.get("/pinned", response_model=List[PinnedToolResponse])
async def list_pinned_tools(
    session: AsyncSession = Depends(get_db_session)
):
    """List all pinned tools with tool info.

    Uses cached metadata from the database, refreshing from provider if available.
    This ensures tools are displayed even when providers aren't ready after restart.
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Get pinned tools from database
    result = await session.execute(
        select(PinnedTool).order_by(PinnedTool.pin_order.asc())
    )
    pinned = result.scalars().all()

    response = []
    updates_needed = []

    for pin in pinned:
        # Parse cached task_types (fallback to [task_type] for backward compat)
        cached_task_types = json.loads(pin.task_types) if pin.task_types else []
        if not cached_task_types and pin.task_type:
            cached_task_types = [pin.task_type]

        # Start with stored metadata (fallback)
        tool_info = {
            "name": pin.name,
            "task_type": pin.task_type,
            "task_types": cached_task_types,
            "provider_id": pin.provider_id,
            "provider_name": pin.provider_name,
        }

        # Try to refresh from provider if available (updates cache if changed)
        for pid, provider in registry._providers.items():
            if pin.full_tool_id.startswith(f"{pid}:"):
                tool_id = pin.full_tool_id[len(pid) + 1:]
                try:
                    tool = await provider.get_tool(tool_id)
                    if tool:
                        tool_task_types = tool.task_types if tool.task_types else ([tool.task_type] if tool.task_type else [])
                        provider_name = getattr(provider, "provider_name", None) or pid
                        new_info = {
                            "name": tool.name,
                            "task_type": tool.task_type,
                            "task_types": tool_task_types,
                            "provider_id": pid,
                            "provider_name": provider_name,
                        }
                        tool_info = new_info
                        # Update cache if metadata changed
                        if (pin.name != tool.name or
                            pin.task_type != tool.task_type or
                            pin.provider_id != pid or
                            pin.provider_name != provider_name or
                            cached_task_types != tool_task_types):
                            updates_needed.append((pin, new_info))
                except Exception:
                    # Provider not ready or error - use cached data
                    pass
                break

        response.append(PinnedToolResponse(
            full_tool_id=pin.full_tool_id,
            pin_order=pin.pin_order,
            **tool_info,
        ))

    # Update cached metadata in background
    for pin, info in updates_needed:
        pin.name = info["name"]
        pin.task_type = info["task_type"]
        pin.task_types = json.dumps(info["task_types"]) if info["task_types"] else None
        pin.provider_id = info["provider_id"]
        pin.provider_name = info["provider_name"]
    if updates_needed:
        await session.commit()

    return response


@router.post("/pin", response_model=PinnedToolResponse)
async def pin_tool(
    request: PinToolRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Pin a provider tool to the sidebar.

    Saves tool metadata so it's available even after restart when providers aren't ready.
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Verify tool exists and get metadata
    tool_exists = False
    tool_info = {"name": None, "task_type": None, "task_types": [], "provider_id": None, "provider_name": None}
    for pid, provider in registry._providers.items():
        if request.full_tool_id.startswith(f"{pid}:"):
            tool_id = request.full_tool_id[len(pid) + 1:]
            tool = await provider.get_tool(tool_id)
            if tool:
                tool_exists = True
                tool_task_types = tool.task_types if tool.task_types else ([tool.task_type] if tool.task_type else [])
                tool_info = {
                    "name": tool.name,
                    "task_type": tool.task_type,
                    "task_types": tool_task_types,
                    "provider_id": pid,
                    "provider_name": getattr(provider, "provider_name", None) or pid,
                }
            break

    if not tool_exists:
        raise HTTPException(status_code=404, detail="Provider tool not found")

    # Check if already pinned
    existing = await session.execute(
        select(PinnedTool).where(PinnedTool.full_tool_id == request.full_tool_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tool is already pinned")

    # Get next pin order
    max_order_result = await session.execute(select(func.max(PinnedTool.pin_order)))
    max_order = max_order_result.scalar_one_or_none() or 0

    # Create pin with metadata
    pin = PinnedTool(
        full_tool_id=request.full_tool_id,
        pin_order=max_order + 1,
        created_at=datetime.utcnow(),
        name=tool_info["name"],
        task_type=tool_info["task_type"],
        task_types=json.dumps(tool_info["task_types"]) if tool_info["task_types"] else None,
        provider_id=tool_info["provider_id"],
        provider_name=tool_info["provider_name"],
    )
    session.add(pin)
    await session.commit()

    # Broadcast
    await ws_manager.broadcast("tool_pinned", {"full_tool_id": request.full_tool_id})

    return PinnedToolResponse(
        full_tool_id=pin.full_tool_id,
        pin_order=pin.pin_order,
        **tool_info,
    )


@router.delete("/pin/{full_tool_id:path}")
async def unpin_tool(
    full_tool_id: str,
    session: AsyncSession = Depends(get_db_session)
):
    """Unpin a provider tool from the sidebar."""
    result = await session.execute(
        select(PinnedTool).where(PinnedTool.full_tool_id == full_tool_id)
    )
    pin = result.scalar_one_or_none()

    if not pin:
        raise HTTPException(status_code=404, detail="Tool is not pinned")

    await session.delete(pin)
    await session.commit()

    # Broadcast
    await ws_manager.broadcast("tool_unpinned", {"full_tool_id": full_tool_id})

    return {"success": True}


@router.post("/reorder-pins")
async def reorder_pinned_tools(
    request: ReorderPinsRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Reorder pinned tools."""
    for index, full_tool_id in enumerate(request.full_tool_ids):
        result = await session.execute(
            select(PinnedTool).where(PinnedTool.full_tool_id == full_tool_id)
        )
        pin = result.scalar_one_or_none()
        if pin:
            pin.pin_order = index

    await session.commit()

    return {"success": True}


# =============================================================================
# Tool State Routes
# =============================================================================

@router.get("/state/{full_tool_id:path}", response_model=ToolStateResponse)
async def get_tool_state(
    full_tool_id: str,
    session: AsyncSession = Depends(get_db_session)
):
    """Get the working state for a tool."""
    result = await session.execute(
        select(ToolState).where(ToolState.full_tool_id == full_tool_id)
    )
    state = result.scalar_one_or_none()

    if not state:
        return ToolStateResponse(full_tool_id=full_tool_id, state={}, updated_at=None)

    return ToolStateResponse(
        full_tool_id=state.full_tool_id,
        state=json.loads(state.state) if state.state else {},
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
    )


@router.put("/state/{full_tool_id:path}", response_model=ToolStateResponse)
async def save_tool_state(
    full_tool_id: str,
    request: SaveToolStateRequest,
    session: AsyncSession = Depends(get_db_session)
):
    """Save the working state for a tool."""
    result = await session.execute(
        select(ToolState).where(ToolState.full_tool_id == full_tool_id)
    )
    state = result.scalar_one_or_none()

    if state:
        state.state = json.dumps(request.state)
        state.updated_at = datetime.utcnow()
    else:
        state = ToolState(
            full_tool_id=full_tool_id,
            state=json.dumps(request.state),
            updated_at=datetime.utcnow(),
        )
        session.add(state)

    await session.commit()
    await session.refresh(state)

    return ToolStateResponse(
        full_tool_id=state.full_tool_id,
        state=json.loads(state.state) if state.state else {},
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
    )


# =============================================================================
# Tool Execution Routes
# =============================================================================

class ExecuteToolResponse(BaseModel):
    """Response from executing a lightweight tool."""
    success: bool
    outputs: Dict = {}
    metadata: Dict = {}
    error: Optional[str] = None


@router.post("/execute/{full_tool_id:path}", response_model=ExecuteToolResponse)
async def execute_tool(
    full_tool_id: str,
    request: ExecuteToolRequest,
):
    """
    Execute a lightweight tool directly.

    This is for tools that don't go through the generation queue -
    they execute immediately and return results.
    """
    import shutil
    from pathlib import Path
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Find the provider and tool
    provider = None
    tool_id = None
    for pid, p in registry._providers.items():
        if full_tool_id.startswith(f"{pid}:"):
            tool_id = full_tool_id[len(pid) + 1:]
            tool = await p.get_tool(tool_id)
            if tool:
                provider = p
                break

    if not provider or not tool_id:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Verify this is a lightweight tool
    if provider.provider_type != "builtin" or not hasattr(provider, '_tools'):
        raise HTTPException(
            status_code=400,
            detail="This endpoint is only for lightweight tools. Use the generation queue for other tools."
        )

    try:
        # Execute the tool
        result = None
        async for progress_or_result in provider.execute(
            tool_id=tool_id,
            parameters=request.parameters,
            inputs=request.inputs,
        ):
            # Keep the last result (progress updates are intermediate)
            from providers import ExecutionResult
            if isinstance(progress_or_result, ExecutionResult):
                result = progress_or_result

        if not result:
            raise HTTPException(status_code=500, detail="Tool did not return a result")

        if not result.success:
            return ExecuteToolResponse(
                success=False,
                error=result.error,
            )

        # Move output files to the requested output folder
        output_folder = Path(request.output_folder)
        output_folder.mkdir(parents=True, exist_ok=True)

        final_outputs = {}
        for key, value in (result.outputs or {}).items():
            if isinstance(value, str) and Path(value).exists():
                # It's a file path - copy to output folder
                src_path = Path(value)
                dst_path = output_folder / src_path.name
                shutil.copy2(src_path, dst_path)
                final_outputs[key] = str(dst_path)
            else:
                final_outputs[key] = value

        return ExecuteToolResponse(
            success=True,
            outputs=final_outputs,
            metadata=result.metadata or {},
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Tool execution failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Tool Stats Routes
# =============================================================================

class ToolStatsResponse(BaseModel):
    """Response for tool usage statistics."""
    tool_id: str
    media_count: int
    last_generated_at: Optional[str] = None


class GenerateMoreToolResponse(BaseModel):
    """Response for a text-to-image tool in generate-more context."""
    full_tool_id: str
    name: str
    task_type: str
    provider_id: str
    provider_name: str
    metadata: Dict = {}
    subtitle: Optional[str] = None
    is_original: bool = False  # True if this is the tool that created the original image


@router.get("/stats/{full_tool_id:path}", response_model=ToolStatsResponse)
async def get_tool_stats(
    full_tool_id: str,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get usage statistics for a tool.

    Returns:
        - media_count: Number of media items created by this tool
        - last_generated_at: Timestamp of most recent generation
    """
    # Count media items created by this tool
    count_result = await session.execute(
        select(func.count(MediaItem.id))
        .where(MediaItem.tool_id == full_tool_id)
        .where(MediaItem.deleted_at.is_(None))
    )
    media_count = count_result.scalar() or 0

    # Get most recent generation
    last_result = await session.execute(
        select(MediaItem.indexed_date)
        .where(MediaItem.tool_id == full_tool_id)
        .where(MediaItem.deleted_at.is_(None))
        .order_by(MediaItem.indexed_date.desc())
        .limit(1)
    )
    last_row = last_result.first()
    last_generated_at = last_row[0].isoformat() if last_row and last_row[0] else None

    return ToolStatsResponse(
        tool_id=full_tool_id,
        media_count=media_count,
        last_generated_at=last_generated_at,
    )


# =============================================================================
# Generate More Like This Routes
# =============================================================================

@router.get("/generate-more-tools/{media_id}", response_model=List[GenerateMoreToolResponse])
@router.get("/inspire-tools/{media_id}", response_model=List[GenerateMoreToolResponse])
@router.get("/remix-tools/{media_id}", response_model=List[GenerateMoreToolResponse])
async def get_generate_more_tools(
    media_id: int,
    session: AsyncSession = Depends(get_db_session)
):
    """
    Get tools for "Remix" feature.

    Detects the source media's task type from generation_metadata and returns
    tools matching that task type. Falls back to text-to-image if the source
    task type is unknown.

    Returns tools with the original tool (if found in lineage) first,
    marked with is_original=True, followed by others alphabetically.
    """
    from providers import ProviderRegistry

    registry = ProviderRegistry.get_instance()

    # Get the media item
    result = await session.execute(
        select(MediaItem).filter(MediaItem.id == media_id)
    )
    media_item = result.scalar_one_or_none()
    if not media_item:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Find the original tool and detect source task type from lineage
    original_tool_id = None
    source_task_type = None

    if media_item.generation_metadata:
        try:
            gen_meta = json.loads(media_item.generation_metadata)

            tool_id = gen_meta.get("tool_id")
            task_type = gen_meta.get("task_type")
            source_task_type = task_type

            # Check if this media item's tool still exists
            if tool_id and registry.get_tool(tool_id):
                original_tool_id = tool_id

            # If not found or tool doesn't exist, search lineage_trace
            if not original_tool_id:
                lineage_trace = gen_meta.get("lineage_trace", [])
                for entry in reversed(lineage_trace):
                    entry_task_type = entry.get("task_type")
                    # Look for a tool matching the source task type (or t2i as fallback)
                    target_types = {source_task_type, "text-to-image"} if source_task_type else {"text-to-image"}
                    if entry_task_type in target_types:
                        entry_media_id = entry.get("media_id")
                        if entry_media_id:
                            ancestor_result = await session.execute(
                                select(MediaItem.generation_metadata)
                                .filter(MediaItem.id == entry_media_id)
                            )
                            ancestor_row = ancestor_result.first()
                            if ancestor_row and ancestor_row[0]:
                                try:
                                    ancestor_meta = json.loads(ancestor_row[0])
                                    ancestor_tool_id = ancestor_meta.get("tool_id")
                                    if ancestor_tool_id and registry.get_tool(ancestor_tool_id):
                                        original_tool_id = ancestor_tool_id
                                        if not source_task_type:
                                            source_task_type = entry_task_type
                                        break
                                except json.JSONDecodeError:
                                    pass
        except json.JSONDecodeError:
            log.error(f"Failed to parse generation_metadata for media {media_id}")

    # Fall back to text-to-image if we couldn't detect source task type
    if not source_task_type:
        source_task_type = "text-to-image"

    # Get tools matching the source task type (check task_types list for multi-task tools)
    all_tools = []
    for pid, provider in registry._providers.items():
        provider_tools = await provider.list_tools()
        for tool in provider_tools:
            tool_types = getattr(tool, 'task_types', []) or ([tool.task_type] if tool.task_type else [])
            if source_task_type in tool_types:
                all_tools.append(GenerateMoreToolResponse(
                    full_tool_id=f"{pid}:{tool.id}",
                    name=tool.name,
                    task_type=tool.task_type,
                    provider_id=pid,
                    provider_name=provider.provider_name,
                    metadata=tool.metadata or {},
                    subtitle=tool.subtitle,
                    is_original=f"{pid}:{tool.id}" == original_tool_id,
                ))

    # If no tools found for source task type, fall back to text-to-image
    if not all_tools and source_task_type != "text-to-image":
        for pid, provider in registry._providers.items():
            provider_tools = await provider.list_tools()
            for tool in provider_tools:
                fallback_types = getattr(tool, 'task_types', []) or ([tool.task_type] if tool.task_type else [])
                if "text-to-image" in fallback_types:
                    all_tools.append(GenerateMoreToolResponse(
                        full_tool_id=f"{pid}:{tool.id}",
                        name=tool.name,
                        task_type=tool.task_type,
                        provider_id=pid,
                        provider_name=provider.provider_name,
                        metadata=tool.metadata or {},
                        subtitle=tool.subtitle,
                        is_original=f"{pid}:{tool.id}" == original_tool_id,
                    ))

    # Sort: original tool first (if found), then alphabetically by name
    def sort_key(tool: GenerateMoreToolResponse):
        if tool.is_original:
            return (0, "")
        return (1, tool.name.lower())

    all_tools.sort(key=sort_key)

    return all_tools

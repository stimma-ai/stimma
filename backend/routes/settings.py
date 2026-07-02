"""
Settings API routes for managing application configuration.

Provides endpoints for:
- Reading all settings for the UI
- Updating profile-scoped settings (folders, markers)
- Updating global settings (tool providers, background work)
- Profile CRUD operations
"""
import os
import re
import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import app_dirs
from app_context import get_bundle_id, get_sandbox
from config import get_settings, generate_profile_id, FolderConfig, LLMRoleConfig, LLMEndpointConfig, WildcardEntry, PromptSegmentEntry
from database_registry import get_database_registry
from database import MediaItem
from sqlalchemy import select, func
from ingestion import sync_auto_markers_for_items
from utils.websocket import ws_manager
from config_writer import (
    patch_profile_section,
    patch_global_section,
    update_tool_provider,
    create_profile,
    delete_profile as delete_profile_config,
    rename_profile,
    validate_folder_path,
    validate_marker,
    validate_markers,
    validate_folders,
    validate_parallelism,
    validate_captioning_parallelism,
    validate_confidence,
    validate_max_faces,
    ValidationError,
)

# Builtin providers that should always be shown in settings, even if not configured.
# These have required props (like api_key) so they appear disabled until configured.
ALWAYS_SHOW_BUILTIN_PROVIDERS = []

# Provider ID for Stimma Cloud - used for special handling in settings
STIMMA_CLOUD_PROVIDER_ID = "stimma-cloud"
from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# =============================================================================
# Response/Request Models
# =============================================================================


class FolderResponse(BaseModel):
    """Folder configuration response."""
    path: str
    readonly: bool = False
    allow_generate: bool = False
    is_uploads_folder: bool = False
    uploads_subfolder: str = "uploads"
    refresh_interval_seconds: Optional[int] = 300
    markers: List[str] = []
    media_count: int = 0


class MarkerResponse(BaseModel):
    """Marker configuration response."""
    id: Optional[str] = None  # Stable config ID for safe renaming
    name: str
    icon_svg: str
    color: str


class WildcardResponse(BaseModel):
    """Wildcard configuration response."""
    name: str
    values: List[str] = []


class PromptSegmentResponse(BaseModel):
    """Prompt segment configuration response."""
    name: str
    content: str = ""


class FaceDetectionResponse(BaseModel):
    """Face detection settings response."""
    enabled: bool
    min_confidence: float
    max_faces: int
    parallelism: int
    similarity_threshold: float = 0.55


class ClipResponse(BaseModel):
    """CLIP settings response."""
    enabled: bool


class CaptioningResponse(BaseModel):
    """Captioning settings response."""
    enabled: bool
    parallelism: int


class BackgroundWorkResponse(BaseModel):
    """Background work settings response."""
    face_detection: FaceDetectionResponse
    clip: ClipResponse
    captioning: CaptioningResponse


class ToolProviderResponse(BaseModel):
    """Tool provider response (for settings UI)."""
    id: str
    name: str
    type: str  # "builtin", "stdio", "websocket"
    enabled: bool = True
    has_api_key: bool = False
    status: str = "unknown"  # Will be populated from provider registry
    error_message: Optional[str] = None  # Connection error message if any
    tool_count: int = 0  # Number of tools from this provider
    max_concurrent: int = 1  # Max concurrent jobs (from provider registration)
    queue_status: Optional[Dict[str, int]] = None  # Current queue status (dev mode)
    # For stdio providers
    command: Optional[str] = None
    args: Optional[List[str]] = None
    working_dir: Optional[str] = None
    # For websocket providers
    url: Optional[str] = None


class ProfileResponse(BaseModel):
    """Profile summary for settings."""
    id: str
    name: str
    media_count: int
    has_pin: bool = False
    pin_idle_timeout_minutes: int = 30


# =============================================================================
# LLM Settings Models
# =============================================================================


class LLMEndpointResponse(BaseModel):
    """OpenAI-compatible endpoint configuration response."""
    url: str
    model: str
    api_key_set: bool = False
    max_context_tokens: int = 128_000
    # Local-endpoint extras
    content_policy_enabled: bool = True
    extra_system_prompt: str = ""
    extra_body: Optional[Dict[str, Any]] = None
    reasoning_method: Optional[str] = None
    reasoning_method_source: str = "auto"
    detected_runtime: Optional[str] = None
    reasoning_mode: Optional[str] = None
    reasoning_output: Optional[str] = None
    last_tested_at: Optional[str] = None
    last_test_passed: Optional[bool] = None


class LLMRoleResponse(BaseModel):
    """Per-role LLM configuration response."""
    role: str  # 'agent', 'agent-fast'
    source: str  # 'stimma_cloud' or 'endpoint'
    endpoint: Optional[LLMEndpointResponse] = None


class LLMUpdateRequest(BaseModel):
    """Request to update LLM configuration for a role.

    Only include the fields you want to update.
    """
    source: Optional[str] = None  # 'stimma_cloud' or 'endpoint'
    # Endpoint config fields:
    endpoint_url: Optional[str] = None
    endpoint_model: Optional[str] = None
    endpoint_api_key: Optional[str] = None
    endpoint_max_context_tokens: Optional[int] = None
    # Local-endpoint extras:
    endpoint_content_policy_enabled: Optional[bool] = None
    endpoint_extra_system_prompt: Optional[str] = None
    endpoint_extra_body: Optional[Dict[str, Any]] = None
    endpoint_reasoning_method: Optional[str] = None
    endpoint_reasoning_method_source: Optional[str] = None


class LLMScenarioResult(BaseModel):
    """Result of a single LLM test scenario."""
    passed: bool
    elapsed_ms: int = 0
    detail: Optional[str] = None  # Short description of what happened
    error: Optional[str] = None  # Error message if failed


class LLMDetected(BaseModel):
    """What the connection profiler learned about the endpoint/model."""
    runtime: Optional[str] = None          # e.g. 'vLLM 0.22'
    reasoning_method: Optional[str] = None  # how thinking is toggled
    reasoning_mode: Optional[str] = None    # 'always' | 'toggleable' | 'none'
    reasoning_output: Optional[str] = None  # 'field' | 'tags'


class LLMTestResponse(BaseModel):
    """Response from LLM test endpoint."""
    success: bool
    response: Optional[str] = None  # The LLM response text (truncated)
    error: Optional[str] = None  # Error message if failed
    elapsed_ms: Optional[int] = None  # Response time in milliseconds
    scenarios: Optional[dict[str, LLMScenarioResult]] = None
    detected: Optional[LLMDetected] = None


class LLMEndpointModelsRequest(BaseModel):
    """Request to list the models advertised by an OpenAI-compatible endpoint."""
    url: str
    # Plaintext key from the form. If omitted or the masked placeholder, the
    # saved agent endpoint key is used instead.
    api_key: Optional[str] = None


class LLMEndpointModelsResponse(BaseModel):
    """Models advertised by an endpoint's /models route."""
    models: List[str] = []
    error: Optional[str] = None


def _endpoint_response(ep: dict) -> LLMEndpointResponse:
    """Build an LLMEndpointResponse from a stored endpoint dict (or model_dump)."""
    return LLMEndpointResponse(
        url=ep.get("url", ""),
        model=ep.get("model", ""),
        api_key_set=bool(ep.get("api_key")),
        max_context_tokens=int(ep.get("max_context_tokens") or 128_000),
        content_policy_enabled=ep.get("content_policy_enabled", True),
        extra_system_prompt=ep.get("extra_system_prompt") or "",
        extra_body=ep.get("extra_body"),
        reasoning_method=ep.get("reasoning_method"),
        reasoning_method_source=ep.get("reasoning_method_source") or "auto",
        detected_runtime=ep.get("detected_runtime"),
        reasoning_mode=ep.get("reasoning_mode"),
        reasoning_output=ep.get("reasoning_output"),
        last_tested_at=ep.get("last_tested_at"),
        last_test_passed=ep.get("last_test_passed"),
    )


class SettingsResponse(BaseModel):
    """Complete settings response for the UI."""
    profiles: List[ProfileResponse]
    current_profile: str
    folders: List[FolderResponse]
    markers: List[MarkerResponse]
    wildcards: List[WildcardResponse]
    prompt_segments: List[PromptSegmentResponse]
    background_work: BackgroundWorkResponse
    tool_providers: List[ToolProviderResponse]
    llm_settings: List[LLMRoleResponse]  # LLM configurations by role
    bundle_id: str  # e.g., "ai.stimma.stimma" for prod, "ai.stimma.stimma.debug" for dev
    sandbox: str  # e.g., "default" or a named dev/test sandbox
    cloud_base_url: str  # Base URL for stimma.ai cloud services
    developer_mode: bool  # Show debug tools and developer options in the UI
    theme: str  # UI theme preference: light, dark, system
    # Usage telemetry consent: True/False, or None while
    # undetermined (onboarding not completed). Official builds only —
    # dev builds have no telemetry regardless of this value.
    telemetry_enabled: Optional[bool] = None
    distribution: str = "dev"  # Build distribution: 'dev' | 'official'
    privacy_lockdown_active: bool = False
    default_model: str = 'agent-max'  # Global default model slug


class FolderUpdate(BaseModel):
    """Folder update request."""
    path: str
    readonly: bool = False
    allow_generate: bool = False
    is_uploads_folder: bool = False
    uploads_subfolder: str = "uploads"
    refresh_interval_seconds: Optional[int] = 300
    markers: List[str] = []


class MarkerUpdate(BaseModel):
    """Marker update request."""
    id: Optional[str] = None  # Stable config ID (auto-generated if missing)
    name: str
    icon_svg: str
    color: str


class UpdateFoldersRequest(BaseModel):
    """Request to update profile folders."""
    folders: List[FolderUpdate]


class UpdateMarkersRequest(BaseModel):
    """Request to update profile markers."""
    markers: List[MarkerUpdate]


class WildcardUpdate(BaseModel):
    """Wildcard update request."""
    name: str
    values: List[str] = []


class UpdateWildcardsRequest(BaseModel):
    """Request to update profile wildcards."""
    wildcards: List[WildcardUpdate]


class PromptSegmentUpdate(BaseModel):
    """Prompt segment update request."""
    name: str
    content: str = ""


class UpdatePromptSegmentsRequest(BaseModel):
    """Request to update profile prompt segments."""
    prompt_segments: List[PromptSegmentUpdate]


class UpdateToolProviderRequest(BaseModel):
    """Request to update a tool provider."""
    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    # Fields for editing provider config
    name: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    working_dir: Optional[str] = None
    url: Optional[str] = None


class CreateToolProviderRequest(BaseModel):
    """Request to create a new tool provider."""
    id: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-z0-9-]+$')
    name: Optional[str] = None
    type: str = Field(..., pattern=r'^(stdio|websocket)$')
    # For stdio providers
    command: Optional[str] = None
    args: List[str] = []
    working_dir: Optional[str] = None
    # For websocket providers
    url: Optional[str] = None


class UpdateBackgroundWorkRequest(BaseModel):
    """Request to update background work settings."""
    face_detection: Optional[Dict[str, Any]] = None
    clip: Optional[Dict[str, Any]] = None
    captioning: Optional[Dict[str, Any]] = None


class CreateProfileRequest(BaseModel):
    """Request to create a new profile."""
    name: str = Field(..., min_length=1, max_length=100)


class RenameProfileRequest(BaseModel):
    """Request to rename a profile."""
    name: str = Field(..., min_length=1, max_length=100)


class DatabaseCleanupPreviewResponse(BaseModel):
    """Preview of what database cleanup will forget."""
    orphaned_count: int  # Files from folders NOT in current config
    missing_count: int   # Files marked unavailable from configured folders
    total_count: int


class DatabaseCleanupRequest(BaseModel):
    """Request to execute database cleanup."""
    confirm: bool = True  # Safety flag


class DatabaseCleanupResponse(BaseModel):
    """Result of database cleanup execution."""
    orphaned_forgotten: int
    missing_forgotten: int
    total_forgotten: int


class HeroiconResponse(BaseModel):
    """Heroicon entry for the picker."""
    name: str
    ref: str  # e.g., "heroicons:heart"


# =============================================================================
# Common Heroicons for Picker
# =============================================================================

# List of ~30 common heroicons for the marker icon picker
COMMON_HEROICONS = [
    "heart", "star", "bookmark", "flag", "check-circle",
    "x-circle", "bell", "chat-bubble-left", "envelope", "eye",
    "fire", "gift", "globe-alt", "hand-thumb-up", "bolt",
    "lock-closed", "photo", "plus", "minus", "trash",
    "pencil", "document", "folder", "archive-box", "tag",
    "clock", "calendar", "camera", "musical-note", "sparkles",
    "shield-check", "trophy", "light-bulb", "beaker", "cube",
]


# =============================================================================
# Read Endpoints
# =============================================================================


@router.get("", response_model=SettingsResponse)
async def get_settings_all():
    """Get all settings for the UI.

    Returns profile-scoped settings for the current profile and global settings.
    """
    from providers import ProviderRegistry
    from distribution import get_distribution, is_privacy_lockdown

    settings = get_settings()
    current_profile_id = get_current_profile()

    # Get profile list with media counts
    registry = get_database_registry()
    profiles = []
    for p in settings.profiles:
        # Get media count from the profile's database
        media_count = 0
        try:
            db = registry.get_database(p.id)
            async with db.async_session_maker() as session:
                result = await session.execute(
                    select(func.count(MediaItem.id)).where(MediaItem.deleted_at.is_(None))
                )
                media_count = result.scalar() or 0
        except Exception:
            pass  # Profile database may not be initialized yet

        profiles.append(ProfileResponse(
            id=p.id,
            name=p.name,
            media_count=media_count,
            has_pin=p.pin_hash is not None,
            pin_idle_timeout_minutes=p.pin_idle_timeout_minutes,
        ))

    # Get folders and markers for current profile
    # Also count media items per folder
    folder_configs = settings.get_folders_for_profile(current_profile_id)
    folders = []

    # Get database for current profile to count media
    try:
        db = registry.get_database(current_profile_id)
        async with db.async_session_maker() as session:
            for f in folder_configs:
                # Count media items where file_path starts with this folder
                # Ensure we match the folder prefix properly (add trailing slash if needed)
                folder_prefix = f.path if f.path.endswith('/') else f.path + '/'
                result = await session.execute(
                    select(func.count(MediaItem.id)).where(
                        MediaItem.deleted_at.is_(None),
                        MediaItem.file_path.like(f"{folder_prefix}%")
                    )
                )
                media_count = result.scalar() or 0

                folders.append(FolderResponse(
                    path=f.path,
                    readonly=f.readonly,
                    allow_generate=f.allow_generate,
                    is_uploads_folder=f.is_uploads_folder,
                    uploads_subfolder=f.uploads_subfolder,
                    refresh_interval_seconds=f.refresh_interval_seconds,
                    markers=f.markers,
                    media_count=media_count,
                ))
    except Exception:
        # Fallback if database not available
        folders = [
            FolderResponse(
                path=f.path,
                readonly=f.readonly,
                allow_generate=f.allow_generate,
                is_uploads_folder=f.is_uploads_folder,
                uploads_subfolder=f.uploads_subfolder,
                refresh_interval_seconds=f.refresh_interval_seconds,
                markers=f.markers,
                media_count=0,
            )
            for f in folder_configs
        ]

    markers = [
        MarkerResponse(
            id=m.id,
            name=m.name,
            icon_svg=m.icon_svg,
            color=m.color,
        )
        for m in settings.get_markers_for_profile(current_profile_id)
    ]

    wildcards = [
        WildcardResponse(name=w.name, values=w.values)
        for w in settings.get_wildcards_for_profile(current_profile_id)
    ]

    prompt_segments = [
        PromptSegmentResponse(name=s.name, content=s.content)
        for s in settings.get_prompt_segments_for_profile(current_profile_id)
    ]

    # Background work settings
    background_work = BackgroundWorkResponse(
        face_detection=FaceDetectionResponse(
            enabled=settings.face_detection.enabled,
            min_confidence=settings.face_detection.min_confidence,
            max_faces=settings.face_detection.max_faces,
            parallelism=settings.face_detection.parallelism,
            similarity_threshold=settings.face_detection.similarity_threshold,
        ),
        clip=ClipResponse(
            enabled=settings.clip.enabled,
        ),
        captioning=CaptioningResponse(
            enabled=settings.captioning.enabled,
            parallelism=settings.captioning.parallelism,
        ),
    )

    # Tool providers (all types)
    registry = ProviderRegistry.get_instance()
    tool_providers = []

    # Get manager for error messages (persists even when provider not registered)
    from providers.jsonrpc_manager import get_jsonrpc_manager
    manager = get_jsonrpc_manager()

    for provider_config in settings.tool_providers:
        # Get status from provider registry
        provider = registry.get_provider(provider_config.id)
        status = provider.status.value if provider else "disconnected"
        # Get error message from manager (persists even when provider fails to connect)
        error_message = manager.get_error_message(provider_config.id)
        # Get tool count if provider is connected
        tool_count = 0
        if provider:
            try:
                tools = await provider.list_tools()
                tool_count = len(tools)
            except Exception:
                pass  # Provider may be disconnected or errored

        # Get max_concurrent and queue_status if provider is connected
        max_concurrent = provider.max_concurrent if provider else 1
        queue_status = provider.queue_status if provider and hasattr(provider, 'queue_status') else None

        tool_providers.append(ToolProviderResponse(
            id=provider_config.id,
            name=provider_config.name or provider_config.id,
            type=provider_config.type,
            enabled=provider_config.enabled,
            has_api_key=bool(provider_config.api_key),
            status=status,
            error_message=error_message,
            tool_count=tool_count,
            max_concurrent=max_concurrent,
            queue_status=queue_status,
            command=provider_config.command if provider_config.type == "stdio" else None,
            args=provider_config.args if provider_config.type == "stdio" and provider_config.args else None,
            working_dir=provider_config.working_dir if provider_config.type == "stdio" else None,
            url=provider_config.url if provider_config.type == "websocket" else None,
        ))

    # Add unconfigured builtin providers that should always be shown
    # They default to enabled=True; connection error state shows if API key is missing
    configured_ids = {p.id for p in tool_providers}
    for builtin in ALWAYS_SHOW_BUILTIN_PROVIDERS:
        if builtin["id"] not in configured_ids:
            # Check if provider is registered (connected via env var)
            provider = registry.get_provider(builtin["id"])
            status = provider.status.value if provider else "disconnected"
            error_message = manager.get_error_message(builtin["id"])
            tool_count = 0
            if provider:
                try:
                    tools = await provider.list_tools()
                    tool_count = len(tools)
                except Exception:
                    pass
            max_concurrent = provider.max_concurrent if provider else 1
            queue_status = provider.queue_status if provider and hasattr(provider, 'queue_status') else None
            tool_providers.append(ToolProviderResponse(
                id=builtin["id"],
                name=builtin["name"],
                type=builtin["type"],
                enabled=True,
                has_api_key=provider is not None,  # True if connected (has working key)
                status=status,
                error_message=error_message,
                tool_count=tool_count,
                max_concurrent=max_concurrent,
                queue_status=queue_status,
            ))

    # Add Stimma Cloud provider if registered (dynamically connected on login)
    # or if user is authenticated (so they can enable/disable it)
    if STIMMA_CLOUD_PROVIDER_ID not in configured_ids:
        provider = registry.get_provider(STIMMA_CLOUD_PROVIDER_ID)
        if provider:
            # Provider is connected
            status = provider.status.value
            error_message = manager.get_error_message(STIMMA_CLOUD_PROVIDER_ID)
            tool_count = 0
            try:
                tools = await provider.list_tools()
                tool_count = len(tools)
            except Exception:
                pass
            max_concurrent = provider.max_concurrent if provider else 1
            queue_status = provider.queue_status if provider and hasattr(provider, 'queue_status') else None
            tool_providers.append(ToolProviderResponse(
                id=STIMMA_CLOUD_PROVIDER_ID,
                name=provider.provider_name,
                type="websocket",
                enabled=True,
                status=status,
                error_message=error_message,
                tool_count=tool_count,
                max_concurrent=max_concurrent,
                queue_status=queue_status,
            ))

    # Build LLM settings response
    llm_settings = []
    for role, role_config in settings.llms.items():
        endpoint_response = None
        if role_config.endpoint:
            endpoint_response = _endpoint_response(role_config.endpoint.model_dump())
        llm_settings.append(LLMRoleResponse(
            role=role,
            source=role_config.source,
            endpoint=endpoint_response,
        ))

    return SettingsResponse(
        profiles=profiles,
        current_profile=current_profile_id,
        folders=folders,
        markers=markers,
        wildcards=wildcards,
        prompt_segments=prompt_segments,
        background_work=background_work,
        tool_providers=tool_providers,
        llm_settings=llm_settings,
        bundle_id=get_bundle_id(),
        sandbox=get_sandbox(),
        cloud_base_url=settings.cloud.base_url,
        developer_mode=settings.developer_mode,
        theme=settings.theme,
        telemetry_enabled=settings.telemetry.enabled,
        distribution=get_distribution(),
        privacy_lockdown_active=is_privacy_lockdown(),
        default_model=settings.default_model,
    )


@router.get("/heroicons", response_model=List[HeroiconResponse])
async def list_heroicons():
    """List available heroicons for the marker icon picker."""
    return [
        HeroiconResponse(name=name, ref=f"heroicons:{name}")
        for name in COMMON_HEROICONS
    ]


# =============================================================================
# Global Settings Endpoints
# =============================================================================


class UpdateDeveloperModeRequest(BaseModel):
    """Request to update developer mode setting."""
    enabled: bool


@router.patch("/developer-mode")
async def update_developer_mode(request: UpdateDeveloperModeRequest):
    """Update the developer mode setting (global)."""
    patch_global_section("developer_mode", request.enabled)
    log.info("developer_mode updated", enabled=request.enabled)
    return {"status": "success", "developer_mode": request.enabled}


class UpdateThemeRequest(BaseModel):
    """Request to update theme setting."""
    theme: str


@router.patch("/theme")
async def update_theme(request: UpdateThemeRequest):
    """Update the theme setting (global)."""
    if request.theme not in ("light", "dark", "system"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Theme must be 'light', 'dark', or 'system'")
    patch_global_section("theme", request.theme)
    log.info("theme updated", theme=request.theme)
    from telemetry import get_telemetry_client
    get_telemetry_client().track("theme_changed", {"theme": request.theme})
    return {"status": "success", "theme": request.theme}


class UpdateTelemetryRequest(BaseModel):
    """Request to update telemetry setting."""
    enabled: bool


@router.patch("/telemetry")
async def update_telemetry(request: UpdateTelemetryRequest):
    """Update the telemetry consent setting (global).

    The telemetry client handles the transition: a consent-on flushes the
    pre-consent buffer; a consent-off clears anything buffered locally and
    sends nothing.
    """
    settings = get_settings()
    section = settings.telemetry.model_dump()
    section["enabled"] = request.enabled
    patch_global_section("telemetry", section)
    settings.telemetry.enabled = request.enabled
    log.info("telemetry updated", enabled=request.enabled)
    from telemetry import get_telemetry_client
    get_telemetry_client().on_consent_changed(request.enabled)
    return {"status": "success", "telemetry_enabled": request.enabled}


class UpdateDefaultModelRequest(BaseModel):
    """Request to update the global default model."""
    default_model: str


@router.patch("/default-model")
async def update_default_model(request: UpdateDefaultModelRequest):
    """Update the global default model slug."""
    patch_global_section("default_model", request.default_model)
    log.info("default model updated", default_model=request.default_model)
    return {"status": "success", "default_model": request.default_model}


# =============================================================================
# Profile-Scoped Endpoints
# =============================================================================


@router.patch("/folders")
async def update_folders(request: UpdateFoldersRequest):
    """Update folders for the current profile.

    Replaces all folders with the provided list.
    """
    current_profile_id = get_current_profile()

    # Capture old folder paths for telemetry comparison
    settings = get_settings()
    old_folder_paths = set()
    for p in settings.profiles:
        if p.id == current_profile_id:
            old_folder_paths = {f.path for f in p.folders}
            break

    # Convert to dict format for config writer
    folders_data = [
        {
            "path": f.path,
            "readonly": f.readonly,
            "allow_generate": f.allow_generate,
            "is_uploads_folder": f.is_uploads_folder,
            "uploads_subfolder": f.uploads_subfolder,
            "refresh_interval_seconds": f.refresh_interval_seconds,
            "markers": f.markers,
        }
        for f in request.folders
    ]

    # Validate folders
    try:
        validate_folders(folders_data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        patch_profile_section(current_profile_id, "folders", folders_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log.info("folders updated", profile=current_profile_id, count=len(folders_data))

    # Track folder add/remove telemetry
    new_folder_paths = {f["path"] for f in folders_data}
    added_count = len(new_folder_paths - old_folder_paths)
    removed_count = len(old_folder_paths - new_folder_paths)
    if added_count > 0 or removed_count > 0:
        from telemetry import get_telemetry_client
        tc = get_telemetry_client()
        if added_count > 0:
            tc.track("folder_added", {"count": added_count})
        if removed_count > 0:
            tc.track("folder_removed", {"count": removed_count})

    # Immediately sync auto-markers for all media in folders with markers
    await _sync_folder_auto_markers(current_profile_id, folders_data)

    return {"status": "success", "message": "Folders updated"}


async def _sync_folder_auto_markers(profile_id: str, folders_data: list[dict]):
    """Sync auto-markers for all media in folders after config change."""
    # Build FolderConfig objects for sync function
    profile_folders = [FolderConfig(**f) for f in folders_data]

    if not profile_folders:
        log.info("No folders configured, skipping auto-marker sync")
        return

    try:
        registry = get_database_registry()
        db = registry.get_database(profile_id)
        async with db.async_session_maker() as session:
            # Get all media items in ALL folders (needed for both adding and removing)
            media_items = []
            for folder in profile_folders:
                folder_prefix = folder.path if folder.path.endswith('/') else folder.path + '/'
                result = await session.execute(
                    select(MediaItem.id, MediaItem.file_path).where(
                        MediaItem.deleted_at.is_(None),
                        MediaItem.file_path.like(f"{folder_prefix}%")
                    )
                )
                media_items.extend([(row.id, row.file_path) for row in result.all()])

            if not media_items:
                log.info("No media items in any folders")
                return

            log.info(f"Syncing auto-markers for {len(media_items)} media items")

            # Sync auto-markers (handles both adding and removing)
            await sync_auto_markers_for_items(session, media_items, profile_folders)
            await session.commit()

            # Broadcast a single event to tell clients to refresh their marker caches
            # (much more efficient than sending individual media_updated for each item)
            await ws_manager.broadcast("auto_markers_synced", {
                "folder_paths": [f.path for f in profile_folders],
                "media_count": len(media_items)
            })

            log.info(f"Auto-marker sync complete for {len(media_items)} items")
    except Exception as e:
        log.error(f"Failed to sync auto-markers: {e}")


@router.patch("/markers")
async def update_markers(request: UpdateMarkersRequest):
    """Update markers for the current profile.

    Replaces all markers with the provided list. New markers without an ID
    will have one auto-generated. Existing markers keep their ID for stable
    database references.
    """
    import uuid
    import re
    current_profile_id = get_current_profile()

    # Convert to dict format for config writer, generating IDs for new markers
    markers_data = []
    for m in request.markers:
        marker_dict = {
            "name": m.name,
            "icon_svg": m.icon_svg,
            "color": m.color,
        }
        # Preserve existing ID or generate new one
        if m.id:
            marker_dict["id"] = m.id
        else:
            # Generate stable ID from name
            slug = re.sub(r'[^a-z0-9-]', '', m.name.lower().replace(' ', '-'))
            marker_dict["id"] = f"{slug}-{str(uuid.uuid4())[:8]}" if slug else str(uuid.uuid4())[:8]
        markers_data.append(marker_dict)

    # Validate markers
    try:
        validate_markers(markers_data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        patch_profile_section(current_profile_id, "markers", markers_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log.info("markers updated", profile=current_profile_id, count=len(markers_data))
    return {"status": "success", "message": "Markers updated"}


@router.patch("/wildcards")
async def update_wildcards(request: UpdateWildcardsRequest):
    """Update wildcards for the current profile.

    Replaces all wildcards with the provided list.
    """
    current_profile_id = get_current_profile()

    wildcards_data = [
        {"name": w.name, "values": w.values}
        for w in request.wildcards
    ]

    try:
        patch_profile_section(current_profile_id, "wildcards", wildcards_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log.info("wildcards updated", profile=current_profile_id, count=len(wildcards_data))
    return {"status": "success", "message": "Wildcards updated"}


@router.patch("/prompt-segments")
async def update_prompt_segments(request: UpdatePromptSegmentsRequest):
    """Update prompt segments for the current profile.

    Replaces all prompt segments with the provided list.
    """
    current_profile_id = get_current_profile()

    segments_data = [
        {"name": s.name, "content": s.content}
        for s in request.prompt_segments
    ]

    try:
        patch_profile_section(current_profile_id, "prompt_segments", segments_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log.info("prompt_segments updated", profile=current_profile_id, count=len(segments_data))
    return {"status": "success", "message": "Prompt segments updated"}


# =============================================================================
# Global Endpoints
# =============================================================================


@router.patch("/tool-providers/{provider_id}")
async def update_tool_provider_endpoint(
    provider_id: str,
    request: UpdateToolProviderRequest,
):
    """Update a tool provider.

    Supports updating enabled status, API key, and provider configuration.
    When connection-critical fields change (url, command, args), the provider
    is automatically reconnected with the new settings.
    """
    updates = {}

    # Handle enabled toggle
    if request.enabled is not None:
        updates["enabled"] = request.enabled

    # Only update API key if a new value is provided (not the masked placeholder)
    if request.api_key is not None and not request.api_key.startswith("***"):
        updates["api_key"] = request.api_key

    # Handle provider configuration updates
    if request.name is not None:
        updates["name"] = request.name
    if request.command is not None:
        updates["command"] = request.command
    if request.args is not None:
        updates["args"] = request.args
    if request.working_dir is not None:
        updates["working_dir"] = request.working_dir
    if request.url is not None:
        updates["url"] = request.url

    if not updates:
        return {"status": "success", "message": "No changes"}

    try:
        update_tool_provider(provider_id, updates)
    except ValueError as e:
        # If the provider doesn't exist but it's in ALWAYS_SHOW_BUILTIN_PROVIDERS,
        # create it first then apply updates
        builtin_match = next(
            (b for b in ALWAYS_SHOW_BUILTIN_PROVIDERS if b["id"] == provider_id),
            None
        )
        if builtin_match:
            from config_writer import add_tool_provider
            new_provider = {
                "id": builtin_match["id"],
                "name": builtin_match["name"],
                "type": builtin_match["type"],
                "enabled": updates.get("enabled", True),
                **{k: v for k, v in updates.items() if k != "enabled"},
            }
            add_tool_provider(new_provider)
            log.info("created builtin provider config", provider=provider_id)
        elif provider_id == STIMMA_CLOUD_PROVIDER_ID:
            # Handle stimma-cloud specially - create minimal config entry when disabling
            from config_writer import add_tool_provider
            new_provider = {
                "id": STIMMA_CLOUD_PROVIDER_ID,
                "name": "Stimma Cloud",
                "type": "websocket",
                "enabled": updates.get("enabled", True),
            }
            add_tool_provider(new_provider)
            log.info("created stimma-cloud provider config", provider=provider_id)
        else:
            raise HTTPException(status_code=404, detail=str(e))

    log.info("tool provider updated", provider=provider_id, updates=list(updates.keys()))

    # Handle stimma-cloud enable/disable - need to connect/disconnect immediately
    if provider_id == STIMMA_CLOUD_PROVIDER_ID and "enabled" in updates:
        from routes.cloud import connect_cloud_internal, disconnect_cloud_internal
        from firebase_auth import get_valid_id_token

        if updates["enabled"]:
            # Re-enable: try to connect
            try:
                id_token = await get_valid_id_token()
                if id_token:
                    await connect_cloud_internal(id_token)
                    log.info("stimma-cloud re-enabled and reconnected")
            except Exception as e:
                log.warning("failed to reconnect stimma-cloud after enabling", error=str(e))
        else:
            # Disable: disconnect
            await disconnect_cloud_internal()
            log.info("stimma-cloud disabled and disconnected")

    return {"status": "success", "message": "Provider updated"}


@router.post("/tool-providers", response_model=ToolProviderResponse)
async def create_tool_provider_endpoint(request: CreateToolProviderRequest):
    """Create a new tool provider (stdio or websocket only).

    Builtin providers cannot be created via API.
    """
    settings = get_settings()

    # Check if ID already exists
    for provider in settings.tool_providers:
        if provider.id == request.id:
            raise HTTPException(status_code=400, detail=f"Provider with ID '{request.id}' already exists")

    # Validate type-specific fields
    if request.type == "stdio" and not request.command:
        raise HTTPException(status_code=400, detail="Command is required for stdio providers")
    if request.type == "websocket" and not request.url:
        raise HTTPException(status_code=400, detail="URL is required for websocket providers")

    # Create provider config
    new_provider = {
        "id": request.id,
        "name": request.name or request.id,
        "type": request.type,
        "enabled": True,
    }

    if request.type == "stdio":
        new_provider["command"] = request.command
        new_provider["args"] = request.args
        if request.working_dir:
            new_provider["working_dir"] = request.working_dir
    else:  # websocket
        new_provider["url"] = request.url

    # Add to config
    from config_writer import add_tool_provider
    add_tool_provider(new_provider)

    log.info("tool provider created", provider=request.id, type=request.type)
    # providerType only — the user-entered label never egresses (fix #6).
    from telemetry import get_telemetry_client
    get_telemetry_client().track("tool_provider_added", {
        "providerType": request.type,
    }, category="generation")

    return ToolProviderResponse(
        id=request.id,
        name=request.name or request.id,
        type=request.type,
        enabled=True,
        status="disconnected",
        command=request.command if request.type == "stdio" else None,
        url=request.url if request.type == "websocket" else None,
    )


@router.delete("/tool-providers/{provider_id}")
async def delete_tool_provider_endpoint(provider_id: str):
    """Delete a tool provider.

    Only stdio and websocket providers can be deleted. Builtin providers cannot be deleted.
    """
    settings = get_settings()

    # Find the provider
    provider = None
    for p in settings.tool_providers:
        if p.id == provider_id:
            provider = p
            break

    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    if provider.type == "builtin":
        raise HTTPException(status_code=400, detail="Cannot delete builtin providers")

    # Remove from config
    from config_writer import remove_tool_provider
    remove_tool_provider(provider_id)

    log.info("tool provider deleted", provider=provider_id)
    from telemetry import get_telemetry_client
    get_telemetry_client().track("tool_provider_removed", category="generation")
    return {"status": "success", "message": "Provider deleted"}


@router.patch("/background-work")
async def update_background_work(request: UpdateBackgroundWorkRequest):
    """Update background work settings (face detection, CLIP, captioning).

    After updating settings, signals the ingestion worker to reload its config
    so the new enabled flags take effect immediately.
    """
    from core.app import get_reload_config_event

    settings = get_settings()

    # Update face detection
    if request.face_detection is not None:
        face_data = settings.face_detection.model_dump()

        for key, value in request.face_detection.items():
            if key == "enabled":
                face_data["enabled"] = bool(value)
            elif key == "min_confidence":
                try:
                    validate_confidence(value)
                except ValidationError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                face_data["min_confidence"] = value
            elif key == "max_faces":
                try:
                    validate_max_faces(value)
                except ValidationError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                face_data["max_faces"] = value
            elif key == "parallelism":
                try:
                    validate_parallelism(value)
                except ValidationError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                face_data["parallelism"] = value

        patch_global_section("face_detection", face_data)

    # Update CLIP
    if request.clip is not None:
        clip_data = settings.clip.model_dump()

        for key, value in request.clip.items():
            if key == "enabled":
                clip_data["enabled"] = bool(value)

        patch_global_section("clip", clip_data)

    # Update captioning
    if request.captioning is not None:
        captioning_data = settings.captioning.model_dump()

        for key, value in request.captioning.items():
            if key == "enabled":
                captioning_data["enabled"] = bool(value)
            elif key == "parallelism":
                try:
                    validate_captioning_parallelism(value)
                except ValidationError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                captioning_data["parallelism"] = value

        patch_global_section("captioning", captioning_data)

    # Signal ingestion worker to reload config so new settings take effect
    reload_event = get_reload_config_event()
    if reload_event is not None:
        reload_event.set()
        log.info("signaled ingestion worker to reload config")

    log.info("background work settings updated")
    return {"status": "success", "message": "Background work settings updated"}


# =============================================================================
# LLM Settings Endpoints
# =============================================================================


VALID_LLM_ROLES = {"agent", "agent-fast"}
VALID_LLM_SOURCES = {"auto", "stimma_cloud", "endpoint"}


@router.patch("/llms/{role}", response_model=LLMRoleResponse)
async def update_llm_settings(role: str, request: LLMUpdateRequest):
    """Update LLM configuration for a specific role.

    Supports three independent sources:
    - stimma_cloud: Uses Stimma Cloud LLM endpoint
    - litellm: Uses a LiteLLM provider (openrouter, anthropic, etc.)
    - endpoint: Uses an OpenAI-compatible custom endpoint

    Each source config is updated independently and preserved for easy switching.
    """
    if role not in VALID_LLM_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of: {', '.join(VALID_LLM_ROLES)}"
        )

    # Validate source if provided
    if request.source is not None and request.source not in VALID_LLM_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source '{request.source}'. Must be one of: {', '.join(VALID_LLM_SOURCES)}"
        )

    settings = get_settings()

    # Get existing config or create default
    if role in settings.llms:
        role_config = settings.llms[role]
        existing_data = {
            "source": role_config.source,
            "endpoint": role_config.endpoint.model_dump() if role_config.endpoint else None,
        }
    else:
        existing_data = {
            "source": "stimma_cloud",
            "endpoint": None,
        }

    # Update source if provided
    if request.source is not None:
        existing_data["source"] = request.source

    # Update endpoint config if any endpoint fields provided
    has_endpoint_updates = any([
        request.endpoint_url is not None,
        request.endpoint_model is not None,
        request.endpoint_api_key is not None,
        request.endpoint_max_context_tokens is not None,
        request.endpoint_content_policy_enabled is not None,
        request.endpoint_extra_system_prompt is not None,
        request.endpoint_extra_body is not None,
        request.endpoint_reasoning_method is not None,
        request.endpoint_reasoning_method_source is not None,
    ])

    if has_endpoint_updates:
        if existing_data["endpoint"] is None:
            existing_data["endpoint"] = {"url": "", "model": ""}

        endpoint = existing_data["endpoint"]

        if request.endpoint_url is not None:
            endpoint["url"] = request.endpoint_url

        if request.endpoint_model is not None:
            endpoint["model"] = request.endpoint_model

        # Only update API key if not masked placeholder
        if request.endpoint_api_key is not None and not request.endpoint_api_key.startswith("***"):
            if request.endpoint_api_key:
                endpoint["api_key"] = request.endpoint_api_key
            else:
                endpoint.pop("api_key", None)

        if request.endpoint_max_context_tokens is not None:
            # Clamp to a sane band; matches the UI slider (32k..256k).
            endpoint["max_context_tokens"] = max(32_000, min(262_144, int(request.endpoint_max_context_tokens)))

        if request.endpoint_content_policy_enabled is not None:
            endpoint["content_policy_enabled"] = bool(request.endpoint_content_policy_enabled)

        if request.endpoint_extra_system_prompt is not None:
            endpoint["extra_system_prompt"] = request.endpoint_extra_system_prompt

        if request.endpoint_extra_body is not None:
            # Empty dict clears it.
            endpoint["extra_body"] = request.endpoint_extra_body or None

        if request.endpoint_reasoning_method is not None:
            endpoint["reasoning_method"] = request.endpoint_reasoning_method or None

        if request.endpoint_reasoning_method_source is not None:
            endpoint["reasoning_method_source"] = request.endpoint_reasoning_method_source

    # Write updated config
    _update_llm_config(role, existing_data)

    log.info("llm settings updated", role=role, source=existing_data["source"])

    # Build response
    endpoint_response = None
    if existing_data["endpoint"]:
        endpoint_response = _endpoint_response(existing_data["endpoint"])

    return LLMRoleResponse(
        role=role,
        source=existing_data["source"],
        endpoint=endpoint_response,
    )


@router.post("/llms/{role}/test", response_model=LLMTestResponse)
async def test_llm_connection(role: str):
    """Test the LLM connection for a specific role.

    Runs scenarios against the endpoint to verify text completion, thinking/reasoning
    extraction, tool calling, and vision capabilities.
    """
    import time
    import json
    import base64
    import struct
    import zlib
    from llm_resolver import LLMUnavailableError, get_effective_llm_config
    from llm import llm_completion, strip_thinking_tags

    if role not in VALID_LLM_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{role}'. Must be one of: {', '.join(VALID_LLM_ROLES)}"
        )

    # Profile the configured endpoint directly when one exists — this screen is
    # about the local endpoint, regardless of which source the role resolves to.
    role_config = get_settings().llms.get(role)
    if role_config and role_config.endpoint and role_config.endpoint.url:
        config = role_config.endpoint
    else:
        try:
            config = await get_effective_llm_config(role)
        except (ValueError, LLMUnavailableError) as e:
            return LLMTestResponse(
                success=False,
                error=f"No valid configuration: {str(e)}"
            )

    overall_start = time.time()
    scenarios, detected = await _profile_endpoint(config)
    total_elapsed = int((time.time() - overall_start) * 1000)
    text_passed = scenarios.get("text", LLMScenarioResult(passed=False)).passed

    tested_endpoint = bool(role_config and role_config.endpoint and role_config.endpoint.url) \
        and "stimma.ai" not in (config.get_api_base() or "")
    if tested_endpoint:
        # Remember when this endpoint was last tested (pass or fail) so the UI can
        # show "tested N days ago" instead of re-testing on every startup.
        try:
            _persist_test_meta(text_passed)
        except Exception as e:
            log.warning(f"failed to persist test meta: {e}")
    if detected:
        # Persist auto-detected reasoning so the agent/utility path uses the right
        # dialect. Manual overrides are respected inside _persist_detection.
        try:
            _persist_detection(detected.reasoning_method, detected.runtime, detected.reasoning_mode, detected.reasoning_output)
        except Exception as e:
            log.warning(f"failed to persist endpoint detection: {e}")
    log.info("llm test complete", role=role, elapsed_ms=total_elapsed,
             scenarios={k: v.passed for k, v in scenarios.items()})
    return LLMTestResponse(success=text_passed, elapsed_ms=total_elapsed, scenarios=scenarios, detected=detected)


async def _profile_endpoint(config) -> "tuple[dict, Optional[LLMDetected]]":
    """Probe an endpoint for capabilities + reasoning behavior (pure; no persistence).

    Returns (scenarios, detected). Used by the test route and reusable for
    profiling arbitrary endpoints.
    """
    import time, base64, struct, zlib
    from llm import llm_completion

    scenarios: dict[str, LLMScenarioResult] = {}

    # Cloud configs resolve+inject reasoning server-side; only profile local ones.
    is_local = "stimma.ai" not in (config.get_api_base() or "")
    is_openrouter = "openrouter.ai" in (config.get_api_base() or "")
    runtime: Optional[str] = None
    reasoning_output: Optional[str] = None
    reasoning_off: Optional[bool] = None  # did it reason when asked NOT to?
    reasoning_on: Optional[bool] = None   # did it reason when asked to?

    def _ms(start: float) -> int:
        return int((time.time() - start) * 1000)

    # --- Probe 1: thinking OFF (also the "text" capability) ---
    t0 = time.time()
    try:
        off = await llm_completion(config,
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Reply concisely."},
                {"role": "user", "content": "What is the capital of France? Reply in one sentence."},
            ],
            max_tokens=1024, temperature=0.1,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            apply_endpoint_extras=False,
        )
        elapsed = _ms(t0)
        runtime = _detect_runtime(off) or runtime
        reasoning_off = bool(off.thinking)
        if off.content:
            scenarios["text"] = LLMScenarioResult(passed=True, elapsed_ms=elapsed, detail=off.content[:80])
        elif off.thinking:
            # Model works but spent the turn reasoning — fine, just an always-on reasoner.
            scenarios["text"] = LLMScenarioResult(passed=True, elapsed_ms=elapsed, detail="Reasons before answering")
        else:
            scenarios["text"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error="Empty response")
    except Exception as e:
        scenarios["text"] = LLMScenarioResult(passed=False, elapsed_ms=_ms(t0), error=str(e)[:200])

    # --- Probe 2: thinking ON (also the "thinking" capability) ---
    # Each dialect is sent ALONE — strict gateways (OpenRouter) 400 when you mix
    # reasoning_effort with chat_template_kwargs/thinking. reasoning_effort is the
    # broadest (OpenAI/OpenRouter/vLLM), so try it first; fall back to the
    # vLLM/Qwen enable_thinking template flag only if it didn't reason.
    reasoning_method: Optional[str] = None
    THINK_Q = [{"role": "user", "content": "A bat and ball cost $1.10. The bat costs $1.00 more than the ball. How much is the ball? Think it through."}]

    async def _think_probe(extra: dict):
        return await llm_completion(config, messages=THINK_Q, max_tokens=2048,
                                    temperature=0.3, extra_body=extra, apply_endpoint_extras=False)

    t0 = time.time()
    try:
        on = await _think_probe({"reasoning_effort": "high"})
        runtime = _detect_runtime(on) or runtime
        reasoning_on = bool(on.thinking)
        if reasoning_on:
            reasoning_method = "reasoning_effort"
        elif on.content and is_local:
            # Didn't reason via reasoning_effort — try the vLLM/Qwen template flag.
            try:
                alt = await _think_probe({"chat_template_kwargs": {"enable_thinking": True}})
                if alt.thinking:
                    on = alt
                    reasoning_on = True
                    reasoning_method = "enable_thinking"
            except Exception:
                pass
        reasoning_output = _reasoning_location(on) or reasoning_output
        elapsed = _ms(t0)
        if on.thinking and on.content:
            scenarios["thinking"] = LLMScenarioResult(passed=True, elapsed_ms=elapsed, detail="Content + reasoning extracted")
        elif on.content:
            scenarios["thinking"] = LLMScenarioResult(passed=True, elapsed_ms=elapsed, detail="Answered without separate reasoning")
        else:
            scenarios["thinking"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error="No content extracted")
    except Exception as e:
        reasoning_on = False
        scenarios["thinking"] = LLMScenarioResult(passed=False, elapsed_ms=_ms(t0), error=str(e)[:200])

    # --- Verify the OFF switch for the chosen method ---
    # Probe 2 picks the dialect that turns reasoning ON, but the utility path
    # mostly needs it OFF. Some self-hosted vLLM/Qwen builds honor
    # reasoning_effort:"high" for ON yet ignore reasoning_effort:"none" for OFF —
    # they blank the reasoning field but still spend the full token budget
    # reasoning, which starves the answer and stalls the call. The template-level
    # enable_thinking flag is the reliable lever there, so when it verifiably
    # suppresses reasoning on a reasoning-eliciting prompt, prefer it.
    if reasoning_on and reasoning_method == "reasoning_effort" and is_local and not is_openrouter:
        try:
            off_check = await _think_probe({"chat_template_kwargs": {"enable_thinking": False}})
            if not off_check.thinking:
                reasoning_method = "enable_thinking"
        except Exception:
            pass

    # --- Classify reasoning mode (method was set above by whichever probe reasoned) ---
    reasoning_mode: Optional[str] = None
    if is_local:
        if reasoning_off or reasoning_on:
            # If reasoning showed up even when asked off, it's always-on; otherwise
            # it's controllable. OpenRouter gets its own method (it has a real
            # off-switch); elsewhere reasoning_effort is the default lever.
            if is_openrouter:
                reasoning_method = "openrouter"
            else:
                reasoning_method = reasoning_method or "reasoning_effort"
            reasoning_mode = "always" if reasoning_off else "toggleable"
        else:
            reasoning_method, reasoning_mode = "none", "none"
        if is_openrouter and not runtime:
            runtime = "OpenRouter"

    # --- Tools scenario ---
    t0 = time.time()
    try:
        weather_tool = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string", "description": "City name"}},
                    "required": ["location"],
                },
            },
        }
        resp = await llm_completion(config,
            messages=[
                {"role": "system", "content": "Use the provided tools when appropriate."},
                {"role": "user", "content": "What's the weather in Tokyo?"},
            ],
            tools=[weather_tool], max_tokens=1024, temperature=0.1,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            apply_endpoint_extras=False,
        )
        elapsed = int((time.time() - t0) * 1000)
        if resp.tool_calls:
            scenarios["tools"] = LLMScenarioResult(passed=True, elapsed_ms=elapsed, detail=f"Called {resp.tool_calls[0].name}")
        else:
            scenarios["tools"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error=f"No tool call — got text: {resp.content[:80]}")
    except Exception as e:
        error_str = str(e)[:200]
        elapsed = int((time.time() - t0) * 1000)
        if "tool" in error_str.lower() and "auto" in error_str.lower():
            scenarios["tools"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error="Tool calling not enabled on this endpoint")
        else:
            scenarios["tools"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error=error_str)

    # --- Vision scenario ---
    t0 = time.time()
    try:
        # Generate a 16x16 red square PNG
        w, h = 16, 16
        raw_data = b""
        for _ in range(h):
            raw_data += b"\x00" + b"\xff\x00\x00" * w
        def _chunk(ct, d):
            c = ct + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw_data)) + _chunk(b"IEND", b"")
        b64 = base64.b64encode(png).decode()

        resp = await llm_completion(config,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image in one sentence."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            max_tokens=1024, temperature=0.1,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            apply_endpoint_extras=False,
        )
        elapsed = int((time.time() - t0) * 1000)
        if resp.content:
            scenarios["vision"] = LLMScenarioResult(passed=True, elapsed_ms=elapsed, detail=resp.content[:80])
        else:
            scenarios["vision"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error="Empty response")
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        error_str = str(e)[:200]
        if "image" in error_str.lower() or "vision" in error_str.lower() or "multimodal" in error_str.lower():
            scenarios["vision"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error="Vision not supported by this model")
        else:
            scenarios["vision"] = LLMScenarioResult(passed=False, elapsed_ms=elapsed, error=error_str)

    # At minimum, text must pass for detection to be meaningful.
    text_passed = scenarios.get("text", LLMScenarioResult(passed=False)).passed
    detected = None
    if is_local and text_passed:
        detected = LLMDetected(
            runtime=runtime,
            reasoning_method=reasoning_method,
            reasoning_mode=reasoning_mode,
            reasoning_output=reasoning_output,
        )
    return scenarios, detected


@router.post("/llms/endpoint/models", response_model=LLMEndpointModelsResponse)
async def list_endpoint_models(request: LLMEndpointModelsRequest):
    """List model IDs advertised by an OpenAI-compatible endpoint's /models route.

    Lets the settings UI auto-fill the model name when an endpoint serves a
    single model. Probed server-side to avoid browser CORS limits against
    local endpoints (vLLM, Ollama, LM Studio, etc.).
    """
    import httpx

    url = (request.url or "").strip().rstrip("/")
    if not url:
        return LLMEndpointModelsResponse(models=[], error="No endpoint URL")
    try:
        from privacy_lockdown import raise_for_stimma_url_if_enabled
        raise_for_stimma_url_if_enabled(url, "Stimma endpoint checks")
    except Exception as e:
        return LLMEndpointModelsResponse(models=[], error=str(e)[:200])

    # Resolve the API key: prefer the plaintext value from the form; if it's
    # absent or the masked placeholder, fall back to the saved agent key.
    api_key = request.api_key
    if not api_key or api_key.startswith("•") or api_key.startswith("***"):
        role_config = get_settings().llms.get("agent")
        api_key = role_config.endpoint.api_key if role_config and role_config.endpoint else None

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            resp = await client.get(f"{url}/models", headers=headers)
    except Exception as e:
        return LLMEndpointModelsResponse(models=[], error=str(e)[:200])

    if resp.status_code >= 400:
        return LLMEndpointModelsResponse(models=[], error=f"HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception:
        return LLMEndpointModelsResponse(models=[], error="Invalid response")

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return LLMEndpointModelsResponse(models=[], error="Unexpected response shape")

    models = [m["id"] for m in items if isinstance(m, dict) and m.get("id")]
    return LLMEndpointModelsResponse(models=models)


def _detect_runtime(resp) -> Optional[str]:
    """Best-effort runtime name from a response's system_fingerprint."""
    import re
    raw = getattr(resp, "_raw", None)
    fp = (getattr(raw, "system_fingerprint", "") or "").lower() if raw else ""
    if "vllm" in fp:
        m = re.search(r"vllm-(\d+\.\d+)", fp)
        return f"vLLM {m.group(1)}" if m else "vLLM"
    if "llama" in fp or "llamacpp" in fp:
        return "llama.cpp"
    if "ollama" in fp:
        return "Ollama"
    return None


def _reasoning_location(resp) -> Optional[str]:
    """Where the model put its reasoning: a structured field, or inline tags."""
    raw = getattr(resp, "_raw", None)
    try:
        msg = raw.choices[0].message
        for attr in ("reasoning_content", "reasoning", "thinking"):
            v = getattr(msg, attr, None)
            if v and isinstance(v, str) and v.strip():
                return "field"
    except Exception:
        pass
    return "tags" if getattr(resp, "thinking", None) else None


def _persist_detection(reasoning_method, runtime, reasoning_mode, reasoning_output):
    """Save profiler results to every endpoint config whose reasoning method is
    still on auto. Manual overrides are never touched."""
    settings = get_settings()
    for r in ("agent", "agent-fast"):
        rc = settings.llms.get(r)
        if not rc or not rc.endpoint or not rc.endpoint.url:
            continue
        ep = rc.endpoint.model_dump()
        if (ep.get("reasoning_method_source") or "auto") == "manual":
            continue
        ep["reasoning_method"] = reasoning_method
        ep["reasoning_method_source"] = "auto"
        ep["detected_runtime"] = runtime
        ep["reasoning_mode"] = reasoning_mode
        ep["reasoning_output"] = reasoning_output
        _update_llm_config(r, {"source": rc.source, "endpoint": ep})


def _persist_test_meta(passed: bool):
    """Stamp last-tested time + result on every endpoint config (both roles share
    the same endpoint). Independent of reasoning detection / manual overrides."""
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    settings = get_settings()
    for r in ("agent", "agent-fast"):
        rc = settings.llms.get(r)
        if not rc or not rc.endpoint or not rc.endpoint.url:
            continue
        ep = rc.endpoint.model_dump()
        ep["last_tested_at"] = now_iso
        ep["last_test_passed"] = bool(passed)
        _update_llm_config(r, {"source": rc.source, "endpoint": ep})


def _update_llm_config(role: str, data: dict):
    """Update LLM config in the config file.

    Uses ruamel.yaml to preserve comments and formatting.
    """
    from ruamel.yaml import YAML
    import tempfile

    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    yaml_parser.width = 120

    config_path = app_dirs.get_config_path()

    with open(config_path, 'r') as f:
        config = yaml_parser.load(f)

    # Ensure llms section exists
    if "llms" not in config:
        config["llms"] = {}

    # Update the specific role
    config["llms"][role] = data

    # Write atomically
    import config_writer
    config_writer._app_initiated_write = True
    fd, temp_path = tempfile.mkstemp(suffix='.yaml', dir=config_path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            yaml_parser.dump(config, f)

        # Backup existing config
        backup_path = config_path.with_suffix('.yaml.bak')
        if config_path.exists():
            shutil.copy2(config_path, backup_path)

        # Atomic rename
        os.replace(temp_path, config_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    # Reload settings
    from config import reload_settings
    reload_settings()


# =============================================================================
# Profile CRUD Endpoints
# =============================================================================


def _generate_unique_profile_id() -> str:
    """Generate a unique nanoid-based profile ID.

    Format: profile-<6 chars from a-zA-Z0-9> (e.g., profile-k3Rm9x).
    Retries if there's a collision with existing profiles.
    """
    settings = get_settings()
    existing_ids = {p.id for p in settings.profiles}

    # Retry until unique (collision is astronomically unlikely)
    for _ in range(10):
        profile_id = generate_profile_id()
        if profile_id not in existing_ids:
            return profile_id

    # Fallback should never be reached
    return generate_profile_id()


@router.post("/profiles", response_model=ProfileResponse)
async def create_profile_endpoint(request: CreateProfileRequest):
    """Create a new profile.

    Auto-generates an ID from the name. Creates the profile directory.
    """
    profile_id = _generate_unique_profile_id()

    try:
        create_profile(profile_id, request.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create profile directory
    profile_dir = app_dirs.get_profile_dir(profile_id)
    profile_dir.mkdir(parents=True, exist_ok=True)

    from telemetry import get_telemetry_client
    get_telemetry_client().track("profile_created")

    log.info("profile created", profile_id=profile_id, name=request.name)

    return ProfileResponse(
        id=profile_id,
        name=request.name,
        media_count=0,
    )


@router.delete("/profiles/{profile_id}")
async def delete_profile_endpoint(profile_id: str):
    """Delete a profile and its database.

    Cannot delete the only remaining profile or the current profile.
    """
    current_profile_id = get_current_profile()

    if profile_id == current_profile_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the currently active profile"
        )

    settings = get_settings()
    if len(settings.profiles) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the only remaining profile"
        )

    # Check profile exists
    profile = settings.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Delete from config
    try:
        delete_profile_config(profile_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Delete profile directory (contains database)
    profile_dir = app_dirs.get_profile_dir(profile_id)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)

    log.info("profile deleted", profile_id=profile_id)

    from telemetry import get_telemetry_client
    get_telemetry_client().track("profile_deleted", category="settings")

    return {"status": "success", "message": "Profile deleted"}


@router.patch("/profiles/{profile_id}")
async def rename_profile_endpoint(profile_id: str, request: RenameProfileRequest):
    """Rename a profile."""
    try:
        rename_profile(profile_id, request.name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log.info("profile renamed", profile_id=profile_id, new_name=request.name)
    return {"status": "success", "message": "Profile renamed"}


# =============================================================================
# Database Cleanup Endpoints
# =============================================================================


def _is_path_under_folders(file_path: str, folder_paths: List[str]) -> bool:
    """Check if a file path is under any of the configured folders."""
    for folder_path in folder_paths:
        # Normalize: ensure folder ends with /
        folder_prefix = folder_path if folder_path.endswith('/') else folder_path + '/'
        if file_path.startswith(folder_prefix) or file_path == folder_path:
            return True
    return False


@router.get("/database/cleanup-preview", response_model=DatabaseCleanupPreviewResponse)
async def get_database_cleanup_preview():
    """Preview what database cleanup will delete.

    Returns counts of:
    - orphaned_count: Files from folders NOT in current config
    - missing_count: Files marked unavailable from configured folders
    """
    settings = get_settings()
    current_profile_id = get_current_profile()

    # Get configured folder paths
    folder_configs = settings.get_folders_for_profile(current_profile_id)
    folder_paths = [f.path for f in folder_configs]

    registry = get_database_registry()
    db = registry.get_database(current_profile_id)

    orphaned_count = 0
    missing_count = 0

    async with db.async_session_maker() as session:
        # Get all non-deleted media items
        result = await session.execute(
            select(MediaItem.id, MediaItem.file_path, MediaItem.file_unavailable).where(
                MediaItem.deleted_at.is_(None)
            )
        )
        items = result.fetchall()

        for item_id, file_path, file_unavailable in items:
            is_under_config = _is_path_under_folders(file_path, folder_paths)

            if not is_under_config:
                # Orphaned: file is not under any configured folder
                orphaned_count += 1
            elif file_unavailable:
                # Missing: file is marked unavailable but IS under a configured folder
                missing_count += 1

    return DatabaseCleanupPreviewResponse(
        orphaned_count=orphaned_count,
        missing_count=missing_count,
        total_count=orphaned_count + missing_count,
    )


@router.post("/database/cleanup", response_model=DatabaseCleanupResponse)
async def execute_database_cleanup(request: DatabaseCleanupRequest):
    """Execute database cleanup.

    Permanently deletes (hard delete) database entries for:
    - Orphaned files: Files from folders NOT in current config
    - Missing files: Files marked unavailable from configured folders

    This operation is irreversible.
    """
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Cleanup must be confirmed")

    settings = get_settings()
    current_profile_id = get_current_profile()

    # Get configured folder paths
    folder_configs = settings.get_folders_for_profile(current_profile_id)
    folder_paths = [f.path for f in folder_configs]

    registry = get_database_registry()
    db = registry.get_database(current_profile_id)

    orphaned_ids = []
    missing_ids = []

    async with db.async_session_maker() as session:
        # Get all non-deleted media items
        result = await session.execute(
            select(MediaItem.id, MediaItem.file_path, MediaItem.file_unavailable).where(
                MediaItem.deleted_at.is_(None)
            )
        )
        items = result.fetchall()

        for item_id, file_path, file_unavailable in items:
            is_under_config = _is_path_under_folders(file_path, folder_paths)

            if not is_under_config:
                orphaned_ids.append(item_id)
            elif file_unavailable:
                missing_ids.append(item_id)

        # Hard delete the items (permanent deletion, not soft delete)
        all_ids = orphaned_ids + missing_ids
        if all_ids:
            from sqlalchemy import delete
            # Delete related records first (cascade may not handle all)
            from database import BoardItem, MediaMarker, MediaTag, MediaKeyword, Face, MediaLineage

            # Delete junction table entries
            await session.execute(delete(MediaMarker).where(MediaMarker.media_id.in_(all_ids)))
            await session.execute(delete(MediaTag).where(MediaTag.media_id.in_(all_ids)))
            await session.execute(delete(BoardItem).where(BoardItem.media_id.in_(all_ids)))
            await session.execute(delete(MediaKeyword).where(MediaKeyword.media_id.in_(all_ids)))
            await session.execute(delete(Face).where(Face.media_id.in_(all_ids)))
            await session.execute(delete(MediaLineage).where(MediaLineage.media_id.in_(all_ids)))
            await session.execute(delete(MediaLineage).where(MediaLineage.source_media_id.in_(all_ids)))

            # Delete media items
            await session.execute(delete(MediaItem).where(MediaItem.id.in_(all_ids)))

            await session.commit()

    log.info(
        "database cleanup completed",
        profile=current_profile_id,
        orphaned_forgotten=len(orphaned_ids),
        missing_forgotten=len(missing_ids),
    )

    return DatabaseCleanupResponse(
        orphaned_forgotten=len(orphaned_ids),
        missing_forgotten=len(missing_ids),
        total_forgotten=len(all_ids),
    )


# =============================================================================
# Agent Settings Endpoints (per-profile)
# =============================================================================


class AgentToolConfigResponse(BaseModel):
    """Tool configuration for agent settings."""
    allowed_tools: List[str] = []
    denied_tools: List[str] = []
    v2_permissions: Dict[str, str] = {}  # V2 tool permissions: tool_name -> "allow" | "deny"


class AgentSettingsResponse(BaseModel):
    """Per-profile agent settings response."""
    additional_instructions: str
    memory: str
    tool_config: AgentToolConfigResponse


class AgentSettingsUpdate(BaseModel):
    """Request to update per-profile agent settings."""
    additional_instructions: Optional[str] = None
    memory: Optional[str] = None
    tool_config: Optional[AgentToolConfigResponse] = None


@router.get("/agent", response_model=AgentSettingsResponse)
async def get_agent_settings():
    """Get agent settings for the current profile."""
    settings = get_settings()
    current_profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(current_profile_id)

    return AgentSettingsResponse(
        additional_instructions=agent_config.additional_instructions,
        memory=agent_config.memory,
        tool_config=AgentToolConfigResponse(
            allowed_tools=agent_config.tool_config.allowed_tools,
            denied_tools=agent_config.tool_config.denied_tools,
            v2_permissions=agent_config.tool_config.v2_permissions,
        ),
    )


@router.patch("/agent", response_model=AgentSettingsResponse)
async def update_agent_settings(request: AgentSettingsUpdate):
    """Update agent settings for the current profile.

    Updates the profile's agent section in config.yaml and triggers a config reload.
    """
    settings = get_settings()
    current_profile_id = get_current_profile()
    agent_config = settings.get_agent_for_profile(current_profile_id)

    # Build updated agent config (profile-level, no llm_params)
    agent_data = {
        "additional_instructions": agent_config.additional_instructions,
        "memory": agent_config.memory,
        "tool_config": {
            "allowed_tools": agent_config.tool_config.allowed_tools,
            "denied_tools": agent_config.tool_config.denied_tools,
            "v2_permissions": agent_config.tool_config.v2_permissions,
        },
    }

    # Apply updates
    if request.additional_instructions is not None:
        agent_data["additional_instructions"] = request.additional_instructions
    if request.memory is not None:
        agent_data["memory"] = request.memory
    if request.tool_config is not None:
        agent_data["tool_config"] = {
            "allowed_tools": request.tool_config.allowed_tools,
            "denied_tools": request.tool_config.denied_tools,
            "v2_permissions": request.tool_config.v2_permissions,
        }

    # Write to profile's agent section in config
    try:
        patch_profile_section(current_profile_id, "agent", agent_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Reload settings to pick up the changes immediately
    from config import reload_settings
    reload_settings()

    log.info("agent settings updated", profile=current_profile_id)

    # Return updated settings
    return AgentSettingsResponse(
        additional_instructions=agent_data["additional_instructions"],
        memory=agent_data.get("memory", ""),
        tool_config=AgentToolConfigResponse(
            allowed_tools=agent_data["tool_config"]["allowed_tools"],
            denied_tools=agent_data["tool_config"]["denied_tools"],
            v2_permissions=agent_data["tool_config"].get("v2_permissions", {}),
        ),
    )


# =============================================================================
# Stimpacks Endpoints
# =============================================================================

from fastapi import UploadFile, File as FastAPIFile
from fastapi.responses import Response


def _stimpacks_api():
    # Import lazily: importing agent.v2.stimpacks runs agent.v2.__init__, which
    # registers all agent tools and can pull heavy image/ML modules into startup.
    from agent.v2 import stimpacks
    return stimpacks


class SkillResponse(BaseModel):
    """One skill inside a stimpack — the flat, agent-facing capability unit."""
    slug: str
    qualified_name: str
    display_name: str
    description: str
    environments: dict  # {chat: bool, flow: bool, tool: bool | {task_types: [...]}}
    provides: list[str] = []
    pack_name: str
    pack_display_name: str


class StimpackResponse(BaseModel):
    name: str
    display_name: str
    description: str
    author: str
    tags: list[str]
    tier: str  # "local" | "marketplace"
    source: str  # "profile" | "dev"
    is_dev: bool = False
    marketplace_version: int | None = None  # version number if from marketplace
    marketplace_author: str | None = None  # marketplace author username
    marketplace_author_avatar_key: str | None = None
    skills: list[SkillResponse] = []


class StimpackDetailResponse(StimpackResponse):
    content: str


class StimpackCreateRequest(BaseModel):
    name: str
    display_name: str = ""
    description: str = ""
    tags: list[str] = []
    content: str


class StimpackUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    content: str | None = None


def _skill_info_to_response(skill) -> SkillResponse:
    return SkillResponse(
        slug=skill.slug,
        qualified_name=skill.qualified_name,
        display_name=skill.display_name,
        description=skill.description,
        environments=skill.environments.to_dict(),
        provides=skill.provides,
        pack_name=skill.pack_name,
        pack_display_name=skill.pack_display_name,
    )


def _stimpack_info_to_response(s) -> StimpackResponse:
    return StimpackResponse(
        name=s.name,
        display_name=s.display_name,
        description=s.description,
        author=s.author,
        tags=s.tags,
        tier=s.tier,
        source="dev" if getattr(s, "is_dev", False) else "profile",
        is_dev=bool(getattr(s, "is_dev", False)),
        marketplace_version=s.marketplace.version if s.marketplace else None,
        marketplace_author=s.marketplace.author if s.marketplace else None,
        marketplace_author_avatar_key=s.marketplace.author_avatar_key if s.marketplace and s.marketplace.author_avatar_key else None,
        skills=[_skill_info_to_response(sk) for sk in s.skills],
    )


def _stimpack_detail_response(info, content: str) -> StimpackDetailResponse:
    return StimpackDetailResponse(
        name=info.name,
        display_name=info.display_name,
        description=info.description,
        author=info.author,
        tags=info.tags,
        tier=info.tier,
        source="dev" if getattr(info, "is_dev", False) else "profile",
        is_dev=bool(getattr(info, "is_dev", False)),
        marketplace_version=info.marketplace.version if info.marketplace else None,
        marketplace_author=info.marketplace.author if info.marketplace else None,
        marketplace_author_avatar_key=info.marketplace.author_avatar_key if info.marketplace and info.marketplace.author_avatar_key else None,
        content=content,
    )


@router.get("/stimpacks", response_model=list[StimpackResponse])
async def list_stimpacks_endpoint():
    """List installed stimpacks for the current profile."""
    profile_id = get_current_profile()
    stimpacks = _stimpacks_api().list_installed_stimpacks(profile_id=profile_id)
    return [_stimpack_info_to_response(s) for s in stimpacks]


@router.get("/stimpacks-dir")
async def get_stimpacks_dir():
    """Path of the profile's stimpacks folder — packs dropped/edited here load live."""
    from agent.v2.stimpacks import get_user_stimpacks_dir
    profile_id = get_current_profile()
    return {"path": str(get_user_stimpacks_dir(profile_id))}


@router.post("/stimpacks/{name}/validate")
async def validate_stimpack_endpoint(name: str):
    """Run the stimpack validator against an installed pack's directory."""
    from agent.v2.stimpack_validate import validate_pack
    profile_id = get_current_profile()
    installed = _stimpacks_api().list_installed_stimpacks(profile_id=profile_id)
    info = next((s for s in installed if s.name == name), None)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stimpack '{name}' not found")
    report, warnings, errors = validate_pack(info.dir_path)
    return {"valid": not errors, "report": report, "warnings": warnings, "errors": errors}


@router.get("/skills", response_model=list[SkillResponse])
async def list_skills_endpoint():
    """List all skills across installed stimpacks, flat."""
    profile_id = get_current_profile()
    skills = _stimpacks_api().list_skills(profile_id=profile_id)
    return [_skill_info_to_response(s) for s in skills]


@router.get("/skills/{name:path}/content")
async def get_skill_content_endpoint(name: str):
    """Return one skill's markdown body (frontmatter stripped) by qualified name."""
    profile_id = get_current_profile()
    loaded = _stimpacks_api().load_skill(name, profile_id=profile_id)
    if not loaded:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return {
        "qualified_name": loaded.skill.qualified_name,
        "display_name": loaded.skill.display_name,
        "content": loaded.content,
    }


@router.get("/stimpacks/{name}/download")
async def download_stimpack_zip(name: str):
    """Download a stimpack packaged as a zip file."""
    profile_id = get_current_profile()
    zip_bytes = _stimpacks_api().package_stimpack_as_zip(name, profile_id=profile_id)
    if not zip_bytes:
        raise HTTPException(status_code=404, detail=f"Stimpack '{name}' not found")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@router.get("/stimpacks/{name}", response_model=StimpackDetailResponse)
async def get_stimpack_endpoint(name: str):
    profile_id = get_current_profile()
    loaded = _stimpacks_api().load_stimpack(name, profile_id=profile_id)
    if not loaded:
        raise HTTPException(status_code=404, detail=f"Stimpack '{name}' not found")
    return _stimpack_detail_response(loaded.info, loaded.content)


@router.post("/stimpacks", response_model=StimpackDetailResponse, status_code=201)
async def create_stimpack_endpoint(data: StimpackCreateRequest):
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()
    existing = stimpacks_api.load_stimpack(data.name, profile_id=profile_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Stimpack '{data.name}' already exists")
    stimpacks_api.save_stimpack(
        data.name,
        data.content,
        description=data.description,
        display_name=data.display_name,
        tags=data.tags,
        profile_id=profile_id,
    )
    loaded = stimpacks_api.load_stimpack(data.name, profile_id=profile_id)
    return _stimpack_detail_response(loaded.info, loaded.content)


@router.post("/stimpacks/upload", response_model=StimpackResponse)
async def upload_stimpack_endpoint(file: UploadFile = FastAPIFile(...)):
    """Upload and install a stimpack from a .md or .zip file."""
    profile_id = get_current_profile()
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    from pathlib import Path
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".md", ".zip"):
        raise HTTPException(status_code=400, detail="Only .md and .zip files are supported")

    import tempfile as _tempfile
    with _tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        info = _stimpacks_api().install_stimpack_from_file(tmp_path, profile_id=profile_id)
        if not info:
            raise HTTPException(status_code=400, detail="Failed to parse stimpack file")
        return _stimpack_info_to_response(info)
    finally:
        tmp_path.unlink(missing_ok=True)


@router.put("/stimpacks/{name}", response_model=StimpackDetailResponse)
async def update_stimpack_endpoint(name: str, data: StimpackUpdateRequest):
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()
    existing = stimpacks_api.load_stimpack(name, profile_id=profile_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Stimpack '{name}' not found")
    if existing.info.is_dev:
        raise HTTPException(
            status_code=400,
            detail="Dev stimpacks are read-only here. Edit the sibling stimma-skills repository instead.",
        )

    # Merge: use existing values for any None fields
    new_display_name = data.display_name if data.display_name is not None else existing.info.display_name
    new_description = data.description if data.description is not None else existing.info.description
    new_tags = data.tags if data.tags is not None else existing.info.tags
    new_content = data.content if data.content is not None else existing.content
    stimpacks_api.save_stimpack(
        name,
        new_content,
        description=new_description,
        display_name=new_display_name,
        tags=new_tags,
        profile_id=profile_id,
    )
    loaded = stimpacks_api.load_stimpack(name, profile_id=profile_id)
    # D17: this editor route fires for user-authored stimpacks too — the name
    # passes only when the stimpack is a marketplace install (catalog data).
    from telemetry import get_telemetry_client
    _source = stimpacks_api.telemetry_stimpack_source(loaded.info if loaded else None)
    _props = {"stimpackSource": _source}
    if _source == "marketplace":
        _props["stimpackName"] = name
    get_telemetry_client().track("stimpack_updated", _props, category="stimpacks")
    return _stimpack_detail_response(loaded.info, loaded.content)


@router.delete("/stimpacks/{name}", status_code=204)
async def delete_stimpack_endpoint(name: str):
    """Uninstall a stimpack from the current profile."""
    profile_id = get_current_profile()
    stimpacks_api = _stimpacks_api()
    # Classify before deletion (the sidecar is gone afterwards).
    existing = stimpacks_api.load_stimpack(name, profile_id=profile_id)
    if existing and existing.info.is_dev:
        raise HTTPException(
            status_code=400,
            detail="Dev stimpacks are read-only here. Remove or edit them in the sibling stimma-skills repository.",
        )
    deleted = stimpacks_api.delete_stimpack(name, profile_id=profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Stimpack '{name}' not found")

    from telemetry import get_telemetry_client
    _source = stimpacks_api.telemetry_stimpack_source(existing.info if existing else None)
    _props = {"stimpackSource": _source}
    if _source == "marketplace":
        _props["stimpackName"] = name
    get_telemetry_client().track("stimpack_uninstalled", _props, category="stimpacks")

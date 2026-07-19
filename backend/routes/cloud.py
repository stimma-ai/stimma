"""
Cloud tool provider routes for Stimma Cloud.

Stimma Cloud is a WebSocket-based tool provider that auto-connects when the user
is logged in. Access is decided per-request by balance on the cloud side.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from config import get_settings
from core.logging import get_logger
from cloud_runtime import cloud_access_headers, with_cloud_access_headers
from privacy_lockdown import disabled_message, is_privacy_lockdown_enabled
from tool_provider_identity import STIMMA_TOOL_PROVIDER_DISPLAY_NAME, STIMMA_TOOL_PROVIDER_ID
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/cloud", tags=["cloud"])
log = get_logger(__name__)

# Provider ID for Stimma Cloud - used as a constant
STIMMA_CLOUD_PROVIDER_ID = STIMMA_TOOL_PROVIDER_ID


class ConnectRequest(BaseModel):
    """Request to connect to Stimma Cloud tools."""
    token: str


class ConnectResponse(BaseModel):
    """Response from cloud tools connect."""
    success: bool
    provider_id: str
    error: Optional[str] = None


class DisconnectResponse(BaseModel):
    """Response from cloud tools disconnect."""
    success: bool


def _http_to_ws_url(http_url: str) -> str:
    """Convert an HTTP(S) URL to WS(S) URL."""
    if http_url.startswith("https://"):
        return "wss://" + http_url[8:]
    elif http_url.startswith("http://"):
        return "ws://" + http_url[7:]
    return http_url


async def _refresh_cloud_token(config: dict) -> bool:
    """Refresh the auth token for Stimma Cloud before reconnection.

    Called by the manager before each connection attempt to ensure
    the Firebase ID token is fresh (they expire after 1 hour).
    """
    from firebase_auth import get_valid_id_token

    if is_privacy_lockdown_enabled():
        log.info("skipping cloud token refresh in Privacy Lockdown")
        await disconnect_cloud_internal()
        return False

    try:
        fresh_token = await get_valid_id_token()
        if fresh_token:
            config['auth_token'] = fresh_token
            log.debug("refreshed cloud auth token")
            return True

        # get_valid_id_token() clears auth state when Firebase rejects the
        # saved session. Do not fall back to a stale token for the operation
        # that triggered this refresh.
        from auth_storage import load_auth_state
        if not (load_auth_state() or {}).get('refresh_token'):
            log.info("cloud token refresh found no signed-in session")
            await disconnect_cloud_internal()
            return False

        # A transient refresh failure preserves auth state. The cached token
        # may still be accepted, so keep the connection alive.
        return True
    except Exception as e:
        log.warning("failed to refresh cloud auth token", error=str(e))
        # Don't update config - try with existing token
        return True


async def reconcile_cloud_connection() -> bool:
    """Make the cloud STP connection match the current account state."""
    from auth_storage import load_auth_state
    from firebase_auth import get_valid_id_token
    from providers import ProviderRegistry

    settings = get_settings()
    cloud_config = next(
        (p for p in settings.tool_providers if p.id == STIMMA_CLOUD_PROVIDER_ID),
        None,
    )
    enabled = cloud_config is None or cloud_config.enabled
    auth_state = load_auth_state()
    signed_in = bool(auth_state and auth_state.get('refresh_token'))

    if is_privacy_lockdown_enabled() or not enabled or not signed_in:
        await disconnect_cloud_internal()
        return False

    if ProviderRegistry.get_instance().get_provider(STIMMA_CLOUD_PROVIDER_ID):
        return True

    id_token = await get_valid_id_token()
    token_to_use = id_token or auth_state.get('id_token')
    if not token_to_use:
        if not (load_auth_state() or {}).get('refresh_token'):
            await disconnect_cloud_internal()
        return False

    return await connect_cloud_internal(token_to_use)


async def connect_cloud_internal(id_token: str) -> bool:
    """Internal function to connect to Stimma Cloud with given token.

    Uses the JsonRpcManager for proper reconnection handling - same as other
    WebSocket providers. The manager handles:
    - Initial connection with retries
    - Auto-reconnect on disconnect (indefinitely for websocket providers)
    - Proper backend unregistration on disconnect to prevent job loops
    - Token refresh before each reconnect attempt

    Args:
        id_token: Firebase ID token for authentication

    Returns:
        True if connection succeeded, False otherwise
    """
    from providers.jsonrpc_manager import get_jsonrpc_manager

    if is_privacy_lockdown_enabled():
        log.info("stimma cloud connect blocked by Privacy Lockdown")
        return False

    # A caller-supplied ID token is not sufficient authority to create a
    # desktop provider connection. Persisted account state is the source of
    # truth for whether Stimma Cloud exists as a connection.
    from auth_storage import load_auth_state
    auth_state = load_auth_state()
    if not auth_state or not auth_state.get('refresh_token'):
        log.info("stimma cloud connect skipped because the user is signed out")
        await disconnect_cloud_internal()
        return False

    settings = get_settings()
    base_url = settings.cloud.base_url
    ws_url = _http_to_ws_url(base_url) + "/stp-v1"

    log.info("connecting to stimma cloud", ws_url=ws_url)

    jsonrpc_manager = get_jsonrpc_manager()

    # Remove existing provider from manager if present (handles cleanup)
    await jsonrpc_manager.remove_provider(STIMMA_CLOUD_PROVIDER_ID)

    # Build config dict for the manager (same format as config file providers)
    config = {
        "id": STIMMA_CLOUD_PROVIDER_ID,
        "name": STIMMA_TOOL_PROVIDER_DISPLAY_NAME,
        "type": "websocket",
        "url": ws_url,
        "auth_token": id_token,
        "headers": cloud_access_headers(),
        "enabled": True,
    }

    # Add provider via manager with token refresh callback
    # The callback refreshes the Firebase ID token before each reconnect attempt
    success = await jsonrpc_manager.add_provider(
        config,
        token_refresh_callback=_refresh_cloud_token,
    )

    if success:
        # Broadcast tools_updated so frontend refreshes tool lists
        await ws_manager.broadcast("tools_updated", {}, include_profile=False)

    return success


async def disconnect_cloud_internal() -> bool:
    """Internal function to disconnect from Stimma Cloud.

    Used by both the /tools/disconnect endpoint and logout flow.

    Returns:
        True (always succeeds - goal is to be disconnected)
    """
    from providers.jsonrpc_manager import get_jsonrpc_manager

    jsonrpc_manager = get_jsonrpc_manager()

    try:
        # Remove from manager - handles unregistration and cleanup
        await jsonrpc_manager.remove_provider(STIMMA_CLOUD_PROVIDER_ID)

        # Defensive cleanup for stale registry entries left by an interrupted
        # reconnect whose manager state has already disappeared.
        from providers import ProviderRegistry
        await ProviderRegistry.get_instance().unregister(STIMMA_CLOUD_PROVIDER_ID)

        log.info("stimma cloud disconnected")

        # Broadcast tools_updated so frontend refreshes tool lists
        await ws_manager.broadcast("tools_updated", {}, include_profile=False)

        return True

    except Exception as e:
        log.error("failed to disconnect from stimma cloud", error=str(e))
        # Return true anyway - the goal is to be disconnected
        return True


@router.post("/tools/connect", response_model=ConnectResponse)
async def connect_cloud_tools(request: ConnectRequest):
    """
    Connect to Stimma Cloud as a tool provider.

    Creates a WebSocket-based JsonRpcProvider for the cloud and registers it.
    The token is a Firebase ID token that authenticates the user.
    """
    if is_privacy_lockdown_enabled():
        return ConnectResponse(
            success=False,
            provider_id=STIMMA_CLOUD_PROVIDER_ID,
            error=disabled_message("Stimma tools"),
        )

    success = await connect_cloud_internal(request.token)

    if success:
        return ConnectResponse(
            success=True,
            provider_id=STIMMA_CLOUD_PROVIDER_ID,
        )
    else:
        from providers.jsonrpc_manager import get_jsonrpc_manager
        jsonrpc_manager = get_jsonrpc_manager()
        error_msg = jsonrpc_manager.get_error_message(STIMMA_CLOUD_PROVIDER_ID)
        return ConnectResponse(
            success=False,
            provider_id=STIMMA_CLOUD_PROVIDER_ID,
            error=error_msg or "Connection failed",
        )


@router.post("/tools/disconnect", response_model=DisconnectResponse)
async def disconnect_cloud_tools():
    """
    Disconnect from Stimma Cloud tool provider.

    Unregisters the cloud provider and cleans up connections.
    """
    await disconnect_cloud_internal()
    return DisconnectResponse(success=True)


@router.get("/tools/status")
async def get_cloud_tools_status():
    """
    Get status of the Stimma Cloud tool provider.

    Returns connection status and tool count if connected.
    """
    from providers import ProviderRegistry
    from providers.jsonrpc_manager import get_jsonrpc_manager

    if is_privacy_lockdown_enabled():
        return {
            "connected": False,
            "status": "privacy_lockdown",
            "error_message": disabled_message("Stimma tools"),
            "tool_count": 0,
        }

    provider_registry = ProviderRegistry.get_instance()
    jsonrpc_manager = get_jsonrpc_manager()

    provider = provider_registry.get_provider(STIMMA_CLOUD_PROVIDER_ID)

    if not provider:
        return {
            "connected": False,
            "status": "disconnected",
            "error_message": jsonrpc_manager.get_error_message(STIMMA_CLOUD_PROVIDER_ID),
            "tool_count": 0,
        }

    tools = await provider.list_tools()

    return {
        "connected": True,
        "status": provider.status.value,
        "error_message": None,
        "tool_count": len(tools),
    }

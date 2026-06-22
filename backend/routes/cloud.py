"""
Cloud tool provider routes for Stimma Cloud.

Stimma Cloud is a WebSocket-based tool provider that auto-connects when the user
is logged in. The server at stimma.ai determines available tools based on account tier.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from config import get_settings
from core.logging import get_logger
from privacy_lockdown import disabled_message, is_privacy_lockdown_enabled
from utils.websocket import ws_manager

router = APIRouter(prefix="/api/cloud", tags=["cloud"])
log = get_logger(__name__)

# Provider ID for Stimma Cloud - used as a constant
STIMMA_CLOUD_PROVIDER_ID = "stimma-cloud"


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


async def _refresh_cloud_token(config: dict) -> None:
    """Refresh the auth token for Stimma Cloud before reconnection.

    Called by the manager before each connection attempt to ensure
    the Firebase ID token is fresh (they expire after 1 hour).
    """
    from firebase_auth import get_valid_id_token

    if is_privacy_lockdown_enabled():
        log.info("skipping cloud token refresh in Privacy Lockdown")
        return

    try:
        fresh_token = await get_valid_id_token()
        if fresh_token:
            config['auth_token'] = fresh_token
            log.debug("refreshed cloud auth token")
        else:
            log.warning("failed to refresh cloud auth token - no token returned")
    except Exception as e:
        log.warning("failed to refresh cloud auth token", error=str(e))
        # Don't update config - try with existing token


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
        "name": "Stimma Cloud",
        "type": "websocket",
        "url": ws_url,
        "auth_token": id_token,
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
            error=disabled_message("Stimma Cloud tools"),
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
            "error_message": disabled_message("Stimma Cloud tools"),
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


class LLMUsageResponse(BaseModel):
    """LLM usage stats from Stimma Cloud."""
    request_count: int = 0
    tokens_used: int = 0
    requests_limit: Optional[int] = None
    tokens_limit: Optional[int] = None


class LLMStatusResponse(BaseModel):
    """Stimma Cloud LLM availability status."""
    available: bool  # True if user has a paid tier
    tier: Optional[str] = None
    usage: Optional[LLMUsageResponse] = None


@router.get("/llm/status", response_model=LLMStatusResponse)
async def get_cloud_llm_status():
    """
    Get Stimma Cloud LLM availability and usage status.

    Returns:
    - available: Whether user has access to cloud LLMs (non-free tier)
    - tier: User's account tier
    - usage: Current usage stats if available

    Returns available=False if user is not logged in or has free tier.
    """
    from firebase_auth import get_valid_id_token
    from cloud_api import fetch_user_account
    import httpx

    if is_privacy_lockdown_enabled():
        return LLMStatusResponse(available=False)

    try:
        id_token = await get_valid_id_token()
        if not id_token:
            return LLMStatusResponse(available=False)

        # Fetch user account info
        account = await fetch_user_account(id_token)
        tier = account.get("tier", "free")

        # Check if user has LLM access (non-free tier)
        # Free tier users don't have access to cloud LLMs
        available = tier.lower() != "free"

        usage = None
        if available:
            # Try to fetch usage stats from Stimma Cloud
            try:
                settings = get_settings()
                base_url = settings.cloud.base_url
                usage_url = f"{base_url}/api/llm/v1/usage"

                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        usage_url,
                        headers={"Authorization": f"Bearer {id_token}"},
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        usage_data = response.json()
                        usage = LLMUsageResponse(
                            request_count=usage_data.get("requestCount", 0),
                            tokens_used=usage_data.get("tokensUsed", 0),
                            requests_limit=usage_data.get("requestsLimit"),
                            tokens_limit=usage_data.get("tokensLimit"),
                        )
            except Exception as e:
                log.warning("failed to fetch llm usage stats", error=str(e))
                # Continue without usage stats

        return LLMStatusResponse(
            available=available,
            tier=tier,
            usage=usage,
        )

    except httpx.HTTPStatusError as e:
        log.warning("failed to fetch cloud account status", status=e.response.status_code)
        return LLMStatusResponse(available=False)
    except Exception as e:
        log.warning("failed to get cloud llm status", error=str(e))
        return LLMStatusResponse(available=False)

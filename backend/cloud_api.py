"""
Stimma Cloud API client.

Provides functions for calling the stimma.cloud API endpoints.
"""
from typing import TypedDict

import httpx

from config import get_settings
from core.logging import get_logger

log = get_logger(__name__)


class CloudAccount(TypedDict):
    """User account info from stimma.cloud."""
    tier: str           # 'free', 'starter', 'pro', etc.
    credits: int        # Account credits
    # May include other fields - preserve them


async def fetch_user_account(id_token: str) -> CloudAccount:
    """Fetch user account info from stimma.cloud.

    Args:
        id_token: Firebase ID token for authentication

    Returns:
        Account info including tier and credits

    Raises:
        httpx.HTTPStatusError: On API errors (401, 403, etc.)
    """
    base_url = get_settings().cloud.base_url
    url = f"{base_url}/api/auth/me"

    from user_agent import ua_headers
    headers = ua_headers()
    headers["Authorization"] = f"Bearer {id_token}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=headers,
            timeout=30.0
        )
        response.raise_for_status()

        data = response.json()
        log.debug("fetched cloud account", tier=data.get('tier'))

        return data


async def revoke_remote_session_if_supported(id_token: str) -> bool:
    """Best-effort remote desktop logout/session revocation.

    Expected cloud contract is documented in docs/DESKTOP_AUTH.md. The endpoint
    is optional for older cloud deployments; missing support must not block
    local logout.
    """
    if not id_token:
        return False

    base_url = get_settings().cloud.base_url
    url = f"{base_url}/api/auth/desktop/logout"

    from user_agent import ua_headers
    headers = ua_headers()
    headers["Authorization"] = f"Bearer {id_token}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, timeout=10.0)

        if response.status_code in (404, 405):
            log.info("cloud desktop logout endpoint not available", status=response.status_code)
            return False

        if response.status_code in (200, 202, 204):
            log.info("cloud desktop logout endpoint accepted session revoke")
            return True

        response.raise_for_status()
        return True

    except httpx.RequestError as e:
        log.warning("could not reach cloud desktop logout endpoint", error=str(e))
        return False
    except httpx.HTTPStatusError as e:
        log.warning(
            "cloud desktop logout endpoint failed",
            status=e.response.status_code,
            error=str(e),
        )
        return False

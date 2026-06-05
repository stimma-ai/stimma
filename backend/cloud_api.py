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

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {id_token}"},
            timeout=30.0
        )
        response.raise_for_status()

        data = response.json()
        log.debug("fetched cloud account", tier=data.get('tier'))

        return data

"""
Shared account-state synchronization.

One place applies a fresh Stimma account payload to the app: persist
credits, connect the cloud tool provider for signed-in accounts, and
broadcast the change to the frontend over the app websocket. Used by
GET /api/auth/account (pull) and the account-events client (push) so
both paths behave identically.

Broadcast events:
- ``account_updated``: every applied refresh; payload mirrors the
  /api/auth/account response shape (credits, usage, ...).
- ``balance_added``: only on an observed zero -> positive balance
  transition (the OOBE first top-up / redeem moment).
"""
import asyncio

from core.logging import get_logger
from privacy_lockdown import is_privacy_lockdown_enabled
from utils.websocket import ws_manager

log = get_logger(__name__)

def account_payload(account: dict) -> dict:
    """The account fields the frontend consumes, matching /api/auth/account."""
    return {
        "tier": account.get('tier', 'free'),
        "tierDisplayName": account.get('tierDisplayName'),
        "credits": account.get('credits', 0),
        "createdAt": account.get('createdAt'),
        "usageWindows": account.get('usageWindows'),
        "usage": account.get('usage'),
        "subscription": account.get('subscription'),
    }


async def apply_account_update(account: dict, id_token: str | None) -> dict:
    """Persist a fresh account payload and react to tier transitions.

    Returns the response-shaped payload. Never raises — connect/disconnect
    and broadcast failures are logged; persisting the tier is the one step
    that must not be skipped, and it happens first.
    """
    from auth_storage import load_auth_state, save_auth_state

    auth_state = load_auth_state()
    if not auth_state:
        # Signed out between fetch and apply — don't resurrect state.
        return account_payload(account)

    previous_credits = auth_state.get('credits')
    new_credits = account.get('credits', 0)

    auth_state['tier'] = account.get('tier', 'free')
    auth_state['credits'] = new_credits
    auth_state['createdAt'] = account.get('createdAt')
    save_auth_state(auth_state)

    await _ensure_cloud_provider_connected(id_token)

    payload = account_payload(account)
    try:
        await ws_manager.broadcast("account_updated", payload, include_profile=False)
        # Celebrate only a real observed zero -> positive transition; an
        # unknown previous balance (fresh login) is not a transition.
        if previous_credits is not None and previous_credits <= 0 and new_credits > 0:
            await ws_manager.broadcast(
                "balance_added",
                {"credits": new_credits},
                include_profile=False,
            )
    except Exception as e:
        log.warning("failed to broadcast account update", error=str(e))

    return payload


async def _ensure_cloud_provider_connected(id_token: str | None) -> None:
    """Attach the cloud tool provider for any signed-in account.

    Access is decided per-request by balance on the cloud side, so the
    provider connects whenever the user is signed in (unless disabled in
    config). Disconnect happens only on sign-out (routes/cloud.py).
    """
    if is_privacy_lockdown_enabled():
        return

    try:
        from config import get_settings
        from providers import ProviderRegistry
        from routes.cloud import (
            STIMMA_CLOUD_PROVIDER_ID,
            connect_cloud_internal,
        )

        cloud_cfg = next(
            (p for p in get_settings().tool_providers if p.id == STIMMA_CLOUD_PROVIDER_ID),
            None,
        )
        disabled_in_config = cloud_cfg is not None and not cloud_cfg.enabled
        already_connected = (
            ProviderRegistry.get_instance().get_provider(STIMMA_CLOUD_PROVIDER_ID) is not None
        )

        if not disabled_in_config and not already_connected and id_token:
            log.info("signed in without cloud tools connected, connecting")
            asyncio.create_task(connect_cloud_internal(id_token))
    except Exception as e:
        log.warning("failed to ensure cloud provider connection", error=str(e))


async def refresh_account_state(source: str) -> dict | None:
    """Fetch the freshest account from Stimma Cloud and apply it.

    Best-effort: returns the applied payload, or None when signed out /
    unreachable. Used by the account-events client on connect and on each
    pushed event.
    """
    from auth_storage import load_auth_state
    from cloud_api import fetch_user_account
    from firebase_auth import get_valid_id_token

    if is_privacy_lockdown_enabled():
        return None

    auth_state = load_auth_state()
    if not auth_state or not auth_state.get('refresh_token'):
        return None

    try:
        id_token = await get_valid_id_token()
        if not id_token:
            return None
        account = await fetch_user_account(id_token)
        payload = await apply_account_update(account, id_token)
        log.debug("account state refreshed", source=source, tier=payload.get('tier'))
        return payload
    except Exception as e:
        log.warning("account refresh failed", source=source, error=str(e))
        return None

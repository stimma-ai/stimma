"""
Shared account-state synchronization.

One place applies a fresh Stimma Cloud account payload to the app: persist
tier/credits, connect or disconnect the cloud tool provider on tier
transitions, and broadcast the change to the frontend over the app websocket.
Used by GET /api/auth/account (pull) and the account-events client (push) so
both paths behave identically.

Broadcast events:
- ``account_updated``: every applied refresh; payload mirrors the
  /api/auth/account response shape (tier, credits, subscription, ...).
- ``subscription_activated``: only on an observed unsubscribed -> subscribed
  transition (the OOBE purchase moment).
"""
import asyncio

from core.logging import get_logger
from privacy_lockdown import is_privacy_lockdown_enabled
from utils.websocket import ws_manager

log = get_logger(__name__)

UNSUBSCRIBED_TIERS = ('free', 'byoai')


def is_subscribed_tier(tier) -> bool:
    t = (tier or '').lower()
    return bool(t) and t not in UNSUBSCRIBED_TIERS


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

    previous_tier = auth_state.get('tier')
    new_tier = account.get('tier', 'free')

    auth_state['tier'] = new_tier
    auth_state['credits'] = account.get('credits', 0)
    auth_state['createdAt'] = account.get('createdAt')
    save_auth_state(auth_state)

    await _apply_tier_transition(previous_tier, new_tier, id_token)

    payload = account_payload(account)
    try:
        await ws_manager.broadcast("account_updated", payload, include_profile=False)
        # Celebrate only a real observed transition; an unknown previous tier
        # (fresh login) is not a transition.
        if previous_tier is not None and not is_subscribed_tier(previous_tier) and is_subscribed_tier(new_tier):
            await ws_manager.broadcast(
                "subscription_activated",
                {"tier": new_tier, "tierDisplayName": account.get('tierDisplayName')},
                include_profile=False,
            )
    except Exception as e:
        log.warning("failed to broadcast account update", error=str(e))

    return payload


async def _apply_tier_transition(previous_tier, new_tier: str, id_token: str | None) -> None:
    """Attach/detach the cloud tool provider to match the (fresh) tier."""
    if is_privacy_lockdown_enabled():
        return

    try:
        from config import get_settings
        from providers import ProviderRegistry
        from routes.cloud import (
            STIMMA_CLOUD_PROVIDER_ID,
            connect_cloud_internal,
            disconnect_cloud_internal,
        )

        cloud_cfg = next(
            (p for p in get_settings().tool_providers if p.id == STIMMA_CLOUD_PROVIDER_ID),
            None,
        )
        disabled_in_config = cloud_cfg is not None and not cloud_cfg.enabled
        already_connected = (
            ProviderRegistry.get_instance().get_provider(STIMMA_CLOUD_PROVIDER_ID) is not None
        )

        if new_tier != 'free' and not disabled_in_config and not already_connected:
            log.info("paid tier without cloud tools connected, connecting", tier=new_tier)
            if id_token:
                asyncio.create_task(connect_cloud_internal(id_token))
        elif new_tier == 'free' and already_connected:
            # Lapsed/canceled subscription: detach instead of reconnect-looping
            # against a cloud that will reject the session.
            log.info("tier dropped to free with cloud tools connected, disconnecting")
            await disconnect_cloud_internal()
    except Exception as e:
        log.warning("failed to apply tier transition", error=str(e))


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

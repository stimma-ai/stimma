"""
Tests for account_sync — the shared pull/push account-state application:
persisting tier/credits, tier-transition side effects, and the
account_updated / subscription_activated websocket broadcasts.
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _account(tier="maker", credits=1234, display="Maker"):
    return {
        "tier": tier,
        "tierDisplayName": display,
        "credits": credits,
        "createdAt": "2026-01-01T00:00:00Z",
        "usageWindows": None,
        "usage": None,
        "subscription": {"status": "active"},
    }


@pytest.fixture
def sync_env(test_app):
    """Patch auth storage, transition side effects, and the ws broadcast."""
    import account_sync

    state = {"auth": {"tier": "free", "credits": 0, "refresh_token": "r"}}
    saved = []
    broadcasts = []
    transitions = []

    async def fake_broadcast(event, data, include_profile=True):
        broadcasts.append((event, data))

    async def fake_transition(prev, new, token):
        transitions.append((prev, new, token))

    with patch("auth_storage.load_auth_state", side_effect=lambda: state["auth"]), \
         patch("auth_storage.save_auth_state", side_effect=saved.append), \
         patch.object(account_sync.ws_manager, "broadcast", side_effect=fake_broadcast), \
         patch.object(account_sync, "_apply_tier_transition", side_effect=fake_transition):
        yield {
            "state": state,
            "saved": saved,
            "broadcasts": broadcasts,
            "transitions": transitions,
        }


async def test_free_to_paid_broadcasts_activation(sync_env):
    from account_sync import apply_account_update

    payload = await apply_account_update(_account(tier="maker"), "tok")

    assert payload["tier"] == "maker"
    assert sync_env["saved"][0]["tier"] == "maker"
    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated", "subscription_activated"]
    activated = sync_env["broadcasts"][1][1]
    assert activated["tier"] == "maker"
    assert sync_env["transitions"] == [("free", "maker", "tok")]


async def test_paid_to_paid_no_activation(sync_env):
    sync_env["state"]["auth"]["tier"] = "maker"
    from account_sync import apply_account_update

    await apply_account_update(_account(tier="creator", display="Creator"), "tok")

    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated"]


async def test_paid_to_free_no_activation(sync_env):
    sync_env["state"]["auth"]["tier"] = "maker"
    from account_sync import apply_account_update

    payload = await apply_account_update(_account(tier="free", display=None), "tok")

    assert payload["tier"] == "free"
    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated"]
    assert sync_env["transitions"] == [("maker", "free", "tok")]


async def test_unknown_previous_tier_no_activation(sync_env):
    """A fresh login (no cached tier) is not a transition — no celebration."""
    sync_env["state"]["auth"] = {"refresh_token": "r"}
    from account_sync import apply_account_update

    await apply_account_update(_account(tier="maker"), "tok")

    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated"]


async def test_signed_out_between_fetch_and_apply(sync_env):
    """No auth state: nothing persisted, nothing broadcast."""
    sync_env["state"]["auth"] = None
    from account_sync import apply_account_update

    payload = await apply_account_update(_account(tier="maker"), "tok")

    assert payload["tier"] == "maker"
    assert sync_env["saved"] == []
    assert sync_env["broadcasts"] == []


async def test_transition_connects_when_paid_and_disconnected(test_app):
    from account_sync import _apply_tier_transition

    connect = AsyncMock(return_value=True)
    disconnect = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_provider.return_value = None  # not connected

    settings = MagicMock()
    settings.tool_providers = []

    with patch("routes.cloud.connect_cloud_internal", connect), \
         patch("routes.cloud.disconnect_cloud_internal", disconnect), \
         patch("providers.ProviderRegistry.get_instance", return_value=registry), \
         patch("config.get_settings", return_value=settings):
        await _apply_tier_transition("free", "maker", "tok")
        # connect is fired as a task
        await asyncio.sleep(0)

    connect.assert_called_once_with("tok")
    disconnect.assert_not_called()


async def test_transition_disconnects_on_lapse(test_app):
    from account_sync import _apply_tier_transition

    connect = AsyncMock(return_value=True)
    disconnect = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_provider.return_value = object()  # connected

    settings = MagicMock()
    settings.tool_providers = []

    with patch("routes.cloud.connect_cloud_internal", connect), \
         patch("routes.cloud.disconnect_cloud_internal", disconnect), \
         patch("providers.ProviderRegistry.get_instance", return_value=registry), \
         patch("config.get_settings", return_value=settings):
        await _apply_tier_transition("maker", "free", "tok")

    disconnect.assert_called_once()
    connect.assert_not_called()


async def test_transition_respects_config_disabled(test_app):
    from account_sync import _apply_tier_transition

    connect = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_provider.return_value = None

    provider_cfg = MagicMock()
    provider_cfg.id = "stimma-cloud"
    provider_cfg.enabled = False
    settings = MagicMock()
    settings.tool_providers = [provider_cfg]

    with patch("routes.cloud.connect_cloud_internal", connect), \
         patch("providers.ProviderRegistry.get_instance", return_value=registry), \
         patch("config.get_settings", return_value=settings):
        await _apply_tier_transition("free", "maker", "tok")
        await asyncio.sleep(0)

    connect.assert_not_called()

"""
Tests for account_sync — the shared pull/push account-state application:
persisting credits, cloud-provider connection, and the
account_updated / balance_added websocket broadcasts.
"""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _account(credits=1234):
    return {
        "credits": credits,
        "createdAt": "2026-01-01T00:00:00Z",
        "usage": None,
    }


@pytest.fixture
def sync_env(test_app):
    """Patch auth storage, connect side effects, and the ws broadcast."""
    import account_sync

    state = {"auth": {"credits": 0, "refresh_token": "r"}}
    saved = []
    broadcasts = []
    connects = []

    async def fake_broadcast(event, data, include_profile=True):
        broadcasts.append((event, data))

    async def fake_connect(token):
        connects.append(token)

    with patch("auth_storage.load_auth_state", side_effect=lambda: state["auth"]), \
         patch("auth_storage.save_auth_state", side_effect=saved.append), \
         patch.object(account_sync.ws_manager, "broadcast", side_effect=fake_broadcast), \
         patch.object(account_sync, "_ensure_cloud_provider_connected", side_effect=fake_connect):
        yield {
            "state": state,
            "saved": saved,
            "broadcasts": broadcasts,
            "connects": connects,
        }


async def test_zero_to_positive_broadcasts_balance_added(sync_env):
    from account_sync import apply_account_update

    payload = await apply_account_update(_account(credits=1000), "tok")

    assert payload["credits"] == 1000
    assert sync_env["saved"][0]["credits"] == 1000
    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated", "balance_added"]
    added = sync_env["broadcasts"][1][1]
    assert added["credits"] == 1000
    assert sync_env["connects"] == ["tok"]


async def test_positive_to_positive_no_celebration(sync_env):
    sync_env["state"]["auth"]["credits"] = 500
    from account_sync import apply_account_update

    await apply_account_update(_account(credits=1500), "tok")

    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated"]


async def test_positive_to_zero_no_celebration(sync_env):
    sync_env["state"]["auth"]["credits"] = 500
    from account_sync import apply_account_update

    payload = await apply_account_update(_account(credits=0), "tok")

    assert payload["credits"] == 0
    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated"]


async def test_unknown_previous_balance_no_celebration(sync_env):
    """A fresh login (no cached credits) is not a transition — no celebration."""
    sync_env["state"]["auth"] = {"refresh_token": "r"}
    from account_sync import apply_account_update

    await apply_account_update(_account(credits=1000), "tok")

    events = [e for e, _ in sync_env["broadcasts"]]
    assert events == ["account_updated"]


async def test_signed_out_between_fetch_and_apply(sync_env):
    """No auth state: nothing persisted, nothing broadcast."""
    sync_env["state"]["auth"] = None
    from account_sync import apply_account_update

    payload = await apply_account_update(_account(credits=1000), "tok")

    assert payload["credits"] == 1000
    assert sync_env["saved"] == []
    assert sync_env["broadcasts"] == []


async def test_connects_when_signed_in_and_disconnected(test_app):
    from account_sync import _ensure_cloud_provider_connected

    connect = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_provider.return_value = None  # not connected

    settings = MagicMock()
    settings.tool_providers = []

    with patch("routes.cloud.connect_cloud_internal", connect), \
         patch("providers.ProviderRegistry.get_instance", return_value=registry), \
         patch("config.get_settings", return_value=settings):
        await _ensure_cloud_provider_connected("tok")
        # connect is fired as a task
        await asyncio.sleep(0)

    connect.assert_called_once_with("tok")


async def test_no_connect_when_already_connected(test_app):
    from account_sync import _ensure_cloud_provider_connected

    connect = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_provider.return_value = object()  # connected

    settings = MagicMock()
    settings.tool_providers = []

    with patch("routes.cloud.connect_cloud_internal", connect), \
         patch("providers.ProviderRegistry.get_instance", return_value=registry), \
         patch("config.get_settings", return_value=settings):
        await _ensure_cloud_provider_connected("tok")
        await asyncio.sleep(0)

    connect.assert_not_called()


async def test_connect_respects_config_disabled(test_app):
    from account_sync import _ensure_cloud_provider_connected

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
        await _ensure_cloud_provider_connected("tok")
        await asyncio.sleep(0)

    connect.assert_not_called()

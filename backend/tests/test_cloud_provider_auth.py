"""Auth ownership of the Stimma Cloud STP provider connection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def test_generic_startup_provider_list_excludes_stimma_cloud():
    from core.app import _saved_jsonrpc_provider_configs

    cloud = MagicMock(id="stimma-cloud", type="websocket")
    cloud.model_dump.return_value = {"id": "stimma-cloud"}
    comfy = MagicMock(id="comfyui", type="websocket")
    comfy.model_dump.return_value = {"id": "comfyui"}
    builtin = MagicMock(id="builtin", type="builtin")
    builtin.model_dump.return_value = {"id": "builtin"}
    settings = SimpleNamespace(tool_providers=[cloud, comfy, builtin])

    assert _saved_jsonrpc_provider_configs(settings) == [{"id": "comfyui"}]


async def test_connect_cloud_refuses_signed_out_state():
    from routes.cloud import connect_cloud_internal

    manager = MagicMock()
    manager.add_provider = AsyncMock()

    with patch("auth_storage.load_auth_state", return_value=None), \
         patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as disconnect, \
         patch("providers.jsonrpc_manager.get_jsonrpc_manager", return_value=manager):
        connected = await connect_cloud_internal("stale-id-token")

    assert connected is False
    disconnect.assert_awaited_once()
    manager.add_provider.assert_not_awaited()


async def test_reconcile_disconnects_cloud_when_signed_out():
    from routes.cloud import reconcile_cloud_connection

    settings = SimpleNamespace(tool_providers=[])
    with patch("routes.cloud.get_settings", return_value=settings), \
         patch("auth_storage.load_auth_state", return_value=None), \
         patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as disconnect:
        connected = await reconcile_cloud_connection()

    assert connected is False
    disconnect.assert_awaited_once()


async def test_disconnect_clears_manager_and_stale_registry_entry():
    from routes.cloud import disconnect_cloud_internal

    manager = MagicMock()
    manager.remove_provider = AsyncMock()
    registry = MagicMock()
    registry.unregister = AsyncMock()

    with patch("providers.jsonrpc_manager.get_jsonrpc_manager", return_value=manager), \
         patch("providers.ProviderRegistry.get_instance", return_value=registry), \
         patch("routes.cloud.ws_manager.broadcast", new_callable=AsyncMock):
        disconnected = await disconnect_cloud_internal()

    assert disconnected is True
    manager.remove_provider.assert_awaited_once_with("stimma-cloud")
    registry.unregister.assert_awaited_once_with("stimma-cloud")


async def test_cloud_token_refresh_blocks_stale_token_when_auth_is_gone():
    from routes.cloud import _refresh_cloud_token

    config = {"auth_token": "stale"}
    with patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value=None), \
         patch("auth_storage.load_auth_state", return_value=None), \
         patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as disconnect:
        allowed = await _refresh_cloud_token(config)

    assert allowed is False
    assert config["auth_token"] == "stale"
    disconnect.assert_awaited_once()

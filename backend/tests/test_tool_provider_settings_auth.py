"""Regression coverage for bearer tokens in STP provider settings."""

from types import SimpleNamespace

import pytest

import config_writer
from routes import settings as settings_routes
from routes import tools as tools_routes


@pytest.mark.asyncio
async def test_create_websocket_provider_persists_auth_token(monkeypatch):
    written = []
    monkeypatch.setattr(settings_routes, "get_settings", lambda: SimpleNamespace(tool_providers=[]))
    monkeypatch.setattr(config_writer, "add_tool_provider", written.append)
    monkeypatch.setattr(
        "telemetry.get_telemetry_client",
        lambda: SimpleNamespace(track=lambda *args, **kwargs: None),
    )

    response = await settings_routes.create_tool_provider_endpoint(
        settings_routes.CreateToolProviderRequest(
            id="secured-provider",
            name="Secured Provider",
            type="websocket",
            url="wss://example.invalid/stp",
            auth_token="top-secret",
        )
    )

    assert written[0]["auth_token"] == "top-secret"
    assert response.has_auth_token is True
    assert "top-secret" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_update_provider_persists_auth_token(monkeypatch):
    written = []
    monkeypatch.setattr(
        settings_routes,
        "update_tool_provider",
        lambda provider_id, updates: written.append((provider_id, updates)),
    )

    await settings_routes.update_tool_provider_endpoint(
        "secured-provider",
        settings_routes.UpdateToolProviderRequest(auth_token="replacement-secret"),
    )

    assert written == [("secured-provider", {"auth_token": "replacement-secret"})]


@pytest.mark.asyncio
async def test_configured_provider_test_uses_saved_token(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        tools_routes,
        "get_settings",
        lambda: SimpleNamespace(
            tool_providers=[SimpleNamespace(id="secured-provider", auth_token="saved-secret")]
        ),
    )

    async def fake_test_provider_connection(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            success=True,
            provider_name="Provider",
            provider_version="1",
            tool_count=1,
            error=None,
            error_type=None,
            server=None,
        )

    monkeypatch.setattr("providers.jsonrpc.test_provider_connection", fake_test_provider_connection)
    monkeypatch.setattr(
        "telemetry.get_telemetry_client",
        lambda: SimpleNamespace(track=lambda *args, **kwargs: None),
    )

    response = await tools_routes.test_connection(
        tools_routes.TestConnectionRequest(
            type="websocket",
            url="wss://example.invalid/stp",
            provider_id="secured-provider",
        )
    )

    assert response.success is True
    assert captured["auth_token"] == "saved-secret"

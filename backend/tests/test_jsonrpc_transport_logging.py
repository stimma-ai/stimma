"""Logging behavior for JSON-RPC transports."""

from unittest.mock import patch

from providers.jsonrpc import WebSocketProviderConfig, WebSocketTransport


async def test_websocket_disconnect_cleanup_logs_at_debug():
    transport = WebSocketTransport(
        WebSocketProviderConfig(id="p1", url="ws://127.0.0.1:8765/stp-v1")
    )

    with patch("providers.jsonrpc.log") as mock_log:
        await transport.disconnect()

    mock_log.debug.assert_called_once_with("websocket disconnected")
    assert mock_log.info.call_count == 0

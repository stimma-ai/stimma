"""Regression coverage for keeping prompt text out of routine logs."""

from unittest.mock import AsyncMock, patch

import pytest

from utils.websocket import WebSocketManager


def _logged_text(mock_log) -> str:
    return repr(mock_log.method_calls)


@pytest.mark.asyncio
async def test_websocket_broadcast_logs_payload_shape_without_content():
    secret_prompt = "PRIVATE PROMPT sentinel-broadcast-93817"
    manager = WebSocketManager()
    socket = AsyncMock()
    manager.attach(socket)

    with patch("utils.websocket.log") as mock_log:
        await manager.broadcast(
            "chat_item_created",
            {
                "chat_id": 42,
                "item": {
                    "item_type": "user_message",
                    "message_text": secret_prompt,
                    "tool_args": {"prompt": secret_prompt},
                },
            },
            include_profile=False,
        )
        await manager.drain()
    await manager.disconnect(socket)

    assert secret_prompt not in _logged_text(mock_log)
    mock_log.info.assert_called_once_with(
        "WS OUT (broadcast)",
        ws_event="chat_item_created",
        data_keys=["chat_id", "item"],
        chat_id=42,
    )
    socket.send_text.assert_awaited_once()
    assert secret_prompt in socket.send_text.await_args.args[0]


@pytest.mark.asyncio
async def test_websocket_direct_logs_payload_shape_without_content():
    secret_prompt = "PRIVATE PROMPT sentinel-direct-48302"
    manager = WebSocketManager()
    socket = AsyncMock()

    with patch("utils.websocket.log") as mock_log:
        await manager.send_to(
            socket,
            "prompt_preview",
            {"request_id": "req-123", "prompt": secret_prompt},
        )

    assert secret_prompt not in _logged_text(mock_log)
    mock_log.info.assert_called_once_with(
        "WS OUT (direct)",
        ws_event="prompt_preview",
        data_keys=["prompt", "request_id"],
        request_id="req-123",
    )
    socket.send_text.assert_awaited_once()
    assert secret_prompt in socket.send_text.await_args.args[0]

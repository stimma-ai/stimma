"""The WS manager's logging must never take a client down with it.

``event`` is structlog's own positional field. Passing it as a keyword raises
TypeError inside the log call itself — which, on the welcome message, killed
the connection before the client was ever usable. A dropped client means no UI
render target, so every SVG and layout thumbnail 503s forever. Cheap to assert,
expensive to miss.
"""
import pytest

from utils.websocket import WebSocketManager


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, message: str):
        self.sent.append(message)


@pytest.mark.asyncio
async def test_send_to_logs_without_shadowing_structlogs_event_field():
    manager = WebSocketManager()
    ws = FakeWebSocket()
    manager.attach(ws)

    await manager.send_to(ws, "connected", {"message": "hi", "chat_id": 7})
    await manager.drain()
    await manager.disconnect(ws)

    assert len(ws.sent) == 1
    assert '"event": "connected"' in ws.sent[0]


@pytest.mark.asyncio
async def test_broadcast_logs_without_shadowing_structlogs_event_field():
    manager = WebSocketManager()
    ws = FakeWebSocket()
    manager.attach(ws)

    await manager.broadcast("media_added", {"media_id": 1})
    await manager.drain()
    await manager.disconnect(ws)

    assert len(ws.sent) == 1
    assert '"event": "media_added"' in ws.sent[0]

"""The loopback listener rejects foreign Host headers (DNS rebinding)."""
import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.loopback_host import LoopbackHostGuard, is_loopback_host


def _app():
    app = FastAPI()

    @app.get('/ping')
    def ping():
        return {'ok': True}

    @app.websocket('/ws')
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text('hello')
        await socket.close()

    return LoopbackHostGuard(app, 9191)


@pytest.mark.parametrize('host,ok', [
    ('127.0.0.1:9191', True), ('localhost:9191', True), ('LOCALHOST:9191', True), ('127.0.0.1', True),
    ('127.0.0.1:9999', False), ('attacker.example:9191', False), ('attacker.example', False),
    ('192.168.1.5:9191', False), ('', False), (None, False),
])
def test_is_loopback_host(host, ok):
    assert is_loopback_host(host, 9191) is ok


def test_http_with_foreign_host_is_rejected():
    assert TestClient(_app(), base_url='http://127.0.0.1:9191').get('/ping').json() == {'ok': True}
    response = TestClient(_app(), base_url='http://attacker.example:9191').get('/ping')
    assert response.status_code == 421


def test_websocket_with_foreign_host_is_rejected():
    client = TestClient(_app())
    with client.websocket_connect('/ws', headers={'host': 'localhost:9191'}) as socket:
        assert socket.receive_text() == 'hello'
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws', headers={'host': 'attacker.example:9191'}) as socket:
            socket.receive_text()

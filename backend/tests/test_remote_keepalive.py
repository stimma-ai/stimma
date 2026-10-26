"""The remote listener keeps idle connections open and says for how long."""
import asyncio
import socket

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from multi_device import server


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/ok")
    async def ok():
        return {"ok": True}

    @app.get("/api/closing")
    async def closing():
        return Response("bye", headers={"Connection": "close"})

    return app


async def _call(gate, path, headers=()):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await gate({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"",
                "headers": list(headers), "scheme": "https", "server": ("test", 443), "client": ("127.0.0.1", 1),
                "root_path": "", "http_version": "1.1", "asgi": {"version": "3.0"}}, receive, send)
    return sent[0]


def _keep_alive(start):
    return [value for name, value in start["headers"] if name.lower() == b"keep-alive"]


@pytest.mark.asyncio
async def test_every_gate_response_advertises_the_keep_alive(monkeypatch):
    monkeypatch.setattr(server, "verify_session", lambda token: token == "session")
    gate = server.ServingGate(_app(), lambda: "server-device")
    auth = [(b"authorization", b"Bearer session")]
    # The unauthenticated ping (what discovery reads), a gate rejection, and app responses.
    assert _keep_alive(await _call(gate, server.PING_PATH)) == [b"timeout=65"]
    assert _keep_alive(await _call(gate, "/api/ok")) == [b"timeout=65"]
    assert _keep_alive(await _call(gate, "/api/ok", auth)) == [b"timeout=65"]
    # A response that closes its connection promises nothing.
    assert _keep_alive(await _call(gate, "/api/closing", auth)) == []


def test_the_remote_listener_keeps_idle_connections_for_the_advertised_time():
    config = server.serving_config(object(), ssl_certfile="cert.pem", ssl_keyfile="key.pem")
    assert config.timeout_keep_alive == server.KEEP_ALIVE_SECONDS == 65
    assert config.ssl_certfile == "cert.pem"


def _request(connection: socket.socket) -> bytes:
    connection.sendall(b"GET /multi-device/ping HTTP/1.1\r\nHost: test\r\n\r\n")
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            return data
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    length = int(next(line.split(b":")[1] for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")))
    while len(body) < length:
        chunk = connection.recv(4096)
        if not chunk:
            break
        body += chunk
    return head


@pytest.mark.asyncio
async def test_a_connection_survives_a_pause_longer_than_uvicorns_default(monkeypatch):
    """Measured on real uvicorn listeners: the remote listener reuses a
    connection after a 6 second pause; a default-configured (older) server
    has already closed it, which is why clients without the advertisement
    must keep their short idle limit."""
    gate = server.ServingGate(_app(), lambda: "server-device")
    servers, tasks, connections = [], [], []
    for config in (server.serving_config(gate), uvicorn.Config(gate, log_config=None, lifespan="on")):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        instance = uvicorn.Server(config)
        instance.install_signal_handlers = lambda: None
        servers.append(instance)
        tasks.append(asyncio.create_task(instance.serve(sockets=[sock])))
        while not instance.started:
            await asyncio.sleep(0.02)
        connection = socket.create_connection(sock.getsockname(), timeout=5)
        connections.append(connection)
    try:
        for connection in connections:
            head = await asyncio.to_thread(_request, connection)
            assert head.startswith(b"HTTP/1.1 200")
        assert b"keep-alive: timeout=65" in (await asyncio.to_thread(_request, connections[0])).lower()
        await asyncio.sleep(6)
        remote, default = connections
        assert (await asyncio.to_thread(_request, remote)).startswith(b"HTTP/1.1 200")
        assert await asyncio.to_thread(_request, default) == b""  # closed by the server
    finally:
        for connection in connections:
            connection.close()
        for instance in servers:
            instance.should_exit = True
        await asyncio.gather(*tasks)

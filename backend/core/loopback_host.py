"""Host validation for the loopback listener.

The local backend listens on 127.0.0.1 only, but a web page can still reach
it through DNS rebinding: its own hostname resolves to 127.0.0.1 and the
browser sends that hostname as Host. Only loopback names are accepted here.
The remote serving listener wraps the same app separately and is unaffected.
"""
from __future__ import annotations

LOOPBACK_NAMES = frozenset({'127.0.0.1', 'localhost'})


def is_loopback_host(value: str | None, port: int) -> bool:
    if not value:
        return False
    name, sep, host_port = value.strip().lower().rpartition(':')
    if not sep:
        name, host_port = host_port, ''
    if host_port and host_port != str(port):
        return False
    return name in LOOPBACK_NAMES


class LoopbackHostGuard:
    """ASGI wrapper rejecting HTTP and WebSocket requests with a foreign Host."""

    def __init__(self, app, port: int):
        self.app = app
        self.port = port

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            host = next((value.decode('latin-1') for key, value in scope.get('headers', ())
                         if key == b'host'), None)
            if not is_loopback_host(host, self.port):
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1008})
                    return
                body = b'{"detail":"Invalid host"}'
                await send({'type': 'http.response.start', 'status': 421,
                            'headers': [(b'content-type', b'application/json'),
                                        (b'content-length', str(len(body)).encode())]})
                await send({'type': 'http.response.body', 'body': body})
                return
        await self.app(scope, receive, send)

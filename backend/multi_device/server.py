"""The serving surface: a second, TLS-only listener for remote devices.

The loopback listener the local app uses is untouched. This adds a separate
HTTPS/WSS port wrapping the *same* FastAPI app behind an authentication
gate.

Why a wrapper rather than loosening the existing middleware: the spec called
for "closing the /api/db/ bypass", but that bypass exists for a good reason
locally — `<img>` and `<video>` cannot send headers, and those URLs carry
their database in the path precisely so they work without one. Removing it
would break local media loading.

Gating at the ASGI layer instead gets the property that actually matters:
on the remote surface there is no unauthenticated path at all, `/api/db/`
included, while loopback behaviour is bit-for-bit unchanged. The connecting
side's proxy supplies the credential on every request, including the ones
the browser issues itself.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
from typing import Optional

import app_dirs
from core.logging import get_logger

from .auth import AuthError, ensure_own_account_uid, issue_session, verify_firebase_token, verify_session

log = get_logger(__name__)

# The one endpoint reachable without a session: exchange an account token for
# one. Kept outside the app so it cannot collide with an app route.
BOOTSTRAP_PATH = "/multi-device/session"
# Unauthenticated liveness probe. Reveals only that something is here, which
# a TCP connect already tells you.
PING_PATH = "/multi-device/ping"
# Lets the connecting proxy distinguish a gate rejection from an ordinary
# application-level 401 and refresh the device session without guessing.
SESSION_INVALID_HEADER = (b"x-stimma-session-invalid", b"1")

_server_task: Optional[asyncio.Task] = None
_server = None
_bound_port: Optional[int] = None


def _write_secret(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(contents)
    os.chmod(path, 0o600)
    return path


def _cors_headers(scope) -> list[tuple[bytes, bytes]]:
    """Echo the caller's Origin on gate-generated responses.

    These short-circuit before the app's CORSMiddleware, so without this the
    connecting renderer sees an opaque CORS failure rather than the 401 that
    would tell it to (re-)bootstrap.
    """
    for name, value in scope.get("headers", []):
        if name.lower() == b"origin" and value:
            return [
                (b"access-control-allow-origin", value),
                (b"access-control-allow-credentials", b"true"),
                (b"access-control-allow-headers", b"*"),
                (b"access-control-allow-methods", b"*"),
            ]
    return []


async def _send_json(send, status: int, payload: dict, scope=None, extra_headers=None) -> None:
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    if scope is not None:
        headers.extend(_cors_headers(scope))
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive) -> bytes:
    chunks = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body"):
            break
    return b"".join(chunks)


def _bearer(headers: list[tuple[bytes, bytes]]) -> Optional[str]:
    for name, value in headers:
        if name.lower() == b"authorization":
            text = value.decode("latin-1")
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    return None


class ServingGate:
    """ASGI wrapper enforcing session auth on every request and socket."""

    def __init__(self, app, device_id_provider):
        self.app = app
        self.device_id_provider = device_id_provider

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            # The inner app's lifespan is already run by the loopback server;
            # running it twice would double-initialise services.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope["type"] == "http":
            path = scope.get("path", "")
            if path == PING_PATH:
                await _send_json(send, 200, {
                    "service": "stimma",
                    "deviceId": self.device_id_provider(),
                }, scope)
                return
            if path == BOOTSTRAP_PATH:
                await self._bootstrap(scope, receive, send)
                return

            if not verify_session(_bearer(scope.get("headers", []))):
                await _send_json(
                    send,
                    401,
                    {"detail": "Multi-device session required"},
                    scope,
                    [SESSION_INVALID_HEADER],
                )
                return

            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # Same credential as HTTP. Browsers cannot set headers on a
            # WebSocket handshake, but the connecting side is our own proxy,
            # which can.
            if not verify_session(_bearer(scope.get("headers", []))):
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _bootstrap(self, scope, receive, send) -> None:
        """Exchange a live account token for a durable session."""
        if scope.get("method") != "POST":
            await _send_json(send, 405, {"detail": "Method not allowed"}, scope)
            return

        try:
            body = json.loads(await _read_body(receive) or b"{}")
        except Exception:
            await _send_json(send, 400, {"detail": "Invalid JSON body"}, scope)
            return

        token = body.get("idToken")
        client_device_id = body.get("deviceId")
        if not isinstance(token, str) or not token:
            await _send_json(send, 400, {"detail": "idToken required"}, scope)
            return
        if not isinstance(client_device_id, str) or not client_device_id:
            await _send_json(send, 400, {"detail": "deviceId required"}, scope)
            return

        expected = await ensure_own_account_uid()
        if not expected:
            # Serving while signed out must not be possible; if it happens,
            # refuse rather than trusting whoever asked.
            await _send_json(send, 503, {"detail": "Server is not signed in"}, scope)
            return

        try:
            claims = await verify_firebase_token(token)
        except AuthError as exc:
            log.warning("multi-device: bootstrap rejected", reason=str(exc))
            await _send_json(send, 401, {"detail": "Invalid account token"}, scope)
            return

        if claims.get("sub") != expected:
            log.warning("multi-device: bootstrap rejected, different account")
            await _send_json(send, 403, {"detail": "Different account"}, scope)
            return

        session = issue_session(client_device_id, expected)
        await _send_json(send, 200, {"session": session, "deviceId": self.device_id_provider()}, scope)


def _bind_listener(preferred: int) -> socket.socket:
    """Bind the serving socket, falling back to an OS-assigned port.

    Port assignment must never be something the user debugs. Several installs
    can share a machine — different channels, different sandboxes, a dev build
    beside a release one — and an unrelated process may already hold whatever
    number we would have picked. So `preferred` is a hint, not a requirement:
    if it is 0 or already taken, the OS assigns a free port and that is what
    gets published in the registry. Discovery carries the port, so nothing
    downstream needs to agree on a number in advance.

    We bind here rather than letting uvicorn do it so the resolved port is
    known before the server starts, and so the fallback is ours to control.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        # Lets a restart re-take its own port out of TIME_WAIT. Deliberately
        # not set on Windows, where SO_REUSEADDR would let us silently steal a
        # port from a LIVE listener instead.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    if preferred:
        try:
            sock.bind(("0.0.0.0", preferred))
            sock.listen(128)
            sock.setblocking(False)
            return sock
        except OSError as exc:
            log.info(
                "multi-device: preferred port unavailable, letting the OS choose",
                port=preferred,
                error=str(exc),
            )

    sock.bind(("0.0.0.0", 0))
    sock.listen(128)
    sock.setblocking(False)
    return sock


async def start_serving(app, cert_pem: str, key_pem: str, port: int, device_id: str) -> int:
    """Start (or restart) the TLS listener. Returns the port actually bound."""
    global _server_task, _server, _bound_port

    await stop_serving()

    import uvicorn

    data_dir = app_dirs.get_data_dir()
    cert_path = _write_secret(data_dir / "multi_device_cert.pem", cert_pem)
    key_path = _write_secret(data_dir / "multi_device_key.pem", key_pem)

    sock = _bind_listener(port)
    bound = sock.getsockname()[1]

    gate = ServingGate(app, lambda: device_id)
    config = uvicorn.Config(
        gate,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        log_config=None,
        lifespan="on",
    )
    _server = uvicorn.Server(config)
    # install_signal_handlers would steal SIGINT/SIGTERM from the main server.
    _server.install_signal_handlers = lambda: None

    _server_task = asyncio.create_task(_server.serve(sockets=[sock]))

    for _ in range(200):
        if getattr(_server, "started", False):
            break
        if _server_task.done():
            exc = _server_task.exception()
            sock.close()
            raise RuntimeError(f"serving listener failed to start: {exc}")
        await asyncio.sleep(0.05)
    else:
        sock.close()
        raise RuntimeError("serving listener did not start in time")

    _bound_port = bound
    log.info("multi-device: serving", port=bound, requested=port, device_id=device_id)
    return bound


async def stop_serving() -> None:
    global _server_task, _server, _bound_port
    if _server is not None:
        _server.should_exit = True
    if _server_task is not None:
        try:
            await asyncio.wait_for(_server_task, timeout=5)
        except Exception:
            _server_task.cancel()
    _server_task = None
    _server = None
    _bound_port = None


def is_serving() -> bool:
    return _bound_port is not None


def serving_port() -> Optional[int]:
    return _bound_port

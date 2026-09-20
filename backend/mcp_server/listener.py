"""A separate MCP-only listener; never exposes the owner's REST API."""
from contextlib import asynccontextmanager, contextmanager
import asyncio
import errno
import ipaddress
import os
import re
import socket

from starlette.responses import JSONResponse

from config import McpDirectConfig, get_settings, reload_settings
from config_writer import patch_global_section


def authority(config):
    host = f"[{config.host}]" if ":" in config.host else config.host
    return f"{host}:{config.port}"


def addresses():
    """Enumerate this backend's interfaces, including VPNs, not the UI host."""
    import psutil

    found = {"127.0.0.1": "Loopback"}
    try:
        interfaces = psutil.net_if_addrs()
    except OSError:
        interfaces = {}
    for interface, items in interfaces.items():
        for item in items:
            if item.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            try:
                host = McpDirectConfig(host=item.address).host
            except ValueError:
                continue
            ip = ipaddress.ip_address(host)
            kind = "Loopback" if ip.is_loopback else "VPN" if (
                ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")
            ) or interface.lower().startswith("tailscale") else interface
            found[host] = kind
    return [{"host": host, "label": f"{label} · {host}"} for host, label in found.items()]


class DirectApp:
    def __init__(self, config):
        from .server import Gateway
        from headless_runtime import MaintenanceGate

        self.authority = authority(config)
        self.app = MaintenanceGate(Gateway())

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        # Restrict both the path and Host before even signed transfers reach
        # Gateway. Never trust proxy headers on this directly exposed socket.
        if not re.fullmatch(r"/mcp/profiles/[^/]+(?:/(?:upload|download)(?:/[^/]+)?)?/?", scope["path"]):
            return await JSONResponse({"error": "not_found"}, 404)(scope, receive, send)
        headers = scope.get("headers", [])
        hosts = [v.decode("latin-1") for k, v in headers if k.lower() == b"host"]
        if hosts != [self.authority]:
            return await JSONResponse({"error": "invalid_host"}, 403)(scope, receive, send)
        scope = dict(scope, headers=[(k, v) for k, v in headers if not (
            k.lower().startswith(b"x-forwarded-") or k.lower() == b"forwarded"
        )])
        await self.app(scope, receive, send)


class DirectListener:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.server = None
        self.task = None
        self.bound = None
        self.error = None

    def status(self, profile_id):
        config = get_settings().mcp_direct
        listening = bool(self.server and self.server.started and self.task and not self.task.done())
        return {
            **config.model_dump(),
            "status": "listening" if listening else "error" if self.error else "off",
            "error": self.error,
            "endpoint": f"http://{authority(self.bound)}/mcp/profiles/{profile_id}" if listening else None,
        }

    async def _stop(self):
        if self.server:
            self.server.should_exit = True
        if self.task:
            try:
                await asyncio.wait_for(asyncio.shield(self.task), timeout=6)
            except asyncio.TimeoutError:
                self.task.cancel()
            except Exception:
                # A crashed serving task must not prevent disabling it or
                # rebinding on the next configuration pass.
                pass
            await asyncio.gather(self.task, return_exceptions=True)
        self.server = self.task = self.bound = None

    async def apply(self, config=None):
        """Serialize Apply and file reloads. Fail closed on a bad new binding."""
        async with self.lock:
            if config is not None:
                patch_global_section("mcp_direct", config.model_dump())
                reload_settings()
            else:
                config = get_settings().mcp_direct
            if self.bound == config and self.task and not self.task.done():
                return
            await self._stop()
            self.error = None
            if not config.enabled:
                return
            sock = None
            try:
                sock = socket.socket(socket.AF_INET6 if ":" in config.host else socket.AF_INET, socket.SOCK_STREAM)
                if os.name == "nt":
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                # Bind here so EADDRINUSE is a recoverable settings error,
                # not uvicorn's SystemExit. Never silently pick another port.
                sock.bind((config.host, config.port))
                sock.listen(128)
                sock.setblocking(False)
                import uvicorn

                class Server(uvicorn.Server):
                    @contextmanager
                    def capture_signals(self):
                        yield

                    def install_signal_handlers(self):
                        pass

                self.server = Server(uvicorn.Config(
                    DirectApp(config), lifespan="off", proxy_headers=False,
                    log_config=None, access_log=False, timeout_graceful_shutdown=2,
                ))
                self.task = asyncio.create_task(self.server.serve(sockets=[sock]))
                for _ in range(200):
                    if self.server.started:
                        self.bound = config.model_copy()
                        return
                    if self.task.done():
                        await self.task
                        raise RuntimeError("MCP listener stopped during startup.")
                    await asyncio.sleep(0.01)
                raise RuntimeError("MCP listener did not start in time.")
            except Exception as exc:
                self.error = {
                    errno.EADDRINUSE: "Port already in use. Choose another port.",
                    errno.EADDRNOTAVAIL: "Address unavailable on this server.",
                    errno.EACCES: "Permission denied for this address or port.",
                    errno.EAFNOSUPPORT: "This address family is unavailable on this server.",
                }.get(getattr(exc, "errno", None), "Could not start the MCP listener.")
                await self._stop()
                if sock is not None:
                    sock.close()

    @asynccontextmanager
    async def lifespan(self):
        await self.apply()

        async def watch():
            while True:
                await asyncio.sleep(2)
                # Settings are reloaded by the ordinary config watcher. Retry
                # failed bindings as interfaces (especially VPNs) come online.
                await self.apply()

        watcher = asyncio.create_task(watch())
        try:
            yield
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            async with self.lock:
                await self._stop()


listener = DirectListener()

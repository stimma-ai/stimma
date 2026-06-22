"""
JSON-RPC provider for external tool integration.

Implements the Stimma Tools Protocol (STP) for connecting to external
tool providers via WebSocket or stdio transport.

See https://github.com/stimma-ai/stimma-tools-protocol for the full protocol specification.
"""

import asyncio
import json
import os
import re
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import aiohttp

from core.logging import get_logger
from tasks.schemas import validate_tool_schema, validate_tool_schema_multi, is_known_task_type, normalize_task_type
from .base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)

log = get_logger(__name__)


# Asset IDs are opaque tokens from a fixed charset (STP §Asset Management). A receiver must
# reject anything that doesn't match before using it to build a filesystem path or URL.
_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9]{1,12}$")


def _valid_asset_id(asset_id: str) -> bool:
    return isinstance(asset_id, str) and bool(_ASSET_ID_RE.match(asset_id))


# Media inputs are identified by their declared `x-control`, never by field name (STP keeps
# field names conventional, not load-bearing). These controls carry uploadable file paths.
_ARRAY_MEDIA_CONTROLS = {"image_picker", "video_picker", "video_frame_picker"}
_SINGLE_MEDIA_CONTROLS = {"mask_editor"}


def _media_input_keys(parameter_schema: Optional[Dict[str, Any]]) -> tuple[set, set]:
    """Return (single_file_keys, array_file_keys) derived from each property's `x-control`."""
    single: set = set()
    array: set = set()
    props = (parameter_schema or {}).get("properties", {})
    if isinstance(props, dict):
        for name, prop in props.items():
            control = prop.get("x-control") if isinstance(prop, dict) else None
            if control in _ARRAY_MEDIA_CONTROLS:
                array.add(name)
            elif control in _SINGLE_MEDIA_CONTROLS:
                single.add(name)
    return single, array


def _strip_undeclared_parameters(
    parameters: Dict[str, Any],
    parameter_schema: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return only parameters declared by the tool's STP parameter schema.

    Stimma jobs carry local metadata such as prompt_metadata, media IDs, and
    preprocessing hints for UI restore and lineage. Those values are not part of
    the remote tool contract and strict STP providers reject them.
    """
    props = (parameter_schema or {}).get("properties")
    if not isinstance(props, dict):
        return dict(parameters)
    declared = set(props.keys())
    return {k: v for k, v in parameters.items() if k in declared}


# --- Configuration ---


@dataclass
class StdioProviderConfig:
    """Configuration for a stdio-based provider."""

    id: str
    command: str
    args: List[str] = field(default_factory=list)
    working_dir: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    name: Optional[str] = None  # Human-readable display name (defaults to id)


@dataclass
class WebSocketProviderConfig:
    """Configuration for a WebSocket-based provider."""

    id: str
    url: str
    auth_token: Optional[str] = None
    reconnect_delay: float = 5.0  # Base delay in seconds
    name: Optional[str] = None  # Human-readable display name (defaults to id)


# --- Transport Layer ---


class Transport(ABC):
    """Abstract transport layer for JSON-RPC communication."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the transport connection."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the transport connection."""
        pass

    @abstractmethod
    async def send(self, message: dict) -> None:
        """Send a JSON-RPC message."""
        pass

    @abstractmethod
    async def receive(self) -> Optional[dict]:
        """Receive a JSON-RPC message. Returns None if connection closed."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        pass


class WebSocketTransport(Transport):
    """WebSocket transport implementation."""

    def __init__(self, config: WebSocketProviderConfig):
        self.config = config
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._origin: str = ""

    async def connect(self) -> None:
        """Connect to the WebSocket endpoint."""
        headers = {}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        self._session = aiohttp.ClientSession()

        try:
            self._ws = await self._session.ws_connect(
                self.config.url,
                headers=headers,
                heartbeat=30.0,
            )
            # Extract origin for asset URLs
            parsed = urlparse(self.config.url)
            scheme = "https" if parsed.scheme == "wss" else "http"
            self._origin = f"{scheme}://{parsed.netloc}"
            log.info("websocket connected", url=self.config.url)
        except Exception as e:
            if self._session:
                await self._session.close()
                self._session = None
            raise ConnectionError(f"Failed to connect to {self.config.url}: {e}")

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._session:
            await self._session.close()
            self._session = None
        log.info("websocket disconnected")

    async def send(self, message: dict) -> None:
        """Send a JSON-RPC message."""
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        log.info(
            "ws client send",
            method=message.get("method"),
            id=message.get("id"),
        )
        await self._ws.send_json(message)

    async def receive(self) -> Optional[dict]:
        """Receive a JSON-RPC message."""
        if not self._ws:
            return None

        try:
            msg = await self._ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                # Log both requests (with method) and responses (with result/error)
                if data.get("method"):
                    log.info(
                        "ws client recv",
                        method=data.get("method"),
                        id=data.get("id"),
                    )
                elif "result" in data or "error" in data:
                    log.debug(
                        "ws client recv response",
                        id=data.get("id"),
                        has_result="result" in data,
                        has_error="error" in data,
                    )
                return data
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                log.warning("ws client connection closed/error", msg_type=str(msg.type))
                return None
        except Exception as e:
            log.warning("websocket receive error", error=str(e))
            return None

        return None

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def origin(self) -> str:
        """Get the origin URL for asset requests."""
        return self._origin

    async def http_put(self, path: str, data: bytes, content_type: str) -> None:
        """HTTP PUT request for asset upload."""
        if not self._session:
            raise RuntimeError("Session not connected")

        url = f"{self._origin}{path}"
        size_mb = len(data) / (1024 * 1024)
        headers = {"Content-Type": content_type}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        try:
            async with self._session.put(url, data=data, headers=headers) as resp:
                if resp.status == 413:
                    raise RuntimeError(
                        f"File too large ({size_mb:.0f} MB) — rejected by provider (HTTP 413). "
                        f"Provider's HTTP server needs a higher body size limit."
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(f"Asset upload failed: HTTP {resp.status} — {body[:200]}")
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            raise RuntimeError(
                f"Connection lost during upload ({size_mb:.0f} MB to {url}). "
                f"Provider likely rejected the request due to body size limit. "
                f"Error: {e}"
            )

    async def http_put_absolute(self, url: str, data: bytes, content_type: str) -> None:
        """HTTP PUT to an arbitrary absolute URL with no origin or auth header.

        Used for upload paths where the provider returns a pre-signed URL on
        tools.upload (e.g. cloud LoRA uploads going directly to R2 via Sigv4
        signed URL). The URL itself is the auth — Authorization header would
        actually conflict with the signature.

        Override the session's default 5-minute total timeout: LoRA safetensors
        run 100 MB–2 GB and on residential upstream a single PUT can legitimately
        take 20+ minutes. We keep a sock_read timeout so a stalled connection
        still surfaces, just not a total budget.
        """
        if not self._session:
            raise RuntimeError("Session not connected")

        size_mb = len(data) / (1024 * 1024)
        headers = {"Content-Type": content_type}
        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)

        try:
            async with self._session.put(url, data=data, headers=headers, timeout=timeout) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Direct upload failed: HTTP {resp.status} — {body[:200]}"
                    )
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            raise RuntimeError(
                f"Connection lost during direct upload ({size_mb:.0f} MB). Error: {e}"
            )

    async def http_get(self, path: str) -> bytes:
        """HTTP GET request for asset download."""
        if not self._session:
            raise RuntimeError("Session not connected")

        url = f"{self._origin}{path}"
        headers = {}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        async with self._session.get(url, headers=headers) as resp:
            if resp.status >= 400:
                raise KeyError(f"Asset not found: {path}")
            return await resp.read()

    async def http_delete(self, path: str) -> None:
        """HTTP DELETE request for asset deletion."""
        if not self._session:
            raise RuntimeError("Session not connected")

        url = f"{self._origin}{path}"
        headers = {}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        async with self._session.delete(url, headers=headers) as resp:
            pass  # Ignore response


# Max message size for JSON-RPC messages (16 MiB)
# Large tool schemas (e.g., 26 tools × 1500 LoRAs × 60 chars each ≈ 5-6 MB)
JSONRPC_MESSAGE_LIMIT = 16 * 1024 * 1024  # 16 MiB


class StdioTransport(Transport):
    """Stdio transport for subprocess-based providers."""

    # Maximum number of stderr lines to keep in memory (fallback if no external buffer)
    STDERR_BUFFER_SIZE = 500

    def __init__(self, config: StdioProviderConfig):
        self.config = config
        self._process: Optional[asyncio.subprocess.Process] = None
        self._asset_dir: Optional[Path] = None
        self._read_buffer: str = ""
        # Ring buffer for stderr output (fallback - manager provides shared buffer)
        self._stderr_lines: deque[str] = deque(maxlen=self.STDERR_BUFFER_SIZE)
        self._stderr_total_lines: int = 0
        # Callback for adding stderr lines to external buffer (set by manager)
        self._add_stderr_line_callback: Optional[Callable[[str], None]] = None

    async def connect(self) -> None:
        """Spawn the provider subprocess."""
        # Create asset directory
        self._asset_dir = Path(tempfile.mkdtemp(prefix="stimma-assets-"))

        # Build environment
        env = os.environ.copy()
        env["ASSET_PATH"] = str(self._asset_dir)
        env.update(self.config.env)

        # Spawn process
        cmd = [self.config.command] + self.config.args
        cwd = self.config.working_dir

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                limit=JSONRPC_MESSAGE_LIMIT,  # Allow large JSON-RPC messages
            )
            log.info(
                "stdio process started",
                command=self.config.command,
                pid=self._process.pid,
            )

            # Start stderr reader task
            asyncio.create_task(self._read_stderr())

        except Exception as e:
            if self._asset_dir and self._asset_dir.exists():
                shutil.rmtree(self._asset_dir)
            raise ConnectionError(f"Failed to start provider process: {e}")

    async def _read_stderr(self) -> None:
        """Read stderr, log it, and store in ring buffer."""
        if not self._process or not self._process.stderr:
            return

        while True:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text:
                    # Use external callback if set, otherwise use internal buffer
                    if self._add_stderr_line_callback:
                        self._add_stderr_line_callback(text)
                    else:
                        self._stderr_lines.append(text)
                        self._stderr_total_lines += 1
                    log.info(
                        "provider stderr",
                        provider=self.config.id,
                        message=text,
                    )
            except Exception:
                break

    def get_stderr_logs(self) -> Tuple[List[str], int]:
        """Get stderr lines from the ring buffer.

        Returns:
            Tuple of (lines, total_lines_since_startup)
        """
        return list(self._stderr_lines), self._stderr_total_lines

    async def disconnect(self) -> None:
        """Terminate the subprocess and clean up."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            except Exception:
                pass
            self._process = None

        # Clean up asset directory
        if self._asset_dir and self._asset_dir.exists():
            shutil.rmtree(self._asset_dir)
            self._asset_dir = None

        log.info("stdio process terminated", provider=self.config.id)

    async def send(self, message: dict) -> None:
        """Send a JSON-RPC message via stdin."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Process not running")

        line = json.dumps(message) + "\n"
        log.info(
            "provider send",
            provider=self.config.id,
            method=message.get("method"),
            id=message.get("id"),
        )
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

    async def receive(self) -> Optional[dict]:
        """Receive a JSON-RPC message from stdout.

        Skips non-JSON lines (logging them as warnings) and keeps
        reading until we get a valid JSON-RPC message or EOF.
        """
        if not self._process or not self._process.stdout:
            return None

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    return None

                text = line.decode().strip()
                if not text:
                    continue

                # Try to parse as JSON
                try:
                    message = json.loads(text)
                    # Validate it looks like JSON-RPC
                    if not isinstance(message, dict) or "jsonrpc" not in message:
                        log.warning(
                            "provider stdout junk (not JSON-RPC)",
                            provider=self.config.id,
                            line=text[:200],
                        )
                        continue

                    # Log both requests (with method) and responses (with result/error)
                    if message.get("method"):
                        log.info(
                            "provider recv",
                            provider=self.config.id,
                            method=message.get("method"),
                            id=message.get("id"),
                        )
                    elif "result" in message or "error" in message:
                        log.debug(
                            "provider recv response",
                            provider=self.config.id,
                            id=message.get("id"),
                            has_result="result" in message,
                            has_error="error" in message,
                        )
                    return message

                except json.JSONDecodeError:
                    log.warning(
                        "provider stdout junk (invalid JSON)",
                        provider=self.config.id,
                        line=text[:200],
                    )
                    continue

            except Exception as e:
                log.warning(
                    "provider receive error",
                    provider=self.config.id,
                    error=str(e),
                )
                return None

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def asset_path(self) -> Path:
        """Get the asset directory path."""
        if not self._asset_dir:
            raise RuntimeError("Not connected")
        return self._asset_dir


# --- JSON-RPC Provider ---


class JsonRpcProvider(ToolProvider):
    """
    Provider that communicates via JSON-RPC protocol.

    Supports both WebSocket and stdio transports.
    """

    def __init__(
        self,
        config: Union[StdioProviderConfig, WebSocketProviderConfig],
    ):
        self._config = config
        self._transport: Optional[Transport] = None
        self._status = ProviderStatus.DISCONNECTED
        self._session_id: Optional[str] = None
        self._asset_base_url: Optional[str] = None  # Provider's asset endpoint URL
        self._tools: List[ToolDescriptor] = []
        self._max_concurrent: int = 1
        self._supports_cancel: bool = False

        # Request tracking
        self._request_id: int = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}

        # Queue status
        self._queue_status: Dict[str, int] = {"queued": 0, "running": 0, "capacity": 1}

        # Execution tracking
        self._pending_executions: Dict[str, asyncio.Queue] = {}

        # Message handler task
        self._message_handler_task: Optional[asyncio.Task] = None

        # Disconnect callback (set by manager for auto-restart)
        self._on_disconnect: Optional[Callable[[], None]] = None

        # Tools changed callback (set by manager to update registry + broadcast)
        self._on_tools_changed: Optional[Callable] = None

        # Error tracking
        self._error_message: Optional[str] = None

        # Token refresh callback for WebSocket providers
        # Called before HTTP operations to refresh auth token if expired
        self._token_refresh_callback: Optional[Callable[[dict], Any]] = None

        # Provider identity from handshake (provider.register)
        self._reported_name: Optional[str] = None
        self._server: Optional[str] = None          # software identifier, e.g. "ComfyUI-Stimma/1.2.3"
        self._stp_version: Optional[str] = None      # protocol version the provider speaks
        self._capabilities: dict = {}

    @property
    def provider_id(self) -> str:
        return self._config.id

    @property
    def provider_name(self) -> str:
        return self._config.name or self._config.id

    @property
    def provider_type(self) -> str:
        return "jsonrpc"

    @property
    def reported_name(self) -> Optional[str]:
        """Provider name reported during STP handshake."""
        return self._reported_name

    @property
    def reported_version(self) -> Optional[str]:
        """Provider software identifier (`server`) reported during STP handshake."""
        return self._server

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def queue_status(self) -> Dict[str, int]:
        """Current queue status from provider."""
        return self._queue_status.copy()

    def get_stderr_logs(self) -> tuple[list[str], int]:
        """Get stderr logs from stdio transport.

        Returns:
            Tuple of (lines, total_lines_since_startup)
            Returns ([], 0) if not a stdio transport or not connected
        """
        if isinstance(self._transport, StdioTransport):
            return self._transport.get_stderr_logs()
        return [], 0

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self, method: str, params: Optional[dict] = None, timeout: float = 30.0
    ) -> Any:
        """Send a JSON-RPC request and wait for response."""
        if not self._transport or not self._transport.is_connected:
            raise RuntimeError("Not connected")

        request_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            await self._transport.send(request)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self._pending_requests.pop(request_id, None)

    async def _send_notification(self, method: str, params: Optional[dict] = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._transport or not self._transport.is_connected:
            raise RuntimeError("Not connected")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        await self._transport.send(notification)

    async def _ensure_fresh_token(self) -> None:
        """Refresh auth token if callback is set (for WebSocket providers).

        Called before HTTP operations (asset upload/download/delete) to ensure
        the token hasn't expired. Firebase tokens expire after 1 hour but the
        WebSocket connection may stay alive longer.
        """
        if not self._token_refresh_callback:
            return

        if not isinstance(self._config, WebSocketProviderConfig):
            return

        try:
            # The callback updates config['auth_token'] in place
            # We pass a dict view of the config so it can be mutated
            config_dict = {
                'auth_token': self._config.auth_token,
            }
            await self._token_refresh_callback(config_dict)

            # Update our config if token changed
            new_token = config_dict.get('auth_token')
            if new_token and new_token != self._config.auth_token:
                self._config.auth_token = new_token
                log.debug("refreshed auth token for http operations", provider=self.provider_id)
        except Exception as e:
            log.warning("failed to refresh auth token", provider=self.provider_id, error=str(e))
            # Continue with existing token - it might still be valid

    async def _handle_messages(self) -> None:
        """Background task to handle incoming messages."""
        while self._transport and self._transport.is_connected:
            try:
                message = await self._transport.receive()
                if message is None:
                    log.warning("connection closed by provider")
                    self._status = ProviderStatus.DISCONNECTED
                    # Fail any pending executions so callers don't hang
                    await self._fail_pending_executions("Provider connection lost")
                    # Notify manager for immediate restart
                    if self._on_disconnect:
                        self._on_disconnect()
                    break

                await self._process_message(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("error handling message", error=str(e))

    async def _process_message(self, message: dict) -> None:
        """Process an incoming JSON-RPC message."""
        # Check if it's a response (has id)
        if "id" in message and message["id"] is not None:
            request_id = message["id"]
            if request_id in self._pending_requests:
                future = self._pending_requests[request_id]
                if "error" in message:
                    future.set_exception(
                        RuntimeError(message["error"].get("message", "Unknown error"))
                    )
                else:
                    future.set_result(message.get("result"))
            else:
                log.warning(
                    "ignoring message with unknown id",
                    id=request_id,
                    method=message.get("method"),
                    provider=self.provider_id,
                )
            return

        # It's a notification
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "queue.status":
            def _count(key, default):
                val = params.get(key, default)
                return val if isinstance(val, int) and not isinstance(val, bool) and val >= 0 else None
            counts = {"queued": _count("queued", 0), "running": _count("running", 0), "capacity": _count("capacity", 1)}
            if None in counts.values():
                log.warning("ignoring malformed queue.status", params=params)
            else:
                self._queue_status = counts
                log.debug("queue status update", **self._queue_status)

        elif method == "tools.progress":
            request_id = params.get("request_id")
            if request_id in self._pending_executions:
                progress = ExecutionProgress(
                    progress=params.get("progress", 0.0),
                    stage="executing",
                )
                await self._pending_executions[request_id].put(("progress", progress))
            else:
                log.debug(
                    "dropping tools.progress for unknown request",
                    request_id=request_id,
                    provider=self.provider_id,
                )

        elif method == "tools.result":
            request_id = params.get("request_id")
            if request_id in self._pending_executions:
                await self._pending_executions[request_id].put(("result", params))
            else:
                log.warning(
                    "dropping tools.result for unknown request",
                    request_id=request_id,
                    success=params.get("success"),
                    provider=self.provider_id,
                )

        elif method == "tools.changed":
            log.info("provider tools changed, refreshing", provider=self.provider_id)
            # Run in a detached task — refresh_tools() sends a tools.refresh RPC
            # and awaits the response, which can only be received by this same
            # message handler loop. Running inline would deadlock.
            asyncio.create_task(self._handle_tools_changed())

        else:
            log.debug("unknown notification", method=method)

    async def _handle_tools_changed(self) -> None:
        """Handle tools.changed notification in a detached task."""
        try:
            await self.refresh_tools()
            if self._on_tools_changed:
                await self._on_tools_changed()
        except Exception as e:
            log.error("failed to refresh tools after tools.changed", error=str(e))

    # --- ToolProvider Implementation ---

    async def connect(self) -> None:
        """Connect to the provider."""
        # Skip if already connected (registry.register() may call this again)
        if self._status == ProviderStatus.CONNECTED:
            log.debug("provider already connected, skipping", provider=self.provider_id)
            return

        self._status = ProviderStatus.CONNECTING

        # Create appropriate transport
        if isinstance(self._config, WebSocketProviderConfig):
            self._transport = WebSocketTransport(self._config)
        else:
            self._transport = StdioTransport(self._config)
            # Pass stderr callback if set by manager
            if hasattr(self, '_add_stderr_line') and self._add_stderr_line:
                self._transport._add_stderr_line_callback = self._add_stderr_line

        try:
            await self._transport.connect()

            # Wait for provider to register (it sends first message)
            # NOTE: Do NOT start message handler until after registration handshake
            # to avoid race condition where handler consumes the registration message
            message = await self._transport.receive()
            if not message or message.get("method") != "provider.register":
                raise ConnectionError("Expected provider.register message")

            params = message.get("params", {})
            self._max_concurrent = params.get("max_concurrent", 1)
            capabilities = params.get("capabilities") or {}
            self._capabilities = capabilities
            self._supports_cancel = bool(capabilities.get("cancel", False))
            self._reported_name = params.get("provider_name") or params.get("provider_id")
            self._stp_version = params.get("stp_version")
            self._server = params.get("server")

            # For WebSocket transport, parse asset_endpoint from provider
            # Provider hosts assets and tells us where to upload/download
            if isinstance(self._transport, WebSocketTransport):
                asset_endpoint = params.get("asset_endpoint")
                if asset_endpoint:
                    if asset_endpoint.startswith("http://") or asset_endpoint.startswith("https://"):
                        # Absolute URL - use as-is
                        self._asset_base_url = asset_endpoint.rstrip("/")
                    else:
                        # Relative path - construct URL from WebSocket origin
                        self._asset_base_url = f"{self._transport.origin}{asset_endpoint.rstrip('/')}"
                    log.info(f"Provider asset URL: {self._asset_base_url}")

            # Send registration response
            response = {
                "jsonrpc": "2.0",
                "result": {
                    "session_id": str(uuid.uuid4()),
                    "stp_version": "1.0",
                    "host_version": "1.0.0",
                    "capabilities": {},
                },
                "id": message.get("id"),
            }

            await self._transport.send(response)

            # Start message handler AFTER registration handshake
            self._message_handler_task = asyncio.create_task(self._handle_messages())

            # Request tool list
            result = await self._send_request("tools.list")
            raw_tools = result.get("tools", [])

            # Detailed logging to debug empty tool lists
            if isinstance(result, dict):
                result_keys = list(result.keys())
                if isinstance(raw_tools, list):
                    tool_count = len(raw_tools)
                    # Log first tool's id if available for debugging
                    first_tool_id = raw_tools[0].get("id") if raw_tools else None
                else:
                    tool_count = f"not a list: {type(raw_tools).__name__}"
                    first_tool_id = None
            else:
                result_keys = f"not a dict: {type(result).__name__}"
                tool_count = "N/A"
                first_tool_id = None

            log.info(
                "tools.list response",
                provider=self.provider_id,
                result_keys=result_keys,
                raw_tool_count=tool_count,
                first_tool_id=first_tool_id,
            )

            # If we got 0 tools, log guidance for debugging
            if isinstance(raw_tools, list) and len(raw_tools) == 0:
                log.warning(
                    "tools.list returned 0 tools - check provider logs for details",
                    provider=self.provider_id,
                    hint="Provider likely failed to connect to ComfyUI or no tools met requirements. "
                         "Check the provider's terminal for 'object_info' fetch errors or "
                         "'Tool X not available' messages.",
                )

            self._tools = self._parse_and_validate_tools(raw_tools)

            self._status = ProviderStatus.CONNECTED
            self._error_message = None  # Clear any previous error
            log.info(
                "provider connected",
                provider=self.provider_id,
                tools=len(self._tools),
                max_concurrent=self._max_concurrent,
            )

        except Exception as e:
            self._status = ProviderStatus.ERROR
            self._error_message = str(e)  # Capture error message
            if self._transport:
                await self._transport.disconnect()
                self._transport = None
            raise ConnectionError(f"Failed to connect: {e}")

    async def _fail_pending_executions(self, reason: str) -> None:
        """Fail all pending executions so waiting callers don't hang."""
        if not self._pending_executions:
            return
        log.warning(
            "failing pending executions",
            count=len(self._pending_executions),
            reason=reason,
            provider=self.provider_id,
        )
        for request_id, queue in self._pending_executions.items():
            await queue.put(("result", {
                "request_id": request_id,
                "success": False,
                "error": {
                    "code": "PROVIDER_DISCONNECTED",
                    "message": reason,
                },
            }))

    async def disconnect(self) -> None:
        """Disconnect from the provider."""
        # Cancel message handler
        if self._message_handler_task:
            self._message_handler_task.cancel()
            try:
                await self._message_handler_task
            except asyncio.CancelledError:
                pass
            self._message_handler_task = None

        # Fail any pending executions so callers don't hang forever
        await self._fail_pending_executions("Provider disconnected during execution")

        # Send disconnect notification
        if self._transport and self._transport.is_connected:
            try:
                await self._send_notification(
                    "provider.disconnect", {"reason": "shutdown"}
                )
            except Exception:
                pass

        # Close transport
        if self._transport:
            await self._transport.disconnect()
            self._transport = None

        self._status = ProviderStatus.DISCONNECTED
        self._tools = []
        log.info("provider disconnected", provider=self.provider_id)

    def _parse_and_validate_tools(self, tools_data: List[Dict[str, Any]]) -> List[ToolDescriptor]:
        """
        Parse tool data from provider and validate schemas.

        Supports both `task_type` (string, legacy) and `task_types` (array, new).
        - task_types array takes precedence if provided
        - Unknown task types in the array are filtered out with a warning
        - Tools must validate against ALL declared task types
        - Tools with invalid schemas are rejected entirely
        """
        validated_tools = []

        for tool_data in tools_data:
            tool_id = tool_data.get("id", "unknown")
            parameter_schema = tool_data.get("parameter_schema", {})
            output_schema = tool_data.get("output_schema", {})

            # Parse task types - prefer task_types array, fallback to task_type string
            raw_task_types = tool_data.get("task_types", [])
            legacy_task_type = tool_data.get("task_type")

            # Build the list of task types
            if raw_task_types and isinstance(raw_task_types, list):
                # New format: task_types array
                task_types = []
                for tt in raw_task_types:
                    if not isinstance(tt, str):
                        continue
                    if is_known_task_type(tt):
                        task_types.append(tt)
                    else:
                        log.warning(
                            "unknown task_type in array, skipping",
                            provider=self.provider_id,
                            tool=tool_id,
                            task_type=tt,
                        )
            elif legacy_task_type and isinstance(legacy_task_type, str):
                # Legacy format: single task_type string
                if is_known_task_type(legacy_task_type):
                    task_types = [legacy_task_type]
                else:
                    log.warning(
                        "tool has unknown task_type, treating as utility",
                        provider=self.provider_id,
                        tool=tool_id,
                        task_type=legacy_task_type,
                    )
                    task_types = []
            else:
                # No task type declared - utility tool
                task_types = []

            # Normalize task types (e.g., "image-edit" → "image-to-image")
            task_types = [normalize_task_type(tt) for tt in task_types]

            # Validate schema against all declared task types
            if task_types:
                errors = validate_tool_schema_multi(task_types, parameter_schema, output_schema)
                if errors:
                    log.error(
                        "tool rejected - schema mismatch",
                        provider=self.provider_id,
                        tool=tool_id,
                        task_types=task_types,
                        errors=errors,
                    )
                    continue  # Skip this tool entirely

            # Primary task_type is the first in the list (for backward compat)
            primary_task_type = task_types[0] if task_types else None

            # Layout: prefer top-level, fall back to metadata.layout
            metadata = tool_data.get("metadata", {})
            layout = tool_data.get("layout") or metadata.get("layout")

            validated_tools.append(
                ToolDescriptor(
                    id=tool_id,
                    name=tool_data.get("name", tool_id),
                    subtitle=tool_data.get("subtitle") or metadata.get("description"),
                    description=tool_data.get("description") or metadata.get("description"),
                    task_type=primary_task_type,  # None for utilities
                    task_types=task_types,  # All task types (empty for utilities)
                    parameter_schema=parameter_schema,
                    output_schema=output_schema,
                    layout=layout,
                    metadata=metadata,
                    raw_registration=tool_data,  # Preserve raw JSON for debugging
                )
            )

        rejected_count = len(tools_data) - len(validated_tools)
        if rejected_count > 0:
            log.warning(
                "tools validation summary",
                provider=self.provider_id,
                received=len(tools_data),
                validated=len(validated_tools),
                rejected=rejected_count,
            )
        return validated_tools

    async def list_tools(self) -> List[ToolDescriptor]:
        """List available tools."""
        return self._tools.copy()

    async def refresh_tools(self) -> List[ToolDescriptor]:
        """
        Refresh tools by sending tools.refresh to the remote provider.

        This re-queries the provider for its tool list, which may include
        updated LoRA lists or other dynamic metadata.
        """
        if self._status != ProviderStatus.CONNECTED:
            raise RuntimeError("Provider not connected")

        try:
            result = await self._send_request("tools.refresh")
            self._tools = self._parse_and_validate_tools(result.get("tools", []))
            log.info(
                "tools refreshed",
                provider=self.provider_id,
                tools=len(self._tools),
            )
            return self._tools.copy()
        except Exception as e:
            log.error("failed to refresh tools", provider=self.provider_id, error=str(e))
            raise

    async def upload_prepare(
        self,
        tool_id: str,
        parameter: str,
        filename: str,
        file_size: int,
    ) -> Dict[str, Any]:
        """
        First half of a split upload: ask the provider to accept an upload of
        this size and return where to PUT the bytes.

        Returns the raw response from `tools.upload`. For cloud providers this
        includes `upload_url` (a pre-signed URL the frontend can PUT to directly);
        for desktop providers the bytes go to `{asset_endpoint}/{asset_id}`.
        """
        if self._status != ProviderStatus.CONNECTED:
            raise RuntimeError("Provider not connected")

        upload_id = f"upload-{uuid.uuid4().hex[:12]}"
        log.info(
            "upload_prepare: sending tools.upload",
            provider=self.provider_id,
            upload_id=upload_id,
            tool_id=tool_id,
            filename=filename,
            size_mb=f"{file_size / (1024 * 1024):.1f}",
        )
        init_result = await self._send_request("tools.upload", {
            "upload_id": upload_id,
            "tool_id": tool_id,
            "parameter": parameter,
            "filename": filename,
            "file_size": file_size,
        }, timeout=30.0)

        if not init_result.get("accepted"):
            error = init_result.get("error", "Upload rejected by provider")
            log.error("upload_prepare: rejected by provider", provider=self.provider_id, error=error)
            raise RuntimeError(f"Upload rejected: {error}")

        asset_id = init_result["asset_id"]
        upload_url = init_result.get("upload_url")
        upload_method = init_result.get("upload_method") or "PUT"

        # If the provider didn't give us an upload_url, build the legacy
        # {asset_endpoint}/{asset_id} URL so the caller has something concrete
        # to PUT to either way.
        legacy_url: Optional[str] = None
        if not upload_url and isinstance(self._transport, WebSocketTransport):
            if self._asset_base_url:
                legacy_url = f"{self._asset_base_url}/{asset_id}"

        return {
            "upload_id": upload_id,
            "asset_id": asset_id,
            "upload_url": upload_url or legacy_url,
            "upload_method": upload_method,
            "is_presigned": bool(upload_url),  # frontend can decide whether to send Authorization
        }

    async def upload_finalize(self, upload_id: str) -> Dict[str, Any]:
        """
        Second half of a split upload: tell the provider the bytes are in
        place. Provider verifies (e.g. sha256 read from R2), dedups, inserts
        ownership rows, and returns the installed path + opaque id.
        """
        if self._status != ProviderStatus.CONNECTED:
            raise RuntimeError("Provider not connected")

        log.info("upload_finalize: sending tools.upload_complete", provider=self.provider_id, upload_id=upload_id)
        complete_result = await self._send_request("tools.upload_complete", {
            "upload_id": upload_id,
        }, timeout=300.0)

        if not complete_result.get("success"):
            error = complete_result.get("error", "Upload completion failed")
            log.error("upload_finalize: failed", provider=self.provider_id, error=error)
            raise RuntimeError(f"Upload completion failed: {error}")

        # Refresh tools after a successful install so enum lists pick up the new file.
        try:
            await self.refresh_tools()
        except Exception as e:
            log.warning(f"Failed to refresh tools after upload: {e}")

        return {
            "success": True,
            "installed_path": complete_result.get("installed_path"),
            "upload_id": upload_id,
            "lora_id": complete_result.get("lora_id"),
        }

    async def upload_to_tool(
        self,
        tool_id: str,
        parameter: str,
        filename: str,
        file_data: bytes,
    ) -> Dict[str, Any]:
        """
        Single-call convenience wrapper that does prepare → PUT-through-backend → finalize.
        Kept for the legacy /upload route and code paths where the bytes are
        already in process. New paths should call upload_prepare directly and
        have the frontend PUT to the returned URL itself — that avoids
        proxying multi-GB files through this process.
        """
        prep = await self.upload_prepare(tool_id, parameter, filename, len(file_data))
        upload_id = prep["upload_id"]
        upload_url = prep["upload_url"]
        is_presigned = prep["is_presigned"]
        size_mb = len(file_data) / (1024 * 1024)

        if isinstance(self._transport, WebSocketTransport):
            await self._ensure_fresh_token()
            if is_presigned and upload_url:
                log.info("upload (wrap): PUT to provider-supplied URL", size_mb=f"{size_mb:.1f}")
                await self._transport.http_put_absolute(
                    upload_url, file_data, "application/octet-stream"
                )
            elif upload_url:
                asset_path = upload_url.replace(self._transport.origin, "")
                log.info("upload (wrap): PUT to asset endpoint", size_mb=f"{size_mb:.1f}")
                await self._transport.http_put(asset_path, file_data, "application/octet-stream")
            else:
                raise RuntimeError("No upload destination available")
        elif isinstance(self._transport, StdioTransport):
            asset_path_fs = self._transport.asset_path / prep["asset_id"]
            log.info("upload (wrap): writing to filesystem", path=str(asset_path_fs), size_mb=f"{size_mb:.1f}")
            asset_path_fs.write_bytes(file_data)
        else:
            raise RuntimeError("No transport available")

        return await self.upload_finalize(upload_id)

    async def execute(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[ExecutionProgress], None]] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[Union[ExecutionProgress, ExecutionResult]]:
        """Execute a tool."""
        if self._status != ProviderStatus.CONNECTED:
            raise RuntimeError("Provider not connected")

        # Use provided request_id or generate one
        if request_id is None:
            request_id = f"exec-{uuid.uuid4().hex[:8]}"

        # Create queue for results
        result_queue: asyncio.Queue = asyncio.Queue()
        self._pending_executions[request_id] = result_queue

        try:
            # Upload any input files as assets to the provider
            tool = next((t for t in self._tools if t.id == tool_id), None)
            schema = tool.parameter_schema if tool else None
            outbound_parameters = _strip_undeclared_parameters(parameters, schema)
            dropped_keys = sorted(set(parameters) - set(outbound_parameters))
            if dropped_keys:
                log.debug(
                    "stripped undeclared STP parameters before execute",
                    tool_id=tool_id,
                    keys=dropped_keys,
                )
            processed_params = await self._upload_input_assets(outbound_parameters, schema)

            # Send execute request
            execute_params = {
                "request_id": request_id,
                "tool_id": tool_id,
                "parameters": processed_params,
            }

            result = await self._send_request("tools.execute", execute_params)

            if not result.get("accepted", False):
                raise RuntimeError(f"Job rejected: {result.get('reason', 'unknown')}")

            # Wait for progress/result notifications
            while True:
                msg_type, data = await result_queue.get()

                if msg_type == "progress":
                    if progress_callback:
                        progress_callback(data)
                    yield data

                elif msg_type == "result":
                    # Download output assets. The output envelope is {"assets": [{asset_id, type, role}, ...]};
                    # the primary asset becomes output_data, the rest additional_outputs.
                    output_data = None
                    additional_outputs: List[bytes] = []
                    output = data.get("output", {}) or {}
                    if data.get("success"):
                        assets = output.get("assets") or []
                        # Order primary first
                        assets = sorted(assets, key=lambda a: 0 if a.get("role") == "primary" else 1)
                        for a in assets:
                            aid = a.get("asset_id") if isinstance(a, dict) else None
                            if not aid:
                                continue
                            blob = await self.download_asset(aid)
                            if output_data is None:
                                output_data = blob
                            else:
                                additional_outputs.append(blob)

                    metadata = data.get("metadata", {})
                    # generation_time can be in metadata or output
                    generation_time = (
                        metadata.get("generation_time")
                        or output.get("generation_time")
                        or 0.0
                    )
                    yield ExecutionResult(
                        success=data.get("success", False),
                        output_data=output_data,
                        additional_outputs=additional_outputs,
                        generation_time=generation_time,
                        actual_seed=metadata.get("actual_seed") or output.get("actual_seed"),
                        metadata=metadata,
                        error=data.get("error", {}).get("message")
                        if not data.get("success")
                        else None,
                    )
                    break

        finally:
            self._pending_executions.pop(request_id, None)

    async def _upload_input_assets(
        self,
        parameters: Dict[str, Any],
        parameter_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process any file paths in parameters for the provider.

        For stdio transport: uses shared filesystem, just passes paths.
        For websocket transport: uploads files as assets and passes asset IDs.

        Media inputs are identified from the tool's `parameter_schema` via each property's
        `x-control` (not by field name). Returns a new dict with file paths replaced appropriately.
        """
        import mimetypes
        from pathlib import Path

        single_file_keys, array_file_keys = _media_input_keys(parameter_schema)

        processed = dict(parameters)

        async def upload_file(file_path: str) -> str:
            """Upload a file as an asset and return the asset ID."""
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                return file_path  # Return as-is if not a valid file

            if isinstance(self._transport, StdioTransport):
                return file_path  # Stdio uses shared filesystem

            # WebSocket: upload as asset and return asset ID
            data = path.read_bytes()
            mime_type, _ = mimetypes.guess_type(str(path))
            if not mime_type:
                mime_type = "application/octet-stream"
            asset_id = await self.upload_asset(data, mime_type)
            log.debug(f"Uploaded input asset: {path.name} ({len(data)} bytes) -> {asset_id}")
            return asset_id

        # Process single file keys
        for key in single_file_keys:
            if key in parameters and isinstance(parameters[key], str):
                processed[key] = await upload_file(parameters[key])

        # Process array file keys
        for key in array_file_keys:
            if key in parameters and isinstance(parameters[key], list):
                processed[key] = [await upload_file(p) for p in parameters[key] if isinstance(p, str)]

        return processed

    async def upload_asset(self, data: bytes, mime_type: str) -> str:
        """Upload an asset to the provider."""
        # Generate asset ID
        ext = mime_type.split("/")[-1]
        if ext == "jpeg":
            ext = "jpg"
        asset_id = f"{uuid.uuid4().hex}.{ext}"

        if isinstance(self._transport, WebSocketTransport):
            # Refresh token before HTTP operation to avoid 401
            await self._ensure_fresh_token()
            # Upload to provider via HTTP PUT (uses transport's authenticated session)
            if not self._asset_base_url:
                raise RuntimeError("Provider does not support assets (no asset_endpoint in registration)")
            asset_path = f"{self._asset_base_url}/{asset_id}".replace(self._transport.origin, "")
            await self._transport.http_put(asset_path, data, mime_type)
            log.debug(f"Uploaded asset to provider: {asset_id} ({len(data)} bytes)")
        elif isinstance(self._transport, StdioTransport):
            # Filesystem write
            asset_path = self._transport.asset_path / asset_id
            asset_path.write_bytes(data)
        else:
            raise RuntimeError("No transport available")

        return asset_id

    async def download_asset(self, asset_id: str) -> bytes:
        """Download an asset from the provider with retry logic."""
        if not _valid_asset_id(asset_id):
            raise ValueError(f"Malformed asset_id: {asset_id!r}")

        max_retries = 5
        retry_delay = 0.5  # seconds

        for attempt in range(max_retries):
            try:
                if isinstance(self._transport, WebSocketTransport):
                    # Refresh token before HTTP operation to avoid 401
                    await self._ensure_fresh_token()
                    # Download from provider via HTTP GET (uses transport's authenticated session)
                    if not self._asset_base_url:
                        raise RuntimeError("Provider does not support assets (no asset_endpoint in registration)")
                    asset_path = f"{self._asset_base_url}/{asset_id}".replace(self._transport.origin, "")
                    data = await self._transport.http_get(asset_path)
                    log.debug(f"Downloaded asset from provider: {asset_id} ({len(data)} bytes)")
                    return data
                elif isinstance(self._transport, StdioTransport):
                    # Filesystem read
                    asset_path = self._transport.asset_path / asset_id
                    if asset_path.exists():
                        return asset_path.read_bytes()
                else:
                    raise RuntimeError("No transport available")
            except RuntimeError:
                raise
            except Exception as e:
                log.warning(f"Error downloading asset (attempt {attempt + 1}): {e}")

            # Asset not found yet - wait and retry
            if attempt < max_retries - 1:
                log.warning(
                    f"Asset not found (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {retry_delay}s: {asset_id}"
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 3.0)  # Exponential backoff, max 3s

        # All retries exhausted
        raise KeyError(f"Asset not found after {max_retries} attempts: {asset_id}")

    async def delete_asset(self, asset_id: str) -> bool:
        """Delete an asset from the provider."""
        if not _valid_asset_id(asset_id):
            raise ValueError(f"Malformed asset_id: {asset_id!r}")
        try:
            if isinstance(self._transport, WebSocketTransport):
                # Refresh token before HTTP operation to avoid 401
                await self._ensure_fresh_token()
                # Delete from provider via HTTP DELETE (uses transport's authenticated session)
                if not self._asset_base_url:
                    return True  # No asset endpoint, nothing to delete
                asset_path = f"{self._asset_base_url}/{asset_id}".replace(self._transport.origin, "")
                await self._transport.http_delete(asset_path)
                return True
            elif isinstance(self._transport, StdioTransport):
                asset_path = self._transport.asset_path / asset_id
                if asset_path.exists():
                    asset_path.unlink()
            return True
        except Exception:
            return False

    async def cancel_execution(self, request_id: str) -> bool:
        """Cancel an in-progress execution."""
        if not self._supports_cancel:
            return False

        try:
            result = await self._send_request(
                "tools.cancel", {"request_id": request_id}
            )
            return result.get("cancelled", False)
        except Exception:
            return False

    async def ping(self) -> bool:
        """Health check - just verifies we're in connected state."""
        return self._status == ProviderStatus.CONNECTED


# --- Factory Functions ---


def create_provider_from_config(config: dict) -> JsonRpcProvider:
    """Create a JsonRpcProvider from a config dict."""
    provider_type = config.get("type")

    if provider_type == "stdio":
        stdio_config = StdioProviderConfig(
            id=config["id"],
            command=config["command"],
            args=config.get("args", []),
            working_dir=config.get("working_dir"),
            env=config.get("env", {}),
            name=config.get("name"),
        )
        return JsonRpcProvider(stdio_config)

    elif provider_type == "websocket":
        ws_config = WebSocketProviderConfig(
            id=config["id"],
            url=config["url"],
            auth_token=config.get("auth_token"),
            reconnect_delay=config.get("reconnect_delay", 5.0),
            name=config.get("name"),
        )
        return JsonRpcProvider(ws_config)

    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


async def create_providers_from_config(configs: List[dict]) -> List[JsonRpcProvider]:
    """Create and connect providers from config list."""
    providers = []

    for config in configs:
        try:
            provider = create_provider_from_config(config)
            await provider.connect()
            providers.append(provider)
        except Exception as e:
            log.warning(
                "failed to create provider",
                provider_id=config.get("id"),
                error=str(e),
            )

    return providers


# --- Test Connection ---


@dataclass
class TestConnectionResult:
    """Result of a test connection attempt."""

    success: bool
    provider_name: Optional[str] = None
    provider_version: Optional[str] = None
    tool_count: Optional[int] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # "process_not_found", "connection_refused", "handshake_failed", "timeout"
    # STP `server` software identifier ("Name/Version") from the handshake —
    # set by the provider software (not the user); telemetry validates it via
    # stp_identity.parse_server_identity before anything egresses.
    server: Optional[str] = None


async def test_provider_connection(
    provider_type: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
    url: Optional[str] = None,
    auth_token: Optional[str] = None,
    timeout: float = 10.0,
) -> TestConnectionResult:
    """
    Test connection to a tool provider without registering it.

    For stdio: spawns process, waits for STP handshake, terminates
    For websocket: connects, waits for STP handshake, disconnects

    Args:
        provider_type: "stdio" or "websocket"
        command: Command to run (stdio only)
        args: Command arguments (stdio only)
        working_dir: Working directory (stdio only)
        url: WebSocket URL (websocket only)
        auth_token: Bearer token for authentication (websocket only)
        timeout: How long to wait for handshake (seconds)

    Returns:
        TestConnectionResult with success status and details
    """
    transport: Optional[Transport] = None

    try:
        if provider_type == "stdio":
            if not command:
                return TestConnectionResult(
                    success=False,
                    error="Command is required for stdio provider",
                    error_type="invalid_config",
                )

            # Check if command exists
            import shutil as _shutil
            if not _shutil.which(command):
                return TestConnectionResult(
                    success=False,
                    error=f"Command not found: {command}",
                    error_type="process_not_found",
                )

            config = StdioProviderConfig(
                id="test-connection",
                command=command,
                args=args or [],
                working_dir=working_dir,
            )
            transport = StdioTransport(config)

        elif provider_type == "websocket":
            if not url:
                return TestConnectionResult(
                    success=False,
                    error="URL is required for websocket provider",
                    error_type="invalid_config",
                )

            config = WebSocketProviderConfig(
                id="test-connection",
                url=url,
                auth_token=auth_token,
            )
            transport = WebSocketTransport(config)

        else:
            return TestConnectionResult(
                success=False,
                error=f"Unknown provider type: {provider_type}",
                error_type="invalid_config",
            )

        # Connect transport
        try:
            await transport.connect()
        except ConnectionError as e:
            error_msg = str(e)
            error_type = "connection_refused"
            if "Failed to start" in error_msg or "not found" in error_msg.lower():
                error_type = "process_not_found"
            return TestConnectionResult(
                success=False,
                error=error_msg,
                error_type=error_type,
            )
        except Exception as e:
            return TestConnectionResult(
                success=False,
                error=f"Connection failed: {e}",
                error_type="connection_refused",
            )

        # Wait for provider.register message with timeout
        try:
            message = await asyncio.wait_for(
                transport.receive(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return TestConnectionResult(
                success=False,
                error=f"Timeout waiting for STP handshake (waited {timeout}s)",
                error_type="timeout",
            )

        if not message:
            return TestConnectionResult(
                success=False,
                error="Connection closed before handshake",
                error_type="connection_refused",
            )

        if message.get("method") != "provider.register":
            return TestConnectionResult(
                success=False,
                error=f"Expected provider.register, got: {message.get('method', 'no method')}",
                error_type="handshake_failed",
            )

        # Extract provider info from registration
        params = message.get("params", {})
        provider_name = params.get("provider_name") or params.get("provider_id", "Unknown")
        provider_version = params.get("version")

        # Send registration response to complete handshake
        response = {
            "jsonrpc": "2.0",
            "result": {
                "session_id": str(uuid.uuid4()),
                "stimma_version": "1.0.0",
            },
            "id": message.get("id"),
        }
        await transport.send(response)

        # Request tool list to get tool count
        tool_count = None
        try:
            request_id = 1
            list_request = {
                "jsonrpc": "2.0",
                "method": "tools.list",
                "params": {},
                "id": request_id,
            }
            await transport.send(list_request)

            # Wait for response
            list_response = await asyncio.wait_for(
                transport.receive(),
                timeout=5.0,
            )
            if list_response and "result" in list_response:
                tools = list_response["result"].get("tools", [])
                tool_count = len(tools)
        except Exception:
            # Tool listing is optional - connection still succeeded
            pass

        return TestConnectionResult(
            success=True,
            provider_name=provider_name,
            provider_version=provider_version,
            tool_count=tool_count,
            server=params.get("server"),
        )

    except Exception as e:
        log.exception("unexpected error during test connection")
        return TestConnectionResult(
            success=False,
            error=f"Unexpected error: {e}",
            error_type="unknown",
        )

    finally:
        # Always clean up transport
        if transport:
            try:
                await transport.disconnect()
            except Exception:
                pass

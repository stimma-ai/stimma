"""
JSON-RPC Provider Manager - handles lifecycle and auto-restart for external providers.

Manages:
- Initial connection with retries
- Health monitoring
- Auto-restart on failure:
  - stdio providers: up to 5 times at 2s intervals (then stops)
  - websocket providers: indefinitely at 2s intervals (remote services can come/go)
- Retry count resets on successful registration
"""

import asyncio
import structlog
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .jsonrpc import JsonRpcProvider, create_provider_from_config
from .registry import ProviderRegistry
from .base import ProviderStatus

log = structlog.get_logger(__name__)

# Maximum number of stderr lines to keep per provider
STDERR_BUFFER_SIZE = 500

MAX_RETRIES = 5


def _track_connection_changed(provider, connection_type: str, state: str, in_flight_jobs: int) -> None:
    """Emit provider_connection_changed — mid-session connection transitions.

    Categorical only: connection kind, validated STP product identity, state,
    and the count of jobs orphaned by a disconnect. Never user labels.
    """
    try:
        from stp_identity import parse_server_identity
        from telemetry import get_telemetry_client
        props = {
            "providerType": connection_type,
            "state": state,
            "inFlightJobs": in_flight_jobs,
        }
        identity = parse_server_identity(getattr(provider, "server", None))
        if identity.get("productName") and identity["productName"] != "unknown":
            props["productName"] = identity["productName"]
        get_telemetry_client().track(
            "provider_connection_changed", props, category="generation"
        )
    except Exception:
        pass


def _get_backend_name(provider_id: str) -> str:
    """Extract backend_name from provider_id.

    For builtin providers: "builtin:comfyui" -> "comfyui"
    For other providers: keep as-is

    This ensures consistency with how jobs are created in generation_queue.py
    """
    if provider_id.startswith("builtin:"):
        return provider_id.split(":", 1)[1]
    return provider_id


RETRY_INTERVAL_SECONDS = 2
HEALTH_CHECK_INTERVAL_SECONDS = 10


@dataclass
class ProviderState:
    """Tracks state for a managed provider."""
    config: dict
    provider: Optional[JsonRpcProvider] = None
    retry_count: int = 0
    is_healthy: bool = False
    restart_task: Optional[asyncio.Task] = None
    # Error tracking - persists even when provider fails to connect
    error_message: Optional[str] = None
    # Stderr log buffer - persists across restarts
    stderr_buffer: deque = field(default_factory=lambda: deque(maxlen=STDERR_BUFFER_SIZE))
    stderr_total_lines: int = 0
    # Process lifecycle tracking
    process_started_at: Optional[datetime] = None
    # Optional async callback to refresh auth token before reconnect
    # Called with config dict, should update config['auth_token'] in place
    token_refresh_callback: Optional[callable] = None


class JsonRpcProviderManager:
    """
    Manages JSON-RPC provider lifecycle with auto-restart.

    Features:
    - Connects providers on startup
    - Monitors health and restarts failed providers
    - stdio providers: limited to 5 restart attempts
    - websocket providers: retry indefinitely (remote services can come/go)
    - Resets retry count on successful registration
    """

    def __init__(self):
        self._providers: Dict[str, ProviderState] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._registry: Optional[ProviderRegistry] = None
        self._backend_registry = None
        # Error messages for providers not managed by this class (e.g., builtin providers)
        self._external_errors: Dict[str, str] = {}
        # Logs for providers not managed by this class (e.g., stimma-cloud)
        self._external_logs: Dict[str, list] = {}

    async def start(
        self,
        provider_configs: List[dict],
        provider_registry: ProviderRegistry,
        backend_registry,
    ) -> int:
        """
        Start managing providers from config.

        Args:
            provider_configs: List of provider config dicts
            provider_registry: The ProviderRegistry to register with
            backend_registry: The BackendRegistry to register backends with

        Returns:
            Number of successfully connected providers
        """
        self._registry = provider_registry
        self._backend_registry = backend_registry
        self._shutdown = False

        connected_count = 0

        for config in provider_configs:
            provider_id = config.get('id')
            if not provider_id:
                log.warning("Skipping provider config without id")
                continue

            # Initialize state
            self._providers[provider_id] = ProviderState(config=config)

            # Try initial connection
            if await self._connect_provider(provider_id):
                connected_count += 1

        # Start health monitor
        self._monitor_task = asyncio.create_task(self._health_monitor())

        return connected_count

    async def stop(self) -> None:
        """Stop managing providers and disconnect all."""
        self._shutdown = True

        # Cancel monitor
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Cancel any pending restart tasks
        for state in self._providers.values():
            if state.restart_task:
                state.restart_task.cancel()
                try:
                    await state.restart_task
                except asyncio.CancelledError:
                    pass

        # Disconnect providers - copy to avoid modification during iteration
        providers_snapshot = list(self._providers.items())
        for provider_id, state in providers_snapshot:
            if state.provider:
                try:
                    await self._registry.unregister(provider_id)
                except Exception as e:
                    log.warning(f"Error unregistering provider {provider_id}: {e}")

        self._providers.clear()

    def _add_log_line(self, state: ProviderState, line: str) -> None:
        """Add a line to the provider's stderr buffer."""
        state.stderr_buffer.append(line)
        state.stderr_total_lines += 1

    async def _connect_provider(self, provider_id: str) -> bool:
        """
        Connect a single provider.

        Returns:
            True if connected successfully
        """
        state = self._providers.get(provider_id)
        if not state:
            return False

        provider_type = state.config.get('type', 'stdio')

        # Refresh auth token if callback is set (e.g., for Stimma Cloud)
        if state.token_refresh_callback:
            try:
                await state.token_refresh_callback(state.config)
            except Exception as e:
                log.warning(
                    "token refresh failed",
                    provider_id=provider_id,
                    error=str(e),
                )
                # Continue anyway - maybe the token is still valid

        try:
            log.info(
                "connecting jsonrpc provider",
                provider_id=provider_id,
                attempt=state.retry_count + 1,
            )

            # Log process start to stderr buffer
            if provider_type == 'stdio':
                cmd = state.config.get('command', 'unknown')
                args = state.config.get('args', [])
                full_cmd = ' '.join([cmd] + args) if args else cmd
                self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Starting: {full_cmd}")
                state.process_started_at = datetime.now()
            elif provider_type == 'websocket':
                url = state.config.get('url', 'unknown')
                self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Connecting to: {url}")

            # Ensure clean slate - unregister any stale entries
            try:
                await self._registry.unregister(provider_id)
            except Exception:
                pass  # May not exist, that's fine
            try:
                await self._backend_registry.unregister_backend(_get_backend_name(provider_id))
            except Exception:
                pass

            # Create new provider instance with shared stderr buffer
            provider = create_provider_from_config(state.config)

            # Pass token refresh callback to the provider for HTTP operations
            if state.token_refresh_callback:
                provider._token_refresh_callback = state.token_refresh_callback

            # Pass the persistent stderr buffer to the provider
            provider._stderr_buffer = state.stderr_buffer
            provider._stderr_total_lines_ref = lambda: state.stderr_total_lines
            provider._add_stderr_line = lambda line: self._add_log_line(state, line)

            # Set disconnect callback for immediate restart
            def on_disconnect():
                log.info(
                    "jsonrpc provider disconnected - scheduling restart",
                    provider_id=provider_id,
                )
                state.is_healthy = False

                # Log disconnect with process info
                if provider_type == 'stdio' and state.process_started_at:
                    uptime = datetime.now() - state.process_started_at
                    uptime_str = str(uptime).split('.')[0]  # Remove microseconds
                    # Try to get exit code from transport
                    exit_code = None
                    if hasattr(provider, '_transport') and provider._transport:
                        transport = provider._transport
                        if hasattr(transport, '_process') and transport._process:
                            exit_code = transport._process.returncode
                    if exit_code is not None:
                        self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Process exited with code {exit_code} (uptime: {uptime_str})")
                    else:
                        self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Process disconnected (uptime: {uptime_str})")
                elif provider_type == 'websocket':
                    self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] WebSocket disconnected")

                # Unregister backend immediately so workers stop trying to use it
                async def handle_disconnect():
                    backend_name = _get_backend_name(provider_id)
                    orphaned_jobs = 0
                    try:
                        # Unregister from backend registry first
                        await self._backend_registry.unregister_backend(backend_name)
                        log.info("unregistered backend on disconnect", provider_id=provider_id, backend_name=backend_name)

                        # Then requeue any jobs that were processing
                        from generation_queue import get_generation_queue
                        queue = get_generation_queue()
                        count = await queue.cleanup_disconnected_backend(backend_name)
                        orphaned_jobs = count or 0
                        if count > 0:
                            log.info(
                                "requeued jobs for disconnected provider",
                                provider_id=provider_id,
                                count=count
                            )
                    except Exception as e:
                        log.warning(
                            "failed to handle provider disconnect",
                            provider_id=provider_id,
                            error=str(e)
                        )
                    _track_connection_changed(
                        provider, provider_type, "disconnected", orphaned_jobs
                    )

                asyncio.create_task(handle_disconnect())

                # Schedule restart task if not already running
                if not state.restart_task or state.restart_task.done():
                    state.restart_task = asyncio.create_task(
                        self._restart_provider(provider_id)
                    )

            provider._on_disconnect = on_disconnect

            async def on_tools_changed():
                log.info("tools changed notification, updating registry", provider_id=provider_id)
                # force_refresh=False: the provider already refreshed its tools
                # via RPC, so just re-read its cached list_tools()
                await self._registry.refresh_tools(provider_id, force_refresh=False)
                from utils.websocket import ws_manager
                await ws_manager.broadcast("tools_updated", {
                    "provider_id": provider_id,
                }, include_profile=False)

            provider._on_tools_changed = on_tools_changed

            await provider.connect()

            # Register with provider registry
            await self._registry.register(provider)

            # Register as backend using the extracted backend_name (e.g., "comfyui" not "builtin:comfyui")
            # This ensures consistency with how jobs are created and forever mode works
            backend_name = _get_backend_name(provider_id)
            await self._backend_registry.register_backend(
                backend_name,
                max_concurrent=provider.max_concurrent
            )

            # Update state - success clears error and resets retry count
            state.provider = provider
            state.is_healthy = True
            state.retry_count = 0  # Reset on success!
            state.error_message = None  # Clear error on success

            # Log successful connection
            tools = await provider.list_tools()
            self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Connected successfully")
            self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Loaded {len(tools)} tools")

            log.info(
                "jsonrpc provider connected",
                provider_id=provider_id,
                backend_name=backend_name,
                max_concurrent=provider.max_concurrent,
                tool_count=len(tools),
            )

            # Broadcast tools_updated so frontend refreshes (especially for reconnects)
            from utils.websocket import ws_manager
            await ws_manager.broadcast("tools_updated", {}, include_profile=False)

            _track_connection_changed(provider, provider_type, "connected", 0)

            return True

        except Exception as e:
            error_msg = str(e)
            log.warning(
                "jsonrpc provider connection failed",
                provider_id=provider_id,
                attempt=state.retry_count + 1,
                error=error_msg,
            )
            state.is_healthy = False
            state.error_message = error_msg  # Capture error message
            self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Connection failed: {error_msg}")
            state.provider = None
            return False

    async def _restart_provider(self, provider_id: str) -> None:
        """
        Restart a failed provider with retry logic.

        For stdio providers: Retries up to MAX_RETRIES times at RETRY_INTERVAL_SECONDS.
        For websocket providers: Retries indefinitely (remote services can come/go).
        """
        state = self._providers.get(provider_id)
        if not state or self._shutdown:
            return

        # Clear old provider reference
        state.provider = None

        # WebSocket providers retry indefinitely since remote services can come/go
        provider_type = state.config.get('type', 'stdio')
        retry_indefinitely = provider_type == 'websocket'

        while not self._shutdown:
            # For stdio: respect MAX_RETRIES limit
            if not retry_indefinitely and state.retry_count >= MAX_RETRIES:
                break

            state.retry_count += 1

            if retry_indefinitely:
                log.info(
                    "restarting jsonrpc provider",
                    provider_id=provider_id,
                    attempt=state.retry_count,
                    mode="indefinite (websocket)",
                )
            else:
                log.info(
                    "restarting jsonrpc provider",
                    provider_id=provider_id,
                    attempt=state.retry_count,
                    max_attempts=MAX_RETRIES,
                )

            # Wait before retry
            await asyncio.sleep(RETRY_INTERVAL_SECONDS)

            if self._shutdown:
                break

            # Try to connect (handles cleanup internally)
            if await self._connect_provider(provider_id):
                log.info(
                    "jsonrpc provider restarted successfully",
                    provider_id=provider_id,
                )
                return

        if not retry_indefinitely and state.retry_count >= MAX_RETRIES:
            log.error(
                "jsonrpc provider restart failed - max retries exceeded",
                provider_id=provider_id,
                max_retries=MAX_RETRIES,
            )

    async def _health_monitor(self) -> None:
        """Background task to monitor provider health."""
        while not self._shutdown:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)

                if self._shutdown:
                    break

                for provider_id, state in list(self._providers.items()):
                    if self._shutdown:
                        break

                    # Skip if already restarting
                    if state.restart_task and not state.restart_task.done():
                        continue

                    # Check health
                    is_healthy = await self._check_provider_health(provider_id, state)

                    if not is_healthy and state.is_healthy:
                        # Provider just failed - start restart
                        log.warning(
                            "jsonrpc provider health check failed",
                            provider_id=provider_id,
                        )
                        state.is_healthy = False
                        state.restart_task = asyncio.create_task(
                            self._restart_provider(provider_id)
                        )
                    elif not is_healthy and not state.is_healthy:
                        # Still unhealthy - check if we should retry
                        # WebSocket providers retry indefinitely, stdio respects MAX_RETRIES
                        provider_type = state.config.get('type', 'stdio')
                        should_retry = provider_type == 'websocket' or state.retry_count < MAX_RETRIES
                        if should_retry and (not state.restart_task or state.restart_task.done()):
                            state.restart_task = asyncio.create_task(
                                self._restart_provider(provider_id)
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception(f"Error in health monitor: {e}")

    async def _check_provider_health(
        self,
        provider_id: str,
        state: ProviderState
    ) -> bool:
        """Check if a provider is healthy."""
        if not state.provider:
            return False

        try:
            # Check provider status
            if state.provider.status != ProviderStatus.CONNECTED:
                return False

            return await state.provider.ping()

        except Exception as e:
            log.debug(f"Health check failed for {provider_id}: {e}")
            return False

    def get_error_message(self, provider_id: str) -> Optional[str]:
        """Get the last error message for a provider.

        This returns the error even if the provider is not currently registered
        in the provider registry (e.g., because it failed to connect).
        Checks both managed providers and external error messages.
        """
        state = self._providers.get(provider_id)
        if state:
            return state.error_message
        return self._external_errors.get(provider_id)

    def set_error_message(self, provider_id: str, message: str) -> None:
        """Set an error message for an external provider (not managed by this class).

        Used for builtin providers that aren't managed by jsonrpc_manager
        but need to show error state in the settings UI.
        """
        self._external_errors[provider_id] = message

    def clear_error_message(self, provider_id: str) -> None:
        """Clear an external error message (e.g., when provider connects successfully)."""
        self._external_errors.pop(provider_id, None)

    def add_provider_log(self, provider_id: str, line: str, max_lines: int = 1000) -> None:
        """Add a log line for an external provider (not managed by this class).

        Used for providers like stimma-cloud that manage their own connection
        but need to show logs in the settings UI.
        """
        if provider_id not in self._external_logs:
            self._external_logs[provider_id] = []
        self._external_logs[provider_id].append(line)
        # Trim if exceeds max
        if len(self._external_logs[provider_id]) > max_lines:
            self._external_logs[provider_id] = self._external_logs[provider_id][-max_lines:]

    def get_stderr_logs(self, provider_id: str) -> tuple[list[str], int]:
        """Get stderr logs for a provider.

        Returns:
            Tuple of (lines, total_lines_since_start)
            The buffer persists across provider restarts.
        """
        state = self._providers.get(provider_id)
        if state:
            return list(state.stderr_buffer), state.stderr_total_lines
        # Check external logs (for providers like stimma-cloud)
        external_logs = self._external_logs.get(provider_id, [])
        if external_logs:
            return list(external_logs), len(external_logs)
        return [], 0

    def get_process_uptime(self, provider_id: str) -> Optional[str]:
        """Get process uptime as a human-readable string."""
        state = self._providers.get(provider_id)
        if state and state.process_started_at and state.is_healthy:
            uptime = datetime.now() - state.process_started_at
            return str(uptime).split('.')[0]  # Remove microseconds
        return None

    async def add_provider(
        self,
        config: dict,
        token_refresh_callback: Optional[callable] = None,
    ) -> bool:
        """Add and connect a new provider at runtime.

        Args:
            config: Provider configuration dict
            token_refresh_callback: Optional async function to refresh auth token
                before each connection attempt. Called with config dict, should
                update config['auth_token'] in place.

        Returns:
            True if connected successfully
        """
        provider_id = config.get('id')
        if not provider_id:
            log.warning("Cannot add provider without id")
            return False

        if config.get("type") == "websocket":
            try:
                from privacy_lockdown import is_privacy_lockdown_enabled, is_stimma_service_url
                if is_privacy_lockdown_enabled() and is_stimma_service_url(config.get("url")):
                    log.info("skipping Stimma websocket provider in Privacy Lockdown", provider_id=provider_id)
                    return False
            except Exception:
                pass

        if provider_id in self._providers:
            log.warning("Provider already exists", provider_id=provider_id)
            return False

        # Initialize state and connect
        self._providers[provider_id] = ProviderState(
            config=config,
            token_refresh_callback=token_refresh_callback,
        )
        success = await self._connect_provider(provider_id)

        # If initial connection failed for websocket, start retry immediately
        # instead of waiting for the health monitor (which runs every 10s)
        if not success:
            state = self._providers.get(provider_id)
            provider_type = config.get('type', 'stdio')
            if state and provider_type == 'websocket':
                log.info("starting immediate retry for failed websocket provider", provider_id=provider_id)
                state.restart_task = asyncio.create_task(self._restart_provider(provider_id))

        return success

    async def reconnect_provider(self, provider_id: str, new_config: dict) -> bool:
        """Reconnect a provider with a new configuration.

        Preserves the stderr log buffer across reconnection.

        Args:
            provider_id: Provider ID to reconnect
            new_config: New provider configuration dict

        Returns:
            True if reconnected successfully
        """
        state = self._providers.get(provider_id)
        if not state:
            # Provider doesn't exist in manager, add it as new
            return await self.add_provider(new_config)

        # Cancel any pending restart task
        if state.restart_task and not state.restart_task.done():
            state.restart_task.cancel()
            try:
                await state.restart_task
            except asyncio.CancelledError:
                pass

        # Disconnect old provider if connected
        if state.provider:
            try:
                await self._registry.unregister(provider_id)
            except Exception as e:
                log.warning(f"Error unregistering provider {provider_id}: {e}")
            state.provider = None

        # Log the config change
        self._add_log_line(state, f"[{datetime.now().strftime('%H:%M:%S')}] Configuration changed, reconnecting...")

        # Update config but preserve stderr buffer
        state.config = new_config
        state.retry_count = 0  # Reset retries for new config
        state.error_message = None

        # Reconnect with new config
        return await self._connect_provider(provider_id)

    async def remove_provider(self, provider_id: str) -> None:
        """Remove a provider from management.

        Args:
            provider_id: Provider ID to remove
        """
        state = self._providers.get(provider_id)
        if not state:
            return

        # Cancel any pending restart task
        if state.restart_task and not state.restart_task.done():
            state.restart_task.cancel()
            try:
                await state.restart_task
            except asyncio.CancelledError:
                pass

        # Disconnect provider and unregister from both registries
        if state.provider:
            try:
                await self._registry.unregister(provider_id)
            except Exception as e:
                log.warning(f"Error unregistering provider {provider_id}: {e}")

        # Unregister from backend registry to stop jobs from being assigned
        backend_name = _get_backend_name(provider_id)
        try:
            await self._backend_registry.unregister_backend(backend_name)
        except Exception as e:
            log.warning(f"Error unregistering backend {backend_name}: {e}")

        # Remove from managed providers
        del self._providers[provider_id]
        log.info("provider removed from manager", provider_id=provider_id)


# Singleton instance
_manager: Optional[JsonRpcProviderManager] = None


def get_jsonrpc_manager() -> JsonRpcProviderManager:
    """Get the singleton JsonRpcProviderManager instance."""
    global _manager
    if _manager is None:
        _manager = JsonRpcProviderManager()
    return _manager

"""
Tests for providers.jsonrpc_manager.JsonRpcProviderManager.

Covers:
- _get_backend_name helper
- ProviderState defaults
- Error message get/set/clear (managed + external)
- Stderr log buffer management
- Process uptime query
- add_provider / remove_provider / reconnect_provider
- Health check logic (_check_provider_health)
- Restart retry logic
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.base import ProviderStatus
from providers.jsonrpc_manager import (
    JsonRpcProviderManager,
    ProviderState,
    STDERR_BUFFER_SIZE,
    MAX_RETRIES,
    _get_backend_name,
)


# ---------------------------------------------------------------------------
# _get_backend_name
# ---------------------------------------------------------------------------


class TestGetBackendName:
    def test_builtin_prefix_stripped(self):
        assert _get_backend_name("builtin:comfyui") == "comfyui"

    def test_other_ids_unchanged(self):
        assert _get_backend_name("mycomfy") == "mycomfy"
        assert _get_backend_name("cloud:provider") == "cloud:provider"

    def test_just_builtin_prefix(self):
        assert _get_backend_name("builtin:") == ""


# ---------------------------------------------------------------------------
# ProviderState defaults
# ---------------------------------------------------------------------------


class TestProviderState:
    def test_defaults(self):
        state = ProviderState(config={"id": "test"})
        assert state.provider is None
        assert state.retry_count == 0
        assert state.is_healthy is False
        assert state.restart_task is None
        assert state.error_message is None
        assert len(state.stderr_buffer) == 0
        assert state.stderr_total_lines == 0
        assert state.process_started_at is None
        assert state.token_refresh_callback is None

    def test_stderr_buffer_respects_maxlen(self):
        state = ProviderState(config={})
        assert state.stderr_buffer.maxlen == STDERR_BUFFER_SIZE


# ---------------------------------------------------------------------------
# Error Message Management
# ---------------------------------------------------------------------------


class TestErrorMessages:
    def test_get_error_for_managed_provider(self):
        mgr = JsonRpcProviderManager()
        mgr._providers["p1"] = ProviderState(
            config={}, error_message="Connection refused"
        )
        assert mgr.get_error_message("p1") == "Connection refused"

    def test_get_error_for_external_provider(self):
        mgr = JsonRpcProviderManager()
        mgr.set_error_message("ext", "Something broke")
        assert mgr.get_error_message("ext") == "Something broke"

    def test_get_error_returns_none_for_unknown(self):
        mgr = JsonRpcProviderManager()
        assert mgr.get_error_message("ghost") is None

    def test_clear_error_message(self):
        mgr = JsonRpcProviderManager()
        mgr.set_error_message("ext", "error")
        mgr.clear_error_message("ext")
        assert mgr.get_error_message("ext") is None

    def test_clear_nonexistent_is_noop(self):
        mgr = JsonRpcProviderManager()
        mgr.clear_error_message("nope")  # Should not raise

    def test_managed_takes_precedence_over_external(self):
        mgr = JsonRpcProviderManager()
        mgr.set_error_message("p1", "external error")
        mgr._providers["p1"] = ProviderState(
            config={}, error_message="managed error"
        )
        assert mgr.get_error_message("p1") == "managed error"


# ---------------------------------------------------------------------------
# Stderr Log Buffer
# ---------------------------------------------------------------------------


class TestStderrLogs:
    def test_add_log_line(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})
        mgr._add_log_line(state, "line 1")
        mgr._add_log_line(state, "line 2")

        assert list(state.stderr_buffer) == ["line 1", "line 2"]
        assert state.stderr_total_lines == 2

    def test_get_stderr_logs_managed(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})
        mgr._providers["p1"] = state
        mgr._add_log_line(state, "hello")

        lines, total = mgr.get_stderr_logs("p1")
        assert lines == ["hello"]
        assert total == 1

    def test_get_stderr_logs_external(self):
        mgr = JsonRpcProviderManager()
        mgr.add_provider_log("ext", "log1")
        mgr.add_provider_log("ext", "log2")

        lines, total = mgr.get_stderr_logs("ext")
        assert lines == ["log1", "log2"]
        assert total == 2

    def test_get_stderr_logs_unknown(self):
        mgr = JsonRpcProviderManager()
        lines, total = mgr.get_stderr_logs("unknown")
        assert lines == []
        assert total == 0

    def test_external_log_trimming(self):
        mgr = JsonRpcProviderManager()
        for i in range(15):
            mgr.add_provider_log("ext", f"line {i}", max_lines=10)

        lines, total = mgr.get_stderr_logs("ext")
        assert len(lines) == 10
        assert lines[0] == "line 5"  # First 5 trimmed


# ---------------------------------------------------------------------------
# Process Uptime
# ---------------------------------------------------------------------------


class TestProcessUptime:
    def test_uptime_when_healthy(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})
        state.process_started_at = datetime.now() - timedelta(hours=1, minutes=30)
        state.is_healthy = True
        mgr._providers["p1"] = state

        uptime = mgr.get_process_uptime("p1")
        assert uptime is not None
        assert "1:30" in uptime

    def test_uptime_when_unhealthy(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})
        state.process_started_at = datetime.now()
        state.is_healthy = False
        mgr._providers["p1"] = state

        assert mgr.get_process_uptime("p1") is None

    def test_uptime_when_no_start_time(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})
        state.is_healthy = True
        mgr._providers["p1"] = state

        assert mgr.get_process_uptime("p1") is None

    def test_uptime_unknown_provider(self):
        mgr = JsonRpcProviderManager()
        assert mgr.get_process_uptime("ghost") is None


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


class TestCheckProviderHealth:
    async def test_healthy_provider(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})

        mock_provider = MagicMock()
        mock_provider.status = ProviderStatus.CONNECTED
        mock_provider.ping = AsyncMock(return_value=True)
        state.provider = mock_provider

        result = await mgr._check_provider_health("p1", state)
        assert result is True

    async def test_no_provider(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})
        state.provider = None

        result = await mgr._check_provider_health("p1", state)
        assert result is False

    async def test_disconnected_status(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})

        mock_provider = MagicMock()
        mock_provider.status = ProviderStatus.DISCONNECTED
        state.provider = mock_provider

        result = await mgr._check_provider_health("p1", state)
        assert result is False

    async def test_ping_fails(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})

        mock_provider = MagicMock()
        mock_provider.status = ProviderStatus.CONNECTED
        mock_provider.ping = AsyncMock(return_value=False)
        state.provider = mock_provider

        result = await mgr._check_provider_health("p1", state)
        assert result is False

    async def test_ping_raises(self):
        mgr = JsonRpcProviderManager()
        state = ProviderState(config={})

        mock_provider = MagicMock()
        mock_provider.status = ProviderStatus.CONNECTED
        mock_provider.ping = AsyncMock(side_effect=RuntimeError("network error"))
        state.provider = mock_provider

        result = await mgr._check_provider_health("p1", state)
        assert result is False


# ---------------------------------------------------------------------------
# add_provider / remove_provider
# ---------------------------------------------------------------------------


class TestAddRemoveProvider:
    async def test_add_provider_no_id(self):
        mgr = JsonRpcProviderManager()
        result = await mgr.add_provider({})
        assert result is False

    async def test_add_provider_duplicate(self):
        mgr = JsonRpcProviderManager()
        mgr._providers["existing"] = ProviderState(config={"id": "existing"})
        result = await mgr.add_provider({"id": "existing"})
        assert result is False

    async def test_remove_nonexistent_is_noop(self):
        mgr = JsonRpcProviderManager()
        await mgr.remove_provider("ghost")  # Should not raise

    async def test_remove_provider_cancels_restart_task(self):
        mgr = JsonRpcProviderManager()
        mgr._registry = MagicMock()
        mgr._backend_registry = MagicMock()
        mgr._backend_registry.unregister_backend = AsyncMock()

        state = ProviderState(config={"id": "p1"})
        state.provider = None  # Not connected

        # Create a fake restart task
        async def fake_restart():
            await asyncio.sleep(100)
        state.restart_task = asyncio.create_task(fake_restart())

        mgr._providers["p1"] = state

        await mgr.remove_provider("p1")

        assert "p1" not in mgr._providers
        assert state.restart_task.cancelled()


# ---------------------------------------------------------------------------
# Restart Logic
# ---------------------------------------------------------------------------


class TestRestartLogic:
    async def test_stdio_retries_limited_to_max(self):
        mgr = JsonRpcProviderManager()
        mgr._shutdown = False

        state = ProviderState(config={"id": "p1", "type": "stdio"})
        mgr._providers["p1"] = state

        # Mock _connect_provider to always fail
        mgr._connect_provider = AsyncMock(return_value=False)

        await mgr._restart_provider("p1")

        assert state.retry_count == MAX_RETRIES
        assert mgr._connect_provider.call_count == MAX_RETRIES

    async def test_restart_stops_on_shutdown(self):
        mgr = JsonRpcProviderManager()
        mgr._shutdown = False

        state = ProviderState(config={"id": "p1", "type": "stdio"})
        mgr._providers["p1"] = state

        call_count = 0
        original_sleep = asyncio.sleep

        async def fake_connect(pid):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._shutdown = True
            return False

        mgr._connect_provider = fake_connect

        with patch("providers.jsonrpc_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr._restart_provider("p1")

        assert call_count <= 3  # Should stop early due to shutdown

    async def test_restart_stops_when_successful(self):
        mgr = JsonRpcProviderManager()
        mgr._shutdown = False

        state = ProviderState(config={"id": "p1", "type": "stdio"})
        mgr._providers["p1"] = state

        call_count = 0

        async def fake_connect(pid):
            nonlocal call_count
            call_count += 1
            return call_count == 2  # Succeeds on second attempt

        mgr._connect_provider = fake_connect

        with patch("providers.jsonrpc_manager.asyncio.sleep", new_callable=AsyncMock):
            await mgr._restart_provider("p1")

        assert call_count == 2

    async def test_restart_nonexistent_provider_is_noop(self):
        mgr = JsonRpcProviderManager()
        await mgr._restart_provider("ghost")  # Should not raise


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


class TestStop:
    async def test_stop_sets_shutdown_flag(self):
        mgr = JsonRpcProviderManager()
        mgr._shutdown = False
        mgr._monitor_task = None

        await mgr.stop()

        assert mgr._shutdown is True

"""
Tests for providers.health.ProviderHealthMonitor.

Covers:
- Health check logic (connected, ping success/failure, timeout)
- Failure threshold tracking
- Subscriber notifications on status change
- get_health / get_all_health / get_available_providers / is_provider_available
- Start/stop lifecycle
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from providers.base import ProviderStatus, ToolDescriptor, ToolProvider, ExecutionResult
from providers.health import ProviderHealth, ProviderHealthMonitor
from providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeProvider(ToolProvider):
    """Minimal provider with controllable status and ping."""

    def __init__(self, pid="fake", connected=True, ping_result=True, ping_raises=None):
        self._pid = pid
        self._connected = connected
        self._ping_result = ping_result
        self._ping_raises = ping_raises

    @property
    def provider_id(self): return self._pid
    @property
    def provider_name(self): return "Fake"
    @property
    def provider_type(self): return "builtin"
    @property
    def status(self):
        return ProviderStatus.CONNECTED if self._connected else ProviderStatus.DISCONNECTED

    async def connect(self): pass
    async def disconnect(self): pass
    async def list_tools(self): return []
    async def execute(self, *args, **kwargs):
        yield ExecutionResult(success=True)
    async def upload_asset(self, data, mime_type): return "a"
    async def download_asset(self, asset_id): return b""

    async def ping(self):
        if self._ping_raises:
            raise self._ping_raises
        return self._ping_result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singletons before each test."""
    ProviderHealthMonitor._instance = None
    ProviderRegistry.reset()
    yield
    ProviderHealthMonitor._instance = None
    ProviderRegistry.reset()


@pytest.fixture
def monitor():
    return ProviderHealthMonitor(check_interval=1.0, failure_threshold=3)


@pytest.fixture
def registry():
    return ProviderRegistry.get_instance()


# ---------------------------------------------------------------------------
# Health Check Logic
# ---------------------------------------------------------------------------


class TestCheckProvider:
    async def test_healthy_provider(self, monitor):
        provider = FakeProvider("ok", connected=True, ping_result=True)

        await monitor._check_provider("ok", provider)

        health = monitor.get_health("ok")
        assert health is not None
        assert health.status == ProviderStatus.CONNECTED
        assert health.consecutive_failures == 0
        assert health.last_healthy is not None

    async def test_disconnected_provider(self, monitor):
        provider = FakeProvider("dc", connected=False)

        await monitor._check_provider("dc", provider)

        health = monitor.get_health("dc")
        assert health.status == ProviderStatus.DISCONNECTED
        assert health.error_message == "Provider not connected"

    async def test_ping_returns_false(self, monitor):
        provider = FakeProvider("bad", connected=True, ping_result=False)

        await monitor._check_provider("bad", provider)

        health = monitor.get_health("bad")
        assert health.consecutive_failures == 1
        assert health.error_message == "Ping returned false"

    async def test_ping_raises_exception(self, monitor):
        provider = FakeProvider("err", connected=True, ping_raises=RuntimeError("boom"))

        await monitor._check_provider("err", provider)

        health = monitor.get_health("err")
        assert health.consecutive_failures == 1
        assert "boom" in health.error_message

    async def test_ping_timeout(self, monitor):
        async def slow_ping():
            await asyncio.sleep(20)
            return True

        provider = FakeProvider("slow", connected=True)
        provider.ping = slow_ping

        # Patch the timeout to be short
        with patch("providers.health.asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            await monitor._check_provider("slow", provider)

        health = monitor.get_health("slow")
        assert health.consecutive_failures == 1
        assert "timed out" in health.error_message.lower()


# ---------------------------------------------------------------------------
# Failure Threshold
# ---------------------------------------------------------------------------


class TestFailureThreshold:
    async def test_status_becomes_error_at_threshold(self, monitor):
        provider = FakeProvider("fail", connected=True, ping_result=True)

        # First establish healthy state
        await monitor._check_provider("fail", provider)
        health = monitor.get_health("fail")
        assert health.status == ProviderStatus.CONNECTED

        # Now start failing - below threshold keeps previous status
        provider._ping_result = False
        for _ in range(2):
            await monitor._check_provider("fail", provider)
        health = monitor.get_health("fail")
        assert health.consecutive_failures == 2

        # At threshold → ERROR
        await monitor._check_provider("fail", provider)
        health = monitor.get_health("fail")
        assert health.status == ProviderStatus.ERROR
        assert health.consecutive_failures == 3

    async def test_first_failure_for_new_provider_sets_error(self, monitor):
        """A provider that has never been seen before gets ERROR on first failure."""
        provider = FakeProvider("new-fail", connected=True, ping_result=False)
        await monitor._check_provider("new-fail", provider)

        health = monitor.get_health("new-fail")
        assert health.status == ProviderStatus.ERROR
        assert health.consecutive_failures == 1

    async def test_recovery_resets_failures(self, monitor):
        provider = FakeProvider("recov", connected=True, ping_result=False)

        # Fail a few times
        for _ in range(2):
            await monitor._check_provider("recov", provider)

        # Recover
        provider._ping_result = True
        await monitor._check_provider("recov", provider)

        health = monitor.get_health("recov")
        assert health.consecutive_failures == 0
        assert health.status == ProviderStatus.CONNECTED


# ---------------------------------------------------------------------------
# Subscriber Notifications
# ---------------------------------------------------------------------------


class TestSubscriberNotifications:
    async def test_notified_on_status_change(self, monitor):
        provider = FakeProvider("notify", connected=True, ping_result=True)
        callback = MagicMock()
        monitor.subscribe(callback)

        # First check - new provider → status change from None to CONNECTED
        await monitor._check_provider("notify", provider)
        callback.assert_called_once_with("notify", ProviderStatus.CONNECTED, None)

    async def test_not_notified_when_status_unchanged(self, monitor):
        provider = FakeProvider("stable", connected=True, ping_result=True)
        callback = MagicMock()

        # First check sets initial state
        await monitor._check_provider("stable", provider)

        monitor.subscribe(callback)

        # Second check - same status, no notification
        await monitor._check_provider("stable", provider)
        callback.assert_not_called()

    async def test_unsubscribe(self, monitor):
        callback = MagicMock()
        monitor.subscribe(callback)
        monitor.unsubscribe(callback)

        provider = FakeProvider("unsub", connected=True)
        await monitor._check_provider("unsub", provider)
        callback.assert_not_called()

    async def test_duplicate_subscribe_ignored(self, monitor):
        callback = MagicMock()
        monitor.subscribe(callback)
        monitor.subscribe(callback)
        assert monitor._subscribers.count(callback) == 1

    async def test_subscriber_exception_swallowed(self, monitor):
        bad = MagicMock(side_effect=RuntimeError("oops"))
        monitor.subscribe(bad)

        provider = FakeProvider("exc", connected=True)
        # Should not raise
        await monitor._check_provider("exc", provider)


# ---------------------------------------------------------------------------
# Query Methods
# ---------------------------------------------------------------------------


class TestQueryMethods:
    async def test_get_all_health(self, monitor):
        p1 = FakeProvider("a", connected=True)
        p2 = FakeProvider("b", connected=False)

        await monitor._check_provider("a", p1)
        await monitor._check_provider("b", p2)

        all_health = monitor.get_all_health()
        assert "a" in all_health
        assert "b" in all_health

    async def test_get_available_providers(self, monitor):
        await monitor._check_provider("ok", FakeProvider("ok", connected=True))
        await monitor._check_provider("dc", FakeProvider("dc", connected=False))

        available = monitor.get_available_providers()
        assert "ok" in available
        assert "dc" not in available

    async def test_is_provider_available(self, monitor):
        await monitor._check_provider("yes", FakeProvider("yes", connected=True))

        assert monitor.is_provider_available("yes") is True
        assert monitor.is_provider_available("unknown") is False


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_start_creates_monitor_task(self, monitor):
        with patch.object(monitor, "_check_all_providers", new_callable=AsyncMock):
            await monitor.start()
            assert monitor._running is True
            assert monitor._monitor_task is not None
            await monitor.stop()
            assert monitor._running is False

    async def test_double_start_is_noop(self, monitor):
        with patch.object(monitor, "_check_all_providers", new_callable=AsyncMock):
            await monitor.start()
            task1 = monitor._monitor_task
            await monitor.start()
            assert monitor._monitor_task is task1
            await monitor.stop()

    async def test_check_all_providers_uses_registry(self, monitor, registry):
        """_check_all_providers iterates registered providers."""
        provider = FakeProvider("reg", connected=True)

        # Patch to bypass DB/WS
        with patch.object(ProviderRegistry, "_cache_tools_to_db", new_callable=AsyncMock), \
             patch.object(ProviderRegistry, "_broadcast_provider_status", new_callable=AsyncMock):
            await registry.register(provider)

        await monitor._check_all_providers()

        health = monitor.get_health("reg")
        assert health is not None
        assert health.status == ProviderStatus.CONNECTED

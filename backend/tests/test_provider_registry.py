"""
Tests for providers.registry.ProviderRegistry.

Covers:
- Singleton behavior and reset
- Provider registration / unregistration
- Tool cache (exact and case-insensitive lookup)
- List helpers (all tools, by task type, by provider)
- Status subscriptions
- execute_tool delegation
- interrupt helpers
- shutdown
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from providers.base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)
from providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(tool_id: str, task_type: str = None, task_types: list = None) -> ToolDescriptor:
    return ToolDescriptor(
        id=tool_id,
        name=tool_id.replace("-", " ").title(),
        parameter_schema={},
        output_schema={},
        task_type=task_type,
        task_types=task_types or [],
    )


class MockProvider(ToolProvider):
    """Lightweight mock provider for registry tests."""

    def __init__(self, pid: str = "mock", tools: list = None, max_conc: int = 1):
        self._pid = pid
        self._tools = tools or []
        self._status = ProviderStatus.DISCONNECTED
        self._max_concurrent = max_conc
        self.connect_called = False
        self.disconnect_called = False
        self._interrupt_count = 0

    @property
    def provider_id(self): return self._pid
    @property
    def provider_name(self): return f"Mock {self._pid}"
    @property
    def provider_type(self): return "builtin"
    @property
    def status(self): return self._status
    @property
    def max_concurrent(self): return self._max_concurrent

    async def connect(self):
        self._status = ProviderStatus.CONNECTED
        self.connect_called = True

    async def disconnect(self):
        self._status = ProviderStatus.DISCONNECTED
        self.disconnect_called = True

    async def list_tools(self): return list(self._tools)

    async def execute(self, tool_id, parameters,
                      output_path=None, progress_callback=None, request_id=None):
        yield ExecutionProgress(progress=0.5, stage="working")
        yield ExecutionResult(success=True, metadata={"tool_id": tool_id})

    async def upload_asset(self, data, mime_type): return "asset-1"
    async def download_asset(self, asset_id): return b"data"

    async def interrupt(self):
        self._interrupt_count += 1
        return 2

    async def interrupt_and_clear(self):
        self._interrupt_count += 1
        return 5


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton registry before each test."""
    ProviderRegistry.reset()
    yield
    ProviderRegistry.reset()


@pytest.fixture
def registry():
    return ProviderRegistry.get_instance()


# Patch DB and WebSocket interactions for all tests in this module
@pytest.fixture(autouse=True)
def patch_external_deps():
    with patch.object(ProviderRegistry, "_cache_tools_to_db", new_callable=AsyncMock), \
         patch.object(ProviderRegistry, "_broadcast_provider_status", new_callable=AsyncMock):
        yield


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_instance(self):
        a = ProviderRegistry.get_instance()
        b = ProviderRegistry.get_instance()
        assert a is b

    def test_reset_clears_state(self, registry):
        registry._providers["x"] = "dummy"
        ProviderRegistry.reset()
        assert len(registry._providers) == 0
        assert len(registry._tools_cache) == 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    async def test_register_connects_and_caches(self, registry):
        tool = _make_tool("t2i", task_type="text-to-image")
        provider = MockProvider("p1", tools=[tool])

        await registry.register(provider)

        assert provider.connect_called
        assert "p1" in registry._providers
        assert registry.get_tool("p1:t2i") is not None

    async def test_register_duplicate_raises(self, registry):
        provider = MockProvider("dup")
        await registry.register(provider)

        with pytest.raises(ValueError, match="already registered"):
            await registry.register(MockProvider("dup"))

    async def test_unregister_disconnects_and_clears(self, registry):
        tool = _make_tool("x")
        provider = MockProvider("p2", tools=[tool])
        await registry.register(provider)

        await registry.unregister("p2")

        assert provider.disconnect_called
        assert "p2" not in registry._providers
        assert registry.get_tool("p2:x") is None

    async def test_unregister_nonexistent_is_noop(self, registry):
        # Should not raise
        await registry.unregister("ghost")


# ---------------------------------------------------------------------------
# Tool Lookup
# ---------------------------------------------------------------------------


class TestToolLookup:
    async def test_exact_match(self, registry):
        tool = _make_tool("upscale")
        await registry.register(MockProvider("comfy", tools=[tool]))

        result = registry.get_tool("comfy:upscale")
        assert result is not None
        provider, descriptor = result
        assert descriptor.id == "upscale"

    async def test_case_insensitive_match(self, registry):
        tool = _make_tool("Text-To-Image")
        await registry.register(MockProvider("comfy", tools=[tool]))

        result = registry.get_tool("COMFY:TEXT-TO-IMAGE")
        assert result is not None

    async def test_not_found_returns_none(self, registry):
        assert registry.get_tool("nope:missing") is None


class TestEnabledProviderIds:
    def test_cloud_is_known_when_no_config_row_exists(self, registry):
        settings = MagicMock(tool_providers=[])
        with patch("config.get_settings", return_value=settings):
            assert "stimma-cloud" in registry.get_enabled_provider_ids()

    def test_explicitly_disabled_cloud_is_not_enabled(self, registry):
        cloud = MagicMock(id="stimma-cloud", enabled=False)
        settings = MagicMock(tool_providers=[cloud])
        with patch("config.get_settings", return_value=settings):
            assert "stimma-cloud" not in registry.get_enabled_provider_ids()


# ---------------------------------------------------------------------------
# List Methods
# ---------------------------------------------------------------------------


class TestListMethods:
    async def test_list_all_tools(self, registry):
        await registry.register(MockProvider("a", tools=[_make_tool("t1")]))
        await registry.register(MockProvider("b", tools=[_make_tool("t2")]))

        all_tools = registry.list_all_tools()
        ids = {full_id for full_id, _, _ in all_tools}
        assert ids == {"a:t1", "b:t2"}

    async def test_list_tools_by_task_type(self, registry):
        t2i = _make_tool("gen", task_type="text-to-image")
        i2i = _make_tool("edit", task_type="image-to-image")
        await registry.register(MockProvider("x", tools=[t2i, i2i]))

        result = registry.list_tools_by_task_type("text-to-image")
        assert len(result) == 1
        assert result[0][2].id == "gen"

    async def test_list_tools_by_task_type_uses_task_types_list(self, registry):
        multi = _make_tool("multi", task_types=["text-to-image", "image-to-image"])
        await registry.register(MockProvider("y", tools=[multi]))

        assert len(registry.list_tools_by_task_type("text-to-image")) == 1
        assert len(registry.list_tools_by_task_type("image-to-image")) == 1

    async def test_list_tools_by_provider(self, registry):
        await registry.register(MockProvider("a", tools=[_make_tool("t1"), _make_tool("t2")]))
        await registry.register(MockProvider("b", tools=[_make_tool("t3")]))

        result = registry.list_tools_by_provider("a")
        assert len(result) == 2

    async def test_list_providers(self, registry):
        await registry.register(MockProvider("a"))
        await registry.register(MockProvider("b"))

        providers = registry.list_providers()
        ids = {p.provider_id for p in providers}
        assert ids == {"a", "b"}

    async def test_get_provider_ids(self, registry):
        await registry.register(MockProvider("a"))
        assert registry.get_provider_ids() == {"a"}

    async def test_get_provider(self, registry):
        p = MockProvider("found")
        await registry.register(p)

        assert registry.get_provider("found") is p
        assert registry.get_provider("missing") is None


# ---------------------------------------------------------------------------
# Status Subscriptions
# ---------------------------------------------------------------------------


class TestStatusSubscriptions:
    async def test_subscriber_called_on_unregister(self, registry):
        provider = MockProvider("sub-test")
        await registry.register(provider)

        callback = MagicMock()
        registry.subscribe_status(callback)

        await registry.unregister("sub-test")

        callback.assert_called_once_with("sub-test", ProviderStatus.DISCONNECTED)

    async def test_unsubscribe(self, registry):
        callback = MagicMock()
        registry.subscribe_status(callback)
        registry.unsubscribe_status(callback)

        provider = MockProvider("x")
        await registry.register(provider)
        await registry.unregister("x")

        callback.assert_not_called()

    async def test_subscriber_exception_is_swallowed(self, registry):
        bad_callback = MagicMock(side_effect=RuntimeError("boom"))
        registry.subscribe_status(bad_callback)

        provider = MockProvider("x")
        await registry.register(provider)
        # Should not raise
        await registry.unregister("x")


# ---------------------------------------------------------------------------
# Execute Tool
# ---------------------------------------------------------------------------


class TestExecuteTool:
    async def test_execute_delegates_to_provider(self, registry):
        tool = _make_tool("gen")
        await registry.register(MockProvider("p", tools=[tool]))

        items = []
        async for item in registry.execute_tool("p:gen", {}):
            items.append(item)

        assert len(items) == 2
        assert isinstance(items[0], ExecutionProgress)
        assert isinstance(items[1], ExecutionResult)
        assert items[1].success is True

    async def test_execute_not_found_raises(self, registry):
        with pytest.raises(ValueError, match="Tool not found"):
            async for _ in registry.execute_tool("no:tool", {}):
                pass

    async def test_execute_disconnected_raises(self, registry):
        tool = _make_tool("gen")
        provider = MockProvider("p", tools=[tool])
        await registry.register(provider)

        # Force disconnect status without unregistering
        provider._status = ProviderStatus.DISCONNECTED

        with pytest.raises(RuntimeError, match="disconnected"):
            async for _ in registry.execute_tool("p:gen", {}):
                pass


# ---------------------------------------------------------------------------
# Interrupt
# ---------------------------------------------------------------------------


class TestInterrupt:
    async def test_interrupt_all(self, registry):
        await registry.register(MockProvider("a"))
        await registry.register(MockProvider("b"))

        total = await registry.interrupt_all()
        assert total == 4  # 2 per provider

    async def test_interrupt_specific(self, registry):
        await registry.register(MockProvider("a"))
        await registry.register(MockProvider("b"))

        total = await registry.interrupt_all(provider_id="a")
        assert total == 2

    async def test_interrupt_and_clear_all(self, registry):
        await registry.register(MockProvider("a"))
        total = await registry.interrupt_and_clear_all()
        assert total == 5

    async def test_interrupt_nonexistent_returns_zero(self, registry):
        total = await registry.interrupt_all(provider_id="ghost")
        assert total == 0


# ---------------------------------------------------------------------------
# Refresh Tools
# ---------------------------------------------------------------------------


class TestRefreshTools:
    async def test_refresh_updates_cache(self, registry):
        tool1 = _make_tool("old")
        provider = MockProvider("r", tools=[tool1])
        await registry.register(provider)

        assert registry.get_tool("r:old") is not None

        # Swap tools
        tool2 = _make_tool("new")
        provider._tools = [tool2]

        await registry.refresh_tools(provider_id="r")

        assert registry.get_tool("r:old") is None
        assert registry.get_tool("r:new") is not None

    async def test_refresh_all_providers(self, registry):
        await registry.register(MockProvider("a", tools=[_make_tool("t1")]))
        await registry.register(MockProvider("b", tools=[_make_tool("t2")]))

        await registry.refresh_tools()  # refreshes all

        # Tools should still be there (same list_tools results)
        assert registry.get_tool("a:t1") is not None
        assert registry.get_tool("b:t2") is not None


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    async def test_shutdown_disconnects_all(self, registry):
        p1 = MockProvider("a")
        p2 = MockProvider("b")
        await registry.register(p1)
        await registry.register(p2)

        await registry.shutdown()

        assert p1.disconnect_called
        assert p2.disconnect_called
        assert len(registry._providers) == 0
        assert len(registry._tools_cache) == 0
        assert len(registry._status_subscribers) == 0

"""
Tests for providers.base module.

Covers:
- ToolDescriptor dataclass and auto-population logic
- ExecutionProgress and ExecutionResult dataclasses
- ToolProvider abstract base class default method implementations
"""

import pytest
from providers.base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)


# ---------------------------------------------------------------------------
# ToolDescriptor
# ---------------------------------------------------------------------------


class TestToolDescriptor:
    def test_basic_construction(self):
        td = ToolDescriptor(
            id="text-to-image",
            name="Text to Image",
            parameter_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        assert td.id == "text-to-image"
        assert td.name == "Text to Image"
        assert td.task_type is None
        assert td.task_types == []

    def test_task_types_auto_populated_from_task_type(self):
        td = ToolDescriptor(
            id="t2i",
            name="T2I",
            parameter_schema={},
            output_schema={},
            task_type="text-to-image",
        )
        assert td.task_types == ["text-to-image"]

    def test_explicit_task_types_not_overridden(self):
        td = ToolDescriptor(
            id="multi",
            name="Multi",
            parameter_schema={},
            output_schema={},
            task_type="text-to-image",
            task_types=["text-to-image", "image-to-image"],
        )
        assert td.task_types == ["text-to-image", "image-to-image"]

    def test_full_id(self):
        td = ToolDescriptor(
            id="upscale",
            name="Upscale",
            parameter_schema={},
            output_schema={},
        )
        assert td.full_id("comfyui") == "comfyui:upscale"

    def test_metadata_defaults_to_empty_dict(self):
        td = ToolDescriptor(
            id="x", name="X",
            parameter_schema={}, output_schema={},
        )
        assert td.metadata == {}

    def test_optional_fields_default_none(self):
        td = ToolDescriptor(
            id="x", name="X",
            parameter_schema={}, output_schema={},
        )
        assert td.layout is None
        assert td.subtitle is None
        assert td.description is None
        assert td.raw_registration is None


# ---------------------------------------------------------------------------
# ExecutionProgress / ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionProgress:
    def test_basic_progress(self):
        p = ExecutionProgress(progress=0.5, stage="sampling")
        assert p.progress == 0.5
        assert p.stage == "sampling"
        assert p.preview_data is None
        assert p.message is None

    def test_with_preview(self):
        data = b"\x89PNG"
        p = ExecutionProgress(progress=0.8, stage="encoding", preview_data=data)
        assert p.preview_data == data


class TestExecutionResult:
    def test_success_result(self):
        r = ExecutionResult(success=True, output_data=b"img", generation_time=1.5)
        assert r.success is True
        assert r.output_data == b"img"
        assert r.generation_time == 1.5
        assert r.error is None

    def test_failure_result(self):
        r = ExecutionResult(success=False, error="OOM")
        assert r.success is False
        assert r.error == "OOM"
        assert r.output_data is None

    def test_defaults(self):
        r = ExecutionResult(success=True)
        assert r.generation_time == 0.0
        assert r.actual_seed is None
        assert r.metadata == {}
        assert r.additional_outputs == []
        assert r.workflow is None


# ---------------------------------------------------------------------------
# ToolProvider default methods
# ---------------------------------------------------------------------------


def _make_tool(tool_id: str = "tool-a") -> ToolDescriptor:
    return ToolDescriptor(
        id=tool_id, name=tool_id.title(),
        parameter_schema={}, output_schema={},
    )


class _StubProvider(ToolProvider):
    """Minimal concrete provider for testing default methods."""

    def __init__(self, tools=None, connected=True):
        self._tools = tools or []
        self._connected = connected

    @property
    def provider_id(self): return "stub"
    @property
    def provider_name(self): return "Stub"
    @property
    def provider_type(self): return "builtin"
    @property
    def status(self):
        return ProviderStatus.CONNECTED if self._connected else ProviderStatus.DISCONNECTED

    async def connect(self): pass
    async def disconnect(self): pass
    async def list_tools(self): return self._tools

    async def execute(self, tool_id, parameters,
                      output_path=None, progress_callback=None, request_id=None):
        yield ExecutionResult(success=True)

    async def upload_asset(self, data, mime_type): return "asset-1"
    async def download_asset(self, asset_id): return b"data"


class TestToolProviderDefaults:
    async def test_get_tool_found(self):
        tool = _make_tool("my-tool")
        provider = _StubProvider(tools=[tool])
        result = await provider.get_tool("my-tool")
        assert result is tool

    async def test_get_tool_not_found(self):
        provider = _StubProvider(tools=[_make_tool("other")])
        result = await provider.get_tool("missing")
        assert result is None

    async def test_refresh_tools_delegates_to_list_tools(self):
        tools = [_make_tool("a"), _make_tool("b")]
        provider = _StubProvider(tools=tools)
        result = await provider.refresh_tools()
        assert result == tools

    async def test_max_concurrent_default(self):
        provider = _StubProvider()
        assert provider.max_concurrent == 1

    async def test_ping_connected(self):
        provider = _StubProvider(connected=True)
        assert await provider.ping() is True

    async def test_ping_disconnected(self):
        provider = _StubProvider(connected=False)
        assert await provider.ping() is False

    async def test_delete_asset_default_returns_true(self):
        provider = _StubProvider()
        assert await provider.delete_asset("any-id") is True

    async def test_interrupt_default_returns_zero(self):
        provider = _StubProvider()
        assert await provider.interrupt() == 0

    async def test_interrupt_and_clear_delegates_to_interrupt(self):
        provider = _StubProvider()
        assert await provider.interrupt_and_clear() == 0

    async def test_upload_to_tool_raises_not_implemented(self):
        provider = _StubProvider()
        with pytest.raises(NotImplementedError):
            await provider.upload_to_tool("tool", "param", "file.bin", b"data")

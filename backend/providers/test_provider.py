"""
Test Provider - configurable mock provider for integration tests.

Provides realistic tool execution simulation with:
- Configurable progress events
- Configurable success/failure behavior
- Deterministic dummy image output
"""

import asyncio
import io
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from PIL import Image

from .base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)


@dataclass
class TestToolConfig:
    """Configuration for test tool behavior."""

    delay_per_stage: float = 0.01  # Seconds between progress events
    should_fail: bool = False
    fail_at_progress: float = 0.5  # Progress value at which to fail (0.0-1.0)
    fail_message: str = "Simulated failure"
    output_size: tuple = (64, 64)  # Width, height of dummy images
    output_color: tuple = (255, 0, 0)  # RGB color for dummy images


class TestToolProvider(ToolProvider):
    """
    Test provider with configurable behavior for integration tests.

    Usage in tests:
        provider = TestToolProvider()
        await provider.connect()

        # Configure a tool to fail
        provider.configure_tool("text-to-image:test-model", TestToolConfig(
            should_fail=True,
            fail_at_progress=0.5,
            fail_message="GPU out of memory"
        ))

        # Reset between tests
        provider.reset_configs()
    """

    def __init__(self):
        self._status = ProviderStatus.DISCONNECTED
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._tool_configs: Dict[str, TestToolConfig] = {}
        self._assets: Dict[str, bytes] = {}
        self._cancelled_requests: set = set()

    @property
    def provider_id(self) -> str:
        return "test"

    @property
    def provider_name(self) -> str:
        return "Test Provider"

    @property
    def provider_type(self) -> str:
        return "builtin"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def max_concurrent(self) -> int:
        return 4

    async def connect(self) -> None:
        """Initialize the provider and register tools."""
        self._status = ProviderStatus.CONNECTING
        self._register_tools()
        self._status = ProviderStatus.CONNECTED

    async def disconnect(self) -> None:
        """Clean disconnect."""
        self._status = ProviderStatus.DISCONNECTED
        self._descriptors.clear()
        self._tool_configs.clear()
        self._assets.clear()
        self._cancelled_requests.clear()

    async def upload_asset(self, data: bytes, mime_type: str) -> str:
        """Upload an asset and return a reference ID."""
        asset_id = f"test_{uuid.uuid4().hex}"
        self._assets[asset_id] = data
        return asset_id

    async def download_asset(self, asset_id: str) -> bytes:
        """Download an asset by reference ID."""
        if asset_id not in self._assets:
            raise ValueError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    def configure_tool(self, tool_id: str, config: TestToolConfig) -> None:
        """Configure a tool's behavior for testing."""
        self._tool_configs[tool_id] = config

    def reset_configs(self) -> None:
        """Reset all tool configurations to defaults."""
        self._tool_configs.clear()
        self._cancelled_requests.clear()

    def _register_tools(self) -> None:
        """Register test tools."""
        # Text-to-image tool
        self._descriptors["text-to-image:test-model"] = ToolDescriptor(
            id="text-to-image:test-model",
            name="Test Text-to-Image",
            task_type="text-to-image",
            parameter_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string", "default": ""},
                    "width": {"type": "integer", "default": 512},
                    "height": {"type": "integer", "default": 512},
                    "steps": {
                        "type": "integer",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "cfg": {
                        "type": "number",
                        "default": 7.0,
                        "minimum": 1.0,
                        "maximum": 20.0,
                    },
                    "seed": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "format": "binary"},
                },
            },
            metadata={"generator_type": "test"},
        )

        # Image edit tool
        self._descriptors["image-to-image:test-edit"] = ToolDescriptor(
            id="image-to-image:test-edit",
            name="Test Image to Image",
            task_type="image-to-image",
            parameter_schema={
                "type": "object",
                "required": ["prompt", "input_images"],
                "properties": {
                    "prompt": {"type": "string"},
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string", "format": "file-path"},
                        "minItems": 1,
                        "maxItems": 3,
                        "x-control": "image_picker",
                    },
                    "strength": {
                        "type": "number",
                        "default": 0.75,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "seed": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "format": "binary"},
                },
            },
            metadata={"generator_type": "test"},
        )

        # Upscale tool
        self._descriptors["upscale-image:test-upscale"] = ToolDescriptor(
            id="upscale-image:test-upscale",
            name="Test Upscale",
            task_type="upscale-image",
            parameter_schema={
                "type": "object",
                "required": ["input_images"],
                "properties": {
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string", "format": "file-path"},
                        "minItems": 1,
                        "maxItems": 1,
                        "x-control": "image_picker",
                    },
                    "scale": {
                        "type": "integer",
                        "default": 2,
                        "enum": [2, 4],
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "format": "binary"},
                },
            },
            metadata={"generator_type": "test"},
        )

        # Image-to-video tool (outputs PNG for test simplicity)
        self._descriptors["image-to-video:test-i2v"] = ToolDescriptor(
            id="image-to-video:test-i2v",
            name="Test Image-to-Video",
            task_type="image-to-video",
            parameter_schema={
                "type": "object",
                "required": ["input_images"],
                "properties": {
                    "prompt": {"type": "string", "default": ""},
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string", "format": "file-path"},
                        "minItems": 1,
                        "maxItems": 2,
                        "x-control": "video_frame_picker",
                    },
                    "steps": {
                        "type": "integer",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "seed": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "format": "binary"},
                },
            },
            metadata={"generator_type": "test"},
        )

        # Inpaint tool
        self._descriptors["inpaint-image:test-inpaint"] = ToolDescriptor(
            id="inpaint-image:test-inpaint",
            name="Test Inpaint",
            task_type="inpaint-image",
            parameter_schema={
                "type": "object",
                "required": ["prompt", "input_images"],
                "properties": {
                    "prompt": {"type": "string"},
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string", "format": "file-path"},
                        "minItems": 1,
                        "maxItems": 1,
                        "x-control": "image_picker",
                    },
                    "mask": {"type": "string", "format": "file-path"},
                    "strength": {
                        "type": "number",
                        "default": 0.75,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "seed": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "format": "binary"},
                },
            },
            metadata={"generator_type": "test"},
        )

        # Second text-to-image tool (for hop & generate-more testing)
        self._descriptors["text-to-image:test-model-alt"] = ToolDescriptor(
            id="text-to-image:test-model-alt",
            name="Test Alt Text-to-Image",
            task_type="text-to-image",
            parameter_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string", "default": ""},
                    "width": {"type": "integer", "default": 768},
                    "height": {"type": "integer", "default": 768},
                    "steps": {
                        "type": "integer",
                        "default": 30,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "cfg": {
                        "type": "number",
                        "default": 7.0,
                        "minimum": 1.0,
                        "maximum": 20.0,
                    },
                    "seed": {
                        "type": "integer",
                        "minimum": 0,
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "format": "binary"},
                },
            },
            metadata={"generator_type": "test"},
        )

    async def list_tools(self) -> List[ToolDescriptor]:
        """Return all available test tools."""
        return list(self._descriptors.values())

    async def get_tool(self, tool_id: str) -> Optional[ToolDescriptor]:
        """Get a specific tool by ID."""
        return self._descriptors.get(tool_id)

    async def cancel_execution(self, request_id: str) -> bool:
        """Cancel an in-progress execution."""
        self._cancelled_requests.add(request_id)
        return True

    async def execute(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[ExecutionProgress], None]] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[ExecutionProgress | ExecutionResult]:
        """
        Execute a test tool with configurable behavior.

        Yields progress events at 0%, 25%, 50%, 75%, 100% then final result.
        """
        if tool_id not in self._descriptors:
            yield ExecutionResult(
                success=False,
                error=f"Unknown tool: {tool_id}",
            )
            return

        config = self._tool_configs.get(tool_id, TestToolConfig())
        request_id = request_id or str(uuid.uuid4())

        # Progress stages
        stages = [
            (0.0, "initializing", "Starting..."),
            (0.25, "preparing", "Preparing model..."),
            (0.5, "generating", "Generating..."),
            (0.75, "finalizing", "Finalizing..."),
            (1.0, "complete", "Complete"),
        ]

        start_time = asyncio.get_event_loop().time()

        for progress, stage, message in stages:
            # Check for cancellation
            if request_id in self._cancelled_requests:
                self._cancelled_requests.discard(request_id)
                yield ExecutionResult(
                    success=False,
                    error="Cancelled by user",
                )
                return

            # Check for configured failure
            if config.should_fail and progress >= config.fail_at_progress:
                yield ExecutionResult(
                    success=False,
                    error=config.fail_message,
                )
                return

            yield ExecutionProgress(
                progress=progress,
                stage=stage,
                message=message,
            )

            if progress < 1.0:
                await asyncio.sleep(config.delay_per_stage)

        # Generate dummy output
        generation_time = asyncio.get_event_loop().time() - start_time
        seed = parameters.get("seed", 12345)
        output_bytes = self._generate_dummy_image(config, seed)

        # Save to output_path if specified
        if output_path:
            with open(output_path, "wb") as f:
                f.write(output_bytes)

        yield ExecutionResult(
            success=True,
            output_data=output_bytes,
            generation_time=generation_time,
            actual_seed=seed,
            metadata={
                "test_tool": True,
                "tool_id": tool_id,
                "output_path": output_path,
            },
        )

    def _generate_dummy_image(self, config: TestToolConfig, seed: int) -> bytes:
        """Generate a deterministic dummy PNG image."""
        width, height = config.output_size

        # Use seed to vary the color slightly
        r, g, b = config.output_color
        r = (r + seed) % 256
        g = (g + seed * 2) % 256
        b = (b + seed * 3) % 256

        # Create a simple colored image
        img = Image.new("RGB", (width, height), (r, g, b))

        # Add a simple pattern based on seed
        pixels = img.load()
        for x in range(width):
            for y in range(height):
                if (x + y + seed) % 10 == 0:
                    pixels[x, y] = (255, 255, 255)

        # Convert to PNG bytes
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()


# Singleton instance for tests
_test_provider: Optional[TestToolProvider] = None


def get_test_provider() -> TestToolProvider:
    """Get the singleton TestToolProvider instance."""
    global _test_provider
    if _test_provider is None:
        _test_provider = TestToolProvider()
    return _test_provider


def reset_test_provider() -> None:
    """Reset the singleton (for test isolation)."""
    global _test_provider
    _test_provider = None

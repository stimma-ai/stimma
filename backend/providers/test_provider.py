"""
Test Provider - configurable mock provider for integration tests.

Provides realistic tool execution simulation with:
- Configurable progress events
- Configurable success/failure behavior
- Deterministic dummy outputs for image, video, and audio task types

Image outputs render their own generation parameters (tool id, prompt, seed,
dimensions) onto the canvas and embed the full parameter dict as a PNG text
chunk under the key "stimma:test_params", so integration tests and eval
graders can verify exactly what flowed through the pipeline. Video and audio
outputs are minimal valid container files; their parameters are available in
the ExecutionResult metadata and the media item's generation metadata.
"""

import asyncio
import base64
import io
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

from .base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)

# Minimal valid media containers for non-image outputs (generated with ffmpeg,
# FLAC padding stripped). Deterministic and dependency-free.
_STUB_FLAC_B64 = (
    "ZkxhQwAAACICQAJAAAANAAANAfQA8AAAAZBrQxvy2nyTErPlwh5n9lkbhAAADgYAAABmZm1wZWcAAAAA//h0CAABjyQAAAB9Xw=="
)
_STUB_MP4_B64 = (
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAAAyJtZGF0AAACrQYF//+p3EXpvebZSLeWLNgg2SPu"
    "73gyNjQgLSBjb3JlIDE2NCByMzEwOCAzMWUxOWY5IC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMt"
    "MjAyMyAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9j"
    "az0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9MS4wMDowLjAwIG1peGVkX3Jl"
    "Zj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0"
    "X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTIgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFk"
    "cz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZy"
    "YW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWln"
    "aHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWluPTggc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJjX2xvb2thaGVhZD00"
    "MCByYz1jcmYgbWJ0cmVlPTEgY3JmPTIzLjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlv"
    "PTEuNDAgYXE9MToxLjAwAIAAAAAfZYiEABH//veIHzKI2rXchHnrFT9RiMZbXPnZroYp3wAAAApBmiRsQ//+qZ00AAAACEGe"
    "QniH/wTFAAAACAGeYXRDvwW8AAAACAGeY2pDvwW9AAAAEEGaZUmoQWiZTAh3//6pnTUAAANdbW9vdgAAAGxtdmhkAAAAAAAA"
    "AAAAAAAAAAAD6AAAAu4AAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAqx0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAAu4AAAAAAAAAAAAA"
    "AAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAEAAAABAAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAA"
    "AAEAAALuAAAQAAABAAAAAAIkbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAABAAAAAMABVxAAAAAAALWhkbHIAAAAAAAAAAHZp"
    "ZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABz21pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYA"
    "AAAAAAAAAQAAAAx1cmwgAAAAAQAAAY9zdGJsAAAAv3N0c2QAAAAAAAAAAQAAAK9hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAA"
    "AAAAAEAAQABIAAAASAAAAAAAAAABDExhdmMgbGlieDI2NAAAAAAAAAAAAAAAAAAAAAAAAAAAGP//AAAANWF2Y0MBZAAK/+EA"
    "GGdkAAqs2UQmwEQAAAMABAAAAwBAPEiWWAEABmjr48siwP34+AAAAAAQcGFzcAAAAAEAAAABAAAAFGJ0cnQAAAAAAAAhFQAA"
    "AAAAAAAYc3R0cwAAAAAAAAABAAAABgAACAAAAAAUc3RzcwAAAAAAAAABAAAAAQAAAEBjdHRzAAAAAAAAAAYAAAABAAAQAAAA"
    "AAEAACgAAAAAAQAAEAAAAAABAAAAAAAAAAEAAAgAAAAAAQAAEAAAAAAcc3RzYwAAAAAAAAABAAAAAQAAAAYAAAABAAAALHN0"
    "c3oAAAAAAAAAAAAAAAYAAALUAAAADgAAAAwAAAAMAAAADAAAABQAAAAUc3RjbwAAAAAAAAABAAAAMAAAAD11ZHRhAAAANW1l"
    "dGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAACGlsc3Q="
)

_VIDEO_TASK_TYPES = {
    "image-to-video",
    "text-to-video",
    "video-to-video",
    "upscale-video",
    "video-stitch",
    "video-extend",
    "lip-sync",
}
_AUDIO_TASK_TYPES = {"text-to-audio", "text-to-music", "text-to-speech"}

# Standard ~1MP generation buckets (SDXL convention, both orientations).
# Declared as x-allowed-dimensions on width so call_tool's aspect snap
# enforces the resolution policy in code, like well-configured real tools.
_STANDARD_DIMENSIONS = [
    [1024, 1024], [1152, 896], [896, 1152], [1216, 832], [832, 1216],
    [1344, 768], [768, 1344], [1536, 640], [640, 1536],
]

# LoRA stack input, matching the {path, weight} shape call_tool/params_from
# emit (see agent/v2/tools/library.py _normalize_loras_for_input). The path
# enum is how tools advertise their available LoRAs — _resolve_lora_paths
# fuzzy-matches short names ("inkwash") against it, like real tools.
_LORAS_SCHEMA = {
    "type": "array",
    "default": [],
    "items": {
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "enum": [
                    "styles/inkwash-v2.safetensors",
                    "styles/watercolor-v2.safetensors",
                    "detail/crisp-detail-xl.safetensors",
                ],
            },
            "weight": {"type": "number", "default": 1.0, "minimum": -2.0, "maximum": 2.0},
        },
    },
    "x-control": "lora_picker",
}


@dataclass
class TestToolConfig:
    """Configuration for test tool behavior."""

    delay_per_stage: float = 0.01  # Seconds between progress events
    should_fail: bool = False
    fail_at_progress: float = 0.5  # Progress value at which to fail (0.0-1.0)
    fail_message: str = "Simulated failure"
    # Marker-based failure: fail only when the prompt contains this substring
    # (case-insensitive). Unlike should_fail, this is safe to leave configured
    # while other tests/eval trials share the provider concurrently — only
    # requests that opt in via their prompt are affected.
    fail_if_prompt_contains: Optional[str] = None
    fail_count: Optional[int] = None  # With fail_if_prompt_contains: fail only the first N matching calls
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
        self._marker_fail_counts: Dict[tuple, int] = {}
        # Additive marker rules: (marker, fail_count, message) per tool.
        # Unlike configure_tool (replace semantics), multiple independent
        # tests/eval tasks can arm rules on the same tool concurrently.
        self._marker_rules: Dict[str, list] = {}

    def add_marker_failure(
        self,
        tool_id: str,
        marker: str,
        fail_count: Optional[int] = None,
        message: str = "Simulated provider failure",
    ) -> None:
        """Arm an additive prompt-marker failure rule on a tool."""
        self._marker_rules.setdefault(tool_id, []).append((marker, fail_count, message))

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
        self._marker_fail_counts.clear()
        self._marker_rules.clear()

    def _register_tools(self) -> None:
        """Register test tools."""
        # Text-to-image tool
        self._descriptors["text-to-image:test-model"] = ToolDescriptor(
            id="text-to-image:test-model",
            name="Test Text-to-Image",
            description="Fast draft-quality image generation for quick iteration.",
            task_type="text-to-image",
            parameter_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string", "default": ""},
                    "width": {
                        "type": "integer",
                        "default": 1024,
                        "description": "Output width. Snapped to the nearest standard ~1MP bucket by aspect ratio.",
                        "x-allowed-dimensions": _STANDARD_DIMENSIONS,
                    },
                    "height": {"type": "integer", "default": 1024},
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
                    "scheduler": {
                        "type": "string",
                        "default": "euler",
                        "enum": ["euler", "karras", "ddim", "dpmpp-2m"],
                    },
                    "loras": _LORAS_SCHEMA,
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
            description="Slow, maximum-quality image generation for final output.",
            task_type="text-to-image",
            parameter_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string", "default": ""},
                    "width": {
                        "type": "integer",
                        "default": 1024,
                        "description": "Output width. Snapped to the nearest standard ~1MP bucket by aspect ratio.",
                        "x-allowed-dimensions": _STANDARD_DIMENSIONS,
                    },
                    "height": {"type": "integer", "default": 1024},
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
                    "scheduler": {
                        "type": "string",
                        "default": "euler",
                        "enum": ["euler", "karras", "ddim", "dpmpp-2m"],
                    },
                    "loras": _LORAS_SCHEMA,
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

        self._register_extended_tools()

    def _register_extended_tools(self) -> None:
        """Register fake tools for the remaining media task types.

        Schemas follow tasks/schemas.py TASK_SCHEMA_REQUIREMENTS for each task
        type. Video tools output a stub MP4, audio tools a stub FLAC.
        """
        _prompt = {"prompt": {"type": "string"}}
        _neg = {"negative_prompt": {"type": "string", "default": ""}}
        _seed = {"seed": {"type": "integer", "minimum": 0}}
        _images = {
            "input_images": {
                "type": "array",
                "items": {"type": "string", "format": "file-path"},
                "minItems": 1,
                "maxItems": 4,
                "x-control": "image_picker",
            }
        }
        _videos = {
            "input_videos": {
                "type": "array",
                "items": {"type": "string", "format": "file-path"},
                "minItems": 1,
                "maxItems": 4,
                "x-control": "video_picker",
            }
        }
        _size = {
            "width": {"type": "integer", "default": 512},
            "height": {"type": "integer", "default": 512},
        }
        _duration = {"duration": {"type": "number", "default": 5.0, "minimum": 0.5, "maximum": 60.0}}

        specs = [
            ("text-to-video:test-t2v", "Test Text-to-Video", "text-to-video",
             {**_prompt, **_neg, **_size, **_duration, **_seed}, ["prompt"]),
            ("remove-background:test-rmbg", "Test Background Removal", "remove-background",
             {**_images}, ["input_images"]),
            ("outpaint-image:test-outpaint", "Test Outpaint", "outpaint-image",
             {**_images, **_prompt, **_neg, **_seed,
              "expand_left": {"type": "integer", "default": 0, "minimum": 0,
                              "description": "Pixels of new canvas to add on the left edge."},
              "expand_right": {"type": "integer", "default": 0, "minimum": 0,
                               "description": "Pixels of new canvas to add on the right edge."},
              "expand_top": {"type": "integer", "default": 0, "minimum": 0,
                             "description": "Pixels of new canvas to add on the top edge."},
              "expand_bottom": {"type": "integer", "default": 0, "minimum": 0,
                                "description": "Pixels of new canvas to add on the bottom edge. "
                                               "Output size is input size plus the expands — for a target "
                                               "aspect ratio, compute the padding from the input dimensions "
                                               "(e.g. 1024x1024 -> 16:9 needs 1024*16/9-1024 = 796 total horizontal)."}},
             ["input_images"]),
            ("filter:test-filter", "Test Filter", "filter",
             {**_images, "intensity": {"type": "number", "default": 1.0, "minimum": 0.0, "maximum": 2.0}},
             ["input_images"]),
            ("upscale-video:test-upscale-video", "Test Video Upscale", "upscale-video",
             {**_videos, "scale": {"type": "integer", "default": 2, "enum": [2, 4]}},
             ["input_videos"]),
            ("video-to-video:test-v2v", "Test Video to Video", "video-to-video",
             {**_videos, **_prompt, **_neg, **_seed}, ["input_videos"]),
            ("video-extend:test-extend", "Test Video Extend", "video-extend",
             {**_videos, **_prompt, **_neg, **_duration, **_seed}, ["input_videos"]),
            ("video-stitch:test-stitch", "Test Video Stitch", "video-stitch",
             {**_videos, **_prompt, **_neg}, ["input_videos"]),
            ("text-to-speech:test-tts", "Test Text-to-Speech", "text-to-speech",
             {**_prompt,
              "voice": {"type": "string", "default": "narrator", "enum": ["narrator", "casual", "formal"]},
              "speed": {"type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.0}},
             ["prompt"]),
            ("text-to-music:test-music", "Test Text-to-Music", "text-to-music",
             {**_prompt, **_duration,
              "lyrics": {"type": "string", "default": ""},
              "instrumental": {"type": "boolean", "default": True}},
             ["prompt"]),
            ("text-to-audio:test-sfx", "Test Sound Effects", "text-to-audio",
             {**_prompt, **_duration}, ["prompt"]),
        ]

        for tool_id, name, task_type, properties, required in specs:
            self._descriptors[tool_id] = ToolDescriptor(
                id=tool_id,
                name=name,
                task_type=task_type,
                parameter_schema={
                    "type": "object",
                    "required": required,
                    "properties": properties,
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "assets": {"type": "array", "items": {"type": "string", "format": "binary"}},
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

        # Marker-based failure: triggers only for prompts containing a
        # marker, so rules can stay armed while unrelated requests share the
        # provider. fail_count limits failures per unique prompt text — a
        # verbatim retry of the same prompt then succeeds (transient-error
        # simulation).
        prompt_text = str(parameters.get("prompt") or "").lower()
        rules = list(self._marker_rules.get(tool_id, []))
        if config.fail_if_prompt_contains:
            rules.append((config.fail_if_prompt_contains, config.fail_count, config.fail_message))
        # fail_count scope: the caller's output folder when available (one
        # transient failure per consumer, regardless of prompt rewording),
        # falling back to the exact prompt text.
        import os as _os
        count_scope = _os.path.dirname(output_path) if output_path else str(parameters.get("prompt") or "")
        for marker, fail_count, message in rules:
            if marker.lower() not in prompt_text:
                continue
            if fail_count is not None:
                key = (tool_id, marker, count_scope)
                seen = self._marker_fail_counts.get(key, 0)
                if seen >= fail_count:
                    continue
                self._marker_fail_counts[key] = seen + 1
            yield ExecutionProgress(progress=0.0, stage="initializing", message="Starting...")
            yield ExecutionResult(success=False, error=message)
            return

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
        task_type = self._descriptors[tool_id].task_type or ""
        if task_type in _VIDEO_TASK_TYPES:
            output_bytes = base64.b64decode(_STUB_MP4_B64)
        elif task_type in _AUDIO_TASK_TYPES:
            output_bytes = base64.b64decode(_STUB_FLAC_B64)
        else:
            output_bytes = self._generate_dummy_image(config, seed, tool_id, parameters)

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
                "parameters": parameters,
            },
        )

    def _resolve_output_size(self, config: TestToolConfig, tool_id: str, parameters: Dict[str, Any]) -> tuple:
        """Output dimensions: explicit width/height params win; image-input
        tools inherit their first input's dimensions (times scale for
        upscale); otherwise the configured default."""
        width = parameters.get("width")
        height = parameters.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return (width, height)

        inputs = parameters.get("input_images") or []
        if inputs:
            try:
                with Image.open(inputs[0]) as src:
                    w, h = src.size
                scale = parameters.get("scale", 1)
                if tool_id.startswith("upscale-image:") and isinstance(scale, int):
                    return (w * scale, h * scale)
                if tool_id.startswith("outpaint-image:"):
                    return (
                        w + int(parameters.get("expand_left") or 0) + int(parameters.get("expand_right") or 0),
                        h + int(parameters.get("expand_top") or 0) + int(parameters.get("expand_bottom") or 0),
                    )
                return (w, h)
            except Exception:
                pass
        return config.output_size

    def _generate_dummy_image(
        self,
        config: TestToolConfig,
        seed: int,
        tool_id: str = "",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Generate a deterministic dummy PNG image.

        The generation parameters are rendered onto the canvas and embedded as
        a PNG text chunk ("stimma:test_params") so tests and eval graders can
        verify what flowed through the pipeline end to end.
        """
        parameters = parameters or {}
        width, height = self._resolve_output_size(config, tool_id, parameters)

        # Deterministic abstract composition rather than a flat rectangle:
        # vision-capable agents inspect their outputs, and a solid color reads
        # as a broken generation — they then reject the tool and route around
        # it, which is not the behavior under test.
        r, g, b = config.output_color
        base = ((r + seed) % 256, (g + seed * 2) % 256, (b + seed * 3) % 256)
        other = ((r + seed * 5 + 90) % 256, (g + seed * 7 + 40) % 256, (b + seed * 11 + 160) % 256)

        img = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(img, "RGBA")
        for y in range(height):
            t = y / max(1, height - 1)
            row = tuple(int(base[i] * (1 - t) + other[i] * t) for i in range(3))
            draw.line([(0, y), (width, y)], fill=row)
        rng_vals = [(seed * (i + 3) * 2654435761) % 2**32 for i in range(24)]
        for i in range(5):
            cx = rng_vals[i * 4] % width
            cy = rng_vals[i * 4 + 1] % height
            rad = max(8, (rng_vals[i * 4 + 2] % max(16, width // 3)))
            col = ((rng_vals[i * 4 + 3] % 200) + 30, (rng_vals[i * 4 + 3] // 7 % 200) + 30,
                   (rng_vals[i * 4 + 3] // 41 % 200) + 30, 110)
            draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col)

        self._draw_params(img, tool_id, seed, parameters)

        serializable = {k: v for k, v in parameters.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        info = PngInfo()
        info.add_text(
            "stimma:test_params",
            json.dumps({"tool_id": tool_id, "seed": seed, "parameters": serializable}, default=str),
        )

        buffer = io.BytesIO()
        img.save(buffer, format="PNG", pnginfo=info)
        return buffer.getvalue()

    def _draw_params(self, img: Image.Image, tool_id: str, seed: int, parameters: Dict[str, Any]) -> None:
        """Render key generation params onto the image for visual verification."""
        width, height = img.size
        if width < 48 or height < 32:
            return
        draw = ImageDraw.Draw(img)
        lines = [tool_id or "test", f"seed={seed} {width}x{height}"]
        prompt = parameters.get("prompt")
        if prompt:
            # Wrap the prompt to the canvas width (default font is ~6px/char)
            chars = max(8, (width - 8) // 6)
            text = str(prompt)
            lines.extend(text[i:i + chars] for i in range(0, min(len(text), chars * 8), chars))
        line_height = 12
        band_height = min(height, len(lines) * line_height + 8)
        draw.rectangle([0, 0, width, band_height], fill=(0, 0, 0))
        y = 4
        for line in lines:
            if y + line_height > height:
                break
            draw.text((4, y), line, fill=(255, 255, 255))
            y += line_height


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

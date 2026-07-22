"""
Lightweight Provider - hosts fast, in-process image manipulation tools.

These tools don't go through the generation queue. They execute directly
and return results immediately. Examples:
- detect_objects (SAM3)
"""

import asyncio
import io
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from PIL import Image

from .base import (
    ExecutionProgress,
    ExecutionResult,
    ProviderStatus,
    ToolDescriptor,
    ToolProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class LightweightTool:
    """Definition of a lightweight tool."""
    id: str
    name: str
    description: str
    task_type: str
    parameter_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    execute_fn: Callable  # async function to execute the tool
    metadata: Dict[str, Any] = None  # Optional tool-specific metadata


class LightweightProvider(ToolProvider):
    """
    Provider for fast, in-process image manipulation tools.

    These tools execute directly without going through the generation queue.
    They're ideal for quick operations like background removal, cropping, etc.
    """

    def __init__(self):
        self._status = ProviderStatus.DISCONNECTED
        self._tools: Dict[str, LightweightTool] = {}
        self._descriptors: Dict[str, ToolDescriptor] = {}
        self._assets: Dict[str, bytes] = {}  # In-memory asset storage

    @property
    def provider_id(self) -> str:
        return "builtin"

    @property
    def provider_name(self) -> str:
        return "Built-in Tools"

    @property
    def provider_type(self) -> str:
        return "builtin"

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def max_concurrent(self) -> int:
        return 4  # These are fast, can run several in parallel

    async def connect(self) -> None:
        """Initialize the provider and register tools."""
        self._status = ProviderStatus.CONNECTING

        try:
            self._register_tools()
            self._status = ProviderStatus.CONNECTED
            logger.info(
                f"LightweightProvider connected with {len(self._tools)} tools"
            )
        except Exception as e:
            self._status = ProviderStatus.ERROR
            logger.error(f"Failed to connect LightweightProvider: {e}")
            raise

    async def disconnect(self) -> None:
        """Clean disconnect."""
        self._status = ProviderStatus.DISCONNECTED
        self._tools.clear()
        self._descriptors.clear()
        self._assets.clear()
        logger.info("LightweightProvider disconnected")

    async def upload_asset(self, data: bytes, mime_type: str) -> str:
        """Upload an asset and return a reference ID."""
        asset_id = f"lightweight_{uuid.uuid4().hex}"
        self._assets[asset_id] = data
        return asset_id

    async def download_asset(self, asset_id: str) -> bytes:
        """Download an asset by reference ID."""
        if asset_id not in self._assets:
            raise ValueError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    def _register_tools(self) -> None:
        """Register all lightweight tools."""
        # Detect Objects (returns all detections for find_objects tool)
        self._register_tool(LightweightTool(
            id="detect-objects",
            name="Detect Objects",
            description="Detect and locate objects in an image using AI segmentation. Returns bounding boxes and confidence scores for ALL detected objects.",
            task_type="detect-objects",
            parameter_schema={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "What to find, as a short noun phrase ('cat', 'child', 'red car'). SAM3 matches object categories, not scene descriptions — a long descriptive sentence returns zero detections. On zero results, broaden the noun ('girl' → 'child' → 'person'); each call is a full ~10s CPU inference, so refine one phrasing at a time rather than sweeping many.",
                        "x-label": "Subject",
                    },
                    "index": {
                        "type": "integer",
                        "default": 0,
                        "minimum": 0,
                        "maximum": 10,
                        "x-label": "Detection Index",
                        "x-step": 1,
                        "description": "Which detection to use if multiple found (0 = highest confidence)",
                    },
                    "confidence_threshold": {
                        "type": "number",
                        "default": 0.3,
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "x-label": "Confidence",
                        "x-step": 0.05,
                        "description": "Minimum confidence score for detections",
                    },
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string", "format": "file-path"},
                        "minItems": 1,
                        "maxItems": 1,
                        "x-control": "image_picker",
                        "description": "Input image to analyze",
                    },
                },
                "required": ["subject", "input_images"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "detections": {
                        "type": "array",
                        "description": "Detected objects, sorted by score: {label, bbox: {x, y, width, height} (pixels in the original image), score, area_percent}",
                    },
                    "count": {
                        "type": "integer",
                        "description": "Number of detections",
                    },
                    "image_size": {
                        "type": "object",
                        "description": "Original image dimensions: {width, height} in pixels — bbox coordinates are in this frame",
                    },
                },
            },
            execute_fn=self._execute_detect_objects,
            # metadata_only: returns data (detections), not media — the agent
            # executes it in-process instead of through the generation queue,
            # which assumes every job produces an output file to ingest.
            metadata={"agent_only": True, "metadata_only": True},
        ))

        self._register_filter_tools()
        self._register_darkroom_tools()

    def _register_filter_tools(self) -> None:
        """Register the built-in image filters (task type "filter").

        One tool per filter definition — the same Filters/Levels/Effects set
        the image editor exposes, shared via filters.defs. Being ordinary
        catalog tools makes them first-class capabilities: the chat agent,
        flows, ToolView, and post-processing chains all invoke them through
        the normal tool path.
        """
        from filters.defs import CHAIN_FILTER_DEFS
        from filters.schemas import FILTER_OUTPUT_SCHEMA, build_filter_parameter_schema

        for filter_def in CHAIN_FILTER_DEFS:
            self._register_tool(LightweightTool(
                id=filter_def["id"],
                name=filter_def["label"],
                description=filter_def.get("description") or filter_def["label"],
                task_type="filter",
                parameter_schema=build_filter_parameter_schema(filter_def),
                output_schema=FILTER_OUTPUT_SCHEMA,
                execute_fn=self._make_filter_executor(filter_def["id"]),
            ))

    def _register_darkroom_tools(self) -> None:
        """Register the Darkroom film emulation / grading tools.

        Built on the vendored ComfyUI-Darkroom engine (MIT, Jérémie Louvaert)
        — see darkroom/vendor/ATTRIBUTION.md. Same shape as the built-in
        filters: task type "filter", image in → image out.
        """
        from darkroom.tools import ATTRIBUTION, DARKROOM_TOOLS
        from filters.schemas import FILTER_OUTPUT_SCHEMA

        for tool_def in DARKROOM_TOOLS:
            self._register_tool(LightweightTool(
                id=tool_def.id,
                name=tool_def.name,
                description=tool_def.description,
                task_type="filter",
                parameter_schema=tool_def.parameter_schema,
                output_schema=FILTER_OUTPUT_SCHEMA,
                execute_fn=self._make_darkroom_executor(tool_def),
                # description rides in metadata: ToolDescriptor has no
                # description field, and the frontend reads
                # tool.metadata.description (same convention as cloud tools).
                metadata={
                    "attribution": dict(ATTRIBUTION),
                    "description": tool_def.description,
                },
            ))

    def _make_darkroom_executor(self, tool_def) -> Callable:
        async def _execute(
            parameters: Dict[str, Any],
            job_id: str,
            progress_callback: Optional[Callable] = None,
        ) -> ExecutionResult:
            return await self._execute_darkroom(tool_def, parameters)
        return _execute

    async def _execute_darkroom(self, tool_def, parameters: Dict[str, Any]) -> ExecutionResult:
        """Run one Darkroom tool's stage pipeline over the input image."""
        import tempfile
        import time

        input_images = parameters.get("input_images", [])
        image_path = input_images[0] if input_images else None
        if not image_path or not Path(str(image_path)).exists():
            return ExecutionResult(success=False, error="No input media provided")

        started = time.perf_counter()

        def _apply() -> str:
            import os

            from utils.image_ops import open_oriented
            with open_oriented(image_path) as img:
                out = tool_def.run(parameters, img)
                fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix=f"{tool_def.id}_")
                os.close(fd)
                out.save(tmp_path, format="PNG")
                return tmp_path

        tmp_path = await asyncio.to_thread(_apply)

        return ExecutionResult(
            success=True,
            generation_time=time.perf_counter() - started,
            metadata={"output_path": tmp_path, "filter_id": tool_def.id},
        )

    def _make_filter_executor(self, filter_id: str) -> Callable:
        async def _execute(
            parameters: Dict[str, Any],
            job_id: str,
            progress_callback: Optional[Callable] = None,
        ) -> ExecutionResult:
            return await self._execute_filter(filter_id, parameters)
        return _execute

    def _register_tool(self, tool: LightweightTool) -> None:
        """Register a single lightweight tool."""
        self._tools[tool.id] = tool
        # Merge tool-specific metadata with default lightweight flag
        metadata = {"lightweight": True}
        if tool.metadata:
            metadata.update(tool.metadata)
        self._descriptors[tool.id] = ToolDescriptor(
            id=tool.id,
            name=tool.name,
            task_type=tool.task_type,
            parameter_schema=tool.parameter_schema,
            output_schema=tool.output_schema,
            metadata=metadata,
        )

    async def list_tools(self) -> List[ToolDescriptor]:
        """Return all available lightweight tools."""
        return list(self._descriptors.values())

    async def get_tool(self, tool_id: str) -> Optional[ToolDescriptor]:
        """Get a specific tool by ID."""
        return self._descriptors.get(tool_id)

    async def execute(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        output_path: Optional[str] = None,
        progress_callback: Optional[Callable[[ExecutionProgress], None]] = None,
        request_id: Optional[str] = None,
    ) -> AsyncIterator[ExecutionProgress | ExecutionResult]:
        """
        Execute a lightweight tool.

        Args:
            tool_id: Tool ID within this provider (e.g., "remove-background")
            parameters: All parameters including inputs - e.g., {"input_images": ["/path/to/image.png"], "subject": "cat"}
            output_path: Optional path to save output file
            request_id: Optional request ID for cancellation (unused by lightweight provider)
            progress_callback: Optional callback for progress updates
        """
        tool = self._tools.get(tool_id)
        if not tool:
            yield ExecutionResult(
                success=False,
                error=f"Unknown tool: {tool_id}",
            )
            return

        job_id = str(uuid.uuid4())

        # Report starting
        yield ExecutionProgress(
            progress=0.0,
            stage="starting",
            message=f"Starting {tool.name}...",
        )

        try:
            # Execute the tool with the single parameters dict
            result = await tool.execute_fn(parameters, job_id, progress_callback)

            # If output_path specified, move the result file there (tool
            # outputs land in temp files; the move is also the cleanup)
            if output_path and result.success and result.metadata.get("output_path"):
                import shutil
                from pathlib import Path
                src_path = result.metadata["output_path"]
                if Path(src_path).exists() and str(src_path) != str(output_path):
                    shutil.move(src_path, output_path)
                    result.metadata["output_path"] = output_path

            yield ExecutionProgress(
                progress=1.0,
                stage="complete",
                message="Complete",
            )

            yield result

        except Exception as e:
            logger.error(f"Lightweight tool {tool_id} failed: {e}", exc_info=True)
            yield ExecutionResult(
                success=False,
                error=str(e),
            )

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def _execute_filter(
        self,
        filter_id: str,
        parameters: Dict[str, Any],
    ) -> ExecutionResult:
        """Apply one built-in filter to the input image or video."""
        import tempfile
        import time

        from filters.defs import get_filter_def
        from filters.ops import apply_builtin_filter

        from utils.query_builder import VIDEO_FORMATS

        input_images = parameters.get("input_images", [])
        image_path = input_images[0] if input_images else None
        if not image_path or not Path(str(image_path)).exists():
            return ExecutionResult(success=False, error="No input media provided")

        settings = {
            k: v for k, v in parameters.items()
            if k not in ("input_images", "input_media_ids", "tool_id")
            and not k.startswith("_")
        }

        started = time.perf_counter()
        is_video = Path(str(image_path)).suffix.lstrip(".").lower() in VIDEO_FORMATS

        # Most filters accept both stills and video; a few (e.g. reverse) only
        # make sense on video — don't silently misapply them to a still.
        accepts = (get_filter_def(filter_id) or {}).get("accepts") or ["image", "video"]
        if not is_video and "image" not in accepts:
            return ExecutionResult(success=False, error=f"Filter '{filter_id}' does not support image input")
        if is_video and "video" not in accepts:
            return ExecutionResult(success=False, error=f"Filter '{filter_id}' does not support video input")

        def _apply_image() -> str:
            from utils.image_ops import open_oriented
            with open_oriented(image_path) as img:
                out = apply_builtin_filter(filter_id, img, settings)
                fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix=f"filter_{filter_id}_")
                import os
                os.close(fd)
                out.save(tmp_path, format="PNG")
                return tmp_path

        def _apply_video() -> str:
            import os

            from filters.video_ops import WHOLE_CLIP_VIDEO_FILTERS, apply_builtin_filter_video
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix=f"filter_{filter_id}_")
            os.close(fd)
            whole_clip = WHOLE_CLIP_VIDEO_FILTERS.get(filter_id)
            if whole_clip is not None:
                whole_clip(str(image_path), tmp_path, settings)
            else:
                # Per-frame application reuses apply_builtin_filter, which overlays
                # the filter def defaults — so pass the raw settings through.
                apply_builtin_filter_video(filter_id, str(image_path), tmp_path, settings)
            return tmp_path

        tmp_path = await asyncio.to_thread(_apply_video if is_video else _apply_image)

        return ExecutionResult(
            success=True,
            generation_time=time.perf_counter() - started,
            metadata={"output_path": tmp_path, "filter_id": filter_id},
        )

    async def _execute_detect_objects(
        self,
        parameters: Dict[str, Any],
        job_id: str,
        progress_callback: Optional[Callable] = None,
    ) -> ExecutionResult:
        """Detect and locate objects in an image using SAM3. Returns ALL detections."""
        from sam3_service import get_sam3_service

        input_images = parameters.get("input_images", [])
        image_path = input_images[0] if input_images else None
        if not image_path:
            return ExecutionResult(success=False, error="No input image provided")

        subject = parameters.get("subject")
        if not subject:
            return ExecutionResult(success=False, error="No subject specified")

        confidence_threshold = parameters.get("confidence_threshold", 0.3)

        # Run SAM3 segmentation
        sam3 = get_sam3_service()
        result = await sam3.segment(
            image_path=image_path,
            prompt=subject,
            confidence_threshold=confidence_threshold,
        )

        if result.error:
            return ExecutionResult(success=False, error=f"Segmentation failed: {result.error}")

        # Build list of all detections
        detections = []
        for detection in result.detections:
            detections.append({
                "label": subject,
                "bbox": {
                    "x": detection.bbox.x,
                    "y": detection.bbox.y,
                    "width": detection.bbox.width,
                    "height": detection.bbox.height,
                },
                "score": round(detection.score, 3),
                "area_percent": round(detection.area_percent, 2),
            })

        # Sort by score descending
        detections.sort(key=lambda x: x["score"], reverse=True)

        return ExecutionResult(
            success=True,
            metadata={
                "count": len(detections),
                "detections": detections,
                "subject": subject,
                "image_size": {
                    "width": result.original_width,
                    "height": result.original_height,
                },
            },
        )


# Singleton instance
_lightweight_provider: Optional[LightweightProvider] = None


def get_lightweight_provider() -> LightweightProvider:
    """Get the singleton LightweightProvider instance."""
    global _lightweight_provider
    if _lightweight_provider is None:
        _lightweight_provider = LightweightProvider()
    return _lightweight_provider

"""Mask assistant routes for AI-powered mask editing.

Segmentation only: natural-language mask commands are interpreted by the
ToolView prompt agent (mask_subject / unmask_subject / expand_mask / ... in
prompt_agent_tools.py), which calls /segment directly.
"""
import asyncio
import base64
import hashlib
import io
import threading
import time
from typing import List, Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from PIL import Image

from core.logging import get_logger
from sam3_service import get_sam3_service

router = APIRouter(prefix="/api/mask", tags=["mask"])
log = get_logger(__name__)


# --- Request/Response Models ---

class SegmentRequest(BaseModel):
    image_path: str
    prompt: str
    confidence: float = 0.2
    return_all_above_threshold: bool = False  # If true, return all detections above confidence
    threshold: float = 0.7  # Threshold for returning multiple masks


class SegmentResponse(BaseModel):
    success: bool
    mask_data_url: Optional[str] = None  # Base64 RGBA PNG (alpha=0 = inpaint area) - best match
    mask_data_urls: List[str] = []  # All masks above threshold when return_all_above_threshold=True
    detections_count: int = 0
    best_confidence: float = 0.0
    error: Optional[str] = None


def _convert_grayscale_to_rgba(mask_data: bytes) -> bytes:
    """
    Convert SAM3 grayscale mask to RGBA format expected by MaskEditor.

    SAM3: white (255) = detected object
    MaskEditor: alpha=0 = inpaint area, alpha=255 = preserve
    """
    img = Image.open(io.BytesIO(mask_data))

    # Convert to grayscale if not already
    if img.mode != 'L':
        img = img.convert('L')

    # White = detected = inpaint (transparent white); else preserve (opaque black).
    hit = np.asarray(img) > 128
    rgba_arr = np.zeros((img.height, img.width, 4), dtype=np.uint8)
    rgba_arr[..., 3] = 255
    rgba_arr[hit] = (255, 255, 255, 0)
    rgba = Image.fromarray(rgba_arr, mode="RGBA")

    # Convert to PNG bytes
    output = io.BytesIO()
    rgba.save(output, format='PNG')
    return output.getvalue()


# --- Editor selection endpoint ---
#
# /select serves the image editor's AI selection gestures (prompt-to-mask,
# click-to-mask). It differs from /segment in that the image arrives as pixels
# (the editor's composite exists only client-side), and masks return in the
# selection-canvas convention: white-on-transparent RGBA, alpha = selected.
#
# Prompt mode (concept model): every instance of a named concept, above
# confidence, one detection each. Point mode (tracker model): the object under
# a click, returned at EVERY granularity the tracker offers (largest area
# first) so the editor can default to the object and cycle finer on repeated
# clicks without another request. Intent mode (BEN2 Base): one continuous
# whole-subject alpha, or its exact alpha complement for the background. Sky
# intent uses the dedicated SkyWater semantic pass and guided refinement.

class SelectRequest(BaseModel):
    image_data_url: str  # PNG/JPEG data URL of the composite being selected over
    request_id: Optional[str] = Field(
        default=None, min_length=1, max_length=128,
    )  # Correlates exact backend progress with this UI request
    prompt: Optional[str] = None  # text mode: select every instance of a concept
    point: Optional[dict] = None  # click mode: {x, y} normalized 0-1; one object
    intent: Optional[Literal["subject", "background", "sky"]] = None
    confidence: float = 0.5
    max_detections: int = 8

    @model_validator(mode="after")
    def exactly_one_selector(self):
        selectors = (
            self.point is not None,
            self.prompt is not None,
            self.intent is not None,
        )
        if sum(selectors) != 1:
            raise ValueError("Provide exactly one of point, prompt, or intent")
        if self.prompt is not None and not self.prompt.strip():
            raise ValueError("Prompt must not be blank")
        return self


class SelectDetection(BaseModel):
    mask_data_url: str  # white-on-transparent RGBA PNG, alpha = selected
    score: float
    bbox: dict  # {x, y, width, height} in sent-image pixels


class SelectResponse(BaseModel):
    success: bool
    detections: List[SelectDetection] = []
    error: Optional[str] = None


SelectProgressStage = Literal[
    "starting", "downloading_model", "loading", "processing_image", "selecting",
]


class SelectProgressResponse(BaseModel):
    stage: SelectProgressStage


_select_progress_lock = threading.Lock()
_select_progress: dict[str, tuple[str, str, float]] = {}
_SELECT_PROGRESS_TTL_SECONDS = 10 * 60


def _register_select_progress(
    request_id: Optional[str], mode: str, cache_key: str,
) -> None:
    if not request_id:
        return
    now = time.monotonic()
    with _select_progress_lock:
        expired = [
            key for key, (_, _, created) in _select_progress.items()
            if now - created > _SELECT_PROGRESS_TTL_SECONDS
        ]
        for key in expired:
            _select_progress.pop(key, None)
        _select_progress[request_id] = (mode, cache_key, now)


@router.get("/select/progress/{request_id}", response_model=SelectProgressResponse)
async def select_progress(request_id: str):
    """Report the real model/download/encode phase of an editor selection."""
    with _select_progress_lock:
        entry = _select_progress.get(request_id)
    if entry is None:
        return SelectProgressResponse(stage="starting")

    mode, cache_key, _ = entry
    try:
        if mode == "point":
            from sam3_tracker_service import get_sam3_tracker_service
            stage = get_sam3_tracker_service().selection_stage(cache_key)
        elif mode == "prompt":
            stage = get_sam3_service().selection_stage(cache_key)
        elif mode == "intent":
            from ben2_service import get_ben2_service
            stage = get_ben2_service().selection_stage(cache_key)
        elif mode == "sky":
            from skywater_service import get_skywater_service
            stage = get_skywater_service().selection_stage(cache_key)
        else:
            stage = "starting"
    except Exception as exc:
        log.debug(f"Could not read selection progress: {exc}")
        stage = "starting"
    return SelectProgressResponse(stage=stage)


def _decode_data_url(data_url: str) -> bytes:
    header, _, payload = data_url.partition(",")
    if not payload or ";base64" not in header:
        raise ValueError("Expected a base64 image data URL")
    return base64.b64decode(payload)


def _mask_png_to_selection_rgba(mask_png: bytes) -> str:
    """SAM3 grayscale mask (white = object) -> white-on-transparent RGBA data URL."""
    gray = np.asarray(Image.open(io.BytesIO(mask_png)).convert("L"))
    rgba = np.zeros((*gray.shape, 4), dtype=np.uint8)
    rgba[gray > 128] = (255, 255, 255, 255)
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _alpha_to_selection_rgba(alpha: np.ndarray) -> str:
    """Continuous grayscale alpha -> white RGBA selection without thresholding."""
    alpha = np.asarray(alpha, dtype=np.uint8)
    if alpha.ndim != 2:
        raise ValueError(f"Expected a 2D alpha mask, got {alpha.shape}")
    rgba = np.full((*alpha.shape, 4), 255, dtype=np.uint8)
    rgba[:, :, 3] = alpha
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _alpha_bbox(alpha: np.ndarray) -> dict:
    """Bounding box metadata for one continuous selection mask."""
    rows, cols = np.nonzero(alpha)
    if not len(rows):
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    x_min, x_max = int(cols.min()), int(cols.max())
    y_min, y_max = int(rows.min()), int(rows.max())
    return {
        "x": x_min,
        "y": y_min,
        "width": x_max - x_min + 1,
        "height": y_max - y_min + 1,
    }


class WarmRequest(BaseModel):
    image_data_url: str


@router.post("/select/warm")
async def warm_select(request: WarmRequest):
    """
    Pre-run the tracker's image encoder for an upcoming click. The editor
    fires this when the Object tool arms; the request returns once the
    embedding is cached, and the client ignores the response.
    """
    try:
        image_bytes = _decode_data_url(request.image_data_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad image data URL: {e}")
    from sam3_tracker_service import get_sam3_tracker_service
    await get_sam3_tracker_service().warm(image_bytes)
    return {"success": True}


@router.post("/select", response_model=SelectResponse)
async def select_mask(request: SelectRequest):
    """Segment the posted image for the editor's AI selection gestures."""
    try:
        image_bytes = _decode_data_url(request.image_data_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad image data URL: {e}")

    if request.point is not None:
        progress_mode = "point"
        progress_cache_key = hashlib.sha1(image_bytes).hexdigest()
    elif request.prompt:
        progress_mode = "prompt"
        progress_cache_key = hashlib.sha1(image_bytes).hexdigest()
    else:
        progress_mode = "sky" if request.intent == "sky" else "intent"
        progress_cache_key = hashlib.sha256(image_bytes).hexdigest()
    _register_select_progress(request.request_id, progress_mode, progress_cache_key)

    if request.intent is not None:
        if request.intent == "sky":
            from skywater_service import get_skywater_service
            sky_result = await get_skywater_service().sky_alpha(image_bytes)
            if sky_result.error:
                return SelectResponse(success=False, error=sky_result.error)
            if sky_result.alpha is None:
                return SelectResponse(success=False, error="Sky selection returned no alpha mask")
            if not np.any(sky_result.alpha):
                return SelectResponse(success=False, error="No sky found")
            return SelectResponse(
                success=True,
                detections=[SelectDetection(
                    mask_data_url=_alpha_to_selection_rgba(sky_result.alpha),
                    score=sky_result.score,
                    bbox=_alpha_bbox(sky_result.alpha),
                )],
            )

        from ben2_service import get_ben2_service
        ben2_result = await get_ben2_service().subject_alpha(image_bytes)
        if ben2_result.error:
            return SelectResponse(success=False, error=ben2_result.error)
        if ben2_result.alpha is None:
            return SelectResponse(success=False, error="BEN2 Base returned no alpha mask")

        # Background is defined as the exact 8-bit alpha complement. It must
        # never become a second model request or a SAM3 text prompt.
        alpha = (
            ben2_result.alpha
            if request.intent == "subject"
            else np.subtract(255, ben2_result.alpha, dtype=np.uint8)
        )
        return SelectResponse(
            success=True,
            detections=[SelectDetection(
                mask_data_url=_alpha_to_selection_rgba(alpha),
                score=1.0,
                bbox=_alpha_bbox(alpha),
            )],
        )
    if request.point is not None:
        from sam3_tracker_service import get_sam3_tracker_service
        result = await get_sam3_tracker_service().point_masks(
            image_bytes=image_bytes,
            points=[(float(request.point.get("x", 0)), float(request.point.get("y", 0)), 1)],
        )
    elif request.prompt:
        result = await get_sam3_service().segment(
            image_bytes=image_bytes,
            prompt=request.prompt,
            confidence_threshold=request.confidence,
            max_detections=request.max_detections,
        )
    else:
        # SelectRequest validation makes this unreachable, but keeping the
        # branch explicit makes direct calls fail clearly too.
        raise HTTPException(status_code=400, detail="Provide exactly one of point, prompt, or intent")

    if result.error:
        return SelectResponse(success=False, error=result.error)

    detections = [
        SelectDetection(
            mask_data_url=_mask_png_to_selection_rgba(d.mask_data),
            score=d.score,
            bbox=d.bbox.to_dict(),
        )
        for d in result.detections
        if d.mask_data
    ]
    if not detections:
        target = f"'{request.prompt}'" if request.prompt else "an object at that point"
        return SelectResponse(success=False, error=f"No match for {target}")
    return SelectResponse(success=True, detections=detections)


@router.post("/segment", response_model=SegmentResponse)
async def segment_with_sam3(request: SegmentRequest):
    """
    Run SAM3 segmentation and return mask in frontend-compatible format.
    """
    try:
        sam3 = get_sam3_service()
        result = await sam3.segment(
            image_path=request.image_path,
            prompt=request.prompt,
            confidence_threshold=request.confidence,
        )

        if result.error:
            return SegmentResponse(
                success=False,
                error=result.error,
                detections_count=0,
                best_confidence=0.0,
            )

        if not result.detections:
            return SegmentResponse(
                success=False,
                error=f"No detections found for '{request.prompt}'",
                detections_count=0,
                best_confidence=0.0,
            )

        # If returning all above threshold (for plural queries)
        if request.return_all_above_threshold:
            qualifying = [d for d in result.detections if d.score >= request.threshold and d.mask_data]
            if not qualifying:
                # Fall back to best detection
                qualifying = [max(result.detections, key=lambda d: d.score)]
                qualifying = [d for d in qualifying if d.mask_data]

            mask_data_urls = []
            best_confidence = 0.0
            for detection in qualifying:
                if detection.mask_data:
                    rgba_mask = await asyncio.to_thread(_convert_grayscale_to_rgba, detection.mask_data)
                    mask_b64 = base64.b64encode(rgba_mask).decode('utf-8')
                    mask_data_urls.append(f"data:image/png;base64,{mask_b64}")
                    best_confidence = max(best_confidence, detection.score)

            return SegmentResponse(
                success=len(mask_data_urls) > 0,
                mask_data_url=mask_data_urls[0] if mask_data_urls else None,
                mask_data_urls=mask_data_urls,
                detections_count=len(result.detections),
                best_confidence=best_confidence,
            )

        # Use highest confidence detection (default behavior)
        best = max(result.detections, key=lambda d: d.score)

        if not best.mask_data:
            return SegmentResponse(
                success=False,
                error="Detection found but no mask data available",
                detections_count=len(result.detections),
                best_confidence=best.score,
            )

        # Convert SAM3 grayscale mask to RGBA format
        rgba_mask = await asyncio.to_thread(_convert_grayscale_to_rgba, best.mask_data)

        # Convert to data URL
        mask_b64 = base64.b64encode(rgba_mask).decode('utf-8')
        mask_data_url = f"data:image/png;base64,{mask_b64}"

        return SegmentResponse(
            success=True,
            mask_data_url=mask_data_url,
            detections_count=len(result.detections),
            best_confidence=best.score,
        )

    except Exception as e:
        log.error(f"SAM3 segmentation failed: {e}", exc_info=True)
        return SegmentResponse(
            success=False,
            error=str(e),
            detections_count=0,
            best_confidence=0.0,
        )

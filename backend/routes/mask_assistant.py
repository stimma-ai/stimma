"""Mask assistant routes for AI-powered mask editing.

Segmentation only: natural-language mask commands are interpreted by the
ToolView prompt agent (mask_subject / unmask_subject / expand_mask / ... in
prompt_agent_tools.py), which calls /segment directly.
"""
import base64
import io
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
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

    # Create RGBA image
    rgba = Image.new('RGBA', img.size, (0, 0, 0, 255))  # Default: preserve (opaque black)

    # Process pixels
    gray_data = img.load()
    rgba_data = rgba.load()

    for y in range(img.height):
        for x in range(img.width):
            gray_value = gray_data[x, y]
            if gray_value > 128:  # White = detected = inpaint this area
                rgba_data[x, y] = (255, 255, 255, 0)  # Transparent = inpaint
            # else: keep (0, 0, 0, 255) = preserve

    # Convert to PNG bytes
    output = io.BytesIO()
    rgba.save(output, format='PNG')
    return output.getvalue()


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
                    rgba_mask = _convert_grayscale_to_rgba(detection.mask_data)
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
        rgba_mask = _convert_grayscale_to_rgba(best.mask_data)

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

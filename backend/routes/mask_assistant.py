"""Mask assistant routes for AI-powered mask editing."""
import base64
import io
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from PIL import Image

from core.logging import get_logger
from config import get_settings
from prompts import get_prompt
from llm import llm_complete_text
from sam3_service import get_sam3_service

router = APIRouter(prefix="/api/mask", tags=["mask"])
log = get_logger(__name__)


# --- Request/Response Models ---

class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class SAM3Command(BaseModel):
    """Command to run SAM3 segmentation."""
    prompt: str
    confidence: float = 0.2
    is_plural: bool = False  # True for plural requests like "the lights", "all windows"


class PaddingCommand(BaseModel):
    """Command to expand mask regions."""
    percent: int  # 1-100


class InterpretRequest(BaseModel):
    user_input: str
    image_path: str
    has_existing_mask: bool
    conversation_history: List[Message] = []
    default_expand_percent: int = 15  # From UI dropdown


class InterpretResponse(BaseModel):
    operation: str  # "replace", "add", "clear", "pad", "contract", "unmask", "invert"
    sam3_commands: List[SAM3Command] = []
    padding: Optional[PaddingCommand] = None
    explanation: str
    llm_request: Optional[str] = None  # For debug panel
    llm_response: Optional[str] = None  # For debug panel


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


# --- System Prompt ---

def _get_mask_interpreter_prompt() -> str:
    """Get the mask interpreter system prompt from prompts.yaml (hot-reloaded)."""
    prompt = get_prompt("mask", "interpreter_system_prompt")
    if not prompt:
        raise ValueError("Missing mask.interpreter_system_prompt in prompts.yaml")
    return prompt


def _parse_interpret_response(raw_response: str) -> dict:
    """Parse LLM response into structured format."""
    # Try to extract JSON from response
    try:
        # Handle case where model wraps in markdown code blocks
        response = raw_response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            # Find the JSON content between ``` markers
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            response = "\n".join(json_lines)

        parsed = json.loads(response)
        return {
            "operation": parsed.get("operation", "replace"),
            "sam3_commands": [
                SAM3Command(
                    prompt=cmd.get("prompt", ""),
                    confidence=cmd.get("confidence", 0.2),
                    is_plural=cmd.get("is_plural", False)
                )
                for cmd in parsed.get("sam3_commands", [])
            ],
            "padding": PaddingCommand(percent=parsed["padding"]["percent"]) if parsed.get("padding") else None,
            "explanation": parsed.get("explanation", ""),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning(f"Failed to parse LLM response: {e}, raw: {raw_response}")
        # Return a safe default
        return {
            "operation": "replace",
            "sam3_commands": [],
            "padding": None,
            "explanation": f"Could not parse response: {raw_response[:200]}",
        }


@router.post("/interpret", response_model=InterpretResponse)
async def interpret_mask_command(request: InterpretRequest):
    """
    Interpret a natural language mask editing command using the agent-fast LLM.
    Returns structured commands for the frontend to execute.
    """
    settings = get_settings()
    llm_config = settings.agent_fast_llm

    # Build messages
    messages = [{"role": "system", "content": _get_mask_interpreter_prompt()}]

    # Add conversation history
    for msg in request.conversation_history:
        messages.append({"role": msg.role, "content": msg.content})

    # Build current user message
    user_content = f"""User command: "{request.user_input}"
Has existing mask: {request.has_existing_mask}
default_expand_percent: {request.default_expand_percent}"""

    messages.append({"role": "user", "content": user_content})

    # Store for debug
    llm_request = user_content

    try:
        response = await llm_complete_text(
            config=llm_config,
            messages=messages,
            max_tokens=500,
            temperature=0.3,
        )

        # Parse the response
        parsed = _parse_interpret_response(response)

        return InterpretResponse(
            operation=parsed["operation"],
            sam3_commands=parsed["sam3_commands"],
            padding=parsed["padding"],
            explanation=parsed["explanation"],
            llm_request=llm_request,
            llm_response=response,
        )

    except Exception as e:
        log.error(f"LLM interpretation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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

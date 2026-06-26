"""Prompt enhancement routes for AI-assisted prompt editing."""
from core.logging import get_logger
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import asyncio
import re

from core.dependencies import get_db_session

from prompts import get_prompt
from llm import llm_complete_text
from llm_correlation import llm_correlation_context
from model_family import model_family

router = APIRouter(prefix="/api/prompt", tags=["prompt"])
log = get_logger(__name__)


# Map a modelFamily (from model_family.py) to a prompt-enhancement style. The
# style picks which system prompt /improve uses. Families not listed fall back
# to prose enhancement — that covers Flux/Klein, SD3.x (natural-language T5
# encoder), and anything unknown.
_KEYWORD_FAMILIES = frozenset({
    "sdxl", "sdxl-turbo", "sdxl-lightning", "sd-1.5", "sd-2",
})
_VIDEO_FAMILIES = frozenset({
    "stable-video-diffusion", "wan-2.2", "wan-2.1", "wan-other",
    "hunyuan-video", "ltx-video", "mochi", "cogvideo",
    "veo-3", "veo-2", "kling", "runway-gen", "sora", "seedance",
})


def enhancement_mode(family: str, is_video: bool = False) -> str:
    """Map (task, modelFamily) to an enhancement style.

    The TASK is authoritative for video: any video tool gets cinematography,
    regardless of whether the model string is recognized (``is_video`` comes
    from the tool's output type). ``_VIDEO_FAMILIES`` is only a fallback for
    callers that don't pass the task. The remaining styles are model-specific:
    ``ideogram`` (structured JSON), ``keyword`` (booru tags for SD1.5/SDXL), or
    ``prose`` (the default).
    """
    if is_video or family in _VIDEO_FAMILIES:
        return "cinematography"
    if family == "ideogram":
        return "ideogram"
    if family in _KEYWORD_FAMILIES:
        return "keyword"
    return "prose"


# Enhancement style -> the prompts.yaml key for its system prompt. ``ideogram``
# is intentionally absent: that family routes to /to-ideogram-json instead, and
# if it ever reaches /improve it falls back to the prose prompt.
_IMPROVE_PROMPT_BY_MODE = {
    "keyword": "improve_keyword_system_prompt",
    "cinematography": "improve_cinematography_system_prompt",
    "prose": "improve_system_prompt",
}

# Raster formats we can hand to a VLM. Source frames in other formats (or video)
# are simply not shown — enhancement falls back to the text-only path.
_VLM_IMAGE_FORMATS = frozenset({"jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff"})


async def _load_source_image_b64(
    session: AsyncSession, media_id: int, max_size: int = 1024
) -> Optional[str]:
    """Load a library image by id and return EXIF-corrected base64 JPEG, or None.

    Used to show an i2v source frame to the enhancement model. Best-effort: any
    failure (missing item, unreadable file, non-raster format) returns None so
    the caller falls back to text-only enhancement.
    """
    try:
        import io
        import base64
        from pathlib import Path
        from database import MediaItem
        from utils.image_ops import open_oriented

        item = await session.get(MediaItem, media_id)
        if not item or not item.file_path:
            return None
        if (item.file_format or "").lower() not in _VLM_IMAGE_FORMATS:
            return None
        path = Path(item.file_path)
        if not path.exists():
            return None

        img = open_oriented(path)
        try:
            if img.mode != "RGB":
                img = img.convert("RGB")
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=90)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        finally:
            img.close()
    except Exception as e:
        log.warning(f"improve: could not load source image {media_id}: {e}")
        return None


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class EnhancePromptRequest(BaseModel):
    prompt: str
    feedback: str
    conversation_history: List[Message] = []
    human_edited: bool = False  # True if user manually edited the prompt since last AI response
    previous_prompt: Optional[str] = None  # The prompt before human edits (for diff context)


class EnhancePromptResponse(BaseModel):
    enhanced_prompt: str


class ImprovePromptRequest(BaseModel):
    prompt: str
    instructions: Optional[str] = None
    # The tool's model string (api id / checkpoint name). Classified server-side
    # via model_family() to pick the enhancement style; the raw string never
    # egresses. Absent -> prose enhancement.
    model: Optional[str] = None
    # Whether the tool outputs video. Authoritative for cinematography routing —
    # the task is known, so we don't depend on the model string being recognized.
    is_video: bool = False
    # For image-to-video: the library id of the source/first frame. When present
    # on the cinematography path, the frame is shown to the model so the prompt
    # animates the real image. Ignored for other styles.
    media_id: Optional[int] = None


class ImprovePromptResponse(BaseModel):
    improved_prompt: str


class TranslatePromptRequest(BaseModel):
    prompt: str
    # The target language as a human-readable English name, e.g. "Simplified
    # Chinese" — the frontend maps its language code to this before sending.
    target_language: str


class TranslatePromptResponse(BaseModel):
    translated_prompt: str


class IdeogramJsonRequest(BaseModel):
    prompt: str
    # Target canvas, so the model can compose layout / bounding boxes for the
    # real aspect ratio rather than guessing. Optional — falls back to 1:1.
    width: Optional[int] = None
    height: Optional[int] = None


class IdeogramJsonResponse(BaseModel):
    json_prompt: str


# --- 2-Phase Auto-Improve Models ---

class CategoryItem(BaseModel):
    label: str                  # Display text (e.g., "Lighting", "Hair Style")
    category: str               # Machine key (e.g., "lighting", "hair_style")
    allow_wildcard: bool = False


class SuggestCategoriesRequest(BaseModel):
    prompt: str
    # Per-tool standing Instructions (the agent note) — factored into suggestions.
    instructions: Optional[str] = None
    # Let the model reason first (the editor's thinking toggle). Slower; off by default.
    thinking: bool = False
    debug: bool = False


class SuggestCategoriesResponse(BaseModel):
    categories: List[CategoryItem]
    debug: Optional[dict] = None
    message: Optional[str] = None


class SuggestOptionsRequest(BaseModel):
    prompt: str
    category: CategoryItem
    exclude: List[str] = []
    instructions: Optional[str] = None
    thinking: bool = False
    debug: bool = False


class SuggestOptionsResponse(BaseModel):
    category: str
    label: str
    subitems: List[str]
    allow_wildcard: bool = False
    debug: Optional[dict] = None
    message: Optional[str] = None


class SuggestOptionsBatchRequest(BaseModel):
    prompt: str
    categories: List[CategoryItem]
    exclude_by_category: dict[str, List[str]] = {}
    instructions: Optional[str] = None
    thinking: bool = False
    debug: bool = False


class SuggestOptionsBatchResponse(BaseModel):
    results: List[SuggestOptionsResponse]


# Context window config - leave room for response
MAX_CONTEXT_TOKENS = 3000  # Model has 4096, leave ~1000 for response
CHARS_PER_TOKEN = 4  # Rough estimate


def trim_messages_to_fit(messages: list, max_tokens: int = MAX_CONTEXT_TOKENS) -> list:
    """Trim conversation history to fit within context window, keeping system + recent messages."""
    if not messages:
        return messages

    max_chars = max_tokens * CHARS_PER_TOKEN

    # Always keep system message (first) and current user message (last)
    if len(messages) <= 2:
        return messages

    system_msg = messages[0]
    current_msg = messages[-1]
    history = messages[1:-1]

    # Calculate space used by required messages
    required_chars = len(system_msg.get('content', '')) + len(current_msg.get('content', ''))

    # Add history from most recent, working backwards
    available_chars = max_chars - required_chars
    kept_history = []

    for msg in reversed(history):
        msg_chars = len(msg.get('content', ''))
        if available_chars >= msg_chars:
            kept_history.insert(0, msg)
            available_chars -= msg_chars
        else:
            break

    return [system_msg] + kept_history + [current_msg]


_CENTRAL_HUMAN_RE = re.compile(
    r"\b("
    r"person|people|human|man|woman|boy|girl|child|teen|teenager|adult|elderly|"
    r"model|actor|actress|character|portrait|headshot|selfie|bride|groom"
    r")\b",
    re.IGNORECASE,
)

_CENTRAL_HUMAN_CORE_CATEGORIES = (
    CategoryItem(label="Expression", category="expression", allow_wildcard=False),
    CategoryItem(label="Pose", category="pose", allow_wildcard=False),
    CategoryItem(label="Outfit", category="outfit", allow_wildcard=True),
    CategoryItem(label="Hair Style", category="hair_style", allow_wildcard=False),
    CategoryItem(label="Hair Color", category="hair_color", allow_wildcard=True),
    CategoryItem(label="Age", category="age", allow_wildcard=False),
)


def _normalize_category_key(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", category.strip().lower()).strip("_")


def _stabilize_suggestion_categories(
    prompt: str,
    categories: List[CategoryItem],
    has_instructions: bool = False,
) -> List[CategoryItem]:
    """Lightly tidy the model's category list — we trust its choices.

    Normalizes keys and dedupes. For central-human prompts WITHOUT user
    Instructions we also keep the common portrait dimensions present and first
    (consistency across refreshes); Instructions turn that off so the model's list
    passes through. Capped at MAX_CATEGORIES so a runaway model can't flood the UI.
    """
    MAX_CATEGORIES = 20
    normalized: List[CategoryItem] = []
    seen: set[str] = set()

    for item in categories:
        key = _normalize_category_key(item.category or item.label)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(CategoryItem(
            label=item.label,
            category=key,
            allow_wildcard=item.allow_wildcard,
        ))

    # Explicit user instructions: trust them fully — no forced core set.
    if has_instructions or not _CENTRAL_HUMAN_RE.search(prompt):
        return normalized[:MAX_CATEGORIES]

    by_key = {item.category: item for item in normalized}
    result: List[CategoryItem] = []
    added: set[str] = set()

    for default in _CENTRAL_HUMAN_CORE_CATEGORIES:
        existing = by_key.get(default.category)
        result.append(existing or default)
        added.add(default.category)

    for item in normalized:
        if item.category in added:
            continue
        result.append(item)
        added.add(item.category)
        if len(result) >= MAX_CATEGORIES:
            break

    return result


@router.post("/enhance", response_model=EnhancePromptResponse)
async def enhance_prompt(request: EnhancePromptRequest):
    """
    Enhance or modify an image generation prompt using AI.

    Takes the current prompt, user feedback, and conversation history
    to generate an improved prompt.
    """
    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    try:
        llm_config = await get_effective_llm_config('agent-fast')
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

    # Build messages array for the LLM
    messages = [
        {"role": "system", "content": get_prompt("prompt_enhancement", "system_prompt")}
    ]

    # Add conversation history
    for msg in request.conversation_history:
        messages.append({"role": msg.role, "content": msg.content})

    # Build the current user message with clear delimiters
    # Use XML-style tags to clearly delineate the prompt boundaries
    if request.feedback.strip():
        if request.human_edited and request.previous_prompt:
            # Show before/after so model doesn't resurrect deleted content
            user_content = f"""The user manually edited the prompt. Here is the before/after:

<previous_prompt>
{request.previous_prompt}
</previous_prompt>

<prompt>
{request.prompt}
</prompt>

IMPORTANT: The user's edits are INTENTIONAL. If they removed something, do NOT add it back. Work from <prompt>, not <previous_prompt>.

<feedback>{request.feedback}</feedback>"""
        else:
            user_content = f"""<prompt>
{request.prompt}
</prompt>

<feedback>{request.feedback}</feedback>"""
    else:
        # No feedback - just improve the prompt
        user_content = f"""Please improve this prompt:

<prompt>
{request.prompt}
</prompt>"""

    messages.append({"role": "user", "content": user_content})

    # Trim to fit context window
    messages = trim_messages_to_fit(messages)

    with llm_correlation_context("prompt-agent"):
        try:
            # Calculate approximate input size for logging
            total_input_chars = sum(len(m.get('content', '')) for m in messages)
            log.info(f"Starting enhancement - {len(messages)} messages, ~{total_input_chars} input chars")

            enhanced_prompt = await llm_complete_text(
                config=llm_config,
                messages=messages,
                max_tokens=8192,
                temperature=0.7,

            )

            log.info(f"Enhancement complete - output: {len(enhanced_prompt)} chars")

            return EnhancePromptResponse(enhanced_prompt=enhanced_prompt)

        except asyncio.TimeoutError:
            log.error("Prompt enhancement request timed out")
            raise HTTPException(status_code=504, detail="Request timed out")
        except Exception as e:
            log.error(f"Prompt enhancement error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


# Default system prompts (used if not configured in config.yaml)
DEFAULT_IMPROVE_SYSTEM_PROMPT = """You are a helpful assistant that improves image generation prompts.
Your job is to take a prompt and make it better while preserving the user's original intent.

Guidelines:
- Apply a light touch - don't completely rewrite the prompt
- Fix grammar and spelling issues
- Add clarity where the intent is unclear
- Enhance descriptive language where appropriate
- Keep the same subject, style, and mood
- If the prompt already looks well-crafted, make minimal changes
- Output ONLY the improved prompt, no explanations or additional text"""

@router.post("/improve", response_model=ImprovePromptResponse)
async def improve_prompt(request: ImprovePromptRequest, session: AsyncSession = Depends(get_db_session)):
    """
    Auto-improve an image generation prompt using AI.

    Applies light-touch improvements to fix grammar, add clarity,
    and enhance descriptions while preserving the original intent.
    """
    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    try:
        llm_config = await get_effective_llm_config('agent-fast')
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

    # Pick the enhancement style. Task drives video (cinematography); model
    # family drives the rest (keyword / ideogram / prose). Falls back to prose
    # for unknown families and missing model strings.
    mode = enhancement_mode(model_family(request.model), is_video=request.is_video)

    # i2v: on the cinematography path, show the source frame to the model so the
    # prompt animates the real image. Best-effort — if the frame can't be loaded
    # we fall back to the text-only cinematography prompt.
    source_image_b64: Optional[str] = None
    if mode == "cinematography" and request.media_id is not None:
        source_image_b64 = await _load_source_image_b64(session, request.media_id)

    prompt_key = _IMPROVE_PROMPT_BY_MODE.get(mode, "improve_system_prompt")
    if source_image_b64:
        prompt_key = "improve_cinematography_image_system_prompt"
    prompt_from_file = get_prompt("prompt_enhancement", prompt_key)
    if not prompt_from_file and prompt_key != "improve_system_prompt":
        # A family-specific prompt isn't configured — fall back to prose.
        prompt_from_file = get_prompt("prompt_enhancement", "improve_system_prompt")
    system_prompt = prompt_from_file if prompt_from_file else DEFAULT_IMPROVE_SYSTEM_PROMPT
    log.info(f"Prompt improve mode={mode} image={'yes' if source_image_b64 else 'no'}")

    # Build the user message
    if source_image_b64:
        # i2v: the attached frame is reference; the user's text is direction for
        # the clip, to be turned into motion/camera — not a prompt to "improve".
        instr = (f"\n\nAdditional instructions: {request.instructions.strip()}"
                 if request.instructions and request.instructions.strip() else "")
        user_content = (
            "The image is the first frame. Here is the user's direction for the clip — "
            f"turn it into shot direction (motion and camera):\n\n{request.prompt}{instr}"
        )
    elif request.instructions and request.instructions.strip():
        user_content = f"Please improve this prompt according to these instructions:\n\nInstructions: {request.instructions}\n\nPrompt:\n{request.prompt}"
    else:
        user_content = f"Please improve this prompt with a light touch:\n\n{request.prompt}"

    if source_image_b64:
        # Multimodal: the source frame rides alongside the prompt text.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_content},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{source_image_b64}"}},
            ]},
        ]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

    with llm_correlation_context("prompt-agent"):
        try:
            log.info(f"Sending prompt improve request")

            improved_prompt = await llm_complete_text(
                config=llm_config,
                messages=messages,
                max_tokens=8192,
                temperature=0.7,

            )

            log.info(f"Prompt improve successful ({len(improved_prompt)} chars)")

            return ImprovePromptResponse(improved_prompt=improved_prompt)

        except asyncio.TimeoutError:
            log.error("Prompt improve request timed out")
            raise HTTPException(status_code=504, detail="Request timed out")
        except Exception as e:
            log.error(f"Prompt improve error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/translate", response_model=TranslatePromptResponse)
async def translate_prompt(request: TranslatePromptRequest):
    """
    Translate an image generation prompt into a target language using AI.

    Preserves verbatim [brackets], placeholder tokens, wildcard syntax, and
    comments — only the natural-language description is translated. This runs as
    a non-destructive generate-time step (after auto-improve), so the editor text
    is untouched.
    """
    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    if not request.target_language.strip():
        raise HTTPException(status_code=400, detail="target_language is required")

    try:
        llm_config = await get_effective_llm_config('agent-fast')
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

    system_prompt_template = get_prompt("prompt_enhancement", "translate_system_prompt")
    if not system_prompt_template:
        raise HTTPException(status_code=500, detail="translate_system_prompt not configured")
    system_prompt = system_prompt_template.replace("{target_language}", request.target_language.strip())

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request.prompt},
    ]

    with llm_correlation_context("prompt-agent"):
        try:
            log.info(f"Translating prompt -> {request.target_language}")

            translated_prompt = await llm_complete_text(
                config=llm_config,
                messages=messages,
                max_tokens=8192,
                temperature=0.3,
            )

            log.info(f"Prompt translate successful ({len(translated_prompt)} chars)")

            return TranslatePromptResponse(translated_prompt=translated_prompt.strip())

        except asyncio.TimeoutError:
            log.error("Prompt translate request timed out")
            raise HTTPException(status_code=504, detail="Request timed out")
        except Exception as e:
            log.error(f"Prompt translate error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


def _extract_json_object(text: str) -> str:
    """Pull a single JSON object out of an LLM response and re-serialize it.

    Tolerates ```json fences and leading/trailing prose, then validates by
    round-tripping through json.loads so callers get well-formed JSON or a clear
    error. Returns pretty-printed JSON (ensure_ascii=False so CJK stays legible).
    """
    import json

    candidate = text.strip()
    if "```json" in candidate:
        candidate = candidate.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in candidate:
        candidate = candidate.split("```", 1)[1].split("```", 1)[0]
    candidate = candidate.strip()

    # Fall back to the outermost {...} span if there's still surrounding prose.
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start:end + 1]

    parsed = json.loads(candidate)  # raises json.JSONDecodeError if invalid
    return json.dumps(parsed, ensure_ascii=False, indent=2)


def _looks_like_ideogram_json(text: str) -> bool:
    """True when the prompt is already a JSON object (an Ideogram structured caption).

    Used to decide between refine-in-place and convert-from-prose. Deliberately
    strict: only a bare ``{...}`` that parses as a dict counts, so ordinary prose
    that merely mentions braces isn't misread as JSON.
    """
    import json

    s = (text or "").strip()
    if not s.startswith("{") or not s.endswith("}"):
        return False
    try:
        return isinstance(json.loads(s), dict)
    except (json.JSONDecodeError, ValueError):
        return False


def _canvas_description(width: Optional[int], height: Optional[int]) -> str:
    """Human-readable canvas description for the Ideogram JSON prompt.

    Gives the model the orientation + reduced aspect ratio so it can place
    bounding boxes for the real shape. Falls back to 1:1 when size is unknown.
    """
    from math import gcd

    if not width or not height or width <= 0 or height <= 0:
        return "1:1 square canvas (exact size unknown — assume square unless the prompt implies otherwise)"

    g = gcd(width, height) or 1
    rw, rh = width // g, height // g
    if width == height:
        orient = "square"
    elif width > height:
        orient = "landscape"
    else:
        orient = "portrait"
    return f"{width}×{height}px {orient} canvas (aspect ratio {rw}:{rh})"


@router.post("/to-ideogram-json", response_model=IdeogramJsonResponse)
async def prompt_to_ideogram_json(request: IdeogramJsonRequest):
    """
    Convert a plain-text prompt into Ideogram 4.0 structured JSON format.

    Ideogram 4 is trained on structured JSON captions, so this produces better
    text rendering, layout, and style fidelity. Offered only for the Ideogram 4
    tool; runs as the final non-destructive generate-time step.
    """
    import json
    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    try:
        llm_config = await get_effective_llm_config('agent-fast')
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

    # If the prompt is ALREADY an Ideogram JSON object, take a lighter touch:
    # enhance the wording but keep the user's structure, layout, and bboxes.
    # Otherwise convert prose/keywords into a fresh JSON caption.
    already_json = _looks_like_ideogram_json(request.prompt)
    prompt_key = "ideogram_json_refine_system_prompt" if already_json else "ideogram_json_system_prompt"
    system_prompt_template = get_prompt("prompt_enhancement", prompt_key)
    if not system_prompt_template:
        raise HTTPException(status_code=500, detail=f"{prompt_key} not configured")
    system_prompt = system_prompt_template.replace(
        "{canvas}", _canvas_description(request.width, request.height)
    )
    log.info(f"Ideogram JSON mode={'refine' if already_json else 'convert'}")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request.prompt},
    ]

    with llm_correlation_context("prompt-agent"):
        try:
            log.info("Converting prompt to Ideogram 4 JSON")

            raw = await llm_complete_text(
                config=llm_config,
                messages=messages,
                max_tokens=8192,
                temperature=0.4,
            )

            try:
                json_prompt = _extract_json_object(raw)
            except json.JSONDecodeError as e:
                log.error(f"Ideogram JSON parse failed: {e}; raw: {raw[:500]}")
                raise HTTPException(
                    status_code=502,
                    detail="The model returned invalid JSON for Ideogram. Try again.",
                )

            log.info(f"Ideogram JSON conversion successful ({len(json_prompt)} chars)")

            return IdeogramJsonResponse(json_prompt=json_prompt)

        except HTTPException:
            raise
        except asyncio.TimeoutError:
            log.error("Ideogram JSON request timed out")
            raise HTTPException(status_code=504, detail="Request timed out")
        except Exception as e:
            log.error(f"Ideogram JSON error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


def _detect_refusal(response_content: str) -> Optional[str]:
    """
    Detect if the LLM refused to generate suggestions.
    Returns the refusal message if detected, None otherwise.

    Delegates to the shared refusal classifier (refusal_detection.py) —
    the single source of truth used across all agent surfaces.
    """
    from refusal_detection import detect_refusal
    return detect_refusal(response_content)


def _parse_categories_response(response_content: str) -> tuple[List[CategoryItem], Optional[str]]:
    """Parse LLM response into a list of CategoryItems."""
    import json
    import re

    refusal = _detect_refusal(response_content)
    if refusal:
        return [], refusal

    try:
        json_match = re.search(r'\[.*\]', response_content, re.DOTALL)
        if json_match:
            response_content = json_match.group(0)

        data = json.loads(response_content)
        if not isinstance(data, list):
            log.error(f"Categories response is not an array: {type(data)}")
            return [], None

        categories = []
        seen = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            label = item.get('label', '').strip()
            category = item.get('category', '').strip()
            if not label or not category or category in seen:
                continue
            seen.add(category)
            categories.append(CategoryItem(
                label=label,
                category=category,
                allow_wildcard=bool(item.get('allow_wildcard', False))
            ))

        return categories, None

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse categories JSON: {e}")
        log.error(f"Response content: {response_content[:500]}")
        return [], None


def _parse_options_response(response_content: str) -> tuple[List[str], Optional[str]]:
    """Parse LLM response into a list of option strings."""
    import json
    import re

    refusal = _detect_refusal(response_content)
    if refusal:
        return [], refusal

    # Collect string items from every flat array in the response. Small models
    # sometimes emit several arrays (one per line) instead of one — a plain
    # json.loads then fails with "Extra data". Parsing each bracket group and
    # merging is robust to that, and to leading/trailing prose.
    arrays = re.findall(r'\[[^\[\]]*\]', response_content, re.DOTALL)
    if not arrays:
        # Fall back to a single greedy match (handles odd whitespace).
        m = re.search(r'\[.*\]', response_content, re.DOTALL)
        if m:
            arrays = [m.group(0)]

    options: List[str] = []
    seen: set[str] = set()
    parsed_any = False
    for chunk in arrays:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        parsed_any = True
        for item in data:
            if isinstance(item, str) and item.strip():
                normalized = item.strip().lower()
                if normalized not in seen:
                    seen.add(normalized)
                    options.append(item.strip())

    if not parsed_any:
        log.error(f"Failed to parse options JSON. Response content: {response_content[:500]}")
        return [], None

    return options, None


@router.post("/suggest-categories", response_model=SuggestCategoriesResponse)
async def suggest_categories(request: SuggestCategoriesRequest):
    """
    Phase 1: Analyze prompt and return relevant category dimensions.
    Fast call with low temperature.
    """
    from llm_resolver import get_effective_llm_config
    llm_config = await get_effective_llm_config('agent-fast')

    prompt_from_file = get_prompt("prompt_enhancement", "suggest_categories_system_prompt")
    if not prompt_from_file:
        raise HTTPException(status_code=500, detail="suggest_categories_system_prompt not configured")

    system_prompt = prompt_from_file
    if request.instructions and request.instructions.strip():
        system_prompt = (
            f"{prompt_from_file}\n\n"
            "USER INSTRUCTIONS — the user's standing requirements for this tool. Follow them exactly. "
            "They take priority over the guidance above: include every dimension the user requires "
            "(even ones you wouldn't normally suggest), and omit any they say to exclude:\n"
            f"{request.instructions.strip()}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": request.prompt}
    ]

    debug_info = None
    if request.debug:
        debug_info = {
            "system_prompt": system_prompt,
            "user_prompt": request.prompt,
            "raw_response": None,
        }

    try:
        log.info(f"Suggest-categories starting - prompt: {len(request.prompt)} chars, model: {llm_config.get_model()}, base: {llm_config.get_api_base()}")

        MAX_RETRIES = 3
        best_categories: List[CategoryItem] = []
        last_response = ""

        with llm_correlation_context("prompt-agent"):
            for attempt in range(MAX_RETRIES):
                response_content = await llm_complete_text(
                    config=llm_config,
                    messages=messages,
                    max_tokens=8192,
                    temperature=0.3 + (attempt * 0.1),
                    enable_thinking=request.thinking,
                )

                last_response = response_content

                if not response_content:
                    log.warning(
                        "Suggest-categories: empty response, retrying",
                        attempt=attempt + 1,
                        model=getattr(llm_config, "model", None),
                        max_tokens=8192,
                    )
                    continue

                log.info(f"Suggest-categories attempt {attempt + 1}: got {len(response_content)} chars response")

                categories, refusal = _parse_categories_response(response_content)
                categories = _stabilize_suggestion_categories(
                    request.prompt,
                    categories,
                    has_instructions=bool(request.instructions and request.instructions.strip()),
                )

                if refusal:
                    log.warning(f"Suggest-categories detected refusal: {refusal[:100]}")
                    if debug_info:
                        debug_info["raw_response"] = response_content
                    return SuggestCategoriesResponse(categories=[], debug=debug_info, message=refusal)

                if len(categories) >= 3:
                    best_categories = categories
                    log.info(f"Suggest-categories complete on attempt {attempt + 1} - {len(categories)} categories")
                    break

                if len(categories) > len(best_categories):
                    best_categories = categories

                log.debug(f"Suggest-categories attempt {attempt + 1}: {len(categories)} categories - retrying")

            if debug_info:
                debug_info["raw_response"] = last_response

            log.info(f"Suggest-categories returning {len(best_categories)} categories")
            return SuggestCategoriesResponse(categories=best_categories, debug=debug_info)

    except asyncio.TimeoutError:
        log.error("Suggest-categories request timed out")
        raise HTTPException(status_code=504, detail="Request timed out")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Suggest-categories error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/suggest-options", response_model=SuggestOptionsResponse)
async def suggest_options(request: SuggestOptionsRequest):
    """
    Phase 2: Generate creative options for a single category.
    Called in parallel for each category. High temperature for diversity.
    """
    return await _suggest_options_impl(request)


@router.post("/suggest-options/batch", response_model=SuggestOptionsBatchResponse)
async def suggest_options_batch(request: SuggestOptionsBatchRequest):
    """
    Fetch options for multiple categories in one backend request.

    This keeps LLM calls parallel while avoiding frontend request fan-out that
    can starve other UI requests (e.g. context menu data fetches).
    """
    tasks = []
    for category in request.categories:
        tasks.append(
            _suggest_options_impl(
                SuggestOptionsRequest(
                    prompt=request.prompt,
                    category=category,
                    exclude=request.exclude_by_category.get(category.category, []),
                    instructions=request.instructions,
                    thinking=request.thinking,
                    debug=request.debug,
                )
            )
        )

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    results: List[SuggestOptionsResponse] = []

    for category, result in zip(request.categories, gathered):
        if isinstance(result, Exception):
            log.error(
                "Suggest-options batch failed for %s: %s",
                category.label,
                result,
                exc_info=result,
            )
            results.append(SuggestOptionsResponse(
                category=category.category,
                label=category.label,
                subitems=[],
                allow_wildcard=category.allow_wildcard,
                message=str(result),
            ))
        else:
            results.append(result)

    return SuggestOptionsBatchResponse(results=results)


async def _suggest_options_impl(request: SuggestOptionsRequest) -> SuggestOptionsResponse:
    """Shared suggest-options implementation for single and batch endpoints."""
    from llm_resolver import get_effective_llm_config
    llm_config = await get_effective_llm_config('agent-fast')

    prompt_from_file = get_prompt("prompt_enhancement", "suggest_options_system_prompt")
    if not prompt_from_file:
        raise HTTPException(status_code=500, detail="suggest_options_system_prompt not configured")

    exclude_section = ""
    if request.exclude:
        exclude_list = ", ".join(f'"{e}"' for e in request.exclude)
        exclude_section = f"\n\nDo NOT repeat any of these previously shown options: [{exclude_list}]. Generate completely fresh alternatives."

    system_prompt = prompt_from_file.replace("{exclude_section}", exclude_section)
    if request.instructions and request.instructions.strip():
        system_prompt += (
            "\n\nUSER INSTRUCTIONS — the user's standing requirements for this tool. Honor them "
            "strictly: only include values they permit, and respect any ranges or limits they set:\n"
            f"{request.instructions.strip()}"
        )

    user_content = f"""Prompt: {request.prompt}

Category: {request.category.label} ({request.category.category})"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    debug_info = None
    if request.debug:
        debug_info = {
            "system_prompt": system_prompt,
            "user_prompt": user_content,
            "raw_response": None,
        }

    try:
        log.info(f"Suggest-options starting - category: {request.category.label}, exclude: {len(request.exclude)} items")

        with llm_correlation_context("prompt-agent"):
            response_content = await llm_complete_text(
                config=llm_config,
                messages=messages,
                max_tokens=8192,
                temperature=0.8,
                enable_thinking=request.thinking,
            )

        if debug_info:
            debug_info["raw_response"] = response_content

        options, refusal = _parse_options_response(response_content)

        if refusal:
            log.warning(f"Suggest-options detected refusal for {request.category.label}: {refusal[:100]}")
            return SuggestOptionsResponse(
                category=request.category.category,
                label=request.category.label,
                subitems=[],
                allow_wildcard=request.category.allow_wildcard,
                debug=debug_info,
                message=refusal
            )

        log.info(f"Suggest-options returning {len(options)} options for {request.category.label}")
        return SuggestOptionsResponse(
            category=request.category.category,
            label=request.category.label,
            subitems=options,
            allow_wildcard=request.category.allow_wildcard,
            debug=debug_info
        )

    except asyncio.TimeoutError:
        log.error(f"Suggest-options request timed out for {request.category.label}")
        raise HTTPException(status_code=504, detail="Request timed out")
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Suggest-options error for {request.category.label}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Prompt-editor mini-agent (tool-calling)
# ---------------------------------------------------------------------------

class AgentToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON string


class AgentStepRequest(BaseModel):
    # OpenAI-style message dicts the frontend maintains for the run:
    #   {"role": "user", "content": str}
    #   {"role": "assistant", "content": str|None, "tool_calls": [...]}
    #   {"role": "tool", "tool_call_id": str, "content": str}
    conversation_history: List[dict] = []
    # Live snapshot of the editor screen, refreshed every step.
    state_context: dict = {}
    # Per-request thinking toggle (the lightbulb) — unique to this use case.
    thinking: bool = True
    # Stable id for the whole editor conversation, for caching + trace grouping.
    session_id: Optional[str] = None


class AgentStepResponse(BaseModel):
    message: str
    tool_calls: List[AgentToolCall] = []
    thinking: Optional[str] = None


@router.post("/agent/step", response_model=AgentStepResponse)
async def agent_step(request: AgentStepRequest):
    """One step of the prompt-editor mini-agent.

    Stateless: the frontend owns the conversation and executes tool calls. We
    resolve the agent-fast model, inject a fresh live-state snapshot, trim the
    middle of the history to the real context window, and return the model's
    next assistant message (text + tool_calls).
    """
    import json
    from llm import llm_completion, QuotaExceededError, ContentFilteredError
    from llm_resolver import LLMUnavailableError, get_effective_llm_config
    from prompt_agent_tools import TOOL_SCHEMAS
    # Reuse the shared agent LLM infrastructure — thinking options, output
    # reserve, drop-the-middle compaction, and last-user-message reminder
    # injection are all the same helpers the v2 agent uses.
    from agent.v2.llm_options import agent_llm_options
    from agent.v2.conversation import (
        response_reserve,
        _inject_last_user_context,
        _apply_token_budget,
        _estimate_tokens,
    )

    try:
        llm_config = await get_effective_llm_config('agent-fast')
    except LLMUnavailableError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": str(e)})

    system_prompt = get_prompt("prompt_enhancement", "agent_system_prompt")
    if not system_prompt:
        raise HTTPException(status_code=500, detail="agent_system_prompt not configured")

    # The live screen state rides as a <system-reminder> on the LAST user message
    # (the established pattern — see system_reminders.py), NOT a second system
    # message. This keeps the system prompt prefix stable for caching, keeps the
    # volatile state at the tail, and never persists it into stored history.
    state_json = json.dumps(request.state_context, ensure_ascii=False, indent=2)
    state_reminder = (
        "<system-reminder>\n"
        "Editor screen state at the START of this turn (before any tools you call now). "
        "After you call tools, rely on the tool results for what changed — describe what YOU "
        "changed, and don't say something is 'already' set if your own tool calls just set it.\n"
        f"```json\n{state_json}\n```\n"
        "</system-reminder>"
    )

    # Budget the history against the real model window, then drop-the-middle via
    # the shared compactor. Shallow-copy history dicts so the in-place reminder
    # injection never mutates the request payload.
    max_ctx = int(getattr(llm_config, "max_context_tokens", 128_000) or 128_000)
    max_tokens = response_reserve(max_ctx)
    overhead = _estimate_tokens([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": state_reminder},
    ])
    history_budget = max(1000, int(max_ctx * 0.80) - overhead["total"] - max_tokens)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [dict(m) for m in request.conversation_history]
    messages = _apply_token_budget(messages, budget=history_budget)
    # Inject the state reminder (+ timestamp) into the last user message in place.
    _inject_last_user_context(messages, [state_reminder])

    # Telemetry: one prompt_agent_step per request/response cycle. Identity
    # fields classify through the helpers (model_family / endpoint_class);
    # errorType domain is the shared agent error list incl. refusal.
    import time as _time
    from telemetry import get_telemetry_client
    from telemetry_props import classify_agent_error, llm_config_fields
    _step_started = _time.monotonic()
    _llm_fields = llm_config_fields(llm_config)

    def _track_step(status: str, error_type: Optional[str] = None) -> None:
        try:
            props = {
                **_llm_fields,
                "durationMs": int((_time.monotonic() - _step_started) * 1000),
                "status": status,
            }
            if error_type:
                props["errorType"] = error_type
            get_telemetry_client().track("prompt_agent_step", props, category="prompt_agent")
        except Exception:
            pass

    with llm_correlation_context("prompt-agent"):
        try:
            resp = await llm_completion(
                config=llm_config,
                messages=messages,
                tools=TOOL_SCHEMAS,
                max_tokens=max_tokens,
                # Stable system-prompt prefix + state-as-reminder-on-last-user-msg
                # means the prefix is cacheable across turns (same as the v2 agent).
                cacheable=True,
                session_id=request.session_id,
                **agent_llm_options(enable_thinking=request.thinking),
            )
            tool_calls = [AgentToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in resp.tool_calls]
            # Shared refusal classifier: only the categorical label egresses.
            from refusal_detection import is_refusal
            if not tool_calls and is_refusal(resp.content):
                _track_step("failed", error_type="refusal")
            else:
                _track_step("completed")
            return AgentStepResponse(message=resp.content or "", tool_calls=tool_calls, thinking=resp.thinking)
        except asyncio.TimeoutError:
            log.error("Prompt-agent step timed out")
            _track_step("timeout")
            raise HTTPException(status_code=504, detail="The request timed out. Try again.")
        except ContentFilteredError:
            log.warning("Prompt-agent step content-filtered")
            _track_step("failed", error_type="content_filtered")
            raise HTTPException(
                status_code=422,
                detail="The model declined this request (content filter). Try rephrasing.",
            )
        except QuotaExceededError as e:
            log.warning(f"Prompt-agent step quota exceeded: {e}")
            _track_step("failed", error_type="quota_exceeded")
            raise HTTPException(
                status_code=429,
                detail=str(e) or "LLM quota exceeded. Check your plan or usage and try again.",
            )
        except Exception as e:
            log.error(f"Prompt-agent step error: {e}", exc_info=True)
            _track_step("failed", error_type=classify_agent_error(e))
            raise HTTPException(status_code=500, detail=str(e))

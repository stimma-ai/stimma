"""Prompt enhancement routes for AI-assisted prompt editing."""
from core.logging import get_logger
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import asyncio
import json
import re

from core.dependencies import get_db_session

from prompts import get_prompt
from llm import llm_complete_text, EntitlementError
from llm_correlation import llm_correlation_context
from model_family import model_family

router = APIRouter(prefix="/api/prompt", tags=["prompt"])
log = get_logger(__name__)


def _entitlement_http_exception(e: EntitlementError) -> HTTPException:
    """EntitlementError -> a typed 402 the frontend can classify on status +
    code, not by matching the message string (which is Stimma Cloud's raw
    upstream text and may change)."""
    return HTTPException(
        status_code=402,
        detail={"code": "subscription_required", "message": str(e)},
    )


# Map a modelFamily (from model_family.py) to a prompt-enhancement style. The
# style picks which system prompt /improve uses. Families not listed fall back
# to prose enhancement — that covers Flux/Klein, SD3.x (natural-language T5
# encoder), and anything unknown.
_KEYWORD_FAMILIES = frozenset({
    "sdxl", "sdxl-turbo", "sdxl-lightning", "sd-1.5", "sd-2",
})
_VIDEO_FAMILIES = frozenset({
    "stable-video-diffusion", "wan-2.2", "wan-2.1", "wan-other",
    "hunyuan-video", "minimax-h3", "ltx-video", "mochi", "cogvideo",
    "veo-3", "veo-2", "kling", "runway-gen", "sora", "seedance",
})


def enhancement_mode(
    family: str, is_video: bool = False, is_image_edit: bool = False, is_audio: bool = False
) -> str:
    """Map (task, modelFamily) to an enhancement style.

    The TASK is authoritative for audio, video and edits: any audio tool gets the
    sound-focused ``audio`` style, any video tool gets cinematography, and a
    natural-language image model fed input image(s) gets ``edit`` — all regardless
    of whether the model string is recognized (``is_audio`` / ``is_video`` /
    ``is_image_edit`` come from the tool's I/O, not the model name).
    ``_VIDEO_FAMILIES`` is only a fallback for callers that don't pass the task.
    The remaining styles are model-specific: ``ideogram`` (structured JSON) and
    ``keyword`` (booru tags for SD1.5/SDXL) keep their style even when editing
    (they describe the target, not an instruction over the input); everything else
    is ``edit`` when input images are present, else ``prose``.
    """
    if is_audio:
        return "audio"
    if family == "minimax-h3" and (is_video or family in _VIDEO_FAMILIES):
        return "minimax-h3"
    if is_video or family in _VIDEO_FAMILIES:
        return "cinematography"
    if family == "qwen-image-2.1":
        return "qwen-image-2.1-edit" if is_image_edit else "qwen-image-2.1"
    if family == "ideogram":
        return "ideogram"
    if family in _KEYWORD_FAMILIES:
        return "keyword"
    if is_image_edit:
        return "edit"
    return "prose"


# Enhancement style -> the prompts.yaml key for its system prompt. ``ideogram``
# is intentionally absent: that family routes to /to-ideogram-json instead, and
# if it ever reaches /improve it falls back to the prose prompt.
_IMPROVE_PROMPT_BY_MODE = {
    "keyword": "improve_keyword_system_prompt",
    "cinematography": "improve_cinematography_system_prompt",
    "minimax-h3": "improve_minimax_h3_system_prompt",
    "qwen-image-2.1": "improve_qwen_image_21_system_prompt",
    "qwen-image-2.1-edit": "improve_qwen_image_21_edit_system_prompt",
    "edit": "improve_image_edit_system_prompt",
    "audio": "improve_audio_system_prompt",
    "prose": "improve_system_prompt",
}


def _qwen_image_refs_phrase(n: int) -> str:
    """The inputs a Qwen-Image-2.1 edit can address, e.g. "2 input images, <image1> and <image2>".
    A single input is referred to naturally, so it gets no tag."""
    tags = [f"<image{i}>" for i in range(1, max(1, n) + 1)]
    if len(tags) == 1:
        return "one input image"
    listed = ", ".join(tags[:-1]) + f" and {tags[-1]}"
    return f"{len(tags)} input images, {listed}"


def _qwen_canvas_guidance(width: Optional[int], height: Optional[int]) -> str:
    """Tell the Qwen-Image-2.1 rewriter the frame it is composing for."""
    if not width or not height:
        return ""
    ratio = width / height
    if ratio > 1.15:
        shape = "wide (landscape)"
    elif ratio < 1 / 1.15:
        shape = "vertical (portrait)"
    else:
        shape = "square"
    return (
        f"The canvas is already fixed at {width}x{height}, a {shape} frame. Compose for that "
        "orientation and name it in the opening sentence, but never write the ratio or size "
        "into the description."
    )


def _input_images_phrase(n: int) -> str:
    """Human-readable count of input images for the edit system prompt."""
    return "an input image" if n <= 1 else f"{n} input images"


# The cinematography prompts carry an {audio_guidance} slot because the right
# instruction flips entirely on whether the tool generates its own soundtrack.
_AUDIO_GENERATED_GUIDANCE = (
    "If the user gives spoken lines or sound effects, carry them through verbatim — modern "
    "video models render dialogue and audio, so these are content to keep, not motion to mime; "
    'never reduce a line to "her lips move". Keep them even when the speaker or source is '
    "offscreen or not visible{frame_clause}: an unseen voice or an off-camera sound is audio the "
    "model should produce, not a detail to drop because it doesn't move."
)

_AUDIO_SUPPLIED_GUIDANCE = (
    "The user supplied the soundtrack: the model reproduces that track exactly and generates no "
    "sound of its own, so write the picture that belongs to it — mouth movement and jaw "
    "articulation while a voice is heard, breath between phrases, an impact landing on a hit, "
    "movement carried on the tempo. Keep any words the user wrote and attribute them to the "
    "speaker; they tell the model what the mouth is doing. Don't write sound effects, ambience, "
    "or dialogue as things to produce — nothing you write changes the audio, and invented sound "
    "design only pulls the picture away from the real track."
)


def _audio_guidance(*, audio_conditioned: bool, image_variant: bool) -> str:
    """Pick the soundtrack instruction for the cinematography prompts."""
    if audio_conditioned:
        return _AUDIO_SUPPLIED_GUIDANCE
    return _AUDIO_GENERATED_GUIDANCE.format(
        frame_clause=" in the frame" if image_variant else ""
    )


def _h3_task_guidance(
    task: Optional[str],
    duration: Optional[float],
    reference_manifest: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Exact MiniMax H3 Context-IR alignment rules for the active task."""
    seconds = max(0.0, float(duration or 0.0))
    end_time = f"{seconds:.2f}"
    if task == "ref2va":
        entries = []
        for item in reference_manifest or []:
            label = str(item.get("label") or "").strip()
            kind = str(item.get("kind") or "reference")
            if not label:
                continue
            if kind == "video_audio":
                meaning = "the soundtrack extracted from the same-numbered reference video"
            elif kind == "video":
                meaning = "reference video frames"
            elif kind == "image":
                meaning = "reference image"
            else:
                meaning = "standalone reference audio"
            entries.append(f"- <{label}>: {meaning}")
        mapping = "\n".join(entries) or "- No references were supplied (invalid request)."
        return (
            "This is REF2VA. Do not write first-frame, last-frame, or timeline-alignment instructions. "
            "Begin directly with integrated_multimodal_description. The model receives references in "
            "the exact presentation order below; these tags are positional and must not be renamed, "
            "renumbered, swapped, or described as keyframes:\n"
            f"{mapping}\n"
            "Use every listed tag at least once in integrated_multimodal_description. State concretely "
            "what identity, appearance, style, motion, camera behavior, or voice each reference controls. "
            "A paired <Audio N> appears immediately before its matching <Video N> in the model input, "
            "but they remain distinct tags and should be assigned distinct audio/video roles."
        )
    if task == "i2va":
        return (
            "This is I2VA. The output MUST begin with this exact line, followed by one blank line:\n"
            "For the target video, at 0.00 seconds into the target video, <Picture 1> "
            "(from [Shot 1]) is fully referenced.\n"
            "Start Shot 1 by anchoring its style, subjects, composition, scene, colors, key objects, "
            "and spatial relationships to Picture 1, then describe action onset, continuous development, "
            "and the result or reaction. Preserve visual identity and layout."
        )
    if task == "fl2va":
        return (
            "This is FL2VA. Prefer one continuous shot unless the user explicitly requests cuts. The "
            "output MUST begin with an alignment line in exactly this form, followed by one blank line:\n"
            "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns "
            f"with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the {end_time}-second mark of the target video.\n"
            "Replace N with the actual final shot number (normally 1). Describe the observable path from "
            "Picture 1 through intermediate changes until pose, objects, composition, camera, and lighting "
            "land on Picture 2 at the end; do not merely describe two static images."
        )
    if task == "l2va":
        return (
            "This is L2VA. The output MUST begin with an alignment line in exactly this form, followed by one blank line:\n"
            "How the reference pictures align with the target video — <Picture 1> (from [Shot N]) "
            f"aligns with the {end_time}-second mark of the target video.\n"
            "Replace N with the actual final shot number. Infer a plausible preceding state and describe "
            "a continuous path that converges on Picture 1's exact final composition."
        )
    return (
        "This is T2VA. Do not add an image-alignment instruction; begin directly with "
        "integrated_multimodal_description. Build the complete audiovisual timeline from the user's text."
    )


def _h3_audio_guidance(generate_audio: bool) -> str:
    if generate_audio:
        return (
            "Audio generation is enabled. Preserve requested dialogue verbatim and describe requested "
            "ambience, physical sounds, and score in their proper sections. Do not invent dialogue or music."
        )
    return (
        "Audio generation is disabled. Keep the three required fields, but write overall_soundscape: N/A "
        "and non_diegetic_music: N/A. Describe visible speaking or sound-causing actions only as visible "
        "motion; do not invent audio content."
    )


_H3_DIALOGUE_BLOCK_RE = re.compile(r"<d>.*?</d>", re.IGNORECASE | re.DOTALL)
_H3_DIALOGUE_INTENT_RE = re.compile(
    r"\b(?:dialogue|voiceover|narration|narrator|speaks?|says?|asks?|replies?|"
    r"shouts?|whispers?|yells?|sings?|chants?)\b",
    re.IGNORECASE,
)
_H3_NEGATED_DIALOGUE_RE = re.compile(
    r"\b(?:(?:no|without)\s+(?:spoken\s+)?(?:dialogue|speech|voiceover|narration|singing)|"
    r"(?:does\s+not|doesn't|never)\s+(?:speak|say|sing|narrate))\b",
    re.IGNORECASE,
)
_H3_VISIBLE_TEXT_ATTRIBUTION_RE = re.compile(
    r"\b(?:sign|banner|label|screen|poster|caption|subtitle|text)\s+"
    r"(?:reads?|says?|shows?|displays?)\b",
    re.IGNORECASE,
)
_H3_SCRIPT_LINE_RE = re.compile(r"(?m)^\s*[A-Z][A-Z0-9 _-]{0,30}:\s*\S+")


def _h3_input_has_dialogue(prompt: str) -> bool:
    """Whether the user actually supplied or requested spoken words."""
    if _H3_DIALOGUE_BLOCK_RE.search(prompt):
        return True
    without_negations = _H3_NEGATED_DIALOGUE_RE.sub("", prompt)
    without_visible_text = _H3_VISIBLE_TEXT_ATTRIBUTION_RE.sub("", without_negations)
    return bool(
        _H3_DIALOGUE_INTENT_RE.search(without_visible_text)
        or _H3_SCRIPT_LINE_RE.search(without_visible_text)
    )


def _h3_dialogue_guidance(prompt: str) -> str:
    if not _h3_input_has_dialogue(prompt):
        return (
            "NO DIALOGUE: The user's input contains no requested spoken, sung, narrated, or "
            "voiceover words. Do not introduce speaker IDs, speech attribution, <d> blocks, "
            "singing, narration, or voiceover. Do not turn visible text into speech. Characters "
            "produce no intelligible words unless the user explicitly supplied them. If the user "
            "requested visible talking without supplying words, describe only the visible nonverbal "
            "performance and do not compose a line."
        )
    return (
        "PRESERVING DIALOGUE: Use only spoken, sung, narrated, or voiceover words explicitly "
        "supplied by the user. Never compose, complete, paraphrase, or infer a line. Preserve the "
        "original language and every word and punctuation mark. Give each speaker a stable ID such "
        "as (S1), reused across shots. Put delivery outside the dialogue block and the exact supplied "
        "words inside <d>[Language] ...</d>. For voiceover, use the exact phrase \"says in an "
        "off-screen voiceover\" and immediately state that the corresponding on-screen character's "
        "lips remain completely closed. Use <scenetrans> for a supplied line continuing across a cut "
        "and <cutoff> when supplied speech is truncated by the video ending."
    )

# Raster formats we can hand to a VLM. Source frames in other formats (or video)
# are simply not shown — enhancement falls back to the text-only path.
_VLM_IMAGE_FORMATS = frozenset({"jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff"})

# The frontend swaps real [bracketed] spans for __VERBATIM_A__ placeholders before
# enhancement and restores them after, so a legitimate token always echoes one in
# the input prompt.
_VERBATIM_TOKEN_RE = re.compile(r"__VERBATIM_[A-Z]__")

# A double-quoted span (straight or curly) signals dialogue the user wants spoken.
# Single quotes are excluded — contractions ("don't", "she's") would false-positive.
_DIALOGUE_QUOTE_RE = re.compile(r'["“][^"“”]+["”]')


def _protected_text_guidance(
    prompt: str, *, keyword_mode: bool = False, cinematography: bool = False,
    audio_conditioned: bool = False, audio_disabled: bool = False,
) -> str:
    """Build the 'PRESERVING PROTECTED TEXT' block for the spans actually present.

    The improve_* system prompts carry a ``{protected_text_guidance}`` slot that
    this fills per request. We only tell the model about the kinds of protected
    span this prompt actually contains — guidance about placeholders/brackets/
    wildcards the user never used is pure distraction, and a fast model can latch
    onto it (e.g. inventing a bare ``__VERBATIM_A__`` token that then reaches the
    image model). Returns "" for a plain prose prompt so it gets no such chatter.
    ``keyword_mode`` adds the comma-separated-tag nuance the SD1.5/SDXL prompt needs.
    ``cinematography`` adds a dialogue bullet when the prompt quotes spoken lines —
    the video prompt's motion-only framing otherwise drops the words and keeps only
    the lip movement. ``audio_conditioned`` keeps that bullet but drops the claim
    that the model voices the line: with a supplied track it doesn't, and the words
    are there to align the visible performance.
    """
    bullets: List[str] = []
    if cinematography and _DIALOGUE_QUOTE_RE.search(prompt):
        if audio_disabled:
            bullets.append(
                '- Quoted dialogue (e.g. she says, "..."): keep the words exactly as written and '
                "attribute them to the speaker as a visible performance cue, but do not claim the "
                "audio-disabled model will voice them."
            )
        elif audio_conditioned:
            bullets.append(
                '- Quoted dialogue (e.g. she says, "..."): keep the spoken words exactly as '
                "written and attribute them to the speaker — they mark what is being said in "
                "the supplied audio, so the visible performance lines up with it."
            )
        else:
            bullets.append(
                '- Quoted dialogue (e.g. she says, "..."): keep the spoken words exactly as '
                "written and present them as a spoken line — they are content the video model "
                'voices, never motion to mime (don\'t reduce them to "her lips move").'
            )
    if _VERBATIM_TOKEN_RE.search(prompt):
        bullets.append(
            "- Placeholder tokens of the form __VERBATIM_A__, __VERBATIM_B__ … "
            "(always __VERBATIM_ + one capital letter + __). Copy each through exactly, "
            "as an opaque object — never translate it, renumber it, rephrase around it, "
            'or turn it into the word "verbatim".'
        )
    if re.search(r"\[[^\[\]]+\]", prompt):
        bullets.append("- [Bracketed text]: keep the brackets and their contents exactly as written.")
    if re.search(r"\{[^{}]+\}", prompt):
        bullets.append("- {a|b|c} and {{name}} wildcards: keep the braces and structure intact.")
    if any(line.lstrip().startswith("#") for line in prompt.splitlines()):
        bullets.append(
            "- Lines starting with '#' are notes to you — follow them, but never include them in your output."
        )

    if not bullets:
        return ""

    lead = "Carry each one into your output unchanged"
    lead += ", each as its own comma-separated tag:" if keyword_mode else ":"
    return "PRESERVING PROTECTED TEXT\nThe prompt contains protected spans. " + lead + "\n" + "\n".join(bullets)


def _strip_hallucinated_placeholders(output: str, source: str) -> str:
    """Drop __VERBATIM_X__ tokens the model invented (absent from the input).

    A token present only in the output is a hallucination — left in, it reaches the
    image model as literal garbage (and can fail the job with 'Invalid params').
    Remove each one and tidy the whitespace it leaves behind. Tokens that echo the
    input are real placeholders and pass through untouched.
    """
    allowed = set(_VERBATIM_TOKEN_RE.findall(source))
    hallucinated = sorted({t for t in _VERBATIM_TOKEN_RE.findall(output) if t not in allowed})
    if not hallucinated:
        return output

    log.warning(f"improve: stripped hallucinated placeholder(s) {hallucinated} from model output")
    cleaned = output
    for tok in hallucinated:
        # [ \t]* (not \s*) so we don't merge across newlines into comment/other lines.
        cleaned = re.sub(r"[ \t]*" + re.escape(tok) + r"[ \t]*", " ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


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
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


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
    # Whether the tool outputs audio (text-to-audio / music / sound / speech).
    # Authoritative for the sound-focused audio style — like is_video, the task is
    # known, so routing doesn't depend on recognizing the model string.
    is_audio: bool = False
    # Number of input images the tool will edit (image-to-image / inpaint / edit).
    # >0 on a natural-language image model routes to the edit style, which frames
    # the prompt as an instruction over the input image(s) rather than a fresh
    # scene to describe. 0 for text-to-image. Ignored for video/keyword/ideogram.
    input_image_count: int = 0
    # Whether the tool is generating against a supplied audio track (LTX
    # image+audio-to-video, lip-sync, avatar). On the cinematography path this
    # flips the soundtrack instruction: the model reproduces the track rather than
    # scoring the clip, so invented sound design and dialogue are wrong.
    audio_conditioned: bool = False
    # For image-to-video: the library id of the source/first frame. When present
    # on the cinematography path, the frame is shown to the model so the prompt
    # animates the real image. Ignored for other styles.
    media_id: Optional[int] = None
    # MiniMax H3's local base model consumes a task-specific Context-IR shape.
    # These are derived from the live generation parameters by the submit route.
    h3_task: Optional[str] = None
    h3_duration: Optional[float] = None
    h3_media_ids: List[Optional[int]] = Field(default_factory=list)
    h3_reference_manifest: List[Dict[str, Any]] = Field(default_factory=list)
    h3_generate_audio: bool = True
    # Library ids of the tool's input images in presentation order (None for
    # an input that isn't a library item). Qwen-Image-2.1 edits address inputs
    # positionally as <image1>, <image2>, ..., so its enhancer is shown them.
    input_media_ids: List[Optional[int]] = Field(default_factory=list)
    # Target canvas, when known. Qwen-Image-2.1's rewriter composes the frame
    # for its orientation rather than guessing one.
    width: Optional[int] = None
    height: Optional[int] = None
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


class ImprovePromptResponse(BaseModel):
    improved_prompt: str


# Language code → English name for the Translate control. Mirrors the
# frontend's promptLanguages.ts (code/english pairs); used by in-process
# callers (post-processing chain executor) that hold the stored code.
PROMPT_LANGUAGE_ENGLISH_BY_CODE = {
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
}


class TranslatePromptRequest(BaseModel):
    prompt: str
    # The target language as a human-readable English name, e.g. "Simplified
    # Chinese" — the frontend maps its language code to this before sending.
    target_language: str
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


class TranslatePromptResponse(BaseModel):
    translated_prompt: str


class IdeogramJsonRequest(BaseModel):
    prompt: str
    # Target canvas, so the model can compose layout / bounding boxes for the
    # real aspect ratio rather than guessing. Optional — falls back to 1:1.
    width: Optional[int] = None
    height: Optional[int] = None
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


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
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


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
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


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
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


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
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
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
        except EntitlementError as e:
            raise _entitlement_http_exception(e)
        except Exception as e:
            log.error(
                "Prompt enhancement error",
                error_type=type(e).__name__,
            )
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
    if not request.prompt.strip():
        # Nothing to improve (e.g. a tool with no prompt input) — don't spend
        # an LLM call asking the model to improve an empty string.
        return ImprovePromptResponse(improved_prompt=request.prompt)

    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    try:
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

    # Pick the enhancement style. Task drives video (cinematography) and edits
    # (input images on a natural-language model); model family drives the rest
    # (keyword / ideogram / prose). Falls back to prose for unknown families and
    # missing model strings.
    mode = enhancement_mode(
        model_family(request.model),
        is_video=request.is_video,
        is_image_edit=request.input_image_count > 0,
        is_audio=request.is_audio,
    )

    # i2v: on the cinematography path, show the source frame to the model so the
    # prompt animates the real image. Best-effort — if the frame can't be loaded
    # we fall back to the text-only cinematography prompt.
    source_images_b64: List[tuple[int, str]] = []
    if mode == "minimax-h3":
        for picture_number, media_id in enumerate(request.h3_media_ids, start=1):
            if media_id is None:
                continue
            loaded = await _load_source_image_b64(session, media_id)
            if loaded:
                source_images_b64.append((picture_number, loaded))
    elif mode == "qwen-image-2.1-edit":
        for image_number, media_id in enumerate(request.input_media_ids, start=1):
            if media_id is None:
                continue
            loaded = await _load_source_image_b64(session, media_id)
            if loaded:
                source_images_b64.append((image_number, loaded))
    elif mode == "cinematography" and request.media_id is not None:
        loaded = await _load_source_image_b64(session, request.media_id)
        if loaded:
            source_images_b64.append((1, loaded))

    prompt_key = _IMPROVE_PROMPT_BY_MODE.get(mode, "improve_system_prompt")
    if source_images_b64 and mode == "cinematography":
        prompt_key = "improve_cinematography_image_system_prompt"
    prompt_from_file = get_prompt("prompt_enhancement", prompt_key)
    if not prompt_from_file and prompt_key != "improve_system_prompt":
        # A family-specific prompt isn't configured — fall back to prose.
        prompt_from_file = get_prompt("prompt_enhancement", "improve_system_prompt")
    system_prompt = prompt_from_file if prompt_from_file else DEFAULT_IMPROVE_SYSTEM_PROMPT
    # Fill the input-image count (edit prompt only — no-op elsewhere), then the
    # protected-text slot with guidance ONLY for spans this prompt actually
    # contains; collapse the blank lines the slot leaves behind when it's empty.
    system_prompt = system_prompt.replace(
        "{input_images_desc}", _input_images_phrase(request.input_image_count)
    )
    system_prompt = system_prompt.replace(
        "{qwen_image_refs}", _qwen_image_refs_phrase(request.input_image_count)
    )
    system_prompt = system_prompt.replace(
        "{canvas_guidance}", _qwen_canvas_guidance(request.width, request.height)
    )
    system_prompt = system_prompt.replace(
        "{audio_guidance}",
        _audio_guidance(
            audio_conditioned=request.audio_conditioned,
            image_variant=bool(source_images_b64),
        ),
    )
    system_prompt = system_prompt.replace(
        "{h3_task_guidance}", _h3_task_guidance(
            request.h3_task, request.h3_duration, request.h3_reference_manifest
        )
    )
    system_prompt = system_prompt.replace(
        "{h3_audio_guidance}", _h3_audio_guidance(request.h3_generate_audio)
    )
    system_prompt = system_prompt.replace(
        "{h3_dialogue_guidance}", _h3_dialogue_guidance(request.prompt)
    )
    system_prompt = system_prompt.replace(
        "{protected_text_guidance}",
        _protected_text_guidance(
            request.prompt,
            keyword_mode=(mode == "keyword"),
            cinematography=(mode in {"cinematography", "minimax-h3"}),
            audio_conditioned=request.audio_conditioned,
            audio_disabled=(mode == "minimax-h3" and not request.h3_generate_audio),
        ),
    )
    system_prompt = re.sub(r"\n{3,}", "\n\n", system_prompt)
    log.info(
        f"Prompt improve mode={mode} images={len(source_images_b64)} "
        f"audio_conditioned={request.audio_conditioned}"
    )

    # Build the user message
    if mode == "minimax-h3":
        instr = (f"\n\nAdditional instructions: {request.instructions.strip()}"
                 if request.instructions and request.instructions.strip() else "")
        user_content = (
            f"Rewrite this request as MiniMax H3 {str(request.h3_task or 't2va').upper()} "
            f"Context-IR for a {float(request.h3_duration or 0):.2f}-second target video. "
            "Return only the final model prompt:\n\n"
            f"{request.prompt}{instr}"
        )
    elif mode == "qwen-image-2.1-edit":
        instr = (f"\n\nAdditional instructions: {request.instructions.strip()}"
                 if request.instructions and request.instructions.strip() else "")
        user_content = (
            f"Rewrite this Qwen-Image-2.1 edit request. The model receives "
            f"{_qwen_image_refs_phrase(request.input_image_count)}"
            + (" (attached below, labeled)" if source_images_b64 else "")
            + ". Return only the final model prompt:\n\n"
            f"{request.prompt}{instr}"
        )
    elif mode == "qwen-image-2.1":
        instr = (f"\n\nAdditional instructions: {request.instructions.strip()}"
                 if request.instructions and request.instructions.strip() else "")
        user_content = (
            "Rewrite this request as a Qwen-Image-2.1 text-to-image prompt. "
            f"Return only the final model prompt:\n\n{request.prompt}{instr}"
        )
    elif source_images_b64:
        # i2v: the attached frame is reference; the user's text is direction for
        # the clip, to be turned into motion/camera — not a prompt to "improve".
        instr = (f"\n\nAdditional instructions: {request.instructions.strip()}"
                 if request.instructions and request.instructions.strip() else "")
        user_content = (
            "The image is the first frame. Here is the user's direction for the clip — "
            f"turn it into shot direction (motion and camera):\n\n{request.prompt}{instr}"
        )
    elif mode == "edit":
        # The user's text is an instruction applied to the input image(s) the model
        # already sees — refine it as an edit instruction, not a scene description.
        instr = (f"\n\nAdditional instructions: {request.instructions.strip()}"
                 if request.instructions and request.instructions.strip() else "")
        user_content = f"Refine this image-edit instruction:\n\n{request.prompt}{instr}"
    elif request.instructions and request.instructions.strip():
        user_content = f"Please improve this prompt according to these instructions:\n\nInstructions: {request.instructions}\n\nPrompt:\n{request.prompt}"
    else:
        user_content = f"Please improve this prompt with a light touch:\n\n{request.prompt}"

    if source_images_b64:
        # Multimodal: H3 may carry first and last frames; generic I2V carries one.
        image_parts = []
        for picture_number, image_b64 in source_images_b64:
            if mode == "minimax-h3":
                role = (
                    "reference image"
                    if request.h3_task == "ref2va"
                    else ("first frame" if picture_number == 1 else "last frame")
                )
                image_parts.append({"type": "text", "text": f"Picture {picture_number} ({role}):"})
            elif mode == "qwen-image-2.1-edit":
                image_parts.append({"type": "text", "text": f"<image{picture_number}>:"})
            image_parts.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_content},
                *image_parts,
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

            # Safety net: a fast model can still emit a placeholder token that was
            # never in the input. Strip it before it reaches the image model.
            improved_prompt = _strip_hallucinated_placeholders(improved_prompt, request.prompt)

            log.info(f"Prompt improve successful ({len(improved_prompt)} chars)")

            return ImprovePromptResponse(improved_prompt=improved_prompt)

        except asyncio.TimeoutError:
            log.error("Prompt improve request timed out")
            raise HTTPException(status_code=504, detail="Request timed out")
        except EntitlementError as e:
            raise _entitlement_http_exception(e)
        except Exception as e:
            log.error(
                "Prompt improve error",
                error_type=type(e).__name__,
            )
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

    if not request.prompt.strip():
        # Nothing to translate (e.g. a tool with no prompt input).
        return TranslatePromptResponse(translated_prompt=request.prompt)

    try:
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
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
        except EntitlementError as e:
            raise _entitlement_http_exception(e)
        except Exception as e:
            log.error(
                "Prompt translate error",
                error_type=type(e).__name__,
            )
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
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
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
                log.error(
                    "Ideogram JSON parse failed",
                    error_type=type(e).__name__,
                    output_chars=len(raw or ""),
                )
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
        except EntitlementError as e:
            raise _entitlement_http_exception(e)
        except Exception as e:
            log.error(
                "Ideogram JSON error",
                error_type=type(e).__name__,
            )
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
        log.error(
            "Categories response could not be parsed",
            output_chars=len(response_content or ""),
        )
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
        log.error(
            "Failed to parse options JSON",
            output_chars=len(response_content or ""),
        )
        return [], None

    return options, None


@router.post("/suggest-categories", response_model=SuggestCategoriesResponse)
async def suggest_categories(request: SuggestCategoriesRequest):
    """
    Phase 1: Analyze prompt and return relevant category dimensions.
    Fast call with low temperature.
    """
    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    try:
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

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
            "model": llm_config.get_model(),
            "api_base": llm_config.get_api_base(),
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
                    log.warning(
                        "Suggest-categories detected refusal",
                        refusal_chars=len(refusal),
                    )
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
        log.error(
            "Suggest-categories error",
            error_type=type(e).__name__,
        )
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
                    project_id=request.project_id,
                )
            )
        )

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    def _llm_error_detail(result) -> Optional[dict]:
        if not isinstance(result, HTTPException):
            return None
        detail = result.detail
        if isinstance(detail, dict) and str(detail.get("code", "")).startswith("llm_"):
            return detail
        return None

    # Every category failing on LLM availability is one problem, not N —
    # surface the coded error so the client shows the configure/top-up CTA.
    if gathered and all(_llm_error_detail(r) for r in gathered):
        raise gathered[0]

    results: List[SuggestOptionsResponse] = []

    for category, result in zip(request.categories, gathered):
        if isinstance(result, Exception):
            log.error(
                "Suggest-options batch failed",
                category_chars=len(category.category or ""),
                label_chars=len(category.label or ""),
                error_type=type(result).__name__,
            )
            detail = _llm_error_detail(result)
            results.append(SuggestOptionsResponse(
                category=category.category,
                label=category.label,
                subitems=[],
                allow_wildcard=category.allow_wildcard,
                message=detail.get("message") if detail else str(result),
            ))
        else:
            results.append(result)

    return SuggestOptionsBatchResponse(results=results)


async def _suggest_options_impl(request: SuggestOptionsRequest) -> SuggestOptionsResponse:
    """Shared suggest-options implementation for single and batch endpoints."""
    from llm_resolver import LLMUnavailableError, get_effective_llm_config

    try:
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e)},
        )

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
            "model": llm_config.get_model(),
            "api_base": llm_config.get_api_base(),
        }

    try:
        log.info(
            "Suggest-options starting",
            category_chars=len(request.category.category or ""),
            label_chars=len(request.category.label or ""),
            exclude_count=len(request.exclude),
        )

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
            log.warning(
                "Suggest-options detected refusal",
                category_chars=len(request.category.category or ""),
                refusal_chars=len(refusal),
            )
            return SuggestOptionsResponse(
                category=request.category.category,
                label=request.category.label,
                subitems=[],
                allow_wildcard=request.category.allow_wildcard,
                debug=debug_info,
                message=refusal
            )

        log.info(
            "Suggest-options returning",
            option_count=len(options),
            category_chars=len(request.category.category or ""),
        )
        return SuggestOptionsResponse(
            category=request.category.category,
            label=request.category.label,
            subitems=options,
            allow_wildcard=request.category.allow_wildcard,
            debug=debug_info
        )

    except asyncio.TimeoutError:
        log.error(
            "Suggest-options request timed out",
            category_chars=len(request.category.category or ""),
        )
        raise HTTPException(status_code=504, detail="Request timed out")
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Suggest-options error",
            category_chars=len(request.category.category or ""),
            error_type=type(e).__name__,
        )
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
    # Per-request thinking toggle. Off by default: this is a fast, tool-driven
    # editor agent, and on a think-by-default endpoint (e.g. a Qwen3 reasoner)
    # leaving it on makes every trivial step spend seconds on scratchpad and can
    # blow the token budget on reasoning alone — returning empty content, a
    # silent no-op. Callers opt in explicitly when they want the model to reason.
    thinking: bool = False
    # Stable id for the whole editor conversation, for caching + trace grouping.
    session_id: Optional[str] = None
    # Dev-mode diagnostic: when true, the response carries a `debug` trace
    # (resolved model/api_base, the full message list sent to the LLM, and the
    # raw response text) so a failed/refused step can be copied into a bug report.
    debug: bool = False
    # Project whose model override should apply, when the editor is scoped
    # to one. Absent -> the profile's Tool Assistant setting.
    project_id: Optional[int] = None


class AgentStepResponse(BaseModel):
    message: str
    tool_calls: List[AgentToolCall] = []
    thinking: Optional[str] = None
    # True when this step produced no tool calls and its text reads as a
    # textual refusal (see refusal_detection.is_refusal) rather than a normal
    # final reply.
    refused: bool = False
    debug: Optional[dict] = None


# vLLM reports its enforced window in the 400 body when the configured window
# is stale.  Remember that smaller cap for the lifetime of this backend process
# so one mismatch costs at most one rejected request and later turns compact
# before they reach the endpoint.  The key never leaves this process or enters
# a prompt/cache prefix.
_PROMPT_AGENT_CONTEXT_CAPS: dict[tuple[str, str], int] = {}
_CONTEXT_LIMIT_PATTERNS = (
    re.compile(r"maximum context length is\s*([\d,]+)\s*tokens", re.IGNORECASE),
    re.compile(r"max(?:imum)?[_ -]?model[_ -]?len(?:gth)?[^\d]{0,20}([\d,]+)", re.IGNORECASE),
)


def _prompt_agent_context_key(config) -> tuple[str, str]:
    return (
        str(config.get_api_base() or "").rstrip("/"),
        str(config.get_model() or ""),
    )


def _reported_provider_context_limit(exc: Exception) -> Optional[int]:
    """Extract a provider-enforced context window from a rejected response."""
    response = getattr(exc, "response", None)
    if response is None or getattr(response, "status_code", None) not in {400, 413, 422}:
        return None
    try:
        body = response.text or ""
    except Exception:
        return None
    for pattern in _CONTEXT_LIMIT_PATTERNS:
        match = pattern.search(body)
        if not match:
            continue
        try:
            limit = int(match.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if limit >= 1024:
            return limit
    return None


def _prompt_agent_max_tokens(max_context_tokens: int) -> int:
    """Keep reasoning headroom without claiming most of a small window."""
    from agent.v2.conversation import response_reserve

    reserve = response_reserve(max_context_tokens)
    return min(max(reserve, 16_384), max(reserve, max_context_tokens // 4))


def _prepare_prompt_agent_request(
    *,
    conversation_history: List[dict],
    system_prompt: str,
    reminders: List[str],
    tools: List[dict],
    max_context_tokens: int,
) -> tuple[List[dict], int]:
    """Build one cache-friendly, context-bounded ToolView LLM request.

    Stable data stays stable and first: system prompt, tool schemas, then old
    conversation turns.  Volatile editor state and time are injected only on
    the final user message after compaction.  Tool definitions count toward
    the provider's input even though they are outside ``messages``.
    """
    from agent.v2.conversation import (
        _apply_token_budget_strict,
        _estimate_tokens,
        _inject_last_user_context,
    )

    max_context_tokens = max(1024, int(max_context_tokens))
    max_tokens = _prompt_agent_max_tokens(max_context_tokens)
    fixed = _estimate_tokens([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(reminders)},
    ])
    # Function definitions are serialized outside the messages list but vLLM
    # tokenizes them as part of the prompt.  Match the main chat agent's
    # conservative JSON-size estimate and retain the shared 20% safety margin.
    tools_overhead = len(json.dumps(tools)) // 4 if tools else 0
    history_budget = max(
        0,
        int(max_context_tokens * 0.80)
        - fixed["total"]
        - tools_overhead
        - max_tokens,
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages += [dict(message) for message in conversation_history]
    messages = _apply_token_budget_strict(messages, budget=history_budget)
    _inject_last_user_context(messages, reminders)
    return messages, max_tokens


@router.post("/agent/step", response_model=AgentStepResponse)
async def agent_step(request: AgentStepRequest):
    """One step of the prompt-editor mini-agent.

    Stateless: the frontend owns the conversation and executes tool calls. We
    resolve the agent-fast model, inject a fresh live-state snapshot, trim the
    middle of the history to the real context window, and return the model's
    next assistant message (text + tool_calls).
    """
    from llm import llm_completion, QuotaExceededError, ContentFilteredError, EntitlementError
    from llm_resolver import LLMUnavailableError, get_effective_llm_config
    from prompt_agent_tools import TOOL_SCHEMAS
    # Reuse the shared agent LLM infrastructure — thinking options, output
    # reserve, drop-the-middle compaction, and last-user-message reminder
    # injection are all the same helpers the v2 agent uses.
    from agent.v2.llm_options import agent_llm_options

    try:
        llm_config = await get_effective_llm_config('tool_assistant', request.project_id)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=e.status_code, detail={"code": e.code, "message": str(e)})

    system_prompt = get_prompt("prompt_enhancement", "agent_system_prompt")
    if not system_prompt:
        raise HTTPException(status_code=500, detail="agent_system_prompt not configured")

    # The live screen state rides as a <system-reminder> on the LAST user message
    # (the established pattern — see system_reminders.py), NOT a second system
    # message. This keeps the system prompt prefix stable for caching, keeps the
    # volatile state at the tail, and never persists it into stored history.
    #
    # Skill guidance (bodies of installed skills targeting this tool, computed
    # by the frontend alongside the rest of state_context) is markdown, not
    # state — pop it out of the JSON snapshot and deliver it as its own
    # reminder so it reads as instructions rather than data.
    state_context = dict(request.state_context)
    skill_guidance = None
    notes = state_context.get("notes")
    if isinstance(notes, dict) and notes.get("skill_guidance"):
        notes = dict(notes)
        skill_guidance = str(notes.pop("skill_guidance"))
        state_context["notes"] = notes
    state_json = json.dumps(state_context, ensure_ascii=False, indent=2)
    state_reminder = (
        "<system-reminder>\n"
        "Editor screen state at the START of this turn (before any tools you call now). "
        "After you call tools, rely on the tool results for what changed — describe what YOU "
        "changed, and don't say something is 'already' set if your own tool calls just set it.\n"
        f"```json\n{state_json}\n```\n"
        "</system-reminder>"
    )
    reminders = [state_reminder]
    if skill_guidance:
        reminders.append(
            "<system-reminder>\n"
            "Skill guidance for this tool (from the user's installed skills):\n\n"
            f"{skill_guidance}\n"
            "</system-reminder>"
        )

    configured_max_ctx = int(
        getattr(llm_config, "max_context_tokens", 128_000) or 128_000
    )
    context_key = _prompt_agent_context_key(llm_config)
    learned_cap = _PROMPT_AGENT_CONTEXT_CAPS.get(context_key)
    max_ctx = min(configured_max_ctx, learned_cap) if learned_cap else configured_max_ctx
    messages, max_tokens = _prepare_prompt_agent_request(
        conversation_history=request.conversation_history,
        system_prompt=system_prompt,
        reminders=reminders,
        tools=TOOL_SCHEMAS,
        max_context_tokens=max_ctx,
    )

    # Dev-mode diagnostic trace (see AgentStepRequest.debug). Built once, before
    # the LLM call, so it's available in every return path — success, refusal,
    # and every exception branch below — with raw_response/error_type filled in
    # as each path learns them.
    debug_info: Optional[dict] = None
    if request.debug:
        debug_info = {
            "model": llm_config.get_model(),
            "api_base": llm_config.get_api_base(),
            "messages": [dict(m) for m in messages],
            "raw_response": None,
            "error_type": None,
        }

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
            async def _complete():
                return await llm_completion(
                    config=llm_config,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    max_tokens=max_tokens,
                    # Stable system/tool prefix + state on the final user message
                    # preserves vLLM prefix caching across turns.
                    cacheable=True,
                    session_id=request.session_id,
                    **agent_llm_options(enable_thinking=request.thinking),
                )

            try:
                resp = await _complete()
            except Exception as first_error:
                reported_cap = _reported_provider_context_limit(first_error)
                if not reported_cap or reported_cap >= max_ctx:
                    raise

                # A local runtime can enforce a smaller --max-model-len than its
                # Stimma setting advertises. Learn the supplier's explicit cap,
                # rebuild from the original history, and retry once. Nothing is
                # inserted before the stable prompt/tool prefix.
                _PROMPT_AGENT_CONTEXT_CAPS[context_key] = reported_cap
                max_ctx = reported_cap
                messages, max_tokens = _prepare_prompt_agent_request(
                    conversation_history=request.conversation_history,
                    system_prompt=system_prompt,
                    reminders=reminders,
                    tools=TOOL_SCHEMAS,
                    max_context_tokens=max_ctx,
                )
                if debug_info is not None:
                    debug_info["messages"] = [dict(message) for message in messages]
                log.warning(
                    "Prompt-agent learned a smaller provider context window; "
                    "compacted and retrying",
                    configured_context=configured_max_ctx,
                    provider_context=reported_cap,
                )
                resp = await _complete()
            tool_calls = [AgentToolCall(id=tc.id, name=tc.name, arguments=tc.arguments) for tc in resp.tool_calls]
            if debug_info:
                debug_info["raw_response"] = resp.content

            # Shared refusal classifier: only the categorical label egresses.
            from refusal_detection import is_refusal
            refused = not tool_calls and is_refusal(resp.content)
            if refused:
                _track_step("failed", error_type="refusal")
                if debug_info:
                    debug_info["error_type"] = "refusal"
            else:
                _track_step("completed")
            return AgentStepResponse(
                message=resp.content or "",
                tool_calls=tool_calls,
                thinking=resp.thinking,
                refused=refused,
                debug=debug_info,
            )
        except asyncio.TimeoutError:
            log.error("Prompt-agent step timed out")
            _track_step("timeout")
            if debug_info:
                debug_info["error_type"] = "timeout"
                raise HTTPException(
                    status_code=504,
                    detail={"message": "The request timed out. Try again.", "debug": debug_info},
                )
            raise HTTPException(status_code=504, detail="The request timed out. Try again.")
        except ContentFilteredError as e:
            log.warning("Prompt-agent step content-filtered")
            _track_step("failed", error_type="content_filtered")
            message = "The model declined this request (content filter). Try rephrasing."
            if debug_info:
                debug_info["error_type"] = "content_filtered"
                debug_info["raw_response"] = getattr(e, "upstream_message", None)
                raise HTTPException(status_code=422, detail={"message": message, "debug": debug_info})
            raise HTTPException(status_code=422, detail=message)
        except QuotaExceededError as e:
            log.warning("Prompt-agent step quota exceeded")
            _track_step("failed", error_type="quota_exceeded")
            message = str(e) or "LLM quota exceeded. Check your plan or usage and try again."
            if debug_info:
                debug_info["error_type"] = "quota_exceeded"
                debug_info["raw_response"] = getattr(e, "upstream_message", None)
                raise HTTPException(status_code=429, detail={"message": message, "debug": debug_info})
            raise HTTPException(status_code=429, detail=message)
        except EntitlementError as e:
            log.warning("Prompt-agent step: no active subscription")
            _track_step("failed", error_type="subscription_required")
            message = str(e) or "No active Stimma subscription."
            if debug_info:
                debug_info["error_type"] = "subscription_required"
                raise HTTPException(status_code=402, detail={"code": "subscription_required", "message": message, "debug": debug_info})
            raise HTTPException(status_code=402, detail={"code": "subscription_required", "message": message})
        except Exception as e:
            log.error(
                "Prompt-agent step error",
                error_type=type(e).__name__,
            )
            error_type = classify_agent_error(e)
            _track_step("failed", error_type=error_type)
            if debug_info:
                debug_info["error_type"] = error_type
                raise HTTPException(status_code=500, detail={"message": str(e), "debug": debug_info})
            raise HTTPException(status_code=500, detail=str(e))

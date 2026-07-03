"""Server-side generate-time prompt pipeline.

The exact counterpart of the frontend's interactive pipeline
(frontend/src/utils/promptProcessor.ts + useSubmissionQueue.ts), for
generations that run with no client attached (post-processing chain steps).
The behavior must stay in lockstep with the client implementation — users
expect a chain-step prompt to be treated identically to one submitted from
the editor:

  1. Enhance (autoImprove) — family-aware LLM rewrite with [verbatim]
     protection and a 3-attempt retry when placeholders get dropped
     (falls back to the original prompt, like improveViaApi).
     Skipped in Ideogram JSON mode — that runs post-resolve (step 4).
  2. Translate — same verbatim protection; unknown language codes are a
     no-op (mirrors translateViaApi).
  3. Final processing — expand {{name}} (segments first, then wildcards),
     strip # comments, unwrap [verbatim], expand inline {a|b|c}.
  4. Ideogram JSON — when Enhance is on and the tool is Ideogram 4,
     convert the fully-resolved prompt to structured JSON (final step).

All steps are non-destructive: the stored step prompt is untouched; only
the prompt actually sent to the tool is transformed.
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger

log = get_logger(__name__)

# Matches improveViaApi/translateViaApi in useSubmissionQueue.ts.
_MAX_LLM_RETRIES = 3


# --- promptProcessor.ts ports -------------------------------------------------

def extract_verbatim(prompt: str) -> Tuple[str, List[Dict[str, str]]]:
    """Extract [verbatim] segments and replace with placeholders (before LLM)."""
    segments: List[Dict[str, str]] = []

    def _repl(match: re.Match) -> str:
        placeholder = f"__VERBATIM_{chr(65 + len(segments))}__"  # A, B, C, ...
        segments.append({"placeholder": placeholder, "original": match.group(1)})
        return placeholder

    processed = re.sub(r"\[([^\[\]]+)\]", _repl, prompt)
    return processed, segments


def restore_verbatim(prompt: str, segments: List[Dict[str, str]]) -> str:
    """Restore [verbatim] segments from placeholders (after LLM)."""
    result = prompt
    for segment in segments:
        result = result.replace(segment["placeholder"], f"[{segment['original']}]", 1)
    return result


def verify_verbatim_preserved(output: str, segments: List[Dict[str, str]]) -> bool:
    """True when every placeholder survived the LLM rewrite."""
    return all(segment["placeholder"] in output for segment in segments)


def strip_comments(prompt: str) -> str:
    """Drop # comment lines (they guide Enhance but never reach the tool)."""
    kept = [line for line in prompt.split("\n") if not line.lstrip().startswith("#")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def unwrap_verbatim(prompt: str) -> str:
    """Drop the [ ] markers — the final prompt uses the text directly."""
    return re.sub(r"\[([^\[\]]+)\]", r"\1", prompt)


def expand_named_wildcards(
    prompt: str,
    wildcards: List[Dict[str, Any]],
    segments: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Replace each {{name}} with a segment's fixed content (checked first) or
    a random value from the matching wildcard list. Unknown names stay as-is."""
    if not wildcards and not segments:
        return prompt

    wildcard_lookup = {str(w["name"]).lower(): w.get("values") or [] for w in wildcards}
    segment_lookup = {str(s["name"]).lower(): s.get("content", "") for s in (segments or [])}

    def _repl(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        if key in segment_lookup:
            return segment_lookup[key]
        values = wildcard_lookup.get(key)
        if not values:
            return match.group(0)
        return random.choice(values)

    return re.sub(r"\{\{([^{}]+)\}\}", _repl, prompt)


def expand_wildcards(prompt: str) -> str:
    """Replace each inline {a|b|c} with a random option ({foo} → "foo").
    Unresolved {{name}} tokens are protected so this pass can't eat their
    inner braces."""
    protected: List[str] = []

    def _protect(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    result = re.sub(r"\{\{[^{}]+\}\}", _protect, prompt)

    def _pick(match: re.Match) -> str:
        choices = [s.strip() for s in match.group(1).split("|")]
        return random.choice(choices)

    result = re.sub(r"\{([^{}]+)\}", _pick, result)
    return re.sub("\x00(\\d+)\x00", lambda m: protected[int(m.group(1))], result)


def process_final_prompt(
    prompt: str,
    wildcards: Optional[List[Dict[str, Any]]] = None,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Final resolve: {{name}} first (segment content gets further processing),
    then strip comments, unwrap verbatim, expand inline wildcards."""
    result = prompt
    if wildcards or segments:
        result = expand_named_wildcards(result, wildcards or [], segments)
    result = strip_comments(result)
    result = unwrap_verbatim(result)
    result = expand_wildcards(result)
    return result


# --- Ideogram 4 detection (mirrors isIdeogram4 in ToolView.vue) ----------------

def is_ideogram4(model_vendor: Optional[str], model: Optional[str]) -> bool:
    vendor = (model_vendor or "").lower()
    if vendor != "ideogram":
        return False
    m = (model or "").lower()
    return bool(re.search(r"ideogram[\s:_-]*v?4(\b|@|\.0|$)", m)) or "ideogram:4" in m


# --- LLM steps (mirror improveViaApi / translateViaApi) -------------------------

async def _improve_with_verbatim_protection(
    db,
    prompt: str,
    instructions: Optional[str],
    model: Optional[str],
    is_video: bool,
    is_audio: bool,
    input_image_count: int,
    media_id: Optional[int],
) -> str:
    from routes.prompt_enhancement import ImprovePromptRequest, improve_prompt

    prompt_with_placeholders, segments = extract_verbatim(prompt)

    for attempt in range(_MAX_LLM_RETRIES):
        request = ImprovePromptRequest(
            prompt=prompt_with_placeholders,
            instructions=instructions or None,
            model=model or None,
            is_video=is_video,
            is_audio=is_audio,
            input_image_count=input_image_count,
            media_id=media_id,
        )
        async with db.async_session_maker() as session:
            candidate = (await improve_prompt(request, session)).improved_prompt
        if not segments:
            return candidate
        if verify_verbatim_preserved(candidate, segments):
            return restore_verbatim(candidate, segments)
        log.warning(f"[prompt-pipeline] Improve attempt {attempt + 1}: verbatim placeholders dropped, retrying...")

    log.warning("[prompt-pipeline] All improve retries failed to preserve verbatim text, using original prompt")
    return prompt


async def _translate_with_verbatim_protection(prompt: str, language_code: str) -> str:
    from routes.prompt_enhancement import (
        PROMPT_LANGUAGE_ENGLISH_BY_CODE,
        TranslatePromptRequest,
        translate_prompt,
    )

    target = PROMPT_LANGUAGE_ENGLISH_BY_CODE.get(language_code)
    if not target:
        return prompt  # unknown code — nothing to do

    prompt_with_placeholders, segments = extract_verbatim(prompt)

    for attempt in range(_MAX_LLM_RETRIES):
        request = TranslatePromptRequest(prompt=prompt_with_placeholders, target_language=target)
        candidate = (await translate_prompt(request)).translated_prompt
        if not segments:
            return candidate
        if verify_verbatim_preserved(candidate, segments):
            return restore_verbatim(candidate, segments)
        log.warning(f"[prompt-pipeline] Translate attempt {attempt + 1}: verbatim placeholders dropped, retrying...")

    log.warning("[prompt-pipeline] All translate retries failed to preserve verbatim text, using untranslated prompt")
    return prompt


async def _to_ideogram_json(prompt: str, width: Optional[int], height: Optional[int]) -> str:
    from routes.prompt_enhancement import IdeogramJsonRequest, prompt_to_ideogram_json

    request = IdeogramJsonRequest(prompt=prompt, width=width or None, height=height or None)
    return (await prompt_to_ideogram_json(request)).json_prompt


# --- Orchestration (mirrors submitJobAsync steps 1-3 + applyJsonMode) -----------

def _profile_wildcards_and_segments(profile_id: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not profile_id:
        return [], []
    try:
        from config import get_settings
        settings = get_settings()
        wildcards = [
            {"name": w.name, "values": list(w.values or [])}
            for w in settings.get_wildcards_for_profile(profile_id)
        ]
        segments = [
            {"name": s.name, "content": s.content or ""}
            for s in settings.get_prompt_segments_for_profile(profile_id)
        ]
        return wildcards, segments
    except Exception as e:
        log.warning(f"[prompt-pipeline] Could not load wildcards for profile {profile_id}: {e}")
        return [], []


async def run_prompt_pipeline(
    db,
    prompt: str,
    prompt_options: Optional[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    model_vendor: Optional[str] = None,
    is_video: bool = False,
    is_audio: bool = False,
    input_image_count: int = 0,
    media_id: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    profile_id: Optional[str] = None,
) -> str:
    """Run the full generate-time pipeline on a prompt, server-side.

    `prompt_options` is the raw PromptOptions shape the editor persists
    ({autoImprove: {enabled, instructions}, translate: {enabled, language}});
    absent/disabled options skip the LLM steps, but final processing
    (wildcards/comments/verbatim) ALWAYS runs — same as an interactive submit.
    LLM failures propagate (the caller fails the step, like the interactive
    submit surfaces the error); verbatim-drop retries fall back non-fatally.
    """
    if not prompt:
        return prompt

    options = prompt_options or {}
    auto_improve = options.get("autoImprove") or {}
    translate = options.get("translate") or {}

    enhance_on = bool(auto_improve.get("enabled"))
    ideogram_json_mode = enhance_on and is_ideogram4(model_vendor, model)

    processed = prompt

    # 1) Enhance (text styles only — Ideogram JSON runs post-resolve).
    if enhance_on and not ideogram_json_mode:
        processed = await _improve_with_verbatim_protection(
            db,
            processed,
            instructions=(auto_improve.get("instructions") or "").strip() or None,
            model=model,
            is_video=is_video,
            is_audio=is_audio,
            input_image_count=input_image_count,
            media_id=media_id,
        )

    # 2) Translate.
    if translate.get("enabled") and translate.get("language"):
        processed = await _translate_with_verbatim_protection(processed, translate["language"])

    # 3) Final processing: {{name}}, comments, verbatim, inline wildcards.
    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    processed = process_final_prompt(processed, wildcards, segments)

    # 4) Ideogram JSON — on the fully resolved prompt (last step).
    if ideogram_json_mode:
        processed = await _to_ideogram_json(processed, width, height)

    return processed

"""How an agent's prompt reaches the image model.

The agent uses the surface a person uses in Tool View, with the same syntax:

* By default its prompt gets the person's Direct handling: the words go out as
  written, ``{a|b}`` picks one option, saved ``{{name}}`` lists and segments fill,
  ``[exact text]`` unwraps and ``#`` lines drop. A ``{{name}}`` that isn't saved stops
  the call with a message saying how to fix it, rather than reaching the model as
  text. Structured prompts (MiniMax H3, a JSON prompt) are left untouched.
  ``enhance_prompt`` keeps its meaning: omitted rewrites only for models with their
  own prompt format, True rewrites for any model, False never rewrites.
* ``vary=True`` opts into the person's Fluent handling: the prompt's ``<slots>`` and
  ``{a|b}`` lists are read once, with the same program cache as Tool View, and each image
  draws its own choices, then has its prompt written for the model at the detail level
  ``enhance_prompt`` gives. ``keep_choices`` are the person's chosen values and
  ``draw_seed`` the person's *Same draws*.

Every path goes through the person's own pipeline (``routes.generation`` and
``prompt_pipeline``); nothing here prepares or draws on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.logging import get_logger

log = get_logger(__name__)


# Model-facing text. Plain words, no feature names: weak local models read these too.
VARY_DOC = (
    "Give each image its own fresh choices from this prompt. Put angle brackets around each "
    "part that should change from image to image, as <young woman> or <pet>: options are "
    "found for it within its words. Write your own options as {a|b|c}. Lines starting with "
    "# are notes for choosing and writing; they never reach the image model. Choices are "
    "made to fit together, and the result lists what each image got. The first call with a "
    "new prompt takes a few seconds longer; calls with the same prompt share that work. "
    "Without vary, each {a|b|c} picks one option at random, <words> are sent as their words "
    "and the rest is sent as written."
)
KEEP_CHOICES_DOC = (
    "Only with vary. Hold choices from an earlier result while the rest vary: a choice's "
    "name mapped to one value to always use, or to a list of values to choose among. Copy "
    "names and values from that result's choices."
)
DRAW_SEED_DOC = (
    "Only with vary. Repeat an earlier result's choices: pass its draw_seed with the same "
    "prompt. It is separate from seed: the same draw_seed with a new seed keeps the "
    "choices and changes the picture; the same seed without a draw_seed keeps the picture's "
    "randomness and changes the choices."
)
ENHANCE_DOC = (
    "Rewrite the prompt for the selected model before generating. Omit for the default: "
    "on for models with their own prompt format, off otherwise. False keeps your wording, "
    "with the prompt syntax applied ({a|b} picks one, [brackets] unwrap, # lines drop); "
    "true rewrites for any model. With vary, each image's prompt is rewritten after its "
    "choices are made, keeping them word for word: true writes it fuller, omitted writes it "
    "in the model's format, false sends your wording with the choices filled in."
)

UNCHECKED_NOTE = (
    "These choices weren't checked to fit together: that check isn't available right now "
    "(it keeps downloading in the background). Later calls are checked once it's ready."
)
UNCHECKED_LOCKDOWN_NOTE = (
    "These choices weren't checked to fit together: that check needs a download, and "
    "Privacy Lockdown is on."
)

NO_CHOICES_NOTE = (
    "Fresh choices aren't available for this model, so each image's prompt was written "
    "separately and there are no choices to keep."
)

_NAMED = re.compile(r"\{\{([^{}]+)\}\}")
_SYNTAX = re.compile(r"[{\[]")


class PromptHandlingError(ValueError):
    """A prompt the call can't send as asked. The message says what to change."""


@dataclass
class PromptRequest:
    """What the caller asked for. ``enhance`` is True, False or "auto" (omitted)."""

    enhance: Any = "auto"
    vary: bool = False
    keep_choices: Optional[Dict[str, Any]] = None
    draw_seed: Optional[int] = None


@dataclass
class PreparedPrompt:
    params: Dict[str, Any]
    note: Optional[str] = None
    choices: Optional[Dict[str, Any]] = None
    draw_seed: Optional[int] = None
    notes: List[str] = field(default_factory=list)


def coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def coerce_draw_seed(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        seed = int(value)
    except (TypeError, ValueError):
        raise PromptHandlingError(
            f"draw_seed must be a whole number from an earlier result, got {value!r}. Nothing was generated."
        ) from None
    if seed < 0:
        return None
    return seed


def coerce_keep_choices(value: Any) -> Optional[Dict[str, Any]]:
    if value is None or value == {}:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    if not isinstance(value, dict):
        raise PromptHandlingError(
            "keep_choices must map a choice's name to a value (or a list of values), "
            'for example {"outfit": "a red raincoat"}. Nothing was generated.'
        )
    return value


def request_from(kwargs: Dict[str, Any], enhance: Any) -> PromptRequest:
    """Pop vary / keep_choices / draw_seed out of a tool call's keyword arguments."""
    return PromptRequest(
        enhance=enhance,
        vary=coerce_bool(kwargs.pop("vary", False)),
        keep_choices=coerce_keep_choices(kwargs.pop("keep_choices", None)),
        draw_seed=coerce_draw_seed(kwargs.pop("draw_seed", None)),
    )


def _is_json_prompt(prompt: str) -> bool:
    text = prompt.strip()
    if not text or text[0] not in "{[":
        return False
    try:
        return isinstance(json.loads(text), (dict, list))
    except ValueError:
        return False


def _has_syntax(prompt: str) -> bool:
    return bool(_SYNTAX.search(prompt)) or any(line.lstrip().startswith("#") for line in prompt.split("\n"))


def unknown_names(prompt: str, profile_id: Optional[str]) -> List[str]:
    """{{name}}s outside # lines that aren't a saved list or segment (Tool View's check)."""
    from prompt_pipeline import _profile_wildcards_and_segments

    kept = "\n".join(line for line in prompt.split("\n") if not line.lstrip().startswith("#"))
    names = [m.group(1).strip() for m in _NAMED.finditer(kept)]
    if not names:
        return []
    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    known = {str(w.get("name", "")).lower() for w in wildcards} | {str(s.get("name", "")).lower() for s in segments}
    out: List[str] = []
    for n in names:
        if n and n.lower() not in known and n not in out:
            out.append(n)
    return out


def _unknown_name_error(name: str) -> PromptHandlingError:
    return PromptHandlingError(
        f"{{{{{name}}}}} isn't one of your saved lists. Write its options as {{a|b|c}}, "
        f"or write it as <{name}> and pass vary=True for options to be found. Nothing was generated."
    )


def _prompt_metadata(written: str, enhanced: bool) -> Dict[str, Any]:
    # The shape Tool View records, so Generation details and Use in Tool View read an
    # agent's image as they read a person's.
    return {"original_prompt": written, "auto_improve_enabled": bool(enhanced)}


def _structured(ctx_mode: str, prompt: str) -> bool:
    return ctx_mode == "minimax-h3" or _is_json_prompt(prompt)


def choices_of(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The visible choices a run drew, {choice: value}, from its recorded draws."""
    if not isinstance(record, dict):
        return None
    out: Dict[str, Any] = {}
    for d in record.get("draws") or []:
        if not isinstance(d, dict) or d.get("hidden") or not d.get("id"):
            continue
        out[str(d["id"])] = d.get("value")
    return out


def choices_line(choices: Optional[Dict[str, Any]], draw_seed: Optional[int]) -> Optional[str]:
    """`choices: outfit = … · age = … (draw_seed N)`, for receipts and results."""
    if draw_seed is None and not choices:
        return None
    body = " · ".join(f"{k} = {v}" for k, v in (choices or {}).items()) or "none"
    tail = f"  (draw_seed {draw_seed})" if draw_seed is not None else ""
    return f"choices: {body}{tail}"


def _detail_level(enhance: Any, format_model: bool) -> str:
    """Under vary: True is High, False is Yours, omitted is Medium for models with
    their own prompt format and Yours otherwise."""
    if enhance is True:
        return "expand"
    if enhance is False:
        return "off"
    if enhance == "fill":  # an image's own Medium, when varying from it
        return "fill"
    return "fill" if format_model else "off"


def _auto_improve(level: str) -> Dict[str, Any]:
    if level == "off":
        return {"enabled": False}
    return {"enabled": True, "level": level}


def _prepare_failure(exc: Exception) -> PromptHandlingError:
    detail = getattr(exc, "detail", None)
    code = detail.get("code") if isinstance(detail, dict) else None
    message = detail.get("message") if isinstance(detail, dict) else (detail or str(exc))
    reason = str(message or exc).removeprefix("Generation was not started: ").strip().rstrip(".")
    if code == "llm_not_configured":
        reason = "no chat model is set up in Settings"
    return PromptHandlingError(
        f"The prompt couldn't be prepared for varied choices: {reason}. Nothing was generated. "
        "Try again, or generate without vary."
    )


async def prepare_prompt(
    job_params: Dict[str, Any],
    *,
    tool_id: str,
    task_type: Optional[str],
    request: PromptRequest,
    project_id: Optional[int],
) -> PreparedPrompt:
    """The job's parameters with its prompt handled as asked, plus what to tell the agent.

    Raises PromptHandlingError (plain, fixable words) when nothing should be generated;
    a failed rewrite raises ValueError with the message the agent has always seen.
    """
    prompt = job_params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return PreparedPrompt(job_params)
    if not request.vary and (request.keep_choices or request.draw_seed is not None):
        raise PromptHandlingError(
            "keep_choices and draw_seed only work with vary=True. Pass vary=True to vary the rest, "
            "or leave them out. Nothing was generated."
        )

    from core.profile_context import get_current_profile
    from routes.generation import native_prompt_format, prompt_enhance_context

    profile_id = get_current_profile()
    ctx = prompt_enhance_context(job_params, tool_id, task_type, None)
    format_label = native_prompt_format(tool_id, task_type)
    structured = _structured(ctx["mode"], prompt)

    # Nothing fills a {{name}} that isn't saved, with vary or without.
    if not structured:
        missing = unknown_names(prompt, profile_id)
        if missing:
            raise _unknown_name_error(missing[0])

    if request.vary:
        return await _vary(job_params, prompt, ctx=ctx, format_model=format_label is not None,
                           tool_id=tool_id, task_type=task_type, request=request, project_id=project_id)

    enhance = request.enhance
    if enhance == "fill":
        enhance = "auto"
    if enhance is True or (enhance == "auto" and format_label is not None):
        return await _enhance(job_params, prompt, tool_id=tool_id, task_type=task_type,
                              project_id=project_id, target=format_label)

    # Direct: the person's Direct handling, no model.
    updated = dict(job_params)
    if not structured and _has_syntax(prompt):
        from prompt_pipeline import run_prompt_pipeline
        updated["prompt"] = await run_prompt_pipeline(None, prompt, None, profile_id=profile_id,
                                                      project_id=project_id)
    updated["prompt_metadata"] = _prompt_metadata(prompt, False)
    return PreparedPrompt(updated)


async def _enhance(job_params: Dict[str, Any], prompt: str, *, tool_id: str, task_type: Optional[str],
                   project_id: Optional[int], target: Optional[str], note: Optional[str] = None) -> PreparedPrompt:
    """The classic per-image rewrite (Tool View's Enhance), as today."""
    from routes.generation import enhance_tool_prompt

    try:
        enhanced = await enhance_tool_prompt(job_params, tool_id=tool_id, task_type=task_type, project_id=project_id)
    except Exception as e:
        log.warning(f"[prompt_handling] Prompt enhancement failed for {tool_id}: {e}")
        detail = getattr(e, "detail", None)
        message = detail.get("message") if isinstance(detail, dict) else detail
        if isinstance(detail, dict) and detail.get("code") == "llm_provider_error":
            # run_code returns exception text to the agent. Keep the structured
            # provider fields visible there as well as in the HTTP response.
            metadata = detail.get("upstream_metadata") or {}
            if metadata:
                message = f"{message} Provider error fields: {json.dumps(metadata, ensure_ascii=False)}"
        raise ValueError(
            f"Prompt enhancement failed: {message or str(e)}. No generation was started."
        ) from e
    enhanced = dict(enhanced)
    enhanced["prompt_metadata"] = _prompt_metadata(prompt, True)
    if note is None and enhanced.get("prompt") != prompt:
        note = (f"Your prompt was rewritten for {target or 'this model'} before generating. "
                "The result includes the exact prompt sent.")
    return PreparedPrompt(enhanced, note=note)


async def _vary(job_params: Dict[str, Any], prompt: str, *, ctx: Dict[str, Any], format_model: bool,
                tool_id: str, task_type: Optional[str], request: PromptRequest,
                project_id: Optional[int]) -> PreparedPrompt:
    # Tools whose prompts can't be prepared (structured formats, edits, audio): what
    # Tool View does there, a fuller prompt written for each image.
    if not ctx["program_supported"]:
        return await _enhance(job_params, prompt, tool_id=tool_id, task_type=task_type,
                              project_id=project_id, target=None, note=NO_CHOICES_NOTE)

    from fastapi import HTTPException
    from prompt_programs.choices import UnknownChoiceError
    from routes.generation import _apply_generation_prompt_pipeline

    level = _detail_level(request.enhance, format_model)
    program: Dict[str, Any] = {"enabled": True}
    if request.keep_choices:
        program["keep_choices"] = request.keep_choices
    if request.draw_seed is not None:
        program["draw_seed"] = request.draw_seed
    # The submit Tool View sends in Fluent: the LoRA choices explicit and on.
    prompt_options = {"program": program, "autoImprove": _auto_improve(level),
                      "loraTriggers": True, "loraNotes": True}
    try:
        updated = await _apply_generation_prompt_pipeline(
            dict(job_params), tool_id=tool_id, task_type=task_type, prompt_options=prompt_options,
            prompt_preload=None, project_id=project_id,
        )
    except UnknownChoiceError as e:
        raise PromptHandlingError(f"{e} Nothing was generated.") from None
    except HTTPException as e:
        raise _prepare_failure(e) from None
    except Exception as e:
        from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
        if isinstance(e, (LLMNotConfiguredError, LLMUnavailableError)):
            raise _prepare_failure(e) from None
        raise
    record = updated.get("prompt_program")
    updated["prompt_metadata"] = _prompt_metadata(prompt, level != "off")
    seed = record.get("draw_seed") if isinstance(record, dict) else None
    return PreparedPrompt(updated, note=unchecked_note(record), choices=choices_of(record), draw_seed=seed)


def unchecked_note(record: Optional[Dict[str, Any]]) -> Optional[str]:
    """A line for the result when the run's choices shipped without the fit check
    (the judge couldn't be had); None when they were checked, or needed no check."""
    fix = record.get("fix") if isinstance(record, dict) else None
    if not isinstance(fix, dict) or not fix.get("skipped"):
        return None
    return UNCHECKED_LOCKDOWN_NOTE if fix["skipped"] == "lockdown" else UNCHECKED_NOTE


async def source_prompt_for_vary(session, media_id: Any) -> Optional[Dict[str, Any]]:
    """For params_from + vary on an image made with varied choices: the prompt as it
    was written and the detail level it was prepared at, so the rest really varies.
    None when the image wasn't varied (reproduction stays exact)."""
    from sqlalchemy import select
    from database import MediaItem
    from .tools.library import _parse_generation_metadata

    try:
        mid = int(media_id)
    except (TypeError, ValueError):
        return None
    item = (await session.execute(select(MediaItem).where(MediaItem.id == mid))).scalar_one_or_none()
    if not item:
        return None
    gen = _parse_generation_metadata(item) or {}
    record = gen.get("prompt_program")
    written = (gen.get("prompt_metadata") or {}).get("original_prompt") if isinstance(gen.get("prompt_metadata"), dict) else None
    if not isinstance(record, dict) or not isinstance(written, str) or not written.strip():
        return None
    level = record.get("level") or "off"
    return {"prompt": written, "enhance": {"expand": True, "off": False}.get(level, "fill")}

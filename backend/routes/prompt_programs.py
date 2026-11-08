"""Prompt programs: prepare a prompt into a program, and preview a run of it."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

router = APIRouter(prefix="/api/prompt-programs", tags=["prompt-programs"])

# What the editor needs from a prepared program (the program text itself stays server-side
# unless asked for).
_PUBLIC_KEYS = ("key", "mode", "elaborate", "choices", "groups", "params", "loras", "lora_choices", "example", "warnings",
                "seconds", "upsample_seconds", "attempts")


class PrepareRequest(BaseModel):
    tool_id: str
    prompt: str
    loras: List[Dict[str, Any]] = Field(default_factory=list)
    # The generation's parameters (inputs, size): the enhancer's style depends on them.
    parameters: Dict[str, Any] = Field(default_factory=dict)
    task_type: Optional[str] = None
    instructions: str = ""
    project_id: Optional[int] = None
    include_program: bool = False
    # cache_only: return the prepared program if there is one, never call the model.
    cache_only: bool = False
    # force: prepare again from scratch even if a program for these inputs exists.
    force: bool = False
    # elaborate: Enhance on (rich, per-model example). Off: keep the user's own words.
    elaborate: bool = True
    # The prompt menu's "LoRA notes": whether the model is told the user's LoRA notes.
    lora_notes: bool = True


class PreviewRequest(PrepareRequest):
    pins: Dict[str, Any] = Field(default_factory=dict)
    edits: Dict[str, Any] = Field(default_factory=dict)
    seed: Optional[int] = None


async def _prepare(req: PrepareRequest) -> Dict[str, Any]:
    from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
    from prompt_programs.prepare import PrepareTimeout, ProgramError, ensure_program
    from routes.generation import prompt_enhance_context

    ctx = prompt_enhance_context(req.parameters, req.tool_id, req.task_type, None)
    if not ctx["program_supported"]:
        return {"unsupported": ctx["mode"]}
    try:
        return await ensure_program(
            prompt=req.prompt, tool_id=req.tool_id, ctx=ctx, instructions=req.instructions.strip(),
            lora_items=req.loras, project_id=req.project_id, profile_id=get_current_profile(),
            cache_only=req.cache_only, force=req.force, elaborate=req.elaborate, lora_notes=req.lora_notes,
        )
    except PrepareTimeout as e:
        raise HTTPException(status_code=422, detail={"code": "prepare_timeout", "message": str(e)}) from None
    except ProgramError as e:
        raise HTTPException(status_code=422, detail={"code": "program_failed", "message": str(e)}) from None
    except LLMNotConfiguredError as e:
        raise HTTPException(status_code=424, detail={"code": "llm_not_configured", "message": str(e)}) from None
    except LLMUnavailableError as e:
        raise HTTPException(status_code=424, detail={"code": "llm_unavailable", "message": str(e)}) from None


@router.post("/prepare")
async def prepare(req: PrepareRequest) -> Dict[str, Any]:
    entry = await _prepare(req)
    if entry is None:  # cache_only and not prepared yet: not an error, just nothing to show
        return {"key": None}
    if entry.get("unsupported"):  # structured formats are still enhanced per image
        return {"key": None, "unsupported": entry["unsupported"]}
    from prompt_programs.fluent import start_options
    start_options(entry, profile_id=get_current_profile(), project_id=req.project_id)  # background, low priority
    out = {k: entry.get(k) for k in _PUBLIC_KEYS}
    if req.include_program:
        out["program"] = entry["program"]
        out["enhanced"] = entry.get("enhanced")
    return out


class OptionsRequest(PrepareRequest):
    choice_id: str
    # The options the card shows now (after the user's edits), so new ones differ.
    existing: List[str] = Field(default_factory=list)
    count: int = 6


@router.post("/options")
async def options(req: OptionsRequest) -> Dict[str, Any]:
    """New options for one choice (the card's More like these and Reroll all)."""
    from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
    from prompt_programs.prepare import ProgramError, suggest_options
    entry = await _prepare(req.model_copy(update={"cache_only": True}))
    if entry is None or entry.get("unsupported"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        out = await suggest_options(entry, req.choice_id, req.existing, req.count, req.project_id)
    except ProgramError as e:
        raise HTTPException(status_code=422, detail={"code": "options_failed", "message": str(e)}) from None
    except LLMNotConfiguredError as e:
        raise HTTPException(status_code=424, detail={"code": "llm_not_configured", "message": str(e)}) from None
    except LLMUnavailableError as e:
        raise HTTPException(status_code=424, detail={"code": "llm_unavailable", "message": str(e)}) from None
    return {"options": out}


@router.post("/preview")
async def preview(req: PreviewRequest) -> Dict[str, Any]:
    import asyncio
    from prompt_programs.prepare import DrawAborted, ProgramError, draw_seed, realize
    entry = await _prepare(req)
    if entry is None or entry.get("unsupported"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        from prompt_programs.fluent import attach_filler
        attach_filler(entry, get_current_profile())
        # In a thread: a judge on CPU must not hold up the event loop.
        result = await asyncio.to_thread(realize, entry, seed=draw_seed(req.seed), pins=req.pins, edits=req.edits,
                                         profile_id=get_current_profile(), project_id=req.project_id)
    except DrawAborted as e:  # e.g. "Nothing left to draw for Hairstyle": shown at the choice
        raise HTTPException(status_code=422, detail=e.to_dict()) from None
    except ProgramError as e:
        raise HTTPException(status_code=422, detail={"code": "program_failed", "message": str(e)}) from None
    return {"key": entry["key"], **result.to_dict()}

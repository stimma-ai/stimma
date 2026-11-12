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
_PUBLIC_KEYS = ("key", "mode", "elaborate", "enhance", "choices", "groups", "params", "loras", "lora_choices", "example", "warnings",
                "seconds", "upsample_seconds", "attempts")


class PrepareRequest(BaseModel):
    tool_id: str
    prompt: str
    loras: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)
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
    # enhance: "off" | "fill" | "expand"; when set it decides (elaborate is for older clients).
    enhance: Optional[str] = None
    # The prompt menu's "LoRA notes": whether the model is told the user's LoRA notes.
    lora_notes: bool = True
    # The prompt menu's "Trigger words": whether the writer is told the on LoRAs' trigger words.
    lora_triggers: bool = True
    # The program the editor showed before this prompt: an edit of it continues its writer session.
    base_key: Optional[str] = None
    # What the user has pinned in the app: the writer keeps those choices and their values.
    pins: Dict[str, Any] = Field(default_factory=dict)
    # The program the cards are showing. Options and pools work on it even while a newer
    # version of the prompt is being prepared (choices that survive keep their edits).
    key: Optional[str] = None


class PreviewRequest(PrepareRequest):
    edits: Dict[str, Any] = Field(default_factory=dict)
    seed: Optional[int] = None


def program_http_error(e: Exception, failed: str = "program_failed") -> Optional[HTTPException]:
    """The HTTP error for a prepare or option-writing failure, or None for a real bug (left
    to the app's handler). The chat model failing to answer is a 424 the client offers Try
    again or Direct for, never a 500 with a crash report."""
    from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
    from prompt_programs.prepare import PrepareTimeout, ProgramError, writer_failure

    e = writer_failure(e) or e
    if isinstance(e, PrepareTimeout):
        return HTTPException(status_code=422, detail={"code": "prepare_timeout", "message": str(e)})
    if isinstance(e, ProgramError):
        detail = {"code": getattr(e, "code", failed), "message": str(e)}
        if getattr(e, "problems", ""):
            detail["problems"] = e.problems  # what the writer was told: for the dev panel
        return HTTPException(status_code=422, detail=detail)
    if isinstance(e, LLMUnavailableError):  # its code says which: not set up, no balance, unreachable
        code = "llm_not_configured" if isinstance(e, LLMNotConfiguredError) else (e.code or "llm_unavailable")
        return HTTPException(status_code=424, detail={"code": code, "message": str(e)})
    return None


async def _prepare(req: PrepareRequest, tell_declined: bool = False) -> Dict[str, Any]:
    from prompt_programs.prepare import ensure_program
    from routes.generation import prompt_enhance_context

    ctx = prompt_enhance_context(req.parameters, req.tool_id, req.task_type, None)
    if not ctx["program_supported"]:
        return {"unsupported": ctx["mode"]}
    try:
        return await ensure_program(
            prompt=req.prompt, tool_id=req.tool_id, ctx=ctx, instructions=req.instructions.strip(),
            lora_items=req.loras, project_id=req.project_id, profile_id=get_current_profile(),
            cache_only=req.cache_only, force=req.force, elaborate=req.elaborate, lora_notes=req.lora_notes,
            lora_triggers=req.lora_triggers, base_key=req.base_key, enhance=req.enhance,
            tell_declined=tell_declined, pins=req.pins,
        )
    except Exception as e:
        http = program_http_error(e)
        if http is None:
            raise
        raise http from None


@router.post("/prepare")
async def prepare(req: PrepareRequest) -> Dict[str, Any]:
    # The editor's lookup also learns that the chat model declined this prompt (the answer a
    # background retry may have met since the prompt box last heard).
    entry = await _prepare(req, tell_declined=True)
    if entry is None:  # cache_only and not prepared yet: not an error, just nothing to show
        return {"key": None}
    if entry.get("unsupported"):  # structured formats are still enhanced per image
        return {"key": None, "unsupported": entry["unsupported"]}
    # A fresh prepare already started its option pools (prepare.on_prepared); a cached one's
    # unfilled pools queue as draws reach them. Not here: the editor looks up on every Run.
    out = {k: entry.get(k) for k in _PUBLIC_KEYS}
    if req.include_program:
        out["program"] = entry["program"]
        out["enhanced"] = entry.get("enhanced")
    return out


class OptionsRequest(PrepareRequest):
    choice_id: str
    # The options the card shows now (after the user's edits), so new ones differ.
    existing: List[str] = Field(default_factory=list, max_length=200)
    count: int = 6


async def _shown(req: PrepareRequest) -> Optional[Dict[str, Any]]:
    """The program the cards are showing (req.key), else the one prepared for these inputs."""
    if req.key:
        from prompt_programs.prepare import _store
        entry = _store(get_current_profile()).get(req.key)
        if entry:
            return entry
    return await _prepare(req.model_copy(update={"cache_only": True}))


@router.post("/options")
async def options(req: OptionsRequest) -> Dict[str, Any]:
    """New options for one choice (the card's More like these and Reroll all)."""
    from prompt_programs.options import suggest_options
    entry = await _shown(req)
    if entry is None or entry.get("unsupported"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        out = await suggest_options(entry, req.choice_id, req.existing, req.count, req.project_id)
    except Exception as e:
        http = program_http_error(e, failed="options_failed")
        if http is None:
            raise
        raise http from None
    return {"options": out}


@router.post("/pools")
async def pools(req: PreviewRequest) -> Dict[str, Any]:
    """What each generated choice's picker shows: its seeds plus the options generated so far."""
    import asyncio
    from prompt_programs.fluent import attach_filler, pool_options
    entry = await _shown(req)
    if entry is None or entry.get("unsupported"):
        return {"options": {}, "more": []}
    attach_filler(entry, get_current_profile())
    return await asyncio.to_thread(pool_options, entry, req.pins, profile_id=get_current_profile(), project_id=req.project_id)


class AdditionRequest(BaseModel):
    # The vocabulary list the choice is bound to (its `cls`, e.g. "person.hairstyle").
    cls: str = Field(max_length=200)
    text: str = Field(max_length=2000)


def _addition_list(req: AdditionRequest) -> str:
    from prompt_programs.additions import list_id
    lid = list_id(req.cls)
    if lid is None:
        raise HTTPException(status_code=422, detail={"code": "not_a_list",
                                                     "message": "This choice's options aren't kept for later prompts."})
    return lid


@router.get("/additions")
async def list_additions() -> Dict[str, Any]:
    """The user's own options kept for each vocabulary list, offered by every later prompt."""
    from prompt_programs.additions import additions_for
    return {"lists": additions_for(get_current_profile()).lists()}


@router.post("/additions")
async def add_addition(req: AdditionRequest) -> Dict[str, Any]:
    """Keep an option the user added to a choice bound to a list, for every later prompt."""
    from prompt_programs.additions import MAX_TEXT, additions_for, clean_text
    lid = _addition_list(req)
    text = clean_text(req.text)
    if not text or len(text) > MAX_TEXT:
        raise HTTPException(status_code=422, detail={"code": "bad_option", "message": "An option is a few words."})
    store = additions_for(get_current_profile())
    added = store.add(lid, text)
    return {"list": lid, "added": added, "options": store.of(lid)}


@router.post("/additions/remove")
async def remove_addition(req: AdditionRequest) -> Dict[str, Any]:
    """Forget an option the user had kept for a list."""
    from prompt_programs.additions import additions_for
    lid = _addition_list(req)
    store = additions_for(get_current_profile())
    removed = store.remove(lid, req.text)
    return {"list": lid, "removed": removed, "options": store.of(lid)}


@router.get("/vocabulary")
async def vocabulary_tree() -> Dict[str, Any]:
    """The whole vocabulary (nodes, leaves, values with tiers and facet tags), for the dev browser."""
    from prompt_programs.vocab import vocabulary
    return vocabulary().to_dict()


@router.post("/preview")
async def preview(req: PreviewRequest) -> Dict[str, Any]:
    import asyncio
    from prompt_programs.fix import realize_and_fix
    from prompt_programs.prepare import DrawAborted, ProgramError, draw_seed
    entry = await _prepare(req)
    if entry is None or entry.get("unsupported"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        from prompt_programs.fix import await_judge
        from prompt_programs.fluent import attach_filler
        attach_filler(entry, get_current_profile())
        await await_judge(entry, project_id=req.project_id)
        # In a thread: a judge on CPU must not hold up the event loop.
        result, fix = await asyncio.to_thread(realize_and_fix, entry, seed=draw_seed(req.seed), pins=req.pins,
                                              edits=req.edits, profile_id=get_current_profile(),
                                              project_id=req.project_id)
    except DrawAborted as e:  # e.g. "Nothing left to draw for Hairstyle": shown at the choice
        raise HTTPException(status_code=422, detail=e.to_dict()) from None
    except ProgramError as e:
        raise HTTPException(status_code=422, detail={"code": "program_failed", "message": str(e)}) from None
    return {"key": entry["key"], **result.to_dict(), **({"fix": fix} if fix is not None else {})}


# --------------------------------------------------------------------------- the fix judge

class FixJudgeRequest(BaseModel):
    # "default" (the Tool View model), a model directory on this machine, or empty /
    # "off" to turn the fix pass off
    model: str = ""


def _fix_judge_status(model: str, threads: int) -> Dict[str, Any]:
    """The judge's state: the Tool View model is always ready to be asked; a model
    directory is loaded (once) to say whether it works."""
    from prompt_programs.fix import FixJudgeUnavailable, fix_judge, fix_mode
    mode = fix_mode(model)
    if mode == "off":
        return {"model": model, "status": "off"}
    if mode == "default":
        return {"model": model, "status": "ready", "waiting": False}
    try:
        j = fix_judge(model, threads)
    except FixJudgeUnavailable as e:
        return {"model": model, "status": "error", "error": str(e)}
    return {"model": model, "status": "ready", "version": j.version, "cut": j.cut}


@router.get("/fix-judge")
async def get_fix_judge(start: bool = False, retry: bool = False) -> Dict[str, Any]:
    """The configured judge's state. `start` and `retry` are accepted for the client's
    wait loop and change nothing: the Tool View model needs no download."""
    import asyncio
    from prompt_programs.judge import settings
    s = settings()
    return await asyncio.to_thread(_fix_judge_status, s.fix_model, s.fix_threads)


@router.put("/fix-judge")
async def put_fix_judge(req: FixJudgeRequest) -> Dict[str, Any]:
    import asyncio
    import config_writer
    from config import get_settings
    model = req.model.strip()
    cfg = get_settings()
    section = cfg.fluent.model_dump()
    section["fix_model"] = model
    config_writer.patch_global_section("fluent", section)
    cfg.fluent.fix_model = model
    return await asyncio.to_thread(_fix_judge_status, model, cfg.fluent.fix_threads)

"""Prompt programs: prepare a prompt into a program, and preview a run of it."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

router = APIRouter(prefix="/api/prompt-programs", tags=["prompt-programs"])

# What a slot and a choice say to the editor (the program text itself stays server-side unless asked for).
_SLOT_KEYS = ("id", "n", "kind", "label", "words", "span", "line", "details", "stated")
_CHOICE_KEYS = ("id", "kind", "label", "cls", "options", "follows", "parent", "when")


class PrepareRequest(BaseModel):
    tool_id: str
    prompt: str
    # The generation's parameters (inputs, size): structured prompt formats aren't prepared.
    parameters: Dict[str, Any] = Field(default_factory=dict)
    task_type: Optional[str] = None
    project_id: Optional[int] = None
    include_program: bool = False
    # cache_only: return the prepared program if there is one, never call the model.
    cache_only: bool = False
    # force: read the prompt's slots again, even if a program for it exists.
    force: bool = False
    # The program the cards are showing. Options and pools work on it even while a newer
    # version of the prompt is being prepared.
    key: Optional[str] = None


class PreviewRequest(PrepareRequest):
    # What the user chose in the chooser, per choice (prompt_programs.choices).
    choices: Dict[str, Any] = Field(default_factory=dict)
    seed: Optional[int] = None


def program_http_error(e: Exception, failed: str = "program_failed") -> Optional[HTTPException]:
    """The HTTP error for a prepare or option-writing failure, or None for a real bug (left
    to the app's handler). The chat model failing to answer, or answering with a reading
    that can't be used, is a 424 the client offers Try again or Direct for, never a 500
    with a crash report."""
    from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
    from prompt_programs.prepare import PrepareTimeout, ProgramError, writer_failure
    from prompt_programs.reader import ReaderFailed

    if isinstance(e, ReaderFailed):
        return HTTPException(status_code=424, detail={"code": e.code, "message": str(e)})
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


async def _prepare(req: PrepareRequest) -> Optional[Dict[str, Any]]:
    from prompt_programs import slots
    from routes.generation import prompt_enhance_context

    ctx = prompt_enhance_context(req.parameters, req.tool_id, req.task_type, None)
    if not ctx["program_supported"]:
        return {"unsupported": ctx["mode"]}
    try:
        return await slots.ensure(req.prompt, profile_id=get_current_profile(), project_id=req.project_id,
                                  cache_only=req.cache_only, force=req.force)
    except Exception as e:
        http = program_http_error(e)
        if http is None:
            raise
        raise http from None


def public(entry: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    """A prepared slot program as the editor reads it: its slots (spans in the prompt as typed),
    their choices and the user's lists, and an example."""
    from prompt_programs.choices import zone_titles
    from prompt_programs.slots import raw_spans
    slots = []
    for s, raw in zip(entry.get("slots") or [], raw_spans(prompt, entry)):
        out = {k: s[k] for k in _SLOT_KEYS if k in s}
        out["span"], out["line"] = (list(raw[0]), raw[1]) if raw else (None, None)
        slots.append(out)
    owner = {d: s["id"] for s in entry.get("slots") or [] for d in s.get("details") or []}
    choices = []
    for c in entry.get("choices") or []:
        if c.get("hidden"):
            continue
        out = {k: c[k] for k in _CHOICE_KEYS if k in c}
        zones = zone_titles(entry, c["id"])
        if zones:
            out["zones"] = zones
        if c["id"] in owner:
            out["slot"] = owner[c["id"]]
        elif c.get("source") == "list":
            out.update(source="list", line=c.get("line"))
        choices.append(out)
    return {"key": entry.get("key"), "slots": slots, "choices": choices, "example": entry.get("example"),
            "seconds": entry.get("seconds", 0.0)}


@router.post("/prepare")
async def prepare(req: PrepareRequest) -> Dict[str, Any]:
    entry = await _prepare(req)
    if entry is None:  # cache_only and not prepared yet: not an error, just nothing to show
        return {"key": None}
    if entry.get("unsupported"):  # structured formats are still enhanced per image
        return {"key": None, "unsupported": entry["unsupported"]}
    if not entry.get("key"):   # nothing in the prompt varies
        return {"key": None, "slots": [], "choices": []}
    # A fresh prepare already started its option pools (prepare.on_prepared); a cached one's
    # unfilled pools queue as draws reach them.
    out = public(entry, req.prompt)
    if req.include_program:
        out["program"] = entry["program"]
        out["reading"] = entry.get("reading")
    return out


class OptionsRequest(PrepareRequest):
    choice_id: str
    # The options the card shows now (after the user's edits), so new ones differ.
    existing: List[str] = Field(default_factory=list, max_length=200)
    count: int = 6
    # One of the choice's zones ("kinds", "instead"): options for that zone.
    zone: Optional[str] = None


async def _shown(req: PrepareRequest) -> Optional[Dict[str, Any]]:
    """The program the cards are showing (req.key), else the one prepared for these inputs."""
    if req.key:
        from prompt_programs.prepare import _store
        entry = _store(get_current_profile()).get(req.key)
        if entry:
            return entry
    entry = await _prepare(req.model_copy(update={"cache_only": True}))
    return entry if entry is not None and (entry.get("key") or entry.get("unsupported")) else None


@router.post("/options")
async def options(req: OptionsRequest) -> Dict[str, Any]:
    """New options for one choice (the card's More like these and Reroll all)."""
    from prompt_programs.options import suggest_options
    entry = await _shown(req)
    if entry is None or entry.get("unsupported"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        out = await suggest_options(entry, req.choice_id, req.existing, req.count, req.project_id, zone=req.zone)
    except Exception as e:
        http = program_http_error(e, failed="options_failed")
        if http is None:
            raise
        raise http from None
    return {"options": out}


@router.post("/pools")
async def pools(req: PreviewRequest) -> Dict[str, Any]:
    """What each generated choice's picker shows, per choice: its options (seeds plus those
    generated so far, for the zones chosen), each zone's options, its list's groups, tiers, the
    user's own options and short forms, and whether more are being written."""
    import asyncio
    from prompt_programs.choices import expand
    from prompt_programs.fluent import attach_filler, pool_options
    entry = await _shown(req)
    if entry is None or entry.get("unsupported"):
        return {"choices": {}, "more": []}
    attach_filler(entry, get_current_profile())
    pins, edits, zones = expand(entry, req.choices)
    got = await asyncio.to_thread(pool_options, entry, pins, edits=edits, zones=zones, profile_id=get_current_profile(),
                                  project_id=req.project_id)
    out: Dict[str, Any] = {}
    for cid, options in got["options"].items():
        out[cid] = {"options": options, "more": cid in got["more"], **got["vocab"].get(cid, {})}
        if got["zones"].get(cid):
            out[cid]["zones"] = got["zones"][cid]
    return {"choices": out, "more": got["more"]}


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
    from prompt_programs.choices import expand
    from prompt_programs.fix import realize_and_fix
    from prompt_programs.prepare import DrawAborted, ProgramError, draw_seed
    entry = await _prepare(req)
    if entry is None or entry.get("unsupported") or not entry.get("key"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        from prompt_programs.fix import await_judge
        from prompt_programs.fluent import attach_filler
        attach_filler(entry, get_current_profile())
        await await_judge(entry, project_id=req.project_id)
        # In a thread: a judge on CPU must not hold up the event loop.
        pins, edits, zones = expand(entry, req.choices)
        result, fix = await asyncio.to_thread(realize_and_fix, entry, seed=draw_seed(req.seed), pins=pins,
                                              edits=edits, zones=zones, profile_id=get_current_profile(),
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


# --------------------------------------------------------------------------- suggest and add

class SuggestRequest(BaseModel):
    prompt: str = Field(max_length=20000)
    project_id: Optional[int] = None
    # Raw mode sends the prompt as typed: nothing in it varies, so nothing is suggested.
    raw: bool = False


class AddRequest(BaseModel):
    prompt: str = Field(max_length=20000)
    # The words the new slot carries (an add's `name` from /suggest).
    name: str = Field(max_length=200)
    project_id: Optional[int] = None


@router.post("/suggest")
async def suggest_slots(req: SuggestRequest) -> Dict[str, Any]:
    """Phrases in the prompt that could vary, and things it doesn't mention worth varying."""
    from prompt_programs.suggest import cache_for, model_name, suggest
    try:
        model = await model_name(req.project_id) if req.prompt.strip() and not req.raw else ""
        return await suggest(req.prompt, cache=cache_for(get_current_profile()), project_id=req.project_id,
                             model=model, raw=req.raw)
    except Exception as e:
        http = program_http_error(e, failed="suggest_failed")
        if http is None:
            raise
        raise http from None


@router.post("/add")
async def add_slot(req: AddRequest) -> Dict[str, Any]:
    """The prompt with a new slot for `name` written in, and where it is."""
    from prompt_programs.slots import SLOT_RE
    from prompt_programs.suggest import add
    name = req.name.strip()
    if not SLOT_RE.fullmatch(f"<{name}>"):
        raise HTTPException(status_code=422, detail={"code": "bad_slot", "message": "Those words can't be a slot."})
    try:
        return await add(req.prompt, name, project_id=req.project_id)
    except Exception as e:
        http = program_http_error(e, failed="add_failed")
        if http is None:
            raise
        raise http from None

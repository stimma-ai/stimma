"""Prompt programs: prepare a prompt into a program, and preview a run of it."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

router = APIRouter(prefix="/api/prompt-programs", tags=["prompt-programs"])

# What a slot and a choice say to the editor (the program text itself stays server-side unless asked for).
_SLOT_KEYS = ("id", "n", "kind", "label", "words", "span", "line", "stated", "degraded", "state")
_CHOICE_KEYS = ("id", "kind", "label", "options", "slot")


class PrepareRequest(BaseModel):
    tool_id: str
    prompt: str
    # The generation's parameters (inputs, size): structured prompt formats aren't prepared.
    parameters: Dict[str, Any] = Field(default_factory=dict)
    task_type: Optional[str] = None
    project_id: Optional[int] = None
    include_program: bool = False
    # cache_only: what is ready now, starting no background reading. Prepare never waits on
    # a model either way.
    cache_only: bool = False
    # force: read the prompt's slots again, even those already read.
    force: bool = False
    # retry: Try again on parts that stand as their words because their reading or their
    # variants failed: read those again and write their variants again at once; the rest keep
    # what they have.
    retry: bool = False
    # The program the cards are showing. Options and pools work on it even while a newer
    # version of the prompt is being prepared, and a prepare keeps its readings for the parts
    # the new version still has.
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
    from prompt_programs.program import ProgramError, model_failure
    from prompt_programs.reader import ReaderFailed

    if isinstance(e, ReaderFailed):
        return HTTPException(status_code=424, detail={"code": e.code, "message": str(e)})
    e = model_failure(e) or e
    if isinstance(e, ProgramError):
        return HTTPException(status_code=422, detail={"code": getattr(e, "code", failed), "message": str(e)})
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
        return await slots.prepare(req.prompt, profile_id=get_current_profile(), project_id=req.project_id,
                                   start=not req.cache_only, force=req.force, shown=req.key)
    except Exception as e:
        http = program_http_error(e)
        if http is None:
            raise
        raise http from None


def public(entry: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    """A prepared prompt as the editor reads it: its slots (spans in the prompt as typed, each
    with its state: reading, writing, ready or as_written), one choice per slot and per user
    list (stimma-plans VARIANTS_IMPL.md section 4)."""
    from prompt_programs.fluent import _writer, slot_state
    from prompt_programs.slots import raw_spans
    writer = _writer(get_current_profile())
    slots = []
    for s, raw in zip(entry.get("slots") or [], raw_spans(prompt, entry)):
        out = {k: s[k] for k in _SLOT_KEYS if k in s}
        out["span"], out["line"] = (list(raw[0]), raw[1]) if raw else (None, None)
        out["state"] = slot_state(entry, s, writer)
        slots.append(out)
    # Which part of the program the editor showed each one is (slots.prepare's `was`): the
    # editor moves what was chosen, and the options it shows, over to the part's id here.
    was = entry.get("was") or {}
    ids = was.get("ids") or {}
    for out in slots:
        if out["id"] in ids:
            out["was"] = ids[out["id"]]
    choices = []
    for c in entry.get("choices") or []:
        out = {k: c[k] for k in _CHOICE_KEYS if k in c}
        if c.get("source") == "list":
            out.update(source="list", line=c.get("line"))
        if c["id"] in ids:
            out["was"] = ids[c["id"]]
        choices.append(out)
    return {"key": entry.get("key"), "slots": slots, "choices": choices,
            "reading": bool(entry.get("reading")), "working": bool(entry.get("working")),
            **({"from": was["from"]} if was.get("from") else {})}


@router.post("/prepare")
async def prepare(req: PrepareRequest) -> Dict[str, Any]:
    entry = await _prepare(req)
    if entry.get("unsupported"):  # structured formats are still enhanced per image
        return {"key": None, "unsupported": entry["unsupported"]}
    if not entry.get("key"):   # nothing in the prompt varies
        return {"key": None, "slots": [], "choices": []}
    # Readings and seeds that land start their pools (slots._settle); a slot whose pool isn't
    # written yet stands as its words.
    if req.retry and not req.cache_only:
        from prompt_programs import program as prep
        prep.on_prepared(entry, project_id=req.project_id, profile_id=get_current_profile(), retry=True)
        # What is read again now stands as being read: answer with that.
        entry = await _prepare(req.model_copy(update={"cache_only": True, "retry": False}))
    out = public(entry, req.prompt)
    from prompt_programs.events import watch
    watch(entry, get_current_profile())
    if req.include_program:   # the dev dialog: what each part was read as, its seeds, and one draw
        from prompt_programs.program import realize
        out["readings"] = entry.get("readings")
        out["seeds"] = entry.get("seeds")
        try:
            out["example"] = realize(entry, seed=0, profile_id=get_current_profile(), project_id=req.project_id).prompt
        except Exception as e:
            out["example"] = f"(couldn't draw: {e})"
    return out


class OptionsRequest(PrepareRequest):
    # The slot to write more variants for (More like these).
    choice_id: str
    # What the user chose (their picked seeds steer the batch).
    choices: Dict[str, Any] = Field(default_factory=dict)


async def _shown(req: PrepareRequest) -> Optional[Dict[str, Any]]:
    """The prompt the cards are showing: the one in the request as it stands now, else (the
    prompt moved on since the cards were made) the entry stored under req.key."""
    entry = await _prepare(req.model_copy(update={"cache_only": True}))
    if req.key and entry.get("key") != req.key:
        from prompt_programs.program import store_for
        stored = store_for(get_current_profile()).get(req.key)
        if stored:
            return stored
    return entry if entry.get("key") or entry.get("unsupported") else None


@router.post("/options")
async def options(req: OptionsRequest) -> Dict[str, Any]:
    """More like these: one more batch of variants for a slot, awaited; the new ones."""
    from prompt_programs.choices import expand
    from prompt_programs.fluent import more_like_these
    entry = await _shown(req)
    if entry is None or entry.get("unsupported"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    _, _, chosen = expand(entry, req.choices)
    try:
        out = await more_like_these(entry, req.choice_id, profile_id=get_current_profile(), project_id=req.project_id,
                                    chosen=chosen)
    except Exception as e:
        http = program_http_error(e, failed="options_failed")
        if http is None:
            raise
        raise http from None
    return {"options": out}


@router.post("/pools")
async def pools(req: PreviewRequest) -> Dict[str, Any]:
    """What each slot's picker shows: its state, its variants with their seeds and use counts,
    the user's own, the choice as read, and for a person the descent and gender pickers
    (VARIANTS_IMPL.md section 4). Starts the writes it needs; never waits on a model."""
    from prompt_programs.choices import expand
    from prompt_programs.fluent import attach_writer, pool_view
    entry = await _shown(req)
    if entry is None or entry.get("unsupported"):
        return {"choices": {}, "more": []}
    from prompt_programs.events import watch
    attach_writer(entry, get_current_profile())
    watch(entry, get_current_profile())
    _, _, chosen = expand(entry, req.choices)
    return pool_view(entry, chosen, profile_id=get_current_profile(), project_id=req.project_id)


class RemoveVariantRequest(PrepareRequest):
    # The slot, and the variant to remove from its pool.
    choice_id: str
    text: str = Field(min_length=1, max_length=4000)


@router.post("/remove-variant")
async def remove_variant(req: RemoveVariantRequest) -> Dict[str, Any]:
    """Remove one variant from a slot's pool for good: it is never drawn or listed again, and a
    later batch that writes the same text doesn't bring it back."""
    from prompt_programs.events import prompt_changed
    from prompt_programs.variant_pools import store_for
    entry = await _shown(req)
    s = next((x for x in (entry or {}).get("slots") or [] if x.get("id") == req.choice_id), None)
    if s is None or not s.get("pool"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "That part of the prompt isn't there any more."})
    store = store_for(get_current_profile())
    for pool in dict.fromkeys(k for k in (s.get("pool"), s.get("stand_in")) if k):
        store.remove(str(pool), [req.text])
    prompt_changed(entry.get("key"), get_current_profile())
    return {"removed": True}


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
    from prompt_programs.program import DrawAborted, ProgramError, draw_seed
    entry = await _prepare(req)
    if entry is None or entry.get("unsupported") or not entry.get("key"):
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    try:
        from prompt_programs.fix import await_judge
        from prompt_programs.fluent import attach_writer
        attach_writer(entry, get_current_profile())
        await await_judge(entry, project_id=req.project_id)
        # In a thread: a judge on CPU must not hold up the event loop.
        pins, edits, chosen = expand(entry, req.choices)
        result, fix = await asyncio.to_thread(realize_and_fix, entry, seed=draw_seed(req.seed), pins=pins,
                                              edits=edits, chosen=chosen, profile_id=get_current_profile(),
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
    # Where /suggest said it goes, and the prompt it said so for: written in with no model call
    # only when that is exactly `prompt`.
    after: Optional[str] = Field(default=None, max_length=2000)
    insert: Optional[str] = Field(default=None, max_length=400)
    suggested_for: Optional[str] = Field(default=None, max_length=20000)
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
    """The prompt with a new slot for `name` written in, and where it is: spliced in where
    /suggest said when that still fits, else placed by a short model call."""
    from prompt_programs.slots import SLOT_RE
    from prompt_programs.suggest import add
    name = req.name.strip()
    if not SLOT_RE.fullmatch(f"<{name}>"):
        raise HTTPException(status_code=422, detail={"code": "bad_slot", "message": "Those words can't be a slot."})
    try:
        return await add(req.prompt, name, project_id=req.project_id, after=req.after, insert=req.insert,
                         suggested_for=req.suggested_for)
    except Exception as e:
        http = program_http_error(e, failed="add_failed")
        if http is None:
            raise
        raise http from None

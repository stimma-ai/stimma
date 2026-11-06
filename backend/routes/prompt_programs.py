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
_PUBLIC_KEYS = ("key", "choices", "groups", "params", "loras", "lora_choices", "example", "warnings", "seconds", "attempts")


class PrepareRequest(BaseModel):
    tool_id: str
    prompt: str
    loras: List[Dict[str, Any]] = Field(default_factory=list)
    project_id: Optional[int] = None
    include_program: bool = False
    # cache_only: return the prepared program if there is one, never call the model.
    cache_only: bool = False
    # force: prepare again from scratch even if a program for these inputs exists.
    force: bool = False


class PreviewRequest(PrepareRequest):
    pins: Dict[str, Any] = Field(default_factory=dict)
    edits: Dict[str, Any] = Field(default_factory=dict)
    seed: Optional[int] = None


async def _prepare(req: PrepareRequest) -> Dict[str, Any]:
    from llm_resolver import LLMNotConfiguredError, LLMUnavailableError
    from prompt_programs.prepare import ProgramError, ensure_program
    from routes.generation import _prompt_pipeline_context

    model, _vendor, _task, schema_props = _prompt_pipeline_context(req.tool_id, None, None)
    try:
        return await ensure_program(
            prompt=req.prompt, tool_id=req.tool_id, model_name=model, schema_props=schema_props,
            lora_items=req.loras, project_id=req.project_id, profile_id=get_current_profile(),
            cache_only=req.cache_only, force=req.force,
        )
    except ProgramError as e:
        raise HTTPException(status_code=422, detail={"code": "program_failed", "message": str(e)}) from None
    except (LLMNotConfiguredError, LLMUnavailableError) as e:
        raise HTTPException(status_code=424, detail={"code": "llm_not_configured", "message": str(e)}) from None


@router.post("/prepare")
async def prepare(req: PrepareRequest) -> Dict[str, Any]:
    entry = await _prepare(req)
    if entry is None:  # cache_only and not prepared yet: not an error, just nothing to show
        return {"key": None}
    out = {k: entry.get(k) for k in _PUBLIC_KEYS}
    if req.include_program:
        out["program"] = entry["program"]
    return out


@router.post("/preview")
async def preview(req: PreviewRequest) -> Dict[str, Any]:
    from prompt_programs.prepare import program_seed, realize
    entry = await _prepare(req)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "not_prepared", "message": "This prompt isn't prepared yet."})
    result = realize(entry, seed=program_seed(req.seed), pins=req.pins, edits=req.edits)
    return {"key": entry["key"], **result.to_dict()}

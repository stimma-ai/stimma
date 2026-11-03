"""API routes for LoRA trigger words and notes."""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.profile_context import get_current_profile
from lora_notes import FINGERPRINT_RE, resolve_lora_notes, save_note, share_note, unshare_note

router = APIRouter(prefix="/api/lora-notes", tags=["lora-notes"])


class SaveNoteRequest(BaseModel):
    trigger_words: List[str] = Field(default_factory=list, max_length=50)
    notes: str = Field(default="", max_length=8000)
    value: Optional[str] = None


class ShareNoteRequest(BaseModel):
    tool_id: str
    value: str
    replace: bool = False


def _check_fingerprint(fingerprint: str) -> None:
    if not FINGERPRINT_RE.match(fingerprint):
        raise HTTPException(status_code=422, detail="Invalid fingerprint")


@router.get("")
async def get_lora_notes(tool_id: str = Query(...)):
    return await resolve_lora_notes(get_current_profile(), tool_id)


@router.put("/files/{fingerprint}")
async def put_lora_note(fingerprint: str, request: SaveNoteRequest):
    _check_fingerprint(fingerprint)
    await save_note(get_current_profile(), fingerprint, request.trigger_words, request.notes, request.value)
    return {"status": "ok"}


@router.post("/files/{fingerprint}/share")
async def post_lora_note_share(fingerprint: str, request: ShareNoteRequest):
    _check_fingerprint(fingerprint)
    result = await share_note(get_current_profile(), request.tool_id, request.value, request.replace)
    if result["status"] == "conflict":
        raise HTTPException(status_code=409, detail={"conflicts": result["conflicts"]})
    if result["status"] == "unavailable":
        raise HTTPException(status_code=404, detail="This LoRA has no fingerprint")
    return result


@router.post("/files/{fingerprint}/unshare")
async def post_lora_note_unshare(fingerprint: str):
    _check_fingerprint(fingerprint)
    if not await unshare_note(get_current_profile(), fingerprint):
        raise HTTPException(status_code=404, detail="No note for this LoRA")
    return {"status": "ok"}

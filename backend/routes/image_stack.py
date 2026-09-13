"""Routes for the op-stack image editor's working documents.

The stack document is server-persisted so a session survives app restarts and
so generated candidates can be owned by something durable. See
``image_stack_service`` for the on-disk shape.

The editor screen is the single writer for a given document; these routes are
storage, not orchestration. The open handshake resolves the base Revision and
creates or resumes the Asset's stack document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import image_stack_service as stack
from core.dependencies import get_db_session
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import Asset, AssetRevision, MediaItem, WorkingDocument

router = APIRouter(prefix="/api/image-stack", tags=["image-stack"])
log = get_logger(__name__)


class OpenStackRequest(BaseModel):
    asset_id: int
    # Open from a specific version ("Edit from this version"); defaults to head.
    revision_id: Optional[int] = None


class BaseInfo(BaseModel):
    asset_id: int
    revision_id: int
    media_id: int
    file_hash: str
    width: int
    height: int


class OpenStackResponse(BaseModel):
    document_id: int
    base: BaseInfo
    # Null when this asset has never been opened in the op-stack editor.
    document: Optional[dict] = None
    # The head at open time, so the client can tell when it has drifted.
    head_revision_id: Optional[int] = None


class WriteDocumentRequest(BaseModel):
    document: dict


class AppendJournalRequest(BaseModel):
    entries: list[dict]


async def _load_document(
    session: AsyncSession, document_id: int
) -> tuple[WorkingDocument, Path]:
    document = await session.get(WorkingDocument, document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.editor_type != stack.EDITOR_TYPE
    ):
        raise HTTPException(status_code=404, detail="Stack document not found")
    directory = stack.document_dir(document, get_current_profile())
    return document, directory


@router.post("/open", response_model=OpenStackResponse)
async def open_stack(
    request: OpenStackRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Create or resume the stack document for an Asset.

    One document per (asset, branch): reopening the same asset resumes the same
    stack rather than starting a second one, which is what makes the editor's
    one-instance-per-asset rule hold across restarts.
    """
    from asset_service import create_working_document

    asset = await session.get(Asset, request.asset_id)
    if asset is None or asset.deleted_at is not None or asset.state != "active":
        raise HTTPException(status_code=404, detail="Asset not found")

    revision_id = request.revision_id or asset.current_revision_id
    revision = await session.get(AssetRevision, revision_id) if revision_id else None
    if (
        revision is None
        or revision.deleted_at is not None
        or revision.asset_id != asset.id
    ):
        raise HTTPException(status_code=400, detail="Base revision does not belong to this Asset")

    media = await session.get(MediaItem, revision.primary_media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Base revision has no media")

    # Entering the editor is a use of the Asset and clears auto-expiration.
    from asset_association_service import clear_asset_expiration
    await clear_asset_expiration(session, asset.id)

    document = await create_working_document(
        session,
        asset_id=asset.id,
        editor_type=stack.EDITOR_TYPE,
        base_revision_id=revision.id,
    )
    directory = stack.document_dir(document, get_current_profile())
    stack.ensure_layout(directory)
    if document.state_locator != str(directory):
        document.state_locator = str(directory)
    await session.commit()

    stored = await stack.read_document(directory)

    # A resumed working document keeps the base its composition was authored
    # against. Saving advances the Asset's current Revision, but that flattened
    # output must never become the base under the still-live stack or every
    # edit is effectively baked in before it is replayed. The document JSON is
    # the authoritative description of that base.
    base_info = BaseInfo(
        asset_id=asset.id,
        revision_id=revision.id,
        media_id=media.id,
        file_hash=media.file_hash,
        width=media.width or 0,
        height=media.height or 0,
    )
    if stored is not None:
        stored_base = stored.get("base") if isinstance(stored, dict) else None
        if isinstance(stored_base, dict):
            try:
                base_info = BaseInfo(
                    asset_id=int(stored_base["asset_id"]),
                    revision_id=int(stored_base["revision_id"]),
                    media_id=int(stored_base["media_id"]),
                    file_hash=str(stored_base["file_hash"]),
                    width=int(stored_base["width"]),
                    height=int(stored_base["height"]),
                )
            except (KeyError, TypeError, ValueError):
                log.warning(
                    f"image-stack: stored document {document.id} has an invalid "
                    "base; falling back to the requested revision"
                )

    return OpenStackResponse(
        document_id=document.id,
        base=base_info,
        document=stored,
        head_revision_id=asset.current_revision_id,
    )


@router.get("/{document_id}")
async def get_stack(
    document_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    document, directory = await _load_document(session, document_id)
    return {
        "document_id": document.id,
        "asset_id": document.asset_id,
        "base_revision_id": document.base_revision_id,
        "document": await stack.read_document(directory),
        "journal_length": await stack.journal_length(directory),
    }


@router.put("/{document_id}/document")
async def put_stack_document(
    document_id: int,
    request: WriteDocumentRequest,
    session: AsyncSession = Depends(get_db_session),
):
    document, directory = await _load_document(session, document_id)
    try:
        await stack.write_document(directory, request.document)
    except stack.ImageStackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    document.generation += 1
    await session.commit()
    return {"ok": True, "generation": document.generation}


@router.post("/{document_id}/journal")
async def append_stack_journal(
    document_id: int,
    request: AppendJournalRequest,
    session: AsyncSession = Depends(get_db_session),
):
    _, directory = await _load_document(session, document_id)
    try:
        length = await stack.append_journal(directory, request.entries)
    except stack.ImageStackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "journal_length": length}


@router.get("/{document_id}/journal")
async def get_stack_journal(
    document_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """The bounded recent undo window, loaded independently of the document."""
    _, directory = await _load_document(session, document_id)
    return {"entries": await stack.read_journal(directory)}


class NameEditRequest(BaseModel):
    """A generative step and the region it touched, to be named."""

    operation: str
    # Base64 JPEG of the region as it looked BEFORE the step ran.
    image_b64: str
    prompt: Optional[str] = None


class NameEditResponse(BaseModel):
    # Null whenever no usable name came back; the caller keeps its verb label.
    label: Optional[str] = None


def _clean_step_label(text: str) -> Optional[str]:
    """Accept only what fits a 320px row: a few words, sentence case.

    A model that answers with a sentence, a refusal or a paragraph gets dropped
    rather than truncated — a label cut mid-word is worse than "Repaint".
    """
    label = " ".join((text or "").split())
    label = label.strip().strip('".\'')
    label = label.replace("->", "→").replace("  ", " ")
    if not label or len(label) > 32:
        return None
    if len(label.split()) > 5:
        return None
    return label[0].upper() + label[1:]


def _bare_noun(text: str) -> Optional[str]:
    """Reduce a subject phrase to the one noun the row needs.

    Models answer "german shepherd dog" or "abandoned house" however tightly the
    instruction is worded, and no amount of prompting kills the adjective every
    time. The head noun of an English noun phrase is its last word, so the
    phrase is cut back to that: "dog", "house". This does clip real compounds
    ("fire hydrant" -> "hydrant"), which reads fine in a row and is the price of
    a rule that never leaves an adjective standing.
    """
    words = " ".join((text or "").split()).strip('".\'').lower().split()
    if not words or len(words) > 4:
        # Not a subject phrase — a sentence or a refusal. Keep the verb label.
        return None
    return words[-1]


@router.post("/name-edit", response_model=NameEditResponse)
async def name_edit(request: NameEditRequest):
    """Name a Remove or Repaint step from what it actually did.

    "Remove" and "Repaint" are the verbs; a column of them says nothing about
    which one took the house out. The quick-task model looks at the region as it
    was before the step and names the subject, so the stack reads as a history
    of the picture rather than a history of button presses.

    Advisory by construction: any failure returns no label, and the caller keeps
    the verb. Never raises for a model or provider problem.
    """
    from llm import llm_complete_vision
    from llm_resolver import get_effective_llm_config

    target = " ".join((request.prompt or "").split())[:200]
    if request.operation == "remove":
        instruction = (
            "This is a crop of a photo, centered on something that is about to "
            "be erased. Reply with ONE lowercase word: the plainest common noun "
            "for it. No breed, no color, no age, no condition, no adjectives of "
            "any kind. Examples of well-formed answers:\n"
            "a german shepherd in a field -> dog\n"
            "a boarded-up farmhouse -> house\n"
            "a red pickup truck -> truck\n"
            "a woman in a yellow raincoat -> woman\n"
            "Reply with ONLY that word — no punctuation, no sentence, no "
            "explanation."
        )
    elif request.operation == "repaint" and target:
        instruction = (
            "This is a crop of a photo, centered on content that is about to be "
            "replaced. The replacement was requested as: "
            f"\"{target}\"\n"
            "Reply with ONLY \"X -> Y\", where X names what is there now and Y "
            "names what it becomes. Lowercase, one word per side whenever one "
            "word will do, two at the most, and only keep an adjective when it "
            "is the whole point of the change. Examples of well-formed "
            "answers:\n"
            "dog -> cat\n"
            "house -> barn\n"
            "tree -> statue\n"
            "cloudy sky -> clear sky\n"
            "No other text."
        )
    else:
        return NameEditResponse()

    try:
        config = await get_effective_llm_config("quick_task")
        if not config:
            return NameEditResponse()
        result, error = await llm_complete_vision(
            config, instruction, request.image_b64, max_tokens=24, temperature=0.2
        )
        if error or not result:
            return NameEditResponse()
        if request.operation == "remove":
            subject = _bare_noun(result)
            label = _clean_step_label(f"remove {subject}") if subject else None
        else:
            label = _clean_step_label(result)
        if not label:
            return NameEditResponse()
        return NameEditResponse(label=label)
    except Exception as exc:
        log.debug("step naming failed", error_type=type(exc).__name__)
        return NameEditResponse()


@router.post("/{document_id}/payloads")
async def upload_stack_payload(
    document_id: int,
    file: UploadFile = File(...),
    name: str = Form(...),
    subdir: str = Form("payloads"),
    session: AsyncSession = Depends(get_db_session),
):
    """Store a mask, patch, stroke set or rendered layer under its op's name."""
    _, directory = await _load_document(session, document_id)
    data = await file.read()
    try:
        await stack.write_payload(directory, name, data, subdir=subdir)
        if subdir == "cache":
            await stack.prune_head_caches(directory, keep=name)
    except stack.ImageStackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ref": f"{subdir}/{name}", "bytes": len(data)}


@router.get("/{document_id}/payloads/{name}")
async def get_stack_payload(
    document_id: int,
    name: str,
    subdir: str = "payloads",
    session: AsyncSession = Depends(get_db_session),
):
    _, directory = await _load_document(session, document_id)
    try:
        path = stack.resolve_payload(directory, name, subdir=subdir)
    except stack.ImageStackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Payload not found")
    # Paint layers are intentionally rewritten under a stable raster_ref as
    # strokes land. Force clients to revalidate that URL; otherwise WebKit can
    # keep returning the first PNG and the compositor appears to lose every
    # later stroke until a browser refresh.
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.delete("/{document_id}/cache")
async def clear_stack_cache(
    document_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Discard composite intermediates. Safe by construction: pure function of
    document + payloads + base."""
    _, directory = await _load_document(session, document_id)
    await stack.clear_cache(directory)
    return {"ok": True}

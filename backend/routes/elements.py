"""Element routes: list, detail for the viewer, rename / set cover, companion files, create."""

from __future__ import annotations

import mimetypes
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from core.profile_context import get_current_profile
from elements.bundle import (
    ElementConflict,
    ElementError,
    ElementNotFound,
    commit_element,
    element_asset,
    element_detail,
    element_revision_by_media,
    list_elements,
    safe_bundle_file,
    update_element,
)
from elements.manifest import INSTRUCTIONS_NAME, new_manifest, starter_instructions, write_manifest
from routes.media_files import get_db_session_by_guid
from utils.http_headers import content_disposition

router = APIRouter(prefix="/api", tags=["elements"])


def _http(exc: ElementError) -> HTTPException:
    if isinstance(exc, ElementNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ElementConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/elements")
async def get_elements(
    kind: Optional[str] = None,
    q: Optional[str] = None,
    project_id: Optional[int] = None,
    session: AsyncSession = Depends(get_db_session),
):
    return {"elements": await list_elements(session, kind=kind, query=q, project_id=project_id)}


class CreateElementRequest(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    description: Optional[str] = None
    asset_ids: list[int] = []
    project_id: Optional[int] = None


@router.post("/elements")
async def create_element(body: CreateElementRequest, session: AsyncSession = Depends(get_db_session)):
    """A new element, optionally from selected library assets (the first becomes the cover)."""
    manifest = new_manifest(body.name or "Untitled element", body.kind or "", body.description or "")
    manifest["media_menu"] = [
        {"key": f"ref-{index + 1}", "asset_id": asset_id, "title": "", "labels": [], "status": "canonical"}
        for index, asset_id in enumerate(dict.fromkeys(body.asset_ids))
    ]
    if manifest["media_menu"]:
        manifest["cover_member_key"] = manifest["media_menu"][0]["key"]
    scratch = Path(tempfile.mkdtemp(prefix="stimma-element-new-"))
    try:
        write_manifest(scratch, manifest)
        (scratch / INSTRUCTIONS_NAME).write_text(
            starter_instructions(manifest["name"], manifest["kind"], manifest["description"]), encoding="utf-8"
        )
        result = await commit_element(
            session,
            profile_id=get_current_profile(),
            source_dir=scratch,
            origin_type="element_new",
            project_id=body.project_id,
        )
    except ElementError as exc:
        raise _http(exc)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    detail = await element_detail(session, result.asset.id)
    return {**detail, "warnings": result.warnings}


@router.get("/elements/by-media/{media_id}")
async def get_element_by_media(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """One version of an element, by its bundle's media id (chat cards and the version menu)."""
    try:
        asset, _revision, _media = await element_revision_by_media(session, media_id)
        return await element_detail(session, asset.id, media_id=media_id)
    except ElementError as exc:
        raise _http(exc)


class ResolveRequest(BaseModel):
    elements: list[dict] = []
    tool_id: str
    prompt: str = ""
    parameters: dict = {}
    task_type: Optional[str] = None
    enhance_enabled: bool = True
    overrides: dict = {}
    project_id: Optional[int] = None


@router.post("/elements/resolve")
async def resolve_elements(body: ResolveRequest, session: AsyncSession = Depends(get_db_session)):
    """Which reference images and LoRAs the attached elements put on a tool, for this prompt.

    Never fails for model trouble: that answers with a plan made without the model.
    """
    from elements.resolver import resolve

    return await resolve(
        session,
        elements=body.elements,
        tool_id=body.tool_id,
        prompt=body.prompt,
        parameters=body.parameters,
        task_type=body.task_type,
        enhance_enabled=body.enhance_enabled,
        overrides=body.overrides,
        project_id=body.project_id,
        profile_id=get_current_profile(),
    )


@router.get("/elements/{asset_id}")
async def get_element(asset_id: int, session: AsyncSession = Depends(get_db_session)):
    try:
        return await element_detail(session, asset_id)
    except ElementError as exc:
        raise _http(exc)


class UpdateElementRequest(BaseModel):
    name: Optional[str] = None
    cover_member_key: Optional[str] = None
    base_revision_id: Optional[int] = None


@router.api_route("/elements/{asset_id}", methods=["PATCH", "PUT"])
async def patch_element(asset_id: int, body: UpdateElementRequest, session: AsyncSession = Depends(get_db_session)):
    """The viewer's direct edits: rename, and set the cover. Everything else is refined in chat."""
    try:
        detail = await update_element(
            session,
            profile_id=get_current_profile(),
            asset_id=asset_id,
            name=body.name,
            cover_member_key=body.cover_member_key,
            base_revision_id=body.base_revision_id,
        )
    except ElementError as exc:
        raise _http(exc)
    # Tiles, open viewers and chat panels follow the edit.
    from utils.websocket import ws_manager

    if body.cover_member_key is not None:
        await ws_manager.broadcast("asset_current_revision_changed", {
            "asset_id": detail["asset_id"], "revision_id": detail["revision_id"], "media_id": detail["media_id"],
        })
    if body.name is not None:
        await ws_manager.broadcast("assets_updated", {"asset_ids": [detail["asset_id"]], "fields": ["title"]})
    return detail


async def _serve_file(session: AsyncSession, asset_id: int, path: str, download: bool) -> FileResponse:
    try:
        _asset, _revision, media = await element_asset(session, asset_id)
    except ElementError as exc:
        raise _http(exc)
    target = safe_bundle_file(media, path)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    headers = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}
    if download:
        headers["Content-Disposition"] = content_disposition("attachment", target.name)
    return FileResponse(
        target, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream", headers=headers
    )


@router.get("/elements/{asset_id}/files/{path:path}")
async def get_element_file(asset_id: int, path: str, download: bool = False, session: AsyncSession = Depends(get_db_session)):
    """A companion file of the element's current version, e.g. ``files/palette.json``."""
    return await _serve_file(session, asset_id, path, download)


@router.get("/db/{db_guid}/elements/{asset_id}/files/{path:path}")
async def get_element_file_by_db_guid(
    db_guid: str, asset_id: int, path: str, download: bool = False,
    session: AsyncSession = Depends(get_db_session_by_guid),
):
    return await _serve_file(session, asset_id, path, download)


@router.get("/db/{db_guid}/pin/{pin_hex}/elements/{asset_id}/files/{path:path}")
async def get_element_file_by_db_guid_with_pin(
    db_guid: str, pin_hex: str, asset_id: int, path: str, download: bool = False,
    session: AsyncSession = Depends(get_db_session_by_guid),
):
    return await _serve_file(session, asset_id, path, download)

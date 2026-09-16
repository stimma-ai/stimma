"""Workspace file previews, downloads, and explicit library saves."""

import asyncio
import json
from utils.file_mime import guess_file_mime
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from database import Chat, MediaItem
from agent.v2.workspace import get_workspace_dir, get_project_workspace
from workspace_files import describe_file, resolve_file, zip_entries, read_zip_entry

router = APIRouter()
Root = Literal["chat", "project"]


async def file_context(
    session, chat_id: int, root: Root, path: str, media_id: int | None = None
):
    chat = await session.get(Chat, chat_id)
    if not chat or chat.deleted_at is not None:
        raise HTTPException(404, "Chat not found")
    directory = (
        get_workspace_dir(chat_id, chat.project_id)
        if root == "chat"
        else get_project_workspace(chat.project_id)
    )
    if directory is None:
        raise HTTPException(400, "Chat has no project workspace")
    if media_id is not None:
        media = await session.get(MediaItem, media_id)
        if (
            media is None
            or media.deleted_at is not None
            or not media.file_path
            or not Path(media.file_path).is_file()
        ):
            raise HTTPException(404, "Library file not found")
        return chat, directory, Path(media.file_path)
    return chat, directory, resolve_file(directory, path)


@router.get("/{chat_id}/files/{root}/info")
async def file_info(
    chat_id: int,
    root: Root,
    path: str,
    media_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    _, _, file = await file_context(session, chat_id, root, path, media_id)
    return await asyncio.to_thread(describe_file, chat_id, root, path, file)


@router.get("/{chat_id}/files/{root}/index")
async def archive_index(
    chat_id: int,
    root: Root,
    path: str,
    media_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    _, _, file = await file_context(session, chat_id, root, path, media_id)
    return {"entries": await asyncio.to_thread(zip_entries, file)}


@router.get("/{chat_id}/files/{root}/content")
async def file_content(
    chat_id: int,
    root: Root,
    path: str,
    entry: str | None = None,
    download: bool = False,
    media_id: int | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    _, _, file = await file_context(session, chat_id, root, path, media_id)
    name = Path(entry or path).name
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        "Content-Disposition": f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(name)}",
    }
    mime = guess_file_mime(name)
    if entry is not None:
        data = await asyncio.to_thread(read_zip_entry, file, entry)
        return Response(data, media_type=mime, headers=headers)
    return FileResponse(file, media_type=mime, headers=headers)


class FileAction(BaseModel):
    path: str
    entry: str | None = None
    media_id: int | None = None


async def attachment_file(session, chat_id, root, path, entry=None, media_id=None):
    chat, directory, file = await file_context(session, chat_id, root, path, media_id)
    if entry is not None or media_id is not None:
        import hashlib

        if entry is None and file.stat().st_size > 128 * 1024 * 1024:
            raise HTTPException(413, "File is too large to attach")
        data = (
            await asyncio.to_thread(read_zip_entry, file, entry)
            if entry is not None
            else await asyncio.to_thread(file.read_bytes)
        )
        relative = f"attachments/{hashlib.sha256(data).hexdigest()[:16]}/{Path(entry or path).name}"
        workspace = get_workspace_dir(chat_id, chat.project_id)
        destination = workspace / relative
        # Resolve before writing too: existing workspace symlinks cannot escape.
        if not destination.resolve().is_relative_to(workspace.resolve()):
            raise HTTPException(400, "Path escapes workspace")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return {"root": "chat", "path": relative, "filename": destination.name}
    return {"root": root, "path": path, "filename": file.name}


@router.post("/{chat_id}/files/{root}/attach")
async def attach_file(
    chat_id: int,
    root: Root,
    request: FileAction,
    session: AsyncSession = Depends(get_db_session),
):
    return await attachment_file(
        session, chat_id, root, request.path, request.entry, request.media_id
    )


@router.post("/{chat_id}/files/{root}/save")
async def save_file(
    chat_id: int,
    root: Root,
    request: FileAction,
    session: AsyncSession = Depends(get_db_session),
):
    from agent.v2.tools.library import save_workspace_file
    from agent.v2.tools.show import _apply_show_disposition
    from asset_service import AssetServiceError, require_asset_format
    from utils.query_builder import STRUCTURED_FORMATS
    from utils.websocket import ws_manager

    chat, directory, file = await file_context(
        session, chat_id, root, request.path, request.media_id
    )
    with tempfile.TemporaryDirectory() as staging:
        if request.entry is not None:
            data = await asyncio.to_thread(read_zip_entry, file, request.entry)
            file = Path(staging) / Path(request.entry).name
            file.write_bytes(data)
        fmt = next(
            (fmt for fmt in STRUCTURED_FORMATS if file.name.lower().endswith("." + fmt)),
            file.suffix.lstrip(".").lower(),
        )
        try:
            require_asset_format(fmt)
        except AssetServiceError as exc:
            raise HTTPException(400, str(exc)) from exc
        raw = await save_workspace_file(
            session, str(file), directory, None, project_id=chat.project_id,
        )
    if raw.startswith("Error:"):
        raise HTTPException(400, raw.removeprefix("Error:").strip())
    result = json.loads(raw)
    assets = await _apply_show_disposition(
        session=session, chat_id=chat_id, media_ids=[result["media_id"]], role="final"
    )
    if chat.project_id is not None:
        from asset_association_service import attach_asset_to_project

        await attach_asset_to_project(session, chat.project_id, assets[0])
    await session.commit()
    await ws_manager.broadcast(
        "asset_created", {"asset_id": assets[0], "media_id": result["media_id"]}
    )
    return {**result, "asset_id": assets[0]}

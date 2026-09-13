"""Package routes: recipes, creation from a selection, bundle files, status, rebuild, export."""

from __future__ import annotations

import asyncio
import io
import mimetypes
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import Asset, AssetRevision, MediaItem
from packages import cache as run_cache
from packages.bundle import (
    PackageBuilder,
    PackageError,
    manifest_for_media,
    package_status,
    rebuild_package,
)
from packages.cover import CoverError
from packages.export import export_single_html, export_zip, run_zip_for_path
from packages.manifest import COVER_NAME, ManifestError, is_package_format, slugify
from packages.recipes import RecipeError, list_recipes
from routes.media_files import get_db_session_by_guid
from utils.http_headers import content_disposition
from utils.query_builder import not_due_for_autodelete

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["packages"])

ID_KEYED_CACHE_HEADERS = {"Cache-Control": "no-cache"}


async def _package_media(session: AsyncSession, media_id: int) -> MediaItem:
    media = await session.scalar(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.deletion_pending_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
            not_due_for_autodelete(),
        )
    )
    if media is None or not is_package_format(media.file_format):
        raise HTTPException(status_code=404, detail="Package not found")
    if not Path(media.file_path).is_dir():
        raise HTTPException(status_code=404, detail="Package bundle is missing on disk")
    return media


@router.get("/packages/recipes")
async def get_recipes():
    """Every installed recipe with its input roles and parameters."""
    return {"recipes": [spec.to_dict() for spec in list_recipes(get_current_profile())]}


class CreatePackageRequest(BaseModel):
    title: Optional[str] = None
    media_ids: list[int] = []
    recipe: Optional[str] = None
    inputs: dict[str, int] = {}  # role -> media id
    params: dict[str, Any] = {}
    project_id: Optional[int] = None


@router.post("/packages")
async def create_package(body: CreatePackageRequest, session: AsyncSession = Depends(get_db_session)):
    """Package as… from a selection. No agent involved."""
    profile_id = get_current_profile()
    title = (body.title or "").strip()
    if not title:
        from packages.recipes import get_recipe

        spec = get_recipe(body.recipe, profile_id) if body.recipe else None
        title = spec.display_name if spec else "Package"
    try:
        async with PackageBuilder(
            session, profile_id=profile_id, title=title, project_id=body.project_id, source="package_as",
        ) as builder:
            role_by_media: dict[int, str] = {int(v): k for k, v in body.inputs.items()}
            member_ids: dict[int, str] = {}
            for media_id in list(body.media_ids) + [m for m in role_by_media if m not in body.media_ids]:
                member_ids[media_id] = await builder.add_member(media_id, role=role_by_media.get(media_id))
            if body.recipe:
                inputs = {role: member_ids[int(media_id)] for role, media_id in body.inputs.items()}
                await builder.run(body.recipe, inputs, body.params)
            media, asset = await builder.save(materialize_asset=True, origin_type="package_as")
    except (PackageError, RecipeError, CoverError, ManifestError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"media_id": media.id, "asset_id": asset.id if asset else None}


@router.get("/media/{media_id}/package")
async def get_package(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """Manifest plus status for the viewer sidebar."""
    media = await _package_media(session, media_id)
    manifest = await manifest_for_media(session, media)
    if manifest is None:
        raise HTTPException(status_code=500, detail="Package manifest is unreadable")
    try:
        status = await package_status(session, media)
    except PackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"media_id": media.id, "manifest": manifest, "status": status}


def _safe_bundle_path(bundle_dir: Path, rel: str) -> Path:
    target = (bundle_dir / rel).resolve()
    try:
        target.relative_to(bundle_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    return target


async def _serve_bundle_file(session: AsyncSession, media_id: int, path: str) -> Response:
    media = await _package_media(session, media_id)
    bundle_dir = Path(media.file_path)
    rel = path or COVER_NAME
    target = _safe_bundle_path(bundle_dir, rel)
    if target.is_file():
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        headers = {**ID_KEYED_CACHE_HEADERS, "Access-Control-Allow-Origin": "*"}
        if target.name == COVER_NAME:
            html = target.read_text(encoding="utf-8").replace(
                '<html lang="en" data-stimma-package="1">', '<html lang="en" data-stimma-package="1" data-stimma-host="local">', 1
            )
            return HTMLResponse(html, headers=headers)
        return FileResponse(target, media_type=mime, headers=headers)
    manifest = await manifest_for_media(session, media)
    if manifest is not None:
        data = await asyncio.to_thread(run_zip_for_path, bundle_dir, manifest, rel)
        if data is not None:
            return Response(
                content=data,
                media_type="application/zip",
                headers={**ID_KEYED_CACHE_HEADERS, "Content-Disposition": content_disposition("attachment", Path(rel).name)},
            )
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/media/{media_id}/package-file/{path:path}")
async def get_package_file(media_id: int, path: str, session: AsyncSession = Depends(get_db_session)):
    """A file inside the bundle. ``<run-root>.zip`` is produced on the fly."""
    return await _serve_bundle_file(session, media_id, path)


@router.get("/db/{db_guid}/media/{media_id}/package-file/{path:path}")
async def get_package_file_by_db_guid(
    db_guid: str, media_id: int, path: str, session: AsyncSession = Depends(get_db_session_by_guid)
):
    return await _serve_bundle_file(session, media_id, path)


@router.get("/media/{media_id}/package-cover")
async def get_package_cover(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """The cover with previews inlined (self-contained), for thumbnails and previews."""
    media = await _package_media(session, media_id)
    html = await asyncio.to_thread(export_single_html, Path(media.file_path))
    return HTMLResponse(html, headers=ID_KEYED_CACHE_HEADERS)


class PackageExportRequest(BaseModel):
    format: str = "zip"  # zip | html


@router.post("/media/{media_id}/package-export")
async def export_package(media_id: int, body: PackageExportRequest, session: AsyncSession = Depends(get_db_session)):
    media = await _package_media(session, media_id)
    manifest = await manifest_for_media(session, media)
    if manifest is None:
        raise HTTPException(status_code=500, detail="Package manifest is unreadable")
    slug = manifest.get("slug") or slugify(manifest.get("title") or "package")
    if body.format == "zip":
        data = await asyncio.to_thread(export_zip, Path(media.file_path), manifest, folder_name=slug)
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/zip",
            headers={"Content-Disposition": content_disposition("attachment", f"{slug}.zip")},
        )
    if body.format == "html":
        html = await asyncio.to_thread(export_single_html, Path(media.file_path))
        return StreamingResponse(
            io.BytesIO(html.encode("utf-8")),
            media_type="text/html",
            headers={"Content-Disposition": content_disposition("attachment", f"{slug}.html")},
        )
    if body.format == "link":
        raise HTTPException(status_code=501, detail="Hosted links are not available yet")
    raise HTTPException(status_code=400, detail="format must be zip or html")


@router.get("/assets/{asset_id}/package/status")
async def get_package_status(asset_id: int, session: AsyncSession = Depends(get_db_session)):
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.asset_type != "package" or not asset.current_revision_id:
        raise HTTPException(status_code=404, detail="Package asset not found")
    head = await session.get(AssetRevision, asset.current_revision_id)
    media = await session.get(MediaItem, head.primary_media_id) if head else None
    if media is None:
        raise HTTPException(status_code=404, detail="Package revision has no media")
    try:
        return await package_status(session, media)
    except PackageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class RebuildRequest(BaseModel):
    note: Optional[str] = None


@router.post("/assets/{asset_id}/package/rebuild")
async def post_rebuild(asset_id: int, body: RebuildRequest | None = None, session: AsyncSession = Depends(get_db_session)):
    """New revision: recipes re-run against current masters, cover carried forward."""
    try:
        media, asset, report = await rebuild_package(
            session, profile_id=get_current_profile(), asset_id=asset_id, note=(body.note if body else None)
        )
    except (PackageError, RecipeError, CoverError, ManifestError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"media_id": media.id, "asset_id": asset.id, "revision_id": asset.current_revision_id, "report": report}


@router.get("/packages/cache")
async def get_cache_stats():
    s = run_cache.stats(get_current_profile())
    return {"entries": s.entries, "bytes": s.bytes, "root": s.root}


@router.delete("/packages/cache")
async def clear_cache():
    run_cache.clear(get_current_profile())
    return {"ok": True}

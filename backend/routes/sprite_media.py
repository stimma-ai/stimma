"""Sprite document routes: export targets and the export endpoint.

Mirrors ``svg_media.py``/the layout export: one POST per media item with an
options model, returning an attachment. Writers live in ``sprite_export`` so
the agent sandbox (``stimma.library.export``) shares them.
"""

from __future__ import annotations

import asyncio
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from core.logging import get_logger
from database import MediaItem
from sprite_document import is_sprite_format
from sprite_export import (
    EXPORT_TARGETS,
    GROUPS,
    SpriteExportError,
    SpriteExportOptions,
    load_sprite_source,
    run_sprite_export,
)
from utils.http_headers import content_disposition
from utils.query_builder import not_due_for_autodelete

log = get_logger(__name__)
router = APIRouter()


@router.get("/sprite-export/targets")
async def list_sprite_export_targets():
    """Export targets grouped for the Export dialog."""
    return {
        "groups": [
            {
                "id": group,
                "targets": [
                    {"id": key, **info}
                    for key, info in EXPORT_TARGETS.items()
                    if info["group"] == group
                ],
            }
            for group in GROUPS
        ]
    }


async def _load_sprite(media_id: int, session: AsyncSession) -> MediaItem:
    item = await session.scalar(
        select(MediaItem).where(
            MediaItem.id == media_id,
            MediaItem.deleted_at.is_(None),
            MediaItem.deletion_pending_at.is_(None),
            MediaItem.ephemeral_run_id.is_(None),
            not_due_for_autodelete(),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if not is_sprite_format(item.file_format):
        raise HTTPException(status_code=400, detail="Not a sprite asset")
    return item


@router.post("/media/{media_id}/sprite-export")
async def export_sprite(
    media_id: int,
    request: SpriteExportOptions = SpriteExportOptions(),
    session: AsyncSession = Depends(get_db_session),
):
    """Export a sprite for a game engine, as loose frames, or as a preview."""
    item = await _load_sprite(media_id, session)
    try:
        source = await load_sprite_source(session, item)
        result = await asyncio.to_thread(run_sprite_export, source, request)
    except SpriteExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        io.BytesIO(result.payload),
        media_type=result.media_type,
        headers={
            "Content-Disposition": content_disposition("attachment", result.filename),
            "Access-Control-Allow-Origin": "*",
        },
    )

"""Timeline service: glue between the op-log store and the Asset system.

Live editing (agent tools, sequencer API) goes through apply_ops/undo/redo —
durable immediately via the op log; the WorkingDocument row tracks the edit
session. save_revision materializes the canonical snapshot through the one
serializer and commits it as an immutable AssetRevision with container
members, exactly like sets/grids.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from asset_service import AssetServiceError, create_working_document
from config_version import get_config_version_manager
from container_service import (
    commit_container_revision,
    create_container_asset_from_media,
)
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import Asset, AssetRevision, MediaItem, WorkingDocument
from generation_metadata import dump_generation_metadata
from utils.websocket import ws_manager

from .ops import new_entry_id
from .serializer import serialize_snapshot, snapshot_duration
from .store import TimelineProject, get_project, run_store

log = get_logger(__name__)

EDITOR_TYPE = "timeline"


def project_dir_for(project_key: str) -> Path:
    return app_dirs.get_timeline_projects_dir(get_current_profile()) / project_key


async def get_project_for_asset(
    session: AsyncSession, asset_id: int
) -> tuple[WorkingDocument, TimelineProject]:
    doc = await session.scalar(
        select(WorkingDocument).where(
            WorkingDocument.asset_id == asset_id,
            WorkingDocument.editor_type == EDITOR_TYPE,
            WorkingDocument.deleted_at.is_(None),
        )
    )
    if doc is None or not doc.state_locator:
        raise AssetServiceError("Asset has no timeline working document")
    return doc, get_project(project_dir_for(doc.state_locator))


async def _touch_working_document(session: AsyncSession, doc: WorkingDocument) -> None:
    doc.generation = (doc.generation or 0) + 1
    doc.updated_at = datetime.utcnow()
    await session.flush()


async def _broadcast_changed(asset_id: int, result: dict) -> None:
    await ws_manager.broadcast(
        "timeline_changed",
        {
            "asset_id": asset_id,
            "cursor": result.get("cursor"),
            "can_undo": result.get("can_undo"),
            "can_redo": result.get("can_redo"),
        },
    )


async def apply_ops(
    session: AsyncSession,
    *,
    asset_id: int,
    ops: list[tuple[str, dict]],
    author: str,
    label: Optional[str] = None,
) -> dict:
    doc, project = await get_project_for_asset(session, asset_id)
    result = await run_store(project.append_batch, ops, author=author, label=label)
    result.update(await run_store(project.status))
    await _touch_working_document(session, doc)
    await session.commit()
    await _broadcast_changed(asset_id, result)
    return result


async def undo(session: AsyncSession, *, asset_id: int) -> dict:
    doc, project = await get_project_for_asset(session, asset_id)
    result = await run_store(project.undo)
    await _touch_working_document(session, doc)
    await session.commit()
    await _broadcast_changed(asset_id, result)
    return result


async def redo(session: AsyncSession, *, asset_id: int) -> dict:
    doc, project = await get_project_for_asset(session, asset_id)
    result = await run_store(project.redo)
    await _touch_working_document(session, doc)
    await session.commit()
    await _broadcast_changed(asset_id, result)
    return result


def _clip_media_ids(state: dict) -> list[int]:
    ids: list[int] = []
    for track in state["tracks"]:
        for entry in track["entries"]:
            if entry["kind"] == "clip":
                ids.append(entry["media"]["media_id"])
    return ids


async def _member_specs(session: AsyncSession, media_ids: list[int]) -> list[dict]:
    """One member per clip, in track order: linked Asset when one exists,
    exact embedded Media otherwise — the standard container duality."""
    specs: list[dict] = []
    for media_id in media_ids:
        revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == media_id,
                AssetRevision.deleted_at.is_(None),
            )
        )
        if revision is not None:
            specs.append({"linked_asset_id": revision.asset_id})
        else:
            specs.append({"embedded_media_id": media_id})
    return specs


async def _write_snapshot_media(
    session: AsyncSession,
    *,
    state: dict,
    source: str,
) -> tuple[MediaItem, dict]:
    """Serialize state and land it as a .stimmatimeline.json MediaItem."""
    media_ids = _clip_media_ids(state)
    items: dict[int, MediaItem] = {}
    if media_ids:
        rows = await session.execute(
            select(MediaItem).where(MediaItem.id.in_(media_ids))
        )
        items = {m.id: m for m in rows.scalars().all()}
        missing = [mid for mid in media_ids if mid not in items]
        if missing:
            raise AssetServiceError(f"Timeline references missing media: {missing}")

    profile_id = get_current_profile()
    output_folder = app_dirs.get_managed_staging_dir(profile_id, "generated")
    output_folder.mkdir(parents=True, exist_ok=True)

    media_paths: dict[int, str] = {}
    for media_id, item in items.items():
        try:
            media_paths[media_id] = os.path.relpath(Path(item.file_path), output_folder)
        except ValueError:
            media_paths[media_id] = str(item.file_path)

    snapshot = serialize_snapshot(state, media_paths)
    snapshot_text = json.dumps(snapshot, indent=2, ensure_ascii=False)

    base_name = (state.get("title") or "timeline").replace(" ", "_").replace("/", "-")[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = output_folder / f"{base_name}_{timestamp}.stimmatimeline.json"
    counter = 1
    while file_path.exists():
        file_path = output_folder / f"{base_name}_{timestamp}_{counter}.stimmatimeline.json"
        counter += 1
    file_path.write_text(snapshot_text, encoding="utf-8")

    stat_info = file_path.stat()
    media = MediaItem(
        file_path=str(file_path),
        file_hash=hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest(),
        file_size=stat_info.st_size,
        file_format="stimmatimeline.json",
        created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
        modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
        indexed_date=datetime.utcnow(),
        metadata_status="completed",
        metadata_processed_at=datetime.utcnow(),
        metadata_config_version=get_config_version_manager().get_version("metadata"),
        width=int(state["width"]),
        height=int(state["height"]),
        megapixels=0,
        duration=snapshot_duration(state) or None,
        raw_metadata=snapshot_text,
        generation_metadata=dump_generation_metadata(
            task_type="timeline-save",
            source=source,
            source_inputs=[{"media_id": mid, "role": "clip"} for mid in media_ids],
            extra={
                "entry_count": sum(len(t["entries"]) for t in state["tracks"]),
                "clip_count": len(media_ids),
            },
        ),
    )
    session.add(media)
    await session.flush()

    from storage_service import stage_managed_media

    await stage_managed_media(
        session, media=media, profile_id=profile_id, remove_source=True
    )
    return media, snapshot


async def create_timeline_asset(
    session: AsyncSession,
    *,
    title: str = "",
    fps: float = 30,
    width: int = 1920,
    height: int = 1080,
    author: str = "user",
    origin_type: Optional[str] = None,
    origin_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create the project store, its empty first snapshot, the Asset, and the
    working document. Returns {asset_id, media_id, state, ...status}."""
    project_key = new_entry_id()
    project = get_project(project_dir_for(project_key))
    result = await run_store(
        project.append_batch,
        [("create_timeline", {"title": title, "fps": fps, "width": width, "height": height})],
        author=author,
        label="Create timeline",
    )
    state = result["state"]

    media, _ = await _write_snapshot_media(session, state=state, source="timeline_editor")
    asset = await create_container_asset_from_media(
        session,
        media_id=media.id,
        container_type="timeline",
        members=[],
        title=title or None,
        origin_type=origin_type,
        origin_id=origin_id,
    )
    await create_working_document(
        session,
        asset_id=asset.id,
        editor_type=EDITOR_TYPE,
        state_locator=project_key,
    )
    await session.commit()

    from storage_service import cleanup_staged_source

    await cleanup_staged_source(session, media_id=media.id)
    await ws_manager.broadcast("media_added", {"media_id": media.id, "count": 1})

    status = await run_store(project.status)
    return {"asset_id": asset.id, "media_id": media.id, "state": state, **status}


async def save_revision(
    session: AsyncSession,
    *,
    asset_id: int,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Deliberate save point: snapshot the working state as a new revision."""
    doc, project = await get_project_for_asset(session, asset_id)
    state = await run_store(project.state)
    if state is None:
        raise AssetServiceError("Timeline has no state to save")

    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise AssetServiceError("Asset is unavailable")

    media, _ = await _write_snapshot_media(session, state=state, source="timeline_editor")
    revision = await commit_container_revision(
        session,
        asset_id=asset_id,
        media_id=media.id,
        members=await _member_specs(session, _clip_media_ids(state)),
        note=note,
    )
    if state.get("title") and asset.title != state["title"]:
        asset.title = state["title"]
    doc.base_revision_id = revision.id
    await session.commit()

    from storage_service import cleanup_staged_source

    await cleanup_staged_source(session, media_id=media.id)
    await ws_manager.broadcast("media_added", {"media_id": media.id, "count": 1})

    return {
        "asset_id": asset_id,
        "revision_id": revision.id,
        "revision_number": revision.revision_number,
        "media_id": media.id,
    }

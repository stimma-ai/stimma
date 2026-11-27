"""
Lineage tracking utilities for media items.

This module provides centralized functions for recording lineage relationships
between media items. Lineage tracks which source images were used to create
a new media item (e.g., for image-to-image generation, grids, sets, documents).
"""

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem, MediaLineage, MediaToolLineage

log = logging.getLogger(__name__)


def build_inherited_lineage_trace(parent_media: Any) -> list[dict]:
    """Return a parent's full history with the parent as the newest ancestor.

    ``lineage_trace`` never contains the current output. Producers that derive
    a new Media item must inherit the parent's existing trace and then append a
    snapshot of the parent itself. Keeping this here beside the relational
    lineage helpers prevents one-off producers from accidentally inventing a
    synthetic step or pointing an ancestor entry at the child.
    """
    parent_meta: dict = {}
    raw_metadata = getattr(parent_media, "generation_metadata", None)
    if raw_metadata:
        try:
            parsed = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
            if isinstance(parsed, dict):
                parent_meta = parsed
        except (TypeError, json.JSONDecodeError):
            pass

    trace = [
        dict(entry)
        for entry in (parent_meta.get("lineage_trace") or [])
        if isinstance(entry, dict)
    ]

    parent_id = getattr(parent_media, "id", None)
    if parent_id is None:
        return trace

    # A few legacy producers stored seed at the top level. Preserve it in both
    # places so old and new history consumers render the same facts.
    parameters = dict(parent_meta.get("parameters") or {})
    if parameters.get("seed") is None and parent_meta.get("seed") is not None:
        parameters["seed"] = parent_meta["seed"]

    created_date = getattr(parent_media, "created_date", None)
    generated_at = parent_meta.get("generated_at")
    if generated_at is None and created_date is not None:
        generated_at = created_date.isoformat() + "Z"

    parent_entry = {
        "media_id": parent_id,
        "task_type": parent_meta.get("task_type"),
        "tool_id": parent_meta.get("tool_id"),
        "model": parent_meta.get("model"),
        "generator": parent_meta.get("generator"),
        "prompt": parent_meta.get("prompt"),
        "negative_prompt": parent_meta.get("negative_prompt"),
        "parameters": parameters,
        "generated_at": generated_at,
        "source_inputs": (
            parent_meta.get("source_inputs")
            if isinstance(parent_meta.get("source_inputs"), list)
            else []
        ),
    }
    if parent_meta.get("seed") is not None:
        parent_entry["seed"] = parent_meta["seed"]

    # Malformed historical rows may already mention the parent. Replace that
    # snapshot instead of showing the same Media twice in a derived history.
    trace = [entry for entry in trace if entry.get("media_id") != parent_id]
    trace.append(parent_entry)
    return trace


def _as_media_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


async def existing_media_ids(session: AsyncSession, media_ids) -> set[int]:
    """The ids among ``media_ids`` that still have a Media row.

    A source can be permanently deleted after a job picks it up (or while a
    tool's reference slot still remembers it), so lineage writers keep only the
    sources that still exist instead of failing the finished output.
    """
    ids = {i for i in map(_as_media_id, media_ids) if i is not None}
    if not ids:
        return set()
    rows = await session.scalars(select(MediaItem.id).where(MediaItem.id.in_(ids)))
    return set(rows)


async def record_lineage(
    session: AsyncSession,
    media_id: int,
    source_media_ids: list[int],
    task_type: str,
    relationship_type: str = 'derived',
) -> None:
    """
    Record lineage relationships for a media item.

    This records which source media items were used to create the given output.
    If lineage already exists for this media_id, it is replaced.

    Note: The caller is responsible for committing the session.

    Args:
        session: Database session to use
        media_id: The newly created media item ID
        source_media_ids: List of source media IDs that contributed to this output
        task_type: The task type that created this media (e.g., "grid-creation")
    """
    if not source_media_ids:
        return

    # Delete any existing lineage for this media (handles retries/race conditions)
    await session.execute(
        delete(MediaLineage).where(MediaLineage.media_id == media_id)
    )

    present = await existing_media_ids(session, source_media_ids)
    source_media_ids = [i for i in map(_as_media_id, source_media_ids) if i in present]
    for i, source_id in enumerate(source_media_ids):
        lineage = MediaLineage(
            media_id=media_id,
            source_media_id=source_id,
            source_order=i,
            task_type=task_type,
            relationship_type=relationship_type,
        )
        session.add(lineage)

    log.info(f"Added {len(source_media_ids)} lineage entries for media {media_id}")


async def record_lineage_from_inputs(
    session: AsyncSession,
    media_id: int,
    source_inputs: list[dict],
    task_type: str,
    relationship_type: str = 'derived',
) -> None:
    """
    Record lineage relationships from source input dictionaries.

    This variant accepts the source_inputs format used by the generation queue,
    which can include both media_id and file_path for external sources.

    Note: The caller is responsible for committing the session.

    Args:
        session: Database session to use
        media_id: The newly created media item ID
        source_inputs: List of source input dicts with media_id, file_path, role
        task_type: The task type that created this media
    """
    if not source_inputs:
        return

    # Delete any existing lineage for this media (handles retries/race conditions)
    await session.execute(
        delete(MediaLineage).where(MediaLineage.media_id == media_id)
    )

    # A source deleted since the job started keeps its file path, like an
    # external file, rather than pointing at a Media row that is gone.
    present = await existing_media_ids(session, [s.get('media_id') for s in source_inputs])
    for i, source in enumerate(source_inputs):
        source_id = _as_media_id(source.get('media_id'))
        if source_id not in present:
            source_id = None
        lineage = MediaLineage(
            media_id=media_id,
            source_media_id=source_id,
            source_file_path=source.get('file_path') if source_id is None else None,
            source_order=i,
            task_type=task_type,
            relationship_type=relationship_type,
        )
        session.add(lineage)

    log.info(f"Added {len(source_inputs)} lineage entries for media {media_id}")


async def propagate_tool_lineage(
    session: AsyncSession,
    media_id: int,
    source_media_ids: list[int] | None = None,
    own_tool_id: str | None = None,
) -> None:
    """
    Populate media_tool_lineage for a new media item.

    Collects tool IDs from:
    1. The item's own tool_id (if it was directly generated)
    2. All tool_ids inherited from source items' lineage chains

    Note: The caller is responsible for committing the session.

    Args:
        session: Database session to use
        media_id: The newly created media item ID
        source_media_ids: List of source media IDs (parents)
        own_tool_id: The tool that directly created this media item (if any)
    """
    tool_ids = set()

    if own_tool_id:
        tool_ids.add(own_tool_id)

    if source_media_ids:
        # Collect all tool_ids from source items' lineage
        result = await session.execute(
            select(MediaToolLineage.full_tool_id)
            .where(MediaToolLineage.media_id.in_(source_media_ids))
        )
        for row in result.scalars():
            tool_ids.add(row)

    if not tool_ids:
        return

    # Delete any existing tool lineage for this media (handles retries)
    await session.execute(
        delete(MediaToolLineage).where(MediaToolLineage.media_id == media_id)
    )

    for tid in tool_ids:
        session.add(MediaToolLineage(media_id=media_id, full_tool_id=tid))

    log.info(f"Added {len(tool_ids)} tool lineage entries for media {media_id}")

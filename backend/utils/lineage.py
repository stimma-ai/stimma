"""
Lineage tracking utilities for media items.

This module provides centralized functions for recording lineage relationships
between media items. Lineage tracks which source images were used to create
a new media item (e.g., for image-to-image generation, grids, sets, documents).
"""

import logging
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaLineage, MediaToolLineage

log = logging.getLogger(__name__)


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

    for i, source in enumerate(source_inputs):
        lineage = MediaLineage(
            media_id=media_id,
            source_media_id=source.get('media_id'),
            source_file_path=source.get('file_path') if not source.get('media_id') else None,
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

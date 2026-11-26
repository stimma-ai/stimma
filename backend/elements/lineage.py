"""Generation lineage: which element revisions a Media was made with.

``record_media_elements`` writes ``media_elements`` rows and the same facts
into ``generation_metadata["elements"]`` so the record is self-contained.
The job that runs with elements (ToolView, chat ``call_tool``) calls it once
the output Media exists.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset, AssetRevision, MediaElement, MediaItem
from elements.manifest import ELEMENT_ASSET_TYPE


async def record_media_elements(
    session: AsyncSession, media_id: int, elements: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Record ``[{asset_id, revision_id?, carrier?}]`` on ``media_id``. Unknown elements are skipped.

    ``revision_id`` defaults to the element's current revision. Returns the
    entries written to generation metadata.
    """
    media = await session.get(MediaItem, int(media_id))
    if media is None:
        return []
    entries: list[dict[str, Any]] = []
    seen: set[int] = set()
    for order, spec in enumerate(elements):
        try:
            asset_id = int(spec["asset_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if asset_id in seen:
            continue
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.asset_type != ELEMENT_ASSET_TYPE or asset.deleted_at is not None:
            continue
        revision_id = spec.get("revision_id") or asset.current_revision_id
        revision = await session.get(AssetRevision, int(revision_id)) if revision_id else None
        if revision is None or revision.asset_id != asset.id:
            continue
        seen.add(asset_id)
        carrier = spec.get("carrier") or None
        session.add(MediaElement(
            media_id=media.id,
            element_asset_id=asset.id,
            element_revision_id=revision.id,
            element_order=len(entries),
            carrier=carrier,
        ))
        entries.append({"asset_id": asset.id, "revision_id": revision.id, "name": asset.title, "carrier": carrier})
    if entries:
        try:
            metadata = json.loads(media.generation_metadata) if media.generation_metadata else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["elements"] = entries
        media.generation_metadata = json.dumps(metadata)
    await session.flush()
    return entries


async def media_made_with(session: AsyncSession, element_asset_id: int) -> list[int]:
    """Media ids made with an element, newest first."""
    rows = await session.scalars(
        select(MediaElement.media_id)
        .where(MediaElement.element_asset_id == element_asset_id, MediaElement.deleted_at.is_(None))
        .order_by(MediaElement.created_at.desc(), MediaElement.id.desc())
    )
    return list(rows)


async def scrub_element_lineage(session: AsyncSession, asset_ids: Iterable[int]) -> None:
    """Before an element is deleted: drop its lineage rows and its entries in outputs' metadata."""
    ids = {int(a) for a in asset_ids}
    if not ids:
        return
    media_ids = set(await session.scalars(
        select(MediaElement.media_id).where(MediaElement.element_asset_id.in_(ids))
    ))
    for media in (await session.scalars(select(MediaItem).where(MediaItem.id.in_(media_ids)))) if media_ids else []:
        try:
            metadata = json.loads(media.generation_metadata) if media.generation_metadata else None
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(metadata, dict) and isinstance(metadata.get("elements"), list):
            metadata["elements"] = [
                e for e in metadata["elements"] if not (isinstance(e, dict) and e.get("asset_id") in ids)
            ]
            if not metadata["elements"]:
                metadata.pop("elements")
            media.generation_metadata = json.dumps(metadata)
    await session.execute(delete(MediaElement).where(MediaElement.element_asset_id.in_(ids)))

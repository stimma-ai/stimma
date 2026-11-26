"""Generation lineage: which element revisions a Media was made with.

``record_media_elements`` writes ``media_elements`` rows and the same facts
into ``generation_metadata["elements"]`` so the record is self-contained.
The job that runs with elements (ToolView, chat ``call_tool``) calls it once
the output Media exists.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from database import Asset, AssetRevision, MediaElement, MediaItem
from elements.manifest import ELEMENT_ASSET_TYPE, parse_manifest
from utils.query_builder import asset_not_expired, browser_payload_visible


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


async def record_job_elements(session: AsyncSession, media_id: int, params: dict[str, Any]) -> list[dict[str, Any]]:
    """A finished job's ``_elements`` (``[{asset_id, revision_id?, carrier?}]``), recorded on its output."""
    specs = (params or {}).get("_elements")
    if not isinstance(specs, list) or not specs:
        return []
    return await record_media_elements(session, media_id, [s for s in specs if isinstance(s, dict)])


async def elements_used_by(session: AsyncSession, media_id: int) -> list[dict[str, Any]]:
    """The live elements a Media was made with, in the order they were used.

    Each entry names the element's current version (``media_id``/``file_hash``
    open and picture it) and the version that made this Media.
    """
    used = aliased(AssetRevision)
    current = aliased(AssetRevision)
    rows = (await session.execute(
        select(MediaElement, Asset, used, current, MediaItem)
        .join(Asset, Asset.id == MediaElement.element_asset_id)
        .join(used, used.id == MediaElement.element_revision_id)
        .join(current, current.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == current.primary_media_id)
        .where(
            MediaElement.media_id == int(media_id),
            MediaElement.deleted_at.is_(None),
            Asset.asset_type == ELEMENT_ASSET_TYPE,
            Asset.deleted_at.is_(None),
            Asset.state == "active",
        )
        .order_by(MediaElement.element_order, MediaElement.id)
    )).all()
    out = []
    for link, asset, used_rev, current_rev, media in rows:
        manifest = parse_manifest(media.raw_metadata or "") or {}
        out.append({
            "asset_id": asset.id,
            "name": asset.title or manifest.get("name") or "Untitled element",
            "kind": (manifest.get("kind") or "").lower(),
            "media_id": media.id,
            "file_hash": media.file_hash,
            "revision_number": used_rev.revision_number,
            "is_current_revision": used_rev.id == current_rev.id,
            "carrier": link.carrier,
        })
    return out


async def element_outputs(session: AsyncSession, element_asset_id: int, *, limit: int = 8) -> dict[str, Any]:
    """Library items made with an element, newest first: ``{total, items}``.

    Only items whose current version was made with it count, and only ones the
    library would show, matching its "made with" filter.
    """
    base = (
        select(Asset.id.label("asset_id"), MediaItem.id.label("media_id"), MediaItem.file_hash, MediaElement.created_at)
        .select_from(MediaElement)
        .join(MediaItem, MediaItem.id == MediaElement.media_id)
        .join(AssetRevision, AssetRevision.primary_media_id == MediaItem.id)
        .join(Asset, Asset.current_revision_id == AssetRevision.id)
        .where(
            MediaElement.element_asset_id == int(element_asset_id),
            MediaElement.deleted_at.is_(None),
            Asset.deleted_at.is_(None),
            Asset.state == "active",
            # The library's own visibility, so "Show all N" matches what it shows.
            browser_payload_visible(),
            asset_not_expired(),
        )
    )
    total = await session.scalar(select(func.count(func.distinct(base.subquery().c.asset_id))))
    rows = (await session.execute(
        base.order_by(MediaElement.created_at.desc(), MediaElement.id.desc()).limit(max(1, min(int(limit), 50)) * 2)
    )).all()
    items, seen = [], set()
    for row in rows:
        if row.asset_id in seen:
            continue
        seen.add(row.asset_id)
        items.append({"asset_id": row.asset_id, "media_id": row.media_id, "file_hash": row.file_hash})
        if len(items) >= limit:
            break
    return {"total": total or 0, "items": items}

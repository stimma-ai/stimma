"""Asset-level curation/organization compatibility projections and writes."""

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    AssetRevision,
    AssetMarker,
    AssetTag,
    Board,
    BoardAssetItem,
    BoardItem,
    MediaMarker,
    MediaTag,
    Marker,
    ProjectAsset,
    ProjectMedia,
    Tag,
    WorkingDocument,
)


async def classify_media_assets(
    session: AsyncSession, media_ids: list[int] | set[int],
) -> dict[int, str]:
    """Classify Media IDs by canonical Asset lifecycle state.

    Returns a mapping of media_id -> 'asset' | 'trashed' | 'bare':
    - 'asset': the payload of a live revision of an active Asset
    - 'trashed': retained only by a trashed/deleting Asset
    - 'bare': contextual Media with no Asset identity

    IDs without a MediaItem row are absent from the result.
    """
    ids = list(media_ids)
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(AssetRevision.primary_media_id, Asset.state)
            .join(Asset, Asset.id == AssetRevision.asset_id)
            .where(
                AssetRevision.primary_media_id.in_(ids),
                AssetRevision.deleted_at.is_(None),
            )
        )
    ).all()
    from database import MediaItem

    existing = set(
        await session.scalars(select(MediaItem.id).where(MediaItem.id.in_(ids)))
    )
    result = {mid: "bare" for mid in ids if mid in existing}
    for media_id, state in rows:
        if media_id not in result:
            continue
        if state == "active":
            result[media_id] = "asset"
        elif result[media_id] != "asset":
            result[media_id] = "trashed"
    return result


async def media_compatibility_projections(
    session: AsyncSession, media_items: list,
) -> list[dict]:
    """Project canonical Asset state onto legacy Media-shaped responses.

    Technical payload fields still come from Media. Curation, organization,
    retention, and trash state come only from the Asset that retains the
    payload. Bare contextual Media deliberately has no such state.
    """
    if not media_items:
        return []

    media_ids = [item.id for item in media_items]
    revision_rows = (
        await session.execute(
            select(AssetRevision, Asset)
            .join(Asset, Asset.id == AssetRevision.asset_id)
            .where(
                AssetRevision.primary_media_id.in_(media_ids),
                AssetRevision.deleted_at.is_(None),
            )
        )
    ).all()
    revisions_by_media = {
        revision.primary_media_id: (revision, asset)
        for revision, asset in revision_rows
    }
    asset_ids = [asset.id for _, asset in revisions_by_media.values()]

    markers: dict[int, list[dict]] = defaultdict(list)
    tags: dict[int, list[dict]] = defaultdict(list)
    working_document_assets: set[int] = set()
    if asset_ids:
        marker_rows = (
            await session.execute(
                select(AssetMarker, Marker)
                .join(Marker, Marker.id == AssetMarker.marker_id)
                .where(
                    AssetMarker.asset_id.in_(asset_ids),
                    AssetMarker.deleted_at.is_(None),
                    AssetMarker.source != "suppressed",
                )
            )
        ).all()
        for association, marker in marker_rows:
            markers[association.asset_id].append(
                {**marker.to_dict(), "source": association.source}
            )
        tag_rows = (
            await session.execute(
                select(AssetTag, Tag)
                .join(Tag, Tag.id == AssetTag.tag_id)
                .where(
                    AssetTag.asset_id.in_(asset_ids),
                    AssetTag.deleted_at.is_(None),
                )
            )
        ).all()
        for association, tag in tag_rows:
            tags[association.asset_id].append(tag.to_dict())
        working_document_assets = set(
            await session.scalars(
                select(WorkingDocument.asset_id).where(
                    WorkingDocument.asset_id.in_(asset_ids),
                    WorkingDocument.deleted_at.is_(None),
                )
            )
        )

    projections: list[dict] = []
    for media in media_items:
        item = media.to_dict()
        item["media_id"] = media.id
        item["media_deleted_at"] = item.get("deleted_at")
        item["auto_delete_at"] = None
        item["expires_at"] = None
        item["markers"] = []
        item["tags"] = []
        item["has_working_document"] = False

        retained = revisions_by_media.get(media.id)
        if retained is not None:
            revision, asset = retained
            item.update(
                {
                    "asset_id": asset.id,
                    "revision_id": revision.id,
                    "asset_state": asset.state,
                    "deleted_at": (
                        asset.deleted_at.isoformat() if asset.deleted_at else None
                    ),
                    "expires_at": (
                        asset.expires_at.isoformat() if asset.expires_at else None
                    ),
                    "auto_delete_at": (
                        asset.expires_at.isoformat()
                        if asset.state == "active" and asset.expires_at
                        else None
                    ),
                    "title": asset.title or item.get("title"),
                    "markers": markers[asset.id],
                    "tags": tags[asset.id],
                    "has_working_document": asset.id in working_document_assets,
                }
            )
        projections.append(item)
    return projections


async def asset_for_media(
    session: AsyncSession,
    media_id: int,
    *,
    promote: bool = False,
    origin_type: str = "organization_action",
) -> Asset | None:
    """Resolve Media to its stable Asset, optionally promoting it.

    Compatibility UI may still address a payload by Media id. Organization is
    Asset-only, so an explicit curation action promotes contextual Media rather
    than creating another Media-level source of truth.
    """
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if revision is not None:
        asset = await session.get(Asset, revision.asset_id)
        if asset is None or asset.deleted_at is not None or asset.state != "active":
            return None
        return asset
    if not promote:
        return None

    from asset_service import create_asset_from_media

    return await create_asset_from_media(
        session,
        media_id=media_id,
        origin_type=origin_type,
        origin_id=str(media_id),
        idempotency_key=f"{origin_type}:media:{media_id}",
    )


async def asset_ids_for_media_ids(
    session: AsyncSession,
    media_ids: list[int] | set[int],
    *,
    promote: bool = False,
    origin_type: str = "organization_action",
) -> dict[int, int]:
    """Resolve a batch of Media ids to Asset ids, preserving input identity."""
    resolved: dict[int, int] = {}
    for media_id in dict.fromkeys(media_ids):
        asset = await asset_for_media(
            session,
            media_id,
            promote=promote,
            origin_type=origin_type,
        )
        if asset is not None:
            resolved[media_id] = asset.id
    return resolved


async def clear_asset_expiration(session: AsyncSession, asset_id: int) -> Asset | None:
    """Make an Asset durable after user curation.

    Asset lifecycle is canonical. Clear historical ``MediaItem.auto_delete_at``
    residue on the current payload as a one-way compatibility repair; Media
    availability never depends on that legacy field.
    """
    asset = await session.get(Asset, asset_id)
    if asset is None:
        return None
    asset.expires_at = None
    if asset.current_revision_id is not None:
        revision = await session.get(AssetRevision, asset.current_revision_id)
        if revision is not None:
            from database import MediaItem

            media = await session.get(MediaItem, revision.primary_media_id)
            if media is not None:
                media.auto_delete_at = None
    return asset


async def broadcast_assets_retained(
    session: AsyncSession, asset_ids: list[int] | set[int], ws_manager
) -> None:
    """Project a committed retention action to legacy and Asset-first clients."""
    ids = sorted(set(asset_ids))
    if not ids:
        return
    media_ids = list(
        await session.scalars(
            select(AssetRevision.primary_media_id)
            .join(Asset, Asset.current_revision_id == AssetRevision.id)
            .where(
                Asset.id.in_(ids),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
                AssetRevision.deleted_at.is_(None),
            )
        )
    )
    for media_id in media_ids:
        await ws_manager.broadcast("auto_delete_removed", {"media_id": media_id})
    await ws_manager.broadcast(
        "assets_updated", {"asset_ids": ids, "fields": ["expires_at"]}
    )


async def broadcast_asset_organization_updated(
    session: AsyncSession,
    asset_ids: list[int] | set[int],
    ws_manager,
    *,
    fields: tuple[str, ...] = ("markers",),
) -> None:
    """Emit the full event pair every organization display surface consumes.

    Marker/tag state is Asset-level, but the display surfaces are a mix of
    Asset-first listeners (``assets_updated``, no payload — triggers refetch)
    and compatibility listeners that patch in place from ``media_updated``
    keyed by the current payload's media_id (grid tiles, slideshow, chat
    cards, job tiles, the useMarkers store). A write path that emits only
    ``assets_updated`` leaves every in-place surface stale until an unrelated
    refetch, so all Asset-level organization writes must go through here.
    """
    from database import MediaItem

    ids = sorted(set(asset_ids))
    if not ids:
        return
    media_items = list(
        await session.scalars(
            select(MediaItem)
            .join(AssetRevision, AssetRevision.primary_media_id == MediaItem.id)
            .join(Asset, Asset.current_revision_id == AssetRevision.id)
            .where(
                Asset.id.in_(ids),
                Asset.deleted_at.is_(None),
                AssetRevision.deleted_at.is_(None),
            )
        )
    )
    for projection in await media_compatibility_projections(session, media_items):
        if "expires_at" in fields and projection.get("expires_at") is None:
            await ws_manager.broadcast(
                "auto_delete_removed", {"media_id": projection["media_id"]}
            )
        await ws_manager.broadcast(
            "media_updated",
            {
                "media_id": projection["media_id"],
                "asset_id": projection.get("asset_id"),
                "fields": list(fields),
                "media": projection,
            },
        )
    await ws_manager.broadcast(
        "assets_updated", {"asset_ids": ids, "fields": list(fields)}
    )


async def _add_live(session, model, lookup: dict, values: dict):
    existing = await session.scalar(
        select(model).where(
            *(getattr(model, key) == value for key, value in lookup.items()),
            model.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing
    row = model(**values)
    session.add(row)
    await session.flush()
    return row


async def attach_asset_to_project(session: AsyncSession, project_id: int, asset_id: int):
    row = await _add_live(
        session,
        ProjectAsset,
        {"project_id": project_id, "asset_id": asset_id},
        {"project_id": project_id, "asset_id": asset_id},
    )
    await clear_asset_expiration(session, asset_id)
    return row


async def detach_asset_from_project(session: AsyncSession, project_id: int, asset_id: int) -> bool:
    row = await session.scalar(
        select(ProjectAsset).where(
            ProjectAsset.project_id == project_id,
            ProjectAsset.asset_id == asset_id,
            ProjectAsset.deleted_at.is_(None),
        )
    )
    if row is None:
        return False
    row.deleted_at = datetime.utcnow()
    await session.flush()
    return True


async def attach_asset_to_board_section(
    session: AsyncSession,
    *,
    board: Board,
    section_id: int,
    asset_id: int,
    display_order: int,
) -> tuple[BoardAssetItem | None, bool]:
    """Add one live Asset to a board and apply board retention semantics."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.state != "active" or asset.deleted_at is not None:
        return None, False
    existing = await session.scalar(
        select(BoardAssetItem).where(
            BoardAssetItem.board_section_id == section_id,
            BoardAssetItem.asset_id == asset_id,
            BoardAssetItem.deleted_at.is_(None),
        )
    )
    await clear_asset_expiration(session, asset_id)
    if board.project_id is not None:
        await attach_asset_to_project(session, board.project_id, asset_id)
    if existing is not None:
        await session.flush()
        return existing, False
    row = BoardAssetItem(
        board_section_id=section_id,
        asset_id=asset_id,
        display_order=display_order,
    )
    session.add(row)
    await session.flush()
    return row, True


async def set_asset_marker(
    session: AsyncSession, *, asset_id: int, marker_id: int, add: bool
) -> bool:
    row = await session.scalar(
        select(AssetMarker).where(
            AssetMarker.asset_id == asset_id,
            AssetMarker.marker_id == marker_id,
            AssetMarker.deleted_at.is_(None),
        )
    )
    if add:
        await clear_asset_expiration(session, asset_id)
        if row is not None and row.source == "manual":
            await session.flush()
            return False
        if row is None:
            session.add(
                AssetMarker(asset_id=asset_id, marker_id=marker_id, source="manual")
            )
        else:
            row.source = "manual"
        await session.flush()
        return True
    if row is None:
        return False
    if row.source == "auto":
        row.source = "suppressed"
    else:
        row.deleted_at = datetime.utcnow()
    await session.flush()
    return True


async def set_asset_tag(
    session: AsyncSession, *, asset_id: int, tag_id: int, add: bool
) -> bool:
    row = await session.scalar(
        select(AssetTag).where(
            AssetTag.asset_id == asset_id,
            AssetTag.tag_id == tag_id,
            AssetTag.deleted_at.is_(None),
        )
    )
    if add:
        await clear_asset_expiration(session, asset_id)
        if row is not None:
            await session.flush()
            return False
        session.add(AssetTag(asset_id=asset_id, tag_id=tag_id))
        await session.flush()
        return True
    if row is None:
        return False
    row.deleted_at = datetime.utcnow()
    await session.flush()
    return True


async def mirror_media_associations_to_asset(
    session: AsyncSession,
    *,
    media_id: int,
    asset_id: int,
) -> None:
    """Consume historical Media organization into its stable Asset identity.

    The legacy rows are staging/migration residue, not a second live model.
    Once an Asset exists, move their meaning to canonical Asset associations
    and remove the old edges so later Media reads cannot drift.
    """
    marker_rows = list(
        await session.scalars(
            select(MediaMarker).where(MediaMarker.media_id == media_id)
        )
    )
    for marker in marker_rows:
        existing = await session.scalar(
            select(AssetMarker).where(
                AssetMarker.asset_id == asset_id,
                AssetMarker.marker_id == marker.marker_id,
                AssetMarker.deleted_at.is_(None),
            )
        )
        if marker.source == "suppressed":
            if existing is None:
                session.add(
                    AssetMarker(
                        asset_id=asset_id,
                        marker_id=marker.marker_id,
                        source="suppressed",
                        created_at=marker.created_at or datetime.utcnow(),
                    )
                )
            else:
                existing.source = "suppressed"
        elif existing is None:
            session.add(
                AssetMarker(
                    asset_id=asset_id,
                    marker_id=marker.marker_id,
                    source=marker.source,
                    created_at=marker.created_at or datetime.utcnow(),
                )
            )
        elif existing.source != "manual" or marker.source == "manual":
            existing.source = marker.source
        await session.delete(marker)

    tag_ids = list(
        await session.scalars(
            select(MediaTag.tag_id).where(MediaTag.media_id == media_id)
        )
    )
    for tag_id in tag_ids:
        await _add_live(
            session,
            AssetTag,
            {"asset_id": asset_id, "tag_id": tag_id},
            {"asset_id": asset_id, "tag_id": tag_id},
        )
    if tag_ids:
        tag_rows = list(
            await session.scalars(
                select(MediaTag).where(MediaTag.media_id == media_id)
            )
        )
        for row in tag_rows:
            await session.delete(row)

    project_rows = list(
        await session.scalars(
            select(ProjectMedia).where(ProjectMedia.media_id == media_id)
        )
    )
    for project_row in project_rows:
        project_id = project_row.project_id
        await attach_asset_to_project(session, project_id, asset_id)
        await session.delete(project_row)

    board_items = list(
        await session.scalars(select(BoardItem).where(BoardItem.media_id == media_id))
    )
    for board_item in board_items:
        await _add_live(
            session,
            BoardAssetItem,
            {"board_section_id": board_item.board_section_id, "asset_id": asset_id},
            {
                "board_section_id": board_item.board_section_id,
                "asset_id": asset_id,
                "display_order": board_item.display_order,
                "added_at": board_item.added_at,
            },
        )
        await session.delete(board_item)

    if marker_rows or tag_ids or board_items:
        await clear_asset_expiration(session, asset_id)
    await session.flush()

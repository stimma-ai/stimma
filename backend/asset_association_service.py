"""Asset-level curation/organization compatibility writes."""

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
    ProjectAsset,
    ProjectMedia,
)


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
    """Dual-write existing Media curation onto its new Asset identity."""
    marker_rows = list(
        await session.scalars(
            select(MediaMarker).where(
                MediaMarker.media_id == media_id,
                MediaMarker.source != 'suppressed',
            )
        )
    )
    for marker in marker_rows:
        await _add_live(
            session,
            AssetMarker,
            {"asset_id": asset_id, "marker_id": marker.marker_id},
            {
                "asset_id": asset_id,
                "marker_id": marker.marker_id,
                "source": marker.source,
                "created_at": marker.created_at or datetime.utcnow(),
            },
        )

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

    for project_id in await session.scalars(
        select(ProjectMedia.project_id).where(ProjectMedia.media_id == media_id)
    ):
        await attach_asset_to_project(session, project_id, asset_id)

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

    if marker_rows or tag_ids or board_items:
        await clear_asset_expiration(session, asset_id)
    await session.flush()

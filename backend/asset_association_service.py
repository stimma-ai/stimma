"""Asset-level curation/organization compatibility writes."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    AssetMarker,
    AssetTag,
    BoardAssetItem,
    BoardItem,
    MediaMarker,
    MediaTag,
    ProjectAsset,
    ProjectMedia,
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
    asset = await session.get(Asset, asset_id)
    if asset is not None:
        asset.expires_at = None
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
        if row is not None and row.source == "manual":
            return False
        if row is None:
            session.add(
                AssetMarker(asset_id=asset_id, marker_id=marker_id, source="manual")
            )
        else:
            row.source = "manual"
        asset = await session.get(Asset, asset_id)
        if asset is not None:
            asset.expires_at = None
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
        if row is not None:
            return False
        session.add(AssetTag(asset_id=asset_id, tag_id=tag_id))
        asset = await session.get(Asset, asset_id)
        if asset is not None:
            asset.expires_at = None
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

    for tag_id in await session.scalars(select(MediaTag.tag_id).where(MediaTag.media_id == media_id)):
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

    if marker_rows or board_items:
        asset = await session.get(Asset, asset_id)
        if asset is not None:
            asset.expires_at = None
    await session.flush()

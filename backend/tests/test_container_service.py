"""Tests for normalized linked and embedded container membership."""

import pytest
from sqlalchemy import func, select

from asset_service import commit_revision, create_asset_from_media
from container_service import (
    create_container_asset_from_media,
    explode_container,
    resolve_container_members,
    save_container_members_as_assets,
)
from database import Asset, MediaOwner
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_grid_cells_are_media_until_explode(db_session):
    async with db_session() as session:
        grid_media = await create_media_item(session, file_format="stimmagrid.json")
        first_cell = await create_media_item(session, file_format="png")
        second_cell = await create_media_item(session, file_format="png")
        grid = await create_container_asset_from_media(
            session,
            media_id=grid_media.id,
            container_type="grid",
            members=[
                {"embedded_media_id": first_cell.id, "row_index": 0, "column_index": 0},
                {"embedded_media_id": second_cell.id, "row_index": 0, "column_index": 1},
            ],
        )
        await session.commit()

        assert await session.scalar(select(func.count()).select_from(Asset)) == 1
        owners = list(
            await session.scalars(
                select(MediaOwner).where(
                    MediaOwner.root_kind == "container_revision",
                    MediaOwner.root_id == str(grid.current_revision_id),
                    MediaOwner.deleted_at.is_(None),
                )
            )
        )
        assert {owner.media_id for owner in owners} == {first_cell.id, second_cell.id}

        promoted_ids = await explode_container(session, asset_id=grid.id)
        await session.commit()
        assert len(promoted_ids) == 2
        assert await session.scalar(select(func.count()).select_from(Asset)) == 3
        assert grid.state == "trashed"
        # Trash preserves grid history, so its exact embedded payloads remain owned.
        assert all(owner.deleted_at is None for owner in owners)


@pytest.mark.asyncio
async def test_save_grid_cells_as_assets_preserves_the_grid(db_session):
    async with db_session() as session:
        before_count = await session.scalar(select(func.count()).select_from(Asset))
        grid_media = await create_media_item(session, file_format="stimmagrid.json")
        cell = await create_media_item(session, file_format="png")
        grid = await create_container_asset_from_media(
            session,
            media_id=grid_media.id,
            container_type="grid",
            members=[{"embedded_media_id": cell.id, "row_index": 0, "column_index": 0}],
        )
        promoted = await save_container_members_as_assets(session, asset_id=grid.id)
        await session.commit()

        assert len(promoted) == 1
        assert grid.state == "active"
        assert grid.deleted_at is None
        assert await session.scalar(select(func.count()).select_from(Asset)) == before_count + 2

        retried = await save_container_members_as_assets(session, asset_id=grid.id)
        await session.commit()
        assert retried == promoted
        assert await session.scalar(select(func.count()).select_from(Asset)) == before_count + 2


@pytest.mark.asyncio
async def test_linked_member_follows_current_revision_and_supports_multiple_membership(db_session):
    async with db_session() as session:
        original = await create_media_item(session, file_format="png")
        replacement = await create_media_item(session, file_format="png")
        linked = await create_asset_from_media(session, media_id=original.id)
        containers = []
        for _ in range(2):
            container_media = await create_media_item(session, file_format="stimmaset.json")
            containers.append(
                await create_container_asset_from_media(
                    session,
                    media_id=container_media.id,
                    container_type="set",
                    members=[{"linked_asset_id": linked.id}],
                )
            )
        await session.commit()

        for container in containers:
            resolved = await resolve_container_members(
                session, revision_id=container.current_revision_id
            )
            assert resolved[0]["media_id"] == original.id

        await commit_revision(session, asset_id=linked.id, media_id=replacement.id)
        await session.commit()
        for container in containers:
            resolved = await resolve_container_members(
                session, revision_id=container.current_revision_id
            )
            assert resolved[0]["media_id"] == replacement.id

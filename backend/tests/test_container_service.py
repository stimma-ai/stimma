"""Tests for normalized linked and embedded container membership."""

import json

import pytest
from sqlalchemy import func, select

from asset_service import commit_revision, create_asset_from_media
from container_service import (
    container_title_for_media,
    create_container_asset_from_media,
    explode_container,
    get_normalized_container_content,
    resolve_container_members,
    save_container_members_as_assets,
)
from asset_association_service import set_asset_marker
from database import Asset, AssetTag, Marker, MediaOwner, Tag
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


@pytest.mark.asyncio
async def test_set_content_carries_member_markers_and_tags(db_session):
    async with db_session() as session:
        linked_media = await create_media_item(session, file_format="mp4")
        saved_media = await create_media_item(session, file_format="mp4")
        bare_media = await create_media_item(session, file_format="mp4")
        linked = await create_asset_from_media(session, media_id=linked_media.id)
        saved = await create_asset_from_media(session, media_id=saved_media.id)
        marker = Marker(name="container-member-marker", icon_svg="<svg/>", color="#ff0000")
        tag = Tag(tag_text="container-member-tag")
        session.add_all([marker, tag])
        await session.flush()
        await set_asset_marker(session, asset_id=linked.id, marker_id=marker.id, add=True)
        await set_asset_marker(session, asset_id=saved.id, marker_id=marker.id, add=True)
        session.add(AssetTag(asset_id=linked.id, tag_id=tag.id))
        set_media = await create_media_item(session, file_format="stimmaset.json")
        await create_container_asset_from_media(
            session,
            media_id=set_media.id,
            container_type="set",
            members=[
                {"linked_asset_id": linked.id},
                {"embedded_media_id": saved_media.id},
                {"embedded_media_id": bare_media.id},
            ],
        )
        await session.commit()

        content = await get_normalized_container_content(session, container_media=set_media)
        members = [item["resolved"] for item in content["items"]]

        # Linked members show their Asset's organization; embedded members show
        # the saved Asset holding that exact Media, which marker writes target.
        assert [m["id"] for m in members[0]["markers"]] == [marker.id]
        assert [t["id"] for t in members[0]["tags"]] == [tag.id]
        assert [m["id"] for m in members[1]["markers"]] == [marker.id]
        assert members[1]["tags"] == []
        assert members[2]["markers"] == []


@pytest.mark.asyncio
async def test_container_title_comes_from_the_payload_seed_then_the_asset(db_session):
    async with db_session() as session:
        set_media = await create_media_item(
            session,
            file_format="stimmaset.json",
            raw_metadata=json.dumps({"version": 1, "title": "Wool Coat Variations", "items": []}),
        )
        member = await create_media_item(session, file_format="png")
        container = await create_container_asset_from_media(
            session,
            media_id=set_media.id,
            container_type="set",
            members=[{"embedded_media_id": member.id}],
        )
        await session.commit()

        # Promotion seeds Asset.title from the payload, so both the browser
        # projection and the set content endpoint agree.
        assert container.title == "Wool Coat Variations"
        content = await get_normalized_container_content(session, container_media=set_media)
        assert content["title"] == "Wool Coat Variations"

        # Renames land on the Asset only; the stale payload must not win.
        container.title = "Renamed"
        await session.commit()
        content = await get_normalized_container_content(session, container_media=set_media)
        assert content["title"] == "Renamed"
        assert await container_title_for_media(session, media_id=set_media.id) == "Renamed"

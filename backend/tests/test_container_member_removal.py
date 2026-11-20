"""Removing a member from a set or grid commits a new container Revision.

Delete acts on the image, never on the layout: sets drop the member, grids keep
the slot empty, and built documents (sheets, sprites, packages) refuse.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from asset_service import create_asset_from_media, trash_asset
from container_service import create_container_asset_from_media
from database import Asset, AssetRevision, ContainerMember, MediaItem
from tests.helpers.media import create_media_item
from tests.helpers.ws import MockWebSocketManager


async def _linked_assets(session, count):
    assets = []
    for _ in range(count):
        media = await create_media_item(session, file_format="png")
        assets.append(await create_asset_from_media(session, media_id=media.id))
    return assets


async def _container(session, *, file_format, container_type, members, manifest=None):
    container_media = await create_media_item(
        session,
        file_format=file_format,
        raw_metadata=json.dumps(manifest or {"version": 1}),
    )
    return await create_container_asset_from_media(
        session,
        media_id=container_media.id,
        container_type=container_type,
        members=members,
    )


async def _head_media_id(db_session, asset_id):
    async with db_session() as session:
        asset = await session.get(Asset, asset_id)
        revision = await session.get(AssetRevision, asset.current_revision_id)
        return revision.primary_media_id, revision.id


async def _remove(client, asset_id, member_id, **body):
    ws = MockWebSocketManager()
    with patch("routes.assets.ws_manager", ws):
        response = await client.post(
            f"/api/assets/item/{asset_id}/container-members/{member_id}/remove",
            json=body or None,
        )
    return response, ws


async def _revert(client, asset_id, revision_id, expected_revision_id):
    with patch("routes.assets.ws_manager", MockWebSocketManager()):
        return await client.post(
            f"/api/assets/item/{asset_id}/container-members/revert",
            json={"revision_id": revision_id, "expected_revision_id": expected_revision_id},
        )


async def _set_items(client, media_id):
    response = await client.get(f"/api/media/{media_id}/content")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_remove_linked_member_keeps_the_asset_and_reflows_the_set(client, db_session):
    async with db_session() as session:
        members = await _linked_assets(session, 3)
        container = await _container(
            session,
            file_format="stimmaset.json",
            container_type="set",
            members=[{"linked_asset_id": asset.id} for asset in members],
            manifest={"version": 1, "items": [{"path": "a"}, {"path": "b"}, {"path": "c"}]},
        )
        await session.commit()
        container_id, first_revision = container.id, container.current_revision_id
        member_asset_ids = [asset.id for asset in members]

    old_media_id, _ = await _head_media_id(db_session, container_id)
    content = await _set_items(client, old_media_id)
    middle = content["items"][1]
    assert middle["resolved"]["asset_id"] == member_asset_ids[1]

    response, ws = await _remove(
        client, container_id, middle["member_id"], expected_revision_id=first_revision
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous_revision_id"] == first_revision
    assert body["media_id"] != old_media_id
    assert any(
        event == "asset_current_revision_changed"
        and data["asset_id"] == container_id
        and data["media_id"] == body["media_id"]
        for event, data in ws.broadcasts
    )

    content = await _set_items(client, body["media_id"])
    assert [item["resolved"]["asset_id"] for item in content["items"]] == [
        member_asset_ids[0], member_asset_ids[2]
    ]
    async with db_session() as session:
        removed_asset = await session.get(Asset, member_asset_ids[1])
        assert removed_asset.state == "active" and removed_asset.deleted_at is None
        new_media = await session.get(MediaItem, body["media_id"])
        assert json.loads(new_media.raw_metadata)["items"] == [{"path": "a"}, {"path": "c"}]
        assert Path(new_media.file_path).is_file()


@pytest.mark.asyncio
async def test_remove_embedded_member_then_undo_puts_it_back_in_its_slot(client, db_session):
    async with db_session() as session:
        linked = (await _linked_assets(session, 1))[0]
        embedded = await create_media_item(session, file_format="png")
        tail = (await _linked_assets(session, 1))[0]
        container = await _container(
            session,
            file_format="stimmaset.json",
            container_type="set",
            members=[
                {"linked_asset_id": linked.id},
                {"embedded_media_id": embedded.id},
                {"linked_asset_id": tail.id},
            ],
        )
        await session.commit()
        container_id, embedded_id = container.id, embedded.id

    media_id, first_revision = await _head_media_id(db_session, container_id)
    content = await _set_items(client, media_id)
    assert content["items"][1]["resolved"]["media_id"] == embedded_id
    assert content["items"][1]["resolved"]["asset_id"] is None

    response, _ = await _remove(client, container_id, content["items"][1]["member_id"])
    assert response.status_code == 200, response.text
    removed = response.json()
    after = await _set_items(client, removed["media_id"])
    assert embedded_id not in [item["resolved"]["media_id"] for item in after["items"]]

    # The removal is the only thing undo may replace.
    stale = await _revert(client, container_id, first_revision, first_revision)
    assert stale.status_code == 409

    undone = await _revert(client, container_id, removed["previous_revision_id"], removed["revision_id"])
    assert undone.status_code == 200, undone.text
    restored = await _set_items(client, undone.json()["media_id"])
    assert [item["resolved"]["media_id"] for item in restored["items"]][1] == embedded_id
    assert len(restored["items"]) == 3
    # The embedded payload was never soft-deleted.
    async with db_session() as session:
        assert (await session.get(MediaItem, embedded_id)).deleted_at is None


@pytest.mark.asyncio
async def test_removal_carries_trashed_linked_members_as_holes(client, db_session):
    async with db_session() as session:
        trashed, kept, other = await _linked_assets(session, 3)
        container = await _container(
            session,
            file_format="stimmaset.json",
            container_type="set",
            members=[{"linked_asset_id": a.id} for a in (trashed, kept, other)],
        )
        await trash_asset(session, asset_id=trashed.id)
        await session.commit()
        container_id, trashed_id = container.id, trashed.id

    media_id, _ = await _head_media_id(db_session, container_id)
    content = await _set_items(client, media_id)
    assert content["items"][0]["resolved"] is None
    response, _ = await _remove(client, container_id, content["items"][2]["member_id"])
    assert response.status_code == 200, response.text

    # Restoring the trashed member brings it back in its slot.
    async with db_session() as session:
        from asset_service import restore_asset

        await restore_asset(session, asset_id=trashed_id)
        await session.commit()
    content = await _set_items(client, response.json()["media_id"])
    assert content["items"][0]["resolved"]["asset_id"] == trashed_id
    assert len(content["items"]) == 2


@pytest.mark.asyncio
async def test_stale_member_is_a_conflict(client, db_session):
    async with db_session() as session:
        members = await _linked_assets(session, 2)
        container = await _container(
            session,
            file_format="stimmaset.json",
            container_type="set",
            members=[{"linked_asset_id": a.id} for a in members],
        )
        await session.commit()
        container_id = container.id

    media_id, _ = await _head_media_id(db_session, container_id)
    member_id = (await _set_items(client, media_id))["items"][0]["member_id"]
    first, _ = await _remove(client, container_id, member_id)
    assert first.status_code == 200
    again, _ = await _remove(client, container_id, member_id)
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_clearing_an_embedded_grid_cell_keeps_the_slot(client, db_session):
    manifest = {
        "version": 1,
        "rows": 2,
        "cols": 2,
        "row_headers": ["A", "B"],
        "col_headers": ["one", "two"],
        "cells": [
            {"row": r, "col": c, "path": f"{r}-{c}.png"} for r in range(2) for c in range(2)
        ],
    }
    async with db_session() as session:
        cells = [await create_media_item(session, file_format="png") for _ in range(4)]
        container = await _container(
            session,
            file_format="stimmagrid.json",
            container_type="grid",
            members=[
                {"embedded_media_id": cells[r * 2 + c].id, "row_index": r, "column_index": c}
                for r in range(2)
                for c in range(2)
            ],
            manifest=manifest,
        )
        await session.commit()
        container_id = container.id

    media_id, _ = await _head_media_id(db_session, container_id)
    content = await _set_items(client, media_id)
    target = next(cell for cell in content["cells"] if (cell["row"], cell["col"]) == (0, 1))
    response, _ = await _remove(client, container_id, target["member_id"])
    assert response.status_code == 200, response.text

    after = await _set_items(client, response.json()["media_id"])
    assert (after["rows"], after["cols"]) == (2, 2)
    assert after["row_headers"] == ["A", "B"] and after["col_headers"] == ["one", "two"]
    positions = {(cell["row"], cell["col"]) for cell in after["cells"]}
    assert positions == {(0, 0), (1, 0), (1, 1)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("file_format", "container_type"),
    [
        ("stimmasheet.html", "sheet"),
        ("stimmasprite.json", "sprite"),
        ("stimmapackage", "package"),
    ],
)
async def test_built_documents_reject_member_removal(client, db_session, file_format, container_type):
    async with db_session() as session:
        part = await create_media_item(session, file_format="png")
        container = await _container(
            session,
            file_format=file_format,
            container_type=container_type,
            members=[{"embedded_media_id": part.id, "title": "m1"}],
        )
        await session.commit()
        container_id, revision_id = container.id, container.current_revision_id
        member_id = await session.scalar(
            select(ContainerMember.id).where(ContainerMember.container_revision_id == revision_id)
        )

    response, _ = await _remove(client, container_id, member_id)
    assert response.status_code == 400
    _, head_revision = await _head_media_id(db_session, container_id)
    assert head_revision == revision_id

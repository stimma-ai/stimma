"""Asset-first and contextual-Media API integration tests."""

import asyncio

import numpy as np
import pytest

from asset_service import (
    acquire_media_owner,
    commit_revision,
    create_asset_from_media,
    create_asset_snapshot,
    create_working_document,
)
from database import Asset, AssetMarker, AssetSnapshot, Marker, MediaItem
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_asset_browser_lists_only_assets_and_contextual_endpoint_finds_intermediates(
    client, db_session
):
    async with db_session() as session:
        asset_media = await create_media_item(session)
        intermediate = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=asset_media.id)
        await acquire_media_owner(
            session,
            media_id=intermediate.id,
            root_kind="chat",
            root_id="123",
            role="intermediate",
        )
        await session.commit()

    response = await client.get("/api/assets")
    assert response.status_code == 200
    payload = response.json()
    assert [item["asset"]["id"] for item in payload["items"]] == [asset.id]
    assert payload["items"][0]["media"]["id"] == asset_media.id
    assert intermediate.id not in {
        item["media"]["id"] for item in payload["items"]
    }

    contextual = await client.get("/api/assets/contextual-media")
    assert contextual.status_code == 200
    groups = contextual.json()["groups"]
    chat_group = next(group for group in groups if group["root_kind"] == "chat")
    assert chat_group["root_id"] == "123"
    assert [item["id"] for item in chat_group["items"]] == [intermediate.id]


@pytest.mark.asyncio
async def test_asset_browser_identity_and_curation_survive_current_revision_change(
    client, db_session
):
    async with db_session() as session:
        first = await create_media_item(session)
        second = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=first.id)
        marker = Marker(name="Winner", icon_svg="<svg />", color="#fff")
        session.add(marker)
        await session.flush()
        session.add(AssetMarker(asset_id=asset.id, marker_id=marker.id, source="manual"))
        asset_id = asset.id
        first_media_id = first.id
        await session.commit()

    before = (await client.get("/api/assets/browse")).json()["items"]
    item = next(item for item in before if item["asset_id"] == asset_id)
    assert item["id"] == asset_id
    assert item["media_id"] == first_media_id
    assert [entry["name"] for entry in item["markers"]] == ["Winner"]

    async with db_session() as session:
        await commit_revision(session, asset_id=asset_id, media_id=second.id)
        await session.commit()

    after = (await client.get("/api/assets/browse")).json()["items"]
    item = next(item for item in after if item["asset_id"] == asset_id)
    assert item["id"] == asset_id
    assert item["media_id"] == second.id
    assert [entry["name"] for entry in item["markers"]] == ["Winner"]


@pytest.mark.asyncio
async def test_asset_browser_similarity_returns_asset_identity(client, db_session):
    async with db_session() as session:
        reference = await create_media_item(session)
        match = await create_media_item(session)
        miss = await create_media_item(session)
        reference.set_embedding(np.ones(512, dtype=np.float32))
        match.set_embedding(np.ones(512, dtype=np.float32))
        miss.set_embedding(
            np.concatenate(
                [np.ones(256, dtype=np.float32), -np.ones(256, dtype=np.float32)]
            )
        )
        reference_asset = await create_asset_from_media(session, media_id=reference.id)
        match_asset = await create_asset_from_media(session, media_id=match.id)
        await create_asset_from_media(session, media_id=miss.id)
        await session.commit()

    response = await client.get(
        "/api/assets/browse",
        params={
            "similar_to": str(reference.id),
            "similarity_threshold": 0.9,
            "sort_by": "similarity",
        },
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["asset_id"] for item in items} == {
        reference_asset.id,
        match_asset.id,
    }
    assert {item["media_id"] for item in items} == {reference.id, match.id}

@pytest.mark.asyncio
async def test_asset_trash_restore_preserves_revision_and_clears_expiration(
    client, db_session
):
    async with db_session() as session:
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        asset_id = asset.id
        revision_id = asset.current_revision_id
        await session.commit()

    deleted = await client.delete(f"/api/assets/{asset_id}")
    assert deleted.status_code == 200
    assert deleted.json()["asset"]["state"] == "trashed"

    active = await client.get("/api/assets")
    assert asset_id not in {item["asset"]["id"] for item in active.json()["items"]}
    trash = await client.get("/api/assets", params={"state": "trashed"})
    assert asset_id in {item["asset"]["id"] for item in trash.json()["items"]}

    restored = await client.post(f"/api/assets/{asset_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["asset"]["state"] == "active"
    fetched = await client.get(f"/api/assets/{asset_id}")
    assert fetched.json()["revision"]["id"] == revision_id


async def _wait_for_delete(client, operation_id: int):
    for _ in range(100):
        response = await client.get(f"/api/delete-operations/{operation_id}")
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError("delete operation did not finish")


@pytest.mark.asyncio
async def test_permanent_asset_delete_collects_newly_unowned_media(client, db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        asset_id = asset.id
        media_id = media.id
        await session.commit()

    assert (await client.delete(f"/api/assets/{asset_id}")).status_code == 200
    response = await client.delete(f"/api/assets/{asset_id}/permanent")
    assert response.status_code == 202
    operation = await _wait_for_delete(client, response.json()["operation"]["id"])
    assert operation["status"] == "completed"

    async with db_session() as session:
        assert await session.get(Asset, asset_id) is None
        assert await session.get(MediaItem, media_id) is None


@pytest.mark.asyncio
async def test_source_asset_delete_preserves_dependent_snapshot_media(client, db_session):
    async with db_session() as session:
        source_media = await create_media_item(session)
        dependent_media = await create_media_item(session)
        source = await create_asset_from_media(session, media_id=source_media.id)
        dependent = await create_asset_from_media(session, media_id=dependent_media.id)
        document = await create_working_document(
            session, asset_id=dependent.id, editor_type="image"
        )
        snapshot = await create_asset_snapshot(
            session,
            owner_kind="working_document",
            owner_id=document.id,
            media_id=source_media.id,
            source_asset_id=source.id,
            source_revision_id=source.current_revision_id,
            role="layer",
        )
        source_id = source.id
        dependent_id = dependent.id
        source_media_id = source_media.id
        snapshot_id = snapshot.id
        await session.commit()

    await client.delete(f"/api/assets/{source_id}")
    response = await client.delete(f"/api/assets/{source_id}/permanent")
    assert response.status_code == 202
    assert response.json()["status"] == "completed"
    assert response.json()["operation"] is None

    async with db_session() as session:
        assert await session.get(Asset, source_id) is None
        assert await session.get(Asset, dependent_id) is not None
        assert await session.get(MediaItem, source_media_id) is not None
        retained = await session.get(AssetSnapshot, snapshot_id)
        assert retained.media_id == source_media_id
        assert retained.source_asset_id is None
        assert retained.source_revision_id is None

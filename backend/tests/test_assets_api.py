"""Asset-first and contextual-Media API integration tests."""

import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from sqlalchemy import delete, func, insert, select, update

from asset_service import (
    acquire_media_owner,
    commit_revision,
    create_asset_from_media,
    create_asset_snapshot,
    create_working_document,
)
from database import (
    Asset,
    AssetMarker,
    AssetSnapshot,
    AssetTag,
    Chat,
    ChatItem,
    ContainerMember,
    CachedProviderTool,
    DeleteOperation,
    DeleteOperationItem,
    Keyword,
    Marker,
    MediaItem,
    MediaKeyword,
    MediaMarker,
    MediaTag,
    MediaThumbnailCache,
    MediaToolLineage,
    Tag,
)
from container_service import create_container_asset_from_media
from cleanup_service import CleanupService
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_media_compatibility_reads_project_only_canonical_asset_state(
    client, db_session
):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/canonical-projection.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        canonical_marker = Marker(
            name=f"canonical-marker-{media.id}", icon_svg="<svg/>", color="#111111"
        )
        stale_marker = Marker(
            name=f"stale-marker-{media.id}", icon_svg="<svg/>", color="#222222"
        )
        canonical_tag = Tag(tag_text=f"canonical-tag-{media.id}")
        stale_tag = Tag(tag_text=f"stale-tag-{media.id}")
        session.add_all([canonical_marker, stale_marker, canonical_tag, stale_tag])
        await session.flush()
        session.add_all(
            [
                AssetMarker(
                    asset_id=asset.id,
                    marker_id=canonical_marker.id,
                    source="manual",
                ),
                AssetTag(asset_id=asset.id, tag_id=canonical_tag.id),
                MediaMarker(
                    media_id=media.id,
                    marker_id=stale_marker.id,
                    source="manual",
                ),
                MediaTag(media_id=media.id, tag_id=stale_tag.id),
            ]
        )
        deadline = datetime.utcnow() + timedelta(minutes=10)
        asset.expires_at = deadline
        media.auto_delete_at = deadline + timedelta(days=1)
        media_id = media.id
        asset_id = asset.id
        canonical_marker_id = canonical_marker.id
        stale_marker_id = stale_marker.id
        canonical_tag_id = canonical_tag.id
        stale_tag_id = stale_tag.id
        await session.commit()

    detail = await client.get(f"/api/media/{media_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["asset_id"] == asset_id
    assert payload["asset_state"] == "active"
    assert payload["expires_at"] == deadline.isoformat()
    assert {marker["id"] for marker in payload["markers"]} == {canonical_marker_id}
    assert {tag["id"] for tag in payload["tags"]} == {canonical_tag_id}

    canonical_filter = await client.get(
        "/api/media", params={"tag_ids": canonical_tag_id}
    )
    assert media_id in {item["id"] for item in canonical_filter.json()["items"]}
    stale_filter = await client.get("/api/media", params={"tag_ids": stale_tag_id})
    assert media_id not in {item["id"] for item in stale_filter.json()["items"]}
    stale_marker_filter = await client.get(
        "/api/media", params={"marker_ids": stale_marker_id}
    )
    assert media_id not in {item["id"] for item in stale_marker_filter.json()["items"]}


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
    assert asset.id in {item["asset"]["id"] for item in payload["items"]}
    assert asset_media.id in {item["media"]["id"] for item in payload["items"]}
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
        second_media_id = second.id
        await session.commit()

    before = (await client.get("/api/assets/browse")).json()["items"]
    item = next(item for item in before if item["asset_id"] == asset_id)
    assert item["id"] == asset_id
    assert item["media_id"] == first_media_id
    assert [entry["name"] for entry in item["markers"]] == ["Winner"]
    assert item["revision_count"] == 1

    async with db_session() as session:
        await commit_revision(session, asset_id=asset_id, media_id=second_media_id)
        await session.commit()

    after = (await client.get("/api/assets/browse")).json()["items"]
    item = next(item for item in after if item["asset_id"] == asset_id)
    assert item["id"] == asset_id
    assert item["media_id"] == second_media_id
    assert item["revision_count"] == 2
    assert [entry["name"] for entry in item["markers"]] == ["Winner"]

    legacy_items = (await client.get("/api/media")).json()["items"]
    listed_media_ids = {entry["id"] for entry in legacy_items}
    assert second_media_id in listed_media_ids
    assert first_media_id not in listed_media_ids


@pytest.mark.asyncio
async def test_asset_expiration_is_projected_to_browser_surfaces(client, db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        deadline = datetime.utcnow() + timedelta(days=1)
        asset.expires_at = deadline
        asset_id = asset.id
        await session.commit()

    browse = (await client.get("/api/assets/browse")).json()["items"]
    item = next(item for item in browse if item["asset_id"] == asset_id)
    assert item["expires_at"] == deadline.isoformat()

    detail = (await client.get(f"/api/assets/item/{asset_id}/browser")).json()
    assert detail["expires_at"] == deadline.isoformat()


@pytest.mark.asyncio
async def test_asset_marker_clears_asset_and_media_expiration(
    client, db_session
):
    """A kept Asset stays usable by Media-ID consumers after its old deadline."""
    async with db_session() as session:
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        marker = Marker(name="Keep", icon_svg="<svg />", color="#fff")
        session.add(marker)
        await session.flush()
        deadline = datetime.utcnow() - timedelta(minutes=1)
        asset.expires_at = deadline
        media.auto_delete_at = deadline
        asset_id = asset.id
        media_id = media.id
        marker_id = marker.id
        await session.commit()

    response = await client.post(
        f"/api/assets/item/{asset_id}/markers/{marker_id}"
    )
    assert response.status_code == 200, response.text

    async with db_session() as session:
        kept_asset = await session.get(Asset, asset_id)
        kept_media = await session.get(MediaItem, media_id)
        assert kept_asset.expires_at is None
        assert kept_media.auto_delete_at is None

    # Sidebar/tool handoff hydrates exact payloads through this endpoint.
    payload = await client.get(f"/api/media/{media_id}")
    assert payload.status_code == 200, payload.text
    assert payload.json()["auto_delete_at"] is None

    response = await client.delete(
        f"/api/assets/item/{asset_id}/markers/{marker_id}"
    )
    assert response.status_code == 200, response.text

    async with db_session() as session:
        asset_ids, media_ids, _ = await CleanupService().cleanup_expired_images(
            session, {}
        )
        assert asset_ids == []
        assert media_ids == []
        assert (await session.get(Asset, asset_id)).state == "active"


@pytest.mark.asyncio
async def test_readding_existing_asset_marker_still_clears_expiration(
    client, db_session
):
    """Idempotent curation repairs stale deadlines left by older builds."""
    async with db_session() as session:
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        marker = Marker(name="Existing", icon_svg="<svg />", color="#fff")
        session.add(marker)
        await session.flush()
        session.add(
            AssetMarker(asset_id=asset.id, marker_id=marker.id, source="manual")
        )
        deadline = datetime.utcnow() - timedelta(minutes=1)
        asset.expires_at = deadline
        media.auto_delete_at = deadline
        asset_id = asset.id
        media_id = media.id
        marker_id = marker.id
        await session.commit()

    response = await client.post(
        f"/api/assets/item/{asset_id}/markers/{marker_id}"
    )
    assert response.status_code == 200, response.text

    async with db_session() as session:
        assert (await session.get(Asset, asset_id)).expires_at is None
        assert (await session.get(MediaItem, media_id)).auto_delete_at is None


@pytest.mark.asyncio
async def test_revision_history_can_restore_an_old_version_as_a_new_latest_version(
    client, db_session
):
    async with db_session() as session:
        first = await create_media_item(session, file_hash="first-version")
        second = await create_media_item(session, file_hash="second-version")
        asset = await create_asset_from_media(session, media_id=first.id)
        first_revision_id = asset.current_revision_id
        second_revision = await commit_revision(session, asset_id=asset.id, media_id=second.id)
        asset_id = asset.id
        await session.commit()

    history = await client.get(f"/api/assets/{asset_id}/revisions")
    assert history.status_code == 200, history.text
    items = history.json()["items"]
    assert history.json()["current_revision_id"] == second_revision.id
    assert [item["revision_number"] for item in items] == [2, 1]
    assert items[1]["media"]["file_hash"] == "first-version"

    restored = await client.post(
        f"/api/assets/{asset_id}/revisions/{first_revision_id}/restore"
    )
    assert restored.status_code == 200, restored.text
    payload = restored.json()
    assert payload["revision"]["revision_number"] == 3
    assert payload["revision"]["parent_revision_id"] == first_revision_id
    assert payload["revision"]["primary_media_id"] not in {
        first.id,
        second_revision.primary_media_id,
    }
    assert payload["asset"]["file_hash"] == "first-version"
    assert payload["asset"]["revision_count"] == 3


@pytest.mark.asyncio
async def test_contextual_media_search_and_explicit_promotion(client, db_session):
    async with db_session() as session:
        matching = await create_media_item(session, extracted_prompt="a copper lighthouse")
        other = await create_media_item(session, extracted_prompt="a blue bicycle")
        for media in (matching, other):
            await acquire_media_owner(
                session,
                media_id=media.id,
                root_kind="chat",
                root_id="456",
                role="intermediate",
            )
        matching_id = matching.id
        await session.commit()

    search = await client.get(
        "/api/assets/contextual-media", params={"q": "lighthouse"}
    )
    assert search.status_code == 200, search.text
    assert search.json()["count"] == 1
    assert search.json()["groups"][0]["items"][0]["id"] == matching_id

    promoted = await client.post(
        f"/api/assets/contextual-media/{matching_id}/promote"
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["asset"]["media_id"] == matching_id
    after = await client.get(
        "/api/assets/contextual-media", params={"q": "lighthouse"}
    )
    assert after.json()["count"] == 0


@pytest.mark.asyncio
async def test_contextual_media_search_includes_visual_matches(
    client, db_session, monkeypatch
):
    from clip_service import CLIP_EMBEDDING_DIM

    class FakeClipService:
        def encode_text(self, _text):
            embedding = np.zeros(CLIP_EMBEDDING_DIM, dtype=np.float32)
            embedding[0] = 1.0
            return embedding

        def compute_similarity(self, first, second):
            return float(np.dot(first, second))

    monkeypatch.setattr(
        "clip_service.get_clip_service", lambda: FakeClipService()
    )

    async with db_session() as session:
        raccoon = await create_media_item(session)
        raccoon_embedding = np.zeros(CLIP_EMBEDDING_DIM, dtype=np.float32)
        raccoon_embedding[0] = 1.0
        raccoon.set_embedding(raccoon_embedding)
        other = await create_media_item(session)
        other_embedding = np.zeros(CLIP_EMBEDDING_DIM, dtype=np.float32)
        other_embedding[1] = 1.0
        other.set_embedding(other_embedding)
        for media in (raccoon, other):
            await acquire_media_owner(
                session,
                media_id=media.id,
                root_kind="chat",
                root_id="457",
                role="intermediate",
            )
        raccoon_id = raccoon.id
        await session.commit()

    search = await client.get(
        "/api/assets/contextual-media", params={"q": "raccoon"}
    )
    assert search.status_code == 200, search.text
    assert search.json()["count"] == 1
    assert search.json()["groups"][0]["items"][0]["id"] == raccoon_id


@pytest.mark.asyncio
async def test_container_membership_and_promotion_are_asset_first(client, db_session):
    async with db_session() as session:
        linked_media = await create_media_item(session)
        linked = await create_asset_from_media(session, media_id=linked_media.id)
        linked_id = linked.id
        for index in range(2):
            container_media = await create_media_item(
                session, file_format="stimmaset.json"
            )
            await create_container_asset_from_media(
                session,
                media_id=container_media.id,
                container_type="set",
                title=f"Collection {index + 1}",
                members=[{"linked_asset_id": linked_id}],
            )
        grid_media = await create_media_item(session, file_format="stimmagrid.json")
        cell = await create_media_item(session)
        grid = await create_container_asset_from_media(
            session,
            media_id=grid_media.id,
            container_type="grid",
            members=[{"embedded_media_id": cell.id, "row_index": 0, "column_index": 0}],
        )
        grid_id = grid.id
        await session.commit()

    containers = await client.get(f"/api/assets/item/{linked_id}/containers")
    assert containers.status_code == 200, containers.text
    assert {item["title"] for item in containers.json()} == {
        "Collection 1",
        "Collection 2",
    }

    promoted = await client.post(
        f"/api/assets/item/{grid_id}/container-members/promote"
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["count"] == 1
    summary = await client.get(
        f"/api/assets/item/{grid_id}/container-members/summary"
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["to_create"] == 0
    assert summary.json()["already_saved"] == 1
    async with db_session() as session:
        assert (await session.get(Asset, grid_id)).state == "active"

    exploded = await client.post(f"/api/assets/item/{grid_id}/explode")
    assert exploded.status_code == 200, exploded.text
    assert exploded.json()["created_count"] == 0
    assert exploded.json()["reused_count"] == 1
    assert exploded.json()["moved_to_trash"] is True
    async with db_session() as session:
        assert (await session.get(Asset, grid_id)).state == "trashed"
    restored = await client.post(f"/api/assets/{grid_id}/restore")
    assert restored.status_code == 200, restored.text


@pytest.mark.asyncio
async def test_deletion_preview_distinguishes_collectible_and_retained_media(
    client, db_session
):
    async with db_session() as session:
        first = await create_media_item(session)
        second = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=first.id)
        await commit_revision(session, asset_id=asset.id, media_id=second.id)
        await acquire_media_owner(
            session,
            media_id=first.id,
            root_kind="chat",
            root_id="retained-preview",
            role="intermediate",
        )
        asset_id = asset.id
        first_id = first.id
        second_id = second.id
        await session.commit()

    assert (await client.delete(f"/api/assets/{asset_id}")).status_code == 200
    preview = await client.get(f"/api/assets/{asset_id}/deletion-preview")
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["revision_count"] == 2
    assert payload["candidate_media_ids"] == [first_id, second_id]
    assert payload["retained_media_ids"] == [first_id]
    assert payload["collectible_media_ids"] == [second_id]
    assert payload["retained_by_kind"] == {"chat": 1}
    assert (await client.post(f"/api/assets/{asset_id}/restore")).status_code == 200

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
    ids_response = await client.get(
        "/api/assets/browse/ids",
        params={
            "similar_to": str(reference.id),
            "similarity_threshold": 0.9,
            "sort_by": "similarity",
        },
    )
    assert ids_response.status_code == 200, ids_response.text
    assert set(ids_response.json()["ids"]) == {reference_asset.id, match_asset.id}

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
    manifest = await client.get("/api/assets/trash-deletion-manifest")
    entry = next(
        item for item in manifest.json()["items"] if item["asset_id"] == asset_id
    )
    assert entry["media_ids"] == [media.id]

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
    assert response.json()["identity_status"] == "pending"
    assert response.json()["privacy_status"] == "pending"
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
    assert response.json()["status"] == "accepted"
    assert response.json()["identity_status"] == "pending"
    assert response.json()["privacy_status"] == "pending"
    operation = await _wait_for_delete(client, response.json()["operation"]["id"])
    assert operation["status"] == "completed"

    async with db_session() as session:
        assert await session.get(Asset, source_id) is None
        assert await session.get(Asset, dependent_id) is not None
        assert await session.get(MediaItem, source_media_id) is not None
        retained = await session.get(AssetSnapshot, snapshot_id)
        assert retained.media_id == source_media_id
        assert retained.source_asset_id is None
        assert retained.source_revision_id is None


@pytest.mark.asyncio
async def test_failed_asset_delete_can_retry_after_legacy_blocker_is_removed(
    client, db_session, tmp_path
):
    async with db_session() as session:
        source_media = await create_media_item(
            session, file_path=tmp_path / "asset-source.png"
        )
        source = await create_asset_from_media(session, media_id=source_media.id)
        edited_path = tmp_path / "legacy-edit.png"
        edited = await create_media_item(session, file_path=edited_path)
        edited.has_editor_sidecar = True
        sidecar = tmp_path / "legacy-edit.png.stimmaedit.json"
        sidecar.write_text(
            json.dumps({"source_media_id": source_media.id, "project": {}}),
            encoding="utf-8",
        )
        await session.commit()
        source_id = source.id
        source_media_id = source_media.id

    await client.delete(f"/api/assets/{source_id}")
    response = await client.delete(f"/api/assets/{source_id}/permanent")
    operation_id = response.json()["operation"]["id"]
    failed = await _wait_for_delete(client, operation_id)
    assert failed["status"] == "failed"
    async with db_session() as session:
        assert await session.get(Asset, source_id) is None
        surviving = await session.get(MediaItem, source_media_id)
        assert surviving.deleted_at is None
        assert surviving.deletion_pending_at is not None

    sidecar.unlink()
    retry = await client.post(f"/api/delete-operations/{operation_id}/retry")
    assert retry.status_code == 202
    completed = await _wait_for_delete(client, operation_id)
    assert completed["status"] == "completed"
    async with db_session() as session:
        assert await session.get(MediaItem, source_media_id) is None


@pytest.mark.asyncio
async def test_permanent_asset_delete_scrubs_all_weak_identity_references(
    client, db_session
):
    async with db_session() as session:
        source_media = await create_media_item(session)
        dependent_media = await create_media_item(session)
        source = await create_asset_from_media(session, media_id=source_media.id)
        dependent = await create_asset_from_media(
            session,
            media_id=dependent_media.id,
            origin_type="editor_save_as_new",
            origin_id=str(source.id),
        )
        exploded_media = await create_media_item(session)
        exploded = await create_asset_from_media(
            session,
            media_id=exploded_media.id,
            origin_type="container_explode",
            origin_id=str(source.id),
        )
        member = ContainerMember(
            container_revision_id=dependent.current_revision_id,
            linked_asset_id=source.id,
            missing_linked_asset=False,
            member_order=0,
            member_metadata=json.dumps(
                {"asset_id": source.id, "private_label": "source name"}
            ),
            deleted_at=datetime.utcnow(),
        )
        chat = Chat(name="Weak reference scrub")
        session.add_all([member, chat])
        await session.flush()
        chat_item = ChatItem(
            chat_id=chat.id,
            item_type="tool_result",
            asset_id=source.id,
            asset_ids=json.dumps([source.id, dependent.id]),
            item_metadata=json.dumps({"asset_id": source.id}),
            tool_args=json.dumps({"input": {"asset_id": source.id}}),
            tool_result=json.dumps({"asset_ids": [source.id]}),
            grid_layout=json.dumps({"cells": [{"asset_id": source.id}]}),
        )
        session.add(chat_item)
        await session.commit()
        source_id = source.id
        dependent_id = dependent.id
        exploded_id = exploded.id
        member_id = member.id
        chat_item_id = chat_item.id

    await client.delete(f"/api/assets/{source_id}")
    response = await client.delete(f"/api/assets/{source_id}/permanent")
    assert response.status_code == 202
    operation = await _wait_for_delete(client, response.json()["operation"]["id"])
    assert operation["status"] == "completed"

    async with db_session() as session:
        dependent = await session.get(Asset, dependent_id)
        assert dependent.origin_id is None
        assert (await session.get(Asset, exploded_id)).origin_id is None
        member = await session.get(ContainerMember, member_id)
        assert member.deleted_at is not None
        assert member.linked_asset_id is None
        assert member.missing_linked_asset is True
        assert member.member_metadata is None

        item = await session.get(ChatItem, chat_item_id)
        assert item.asset_id is None
        assert json.loads(item.asset_ids) == [dependent_id]
        for field in (
            item.item_metadata,
            item.tool_args,
            item.tool_result,
            item.grid_layout,
        ):
            assert str(source_id) not in field
            assert json.loads(field)


@pytest.mark.asyncio
async def test_bare_media_cannot_enter_user_trash_with_only_stale_container_history(
    client, db_session
):
    async with db_session() as session:
        target = await create_media_item(session)
        container_media = await create_media_item(session)
        container = await create_asset_from_media(
            session, media_id=container_media.id
        )
        member = ContainerMember(
            container_revision_id=container.current_revision_id,
            embedded_media_id=target.id,
            missing_linked_asset=False,
            member_order=0,
            deleted_at=datetime.utcnow(),
        )
        session.add(member)
        await session.commit()
        target_id = target.id
        member_id = member.id

    response = await client.delete(f"/api/media/{target_id}")
    assert response.status_code == 409
    permanent = await client.delete(f"/api/trash/{target_id}")
    assert permanent.status_code == 409
    async with db_session() as session:
        assert await session.get(MediaItem, target_id) is not None
        assert await session.get(ContainerMember, member_id) is not None


@pytest.mark.asyncio
async def test_asset_organization_reads_and_expiration_are_asset_scoped(client, db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        asset.expires_at = datetime.utcnow() + timedelta(days=1)
        tag = Tag(tag_text="asset-only")
        session.add(tag)
        await session.flush()
        session.add(AssetTag(asset_id=asset.id, tag_id=tag.id))
        asset_id = asset.id
        await session.commit()

    project = await client.post("/api/projects", json={"name": "Asset Project"})
    project_id = project.json()["id"]
    assert (
        await client.post(
            f"/api/assets/batch/projects/{project_id}",
            json={"asset_ids": [asset_id]},
        )
    ).status_code == 200

    board = await client.post("/api/boards", json={"name": "Asset Board"})
    board_id = board.json()["id"]
    assert (
        await client.post(
            f"/api/boards/{board_id}/items",
            json={"asset_ids": [asset_id]},
        )
    ).status_code == 200

    projects = await client.get(f"/api/assets/item/{asset_id}/projects")
    boards = await client.get(f"/api/assets/item/{asset_id}/boards")
    assert [entry["id"] for entry in projects.json()] == [project_id]
    assert [entry["id"] for entry in boards.json()] == [board_id]

    tags = await client.get("/api/assets/tags", params={"with_counts": True})
    counted = next(entry for entry in tags.json() if entry["id"] == tag.id)
    assert counted["usage_count"] == 1

    cleared = await client.delete(f"/api/assets/item/{asset_id}/expiration")
    assert cleared.status_code == 200
    async with db_session() as session:
        assert (await session.get(Asset, asset_id)).expires_at is None


@pytest.mark.asyncio
async def test_asset_tag_counts_only_include_live_assets(client, db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/live-tag-count.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        tag = Tag(tag_text="live-count")
        session.add(tag)
        await session.flush()
        session.add(AssetTag(asset_id=asset.id, tag_id=tag.id))
        asset_id = asset.id
        tag_id = tag.id
        await session.commit()

    tags = await client.get("/api/assets/tags", params={"with_counts": True})
    counted = next(entry for entry in tags.json() if entry["id"] == tag_id)
    assert counted["usage_count"] == 1

    trashed = await client.post(
        "/api/assets/batch/trash", json={"asset_ids": [asset_id]}
    )
    assert trashed.status_code == 200

    tags = await client.get("/api/assets/tags", params={"with_counts": True})
    counted = next(entry for entry in tags.json() if entry["id"] == tag_id)
    assert counted["usage_count"] == 0


@pytest.mark.asyncio
async def test_asset_facets_ignore_contextual_and_old_revision_media(client, db_session):
    before = (await client.get("/api/assets/filter-counts")).json()
    async with db_session() as session:
        old_media = await create_media_item(session, file_path="/tmp/old.png")
        current_media = await create_media_item(session, file_path="/tmp/current.png")
        contextual = await create_media_item(session, file_path="/tmp/intermediate.png")
        asset = await create_asset_from_media(session, media_id=old_media.id)
        await commit_revision(session, asset_id=asset.id, media_id=current_media.id)
        await acquire_media_owner(
            session,
            media_id=contextual.id,
            root_kind="chat",
            root_id="facet-test",
            role="intermediate",
        )
        old_keyword = Keyword(keyword_text="old-revision-only")
        current_keyword = Keyword(keyword_text="current-only")
        contextual_keyword = Keyword(keyword_text="intermediate-only")
        tag = Tag(tag_text="winner")
        session.add_all([old_keyword, current_keyword, contextual_keyword, tag])
        await session.flush()
        session.add_all([
            MediaKeyword(media_id=old_media.id, keyword_id=old_keyword.id),
            MediaKeyword(media_id=current_media.id, keyword_id=current_keyword.id),
            MediaKeyword(media_id=contextual.id, keyword_id=contextual_keyword.id),
            AssetTag(asset_id=asset.id, tag_id=tag.id),
        ])
        await session.commit()

    counts = await client.get("/api/assets/filter-counts")
    assert counts.status_code == 200, counts.text
    payload = counts.json()
    assert payload["media_type"]["images"] == before["media_type"]["images"] + 1
    assert payload["keywords"]["current-only"] == 1
    assert "old-revision-only" not in payload["keywords"]
    assert "intermediate-only" not in payload["keywords"]
    assert {entry["tag"]: entry["usage_count"] for entry in payload["tags"]}["winner"] == 1

    keywords = await client.get("/api/assets/keywords/top")
    assert keywords.status_code == 200, keywords.text
    keyword_counts = {
        entry["keyword"]: entry["count"] for entry in keywords.json()["keywords"]
    }
    assert keyword_counts["current-only"] == 1
    assert "old-revision-only" not in keyword_counts
    assert "intermediate-only" not in keyword_counts


@pytest.mark.asyncio
async def test_asset_tool_facets_resolve_builtins_history_and_legacy_aliases(
    client, db_session
):
    canonical_id = "comfyui:facet-alias-proof"
    legacy_id = "comfyui:text-to-image:facet-alias-proof"
    editor_id = "builtin:stimma:image-editor"

    async with db_session() as session:
        current_media = await create_media_item(
            session, file_path="/tmp/tool-facet-current.png"
        )
        legacy_media = await create_media_item(
            session, file_path="/tmp/tool-facet-legacy.png"
        )
        editor_media = await create_media_item(
            session, file_path="/tmp/tool-facet-editor.png"
        )
        current_asset = await create_asset_from_media(
            session, media_id=current_media.id
        )
        legacy_asset = await create_asset_from_media(
            session, media_id=legacy_media.id
        )
        await create_asset_from_media(session, media_id=editor_media.id)
        session.add_all([
            MediaToolLineage(
                media_id=current_media.id,
                full_tool_id=canonical_id,
            ),
            MediaToolLineage(
                media_id=legacy_media.id,
                full_tool_id=legacy_id,
            ),
            MediaToolLineage(
                media_id=editor_media.id,
                full_tool_id=editor_id,
            ),
            CachedProviderTool(
                full_tool_id=canonical_id,
                provider_id="comfyui",
                provider_name="ComfyUI",
                tool_id="facet-alias-proof",
                name="Facet Alias Proof",
                deleted_at=datetime.utcnow(),
            ),
        ])
        await session.commit()

    payload = (await client.get("/api/assets/filter-counts")).json()
    alias_facet = next(
        tool for tool in payload["tools"] if tool["full_tool_id"] == canonical_id
    )
    assert alias_facet == {
        "full_tool_id": canonical_id,
        "lineage_tool_ids": [canonical_id, legacy_id],
        "name": "Facet Alias Proof",
        "provider_name": "ComfyUI",
        "provider_id": "comfyui",
        "count": 2,
    }
    editor_facet = next(
        tool for tool in payload["tools"] if tool["full_tool_id"] == editor_id
    )
    assert editor_facet["name"] == "Image Editor"
    assert editor_facet["provider_name"] == "Stimma"

    selected = await client.get(
        "/api/assets/browse", params={"tool_ids": canonical_id}
    )
    selected_ids = {item["asset_id"] for item in selected.json()["items"]}
    assert {current_asset.id, legacy_asset.id} <= selected_ids

    excluded = await client.get(
        "/api/assets/browse", params={"excluded_tool_ids": canonical_id}
    )
    excluded_ids = {item["asset_id"] for item in excluded.json()["items"]}
    assert current_asset.id not in excluded_ids
    assert legacy_asset.id not in excluded_ids


@pytest.mark.asyncio
async def test_imported_asset_filter_uses_lineage_provenance_not_storage(client, db_session):
    before = (await client.get("/api/assets/filter-counts")).json()
    async with db_session() as session:
        plain_import = await create_media_item(
            session,
            file_path="/external/library/plain-import.png",
        )
        metadata_import = await create_media_item(
            session,
            file_path="/external/library/metadata-import.png",
            generation_metadata=json.dumps({
                "source": "external",
                "task_type": "imported",
                "prompt": "external metadata",
            }),
        )
        path_backed_generation = await create_media_item(
            session,
            file_path="/external/library/legacy-generation.png",
            generation_metadata=json.dumps({
                "task_type": "text-to-image",
                "tool_id": "test:text-to-image",
                "prompt": "generated outside managed storage",
            }),
            tool_id="test:text-to-image",
        )
        plain_asset = await create_asset_from_media(session, media_id=plain_import.id)
        metadata_asset = await create_asset_from_media(session, media_id=metadata_import.id)
        generated_asset = await create_asset_from_media(
            session,
            media_id=path_backed_generation.id,
        )
        assert path_backed_generation.storage_object_id is None
        await session.commit()

    imported = await client.get("/api/assets/browse", params={"is_imported": "true"})
    assert imported.status_code == 200, imported.text
    imported_ids = {item["asset_id"] for item in imported.json()["items"]}
    assert {plain_asset.id, metadata_asset.id} <= imported_ids
    assert generated_asset.id not in imported_ids

    tool_history = await client.get("/api/assets/browse", params={"is_imported": "false"})
    assert tool_history.status_code == 200, tool_history.text
    tool_history_ids = {item["asset_id"] for item in tool_history.json()["items"]}
    assert generated_asset.id in tool_history_ids
    assert plain_asset.id not in tool_history_ids
    assert metadata_asset.id not in tool_history_ids

    selected_ids = await client.get(
        "/api/assets/browse/ids",
        params={"is_imported": "true"},
    )
    assert selected_ids.status_code == 200, selected_ids.text
    assert {plain_asset.id, metadata_asset.id} <= set(selected_ids.json()["ids"])
    assert generated_asset.id not in selected_ids.json()["ids"]

    counts = (await client.get("/api/assets/filter-counts")).json()
    assert counts["imported"] == before["imported"] + 2
    inverse_counts = (
        await client.get("/api/assets/filter-counts", params={"is_imported": "false"})
    ).json()
    assert inverse_counts["imported"] == before["imported"] + 2


@pytest.mark.asyncio
async def test_expired_asset_is_absent_from_browse_and_facets(client, db_session):
    before = (await client.get("/api/assets/filter-counts")).json()
    async with db_session() as session:
        expired_media = await create_media_item(session, file_path="/tmp/expired.png")
        live_media = await create_media_item(session, file_path="/tmp/live.png")
        expired = await create_asset_from_media(session, media_id=expired_media.id)
        live = await create_asset_from_media(session, media_id=live_media.id)
        expired.expires_at = datetime.utcnow() - timedelta(seconds=1)
        live.expires_at = datetime.utcnow() + timedelta(days=1)
        await session.commit()

    browse = (await client.get("/api/assets/browse")).json()
    visible_ids = [item["asset_id"] for item in browse["items"]]
    assert live.id in visible_ids
    assert expired.id not in visible_ids
    counts = (await client.get("/api/assets/filter-counts")).json()
    assert counts["media_type"]["images"] == before["media_type"]["images"] + 1
    assert counts["expiring"] == before["expiring"] + 1


@pytest.mark.asyncio
async def test_empty_asset_trash_permanently_deletes_all_roots(client, db_session):
    trashed_before = (
        await client.get("/api/assets", params={"state": "trashed"})
    ).json()["total"]

    async with db_session() as session:
        roots = []
        for _ in range(2):
            media = await create_media_item(session)
            roots.append(await create_asset_from_media(session, media_id=media.id))
        asset_ids = [asset.id for asset in roots]
        await session.commit()

    assert (
        await client.post("/api/assets/batch/trash", json={"asset_ids": asset_ids})
    ).status_code == 200
    response = await client.delete("/api/assets")
    assert response.status_code == 202
    assert response.json()["accepted"] == trashed_before + 2
    async with db_session() as session:
        operation_ids = list(
            await session.scalars(
                select(DeleteOperation.id).where(
                    DeleteOperation.asset_id.in_(asset_ids)
                )
            )
        )
    assert len(operation_ids) == 2
    for operation_id in operation_ids:
        result = await _wait_for_delete(client, operation_id)
        assert result["status"] == "completed"

    async with db_session() as session:
        for asset_id in asset_ids:
            assert await session.get(Asset, asset_id) is None


@pytest.mark.asyncio
async def test_batch_permanent_delete_queues_one_operation_per_asset(
    client, db_session
):
    async with db_session() as session:
        roots = []
        for _ in range(3):
            media = await create_media_item(session)
            roots.append(await create_asset_from_media(session, media_id=media.id))
        asset_ids = [asset.id for asset in roots]
        deleted_at = datetime.utcnow()
        for asset in roots:
            asset.state = "trashed"
            asset.deleted_at = deleted_at
        await session.commit()
    manifest = await client.post(
        "/api/assets/batch/deletion-manifest",
        json={"asset_ids": asset_ids},
    )
    assert manifest.status_code == 200
    assert [item["asset_id"] for item in manifest.json()["items"]] == asset_ids
    assert all(item["media_ids"] for item in manifest.json()["items"])
    response = await client.post(
        "/api/assets/batch/permanent", json={"asset_ids": asset_ids}
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["accepted"] == 3
    assert payload["asset_ids"] == asset_ids

    async with db_session() as session:
        operation_ids = list(
            await session.scalars(
                select(DeleteOperation.id)
                .where(DeleteOperation.asset_id.in_(asset_ids))
                .order_by(DeleteOperation.id)
            )
        )
    assert len(operation_ids) == 3
    for operation_id in operation_ids:
        completed = await _wait_for_delete(client, operation_id)
        assert completed["status"] == "completed"


@pytest.mark.asyncio
async def test_large_asset_batch_prescrubs_and_checkpoints_once(
    client, db_session
):
    from asset_deletion_service import _scrub_chat_asset_references
    from delete_operations import (
        _batch_scrub_references,
        _process_profile,
        _truncate_privacy_wal,
    )

    async with db_session() as session:
        roots = []
        for _ in range(100):
            media = await create_media_item(session)
            roots.append(await create_asset_from_media(session, media_id=media.id))
        asset_ids = [asset.id for asset in roots]
        for asset in roots:
            asset.state = "trashed"
            asset.deleted_at = datetime.utcnow()
        await session.commit()

    with (
        patch(
            "asset_deletion_service._scrub_chat_asset_references",
            wraps=_scrub_chat_asset_references,
        ) as asset_scrub,
        patch(
            "delete_operations.ensure_delete_worker_started",
            new=AsyncMock(),
        ),
    ):
        response = await client.post(
            "/api/assets/batch/permanent",
            json={"asset_ids": asset_ids},
        )
    assert response.status_code == 202
    assert asset_scrub.await_count == 0

    async with db_session() as session:
        operations = list(
            await session.scalars(
                select(DeleteOperation)
                .where(DeleteOperation.asset_id.in_(asset_ids))
                .order_by(DeleteOperation.id)
            )
        )
        operation_ids = [operation.id for operation in operations]
        assert [operation.current_phase for operation in operations] == [
            "identity_queued"
        ] * len(asset_ids)
        asset_states = list(
            await session.scalars(
                select(Asset.state)
                .where(Asset.id.in_(asset_ids))
                .order_by(Asset.id)
            )
        )
        assert asset_states == ["deleting"] * len(asset_ids)

    worker_started = time.monotonic()
    with patch(
        "asset_deletion_service._scrub_chat_asset_references",
        wraps=_scrub_chat_asset_references,
    ) as worker_asset_scrub:
        await _process_profile("default")
    assert worker_asset_scrub.await_count == 1
    async with db_session() as session:
        checkpointing_after_one_pass = await session.scalar(
            select(func.count())
            .select_from(DeleteOperation)
            .where(
                DeleteOperation.id.in_(operation_ids),
                DeleteOperation.status == "checkpointing",
            )
        )
    assert checkpointing_after_one_pass == 25
    async with db_session() as session:
        states = list(
            await session.scalars(
                select(DeleteOperationItem.state).where(
                    DeleteOperationItem.operation_id.in_(operation_ids),
                    DeleteOperationItem.state != "done",
                )
            )
        )
        assert all(state == "media_deleted" for state in states)

    with (
        patch(
            "delete_operations._truncate_privacy_wal",
            wraps=_truncate_privacy_wal,
        ) as checkpoint,
        patch(
            "asset_deletion_service._scrub_chat_asset_references",
            wraps=_scrub_chat_asset_references,
        ) as repeated_asset_scrub,
        patch(
            "delete_operations._batch_scrub_references",
            wraps=_batch_scrub_references,
        ) as worker_scrub,
    ):
        for _ in range(len(asset_ids) * 2 + 5):
            await _process_profile("default")
            async with db_session() as session:
                remaining = await session.scalar(
                    select(DeleteOperation.id)
                    .where(
                        DeleteOperation.id.in_(operation_ids),
                        DeleteOperation.status.not_in(["completed", "failed"]),
                    )
                    .limit(1)
                )
            if remaining is None:
                break

    assert worker_scrub.await_count == 3
    assert repeated_asset_scrub.await_count == 0
    assert checkpoint.await_count == 1
    assert time.monotonic() - worker_started < 10
    async with db_session() as session:
        statuses = list(
            await session.scalars(
                select(DeleteOperation.status).where(
                    DeleteOperation.id.in_(operation_ids)
                )
            )
        )
    assert statuses == ["completed"] * len(asset_ids)


@pytest.mark.asyncio
async def test_empty_trash_durably_enqueues_more_than_10k_assets_promptly(
    client, db_session
):
    asset_count = 10_050
    created_at = datetime.utcnow()
    async with db_session() as session:
        await session.execute(
            insert(Asset),
            [
                {
                    "asset_type": "image",
                    "title": "delete-queue-10k-regression",
                    "state": "trashed",
                    "created_at": created_at,
                    "updated_at": created_at,
                    "deleted_at": created_at,
                }
                for _ in range(asset_count)
            ],
        )
        await session.commit()
        bounds = (
            await session.execute(
                select(func.min(Asset.id), func.max(Asset.id)).where(
                    Asset.title == "delete-queue-10k-regression"
                )
            )
        ).one()

    started = time.monotonic()
    with patch(
        "delete_operations.ensure_delete_worker_started",
        new=AsyncMock(),
    ):
        response = await client.delete("/api/assets")
    elapsed = time.monotonic() - started
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] >= asset_count
    assert elapsed < 5
    active = (await client.get("/api/delete-operations/active")).json()
    assert active["summary"]["total_assets"] >= asset_count
    assert active["summary"]["processed_assets"] == 0

    async with db_session() as session:
        queued = await session.scalar(
            select(func.count())
            .select_from(DeleteOperation)
            .where(
                DeleteOperation.asset_id.between(bounds[0], bounds[1]),
                DeleteOperation.current_phase == "identity_queued",
            )
        )
        deleting = await session.scalar(
            select(func.count())
            .select_from(Asset)
            .where(
                Asset.id.between(bounds[0], bounds[1]),
                Asset.state == "deleting",
            )
        )
        assert queued == asset_count
        assert deleting == asset_count
        await session.execute(
            delete(DeleteOperation).where(
                DeleteOperation.asset_id.between(bounds[0], bounds[1])
            )
        )
        await session.execute(
            delete(Asset).where(Asset.id.between(bounds[0], bounds[1]))
        )
        await session.commit()


@pytest.mark.asyncio
async def test_asset_identity_batches_release_sqlite_for_thumbnail_writers(
    client, db_session
):
    from asset_deletion_service import permanently_delete_asset
    from database_registry import get_database_registry
    from delete_operations import (
        _prepare_queued_asset_references,
        _process_profile,
        _stage_queued_asset_identities,
    )

    async with db_session() as session:
        roots = []
        for _ in range(30):
            media = await create_media_item(session)
            roots.append(await create_asset_from_media(session, media_id=media.id))
        writer_media = await create_media_item(session)
        asset_ids = [asset.id for asset in roots]
        for asset in roots:
            asset.state = "trashed"
            asset.deleted_at = datetime.utcnow()
        writer_media_id = writer_media.id
        await session.commit()

    with patch(
        "delete_operations.ensure_delete_worker_started",
        new=AsyncMock(),
    ):
        response = await client.post(
            "/api/assets/batch/permanent",
            json={"asset_ids": asset_ids},
        )
    assert response.status_code == 202
    db = get_database_registry().get_database("default")
    await _prepare_queued_asset_references(db, "default")

    entered = asyncio.Event()
    release = asyncio.Event()

    async def pause_inside_writer_transaction(*args, **kwargs):
        entered.set()
        await release.wait()
        return await permanently_delete_asset(*args, **kwargs)

    with patch(
        "asset_deletion_service.permanently_delete_asset",
        side_effect=pause_inside_writer_transaction,
    ):
        stage_task = asyncio.create_task(
            _stage_queued_asset_identities(db, "default")
        )
        await asyncio.wait_for(entered.wait(), timeout=2)

        async def write_thumbnail_cache():
            async with db_session() as session:
                session.add(
                    MediaThumbnailCache(
                        media_id=writer_media_id,
                        cache_path="/tmp/concurrent-delete-thumbnail.jpg",
                    )
                )
                await session.commit()

        thumbnail_task = asyncio.create_task(write_thumbnail_cache())
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.wait_for(
            asyncio.gather(stage_task, thumbnail_task),
            timeout=5,
        )

    async with db_session() as session:
        cached = await session.get(
            MediaThumbnailCache,
            (writer_media_id, "/tmp/concurrent-delete-thumbnail.jpg"),
        )
        remaining_identities = await session.scalar(
            select(func.count())
            .select_from(DeleteOperation)
                .where(
                    DeleteOperation.asset_id.in_(asset_ids),
                    DeleteOperation.current_phase == "identity_refs_scrubbed",
                )
        )
        assert cached is not None
        assert remaining_identities == 5

        leased_item = await session.scalar(
            select(DeleteOperationItem)
            .join(
                DeleteOperation,
                DeleteOperation.id == DeleteOperationItem.operation_id,
            )
            .where(
                DeleteOperation.asset_id.in_(asset_ids),
                DeleteOperationItem.state == "media_deleted",
            )
            .limit(1)
        )
        leased_operation_id = leased_item.operation_id
        leased_media_id = leased_item.media_id
        leased_item.state = "unlinking"
        leased_item.lease_expires_at = datetime.utcnow() + timedelta(minutes=1)
        await session.commit()

    await _process_profile("default")
    async with db_session() as session:
        leased_operation = await session.get(
            DeleteOperation, leased_operation_id
        )
        leased_item = await session.get(
            DeleteOperationItem,
            (leased_operation_id, leased_media_id),
        )
        assert leased_operation.status == "running"
        assert leased_item.state == "unlinking"
        await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.operation_id == leased_operation_id,
                DeleteOperationItem.media_id == leased_media_id,
            )
            .values(state="media_deleted", lease_expires_at=None)
        )
        await session.commit()

    for _ in range(100):
        await _process_profile("default")
        async with db_session() as session:
            unfinished = await session.scalar(
                select(DeleteOperation.id)
                .where(
                    DeleteOperation.asset_id.in_(asset_ids),
                    DeleteOperation.status.not_in(("completed", "failed")),
                )
                .limit(1)
            )
        if unfinished is None:
            break
    assert unfinished is None


@pytest.mark.asyncio
async def test_asset_finalize_batch_isolates_one_unlink_failure(
    client, db_session, tmp_path
):
    from delete_operations import _process_profile, retry_delete_operation
    from trash_service import TrashService

    paths = [tmp_path / "batch-ok.png", tmp_path / "batch-fails.png"]
    for path in paths:
        path.write_bytes(b"asset")
    async with db_session() as session:
        roots = []
        for path in paths:
            media = await create_media_item(session, file_path=path)
            roots.append(await create_asset_from_media(session, media_id=media.id))
        asset_ids = [asset.id for asset in roots]
        for asset in roots:
            asset.state = "trashed"
            asset.deleted_at = datetime.utcnow()
        await session.commit()

    with patch(
        "delete_operations.ensure_delete_worker_started",
        new=AsyncMock(),
    ):
        response = await client.post(
            "/api/assets/batch/permanent",
            json={"asset_ids": asset_ids},
        )
    assert response.status_code == 202

    original_delete = TrashService.permanently_delete

    def selective_failure(service, file_path):
        if str(file_path) == str(paths[1]):
            raise PermissionError("denied")
        return original_delete(service, file_path)

    with patch.object(
        TrashService,
        "permanently_delete",
        autospec=True,
        side_effect=selective_failure,
    ):
        await _process_profile("default")

    async with db_session() as session:
        operations = list(
            await session.scalars(
                select(DeleteOperation)
                .where(DeleteOperation.asset_id.in_(asset_ids))
                .order_by(DeleteOperation.asset_id)
            )
        )
        assert [operation.status for operation in operations] == [
            "checkpointing",
            "failed",
        ]
        failed_operation_id = operations[1].id
        await retry_delete_operation(session, failed_operation_id)
    assert not paths[0].exists()
    assert paths[1].exists()

    for _ in range(5):
        await _process_profile("default")
    assert not paths[1].exists()
    async with db_session() as session:
        statuses = list(
            await session.scalars(
                select(DeleteOperation.status)
                .where(DeleteOperation.asset_id.in_(asset_ids))
                .order_by(DeleteOperation.asset_id)
            )
        )
    assert statuses == ["completed", "completed"]

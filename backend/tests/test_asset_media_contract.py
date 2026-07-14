"""Adversarial regression tests for the Asset/Media cutover product contract.

These tests encode the canonical model rather than mirroring the
implementation:

- Asset is the durable, user-visible root; browsers show only the current
  revision of live Assets.
- Bare contextual Media (chat/editor/container-retained) never appears in
  ordinary Asset browsers but stays addressable as a payload.
- Legacy MediaMarker/MediaTag/ProjectMedia/BoardItem rows are provisional
  staging only and must be consumed on promotion.
- Expiration is Asset-level (Asset.expires_at); expired Assets leave the
  browser population.
- Media payloads are collected only when their last strong owner disappears.

Every test seeds its own rows and asserts exact membership of those rows in
responses, so module-shared database state cannot mask a regression.
"""

import asyncio
from datetime import datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from asset_service import commit_revision, create_asset_from_media, trash_asset
from container_service import create_container_asset_from_media
from database import (
    Asset,
    AssetMarker,
    AssetRevision,
    AssetTag,
    Board,
    BoardAssetItem,
    BoardItem,
    BoardSection,
    Marker,
    MediaItem,
    MediaMarker,
    MediaOwner,
    MediaTag,
    Project,
    ProjectAsset,
    ProjectMedia,
    Tag,
)
from tests.helpers.media import create_media_item

pytestmark = pytest.mark.asyncio


async def _listing_ids(client, **params) -> set[int]:
    response = await client.get(
        "/api/media", params={"page_size": 200, **params}
    )
    assert response.status_code == 200
    return {item["media_id"] for item in response.json()["items"]}


async def _listing_id_endpoint_ids(client, **params) -> set[int]:
    response = await client.get("/api/media/ids", params=params)
    assert response.status_code == 200
    return set(response.json()["ids"])


async def _trash_ids(client) -> set[int]:
    response = await client.get("/api/trash", params={"page_size": 200})
    assert response.status_code == 200
    return {item["media_id"] for item in response.json()["items"]}


async def _wait_for_delete(client, operation_id: int):
    for _ in range(100):
        response = await client.get(f"/api/delete-operations/{operation_id}")
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError("delete operation did not finish")


async def _permanently_delete(client, asset_id: int):
    trash = await client.delete(f"/api/assets/{asset_id}")
    assert trash.status_code == 200
    response = await client.delete(f"/api/assets/{asset_id}/permanent")
    assert response.status_code == 202
    payload = response.json()
    if payload.get("operation"):
        operation = await _wait_for_delete(client, payload["operation"]["id"])
        assert operation["status"] == "completed"
    return payload


class TestBrowserProjection:
    """Which payloads may appear in the ordinary /api/media browser listing."""

    async def test_only_current_revision_of_active_asset_is_listed(
        self, client, db_session
    ):
        async with db_session() as session:
            old = await create_media_item(session)
            new = await create_media_item(session)
            asset = await create_asset_from_media(session, media_id=old.id)
            await commit_revision(session, asset_id=asset.id, media_id=new.id)
            await session.commit()
            old_id, new_id, asset_id = old.id, new.id, asset.id

        listed = await _listing_ids(client)
        assert new_id in listed
        assert old_id not in listed  # historical revision payload must not leak

        id_listing = await _listing_id_endpoint_ids(client)
        assert new_id in id_listing
        assert old_id not in id_listing

        # The historical payload is not trash either.
        assert old_id not in await _trash_ids(client)

        # Both payload records stay addressable, and both resolve to the same
        # durable Asset identity.
        for media_id in (old_id, new_id):
            response = await client.get(f"/api/media/{media_id}")
            assert response.status_code == 200
            assert response.json()["asset_id"] == asset_id

    async def test_trashed_asset_leaves_listing_and_enters_trash(
        self, client, db_session
    ):
        async with db_session() as session:
            media = await create_media_item(session)
            asset = await create_asset_from_media(session, media_id=media.id)
            await trash_asset(session, asset_id=asset.id)
            await session.commit()
            media_id, asset_id = media.id, asset.id

        assert media_id not in await _listing_ids(client)
        assert media_id not in await _listing_id_endpoint_ids(client)
        assert media_id in await _trash_ids(client)

        # Restore brings it back to exactly one population.
        response = await client.post(f"/api/assets/{asset_id}/restore")
        assert response.status_code == 200
        assert media_id in await _listing_ids(client)
        assert media_id not in await _trash_ids(client)

    async def test_bare_contextual_media_is_never_listed_but_stays_addressable(
        self, client, db_session
    ):
        async with db_session() as session:
            bare = await create_media_item(session)
            # Retained contextually (e.g. by a chat) — a strong owner, but not
            # an Asset root.
            session.add(
                MediaOwner(
                    media_id=bare.id,
                    root_kind="chat",
                    root_id="contract-test-chat",
                    role="intermediate",
                )
            )
            await session.commit()
            bare_id = bare.id

        assert bare_id not in await _listing_ids(client)
        assert bare_id not in await _listing_id_endpoint_ids(client)
        assert bare_id not in await _trash_ids(client)

        response = await client.get(f"/api/media/{bare_id}")
        assert response.status_code == 200
        assert response.json()["asset_id"] is None


class TestExpirationIsAssetLevel:
    async def test_expiring_filters_and_expired_exclusion(self, client, db_session):
        async with db_session() as session:
            plain_media = await create_media_item(session)
            expiring_media = await create_media_item(session)
            expired_media = await create_media_item(session)
            await create_asset_from_media(session, media_id=plain_media.id)
            expiring = await create_asset_from_media(
                session,
                media_id=expiring_media.id,
                expires_at=datetime.utcnow() + timedelta(hours=6),
            )
            await create_asset_from_media(
                session,
                media_id=expired_media.id,
                expires_at=datetime.utcnow() - timedelta(minutes=1),
            )
            await session.commit()
            plain_id = plain_media.id
            expiring_id = expiring_media.id
            expired_id = expired_media.id
            mine = {plain_id, expiring_id, expired_id}
            assert expiring.expires_at is not None

        default_listing = await _listing_ids(client)
        assert default_listing & mine == {plain_id, expiring_id}

        show_expiring = await _listing_ids(client, show_expiring=True)
        assert show_expiring & mine == {expiring_id}

        exclude_expiring = await _listing_ids(client, exclude_expiring=True)
        assert exclude_expiring & mine == {plain_id}

    async def test_legacy_media_auto_delete_at_does_not_expire_assets(
        self, client, db_session
    ):
        async with db_session() as session:
            media = await create_media_item(session)
            await create_asset_from_media(session, media_id=media.id)
            media.auto_delete_at = datetime.utcnow() - timedelta(days=1)
            await session.commit()
            media_id = media.id

        listing = await _listing_ids(client)
        assert media_id in listing  # inert legacy column must not hide it
        assert media_id not in await _listing_ids(client, show_expiring=True)


class TestPromotionConsumesLegacyStaging:
    async def test_stale_legacy_rows_are_consumed_exactly_once(
        self, client, db_session
    ):
        async with db_session() as session:
            media = await create_media_item(session)
            marker = Marker(
                name="contract-stale-marker",
                icon_svg="<svg/>",
                color="#123456",
            )
            tag = Tag(tag_text="contract-stale-tag")
            project = Project(name="contract-stale-project")
            board = Board(name="contract-stale-board")
            session.add_all([marker, tag, project, board])
            await session.flush()
            section = BoardSection(board_id=board.id, is_default=True)
            session.add(section)
            await session.flush()
            session.add_all(
                [
                    MediaMarker(
                        media_id=media.id, marker_id=marker.id, source="manual"
                    ),
                    MediaTag(media_id=media.id, tag_id=tag.id),
                    ProjectMedia(project_id=project.id, media_id=media.id),
                    BoardItem(board_section_id=section.id, media_id=media.id),
                ]
            )
            await session.commit()
            media_id = media.id
            marker_id, tag_id = marker.id, tag.id
            project_id, section_id = project.id, section.id

        response = await client.post(
            f"/api/assets/contextual-media/{media_id}/promote"
        )
        assert response.status_code == 200
        asset_id = response.json()["asset"]["asset_id"]

        async with db_session() as session:
            # Canonical Asset-level state carries the staged curation…
            assert (
                await session.scalar(
                    select(AssetMarker).where(
                        AssetMarker.asset_id == asset_id,
                        AssetMarker.marker_id == marker_id,
                        AssetMarker.deleted_at.is_(None),
                    )
                )
                is not None
            )
            assert (
                await session.scalar(
                    select(AssetTag).where(
                        AssetTag.asset_id == asset_id,
                        AssetTag.tag_id == tag_id,
                        AssetTag.deleted_at.is_(None),
                    )
                )
                is not None
            )
            assert (
                await session.scalar(
                    select(ProjectAsset).where(
                        ProjectAsset.asset_id == asset_id,
                        ProjectAsset.project_id == project_id,
                        ProjectAsset.deleted_at.is_(None),
                    )
                )
                is not None
            )
            assert (
                await session.scalar(
                    select(BoardAssetItem).where(
                        BoardAssetItem.asset_id == asset_id,
                        BoardAssetItem.board_section_id == section_id,
                        BoardAssetItem.deleted_at.is_(None),
                    )
                )
                is not None
            )
            # …and the legacy staging rows are gone, so later Media-level reads
            # cannot drift from Asset state.
            assert (
                await session.scalar(
                    select(MediaMarker).where(MediaMarker.media_id == media_id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(MediaTag).where(MediaTag.media_id == media_id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(ProjectMedia).where(ProjectMedia.media_id == media_id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(BoardItem).where(BoardItem.media_id == media_id)
                )
                is None
            )

    async def test_project_add_by_media_id_consumes_staged_rows(
        self, client, db_session
    ):
        """The legacy media_id project endpoint must promote AND consume."""
        async with db_session() as session:
            media = await create_media_item(session)
            marker = Marker(
                name="contract-project-promo-marker",
                icon_svg="<svg/>",
                color="#654321",
            )
            project = Project(name="contract-promo-project")
            session.add_all([marker, project])
            await session.flush()
            session.add(
                MediaMarker(media_id=media.id, marker_id=marker.id, source="auto")
            )
            await session.commit()
            media_id, marker_id, project_id = media.id, marker.id, project.id

        response = await client.post(
            f"/api/projects/{project_id}/assets", json={"media_ids": [media_id]}
        )
        assert response.status_code == 200
        assert response.json()["added"] == 1

        async with db_session() as session:
            revision = await session.scalar(
                select(AssetRevision).where(
                    AssetRevision.primary_media_id == media_id
                )
            )
            assert revision is not None
            assert (
                await session.scalar(
                    select(AssetMarker).where(
                        AssetMarker.asset_id == revision.asset_id,
                        AssetMarker.marker_id == marker_id,
                        AssetMarker.deleted_at.is_(None),
                    )
                )
                is not None
            )
            assert (
                await session.scalar(
                    select(MediaMarker).where(MediaMarker.media_id == media_id)
                )
                is None
            )


class TestContainersAndOwnership:
    async def test_linked_member_stays_independent_embedded_member_stays_contextual(
        self, client, db_session
    ):
        async with db_session() as session:
            linked_media = await create_media_item(session)
            embedded_media = await create_media_item(session)
            container_media = await create_media_item(
                session, file_format="stimmaset.json", raw_metadata='{"items": []}'
            )
            linked = await create_asset_from_media(session, media_id=linked_media.id)
            container = await create_container_asset_from_media(
                session,
                media_id=container_media.id,
                container_type="set",
                members=[
                    {"linked_asset_id": linked.id},
                    {"embedded_media_id": embedded_media.id},
                ],
            )
            await session.commit()
            linked_media_id = linked_media.id
            embedded_media_id = embedded_media.id
            container_media_id = container_media.id
            linked_asset_id = linked.id
            container_asset_id = container.id

        listing = await _listing_ids(client)
        assert linked_media_id in listing  # linked member is its own Asset
        assert container_media_id in listing
        assert embedded_media_id not in listing  # exact snapshot stays contextual

        # Deleting the container removes its identity and collects the embedded
        # payload (no other owner), while the linked Asset is untouched.
        await _permanently_delete(client, container_asset_id)

        async with db_session() as session:
            assert await session.get(Asset, container_asset_id) is None
            assert await session.get(MediaItem, embedded_media_id) is None
            assert await session.get(Asset, linked_asset_id) is not None
            assert await session.get(MediaItem, linked_media_id) is not None

        assert linked_media_id in await _listing_ids(client)

    async def test_shared_payload_survives_until_last_owner_disappears(
        self, client, db_session
    ):
        """Matrix rows: permanent deletion with one surviving owner, then after
        the final owner disappears."""
        async with db_session() as session:
            shared = await create_media_item(session)
            first_container_media = await create_media_item(
                session, file_format="stimmaset.json", raw_metadata='{"items": []}'
            )
            second_container_media = await create_media_item(
                session, file_format="stimmaset.json", raw_metadata='{"items": []}'
            )
            first = await create_container_asset_from_media(
                session,
                media_id=first_container_media.id,
                container_type="set",
                members=[{"embedded_media_id": shared.id}],
            )
            second = await create_container_asset_from_media(
                session,
                media_id=second_container_media.id,
                container_type="set",
                members=[{"embedded_media_id": shared.id}],
            )
            await session.commit()
            shared_id = shared.id
            first_id, second_id = first.id, second.id

        payload = await _permanently_delete(client, first_id)
        assert shared_id in payload.get("retained_media_ids", [shared_id])

        async with db_session() as session:
            survivor = await session.get(MediaItem, shared_id)
            assert survivor is not None
            assert survivor.deletion_pending_at is None

        await _permanently_delete(client, second_id)

        async with db_session() as session:
            assert await session.get(MediaItem, shared_id) is None


class TestSimilaritySearchPopulation:
    async def test_similarity_results_are_browser_population_only(
        self, client, db_session
    ):
        from clip_service import CLIP_EMBEDDING_DIM

        vector = np.ones(CLIP_EMBEDDING_DIM, dtype=np.float32)
        vector /= np.linalg.norm(vector)

        async with db_session() as session:
            reference = await create_media_item(session, clip_status="completed")
            active = await create_media_item(session, clip_status="completed")
            trashed = await create_media_item(session, clip_status="completed")
            bare = await create_media_item(session, clip_status="completed")
            historical = await create_media_item(session, clip_status="completed")
            replacement = await create_media_item(session, clip_status="completed")
            for item in (reference, active, trashed, bare, historical, replacement):
                item.set_embedding(vector)
            await create_asset_from_media(session, media_id=reference.id)
            await create_asset_from_media(session, media_id=active.id)
            trashed_asset = await create_asset_from_media(
                session, media_id=trashed.id
            )
            await trash_asset(session, asset_id=trashed_asset.id)
            versioned = await create_asset_from_media(
                session, media_id=historical.id
            )
            await commit_revision(
                session, asset_id=versioned.id, media_id=replacement.id
            )
            await session.commit()
            reference_id = reference.id
            expected_present = {active.id, replacement.id}
            expected_absent = {trashed.id, bare.id, historical.id}

        response = await client.post(
            "/api/search/similar", json={"media_id": reference_id, "top_k": 200}
        )
        assert response.status_code == 200
        result_ids = {item["media_id"] for item in response.json()["items"]}

        assert expected_present <= result_ids
        assert result_ids & expected_absent == set()


class TestOrganizationEventing:
    """Every Asset-level organization write must emit BOTH event flavors.

    Display surfaces patch marker/tag chips in place from ``media_updated``
    (keyed by the current payload's media_id, with the marker/tag data in the
    ``media`` projection) and treat ``assets_updated`` as a refetch hint. A
    write path that emits only ``assets_updated`` leaves the slideshow strip,
    chat cards, job tiles, and the useMarkers store stale until an unrelated
    full refetch — the symptom is marker clicks that "do nothing" or apply
    late on other surfaces.
    """

    async def _seed_asset_and_marker(self, db_session, *, revisions: int = 1):
        from unittest.mock import patch  # noqa: F401  (kept near usage below)

        async with db_session() as session:
            media = await create_media_item(session)
            asset = await create_asset_from_media(session, media_id=media.id)
            payload_id = media.id
            for _ in range(revisions - 1):
                replacement = await create_media_item(session)
                await commit_revision(
                    session, asset_id=asset.id, media_id=replacement.id
                )
                payload_id = replacement.id
            marker = Marker(
                name=f"contract-event-marker-{asset.id}-{revisions}",
                icon_svg="<svg/>",
                color="#0000ff",
            )
            session.add(marker)
            await session.commit()
            return asset.id, payload_id, marker.id

    async def test_asset_marker_add_emits_media_updated_with_marker_data(
        self, client, db_session
    ):
        from unittest.mock import patch

        from tests.helpers.ws import MockWebSocketManager

        asset_id, payload_id, marker_id = await self._seed_asset_and_marker(db_session)

        mock_ws = MockWebSocketManager()
        with patch("routes.assets.ws_manager", mock_ws):
            response = await client.post(
                f"/api/assets/item/{asset_id}/markers/{marker_id}"
            )
            assert response.status_code == 200

        media_updated = mock_ws.get_broadcasts("media_updated")
        assert len(media_updated) == 1
        payload = media_updated[0][1]
        assert payload["media_id"] == payload_id
        assert payload["asset_id"] == asset_id
        assert "markers" in payload["fields"]
        assert [m["id"] for m in payload["media"]["markers"]] == [marker_id]

        assets_updated = mock_ws.get_broadcasts("assets_updated")
        assert len(assets_updated) == 1
        assert assets_updated[0][1]["asset_ids"] == [asset_id]
        assert "markers" in assets_updated[0][1]["fields"]

    async def test_asset_marker_remove_emits_media_updated_with_marker_data(
        self, client, db_session
    ):
        from unittest.mock import patch

        from tests.helpers.ws import MockWebSocketManager

        asset_id, payload_id, marker_id = await self._seed_asset_and_marker(db_session)
        assert (
            await client.post(f"/api/assets/item/{asset_id}/markers/{marker_id}")
        ).status_code == 200

        mock_ws = MockWebSocketManager()
        with patch("routes.assets.ws_manager", mock_ws):
            response = await client.delete(
                f"/api/assets/item/{asset_id}/markers/{marker_id}"
            )
            assert response.status_code == 200

        media_updated = mock_ws.get_broadcasts("media_updated")
        assert len(media_updated) == 1
        payload = media_updated[0][1]
        assert payload["media_id"] == payload_id
        assert payload["media"]["markers"] == []
        assert "markers" in payload["fields"]
        assert len(mock_ws.get_broadcasts("assets_updated")) == 1

    async def test_marker_events_carry_the_current_revision_payload_id(
        self, client, db_session
    ):
        """After an edit creates revision 2, marker events must reference the
        new payload, not the historical one the surfaces no longer show."""
        from unittest.mock import patch

        from tests.helpers.ws import MockWebSocketManager

        asset_id, current_payload_id, marker_id = await self._seed_asset_and_marker(
            db_session, revisions=2
        )

        mock_ws = MockWebSocketManager()
        with patch("routes.assets.ws_manager", mock_ws):
            response = await client.post(
                f"/api/assets/item/{asset_id}/markers/{marker_id}"
            )
            assert response.status_code == 200

        media_updated = mock_ws.get_broadcasts("media_updated")
        assert len(media_updated) == 1
        assert media_updated[0][1]["media_id"] == current_payload_id

    async def test_bulk_asset_markers_emit_per_payload_media_updated(
        self, client, db_session
    ):
        from unittest.mock import patch

        from tests.helpers.ws import MockWebSocketManager

        first_asset, first_payload, marker_id = await self._seed_asset_and_marker(
            db_session
        )
        async with db_session() as session:
            second_media = await create_media_item(session)
            second = await create_asset_from_media(session, media_id=second_media.id)
            await session.commit()
            second_asset, second_payload = second.id, second_media.id

        mock_ws = MockWebSocketManager()
        with patch("routes.assets.ws_manager", mock_ws):
            response = await client.post(
                "/api/assets/batch/markers",
                json={
                    "asset_ids": [first_asset, second_asset],
                    "marker_id": marker_id,
                    "add": True,
                },
            )
            assert response.status_code == 200
            assert response.json()["changed"] == 2

        media_updated = mock_ws.get_broadcasts("media_updated")
        assert {event[1]["media_id"] for event in media_updated} == {
            first_payload,
            second_payload,
        }
        for _, payload in media_updated:
            assert [m["id"] for m in payload["media"]["markers"]] == [marker_id]
        assets_updated = mock_ws.get_broadcasts("assets_updated")
        assert len(assets_updated) == 1
        assert sorted(assets_updated[0][1]["asset_ids"]) == sorted(
            [first_asset, second_asset]
        )

    async def test_asset_tag_add_emits_media_updated_with_tag_data(
        self, client, db_session
    ):
        from unittest.mock import patch

        from tests.helpers.ws import MockWebSocketManager

        async with db_session() as session:
            media = await create_media_item(session)
            asset = await create_asset_from_media(session, media_id=media.id)
            await session.commit()
            asset_id, payload_id = asset.id, media.id

        mock_ws = MockWebSocketManager()
        with patch("routes.assets.ws_manager", mock_ws):
            response = await client.post(
                f"/api/assets/item/{asset_id}/tags",
                json={"tags": ["contract-event-tag"]},
            )
            assert response.status_code == 200

        media_updated = mock_ws.get_broadcasts("media_updated")
        assert len(media_updated) == 1
        payload = media_updated[0][1]
        assert payload["media_id"] == payload_id
        assert "tags" in payload["fields"]
        assert [t["tag"] for t in payload["media"]["tags"]] == ["contract-event-tag"]

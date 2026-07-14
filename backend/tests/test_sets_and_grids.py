"""
Tests for set/grid references: linked membership, independent deletion,
explode, project context, and multiple membership.

Uses generation_client / generation_db_session because set creation writes
managed .stimmaset.json payloads and persists container revisions.
"""

import json
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from unittest.mock import patch

from tests.helpers.media import create_media_item
from tests.helpers.ws import MockWebSocketManager


# ── helpers ──────────────────────────────────────────────────────────────

async def create_set(client, db_session, *, count=3, title="Test Set", project_id=None, member_ids=None):
    """Helper: create images, group them into a set, return (set_id, member_ids)."""
    if member_ids is None:
        async with db_session() as session:
            members = []
            for _ in range(count):
                members.append(await create_media_item(session, file_format="png"))
        member_ids = [m.id for m in members]

    payload = {"media_ids": member_ids, "title": title}
    if project_id is not None:
        payload["project_id"] = project_id

    with patch("routes.media.ws_manager", MockWebSocketManager()):
        resp = await client.post("/api/media/sets", json=payload)
    assert resp.status_code == 200, f"Set creation failed: {resp.text}"
    return resp.json()["media_id"], member_ids


async def get_media_project_ids(db_session, media_id):
    """Return project ids for the Asset retaining this payload."""
    from database import AssetRevision, ProjectAsset
    async with db_session() as session:
        result = await session.execute(
            select(ProjectAsset.project_id)
            .join(AssetRevision, AssetRevision.asset_id == ProjectAsset.asset_id)
            .where(
                AssetRevision.primary_media_id == media_id,
                AssetRevision.deleted_at.is_(None),
                ProjectAsset.deleted_at.is_(None),
            )
        )
        return {row[0] for row in result.all()}


# ── independent membership on set creation ──────────────────────────────

class TestIndependentMembershipOnCreate:
    """Creating a set must not hide, move, or replace member items."""

    async def test_members_remain_independent_assets(
        self, generation_client, generation_db_session
    ):
        """Grouping does not remove member Asset identity."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session
        )

        from database import AssetRevision
        from sqlalchemy import select
        async with generation_db_session() as session:
            for mid in member_ids:
                revision = await session.scalar(
                    select(AssetRevision).where(AssetRevision.primary_media_id == mid)
                )
                assert revision is not None

    async def test_set_file_format(
        self, generation_client, generation_db_session
    ):
        """The set item should be a stimmaset.json."""
        set_id, _ = await create_set(
            generation_client, generation_db_session
        )

        from database import MediaItem
        from sqlalchemy import select
        async with generation_db_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == set_id)
            )
            set_item = result.scalar_one()
            assert set_item.file_format == "stimmaset.json"


# ── browse filtering ────────────────────────────────────────────────────

class TestBrowseFiltering:
    """Adding an Asset to a set does not remove it from browsers."""

    async def test_set_members_remain_visible_in_browse(
        self, generation_client, generation_db_session
    ):
        """Legacy Media browse also reflects the non-owning behavior."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session
        )

        response = await generation_client.get("/api/media")
        assert response.status_code == 200

        returned_ids = {item["id"] for item in response.json()["items"]}

        # Members remain independent roots.
        for mid in member_ids:
            assert mid in returned_ids

    async def test_standalone_items_visible(
        self, generation_client, generation_db_session
    ):
        """Standalone images should appear in browse."""
        async with generation_db_session() as session:
            images = []
            for _ in range(3):
                images.append(
                    await create_media_item(
                        session, file_format="png", materialize_asset=True
                    )
                )

        response = await generation_client.get("/api/media")
        assert response.status_code == 200

        returned_ids = {item["id"] for item in response.json()["items"]}
        for img in images:
            assert img.id in returned_ids, (
                f"Standalone image {img.id} should appear in browse"
            )


# ── multiple membership ─────────────────────────────────────────────────

class TestMultipleMembership:
    """Assets may be linked from any number of sets/grids."""

    async def test_create_set_accepts_items_linked_from_another_set(
        self, generation_client, generation_db_session
    ):
        """Legacy superseded state does not block normalized membership."""
        _, member_ids = await create_set(
            generation_client, generation_db_session
        )

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            response = await generation_client.post("/api/media/sets", json={
                "media_ids": member_ids,
                "title": "Duplicate Set"
            })

        assert response.status_code == 200
        second_set_id = response.json()["media_id"]
        from database import AssetRevision, ContainerMember
        async with generation_db_session() as session:
            second_revision = await session.scalar(
                select(AssetRevision).where(AssetRevision.primary_media_id == second_set_id)
            )
            members = list(await session.scalars(
                select(ContainerMember).where(
                    ContainerMember.container_revision_id == second_revision.id
                )
            ))
            assert len(members) == len(member_ids)
            assert all(member.linked_asset_id is not None for member in members)

    async def test_create_set_accepts_mix_of_existing_and_new_members(
        self, generation_client, generation_db_session
    ):
        """Grouping promotes a bare selected item and links all members."""
        _, member_ids = await create_set(
            generation_client, generation_db_session
        )

        async with generation_db_session() as session:
            free_item = await create_media_item(session, file_format="png")

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            response = await generation_client.post("/api/media/sets", json={
                "media_ids": [free_item.id, member_ids[0]],
                "title": "Mixed Set"
            })

        assert response.status_code == 200

    async def test_asset_request_links_exact_selected_assets(
        self, generation_client, generation_db_session
    ):
        from asset_service import create_asset_from_media
        from database import AssetRevision, ContainerMember, MediaItem

        async with generation_db_session() as session:
            media = [
                await create_media_item(session, file_format="png") for _ in range(2)
            ]
            assets = [
                await create_asset_from_media(session, media_id=item.id) for item in media
            ]
            await session.commit()

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            response = await generation_client.post("/api/media/sets", json={
                "asset_ids": [asset.id for asset in assets],
                "title": "Asset-linked Set",
            })

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["asset_id"] not in {asset.id for asset in assets}
        async with generation_db_session() as session:
            revision = await session.scalar(
                select(AssetRevision).where(
                    AssetRevision.asset_id == payload["asset_id"]
                )
            )
            linked_ids = list(await session.scalars(
                select(ContainerMember.linked_asset_id)
                .where(ContainerMember.container_revision_id == revision.id)
                .order_by(ContainerMember.member_order)
            ))
            assert linked_ids == [asset.id for asset in assets]
            members = list(await session.scalars(
                select(MediaItem).where(MediaItem.id.in_([item.id for item in media]))
            ))
            assert len(members) == len(media)

    async def test_linked_member_content_follows_current_asset_revision(
        self, generation_client, generation_db_session
    ):
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, count=1
        )
        from asset_service import commit_revision
        from database import AssetRevision
        async with generation_db_session() as session:
            original_revision = await session.scalar(
                select(AssetRevision).where(
                    AssetRevision.primary_media_id == member_ids[0]
                )
            )
            replacement = await create_media_item(session, file_format="png")
            replacement_id = replacement.id
            asset_id = original_revision.asset_id
            new_revision = await commit_revision(
                session, asset_id=asset_id, media_id=replacement_id
            )
            await session.commit()

        response = await generation_client.get(f"/api/media/{set_id}/content")
        assert response.status_code == 200, response.text
        resolved = response.json()["items"][0]["resolved"]
        assert resolved["asset_id"] == asset_id
        assert resolved["media_id"] == replacement_id
        assert resolved["revision_id"] == new_revision.id


# ── independent Asset deletion ─────────────────────────────────────────

class TestIndependentAssetDeletion:
    """Trashing a container never trashes linked member Assets."""

    async def test_trash_set_preserves_members(
        self, generation_client, generation_db_session
    ):
        """The set does not own linked members."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, title="Set To Delete"
        )

        # Trash the set
        with patch("routes.trash.ws_manager", MockWebSocketManager()):
            resp = await generation_client.delete(f"/api/media/{set_id}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["deleted_count"] == 1

        # Verify members remain active
        from database import MediaItem
        from sqlalchemy import select
        async with generation_db_session() as session:
            for mid in member_ids:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == mid)
                )
                item = result.scalar_one()
                assert item.deleted_at is None, (
                    f"Member {mid} should survive set deletion"
                )

    async def test_trash_regular_image_does_not_cascade(
        self, generation_client, generation_db_session
    ):
        """Trashing a regular image should NOT cascade-delete anything."""
        async with generation_db_session() as session:
            image = await create_media_item(session, file_format="png")
            from asset_service import create_asset_from_media

            await create_asset_from_media(session, media_id=image.id)
            await session.commit()

        with patch("routes.trash.ws_manager", MockWebSocketManager()):
            resp = await generation_client.delete(f"/api/media/{image.id}")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 1


# ── explode ─────────────────────────────────────────────────────────────

class TestExplodeSetOrGrid:
    """Exploding frees members and moves the container to Trash."""

    async def test_explode_frees_members(
        self, generation_client, generation_db_session
    ):
        """Exploding preserves members and trashes only the container."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, title="Set To Explode"
        )

        # Explode the set
        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post(f"/api/media/{set_id}/explode")
        assert resp.status_code == 200
        assert resp.json()["exploded_count"] == 3

        # Verify members remain independent Assets.
        from database import AssetRevision, MediaItem
        from sqlalchemy import select
        async with generation_db_session() as session:
            for mid in member_ids:
                revision = await session.scalar(
                    select(AssetRevision).where(AssetRevision.primary_media_id == mid)
                )
                assert revision is not None

            # The container revision retains its Media while the Asset is in Trash.
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == set_id)
            )
            set_media = result.scalar_one()
            assert set_media.deleted_at is None

    async def test_exploded_members_appear_in_browse(
        self, generation_client, generation_db_session
    ):
        """After exploding, freed members should appear in browse."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, count=2,
            title="Set To Explode 2",
        )

        # Members are visible before explode because the container only links them.
        resp = await generation_client.get("/api/media")
        returned_ids = {item["id"] for item in resp.json()["items"]}
        for mid in member_ids:
            assert mid in returned_ids

        # Explode
        with patch("routes.media.ws_manager", MockWebSocketManager()):
            await generation_client.post(f"/api/media/{set_id}/explode")

        # Now members should appear
        resp = await generation_client.get("/api/media")
        returned_ids = {item["id"] for item in resp.json()["items"]}
        for mid in member_ids:
            assert mid in returned_ids, (
                f"Freed member {mid} should appear in browse after explode"
            )

    async def test_explode_rejects_non_set(
        self, generation_client, generation_db_session
    ):
        """Exploding a regular image should fail."""
        async with generation_db_session() as session:
            image = await create_media_item(session, file_format="png")

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post(f"/api/media/{image.id}/explode")
        assert resp.status_code == 409
        assert "container asset" in resp.json()["detail"].lower()

    async def test_explode_then_create_new_set(
        self, generation_client, generation_db_session
    ):
        """After exploding, freed items can be added to a new set."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, count=2,
            title="Original Set",
        )

        # Explode
        with patch("routes.media.ws_manager", MockWebSocketManager()):
            await generation_client.post(f"/api/media/{set_id}/explode")

        # Now create a new set from the same items — should succeed
        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post("/api/media/sets", json={
                "media_ids": member_ids,
                "title": "Rebuilt Set"
            })
        assert resp.status_code == 200, (
            "Should be able to re-group freed items into a new set"
        )


# ── project context ─────────────────────────────────────────────────────

class TestSetProjectContext:
    """Sets created in a project land in it without owning member placement."""

    async def _create_project(self, client, name):
        resp = await client.post("/api/projects", json={"name": name})
        assert resp.status_code == 200
        return resp.json()["id"]

    async def test_create_set_in_project_context_attaches_set(
        self, generation_client, generation_db_session
    ):
        """Explicit project_id on set creation attaches the set to that project."""
        project_id = await self._create_project(generation_client, "Set Context")

        set_id, member_ids = await create_set(
            generation_client, generation_db_session,
            title="Project Set", project_id=project_id,
        )

        assert project_id in await get_media_project_ids(generation_db_session, set_id)

        # The set shows up when browsing the project; superseded members don't
        resp = await generation_client.get(f"/api/media?project_id={project_id}")
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert set_id in returned_ids
        for mid in member_ids:
            assert mid not in returned_ids

    async def test_create_set_inherits_member_projects(
        self, generation_client, generation_db_session
    ):
        """Without explicit context, the set inherits its members' projects."""
        project_id = await self._create_project(generation_client, "Inherited")

        async with generation_db_session() as session:
            members = [
                await create_media_item(session, file_format="png") for _ in range(2)
            ]
        member_ids = [m.id for m in members]
        resp = await generation_client.post(
            f"/api/projects/{project_id}/assets", json={"media_ids": member_ids}
        )
        assert resp.status_code == 200

        set_id, _ = await create_set(
            generation_client, generation_db_session,
            title="Inherited Set", member_ids=member_ids,
        )

        assert project_id in await get_media_project_ids(generation_db_session, set_id)

    async def test_create_set_with_unknown_project_404s(
        self, generation_client, generation_db_session
    ):
        async with generation_db_session() as session:
            members = [
                await create_media_item(session, file_format="png") for _ in range(2)
            ]

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post("/api/media/sets", json={
                "media_ids": [m.id for m in members],
                "title": "Orphan Set",
                "project_id": 999999,
            })
        assert resp.status_code == 404

    async def test_explode_does_not_move_project_membership_to_members(
        self, generation_client, generation_db_session
    ):
        """Exploding does not infer project placement for independent members."""
        project_id = await self._create_project(generation_client, "Explode Context")

        set_id, member_ids = await create_set(
            generation_client, generation_db_session,
            title="Set To Explode In Project", project_id=project_id,
        )

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post(f"/api/media/{set_id}/explode")
        assert resp.status_code == 200

        for mid in member_ids:
            assert project_id not in await get_media_project_ids(
                generation_db_session, mid
            )

        # Trash preserves the container's own project placement for restore.
        assert await get_media_project_ids(generation_db_session, set_id) == {
            project_id
        }

        # Trashing the only project member leaves the project view empty.
        resp = await generation_client.get(f"/api/media?project_id={project_id}")
        returned_ids = {item["id"] for item in resp.json()["items"]}
        for mid in member_ids:
            assert mid not in returned_ids

    async def test_explode_outside_project_attaches_nothing(
        self, generation_client, generation_db_session
    ):
        """Exploding a project-less set leaves members in no project."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, title="Free Set",
        )

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post(f"/api/media/{set_id}/explode")
        assert resp.status_code == 200

        for mid in member_ids:
            assert await get_media_project_ids(generation_db_session, mid) == set()

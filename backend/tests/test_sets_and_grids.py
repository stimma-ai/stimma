"""
Tests for set/grid ownership: supersede on create, browse filtering,
cascade delete, explode, and duplicate-membership prevention.

Uses generation_client / generation_db_session because set creation
requires a configured generation folder to write .stimmaset.json files.
"""

import json
import pytest
from httpx import AsyncClient
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
    """Helper: return the set of project ids a media item is attached to."""
    from database import ProjectMedia
    from sqlalchemy import select
    async with db_session() as session:
        result = await session.execute(
            select(ProjectMedia.project_id).where(ProjectMedia.media_id == media_id)
        )
        return {row[0] for row in result.all()}


# ── supersede on set creation ────────────────────────────────────────────

class TestSupersedeOnCreate:
    """Creating a set should supersede all member items."""

    async def test_members_get_superseded_by(
        self, generation_client, generation_db_session
    ):
        """All member items should have superseded_by = set.id."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session
        )

        from database import MediaItem
        from sqlalchemy import select
        async with generation_db_session() as session:
            for mid in member_ids:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == mid)
                )
                item = result.scalar_one()
                assert item.superseded_by == set_id, (
                    f"Member {mid} should be superseded by set {set_id}"
                )

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
    """Superseded items should not appear in browse listings."""

    async def test_superseded_items_hidden_from_browse(
        self, generation_client, generation_db_session
    ):
        """GET /api/media should not return superseded items."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session
        )

        response = await generation_client.get("/api/media")
        assert response.status_code == 200

        returned_ids = {item["id"] for item in response.json()["items"]}

        # Members should NOT be in browse results
        for mid in member_ids:
            assert mid not in returned_ids, (
                f"Superseded member {mid} should not appear in browse"
            )

        # The set itself SHOULD appear (it has metadata_status=completed from ingestion)
        # Note: the set may not appear if metadata_status != 'completed' yet,
        # so we just verify members are hidden.

    async def test_non_superseded_items_visible(
        self, generation_client, generation_db_session
    ):
        """Standalone images (no superseded_by) should appear in browse."""
        async with generation_db_session() as session:
            images = []
            for _ in range(3):
                images.append(await create_media_item(session, file_format="png"))

        response = await generation_client.get("/api/media")
        assert response.status_code == 200

        returned_ids = {item["id"] for item in response.json()["items"]}
        for img in images:
            assert img.id in returned_ids, (
                f"Standalone image {img.id} should appear in browse"
            )


# ── duplicate membership prevention ─────────────────────────────────────

class TestDuplicateMembershipPrevention:
    """Items already owned by a set/grid cannot be added to another."""

    async def test_create_set_rejects_already_owned_items(
        self, generation_client, generation_db_session
    ):
        """Trying to put already-superseded items in a new set should fail."""
        _, member_ids = await create_set(
            generation_client, generation_db_session
        )

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            response = await generation_client.post("/api/media/sets", json={
                "media_ids": member_ids,
                "title": "Duplicate Set"
            })

        assert response.status_code == 400
        assert "already in a set or grid" in response.json()["detail"].lower()

    async def test_create_set_rejects_mix_of_owned_and_free(
        self, generation_client, generation_db_session
    ):
        """A mix of owned and free items should also be rejected."""
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

        assert response.status_code == 400
        assert "already in a set or grid" in response.json()["detail"].lower()


# ── cascade delete ──────────────────────────────────────────────────────

class TestCascadeDelete:
    """Deleting a set/grid should cascade-delete its members."""

    async def test_trash_set_cascades_to_members(
        self, generation_client, generation_db_session
    ):
        """Trashing a set should also trash all its members."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, title="Set To Delete"
        )

        # Trash the set
        with patch("routes.trash.ws_manager", MockWebSocketManager()):
            resp = await generation_client.delete(f"/api/media/{set_id}")
        assert resp.status_code == 200

        data = resp.json()
        # Should report deleting set + 3 members = 4 items
        assert data["deleted_count"] == 4

        # Verify members are trashed
        from database import MediaItem
        from sqlalchemy import select
        async with generation_db_session() as session:
            for mid in member_ids:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == mid)
                )
                item = result.scalar_one()
                assert item.deleted_at is not None, (
                    f"Member {mid} should be trashed after set deletion"
                )

    async def test_trash_regular_image_does_not_cascade(
        self, generation_client, generation_db_session
    ):
        """Trashing a regular image should NOT cascade-delete anything."""
        async with generation_db_session() as session:
            image = await create_media_item(session, file_format="png")

        with patch("routes.trash.ws_manager", MockWebSocketManager()):
            resp = await generation_client.delete(f"/api/media/{image.id}")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 1


# ── explode ─────────────────────────────────────────────────────────────

class TestExplodeSetOrGrid:
    """Exploding a set/grid should free members and delete the container."""

    async def test_explode_frees_members(
        self, generation_client, generation_db_session
    ):
        """Exploding a set should clear superseded_by on members."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, title="Set To Explode"
        )

        # Explode the set
        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post(f"/api/media/{set_id}/explode")
        assert resp.status_code == 200
        assert resp.json()["exploded_count"] == 3

        # Verify members are freed
        from database import MediaItem
        from sqlalchemy import select
        async with generation_db_session() as session:
            for mid in member_ids:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == mid)
                )
                item = result.scalar_one()
                assert item.superseded_by is None, (
                    f"Member {mid} should have superseded_by=None after explode"
                )

            # Verify set is deleted from DB
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == set_id)
            )
            assert result.scalar_one_or_none() is None, "Set should be deleted"

    async def test_exploded_members_appear_in_browse(
        self, generation_client, generation_db_session
    ):
        """After exploding, freed members should appear in browse."""
        set_id, member_ids = await create_set(
            generation_client, generation_db_session, count=2,
            title="Set To Explode 2",
        )

        # Confirm members are hidden from browse
        resp = await generation_client.get("/api/media")
        returned_ids = {item["id"] for item in resp.json()["items"]}
        for mid in member_ids:
            assert mid not in returned_ids

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
        assert resp.status_code == 400
        assert "only explode sets or grids" in resp.json()["detail"].lower()

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
    """Sets created in a project land in it; exploding hands membership back."""

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

    async def test_explode_moves_membership_to_members(
        self, generation_client, generation_db_session
    ):
        """Exploding a set in a project leaves the members in that project."""
        project_id = await self._create_project(generation_client, "Explode Context")

        set_id, member_ids = await create_set(
            generation_client, generation_db_session,
            title="Set To Explode In Project", project_id=project_id,
        )

        with patch("routes.media.ws_manager", MockWebSocketManager()):
            resp = await generation_client.post(f"/api/media/{set_id}/explode")
        assert resp.status_code == 200

        for mid in member_ids:
            assert project_id in await get_media_project_ids(generation_db_session, mid)

        # No orphaned membership rows for the deleted set
        assert await get_media_project_ids(generation_db_session, set_id) == set()

        # Members are visible when browsing the project
        resp = await generation_client.get(f"/api/media?project_id={project_id}")
        returned_ids = {item["id"] for item in resp.json()["items"]}
        for mid in member_ids:
            assert mid in returned_ids

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

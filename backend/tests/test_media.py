"""
Tests for the media API endpoints.

Tests cover:
- Media listing and pagination
- Filtering by markers, tags, boards
- Caption search
- Single media fetch
- Soft delete
- WebSocket events
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.helpers.ws import MockWebSocketManager


class TestMediaListing:
    """Tests for GET /api/media endpoint."""

    async def test_list_empty(self, client: AsyncClient):
        """Test listing media when database is empty."""
        response = await client.get("/api/media")
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_with_media(self, client: AsyncClient, seeded_media):
        """Test listing media with items in database."""
        response = await client.get("/api/media")
        assert response.status_code == 200

        data = response.json()
        # Should have at least the 5 seeded items
        assert len(data["items"]) >= 5
        assert data["total"] >= 5

    async def test_pagination_limit(self, client: AsyncClient, seeded_media):
        """Test pagination with limit parameter."""
        response = await client.get("/api/media", params={"page_size": 2})
        assert response.status_code == 200

        data = response.json()
        # Should return exactly 2 items when limited
        assert len(data["items"]) == 2
        # Total should reflect all items
        assert data["total"] >= 5

    async def test_pagination_offset(self, client: AsyncClient, seeded_media):
        """Test pagination with page parameter."""
        # Get first page
        response1 = await client.get("/api/media", params={"page_size": 2, "page": 1})
        data1 = response1.json()

        # Get second page
        response2 = await client.get("/api/media", params={"page_size": 2, "page": 2})
        data2 = response2.json()

        # Both should have 2 items
        assert len(data1["items"]) == 2
        assert len(data2["items"]) == 2

        # Items should be different
        ids1 = {item["id"] for item in data1["items"]}
        ids2 = {item["id"] for item in data2["items"]}
        assert ids1.isdisjoint(ids2)


class TestMediaSearch:
    """Tests for media search functionality."""

    async def test_caption_search(self, client: AsyncClient, seeded_media_with_captions):
        """Test searching by caption text."""
        response = await client.get("/api/media", params={"caption_query": "red"})
        assert response.status_code == 200

        data = response.json()
        # Should find items with "red" in caption
        assert len(data["items"]) >= 1
        for item in data["items"]:
            assert "red" in item.get("vlm_caption", "").lower()

    async def test_caption_search_no_results(self, client: AsyncClient, seeded_media):
        """Test search with no matching results."""
        response = await client.get("/api/media", params={"caption_query": "xyznonexistent123"})
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []


class TestSingleMedia:
    """Tests for GET /api/media/{id} endpoint."""

    async def test_get_single_media(self, client: AsyncClient, seeded_media):
        """Test fetching a single media item."""
        # First get the list to find an ID
        list_response = await client.get("/api/media")
        items = list_response.json()["items"]
        assert len(items) > 0

        media_id = items[0]["id"]

        # Fetch single item
        response = await client.get(f"/api/media/{media_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == media_id

    async def test_get_nonexistent_media(self, client: AsyncClient):
        """Test fetching a media item that doesn't exist."""
        response = await client.get("/api/media/99999")
        assert response.status_code == 404


class TestAutoDeleteGate:
    """Items past their auto_delete_at deadline must be invisible immediately, before
    the background cleanup worker physically removes them — mirroring the worker's
    keep rules (tags/boards/markers exempt an item from deletion)."""

    async def test_expired_item_hidden_from_list(self, client: AsyncClient, db_session):
        """An item whose auto_delete_at has passed is excluded from GET /api/media."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            item = await create_media_item(session)
            item.auto_delete_at = datetime.utcnow() - timedelta(minutes=1)
            await session.commit()
            expired_id = item.id

        response = await client.get("/api/media")
        assert response.status_code == 200
        ids = {i["id"] for i in response.json()["items"]}
        assert expired_id not in ids

    async def test_expired_item_returns_404_on_single_fetch(self, client: AsyncClient, db_session):
        """A direct GET /api/media/{id} for an expired item must 404, not flash the content."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            item = await create_media_item(session)
            item.auto_delete_at = datetime.utcnow() - timedelta(minutes=1)
            await session.commit()
            expired_id = item.id

        response = await client.get(f"/api/media/{expired_id}")
        assert response.status_code == 404

    async def test_future_expiry_item_still_visible(self, client: AsyncClient, db_session):
        """An item with a future auto_delete_at is still shown (deadline not reached)."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            item = await create_media_item(session)
            item.auto_delete_at = datetime.utcnow() + timedelta(hours=1)
            await session.commit()
            future_id = item.id

        response = await client.get("/api/media")
        ids = {i["id"] for i in response.json()["items"]}
        assert future_id in ids
        assert (await client.get(f"/api/media/{future_id}")).status_code == 200

    async def test_expired_but_tagged_item_preserved(self, client: AsyncClient, db_session):
        """Tagging exempts an item from auto-deletion, so an expired-but-tagged item stays
        visible — the read gate must match the worker's keep rules, not hide it."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            item = await create_media_item(session)
            tagged_id = item.id

        # Tag it through the API, then push its deadline into the past.
        await client.post(f"/api/media/{tagged_id}/tags", json={"tags": ["keepme"]})

        async with db_session() as session:
            from database import MediaItem
            from sqlalchemy import select
            item = (await session.execute(
                select(MediaItem).where(MediaItem.id == tagged_id)
            )).scalar_one()
            item.auto_delete_at = datetime.utcnow() - timedelta(minutes=1)
            await session.commit()

        response = await client.get("/api/media")
        ids = {i["id"] for i in response.json()["items"]}
        assert tagged_id in ids
        assert (await client.get(f"/api/media/{tagged_id}")).status_code == 200


class TestMediaDelete:
    """Tests for DELETE /api/media/{id} endpoint."""

    async def test_soft_delete_media(self, client: AsyncClient, seeded_media):
        """Test soft deleting a media item."""
        # Get initial count
        list_response = await client.get("/api/media")
        initial_count = list_response.json()["total"]
        media_id = list_response.json()["items"][0]["id"]

        # Delete the item
        delete_response = await client.delete(f"/api/media/{media_id}")
        assert delete_response.status_code == 200

        # Verify it's gone from the list
        list_response2 = await client.get("/api/media")
        assert list_response2.json()["total"] == initial_count - 1

        # Verify the item is not in the list
        ids = {item["id"] for item in list_response2.json()["items"]}
        assert media_id not in ids


class TestMediaFilteringByMarkers:
    """Tests for filtering media by markers."""

    async def test_filter_by_marker(self, client: AsyncClient, seeded_media, marker_ids):
        """Test filtering media by marker ID."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Add marker to media
        await client.post(f"/api/media/{media_id}/markers/{marker_id}")

        # Filter by marker
        response = await client.get("/api/media", params={"marker_ids": str(marker_id)})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        item_ids = [item["id"] for item in data["items"]]
        assert media_id in item_ids

    async def test_filter_by_excluded_marker(self, client: AsyncClient, seeded_media, marker_ids):
        """Test filtering media by excluding markers."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Add marker to first media item
        await client.post(f"/api/media/{media_id}/markers/{marker_id}")

        # Get total without filter
        total_response = await client.get("/api/media")
        total_count = total_response.json()["total"]

        # Filter by excluded marker
        response = await client.get("/api/media", params={"excluded_marker_ids": str(marker_id)})
        assert response.status_code == 200

        data = response.json()
        # Should have fewer items
        assert data["total"] < total_count
        # Should not contain the marked item
        item_ids = [item["id"] for item in data["items"]]
        assert media_id not in item_ids

    async def test_filter_by_multiple_markers(self, client: AsyncClient, seeded_media, marker_ids):
        """Test filtering by multiple markers (AND logic - item must have ALL markers)."""
        media_id = seeded_media[0].id

        # Add both markers to the same item
        await client.post(f"/api/media/{media_id}/markers/{marker_ids['favorite']}")
        await client.post(f"/api/media/{media_id}/markers/{marker_ids['library']}")

        # Filter by both markers (AND logic - must have both)
        marker_param = f"{marker_ids['favorite']},{marker_ids['library']}"
        response = await client.get("/api/media", params={"marker_ids": marker_param})
        assert response.status_code == 200

        data = response.json()
        # Should include the item with both markers
        assert data["total"] >= 1
        item_ids = [item["id"] for item in data["items"]]
        assert media_id in item_ids


class TestMediaFilteringByTags:
    """Tests for filtering media by tags."""

    async def test_filter_by_tag(self, client: AsyncClient, seeded_media):
        """Test filtering media by tag ID."""
        media_id = seeded_media[0].id

        # Add tag to media
        await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["test_filter"]}
        )

        # Get tag ID
        tags_response = await client.get("/api/tags")
        tag_id = next(t["id"] for t in tags_response.json() if t["tag"] == "test_filter")

        # Filter by tag
        response = await client.get("/api/media", params={"tag_ids": str(tag_id)})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        item_ids = [item["id"] for item in data["items"]]
        assert media_id in item_ids

    async def test_filter_by_multiple_tags(self, client: AsyncClient, seeded_media):
        """Test filtering by multiple tags (OR logic)."""
        media_id_1 = seeded_media[0].id
        media_id_2 = seeded_media[1].id

        # Add different tags to different items
        await client.post(f"/api/media/{media_id_1}/tags", json={"tags": ["tag_a"]})
        await client.post(f"/api/media/{media_id_2}/tags", json={"tags": ["tag_b"]})

        # Get tag IDs
        tags_response = await client.get("/api/tags")
        tags = tags_response.json()
        tag_a_id = next(t["id"] for t in tags if t["tag"] == "tag_a")
        tag_b_id = next(t["id"] for t in tags if t["tag"] == "tag_b")

        # Filter by both tags
        response = await client.get("/api/media", params={"tag_ids": f"{tag_a_id},{tag_b_id}"})
        assert response.status_code == 200

        data = response.json()
        # Should include both items
        assert data["total"] >= 2
        item_ids = [item["id"] for item in data["items"]]
        assert media_id_1 in item_ids
        assert media_id_2 in item_ids


class TestMediaWebSocketEvents:
    """Tests for WebSocket events emitted on media changes."""

    async def test_delete_media_broadcasts_event(self, client: AsyncClient, seeded_media):
        """Test that deleting media broadcasts media_deleted event."""
        media_id = seeded_media[0].id

        mock_ws = MockWebSocketManager()

        # Note: delete endpoint is in trash.py, not media.py
        with patch("routes.trash.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.delete(f"/api/media/{media_id}")
            assert response.status_code == 200

            # Check that media_deleted was broadcast
            events = mock_ws.get_broadcasts("media_deleted")
            assert len(events) >= 1

    async def test_marker_change_broadcasts_media_updated(self, client: AsyncClient, seeded_media, marker_ids):
        """Test that changing markers broadcasts media_updated event."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        mock_ws = MockWebSocketManager()

        with patch("routes.markers.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.post(f"/api/media/{media_id}/markers/{marker_id}")
            assert response.status_code == 200

            # Check that media_updated was broadcast
            events = mock_ws.get_broadcasts("media_updated")
            assert len(events) >= 1


# Fixtures specific to this test module

@pytest.fixture
async def seeded_media(db_session):
    """Create test media items for this module."""
    from tests.helpers.media import create_test_media

    async with db_session() as session:
        items = await create_test_media(session, count=5)
        yield items


@pytest.fixture
async def seeded_media_with_captions(db_session):
    """Create test media items with captions for search testing."""
    from tests.helpers.media import create_test_media

    async with db_session() as session:
        items = await create_test_media(session, count=5, with_captions=True)
        yield items


@pytest.fixture
async def marker_ids(client: AsyncClient):
    """Get marker IDs from the API for use in tests."""
    response = await client.get("/api/markers")
    markers = response.json()

    ids = {}
    for marker in markers:
        ids[marker["name"]] = marker["id"]

    return ids


class TestSetCreationConstraints:
    """Tests that sets/grids cannot be nested."""

    async def test_create_set_rejects_set_item(self, client: AsyncClient, db_session):
        """Creating a set from another set should fail."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            set_item = await create_media_item(session, file_format='stimmaset.json')

        response = await client.post("/api/media/sets", json={
            "media_ids": [set_item.id],
            "title": "Nested Set"
        })

        assert response.status_code == 400
        assert "structured media" in response.json()["detail"].lower()

    async def test_create_set_rejects_grid_item(self, client: AsyncClient, db_session):
        """Creating a set from a grid should fail."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            grid_item = await create_media_item(session, file_format='stimmagrid.json')

        response = await client.post("/api/media/sets", json={
            "media_ids": [grid_item.id],
            "title": "Nested Grid"
        })

        assert response.status_code == 400
        assert "structured media" in response.json()["detail"].lower()

    async def test_create_set_rejects_mixed_with_set(self, client: AsyncClient, db_session):
        """Creating a set with a mix of items including a set should fail."""
        from tests.helpers.media import create_media_item

        async with db_session() as session:
            image = await create_media_item(session, file_format='png')
            set_item = await create_media_item(session, file_format='stimmaset.json')

        response = await client.post("/api/media/sets", json={
            "media_ids": [image.id, set_item.id],
            "title": "Mixed Set"
        })

        assert response.status_code == 400
        assert "structured media" in response.json()["detail"].lower()

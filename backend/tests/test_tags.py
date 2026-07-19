"""
Tests for the tags API endpoints.

Tests cover:
- Tag CRUD operations (create, read, delete)
- Tag assignment to media
- Bulk tag operations
- Media filtering by tags (via browse endpoint)
- WebSocket events for tag changes
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.helpers.media import create_test_media, create_media_item
from tests.helpers.ws import MockWebSocketManager


class TestTagCRUD:
    """Tests for tag CRUD operations."""

    async def test_list_tags_empty(self, client: AsyncClient):
        """Test listing tags when none exist."""
        response = await client.get("/api/tags")
        assert response.status_code == 200
        assert response.json() == []

    async def test_create_tag(self, client: AsyncClient):
        """Test creating a new tag."""
        response = await client.post(
            "/api/tags",
            json={"tag_text": "nature"}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["tag"] == "nature"
        assert "id" in data
        assert "created_at" in data

    async def test_create_tag_normalizes_case(self, client: AsyncClient):
        """Test that tags are normalized to lowercase."""
        response = await client.post(
            "/api/tags",
            json={"tag_text": "UPPERCASE"}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["tag"] == "uppercase"

    async def test_create_tag_strips_whitespace(self, client: AsyncClient):
        """Test that tags have whitespace stripped."""
        response = await client.post(
            "/api/tags",
            json={"tag_text": "  spaces  "}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["tag"] == "spaces"

    async def test_create_duplicate_tag_returns_existing(self, client: AsyncClient):
        """Test that creating a duplicate tag returns the existing one."""
        # Create first
        response1 = await client.post(
            "/api/tags",
            json={"tag_text": "duplicate"}
        )
        tag_id = response1.json()["id"]

        # Create duplicate
        response2 = await client.post(
            "/api/tags",
            json={"tag_text": "duplicate"}
        )
        assert response2.status_code == 200
        assert response2.json()["id"] == tag_id

    async def test_list_tags(self, client: AsyncClient):
        """Test listing tags after creating some."""
        # Create tags
        await client.post("/api/tags", json={"tag_text": "tag1"})
        await client.post("/api/tags", json={"tag_text": "tag2"})

        response = await client.get("/api/tags")
        assert response.status_code == 200

        tags = response.json()
        assert len(tags) >= 2
        tag_names = [t["tag"] for t in tags]
        assert "tag1" in tag_names
        assert "tag2" in tag_names

    async def test_list_tags_with_counts(self, client: AsyncClient, seeded_media):
        """Test listing tags with usage counts."""
        # Create tag and assign to media
        create_response = await client.post("/api/tags", json={"tag_text": "counted"})

        # Assign tag to media
        await client.post(
            f"/api/media/{seeded_media[0].id}/tags",
            json={"tags": ["counted"]}
        )

        response = await client.get("/api/tags", params={"with_counts": True})
        assert response.status_code == 200

        tags = response.json()
        counted_tag = next((t for t in tags if t["tag"] == "counted"), None)
        assert counted_tag is not None
        assert counted_tag["usage_count"] >= 1

    async def test_list_tags_with_counts_ignores_trashed_assets(
        self, client: AsyncClient, seeded_media
    ):
        assignment = await client.post(
            f"/api/media/{seeded_media[0].id}/tags",
            json={"tags": ["trashed-only"]},
        )
        asset_id = assignment.json()["asset_id"]

        response = await client.get("/api/tags", params={"with_counts": True})
        counted_tag = next(t for t in response.json() if t["tag"] == "trashed-only")
        assert counted_tag["usage_count"] == 1

        trashed = await client.post(
            "/api/assets/batch/trash", json={"asset_ids": [asset_id]}
        )
        assert trashed.status_code == 200

        response = await client.get("/api/tags", params={"with_counts": True})
        counted_tag = next(t for t in response.json() if t["tag"] == "trashed-only")
        assert counted_tag["usage_count"] == 0

    async def test_delete_unused_tag(self, client: AsyncClient):
        """Test deleting an unused tag."""
        # Create tag
        response = await client.post("/api/tags", json={"tag_text": "to_delete"})
        tag_id = response.json()["id"]

        # Delete tag
        delete_response = await client.delete(f"/api/tags/{tag_id}")
        assert delete_response.status_code == 200

        # Verify it's gone
        list_response = await client.get("/api/tags")
        tags = list_response.json()
        assert not any(t["id"] == tag_id for t in tags)

    async def test_delete_tag_in_use_fails(self, client: AsyncClient, seeded_media):
        """Test that deleting a tag in use returns error."""
        # Create tag and assign
        await client.post("/api/tags", json={"tag_text": "in_use"})
        await client.post(
            f"/api/media/{seeded_media[0].id}/tags",
            json={"tags": ["in_use"]}
        )

        # Get tag ID
        list_response = await client.get("/api/tags")
        tag_id = next(t["id"] for t in list_response.json() if t["tag"] == "in_use")

        # Try to delete
        delete_response = await client.delete(f"/api/tags/{tag_id}")
        assert delete_response.status_code == 400
        assert "used by" in delete_response.json()["detail"].lower()

    async def test_delete_nonexistent_tag(self, client: AsyncClient):
        """Test deleting a tag that doesn't exist."""
        response = await client.delete("/api/tags/99999")
        assert response.status_code == 404


class TestTagAssignment:
    """Tests for assigning tags to media."""

    async def test_add_tags_to_media(self, client: AsyncClient, seeded_media):
        """Test adding tags to a media item."""
        media_id = seeded_media[0].id

        response = await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["landscape", "sunset"]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert len(data["added"]) == 2

    async def test_add_tags_creates_new_tags(self, client: AsyncClient, seeded_media):
        """Test that adding a non-existent tag creates it."""
        media_id = seeded_media[0].id

        # Add new tag
        await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["brand_new_tag"]}
        )

        # Verify tag was created
        response = await client.get("/api/tags")
        tags = response.json()
        assert any(t["tag"] == "brand_new_tag" for t in tags)

    async def test_add_duplicate_tag_to_media(self, client: AsyncClient, seeded_media):
        """Test adding the same tag twice to media."""
        media_id = seeded_media[0].id

        # Add first time
        await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["dup_tag"]}
        )

        # Add second time
        response = await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["dup_tag"]}
        )
        assert response.status_code == 200
        # Should not add duplicate
        assert len(response.json()["added"]) == 0

    async def test_add_tags_to_nonexistent_media(self, client: AsyncClient):
        """Test adding tags to non-existent media returns 404."""
        response = await client.post(
            "/api/media/99999/tags",
            json={"tags": ["test"]}
        )
        assert response.status_code == 404

    async def test_remove_tag_from_media(self, client: AsyncClient, seeded_media):
        """Test removing a tag from a media item."""
        media_id = seeded_media[0].id

        # Add tag first
        await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["removable"]}
        )

        # Get tag ID
        tags_response = await client.get("/api/tags")
        tag_id = next(t["id"] for t in tags_response.json() if t["tag"] == "removable")

        # Remove tag
        response = await client.delete(f"/api/media/{media_id}/tags/{tag_id}")
        assert response.status_code == 200

    async def test_remove_nonexistent_tag_from_media(self, client: AsyncClient, seeded_media):
        """Test removing a tag that's not on the media returns 404."""
        media_id = seeded_media[0].id

        response = await client.delete(f"/api/media/{media_id}/tags/99999")
        assert response.status_code == 404


class TestBulkTagOperations:
    """Tests for POST /api/media/batch/tags endpoint."""

    async def test_bulk_add_tags(self, client: AsyncClient, seeded_media):
        """Test bulk adding tags to multiple media items."""
        media_ids = [m.id for m in seeded_media[:3]]

        response = await client.post(
            "/api/media/batch/tags",
            json={
                "media_ids": media_ids,
                "tag_texts": ["bulk1", "bulk2"]
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        # 3 media items × 2 tags = 6 additions
        assert data["added"] == 6

    async def test_bulk_remove_tags(self, client: AsyncClient, seeded_media):
        """Test bulk removing tags from multiple media items."""
        media_ids = [m.id for m in seeded_media[:2]]

        # Add tags first
        await client.post(
            "/api/media/batch/tags",
            json={
                "media_ids": media_ids,
                "tag_texts": ["to_remove"]
            }
        )

        # Get tag ID
        tags_response = await client.get("/api/tags")
        tag_id = next(t["id"] for t in tags_response.json() if t["tag"] == "to_remove")

        # Bulk remove
        response = await client.post(
            "/api/media/batch/tags",
            json={
                "media_ids": media_ids,
                "remove_tag_ids": [tag_id]
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["removed"] == 2

    async def test_bulk_add_and_remove_together(self, client: AsyncClient, seeded_media):
        """Test bulk add and remove in same request."""
        media_ids = [m.id for m in seeded_media[:2]]

        # First add a tag to remove
        await client.post(
            "/api/media/batch/tags",
            json={
                "media_ids": media_ids,
                "tag_texts": ["old_tag"]
            }
        )

        # Get tag ID
        tags_response = await client.get("/api/tags")
        old_tag_id = next(t["id"] for t in tags_response.json() if t["tag"] == "old_tag")

        # Add new and remove old
        response = await client.post(
            "/api/media/batch/tags",
            json={
                "media_ids": media_ids,
                "tag_texts": ["new_tag"],
                "remove_tag_ids": [old_tag_id]
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["added"] == 2
        assert data["removed"] == 2


class TestTagWebSocketEvents:
    """Tests for WebSocket events emitted on tag changes."""

    async def test_add_tags_broadcasts_event(self, client: AsyncClient, seeded_media):
        """Test that adding tags broadcasts media_updated event."""
        media_id = seeded_media[0].id
        mock_ws = MockWebSocketManager()

        with patch("routes.tags.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.post(
                f"/api/media/{media_id}/tags",
                json={"tags": ["ws_test"]}
            )
            assert response.status_code == 200

            # Check that media_updated was broadcast
            events = mock_ws.get_broadcasts("media_updated")
            assert len(events) >= 1

    async def test_remove_tag_broadcasts_event(self, client: AsyncClient, seeded_media):
        """Test that removing a tag broadcasts media_updated event."""
        media_id = seeded_media[0].id

        # Add tag first
        await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["to_ws_remove"]}
        )

        # Get tag ID
        tags_response = await client.get("/api/tags")
        tag_id = next(t["id"] for t in tags_response.json() if t["tag"] == "to_ws_remove")

        mock_ws = MockWebSocketManager()

        with patch("routes.tags.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.delete(f"/api/media/{media_id}/tags/{tag_id}")
            assert response.status_code == 200

            # Check that media_updated was broadcast
            events = mock_ws.get_broadcasts("media_updated")
            assert len(events) >= 1

    async def test_bulk_operation_broadcasts_events(self, client: AsyncClient, seeded_media):
        """Test that bulk operations broadcast media_updated events."""
        media_ids = [m.id for m in seeded_media[:2]]

        mock_ws = MockWebSocketManager()

        with patch("routes.tags.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.post(
                "/api/media/batch/tags",
                json={
                    "media_ids": media_ids,
                    "tag_texts": ["bulk_ws_test"]
                }
            )
            assert response.status_code == 200

            # Check that media_updated was broadcast
            events = mock_ws.get_broadcasts("media_updated")
            assert len(events) >= 1


class TestMediaFilteringByTags:
    """Tests for filtering media by tags via the browse endpoint."""

    async def test_filter_media_by_tag(self, client: AsyncClient, seeded_media):
        """Test filtering media list by tag."""
        # Add tag to one media item
        media_id = seeded_media[0].id
        await client.post(
            f"/api/media/{media_id}/tags",
            json={"tags": ["filter_test"]}
        )

        # Get tag ID
        tags_response = await client.get("/api/tags")
        tag_id = next(t["id"] for t in tags_response.json() if t["tag"] == "filter_test")

        # Filter by tag
        response = await client.get("/api/media", params={"tag_ids": str(tag_id)})
        assert response.status_code == 200

        data = response.json()
        # Should find at least the one tagged item
        assert data["total"] >= 1
        item_ids = [item["id"] for item in data["items"]]
        assert media_id in item_ids


# Fixtures specific to this test module

@pytest.fixture
async def seeded_media(db_session):
    """Create test media items for this module."""
    async with db_session() as session:
        items = await create_test_media(session, count=5)
        yield items

"""
Tests for the markers API endpoints.

Tests cover:
- Marker definitions endpoint (GET /api/markers)
- Marker assignment (POST /api/media/{id}/markers/{marker_id})
- Marker removal (DELETE /api/media/{id}/markers/{marker_id})
- Bulk marker operations (POST /api/media/batch/markers)
- WebSocket events for marker changes
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.helpers.media import create_test_media, create_media_item
from tests.helpers.ws import MockWebSocketManager


class TestMarkerDefinitions:
    """Tests for GET /api/markers endpoint."""

    async def test_get_markers_returns_configured_markers(self, client: AsyncClient):
        """Test that configured markers are returned."""
        response = await client.get("/api/markers")
        assert response.status_code == 200

        markers = response.json()
        # Config defines 'favorite' and 'library' markers
        assert len(markers) >= 2

        names = {m["name"] for m in markers}
        assert "favorite" in names
        assert "library" in names

    async def test_marker_response_structure(self, client: AsyncClient):
        """Test that marker response has expected fields."""
        response = await client.get("/api/markers")
        assert response.status_code == 200

        markers = response.json()
        assert len(markers) > 0

        marker = markers[0]
        assert "id" in marker
        assert "name" in marker
        assert "icon_svg" in marker
        assert "color" in marker
        assert "created_at" in marker


class TestMarkerAssignment:
    """Tests for POST /api/media/{media_id}/markers/{marker_id} endpoint."""

    async def test_add_marker_to_media(self, client: AsyncClient, seeded_media, marker_ids):
        """Test adding a marker to a media item."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        response = await client.post(f"/api/media/{media_id}/markers/{marker_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"

    async def test_get_media_markers(self, client: AsyncClient, seeded_media, marker_ids):
        """Test getting markers for a media item."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Add a marker first
        await client.post(f"/api/media/{media_id}/markers/{marker_id}")

        # Get markers
        response = await client.get(f"/api/media/{media_id}/markers")
        assert response.status_code == 200

        markers = response.json()
        assert len(markers) >= 1
        assert any(m["id"] == marker_id for m in markers)

    async def test_add_marker_already_exists(self, client: AsyncClient, seeded_media, marker_ids):
        """Test adding the same marker twice returns appropriate status."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Add marker first time
        await client.post(f"/api/media/{media_id}/markers/{marker_id}")

        # Add same marker again
        response = await client.post(f"/api/media/{media_id}/markers/{marker_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "already_exists"

    async def test_add_marker_nonexistent_media(self, client: AsyncClient, marker_ids):
        """Test adding marker to non-existent media returns 404."""
        marker_id = marker_ids["favorite"]

        response = await client.post(f"/api/media/99999/markers/{marker_id}")
        assert response.status_code == 404

    async def test_add_nonexistent_marker(self, client: AsyncClient, seeded_media):
        """Test adding non-existent marker returns 404."""
        media_id = seeded_media[0].id

        response = await client.post(f"/api/media/{media_id}/markers/99999")
        assert response.status_code == 404

    async def test_batch_get_markers(self, client: AsyncClient, seeded_media, marker_ids):
        """Test batch getting markers for multiple media items."""
        media_id_1 = seeded_media[0].id
        media_id_2 = seeded_media[1].id

        # Add different markers to different items
        await client.post(f"/api/media/{media_id_1}/markers/{marker_ids['favorite']}")
        await client.post(f"/api/media/{media_id_2}/markers/{marker_ids['library']}")

        # Batch get
        response = await client.post(
            "/api/media/markers/batch-get",
            json=[media_id_1, media_id_2]
        )
        assert response.status_code == 200

        data = response.json()
        assert str(media_id_1) in data or media_id_1 in data
        assert str(media_id_2) in data or media_id_2 in data


class TestMarkerRemoval:
    """Tests for DELETE /api/media/{media_id}/markers/{marker_id} endpoint."""

    async def test_remove_marker_from_media(self, client: AsyncClient, seeded_media, marker_ids):
        """Test removing a marker from a media item."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Add marker first
        await client.post(f"/api/media/{media_id}/markers/{marker_id}")

        # Remove marker
        response = await client.delete(f"/api/media/{media_id}/markers/{marker_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"

        # Verify marker is removed
        markers_response = await client.get(f"/api/media/{media_id}/markers")
        markers = markers_response.json()
        assert not any(m["id"] == marker_id for m in markers)

    async def test_remove_nonexistent_marker_from_media(self, client: AsyncClient, seeded_media, marker_ids):
        """Test removing a marker that isn't on the media returns 404."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Try to remove without adding first
        response = await client.delete(f"/api/media/{media_id}/markers/{marker_id}")
        assert response.status_code == 404

    async def test_remove_marker_nonexistent_marker_id(self, client: AsyncClient, seeded_media):
        """Test removing non-existent marker returns 404."""
        media_id = seeded_media[0].id

        response = await client.delete(f"/api/media/{media_id}/markers/99999")
        assert response.status_code == 404

    async def test_auto_marker_suppression(self, client: AsyncClient, db_session, marker_ids):
        """Test that auto-markers are suppressed (not deleted) when removed."""
        from database import MediaMarker

        # Create media item
        async with db_session() as session:
            media = await create_media_item(session)
            media_id = media.id

            # Add an auto-marker directly in DB
            auto_marker = MediaMarker(
                media_id=media_id,
                marker_id=marker_ids["favorite"],
                source="auto"
            )
            session.add(auto_marker)
            await session.commit()

        # Remove via API (should suppress, not delete)
        response = await client.delete(f"/api/media/{media_id}/markers/{marker_ids['favorite']}")
        assert response.status_code == 200

        # Verify it's suppressed (not returned in API but still in DB)
        markers_response = await client.get(f"/api/media/{media_id}/markers")
        markers = markers_response.json()
        assert not any(m["id"] == marker_ids["favorite"] for m in markers)

        # Verify source is 'suppressed' in DB
        async with db_session() as session:
            from sqlalchemy import select, and_
            result = await session.execute(
                select(MediaMarker).where(
                    and_(
                        MediaMarker.media_id == media_id,
                        MediaMarker.marker_id == marker_ids["favorite"]
                    )
                )
            )
            mm = result.scalar_one_or_none()
            assert mm is not None
            assert mm.source == "suppressed"


class TestBulkMarkerOperations:
    """Tests for POST /api/media/batch/markers endpoint."""

    async def test_bulk_add_markers(self, client: AsyncClient, seeded_media, marker_ids):
        """Test bulk adding markers to multiple media items."""
        media_ids = [m.id for m in seeded_media[:3]]
        marker_id = marker_ids["favorite"]

        response = await client.post(
            "/api/media/batch/markers",
            json={
                "media_ids": media_ids,
                "marker_id": marker_id,
                "add": True
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["added"] == 3
        assert data["total"] == 3

        # Verify markers were added
        for media_id in media_ids:
            markers_response = await client.get(f"/api/media/{media_id}/markers")
            markers = markers_response.json()
            assert any(m["id"] == marker_id for m in markers)

    async def test_bulk_remove_markers(self, client: AsyncClient, seeded_media, marker_ids):
        """Test bulk removing markers from multiple media items."""
        media_ids = [m.id for m in seeded_media[:3]]
        marker_id = marker_ids["library"]

        # Add markers first
        await client.post(
            "/api/media/batch/markers",
            json={
                "media_ids": media_ids,
                "marker_id": marker_id,
                "add": True
            }
        )

        # Remove markers
        response = await client.post(
            "/api/media/batch/markers",
            json={
                "media_ids": media_ids,
                "marker_id": marker_id,
                "add": False
            }
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["removed"] == 3

        # Verify markers were removed
        for media_id in media_ids:
            markers_response = await client.get(f"/api/media/{media_id}/markers")
            markers = markers_response.json()
            assert not any(m["id"] == marker_id for m in markers)

    async def test_bulk_add_nonexistent_marker(self, client: AsyncClient, seeded_media):
        """Test bulk add with non-existent marker returns 404."""
        media_ids = [m.id for m in seeded_media[:2]]

        response = await client.post(
            "/api/media/batch/markers",
            json={
                "media_ids": media_ids,
                "marker_id": 99999,
                "add": True
            }
        )
        assert response.status_code == 404

    async def test_bulk_add_idempotent(self, client: AsyncClient, seeded_media, marker_ids):
        """Test that bulk adding same marker twice doesn't double-count."""
        media_ids = [m.id for m in seeded_media[:2]]
        marker_id = marker_ids["favorite"]

        # Add first time
        response1 = await client.post(
            "/api/media/batch/markers",
            json={
                "media_ids": media_ids,
                "marker_id": marker_id,
                "add": True
            }
        )
        assert response1.json()["added"] == 2

        # Add second time (already exists, so upgrades or skips)
        response2 = await client.post(
            "/api/media/batch/markers",
            json={
                "media_ids": media_ids,
                "marker_id": marker_id,
                "add": True
            }
        )
        # Since they're already manual, no upgrade needed
        assert response2.json()["added"] == 0


class TestMarkerWebSocketEvents:
    """Tests for WebSocket events emitted on marker changes."""

    async def test_add_marker_broadcasts_event(self, client: AsyncClient, seeded_media, marker_ids):
        """Test that adding a marker broadcasts media_updated event."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        mock_ws = MockWebSocketManager()

        with patch("routes.markers.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.post(f"/api/media/{media_id}/markers/{marker_id}")
            assert response.status_code == 200

            # Check that media_updated was broadcast
            media_updated_events = mock_ws.get_broadcasts("media_updated")
            assert len(media_updated_events) >= 1

    async def test_remove_marker_broadcasts_event(self, client: AsyncClient, seeded_media, marker_ids):
        """Test that removing a marker broadcasts media_updated event."""
        media_id = seeded_media[0].id
        marker_id = marker_ids["favorite"]

        # Add marker first (without mock to avoid counting this event)
        await client.post(f"/api/media/{media_id}/markers/{marker_id}")

        mock_ws = MockWebSocketManager()

        with patch("routes.markers.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.delete(f"/api/media/{media_id}/markers/{marker_id}")
            assert response.status_code == 200

            # Check that media_updated was broadcast
            media_updated_events = mock_ws.get_broadcasts("media_updated")
            assert len(media_updated_events) >= 1

    async def test_bulk_operation_broadcasts_events(self, client: AsyncClient, seeded_media, marker_ids):
        """Test that bulk operations broadcast media_updated events."""
        media_ids = [m.id for m in seeded_media[:3]]
        marker_id = marker_ids["favorite"]

        mock_ws = MockWebSocketManager()

        with patch("routes.markers.ws_manager", mock_ws), \
             patch("utils.websocket.ws_manager", mock_ws):
            response = await client.post(
                "/api/media/batch/markers",
                json={
                    "media_ids": media_ids,
                    "marker_id": marker_id,
                    "add": True
                }
            )
            assert response.status_code == 200

            # Check that media_updated was broadcast
            media_updated_events = mock_ws.get_broadcasts("media_updated")
            assert len(media_updated_events) >= 1


# Fixtures specific to this test module

@pytest.fixture
async def seeded_media(db_session):
    """Create test media items for this module."""
    async with db_session() as session:
        items = await create_test_media(session, count=5)
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

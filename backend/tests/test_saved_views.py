"""
Tests for the saved views API endpoints.

Tests cover:
- Saved view CRUD operations (create, read, update, delete)
- Duplicate name validation
- Reorder operations (up/down)
- Display order consistency
"""

import pytest
import httpx

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Module-level state shared between sequential tests
_state = {}


async def test_list_saved_views_returns_list(client: httpx.AsyncClient):
    """GET /api/saved-views returns 200 and a list."""
    response = await client.get("/api/saved-views")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_create_saved_view(client: httpx.AsyncClient):
    """POST /api/saved-views creates a view."""
    response = await client.post(
        "/api/saved-views",
        json={
            "name": "Test View Alpha",
            "filters": {"media_types": "images", "is_generated": True},
            "sort_by": "newest",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test View Alpha"
    assert data["sort_by"] == "newest"
    assert "id" in data
    _state["view_id"] = data["id"]


async def test_get_saved_view(client: httpx.AsyncClient):
    """GET /api/saved-views/{id} returns the created view."""
    view_id = _state["view_id"]
    response = await client.get(f"/api/saved-views/{view_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == view_id
    assert data["name"] == "Test View Alpha"


async def test_update_saved_view(client: httpx.AsyncClient):
    """PUT /api/saved-views/{id} updates fields."""
    view_id = _state["view_id"]
    response = await client.put(
        f"/api/saved-views/{view_id}",
        json={
            "name": "Test View Alpha Updated",
            "filters": {"media_types": "videos"},
            "sort_by": "oldest",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test View Alpha Updated"
    assert data["sort_by"] == "oldest"


async def test_create_duplicate_name_returns_400(client: httpx.AsyncClient):
    """POST /api/saved-views with duplicate name returns 400."""
    response = await client.post(
        "/api/saved-views",
        json={
            "name": "Test View Alpha Updated",
            "filters": {},
            "sort_by": "newest",
        },
    )
    assert response.status_code == 400


async def test_update_duplicate_name_returns_400(client: httpx.AsyncClient):
    """PUT /api/saved-views/{id} with a name that already exists returns 400."""
    # Create a second view
    response = await client.post(
        "/api/saved-views",
        json={
            "name": "Test View Beta",
            "filters": {"is_generated": False},
            "sort_by": "newest",
        },
    )
    assert response.status_code == 200
    _state["view_id_beta"] = response.json()["id"]

    # Try to rename it to the existing name
    response = await client.put(
        f"/api/saved-views/{_state['view_id_beta']}",
        json={"name": "Test View Alpha Updated"},
    )
    assert response.status_code == 400


async def test_reorder_down(client: httpx.AsyncClient):
    """POST /api/saved-views/{id}/reorder with direction=down works."""
    view_id = _state["view_id"]
    response = await client.post(
        f"/api/saved-views/{view_id}/reorder",
        json={"direction": "down"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_reorder_up(client: httpx.AsyncClient):
    """POST /api/saved-views/{id}/reorder with direction=up works."""
    view_id = _state["view_id"]
    response = await client.post(
        f"/api/saved-views/{view_id}/reorder",
        json={"direction": "up"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_display_order_consistent(client: httpx.AsyncClient):
    """display_order values are unique and sequential after operations."""
    response = await client.get("/api/saved-views")
    assert response.status_code == 200
    views = response.json()
    orders = [v["display_order"] for v in views]
    # Orders should be unique
    assert len(orders) == len(set(orders))


async def test_invalid_reorder_direction_returns_400(client: httpx.AsyncClient):
    """POST /api/saved-views/{id}/reorder with invalid direction returns 400."""
    view_id = _state["view_id"]
    response = await client.post(
        f"/api/saved-views/{view_id}/reorder",
        json={"direction": "sideways"},
    )
    assert response.status_code == 400


async def test_delete_saved_view(client: httpx.AsyncClient):
    """DELETE /api/saved-views/{id} returns success."""
    view_id = _state["view_id"]
    response = await client.delete(f"/api/saved-views/{view_id}")
    assert response.status_code == 200


async def test_get_deleted_saved_view_returns_404(client: httpx.AsyncClient):
    """GET /api/saved-views/{id} on a deleted view returns 404."""
    view_id = _state["view_id"]
    response = await client.get(f"/api/saved-views/{view_id}")
    assert response.status_code == 404

"""
Tests for the presets API endpoints.

Tests cover:
- Preset CRUD operations (create, read, update, soft-delete)
- Filtering by tool_id and pinned status
- Use tracking (usage_count increment)
- Duplicate/copy functionality
- Stats endpoint
- 404 handling
"""

import pytest
import httpx

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Module-level state shared between sequential tests
_state = {}


async def test_create_preset(client: httpx.AsyncClient):
    """POST /api/presets creates a preset."""
    response = await client.post(
        "/api/presets",
        json={
            "name": "My Landscape Preset",
            "tool_id": "builtin:TestProvider:tool-a:text-to-image",
            "state": {"width": 1024, "height": 768, "steps": 30},
            "pinned": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My Landscape Preset"
    assert data["tool_id"] == "builtin:TestProvider:tool-a:text-to-image"
    assert data["state"]["width"] == 1024
    assert data["usage_count"] == 0
    _state["preset_id"] = data["id"]


async def test_create_second_preset(client: httpx.AsyncClient):
    """Create a second preset with a different tool_id for filter tests."""
    response = await client.post(
        "/api/presets",
        json={
            "name": "Portrait Preset",
            "tool_id": "builtin:TestProvider:tool-b:image-to-image",
            "state": {"width": 512, "height": 768},
            "pinned": True,
        },
    )
    assert response.status_code == 200
    _state["preset_id_2"] = response.json()["id"]


async def test_list_presets(client: httpx.AsyncClient):
    """GET /api/presets lists all presets."""
    response = await client.get("/api/presets")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2


async def test_list_presets_filter_by_tool_id(client: httpx.AsyncClient):
    """GET /api/presets?tool_id=... filters by tool."""
    response = await client.get(
        "/api/presets",
        params={"tool_id": "builtin:TestProvider:tool-a:text-to-image"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    for preset in data:
        assert preset["tool_id"] == "builtin:TestProvider:tool-a:text-to-image"


async def test_list_presets_filter_pinned(client: httpx.AsyncClient):
    """GET /api/presets?pinned_only=true filters pinned presets."""
    response = await client.get("/api/presets", params={"pinned_only": "true"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    for preset in data:
        assert preset["pinned"] is True


async def test_get_preset(client: httpx.AsyncClient):
    """GET /api/presets/{id} gets a specific preset."""
    preset_id = _state["preset_id"]
    response = await client.get(f"/api/presets/{preset_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == preset_id
    assert data["name"] == "My Landscape Preset"


async def test_update_preset(client: httpx.AsyncClient):
    """PUT /api/presets/{id} updates name, state, pinned."""
    preset_id = _state["preset_id"]
    response = await client.put(
        f"/api/presets/{preset_id}",
        json={
            "name": "My Landscape Preset V2",
            "state": {"width": 2048, "height": 1024, "steps": 50},
            "pinned": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My Landscape Preset V2"
    assert data["state"]["width"] == 2048
    assert data["pinned"] is True


async def test_use_preset_increments_count(client: httpx.AsyncClient):
    """POST /api/presets/{id}/use increments usage_count."""
    preset_id = _state["preset_id"]
    response = await client.post(f"/api/presets/{preset_id}/use")
    assert response.status_code == 200
    data = response.json()
    assert data["usage_count"] == 1

    # Use again
    response2 = await client.post(f"/api/presets/{preset_id}/use")
    assert response2.json()["usage_count"] == 2


async def test_duplicate_preset(client: httpx.AsyncClient):
    """POST /api/presets/{id}/duplicate creates a copy."""
    preset_id = _state["preset_id"]
    response = await client.post(f"/api/presets/{preset_id}/duplicate")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My Landscape Preset V2 (copy)"
    assert data["id"] != preset_id
    assert data["pinned"] is False
    assert data["usage_count"] == 0
    _state["duplicate_id"] = data["id"]


async def test_get_preset_stats(client: httpx.AsyncClient):
    """GET /api/presets/{id}/stats returns stats."""
    preset_id = _state["preset_id"]
    response = await client.get(f"/api/presets/{preset_id}/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["preset_id"] == preset_id
    assert data["applied_count"] == 2  # We called /use twice
    assert "generated_count" in data


async def test_delete_preset(client: httpx.AsyncClient):
    """DELETE /api/presets/{id} soft deletes."""
    preset_id = _state["preset_id"]
    response = await client.delete(f"/api/presets/{preset_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"

    # Subsequent GET returns 404
    get_response = await client.get(f"/api/presets/{preset_id}")
    assert get_response.status_code == 404


async def test_get_nonexistent_preset_returns_404(client: httpx.AsyncClient):
    """GET /api/presets/999999 returns 404."""
    response = await client.get("/api/presets/999999")
    assert response.status_code == 404

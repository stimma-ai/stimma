"""
Tests for the preferences API endpoints.

Tests cover:
- 404 for nonexistent key
- Create preference via PUT (upsert)
- Read preference via GET
- Update existing preference
- JSON round-trip with nested objects
"""

import pytest
import httpx

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_get_nonexistent_preference_returns_404(client: httpx.AsyncClient):
    """GET /api/preferences/nonexistent returns 404."""
    response = await client.get("/api/preferences/nonexistent")
    assert response.status_code == 404


async def test_preference_crud_round_trip(client: httpx.AsyncClient):
    """Create, read, update, and read back a preference."""
    response = await client.put(
        "/api/preferences/test_key",
        json={"theme": "dark"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["key"] == "test_key"

    response = await client.get("/api/preferences/test_key")
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "test_key"
    assert data["value"]["theme"] == "dark"

    response = await client.put(
        "/api/preferences/test_key",
        json={"theme": "light", "font_size": 14},
    )
    assert response.status_code == 200

    response = await client.get("/api/preferences/test_key")
    assert response.status_code == 200
    data = response.json()
    assert data["value"]["theme"] == "light"
    assert data["value"]["font_size"] == 14


async def test_json_round_trip_nested_objects(client: httpx.AsyncClient):
    """JSON round-trip with nested objects works."""
    nested_value = {
        "layout": {
            "sidebar": {"width": 300, "collapsed": False},
            "panels": [
                {"id": "preview", "visible": True},
                {"id": "metadata", "visible": False},
            ],
        },
        "version": 2,
    }
    await client.put("/api/preferences/nested_key", json=nested_value)

    response = await client.get("/api/preferences/nested_key")
    assert response.status_code == 200
    data = response.json()
    assert data["value"] == nested_value

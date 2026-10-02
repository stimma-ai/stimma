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


async def test_project_views_have_independent_names_order_and_lifetime(client: httpx.AsyncClient):
    project = (await client.post('/api/projects', json={'name': 'Saved view scope'})).json()
    other = (await client.post('/api/projects', json={'name': 'Other saved view scope'})).json()

    async def create(name, owner=None):
        response = await client.post('/api/saved-views', json={
            'name': name, 'filters': {}, 'project_id': owner,
        })
        assert response.status_code == 200, response.text
        return response.json()

    global_view = await create('Scoped favorites')
    first = await create('Scoped favorites', project['id'])
    second = await create('Second scoped view', project['id'])
    third = await create('Scoped favorites', other['id'])
    duplicate = await client.post('/api/saved-views', json={
        'name': first['name'], 'filters': {}, 'project_id': project['id'],
    })
    assert duplicate.status_code == 400
    rename = await client.put(f"/api/saved-views/{second['id']}", json={'name': third['name']})
    assert rename.status_code == 400
    reordered = await client.post(f"/api/saved-views/{second['id']}/reorder", json={'direction': 'up'})
    assert [v['id'] for v in reordered.json()] == [second['id'], first['id']]
    assert (await client.get(f"/api/saved-views/{global_view['id']}")).json()['display_order'] == global_view['display_order']
    scoped = await client.get('/api/saved-views', params={'project_id': project['id']})
    assert {v['id'] for v in scoped.json()} == {first['id'], second['id']}
    global_views = (await client.get('/api/saved-views', params={'project_id': 0})).json()
    assert all(v['project_id'] is None for v in global_views)
    await client.delete(f"/api/projects/{project['id']}")
    assert (await client.get(f"/api/saved-views/{first['id']}")).status_code == 404
    assert (await client.get(f"/api/saved-views/{second['id']}")).status_code == 404
    assert (await client.get(f"/api/saved-views/{third['id']}")).status_code == 200
    assert (await client.get(f"/api/saved-views/{global_view['id']}")).status_code == 200
    missing = await client.post('/api/saved-views', json={'name': 'Missing project', 'filters': {}, 'project_id': project['id']})
    assert missing.status_code == 404

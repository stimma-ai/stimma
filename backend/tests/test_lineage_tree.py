"""
Tests for the lineage tree API endpoint.

Tests cover:
- Basic tree structure (nodes and edges)
- Multi-level ancestor chains
- Branching descendants
- Multiple parents (merge nodes)
- Empty lineage (isolated node)
"""

import pytest
from httpx import AsyncClient


async def _create_item(db_session, **kwargs):
    """Helper to create a media item."""
    from tests.helpers.media import create_media_item

    async with db_session() as session:
        return await create_media_item(session, **kwargs)


async def _create_lineage(db_session, media_id: int, source_media_id: int, task_type: str = "image-to-image", relationship_type: str = "derived", source_order: int = 0):
    """Helper to create a lineage record."""
    from database import MediaLineage

    async with db_session() as session:
        lineage = MediaLineage(
            media_id=media_id,
            source_media_id=source_media_id,
            task_type=task_type,
            relationship_type=relationship_type,
            source_order=source_order,
        )
        session.add(lineage)
        await session.commit()


class TestLineageTree:
    """Tests for GET /api/media/{media_id}/lineage/tree endpoint."""

    async def test_isolated_node(self, client: AsyncClient, db_session):
        """A node with no lineage returns just itself."""
        item = await _create_item(db_session)

        response = await client.get(f"/api/media/{item.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        assert data["focus_media_id"] == item.id
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["id"] == item.id
        assert data["nodes"][0]["depth"] == 0
        assert len(data["edges"]) == 0

    async def test_linear_chain(self, client: AsyncClient, db_session):
        """A -> B -> C chain returns all nodes and edges."""
        a = await _create_item(db_session, tool_id="builtin:text-to-image")
        b = await _create_item(db_session, tool_id="builtin:image-to-image")
        c = await _create_item(db_session, tool_id="builtin:upscale")

        await _create_lineage(db_session, b.id, a.id, "text-to-image")
        await _create_lineage(db_session, c.id, b.id, "upscale")

        # Query from the middle node B
        response = await client.get(f"/api/media/{b.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        assert data["focus_media_id"] == b.id

        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {a.id, b.id, c.id}

        # Check depths (relative to B)
        depth_map = {n["id"]: n["depth"] for n in data["nodes"]}
        assert depth_map[a.id] < 0  # ancestor
        assert depth_map[b.id] == 0  # focus
        assert depth_map[c.id] > 0  # descendant

        # Check edges
        edge_pairs = {(e["source_id"], e["target_id"]) for e in data["edges"]}
        assert (a.id, b.id) in edge_pairs
        assert (b.id, c.id) in edge_pairs
        assert len(data["edges"]) == 2

    async def test_branching_descendants(self, client: AsyncClient, db_session):
        """A -> B and A -> C (one parent, two children)."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, a.id, "upscale")

        response = await client.get(f"/api/media/{a.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {a.id, b.id, c.id}

        edge_pairs = {(e["source_id"], e["target_id"]) for e in data["edges"]}
        assert (a.id, b.id) in edge_pairs
        assert (a.id, c.id) in edge_pairs

    async def test_multiple_parents(self, client: AsyncClient, db_session):
        """A + B -> C (two parents, one child)."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, c.id, a.id, "image-to-image", source_order=0)
        await _create_lineage(db_session, c.id, b.id, "image-to-image", source_order=1)

        response = await client.get(f"/api/media/{c.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {a.id, b.id, c.id}

        edge_pairs = {(e["source_id"], e["target_id"]) for e in data["edges"]}
        assert (a.id, c.id) in edge_pairs
        assert (b.id, c.id) in edge_pairs

    async def test_relationship_types(self, client: AsyncClient, db_session):
        """Edges carry relationship_type and task_type."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image", relationship_type="inspired")

        response = await client.get(f"/api/media/{a.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        assert len(data["edges"]) == 1
        edge = data["edges"][0]
        assert edge["task_type"] == "image-to-image"
        assert edge["relationship_type"] == "inspired"

    async def test_full_connected_component(self, client: AsyncClient, db_session):
        """Querying from a leaf includes siblings and their descendants.

        Tree: A -> B -> C (focus), A -> D -> E
        Querying from C should include D and E (siblings/cousins).
        """
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)
        d = await _create_item(db_session)
        e = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, b.id, "upscale")
        await _create_lineage(db_session, d.id, a.id, "image-to-image")
        await _create_lineage(db_session, e.id, d.id, "upscale")

        response = await client.get(f"/api/media/{c.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        # All 5 nodes should be present — full connected component
        assert node_ids == {a.id, b.id, c.id, d.id, e.id}

    async def test_nonexistent_media(self, client: AsyncClient):
        """Requesting tree for nonexistent media returns 404."""
        response = await client.get("/api/media/999999/lineage/tree")
        assert response.status_code == 404

    async def test_nodes_include_media_data(self, client: AsyncClient, db_session):
        """Nodes include full media data."""
        item = await _create_item(db_session, width=512, height=512)

        response = await client.get(f"/api/media/{item.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node = data["nodes"][0]
        assert "media" in node
        assert node["media"]["width"] == 512
        assert node["media"]["height"] == 512

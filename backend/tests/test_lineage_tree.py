"""
Tests for the lineage tree API endpoint.

Tests cover:
- Basic tree structure (nodes and edges)
- Directional walk: ancestors + descendants only, never siblings/cousins
- Asset-aware visibility: trashed Assets and bare Media as placeholders or dropped
- Truncation budget
- The flat /lineage endpoint's Asset-aware gates
"""

import pytest
from httpx import AsyncClient


async def _create_item(db_session, materialize_asset=True, **kwargs):
    """Helper to create a media item (Asset-backed by default, like real producers)."""
    from tests.helpers.media import create_media_item

    async with db_session() as session:
        return await create_media_item(session, materialize_asset=materialize_asset, **kwargs)


async def _trash_item(db_session, media_id: int):
    """Move the Asset retaining this media to Trash (canonical trash path)."""
    from sqlalchemy import select
    from database import AssetRevision
    from asset_service import trash_asset

    async with db_session() as session:
        revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == media_id)
        )
        assert revision is not None, "media is not Asset-backed"
        await trash_asset(session, asset_id=revision.asset_id)
        await session.commit()


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
        assert data["truncated"] is False
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["id"] == item.id
        assert data["nodes"][0]["depth"] == 0
        assert data["nodes"][0]["kind"] == "asset"
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

    async def test_siblings_and_cousins_included(self, client: AsyncClient, db_session):
        """The walk covers the whole connected component of visible nodes.

        Tree: A -> B -> C (focus), A -> D -> E
        Querying from C includes the sibling branch D and its descendant E.
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
        assert node_ids == {a.id, b.id, c.id, d.id, e.id}

    async def test_trashed_sibling_dropped(self, client: AsyncClient, db_session):
        """Trashed sibling drafts with no visible offspring stay out of the tree."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, a.id, "image-to-image")
        await _trash_item(db_session, c.id)

        response = await client.get(f"/api/media/{b.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {a.id, b.id}

    async def test_trashed_sibling_with_live_descendant_is_placeholder(self, client: AsyncClient, db_session):
        """A trashed sibling survives as a placeholder when something visible came from it."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)
        d = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, a.id, "image-to-image")
        await _create_lineage(db_session, d.id, c.id, "upscale")
        await _trash_item(db_session, c.id)

        response = await client.get(f"/api/media/{b.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert set(nodes_by_id) == {a.id, b.id, c.id, d.id}
        assert nodes_by_id[c.id]["kind"] == "trashed"
        assert nodes_by_id[c.id].get("placeholder") is True
        assert nodes_by_id[d.id]["kind"] == "asset"

    async def test_expired_asset_is_not_full_node(self, client: AsyncClient, db_session):
        """Assets past their auto-delete deadline never render as full nodes."""
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from database import Asset, AssetRevision

        a = await _create_item(db_session)
        b = await _create_item(db_session)
        await _create_lineage(db_session, b.id, a.id, "image-to-image")

        async with db_session() as session:
            revision = await session.scalar(
                select(AssetRevision).where(AssetRevision.primary_media_id == b.id)
            )
            asset = await session.get(Asset, revision.asset_id)
            asset.expires_at = datetime.utcnow() - timedelta(hours=1)
            await session.commit()

        response = await client.get(f"/api/media/{a.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert b.id not in node_ids  # expired leaf is dropped

    async def test_old_revision_payload_is_placeholder(self, client: AsyncClient, db_session):
        """Media that is a non-current revision payload shows as a placeholder, not a card."""
        from sqlalchemy import select
        from database import Asset, AssetRevision

        v1 = await _create_item(db_session)
        v2 = await _create_item(db_session, materialize_asset=False)
        child = await _create_item(db_session)

        # Make v2 the current revision of v1's asset; v1 becomes history.
        async with db_session() as session:
            revision1 = await session.scalar(
                select(AssetRevision).where(AssetRevision.primary_media_id == v1.id)
            )
            asset = await session.get(Asset, revision1.asset_id)
            revision2 = AssetRevision(
                asset_id=asset.id,
                parent_revision_id=revision1.id,
                primary_media_id=v2.id,
                revision_number=revision1.revision_number + 1,
            )
            session.add(revision2)
            await session.flush()
            asset.current_revision_id = revision2.id
            await session.commit()

        await _create_lineage(db_session, child.id, v1.id, "image-to-image")

        response = await client.get(f"/api/media/{child.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert set(nodes_by_id) == {v1.id, child.id}
        assert nodes_by_id[v1.id]["kind"] == "revision"
        assert nodes_by_id[v1.id].get("placeholder") is True

    async def test_dangling_lineage_rows_skipped(self, client: AsyncClient, db_session):
        """Lineage rows pointing at permanently deleted media are never followed."""
        from sqlalchemy import text

        # Create the ghost first: media_items ids are not AUTOINCREMENT, so
        # deleting the highest id would let the next test reuse it and inherit
        # this test's dangling lineage row.
        ghost = await _create_item(db_session, materialize_asset=False)
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, b.id, ghost.id, "image-to-image", source_order=1)
        # Simulate a pre-cutover hard delete that left the lineage row behind
        # (real profile databases do not enforce FKs).
        async with db_session() as session:
            await session.execute(text("PRAGMA foreign_keys=OFF"))
            await session.execute(text("DELETE FROM media_items WHERE id = :mid"), {"mid": ghost.id})
            await session.commit()
            await session.execute(text("PRAGMA foreign_keys=ON"))

        response = await client.get(f"/api/media/{b.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {a.id, b.id}
        assert all(e["source_id"] != ghost.id for e in data["edges"])

    async def test_trashed_descendant_leaf_dropped(self, client: AsyncClient, db_session):
        """Trashed descendants with no live offspring disappear from the tree."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, a.id, "image-to-image")
        await _trash_item(db_session, c.id)

        response = await client.get(f"/api/media/{a.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        node_ids = {n["id"] for n in data["nodes"]}
        assert node_ids == {a.id, b.id}

    async def test_trashed_interior_descendant_is_placeholder(self, client: AsyncClient, db_session):
        """A trashed node between the focus and a live descendant stays as a placeholder."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, b.id, "upscale")
        await _trash_item(db_session, b.id)

        response = await client.get(f"/api/media/{a.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert set(nodes_by_id) == {a.id, b.id, c.id}
        assert nodes_by_id[b.id]["kind"] == "trashed"
        assert nodes_by_id[b.id].get("placeholder") is True
        assert nodes_by_id[c.id]["kind"] == "asset"

    async def test_trashed_ancestor_is_placeholder(self, client: AsyncClient, db_session):
        """Ancestors in Trash remain visible as placeholders (provenance path to focus)."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _trash_item(db_session, a.id)

        response = await client.get(f"/api/media/{b.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert set(nodes_by_id) == {a.id, b.id}
        assert nodes_by_id[a.id]["kind"] == "trashed"
        assert nodes_by_id[a.id].get("placeholder") is True

    async def test_bare_media_leaf_dropped_interior_kept(self, client: AsyncClient, db_session):
        """Bare contextual Media: leaves dropped, interior steps become placeholders.

        Chain: A(asset) -> I(bare) -> B(asset), plus A -> J(bare leaf).
        """
        a = await _create_item(db_session)
        i = await _create_item(db_session, materialize_asset=False)
        b = await _create_item(db_session)
        j = await _create_item(db_session, materialize_asset=False)

        await _create_lineage(db_session, i.id, a.id, "image-to-image")
        await _create_lineage(db_session, b.id, i.id, "upscale")
        await _create_lineage(db_session, j.id, a.id, "image-to-image")

        response = await client.get(f"/api/media/{a.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert set(nodes_by_id) == {a.id, i.id, b.id}
        assert nodes_by_id[i.id]["kind"] == "intermediate"
        assert nodes_by_id[i.id].get("placeholder") is True
        assert j.id not in nodes_by_id

    async def test_trashed_focus_returns_full_node(self, client: AsyncClient, db_session):
        """Opening lineage on a trashed item still shows the focus with full payload."""
        a = await _create_item(db_session)
        b = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _trash_item(db_session, b.id)

        response = await client.get(f"/api/media/{b.id}/lineage/tree")
        assert response.status_code == 200

        data = response.json()
        nodes_by_id = {n["id"]: n for n in data["nodes"]}
        assert set(nodes_by_id) == {a.id, b.id}
        focus = nodes_by_id[b.id]
        assert focus["kind"] == "trashed"
        assert focus.get("placeholder") is not True
        assert focus["media"]["file_hash"]

    async def test_truncation_budget(self, client: AsyncClient, db_session):
        """The walk stops expanding at max_nodes and reports truncation."""
        root = await _create_item(db_session)
        for _ in range(15):
            child = await _create_item(db_session)
            await _create_lineage(db_session, child.id, root.id, "image-to-image")

        response = await client.get(f"/api/media/{root.id}/lineage/tree?max_nodes=10")
        assert response.status_code == 200

        data = response.json()
        assert data["truncated"] is True
        assert len(data["nodes"]) <= 10

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


class TestFlatLineage:
    """Tests for GET /api/media/{media_id}/lineage Asset-aware gates."""

    async def test_trashed_derivative_excluded(self, client: AsyncClient, db_session):
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, a.id, "image-to-image")
        await _trash_item(db_session, c.id)

        response = await client.get(f"/api/media/{a.id}/lineage")
        assert response.status_code == 200

        data = response.json()
        derivative_ids = {d["media"]["id"] for d in data["derivatives"]}
        assert derivative_ids == {b.id}

    async def test_trashed_source_is_stub(self, client: AsyncClient, db_session):
        a = await _create_item(db_session)
        b = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _trash_item(db_session, a.id)

        response = await client.get(f"/api/media/{b.id}/lineage")
        assert response.status_code == 200

        data = response.json()
        assert len(data["sources"]) == 1
        source = data["sources"][0]
        assert source["type"] == "trashed"
        assert source["media_id"] == a.id
        assert "media" not in source

    async def test_bare_source_is_intermediate_stub(self, client: AsyncClient, db_session):
        i = await _create_item(db_session, materialize_asset=False)
        b = await _create_item(db_session)

        await _create_lineage(db_session, b.id, i.id, "image-to-image")

        response = await client.get(f"/api/media/{b.id}/lineage")
        assert response.status_code == 200

        data = response.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["type"] == "intermediate"
        assert data["sources"][0]["media_id"] == i.id

    async def test_trashed_descendants_excluded_recursive(self, client: AsyncClient, db_session):
        a = await _create_item(db_session)
        b = await _create_item(db_session)
        c = await _create_item(db_session)

        await _create_lineage(db_session, b.id, a.id, "image-to-image")
        await _create_lineage(db_session, c.id, b.id, "upscale")
        await _trash_item(db_session, c.id)

        response = await client.get(f"/api/media/{a.id}/lineage?include_descendants=true")
        assert response.status_code == 200

        data = response.json()
        descendant_ids = {d["media"]["id"] for d in data["descendants"]}
        assert descendant_ids == {b.id}

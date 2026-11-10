"""
Tests for the collections API endpoints.
"""

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import select

from asset_service import create_asset_from_media
from database import CollectionAssetItem, CollectionSection, MediaItem
from tests.helpers.media import create_test_media
from tests.helpers.ws import MockWebSocketManager


@pytest.fixture
async def seeded_media(db_session):
    async with db_session() as session:
        items = await create_test_media(session, count=3)
        return items


class TestCollectionsApi:
    async def test_create_and_list_collections(self, client):
        create_response = await client.post("/api/collections", json={"name": "Moodboard"})
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "Moodboard"
        assert len(created["sections"]) == 1
        assert created["sections"][0]["is_default"] is True
        assert created["sections"][0]["name"] is None

        list_response = await client.get("/api/collections")
        assert list_response.status_code == 200
        collections = list_response.json()
        assert any(collection["id"] == created["id"] for collection in collections)

    async def test_add_items_create_section_move_and_remove(self, client, seeded_media):
        collection = (await client.post("/api/collections", json={"name": "Working Set"})).json()
        collection_id = collection["id"]
        default_section_id = collection["sections"][0]["id"]

        add_response = await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )
        assert add_response.status_code == 200
        assert add_response.json()["added"] == 2

        section_response = await client.post(
            f"/api/collections/{collection_id}/sections",
            json={"name": "References"},
        )
        assert section_response.status_code == 200
        section = section_response.json()
        assert section["name"] == "References"

        move_response = await client.post(
            f"/api/collections/{collection_id}/items/move",
            json={
                "media_id": seeded_media[1].id,
                "from_section_id": default_section_id,
                "to_section_id": section["id"],
                "target_index": 0,
            },
        )
        assert move_response.status_code == 200

        collection_response = await client.get(f"/api/collections/{collection_id}")
        assert collection_response.status_code == 200
        payload = collection_response.json()
        default_section = next(item for item in payload["sections"] if item["id"] == default_section_id)
        reference_section = next(item for item in payload["sections"] if item["id"] == section["id"])
        assert [item["media_id"] for item in default_section["items"]] == [seeded_media[0].id]
        assert [item["media_id"] for item in reference_section["items"]] == [seeded_media[1].id]

        remove_response = await client.delete(
            f"/api/collections/sections/{section['id']}/items/{seeded_media[1].id}"
        )
        assert remove_response.status_code == 200

        updated = (await client.get(f"/api/collections/{collection_id}")).json()
        assert not any(item["id"] == section["id"] for item in updated["sections"])

    async def test_asset_membership_projects_current_media(self, client, db_session, seeded_media):
        async with db_session() as session:
            asset = await create_asset_from_media(
                session, media_id=seeded_media[0].id
            )
            asset_id = asset.id
            await session.commit()

        collection = (await client.post("/api/collections", json={"name": "Assets"})).json()
        section_id = collection["sections"][0]["id"]
        added = await client.post(
            f"/api/collections/{collection['id']}/items",
            json={"asset_ids": [asset_id]},
        )
        assert added.status_code == 200, added.text
        assert added.json()["added"] == 1

        payload = (await client.get(f"/api/collections/{collection['id']}")).json()
        item = payload["sections"][0]["items"][0]
        assert item["id"] == asset_id
        assert item["asset_id"] == asset_id
        assert item["media_id"] == seeded_media[0].id

        removed = await client.delete(
            f"/api/collections/sections/{section_id}/asset-items/{asset_id}"
        )
        assert removed.status_code == 200

    async def test_move_item_into_section_where_it_already_exists_reorders_without_duplicate(self, client, seeded_media):
        collection = (await client.post("/api/collections", json={"name": "Working Set"})).json()
        collection_id = collection["id"]
        default_section_id = collection["sections"][0]["id"]

        section_response = await client.post(
            f"/api/collections/{collection_id}/sections",
            json={"name": "References"},
        )
        assert section_response.status_code == 200
        target_section_id = section_response.json()["id"]

        add_default = await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )
        assert add_default.status_code == 200

        add_target = await client.post(
            f"/api/collections/{collection_id}/items",
            json={"section_id": target_section_id, "media_ids": [seeded_media[2].id, seeded_media[1].id]},
        )
        assert add_target.status_code == 200

        move_response = await client.post(
            f"/api/collections/{collection_id}/items/move",
            json={
                "media_id": seeded_media[1].id,
                "from_section_id": default_section_id,
                "to_section_id": target_section_id,
                "target_index": 0,
            },
        )
        assert move_response.status_code == 200

        collection_response = await client.get(f"/api/collections/{collection_id}")
        assert collection_response.status_code == 200
        payload = collection_response.json()
        default_section = next(item for item in payload["sections"] if item["id"] == default_section_id)
        target_section = next(item for item in payload["sections"] if item["id"] == target_section_id)

        assert [item["media_id"] for item in default_section["items"]] == [seeded_media[0].id]
        assert [item["media_id"] for item in target_section["items"]] == [seeded_media[1].id, seeded_media[2].id]

    async def test_collection_websocket_events(self, client):
        mock_ws = MockWebSocketManager()
        with patch("routes.collections.ws_manager", mock_ws):
            create_response = await client.post("/api/collections", json={"name": "Events"})
            assert create_response.status_code == 200
            collection_id = create_response.json()["id"]
            mock_ws.assert_broadcast("collection_created")

            update_response = await client.put(f"/api/collections/{collection_id}", json={"name": "Renamed"})
            assert update_response.status_code == 200
            mock_ws.assert_broadcast("collection_updated")

            delete_response = await client.delete(f"/api/collections/{collection_id}")
            assert delete_response.status_code == 200
            mock_ws.assert_broadcast("collection_deleted", {"collection_id": collection_id})


class TestCollectionTrashInteractions:
    """Tests for how collections interact with trashed/deleted media."""

    async def test_trashed_media_hidden_from_collection(self, client, seeded_media):
        """Trashing an Asset hides it without removing its collection membership."""
        collection = (await client.post("/api/collections", json={"name": "Trash Test"})).json()
        collection_id = collection["id"]

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        # Trash one item
        trash_response = await client.delete(f"/api/media/{seeded_media[0].id}")
        assert trash_response.status_code == 200

        # Collection should only show the non-trashed item
        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        default_items = collection_data["sections"][0]["items"]
        item_ids = [item["media_id"] for item in default_items]
        assert seeded_media[0].id not in item_ids
        assert seeded_media[1].id in item_ids
        assert collection_data["asset_count"] == 1

    async def test_restored_media_reappears_on_collection(self, client, seeded_media):
        """Restoring a trashed media item should make it visible on the collection again."""
        collection = (await client.post("/api/collections", json={"name": "Restore Test"})).json()
        collection_id = collection["id"]

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        # Trash and restore
        await client.delete(f"/api/media/{seeded_media[0].id}")
        restore_response = await client.post(f"/api/trash/{seeded_media[0].id}/restore")
        assert restore_response.status_code == 200

        # Both items should be visible again
        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        item_ids = [item["media_id"] for item in collection_data["sections"][0]["items"]]
        assert seeded_media[0].id in item_ids
        assert seeded_media[1].id in item_ids
        assert collection_data["asset_count"] == 2

    async def test_permanent_delete_removes_collection_items(self, client, seeded_media):
        """Permanently deleting an Asset removes its collection membership."""
        collection = (await client.post("/api/collections", json={"name": "Perm Delete Test"})).json()
        collection_id = collection["id"]

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[2].id]},
        )

        # Trash then permanently delete
        await client.delete(f"/api/media/{seeded_media[2].id}")
        perm_response = await client.delete(f"/api/trash/{seeded_media[2].id}")
        assert perm_response.status_code == 202
        operation_id = perm_response.json()["operation"]["id"]
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            op_response = await client.get(f"/api/delete-operations/{operation_id}")
            if op_response.json()["status"] == "completed":
                break
            await asyncio.sleep(0.05)

        # Collection should have no items
        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        assert collection_data["asset_count"] == 0

    async def test_trashed_media_excluded_from_collection_list_asset_count(self, client, seeded_media):
        """The collections list endpoint should not count trashed media in asset_count."""
        collection = (await client.post("/api/collections", json={"name": "Count Test"})).json()
        collection_id = collection["id"]

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        # Trash one
        await client.delete(f"/api/media/{seeded_media[0].id}")

        # List endpoint should reflect reduced count
        collections = (await client.get("/api/collections")).json()
        this_collection = next(b for b in collections if b["id"] == collection_id)
        assert this_collection["asset_count"] == 1

    async def test_unavailable_source_media_is_hidden_from_collection(self, client, db_session, seeded_media):
        collection = (await client.post("/api/collections", json={"name": "Source Count"})).json()
        await client.post(
            f"/api/collections/{collection['id']}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        async with db_session() as session:
            media = await session.get(MediaItem, seeded_media[0].id)
            media.file_unavailable = True
            await session.commit()

        detail = (await client.get(f"/api/collections/{collection['id']}")).json()
        assert detail["asset_count"] == 1
        assert [item["media_id"] for item in detail["sections"][0]["items"]] == [
            seeded_media[1].id
        ]

        collections = (await client.get("/api/collections")).json()
        summary = next(item for item in collections if item["id"] == collection["id"])
        assert summary["asset_count"] == 1


class TestCollectionDeleteCascade:
    """Tests for collection and section deletion cascading behavior."""

    async def test_delete_collection_removes_sections_and_items(self, client, seeded_media):
        """Deleting a collection should remove its sections and items, but NOT the media."""
        collection = (await client.post("/api/collections", json={"name": "Cascade Collection"})).json()
        collection_id = collection["id"]

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id]},
        )

        delete_response = await client.delete(f"/api/collections/{collection_id}")
        assert delete_response.status_code == 200

        # Collection should be gone
        get_response = await client.get(f"/api/collections/{collection_id}")
        assert get_response.status_code == 404

        # Media should still exist in the library
        media_response = await client.get("/api/media")
        media_ids = [item["id"] for item in media_response.json()["items"]]
        assert seeded_media[0].id in media_ids

    async def test_delete_section_removes_items(self, client, seeded_media, db_session):
        """Deleting a non-default section should remove its items from the collection."""
        collection = (await client.post("/api/collections", json={"name": "Section Del"})).json()
        collection_id = collection["id"]

        section = (await client.post(
            f"/api/collections/{collection_id}/sections",
            json={"name": "Extras"},
        )).json()

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"section_id": section["id"], "media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        delete_response = await client.delete(f"/api/collections/sections/{section['id']}")
        assert delete_response.status_code == 200

        # Section and its items should be gone
        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        section_ids = [s["id"] for s in collection_data["sections"]]
        assert section["id"] not in section_ids

        async with db_session() as session:
            stored_section = await session.scalar(
                select(CollectionSection).where(CollectionSection.id == section["id"])
            )
            assert stored_section is not None
            assert stored_section.deleted_at is not None
            rows = list(await session.scalars(
                select(CollectionAssetItem).where(
                    CollectionAssetItem.collection_section_id == section["id"]
                )
            ))
            assert rows
            assert all(row.deleted_at is not None for row in rows)

        # Media should still exist
        media_response = await client.get("/api/media")
        media_ids = [item["id"] for item in media_response.json()["items"]]
        assert seeded_media[0].id in media_ids

    async def test_delete_default_promotes_next_section(self, client):
        """Deleting the default when other sections exist should promote the next one."""
        collection = (await client.post("/api/collections", json={"name": "Default Promote"})).json()
        collection_id = collection["id"]
        default_section_id = collection["sections"][0]["id"]
        other = (await client.post(
            f"/api/collections/{collection_id}/sections",
            json={"name": "Other"},
        )).json()

        response = await client.delete(f"/api/collections/sections/{default_section_id}")
        assert response.status_code == 200

        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        sections = collection_data["sections"]
        assert len(sections) == 1
        assert sections[0]["id"] == other["id"]
        assert sections[0]["is_default"] is True

    async def test_delete_only_section_recreates_default(self, client):
        """Deleting the only section (default) should leave the collection with a fresh default."""
        collection = (await client.post("/api/collections", json={"name": "Solo"})).json()
        collection_id = collection["id"]
        default_section_id = collection["sections"][0]["id"]

        response = await client.delete(f"/api/collections/sections/{default_section_id}")
        assert response.status_code == 200

        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        sections = collection_data["sections"]
        assert len(sections) == 1
        assert sections[0]["id"] != default_section_id
        assert sections[0]["is_default"] is True


class TestSectionCrud:
    """Tests for section update, rename, collapse, and reorder."""

    async def test_update_section_name(self, client):
        """Renaming a section should persist the new name."""
        collection = (await client.post("/api/collections", json={"name": "Sec Update"})).json()
        section = (await client.post(
            f"/api/collections/{collection['id']}/sections",
            json={"name": "Original"},
        )).json()

        update_response = await client.put(
            f"/api/collections/sections/{section['id']}",
            json={"name": "Renamed Section"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Renamed Section"

        # Verify persisted
        collection_data = (await client.get(f"/api/collections/{collection['id']}")).json()
        updated_section = next(s for s in collection_data["sections"] if s["id"] == section["id"])
        assert updated_section["name"] == "Renamed Section"

    async def test_update_section_collapse(self, client):
        """Toggling is_collapsed should persist."""
        collection = (await client.post("/api/collections", json={"name": "Collapse Test"})).json()
        section = (await client.post(
            f"/api/collections/{collection['id']}/sections",
            json={"name": "Collapsible"},
        )).json()
        assert section["is_collapsed"] is False

        update_response = await client.put(
            f"/api/collections/sections/{section['id']}",
            json={"is_collapsed": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_collapsed"] is True

    async def test_naming_default_section_makes_it_non_default(self, client):
        """Giving a non-empty name to the default section should set is_default=False."""
        collection = (await client.post("/api/collections", json={"name": "Default Name"})).json()
        default_section_id = collection["sections"][0]["id"]
        assert collection["sections"][0]["is_default"] is True

        update_response = await client.put(
            f"/api/collections/sections/{default_section_id}",
            json={"name": "Now Named"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_default"] is False

    async def test_reorder_sections(self, client):
        """Reordering sections should update display_order correctly."""
        collection = (await client.post("/api/collections", json={"name": "Reorder"})).json()
        collection_id = collection["id"]
        default_section_id = collection["sections"][0]["id"]

        sec_a = (await client.post(f"/api/collections/{collection_id}/sections", json={"name": "A"})).json()
        sec_b = (await client.post(f"/api/collections/{collection_id}/sections", json={"name": "B"})).json()

        # Reorder: B, default, A
        reorder_response = await client.post(
            f"/api/collections/{collection_id}/sections/reorder",
            json={"section_ids": [sec_b["id"], default_section_id, sec_a["id"]]},
        )
        assert reorder_response.status_code == 200

        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        section_ids = [s["id"] for s in collection_data["sections"]]
        assert section_ids == [sec_b["id"], default_section_id, sec_a["id"]]


class TestCollectionUpdate:
    """Tests for collection update endpoint with data verification."""

    async def test_rename_collection(self, client):
        """Renaming a collection should persist and return the new name."""
        collection = (await client.post("/api/collections", json={"name": "Old Name"})).json()
        collection_id = collection["id"]

        update_response = await client.put(f"/api/collections/{collection_id}", json={"name": "New Name"})
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "New Name"

        # Verify persisted via GET
        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        assert collection_data["name"] == "New Name"

    async def test_update_collection_preserves_sections_and_items(self, client, seeded_media):
        """Updating a collection should not affect its sections or items."""
        collection = (await client.post("/api/collections", json={"name": "Preserve"})).json()
        collection_id = collection["id"]

        await client.post(
            f"/api/collections/{collection_id}/items",
            json={"media_ids": [seeded_media[0].id]},
        )

        await client.put(f"/api/collections/{collection_id}", json={"name": "Preserved"})

        collection_data = (await client.get(f"/api/collections/{collection_id}")).json()
        assert collection_data["name"] == "Preserved"
        assert collection_data["asset_count"] == 1
        assert len(collection_data["sections"]) == 1


class TestCollection404s:
    """Tests for proper 404 responses on invalid IDs."""

    async def test_get_nonexistent_collection(self, client):
        response = await client.get("/api/collections/999999")
        assert response.status_code == 404

    async def test_update_nonexistent_collection(self, client):
        response = await client.put("/api/collections/999999", json={"name": "Nope"})
        assert response.status_code == 404

    async def test_delete_nonexistent_collection(self, client):
        response = await client.delete("/api/collections/999999")
        assert response.status_code == 404

    async def test_add_items_to_nonexistent_collection(self, client):
        response = await client.post("/api/collections/999999/items", json={"media_ids": [1]})
        assert response.status_code == 404

    async def test_update_nonexistent_section(self, client):
        response = await client.put("/api/collections/sections/999999", json={"name": "Nope"})
        assert response.status_code == 404

    async def test_delete_nonexistent_section(self, client):
        response = await client.delete("/api/collections/sections/999999")
        assert response.status_code == 404

    async def test_remove_item_from_nonexistent_section(self, client):
        response = await client.delete("/api/collections/sections/999999/items/1")
        assert response.status_code == 404

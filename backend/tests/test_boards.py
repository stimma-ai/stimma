"""
Tests for the boards API endpoints.
"""

import asyncio
from unittest.mock import patch

import pytest

from tests.helpers.media import create_test_media
from tests.helpers.ws import MockWebSocketManager


@pytest.fixture
async def seeded_media(db_session):
    async with db_session() as session:
        items = await create_test_media(session, count=3)
        return items


class TestBoardsApi:
    async def test_create_and_list_boards(self, client):
        create_response = await client.post("/api/boards", json={"name": "Moodboard"})
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "Moodboard"
        assert len(created["sections"]) == 1
        assert created["sections"][0]["is_default"] is True
        assert created["sections"][0]["name"] is None

        list_response = await client.get("/api/boards")
        assert list_response.status_code == 200
        boards = list_response.json()
        assert any(board["id"] == created["id"] for board in boards)

    async def test_add_items_create_section_move_and_remove(self, client, seeded_media):
        board = (await client.post("/api/boards", json={"name": "Working Set"})).json()
        board_id = board["id"]
        default_section_id = board["sections"][0]["id"]

        add_response = await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )
        assert add_response.status_code == 200
        assert add_response.json()["added"] == 2

        section_response = await client.post(
            f"/api/boards/{board_id}/sections",
            json={"name": "References"},
        )
        assert section_response.status_code == 200
        section = section_response.json()
        assert section["name"] == "References"

        move_response = await client.post(
            f"/api/boards/{board_id}/items/move",
            json={
                "media_id": seeded_media[1].id,
                "from_section_id": default_section_id,
                "to_section_id": section["id"],
                "target_index": 0,
            },
        )
        assert move_response.status_code == 200

        board_response = await client.get(f"/api/boards/{board_id}")
        assert board_response.status_code == 200
        payload = board_response.json()
        default_section = next(item for item in payload["sections"] if item["id"] == default_section_id)
        reference_section = next(item for item in payload["sections"] if item["id"] == section["id"])
        assert [item["id"] for item in default_section["items"]] == [seeded_media[0].id]
        assert [item["id"] for item in reference_section["items"]] == [seeded_media[1].id]

        remove_response = await client.delete(
            f"/api/boards/sections/{section['id']}/items/{seeded_media[1].id}"
        )
        assert remove_response.status_code == 200

        updated = (await client.get(f"/api/boards/{board_id}")).json()
        assert not any(item["id"] == section["id"] for item in updated["sections"])

    async def test_move_item_into_section_where_it_already_exists_reorders_without_duplicate(self, client, seeded_media):
        board = (await client.post("/api/boards", json={"name": "Working Set"})).json()
        board_id = board["id"]
        default_section_id = board["sections"][0]["id"]

        section_response = await client.post(
            f"/api/boards/{board_id}/sections",
            json={"name": "References"},
        )
        assert section_response.status_code == 200
        target_section_id = section_response.json()["id"]

        add_default = await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )
        assert add_default.status_code == 200

        add_target = await client.post(
            f"/api/boards/{board_id}/items",
            json={"section_id": target_section_id, "media_ids": [seeded_media[2].id, seeded_media[1].id]},
        )
        assert add_target.status_code == 200

        move_response = await client.post(
            f"/api/boards/{board_id}/items/move",
            json={
                "media_id": seeded_media[1].id,
                "from_section_id": default_section_id,
                "to_section_id": target_section_id,
                "target_index": 0,
            },
        )
        assert move_response.status_code == 200

        board_response = await client.get(f"/api/boards/{board_id}")
        assert board_response.status_code == 200
        payload = board_response.json()
        default_section = next(item for item in payload["sections"] if item["id"] == default_section_id)
        target_section = next(item for item in payload["sections"] if item["id"] == target_section_id)

        assert [item["id"] for item in default_section["items"]] == [seeded_media[0].id]
        assert [item["id"] for item in target_section["items"]] == [seeded_media[1].id, seeded_media[2].id]

    async def test_board_websocket_events(self, client):
        mock_ws = MockWebSocketManager()
        with patch("routes.boards.ws_manager", mock_ws):
            create_response = await client.post("/api/boards", json={"name": "Events"})
            assert create_response.status_code == 200
            board_id = create_response.json()["id"]
            mock_ws.assert_broadcast("board_created")

            update_response = await client.put(f"/api/boards/{board_id}", json={"name": "Renamed"})
            assert update_response.status_code == 200
            mock_ws.assert_broadcast("board_updated")

            delete_response = await client.delete(f"/api/boards/{board_id}")
            assert delete_response.status_code == 200
            mock_ws.assert_broadcast("board_deleted", {"board_id": board_id})


class TestBoardTrashInteractions:
    """Tests for how boards interact with trashed/deleted media."""

    async def test_trashed_media_hidden_from_board(self, client, seeded_media):
        """Trashing a media item should hide it from board views, but not remove the BoardItem row."""
        board = (await client.post("/api/boards", json={"name": "Trash Test"})).json()
        board_id = board["id"]

        await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        # Trash one item
        trash_response = await client.delete(f"/api/media/{seeded_media[0].id}")
        assert trash_response.status_code == 200

        # Board should only show the non-trashed item
        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        default_items = board_data["sections"][0]["items"]
        item_ids = [item["id"] for item in default_items]
        assert seeded_media[0].id not in item_ids
        assert seeded_media[1].id in item_ids
        assert board_data["asset_count"] == 1

    async def test_restored_media_reappears_on_board(self, client, seeded_media):
        """Restoring a trashed media item should make it visible on the board again."""
        board = (await client.post("/api/boards", json={"name": "Restore Test"})).json()
        board_id = board["id"]

        await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        # Trash and restore
        await client.delete(f"/api/media/{seeded_media[0].id}")
        restore_response = await client.post(f"/api/trash/{seeded_media[0].id}/restore")
        assert restore_response.status_code == 200

        # Both items should be visible again
        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        item_ids = [item["id"] for item in board_data["sections"][0]["items"]]
        assert seeded_media[0].id in item_ids
        assert seeded_media[1].id in item_ids
        assert board_data["asset_count"] == 2

    async def test_permanent_delete_removes_board_items(self, client, seeded_media):
        """Permanently deleting media should CASCADE-remove BoardItem rows."""
        board = (await client.post("/api/boards", json={"name": "Perm Delete Test"})).json()
        board_id = board["id"]

        await client.post(
            f"/api/boards/{board_id}/items",
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

        # Board should have no items
        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        assert board_data["asset_count"] == 0

    async def test_trashed_media_excluded_from_board_list_asset_count(self, client, seeded_media):
        """The boards list endpoint should not count trashed media in asset_count."""
        board = (await client.post("/api/boards", json={"name": "Count Test"})).json()
        board_id = board["id"]

        await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        # Trash one
        await client.delete(f"/api/media/{seeded_media[0].id}")

        # List endpoint should reflect reduced count
        boards = (await client.get("/api/boards")).json()
        this_board = next(b for b in boards if b["id"] == board_id)
        assert this_board["asset_count"] == 1


class TestBoardDeleteCascade:
    """Tests for board and section deletion cascading behavior."""

    async def test_delete_board_removes_sections_and_items(self, client, seeded_media):
        """Deleting a board should remove its sections and items, but NOT the media."""
        board = (await client.post("/api/boards", json={"name": "Cascade Board"})).json()
        board_id = board["id"]

        await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id]},
        )

        delete_response = await client.delete(f"/api/boards/{board_id}")
        assert delete_response.status_code == 200

        # Board should be gone
        get_response = await client.get(f"/api/boards/{board_id}")
        assert get_response.status_code == 404

        # Media should still exist in the library
        media_response = await client.get("/api/media")
        media_ids = [item["id"] for item in media_response.json()["items"]]
        assert seeded_media[0].id in media_ids

    async def test_delete_section_removes_items(self, client, seeded_media):
        """Deleting a non-default section should remove its items from the board."""
        board = (await client.post("/api/boards", json={"name": "Section Del"})).json()
        board_id = board["id"]

        section = (await client.post(
            f"/api/boards/{board_id}/sections",
            json={"name": "Extras"},
        )).json()

        await client.post(
            f"/api/boards/{board_id}/items",
            json={"section_id": section["id"], "media_ids": [seeded_media[0].id, seeded_media[1].id]},
        )

        delete_response = await client.delete(f"/api/boards/sections/{section['id']}")
        assert delete_response.status_code == 200

        # Section and its items should be gone
        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        section_ids = [s["id"] for s in board_data["sections"]]
        assert section["id"] not in section_ids

        # Media should still exist
        media_response = await client.get("/api/media")
        media_ids = [item["id"] for item in media_response.json()["items"]]
        assert seeded_media[0].id in media_ids

    async def test_delete_default_promotes_next_section(self, client):
        """Deleting the default when other sections exist should promote the next one."""
        board = (await client.post("/api/boards", json={"name": "Default Promote"})).json()
        board_id = board["id"]
        default_section_id = board["sections"][0]["id"]
        other = (await client.post(
            f"/api/boards/{board_id}/sections",
            json={"name": "Other"},
        )).json()

        response = await client.delete(f"/api/boards/sections/{default_section_id}")
        assert response.status_code == 200

        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        sections = board_data["sections"]
        assert len(sections) == 1
        assert sections[0]["id"] == other["id"]
        assert sections[0]["is_default"] is True

    async def test_delete_only_section_recreates_default(self, client):
        """Deleting the only section (default) should leave the board with a fresh default."""
        board = (await client.post("/api/boards", json={"name": "Solo"})).json()
        board_id = board["id"]
        default_section_id = board["sections"][0]["id"]

        response = await client.delete(f"/api/boards/sections/{default_section_id}")
        assert response.status_code == 200

        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        sections = board_data["sections"]
        assert len(sections) == 1
        assert sections[0]["id"] != default_section_id
        assert sections[0]["is_default"] is True


class TestSectionCrud:
    """Tests for section update, rename, collapse, and reorder."""

    async def test_update_section_name(self, client):
        """Renaming a section should persist the new name."""
        board = (await client.post("/api/boards", json={"name": "Sec Update"})).json()
        section = (await client.post(
            f"/api/boards/{board['id']}/sections",
            json={"name": "Original"},
        )).json()

        update_response = await client.put(
            f"/api/boards/sections/{section['id']}",
            json={"name": "Renamed Section"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Renamed Section"

        # Verify persisted
        board_data = (await client.get(f"/api/boards/{board['id']}")).json()
        updated_section = next(s for s in board_data["sections"] if s["id"] == section["id"])
        assert updated_section["name"] == "Renamed Section"

    async def test_update_section_collapse(self, client):
        """Toggling is_collapsed should persist."""
        board = (await client.post("/api/boards", json={"name": "Collapse Test"})).json()
        section = (await client.post(
            f"/api/boards/{board['id']}/sections",
            json={"name": "Collapsible"},
        )).json()
        assert section["is_collapsed"] is False

        update_response = await client.put(
            f"/api/boards/sections/{section['id']}",
            json={"is_collapsed": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_collapsed"] is True

    async def test_naming_default_section_makes_it_non_default(self, client):
        """Giving a non-empty name to the default section should set is_default=False."""
        board = (await client.post("/api/boards", json={"name": "Default Name"})).json()
        default_section_id = board["sections"][0]["id"]
        assert board["sections"][0]["is_default"] is True

        update_response = await client.put(
            f"/api/boards/sections/{default_section_id}",
            json={"name": "Now Named"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_default"] is False

    async def test_reorder_sections(self, client):
        """Reordering sections should update display_order correctly."""
        board = (await client.post("/api/boards", json={"name": "Reorder"})).json()
        board_id = board["id"]
        default_section_id = board["sections"][0]["id"]

        sec_a = (await client.post(f"/api/boards/{board_id}/sections", json={"name": "A"})).json()
        sec_b = (await client.post(f"/api/boards/{board_id}/sections", json={"name": "B"})).json()

        # Reorder: B, default, A
        reorder_response = await client.post(
            f"/api/boards/{board_id}/sections/reorder",
            json={"section_ids": [sec_b["id"], default_section_id, sec_a["id"]]},
        )
        assert reorder_response.status_code == 200

        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        section_ids = [s["id"] for s in board_data["sections"]]
        assert section_ids == [sec_b["id"], default_section_id, sec_a["id"]]


class TestBoardUpdate:
    """Tests for board update endpoint with data verification."""

    async def test_rename_board(self, client):
        """Renaming a board should persist and return the new name."""
        board = (await client.post("/api/boards", json={"name": "Old Name"})).json()
        board_id = board["id"]

        update_response = await client.put(f"/api/boards/{board_id}", json={"name": "New Name"})
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "New Name"

        # Verify persisted via GET
        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        assert board_data["name"] == "New Name"

    async def test_update_board_preserves_sections_and_items(self, client, seeded_media):
        """Updating a board should not affect its sections or items."""
        board = (await client.post("/api/boards", json={"name": "Preserve"})).json()
        board_id = board["id"]

        await client.post(
            f"/api/boards/{board_id}/items",
            json={"media_ids": [seeded_media[0].id]},
        )

        await client.put(f"/api/boards/{board_id}", json={"name": "Preserved"})

        board_data = (await client.get(f"/api/boards/{board_id}")).json()
        assert board_data["name"] == "Preserved"
        assert board_data["asset_count"] == 1
        assert len(board_data["sections"]) == 1


class TestBoard404s:
    """Tests for proper 404 responses on invalid IDs."""

    async def test_get_nonexistent_board(self, client):
        response = await client.get("/api/boards/999999")
        assert response.status_code == 404

    async def test_update_nonexistent_board(self, client):
        response = await client.put("/api/boards/999999", json={"name": "Nope"})
        assert response.status_code == 404

    async def test_delete_nonexistent_board(self, client):
        response = await client.delete("/api/boards/999999")
        assert response.status_code == 404

    async def test_add_items_to_nonexistent_board(self, client):
        response = await client.post("/api/boards/999999/items", json={"media_ids": [1]})
        assert response.status_code == 404

    async def test_update_nonexistent_section(self, client):
        response = await client.put("/api/boards/sections/999999", json={"name": "Nope"})
        assert response.status_code == 404

    async def test_delete_nonexistent_section(self, client):
        response = await client.delete("/api/boards/sections/999999")
        assert response.status_code == 404

    async def test_remove_item_from_nonexistent_section(self, client):
        response = await client.delete("/api/boards/sections/999999/items/1")
        assert response.status_code == 404

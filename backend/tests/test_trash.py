"""
Tests for the trash API endpoints.

Tests cover:
- Soft delete (trash) single and bulk
- Viewing trash contents
- Restore from trash single and bulk
- Permanent delete single, bulk, and empty trash
- WebSocket events for all trash operations
"""

import asyncio
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from unittest.mock import patch

from database import (
    Chat,
    ChatItem,
    DeleteOperation,
    DeleteOperationItem,
    GenerationJob,
    ManagedArtifact,
    MediaItem,
    MediaLineage,
    MediaThumbnailCache,
    Tool,
)
from tests.helpers.media import create_test_media, create_media_item
from tests.helpers.ws import MockWebSocketManager


async def wait_for_delete_operation(client: AsyncClient, operation_id: int, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/delete-operations/{operation_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] in {"completed", "failed"}:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(f"Delete operation {operation_id} did not finish in time")


class TestSoftDelete:
    """Tests for soft delete (trash) operations."""

    async def test_soft_delete_single(self, client: AsyncClient, seeded_media):
        """Test soft deleting a single media item."""
        media_id = seeded_media[0].id

        response = await client.delete(f"/api/media/{media_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert "trash" in data["message"].lower()

    async def test_soft_delete_nonexistent(self, client: AsyncClient):
        """Test soft deleting a media item that doesn't exist."""
        response = await client.delete("/api/media/99999")
        assert response.status_code == 404

    async def test_soft_delete_already_deleted(self, client: AsyncClient, seeded_media):
        """Test soft deleting an already deleted item returns error."""
        media_id = seeded_media[0].id

        # Delete first time
        await client.delete(f"/api/media/{media_id}")

        # Try to delete again
        response = await client.delete(f"/api/media/{media_id}")
        assert response.status_code == 400
        assert "already" in response.json()["detail"].lower()

    async def test_soft_delete_removes_from_listing(self, client: AsyncClient, seeded_media):
        """Test that soft deleted items don't appear in media listing."""
        media_id = seeded_media[0].id

        # Get initial count
        initial_response = await client.get("/api/media")
        initial_count = initial_response.json()["total"]

        # Delete
        await client.delete(f"/api/media/{media_id}")

        # Verify removed from listing
        after_response = await client.get("/api/media")
        assert after_response.json()["total"] == initial_count - 1

        item_ids = [item["id"] for item in after_response.json()["items"]]
        assert media_id not in item_ids

    async def test_bulk_soft_delete(self, client: AsyncClient, seeded_media):
        """Test bulk soft delete of multiple items."""
        media_ids = [m.id for m in seeded_media[:3]]

        response = await client.post(
            "/api/media/batch/delete",
            json={"media_ids": media_ids}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["deleted"] == 3
        assert data["total"] == 3
        assert data["errors"] == []

    async def test_bulk_soft_delete_partial_success(self, client: AsyncClient, seeded_media):
        """Test bulk delete with some invalid IDs."""
        valid_id = seeded_media[0].id
        invalid_id = 99999

        response = await client.post(
            "/api/media/batch/delete",
            json={"media_ids": [valid_id, invalid_id]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["deleted"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["media_id"] == invalid_id


class TestTrashListing:
    """Tests for GET /api/trash endpoint."""

    async def test_trash_empty(self, client: AsyncClient):
        """Test listing trash when empty."""
        # Empty trash first (may have items from previous tests)
        delete_response = await client.delete("/api/trash")
        operation = delete_response.json().get("operation")
        if operation:
            await wait_for_delete_operation(client, operation["id"])

        response = await client.get("/api/trash")
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_trash_with_items(self, client: AsyncClient, seeded_media):
        """Test listing trash with deleted items."""
        media_id = seeded_media[0].id

        # Delete item
        await client.delete(f"/api/media/{media_id}")

        # Check trash
        response = await client.get("/api/trash")
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        item_ids = [item["id"] for item in data["items"]]
        assert media_id in item_ids

    async def test_trash_pagination(self, client: AsyncClient, seeded_media):
        """Test trash listing pagination."""
        # Delete multiple items
        for media in seeded_media[:4]:
            await client.delete(f"/api/media/{media.id}")

        # Get first page
        response = await client.get("/api/trash", params={"page": 1, "page_size": 2})
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] >= 4


class TestRestore:
    """Tests for restore from trash operations."""

    async def test_restore_single(self, client: AsyncClient, seeded_media):
        """Test restoring a single item from trash."""
        media_id = seeded_media[0].id

        # Delete first
        await client.delete(f"/api/media/{media_id}")

        # Verify in trash
        trash_response = await client.get("/api/trash")
        assert media_id in [item["id"] for item in trash_response.json()["items"]]

        # Restore
        response = await client.post(f"/api/trash/{media_id}/restore")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"

        # Verify back in media listing
        media_response = await client.get("/api/media")
        assert media_id in [item["id"] for item in media_response.json()["items"]]

        # Verify not in trash
        trash_response2 = await client.get("/api/trash")
        assert media_id not in [item["id"] for item in trash_response2.json()["items"]]

    async def test_restore_nonexistent(self, client: AsyncClient):
        """Test restoring a media item that doesn't exist."""
        response = await client.post("/api/trash/99999/restore")
        assert response.status_code == 404

    async def test_restore_not_deleted(self, client: AsyncClient, seeded_media):
        """Test restoring an item that's not in trash."""
        media_id = seeded_media[0].id

        response = await client.post(f"/api/trash/{media_id}/restore")
        assert response.status_code == 400
        assert "not deleted" in response.json()["detail"].lower()

    async def test_bulk_restore(self, client: AsyncClient, seeded_media):
        """Test bulk restore from trash."""
        media_ids = [m.id for m in seeded_media[:3]]

        # Delete all
        await client.post("/api/media/batch/delete", json={"media_ids": media_ids})

        # Restore all
        response = await client.post(
            "/api/trash/batch/restore",
            json={"media_ids": media_ids}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["restored"] == 3

        # Verify all back in listing
        media_response = await client.get("/api/media")
        listed_ids = [item["id"] for item in media_response.json()["items"]]
        for mid in media_ids:
            assert mid in listed_ids

    async def test_bulk_restore_partial_success(self, client: AsyncClient, seeded_media):
        """Test bulk restore with some items not in trash."""
        deleted_id = seeded_media[0].id
        not_deleted_id = seeded_media[1].id

        # Only delete one
        await client.delete(f"/api/media/{deleted_id}")

        # Try to restore both
        response = await client.post(
            "/api/trash/batch/restore",
            json={"media_ids": [deleted_id, not_deleted_id]}
        )
        assert response.status_code == 200

        data = response.json()
        assert data["restored"] == 1
        assert len(data["errors"]) == 1


class TestPermanentDelete:
    """Tests for permanent delete operations."""

    async def test_permanent_delete_single(self, client: AsyncClient, seeded_media):
        """Test permanently deleting a single item from trash."""
        media_id = seeded_media[0].id

        # Soft delete first
        await client.delete(f"/api/media/{media_id}")

        # Permanently delete
        response = await client.delete(f"/api/trash/{media_id}")
        assert response.status_code == 202

        data = response.json()
        assert data["status"] == "accepted"
        operation = await wait_for_delete_operation(client, data["operation"]["id"])
        assert operation["status"] == "completed"

        # Verify gone from trash
        trash_response = await client.get("/api/trash")
        assert media_id not in [item["id"] for item in trash_response.json()["items"]]

        # Verify can't fetch directly
        get_response = await client.get(f"/api/media/{media_id}")
        assert get_response.status_code == 404

    async def test_media_deletion_status_endpoint(
        self, client: AsyncClient, seeded_media
    ):
        media_id = seeded_media[0].id
        live = await client.get(f"/api/deletion-status/media/{media_id}")
        assert live.json()["status"] == "live"

        await client.delete(f"/api/media/{media_id}")
        trashed = await client.get(f"/api/deletion-status/media/{media_id}")
        assert trashed.json()["status"] == "trashed"

        await client.post(f"/api/trash/{media_id}/restore")

    async def test_successful_delete_scrubs_work_manifest(
        self, client: AsyncClient, db_session, seeded_media
    ):
        """Completed operations retain aggregate progress, not deleted locators."""
        media_id = seeded_media[0].id
        await client.delete(f"/api/media/{media_id}")
        response = await client.delete(f"/api/trash/{media_id}")
        operation_id = response.json()["operation"]["id"]
        operation = await wait_for_delete_operation(client, operation_id)
        assert operation["status"] == "completed"

        async with db_session() as session:
            rows = (
                await session.execute(
                    select(DeleteOperationItem).where(
                        DeleteOperationItem.operation_id == operation_id
                    )
                )
            ).scalars().all()
            assert rows == []

    async def test_artifact_delete_failure_remains_failed_and_retryable(
        self, client: AsyncClient, db_session, seeded_media
    ):
        media_id = seeded_media[0].id
        await client.delete(f"/api/media/{media_id}")

        with patch(
            "delete_operations.TrashService.permanently_delete",
            side_effect=PermissionError("sensitive path must not enter operation error"),
        ):
            response = await client.delete(f"/api/trash/{media_id}")
            operation_id = response.json()["operation"]["id"]
            operation = await wait_for_delete_operation(client, operation_id)

        assert operation["status"] == "failed"
        assert operation["deleted_items"] == 0
        assert operation["failed_items"] == 1

        async with db_session() as session:
            # Logical deletion committed before unlink, so a rollback/crash can
            # never resurrect a live row pointing at missing bytes.
            assert await session.get(MediaItem, media_id) is None
            row = await session.get(DeleteOperationItem, (operation_id, media_id))
            assert row is not None
            assert row.state == "failed"
            assert row.last_error == "permanent deletion failed"
            assert "sensitive path" not in row.last_error

        retried = await client.post(
            f"/api/delete-operations/{operation_id}/retry"
        )
        assert retried.status_code == 202
        completed = await wait_for_delete_operation(client, operation_id)
        assert completed["status"] == "completed"

    async def test_thumbnail_failure_preserves_cache_locator_for_retry(
        self, client: AsyncClient, db_session, seeded_media, tmp_path
    ):
        media_id = seeded_media[0].id
        thumbnail = tmp_path / "thumb.webp"
        thumbnail.write_bytes(b"thumb")
        async with db_session() as session:
            session.add(MediaThumbnailCache(media_id=media_id, cache_path=str(thumbnail)))
            await session.commit()

        await client.delete(f"/api/media/{media_id}")
        with patch("delete_operations.Path.unlink", side_effect=PermissionError("denied")):
            response = await client.delete(f"/api/trash/{media_id}")
            operation = await wait_for_delete_operation(
                client, response.json()["operation"]["id"]
            )

        assert operation["status"] == "failed"
        async with db_session() as session:
            assert await session.get(MediaThumbnailCache, (media_id, str(thumbnail))) is None
            assert await session.get(MediaItem, media_id) is None
            manifest = await session.get(
                DeleteOperationItem, (operation["id"], media_id)
            )
            assert str(thumbnail) in json.loads(manifest.thumbnail_paths)

        retried = await client.post(
            f"/api/delete-operations/{operation['id']}/retry"
        )
        assert retried.status_code == 202
        completed = await wait_for_delete_operation(client, operation["id"])
        assert completed["status"] == "completed"
        assert not thumbnail.exists()

    async def test_legacy_editor_dependency_blocks_source_deletion(
        self, client: AsyncClient, db_session, tmp_path
    ):
        async with db_session() as session:
            source = await create_media_item(session, file_path=tmp_path / "source.png")
            edited = await create_media_item(session, file_path=tmp_path / "edited.png")
            edited.has_editor_sidecar = True
            sidecar = tmp_path / "edited.png.stimmaedit.json"
            sidecar.write_text(
                json.dumps({
                    "version": 1,
                    "source_media_id": source.id,
                    "project": {"imageDataUrl": "data:image/png;base64,c2VjcmV0"},
                }),
                encoding="utf-8",
            )
            source_artifact = tmp_path / "source-proxy.webp"
            source_artifact.write_bytes(b"proxy")
            session.add(
                ManagedArtifact(
                    owner_kind="media",
                    owner_id=str(source.id),
                    media_id=source.id,
                    artifact_kind="proxy",
                    locator=str(source_artifact),
                )
            )
            await session.commit()
            source_id = source.id

        await client.delete(f"/api/media/{source_id}")
        response = await client.delete(f"/api/trash/{source_id}")
        operation = await wait_for_delete_operation(
            client, response.json()["operation"]["id"]
        )

        assert operation["status"] == "failed"
        async with db_session() as session:
            assert await session.get(MediaItem, source_id) is not None
        assert sidecar.exists()
        assert source_artifact.exists()
        async with db_session() as session:
            artifact = await session.scalar(
                select(ManagedArtifact).where(
                    ManagedArtifact.media_id == source_id
                )
            )
            assert artifact.owner_kind == "media"

        # Module-scoped DB fixtures intentionally persist across this file; put
        # the blocked source back so later empty-trash/count tests stay isolated.
        # Restore correctly refuses while a durable deletion remains active;
        # cancel the synthetic failed operation directly for fixture cleanup.
        restore = await client.post(f"/api/trash/{source_id}/restore")
        assert restore.status_code == 409
        async with db_session() as session:
            source = await session.get(MediaItem, source_id)
            source.deletion_pending_at = None
            await session.execute(
                delete(DeleteOperationItem).where(
                    DeleteOperationItem.operation_id == operation["id"]
                )
            )
            failed_operation = await session.get(DeleteOperation, operation["id"])
            await session.delete(failed_operation)
            await session.commit()
        restore = await client.post(f"/api/trash/{source_id}/restore")
        assert restore.status_code == 200

    async def test_deleting_source_and_dependent_edit_together_succeeds(
        self, client: AsyncClient, db_session, tmp_path
    ):
        async with db_session() as session:
            source = await create_media_item(session, file_path=tmp_path / "source-all.png")
            edited = await create_media_item(session, file_path=tmp_path / "edited-all.png")
            edited.has_editor_sidecar = True
            sidecar = tmp_path / "edited-all.png.stimmaedit.json"
            sidecar.write_text(
                json.dumps({
                    "version": 1,
                    "source_media_id": source.id,
                    "project": {"imageDataUrl": "data:image/png;base64,c2VjcmV0"},
                }),
                encoding="utf-8",
            )
            await session.commit()
            media_ids = [source.id, edited.id]

        await client.post("/api/media/batch/delete", json={"media_ids": media_ids})
        response = await client.post(
            "/api/trash/batch/delete", json={"media_ids": media_ids}
        )
        operation = await wait_for_delete_operation(
            client, response.json()["operation"]["id"]
        )

        assert operation["status"] == "completed"
        assert operation["deleted_items"] == 2
        assert not sidecar.exists()

    async def test_permanent_delete_not_in_trash(self, client: AsyncClient, seeded_media):
        """Test permanently deleting an item not in trash fails."""
        media_id = seeded_media[0].id

        response = await client.delete(f"/api/trash/{media_id}")
        assert response.status_code == 400
        assert "not in trash" in response.json()["detail"].lower()

    async def test_permanent_delete_nonexistent(self, client: AsyncClient):
        """Test permanently deleting nonexistent item."""
        response = await client.delete("/api/trash/99999")
        assert response.status_code == 404

    async def test_bulk_permanent_delete(self, client: AsyncClient, seeded_media):
        """Test bulk permanent delete from trash."""
        media_ids = [m.id for m in seeded_media[:3]]

        # Soft delete all
        await client.post("/api/media/batch/delete", json={"media_ids": media_ids})

        # Permanently delete all
        response = await client.post(
            "/api/trash/batch/delete",
            json={"media_ids": media_ids}
        )
        assert response.status_code == 202

        data = response.json()
        assert data["status"] == "accepted"
        assert data["accepted"] == 3
        operation = await wait_for_delete_operation(client, data["operation"]["id"])
        assert operation["deleted_items"] == 3

        # Verify trash is empty of these items
        trash_response = await client.get("/api/trash")
        trash_ids = [item["id"] for item in trash_response.json()["items"]]
        for mid in media_ids:
            assert mid not in trash_ids

    async def test_empty_trash(self, client: AsyncClient, seeded_media):
        """Test emptying entire trash."""
        media_ids = [m.id for m in seeded_media[:3]]

        # Soft delete all
        await client.post("/api/media/batch/delete", json={"media_ids": media_ids})

        # Verify items in trash
        trash_before = await client.get("/api/trash")
        assert trash_before.json()["total"] >= 3

        # Empty trash
        response = await client.delete("/api/trash")
        assert response.status_code == 202

        data = response.json()
        assert data["status"] == "accepted"
        operation = await wait_for_delete_operation(client, data["operation"]["id"])
        assert operation["deleted_items"] >= 3

        # Verify trash is empty
        trash_after = await client.get("/api/trash")
        assert trash_after.json()["total"] == 0

    async def test_empty_already_empty_trash(self, client: AsyncClient):
        """Test emptying an already empty trash."""
        response = await client.delete("/api/trash")
        assert response.status_code == 202

        data = response.json()
        assert data["accepted"] == 0
        assert "empty" in data["message"].lower()

    async def test_permanent_delete_drops_generation_job(self, client: AsyncClient, db_session, tmp_path):
        """Permanent delete must remove the GenerationJob row so the prompt/params
        leave no trace and don't show up as a ghost tile in the queue.

        Also verifies that a sibling batch job whose ``batch_output_set_id`` points
        at the deleted aggregator set keeps its own row but has the dangling
        reference nulled out.
        """
        async with db_session() as session:
            result_media = await create_media_item(session, file_path=tmp_path / "gen.png")
            set_media = await create_media_item(session, file_path=tmp_path / "batch.stimmaset.json")

            session.add(GenerationJob(
                status="completed",
                task_type="text-to-image",
                generator_type="test",
                generator_name="test",
                model_name="test",
                parameters=json.dumps({"prompt": "top secret prompt", "seed": 42}),
                folder_path=str(tmp_path),
                result_media_id=result_media.id,
            ))
            # Sibling in same batch, points at the set as its aggregator output.
            sibling = GenerationJob(
                status="completed",
                task_type="text-to-image",
                generator_type="test",
                generator_name="test",
                model_name="test",
                parameters=json.dumps({"prompt": "sibling"}),
                folder_path=str(tmp_path),
                result_media_id=None,
                batch_id="batch-1",
                batch_output_set_id=set_media.id,
            )
            session.add(sibling)
            await session.commit()
            await session.refresh(sibling)
            sibling_id = sibling.id

        # Permanently delete both the generated image and the aggregator set.
        await client.delete(f"/api/media/{result_media.id}")
        await client.delete(f"/api/media/{set_media.id}")
        op_response = await client.post(
            "/api/trash/batch/delete",
            json={"media_ids": [result_media.id, set_media.id]},
        )
        assert op_response.status_code == 202
        operation = await wait_for_delete_operation(client, op_response.json()["operation"]["id"])
        assert operation["status"] == "completed"

        async with db_session() as session:
            # Job row tied to the deleted result must be gone — params included.
            remaining = (
                await session.execute(
                    select(GenerationJob).where(GenerationJob.result_media_id == result_media.id)
                )
            ).scalars().all()
            assert remaining == []

            # Sibling batch job survives but its dangling aggregator ref is nulled.
            sibling_refreshed = await session.get(GenerationJob, sibling_id)
            assert sibling_refreshed is not None
            assert sibling_refreshed.batch_output_set_id is None


class TestTrashWebSocketEvents:
    """Tests for WebSocket events emitted during trash operations."""

    async def test_soft_delete_broadcasts_media_deleted(self, client: AsyncClient, seeded_media):
        """Test that soft delete broadcasts media_deleted event."""
        media_id = seeded_media[0].id
        mock_ws = MockWebSocketManager()

        with patch("routes.trash.ws_manager", mock_ws):
            response = await client.delete(f"/api/media/{media_id}")
            assert response.status_code == 200

            events = mock_ws.get_broadcasts("media_deleted")
            assert len(events) >= 1
            assert events[0][1]["media_id"] == media_id

    async def test_bulk_delete_broadcasts_media_bulk_deleted(self, client: AsyncClient, seeded_media):
        """Test that bulk soft delete broadcasts media_bulk_deleted event."""
        media_ids = [m.id for m in seeded_media[:2]]
        mock_ws = MockWebSocketManager()

        with patch("routes.trash.ws_manager", mock_ws):
            response = await client.post(
                "/api/media/batch/delete",
                json={"media_ids": media_ids}
            )
            assert response.status_code == 200

            events = mock_ws.get_broadcasts("media_bulk_deleted")
            assert len(events) >= 1
            assert events[0][1]["count"] == 2

    async def test_restore_broadcasts_media_restored(self, client: AsyncClient, seeded_media):
        """Test that restore broadcasts media_restored event."""
        media_id = seeded_media[0].id

        # Soft delete first
        await client.delete(f"/api/media/{media_id}")

        mock_ws = MockWebSocketManager()

        with patch("routes.trash.ws_manager", mock_ws):
            response = await client.post(f"/api/trash/{media_id}/restore")
            assert response.status_code == 200

            events = mock_ws.get_broadcasts("media_restored")
            assert len(events) >= 1
            assert events[0][1]["media_id"] == media_id

    async def test_permanent_delete_broadcasts_event(self, client: AsyncClient, seeded_media):
        """Test that permanent delete broadcasts media_permanently_deleted event."""
        media_id = seeded_media[0].id

        # Soft delete first
        await client.delete(f"/api/media/{media_id}")

        mock_ws = MockWebSocketManager()

        with patch("delete_operations.ws_manager", mock_ws):
            response = await client.delete(f"/api/trash/{media_id}")
            assert response.status_code == 202
            operation = await wait_for_delete_operation(client, response.json()["operation"]["id"])
            assert operation["status"] == "completed"

            events = mock_ws.get_broadcasts("media_permanently_deleted")
            assert len(events) >= 1
            assert media_id in events[0][1]["media_ids"]

    async def test_bulk_permanent_delete_broadcasts_event(self, client: AsyncClient, seeded_media):
        """Test that bulk permanent delete broadcasts media_permanently_deleted event."""
        media_ids = [m.id for m in seeded_media[:2]]

        # Soft delete first
        await client.post("/api/media/batch/delete", json={"media_ids": media_ids})

        mock_ws = MockWebSocketManager()

        with patch("delete_operations.ws_manager", mock_ws):
            response = await client.post(
                "/api/trash/batch/delete",
                json={"media_ids": media_ids}
            )
            assert response.status_code == 202
            operation = await wait_for_delete_operation(client, response.json()["operation"]["id"])
            assert operation["status"] == "completed"

            events = mock_ws.get_broadcasts("media_permanently_deleted")
            assert len(events) >= 1
            assert events[0][1]["count"] == 2

    async def test_empty_trash_broadcasts_event(self, client: AsyncClient, seeded_media):
        """Test that empty trash broadcasts trash_emptied event."""
        media_ids = [m.id for m in seeded_media[:2]]

        # Soft delete first
        await client.post("/api/media/batch/delete", json={"media_ids": media_ids})

        mock_ws = MockWebSocketManager()

        with patch("delete_operations.ws_manager", mock_ws):
            response = await client.delete("/api/trash")
            assert response.status_code == 202
            operation = await wait_for_delete_operation(client, response.json()["operation"]["id"])
            assert operation["status"] == "completed"

            events = mock_ws.get_broadcasts("trash_emptied")
            assert len(events) >= 1
            assert events[0][1]["count"] >= 2

    async def test_permanent_delete_scrubs_chat_lineage_and_tool_refs(self, client: AsyncClient, db_session, tmp_path):
        """Permanent delete should rewrite surviving refs to tombstones/nulls."""
        async with db_session() as session:
            chat = Chat(name="Trash Test")
            session.add(chat)
            await session.commit()
            await session.refresh(chat)

            source = await create_media_item(session, file_path=tmp_path / "source.png")
            child = await create_media_item(
                session,
                file_path=tmp_path / "child.png",
                generation_metadata=json.dumps({
                    "source_inputs": [{"media_id": source.id, "role": "source_image", "prompt": "secret"}],
                    "lineage_trace": [{"media_id": source.id, "task_type": "image-to-image", "model": "secret-model", "prompt": "secret prompt"}],
                }),
            )
            session.add(MediaLineage(media_id=child.id, source_media_id=source.id, task_type="image-to-image"))
            session.add(
                ChatItem(
                    chat_id=chat.id,
                    item_type="media_display",
                    media_id=source.id,
                    item_metadata=json.dumps({
                        "attachments": [{"media_id": source.id, "file_path": "/secret/source.png"}],
                        "display_data": {"rows": [{"output": {"media_id": source.id, "status": "complete"}}]},
                    }),
                )
            )
            session.add(Tool(name="Draft", task_type="image-to-image", generator="test", model="test", source_media_id=source.id))
            await session.commit()

        await client.delete(f"/api/media/{source.id}")
        delete_response = await client.delete(f"/api/trash/{source.id}")
        assert delete_response.status_code == 202
        operation = await wait_for_delete_operation(client, delete_response.json()["operation"]["id"])
        assert operation["status"] == "completed"

        async with db_session() as session:
            # Verify generation_metadata tombstoned — keeps media_id + task_type, strips sensitive data
            child_refreshed = await session.get(type(child), child.id)
            metadata = json.loads(child_refreshed.generation_metadata)

            src_input = metadata["source_inputs"][0]
            assert src_input["deleted"] is True
            assert "media_id" not in src_input
            assert src_input["role"] == "source_image"
            assert "prompt" not in src_input  # sensitive data stripped

            trace_entry = metadata["lineage_trace"][0]
            assert trace_entry["deleted"] is True
            assert "media_id" not in trace_entry
            assert trace_entry["task_type"] == "image-to-image"
            assert "model" not in trace_entry  # sensitive data stripped
            assert "prompt" not in trace_entry  # sensitive data stripped

            # Verify MediaLineage source severed
            lineage_rows = (
                await session.execute(select(MediaLineage).where(MediaLineage.media_id == child.id))
            ).scalars().all()
            assert lineage_rows[0].source_media_id is None

            # Verify Tool.source_media_id nulled
            tool = (await session.execute(select(Tool))).scalars().first()
            assert tool.source_media_id is None

            # Verify ChatItem.media_id nulled
            chat_items = (await session.execute(select(ChatItem).where(ChatItem.chat_id == chat.id))).scalars().all()
            assert chat_items[0].media_id is None

            # The JSON blob itself must be rewritten in place — the file_path
            # and any other identifying fields cannot survive on disk under a
            # "permanent delete leaves no trace" promise. The attachment dict
            # should be reduced to a {deleted: True} tombstone (no media_id,
            # no file_path), and similarly for display_data.rows[].output.
            assert "/secret/source.png" not in (chat_items[0].item_metadata or "")
            stored_metadata = json.loads(chat_items[0].item_metadata)
            assert stored_metadata["attachments"][0] == {"deleted": True}
            assert stored_metadata["display_data"]["rows"][0]["output"] == {"deleted": True}

        # Verify the API response continues to surface the tombstone so the
        # client renders chat history correctly after deletion.
        items_response = await client.get(f"/api/chats/{chat.id}/items")
        assert items_response.status_code == 200
        item_metadata = items_response.json()["items"][0]["item_metadata"]
        assert item_metadata["attachments"][0]["deleted"] is True
        assert item_metadata["display_data"]["rows"][0]["output"]["deleted"] is True


class TestLineageTombstoning:
    """Tests for lineage tombstoning during permanent delete."""

    async def test_multi_hop_lineage_tombstone(self, client: AsyncClient, db_session, tmp_path):
        """Delete grandparent A: both child B and grandchild C should have A tombstoned."""
        async with db_session() as session:
            a = await create_media_item(session, file_path=tmp_path / "a.png")
            b = await create_media_item(
                session,
                file_path=tmp_path / "b.png",
                generation_metadata=json.dumps({
                    "lineage_trace": [
                        {"media_id": a.id, "task_type": "text-to-image", "prompt": "a-prompt", "model": "a-model"},
                    ],
                    "source_inputs": [{"media_id": a.id, "role": "input_image", "file_path": "/secret/a.png"}],
                }),
            )
            c = await create_media_item(
                session,
                file_path=tmp_path / "c.png",
                generation_metadata=json.dumps({
                    "lineage_trace": [
                        {"media_id": a.id, "task_type": "text-to-image", "prompt": "a-prompt", "model": "a-model"},
                        {"media_id": b.id, "task_type": "image-to-image", "prompt": "b-prompt", "model": "b-model"},
                    ],
                    "source_inputs": [{"media_id": b.id, "role": "input_image"}],
                }),
            )
            session.add(MediaLineage(media_id=b.id, source_media_id=a.id, task_type="text-to-image"))
            session.add(MediaLineage(media_id=c.id, source_media_id=b.id, task_type="image-to-image"))
            await session.commit()

        # Delete A
        await client.delete(f"/api/media/{a.id}")
        resp = await client.delete(f"/api/trash/{a.id}")
        op = await wait_for_delete_operation(client, resp.json()["operation"]["id"])
        assert op["status"] == "completed"

        async with db_session() as session:
            # B: lineage_trace[0] (A) should be tombstoned
            b_meta = json.loads((await session.get(type(b), b.id)).generation_metadata)
            assert b_meta["lineage_trace"][0]["deleted"] is True
            assert "prompt" not in b_meta["lineage_trace"][0]
            assert b_meta["source_inputs"][0]["deleted"] is True
            assert "file_path" not in b_meta["source_inputs"][0]

            # C: lineage_trace[0] (A) tombstoned, lineage_trace[1] (B) untouched
            c_meta = json.loads((await session.get(type(c), c.id)).generation_metadata)
            assert c_meta["lineage_trace"][0]["deleted"] is True
            assert "prompt" not in c_meta["lineage_trace"][0]
            assert c_meta["lineage_trace"][1].get("deleted") is not True  # B is still alive
            assert c_meta["lineage_trace"][1]["prompt"] == "b-prompt"
            # C's source_inputs (B) should be untouched
            assert c_meta["source_inputs"][0]["media_id"] == b.id
            assert "deleted" not in c_meta["source_inputs"][0]

    async def test_inspired_by_tombstone(self, client: AsyncClient, db_session, tmp_path):
        """Delete inspiration source: inspired_by should be tombstoned."""
        async with db_session() as session:
            source = await create_media_item(session, file_path=tmp_path / "inspiration.png")
            inspired = await create_media_item(
                session,
                file_path=tmp_path / "inspired.png",
                generation_metadata=json.dumps({
                    "prompt": "my own prompt",
                    "inspired_by": {"media_id": source.id},
                    "lineage_trace": [],
                }),
            )
            session.add(MediaLineage(
                media_id=inspired.id, source_media_id=source.id,
                task_type="text-to-image", relationship_type="inspired",
            ))
            await session.commit()

        await client.delete(f"/api/media/{source.id}")
        resp = await client.delete(f"/api/trash/{source.id}")
        op = await wait_for_delete_operation(client, resp.json()["operation"]["id"])
        assert op["status"] == "completed"

        async with db_session() as session:
            meta = json.loads((await session.get(type(inspired), inspired.id)).generation_metadata)
            assert meta["inspired_by"]["deleted"] is True
            assert "media_id" not in meta["inspired_by"]
            # Own prompt should be untouched
            assert meta["prompt"] == "my own prompt"

    async def test_delete_does_not_affect_unrelated_media(self, client: AsyncClient, db_session, tmp_path):
        """Deleting one item should not touch unrelated items' metadata."""
        async with db_session() as session:
            target = await create_media_item(session, file_path=tmp_path / "target.png")
            unrelated = await create_media_item(
                session,
                file_path=tmp_path / "unrelated.png",
                generation_metadata=json.dumps({
                    "prompt": "unrelated prompt",
                    "lineage_trace": [{"media_id": 99999, "task_type": "text-to-image", "prompt": "other"}],
                    "source_inputs": [{"media_id": 99999, "role": "input_image"}],
                }),
            )
            await session.commit()
            original_meta = unrelated.generation_metadata

        await client.delete(f"/api/media/{target.id}")
        resp = await client.delete(f"/api/trash/{target.id}")
        await wait_for_delete_operation(client, resp.json()["operation"]["id"])

        async with db_session() as session:
            refreshed = await session.get(type(unrelated), unrelated.id)
            assert refreshed.generation_metadata == original_meta

    async def test_chat_item_media_id_nulled(self, client: AsyncClient, db_session, tmp_path):
        """ChatItem.media_id FK should be set to NULL when media is deleted."""
        async with db_session() as session:
            chat = Chat(name="Test")
            session.add(chat)
            await session.commit()
            await session.refresh(chat)

            media = await create_media_item(session, file_path=tmp_path / "m.png")
            ci = ChatItem(chat_id=chat.id, item_type="assistant_message", media_id=media.id)
            session.add(ci)
            malformed = ChatItem(
                chat_id=chat.id,
                item_type="tool_result",
                tool_args=f'{{"media_id": {media.id}, "secret": "unterminated',
            )
            session.add(malformed)
            await session.commit()
            await session.refresh(ci)
            await session.refresh(malformed)
            ci_id = ci.id
            malformed_id = malformed.id

        await client.delete(f"/api/media/{media.id}")
        resp = await client.delete(f"/api/trash/{media.id}")
        await wait_for_delete_operation(client, resp.json()["operation"]["id"])

        async with db_session() as session:
            refreshed = await session.get(ChatItem, ci_id)
            assert refreshed.media_id is None
            assert (await session.get(ChatItem, malformed_id)).tool_args is None

    async def test_chat_item_json_scrubbed_on_permanent_delete(self, client: AsyncClient, db_session, tmp_path):
        """ChatItem JSON blobs must be rewritten in place when their referenced
        media is permanently deleted — leaving the original filename, file_path,
        or any other identifying field in ``item_metadata`` would violate the
        "delete leaves no trace" promise. The read-time marker continues to
        decorate the response so the chat still renders the tombstone."""
        async with db_session() as session:
            chat = Chat(name="Scrub Test")
            session.add(chat)
            await session.commit()
            await session.refresh(chat)

            media = await create_media_item(session, file_path=tmp_path / "m.png")
            original_metadata = {
                "attachments": [{"media_id": media.id, "filename": "m.png"}],
                "display_data": {
                    "rows": [{"output": {"media_id": media.id, "status": "complete"}}],
                },
                "results": [{"media_id": media.id, "score": 0.9}],
            }
            ci = ChatItem(
                chat_id=chat.id,
                item_type="media_display",
                item_metadata=json.dumps(original_metadata),
                media_ids=json.dumps([media.id]),
            )
            session.add(ci)
            await session.commit()
            await session.refresh(ci)
            ci_id = ci.id

        await client.delete(f"/api/media/{media.id}")
        resp = await client.delete(f"/api/trash/{media.id}")
        await wait_for_delete_operation(client, resp.json()["operation"]["id"])

        # DB row is rewritten: every reference to the deleted media collapses
        # to a {deleted: True} tombstone, identifying fields gone.
        async with db_session() as session:
            raw = await session.get(ChatItem, ci_id)
            raw_meta = json.loads(raw.item_metadata)
            assert raw_meta["attachments"][0] == {"deleted": True}
            assert raw_meta["display_data"]["rows"][0]["output"] == {"deleted": True}
            assert raw_meta["results"][0] == {"deleted": True}
            # media_ids column has deleted IDs filtered out
            assert json.loads(raw.media_ids) == []
            # No surviving reference to the original filename anywhere in the blob
            assert "m.png" not in raw.item_metadata

        # API response still surfaces deleted: True for the client renderer.
        items_resp = await client.get(f"/api/chats/{chat.id}/items")
        assert items_resp.status_code == 200
        api_meta = items_resp.json()["items"][0]["item_metadata"]
        assert api_meta["attachments"][0]["deleted"] is True
        assert api_meta["display_data"]["rows"][0]["output"]["deleted"] is True
        assert api_meta["results"][0]["deleted"] is True
        assert items_resp.json()["items"][0]["media_ids"] == []

    async def test_bulk_delete_tombstones_all(self, client: AsyncClient, db_session, tmp_path):
        """Bulk deleting multiple parents should tombstone all in one pass."""
        async with db_session() as session:
            a = await create_media_item(session, file_path=tmp_path / "a.png")
            b = await create_media_item(session, file_path=tmp_path / "b.png")
            child = await create_media_item(
                session,
                file_path=tmp_path / "child.png",
                generation_metadata=json.dumps({
                    "lineage_trace": [
                        {"media_id": a.id, "task_type": "text-to-image", "prompt": "secret-a"},
                        {"media_id": b.id, "task_type": "image-to-image", "prompt": "secret-b"},
                    ],
                    "source_inputs": [
                        {"media_id": a.id, "role": "input_image"},
                        {"media_id": b.id, "role": "input_image"},
                    ],
                }),
            )
            session.add(MediaLineage(media_id=child.id, source_media_id=a.id, source_order=0, task_type="text-to-image"))
            session.add(MediaLineage(media_id=child.id, source_media_id=b.id, source_order=1, task_type="image-to-image"))
            await session.commit()

        # Trash both
        await client.post("/api/media/batch/delete", json={"media_ids": [a.id, b.id]})
        resp = await client.post("/api/trash/batch/delete", json={"media_ids": [a.id, b.id]})
        op = await wait_for_delete_operation(client, resp.json()["operation"]["id"])
        assert op["status"] == "completed"

        async with db_session() as session:
            meta = json.loads((await session.get(type(child), child.id)).generation_metadata)
            # Both lineage entries should be tombstoned
            assert meta["lineage_trace"][0]["deleted"] is True
            assert "prompt" not in meta["lineage_trace"][0]
            assert meta["lineage_trace"][1]["deleted"] is True
            assert "prompt" not in meta["lineage_trace"][1]
            # Both source_inputs should be tombstoned
            assert meta["source_inputs"][0]["deleted"] is True
            assert meta["source_inputs"][1]["deleted"] is True


class TestFilteredTrash:
    """Tests for filtered trash listing and filter counts."""

    async def test_filter_trash_by_media_type(self, client: AsyncClient, filtered_trash_media):
        """Test filtering trash by media type."""
        # Filter for images only
        response = await client.get("/api/trash", params={"media_types": "images"})
        assert response.status_code == 200

        data = response.json()
        # Should have 2 images in trash (created by fixture)
        assert data["total"] == 2
        for item in data["items"]:
            assert item["file_format"] in ["png", "jpg", "jpeg", "gif", "webp", "bmp"]

    async def test_filter_trash_by_resolution(self, client: AsyncClient, filtered_trash_media):
        """Test filtering trash by resolution."""
        # Filter for small resolution items
        response = await client.get("/api/trash", params={"resolutions": "small"})
        assert response.status_code == 200

        data = response.json()
        # Should have 2 small items (created by fixture at 100x100)
        assert data["total"] >= 2

    async def test_filter_trash_by_folder(self, client: AsyncClient, filtered_trash_media):
        """Test filtering trash by folder."""
        response = await client.get("/api/trash", params={"folders": "/fake/path"})
        assert response.status_code == 200

        data = response.json()
        # All items have /fake/path prefix
        assert data["total"] >= 2

    async def test_filter_trash_excluded_media_type(self, client: AsyncClient, filtered_trash_media):
        """Test excluding media type in trash filter."""
        # Exclude videos (should only show images)
        response = await client.get("/api/trash", params={"excluded_media_types": "videos"})
        assert response.status_code == 200

        data = response.json()
        # Should not have any videos
        for item in data["items"]:
            assert item["file_format"] not in ["mp4", "webm", "mov", "avi", "mkv", "ogg"]

    async def test_filter_trash_by_caption(self, client: AsyncClient, filtered_trash_media):
        """Test filtering trash by caption text."""
        response = await client.get("/api/trash", params={"caption_query": "image"})
        assert response.status_code == 200

        data = response.json()
        # Should match items with "image" in caption
        assert data["total"] >= 1
        for item in data["items"]:
            assert "image" in item["vlm_caption"].lower()

    async def test_trash_sorting_by_created_date(self, client: AsyncClient, filtered_trash_media):
        """Test sorting trash by created date."""
        # Sort by created_desc
        response = await client.get("/api/trash", params={"sort_by": "created_desc"})
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) >= 2

        # Verify items are sorted by created_date descending
        dates = [item.get("created_date") for item in data["items"] if item.get("created_date")]
        if len(dates) >= 2:
            assert dates == sorted(dates, reverse=True)

    async def test_trash_sorting_by_deleted_date(self, client: AsyncClient, filtered_trash_media):
        """Test sorting trash by deleted date."""
        # Sort by deleted_asc
        response = await client.get("/api/trash", params={"sort_by": "deleted_asc"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 2

    async def test_combined_trash_filters(self, client: AsyncClient, filtered_trash_media):
        """Test combining multiple filters on trash."""
        # Filter for images that are small resolution
        response = await client.get("/api/trash", params={
            "media_types": "images",
            "resolutions": "small"
        })
        assert response.status_code == 200

        data = response.json()
        # All items should match both conditions
        for item in data["items"]:
            assert item["file_format"] in ["png", "jpg", "jpeg", "gif", "webp", "bmp"]


class TestTrashFilterCounts:
    """Tests for GET /api/trash/filter-counts endpoint."""

    async def test_trash_filter_counts_basic(self, client: AsyncClient, filtered_trash_media):
        """Test basic trash filter counts endpoint."""
        response = await client.get("/api/trash/filter-counts")
        assert response.status_code == 200

        data = response.json()
        assert "media_type" in data
        assert "resolution" in data
        assert "folders" in data
        assert "keywords" in data
        assert "date_ranges" in data

    async def test_trash_filter_counts_media_type(self, client: AsyncClient, filtered_trash_media):
        """Test media type counts in trash."""
        response = await client.get("/api/trash/filter-counts")
        assert response.status_code == 200

        data = response.json()
        # Should have counts for images and videos
        assert data["media_type"]["images"] >= 0
        assert data["media_type"]["videos"] >= 0
        # Our fixture has 2 images and 1 video in trash
        total_media = data["media_type"]["images"] + data["media_type"]["videos"]
        assert total_media >= 3

    async def test_trash_filter_counts_resolution(self, client: AsyncClient, filtered_trash_media):
        """Test resolution counts in trash."""
        response = await client.get("/api/trash/filter-counts")
        assert response.status_code == 200

        data = response.json()
        # Should have resolution category counts
        assert data["resolution"]["small"] >= 0
        assert data["resolution"]["medium"] >= 0
        assert data["resolution"]["large"] >= 0

    async def test_trash_filter_counts_with_filter(self, client: AsyncClient, filtered_trash_media):
        """Test filter counts with active filter."""
        # Get counts with media_type filter active
        response = await client.get("/api/trash/filter-counts", params={"media_types": "images"})
        assert response.status_code == 200

        data = response.json()
        # Counts should reflect current filter state
        assert "media_type" in data
        assert "resolution" in data

    async def test_trash_filter_counts_date_ranges(self, client: AsyncClient, filtered_trash_media):
        """Test date range counts in trash."""
        response = await client.get("/api/trash/filter-counts")
        assert response.status_code == 200

        data = response.json()
        # Should have standard date range keys
        assert "2hrs" in data["date_ranges"]
        assert "24hrs" in data["date_ranges"]
        assert "7d" in data["date_ranges"]
        assert "30d" in data["date_ranges"]


class TestRestoreTrashedMediaSilently:
    """The flow runtime calls restore_trashed_media_silently from its
    store-hit path so a cache-hit on a trashed asset re-asserts it as live."""

    async def test_clears_deleted_at_on_trashed_only(self, db_session, seeded_media):
        from datetime import datetime
        from flow_runtime.production_evaluators import (
            restore_trashed_media_silently,
        )

        trashed_id = seeded_media[0].id
        live_id = seeded_media[1].id

        async with db_session() as session:
            item = await session.get(MediaItem, trashed_id)
            item.deleted_at = datetime.utcnow()
            await session.commit()

        await restore_trashed_media_silently([trashed_id, live_id, 999_999])

        async with db_session() as session:
            t = await session.get(MediaItem, trashed_id)
            l = await session.get(MediaItem, live_id)
            assert t.deleted_at is None
            assert l.deleted_at is None

    async def test_broadcasts_only_when_something_restored(
        self, db_session, seeded_media,
    ):
        from datetime import datetime
        from flow_runtime import production_evaluators

        live_id = seeded_media[0].id
        trashed_id = seeded_media[1].id

        async with db_session() as session:
            t = await session.get(MediaItem, trashed_id)
            t.deleted_at = datetime.utcnow()
            await session.commit()

        mock_ws = MockWebSocketManager()
        with patch("utils.websocket.ws_manager", mock_ws):
            # No-op: nothing is trashed
            await production_evaluators.restore_trashed_media_silently([live_id])
            assert mock_ws.get_broadcasts("media_bulk_restored") == []

            # Restore: broadcast fires with the actually-restored ID
            await production_evaluators.restore_trashed_media_silently(
                [live_id, trashed_id]
            )
            events = mock_ws.get_broadcasts("media_bulk_restored")
            assert len(events) == 1
            payload = events[0][1]
            assert payload["media_ids"] == [trashed_id]
            assert payload["count"] == 1

    async def test_empty_input_is_noop(self):
        from flow_runtime.production_evaluators import (
            restore_trashed_media_silently,
        )
        # Should not raise, should not broadcast.
        await restore_trashed_media_silently([])


# Fixtures specific to this test module

@pytest.fixture
async def seeded_media(db_session):
    """Create test media items for this module."""
    async with db_session() as session:
        items = await create_test_media(session, count=5)
        yield items


@pytest.fixture
async def filtered_trash_media(db_session, client: AsyncClient):
    """Create test media items with various properties and trash them for filter testing."""
    from pathlib import Path
    from datetime import datetime, timedelta
    import uuid

    # Use unique prefix to avoid conflicts with other test runs
    prefix = str(uuid.uuid4())[:8]

    async with db_session() as session:
        items = []

        # Create an image with caption
        item1 = await create_media_item(
            session,
            file_path=Path(f"/fake/path/{prefix}_image1.png"),
            file_format="png",
            width=100,
            height=100,
            vlm_caption="A test image with red color",
            created_date=datetime.now() - timedelta(days=1),
        )
        items.append(item1)

        # Create another image with different caption
        item2 = await create_media_item(
            session,
            file_path=Path(f"/fake/path/{prefix}_image2.jpg"),
            file_format="jpg",
            width=200,
            height=200,
            vlm_caption="A test image with blue color",
            created_date=datetime.now() - timedelta(hours=2),
        )
        items.append(item2)

        # Create a video
        item3 = await create_media_item(
            session,
            file_path=Path(f"/fake/path/{prefix}_video1.mp4"),
            file_format="mp4",
            width=1920,
            height=1080,
            vlm_caption="A test video",
            created_date=datetime.now(),
        )
        items.append(item3)

        # Create a large resolution image (outside trash for comparison)
        item4 = await create_media_item(
            session,
            file_path=Path(f"/fake/path/{prefix}_large.png"),
            file_format="png",
            width=3000,
            height=3000,
            vlm_caption="Large image",
        )
        items.append(item4)

    # Trash the first 3 items (not item4)
    for item in items[:3]:
        await client.delete(f"/api/media/{item.id}")

    yield items

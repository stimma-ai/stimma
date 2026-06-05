"""
Tests for batch processing functionality.

Tests cover:
- Batch job submission via /api/generate/submit-batch
- Set input expansion
- Cartesian product computation
- Batch completion handling
- Output set creation and updates
"""

import pytest
import json
from httpx import AsyncClient
from sqlalchemy import select
from unittest.mock import patch, AsyncMock

from database import MediaItem, GenerationJob
from tests.helpers.media import create_media_item


class TestBatchJobSubmission:
    """Tests for POST /api/generate/submit-batch endpoint."""

    async def test_submit_batch_with_set(self, generation_client: AsyncClient, generation_db_session):
        """Test submitting a batch job with a set input."""
        async with generation_db_session() as session:
            # Create test media items
            media1 = await create_media_item(session, file_format='png', vlm_caption='Image 1')
            media2 = await create_media_item(session, file_format='png', vlm_caption='Image 2')
            media3 = await create_media_item(session, file_format='png', vlm_caption='Image 3')

            # Create a set containing these items
            set_data = {
                "version": 1,
                "title": "Test Set",
                "items": [
                    {"path": media1.file_path, "resolved": {"id": media1.id, "file_format": "png"}},
                    {"path": media2.file_path, "resolved": {"id": media2.id, "file_format": "png"}},
                    {"path": media3.file_path, "resolved": {"id": media3.id, "file_format": "png"}},
                ]
            }
            set_item = await create_media_item(
                session,
                file_format='stimmaset.json',
                raw_metadata=json.dumps(set_data),
            )

        # Mock the generation queue to capture submitted jobs
        with patch('generation_queue.get_generation_queue') as mock_get_queue:
            mock_queue = AsyncMock()
            mock_queue.submit_batch_job = AsyncMock(side_effect=lambda **kwargs: 1)
            mock_get_queue.return_value = mock_queue

            # Submit batch job
            response = await generation_client.post("/api/generate/submit-batch", json={
                "tool_id": "test:upscale",
                "folder_path": "/tmp/test",
                "task_type": "upscale",
                "parameters": {
                    "input_image": {"set_id": set_item.id}
                },
                "output_set_title": "Upscaled Images"
            })

            # Verify response
            assert response.status_code == 200
            data = response.json()
            assert "batch_id" in data
            assert data["total_jobs"] == 3
            assert len(data["job_ids"]) == 3

            # Verify submit_batch_job was called 3 times
            assert mock_queue.submit_batch_job.call_count == 3

    async def test_submit_batch_empty_set_error(self, generation_client: AsyncClient, generation_db_session):
        """Test that submitting a batch with an empty set returns an error."""
        async with generation_db_session() as session:
            # Create empty set
            set_data = {"version": 1, "items": []}
            set_item = await create_media_item(
                session,
                file_format='stimmaset.json',
                raw_metadata=json.dumps(set_data)
            )

        response = await generation_client.post("/api/generate/submit-batch", json={
            "tool_id": "test:upscale",
            "folder_path": "/tmp/test",
            "task_type": "upscale",
            "parameters": {
                "input_image": {"set_id": set_item.id}
            }
        })

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    async def test_submit_batch_no_set_error(self, generation_client: AsyncClient):
        """Test that submitting without set inputs returns an error."""
        response = await generation_client.post("/api/generate/submit-batch", json={
            "tool_id": "test:upscale",
            "folder_path": "/tmp/test",
            "task_type": "upscale",
            "parameters": {
                "prompt": "test prompt"  # Regular input, not a set
            }
        })

        assert response.status_code == 400
        assert "no set inputs" in response.json()["detail"].lower()

    async def test_submit_batch_nonexistent_set_error(self, generation_client: AsyncClient):
        """Test that submitting with a nonexistent set ID returns an error."""
        response = await generation_client.post("/api/generate/submit-batch", json={
            "tool_id": "test:upscale",
            "folder_path": "/tmp/test",
            "task_type": "upscale",
            "parameters": {
                "input_image": {"set_id": 99999}  # Nonexistent
            }
        })

        assert response.status_code == 404

    async def test_submit_batch_max_jobs_limit(self, generation_client: AsyncClient, generation_db_session):
        """Test that submitting too many jobs returns an error."""
        async with generation_db_session() as session:
            # Create a set with 101 items (over the limit of 100)
            items = []
            for i in range(101):
                media = await create_media_item(session, file_format='png')
                items.append({"path": media.file_path, "resolved": {"id": media.id, "file_format": "png"}})

            set_data = {"version": 1, "items": items}
            set_item = await create_media_item(
                session,
                file_format='stimmaset.json',
                raw_metadata=json.dumps(set_data)
            )

        response = await generation_client.post("/api/generate/submit-batch", json={
            "tool_id": "test:upscale",
            "folder_path": "/tmp/test",
            "task_type": "upscale",
            "parameters": {
                "input_image": {"set_id": set_item.id}
            }
        })

        assert response.status_code == 400
        assert "too large" in response.json()["detail"].lower()


class TestBatchCompletionHandling:
    """Tests for batch completion detection and output set creation."""

    @pytest.mark.skip(reason="Requires full config setup including LLM roles")
    async def test_output_set_created_on_first_completion(self, generation_db_session):
        """Test that output set is created when first batch job completes."""
        from structured_media import create_batch_output_set
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a test media item (first result)
            test_file = os.path.join(tmp_dir, "result1.png")
            with open(test_file, "wb") as f:
                f.write(b"fake png data")

            async with generation_db_session() as session:
                # Create output set
                output_set = await create_batch_output_set(
                    session=session,
                    folder_path=tmp_dir,
                    batch_id="test-batch-123",
                    first_item_path=test_file,
                    title="Test Batch Output"
                )

                # Verify set was created
                assert output_set is not None
                assert output_set.id > 0
                assert output_set.file_format == 'stimmaset.json'
                assert "1 item" in output_set.vlm_caption

            # Verify set file was created
            assert os.path.exists(output_set.file_path)

            # Read and verify set content
            with open(output_set.file_path, 'r') as f:
                set_data = json.load(f)
            assert len(set_data["items"]) == 1

    @pytest.mark.skip(reason="Requires full config setup including LLM roles")
    async def test_append_to_set_adds_item(self, generation_db_session):
        """Test that append_to_set correctly adds items to existing set."""
        from structured_media import create_batch_output_set, append_to_set
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create first item and output set
            first_file = os.path.join(tmp_dir, "result1.png")
            with open(first_file, "wb") as f:
                f.write(b"fake png 1")

            async with generation_db_session() as session:
                output_set = await create_batch_output_set(
                    session=session,
                    folder_path=tmp_dir,
                    batch_id="test-batch-456",
                    first_item_path=first_file,
                    title="Growing Set"
                )
                output_set_id = output_set.id

            # Create second item
            second_file = os.path.join(tmp_dir, "result2.png")
            with open(second_file, "wb") as f:
                f.write(b"fake png 2")

            async with generation_db_session() as session:
                # Append to set
                updated_set = await append_to_set(
                    session=session,
                    set_media_id=output_set_id,
                    new_item_path=second_file
                )

                # Verify update
                assert updated_set.id == output_set_id
                assert "2 items" in updated_set.vlm_caption

            # Read and verify set content
            with open(updated_set.file_path, 'r') as f:
                set_data = json.load(f)
            assert len(set_data["items"]) == 2

    async def test_append_to_set_rejects_nested_set(self, generation_db_session):
        """Test that append_to_set rejects adding a set to a set."""
        from structured_media import append_to_set
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            async with generation_db_session() as session:
                # Create a parent set directly in database (bypasses ws_manager)
                set_file_path = os.path.join(tmp_dir, "parent.stimmaset.json")
                set_data = {"version": 1, "items": [{"path": "result1.png"}]}
                with open(set_file_path, 'w') as f:
                    json.dump(set_data, f)

                parent_set = await create_media_item(
                    session,
                    file_format='stimmaset.json',
                    file_path=set_file_path,
                    raw_metadata=json.dumps(set_data)
                )
                parent_set_id = parent_set.id

            # Create a nested set file (which should be rejected)
            nested_set_path = os.path.join(tmp_dir, "nested.stimmaset.json")
            with open(nested_set_path, 'w') as f:
                json.dump({"version": 1, "items": []}, f)

            async with generation_db_session() as session:
                # Should raise ValueError when trying to add a set to a set
                with pytest.raises(ValueError, match="nested"):
                    await append_to_set(
                        session=session,
                        set_media_id=parent_set_id,
                        new_item_path=nested_set_path
                    )

    async def test_append_to_set_rejects_nested_grid(self, generation_db_session):
        """Test that append_to_set rejects adding a grid to a set."""
        from structured_media import append_to_set
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            async with generation_db_session() as session:
                # Create a parent set directly in database (bypasses ws_manager)
                set_file_path = os.path.join(tmp_dir, "parent.stimmaset.json")
                set_data = {"version": 1, "items": [{"path": "result1.png"}]}
                with open(set_file_path, 'w') as f:
                    json.dump(set_data, f)

                parent_set = await create_media_item(
                    session,
                    file_format='stimmaset.json',
                    file_path=set_file_path,
                    raw_metadata=json.dumps(set_data)
                )
                parent_set_id = parent_set.id

            # Create a nested grid file (which should be rejected)
            nested_grid_path = os.path.join(tmp_dir, "nested.stimmagrid.json")
            with open(nested_grid_path, 'w') as f:
                json.dump({"version": 1, "cells": []}, f)

            async with generation_db_session() as session:
                # Should raise ValueError when trying to add a grid to a set
                with pytest.raises(ValueError, match="nested"):
                    await append_to_set(
                        session=session,
                        set_media_id=parent_set_id,
                        new_item_path=nested_grid_path
                    )


class TestGetSetItemIds:
    """Tests for get_set_item_ids function."""

    async def test_get_item_ids_from_set(self, generation_db_session):
        """Test extracting media IDs from a set."""
        from structured_media import get_set_item_ids
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            async with generation_db_session() as session:
                # Create media items
                media1 = await create_media_item(session, file_format='png')
                media2 = await create_media_item(session, file_format='png')

                # Create set file
                set_file_path = os.path.join(tmp_dir, "test.stimmaset.json")
                set_data = {
                    "version": 1,
                    "items": [
                        {"path": media1.file_path},
                        {"path": media2.file_path}
                    ]
                }
                with open(set_file_path, 'w') as f:
                    json.dump(set_data, f)

                # Create set media item
                set_item = await create_media_item(
                    session,
                    file_format='stimmaset.json',
                    file_path=set_file_path,
                    raw_metadata=json.dumps(set_data)
                )

                # Get item IDs
                item_ids = await get_set_item_ids(session, set_item.id)

                assert len(item_ids) == 2
                assert media1.id in item_ids
                assert media2.id in item_ids


class TestCartesianProduct:
    """Tests for cartesian product computation in batch submission."""

    async def test_cartesian_product_multiple_sets(self, generation_client: AsyncClient, generation_db_session):
        """Test that multiple set inputs produce cartesian product of jobs."""
        async with generation_db_session() as session:
            # Create first set with 2 items
            media1a = await create_media_item(session, file_format='png')
            media1b = await create_media_item(session, file_format='png')
            set1_data = {
                "version": 1,
                "items": [
                    {"path": media1a.file_path, "resolved": {"id": media1a.id, "file_format": "png"}},
                    {"path": media1b.file_path, "resolved": {"id": media1b.id, "file_format": "png"}},
                ]
            }
            set1 = await create_media_item(
                session,
                file_format='stimmaset.json',
                raw_metadata=json.dumps(set1_data)
            )

            # Create second set with 3 items
            media2a = await create_media_item(session, file_format='png')
            media2b = await create_media_item(session, file_format='png')
            media2c = await create_media_item(session, file_format='png')
            set2_data = {
                "version": 1,
                "items": [
                    {"path": media2a.file_path, "resolved": {"id": media2a.id, "file_format": "png"}},
                    {"path": media2b.file_path, "resolved": {"id": media2b.id, "file_format": "png"}},
                    {"path": media2c.file_path, "resolved": {"id": media2c.id, "file_format": "png"}},
                ]
            }
            set2 = await create_media_item(
                session,
                file_format='stimmaset.json',
                raw_metadata=json.dumps(set2_data)
            )

        # Mock the generation queue
        with patch('generation_queue.get_generation_queue') as mock_get_queue:
            mock_queue = AsyncMock()
            job_counter = [0]

            def increment_job(*args, **kwargs):
                job_counter[0] += 1
                return job_counter[0]

            mock_queue.submit_batch_job = AsyncMock(side_effect=increment_job)
            mock_get_queue.return_value = mock_queue

            # Submit with both sets
            response = await generation_client.post("/api/generate/submit-batch", json={
                "tool_id": "test:blend",
                "folder_path": "/tmp/test",
                "task_type": "blend",
                "parameters": {
                    "image_a": {"set_id": set1.id},
                    "image_b": {"set_id": set2.id}
                }
            })

            # Should create 2 * 3 = 6 jobs (cartesian product)
            assert response.status_code == 200
            data = response.json()
            assert data["total_jobs"] == 6
            assert len(data["job_ids"]) == 6

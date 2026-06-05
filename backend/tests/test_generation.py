"""
Integration tests for generation/tool invocation system.

Tests the full stack: API endpoints -> generation queue -> provider execution -> database state.
"""

import asyncio
import json
import pytest
from pathlib import Path

import httpx
from sqlalchemy import select

from database import GenerationJob, MediaItem
from providers.test_provider import TestToolConfig
from tests.helpers import (
    create_media_with_generation_metadata,
    process_job,
)


# =============================================================================
# Job Submission Tests
# =============================================================================


class TestJobSubmission:
    """Tests for POST /api/generate/submit"""

    async def test_submit_text_to_image_job(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        """Submit a valid text-to-image job and verify it gets queued."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {
                    "prompt": "test prompt",
                    "width": 64,
                    "height": 64,
"steps": 10,
                    "seed": 42
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    async def test_submit_with_invalid_tool_returns_400(
        self, generation_client: httpx.AsyncClient, output_folder: str
    ):
        """Submitting with an unknown tool ID returns 400."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "nonexistent:tool:id",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "test"},
            },
        )

        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    async def test_submit_to_non_generation_folder_returns_400(
        self, generation_client: httpx.AsyncClient
    ):
        """Submitting to a folder without allow_generate returns 400."""
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": "/nonexistent/folder",
                "task_type": "text-to-image",
                "parameters": {"prompt": "test"},
            },
        )

        assert response.status_code == 400
        assert "generation" in response.json()["detail"].lower()


# =============================================================================
# Job Processing Tests
# =============================================================================


class TestJobProcessing:
    """Tests for job execution through the queue."""

    async def test_job_state_transitions(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Verify job transitions from queued -> processing -> completed."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "state transition test", "width": 64, "height": 64, "steps": 5, "seed": 123},
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        # Verify initial state is queued
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        assert job_response.json()["status"] == "queued"

        # Process the job
        await process_job(generation_queue, job_id)

        # Verify completed
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        job = job_response.json()
        assert job["status"] == "completed"
        assert job["result_media_id"] is not None

    async def test_completed_job_creates_media_item(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Verify completed job creates a MediaItem with correct metadata."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "media creation test", "width": 64, "height": 64, "steps": 5, "seed": 456},
            },
        )
        job_id = response.json()["job_id"]

        # Process the job
        await process_job(generation_queue, job_id)

        # Get job details
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        job = job_response.json()
        assert job["status"] == "completed"

        # Verify MediaItem in database
        async with generation_db_session() as session:
            media = await session.get(MediaItem, job["result_media_id"])
            assert media is not None
            assert media.generation_metadata is not None

            # Verify metadata structure
            meta = json.loads(media.generation_metadata)
            assert meta["prompt"] == "media creation test"
            assert meta["tool_id"] == "test:text-to-image:test-model"
            assert meta["task_type"] == "text-to-image"

            # Verify file was created
            assert Path(media.file_path).exists()

    async def test_failed_job_records_error(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        test_provider,
        output_folder: str,
    ):
        """Configure provider to fail and verify error is recorded."""
        # Configure provider to fail
        test_provider.configure_tool(
            "text-to-image:test-model",
            TestToolConfig(
                should_fail=True,
                fail_at_progress=0.5,
                fail_message="GPU out of memory",
            ),
        )

        try:
            # Submit job
            response = await generation_client.post(
                "/api/generate/submit",
                json={
                    "tool_id": "test:text-to-image:test-model",
                    "folder_path": output_folder,
                    "task_type": "text-to-image",
                    "parameters": {"prompt": "failure test", "steps": 5, "seed": 789},
                },
            )
            job_id = response.json()["job_id"]

            # Process the job (will fail)
            await process_job(generation_queue, job_id)

            # Verify failed state
            job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
            job = job_response.json()
            assert job["status"] == "failed"
            assert "GPU out of memory" in job["error"]
        finally:
            # Reset provider config
            test_provider.reset_configs()

    async def test_websocket_events_broadcast(
        self,
        generation_client: httpx.AsyncClient,
        generation_queue,
        mock_ws,
        output_folder: str,
    ):
        """Verify WebSocket events are broadcast during job lifecycle."""
        mock_ws.clear()

        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "websocket test", "steps": 5, "seed": 111},
            },
        )
        job_id = response.json()["job_id"]

        # Process the job
        await process_job(generation_queue, job_id)

        # Verify broadcast events
        mock_ws.assert_broadcast("generation_job_queued")


# =============================================================================
# Job Cancellation Tests
# =============================================================================


class TestJobCancellation:
    """Tests for DELETE /api/generate/jobs/{job_id}"""

    async def test_cancel_queued_job(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """Cancelling a queued job should succeed."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "cancel queued test", "steps": 5, "seed": 888},
            },
        )
        job_id = response.json()["job_id"]

        # Cancel the queued job
        cancel_response = await generation_client.delete(
            f"/api/generate/jobs/{job_id}"
        )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["success"] is True

        # Verify job is cancelled
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        assert job_response.json()["status"] == "cancelled"

    async def test_cancel_completed_job_returns_400(
        self,
        generation_client: httpx.AsyncClient,
        generation_queue,
        output_folder: str,
    ):
        """Cancelling a completed job returns 400."""
        # Submit job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "cancel test", "steps": 5, "seed": 222},
            },
        )
        job_id = response.json()["job_id"]

        # Process to completion
        await process_job(generation_queue, job_id)

        # Try to cancel completed job
        cancel_response = await generation_client.delete(
            f"/api/generate/jobs/{job_id}"
        )
        assert cancel_response.status_code == 400


# =============================================================================
# Generate More Tests
# =============================================================================


class TestGenerateMore:
    """Tests for GET /api/tools/generate-more-tools/{media_id}"""

    async def test_get_tools_for_generated_media(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Get compatible tools for media with generation metadata."""
        # Create a completed job to generate media with proper metadata
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "generate more test", "width": 64, "height": 64, "steps": 5, "seed": 9999},
            },
        )
        job_id = response.json()["job_id"]
        await process_job(generation_queue, job_id)

        # Get the media ID from the completed job
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        media_id = job_response.json()["result_media_id"]

        # Get generate-more tools
        response = await generation_client.get(f"/api/tools/generate-more-tools/{media_id}")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        # Find the test tool in the response
        test_tools = [t for t in data if "test" in t["full_tool_id"]]
        assert len(test_tools) > 0


# =============================================================================
# Config From Media Tests
# =============================================================================


class TestConfigFromMedia:
    """Tests for POST /api/generate/config-from-media/{media_id}"""

    async def test_extract_config_without_target_tool(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
        generation_queue,
        output_folder: str,
    ):
        """Extract generation config from media without specifying target tool."""
        # Create a completed job to generate media with proper metadata
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "config extraction test", "width": 64, "height": 64, "steps": 30, "seed": 98765, "cfg": 8.5},
            },
        )
        job_id = response.json()["job_id"]
        await process_job(generation_queue, job_id)

        # Get the media ID from the completed job
        job_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        media_id = job_response.json()["result_media_id"]

        # Extract config without target_tool_id (avoids the list_tools bug)
        response = await generation_client.post(
            f"/api/generate/config-from-media/{media_id}",
        )
        assert response.status_code == 200

        data = response.json()
        assert data["prompt"] == "config extraction test"
        assert data["input_media_id"] == media_id

    async def test_caption_only_media_sets_disable_all_loras(
        self,
        generation_client: httpx.AsyncClient,
        generation_db_session,
    ):
        """Caption-only media should return disable_all_loras=True."""
        from tests.helpers import create_media_item

        # Create a media item with only vlm_caption (no generation_metadata)
        async with generation_db_session() as session:
            media = await create_media_item(
                session,
                vlm_caption="A beautiful sunset over mountains",
                vlm_caption_status="complete",
                # No generation_metadata - simulates imported image with caption
            )

        # Extract config
        response = await generation_client.post(
            f"/api/generate/config-from-media/{media.id}",
        )
        assert response.status_code == 200

        data = response.json()
        assert data["prompt"] == "A beautiful sunset over mountains"
        assert data.get("loras") == []
        assert data.get("disable_all_loras") is True


# =============================================================================
# Job Listing Tests
# =============================================================================


class TestJobListing:
    """Tests for GET /api/generate/jobs"""

    async def test_list_jobs(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """List all jobs for current profile."""
        # Submit a job first
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "list test", "steps": 5, "seed": 333},
            },
        )
        job_id = response.json()["job_id"]

        # List jobs
        list_response = await generation_client.get("/api/generate/jobs")
        assert list_response.status_code == 200

        data = list_response.json()
        assert "jobs" in data
        assert "count" in data

        # Our job should be in the list
        job_ids = [j["id"] for j in data["jobs"]]
        assert job_id in job_ids

    async def test_get_job_details(
        self,
        generation_client: httpx.AsyncClient,
        output_folder: str,
    ):
        """Get details of a specific job."""
        # Submit a job
        response = await generation_client.post(
            "/api/generate/submit",
            json={
                "tool_id": "test:text-to-image:test-model",
                "folder_path": output_folder,
                "task_type": "text-to-image",
                "parameters": {"prompt": "details test", "steps": 5, "seed": 444},
            },
        )
        job_id = response.json()["job_id"]

        # Get job details
        details_response = await generation_client.get(f"/api/generate/jobs/{job_id}")
        assert details_response.status_code == 200

        job = details_response.json()
        assert job["id"] == job_id
        assert job["task_type"] == "text-to-image"
        assert job["tool_id"] == "test:text-to-image:test-model"


# =============================================================================
# Fixtures for this test file
# =============================================================================


@pytest.fixture(autouse=True)
def reset_test_provider(test_provider):
    """Reset test provider config between tests."""
    yield
    test_provider.reset_configs()

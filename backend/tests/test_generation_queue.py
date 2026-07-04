"""
Unit tests for GenerationQueue internal state management.

Tests the queue's internal mechanisms: pending counter management,
forever mode slot filling, client cleanup, and cancellation behavior.
These complement test_generation.py (which tests via HTTP API).
"""

import time

import pytest
from unittest.mock import AsyncMock, patch

from database import GenerationJob
from generation_queue import resolve_recorded_seed
from tests.helpers.generation import create_generation_job


# =============================================================================
# Helpers
# =============================================================================


def _reset_queue_state(queue):
    """Reset queue's internal forever mode and pending state between tests."""
    queue._forever_mode_clients.clear()
    queue._pending_work_requests.clear()
    queue._pending_work_requests_per_client.clear()
    queue._last_served_client.clear()
    if hasattr(queue, "_finalizing_per_client"):
        queue._finalizing_per_client.clear()


def _make_timestamps(n: int) -> list[float]:
    """Create n fresh monotonic timestamps for pending request lists."""
    return [time.monotonic() for _ in range(n)]


def test_resolve_recorded_seed_falls_back_to_requested_when_provider_reports_none():
    assert resolve_recorded_seed(12345, None) == 12345
    assert resolve_recorded_seed(12345, 67890) == 67890


# =============================================================================
# Pending Counter Management (BUG-2, BUG-3, MOD-1)
# =============================================================================


class TestPendingCounterManagement:
    """Tests that pending work request counters stay consistent."""

    async def test_submit_job_decrements_pending_counter(
        self, generation_queue, mock_ws, output_folder
    ):
        """After submit_job, both global and per-client pending counters decrement."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        backend = "test"
        client = "test-client-1"

        # Simulate _fill_available_slots having appended timestamps
        generation_queue._pending_work_requests[backend] = _make_timestamps(1)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(1)

        await generation_queue.submit_job(
            generator_name="test",
            model_name="test-model",
            folder_path=output_folder,
            parameters={"prompt": "counter test", "steps": 5, "seed": 1},
            generator_instance_id=client,
            backend_name=backend,
            tool_id="test:text-to-image:test-model",
        )

        assert len(generation_queue._pending_work_requests.get(backend, [])) == 0
        assert len(generation_queue._pending_work_requests_per_client.get(client, [])) == 0

    async def test_submit_job_failure_still_decrements_pending(
        self, generation_queue, output_folder
    ):
        """BUG-3: Even when submit_job raises (bad folder), pending counters decrement."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-bug3"

        # Simulate pending from _fill_available_slots
        generation_queue._pending_work_requests[backend] = _make_timestamps(2)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(2)

        with pytest.raises(ValueError, match="does not allow generation"):
            await generation_queue.submit_job(
                generator_name="test",
                model_name="test-model",
                folder_path="/nonexistent/folder/that/fails/validation",
                parameters={"prompt": "fail test", "steps": 5, "seed": 1},
                generator_instance_id=client,
                backend_name=backend,
                tool_id="test:text-to-image:test-model",
            )

        # Counters should have decremented despite the exception
        assert len(generation_queue._pending_work_requests[backend]) == 1
        assert len(generation_queue._pending_work_requests_per_client[client]) == 1

    async def test_submit_job_tool_resolution_failure_still_decrements_pending(
        self, generation_queue, output_folder
    ):
        """Even failures before DB validation consume the owned reservation."""
        _reset_queue_state(generation_queue)

        backend = "missing"
        client = "test-client-invalid-tool"
        generation_queue._pending_work_requests[backend] = _make_timestamps(1)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(1)

        with pytest.raises(ValueError, match="Tool not found"):
            await generation_queue.submit_job(
                generator_name="missing",
                model_name="missing-tool",
                folder_path=output_folder,
                parameters={"prompt": "invalid tool", "steps": 5, "seed": 1},
                generator_instance_id=client,
                backend_name=backend,
                tool_id="missing:tool",
            )

        assert len(generation_queue._pending_work_requests[backend]) == 0
        assert len(generation_queue._pending_work_requests_per_client[client]) == 0

    async def test_submit_job_can_skip_pending_consumption(
        self, generation_queue, output_folder
    ):
        """Manual/local submits must not consume an unrelated reserved slot."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-manual"
        generation_queue._pending_work_requests[backend] = _make_timestamps(1)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(1)

        await generation_queue.submit_job(
            generator_name="test",
            model_name="test-model",
            folder_path=output_folder,
            parameters={"prompt": "manual submit", "steps": 5, "seed": 1},
            generator_instance_id=client,
            backend_name=backend,
            tool_id="test:text-to-image:test-model",
            consume_pending_request=False,
        )

        assert len(generation_queue._pending_work_requests[backend]) == 1
        assert len(generation_queue._pending_work_requests_per_client[client]) == 1

    async def test_submit_batch_job_failure_still_decrements_pending(
        self, generation_queue, output_folder
    ):
        """BUG-3: submit_batch_job failure also decrements pending counters."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-batch-bug3"

        generation_queue._pending_work_requests[backend] = _make_timestamps(1)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(1)

        with pytest.raises(ValueError, match="does not allow generation"):
            await generation_queue.submit_batch_job(
                generator_name="test",
                model_name="test-model",
                folder_path="/bad/folder",
                parameters={"prompt": "fail batch", "steps": 5, "seed": 1},
                batch_id="test-batch-1",
                batch_total=3,
                generator_instance_id=client,
                backend_name=backend,
                tool_id="test:text-to-image:test-model",
            )

        assert len(generation_queue._pending_work_requests[backend]) == 0
        assert len(generation_queue._pending_work_requests_per_client[client]) == 0

    async def test_cleanup_disconnected_client_releases_all_pending(
        self, generation_queue
    ):
        """BUG-2: Disconnecting a client with N pending releases N (not 1) from global counter."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-bug2"

        # Register forever mode
        generation_queue._forever_mode_clients[backend] = {client: 3}
        # Client has 3 pending work requests
        generation_queue._pending_work_requests[backend] = _make_timestamps(3)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(3)

        await generation_queue.cleanup_disconnected_client(client)

        # All 3 should be released, not just 1
        assert len(generation_queue._pending_work_requests.get(backend, [])) == 0
        assert client not in generation_queue._pending_work_requests_per_client
        assert client not in generation_queue._forever_mode_clients.get(backend, {})

    async def test_cleanup_disconnected_client_no_underflow(
        self, generation_queue
    ):
        """Pending counter never goes below 0."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-underflow"

        # Client thinks it has 5 pending but global only has 2
        generation_queue._forever_mode_clients[backend] = {client: 0}
        generation_queue._pending_work_requests[backend] = _make_timestamps(2)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(5)

        await generation_queue.cleanup_disconnected_client(client)

        assert len(generation_queue._pending_work_requests.get(backend, [])) == 0  # 2 - 5 entries removed = empty

    async def test_unregister_forever_mode_releases_pending(
        self, generation_queue
    ):
        """MOD-1: Graceful unregister releases pending from global counter."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-mod1"

        generation_queue._forever_mode_clients[backend] = {client: 2}
        generation_queue._pending_work_requests[backend] = _make_timestamps(2)
        generation_queue._pending_work_requests_per_client[client] = _make_timestamps(2)

        await generation_queue.unregister_forever_mode(client, backend)

        assert len(generation_queue._pending_work_requests.get(backend, [])) == 0
        assert client not in generation_queue._pending_work_requests_per_client
        assert client not in generation_queue._forever_mode_clients.get(backend, {})

    async def test_unregister_with_zero_pending_is_safe(
        self, generation_queue
    ):
        """Unregistering a client with 0 pending doesn't corrupt counters."""
        _reset_queue_state(generation_queue)

        backend = "test"
        client = "test-client-zero"

        generation_queue._forever_mode_clients[backend] = {client: 2}
        # No pending
        generation_queue._pending_work_requests[backend] = []

        await generation_queue.unregister_forever_mode(client, backend)

        assert len(generation_queue._pending_work_requests.get(backend, [])) == 0


# =============================================================================
# Forever Mode Slot Filling (BUG-4)
# =============================================================================


class TestForeverModeSlotFilling:
    """Tests for _fill_available_slots and cancel_job interaction."""

    async def test_register_forever_mode_sends_work_requests(
        self, generation_queue, mock_ws
    ):
        """Registering a forever mode client triggers work request broadcasts."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        client = "test-forever-register"

        await generation_queue.register_forever_mode(client, "test", max_concurrency=2)

        # Should have sent work requests (up to backend capacity)
        work_requests = mock_ws.get_broadcasts("generation_request_work")
        assert len(work_requests) > 0
        assert all(d["generator_instance_id"] == client for _, d in work_requests)

        # Clean up
        await generation_queue.unregister_forever_mode(client, "test")

    async def test_max_concurrency_limits_work_requests(
        self, generation_queue, mock_ws
    ):
        """Client with max_concurrency=1 only gets 1 work request."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        client = "test-forever-concurrency"

        await generation_queue.register_forever_mode(client, "test", max_concurrency=1)

        work_requests = mock_ws.get_broadcasts("generation_request_work")
        client_requests = [d for _, d in work_requests if d["generator_instance_id"] == client]
        assert len(client_requests) == 1

        # Clean up
        await generation_queue.unregister_forever_mode(client, "test")

    async def test_cancel_job_refills_forever_mode_slots(
        self, generation_queue, generation_db_session, mock_ws, output_folder
    ):
        """BUG-4: Cancelling a job in forever mode triggers slot refill."""
        _reset_queue_state(generation_queue)

        client = "test-forever-cancel"

        # Submit a job first
        job_id = await generation_queue.submit_job(
            generator_name="test",
            model_name="test-model",
            folder_path=output_folder,
            parameters={"prompt": "cancel refill test", "steps": 5, "seed": 42},
            generator_instance_id=client,
            backend_name="test",
            tool_id="test:text-to-image:test-model",
        )

        # Register forever mode (this sends initial work requests)
        await generation_queue.register_forever_mode(client, "test", max_concurrency=2)
        mock_ws.clear()

        # Cancel the job
        await generation_queue.cancel_job(job_id)

        # Should have called _fill_available_slots, which sends work requests
        work_requests = mock_ws.get_broadcasts("generation_request_work")
        assert len(work_requests) > 0, "cancel_job should trigger slot refill"

        # Clean up
        await generation_queue.unregister_forever_mode(client, "test")

    async def test_fill_slots_round_robin_fairness(
        self, generation_queue, mock_ws
    ):
        """Multiple clients get work distributed via round-robin."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        client_a = "test-rr-a"
        client_b = "test-rr-b"

        # Register both clients with unlimited concurrency
        generation_queue._forever_mode_clients["test"] = {
            client_a: 0,  # unlimited
            client_b: 0,  # unlimited
        }

        await generation_queue._fill_available_slots("test")

        work_requests = mock_ws.get_broadcasts("generation_request_work")
        recipients = [d["generator_instance_id"] for _, d in work_requests]

        # Both clients should receive at least one request
        assert client_a in recipients, "Client A should get work"
        assert client_b in recipients, "Client B should get work"

        # Clean up
        _reset_queue_state(generation_queue)

    async def test_finalizing_jobs_do_not_block_work_requests(
        self, generation_queue, mock_ws
    ):
        """Regression: a job whose GPU work is done but whose post-processing tail
        is still running stays 'processing' in the DB. It must NOT count against the
        client's concurrency, otherwise forever mode dispatches one batch and stalls.
        """
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        client = "test-finalizing"
        generation_queue._forever_mode_clients["test"] = {client: 2}

        # DB still reports 2 active ('processing') jobs for this client ...
        async def _two_active(client_id):
            return 2

        generation_queue._get_client_active_jobs = _two_active

        # ... but both have finished on the GPU and are only finalizing (detached
        # post-processing tail), so they occupy no slot.
        generation_queue._finalizing_per_client[client] = 2

        # Isolate from any queued jobs left in the shared DB by other tests so the
        # backend capacity math is deterministic (queued_count = 0).
        orig_get_all_jobs_dbs = generation_queue._get_all_jobs_dbs
        generation_queue._get_all_jobs_dbs = lambda: []

        class _BackendRegistryStub:
            async def list_backends(self):
                return {"test": {"max_concurrent": 2, "current_jobs": 0}}

        try:
            with patch("backend_registry.get_backend_registry", return_value=_BackendRegistryStub()):
                await generation_queue._fill_available_slots("test")
        finally:
            generation_queue._get_all_jobs_dbs = orig_get_all_jobs_dbs

        work_requests = mock_ws.get_broadcasts("generation_request_work")
        client_requests = [d for _, d in work_requests if d["generator_instance_id"] == client]
        assert len(client_requests) == 2, (
            "finalizing jobs must free client capacity so forever mode keeps dispatching"
        )

        _reset_queue_state(generation_queue)

    async def test_fill_slots_handles_unregister_during_iteration(
        self, generation_queue, mock_ws
    ):
        """Concurrent unregister during slot-fill should not crash with dict-size errors."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        client_a = "test-race-a"
        client_b = "test-race-b"
        generation_queue._forever_mode_clients["test"] = {
            client_a: 0,
            client_b: 0,
        }

        call_count = 0

        async def _active_jobs_with_unregister(client_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await generation_queue.unregister_forever_mode(client_b, "test")
            return 0

        generation_queue._get_client_active_jobs = _active_jobs_with_unregister

        class _BackendRegistryStub:
            async def list_backends(self):
                return {"test": {"max_concurrent": 2, "current_jobs": 0}}

        with patch("backend_registry.get_backend_registry", return_value=_BackendRegistryStub()):
            await generation_queue._fill_available_slots("test")


# =============================================================================
# Client Cleanup (STRUCT-2)
# =============================================================================


class TestClientCleanup:
    """Tests for cleanup_disconnected_client and cancel_queued_jobs_for_instance."""

    async def test_cleanup_cancels_queued_jobs(
        self, generation_queue, generation_db_session, mock_ws
    ):
        """cleanup_disconnected_client cancels all queued jobs for the instance."""
        _reset_queue_state(generation_queue)

        client = "test-cleanup-jobs"

        # Create some queued jobs for this client directly in DB
        async with generation_db_session() as session:
            job1 = await create_generation_job(session, generator_instance_id=client, status="queued")
            job2 = await create_generation_job(session, generator_instance_id=client, status="queued")
            job1_id = job1.id
            job2_id = job2.id

        mock_ws.clear()

        await generation_queue.cleanup_disconnected_client(client)

        # Verify jobs are cancelled
        async with generation_db_session() as session:
            from sqlalchemy import select
            for jid in [job1_id, job2_id]:
                result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == jid)
                )
                job = result.scalar_one()
                assert job.status == "cancelled"
                assert job.error == "Client disconnected"

        # Verify cancellation events were broadcast
        cancel_events = mock_ws.get_broadcasts("generation_job_cancelled")
        cancelled_ids = {d["job"]["id"] for _, d in cancel_events}
        assert job1_id in cancelled_ids
        assert job2_id in cancelled_ids

    async def test_cleanup_unregisters_from_all_backends(
        self, generation_queue
    ):
        """cleanup_disconnected_client removes client from ALL backends' forever mode."""
        _reset_queue_state(generation_queue)

        client = "test-cleanup-multi-backend"

        # Register on multiple backends
        generation_queue._forever_mode_clients["backend-a"] = {client: 2}
        generation_queue._forever_mode_clients["backend-b"] = {client: 3}

        await generation_queue.cleanup_disconnected_client(client)

        assert client not in generation_queue._forever_mode_clients.get("backend-a", {})
        assert client not in generation_queue._forever_mode_clients.get("backend-b", {})

    async def test_cancel_queued_jobs_returns_count(
        self, generation_queue, generation_db_session, mock_ws
    ):
        """cancel_queued_jobs_for_instance returns the count of cancelled jobs."""
        _reset_queue_state(generation_queue)

        client = "test-cancel-count"

        async with generation_db_session() as session:
            await create_generation_job(session, generator_instance_id=client, status="queued")
            await create_generation_job(session, generator_instance_id=client, status="queued")
            await create_generation_job(session, generator_instance_id=client, status="queued")

        mock_ws.clear()

        count = await generation_queue.cancel_queued_jobs_for_instance(client)
        assert count == 3

    async def test_cancel_queued_jobs_uses_custom_error_message(
        self, generation_queue, generation_db_session, mock_ws
    ):
        """cancel_queued_jobs_for_instance accepts a custom error message."""
        _reset_queue_state(generation_queue)

        client = "test-cancel-msg"

        async with generation_db_session() as session:
            job = await create_generation_job(session, generator_instance_id=client, status="queued")
            job_id = job.id

        mock_ws.clear()

        await generation_queue.cancel_queued_jobs_for_instance(client, error_message="Custom reason")

        async with generation_db_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(GenerationJob).where(GenerationJob.id == job_id)
            )
            job = result.scalar_one()
            assert job.error == "Custom reason"

    async def test_cancel_skips_non_queued_jobs(
        self, generation_queue, generation_db_session, mock_ws
    ):
        """cancel_queued_jobs_for_instance only cancels queued jobs, not processing/completed."""
        _reset_queue_state(generation_queue)

        client = "test-cancel-selective"

        async with generation_db_session() as session:
            queued_job = await create_generation_job(
                session, generator_instance_id=client, status="queued"
            )
            processing_job = await create_generation_job(
                session, generator_instance_id=client, status="processing"
            )
            queued_id = queued_job.id
            processing_id = processing_job.id

        mock_ws.clear()

        count = await generation_queue.cancel_queued_jobs_for_instance(client)
        assert count == 1  # Only the queued job

        async with generation_db_session() as session:
            from sqlalchemy import select
            # Processing job should be untouched
            result = await session.execute(
                select(GenerationJob).where(GenerationJob.id == processing_id)
            )
            job = result.scalar_one()
            assert job.status == "processing"


# =============================================================================
# Job Submission Consolidation (STRUCT-1)
# =============================================================================


class TestJobSubmissionConsolidation:
    """Tests that both submit_job and submit_batch_job work through _create_job."""

    async def test_submit_job_creates_queued_job(
        self, generation_queue, generation_db_session, mock_ws, output_folder
    ):
        """submit_job creates a job with status='queued' and broadcasts."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        job_id = await generation_queue.submit_job(
            generator_name="test",
            model_name="test-model",
            folder_path=output_folder,
            parameters={"prompt": "consolidation test", "steps": 5, "seed": 99},
            generator_instance_id="test-struct1",
            backend_name="test",
            tool_id="test:text-to-image:test-model",
        )

        assert job_id > 0

        # Verify broadcast
        mock_ws.assert_broadcast("generation_job_queued")

        # Verify DB state
        job = await generation_queue.get_job(job_id)
        assert job["status"] == "queued"
        assert job["tool_id"] == "test:text-to-image:test-model"
        assert "batch_id" not in job or job.get("batch_id") is None

    async def test_submit_batch_job_includes_batch_fields(
        self, generation_queue, generation_db_session, mock_ws, output_folder
    ):
        """submit_batch_job creates a job with batch_id and batch_total."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        job_id = await generation_queue.submit_batch_job(
            generator_name="test",
            model_name="test-model",
            folder_path=output_folder,
            parameters={"prompt": "batch consolidation test", "steps": 5, "seed": 100},
            batch_id="struct1-batch-abc",
            batch_total=5,
            generator_instance_id="test-struct1-batch",
            backend_name="test",
            tool_id="test:text-to-image:test-model",
        )

        assert job_id > 0

        # Verify broadcast includes batch_id
        batch_broadcasts = [
            d for _, d in mock_ws.get_broadcasts("generation_job_queued")
            if d.get("batch_id") == "struct1-batch-abc"
        ]
        assert len(batch_broadcasts) == 1

        # Verify DB state
        job = await generation_queue.get_job(job_id)
        assert job["batch_id"] == "struct1-batch-abc"
        assert job["batch_total"] == 5

    async def test_submit_batch_stores_metadata_in_input(
        self, generation_queue, generation_db_session, mock_ws, output_folder
    ):
        """submit_batch_job stores batch_output_title in the flat parameters dict."""
        _reset_queue_state(generation_queue)
        mock_ws.clear()

        job_id = await generation_queue.submit_batch_job(
            generator_name="test",
            model_name="test-model",
            folder_path=output_folder,
            parameters={"prompt": "batch meta test", "steps": 5, "seed": 101},
            batch_id="meta-batch-abc",
            batch_total=3,
            batch_output_title="My Batch Output",
            batch_input_set_ids=[10, 20],
            generator_instance_id="test-struct1-meta",
            backend_name="test",
            tool_id="test:text-to-image:test-model",
        )

        import json
        job = await generation_queue.get_job(job_id)
        params = json.loads(job["parameters"])
        assert params["_batch_output_title"] == "My Batch Output"
        assert params["_batch_input_set_ids"] == [10, 20]


# =============================================================================
# Stale Job Cleanup
# =============================================================================


class TestStaleJobCleanup:
    """Tests for cleanup_stale_jobs (backend restart recovery)."""

    async def test_cleanup_deletes_queued_jobs(
        self, generation_queue, generation_db_session
    ):
        """cleanup_stale_jobs deletes queued jobs (clients must re-submit)."""
        _reset_queue_state(generation_queue)

        async with generation_db_session() as session:
            job = await create_generation_job(
                session, generator_instance_id="stale-queued", status="queued"
            )
            job_id = job.id

        await generation_queue.cleanup_stale_jobs()

        # Job should be deleted
        result = await generation_queue.get_job(job_id)
        assert result is None

    async def test_cleanup_fails_processing_jobs(
        self, generation_queue, generation_db_session
    ):
        """cleanup_stale_jobs marks processing/assigned jobs as failed."""
        _reset_queue_state(generation_queue)

        async with generation_db_session() as session:
            job = await create_generation_job(
                session, generator_instance_id="stale-processing", status="processing"
            )
            job_id = job.id

        await generation_queue.cleanup_stale_jobs()

        result = await generation_queue.get_job(job_id)
        assert result["status"] == "failed"
        assert "restart" in result["error"].lower()

    async def test_cleanup_ignores_completed_jobs(
        self, generation_queue, generation_db_session
    ):
        """cleanup_stale_jobs does not touch completed/failed/cancelled jobs."""
        _reset_queue_state(generation_queue)

        async with generation_db_session() as session:
            job = await create_generation_job(
                session, generator_instance_id="stale-complete", status="completed"
            )
            job_id = job.id

        await generation_queue.cleanup_stale_jobs()

        result = await generation_queue.get_job(job_id)
        assert result["status"] == "completed"


# =============================================================================
# Fixtures for this test file
# =============================================================================


@pytest.fixture(autouse=True)
def clean_queue_state(generation_queue):
    """Reset queue internal state before each test."""
    _reset_queue_state(generation_queue)
    yield
    _reset_queue_state(generation_queue)

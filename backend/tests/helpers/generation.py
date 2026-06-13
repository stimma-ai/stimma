"""
Helpers for creating test generation data directly in the database.

These helpers bypass the generation pipeline for fast test setup.
Use when you need generated media items but don't care about testing generation itself.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from database import GenerationJob, MediaItem
from .media import create_media_item, generate_test_image


async def create_media_with_generation_metadata(
    session: AsyncSession,
    *,
    tool_id: str = "test:text-to-image:test-model",
    task_type: str = "text-to-image",
    prompt: str = "test prompt",
    negative_prompt: str = "",
    seed: int = 12345,
    steps: int = 20,
    cfg: float = 7.5,
    width: int = 512,
    height: int = 512,
    file_path: Optional[Path] = None,
    temp_dir: Optional[Path] = None,
    **kwargs,
) -> MediaItem:
    """Create a media item with valid generation_metadata for testing.

    Args:
        session: Database session
        tool_id: Tool ID that generated the media
        task_type: Type of generation task
        prompt: Generation prompt
        negative_prompt: Negative prompt
        seed: Random seed used
        steps: Number of steps
        cfg: CFG scale
        width: Image width
        height: Image height
        file_path: Optional explicit file path
        temp_dir: Optional directory to create real image file
        **kwargs: Additional args passed to create_media_item

    Returns:
        The created MediaItem with generation_metadata set
    """
    metadata = {
        "version": 3,
        "source": "stimma",
        "tool_id": tool_id,
        "task_type": task_type,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "parameters": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "width": width,
            "height": height,
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    # Create real file if temp_dir provided
    file_hash = None
    if temp_dir and not file_path:
        file_path = temp_dir / f"generated_{seed}.png"
        file_hash = generate_test_image(file_path, width=64, height=64)
    elif file_path and not file_path.exists():
        file_hash = generate_test_image(file_path, width=64, height=64)

    return await create_media_item(
        session,
        file_path=file_path,
        file_hash=file_hash,
        generation_metadata=json.dumps(metadata),
        extracted_prompt=prompt,
        tool_id=tool_id,
        width=width,
        height=height,
        **kwargs,
    )


async def create_generation_job(
    session: AsyncSession,
    *,
    tool_id: str = "test:text-to-image:test-model",
    task_type: str = "text-to-image",
    status: str = "queued",
    folder_path: str = "/fake/output",
    generator_instance_id: str = "test-instance",
    profile_id: str = "default",
    prompt: str = "test prompt",
    seed: int = 12345,
    steps: int = 20,
    cfg: float = 7.5,
    width: int = 512,
    height: int = 512,
    result_media_id: Optional[int] = None,
    error: Optional[str] = None,
) -> GenerationJob:
    """Create a generation job directly in the database.

    Args:
        session: Database session
        tool_id: Tool ID for generation
        task_type: Type of generation task
        status: Job status (queued, processing, completed, failed, cancelled)
        folder_path: Output folder path
        generator_instance_id: ID of generator instance
        profile_id: Profile owning the job
        prompt: Generation prompt
        seed: Random seed
        steps: Number of steps
        cfg: CFG scale
        width: Image width
        height: Image height
        result_media_id: Optional resulting media ID (for completed jobs)
        error: Optional error message (for failed jobs)

    Returns:
        The created GenerationJob
    """
    # Extract provider info from tool_id
    parts = tool_id.split(":")
    provider_id = parts[0] if parts else "test"
    model_name = parts[-1] if len(parts) > 1 else "test-model"

    # Single flat parameters dict (no input/parameters duality)
    parameters = json.dumps({
        "prompt": prompt,
        "negative_prompt": "",
        "width": width,
        "height": height,
        "seed": seed,
        "steps": steps,
        "cfg": cfg,
    })

    job = GenerationJob(
        status=status,
        task_type=task_type,
        generator_type="test",
        generator_name=provider_id,
        backend_name=provider_id,
        tool_id=tool_id,
        model_name=model_name,
        parameters=parameters,
        folder_path=folder_path,
        generator_instance_id=generator_instance_id,
        created_at=datetime.utcnow(),
        result_media_id=result_media_id,
        error=error,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    return job


async def wait_for_job_status(
    client: httpx.AsyncClient,
    job_id: int,
    expected_status: str,
    timeout: float = 5.0,
    poll_interval: float = 0.1,
) -> dict:
    """Poll job status until expected state or timeout.

    Args:
        client: HTTP client for API calls
        job_id: Job ID to poll
        expected_status: Status to wait for (completed, failed, cancelled)
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        Job dict when expected status is reached

    Raises:
        TimeoutError: If timeout reached before expected status
    """
    start = asyncio.get_event_loop().time()

    while True:
        response = await client.get(f"/api/generate/jobs/{job_id}")
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get job {job_id}: {response.status_code}")

        job = response.json()
        if job["status"] == expected_status:
            return job

        # Check timeout
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed >= timeout:
            raise TimeoutError(
                f"Job {job_id} did not reach status '{expected_status}' "
                f"within {timeout}s (current: '{job['status']}')"
            )

        await asyncio.sleep(poll_interval)


async def wait_for_job_completion(
    client: httpx.AsyncClient,
    job_id: int,
    timeout: float = 10.0,
) -> dict:
    """Wait for a job to complete (success or failure).

    Args:
        client: HTTP client for API calls
        job_id: Job ID to poll
        timeout: Maximum time to wait in seconds

    Returns:
        Job dict when job is no longer queued/processing

    Raises:
        TimeoutError: If timeout reached
    """
    start = asyncio.get_event_loop().time()

    while True:
        response = await client.get(f"/api/generate/jobs/{job_id}")
        if response.status_code != 200:
            raise RuntimeError(f"Failed to get job {job_id}: {response.status_code}")

        job = response.json()
        if job["status"] not in ("queued", "assigned", "processing"):
            return job

        elapsed = asyncio.get_event_loop().time() - start
        if elapsed >= timeout:
            raise TimeoutError(
                f"Job {job_id} did not complete within {timeout}s "
                f"(current: '{job['status']}')"
            )

        await asyncio.sleep(0.1)


async def process_job(generation_queue, job_id: int, profile_id: str = "default") -> None:
    """Process a specific job synchronously for testing.

    This is used in tests instead of background workers for deterministic behavior.

    Args:
        generation_queue: The GenerationQueue instance
        job_id: ID of the job to process
        profile_id: Profile ID where the job is stored
    """
    from database import GenerationJob
    from database_registry import get_database_registry

    # Get the job from the database
    registry = get_database_registry()
    db = registry.get_database(profile_id)

    async with db.async_session_maker() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status != "queued":
            raise ValueError(f"Job {job_id} is not queued (status: {job.status})")

        # Mark as assigned
        from datetime import datetime
        job.status = "assigned"
        job.assigned_at = datetime.utcnow()
        await session.commit()

    # Process the job using the queue's internal method
    # Refetch the job since we committed
    async with db.async_session_maker() as session:
        result = await session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        )
        job = result.scalar_one()

    await generation_queue._process_job(job, profile_id=profile_id)
    # Post-processing (media insert, lineage, metadata embed, completion) now runs
    # in a detached task so the GPU worker isn't blocked. Await it here so tests
    # observe the finished state deterministically.
    await generation_queue._await_finalizers()

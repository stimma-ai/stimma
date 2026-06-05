"""
Job waiting utilities for blocking tool execution.

Tools that create generation jobs need to wait for completion
before returning results to the agent.
"""

import asyncio
import json
import re
from core.logging import get_logger
from typing import List, Tuple, Literal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import GenerationJob, MediaItem
from .context import MediaRef

log = get_logger(__name__)


def _clean_job_error(error: str) -> str:
    """Extract human-readable details from a job error string (e.g. ComfyUI JSON blobs)."""
    if not error or len(error) < 200:
        return error

    # Extract "details" fields from ComfyUI node_errors JSON
    details = re.findall(r'"details":\s*"([^"]+)"', error)
    if details:
        unique = list(dict.fromkeys(details))
        return "; ".join(unique[:3])

    # Extract specific "message" fields (skip generic ones)
    messages = re.findall(r'"message":\s*"([^"]+)"', error)
    if messages:
        specific = [m for m in messages if "validation" not in m.lower()]
        if specific:
            unique = list(dict.fromkeys(specific))
            return "; ".join(unique[:3])

    return error[:300] + ("..." if len(error) > 300 else "")


async def wait_for_jobs(
    job_ids: List[int],
    session: AsyncSession,
    poll_interval: float = 0.5,
    timeout: float = 1800.0,  # 30 minutes stall timeout (not wall-clock) - resets on real progress
    status_checker: callable = None,  # Optional callback to check if we should stop
    progress_callback: callable = None,  # Optional callback for progress updates
) -> Tuple[List[int], List[str], int, dict]:
    """
    Wait for generation jobs to complete.

    IMPORTANT: This function does NOT use the passed session for polling.
    Instead, it creates fresh sessions for each poll to avoid holding a
    connection open, which can cause deadlocks with aiosqlite.
    The session parameter is kept for API compatibility and to get the
    database reference.

    Timeout behaviour:
        The timeout is a STALL timeout, not a wall-clock timeout. The timer
        resets whenever any job changes state (queued -> assigned -> processing
        -> done) or any job in the batch completes/fails. A job that remains in
        the same active state is not progress; otherwise provider-side hangs can
        spin forever.

    Args:
        job_ids: List of job IDs to wait for
        session: Database session (used to get session_maker reference)
        poll_interval: Seconds between status checks
        timeout: Stall timeout — max seconds with NO progress before giving up
        status_checker: Optional async callback that returns plan status.
                        If it returns 'interrupted', we cancel remaining jobs and return.
        progress_callback: Optional async callback(job_id, status, media_id) called when
                          a job completes, fails, or is cancelled.

    Returns:
        Tuple of (completed_media_ids, errors, cancelled_count, job_to_media)
        - completed_media_ids: Media IDs for successful jobs
        - errors: Error messages for failed jobs (not cancelled)
        - cancelled_count: Number of jobs cancelled by user
        - job_to_media: Dict mapping job_id -> media_id for completed jobs
    """
    if not job_ids:
        log.debug("No job IDs provided, returning immediately")
        return [], [], 0, {}

    log.info(f"Waiting for {len(job_ids)} jobs: {job_ids}")
    time_since_progress = 0.0
    completed_media_ids: List[int] = []
    job_to_media: dict = {}  # job_id -> media_id
    errors: List[str] = []
    cancelled_count = 0
    pending = set(job_ids)

    # Track last-known status per job so we can detect state transitions
    last_status: dict[int, str] = {jid: "queued" for jid in job_ids}

    # Get a fresh session maker from the database registry
    # This avoids holding a connection open during the entire polling period
    from database_registry import get_database_registry
    from core.profile_context import get_current_profile

    profile_id = get_current_profile()
    db = get_database_registry().get_database(profile_id)
    session_maker = db.async_session_maker

    poll_count = 0

    while pending and time_since_progress < timeout:
        await asyncio.sleep(poll_interval)
        time_since_progress += poll_interval
        poll_count += 1

        # Check if we should stop (plan cancelled/interrupted)
        if status_checker:
            status = await status_checker()
            if status == 'interrupted':
                log.info(f"[wait_for_jobs] Plan interrupted, cancelling {len(pending)} remaining jobs")
                # Cancel remaining pending jobs
                from generation_queue import get_generation_queue
                queue = get_generation_queue()
                for job_id in list(pending):
                    try:
                        await queue.cancel_job(job_id)
                        cancelled_count += 1
                        pending.discard(job_id)
                    except Exception as e:
                        log.warning(f"[wait_for_jobs] Failed to cancel job {job_id}: {e}")
                break

        # Use a fresh session for each poll - this is critical to avoid
        # deadlocks with aiosqlite which serializes all operations through
        # a single thread. A long-held session blocks other operations.
        async with session_maker() as poll_session:
            # Check status of pending jobs
            result = await poll_session.execute(
                select(GenerationJob).where(GenerationJob.id.in_(pending))
            )
            jobs = result.scalars().all()

            # Active states are useful diagnostics, but staying active without a
            # status transition is not progress. Providers can hang while a job
            # remains "processing", so only real transitions below reset the
            # stall timer.
            any_active = any(j.status in ("processing", "assigned") for j in jobs)

            # Log periodically (every ~30s) but only at debug level when active
            if poll_count % 60 == 0:  # every ~30s at 0.5s poll interval
                statuses = {j.id: j.status for j in jobs}
                if any_active:
                    log.debug(f"[wait_for_jobs] Active, stalled={time_since_progress:.0f}s/{timeout}s, pending={pending}, statuses={statuses}")
                else:
                    backend_names = set()
                    for j in jobs:
                        if hasattr(j, 'backend_name') and j.backend_name:
                            backend_names.add(j.backend_name)
                    log.warning(f"[wait_for_jobs] Stall={time_since_progress:.0f}s/{timeout}s, pending={pending}, statuses={statuses}, backends={backend_names}, profile={profile_id}")

            for job in jobs:
                # Detect state transitions → reset stall timer
                prev = last_status.get(job.id)
                if prev is not None and job.status != prev:
                    log.debug(f"Job {job.id} state change: {prev} → {job.status}")
                    time_since_progress = 0.0
                last_status[job.id] = job.status

                if job.status == "completed":
                    pending.discard(job.id)
                    time_since_progress = 0.0  # a job finished — reset stall timer
                    log.info(f"Job {job.id} completed, media_id={job.result_media_id}")
                    if job.result_media_id:
                        completed_media_ids.append(job.result_media_id)
                        job_to_media[job.id] = job.result_media_id
                    # Call progress callback
                    if progress_callback:
                        try:
                            await progress_callback(job.id, "complete", job.result_media_id)
                        except Exception as e:
                            log.warning(f"Progress callback failed: {e}")

                elif job.status == "cancelled":
                    pending.discard(job.id)
                    time_since_progress = 0.0
                    log.info(f"[wait_for_jobs] Job {job.id} cancelled by user")
                    cancelled_count += 1
                    if progress_callback:
                        try:
                            await progress_callback(job.id, "cancelled", None)
                        except Exception as e:
                            log.warning(f"Progress callback failed: {e}")

                elif job.status == "failed":
                    pending.discard(job.id)
                    time_since_progress = 0.0
                    log.warning(f"[wait_for_jobs] Job {job.id} failed: {job.error}")
                    errors.append(f"Job {job.id}: {_clean_job_error(job.error) if job.error else 'failed'}")
                    if progress_callback:
                        try:
                            await progress_callback(job.id, "failed", None)
                        except Exception as e:
                            log.warning(f"Progress callback failed: {e}")
            # Session closes here at end of `async with` block

    # Handle timeout — log diagnostic info
    if pending:
        try:
            from backend_registry import get_backend_registry
            backends = await get_backend_registry().list_backends()
            log.error(f"[wait_for_jobs] TIMEOUT — no progress for {timeout}s. pending={list(pending)}, registered_backends={list(backends.keys())}, backend_states={{k: {{'available': v['is_available'], 'busy': v['is_busy'], 'jobs': v['current_jobs']}} for k, v in backends.items()}}")
        except Exception:
            log.error(f"[wait_for_jobs] TIMEOUT — no progress for {timeout}s. pending={list(pending)}")
        errors.append(f"Timeout waiting for jobs (no progress for {timeout}s): {list(pending)}")

    return completed_media_ids, errors, cancelled_count, job_to_media


async def get_job_status(job_id: int, session: AsyncSession) -> str | None:
    """Get the current status of a job."""
    result = await session.execute(
        select(GenerationJob.status).where(GenerationJob.id == job_id)
    )
    return result.scalar_one_or_none()


async def create_media_refs(
    media_ids: List[int],
    media_type: Literal["image", "video"],
    session: AsyncSession,
    prompt: str | None = None,
    prompts: dict | None = None,  # media_id -> prompt
) -> List[MediaRef]:
    """
    Create MediaRefs with context for the given media IDs.

    Fetches VLM captions from the database and attaches them to the refs.
    This enables verbal references like "the red one" to work.

    Args:
        media_ids: List of media IDs
        media_type: "image" or "video"
        session: Database session
        prompt: Single prompt for all media (fallback)
        prompts: Dict mapping media_id -> prompt for per-image prompts

    Returns:
        List of MediaRef objects with prompt and ai_caption populated
    """
    if not media_ids:
        return []

    # Fetch media items to get their VLM captions
    result = await session.execute(
        select(MediaItem.id, MediaItem.vlm_caption).where(MediaItem.id.in_(media_ids))
    )
    rows = result.fetchall()
    caption_map = {row.id: row.vlm_caption for row in rows}

    return [
        MediaRef(
            media_id=media_id,
            media_type=media_type,
            prompt=(prompts or {}).get(media_id) or prompt,
            ai_caption=caption_map.get(media_id),
        )
        for media_id in media_ids
    ]

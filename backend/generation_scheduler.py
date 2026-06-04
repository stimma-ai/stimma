"""
Generation scheduler for fair distribution of jobs across backends.
"""

import asyncio
from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import GenerationJob
from database_registry import get_database_registry
from backend_registry import get_backend_registry
from core.profile_context import get_current_profile

log = get_logger(__name__)


class GenerationScheduler:
    """
    Scheduler for distributing generation jobs across backends using round-robin.

    This scheduler maintains per-generator queues and round-robins across schedulable
    generators to fairly distribute work across backends while respecting backend
    capacity limits.

    Jobs are stored per-profile for complete database isolation.
    """

    def __init__(self):
        self.backend_registry = get_backend_registry()
        self._lock = asyncio.Lock()
        # Track the last generator we served for each backend (for round-robin)
        self._last_served_generator: Dict[str, Optional[str]] = {}

    def _get_jobs_db(self, profile_id: str = None):
        """Get database for generation jobs for a specific profile.

        Args:
            profile_id: Profile ID to get database for. If None, uses current profile.
        """
        if profile_id is None:
            profile_id = get_current_profile()
        return get_database_registry().get_database(profile_id)

    def _get_all_jobs_dbs(self) -> List[tuple]:
        """Get all profile databases for aggregated queue status.

        Returns:
            List of (profile_id, Database) tuples for all active profiles
        """
        registry = get_database_registry()
        profiles = registry.list_profiles()
        return [(p['id'], registry.get_database(p['id'])) for p in profiles]

    async def assign_next_job(self, backend_name: str, worker_id: str, profile_id: str = None) -> Optional[GenerationJob]:
        """
        Assign the next job to a worker for a specific backend and profile.

        Uses round-robin across generator instances to ensure fair distribution.

        Args:
            backend_name: Name of the backend that will process the job
            worker_id: ID of the worker requesting a job
            profile_id: Profile database to search for jobs

        Returns:
            GenerationJob if one is available and assigned, None otherwise
        """
        async with self._lock:
            # Check if backend can accept more jobs
            if not await self.backend_registry.get_backend_for_job(backend_name):
                return None

            db = self._get_jobs_db(profile_id)
            async with db.async_session_maker() as session:
                # Get the last generator we served for this backend
                last_generator = self._last_served_generator.get(backend_name)

                # Find all generators with queued jobs for this backend
                # Get distinct generator_instance_ids with queued jobs
                query = select(GenerationJob.generator_instance_id).where(
                    and_(
                        GenerationJob.status == 'queued',
                        GenerationJob.backend_name == backend_name
                    )
                ).distinct().order_by(GenerationJob.generator_instance_id)

                result = await session.execute(query)
                generator_ids = [row[0] for row in result.fetchall()]

                if not generator_ids:
                    return None

                # Round-robin: find the next generator after the last one we served
                next_generator = None
                if last_generator and last_generator in generator_ids:
                    # Find the next generator in the list after last_generator
                    idx = generator_ids.index(last_generator)
                    next_idx = (idx + 1) % len(generator_ids)
                    next_generator = generator_ids[next_idx]
                else:
                    # Start with the first generator
                    next_generator = generator_ids[0]

                # Get the oldest queued job for this generator on this backend
                job_query = select(GenerationJob).where(
                    and_(
                        GenerationJob.status == 'queued',
                        GenerationJob.backend_name == backend_name,
                        GenerationJob.generator_instance_id == next_generator
                    )
                ).order_by(GenerationJob.created_at).limit(1)

                result = await session.execute(job_query)
                job = result.scalar_one_or_none()

                if not job:
                    return None

                # Assign the job
                job.status = 'assigned'
                job.assigned_at = datetime.utcnow()
                job.worker_id = worker_id

                # Try to assign in backend registry
                if await self.backend_registry.assign_job(backend_name, job.id):
                    await session.commit()

                    # Update last served generator
                    self._last_served_generator[backend_name] = next_generator

                    # Refresh the job to get updated data
                    await session.refresh(job)
                    log.debug(f"Job {job.id} assigned, auto_delete_duration={repr(job.auto_delete_duration)}")
                    return job
                else:
                    # Backend couldn't accept the job, rollback
                    await session.rollback()
                    return None

    async def on_job_completed(self, job_id: int, backend_name: str):
        """
        Callback when a job completes or fails.

        This triggers the scheduler to find more work and release backend capacity.

        Args:
            job_id: ID of the completed job
            backend_name: Name of the backend that processed the job
        """
        # Release the job from backend registry
        await self.backend_registry.release_job(backend_name, job_id)

        # The worker loop will automatically pick up the next job
        # No explicit scheduling action needed here

    async def get_queue_status(self) -> Dict:
        """
        Get overall queue status across all profiles, generators, and backends.

        Returns:
            Dict with queue statistics aggregated across all profiles
        """
        status_counts = {'queued': 0, 'assigned': 0, 'processing': 0}
        generator_counts = {}
        profile_counts = {}

        # Aggregate across all profile databases
        for profile_id, db in self._get_all_jobs_dbs():
            async with db.async_session_maker() as session:
                # Count jobs by status
                query = select(GenerationJob.status, GenerationJob.generator_instance_id).where(
                    GenerationJob.status.in_(['queued', 'assigned', 'processing'])
                )
                result = await session.execute(query)
                jobs = result.fetchall()

                profile_job_count = 0
                for status, generator_id in jobs:
                    status_counts[status] += 1
                    profile_job_count += 1
                    if generator_id not in generator_counts:
                        generator_counts[generator_id] = {'queued': 0, 'assigned': 0, 'processing': 0}
                    generator_counts[generator_id][status] += 1

                if profile_job_count > 0:
                    profile_counts[profile_id] = profile_job_count

        # Get backend status
        backends = await self.backend_registry.list_backends()

        return {
            'total_queued': status_counts['queued'],
            'total_assigned': status_counts['assigned'],
            'total_processing': status_counts['processing'],
            'by_generator': generator_counts,
            'by_profile': profile_counts,
            'backends': backends,
        }


# Global scheduler instance
_scheduler: Optional[GenerationScheduler] = None


def get_scheduler() -> GenerationScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = GenerationScheduler()
    return _scheduler

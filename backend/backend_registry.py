"""
Backend registry for managing generation backend availability and capacity.
"""

import asyncio
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime

from config import get_settings


@dataclass
class BackendState:
    """State tracking for a single backend."""
    name: str
    max_concurrent: int
    current_jobs: Set[int] = field(default_factory=set)  # Set of job IDs currently processing
    is_available: bool = True
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None

    @property
    def available_slots(self) -> int:
        """Number of available processing slots."""
        return max(0, self.max_concurrent - len(self.current_jobs))

    @property
    def is_busy(self) -> bool:
        """Whether backend is at capacity."""
        return len(self.current_jobs) >= self.max_concurrent

    def can_accept_job(self) -> bool:
        """Whether backend can accept a new job."""
        return self.is_available and not self.is_busy


class BackendRegistry:
    """
    Registry for tracking backend availability and capacity.

    This class manages the state of all generation backends (e.g., ComfyUI instances),
    tracking which backends are available, how many jobs each can handle concurrently,
    and which jobs are currently running on each backend.
    """

    def __init__(self):
        self.backends: Dict[str, BackendState] = {}
        self._lock = asyncio.Lock()
        self._load_backends()

    def _load_backends(self):
        """Load backend configurations from settings."""
        settings = get_settings()

        for gen_config in settings.generators:
            # Use generator name as backend name
            # In the future, you might have multiple backends of the same type
            backend_name = gen_config.name

            # Get max_concurrent from config, default to 2 for backward compatibility
            max_concurrent = getattr(gen_config, 'max_concurrent', 2)

            self.backends[backend_name] = BackendState(
                name=backend_name,
                max_concurrent=max_concurrent
            )

    async def register_backend(self, backend_name: str, max_concurrent: int = 1) -> None:
        """
        Dynamically register a backend (e.g., a JSON-RPC tool provider).

        If the backend already exists (e.g., from config), updates its max_concurrent
        to match what the provider reports.

        Args:
            backend_name: Unique name for this backend
            max_concurrent: Maximum concurrent jobs this backend can handle
        """
        async with self._lock:
            if backend_name not in self.backends:
                self.backends[backend_name] = BackendState(
                    name=backend_name,
                    max_concurrent=max_concurrent
                )
            else:
                # Update max_concurrent for existing backend (provider may report different value)
                old_value = self.backends[backend_name].max_concurrent
                self.backends[backend_name].max_concurrent = max_concurrent
                if old_value != max_concurrent:
                    from core.logging import get_logger
                    log = get_logger(__name__)
                    log.info(f"Backend {backend_name}: updated max_concurrent from {old_value} to {max_concurrent}")

    async def unregister_backend(self, backend_name: str) -> None:
        """
        Unregister a dynamically registered backend.

        Args:
            backend_name: Name of the backend to remove
        """
        async with self._lock:
            self.backends.pop(backend_name, None)

    async def get_available_backend(self) -> Optional[str]:
        """
        Get the name of an available backend that can accept a job.

        Returns:
            Backend name if one is available, None otherwise
        """
        async with self._lock:
            for backend_name, state in self.backends.items():
                if state.can_accept_job():
                    return backend_name
            return None

    async def get_backend_for_job(self, backend_name: str) -> Optional[str]:
        """
        Check if a specific backend can accept a job.

        Args:
            backend_name: Name of the backend to check

        Returns:
            Backend name if available, None otherwise
        """
        async with self._lock:
            state = self.backends.get(backend_name)
            if state and state.can_accept_job():
                return backend_name
            return None

    async def assign_job(self, backend_name: str, job_id: int) -> bool:
        """
        Assign a job to a backend.

        Args:
            backend_name: Name of the backend
            job_id: ID of the job to assign

        Returns:
            True if assignment successful, False otherwise
        """
        async with self._lock:
            state = self.backends.get(backend_name)
            if not state or not state.can_accept_job():
                return False

            state.current_jobs.add(job_id)
            return True

    async def release_job(self, backend_name: str, job_id: int):
        """
        Release a job from a backend when it completes or fails.

        Args:
            backend_name: Name of the backend
            job_id: ID of the job to release
        """
        async with self._lock:
            state = self.backends.get(backend_name)
            if state and job_id in state.current_jobs:
                state.current_jobs.discard(job_id)

    async def mark_backend_error(self, backend_name: str, error: str):
        """
        Mark a backend as having an error.

        Args:
            backend_name: Name of the backend
            error: Error message
        """
        async with self._lock:
            state = self.backends.get(backend_name)
            if state:
                state.last_error = error
                state.last_error_at = datetime.utcnow()
                # For now, don't disable backend on error
                # In the future, you might want to implement health checking

    async def get_backend_state(self, backend_name: str) -> Optional[BackendState]:
        """
        Get the current state of a backend.

        Args:
            backend_name: Name of the backend

        Returns:
            BackendState if backend exists, None otherwise
        """
        async with self._lock:
            return self.backends.get(backend_name)

    async def list_backends(self) -> Dict[str, Dict]:
        """
        List all backends with their current state.

        Returns:
            Dict mapping backend name to state info
        """
        async with self._lock:
            return {
                name: {
                    "name": state.name,
                    "max_concurrent": state.max_concurrent,
                    "current_jobs": len(state.current_jobs),
                    "available_slots": state.available_slots,
                    "is_available": state.is_available,
                    "is_busy": state.is_busy,
                    "last_error": state.last_error,
                    "last_error_at": state.last_error_at.isoformat() if state.last_error_at else None,
                }
                for name, state in self.backends.items()
            }


# Global registry instance
_backend_registry: Optional[BackendRegistry] = None


def get_backend_registry() -> BackendRegistry:
    """Get or create the global backend registry instance."""
    global _backend_registry
    if _backend_registry is None:
        _backend_registry = BackendRegistry()
    return _backend_registry

"""
Profile context management for multi-profile support.

Uses contextvars for async code and thread-local storage for generation workers.
"""
from contextvars import ContextVar
import threading
from typing import Optional

# Context variable for current profile - works across async/await boundaries
profile_context: ContextVar[Optional[str]] = ContextVar('profile_context', default=None)

# Thread-local storage for generation workers (contextvars don't propagate to new threads)
_thread_local = threading.local()


def get_current_profile() -> str:
    """
    Get the current profile ID.

    Checks contextvar first (for async code), then falls back to thread-local
    storage (for generation workers running in threads).

    Falls back to the first configured/registered profile if no context is set.
    Raises RuntimeError if no profiles are available.
    """
    # First check contextvar (for async code)
    profile = profile_context.get()
    if profile is not None:
        return profile

    # Fall back to thread-local (for generation workers)
    thread_profile = getattr(_thread_local, 'profile_id', None)
    if thread_profile is not None:
        return thread_profile

    # Fallback: first registered profile (registry order follows config order)
    try:
        from database_registry import get_database_registry
        registry = get_database_registry()
        profiles = registry.list_profiles()
        if profiles:
            return profiles[0]["id"]
    except Exception:
        pass

    # Secondary fallback: first configured profile from settings
    try:
        from config import get_settings
        settings = get_settings()
        if settings.profiles:
            return settings.profiles[0].id
    except Exception:
        pass

    raise RuntimeError("No profile context is set and no profiles are configured")


def set_current_profile(profile_id: str) -> None:
    """Set the current profile ID in contextvar (for async code)."""
    profile_context.set(profile_id)


def set_thread_profile(profile_id: Optional[str]) -> None:
    """
    Set the current profile ID for thread-local storage.

    Used by generation workers running in threads where contextvars
    don't automatically propagate.

    Pass None to clear the thread profile.
    """
    if profile_id is None:
        if hasattr(_thread_local, 'profile_id'):
            delattr(_thread_local, 'profile_id')
    else:
        _thread_local.profile_id = profile_id


class ProfileScope:
    """
    Context manager for setting profile context in a scope.

    Usage:
        with ProfileScope(profile_id):
            # Code here runs with profile_id set
            pass
    """

    def __init__(self, profile_id: str, use_thread_local: bool = False):
        """
        Initialize profile scope.

        Args:
            profile_id: The profile ID to set
            use_thread_local: If True, use thread-local storage instead of contextvar
        """
        self.profile_id = profile_id
        self.use_thread_local = use_thread_local
        self._token = None
        self._old_thread_profile = None

    def __enter__(self):
        if self.use_thread_local:
            self._old_thread_profile = getattr(_thread_local, 'profile_id', None)
            set_thread_profile(self.profile_id)
        else:
            self._token = profile_context.set(self.profile_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.use_thread_local:
            set_thread_profile(self._old_thread_profile)
        elif self._token is not None:
            profile_context.reset(self._token)
        return False

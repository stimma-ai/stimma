"""Shared dependencies for FastAPI routes."""
from fastapi import HTTPException
from core.profile_context import get_current_profile
from core.logging import get_logger
from database_registry import get_database_registry

log = get_logger(__name__)


async def get_db_session():
    """
    Dependency to get database session for the current profile.

    Uses the profile context (set by middleware) to determine which
    profile's database to use.
    """
    try:
        profile_id = get_current_profile()
        registry = get_database_registry()
        db = registry.get_database(profile_id)
    except Exception as e:
        log.error(f"get_db_session ERROR: {e}", exc_info=True)
        raise

    async for session in db.get_session():
        yield session

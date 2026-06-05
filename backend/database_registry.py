"""
Database registry for multi-profile support.

Manages multiple Database instances, one per profile.
"""
import threading
from typing import Dict, List, Optional

from database import Database
from config import ProfileConfig


class DatabaseRegistry:
    """
    Registry that manages multiple Database instances, one per profile.

    Thread-safe singleton that lazy-creates Database instances as needed.
    """

    def __init__(self):
        self._databases: Dict[str, Database] = {}
        self._configs: Dict[str, ProfileConfig] = {}
        self._lock = threading.Lock()

    def register_profile(self, config: ProfileConfig) -> None:
        """
        Register a profile configuration.

        Args:
            config: The profile configuration containing id, name, database path, etc.
        """
        with self._lock:
            self._configs[config.id] = config

    def get_database(self, profile_id: str) -> Database:
        """
        Get or create a Database instance for a profile.

        Args:
            profile_id: The profile ID to get the database for

        Returns:
            Database instance for the profile

        Raises:
            ValueError: If the profile is not registered
        """
        # Fast path without lock
        if profile_id in self._databases:
            return self._databases[profile_id]

        # Slow path with lock
        with self._lock:
            # Double-check after acquiring lock
            if profile_id not in self._databases:
                config = self._configs.get(profile_id)
                if not config:
                    raise ValueError(f"Unknown profile: {profile_id}")
                self._databases[profile_id] = Database(config.database)

        return self._databases[profile_id]

    async def init_database(self, profile_id: str) -> None:
        """
        Initialize a specific profile's database.

        Args:
            profile_id: The profile ID to initialize
        """
        db = self.get_database(profile_id)
        await db.init_db()

    async def init_all_databases(self) -> None:
        """Initialize all registered profile databases."""
        from core.logging import get_logger
        log = get_logger(__name__)
        for profile_id in self._configs:
            log.info(f"REGISTRY: Initializing database for profile '{profile_id}'...")
            await self.init_database(profile_id)
            log.info(f"REGISTRY: Database initialized for profile '{profile_id}'")

    async def unregister_profile(self, profile_id: str) -> None:
        """
        Unregister a profile and dispose its database connection.

        Args:
            profile_id: The profile ID to unregister
        """
        from core.logging import get_logger
        log = get_logger(__name__)

        with self._lock:
            # Remove from configs
            if profile_id in self._configs:
                del self._configs[profile_id]
                log.info(f"REGISTRY: Removed config for profile '{profile_id}'")

            # Dispose and remove database connection
            if profile_id in self._databases:
                db = self._databases[profile_id]
                try:
                    await db.async_engine.dispose()
                    log.info(f"REGISTRY: Disposed database for profile '{profile_id}'")
                except Exception as e:
                    log.error(f"REGISTRY: Error disposing database for '{profile_id}': {e}")
                del self._databases[profile_id]

    async def dispose_all(self) -> None:
        """Dispose all database engines."""
        for db in self._databases.values():
            await db.async_engine.dispose()

    def list_profiles(self) -> List[dict]:
        """
        List all registered profiles in config.yaml order.

        Returns:
            List of profile info dicts with id, name, and database fields
        """
        from config import get_settings
        settings = get_settings()
        # Return profiles in the order defined in settings (config.yaml order)
        return [
            {
                "id": profile.id,
                "name": profile.name,
                "database": profile.database,
            }
            for profile in settings.profiles
            if profile.id in self._configs
        ]

    def get_profile_config(self, profile_id: str) -> Optional[ProfileConfig]:
        """
        Get the configuration for a profile.

        Args:
            profile_id: The profile ID

        Returns:
            ProfileConfig or None if not found
        """
        return self._configs.get(profile_id)

    def has_profile(self, profile_id: str) -> bool:
        """
        Check if a profile is registered.

        Args:
            profile_id: The profile ID to check

        Returns:
            True if the profile exists
        """
        return profile_id in self._configs

    def get_db_guid(self, profile_id: str) -> str:
        """
        Get the database GUID for a profile.

        Args:
            profile_id: The profile ID

        Returns:
            The unique database identifier (8-char UUID)

        Raises:
            ValueError: If the profile is not registered or database not initialized
        """
        db = self.get_database(profile_id)
        return db.db_guid

    def get_profile_by_db_guid(self, db_guid: str) -> Optional[str]:
        """
        Look up a profile ID by its database GUID.

        Args:
            db_guid: The database GUID to look up

        Returns:
            The profile ID, or None if not found
        """
        for profile_id, db in self._databases.items():
            if db._db_guid == db_guid:
                return profile_id
        return None


# Global registry instance
_registry: Optional[DatabaseRegistry] = None


def get_database_registry() -> DatabaseRegistry:
    """
    Get or create the global database registry.

    Returns:
        The global DatabaseRegistry singleton
    """
    global _registry
    if _registry is None:
        _registry = DatabaseRegistry()
    return _registry

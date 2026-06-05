"""Tests for DatabaseRegistry (database_registry.py)."""

import threading
import pytest
from unittest.mock import patch, MagicMock

from config import ProfileConfig
from database import Database
from database_registry import DatabaseRegistry, get_database_registry, _registry


def make_profile(profile_id: str, db_path: str) -> ProfileConfig:
    """Create a minimal ProfileConfig for testing."""
    return ProfileConfig(
        id=profile_id,
        name=f"Test {profile_id}",
        database=db_path,
    )


@pytest.fixture
def registry():
    """Fresh DatabaseRegistry per test."""
    return DatabaseRegistry()


@pytest.fixture
def profile_a(tmp_path):
    """ProfileConfig pointing to a temp DB file."""
    return make_profile("profile_a", str(tmp_path / "a.db"))


@pytest.fixture
def profile_b(tmp_path):
    """ProfileConfig pointing to a second temp DB file."""
    return make_profile("profile_b", str(tmp_path / "b.db"))


class TestRegisterAndHasProfile:

    def test_has_profile_after_register(self, registry, profile_a):
        registry.register_profile(profile_a)
        assert registry.has_profile("profile_a") is True

    def test_has_profile_unknown(self, registry):
        assert registry.has_profile("nonexistent") is False


class TestGetDatabase:

    def test_returns_database_instance(self, registry, profile_a):
        registry.register_profile(profile_a)
        db = registry.get_database("profile_a")
        assert isinstance(db, Database)

    def test_same_instance_on_repeated_calls(self, registry, profile_a):
        registry.register_profile(profile_a)
        db1 = registry.get_database("profile_a")
        db2 = registry.get_database("profile_a")
        assert db1 is db2

    def test_raises_for_unknown_profile(self, registry):
        with pytest.raises(ValueError, match="Unknown profile"):
            registry.get_database("nonexistent")

    def test_thread_safety(self, registry, profile_a):
        """Concurrent get_database calls from multiple threads return same instance."""
        registry.register_profile(profile_a)
        results = []
        errors = []

        def get_db():
            try:
                results.append(registry.get_database("profile_a"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_db) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 10
        assert all(r is results[0] for r in results)


class TestInitDatabase:

    async def test_init_database_creates_guid(self, registry, profile_a):
        registry.register_profile(profile_a)
        # Create tables first
        db = registry.get_database("profile_a")
        from database import Base
        async with db.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        await registry.init_database("profile_a")
        guid = registry.get_db_guid("profile_a")
        assert isinstance(guid, str)
        assert len(guid) == 8

    async def test_init_all_databases(self, registry, profile_a, profile_b):
        registry.register_profile(profile_a)
        registry.register_profile(profile_b)

        # Create tables for both
        from database import Base
        for pid in ["profile_a", "profile_b"]:
            db = registry.get_database(pid)
            async with db.async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        await registry.init_all_databases()
        assert len(registry.get_db_guid("profile_a")) == 8
        assert len(registry.get_db_guid("profile_b")) == 8


class TestUnregisterProfile:

    async def test_unregister_removes_profile(self, registry, profile_a):
        registry.register_profile(profile_a)
        _ = registry.get_database("profile_a")  # Force creation
        await registry.unregister_profile("profile_a")
        assert registry.has_profile("profile_a") is False

    async def test_get_database_raises_after_unregister(self, registry, profile_a):
        registry.register_profile(profile_a)
        _ = registry.get_database("profile_a")
        await registry.unregister_profile("profile_a")
        with pytest.raises(ValueError, match="Unknown profile"):
            registry.get_database("profile_a")

    async def test_unregister_nonexistent_is_noop(self, registry):
        """Unregistering a profile that doesn't exist should not raise."""
        await registry.unregister_profile("nonexistent")


class TestDisposeAll:

    async def test_dispose_all(self, registry, profile_a, profile_b):
        registry.register_profile(profile_a)
        registry.register_profile(profile_b)
        _ = registry.get_database("profile_a")
        _ = registry.get_database("profile_b")
        # Should not raise
        await registry.dispose_all()
        # Profiles still registered (dispose != unregister)
        assert registry.has_profile("profile_a") is True
        assert registry.has_profile("profile_b") is True


class TestGetProfileConfig:

    def test_returns_config(self, registry, profile_a):
        registry.register_profile(profile_a)
        config = registry.get_profile_config("profile_a")
        assert config is profile_a

    def test_returns_none_for_unknown(self, registry):
        assert registry.get_profile_config("nonexistent") is None


class TestGuidLookup:

    async def test_get_db_guid(self, registry, profile_a):
        registry.register_profile(profile_a)
        db = registry.get_database("profile_a")
        from database import Base
        async with db.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await registry.init_database("profile_a")

        guid = registry.get_db_guid("profile_a")
        assert isinstance(guid, str)
        assert len(guid) == 8

    async def test_get_profile_by_db_guid(self, registry, profile_a):
        registry.register_profile(profile_a)
        db = registry.get_database("profile_a")
        from database import Base
        async with db.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await registry.init_database("profile_a")

        guid = registry.get_db_guid("profile_a")
        assert registry.get_profile_by_db_guid(guid) == "profile_a"

    async def test_get_profile_by_unknown_guid(self, registry):
        assert registry.get_profile_by_db_guid("unknown") is None


class TestListProfiles:

    def test_list_profiles_in_config_order(self, registry, profile_a, profile_b):
        """list_profiles returns profiles in the order from settings."""
        registry.register_profile(profile_b)
        registry.register_profile(profile_a)

        mock_settings = MagicMock()
        # Settings returns profiles in b, a order
        mock_settings.profiles = [profile_b, profile_a]

        with patch("config.get_settings", return_value=mock_settings):
            profiles = registry.list_profiles()

        assert len(profiles) == 2
        assert profiles[0]["id"] == "profile_b"
        assert profiles[1]["id"] == "profile_a"

    def test_list_profiles_excludes_unregistered(self, registry, profile_a, profile_b):
        """Only registered profiles appear in the list."""
        registry.register_profile(profile_a)

        mock_settings = MagicMock()
        mock_settings.profiles = [profile_a, profile_b]

        with patch("config.get_settings", return_value=mock_settings):
            profiles = registry.list_profiles()

        assert len(profiles) == 1
        assert profiles[0]["id"] == "profile_a"


class TestGlobalSingleton:

    def test_get_database_registry_returns_same_instance(self):
        """get_database_registry returns the same singleton."""
        import database_registry as mod
        old = mod._registry
        try:
            mod._registry = None  # Reset
            r1 = mod.get_database_registry()
            r2 = mod.get_database_registry()
            assert r1 is r2
        finally:
            mod._registry = old  # Restore

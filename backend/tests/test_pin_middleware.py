"""
Tests for PIN-protected profile middleware.

Verifies that:
- Profiles with PIN require X-Profile-PIN header
- Requests without PIN header get 403
- Requests with invalid PIN get 403
- Requests with valid PIN succeed
- PIN-exempt routes don't require PIN
"""

import asyncio
import bcrypt
import pytest
from pathlib import Path
from unittest.mock import patch

import httpx
from httpx import ASGITransport


# Config with PIN-protected profile
PIN_CONFIG = """
server:
  port: 0
  log_level: WARNING

clip:
  model: ViT-g-14
  pretrained: laion2b_s12b_b42k
  batch_size: 50

face_detection:
  enabled: false

profiles:
  - id: protected
    name: Protected Profile
    database: stimma_test.db
    pin_hash: "{pin_hash}"
    pin_idle_timeout_minutes: 30
    folders: []
    markers:
      - name: favorite
        icon_svg: heroicon:heart
        color: "#ef4444"
  - id: unprotected
    name: Unprotected Profile
    database: stimma_unprotected.db
    folders: []
    markers: []

generators: []
tool_providers: []
llms: {{}}
"""

# Test PIN (in real usage this would be hashed)
TEST_PIN = "1234"


def _create_app_dirs_patches(temp_dir: Path):
    """Create mock functions for app_dirs that use the temp directory."""

    def mock_get_data_dir(modifier: str = "") -> Path:
        return temp_dir

    def mock_get_cache_dir(modifier: str = "") -> Path:
        cache_dir = temp_dir / "cache"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir

    def mock_get_config_path(modifier: str = "") -> Path:
        return temp_dir / "config.yaml"

    def mock_get_profile_dir(profile_id: str = "default") -> Path:
        profile_dir = temp_dir / profile_id
        profile_dir.mkdir(exist_ok=True)
        return profile_dir

    def mock_get_database_path(profile_id: str = "default") -> Path:
        return mock_get_profile_dir(profile_id) / "stimma_v1.db"

    def mock_get_thumbnail_cache_dir(modifier: str = "") -> Path:
        thumb_dir = mock_get_cache_dir(modifier) / "thumbnails"
        thumb_dir.mkdir(exist_ok=True)
        return thumb_dir

    def mock_get_uploads_dir(modifier: str = "") -> Path:
        uploads_dir = mock_get_cache_dir(modifier) / "uploads"
        uploads_dir.mkdir(exist_ok=True)
        return uploads_dir

    return {
        "get_data_dir": mock_get_data_dir,
        "get_cache_dir": mock_get_cache_dir,
        "get_config_path": mock_get_config_path,
        "get_profile_dir": mock_get_profile_dir,
        "get_database_path": mock_get_database_path,
        "get_thumbnail_cache_dir": mock_get_thumbnail_cache_dir,
        "get_uploads_dir": mock_get_uploads_dir,
    }


@pytest.fixture(scope="module")
def pin_temp_dir(tmp_path_factory) -> Path:
    """Create a temp directory with PIN-protected profile config."""
    base_dir = tmp_path_factory.mktemp("stimma_pin_test")

    # Hash the test PIN
    pin_hash = bcrypt.hashpw(TEST_PIN.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Create config with hashed PIN
    config_content = PIN_CONFIG.format(pin_hash=pin_hash)
    config_path = base_dir / "config.yaml"
    config_path.write_text(config_content)

    # Create profile directories
    (base_dir / "protected").mkdir(exist_ok=True)
    (base_dir / "unprotected").mkdir(exist_ok=True)

    return base_dir


@pytest.fixture(scope="module")
async def pin_app(pin_temp_dir: Path):
    """Create a FastAPI test app with PIN-protected profile."""
    patches = _create_app_dirs_patches(pin_temp_dir)

    with patch.multiple("app_dirs", **patches):
        # Reset singletons
        import database_registry
        database_registry._registry = None

        import config
        config.settings = None

        # Import and initialize
        from config import reload_settings
        from database_registry import get_database_registry
        from utils.migrations import run_all_migrations
        from core.app import create_app

        settings = reload_settings()
        run_all_migrations()

        registry = get_database_registry()
        for profile in settings.profiles:
            registry.register_profile(profile)
        await registry.init_all_databases()

        app = create_app()

        # Include routers
        from routes import media, media_files, package_media, profiles
        from routes import settings as settings_routes
        app.include_router(media.router)
        app.include_router(media_files.router, prefix="/api")
        app.include_router(package_media.router, prefix="/api")
        app.include_router(profiles.router)
        app.include_router(settings_routes.router)

        @app.get("/")
        async def root():
            return {"status": "ok"}

        yield app

        await registry.dispose_all()


@pytest.fixture(scope="module")
async def pin_client(pin_app) -> httpx.AsyncClient:
    """Create an httpx AsyncClient without default headers."""
    transport = ASGITransport(app=pin_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture(scope="module")
def event_loop():
    """Create an event loop for the test module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Tests
# =============================================================================


class TestPinMiddleware:
    """Tests for PIN-protected profile middleware."""

    async def test_config_has_pin_hash(self, pin_client):
        """Verify the test config has PIN hash loaded correctly."""
        from config import get_settings
        settings = get_settings()
        protected = settings.get_profile("protected")
        assert protected is not None, "Protected profile not found"
        assert protected.pin_hash is not None, f"PIN hash is None. Profile: {protected}"

    async def test_middleware_is_working(self, pin_client):
        """Test that middleware is actually being called by checking that requests without profile ID fail."""
        # Make a request without X-Profile-ID header - should get 400
        response = await pin_client.get("/api/media", headers={})
        assert response.status_code == 400, f"Expected 400 without profile ID, got {response.status_code}. Body: {response.text}"

    async def test_protected_profile_without_pin_returns_403(self, pin_client):
        """Request to protected profile without PIN header should return 403."""
        response = await pin_client.get(
            "/api/media",
            headers={"X-Profile-ID": "protected"}
        )
        assert response.status_code == 403
        data = response.json()
        assert data["detail"] == "PIN required"
        assert data["requires_pin"] is True
        assert data["profile_id"] == "protected"

    async def test_protected_profile_with_invalid_pin_returns_403(self, pin_client):
        """Request to protected profile with wrong PIN should return 403."""
        response = await pin_client.get(
            "/api/media",
            headers={
                "X-Profile-ID": "protected",
                "X-Profile-PIN": "wrong"
            }
        )
        assert response.status_code == 403
        data = response.json()
        assert data["detail"] == "Invalid PIN"
        assert data["requires_pin"] is True

    async def test_protected_profile_with_valid_pin_succeeds(self, pin_client):
        """Request to protected profile with correct PIN should succeed."""
        response = await pin_client.get(
            "/api/media",
            headers={
                "X-Profile-ID": "protected",
                "X-Profile-PIN": TEST_PIN
            }
        )
        assert response.status_code == 200

    async def test_unprotected_profile_without_pin_succeeds(self, pin_client):
        """Request to unprotected profile should succeed without PIN."""
        response = await pin_client.get(
            "/api/media",
            headers={"X-Profile-ID": "unprotected"}
        )
        assert response.status_code == 200

    async def test_profiles_endpoint_is_pin_exempt(self, pin_client):
        """The /api/profiles endpoint should not require PIN."""
        response = await pin_client.get("/api/profiles")
        assert response.status_code == 200
        data = response.json()
        # Should list both profiles with has_pin info
        profiles = {p["id"]: p for p in data["profiles"]}
        assert "protected" in profiles
        assert "unprotected" in profiles
        assert profiles["protected"]["has_pin"] is True
        assert profiles["unprotected"]["has_pin"] is False

    async def test_verify_pin_endpoint_works(self, pin_client):
        """The PIN verification endpoint should verify PINs correctly."""
        # Valid PIN
        response = await pin_client.post(
            "/api/profiles/protected/verify-pin",
            json={"pin": TEST_PIN},
            headers={"X-Profile-ID": "protected"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True

        # Invalid PIN
        response = await pin_client.post(
            "/api/profiles/protected/verify-pin",
            json={"pin": "wrong"},
            headers={"X-Profile-ID": "protected"}
        )
        assert response.status_code == 401

    async def test_saving_the_same_pin_keeps_its_hash(self, pin_client):
        """Re-saving the current PIN must not re-hash it: proofs bound to the
        hash (live-update sockets) would silently stop matching."""
        from config import get_settings
        before = get_settings().get_profile("protected").pin_hash
        response = await pin_client.patch(
            "/api/profiles/protected/pin",
            json={"current_pin": TEST_PIN, "new_pin": TEST_PIN},
            headers={"X-Profile-ID": "protected", "X-Profile-PIN": TEST_PIN},
        )
        assert response.status_code == 200
        assert get_settings().get_profile("protected").pin_hash == before


def _hex(pin: str) -> str:
    return pin.encode().hex()


class TestTargetProfilePin:
    """Routes that name a profile (by db_guid or id) need that profile's PIN,
    whatever profile the caller is on."""

    async def test_db_guid_media_needs_its_profiles_pin(self, pin_client):
        from database_registry import get_database_registry

        guid = get_database_registry().get_db_guid("protected")
        url = f"/api/db/{guid}/media/999999/file"
        as_other = {"X-Profile-ID": "unprotected"}
        assert (await pin_client.get(url, headers=as_other)).status_code == 403
        assert (await pin_client.get(url, params={"pin": "wrong"})).status_code == 403
        allowed = await pin_client.get(url, params={"pin": TEST_PIN})
        assert allowed.status_code == 404  # past the PIN; there is no such media
        assert allowed.headers["cache-control"] == "no-store"
        header = await pin_client.get(url, headers={"X-Profile-PIN": TEST_PIN})
        assert header.status_code == 404
        # Package covers carry it in the path, so their relative URLs keep it.
        cover = f"/api/db/{guid}/pin/{{}}/media/999999/package-file/index.html"
        assert (await pin_client.get(cover.format(_hex("wrong")))).status_code == 403
        assert (await pin_client.get(cover.format(_hex(TEST_PIN)))).status_code == 404

    async def test_db_guid_media_of_open_profile_is_unchanged(self, pin_client):
        from database_registry import get_database_registry

        registry = get_database_registry()
        guid = registry.get_db_guid("unprotected")
        response = await pin_client.get(f"/api/db/{guid}/media/999999/file")
        assert response.status_code == 404, response.text
        assert response.headers.get("cache-control") != "no-store"

    async def test_profile_folders_need_its_pin(self, pin_client):
        for url in ("/api/profiles/protected", "/api/profiles/protected/folders"):
            assert (await pin_client.get(url, headers={"X-Profile-ID": "unprotected"})).status_code == 403
            ok = await pin_client.get(url, headers={"X-Target-Profile-PIN": TEST_PIN})
            assert ok.status_code == 200
        assert (await pin_client.get("/api/profiles/unprotected/folders")).status_code == 200

    async def test_rename_needs_the_target_pin(self, pin_client):
        from config import get_settings

        caller = {"X-Profile-ID": "unprotected"}
        denied = await pin_client.patch("/api/settings/profiles/protected", json={"name": "Taken"}, headers=caller)
        assert denied.status_code == 403
        renamed = await pin_client.patch(
            "/api/settings/profiles/protected", json={"name": "Renamed"},
            headers={**caller, "X-Target-Profile-PIN": TEST_PIN},
        )
        assert renamed.status_code == 200, renamed.text
        assert (await pin_client.patch(
            "/api/settings/profiles/unprotected", json={"name": "Open"}, headers=caller,
        )).status_code == 200


class TestDeleteProfile:
    """Runs last in this module: it deletes the protected profile."""

    async def test_delete_needs_the_target_pin_and_closes_it_first(self, pin_client, pin_temp_dir, monkeypatch):
        from database_registry import get_database_registry
        from routes import settings as settings_routes

        caller = {"X-Profile-ID": "unprotected"}
        assert (await pin_client.delete("/api/settings/profiles/protected", headers=caller)).status_code == 403
        assert (pin_temp_dir / "protected").is_dir()

        registry = get_database_registry()
        seen = {}
        real_remove = settings_routes._remove_profile_dir

        def remove(profile_dir):
            # The database is closed before its files are touched.
            seen["registered"] = registry.has_profile("protected")
            seen["marked"] = (profile_dir / settings_routes.PROFILE_DELETED_MARKER).is_file()
            return real_remove(profile_dir)

        monkeypatch.setattr(settings_routes, "_remove_profile_dir", remove)
        response = await pin_client.delete(
            "/api/settings/profiles/protected", headers={**caller, "X-Target-Profile-PIN": TEST_PIN},
        )
        assert response.status_code == 200, response.text
        assert seen == {"registered": False, "marked": True}
        assert not (pin_temp_dir / "protected").exists()


def test_profile_folder_in_use_is_removed_later(tmp_path, monkeypatch):
    """A folder that can't be removed yet keeps its marker, and launch finishes it."""
    import shutil
    from types import SimpleNamespace
    from routes import settings as settings_routes

    gone = tmp_path / "profile-gone"
    (gone / "sub").mkdir(parents=True)
    (gone / "stimma_v1.db").write_bytes(b"db")
    (gone / settings_routes.PROFILE_DELETED_MARKER).touch()
    kept = tmp_path / "profile-kept"  # configured: never touched, marker or not
    kept.mkdir()
    (kept / settings_routes.PROFILE_DELETED_MARKER).touch()
    unmarked = tmp_path / "profile-unmarked"  # not ours to remove
    unmarked.mkdir()

    real_unlink = type(gone).unlink

    def busy_unlink(self, *args, **kwargs):
        if self.name == "stimma_v1.db":
            raise PermissionError("in use")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(gone), "unlink", busy_unlink)
    assert settings_routes._remove_profile_dir(gone) is False
    assert (gone / settings_routes.PROFILE_DELETED_MARKER).is_file()
    monkeypatch.setattr(type(gone), "unlink", real_unlink)

    monkeypatch.setattr(settings_routes.app_dirs, "get_data_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(settings_routes, "get_settings", lambda: SimpleNamespace(profiles=[SimpleNamespace(id="profile-kept")]))
    settings_routes.remove_deleted_profile_dirs()
    assert not gone.exists()
    assert kept.is_dir() and unmarked.is_dir()
    shutil.rmtree(kept)

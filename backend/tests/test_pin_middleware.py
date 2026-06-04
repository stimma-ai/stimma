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

    def mock_get_profile_dir(modifier: str = "", profile_id: str = "default") -> Path:
        profile_dir = temp_dir / profile_id
        profile_dir.mkdir(exist_ok=True)
        return profile_dir

    def mock_get_database_path(modifier: str = "", profile_id: str = "default") -> Path:
        return mock_get_profile_dir(modifier, profile_id) / "stimma_v1.db"

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
        from routes import media, profiles
        app.include_router(media.router)
        app.include_router(profiles.router)

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

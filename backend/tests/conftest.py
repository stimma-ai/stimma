"""
Pytest fixtures for backend integration tests.

Provides:
- Fresh temp appdata directory per module
- Test FastAPI app with isolated database
- httpx AsyncClient for HTTP requests
- WebSocket client helper for event verification
"""

import asyncio
import os
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch, MagicMock

import httpx
from sqlalchemy import select

# Minimal config template for testing
MINIMAL_CONFIG = """
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
  - id: default
    name: Test Profile
    database: stimma_test.db
    folders: []
    markers:
      - id: favorite-test-id
        name: favorite
        icon_svg: heroicon:heart
        color: "#ef4444"
      - id: library-test-id
        name: library
        icon_svg: heroicon:bookmark
        color: "#3b82f6"

generators: []
tool_providers: []
llms: {}
"""


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
def temp_appdata_dir(tmp_path_factory) -> Path:
    """Create a fresh temp directory for the test module.

    This directory serves as the app data directory, containing:
    - config.yaml
    - profile databases
    - cache directories
    """
    base_dir = tmp_path_factory.mktemp("stimma_test")

    # Create config.yaml
    config_path = base_dir / "config.yaml"
    config_path.write_text(MINIMAL_CONFIG)

    # Create required subdirectories
    (base_dir / "default").mkdir(exist_ok=True)

    return base_dir


@pytest.fixture(scope="module")
async def test_app(temp_appdata_dir: Path):
    """Create a FastAPI test app with isolated database.

    This creates a minimal app suitable for testing:
    - Uses temp appdata directory
    - Skips heavy initialization (ingestion, generation queue)
    - Runs migrations and sets up database
    """
    # Create patches for app_dirs
    patches = _create_app_dirs_patches(temp_appdata_dir)

    # Apply patches before importing anything that uses app_dirs
    with patch.multiple("app_dirs", **patches):
        # Reset the database registry singleton
        import database_registry
        database_registry._registry = None

        # Reset settings cache
        import config
        config.settings = None

        # Reset equation store singleton so each test module gets a fresh
        # store rooted at its own temp data dir.
        from flow_runtime.equation_store import reset_equation_store_singleton
        reset_equation_store_singleton()

        # Now import and initialize
        from config import reload_settings
        from database import Base
        from database_registry import get_database_registry
        from utils.migrations import run_all_migrations
        from core.app import create_app

        # Force reload settings from our temp config
        settings = reload_settings()

        # Run migrations
        run_all_migrations()

        # Initialize database registry
        registry = get_database_registry()
        for profile in settings.profiles:
            registry.register_profile(profile)
        await registry.init_all_databases()

        # Create app (without running full lifespan)
        app = create_app()

        # Import and include routers
        from routes import (
            boards, chats, generation, media, media_files, markers, projects, flows, tags, trash,
            saved_views, search, profiles, keywords, processing, settings as settings_routes,
        )
        from routes import tasks as flow_tasks
        from routes.presets import router as presets_router
        from routes.preferences import router as preferences_router
        app.include_router(media.router)
        app.include_router(media_files.router)
        app.include_router(boards.router)
        app.include_router(chats.router)
        app.include_router(generation.router)
        app.include_router(markers.router)
        app.include_router(projects.router)
        app.include_router(flows.router)
        app.include_router(flow_tasks.router)
        app.include_router(tags.router)
        app.include_router(trash.router)
        app.include_router(saved_views.router)
        app.include_router(search.router)
        app.include_router(profiles.router)
        app.include_router(keywords.router)
        app.include_router(processing.router)
        app.include_router(presets_router)
        app.include_router(preferences_router)
        app.include_router(settings_routes.router)

        # Sync markers from config (normally done in lifespan)
        from database import Marker
        from heroicons import resolve_icon_svg
        for profile in settings.profiles:
            profile_markers = profile.markers or []
            db = registry.get_database(profile.id)
            async with db.async_session_maker() as session:
                for marker_config in profile_markers:
                    resolved_svg = resolve_icon_svg(marker_config.icon_svg)
                    result = await session.execute(
                        select(Marker).where(Marker.name == marker_config.name)
                    )
                    existing = result.scalar_one_or_none()
                    if existing:
                        # Update config_id if missing (migration may have created without it)
                        if not existing.config_id:
                            existing.config_id = marker_config.id
                    else:
                        new_marker = Marker(
                            name=marker_config.name,
                            icon_svg=resolved_svg,
                            color=marker_config.color,
                            config_id=marker_config.id
                        )
                        session.add(new_marker)
                await session.commit()

        # Add health check
        @app.get("/")
        async def root():
            return {"status": "ok"}

        yield app

        # Cleanup
        await registry.dispose_all()


@pytest.fixture(scope="module")
async def client(test_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx AsyncClient for making requests to the test app.

    Uses ASGI transport to call the app directly without a real server.
    """
    from httpx import ASGITransport

    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Profile-ID": "default"},
    ) as ac:
        yield ac


@pytest.fixture(scope="module")
async def db_session(test_app):
    """Get a database session for the test module.

    This returns a session factory that can be used to create sessions.
    """
    from database_registry import get_database_registry

    registry = get_database_registry()
    db = registry.get_database("default")
    return db.async_session_maker


@pytest.fixture(scope="module")
def event_loop():
    """Create an event loop for the test module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Generation Test Fixtures
# =============================================================================

# Config template with generation folder
GENERATION_CONFIG_TEMPLATE = """
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
  - id: default
    name: Test Profile
    database: stimma_test.db
    folders:
      - path: "{output_folder}"
        allow_generate: true
        is_uploads_folder: true
    markers:
      - id: favorite-test-id
        name: favorite
        icon_svg: heroicon:heart
        color: "#ef4444"
      - id: library-test-id
        name: library
        icon_svg: heroicon:bookmark
        color: "#3b82f6"

generators: []
tool_providers: []
llms: {{}}
"""


@pytest.fixture(scope="module")
def generation_temp_appdata_dir(tmp_path_factory) -> Path:
    """Create a fresh temp directory for generation tests.

    Includes an output folder configured for generation.
    """
    base_dir = tmp_path_factory.mktemp("stimma_generation_test")

    # Create output folder
    output_folder = base_dir / "output"
    output_folder.mkdir(exist_ok=True)

    # Create config.yaml with output folder path
    config_content = GENERATION_CONFIG_TEMPLATE.format(output_folder=str(output_folder))
    config_path = base_dir / "config.yaml"
    config_path.write_text(config_content)

    # Create required subdirectories
    (base_dir / "default").mkdir(exist_ok=True)

    return base_dir


@pytest.fixture(scope="module")
async def generation_app(generation_temp_appdata_dir: Path):
    """Create a FastAPI test app with generation support.

    Extends test_app with:
    - Generation routes
    - Tools routes
    - TestToolProvider registered
    - Generation queue initialized
    - Backend registry configured
    """
    patches = _create_app_dirs_patches(generation_temp_appdata_dir)

    with patch.multiple("app_dirs", **patches):
        # Reset singletons
        import database_registry
        database_registry._registry = None

        import config
        config.settings = None

        # Reset provider registry
        from providers import ProviderRegistry
        ProviderRegistry.reset()

        # Reset test provider singleton
        from providers.test_provider import reset_test_provider
        reset_test_provider()

        # Reset backend registry singleton
        import backend_registry
        backend_registry._backend_registry = None

        # Reset generation queue singleton
        import generation_queue as gq_module
        gq_module._generation_queue = None

        # Reset generation scheduler singleton
        import generation_scheduler
        generation_scheduler._scheduler = None

        # Now import and initialize
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

        # Import and include routers (including generation and tools)
        from routes import (
            boards, media, markers, projects, tags, trash,
            saved_views, profiles, keywords, generation, tools,
            postprocessing,
        )
        app.include_router(media.router)
        app.include_router(boards.router)
        app.include_router(projects.router)
        app.include_router(markers.router)
        app.include_router(tags.router)
        app.include_router(trash.router)
        app.include_router(saved_views.router)
        app.include_router(profiles.router)
        app.include_router(keywords.router)
        app.include_router(generation.router)
        app.include_router(postprocessing.router)
        app.include_router(tools.router)

        # Sync markers
        from database import Marker
        from heroicons import resolve_icon_svg
        for profile in settings.profiles:
            profile_markers = profile.markers or []
            db = registry.get_database(profile.id)
            async with db.async_session_maker() as session:
                for marker_config in profile_markers:
                    resolved_svg = resolve_icon_svg(marker_config.icon_svg)
                    result = await session.execute(
                        select(Marker).where(Marker.name == marker_config.name)
                    )
                    existing = result.scalar_one_or_none()
                    if existing:
                        # Update config_id if missing (migration may have created without it)
                        if not existing.config_id:
                            existing.config_id = marker_config.id
                    else:
                        new_marker = Marker(
                            name=marker_config.name,
                            icon_svg=resolved_svg,
                            color=marker_config.color,
                            config_id=marker_config.id
                        )
                        session.add(new_marker)
                await session.commit()

        # Initialize provider registry and test provider
        from providers import ProviderRegistry
        from providers.test_provider import get_test_provider
        from backend_registry import get_backend_registry

        provider_registry = ProviderRegistry.get_instance()
        backend_registry = get_backend_registry()

        test_provider = get_test_provider()
        await test_provider.connect()
        await provider_registry.register(test_provider)
        await backend_registry.register_backend(
            test_provider.provider_id,
            test_provider.max_concurrent
        )

        # Builtin lightweight provider (in-process filter tools etc.)
        from providers import get_lightweight_provider
        builtin_provider = get_lightweight_provider()
        await builtin_provider.connect()
        await provider_registry.register(builtin_provider)
        await backend_registry.register_backend(
            builtin_provider.provider_id,
            builtin_provider.max_concurrent
        )

        # Initialize generation queue with mock WebSocket manager
        from generation_queue import get_generation_queue
        from tests.helpers.ws import MockWebSocketManager

        mock_ws = MockWebSocketManager()
        generation_queue = get_generation_queue()
        generation_queue.set_websocket_manager(mock_ws)
        await generation_queue.cleanup_stale_jobs()
        # Note: We don't start background workers for tests
        # Instead, we'll process jobs manually for deterministic testing

        # Store references for fixtures
        app.state.test_provider = test_provider
        app.state.mock_ws = mock_ws
        app.state.generation_queue = generation_queue
        app.state.output_folder = str(generation_temp_appdata_dir / "output")
        app.state.backend_registry = backend_registry

        @app.get("/")
        async def root():
            return {"status": "ok"}

        yield app

        # Cleanup
        await provider_registry.unregister(test_provider.provider_id)
        await provider_registry.unregister(builtin_provider.provider_id)
        await registry.dispose_all()


@pytest.fixture(scope="module")
async def generation_client(generation_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx AsyncClient for generation tests."""
    from httpx import ASGITransport

    transport = ASGITransport(app=generation_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Profile-ID": "default"},
    ) as ac:
        yield ac


@pytest.fixture(scope="module")
async def generation_db_session(generation_app):
    """Get a database session for generation tests."""
    from database_registry import get_database_registry

    registry = get_database_registry()
    db = registry.get_database("default")
    return db.async_session_maker


@pytest.fixture(scope="module")
def test_provider(generation_app):
    """Access to the TestToolProvider for configuration."""
    return generation_app.state.test_provider


@pytest.fixture(scope="module")
def mock_ws(generation_app):
    """Access to the MockWebSocketManager for verification."""
    return generation_app.state.mock_ws


@pytest.fixture(scope="module")
def output_folder(generation_app) -> str:
    """Path to the generation output folder."""
    return generation_app.state.output_folder


@pytest.fixture(scope="module")
def generation_queue(generation_app):
    """Access to the GenerationQueue."""
    return generation_app.state.generation_queue

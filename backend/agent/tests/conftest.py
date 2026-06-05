"""
Pytest fixtures for agent testing.

Provides:
- Test database sessions (fresh per test)
- LLM configuration
"""

import os
import pytest
import pytest_asyncio
import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from database import Base, Chat
from .helpers.runner import NoOpWebSocketManager


# =============================================================================
# Event Loop
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def async_engine(tmp_path):
    """Create an async SQLAlchemy engine with a fresh test database."""
    db_path = tmp_path / "test_agent.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(async_engine) -> async_sessionmaker:
    """Create a session factory for the test database."""
    return async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for a test."""
    async with session_factory() as sess:
        yield sess
        # Rollback any uncommitted changes
        await sess.rollback()


# =============================================================================
# Chat Fixtures
# =============================================================================

@pytest_asyncio.fixture
async def test_chat(session) -> Chat:
    """Create a basic test chat."""
    chat = Chat(name="Test Chat")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    return chat


# =============================================================================
# WebSocket Fixtures
# =============================================================================

@pytest.fixture
def mock_ws() -> NoOpWebSocketManager:
    """Create a mock WebSocket manager."""
    return NoOpWebSocketManager()


# =============================================================================
# LLM Configuration Fixtures
# =============================================================================

@pytest.fixture
def mock_llm_response():
    """
    Factory fixture for mocking LLM responses.

    Usage:
        def test_something(mock_llm_response):
            mock = mock_llm_response('{"nodes": [...]}')
            with patch("llm_http.acompletion", mock):
                # Test code
    """
    def _mock(response_content: str):
        from unittest.mock import MagicMock

        async def mock_completion(*args, **kwargs):
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.content = response_content
            response.choices[0].message.tool_calls = None
            response.usage = MagicMock(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            )
            return response

        return mock_completion

    return _mock


@pytest.fixture
def llm_configs():
    """
    Available LLM configurations for eval tests.

    Set environment variables to enable different models:
    - ANTHROPIC_API_KEY for Claude
    - OPENAI_API_KEY for GPT-4
    - LOCAL_LLM_URL for local models
    """
    configs = {}

    if os.environ.get("ANTHROPIC_API_KEY"):
        configs["claude-sonnet"] = {
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
        }

    if os.environ.get("OPENAI_API_KEY"):
        configs["gpt-4-turbo"] = {
            "provider": "openai",
            "model": "gpt-4-turbo",
        }

    if os.environ.get("LOCAL_LLM_URL"):
        configs["local"] = {
            "provider": "openai",
            "model": "local-model",
            "endpoint": {"url": os.environ["LOCAL_LLM_URL"]},
        }

    return configs


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--llm",
        action="store",
        default="mock",
        help="LLM to use: mock, claude-sonnet, gpt-4-turbo, local, all",
    )


# Mark all async tests automatically
pytest_plugins = ('pytest_asyncio',)

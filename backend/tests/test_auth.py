"""
Tests for the auth API endpoints.

Tests cover:
- Auth status (GET /api/auth/status)
- Auth polling (GET /api/auth/poll/{session_id})
- Account info (GET /api/auth/account)
- Logout (POST /api/auth/logout)
- Start auth flow (POST /api/auth/start)
- Internal helpers (_html_page)
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock


def _get_pending_sessions():
    from routes.auth import _pending_sessions
    return _pending_sessions


def _make_html_page(*args, **kwargs):
    from routes.auth import _html_page
    return _html_page(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def auth_client(test_app):
    """Client with auth router included."""
    from httpx import ASGITransport
    from routes.auth import router

    test_app.include_router(router)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Profile-ID": "default"},
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Clear pending auth sessions between tests."""
    sessions = _get_pending_sessions()
    sessions.clear()
    yield
    sessions.clear()


# ---------------------------------------------------------------------------
# Tests: _html_page helper
# ---------------------------------------------------------------------------

class TestHtmlPage:
    """Tests for the _html_page helper function."""

    def test_success_page(self):
        html = _make_html_page("Success!", "You can close this window.")
        assert "Success!" in html
        assert "You can close this window." in html
        assert "#6366f1" in html  # success icon color
        assert "window.close()" in html

    def test_error_page(self):
        html = _make_html_page("Error", "Something went wrong.", is_error=True)
        assert "Error" in html
        assert "Something went wrong." in html
        assert "#f87171" in html  # error icon color


# ---------------------------------------------------------------------------
# Tests: GET /api/auth/status
# ---------------------------------------------------------------------------

class TestAuthStatus:
    """Tests for GET /api/auth/status endpoint."""

    async def test_status_not_authenticated(self, auth_client: AsyncClient):
        """Test auth status when not logged in."""
        with patch("auth_storage.load_auth_state", return_value=None):
            response = await auth_client.get("/api/auth/status")

        assert response.status_code == 200
        assert response.json()["authenticated"] is False

    async def test_status_authenticated(self, auth_client: AsyncClient):
        """Test auth status when logged in."""
        mock_state = {
            "user": {"uid": "u1", "email": "test@example.com", "displayName": "Test"},
            "tier": "pro",
            "credits": 100,
        }
        with patch("auth_storage.load_auth_state", return_value=mock_state):
            response = await auth_client.get("/api/auth/status")

        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user"]["email"] == "test@example.com"
        assert data["tier"] == "pro"
        assert data["credits"] == 100

    async def test_status_defaults_tier_to_free(self, auth_client: AsyncClient):
        """Test auth status defaults tier to 'free' if missing."""
        mock_state = {"user": {"uid": "u1"}}
        with patch("auth_storage.load_auth_state", return_value=mock_state):
            response = await auth_client.get("/api/auth/status")

        assert response.json()["tier"] == "free"


# ---------------------------------------------------------------------------
# Tests: GET /api/auth/poll/{session_id}
# ---------------------------------------------------------------------------

class TestPollAuth:
    """Tests for GET /api/auth/poll/{session_id} endpoint."""

    async def test_poll_unknown_session(self, auth_client: AsyncClient):
        """Test polling a non-existent session returns 404."""
        response = await auth_client.get("/api/auth/poll/nonexistent")
        assert response.status_code == 404

    async def test_poll_pending_session(self, auth_client: AsyncClient):
        """Test polling a pending (not yet completed) session."""
        sessions = _get_pending_sessions()
        sessions["test-session"] = {
            "state": "abc",
            "port": 12345,
            "result": None,
            "completed": False,
            "runner": None,
        }

        response = await auth_client.get("/api/auth/poll/test-session")
        assert response.status_code == 200
        assert response.json()["completed"] is False

    async def test_poll_completed_session(self, auth_client: AsyncClient):
        """Test polling a completed session returns result."""
        sessions = _get_pending_sessions()
        sessions["done-session"] = {
            "state": "abc",
            "port": 12345,
            "result": {"user": {"uid": "u1"}, "tier": "pro", "completed": True},
            "completed": True,
            "runner": None,
        }

        response = await auth_client.get("/api/auth/poll/done-session")
        assert response.status_code == 200
        data = response.json()
        assert data["completed"] is True
        assert data["user"]["uid"] == "u1"
        assert data["tier"] == "pro"

    async def test_poll_completed_with_error(self, auth_client: AsyncClient):
        """Test polling a completed session that has an error."""
        sessions = _get_pending_sessions()
        sessions["error-session"] = {
            "state": "abc",
            "port": 12345,
            "result": {"error": "Token exchange failed"},
            "completed": True,
            "runner": None,
        }

        response = await auth_client.get("/api/auth/poll/error-session")
        assert response.status_code == 200
        data = response.json()
        assert data["completed"] is True
        assert data["error"] == "Token exchange failed"


# ---------------------------------------------------------------------------
# Tests: GET /api/auth/account
# ---------------------------------------------------------------------------

class TestAccountInfo:
    """Tests for GET /api/auth/account endpoint."""

    async def test_account_not_authenticated(self, auth_client: AsyncClient):
        """Test account info when not logged in returns 401."""
        with patch("auth_storage.load_auth_state", return_value=None):
            response = await auth_client.get("/api/auth/account")
        assert response.status_code == 401

    async def test_account_invalid_token(self, auth_client: AsyncClient):
        """Test account info when token refresh fails returns 401."""
        with patch("auth_storage.load_auth_state", return_value={"user": {}}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value=None):
            response = await auth_client.get("/api/auth/account")
        assert response.status_code == 401

    async def test_account_success(self, auth_client: AsyncClient):
        """Test account info returns fresh data from cloud."""
        cloud_account = {
            "tier": "pro",
            "tierDisplayName": "Pro",
            "credits": 500,
            "createdAt": "2024-01-01",
            "usageWindows": {},
            "usage": {},
            "subscription": {"status": "active"},
        }

        with patch("auth_storage.load_auth_state", return_value={"user": {}, "tier": "free"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="tok"), \
             patch("cloud_api.fetch_user_account", new_callable=AsyncMock, return_value=cloud_account), \
             patch("auth_storage.save_auth_state"):
            response = await auth_client.get("/api/auth/account")

        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "pro"
        assert data["credits"] == 500
        assert data["subscription"]["status"] == "active"

    async def test_account_cloud_failure(self, auth_client: AsyncClient):
        """Test account info when cloud API fails returns 502."""
        with patch("auth_storage.load_auth_state", return_value={"user": {}}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="tok"), \
             patch("cloud_api.fetch_user_account", new_callable=AsyncMock, side_effect=Exception("boom")):
            response = await auth_client.get("/api/auth/account")
        assert response.status_code == 502


# ---------------------------------------------------------------------------
# Tests: POST /api/auth/logout
# ---------------------------------------------------------------------------

class TestLogout:
    """Tests for POST /api/auth/logout endpoint."""

    async def test_logout_success(self, auth_client: AsyncClient):
        """Test logout clears auth state and disconnects cloud."""
        with patch("auth_storage.clear_auth_state") as mock_clear, \
             patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as mock_disconnect:
            response = await auth_client.post("/api/auth/logout")

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_clear.assert_called_once()
        mock_disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: POST /api/auth/start
# ---------------------------------------------------------------------------

class TestStartAuth:
    """Tests for POST /api/auth/start endpoint."""

    async def test_start_auth_returns_session(self, auth_client: AsyncClient):
        """Test that starting auth creates a session with login URL."""
        sessions = _get_pending_sessions()

        with patch("routes.auth._get_cloud_base_url", return_value="https://stimma.cloud"):
            response = await auth_client.post("/api/auth/start")

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "port" in data
        assert "state" in data
        assert "login_url" in data
        assert "https://stimma.cloud" in data["login_url"]
        assert str(data["port"]) in data["login_url"]

        # Session should be registered
        assert data["session_id"] in sessions

        # Cleanup: shut down the callback server
        session = sessions.pop(data["session_id"], None)
        if session and session.get("runner"):
            await session["runner"].cleanup()

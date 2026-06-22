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
import json
import os
import httpx
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


@pytest.fixture
def auth_storage_env(monkeypatch, temp_appdata_dir):
    """Patch auth storage to use temp app data and an in-memory token store."""
    import auth_storage

    class MemoryRefreshTokenStore:
        backend_name = "test-memory"

        def __init__(self):
            self.token = None
            self.set_calls = []
            self.clear_calls = 0

        def get_refresh_token(self):
            return self.token

        def set_refresh_token(self, token):
            self.token = token
            self.set_calls.append(token)

        def clear_refresh_token(self):
            self.token = None
            self.clear_calls += 1

    store = MemoryRefreshTokenStore()

    monkeypatch.setattr(auth_storage.app_dirs, "get_data_dir", lambda: temp_appdata_dir)
    monkeypatch.setattr(auth_storage, "_token_store_override", store)
    monkeypatch.setattr(auth_storage, "_memory_refresh_token", None)
    monkeypatch.setattr(auth_storage, "_warned_memory_fallback", False)
    monkeypatch.setattr(auth_storage, "_warned_file_fallback", False)
    auth_storage._cache_id_token(None, None)

    yield store, temp_appdata_dir

    for filename in ("cloud_auth.json", "cloud_auth_tokens.json"):
        path = temp_appdata_dir / filename
        if path.exists():
            path.unlink()
    store.clear_refresh_token()
    auth_storage._cache_id_token(None, None)


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
# Tests: auth storage
# ---------------------------------------------------------------------------

class TestAuthStorage:
    """Tests for local auth persistence and token migration."""

    def test_token_store_uses_windows_credential_manager(self, monkeypatch):
        """Windows uses Credential Manager for refresh-token persistence."""
        import auth_storage

        class FakeWindowsStore:
            backend_name = "windows-credential-manager"

        monkeypatch.setattr(auth_storage.platform, "system", lambda: "Windows")
        monkeypatch.setattr(auth_storage, "_token_store_override", None)
        monkeypatch.setattr(auth_storage, "WindowsCredentialManagerRefreshTokenStore", FakeWindowsStore)

        store = auth_storage._get_token_store()

        assert store is not None
        assert store.backend_name == "windows-credential-manager"

    def test_token_store_uses_linux_secret_service(self, monkeypatch):
        """Linux uses Secret Service when it is available."""
        import auth_storage

        class FakeLinuxStore:
            backend_name = "linux-secret-service"

        monkeypatch.setattr(auth_storage.platform, "system", lambda: "Linux")
        monkeypatch.setattr(auth_storage, "_token_store_override", None)
        monkeypatch.setattr(auth_storage, "LinuxSecretServiceRefreshTokenStore", FakeLinuxStore)

        store = auth_storage._get_token_store()

        assert store is not None
        assert store.backend_name == "linux-secret-service"

    def test_linux_secret_service_unavailable_uses_file_fallback(
        self,
        monkeypatch,
        temp_appdata_dir,
    ):
        """Linux persists refresh tokens in a managed file when Secret Service is unavailable."""
        import auth_storage

        class UnavailableLinuxStore:
            def __init__(self):
                raise auth_storage.SecureTokenStorageUnavailable("no secret service")

        monkeypatch.setattr(auth_storage.app_dirs, "get_data_dir", lambda: temp_appdata_dir)
        monkeypatch.setattr(auth_storage.platform, "system", lambda: "Linux")
        monkeypatch.setattr(auth_storage, "_token_store_override", None)
        monkeypatch.setattr(auth_storage, "_memory_refresh_token", None)
        monkeypatch.setattr(auth_storage, "_warned_memory_fallback", False)
        monkeypatch.setattr(auth_storage, "_warned_file_fallback", False)
        monkeypatch.setattr(auth_storage, "LinuxSecretServiceRefreshTokenStore", UnavailableLinuxStore)
        auth_storage._cache_id_token(None, None)

        auth_storage.save_auth_state({
            "user": {"uid": "u1", "email": "test@example.com"},
            "tier": "pro",
            "refresh_token": "refresh-file",
            "id_token": "id-secret",
            "id_token_expiry": 9999999999,
        })

        auth_path = temp_appdata_dir / "cloud_auth.json"
        fallback_path = temp_appdata_dir / "cloud_auth_tokens.json"
        raw_auth = json.loads(auth_path.read_text())
        raw_fallback = json.loads(fallback_path.read_text())

        assert "refresh_token" not in raw_auth
        assert "id_token" not in raw_auth
        assert raw_fallback["refresh_token"] == "refresh-file"
        if os.name == "posix":
            assert fallback_path.stat().st_mode & 0o777 == 0o600

        auth_storage._memory_refresh_token = None
        auth_storage._cache_id_token(None, None)

        loaded = auth_storage.load_auth_state()

        assert loaded is not None
        assert loaded["refresh_token"] == "refresh-file"
        assert "id_token" not in loaded

    def test_clear_auth_state_removes_linux_file_fallback(
        self,
        monkeypatch,
        temp_appdata_dir,
    ):
        """Logout clears the Linux fallback token file."""
        import auth_storage

        class UnavailableLinuxStore:
            def __init__(self):
                raise auth_storage.SecureTokenStorageUnavailable("no secret service")

        monkeypatch.setattr(auth_storage.app_dirs, "get_data_dir", lambda: temp_appdata_dir)
        monkeypatch.setattr(auth_storage.platform, "system", lambda: "Linux")
        monkeypatch.setattr(auth_storage, "_token_store_override", None)
        monkeypatch.setattr(auth_storage, "_memory_refresh_token", None)
        monkeypatch.setattr(auth_storage, "_warned_memory_fallback", False)
        monkeypatch.setattr(auth_storage, "_warned_file_fallback", False)
        monkeypatch.setattr(auth_storage, "LinuxSecretServiceRefreshTokenStore", UnavailableLinuxStore)

        auth_storage.save_auth_state({
            "user": {"uid": "u1"},
            "refresh_token": "refresh-file",
        })

        fallback_path = temp_appdata_dir / "cloud_auth_tokens.json"
        assert fallback_path.exists()

        auth_storage.clear_auth_state()

        assert not (temp_appdata_dir / "cloud_auth.json").exists()
        assert not fallback_path.exists()

    def test_save_auth_state_strips_tokens_from_json(self, auth_storage_env):
        """Refresh and ID tokens are not persisted in cloud_auth.json."""
        from auth_storage import load_auth_state, save_auth_state

        store, data_dir = auth_storage_env

        save_auth_state({
            "user": {"uid": "u1", "email": "test@example.com"},
            "tier": "pro",
            "credits": 100,
            "refresh_token": "refresh-secret",
            "id_token": "id-secret",
            "id_token_expiry": 9999999999,
        })

        raw = json.loads((data_dir / "cloud_auth.json").read_text())
        assert raw["user"]["uid"] == "u1"
        assert raw["tier"] == "pro"
        assert "refresh_token" not in raw
        assert "id_token" not in raw
        assert store.token == "refresh-secret"

        loaded = load_auth_state()
        assert loaded["refresh_token"] == "refresh-secret"
        assert loaded["id_token"] == "id-secret"

    def test_load_auth_state_migrates_legacy_tokens(self, auth_storage_env):
        """Existing plaintext token JSON is migrated into secure storage."""
        from auth_storage import load_auth_state

        store, data_dir = auth_storage_env
        path = data_dir / "cloud_auth.json"
        path.write_text(json.dumps({
            "user": {"uid": "u1"},
            "tier": "pro",
            "refresh_token": "legacy-refresh",
            "id_token": "legacy-id",
            "id_token_expiry": 9999999999,
        }))

        loaded = load_auth_state()

        assert loaded["refresh_token"] == "legacy-refresh"
        assert loaded["id_token"] == "legacy-id"
        assert store.token == "legacy-refresh"

        raw = json.loads(path.read_text())
        assert "refresh_token" not in raw
        assert "id_token" not in raw
        assert raw["tier"] == "pro"

    def test_clear_auth_state_clears_json_and_secure_token(self, auth_storage_env):
        """Logout clears both display JSON and secure token storage."""
        from auth_storage import clear_auth_state, load_auth_state, save_auth_state

        store, data_dir = auth_storage_env

        save_auth_state({
            "user": {"uid": "u1"},
            "refresh_token": "refresh-secret",
            "id_token": "id-secret",
            "id_token_expiry": 9999999999,
        })

        clear_auth_state()

        assert not (data_dir / "cloud_auth.json").exists()
        assert store.token is None
        assert store.clear_calls == 1
        assert load_auth_state() is None

    def test_malformed_json_still_returns_none(self, auth_storage_env):
        """Malformed auth JSON is ignored instead of crashing."""
        from auth_storage import load_auth_state

        store, data_dir = auth_storage_env
        (data_dir / "cloud_auth.json").write_text("{not json")

        assert load_auth_state() is None
        assert store.token is None


# ---------------------------------------------------------------------------
# Tests: Firebase refresh classification
# ---------------------------------------------------------------------------

class TestFirebaseRefreshHandling:
    """Tests for expired/revoked vs transient token refresh failures."""

    async def test_invalid_refresh_token_clears_auth_state(self, auth_storage_env):
        """Firebase invalid-refresh semantics clear local auth and ask for sign-in."""
        from auth_storage import load_auth_state, save_auth_state
        from firebase_auth import AuthSessionExpiredError, get_valid_id_token

        store, data_dir = auth_storage_env
        save_auth_state({
            "user": {"uid": "u1"},
            "refresh_token": "bad-refresh",
            "id_token_expiry": 0,
        })

        request = httpx.Request("POST", "https://securetoken.googleapis.com/v1/token")
        response = httpx.Response(
            400,
            json={"error": {"message": "INVALID_REFRESH_TOKEN"}},
            request=request,
        )
        error = httpx.HTTPStatusError("invalid refresh", request=request, response=response)

        with patch("firebase_auth.refresh_id_token", new_callable=AsyncMock, side_effect=error):
            with pytest.raises(AuthSessionExpiredError):
                await get_valid_id_token(raise_on_failure=True)

        assert load_auth_state() is None
        assert not (data_dir / "cloud_auth.json").exists()
        assert store.token is None

    async def test_network_refresh_error_does_not_clear_auth_state(self, auth_storage_env):
        """Transient Firebase network errors preserve local auth state."""
        from auth_storage import load_auth_state, save_auth_state
        from firebase_auth import AuthNetworkError, get_valid_id_token

        store, data_dir = auth_storage_env
        save_auth_state({
            "user": {"uid": "u1"},
            "refresh_token": "refresh-secret",
            "id_token_expiry": 0,
        })

        request = httpx.Request("POST", "https://securetoken.googleapis.com/v1/token")
        error = httpx.ConnectTimeout("timeout", request=request)

        with patch("firebase_auth.refresh_id_token", new_callable=AsyncMock, side_effect=error):
            with pytest.raises(AuthNetworkError):
                await get_valid_id_token(raise_on_failure=True)

        assert (data_dir / "cloud_auth.json").exists()
        assert store.token == "refresh-secret"
        assert load_auth_state()["refresh_token"] == "refresh-secret"


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
            "refresh_token": "refresh",
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
        mock_state = {"user": {"uid": "u1"}, "refresh_token": "refresh"}
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
        with patch("auth_storage.load_auth_state", return_value={"user": {}, "refresh_token": "refresh"}), \
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

        with patch("auth_storage.load_auth_state", return_value={"user": {}, "tier": "free", "refresh_token": "refresh"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="tok"), \
             patch("cloud_api.fetch_user_account", new_callable=AsyncMock, return_value=cloud_account), \
             patch("auth_storage.save_auth_state"):
            response = await auth_client.get("/api/auth/account")

        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "pro"
        assert data["credits"] == 500
        assert data["subscription"]["status"] == "active"

    async def test_account_cloud_auth_temporarily_unavailable_preserves_auth(self, auth_client: AsyncClient):
        """Cloud auth verification outages return 503 without clearing local auth."""
        request = httpx.Request("GET", "https://stimma.ai/api/auth/me")
        response = httpx.Response(
            503,
            json={"error": "Authentication temporarily unavailable"},
            request=request,
        )
        error = httpx.HTTPStatusError("auth unavailable", request=request, response=response)

        with patch("auth_storage.load_auth_state", return_value={"user": {}, "refresh_token": "refresh"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="tok"), \
             patch("cloud_api.fetch_user_account", new_callable=AsyncMock, side_effect=error), \
             patch("auth_storage.clear_auth_state") as mock_clear:
            response = await auth_client.get("/api/auth/account")

        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "auth_temporarily_unavailable",
            "message": "Couldn't verify your Stimma Cloud session. Try again shortly.",
        }
        mock_clear.assert_not_called()

    async def test_account_cloud_rejects_refreshed_token_clears_auth(self, auth_client: AsyncClient):
        """Cloud 401/403 after force-refresh clears local auth and asks for sign-in."""
        request = httpx.Request("GET", "https://stimma.ai/api/auth/me")
        first_response = httpx.Response(
            401,
            json={"error": "Invalid token"},
            request=request,
        )
        second_response = httpx.Response(
            401,
            json={"error": "Invalid token"},
            request=request,
        )
        first_error = httpx.HTTPStatusError("invalid token", request=request, response=first_response)
        second_error = httpx.HTTPStatusError("invalid token", request=request, response=second_response)

        with patch("auth_storage.load_auth_state", return_value={"user": {}, "refresh_token": "refresh"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="tok"), \
             patch("firebase_auth.force_refresh_id_token", new_callable=AsyncMock, return_value="fresh-tok"), \
             patch("cloud_api.fetch_user_account", new_callable=AsyncMock, side_effect=[first_error, second_error]), \
             patch("auth_storage.clear_auth_state") as mock_clear:
            response = await auth_client.get("/api/auth/account")

        assert response.status_code == 401
        assert response.json()["detail"] == {
            "code": "session_expired",
            "message": "Please sign in again.",
        }
        mock_clear.assert_called_once()

    async def test_account_cloud_failure(self, auth_client: AsyncClient):
        """Test account info when cloud API fails returns 502."""
        with patch("auth_storage.load_auth_state", return_value={"user": {}, "refresh_token": "refresh"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="tok"), \
             patch("cloud_api.fetch_user_account", new_callable=AsyncMock, side_effect=Exception("boom")):
            response = await auth_client.get("/api/auth/account")
        assert response.status_code == 502


# ---------------------------------------------------------------------------
# Tests: POST /api/auth/logout
# ---------------------------------------------------------------------------

class TestLogout:
    """Tests for POST /api/auth/logout endpoint."""

    async def test_remote_logout_accepts_204_success(self, monkeypatch):
        """Cloud desktop logout helper treats 204 as accepted revocation."""
        import cloud_api

        calls = []

        class FakeSettings:
            class cloud:
                base_url = "https://stimma.test"

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, headers, timeout):
                calls.append((url, headers, timeout))
                return httpx.Response(204, request=httpx.Request("POST", url))

        monkeypatch.setattr(cloud_api, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(cloud_api.httpx, "AsyncClient", FakeAsyncClient)

        accepted = await cloud_api.revoke_remote_session_if_supported("id-token")

        assert accepted is True
        assert calls[0][0] == "https://stimma.test/api/auth/desktop/logout"
        assert calls[0][1]["Authorization"] == "Bearer id-token"

    async def test_remote_logout_503_is_non_blocking(self, monkeypatch):
        """Cloud desktop logout helper treats 503 as a best-effort failure."""
        import cloud_api

        class FakeSettings:
            class cloud:
                base_url = "https://stimma.test"

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, headers, timeout):
                return httpx.Response(
                    503,
                    request=httpx.Request("POST", url),
                    json={"error": "Authentication temporarily unavailable"},
                )

        monkeypatch.setattr(cloud_api, "get_settings", lambda: FakeSettings())
        monkeypatch.setattr(cloud_api.httpx, "AsyncClient", FakeAsyncClient)

        accepted = await cloud_api.revoke_remote_session_if_supported("id-token")

        assert accepted is False

    async def test_logout_success(self, auth_client: AsyncClient):
        """Test logout clears auth state, disconnects cloud, and revokes remotely."""
        with patch("auth_storage.clear_auth_state") as mock_clear, \
             patch("auth_storage.load_auth_state", return_value={"user": {}, "refresh_token": "refresh"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="id-token") as mock_token, \
             patch("cloud_api.revoke_remote_session_if_supported", new_callable=AsyncMock, return_value=True) as mock_revoke, \
             patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as mock_disconnect:
            response = await auth_client.post("/api/auth/logout")

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_clear.assert_called_once()
        mock_disconnect.assert_called_once()
        mock_token.assert_called_once()
        mock_revoke.assert_called_once_with("id-token")

    async def test_logout_clears_local_state_when_remote_revoke_fails(self, auth_client: AsyncClient):
        """Test remote revoke failure does not block local logout."""
        with patch("auth_storage.clear_auth_state") as mock_clear, \
             patch("auth_storage.load_auth_state", return_value={"user": {}, "refresh_token": "refresh"}), \
             patch("firebase_auth.get_valid_id_token", new_callable=AsyncMock, return_value="id-token"), \
             patch("cloud_api.revoke_remote_session_if_supported", new_callable=AsyncMock, side_effect=Exception("offline")) as mock_revoke, \
             patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as mock_disconnect:
            response = await auth_client.post("/api/auth/logout")

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_revoke.assert_called_once_with("id-token")
        mock_clear.assert_called_once()
        mock_disconnect.assert_called_once()

    async def test_logout_without_token_still_succeeds_locally(self, auth_client: AsyncClient):
        """Test logout succeeds even when no auth token is available."""
        with patch("auth_storage.clear_auth_state") as mock_clear, \
             patch("auth_storage.load_auth_state", return_value=None), \
             patch("cloud_api.revoke_remote_session_if_supported", new_callable=AsyncMock) as mock_revoke, \
             patch("routes.cloud.disconnect_cloud_internal", new_callable=AsyncMock) as mock_disconnect:
            response = await auth_client.post("/api/auth/logout")

        assert response.status_code == 200
        assert response.json()["success"] is True
        mock_revoke.assert_not_called()
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

"""Tests for the ChatGPT-plan OAuth device-code flow."""
import asyncio
import base64
import json
import time

import httpx
import pytest

import auth_storage
import chatgpt_auth


def _jwt(claims: dict) -> str:
    """Build an unsigned JWT. Only the payload is ever read."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _access_token(*, account_id="acct_123", plan="plus", email="a@b.test", ttl=3600):
    return _jwt({
        "exp": int(time.time()) + ttl,
        "email": email,
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_plan_type": plan,
        },
    })


class MemoryStore:
    backend_name = "memory-test"

    def __init__(self):
        self.token = None

    def get_refresh_token(self):
        return self.token

    def set_refresh_token(self, token):
        self.token = token

    def clear_refresh_token(self):
        self.token = None


@pytest.fixture
def chatgpt_env(monkeypatch, tmp_path):
    """Isolated token store and state file."""
    store = MemoryStore()
    chatgpt_auth._token_store.set_override(store)
    monkeypatch.setattr(chatgpt_auth.app_dirs, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(chatgpt_auth, "_access_token", None)
    yield store
    chatgpt_auth._token_store.set_override(None)


class TestJWTClaims:
    def test_extracts_account_id_and_plan(self):
        token = _access_token(account_id="acct_xyz", plan="pro")
        assert chatgpt_auth.account_id_from_token(token) == "acct_xyz"
        assert chatgpt_auth.plan_from_token(token) == "pro"

    def test_extracts_email(self):
        assert chatgpt_auth.email_from_token(_access_token(email="x@y.test")) == "x@y.test"

    def test_malformed_token_yields_no_claims(self):
        for value in (None, "", "not-a-jwt", "a.b", "a.!!!.c"):
            assert chatgpt_auth.account_id_from_token(value) is None
            assert chatgpt_auth.decode_jwt_claims(value) == {}

    def test_expiring_token_is_detected(self):
        assert chatgpt_auth._token_is_expiring(_access_token(ttl=30), 120)
        assert not chatgpt_auth._token_is_expiring(_access_token(ttl=600), 120)

    def test_token_without_exp_counts_as_expiring(self):
        assert chatgpt_auth._token_is_expiring(_jwt({"email": "a@b.test"}), 120)


class TestRequestHeaders:
    def test_identifies_stimma_and_carries_account_id(self):
        headers = chatgpt_auth.request_headers(_access_token(account_id="acct_9"))
        assert headers["ChatGPT-Account-Id"] == "acct_9"
        assert headers["originator"] == "stimma"
        assert headers["Authorization"].startswith("Bearer ")

    def test_does_not_impersonate_a_first_party_client(self):
        headers = chatgpt_auth.request_headers(_access_token())
        assert headers["originator"] != "codex_cli_rs"
        assert "codex_cli_rs" not in headers["User-Agent"]

    def test_account_id_omitted_when_token_lacks_the_claim(self):
        headers = chatgpt_auth.request_headers(_jwt({"exp": int(time.time()) + 600}))
        assert "ChatGPT-Account-Id" not in headers


class TestSessionState:
    def test_signed_out_when_no_token(self, chatgpt_env):
        assert not chatgpt_auth.is_signed_in()
        assert chatgpt_auth.load_account() is None

    def test_account_roundtrips(self, chatgpt_env):
        chatgpt_env.set_refresh_token("refresh-1")
        chatgpt_auth.save_account(
            chatgpt_auth.ChatGPTAccount(account_id="a1", email="e@x.test", plan="plus")
        )
        assert chatgpt_auth.is_signed_in()
        assert chatgpt_auth.load_account().email == "e@x.test"

    def test_sign_out_clears_token_and_state(self, chatgpt_env):
        chatgpt_env.set_refresh_token("refresh-1")
        chatgpt_auth.save_account(chatgpt_auth.ChatGPTAccount(account_id="a1"))

        chatgpt_auth.sign_out()

        assert chatgpt_env.get_refresh_token() is None
        assert chatgpt_auth.load_account() is None
        assert not chatgpt_auth.is_signed_in()

    def test_unreadable_state_file_reads_as_signed_out(self, chatgpt_env, tmp_path):
        (tmp_path / chatgpt_auth.STATE_FILENAME).write_text("{not json")
        assert chatgpt_auth.load_account() is None


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_persists_rotated_token(self, chatgpt_env, monkeypatch):
        chatgpt_env.set_refresh_token("refresh-old")
        new_access = _access_token(account_id="acct_new", plan="pro")

        async def fake_post(self, url, **kwargs):
            assert kwargs["data"]["grant_type"] == "refresh_token"
            assert kwargs["data"]["refresh_token"] == "refresh-old"
            return httpx.Response(
                200,
                json={"access_token": new_access, "refresh_token": "refresh-new"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        token = await chatgpt_auth.get_access_token(force_refresh=True)

        assert token == new_access
        # OpenAI rotates refresh tokens; losing the new one bricks the session.
        assert chatgpt_env.get_refresh_token() == "refresh-new"
        assert chatgpt_auth.load_account().plan == "pro"

    @pytest.mark.asyncio
    async def test_refresh_keeps_old_token_when_none_returned(self, chatgpt_env, monkeypatch):
        chatgpt_env.set_refresh_token("refresh-keep")

        async def fake_post(self, url, **kwargs):
            return httpx.Response(
                200, json={"access_token": _access_token()},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await chatgpt_auth.get_access_token(force_refresh=True)
        assert chatgpt_env.get_refresh_token() == "refresh-keep"

    @pytest.mark.asyncio
    async def test_no_refresh_token_requires_relogin(self, chatgpt_env):
        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.get_access_token(force_refresh=True)
        assert exc.value.code == "chatgpt_not_signed_in"
        assert exc.value.relogin_required

    @pytest.mark.asyncio
    async def test_429_is_a_quota_error_not_an_auth_error(self, chatgpt_env, monkeypatch):
        """A plan limit must not tell the user to sign in again — it cannot help."""
        chatgpt_env.set_refresh_token("refresh-1")

        async def fake_post(self, url, **kwargs):
            return httpx.Response(
                429, headers={"Retry-After": "90"}, json={},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.get_access_token(force_refresh=True)

        assert exc.value.code == "chatgpt_rate_limited"
        assert exc.value.relogin_required is False
        assert exc.value.retry_after == 90
        # The credential survives a quota rejection.
        assert chatgpt_env.get_refresh_token() == "refresh-1"

    @pytest.mark.asyncio
    async def test_invalid_grant_requires_relogin(self, chatgpt_env, monkeypatch):
        chatgpt_env.set_refresh_token("refresh-1")

        async def fake_post(self, url, **kwargs):
            return httpx.Response(
                400, json={"error": "invalid_grant", "error_description": "expired"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.get_access_token(force_refresh=True)
        assert exc.value.relogin_required

    @pytest.mark.asyncio
    async def test_reused_refresh_token_is_reported_distinctly(self, chatgpt_env, monkeypatch):
        chatgpt_env.set_refresh_token("refresh-1")

        async def fake_post(self, url, **kwargs):
            return httpx.Response(
                400, json={"error": "refresh_token_reused"},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.get_access_token(force_refresh=True)
        assert exc.value.code == "chatgpt_session_superseded"
        assert exc.value.relogin_required

    @pytest.mark.asyncio
    async def test_valid_cached_token_skips_the_network(self, chatgpt_env, monkeypatch):
        chatgpt_env.set_refresh_token("refresh-1")
        cached = _access_token(ttl=3600)
        monkeypatch.setattr(chatgpt_auth, "_access_token", cached)

        async def fail(self, url, **kwargs):
            raise AssertionError("should not refresh a token that is still valid")

        monkeypatch.setattr(httpx.AsyncClient, "post", fail)
        assert await chatgpt_auth.get_access_token() == cached


class TestModelCatalog:
    @pytest.mark.asyncio
    async def test_hidden_models_are_dropped_and_priority_orders(self, monkeypatch):
        async def fake_get(self, url, **kwargs):
            assert "ChatGPT-Account-Id" in kwargs["headers"]
            return httpx.Response(200, json={"models": [
                {"slug": "gpt-b", "priority": 2},
                {"slug": "gpt-hidden", "priority": 0, "visibility": "hide"},
                {"slug": "gpt-a", "priority": 1,
                 "supported_reasoning_efforts": ["low", "high"],
                 "default_reasoning_effort": "high"},
            ]}, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        models = await chatgpt_auth.fetch_models(_access_token())

        assert [m["id"] for m in models] == ["gpt-a", "gpt-b"]
        assert models[0]["reasoning_efforts"] == ["low", "high"]

    @pytest.mark.asyncio
    async def test_supported_in_api_false_is_not_filtered(self, monkeypatch):
        """That flag describes the public API, not this OAuth backend."""
        async def fake_get(self, url, **kwargs):
            return httpx.Response(200, json={"models": [
                {"slug": "gpt-5.3-codex-spark", "supported_in_api": False},
            ]}, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        models = await chatgpt_auth.fetch_models(_access_token())
        assert [m["id"] for m in models] == ["gpt-5.3-codex-spark"]

    @pytest.mark.asyncio
    async def test_401_requires_relogin(self, monkeypatch):
        async def fake_get(self, url, **kwargs):
            return httpx.Response(401, json={}, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.fetch_models(_access_token())
        assert exc.value.relogin_required

    @pytest.mark.asyncio
    async def test_empty_catalog_returns_empty_not_fallback(self, monkeypatch):
        """An entitlement-less account must not appear to have models."""
        async def fake_get(self, url, **kwargs):
            return httpx.Response(200, json={"models": []},
                                  request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        assert await chatgpt_auth.fetch_models(_access_token()) == []


class TestUsage:
    @pytest.mark.asyncio
    async def test_parses_rate_limit_windows(self, monkeypatch):
        async def fake_get(self, url, **kwargs):
            return httpx.Response(200, json={"rate_limit": {
                "primary_window": {"used_percent": 38.5, "resets_in_seconds": 900},
                "secondary_window": {"used_percent": 71},
            }}, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        usage = await chatgpt_auth.fetch_usage(_access_token())

        assert [w["window"] for w in usage["windows"]] == ["primary", "secondary"]
        assert usage["windows"][0]["used_percent"] == 38.5

    @pytest.mark.asyncio
    async def test_usage_failure_is_not_fatal(self, monkeypatch):
        async def fake_get(self, url, **kwargs):
            return httpx.Response(500, text="boom", request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
        assert await chatgpt_auth.fetch_usage(_access_token()) is None


class TestDeviceLogin:
    @pytest.mark.asyncio
    async def test_start_returns_user_code_without_secrets(self, chatgpt_env, monkeypatch):
        async def fake_post(self, url, **kwargs):
            return httpx.Response(200, json={
                "user_code": "ABCD-1234",
                "device_auth_id": "dev-1",
                "interval": 5,
            }, request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        session = await chatgpt_auth.start_device_login()
        chatgpt_auth.cancel_login(session.id)

        state = session.public_state()
        assert state["user_code"] == "ABCD-1234"
        assert state["verification_url"] == chatgpt_auth.DEVICE_VERIFICATION_URL
        # device_auth_id is an internal handle and must not reach the client.
        assert "device_auth_id" not in state

    @pytest.mark.asyncio
    async def test_rate_limited_start_is_typed(self, chatgpt_env, monkeypatch):
        async def fake_post(self, url, **kwargs):
            return httpx.Response(429, headers={"Retry-After": "5"}, json={},
                                  request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(chatgpt_auth.asyncio, "sleep", _no_sleep)

        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.start_device_login()
        assert exc.value.code == "chatgpt_rate_limited"

    @pytest.mark.asyncio
    async def test_incomplete_start_response_is_rejected(self, chatgpt_env, monkeypatch):
        async def fake_post(self, url, **kwargs):
            return httpx.Response(200, json={"user_code": "ABCD-1234"},
                                  request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        with pytest.raises(chatgpt_auth.ChatGPTAuthError) as exc:
            await chatgpt_auth.start_device_login()
        assert exc.value.code == "chatgpt_device_start_invalid"

    @pytest.mark.asyncio
    async def test_full_flow_persists_tokens(self, chatgpt_env, monkeypatch):
        access = _access_token(account_id="acct_new", plan="plus", email="u@x.test")
        calls = {"n": 0}

        async def fake_post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            if url == chatgpt_auth.DEVICE_USERCODE_URL:
                return httpx.Response(200, json={
                    "user_code": "WXYZ-9999", "device_auth_id": "dev-9", "interval": 1,
                }, request=request)
            if url == chatgpt_auth.DEVICE_TOKEN_URL:
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(403, json={}, request=request)  # pending
                return httpx.Response(200, json={
                    "authorization_code": "auth-code", "code_verifier": "verifier",
                }, request=request)
            if url == chatgpt_auth.OAUTH_TOKEN_URL:
                assert kwargs["data"]["grant_type"] == "authorization_code"
                assert kwargs["data"]["code_verifier"] == "verifier"
                return httpx.Response(200, json={
                    "access_token": access, "refresh_token": "refresh-final",
                }, request=request)
            raise AssertionError(f"unexpected POST {url}")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(chatgpt_auth.asyncio, "sleep", _no_sleep)

        session = await chatgpt_auth.start_device_login()
        await session.task

        assert session.error_code is None
        assert chatgpt_env.get_refresh_token() == "refresh-final"
        account = chatgpt_auth.load_account()
        assert account.email == "u@x.test"
        assert account.plan == "plus"
        assert account.connected_at

    @pytest.mark.asyncio
    async def test_expired_code_reports_timeout(self, chatgpt_env, monkeypatch):
        async def fake_post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            if url == chatgpt_auth.DEVICE_USERCODE_URL:
                return httpx.Response(200, json={
                    "user_code": "AAAA-0000", "device_auth_id": "dev-x", "interval": 1,
                }, request=request)
            return httpx.Response(404, json={}, request=request)  # never approved

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(chatgpt_auth.asyncio, "sleep", _no_sleep)
        monkeypatch.setattr(chatgpt_auth, "DEVICE_LOGIN_MAX_WAIT_SECONDS", 0)

        session = await chatgpt_auth.start_device_login()
        await session.task

        assert session.error_code == "chatgpt_device_timeout"
        assert chatgpt_env.get_refresh_token() is None

    @pytest.mark.asyncio
    async def test_cancel_stops_the_login(self, chatgpt_env, monkeypatch):
        async def fake_post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            if url == chatgpt_auth.DEVICE_USERCODE_URL:
                return httpx.Response(200, json={
                    "user_code": "BBBB-1111", "device_auth_id": "dev-c", "interval": 1,
                }, request=request)
            return httpx.Response(403, json={}, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        monkeypatch.setattr(chatgpt_auth.asyncio, "sleep", _no_sleep)

        session = await chatgpt_auth.start_device_login()
        assert chatgpt_auth.cancel_login(session.id)
        # CancelledError derives from BaseException, not Exception.
        with pytest.raises(asyncio.CancelledError):
            await session.task
        assert session.cancelled
        assert chatgpt_env.get_refresh_token() is None


async def _no_sleep(_seconds):
    """Drive the polling loops without real delays."""
    return None


class TestCredentialIsolation:
    def test_chatgpt_and_cloud_use_distinct_credential_keys(self):
        """Signing out of one must never disturb the other."""
        cloud = auth_storage.CLOUD_CREDENTIAL_KEY
        chatgpt = auth_storage.CHATGPT_CREDENTIAL_KEY
        assert cloud.account_kind != chatgpt.account_kind
        assert cloud.keychain_service != chatgpt.keychain_service
        assert cloud.windows_target != chatgpt.windows_target
        assert cloud.fallback_filename != chatgpt.fallback_filename

    def test_cloud_credential_names_are_unchanged(self):
        """These names key credentials already written by shipped builds."""
        cloud = auth_storage.CLOUD_CREDENTIAL_KEY
        assert cloud.keychain_service == "Stimma Cloud Auth"
        assert cloud.account_kind == "stimma-cloud-refresh-token"
        assert cloud.windows_target == "Stimma Cloud:{bundle}:{sandbox}:refresh-token"
        assert cloud.fallback_filename == "cloud_auth_tokens.json"

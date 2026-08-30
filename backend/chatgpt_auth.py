"""ChatGPT-plan OAuth: device-code login, token refresh, and account state.

Stimma runs OpenAI's device-code flow directly rather than shelling out to
``codex app-server``. The wire protocol here mirrors what Hermes Agent does in
``hermes_cli/auth.py`` — it is the only documented-by-observation path to a
ChatGPT-subscription credential that a third-party desktop app can drive.

Boundaries this module keeps:

* The refresh token lives in the OS credential store (``auth_storage``), never
  in ``config.yaml`` and never in an API response.
* Stimma keeps its **own** OAuth session. It never reads or writes the user's
  ``~/.codex/auth.json``; a shared refresh token would be rotated out from
  under Codex CLI (and vice versa) since OpenAI rotates on every refresh.
* Stimma identifies itself honestly as ``stimma`` in ``originator`` and its
  User-Agent. It does not impersonate a first-party OpenAI client.
"""
from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

import app_dirs
from auth_storage import CHATGPT_CREDENTIAL_KEY, SecretTokenStore
from core.logging import get_logger

log = get_logger(__name__)

# --- OpenAI endpoints -------------------------------------------------------

OAUTH_ISSUER = "https://auth.openai.com"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_TOKEN_URL = f"{OAUTH_ISSUER}/oauth/token"
DEVICE_USERCODE_URL = f"{OAUTH_ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{OAUTH_ISSUER}/api/accounts/deviceauth/token"
DEVICE_REDIRECT_URI = f"{OAUTH_ISSUER}/deviceauth/callback"
DEVICE_VERIFICATION_URL = f"{OAUTH_ISSUER}/codex/device"

BACKEND_BASE_URL = "https://chatgpt.com/backend-api/codex"
MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

# Refresh this far ahead of expiry so an in-flight turn never races the clock.
REFRESH_SKEW_SECONDS = 120
# OpenAI's device codes are good for 15 minutes.
DEVICE_LOGIN_MAX_WAIT_SECONDS = 15 * 60
DEVICE_POLL_MIN_INTERVAL_SECONDS = 3

STATE_FILENAME = "chatgpt_auth.json"

USER_AGENT = "Stimma"
ORIGINATOR = "stimma"


def _user_agent() -> str:
    try:
        from user_agent import user_agent as _ua

        return _ua()
    except Exception:
        return USER_AGENT


# --- errors -----------------------------------------------------------------


class ChatGPTAuthError(Exception):
    """A typed ChatGPT-plan auth failure.

    ``code`` is a stable machine string the frontend switches on; see the
    error table in the settings UI. ``relogin_required`` distinguishes "your
    session is gone" from "OpenAI is throttling, try later" — collapsing the
    two produces the classic misleading "check your API key" message.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        relogin_required: bool = False,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.relogin_required = relogin_required
        self.retry_after = retry_after


# --- token storage ----------------------------------------------------------

_token_store = SecretTokenStore(
    CHATGPT_CREDENTIAL_KEY, description="ChatGPT refresh token"
)

# Access tokens are short-lived; keep them in memory only, like the cloud
# ID token. A restart re-mints one from the refresh token.
_access_token: Optional[str] = None
_refresh_lock = asyncio.Lock()


def _state_path():
    return app_dirs.get_data_dir() / STATE_FILENAME


@dataclass
class ChatGPTAccount:
    """Non-secret account state, safe to persist and to return to the UI."""

    account_id: Optional[str] = None
    email: Optional[str] = None
    plan: Optional[str] = None
    connected_at: Optional[str] = None
    last_refresh: Optional[str] = None
    models: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "email": self.email,
            "plan": self.plan,
            "connected_at": self.connected_at,
            "last_refresh": self.last_refresh,
            "models": self.models,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ChatGPTAccount":
        return cls(
            account_id=data.get("account_id"),
            email=data.get("email"),
            plan=data.get("plan"),
            connected_at=data.get("connected_at"),
            last_refresh=data.get("last_refresh"),
            models=data.get("models") or [],
        )


def load_account() -> Optional[ChatGPTAccount]:
    """Read persisted non-secret account state, or None when signed out."""
    path = _state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("chatgpt_auth.json is unreadable; treating as signed out")
        return None
    if not isinstance(data, dict):
        return None
    return ChatGPTAccount.from_json(data)


def save_account(account: ChatGPTAccount) -> None:
    from auth_storage import _write_auth_state_json

    _write_auth_state_json(_state_path(), account.to_json())


def is_signed_in() -> bool:
    return bool(_token_store.get()) and load_account() is not None


def sign_out() -> None:
    """Clear only Stimma's ChatGPT session.

    The user's Codex CLI / IDE logins live in their own credential domain and
    are untouched — Stimma never held those tokens in the first place.
    """
    global _access_token
    _access_token = None
    _token_store.clear()
    try:
        _state_path().unlink(missing_ok=True)
    except OSError as e:
        log.warning("could not remove chatgpt_auth.json", reason=str(e))


# --- JWT helpers ------------------------------------------------------------


def decode_jwt_claims(token: Optional[str]) -> dict[str, Any]:
    """Best-effort decode of a JWT payload. Returns {} for anything unparseable."""
    if not isinstance(token, str) or token.count(".") < 2:
        return {}
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def _openai_auth_claims(token: Optional[str]) -> dict[str, Any]:
    claims = decode_jwt_claims(token).get("https://api.openai.com/auth")
    return claims if isinstance(claims, dict) else {}


def account_id_from_token(token: Optional[str]) -> Optional[str]:
    """Extract ``chatgpt_account_id``.

    The Codex backend needs this in ``ChatGPT-Account-Id``. Without it the
    models endpoint returns ``{"models": []}`` with HTTP 200, which reads as
    "no models on this plan" rather than "you forgot a header".
    """
    value = _openai_auth_claims(token).get("chatgpt_account_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def plan_from_token(token: Optional[str]) -> Optional[str]:
    value = _openai_auth_claims(token).get("chatgpt_plan_type")
    return value.strip() if isinstance(value, str) and value.strip() else None


def email_from_token(token: Optional[str]) -> Optional[str]:
    claims = decode_jwt_claims(token)
    for key in ("email", "preferred_username"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    profile = claims.get("https://api.openai.com/profile")
    if isinstance(profile, dict):
        value = profile.get("email")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _token_is_expiring(token: Optional[str], skew_seconds: int) -> bool:
    """True when the token is missing, unparseable, or expires within the skew."""
    claims = decode_jwt_claims(token)
    if not claims:
        return True
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return True
    return time.time() >= float(exp) - skew_seconds


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _retry_after_seconds(headers: Any) -> Optional[int]:
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return None


# --- device-code login ------------------------------------------------------


@dataclass
class DeviceLoginSession:
    """One in-flight device-code login."""

    id: str
    user_code: str
    device_auth_id: str
    verification_url: str
    poll_interval: int
    expires_at: float
    task: Optional[asyncio.Task] = None
    completed: bool = False
    account: Optional[ChatGPTAccount] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    cancelled: bool = False

    def public_state(self) -> dict[str, Any]:
        return {
            "login_id": self.id,
            "user_code": self.user_code,
            "verification_url": self.verification_url,
            "expires_in": max(0, int(self.expires_at - time.monotonic())),
            "completed": self.completed,
            "cancelled": self.cancelled,
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code
                else None
            ),
            "account": self.account.to_json() if self.account else None,
        }


_sessions: dict[str, DeviceLoginSession] = {}


def get_login_session(login_id: str) -> Optional[DeviceLoginSession]:
    return _sessions.get(login_id)


async def start_device_login() -> DeviceLoginSession:
    """Request a device code and start polling for approval in the background.

    Not gated on Privacy Lockdown: lockdown covers Stimma-owned network
    surfaces, and this is the user's own OpenAI account, exactly like the
    existing BYO API-key providers.
    """
    payload: Optional[dict[str, Any]] = None
    response: Optional[httpx.Response] = None
    # OpenAI throttles this endpoint per IP/account. Back off rather than
    # surfacing a bare 429 that reads like a credential problem.
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        for attempt in range(1, 5):
            try:
                response = await client.post(
                    DEVICE_USERCODE_URL,
                    json={"client_id": OAUTH_CLIENT_ID},
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": _user_agent(),
                        "originator": ORIGINATOR,
                    },
                )
            except httpx.HTTPError as e:
                raise ChatGPTAuthError(
                    f"Could not reach OpenAI to start sign-in: {e}",
                    code="chatgpt_network_error",
                ) from e

            if response.status_code != 429:
                break
            if attempt < 4:
                delay = _retry_after_seconds(response.headers) or 2**attempt
                await asyncio.sleep(max(1, min(int(delay), 60)))

        if response is None:
            raise ChatGPTAuthError(
                "Could not reach OpenAI to start sign-in.",
                code="chatgpt_network_error",
            )
        if response.status_code == 429:
            retry_after = _retry_after_seconds(response.headers)
            raise ChatGPTAuthError(
                "OpenAI is throttling sign-in requests. Try again shortly.",
                code="chatgpt_rate_limited",
                retry_after=retry_after,
            )
        if response.status_code != 200:
            raise ChatGPTAuthError(
                f"OpenAI returned HTTP {response.status_code} starting sign-in.",
                code="chatgpt_device_start_failed",
            )
        payload = response.json()

    user_code = str((payload or {}).get("user_code") or "").strip()
    device_auth_id = str((payload or {}).get("device_auth_id") or "").strip()
    if not user_code or not device_auth_id:
        raise ChatGPTAuthError(
            "OpenAI's sign-in response was missing required fields.",
            code="chatgpt_device_start_invalid",
        )

    try:
        interval = int((payload or {}).get("interval") or 5)
    except (TypeError, ValueError):
        interval = 5

    session = DeviceLoginSession(
        id=secrets.token_urlsafe(16),
        user_code=user_code,
        device_auth_id=device_auth_id,
        verification_url=DEVICE_VERIFICATION_URL,
        poll_interval=max(DEVICE_POLL_MIN_INTERVAL_SECONDS, interval),
        expires_at=time.monotonic() + DEVICE_LOGIN_MAX_WAIT_SECONDS,
    )
    _sessions[session.id] = session
    session.task = asyncio.create_task(_run_device_login(session))
    return session


def cancel_login(login_id: str) -> bool:
    session = _sessions.get(login_id)
    if session is None:
        return False
    session.cancelled = True
    session.completed = True
    if session.task is not None and not session.task.done():
        session.task.cancel()
    return True


async def _run_device_login(session: DeviceLoginSession) -> None:
    """Poll for approval, exchange the code, and persist the result."""
    try:
        code_payload = await _poll_for_authorization(session)
        tokens = await _exchange_authorization_code(
            authorization_code=code_payload["authorization_code"],
            code_verifier=code_payload["code_verifier"],
        )
        account = await _persist_tokens(tokens, first_login=True)
        session.account = account
    except asyncio.CancelledError:
        session.cancelled = True
        raise
    except ChatGPTAuthError as e:
        session.error_code = e.code
        session.error_message = e.message
        log.warning("ChatGPT device login failed", code=e.code, reason=e.message)
    except Exception as e:
        session.error_code = "chatgpt_login_failed"
        session.error_message = str(e)
        log.exception("ChatGPT device login raised")
    finally:
        session.completed = True


async def _poll_for_authorization(session: DeviceLoginSession) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        while time.monotonic() < session.expires_at:
            await asyncio.sleep(session.poll_interval)
            if session.cancelled:
                raise asyncio.CancelledError()
            try:
                response = await client.post(
                    DEVICE_TOKEN_URL,
                    json={
                        "device_auth_id": session.device_auth_id,
                        "user_code": session.user_code,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": _user_agent(),
                        "originator": ORIGINATOR,
                    },
                )
            except httpx.HTTPError:
                # Transient network trouble mid-poll is not a login failure;
                # the device code is still valid until it expires.
                continue

            if response.status_code == 200:
                data = response.json()
                authorization_code = str(data.get("authorization_code") or "").strip()
                code_verifier = str(data.get("code_verifier") or "").strip()
                if not authorization_code or not code_verifier:
                    raise ChatGPTAuthError(
                        "OpenAI approved the sign-in but returned an incomplete response.",
                        code="chatgpt_device_exchange_invalid",
                    )
                return {
                    "authorization_code": authorization_code,
                    "code_verifier": code_verifier,
                }
            if response.status_code in {403, 404}:
                continue  # not approved yet
            if response.status_code == 429:
                await asyncio.sleep(
                    _retry_after_seconds(response.headers) or session.poll_interval
                )
                continue
            raise ChatGPTAuthError(
                f"OpenAI returned HTTP {response.status_code} while waiting for approval.",
                code="chatgpt_device_poll_failed",
            )

    raise ChatGPTAuthError(
        "Sign-in code expired.",
        code="chatgpt_device_timeout",
    )


async def _exchange_authorization_code(
    *, authorization_code: str, code_verifier: str
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        try:
            response = await client.post(
                OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": DEVICE_REDIRECT_URI,
                    "client_id": OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "User-Agent": _user_agent(),
                },
            )
        except httpx.HTTPError as e:
            raise ChatGPTAuthError(
                f"Could not reach OpenAI to complete sign-in: {e}",
                code="chatgpt_network_error",
            ) from e

    if response.status_code == 429:
        raise ChatGPTAuthError(
            "OpenAI is throttling sign-in requests. Try again shortly.",
            code="chatgpt_rate_limited",
            retry_after=_retry_after_seconds(response.headers),
        )
    if response.status_code != 200:
        raise ChatGPTAuthError(
            f"OpenAI returned HTTP {response.status_code} completing sign-in.",
            code="chatgpt_token_exchange_failed",
        )

    tokens = response.json()
    if not str(tokens.get("access_token") or "").strip():
        raise ChatGPTAuthError(
            "OpenAI did not return an access token.",
            code="chatgpt_token_exchange_invalid",
        )
    if not str(tokens.get("refresh_token") or "").strip():
        raise ChatGPTAuthError(
            "OpenAI did not return a refresh token, so the session could not be saved.",
            code="chatgpt_token_exchange_invalid",
        )
    return tokens


async def _persist_tokens(
    tokens: dict[str, Any], *, first_login: bool = False
) -> ChatGPTAccount:
    global _access_token

    access_token = str(tokens["access_token"]).strip()
    refresh_token = str(tokens["refresh_token"]).strip()

    _access_token = access_token
    _token_store.set(refresh_token)

    existing = load_account() if not first_login else None
    account = existing or ChatGPTAccount()
    account.account_id = account_id_from_token(access_token) or account.account_id
    account.email = email_from_token(access_token) or account.email
    account.plan = plan_from_token(access_token) or account.plan
    account.last_refresh = _now_iso()
    if first_login or not account.connected_at:
        account.connected_at = account.last_refresh
    save_account(account)
    return account


# --- refresh ----------------------------------------------------------------


async def _refresh_access_token() -> str:
    """Exchange the stored refresh token for a fresh access token.

    OpenAI rotates refresh tokens, so the new one must be persisted on every
    successful refresh or the next call is dead.
    """
    global _access_token

    refresh_token = _token_store.get()
    if not refresh_token:
        raise ChatGPTAuthError(
            "Not signed in to ChatGPT.",
            code="chatgpt_not_signed_in",
            relogin_required=True,
        )

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        try:
            response = await client.post(
                OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": OAUTH_CLIENT_ID,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "User-Agent": _user_agent(),
                },
            )
        except httpx.HTTPError as e:
            raise ChatGPTAuthError(
                f"Could not reach OpenAI to refresh your session: {e}",
                code="chatgpt_network_error",
            ) from e

    if response.status_code == 429:
        # The credential is fine — the plan quota is not. Re-authenticating
        # cannot lift a quota cap, so do not tell the user to sign in again.
        raise ChatGPTAuthError(
            "ChatGPT plan limit reached. Sign-in is still valid.",
            code="chatgpt_rate_limited",
            retry_after=_retry_after_seconds(response.headers),
        )

    if response.status_code != 200:
        code = "chatgpt_refresh_failed"
        message = f"Refreshing your ChatGPT session failed (HTTP {response.status_code})."
        relogin = response.status_code in {400, 401, 403}
        try:
            error = response.json()
        except Exception:
            error = {}
        if isinstance(error, dict):
            raw = error.get("error")
            detail = None
            if isinstance(raw, dict):
                detail = raw.get("code") or raw.get("type")
                if isinstance(raw.get("message"), str):
                    message = raw["message"]
            elif isinstance(raw, str):
                detail = raw
                if isinstance(error.get("error_description"), str):
                    message = error["error_description"]
            if isinstance(detail, str) and detail.strip():
                if detail.strip() == "refresh_token_reused":
                    # Another client consumed this rotating token. Stimma keeps
                    # its own session precisely to avoid this, so it means the
                    # credential was copied or the store was restored.
                    raise ChatGPTAuthError(
                        "Session invalidated by another sign-in. Sign in again.",
                        code="chatgpt_session_superseded",
                        relogin_required=True,
                    )
                if detail.strip() in {"invalid_grant", "invalid_token", "invalid_request"}:
                    relogin = True
        raise ChatGPTAuthError(message, code=code, relogin_required=relogin)

    payload = response.json()
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise ChatGPTAuthError(
            "OpenAI's refresh response did not include an access token.",
            code="chatgpt_refresh_invalid",
            relogin_required=True,
        )

    _access_token = access_token
    rotated = str(payload.get("refresh_token") or "").strip()
    if rotated:
        _token_store.set(rotated)

    account = load_account() or ChatGPTAccount()
    account.account_id = account_id_from_token(access_token) or account.account_id
    account.email = email_from_token(access_token) or account.email
    account.plan = plan_from_token(access_token) or account.plan
    account.last_refresh = _now_iso()
    save_account(account)
    return access_token


async def get_access_token(*, force_refresh: bool = False) -> str:
    """Return a usable access token, refreshing when needed.

    Serialized on a lock: OpenAI rotates the refresh token, so two concurrent
    refreshes would race and one would invalidate the other's result.
    """
    global _access_token

    if not force_refresh and not _token_is_expiring(_access_token, REFRESH_SKEW_SECONDS):
        return _access_token  # type: ignore[return-value]

    async with _refresh_lock:
        # Another waiter may have refreshed while this one queued.
        if not force_refresh and not _token_is_expiring(
            _access_token, REFRESH_SKEW_SECONDS
        ):
            return _access_token  # type: ignore[return-value]
        return await _refresh_access_token()


def request_headers(access_token: str) -> dict[str, str]:
    """Identity headers for chatgpt.com/backend-api/codex.

    Stimma identifies itself as itself. It does not send ``codex_cli_rs`` or a
    Codex-shaped User-Agent to pass an allowlist.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": _user_agent(),
        "originator": ORIGINATOR,
    }
    account_id = account_id_from_token(access_token)
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    return headers


# --- catalog and usage ------------------------------------------------------

# Shown only when live discovery is unavailable, and marked as such. The live
# list is authoritative: OpenAI adds and retires Codex-backend slugs often, and
# a stale hardcoded list surfaces models that 400 on selection.
FALLBACK_MODELS: list[dict[str, Any]] = [
    {"id": "gpt-5.6-terra", "name": "GPT-5.6 Terra"},
    {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol"},
    {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna"},
    {"id": "gpt-5.5", "name": "GPT-5.5"},
    {"id": "gpt-5.3-codex", "name": "GPT-5.3 Codex"},
]


def _pretty_model_name(slug: str) -> str:
    if slug.startswith("gpt-"):
        parts = slug.split("-")
        rendered = ["GPT-" + parts[1]] if len(parts) > 1 else ["GPT"]
        rendered += [part.capitalize() for part in parts[2:]]
        return " ".join(rendered)
    return slug


async def fetch_models(access_token: str) -> list[dict[str, Any]]:
    """List the models this ChatGPT account can actually use.

    Returns an empty list when the account has no Codex entitlement, which the
    caller surfaces as ``chatgpt_no_models`` rather than silently falling back.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        try:
            response = await client.get(
                f"{MODELS_URL}?client_version=1.0.0",
                headers=request_headers(access_token),
            )
        except httpx.HTTPError as e:
            raise ChatGPTAuthError(
                f"Could not reach OpenAI to list models: {e}",
                code="chatgpt_network_error",
            ) from e

    if response.status_code == 401:
        raise ChatGPTAuthError(
            "ChatGPT session is no longer valid.",
            code="chatgpt_not_signed_in",
            relogin_required=True,
        )
    if response.status_code == 429:
        raise ChatGPTAuthError(
            "ChatGPT plan limit reached.",
            code="chatgpt_rate_limited",
            retry_after=_retry_after_seconds(response.headers),
        )
    if response.status_code != 200:
        raise ChatGPTAuthError(
            f"OpenAI returned HTTP {response.status_code} listing models.",
            code="chatgpt_models_failed",
        )

    try:
        entries = (response.json() or {}).get("models") or []
    except Exception:
        entries = []

    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        visibility = str(item.get("visibility") or "").strip().lower()
        if visibility in {"hide", "hidden"}:
            continue
        # `supported_in_api` describes the public OpenAI API, not this
        # OAuth-backed backend. Filtering on it drops models that work here.
        priority = item.get("priority")
        rank = int(priority) if isinstance(priority, (int, float)) else 10_000
        efforts = [
            str(level).strip().lower()
            for level in (item.get("supported_reasoning_efforts") or [])
            if str(level).strip()
        ]
        ranked.append((
            rank,
            {
                "id": slug,
                "name": str(item.get("display_name") or "").strip() or _pretty_model_name(slug),
                "reasoning_efforts": efforts,
                "default_reasoning_effort": (
                    str(item.get("default_reasoning_effort") or "").strip().lower() or None
                ),
                "context_length": item.get("context_window") or item.get("max_context_window"),
            },
        ))

    ranked.sort(key=lambda row: (row[0], row[1]["id"]))
    return [row[1] for row in ranked]


async def fetch_usage(access_token: str) -> Optional[dict[str, Any]]:
    """Read ChatGPT plan rate-limit windows. None when unavailable."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        try:
            response = await client.get(USAGE_URL, headers=request_headers(access_token))
        except httpx.HTTPError:
            return None

    if response.status_code != 200:
        return None
    try:
        payload = response.json() or {}
    except Exception:
        return None

    rate_limit = payload.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return None

    windows = []
    for key, label in (("primary_window", "primary"), ("secondary_window", "secondary")):
        window = rate_limit.get(key)
        if not isinstance(window, dict):
            continue
        used = window.get("used_percent")
        resets_at = window.get("resets_at") or window.get("reset_at")
        resets_in = window.get("resets_in_seconds")
        if not isinstance(resets_in, (int, float)) and isinstance(resets_at, (int, float)):
            # Live accounts send an absolute unix timestamp instead.
            resets_in = max(0, int(resets_at - time.time()))
        windows.append({
            "window": label,
            "used_percent": float(used) if isinstance(used, (int, float)) else None,
            "resets_at": resets_at,
            "resets_in_seconds": resets_in if isinstance(resets_in, (int, float)) else None,
            "label": window.get("window_label") or window.get("label"),
        })
    return {"windows": windows} if windows else None

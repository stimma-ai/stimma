"""
Firebase token management via REST API.

Handles:
- Exchanging custom tokens for ID + refresh tokens
- Refreshing ID tokens when they expire
- Getting valid ID tokens (with auto-refresh)
"""
import time
from typing import Optional, TypedDict

import httpx

from core.logging import get_logger
from privacy_lockdown import is_privacy_lockdown_enabled

log = get_logger(__name__)

# Firebase project configuration
# These are public web API keys (safe to embed in client apps)
FIREBASE_API_KEY = "AIzaSyB4xzVbmK5OnZGfs9qSwGJdPVbBoddYCvw"
FIREBASE_PROJECT_ID = "stimma-13a84"

# Firebase REST API endpoints
IDENTITY_TOOLKIT_URL = "https://identitytoolkit.googleapis.com/v1"
SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1"


class TokenResult(TypedDict):
    """Result from token exchange or refresh."""
    id_token: str        # Firebase ID token (use for API calls)
    refresh_token: str   # Long-lived refresh token
    expiry: float        # Unix timestamp when id_token expires


class AuthRefreshError(Exception):
    """Base error for Firebase ID-token refresh failures."""


class AuthSessionExpiredError(AuthRefreshError):
    """Raised when the stored refresh token is invalid, revoked, or expired."""


class AuthNetworkError(AuthRefreshError):
    """Raised when token refresh could not reach Firebase."""


_INVALID_REFRESH_TOKEN_MARKERS = {
    "invalid_refresh_token",
    "invalid_grant",
    "token_expired",
    "user_token_expired",
    "invalid_user_token",
    "user_disabled",
    "user_not_found",
    "refresh_token_not_found",
}


def _firebase_error_text(response: httpx.Response) -> str:
    """Extract Firebase error detail without including credentials."""
    pieces: list[str] = []
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw_error = payload.get("error")
        if isinstance(raw_error, dict):
            for key in ("message", "status", "code"):
                value = raw_error.get(key)
                if value is not None:
                    pieces.append(str(value))
        elif isinstance(raw_error, str):
            pieces.append(raw_error)

    try:
        if response.text:
            pieces.append(response.text[:500])
    except Exception:
        pass

    return " ".join(pieces).lower()


def _is_invalid_refresh_token_error(exc: httpx.HTTPStatusError) -> bool:
    """Return True when Firebase says the refresh token can no longer be used."""
    status = exc.response.status_code
    if status not in (400, 401, 403):
        return False

    error_text = _firebase_error_text(exc.response)
    return any(marker in error_text for marker in _INVALID_REFRESH_TOKEN_MARKERS)


async def _refresh_id_token_classified(refresh_token: str) -> TokenResult:
    """Refresh an ID token and classify failures for callers."""
    try:
        return await refresh_id_token(refresh_token)
    except httpx.HTTPStatusError as e:
        if _is_invalid_refresh_token_error(e):
            raise AuthSessionExpiredError("Stimma Cloud session expired") from e
        raise AuthRefreshError(
            f"Firebase token refresh failed with HTTP {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        raise AuthNetworkError(str(e) or type(e).__name__) from e
    except Exception as e:
        raise AuthRefreshError(str(e) or type(e).__name__) from e


def _clear_auth_after_session_expiry() -> None:
    """Clear local auth material after Firebase rejects the refresh token."""
    try:
        from auth_storage import clear_auth_state
        clear_auth_state()
    except Exception as e:
        log.warning("failed to clear auth state after session expiry", error=str(e))


async def exchange_custom_token(custom_token: str) -> TokenResult:
    """Exchange a Firebase custom token for ID + refresh tokens.

    Called after OAuth callback receives custom_token from stimma.cloud.

    Args:
        custom_token: The custom token from stimma.cloud's OAuth flow

    Returns:
        TokenResult with id_token, refresh_token, and expiry timestamp

    Raises:
        httpx.HTTPStatusError: If the Firebase API returns an error
        Exception: For network or other errors
    """
    if is_privacy_lockdown_enabled():
        raise AuthNetworkError("Privacy Lockdown is enabled")

    url = f"{IDENTITY_TOOLKIT_URL}/accounts:signInWithCustomToken"
    params = {"key": FIREBASE_API_KEY}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params=params,
            json={
                "token": custom_token,
                "returnSecureToken": True
            },
            timeout=30.0
        )
        response.raise_for_status()

        data = response.json()

        # Calculate expiry timestamp
        # Firebase returns expiresIn as a string of seconds
        expires_in = int(data.get("expiresIn", "3600"))
        expiry = time.time() + expires_in

        log.debug("exchanged custom token for firebase tokens",
                  expires_in=expires_in)

        return TokenResult(
            id_token=data["idToken"],
            refresh_token=data["refreshToken"],
            expiry=expiry
        )


async def refresh_id_token(refresh_token: str) -> TokenResult:
    """Use refresh_token to get a fresh ID token.

    Called when cached id_token is expired or about to expire.

    Args:
        refresh_token: The long-lived refresh token

    Returns:
        TokenResult with new id_token, refresh_token, and expiry timestamp

    Raises:
        httpx.HTTPStatusError: If the Firebase API returns an error
        Exception: For network or other errors
    """
    if is_privacy_lockdown_enabled():
        raise AuthNetworkError("Privacy Lockdown is enabled")

    url = f"{SECURE_TOKEN_URL}/token"
    params = {"key": FIREBASE_API_KEY}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params=params,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0
        )
        response.raise_for_status()

        data = response.json()

        # Calculate expiry timestamp
        expires_in = int(data.get("expires_in", "3600"))
        expiry = time.time() + expires_in

        log.debug("refreshed firebase id token", expires_in=expires_in)

        return TokenResult(
            id_token=data["id_token"],
            refresh_token=data["refresh_token"],
            expiry=expiry
        )


async def get_valid_id_token(*, raise_on_failure: bool = False) -> Optional[str]:
    """Get a valid ID token, refreshing if necessary.

    Loads auth state, checks expiry, refreshes if needed, saves updated state.

    Returns:
        Valid ID token string, or None if not logged in or refresh fails.

    Raises:
        AuthSessionExpiredError: If raise_on_failure=True and the refresh
            token is invalid/revoked/expired.
        AuthNetworkError: If raise_on_failure=True and Firebase is unreachable.
        AuthRefreshError: If raise_on_failure=True and refresh fails otherwise.
    """
    if is_privacy_lockdown_enabled():
        log.info("skipping Firebase ID token access in Privacy Lockdown")
        if raise_on_failure:
            raise AuthNetworkError("Privacy Lockdown is enabled")
        return None

    from auth_storage import load_auth_state, save_auth_state, is_token_expired

    auth_state = load_auth_state()
    if not auth_state:
        log.debug("no auth state found")
        return None

    refresh_token = auth_state.get('refresh_token')
    if not refresh_token:
        log.debug("no refresh token in auth state")
        if raise_on_failure:
            raise AuthSessionExpiredError("No saved Stimma Cloud session")
        return None

    # Check if current token is valid
    if not is_token_expired(auth_state):
        id_token = auth_state.get('id_token')
        if id_token:
            log.debug("using cached id token")
            return id_token

    # Token is expired or missing, need to refresh
    log.info("id token expired or missing, refreshing")

    try:
        result = await _refresh_id_token_classified(refresh_token)

        # Update auth state with new tokens
        auth_state['id_token'] = result['id_token']
        auth_state['refresh_token'] = result['refresh_token']
        auth_state['id_token_expiry'] = result['expiry']

        save_auth_state(auth_state)

        log.info("refreshed and saved new id token")
        return result['id_token']

    except AuthSessionExpiredError:
        log.info("stored Stimma Cloud session is no longer valid")
        _clear_auth_after_session_expiry()
        if raise_on_failure:
            raise
    except AuthNetworkError as e:
        log.warning("could not reach Firebase to refresh id token", error=str(e))
        if raise_on_failure:
            raise
    except AuthRefreshError as e:
        log.error("failed to refresh id token", error=str(e))
        if raise_on_failure:
            raise
    return None


async def force_refresh_id_token(*, raise_on_failure: bool = False) -> Optional[str]:
    """Force-refresh the ID token, ignoring cached expiry.

    Used as a reactive measure when a 401 is received from the server,
    indicating the cached token is actually expired despite local checks.

    Returns:
        Fresh ID token string, or None if not logged in or refresh fails.
    """
    if is_privacy_lockdown_enabled():
        log.info("skipping Firebase ID token refresh in Privacy Lockdown")
        if raise_on_failure:
            raise AuthNetworkError("Privacy Lockdown is enabled")
        return None

    from auth_storage import load_auth_state, save_auth_state

    auth_state = load_auth_state()
    if not auth_state:
        return None

    refresh_token = auth_state.get('refresh_token')
    if not refresh_token:
        if raise_on_failure:
            raise AuthSessionExpiredError("No saved Stimma Cloud session")
        return None

    log.info("force-refreshing id token after 401")

    try:
        result = await _refresh_id_token_classified(refresh_token)

        auth_state['id_token'] = result['id_token']
        auth_state['refresh_token'] = result['refresh_token']
        auth_state['id_token_expiry'] = result['expiry']

        save_auth_state(auth_state)

        log.info("force-refreshed and saved new id token")
        return result['id_token']

    except AuthSessionExpiredError:
        log.info("stored Stimma Cloud session is no longer valid during force refresh")
        _clear_auth_after_session_expiry()
        if raise_on_failure:
            raise
    except AuthNetworkError as e:
        log.warning("could not reach Firebase during force refresh", error=str(e))
        if raise_on_failure:
            raise
    except AuthRefreshError as e:
        log.error("force refresh failed", error=str(e))
        if raise_on_failure:
            raise
    return None

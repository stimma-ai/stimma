"""
Persist non-secret Stimma Cloud auth state to disk.

Display/cache state is stored as JSON at: {app_data_dir}/cloud_auth.json.
Refresh tokens are stored through OS credential storage when available and are
never written to cloud_auth.json. ID tokens are cached in memory only.
"""
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Protocol, TypedDict

import app_dirs
from app_context import get_bundle_id, get_sandbox
from core.logging import get_logger

log = get_logger(__name__)

# Auth state file name (stored in app data directory)
AUTH_STATE_FILENAME = "cloud_auth.json"
KEYCHAIN_SERVICE = "Stimma Cloud Auth"

_SECRET_KEYS = {"refresh_token", "id_token"}
_cached_id_token: Optional[str] = None
_cached_id_token_expiry: Optional[float] = None
_memory_refresh_token: Optional[str] = None
_warned_memory_fallback = False
_token_store_override: Optional["RefreshTokenStore"] = None


class AuthState(TypedDict, total=False):
    """Authentication state for Stimma Cloud.

    The token fields may be present in values returned by load_auth_state(),
    but save_auth_state() strips them before writing cloud_auth.json.
    """
    user: dict           # {uid, email, displayName, photoURL}
    tier: str            # 'free', 'starter', 'pro', etc.
    refresh_token: str   # Firebase refresh token (secure storage or memory)
    id_token: str        # Firebase ID token (memory cache only)
    id_token_expiry: float  # Unix timestamp when id_token expires


class SecureTokenStorageUnavailable(Exception):
    """Raised when the platform credential store cannot be used."""


class RefreshTokenStore(Protocol):
    """Minimal storage interface for the Firebase refresh token."""

    backend_name: str

    def get_refresh_token(self) -> Optional[str]:
        ...

    def set_refresh_token(self, token: str) -> None:
        ...

    def clear_refresh_token(self) -> None:
        ...


class MacOSKeychainRefreshTokenStore:
    """Store refresh tokens in the user's macOS Keychain."""

    backend_name = "macos-keychain"

    def __init__(self) -> None:
        self._security_bin = shutil.which("security")
        if not self._security_bin:
            raise SecureTokenStorageUnavailable("security command not found")

    @property
    def _account(self) -> str:
        return f"{get_bundle_id()}:{get_sandbox()}:stimma-cloud-refresh-token"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        if not self._security_bin:
            raise SecureTokenStorageUnavailable("security command not found")
        try:
            return subprocess.run(
                [self._security_bin, *args],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

    def get_refresh_token(self) -> Optional[str]:
        result = self._run([
            "find-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", self._account,
            "-w",
        ])
        if result.returncode == 44:
            return None
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            if "could not be found" in message.lower():
                return None
            raise SecureTokenStorageUnavailable(message or "keychain lookup failed")
        token = result.stdout.rstrip("\n")
        return token or None

    def set_refresh_token(self, token: str) -> None:
        result = self._run([
            "add-generic-password",
            "-U",
            "-s", KEYCHAIN_SERVICE,
            "-a", self._account,
            "-w", token,
        ])
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise SecureTokenStorageUnavailable(message or "keychain write failed")

    def clear_refresh_token(self) -> None:
        result = self._run([
            "delete-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", self._account,
        ])
        if result.returncode in (0, 44):
            return
        message = (result.stderr or result.stdout or "").strip()
        if "could not be found" in message.lower():
            return
        raise SecureTokenStorageUnavailable(message or "keychain delete failed")


def _get_auth_state_path() -> Path:
    """Get the path to the auth state file."""
    return app_dirs.get_data_dir() / AUTH_STATE_FILENAME


def _get_token_store() -> Optional[RefreshTokenStore]:
    """Return the best available secure refresh-token store."""
    if _token_store_override is not None:
        return _token_store_override

    if platform.system() == "Darwin":
        try:
            return MacOSKeychainRefreshTokenStore()
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
            return None

    _log_memory_fallback(f"no OS credential storage backend for {platform.system()}")
    return None


def _log_memory_fallback(reason: str) -> None:
    """Log the memory-only fallback once per process."""
    global _warned_memory_fallback
    if _warned_memory_fallback:
        return
    _warned_memory_fallback = True
    log.warning(
        "secure auth token storage unavailable; refresh token will be kept in memory only",
        reason=reason,
    )


def _get_refresh_token() -> Optional[str]:
    """Load refresh token from secure storage, falling back to process memory."""
    store = _get_token_store()
    if store is not None:
        try:
            token = store.get_refresh_token()
            if token:
                return token
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
    return _memory_refresh_token


def _set_refresh_token(token: str) -> None:
    """Persist refresh token through secure storage when possible."""
    global _memory_refresh_token
    store = _get_token_store()
    if store is not None:
        try:
            store.set_refresh_token(token)
            _memory_refresh_token = None
            log.debug("saved cloud refresh token", backend=store.backend_name)
            return
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))

    _memory_refresh_token = token
    _log_memory_fallback("using process memory for refresh token")


def _clear_refresh_token() -> None:
    """Clear refresh token from secure storage and memory."""
    global _memory_refresh_token
    store = _get_token_store()
    if store is not None:
        try:
            store.clear_refresh_token()
            log.debug("cleared cloud refresh token", backend=store.backend_name)
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
    _memory_refresh_token = None


def _cache_id_token(id_token: Optional[str], expiry: Optional[float]) -> None:
    """Keep the short-lived ID token in memory only."""
    global _cached_id_token, _cached_id_token_expiry
    _cached_id_token = id_token or None
    _cached_id_token_expiry = expiry if id_token else None


def _write_auth_state_json(path: Path, state: AuthState) -> None:
    """Atomically write non-secret auth state JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        suffix='.json',
        dir=path.parent,
        prefix='cloud_auth_'
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2)

        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise


def save_auth_state(state: AuthState) -> None:
    """Save auth state to disk.

    Uses atomic writes (write to temp file, then rename) to avoid corruption.
    Token fields are stripped before writing JSON.
    """
    path = _get_auth_state_path()

    refresh_token = state.get('refresh_token')
    if refresh_token:
        _set_refresh_token(refresh_token)

    id_token = state.get('id_token')
    if id_token:
        _cache_id_token(id_token, state.get('id_token_expiry'))

    non_secret_state = {
        key: value
        for key, value in state.items()
        if key not in _SECRET_KEYS
    }

    try:
        _write_auth_state_json(path, non_secret_state)
        log.debug("saved auth state", path=str(path))
    except Exception as e:
        log.error("failed to save auth state", error=str(e))
        raise


def load_auth_state() -> Optional[AuthState]:
    """Load auth state from disk.

    Returns None if not logged in or if the file is missing/malformed.
    """
    path = _get_auth_state_path()

    if not path.exists():
        return None

    try:
        with open(path, 'r') as f:
            data = json.load(f)

        # Basic validation - ensure it's a dict
        if not isinstance(data, dict):
            log.warning("auth state file is not a dict, ignoring", path=str(path))
            return None

        needs_rewrite = any(key in data for key in _SECRET_KEYS)

        legacy_refresh_token = data.pop('refresh_token', None)
        if legacy_refresh_token:
            _set_refresh_token(legacy_refresh_token)
            log.info("migrated cloud refresh token out of auth state JSON")

        legacy_id_token = data.pop('id_token', None)
        if legacy_id_token:
            _cache_id_token(legacy_id_token, data.get('id_token_expiry'))
            log.info("migrated cloud id token to memory cache")

        if needs_rewrite:
            try:
                _write_auth_state_json(path, data)
                log.info("rewrote auth state JSON without token fields", path=str(path))
            except Exception as e:
                log.error("failed to rewrite auth state JSON during token migration", error=str(e))
                raise

        refresh_token = _get_refresh_token()
        if refresh_token:
            data['refresh_token'] = refresh_token

        if _cached_id_token:
            data['id_token'] = _cached_id_token
            if _cached_id_token_expiry is not None:
                data['id_token_expiry'] = _cached_id_token_expiry

        return data
    except json.JSONDecodeError as e:
        log.warning("auth state file is malformed JSON", path=str(path), error=str(e))
        return None
    except Exception as e:
        log.warning("failed to load auth state", path=str(path), error=str(e))
        return None


def clear_auth_state() -> None:
    """Delete auth state file and local auth tokens (logout/session expiry)."""
    path = _get_auth_state_path()

    _clear_refresh_token()
    _cache_id_token(None, None)

    if path.exists():
        try:
            os.unlink(path)
            log.info("cleared auth state", path=str(path))
        except Exception as e:
            log.error("failed to clear auth state", path=str(path), error=str(e))
            raise


def is_token_expired(state: AuthState) -> bool:
    """Check if id_token is expired or will expire within 5 minutes.

    Returns True if:
    - No id_token_expiry is set
    - Token has expired
    - Token will expire within 5 minutes (300 seconds)
    """
    import time

    expiry = state.get('id_token_expiry')
    if expiry is None:
        return True

    # Consider expired if within 5 minutes of expiry
    buffer_seconds = 300
    return time.time() >= (expiry - buffer_seconds)

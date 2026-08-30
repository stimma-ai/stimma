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
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, TypedDict

import app_dirs
from app_context import BUNDLE_ID_DEBUG, get_bundle_id, get_sandbox
from core.logging import get_logger

log = get_logger(__name__)

# Auth state file name (stored in app data directory)
AUTH_STATE_FILENAME = "cloud_auth.json"
AUTH_TOKEN_FALLBACK_FILENAME = "cloud_auth_tokens.json"
KEYCHAIN_SERVICE = "Stimma Cloud Auth"
CREDENTIAL_LABEL = "Stimma Cloud refresh token"



@dataclass(frozen=True)
class CredentialKey:
    """Names one logical secret across every platform credential backend.

    Each backend keys entries differently, so the whole naming surface is
    grouped here rather than hard-coded per store. ``CLOUD_CREDENTIAL_KEY``
    reproduces the original Stimma Cloud names byte for byte — changing any
    of them would orphan credentials already written by shipped builds.
    """

    keychain_service: str      # macOS: -s argument
    account_kind: str          # macOS account suffix / Secret Service "kind"
    windows_target: str        # Windows target, {bundle}/{sandbox} templated
    label: str                 # Secret Service human-readable label
    fallback_filename: str     # Linux 0600 file fallback


CLOUD_CREDENTIAL_KEY = CredentialKey(
    keychain_service=KEYCHAIN_SERVICE,
    account_kind="stimma-cloud-refresh-token",
    windows_target="Stimma Cloud:{bundle}:{sandbox}:refresh-token",
    label=CREDENTIAL_LABEL,
    fallback_filename=AUTH_TOKEN_FALLBACK_FILENAME,
)

# ChatGPT-plan OAuth. Deliberately a distinct credential so signing out of
# ChatGPT never touches the Stimma Cloud session, and vice versa.
CHATGPT_CREDENTIAL_KEY = CredentialKey(
    keychain_service="Stimma ChatGPT Auth",
    account_kind="stimma-chatgpt-refresh-token",
    windows_target="Stimma ChatGPT:{bundle}:{sandbox}:refresh-token",
    label="Stimma ChatGPT refresh token",
    fallback_filename="chatgpt_auth_tokens.json",
)


_SECRET_KEYS = {"refresh_token", "id_token"}
_cached_id_token: Optional[str] = None
_cached_id_token_expiry: Optional[float] = None
_memory_refresh_token: Optional[str] = None
_warned_memory_fallback = False
_warned_file_fallback = False
_token_store_override: Optional["RefreshTokenStore"] = None


class AuthState(TypedDict, total=False):
    """Authentication state for Stimma Cloud.

    The token fields may be present in values returned by load_auth_state(),
    but save_auth_state() strips them before writing cloud_auth.json.
    """
    user: dict           # {uid, email, displayName, photoURL}
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

    def __init__(self, key: CredentialKey = CLOUD_CREDENTIAL_KEY) -> None:
        self._security_bin = shutil.which("security")
        if not self._security_bin:
            raise SecureTokenStorageUnavailable("security command not found")
        self._key = key
        self._default_keychain = self._resolve_default_keychain()

    @property
    def _account(self) -> str:
        return self._account_for(get_bundle_id())

    def _account_for(self, bundle_id: str) -> str:
        return f"{bundle_id}:{get_sandbox()}:{self._key.account_kind}"

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

    def _resolve_default_keychain(self) -> Optional[str]:
        """Resolve the user keychain independently of the mutable search list."""
        result = self._run(["default-keychain", "-d", "user"])
        if result.returncode != 0:
            return None
        keychain = result.stdout.strip().strip('"')
        return keychain or None

    def _keychain_args(self) -> list[str]:
        """Target the default keychain when macOS reports one."""
        return [self._default_keychain] if self._default_keychain else []

    def get_refresh_token(self) -> Optional[str]:
        return self._get_for_account(self._account)

    def get_legacy_refresh_token(self) -> Optional[str]:
        return self._get_for_account(self._account_for(BUNDLE_ID_DEBUG))

    def _get_for_account(self, account: str) -> Optional[str]:
        result = self._run([
            "find-generic-password",
            "-s", self._key.keychain_service,
            "-a", account,
            "-w",
            *self._keychain_args(),
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
            "-s", self._key.keychain_service,
            "-a", self._account,
            "-w", token,
            *self._keychain_args(),
        ])
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise SecureTokenStorageUnavailable(message or "keychain write failed")

    def clear_refresh_token(self) -> None:
        self._clear_for_account(self._account)

    def clear_legacy_refresh_token(self) -> None:
        self._clear_for_account(self._account_for(BUNDLE_ID_DEBUG))

    def _clear_for_account(self, account: str) -> None:
        result = self._run([
            "delete-generic-password",
            "-s", self._key.keychain_service,
            "-a", account,
            *self._keychain_args(),
        ])
        if result.returncode in (0, 44):
            return
        message = (result.stderr or result.stdout or "").strip()
        if "could not be found" in message.lower():
            return
        raise SecureTokenStorageUnavailable(message or "keychain delete failed")


class WindowsCredentialManagerRefreshTokenStore:
    """Store refresh tokens in Windows Credential Manager."""

    backend_name = "windows-credential-manager"

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self, key: CredentialKey = CLOUD_CREDENTIAL_KEY) -> None:
        self._key = key
        try:
            import ctypes
            from ctypes import wintypes
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

        if not hasattr(ctypes, "WinDLL"):
            raise SecureTokenStorageUnavailable("ctypes.WinDLL unavailable")

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        class FILETIME(ctypes.Structure):
            _fields_ = [
                ("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD),
            ]

        class CREDENTIAL_ATTRIBUTE(ctypes.Structure):
            _fields_ = [
                ("Keyword", wintypes.LPWSTR),
                ("Flags", wintypes.DWORD),
                ("ValueSize", wintypes.DWORD),
                ("Value", ctypes.POINTER(ctypes.c_ubyte)),
            ]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTE)),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self._CREDENTIAL = CREDENTIAL
        self._PCREDENTIAL = ctypes.POINTER(CREDENTIAL)

        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(self._PCREDENTIAL),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(CREDENTIAL),
            wintypes.DWORD,
        ]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    @property
    def _target_name(self) -> str:
        return self._target_for(get_bundle_id())

    def _target_for(self, bundle_id: str) -> str:
        return self._key.windows_target.format(
            bundle=bundle_id, sandbox=get_sandbox()
        )

    def _raise_last_error(self, operation: str) -> None:
        error_code = self._ctypes.get_last_error()
        raise SecureTokenStorageUnavailable(f"{operation} failed with Windows error {error_code}")

    def get_refresh_token(self) -> Optional[str]:
        return self._get_for_target(self._target_name)

    def get_legacy_refresh_token(self) -> Optional[str]:
        return self._get_for_target(self._target_for(BUNDLE_ID_DEBUG))

    def _get_for_target(self, target_name: str) -> Optional[str]:
        credential_ptr = self._PCREDENTIAL()
        ok = self._advapi32.CredReadW(
            target_name,
            self.CRED_TYPE_GENERIC,
            0,
            self._ctypes.byref(credential_ptr),
        )
        if not ok:
            error_code = self._ctypes.get_last_error()
            if error_code == self.ERROR_NOT_FOUND:
                return None
            raise SecureTokenStorageUnavailable(
                f"Credential Manager lookup failed with Windows error {error_code}"
            )

        try:
            credential = credential_ptr.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize == 0:
                return None
            raw = self._ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return raw.decode("utf-16-le") or None
        finally:
            self._advapi32.CredFree(credential_ptr)

    def set_refresh_token(self, token: str) -> None:
        token_bytes = token.encode("utf-16-le")
        token_buffer = self._ctypes.create_string_buffer(token_bytes)

        credential = self._CREDENTIAL()
        credential.Flags = 0
        credential.Type = self.CRED_TYPE_GENERIC
        target_name = self._ctypes.c_wchar_p(self._target_name)
        comment = self._ctypes.c_wchar_p(CREDENTIAL_LABEL)
        username = self._ctypes.c_wchar_p("Stimma Cloud")

        credential.TargetName = target_name
        credential.Comment = comment
        credential.CredentialBlobSize = len(token_bytes)
        credential.CredentialBlob = self._ctypes.cast(
            token_buffer,
            self._ctypes.POINTER(self._ctypes.c_ubyte),
        )
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.AttributeCount = 0
        credential.Attributes = None
        credential.TargetAlias = None
        credential.UserName = username

        ok = self._advapi32.CredWriteW(self._ctypes.byref(credential), 0)
        if not ok:
            self._raise_last_error("Credential Manager write")

    def clear_refresh_token(self) -> None:
        self._clear_for_target(self._target_name)

    def clear_legacy_refresh_token(self) -> None:
        self._clear_for_target(self._target_for(BUNDLE_ID_DEBUG))

    def _clear_for_target(self, target_name: str) -> None:
        ok = self._advapi32.CredDeleteW(
            target_name,
            self.CRED_TYPE_GENERIC,
            0,
        )
        if ok:
            return
        error_code = self._ctypes.get_last_error()
        if error_code == self.ERROR_NOT_FOUND:
            return
        raise SecureTokenStorageUnavailable(
            f"Credential Manager delete failed with Windows error {error_code}"
        )


class LinuxSecretServiceRefreshTokenStore:
    """Store refresh tokens via the Freedesktop Secret Service DBus API."""

    backend_name = "linux-secret-service"

    def __init__(self, key: CredentialKey = CLOUD_CREDENTIAL_KEY) -> None:
        self._key = key

    @property
    def _attributes(self) -> dict[str, str]:
        return self._attributes_for(get_bundle_id())

    def _attributes_for(self, bundle_id: str) -> dict[str, str]:
        return {
            "application": "Stimma",
            "kind": self._key.account_kind,
            "bundle_id": bundle_id,
            "sandbox": get_sandbox(),
        }

    @property
    def _label(self) -> str:
        return f"{self._key.label} ({get_bundle_id()}/{get_sandbox()})"

    def _get_collection(self):
        try:
            import secretstorage
            from secretstorage.exceptions import SecretStorageException
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

        try:
            connection = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(connection)
            if collection.is_locked() and not collection.unlock(timeout=5.0):
                raise SecureTokenStorageUnavailable("Secret Service collection is locked")
            return collection
        except SecretStorageException as e:
            raise SecureTokenStorageUnavailable(str(e)) from e
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

    def _iter_items(self, attributes: Optional[dict[str, str]] = None):
        collection = self._get_collection()
        return list(collection.search_items(attributes or self._attributes))

    def get_refresh_token(self) -> Optional[str]:
        return self._get_for_attributes(self._attributes)

    def get_legacy_refresh_token(self) -> Optional[str]:
        return self._get_for_attributes(self._attributes_for(BUNDLE_ID_DEBUG))

    def _get_for_attributes(self, attributes: dict[str, str]) -> Optional[str]:
        try:
            for item in self._iter_items(attributes):
                if item.is_locked() and not item.unlock(timeout=5.0):
                    continue
                secret = item.get_secret()
                if secret:
                    return secret.decode("utf-8")
            return None
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

    def set_refresh_token(self, token: str) -> None:
        try:
            collection = self._get_collection()
            collection.create_item(
                self._label,
                self._attributes,
                token.encode("utf-8"),
                replace=True,
            )
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

    def clear_refresh_token(self) -> None:
        self._clear_for_attributes(self._attributes)

    def clear_legacy_refresh_token(self) -> None:
        self._clear_for_attributes(self._attributes_for(BUNDLE_ID_DEBUG))

    def _clear_for_attributes(self, attributes: dict[str, str]) -> None:
        try:
            for item in self._iter_items(attributes):
                item.delete()
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e


class FileRefreshTokenStore:
    """Fallback persistent refresh-token store for Linux without Secret Service."""

    backend_name = "linux-file-fallback"

    def __init__(self, key: CredentialKey = CLOUD_CREDENTIAL_KEY) -> None:
        if platform.system() != "Linux":
            raise SecureTokenStorageUnavailable("file fallback is only enabled for Linux")
        self._key = key

    @property
    def _path(self) -> Path:
        return app_dirs.get_data_dir() / self._key.fallback_filename

    def get_refresh_token(self) -> Optional[str]:
        path = self._path
        if not path.exists():
            return None
        try:
            if hasattr(os, "chmod"):
                os.chmod(path, 0o600)
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            token = data.get("refresh_token")
            return token if isinstance(token, str) and token else None
        except json.JSONDecodeError as e:
            raise SecureTokenStorageUnavailable(f"fallback token file is malformed: {e}") from e
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

    def set_refresh_token(self, token: str) -> None:
        path = self._path
        try:
            _write_auth_state_json(path, {"refresh_token": token})
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e

    def clear_refresh_token(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except Exception as e:
            raise SecureTokenStorageUnavailable(str(e)) from e


def _get_auth_state_path() -> Path:
    """Get the path to the auth state file."""
    return app_dirs.get_data_dir() / AUTH_STATE_FILENAME


def _get_file_fallback_store(
    key: CredentialKey = CLOUD_CREDENTIAL_KEY,
) -> Optional[RefreshTokenStore]:
    """Return a persistent Linux fallback store if it is allowed."""
    if platform.system() != "Linux":
        return None
    try:
        return FileRefreshTokenStore(key)
    except SecureTokenStorageUnavailable as e:
        _log_memory_fallback(str(e))
        return None


def _get_token_store(
    key: CredentialKey = CLOUD_CREDENTIAL_KEY,
) -> Optional[RefreshTokenStore]:
    """Return the best available secure refresh-token store."""
    if _token_store_override is not None and key is CLOUD_CREDENTIAL_KEY:
        return _token_store_override

    system = platform.system()
    if system == "Darwin":
        try:
            return MacOSKeychainRefreshTokenStore(key)
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
            return None

    if system == "Windows":
        try:
            return WindowsCredentialManagerRefreshTokenStore(key)
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
            return None

    if system == "Linux":
        try:
            return LinuxSecretServiceRefreshTokenStore(key)
        except SecureTokenStorageUnavailable as e:
            _log_file_fallback(str(e))
            return _get_file_fallback_store(key)

    _log_memory_fallback(f"no OS credential storage backend for {system}")
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


def _log_file_fallback(reason: str) -> None:
    """Log the Linux persistent file fallback once per process."""
    global _warned_file_fallback
    if _warned_file_fallback:
        return
    _warned_file_fallback = True
    log.warning(
        "Linux Secret Service unavailable; refresh token will be stored in a 0600 fallback file",
        reason=reason,
    )


def _log_store_failure_for_fallback(store: RefreshTokenStore, reason: str) -> None:
    """Log where token storage will fall back after a platform-store failure."""
    if platform.system() == "Linux" and store.backend_name != FileRefreshTokenStore.backend_name:
        _log_file_fallback(reason)
    else:
        _log_memory_fallback(reason)


def _migrate_legacy_refresh_token(store: RefreshTokenStore) -> Optional[str]:
    """One-time migration from the debug-bundle-scoped credential key.

    Before the bundle id was forwarded to the backend, official builds stored
    their refresh token under the debug bundle id. On the first launch of a
    fixed build the current-key lookup misses; recover the token from the
    legacy key, re-save it under the current key, and delete the legacy entry.
    """
    if get_bundle_id() == BUNDLE_ID_DEBUG:
        return None
    getter = getattr(store, "get_legacy_refresh_token", None)
    if getter is None:
        return None
    try:
        token = getter()
        if not token:
            return None
        store.set_refresh_token(token)
        try:
            store.clear_legacy_refresh_token()
        except SecureTokenStorageUnavailable:
            pass
        log.info("migrated cloud refresh token from legacy credential key", backend=store.backend_name)
        return token
    except SecureTokenStorageUnavailable as e:
        _log_store_failure_for_fallback(store, str(e))
        return None


def _get_refresh_token() -> Optional[str]:
    """Load refresh token from secure storage, fallback file, or memory."""
    store = _get_token_store()
    if store is not None:
        try:
            token = store.get_refresh_token()
            if token:
                return token
        except SecureTokenStorageUnavailable as e:
            _log_store_failure_for_fallback(store, str(e))
        else:
            token = _migrate_legacy_refresh_token(store)
            if token:
                return token

    fallback = _get_file_fallback_store()
    if fallback is not None:
        try:
            token = fallback.get_refresh_token()
            if token:
                return token
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
    return _memory_refresh_token


def _set_refresh_token(token: str) -> None:
    """Persist refresh token through platform storage or fallback storage."""
    global _memory_refresh_token
    store = _get_token_store()
    if store is not None:
        try:
            store.set_refresh_token(token)
            fallback = _get_file_fallback_store()
            if fallback is not None and fallback.backend_name != store.backend_name:
                fallback.clear_refresh_token()
            _memory_refresh_token = None
            log.debug("saved cloud refresh token", backend=store.backend_name)
            return
        except SecureTokenStorageUnavailable as e:
            _log_store_failure_for_fallback(store, str(e))

    fallback = _get_file_fallback_store()
    if fallback is not None:
        try:
            fallback.set_refresh_token(token)
            _memory_refresh_token = None
            log.warning("saved cloud refresh token using fallback file", backend=fallback.backend_name)
            return
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))

    _memory_refresh_token = token
    _log_memory_fallback("using process memory for refresh token")


def _clear_refresh_token() -> None:
    """Clear refresh token from secure storage, fallback storage, and memory."""
    global _memory_refresh_token
    store = _get_token_store()
    if store is not None:
        try:
            store.clear_refresh_token()
            # Also clear the legacy debug-scoped key so a later launch cannot
            # resurrect a signed-out session via the migration path.
            clear_legacy = getattr(store, "clear_legacy_refresh_token", None)
            if clear_legacy is not None and get_bundle_id() != BUNDLE_ID_DEBUG:
                clear_legacy()
            log.debug("cleared cloud refresh token", backend=store.backend_name)
        except SecureTokenStorageUnavailable as e:
            _log_memory_fallback(str(e))
    fallback = _get_file_fallback_store()
    if fallback is not None:
        try:
            fallback.clear_refresh_token()
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


class SecretTokenStore:
    """Generic single-secret store over the platform credential backends.

    Same cascade the Stimma Cloud helpers use — OS credential store, then a
    0600 file on Linux, then process memory — but keyed by an arbitrary
    ``CredentialKey`` and without the cloud-specific legacy migration. Used
    for the ChatGPT-plan OAuth refresh token.
    """

    def __init__(self, key: CredentialKey, *, description: str) -> None:
        self._key = key
        self._description = description
        self._memory_token: Optional[str] = None
        self._override: Optional[RefreshTokenStore] = None

    def set_override(self, store: Optional[RefreshTokenStore]) -> None:
        """Inject a store for tests."""
        self._override = store
        self._memory_token = None

    def _store(self) -> Optional[RefreshTokenStore]:
        if self._override is not None:
            return self._override
        return _get_token_store(self._key)

    def _fallback(self) -> Optional[RefreshTokenStore]:
        if self._override is not None:
            return None
        return _get_file_fallback_store(self._key)

    def get(self) -> Optional[str]:
        store = self._store()
        if store is not None:
            try:
                token = store.get_refresh_token()
                if token:
                    return token
            except SecureTokenStorageUnavailable as e:
                log.warning(
                    "secure storage read failed", secret=self._description, reason=str(e)
                )

        fallback = self._fallback()
        if fallback is not None and (store is None or fallback.backend_name != store.backend_name):
            try:
                token = fallback.get_refresh_token()
                if token:
                    return token
            except SecureTokenStorageUnavailable as e:
                log.warning(
                    "fallback storage read failed", secret=self._description, reason=str(e)
                )
        return self._memory_token

    def set(self, token: str) -> None:
        store = self._store()
        if store is not None:
            try:
                store.set_refresh_token(token)
                fallback = self._fallback()
                if fallback is not None and fallback.backend_name != store.backend_name:
                    try:
                        fallback.clear_refresh_token()
                    except SecureTokenStorageUnavailable:
                        pass
                self._memory_token = None
                log.debug("saved secret", secret=self._description, backend=store.backend_name)
                return
            except SecureTokenStorageUnavailable as e:
                log.warning(
                    "secure storage write failed", secret=self._description, reason=str(e)
                )

        fallback = self._fallback()
        if fallback is not None:
            try:
                fallback.set_refresh_token(token)
                self._memory_token = None
                log.warning(
                    "saved secret using fallback file",
                    secret=self._description,
                    backend=fallback.backend_name,
                )
                return
            except SecureTokenStorageUnavailable as e:
                log.warning(
                    "fallback storage write failed", secret=self._description, reason=str(e)
                )

        # Memory-only: the sign-in still works for this run, but will not
        # survive a restart. Callers surface this as "sign in again".
        self._memory_token = token
        log.warning("keeping secret in process memory only", secret=self._description)

    def clear(self) -> None:
        store = self._store()
        if store is not None:
            try:
                store.clear_refresh_token()
            except SecureTokenStorageUnavailable as e:
                log.warning(
                    "secure storage clear failed", secret=self._description, reason=str(e)
                )
        fallback = self._fallback()
        if fallback is not None:
            try:
                fallback.clear_refresh_token()
            except SecureTokenStorageUnavailable as e:
                log.warning(
                    "fallback storage clear failed", secret=self._description, reason=str(e)
                )
        self._memory_token = None

    @property
    def is_memory_only(self) -> bool:
        """True when the last write could only be kept in memory."""
        return self._memory_token is not None

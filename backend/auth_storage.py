"""
Persist Stimma Cloud auth state to disk.

Auth state is stored as a JSON file at: {app_data_dir}/cloud_auth.json
This is global (not per-profile) and survives backend restarts.
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Optional, TypedDict

import app_dirs
from core.logging import get_logger

log = get_logger(__name__)

# Auth state file name (stored in app data directory)
AUTH_STATE_FILENAME = "cloud_auth.json"


class AuthState(TypedDict, total=False):
    """Stored authentication state for Stimma Cloud."""
    user: dict           # {uid, email, displayName, photoURL}
    tier: str            # 'free', 'starter', 'pro', etc.
    refresh_token: str   # Firebase refresh token (long-lived)
    id_token: str        # Firebase ID token (cached, expires in 1hr)
    id_token_expiry: float  # Unix timestamp when id_token expires


def _get_auth_state_path() -> Path:
    """Get the path to the auth state file."""
    return app_dirs.get_data_dir() / AUTH_STATE_FILENAME


def save_auth_state(state: AuthState) -> None:
    """Save auth state to disk.

    Uses atomic writes (write to temp file, then rename) to avoid corruption.
    Sets restrictive file permissions (0600) since this contains tokens.
    """
    path = _get_auth_state_path()

    # Ensure directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then rename atomically
    fd, temp_path = tempfile.mkstemp(
        suffix='.json',
        dir=path.parent,
        prefix='cloud_auth_'
    )
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        os.chmod(temp_path, 0o600)

        # Atomic rename
        os.replace(temp_path, path)

        log.debug("saved auth state", path=str(path))
    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
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

        return data
    except json.JSONDecodeError as e:
        log.warning("auth state file is malformed JSON", path=str(path), error=str(e))
        return None
    except Exception as e:
        log.warning("failed to load auth state", path=str(path), error=str(e))
        return None


def clear_auth_state() -> None:
    """Delete auth state file (logout)."""
    path = _get_auth_state_path()

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

"""Serving-side authentication for multi-device.

Two layers, in the order a satellite hits them:

1. **Bootstrap** — the connecting install presents a live Firebase ID token.
   We verify it against Google's JWKS *locally* and require its subject to
   match our own account. Local verification is deliberate: a cloud
   round-trip here would violate the spec's rule that an established LAN
   session survives a transient cloud blip.

2. **Session** — on a successful bootstrap we mint an opaque session token
   for that client and persist it. Every later launch presents the session
   instead, so a satellite reaches its server without the local Python
   backend having to come up and mint an account token first.

Sessions are dropped when serving is turned off or the account signs out,
which is what makes "signed out = the feature doesn't exist" true rather
than aspirational.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

import app_dirs
from core.logging import get_logger

log = get_logger(__name__)

GOOGLE_JWKS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
FIREBASE_PROJECT_ID = "stimma-13a84"

SESSIONS_FILENAME = "multi_device_sessions.json"

# Keys rotate roughly daily; Google's own cache-control is ~6h. We keep the
# last good set indefinitely as a fallback so a cloud/network blip cannot
# break an already-trusted LAN link.
_JWKS_TTL_S = 6 * 3600
_jwks_cache: dict[str, str] = {}
_jwks_fetched_at: float = 0.0


class AuthError(Exception):
    """Any failure to authenticate a connecting client."""


def _b64url_decode(segment: str) -> bytes:
    padding_needed = -len(segment) % 4
    return base64.urlsafe_b64decode(segment + "=" * padding_needed)


async def _fetch_jwks(force: bool = False) -> dict[str, str]:
    global _jwks_cache, _jwks_fetched_at

    fresh = (time.time() - _jwks_fetched_at) < _JWKS_TTL_S
    if _jwks_cache and fresh and not force:
        return _jwks_cache

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(GOOGLE_JWKS_URL)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_fetched_at = time.time()
    except Exception as exc:
        # Serve the stale set rather than failing: an expired cache is a much
        # smaller problem than refusing a legitimate device because Google
        # was briefly unreachable.
        if _jwks_cache:
            log.warning("multi-device: JWKS refresh failed, using cached keys", error=str(exc))
            return _jwks_cache
        raise AuthError(f"cannot fetch signing keys: {exc}") from exc

    return _jwks_cache


async def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token locally and return its claims.

    Mirrors the checks the cloud's own middleware makes: RS256, correct
    issuer and audience for our Firebase project, unexpired, and a signature
    from one of Google's current public keys.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("malformed token")

    try:
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except Exception as exc:
        raise AuthError("undecodable token") from exc

    if header.get("alg") != "RS256":
        raise AuthError("unexpected signing algorithm")
    kid = header.get("kid")
    if not kid:
        raise AuthError("token has no key id")

    keys = await _fetch_jwks()
    cert_pem = keys.get(kid)
    if not cert_pem:
        # Unknown kid usually means rotation since our last fetch.
        keys = await _fetch_jwks(force=True)
        cert_pem = keys.get(kid)
    if not cert_pem:
        raise AuthError("unknown signing key")

    public_key = load_pem_x509_certificate(cert_pem.encode()).public_key()
    signed = f"{parts[0]}.{parts[1]}".encode()
    try:
        public_key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise AuthError("bad signature") from exc

    now = time.time()
    if claims.get("exp", 0) <= now:
        raise AuthError("token expired")
    if claims.get("iat", 0) > now + 300:
        raise AuthError("token issued in the future")
    if claims.get("aud") != FIREBASE_PROJECT_ID:
        raise AuthError("wrong audience")
    if claims.get("iss") != f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}":
        raise AuthError("wrong issuer")
    if not claims.get("sub"):
        raise AuthError("token has no subject")

    return claims


def own_account_uid() -> Optional[str]:
    """The Firebase uid this install is signed in as, from its own ID token.

    Read from our own cached token rather than the network, so the identity
    check keeps working while the cloud is unreachable. No signature check:
    it is our own token, obtained over TLS from Firebase.
    """
    from auth_storage import load_auth_state

    state = load_auth_state()
    if not state:
        return None
    token = state.get("id_token")
    if not token:
        return None
    try:
        claims = json.loads(_b64url_decode(token.split(".")[1]))
        return claims.get("sub")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sessions


def _sessions_path() -> Path:
    return app_dirs.get_data_dir() / SESSIONS_FILENAME


def _hash_session(token: str) -> str:
    """Only the hash is stored, so a leaked file is not a set of live keys."""
    return hashlib.sha256(token.encode()).hexdigest()


def _load_sessions() -> dict:
    try:
        with open(_sessions_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_sessions(sessions: dict) -> None:
    path = _sessions_path()
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(sessions, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception as exc:
        log.warning("multi-device: failed to persist sessions", error=str(exc))


def issue_session(client_device_id: str, account_uid: str) -> str:
    """Mint and persist a session token for a bootstrapped client."""
    token = secrets.token_urlsafe(32)
    sessions = _load_sessions()
    sessions[_hash_session(token)] = {
        "client_device_id": client_device_id,
        "account_uid": account_uid,
        "created_at": time.time(),
    }
    _save_sessions(sessions)
    log.info("multi-device: issued session", client_device_id=client_device_id)
    return token


def verify_session(token: str) -> Optional[dict]:
    """Return the session record for a token, or None."""
    if not token:
        return None
    record = _load_sessions().get(_hash_session(token))
    if not record:
        return None
    # A session outlives cloud outages but not a change of account.
    current = own_account_uid()
    if current and record.get("account_uid") != current:
        return None
    return record


def revoke_all_sessions() -> None:
    """Drop every session — called when serving stops or the account signs out."""
    _save_sessions({})
    log.info("multi-device: revoked all sessions")

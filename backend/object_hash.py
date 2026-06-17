"""
Salted object hashes for telemetry.

sha256(install-local random salt ‖ object id). The salt is generated once
per install, stored in config, and never transmitted — hashes are
irreversible, stable within an install (enabling per-object funnels), and
meaningless across installs.

Used for: flowHash, boardHash, chatHash, presetHash, projectHash,
chainHash, and user-provider toolRefs. Deliberately NOT used for media
items (per-asset rows would be a per-creation activity trace).
"""
import hashlib
import secrets
from typing import Optional

from core.logging import get_logger

log = get_logger(__name__)

_salt: Optional[str] = None


def _ensure_salt() -> str:
    """Return the per-install hash salt, generating and persisting if needed."""
    global _salt
    if _salt:
        return _salt

    try:
        from config import get_settings
        settings = get_settings()
        if settings.telemetry.hash_salt:
            _salt = settings.telemetry.hash_salt
            return _salt
    except Exception:
        pass

    new_salt = secrets.token_hex(32)
    _salt = new_salt

    try:
        import config_writer
        from config import get_settings
        section = get_settings().telemetry.model_dump()
        section["hash_salt"] = new_salt
        config_writer.patch_global_section("telemetry", section)
        log.info("telemetry hash salt generated")
    except Exception as e:
        log.info(f"failed to persist telemetry hash salt: {e}")

    return new_salt


def salted_hash(value) -> str:
    """Irreversible install-scoped hash of an object identifier.

    Returns the first 16 hex chars of sha256(salt || value) — plenty for
    per-install funnel joins, useless for reversal or cross-install joins.
    """
    salt = _ensure_salt()
    digest = hashlib.sha256(f"{salt}{value}".encode("utf-8")).hexdigest()
    return digest[:16]

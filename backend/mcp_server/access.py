"""MCP credentials are independent of REST sessions and UI PIN unlocks."""

from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from sqlalchemy import select
from config import get_settings
from database_registry import get_database_registry
from .models import McpClient


class McpError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def installation_secret() -> bytes:
    # Outside profile snapshots. Copying a profile DB never copies client authority.
    from app_dirs import get_data_dir

    path = Path(get_data_dir()) / "mcp-installation.key"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    return path.read_bytes()


def installation_id() -> str:
    return hashlib.sha256(installation_secret()).hexdigest()


@dataclass(frozen=True)
class Caller:
    profile_id: str
    client_id: str
    database_id: str
    stamp: str

    @property
    def key(self):
        return self.profile_id, self.client_id


@dataclass
class Unlock:
    stamp: str
    last_activity: float
    grant: str


class Access:
    def __init__(self):
        self.unlocks: dict[tuple[str, str], Unlock] = {}
        self.failures: dict[str, tuple[int, float]] = {}
        self.pin_locks: dict[str, asyncio.Lock] = {}

    def stamp(self, profile_id):
        profile = get_settings().get_profile(profile_id)
        if not profile or not profile.mcp_enabled:
            raise McpError("profile_disabled", "MCP is disabled for this profile.")
        db = get_database_registry().get_database(profile_id)
        # DB object identity also invalidates live grants on database replacement.
        stamp = hashlib.sha256(
            f"{db.db_guid}:{id(db)}:{profile.pin_hash}:{profile.mcp_enabled}".encode()
        ).hexdigest()
        return profile, db, stamp

    async def authenticate(self, profile_id: str, credential: str) -> Caller:
        profile, db, stamp = self.stamp(profile_id)
        digest = hashlib.sha256(credential.encode()).hexdigest()
        async with db.async_session_maker() as session:
            client = (
                await session.execute(
                    select(McpClient).where(
                        McpClient.credential_hash == digest,
                        McpClient.profile_id == profile_id,
                        McpClient.installation == installation_id(),
                        McpClient.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not client:
                raise McpError(
                    "unauthorized", "This assistant connection is not authorized."
                )
            return Caller(profile_id, client.id, db.db_guid, stamp)

    def status(self, caller):
        profile, _, stamp = self.stamp(caller.profile_id)
        unlock = self.unlocks.get(caller.key)
        timeout = max(1, profile.pin_idle_timeout_minutes) * 60
        unlocked = bool(
            unlock
            and unlock.stamp == stamp == caller.stamp
            and time.time() - unlock.last_activity < timeout
        )
        return {
            "locked": not unlocked,
            "requires_pin": bool(profile.pin_hash),
            "expires_at": unlock.last_activity + timeout if unlocked else None,
        }

    def require(self, caller, *, activity=True):
        if self.status(caller)["locked"]:
            raise McpError(
                "profile_locked",
                "Unlock this profile with access_open using the PIN supplied by the user.",
            )
        if activity:
            self.unlocks[caller.key].last_activity = time.time()
        return self.unlocks[caller.key]

    async def open(self, caller, pin=None):
        async with self.pin_locks.setdefault(caller.profile_id, asyncio.Lock()):
            profile, _, stamp = self.stamp(caller.profile_id)
            failures, retry_at = self.failures.get(caller.profile_id, (0, 0))
            if time.time() < retry_at:
                raise McpError(
                    "unlock_rate_limited",
                    "Wait before trying another user-supplied PIN.",
                )
            if profile.pin_hash:
                import bcrypt

                raw = (pin or "").encode()
                valid = len(raw) <= 72 and await asyncio.to_thread(
                    bcrypt.checkpw, raw, profile.pin_hash.encode()
                )
                if not valid:
                    failures += 1
                    self.failures[caller.profile_id] = (
                        failures,
                        time.time() + min(300, 2 ** min(failures, 9)),
                    )
                    raise McpError(
                        "invalid_pin",
                        "The PIN was not accepted. Ask the user; do not guess or retry it.",
                    )
            self.failures.pop(caller.profile_id, None)
            self.unlocks[caller.key] = Unlock(
                stamp, time.time(), secrets.token_urlsafe(18)
            )
            return self.status(caller)

    def lock(self, profile_id, client_id=None):
        if client_id is None:
            from .ui_context import clear

            clear(profile_id)
        for key in list(self.unlocks):
            if key[0] == profile_id and (client_id is None or key[1] == client_id):
                self.unlocks.pop(key, None)

    def ref(self, caller, kind, identifier):
        payload = json.dumps(
            [caller.profile_id, caller.database_id, kind, str(identifier)],
            separators=(",", ":"),
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(
            installation_secret(), payload, hashlib.sha256
        ).hexdigest()[:32]
        return f"{kind}:{encoded}.{signature}"

    def resolve(self, caller, reference, kind):
        try:
            prefix, encoded = reference.split(":", 1)
            encoded, signature = encoded.rsplit(".", 1)
            payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            expected = hmac.new(
                installation_secret(), payload, hashlib.sha256
            ).hexdigest()[:32]
            profile, database, actual_kind, identifier = json.loads(payload)
            if not hmac.compare_digest(signature, expected) or (
                profile,
                database,
                actual_kind,
                prefix,
            ) != (caller.profile_id, caller.database_id, kind, kind):
                raise ValueError()
            return identifier
        except (ValueError, TypeError, AttributeError):
            raise McpError(
                "not_found", "Reference is unavailable in this profile."
            ) from None


access = Access()

"""Keep marketplace stimpacks current from the server, without a client.

A headless install may go days without a page load, and the frontend's
once-per-load sync is not reliable there. This loop installs default packs
and applies marketplace updates for every profile the server may act for:
profiles without a PIN, and PIN profiles this process has seen unlocked.
Privacy lockdown turns it off entirely.
"""
from __future__ import annotations

import asyncio
import os

from core.logging import get_logger
from core.profile_context import ProfileScope
from privacy_lockdown import is_privacy_lockdown_enabled

log = get_logger(__name__)

STARTUP_DELAY_SECONDS = 60
SYNC_INTERVAL_SECONDS = 6 * 60 * 60

_locks: dict[str, asyncio.Lock] = {}


def profile_lock(profile_id: str) -> asyncio.Lock:
    """Serializes every marketplace install/update for one profile."""
    return _locks.setdefault(profile_id, asyncio.Lock())


def eligible_profile_ids() -> list[str]:
    """Profiles the server may sync on its own: PIN-less, or unlocked in this process."""
    from config import get_settings
    from core.middleware import has_verified_pin
    out = []
    for profile in get_settings().profiles or []:
        if not profile.pin_hash or has_verified_pin(
            profile.id, profile.pin_hash, profile.pin_idle_timeout_minutes
        ):
            out.append(profile.id)
    return out


async def sync_profile(profile_id: str) -> dict:
    """Auto-install default packs, then apply every available update. Never raises."""
    if is_privacy_lockdown_enabled():
        return {"installed": [], "updated": [], "changed": False}
    from routes import stimpack_marketplace as market
    installed: list[str] = []
    updated: list[str] = []
    async with profile_lock(profile_id):
        with ProfileScope(profile_id):
            try:
                installed = list((await market.auto_install_packs(profile_id)).get("installed") or [])
            except Exception as e:
                log.warning(f"Stimpack auto-install failed for profile {profile_id}: {e}")
            try:
                updates = (await market.check_updates()).get("updates") or []
            except Exception as e:
                log.warning(f"Stimpack update check failed for profile {profile_id}: {e}")
                updates = []
            for update in updates:
                name = update.get("name") if isinstance(update, dict) else None
                if not name:
                    continue
                try:
                    await market.update_pack(name, profile_id)
                    updated.append(name)
                except Exception as e:
                    log.warning(f"Stimpack update of '{name}' failed for profile {profile_id}: {e}")
    if installed or updated:
        log.info(f"Stimpacks synced for profile {profile_id}: installed {installed}, updated {updated}")
    return {"installed": installed, "updated": updated, "changed": bool(installed or updated)}


def _log_overrides(profile_id: str) -> None:
    try:
        from agent.v2.stimpacks import log_active_overrides
        log_active_overrides(profile_id)
    except Exception as e:  # pragma: no cover - defensive
        log.debug(f"override check failed for profile {profile_id}: {e}")


def _all_profile_ids() -> list[str]:
    from config import get_settings
    return [profile.id for profile in get_settings().profiles or []]


async def sync_loop() -> None:
    """Startup + periodic marketplace sync. Runs for the life of the server."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    # Local housekeeping for every profile: listing runs the legacy-install
    # migration, then one warning per profile names any active overrides.
    try:
        for profile_id in _all_profile_ids():
            await asyncio.to_thread(_log_overrides, profile_id)
    except Exception as e:
        log.warning(f"Stimpack override check failed: {e}")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            for profile_id in _all_profile_ids():
                # Recheck per profile: an earlier profile's sync can outlast another's unlock.
                if not is_privacy_lockdown_enabled() and profile_id in eligible_profile_ids():
                    await sync_profile(profile_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"Stimpack sync pass failed: {e}")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)

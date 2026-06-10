"""
Daily update check against our API.

``GET {cloud.base_url}/api/app/version?branch=&target=`` — the server
reads the manifest and touches install/MAU counters; the response tells
us whether a newer version exists on this install's branch.

Runs only in official builds on an update branch (alpha/beta/production);
dev/source builds never call it. Suppressed by ``DO_NOT_TRACK=1`` (D11)
and by the ``disable_update_check`` config setting. Result is logged —
installation itself stays with the existing in-app updater UI.
"""
import asyncio
import platform
from typing import Optional

import httpx

from core.logging import get_logger
from distribution import is_dnt, is_official

log = get_logger(__name__)

CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # daily
CHECK_TIMEOUT_SECONDS = 15

_task: Optional[asyncio.Task] = None


def _target() -> str:
    """Platform target string matching the release artifact naming."""
    from user_agent import get_arch
    system = platform.system()
    arch = get_arch()
    if system == "Darwin":
        return f"darwin-{'aarch64' if arch == 'arm64' else 'x86_64'}"
    if system == "Windows":
        return f"windows-{'aarch64' if arch == 'arm64' else 'x86_64'}"
    return f"linux-{'aarch64' if arch == 'arm64' else 'x86_64'}"


def should_check() -> bool:
    """Whether this build/install performs the daily update check."""
    if not is_official():
        return False
    if is_dnt():
        return False
    try:
        from config import get_settings
        if get_settings().disable_update_check:
            return False
    except Exception:
        pass
    from user_agent import get_app_branch
    return get_app_branch() in ("alpha", "beta", "production")


async def check_once() -> Optional[dict]:
    """One update check. Returns the manifest dict or None."""
    if not should_check():
        return None
    try:
        from config import get_settings
        from user_agent import ua_headers, get_app_branch, get_app_version

        base_url = get_settings().cloud.base_url.rstrip("/")
        url = f"{base_url}/api/app/version"
        params = {"branch": get_app_branch(), "target": _target()}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(CHECK_TIMEOUT_SECONDS)
        ) as client:
            response = await client.get(url, params=params, headers=ua_headers())
        if response.status_code != 200:
            log.debug(f"update check returned status {response.status_code}")
            return None
        manifest = response.json()
        latest = manifest.get("version")
        current = get_app_version()
        if latest and latest != current:
            log.info("update available", latest=latest, current=current)
        else:
            log.debug("no update available", current=current)
        return manifest
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.debug(f"update check failed: {e}")
        return None


async def _loop() -> None:
    # First check shortly after startup, then daily.
    await asyncio.sleep(60)
    while True:
        try:
            await check_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start() -> None:
    """Start the daily update-check task (no-op when gated off)."""
    global _task
    if _task is not None or not should_check():
        return
    _task = asyncio.create_task(_loop())
    log.info("update check started")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None

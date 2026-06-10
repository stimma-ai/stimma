"""
Session context for the desktop app sidecar.

The frontend is the source of truth for the session id (a plain UUID,
rotated on app start and after 30 minutes of inactivity — see
``apiConfig.js``). It propagates the value via the ``X-Stimma-Session-Id``
header on every sidecar API call. ``SessionIdMiddleware`` extracts the
header and updates the most-recently-seen value here.

This is single-user, single-frontend — no per-request scoping needed.
A simple module-level variable (with no lock; assignment is atomic in
CPython for str/None) is enough.
"""
import asyncio
from typing import Awaitable, Callable, List, Optional

from core.logging import get_logger

log = get_logger(__name__)

_current_session_id: Optional[str] = None
_change_callbacks: List[Callable[[Optional[str], str], Awaitable[None]]] = []


def get_session_id() -> Optional[str]:
    """Return the most-recently-seen ``$session_id``, or None if not yet known."""
    return _current_session_id


def on_session_change(callback: Callable[[Optional[str], str], Awaitable[None]]) -> None:
    """Register an async callback fired when the session_id changes.

    Callback receives ``(previous, current)``. ``previous`` is None on the
    first session ever seen.
    """
    _change_callbacks.append(callback)


async def update_session_id(session_id: str) -> None:
    """Update the current session_id. Fires change callbacks if it changed.

    Callbacks are scheduled on the running loop and not awaited so request
    handling stays fast.
    """
    global _current_session_id
    if not session_id or session_id == _current_session_id:
        return
    previous = _current_session_id
    _current_session_id = session_id
    log.debug("session_id changed", previous=previous, current=session_id)
    for cb in list(_change_callbacks):
        asyncio.create_task(_run_callback(cb, previous, session_id))


async def _run_callback(
    cb: Callable[[Optional[str], str], Awaitable[None]],
    previous: Optional[str],
    current: str,
) -> None:
    try:
        await cb(previous, current)
    except Exception:
        log.exception("session change callback failed")

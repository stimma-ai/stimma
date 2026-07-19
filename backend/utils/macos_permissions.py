"""Detection and surfacing of macOS TCC file-permission denials.

macOS gates access to ~/Desktop, ~/Documents, and ~/Downloads (and network
volumes) per-app. A denial surfaces as PermissionError/EPERM on open() even
though stat() succeeds — and the grant can silently go stale when the app
bundle is replaced by an update, with System Settings still showing it as
enabled. When we hit that signature, tell the connected UI so the user gets an
actionable notification instead of silent broken media.
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

from core.logging import get_logger

log = get_logger(__name__)

# One notification per interval is plenty — a browse view can hit hundreds of
# denied files in seconds.
_NOTIFY_INTERVAL_SECONDS = 60.0
_last_notify = 0.0
_notify_lock = threading.Lock()

_TCC_PROTECTED_FOLDERS = ("Desktop", "Documents", "Downloads")


def tcc_protected_folder(path) -> str | None:
    """Name of the TCC-protected home folder containing path, if any."""
    try:
        rel = Path(path).relative_to(Path.home())
    except ValueError:
        return None
    if rel.parts and rel.parts[0] in _TCC_PROTECTED_FOLDERS:
        return rel.parts[0]
    return None


def notify_macos_permission_denied(path) -> None:
    """Broadcast a macos_permission_denied event to the UI (rate-limited).

    Must be called from the event loop thread. No-op off macOS.
    """
    if sys.platform != "darwin":
        return
    global _last_notify
    with _notify_lock:
        now = time.monotonic()
        if now - _last_notify < _NOTIFY_INTERVAL_SECONDS:
            return
        _last_notify = now

    folder = tcc_protected_folder(path)
    log.warning(f"macOS denied read access to {path}; notifying clients")

    from utils.websocket import ws_manager
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(ws_manager.broadcast(
        "macos_permission_denied",
        {"path": str(path), "folder": folder},
        include_profile=False,
    ))

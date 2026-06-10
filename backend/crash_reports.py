"""
Crash reports (kind='crash' feedback) — official builds only.

Unhandled backend exceptions write a pending report to
``<data_dir>/crashes/pending/<ts>.json``: exception type + message, stack,
app version/branch/os, session id, the last 200 log lines captured at
crash time (scrubbed), and a stack hash for admin grouping. Exception
messages MAY contain content — which is exactly why this path is
consent-gated with a preview, unlike the content-free ``app_error``
telemetry event (telemetry.py), which stays untouched.

Consent (``feedback.crash_reports`` in config):
- ``ask``: if the app is alive the frontend is notified over the existing
  WS (``crash_reports_pending``) and shows the consent dialog; if the
  crash killed the session, the dialog shows on next launch (the frontend
  queries pending reports at startup). Multiple pending reports get ONE
  batched dialog; one decision covers the batch.
- ``always``: future reports auto-send fully silently (no toast — D12).
- ``never``: nothing is written; new reports are discarded.

Dev/source builds: never writes, never prompts (PRIVACY_PLAN §2.5).
"""
import asyncio
import hashlib
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import get_logger

log = get_logger(__name__)

LOG_TAIL_LINES = 200
MAX_PENDING_REPORTS = 20  # keep the pending dir bounded


def _crash_consent() -> str:
    try:
        from config import get_settings
        value = get_settings().feedback.crash_reports
        if value in ("ask", "always", "never"):
            return value
    except Exception:
        pass
    return "ask"


def get_pending_dir() -> Path:
    from app_dirs import get_data_dir
    return get_data_dir() / "crashes" / "pending"


def _stack_hash(exc: BaseException) -> str:
    """Same categorical fingerprint scheme as telemetry.app_error."""
    frames: List[str] = []
    try:
        for fs in traceback.extract_tb(exc.__traceback__):
            name = fs.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if name.endswith(".py"):
                name = name[:-3]
            frames.append(f"{name}:{fs.name}")
    except Exception:
        pass
    return hashlib.sha1(
        f"{type(exc).__name__}|{'|'.join(frames)}".encode("utf-8")
    ).hexdigest()[:16]


def record_crash(exc: BaseException) -> Optional[Path]:
    """Write a pending crash report. Returns the path, or None when gated.

    Official builds only; ``crash_reports: never`` suppresses + discards.
    Safe to call from any thread / exception hook (pure file IO).
    """
    from distribution import is_official
    if not is_official():
        return None
    if _crash_consent() == "never":
        return None

    try:
        from user_agent import get_app_version, get_app_branch, get_os
        from core.session_context import get_session_id
        from log_tail import tail_log_lines

        try:
            session_id = get_session_id()
        except Exception:
            session_id = None

        report: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "exceptionType": type(exc).__name__,
            "message": str(exc),
            "stack": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            "appVersion": get_app_version(),
            "appBranch": get_app_branch(),
            "os": get_os(),
            "sessionId": session_id,
            "stackHash": _stack_hash(exc),
            "logTail": tail_log_lines(LOG_TAIL_LINES),
        }

        pending = get_pending_dir()
        pending.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        path = pending / f"{ts}.json"
        suffix = 0
        while path.exists():
            suffix += 1
            path = pending / f"{ts}-{suffix}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _prune_pending(pending)

        _after_record()
        return path
    except Exception:
        # The crash reporter must never make a crash worse.
        return None


def _prune_pending(pending: Path) -> None:
    try:
        files = sorted(pending.glob("*.json"))
        for old in files[:-MAX_PENDING_REPORTS]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def _after_record() -> None:
    """If the app is alive: auto-send (consent 'always') or notify the UI."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # crash killed the session — next-launch path handles it
    if _crash_consent() == "always":
        loop.create_task(send_pending_silently())
    else:
        loop.create_task(_broadcast_pending())


async def _broadcast_pending() -> None:
    try:
        from utils.websocket import ws_manager
        await ws_manager.broadcast(
            "crash_reports_pending",
            {"count": len(list_pending())},
            include_profile=False,
        )
    except Exception:
        pass


def list_pending() -> List[Dict[str, Any]]:
    """Summaries of pending reports (newest last)."""
    pending = get_pending_dir()
    if not pending.exists():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(pending.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({
                "file": path.name,
                "ts": data.get("ts"),
                "errorType": data.get("exceptionType"),
                "message": data.get("message"),
                "stackHash": data.get("stackHash"),
            })
        except Exception:
            path.unlink(missing_ok=True)
    return out


def load_pending_full() -> List[Dict[str, Any]]:
    """Full pending reports (for the 'see what will be sent' preview)."""
    pending = get_pending_dir()
    if not pending.exists():
        return []
    out = []
    for path in sorted(pending.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["file"] = path.name
            out.append(data)
        except Exception:
            pass
    return out


def discard_pending() -> int:
    """Delete all pending reports ([Don't send])."""
    pending = get_pending_dir()
    if not pending.exists():
        return 0
    count = 0
    for path in pending.glob("*.json"):
        path.unlink(missing_ok=True)
        count += 1
    return count


async def send_pending(track: bool = True) -> int:
    """Send every pending report as a kind='crash' feedback row.

    Best-effort: each successfully sent report's file is deleted; on any
    failure the remainder is left pending for a later attempt. Returns the
    number sent.
    """
    from distribution import is_official
    if not is_official():
        return 0

    from feedback_client import submit_feedback, FeedbackSubmitError

    pending = get_pending_dir()
    if not pending.exists():
        return 0

    sent = 0
    for path in sorted(pending.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            path.unlink(missing_ok=True)
            continue

        message = f"{data.get('exceptionType', 'Error')}: {data.get('message', '')}"[:500]
        logs_text = "\n".join(data.get("logTail") or [])
        crash_body = dict(data)
        crash_body.pop("logTail", None)  # rides separately as logs.txt
        crash_body.pop("file", None)

        try:
            await submit_feedback(
                kind="crash",
                message=message,
                error_hash=data.get("stackHash"),
                crash=json.dumps(crash_body, indent=2).encode("utf-8"),
                logs=logs_text.encode("utf-8") if logs_text else None,
            )
            path.unlink(missing_ok=True)
            sent += 1
        except FeedbackSubmitError as e:
            log.info("crash report send failed", status=e.status_code)
            if e.status_code == 429:
                break  # daily cap — keep the rest pending
        except Exception:
            log.info("crash report send failed (network)")
            break

    if sent and track:
        try:
            from telemetry import get_telemetry_client
            get_telemetry_client().track(
                "feedback_submitted",
                {"kind": "crash", "hasLogs": True, "hasScreenshot": False,
                 "hasPackage": False},
                category="feedback",
            )
        except Exception:
            pass
    return sent


async def send_pending_silently() -> None:
    """Auto-send path for consent 'always' — fully silent (D12, no toast)."""
    try:
        await send_pending()
    except Exception:
        pass


def install_crash_hooks() -> None:
    """Chain crash recording onto the process exception hooks.

    Additive next to telemetry's app_error hooks — installed separately so
    crash reporting works even when telemetry is consent-off (it has its
    own consent). No-op in dev builds (record_crash gates internally, but
    we skip the hook entirely to keep source builds untouched).
    """
    from distribution import is_official
    if not is_official():
        return

    import sys
    import threading

    prev_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        try:
            if exc is not None:
                record_crash(exc)
        except Exception:
            pass
        prev_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    prev_thread_hook = threading.excepthook

    def _thread_excepthook(args):
        try:
            if args.exc_value is not None:
                record_crash(args.exc_value)
        except Exception:
            pass
        prev_thread_hook(args)

    threading.excepthook = _thread_excepthook


async def startup_check() -> None:
    """Handle reports left by a previous run.

    Consent 'always': send silently. 'ask': nothing to do here — the
    frontend queries pending reports on launch and shows the batched
    dialog. 'never': discard leftovers.
    """
    from distribution import is_official
    if not is_official():
        return
    consent = _crash_consent()
    if consent == "never":
        discard_pending()
        return
    if consent == "always" and list_pending():
        await send_pending_silently()

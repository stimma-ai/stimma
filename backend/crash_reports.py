"""
Crash reports (kind='crash' feedback) — official builds only.

Unhandled backend exceptions write a pending report to
``<data_dir>/crashes/pending/<ts>.json``: exception type + message, stack,
app version/branch/os, session id, the last 200 log lines captured at
crash time (scrubbed), and a stack hash for admin grouping. Exception
messages MAY contain content, so this path is consent-gated, unlike the
content-free ``app_error`` telemetry event (telemetry.py), which stays
untouched.

Consent (``feedback.crash_reports`` in config):
- ``ask``: if the app is alive the frontend is notified over the existing
  WS (``crash_reports_pending``) and shows the consent dialog; if the
  crash killed the session, the dialog shows on next launch (the frontend
  queries pending reports at startup). Multiple pending reports get ONE
  batched dialog; one decision covers the batch.
- ``always``: future reports send under the saved consent choice.
- ``never``: nothing is written; new reports are discarded.

Dev/source builds and Privacy Lockdown: never writes, never prompts.

Rate limiting (client-side, ahead of the server's per-install daily cap):
- Write-time dedupe: pending reports are keyed by stack hash. A crash
  whose hash already has a pending report bumps ``occurrences`` +
  ``lastSeenAt`` on the existing file instead of writing a new one — a
  crash STORM in one session costs one small file rewrite per hit, no
  new dialog prompts, no new send tasks.
- Pending cap: at most MAX_UNIQUE_PENDING unique reports. Beyond that,
  new unique crashes are dropped (one rate-limited warning, not one per
  crash); under consent 'always' the oldest pending report is evicted
  instead so the newest crash wins.
- Send throttle: at most MAX_SENDS_PER_DAY crash submissions per rolling
  24h, and at least MIN_AUTO_SEND_INTERVAL_SECONDS between auto-sends
  (consent 'always'). Throttled sends keep reports pending.
- Server backoff: a 429 from the feedback API stops all crash sends for
  SERVER_BACKOFF_SECONDS; reports stay pending.
State persists in ``<data_dir>/crashes/throttle.json``.
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
MAX_UNIQUE_PENDING = 10            # unique (per stack hash) pending reports
MAX_SENDS_PER_DAY = 3              # crash submissions per rolling 24h
SEND_WINDOW_SECONDS = 24 * 3600    # the rolling window above
MIN_AUTO_SEND_INTERVAL_SECONDS = 600   # between consent-'always' auto-sends
SERVER_BACKOFF_SECONDS = 24 * 3600     # after a 429 from the feedback API
DROP_WARN_INTERVAL_SECONDS = 3600      # rate limit for the drop warning itself

_last_drop_warning = 0.0  # module state — at most one drop warning per interval


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
    """Write or update a pending crash report. Returns the path, or None.

    Official builds only; ``crash_reports: never`` suppresses + discards.
    Safe to call from any thread / exception hook (pure file IO). A repeat
    crash (same stack hash) only bumps counters on the existing pending
    file — cheap under a crash loop, and never re-prompts the user.
    """
    from distribution import is_official
    from privacy_lockdown import is_privacy_lockdown_enabled
    if not is_official():
        return None
    if is_privacy_lockdown_enabled():
        return None
    if _crash_consent() == "never":
        return None

    try:
        stack_hash = _stack_hash(exc)
        pending = get_pending_dir()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Dedupe: same stack hash already pending → bump counters only.
        existing = _find_pending(pending, stack_hash)
        if existing is not None:
            try:
                data = json.loads(existing.read_text(encoding="utf-8"))
                data["occurrences"] = int(data.get("occurrences") or 1) + 1
                data["lastSeenAt"] = now_iso
                existing.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass
            return existing  # no _after_record: no dialog/send-task spam

        # Unique-report cap. Consent 'always' keeps the newest crash
        # (evict the oldest pending, silently); otherwise drop the new
        # crash with one rate-limited warning.
        existing_files = sorted(pending.glob("*.json")) if pending.exists() else []
        if len(existing_files) >= MAX_UNIQUE_PENDING:
            if _crash_consent() == "always":
                existing_files[0].unlink(missing_ok=True)
            else:
                _warn_dropped()
                return None

        from user_agent import get_app_version, get_app_branch, get_os
        from core.session_context import get_session_id
        from log_tail import tail_log_lines

        try:
            session_id = get_session_id()
        except Exception:
            session_id = None

        report: Dict[str, Any] = {
            "ts": now_iso,
            "exceptionType": type(exc).__name__,
            "message": str(exc),
            "stack": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            "appVersion": get_app_version(),
            "appBranch": get_app_branch(),
            "os": get_os(),
            "sessionId": session_id,
            "stackHash": stack_hash,
            "occurrences": 1,
            "firstSeenAt": now_iso,
            "lastSeenAt": now_iso,
            "logTail": tail_log_lines(LOG_TAIL_LINES),
        }

        pending.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        path = pending / f"{ts}-{stack_hash}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        _after_record()
        return path
    except Exception:
        # The crash reporter must never make a crash worse.
        return None


def _find_pending(pending: Path, stack_hash: str) -> Optional[Path]:
    """The pending file for a stack hash, if any (bounded by the cap)."""
    if not pending.exists():
        return None
    return next(iter(sorted(pending.glob(f"*-{stack_hash}.json"))), None)


def _warn_dropped() -> None:
    global _last_drop_warning
    now = time.time()
    if now - _last_drop_warning < DROP_WARN_INTERVAL_SECONDS:
        return
    _last_drop_warning = now
    log.warning(
        "crash report dropped: pending cap reached",
        cap=MAX_UNIQUE_PENDING,
    )


def _after_record() -> None:
    """If the app is alive: auto-send (consent 'always') or notify the UI.

    Only called for NEW unique reports — deduped repeats just bump
    counters, so a crash loop can't spam dialogs or send tasks.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # crash killed the session — next-launch path handles it
    if _crash_consent() == "always":
        loop.create_task(send_pending_silently())
    else:
        loop.create_task(_broadcast_pending())


# ── Send throttle state (persisted in <data_dir>/crashes/throttle.json) ──


def _throttle_path() -> Path:
    return get_pending_dir().parent / "throttle.json"


def _load_throttle() -> Dict[str, Any]:
    try:
        data = json.loads(_throttle_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_throttle(state: Dict[str, Any]) -> None:
    try:
        path = _throttle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def _send_budget(auto: bool) -> int:
    """How many crash submissions are allowed right now (0 = throttled)."""
    state = _load_throttle()
    now = time.time()
    if now < float(state.get("backoffUntil") or 0):
        return 0  # server said 429 — back off entirely
    if auto and now - float(state.get("lastAutoSendAt") or 0) < MIN_AUTO_SEND_INTERVAL_SECONDS:
        return 0
    recent = [t for t in (state.get("sendTimes") or []) if now - t < SEND_WINDOW_SECONDS]
    return max(0, MAX_SENDS_PER_DAY - len(recent))


def is_send_throttled(auto: bool = False) -> bool:
    """True when the client-side send throttle blocks crash sends."""
    return _send_budget(auto) <= 0


def _record_send(auto: bool) -> None:
    state = _load_throttle()
    now = time.time()
    times = [t for t in (state.get("sendTimes") or []) if now - t < SEND_WINDOW_SECONDS]
    times.append(now)
    state["sendTimes"] = times
    if auto:
        state["lastAutoSendAt"] = now
    _save_throttle(state)


def _record_server_backoff() -> None:
    state = _load_throttle()
    state["backoffUntil"] = time.time() + SERVER_BACKOFF_SECONDS
    _save_throttle(state)


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
                "occurrences": int(data.get("occurrences") or 1),
            })
        except Exception:
            path.unlink(missing_ok=True)
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


async def send_pending(track: bool = True, auto: bool = False) -> int:
    """Send pending reports as kind='crash' feedback rows, throttled.

    Best-effort: each successfully sent report's file is deleted; on any
    failure the remainder is left pending for a later attempt. The send
    throttle (rolling 24h budget, auto-send spacing, 429 backoff) applies
    to BOTH the consent-'always' auto path (``auto=True``) and manual
    dialog sends — throttled reports simply stay pending. Returns the
    number sent.
    """
    from distribution import is_official
    from privacy_lockdown import is_privacy_lockdown_enabled
    if not is_official() or is_privacy_lockdown_enabled():
        return 0

    budget = _send_budget(auto)
    if budget <= 0:
        return 0

    from feedback_client import submit_feedback, FeedbackSubmitError

    pending = get_pending_dir()
    if not pending.exists():
        return 0

    sent = 0
    for path in sorted(pending.glob("*.json")):
        if sent >= budget:
            break  # rolling-24h budget spent — the rest stays pending
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
            _record_send(auto)
        except FeedbackSubmitError as e:
            log.info("crash report send failed", status=e.status_code)
            if e.status_code == 429:
                # Server's daily cap — stop all crash sends for a while
                # and keep everything pending.
                _record_server_backoff()
                break
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
    """Auto-send path for consent 'always' — fully silent (D12, no toast).

    Throttled auto-sends (budget spent, <10 min since the last auto-send,
    or 429 backoff) silently leave reports pending.
    """
    try:
        await send_pending(auto=True)
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
    from privacy_lockdown import is_privacy_lockdown_enabled
    if not is_official() or is_privacy_lockdown_enabled():
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
    from privacy_lockdown import is_privacy_lockdown_enabled
    if not is_official() or is_privacy_lockdown_enabled():
        return
    consent = _crash_consent()
    if consent == "never":
        discard_pending()
        return
    if consent == "always" and list_pending():
        await send_pending_silently()

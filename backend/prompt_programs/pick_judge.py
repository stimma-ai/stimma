"""The pick judge Stimma ships: the pinned, versioned fix judge, downloaded ahead of use.

`fix_model: default` (the default) means this judge. The version is pinned per app
release in `model_manifests/pick-judge.json`, a verbatim copy of the published
manifest; its files live at `<models mirror>/pick-judge/<version>/` and are cached
under `<cache>/models/pick-judge/<version>/` (model_cache.ensure_bundle). Versions are
immutable, so a cached, verified version is used with no network at all.

The judge is how Fluent's draws fit together, so a draw that needs it waits for it
(`get()`), and the download starts at launch (`kick()`, from the app's startup) rather
than at the first draw. Waiting is bounded by progress, not by a total: a draw stops
waiting once the download has gone STALL_SECONDS without a byte (or a load from disk
LOAD_SECONDS), and then ships unjudged with a fix record that says why
(`skip_record()`). The judge can't be had when:

    offline / server error / hash mismatch   "unavailable": retried in the background,
                                              FIRST_RETRY_SECONDS doubling to RETRY_SECONDS,
                                              resuming the bytes it has
    the download stopped making progress      "stalled": the download carries on
    lockdown with nothing cached              "lockdown": nothing is fetched; retried only
                                              after RETRY_SECONDS
    unknown contract / won't load             "error" for this session (an app update fixes it)

Each change of state logs one line. A verified bundle on disk loads on the
background thread when kicked, or in the calling thread from `ready()` (well under a
second), so the first draw after a restart is judged. The loaded judge is unloaded
after IDLE_SECONDS without use and reloads from disk on the next draw.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import model_cache
from core.logging import get_logger
from model_lifetime import IdleModelHandle, idle_seconds

log = get_logger(__name__)

NAME = "pick-judge"
CONTRACTS = (1,)        # JUDGE_IO contract versions this code implements
RETRY_SECONDS = 600.0        # the longest pause between background retries after a failure
FIRST_RETRY_SECONDS = 30.0   # the first pause; doubles each failure up to RETRY_SECONDS
# A draw stops waiting once the download has gone this long without a byte. Bytes
# arrive a MiB at a time, so this is under ~70 kbit/s for two minutes: stalled, not
# slow. At 20 Mbit/s the whole judge takes about a minute; nothing bounds the total.
STALL_SECONDS = 120.0
LOAD_SECONDS = 60.0          # ... or a load from disk this long
POLL_SECONDS = 0.25
LOCAL_LOAD_WAIT = 5.0   # a draw waits this long at most for a load from disk already under way
IDLE_SECONDS = idle_seconds("STIMMA_PICK_JUDGE_IDLE_SECONDS", 900.0)
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "model_manifests" / f"{NAME}.json"


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = "idle"          # idle | downloading | loading | ready | unavailable | lockdown | error
        self.error = ""
        self.done = 0
        self.total = 0
        self.judge: Any = None
        self.threads = 0
        self.failed_at = 0.0
        self.last_fail = ("", "")
        self.progress_at = 0.0   # when the download last moved (or a phase began)
        self.worker: Optional[threading.Thread] = None
        self.handle: Optional[IdleModelHandle] = None
        self.stop = threading.Event()   # shutdown: the worker stops at its next byte
        self.wake = threading.Event()   # retry now, not at the end of the pause


_state = _State()
_load_lock = threading.Lock()   # one synchronous load from disk at a time
_manifest_cache: Dict[str, Any] = {}


def manifest(path: Optional[Path] = None) -> Dict[str, Any]:
    """The pinned manifest (cached). Raises model_cache.BundleError if it's malformed."""
    p = Path(path or MANIFEST_PATH)
    key = str(p)
    if key not in _manifest_cache:
        m = json.loads(p.read_text())
        if m.get("name") != NAME or not isinstance(m.get("version"), str):
            raise model_cache.BundleError(f"{p.name} isn't a {NAME} manifest")
        model_cache.bundle_files(m)
        _manifest_cache[key] = m
    return _manifest_cache[key]


def prefix(m: Dict[str, Any]) -> str:
    return f"{NAME}/{m['version']}"


def label() -> str:
    """`pick-judge/<version>` of the pinned judge."""
    try:
        return prefix(manifest())
    except Exception:
        return NAME


def model_file(m: Dict[str, Any]) -> Dict[str, Any]:
    """The manifest's entry for the ONNX graph (its `model`, else the one .onnx file)."""
    files = model_cache.bundle_files(m)
    want = m.get("model")
    hit = [f for f in files if f["path"] == want] if want else [f for f in files if f["path"].endswith(".onnx")]
    if len(hit) != 1:
        raise model_cache.BundleError("the manifest doesn't name one ONNX model")
    return hit[0]


def version_of(m: Dict[str, Any]) -> str:
    """What a draw's fix record calls this judge: pick-judge/<version>@<sha256 prefix>."""
    return f"{prefix(m)}@{model_file(m)['sha256'][:12]}"


def _unload() -> None:
    with _state.lock:
        if _state.status == "ready":
            _state.judge = None
            _state.status = "idle"


def _touch() -> None:
    h = _state.handle
    if h is not None:
        with h.use():
            pass  # restarts the idle timer; an in-flight pass keeps its own reference


def _check_contract(m: Dict[str, Any]) -> None:
    if m.get("contract") not in CONTRACTS:
        raise _Permanent(f"{prefix(m)} needs judge contract {m.get('contract')}, which this version of Stimma "
                         "doesn't implement")


def _load(m: Dict[str, Any], d: Path, threads: int) -> Any:
    from prompt_programs.fix import OnnxJudge
    _check_contract(m)
    try:
        return OnnxJudge(d, threads, manifest=m)
    except Exception as e:
        raise _Permanent(f"{prefix(m)} didn't load ({e})") from None


class _Permanent(RuntimeError):
    pass


def _fail(status: str, message: str) -> None:
    with _state.lock:
        again = _state.last_fail == (status, message)
        _state.last_fail = (status, message)
        _state.status, _state.error, _state.failed_at = status, message, time.monotonic()
        _state.judge = None
    (log.debug if again else log.warning)(
        f"[fluent-fix] the pick judge isn't available ({status}): {message}; draws ship unjudged")


def _attempt(m: Dict[str, Any], threads: int) -> str:
    """One download-verify-load. Returns the state it ends in."""
    from privacy_lockdown import PrivacyLockdownError

    def progress(done: int, total: int) -> None:
        if _state.stop.is_set():
            raise model_cache.Cancelled()
        with _state.lock:
            if done != _state.done:
                _state.progress_at = time.monotonic()
            _state.done, _state.total = done, total

    try:
        _check_contract(m)  # before downloading anything this code can't run
        d = model_cache.ensure_bundle(prefix(m), m, progress=progress)
        with _state.lock:
            _state.status, _state.progress_at = "loading", time.monotonic()
        judge = _load(m, d, threads)
    except model_cache.Cancelled:
        with _state.lock:
            _state.status = "idle"
        return "stopped"
    except PrivacyLockdownError as e:
        _fail("lockdown", str(e))
        return "lockdown"
    except _Permanent as e:
        _fail("error", str(e))
        return "error"
    except Exception as e:  # offline, a server error, a stall, a hash that never matched
        _fail("unavailable", f"{type(e).__name__}: {e}")
        return "unavailable"
    _ready(judge, m)
    try:
        model_cache.prune_bundles(NAME, m["version"])
    except Exception as e:
        log.debug(f"[fluent-fix] couldn't remove old pick judge versions: {e}")
    return "ready"


def _work(m: Dict[str, Any], threads: int) -> None:
    """The background worker: attempt, and after a transient failure keep retrying
    with a growing pause (cut short by kick(retry=True)) until it's ready, it fails
    for good, or the app shuts down. Each retry resumes the bytes already fetched."""
    delay = FIRST_RETRY_SECONDS
    while not _state.stop.is_set():
        if _attempt(m, threads) != "unavailable":
            return
        woke = _state.wake.wait(delay)
        _state.wake.clear()
        if _state.stop.is_set():
            return
        delay = FIRST_RETRY_SECONDS if woke else min(delay * 2, RETRY_SECONDS)
        with _state.lock:
            _state.status, _state.error, _state.progress_at = "downloading", "", time.monotonic()


def _ready(judge: Any, m: Dict[str, Any]) -> None:
    with _state.lock:
        _state.judge, _state.status, _state.error = judge, "ready", ""
        if _state.handle is None:
            _state.handle = IdleModelHandle("pick judge", IDLE_SECONDS, _unload)
    _touch()


def ready(threads: int = 0, *, start: bool = True) -> Any:
    """The loaded pinned judge, or None when it isn't ready (yet). Never waits on the
    network: a call starts the background download (`start`) when it isn't running
    (get() is the call that waits for it). A verified copy on disk loads here, in the
    caller's thread."""
    try:
        m = manifest()
    except Exception as e:
        with _state.lock:
            if _state.status != "error":
                _state.status, _state.error = "error", f"the pinned pick judge manifest is unreadable ({e})"
                log.warning(f"[fluent-fix] {_state.error}")
        return None
    with _state.lock:
        if _state.status == "ready" and _state.judge is not None and _state.threads == int(threads):
            judge = _state.judge
        else:
            judge = None
    if judge is not None:
        _touch()
        return judge
    with _state.lock:
        worker = _state.worker if _state.worker is not None and _state.worker.is_alive() else None
    if worker is not None and model_cache.bundle_is_present(prefix(m), m):
        worker.join(LOCAL_LOAD_WAIT)  # it's only loading the verified copy from disk
        with _state.lock:
            if _state.judge is not None and _state.threads == int(threads):
                judge = _state.judge
        if judge is not None:
            _touch()
            return judge
    with _state.lock:
        busy = _state.worker is not None and _state.worker.is_alive()
        if busy or _state.status == "error":
            return None
        if _state.status in ("unavailable", "lockdown") and time.monotonic() - _state.failed_at < RETRY_SECONDS:
            return None
    if model_cache.bundle_is_present(prefix(m), m):
        with _load_lock:
            with _state.lock:
                if _state.judge is not None and _state.threads == int(threads):
                    return _state.judge
            try:
                judge = _load(m, model_cache.bundle_path(prefix(m)), threads)
            except _Permanent as e:
                _fail("error", str(e))
                return None
            with _state.lock:
                _state.threads = int(threads)
            _ready(judge, m)
            return judge
    if start:
        kick(threads)
    return None


def kick(threads: int = 0, *, retry: bool = False) -> None:
    """Start the background download-and-load unless it's running, ready, failed for
    good, or (lockdown) failed within RETRY_SECONDS. `retry`: the user asked to try
    again, so a pause between retries ends now. Never blocks."""
    try:
        m = manifest()
    except Exception:
        return
    with _state.lock:
        if _state.worker is not None and _state.worker.is_alive():
            if retry:
                _state.wake.set()
            return
        if _state.status in ("ready", "error"):
            return
        if (_state.status in ("unavailable", "lockdown") and not retry
                and time.monotonic() - _state.failed_at < RETRY_SECONDS):
            return
        _state.status, _state.error, _state.threads = "downloading", "", int(threads)
        _state.done, _state.total = 0, sum(f["size"] for f in model_cache.bundle_files(m))
        _state.progress_at = time.monotonic()
        _state.worker = threading.Thread(target=_work, args=(m, int(threads)), name="pick-judge-download",
                                         daemon=True)
        _state.worker.start()


def _stalled_locked(now: float) -> bool:
    limit = STALL_SECONDS if _state.status == "downloading" else LOAD_SECONDS
    return now - _state.progress_at >= limit


def waiting() -> bool:
    """Whether a draw that needs the judge should keep waiting: the download (or the
    load from disk) is under way and has moved within STALL_SECONDS (LOAD_SECONDS)."""
    with _state.lock:
        if _state.status not in ("downloading", "loading"):
            return False
        if _state.worker is None or not _state.worker.is_alive():
            return False
        return not _stalled_locked(time.monotonic())


def get(threads: int = 0, *, cancelled: Optional[Callable[[], bool]] = None) -> Any:
    """The judge for a draw that needs it: ready() if it's loaded or on disk; else it
    starts the download if it isn't running and waits while it's making progress
    (waiting()). None when it can't be had (skip_record() says why) or `cancelled()`
    turns true. Blocking: call it off the event loop (fix.await_judge waits there)."""
    while True:
        judge = ready(threads)
        if judge is not None:
            return judge
        if not waiting() or (cancelled is not None and cancelled()):
            return None
        time.sleep(POLL_SECONDS)


def shutdown() -> None:
    """App shutdown: stop the download at its next byte (what it has stays on disk,
    to resume next launch) and end any pause between retries."""
    _state.stop.set()
    _state.wake.set()


def _reason_locked() -> Optional[str]:
    """Why a draw would ship unjudged right now, or None while it's worth waiting."""
    st = _state.status
    if st in ("unavailable", "lockdown", "error"):
        return st
    if st in ("downloading", "loading") and _stalled_locked(time.monotonic()):
        return "stalled"
    return None


def status() -> Dict[str, Any]:
    """off/idle/downloading/loading/ready/unavailable/lockdown/error, with the version
    and download progress, for the settings route and Tool View's wait. `waiting`:
    a draw would wait now; `unjudged`: why a draw would ship unjudged now."""
    with _state.lock:
        out: Dict[str, Any] = {"status": _state.status, "version": label()}
        if _state.status == "downloading" and _state.total:
            out.update(bytes_done=_state.done, bytes_total=_state.total,
                       percent=min(99, int(100 * _state.done / _state.total)))
        if _state.error:
            out["error"] = _state.error
        reason = _reason_locked()
        if reason:
            out["unjudged"] = reason
        if _state.judge is not None:
            out["version"] = _state.judge.version
            out["cut"] = _state.judge.cut
    out["waiting"] = waiting()
    return out


def skip_record() -> Dict[str, Any]:
    """The fix record of a draw shipped unjudged because the pinned judge can't be had."""
    with _state.lock:
        err = _state.error
        reason = _reason_locked() or "unavailable"
    rec: Dict[str, Any] = {"judge": label(), "skipped": reason}
    if err:
        rec["error"] = err
    elif reason == "stalled":
        rec["error"] = f"the download made no progress for {int(STALL_SECONDS)} seconds"
    return rec


def identity() -> str:
    """The judge part of a hot-draw signature: the version and whether it's ready, so
    draws made unjudged while it downloaded aren't served once it's ready."""
    with _state.lock:
        if _state.judge is not None:
            return f"{_state.judge.version}:ready"
        st = _state.status
    try:
        m = manifest()
        if st in ("idle", "ready") and model_cache.bundle_is_present(prefix(m), m):
            return f"{version_of(m)}:ready"  # on disk: the next draw loads it and is judged
    except Exception:
        pass
    return f"{label()}:{st}"


def wait(timeout: float) -> bool:
    """Wait for a running download-and-load (scripts and tests). True when ready."""
    w = _state.worker
    if w is not None:
        w.join(timeout)
    return _state.status == "ready"


def reset() -> None:
    """Forget the loaded judge and any failure (tests; a settings change)."""
    w = _state.worker
    _state.stop.set()
    _state.wake.set()
    if w is not None and w.is_alive():
        w.join(30)
    if _state.handle is not None:
        _state.handle.unload_now()
    _state.__init__()
    _manifest_cache.clear()


__all__ = ["CONTRACTS", "MANIFEST_PATH", "NAME", "get", "identity", "kick", "label", "manifest", "ready", "reset",
           "shutdown", "skip_record", "status", "version_of", "wait", "waiting"]

"""Download-on-first-run cache for ML model weights.

Model weights are NOT shipped inside the app bundle (large bundles hurt CDN
behavior and bloat installers). Instead every model downloads lazily on first
use into the user's cache directory and is reused forever after:

    <app cache dir>/models/<key>

Downloads come from Stimma's own R2 bucket (https://models.stimma.ai), which has
free, unmetered egress — a cold-start download costs nothing regardless of file
size. Writes are atomic (temp file + os.replace) so an interrupted or partial
download never leaves a corrupt model behind. Users may delete anything under the
cache dir at will; it simply re-downloads on next use.

This module is the single, consistent entry point for model fetching. New model
consumers should call `ensure_model(...)` rather than rolling their own download
or caching logic.

A model made of several files that must match each other (an ONNX graph and its
tokenizer) and that is versioned is a *bundle*: `ensure_bundle(prefix, manifest)`
fetches every file the manifest lists into `<cache>/models/<prefix>/`, checking
each one's size and sha256 as it streams, and writes a `.verified` marker last.
Once the marker matches, using the bundle touches no network at all.
"""
import contextlib
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from filelock import FileLock, Timeout as FileLockTimeout

import app_dirs
from core.logging import get_logger
from privacy_lockdown import raise_for_stimma_url_if_enabled

log = get_logger(__name__)

# Base URL of the R2 bucket that mirrors all model weights. Overridable for
# tests / local mirrors. Keys below are appended verbatim.
MODELS_BASE_URL = os.environ.get("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai").rstrip("/")

_USER_AGENT = "Stimma/1.0"
_CHUNK = 1 << 20  # 1 MiB
# Seconds a download may go without receiving a byte (connect included) before it
# fails. A stalled socket must not hold a model's lock for the rest of the process.
STALL_TIMEOUT = 60.0


def base_url() -> str:
    """The models mirror: STIMMA_MODELS_BASE_URL when set, else Stimma's bucket."""
    return (os.environ.get("STIMMA_MODELS_BASE_URL") or MODELS_BASE_URL).rstrip("/")

# Serialize concurrent ensure_model() calls per key so parallel ingestion
# workers don't download the same file twice or race on the temp file.
_key_locks: dict[str, threading.Lock] = {}
_key_locks_guard = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    with _key_locks_guard:
        return _key_locks.setdefault(key, threading.Lock())


def models_root() -> Path:
    """Return (and create) the root cache directory for model weights."""
    root = app_dirs.get_cache_dir() / "models"
    root.mkdir(parents=True, exist_ok=True)
    return root


def model_path(key: str) -> Path:
    """Return the local cache path for `key` (no download)."""
    return models_root() / key


def model_is_present(key: str) -> bool:
    """Return whether a complete, non-empty cached model artifact exists."""
    return _is_present(model_path(key))


def _is_present(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _adopt_legacy(dest: Path, legacy_paths: Sequence[Path]) -> bool:
    """Migrate a pre-existing copy from an old location into the cache.

    Lets installs that downloaded a model before this module existed (e.g. under
    ~/.insightface, ~/.cache/stimma, the onnx_clip package dir) keep using it
    instead of re-downloading. Returns True if a copy was adopted.
    """
    for old in legacy_paths:
        old = Path(old)
        if not _is_present(old) or old == dest:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(old, dest)  # atomic when same filesystem
        except OSError:
            shutil.copyfile(old, dest)  # cross-device fallback; leave original
        log.info(f"Adopted cached model from {old} -> {dest}")
        return True
    return False


class RangeIgnored(OSError):
    """A resumed download's server answered with the whole file instead of the rest."""


def _download(url: str, tmp: Path, on_chunk: Optional[Callable[[bytes], None]] = None, offset: int = 0) -> None:
    """Stream `url` into `tmp`, calling `on_chunk` with each chunk written. The
    single network seam for this module; the test suite stubs it out so tests can
    never download model weights. Fails after STALL_TIMEOUT seconds without data.
    `offset` > 0 resumes: it asks for the bytes from there on (HTTP Range) and appends
    them to `tmp`; a server that sends the whole file instead raises RangeIgnored
    before anything is written. Nothing is written until the server has answered."""
    headers = {"User-Agent": _USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=STALL_TIMEOUT) as resp:
        if offset and getattr(resp, "status", 200) != 206:
            raise RangeIgnored(f"{url} doesn't resume (HTTP {getattr(resp, 'status', '?')})")
        with open(tmp, "ab" if offset else "wb") as f:
            while chunk := resp.read(_CHUNK):
                f.write(chunk)
                if on_chunk is not None:
                    on_chunk(chunk)


def ensure_model(key: str, *, legacy_paths: Optional[Iterable[Path]] = None) -> Path:
    """Return a local path to model file `key`, downloading on first use.

    `key` is a path relative to both the cache root and the R2 bucket, e.g.
    "clip/clip_image_model_vitb32.onnx". Idempotent: returns immediately if the
    file is already cached (or adoptable from `legacy_paths`). The download is
    atomic — bytes land in a sibling ".part" file that is os.replace()d into
    place only after the full transfer succeeds.
    """
    dest = models_root() / key
    if _is_present(dest):
        return dest

    with _key_lock(key):
        # Another thread may have finished the download while we waited.
        if _is_present(dest):
            return dest

        if legacy_paths and _adopt_legacy(dest, [Path(p) for p in legacy_paths]):
            return dest

        url = f"{base_url()}/{key}"
        raise_for_stimma_url_if_enabled(url, "Stimma model downloads")

        dest.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp name so a concurrent download in another process can't
        # rename our partial file out from under us.
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.part")
        log.info(f"Downloading model {key} from {url}")
        try:
            _download(url, tmp)
            os.replace(tmp, dest)
        except BaseException:
            # Clean up the partial file on any failure, including KeyboardInterrupt.
            tmp.unlink(missing_ok=True)
            raise

    log.info(f"Model {key} cached at {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
    return dest


def ensure_models(keys: Iterable[str]) -> list[Path]:
    """Ensure several model files are present; returns their local paths."""
    return [ensure_model(k) for k in keys]


# --------------------------------------------------------------------------- bundles

VERIFIED = ".verified"
LOCAL_MANIFEST = "manifest.json"
BUNDLE_TRIES = 3
_RETRY_BASE_SECONDS = 2.0
_STALE_PART_SECONDS = 24 * 3600
_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

Progress = Callable[[int, int], None]  # (bytes in place, bytes in the bundle)


class BundleError(RuntimeError):
    """A bundle's manifest is malformed, or a file failed to arrive intact."""


class Cancelled(Exception):
    """Raised by a progress callback to stop ensure_bundle (shutdown). Never retried;
    the bytes already fetched stay for the next attempt."""


def _check_rel(path: str, what: str) -> str:
    if not isinstance(path, str) or not _SAFE_PATH.match(path) or ".." in path.split("/"):
        raise BundleError(f"{what} {path!r} isn't a plain relative path")
    return path


def bundle_files(manifest: Dict[str, Any]) -> list[Dict[str, Any]]:
    """The manifest's file list, validated: plain relative paths, sizes, sha256s."""
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list) or not files:
        raise BundleError("the manifest lists no files")
    out, seen = [], set()
    for f in files:
        if not isinstance(f, dict):
            raise BundleError("a manifest file entry isn't an object")
        path = _check_rel(f.get("path"), "file")
        size, sha = f.get("size"), f.get("sha256")
        if path in (VERIFIED, LOCAL_MANIFEST) or path in seen:
            raise BundleError(f"the manifest names {path} twice or a reserved name")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BundleError(f"{path} has no valid size")
        if not isinstance(sha, str) or not _SHA256.match(sha):
            raise BundleError(f"{path} has no valid sha256")
        seen.add(path)
        out.append({"path": path, "size": size, "sha256": sha})
    return out


def manifest_digest(manifest: Dict[str, Any]) -> str:
    """The sha256 of a manifest's canonical JSON: what `.verified` holds."""
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def bundle_path(prefix: str) -> Path:
    return models_root() / _check_rel(prefix, "bundle")


def bundle_is_present(prefix: str, manifest: Dict[str, Any]) -> bool:
    """Whether the bundle is cached and verified: its marker holds this manifest's
    digest and every file has its listed size. Never hashes the files (that was done
    once, as they arrived) and never touches the network."""
    d = bundle_path(prefix)
    try:
        if (d / VERIFIED).read_text().strip() != manifest_digest(manifest):
            return False
        return all((d / f["path"]).is_file() and (d / f["path"]).stat().st_size == f["size"]
                   for f in bundle_files(manifest))
    except (OSError, BundleError):
        return False


def _sweep_parts(d: Path) -> None:
    """Remove `.part` files a hard-killed download left behind (older than a day,
    so a concurrent download in another process keeps its own)."""
    now = time.time()
    for p in d.rglob("*.part"):
        try:
            if now - p.stat().st_mtime > _STALE_PART_SECONDS:
                p.unlink()
        except OSError:
            pass


PARTIAL = ".partial"


def _fetch_verified(url: str, dest: Path, size: int, sha: str, on_bytes: Callable[[int], None]) -> None:
    """Download one bundle file, hashing as it streams; os.replace it into place
    only when its size and sha256 match. The bytes collect in `<name>.partial`
    (the bundle's file lock makes that name safe across processes): a dropped
    connection keeps them, and the next attempt, or the next launch, asks the server
    for the rest only. Bytes that turn out wrong (too many, a bad hash) are deleted."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + PARTIAL)
    try:
        offset = part.stat().st_size if part.is_file() else 0
    except OSError:
        offset = 0
    if offset > size:
        part.unlink(missing_ok=True)
        offset = 0
    seen = offset
    if offset:
        on_bytes(offset)

    def chunk(b: bytes) -> None:
        nonlocal seen
        seen += len(b)
        if seen > size:
            raise BundleError(f"{dest.name} is larger than its manifest says ({size} bytes)")
        on_bytes(len(b))

    try:
        if offset < size:
            try:
                _download(url, part, chunk, offset=offset) if offset else _download(url, part, chunk)
            except RangeIgnored:
                on_bytes(-offset)
                part.unlink(missing_ok=True)
                seen = 0
                _download(url, part, chunk)
        got = part.stat().st_size
        if got != size:
            raise OSError(f"{dest.name} arrived as {got} of {size} bytes")
        if sha256_file(part) != sha:
            raise BundleError(f"{dest.name} failed its sha256 check")
        os.replace(part, dest)
    except BundleError:
        part.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _bundle_file_lock(d: Path, files: Sequence[Dict[str, Any]], total: int, progress: Optional[Progress]):
    """Hold `<bundle>.lock` so two processes sharing the cache (two sandboxes, a
    second server) never write the same `.partial` file. While another process holds
    it, progress reports the bytes it has on disk, once a second."""
    d.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(d.parent / f"{d.name}.lock"))
    while True:
        try:
            lock.acquire(timeout=1.0)
            break
        except FileLockTimeout:
            if progress:
                progress(_bytes_on_disk(d, files), total)
    try:
        yield
    finally:
        lock.release()


def _bytes_on_disk(d: Path, files: Sequence[Dict[str, Any]]) -> int:
    n = 0
    for f in files:
        for p in (d / f["path"], d / (f["path"] + PARTIAL)):
            try:
                n += min(p.stat().st_size, f["size"])
                break
            except OSError:
                continue
    return n


def ensure_bundle(prefix: str, manifest: Dict[str, Any], *, progress: Optional[Progress] = None,
                  tries: int = BUNDLE_TRIES) -> Path:
    """Return the local directory of bundle `prefix` (e.g. "pick-judge/2026-11-10.1"),
    downloading what's missing on first use. Blocking: call it off the event loop.

    Every file is fetched from `<base_url>/<prefix>/<path>`, hashed while it streams,
    and moved into place only when its size and sha256 match the manifest. A cached
    file of the wrong size (or, when the bundle isn't verified yet, the wrong hash) is
    fetched again. A file whose download broke off resumes where it stopped (HTTP
    Range), in this process or the next. When every file is in place the manifest is
    written next to them and `.verified` (the manifest's digest) last. A verified bundle returns at once
    with no network. Privacy lockdown blocks fetching from Stimma's hosts; a cached
    bundle still loads. Each file gets `tries` attempts with backoff; the error of the
    last one is raised (URLError, TimeoutError, BundleError, PrivacyLockdownError).
    `progress` may raise Cancelled to stop at once (no retry). Another process
    fetching the same bundle is waited for (a file lock), not duplicated."""
    files = bundle_files(manifest)
    d = bundle_path(prefix)
    total = sum(f["size"] for f in files)
    if bundle_is_present(prefix, manifest):
        if progress:
            progress(total, total)
        return d

    with _key_lock(f"bundle:{prefix}"), _bundle_file_lock(d, files, total, progress):
        if bundle_is_present(prefix, manifest):
            if progress:
                progress(total, total)
            return d
        d.mkdir(parents=True, exist_ok=True)
        _sweep_parts(d)
        (d / VERIFIED).unlink(missing_ok=True)
        done = 0
        todo = []
        for f in files:
            p = d / f["path"]
            try:
                ok = p.is_file() and p.stat().st_size == f["size"] and sha256_file(p) == f["sha256"]
            except OSError:
                ok = False
            if ok:
                done += f["size"]
            else:
                p.unlink(missing_ok=True)
                todo.append(f)
        if progress:
            progress(done, total)
        if todo:
            root = base_url()
            raise_for_stimma_url_if_enabled(root + "/", "Stimma model downloads")
            log.info(f"Downloading model bundle {prefix} from {root} ({len(todo)} files, "
                     f"{sum(f['size'] for f in todo) / 1024 / 1024:.1f} MB)")
        for f in todo:
            url = f"{root}/{prefix}/{f['path']}"
            for attempt in range(max(1, tries)):
                moved = 0

                def on_bytes(n: int) -> None:
                    nonlocal moved
                    moved += n
                    if progress:
                        progress(done + moved, total)

                try:
                    _fetch_verified(url, d / f["path"], f["size"], f["sha256"], on_bytes)
                    break
                except Cancelled:
                    raise
                except Exception as e:
                    if attempt + 1 >= max(1, tries):
                        raise
                    log.warning(f"Model bundle {prefix}: {f['path']} failed ({e}); retrying")
                    time.sleep(_RETRY_BASE_SECONDS * (2 ** attempt))
            done += f["size"]
            if progress:
                progress(done, total)
        tmp = d / f"{LOCAL_MANIFEST}.{os.getpid()}.{threading.get_ident()}.part"
        tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        os.replace(tmp, d / LOCAL_MANIFEST)
        tmp = d / f"{VERIFIED}.{os.getpid()}.{threading.get_ident()}.part"
        tmp.write_text(manifest_digest(manifest))
        os.replace(tmp, d / VERIFIED)
    log.info(f"Model bundle {prefix} verified at {d}")
    return d


def prune_bundles(parent: str, keep: str) -> list[str]:
    """Remove every version directory under `<cache>/models/<parent>/` except `keep`.
    Only names shaped like versions (YYYY-MM-DD.N) are touched. Caches are per channel
    and sandbox, so nothing else ever reads these. Returns the names removed."""
    root = models_root() / _check_rel(parent, "bundle")
    removed = []
    if not root.is_dir():
        return removed
    for child in root.iterdir():
        if child.name == keep or not child.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", child.name):
            continue
        with _key_lock(f"bundle:{parent}/{child.name}"):
            shutil.rmtree(child, ignore_errors=True)
        removed.append(child.name)
    if removed:
        log.info(f"Removed old model bundle versions under {parent}: {', '.join(sorted(removed))}")
    return removed

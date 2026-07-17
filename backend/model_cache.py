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
"""
import os
import shutil
import threading
import urllib.request
from pathlib import Path
from typing import Iterable, Optional, Sequence

import app_dirs
from core.logging import get_logger
from privacy_lockdown import raise_for_stimma_url_if_enabled

log = get_logger(__name__)

# Base URL of the R2 bucket that mirrors all model weights. Overridable for
# tests / local mirrors. Keys below are appended verbatim.
MODELS_BASE_URL = os.environ.get("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai").rstrip("/")

_USER_AGENT = "Stimma/1.0"
_CHUNK = 1 << 20  # 1 MiB

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

        url = f"{MODELS_BASE_URL}/{key}"
        raise_for_stimma_url_if_enabled(url, "Stimma model downloads")

        dest.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp name so a concurrent download in another process can't
        # rename our partial file out from under us.
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.part")
        log.info(f"Downloading model {key} from {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
                while chunk := resp.read(_CHUNK):
                    f.write(chunk)
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

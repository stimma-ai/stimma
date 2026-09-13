"""Run memoization.

A cache, not a packrat. Every cached run has an owner (its key), a retention
condition (within budget) and an eviction rule (LRU). Losing an entry only
costs a re-run; nothing here is the only copy of anything.

Layout: ``<cache_dir>/package-runs/<profile>/<key>/`` holding ``run.json``
(the files list) and the run's subtree. ``mtime`` of ``run.json`` is the LRU
clock.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import app_dirs
from core.logging import get_logger
from packages.recipes import WrittenFile

log = get_logger(__name__)

DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_BYTES = 4 * 1024 ** 3  # 4 GiB


@dataclass
class CacheStats:
    entries: int
    bytes: int
    root: str


def cache_root(profile_id: str) -> Path:
    return app_dirs.get_cache_dir() / "package-runs" / profile_id


def _entry_dir(profile_id: str, key: str) -> Path:
    return cache_root(profile_id) / key


def lookup(profile_id: str, key: str) -> Optional[list[WrittenFile]]:
    """Return the memoized file list when every file is present, else None."""
    entry = _entry_dir(profile_id, key)
    meta = entry / "run.json"
    if not meta.is_file():
        return None
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
        files = [WrittenFile(**f) for f in payload["files"]]
    except Exception:  # noqa: BLE001
        shutil.rmtree(entry, ignore_errors=True)
        return None
    for f in files:
        if not (entry / "tree" / f.path).is_file():
            shutil.rmtree(entry, ignore_errors=True)
            return None
    try:
        os.utime(meta, None)  # LRU touch
    except OSError:
        pass
    return files


def store(profile_id: str, key: str, tree_dir: Path, files: list[WrittenFile]) -> None:
    """Copy a finished run subtree into the cache (idempotent)."""
    entry = _entry_dir(profile_id, key)
    if (entry / "run.json").is_file():
        return
    tmp = entry.with_name(entry.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copytree(tree_dir, tmp / "tree", dirs_exist_ok=True)
    (tmp / "run.json").write_text(
        json.dumps({"files": [f.__dict__ for f in files], "stored_at": time.time()}),
        encoding="utf-8",
    )
    shutil.rmtree(entry, ignore_errors=True)
    os.replace(tmp, entry)


def materialize(profile_id: str, key: str, files: list[WrittenFile], dest_dir: Path) -> None:
    """Copy a cached run's files into ``dest_dir`` (the bundle's run root)."""
    tree = _entry_dir(profile_id, key) / "tree"
    for f in files:
        src = tree / f.path
        dst = Path(dest_dir) / f.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)


def _entry_size(entry: Path) -> int:
    total = 0
    for p in entry.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def stats(profile_id: str) -> CacheStats:
    root = cache_root(profile_id)
    if not root.is_dir():
        return CacheStats(entries=0, bytes=0, root=str(root))
    entries = [e for e in root.iterdir() if e.is_dir()]
    return CacheStats(entries=len(entries), bytes=sum(_entry_size(e) for e in entries), root=str(root))


def enforce_budget(
    profile_id: str,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> int:
    """Evict least-recently-used entries until within budget. Returns count evicted."""
    root = cache_root(profile_id)
    if not root.is_dir():
        return 0
    entries = []
    for e in root.iterdir():
        if not e.is_dir():
            continue
        meta = e / "run.json"
        if not meta.is_file():
            shutil.rmtree(e, ignore_errors=True)  # half-written or foreign
            continue
        try:
            entries.append((meta.stat().st_mtime, _entry_size(e), e))
        except OSError:
            shutil.rmtree(e, ignore_errors=True)
    entries.sort()  # oldest first
    total = sum(size for _, size, _ in entries)
    evicted = 0
    while entries and (len(entries) > max_entries or total > max_bytes):
        _, size, e = entries.pop(0)
        shutil.rmtree(e, ignore_errors=True)
        total -= size
        evicted += 1
    if evicted:
        log.info(f"package run cache: evicted {evicted} entries for profile {profile_id}")
    return evicted


def clear(profile_id: str) -> None:
    shutil.rmtree(cache_root(profile_id), ignore_errors=True)

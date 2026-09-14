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
DEFAULT_MAX_RENDER_BYTES = 512 * 1024 ** 2  # 512 MiB of cached vector renders


@dataclass
class CacheStats:
    entries: int
    bytes: int
    root: str


def cache_root(profile_id: str) -> Path:
    return app_dirs.get_cache_dir() / "package-runs" / profile_id


def _entry_dir(profile_id: str, key: str) -> Path:
    return cache_root(profile_id) / key


def lookup(profile_id: str, key: str) -> Optional[tuple[list[WrittenFile], Optional[bytes]]]:
    """Return the memoized (files, tile) when every file is present, else None."""
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
    tile_path = entry / "tile.png"
    tile = tile_path.read_bytes() if tile_path.is_file() else None
    return files, tile


def store(
    profile_id: str, key: str, tree_dir: Path, files: list[WrittenFile],
    *, tile_png: Optional[bytes] = None,
) -> None:
    """Copy a finished run subtree into the cache (idempotent)."""
    entry = _entry_dir(profile_id, key)
    if (entry / "run.json").is_file():
        return
    tmp = entry.with_name(entry.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    shutil.copytree(tree_dir, tmp / "tree", dirs_exist_ok=True)
    if tile_png:
        (tmp / "tile.png").write_bytes(tile_png)
    (tmp / "run.json").write_text(
        json.dumps({"files": [f.__dict__ for f in files], "stored_at": time.time()}),
        encoding="utf-8",
    )
    shutil.rmtree(entry, ignore_errors=True)
    os.replace(tmp, entry)


def materialize(profile_id: str, key: str, files: list[WrittenFile], dest_dir: Path, *, copy: bool = False) -> None:
    """Copy a cached run's files into ``dest_dir`` (the bundle's run root)."""
    tree = _entry_dir(profile_id, key) / "tree"
    for f in files:
        src = tree / f.path
        dst = Path(dest_dir) / f.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if copy:
            shutil.copy2(src, dst)
        else:
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
    shutil.rmtree(render_root(profile_id), ignore_errors=True)


# Vector renders -------------------------------------------------------------
#
# The same mark at the same size is the same pixels, and rendering goes out to
# the app's engine over a socket, so these are worth keeping. Content-addressed
# by (source hash, size): nothing here is the only copy of anything, and a miss
# costs one render.

def render_root(profile_id: str) -> Path:
    return app_dirs.get_cache_dir() / "package-renders" / profile_id


def _render_path(profile_id: str, source_hash: str, size: int) -> Path:
    return render_root(profile_id) / source_hash[:2] / source_hash / f"{int(size)}.png"


def render_lookup(profile_id: str, source_hash: str, size: int) -> Optional[bytes]:
    path = _render_path(profile_id, source_hash, size)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    try:
        os.utime(path, None)  # LRU touch
    except OSError:
        pass
    return data


def render_store(profile_id: str, source_hash: str, size: int, png: bytes) -> None:
    path = _render_path(profile_id, source_hash, size)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".png.tmp")
    try:
        tmp.write_bytes(png)
        os.replace(tmp, path)
    except OSError as exc:  # noqa: BLE001
        log.debug(f"could not cache vector render: {exc}")
        tmp.unlink(missing_ok=True)


def render_stats(profile_id: str) -> CacheStats:
    root = render_root(profile_id)
    if not root.is_dir():
        return CacheStats(entries=0, bytes=0, root=str(root))
    files = [p for p in root.rglob("*.png") if p.is_file()]
    total = 0
    for p in files:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return CacheStats(entries=len(files), bytes=total, root=str(root))


def enforce_render_budget(profile_id: str, *, max_bytes: int = DEFAULT_MAX_RENDER_BYTES) -> int:
    """Evict least-recently-used renders until within budget."""
    root = render_root(profile_id)
    if not root.is_dir():
        return 0
    entries = []
    for p in root.rglob("*.png"):
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, p))
    entries.sort()
    total = sum(size for _, size, _ in entries)
    evicted = 0
    while entries and total > max_bytes:
        _, size, p = entries.pop(0)
        try:
            p.unlink()
        except OSError:
            pass
        total -= size
        evicted += 1
    return evicted

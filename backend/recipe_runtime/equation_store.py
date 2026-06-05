"""Global equation store.

Stores computational results (tool outputs, LLM responses, code execution
results) shared across recipes when the computational identity matches.
HITL results are NOT stored here — they live in each recipe's state.db.

The equation store is durable, not a cache (non-deterministic results
cannot be faithfully recomputed). Schema matches RECIPES_TECH.md §"Equation
Store".

Storage layout:

    <data_dir>/equation_store/
    ├── equations.db    # sqlite: metadata + lookup index
    └── blobs/
        └── <hash_prefix>/<content_hash>   # large result blobs

The blob prefix is the first two hex characters of the content hash. This
"content-hash prefix bucketing" spreads blobs across 256 subdirectories,
which keeps directory sizes manageable under realistic load.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .paths import (
    get_equation_store_blobs_dir,
    get_equation_store_db_path,
    get_equation_store_dir,
)


_ENTRIES_DDL = """
CREATE TABLE IF NOT EXISTS equation_store_entries (
    store_key TEXT PRIMARY KEY,
    equation_type TEXT NOT NULL,
    result_small TEXT,
    result_media_ids TEXT,
    execution_duration_ms INTEGER,
    compute_duration_ms INTEGER,
    result_blob_hash TEXT,
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 1,
    size_bytes INTEGER NOT NULL DEFAULT 0
)
"""

_ENTRIES_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_equation_store_last_accessed "
    "ON equation_store_entries(last_accessed_at)"
)


def blob_path_for_hash(content_hash: str, blobs_root: Optional[Path] = None) -> Path:
    """Compute the on-disk path for a blob given its content hash.

    Uses the first two hex characters as a prefix bucket so ~256 directories
    absorb what would otherwise be a single huge flat directory.
    """
    if len(content_hash) < 3:
        raise ValueError(f"content_hash too short for prefix bucketing: {content_hash!r}")
    root = blobs_root if blobs_root is not None else get_equation_store_blobs_dir()
    return root / content_hash[:2] / content_hash


class EquationStore:
    """File-backed equation store. Thread-safe for concurrent writers."""

    def __init__(self, store_dir: Optional[Path] = None) -> None:
        self._store_dir = store_dir if store_dir is not None else get_equation_store_dir()
        self._db_path = self._store_dir / "equations.db"
        self._blobs_dir = self._store_dir / "blobs"
        self._lock = threading.Lock()
        self._initialized = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def blobs_dir(self) -> Path:
        return self._blobs_dir

    def initialize(self) -> None:
        """Create the store directory + DB schema + WAL mode. Idempotent."""
        with self._lock:
            if self._initialized:
                return
            self._store_dir.mkdir(parents=True, exist_ok=True)
            self._blobs_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            try:
                cur = conn.execute("PRAGMA journal_mode=WAL")
                mode = cur.fetchone()[0]
                if str(mode).lower() != "wal":
                    raise RuntimeError(
                        f"Failed to enable WAL on equation store: {mode!r}"
                    )
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute(_ENTRIES_DDL)
                cols = {
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(equation_store_entries)"
                    ).fetchall()
                }
                if cols and "result_media_ids" not in cols:
                    conn.execute(
                        "ALTER TABLE equation_store_entries ADD COLUMN result_media_ids TEXT"
                    )
                if cols and "execution_duration_ms" not in cols:
                    conn.execute(
                        "ALTER TABLE equation_store_entries ADD COLUMN execution_duration_ms INTEGER"
                    )
                if cols and "compute_duration_ms" not in cols:
                    conn.execute(
                        "ALTER TABLE equation_store_entries ADD COLUMN compute_duration_ms INTEGER"
                    )
                conn.execute(_ENTRIES_INDEX)
                conn.commit()
            finally:
                conn.close()
            self._initialized = True

    # ----- Blob I/O -----

    def _blob_path(self, content_hash: str) -> Path:
        return blob_path_for_hash(content_hash, self._blobs_dir)

    def write_blob(self, data: bytes) -> str:
        """Write `data` to a content-addressed blob. Returns its sha256 hex digest.

        Writing the same bytes twice is a no-op on the second call.
        """
        self.initialize()
        content_hash = hashlib.sha256(data).hexdigest()
        path = self._blob_path(content_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            # Atomic write: write to a temp sibling then rename.
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return content_hash

    def read_blob(self, content_hash: str) -> Optional[bytes]:
        path = self._blob_path(content_hash)
        if not path.exists():
            return None
        return path.read_bytes()

    # ----- Metadata I/O -----

    def insert(
        self,
        store_key: str,
        equation_type: str,
        *,
        result_small: Any = None,
        result_media_ids: Optional[list[int]] = None,
        execution_duration_ms: Optional[int] = None,
        compute_duration_ms: Optional[int] = None,
        result_blob_hash: Optional[str] = None,
        size_bytes: int = 0,
    ) -> None:
        """Insert a new entry. If the key already exists, this is a no-op."""
        self.initialize()
        now = datetime.utcnow().isoformat()
        small_json = json.dumps(result_small) if result_small is not None else None
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                "INSERT OR IGNORE INTO equation_store_entries "
                "(store_key, equation_type, result_small, result_media_ids, execution_duration_ms, "
                "compute_duration_ms, result_blob_hash, "
                "created_at, last_accessed_at, access_count, size_bytes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    store_key,
                    equation_type,
                    small_json,
                    json.dumps(result_media_ids) if result_media_ids is not None else None,
                    execution_duration_ms,
                    compute_duration_ms,
                    result_blob_hash,
                    now,
                    now,
                    1,
                    size_bytes,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def lookup(self, store_key: str) -> Optional[dict]:
        """Return the entry dict for `store_key`, or None if absent.

        Returns the raw row; call `touch()` separately to update
        last_accessed_at. RECIPES_TECH.md §"Store Lookup Flow" shows the
        runtime does this in two steps.
        """
        self.initialize()
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            row = conn.execute(
                "SELECT store_key, equation_type, result_small, result_media_ids, execution_duration_ms, "
                "compute_duration_ms, result_blob_hash, "
                "created_at, last_accessed_at, access_count, size_bytes "
                "FROM equation_store_entries WHERE store_key = ?",
                (store_key,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        entry = dict(row)
        if entry["result_small"] is not None:
            entry["result_small"] = json.loads(entry["result_small"])
        if entry["result_media_ids"] is not None:
            entry["result_media_ids"] = json.loads(entry["result_media_ids"])
        return entry

    def touch(self, store_key: str) -> bool:
        """Mark `store_key` as accessed. Returns True if a row was updated."""
        self.initialize()
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            cur = conn.execute(
                "UPDATE equation_store_entries "
                "SET last_accessed_at = ?, access_count = access_count + 1 "
                "WHERE store_key = ?",
                (now, store_key),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


_store_singleton: Optional[EquationStore] = None
_store_singleton_lock = threading.Lock()


def get_equation_store() -> EquationStore:
    """Return the process-wide EquationStore singleton.

    Tests that need isolation should construct their own EquationStore with an
    explicit `store_dir` rather than using this singleton.
    """
    global _store_singleton
    if _store_singleton is None:
        with _store_singleton_lock:
            if _store_singleton is None:
                store = EquationStore()
                store.initialize()
                _store_singleton = store
    return _store_singleton


def reset_equation_store_singleton() -> None:
    """Reset the process-wide singleton (for tests that rebind the data dir)."""
    global _store_singleton
    with _store_singleton_lock:
        _store_singleton = None

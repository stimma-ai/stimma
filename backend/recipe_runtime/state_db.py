"""Per-recipe SQLite database (state.db).

Each recipe has its own SQLite database at <data_dir>/recipes/<id>/state.db
containing equations, HITL tasks, and durable HITL results. This avoids
polluting the main database with potentially millions of equation rows and
makes forking efficient (the file can be copied — APFS clonefile when
available).

Schema matches RECIPES_TECH.md §"Data Model" and §"Indexes (per-recipe
database)" exactly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


# Table DDL statements, kept as module-level constants so tests can assert against them.
_EQUATIONS_DDL = """
CREATE TABLE IF NOT EXISTS equations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equation_key TEXT NOT NULL UNIQUE,
    equation_type TEXT NOT NULL,
    definition TEXT,
    phase_path TEXT,
    status TEXT NOT NULL,
    inputs_hash TEXT,
    result TEXT,
    result_media_ids TEXT,
    execution_duration_ms INTEGER,
    compute_duration_ms INTEGER,
    error TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    dependencies TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    invalidated_at TEXT
)
"""

_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equation_id INTEGER NOT NULL REFERENCES equations(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    instructions TEXT,
    payload TEXT,
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
)
"""

_HITL_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS hitl_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equation_key TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    resolution TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

# Indexes per RECIPES_TECH.md §"Indexes (per-recipe database)"
_INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_equations_status ON equations(status)",
    "CREATE INDEX IF NOT EXISTS ix_equations_key ON equations(equation_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_hitl_key_hash ON hitl_results(equation_key, inputs_hash)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status)",
]

REQUIRED_TABLES = {"equations", "tasks", "hitl_results"}
REQUIRED_INDEXES = {
    "ix_equations_status",
    "ix_equations_key",
    "ix_hitl_key_hash",
    "ix_tasks_status",
}

# Equation statuses that should be reset to 'pending' on fork or app restart,
# because their result is unknown — the recipe was interrupted mid-evaluation.
TRANSIENT_STATUSES = ("computing", "awaiting_input")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_equations_schema_compat(conn: sqlite3.Connection) -> None:
    """Apply narrow, in-place schema upgrades for existing state.db files."""
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(equations)").fetchall()
    }
    if columns and "definition" not in columns:
        conn.execute("ALTER TABLE equations ADD COLUMN definition TEXT")
    if columns and "execution_duration_ms" not in columns:
        conn.execute("ALTER TABLE equations ADD COLUMN execution_duration_ms INTEGER")
    if columns and "compute_duration_ms" not in columns:
        conn.execute("ALTER TABLE equations ADD COLUMN compute_duration_ms INTEGER")


def create_recipe_state_db(db_path: Path) -> None:
    """Create the per-recipe state.db at `db_path` with schema + WAL mode.

    Idempotent: creating over an existing state.db is a no-op for existing tables.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _connect(db_path)
    try:
        # WAL mode (durable — setting it once is enough for the database file).
        # Verify the PRAGMA actually took effect rather than trusting the declaration;
        # on some filesystems WAL falls back silently to the default journal mode.
        cur = conn.execute("PRAGMA journal_mode=WAL")
        mode = cur.fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError(
                f"Failed to enable WAL mode on {db_path}: PRAGMA journal_mode returned {mode!r}"
            )
        conn.execute("PRAGMA busy_timeout=30000")

        conn.execute(_EQUATIONS_DDL)
        conn.execute(_TASKS_DDL)
        conn.execute(_HITL_RESULTS_DDL)
        ensure_equations_schema_compat(conn)
        for stmt in _INDEX_STATEMENTS:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def verify_state_db_schema(db_path: Path) -> None:
    """Verify tables and indexes exist and WAL mode is on. Raises on mismatch."""
    conn = _connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() != "wal":
            raise RuntimeError(f"state.db at {db_path} is not in WAL mode (mode={mode!r})")

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing_tables = REQUIRED_TABLES - tables
        if missing_tables:
            raise RuntimeError(f"state.db at {db_path} missing tables: {missing_tables}")

        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        missing_indexes = REQUIRED_INDEXES - indexes
        if missing_indexes:
            raise RuntimeError(f"state.db at {db_path} missing indexes: {missing_indexes}")
    finally:
        conn.close()


def reset_transient_equation_states(db_path: Path) -> int:
    """Reset `computing` and `awaiting_input` equations back to `pending`.

    Used on fork (per RECIPES_TECH.md §Forking step 5) and on app restart to
    recover from interrupted evaluations. Returns the number of rows updated.
    """
    conn = _connect(db_path)
    try:
        placeholders = ",".join("?" for _ in TRANSIENT_STATUSES)
        cur = conn.execute(
            f"UPDATE equations SET status='pending' WHERE status IN ({placeholders})",
            TRANSIENT_STATUSES,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_pending_tasks(db_path: Path) -> int:
    """Remove copied pending tasks from a forked state.db."""
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM tasks WHERE status = 'pending'")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

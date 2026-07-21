"""Timeline project store: a per-project SQLite op log with a linear undo cursor.

A video project is a directory in the profile's managed area holding
``oplog.db`` (plus caches later). Every edit is an appended op row carrying
its precomputed inverse and author; the undo stack is the log with a cursor,
durable across restarts. Agent tool calls append as one labeled batch and
undo as one unit; sequencer gestures are single-op batches.

Linear undo: appending while the cursor is behind the head marks the redo
ops dead (``dead=1``) rather than deleting them — replay ignores them, but
the history stays inspectable and a history tree remains possible later
without a format change.
"""

import asyncio
import copy
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.logging import get_logger

from .ops import TimelineOpError, apply_op, compute_inverse, new_entry_id

log = get_logger(__name__)

OPLOG_FILENAME = "oplog.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    batch_label TEXT,
    author TEXT NOT NULL,
    op TEXT NOT NULL,
    args TEXT NOT NULL,
    inverse TEXT,
    dead INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ops_live ON ops(dead, seq);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class TimelineStoreError(ValueError):
    """The store rejected an operation (not an op-validation failure)."""


class TimelineProject:
    """One open timeline project. Thread-safe; use via get_project()."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None
        self._state: Optional[dict] = None
        self._cursor = 0

    # -- lifecycle ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self.project_dir.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(
                self.project_dir / OPLOG_FILENAME, check_same_thread=False
            )
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            self._db.commit()
        return self._db

    def _load(self) -> None:
        db = self._connect()
        row = db.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()
        self._cursor = int(row[0]) if row else 0
        self._state = None
        for seq, op, args in db.execute(
            "SELECT seq, op, args FROM ops WHERE dead=0 AND seq<=? ORDER BY seq",
            (self._cursor,),
        ):
            self._state = apply_op(self._state, op, json.loads(args))

    def _ensure_loaded(self) -> None:
        if self._db is None:
            self._load()

    def _set_cursor(self, value: int) -> None:
        self._cursor = value
        self._connect().execute(
            "INSERT INTO meta(key, value) VALUES('cursor', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(value),),
        )

    # -- reads ------------------------------------------------------------

    def state(self) -> Optional[dict]:
        with self._lock:
            self._ensure_loaded()
            return copy.deepcopy(self._state)

    def status(self) -> dict:
        """Cursor position and undo/redo batch availability, for the UI."""
        with self._lock:
            self._ensure_loaded()
            db = self._connect()
            undo_row = db.execute(
                "SELECT inverse IS NOT NULL FROM ops WHERE dead=0 AND seq<=? "
                "ORDER BY seq DESC LIMIT 1",
                (self._cursor,),
            ).fetchone()
            redo_row = db.execute(
                "SELECT 1 FROM ops WHERE dead=0 AND seq>? LIMIT 1", (self._cursor,)
            ).fetchone()
            return {
                "cursor": self._cursor,
                "can_undo": bool(undo_row and undo_row[0]),
                "can_redo": bool(redo_row),
            }

    def history(self, limit: int = 100) -> list[dict]:
        with self._lock:
            self._ensure_loaded()
            rows = self._connect().execute(
                "SELECT seq, batch_id, batch_label, author, op, args, dead, created_at "
                "FROM ops ORDER BY seq DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "seq": seq,
                "batch_id": batch_id,
                "batch_label": batch_label,
                "author": author,
                "op": op,
                "args": json.loads(args),
                "dead": bool(dead),
                "applied": (not dead) and seq <= self._cursor,
                "created_at": created_at,
            }
            for seq, batch_id, batch_label, author, op, args, dead, created_at in rows
        ]

    # -- writes -----------------------------------------------------------

    def append_batch(
        self,
        ops: list[tuple[str, dict]],
        *,
        author: str,
        label: Optional[str] = None,
    ) -> dict:
        """Validate, apply, and persist a batch of ops atomically.

        Entry ids are assigned here (recorded into args, so replay is
        deterministic). On op failure nothing is persisted or applied.
        Returns {state, applied: [{op, args}], batch_id}.
        """
        if not ops:
            raise TimelineStoreError("Empty op batch")
        with self._lock:
            self._ensure_loaded()
            db = self._connect()
            batch_id = uuid.uuid4().hex
            now = datetime.utcnow().isoformat()

            # Dry-run against a copy so a mid-batch failure leaves state intact.
            trial = copy.deepcopy(self._state)
            prepared: list[tuple[str, dict, Optional[tuple[str, dict]]]] = []
            for op, args in ops:
                args = dict(args or {})
                if op.startswith("_"):
                    raise TimelineOpError(f"{op} is internal to undo and cannot be appended")
                if op in ("add_clip", "add_slot") and not args.get("id"):
                    args["id"] = new_entry_id()
                inverse = compute_inverse(trial, op, args)
                trial = apply_op(trial, op, args)
                prepared.append((op, args, inverse))

            try:
                db.execute("BEGIN")
                db.execute("UPDATE ops SET dead=1 WHERE dead=0 AND seq>?", (self._cursor,))
                last_seq = self._cursor
                for op, args, inverse in prepared:
                    cur = db.execute(
                        "INSERT INTO ops(batch_id, batch_label, author, op, args, inverse, created_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            batch_id,
                            label,
                            author,
                            op,
                            json.dumps(args),
                            json.dumps(inverse) if inverse else None,
                            now,
                        ),
                    )
                    last_seq = cur.lastrowid
                self._set_cursor(last_seq)
                db.commit()
            except Exception:
                db.rollback()
                self._load()
                raise
            self._state = trial
            return {
                "state": copy.deepcopy(self._state),
                "applied": [{"op": op, "args": args} for op, args, _ in prepared],
                "batch_id": batch_id,
            }

    def undo(self) -> dict:
        """Undo the whole batch at the cursor. Returns status()+state."""
        with self._lock:
            self._ensure_loaded()
            db = self._connect()
            head = db.execute(
                "SELECT batch_id FROM ops WHERE dead=0 AND seq<=? ORDER BY seq DESC LIMIT 1",
                (self._cursor,),
            ).fetchone()
            if not head:
                raise TimelineStoreError("Nothing to undo")
            rows = db.execute(
                "SELECT seq, inverse FROM ops WHERE dead=0 AND seq<=? AND batch_id=? ORDER BY seq DESC",
                (self._cursor, head[0]),
            ).fetchall()
            if any(inverse is None for _, inverse in rows):
                raise TimelineStoreError("Nothing to undo")
            state = copy.deepcopy(self._state)
            for _, inverse in rows:
                op, args = json.loads(inverse)
                state = apply_op(state, op, args)
            prev = db.execute(
                "SELECT seq FROM ops WHERE dead=0 AND seq<? ORDER BY seq DESC LIMIT 1",
                (rows[-1][0],),
            ).fetchone()
            self._set_cursor(prev[0] if prev else 0)
            db.commit()
            self._state = state
        return self._result()

    def redo(self) -> dict:
        """Re-apply the next live batch above the cursor."""
        with self._lock:
            self._ensure_loaded()
            db = self._connect()
            nxt = db.execute(
                "SELECT batch_id FROM ops WHERE dead=0 AND seq>? ORDER BY seq LIMIT 1",
                (self._cursor,),
            ).fetchone()
            if not nxt:
                raise TimelineStoreError("Nothing to redo")
            rows = db.execute(
                "SELECT seq, op, args FROM ops WHERE dead=0 AND seq>? AND batch_id=? ORDER BY seq",
                (self._cursor, nxt[0]),
            ).fetchall()
            state = copy.deepcopy(self._state)
            for _, op, args in rows:
                state = apply_op(state, op, json.loads(args))
            self._set_cursor(rows[-1][0])
            db.commit()
            self._state = state
        return self._result()

    def _result(self) -> dict:
        result = self.status()
        result["state"] = self.state()
        return result


# -- registry ------------------------------------------------------------

_projects: dict[Path, TimelineProject] = {}
_projects_lock = threading.Lock()


def get_project(project_dir: Path) -> TimelineProject:
    """Return the shared TimelineProject for a directory (one per process)."""
    project_dir = Path(project_dir).resolve()
    with _projects_lock:
        project = _projects.get(project_dir)
        if project is None:
            project = _projects[project_dir] = TimelineProject(project_dir)
        return project


async def run_store(fn, *args, **kwargs):
    """Run a blocking store call off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)

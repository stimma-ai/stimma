"""Per-recipe state.db persistence for the equation graph.

The in-memory `EquationGraph` is the working copy during an active run. All
state transitions also write through to the per-recipe state.db so that
app restarts, debugging, and WebSocket listeners see consistent state.

Writes are small (one row per equation) and SQLite WAL mode is enabled by
Phase 1. We use short-lived connections instead of pooling to avoid tangling
with any sharing across the asyncio loop.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .graph import Equation, EquationGraph, EquationStatus, EquationType
from .state_db import ensure_equations_schema_compat


# ----- Low-level helpers ----------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        ensure_equations_schema_compat(conn)
        conn.commit()
    except sqlite3.OperationalError:
        # Brand-new files or unrelated tables may not exist yet; callers that
        # manage schema creation will create the base tables first.
        pass
    return conn


def _json_or_none(value: Any) -> Optional[str]:
    return None if value is None else json.dumps(value, default=str)


def _from_json(s: Optional[str]) -> Any:
    return None if s is None else json.loads(s)


# The definition dict may contain non-JSON-serializable things (NodeRefs in
# _dynamic bindings, Callables in foreach extra_kwargs, and the
# ``fn`` entry on code() equations that take a callable). We persist only
# the JSON-safe portion; the full definition is rebuilt on program
# re-parse. Dynamic bindings are reconstructed from the program at load
# time.
_NON_SERIALIZABLE_DEFINITION_KEYS = frozenset({"_dynamic", "extra_kwargs", "fn"})


def _definition_to_json(definition: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in definition.items():
        if k in _NON_SERIALIZABLE_DEFINITION_KEYS:
            continue
        try:
            json.dumps(v, default=str)
        except TypeError:
            continue
        out[k] = v
    return out


# ----- Equation row I/O -----------------------------------------------------


def insert_equation(db_path: Path, eq: Equation) -> int:
    now = datetime.utcnow().isoformat()
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO equations (equation_key, equation_type, phase_path, status, "
            "definition, inputs_hash, result, result_media_ids, execution_duration_ms, error, attempt, dependencies, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eq.key,
                eq.equation_type.value,
                _json_or_none(eq.phase_path),
                eq.status.value,
                _json_or_none(_definition_to_json(eq.definition or {})),
                eq.inputs_hash,
                _json_or_none(eq.result),
                _json_or_none(eq.result_media_ids),
                eq.execution_duration_ms,
                eq.error,
                eq.attempt,
                _json_or_none(eq.dependencies),
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def sync_equation_definitions(db_path: Path, equations: Iterable[Equation]) -> None:
    """Overwrite persisted DSL-declared columns from the in-memory graph.

    ``upsert_equations`` uses ``INSERT OR IGNORE``, so rows from a previous
    build keep their old structural fields even when the program has changed
    (e.g. a recipe input gained ``optional=True``, a ``foreach(...)`` moved
    to a different ``with phase(...)`` block, or a tool gained a new input).
    After ``build_initial_graph`` (and each ``try_reload_program``) this
    helper walks every equation and writes fresh definition, phase_path, and
    dependencies back — status/result/error stay untouched because those are
    authoritative in the DB (hydrated back into the in-memory graph a moment
    earlier).
    """
    rows = [
        (
            _json_or_none(_definition_to_json(eq.definition or {})),
            _json_or_none(eq.phase_path),
            _json_or_none(eq.dependencies),
            eq.key,
        )
        for eq in equations
    ]
    if not rows:
        return
    conn = _connect(db_path)
    try:
        conn.executemany(
            "UPDATE equations SET definition = ?, phase_path = ?, "
            "dependencies = ? WHERE equation_key = ?",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def upsert_equations(db_path: Path, equations: Iterable[Equation]) -> None:
    """Insert rows for equations, ignoring any that already exist by key.

    Used on initial graph persist. Status updates use `update_equation_status`
    to preserve the uniqueness check and narrow the write surface.
    """
    now = datetime.utcnow().isoformat()
    rows = [
        (
            eq.key,
            eq.equation_type.value,
            _json_or_none(eq.phase_path),
            eq.status.value,
            _json_or_none(_definition_to_json(eq.definition or {})),
            eq.inputs_hash,
            _json_or_none(eq.result),
            _json_or_none(eq.result_media_ids),
            eq.execution_duration_ms,
            eq.error,
            eq.attempt,
            _json_or_none(eq.dependencies),
            now,
        )
        for eq in equations
    ]
    if not rows:
        return
    conn = _connect(db_path)
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO equations (equation_key, equation_type, "
            "phase_path, status, definition, inputs_hash, result, result_media_ids, "
            "execution_duration_ms, error, attempt, dependencies, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


_SENTINEL = object()


def update_equation_status(
    db_path: Path,
    equation_key: str,
    status: EquationStatus,
    *,
    result: Any = _SENTINEL,
    result_media_ids: Any = _SENTINEL,
    execution_duration_ms: Any = _SENTINEL,
    compute_duration_ms: Any = _SENTINEL,
    error: Any = _SENTINEL,
    inputs_hash: Optional[str] = None,
    attempt: Optional[int] = None,
    dependencies: Optional[list[str]] = None,
    definition: Any = _SENTINEL,
    completed_at: Any = _SENTINEL,
    mark_completed: bool = False,
    mark_invalidated: bool = False,
) -> None:
    """Narrow update by equation_key. Pass sentinels to leave fields untouched."""
    fields: list[str] = ["status = ?"]
    params: list[Any] = [status.value]

    if result is not _SENTINEL:
        fields.append("result = ?")
        params.append(_json_or_none(result))
    if result_media_ids is not _SENTINEL:
        fields.append("result_media_ids = ?")
        params.append(_json_or_none(result_media_ids))
    if execution_duration_ms is not _SENTINEL:
        fields.append("execution_duration_ms = ?")
        params.append(execution_duration_ms)
    if compute_duration_ms is not _SENTINEL:
        fields.append("compute_duration_ms = ?")
        params.append(compute_duration_ms)
    if error is not _SENTINEL:
        fields.append("error = ?")
        params.append(error)
    if inputs_hash is not None:
        fields.append("inputs_hash = ?")
        params.append(inputs_hash)
    if attempt is not None:
        fields.append("attempt = ?")
        params.append(attempt)
    if dependencies is not None:
        fields.append("dependencies = ?")
        params.append(_json_or_none(dependencies))
    if definition is not _SENTINEL:
        fields.append("definition = ?")
        params.append(_json_or_none(_definition_to_json(definition or {})))
    if completed_at is not _SENTINEL:
        fields.append("completed_at = ?")
        params.append(completed_at)
    if mark_completed:
        fields.append("completed_at = ?")
        params.append(datetime.utcnow().isoformat())
    if mark_invalidated:
        fields.append("invalidated_at = ?")
        params.append(datetime.utcnow().isoformat())

    params.append(equation_key)
    conn = _connect(db_path)
    try:
        conn.execute(
            f"UPDATE equations SET {', '.join(fields)} WHERE equation_key = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def delete_equations_by_keys(db_path: Path, keys: Iterable[str]) -> int:
    keys = list(keys)
    if not keys:
        return 0
    placeholders = ",".join("?" for _ in keys)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            f"DELETE FROM equations WHERE equation_key IN ({placeholders})",
            keys,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def load_equation_keys(db_path: Path) -> set[str]:
    """Return the set of equation_keys currently in the state DB.

    Used at startup to detect equations orphaned by program edits between
    runtime instances — rows that exist in the DB but not in the freshly
    built graph (e.g. the agent renamed a primitive, swapped a foreach for
    an hitl.approve, etc.). Cheap: single column, no JSON parsing.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT equation_key FROM equations").fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def load_equation_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT equation_key, equation_type, phase_path, status, definition, "
            "inputs_hash, result, result_media_ids, execution_duration_ms, compute_duration_ms, "
            "error, attempt, dependencies, "
            "created_at, completed_at, invalidated_at FROM equations"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ----- HITL results ---------------------------------------------------------


def lookup_hitl_result(db_path: Path, equation_key: str, inputs_hash: str) -> Optional[Any]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT resolution FROM hitl_results WHERE equation_key = ? AND inputs_hash = ?",
            (equation_key, inputs_hash),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _from_json(row[0])


def insert_hitl_result(
    db_path: Path,
    equation_key: str,
    inputs_hash: str,
    resolution: Any,
) -> None:
    now = datetime.utcnow().isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO hitl_results "
            "(equation_key, inputs_hash, resolution, created_at) VALUES (?, ?, ?, ?)",
            (equation_key, inputs_hash, json.dumps(resolution, default=str), now),
        )
        conn.commit()
    finally:
        conn.close()


def delete_hitl_result(db_path: Path, equation_key: str, inputs_hash: str) -> None:
    """Remove the cached HITL resolution for (equation_key, inputs_hash).

    Called when a completed HITL is invalidated so the re-evaluation path
    actually re-asks the user instead of re-applying the old pick.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM hitl_results WHERE equation_key = ? AND inputs_hash = ?",
            (equation_key, inputs_hash),
        )
        conn.commit()
    finally:
        conn.close()


def lookup_hitl_by_inputs_hash(
    db_path: Path,
    inputs_hash: str,
) -> Optional[Any]:
    """Best-effort HITL recovery after a function rename (§I5).

    Returns any resolution stored against `inputs_hash`, regardless of
    equation_key. Because inputs_hash includes the resolved instructions
    plus candidates, a match is a strong signal.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT resolution FROM hitl_results WHERE inputs_hash = ? LIMIT 1",
            (inputs_hash,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _from_json(row[0])


# ----- Task rows (simple — Phase 4 will expand this) ------------------------


def insert_task(
    db_path: Path,
    equation_key: str,
    task_type: str,
    instructions: str,
    payload: Any,
) -> int:
    """Insert a task row for the given equation. Requires the equation row
    to already exist (FK cascade on delete).
    """
    now = datetime.utcnow().isoformat()
    conn = _connect(db_path)
    try:
        eq_row = conn.execute(
            "SELECT id FROM equations WHERE equation_key = ?",
            (equation_key,),
        ).fetchone()
        if eq_row is None:
            raise KeyError(
                f"insert_task: no equation row for key {equation_key!r}"
            )
        equation_id = eq_row[0]
        cur = conn.execute(
            "INSERT INTO tasks (equation_id, task_type, status, instructions, "
            "payload, created_at) VALUES (?, ?, 'pending', ?, ?, ?)",
            (equation_id, task_type, instructions, _json_or_none(payload), now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def resolve_task(db_path: Path, task_id: int, resolution: Any) -> Optional[str]:
    """Mark task resolved. Returns the equation_key of its equation, or None."""
    now = datetime.utcnow().isoformat()
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT e.equation_key FROM tasks t JOIN equations e ON e.id = t.equation_id "
            "WHERE t.id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        equation_key = row[0]
        conn.execute(
            "UPDATE tasks SET status='resolved', resolution=?, resolved_at=? WHERE id=?",
            (json.dumps(resolution, default=str), now, task_id),
        )
        conn.commit()
        return equation_key
    finally:
        conn.close()


_TASK_SELECT_COLUMNS = (
    "t.id AS task_id, "
    "t.task_type AS task_type, "
    "t.status AS status, "
    "t.instructions AS instructions, "
    "t.payload AS payload, "
    "t.resolution AS resolution, "
    "t.created_at AS created_at, "
    "t.resolved_at AS resolved_at, "
    "e.equation_key AS equation_key, "
    "e.equation_type AS equation_type, "
    "e.definition AS definition, "
    "e.status AS equation_status, "
    "e.phase_path AS phase_path, "
    "e.inputs_hash AS inputs_hash, "
    "e.attempt AS attempt, "
    "e.error AS error, "
    "e.dependencies AS dependencies"
)


def _task_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "task_type": row["task_type"],
        "status": row["status"],
        "instructions": row["instructions"],
        "payload": _from_json(row["payload"]),
        "resolution": _from_json(row["resolution"]),
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "equation_key": row["equation_key"],
        "equation_type": row["equation_type"],
        "definition": _from_json(row["definition"]),
        "equation_status": row["equation_status"],
        "phase_path": _from_json(row["phase_path"]) or [],
        "inputs_hash": row["inputs_hash"],
        "attempt": row["attempt"],
        "error": row["error"],
        "dependencies": _from_json(row["dependencies"]) or [],
    }


def list_tasks(
    db_path: Path,
    *,
    status: Optional[str] = "pending",
    task_types: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    """List tasks joined with their equation rows.

    Returns a list of dicts with task + equation fields. Missing state.db
    files or schema-less paths return an empty list rather than raising —
    cross-recipe listing fans out across many recipes and one broken file
    shouldn't take down the whole query.
    """
    if not db_path.exists():
        return []
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            f"SELECT {_TASK_SELECT_COLUMNS} FROM tasks t "
            "JOIN equations e ON e.id = t.equation_id"
        )
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("t.status = ?")
            params.append(status)
        task_type_list = list(task_types) if task_types else []
        if task_type_list:
            placeholders = ",".join("?" for _ in task_type_list)
            conditions.append(f"t.task_type IN ({placeholders})")
            params.extend(task_type_list)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY t.created_at ASC, t.id ASC"
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # e.g. tables not yet present — treat as "no tasks".
        return []
    finally:
        conn.close()
    return [_task_row_to_dict(r) for r in rows]


def get_latest_task_for_equation(
    db_path: Path,
    equation_key: str,
) -> Optional[dict[str, Any]]:
    """Return the newest task row for an equation, regardless of status."""
    if not db_path.exists():
        return None
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT {_TASK_SELECT_COLUMNS} FROM tasks t "
            "JOIN equations e ON e.id = t.equation_id "
            "WHERE e.equation_key = ? "
            "ORDER BY t.created_at DESC, t.id DESC "
            "LIMIT 1",
            (equation_key,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _task_row_to_dict(row)


def get_task(db_path: Path, task_id: int) -> Optional[dict[str, Any]]:
    if not db_path.exists():
        return None
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            f"SELECT {_TASK_SELECT_COLUMNS} FROM tasks t "
            "JOIN equations e ON e.id = t.equation_id WHERE t.id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    return _task_row_to_dict(row) if row else None


def update_task_payload(db_path: Path, task_id: int, payload: Any) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE tasks SET payload = ? WHERE id = ?",
            (_json_or_none(payload), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_pending_tasks_for_equation(
    db_path: Path, equation_key: str,
) -> list[dict[str, Any]]:
    """List pending task rows for an equation.

    Used by the reload path to collect task metadata before cancelling /
    cascade-deleting them so callers can broadcast per-task events.
    """
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT t.id, t.task_type, e.equation_key "
            "FROM tasks t JOIN equations e ON e.id = t.equation_id "
            "WHERE e.equation_key = ? AND t.status = 'pending'",
            (equation_key,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def cancel_pending_tasks_for_equation(db_path: Path, equation_key: str) -> list[int]:
    """Mark any pending tasks for this equation as 'cancelled'. Returns task ids."""
    now = datetime.utcnow().isoformat()
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT t.id FROM tasks t JOIN equations e ON e.id = t.equation_id "
            "WHERE e.equation_key = ? AND t.status = 'pending'",
            (equation_key,),
        ).fetchall()
        ids = [r[0] for r in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"UPDATE tasks SET status='cancelled', resolved_at=? WHERE id IN ({placeholders})",
                [now, *ids],
            )
            conn.commit()
        return ids
    finally:
        conn.close()


# ----- Hydration helpers ----------------------------------------------------


def hydrate_results_into_graph(db_path: Path, graph: EquationGraph) -> None:
    """Copy completed/failed/skipped results from state.db into `graph`.

    Used after rebuilding the graph from program.py on app restart: we want
    completed results to survive so downstream equations can skip
    re-evaluation (store hits still apply, but this is faster).
    """
    rows = load_equation_rows(db_path)
    for row in rows:
        key = row["equation_key"]
        eq = graph.try_get(key)
        if eq is None:
            continue
        db_status = EquationStatus(row["status"])
        if db_status in (
            EquationStatus.COMPLETED,
            EquationStatus.FAILED,
            EquationStatus.SKIPPED,
            EquationStatus.AWAITING_INPUT,
            EquationStatus.WAITING_FOR_TOOL,
        ):
            eq.status = db_status
            eq.result = _from_json(row["result"])
            eq.result_media_ids = _from_json(row["result_media_ids"]) or []
            eq.execution_duration_ms = row["execution_duration_ms"]
            eq.compute_duration_ms = row["compute_duration_ms"]
            eq.error = row["error"]
            eq.attempt = row["attempt"]
            eq.inputs_hash = row["inputs_hash"]


def reset_computing_to_pending(db_path: Path) -> int:
    """App-restart recovery (RECIPES_TECH §Implementation Notes).

    'computing' equations were interrupted mid-evaluation — their result is
    unknown, so reset to pending. Returns number of rows updated.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE equations SET status = 'pending' WHERE status = 'computing'"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def clear_recipe_state(db_path: Path) -> None:
    """Delete persisted equations, tasks, and HITL results for a recipe."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM equations")
        conn.execute("DELETE FROM hitl_results")
        conn.commit()
    finally:
        conn.close()

"""Developer-invoked repair of historical SQLite foreign-key debris.

This service is deliberately independent from migrations and startup. It only
repairs violations whose declared single-column action is unambiguous, and it
never touches files.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTECTED_DELETE_TABLES = {
    "asset",
    "assets",
    "assetrevision",
    "assetrevisions",
    "media",
    "mediaitem",
    "mediaitems",
    "revision",
    "revisions",
    "storageobject",
    "storageobjects",
}


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _protected_from_delete(table: str) -> bool:
    normalized = "".join(character for character in table.casefold() if character.isalnum())
    return normalized in PROTECTED_DELETE_TABLES or normalized.endswith("revisions")


@dataclass(frozen=True)
class _Constraint:
    child_table: str
    child_columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]
    on_delete: str
    composite: bool
    ambiguous: bool


def _foreign_keys(connection: sqlite3.Connection, child_table: str) -> dict[int, _Constraint]:
    rows = connection.execute(
        f"PRAGMA foreign_key_list({_quote_identifier(child_table)})"
    ).fetchall()
    by_id: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_id[int(row[0])].append(row)

    constraints: dict[int, _Constraint] = {}
    for constraint_id, parts in by_id.items():
        parts.sort(key=lambda row: int(row[1]))
        parent_table = str(parts[0][2])
        child_columns = tuple(str(row[3]) for row in parts if row[3] is not None)
        parent_columns = tuple(str(row[4]) for row in parts if row[4] is not None)
        on_delete_values = {str(row[6]).upper() for row in parts}
        constraints[constraint_id] = _Constraint(
            child_table=child_table,
            child_columns=child_columns,
            parent_table=parent_table,
            parent_columns=parent_columns,
            on_delete=next(iter(on_delete_values)) if len(on_delete_values) == 1 else "AMBIGUOUS",
            composite=len(parts) != 1,
            ambiguous=(
                len(on_delete_values) != 1
                or len(child_columns) != len(parts)
                or len(parent_columns) != len(parts)
            ),
        )
    return constraints


def _classification(constraint: _Constraint | None, rowid: int | None) -> tuple[bool, str | None, str]:
    if constraint is None or constraint.ambiguous or rowid is None:
        return False, None, "Constraint metadata or child row identity is ambiguous"
    if constraint.composite:
        return False, None, "Composite foreign keys are report only"
    if constraint.on_delete == "CASCADE":
        if _protected_from_delete(constraint.child_table):
            return False, None, "Protected durable records are never deleted"
        return True, "delete_child", "Delete the orphaned child row (declared CASCADE)"
    if constraint.on_delete == "SET NULL":
        return True, "set_null", "Clear the orphaned reference (declared SET NULL)"
    return False, None, f"Declared {constraint.on_delete} relationships are report only"


def _analyze_connection(connection: sqlite3.Connection) -> tuple[dict[str, Any], dict[tuple[Any, ...], list[int]]]:
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    metadata: dict[str, dict[int, _Constraint]] = {}
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    rowids: dict[tuple[Any, ...], list[int]] = defaultdict(list)

    for child_table, rowid, parent_table, constraint_id in violations:
        child_table = str(child_table)
        if child_table not in metadata:
            metadata[child_table] = _foreign_keys(connection, child_table)
        constraint = metadata[child_table].get(int(constraint_id))
        repairable, repair_action, reason = _classification(constraint, rowid)

        child_columns = constraint.child_columns if constraint else ()
        parent_columns = constraint.parent_columns if constraint else ()
        on_delete = constraint.on_delete if constraint else "UNKNOWN"
        actual_parent = constraint.parent_table if constraint else str(parent_table)
        key = (
            child_table,
            child_columns,
            actual_parent,
            parent_columns,
            on_delete,
            repairable,
            repair_action,
            reason,
        )
        if key not in grouped:
            grouped[key] = {
                "child_table": child_table,
                "child_columns": list(child_columns),
                "parent_table": actual_parent,
                "parent_columns": list(parent_columns),
                "on_delete": on_delete,
                "count": 0,
                "repairable": repairable,
                "repair_action": repair_action,
                "reason": reason,
            }
        grouped[key]["count"] += 1
        if rowid is not None:
            rowids[key].append(int(rowid))

    groups = sorted(
        grouped.values(),
        key=lambda group: (
            group["child_table"],
            group["child_columns"],
            group["parent_table"],
            group["parent_columns"],
        ),
    )
    repairable_count = sum(group["count"] for group in groups if group["repairable"])
    total_findings = len(violations)
    return {
        "total_findings": total_findings,
        "repairable_count": repairable_count,
        "report_only_count": total_findings - repairable_count,
        "groups": groups,
    }, rowids


def _open_read_only(db_path: str) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _analyze_database_sync(db_path: str) -> dict[str, Any]:
    connection = _open_read_only(db_path)
    try:
        analysis, _ = _analyze_connection(connection)
        return analysis
    finally:
        connection.close()


async def analyze_database(db_path: str) -> dict[str, Any]:
    """Run a read-only foreign-key analysis without blocking the event loop."""
    return await asyncio.to_thread(_analyze_database_sync, db_path)


def _cleanup_database_sync(db_path: str) -> dict[str, Any]:
    connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=30000")
    # Prevent repairing one relationship from cascading into other records.
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        before, rowids = _analyze_connection(connection)
        deleted_count = 0
        nullified_count = 0

        for key, ids in rowids.items():
            child_table, child_columns, _parent, _parent_columns, _action, repairable, repair_action, _reason = key
            if not repairable or not ids:
                continue
            placeholders = ", ".join("?" for _ in ids)
            if repair_action == "delete_child":
                cursor = connection.execute(
                    f"DELETE FROM {_quote_identifier(child_table)} WHERE rowid IN ({placeholders})",
                    ids,
                )
                deleted_count += cursor.rowcount
            elif repair_action == "set_null":
                child_column = child_columns[0]
                cursor = connection.execute(
                    f"UPDATE {_quote_identifier(child_table)} "
                    f"SET {_quote_identifier(child_column)} = NULL "
                    f"WHERE rowid IN ({placeholders})",
                    ids,
                )
                nullified_count += cursor.rowcount

        after, _ = _analyze_connection(connection)
        connection.commit()
        return {
            "before": before,
            "after": after,
            "repaired_count": deleted_count + nullified_count,
            "deleted_count": deleted_count,
            "nullified_count": nullified_count,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


async def cleanup_database(db_path: str) -> dict[str, Any]:
    """Repair safe violations in one all-or-nothing SQLite transaction."""
    return await asyncio.to_thread(_cleanup_database_sync, db_path)

"""One-off, exhaustive literal rewrite of persisted prompt history.

The command is intentionally schema-agnostic.  Prompt text has lived in plain
columns, JSON blobs, per-flow SQLite databases, and embedded image metadata over
Stimma's lifetime; discovering non-structural SQLite text cells is safer than
maintaining a prompt-column list which will eventually drift.  Identifier,
hash, and filesystem-locator columns are left to the dedicated media-identity
rewrite so a coincidental match cannot break a live path or foreign identity.

Dry-run is the default.  Apply mode must only be used while the Stimma backend
for the target sandbox is stopped.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import zlib
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import piexif
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table


SQLITE_HEADER = b"SQLite format 3\x00"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8"
HASH_FINGERPRINT_BYTES = re.compile(
    rb"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"
)
IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png"}
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
TEXT_SUFFIXES = {
    ".css", ".csv", ".html", ".ini", ".json", ".jsonl", ".log", ".md",
    ".py", ".toml", ".tsv", ".txt", ".xml", ".yaml", ".yml",
}
EXCLUDED_TEXT_DIRS = {"objects", "staging"}
STRUCTURAL_COLUMN_NAMES = {
    "id", "cache_path", "external_path", "file_format", "file_hash", "file_path",
    "folder_path", "locator", "mime_type", "object_key", "original_filename",
    "source_file_path", "storage_object_key", "thumbnail_paths",
}
STRUCTURAL_COLUMN_SUFFIXES = ("_hash", "_id", "_ids", "_key", "_path", "_slug")
PNG_TRAILING_DATA = b"__stimma_png_trailing_data__"
DEFAULT_SCAN_WORKERS = min(32, max(4, (os.cpu_count() or 4) + 4))


class RewriteError(RuntimeError):
    """A safety or verification failure."""


@dataclass(frozen=True)
class Rule:
    old: str
    new: str


class ReplacementPlan:
    """A non-cascading literal multi-replacement plan."""

    def __init__(self, rules: Sequence[Rule], *, ignore_case: bool = False):
        if not rules:
            raise RewriteError("At least one --replace OLD NEW pair is required")
        if any(rule.old == "" for rule in rules):
            raise RewriteError("Search terms may not be empty")

        normalize = str.casefold if ignore_case else (lambda value: value)
        normalized = [normalize(rule.old) for rule in rules]
        if len(set(normalized)) != len(normalized):
            raise RewriteError("Search terms must be unique")

        # A successful verification is impossible if replacement output itself
        # contains a search term.  Refuse swaps/cascades instead of claiming the
        # old value has disappeared when it has merely been reintroduced.
        for rule in rules:
            replacement = normalize(rule.new)
            for old in normalized:
                if old in replacement:
                    raise RewriteError(
                        "A replacement contains a search term; the requested rewrite "
                        "cannot finish with zero matches"
                    )

        flags = re.IGNORECASE if ignore_case else 0
        ordered = sorted(rules, key=lambda rule: len(rule.old), reverse=True)
        self.rules = tuple(rules)
        self.ignore_case = ignore_case
        self._lookup = {normalize(rule.old): rule.new for rule in rules}
        self._pattern = re.compile("|".join(re.escape(rule.old) for rule in ordered), flags)

    def replace(self, value: str) -> tuple[str, Counter[str]]:
        counts: Counter[str] = Counter()
        normalize = str.casefold if self.ignore_case else (lambda text: text)

        def substitute(match: re.Match[str]) -> str:
            key = normalize(match.group(0))
            counts[key] += 1
            return self._lookup[key]

        return self._pattern.sub(substitute, value), counts

    def count(self, value: str) -> Counter[str]:
        return self.replace(value)[1]

    def has_match(self, value: str) -> bool:
        return self._pattern.search(value) is not None


class FingerprintReplacementPlan(ReplacementPlan):
    """O(text length) replacement for a potentially large set of SHA-256s."""

    _fingerprint_pattern = re.compile(
        r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])"
    )

    def __init__(self, changes: dict[str, str]):
        rules = [Rule(old.lower(), new.lower()) for old, new in changes.items() if old != new]
        if not rules:
            raise RewriteError("At least one fingerprint change is required")
        self.rules = tuple(rules)
        self.ignore_case = True
        self._lookup = {rule.old: rule.new for rule in rules}
        self._pattern = self._fingerprint_pattern

    def replace(self, value: str) -> tuple[str, Counter[str]]:
        counts: Counter[str] = Counter()

        def substitute(match: re.Match[str]) -> str:
            key = match.group(0).lower()
            replacement = self._lookup.get(key)
            if replacement is None:
                return match.group(0)
            counts[key] += 1
            return replacement

        return self._pattern.sub(substitute, value), counts

    def has_match(self, value: str) -> bool:
        return any(
            match.group(0).lower() in self._lookup
            for match in self._pattern.finditer(value)
        )


class CompositeReplacementPlan(ReplacementPlan):
    """Combine plans for a single final read/parse verification pass."""

    def __init__(self, plans: Sequence[ReplacementPlan]):
        self.plans = tuple(plans)
        self.rules = tuple(rule for plan in plans for rule in plan.rules)
        self.ignore_case = any(plan.ignore_case for plan in plans)

    def replace(self, value: str) -> tuple[str, Counter[str]]:
        rewritten = value
        combined: Counter[str] = Counter()
        for plan in self.plans:
            rewritten, counts = plan.replace(rewritten)
            combined.update(counts)
        return rewritten, combined

    def has_match(self, value: str) -> bool:
        return any(plan.has_match(value) for plan in self.plans)


@dataclass
class LocationResult:
    location: str
    occurrences: int
    values: int = 1


@dataclass
class ScanReport:
    locations: list[LocationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    hash_references: dict[str, set[str]] = field(default_factory=dict)

    @property
    def occurrences(self) -> int:
        return sum(item.occurrences for item in self.locations)

    @property
    def values(self) -> int:
        return sum(item.values for item in self.locations)

    def add(self, location: str, occurrences: int, values: int = 1) -> None:
        if occurrences:
            self.locations.append(LocationResult(location, occurrences, values))


@dataclass(frozen=True)
class MediaReference:
    database: Path
    profile_dir: Path
    media_id: int
    file_path: Path
    file_hash: str
    storage_object_id: int | None
    storage_kind: str | None
    object_key: str | None
    external_path: Path | None
    lineage_hashes: frozenset[str] = frozenset()

    @property
    def payload_path(self) -> Path:
        if self.storage_kind == "managed" and self.object_key:
            return self.profile_dir / "objects" / self.object_key
        if self.storage_kind == "external" and self.external_path:
            return self.external_path
        return self.file_path


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def discover_databases(data_dir: Path) -> list[Path]:
    # Stimma databases consistently use a SQLite filename suffix. Restricting
    # signature reads to those candidates avoids touching every managed media
    # object's access/change timestamps during database discovery.
    return sorted(
        path for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SQLITE_SUFFIXES and _is_sqlite(path)
    )


def _database_text_columns(connection: sqlite3.Connection) -> Iterator[tuple[str, str]]:
    tables = connection.execute(
        "SELECT name, sql FROM sqlite_schema "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    virtual_names = {
        name for name, sql in tables
        if sql and sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE")
    }
    shadow_prefixes = tuple(f"{name}_" for name in virtual_names)
    for table_name, _sql in tables:
        if table_name in virtual_names or (shadow_prefixes and table_name.startswith(shadow_prefixes)):
            continue
        for column in connection.execute(f"PRAGMA table_xinfo({_quote(table_name)})"):
            column_name = column[1]
            hidden = column[6] if len(column) > 6 else 0
            if hidden == 0 and not _is_structural_column(column_name):
                yield table_name, column_name


def _is_structural_column(column_name: str) -> bool:
    lowered = column_name.lower()
    return (
        lowered in STRUCTURAL_COLUMN_NAMES
        or lowered.endswith(STRUCTURAL_COLUMN_SUFFIXES)
    )


def _database_value_text(value: object) -> tuple[str, bool] | None:
    if isinstance(value, str):
        return value, False
    if isinstance(value, bytes) and b"\x00" not in value:
        try:
            return value.decode("utf-8"), True
        except UnicodeDecodeError:
            return None
    return None


def _merge_simple_vocabulary_associations(
    connection: sqlite3.Connection,
    *,
    table: str,
    vocabulary_column: str,
    survivor_id: int,
    duplicate_id: int,
) -> None:
    columns = [row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")]
    if vocabulary_column not in columns:
        return
    quoted_columns = ", ".join(_quote(column) for column in columns)
    select_columns = ", ".join(
        "?" if column == vocabulary_column else _quote(column)
        for column in columns
    )
    connection.execute(
        f"INSERT OR IGNORE INTO {_quote(table)} ({quoted_columns}) "
        f"SELECT {select_columns} FROM {_quote(table)} "
        f"WHERE {_quote(vocabulary_column)} = ?",
        (survivor_id, duplicate_id),
    )
    connection.execute(
        f"DELETE FROM {_quote(table)} WHERE {_quote(vocabulary_column)} = ?",
        (duplicate_id,),
    )


def _merge_soft_vocabulary_associations(
    connection: sqlite3.Connection,
    *,
    table: str,
    vocabulary_column: str,
    survivor_id: int,
    duplicate_id: int,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")}
    if vocabulary_column not in columns or "deleted_at" not in columns:
        return
    # Non-conflicting rows move directly. A conflicting live row is first
    # retired, then remapped as historical data after it no longer participates
    # in the partial unique index.
    connection.execute(
        f"UPDATE OR IGNORE {_quote(table)} SET {_quote(vocabulary_column)} = ? "
        f"WHERE {_quote(vocabulary_column)} = ?",
        (survivor_id, duplicate_id),
    )
    connection.execute(
        f"UPDATE {_quote(table)} SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP), "
        f"{_quote(vocabulary_column)} = ? WHERE {_quote(vocabulary_column)} = ?",
        (survivor_id, duplicate_id),
    )


def _rewrite_normalized_vocabularies(
    connection: sqlite3.Connection,
    plan: ReplacementPlan,
    *,
    location_prefix: str,
) -> ScanReport:
    """Rewrite/merge normalized vocabularies without violating unique indexes.

    A literal replacement can collapse e.g. ``private portrait`` and
    ``clean portrait`` to the same final keyword. Keep the existing canonical
    row when possible, union its associations, then remove the redundant row
    inside the same transaction. Tags and markers use the same treatment.
    """
    report = ScanReport()
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table'"
        )
    }
    specs = (
        ("keywords", "keyword_text", (("media_keywords", "keyword_id", False),)),
        (
            "tags",
            "tag_text",
            (("media_tags", "tag_id", False), ("asset_tags", "tag_id", True)),
        ),
        (
            "markers",
            "name",
            (("media_markers", "marker_id", False), ("asset_markers", "marker_id", True)),
        ),
    )
    for table, text_column, associations in specs:
        if table not in tables:
            continue
        columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
        }
        if not {"id", text_column}.issubset(columns):
            continue
        rows = list(connection.execute(
            f"SELECT id, {_quote(text_column)} FROM {_quote(table)} ORDER BY id"
        ))
        grouped: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
        total_occurrences = 0
        changed_values = 0
        for vocabulary_id, original in rows:
            rewritten, counts = plan.replace(original)
            occurrences = sum(counts.values())
            grouped[rewritten].append((vocabulary_id, original, occurrences))
            if occurrences:
                total_occurrences += occurrences
                changed_values += 1

        for final_text, candidates in grouped.items():
            if not any(occurrences for _item_id, _original, occurrences in candidates):
                continue
            unchanged = [candidate for candidate in candidates if candidate[1] == final_text]
            survivor = min(unchanged or candidates, key=lambda candidate: candidate[0])
            survivor_id = survivor[0]
            for duplicate_id, _original, _occurrences in candidates:
                if duplicate_id == survivor_id:
                    continue
                for association_table, association_column, soft_delete in associations:
                    if association_table not in tables:
                        continue
                    merge = (
                        _merge_soft_vocabulary_associations
                        if soft_delete
                        else _merge_simple_vocabulary_associations
                    )
                    merge(
                        connection,
                        table=association_table,
                        vocabulary_column=association_column,
                        survivor_id=survivor_id,
                        duplicate_id=duplicate_id,
                    )
                connection.execute(
                    f"DELETE FROM {_quote(table)} WHERE id = ?", (duplicate_id,)
                )
            connection.execute(
                f"UPDATE {_quote(table)} SET {_quote(text_column)} = ? WHERE id = ?",
                (final_text, survivor_id),
            )

        report.add(
            f"{location_prefix}:{table}.{text_column}",
            total_occurrences,
            changed_values,
        )
    return report


def scan_database(path: Path, plan: ReplacementPlan) -> ScanReport:
    report = ScanReport()
    uri = f"file:{path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        for table_name, column_name in _database_text_columns(connection):
            sql = (
                f"SELECT {_quote(column_name)} FROM {_quote(table_name)} "
                f"WHERE typeof({_quote(column_name)}) IN ('text', 'blob')"
            )
            occurrences = 0
            values = 0
            for (value,) in connection.execute(sql):
                decoded = _database_value_text(value)
                if decoded is None:
                    continue
                count = sum(plan.count(decoded[0]).values())
                if count:
                    occurrences += count
                    values += 1
            report.add(f"{path.name}:{table_name}.{column_name}", occurrences, values)
    return report


def rewrite_database(
    path: Path, plan: ReplacementPlan, *, vacuum: bool = True
) -> ScanReport:
    report = ScanReport()
    connection = sqlite3.connect(path, timeout=1)
    try:
        connection.execute("PRAGMA busy_timeout = 1000")
        if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("BEGIN EXCLUSIVE")

        def replace_value(value: object) -> object:
            decoded = _database_value_text(value)
            if decoded is None:
                return value
            rewritten = plan.replace(decoded[0])[0]
            return rewritten.encode("utf-8") if decoded[1] else rewritten

        def has_match(value: object) -> int:
            decoded = _database_value_text(value)
            return int(decoded is not None and plan.has_match(decoded[0]))

        connection.create_function("stimma_rewrite", 1, replace_value)
        connection.create_function("stimma_has_rewrite", 1, has_match)
        _merge_report(
            report,
            _rewrite_normalized_vocabularies(
                connection,
                plan,
                location_prefix=path.name,
            ),
        )
        for table_name, column_name in _database_text_columns(connection):
            quoted_table = _quote(table_name)
            quoted_column = _quote(column_name)
            values = list(connection.execute(
                f"SELECT {quoted_column} FROM {quoted_table} "
                f"WHERE typeof({quoted_column}) IN ('text', 'blob') "
                f"AND stimma_has_rewrite({quoted_column})"
            ))
            if not values:
                continue
            occurrences = sum(
                sum(plan.count(_database_value_text(value)[0]).values())
                for (value,) in values
            )
            connection.execute(
                f"UPDATE {quoted_table} SET {quoted_column} = stimma_rewrite({quoted_column}) "
                f"WHERE typeof({quoted_column}) IN ('text', 'blob') "
                f"AND stimma_has_rewrite({quoted_column})"
            )
            report.add(f"{path.name}:{table_name}.{column_name}", occurrences, len(values))

        remaining = scan_database_connection(connection, plan)
        if remaining.occurrences:
            raise RewriteError(f"Verification found {remaining.occurrences} remaining matches in {path}")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RewriteError(f"SQLite integrity check failed for {path}: {integrity}")
        connection.commit()
    except sqlite3.OperationalError as exc:
        connection.rollback()
        if "locked" in str(exc).lower():
            raise RewriteError(
                f"Database is locked: {path}. Stop the Stimma backend and try again."
            ) from exc
        raise
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if vacuum:
        vacuum_database(path)
    return report


def vacuum_database(path: Path) -> None:
    """Checkpoint and rebuild a DB so replaced text is absent from free pages."""
    connection = sqlite3.connect(path, timeout=1)
    try:
        connection.execute("PRAGMA busy_timeout = 1000")
        original_journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if original_journal_mode == "wal":
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RewriteError(f"SQLite integrity check failed after VACUUM for {path}: {integrity}")
        if original_journal_mode == "wal":
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and checkpoint[0] != 0:
                raise RewriteError(f"Could not fully checkpoint WAL after VACUUM for {path}")
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise RewriteError(
                f"Database is locked: {path}. Stop the Stimma backend and try again."
            ) from exc
        raise
    finally:
        connection.close()

    for suffix in ("-journal", "-wal", "-shm"):
        companion = Path(f"{path}{suffix}")
        if companion.exists():
            companion.unlink()


def scan_database_connection(connection: sqlite3.Connection, plan: ReplacementPlan) -> ScanReport:
    report = ScanReport()
    for table_name, column_name in _database_text_columns(connection):
        quoted_table = _quote(table_name)
        quoted_column = _quote(column_name)
        occurrences = 0
        values = 0
        for (value,) in connection.execute(
            f"SELECT {quoted_column} FROM {quoted_table} "
            f"WHERE typeof({quoted_column}) IN ('text', 'blob')"
        ):
            decoded = _database_value_text(value)
            if decoded is None:
                continue
            count = sum(plan.count(decoded[0]).values())
            if count:
                occurrences += count
                values += 1
        report.add(f"{table_name}.{column_name}", occurrences, values)
    return report


def discover_media_references(databases: Iterable[Path]) -> list[MediaReference]:
    references: list[MediaReference] = []
    for database in databases:
        with sqlite3.connect(database) as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            }
            if "media_items" not in tables:
                continue
            media_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(media_items)")
            }
            metadata_columns = sorted(
                column for column in media_columns
                if column != "id" and not _is_structural_column(column)
            )
            lineage_hashes_by_id: dict[int, frozenset[str]] = {}
            if metadata_columns:
                selected = ", ".join(_quote(column) for column in metadata_columns)
                for row in connection.execute(f"SELECT id, {selected} FROM media_items"):
                    hashes: set[str] = set()
                    for value in row[1:]:
                        decoded = _database_value_text(value)
                        if decoded is None:
                            continue
                        hashes.update(_text_hash_references(decoded[0]))
                    if hashes:
                        lineage_hashes_by_id[row[0]] = frozenset(hashes)
            has_storage = "storage_objects" in tables and "storage_object_id" in media_columns
            if has_storage:
                rows = connection.execute(
                    "SELECT m.id, m.file_path, m.file_hash, m.storage_object_id, "
                    "s.kind, s.object_key, s.external_path "
                    "FROM media_items m LEFT JOIN storage_objects s ON s.id=m.storage_object_id"
                )
            else:
                rows = (
                    (*row, None, None, None, None)
                    for row in connection.execute("SELECT id, file_path, file_hash FROM media_items")
                )
            for media_id, file_path, file_hash, storage_id, kind, object_key, external_path in rows:
                references.append(MediaReference(
                    database=database,
                    profile_dir=database.parent,
                    media_id=media_id,
                    file_path=Path(file_path).expanduser(),
                    file_hash=file_hash,
                    storage_object_id=storage_id,
                    storage_kind=kind,
                    object_key=object_key,
                    external_path=Path(external_path).expanduser() if external_path else None,
                    lineage_hashes=lineage_hashes_by_id.get(media_id, frozenset()),
                ))
    return references


def assert_databases_writable(databases: Iterable[Path]) -> None:
    """Prove every DB can take an exclusive lock before changing any surface."""
    for database in databases:
        try:
            with sqlite3.connect(database, timeout=1) as connection:
                connection.execute("PRAGMA busy_timeout = 1000")
                connection.execute("BEGIN EXCLUSIVE")
                connection.rollback()
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise RewriteError(
                    f"Database is locked: {database}. Stop the Stimma backend and try again."
                ) from exc
            raise


def _png_chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    if not data.startswith(PNG_HEADER):
        raise RewriteError("Invalid PNG signature")
    offset = len(PNG_HEADER)
    while offset < len(data):
        if offset + 12 > len(data):
            raise RewriteError("Truncated PNG chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise RewriteError("Truncated PNG payload")
        payload = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise RewriteError(f"PNG chunk {chunk_type!r} has an invalid CRC")
        yield chunk_type, payload
        offset = end
        if chunk_type == b"IEND":
            # The PNG spec ends at IEND, but a meaningful number of real-world
            # files have harmless encoder/app detritus after it. Preserve those
            # bytes exactly instead of rejecting an otherwise parseable image.
            if offset < len(data):
                yield PNG_TRAILING_DATA, data[offset:]
            return
    raise RewriteError("PNG has no IEND chunk")


def _pack_png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload)) + chunk_type + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _replace_encoded_text(raw: bytes, plan: ReplacementPlan, encoding: str) -> tuple[bytes, int]:
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        return raw, 0
    rewritten, counts = plan.replace(text)
    occurrences = sum(counts.values())
    if not occurrences:
        return raw, 0
    try:
        return rewritten.encode(encoding), occurrences
    except UnicodeEncodeError as exc:
        raise RewriteError(f"Replacement cannot be represented as {encoding}") from exc


def _rewrite_exif_value(value: object, plan: ReplacementPlan) -> tuple[object, int]:
    if isinstance(value, str):
        rewritten, counts = plan.replace(value)
        return rewritten, sum(counts.values())
    if isinstance(value, bytes):
        if value.startswith(b"UNICODE\x00"):
            rewritten, count = _replace_encoded_text(value[8:], plan, "utf-16-be")
            return b"UNICODE\x00" + rewritten, count
        # Current Stimma metadata uses UTF-8 in UserComment/MakerNote.  UTF-8
        # is also byte-identical to EXIF ASCII for ordinary ASCII prompts.
        rewritten, count = _replace_encoded_text(value, plan, "utf-8")
        if count:
            return rewritten, count
        # Windows XP* EXIF tags use UTF-16LE without the UserComment prefix.
        rewritten, count = _replace_encoded_text(value, plan, "utf-16-le")
        return rewritten, count
    if isinstance(value, tuple):
        rewritten_items = []
        total = 0
        for item in value:
            rewritten, count = _rewrite_exif_value(item, plan)
            rewritten_items.append(rewritten)
            total += count
        return tuple(rewritten_items), total
    if isinstance(value, list):
        rewritten_items = []
        total = 0
        for item in value:
            rewritten, count = _rewrite_exif_value(item, plan)
            rewritten_items.append(rewritten)
            total += count
        return rewritten_items, total
    if isinstance(value, dict):
        total = 0
        rewritten_dict = {}
        for key, item in value.items():
            rewritten, count = _rewrite_exif_value(item, plan)
            rewritten_dict[key] = rewritten
            total += count
        return rewritten_dict, total
    return value, 0


def _rewrite_exif_payload(payload: bytes, plan: ReplacementPlan, *, png: bool) -> tuple[bytes, int]:
    load_payload = b"Exif\x00\x00" + payload if png and not payload.startswith(b"Exif\x00\x00") else payload
    try:
        exif = piexif.load(load_payload)
        rewritten, count = _rewrite_exif_value(exif, plan)
        if not count:
            return payload, 0
        dumped = piexif.dump(rewritten)
        if png and dumped.startswith(b"Exif\x00\x00"):
            dumped = dumped[6:]
        return dumped, count
    except Exception as exc:
        # Fail closed only when the unreadable EXIF payload visibly contains a
        # target UTF-8 term.  Unrelated malformed camera EXIF is preserved.
        decoded = payload.decode("utf-8", errors="ignore")
        if plan.has_match(decoded):
            raise RewriteError("Matched text exists in EXIF that could not be safely rewritten") from exc
        return payload, 0


def rewrite_png_bytes(data: bytes, plan: ReplacementPlan) -> tuple[bytes, int]:
    output = bytearray(PNG_HEADER)
    total = 0
    for chunk_type, payload in _png_chunks(data):
        if chunk_type == PNG_TRAILING_DATA:
            output.extend(payload)
            continue
        rewritten = payload
        count = 0
        if chunk_type == b"tEXt":
            if b"\x00" not in payload:
                raise RewriteError("Malformed PNG tEXt chunk")
            keyword, text = payload.split(b"\x00", 1)
            new_keyword, count1 = _replace_encoded_text(keyword, plan, "latin-1")
            new_text, count2 = _replace_encoded_text(text, plan, "latin-1")
            rewritten, count = new_keyword + b"\x00" + new_text, count1 + count2
        elif chunk_type == b"zTXt":
            if b"\x00" not in payload:
                raise RewriteError("Malformed PNG zTXt chunk")
            keyword, compressed = payload.split(b"\x00", 1)
            if not compressed or compressed[0] != 0:
                raise RewriteError("Unsupported PNG zTXt compression")
            text = zlib.decompress(compressed[1:])
            new_keyword, count1 = _replace_encoded_text(keyword, plan, "latin-1")
            new_text, count2 = _replace_encoded_text(text, plan, "latin-1")
            rewritten = new_keyword + b"\x00\x00" + zlib.compress(new_text)
            count = count1 + count2
        elif chunk_type == b"iTXt":
            if b"\x00" not in payload:
                raise RewriteError("Malformed PNG iTXt chunk")
            keyword, remainder = payload.split(b"\x00", 1)
            if len(remainder) < 2:
                raise RewriteError("Malformed PNG iTXt chunk")
            flag, method, remainder = remainder[:1], remainder[1:2], remainder[2:]
            parts = remainder.split(b"\x00", 2)
            if len(parts) != 3:
                raise RewriteError("Malformed PNG iTXt chunk")
            language, translated, text = parts
            if flag == b"\x01":
                text = zlib.decompress(text)
            elif flag != b"\x00":
                raise RewriteError("Unsupported PNG iTXt compression flag")
            new_keyword, count1 = _replace_encoded_text(keyword, plan, "latin-1")
            new_translated, count2 = _replace_encoded_text(translated, plan, "utf-8")
            new_text, count3 = _replace_encoded_text(text, plan, "utf-8")
            if flag == b"\x01":
                new_text = zlib.compress(new_text)
            rewritten = (
                new_keyword + b"\x00" + flag + method + language + b"\x00"
                + new_translated + b"\x00" + new_text
            )
            count = count1 + count2 + count3
        elif chunk_type == b"eXIf":
            rewritten, count = _rewrite_exif_payload(payload, plan, png=True)
        total += count
        output.extend(_pack_png_chunk(chunk_type, rewritten))
    return bytes(output), total


def rewrite_jpeg_bytes(data: bytes, plan: ReplacementPlan) -> tuple[bytes, int]:
    if not data.startswith(JPEG_HEADER):
        raise RewriteError("Invalid JPEG signature")
    output = bytearray(JPEG_HEADER)
    offset = 2
    total = 0
    while offset < len(data):
        if data[offset] != 0xFF:
            raise RewriteError("Malformed JPEG marker stream")
        marker_start = offset
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            raise RewriteError("Truncated JPEG marker")
        marker = data[offset]
        offset += 1
        marker_prefix = data[marker_start:offset]
        if marker == 0xDA:  # Start of scan: compressed pixels continue to EOF.
            output.extend(data[marker_start:])
            return bytes(output), total
        if marker in {0x01, *range(0xD0, 0xDA)}:
            output.extend(marker_prefix)
            continue
        if offset + 2 > len(data):
            raise RewriteError("Truncated JPEG segment length")
        length = struct.unpack(">H", data[offset:offset + 2])[0]
        if length < 2 or offset + length > len(data):
            raise RewriteError("Invalid JPEG segment length")
        payload = data[offset + 2:offset + length]
        rewritten = payload
        count = 0
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            rewritten, count = _rewrite_exif_payload(payload, plan, png=False)
        elif marker == 0xFE:  # COM
            rewritten, count = _replace_encoded_text(payload, plan, "utf-8")
            if not count:
                rewritten, count = _replace_encoded_text(payload, plan, "latin-1")
        elif marker == 0xE1 and (
            payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00")
            or payload.startswith(b"http://ns.adobe.com/xmp/extension/\x00")
        ):
            header, xml = payload.split(b"\x00", 1)
            new_xml, count = _replace_encoded_text(xml, plan, "utf-8")
            rewritten = header + b"\x00" + new_xml
        if len(rewritten) + 2 > 0xFFFF:
            raise RewriteError("Rewritten JPEG metadata segment exceeds 64 KiB")
        output.extend(marker_prefix)
        output.extend(struct.pack(">H", len(rewritten) + 2))
        output.extend(rewritten)
        total += count
        offset += length
    return bytes(output), total


def rewrite_payload_bytes(data: bytes, path: Path, plan: ReplacementPlan) -> tuple[bytes, int]:
    if data.startswith(PNG_HEADER):
        return rewrite_png_bytes(data, plan)
    if data.startswith(JPEG_HEADER):
        return rewrite_jpeg_bytes(data, plan)
    if b"\x00" in data:
        return data, 0
    rewritten, count = _replace_encoded_text(data, plan, "utf-8")
    return rewritten, count


def _byte_hash_references(data: bytes) -> set[str]:
    return {match.group(0).decode("ascii").lower() for match in HASH_FINGERPRINT_BYTES.finditer(data)}


def _text_hash_references(text: str) -> set[str]:
    return _byte_hash_references(text.encode("utf-8", errors="ignore"))


def payload_hash_references(data: bytes, path: Path) -> set[str]:
    """Extract SHA-256 lineage tokens only from payload surfaces we can rewrite."""
    hashes: set[str] = set()
    if data.startswith(PNG_HEADER):
        for chunk_type, payload in _png_chunks(data):
            if chunk_type == b"tEXt":
                hashes.update(_byte_hash_references(payload))
            elif chunk_type == b"zTXt" and b"\x00" in payload:
                _keyword, compressed = payload.split(b"\x00", 1)
                hashes.update(_byte_hash_references(_keyword))
                if compressed and compressed[0] == 0:
                    hashes.update(_byte_hash_references(zlib.decompress(compressed[1:])))
            elif chunk_type == b"iTXt" and b"\x00" in payload:
                keyword, remainder = payload.split(b"\x00", 1)
                hashes.update(_byte_hash_references(keyword))
                if len(remainder) < 2:
                    continue
                flag, remainder = remainder[:1], remainder[2:]
                parts = remainder.split(b"\x00", 2)
                if len(parts) != 3:
                    continue
                _language, translated, text = parts
                hashes.update(_byte_hash_references(translated))
                if flag == b"\x01":
                    text = zlib.decompress(text)
                hashes.update(_byte_hash_references(text))
            elif chunk_type == b"eXIf":
                hashes.update(_byte_hash_references(payload))
        return hashes
    if data.startswith(JPEG_HEADER):
        offset = 2
        while offset < len(data):
            if data[offset] != 0xFF:
                raise RewriteError("Malformed JPEG marker stream")
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                raise RewriteError("Truncated JPEG marker")
            marker = data[offset]
            offset += 1
            if marker == 0xDA:
                break
            if marker in {0x01, *range(0xD0, 0xDA)}:
                continue
            if offset + 2 > len(data):
                raise RewriteError("Truncated JPEG segment length")
            length = struct.unpack(">H", data[offset:offset + 2])[0]
            if length < 2 or offset + length > len(data):
                raise RewriteError("Invalid JPEG segment length")
            payload = data[offset + 2:offset + length]
            if marker in {0xE1, 0xFE}:
                hashes.update(_byte_hash_references(payload))
            offset += length
        return hashes
    if b"\x00" not in data:
        hashes.update(_byte_hash_references(data))
    return hashes


def _file_times_ns(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_atime_ns, stat.st_mtime_ns


def _restore_file_times(path: Path, times_ns: tuple[int, int]) -> None:
    current = _file_times_ns(path)
    if current != times_ns:
        os.utime(path, ns=times_ns)


def _read_bytes_preserving_times(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Read a file without leaving its access or modification time changed."""
    times_ns = _file_times_ns(path)
    try:
        return path.read_bytes(), times_ns
    finally:
        _restore_file_times(path, times_ns)


def _hash_file_preserving_times(digest: "hashlib._Hash", path: Path) -> None:
    times_ns = _file_times_ns(path)
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        _restore_file_times(path, times_ns)


def _payload_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        _hash_file_preserving_times(digest, path)
        return digest.hexdigest()
    digest.update(b"stimma-directory-v1\x00")
    for candidate in sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    ):
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        _hash_file_preserving_times(digest, candidate)
    return digest.hexdigest()


def _payload_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _payload_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    if path.is_dir():
        yield from sorted(item for item in path.rglob("*") if item.is_file())


def scan_payload(path: Path, plan: ReplacementPlan) -> int:
    total = 0
    for candidate in _payload_files(path):
        try:
            data, _times_ns = _read_bytes_preserving_times(candidate)
            _rewritten, count = rewrite_payload_bytes(data, candidate, plan)
            total += count
        except (OSError, RewriteError, zlib.error):
            raise
    return total


def scan_payload_report(path: Path, plan: ReplacementPlan) -> ScanReport:
    """Best-effort payload scan which records unreadable members and continues."""
    report = ScanReport()
    total = 0
    hash_references: set[str] = set()
    for candidate in _payload_files(path):
        try:
            data, _times_ns = _read_bytes_preserving_times(candidate)
            _rewritten, count = rewrite_payload_bytes(data, candidate, plan)
            hash_references.update(payload_hash_references(data, candidate))
            total += count
        except Exception as exc:
            report.errors.append(
                f"{candidate}: {type(exc).__name__}: {exc}"
            )
    report.add(str(path), total)
    if hash_references:
        report.hash_references[str(path)] = hash_references
    return report


def rewrite_payload(path: Path, plan: ReplacementPlan) -> int:
    total = 0
    for candidate in _payload_files(path):
        data, times_ns = _read_bytes_preserving_times(candidate)
        rewritten, count = rewrite_payload_bytes(data, candidate, plan)
        if count:
            _write_in_place(candidate, rewritten, times_ns=times_ns)
            total += count
    remaining = scan_payload(path, plan)
    if remaining:
        raise RewriteError(f"Verification found {remaining} matches in media payload {path}")
    return total


def rewrite_payload_report(path: Path, plan: ReplacementPlan) -> ScanReport:
    """Rewrite readable payload members while skipping and recording corrupt ones."""
    report = ScanReport()
    total = 0
    for candidate in _payload_files(path):
        try:
            data, times_ns = _read_bytes_preserving_times(candidate)
            rewritten, count = rewrite_payload_bytes(data, candidate, plan)
            if not count:
                continue
            _verified, remaining = rewrite_payload_bytes(rewritten, candidate, plan)
            if remaining:
                raise RewriteError(
                    f"Verification found {remaining} matches after rewriting"
                )
            _write_in_place(candidate, rewritten, times_ns=times_ns)
            total += count
        except Exception as exc:
            report.errors.append(
                f"{candidate}: {type(exc).__name__}: {exc}"
            )
    report.add(str(path), total)
    return report


def _write_in_place(path: Path, data: bytes, *, times_ns: tuple[int, int]) -> None:
    # In-place replacement deliberately preserves hard links used by managed
    # compatibility paths.  A temporary sibling still ensures all bytes are
    # prepared and fsynced before the short truncate/write window.
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rewrite-", dir=path.parent)
    temporary = Path(temporary_name)
    destination_touched = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with path.open("r+b") as destination, temporary.open("rb") as source:
            destination_touched = True
            destination.seek(0)
            shutil.copyfileobj(source, destination, 1024 * 1024)
            destination.truncate()
            destination.flush()
            os.fsync(destination.fileno())
    finally:
        temporary.unlink(missing_ok=True)
        if destination_touched:
            _restore_file_times(path, times_ns)


def _media_groups(references: Sequence[MediaReference]) -> list[tuple[Path, list[MediaReference]]]:
    groups: dict[tuple[object, ...], tuple[Path, list[MediaReference]]] = {}
    for reference in references:
        path = reference.payload_path
        if not path.exists():
            continue
        try:
            stat = path.stat()
            key = ("inode", stat.st_dev, stat.st_ino)
        except OSError:
            key = ("path", str(path.resolve(strict=False)))
        if key not in groups:
            groups[key] = (path, [])
        groups[key][1].append(reference)
    return sorted(groups.values(), key=lambda item: str(item[0]))


def _update_media_identity(
    references: Sequence[MediaReference], old_path: Path, new_hash: str, new_size: int
) -> Path:
    final_path = old_path
    by_database: dict[Path, list[MediaReference]] = defaultdict(list)
    for reference in references:
        by_database[reference.database].append(reference)

    for database, db_references in by_database.items():
        with sqlite3.connect(database, timeout=1) as connection:
            connection.execute("BEGIN EXCLUSIVE")
            for reference in db_references:
                connection.execute(
                    "UPDATE media_items SET file_hash=?, file_size=? WHERE id=?",
                    (new_hash, new_size, reference.media_id),
                )
                if reference.storage_object_id is None:
                    continue
                if reference.storage_kind == "external":
                    connection.execute(
                        "UPDATE storage_objects SET expected_hash=?, file_size=?, verified_at=? WHERE id=?",
                        (new_hash, new_size, datetime.now(timezone.utc).replace(tzinfo=None), reference.storage_object_id),
                    )
                elif reference.storage_kind == "managed":
                    new_key = f"sha256/{new_hash[:2]}/{new_hash[2:4]}/{new_hash}"
                    existing = connection.execute(
                        "SELECT id FROM storage_objects WHERE kind='managed' AND object_key=?",
                        (new_key,),
                    ).fetchone()
                    if existing and existing[0] != reference.storage_object_id:
                        connection.execute(
                            "UPDATE media_items SET storage_object_id=? WHERE storage_object_id=?",
                            (existing[0], reference.storage_object_id),
                        )
                        connection.execute(
                            "DELETE FROM storage_objects WHERE id=? AND NOT EXISTS "
                            "(SELECT 1 FROM media_items WHERE storage_object_id=?)",
                            (reference.storage_object_id, reference.storage_object_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE storage_objects SET object_key=?, expected_hash=?, file_size=?, verified_at=? "
                            "WHERE id=?",
                            (
                                new_key, new_hash, new_size,
                                datetime.now(timezone.utc).replace(tzinfo=None),
                                reference.storage_object_id,
                            ),
                        )
                    destination = reference.profile_dir / "objects" / new_key
                    if final_path != destination:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if destination.exists():
                            if _payload_hash(destination) != new_hash:
                                raise RewriteError(f"Managed destination hash mismatch: {destination}")
                            if final_path.is_dir():
                                shutil.rmtree(final_path)
                            else:
                                final_path.unlink()
                        else:
                            final_path.rename(destination)
                        final_path = destination
            connection.commit()

    # A managed collision may have removed the old inode.  Rebuild every
    # compatibility locator against the canonical rewritten object.
    for reference in references:
        if reference.storage_kind != "managed" or reference.file_path == final_path:
            continue
        link = reference.file_path
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            if link.is_dir() and not link.is_symlink():
                shutil.rmtree(link)
            else:
                link.unlink()
        if final_path.is_dir():
            link.symlink_to(final_path, target_is_directory=True)
        else:
            try:
                os.link(final_path, link)
            except OSError:
                link.symlink_to(final_path)
    return final_path


def discover_sandbox_text_files(data_dir: Path, databases: set[Path]) -> list[Path]:
    files: list[Path] = []
    for path in data_dir.rglob("*"):
        if not path.is_file() or path in databases:
            continue
        relative = path.relative_to(data_dir)
        if any(part in EXCLUDED_TEXT_DIRS for part in relative.parts[:-1]):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name.endswith(".stimmaedit.json"):
            files.append(path)
    return sorted(files)


def _backup_path(source: Path, *, data_dir: Path, backup_dir: Path) -> Path:
    try:
        relative = source.resolve(strict=False).relative_to(data_dir.resolve())
        return backup_dir / "sandbox" / relative
    except ValueError:
        digest = hashlib.sha256(str(source.resolve(strict=False)).encode()).hexdigest()[:16]
        return backup_dir / "external" / digest / source.name


def backup_files(paths: Iterable[Path], *, data_dir: Path, backup_dir: Path) -> None:
    for source in sorted(set(paths)):
        if not source.exists():
            continue
        destination = _backup_path(source, data_dir=data_dir, backup_dir=backup_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)


def backup_databases(paths: Iterable[Path], *, data_dir: Path, backup_dir: Path) -> None:
    """Create transactionally consistent SQLite backups, including WAL data."""
    for source in sorted(set(paths)):
        destination = _backup_path(source, data_dir=data_dir, backup_dir=backup_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as target:
            source_connection.backup(target)


@dataclass
class RewriteSummary:
    database_report: ScanReport = field(default_factory=ScanReport)
    file_report: ScanReport = field(default_factory=ScanReport)
    hash_changes: dict[str, str] = field(default_factory=dict)

    @property
    def occurrences(self) -> int:
        return self.database_report.occurrences + self.file_report.occurrences


@dataclass(frozen=True)
class ScanJob:
    surface: str
    path: Path
    description: str


@dataclass
class MediaGroupState:
    key: str
    path: Path
    references: list[MediaReference]
    original_hashes: set[str]
    lineage_hashes: set[str]
    current_hash: str | None


def _new_progress(console: Console) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(show_speed=True),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
        refresh_per_second=4,
    )


def _phase(console: Console, message: str) -> None:
    timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
    console.print(f"[cyan]{timestamp}[/cyan] {message}")


def _build_media_group_states(
    media_groups: Sequence[tuple[Path, list[MediaReference]]],
    scan_report: ScanReport,
) -> list[MediaGroupState]:
    states: list[MediaGroupState] = []
    for path, references in media_groups:
        original_hashes = {
            reference.file_hash.lower()
            for reference in references
            if reference.file_hash
        }
        lineage_hashes = set(scan_report.hash_references.get(str(path), set()))
        for reference in references:
            lineage_hashes.update(reference.lineage_hashes)
        states.append(MediaGroupState(
            key=str(path),
            path=path,
            references=list(references),
            original_hashes=original_hashes,
            lineage_hashes={value.lower() for value in lineage_hashes},
            current_hash=min(original_hashes) if original_hashes else None,
        ))
    return states


def _refresh_media_group_states(
    states: Sequence[MediaGroupState], references: Sequence[MediaReference]
) -> None:
    state_by_media = {
        (reference.database, reference.media_id): state
        for state in states
        for reference in state.references
    }
    refreshed: dict[str, list[MediaReference]] = defaultdict(list)
    for reference in references:
        state = state_by_media.get((reference.database, reference.media_id))
        if state is not None:
            refreshed[state.key].append(reference)
    for state in states:
        latest = refreshed.get(state.key)
        if not latest:
            continue
        state.references = latest
        state.path = latest[0].payload_path
        current_hashes = {reference.file_hash.lower() for reference in latest if reference.file_hash}
        state.current_hash = min(current_hashes) if current_hashes else state.current_hash


def _flatten_hash_changes(changes: dict[str, str]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for original in changes:
        current = original
        seen: set[str] = set()
        while current in changes and changes[current] != current:
            if current in seen:
                raise RewriteError("Cycle detected while resolving rewritten media hashes")
            seen.add(current)
            current = changes[current]
        if original != current:
            flattened[original] = current
    return flattened


def _affected_media_order(
    states: Sequence[MediaGroupState], initial_hashes: set[str]
) -> list[MediaGroupState]:
    states_by_original_hash: dict[str, list[MediaGroupState]] = defaultdict(list)
    states_by_dependency: dict[str, list[MediaGroupState]] = defaultdict(list)
    for state in states:
        for value in state.original_hashes:
            states_by_original_hash[value].append(state)
        for value in state.lineage_hashes:
            states_by_dependency[value].append(state)

    affected: dict[str, MediaGroupState] = {}
    pending = deque(sorted(initial_hashes))
    seen_hashes: set[str] = set()
    while pending:
        changed_hash = pending.popleft()
        if changed_hash in seen_hashes:
            continue
        seen_hashes.add(changed_hash)
        for state in states_by_dependency.get(changed_hash, ()):
            if state.key in affected:
                continue
            affected[state.key] = state
            pending.extend(sorted(state.original_hashes))

    parents: dict[str, set[str]] = {key: set() for key in affected}
    children: dict[str, set[str]] = defaultdict(set)
    for state in affected.values():
        for dependency in state.lineage_hashes:
            for parent in states_by_original_hash.get(dependency, ()):
                if parent.key not in affected or parent.key == state.key:
                    continue
                parents[state.key].add(parent.key)
                children[parent.key].add(state.key)

    ready = deque(sorted(key for key, values in parents.items() if not values))
    ordered: list[MediaGroupState] = []
    while ready:
        key = ready.popleft()
        ordered.append(affected[key])
        for child in sorted(children.get(key, ())):
            parents[child].discard(key)
            if not parents[child]:
                ready.append(child)
    if len(ordered) != len(affected):
        raise RewriteError("Cycle detected in persisted media lineage")
    return ordered


def _propagate_media_lineage(
    states: Sequence[MediaGroupState],
    initial_changes: dict[str, str],
    *,
    console: Console,
    summary: RewriteSummary,
) -> dict[str, str]:
    changes = {old.lower(): new.lower() for old, new in initial_changes.items()}
    ordered = _affected_media_order(states, set(changes))
    _phase(
        console,
        f"Lineage graph ready: {len(ordered)} affected media; each will be rewritten at most once.",
    )
    if not ordered:
        return _flatten_hash_changes(changes)

    with _new_progress(console) as progress:
        task = progress.add_task("Propagating lineage", total=len(ordered))
        for index, state in enumerate(ordered, start=1):
            progress.update(
                task,
                description=f"Propagating lineage {state.path.name}",
            )
            flattened = _flatten_hash_changes(changes)
            relevant = {
                dependency: flattened[dependency]
                for dependency in state.lineage_hashes
                if dependency in flattened and dependency != flattened[dependency]
            }
            if relevant:
                report = rewrite_payload_report(
                    state.path, FingerprintReplacementPlan(relevant)
                )
                summary.file_report.errors.extend(report.errors)
                if report.occurrences:
                    previous_hash = state.current_hash
                    new_hash = _payload_hash(state.path)
                    new_size = _payload_size(state.path)
                    state.path = _update_media_identity(
                        state.references, state.path, new_hash, new_size
                    )
                    state.current_hash = new_hash
                    if previous_hash:
                        changes[previous_hash] = new_hash
                    for original_hash in state.original_hashes:
                        changes[original_hash] = new_hash
            progress.update(task, completed=index)
    return _flatten_hash_changes(changes)


def _merge_report(target: ScanReport, source: ScanReport) -> None:
    target.locations.extend(source.locations)
    target.errors.extend(source.errors)
    for location, hashes in source.hash_references.items():
        target.hash_references.setdefault(location, set()).update(hashes)


def _scan_job(job: ScanJob, plan: ReplacementPlan) -> tuple[str, ScanReport]:
    if job.surface == "database":
        return job.surface, scan_database(job.path, plan)
    return job.surface, scan_payload_report(job.path, plan)


def _parallel_scan_jobs(
    jobs: Sequence[ScanJob],
    plan: ReplacementPlan,
    *,
    workers: int,
    progress: Progress,
    task_id,
    summary: RewriteSummary,
) -> None:
    """Run a bounded set of read-only scan jobs and merge on the main thread."""
    if not jobs:
        return
    pending: dict[concurrent.futures.Future, ScanJob] = {}
    job_iterator = iter(jobs)
    max_pending = max(workers, workers * 4)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="prompt-rewrite-scan",
    ) as executor:
        for _ in range(min(max_pending, len(jobs))):
            job = next(job_iterator)
            pending[executor.submit(_scan_job, job, plan)] = job

        while pending:
            done, _not_done = concurrent.futures.wait(
                pending,
                timeout=1,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                progress.update(
                    task_id,
                    description=f"Scanning: {len(pending)} active/queued jobs remain",
                )
                continue
            for future in done:
                job = pending.pop(future)
                surface, report = future.result()
                target = (
                    summary.database_report
                    if surface == "database"
                    else summary.file_report
                )
                _merge_report(target, report)
                progress.update(task_id, description=job.description)
                progress.advance(task_id)
                try:
                    next_job = next(job_iterator)
                except StopIteration:
                    continue
                pending[executor.submit(_scan_job, next_job, plan)] = next_job


def run_rewrite(
    data_dir: Path,
    plan: ReplacementPlan,
    *,
    apply: bool,
    include_external_media: bool = True,
    backup_dir: Path | None = None,
    console: Console | None = None,
    workers: int = DEFAULT_SCAN_WORKERS,
    _preflight: bool = True,
    _propagate_hashes: bool = True,
    _vacuum_after: bool = True,
) -> RewriteSummary:
    console = console or Console()
    data_dir = data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        raise RewriteError(f"Stimma data directory not found: {data_dir}")
    if workers < 1:
        raise RewriteError("--workers must be at least 1")

    _phase(console, "Inventorying databases, media, sidecars, and text surfaces.")
    with _new_progress(console) as inventory_progress:
        inventory_task = inventory_progress.add_task("Building in-memory inventory", total=None)
        databases = discover_databases(data_dir)
        if not databases:
            raise RewriteError(f"No SQLite databases found below {data_dir}")
        references = discover_media_references(databases)
        media_groups = _media_groups(references)
        if not include_external_media:
            media_groups = [
                (path, refs) for path, refs in media_groups
                if any(ref.storage_kind == "managed" for ref in refs)
                or data_dir in path.resolve(strict=False).parents
            ]
        text_files = discover_sandbox_text_files(data_dir, set(databases))
        inventory_progress.update(
            inventory_task,
            description=(
                f"Inventory ready: {len(databases)} DBs, {len(media_groups)} media, "
                f"{len(text_files)} text files"
            ),
        )

    associated_sidecars = sorted({
        Path(f"{reference.file_path}.stimmaedit.json")
        for _path, group_references in media_groups
        for reference in group_references
        if Path(f"{reference.file_path}.stimmaedit.json").exists()
    })
    media_paths = {
        candidate.resolve(strict=False)
        for path, _refs in media_groups for candidate in _payload_files(path)
    }
    sidecar_paths = {path.resolve(strict=False) for path in associated_sidecars}
    standalone_text_files = [
        path for path in text_files
        if path.resolve(strict=False) not in media_paths | sidecar_paths
    ]

    preflight_summary: RewriteSummary | None = None
    if apply and _preflight:
        # Do a complete parse/read pass and prove all database locks before the
        # first mutation. Corrupt media is recorded and skipped; database and
        # lock failures remain fatal.
        _phase(console, "Preflight: scanning every readable surface once and indexing lineage in RAM.")
        preflight_summary = run_rewrite(
            data_dir,
            plan,
            apply=False,
            include_external_media=include_external_media,
            console=console,
            workers=workers,
        )
        assert_databases_writable(databases)
        _phase(
            console,
            f"Preflight complete: {preflight_summary.occurrences} occurrences; "
            f"{len(preflight_summary.file_report.hash_references)} lineage-bearing files indexed.",
        )

    summary = RewriteSummary()
    if preflight_summary is not None:
        summary.file_report.errors.extend(preflight_summary.file_report.errors)
    progress = _new_progress(console)

    if apply and backup_dir:
        _phase(console, f"Creating rollback backup at {backup_dir}.")
        resolved_backup_dir = backup_dir.expanduser().resolve()
        if resolved_backup_dir == data_dir or data_dir in resolved_backup_dir.parents:
            raise RewriteError("--backup-dir must be outside the Stimma sandbox being rewritten")
        if resolved_backup_dir.exists() and any(resolved_backup_dir.iterdir()):
            raise RewriteError("--backup-dir must be new or empty")
        resolved_backup_dir.mkdir(parents=True, exist_ok=True)
        backup_sources = [
            *text_files,
            *associated_sidecars,
            *(path for path, _refs in media_groups),
        ]
        with _new_progress(console) as backup_progress:
            backup_task = backup_progress.add_task("Backing up databases", total=None)
            backup_databases(databases, data_dir=data_dir, backup_dir=resolved_backup_dir)
            backup_progress.update(backup_task, description="Backing up media and text files")
            backup_files(backup_sources, data_dir=data_dir, backup_dir=resolved_backup_dir)
            backup_progress.update(backup_task, description="Rollback backup complete")

    if not apply:
        scan_jobs = [
            *(ScanJob("database", path, f"Scanning database {path.name}") for path in databases),
            *(ScanJob("file", path, f"Scanning media {path.name}") for path, _refs in media_groups),
            *(ScanJob("file", path, f"Scanning sidecar {path.name}") for path in associated_sidecars),
            *(ScanJob("file", path, f"Scanning file {path.name}") for path in standalone_text_files),
        ]
        _phase(console, f"Scanning {len(scan_jobs)} surfaces with {workers} workers.")
        with progress:
            task = progress.add_task(
                f"Scanning with {workers} workers",
                total=len(scan_jobs),
            )
            _parallel_scan_jobs(
                scan_jobs,
                plan,
                workers=workers,
                progress=progress,
                task_id=task,
                summary=summary,
            )
        summary.database_report.locations.sort(key=lambda item: item.location)
        summary.file_report.locations.sort(key=lambda item: item.location)
        summary.file_report.errors = sorted(set(summary.file_report.errors))
        _phase(console, f"Scan complete: {summary.occurrences} occurrences found.")
        return summary

    matching_locations = (
        {item.location for item in preflight_summary.file_report.locations}
        if preflight_summary is not None
        else None
    )
    rewrite_media_groups = [
        (path, refs) for path, refs in media_groups
        if matching_locations is None or str(path) in matching_locations
    ]
    rewrite_sidecars = [
        path for path in associated_sidecars
        if matching_locations is None or str(path) in matching_locations
    ]
    rewrite_text_files = [
        path for path in standalone_text_files
        if matching_locations is None or str(path) in matching_locations
    ]
    total_steps = (
        len(databases) + len(rewrite_media_groups)
        + len(rewrite_sidecars) + len(rewrite_text_files)
    )
    media_states = _build_media_group_states(
        media_groups,
        preflight_summary.file_report if preflight_summary is not None else ScanReport(),
    )
    state_by_key = {state.key: state for state in media_states}

    _phase(
        console,
        f"Applying requested replacements to {total_steps} matching database/file surfaces.",
    )
    with progress:
        task = progress.add_task("Rewriting", total=total_steps)
        for database in databases:
            progress.update(task, description=f"Rewriting database {database.name}")
            report = rewrite_database(database, plan, vacuum=False)
            _merge_report(summary.database_report, report)
            progress.advance(task)

        for path, refs in rewrite_media_groups:
            progress.update(task, description=f"Rewriting media {path.name}")
            report = rewrite_payload_report(path, plan)
            _merge_report(summary.file_report, report)
            if report.occurrences:
                new_hash = _payload_hash(path)
                new_size = _payload_size(path)
                for reference in refs:
                    if reference.file_hash and reference.file_hash != new_hash:
                        summary.hash_changes[reference.file_hash] = new_hash
                final_path = _update_media_identity(refs, path, new_hash, new_size)
                state = state_by_key.get(str(path))
                if state is not None:
                    state.path = final_path
                    state.current_hash = new_hash
            progress.advance(task)

        for path in rewrite_sidecars:
            progress.update(task, description=f"Rewriting sidecar {path.name}")
            _merge_report(summary.file_report, rewrite_payload_report(path, plan))
            progress.advance(task)

        for path in rewrite_text_files:
            progress.update(task, description=f"Rewriting file {path.name}")
            _merge_report(summary.file_report, rewrite_payload_report(path, plan))
            progress.advance(task)

    if apply and _propagate_hashes:
        if summary.hash_changes:
            _phase(
                console,
                f"Refreshing {len(media_states)} media identities before targeted lineage propagation.",
            )
            with _new_progress(console) as refresh_progress:
                refresh_task = refresh_progress.add_task(
                    "Loading current media identities into RAM", total=None
                )
                latest_references = discover_media_references(databases)
                _refresh_media_group_states(media_states, latest_references)
                refresh_progress.update(
                    refresh_task,
                    description=f"Loaded {len(latest_references)} current media identities",
                )
            summary.hash_changes = _propagate_media_lineage(
                media_states,
                summary.hash_changes,
                console=console,
                summary=summary,
            )

            hash_plan = FingerprintReplacementPlan(summary.hash_changes)
            hash_keys = set(summary.hash_changes)
            hash_file_candidates = [
                path for path in [*associated_sidecars, *standalone_text_files]
                if preflight_summary is not None
                and preflight_summary.file_report.hash_references.get(str(path), set())
                & hash_keys
            ]
            _phase(
                console,
                f"Applying {len(summary.hash_changes)} finalized fingerprint remaps to "
                f"{len(databases)} DBs and {len(hash_file_candidates)} text/sidecar files.",
            )
            with _new_progress(console) as hash_progress:
                hash_total = len(databases) + len(hash_file_candidates)
                hash_task = hash_progress.add_task(
                    "Updating persisted lineage fingerprints", total=hash_total
                )
                for database in databases:
                    hash_progress.update(
                        hash_task,
                        description=f"Updating lineage in database {database.name}",
                    )
                    rewrite_database(database, hash_plan, vacuum=False)
                    hash_progress.advance(hash_task)
                for path in hash_file_candidates:
                    hash_progress.update(
                        hash_task,
                        description=f"Updating lineage in {path.name}",
                    )
                    report = rewrite_payload_report(path, hash_plan)
                    summary.file_report.errors.extend(report.errors)
                    hash_progress.advance(hash_task)
        else:
            _phase(console, "No media payload hashes changed; lineage propagation is unnecessary.")

    if apply and _vacuum_after:
        _phase(console, f"Vacuuming {len(databases)} databases to remove obsolete pages.")
        with _new_progress(console) as vacuum_progress:
            vacuum_task = vacuum_progress.add_task("Vacuuming databases", total=len(databases))
            for database in databases:
                vacuum_progress.update(vacuum_task, description=f"Vacuuming {database.name}")
                vacuum_database(database)
                vacuum_progress.advance(vacuum_task)

    if apply:
        verification_plan: ReplacementPlan = plan
        if summary.hash_changes:
            verification_plan = CompositeReplacementPlan([
                plan,
                FingerprintReplacementPlan(summary.hash_changes),
            ])
        _phase(console, "Final verification: one exhaustive parallel scan, with visible progress.")
        verification = run_rewrite(
            data_dir,
            verification_plan,
            apply=False,
            include_external_media=include_external_media,
            console=console,
            workers=workers,
        )
        summary.file_report.errors.extend(verification.file_report.errors)
        summary.file_report.errors = sorted(set(summary.file_report.errors))
        if verification.occurrences:
            raise RewriteError(
                f"Final verification found {verification.occurrences} remaining matches"
            )
        _phase(console, "Final verification complete: zero readable matches remain.")
    return summary


def _print_summary(console: Console, summary: RewriteSummary, *, apply: bool) -> None:
    table = Table(title="Prompt history rewrite" if apply else "Prompt history rewrite dry run")
    table.add_column("Surface")
    table.add_column("Location")
    table.add_column("Values", justify="right")
    table.add_column("Occurrences", justify="right")
    for surface, report in (
        ("database", summary.database_report),
        ("file/media", summary.file_report),
    ):
        for item in report.locations:
            table.add_row(surface, item.location, str(item.values), str(item.occurrences))
    if not summary.occurrences:
        table.add_row("—", "No matches", "0", "0")
    console.print(table)
    verb = "Replaced" if apply else "Would replace"
    console.print(f"{verb} [bold]{summary.occurrences}[/bold] occurrences.")
    warnings = sorted(set(summary.database_report.errors + summary.file_report.errors))
    if warnings:
        console.print(
            f"[yellow]Skipped {len(warnings)} unreadable/corrupt file"
            f"{'s' if len(warnings) != 1 else ''}:[/yellow]"
        )
        for warning in warnings[:20]:
            console.print(f"  [yellow]•[/yellow] {warning}")
        if len(warnings) > 20:
            console.print(f"  … and {len(warnings) - 20} more")
    if apply:
        if warnings:
            console.print(
                "[yellow]Final verification passed for every readable surface; "
                "skipped corrupt files could not be verified.[/yellow]"
            )
        else:
            console.print(
                "[green]Final verification passed: zero target terms remain in scanned surfaces.[/green]"
            )
    else:
        console.print("Dry run only. Re-run with --apply --yes to perform the rewrite.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rewrite prompt/history text in every sandbox database and associated media metadata."
    )
    parser.add_argument("--data-dir", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument(
        "--replace", nargs=2, action="append", metavar=("OLD", "NEW"), required=True,
        help="Literal replacement pair; repeat for multiple terms",
    )
    parser.add_argument("--ignore-case", action="store_true", help="Match OLD terms case-insensitively")
    parser.add_argument("--apply", action="store_true", help="Perform the rewrite (default: dry run)")
    parser.add_argument("--yes", action="store_true", help="Confirm the destructive apply operation")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_SCAN_WORKERS,
        help=f"Parallel read-only scan workers (default: {DEFAULT_SCAN_WORKERS})",
    )
    parser.add_argument(
        "--no-external-media", action="store_true",
        help="Do not modify media or editor sidecars outside the Stimma sandbox",
    )
    parser.add_argument(
        "--backup-dir", type=Path,
        help="Optional rollback copy; it intentionally retains the original terms",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(stderr=True)
    if args.apply and not args.yes:
        parser.error("--apply requires --yes")
    if not args.apply and args.backup_dir:
        parser.error("--backup-dir is only valid with --apply")
    try:
        plan = ReplacementPlan(
            [Rule(old, new) for old, new in args.replace],
            ignore_case=args.ignore_case,
        )
        summary = run_rewrite(
            args.data_dir,
            plan,
            apply=args.apply,
            include_external_media=not args.no_external_media,
            backup_dir=args.backup_dir,
            console=console,
            workers=args.workers,
        )
        _print_summary(console, summary, apply=args.apply)
        return 0
    except (OSError, RewriteError, sqlite3.Error, zlib.error) as exc:
        console.print(f"[red]Rewrite failed:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

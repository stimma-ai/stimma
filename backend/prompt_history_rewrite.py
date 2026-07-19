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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import piexif
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table


SQLITE_HEADER = b"SQLite format 3\x00"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8"
IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png"}
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


@dataclass
class LocationResult:
    location: str
    occurrences: int
    values: int = 1


@dataclass
class ScanReport:
    locations: list[LocationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

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
    return sorted(path for path in data_dir.rglob("*") if path.is_file() and _is_sqlite(path))


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
            lowered = column_name.lower()
            structural = (
                lowered in STRUCTURAL_COLUMN_NAMES
                or lowered.endswith(STRUCTURAL_COLUMN_SUFFIXES)
            )
            if hidden == 0 and not structural:
                yield table_name, column_name


def _database_value_text(value: object) -> tuple[str, bool] | None:
    if isinstance(value, str):
        return value, False
    if isinstance(value, bytes) and b"\x00" not in value:
        try:
            return value.decode("utf-8"), True
        except UnicodeDecodeError:
            return None
    return None


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
            if offset != len(data):
                raise RewriteError("Unexpected bytes after PNG IEND")
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


def _payload_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    digest.update(b"stimma-directory-v1\x00")
    for candidate in sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    ):
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
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
            data = candidate.read_bytes()
            _rewritten, count = rewrite_payload_bytes(data, candidate, plan)
            total += count
        except (OSError, RewriteError, zlib.error):
            raise
    return total


def rewrite_payload(path: Path, plan: ReplacementPlan) -> int:
    total = 0
    for candidate in _payload_files(path):
        data = candidate.read_bytes()
        rewritten, count = rewrite_payload_bytes(data, candidate, plan)
        if count:
            _write_in_place(candidate, rewritten)
            total += count
    remaining = scan_payload(path, plan)
    if remaining:
        raise RewriteError(f"Verification found {remaining} matches in media payload {path}")
    return total


def _write_in_place(path: Path, data: bytes) -> None:
    # In-place replacement deliberately preserves hard links used by managed
    # compatibility paths.  A temporary sibling still ensures all bytes are
    # prepared and fsynced before the short truncate/write window.
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rewrite-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with path.open("r+b") as destination, temporary.open("rb") as source:
            destination.seek(0)
            shutil.copyfileobj(source, destination, 1024 * 1024)
            destination.truncate()
            destination.flush()
            os.fsync(destination.fileno())
    finally:
        temporary.unlink(missing_ok=True)


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


def run_rewrite(
    data_dir: Path,
    plan: ReplacementPlan,
    *,
    apply: bool,
    include_external_media: bool = True,
    backup_dir: Path | None = None,
    console: Console | None = None,
    _preflight: bool = True,
    _propagate_hashes: bool = True,
    _vacuum_after: bool = True,
) -> RewriteSummary:
    console = console or Console()
    data_dir = data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        raise RewriteError(f"Stimma data directory not found: {data_dir}")

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

    associated_sidecars = {
        Path(f"{reference.file_path}.stimmaedit.json")
        for reference in references
        if Path(f"{reference.file_path}.stimmaedit.json").exists()
    }

    if apply and _preflight:
        # Do a complete parse/read pass and prove all database locks before the
        # first mutation.  This catches corrupt metadata, permissions failures,
        # and a still-running backend without leaving a half-rewritten sandbox.
        with open(os.devnull, "w") as sink:
            run_rewrite(
                data_dir,
                plan,
                apply=False,
                include_external_media=include_external_media,
                console=Console(file=sink),
            )
        assert_databases_writable(databases)

    summary = RewriteSummary()
    total_steps = len(databases) + len(media_groups) + len(text_files)
    progress = Progress(
        SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
        MofNCompleteColumn(), console=console, transient=False,
    )

    if apply and backup_dir:
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
        backup_databases(databases, data_dir=data_dir, backup_dir=resolved_backup_dir)
        backup_files(backup_sources, data_dir=data_dir, backup_dir=resolved_backup_dir)

    with progress:
        task = progress.add_task("Scanning" if not apply else "Rewriting", total=total_steps)
        for database in databases:
            progress.update(task, description=f"{'Rewriting' if apply else 'Scanning'} {database.name}")
            report = (
                rewrite_database(database, plan, vacuum=False)
                if apply else scan_database(database, plan)
            )
            summary.database_report.locations.extend(report.locations)
            progress.advance(task)

        processed_sidecars: set[Path] = set()
        for path, refs in media_groups:
            progress.update(task, description=f"{'Rewriting' if apply else 'Scanning'} media {path.name}")
            count = rewrite_payload(path, plan) if apply else scan_payload(path, plan)
            if count:
                summary.file_report.add(str(path), count)
                if apply:
                    new_hash = _payload_hash(path)
                    new_size = _payload_size(path)
                    for reference in refs:
                        if reference.file_hash and reference.file_hash != new_hash:
                            summary.hash_changes[reference.file_hash] = new_hash
                    _update_media_identity(refs, path, new_hash, new_size)
            # External editor sidecars are not necessarily below data_dir.
            for ref in refs:
                sidecar = Path(f"{ref.file_path}.stimmaedit.json")
                resolved_sidecar = sidecar.resolve(strict=False)
                if resolved_sidecar in processed_sidecars:
                    continue
                if not include_external_media and data_dir not in sidecar.resolve(strict=False).parents:
                    continue
                if sidecar.exists():
                    sidecar_count = rewrite_payload(sidecar, plan) if apply else scan_payload(sidecar, plan)
                    summary.file_report.add(str(sidecar), sidecar_count)
                    processed_sidecars.add(resolved_sidecar)
            progress.advance(task)

        media_paths = {
            candidate.resolve(strict=False)
            for path, _refs in media_groups for candidate in _payload_files(path)
        } | processed_sidecars
        for path in text_files:
            progress.update(task, description=f"{'Rewriting' if apply else 'Scanning'} {path.name}")
            if path.resolve(strict=False) not in media_paths:
                count = rewrite_payload(path, plan) if apply else scan_payload(path, plan)
                summary.file_report.add(str(path), count)
            progress.advance(task)

    if apply and _propagate_hashes:
        pending_hash_changes = dict(summary.hash_changes)
        # Rewriting an ancestor fingerprint changes the descendant payload's
        # hash, so propagation is iterative.  Media lineage is a DAG; the guard
        # is a fail-closed defense against corrupt cyclic provenance.
        for _iteration in range(100):
            pending_hash_changes = {
                old: new for old, new in pending_hash_changes.items() if old != new
            }
            if not pending_hash_changes:
                break
            if _iteration == 0:
                console.print("Propagating rewritten media fingerprints through lineage…")
            hash_plan = ReplacementPlan(
                [Rule(old, new) for old, new in pending_hash_changes.items()]
            )
            with open(os.devnull, "w") as sink:
                propagation = run_rewrite(
                    data_dir,
                    hash_plan,
                    apply=True,
                    include_external_media=include_external_media,
                    console=Console(file=sink),
                    _preflight=False,
                    _propagate_hashes=False,
                    _vacuum_after=False,
                )
            summary.hash_changes.update(propagation.hash_changes)
            pending_hash_changes = propagation.hash_changes
        else:
            raise RewriteError("Media fingerprint propagation did not converge")

    if apply and _vacuum_after:
        with Progress(
            SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
            MofNCompleteColumn(), console=console, transient=False,
        ) as vacuum_progress:
            vacuum_task = vacuum_progress.add_task("Vacuuming databases", total=len(databases))
            for database in databases:
                vacuum_progress.update(vacuum_task, description=f"Vacuuming {database.name}")
                vacuum_database(database)
                vacuum_progress.advance(vacuum_task)

    if apply:
        with open(os.devnull, "w") as sink:
            verification = run_rewrite(
                data_dir,
                plan,
                apply=False,
                include_external_media=include_external_media,
                console=Console(file=sink),
            )
        if verification.occurrences:
            raise RewriteError(
                f"Final verification found {verification.occurrences} remaining matches"
            )
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
    if apply:
        console.print("[green]Final verification passed: zero target terms remain in scanned surfaces.[/green]")
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
        )
        _print_summary(console, summary, apply=args.apply)
        return 0
    except (OSError, RewriteError, sqlite3.Error, zlib.error) as exc:
        console.print(f"[red]Rewrite failed:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Program version tracking for flow rollback.

Each flow directory gets a ``versions/`` subdirectory. Every time the
agent writes a successful program, we snapshot it here:

    <flow_dir>/versions/
    ├── manifest.jsonl    # one record per line: {hash, timestamp, note}
    ├── <hash1>.py        # exact program bytes
    ├── <hash2>.py
    └── ...

Manifest is append-only JSONL so concurrent writes (agent + file watcher)
don't trample it. Rollback resolves a hash to a file and copies it back
into ``program.py``.

This is deliberately file-based rather than SQLite: versions are just
files, the manifest gives chronology, and git-style ``diff`` tools can
operate on them if needed. Heavy operations (pruning, compaction) are
deferred — the expected version count per flow is small (tens, not
thousands).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)


@dataclass
class ProgramVersionRecord:
    hash: str
    timestamp: str
    note: str = ""
    is_good: bool = True  # False = program failed to parse; kept for audit

    def to_dict(self) -> dict:
        return {
            "hash": self.hash,
            "timestamp": self.timestamp,
            "note": self.note,
            "is_good": self.is_good,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProgramVersionRecord":
        return cls(
            hash=data["hash"],
            timestamp=data["timestamp"],
            note=data.get("note", ""),
            is_good=bool(data.get("is_good", True)),
        )


class ProgramVersionStore:
    """File-backed history of program.py for a single flow.

    The program file itself remains the source of truth; the store snapshots
    it and lets the caller roll back to a previous snapshot.
    """

    MANIFEST = "manifest.jsonl"
    VERSIONS_DIR = "versions"

    def __init__(self, flow_dir: Path) -> None:
        self.flow_dir = Path(flow_dir)
        self.versions_dir = self.flow_dir / self.VERSIONS_DIR

    # ----- internal helpers ---------------------------------------------

    def _ensure_dir(self) -> None:
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self) -> Path:
        return self.versions_dir / self.MANIFEST

    def _version_path(self, version_hash: str) -> Path:
        return self.versions_dir / f"{version_hash}.py"

    @staticmethod
    def _hash_source(source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    # ----- public API ----------------------------------------------------

    def program_path(self) -> Path:
        """Absolute path of the flow's current program.py."""
        return self.flow_dir / "program.py"

    def record(self, source: str, *, note: str = "", is_good: bool = True) -> ProgramVersionRecord:
        """Snapshot ``source`` and append a manifest record.

        If a version with the same hash already exists, the manifest still
        gets a new row (so we can distinguish "rolled back to" vs. "wrote
        the same thing again") but the file is only written once.
        """
        self._ensure_dir()
        version_hash = self._hash_source(source)
        target = self._version_path(version_hash)
        if not target.exists():
            target.write_text(source)
        record = ProgramVersionRecord(
            hash=version_hash,
            timestamp=datetime.utcnow().isoformat(),
            note=note,
            is_good=is_good,
        )
        with self._manifest_path().open("a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")
        return record

    def list_versions(self) -> list[ProgramVersionRecord]:
        """Return manifest entries in chronological order."""
        if not self._manifest_path().exists():
            return []
        out: list[ProgramVersionRecord] = []
        for line in self._manifest_path().read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(ProgramVersionRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning(f"ignoring malformed version manifest row: {exc}")
        return out

    def latest_good(self) -> Optional[ProgramVersionRecord]:
        """Most recent manifest row with ``is_good=True``."""
        for record in reversed(self.list_versions()):
            if record.is_good:
                return record
        return None

    def get_source(self, version_hash: str) -> Optional[str]:
        path = self._version_path(version_hash)
        if not path.exists():
            return None
        return path.read_text()

    def rollback_to(self, version_hash: str, *, note: str = "") -> ProgramVersionRecord:
        """Overwrite program.py with the contents of ``version_hash``.

        Records a new manifest entry noting the rollback so the history is
        append-only. Raises FileNotFoundError if the version isn't stored.
        """
        source = self.get_source(version_hash)
        if source is None:
            raise FileNotFoundError(
                f"version {version_hash!r} not found in {self.versions_dir}"
            )
        program_path = self.program_path()
        program_path.parent.mkdir(parents=True, exist_ok=True)
        program_path.write_text(source)
        record_note = note or f"rolled back to {version_hash[:12]}"
        return self.record(source, note=record_note, is_good=True)

    def rollback_to_latest_good(self, *, note: str = "") -> Optional[ProgramVersionRecord]:
        """Convenience: rollback to the most recent known-good version."""
        latest = self.latest_good()
        if latest is None:
            return None
        return self.rollback_to(latest.hash, note=note or "rollback to last good version")

    # ----- snapshotting helpers -----------------------------------------

    def snapshot_current(self, *, note: str = "", is_good: bool = True) -> Optional[ProgramVersionRecord]:
        """Record the current program.py contents. Returns None if missing."""
        path = self.program_path()
        if not path.exists():
            return None
        return self.record(path.read_text(), note=note, is_good=is_good)


def get_version_store(flow_dir: Path) -> ProgramVersionStore:
    return ProgramVersionStore(flow_dir)

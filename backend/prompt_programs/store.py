"""Prepared programs, cached on disk by the inputs that produced them.

A prompt's entry is keyed by everything that shaped it (slots.prepare: the prompt as read,
the reader's version and model, the vocabulary). Asking again with the same inputs never calls
the model. Entries are small JSON files (a vocabulary list in one is a reference to the
list, never a copy: compact.py); nothing is deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

_KEY = re.compile(r"[0-9a-f]{32}")   # what program_key() makes; keys also arrive from clients


def valid_key(key: Any) -> bool:
    return isinstance(key, str) and _KEY.fullmatch(key) is not None


def program_key(parts: Dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class ProgramStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not valid_key(key):  # never a path out of the store
            raise ValueError(f"not a program key: {key!r}")
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not valid_key(key):
            return None
        p = self._path(key)
        try:
            entry = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        from prompt_programs.compact import unpack_entry
        if not isinstance(entry, dict):
            return None
        return unpack_entry(entry)   # its vocabulary lists are stored by reference (compact.py)

    def put(self, key: str, entry: Dict[str, Any]) -> None:
        from prompt_programs.compact import pack_entry
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(pack_entry(entry), f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

"""Prepared programs, cached on disk by the inputs that produced them.

A program is keyed by everything that shaped it (prompt source, tool, the LoRAs the
prompt named, parameter names, and the instructions version). Asking again with the
same inputs never calls the model. Entries are small JSON files; nothing is deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


def program_key(parts: Dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class ProgramStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        p = self._path(key)
        try:
            return json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, entry: Dict[str, Any]) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

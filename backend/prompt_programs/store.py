"""Prepared programs, cached on disk by the inputs that produced them.

A program is keyed by everything that shaped it (prompt source, tool, the LoRAs the
prompt named, parameter names, and the instructions version). Asking again with the
same inputs never calls the model. Entries are small JSON files; nothing is deleted.

Each editing context (everything in the key except the prompt) also remembers its most
recent programs, so a small edit to a prompt can patch the program it came from.

The writer's session log lives beside the entries as immutable nodes (sessions/<id>.json):
each node holds the messages one prepare added and its parent's id, so an entry's full log
is its node's parent chain. An entry points at its node; regenerating an entry writes a new
node and moves the pointer, never rewriting a node another entry continues from.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

RECENT = 8
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
        from prompt_programs.runtime import current_entry
        return current_entry(entry)   # an older build's choice ids, read as today's

    def put(self, key: str, entry: Dict[str, Any]) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)

    def _recent_path(self, context: str) -> Path:
        if not valid_key(context):
            raise ValueError(f"not a program context: {context!r}")
        return self.root / "recent" / f"{context}.json"

    def recent(self, context: str) -> List[str]:
        """Keys of this context's latest programs, newest first."""
        if not valid_key(context):
            return []
        try:
            keys = json.loads(self._recent_path(context).read_text("utf-8"))
        except (OSError, ValueError):
            return []
        return [k for k in keys if valid_key(k)] if isinstance(keys, list) else []

    def remember(self, context: str, key: str) -> None:
        keys = [key, *(k for k in self.recent(context) if k != key)][:RECENT]
        p = self._recent_path(context)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(keys, f)
        os.replace(tmp, p)

    # ------------------------------------------------------------------ by prompt text

    def _text_path(self, text_key: str) -> Path:
        if not valid_key(text_key):
            raise ValueError(f"not a text key: {text_key!r}")
        return self.root / "texts" / f"{text_key}.json"

    def texts(self, text_key: str) -> List[str]:
        """Keys of the latest programs prepared for one prompt text (under any settings), newest first."""
        if not valid_key(text_key):
            return []
        try:
            keys = json.loads(self._text_path(text_key).read_text("utf-8"))
        except (OSError, ValueError):
            return []
        return [k for k in keys if valid_key(k)] if isinstance(keys, list) else []

    def remember_text(self, text_key: str, key: str) -> None:
        keys = [key, *(k for k in self.texts(text_key) if k != key)][:RECENT]
        p = self._text_path(text_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(keys, f)
        os.replace(tmp, p)

    # ------------------------------------------------------------------ session nodes

    def _node_path(self, node_id: str) -> Path:
        return self.root / "sessions" / node_id[:2] / f"{node_id}.json"

    def get_node(self, node_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not valid_key(node_id):  # uuid4().hex, like a program key
            return None
        try:
            node = json.loads(self._node_path(node_id).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return node if isinstance(node, dict) and node.get("id") == node_id else None

    def put_node(self, node: Dict[str, Any]) -> str:
        """Write a new node and return its id. Nodes are never rewritten."""
        node_id = uuid.uuid4().hex
        node = {**node, "id": node_id}
        p = self._node_path(node_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(node, f, ensure_ascii=False)
        os.replace(tmp, p)
        return node_id

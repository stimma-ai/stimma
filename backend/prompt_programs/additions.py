"""The user's own options for a vocabulary list, kept for every later prompt.

A choice bound to a vocabulary list (a hairstyle, an outfit) lets the user add an option of
their own. That addition is kept here, per profile and per list, so every later choice bound
to the same list, in any prompt and any tool, offers it again. A choice whose options were
written for one prompt has no list, so nothing names it across prompts: its additions stay
with that prompt (the `add` edits a client holds), as they always have.

How a kept addition is drawn (options.GeneratedOptions._read_bound):
- It is an option like one typical value of the list: the same weight, never more, so a
  few additions don't crowd out a long list and a draw of one is no surprise.
- A choice narrowed by the user's words (where=) or standing for a value they stated
  (said=) offers it but draws it only once ticked: the words decide what is drawn.
- The age list's additions are drawn only once ticked, like its bands under 18: no age is
  drawn unasked in a prompt that didn't ask for it (MINORS_POLICY in the notes).
- Like an option just added in the card, it is never left out for a person under 18 and
  never rerolled by the fit check.

The list's id (`person.hairstyle`) is what an addition is kept under: the id the program
binds and records, the same across vocabulary versions. A list a later vocabulary no longer
has keeps its additions on disk, unused. A palette (a look's Colors) takes no additions:
its schemes carry the colors a look is filled with, which a typed option has none of.
Nothing here touches a program's key: additions are read when pools are built.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional

MAX_TEXT = 300           # longer is not an option, it's a paragraph
FILE = "additions.json"
_FORMAT = 1


def _norm(s: str) -> str:   # as options._norm: one option, however it was spaced or capitalized
    return re.sub(r"\s+", " ", str(s).strip().lower())


def clean_text(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def list_id(cls: object) -> Optional[str]:
    """The vocabulary list an addition for `cls` is kept under, or None when it takes none
    (not a list, or a palette)."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    leaf = vocab.resolve(str(cls or "").strip()) if cls else None
    if leaf is None or any(other.slots == leaf.id for other in vocab.leaves.values()):
        return None
    return leaf.id


class AdditionStore:
    """{list id: [the user's options, oldest first]} in one small JSON file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> Dict[str, List[str]]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        lists = data.get("lists") if isinstance(data, dict) else None
        if not isinstance(lists, dict):
            return {}
        return {str(k): [str(x) for x in v if isinstance(x, str) and x.strip()]
                for k, v in lists.items() if isinstance(v, list)}

    def _write(self, lists: Dict[str, List[str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"format": _FORMAT, "lists": {k: v for k, v in sorted(lists.items()) if v}},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def lists(self) -> Dict[str, List[str]]:
        return self._read()

    def of(self, lid: str) -> List[str]:
        return list(self._read().get(lid, []))

    def add(self, lid: str, text: str) -> bool:
        """Keep one option for a list. False when it was already kept."""
        text = clean_text(text)
        if not text:
            return False
        with self._lock:
            lists = self._read()
            have = lists.setdefault(lid, [])
            if any(_norm(x) == _norm(text) for x in have):
                return False
            have.append(text)
            del have[:-MAX_PER_LIST]  # a list keeps its newest: the oldest make room
            self._write(lists)
            return True

    def remove(self, lid: str, text: str) -> bool:
        """Forget one option of a list. False when it wasn't kept."""
        with self._lock:
            lists = self._read()
            have = lists.get(lid, [])
            left = [x for x in have if _norm(x) != _norm(text)]
            if len(left) == len(have):
                return False
            lists[lid] = left
            self._write(lists)
            return True

    def version(self) -> str:
        """A short hash of what is kept: a draw made before an addition is never served after it."""
        blob = json.dumps(self._read(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


MAX_PER_LIST = 500

_stores: Dict[str, AdditionStore] = {}


def additions_for(profile_id: Optional[str]) -> AdditionStore:
    """The profile's store, beside its prepared programs."""
    import app_dirs
    from core.profile_context import get_current_profile
    path = app_dirs.get_profile_dir(profile_id or get_current_profile()) / "prompt_programs" / FILE
    s = _stores.get(str(path))
    if s is None:
        s = _stores[str(path)] = AdditionStore(path)
    return s


def profile_additions(profile_id: Optional[str]) -> Dict[str, List[str]]:
    """What a draw for this profile offers, never raising: no profile (scripts) keeps none."""
    try:
        return additions_for(profile_id).lists()
    except Exception:
        return {}


__all__ = ["AdditionStore", "MAX_TEXT", "additions_for", "clean_text", "list_id", "profile_additions"]

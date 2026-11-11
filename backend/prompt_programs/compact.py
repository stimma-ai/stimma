"""What is stored about a vocabulary list is a reference to it, never a copy of it.

A prepared program's choices and filters, and a draw's recorded pools, name values of the
vocabulary's lists. Written out, a list of 3,000 faces is 300 KB: per person, per program,
and (in a draw's revision) per image. So:

- **A prepared program** (store.py) keeps, for a choice's options or a pick's filter that is
  values of one list in the list's order, a reference: the list, the vocabulary version, and
  which values by position ({"all": true}, or the shorter of "only" and "without"). It is
  written out again when the program is read, so nothing that reads a program changes. Read
  under another vocabulary version (only a replay or "use these choices" of an older image
  reaches such a program, and a replay draws from its revision's pools, not from these), a
  choice shows the list as it is now and a filter is dropped.

- **A draw's revision** (draws.py) records each vocabulary pool as the hash of its exact
  contents, and the contents are kept once, beside the generated options (`PoolStore`): every
  image drawn from the same pool shares one copy. A replay reads the pool back by its hash,
  so it stays exact when the vocabulary changes. A pool that can't be found says so; an older
  revision's pools, written out in full, still replay.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REF = "$list"       # a packed list of values: {"$list": id, "$vocab": version, "all" | "only" | "without": ...}
POOL = "$pool"      # a recorded pool by reference: {"$pool": hash, "n": how many values}


# --------------------------------------------------------------------------- values of a list

def pack_values(cls: Optional[str], values: Any) -> Any:
    """`values` as a reference to the list `cls`, when they are values of it in its order (a
    subset keeps the list's order: narrowing and discovery both do). Anything else is returned
    as it is."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    leaf = vocab.get(cls)
    if leaf is None or not isinstance(values, list) or len(values) < 8 or not all(isinstance(v, str) for v in values):
        return values
    index = {v.text: i for i, v in enumerate(leaf.values)}
    at = [index.get(v, -1) for v in values]
    if any(i < 0 for i in at) or any(b <= a for a, b in zip(at, at[1:])):
        return values
    ref: Dict[str, Any] = {REF: leaf.id, "$vocab": vocab.version}
    if len(at) == len(leaf.values):
        return {**ref, "all": True}
    without = sorted(set(range(len(leaf.values))) - set(at))
    return {**ref, **({"without": without} if len(without) < len(at) else {"only": at})}


def is_ref(value: Any) -> bool:
    return isinstance(value, dict) and REF in value


def unpack_values(ref: Any) -> Optional[List[str]]:
    """The values a reference names, or None when the vocabulary has changed since (or no
    longer has the list): the caller says what stands in then."""
    from prompt_programs.vocab import vocabulary
    if not is_ref(ref):
        return ref
    vocab = vocabulary()
    leaf = vocab.get(ref.get(REF))
    if leaf is None or ref.get("$vocab") != vocab.version:
        return None
    texts = [v.text for v in leaf.values]
    try:
        if ref.get("all"):
            return texts
        if "only" in ref:
            return [texts[i] for i in ref["only"]]
        gone = set(ref.get("without") or ())
        return [t for i, t in enumerate(texts) if i not in gone]
    except (IndexError, TypeError):
        return None


def pack_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """A prepared program as it is stored: its vocabulary lists by reference."""
    out = dict(entry)
    cls = {c.get("id"): c.get("cls") for c in entry.get("choices") or [] if isinstance(c, dict)}
    if isinstance(entry.get("choices"), list):
        out["choices"] = [{**c, "options": pack_values(c.get("cls"), c.get("options"))} if isinstance(c, dict) and c.get("cls")
                          else c for c in entry["choices"]]
    if isinstance(entry.get("filters"), dict):
        pending = entry.get("narrow_pending") if isinstance(entry.get("narrow_pending"), dict) else {}
        out["filters"] = {k: pack_values(cls.get(k) or (pending.get(k) or {}).get("cls"), v) for k, v in entry["filters"].items()}
    if isinstance(entry.get("narrow_pending"), dict):
        out["narrow_pending"] = {k: {**p, "options": pack_values(p.get("cls"), p.get("options"))} if isinstance(p, dict) else p
                                 for k, p in entry["narrow_pending"].items()}
    return out


def unpack_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """A stored program written out again. Under another vocabulary version a choice shows its
    list as it is now, and a filter the references can't name is dropped (module docstring)."""
    from prompt_programs.vocab import vocabulary

    def now(cls: Any) -> List[str]:
        leaf = vocabulary().get(cls)
        return [v.text for v in leaf.values if not v.opt_in] if leaf is not None else []
    out = dict(entry)
    if isinstance(entry.get("choices"), list):
        out["choices"] = [{**c, "options": got if (got := unpack_values(c["options"])) is not None else now(c.get("cls"))}
                          if isinstance(c, dict) and is_ref(c.get("options")) else c for c in entry["choices"]]
    if isinstance(entry.get("filters"), dict):
        out["filters"] = {k: got for k, v in entry["filters"].items() if (got := unpack_values(v)) is not None}
    if isinstance(entry.get("narrow_pending"), dict):
        out["narrow_pending"] = {
            k: {**p, "options": got if (got := unpack_values(p["options"])) is not None else now(p.get("cls"))}
            if isinstance(p, dict) and is_ref(p.get("options")) else p for k, p in entry["narrow_pending"].items()}
    return out


# --------------------------------------------------------------------------- recorded pools

class PoolStore:
    """Recorded pools, each kept once under the hash of its contents (gzipped JSON). Nothing is
    rewritten or deleted: a revision that names a pool can always read it back."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, digest: str) -> Path:
        if not (isinstance(digest, str) and len(digest) == 32 and all(c in "0123456789abcdef" for c in digest)):
            raise ValueError(f"not a pool hash: {digest!r}")
        return self.root / digest[:2] / f"{digest}.json.gz"

    def put(self, pool: Sequence[Any]) -> Dict[str, Any]:
        """Keep a pool ([[value, weight, roles?], ...]) and return the reference a revision records."""
        blob = json.dumps(pool, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()[:32]
        p = self._path(digest)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(gzip.compress(blob, mtime=0))
            os.replace(tmp, p)
        return {POOL: digest, "n": len(pool)}

    def get(self, ref: Any) -> Optional[List[Any]]:
        try:
            pool = json.loads(gzip.decompress(self._path(ref[POOL]).read_bytes()).decode("utf-8"))
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            return None
        return pool if isinstance(pool, list) else None


def is_pool_ref(value: Any) -> bool:
    return isinstance(value, dict) and POOL in value


__all__ = ["POOL", "PoolStore", "is_pool_ref", "is_ref", "pack_entry", "pack_values", "unpack_entry", "unpack_values"]

"""The vocabulary: curated lists a program binds picks to with `cls=`.

    eyes = pick("eyes", cls="person.eye_color", about="her eye colour", seed=["hazel"], ...)

The vocabulary is a tree. An inner node (`person`, `person.outfit`) has a one-line
description; a leaf is a list of values of one part of speech, each with a typicality
tier and optional facet tags (genre, era, region...). The directory layout under
`vocab/` is the tree: `vocab/person/outfit/casual.json` is `person.outfit.casual`, and
each inner node has a `_node.json`.

A bound pick draws from its leaf instead of from options a model wrote. A **closed** leaf
(eye colour, skin tone, shot size) is the whole pool: small natural sets, where generated
options go weird too often. An **open** leaf (expressions, outfits, places) is a backbone
that generation extends: the options generator gets a spread of the leaf's values as its
examples, so a finite list never becomes everyone's only choices.

Facets filter values by context. A value's tags list the facet values it fits; a leaf's
`untagged` says what a value with no tag fits; facets without either fit everything.
Programs don't set facets yet, so every pool uses the context defaults (genre realistic,
era contemporary).

More roots can be added (a stimpack's vocabulary); ids must not collide.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).parent / "vocab"
TIER_WEIGHTS = {"typical": 1.0, "plausible": 0.3, "unusual": 0.03}
OPEN_SHARE = 0.5      # an open leaf's list values' share of its pool's weight once generated options exist
EXAMPLES = 10         # list values shown to the options generator for an open leaf
CATALOGUE_ROOTS = ("person",)
TYPO_CUTOFF = 0.85    # difflib ratio above which an unknown id is read as a typo of a known one   # what the writer is shown; the rest waits for an open() tool


@dataclass(frozen=True)
class Value:
    text: str
    tier: str
    tags: Dict[str, Any] = field(default_factory=dict)

    @property
    def weight(self) -> float:
        return TIER_WEIGHTS.get(self.tier, TIER_WEIGHTS["plausible"])


@dataclass(frozen=True)
class Leaf:
    id: str
    label: str
    description: str
    pos: str
    frame: str
    notes: str
    facets: Tuple[str, ...]
    closed: bool
    untagged: Dict[str, Tuple[str, ...]]
    values: Tuple[Value, ...]

    def fits(self, value: Value, context: Dict[str, str]) -> bool:
        for f, want in context.items():
            fits = value.tags.get(f, self.untagged.get(f, "any"))
            if fits != "any" and want not in fits:
                return False
        return True

    def eligible(self, context: Optional[Dict[str, str]] = None) -> List[Value]:
        """The values that fit a context (unset facets take their defaults)."""
        ctx = {**vocabulary().defaults, **(context or {})}
        return [v for v in self.values if self.fits(v, ctx)]

    def examples(self, key: str, context: Optional[Dict[str, str]] = None, n: int = EXAMPLES) -> List[str]:
        """A spread of eligible values for the options generator: one per tier and tag
        combination first, then at random, seeded by `key` so a pool's examples are stable."""
        vals = list(self.eligible(context))
        random.Random(key).shuffle(vals)
        out: List[str] = []
        kinds = set()
        for v in vals:
            kind = (v.tier, json.dumps(v.tags, sort_keys=True))
            if kind not in kinds:
                kinds.add(kind)
                out.append(v.text)
            if len(out) >= n:
                return out
        out += [v.text for v in vals if v.text not in out][: n - len(out)]
        return out


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    description: str


@dataclass
class Vocabulary:
    nodes: Dict[str, Node]
    leaves: Dict[str, Leaf]
    facets: Dict[str, Dict[str, Any]]
    version: str

    @property
    def defaults(self) -> Dict[str, str]:
        return {f: spec["default"] for f, spec in self.facets.items() if spec.get("default")}

    def get(self, cls: Optional[str]) -> Optional[Leaf]:
        return self.leaves.get(str(cls or "").strip())

    def resolve(self, cls: Optional[str]) -> Optional[Leaf]:
        """The leaf an id names, allowing a near-certain typo ("person.eye_eye_color"):
        writers garble ids now and then, and a repair round costs more than the guess."""
        leaf = self.get(cls)
        if leaf is None and cls:
            import difflib
            near = difflib.get_close_matches(str(cls).strip(), list(self.leaves), n=1, cutoff=TYPO_CUTOFF)
            leaf = self.leaves[near[0]] if near else None
        return leaf

    def catalogue(self, roots: Sequence[str] = CATALOGUE_ROOTS) -> str:
        """The lists the writer may bind to, one line each: id, part of speech, where a
        value fits, what it's for. No sample values: a fixed sample shown to every writer
        ends up in every program's text."""
        lines = []
        for lid in sorted(self.leaves):
            if not any(lid == r or lid.startswith(r + ".") for r in roots):
                continue
            leaf = self.leaves[lid]
            lines.append(f'- {lid}: {leaf.pos}, fits "{leaf.frame}". {leaf.description[:1].upper()}{leaf.description[1:].rstrip(".")}.')
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """The whole tree, for the dev browser."""
        return {
            "version": self.version, "facets": self.facets, "defaults": self.defaults,
            "nodes": [vars(n) for n in sorted(self.nodes.values(), key=lambda n: n.id)],
            "leaves": [{
                "id": lf.id, "label": lf.label, "description": lf.description, "pos": lf.pos, "frame": lf.frame,
                "notes": lf.notes, "facets": list(lf.facets), "closed": lf.closed,
                "untagged": {k: list(v) for k, v in lf.untagged.items()},
                "values": [{"text": v.text, "tier": v.tier, **({"tags": v.tags} if v.tags else {})} for v in lf.values],
            } for lf in sorted(self.leaves.values(), key=lambda lf: lf.id)],
        }


def _leaf(lid: str, d: Dict[str, Any]) -> Leaf:
    vals = tuple(Value(str(v["text"]), str(v.get("tier") or "plausible"), dict(v.get("tags") or {}))
                 for v in d.get("values") or [] if str(v.get("text") or "").strip())
    return Leaf(lid, str(d.get("label") or lid), str(d.get("description") or ""), str(d.get("pos") or ""),
                str(d.get("frame") or ""), str(d.get("notes") or ""), tuple(d.get("facets") or ()),
                bool(d.get("closed")), {k: tuple(v) for k, v in (d.get("untagged") or {}).items()}, vals)


def load(roots: Sequence[Path] = (ROOT,)) -> Vocabulary:
    nodes: Dict[str, Node] = {}
    leaves: Dict[str, Leaf] = {}
    facets: Dict[str, Dict[str, Any]] = {}
    h = hashlib.sha256()
    for root in roots:
        if not root.is_dir():
            continue
        fpath = root / "facets.json"
        if fpath.exists():
            raw = fpath.read_bytes()
            h.update(raw)
            for k, v in (json.loads(raw).get("facets") or {}).items():
                facets.setdefault(k, v)
        for p in sorted(root.rglob("*.json")):
            rel = p.relative_to(root)
            if rel.name == "facets.json":
                continue
            raw = p.read_bytes()
            h.update(str(rel).encode() + raw)
            d = json.loads(raw)
            if rel.name == "_node.json":
                nid = ".".join(rel.parts[:-1])
                nodes[nid] = Node(nid, str(d.get("label") or nid), str(d.get("description") or ""))
            else:
                lid = ".".join(rel.with_suffix("").parts)
                if lid in leaves:
                    raise ValueError(f"vocabulary: {lid} is defined twice")
                leaves[lid] = _leaf(lid, d)
    return Vocabulary(nodes, leaves, facets, "vocab-" + h.hexdigest()[:12])


@lru_cache(maxsize=1)
def vocabulary() -> Vocabulary:
    return load()


__all__ = ["Leaf", "Node", "Value", "Vocabulary", "load", "vocabulary", "TIER_WEIGHTS", "OPEN_SHARE"]

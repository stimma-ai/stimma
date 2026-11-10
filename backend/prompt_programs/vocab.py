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
A pool uses the context defaults (genre realistic, era contemporary) unless the prompt
narrows it: a pick's `where={facet: value}`, or the user's words read by narrow.py.

Two markers on a value say who it is for:
- `opt_in`: drawn only when asked for. The age list's baby, child and teen bands are opt-in:
  a person is an adult unless the user's words (narrowing, a pick's where=) or their own
  choice in the picker ask for a younger age. Unasked, such a value stays in its pool at
  weight 0 ("standby"), so the picker can offer it and a pin of it draws.
- `adult_only`: an adult-coded look (lingerie, sheer or boudoir wear, a sultry expression).
  It leaves a person's bound pools when that person may be under 18 (see `minor_ages`).
  The user's own lists and wildcards are never filtered.

More roots can be added (a stimpack's vocabulary); ids must not collide.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).parent / "vocab"
TIER_WEIGHTS = {"typical": 1.0, "plausible": 0.3, "unusual": 0.03}
OPEN_SHARE = 0.5      # an open leaf's list values' share of its pool's weight once generated options exist
EXAMPLES = 10         # list values shown to the options generator for an open leaf
CATALOGUE_ROOTS = ("person",)   # what the writer is shown; the rest waits for an open() tool
TYPO_CUTOFF = 0.85    # difflib ratio above which an unknown id is read as a typo of a known one
AGE_LIST = "person.age_band"     # the list a person's age is drawn from
MINOR = ("child", "teen")        # the age facet's values under 18


ROLES = ("main", "accent", "neutral")
_SLOT = re.compile(r"\{(main|accent|neutral)\}")


def fill(template: str, roles: Optional[Dict[str, str]]) -> str:
    """A template value with its palette roles filled in. Without roles (a palette not
    drawn yet, or a probe), slots are left out and the text still reads: "a technical
    T-shirt and running shorts"."""
    out = _SLOT.sub(lambda m: (roles or {}).get(m.group(1), ""), template)
    return re.sub(r"\s{2,}", " ", out).strip()


def is_template(text: str) -> bool:
    return bool(_SLOT.search(text))


def template_matches(template: str, text: str) -> bool:
    """Whether `text` is `template` filled with some colours (a removal or a kept value
    that came from a draw names the filled text, not the template)."""
    if not is_template(template):
        return template == text
    pattern = "".join(".+?" if m.group(1) else re.escape(m.group(0))
                      for m in re.finditer(r"\{(?:(main|accent|neutral))\}|[^{]+|\{", template))
    return re.fullmatch(pattern, text, re.I | re.S) is not None


def tags_match(tags: Dict[str, Any], want: Dict[str, Any]) -> bool:
    """Whether a value's tags satisfy a facet filter ({facet: value or [values]}, any-of
    per facet). A value with no tag for a filtered facet doesn't match."""
    for f, w in want.items():
        wants = {str(x) for x in (w if isinstance(w, (list, tuple)) else [w])}
        have = tags.get(f)
        if have is None:
            return False
        if have != "any" and not wants & {str(x) for x in have}:
            return False
    return True


@dataclass(frozen=True)
class Value:
    text: str
    tier: str
    tags: Dict[str, Any] = field(default_factory=dict)
    roles: Dict[str, str] = field(default_factory=dict)       # a palette's colours by role
    palette: Dict[str, Any] = field(default_factory=dict)     # a template's restriction on its palette
    opt_in: bool = False       # drawn only when asked for (the module docstring)
    adult_only: bool = False   # an adult-coded look: never in the pools of a person under 18

    @property
    def weight(self) -> float:
        return TIER_WEIGHTS.get(self.tier, TIER_WEIGHTS["plausible"])

    @property
    def minor(self) -> bool:
        """An age under 18: its age tags are all child or teen (18–19 is tagged adult)."""
        ages = self.tags.get("age")
        return isinstance(ages, (list, tuple)) and bool(ages) and all(str(a) in MINOR for a in ages)


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
    local_facets: Dict[str, Tuple[str, ...]] = field(default_factory=dict)   # named parts the writer can ask for
    slots: str = ""            # templates: the palette list whose roles fill {main}/{accent}/{neutral}
    individual: bool = False   # a detail of one subject (a node above says "individual": see Node)

    def value(self, text: str) -> Optional[Value]:
        return next((v for v in self.values if v.text == text), None)

    def matching(self, want: Dict[str, Any], context: Optional[Dict[str, str]] = None) -> List[Value]:
        """Eligible values whose tags satisfy a local-facet filter (where={...})."""
        return [v for v in self.eligible(context) if tags_match(v.tags, want)]

    def fits(self, value: Value, context: Dict[str, str]) -> bool:
        for f, want in context.items():
            fits = value.tags.get(f, self.untagged.get(f, "any"))
            if fits != "any" and want not in fits:
                return False
        return True

    def eligible(self, context: Optional[Dict[str, str]] = None) -> List[Value]:
        """The values that fit a context (unset facets take their defaults). A list the
        defaults would empty (period, fantasy or sci-fi outfits in a realistic, contemporary
        default) was bound because the image is in its world: it keeps to what the context
        does set instead of drawing nothing."""
        ctx = {**vocabulary().defaults, **(context or {})}
        out = [v for v in self.values if self.fits(v, ctx)]
        if out:
            return out
        return [v for v in self.values if self.fits(v, dict(context or {}))]

    def pool_values(self, allowed: Optional[Sequence[str]] = None, minor: bool = False,
                    context: Optional[Dict[str, str]] = None) -> Tuple[List[Value], List[Value]]:
        """(drawn, standby): the values a pick's pool draws from, and the opt-in values it
        holds at weight 0 for the picker and pins. Narrowed (`allowed`, where=) a pool is
        exactly its subset, opt-in values included: the words asked for them. For a person
        who may be under 18 (`minor`), adult-only values leave both."""
        vals = self.eligible(context)
        if allowed is not None:
            keep = set(allowed)
            drawn, standby = [v for v in vals if v.text in keep], []
        else:
            drawn, standby = [v for v in vals if not v.opt_in], [v for v in vals if v.opt_in]
        if minor:
            drawn, standby = [v for v in drawn if not v.adult_only], [v for v in standby if not v.adult_only]
        return drawn, standby

    def examples(self, key: str, context: Optional[Dict[str, str]] = None, n: int = EXAMPLES,
                 only: Optional[Sequence[str]] = None, minor: bool = False) -> List[str]:
        """A spread of eligible values for the options generator: one per tier and tag
        combination first, then at random, seeded by `key` so a pool's examples are stable.
        `only` keeps to a narrowed subset (where=); `minor` leaves adult-only values out."""
        vals = self.pool_values(only, minor, context)[0]
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
    """An inner node. `individual`: every list under it is a detail of one subject (a person's
    hairstyle, an animal's breed), so with several subjects each draws their own (prepare.py)."""
    id: str
    label: str
    description: str
    individual: bool = False


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
            if any(other.slots == lid for other in self.leaves.values()):
                continue  # a palette: drawn with the templates that use it, never bound by itself
            line = f'- {lid}: {leaf.pos}, fits "{leaf.frame}". {leaf.description[:1].upper()}{leaf.description[1:].rstrip(".")}.'
            parts = [f'{f} = {" | ".join(vals)}' for f, vals in leaf.local_facets.items()]
            palette = self.leaves.get(leaf.slots) if leaf.slots else None
            if palette is not None:
                parts += [f'{f} = {" | ".join(vals)}' for f, vals in palette.local_facets.items()]
                line += " Colours vary separately."
            if parts:
                line += " where: " + "; ".join(parts) + "."
            lines.append(line)
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
                **({"local_facets": {k: list(v) for k, v in lf.local_facets.items()}} if lf.local_facets else {}),
                **({"slots": lf.slots} if lf.slots else {}),
                "values": [{"text": v.text, "tier": v.tier, **({"tags": v.tags} if v.tags else {}),
                            **({"roles": v.roles} if v.roles else {}), **({"palette": v.palette} if v.palette else {}),
                            **({"opt_in": True} if v.opt_in else {}), **({"adult_only": True} if v.adult_only else {})}
                           for v in lf.values],
            } for lf in sorted(self.leaves.values(), key=lambda lf: lf.id)],
        }


def _leaf(lid: str, d: Dict[str, Any]) -> Leaf:
    vals = tuple(Value(str(v["text"]), str(v.get("tier") or "plausible"), dict(v.get("tags") or {}),
                       {str(k): str(x) for k, x in (v.get("roles") or {}).items()}, dict(v.get("palette") or {}),
                       v.get("opt_in") is True, v.get("adult_only") is True)
                 for v in d.get("values") or [] if str(v.get("text") or "").strip())
    return Leaf(lid, str(d.get("label") or lid), str(d.get("description") or ""), str(d.get("pos") or ""),
                str(d.get("frame") or ""), str(d.get("notes") or ""), tuple(d.get("facets") or ()),
                bool(d.get("closed")), {k: tuple(v) for k, v in (d.get("untagged") or {}).items()}, vals,
                {k: tuple(v) for k, v in (d.get("local_facets") or {}).items()}, str(d.get("slots") or ""))


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
                nodes[nid] = Node(nid, str(d.get("label") or nid), str(d.get("description") or ""), d.get("individual") is True)
            else:
                lid = ".".join(rel.with_suffix("").parts)
                if lid in leaves:
                    raise ValueError(f"vocabulary: {lid} is defined twice")
                leaves[lid] = _leaf(lid, d)
    for lid, lf in list(leaves.items()):  # a leaf under an individual node is a subject's own detail
        parts = lid.split(".")
        if any(getattr(nodes.get(".".join(parts[:i])), "individual", False) for i in range(1, len(parts))):
            leaves[lid] = replace(lf, individual=True)
    return Vocabulary(nodes, leaves, facets, "vocab-" + h.hexdigest()[:12])


@lru_cache(maxsize=1)
def vocabulary() -> Vocabulary:
    return load()


def minor_ages(values: Sequence[str]) -> Tuple[str, ...]:
    """The ages under 18 among `values` of the age list (a pick's subset, pins or kept
    values): a person whose age may be one of them is drawn as a minor."""
    leaf = vocabulary().get(AGE_LIST)
    if leaf is None:
        return ()
    want = {str(x) for x in values}
    return tuple(v.text for v in leaf.values if v.text in want and v.minor)


__all__ = ["AGE_LIST", "Leaf", "Node", "Value", "Vocabulary", "load", "minor_ages", "vocabulary", "TIER_WEIGHTS",
           "OPEN_SHARE"]

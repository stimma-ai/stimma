"""The vocabulary: curated lists a program binds picks to with `cls=`.

    eyes = pick("eyes", cls="person.eye_color", about="her eye color", seed=["hazel"], ...)

The vocabulary is a tree. An inner node (`person`, `person.outfit`) has a one-line
description; a leaf is a list of values of one part of speech, each with a typicality
tier and optional facet tags (genre, era, region...). The directory layout under
`vocab/` is the tree: `vocab/person/outfit/casual.json` is `person.outfit.casual`, and
each inner node has a `_node.json`.

A bound pick draws from its leaf instead of from options a model wrote. A **closed** leaf
(eye color, skin tone, shot size) is the whole pool: small natural sets, where generated
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

A face piece is rated `strength` 1 (subtle) or 2 (marked). A marked piece is opt-in: drawn
only when the user picks it or their words ask for it, never because a facet filter
(where={"presentation": ...}) let it in. `distinctive` marks a scar, birthmark, vitiligo, a
prominent mark or a strongly unusual feature, so how often faces show one can be counted.

Context: a drawn value gives context to the picks that follow it in the same scope.
`facets.json`'s "context" section declares the context facets, each with a scope: "person"
(a person's descent → their skin, eye and hair families) or "scene" (time of day, season,
indoor or outdoor, climate → the light, weather and clothes that fit). A leaf says which
context facets its values give ("gives") and which it takes ("takes", with what a mismatch
costs: "rare" multiplies the value's weight by a factor, "never" sets it to 0). When a
pick's leaf takes a facet, the tags on that facet of the values drawn before it in its
scope (its person's, or the image's) weight its pool: a value whose tag shares a family
with the context keeps its weight, one that shares none pays the mismatch, an untagged one
fits every context. A giving value can also name families it gives as "less_common"
("mostly light eyes, sometimes brown"): a value in one of those (and in no typical one)
is multiplied by the taking list's own "less_common" factor, between kept and rare.
All of the knowledge is data; the engine only matches tag sets.
The user's own lists, wildcards, pins and additions are never weighted (draws.py).

A list whose values share settings can declare them once as "groups" ({name: {about,
tags, less_common}}); a value's "group" names one, and its own tags add to the group's.
The descent list uses them, so every heritage's coloring is declared and reviewed by name.

A list may name one of its local facets as the one it is browsed by ("browse": "region"): every
value sits in exactly one part of it, and the chooser opens on a row per part (descent's world
regions), each leading to its values. Its declared groups then aren't offered as chips.

More roots can be added (a stimpack's vocabulary); ids must not collide.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field, replace
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).parent / "vocab"
TIER_WEIGHTS = {"typical": 1.0, "plausible": 0.3, "unusual": 0.03}
OPEN_SHARE = 0.5      # an open leaf's list values' share of its pool's weight once generated options exist
EXAMPLES = 10         # list values shown to the options generator for an open leaf
CATALOG_ROOTS = ("person", "clothing", "animal", "plant", "place", "interior_space", "exterior_space", "scene", "camera",
                 "lighting", "art", "object", "vehicle", "food")   # every directory: what a slot may be bound to
TYPO_CUTOFF = 0.85    # difflib ratio above which an unknown id is read as a typo of a known one
AGE_LIST = "person.age_band"     # the list a person's age is drawn from
MINOR = ("child", "teen")        # the age facet's values under 18
LESS = "~"   # marks a less-common family in a context ("~brown"); the families a value gives typically are bare


ROLES = ("main", "accent", "neutral")
_SLOT = re.compile(r"\{(main|accent|neutral)\}")


def fill(template: str, roles: Optional[Dict[str, str]]) -> str:
    """A template value with its palette roles filled in. Without roles (a palette not
    drawn yet, or a probe), slots are left out and the text still reads: "a technical
    T-shirt and running shorts"."""
    from prompt_programs.fill import fix_articles
    out = _SLOT.sub(lambda m: (roles or {}).get(m.group(1), ""), template)
    # the article before a slot goes with the color filled in: "a {main} coat" → "an olive coat",
    # so the drawn value is the text the prompt shows
    return fix_articles(re.sub(r"\s{2,}", " ", out).strip())


def is_template(text: str) -> bool:
    return bool(_SLOT.search(text))


def template_matches(template: str, text: str) -> bool:
    """Whether `text` is `template` filled with some colors (a removal or a kept value
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
    roles: Dict[str, str] = field(default_factory=dict)       # a palette's colors by role
    palette: Dict[str, Any] = field(default_factory=dict)     # a template's restriction on its palette
    opt_in: bool = False       # drawn only when asked for (the module docstring)
    adult_only: bool = False   # an adult-coded look: never in the pools of a person under 18
    group: str = ""            # the leaf's declared group it takes its shared tags from
    less_common: Dict[str, Any] = field(default_factory=dict)   # context facet -> families it gives as less common
    scale: float = 1.0         # its branch's share over the branch's tier weights (a leaf's `shares`)
    short: str = ""            # a pill-sized name for the chooser ("flannel shirt and jeans"); never drawn
    look: str = ""             # one line on what it looks like, for a person browsing ("hair rolled up and pinned in a vertical fold"); never drawn
    strength: int = 0          # a face piece's: 1 subtle, 2 marked (0: not rated); a marked one is opt-in
    distinctive: bool = False  # a scar, birthmark, vitiligo, a prominent mark or a strongly unusual feature

    @property
    def marked(self) -> bool:
        """A marked face piece: drawn only when picked or asked for in words (never let in by a facet filter)."""
        return self.strength >= 2

    @property
    def weight(self) -> float:
        return TIER_WEIGHTS.get(self.tier, TIER_WEIGHTS["plausible"]) * self.scale

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
    gives: Tuple[str, ...] = ()                      # context facets its drawn values give (module docstring)
    takes: Dict[str, Tuple[str, float]] = field(default_factory=dict)   # facet -> (rare | never, factor)
    stated: bool = False       # a person's or scene's stated value of this list is read as context (narrow.py)
    groups: Dict[str, Any] = field(default_factory=dict)   # declared groups of shared tags (module docstring)
    less: Dict[str, float] = field(default_factory=dict)   # facet -> factor for a less-common family (module docstring)
    listed: bool = True        # shown to the writer; a part of a composed list isn't ("catalog": false)
    strict: bool = False       # never drawn without the list: words nothing in it fits leave it whole (narrow.py)
    plain: str = ""            # the value that goes without saying (an animal's "adult"): drawn unasked, it adds no word (fill.py)
    parts: Tuple[str, ...] = ()   # a list of pieces ("compose": {"each": true}): its part lists, in order (a face's shape, eyes…)
    browse: str = ""           # the local facet the chooser is browsed by: a row per part (descent's regions)

    def value(self, text: str) -> Optional[Value]:
        return self._by_text.get(text)

    def look(self, text: str) -> str:
        """A value's one line on what it looks like ("" when the list gives none); a filled
        template reads as its template's."""
        v = self.value(text)
        if v is None and not is_template(text):
            v = next((x for x in self.values if is_template(x.text) and template_matches(x.text, text)), None)
        return v.look if v is not None else ""

    def short(self, text: str) -> str:
        """A value's short form for a small pill: its `short` when the list gives one, else the
        value itself. A filled template ("a navy cotton T-shirt and ...") reads as its template's
        short form, which names no colors."""
        v = self.value(text)
        if v is None and not is_template(text):
            v = next((x for x in self.values if is_template(x.text) and template_matches(x.text, text)), None)
        return (v.short if v is not None else "") or text

    @cached_property
    def _by_text(self) -> Dict[str, Value]:
        out: Dict[str, Value] = {}
        for v in self.values:
            out.setdefault(v.text, v)
        return out

    def context_tags(self, text: str, facet: str) -> Optional[Tuple[str, ...]]:
        """A value's tags on a context facet (the leaf's `untagged` default when it has none),
        then the families it gives as less common, marked (LESS + family); None when it has
        no tag or isn't a value of this list."""
        v = self.value(text)
        if v is None:
            return None
        got = v.tags.get(facet, self.untagged.get(facet))
        if got is None or got == "any":
            return None
        less = v.less_common.get(facet) or ()
        return tuple(str(x) for x in (got if isinstance(got, (list, tuple)) else [got])) + tuple(LESS + str(x) for x in less)

    def weigh(self, items: Sequence[Tuple[str, float]],
              context: Sequence[Tuple[str, Sequence[str]]]) -> List[Tuple[str, float]]:
        """A pool's (value, weight) pairs weighted by the context it is drawn in: for each facet
        this list takes, a value tagged on it that shares no family with the context pays the
        mismatch (rare: × factor; never: × 0), or, when it shares only a family the context gives
        as less common (LESS-marked), this list's less_common factor for the facet (the mismatch
        factor if it declares none); the values tagged on the facet are scaled back
        to the share of the pool they had, so the context only moves weight among the values it
        speaks to. Values with no tag on the facet (gray or dyed hair for descent), the facet's
        neutral values and anything not in this list (a user's addition, a generated option) keep
        their weight. A mismatch that would leave the tagged values no weight is not applied."""
        out = list(items)
        for facet, mode, costs in self._facet_costs([o for o, _ in out], context):
            spoken = [c is not None for c in costs]
            nxt = [(o, w * c) if c is not None else (o, w) for (o, w), c in zip(out, costs)]
            before = sum(w for (_, w), s in zip(out, spoken) if s)
            after = sum(w for (_, w), s in zip(nxt, spoken) if s)
            if mode == "drop":   # the values that don't fit leave; the rest keep their own weight
                # A context never empties a pool: when the user's words narrowed the list to values
                # the context would drop ("a young woman with gray hair", "a man in a romantic
                # outfit"), their words stand and the context isn't applied.
                if any(w > 0 for _, w in nxt) or not any(w > 0 for _, w in out):
                    out = nxt
                continue
            if before > 0 and after <= 0:
                continue
            if after > 0:
                nxt = [(o, w * before / after) if s else (o, w) for (o, w), s in zip(nxt, spoken)]
            out = nxt
        return out

    def _facet_costs(self, texts: Sequence[str], context: Sequence[Tuple[str, Sequence[str]]]):
        """For each context facet this list takes: (facet, mode, each text's cost), the cost
        None for a text the facet doesn't speak to (no tag, a neutral value, not in this list)."""
        neutral = vocabulary().context_neutral
        for facet, families in context:
            mode = self.takes.get(facet)
            if mode is None or not families:
                continue
            want = {f for f in families if not f.startswith(LESS)}
            less = {f[len(LESS):] for f in families if f.startswith(LESS)} - want
            keep = set(neutral.get(facet, ()))
            factor = 0.0 if mode[0] in ("never", "drop") else mode[1]
            less_factor = self.less.get(facet, factor)

            def cost(t: Optional[Tuple[str, ...]]) -> Optional[float]:
                if t is None or set(t) & keep:
                    return None
                fams = set(t)
                return 1.0 if fams & want else less_factor if fams & less else factor
            yield facet, mode[0], [cost(self.context_tags(o, facet)) for o in texts]

    def reduced(self, texts: Sequence[str], context: Sequence[Tuple[str, Sequence[str]]]) -> Set[str]:
        """The texts a context makes less likely or leaves out (weigh() gives them less than
        their own weight): those tagged on a facet it speaks to with no family it wants. A
        facet weigh() would skip (every value it speaks to mismatched) reduces nothing."""
        out: Set[str] = set()
        for _, mode, costs in self._facet_costs(texts, context):
            low = {t for t, c in zip(texts, costs) if c is not None and c < 1.0}
            if mode != "drop" and any(c is not None for c in costs) and all(c is None or c <= 0 for c in costs):
                continue
            out |= low
        return out

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
        holds at weight 0 for the picker and pins. Narrowed (`allowed`, where=) a pool draws
        exactly its subset, opt-in values included: the words asked for them; the rest of the list
        stands by, so the picker can offer it and a tick draws it. For a person
        who may be under 18 (`minor`), adult-only values leave both."""
        vals = self.eligible(context)
        if allowed is not None:
            keep = set(allowed)
            drawn, standby = [v for v in vals if v.text in keep], [v for v in vals if v.text not in keep]
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
    """An inner node: a folder of lists, with a label and a one-line description."""
    id: str
    label: str
    description: str


@dataclass
class Vocabulary:
    nodes: Dict[str, Node]
    leaves: Dict[str, Leaf]
    facets: Dict[str, Dict[str, Any]]
    version: str
    context: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # context facet -> {scope, values, neutral, about}

    @property
    def context_neutral(self) -> Dict[str, Tuple[str, ...]]:
        return {f: tuple(spec.get("neutral") or ()) for f, spec in self.context.items()}

    def scope(self, facet: str) -> str:
        """A context facet's scope: "person" or "scene"."""
        return str((self.context.get(facet) or {}).get("scope") or "scene")

    def givers(self, facet: str) -> List["Leaf"]:
        return [lf for lf in self.leaves.values() if facet in lf.gives]

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

    def catalog(self, roots: Sequence[str] = CATALOG_ROOTS) -> str:
        """The lists a slot may be bound to, one line each: id, part of speech, where a value
        fits, what it's for. No sample values (a fixed sample shown to every reader ends up in
        every prompt) and no groups (the slot's words narrow a list after it is bound)."""
        lines = []
        for lid in sorted(self.leaves):
            if not any(lid == r or lid.startswith(r + ".") for r in roots):
                continue
            leaf = self.leaves[lid]
            if any(other.slots == lid for other in self.leaves.values()):
                continue  # a palette: drawn with the templates that use it, never bound by itself
            if not leaf.listed:
                continue  # a part of a composed list: bindable, but the reader is shown the whole
            line = f'- {lid}: {leaf.pos}, fits "{leaf.frame}". {leaf.description[:1].upper()}{leaf.description[1:].rstrip(".")}.'
            if leaf.slots and self.leaves.get(leaf.slots) is not None:
                line += " Colors vary separately."
            lines.append(line)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """The whole tree, for the dev browser."""
        return {
            "version": self.version, "facets": self.facets, "defaults": self.defaults, "context": self.context,
            "nodes": [vars(n) for n in sorted(self.nodes.values(), key=lambda n: n.id)],
            "leaves": [{
                "id": lf.id, "label": lf.label, "description": lf.description, "pos": lf.pos, "frame": lf.frame,
                "notes": lf.notes, "facets": list(lf.facets), "closed": lf.closed,
                "untagged": {k: list(v) for k, v in lf.untagged.items()},
                **({"local_facets": {k: list(v) for k, v in lf.local_facets.items()}} if lf.local_facets else {}),
                **({"slots": lf.slots} if lf.slots else {}),
                **({"context": _context_dict(lf)} if lf.gives or lf.takes else {}),
                **({"groups": lf.groups} if lf.groups else {}),
                **({"browse": lf.browse} if lf.browse else {}),
                "values": [{"text": v.text, "tier": v.tier, **({"tags": v.tags} if v.tags else {}),
                            **({"roles": v.roles} if v.roles else {}), **({"palette": v.palette} if v.palette else {}),
                            **({"opt_in": True} if v.opt_in else {}), **({"adult_only": True} if v.adult_only else {}),
                            **({"group": v.group} if v.group else {}), **({"short": v.short} if v.short else {}),
                            **({"look": v.look} if v.look else {}), **({"strength": v.strength} if v.strength else {}),
                            **({"distinctive": True} if v.distinctive else {}),
                            **({"less_common": v.less_common} if v.less_common else {})}
                           for v in lf.values],
            } for lf in sorted(self.leaves.values(), key=lambda lf: lf.id)],
        }


def _context_dict(lf: Leaf) -> Dict[str, Any]:
    return {**({"gives": list(lf.gives)} if lf.gives else {}), **({"stated": True} if lf.stated else {}),
            **({"takes": {f: {**({"mismatch": m} if m in ("never", "drop") else {"mismatch": m, "factor": x}),
                              **({"less_common": lf.less[f]} if f in lf.less else {})}
                          for f, (m, x) in lf.takes.items()}} if lf.takes else {})}


def _leaf_context(d: Dict[str, Any]) -> Tuple[Tuple[str, ...], Dict[str, Tuple[str, float]], bool, Dict[str, float]]:
    ctx = d.get("context") or {}
    takes, less = {}, {}
    for f, spec in (ctx.get("takes") or {}).items():
        mode = str((spec or {}).get("mismatch") or "rare")
        takes[str(f)] = (mode, 0.0) if mode in ("never", "drop") else ("rare", float((spec or {}).get("factor", 0.1)))
        if (spec or {}).get("less_common") is not None:
            less[str(f)] = float(spec["less_common"])
    return tuple(str(f) for f in ctx.get("gives") or ()), takes, ctx.get("stated") is True, less


def _value(lid: str, v: Dict[str, Any], groups: Dict[str, Any]) -> Value:
    """A value with its group's shared tags and less-common families under its own."""
    name = str(v.get("group") or "")
    if name and name not in groups:
        raise ValueError(f"vocabulary: {lid} value {v.get('text')!r} names unknown group {name!r}")
    g = groups.get(name) or {}
    strength = int(v.get("strength") or 0)
    # A marked face piece is drawn only when chosen: opt-in, as the schema says of strength 2.
    return Value(str(v["text"]), str(v.get("tier") or "plausible"), {**(g.get("tags") or {}), **(v.get("tags") or {})},
                 {str(k): str(x) for k, x in (v.get("roles") or {}).items()}, dict(v.get("palette") or {}),
                 v.get("opt_in") is True or strength >= 2, v.get("adult_only") is True, name,
                 {**(g.get("less_common") or {}), **(v.get("less_common") or {})},
                 short=str(v.get("short") or "").strip(), look=str(v.get("look") or "").strip(),
                 strength=strength, distinctive=v.get("distinctive") is True)


def _shared(lid: str, vals: Tuple[Value, ...], shares: Dict[str, Dict[str, float]]) -> Tuple[Value, ...]:
    """Values weighted by their branch's share. A leaf may declare, for one local facet, the
    share of draws each of its parts gets when a pick isn't narrowed:
    `"shares": {"intent": {"sharp": 0.2, "soft_background": 0.05}}`. A part's values split its
    share by tier, so how many values a part has doesn't change how often it's drawn. A part
    with share 0 is opt-in: drawn only when a pick asks for it (where=). The share is of what is
    drawn unasked: a part's opt-in values (marked face pieces) don't take from it, and are drawn
    at their tier's weight in it when picked."""
    if not shares:
        return vals
    if len(shares) != 1:
        raise ValueError(f"vocabulary: {lid} declares shares on more than one facet")
    (facet, by_part), = shares.items()
    parts: Dict[str, float] = {}
    every: Dict[str, float] = {}   # a part with only opt-in values splits its share among them all
    for v in vals:
        tagged = v.tags.get(facet)
        if not isinstance(tagged, (list, tuple)) or len(tagged) != 1 or str(tagged[0]) not in by_part:
            raise ValueError(f"vocabulary: {lid} has shares on {facet}; {v.text!r} needs exactly one {facet} with a share")
        every[str(tagged[0])] = every.get(str(tagged[0]), 0.0) + v.weight
        if not v.opt_in:
            parts[str(tagged[0])] = parts.get(str(tagged[0]), 0.0) + v.weight
    parts = {p: parts.get(p) or w for p, w in every.items()}
    total = sum(float(by_part[p]) for p in parts)
    if total <= 0:
        raise ValueError(f"vocabulary: {lid}'s shares on {facet} are all 0")
    out = []
    for v in vals:
        part = str(v.tags[facet][0])
        share = float(by_part[part]) / total
        out.append(replace(v, scale=(share or 1.0) / parts[part], opt_in=v.opt_in or share == 0))
    return tuple(out)


def _weighted(rng: random.Random, pairs: Sequence[Tuple[Any, float]]) -> Any:
    return rng.choices([x for x, _ in pairs], weights=[w for _, w in pairs], k=1)[0]


def _composed(lid: str, spec: Dict[str, Any], leaves: Dict[str, Leaf]) -> Tuple[Value, ...]:
    """A composed list's values: each one a few parts joined, every part a value of a
    different list. `"compose": {"parts": {list id: weight}, "take": {"2": 0.55, "3": 0.45},
    "count": 2000, "tags": {facet: [values an untagged part fits]}}`. The parts are sampled
    by the lists' weights and the values' own, so drawing the result uniformly keeps each
    list's designed spread; which lists a value uses varies, so two faces differ in what is
    said of them, not only in how. A combination keeps a tag only where its parts agree (the
    ages all of them fit); parts that share nothing are not combined. Sampling is seeded by
    the list id: the same data always composes the same values."""
    if spec.get("each"):
        return _pieces(spec, leaves)
    rng = random.Random(lid)
    parts = [(leaves[pid], float(w)) for pid, w in spec["parts"].items()]
    order = {lf.id: i for i, (lf, _) in enumerate(parts)}
    take = [(int(k), float(w)) for k, w in spec["take"].items()]
    fill_tags = {f: tuple(v) for f, v in (spec.get("tags") or {}).items()}
    out: Dict[str, Value] = {}
    for _ in range(int(spec.get("count", 1000)) * 20):
        if len(out) >= int(spec.get("count", 1000)):
            break
        pool, chosen = list(parts), []
        for _ in range(min(_weighted(rng, take), len(pool))):
            got = _weighted(rng, [(p, p[1]) for p in pool])
            pool.remove(got)
            chosen.append(got[0])
        chosen.sort(key=lambda lf: order[lf.id])
        vals = [_weighted(rng, [(v, v.weight) for v in lf.values]) for lf in chosen]
        tags: Dict[str, Any] = {}
        for facet, default in fill_tags.items():
            fits = set(default)
            for v in vals:
                if facet in v.tags:
                    fits &= {str(x) for x in v.tags[facet]}
            tags[facet] = [x for x in default if x in fits]
        if not all(tags.values()):
            continue
        tags = {f: v for f, v in tags.items() if f in (spec.get("keep") or ()) or len(v) < len(fill_tags[f])}
        text = ", ".join(v.text for v in vals)   # a list, as a prompt lists things: no "and" to misread
        out.setdefault(text, Value(text, "typical", tags, opt_in=any(v.opt_in for v in vals)))
    return tuple(out.values())


def _pieces(spec: Dict[str, Any], leaves: Dict[str, Leaf]) -> Tuple[Value, ...]:
    """A list of pieces: every value of every part list, one at a time. `"compose": {"each":
    true, "parts": {list id: share}}`. A part's values share its share of the draws (by their
    own weights), and each carries the part it came from as its "piece" tag (the last part of the
    list id), so the chooser groups them. With "marked": "opt_in", a piece rated strength 2
    (marked) is drawn only when asked for, so an open face is one subtle piece. "tags" gives what
    a piece with no tag on a facet counts as (a piece of either sex). The face is
    built this way: one piece reads as a face, three named features caricature. A part's plain
    value (nothing notable about it) is not a piece: it is drawn only when the part varies on its
    own. A part's share is of what is drawn unasked (not its marked pieces)."""
    total = sum(float(w) for w in spec["parts"].values()) or 1.0
    out: Dict[str, Value] = {}
    for pid, share in spec["parts"].items():
        lf = leaves[pid]
        pieces = [v for v in lf.values if v.text != lf.plain]
        mass = sum(v.weight for v in pieces if not v.opt_in) or sum(v.weight for v in pieces) or 1.0
        for v in pieces:
            marked = spec.get("marked") == "opt_in" and v.strength >= 2
            tags = {**{f: list(x) for f, x in (spec.get("tags") or {}).items()}, **v.tags, "piece": [pid.rsplit(".", 1)[-1]]}
            out.setdefault(v.text, replace(v, tags=tags, group="",
                                           scale=v.weight / mass * float(share) / total / (TIER_WEIGHTS.get(v.tier) or 1.0),
                                           opt_in=v.opt_in or marked))
    return tuple(out.values())


def _leaf(lid: str, d: Dict[str, Any]) -> Leaf:
    gives, takes, stated, less = _leaf_context(d)
    groups = dict(d.get("groups") or {})
    vals = tuple(_value(lid, v, groups) for v in d.get("values") or [] if str(v.get("text") or "").strip())
    vals = _shared(lid, vals, d.get("shares") or {})
    return Leaf(lid, str(d.get("label") or lid), str(d.get("description") or ""), str(d.get("pos") or ""),
                str(d.get("frame") or ""), str(d.get("notes") or ""), tuple(d.get("facets") or ()),
                bool(d.get("closed")), {k: tuple(v) for k, v in (d.get("untagged") or {}).items()}, vals,
                {k: tuple(v) for k, v in (d.get("local_facets") or {}).items()}, str(d.get("slots") or ""),
                gives, takes, stated, less=less, groups=groups)


def _browse(lid: str, leaf: Leaf, facet: str) -> str:
    """The local facet a list is browsed by, once every value is known to sit in exactly one of its parts."""
    parts = set(leaf.local_facets.get(facet) or ())
    if not parts:
        raise ValueError(f"vocabulary: {lid} is browsed by {facet!r}, which isn't one of its local facets")
    for v in leaf.values:
        tagged = v.tags.get(facet)
        if not isinstance(tagged, (list, tuple)) or len(tagged) != 1 or str(tagged[0]) not in parts:
            raise ValueError(f"vocabulary: {lid} is browsed by {facet}; {v.text!r} needs exactly one of its parts")
    return facet


def load(roots: Sequence[Path] = (ROOT,)) -> Vocabulary:
    nodes: Dict[str, Node] = {}
    leaves: Dict[str, Leaf] = {}
    facets: Dict[str, Dict[str, Any]] = {}
    context: Dict[str, Dict[str, Any]] = {}
    composed: Dict[str, Dict[str, Any]] = {}
    h = hashlib.sha256()
    for root in roots:
        if not root.is_dir():
            continue
        fpath = root / "facets.json"
        if fpath.exists():
            raw = fpath.read_bytes()
            h.update(raw)
            got = json.loads(raw)
            for k, v in (got.get("facets") or {}).items():
                facets.setdefault(k, v)
            for k, v in ((got.get("context") or {}).get("facets") or {}).items():
                context.setdefault(k, v)
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
                if d.get("catalog") is False:
                    leaves[lid] = replace(leaves[lid], listed=False)
                if d.get("strict") is True:
                    leaves[lid] = replace(leaves[lid], strict=True)
                if d.get("plain"):
                    if leaves[lid].value(str(d["plain"])) is None:
                        raise ValueError(f"vocabulary: {lid}'s plain value {d['plain']!r} is not one of its values")
                    leaves[lid] = replace(leaves[lid], plain=str(d["plain"]))
                if d.get("browse"):
                    leaves[lid] = replace(leaves[lid], browse=_browse(lid, leaves[lid], str(d["browse"])))
                if d.get("compose"):
                    composed[lid] = d["compose"]
    for lid, spec in composed.items():
        leaves[lid] = replace(leaves[lid], values=_composed(lid, spec, leaves),
                              parts=tuple(spec["parts"]) if spec.get("each") else ())
    return Vocabulary(nodes, leaves, facets, "vocab-" + h.hexdigest()[:12], context)


@lru_cache(maxsize=1)
def vocabulary() -> Vocabulary:
    return load()


def given_families(cls: str, values: Sequence[str]) -> Dict[str, Tuple[str, ...]]:
    """The context a subset of a giving list's values gives (a stated "Japanese", a user's list
    value read on the descent list): per facet the list gives, the union of their tags. A facet
    some value of the subset has no tag on gives nothing (it could be anything)."""
    leaf = vocabulary().get(cls)
    if leaf is None or not values:
        return {}
    out: Dict[str, Tuple[str, ...]] = {}
    for f in leaf.gives:
        tags = [leaf.context_tags(str(x), f) for x in values]
        if tags and all(t for t in tags):
            out[f] = tuple(sorted({x for t in tags for x in t}))   # type: ignore[union-attr]
    return out


def minor_ages(values: Sequence[str]) -> Tuple[str, ...]:
    """The ages under 18 among `values` of the age list (a pick's subset, pins or kept
    values): a person whose age may be one of them is drawn as a minor."""
    leaf = vocabulary().get(AGE_LIST)
    if leaf is None:
        return ()
    want = {str(x) for x in values}
    return tuple(v.text for v in leaf.values if v.text in want and v.minor)


__all__ = ["AGE_LIST", "LESS", "Leaf", "Node", "Value", "Vocabulary", "given_families", "load", "minor_ages", "vocabulary",
           "TIER_WEIGHTS", "OPEN_SHARE"]

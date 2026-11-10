"""The prompt-program language and its draw API.

A program is a small Python subset written by the prepare step. It is checked
against an AST whitelist, then run with a seeded RNG and a step budget. Running it
needs no model call: it yields a finished prompt, LoRAs, parameter values and a
record of every draw.

    weather = pick("weather", ["rainy", "foggy", "bright"], label="Weather", source="list", line=1)
    if weather == "rainy":
        pick("umbrella", ["a clear umbrella", "a black umbrella"], label="Umbrella", added=True)
    clothing = pick("clothing", by=weather, options={"rainy": [...], "foggy": [...], "bright": [...]})
    hair = pick_lora("hair", ["Curtain bangs", "Wolf cut"], label="Hairstyle", line=3)
    param("guidance", 3.5, 5.5, line=4)
    for i in range(group("people", 3, label="People")):
        pick(f"people[{i+1}].age", AGES, exclude=ages_so_far)
    emit("A candid photograph of a woman", clothing, "waiting for a train.")

Choices are discovered by running the program over many seeds (`discover`): which
picks exist, their options, which earlier pick a pick only appears under, and which
earlier pick its options follow (`by=`).
"""

from __future__ import annotations

import ast
import functools
import operator
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

MAX_STEPS = 20_000
MAX_SOURCE_CHARS = 40_000
# Rank decay for options the agent lists most-likely-first. Fairly flat on purpose:
# variety is the point, order only nudges.
RANK_DECAY = 0.86

SOURCES = ("text", "list", "added")


class ProgramError(Exception):
    """A program that can't be checked or run. The message is fed back to the model."""


# --------------------------------------------------------------------------- checking

_ALLOWED_NODES: Tuple[type, ...] = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.Pass, ast.Break, ast.Continue,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.keyword, ast.Attribute, ast.JoinedStr, ast.FormattedValue,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
)
_ALLOWED_METHODS = {
    "append", "extend", "get", "items", "keys", "values", "join", "lower", "upper",
    "capitalize", "title", "strip", "replace", "startswith", "endswith", "split", "count", "index",
}
_SAFE_BUILTINS: Dict[str, Any] = {
    "range": range, "len": len, "str": str, "int": int, "float": float, "min": min, "max": max,
    "round": round, "sorted": sorted, "list": list, "dict": dict, "set": set, "enumerate": enumerate,
    "zip": zip, "abs": abs, "any": any, "all": all, "True": True, "False": False, "None": None,
}
API_NAMES = {"pick", "pick_lora", "param", "group", "emit"}
# Methods the sandbox checks at the call (they grow a value, or compare or hash their argument)
_GROWING_METHODS = ("join", "replace", "extend")
_COMPARING_METHODS = ("index", "count", "get")
_CALLED_METHODS = frozenset(_GROWING_METHODS + _COMPARING_METHODS)


def extract_code(text: str) -> str:
    """Pull the program out of a model reply (fenced block or bare code)."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if not m:  # a reply cut off (or never closed) after its opening fence
        m = re.search(r"```(?:python|py)?\s*\n(.*)", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


def check(source: str) -> ast.Module:
    if len(source) > MAX_SOURCE_CHARS:
        raise ProgramError(f"Program is too long ({len(source)} characters; limit {MAX_SOURCE_CHARS}).")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ProgramError(f"Syntax error on line {e.lineno}: {e.msg}") from None
    # The guarded methods are checked where they're called (see _Guarded), so they may only
    # be called where they're written: `f = s.replace` or `key=lst.index` would skip the check.
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            line = getattr(node, "lineno", "?")
            raise ProgramError(f"Line {line}: {type(node).__name__} is not allowed. Use only assignments, if, for, and the pick/pick_lora/param/group/emit functions.")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr not in _ALLOWED_METHODS:
                raise ProgramError(f"Line {node.lineno}: .{node.attr} is not allowed.")
            if node.attr in _CALLED_METHODS and id(node) not in called:
                raise ProgramError(f"Line {node.lineno}: .{node.attr} can only be called where it's written, "
                                   f"as in x.{node.attr}(...), not stored or passed along.")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ProgramError(f"Line {node.lineno}: names starting with __ are not allowed.")
    return tree


# --------------------------------------------------------------------------- records

@dataclass
class Draw:
    id: str
    value: Any
    kind: str                      # pick | lora | param
    label: str = ""
    source: str = "text"           # text | list | added
    line: Optional[int] = None
    hidden: bool = False
    pinned: bool = False
    options: List[str] = field(default_factory=list)   # what was available this time
    follows: Optional[str] = None  # id of the pick whose value keyed these options (by=)
    phase: Optional[int] = None    # pick specs (see draws.py); unset for older programs
    about: str = ""
    cls: str = ""                  # the vocabulary list the pick is bound to (see vocab.py)
    where: Any = ""                # the user's words, or {local facet: value}, narrowing that list (narrow.py)
    said: str = ""                 # the user's own words this pick stands for (said_value): drawn unless they choose others
    shared: bool = False           # shared=True: one value for every subject, as the user asked

    def to_dict(self) -> Dict[str, Any]:
        d = {"id": self.id, "value": self.value, "kind": self.kind, "label": self.label, "source": self.source}
        if self.line is not None:
            d["line"] = self.line
        if self.hidden:
            d["hidden"] = True
        if self.pinned:
            d["pinned"] = True
        if self.follows:
            d["follows"] = self.follows
        if self.phase is not None:
            d["phase"] = self.phase
        if self.about:
            d["about"] = self.about
        if self.cls:
            d["cls"] = self.cls
        if self.where:
            d["where"] = self.where
        if self.said:
            d["said"] = self.said
        if self.shared:
            d["shared"] = True
        return d


def said_value(said: Any) -> str:
    """A pick's said= (the user's own words for the thing it stands for), or "" for none.

    A pick with said= draws the user's words every time, exactly as written, until the user
    ticks other options for it (pins, see draws.py): its other options are alternatives they
    may switch to, never a replacement chosen for them. It is the user's choice, from their
    text, whatever else the writer marked it."""
    return re.sub(r"\s+", " ", said).strip() if isinstance(said, str) else ""


def holds_said(cid: str, said: str, options: Sequence[str], pins: Dict[str, Any], fixed: Dict[str, Any]) -> bool:
    """Whether a said pick draws the user's words this time: no pins of the user's own for it
    (ticking other options is how they widen it), no value kept from an earlier draw (a
    replay keeps what it drew), and their words still among its options (not deleted)."""
    return bool(said) and cid not in pins and cid not in fixed and said in options


@dataclass
class LoraUse:
    name: str
    weight: float
    trigger: str = ""
    path: str = ""
    choice: str = ""


@dataclass
class RunResult:
    prompt: str
    draws: List[Draw]
    loras: List[LoraUse]
    params: Dict[str, Any]
    groups: Dict[str, Dict[str, Any]]
    seed: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "draw_seed": self.seed,
            "draws": [d.to_dict() for d in self.draws],
            "loras": [vars(lu) for lu in self.loras],
            "params": dict(self.params),
        }


@dataclass
class LoraInfo:
    """A LoRA the program may pick: from the tool's LoRA list."""
    name: str
    path: str
    weight: float = 1.0
    trigger: str = ""
    on: bool = False   # switched on in the LoRA panel (runs unless the prompt chooses among it)


class LoraName(str):
    """What pick_lora returns: the LoRA's name, for the program to compare or look up.
    It turns the LoRA on; it is never prompt text, so emit() skips it."""


def lora_names(names: Sequence[str], loras: Dict[str, LoraInfo]) -> List[str]:
    """The list's names for what a program wrote: an exact name, or a short one the user
    used ("rainglass") when every word of it is a word of exactly one listed name
    ("KREA2 studio rainglass v1"). Unknown or ambiguous names are dropped."""
    out: List[str] = []
    for n in names:
        info = loras.get(_lora_key(n))
        if info is None:
            words = set(re.findall(r"[a-z0-9]+", str(n).lower()))
            hits = [lo for lo in loras.values() if words and words <= set(re.findall(r"[a-z0-9]+", lo.name.lower()))]
            info = hits[0] if len(hits) == 1 else None
        if info is not None and info.name not in out:
            out.append(info.name)
    return out


# --------------------------------------------------------------------------- running

def _weights(n: int, uniform: bool) -> List[float]:
    return [1.0] * n if uniform else [RANK_DECAY ** i for i in range(n)]


def _as_list(options: Any, where: str) -> List[str]:
    if isinstance(options, (list, tuple)):
        out = [str(o) for o in options if o is not None and str(o).strip()]
        return list(dict.fromkeys(out))
    raise ProgramError(f"{where}: options must be a list of strings.")


# --------------------------------------------------------------------------- the Colors id

# A template look's Colors pick is the look's id plus COLORS: "outfit.colors". Builds before the
# US spelling named it ".colours", and what they recorded still does: prepared programs (their
# choices and filters), revisions (their pool keys), and the pins, kept values and edits a client
# or an agent holds. Those are read under the current id (current_*); nothing else is renamed.
COLORS = ".colors"
OLD_COLORS = ".colours"
# The Colors pick's about, as the pick judge reads it ("Colors (the colours of her outfit)"). The
# judge was trained on this wording, so it keeps the old spelling until the judge is retrained.
COLORS_ABOUT = "the colours of {}"
_OLD_COLORS_IN_KEY = re.compile(r"(^|\| )([^\s:|=]+)\.colours(?=: |=| \||$)")


def current_id(cid: str) -> str:
    """A choice id as this build names it: a ".colours" id recorded by an older build is ".colors"."""
    cid = str(cid)
    return cid[: -len(OLD_COLORS)] + COLORS if cid.endswith(OLD_COLORS) else cid


def current_keys(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A dict keyed by choice id (pins, kept values, edits, filters) with old ids read as current."""
    if not d or not any(str(k).endswith(OLD_COLORS) for k in d):
        return d
    return {current_id(k): v for k, v in d.items()}


def current_revision(rev: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A recorded revision whose pool keys name its picks ("outfit.colours: …", "… | outfit.colours=…")
    by their current ids, so an older build's revision still finds its pools."""
    pools = rev.get("pools") if isinstance(rev, dict) else None
    if not isinstance(pools, dict) or not any(OLD_COLORS in str(k) for k in pools):
        return rev
    return {**rev, "pools": {_OLD_COLORS_IN_KEY.sub(lambda m: m.group(1) + m.group(2) + COLORS, str(k)): v
                             for k, v in pools.items()}}


def current_entry(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A prepared program from an older build with its choices and filters under current ids."""
    if not isinstance(entry, dict):
        return entry
    choices = entry.get("choices")
    old = isinstance(choices, list) and any(
        isinstance(c, dict) and any(str(c.get(k) or "").endswith(OLD_COLORS) for k in ("id", "follows", "parent"))
        for c in choices)
    filters = entry.get("filters")
    if not old and not (isinstance(filters, dict) and current_keys(filters) is not filters):
        return entry
    out = dict(entry)
    if old:
        out["choices"] = [{**c, **{k: current_id(c[k]) for k in ("id", "follows", "parent") if c.get(k)}}
                          if isinstance(c, dict) else c for c in choices]
    if isinstance(filters, dict):
        out["filters"] = current_keys(filters)
    return out


_GROUP_ID = re.compile(r"^([a-z_][a-z0-9_]*)\[(\d+)\]\.([a-z_][a-z0-9_]*)$")
_SUBJECT_ID = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*?)(?:_?(?P<num>\d+))?(?:\[(?P<index>\d+)\])?\.(?P<attr>[A-Za-z_].*)$")


def subject_of(cid: str) -> Optional[Tuple[str, Optional[int], str]]:
    """Whose detail a pick is, from its id, as (subject, number, detail): `friends[2].age` is
    ("friends", 2, "age"), `woman1.hair` ("woman", 1, "hair"), `mother.outfit` ("mother",
    None, "outfit"), `friends[2].outfit.colors` ("friends", 2, "outfit.colors"). A plain id
    (`weather`, `outfit.colors`) is no subject's: None. Display structure only; whose detail
    it is for draws is draws.person_of (the id before its last part)."""
    cid = str(cid)
    if cid.startswith("param.") or (cid.endswith(COLORS) and cid.count(".") == 1):
        return None
    m = _SUBJECT_ID.match(cid)
    if not m:
        return None
    name, num, index = m.group("name"), m.group("num"), m.group("index")
    if num and index:  # team2[1].age: the number is part of the name
        name, num = f"{name}{num}", None
    n = index or num
    return name, int(n) if n else None, m.group("attr")


class _Runner:
    def __init__(self, seed: int, pins: Dict[str, Sequence[str]], loras: Dict[str, LoraInfo],
                 tool_params: Optional[Set[str]] = None, fixed: Optional[Dict[str, Any]] = None,
                 edits: Optional[Dict[str, Dict[str, Any]]] = None):
        self.rng = random.Random(seed)
        self.seed = seed
        self.pins = {k: [str(v) for v in vs] for k, vs in (pins or {}).items() if vs}
        self.fixed = fixed or {}  # exact replay: id -> value (overrides pins and RNG)
        # The user's own changes to a choice, applied at draw time with no model call:
        # {"add": [...], "remove": [...], "off": True}
        self.edits = edits or {}
        self.loras = loras
        self.tool_params = tool_params
        self.draws: List[Draw] = []
        self.by_id: Dict[str, Draw] = {}
        self.parts: List[str] = []
        self.lora_uses: List[LoraUse] = []
        self.params: Dict[str, Any] = {}
        self.groups: Dict[str, Dict[str, Any]] = {}

    # -- helpers
    def _record(self, d: Draw) -> None:
        if d.id in self.by_id:
            raise ProgramError(f'pick id "{d.id}" is used twice in one run. Give each pick its own id (inside loops use f"people[{{i+1}}].age").')
        self.draws.append(d)
        self.by_id[d.id] = d

    def _choose(self, cid: str, options: List[str], uniform: bool, exclude: Iterable[str] = ()) -> Tuple[Optional[str], bool]:
        if cid in self.fixed and self.fixed[cid] in options:
            return self.fixed[cid], True
        excl = {str(x) for x in (exclude or []) if x is not None}
        pool = [(o, w) for o, w in zip(options, _weights(len(options), uniform)) if o not in excl] or list(zip(options, _weights(len(options), uniform)))
        pinned = False
        pins = self.pins.get(cid)
        if pins:
            narrowed = [(o, w) for o, w in pool if o in pins]
            if narrowed:
                pool, pinned = narrowed, len(narrowed) == 1
        if not pool:
            return None, False
        total = sum(w for _, w in pool)
        r = self.rng.random() * total
        for o, w in pool:
            r -= w
            if r <= 0:
                return o, pinned
        return pool[-1][0], pinned

    def _follow_id(self, by: Any) -> Optional[str]:
        for d in reversed(self.draws):
            if d.kind == "pick" and d.value == by:
                return d.id
        return None

    # -- API
    def pick(self, id: str, options: Any = None, label: str = "", by: Any = None, source: str = "text",
             line: Optional[int] = None, exclude: Any = None, hidden: bool = False, added: bool = False,
             about: Optional[str] = None, phase: Optional[int] = None, seed: Any = None,
             cls: Optional[str] = None, where: Any = None, said: Any = None, shared: bool = False) -> Optional[str]:
        cid = str(id)
        if shared:
            value = self.pick(cid, options, label, by, source, line, exclude, hidden, added, about, phase, seed, cls, where, said)
            if cid in self.by_id:
                self.by_id[cid].shared = True
            return value
        if about is not None or phase is not None or seed is not None or cls is not None or said is not None:
            return self._spec_pick(cid, options, label, by, source, line, exclude, hidden, added, about, phase, seed, cls,
                                   where, said)
        if added:
            source = "added"
        if source not in SOURCES:
            source = "text"
        follows = None
        if isinstance(options, dict):
            if by is None:
                raise ProgramError(f'pick("{cid}"): options is a dict, so pass by=<the earlier pick it depends on>.')
            follows = self._follow_id(by)
            opts = options.get(by)
            if opts is None:
                opts = options.get(str(by))
            if opts is None:
                opts = next(iter(options.values()), [])
            opts = _as_list(opts, f'pick("{cid}")')
        else:
            opts = _as_list(options if options is not None else [], f'pick("{cid}")')
        edit = self.edits.get(cid) or {}
        if edit.get("off"):
            return None  # removed by the user: the detail is left to the image model
        written = opts
        if edit.get("remove"):
            opts = [o for o in opts if o not in set(edit["remove"])]
        for extra in edit.get("add") or []:
            if str(extra).strip() and str(extra) not in opts:
                opts.append(str(extra))
        if not opts:  # never leave a choice empty: removing everything means the program's own
            opts = written
        if not opts:
            return None
        value, pinned = self._choose(cid, opts, uniform=(source == "list"), exclude=exclude or ())
        self._record(Draw(cid, value, "pick", label or _label_from_id(cid), source, line, bool(hidden), pinned, opts, follows))
        return value

    def _spec_pick(self, cid: str, options: Any, label: str, by: Any, source: str, line: Optional[int], exclude: Any,
                   hidden: bool, added: bool, about: Optional[str], phase: Optional[int], seed: Any,
                   cls: Optional[str] = None, where: Any = None, said: Any = None) -> Optional[str]:
        """A pick with a spec (draws.py), run the plain way for discovery and validation:
        seeds stand in for options it doesn't list, and it is recorded even with none. A
        pick bound to a vocabulary list (cls=) runs on the list's values instead. A pick with
        said= draws the user's words unless pinned (said_value)."""
        seeds = _as_list(seed if seed is not None else [], f'pick("{cid}") seed')
        said = said_value(said) if source != "list" else ""
        if said:
            seeds, added, source = list(dict.fromkeys([said, *seeds])), False, "text"
        leaf = bound_leaf(cid, cls, source, options)
        written = list(options) if isinstance(options, (list, tuple)) else options
        if leaf is not None:  # opt-in values (ages under 18) only when asked: never in a plain run
            written = [v.text for v in leaf.eligible() if not v.opt_in]
        elif isinstance(written, dict) or written:
            if isinstance(written, dict):
                written = {k: [*seeds, *(v or [])] for k, v in written.items()}
            else:
                written = [*seeds, *written]
        else:
            written = seeds
        if said and leaf is not None and said not in written:
            written = [said, *written]
        n = len(self.draws)
        held = said and holds_said(cid, said, written if isinstance(written, list) else [], self.pins, self.fixed) and not [
            x for x in (self.edits.get(cid) or {}).get("remove") or [] if str(x) == said]
        if held:
            self.pins[cid] = [said]
        try:
            value = self.pick(cid, written, label, by, source, line, exclude, hidden, added) if written else None
        finally:
            if held:
                self.pins.pop(cid, None)
        if len(self.draws) == n:  # off, or nothing to draw: still a choice
            if (self.edits.get(cid) or {}).get("off"):
                return None
            self._record(Draw(cid, None, "pick", label or _label_from_id(cid), "added" if added else (source if source in SOURCES else "text"),
                              line, bool(hidden), False, []))
        d = self.draws[-1]
        d.phase, d.about = int(phase) if isinstance(phase, int) else None, str(about or "")
        d.cls = leaf.id if leaf is not None else ""
        d.where = where if isinstance(where, dict) else (str(where).strip() if isinstance(where, str) else "")
        d.said = said
        if leaf is not None and leaf.slots and value is not None and "{" in str(value):
            value = self._palette(cid, d, leaf, value, source, line, hidden)
        elif isinstance(value, str) and "{" in value:
            from prompt_programs.vocab import fill
            value = d.value = fill(value, None)
        return value

    def _palette(self, cid: str, d: "Draw", leaf: Any, template: str, source: str, line: Optional[int],
                 hidden: bool) -> str:
        """A template pick's colors (see draws._Exec._palette), the plain way: a palette
        pick recorded right after the template, and the template filled with it."""
        from prompt_programs.vocab import fill, tags_match, vocabulary
        palette = vocabulary().get(leaf.slots)
        if palette is None:
            return template
        tv = leaf.value(str(template))
        values = palette.eligible()
        if tv is not None and tv.palette:
            values = [v for v in values if tags_match(v.tags, tv.palette)] or values
        ccid = cid + COLORS
        n = len(self.draws)
        chosen = self.pick(ccid, [v.text for v in values], "Colors", None, source, line, None, hidden)
        if len(self.draws) > n:
            c = self.draws[-1]
            c.phase, c.about, c.cls, c.follows = d.phase, COLORS_ABOUT.format(d.about or d.label), palette.id, cid
        pv = palette.value(str(chosen)) if chosen is not None else None
        filled = fill(str(template), pv.roles if pv is not None else None)
        d.value = filled
        return filled

    def pick_lora(self, id: str, names: Any = None, label: str = "", source: str = "text", line: Optional[int] = None,
                  phase: Optional[int] = None) -> Optional[str]:
        cid = str(id)
        names = _as_list(names if names is not None else [], f'pick_lora("{cid}")')
        known = lora_names(names, self.loras)
        if not known:
            raise ProgramError(f'pick_lora("{cid}"): none of {names} are in the LoRA list. Use the exact names given.')
        value, pinned = self._choose(cid, known, uniform=True)
        self._record(Draw(cid, value, "lora", label or _label_from_id(cid), source, line, False, pinned, known))
        info = self.loras.get(_lora_key(value))
        if info is not None:
            self.lora_uses.append(LoraUse(info.name, info.weight, info.trigger, info.path, cid))
        return LoraName(value) if isinstance(value, str) else value

    def param(self, name: str, low: Any = None, high: Any = None, label: str = "", source: str = "text",
              line: Optional[int] = None) -> Any:
        pname = str(name)
        if self.tool_params is not None and pname not in self.tool_params:
            raise ProgramError(f'param("{pname}"): this tool has no parameter called "{pname}". Available: {sorted(self.tool_params)}.')
        if source == "added":
            raise ProgramError(f'param("{pname}"): parameters only vary when the user asks for it.')
        try:
            lo, hi = float(low), float(high)
        except (TypeError, ValueError):
            raise ProgramError(f'param("{pname}"): give a low and high number.') from None
        if lo > hi:
            lo, hi = hi, lo
        is_int = float(low).is_integer() and float(high).is_integer() and isinstance(low, int) and isinstance(high, int)
        cid = f"param.{pname}"
        if cid in self.fixed:
            value = self.fixed[cid]
        else:
            pins = self.pins.get(cid)
            if pins:
                try:
                    value = float(pins[0])
                except ValueError:
                    value = None
            else:
                value = None
            if value is None:
                value = self.rng.randint(int(lo), int(hi)) if is_int else round(self.rng.uniform(lo, hi), 1)
        if is_int:
            value = int(value)
        d = Draw(cid, value, "param", label or pname.replace("_", " ").capitalize(), source, line, False, bool(self.pins.get(cid)))
        d.options = [f"{lo:g}", f"{hi:g}"]
        self._record(d)
        self.params[pname] = value
        return value

    def group(self, id: str, count: Any, label: str = "", source: str = "text", line: Optional[int] = None) -> int:
        try:
            n = max(0, min(12, int(count)))
        except (TypeError, ValueError):
            raise ProgramError(f'group("{id}"): count must be a number.') from None
        self.groups[str(id)] = {"id": str(id), "count": n, "label": label or _label_from_id(str(id)), "source": source, "line": line}
        return n

    def emit(self, *parts: Any) -> None:
        self.parts.extend(flatten_parts(parts, sum(map(len, self.parts))))


def flatten_parts(parts: Sequence[Any], used: int = 0) -> List[str]:
    """What emit() writes for its arguments: each value as text, lists and tuples in
    order, None and LoRA names skipped (a LoRA is turned on, never written into the
    prompt). `used` is the prompt text already emitted: the whole prompt is capped."""
    out: List[str] = []
    stack = [iter(parts)]
    while stack:
        for p in stack[-1]:
            if p is None or isinstance(p, LoraName):
                continue
            if isinstance(p, (list, tuple)):
                if len(stack) > 32:
                    raise _limit("emit() was given lists nested too deeply.")
                stack.append(iter(p))
                break
            s = _text(p).strip()
            if s:
                used += len(s)
                if used > MAX_PROMPT_CHARS:
                    raise _limit(f"the prompt is too long (over {MAX_PROMPT_CHARS:,} characters).")
                out.append(s)
        else:
            stack.pop()
    return out


def bound_leaf(cid: str, cls: Optional[str], source: str = "text", options: Any = None) -> Any:
    """The vocabulary leaf a pick binds to with cls=, or None without one. A cls that
    names no list, or one on a user list, is the writer's mistake: said so it can fix it."""
    if cls is None or not str(cls).strip():
        return None
    from prompt_programs.vocab import vocabulary
    if source == "list" or options:
        raise ProgramError(f'pick("{cid}"): cls= binds a pick to a vocabulary list, so it takes no options of its '
                           'own and is never a user list. Drop cls=, or drop the options.')
    vocab = vocabulary()
    leaf = vocab.resolve(cls)
    if leaf is None:
        import difflib
        near = difflib.get_close_matches(str(cls), list(vocab.leaves), n=1, cutoff=0.6)
        hint = f' Did you mean cls="{near[0]}"?' if near else " Use one of the listed ids exactly, or leave cls out."
        raise ProgramError(f'pick("{cid}"): cls="{cls}" isn\'t a vocabulary list.{hint}')
    return leaf


def _lora_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _label_from_id(cid: str) -> str:
    m = _GROUP_ID.match(cid)
    base = m.group(3) if m else cid.split(".")[-1]
    return base.replace("_", " ").strip().capitalize()


_ARTICLE = re.compile(r"\b(a|an|the)\s+(?=(?:a|an|the)\s)", re.I)


# An article and the word after it. A capital "A" mid-sentence is a letter, not an article
# ("Plan A", "vitamin A", '"A is for apple"', "(A and B)"): only a lowercase one, or one
# starting the text or a sentence, is corrected.
_WORD = r"(?:[A-Za-z][\w'-]*|\d[\d,]*[\w'-]*)"   # commas only inside a number ("18,000-seat")
_A_AN = re.compile(rf"(?:(?<=^)|(?<=[.!?]\s))(A|An)\s+({_WORD})|\b(a|an)\s+({_WORD})")
# Words whose sound doesn't follow their first letter.
_AN_WORDS = {"hour", "hours", "hourly", "honest", "honestly", "honor", "honour", "honorable", "honourable", "heir", "heiress"}
# Vowel-initial words said with a consonant sound ("a unicorn", "a European", "a one-off").
_A_WORDS = ("unic", "unif", "unio", "uniq", "unis", "unit", "univ", "use", "usu", "uti", "uto", "uga", "ukr", "uru",
            "uro", "ura", "eu", "one", "once", "ubiq")


def _number_wants_an(digits: str) -> bool:
    """A number said with a vowel sound: eight…, eleven, eighteen ("an 8–10-year-old",
    "an 11-year-old", "an 18,000-seat arena", "an 80–84-year-old")."""
    digits = digits.replace(",", "")
    return digits.startswith("8") or (len(digits) % 3 == 2 and digits[:2] in ("11", "18"))


def _wants_an(word: str) -> bool:
    if word[0].isdigit():
        return _number_wants_an(re.match(r"[\d,]+", word).group(0))
    if len(word) > 1 and word.isupper():  # an initialism, said letter by letter: "an LED", "a USB"
        return word[0] in "AEFHILMNORSX"
    w = word.lower()
    if w in _AN_WORDS:
        return True
    return w[0] in "aeiou" and not w.startswith(_A_WORDS)


def _fix_article(m: "re.Match[str]") -> str:
    art, word = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    if len(word) == 1 and not word.isdigit():  # "a B-movie" reads by letter; "a A" is too rare to guess
        return m.group(0)
    new = "an" if _wants_an(word) else "a"
    return f"{new.capitalize() if art[0].isupper() else new} {word}"


def tidy_text(parts: List[str]) -> str:
    s = " ".join(parts)
    s = re.sub(r"\s+", " ", s)
    # "a" written before a value that brings its own ("A a candid snapshot"): keep the value's
    s = _ARTICLE.sub("", s)
    s = _A_AN.sub(_fix_article, s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([,;])\1+", r"\1", s)
    s = re.sub(r",\s*\.", ".", s)
    s = re.sub(r"\.\s*\.", ".", s)
    s = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    return s.strip()


# --------------------------------------------------------------------------- the sandbox
# The step budget counts the program's lines, but one line can still ask C code for a lot
# of work: "a" * 10**9, s.replace("", s), f"{x:>999999999}", max(range(10**9)). Every
# operation that can grow a value is checked before it runs (compile_program rewrites
# +, *, % and the growing methods into calls to a _Guard; check() lets those methods be
# called only where they're written, never stored or passed), what C code compares, hashes
# or sorts is size-checked first (expanded_size), and a run's CPU time is capped. Prompts
# are short: legitimate programs are far inside every limit.

MAX_SIZE = 100_000          # characters of a string, or items of a list, one operation may make
MAX_MADE = 5_000_000        # characters and items one run's operations may make in all
MAX_RANGE = 10_000          # numbers in a range()
MAX_INT_BITS = 1024         # size of an int a multiplication may make
MAX_FORMAT_NUMBER = 1000    # a width or precision in a format spec or % format
MAX_PROMPT_CHARS = 100_000  # the emitted prompt
MAX_CPU_SECONDS = 1.0       # CPU time of one run (thread time: waiting for the GIL doesn't count)

_SCALARS = (str, int, float, bool, type(None))
_SEQS = (str, bytes, list, tuple)
_CONVERSIONS = {115: str, 114: repr, 97: ascii}


def _program_line() -> Optional[int]:
    f = sys._getframe(1)
    while f is not None:
        if f.f_code.co_filename == "<program>":
            return f.f_lineno
        f = f.f_back
    return None


def _limit(msg: str) -> ProgramError:
    line = _program_line()
    return ProgramError(f"Line {line}: {msg}" if line is not None else msg[:1].upper() + msg[1:])


def measure(value: Any, limit: int = MAX_SIZE) -> int:
    """About how many characters a value's text takes, counted until it passes `limit`.
    Containers are walked without recursion, so lists that hold the same list many
    times over stop at the limit instead of writing it all out."""
    total = 0
    stack = [value]
    while stack:
        v = stack.pop()
        t = type(v)
        if t is str or t is bytes:
            total += len(v)
        elif t is int:
            total += v.bit_length() // 3 + 2
        elif t in (list, tuple, set, frozenset):
            total += 2 + 2 * len(v)
            if len(v) and set(map(type, v)) == {str}:
                total += sum(map(len, v))
            else:
                stack.extend(v)
        elif t is dict:
            total += 2 + 4 * len(v)
            stack.extend(v.keys())
            stack.extend(v.values())
        elif isinstance(v, (str, bytes)):
            total += len(v)
        else:
            total += 8
        if total > limit:
            break
    return total


def _text_ok(value: Any) -> None:
    """Refuse a value whose text would be too long to make."""
    if type(value) is not str and not isinstance(value, _SCALARS) and measure(value) > MAX_SIZE:
        raise _limit(f"this value's text is too long (over {MAX_SIZE:,} characters).")


def _text(value: Any) -> str:
    """str(value), refused when the text would be too long."""
    _text_ok(value)
    return str(value)


# Comparing, hashing or sorting containers walks them in C, where neither the step nor the
# CPU budget can stop it, and containers can hold the same container many times over:
# twenty-seven rounds of `a = [a, a]` make a list that `==` walks 2**27 times while it
# holds 28 lists. So a container is compared, hashed or sorted only when its EXPANDED size
# (every element counted each time it is reached, shared ones included) is within MAX_SIZE.
# The check is memoized by id, so it costs one visit per distinct container: a list of
# scalars costs one C pass.

_VIEWS = (type({}.keys()), type({}.values()), type({}.items()))
_CONTAINERS = frozenset((list, tuple, dict, set, frozenset, *_VIEWS))
_LEAVES = frozenset((str, int, float, bool, type(None), bytes, range))


def _members(v: Any) -> Any:
    return [*v.keys(), *v.values()] if type(v) is dict else v if type(v) not in _VIEWS else list(v)


def expanded_size(value: Any, limit: int = MAX_SIZE) -> int:
    """How many elements walking `value` reaches, every repeat counted, stopping (with a
    ProgramError) past `limit` or at a container that holds itself."""
    if type(value) not in _CONTAINERS:
        return 1
    sizes: Dict[int, Tuple[int, Any]] = {}   # id -> (size, the object, kept alive for the walk)
    path: Set[int] = set()
    stack: List[Tuple[Any, Any]] = [(value, None)]
    while stack:
        v, members = stack.pop()
        i = id(v)
        if members is not None:  # its members are all sized
            n = 1 + sum(sizes[id(m)][0] if type(m) in _CONTAINERS else 1 for m in members)
            if n > limit:
                raise _limit(f"this value is too big to compare or sort (over {limit:,} items, "
                             "counting each time a list holds the same list).")
            sizes[i] = (n, v)
            path.discard(i)
            continue
        if i in sizes:
            continue
        if i in path:
            raise _limit("this value holds itself, so it can't be compared or sorted.")
        members = _members(v)
        if set(map(type, members)) <= _LEAVES:
            if len(members) + 1 > limit:
                raise _limit(f"this value is too big to compare or sort (over {limit:,} items).")
            sizes[i] = (len(members) + 1, v)
            continue
        path.add(i)
        stack.append((v, members))
        stack.extend((m, None) for m in members if type(m) in _CONTAINERS and id(m) not in sizes)
    return sizes[id(value)][0]


def _compared(value: Any) -> Any:
    """A value about to be compared or hashed (an operand of ==, <, in, a dict key, a set
    member, an .index/.count/.get argument): refused when it's too big to walk."""
    if type(value) in _CONTAINERS:
        expanded_size(value)
    return value


def _sorted(iterable: Any, *, key: Any = None, reverse: Any = False) -> List[Any]:
    items = list(iterable)
    if key is None:
        expanded_size(items)
        return sorted(items, reverse=reverse)
    keys = [key(x) for x in items]   # once each, as sorted() does
    expanded_size(keys)
    return [items[i] for i in sorted(range(len(items)), key=keys.__getitem__, reverse=reverse)]


_NO_DEFAULT = object()


def _extreme(fn: Callable[..., Any]) -> Callable[..., Any]:
    def pick_one(*args: Any, key: Any = None, default: Any = _NO_DEFAULT) -> Any:
        if not args:
            return fn()  # min()/max()'s own error
        items = list(args[0]) if len(args) == 1 else list(args)
        if not items and default is not _NO_DEFAULT:
            return default
        if key is None:
            expanded_size(items)
            return fn(items)
        keys = [key(x) for x in items]
        expanded_size(keys)
        return items[fn(range(len(items)), key=keys.__getitem__)] if items else fn(items)
    pick_one.__name__ = fn.__name__
    return pick_one


def _hashed(fn: Callable[..., Any]) -> Callable[..., Any]:
    """set() and dict(): what they hash is checked first (an iterator is read into a list)."""
    def make(*args: Any, **kw: Any) -> Any:
        if args and type(args[0]) is not dict:
            args = (list(args[0]), *args[1:])
        for a in args:
            expanded_size(a)
        return fn(*args, **kw)
    make.__name__ = fn.__name__
    return make


class _StrBuiltin:
    """The program's str(): the real str, refusing text too long to make. str.lower and
    the other methods are str's own."""
    __slots__ = ()

    def __call__(self, *args: Any, **kw: Any) -> str:
        # str(x), str(object=x), str(b, encoding): whichever way it's called, the object's
        # text is measured (bytes decode to no more characters than they hold).
        if args or "object" in kw:
            _text_ok(args[0] if args else kw["object"])
        return str(*args, **kw)

    def __getattr__(self, name: str) -> Any:
        return getattr(str, name)


def _range(*args: Any) -> range:
    r = range(*args)
    try:
        n = len(r)
    except OverflowError:
        n = MAX_RANGE + 1
    if n > MAX_RANGE:
        raise _limit(f"range() is limited to {MAX_RANGE:,} numbers.")
    return r


_PERCENT = re.compile(r"%(?:\([^)]*\))?([^a-zA-Z%]*)")


def _spec_ok(spec: str, what: str, star: bool = False) -> None:
    """No width or precision over MAX_FORMAT_NUMBER, and (`star`: a % format) none taken
    from the arguments."""
    if (star and "*" in spec) or any(int(d) > MAX_FORMAT_NUMBER for d in re.findall(r"\d+", spec)):
        raise _limit(f"{what}: widths and precisions go up to {MAX_FORMAT_NUMBER}.")


class _Guard:
    """One run's checks on the operations that can grow a value (see compile_program)."""

    def __init__(self) -> None:
        self.made = 0

    def _made(self, v: Any) -> Any:
        if isinstance(v, _SEQS):
            n = len(v)
            if n > MAX_SIZE:
                raise _limit(f"this makes a value too long (over {MAX_SIZE:,} characters or items).")
            self.made += n
            if self.made > MAX_MADE:
                raise _limit("the program builds too much text (it may grow a value in a loop).")
        return v

    @staticmethod
    def _before(op: str, a: Any, b: Any) -> None:
        if op == "*":
            if isinstance(a, int) and isinstance(b, int):
                if a.bit_length() + b.bit_length() > MAX_INT_BITS:
                    raise _limit("this number is too big.")
                return
            seq, n = (a, b) if isinstance(a, _SEQS) else (b, a)
            if isinstance(seq, _SEQS) and isinstance(n, int) and len(seq) * n > MAX_SIZE:
                raise _limit(f"this makes a value too long (over {MAX_SIZE:,} characters or items).")
        elif op == "+":
            if isinstance(a, _SEQS) and isinstance(b, _SEQS) and len(a) + len(b) > MAX_SIZE:
                raise _limit(f"this makes a value too long (over {MAX_SIZE:,} characters or items).")
        elif op == "%" and isinstance(a, (str, bytes)):
            for spec in _PERCENT.findall(a if isinstance(a, str) else a.decode("latin-1")):
                _spec_ok(spec, "a % format", star=True)
            if not isinstance(b, _SCALARS) and measure(b) > MAX_SIZE:
                raise _limit(f"this value's text is too long (over {MAX_SIZE:,} characters).")

    def op(self, op: str, a: Any, b: Any) -> Any:
        self._before(op, a, b)
        return self._made(a + b if op == "+" else a * b if op == "*" else a % b)

    def aug(self, op: str, a: Any, b: Any) -> Any:
        """x += y (and *=, %=): in place where the value allows it, as Python does."""
        self._before(op, a, b)
        return self._made(operator.iadd(a, b) if op == "+" else operator.imul(a, b) if op == "*" else operator.imod(a, b))

    def aug_item(self, obj: Any, key: Any, op: str, b: Any) -> None:
        obj[key] = self.aug(op, obj[key], b)

    def call(self, obj: Any, name: str, *args: Any, **kw: Any) -> Any:
        """obj.join / .replace / .extend: the result's size is known before it's made."""
        if isinstance(obj, (type, _StrBuiltin)) and args:  # str.join(sep, items): the unbound form
            obj, args = args[0], args[1:]
        fn = getattr(obj, name)
        if name == "join" and isinstance(obj, (str, bytes)) and len(args) == 1:
            items = args[0] if isinstance(args[0], (list, tuple)) else list(args[0])
            args = (items,)
            try:
                size = sum(map(len, items)) + len(obj) * max(0, len(items) - 1)
            except TypeError:  # not all text: join says what's wrong
                size = 0
            if size > MAX_SIZE:
                raise _limit(f"this makes a value too long (over {MAX_SIZE:,} characters or items).")
        elif name == "replace" and isinstance(obj, (str, bytes)) and len(args) >= 2:
            old, new = args[0], args[1]
            count = args[2] if len(args) > 2 else kw.get("count", -1)
            if isinstance(old, type(obj)) and isinstance(new, type(obj)) and len(new) > len(old):
                hits = obj.count(old) if old else len(obj) + 1
                if isinstance(count, int) and count >= 0:
                    hits = min(hits, count)
                if len(obj) + hits * (len(new) - len(old)) > MAX_SIZE:
                    raise _limit(f"this makes a value too long (over {MAX_SIZE:,} characters or items).")
        elif name == "extend" and isinstance(obj, list) and len(args) == 1:
            items = args[0] if isinstance(args[0], _SEQS) else list(args[0])
            args = (items,)
            if len(obj) + len(items) > MAX_SIZE:
                raise _limit(f"this makes a value too long (over {MAX_SIZE:,} characters or items).")
            self.made += len(items)
        out = fn(*args, **kw)
        return self._made(out) if isinstance(out, (str, bytes)) else out

    def fmt(self, value: Any, conversion: int, spec: str) -> str:
        """One {value!r:spec} of an f-string."""
        if conversion == -1 and not spec and type(value) is str:
            return value
        if conversion in _CONVERSIONS:
            if not isinstance(value, _SCALARS) and measure(value) > MAX_SIZE:
                raise _limit(f"this value's text is too long (over {MAX_SIZE:,} characters).")
            value = _CONVERSIONS[conversion](value)
        if spec:
            if len(spec) > 40:
                raise _limit("this f-string's format spec is too long.")
            _spec_ok(spec, "an f-string format")
            return format(value, spec)
        return _text(value)

    def fstr(self, s: str) -> str:
        return self._made(s)


class _Guarded(ast.NodeTransformer):
    """Rewrites the operations that can grow a value into calls to a _Guard (the
    `__pp_*` names: a program can't write a name starting with __)."""

    _OPS = {ast.Add: "+", ast.Mult: "*", ast.Mod: "%"}

    @staticmethod
    def _call(name: str, args: List[ast.expr], node: ast.AST, keywords: Optional[List[ast.keyword]] = None) -> ast.Call:
        return ast.copy_location(ast.Call(ast.Name(name, ast.Load()), args, keywords or []), node)

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        op = self._OPS.get(type(node.op))
        return self._call("__pp_op", [ast.Constant(op), node.left, node.right], node) if op else node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST:
        self.generic_visit(node)
        op = self._OPS.get(type(node.op))
        if op is None:
            return node
        if isinstance(node.target, ast.Name):
            value = self._call("__pp_aug", [ast.Constant(op), ast.Name(node.target.id, ast.Load()), node.value], node)
            return ast.copy_location(ast.Assign([node.target], value), node)
        if isinstance(node.target, ast.Subscript):
            t = node.target
            return ast.copy_location(ast.Expr(self._call("__pp_aug_item", [t.value, t.slice, ast.Constant(op), node.value],
                                                          node)), node)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr in _GROWING_METHODS:
            return self._call("__pp_call", [node.func.value, ast.Constant(node.func.attr), *node.args], node, node.keywords)
        if isinstance(node.func, ast.Attribute) and node.func.attr in _COMPARING_METHODS:
            node.args = [self._compared(a) for a in node.args]
            node.keywords = [ast.keyword(k.arg, self._compared(k.value)) for k in node.keywords]
        return node

    # Operands that C code compares or hashes go through __pp_cmp (_compared) first.
    def _compared(self, value: ast.expr) -> ast.expr:
        return self._call("__pp_cmp", [value], value)

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if not all(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            node.left = self._compared(node.left)
            node.comparators = [self._compared(c) for c in node.comparators]
        return node

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.slice, ast.Slice):  # a slice copies: counted like any value made
            return self._call("__pp_made", [node], node) if isinstance(node.ctx, ast.Load) else node
        node.slice = self._compared(node.slice)  # a dict key is hashed
        return node

    def visit_Dict(self, node: ast.Dict) -> ast.AST:
        self.generic_visit(node)
        node.keys = [k if k is None else self._compared(k) for k in node.keys]
        return node

    def visit_Set(self, node: ast.Set) -> ast.AST:
        self.generic_visit(node)
        node.elts = [self._compared(e) for e in node.elts]
        return node

    def visit_DictComp(self, node: ast.DictComp) -> ast.AST:
        self.generic_visit(node)
        node.key = self._compared(node.key)
        return node

    def visit_SetComp(self, node: ast.SetComp) -> ast.AST:
        self.generic_visit(node)
        node.elt = self._compared(node.elt)
        return node

    def visit_FormattedValue(self, node: ast.FormattedValue) -> ast.AST:
        self.generic_visit(node)
        spec = node.format_spec if node.format_spec is not None else ast.Constant("")
        node.value = self._call("__pp_fmt", [node.value, ast.Constant(node.conversion), spec], node)
        node.conversion, node.format_spec = -1, None
        return node

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        self.generic_visit(node)
        return self._call("__pp_fstr", [node], node)


def compile_program(tree: ast.Module) -> Any:
    """Compile a checked program for execute(), its growing operations guarded."""
    tree = ast.fix_missing_locations(_Guarded().visit(tree))
    return compile(tree, "<program>", "exec")


_SANDBOX_BUILTINS: Dict[str, Any] = {**_SAFE_BUILTINS, "range": _range, "str": _StrBuiltin(), "sorted": _sorted,
                                      "min": _extreme(min), "max": _extreme(max), "set": _hashed(set),
                                      "dict": _hashed(dict)}


def _api_call(fn: Callable[..., Any]) -> Callable[..., Any]:
    """An API function as the program calls it: arguments whose text would be huge are
    refused before the runtime turns them into text."""
    def call(*args: Any, **kw: Any) -> Any:
        for v in (*args, *kw.values()):
            if not isinstance(v, _SCALARS) and measure(v) > MAX_SIZE:
                raise _limit(f"this argument is too big (over {MAX_SIZE:,} characters).")
        return fn(*args, **kw)
    return call


def execute(code: Any, api: Any, passthrough: Tuple[type, ...] = ()) -> None:
    """Run compiled program code against an API object (its pick/pick_lora/param/group/
    emit) in the sandbox: only _SANDBOX_BUILTINS, a step budget, a CPU budget and the
    size checks. Errors become a ProgramError naming the program's line; ProgramError
    and `passthrough` exceptions propagate as they are."""
    guard = _Guard()
    env: Dict[str, Any] = {"__builtins__": dict(_SANDBOX_BUILTINS), "__pp_op": guard.op, "__pp_aug": guard.aug,
                           "__pp_aug_item": guard.aug_item, "__pp_call": guard.call, "__pp_fmt": guard.fmt,
                           "__pp_fstr": guard.fstr, "__pp_made": guard._made, "__pp_cmp": _compared}
    env["__builtins__"]["list"] = lambda *a: guard._made(list(*a))   # a copy counts as made
    for name in API_NAMES:
        env[name] = _api_call(getattr(api, name))
    steps = 0
    started = time.thread_time()

    def tracer(frame, event, arg):  # step budget: a program must finish quickly
        nonlocal steps
        if frame.f_code.co_filename == "<program>":
            steps += 1
            if steps > MAX_STEPS or (steps & 63 == 0 and time.thread_time() - started > MAX_CPU_SECONDS):
                raise ProgramError("Program ran too long (it may loop forever).")
            return tracer
        return None

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        exec(code, env)  # noqa: S102 — checked AST, no builtins beyond _SANDBOX_BUILTINS
    except (ProgramError, *passthrough):
        raise
    except Exception as e:  # report like a traceback line the model can act on
        tb = e.__traceback__
        line = None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == "<program>":
                line = tb.tb_lineno
            tb = tb.tb_next
        raise ProgramError(f"Line {line}: {type(e).__name__}: {e}") from None
    finally:
        sys.settrace(old)


@functools.lru_cache(maxsize=256)
def _compiled(source: str) -> Any:
    """check() and compile_program() for a source, once: discovery and draws run the
    same program many times. Code objects are immutable, so sharing one is safe."""
    return compile_program(check(source))


def run(source: str, seed: int, pins: Optional[Dict[str, Sequence[str]]] = None,
        loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None,
        fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Dict[str, Any]]] = None) -> RunResult:
    """Run a program once. Deterministic for a given (source, seed, pins, fixed)."""
    code = _compiled(source)
    runner = _Runner(seed, pins or {}, {_lora_key(lo.name): lo for lo in (loras or [])}, tool_params, fixed, edits)
    execute(code, runner)
    prompt = tidy_text(runner.parts)
    if not prompt:
        raise ProgramError("The program emitted no prompt text. Call emit(...) with the finished prompt.")
    for lu in runner.lora_uses:  # the trigger must be in the prompt for the LoRA to work
        if lu.trigger and lu.trigger.lower() not in prompt.lower():
            prompt = f"{lu.trigger}, {prompt}"
    return RunResult(prompt, runner.draws, runner.lora_uses, runner.params, runner.groups, seed)


# --------------------------------------------------------------------------- discovery

@dataclass
class Choice:
    id: str
    kind: str
    label: str
    source: str
    line: Optional[int]
    options: List[str]
    hidden: bool = False
    follows: Optional[str] = None               # options keyed by this pick's value
    parent: Optional[str] = None                # only exists when parent's value is in `when`
    when: List[str] = field(default_factory=list)
    group: Optional[str] = None                 # "people" for people[2].age
    index: Optional[int] = None
    attr: Optional[str] = None
    phase: Optional[int] = None                 # pick specs (see draws.py)
    about: Optional[str] = None
    deps: List[str] = field(default_factory=list)   # picks this one's structure depends on
    cls: Optional[str] = None                   # the vocabulary list it is bound to
    where: Any = None                           # the user's words, or {local facet: value}, narrowing that list
    said: Optional[str] = None                  # the user's own words it stands for, drawn unless they choose others
    shared: bool = False                        # one value for every subject, marked shared=True
    seen: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in vars(self).items() if v not in (None, [], False) and k != "seen"}
        d["id"], d["kind"], d["label"], d["source"], d["options"] = self.id, self.kind, self.label, self.source, self.options
        return d


_SUBJECT_LABEL = re.compile(r"^(?P<subject>[A-Za-z][A-Za-z ]*?)\s*(?P<index>\d{1,2})\s*[:·-]?\s+(?P<attr>[A-Za-z][\w ]*)$")


def _group_by_subject(choices: Dict[str, "Choice"], order: List[str], groups: Dict[str, Dict[str, Any]]) -> None:
    """Show one subject's details together. Picks written out by hand per person
    ("Girl 1 Hair", "Girl 1 Eyes", "Girl 2 Hair", or ids like girl[1].hair) become a group,
    as if the program had looped with group(): the card shows Girl ×2 with Hair and Eyes
    as rows. Ids, pins and draws are unchanged; only the display structure is added."""
    found: Dict[str, List[Tuple["Choice", int, str]]] = {}
    labels: Dict[str, str] = {}
    for cid in order:
        c = choices[cid]
        if c.group or c.kind == "param" or len(c.label) > 80:  # a long label is no "Girl 1 Hair" (and slow to match)
            continue
        m = _SUBJECT_LABEL.match(c.label.strip())
        if not m:
            continue
        subject = m.group("subject").strip()
        key = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")
        found.setdefault(key, []).append((c, int(m.group("index")), m.group("attr").strip()))
        labels.setdefault(key, subject)
    for key, members in found.items():
        indices = {i for _, i, _ in members}
        attrs: Dict[str, Set[int]] = {}
        for _, i, a in members:
            attrs.setdefault(a.lower(), set()).add(i)
        if len(indices) < 2 or not any(len(v) >= 2 for v in attrs.values()):
            continue  # one person, or nothing shared between them: not a group
        cells = [(i, a.lower()) for _, i, a in members]
        if len(cells) != len(set(cells)):
            continue  # two choices for one person's detail (alternatives by branch): a grid cell holds one
        gid = key if key not in groups else f"{key}_subjects"
        for c, i, a in members:
            c.group, c.index, c.attr, c.label = gid, i, re.sub(r"[^a-z0-9]+", "_", a.lower()).strip("_"), a[:1].upper() + a[1:]
        first = members[0][0]
        groups[gid] = {"id": gid, "count": max(indices), "label": labels[key], "source": first.source, "line": first.line}
    for cid in order:  # people[1].age written by hand, with no group() call
        c = choices[cid]
        if c.group and c.group not in groups:
            n = max((x.index or 0) for x in choices.values() if x.group == c.group)
            groups[c.group] = {"id": c.group, "count": n, "label": c.group.replace("_", " ").capitalize(),
                               "source": c.source, "line": c.line}


def _scope_subjects(choices: Dict[str, "Choice"], order: List[str], groups: Dict[str, Dict[str, Any]]) -> None:
    """Every choice whose id names a subject goes under that subject (`woman1.hair`,
    `mother.outfit`, `friends[2].age`), whether or not the program called group(), so the
    card shows one header per subject. Only with more than one subject: with one there are no
    headers, and its choices stay plain. A shared=True pick with a plain id stays marked
    shared; a plain id is otherwise a detail of the whole scene."""
    subjects: List[Tuple[str, Optional[int]]] = []
    for cid in order:
        s = subject_of(cid) if choices[cid].kind != "param" else None
        if s and (s[0], s[1]) not in subjects:
            subjects.append((s[0], s[1]))
    declared = any(int(g.get("count") or 0) >= 2 for g in groups.values())
    # bride[1] with no group() and no bride[2]: one subject, shown as "Bride", not "Bride 1"
    lone = {k for k, _ in subjects if int((groups.get(k) or {}).get("count") or 1) < 2
            and {i for n, i in subjects if n == k} == {1}}
    labeled = {c.group for c in choices.values() if c.group and subject_of(c.id) is None}  # "Girl 1 Hair" labels
    many = len(subjects) + len({(c.group, c.index) for c in choices.values() if c.group in labeled}) >= 2 or declared
    for cid in order:
        c = choices[cid]
        s = subject_of(cid) if c.kind != "param" else None
        if not many:
            c.group = c.index = c.attr = None
            c.shared = False
            continue
        if s is None:
            continue
        name, index, attr = s
        c.group, c.index, c.attr, c.shared = name, None if name in lone else index, attr, False
        if name not in groups:
            n = max((i or 1) for k, i in subjects if k == name)
            groups[name] = {"id": name, "count": n, "label": name.replace("_", " ").strip().capitalize(),
                            "source": c.source, "line": c.line, "from_ids": True}
    if not many:
        for gid in [g for g in groups if g in labeled]:
            del groups[gid]


def discover(source: str, loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None,
             runs: int = 48, seed: int = 7) -> Dict[str, Any]:
    """Run a program over many seeds to learn its choices and their structure."""
    results = [run(source, seed + i * 7919, None, loras, tool_params) for i in range(runs)]
    choices: Dict[str, Choice] = {}
    order: List[str] = []
    presence: Dict[str, List[bool]] = {}
    values: Dict[str, List[Any]] = {}
    for r_i, res in enumerate(results):
        for d in res.draws:
            c = choices.get(d.id)
            if c is None:
                m = _GROUP_ID.match(d.id)
                c = Choice(d.id, d.kind, d.label, d.source, d.line, [], d.hidden, d.follows,
                           group=m.group(1) if m else None, index=int(m.group(2)) if m else None, attr=m.group(3) if m else None,
                           phase=d.phase, about=d.about or None, cls=d.cls or None, where=d.where or None,
                           said=d.said or None, shared=getattr(d, "shared", False))
                choices[d.id] = c
                order.append(d.id)
            c.seen += 1
            if d.kind == "param":
                c.options = d.options
            else:
                for o in d.options:
                    if o not in c.options:
                        c.options.append(o)
            if d.follows and not c.follows:
                c.follows = d.follows
    for cid in order:
        presence[cid] = [any(d.id == cid for d in res.draws) for res in results]
        values[cid] = [next((d.value for d in res.draws if d.id == cid), None) for res in results]
    # A choice that only appears in some runs: find the earlier pick whose value explains it.
    for i, cid in enumerate(order):
        c = choices[cid]
        if all(presence[cid]) or cid.endswith(COLORS):
            continue  # a look's Colors shows with its outfit: present whenever the look has color slots
        for pid in order[:i]:
            if choices[pid].kind != "pick":
                continue
            on = {values[pid][r] for r in range(runs) if presence[cid][r]}
            off = {values[pid][r] for r in range(runs) if not presence[cid][r]}
            if on and not (on & off) and None not in on:
                c.parent, c.when = pid, sorted(str(v) for v in on)
                break
    if any(c.phase is not None for c in choices.values()):  # pick specs: static dependencies
        from prompt_programs.draws import analyze
        try:
            an = analyze(source)
        except ProgramError:  # validate() reports it; discovery still lists the choices
            an = None
        for c in choices.values() if an else ():
            deps = {d for s in an.sites_for_id(c.id) for d in s.deps}
            c.deps = [an.sites[d].id_text for d in sorted(deps)]
    groups: Dict[str, Dict[str, Any]] = {}
    for res in results:
        for gid, g in res.groups.items():
            groups.setdefault(gid, dict(g))
    _group_by_subject(choices, order, groups)
    _scope_subjects(choices, order, groups)
    sample = results[0]
    return {
        "choices": [choices[cid].to_dict() for cid in order],
        "groups": list(groups.values()),
        "params": sorted({d.id[len("param."):] for res in results for d in res.draws if d.kind == "param"}),
        "loras": sorted({lu.name for res in results for lu in res.loras}),
        "example": sample.prompt,
    }

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
import random
import re
import sys
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
    "capitalize", "title", "strip", "replace", "startswith", "endswith", "split", "format", "count", "index",
}
_SAFE_BUILTINS: Dict[str, Any] = {
    "range": range, "len": len, "str": str, "int": int, "float": float, "min": min, "max": max,
    "round": round, "sorted": sorted, "list": list, "dict": dict, "set": set, "enumerate": enumerate,
    "zip": zip, "abs": abs, "any": any, "all": all, "True": True, "False": False, "None": None,
}
API_NAMES = {"pick", "pick_lora", "param", "group", "emit"}


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
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            line = getattr(node, "lineno", "?")
            raise ProgramError(f"Line {line}: {type(node).__name__} is not allowed. Use only assignments, if, for, and the pick/pick_lora/param/group/emit functions.")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr not in _ALLOWED_METHODS:
                raise ProgramError(f"Line {node.lineno}: .{node.attr} is not allowed.")
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
        return d


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
    used ("flatchest") when every word of it is a word of exactly one listed name
    ("KREA2 bodyshop flatchest v1"). Unknown or ambiguous names are dropped."""
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


_GROUP_ID = re.compile(r"^([a-z_][a-z0-9_]*)\[(\d+)\]\.([a-z_][a-z0-9_]*)$")


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
             cls: Optional[str] = None, where: Any = None) -> Optional[str]:
        cid = str(id)
        if about is not None or phase is not None or seed is not None or cls is not None:
            return self._spec_pick(cid, options, label, by, source, line, exclude, hidden, added, about, phase, seed, cls,
                                   where)
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
                   cls: Optional[str] = None, where: Any = None) -> Optional[str]:
        """A pick with a spec (draws.py), run the plain way for discovery and validation:
        seeds stand in for options it doesn't list, and it is recorded even with none. A
        pick bound to a vocabulary list (cls=) runs on the list's values instead."""
        seeds = _as_list(seed if seed is not None else [], f'pick("{cid}") seed')
        leaf = bound_leaf(cid, cls, source, options)
        written = list(options) if isinstance(options, (list, tuple)) else options
        if leaf is not None:
            written = [v.text for v in leaf.eligible()]
        elif isinstance(written, dict) or written:
            if isinstance(written, dict):
                written = {k: [*seeds, *(v or [])] for k, v in written.items()}
            else:
                written = [*seeds, *written]
        else:
            written = seeds
        n = len(self.draws)
        value = self.pick(cid, written, label, by, source, line, exclude, hidden, added) if written else None
        if len(self.draws) == n:  # off, or nothing to draw: still a choice
            if (self.edits.get(cid) or {}).get("off"):
                return None
            self._record(Draw(cid, None, "pick", label or _label_from_id(cid), "added" if added else (source if source in SOURCES else "text"),
                              line, bool(hidden), False, []))
        d = self.draws[-1]
        d.phase, d.about = int(phase) if isinstance(phase, int) else None, str(about or "")
        d.cls = leaf.id if leaf is not None else ""
        d.where = where if isinstance(where, dict) else (str(where).strip() if isinstance(where, str) else "")
        if leaf is not None and leaf.slots and value is not None and "{" in str(value):
            value = self._palette(cid, d, leaf, value, source, line, hidden)
        elif isinstance(value, str) and "{" in value:
            from prompt_programs.vocab import fill
            value = d.value = fill(value, None)
        return value

    def _palette(self, cid: str, d: "Draw", leaf: Any, template: str, source: str, line: Optional[int],
                 hidden: bool) -> str:
        """A template pick's colours (see draws._Exec._palette), the plain way: a palette
        pick recorded right after the template, and the template filled with it."""
        from prompt_programs.vocab import fill, tags_match, vocabulary
        palette = vocabulary().get(leaf.slots)
        if palette is None:
            return template
        tv = leaf.value(str(template))
        values = palette.eligible()
        if tv is not None and tv.palette:
            values = [v for v in values if tags_match(v.tags, tv.palette)] or values
        ccid = f"{cid}.colours"
        n = len(self.draws)
        chosen = self.pick(ccid, [v.text for v in values], "Colors", None, source, line, None, hidden)
        if len(self.draws) > n:
            c = self.draws[-1]
            c.phase, c.about, c.cls, c.follows = d.phase, f"the colours of {d.about or d.label}", palette.id, cid
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
        for p in parts:
            if p is None:
                continue
            if isinstance(p, (list, tuple)):
                self.emit(*p)
                continue
            if isinstance(p, LoraName):  # a LoRA is turned on, never written into the prompt
                continue
            s = str(p).strip()
            if s:
                self.parts.append(s)


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


def run(source: str, seed: int, pins: Optional[Dict[str, Sequence[str]]] = None,
        loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None,
        fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Dict[str, Any]]] = None) -> RunResult:
    """Run a program once. Deterministic for a given (source, seed, pins, fixed)."""
    tree = check(source)
    runner = _Runner(seed, pins or {}, {_lora_key(lo.name): lo for lo in (loras or [])}, tool_params, fixed, edits)
    env: Dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS)}
    for name in API_NAMES:
        env[name] = getattr(runner, name)
    code = compile(tree, "<program>", "exec")
    steps = 0

    def tracer(frame, event, arg):  # step budget: a program must finish quickly
        nonlocal steps
        if frame.f_code.co_filename == "<program>":
            steps += 1
            if steps > MAX_STEPS:
                raise ProgramError("Program ran too long (it may loop forever).")
            return tracer
        return None

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        exec(code, env)  # noqa: S102 — checked AST, no builtins beyond _SAFE_BUILTINS
    except ProgramError:
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
        if c.group or c.kind == "param":
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
                           phase=d.phase, about=d.about or None, cls=d.cls or None, where=d.where or None)
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
        if all(presence[cid]) or cid.endswith(".colours"):
            continue  # a look's Colours shows with its outfit: present whenever the look has colour slots
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
    sample = results[0]
    return {
        "choices": [choices[cid].to_dict() for cid in order],
        "groups": list(groups.values()),
        "params": sorted({d.id[len("param."):] for res in results for d in res.draws if d.kind == "param"}),
        "loras": sorted({lu.name for res in results for lu in res.loras}),
        "example": sample.prompt,
    }

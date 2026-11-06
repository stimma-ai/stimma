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
             line: Optional[int] = None, exclude: Any = None, hidden: bool = False, added: bool = False) -> Optional[str]:
        cid = str(id)
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
        if edit.get("remove"):
            opts = [o for o in opts if o not in set(edit["remove"])] or opts
        for extra in edit.get("add") or []:
            if str(extra).strip() and str(extra) not in opts:
                opts.append(str(extra))
        if not opts:
            return None
        value, pinned = self._choose(cid, opts, uniform=(source == "list"), exclude=exclude or ())
        self._record(Draw(cid, value, "pick", label or _label_from_id(cid), source, line, bool(hidden), pinned, opts, follows))
        return value

    def pick_lora(self, id: str, names: Any = None, label: str = "", source: str = "text", line: Optional[int] = None) -> Optional[str]:
        cid = str(id)
        names = _as_list(names if names is not None else [], f'pick_lora("{cid}")')
        known = [n for n in names if _lora_key(n) in self.loras]
        if not known:
            raise ProgramError(f'pick_lora("{cid}"): none of {names} are in the LoRA list. Use the exact names given.')
        value, pinned = self._choose(cid, known, uniform=True)
        self._record(Draw(cid, value, "lora", label or _label_from_id(cid), source, line, False, pinned, known))
        info = self.loras[_lora_key(value)]
        self.lora_uses.append(LoraUse(info.name, info.weight, info.trigger, info.path, cid))
        return value

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
            s = str(p).strip()
            if s:
                self.parts.append(s)


def _lora_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def _label_from_id(cid: str) -> str:
    m = _GROUP_ID.match(cid)
    base = m.group(3) if m else cid.split(".")[-1]
    return base.replace("_", " ").strip().capitalize()


def tidy_text(parts: List[str]) -> str:
    s = " ".join(parts)
    s = re.sub(r"\s+", " ", s)
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
    seen: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in vars(self).items() if v not in (None, [], False) and k != "seen"}
        d["id"], d["kind"], d["label"], d["source"], d["options"] = self.id, self.kind, self.label, self.source, self.options
        return d


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
                           group=m.group(1) if m else None, index=int(m.group(2)) if m else None, attr=m.group(3) if m else None)
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
        if all(presence[cid]):
            continue
        for pid in order[:i]:
            if choices[pid].kind != "pick":
                continue
            on = {values[pid][r] for r in range(runs) if presence[cid][r]}
            off = {values[pid][r] for r in range(runs) if not presence[cid][r]}
            if on and not (on & off) and None not in on:
                c.parent, c.when = pid, sorted(str(v) for v in on)
                break
    groups: Dict[str, Dict[str, Any]] = {}
    for res in results:
        for gid, g in res.groups.items():
            groups.setdefault(gid, dict(g))
    sample = results[0]
    return {
        "choices": [choices[cid].to_dict() for cid in order],
        "groups": list(groups.values()),
        "params": sorted({d.id[len("param."):] for res in results for d in res.draws if d.kind == "param"}),
        "loras": sorted({lu.name for res in results for lu in res.loras}),
        "example": sample.prompt,
    }

"""Phased, judged draws for programs whose picks carry specs.

A program that gives its picks `about=`, `phase=` or `seed=` is drawn here instead of
by `runtime.run()`, which stays the path for programs written before specs existed.

    era  = pick("era", ["1920s", "1970s"], source="list", phase=1, line=1)
    role = pick("role", about="the woman's job", phase=1, seed=["jazz singer"])
    hair = pick("hair", about="her hairstyle", phase=2, seed=["finger waves"])
    emit("A portrait of a", role, "in the", era, "with", hair)

Phases are draw order. A pick whose value steers another pick (its `by=`, an `if` test
above it, a subscript, a loop count, its options) must sit in a strictly earlier phase;
`exclude=` may stay within a phase. `analyze()` checks that on the AST before anything
runs.

Per image, phase by phase: the program runs with concrete values (earlier phases
final, this phase proposed, later phases placeholders); the judge reads the text with
this phase and later ones masked as `[Label]` and scores each proposal; a Bernoulli coin
against the keep rate accepts it or a batch of new proposals is tried. Pins are placed
first and are never judged. Options come from an `OptionsService` (here: the program's
own literals, seeds and the user's edits) and judgments from a `Judge` (here: the null
judge, which keeps everything and calls nothing).
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import math
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Protocol, Sequence, Set, Tuple

from prompt_programs.runtime import (
    MAX_STEPS, RANK_DECAY, SOURCES, Draw, LoraInfo, LoraUse, ProgramError, RunResult, _SAFE_BUILTINS, _Runner,
    _as_list, _label_from_id, _lora_key, check, tidy_text,
)

DRAW_VERSION = "draws-2"
SPEC_ARGS = ("about", "phase", "seed")
TIERS = ("typical", "plausible", "unusual", "wrong")
DEFAULT_RARITY = 0.3   # keep rate of an *unusual* value (the rarity knob)
WRONG_CUT = 0.5        # P(wrong) above this keeps nothing (tuned on train data later)
BATCH = 16             # proposals per re-proposal batch
MAX_POOLS = 32         # pools a generated pick may have: one per combination of the lists it names
MAX_BATCHES = 3        # batches before a pick falls back and counts as unresolved

_PICK_PARAMS = ("id", "options", "label", "by", "source", "line", "exclude", "hidden", "added", "about", "phase", "seed")
_LORA_PARAMS = ("id", "names", "label", "source", "line", "phase")


# --------------------------------------------------------------------------- detection

@functools.lru_cache(maxsize=256)
def uses_draws(source: str) -> bool:
    """Whether a program uses pick specs (and so takes the draw path). Never raises:
    anything unparsable is left to run() to report as it always has."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("pick", "pick_lora")
                and any(k.arg in SPEC_ARGS for k in node.keywords)):
            return True
    return False


# --------------------------------------------------------------------------- static analysis
# Taint: which picks' values an expression carries, as (site, derived). `derived` means
# the text came through a lookup, a test or a computation, so it isn't the pick's value
# verbatim and has to be masked whole.

Taint = FrozenSet[Tuple[int, bool]]
_EMPTY: Taint = frozenset()


def _derive(t: Taint) -> Taint:
    return frozenset((s, True) for s, _ in t)


@dataclass
class Site:
    index: int
    kind: str                       # pick | lora
    id_text: str                    # "era", or a template like "people[*].age"
    id_re: "re.Pattern[str]"
    line: int
    phase: int = 1
    generated: bool = False         # its pool grows (about=, not a user list): values aren't known up front
    size: Optional[int] = None      # how many options it has, when they're written out as a list
    deps: Dict[int, str] = field(default_factory=dict)      # site -> where its value is used
    exclude_deps: Set[int] = field(default_factory=set)


@dataclass
class Analysis:
    phased: bool
    sites: List[Site]
    emits: Dict[int, List[Taint]]   # emit call -> per-argument taint
    code: Any
    phases: List[int]

    def sites_for_id(self, cid: str) -> List[Site]:
        return [s for s in self.sites if s.id_re.fullmatch(cid)]


_KEEP_BUILTINS = {"str", "list", "sorted", "min", "max", "enumerate", "zip", "dict", "set"}
_KEEP_METHODS = {"join", "lower", "upper", "capitalize", "title", "strip", "format", "replace", "split",
                 "items", "keys", "values"}


def _err(node: ast.AST, msg: str) -> ProgramError:
    return ProgramError(f"Line {getattr(node, 'lineno', '?')}: {msg}")


class _Analyzer:
    def __init__(self, tree: ast.Module):
        self.tree = tree
        self.vars: Dict[str, Set[Tuple[int, bool]]] = {}
        self.site_of: Dict[int, int] = {}       # id(Call node) -> site index
        self.emit_of: Dict[int, int] = {}
        self.sites: List[Site] = []
        self.emits: Dict[int, List[Taint]] = {}
        self.keyed: Dict[int, int] = {}          # site -> line where its value is used as a lookup key
        self.changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("pick", "pick_lora"):
                    self.site_of[id(node)] = len(self.sites)
                    self.sites.append(self._site(node, len(self.sites)))
                elif node.func.id == "emit":
                    self.emit_of[id(node)] = len(self.emit_of)

    # -- sites
    @staticmethod
    def _args(node: ast.Call, names: Sequence[str]) -> Dict[str, ast.AST]:
        fn = node.func.id  # type: ignore[attr-defined]
        if len(node.args) > len(names):
            raise _err(node, f"{fn}() takes at most {len(names)} arguments.")
        out = dict(zip(names, node.args))
        for k in node.keywords:
            if k.arg is None:
                raise _err(node, f"write {fn}()'s arguments out by name; ** is not allowed.")
            if k.arg not in names:
                raise _err(node, f'{fn}() has no argument "{k.arg}".')
            out[k.arg] = k.value
        return out

    def _site(self, node: ast.Call, index: int) -> Site:
        kind = "pick" if node.func.id == "pick" else "lora"  # type: ignore[attr-defined]
        args = self._args(node, _PICK_PARAMS if kind == "pick" else _LORA_PARAMS)
        id_node = args.get("id")
        if isinstance(id_node, ast.Constant) and isinstance(id_node.value, str):
            text, pattern = id_node.value, re.escape(id_node.value)
        elif isinstance(id_node, ast.JoinedStr):
            text, pattern = "", ""
            for part in id_node.values:
                if isinstance(part, ast.Constant):
                    text, pattern = text + str(part.value), pattern + re.escape(str(part.value))
                else:
                    text, pattern = text + "*", pattern + ".+?"
        else:
            raise _err(node, f"{node.func.id}() needs a written id, like \"hair\" or f\"people[{{i+1}}].age\".")  # type: ignore[attr-defined]
        return Site(index, kind, text, re.compile(pattern), node.lineno)

    # -- expressions
    def expr(self, node: Optional[ast.AST], ctx: List[Tuple[Taint, str]], local: Dict[str, Taint]) -> Taint:
        if node is None or isinstance(node, ast.Constant):
            return _EMPTY
        if isinstance(node, ast.Name):
            if node.id in ("pick", "pick_lora", "param", "group", "emit"):
                raise _err(node, f"call {node.id}(...) directly; don't store or pass it around.")
            if node.id in local:
                return local[node.id]
            return frozenset(self.vars.get(node.id, ()))
        if isinstance(node, ast.JoinedStr):
            return self._union(node.values, ctx, local)
        if isinstance(node, ast.FormattedValue):
            return self.expr(node.value, ctx, local) | _derive(self.expr(node.format_spec, ctx, local))
        if isinstance(node, ast.BinOp):
            t = self.expr(node.left, ctx, local) | self.expr(node.right, ctx, local)
            return t if isinstance(node.op, ast.Add) else _derive(t)
        if isinstance(node, ast.UnaryOp):
            return _derive(self.expr(node.operand, ctx, local))
        if isinstance(node, ast.BoolOp):
            return _derive(self._union(node.values, ctx, local))
        if isinstance(node, ast.Compare):
            return _derive(self._union([node.left, *node.comparators], ctx, local))
        if isinstance(node, ast.IfExp):
            test = self.expr(node.test, ctx, local)
            inner = ctx + [(test, "an if test")]
            return self.expr(node.body, inner, local) | self.expr(node.orelse, inner, local) | _derive(test)
        if isinstance(node, ast.Subscript):
            key = self.expr(node.slice, ctx, local)
            self._keyed(key, node)
            return self.expr(node.value, ctx, local) | _derive(key)
        if isinstance(node, ast.Slice):
            return _derive(self._union([node.lower, node.upper, node.step], ctx, local))
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return self._union(node.elts, ctx, local)
        if isinstance(node, ast.Dict):
            return _derive(self._union(node.keys, ctx, local)) | self._union(node.values, ctx, local)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            return self._comprehension(node, ctx, local)
        if isinstance(node, ast.Call):
            return self._call(node, ctx, local)
        if isinstance(node, ast.Attribute):
            return self.expr(node.value, ctx, local)
        raise _err(node, f"{type(node).__name__} can't be used here.")

    def _union(self, nodes: Sequence[Optional[ast.AST]], ctx, local) -> Taint:
        out: Set[Tuple[int, bool]] = set()
        for n in nodes:
            out |= self.expr(n, ctx, local)
        return frozenset(out)

    def _comprehension(self, node, ctx, local) -> Taint:
        local = dict(local)
        extra: Set[Tuple[int, bool]] = set()
        inner = list(ctx)
        for gen in node.generators:
            it = self.expr(gen.iter, inner, local)
            for name in self._names(gen.target):
                local[name] = it
            extra |= _derive(it)
            inner.append((it, "the loop around it"))
            for cond in gen.ifs:
                c = self.expr(cond, inner, local)
                extra |= _derive(c)
                inner.append((c, "an if test"))
        if isinstance(node, ast.DictComp):
            body = self.expr(node.key, inner, local) | self.expr(node.value, inner, local)
        else:
            body = self.expr(node.elt, inner, local)
        return body | frozenset(extra)

    def _call(self, node: ast.Call, ctx, local) -> Taint:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in ("pick", "pick_lora"):
            return self._pick(node, ctx, local)
        if isinstance(fn, ast.Name) and fn.id == "emit":
            if node.keywords:
                raise _err(node, "emit() takes only the parts of the prompt.")
            control = _derive(frozenset().union(*(t for t, _ in ctx))) if ctx else _EMPTY
            self.emits[self.emit_of[id(node)]] = [self.expr(a, ctx, local) | control for a in node.args]
            return _EMPTY
        args = self._union([*node.args, *(k.value for k in node.keywords)], ctx, local)
        if any(k.arg is None for k in node.keywords):
            raise _err(node, "** is not allowed in calls.")
        if isinstance(fn, ast.Name):
            if fn.id == "group":
                return _derive(args)
            if fn.id == "param":
                return _EMPTY
            return args if fn.id in _KEEP_BUILTINS else _derive(args)
        if isinstance(fn, ast.Attribute):
            recv = self.expr(fn.value, ctx, local)
            if fn.attr in ("append", "extend"):
                root = self._root(fn.value)
                control = _derive(frozenset().union(*(t for t, _ in ctx))) if ctx else _EMPTY
                self._add(root, args | control, local)
                return _EMPTY
            if fn.attr == "get":  # a lookup: the text is the table's, keyed by the args
                if node.args:
                    self._keyed(self.expr(node.args[0], ctx, local), node)
                return recv | _derive(args)
            t = recv | args
            return t if fn.attr in _KEEP_METHODS else _derive(t)
        return _derive(args | self.expr(fn, ctx, local))

    def _keyed(self, t: Taint, node: ast.AST) -> None:
        for s, derived in t:
            if not derived:  # the pick's value itself is the key
                self.keyed.setdefault(s, getattr(node, "lineno", 0))

    def _pick(self, node: ast.Call, ctx, local) -> Taint:
        idx = self.site_of[id(node)]
        site = self.sites[idx]
        args = self._args(node, _PICK_PARAMS if site.kind == "pick" else _LORA_PARAMS)
        if "by" in args:  # a by= dict is looked up by the value of the pick it follows
            self._keyed(self.expr(args["by"], ctx, local), node)
        uses: List[Tuple[Taint, str]] = list(ctx)
        for name, where in (("id", "its id"), ("options", "its options"), ("names", "its options"),
                            ("by", "its by="), ("seed", "its seed="), ("about", "its about="),
                            ("label", "its label"), ("source", "its source"), ("hidden", "its hidden=")):
            if name in args:
                uses.append((self.expr(args[name], ctx, local), where))
        for t, where in uses:
            for s, _ in t:
                site.deps.setdefault(s, where)
        if "exclude" in args:
            for s, _ in self.expr(args["exclude"], ctx, local):
                site.exclude_deps.add(s)
        return frozenset({(idx, False)})

    # -- statements
    @staticmethod
    def _names(target: ast.AST) -> List[str]:
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            return [n for e in target.elts for n in _Analyzer._names(e)]
        return []

    @staticmethod
    def _root(node: ast.AST) -> str:
        while isinstance(node, (ast.Subscript, ast.Attribute)):
            node = node.value
        if not isinstance(node, ast.Name):
            raise _err(node, "assign only to names, or to items of a list or dict held in a name.")
        return node.id

    def _add(self, name: str, t: Taint, local: Dict[str, Taint]) -> None:
        if name in local:
            local[name] = local[name] | t
            return
        cur = self.vars.setdefault(name, set())
        if not t <= cur:
            cur |= t
            self.changed = True

    def _assign(self, target: ast.AST, t: Taint, ctx, local) -> None:
        if isinstance(target, ast.Name):
            self._add(target.id, t, local)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for e in target.elts:
                self._assign(e, t, ctx, local)
        elif isinstance(target, (ast.Subscript, ast.Attribute)):
            key = self.expr(target.slice, ctx, local) if isinstance(target, ast.Subscript) else _EMPTY
            self._add(self._root(target), t | _derive(key), local)
        else:
            raise _err(target, "assign only to names, or to items of a list or dict held in a name.")

    def block(self, stmts: Sequence[ast.stmt], ctx: List[Tuple[Taint, str]]) -> None:
        local: Dict[str, Taint] = {}
        for st in stmts:
            control = _derive(frozenset().union(*(t for t, _ in ctx))) if ctx else _EMPTY
            if isinstance(st, ast.Assign):
                t = self.expr(st.value, ctx, local) | control
                for target in st.targets:
                    self._assign(target, t, ctx, local)
            elif isinstance(st, ast.AugAssign):
                self._assign(st.target, self.expr(st.value, ctx, local) | control, ctx, local)
            elif isinstance(st, ast.Expr):
                self.expr(st.value, ctx, local)
            elif isinstance(st, ast.If):
                test = self.expr(st.test, ctx, local)
                inner = ctx + [(test, "an if test above it")]
                self.block(st.body, inner)
                self.block(st.orelse, inner)
            elif isinstance(st, ast.For):
                it = self.expr(st.iter, ctx, local)
                inner = ctx + [(it, "the loop around it")]
                # A break or continue under an if makes the rest of the body depend on that test.
                for sub in self._loop_exits(st.body):
                    inner.append((self.expr(sub.test, inner, local), "an if test above it"))
                self._assign(st.target, it | control, ctx, local)
                self.block(st.body, inner)
                self.block(st.orelse, inner)
            elif isinstance(st, (ast.Pass, ast.Break, ast.Continue)):
                pass
            else:
                raise _err(st, f"{type(st).__name__} is not allowed.")

    @staticmethod
    def _loop_exits(body: Sequence[ast.stmt]) -> List[ast.If]:
        out: List[ast.If] = []

        def visit(stmts):
            for st in stmts:
                if isinstance(st, ast.If):
                    if any(isinstance(n, (ast.Break, ast.Continue)) for n in ast.walk(st) if not isinstance(n, ast.For)):
                        out.append(st)
                    visit(st.body)
                    visit(st.orelse)
        visit(body)
        return out


def _phase_of(node: ast.Call, site: Site, phased: bool) -> int:
    args = _Analyzer._args(node, _PICK_PARAMS if site.kind == "pick" else _LORA_PARAMS)
    ph = args.get("phase")
    if ph is None:
        if phased and site.kind == "pick":
            raise _err(node, f'pick("{site.id_text}") needs phase=: 1 for picks nothing else steers, '
                             "a higher number for picks that must fit earlier ones.")
        return 1
    if not (isinstance(ph, ast.Constant) and type(ph.value) is int and ph.value >= 1):
        raise _err(node, f'pick("{site.id_text}"): phase= must be a whole number like phase=2.')
    return ph.value


@functools.lru_cache(maxsize=64)
def analyze(source: str) -> Analysis:
    """Check a program's phases and dependencies, and compile it for drawing.
    Raises ProgramError with a message the program writer can act on."""
    tree = check(source)
    an = _Analyzer(tree)
    phased = uses_draws(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) in an.site_of:
            site = an.sites[an.site_of[id(node)]]
            site.phase = _phase_of(node, site, phased)
            if phased and site.kind == "pick":
                args = _Analyzer._args(node, _PICK_PARAMS)
                src = args.get("source")
                site.generated = "about" in args and not (isinstance(src, ast.Constant) and src.value == "list")
                if isinstance(args.get("options"), ast.List):
                    site.size = len(args["options"].elts)
                has_options = "options" in args and not (isinstance(args["options"], ast.Constant) and args["options"].value is None)
                if not has_options and "seed" not in args:
                    raise _err(node, f'pick("{site.id_text}") has no options: give it seed=[1 to 3 options] '
                                     "(and about= to say what it is), or a list of options.")
    for _ in range(50):  # taint to a fixed point (loops feed values back)
        an.changed = False
        for s in an.sites:
            s.deps.clear()
            s.exclude_deps.clear()
        an.block(tree.body, [])
        if not an.changed:
            break
    if phased:
        for s in an.sites:
            for d, where in sorted(s.deps.items()):
                dep = an.sites[d]
                if d == s.index:
                    raise ProgramError(f'Line {s.line}: pick("{s.id_text}") uses its own earlier values in {where}. '
                                       "Only exclude= may refer to them.")
                if dep.phase >= s.phase:
                    raise ProgramError(
                        f'Line {s.line}: pick("{s.id_text}") is in phase {s.phase} but uses pick("{dep.id_text}") '
                        f'(phase {dep.phase}) in {where}. A pick can only depend on picks in earlier phases: give '
                        f'"{dep.id_text}" a lower phase than "{s.id_text}", or don\'t use its value there.')
            named = [an.sites[d] for d, where in sorted(s.deps.items())
                     if where in ("its about=", "its seed=", "its label") and an.sites[d].generated and d != s.index]
            if s.generated and named:
                dep = named[0]
                raise ProgramError(
                    f'Line {s.line}: pick("{s.id_text}") names pick("{dep.id_text}") in {s.deps[dep.index]}, but '
                    f'"{dep.id_text}" is written with about=, so it gets new values as it is used and each would need '
                    "its own options. Only a user list (or another short list written out) may be named this way. "
                    f'Describe "{dep.id_text}" in words instead (about="what he wears for his job"): each value is '
                    "still checked against what earlier phases drew.")
            if s.generated:
                pools = 1
                for d in s.deps:
                    dep = an.sites[d]
                    if d != s.index and not dep.generated and dep.size:
                        pools *= dep.size
                if pools > MAX_POOLS:
                    raise ProgramError(
                        f'Line {s.line}: pick("{s.id_text}") depends on lists with {pools} combinations of values, '
                        f"each needing its own options (at most {MAX_POOLS}). Name only the one or two lists it "
                        "must fit in its about=.")
            if s.generated and s.index in an.keyed:
                raise ProgramError(
                    f'Line {an.keyed[s.index]}: pick("{s.id_text}") gets new options as it is used, so its value '
                    "can't be a key to look something up (a dict subscript, .get() or by=): those keys would be "
                    f'missing. Write what depends on it as its own pick in a later phase, or give "{s.id_text}" a '
                    "fixed list of options without about=.")
            for d in sorted(s.exclude_deps):
                dep = an.sites[d]
                if dep.phase > s.phase:
                    raise ProgramError(
                        f'Line {s.line}: pick("{s.id_text}") (phase {s.phase}) excludes values of pick("{dep.id_text}") '
                        f"(phase {dep.phase}), which isn't drawn yet. Give it the same or an earlier phase.")
    # Tag every pick and emit call with its site so the runtime can attribute spans.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if id(node) in an.site_of:
                node.keywords.append(ast.keyword(arg="_site", value=ast.Constant(an.site_of[id(node)])))
            elif id(node) in an.emit_of:
                node.keywords.append(ast.keyword(arg="_site", value=ast.Constant(an.emit_of[id(node)])))
    ast.fix_missing_locations(tree)
    code = compile(tree, "<program>", "exec")
    return Analysis(phased, an.sites, an.emits, code, sorted({s.phase for s in an.sites}))


# --------------------------------------------------------------------------- options service

@dataclass
class PickSpec:
    """What a pick asks the options service for."""
    id: str
    label: str
    about: str
    phase: int
    source: str                  # text | list | added
    kind: str = "pick"           # pick | lora
    seeds: List[str] = field(default_factory=list)
    literal: List[str] = field(default_factory=list)   # the program's own options on this branch


@dataclass
class Pool:
    key: str
    items: List[str]
    weights: List[float]
    more_coming: bool = False


def pool_key(spec: PickSpec, context: Dict[str, Any]) -> str:
    """A pool is the pick's spec plus the values of the picks it depends on:
    `hair: her hairstyle | era=1920s` is not `hair: her hairstyle | era=1970s`."""
    head = f"{spec.id}: {spec.about}" if spec.about else spec.id
    return head + ("".join(f" | {k}={v}" for k, v in context.items()))


class OptionsService(Protocol):
    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool: ...

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None: ...


class LiteralOptions:
    """Pools from the program itself: seeds first, then its option literals, then the
    user's edits (removals stay removed: an emptied pool is empty, never restored)."""

    def __init__(self, edits: Optional[Dict[str, Dict[str, Any]]] = None):
        self.edits = edits or {}
        self.requests: List[Tuple[str, str]] = []

    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        items = list(dict.fromkeys([*spec.seeds, *spec.literal]))
        edit = self.edits.get(spec.id) or {}
        if edit.get("remove"):
            gone = {str(x) for x in edit["remove"]}
            items = [o for o in items if o not in gone]
        for extra in edit.get("add") or []:
            if str(extra).strip() and str(extra) not in items:
                items.append(str(extra))
        uniform = spec.source == "list" or spec.kind == "lora"
        weights = [1.0] * len(items) if uniform else [RANK_DECAY ** i for i in range(len(items))]
        return Pool(pool_key(spec, context), items, weights, False)

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None:
        self.requests.append((pool_key(spec, context), priority))


# --------------------------------------------------------------------------- judge

@dataclass(frozen=True)
class Question:
    pick_id: str
    label: str
    about: str
    value: str


class Judge(Protocol):
    """Reads a state (the description so far, later picks masked) and one question per
    candidate; returns a probability per tier (typical/plausible/unusual/wrong)."""
    version: str

    def judge(self, state: str, questions: Sequence[Question]) -> List[Dict[str, float]]: ...


class NullJudge:
    """Keeps everything and calls nothing: the same-inputs baseline."""
    version = "null"
    null = True

    def judge(self, state: str, questions: Sequence[Question]) -> List[Dict[str, float]]:
        return [{"typical": 1.0} for _ in questions]


def _tier_rates(rarity: float) -> Dict[str, float]:
    return {"typical": 1.0, "plausible": 1.0, "unusual": rarity, "wrong": 0.0}


def tier_score(probs: Dict[str, float], rarity: float = DEFAULT_RARITY) -> float:
    """Σ P(tier) × rate(tier), with no cut: how good a candidate is, for ranking."""
    rates = _tier_rates(rarity)
    return sum(float(probs.get(t, 0.0)) * rates[t] for t in TIERS)


KEEP_MODES = ("tiers", "cut")


def keep_rate(probs: Dict[str, float], rarity: float = DEFAULT_RARITY, wrong_cut: float = WRONG_CUT,
              mode: str = "tiers") -> float:
    """0 when P(wrong) is above the cut. Otherwise, in "tiers" mode, Σ P(tier) × rate(tier)
    (the rarity knob scales unusual values); in "cut" mode, 1: only the wrong cut acts,
    for judges whose lower tiers aren't calibrated yet. Applied once per candidate per
    context, as the chance a Bernoulli coin keeps it."""
    if float(probs.get("wrong", 0.0)) > wrong_cut:
        return 0.0
    if mode == "cut":
        return 1.0
    return max(0.0, min(1.0, tier_score(probs, rarity)))


def candidate_score(probs: Dict[str, float], rarity: float = DEFAULT_RARITY, mode: str = "tiers") -> float:
    """How good a candidate is, for ranking fallbacks."""
    return 1.0 - float(probs.get("wrong", 0.0)) if mode == "cut" else tier_score(probs, rarity)


# --------------------------------------------------------------------------- results

class DrawAborted(ProgramError):
    """A draw that can't produce a prompt: a pick with nothing left to draw, or a pin
    nothing fits. Nothing is generated; the message is shown where the choice is."""

    def __init__(self, choice_id: str, label: str, reason: str, value: Optional[str] = None):
        self.choice_id, self.label, self.reason, self.value = choice_id, label, reason, value
        if reason == "pin":
            msg = f'The pinned {label} "{value}" doesn\'t fit the other choices.'
        else:
            msg = f"Nothing left to draw for {label}."
        super().__init__(msg)

    def to_dict(self) -> Dict[str, Any]:
        d = {"code": "nothing_to_draw", "message": str(self), "choice_id": self.choice_id, "reason": self.reason}
        if self.value is not None:
            d["value"] = self.value
        return d


@dataclass
class DrawResult(RunResult):
    revision: Dict[str, Any] = field(default_factory=dict)
    unresolved: List[Dict[str, Any]] = field(default_factory=list)
    judge_passes: int = 0
    more_coming: List[str] = field(default_factory=list)   # choices whose pools are still filling
    stats: Dict[str, Any] = field(default_factory=dict)    # proposals, rejections, judge passes

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["draw_revision"] = self.revision
        if self.unresolved:
            d["unresolved"] = list(self.unresolved)
        if self.more_coming:
            d["more_coming"] = list(self.more_coming)
        return d


# --------------------------------------------------------------------------- execution

class _Abort(Exception):
    def __init__(self, choice_id: str, label: str, reason: str, value: Optional[str] = None):
        super().__init__(choice_id)
        self.args_ = (choice_id, label, reason, value)


@dataclass
class _Seen:
    id: str
    site: int
    phase: int
    spec: PickSpec
    items: List[Tuple[str, float]]       # eligible after edits, exclude and pins
    value: Any = None
    pin_ok: bool = True
    context: Dict[str, Any] = field(default_factory=dict)


class _Exec(_Runner):
    """One concrete run: earlier phases (and anything decided) fixed, this phase
    proposed, later phases placeholders. Records spans for masked rendering."""

    def __init__(self, eng: "_Engine", k: float, proposals: Dict[str, str], probe: Optional[str], record: bool):
        super().__init__(0, {}, eng.loras, eng.tool_params)
        self.eng, self.k, self.proposals, self.probe, self.record = eng, k, proposals, probe, record
        self.rng = eng.rng
        self.fixed = {**eng.fixed, **eng.param_values}
        self.pins = {cid: sorted(vs) for cid, vs in eng.pins.items()}  # param() reads these
        self.seen: Dict[str, _Seen] = {}
        self.order: List[str] = []
        self.site_ids: Dict[int, List[str]] = {}
        self.spans: List[Tuple[str, Taint]] = []

    def _context(self, site: Site) -> Dict[str, Any]:
        """The values a pick's pool is keyed by: the fixed-list picks it depends on.
        A generated pick's value never keys a pool (each would need its own options);
        the judge checks the pick against it instead."""
        ctx: Dict[str, Any] = {}
        for d in sorted(site.deps):
            if self.eng.an.sites[d].generated:
                continue
            for cid in self.site_ids.get(d, []):
                if cid in self.by_id:
                    ctx[cid] = self.by_id[cid].value
        return ctx

    def _settle(self, cid: str, site: Site, spec: PickSpec, items: List[Tuple[str, float]],
                context: Dict[str, Any]) -> Tuple[Any, bool]:
        eng, names = self.eng, [o for o, _ in items]
        pin = eng.single_pins.get(cid)
        seen = _Seen(cid, site.index, site.phase, spec, items, context=context)
        self.seen[cid] = seen
        eng.labels[cid] = spec.label
        self.order.append(cid)
        self.site_ids.setdefault(site.index, []).append(cid)
        if pin is not None:  # authoritative: placed first, never judged or rerolled
            seen.pin_ok = pin in names
            seen.value = pin
            return pin, True
        v = eng.decided.get(cid)
        if v is not None and v in names:
            seen.value = v
            return v, False
        if self.probe is not None and site.phase == self.k and cid != self.probe:
            # A probe asks what the decided values and one trial value allow, so this
            # phase's undecided picks stand aside (a value no pool or exclude holds).
            seen.value = f"\x00{cid}"
            return seen.value, False
        if site.phase <= self.k:
            v = self.proposals.get(cid)
            if v not in names:
                if not items:
                    if spec.kind == "pick" and spec.source != "list" and self.probe is None:
                        eng.options.request_more(spec, context, "high")
                    raise _Abort(cid, spec.label, "empty")
                v = eng.propose(cid, items)
                self.proposals[cid] = v
            seen.value = v
            return v, False
        seen.value = names[0] if names else f"[{spec.label}]"  # placeholder; masked, never judged
        return seen.value, False

    def pick(self, id: str, options: Any = None, label: str = "", by: Any = None, source: str = "text",
             line: Optional[int] = None, exclude: Any = None, hidden: bool = False, added: bool = False,
             about: Optional[str] = None, phase: Optional[int] = None, seed: Any = None, _site: int = -1) -> Optional[str]:
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
        if (self.eng.edits.get(cid) or {}).get("off"):
            return None  # removed by the user: the detail is left to the image model
        site = self.eng.an.sites[_site]
        lbl = label or _label_from_id(cid)
        spec = PickSpec(cid, lbl, str(about or ""), site.phase, source, "pick",
                        _as_list(seed if seed is not None else [], f'pick("{cid}") seed'), opts)
        context = self._context(site)
        value, pinned = self._settle(cid, site, spec, self._eligible(cid, spec, context, exclude), context)
        d = Draw(cid, value, "pick", lbl, source, line, bool(hidden), pinned, [o for o, _ in self.seen[cid].items], follows)
        d.phase, d.about = site.phase, spec.about
        self._record(d)
        return value

    def pick_lora(self, id: str, names: Any = None, label: str = "", source: str = "text", line: Optional[int] = None,
                  phase: Optional[int] = None, _site: int = -1) -> Optional[str]:
        cid = str(id)
        names = _as_list(names if names is not None else [], f'pick_lora("{cid}")')
        known = [n for n in names if _lora_key(n) in self.loras]
        if not known:
            raise ProgramError(f'pick_lora("{cid}"): none of {names} are in the LoRA list. Use the exact names given.')
        site = self.eng.an.sites[_site]
        lbl = label or _label_from_id(cid)
        spec = PickSpec(cid, lbl, "", site.phase, source if source in SOURCES else "text", "lora", [], known)
        context = self._context(site)
        value, pinned = self._settle(cid, site, spec, self._eligible(cid, spec, context, None), context)
        d = Draw(cid, value, "lora", lbl, spec.source, line, False, pinned, [o for o, _ in self.seen[cid].items])
        d.phase = site.phase
        self._record(d)
        info = self.loras.get(_lora_key(str(value)))
        if info is not None:
            self.lora_uses.append(LoraUse(info.name, info.weight, info.trigger, info.path, cid))
        return value

    def _eligible(self, cid: str, spec: PickSpec, context: Dict[str, Any], exclude: Any) -> List[Tuple[str, float]]:
        pool = self.eng.options.get(spec, context)
        if self.record:  # the revision records the pools the final prompt drew from
            self.eng.pools[pool.key] = len(pool.items)
            if pool.more_coming:
                self.eng.more_coming.append(cid)
        excl = {str(x) for x in (exclude or []) if x is not None}
        items = [(o, w) for o, w in zip(pool.items, pool.weights) if o not in excl]
        pins = self.eng.pins.get(cid)
        if pins:
            items = [(o, w) for o, w in items if o in pins]
        return items

    def param(self, name: str, low: Any = None, high: Any = None, label: str = "", source: str = "text",
              line: Optional[int] = None) -> Any:
        value = super().param(name, low, high, label, source, line)
        if self.probe is None:  # drawn once per image, then held
            self.eng.param_values.setdefault(f"param.{name}", value)
        return value

    def emit(self, *parts: Any, _site: int = -1) -> None:
        taints = self.eng.an.emits.get(_site, [])
        for i, p in enumerate(parts):
            t = taints[i] if i < len(taints) else _EMPTY
            for s in _flatten(p):  # each span recorded once, with its part's taint
                self.parts.append(s)
                self.spans.append((s, t))


def _flatten(p: Any) -> List[str]:
    """runtime._Runner.emit's flattening, without re-entering emit()."""
    if p is None:
        return []
    if isinstance(p, (list, tuple)):
        return [s for q in p for s in _flatten(q)]
    s = str(p).strip()
    return [s] if s else []


def _execute(code: Any, runner: _Exec) -> None:
    env: Dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS)}
    for name in ("pick", "pick_lora", "param", "group", "emit"):
        env[name] = getattr(runner, name)
    steps = 0

    def tracer(frame, event, arg):
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
    except (ProgramError, _Abort):
        raise
    except Exception as e:
        tb, line = e.__traceback__, None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == "<program>":
                line = tb.tb_lineno
            tb = tb.tb_next
        raise ProgramError(f"Line {line}: {type(e).__name__}: {e}") from None
    finally:
        sys.settrace(old)


# --------------------------------------------------------------------------- the draw loop

class _Engine:
    def __init__(self, an: Analysis, seed: int, pins: Dict[str, Sequence[str]], loras: Dict[str, LoraInfo],
                 tool_params: Optional[Set[str]], fixed: Dict[str, Any], edits: Dict[str, Dict[str, Any]],
                 options: OptionsService, judge: Judge, rarity: float, wrong_cut: float = WRONG_CUT,
                 keep: str = "tiers", prefetch: int = 0):
        self.an, self.rng, self.seed = an, random.Random(seed), seed
        self.loras, self.tool_params = loras, tool_params
        # A choice the user turned off has no value to pin.
        self.pins = {str(k): {str(v) for v in vs} for k, vs in pins.items()
                     if vs and not (edits.get(str(k)) or {}).get("off")}
        self.single_pins = {k: next(iter(vs)) for k, vs in self.pins.items() if len(vs) == 1}
        self.fixed, self.edits, self.options, self.judge, self.rarity = fixed, edits, options, judge, rarity
        self.wrong_cut = wrong_cut
        self.keep = keep if keep in KEEP_MODES else "tiers"
        self.prefetch = max(0, int(prefetch))   # also judge up to this many pool options per pick
        self.more_coming: List[str] = []
        self.proposals = 0
        self.rejected = 0
        self.decided: Dict[str, str] = {}
        self.param_values: Dict[str, Any] = {}
        self.kept: Set[str] = set()            # replayed (fixed) values: kept, not judged
        self.pools: Dict[str, int] = {}
        self.judged: Dict[Tuple[str, str, str, str], Dict[str, float]] = {}
        self.unresolved: List[Dict[str, Any]] = []
        self.labels: Dict[str, str] = {}
        self.judge_passes = 0
        # Pins a pick could break: its site feeds the pinned pick's structure or exclude.
        self.pin_watch: Dict[int, List[Tuple[str, Site]]] = {}
        for cid in sorted(self.single_pins):
            for s in an.sites_for_id(cid):
                for d in sorted(set(s.deps) | s.exclude_deps):
                    self.pin_watch.setdefault(d, []).append((cid, s))

    # -- primitives
    def propose(self, cid: str, items: List[Tuple[str, float]]) -> str:
        kept = self.fixed.get(cid)
        if kept is not None and cid not in self.kept and any(o == kept for o, _ in items):
            self.kept.add(cid)
            return str(kept)
        return self._weighted(items)

    def _weighted(self, items: List[Tuple[str, float]]) -> str:
        total = sum(w for _, w in items)
        r = self.rng.random() * total
        for o, w in items:
            r -= w
            if r <= 0:
                return o
        return items[-1][0]

    def execute(self, k: float, proposals: Dict[str, str], probe: Optional[str] = None, record: bool = False) -> _Exec:
        runner = _Exec(self, k, proposals, probe, record)
        try:
            _execute(self.an.code, runner)
        except _Abort as a:
            if probe is not None:
                raise
            raise DrawAborted(*a.args_) from None
        return runner

    # -- judging
    def probs(self, state: str, seen: _Seen, values: Sequence[str]) -> List[Dict[str, float]]:
        if getattr(self.judge, "null", False):
            return [{"typical": 1.0} for _ in values]
        keys = [(seen.id, seen.spec.about, str(v), state) for v in values]
        todo = list(dict.fromkeys(k for k in keys if k not in self.judged))
        if todo:
            self.judge_passes += 1
            got = self.judge.judge(state, [Question(seen.id, seen.spec.label, seen.spec.about, k[2]) for k in todo])
            for k, p in zip(todo, got):
                self.judged[k] = dict(p)
        return [self.judged[k] for k in keys]

    def prejudge(self, state: str, exe: _Exec, ids: Sequence[str]) -> None:
        """One pass for a phase's first proposals: one question per pick."""
        if getattr(self.judge, "null", False):
            return
        qs, keys = [], []
        for cid in ids:
            s = exe.seen[cid]
            if cid in self.kept:
                continue
            # Prefetch: the rest of the pool rides along, judged in the state this pick
            # is judged in, so later draws find it cached. It changes no draw.
            values = [str(s.value)] + [o for o, _ in s.items[: self.prefetch]]
            for v in dict.fromkeys(values):
                k = (cid, s.spec.about, v, state)
                if k not in self.judged:
                    qs.append(Question(cid, s.spec.label, s.spec.about, v))
                    keys.append(k)
        if qs:
            self.judge_passes += 1
            for k, p in zip(keys, self.judge.judge(state, qs)):
                self.judged[k] = dict(p)

    def state(self, exe: _Exec, k: float) -> str:
        """The text so far for the judge: pins and earlier phases in the clear, this
        phase and later ones masked as [Label]."""
        out: List[str] = []
        for text, taint in exe.spans:
            hidden: List[Tuple[str, bool]] = []
            for s, derived in sorted(taint):
                if self.an.sites[s].phase < k:
                    continue
                for cid in exe.site_ids.get(s, []):
                    if cid in exe.by_id and cid not in self.single_pins:
                        hidden.append((cid, derived))
            if not hidden:
                out.append(text)
                continue
            first = exe.by_id[hidden[0][0]].label
            if any(derived for _, derived in hidden):
                out.append(f"[{first}]")
                continue
            masked, ok, labels = text, True, []
            for cid, _ in sorted(hidden, key=lambda h: -len(str(exe.by_id[h[0]].value or ""))):
                v = str(exe.by_id[cid].value or "")
                if not v:
                    continue
                pat = re.compile(re.escape(v), re.I)
                if not pat.search(masked):
                    ok = False
                    break
                masked = pat.sub(f"\x00{len(labels)}\x00", masked)
                labels.append(exe.by_id[cid].label)
            if not ok:
                out.append(f"[{first}]")
                continue
            out.append(re.sub(r"\x00(\d+)\x00", lambda m: f"[{labels[int(m.group(1))]}]", masked))
        text = tidy_text(out)
        # Single-value pins are authoritative context for every phase, even when their
        # pick sits in a branch that isn't active yet or inside a masked span: always listed.
        extra = [f"{exe.by_id[cid].label if cid in exe.by_id else self.labels.get(cid, _label_from_id(cid))}: {v}"
                 for cid, v in sorted(self.single_pins.items()) if self.an.sites_for_id(cid)]
        return text if not extra else f"{text}\n(Fixed: {'; '.join(extra)})"

    # -- hard constraints
    def hard_ok(self, cid: str, value: str, k: int, proposals: Dict[str, str], site: int) -> bool:
        """Whether this value keeps every pin it could affect satisfiable."""
        watch = [(pid, s) for pid, s in self.pin_watch.get(site, []) if pid != cid]
        if not watch:
            return True
        trial = dict(proposals)
        trial[cid] = value
        try:
            exe = self.execute(k, trial, probe=cid)
        except (_Abort, ProgramError):
            return False
        for pid, s in watch:
            # Structure that still hangs on undrawn picks can't be judged yet; it is
            # checked again when those are drawn. (Exclusions need no wait: a probe's
            # undecided peers hold no value.)
            undecided = any(
                self.an.sites[d].phase > k or (self.an.sites[d].phase == k and any(
                    i not in self.decided for i in exe.site_ids.get(d, []) if i != cid))
                for d in s.deps)
            if undecided:
                continue
            seen = exe.seen.get(pid)
            if seen is None or not seen.pin_ok:
                return False
        return True

    def check_pins(self, exe: _Exec, k: float) -> None:
        for pid, value in sorted(self.single_pins.items()):
            sites = self.an.sites_for_id(pid)
            if not sites:
                continue  # a pin for a choice this program doesn't have: ignored, as before
            settled = all(self.an.sites[d].phase < k for s in sites for d in (set(s.deps) | s.exclude_deps))
            if not settled:
                continue
            seen = exe.seen.get(pid)
            if seen is None or not seen.pin_ok:
                label = self.labels.get(pid, _label_from_id(pid))
                raise DrawAborted(pid, label, "pin", value)

    # -- phases
    def run_phase(self, k: int) -> None:
        proposals: Dict[str, str] = {}
        exe = self.execute(k, proposals)
        self.check_pins(exe, k)
        order = [cid for cid in exe.order if exe.seen[cid].phase == k and cid not in self.single_pins]
        state = self.state(exe, k)
        self.prejudge(state, exe, order)
        dirty = False
        for cid in order:
            if dirty:
                exe = self.execute(k, proposals)
                dirty = False
            seen = exe.seen.get(cid)
            if seen is None:
                continue
            chosen = self.decide(cid, seen, str(seen.value), state, k, proposals)
            self.decided[cid] = chosen
            if proposals.get(cid) != chosen:
                proposals[cid] = chosen
                dirty = True

    def decide(self, cid: str, seen: _Seen, first: str, state: str, k: int, proposals: Dict[str, str]) -> str:
        hard: Dict[str, bool] = {}

        def is_hard_ok(v: str) -> bool:
            if v not in hard:
                hard[v] = self.hard_ok(cid, v, k, proposals, seen.site)
            return hard[v]

        if cid in self.kept and first == str(self.fixed.get(cid)) and is_hard_ok(first):
            return first  # a replayed value: kept as it was
        tried: List[Tuple[str, float]] = []
        for batch in range(MAX_BATCHES + 1):
            cands = [first] if batch == 0 else [self._weighted(seen.items) for _ in range(BATCH)]
            for v, p in zip(cands, self.probs(state, seen, cands)):
                self.proposals += 1
                tried.append((v, candidate_score(p, self.rarity, self.keep)))
                keep = keep_rate(p, self.rarity, self.wrong_cut, self.keep)
                if keep <= 0 or not is_hard_ok(v):
                    self.rejected += 1
                    continue
                if keep >= 1 or self.rng.random() < keep:
                    return v
                self.rejected += 1
        # Nothing accepted: the pool is thin for this context. Ask for more now, so the
        # next run has better options (a user list is never expanded).
        if seen.spec.kind == "pick" and seen.spec.source != "list":
            self.options.request_more(seen.spec, seen.context, "high")
        ok = [(v, s) for v, s in tried if is_hard_ok(v)]
        if not ok:
            pinned = next((pid for pid, _ in self.pin_watch.get(seen.site, []) if pid != cid), None)
            if pinned is not None:
                raise DrawAborted(pinned, self.labels.get(pinned, _label_from_id(pinned)), "pin", self.single_pins[pinned])
            raise DrawAborted(cid, seen.spec.label, "unresolved")
        best = max(range(len(ok)), key=lambda i: (ok[i][1], -i))
        self.unresolved.append({"id": cid, "label": seen.spec.label, "reason": "no_accepted_value"})
        return ok[best][0]

    def revision(self, source: str) -> Dict[str, Any]:
        rev = {
            "engine": DRAW_VERSION,
            "program": hashlib.sha256(source.encode("utf-8")).hexdigest()[:16],
            "pools": dict(sorted(self.pools.items())),
            "edits": hashlib.sha256(json.dumps(self.edits, sort_keys=True, default=str).encode()).hexdigest()[:16]
            if self.edits else None,
            "rarity": self.rarity,
            "judge": getattr(self.judge, "version", type(self.judge).__name__),
        }
        if self.wrong_cut != WRONG_CUT:
            rev["wrong_cut"] = self.wrong_cut
        if self.keep != "tiers":
            rev["keep"] = self.keep
        rev["id"] = hashlib.sha256(json.dumps(rev, sort_keys=True).encode()).hexdigest()[:16]
        return rev


def draw(source: str, seed: int, pins: Optional[Dict[str, Sequence[str]]] = None,
         loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None,
         fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Dict[str, Any]]] = None, *,
         options: Optional[OptionsService] = None, judge: Optional[Judge] = None,
         rarity: float = DEFAULT_RARITY, wrong_cut: float = WRONG_CUT, keep: str = "tiers",
         prefetch: int = 0) -> DrawResult:
    """Draw one prompt from a program with pick specs. Deterministic for a given
    revision, seed and pins. Raises DrawAborted when a pick has nothing left to draw
    or a pin can't be satisfied, and ProgramError for a broken program."""
    an = analyze(source)
    edits = edits or {}
    eng = _Engine(an, seed, pins or {}, {_lora_key(lo.name): lo for lo in (loras or [])}, tool_params,
                  dict(fixed or {}), edits, options or LiteralOptions(edits), judge or NullJudge(), rarity, wrong_cut, keep, prefetch)
    for k in an.phases:
        eng.run_phase(k)
    final = eng.execute(math.inf, {}, record=True)
    eng.check_pins(final, math.inf)
    prompt = tidy_text(final.parts)
    if not prompt:
        raise ProgramError("The program emitted no prompt text. Call emit(...) with the finished prompt.")
    for lu in final.lora_uses:
        if lu.trigger and lu.trigger.lower() not in prompt.lower():
            prompt = f"{lu.trigger}, {prompt}"
    stats = {"proposals": eng.proposals, "rejected": eng.rejected, "judge_passes": eng.judge_passes}
    return DrawResult(prompt, final.draws, final.lora_uses, final.params, final.groups, seed,
                      revision=eng.revision(source), unresolved=eng.unresolved, judge_passes=eng.judge_passes,
                      more_coming=list(dict.fromkeys(eng.more_coming)), stats=stats)


@functools.lru_cache(maxsize=128)
def _fixed_text(source: str, loras: Tuple[Tuple[str, str, float, str], ...], tool_params: Optional[FrozenSet[str]]) -> str:
    an = analyze(source)
    infos = [LoraInfo(*lo) for lo in loras]
    eng = _Engine(an, 0, {}, {_lora_key(lo.name): lo for lo in infos}, set(tool_params) if tool_params else None,
                  {}, {}, LiteralOptions(), NullJudge(), DEFAULT_RARITY)
    return eng.state(eng.execute(0, {}), 0)


def fixed_text(source: str, loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None) -> str:
    """The program's text with every pick masked as [Label]: what the prompt states
    before anything is drawn. Branches and loops take their first options."""
    key = tuple((lo.name, lo.path, lo.weight, lo.trigger) for lo in loras or ())
    return _fixed_text(source, key, frozenset(tool_params) if tool_params else None)


__all__ = [
    "Analysis", "DrawAborted", "DrawResult", "Judge", "LiteralOptions", "NullJudge", "OptionsService", "PickSpec",
    "KEEP_MODES", "Pool", "Question", "TIERS", "WRONG_CUT", "candidate_score", "analyze", "draw", "fixed_text", "keep_rate", "pool_key", "tier_score",
    "uses_draws",
]

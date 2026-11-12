"""Phased draws for programs whose picks carry specs.

A program that gives its picks `about=`, `phase=`, `seed=` or `cls=` is drawn here
instead of by `runtime.run()`, which runs programs without specs.

    era  = pick("era", ["1920s", "1970s"], source="list", phase=1, line=1)
    role = pick("role", about="the woman's job", phase=1, seed=["jazz singer"])
    hair = pick("hair", about="her hairstyle", phase=2, seed=["finger waves"])
    emit("A portrait of a", role, "in the", era, "with", hair)

Phases are draw order. A pick whose value steers another pick (its `by=`, an `if` test
above it, a subscript, a loop count, its options) must sit in a strictly earlier phase;
`exclude=` may stay within a phase. `analyze()` checks that on the AST before anything
runs.

Context (vocab.py): a bound pick whose list takes a context facet is drawn after the bound
picks in its scope whose lists give it (a person's descent before their hair color, the
time of day before the light). `analyze()` orders them from the vocabulary's declarations,
moving a taker to a later phase when the writer put it before its giver; the writer never
has to. Each taker's pool is then weighted by what its givers drew (`_Exec._given`).

Per image, phase by phase: the program runs with concrete values (earlier phases
final, this phase proposed, later phases placeholders), and each proposal is kept unless
it would leave a pin unsatisfiable, in which case new proposals are tried. Pins are
placed first. Options come from an `OptionsService` (here: the program's own literals,
seeds and the user's edits; prompt_programs.options generates more). Whether a finished
draw hangs together is checked afterwards, by the fix pass (prompt_programs.fix).
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Protocol, Sequence, Set, Tuple

from prompt_programs.runtime import (
    COLORS, COLORS_ABOUT, RANK_DECAY, SOURCES, Draw, LoraInfo, LoraUse, ProgramError, RunResult, _Runner, LoraName, _as_list,
    _label_from_id, _lora_key, check, compile_program, execute, flatten_parts, holds_said, lora_names, said_value,
    subject_of, tidy_text, zone_seeds,
)
from prompt_programs.vocab import AGE_LIST, fill, is_template, minor_ages, tags_match, template_matches, vocabulary

DRAW_VERSION = "draws-2"
# Recorded on a revision whose program has context links (a giver and a taker in one scope, or
# a stated context): its draws ran in context order with weighted pools. A revision without it
# drew without context and replays that way. ctx-2 added less-common families (vocab.py); a ctx-1
# revision recorded its weighted vocabulary pools, so it still replays exactly.
CONTEXT_VERSION = "ctx-2"
CONTEXT_VERSIONS = ("ctx-1", CONTEXT_VERSION)   # what a replay can read
SPEC_ARGS = ("about", "phase", "seed", "cls", "zones")
BATCH = 16             # proposals per re-proposal batch, when a value breaks a pin
MAX_BATCHES = 3        # batches before a pick gives up
MAX_POOLS = 32         # pools a generated pick may have: one per combination of the lists it names

_PICK_PARAMS = ("id", "options", "label", "by", "source", "line", "exclude", "hidden", "added", "about", "phase", "seed",
                "cls", "where", "said", "shared", "zones")
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
    named: Dict[int, str] = field(default_factory=dict)     # site -> the argument (about=, seed=, label) naming it
    exclude_deps: Set[int] = field(default_factory=set)
    cls: str = ""                   # the vocabulary list it is bound to, when written as a constant


def person_of(cid: str) -> str:
    """Whose detail a pick is, as the id names its subject (runtime.subject_of, the one rule
    the choices row, validation, the age policy and context all read): `friends[2].age` and
    `friends[2].outfit.colors` are friends[2]'s, `woman1.hair` woman1's, `man.outfit` the
    man's. A plain id (`outfit`, `outfit.colors`) names no subject: "" — the image's one
    subject, or with several a detail shared by all of them (shared=True), so a person's
    policies read "" as theirs too (`owns`). A loop's id (`friends[{}].age`) names its member."""
    cid = str(cid)
    s = subject_of(cid.replace("{}", "1"))
    if s is None:
        return ""
    tail = "." + s[2]
    return cid[: -len(tail)] if cid.endswith(tail) else cid.split(".", 1)[0]


def owns(owner: str, person: str) -> bool:
    """Whether what `owner`'s pick draws (person_of) holds for `person`'s: their own, or either
    names no subject and so is every subject's (a couple's one shared descent or age speaks for
    each of them; a shared outfit is worn by each, so it is fit for the youngest)."""
    return owner == person or owner == "" or person == ""


@dataclass
class Analysis:
    phased: bool
    sites: List[Site]
    emits: Dict[int, List[Taint]]   # emit call -> per-argument taint
    code: Any
    phases: List[int]
    context_links: List[Tuple[int, int]] = field(default_factory=list)   # (giver site, taker site)

    def sites_for_id(self, cid: str) -> List[Site]:
        return [s for s in self.sites if s.id_re.fullmatch(cid)]


_KEEP_BUILTINS = {"str", "list", "sorted", "min", "max", "enumerate", "zip", "dict", "set", "opt"}
_KEEP_METHODS = {"join", "lower", "upper", "capitalize", "title", "strip", "replace", "split",
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
        cls = args.get("cls")
        cls = cls.value.strip() if isinstance(cls, ast.Constant) and isinstance(cls.value, str) else ""
        return Site(index, kind, text, re.compile(pattern), node.lineno, cls=cls)

    # -- expressions
    def expr(self, node: Optional[ast.AST], ctx: List[Tuple[Taint, str]], local: Dict[str, Taint]) -> Taint:
        if node is None or isinstance(node, ast.Constant):
            return _EMPTY
        if isinstance(node, ast.Name):
            if node.id in ("pick", "pick_lora", "param", "group", "emit", "opt"):
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
                if where in _NAMING:  # tracked apart: an if test above may have recorded it first
                    site.named.setdefault(s, where)
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


_NAMING = ("its about=", "its seed=", "its label")


def _list_sizes(tree: ast.Module) -> Dict[str, int]:
    """Names bound once, at the top level, to a list written out: their length."""
    bound: Dict[str, List[ast.AST]] = {}
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(
            node, (ast.AugAssign, ast.AnnAssign, ast.For)) else []
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    bound.setdefault(n.id, []).append(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):  # options.append(...)
            root = node.func.value
            if isinstance(root, ast.Name):
                bound.setdefault(root.id, []).append(node)
    # A list read anywhere but as a pick's options (aliased, passed on, concatenated) may
    # grow out of sight: its size is unknown.
    passed: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("pick", "pick_lora"):
            arg = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg in ("options", "names")), None)
            if isinstance(arg, ast.Name):
                passed.add(id(arg))
    escaped = {n.id for n in ast.walk(tree)
               if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and id(n) not in passed}
    top = {id(st) for st in tree.body}
    return {name: len(nodes[0].value.elts) for name, nodes in bound.items()
            if len(nodes) == 1 and id(nodes[0]) in top and isinstance(nodes[0], ast.Assign)
            and len(nodes[0].targets) == 1 and isinstance(nodes[0].targets[0], ast.Name)  # not a = b = [...]
            and isinstance(nodes[0].value, (ast.List, ast.Tuple)) and name not in escaped}


def _size(node: Optional[ast.AST], sizes: Dict[str, int]) -> Optional[int]:
    """How many values a pick's options hold, when that's known before drawing."""
    if isinstance(node, (ast.List, ast.Tuple)):
        return len(node.elts)
    if isinstance(node, ast.Name):
        return sizes.get(node.id)
    if isinstance(node, ast.Dict):  # options by an earlier pick: every value any key lists
        values: Set[Any] = set()
        for v in node.values:
            if not isinstance(v, (ast.List, ast.Tuple)) or not all(isinstance(e, ast.Constant) for e in v.elts):
                return None
            values |= {e.value for e in v.elts}
        return len(values)
    return None


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


def context_links(sites: Sequence[Site]) -> List[Tuple[int, int]]:
    """(giver, taker) site pairs: a bound pick whose list gives a context facet another bound
    pick's list takes, in the same scope (the same person for a person facet, the image for a
    scene facet). Only the vocabulary's declarations are read."""
    vocab = vocabulary()
    leaves = {}
    for s in sites:
        if s.kind == "pick" and s.cls and s.generated:   # bound, and not the user's list
            leaf = vocab.resolve(s.cls)
            if leaf is not None and (leaf.gives or leaf.takes):
                leaves[s.index] = leaf
    out = []
    for t, tl in leaves.items():
        for g, gl in leaves.items():
            if g != t and any(f in gl.gives and (vocab.scope(f) == "scene" or
                                                 owns(person_of(sites[g].id_text), person_of(sites[t].id_text)))
                              for f in tl.takes):
                out.append((g, t))
    return out


def _context_phases(sites: Sequence[Site], links: Sequence[Tuple[int, int]]) -> Optional[Dict[int, int]]:
    """Phases with each taker after its givers: in a later phase, or in the same one when the
    giver's pick is written above it (drawn first). Dependencies keep holding. None when the
    links can't all hold (a taker steers its own giver): the writer's phases stand."""
    phase = {s.index: s.phase for s in sites}
    after: Dict[int, List[int]] = {}
    for g, t in links:
        after.setdefault(t, []).append(g)
    for _ in range(len(sites) + 2):
        moved = False
        for s in sites:
            need = max([phase[s.index]] + [phase[d] + 1 for d in s.deps if d != s.index]
                       + [phase[d] for d in s.exclude_deps if d != s.index]
                       + [phase[g] + (0 if sites[g].line < s.line else 1) for g in after.get(s.index, [])])
            if need != phase[s.index]:
                phase[s.index], moved = need, True
        if not moved:
            return phase
    return None


@functools.lru_cache(maxsize=64)
def analyze(source: str, strict: bool = False, context: bool = True) -> Analysis:
    """Check a program's phases and dependencies, and compile it for drawing.
    Raises ProgramError with a message the program writer can act on. `strict` adds
    the rules a newly written program must follow (validation): no pick names a
    generated pick, and a generated pick's pools stay few. Drawing an already prepared
    program never applies them: programs written before them draw as they always did.
    `context` orders context takers after their givers (module docstring); without it (a
    revision drawn before context) the writer's phases stand as written."""
    tree = check(source)
    an = _Analyzer(tree)
    phased = uses_draws(source)
    sizes = _list_sizes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and id(node) in an.site_of:
            site = an.sites[an.site_of[id(node)]]
            site.phase = _phase_of(node, site, phased)
            if phased and site.kind == "pick":
                args = _Analyzer._args(node, _PICK_PARAMS)
                src = args.get("source")
                # a pick bound to a vocabulary list counts as generated: its value never keys a lookup
                site.generated = ("about" in args or "cls" in args) and not (isinstance(src, ast.Constant) and src.value == "list")
                site.size = _size(args.get("options"), sizes)
                has_options = "options" in args and not (isinstance(args["options"], ast.Constant) and args["options"].value is None)
                if not has_options and "seed" not in args and "cls" not in args:
                    raise _err(node, f'pick("{site.id_text}") has no options: give it seed=[1 to 3 options] '
                                     "(and about= to say what it is), or a list of options.")
    for _ in range(50):  # taint to a fixed point (loops feed values back)
        an.changed = False
        for s in an.sites:
            s.deps.clear()
            s.named.clear()
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
            named = [an.sites[d] for d in sorted(s.named) if an.sites[d].generated and d != s.index]
            if strict and s.generated and named:
                dep = named[0]
                raise ProgramError(
                    f'Line {s.line}: pick("{s.id_text}") names pick("{dep.id_text}") in {s.named[dep.index]}, but '
                    f'"{dep.id_text}" is written with about=, so it gets new values as it is used and each would need '
                    "its own options. Only a user list (or another short list written out) may be named this way. "
                    f'Describe "{dep.id_text}" in words instead (about="what he wears for his job"): each value is '
                    "still checked against what earlier phases drew.")
            if strict and s.generated:
                pools = 1
                for d in sorted(s.deps):
                    dep = an.sites[d]
                    if d == s.index or dep.generated:
                        continue
                    if dep.kind == "pick" and dep.size is None:
                        raise ProgramError(
                            f'Line {s.line}: pick("{s.id_text}") depends on pick("{dep.id_text}"), whose options '
                            "aren't written out, so how many pools it needs isn't known. Write "
                            f'"{dep.id_text}"\'s options as a list in its pick() (or in a name assigned once).')
                    pools *= dep.size or 1
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
    code = compile_program(tree)
    links: List[Tuple[int, int]] = []
    if phased and context:
        links = context_links(an.sites)
        moved = _context_phases(an.sites, links) if links else None
        if links and moved is None:
            links = []
        for s in an.sites:
            if moved is not None:
                s.phase = moved[s.index]
    return Analysis(phased, an.sites, an.emits, code, sorted({s.phase for s in an.sites}), links)


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
    cls: str = ""                # the vocabulary list it is bound to (vocab.py); "" for none
    restrict: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()   # a palette pick: its template's allowed facets
    # The ages under 18 its person may be (vocab.minor_ages): their pools leave adult-only values
    # out and generated options are written for that age. Empty for an adult, a user list, a
    # wildcard (the user's own words) and the age pick itself.
    minor: Tuple[str, ...] = ()
    # The user's own words this pick stands for (runtime.said_value): first in its pool, and
    # what it draws unless the user ticks others. Its other options are alternatives to them.
    said: str = ""
    # The context its pool is drawn in (vocab.py): (facet, families) for each facet its list
    # takes that a giver in its scope drew. Empty for the user's lists, wildcards, pins and said picks.
    context: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    # A slot's option pools (slots.py): zone id -> its seeds ("kinds" of the thing the words name,
    # things to have "instead"). The options service draws from the chosen zones' pools, each a
    # spec of its own with `zone` set.
    zones: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    zone: str = ""


def context_suffix(spec: PickSpec) -> str:
    """The context's part of a pool's identity (last in the key, so a replay finds it)."""
    if not spec.context:
        return ""
    return " | context " + "; ".join(f"{f}={','.join(v)}" for f, v in spec.context)


@dataclass
class Pool:
    key: str
    items: List[str]
    weights: List[float]
    more_coming: bool = False
    snapshot: bool = False       # a revision records the whole pool (vocabulary lists change between versions)
    roles: Dict[str, Dict[str, str]] = field(default_factory=dict)   # a palette pool: each scheme's colors
    own: frozenset = frozenset()   # the user's own options in it (added in the card, or kept for its list)
    # Values held at weight 0 (standby: opt-in, or a narrowed list's rest) -> the weight a tick
    # draws them at, so a pin that also names drawn values still draws them (a tick means drawn).
    held: Dict[str, float] = field(default_factory=dict)


def pool_key(spec: PickSpec, context: Dict[str, Any]) -> str:
    """A pool is the pick's spec plus the values of the picks it depends on:
    `hair: her hairstyle | era=1920s` is not `hair: her hairstyle | era=1970s`."""
    head = f"{spec.id}: {spec.about}" if spec.about else spec.id
    if spec.zone:
        head += f" | {spec.zone}"
    return head + ("".join(f" | {k}={v}" for k, v in context.items()))


class OptionsService(Protocol):
    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool: ...

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None: ...


class LiteralOptions:
    """Pools from the program itself: seeds first, then its option literals, then the
    user's edits (removals stay removed: an emptied pool is empty, never restored). A pick
    the program writes no values for (a template's Colors, added by the engine) draws from
    its list, restricted as the template says (opt-in values at weight 0, see vocab.py)."""

    def __init__(self, edits: Optional[Dict[str, Dict[str, Any]]] = None):
        self.edits = edits or {}
        self.requests: List[Tuple[str, str]] = []

    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        items = list(dict.fromkeys([*spec.seeds, *spec.literal]))
        leaf = vocabulary().resolve(spec.cls) if not items and spec.cls else None
        standby: Set[str] = set()
        if leaf is not None:
            want = {f: list(vals) for f, vals in spec.restrict}
            drawn, held = leaf.pool_values(minor=bool(spec.minor))
            values = [*drawn, *held]
            items = [v.text for v in values if tags_match(v.tags, want)] or [v.text for v in values]
            standby = {v.text for v in held}
        edit = self.edits.get(spec.id) or {}
        if edit.get("remove"):
            gone = {str(x) for x in edit["remove"]}
            items = [o for o in items if o not in gone]
        for extra in edit.get("add") or []:
            if str(extra).strip() and str(extra) not in items:
                items.append(str(extra))
        uniform = spec.source == "list" or spec.kind == "lora"
        weights = [1.0] * len(items) if uniform else [RANK_DECAY ** i for i in range(len(items))]
        weights = [0.0 if o in standby else w for o, w in zip(items, weights)]
        if leaf is not None and spec.context:
            weights = [w for _, w in leaf.weigh(list(zip(items, weights)), spec.context)]
        return Pool(pool_key(spec, context) + context_suffix(spec), items, weights, False)

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None:
        self.requests.append((pool_key(spec, context), priority))


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
    more_coming: List[str] = field(default_factory=list)   # choices whose pools are still filling
    stats: Dict[str, Any] = field(default_factory=dict)    # proposals and rejections
    # The emitted parts in order, each with the id of the pick whose value it is (None for the
    # program's own text): where each drawn value stands is found from these (value_spans).
    value_parts: List[Tuple[str, Optional[str]]] = field(default_factory=list)

    @property
    def spans(self) -> List[Tuple[int, int, str]]:
        """(start, end, choice id) of every drawn value in `prompt` as it stands now (after
        [exact text] is put back too), in order. User text is never a span."""
        return value_spans(self.prompt, self.value_parts)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["draw_revision"] = self.revision
        if self.more_coming:
            d["more_coming"] = list(self.more_coming)
        return d


def _value_parts(exe: Any) -> List[Tuple[str, Optional[str]]]:
    """Each emitted part with the pick it is the value of: a part of an emit() argument that
    pick's value fed, whose text is that value (any case). A value written into other text
    (an f-string) is no part of its own, so it isn't one."""
    out: List[Tuple[str, Optional[str]]] = []
    for text, taint in exe.spans:
        own = text.strip().lower()
        cid = next((c for s, derived in sorted(taint) if not derived for c in exe.site_ids.get(s, [])
                    if c in exe.by_id and exe.by_id[c].kind == "pick" and exe.by_id[c].value is not None
                    and str(exe.by_id[c].value).strip().lower() == own and own), None)
        out.append((text, cid))
    return out


def value_spans(prompt: str, parts: Sequence[Tuple[str, Optional[str]]]) -> List[Tuple[int, int, str]]:
    """Where each value part stands in the prompt made from `parts` (tidy_text, perhaps with
    [exact text] put back): the parts are found in order, case aside, as whole words, each
    after the one before. Tidying may drop or change the program's own short joiners ("a"
    before a value's own "a"), so one of those moves the search only when it is found right
    there, and only to where it starts. A value not found is no span: it goes unmarked."""
    at = 0
    out: List[Tuple[int, int, str]] = []
    for text, cid in parts:
        t = text.strip()
        if not t:
            continue
        m = None
        for form in dict.fromkeys((t, tidy_text([t]))):   # "a olive coat" reads "an olive coat" once tidied
            pat = (r"(?<!\w)" if form[:1].isalnum() else "") + re.escape(form) + (r"(?!\w)" if form[-1:].isalnum() else "")
            m = re.compile(pat, re.I).search(prompt, at) if form else None
            if m is not None:
                break
        if m is None:
            continue
        if cid is not None:
            out.append((m.start(), m.end(), cid))
            at = m.end()
        elif len(t.split()) > 3:
            at = m.end()
        elif not prompt[at:m.start()].strip(" \t\n,.;:!?"):
            at = m.start()
    return out


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
        A generated pick's value never keys a pool (each would need its own options)."""
        ctx: Dict[str, Any] = {}
        for d in sorted(site.deps):
            if self.eng.an.sites[d].generated:
                continue
            for cid in self.site_ids.get(d, []):
                if cid in self.by_id:
                    ctx[cid] = self.by_id[cid].value
        return ctx

    def _minor(self, cid: str, site: Site) -> Tuple[str, ...]:
        """The ages under 18 this pick's person may be in this draw: the program's (_minors),
        and those of the user's list values the person's age list drew (narrow.py read them).
        A list not drawn before this pick (a later phase, or later in this one) may be any of
        its values, so every age under 18 it holds counts."""
        p = person_of(cid)
        out = [a for who, ages in self.eng.minors.items() if owns(who, p) for a in ages]
        for lid, young in self.eng.list_ages.items():
            if not owns(person_of(lid), p) or not young:
                continue
            d, seen = self.by_id.get(lid), self.seen.get(lid)
            drawn = (d is not None and seen is not None and seen.phase <= min(site.phase, self.k)
                     and not str(d.value).startswith("\x00"))
            for v in ([str(d.value)] if drawn else list(young)):
                out += young.get(v, ())
        return tuple(dict.fromkeys(out))

    def _given(self, cid: str, site: Site, leaf: Any) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
        """The context this pick is drawn in: for each facet its list takes, the families tagged
        on the values drawn before it in its scope by picks whose lists give that facet (a
        later phase's placeholder isn't drawn yet) and by the user's list values read on such a
        list (narrow.py); failing those, what the prompt states for its person or scene."""
        vocab, p, eng = vocabulary(), person_of(cid), self.eng
        drawn: Dict[str, Tuple[_Seen, str]] = {}
        # Earlier phases' values are final (decided, or pinned) even before their pick() runs again
        # in this run; this run's own values count once drawn (an earlier pick of this phase).
        for oid, seen in eng.specs.items():
            if seen.phase < min(site.phase, self.k):
                v = eng.single_pins.get(oid, eng.decided.get(oid))
                if v is not None:
                    drawn[oid] = (seen, str(v))
        for oid, d in self.by_id.items():
            seen = self.seen.get(oid)
            if seen is not None and seen.phase <= min(site.phase, self.k) and not str(d.value).startswith("\x00"):
                drawn[oid] = (seen, str(d.value))
        out = []
        for facet in sorted(leaf.takes):
            person = vocab.scope(facet) == "person"
            fam: Set[str] = set()
            for oid, (seen, value) in drawn.items():
                if oid == cid or (person and not owns(person_of(oid), p)):
                    continue
                gl = vocab.get(seen.spec.cls) if seen.spec.cls and seen.spec.source != "list" else None
                if gl is not None and facet in gl.gives:
                    fam |= set(gl.context_tags(value, facet) or ())
                fam |= set(eng.list_context.get(oid, {}).get(value, {}).get(facet, ()))
            if not fam:   # nothing drawn gave it: what the prompt states, if anything
                if person:
                    fam = {f for who, st in eng.stated.items() if who is not None and owns(who, p)
                           for f in st.get(facet, ())}
                else:
                    fam = set(eng.stated.get(None, {}).get(facet, ()))
            if fam:
                out.append((facet, tuple(sorted(fam))))
        return tuple(out)

    def _settle(self, cid: str, site: Site, spec: PickSpec, items: List[Tuple[str, float]],
                context: Dict[str, Any]) -> Tuple[Any, bool]:
        eng, names = self.eng, [o for o, _ in items]
        pin = eng.single_pins.get(cid)
        seen = _Seen(cid, site.index, site.phase, spec, items, context=context)
        self.seen[cid] = seen
        eng.specs[cid] = seen
        eng.labels[cid] = spec.label
        self.order.append(cid)
        self.site_ids.setdefault(site.index, []).append(cid)
        if pin is not None:  # authoritative: placed first, never rerolled
            seen.pin_ok = pin in names
            seen.value = pin
            return pin, True
        if holds_said(cid, spec.said, names, eng.pins, eng.fixed):
            # The user's own words, as a pin is: placed first, never rerolled. Its pool stays
            # whole, so the picker shows the alternatives they may tick.
            eng.held[cid] = spec.said
            seen.value = spec.said
            return spec.said, True
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
                # Values at weight 0 (opt-in, not asked for) draw only when pinned or kept.
                if not items or (cid not in eng.pins and not any(w > 0 for _, w in items)
                                 and eng.fixed.get(cid) not in names):
                    if spec.kind == "pick" and spec.source != "list" and self.probe is None:
                        eng.options.request_more(spec, context, "high")
                    raise _Abort(cid, spec.label, "empty")
                v = eng.propose(cid, items)
                self.proposals[cid] = v
            seen.value = v
            return v, False
        seen.value = names[0] if names else f"[{spec.label}]"  # placeholder; masked
        return seen.value, False

    def pick(self, id: str, options: Any = None, label: str = "", by: Any = None, source: str = "text",
             line: Optional[int] = None, exclude: Any = None, hidden: bool = False, added: bool = False,
             about: Optional[str] = None, phase: Optional[int] = None, seed: Any = None, cls: Optional[str] = None,
             where: Any = None, said: Any = None, shared: bool = False, zones: Any = None,
             _site: int = -1) -> Optional[str]:
        cid = str(id)
        if added:
            source = "added"
        if source not in SOURCES:
            source = "text"
        said = said_value(said) if source != "list" else ""
        if said:  # the user's words: a choice from their text, whatever else it was marked
            source = "text"
        if source == "list":
            self.eng.lists.add(cid)   # the user's own list: its items are theirs, exactly
        follows = None
        if isinstance(options, dict):
            # every option this pick has under any value of `by` (see _Engine.offered)
            self.eng.offered.setdefault(cid, set()).update(
                str(o) for vs in options.values() if isinstance(vs, (list, tuple)) for o in vs)
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
        # A list the vocabulary no longer has keeps its id (a revision's recorded pool is found
        # by it) and otherwise draws as an unbound pick: seeds and generated options, never a failure.
        leaf = vocabulary().resolve(cls) if cls and source != "list" else None
        seeds = _as_list(seed if seed is not None else [], f'pick("{cid}") seed')
        zoned = ()
        if zones is not None:
            every = zone_seeds(zones, f'pick("{cid}")')
            seeds = seeds if seed is not None else every
            zoned = tuple((str(z), tuple(_as_list(v, f'pick("{cid}") zones'))) for z, v in zones.items())
        spec = PickSpec(cid, lbl, str(about or ""), site.phase, source, "pick",
                        list(dict.fromkeys([said, *seeds])) if said else seeds, opts,
                        leaf.id if leaf is not None else (str(cls).strip() if cls and source != "list" else ""),
                        said=said, zones=zoned)
        if source != "list" and spec.cls != AGE_LIST and cid not in self.eng.theirs:
            spec.minor = self._minor(cid, site)
        # A said pick is the user's own words: it gives context (its drawn value is read like any
        # giver's) but is never weighted itself, nor are the alternatives they may tick.
        if leaf is not None and leaf.takes and self.eng.context_on and cid not in self.eng.theirs \
                and cid not in self.eng.pins and not said:
            spec.context = self._given(cid, site, leaf)
        context = self._context(site)
        if leaf is not None and leaf.slots:
            self._unfill_kept(cid, leaf)
        eligible = self._eligible(cid, spec, context, exclude)
        value, pinned = self._settle(cid, site, spec, eligible, context)
        colors, template = None, ""
        # Only a look with color slots draws Colors: a fixed-color template ("a white karate gi")
        # or a generated option (written with its colors) has none to fill.
        if leaf is not None and leaf.slots and vocabulary().get(leaf.slots) is not None and is_template(str(value)):
            colors = self._palette(cid, site, spec, leaf, value, source, line, hidden)
            template = str(value)
            value = fill(str(value), self.eng.roles.get(cid))  # the image model reads the filled look
        elif isinstance(value, str) and "{" in value:  # a replayed template whose list is gone: never show slots
            value = fill(value, None)
        d = Draw(cid, value, "pick", lbl, source, line, bool(hidden), pinned, [o for o, _ in eligible], follows)
        d.phase, d.about, d.cls, d.said = site.phase, spec.about, spec.cls, said
        d.where = where if isinstance(where, dict) else (str(where).strip() if isinstance(where, str) else "")
        d.shared = bool(shared)
        d.template = template
        d.own = str(value) in self.eng.own.get(cid, frozenset())
        self._record(d)
        if colors is not None:
            self._record(colors)
        return value

    def _unfill_kept(self, cid: str, leaf: Any) -> None:
        """A kept value of a template pick names the filled look ("a navy T-shirt and white
        shorts", from an earlier draw or a fix pass); the engine keeps the template it came
        from, read with the kept palette, or any template it fits."""
        names = {v.text for v in leaf.values}
        palette = vocabulary().get(leaf.slots)
        ccid = cid + COLORS
        for fixed in (self.eng.fixed, self.fixed):
            kept = fixed.get(cid)
            if kept is None or str(kept) in names:
                continue
            pv = palette.value(str(fixed.get(ccid) or "")) if palette is not None else None
            hit = next((v.text for v in leaf.values if pv is not None and fill(v.text, pv.roles) == str(kept)), None)
            if hit is None and pv is None and palette is not None:
                # only the look was kept: find the template and the scheme that wrote it, and keep both
                pair = next(((v.text, p.text) for v in leaf.values if template_matches(v.text, str(kept))
                             for p in palette.values if fill(v.text, p.roles) == str(kept)), None)
                if pair is not None:
                    hit = pair[0]
                    fixed.setdefault(ccid, pair[1])
            hit = hit or next((v.text for v in leaf.values if template_matches(v.text, str(kept))), None)
            if hit is not None:
                fixed[cid] = hit

    def _palette(self, cid: str, site: Site, spec: PickSpec, leaf: Any, template: Any, source: str,
                 line: Optional[int], hidden: bool) -> Optional[Draw]:
        """A template pick's colors: an ordinary pick of the palette list, drawn right after
        the template (same site and phase), restricted to the palettes the template allows.
        Records the palette's roles for the template's fill and returns its Draw."""
        palette = vocabulary().get(leaf.slots)
        ccid = cid + COLORS
        if (self.eng.edits.get(ccid) or {}).get("off"):  # colors turned off: the look reads without them
            self.eng.roles[cid] = {}
            return None
        tv = leaf.value(str(template))
        restrict = tuple(sorted((str(f), tuple(str(x) for x in (w if isinstance(w, (list, tuple)) else [w])))
                                for f, w in (tv.palette if tv is not None else {}).items()))
        cspec = PickSpec(ccid, "Colors", COLORS_ABOUT.format(spec.about or spec.label), site.phase, source, "pick",
                         [], [], palette.id, restrict)
        eligible = self._eligible(ccid, cspec, {}, None)
        value, pinned = self._settle(ccid, site, cspec, eligible, {})
        pv = palette.value(str(value))
        recorded = self.eng.pool_roles.get(ccid, {}).get(str(value))  # a replay's colors, as they were drawn
        self.eng.roles[cid] = dict(recorded or (pv.roles if pv is not None else {}))
        d = Draw(ccid, value, "pick", "Colors", source, line, bool(hidden), pinned, [o for o, _ in eligible], cid)
        d.phase, d.about, d.cls = site.phase, cspec.about, palette.id
        return d

    def pick_lora(self, id: str, names: Any = None, label: str = "", source: str = "text", line: Optional[int] = None,
                  phase: Optional[int] = None, _site: int = -1) -> Optional[str]:
        cid = str(id)
        names = _as_list(names if names is not None else [], f'pick_lora("{cid}")')
        known = lora_names(names, self.loras)
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
        return LoraName(value) if isinstance(value, str) else value

    def _eligible(self, cid: str, spec: PickSpec, context: Dict[str, Any], exclude: Any) -> List[Tuple[str, float]]:
        pool = self.eng.options.get(spec, context)
        if self.record:  # the revision records the pools the final prompt drew from
            self.eng.pools[pool.key] = ([[o, w, *([pool.roles[o]] if o in pool.roles else [])]
                                         for o, w in zip(pool.items, pool.weights)] if pool.snapshot
                                        else len(pool.items))
            if pool.more_coming:
                self.eng.more_coming.append(cid)
        if pool.roles:
            self.eng.pool_roles[cid] = pool.roles
        self.eng.offered.setdefault(cid, set()).update(pool.items)   # before anything is excluded
        excl = {str(x) for x in (exclude or []) if x is not None}
        items = [(o, w) for o, w in zip(pool.items, pool.weights) if o not in excl]
        self.eng.own[cid] = pool.own
        pins = self.eng.pins.get(cid)
        if pins:
            # A ticked option of the user's own is drawn like a typical value, even one their
            # words held back (weight 0 until ticked, see additions.py).
            # A ticked standby value draws at its own weight beside the others.
            items = [(o, (1.0 if o in pool.own else pool.held.get(o, w)) if w <= 0 else w)
                     for o, w in items if o in pins]
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
            for s in flatten_parts([p], sum(map(len, self.parts))):  # each span recorded once, with its part's taint
                self.parts.append(s)
                self.spans.append((s, t))


# --------------------------------------------------------------------------- the draw loop

class _Engine:
    def __init__(self, an: Analysis, seed: int, pins: Dict[str, Sequence[str]], loras: Dict[str, LoraInfo],
                 tool_params: Optional[Set[str]], fixed: Dict[str, Any], edits: Dict[str, Dict[str, Any]],
                 options: OptionsService):
        self.an, self.rng, self.seed = an, random.Random(seed), seed
        self.loras, self.tool_params = loras, tool_params
        # A choice the user turned off has no value to pin.
        self.pins = {str(k): {str(v) for v in vs} for k, vs in pins.items()
                     if vs and not (edits.get(str(k)) or {}).get("off")}
        self.single_pins = {k: next(iter(vs)) for k, vs in self.pins.items() if len(vs) == 1}
        self.fixed, self.edits, self.options = fixed, edits, options
        self.theirs: Set[str] = set(getattr(options, "theirs", ()) or ())   # wildcard picks: the user's words
        self.minors = self._minors()
        self.list_ages: Dict[str, Dict[str, Tuple[str, ...]]] = getattr(options, "list_ages", None) or {}
        # Context (vocab.py): off only to replay a revision drawn before it. What the prompt states
        # ({person, or None for the scene: {facet: families}}) and what the user's list values read
        # as ({list pick: {value: {facet: families}}}) come from the prepared entry (narrow.py).
        self.context_on = getattr(options, "context", True) is not False
        self.stated: Dict[Optional[str], Dict[str, Tuple[str, ...]]] = (
            getattr(options, "stated_context", None) or {}) if self.context_on else {}
        self.list_context: Dict[str, Dict[str, Dict[str, Tuple[str, ...]]]] = (
            getattr(options, "list_context", None) or {}) if self.context_on else {}
        self.specs: Dict[str, "_Seen"] = {}    # each pick's latest spec and phase (context reads earlier ones)
        self.more_coming: List[str] = []
        self.proposals = 0
        self.rejected = 0
        self.decided: Dict[str, str] = {}
        self.roles: Dict[str, Dict[str, str]] = {}   # a template pick's palette roles in the current run
        self.pool_roles: Dict[str, Dict[str, Dict[str, str]]] = {}   # a palette pick's schemes, as its pool had them
        self.param_values: Dict[str, Any] = {}
        self.kept: Set[str] = set()            # replayed (fixed) values: kept as they were
        self.held: Dict[str, str] = {}         # said picks drawing the user's words (as a pin would)
        self.own: Dict[str, frozenset] = {}    # each pick's own options (Pool.own): the fit check leaves them
        # Every option each pick was seen to have in this draw: its pool before exclusions, in
        # every run of the program, and its options under every value of a pick it follows.
        self.offered: Dict[str, Set[str]] = {}
        self.lists: Set[str] = set()   # picks that are the user's own lists
        self.pools: Dict[str, Any] = {}   # pool key → its length, or for a vocabulary list the whole pool
        self.labels: Dict[str, str] = {}
        # Pins a pick could break: its site feeds the pinned pick's structure or exclude.
        self.pin_watch: Dict[int, List[Tuple[str, Site]]] = {}
        for cid in sorted(self.single_pins):
            for s in an.sites_for_id(cid):
                for d in sorted(set(s.deps) | s.exclude_deps):
                    self.pin_watch.setdefault(d, []).append((cid, s))

    def _minors(self) -> Dict[str, Tuple[str, ...]]:
        """Each person who may be under 18, with those ages: from the program (an age pick
        narrowed to them, or the age the prompt states, see narrow.py), and from the user's
        own choices of an age pick here: a pin, an added value or a kept one. A person under
        18 is so because someone asked; nothing here reads the prompt's words."""
        out: Dict[str, Tuple[str, ...]] = {p: tuple(a) for p, a in (getattr(self.options, "minor_ages", None) or {}).items()}
        ages = {s.index for s in self.an.sites if s.kind == "pick" and s.cls and
                getattr(vocabulary().resolve(s.cls), "id", None) == AGE_LIST}
        if not ages:
            return out
        chosen: Dict[str, List[str]] = {}
        for cid, vs in self.pins.items():
            chosen.setdefault(cid, []).extend(vs)
        for cid, e in self.edits.items():
            chosen.setdefault(cid, []).extend(str(x) for x in (e or {}).get("add") or [])
        for cid, v in self.fixed.items():
            chosen.setdefault(cid, []).append(str(v))
        for cid, vs in chosen.items():
            if not any(s.index in ages for s in self.an.sites_for_id(cid)):
                continue
            young = minor_ages(vs)
            if young:
                p = person_of(cid)
                out[p] = tuple(dict.fromkeys([*out.get(p, ()), *young]))
        return out

    # -- primitives
    def propose(self, cid: str, items: List[Tuple[str, float]]) -> str:
        kept = self.fixed.get(cid)
        if kept is not None and cid not in self.kept and any(o == kept for o, _ in items):
            self.kept.add(cid)
            return str(kept)
        return self._weighted(items)

    def _weighted(self, items: List[Tuple[str, float]]) -> str:
        """One item by weight. Weight-0 items (opt-in values held for the picker) are drawn
        only when nothing else is left, which only pins allow (_settle)."""
        if not any(w > 0 for _, w in items):
            items = [(o, 1.0) for o, _ in items]
        else:
            items = [(o, w) for o, w in items if w > 0]
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
            execute(self.an.code, runner, (_Abort,))
        except _Abort as a:
            if probe is not None:
                raise
            raise DrawAborted(*a.args_) from None
        return runner

    # -- masking
    def shown(self, cid: str, value: Any) -> str:
        """A value as the image model reads it: a template filled with its palette."""
        roles = self.roles.get(cid)
        return fill(str(value), roles) if roles is not None else str(value)

    def state(self, exe: _Exec, k: float) -> str:
        """The text so far: pins and earlier phases in the clear, this phase and later
        ones masked as [Label] (fixed_text() masks every phase)."""
        out: List[str] = []
        for text, taint in exe.spans:
            hidden: List[Tuple[str, bool]] = []
            for s, derived in sorted(taint):
                if self.an.sites[s].phase < k:
                    continue
                for cid in exe.site_ids.get(s, []):
                    if cid in exe.by_id and cid not in self.single_pins and cid not in self.held:
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
        extra = [f"{exe.by_id[cid].label if cid in exe.by_id else self.labels.get(cid, _label_from_id(cid))}: {self.shown(cid, v)}"
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
            # Structure that still hangs on undrawn picks can't be checked yet; it is
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
        order = [cid for cid in exe.order if exe.seen[cid].phase == k and cid not in self.single_pins
                 and cid not in self.held]
        dirty = False
        for cid in order:
            if dirty:
                exe = self.execute(k, proposals)
                dirty = False
            seen = exe.seen.get(cid)
            if seen is None:
                continue
            chosen = self.decide(cid, seen, str(seen.value), k, proposals)
            self.decided[cid] = chosen
            if proposals.get(cid) != chosen:
                proposals[cid] = chosen
                dirty = True

    def decide(self, cid: str, seen: _Seen, first: str, k: int, proposals: Dict[str, str]) -> str:
        """The first proposal, unless it would leave a pin unsatisfiable: then batches of
        new proposals from the pool, and a DrawAborted when none fits."""
        hard: Dict[str, bool] = {}

        def is_hard_ok(v: str) -> bool:
            if v not in hard:
                hard[v] = self.hard_ok(cid, v, k, proposals, seen.site)
            return hard[v]

        if cid in self.kept and first == str(self.fixed.get(cid)) and is_hard_ok(first):
            return first  # a replayed value: kept as it was
        for batch in range(MAX_BATCHES + 1):
            for v in [first] if batch == 0 else [self._weighted(seen.items) for _ in range(BATCH)]:
                self.proposals += 1
                if is_hard_ok(v):
                    return v
                self.rejected += 1
        # Nothing fits: the pool is thin for this context. Ask for more now, so the next
        # run has better options (a user list is never expanded).
        if seen.spec.kind == "pick" and seen.spec.source != "list":
            self.options.request_more(seen.spec, seen.context, "high")
        pinned = next((pid for pid, _ in self.pin_watch.get(seen.site, []) if pid != cid), None)
        if pinned is not None:
            raise DrawAborted(pinned, self.labels.get(pinned, _label_from_id(pinned)), "pin", self.single_pins[pinned])
        raise DrawAborted(cid, seen.spec.label, "unresolved")

    def revision(self, source: str) -> Dict[str, Any]:
        # A vocabulary pool is recorded by the hash of its contents, kept once beside the generated
        # options (compact.py): written into every image's revision, a list of faces is 300 KB a person.
        kept = getattr(getattr(self.options, "store", None), "pools", None)
        pools = {k: kept.put(v) if kept is not None and isinstance(v, list) else v for k, v in self.pools.items()}
        rev = {
            "engine": DRAW_VERSION,
            "program": hashlib.sha256(source.encode("utf-8")).hexdigest()[:16],
            "pools": dict(sorted(pools.items())),
            "edits": hashlib.sha256(json.dumps(self.edits, sort_keys=True, default=str).encode()).hexdigest()[:16]
            if self.edits else None,
        }
        options_version = getattr(self.options, "revision_version", None)
        if options_version:  # the generated pools' version: replay reads those, not today's
            rev["options"] = options_version
        if self.context_on and (self.an.context_links or self.stated or self.list_context):
            rev["context"] = getattr(self.options, "context_version", None) or CONTEXT_VERSION
        rev["id"] = hashlib.sha256(json.dumps(rev, sort_keys=True).encode()).hexdigest()[:16]
        return rev


def draw(source: str, seed: int, pins: Optional[Dict[str, Sequence[str]]] = None,
         loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None,
         fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Dict[str, Any]]] = None, *,
         options: Optional[OptionsService] = None) -> DrawResult:
    """Draw one prompt from a program with pick specs. Deterministic for a given
    revision, seed and pins. Raises DrawAborted when a pick has nothing left to draw
    or a pin can't be satisfied, and ProgramError for a broken program."""
    an = analyze(source, context=getattr(options, "context", True) is not False)
    edits = edits or {}
    pins = dict(pins or {})
    # Pins are kept by a choice's id, so after a prompt is prepared again they can name values
    # the choice no longer offers. A draw that fails with such pins is made again, twice at most:
    # first with each single pinned value kept as the user's own option of that choice (they
    # pinned it: it is still what they want there, whatever the options became), and with sets
    # of ticks that match nothing, or a pin on the user's own list that isn't one of its items,
    # dropped; then, if that still fails (a value the program can't take), without those pins
    # at all. A value
    # the choice does offer, but not beside the other choices drawn, is refused as before.
    given_edits, held = edits, set()
    service_edits = getattr(options, "edits", None)   # the options service reads the user's edits too

    def with_edits(now: Dict[str, Dict[str, Any]]) -> None:
        if options is not None and service_edits is not None:
            options.edits = now
            literal = getattr(options, "literal", None)   # its pools of the program's own options
            if literal is not None and hasattr(literal, "edits"):
                literal.edits = now
            reset = getattr(options, "reset", None)
            if callable(reset):   # pools read so far were built from the other edits
                reset()
    try:
        for _attempt in range(2 * len(pins) + 2):
            eng = _Engine(an, seed, pins, {_lora_key(lo.name): lo for lo in (loras or [])}, tool_params,
                          dict(fixed or {}), edits, options or LiteralOptions(edits))
            try:
                for k in an.phases:
                    eng.run_phase(k)
                final = eng.execute(math.inf, {}, record=True)
                eng.check_pins(final, math.inf)
                break
            except ProgramError:
                unknown = [cid for cid in pins if cid not in held and cid in eng.offered
                           and not ({str(v) for v in pins[cid]} & eng.offered[cid])]
                keep = {cid for cid in unknown if len(pins[cid]) == 1 and cid not in eng.lists}
                if unknown:      # found now (a failure can hide the choices after it): kept or dropped
                    held |= keep
                    pins = {k: v for k, v in pins.items() if k not in unknown or k in keep}
                    edits = {**edits, **{cid: {**(edits.get(cid) or {}),
                                               "add": [*((edits.get(cid) or {}).get("add") or []), *map(str, pins[cid])]}
                                         for cid in keep}}
                elif held:       # a kept value the program can't take: those pins go, and their options
                    pins = {k: v for k, v in pins.items() if k not in held}
                    edits = {k: (given_edits[k] if k in given_edits else v) for k, v in edits.items()
                             if k not in held or k in given_edits}
                    held = set()
                else:
                    raise
                with_edits(edits)
        else:
            raise ProgramError("The program couldn't be drawn with these pinned choices.")
    finally:
        if edits is not given_edits:
            with_edits(given_edits)
    prompt = tidy_text(final.parts)
    if not prompt:
        raise ProgramError("The program emitted no prompt text. Call emit(...) with the finished prompt.")
    for lu in final.lora_uses:
        if lu.trigger and lu.trigger.lower() not in prompt.lower():
            prompt = f"{lu.trigger}, {prompt}"
    stats = {"proposals": eng.proposals, "rejected": eng.rejected}
    return DrawResult(prompt, final.draws, final.lora_uses, final.params, final.groups, seed,
                      revision=eng.revision(source),
                      more_coming=list(dict.fromkeys(eng.more_coming)), stats=stats,
                      value_parts=_value_parts(final))


@functools.lru_cache(maxsize=128)
def _fixed_text(source: str, loras: Tuple[Tuple[str, str, float, str], ...], tool_params: Optional[FrozenSet[str]]) -> str:
    an = analyze(source)
    infos = [LoraInfo(*lo) for lo in loras]
    eng = _Engine(an, 0, {}, {_lora_key(lo.name): lo for lo in infos}, set(tool_params) if tool_params else None,
                  {}, {}, LiteralOptions())
    return eng.state(eng.execute(0, {}), 0)


def fixed_text(source: str, loras: Optional[Sequence[LoraInfo]] = None, tool_params: Optional[Set[str]] = None) -> str:
    """The program's text with every pick masked as [Label]: what the prompt states
    before anything is drawn. Branches and loops take their first options."""
    key = tuple((lo.name, lo.path, lo.weight, lo.trigger) for lo in loras or ())
    return _fixed_text(source, key, frozenset(tool_params) if tool_params else None)


__all__ = [
    "CONTEXT_VERSION", "CONTEXT_VERSIONS", "Analysis", "DrawAborted", "DrawResult", "LiteralOptions", "OptionsService", "PickSpec", "Pool",
    "analyze", "context_links", "context_suffix", "draw", "fixed_text", "owns", "person_of", "pool_key", "uses_draws", "value_spans",
]

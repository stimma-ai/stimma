"""Kinds of slot and context tables as vocabulary data: what a person, a light or a pack's new
kind of slot is, how the reader recognizes it and what it asks, which lists its variants draw
and how, and what the writer and Improve are told of it. The schema is described for pack
authors in stimma-plans `active/fluent-ship/VOCAB_SCHEMA.md`.

    vocab/kinds/<kind>.json       one kind of slot
    vocab/contexts/<table>.json   one context table: entries (a country, a realm) whose shares weight a list

The engine reads these declarations and nothing else about the world: reader.py composes its
prompt from each kind's reader part and checks the reply against its questions, seeding.py turns
a reading into banks by the kind's draw rules, variants.py draws per-variant seeds by each rule's
role and composes the writer's prompt from each kind's writing rules, places.py weights a list by
the context table that weights it.

Parsing here is strict about shape and lenient about nothing: `Bad` names what is wrong, and the
loader (vocab.load) decides what a failure costs (the built-in root raises; a pack's file is
skipped and logged).
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROLES = ("heritage", "who", "age", "core", "each", "idea")
QUESTION_TYPES = ("words", "choice", "stated", "vary", "list", "part", "context")
ENGINE_KINDS = ("list", "free")   # binding a slot to a list, or to idea lists: the engine's own
SOURCES = ("part", "notes", "before", "prompt")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class Bad(ValueError):
    """What is wrong with a kind or a table file, said plainly."""


# --------------------------------------------------------------------------- reading the shapes

def _str(d: Dict[str, Any], k: str, where: str, default: str = "") -> str:
    v = d.get(k, default)
    if not isinstance(v, str):
        raise Bad(f"{where}: {k} must be text")
    return v


def _strs(d: Dict[str, Any], k: str, where: str) -> Tuple[str, ...]:
    v = d.get(k) or []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise Bad(f"{where}: {k} must be a list of text")
    return tuple(v)


def _dict(d: Dict[str, Any], k: str, where: str) -> Dict[str, Any]:
    v = d.get(k) or {}
    if not isinstance(v, dict):
        raise Bad(f"{where}: {k} must be an object")
    return v


@dataclass(frozen=True)
class Option:
    """One answer a choice question allows."""
    answer: str
    text: str = ""
    last: bool = False             # stays at the end when packs add options ("other")
    note: str = ""                 # a line in the writer's turn when chosen (a couple's "describe both")
    room: int = 0                  # words a variant may add, when chosen (several people)
    second_heritage: float = 0.0   # the share of variants whose second person gets a heritage of their own
    heritage: str = ""             # the list that plays the heritage role for this sort of being


@dataclass(frozen=True)
class Question:
    """One thing the reader answers about a part of a kind, in its reply object under `key`."""
    key: str
    type: str
    ask: str = ""
    more: Tuple[str, ...] = ()
    options: Tuple[Option, ...] = ()
    options_from: Tuple[str, str] = ("", "")   # (list, local facet) whose parts are the answers
    default: str = ""
    always: bool = False           # stored even when empty or the default
    sources: Tuple[str, ...] = ("part", "notes")
    required: str = ""             # a message: an answer that fails is asked again with it
    invalid: str = ""              # a message: a list or context answer that names none is asked again with it
    under: str = ""                # a list answer's prefix (lighting)
    exclude: Tuple[str, ...] = ()  # lists a list answer may not name
    also: Tuple[str, ...] = ()     # answers allowed besides a list's id ("written")
    only_if_varies: str = ""
    cleared_by: str = ""
    with_stated: bool = False
    needs_one_of: Tuple[str, ...] = ()
    needs_message: str = ""
    except_: Tuple[str, ...] = ()
    tables: Tuple[str, ...] = ()   # a context answer's tables (none: every table)
    none: str = ""                 # a context question's closing words for no answer

    def option(self, answer: str) -> Optional[Option]:
        return next((o for o in self.options if o.answer == answer), None)

    def answers(self, vocab: Any = None) -> Tuple[str, ...]:
        if self.options_from[0] and vocab is not None:
            leaf = vocab.get(self.options_from[0])
            return tuple(leaf.local_facets.get(self.options_from[1], ())) if leaf is not None else ()
        return tuple(o.answer for o in self.options)


@dataclass(frozen=True)
class Detail:
    """Something about a part the reader may say its words state or that varies, bound to a list."""
    name: str
    list: str
    about: str = ""
    reader: bool = True            # listed in the reader's prompt
    needs: Dict[str, str] = field(default_factory=dict)   # {"answered": key, "unless_varied": detail}


@dataclass(frozen=True)
class DrawRule:
    """One list a slot of a kind draws from, by a role the engine knows (variants.py)."""
    role: str
    list: Any                      # an id, or {"answer"|"option"|"detail"|"varied": ...}
    phrase: Any = None
    about: str = ""
    where: Dict[str, Any] = field(default_factory=dict)
    scene: bool = False
    when: Dict[str, Any] = field(default_factory=dict)
    unless: Dict[str, Any] = field(default_factory=dict)
    label: str = ""
    say: str = "value"             # "short": the list's short form of the value
    show: str = ""                 # "must": the variant carries the value's words
    stages: Dict[str, str] = field(default_factory=dict)   # a who rule's list for a person read as a child or a teenager
    adults: bool = False           # drawn only for an adult: left out of a child's or a teenager's seeds (a build)


@dataclass(frozen=True)
class Aspects:
    """What each variant of a kind develops in particular, rotated so a pool shares no template."""
    items: Tuple[str, ...]
    per_variant: int = 2
    drop: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    typical: Optional[Dict[str, Any]] = None

    def typical_share(self, answers: Optional[Dict[str, Any]] = None) -> float:
        """The typical share for a reading: the declared share, or the larger one its `implied`
        rule gives when the reading answers so (a person whose role and place say what they wear)."""
        typ = self.typical or {}
        imp = typ.get("implied") or {}
        if imp and str((answers or {}).get(str(imp.get("answer") or "")) or "") == str(imp.get("is") or ""):
            return float(imp.get("share") or 0.0)
        return float(typ.get("share") or 0.0)

    def typical_at(self, i: int, share: Optional[float] = None) -> bool:
        """Whether variant i (from 0) is one of the typical share, spread evenly: with share 1/3,
        the third, sixth, ninth. A share written as 0.333333 counts as a third."""
        share = float((self.typical or {}).get("share") or 0.0) if share is None else share
        if share <= 0:
            return False
        return math.floor((i + 1) * share + 1e-3) > math.floor(i * share + 1e-3)


@dataclass(frozen=True)
class Kind:
    id: str
    order: int = 100
    recognize: Tuple[str, ...] = ()
    heading: str = ""
    text: str = ""
    example: Optional[Dict[str, Any]] = None
    examples: Tuple[Dict[str, Any], ...] = ()
    category: str = ""
    details_heading: str = ""
    single_detail: str = ""
    require_one: Optional[Dict[str, Any]] = None
    questions: Tuple[Question, ...] = ()
    details: Dict[str, Detail] = field(default_factory=dict)
    noun_default: str = ""
    first_write: int = 30
    room: int = 0
    draws: Tuple[DrawRule, ...] = ()
    aspects: Optional[Aspects] = None
    writer_examples: Tuple[str, ...] = ()
    writer_rules: Tuple[str, ...] = ()
    seed_rules: Tuple[str, ...] = ()
    note: str = ""
    improve: Tuple[str, ...] = ()
    whole: str = ""                # the writer's line when the whole part is its category ("{cat}")

    @property
    def no_category(self) -> bool:
        return bool(self.category)

    def question(self, key: str) -> Optional[Question]:
        return next((q for q in self.questions if q.key == key), None)

    def roles(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(r.role for r in self.draws))

    @property
    def people_like(self) -> bool:
        """A kind whose variants are seeded with a heritage, a gender or an age: it waits for its
        narrowing (the minors rules read its age) and its picker has those rows."""
        return bool({"heritage", "who", "age"} & set(self.roles()))

    def heritage_lists(self) -> Tuple[str, ...]:
        out: List[str] = []
        for r in self.draws:
            if r.role != "heritage":
                continue
            if isinstance(r.list, str):
                out.append(r.list)
            elif isinstance(r.list, dict) and "option" in r.list:
                q = self.question(str(r.list["option"]))
                out += [getattr(o, str(r.list.get("field") or "heritage"), "") for o in (q.options if q else ())]
        return tuple(x for x in dict.fromkeys(out) if x)


def _option(d: Any, where: str) -> Option:
    if not isinstance(d, dict) or not isinstance(d.get("answer"), str) or not d["answer"]:
        raise Bad(f"{where}: an option needs an answer")
    w = f"{where} option {d['answer']!r}"
    share = d.get("second_heritage", 0.0)
    if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 <= share <= 1:
        raise Bad(f"{w}: second_heritage must be a share between 0 and 1")
    room = d.get("room", 0)
    if not isinstance(room, int) or isinstance(room, bool) or room < 0:
        raise Bad(f"{w}: room must be a whole number of words")
    return Option(d["answer"], _str(d, "text", w), d.get("last") is True, _str(d, "note", w), room, float(share),
                  _str(d, "heritage", w))


def _question(d: Any, where: str) -> Question:
    if not isinstance(d, dict):
        raise Bad(f"{where}: a question must be an object")
    key = d.get("key")
    if not isinstance(key, str) or not _NAME.match(key):
        raise Bad(f"{where}: a question's key must be a plain lowercase word, not {key!r}")
    w = f"{where} question {key!r}"
    t = d.get("type")
    if t not in QUESTION_TYPES:
        raise Bad(f"{w}: type must be one of {', '.join(QUESTION_TYPES)}")
    opts = tuple(_option(o, w) for o in (d.get("options") or []))
    if len({o.answer for o in opts}) != len(opts):
        raise Bad(f"{w}: two options give the same answer")
    frm = _dict(d, "options_from", w)
    if t == "choice" and not opts and not frm:
        raise Bad(f"{w}: a choice needs options or options_from")
    sources = _strs(d, "from", w) or ("part", "notes")
    if any(s not in SOURCES for s in sources):
        raise Bad(f"{w}: from may name only {', '.join(SOURCES)}")
    if d.get("store", "set") not in ("set", "always"):
        raise Bad(f"{w}: store is \"always\" or \"set\"")
    return Question(key, t, _str(d, "ask", w), _strs(d, "more", w), opts,
                    (str(frm.get("list") or ""), str(frm.get("facet") or "")) if frm else ("", ""),
                    _str(d, "default", w), d.get("store") == "always", sources, _str(d, "required", w),
                    _str(d, "invalid", w), _str(d, "under", w), _strs(d, "exclude", w), _strs(d, "also", w),
                    _str(d, "only_if_varies", w), _str(d, "cleared_by", w), d.get("with_stated") is True,
                    _strs(d, "needs_one_of", w), _str(d, "needs_message", w), _strs(d, "except", w),
                    _strs(d, "tables", w), _str(d, "none", w))


_LIST_FORMS = ("answer", "option", "detail", "varied")
STAGE_READINGS = ("child", "teenager")   # the readings a who rule's stages name (ages.py)
_PHRASE_FORMS = ("stated",)


def _rule(d: Any, where: str) -> DrawRule:
    if not isinstance(d, dict):
        raise Bad(f"{where}: a draw rule must be an object")
    role = d.get("role")
    if role not in ROLES:
        raise Bad(f"{where}: a draw rule's role must be one of {', '.join(ROLES)}, not {role!r}")
    w = f"{where} {role} rule"
    lst = d.get("list")
    if isinstance(lst, dict):
        if not any(k in lst for k in _LIST_FORMS):
            raise Bad(f"{w}: list must be an id or one of {', '.join(_LIST_FORMS)}")
    elif not isinstance(lst, str) or not lst:
        raise Bad(f"{w}: list must be an id or an object")
    ph = d.get("phrase")
    if ph is not None and ph not in ("words", "") and not (isinstance(ph, dict) and isinstance(ph.get("stated"), str)):
        raise Bad(f"{w}: phrase must be \"words\" or {{\"stated\": ...}}")
    for k in ("when", "unless", "where"):
        _dict(d, k, w)
    if d.get("say", "value") not in ("value", "short"):
        raise Bad(f"{w}: say is \"value\" or \"short\"")
    if d.get("show", "") not in ("", "must"):
        raise Bad(f"{w}: show is \"must\" or left out")
    if role in ("who", "each") and not _str(d, "label", w):
        raise Bad(f"{w}: a {role} rule needs the label its seed line shows")
    stages = _dict(d, "stages", w)
    if stages and (role != "who" or not isinstance(lst, str)):
        raise Bad(f"{w}: only a who rule with a list id has stages")
    if any(k not in STAGE_READINGS or not isinstance(v, str) or not v for k, v in stages.items()):
        raise Bad(f"{w}: stages map {' or '.join(STAGE_READINGS)} to a list id")
    return DrawRule(role, lst, ph, _str(d, "about", w), dict(d.get("where") or {}), d.get("scene") is True,
                    dict(d.get("when") or {}), dict(d.get("unless") or {}), _str(d, "label", w),
                    str(d.get("say") or "value"), str(d.get("show") or ""), {str(k): str(v) for k, v in stages.items()},
                    d.get("adults") is True)


def _aspects(d: Any, where: str) -> Optional[Aspects]:
    if d is None:
        return None
    if not isinstance(d, dict):
        raise Bad(f"{where}: aspects must be an object")
    items = _strs(d, "list", f"{where} aspects")
    n = d.get("per_variant", 2)
    if not items or not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(items):
        raise Bad(f"{where}: aspects need a list and a per_variant between 1 and its length")
    drop = _dict(d, "drop", f"{where} aspects")
    if any(k not in items for k in drop):
        raise Bad(f"{where}: aspects drop names an aspect not in the list")
    typ = d.get("typical")
    if typ is not None:
        if not isinstance(typ, dict) or not isinstance(typ.get("text"), str) or not typ["text"]:
            raise Bad(f"{where}: typical needs its text")
        share = typ.get("share")
        if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 <= share <= 1:
            raise Bad(f"{where}: typical's share must be between 0 and 1")
        if typ.get("replaces") and typ["replaces"] not in items:
            raise Bad(f"{where}: typical replaces an aspect not in the list")
        if not isinstance(typ.get("alone", False), bool):
            raise Bad(f"{where}: typical's alone is true or false")
        if any(x not in items for x in _strs(typ, "without", f"{where} typical")):
            raise Bad(f"{where}: typical's without names an aspect not in the list")
        imp = typ.get("implied")
        if imp is not None and not (isinstance(imp, dict) and isinstance(imp.get("answer"), str) and isinstance(imp.get("is"), str)
                                    and isinstance(imp.get("share"), (int, float)) and not isinstance(imp.get("share"), bool)
                                    and 0 <= imp["share"] <= 1):
            raise Bad(f"{where}: typical's implied needs an answer, the answer it is, and a share between 0 and 1")
    return Aspects(items, n, {k: dict(v or {}) for k, v in drop.items()}, dict(typ) if typ else None)


def parse_kind(d: Any, where: str) -> Kind:
    """A kind from its file's JSON (after any extensions are merged), or Bad."""
    if not isinstance(d, dict):
        raise Bad(f"{where}: a kind file must be an object")
    kid = d.get("id")
    if not isinstance(kid, str) or not _NAME.match(kid):
        raise Bad(f"{where}: a kind's id must be a plain lowercase word")
    if kid in ENGINE_KINDS:
        raise Bad(f"{where}: {kid!r} is the engine's own kind")
    w = f"kind {kid}"
    r = _dict(d, "reader", w)
    if not _strs(r, "recognize", w):
        raise Bad(f"{w}: reader.recognize must say how the reader knows it")
    qs = tuple(_question(q, w) for q in (r.get("questions") or []))
    if len({q.key for q in qs}) != len(qs):
        raise Bad(f"{w}: two questions have the same key")
    if {"kind", "label", "lead", "category", "n"} & {q.key for q in qs}:
        raise Bad(f"{w}: a question's key may not be kind, label, lead, category or n")
    details: Dict[str, Detail] = {}
    for name, x in _dict(d, "details", w).items():
        if not _NAME.match(str(name)) or not isinstance(x, dict) or not isinstance(x.get("list"), str):
            raise Bad(f"{w}: detail {name!r} needs a plain name and a list")
        details[name] = Detail(name, x["list"], _str(x, "about", w), x.get("reader", True) is not False,
                               {str(k): str(v) for k, v in _dict(x, "needs", w).items()})
    ex = r.get("example")
    if ex is not None and not isinstance(ex, dict):
        raise Bad(f"{w}: reader.example must be an object")
    examples = r.get("examples") or []
    if not isinstance(examples, list) or not all(isinstance(e, dict) and isinstance(e.get("intro"), str)
                                                 and isinstance(e.get("reply"), dict) for e in examples):
        raise Bad(f"{w}: reader.examples must be objects with an intro and a reply")
    req = r.get("require_one")
    if req is not None and not (isinstance(req, dict) and _strs(req, "of", w) and isinstance(req.get("message"), str)):
        raise Bad(f"{w}: reader.require_one needs of and message")
    if r.get("single_detail", "") not in ("", "list"):
        raise Bad(f"{w}: reader.single_detail is \"list\" or left out")
    wr = _dict(d, "writer", w)
    for k in ("first_write", "room", "order"):
        v = d.get(k, 0)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise Bad(f"{w}: {k} must be a whole number")
    first = d.get("first_write") or 30
    if not 1 <= first <= 100:
        raise Bad(f"{w}: first_write must be between 1 and 100")
    return Kind(kid, int(d.get("order", 100)), _strs(r, "recognize", w), _str(r, "heading", w), _str(r, "text", w),
                ex, tuple(examples), _str(r, "category", w), _str(r, "details_heading", w), _str(r, "single_detail", w),
                req, qs, details, _str(d, "noun_default", w), int(first), int(d.get("room") or 0),
                tuple(_rule(x, w) for x in (d.get("draws") or [])), _aspects(d.get("aspects"), w),
                _strs(wr, "examples", w), _strs(wr, "rules", w), _strs(wr, "seed_rules", w), _str(wr, "note", w),
                _strs(d, "improve", w), _str(wr, "whole", w))


def check_kind_lists(k: Kind, vocab_get: Any) -> None:
    """Bad when a kind names a list the vocabulary doesn't have (a pack missing a file)."""
    def need(lid: str, what: str) -> None:
        if lid and vocab_get(lid) is None:
            raise Bad(f"kind {k.id}: {what} names the list {lid!r}, which isn't loaded")
    for d in k.details.values():
        need(d.list, f"detail {d.name}")
    for q in k.questions:
        need(q.options_from[0], f"question {q.key}")
        for o in q.options:
            need(o.heritage, f"option {o.answer!r} of {q.key}")
    for r in k.draws:
        for st, lid in r.stages.items():
            need(lid, f"a {r.role} rule's {st} stage")
        if isinstance(r.list, str):
            need(r.list, f"a {r.role} rule")
        elif "answer" in r.list:
            need(str(r.list.get("default") or ""), f"a {r.role} rule's default")
            if k.question(str(r.list["answer"])) is None:
                raise Bad(f"kind {k.id}: a {r.role} rule takes its list from {r.list['answer']!r}, which it doesn't ask")
        elif "option" in r.list and k.question(str(r.list["option"])) is None:
            raise Bad(f"kind {k.id}: a {r.role} rule takes its list from {r.list['option']!r}, which it doesn't ask")
        elif "detail" in r.list and r.list["detail"] not in k.details:
            raise Bad(f"kind {k.id}: a {r.role} rule names detail {r.list['detail']!r}, which it doesn't declare")


# --------------------------------------------------------------------------- extending a kind

_KIND_LISTS = ("improve",)
_READER_LISTS = ("recognize", "examples")
_WRITER_LISTS = ("examples", "rules", "seed_rules")


def extend_kind(base: Dict[str, Any], ext: Dict[str, Any], where: str) -> Tuple[Dict[str, Any], List[str]]:
    """A kind's JSON with a later root's extension merged in, and what was skipped (anything that
    would replace what the kind already says). Adds questions, options of choice questions,
    details, draw rules, writing rules, examples, recognize lines and Improve sentences."""
    out = copy.deepcopy(base)
    skipped: List[str] = []
    for k, v in ext.items():
        if k in ("id", "extend"):
            continue
        if k == "draws":
            out.setdefault("draws", []).extend(copy.deepcopy(v or []))
        elif k in _KIND_LISTS:
            out.setdefault(k, []).extend(v or [])
        elif k == "details":
            have = out.setdefault("details", {})
            for name, x in (v or {}).items():
                if name in have:
                    skipped.append(f"{where}: detail {name!r} is already declared")
                else:
                    have[name] = x
        elif k == "reader":
            r = out.setdefault("reader", {})
            for rk, rv in (v or {}).items():
                if rk in _READER_LISTS:
                    r.setdefault(rk, []).extend(rv or [])
                elif rk == "questions":
                    qs = r.setdefault("questions", [])
                    for q in rv or []:
                        mine = next((x for x in qs if isinstance(q, dict) and x.get("key") == q.get("key")), None)
                        if mine is None:
                            qs.append(copy.deepcopy(q))
                            continue
                        extra = {qk for qk in q if qk not in ("key", "options")}
                        if extra:
                            skipped.append(f"{where}: question {q['key']!r} already exists; only options are added "
                                           f"(ignored: {', '.join(sorted(extra))})")
                        have = {o.get("answer") for o in mine.get("options") or []}
                        opts = mine.setdefault("options", [])
                        for o in q.get("options") or []:
                            if o.get("answer") in have:
                                skipped.append(f"{where}: question {q['key']!r} already allows {o.get('answer')!r}")
                                continue
                            at = next((i for i, x in enumerate(opts) if x.get("last")), len(opts))
                            opts.insert(at, copy.deepcopy(o))
                            have.add(o.get("answer"))
                else:
                    skipped.append(f"{where}: reader.{rk} is the kind's own and isn't replaced")
        elif k == "writer":
            wr = out.setdefault("writer", {})
            for wk, wv in (v or {}).items():
                if wk in _WRITER_LISTS:
                    wr.setdefault(wk, []).extend(wv or [])
                else:
                    skipped.append(f"{where}: writer.{wk} is the kind's own and isn't replaced")
        else:
            skipped.append(f"{where}: {k} is the kind's own and isn't replaced")
    return out, skipped


# --------------------------------------------------------------------------- context tables

@dataclass(frozen=True)
class Entry:
    """A place in a context table: a country, a realm. Its shares are of the table's list's values."""
    code: str
    name: str
    aliases: Tuple[str, ...]
    shares: Tuple[Tuple[str, float], ...]
    notes: str = ""


@dataclass(frozen=True)
class Table:
    """A context table: its entries' shares weight one list (P = w * local + (1 - w) * global)."""
    id: str
    weights: str
    entries: Dict[str, Entry]
    weight_prompt: float = 0.9
    weight_default: float = 0.8
    user_default: bool = False
    ask: str = ""
    about: str = ""

    def named(self, name: Any) -> Optional[Entry]:
        key = str(name or "").strip().casefold()
        return self._names.get(key) if key else None

    @property
    def _names(self) -> Dict[str, Entry]:
        got = self.__dict__.get("_names_cache")
        if got is None:
            got = {n.strip().casefold(): e for e in self.entries.values() for n in (e.name, *e.aliases)}
            object.__setattr__(self, "_names_cache", got)
        return got


def parse_entries(tid: str, raw: Dict[str, Any], values: Optional[set], pattern: str, weights: str,
                  taken: Dict[str, str]) -> Tuple[Dict[str, Entry], List[str]]:
    """A table's entries, checked: codes, values of the weighted list, shares in (0, 1] summing to
    at most 1, names unique (here and against `taken`, every table's names so far). Bad for the
    first problem."""
    out: Dict[str, Entry] = {}
    names: Dict[str, str] = {}
    rx = re.compile(pattern) if pattern else None
    for code, d in raw.items():
        if not isinstance(d, dict) or not isinstance(d.get("name"), str) or not d["name"].strip():
            raise Bad(f"table {tid}: entry {code!r} needs a name")
        if rx is not None and not rx.match(code):
            raise Bad(f"table {tid}: code {code!r} does not match the table's code pattern")
        shares = d.get("shares") or {}
        if not isinstance(shares, dict):
            raise Bad(f"table {tid}: entry {code}'s shares must be an object")
        pairs = []
        for h, x in shares.items():
            if values is not None and h not in values:
                raise Bad(f"table {tid}: entry {code} names {h!r}, which is not a {weights} value")
            if not isinstance(x, (int, float)) or isinstance(x, bool) or not 0 < x <= 1:
                raise Bad(f"table {tid}: entry {code} gives {h!r} a share of {x}")
            pairs.append((str(h), float(x)))
        if sum(x for _, x in pairs) > 1.0001:
            raise Bad(f"table {tid}: entry {code}'s shares sum past 1")
        e = Entry(code, d["name"], tuple(str(a) for a in d.get("aliases") or ()), tuple(pairs), str(d.get("notes") or ""))
        for n in (e.name, *e.aliases):
            k = n.strip().casefold()
            if k in names or k in taken:
                raise Bad(f"table {tid}: the name {n!r} stands for both {names.get(k) or taken.get(k)} and {code}")
            names[k] = code
        out[code] = e
    return out, []


def parse_table_head(d: Any, where: str) -> Dict[str, Any]:
    """A table file's own fields, checked (its entries are checked with its list)."""
    if not isinstance(d, dict):
        raise Bad(f"{where}: a table file must be an object")
    tid = d.get("id")
    if not isinstance(tid, str) or not _NAME.match(tid):
        raise Bad(f"{where}: a table's id must be a plain lowercase word")
    if not isinstance(d.get("weights"), str) or not d["weights"]:
        raise Bad(f"table {tid}: weights must name the list its entries weight")
    w = _dict(d, "weight", f"table {tid}")
    for k in ("prompt", "default"):
        x = w.get(k, 0.9 if k == "prompt" else 0.8)
        if not isinstance(x, (int, float)) or isinstance(x, bool) or not 0 <= x <= 1:
            raise Bad(f"table {tid}: weight.{k} must be between 0 and 1")
    if not isinstance(d.get("entries") or {}, dict):
        raise Bad(f"table {tid}: entries must be an object keyed by code")
    for k in ("ask", "about", "code_pattern"):
        _str(d, k, f"table {tid}")
    return d


__all__ = ["Aspects", "Bad", "Detail", "DrawRule", "ENGINE_KINDS", "Entry", "Kind", "Option", "QUESTION_TYPES", "Question",
           "ROLES", "Table", "check_kind_lists", "extend_kind", "parse_entries", "parse_kind", "parse_table_head"]

"""Typical people: a bound person attribute follows what's known about that person.

Drawn evenly, wide person lists make odd combinations the norm (grey hair at 21, blue eyes
on most Korean women, a beard on a five-year-old). Typicality tables in the vocabulary
(`vocab/person/_typicality/<given>.<target>.json`) say how each target value's frequency
shifts for one given value, relative to people in general:

    {"given": "person.age_band", "target": "person.hair_color",
     "rows": {"20–24": {"gray": "rare", "black": "common", ...}, ...}}

When a `cls=` pick is drawn, its values' tier weights are multiplied by the level weight of
every given value known for the same person (several givens multiply; a mixture of given
values, like "young" over several age bands, averages). What is known comes from:

- other bound picks already decided or pinned (`age_band`, `ethnicity`), matched to this
  pick's person by id and by the person its `about=` names;
- the prompt text so far (stated words and decided values in the clear): "a Japanese
  woman", "a 16 y.o. boy", "aged 25–29", "an elderly man", "his beard".

A given pick drawn after its targets (age in a later phase than hair) is weighted the other
way, by Bayes: P(age | hair) ∝ w(age) · m(age, hair) / Z(age), so draw order doesn't skew
the joint; within a phase givens decide first (draws.py). A given whose target is still to
draw avoids values that target can't follow (no child's age while a beard is pending), and
a bound age or descent pick keeps to what the text states ("a man": no child bands; "an
Asian woman": Asian descents).

User lists and stated text are never reweighted; a pinned, decided or replayed value is
never dropped; the picker still lists every value. Missing tables or values change nothing.
A revision records each pick's conditioning keys and multipliers, so it replays the same
after the tables or the words read from prompts change.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prompt_programs.vocab import ROOT, vocabulary

# How much a level scales a value's weight. Tunable; the tables only name levels.
LEVEL_WEIGHTS = {"common": 1.0, "uncommon": 0.3, "rare": 0.01, "implausible": 0.0}
# A given value whose pending target is this hard to fill (its average level weight) or
# harder is scaled down toward 0: a child when a beard is still to draw.
PENDING_FLOOR = 0.05
KEEP = 1e-9          # weight a protected value (pinned, decided, replayed) keeps when its level is 0
TABLE_DIR = "_typicality"
PRESENTATION = "presentation"   # a given that isn't a class: read from words, never drawn

Mixture = Tuple[Tuple[str, float], ...]   # given values with probabilities, sorted


@dataclass(frozen=True)
class Table:
    given: str
    target: str
    rows: Dict[str, Dict[str, float]]     # given value -> target value -> weight
    _z: Dict[str, float] = field(default_factory=dict, compare=False, hash=False, repr=False)

    def factor(self, mix: Mixture, value: str) -> float:
        """The mixture's average weight for one target value (a missing cell counts 1)."""
        num = den = 0.0
        for g, p in mix:
            row = self.rows.get(g)
            if row is None:
                continue
            num += p * row.get(value, 1.0)
            den += p
        return num / den if den else 1.0


@dataclass
class Tables:
    tables: List[Table]
    lexicon: Dict[str, Any]
    version: str

    def for_target(self, cls: str) -> List[Table]:
        return [t for t in self.tables if t.target == cls]

    def for_given(self, cls: str) -> List[Table]:
        return [t for t in self.tables if t.given == cls]

    def involves(self, cls: str) -> bool:
        return any(cls in (t.given, t.target) for t in self.tables)

    @property
    def givens(self) -> List[str]:
        return sorted({t.given for t in self.tables})


def load(roots: Sequence[Path] = (ROOT,)) -> Tables:
    tables: List[Table] = []
    lexicon: Dict[str, Any] = {}
    h = hashlib.sha256()
    for root in roots:
        for p in sorted(root.rglob(f"{TABLE_DIR}/*.json")):
            raw = p.read_bytes()
            h.update(str(p.relative_to(root)).encode() + raw)
            d = json.loads(raw)
            if p.name == "stated.json":
                for k, v in d.items():
                    lexicon.setdefault(k, v)
                continue
            rows = {str(g): {str(v): LEVEL_WEIGHTS.get(str(lvl), 1.0) for v, lvl in (cells or {}).items()}
                    for g, cells in (d.get("rows") or {}).items()}
            if d.get("given") and d.get("target") and rows:
                tables.append(Table(str(d["given"]), str(d["target"]), rows))
    return Tables(tables, lexicon, "typ-" + h.hexdigest()[:12] if tables else "")


@lru_cache(maxsize=1)
def tables() -> Tables:
    return load()


# --------------------------------------------------------------------------- reading people from text

@dataclass(frozen=True)
class Who:
    """The person a pick is about: a noun ("girl", "goblin") and/or a presentation."""
    noun: str = ""
    gender: str = ""


@dataclass(frozen=True)
class Mention:
    noun: str
    gender: str
    facts: Tuple[Tuple[str, Mixture], ...]      # given class -> mixture
    stated: Tuple[Tuple[str, str], ...]          # target class -> value stated ("gray hair")
    ages: Optional[Tuple[int, int]] = None       # the age range stated or implied ("a man": 18+)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).replace("–", "-").replace("—", "-")).strip().lower()


def _singular(w: str, nouns: Dict[str, Any]) -> str:
    if w in nouns:
        return w
    plural = (nouns.get("_plurals") or {}).get(w)
    if plural:
        return plural
    if w.endswith("s") and w[:-1] in nouns:
        return w[:-1]
    return w


def _nouns(lex: Dict[str, Any]) -> Dict[str, Any]:
    return lex.get("nouns") or {}


def who_of(about: str, label: str, cid: str, lex: Optional[Dict[str, Any]] = None) -> Who:
    """The person a pick names: "the girl's hair colour" → girl; "his eyes" → masculine."""
    lex = lex if lex is not None else tables().lexicon
    nouns = _nouns(lex)
    for text in (about, label):
        t = _norm(text)
        m = re.search(r"\b([a-z][a-z-]*)['’]s?\b", t) if "'" in t or "’" in t else None
        if m:
            n = _singular(m.group(1), nouns)
            info = nouns.get(n) or {}
            return Who(n, str(info.get("gender") or ""))
        words = re.findall(r"[a-z][a-z-]*", t)
        for w in words:
            n = _singular(w, nouns)
            if n in nouns and not n.startswith("_"):
                return Who(n, str(nouns[n].get("gender") or ""))
        for w in words:
            if w in ("her", "she", "hers", "herself"):
                return Who("", "feminine")
            if w in ("his", "he", "him", "himself"):
                return Who("", "masculine")
    for w in re.split(r"[^a-z]+", str(cid).lower()):
        n = _singular(w, nouns)
        if n in nouns and not n.startswith("_"):
            return Who(n, str(nouns[n].get("gender") or ""))
    return Who()


def _band_bounds(text: str) -> Optional[Tuple[int, int]]:
    m = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


@lru_cache(maxsize=8)
def _bands(version: str) -> Tuple[Tuple[str, int, int], ...]:
    leaf = vocabulary().get("person.age_band")
    out = []
    for v in leaf.values if leaf else ():
        b = _band_bounds(v.text)
        if b:
            out.append((v.text, b[0], b[1]))
    return tuple(out)


def age_mixture(lo: int, hi: int) -> Mixture:
    """Age bands overlapping [lo, hi], each weighted by the share of it inside the range
    times its tier weight: "young" spreads over 18–34 evenly, "girl" leans adult like the
    list's own prior does."""
    leaf = vocabulary().get("person.age_band")
    tiers = {v.text: v.weight for v in (leaf.values if leaf else ())}
    got = []
    for text, a, b in _bands(vocabulary().version):
        n = min(b, hi) - max(a, lo) + 1
        if n > 0:
            got.append((text, n / (b - a + 1) * tiers.get(text, 1.0)))
    total = sum(w for _, w in got)
    return tuple(sorted((t, round(w / total, 6)) for t, w in got)) if total else ()


def bands_in(lo: int, hi: int) -> Tuple[str, ...]:
    return tuple(t for t, a, b in _bands(vocabulary().version) if min(b, hi) >= max(a, lo))


_DECADES = {"teens": 10, "twenties": 20, "thirties": 30, "forties": 40, "fifties": 50, "sixties": 60,
            "seventies": 70, "eighties": 80, "nineties": 90}


def _decade(m: "re.Match[str]") -> Tuple[int, int]:
    base = int(m.group(2)) * 10 if m.group(2) else _DECADES[m.group(3)]
    lo, hi = (13, 19) if base == 10 else (base, base + 9)
    if m.group(1) == "early":
        hi = lo + 3
    elif m.group(1) == "late":
        lo = hi - 3
    elif m.group(1) == "mid":
        lo, hi = lo + 3, hi - 3
    return lo, hi


_AGED = re.compile(r"\baged\s+(\d{1,3})(?:\s*-\s*(\d{1,3}))?\b")
_YEARS_OLD = re.compile(r"\b(\d{1,3})\s+years?\s+old\b")
_PRENOMINAL = re.compile(r"\b(\d{1,3})\s*(?:-\s*years?\s*-\s*old|-?\s*y\.?\s?o\b\.?|yo\b|-year\b)")
_IN_THE = re.compile(r"\bin\s+(?:her|his|their)\s+(early|mid|late)?[\s-]*(?:(\d)0s|(teens|twenties|thirties|forties|"
                     r"fifties|sixties|seventies|eighties|nineties))\b")


def ages_before(text: str, lex: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """An age range the words before a noun state: "16 y.o.", "a 30-year-old", "elderly"."""
    t = _norm(text)
    m = _PRENOMINAL.search(t) or _YEARS_OLD.search(t)
    if m:
        return int(m.group(1)), int(m.group(1))
    m = re.search(r"\b(\d)0-something\b", t)
    if m:
        return int(m.group(1)) * 10, int(m.group(1)) * 10 + 9
    for phrase, rng in sorted((lex.get("age_words") or {}).items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![a-z-]){re.escape(_norm(phrase))}(?![a-z-])", t):
            return int(rng[0]), int(rng[1])
    return None


def ages_after(text: str) -> Optional[Tuple[int, int]]:
    """An age range the words after a noun state: "aged 25–29", "30 years old", "in her 40s"."""
    t = _norm(text)
    m = _AGED.search(t)
    if m:
        return int(m.group(1)), int(m.group(2) or m.group(1))
    m = _YEARS_OLD.search(t)
    if m:
        return int(m.group(1)), int(m.group(1))
    m = _IN_THE.search(t)
    return _decade(m) if m else None


def _ethnicities_in(text: str, lex: Dict[str, Any]) -> Mixture:
    leaf = vocabulary().get("person.ethnicity")
    if leaf is None:
        return ()
    t = _norm(text)
    values = {_norm(v.text): v.text for v in leaf.values}
    found: List[str] = []
    for key in sorted(values, key=len, reverse=True):
        if re.search(rf"(?<![a-zāē-]){re.escape(key)}(?![a-z])", t):
            found.append(values[key])
            t = re.sub(rf"(?<![a-zāē-]){re.escape(key)}(?![a-z])", " ", t)
    if not found:
        for alias, members in sorted((lex.get("ethnicity_aliases") or {}).items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"(?<![a-z-]){re.escape(_norm(alias))}(?![a-z])", t):
                found = [values[_norm(m)] for m in members if _norm(m) in values]
                break
    if not found:
        return ()
    p = round(1.0 / len(found), 6)
    return tuple(sorted((v, p) for v in dict.fromkeys(found)))


def _stated_targets(text: str) -> Tuple[Tuple[str, str], ...]:
    """Target values a phrase states by the class's own frame: "gray hair", "blue eyes"."""
    out = []
    t = _norm(text).replace("grey", "gray")
    for cls, word in (("person.hair_color", "hair"), ("person.eye_color", "eyes"), ("person.skin_tone", "skin")):
        leaf = vocabulary().get(cls)
        if leaf is None:
            continue
        for v in sorted(leaf.values, key=lambda v: -len(v.text)):
            if re.search(rf"(?<![a-z-]){re.escape(_norm(v.text))}\s+(?:[a-z-]+\s+)?{word}\b", t):
                out.append((cls, v.text))
                break
    return tuple(out)


_BOUNDARY = re.compile(r"[.;!?\n]")
# Words that end the phrase describing a noun ("a Japanese garden with a woman": not Japanese).
_BREAK = re.compile(r"\b(?:with|in|at|on|near|by|of|from|beside|behind|under|over|into|for|to|holding|and|or|&)\b"
                    r"(?:\s+(?:a|an|the|her|his|their|its|some|two|three))?")


def mentions(text: str, extra_nouns: Iterable[str] = ()) -> List[Mention]:
    return list(_mentions(text, tuple(sorted(set(extra_nouns))), tables().version))


@lru_cache(maxsize=512)
def _mentions(text: str, extra: Tuple[str, ...], version: str) -> Tuple[Mention, ...]:
    lex = tables().lexicon
    nouns = _nouns(lex)
    plurals = nouns.get("_plurals") or {}
    words = sorted({*(n for n in nouns if not n.startswith("_")), *plurals, *extra}, key=len, reverse=True)
    if not words:
        return ()
    t = re.sub(r"\by\.\s?o\.?(?=\s|$)", "yo", _norm(text))   # "16 y.o. boy": not a sentence end
    t = re.sub(r"\b(yrs?|mrs?|ms|dr|st)\.", r"\1", t)
    pat = re.compile(r"(?<![a-z-])(" + "|".join(re.escape(w) for w in words) + r")(?![a-z])")
    hits = list(pat.finditer(t))
    out: List[Mention] = []
    for i, m in enumerate(hits):
        prev_end = hits[i - 1].end() if i else 0
        next_start = hits[i + 1].start() if i + 1 < len(hits) else len(t)
        before = t[prev_end:m.start()]
        cut = max([0] + [b.end() for b in _BOUNDARY.finditer(before)] + [b.end() for b in _BREAK.finditer(before)])
        before = " ".join(before[cut:].split()[-6:])
        after = t[m.end():next_start]
        b = _BOUNDARY.search(after)
        after = " ".join((after[: b.start()] if b else after).split()[:12])
        noun = _singular(m.group(1), nouns)
        info = nouns.get(noun) or {}
        if noun != m.group(1):
            # "two women, one aged 70 and one aged 20": only what describes them all, before
            # the noun ("two elderly Japanese women"), is about each of them.
            after = ""
        gender = str(info.get("gender") or "")
        for w in before.split():
            if w in ("female", "feminine", "woman"):
                gender = "feminine"
            elif w in ("male", "masculine"):
                gender = "masculine"
        facts: Dict[str, Mixture] = {}
        stated = ages_before(before + " " + noun, lex) or ages_after(after)
        noun_ages = info.get("age")
        ages = stated
        if stated and noun_ages:   # "teenage girl": the phrase narrows the noun
            lo, hi = max(stated[0], int(noun_ages[0])), min(stated[1], int(noun_ages[1]))
            ages = (lo, hi) if lo <= hi else stated
        ages = ages or (tuple(noun_ages) if noun_ages else None)
        span: Optional[Tuple[int, int]] = (int(ages[0]), int(ages[1])) if ages else None
        if ages:
            mix = age_mixture(int(ages[0]), int(ages[1]))
            if mix:
                facts["person.age_band"] = mix
        elif info.get("adult"):
            span = (18, 200)       # "a woman": never a child's age band, but no lean among adults
        eth = _ethnicities_in(before, lex)
        if not eth:
            d = re.search(r"\bof\s+([a-z\s-]+?)\s+(?:descent|heritage|origin|ancestry|background)\b", after)
            eth = _ethnicities_in(d.group(1), lex) if d else ()
        if eth:
            facts["person.ethnicity"] = eth
        if gender:
            facts[PRESENTATION] = ((gender, 1.0),)
        out.append(Mention(noun, gender, tuple(sorted(facts.items())), _stated_targets(after), span))
    return tuple(out)


def _compatible(a: Who, b: Who) -> bool:
    if a.noun and b.noun:
        return a.noun == b.noun
    if a.gender and b.gender:
        return a.gender == b.gender
    return True


def _unanimous(values: List[Any]) -> Any:
    distinct = list(dict.fromkeys(values))
    return distinct[0] if len(distinct) == 1 else None


# --------------------------------------------------------------------------- weighting

@dataclass(frozen=True)
class Known:
    """A bound pick: its class, its value once decided or pinned (else None), and the
    person it is about."""
    cls: str
    value: Optional[str]
    prefix: str
    who: Who


def prefix_of(cid: str) -> str:
    """`girl[2].hair` → `girl[2]`; `hair_color` → ``."""
    return cid.rsplit(".", 1)[0] if "." in cid else ""


def same_person(prefix: str, who: Who, k: Known) -> bool:
    return prefix == k.prefix and _compatible(who, k.who)


class Conditioner:
    """Per-draw: what is known about each person, and the weights it implies.

    Every draw that used typicality records, per bound pick, its rank (a given like age, or
    a target like hair), the sequence of conditioning keys it was proposed under, and the
    multipliers for each key. `recorded` replays that record as-is, so a later release of
    the tables or of the words read from prompts draws a revision the same. `off` draws
    without typicality (a revision from before it existed)."""

    def __init__(self, tabs: Optional[Tables] = None, recorded: Optional[Dict[str, Any]] = None, off: bool = False):
        self.tabs = tabs if tabs is not None else tables()
        if off:
            self.tabs = Tables([], self.tabs.lexicon, "")
        self.replay: Optional[Dict[str, Any]] = recorded if isinstance(recorded, dict) else None
        self.text = ""
        self.picks: Dict[str, Dict[str, Any]] = {}    # cid -> {"rank", "seq": [[key, n], ...], "weights": {key: {...}}}
        self._cursor: Dict[str, Tuple[int, int]] = {}

    @property
    def applied(self) -> bool:
        return bool(self.picks)

    def record(self) -> Dict[str, Any]:
        if self.replay is not None:
            return self.replay
        return {"version": self.tabs.version, "picks": {cid: self.picks[cid] for cid in sorted(self.picks)}}

    def active(self, cls: str, cid: str = "") -> bool:
        if self.replay is not None:
            return cid in (self.replay.get("picks") or {})
        return bool(cls) and self.tabs.involves(cls)

    def rank(self, cid: str, cls: str) -> int:
        """Decide order within a phase: 1 for givens (age, descent), 2 for the rest."""
        if self.replay is not None:
            return int(((self.replay.get("picks") or {}).get(cid) or {}).get("rank") or 2)
        return 1 if cls in self.tabs.givens else 2

    def key(self, cid: str, cls: str, about: str, label: str, people: Dict[str, "Known"]) -> str:
        """The conditioning this pick is proposed under now, as a short key (logged in order)."""
        if self.replay is not None:
            seq = ((self.replay.get("picks") or {}).get(cid) or {}).get("seq") or []
            i, n = self._cursor.get(cid, (0, 0))
            if not seq:
                return ""
            if i >= len(seq):
                return str(seq[-1][0])
            k = str(seq[i][0])
            self._cursor[cid] = (i, n + 1) if n + 1 < int(seq[i][1]) else (i + 1, 0)
            return k
        sig = self.signature(cid, cls, about, label, people)
        k = sig_key(sig) if sig else ""
        p = self.picks.setdefault(cid, {"rank": self.rank(cid, cls), "seq": [], "weights": {}})
        if p["seq"] and p["seq"][-1][0] == k:
            p["seq"][-1][1] += 1
        else:
            p["seq"].append([k, 1])
        if k and k not in p["weights"]:
            p["weights"][k] = {v: round(m, 6) for v, m in sorted(self.weights(cls, sig, self._values(cls)).items())
                               if m != 1.0}
        return k

    def multipliers(self, cid: str, key: str) -> Dict[str, float]:
        src = self.replay.get("picks") if self.replay is not None else self.picks
        return dict((((src or {}).get(cid) or {}).get("weights") or {}).get(key) or {})

    def _values(self, cls: str) -> List[str]:
        """The class's values: its leaf's, and every value its tables name (a value the
        vocabulary dropped still weighs what it did, for a revision that recorded it)."""
        leaf = vocabulary().get(cls)
        vals = [v.text for v in leaf.values] if leaf else []
        for t in self.tabs.for_target(cls):
            for row in t.rows.values():
                vals.extend(row)
        for t in self.tabs.for_given(cls):
            vals.extend(t.rows)
        return list(dict.fromkeys(vals))

    def signature(self, cid: str, cls: str, about: str, label: str, people: Dict[str, Known]) -> Tuple[Any, ...]:
        """What this pick is conditioned on, as a hashable key:
        - (given class, mixture): what's known of this person's age, descent, presentation;
        - ("reverse", target class): a target value known when a given is drawn (Bayes);
        - ("pending", target class): a target still to draw for this person, so a given value
          it can't follow (a child, with a beard still to draw) is avoided;
        - ("self", cls): values the text allows this pick ("a man aged [Age]": no child bands).
        `people` holds every bound pick seen; settled ones have a value."""
        lex = self.tabs.lexicon
        who = who_of(about, label, cid, lex)
        prefix = prefix_of(cid)
        mine = {k: v for k, v in people.items() if k != cid and same_person(prefix, who, v)}
        known = {k: v for k, v in mine.items() if v.value is not None}
        found = mentions(self.text, [who.noun] if who.noun else [])
        if who.noun and not any(m.noun == who.noun for m in found):
            who_text = Who("", who.gender)   # "the rider's hair" in "a child on a bike": match by presentation only
        else:
            who_text = who
        ms = [m for m in found if _compatible(who_text, Who(m.noun, m.gender))]
        out: Dict[Any, Any] = {}
        for g in sorted({t.given for t in self.tabs.for_target(cls)}):
            exact = _unanimous([v.value for v in known.values() if v.cls == g])
            if exact is not None:
                out[g] = ((exact, 1.0),)
                continue
            if g == PRESENTATION and who.gender:
                out[g] = ((who.gender, 1.0),)
                continue
            mix = _unanimous([dict(m.facts).get(g) for m in ms if dict(m.facts).get(g)])
            if mix:
                out[g] = mix
        for t in self.tabs.for_given(cls):
            exact = _unanimous([v.value for v in known.values() if v.cls == t.target])
            if exact is None:
                exact = _unanimous([dict(m.stated).get(t.target) for m in ms if dict(m.stated).get(t.target)])
            if exact is not None:
                out[("reverse", t.target)] = exact
            elif any(v.cls == t.target and v.value is None for v in mine.values()):
                out[("pending", t.target)] = True
        if cls == "person.age_band":
            span = _unanimous([m.ages for m in ms if m.ages])
            if span:
                out[("self", cls)] = bands_in(*span)
        elif cls == "person.ethnicity":
            mix = _unanimous([dict(m.facts).get(cls) for m in ms if dict(m.facts).get(cls)])
            if mix:
                out[("self", cls)] = tuple(v for v, _ in mix)
        return tuple(sorted(out.items(), key=lambda kv: str(kv[0])))

    def weights(self, cls: str, sig: Tuple[Any, ...], values: Sequence[str]) -> Dict[str, float]:
        mult = {v: 1.0 for v in values}
        cond = dict(sig)
        for t in self.tabs.for_target(cls):
            mix = cond.get(t.given)
            if mix:
                for v in values:
                    mult[v] *= t.factor(mix, v)
        for t in self.tabs.for_given(cls):
            tv = cond.get(("reverse", t.target))
            pending = cond.get(("pending", t.target))
            for v in values:
                row = t.rows.get(v)
                if row is None:
                    continue
                z = _norm_const(t, v)
                if tv is not None and tv in row:
                    mult[v] *= row[tv] / z if z > 0 else 0.0
                elif pending:
                    mult[v] *= min(1.0, z / PENDING_FLOOR)
        allowed = cond.get(("self", cls))
        if allowed:
            for v in values:
                if v not in allowed:
                    mult[v] = 0.0
        return mult

    def reweight(self, cid: str, key: str, items: List[Tuple[str, float]],
                 protected: Iterable[str] = ()) -> List[Tuple[str, float]]:
        """Items with the key's multipliers applied. Values the tables rule out drop, except
        protected ones; if nothing would be left, the items are returned unchanged."""
        if not key or not items:
            return items
        mult = self.multipliers(cid, key)
        if not mult:
            return items
        keep = set(protected)
        out = []
        for o, w in items:
            nw = w * mult.get(o, 1.0)
            if nw <= 0:
                if o not in keep:
                    continue
                nw = KEEP
            out.append((o, nw))
        return out if any(w > KEEP for _, w in out) else items


def sig_key(sig: Tuple[Any, ...]) -> str:
    return hashlib.sha256(json.dumps(sig, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def _norm_const(t: Table, g: str) -> float:
    """Average multiplier a given value applies to its target class under the tier prior:
    P(target | given) = w · m / Z, so drawing the given from a known target is Bayes."""
    if g not in t._z:
        leaf = vocabulary().get(t.target)
        row = t.rows.get(g) or {}
        vals = leaf.eligible() if leaf else []
        tot = sum(v.weight for v in vals)
        t._z[g] = sum(v.weight * row.get(v.text, 1.0) for v in vals) / tot if tot else 1.0
    return t._z[g]


__all__ = ["LEVEL_WEIGHTS", "Conditioner", "Known", "Table", "Tables", "Who", "age_mixture", "load", "mentions",
           "prefix_of", "tables", "who_of"]

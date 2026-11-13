"""Filling a prompt's slots: one image's text, drawn straight from the parse and the readings.

    dorm room with a <young man>, lit by <light>

A slot's reading (reader.py) says what it is; `picks_of` turns that into plain data: the
picks it draws (a person's age, descent, hair…, their outfit and its colors; a camera's
shot and lens; one pick for anything else) and its form, how its text is put together.
`fill` draws one image: for each segment in order its text is copied, and a slot is filled
from its picks through the options service (options.GeneratedOptions: vocabulary lists,
weights and tiers, narrowed subsets, zones, written options, the user's own), with context
facets (a person's descent before their hair color), pins, kept values, the minors policy,
a look's colors, the person join and leave-out with its lead. Nothing is generated as code
and nothing executes any.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Set, Tuple

from prompt_programs.vocab import (
    AGE_LIST, fill as fill_template, is_template, minor_ages, tags_match, template_matches, vocabulary,
)

FILL_VERSION = "fill-1"
CONTEXT_VERSION = "ctx-2"
RANK_DECAY = 0.86
SOURCES = ("text", "list", "added")
COLORS = ".colors"
# The Colors pick's about, as the pick judge reads it ("Colors (the colors of her outfit)").
COLORS_ABOUT = "the colors of {}"
KINDS = ("person", "animal", "camera", "light", "list", "free")
ANIMAL = ("species", "breed", "life_stage")
ANIMAL_LISTS = {"species": "animal.species", "life_stage": "animal.life_stage"}
CAMERA = ("shot_size", "lens", "angle", "film_look")
MAX_PROMPT_CHARS = 100_000

# detail name -> (list, label, what it is of the person, a seed, phase)
DETAILS: Dict[str, Tuple[str, str, str, str, int]] = {
    "build": ("person.build", "Build", "build", "slender", 2),
    "age": ("person.age_band", "Age", "age", "32-year-old", 1),
    "descent": ("person.ethnicity", "Ethnicity", "descent", "Korean", 1),
    "skin": ("person.skin_tone", "Skin", "skin tone", "warm beige", 2),
    "hair": ("person.hair_length", "Hair length", "hair length", "shoulder-length", 2),
    "hair_texture": ("person.hair_texture", "Hair texture", "hair texture", "wavy", 2),
    "hair_color": ("person.hair_color", "Hair color", "hair color", "dark brown", 2),
    "hairstyle": ("person.hairstyle", "Hairstyle", "hairstyle", "a low ponytail", 2),
    "eyes": ("person.eye_color", "Eyes", "eye color", "hazel", 2),
    "facial_hair": ("person.facial_hair", "Facial hair", "facial hair", "light stubble", 2),
    "face": ("person.face", "Face", "face", "a long, narrow nose, a light scatter of freckles across the nose", 2),
}


# Details a person has that start left out unless the reading asks for them (the chooser turns them on).
STARTS_OFF = ("face", "hairstyle")
# Details every person varies, whatever the reading lists (facial hair only for a masculine person).
CORE = ("age", "descent", "build", "hair", "hair_texture", "hair_color", "facial_hair")


class ProgramError(Exception):
    """A draw that can't be made (kept under its old name: callers catch it as the run's error)."""

    code = "program_failed"


class ReadingError(ValueError):
    """A slot reading the picks can't be made from (the reader checks for these before it caches)."""


# --------------------------------------------------------------------------- whose detail a pick is

_SUBJECT_ID = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*?)(?:_?(?P<num>\d+))?(?:\[(?P<index>\d+)\])?\.(?P<attr>[A-Za-z_].*)$")


def subject_of(cid: str) -> Optional[Tuple[str, Optional[int], str]]:
    """(subject, number, detail) a pick id names: `woman.hair` is ("woman", None, "hair"); a
    plain id (`light`, `outfit.colors`) is no subject's: None."""
    cid = str(cid)
    if cid.endswith(COLORS) and cid.count(".") == 1:
        return None
    m = _SUBJECT_ID.match(cid)
    if not m:
        return None
    name, num, index = m.group("name"), m.group("num"), m.group("index")
    if num and index:
        name, num = f"{name}{num}", None
    n = index or num
    return name, int(n) if n else None, m.group("attr")


def person_of(cid: str) -> str:
    """Whose detail a pick is: `young_man.age` and `young_man.outfit.colors` are young_man's; a
    plain id ("light", "list1") names no subject: "", every subject's (owns)."""
    cid = str(cid)
    s = subject_of(cid)
    if s is None:
        return ""
    tail = "." + s[2]
    return cid[: -len(tail)] if cid.endswith(tail) else cid.split(".", 1)[0]


def owns(owner: str, person: str) -> bool:
    """Whether what `owner`'s pick draws holds for `person`: their own, or either names no subject."""
    return owner == person or owner == "" or person == ""


# --------------------------------------------------------------------------- records

@dataclass
class Draw:
    id: str
    value: Any
    kind: str = "pick"
    label: str = ""
    source: str = "text"           # text | list | added
    line: Optional[int] = None
    hidden: bool = False
    pinned: bool = False
    options: List[str] = field(default_factory=list)   # what was available this time
    follows: Optional[str] = None  # an outfit's Colors follow the outfit
    phase: Optional[int] = None
    about: str = ""
    cls: str = ""                  # the vocabulary list it is bound to (see vocab.py)
    where: Any = ""                # the words or {facet: value} narrowing that list
    said: str = ""                 # the user's own words it stands for: drawn unless they choose others
    shared: bool = False
    own: bool = False              # the user's own option (added or kept for its list): never rerolled
    template: str = ""             # a look with colors: the list's template it was filled from

    def to_dict(self) -> Dict[str, Any]:
        d = {"id": self.id, "value": self.value, "kind": self.kind, "label": self.label, "source": self.source}
        for k in ("line", "phase"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        for k in ("hidden", "pinned", "shared"):
            if getattr(self, k):
                d[k] = True
        for k in ("follows", "about", "cls", "where", "said", "template"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        return d


@dataclass
class RunResult:
    prompt: str
    draws: List[Draw]
    seed: int

    def to_dict(self) -> Dict[str, Any]:
        return {"prompt": self.prompt, "draw_seed": self.seed, "draws": [d.to_dict() for d in self.draws]}


@dataclass
class DrawResult(RunResult):
    revision: Dict[str, Any] = field(default_factory=dict)
    more_coming: List[str] = field(default_factory=list)   # choices whose pools are still filling
    # The parts in order, each with the id of the pick whose value it is (None for the user's text).
    value_parts: List[Tuple[str, Optional[str]]] = field(default_factory=list)

    @property
    def spans(self) -> List[Tuple[int, int, str]]:
        """(start, end, choice id) of every drawn value in `prompt` as it stands now (after
        [exact text] is put back too), in order. The user's text is never a span."""
        return value_spans(self.prompt, self.value_parts)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["draw_revision"] = self.revision
        if self.more_coming:
            d["more_coming"] = list(self.more_coming)
        return d


class DrawAborted(ProgramError):
    """A pick with nothing left to draw: nothing is generated; the message is shown at the choice."""

    def __init__(self, choice_id: str, label: str, reason: str, value: Optional[str] = None):
        self.choice_id, self.label, self.reason, self.value = choice_id, label, reason, value
        msg = (f'The pinned {label} "{value}" doesn\'t fit the other choices.' if reason == "pin"
               else f"Nothing left to draw for {label}.")
        super().__init__(msg)

    def to_dict(self) -> Dict[str, Any]:
        d = {"code": "nothing_to_draw", "message": str(self), "choice_id": self.choice_id, "reason": self.reason}
        if self.value is not None:
            d["value"] = self.value
        return d


# --------------------------------------------------------------------------- the options service's types

@dataclass
class PickSpec:
    """What a pick asks the options service for."""
    id: str
    label: str
    about: str
    phase: int
    source: str                  # text | list | added
    kind: str = "pick"
    seeds: List[str] = field(default_factory=list)
    literal: List[str] = field(default_factory=list)   # a user list's items
    cls: str = ""                # the vocabulary list it is bound to; "" for none
    restrict: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()   # a palette pick: its template's allowed facets
    # The ages under 18 its person may be (vocab.minor_ages): their pools leave adult-only values
    # out and written options are written for that age. Empty for an adult and the age pick itself.
    minor: Tuple[str, ...] = ()
    said: str = ""               # the user's own words it stands for: first in its pool
    context: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()   # (facet, families) drawn before it in its scope
    zones: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()     # a free slot's zones and their seeds
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
    own: frozenset = frozenset()   # the user's own options in it
    # Values held at weight 0 (opt-in, or a narrowed list's rest) -> the weight a tick draws them at.
    held: Dict[str, float] = field(default_factory=dict)


def pool_key(spec: PickSpec, context: Dict[str, Any]) -> str:
    head = f"{spec.id}: {spec.about}" if spec.about else spec.id
    if spec.zone:
        head += f" | {spec.zone}"
    return head + "".join(f" | {k}={v}" for k, v in context.items())


class OptionsService(Protocol):
    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool: ...

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None: ...


class LiteralOptions:
    """Pools from the picks themselves: seeds, a user list's items, then the user's edits. A
    bound pick draws its list (opt-in values at weight 0)."""

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
        uniform = spec.source == "list"
        weights = [1.0] * len(items) if uniform else [RANK_DECAY ** i for i in range(len(items))]
        weights = [0.0 if o in standby else w for o, w in zip(items, weights)]
        if leaf is not None and spec.context:
            weights = [w for _, w in leaf.weigh(list(zip(items, weights)), spec.context)]
        return Pool(pool_key(spec, context) + context_suffix(spec), items, weights, False)

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None:
        self.requests.append((pool_key(spec, context), priority))


# --------------------------------------------------------------------------- text

class Opt(tuple):
    """Parts that stand or go together: the whole group goes when a value in it is off, so
    the words leading to it go with it (", lit by" with the light)."""


class Series(tuple):
    """Opts said as a list: those kept joined by commas, the last by "and" ("warm beige skin,
    wavy black hair and hazel eyes"). Goes when none is kept."""


@dataclass(frozen=True)
class Val:
    """A drawn value in the text, with the pick it is the value of (None: off)."""
    cid: str
    value: Optional[str]


Part = Any   # str | Val | Opt | list of parts


def _clean(t: str) -> str:
    return t.strip() + ("\n" if t.rstrip(" \t").endswith("\n") else "")


def _series_parts(s: Series) -> Optional[List[Tuple[str, Optional[str]]]]:
    """A Series' text: the Opts kept, joined by commas and a last "and"; None when none is."""
    kept = [got for got in (_opt_parts(o) for o in s) if got]
    if not kept:
        return None
    out: List[Tuple[str, Optional[str]]] = []
    for i, got in enumerate(kept):
        if i:
            out.append(("and" if i == len(kept) - 1 else ",", None))
        out += got
    return out


def _opt_parts(o: Opt) -> Optional[List[Tuple[str, Optional[str]]]]:
    """An Opt's text, or None when it goes: a value in it is off, or every Opt (or Series)
    inside it went ("with" and the hair group go when both hair picks are off, stay when one
    is on). A "," leading an inner Opt separates it from one kept before it, so it goes when
    none was."""
    if any(p is None or (isinstance(p, Val) and p.value is None) for p in o):
        return None
    out: List[Tuple[str, Optional[str]]] = []
    inner = kept = 0
    for p in o:
        if isinstance(p, (Opt, Series)):
            inner += 1
            got = _opt_parts(p) if isinstance(p, Opt) else _series_parts(p)
            if got is None:
                continue
            if not kept and got and got[0][0] == ",":
                got = got[1:]
            kept += 1
        else:
            got = flatten([p])
        out += got
    return None if inner and not kept else out


def flatten(parts: Sequence[Part]) -> List[Tuple[str, Optional[str]]]:
    """The parts as (text, the pick it is the value of): lists in order, off values skipped,
    an Opt whole or not at all. A part ending a line keeps its newline."""
    out: List[Tuple[str, Optional[str]]] = []
    for p in parts:
        if p is None:
            continue
        if isinstance(p, Opt):
            out += _opt_parts(p) or []
        elif isinstance(p, Series):
            out += _series_parts(p) or []
        elif isinstance(p, list):
            out += flatten(p)
        elif isinstance(p, Val):
            if p.value is not None and _clean(str(p.value)):
                out.append((_clean(str(p.value)), p.cid))
        else:
            s = _clean(str(p))
            if s:
                out.append((s, None))
    if sum(len(t) for t, _ in out) > MAX_PROMPT_CHARS:
        raise ProgramError(f"The prompt is too long (over {MAX_PROMPT_CHARS:,} characters).")
    return out


_ARTICLE = re.compile(r"\b(a|an|the)\s+(?=(?:a|an|the)\s)", re.I)
# An article and the word after it. A capital "A" mid-sentence is a letter, not an article
# ("Plan A", "vitamin A"): only a lowercase one, or one starting the text or a sentence, is corrected.
_WORD = r"(?:[A-Za-z][\w'-]*|\d[\d,]*[\w'-]*)"   # commas only inside a number ("18,000-seat")
_A_AN = re.compile(rf"(?:(?<=^)|(?<=[.!?]\s))(A|An)\s+({_WORD})|\b(a|an)\s+({_WORD})")
# Words whose sound doesn't follow their first letter.
_AN_WORDS = {"hour", "hours", "hourly", "honest", "honestly", "honor", "honour", "honorable", "honourable", "heir", "heiress"}
# Vowel-initial words said with a consonant sound ("a unicorn", "a European", "a one-off").
_A_WORDS = ("unic", "unif", "unio", "uniq", "unis", "unit", "univ", "use", "usu", "uti", "uto", "uga", "ukr", "uru",
            "uro", "ura", "eu", "one", "once", "ubiq")


def _number_wants_an(digits: str) -> bool:
    """A number said with a vowel sound: eight…, eleven, eighteen ("an 8-year-old", "an 18,000-seat arena")."""
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
    if len(word) == 1 and not word.isdigit():
        return m.group(0)
    new = "an" if _wants_an(word) else "a"
    return f"{new.capitalize() if art[0].isupper() else new} {word}"


def fix_articles(text: str) -> str:
    """Each "a"/"an" in the text as the word after it is said ("a espresso coat" → "an espresso coat")."""
    return _A_AN.sub(_fix_article, text)


_LAST_WORD = re.compile(r"([^\W\d_]+)\s*$")
_FIRST_WORD = re.compile(r"^\s*([^\W\d_]+)")


def _seams(parts: List[str]) -> List[str]:
    """A joining word written before a value that brings its own ("in" then "in a sunlit
    garden"): keep the value's. Only at the seam between two parts, and only when the part
    before is a few words of joining text."""
    out: List[str] = []
    for part in parts:
        part = str(part)
        if out and not out[-1].endswith("\n"):
            last, first = _LAST_WORD.search(out[-1]), _FIRST_WORD.match(part)
            if (last and first and last.group(1).lower() == first.group(1).lower() and len(out[-1].split()) <= 3
                    and last.group(1).lower() not in ("a", "an", "the")):
                out[-1] = out[-1][: last.start()]
        out.append(part)
    return out


def tidy_text(parts: List[str]) -> str:
    """The parts as the prompt: each line tidied, line breaks kept."""
    lines = " ".join(_seams(parts)).split("\n")
    return "\n".join(_tidy_line(line) for line in lines).strip()


def _tidy_line(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = _ARTICLE.sub("", s)   # "a" written before a value that brings its own: keep the value's
    s = _A_AN.sub(_fix_article, s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"([,;])\1+", r"\1", s)
    s = re.sub(r",\s*\.", ".", s)
    s = re.sub(r"\.\s*\.", ".", s)
    s = re.sub(r"\s*[,;:]+$", "", s)   # a joiner left hanging at the line's end (a slot left out after it)
    s = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    return s.strip()


def value_spans(prompt: str, parts: Sequence[Tuple[str, Optional[str]]]) -> List[Tuple[int, int, str]]:
    """Where each value part stands in the prompt made from `parts`: found in order, case
    aside, as whole words, each after the one before. Tidying may drop or change the user's
    short joiners, so one of those moves the search only when found right there."""
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


# --------------------------------------------------------------------------- a slot's picks

def _strings(v: Any, what: str) -> List[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ReadingError(f"{what} must be a list of strings")
    return [x for x in v if x.strip()]


def _pick(cid: str, *, label: str, about: str = "", phase: int = 1, source: str = "added", cls: str = "",
          seed: Optional[List[str]] = None, where: Any = None, zones: Optional[Dict[str, List[str]]] = None,
          slot: Optional[str] = None, line: Optional[int] = None, items: Optional[List[str]] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {"id": cid, "kind": "pick", "label": label, "about": about, "phase": phase, "source": source}
    for k, v in (("cls", cls), ("seed", seed), ("where", where), ("zones", zones), ("slot", slot), ("line", line),
                 ("items", items)):
        if v:
            p[k] = v
    return p


def picks_of(cid: str, words: str, reading: Dict[str, Any], *, close: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """A slot's picks and form from its reading (as reader.check_slot gives it), or ReadingError.
    `close`: text that ends a person's description when any of it is drawn ("," before "reading
    on a porch")."""
    vocab = vocabulary()
    kind = reading.get("kind")
    if kind not in KINDS:
        raise ReadingError(f"kind {kind!r} is not one of {KINDS}")
    label = str(reading.get("label") or words)
    got = reading.get(kind) if isinstance(reading.get(kind), dict) else {}

    def listed(lid: Any) -> str:
        if not isinstance(lid, str) or vocab.get(lid) is None:
            raise ReadingError(f"{label}: {lid!r} is not a list")
        return lid

    if kind == "person":
        noun = str(got.get("noun") or "person")
        presentation = got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else ""
        # The fixed things about a person always vary (design: age within what is stated, descent,
        # build, hair); the reading adds what this picture shows besides (eyes, skin, face).
        show = [*CORE, *(d for d in got.get("vary") or [] if d in DETAILS)]
        # Face detail is part of every person but starts left out: it is drawn only when the
        # reading says the prompt or a note asks for it, or the user turns it on in the chooser.
        quiet = {k for k in STARTS_OFF if k not in show and vocab.get(DETAILS[k][0]) is not None}
        keys = [k for k in DETAILS if (k in show or k in quiet) and (k != "facial_hair" or presentation == "masculine")]
        picks = []
        for k in keys:
            lid, dlabel, what, seed, phase = DETAILS[k]
            where: Any = None
            if k == "age" and noun != "person":
                # What they are speaks to their age ("boy", "grandmother"): the age is read in the
                # slot's own words whole ("young woman"), not the stated word alone.
                where = words
            elif k in ("face", "build") and presentation:
                where = {"presentation": presentation}
            picks.append(_pick(f"{cid}.{k}", label=dlabel, about=f"the {noun}'s {what}", phase=phase, cls=lid,
                               seed=[seed], where=where, slot=cid))
            if k in quiet:
                picks[-1]["starts_off"] = True
            if k == "face":
                picks += face_parts(f"{cid}.{k}", noun, cid)
        outfit = str(got.get("outfit") or "")
        outfit_id = ""
        if outfit:
            outfit_id = f"{cid}.outfit"
            about = f"{label}'s outfit"
            if outfit == "written":
                picks.append(_pick(outfit_id, label="Outfit", about=about, phase=2,
                                   seed=_strings(got.get("outfit_examples") or [], "outfit_examples") or None, slot=cid))
            else:
                leaf = vocab.get(listed(outfit))
                # How the person presents narrows their outfit list, as it does their face and build.
                where = ({"presentation": presentation}
                         if presentation and presentation in leaf.local_facets.get("presentation", ()) else None)
                picks.append(_pick(outfit_id, label="Outfit", about=about, phase=2, cls=outfit, where=where, slot=cid))
                if leaf.slots and vocab.get(leaf.slots) is not None:
                    picks.append(_colors(outfit_id, picks[-1]))
        stated = {d: str(w) for d, w in (got.get("stated") or {}).items() if d in DETAILS and str(w).strip()}
        form = {"kind": "person", "noun": noun, "words": words, "keys": [f"{cid}.{k}" for k in keys],
                "outfit": outfit_id, "close": close}
        return picks, {"form": form, "stated": stated,
                       "slot_words": {f"{cid}.{d}": w for d, w in stated.items() if d in keys}}
    if kind == "camera":
        vary = [d for d in got.get("vary") or [] if d in CAMERA and vocab.get(f"camera.{d}") is not None]
        if not vary:
            raise ReadingError(f"{label}: a camera varies none of {CAMERA}")
        picks = [_pick(f"{cid}.{d}", label=vocab.get(f"camera.{d}").label,
                       about=f"the camera's {vocab.get(f'camera.{d}').label.lower()}", cls=f"camera.{d}", slot=cid)
                 for d in vary]
        return picks, {"form": {"kind": "camera", "keys": [p["id"] for p in picks]}}
    if kind == "animal":
        noun = str(got.get("noun") or words)
        vary = [d for d in ANIMAL if d in (got.get("vary") or [])]
        breed = str(got.get("breed") or "")
        if "breed" in vary:
            listed(breed)
        lists = {**ANIMAL_LISTS, **({"breed": breed} if breed else {})}
        vary = [d for d in vary if d in lists]
        stated = {d: str(w) for d, w in (got.get("stated") or {}).items() if d in vary and str(w).strip()}
        # What each part is of the animal; its life stage is its own part, so a kind is never "puppy".
        abouts = {"species": f"what kind of animal the {noun} is (its age is chosen apart)",
                  "breed": f"the {noun}'s breed (its age is chosen apart)", "life_stage": f"the {noun}'s life stage"}
        # The kind of animal the reader says the words name ("pet": the species list's pets) keeps
        # the species to that tag; the words still narrow within it (narrow.py).
        sort = str(got.get("type") or "")
        sort = sort if sort in vocab.get(lists["species"]).local_facets.get("kind", ()) else ""
        picks = [_pick(f"{cid}.{d}", label=vocab.get(lists[d]).label if d != "species" else "Kind",
                       about=abouts[d], phase=1 if d != "life_stage" else 2, cls=lists[d], slot=cid,
                       where={"kind": sort} if d == "species" and sort else None) for d in vary]
        # The slot's words narrow what kind of animal it is ("pet" keeps pets), unless they say more
        # of it; a life stage they state ("kitten") comes as the reading's stated words.
        said = {f"{cid}.{d}": w for d, w in stated.items()}
        if "species" in vary:
            said.setdefault(f"{cid}.species", words)
        form = {"kind": "animal", "noun": noun, "words": words, "keys": [p["id"] for p in picks]}
        stage = vocab.get(lists["life_stage"])
        if "life_stage" in vary and "life_stage" not in stated and stage is not None and stage.plain:
            # The stage that goes without saying (adult) adds no word unless the user asks for it.
            form["plain"] = {f"{cid}.life_stage": stage.plain}
        if breed and "breed" in vary and str(vocab.get(breed).pos).startswith("adjective"):
            # A list of words that go before the animal (a coat: "a ___ cat") keeps the animal's word after it.
            form["before_noun"] = True
        return picks, {"form": form, "stated": stated, "slot_words": said}
    if kind == "light":
        # One choice of named looks (softbox, golden hour light): a lighting list, or written options.
        lid = str(got.get("list") or "")
        if lid:
            p = _pick(cid, label=label, about=words, cls=listed(lid), seed=_strings(got.get("examples") or [], "examples") or None,
                      slot=cid)
        else:
            p = _pick(cid, label=label, about=words, seed=_strings(got.get("examples") or [], "examples"), slot=cid)
        return [p], {"form": {"kind": "one", "id": cid}, "slot_words": {cid: words}}
    if kind == "list":
        lid = listed(got.get("list"))
        # The slot's words narrow its list, said of what the reader says it is in this image.
        leaf = vocab.get(lid)
        # How the person it is about presents narrows a list that has that facet (an outfit, a face).
        shown = got.get("presentation") if got.get("presentation") in leaf.local_facets.get("presentation", ()) else ""
        p = _pick(cid, label=label, about=str(got.get("about") or "").strip() or words, cls=lid, slot=cid,
                  where={"presentation": shown} if shown else None)
        picks = [p]
        if leaf.slots and vocab.get(leaf.slots) is not None:
            picks.append(_colors(cid, p))
        return picks, {"form": {"kind": "one", "id": cid}, "slot_words": {cid: words}}
    kinds = _strings(got.get("kinds") or [], "kinds")
    instead = _strings(got.get("instead") or [], "instead")
    # Things instead are a zone only when the reader found some: a slot can have its kinds alone.
    zones = {"kinds": kinds, **({"instead": instead} if instead else {})}
    p = _pick(cid, label=label, about=str(got.get("about") or words), phase=2, seed=kinds, zones=zones, slot=cid)
    return [p], {"form": {"kind": "one", "id": cid}, "slot_words": {cid: words}, "zones": zones}


def face_parts(face: str, noun: str, slot: str) -> List[Dict[str, Any]]:
    """A face's parts (its shape, eyes, brows…), one pick each, bound to the part's own list and
    left out until chosen: Face > part > values. A part chosen "Any" varies, mostly saying nothing
    notable (its list's plain value); a part with values chosen draws from them. A face with parts
    chosen is those parts; a face turned on with none is one subtle piece of any part."""
    vocab = vocabulary()
    leaf = vocab.get(DETAILS["face"][0])
    out = []
    for lid in getattr(leaf, "parts", ()) or ():
        part = vocab.get(lid)
        if part is None:
            continue
        p = _pick(f"{face}.{lid.rsplit('.', 1)[-1]}", label=part.label, about=f"the {noun}'s {part.label.lower()}", phase=2,
                  cls=lid, slot=slot)
        p.update(starts_off=True, part_of=face)
        out.append(p)
    return out


def _colors(of: str, look: Dict[str, Any]) -> Dict[str, Any]:
    leaf = vocabulary().get(look["cls"])
    return {**_pick(of + COLORS, label="Colors", about=COLORS_ABOUT.format(look.get("about") or look["label"]),
                    phase=look["phase"], cls=leaf.slots, slot=look.get("slot")), "follows": of}


def choice_options(p: Dict[str, Any]) -> List[str]:
    """A pick's options as the editor sees them before /pools: its list's values (opt-in ones
    only when asked), the user's list's items, or its seeds."""
    if p.get("items"):
        return list(p["items"])
    leaf = vocabulary().resolve(p.get("cls")) if p.get("cls") else None
    said = [p["said"]] if p.get("said") else []
    if leaf is not None:
        return list(dict.fromkeys([*said, *(v.text for v in leaf.eligible() if not v.opt_in)]))
    return list(dict.fromkeys([*said, *(p.get("seed") or [])]))


# --------------------------------------------------------------------------- the text of a prompt

def text_parts(entry: Dict[str, Any], value: Any) -> List[Part]:
    """The prompt's parts in order: the user's text, comment lines on their own lines, and each
    slot and list as `value(pick id)` gives it (a Val). A slot not read (or read as written)
    is its own words. The lead the reader named goes with its slot when it is left out."""
    slots = {s["n"]: s for s in entry.get("slots") or []}
    lists = {l["n"]: l for l in entry.get("lists") or []}
    parts: List[Part] = []
    pending = ""
    person_at: Optional[int] = None

    def flush(lead: str = "") -> str:
        nonlocal pending
        lead, stem = lead.rstrip(), pending.rstrip()
        if not lead.strip() or not stem.endswith(lead):
            lead, stem = "", pending
        before = stem[:len(stem) - len(lead)]
        if before.strip():
            parts.append(before)
        pending = ""
        return lead

    slot_n = list_n = 0
    for seg in entry.get("segments") or []:
        if seg["kind"] == "text":
            lines = seg["text"].split("\n")
            for piece in lines[:-1]:
                pending += piece
                parts.append(pending + "\n" if pending.strip() else "\n")
                pending = ""
            pending += lines[-1]
            continue
        if seg["kind"] == "comment":
            flush()
            parts.append(seg["text"])
            continue
        if seg["kind"] == "list":
            flush()
            list_n += 1
            parts.append(value(lists[list_n]["id"]))
            continue
        slot_n += 1
        s = slots.get(slot_n) or {}
        form = s.get("form") if s.get("state") == "ready" and not s.get("degraded") else None
        if form is None:
            pending += seg["words"]
            continue
        if form["kind"] == "person":
            flush()
            parts.append(person_parts(form, value))
            continue
        if form["kind"] == "animal":
            flush()
            parts.append(animal_parts(form, value))
            continue
        lead = flush(str(s.get("lead") or ""))
        if form["kind"] == "camera":
            group = [Opt((value(k),)) if i == 0 else Opt((",", value(k))) for i, k in enumerate(form["keys"])]
            parts.append(Opt(([lead] if lead else []) + group))
        else:
            parts.append(Opt(([lead] if lead else []) + [value(form["id"])]))
    flush()
    return parts


def person_parts(form: Dict[str, Any], value: Any) -> List[Part]:
    """A person described: "slender 32-year-old Korean man with warm beige skin, shoulder-length
    wavy dark brown hair and a goatee, wearing a navy coat," Each group goes with its joiners
    when it is off; with every detail off they stand as the user's own words."""
    v = {k.rsplit(".", 1)[-1]: value(k) for k in form["keys"]}
    noun = form["noun"]
    if form.get("words") and v:
        noun = noun if any(x.value is not None for x in v.values()) else form["words"]
    parts: List[Part] = [v[k] for k in ("build", "age", "descent") if k in v] + [noun]
    groups = [g for g in (Opt((v["skin"], "skin")) if "skin" in v else None,
                          Opt(tuple(Opt((v[k],)) for k in ("hair", "hair_texture", "hair_color") if k in v) + ("hair",)
                              + ((Opt(("in", v["hairstyle"])),) if "hairstyle" in v else ()))
                          if any(k in v for k in ("hair", "hair_texture", "hair_color", "hairstyle")) else None,
                          Opt((v["eyes"], "eyes")) if "eyes" in v else None,
                          Opt((v["facial_hair"],)) if "facial_hair" in v else None,
                          Opt((v["face"],)) if "face" in v else None) if g is not None]
    tail: List[Part] = []
    if groups:
        # One "with" and one list: "with warm beige skin, wavy black hair and hazel eyes".
        tail.append(Opt(("with", Series(groups))))
    if form.get("outfit"):
        tail.append(Opt((", wearing", value(form["outfit"]))))
    if form.get("close") and tail:
        parts.append(Opt((*tail, form["close"])))
    else:
        parts += tail
    return parts


def animal_parts(form: Dict[str, Any], value: Any) -> List[Part]:
    """An animal described: its life stage, then its breed, else its kind, else the user's word
    for it ("elderly golden retriever", "juvenile rabbit", "dog"); with every detail off, the
    user's own words."""
    v = {k.rsplit(".", 1)[-1]: value(k) for k in form["keys"]}
    if v and all(x.value is None for x in v.values()):
        return [form["words"]]
    main = next((v[d] for d in ("breed", "species") if d in v and v[d].value is not None), None)
    if main is not None and form.get("before_noun") and main is v.get("breed"):
        return [v.get("life_stage"), main, form["noun"]]
    return [v.get("life_stage"), main if main is not None else form["noun"]]


def template_text(entry: Dict[str, Any]) -> str:
    """The prompt with every pick shown as [Label]: what the option writer is shown."""
    labels = {p["id"]: p["label"] for p in entry.get("picks") or [] if not p.get("starts_off")}
    return tidy_text([t for t, _ in flatten(text_parts(
        entry, lambda cid: Val(cid, f"[{labels[cid]}]" if cid in labels else None)))])


# --------------------------------------------------------------------------- drawing

def _draw_order(picks: List[Dict[str, Any]], context: bool) -> List[Tuple[int, Dict[str, Any]]]:
    """(phase, pick) in drawing order: by phase, then as written; a pick whose list takes a
    context facet another bound pick in its scope gives is drawn after it (vocab.py)."""
    vocab = vocabulary()
    phase = [int(p.get("phase") or 1) for p in picks]

    def statement(p: Dict[str, Any]) -> str:
        # A person's details are one statement, a look's colors are the look's, anything else its own:
        # a giver in an earlier statement is drawn first in its phase, one in the same or a later
        # statement a phase after.
        s = p.get("slot")
        if p.get("follows"):
            return p["follows"]
        if s and p["id"].startswith(s + ".") and p["id"][len(s) + 1:] in DETAILS:
            return s
        return p["id"]
    stmt = [statement(p) for p in picks]
    order_of = {s: i for i, s in reversed(list(enumerate(stmt)))}
    leaves = {i: vocab.resolve(p["cls"]) for i, p in enumerate(picks)
              if p.get("cls") and p.get("source") != "list" and not p["id"].endswith(COLORS)}
    leaves = {i: lf for i, lf in leaves.items() if lf is not None and (lf.gives or lf.takes)}
    links = [(g, t) for t, tl in leaves.items() for g, gl in leaves.items()
             if g != t and any(f in gl.gives and (vocab.scope(f) == "scene" or
                                                   owns(person_of(picks[g]["id"]), person_of(picks[t]["id"])))
                               for f in tl.takes)] if context else []
    colors_of = {i: next((j for j, q in enumerate(picks) if q["id"] == p.get("follows")), None)
                 for i, p in enumerate(picks) if p.get("follows")}
    for _ in range(len(picks) + 2):
        moved = False
        for i in range(len(picks)):
            need = max([phase[i]] + [phase[g] + (0 if order_of[stmt[g]] < order_of[stmt[i]] else 1)
                                     for g, t in links if t == i])
            if i in colors_of and colors_of[i] is not None:
                need = phase[colors_of[i]]   # a look's colors are drawn right after the look
            if need != phase[i]:
                phase[i], moved = need, True
        if not moved:
            break
    else:
        phase = [int(p.get("phase") or 1) for p in picks]
    order = sorted(range(len(picks)), key=lambda i: (phase[i], i))
    return [(phase[i], picks[i]) for i in order]


class _Fill:
    def __init__(self, entry: Dict[str, Any], seed: int, pins: Dict[str, Sequence[str]], fixed: Dict[str, Any],
                 edits: Dict[str, Dict[str, Any]], options: Any):
        self.entry, self.options = entry, options
        self.rng = random.Random(seed)
        self.edits = edits
        self.pins = {str(k): {str(v) for v in vs} for k, vs in pins.items() if vs and not (edits.get(str(k)) or {}).get("off")}
        self.single = {k: next(iter(vs)) for k, vs in self.pins.items() if len(vs) == 1}
        self.fixed = dict(fixed)
        self.context_on = getattr(options, "context", True) is not False
        self.stated = (getattr(options, "stated_context", None) or {}) if self.context_on else {}
        self.list_context = (getattr(options, "list_context", None) or {}) if self.context_on else {}
        self.list_ages = getattr(options, "list_ages", None) or {}
        self.picks = [p for p in entry.get("picks") or []]
        self.parts_of: Dict[str, List[Dict[str, Any]]] = {}   # a face -> its parts (face_parts)
        for p in self.picks:
            if p.get("part_of"):
                self.parts_of.setdefault(str(p["part_of"]), []).append(p)
        self.minors = self._minors()
        self.drawn: Dict[str, Tuple[Dict[str, Any], str]] = {}   # id -> (pick, value as drawn, a template unfilled)
        self.values: Dict[str, Optional[str]] = {}               # id -> the value in the text (a look filled)
        self.records: Dict[str, Draw] = {}
        self.roles: Dict[str, Dict[str, str]] = {}
        self.pool_roles: Dict[str, Dict[str, Dict[str, str]]] = {}
        self.pools: Dict[str, Any] = {}
        self.more: List[str] = []

    def _minors(self) -> Dict[str, Tuple[str, ...]]:
        """Each person who may be under 18, with those ages: from the prepared prompt (an age
        narrowed to them, or a stated age), and from the user's own choices on an age pick
        here: a pin, an added value or a kept one. Nothing here reads the prompt's words."""
        out = {p: tuple(a) for p, a in (getattr(self.options, "minor_ages", None) or {}).items()}
        ages = {p["id"] for p in self.picks if p.get("cls") and getattr(vocabulary().resolve(p["cls"]), "id", None) == AGE_LIST}
        chosen: Dict[str, List[str]] = {}
        for cid, vs in self.pins.items():
            chosen.setdefault(cid, []).extend(vs)
        for cid, e in self.edits.items():
            chosen.setdefault(cid, []).extend(str(x) for x in (e or {}).get("add") or [])
        for cid, v in self.fixed.items():
            chosen.setdefault(cid, []).append(str(v))
        for cid, vs in chosen.items():
            young = minor_ages(vs) if cid in ages else ()
            if young:
                p = person_of(cid)
                out[p] = tuple(dict.fromkeys([*out.get(p, ()), *young]))
        return out

    def _minor(self, cid: str) -> Tuple[str, ...]:
        """The ages under 18 this pick's person may be in this draw: the prompt's, and those of the
        user's list values their age list drew (a list not drawn yet may be any of its values)."""
        p = person_of(cid)
        out = [a for who, ages in self.minors.items() if owns(who, p) for a in ages]
        for lid, young in self.list_ages.items():
            if not owns(person_of(lid), p) or not young:
                continue
            got = self.drawn.get(lid)
            for v in ([got[1]] if got is not None else list(young)):
                out += young.get(v, ())
        return tuple(dict.fromkeys(out))

    def _given(self, cid: str, leaf: Any) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
        """The context this pick is drawn in: for each facet its list takes, the families of the
        values drawn before it in its scope by lists giving that facet (and the user's list values
        read on such a list); failing those, what the prompt states for its person or scene."""
        vocab, p = vocabulary(), person_of(cid)
        out = []
        for facet in sorted(leaf.takes):
            person = vocab.scope(facet) == "person"
            fam: Set[str] = set()
            for oid, (pick, value) in self.drawn.items():
                if oid == cid or (person and not owns(person_of(oid), p)):
                    continue
                gl = vocab.get(pick.get("cls")) if pick.get("cls") and pick.get("source") != "list" else None
                if gl is not None and facet in gl.gives:
                    fam |= set(gl.context_tags(value, facet) or ())
                fam |= set(self.list_context.get(oid, {}).get(value, {}).get(facet, ()))
            if not fam:
                if person:
                    fam = {f for who, st in self.stated.items() if who is not None and owns(who, p) for f in st.get(facet, ())}
                else:
                    fam = set(self.stated.get(None, {}).get(facet, ()))
            if fam:
                out.append((facet, tuple(sorted(fam))))
        return tuple(out)

    def _eligible(self, spec: PickSpec, pins: Optional[Set[str]]) -> Tuple[Pool, List[Tuple[str, float]]]:
        pool = self.options.get(spec, {})
        self.pools[pool.key] = ([[o, w, *([pool.roles[o]] if o in pool.roles else [])]
                                 for o, w in zip(pool.items, pool.weights)] if pool.snapshot else len(pool.items))
        if pool.more_coming:
            self.more.append(spec.id)
        if pool.roles:
            self.pool_roles[spec.id] = pool.roles
        items = list(zip(pool.items, pool.weights))
        if pins:
            # A ticked option of the user's own draws like a typical value; a ticked standby value at its own weight.
            items = [(o, (1.0 if o in pool.own else pool.held.get(o, w)) if w <= 0 else w) for o, w in items if o in pins]
        return pool, items

    def _weighted(self, items: List[Tuple[str, float]]) -> str:
        """One item by weight; weight-0 items only when nothing else is left (only pins allow that)."""
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

    def _pieces(self, leaf: Any, items: List[Tuple[str, float]]) -> str:
        """Pieces the user ticked from different parts of a list of pieces (a face's nose and its
        freckles) go in together, one drawn from each part, in the list's order of parts; two ticked
        from one part (two noses) vary between them. "" when the ticks are all of one part."""
        order = list(leaf.local_facets["piece"])
        by: Dict[str, List[Tuple[str, float]]] = {}
        for o, w in items:
            v = leaf.value(o)
            if v is not None and w > 0:
                by.setdefault(str((v.tags.get("piece") or [""])[0]), []).append((o, w))
        if len(by) < 2:
            return ""
        return ", ".join(self._weighted(by[p]) for p in sorted(by, key=lambda p: order.index(p) if p in order else len(order)))

    def _choose(self, spec: PickSpec, pool: Pool, items: List[Tuple[str, float]]) -> Tuple[str, bool, bool]:
        """(value, pinned, the user's own) for a pick."""
        cid, names = spec.id, [o for o, _ in items]
        pin = self.single.get(cid)
        if pin is not None and not (spec.source == "list" and pin not in pool.items):
            # (a pin on the user's own list that isn't one of its items is passed by)
            return pin, True, pin in pool.own or pin not in pool.items
        if spec.said and cid not in self.pins and cid not in self.fixed and spec.said in names:
            return spec.said, True, False   # the user's own words, as a pin is
        kept = self.fixed.get(cid)
        if kept is not None and str(kept) in names:
            return str(kept), False, str(kept) in pool.own
        if not items or (cid not in self.pins and not any(w > 0 for _, w in items)):
            if spec.source != "list":
                self.options.request_more(spec, {}, "high")
            raise DrawAborted(cid, spec.label, "empty")
        v = self._weighted(items)
        return v, False, v in pool.own

    def _on(self, cid: str) -> bool:
        """Turned on: `on`, a pin or a kept value."""
        return bool((self.edits.get(cid) or {}).get("on")) or cid in self.pins or cid in self.fixed

    def _off(self, p: Dict[str, Any]) -> bool:
        """Left out: by the user, or a detail that starts left out and wasn't turned on (a pin,
        their own option, a kept value or `on`). A face is on when one of its parts is; a part is
        out when its face is left out."""
        cid = p["id"]
        e = self.edits.get(cid) or {}
        if e.get("off") or (p.get("part_of") and (self.edits.get(str(p["part_of"])) or {}).get("off")):
            return True
        if not p.get("starts_off") or self._on(cid):
            return False
        return not any(self._on(q["id"]) for q in self.parts_of.get(cid, ()))

    def _by_parts(self, cid: str) -> bool:
        """A face drawn from its parts: some part is chosen, and the face itself has no value
        chosen (a value kept from an older image) to draw beside them."""
        return (cid not in self.pins and cid not in self.fixed
                and any(self._on(q["id"]) and not self._off(q) for q in self.parts_of.get(cid, ())))

    def pick(self, p: Dict[str, Any], phase: int) -> None:
        cid = p["id"]
        if self._off(p) or (p.get("follows") and p["follows"] not in self.drawn) or self._by_parts(cid):
            self.values[cid] = None   # (a face drawn from its parts is put together after them: run)
            return
        if p.get("follows"):
            return self._palette(p, phase)
        source = p.get("source") if p.get("source") in SOURCES else "text"
        said = re.sub(r"\s+", " ", str(p.get("said") or "")).strip() if source != "list" else ""
        if said:
            source = "text"
        leaf = vocabulary().resolve(p["cls"]) if p.get("cls") and source != "list" else None
        seeds = [str(x) for x in p.get("seed") or []]
        zones = p.get("zones") or {}
        spec = PickSpec(cid, p["label"], str(p.get("about") or ""), phase, source, "pick",
                        list(dict.fromkeys([said, *seeds])) if said else seeds, list(p.get("items") or []),
                        leaf.id if leaf is not None else (str(p.get("cls") or "") if source != "list" else ""),
                        said=said, zones=tuple((str(z), tuple(v)) for z, v in zones.items()))
        if source != "list" and spec.cls != AGE_LIST:
            spec.minor = self._minor(cid)
        if leaf is not None and leaf.takes and self.context_on and cid not in self.single and not said:
            spec.context = self._given(cid, leaf)
            if cid in self.pins:
                # Values the user ticked draw evenly, but what can't fit at all still goes: a group of
                # black shades for a 20-year-old draws no salt-and-pepper. One value chosen is drawn as it is.
                spec.context = tuple((f, v) for f, v in spec.context
                                     if (leaf.takes.get(f) or ("",))[0] in ("drop", "never"))
        if leaf is not None and leaf.slots:
            self._unfill_kept(cid, leaf)
        pins = self.pins.get(cid)
        pool, items = self._eligible(spec, pins)
        if pins and spec.context and not any(w > 0 for _, w in items):
            spec.context = ()   # nothing chosen fits: what was chosen holds over fit
            pool, items = self._eligible(spec, pins)
        if pins and not items and (len(pins) > 1 or source == "list"):
            pool, items = self._eligible(spec, None)   # ticks that match nothing it has now are passed by
        value, pinned, own = self._choose(spec, pool, items)
        if leaf is not None and "piece" in leaf.local_facets and len(pins or ()) > 1 and cid not in self.single:
            value = self._pieces(leaf, items) or value
        template = ""
        shown = value
        if leaf is not None and leaf.slots and vocabulary().get(leaf.slots) is not None and is_template(value):
            template = value
            self.roles[cid] = {}
        elif "{" in value:
            shown = fill_template(value, None)
        # A face's part that drew nothing notable unasked (its list's plain value) adds no words,
        # and its record is hidden: nothing to keep, judge or show.
        plain = bool(p.get("part_of") and leaf is not None and leaf.plain and value == leaf.plain
                     and cid not in self.pins and cid not in self.fixed and not said)
        d = Draw(cid, shown, "pick", p["label"], source, p.get("line"), plain, pinned, [o for o, _ in items])
        d.phase, d.about, d.cls, d.said, d.own, d.template = phase, spec.about, spec.cls, said, own, template
        d.where = p.get("where") if isinstance(p.get("where"), dict) else str(p.get("where") or "").strip()
        self.drawn[cid] = (p, value)
        self.values[cid] = None if plain else shown
        self.records[cid] = d
        if template and not any(q.get("follows") == cid for q in self.picks):
            self.values[cid] = self.records[cid].value = fill_template(template, None)

    def _unfill_kept(self, cid: str, leaf: Any) -> None:
        """A kept value of a look names the filled look ("a navy T-shirt and white shorts"):
        keep the template it came from, read with the kept colors, or any template it fits."""
        names = {v.text for v in leaf.values}
        palette = vocabulary().get(leaf.slots)
        ccid = cid + COLORS
        kept = self.fixed.get(cid)
        if kept is None or str(kept) in names:
            return
        pv = palette.value(str(self.fixed.get(ccid) or "")) if palette is not None else None
        hit = next((v.text for v in leaf.values if pv is not None and fill_template(v.text, pv.roles) == str(kept)), None)
        if hit is None and pv is None and palette is not None:
            pair = next(((v.text, q.text) for v in leaf.values if template_matches(v.text, str(kept))
                         for q in palette.values if fill_template(v.text, q.roles) == str(kept)), None)
            if pair is not None:
                hit = pair[0]
                self.fixed.setdefault(ccid, pair[1])
        hit = hit or next((v.text for v in leaf.values if template_matches(v.text, str(kept))), None)
        if hit is not None:
            self.fixed[cid] = hit

    def _palette(self, p: Dict[str, Any], phase: int) -> None:
        """A look's colors: a pick of the palette list right after the look, restricted to the
        palettes its template allows; the look is filled with them."""
        of, ccid = p["follows"], p["id"]
        look = self.records.get(of)
        if look is None or not look.template:
            self.values[ccid] = None
            return
        leaf = vocabulary().resolve(self.drawn[of][0]["cls"])
        palette = vocabulary().get(leaf.slots)
        tv = leaf.value(look.template)
        restrict = tuple(sorted((str(f), tuple(str(x) for x in (w if isinstance(w, (list, tuple)) else [w])))
                                for f, w in (tv.palette if tv is not None else {}).items()))
        spec = PickSpec(ccid, "Colors", COLORS_ABOUT.format(look.about or look.label), phase, look.source, "pick",
                        [], [], palette.id, restrict)
        pins = self.pins.get(ccid)
        pool, items = self._eligible(spec, pins)
        if pins and len(pins) > 1 and not items:
            pool, items = self._eligible(spec, None)
        value, pinned, _own = self._choose(spec, pool, items)
        pv = palette.value(str(value))
        recorded = self.pool_roles.get(ccid, {}).get(str(value))
        roles = dict(recorded or (pv.roles if pv is not None else {}))
        look.value = self.values[of] = fill_template(look.template, roles)
        d = Draw(ccid, value, "pick", "Colors", look.source, p.get("line"), False, pinned, [o for o, _ in items], of)
        d.phase, d.about, d.cls = phase, spec.about, palette.id
        self.drawn[ccid] = (p, value)
        self.values[ccid] = value
        self.records[ccid] = d

    def run(self) -> None:
        for phase, p in _draw_order(self.picks, self.context_on):
            self.pick(p, phase)
        for face, parts in self.parts_of.items():
            # A face is its own value (one subtle piece, or one kept from an older image) and then
            # what its chosen parts drew, in the face's order of parts.
            got = [v for v in (self.values.get(face), *(self.values.get(q["id"]) for q in parts)) if v]
            if len(got) > (1 if self.values.get(face) else 0):
                self.values[face] = ", ".join(dict.fromkeys(got))
        for p in self.picks:   # a look whose colors are off reads without them
            d = self.records.get(p["id"])
            if d is not None and d.template and self.values.get(p["id"] + COLORS) is None:
                d.value = self.values[p["id"]] = fill_template(d.template, {})


def fill(entry: Dict[str, Any], seed: int, pins: Optional[Dict[str, Sequence[str]]] = None,
         fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Dict[str, Any]]] = None, *,
         options: Optional[OptionsService] = None) -> DrawResult:
    """One image's prompt from a prepared entry (slots.assemble): every pick drawn, then each
    segment in order. Deterministic for a seed, pins and pools. DrawAborted when a pick has
    nothing left to draw."""
    edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    f = _Fill(entry, seed, pins, dict(fixed or {}), edits, options or LiteralOptions(edits))
    f.run()
    # A value that goes without saying (an animal's adult stage) adds no word, unless it is pinned.
    plain = {k: v for sl in entry.get("slots") or [] for k, v in ((sl.get("form") or {}).get("plain") or {}).items()}
    parts = flatten(text_parts(entry, lambda cid: Val(cid, None if cid in plain and cid not in f.pins
                                                      and f.values.get(cid) == plain[cid] else f.values.get(cid))))
    prompt = tidy_text([t for t, _ in parts])
    if not prompt:
        raise ProgramError("The prompt has no text.")
    order = [p["id"] for p in f.picks]
    draws = [f.records[cid] for cid in order if cid in f.records]
    for d in draws:   # a look's record says what the text shows ("an espresso coat", not "a espresso coat")
        if d.template and isinstance(d.value, str):
            d.value = next((x for x in (d.value, tidy_text([d.value])) if x.lower() in prompt.lower()), d.value)
    return DrawResult(prompt, draws, seed, revision=_revision(entry, f, edits),
                      more_coming=list(dict.fromkeys(f.more)), value_parts=parts)


def _revision(entry: Dict[str, Any], f: _Fill, edits: Dict[str, Any]) -> Dict[str, Any]:
    # A vocabulary pool is recorded by the hash of its contents, kept once beside the written options (compact.py).
    kept = getattr(getattr(f.options, "store", None), "pools", None)
    pools = {k: kept.put(v) if kept is not None and isinstance(v, list) else v for k, v in f.pools.items()}
    rev = {"engine": FILL_VERSION, "entry": entry.get("key"), "pools": dict(sorted(pools.items())),
           "edits": hashlib.sha256(json.dumps(edits, sort_keys=True, default=str).encode()).hexdigest()[:16]
           if edits else None}
    version = getattr(f.options, "revision_version", None)
    if version:
        rev["options"] = version
    if f.context_on:
        rev["context"] = getattr(f.options, "context_version", None) or CONTEXT_VERSION
    rev["id"] = hashlib.sha256(json.dumps(rev, sort_keys=True).encode()).hexdigest()[:16]
    return rev


__all__ = ["CAMERA", "COLORS", "COLORS_ABOUT", "CONTEXT_VERSION", "DETAILS", "STARTS_OFF", "Draw", "DrawAborted", "DrawResult", "KINDS",
           "face_parts",
           "LiteralOptions", "Opt", "OptionsService", "Series", "PickSpec", "Pool", "ProgramError", "RANK_DECAY", "ReadingError",
           "RunResult", "Val", "choice_options", "context_suffix", "fill", "fix_articles", "flatten", "owns",
           "person_of", "picks_of", "pool_key", "subject_of", "template_text", "text_parts", "tidy_text", "value_spans"]

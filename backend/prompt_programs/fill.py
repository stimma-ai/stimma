"""Filling a prompt's slots: one image's text, drawn straight from the parse and the pools.

    dorm room with a <young man>, lit by <light>

Each slot that has been read draws one variant of its words from its pool (variant_pools.py:
least-used first, the user's choices, pins and their own variants); a slot not read yet, or
whose pool isn't written yet, goes in as its own words. The user's own lists ({a|b}) draw one
item each. Then the text is put together segment by segment: the user's text, comment lines,
each value, and a slot left out goes with its lead. No model call, nothing generated as code.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

FILL_VERSION = "variants-1"
MAX_PROMPT_CHARS = 100_000

class ProgramError(Exception):
    """A draw that can't be made (kept under its old name: callers catch it as the run's error)."""

    code = "program_failed"


# --------------------------------------------------------------------------- records

@dataclass
class Draw:
    id: str
    value: Any
    kind: str = "pick"
    label: str = ""
    source: str = "text"           # list (the user's), variant, own, pinned, fixed, words
    line: Optional[int] = None
    hidden: bool = False
    pinned: bool = False
    options: List[str] = field(default_factory=list)   # what was available this time
    about: str = ""                # a slot's own words
    own: bool = False              # the user's own variant: never rerolled
    seeds: Dict[str, str] = field(default_factory=dict)   # the seeds the variant was written with
    phase: Optional[int] = None
    follows: Optional[str] = None
    cls: str = ""
    where: Any = ""
    said: str = ""
    shared: bool = False
    template: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {"id": self.id, "value": self.value, "kind": self.kind, "label": self.label, "source": self.source}
        if self.line is not None:
            d["line"] = self.line
        for k in ("hidden", "pinned"):
            if getattr(self, k):
                d[k] = True
        for k in ("about", "seeds"):
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
    more_coming: List[str] = field(default_factory=list)   # slots whose pools are still being written
    # The parts in order, each with the id of the choice whose value it is (None for the user's text).
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
    """A user list with nothing left to draw (the judge removed every item): the message is shown at the choice."""

    def __init__(self, choice_id: str, label: str, reason: str, value: Optional[str] = None):
        self.choice_id, self.label, self.reason, self.value = choice_id, label, reason, value
        super().__init__(f"Nothing left to draw for {label}.")

    def to_dict(self) -> Dict[str, Any]:
        d = {"code": "nothing_to_draw", "message": str(self), "choice_id": self.choice_id, "reason": self.reason}
        if self.value is not None:
            d["value"] = self.value
        return d


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


# --------------------------------------------------------------------------- the text of a prompt

def text_parts(entry: Dict[str, Any], value: Any, held: Sequence[str] = ()) -> List[Part]:
    """The prompt's parts in order: the user's text, comment lines on their own lines, and each
    slot and list as `value(id)` gives it (a Val). A slot not read (or read as written) is its
    own words, unless it is `held` (a recorded value replayed). The lead the reader named goes
    with its slot when it is left out."""
    held = set(held)
    slots = {s["n"]: s for s in entry.get("slots") or []}
    lists = {l["n"]: l for l in entry.get("lists") or []}
    parts: List[Part] = []
    pending = ""

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
        if (s.get("state") != "ready" or s.get("degraded")) and s.get("id") not in held:
            pending += seg["words"]
            continue
        lead = flush(str(s.get("lead") or ""))
        parts.append(Opt(([lead] if lead else []) + [value(s["id"])]))
    flush()
    return parts


def template_text(entry: Dict[str, Any]) -> str:
    """The prompt with every slot read shown as [Label]."""
    labels = {s["id"]: s.get("label") or s.get("words") for s in entry.get("slots") or []}
    labels.update({l["id"]: l.get("label") or l["id"] for l in entry.get("lists") or []})
    return tidy_text([t for t, _ in flatten(text_parts(entry, lambda cid: Val(cid, f"[{labels.get(cid, cid)}]")))])


# --------------------------------------------------------------------------- drawing

class OptionsService:
    """What a fill draws slots from (fluent.Variants): per slot its pool, use counts and choice."""

    def pool(self, slot: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:   # pragma: no cover
        return [], {}

    def choice(self, slot_id: str) -> Any:   # pragma: no cover
        from prompt_programs.variant_pools import Choice
        return Choice()


def _list_draw(p: Dict[str, Any], rng: random.Random, pins: Dict[str, List[str]], fixed: Dict[str, Any],
               edits: Dict[str, Dict[str, Any]]) -> Draw:
    """One of the user's own lists: an item, evenly; never weighted or filtered."""
    cid = p["id"]
    e = edits.get(cid) or {}
    gone = {str(x) for x in e.get("remove") or []}
    items = [o for o in dict.fromkeys([*(str(x) for x in p.get("items") or []), *(str(x) for x in e.get("add") or [])])
             if o not in gone]
    pinned = [x for x in pins.get(cid) or [] if x in items]
    if cid in fixed and fixed[cid] is not None:
        value, was_pinned = str(fixed[cid]), False
    elif pinned:
        value, was_pinned = rng.choice(pinned), True
    elif items:
        value, was_pinned = rng.choice(items), False
    else:
        raise DrawAborted(cid, str(p.get("label") or cid), "empty")
    return Draw(cid, value, "pick", str(p.get("label") or cid), "list", p.get("line"), pinned=was_pinned,
                options=items)


def fill(entry: Dict[str, Any], seed: int, pins: Optional[Dict[str, Sequence[str]]] = None,
         fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Dict[str, Any]]] = None, *,
         options: Optional[Any] = None) -> DrawResult:
    """One image's prompt from a prepared entry: each user list and each read slot drawn, then
    the text. `pins`: user lists' ticked items; `fixed`: values held as they are (a replay, Keep
    from this sent as fixed, the judge's held values); `edits`: per id {"off", "add", "remove"}
    (the judge removes what it refused). Slots draw through `options` (fluent.Variants); without
    one every slot stands as its words. Deterministic for a seed, choices and pools."""
    from prompt_programs.variant_pools import Choice, drawable, pick
    rng = random.Random(seed)
    edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    fixed = {str(k): v for k, v in (fixed or {}).items()}
    records: Dict[str, Draw] = {}
    values: Dict[str, Optional[str]] = {}
    more: List[str] = []
    rev: Dict[str, Dict[str, str]] = {}
    for p in entry.get("picks") or []:
        if p.get("source") != "list":
            continue
        if (edits.get(p["id"]) or {}).get("off"):
            values[p["id"]] = None
            continue
        d = _list_draw(p, rng, pins, fixed, edits)
        records[p["id"]], values[p["id"]] = d, d.value
        rev[p["id"]] = {"text": d.value}   # a replay draws the user's list as it was drawn too
    held: List[str] = []
    for s in entry.get("slots") or []:
        sid = s["id"]
        if s.get("state") != "ready" or s.get("degraded"):
            # A recorded value replayed holds though the slot isn't read now (a reset reader cache).
            if isinstance(fixed.get(sid), str) and fixed[sid].strip():
                values[sid] = fixed[sid]
                held.append(sid)
                records[sid] = Draw(sid, fixed[sid], "pick", str(s.get("label") or s["words"]), "fixed", s.get("line"),
                                    about=s["words"])
            continue
        e = edits.get(sid) or {}
        choice = options.choice(sid) if options is not None else Choice()
        if e.get("off"):
            choice = Choice(off=True)
        elif e.get("add"):
            choice = Choice(values=choice.values, add=(*choice.add, *(str(x) for x in e["add"])), pins=choice.pins,
                            as_written=choice.as_written, off=choice.off)
        variants, uses = options.pool(s) if options is not None else ([], {})
        gone = {str(x).lower() for x in e.get("remove") or []}
        if gone:
            variants = [v for v in variants if v["text"].lower() not in gone]
            choice = Choice(values=tuple(t for t in choice.values if t.lower() not in gone),
                            add=tuple(t for t in choice.add if t.lower() not in gone), pins=choice.pins,
                            as_written=choice.as_written, off=choice.off)
        if not variants and not choice.off and not choice.as_written and sid not in fixed:
            more.append(sid)
        got = pick(variants, uses, choice, rng, s["words"], fixed=fixed.get(sid))
        values[sid] = got.text
        if got.text is None:
            continue
        shown = [v["text"] for v in drawable(variants, choice)] if got.source != "words" else []
        d = Draw(sid, got.text, "pick", str(s.get("label") or s["words"]), got.source, s.get("line"),
                 pinned=got.source == "pinned", options=shown, about=s["words"], own=got.source == "own",
                 seeds={k: str(v) for k, v in (got.seeds or {}).items()})
        records[sid] = d
        if s.get("pool"):
            rev[sid] = {"pool": str(s["pool"]), "text": got.text}
    parts = flatten(text_parts(entry, lambda cid: Val(cid, values.get(cid)), held))
    prompt = tidy_text([t for t, _ in parts])
    if not prompt:
        raise ProgramError("The prompt has no text.")
    order = [*(s["id"] for s in entry.get("slots") or []), *(p["id"] for p in entry.get("picks") or [])]
    draws = sorted(records.values(), key=lambda d: order.index(d.id) if d.id in order else len(order))
    revision = {"engine": FILL_VERSION, "entry": entry.get("key"), "variants": dict(sorted(rev.items())),
                "edits": hashlib.sha256(json.dumps(edits, sort_keys=True, default=str).encode()).hexdigest()[:16]
                if edits else None}
    revision["id"] = hashlib.sha256(json.dumps(revision, sort_keys=True).encode()).hexdigest()[:16]
    return DrawResult(prompt, draws, seed, revision=revision, more_coming=more, value_parts=parts)


__all__ = ["Draw", "DrawAborted", "DrawResult", "FILL_VERSION", "MAX_PROMPT_CHARS",
           "Opt", "OptionsService", "ProgramError", "RunResult", "Series", "Val", "fill", "fix_articles", "flatten",
           "template_text", "text_parts", "tidy_text", "value_spans"]

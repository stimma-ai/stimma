"""Slots: the parts of a prompt the user marked to vary, as <words>.

    dorm room with a <young man>, lit by <light>

A slot is `<` + 2 to 80 characters + `>` on one line, with none of `< > { } [ ] | # : =`,
not starting with `/` or a space and not ending with a space, and not right after a letter,
digit or `<`. Slots are not looked for on comment lines, inside [verbatim], or inside
{a|b} lists and {{name}}s. frontend/src/utils/promptSyntax.ts finds them the same way;
both sides are tested against frontend/src/utils/slotGrammar.cases.json.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SLOT_RE = re.compile(r"(?<![<\w])<(?![/\s])([^<>{}\[\]|#:=\n]{2,80})(?<!\s)>")

_NAME = re.compile(r"\{\{[^{}]+\}\}")
_VERBATIM = re.compile(r"\[[^\]]+\]")
_COMMENT = re.compile(r"^\s*#")

Span = Tuple[int, int]


def is_comment(line: str) -> bool:
    return bool(_COMMENT.match(line))


def _list_spans(line: str, skip: List[Span]) -> List[Span]:
    """{...} groups with a | at their own depth (nested lists are one list), outside {{names}}."""
    out: List[Span] = []
    i = 0
    while i < len(line):
        if any(a <= i < b for a, b in skip):
            i += 1
            continue
        if line[i] == "{":
            start, depth, has_pipe = i, 1, False
            i += 1
            while i < len(line) and depth > 0:
                c = line[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                elif c == "|" and depth == 1:
                    has_pipe = True
                i += 1
            if depth == 0 and has_pipe:
                out.append((start, i))
        else:
            i += 1
    return out


def _line_marks(line: str) -> Tuple[List[Span], List[Span], List[Span]]:
    """A non-comment line's slots, lists and {{names}}, in line offsets."""
    names = [m.span() for m in _NAME.finditer(line)]
    lists = _list_spans(line, names)
    skip = names + lists + [m.span() for m in _VERBATIM.finditer(line)]
    slots = [m.span() for m in SLOT_RE.finditer(line) if not any(a <= m.start() < b for a, b in skip)]
    return slots, lists, names


def _lines(text: str):
    at = 0
    for n, line in enumerate(text.split("\n"), 1):
        yield n, at, line
        at += len(line) + 1


def find_slots(text: str) -> List[Span]:
    """Every slot's span in the text, brackets included."""
    out: List[Span] = []
    for _, at, line in _lines(text):
        if not is_comment(line):
            out += [(at + a, at + b) for a, b in _line_marks(line)[0]]
    return out


def unwrap_slots(text: str) -> str:
    """Each <words> as its words: what a slot means where nothing varies it."""
    for a, b in reversed(find_slots(text)):
        text = text[:a] + text[a + 1:b - 1] + text[b:]
    return text


@dataclass
class Segment:
    kind: str                  # text, slot, list, comment
    text: str                  # as it stands in the prompt
    span: Span
    line: int                  # 1-based
    words: str = ""            # slot: the words inside the brackets
    items: List[str] = field(default_factory=list)  # list: its items


@dataclass
class Parsed:
    prompt: str
    segments: List[Segment]

    def slots(self) -> List[Segment]:
        return [s for s in self.segments if s.kind == "slot"]

    def lists(self) -> List[Segment]:
        return [s for s in self.segments if s.kind == "list"]

    def varies(self) -> bool:
        return any(s.kind in ("slot", "list") for s in self.segments)


def _items(group: str) -> List[str]:
    inner, depth, items, cur = group[1:-1], 0, [], ""
    for c in inner:
        if c == "|" and depth == 0:
            items.append(cur.strip())
            cur = ""
            continue
        depth += c == "{"
        depth -= c == "}"
        cur += c
    items.append(cur.strip())
    return items


def parse(prompt: str) -> Parsed:
    """The prompt cut into ordered text, slot, list and comment segments. Run on the prompt
    after expand_named_lists and mask_exact. A comment segment is its line without the
    newline; the newline belongs to the text after it."""
    segments: List[Segment] = []

    def text(a: int, b: int, n: int):
        if b <= a:
            return
        last = segments[-1] if segments else None
        if last and last.kind == "text" and last.span[1] == a:
            last.text += prompt[a:b]
            last.span = (last.span[0], b)
        else:
            segments.append(Segment("text", prompt[a:b], (a, b), n))

    for n, at, line in _lines(prompt):
        if n > 1:
            text(at - 1, at, n - 1)
        if is_comment(line):
            segments.append(Segment("comment", line, (at, at + len(line)), n))
            continue
        slots, lists, _ = _line_marks(line)
        marks = sorted([("slot", s) for s in slots] + [("list", s) for s in lists], key=lambda m: m[1][0])
        pos = 0
        for kind, (a, b) in marks:
            text(at + pos, at + a, n)
            seg = Segment(kind, line[a:b], (at + a, at + b), n)
            if kind == "slot":
                seg.words = line[a + 1:b - 1]
            else:
                seg.items = _items(line[a:b])
            segments.append(seg)
            pos = b
        text(at + pos, at + len(line), n)
    return Parsed(prompt, segments)


# --------------------------------------------------------------------------- the program

KINDS = ("person", "camera", "light", "list", "free")
CAMERA = ("shot_size", "lens", "angle", "film_look")


class ReadingError(ValueError):
    """A slot reading the builder can't use (the reader checks for these before it builds)."""


def slot_ids(parsed: Parsed) -> List[str]:
    """Each slot's id: its words slugged, the second slot with the same words `_2`. Only an
    identifier: nothing decides anything by it."""
    used = {f"list{i}" for i in range(1, len(parsed.lists()) + 1)}
    out: List[str] = []
    for s in parsed.slots():
        # ASCII and starting with a letter: the runtime reads whose detail a pick is from its id.
        base = re.sub(r"[^a-z0-9]+", "_", s.words.lower()).strip("_") or "slot"
        if not base[0].isalpha():
            base = f"slot_{base}"
        cid, k = base, 1
        while cid in used:
            k += 1
            cid = f"{base}_{k}"
        used.add(cid)
        out.append(cid)
    return out


def _call(fn: str, *args: Any, **kw: Any) -> str:
    """A call with every value written by repr(), so quoting is never a problem."""
    inner = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kw.items() if v is not None]
    return f"{fn}({', '.join(inner)})"


def _opt(*parts: str) -> str:
    return f"opt({', '.join(parts)})"


def _strings(v: Any, what: str) -> List[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ReadingError(f"{what} must be a list of strings")
    return [x for x in v if x.strip()]


def build(parsed: Parsed, readings: Dict[str, Any], as_typed: Optional[Dict[str, str]] = None) -> Tuple[str, Dict[str, Any]]:
    """The program for a parsed prompt and its slot reading (reader.py's reply, checked):
    one statement per pick, one emit() in the prompt's order. Returns the source and the
    entry the runtime draws from (`slot_words` still to be narrowed: narrow.narrow_entry).

    A slot read as written (`degraded`) is its own words in the text. `as_typed` (a slot_words
    key → why) holds stated words whose narrowing didn't come back: a person's detail draws the
    words as typed (said=), and a list slot stands as its words."""
    from prompt_programs.people import DETAILS, expand_people
    from prompt_programs.runtime import discover
    from prompt_programs.vocab import vocabulary

    vocab = vocabulary()
    typed = dict(as_typed or {})
    by_n = {r.get("n"): r for r in readings.get("slots") or [] if isinstance(r, dict)}
    labels = {r.get("n"): str(r.get("label") or "") for r in readings.get("lists") or [] if isinstance(r, dict)}
    ids = slot_ids(parsed)
    stmts: List[str] = []
    parts: List[str] = []
    slot_words: Dict[str, str] = {}
    meta: List[Dict[str, Any]] = []
    pending = ""   # text since the last mark, on this line

    def listed(cls: Any, what: str) -> str:
        if not isinstance(cls, str) or vocab.get(cls) is None:
            raise ReadingError(f"{what}: {cls!r} is not a list")
        return cls

    def flush(lead: str = "") -> str:
        """Emit the pending text, but the slot's lead: the reader's copy of the words that end it
        (spaces at the end aside), or none when they don't."""
        nonlocal pending
        lead, stem = lead.rstrip(), pending.rstrip()
        if not lead.strip() or not stem.endswith(lead):
            lead, stem = "", pending
        before = stem[:len(stem) - len(lead)]
        if before.strip():
            parts.append(repr(before))
        pending = ""
        return lead

    slot_n = list_n = 0
    person_at = None   # the stmts index of a person, until the text after them is seen
    for seg in parsed.segments:
        if person_at is not None:
            # Words right after a person ("... jeans reading on a porch", "... a forked beard reading")
            # are set off by a comma that closes the person's description, whatever of it is drawn;
            # punctuation, a line's end or another mark need none.
            if seg.kind == "text" and re.match(r"[ \t]*\w", seg.text):
                stmts[person_at] = stmts[person_at][:-1] + ", close=',')"
            person_at = None
        if seg.kind == "text":
            lines = seg.text.split("\n")
            for piece in lines[:-1]:
                pending += piece
                if pending.strip():
                    parts.append(repr(pending + "\n"))
                else:
                    parts.append(repr("\n"))
                pending = ""
            pending += lines[-1]
            continue
        if seg.kind == "comment":
            flush()
            parts.append(repr(seg.text))
            continue
        if seg.kind == "list":
            flush()
            list_n += 1
            cid = f"list{list_n}"
            stmts.append(f"{cid} = " + _call("pick", cid, seg.items, label=labels.get(list_n) or f"List {list_n}",
                                              source="list", phase=1, line=seg.line))
            parts.append(cid)
            continue
        slot_n += 1
        cid, var = ids[slot_n - 1], f"slot{slot_n}"
        r = by_n.get(slot_n)
        if r is None or r.get("kind") not in KINDS:
            raise ReadingError(f"slot {slot_n} has no reading")
        kind, label = r["kind"], str(r.get("label") or seg.words)
        lead = str(r.get("lead") or "")
        got = r.get(kind) if isinstance(r.get(kind), dict) else {}
        info: Dict[str, Any] = {"id": cid, "n": slot_n, "kind": kind, "label": label, "words": seg.words,
                                "span": list(seg.span), "line": seg.line}
        if kind == "list" and cid in typed:
            r = {"degraded": True, "reason": typed[cid]}
        if r.get("degraded"):
            # Its reading couldn't be used: the words stand as typed, and the pill has nothing to choose yet.
            info.update(kind="free", label=seg.words, degraded=True)
            pending += seg.words
            meta.append(info)
            continue
        if kind == "person":
            flush()
            vary = [d for d in got.get("vary") or [] if d in DETAILS]
            stated = {d: str(w) for d, w in (got.get("stated") or {}).items() if d in DETAILS and str(w).strip()}
            presentation = got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else None
            keyed = {d: f"{cid}.{d if d in vary or d != 'age' else 'stated_age'}" for d in stated}
            said = {d: w for d, w in stated.items() if keyed[d] in typed} or None
            outfit = got.get("outfit") or ""
            stmts.append(f"{var} = " + _call("person", cid, noun=str(got.get("noun") or "person"), presentation=presentation,
                                             said=said, show=vary, article=False, words=seg.words)[:-1]
                         + (f", wearing={var}_outfit)" if outfit else ")"))
            person_at = len(stmts) - 1
            parts.append(var)
            for d, w in stated.items():
                if keyed[d] not in typed:
                    slot_words[keyed[d]] = w
            if said:
                info["degraded"] = True
            info["stated"] = stated
            if outfit:
                about = f"{label}'s outfit"
                if outfit == "written":
                    seeds = _strings(got.get("outfit_examples") or [], "outfit_examples")
                    stmts.append(f"{var}_outfit = " + _call("pick", f"{cid}.outfit", about=about, seed=seeds or None,
                                                            label="Outfit", phase=2))
                else:
                    leaf = vocab.get(listed(outfit, label))
                    # How the person presents narrows their outfit list, as person() does for face and build.
                    where = ({"presentation": presentation}
                             if presentation and presentation in leaf.local_facets.get("presentation", ()) else None)
                    stmts.append(f"{var}_outfit = " + _call("pick", f"{cid}.outfit", cls=outfit, where=where,
                                                            about=about, label="Outfit", phase=2))
        elif kind == "camera":
            lead = flush(lead)
            vary = [d for d in got.get("vary") or [] if d in CAMERA and vocab.get(f"camera.{d}") is not None]
            if not vary:
                raise ReadingError(f"slot {slot_n}: a camera varies none of {CAMERA}")
            group = []
            for i, d in enumerate(vary):
                leaf = vocab.get(f"camera.{d}")
                stmts.append(f"{var}_{d} = " + _call("pick", f"{cid}.{d}", cls=leaf.id, about=f"the camera's {leaf.label.lower()}",
                                                     label=leaf.label, phase=1))
                group.append(_opt(f"{var}_{d}") if i == 0 else _opt(repr(","), f"{var}_{d}"))
            parts.append(_opt(*([repr(lead)] if lead else []), *group))
        else:
            lead = flush(lead)
            if kind == "light" and got.get("list"):
                stmts.append(f"{var} = " + _call("pick", cid, cls=listed(got["list"], label), about=seg.words,
                                                 label=label, phase=1))
            elif kind == "light":
                stmts.append(f"{var} = " + _call("pick", cid, about=seg.words, seed=_strings(got.get("examples") or [], "examples"),
                                                 label=label, phase=1))
                slot_words[cid] = seg.words
            elif kind == "list":
                # The slot's words narrow its list, said of what the reader says it is in this image:
                # "pet" on an animal list keeps pets; "hairstyle" said of "a middle-aged man's hairstyle".
                stmts.append(f"{var} = " + _call("pick", cid, cls=listed(got.get("list"), label),
                                                 about=str(got.get("about") or "").strip() or seg.words,
                                                 label=label, phase=1))
                slot_words[cid] = seg.words
            else:
                kinds = _strings(got.get("kinds") or [], "kinds")
                instead = _strings(got.get("instead") or [], "instead")
                # Things instead are a zone only when the reader found some: a slot can have its kinds alone.
                zones = {"kinds": kinds, **({"instead": instead} if instead else {})}
                stmts.append(f"{var} = " + _call("pick", cid, about=str(got.get("about") or seg.words), seed=kinds,
                                                 zones=zones, label=label, phase=2))
                slot_words[cid] = seg.words
                info["zones"] = zones
            parts.append(_opt(*([repr(lead)] if lead else []), var))
        meta.append(info)
    flush()
    source = "\n".join([*stmts, f"emit({', '.join(parts)})"]) + "\n"
    program = expand_people(source)
    found = discover(program)
    for m in meta:
        m["details"] = [c["id"] for c in found["choices"] if c["id"] == m["id"] or c["id"].startswith(m["id"] + ".")]
    entry = {"program": program, "choices": found["choices"], "groups": found["groups"], "example": found["example"],
             "prompt": parsed.prompt, "mode": "prose", "slot_words": slot_words, "slots": meta}
    return source, entry


# --------------------------------------------------------------------------- composing an entry

def _segment(seg: Segment) -> Dict[str, Any]:
    out: Dict[str, Any] = {"kind": seg.kind, "text": seg.text, "span": list(seg.span), "line": seg.line}
    if seg.kind == "slot":
        out["words"] = seg.words
    if seg.kind == "list":
        out["items"] = list(seg.items)
    return out


def compose(parsed: Parsed, readings: Dict[int, Dict[str, Any]], labels: Optional[Dict[int, str]] = None
            ) -> Dict[str, Any]:
    """What a prompt draws from, from its parse and whichever readings are ready (slot number ->
    reading as reader.check_slot gives it; list number -> label). A slot with no reading yet,
    or one read as written, stands as its words. Plain data; no model, no store."""
    from prompt_programs.fill import ReadingError, choice_options, picks_of, template_text

    ids = slot_ids(parsed)
    segs = parsed.segments
    slots: List[Dict[str, Any]] = []
    lists: List[Dict[str, Any]] = []
    picks: List[Dict[str, Any]] = []
    slot_words: Dict[str, str] = {}
    slot_n = list_n = 0
    for i, seg in enumerate(segs):
        if seg.kind == "list":
            list_n += 1
            label = (labels or {}).get(list_n)
            lists.append({"id": f"list{list_n}", "n": list_n, "line": seg.line, "items": list(seg.items),
                          "label": label or "", "state": "ready" if label is not None else "reading"})
            picks.append({"id": f"list{list_n}", "kind": "pick", "label": label or f"List {list_n}", "phase": 1,
                          "source": "list", "items": list(seg.items), "line": seg.line})
            continue
        if seg.kind != "slot":
            continue
        slot_n += 1
        cid = ids[slot_n - 1]
        info: Dict[str, Any] = {"id": cid, "n": slot_n, "words": seg.words, "span": list(seg.span), "line": seg.line,
                                "kind": "free", "label": seg.words, "details": [], "state": "reading"}
        slots.append(info)
        r = readings.get(slot_n)
        if r is None:
            continue
        info["state"] = "ready"
        if r.get("degraded"):
            # Its reading couldn't be used: the words stand as typed, and the pill has nothing to choose yet.
            info["degraded"] = True
            continue
        # Words right after a person ("... jeans reading on a porch") are set off by a comma that
        # closes their description, whatever of it is drawn; punctuation, a line's end or another
        # mark need none.
        after = segs[i + 1] if i + 1 < len(segs) else None
        close = "," if after is not None and after.kind == "text" and re.match(r"[ \t]*\w", after.text) else ""
        try:
            got, made = picks_of(cid, seg.words, r, close=close)
        except ReadingError:
            info["degraded"] = True
            continue
        info.update(kind=r["kind"], label=str(r.get("label") or seg.words), lead=str(r.get("lead") or ""),
                    details=[p["id"] for p in got], form=made["form"])
        if made.get("stated"):
            info["stated"] = made["stated"]
        if made.get("zones"):
            info["zones"] = made["zones"]
        slot_words.update(made.get("slot_words") or {})
        picks += got
    choices = []
    for p in picks:
        c = {k: v for k, v in p.items() if k not in ("items", "seed")}
        c["options"] = choice_options(p)
        if p.get("seed"):
            c["seed"] = list(p["seed"])
        choices.append(c)
    entry = {"prompt": parsed.prompt, "mode": "prose", "segments": [_segment(s) for s in segs], "slots": slots,
             "lists": lists, "picks": picks, "choices": choices, "slot_words": slot_words}
    entry["template"] = template_text(entry)
    return entry


# --------------------------------------------------------------------------- prepared, at once

SLOTS_VERSION = "slots-2"

# Background work, by (store, cache key): a part's reading, and a prompt's settling (narrowing
# with the model once a reading lands, then starting its option pools). Never started twice.
_reads: Dict[Tuple[str, str], Any] = {}
_settling: Dict[Tuple[str, str], Any] = {}
_again: set = set()
# A part whose last reading couldn't be used or whose call failed, and why: it stands as
# written until a prepare that starts work reads it again. Never cached on disk.
_failed: Dict[Tuple[str, str], str] = {}


@dataclass
class _Prompt:
    typed: str
    parsed: Parsed
    masked: str
    exact: Dict[str, str]
    key: str
    model: Optional[str]
    store: Any
    profile_id: Optional[str]
    project_id: Optional[int]

    @property
    def root(self) -> str:
        return str(self.store.root)

    def cache(self) -> Any:
        from prompt_programs.narrow import NarrowCache
        return NarrowCache(self.store.root / "reader")

    def parts(self) -> List[Tuple[str, int, str]]:
        """(kind, number, cache key) of each slot and list."""
        from prompt_programs.reader import part_key
        from prompt_programs.vocab import vocabulary
        version, out, s, l = vocabulary().version, [], 0, 0
        for seg in self.parsed.segments:
            if seg.kind == "slot":
                s += 1
                out.append(("slot", s, part_key(self.parsed, seg, self.model, version)))
            elif seg.kind == "list":
                l += 1
                out.append(("list", l, part_key(self.parsed, seg, self.model, version)))
        return out


async def _read_prompt(prompt: str, profile_id: Optional[str], project_id: Optional[int]) -> Optional[_Prompt]:
    """The prompt as parsed for reading, or None when nothing in it varies."""
    from prompt_pipeline import _profile_wildcards_and_segments
    from prompt_programs import program as prep
    from prompt_programs.reader import READER_VERSION
    from prompt_programs.store import program_key
    from prompt_programs.vocab import vocabulary

    wildcards, segments = _profile_wildcards_and_segments(profile_id)
    source = prep.expand_named_lists(prompt, wildcards, segments).strip()
    if len(source) > prep.MAX_PROMPT_CHARS:
        raise prep.PromptTooLong(f"This prompt is too long to prepare ({len(source):,} characters with its lists "
                                 f"and segments filled in; the limit is {prep.MAX_PROMPT_CHARS:,}). Shorten it, or use Direct.")
    masked, exact = prep.mask_exact(source)
    parsed = parse(masked)
    if not parsed.varies():
        return None
    model = await prep.model_fingerprint(project_id)
    key = program_key({"v": SLOTS_VERSION, "reader": READER_VERSION, "model": model, "vocab": vocabulary().version,
                       "prompt": masked, "exact": exact})
    return _Prompt(prompt, parsed, masked, exact, key, model, prep.store_for(profile_id), profile_id, project_id)


async def _assemble(p: _Prompt, ask: Any) -> Dict[str, Any]:
    """The prompt's entry from its parse and the readings cached, narrowed with `ask` (None:
    from the cache only, which never calls a model)."""
    from prompt_programs.reader import as_written, cached
    readings, labels = cached(p.parsed, p.model, p.cache())
    segs = {(kind, n): seg for kind, n, seg in _marked(p.parsed)}
    for kind, n, key in p.parts():
        why = _failed.get((p.root, key))
        if why is None:
            continue
        if kind == "slot" and n not in readings:
            readings[n] = as_written(n, segs[("slot", n)], why)
        elif kind == "list" and n not in labels:
            labels[n] = ""
    entry = compose(p.parsed, readings, labels)
    entry.update({"key": p.key, "version": SLOTS_VERSION, "exact": p.exact, "typed": p.typed,
                  "readings": {"slots": [readings[n] for n in sorted(readings)],
                               "lists": [{"n": n, "label": labels[n]} for n in sorted(labels)]}})
    await _narrow(entry, p, ask)
    unread = any(s["state"] != "ready" for s in entry["slots"]) or any(l["state"] != "ready" for l in entry["lists"])
    entry["reading"] = bool(unread or entry.get("narrow_pending"))
    return entry


def _marked(parsed: Parsed) -> List[Tuple[str, int, Segment]]:
    out, s, l = [], 0, 0
    for seg in parsed.segments:
        if seg.kind == "slot":
            s += 1
            out.append(("slot", s, seg))
        elif seg.kind == "list":
            l += 1
            out.append(("list", l, seg))
    return out


async def _narrow(entry: Dict[str, Any], p: _Prompt, ask: Any) -> None:
    """Narrow the entry's bound picks by their slots' words. A stated detail whose narrowing
    isn't there (not asked yet, or its answer didn't come back) stands as the user's words;
    a list slot narrowed by its words stands as its words. Nothing else waits for it."""
    from prompt_programs.narrow import NARROW_SECONDS, NarrowCache, narrow_entry
    if not entry["picks"]:
        return
    await narrow_entry(entry, NarrowCache(p.store.root / "narrow"), ask, p.project_id, seconds=NARROW_SECONDS)
    pending = set(entry.get("narrow_pending") or {})
    words = entry.get("slot_words") or {}
    picks = {x["id"]: x for x in entry["picks"]}
    choices = {c["id"]: c for c in entry["choices"]}
    for s in entry["slots"]:
        form = s.get("form") or {}
        if form.get("kind") == "person":
            for cid in form["keys"]:
                if cid in pending and cid in words:
                    # (said=: drawn as typed, the rest of the list held for the picker)
                    picks[cid]["said"] = choices[cid]["said"] = words[cid]
                    choices[cid]["options"] = list(dict.fromkeys([words[cid], *(choices[cid].get("options") or [])]))
        elif form.get("kind") == "one" and form["id"] in pending and form["id"] in words and picks[form["id"]].get("cls"):
            s["typed"] = True
    typed = {d for s in entry["slots"] if s.get("typed") for d in s["details"]}
    if typed:
        entry["picks"] = [x for x in entry["picks"] if x["id"] not in typed]


def _working(p: _Prompt) -> bool:
    return (p.root, p.key) in _settling or any((p.root, key) in _reads for _, _, key in p.parts())


def _start(p: _Prompt, force: bool = False) -> None:
    """Read whatever of the prompt isn't read yet, each part on its own, and settle the prompt
    once each lands. Returns at once."""
    import asyncio
    from prompt_programs.reader import cached
    readings, labels = cached(p.parsed, p.model, p.cache()) if not force else ({}, {})
    started = False
    for kind, n, key in p.parts():
        if n in (readings if kind == "slot" else labels):
            continue
        flight = (p.root, key)
        if flight in _reads:
            continue
        _failed.pop(flight, None)
        task = asyncio.ensure_future(_read_job(p, kind, n, key))
        _reads[flight] = task
        task.add_done_callback(lambda t, k=flight: _reads.pop(k, None) if _reads.get(k) is t else None)
        started = True
    if not started and not any((p.root, key) in _reads for _, _, key in p.parts()):
        _settle(p)


async def _read_job(p: _Prompt, kind: str, n: int, key: str) -> None:
    from prompt_programs import program as prep
    from prompt_programs import reader
    from core.logging import get_logger
    flight = (p.root, key)
    try:
        got = await reader.read_part(p.parsed, kind, n, ask=prep.ask_model, project_id=p.project_id, model=p.model,
                                     cache=p.cache())
        if (kind == "slot" and got.get("degraded")) or (kind == "list" and not got):
            _failed[flight] = str(got.get("reason") or "") if kind == "slot" else "no label"
    except Exception as e:   # a model slip or an unreachable model never stops a run: the part stands as written
        get_logger(__name__).warning(f"[slots] reading part {n} of {p.key} failed: {e}")
        _failed[flight] = str(e)[:200] or type(e).__name__
    finally:
        _reads.pop(flight, None)
        _settle(p)


def _settle(p: _Prompt) -> None:
    """Narrow the prompt with the model and start its option pools, in the background; one at a
    time per prompt, run once more when something lands meanwhile."""
    import asyncio
    flight = (p.root, p.key)
    if flight in _settling:
        _again.add(flight)
        return

    async def run() -> None:
        from prompt_programs import program as prep
        from core.logging import get_logger
        try:
            while True:
                _again.discard(flight)
                try:
                    entry = await _assemble(p, prep.ask_model)
                    p.store.put(p.key, entry)
                    prep.on_prepared(entry, project_id=p.project_id, profile_id=p.profile_id)
                except Exception as e:
                    get_logger(__name__).warning(f"[slots] settling {p.key} failed: {e}")
                if flight not in _again:
                    return
        finally:
            _settling.pop(flight, None)

    _settling[flight] = asyncio.ensure_future(run())


async def prepare(prompt: str, *, profile_id: Optional[str], project_id: Optional[int] = None,
                  start: bool = True, force: bool = False) -> Dict[str, Any]:
    """The prompt's entry now: every slot and list from the parse, each `ready` with its reading
    or still `reading`. Never waits on a model. `start` reads what isn't read yet in the
    background (`force`: everything again); `reading` says something is still out, `working`
    that background work for it is running. A prompt with nothing that varies:
    {"key": None, "slots": [], "choices": []}."""
    p = await _read_prompt(prompt, profile_id, project_id)
    if p is None:
        return {"key": None, "slots": [], "choices": []}
    entry = await _assemble(p, None)
    # A part read as written, or whose call failed, is read again by the next prepare that starts work.
    again = any((p.root, key) in _failed for _, _, key in p.parts())
    if start and (entry["reading"] or again or force):
        _start(p, force)
    entry["working"] = _working(p)
    p.store.put(p.key, entry)
    return entry


current = prepare   # what a generation draws from: the same, never waiting


async def idle() -> None:
    """Wait for every background reading and settling to finish (tests, scripts)."""
    import asyncio
    while _reads or _settling:
        await asyncio.gather(*list(_reads.values()), *list(_settling.values()), return_exceptions=True)


def preparing() -> bool:
    """Whether any part is being read now (background option writing gives way to it)."""
    return bool(_reads)


def raw_spans(prompt: str, entry: Dict[str, Any]) -> List[Optional[Tuple[Span, int]]]:
    """Each slot's span and line in the prompt as the user typed it (the entry's are in the
    prompt as parsed: saved wildcards filled in, exact text masked). None for every slot when
    the two don't hold the same slots (a segment inlined with slots of its own)."""
    found = find_slots(prompt)
    slots = entry.get("slots") or []
    if len(found) != len(slots) or any(prompt[a + 1:b - 1] != s.get("words") for (a, b), s in zip(found, slots)):
        return [None for _ in slots]
    return [((a, b), prompt.count("\n", 0, a) + 1) for a, b in found]


__all__ = ["KINDS", "Parsed", "ReadingError", "SLOT_RE", "SLOTS_VERSION", "Segment", "build", "compose", "current",
           "find_slots", "idle", "is_comment", "parse", "prepare", "preparing", "raw_spans", "slot_ids", "unwrap_slots"]

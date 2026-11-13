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


def build(parsed: Parsed, readings: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """The program for a parsed prompt and its slot reading (reader.py's reply, checked):
    one statement per pick, one emit() in the prompt's order. Returns the source and the
    entry the runtime draws from (`slot_words` still to be narrowed: narrow.narrow_entry)."""
    from prompt_programs.people import DETAILS, expand_people
    from prompt_programs.runtime import discover
    from prompt_programs.vocab import vocabulary

    vocab = vocabulary()
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
    outfit_at = None   # the parts index of a person's outfit, until the text after it is seen
    for seg in parsed.segments:
        if outfit_at is not None:
            # Words right after the outfit ("... jeans reading on a porch") are set off by a comma
            # that goes with the outfit; punctuation, a line's end or another mark need none.
            if seg.kind == "text" and re.match(r"[ \t]*\w", seg.text):
                parts[outfit_at] = parts[outfit_at][:-1] + ", ',')"
            outfit_at = None
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
        if kind == "person":
            flush()
            vary = [d for d in got.get("vary") or [] if d in DETAILS]
            stated = {d: str(w) for d, w in (got.get("stated") or {}).items() if d in DETAILS and str(w).strip()}
            presentation = got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else None
            stmts.append(f"{var} = " + _call("person", cid, noun=str(got.get("noun") or "person"), presentation=presentation,
                                             show=vary, article=False))
            parts.append(var)
            for d, w in stated.items():
                slot_words[f"{cid}.{d if d in vary or d != 'age' else 'stated_age'}"] = w
            info["stated"] = stated
            outfit = got.get("outfit") or ""
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
                parts.append(_opt(repr(", wearing"), f"{var}_outfit"))
                outfit_at = len(parts) - 1
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
                stmts.append(f"{var} = " + _call("pick", cid, cls=listed(got.get("list"), label), about=seg.words,
                                                 label=label, phase=1))
                if str(got.get("stated") or "").strip():
                    slot_words[cid] = str(got["stated"])
            else:
                kinds = _strings(got.get("kinds") or [], "kinds")
                instead = _strings(got.get("instead") or [], "instead")
                stmts.append(f"{var} = " + _call("pick", cid, about=str(got.get("about") or seg.words), seed=kinds,
                                                 zones={"kinds": kinds, "instead": instead}, label=label, phase=2))
                slot_words[cid] = seg.words
                info["zones"] = {"kinds": kinds, "instead": instead}
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


# --------------------------------------------------------------------------- prepared and stored

SLOTS_VERSION = "slots-1"

_in_flight: Dict[Tuple[str, str], Any] = {}


async def ensure(prompt: str, *, profile_id: Optional[str], project_id: Optional[int] = None,
                 cache_only: bool = False, force: bool = False) -> Optional[Dict[str, Any]]:
    """The slot program for a prompt: from the store, or parsed, read (reader.py), built,
    narrowed and stored. None for a cache_only lookup of a prompt not prepared yet. A prompt
    with no slots and no lists has no program: {"key": None, "slots": [], "choices": []}.
    Raises reader.ReaderFailed when the chat model's reading can't be used, and
    narrow.NarrowFailed when a slot's words couldn't be read into its lists: nothing draws
    from a list its words narrow before they have narrowed it."""
    import asyncio

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
        return {"key": None, "slots": [], "choices": []}
    model = await prep.model_fingerprint(project_id)
    key = program_key({"v": SLOTS_VERSION, "reader": READER_VERSION, "model": model, "vocab": vocabulary().version,
                       "prompt": masked, "exact": exact})
    store = prep.store_for(profile_id)
    cached = None if force else store.get(key)
    if cached and not cached.get("narrow_pending"):
        return cached
    if cache_only:
        return None
    flight = (str(store.root), key)
    running = None if force else _in_flight.get(flight)
    if running is None:
        # A stored entry whose narrowing didn't finish (an older build stored those) is narrowed now.
        running = asyncio.ensure_future(_narrow_stored(cached, store=store, profile_id=profile_id, project_id=project_id)
                                        if cached else
                                        _prepare(parsed, key=key, exact=exact, model=model, store=store,
                                                 profile_id=profile_id, project_id=project_id, force=force))
        _in_flight[flight] = running
        running.add_done_callback(lambda t, k=flight: _in_flight.pop(k, None) if _in_flight.get(k) is t else None)
    return await asyncio.shield(running)


async def _prepare(parsed: Parsed, *, key: str, exact: Dict[str, str], model: Optional[str], store: Any,
                   profile_id: Optional[str], project_id: Optional[int], force: bool) -> Dict[str, Any]:
    import time

    from prompt_programs import program as prep
    from prompt_programs import reader
    from prompt_programs.narrow import NarrowCache

    t0 = time.monotonic()
    reading = await reader.read(parsed, ask=prep.ask_model, project_id=project_id, model=model,
                                cache=NarrowCache(store.root / "reader"), force=force)
    source, entry = build(parsed, reading)
    entry.update({"key": key, "exact": exact, "reading": reading, "source": source, "version": SLOTS_VERSION,
                  "created_at": time.time()})
    await _narrow(entry, store, profile_id, project_id)
    entry["seconds"] = round(time.monotonic() - t0, 2)
    store.put(key, entry)
    prep.on_prepared(entry, project_id=project_id, profile_id=profile_id)
    return entry


async def _narrow_stored(entry: Dict[str, Any], *, store: Any, profile_id: Optional[str],
                         project_id: Optional[int]) -> Dict[str, Any]:
    from prompt_programs import program as prep
    from prompt_programs.narrow import reopen_pending

    reopen_pending(entry)
    await _narrow(entry, store, profile_id, project_id)
    store.put(entry["key"], entry)
    prep.on_prepared(entry, project_id=project_id, profile_id=profile_id)
    return entry


async def _narrow(entry: Dict[str, Any], store: Any, profile_id: Optional[str], project_id: Optional[int]) -> None:
    """Narrow the entry's picks by their words, waiting for every answer, then draw its example
    from the narrowed lists. Raises NarrowFailed when any narrowing didn't finish."""
    from prompt_programs import program as prep
    from prompt_programs.narrow import NARROW_SECONDS, NarrowCache, NarrowFailed, narrow_entry
    from core.logging import get_logger

    await narrow_entry(entry, NarrowCache(store.root / "narrow"), prep.ask_model, project_id, seconds=NARROW_SECONDS)
    left = sorted(entry.get("narrow_pending") or {})
    if left:
        named = ", ".join(sorted({str(k).split("\x00", 1)[0] for k in left}))
        raise NarrowFailed(f"The chat model's reading of what the slots' words allow didn't finish ({named}). "
                           "Try again, or use Direct.")
    try:   # the example the editor shows is drawn as a run would draw it: from the narrowed lists
        entry["example"] = prep.realize(entry, seed=0, profile_id=profile_id, project_id=project_id).prompt
    except Exception as e:
        get_logger(__name__).warning(f"[slots] drawing the example of {entry.get('key')} failed: {e}")
        entry["example"] = None


def preparing() -> bool:
    """Whether any prompt is being read now (background option writing gives way to it)."""
    return bool(_in_flight)


def raw_spans(prompt: str, entry: Dict[str, Any]) -> List[Optional[Tuple[Span, int]]]:
    """Each slot's span and line in the prompt as the user typed it (the entry's are in the
    prompt as parsed: saved wildcards filled in, exact text masked). None for every slot when
    the two don't hold the same slots (a segment inlined with slots of its own)."""
    found = find_slots(prompt)
    slots = entry.get("slots") or []
    if len(found) != len(slots) or any(prompt[a + 1:b - 1] != s.get("words") for (a, b), s in zip(found, slots)):
        return [None for _ in slots]
    return [((a, b), prompt.count("\n", 0, a) + 1) for a, b in found]


__all__ = ["KINDS", "Parsed", "ReadingError", "SLOT_RE", "SLOTS_VERSION", "Segment", "build", "ensure", "find_slots",
           "is_comment", "parse", "preparing", "raw_spans", "slot_ids", "unwrap_slots"]

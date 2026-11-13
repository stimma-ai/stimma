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

from core.logging import get_logger

log = get_logger(__name__)

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


# --------------------------------------------------------------------------- composing an entry

def slot_ids(parsed: Parsed) -> List[str]:
    """Each slot's id: its words slugged, the second slot with the same words `_2`. Only an
    identifier: nothing decides anything by it."""
    used = {f"list{i}" for i in range(1, len(parsed.lists()) + 1)}
    out: List[str] = []
    for s in parsed.slots():
        # ASCII and starting with a letter: whose detail a pick is, is read from its id (fill.person_of).
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
# A part the edit check said an edit changed: read again, not checked again.
_changed: set = set()


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
    # The prepared prompt the editor shows now (its key), whose readings stand for this prompt's
    # parts until they are checked or read.
    shown: Optional[str] = None

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


def _key(model: Optional[str], masked: str, exact: Dict[str, str]) -> str:
    from prompt_programs.reader import READER_VERSION
    from prompt_programs.store import program_key
    from prompt_programs.vocab import vocabulary
    return program_key({"v": SLOTS_VERSION, "reader": READER_VERSION, "model": model, "vocab": vocabulary().version,
                        "prompt": masked, "exact": exact})


async def _read_prompt(prompt: str, profile_id: Optional[str], project_id: Optional[int],
                       shown: Optional[str] = None) -> Optional[_Prompt]:
    """The prompt as parsed for reading, or None when nothing in it varies."""
    from prompt_pipeline import _profile_wildcards_and_segments
    from prompt_programs import program as prep

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
    return _Prompt(prompt, parsed, masked, exact, _key(model, masked, exact), model, prep.store_for(profile_id),
                   profile_id, project_id, shown)


def _earlier(p: _Prompt) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """The readings this prompt's parts had in the prompt last prepared as this one, then in the
    one the editor shows: per (kind, number), a slot's reading or a list's {"label"}, each with
    "seen", what it was read in (reader.seen_in, and for a slot the prompt its options were
    written for). A part is the same part when its words are, in the same order among the
    others (an edit adds, removes or moves parts around it). Read by the same reader, model and
    vocabulary only; a reading that couldn't be used is never carried."""
    from difflib import SequenceMatcher
    from prompt_programs.reader import seen_in
    out: Dict[Tuple[str, int], Dict[str, Any]] = {}
    keys = list(dict.fromkeys(k for k in (p.key, p.shown) if k))
    new = _marked(p.parsed)

    def token(kind: str, seg: Segment) -> Tuple[str, str]:
        return kind, seg.words if kind == "slot" else seg.text
    for key in keys:
        try:
            prev = p.store.get(key)
            # the same reader, model and vocabulary: its key is this prompt's key for its own text
            if not prev or prev.get("key") != key or _key(p.model, str(prev.get("prompt") or ""),
                                                          prev.get("exact") or {}) != key:
                continue
            parsed = parse(str(prev["prompt"]))
            got = prev.get("readings") or {}
            readings = {r.get("n"): r for r in got.get("slots") or [] if isinstance(r, dict)}
            labels = {x.get("n"): x for x in got.get("lists") or [] if isinstance(x, dict)}
            written = str(prev.get("context") or "").strip() or str(prev.get("template") or "")
        except Exception as e:   # an unreadable earlier entry only means nothing is carried from it
            log.debug(f"[slots] no readings carried from {key}: {e}")
            continue
        old = _marked(parsed)
        match = SequenceMatcher(None, [token(k, sg) for k, _, sg in old], [token(k, sg) for k, _, sg in new],
                                autojunk=False)
        for a, b, size in match.get_matching_blocks():
            for i in range(size):
                kind, was, seg = old[a + i]
                now = (kind, new[b + i][1])
                if now in out:
                    continue
                if kind == "slot":
                    r = readings.get(was)
                    if not isinstance(r, dict) or r.get("degraded"):
                        continue
                    seen = r["seen"] if isinstance(r.get("seen"), dict) else {**seen_in(parsed, seg), "template": written}
                    out[now] = {**{k: v for k, v in r.items() if k != "n"}, "seen": seen}
                else:
                    x = labels.get(was)
                    if not x or not str(x.get("label") or "").strip():
                        continue
                    out[now] = {"label": str(x["label"]),
                                "seen": x["seen"] if isinstance(x.get("seen"), dict) else seen_in(parsed, seg)}
    return out


async def _assemble(p: _Prompt, ask: Any) -> Dict[str, Any]:
    """The prompt's entry from its parse and the readings cached, narrowed with `ask` (None:
    from the cache only, which never calls a model)."""
    from prompt_programs.reader import as_written, cached
    readings, labels = cached(p.parsed, p.model, p.cache())
    segs = {(kind, n): seg for kind, n, seg in _marked(p.parsed)}
    # A part read before an edit keeps its reading until it is checked or read again.
    unread = [(kind, n) for kind, n, _ in p.parts() if n not in (readings if kind == "slot" else labels)]
    earlier = _earlier(p) if unread else {}
    carried = [k for k in unread if k in earlier]
    list_seen: Dict[int, Any] = {}
    for kind, n in carried:
        if kind == "slot":
            readings[n] = {**earlier[(kind, n)], "n": n}
        else:
            labels[n] = earlier[(kind, n)]["label"]
            list_seen[n] = earlier[(kind, n)]["seen"]
    for kind, n, key in p.parts():
        why = _failed.get((p.root, key))
        if why is None:
            continue
        if kind == "slot" and n not in readings:
            readings[n] = as_written(n, segs[("slot", n)], why)
        elif kind == "list" and n not in labels:
            labels[n] = ""
    entry = compose(p.parsed, readings, labels)
    # A reading carried from before an edit, or kept through one, says what it was read in: its
    # narrowing is read in that and its options are the ones written for it there.
    for s in entry["slots"]:
        seen = (readings.get(s["n"]) or {}).get("seen")
        if isinstance(seen, dict):
            s["seen"] = seen
    for x in entry["lists"]:
        if x["n"] in list_seen:
            x["seen"] = list_seen[x["n"]]
    entry.update({"key": p.key, "version": SLOTS_VERSION, "exact": p.exact, "typed": p.typed,
                  "readings": {"slots": [readings[n] for n in sorted(readings)],
                               "lists": [{"n": n, "label": labels[n], **({"seen": list_seen[n]} if n in list_seen else {})}
                                         for n in sorted(labels)]}})
    await _narrow(entry, p, ask)
    pending = any(s["state"] != "ready" for s in entry["slots"]) or any(l["state"] != "ready" for l in entry["lists"])
    # (a carried reading is ready, but the edit is still to be checked)
    entry["reading"] = bool(pending or carried or entry.get("narrow_pending"))
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
    from prompt_programs.reader import cached, seen_in
    readings, labels = cached(p.parsed, p.model, p.cache()) if not force else ({}, {})
    earlier = _earlier(p) if not force else {}
    segs = {(kind, n): seg for kind, n, seg in _marked(p.parsed)}
    started = False
    check: List[Tuple[str, int, str, Dict[str, Any], Dict[str, Any]]] = []
    for kind, n, key in p.parts():
        if n in (readings if kind == "slot" else labels):
            continue
        flight = (p.root, key)
        if flight in _reads:
            continue
        _failed.pop(flight, None)
        was = earlier.get((kind, n))
        if was is not None and flight not in _changed:
            now = seen_in(p.parsed, segs[(kind, n)])
            if (was["seen"].get("marked"), list(was["seen"].get("notes") or [])) == (now["marked"], now["notes"]):
                _carry(p, kind, key, was)   # read in this very line and notes: nothing to ask
            else:
                check.append((kind, n, key, was, now))
            continue
        _read(p, kind, n, key)
        started = True
    if check:
        task = asyncio.ensure_future(_check_job(p, check))
        for _, _, key, _, _ in check:
            flight = (p.root, key)
            _reads[flight] = task
            task.add_done_callback(lambda t, k=flight: _reads.pop(k, None) if _reads.get(k) is t else None)
        started = True
    if not started and not any((p.root, key) in _reads for _, _, key in p.parts()):
        _settle(p)


def _read(p: _Prompt, kind: str, n: int, key: str) -> None:
    import asyncio
    flight = (p.root, key)
    task = asyncio.ensure_future(_read_job(p, kind, n, key))
    _reads[flight] = task
    task.add_done_callback(lambda t, k=flight: _reads.pop(k, None) if _reads.get(k) is t else None)


def _carry(p: _Prompt, kind: str, key: str, was: Dict[str, Any]) -> None:
    """Keep a part's earlier reading as its reading here, with what it was read in."""
    p.cache().put_raw(key, was if kind == "slot" else was["label"])


async def _check_job(p: _Prompt, parts: List[Tuple[str, int, str, Dict[str, Any], Dict[str, Any]]]) -> None:
    """Ask once whether an edit changes the parts read before it. The ones it doesn't keep their
    readings, with no more calls; the others are read again, their earlier readings standing
    meanwhile. A failed check or a reply that can't be used reads them all again."""
    from prompt_programs import program as prep
    from prompt_programs.reader import changed_parts
    items = [{"words": _words(p, kind, n), "reading": was, "before": was["seen"], "now": now}
             for kind, n, _, was, now in parts]
    try:
        changed = await changed_parts(items, ask=prep.ask_model, project_id=p.project_id)
    except Exception as e:   # never stops a run: they are read again
        log.warning(f"[slots] checking an edit of {p.key} failed: {e}")
        changed = None
    again = set(range(1, len(parts) + 1)) if changed is None else changed
    kept = 0
    for i, (kind, n, key, was, _) in enumerate(parts, 1):
        if i in again:
            continue
        try:
            _carry(p, kind, key, was)
            kept += 1
        except Exception as e:
            log.warning(f"[slots] keeping a reading of {p.key} failed: {e}")
            again.add(i)
        _reads.pop((p.root, key), None)
    log.info(f"[slots] an edit of {p.key}: {kept} part(s) keep their readings, {len(again)} read again"
             + (" (the check couldn't be used)" if changed is None else ""))
    for i, (kind, n, key, _, _) in enumerate(parts, 1):
        if i in again:
            _changed.add((p.root, key))
            _read(p, kind, n, key)
    _settle(p)


def _words(p: _Prompt, kind: str, n: int) -> str:
    seg = next(seg for k, m, seg in _marked(p.parsed) if (k, m) == (kind, n))
    return seg.words if kind == "slot" else seg.text


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
        else:
            _changed.discard(flight)
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
                  start: bool = True, force: bool = False, shown: Optional[str] = None) -> Dict[str, Any]:
    """The prompt's entry now: every slot and list from the parse, each `ready` with its reading
    or still `reading`. Never waits on a model. `start` reads what isn't read yet in the
    background (`force`: everything again); `reading` says something is still out, `working`
    that background work for it is running. `shown`: the key of the prepared prompt the editor
    shows now; a part it has (the same words, in the same order among the others) is ready with
    its reading there while an edit is checked, and only a part new to it is `reading`. A prompt
    with nothing that varies: {"key": None, "slots": [], "choices": []}."""
    p = await _read_prompt(prompt, profile_id, project_id, shown)
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


__all__ = ["Parsed", "SLOT_RE", "SLOTS_VERSION", "Segment", "compose", "current", "find_slots", "idle", "is_comment",
           "parse", "prepare", "preparing", "raw_spans", "slot_ids", "unwrap_slots"]

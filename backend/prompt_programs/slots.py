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
from typing import Any, Dict, List, Tuple

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
        base = re.sub(r"\W+", "_", s.words.lower()).strip("_") or "slot"
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
    for seg in parsed.segments:
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
                    stmts.append(f"{var}_outfit = " + _call("pick", f"{cid}.outfit", about=about, label="Outfit", phase=2))
                else:
                    stmts.append(f"{var}_outfit = " + _call("pick", f"{cid}.outfit", cls=listed(outfit, label),
                                                            about=about, label="Outfit", phase=2))
                parts.append(_opt(repr(", wearing"), f"{var}_outfit"))
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

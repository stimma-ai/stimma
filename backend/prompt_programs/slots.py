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
from typing import List, Tuple

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
    for n, line in enumerate(text.split("\n")):
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
    line: int                  # 0-based
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
        if n:
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

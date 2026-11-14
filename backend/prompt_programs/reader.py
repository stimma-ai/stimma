"""The slot reader: a model call that says what one slot of a prompt is and how it varies.

    an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening

The model sees the prompt with its slots and lists numbered in place (⟨1: elderly African
man⟩, {L1: summer|autumn}) and replies with plain JSON: per slot its kind, a label, its lead and
what it needs; per list a label. The kinds besides the engine's list and free (a person, an
animal, a camera, light, a pack's own) are vocabulary data (vocab/kinds/*.json): the prompt is
composed from each kind's reader part, and its reply is checked against the kind's questions.
Code checks only the reply's structure (numbers, kinds, list ids, details, declared answers,
exact copies of the user's words) and never reads the slot's words to decide anything. Each part is asked on its own, the whole
prompt shown. A reply that fails the checks gets one retry told what was wrong; then the part
is read as written, never cached.

Cached on disk per part, by its own words, its line and the prompt's comment lines. A part read
before an edit keeps its reading while one small call for all the parts the edit touched
(changed_parts) asks whether the edit changes it: the parts on the edited line, and when the edit
is elsewhere in the prompt (the scene its variants were written for), the parts on other lines
too. Only the parts it changes are read again, and a part read again for its scene gets a pool
of its own (slots.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.slots import Parsed, Segment

log = get_logger(__name__)

READER_VERSION = "reader-23"   # reader-23: kinds are vocabulary data; a person says what sort of being they are (a declared sort, or "other") instead of whether a heritage applies, and a place may be any context table's. reader-22: a person names the place by its country's plain name, asked again when the table lacks it; a person says how many people they are (one, a couple, a family, a group) and whether a real-world heritage applies to them; light names the scene list unless its words call for a named look. reader-21: a person names the country the picture is set in (place), when the prompt says. reader-20: a person keeps the words saying what they wear (clothes), so their variants draw no outfit; a free part no longer gives kinds or things instead, nor a light examples (nothing used them). reader-19: a person no longer says whether their face varies or writes outfits (variants do); every part names its category word (the run of its words a kind of it may replace; none for a person), and a free part names up to three lists that could seed it. reader-18: a person says which other part is what they wear (clothes_part) and then draws no outfit; a person varies some of their fixed details, else it is words about someone (an expression) and is retried, then stands as written; a garment no list holds kinds of is free. reader-17: a camera that varies one detail is a list slot on that detail's list; words naming the whole camera vary all four. reader-16: an animal says the kind the words call for ("pet"). reader-15: hair is length, texture and color, a hairstyle starts left out, and every directory's lists are offered. reader-14: a coat list is a breed list. reader-13: a young animal's word states its life stage. reader-12: light names its looks; a person with no outfit says what the prompt says they wear. reader-11: a list about a person says how they present; face is its own true/false, only when asked for. reader-9: animals are a builder; light may name a lighting list. reader-8: each part is read on its own. reader-7: a free slot gives things instead only when something naturally stands there. reader-6: the example's prompt is shown; only the numbered parts are parts, and the message names them. reader-5: a part about someone the prompt has is never a person (worked tag example; the noun is copied); a list says what it is about. reader-4: a stated detail is always drawn; a person with nothing to draw is retried. reader-3: a part of a person is not a person; leads are joining words; descent is usual. reader-2: each kind's object is shown

Ask = Callable[[List[Dict[str, Any]], Optional[int], int], Awaitable[str]]

# A reading's reply budget: a couple of hundred tokens a part is room enough with no reasoning
# (a person, the longest, is about 120), and a runaway reply stops in seconds instead of minutes.
READING_TOKENS, SLOT_TOKENS = 200, 250

class ReaderFailed(Exception):
    """The chat model's reading of the slots couldn't be used, after one retry."""
    code = "reader_failed"


HEAD = """You read the parts of an image prompt that should change from image to image. The user marked
each one with angle brackets; you see them numbered, as ⟨1: words⟩. The user's own lists of
options are numbered too, as {L1: summer|autumn}. Lines starting with # are notes from the user
about the image: read them as context for every part. Text shown as [EXACT_1] is the user's
exact text, hidden from you.

For each numbered part, say what it is and how it varies. Only the numbered parts change: the
words outside them stay as the user wrote them, and are never a part, even when they name a
person. Reply with JSON only, with nothing
before or after it, in the shape shown at the end. Each part's own fields go in an object named
after its kind: {objects}."""

# The engine's own two kinds: a slot bound to one list, and anything else.
ENGINE_RECOGNIZE = """- "list": something one of the lists below holds: the list's items are kinds of the very thing
  the words name, not of something like it, and its description names that thing. Give its
  id. Clothes most of all: "⟨boots⟩" is a footwear list, but a garment that no list's
  description names ("⟨scrubs⟩", "⟨ballet costume⟩", "⟨diving suit⟩") is "free", never the
  nearest list of outfits, coats or dresses.
- "free": anything else. Options will be written for it."""

ENGINE_SECTIONS = """For a list: list (its id) and about (what it is in this image, and whose, in a few words, with
what the prompt and notes say of them: "the girl's hairstyle", "a middle-aged man's hairstyle",
"his pet, on the porch"). The part's words and the about decide which of the list's items fit.
When it is about a person whose words or the notes say how they present ("1boy", "a woman"),
presentation: "feminine" or "masculine"; else "".
  "list": {"list": "<the list's id>", "about": "...", "presentation": ""}

For free: about (what it is in this image, a few words) and lists: up to three ids of the
lists below whose items could be kinds or details of it in this picture, best first; [] when
none could."""

EVERY_PART = """For every part:
- label: two or three words naming it for a menu.
- category: the word or words of the part that only name what kind of thing it is, so that a
  more specific kind of it could take their place and still be that thing; every other word
  describes it and stays. Copied exactly from the part's words: "clothing" in "clothing
  slightly open in the front" (a cardigan slightly open in the front), "camera angle" in
  "selfie camera angle", "lighting" in "lighting", "expression" in "silly expression", "camera"
  in "vintage camera", "dog" in "dog".{no_category}
- lead: when this part is left out of the prompt, the words right before it that would be left
  hanging without it, copied exactly: ", lit by" in "a kitchen, lit by ⟨light⟩"; " with a" in
  "a desk with a ⟨lamp⟩"; "," in "red car, ⟨camera⟩". Only joining words, articles and the
  punctuation before them, never a word that names or describes something else. "" when nothing
  would hang ("⟨old man⟩ in a kitchen").

For each numbered list {Ln: ...}: a label of one or two words."""


def _choice_text(q: Any, vocab: Any) -> str:
    """A choice question's bullet: its ask, then its options with their texts when they have any
    ("one" (one person: ...), ... or "group" (...)); a list's facet's parts fill {options}."""
    if q.options_from[0]:
        return q.ask.replace("{options}", ", ".join(f'"{t}"' for t in q.answers(vocab)))
    if not any(o.text for o in q.options):
        return q.ask
    opts = [f'"{o.answer}" ({o.text})' if o.text else f'"{o.answer}"' for o in q.options]
    return f"{q.ask}: " + (", ".join(opts[:-1]) + " or " + opts[-1] if len(opts) > 1 else opts[0]) + "."


def _question_text(q: Any, vocab: Any) -> List[str]:
    if q.type == "choice":
        text = _choice_text(q, vocab)
    elif q.type == "context":
        asks = [t.ask for t in sorted(vocab.tables.values(), key=lambda t: (not t.user_default, t.id))
                if t.ask and (not q.tables or t.id in q.tables)]
        text = " ".join([*asks, q.none]).strip()
    else:
        text = q.ask
    return ([f"- {q.key}: {text}"] if text else []) + [f"- {m}" for m in q.more]


def _section(k: Any, vocab: Any) -> str:
    lines: List[str] = []
    if k.text:
        lines.append(f"{k.heading} {k.text}".strip())
    else:
        lines.append(k.heading)
        for q in k.questions:
            lines += _question_text(q, vocab)
    if k.example is not None:
        lines.append(f'  "{k.id}": ' + json.dumps(k.example, ensure_ascii=False))
    return "\n".join(lines)


def system_text() -> str:
    """The reader's system prompt, composed from the engine's framing and every declared kind
    (vocab/kinds/*.json reader parts) in the kinds' order."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    kinds = vocab.ordered_kinds()
    names = [*(k.id for k in kinds), "list", "free"]
    objects = ", ".join(f'"{x}": {{...}}' for x in names[:-1]) + f' or "{names[-1]}": {{...}}'
    recognize = []
    for k in kinds:
        recognize.append(f'- "{k.id}": {k.recognize[0]}')
        recognize += [f"- {x}" for x in k.recognize[1:]]
    sections = [_section(k, vocab) for k in kinds]
    no_cat = "".join(" " + k.category for k in kinds if k.category)
    details = [f"{k.details_heading}\n" + "\n".join(f"- {d.name}: {d.about}" for d in k.details.values() if d.reader)
               for k in kinds if k.details_heading]
    examples = []
    for k in kinds:
        for e in k.examples:
            reply = json.dumps(e["reply"], ensure_ascii=False, indent=e.get("indent")) if e.get("indent") \
                else json.dumps(e["reply"], ensure_ascii=False)
            examples.append(f'{e["intro"]}\n{reply}')
    parts = [HEAD.replace("{objects}", objects), "kind:\n" + "\n".join(recognize) + "\n" + ENGINE_RECOGNIZE,
             *sections, ENGINE_SECTIONS, EVERY_PART.replace("{no_category}", no_cat), *details,
             "Lists:\n" + vocab.catalog(), *examples]
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- the prompt, numbered

def _marked(parsed: Parsed) -> List[Tuple[str, int, Segment]]:
    """("slot" | "list", its number, segment), in the prompt's order."""
    out, s, l = [], 0, 0
    for seg in parsed.segments:
        if seg.kind == "slot":
            s += 1
            out.append(("slot", s, seg))
        elif seg.kind == "list":
            l += 1
            out.append(("list", l, seg))
    return out


def _shown(kind: str, n: int, seg: Segment) -> str:
    return f"⟨{n}: {seg.words}⟩" if kind == "slot" else f"{{L{n}: {seg.text[1:]}"


def numbered(parsed: Parsed) -> str:
    """The prompt with each slot shown as ⟨n: words⟩ and each list as {Ln: a|b}."""
    numbers = {id(seg): (kind, n) for kind, n, seg in _marked(parsed)}
    return "".join(_shown(*numbers[id(seg)], seg) if id(seg) in numbers else seg.text for seg in parsed.segments)


def comment_lines(parsed: Parsed) -> List[str]:
    return [seg.text for seg in parsed.segments if seg.kind == "comment"]


def _line_with(parsed: Parsed, seg: Segment) -> str:
    """The segment's line, the segment itself marked: what a slot is read in besides the notes."""
    line = parsed.prompt.split("\n")[seg.line - 1]
    start = sum(len(x) + 1 for x in parsed.prompt.split("\n")[:seg.line - 1])
    a, b = seg.span[0] - start, seg.span[1] - start
    inner = seg.words if seg.kind == "slot" else seg.text
    return line[:a] + f"⟨{inner}⟩" + line[b:]


def leads(parsed: Parsed) -> Dict[int, str]:
    """Per slot number, the text before it on its line since the last slot or list: where its
    lead must come from."""
    out: Dict[int, str] = {}
    pending, n = "", 0
    for seg in parsed.segments:
        if seg.kind == "text":
            pending = (pending + seg.text).split("\n")[-1]
        elif seg.kind == "comment":
            pending = ""
        else:
            if seg.kind == "slot":
                n += 1
                out[n] = pending
            pending = ""
    return out


def _hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps([READER_VERSION, *parts], ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


def part_key(parsed: Parsed, seg: Segment, model: Optional[str], vocab_version: str) -> str:
    return _hash(seg.kind, model, vocab_version, seg.words if seg.kind == "slot" else seg.text,
                 _line_with(parsed, seg), comment_lines(parsed))


def user_message(parsed: Parsed, asked: Sequence[Tuple[str, int]]) -> str:
    marks = _marked(parsed)
    # named apart from the prompt's own marks (⟨1⟩ "pet"), so each part is shown in the prompt once
    shown = {(kind, n): f'⟨{n}⟩ "{seg.words}"' if kind == "slot" else f"{{L{n}}}" for kind, n, seg in marks}
    text = f"The prompt:\n{numbered(parsed)}"
    if list(asked) != [(kind, n) for kind, n, _ in marks]:
        text += "\n\nThe other parts are already read. Answer only for: "
    else:
        text += "\n\nAnswer for each of its parts: "
    text += ", ".join(shown[k] for k in asked) + "."
    return text


# --------------------------------------------------------------------------- checking a reply

class _Bad(ValueError):
    """What is wrong with a reply, said plainly to the model on the retry."""


def _json(reply: str) -> Dict[str, Any]:
    text = (reply or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        got = json.loads(text)
    except ValueError as e:
        raise _Bad(f"it isn't valid JSON ({e})") from None
    if not isinstance(got, dict):
        raise _Bad("it isn't a JSON object")
    return got


def _strings(v: Any, what: str) -> List[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise _Bad(f"{what} must be a list of strings")
    return [x.strip() for x in v if x.strip()]


def _copied(words: str, sources: Sequence[str]) -> bool:
    from prompt_programs.narrow import _span
    return any(_span(words, s) for s in sources)


def fit_lead(lead: str, before: str) -> Optional[str]:
    """A lead as it stands exactly at the end of `before` (the text before its slot on its line,
    as leads() gives it), so the fill can take it off whole: " with a" after "a table\nwith a "
    is "with a". None when its words don't end `before`; "" for no lead. Structure only."""
    core = lead.strip()
    if not core:
        return ""
    stem = before.rstrip()
    if not stem.endswith(core):
        return None
    start = len(stem) - len(core)
    space = len(lead) - len(lead.lstrip())   # the spacing the lead took with it, where there is some
    while space and start and stem[start - 1].isspace():
        start, space = start - 1, space - 1
    return stem[start:]


def one_detail(out: Dict[str, Any]) -> Dict[str, Any]:
    """A reading of a kind that reads one varied detail as a list slot (reader.single_detail:
    "list", the camera) on that detail's list: `<selfie camera angle>` is the camera angle list,
    narrowed by the slot's words, not a camera with one row to click through. Structure only: the
    count of details, never the slot's words."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    k = vocab.kind(out.get("kind"))
    if k is None or k.single_detail != "list":
        return out
    vary = (out.get(k.id) or {}).get("vary") or []
    d = k.details.get(vary[0]) if len(vary) == 1 else None
    leaf = vocab.get(d.list) if d is not None else None
    if leaf is None:
        return out
    return {"n": out["n"], "kind": "list", "label": out["label"], "lead": out["lead"],
            "list": {"list": leaf.id, "about": f"the {leaf.label.lower()}"}}


def _number(v: Any) -> int:
    """A part's number as a reply gives it (2 or "2"), else 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    return int(v.strip()) if isinstance(v, str) and v.strip().isdigit() else 0


def _list_answer(q: Any, v: Any, n: Any, vocab: Any) -> str:
    """A list question's answer: a list's id there is (under its prefix, not excluded), one of its
    extra answers, or "". One that names no list is asked again when the question says how (its
    `invalid`), else dropped."""
    lid = v.strip() if isinstance(v, str) else ""
    if not lid or lid in q.also:
        return lid
    ok = vocab.get(lid) is not None and (not q.under or lid.startswith(q.under + ".")) and lid not in q.exclude
    if ok:
        return lid
    if q.invalid:
        raise _Bad(q.invalid.replace("{n}", str(n)).replace("{value}", lid))
    return ""


def read_kind(k: Any, got: Dict[str, Any], n: Any, seg: Segment, before: str, notes: Sequence[str], prompt: str,
              strict: bool, others: Dict[int, str]) -> Dict[str, Any]:
    """A declared kind's object of a reading, checked against its questions (kinds.Question): words
    copied from the user's, declared answers, lists there are, another part's number, a context
    table's name; details stated and varied as the kind declares them. _Bad for what is asked
    again (said plainly to the model); anything else that fails is dropped."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    sources = {"part": [seg.words], "notes": list(notes), "before": [before], "prompt": [prompt]}
    ans: Dict[str, Any] = {}
    stated: Dict[str, str] = {}
    for q in k.questions:   # what the words state first: the details that vary depend on it
        if q.type == "stated":
            raw = got.get(q.key) if isinstance(got.get(q.key), dict) else {}
            stated = {d: w.strip() for d, w in raw.items()
                      if d in k.details and isinstance(w, str) and w.strip() and _copied(w, [seg.words, *notes])}
            ans[q.key] = stated
    for q in k.questions:
        v = got.get(q.key)
        if q.type == "words":
            w = v.strip() if isinstance(v, str) else ""
            ok = bool(w) and _copied(w, [x for src in q.sources for x in sources[src]])
            if q.required and not ok:
                raise _Bad(q.required.replace("{n}", str(n)).replace("{value}", w).replace("{words}", seg.words))
            ans[q.key] = w if ok else ""
        elif q.type == "choice":
            ans[q.key] = v if isinstance(v, str) and v in q.answers(vocab) else q.default
        elif q.type == "list":
            ans[q.key] = _list_answer(q, v, n, vocab)
        elif q.type == "part":
            num = _number(v)
            words = others.get(num) if num != n else None
            ans[q.key] = {"n": num, "words": words} if words is not None else None
        elif q.type == "context":
            # Counts only when it is exactly a name of a context table (places.place_for); one
            # otherwise ("rural Vietnam") is asked once more for the plain name, then left out.
            place = v.strip()[:80] if isinstance(v, str) else ""
            if place and vocab.context_named(place, q.tables) is None:
                if strict and q.invalid:
                    raise _Bad(q.invalid.replace("{n}", str(n)).replace("{value}", place))
                place = ""
            ans[q.key] = place
    for q in k.questions:
        if q.cleared_by and ans.get(q.cleared_by):
            ans[q.key] = ""   # another part is what they wear: no outfit of their own
    for q in k.questions:
        if q.type != "vary":
            continue
        vary = [d for d in dict.fromkeys(_strings(got.get(q.key), f"part {n}: {q.key}")) if d in k.details and d not in q.except_]
        if q.with_stated:
            # A detail the words state is drawn, within the words: left undrawn, the person would be
            # only their noun and the words would be lost ("young man" drawn as "a man").
            vary = list(dict.fromkeys([*vary, *stated]))
        def needs_ok(d: str) -> bool:
            need = k.details[d].needs if d in k.details else {}
            if need.get("answered") and not ans.get(need["answered"]):
                return False
            return not (need.get("unless_varied") and need["unless_varied"] in vary)
        vary = [d for d in vary if needs_ok(d)]
        if q.needs_one_of and not any(d in q.needs_one_of for d in vary):
            raise _Bad(q.needs_message.replace("{n}", str(n)) or f"part {n}: {q.key} needs some of {', '.join(q.needs_one_of)}")
        ans[q.key] = vary
    vary = next((ans[q.key] for q in k.questions if q.type == "vary"), [])
    for q in k.questions:
        if q.only_if_varies and q.only_if_varies not in vary:
            ans[q.key] = q.default if q.type == "choice" else ""
    req = k.require_one
    if strict and req and not any(ans.get(x) for x in req.get("of") or ()):
        raise _Bad(str(req["message"]).replace("{n}", str(n)))
    out: Dict[str, Any] = {}
    for q in k.questions:
        v = ans.get(q.key)
        default = q.default if q.type == "choice" else ""
        if q.always or (v not in (None, "", {}, []) and v != default):
            out[q.key] = v if v is not None else ""
    return out


def check_slot(r: Dict[str, Any], seg: Segment, before: str, notes: Sequence[str], prompt: str = "",
               strict: bool = True, others: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """One slot's reading as the seeds take it, or _Bad. Answers its kind doesn't allow, stated
    words that aren't the user's and a lead that isn't the text before the slot are dropped.
    `others`: the prompt's other slots, number -> words (what a part question may name)."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    n = r.get("n")
    kind = r.get("kind")
    names = vocab.kind_names()
    if kind not in names:
        raise _Bad(f"part {n}: kind must be one of {', '.join(names)}; a list's id goes in its object, as "
                   '"kind": "list", "list": {"list": "<the list\'s id>", "about": "..."}')
    got = r.get(kind)
    if not isinstance(got, dict):
        raise _Bad(f'part {n}: a {kind} needs its fields in a "{kind}" object, as "{kind}": {{...}}')
    lead = fit_lead(r.get("lead") if isinstance(r.get("lead"), str) else "", before) or ""
    out: Dict[str, Any] = {"n": n, "kind": kind, "label": str(r.get("label") or "").strip() or seg.words, "lead": lead}
    k = vocab.kind(kind)
    if k is not None:
        out[kind] = read_kind(k, got, n, seg, before, notes, prompt, strict, others or {})
        out = one_detail(out)
    elif kind == "list":
        lid = got.get("list")
        if not isinstance(lid, str) or vocab.get(lid) is None:
            raise _Bad(f'part {n}: list "{lid}" is not one of the lists (the id goes in "list": {{"list": "<id>", "stated": ""}})')
        about = got.get("about") if isinstance(got.get("about"), str) else ""
        out["list"] = {"list": lid, "about": about.strip() or seg.words}
        if got.get("presentation") in ("feminine", "masculine"):
            out["list"]["presentation"] = got["presentation"]
    else:
        lists = [x for x in dict.fromkeys(_strings(got.get("lists"), f"part {n}: lists")) if vocab.get(x) is not None]
        out["free"] = {"about": str(got.get("about") or "").strip() or seg.words, "lists": lists[:3]}
    # The words a kind of it may replace (variants.valid_category: a run of its own words, none
    # for a kind that keeps all its words); anything else is no category, and every word stays.
    from prompt_programs.variants import valid_category
    out["category"] = valid_category(seg.words, r.get("category"), out["kind"])
    return out


def check_parts(reply: str, parsed: Parsed, asked: Sequence[Tuple[str, int]], strict: bool = True
                ) -> Tuple[Dict[int, Any], Dict[int, str], Dict[Tuple[str, int], str]]:
    """The asked slots' readings and lists' labels that a reply gives in a usable form, and
    for each asked part it doesn't, what is wrong, said plainly. Never raises: one part's bad
    answer leaves the others' good ones standing."""
    want = list(asked)
    try:
        got = _json(reply)
    except _Bad as e:
        return {}, {}, {k: str(e) for k in want}
    if "slots" not in got and "kind" in got and "n" in got:
        got = {"slots": [got]}   # one part's reading, given bare rather than in "slots": the same answer
    marks = {(kind, n): seg for kind, n, seg in _marked(parsed)}
    want_slots = {n for kind, n in want if kind == "slot"}
    want_lists = {n for kind, n in want if kind == "list"}
    before, notes = leads(parsed), comment_lines(parsed)
    others = {m: seg.words for (kind, m), seg in marks.items() if kind == "slot"}
    slots: Dict[int, Any] = {}
    bad: Dict[Tuple[str, int], str] = {}
    seen: set = set()
    for r in got.get("slots") or []:
        if not isinstance(r, dict) or r.get("n") not in want_slots:
            continue   # an unknown number is dropped
        n = r["n"]
        if n in seen:
            slots.pop(n, None)
            bad[("slot", n)] = f"part {n} is answered twice"
            continue
        seen.add(n)
        try:
            slots[n] = check_slot(r, marks[("slot", n)], before.get(n, ""), notes, parsed.prompt, strict, others)
        except _Bad as e:
            bad[("slot", n)] = str(e)
    lists: Dict[int, str] = {}
    for r in got.get("lists") or []:
        if not isinstance(r, dict) or r.get("n") not in want_lists:
            continue
        if r["n"] in lists:
            bad[("list", r["n"])] = f"list L{r['n']} is answered twice"
            continue
        lists[r["n"]] = str(r.get("label") or "").strip()
    for kind, n in want:
        if (kind == "slot" and n not in slots or kind == "list" and n not in lists) and (kind, n) not in bad:
            bad[(kind, n)] = f"it has no answer for {'⟨%d⟩' % n if kind == 'slot' else '{L%d}' % n}"
    for kind, n in list(bad):
        if kind == "list":
            lists.pop(n, None)
    return slots, lists, bad


def check_reply(reply: str, parsed: Parsed, asked: Sequence[Tuple[str, int]]) -> Tuple[Dict[int, Any], Dict[int, str]]:
    """The asked slots' readings and lists' labels from a reply, checked; _Bad says why not."""
    slots, lists, bad = check_parts(reply, parsed, asked)
    if bad:
        raise _Bad("; ".join(dict.fromkeys(bad.values())))
    return slots, lists


# --------------------------------------------------------------------------- reading

def as_written(n: int, seg: Segment, reason: str) -> Dict[str, Any]:
    """A slot whose reading couldn't be used: it stands as its own words in every image and keeps
    its pill, with nothing to choose yet. Never cached: the next prepare reads it again."""
    return {"n": n, "kind": "free", "label": seg.words, "lead": "",
            "free": {"about": seg.words, "lists": []}, "degraded": True, "reason": reason}


def _cache_get(cache: Any, key: str) -> Any:
    return cache.get_raw(key) if cache is not None else None


def cached(parsed: Parsed, model: Optional[str], cache: Any) -> Tuple[Dict[int, Any], Dict[int, str]]:
    """The readings of the prompt's parts already cached: slot number -> reading, list number -> label."""
    from prompt_programs.vocab import vocabulary
    version = vocabulary().version
    slots: Dict[int, Any] = {}
    lists: Dict[int, str] = {}
    words = {n: seg.words for kind, n, seg in _marked(parsed) if kind == "slot"}
    for kind, n, seg in _marked(parsed):
        hit = _cache_get(cache, part_key(parsed, seg, model, version))
        if kind == "slot" and isinstance(hit, dict) and _worn_holds(hit, words):
            slots[n] = {**hit, "n": n}
        elif kind == "list" and isinstance(hit, str):
            lists[n] = hit
    return slots, lists


def _worn_holds(reading: Dict[str, Any], words: Dict[int, str]) -> bool:
    """Whether every other part a reading names (a part question's answer: what a person wears)
    is still that part of the prompt: read with "<woman> in a <wetsuit>" on another line, a person
    whose wetsuit is gone is read again, or they would wear nothing drawn. Structure only."""
    got = reading.get(reading.get("kind")) if isinstance(reading.get(reading.get("kind")), dict) else {}
    return all(words.get(v.get("n")) == v.get("words") for v in got.values()
               if isinstance(v, dict) and set(v) == {"n", "words"})


def _unusable(parsed: Parsed, n: int, reading: Dict[str, Any]) -> Optional[str]:
    """Why a slot's checked reading still can't seed its variants, or None."""
    from prompt_programs.seeding import ReadingError, plan
    try:
        plan(reading)
    except ReadingError as e:
        return str(e)
    return None


async def read_part(parsed: Parsed, kind: str, n: int, *, ask: Ask, project_id: Optional[int], model: Optional[str],
                    cache: Any = None) -> Any:
    """One part's reading, from one model call that shows the whole prompt and asks only for
    this part: a slot's reading (as check_slot gives it) or a list's label. A reply that can't
    be used gets one retry told why; then a slot is read as written (`degraded`) and a list
    gets no label, and neither is cached. A call that fails outright raises."""
    from prompt_programs.vocab import vocabulary
    seg = next(seg for k, m, seg in _marked(parsed) if (k, m) == (kind, n))
    key = part_key(parsed, seg, model, vocabulary().version)
    messages = [{"role": "system", "content": system_text()},
                {"role": "user", "content": user_message(parsed, [(kind, n)])}]
    why = ""
    for attempt in range(2):
        reply = await ask(messages, project_id, READING_TOKENS + SLOT_TOKENS)
        slots, lists, bad = check_parts(reply, parsed, [(kind, n)], strict=attempt == 0)
        if kind == "slot" and n in slots:
            why = _unusable(parsed, n, slots[n]) or ""
            if not why:
                if cache is not None:
                    cache.put_raw(key, {k: v for k, v in slots[n].items() if k != "n"})
                return slots[n]
        elif kind == "list" and n in lists:
            if cache is not None:
                cache.put_raw(key, lists[n])
            return lists[n]
        else:
            why = "; ".join(dict.fromkeys(bad.values()))
        log.info(f"[slots] the reader's reply can't be used (try {attempt + 1}): {why}")
        messages = [*messages, {"role": "assistant", "content": reply or ""},
                    {"role": "user", "content": f"That reply can't be used: {why}. Reply again with the whole JSON, "
                                                "and nothing else."}]
    log.warning(f"[slots] {'⟨%d⟩' % n if kind == 'slot' else '{L%d}' % n} is read as written: {why}")
    return as_written(n, seg, why) if kind == "slot" else ""


async def read(parsed: Parsed, *, ask: Ask, project_id: Optional[int], model: Optional[str],
               cache: Any = None) -> Dict[str, Any]:
    """Every part of a prompt read, each on its own and all at once, cached ones from the cache:
    {"slots": [reading...], "lists": [{"n", "label"}]}."""
    import asyncio
    slots, lists = cached(parsed, model, cache)
    todo = [(kind, n) for kind, n, _ in _marked(parsed) if n not in (slots if kind == "slot" else lists)]
    got = await asyncio.gather(*(read_part(parsed, kind, n, ask=ask, project_id=project_id, model=model, cache=cache)
                                 for kind, n in todo))
    for (kind, n), value in zip(todo, got):
        (slots if kind == "slot" else lists)[n] = value
    return _reading(slots, lists)


def _reading(slots: Dict[int, Any], lists: Dict[int, str]) -> Dict[str, Any]:
    return {"slots": [slots[n] for n in sorted(slots)], "lists": [{"n": n, "label": lists[n]} for n in sorted(lists)]}


# --------------------------------------------------------------------------- after an edit: does it matter?
#
# A part read before an edit keeps its reading while the edit is checked: one small call for
# every part of the prompt whose line or notes changed, shown each part's lines before and now
# and what it was read as. The model says which readings the edit changes; the rest are kept
# with no more calls.

def rest_of(parsed: Parsed, seg: Segment) -> str:
    """The prompt's other lines, besides the part's own and the notes, each slot on them as its
    bare words: the scene around the part that its variants were written for. "" for a prompt
    of one line. Structure only."""
    from prompt_programs.slots import is_comment
    text = "".join(x.words if x.kind == "slot" else x.text for x in parsed.segments)
    return "\n".join(ln.strip() for i, ln in enumerate(text.split("\n"), 1)
                     if i != seg.line and ln.strip() and not is_comment(ln))


def scene_mark(rest: str) -> str:
    """A short mark of the rest of the prompt, for a pool written again because an edit there
    changed the scene (variant_pools.pool_key's `scene`): the same rest, the same mark."""
    return hashlib.sha256(rest.encode("utf-8")).hexdigest()[:12]


def seen_in(parsed: Parsed, seg: Segment) -> Dict[str, Any]:
    """What a part is read in: its line (as typed, and with the part marked), the notes, the
    text right before it on its line since the last part (where its lead comes from), and the
    rest of the prompt (rest_of: what an edit elsewhere is checked against)."""
    n = sum(x.kind == "slot" for x in parsed.segments[:next(i for i, x in enumerate(parsed.segments) if x is seg) + 1])
    before = leads(parsed).get(n, "") if seg.kind == "slot" else ""
    return {"line": parsed.prompt.split("\n")[seg.line - 1], "marked": _line_with(parsed, seg),
            "notes": comment_lines(parsed), "before": before, "rest": rest_of(parsed, seg)}


CHECK_SYSTEM = """An image prompt was edited. Its marked parts, shown as ⟨words⟩, change from image to image.
Each was read before the edit, and you see what it was read as. Lines starting with "note:" are
the user's notes about the whole image, as binding as the prompt's own words.

For each numbered part you see its reading, the lines it was read in before the edit, and the
lines now, with the rest of the prompt when it has more lines. Check the reading against the
lines now, field by field: what the part is; what its words or the notes state about it; the
list or outfit chosen to suit the scene (the place, the season, the time, the weather, what
someone wears); and the details chosen for how close the picture is. Its options were also
written for the whole picture, so answer "changed" too when the edit changes what they were
written for: the place, the time, the medium (photo, painting, render), the framing, or who is
in the picture. Answer "changed" when any of that would now be chosen or written differently,
else "same"; when unsure, "changed". Other marked parts are shown as their bare words: an edit
that only adds, removes or rewords one of them, or anything else the part doesn't depend on,
leaves it "same".

Reply with JSON only, one answer per part by its number: {"1": "same", "2": "changed"}."""


def _read_as(reading: Dict[str, Any]) -> str:
    """A reading as the check is shown it: what was read, not where it stands or what it is called."""
    if "kind" not in reading:   # a list's: its label
        return json.dumps({"label": reading.get("label") or ""}, ensure_ascii=False)
    # (its lead is structure, checked in code: slots._lead_holds)
    return json.dumps({k: v for k, v in reading.items() if k not in ("n", "lead", "label", "seen")}, ensure_ascii=False)


def check_message(items: Sequence[Dict[str, Any]]) -> str:
    """The check's question. Each item: {"words", "reading", "before": seen_in(...), "now":
    seen_in(...)}. The notes are shown once when the edit left them as they were, else in each
    part's lines."""
    notes_now = list(items[0]["now"]["notes"]) if items else []
    same = all(list(it["before"]["notes"]) == notes_now for it in items)

    def note(text: str) -> str:   # "note:" reads as the user's; "#" alone reads as markup to skip
        return "note: " + text.lstrip().lstrip("#").strip()
    out = ["\n".join(note(x) for x in notes_now)] if same and notes_now else []

    def lines(seen: Dict[str, Any]) -> str:
        # the other parts as their bare words, so adding or removing one isn't an edit to weigh
        from prompt_programs.slots import unwrap_slots
        rest = str(seen.get("rest") or "")
        return "\n".join([*([] if same else [note(x) for x in seen["notes"]] or ["(no notes)"]),
                          unwrap_slots(str(seen["marked"])), *([f"elsewhere in the prompt:\n{rest}"] if rest else [])])
    for i, it in enumerate(items, 1):
        out.append(f'{i}. ⟨{it["words"]}⟩, read as: {_read_as(it["reading"])}\n'
                   f'before:\n{lines(it["before"])}\nnow:\n{lines(it["now"])}')
    return "\n\n".join(out)


def check_tokens(count: int) -> int:
    """Room for one short answer per part, and nothing more."""
    return 24 + 8 * count


def parse_changed(reply: str, count: int) -> Optional[set]:
    """The parts (numbered from 1) the reply says the edit changed, or None when it isn't the
    asked shape. A part it leaves out counts as changed: it is read again."""
    try:
        got = _json(reply)
    except _Bad:
        return None
    changed = set(range(1, count + 1))
    for k, v in got.items():
        answer = v.strip().lower() if isinstance(v, str) else None
        if not str(k).strip().isdigit() or not 1 <= int(k) <= count or answer not in ("same", "changed"):
            return None
        if answer == "same":
            changed.discard(int(k))
    return changed


async def changed_parts(items: Sequence[Dict[str, Any]], *, ask: Ask, project_id: Optional[int]) -> Optional[set]:
    """Which of the parts (by their place in `items`, from 1) an edit changes, from one small
    call; None when the call fails or its reply can't be read (then every part is read again)."""
    messages = [{"role": "system", "content": CHECK_SYSTEM}, {"role": "user", "content": check_message(items)}]
    try:
        reply = await ask(messages, project_id, check_tokens(len(items)))
    except Exception as e:   # a model slip never stops a run: the parts are read again
        log.warning(f"[slots] checking an edit failed: {e}")
        return None
    got = parse_changed(reply, len(items))
    if got is None:
        log.info(f"[slots] the edit check's reply can't be used: {str(reply)[:200]!r}")
    return got


__all__ = ["CHECK_SYSTEM", "READER_VERSION", "read_kind", "fit_lead", "ReaderFailed", "as_written", "cached", "changed_parts",
           "check_message", "check_parts", "check_reply", "check_slot", "leads", "numbered", "parse_changed", "part_key",
           "read", "read_part", "rest_of", "scene_mark", "seen_in", "system_text", "user_message"]

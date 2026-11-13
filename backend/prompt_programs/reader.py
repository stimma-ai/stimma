"""The slot reader: one model call that says what each slot of a prompt is and how it varies.

    an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening

The model sees the prompt with its slots and lists numbered in place (⟨1: elderly African
man⟩, {L1: summer|autumn}) and replies with plain JSON: per slot its kind (person, camera,
light, list, free), a label, its lead and what it needs; per list a label. Code checks only
the reply's structure (numbers, kinds, list ids, details, exact copies of the user's words)
and never reads the slot's words to decide anything. A reply that fails the checks gets one
retry told what was wrong; then the run fails with the reason.

Cached on disk in two levels: the whole numbered prompt, and each slot (and list) by its
own words, its line and the prompt's comment lines. A prompt edited on one line asks only
about the slots on that line.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.slots import CAMERA, KINDS, Parsed, Segment

log = get_logger(__name__)

READER_VERSION = "reader-3"   # reader-3: a part of a person is not a person; leads are joining words; descent is usual. reader-2: each kind's object is shown

Ask = Callable[[List[Dict[str, Any]], Optional[int], int], Awaitable[str]]


class ReaderFailed(Exception):
    """The chat model's reading of the slots couldn't be used, after one retry."""
    code = "reader_failed"


SYSTEM = """You read the parts of an image prompt that should change from image to image. The user marked
each one with angle brackets; you see them numbered, as ⟨1: words⟩. The user's own lists of
options are numbered too, as {L1: summer|autumn}. Lines starting with # are notes from the user
about the image: read them as context for every part. Text shown as [EXACT_1] is the user's
exact text, hidden from you.

For each numbered part, say what it is and how it varies. Reply with JSON only, with nothing
before or after it, in the shape shown at the end. Each part's own fields go in an object named
after its kind: "person": {...}, "camera": {...}, "light": {...}, "list": {...} or "free": {...}.

kind:
- "person": one person, or a character like one: the words name who they are ("young man",
  "nurse", "my friend"). Two parts with the same words are two different people. Words that
  name only something about a person (their hair, their clothes, their eyes) are not a person:
  they are a "list" when a list below covers them, else "free".
- "camera": how the picture is taken: shot size, lens, angle, film look.
- "light": the light in the scene.
- "list": something one of the lists below already covers well. Give its id.
- "free": anything else. Options will be written for it.

For a person:
- noun: what they are, in one word from their words ("man", "nurse", "friend").
- presentation: "feminine" or "masculine" when their words or the notes say which, else "".
- stated: for each detail their words or the notes settle, the words that settle it, copied
  exactly: {"age": "elderly", "descent": "African"}. Only what is said; nothing guessed.
- vary: the details that change from image to image, from the person details below. They are
  the fixed things about the person: their age, within what the words say ("young man" stays
  young, "elderly African man" stays elderly and of African descent), their descent, build,
  hair and the like. Most often: age, descent, build, hair and hair_color, with facial_hair
  for a masculine person. Choose what this picture shows of them: a small figure in a wide
  scene shows age, build and hair, not eyes; a close portrait adds face and eyes.
  You need not include every detail, but leave one out only for a reason. Facial hair only
  for a masculine person.
- Leave out expression unless the prompt or a note asks for it to change. Leave out pose and
  accessories: they are not part of the person.
- outfit: their clothes change too, unless the prompt already says what they wear. Give the id
  of the outfit list below that suits the scene, or "written" if none does, or "" when the
  prompt already describes their clothes or none show.
- outfit_examples: when outfit is "written", three outfits that suit the scene, each as it
  would read after "wearing"; else [].

For a camera: vary, the parts of it that change, from: shot_size, lens, angle, film_look.
  "camera": {"vary": ["shot_size", "angle"]}

For light: examples, three kinds of light that fit this scene.
  "light": {"examples": ["...", "...", "..."]}

For a list: list (its id) and stated (the words of the part that narrow it, copied exactly, or "").
  "list": {"list": "<the list's id>", "stated": ""}

For free: about (what it is in this image, a few words), kinds (three specific kinds of the
thing the words name) and instead (three other things that could stand in the same place in
the sentence).

Write every example (light, kinds, instead) so it replaces exactly the bracketed words: the
same form, no article unless the words have one. "with his ⟨pet⟩" gives "ginger tabby cat",
not "a cat".

For every part:
- label: two or three words naming it for a menu.
- lead: when this part is left out of the prompt, the words right before it that would be left
  hanging without it, copied exactly: ", lit by" in "a kitchen, lit by ⟨light⟩"; " with a" in
  "a desk with a ⟨lamp⟩"; "," in "red car, ⟨camera⟩". Only joining words, articles and the
  punctuation before them, never a word that names or describes something else. "" when nothing
  would hang ("⟨old man⟩ in a kitchen").

For each numbered list {Ln: ...}: a label of one or two words.

Person details:
{details}

Lists:
{catalog}

The reply's shape (an example):
{shape}"""

SHAPE = {
    "slots": [
        {"n": 1, "kind": "person", "label": "Elderly African man", "lead": "an",
         "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "elderly", "descent": "African"},
                    "vary": ["age", "descent", "build", "hair", "hair_color", "facial_hair"],
                    "outfit": "person.outfit.casual", "outfit_examples": []}},
        {"n": 2, "kind": "free", "label": "Pet", "lead": " with his",
         "free": {"about": "his pet, with him on the porch",
                  "kinds": ["ginger tabby cat", "old basset hound", "grey parrot"],
                  "instead": ["stack of library books", "mug of coffee", "transistor radio"]}},
    ],
    "lists": [{"n": 1, "label": "Season"}],
}

# The lists the reader may bind a slot to (vocab.catalog's roots, the outfit and hairstyle lists among them).
CATALOG_ROOTS = ("person", "animal", "place", "scene", "camera", "art.style")


def system_text() -> str:
    from prompt_programs.people import DETAILS
    from prompt_programs.vocab import vocabulary
    details = "\n".join(f"- {k}: {v[2]}" for k, v in DETAILS.items())
    return (SYSTEM.replace("{details}", details).replace("{catalog}", vocabulary().catalog(CATALOG_ROOTS))
            .replace("{shape}", json.dumps(SHAPE, ensure_ascii=False, indent=1)))


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


def prompt_key(parsed: Parsed, model: Optional[str], vocab_version: str) -> str:
    return _hash("prompt", model, vocab_version, numbered(parsed))


def part_key(parsed: Parsed, seg: Segment, model: Optional[str], vocab_version: str) -> str:
    return _hash(seg.kind, model, vocab_version, seg.words if seg.kind == "slot" else seg.text,
                 _line_with(parsed, seg), comment_lines(parsed))


def user_message(parsed: Parsed, asked: Sequence[Tuple[str, int]]) -> str:
    text = f"The prompt:\n{numbered(parsed)}"
    every = [(kind, n) for kind, n, _ in _marked(parsed)]
    if list(asked) != every:
        names = ", ".join(f"⟨{n}⟩" if kind == "slot" else f"{{L{n}}}" for kind, n in asked)
        text += f"\n\nThe other parts are already read. Answer only for: {names}."
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


def check_slot(r: Dict[str, Any], seg: Segment, before: str, notes: Sequence[str]) -> Dict[str, Any]:
    """One slot's reading as the builder takes it, or _Bad. Details it doesn't know, stated
    words that aren't the user's and a lead that isn't the text before the slot are dropped."""
    from prompt_programs.people import DETAILS
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    n = r.get("n")
    kind = r.get("kind")
    if kind not in KINDS:
        raise _Bad(f"part {n}: kind must be one of {', '.join(KINDS)}")
    got = r.get(kind)
    if not isinstance(got, dict):
        raise _Bad(f'part {n}: a {kind} needs its fields in a "{kind}" object, as "{kind}": {{...}}')
    lead = r.get("lead") if isinstance(r.get("lead"), str) else ""
    if not lead.strip() or not before.rstrip().endswith(lead.strip()):
        lead = ""
    out: Dict[str, Any] = {"n": n, "kind": kind, "label": str(r.get("label") or "").strip() or seg.words, "lead": lead}
    sources = [seg.words, *notes]
    if kind == "person":
        stated = got.get("stated") if isinstance(got.get("stated"), dict) else {}
        outfit = got.get("outfit") if isinstance(got.get("outfit"), str) else ""
        if outfit not in ("", "written") and vocab.get(outfit) is None:
            raise _Bad(f'part {n}: outfit "{outfit}" is not one of the lists')
        examples = _strings(got.get("outfit_examples"), f"part {n}: outfit_examples") if outfit == "written" else []
        if outfit == "written" and not examples:
            raise _Bad(f'part {n}: an outfit that is "written" needs three outfit_examples')
        out["person"] = {
            "noun": str(got.get("noun") or "").strip() or "person",
            "presentation": got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else "",
            "stated": {d: w.strip() for d, w in stated.items()
                       if d in DETAILS and isinstance(w, str) and w.strip() and _copied(w, sources)},
            "vary": [d for d in dict.fromkeys(_strings(got.get("vary"), f"part {n}: vary")) if d in DETAILS],
            "outfit": outfit, **({"outfit_examples": examples} if examples else {}),
        }
    elif kind == "camera":
        vary = [d for d in dict.fromkeys(_strings(got.get("vary"), f"part {n}: vary")) if d in CAMERA]
        if not vary:
            raise _Bad(f"part {n}: a camera must vary some of {', '.join(CAMERA)}")
        out["camera"] = {"vary": vary}
    elif kind == "light":   # a free slot for now (its examples are its seeds), shown as light
        examples = _strings(got.get("examples"), f"part {n}: examples")
        if not examples:
            raise _Bad(f"part {n}: light needs three examples")
        out["light"] = {"examples": examples}
    elif kind == "list":
        lid = got.get("list")
        if not isinstance(lid, str) or vocab.get(lid) is None:
            raise _Bad(f'part {n}: list "{lid}" is not one of the lists (the id goes in "list": {{"list": "<id>", "stated": ""}})')
        stated = got.get("stated") if isinstance(got.get("stated"), str) else ""
        out["list"] = {"list": lid, "stated": stated.strip() if stated.strip() and _copied(stated, sources) else ""}
    else:
        kinds = _strings(got.get("kinds"), f"part {n}: kinds")
        if not kinds:
            raise _Bad(f"part {n}: free needs three kinds")
        out["free"] = {"about": str(got.get("about") or "").strip() or seg.words, "kinds": kinds,
                       "instead": _strings(got.get("instead"), f"part {n}: instead")}
    return out


def check_reply(reply: str, parsed: Parsed, asked: Sequence[Tuple[str, int]]) -> Tuple[Dict[int, Any], Dict[int, str]]:
    """The asked slots' readings and lists' labels from a reply, checked; _Bad says why not."""
    got = _json(reply)
    marks = {(kind, n): seg for kind, n, seg in _marked(parsed)}
    want_slots = {n for kind, n in asked if kind == "slot"}
    want_lists = {n for kind, n in asked if kind == "list"}
    before, notes = leads(parsed), comment_lines(parsed)
    slots: Dict[int, Any] = {}
    for r in got.get("slots") or []:
        if not isinstance(r, dict) or r.get("n") not in want_slots:
            continue   # an unknown number is dropped
        if r["n"] in slots:
            raise _Bad(f"part {r['n']} is answered twice")
        slots[r["n"]] = check_slot(r, marks[("slot", r["n"])], before.get(r["n"], ""), notes)
    lists: Dict[int, str] = {}
    for r in got.get("lists") or []:
        if not isinstance(r, dict) or r.get("n") not in want_lists:
            continue
        if r["n"] in lists:
            raise _Bad(f"list L{r['n']} is answered twice")
        lists[r["n"]] = str(r.get("label") or "").strip()
    missing = [f"⟨{n}⟩" for n in sorted(want_slots - set(slots))] + [f"{{L{n}}}" for n in sorted(want_lists - set(lists))]
    if missing:
        raise _Bad(f"it has no answer for {', '.join(missing)}")
    return slots, lists


# --------------------------------------------------------------------------- reading

def _cache_get(cache: Any, key: str) -> Any:
    return cache.get_raw(key) if cache is not None else None


async def read(parsed: Parsed, *, ask: Ask, project_id: Optional[int], model: Optional[str],
               cache: Any = None, force: bool = False) -> Dict[str, Any]:
    """The reading of every slot and list of a parsed prompt, as slots.build takes it:
    {"slots": [{"n", "kind", "label", "lead", "<kind>": {...}}], "lists": [{"n", "label"}]}.
    `cache`: a narrow.NarrowCache-like store (get_raw/put_raw); `force` reads again."""
    from prompt_programs.slots import ReadingError, build
    from prompt_programs.vocab import vocabulary
    version = vocabulary().version
    whole = prompt_key(parsed, model, version)
    if not force:
        hit = _cache_get(cache, whole)
        if isinstance(hit, dict):
            return hit
    marks = _marked(parsed)
    keys = {(kind, n): part_key(parsed, seg, model, version) for kind, n, seg in marks}
    slots: Dict[int, Any] = {}
    lists: Dict[int, str] = {}
    for (kind, n), key in keys.items():
        hit = None if force else _cache_get(cache, key)
        if kind == "slot" and isinstance(hit, dict):
            slots[n] = {**hit, "n": n}
        elif kind == "list" and isinstance(hit, str):
            lists[n] = hit
    asked = [(kind, n) for kind, n, _ in marks if n not in (slots if kind == "slot" else lists)]
    if asked:
        messages = [{"role": "system", "content": system_text()},
                    {"role": "user", "content": user_message(parsed, asked)}]
        problem = ""
        for attempt in range(2):
            reply = await ask(messages, project_id, 3000)
            try:
                got_slots, got_lists = check_reply(reply, parsed, asked)
                reading = _reading({**slots, **got_slots}, {**lists, **got_lists})
                try:
                    build(parsed, reading)
                except ReadingError as e:
                    raise _Bad(str(e)) from None
            except _Bad as e:
                problem = str(e)
                log.info(f"[slots] the reader's reply can't be used (try {attempt + 1}): {problem}")
                messages = [*messages, {"role": "assistant", "content": reply or ""},
                            {"role": "user", "content": f"That reply can't be used: {problem}. Reply again with the "
                                                        "whole JSON, and nothing else."}]
                continue
            slots.update(got_slots)
            lists.update(got_lists)
            break
        else:
            raise ReaderFailed(f"The chat model's reading of the prompt's slots couldn't be used: {problem}.")
    reading = _reading(slots, lists)
    if cache is not None:
        for (kind, n), key in keys.items():
            if kind == "slot":
                cache.put_raw(key, {k: v for k, v in slots[n].items() if k != "n"})
            else:
                cache.put_raw(key, lists[n])
        cache.put_raw(whole, reading)
    return reading


def _reading(slots: Dict[int, Any], lists: Dict[int, str]) -> Dict[str, Any]:
    return {"slots": [slots[n] for n in sorted(slots)], "lists": [{"n": n, "label": lists[n]} for n in sorted(lists)]}


__all__ = ["READER_VERSION", "ReaderFailed", "SYSTEM", "check_reply", "check_slot", "leads", "numbered", "read",
           "system_text", "user_message"]

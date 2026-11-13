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
from prompt_programs.fill import CAMERA, KINDS
from prompt_programs.slots import Parsed, Segment

log = get_logger(__name__)

READER_VERSION = "reader-8"   # reader-8: each part is read on its own. reader-7: a free slot gives things instead only when something naturally stands there. reader-6: the example's prompt is shown; only the numbered parts are parts, and the message names them. reader-5: a part about someone the prompt has is never a person (worked tag example; the noun is copied); a list says what it is about. reader-4: a stated detail is always drawn; a person with nothing to draw is retried. reader-3: a part of a person is not a person; leads are joining words; descent is usual. reader-2: each kind's object is shown

Ask = Callable[[List[Dict[str, Any]], Optional[int], int], Awaitable[str]]

# A reading's reply budget: a few hundred tokens a part is room enough with no reasoning, and
# a runaway reply stops in seconds instead of minutes.
READING_TOKENS, SLOT_TOKENS = 300, 300


class ReaderFailed(Exception):
    """The chat model's reading of the slots couldn't be used, after one retry."""
    code = "reader_failed"


SYSTEM = """You read the parts of an image prompt that should change from image to image. The user marked
each one with angle brackets; you see them numbered, as ⟨1: words⟩. The user's own lists of
options are numbered too, as {L1: summer|autumn}. Lines starting with # are notes from the user
about the image: read them as context for every part. Text shown as [EXACT_1] is the user's
exact text, hidden from you.

For each numbered part, say what it is and how it varies. Only the numbered parts change: the
words outside them stay as the user wrote them, and are never a part, even when they name a
person. Reply with JSON only, with nothing
before or after it, in the shape shown at the end. Each part's own fields go in an object named
after its kind: "person": {...}, "camera": {...}, "light": {...}, "list": {...} or "free": {...}.

kind:
- "person": someone the prompt doesn't already have, named by the part's own words: "young
  man", "nurse", "my friend", "elderly African man". Their noun is one of those words. Two parts
  with the same words are two different people.
- Words that name only something about a person, or about someone the prompt already has
  ("1girl, ⟨hairstyle⟩", "a woman with ⟨hair color⟩ hair", "1boy, ⟨outfit⟩, ⟨expression⟩",
  "a knight in ⟨armor⟩"), are never a person, even when that is all the part is about: the
  person is already in the prompt's own words. They are a "list" when a list below covers
  them, else "free".
- "camera": how the picture is taken: shot size, lens, angle, film look.
- "light": the light in the scene.
- "list": something one of the lists below holds: the list's items are kinds of the very thing
  the words name, not of something like it. Give its id.
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

For a list: list (its id) and about (what it is in this image, and whose, in a few words, with
what the prompt and notes say of them: "the girl's hairstyle", "a middle-aged man's hairstyle",
"his pet, on the porch"). The part's words and the about decide which of the list's items fit.
  "list": {"list": "<the list's id>", "about": "..."}

For free: about (what it is in this image, a few words), kinds (three specific kinds of the
thing the words name) and instead: up to three other things that would naturally stand in the
same place instead, only when something does ("on a ⟨bench⟩" could be "low stone wall"). Often
nothing does (what stands instead of a pet?): then instead is [].

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

An example. For the prompt "an ⟨1: elderly African man⟩ reading on a porch with his ⟨2: pet⟩,
{L1: summer|autumn} evening" the reply is:
{shape}

Another. The prompt "1girl, ⟨1: hairstyle⟩, ⟨2: outfit⟩, beach" has one person, the girl,
in its own words; both parts are about her:
{tags}"""

SHAPE = {
    "slots": [
        {"n": 1, "kind": "person", "label": "Elderly African man", "lead": "an",
         "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "elderly", "descent": "African"},
                    "vary": ["age", "descent", "build", "hair", "hair_color", "facial_hair"],
                    "outfit": "person.outfit.casual", "outfit_examples": []}},
        {"n": 2, "kind": "free", "label": "Pet", "lead": " with his",
         "free": {"about": "his pet, with him on the porch",
                  "kinds": ["ginger tabby cat", "old basset hound", "grey parrot"],
                  "instead": []}},
    ],
    "lists": [{"n": 1, "label": "Season"}],
}

TAGS = {
    "slots": [
        {"n": 1, "kind": "list", "label": "Hairstyle", "lead": ",",
         "list": {"list": "person.hairstyle", "about": "the girl's hairstyle"}},
        {"n": 2, "kind": "list", "label": "Outfit", "lead": ",",
         "list": {"list": "person.outfit.summer", "about": "the girl's outfit, at the beach"}},
    ],
    "lists": [],
}

# The lists the reader may bind a slot to (vocab.catalog's roots, the outfit and hairstyle lists among them).
CATALOG_ROOTS = ("person", "animal", "place", "scene", "camera", "art.style")


def system_text() -> str:
    from prompt_programs.fill import DETAILS
    from prompt_programs.vocab import vocabulary
    details = "\n".join(f"- {k}: {v[2]}" for k, v in DETAILS.items())
    return (SYSTEM.replace("{details}", details).replace("{catalog}", vocabulary().catalog(CATALOG_ROOTS))
            .replace("{shape}", json.dumps(SHAPE, ensure_ascii=False, indent=1))
            .replace("{tags}", json.dumps(TAGS, ensure_ascii=False)))


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


def check_slot(r: Dict[str, Any], seg: Segment, before: str, notes: Sequence[str]) -> Dict[str, Any]:
    """One slot's reading as the builder takes it, or _Bad. Details it doesn't know, stated
    words that aren't the user's and a lead that isn't the text before the slot are dropped."""
    from prompt_programs.fill import DETAILS
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    n = r.get("n")
    kind = r.get("kind")
    if kind not in KINDS:
        raise _Bad(f"part {n}: kind must be one of {', '.join(KINDS)}; a list's id goes in its object, as "
                   '"kind": "list", "list": {"list": "<the list\'s id>", "about": "..."}')
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
        kept = {d: w.strip() for d, w in stated.items()
                if d in DETAILS and isinstance(w, str) and w.strip() and _copied(w, sources)}
        # A detail the words state is drawn, within the words: left undrawn, the person would be
        # only their noun and the words would be lost ("young man" drawn as "a man").
        vary = list(dict.fromkeys([*(d for d in _strings(got.get("vary"), f"part {n}: vary") if d in DETAILS), *kept]))
        noun = str(got.get("noun") or "").strip()
        if not noun or not _copied(noun, sources):
            # Copied, as stated words are: a person is named by their own part. A reading whose noun
            # comes from elsewhere has taken words about someone already in the prompt for a new person.
            raise _Bad(f'part {n}: a person\'s noun is one of their own words, and "{noun}" is not among the '
                       f'words "{seg.words}". Words that name only something about a person, or about someone '
                       'the prompt already has, are a "list" when a list covers them, else "free"')
        if not vary and not outfit:
            raise _Bad(f"part {n}: a person needs details to vary (from {', '.join(DETAILS)}) or an outfit; "
                       "words about part of a person are a list or free, not a person")
        out["person"] = {
            "noun": noun,
            "presentation": got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else "",
            "stated": kept, "vary": vary,
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
        about = got.get("about") if isinstance(got.get("about"), str) else ""
        out["list"] = {"list": lid, "about": about.strip() or seg.words}
    else:
        kinds = _strings(got.get("kinds"), f"part {n}: kinds")
        if not kinds:
            raise _Bad(f"part {n}: free needs three kinds")
        out["free"] = {"about": str(got.get("about") or "").strip() or seg.words, "kinds": kinds,
                       "instead": _strings(got.get("instead"), f"part {n}: instead")}
    return out


def check_parts(reply: str, parsed: Parsed, asked: Sequence[Tuple[str, int]]
                ) -> Tuple[Dict[int, Any], Dict[int, str], Dict[Tuple[str, int], str]]:
    """The asked slots' readings and lists' labels that a reply gives in a usable form, and
    for each asked part it doesn't, what is wrong, said plainly. Never raises: one part's bad
    answer leaves the others' good ones standing."""
    want = list(asked)
    try:
        got = _json(reply)
    except _Bad as e:
        return {}, {}, {k: str(e) for k in want}
    marks = {(kind, n): seg for kind, n, seg in _marked(parsed)}
    want_slots = {n for kind, n in want if kind == "slot"}
    want_lists = {n for kind, n in want if kind == "list"}
    before, notes = leads(parsed), comment_lines(parsed)
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
            slots[n] = check_slot(r, marks[("slot", n)], before.get(n, ""), notes)
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
            "free": {"about": seg.words, "kinds": [seg.words], "instead": []}, "degraded": True, "reason": reason}


def _cache_get(cache: Any, key: str) -> Any:
    return cache.get_raw(key) if cache is not None else None


def cached(parsed: Parsed, model: Optional[str], cache: Any) -> Tuple[Dict[int, Any], Dict[int, str]]:
    """The readings of the prompt's parts already cached: slot number -> reading, list number -> label."""
    from prompt_programs.vocab import vocabulary
    version = vocabulary().version
    slots: Dict[int, Any] = {}
    lists: Dict[int, str] = {}
    for kind, n, seg in _marked(parsed):
        hit = _cache_get(cache, part_key(parsed, seg, model, version))
        if kind == "slot" and isinstance(hit, dict):
            slots[n] = {**hit, "n": n}
        elif kind == "list" and isinstance(hit, str):
            lists[n] = hit
    return slots, lists


def _unusable(parsed: Parsed, n: int, reading: Dict[str, Any]) -> Optional[str]:
    """Why a slot's checked reading still can't make its picks, or None."""
    from prompt_programs.fill import ReadingError, picks_of
    from prompt_programs.slots import slot_ids
    seg = next(seg for kind, m, seg in _marked(parsed) if kind == "slot" and m == n)
    try:
        picks_of(slot_ids(parsed)[n - 1], seg.words, reading)
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
        slots, lists, bad = check_parts(reply, parsed, [(kind, n)])
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


__all__ = ["READER_VERSION", "ReaderFailed", "SYSTEM", "as_written", "cached", "check_parts", "check_reply", "check_slot",
           "leads", "numbered", "part_key", "read", "read_part", "system_text", "user_message"]

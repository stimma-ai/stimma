"""The slot reader: a model call that says what one slot of a prompt is and how it varies.

    an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening

The model sees the prompt with its slots and lists numbered in place (⟨1: elderly African
man⟩, {L1: summer|autumn}) and replies with plain JSON: per slot its kind (person, camera,
light, list, free), a label, its lead and what it needs; per list a label. Code checks only
the reply's structure (numbers, kinds, list ids, details, exact copies of the user's words)
and never reads the slot's words to decide anything. Each part is asked on its own, the whole
prompt shown. A reply that fails the checks gets one retry told what was wrong; then the part
is read as written, never cached.

Cached on disk per part, by its own words, its line and the prompt's comment lines. A prompt
edited on one line asks only about the parts on that line, and of those, a part read before the
edit keeps its reading while one small call for all of them (changed_parts) asks whether the
edit changes it; only the parts it changes are read again (slots.py).
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

READER_VERSION = "reader-16"   # reader-16: an animal says the kind the words call for ("pet"). reader-15: hair is length, texture and color, a hairstyle starts left out, and every directory's lists are offered. reader-14: a coat list is a breed list. reader-13: a young animal's word states its life stage. reader-12: light names its looks; a person with no outfit says what the prompt says they wear. reader-11: a list about a person says how they present; face is its own true/false, only when asked for. reader-9: animals are a builder; light may name a lighting list. reader-8: each part is read on its own. reader-7: a free slot gives things instead only when something naturally stands there. reader-6: the example's prompt is shown; only the numbered parts are parts, and the message names them. reader-5: a part about someone the prompt has is never a person (worked tag example; the noun is copied); a list says what it is about. reader-4: a stated detail is always drawn; a person with nothing to draw is retried. reader-3: a part of a person is not a person; leads are joining words; descent is usual. reader-2: each kind's object is shown

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
after its kind: "person": {...}, "animal": {...}, "camera": {...}, "light": {...}, "list": {...} or
"free": {...}.

kind:
- "person": someone the prompt doesn't already have, named by the part's own words: "young
  man", "nurse", "my friend", "elderly African man". Their noun is one of those words. Two parts
  with the same words are two different people.
- Words that name only something about a person, or about someone the prompt already has
  ("1girl, ⟨hairstyle⟩", "a woman with ⟨hair color⟩ hair", "1boy, ⟨outfit⟩, ⟨expression⟩",
  "a knight in ⟨armor⟩"), are never a person, even when that is all the part is about: the
  person is already in the prompt's own words. They are a "list" when a list below covers
  them, else "free".
- "animal": an animal the prompt doesn't already have, named by the part's own words: "pet",
  "dog", "old cat", "animal".
- "camera": how the picture is taken: shot size, lens, angle, film look.
- "light": the light in the scene, as one named look (a softbox, flash, chiaroscuro, golden
  hour light), never split into its source, direction or color.
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
  hair and the like. Most often: age, descent, build, hair, hair_texture and hair_color, with
  facial_hair for a masculine person. hairstyle only when the prompt or a note asks for it to
  change. Choose what this picture shows of them: a small figure in a wide
  scene shows age, build and hair, not eyes; a close portrait adds eyes.
  You need not include every detail, but leave one out only for a reason. Facial hair only
  for a masculine person.
- face: true only when the prompt or a note asks for their face or its features to change
  from image to image ("# a different face each time"); a close portrait alone doesn't.
  Else false.
- Leave out expression unless the prompt or a note asks for it to change. Leave out pose and
  accessories: they are not part of the person.
- clothes: the words of the prompt or a note that say what they wear, or that no clothes
  show, copied exactly ("in a red raincoat", "headshot"); "" when nothing says so, which is
  most prompts.
- outfit: their clothes change too, unless clothes has words. Give the id of the outfit list
  below that suits the scene, or "written" if none does; "" only when clothes has words.
- outfit_examples: when outfit is "written", three outfits that suit the scene, each as it
  would read after "wearing"; else [].

For an animal:
- noun: what it is, in one word from its words ("pet", "dog", "cat").
- vary: what changes from image to image, from: species (what kind of animal, when the words
  leave it open: "pet", "animal"), breed (when the words name one kind that has a breed or
  coat list below: "dog", "kitten"; never beside species), life_stage (baby, juvenile, adult,
  elderly).
- type: when species varies, the kind of animal the words call for, from: {types}. "pet" is
  "pet"; "farm animal" is "farm". "" when the words call for any animal ("animal", "creature").
- breed: the id of that kind's breed or coat list below, or "".
- stated: for each of those the words settle, the words that settle it, copied exactly:
  {"life_stage": "old"}; a young animal's own word settles its life stage: "kitten" or
  "puppy" is {"life_stage": "kitten"}.
  "animal": {"noun": "dog", "vary": ["breed", "life_stage"], "type": "", "breed": "<a breed list's id>", "stated": {}}

For a camera: vary, the parts of it that change, from: shot_size, lens, angle, film_look.
  "camera": {"vary": ["shot_size", "angle"]}

For light: list, the id of the lighting list below whose looks suit this scene, or "" only when
none of them could; and examples, three looks of light that fit this scene, each named as a
photographer would name it ("warm desk-lamp glow", "gray window light", "neon sign spill"),
never a bare quality ("warm light", "dim light").
  "light": {"list": "<a lighting list's id, or empty>", "examples": ["...", "...", "..."]}

For a list: list (its id) and about (what it is in this image, and whose, in a few words, with
what the prompt and notes say of them: "the girl's hairstyle", "a middle-aged man's hairstyle",
"his pet, on the porch"). The part's words and the about decide which of the list's items fit.
When it is about a person whose words or the notes say how they present ("1boy", "a woman"),
presentation: "feminine" or "masculine"; else "".
  "list": {"list": "<the list's id>", "about": "...", "presentation": ""}

For free: about (what it is in this image, a few words), kinds (three specific kinds of the
thing the words name) and instead: up to three other things that would naturally stand in the
same place instead, only when something does ("on a ⟨bench⟩" could be "low stone wall"). Often
nothing does (what stands instead of a hat?): then instead is [].

Write every example (light, kinds, instead) so it replaces exactly the bracketed words: the
same form, no article unless the words have one. "in his ⟨hat⟩" gives "battered fedora",
not "a fedora".

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
                    "vary": ["age", "descent", "build", "hair", "hair_texture", "hair_color", "facial_hair"], "face": False,
                    "clothes": "", "outfit": "person.outfit.casual", "outfit_examples": []}},
        {"n": 2, "kind": "animal", "label": "Pet", "lead": " with his",
         "animal": {"noun": "pet", "vary": ["species", "life_stage"], "type": "pet", "breed": "", "stated": {}}},
    ],
    "lists": [{"n": 1, "label": "Season"}],
}

TAGS = {
    "slots": [
        {"n": 1, "kind": "list", "label": "Hairstyle", "lead": ",",
         "list": {"list": "person.hairstyle", "about": "the girl's hairstyle", "presentation": "feminine"}},
        {"n": 2, "kind": "list", "label": "Outfit", "lead": ",",
         "list": {"list": "person.outfit.summer", "about": "the girl's outfit, at the beach", "presentation": "feminine"}},
    ],
    "lists": [],
}

# The lists the reader may bind a slot to (vocab.catalog's roots, the outfit and hairstyle lists among them).
from prompt_programs.vocab import CATALOG_ROOTS   # every directory  # noqa: E402


def system_text() -> str:
    from prompt_programs.fill import ANIMAL_LISTS, DETAILS
    from prompt_programs.vocab import vocabulary
    details = "\n".join(f"- {k}: {v[2]}" for k, v in DETAILS.items() if k != "face")
    types = ", ".join(f'"{t}"' for t in vocabulary().get(ANIMAL_LISTS["species"]).local_facets.get("kind", ()))
    return (SYSTEM.replace("{details}", details).replace("{types}", types).replace("{catalog}", vocabulary().catalog(CATALOG_ROOTS))
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


def check_slot(r: Dict[str, Any], seg: Segment, before: str, notes: Sequence[str], prompt: str = "",
               strict: bool = True) -> Dict[str, Any]:
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
        # Face detail is drawn only when the reading says it was asked for ("face": true).
        asked = ["face"] if got.get("face") is True else []
        vary = list(dict.fromkeys([*(d for d in _strings(got.get("vary"), f"part {n}: vary")
                                     if d in DETAILS and d != "face"), *asked, *kept]))
        noun = str(got.get("noun") or "").strip()
        if not noun or not _copied(noun, sources):
            # Copied, as stated words are: a person is named by their own part. A reading whose noun
            # comes from elsewhere has taken words about someone already in the prompt for a new person.
            raise _Bad(f'part {n}: a person\'s noun is one of their own words, and "{noun}" is not among the '
                       f'words "{seg.words}". Words that name only something about a person, or about someone '
                       'the prompt already has, are a "list" when a list covers them, else "free"')
        clothes = got.get("clothes") if isinstance(got.get("clothes"), str) else ""
        # Asked once (`strict`): a reading that still gives no outfit on the retry stands as it is.
        if strict and (vary or outfit) and not outfit and not (clothes.strip() and _copied(clothes, [seg.words, before, *notes, prompt])):
            raise _Bad(f'part {n}: a person\'s clothes change unless the prompt says what they wear: give an outfit '
                       'list\'s id (or "written" with three outfit_examples), or copy the prompt\'s words about '
                       'their clothes into "clothes"')
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
    elif kind == "animal":
        from prompt_programs.fill import ANIMAL, ANIMAL_LISTS
        noun = str(got.get("noun") or "").strip()
        if not noun or not _copied(noun, sources):
            raise _Bad(f'part {n}: an animal\'s noun is one of its own words, and "{noun}" is not among the words "{seg.words}"')
        vary = [d for d in dict.fromkeys(_strings(got.get("vary"), f"part {n}: vary")) if d in ANIMAL]
        breed = got.get("breed") if isinstance(got.get("breed"), str) else ""
        if breed and (vocab.get(breed) is None or breed in ANIMAL_LISTS.values() or not breed.startswith("animal.")):
            breed = ""   # a kind with no breed list ("kitten"): the rest of the reading stands
        if "breed" in vary and (not breed or "species" in vary):
            vary = [d for d in vary if d != "breed"]
        stated = got.get("stated") if isinstance(got.get("stated"), dict) else {}
        kept = {d: w.strip() for d, w in stated.items()
                if d in ANIMAL and isinstance(w, str) and w.strip() and _copied(w, sources)}
        vary = list(dict.fromkeys([*vary, *(d for d in kept if d != "breed" or breed)]))
        if not vary:
            raise _Bad(f"part {n}: an animal needs something to vary, from {', '.join(ANIMAL)}")
        # The kind of animal the words call for ("pet"): one of the species list's kinds, else none.
        sort = got.get("type") if isinstance(got.get("type"), str) else ""
        sort = sort if "species" in vary and sort in vocab.get(ANIMAL_LISTS["species"]).local_facets.get("kind", ()) else ""
        out["animal"] = {"noun": noun, "vary": vary, **({"type": sort} if sort else {}),
                         "breed": breed if "breed" in vary else "", "stated": kept}
    elif kind == "light":   # one named look of light: a lighting list's, or written for the scene
        examples = _strings(got.get("examples"), f"part {n}: examples")
        lid = got.get("list") if isinstance(got.get("list"), str) else ""
        if lid and (vocab.get(lid) is None or not lid.startswith("lighting.")):
            raise _Bad(f'part {n}: light list "{lid}" is not one of the lighting lists')
        if not examples and not lid:
            raise _Bad(f"part {n}: light needs three examples")
        out["light"] = {"list": lid, "examples": examples}
    elif kind == "list":
        lid = got.get("list")
        if not isinstance(lid, str) or vocab.get(lid) is None:
            raise _Bad(f'part {n}: list "{lid}" is not one of the lists (the id goes in "list": {{"list": "<id>", "stated": ""}})')
        about = got.get("about") if isinstance(got.get("about"), str) else ""
        out["list"] = {"list": lid, "about": about.strip() or seg.words}
        if got.get("presentation") in ("feminine", "masculine"):
            out["list"]["presentation"] = got["presentation"]
    else:
        kinds = _strings(got.get("kinds"), f"part {n}: kinds")
        if not kinds:
            raise _Bad(f"part {n}: free needs three kinds")
        out["free"] = {"about": str(got.get("about") or "").strip() or seg.words, "kinds": kinds,
                       "instead": _strings(got.get("instead"), f"part {n}: instead")}
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
            slots[n] = check_slot(r, marks[("slot", n)], before.get(n, ""), notes, parsed.prompt, strict)
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

def seen_in(parsed: Parsed, seg: Segment) -> Dict[str, Any]:
    """What a part is read in: its line (as typed, and with the part marked) and the notes."""
    return {"line": parsed.prompt.split("\n")[seg.line - 1], "marked": _line_with(parsed, seg),
            "notes": comment_lines(parsed)}


CHECK_SYSTEM = """An image prompt was edited. Its marked parts, shown as ⟨words⟩, change from image to image.
Each was read before the edit, and you see what it was read as. Lines starting with "note:" are
the user's notes about the whole image, as binding as the prompt's own words.

For each numbered part you see its reading, the lines it was read in before the edit, and the
lines now. Check the reading against the lines now, field by field: what the part is; what its
words or the notes state about it; the list, outfit or examples chosen to suit the scene (the
place, the season, the time, the weather, what someone wears); and the details chosen for how
close the picture is. Answer "changed" when any field would now be chosen differently, else
"same"; when unsure, "changed". An edit that adds, removes or rewords things the reading doesn't
depend on, other marked parts among them, leaves it "same".

Reply with JSON only, one answer per part by its number: {"1": "same", "2": "changed"}."""


def _read_as(reading: Dict[str, Any]) -> str:
    """A reading as the check is shown it: what was read, not where it stands or what it is called."""
    if "kind" not in reading:   # a list's: its label
        return json.dumps({"label": reading.get("label") or ""}, ensure_ascii=False)
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
        return "\n".join([*([] if same else [note(x) for x in seen["notes"]] or ["(no notes)"]), seen["marked"]])
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


__all__ = ["CHECK_SYSTEM", "READER_VERSION", "ReaderFailed", "SYSTEM", "as_written", "cached", "changed_parts",
           "check_message", "check_parts", "check_reply", "check_slot", "leads", "numbered", "parse_changed", "part_key",
           "read", "read_part", "seen_in", "system_text", "user_message"]

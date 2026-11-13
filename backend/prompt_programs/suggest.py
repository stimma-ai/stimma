"""Suggest and Add: the editor's helpers for making slots.

Suggest reads a prompt and names phrases already written that could vary (the editor
underlines them; a click wraps one in brackets) and a few things the prompt doesn't mention
that would be worth varying ("+ light"), each with where it would go and the words that join
it (after "on a porch", ", lit by <light>"). Clicking one splices it in with no model call
(`splice`); when the prompt has moved on and that no longer fits, Add asks the model for just
the place and the join, and the slot goes at the end of the text when that fails too.

When the picture is a photo, the chips also offer the parts of its photography the prompt
doesn't have yet (light, angle, lens, film look, framing), each from its vocabulary list rather
than written by the model each time. The same reply says whether it is a photo and which of
those parts the prompt already states; a reply without those fields readable offers none of
them. The model may name the light itself ("+ window light"), which then stands in for the
plain "+ light".

The model decides what could vary and how the words join. Code checks only structure: that
a phrase is an exact stretch of the prompt where a slot can stand, the counts, and that a
join's words occur once and its insert adds the one slot and nothing else. Both replies are plain JSON; a reply that can't be read gets
one retry saying what was wrong.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from core.logging import get_logger
from prompt_programs.narrow import Ask, NarrowCache
from prompt_programs.slots import _VERBATIM, SLOT_RE, _line_marks, _lines, find_slots, is_comment

log = get_logger(__name__)

SUGGEST_VERSION = "suggest-4"   # suggest-4: photography per part (light, angle, lens, film look, framing); the model may name the light. suggest-3: each add says where it goes. suggest-2: the reply says whether the picture is a photo and what photography it states
MAX_VARY = 6
MAX_ADDS = 3
MAX_PHOTO_ADDS = 2   # a photo's own adds, beside its photography
MAX_PHOTO_PARTS = 3  # a photo's photography chips
MAX_OFFERED = 5      # every chip together
ADD_TOKENS = 64      # Add's reply is only the place and the join


class Part(NamedTuple):
    """One part of a photo's photography, offered as its own chip."""
    part: str                # how the reply names it, in `stated` and `joins`
    name: str                # the slot's words
    label: str               # its chip
    kind: str                # the reader's kind for that slot
    lists: Tuple[str, ...]   # the lists that slot draws from, or a node whose lists it draws from


# The photography a photo is offered, one chip per part the prompt doesn't state, in this order,
# which is what most improves a photo prompt: light sets the look of the whole picture and is
# what a prompt most often leaves to chance; the angle changes what the picture shows of its
# subject; the lens its depth and perspective; the film look its color and grain; framing comes
# last, since the subject and the place usually imply it already. <light> is one named look
# among the lighting lists; each camera part is a list slot on its own camera list (the reader
# reads words naming one camera part as that list). The camera directory's other lists (color
# grade, genre, composition) would be list slots too, but not every reader binds those reliably
# yet: a slot read as written would send its bare words.
PHOTO: Tuple[Part, ...] = (
    Part("light", "light", "light", "light", ("lighting",)),
    Part("angle", "camera angle", "angle", "list", ("camera.angle",)),
    Part("lens", "lens", "lens", "list", ("camera.lens",)),
    Part("film_look", "film look", "film look", "list", ("camera.film_look",)),
    Part("shot_size", "framing", "framing", "list", ("camera.shot_size",)),
)
# Names a photo's own adds can't take: the parts' slots, and the whole camera they make up.
PHOTO_NAMES = frozenset({p.name for p in PHOTO} | {"camera"})

Span = Tuple[int, int]

SUGGEST_SYSTEM = """You help someone write an image prompt that makes a different picture each time it runs. They mark the parts that should change from picture to picture with angle brackets: "dorm room with a <young man>, lit by <light>". Any words can be marked: <elderly African man>, <teenage boy>, <pet>, <rainy street>.

Read their prompt and suggest two things.

vary: phrases already written in the prompt that would be worth changing from picture to picture. Prefer what a person would most want to differ between pictures: who is in it, what they wear, the place, an animal, a thing they hold or use. Copy each phrase exactly as it is written, as the smallest stretch that names the thing together with the words that describe it: "young man", not "a young man in"; "red leather jacket", not "a red leather jacket and". Never the whole prompt and never a verb alone. Leave out anything already in angle brackets, square brackets or curly braces. At most 6, the best first. Fewer is fine, and so is none.

adds: things the prompt doesn't mention at all that would be worth varying in this picture. Only what is truly missing: if the prompt already says anything about it, leave it out. What fits depends on the prompt: for a portrait perhaps the background or the light, for a street scene the weather or the time of day, for a product shot the surface it stands on. Name each in one or two plain words, in the prompt's own way of speaking. At most 3, the best first. When photo is true: leave the camera out of adds (its framing, angle, lens and film look are offered anyway); when the prompt says nothing about the light, one add may be the light, named as the look of light that would suit this picture best, with "part": "light"; at most 2 adds besides that light.

For each add, also say where it would be written in: after, the few words of the prompt right before that place, copied exactly, enough that they occur only once in the prompt (usually two to five words, never from a line starting with #); and insert, what goes right after them: the add's name in angle brackets with the words that join it, written the way the prompt is written. A prompt with joining words between the things it names ("with", "on", "at", a verb), even a short one, gets words that make it read as part of the phrase: ", lit by <light>", " in <weather>". A prompt of bare tags between commas gets only the tag: ", <light>". Put it where it reads naturally, usually after what it belongs to.

Then say two more things.

photo: true when the picture is meant to look like a photograph, as any prompt that names no other medium is; false when it asks for a painting, drawing, illustration, anime, cartoon, 3D render or another look that isn't a photograph. A prompt written as anime-style tags ("1girl, solo") is anime unless its tags ask for a photo.

stated: the parts of the photography the prompt already says anything about, from these names:
- "shot_size": the framing, how much of the subject shows: a close-up, a full-length shot, a selfie, a group shot.
- "angle": where the camera looks from: eye level, a low or high angle, overhead, a tilted angle.
- "lens": the lens and focus: wide-angle or telephoto, depth of field, bokeh, motion blur.
- "film_look": the film or format: a film stock, a phone camera, a disposable camera, an instant photo, digital capture.
- "light": the light: its source, look, quality or the time of day that sets it.
Count a part only when the prompt says something about that part itself: "cell phone selfie" says the framing (a selfie) and the format (a phone camera), not the angle or the lens. A part in angle brackets counts. Only those names, never the prompt's words: [], ["light"], ["shot_size", "film_look"].

joins: when photo is true, for each part not in stated, where it would be written in, as for an add, with these words in the angle brackets: <light> for "light", <camera angle> for "angle", <lens> for "lens", <film look> for "film_look", <framing> for "shot_size". {} when photo is false.

Lines starting with # are notes from the user, not part of the picture's text. Never take a phrase from them. They may say what the user does or doesn't want to vary: follow them.

Reply with JSON only, in this shape:
{"vary": ["young man", "dorm room"], "adds": [{"name": "poster", "label": "poster", "after": "dorm room", "insert": " with a <poster> on the wall"}, {"name": "desk lamp glow", "label": "desk lamp", "part": "light", "after": "reading", "insert": " by <desk lamp glow>"}], "photo": true, "stated": ["shot_size"], "joins": {"light": {"after": "reading", "insert": ", lit by <light>"}, "angle": {"after": "reading", "insert": ", seen from <camera angle>"}, "lens": {"after": "reading", "insert": ", shot with <lens>"}, "film_look": {"after": "reading", "insert": ", shot on <film look>"}}}
For each add, name is the words that would go in the angle brackets and label is the one or two words shown on its button."""

ADD_SYSTEM = """You add one changing part to an image prompt. The user marks the parts that change from picture to picture with angle brackets: "dorm room with a <young man>, lit by <light>". They ask you to add a new one. You say where it goes and the words that join it, the way they would have written it themselves.

after: the few words of the prompt right before the place it goes, copied exactly, enough that they occur only once in the prompt (usually two to five words). Never from a line starting with #, and never inside angle brackets, square brackets or curly braces.

insert: what goes right after them: the new part in angle brackets, with exactly the words you were given, and the words that join it. A prompt with joining words between the things it names ("with", "on", "at", "a", a verb), even a short one, gets words that make it read as part of the phrase: ", lit by <light>", " in <weather>", ", under a <sky>". A prompt of bare tags between commas ("1girl, long hair, school rooftop") gets only the tag: ", <light>". Nothing else in brackets or braces. Put it where it reads naturally, usually after what it belongs to.

Reply with JSON only, in this shape:
{"after": "reading on a porch at dusk", "insert": ", lit by <light>"}"""


async def ask_model(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int) -> str:
    """One plain completion from the chat model the editor's helpers use."""
    from llm import llm_complete_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("prompt-program"):
        # Nothing Fluent asks needs reasoning: ask for none, and never retry with room for it.
        return await llm_complete_text(config=cfg, messages=messages, max_tokens=max_tokens, temperature=0.3,
                                       enable_thinking=False, retry_reasoning=False)


async def model_name(project_id: Optional[int]) -> str:
    """The chat model (never its credentials): part of the suggestion cache key."""
    from llm_resolver import get_effective_llm_config
    try:
        cfg = await get_effective_llm_config("tool_assistant", project_id)
        return str(cfg.get_model() or "")
    except Exception:  # no chat model configured: the call itself says so
        return ""


def cache_for(profile_id: Optional[str]) -> NarrowCache:
    """The profile's suggestion cache on disk, one small JSON file per prompt."""
    import app_dirs
    from core.profile_context import get_current_profile
    return NarrowCache(Path(app_dirs.get_profile_dir(profile_id or get_current_profile())) / "prompt_programs" / "suggest")


def _json_object(reply: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def _blocked(prompt: str) -> Tuple[List[Span], List[Span]]:
    """(where no phrase may sit, the existing slots): comment lines, verbatim brackets,
    lists, {{names}} and slots, in prompt offsets."""
    blocked: List[Span] = []
    slots: List[Span] = []
    for _, at, line in _lines(prompt):
        if is_comment(line):
            blocked.append((at, at + len(line)))
            continue
        s, lists, names = _line_marks(line)
        verbatim = [m.span() for m in _VERBATIM.finditer(line)]
        slots += [(at + a, at + b) for a, b in s]
        blocked += [(at + a, at + b) for a, b in s + lists + names + verbatim]
    return blocked, slots


def _overlaps(a: int, b: int, spans: List[Span]) -> bool:
    return any(a < y and x < b for x, y in spans)


def _fits(prompt: str, a: int, b: int) -> bool:
    """Whether brackets around prompt[a:b] would make a slot there: whole words, the slot
    grammar's words, and found as a slot once wrapped."""
    if a > 0 and prompt[a - 1].isalnum() and prompt[a].isalnum():
        return False
    if b < len(prompt) and prompt[b].isalnum() and prompt[b - 1].isalnum():
        return False
    wrapped = prompt[:a] + "<" + prompt[a:b] + ">" + prompt[b:]
    return (a, b + 2) in find_slots(wrapped)


def _body(prompt: str) -> str:
    """The prompt's picture text: its non-comment lines."""
    return "\n".join(line for _, _, line in _lines(prompt) if not is_comment(line)).strip()


def check_suggestions(prompt: str, got: Dict[str, Any]) -> Dict[str, Any]:
    """The reply's usable suggestions, and `photo`: read_photo's answer. A phrase is kept at its
    first stretch of the prompt where a slot could stand, outside comment lines, verbatim,
    lists, names and slots, and not over a phrase kept before it; the whole prompt is not a
    phrase. For a photo, the model's adds leave out the camera, whose parts offered_adds
    offers, and keep one add the reply marks as the light (`"part": "light"`), only when the
    prompt doesn't state the light; it then stands in for the plain light."""
    blocked, slots = _blocked(prompt)
    body = _body(prompt)
    kept: List[Dict[str, Any]] = []
    for item in got.get("vary") if isinstance(got.get("vary"), list) else []:
        text = item.get("text") if isinstance(item, dict) else item
        if not isinstance(text, str):
            continue
        text = text.strip()
        if len(text) < 2 or text == body:
            continue
        at = prompt.find(text)
        while at >= 0:
            b = at + len(text)
            if not _overlaps(at, b, blocked) and not _overlaps(at, b, [(k["from"], k["to"]) for k in kept]) \
                    and _fits(prompt, at, b):
                kept.append({"from": at, "to": b, "text": text})
                break
            at = prompt.find(text, at + 1)
        if len(kept) == MAX_VARY:
            break
    kept.sort(key=lambda k: k["from"])

    photo = read_photo(got)
    # A photo's camera comes from the vocabulary (offered_adds), one part at a time, not from the model.
    own = PHOTO_NAMES if photo is not None else frozenset()
    taken = {prompt[a + 1:b - 1].casefold() for a, b in slots} | {k["text"].casefold() for k in kept}
    adds: List[Dict[str, Any]] = []
    light = None
    for item in got.get("adds") if isinstance(got.get("adds"), list) else []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"].strip()
        label = item.get("label").strip() if isinstance(item.get("label"), str) and item["label"].strip() else name
        if not SLOT_RE.fullmatch(f"<{name}>") or name.casefold() in taken or name.casefold() in own:
            continue
        part = item.get("part") if photo is not None and isinstance(item.get("part"), str) else ""
        if part and part.strip().casefold() in {p.part for p in PHOTO}:
            # Photography: only the light, once, when the prompt has none; the camera's parts
            # are offered from the vocabulary.
            if part.strip().casefold() != "light" or light is not None or "light" in photo:
                continue
            taken.add(name.casefold())
            light = {"name": name, "label": label, "part": "light", **checked_join(prompt, name, item)}
            continue
        if len(adds) == (MAX_PHOTO_ADDS if photo is not None else MAX_ADDS):
            continue
        taken.add(name.casefold())
        adds.append({"name": name, "label": label, **checked_join(prompt, name, item)})
    joins = got.get("joins") if photo is not None and isinstance(got.get("joins"), dict) else {}
    photo_joins = {p.part: j for p in PHOTO if (j := checked_join(prompt, p.name, joins.get(p.part)))}
    return {"vary": kept, "adds": adds + ([light] if light else []), "photo": photo, "joins": photo_joins}


def checked_join(prompt: str, name: str, item: Any) -> Dict[str, str]:
    """{after, insert} from a reply's item when splicing them into the prompt writes in <name>
    and nothing else; {} when they're missing or don't fit (the click then asks Add)."""
    if not isinstance(item, dict):
        return {}
    done, problem = splice(prompt, name, item.get("after"), item.get("insert"))
    if done is None:
        log.info(f"[suggest] the join for <{name}> isn't used: {problem}")
        return {}
    return {"after": item["after"], "insert": item["insert"]}


def read_photo(got: Dict[str, Any]) -> Optional[List[str]]:
    """The parts of its photography the prompt already states (PHOTO's `part` names) when the
    reply says the picture is a photo; None when it isn't one, or when its `photo` or `stated`
    can't be read (logged: no photography is offered then). Unknown names in `stated` are
    skipped."""
    photo = got.get("photo")
    if photo is False:
        return None
    stated = got.get("stated")
    if photo is not True or not isinstance(stated, list) or not all(isinstance(x, str) for x in stated):
        log.info(f"[suggest] no usable photo/stated in the reply: photo={photo!r}, stated={stated!r}"[:240])
        return None
    said = {x.strip().casefold() for x in stated}
    return [p.part for p in PHOTO if p.part in said]


def photo_lists(lists: Tuple[str, ...]) -> List[str]:
    """The vocabulary lists a photography add draws from: each id that is a list, and every list
    under one that is a node. Ids the vocabulary doesn't have are left out."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    out: List[str] = []
    for lid in lists:
        if lid in vocab.leaves:
            out.append(lid)
        elif lid in vocab.nodes:
            out += sorted(k for k in vocab.leaves if k.startswith(lid + "."))
    return list(dict.fromkeys(out))


def offered_adds(prompt: str, checked: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The checked reply's own adds, then, for a photo, the photography parts the prompt doesn't
    state and has no slot of, nor an add of the same words, in PHOTO's order: the model's named
    light in the light's place when it gave one, at most MAX_PHOTO_PARTS of them, and at most
    MAX_OFFERED chips in all. A photography add also carries the reader's `kind` for it and the
    `lists` it draws from, so the editor can leave it out once a slot is read as that."""
    checked_adds = checked.get("adds") or []
    adds = [a for a in checked_adds if not a.get("part")]
    stated = checked.get("photo")
    if not isinstance(stated, list):
        return adds[:MAX_OFFERED]
    light = next((a for a in checked_adds if a.get("part") == "light"), None)
    _, slots = _blocked(prompt)
    taken = {prompt[a + 1:b - 1].strip().casefold() for a, b in slots} | {a["name"].casefold() for a in adds}
    photo: List[Dict[str, Any]] = []
    for p in PHOTO:
        if p.part in stated:
            continue
        have = photo_lists(p.lists)
        if not have:
            continue
        if p.part == "light" and light is not None and light["name"].casefold() not in taken:
            photo.append({"name": light["name"], "label": light["label"], "kind": p.kind, "lists": have,
                          **({"after": light["after"], "insert": light["insert"]} if "insert" in light else {})})
        elif p.name.casefold() not in taken:
            join = (checked.get("joins") or {}).get(p.part)
            photo.append({"name": p.name, "label": p.label, "kind": p.kind, "lists": have,
                          **(join if isinstance(join, dict) else {})})
    return (adds + photo[:MAX_PHOTO_PARTS])[:MAX_OFFERED]


def suggest_key(prompt: str, model: str) -> str:
    blob = json.dumps([SUGGEST_VERSION, model, prompt], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


async def suggest(prompt: str, ask: Optional[Ask] = None, cache: Optional[NarrowCache] = None,
                  project_id: Optional[int] = None, model: str = "", raw: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """{"vary": [{from, to, text}], "adds": [{name, label, after?, insert?}, ...]} for the
    prompt as sent; a photo's photography adds also carry {kind, lists}. No call for an empty prompt (or only
    comment lines) or Raw mode. The checked reply is cached by the exact prompt; a reply that
    can't be read twice gives nothing and isn't cached."""
    empty: Dict[str, List[Dict[str, Any]]] = {"vary": [], "adds": []}
    if raw or not _body(prompt):
        return empty
    ask = ask or ask_model
    key = suggest_key(prompt, model)
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict) and isinstance(hit.get("vary"), list) and isinstance(hit.get("adds"), list):
            return {"vary": hit["vary"], "adds": offered_adds(prompt, hit)}
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SUGGEST_SYSTEM},
                                      {"role": "user", "content": f"The prompt:\n{prompt}"}]
    for attempt in range(2):
        reply = await ask(messages, project_id, 800)
        got = _json_object(reply)
        if got is not None:
            checked = check_suggestions(prompt, got)
            if cache is not None:
                cache.put_raw(key, checked)
            return {"vary": checked["vary"], "adds": offered_adds(prompt, checked)}
        log.info(f"[suggest] unreadable reply (try {attempt + 1}): {str(reply)[:160]!r}")
        messages = messages + [{"role": "assistant", "content": str(reply or "")},
                               {"role": "user", "content": "That reply wasn't a JSON object, so none of it could be used. "
                                                           "Reply with only the JSON, in the shape shown."}]
    return empty


# --------------------------------------------------------------------------- add

def _marks(prompt: str) -> List[Tuple[str, str, Span]]:
    """Comment lines, slots, lists, {{names}} and verbatim brackets, in order: what Add must keep."""
    out: List[Tuple[str, str, Span]] = []
    for _, at, line in _lines(prompt):
        if is_comment(line):
            out.append(("comment", line, (at, at + len(line))))
            continue
        slots, lists, names = _line_marks(line)
        verbatim = [m.span() for m in _VERBATIM.finditer(line)]
        found = [("slot", s) for s in slots] + [("list", s) for s in lists] + [("name", s) for s in names] + \
                [("verbatim", s) for s in verbatim if not _overlaps(*s, lists + names)]
        for kind, (a, b) in sorted(found, key=lambda f: f[1][0]):
            out.append((kind, line[a:b], (at + a, at + b)))
    return out


def check_added(before: str, after: str, name: str) -> Tuple[Optional[Span], str]:
    """(the new slot's span, "") when `after` is `before` with one slot of `name` written in
    and nothing else changed; else (None, what is wrong, said plainly)."""
    old, new = _marks(before), _marks(after)
    old_slots = sum(1 for m in old if m[0] == "slot")
    new_slots = sum(1 for m in new if m[0] == "slot")
    if new_slots != old_slots + 1:
        return None, (f"it has {new_slots - old_slots} new parts in angle brackets; it needs exactly one, <{name}>"
                      if new_slots > old_slots else f"it has no new part in angle brackets; it needs exactly one, <{name}>")
    kept = [(k, t) for k, t, _ in old]
    added = None
    for i, (kind, text, span) in enumerate(new):
        if kind == "slot" and [(k, t) for k, t, _ in new[:i] + new[i + 1:]] == kept:
            added = (text, span)
            break
    if added is None:
        rest = [(k, t) for k, t, _ in new]
        for k, t in kept:
            if (k, t) not in rest:
                what = "a note line" if k == "comment" else f'"{t}"'
                return None, f"it changed or left out {what}, which must stay exactly as it was"
            rest = rest[rest.index((k, t)) + 1:]
        if len(new) > len(old) + 1:
            return None, "it added other parts in brackets or braces; add only the one new part"
        return None, "it moved parts that were already there; keep them where they were"
    text, span = added
    if text[1:-1].casefold() != name.casefold():
        return None, f"the new part is {text}; it must be <{name}>"
    head = 0
    while head < min(len(before), len(after)) and before[head] == after[head]:
        head += 1
    tail = 0
    while tail < min(len(before), len(after)) - head and before[-1 - tail] == after[-1 - tail]:
        tail += 1
    inserted = after[head:len(after) - tail]
    if head + tail != len(before) or "\n" in inserted:
        return None, "it changed words that were already there; keep every character and only insert the new words"
    return span, ""


def plain_add(prompt: str, name: str) -> Dict[str, Any]:
    """`, <name>` at the end of the last non-comment line with text; a line of its own when
    there is none."""
    slot = f"<{name}>"
    lines = prompt.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if line.strip() and not is_comment(line):
            end = len(line.rstrip())
            lines[i] = line[:end] + ", " + slot + line[end:]
            at = sum(len(x) + 1 for x in lines[:i]) + end + 2
            return {"prompt": "\n".join(lines), "slot": {"from": at, "to": at + len(slot)}}
    if not prompt.strip():
        return {"prompt": slot, "slot": {"from": 0, "to": len(slot)}}
    joined = prompt.rstrip("\n") + "\n"
    return {"prompt": joined + slot, "slot": {"from": len(joined), "to": len(joined) + len(slot)}}


_BRACKETS = re.compile(r"[<>\[\]{}]")


def splice(prompt: str, name: str, after: Any, insert: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """({"prompt", "slot": {from, to}}, "") with `insert` written in right after `after`, when
    that fits: `after` occurs exactly once in the prompt and doesn't end inside a word,
    `insert` holds <name> once and nothing else in brackets or braces, and the result is the
    prompt with that one slot added and every other mark kept (check_added). Else (None, what
    is wrong, said plainly)."""
    if not isinstance(after, str) or not isinstance(insert, str) or not after.strip():
        return None, 'it needs "after", words from the prompt, and "insert"'
    at = prompt.find(after)
    if at < 0:
        return None, f'"{after}" is not in the prompt; copy the words exactly'
    if prompt.find(after, at + 1) >= 0:
        return None, f'"{after}" is in the prompt more than once; give enough words that it occurs once'
    slot = f"<{name}>"
    if insert.count(slot) != 1 or _BRACKETS.search(insert.replace(slot, "")) or "\n" in insert:
        return None, f'"insert" must hold {slot} once, and nothing else in brackets or braces'
    p = at + len(after)
    before, rest = prompt[:p], prompt[p:]
    if before[-1:].isalnum() and (rest[:1].isalnum() or insert[:1].isalnum() or insert[:1] == "<"):
        return None, f'"{after}" ends inside a word, or "insert" runs into it; start "insert" with a space or a comma'
    if (rest[:1].isalnum() or rest[:1] == "<") and not insert[-1:].isspace():
        return None, '"insert" runs into the next word; end it with a space'
    out = before + insert + rest
    span, problem = check_added(prompt, out, name)
    if span is None:
        return None, problem
    return {"prompt": out, "slot": {"from": span[0], "to": span[1]}}, ""


async def add(prompt: str, name: str, ask: Optional[Ask] = None, project_id: Optional[int] = None,
              after: Optional[str] = None, insert: Optional[str] = None,
              suggested_for: Optional[str] = None) -> Dict[str, Any]:
    """{"prompt": the prompt with <name> written in, "slot": {from, to}} (the span includes the
    brackets). With Suggest's `after` and `insert`, made for exactly this prompt
    (`suggested_for`) and fitting it, no model call: a join for an earlier prompt can still find
    its words in an edited one, yet land beside what the edit added.
    Else the model says only where it goes and the join; a reply that doesn't fit is asked
    again once, and after that `, <name>` goes at the end of the last non-comment line."""
    name = name.strip()
    if after is not None or insert is not None:
        done, problem = splice(prompt, name, after, insert) if suggested_for == prompt else \
            (None, "it was made for another prompt")
        if done is not None:
            return done
        log.info(f"[add] Suggest's join for <{name}> isn't used: {problem}")
    if not _body(prompt):
        return plain_add(prompt, name)
    ask = ask or ask_model
    messages: List[Dict[str, Any]] = [{"role": "system", "content": ADD_SYSTEM},
                                      {"role": "user", "content": f"The prompt:\n{prompt}\n\nAdd: <{name}>"}]
    for attempt in range(2):
        reply = await ask(messages, project_id, ADD_TOKENS)
        got = _json_object(reply)
        if got is None:
            problem = 'it wasn\'t a JSON object with "after" and "insert"'
        else:
            done, problem = splice(prompt, name, got.get("after"), got.get("insert"))
            if done is not None:
                return done
        log.info(f"[add] reply not used (try {attempt + 1}): {problem}; {str(reply)[:160]!r}")
        messages = messages + [{"role": "assistant", "content": str(reply or "")},
                               {"role": "user", "content": f"That reply couldn't be used: {problem}. Reply again with only "
                                                           'the JSON, {"after": ..., "insert": ...}.'}]
    return plain_add(prompt, name)

"""Suggest: the editor's recommendations for a Fluent prompt, in two kinds.

phrases  up to 3 phrases the user wrote worth changing from picture to picture, each with a
         way: "detail" (Add Detail: keep the words true and make each picture a specific, fully
         described one of them: "dog", "boy", the Eiffel Tower seen new ways) or "any" (Add
         Variety: the words become one of their kind and the others come in: "short bob" -> a
         hairstyle). Every phrase also names its kind ("hairstyle") so the editor can offer both,
         and a label, one or two plain words naming the thing ("dog", "hairstyle"). The editor
         underlines them and shows a chip ("Add Detail: dog", "Add Variety: hairstyle"); Add
         Detail wraps the words in brackets, Add Variety writes the kind in their place, in
         brackets.
adds     things good prompts of this kind state and this one leaves to the image model's habits,
         each written in as a new slot: the camera of a photo, the face of a person. They come
         from a fixed list (ADDS); the model only says which apply.

The model decides meaning; code checks only structure: a phrase is an exact stretch of the
prompt where a slot can stand, a kind is plain words, and the counts fit. [exact text] is never
sent: the model reads [EXACT_1] tokens (`hidden`), and replies are checked against the prompt
as typed. A reply that can't be read is asked once more, then gives nothing, quietly.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger
from prompt_programs.narrow import Ask, NarrowCache
from prompt_programs.slots import _VERBATIM, _line_marks, _lines, find_slots, is_comment

log = get_logger(__name__)

SUGGEST_VERSION = "suggest-12"   # suggest-12: a kind may be "none" (nothing wider), and that answer is kept; "any" only for a phrase with a wider kind. suggest-11: phrases give a label for their chip. suggest-10: people listed, faces described or not. suggest-9: the person a face is offered for may be a slot; phrases on screen stay. suggest-8: phrases say detail (more specific) or any (its kind), with their kind; adds are slots from a fixed list (camera, face), no fixed words. suggest-7: "one" labels say flesh out. suggest-6: vary phrases say how. suggest-5: vary, looks and adds.
MAX_PHRASES, MAX_ANY = 3, 1
SUGGEST_TOKENS = 400
KIND_TOKENS = 40
NO_KIND = "none"   # the kind reply that says there is nothing wider

Span = Tuple[int, int]

SUGGEST_SYSTEM = """You help someone get more out of an image prompt that makes many pictures at once. Their prompt may mark parts that change from picture to picture with angle brackets: "a <young woman> in a kitchen". Curly braces hold choices. Square brackets hold exact words the user keeps hidden, shown as tokens like [EXACT_1]: never copy them, never touch them, never suggest anything inside them. Lines starting with # are their notes: follow them, never copy from them.

Image models fall into the same habits whenever a prompt leaves something open: "dog" gives the same golden retriever every time, "a boy" the same face. You find where that will happen.

phrases: the one to three phrases already written in the prompt that would be most rewarding to change from picture to picture. Copy each exactly as written, the shortest stretch that names the thing with its own describing words, without "a" or "the": "farmer", "rural Vietnam", "short bob", not "a farmer in". One thing per phrase, without what it is doing. Never anything already inside brackets or braces, never the whole prompt. For each give:
- way: "detail" or "any".
  "detail" keeps their words true in every picture and makes each picture a specific, fully described one of them. Use it for broad, plain words the image model would fill the same way every time: people ("boy", "woman", "farmer"), animals ("dog", "fox"), places ("rural Vietnam", "a kitchen"), things ("old car", "house"). Also for one specific thing to show in different ways: a particular place, landmark, building, brand, work, character or real person ("Eiffel Tower", "Sherlock Holmes", "Shinjuku"). These come first: they matter most.
  "any" is for a specific choice the user made that could open up to others of its kind: "short bob" (any hairstyle), "golden retriever" (any dog), "red dress" (any dress), "Paris" (any city). Give at most one "any", and only when a phrase like that is in the prompt. Never "any" for a phrase whose kind is no wider than its words.
- kind: the plain word for what kind of thing it is, one or two words, singular, that could stand in the prompt in its place: "hairstyle" for "short bob", "dog" for "golden retriever", "animal" for "dog", "person" for "boy", "city" for "Paris", "landmark" for "Eiffel Tower".
- names: "one" when it names one specific thing (a particular place, landmark, brand, character, person), else "kind".
- label: one or two plain words naming the thing, for a button, however long the phrase is: "dog" for "scruffy old dog", "hairstyle" for "short bob", "jacket" for "worn leather jacket", "Eiffel Tower" for "Eiffel Tower".
Give none when nothing is worth it.

medium: "photo" when the picture should look like a photograph, as any prompt that names no other medium should; otherwise its medium in one to three words: "watercolor", "vector logo", "anime illustration". A prompt written as anime-style tags ("1girl, solo") is an anime illustration unless its tags ask for a photo.

camera_stated: true when the prompt already says how the photo is taken: the kind of photo, the film or format, the framing or lens, or the light. Otherwise false.

people: every human in the picture, each copied exactly as written, the shortest stretch that names them ("boy", "old fisherman"). Humans in angle brackets count too: give their words without the brackets ("woman" for "<woman>"). Never an animal or a thing. [] when there are none.

face_described: true when the prompt already says what any of their faces look like (features, expression, makeup), else false.

Reply with JSON only, in this shape:
{"phrases": [{"phrase": "dog", "way": "detail", "kind": "animal", "names": "kind", "label": "dog"}], "medium": "photo", "camera_stated": false, "people": ["boy"], "face_described": false}"""

KIND_SYSTEM = """You name the wider kind of a phrase in an image prompt: the plain word that could stand in the prompt in its place so the pictures show other things of that kind. Reply with only that word, one or two words, singular: "hairstyle" for "short bob", "dog" for "golden retriever", "animal" for "dog", "person" for "woman", "city" for "Paris", "dress" for "red dress", "landmark" for "Eiffel Tower".

Reply "none" when no plain, wider word would read naturally in the prompt in the phrase's place and give a meaningfully broader mix. The wider word must take in many things the phrase leaves out; another word for the same thing ("human" for "person") is not wider. Words that are already as wide as plain words go have nothing wider: "person", "thing", "place", "animal", "object"."""


def hidden(prompt: str) -> str:
    """The prompt as a model may read it: [exact text] is the user's and never sent; each
    becomes a token like [EXACT_1]. Replies are checked against the prompt as typed, so a
    phrase or join that names a token simply isn't found there and is dropped."""
    from prompt_programs.program import mask_exact
    return mask_exact(prompt)[0]


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


# Marks a kind may not hold: it would add a slot, a list, exact text or a note.
_MARKS = re.compile(r"[<>\[\]{}|#]")


def _label(value: Any, text: str) -> str:
    """A phrase's chip label as the model gave it, trimmed: plain words, at most three of them.
    Else the phrase's last two words."""
    k = " ".join(value.split()).strip(".") if isinstance(value, str) else ""
    if k and len(k.split()) <= 3 and len(k) <= 30 and not _MARKS.search(k):
        return k
    return " ".join(text.split()[-2:])


def _kind(value: Any) -> str:
    """A kind as the model gave it: plain words, one to three of them, else ""."""
    k = value.strip().strip(".").strip() if isinstance(value, str) else ""
    return k if k and len(k.split()) <= 3 and len(k) <= 30 and not _MARKS.search(k) and "\n" not in k else ""


# The things a prompt can be given as a new slot, each when the reply says it applies: what
# chip it shows and the words it writes. `place` is "end" (after a comma at the end of the last
# picture line) or "after_person" (right after the person the reply names).
ADDS: List[Dict[str, str]] = [
    {"key": "face", "label": "Face", "slot": "face", "join": " with ", "place": "after_person"},
    {"key": "camera", "label": "Camera", "slot": "camera", "join": ", ", "place": "end"},
]


def _end_of_picture(prompt: str) -> Optional[int]:
    """Where words go at the end of the last picture line (not a # note line), else None."""
    best = None
    for _, at, line in _lines(prompt):
        if line.strip() and not is_comment(line):
            best = at + len(line.rstrip())
    return best


def _find_phrase(prompt: str, text: str, blocked: List[Span], taken: List[Span]) -> Optional[Span]:
    """The first stretch of the prompt that is `text`, outside blocked spans and the ones
    already taken, where a slot could stand."""
    at = prompt.find(text)
    while at >= 0:
        b = at + len(text)
        if not _overlaps(at, b, blocked) and not _overlaps(at, b, taken) and _fits(prompt, at, b):
            return at, b
        at = prompt.find(text, at + 1)
    return None


def check_suggestions(prompt: str, got: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The reply's usable suggestions. A phrase is kept at its first stretch of the prompt where
    a slot could stand, outside comment lines, verbatim, lists, names and slots, and not over a
    phrase kept before it; the whole prompt is not a phrase. "any" needs a kind (else it is
    "detail"), and only one "any" is kept. A phrase the editor shows now (`previous`) stays
    as it was (its label too) while it can still become a slot, whatever the reply says. A label
    is the reply's, trimmed, when it is plain words, at most three; else the phrase's last two words. An add is kept when the reply says it applies and
    the prompt has no slot of those words yet."""
    blocked, slots = _blocked(prompt)
    body = _body(prompt)
    phrases: List[Dict[str, Any]] = []
    anys = 0
    shown = [p for p in (previous or {}).get("phrases") or [] if isinstance(p, dict)]
    kept = [{"phrase": p.get("text"), "way": p.get("way"), "kind": p.get("kind"), "names": p.get("mode"),
             "label": p.get("label")} for p in shown]
    replied = got.get("phrases") if isinstance(got.get("phrases"), list) else []
    shown_texts = {str(p.get("phrase") or "").strip() for p in kept}
    for i, item in enumerate(kept + replied):
        if not isinstance(item, dict) or not isinstance(item.get("phrase"), str):
            continue
        text = item["phrase"].strip()
        if i >= len(kept) and text in shown_texts:
            continue   # the reply repeating a phrase on screen: it stays where it is, once
        if len(text) < 2 or text == body:
            continue
        span = _find_phrase(prompt, text, blocked, [(v["from"], v["to"]) for v in phrases])
        if not span:
            continue
        kind = _kind(item.get("kind"))
        if kind.lower() in (NO_KIND, text.lower()):
            kind = ""
        way = "any" if str(item.get("way") or "").strip().lower() == "any" and kind and anys < MAX_ANY else "detail"
        anys += way == "any"
        names = item.get("names")
        phrases.append({"from": span[0], "to": span[1], "text": text, "kind": kind, "way": way,
                        "mode": "one" if isinstance(names, str) and names.strip().lower() == "one" else "kind",
                        "label": _label(item.get("label"), text)})
        if len(phrases) == MAX_PHRASES + 1:
            break
    phrases.sort(key=lambda v: v["from"])

    slot_words = {prompt[a + 1:b - 1].strip().lower() for a, b in slots}
    medium = got.get("medium") if isinstance(got.get("medium"), str) else ""
    photo = medium.strip().lower() in ("", "photo", "photograph", "photography")
    adds: List[Dict[str, Any]] = []
    for add in ADDS:
        if add["slot"] in slot_words:
            continue
        at: Optional[int] = None
        if add["key"] == "camera":
            if not photo or got.get("camera_stated") is not False:
                continue
            at = _end_of_picture(prompt)
            if at is None:
                continue
        elif add["key"] == "face":
            if got.get("face_described") is not False:
                continue
            people = [p.strip() for p in got.get("people") if isinstance(p, str) and len(p.strip()) >= 2] \
                if isinstance(got.get("people"), list) else []
            for who in people:
                span = _find_phrase(prompt, who, blocked, [])
                if span:
                    at = span[1]
                    break
                # A person who is a slot ("a <woman> reading") takes the face after its bracket:
                # the slot's words hold theirs as a whole run ("man" is not in "<woman>").
                run = re.compile(rf"(?<!\w){re.escape(who)}(?!\w)")
                inside = [b for a, b in slots if run.search(prompt[a + 1:b - 1])]
                if inside:
                    at = inside[0]
                    break
            if at is None:
                continue
        text = f"{add['join']}<{add['slot']}>"
        # A person already described "with" something takes the face first: "a woman with
        # <face> and a short bob", not "a woman with <face> with a short bob".
        if add["place"] == "after_person" and at is not None and re.match(r"\s+with\s", prompt[at:]):
            at = at + re.match(r"\s+with\s+", prompt[at:]).end()
            text = f"<{add['slot']}> and "
        if add["place"] == "end" and at is not None and prompt[:at].rstrip().endswith((",", ";")):
            text = f" <{add['slot']}>"
        adds.append({"key": add["key"], "label": add["label"], "at": at, "text": text})
    return {"phrases": phrases, "adds": adds}


def suggest_key(prompt: str, model: str, previous: Optional[Dict[str, Any]] = None) -> str:
    blob = json.dumps([SUGGEST_VERSION, model, prompt, _previous(previous)], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _previous(previous: Optional[Dict[str, Any]]) -> List[str]:
    """The phrases the editor shows now, as lines for the model ("dog: detail, kind animal")."""
    out: List[str] = []
    for p in (previous or {}).get("phrases") or []:
        if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"].strip():
            way = "any" if p.get("way") == "any" else "detail"
            kind = _kind(p.get("kind"))
            out.append(f'{p["text"].strip()}: {way}' + (f", kind {kind}" if kind else ""))
    return out[:MAX_PHRASES + 2]


def _turn(prompt: str, previous: Optional[Dict[str, Any]] = None) -> str:
    """What the model reads: the prompt with exact text hidden, the parts that already vary, and
    the phrases already offered (kept as they were wherever they still fit)."""
    shown = hidden(prompt)
    turn = f"The prompt:\n{shown}"
    marked = [shown[a:b] for a, b in find_slots(shown)]
    if marked:
        turn += ("\n\nAlready changing from picture to picture: " + ", ".join(marked)
                 + ". Nothing you suggest may pin down what they leave open.")
    offered = _previous(previous)
    if offered:
        turn += ("\n\nOn screen now, from your last answer: " + "; ".join(offered)
                 + ". List each of these in phrases again, with the same phrase, way and kind, unless the "
                 "prompt no longer has it outside brackets. Then add any other phrase worth it.")
    return turn


EMPTY: Dict[str, List[Dict[str, Any]]] = {"phrases": [], "adds": []}


async def suggest(prompt: str, ask: Optional[Ask] = None, cache: Optional[NarrowCache] = None,
                  project_id: Optional[int] = None, model: str = "", raw: bool = False,
                  previous: Optional[Dict[str, Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """{"phrases": [{from, to, text, kind, way, mode, label}], "adds": [{key, label, at, text}]} for the
    prompt as sent. No call for an empty prompt (or only comment lines) or Raw mode.
    The checked reply is cached by the exact prompt; a reply that can't be read twice gives
    nothing and isn't cached."""
    if raw or not _body(prompt):
        return {k: [] for k in EMPTY}
    ask = ask or ask_model
    key = suggest_key(prompt, model, previous)
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict) and all(isinstance(hit.get(k), list) for k in EMPTY):
            return {k: hit[k] for k in EMPTY}
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SUGGEST_SYSTEM},
                                      {"role": "user", "content": _turn(prompt, previous)}]
    for attempt in range(2):
        reply = await ask(messages, project_id, SUGGEST_TOKENS)
        got = _json_object(reply)
        if got is not None:
            checked = check_suggestions(prompt, got, previous)
            if cache is not None:
                cache.put_raw(key, checked)
            return checked
        log.info(f"[suggest] unreadable reply (try {attempt + 1}): {str(reply)[:160]!r}")
        messages = messages + [{"role": "assistant", "content": str(reply or "")},
                               {"role": "user", "content": "That reply wasn't a JSON object, so none of it could be used. "
                                                           "Reply with only the JSON, in the shape shown."}]
    return {k: [] for k in EMPTY}


async def kind_of(prompt: str, start: int, end: int, ask: Optional[Ask] = None, cache: Optional[NarrowCache] = None,
                  project_id: Optional[int] = None, model: str = "") -> str:
    """The wider kind of the words at prompt[start:end] ("hairstyle" for "short bob"), for Add
    Variety; "" when there is nothing wider (the model says "none", or gives the words back) or it
    can't be said. Every answer the model gives is cached by the prompt and the span, the empty
    ones too, so words with nothing wider aren't asked about again."""
    words = prompt[start:end].strip() if 0 <= start < end <= len(prompt) else ""
    if not words or _MARKS.search(words):
        return ""
    ask = ask or ask_model
    key = hashlib.sha256(json.dumps([SUGGEST_VERSION, "kind", model, prompt, start, end],
                                    ensure_ascii=False).encode("utf-8")).hexdigest()[:32]
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict) and isinstance(hit.get("kind"), str):
            return hit["kind"]
    turn = f"The prompt:\n{hidden(prompt)}\n\nThe phrase: {words}"
    reply = await ask([{"role": "system", "content": KIND_SYSTEM}, {"role": "user", "content": turn}],
                      project_id, KIND_TOKENS)
    first = str(reply or "").strip().splitlines()[0] if str(reply or "").strip() else ""
    kind = _kind(first.strip().strip('"\'').strip(".").strip('"\''))
    # "none" is the answer that there is nothing wider; so is the words given back.
    if kind.lower() in (NO_KIND, words.lower()):
        kind = ""
    if cache is not None:
        cache.put_raw(key, {"kind": kind})
    return kind

"""Suggest: the editor's recommendations for a Fluent prompt, a few small separate ones.

vary   up to 3 phrases the user wrote that are worth changing from picture to picture, each
       with how: "vary" (a kind of thing: a different one in each picture) or "one" (one
       specific thing, flesh it out: the same thing shown different ways). The editor
       underlines them and shows a chip ("Vary this", "Flesh out this"); a click wraps the
       words in brackets, the slot set to that way.
looks  3 complete descriptions of how the picture is shot or made (for a photo: the kind of
       photo, framing and light together), unless the prompt already says so. A click adds
       the fixed words.
adds   up to 2 concrete things the picture lacks. A click adds the fixed words.

The model decides meaning; code checks only structure: a vary phrase is an exact stretch of
the prompt where a slot can stand, fixed words hold no marks, and the counts and lengths fit.
[exact text] is never sent: the model reads [EXACT_1] tokens (`hidden`), and replies are
checked against the prompt as typed. A reply that can't be read is asked once more, then
gives nothing, quietly.
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

SUGGEST_VERSION = "suggest-7"   # suggest-7: "one" labels say flesh out ("flesh out the Eiffel Tower"), not "more of". suggest-6: vary phrases say how (vary a kind, or flesh out one specific thing), up to 3. suggest-5: vary, looks and adds; fixed words, no photography slots. suggest-4: photography per part
MAX_VARY, MAX_LOOKS, MAX_ADDS = 3, 3, 2
SUGGEST_TOKENS = 400

Span = Tuple[int, int]

SUGGEST_SYSTEM = """You help someone make a better image prompt. Their prompt may mark parts that change from picture to picture with angle brackets: "a <young woman> in a kitchen". Curly braces hold choices. Square brackets hold exact words the user keeps hidden, shown as tokens like [EXACT_1]: never copy them, never touch them, never suggest anything inside them. Lines starting with # are their notes: follow them, never copy from them.

Offer a few small, separate improvements. Each one is a single click and changes one thing.

vary: the one to three phrases already written in the prompt that would be most rewarding to see change from picture to picture: usually who or what the picture is of, and the place. Copy each exactly as written, the shortest stretch that names the thing with its own describing words, without "a" or "the": "farmer", "rural Vietnam", not "a farmer in". One thing per phrase, without what it is doing. Never anything already inside brackets or braces, never the whole prompt. Each says how it would change, in "how":
- "vary" when the phrase names a kind of thing, so each picture can show a different one of it: "farmer", "fox", "rural Vietnam" (other places in it), "old car".
- "one" when it names one specific thing worth showing in different ways, the same thing in every picture while its state, angle, moment, details and surroundings change: a particular place, landmark, building, brand, work, character or real person ("Eiffel Tower", "Sherlock Holmes", "abandoned McDonald's", "Shinjuku"). Look for these too: they are often the most rewarding part of a prompt.
Each gets a label of two to five plain words that keeps their words and says they would see more of them: "different farmers", "other places in rural Vietnam", "different foxes" (not "different animals": the words they wrote stay); for "one", that this same thing would be fleshed out: "flesh out the Eiffel Tower", "flesh out Sherlock Holmes". Give none when nothing is worth it.

medium: "photo" when the picture should look like a photograph, as any prompt that names no other medium should; otherwise its medium in one to three words: "watercolor", "vector logo", "anime illustration". A prompt written as anime-style tags ("1girl, solo") is an anime illustration unless its tags ask for a photo.

shot_stated: true when the prompt already says how it is shot or made: two or more of the kind of photo, film or format, the framing or lens, and the light. Otherwise false.

looks: how the picture is shot or made, as three alternatives that suit this picture and differ plainly from each other. For a photo, each is one short phrase of 8 to 16 words that names the kind of photograph, the framing and the light together, in a photographer's words: "candid phone snapshot, slightly off-center, harsh midday sun"; "editorial portrait, 85mm lens, soft window light from the left"; "documentary photo, wide shot at eye level, flat overcast daylight". For another medium, the same for that medium: its technique, its composition and its palette or finish together, in that craft's words, never a camera's. Each gets a label of two to four words that names its style: "candid phone snapshot". Never contradict the prompt: when it names a time of day, the light fits it; when a part in angle brackets is the time of day or the light, say nothing about the time of day or where the light comes from. When shot_stated is true, give [].

adds: one or two concrete things you could see in the picture that it doesn't have yet and that would make it more complete or more believable: what the person or animal is doing, the time of day, the weather, a second subject, a telling detail of the place. Each is a short phrase of three to eight words that reads well added after a comma at the end of the prompt, written the way the prompt is written ("knee-deep in a flooded rice paddy", "steam rising from the broth"), never a category name ("activity", "weather"). Never anything the prompt already says in any words, and nothing about how it is shot or made. label: its two or three key words: "rice paddy".

Reply with JSON only, in this shape:
{"vary": [{"phrase": "farmer", "how": "vary", "label": "different farmers"}], "medium": "photo", "shot_stated": false, "looks": [{"text": "...", "label": "..."}], "adds": [{"text": "...", "label": "..."}]}"""


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


def _label(item: Dict[str, Any], fallback: str) -> str:
    lab = item.get("label")
    lab = lab.strip() if isinstance(lab, str) else ""
    return lab if lab and len(lab) <= 40 and not _MARKS.search(lab) else fallback


# Marks a fixed suggestion may not hold: it would add a slot, a list, exact text or a note.
_MARKS = re.compile(r"[<>\[\]{}|#]")


def _fixed(item: Any, words: Tuple[int, int]) -> Optional[Dict[str, str]]:
    """{text, label} of a look or an add: plain words, one line, within `words` words."""
    t = item.get("text") if isinstance(item, dict) else None
    if not isinstance(t, str):
        return None
    t = t.strip().rstrip(".").strip()
    if not (words[0] <= len(t.split()) <= words[1]) or _MARKS.search(t) or "\n" in t:
        return None
    return {"text": t, "label": _label(item, t)}


def check_suggestions(prompt: str, got: Dict[str, Any]) -> Dict[str, Any]:
    """The reply's usable suggestions. A vary phrase is kept at its first stretch of the prompt
    where a slot could stand, outside comment lines, verbatim, lists, names and slots, and not
    over a phrase kept before it; the whole prompt is not a phrase. Looks are dropped when the
    reply says the prompt already states how it is shot. Fixed words already in the prompt
    as written add nothing and are dropped."""
    blocked, _ = _blocked(prompt)
    body = _body(prompt)
    vary: List[Dict[str, Any]] = []
    for item in got.get("vary") if isinstance(got.get("vary"), list) else []:
        text = item.get("phrase") if isinstance(item, dict) else item
        if not isinstance(text, str):
            continue
        text = text.strip()
        if len(text) < 2 or text == body:
            continue
        at = prompt.find(text)
        while at >= 0:
            b = at + len(text)
            if not _overlaps(at, b, blocked) and not _overlaps(at, b, [(v["from"], v["to"]) for v in vary]) \
                    and _fits(prompt, at, b):
                # How it varies: "one" (flesh out one specific thing) only when the reply says so;
                # anything else is a kind to vary, as every phrase was before.
                how = item.get("how") if isinstance(item, dict) else None
                vary.append({"from": at, "to": b, "text": text,
                             "label": _label(item, text) if isinstance(item, dict) else text,
                             "mode": "one" if isinstance(how, str) and how.strip().lower() == "one" else "kind"})
                break
            at = prompt.find(text, at + 1)
        if len(vary) == MAX_VARY:
            break
    vary.sort(key=lambda v: v["from"])

    looks: List[Dict[str, str]] = []
    if got.get("shot_stated") is not True:
        for item in got.get("looks") if isinstance(got.get("looks"), list) else []:
            look = _fixed(item, (3, 24))
            if look and look["text"] not in prompt and all(look["text"] != x["text"] for x in looks):
                looks.append(look)
            if len(looks) == MAX_LOOKS:
                break
    adds: List[Dict[str, str]] = []
    for item in got.get("adds") if isinstance(got.get("adds"), list) else []:
        add = _fixed(item, (2, 12))
        if add and add["text"] not in prompt and all(add["text"] != x["text"] for x in adds + looks):
            adds.append(add)
        if len(adds) == MAX_ADDS:
            break
    return {"vary": vary, "looks": looks, "adds": adds}


def suggest_key(prompt: str, model: str) -> str:
    blob = json.dumps([SUGGEST_VERSION, model, prompt], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _turn(prompt: str) -> str:
    """What the model reads: the prompt with exact text hidden, and the parts that already vary."""
    shown = hidden(prompt)
    turn = f"The prompt:\n{shown}"
    marked = [shown[a:b] for a, b in find_slots(shown)]
    if marked:
        turn += ("\n\nAlready changing from picture to picture: " + ", ".join(marked)
                 + ". Nothing you suggest may pin down what they leave open.")
    return turn


EMPTY: Dict[str, List[Dict[str, Any]]] = {"vary": [], "looks": [], "adds": []}


async def suggest(prompt: str, ask: Optional[Ask] = None, cache: Optional[NarrowCache] = None,
                  project_id: Optional[int] = None, model: str = "", raw: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """{"vary": [{from, to, text, label, mode}], "looks": [{text, label}], "adds": [{text, label}]}
    for the prompt as sent. No call for an empty prompt (or only comment lines) or Raw mode.
    The checked reply is cached by the exact prompt; a reply that can't be read twice gives
    nothing and isn't cached."""
    if raw or not _body(prompt):
        return {k: [] for k in EMPTY}
    ask = ask or ask_model
    key = suggest_key(prompt, model)
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict) and all(isinstance(hit.get(k), list) for k in EMPTY):
            return {k: hit[k] for k in EMPTY}
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SUGGEST_SYSTEM},
                                      {"role": "user", "content": _turn(prompt)}]
    for attempt in range(2):
        reply = await ask(messages, project_id, SUGGEST_TOKENS)
        got = _json_object(reply)
        if got is not None:
            checked = check_suggestions(prompt, got)
            if cache is not None:
                cache.put_raw(key, checked)
            return checked
        log.info(f"[suggest] unreadable reply (try {attempt + 1}): {str(reply)[:160]!r}")
        messages = messages + [{"role": "assistant", "content": str(reply or "")},
                               {"role": "user", "content": "That reply wasn't a JSON object, so none of it could be used. "
                                                           "Reply with only the JSON, in the shape shown."}]
    return {k: [] for k in EMPTY}

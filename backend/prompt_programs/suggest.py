"""Suggest and Add: the editor's helpers for making slots.

Suggest reads a prompt and names phrases already written that could vary (the editor
underlines them; a click wraps one in brackets) and a few things the prompt doesn't mention
that would be worth varying ("+ light"). Add writes one of those into the prompt as a slot,
the way the person would have written it (", lit by <light>").

The model decides what could vary and how the words join. Code checks only structure: that
a phrase is an exact stretch of the prompt where a slot can stand, the counts, and that Add
kept everything that was there. Both replies are plain JSON; a reply that can't be read gets
one retry saying what was wrong.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger
from prompt_programs.narrow import Ask, NarrowCache
from prompt_programs.slots import _VERBATIM, SLOT_RE, _line_marks, _lines, find_slots, is_comment

log = get_logger(__name__)

SUGGEST_VERSION = "suggest-1"
MAX_VARY = 6
MAX_ADDS = 3

Span = Tuple[int, int]

SUGGEST_SYSTEM = """You help someone write an image prompt that makes a different picture each time it runs. They mark the parts that should change from picture to picture with angle brackets: "dorm room with a <young man>, lit by <light>". Any words can be marked: <elderly African man>, <teenage boy>, <pet>, <rainy street>.

Read their prompt and suggest two things.

vary: phrases already written in the prompt that would be worth changing from picture to picture. Prefer what a person would most want to differ between pictures: who is in it, what they wear, the place, an animal, a thing they hold or use. Copy each phrase exactly as it is written, as the smallest stretch that names the thing together with the words that describe it: "young man", not "a young man in"; "red leather jacket", not "a red leather jacket and". Never the whole prompt and never a verb alone. Leave out anything already in angle brackets, square brackets or curly braces. At most 6, the best first. Fewer is fine, and so is none.

adds: things the prompt doesn't mention at all that would be worth varying in this picture. Only what is truly missing: if the prompt already says anything about it, leave it out. What fits depends on the prompt: for a portrait perhaps the background or the light, for a street scene the weather or the time of day, for a product shot the surface it stands on. Name each in one or two plain words, in the prompt's own way of speaking. At most 3, the best first.

Lines starting with # are notes from the user, not part of the picture's text. Never take a phrase from them. They may say what the user does or doesn't want to vary: follow them.

Reply with JSON only, in this shape:
{"vary": ["young man", "dorm room"], "adds": [{"name": "light", "label": "light"}]}
For each add, name is the words that would go in the angle brackets and label is the one or two words shown on its button."""

ADD_SYSTEM = """You add one changing part to an image prompt. The user marks the parts that change from picture to picture with angle brackets: "dorm room with a <young man>, lit by <light>". They ask you to add a new one, and you write it into their prompt the way they would have written it themselves.

- Change as little as possible. Keep every character of the prompt exactly as it is, and only insert the new words.
- Write the joining words the way the prompt is written. Words in a sentence or phrase ("a kitchen at noon") get joining words that make the new part read as part of it: "a kitchen at noon, lit by <light>", "a kitchen at noon, shot as <camera>". Only a prompt that is a list of short tags ("1girl, long hair, kitchen") gets the bare tag: ", <light>".
- Put it where it reads naturally, usually after what it belongs to.
- Add exactly one part in angle brackets, with exactly the words you were given. Leave every existing part in angle brackets, square brackets or curly braces as it is.
- Lines starting with # are notes from the user: leave them as they are and put nothing on them.

Reply with JSON only, in this shape:
{"prompt": "the whole prompt with the new part added"}"""


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


def check_suggestions(prompt: str, got: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """The reply's usable suggestions. A phrase is kept at its first stretch of the prompt
    where a slot could stand, outside comment lines, verbatim, lists, names and slots, and
    not over a phrase kept before it; the whole prompt is not a phrase."""
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

    taken = {prompt[a + 1:b - 1].casefold() for a, b in slots} | {k["text"].casefold() for k in kept}
    adds: List[Dict[str, Any]] = []
    for item in got.get("adds") if isinstance(got.get("adds"), list) else []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"].strip()
        label = item.get("label").strip() if isinstance(item.get("label"), str) and item["label"].strip() else name
        if not SLOT_RE.fullmatch(f"<{name}>") or name.casefold() in taken:
            continue
        taken.add(name.casefold())
        adds.append({"name": name, "label": label})
        if len(adds) == MAX_ADDS:
            break
    return {"vary": kept, "adds": adds}


def suggest_key(prompt: str, model: str) -> str:
    blob = json.dumps([SUGGEST_VERSION, model, prompt], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


async def suggest(prompt: str, ask: Optional[Ask] = None, cache: Optional[NarrowCache] = None,
                  project_id: Optional[int] = None, model: str = "", raw: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """{"vary": [{from, to, text}], "adds": [{name, label}]} for the prompt as sent. No call
    for an empty prompt (or only comment lines) or Raw mode. Cached by the exact prompt; a
    reply that can't be read twice gives nothing and isn't cached."""
    empty: Dict[str, List[Dict[str, Any]]] = {"vary": [], "adds": []}
    if raw or not _body(prompt):
        return empty
    ask = ask or ask_model
    key = suggest_key(prompt, model)
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict) and isinstance(hit.get("vary"), list) and isinstance(hit.get("adds"), list):
            return hit
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SUGGEST_SYSTEM},
                                      {"role": "user", "content": f"The prompt:\n{prompt}"}]
    for attempt in range(2):
        reply = await ask(messages, project_id, 800)
        got = _json_object(reply)
        if got is not None:
            out = check_suggestions(prompt, got)
            if cache is not None:
                cache.put_raw(key, out)
            return out
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


def _restore_ends(before: str, reply: str) -> str:
    """The reply with the prompt's own leading and trailing whitespace: models trim them."""
    lead = before[:len(before) - len(before.lstrip())]
    trail = before[len(before.rstrip()):]
    return lead + reply.strip() + trail if before.strip() else reply.strip()


async def add(prompt: str, name: str, ask: Optional[Ask] = None, project_id: Optional[int] = None) -> Dict[str, Any]:
    """{"prompt": the prompt with <name> written in, "slot": {from, to}} (the span includes the
    brackets). The model writes it in; after a second reply that fails the checks, `, <name>`
    goes at the end of the last non-comment line."""
    name = name.strip()
    if not _body(prompt):
        return plain_add(prompt, name)
    ask = ask or ask_model
    messages: List[Dict[str, Any]] = [{"role": "system", "content": ADD_SYSTEM},
                                      {"role": "user", "content": f"The prompt:\n{prompt}\n\nAdd: <{name}>"}]
    for attempt in range(2):
        reply = await ask(messages, project_id, max(800, len(prompt) // 2 + 400))
        got = _json_object(reply)
        if got is None or not isinstance(got.get("prompt"), str):
            problem = 'it wasn\'t a JSON object with the whole prompt as "prompt"'
        else:
            after = _restore_ends(prompt, got["prompt"])
            span, problem = check_added(prompt, after, name)
            if span is not None:
                return {"prompt": after, "slot": {"from": span[0], "to": span[1]}}
        log.info(f"[add] reply not used (try {attempt + 1}): {problem}; {str(reply)[:160]!r}")
        messages = messages + [{"role": "assistant", "content": str(reply or "")},
                               {"role": "user", "content": f"That reply couldn't be used: {problem}. Reply again with only "
                                                           "the JSON, holding the whole prompt with the one new part added."}]
    return plain_add(prompt, name)

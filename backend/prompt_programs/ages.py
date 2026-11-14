"""How old the people in a prompt read: the one question the minors rules are decided by
(stimma-plans MINORS_POLICY.md).

    reading("girl", "a girl on a swing in the park")      ->  "child"
    reading("girl", "a girl lying on the bed")            ->  "adult"
    reading(ANYONE, "a man carrying a baby on a hike")     ->  "child"

How old a reader would naturally picture a person, read in the whole prompt, every line and
note: "child" (under 13), "teenager" (13 to 17) or "adult". Words that fit a child and an adult
alike, with nothing in the prompt pointing to a child, are an adult. It is asked of each person
part, and once of "anyone in the prompt": the youngest person a reader would picture anywhere
in it, named in a part or not, or "none". One short call each, reasoning off, run beside the
narrowing; the reply is read by its value (one age word), never by its key. An unreadable reply
or a failed call is asked once more with a different first line. A reply still unreadable is an
adult; a call that still fails is None, also an adult. Answers are cached on disk per wording, so
a person is pinned once per prompt and never flips between draws; a failed call is never cached. No words are matched here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger

log = get_logger(__name__)

AGES_VERSION = "ages-1"   # ages-1: the natural reading (child, teenager or adult, erring adult; "none" for anyone in the prompt), asked once, replaces the yes asked twice
ANYONE = "anyone in the prompt"   # the whole-prompt form of both questions
STAGES = ("child", "teenager", "adult")
YOUNG = ("child", "teenager")   # readings that make a prompt young
NONE = "none"                            # the reading of anyone in a prompt that shows no one
RETRY_LEAD = "Answer this once more: an earlier reply could not be read.\n\n"
READING_TOKENS = 40

READING_SYSTEM = """You read an image prompt and say how old a reader would naturally picture a person in it.

Answer with one of:
- "child": under 13.
- "teenager": 13 to 17.
- "adult": 18 or over.

Read the whole prompt, every line and note, the way an ordinary reader would. Age comes from what
the words imply as well as what they state. A child's life (a swing, a sandcastle, toys, a school
class, a parent looking after them) reads as a child; a teenager's (high school, prom) as a
teenager; an adult's (a job, a bar, college, a date, a wedding) as an adult. "Teenager" is only
for words that point to high-school age (a teen, a high schooler, prom, homecoming): a college
student, a fraternity, a night out or a job is an adult. "A girl" or "a boy" is whatever the
prompt around them makes them; with nothing around them that points to a child, they are an
adult. When the words fit a child and an adult alike and nothing in the prompt points to a child,
answer "adult". A word for a group (a family, kids, a team, a class) is answered for the youngest
a reader would picture in it: a family on an outing has children in it, unless the scene is one
for adults only. A "1girl" or "1boy" tag is an adult unless other tags make them younger.

When the person is "anyone in the prompt", answer for the youngest person a reader would picture
anywhere in it, named or not: not the main person, the youngest one (a baby someone holds, the
children someone looks after). Answer "none" when the prompt shows no person at all.

Examples:
- "a little boy feeding ducks with his grandmother", said of "a little boy": child
- "a girl selling lemonade at a stand on her street", said of "a girl": child
- "a family opening presents on Christmas morning", said of "a family": child
- "a boy waiting for his date outside a restaurant", said of "a boy": adult
- "1girl, long hair, coffee shop", said of "1girl": adult
- "a woman in a red coat", said of "a woman": adult
- "a girl with a braid, watercolor", said of "a girl": adult
- "a woman pushing a stroller", said of "anyone in the prompt": child
- "a lighthouse on a rocky coast", said of "anyone in the prompt": none

Reply with only a JSON object: {"age": "child"}, {"age": "teenager"} or {"age": "adult"}; for
anyone in the prompt, {"age": "none"} when it shows no one."""

READING_QUESTION = "How old would a reader naturally picture this person?"


def _user(person: str, prompt: str, question: str) -> str:
    return f'The person: "{person.strip()}".\n\nThe prompt:\n{prompt.strip()}\n\n{question}'


def reading_messages(person: str, prompt: str) -> List[Dict[str, str]]:
    return [{"role": "system", "content": READING_SYSTEM},
            {"role": "user", "content": _user(person, prompt, READING_QUESTION)}]


def _objects(reply: str):
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    for m in re.finditer(r"\{[^{}]*\}", text, re.S):
        try:
            got = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(got, dict):
            yield got


def _value(reply: str, allowed: Tuple[str, ...]) -> Optional[str]:
    """The one allowed value in the first JSON object that holds exactly one, read by its value
    (a torn key still reads); a bare one-word reply too. None for anything else."""
    for got in _objects(reply):
        vals = [str(v).strip().lower() for v in got.values() if isinstance(v, str)]
        hit = [v for v in vals if v in allowed]
        if len(hit) == 1:
            return hit[0]
    bare = re.sub(r"[^a-z]", "", re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S).lower())
    return bare if bare in allowed else None


def parse_reading(reply: str, anyone: bool = False) -> Optional[str]:
    """child, teenager or adult (and "none" for anyone in the prompt); None when unreadable."""
    return _value(reply, STAGES + ((NONE,) if anyone else ()))


def _key(kind: str, person: str, prompt: str) -> str:
    norm = lambda s: re.sub(r"\s+", " ", str(s).strip().lower())   # noqa: E731
    blob = json.dumps([AGES_VERSION, kind, norm(person), norm(prompt)], ensure_ascii=False)
    return kind[0] + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:31]


_asking: Dict[Tuple[str, str], "asyncio.Future[Any]"] = {}


async def _ask(kind: str, person: str, prompt: str, cache: Any, ask: Any, project_id: Optional[int]) -> Any:
    key = _key(kind, person, prompt)
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, str):
            return hit
    if ask is None:
        return None
    flight = (str(getattr(cache, "root", "")), key)
    if flight not in _asking:
        _asking[flight] = asyncio.ensure_future(_answer(kind, person, prompt, cache, ask, project_id, key))
        _asking[flight].add_done_callback(lambda t: _asking.pop(flight, None) if _asking.get(flight) is t else None)
    return await asyncio.shield(_asking[flight])


async def _answer(kind: str, person: str, prompt: str, cache: Any, ask: Any, project_id: Optional[int],
                  key: str) -> Any:
    first = reading_messages(person, prompt)
    tokens = READING_TOKENS
    unreadable = False
    for attempt in range(2):
        # The retry starts differently: a model that degenerated on this exact request (a run of
        # "!!!!" from one local build's numerics) answers a request that differs at its start.
        messages = first if not attempt else [first[0], {"role": "user", "content": RETRY_LEAD + first[1]["content"]}]
        try:
            reply = await ask(messages, project_id, tokens)
        except Exception as e:
            log.warning(f"[ages] {kind} of {person!r} failed (try {attempt + 1}): {e}")
            continue
        got = parse_reading(reply, person == ANYONE)
        if got is not None:
            if cache is not None:
                try:
                    cache.put_raw(key, got)
                except OSError as e:   # only means it is asked again next time
                    log.warning(f"[ages] keeping a {kind} failed: {e}")
            return got
        log.info(f"[ages] {kind} of {person!r}: no answer in the reply (try {attempt + 1}): {str(reply)[:120]!r}")
        unreadable = True
    if unreadable:
        # The model answered, twice, with no age in it: an adult, pinned like any answer so the
        # person never flips between draws. A failed call is not kept: it is asked again.
        if cache is not None:
            try:
                cache.put_raw(key, "adult")
            except OSError:
                pass
        return "adult"
    return None


async def reading(person: str, prompt: str, cache: Any, ask: Any, project_id: Optional[int] = None) -> Optional[str]:
    """How old a reader would naturally picture `person` in `prompt`: child, teenager or adult
    (none: anyone in a prompt that shows no one). None with no answer, read as an adult. `ask=None` reads the
    cache only. Never raises."""
    try:
        return await _ask("reading", person, prompt, cache, ask, project_id)
    except Exception as e:   # never stops a prompt: no answer, read on the safe side
        log.warning(f"[ages] reading of {person!r} failed: {e}")
        return None


__all__ = ["AGES_VERSION", "ANYONE", "NONE", "READING_SYSTEM", "STAGES", "YOUNG", "parse_reading", "reading",
           "reading_messages"]

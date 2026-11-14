"""A list narrowed to what a slot's words allow: the seeds of its variants (seeding.py).

    subset(age list, "young woman", about="the woman's age")  ->  the ages 18 to 29

"A young woman" doesn't fix her age, it narrows it. Each distinct (list, words) question is
asked once, by asking which of the list's values fit the words, and cached on disk across
prompts: "young woman" on the age list is asked once per vocabulary version, ever. The reply
copies the items that fit back (numbers alone made models unreliable with reasoning off), or
["ALL"]; a long list is asked in chunks of WORDS_CHUNK side by side, each cached on its own.
A list with declared groups (descent) is shown by group and answered by group.

Ages. A person is an adult unless asked: the age list's bands under 18 are opt-in (vocab.py),
kept only when the words call for them, and an age is read in its line and the prompt's notes,
where "a girl" alone is a young adult (MINORS_POLICY.md). Which words make someone a child is
the model's reading, never matched here: beside every age narrowing the model is asked, yes or
no, whether the prompt's own words make this person a child or a teenager (`under_18`), and the
ages under 18 a narrowing keeps count only after a yes (seeding.narrow_seeds). Anything but a
clear yes, a failed call or an unreadable reply included, means an adult. A failed or unreadable
answer is never cached: the question is worth asking again, and meanwhile the slot's seeds go
without that list.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.vocab import AGE_LIST, Leaf

log = get_logger(__name__)

NARROW_VERSION = "narrow-15"   # narrow-15: words naming a kind of being (an elf) leave gender open. narrow-14: a list may be read in its scene (what a person wears, the light). narrow-13: the gender list, whose description says words for a woman fit a trans woman too. narrow-12: "elderly" is 70 and over. narrow-11: an age is read in its own line and the notes; "young" is 18 to 29. narrow-10: a grouped list is answered as {"groups", "items"}; an empty answer stands. narrow-9: a list with declared groups (descent) is shown by group. narrow-8: ["ALL"] when every item fits; room to copy long items. narrow-7: the rule is stated without the cases it was tested on. narrow-6: a girl or a boy is a child or an adult, never a span of both. narrow-5: an age is read with the whole prompt, and "a girl" or "a boy" alone is what the prompt makes them. narrow-4: words narrow by what they imply ("a grandmother", "an old man"); narrow-3: "a girl" alone is 18 to 29, said as ages (narrow-2: under 18 only when asked)
NARROW_SECONDS = 180.0   # all of a prompt's narrowing calls together; past it what hasn't answered seeds nothing
UNDER_18_VERSION = "under18-1"   # a yes asked twice; the yes/no question: whether the prompt's own words make a person a child or a teenager
WORDS_CHUNK = 80         # a list longer than this is asked in chunks of about this many, side by side

Ask = Callable[[List[Dict[str, Any]], Optional[int], int], Awaitable[str]]


ALL = "ALL"   # the reply for a list whose every item fits: a long list isn't copied back whole

_SYSTEM = """You choose which items of a list fit a description from an image prompt.

Reply with only a JSON list of the items that fit, each copied exactly as written. If no item
fits, reply []. If every item fits, reply ["ALL"] instead of copying them.

Read the description whole, with what it is said of, the way a casting director would: which
items would a reader of those words accept, and which would they call wrong? Keep the first and
leave out the second. Words narrow by what they imply as well as by what they state: a life
stage, a role or a kinship brings its usual range with it ("a grandmother" is not 25, "a
college student" is not 60, "a veteran" is not 20, "retired" is not 30), and "old", "young" or
"little" narrow even where the noun alone would not ("an old man" is old, not any adult).
Only when the description truly says nothing about an item either way, keep it, unless the
list says that item is kept only when called for.

Ages: a person is an adult (18 or over) unless the description itself makes them a child or
a teenager: "a child", "a baby", "a toddler", "kids", "a teenage boy", "a 10-year-old", "a
little girl", "a schoolboy". Such words call for the ages under 18 that match them, and only
those. A man or a woman is an adult, of whatever ages the rest of the description allows.
A "teenage boy" is 13 to 19. "Young", said of an adult ("a young woman", "a young man"), is
their twenties at most: 18 to 29. "Elderly" is 70 and over.

"A girl" or "a boy" alone says neither: people say it of a child and of a young woman or man
alike. For an age you are also given the prompt it is said in, and the prompt decides:
- When the prompt is sexual, nude, romantic or otherwise adult in what it shows or asks for,
  or shows an adult's life (a job, a bar, a date, driving, a wedding), they are an adult: keep
  the ages from 18 to 29 and never one under 18.
- When the prompt shows a child's life (a parent beside them, school, play, what only a child
  has or does), they are a child: keep the ages under 18 that
  match what it shows.
- When the prompt shows neither, or you are given no prompt, they are a young adult: keep the
  ages from 18 to 29.
Decide which of the three it is first. The ages you keep for "a girl" or "a boy" are then all
under 18 or all 18 and over, never some of each."""

RETRY_LEAD = "Answer this once more: an earlier reply could not be read.\n\n"


def _shown(text: str) -> str:
    """A template as the narrowing model reads it: its color slots say "(color)"."""
    return re.sub(r"\{(?:main|accent|neutral)\}", "(color)", text)


def _spaced(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _span(words: str, prompt: str) -> bool:
    """`words` is a stretch of the prompt as written (case and runs of spaces aside): a
    reading copies, it doesn't invent or reword."""
    want = _spaced(words)
    return bool(want) and want in _spaced(prompt)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


GROUPED_REPLY = """The list's items are shown in named groups (peoples, regions, kinds). The description need not
be an item's name: say which items fit it. Reply with only a JSON object {"groups": [...],
"items": [...]}: "groups" are the groups whose every item fits, each name copied exactly, and
"items" are the items that fit from groups that fit only in part, each copied exactly. A word
for a continent or a whole region takes in the items from anywhere in it, all of them:
"European" is every group from Europe, north, south, east and west. A word for one people or
one place is that item alone, not the rest of its group: "Irish" is the item Irish, and no
group. If no item fits, reply {"groups": [], "items": []}."""


def grouped(leaf: Leaf, values: Sequence[str]) -> Optional[Dict[str, List[str]]]:
    """The values by their declared group, when the list declares groups and every value is in
    one (the descent list: its heritage groups); else None."""
    if not getattr(leaf, "groups", None):
        return None
    shown = set(values)
    out: Dict[str, List[str]] = {}
    for v in leaf.values:
        sh = _shown(v.text)
        if sh not in shown:
            continue
        if not v.group or v.group not in leaf.groups:
            return None
        out.setdefault(v.group, []).append(sh)
    return out or None


def messages_for(leaf: Leaf, phrase: str, values: Sequence[str], about: str = "", prompt: str = "") -> List[Dict[str, str]]:
    said = f', said of {about.strip()}' if about.strip() else ""
    groups = grouped(leaf, values)
    if groups:
        listing = "\n".join(f"- {g}: {', '.join(items)}" for g, items in groups.items())
        user = (f'The list "{leaf.label}" ({leaf.description}):\n{json.dumps(list(values), ensure_ascii=False)}\n\n'
                f'Its items by group:\n{listing}\n\nWhich of these fit "{phrase}"{said}?')
        system = _SYSTEM.replace(_SYSTEM.split("\n\n")[1], GROUPED_REPLY, 1)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]
    user = (f'The list "{leaf.label}" ({leaf.description}):\n{json.dumps(list(values), ensure_ascii=False)}\n\n'
            f'Which of these fit "{phrase}"{said}?')
    if prompt.strip() and leaf.id == AGE_LIST:   # an age is read in the whole prompt (see _SYSTEM)
        user += f"\n\nThe prompt it is said in:\n{prompt.strip()}"
    elif prompt.strip():   # a list read in its scene
        user += (f"\n\nThe prompt it is said in:\n{prompt.strip()}\n\nKeep only the items that suit it there: who "
                 "this is, what they are doing, the place, the time and the kind of picture. Leave out an item a "
                 "reader of this prompt would find out of place, even when the words alone don't rule it out.")
    shown = set(values)
    asked = [_shown(v.text) for v in leaf.values if v.opt_in and _shown(v.text) in shown]
    if asked:  # opt-in values (vocab.py): never kept by default
        user += ("\n\nThese items are kept only when called for: keep one when the description itself means it (a "
                 "description of a child means the child's ages), never merely because the description doesn't rule "
                 f"it out: {json.dumps(asked, ensure_ascii=False)}")
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def parse_grouped(reply: str, groups: Dict[str, List[str]]) -> Optional[List[str]]:
    """The values a grouped reply names: every item of each group it names, and each item it
    names; None when it holds neither that object nor a plain JSON list. A group named beside
    some of its own items was named for those items (its items go in "items" only when it fits
    in part): it keeps just them. Unknown names are ignored."""
    every = [v for items in groups.values() for v in items]
    names = {_norm(g): items for g, items in groups.items()}
    m = re.search(r"\{.*\}", reply or "", re.S)
    try:
        got = json.loads(m.group(0)) if m else None
    except ValueError:
        got = None
    if isinstance(got, dict) and all(isinstance(got.get(k, []), list) for k in ("groups", "items")):
        items = {_norm(x) for x in got.get("items") or [] if isinstance(x, str)}
        whole = [names[_norm(g)] for g in got.get("groups") or [] if isinstance(g, str) and _norm(g) in names]
        whole = [g for g in whole if not any(_norm(v) in items for v in g)]
    else:
        said = parse_subset(reply, every + list(groups))
        if said is None:
            return None
        items = {_norm(x) for x in said if _norm(x) not in names}
        whole = [names[_norm(x)] for x in said if _norm(x) in names]
    keep = {v for g in whole for v in g}
    return [v for v in every if v in keep or _norm(v) in items]


def parse_subset(reply: str, values: Sequence[str]) -> Optional[List[str]]:
    """The list's values the reply names, in the list's order; None when the reply holds
    no JSON list. Names that aren't in the list are ignored."""
    for m in re.finditer(r"\[[^\[\]]*\]", reply or "", re.S):
        try:
            got = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(got, list) and all(isinstance(x, str) for x in got):
            if [x.strip() for x in got] == [ALL]:   # every item fits (the opt-in ones aside: subset())
                return list(values)
            named = {_norm(x) for x in got}
            hit = [v for v in values if _norm(v) in named]
            if not hit and len(got) == 1 and "," in got[0]:
                # every item in one string ("a, b, c"): read its comma-separated pieces as the items
                named = {_norm(x) for x in got[0].split(",")}
                hit = [v for v in values if _norm(v) in named]
            return hit
    return None


UNDER_18_SYSTEM = """You read an image prompt and say whether its own words make a person in it a child or a
teenager: someone under 18.

A person is an adult unless the words themselves say they are under 18. Answer "yes" only when a
reader of the prompt would say its words plainly describe a child or a teenager: "a child", "a
baby", "a toddler", "kids", "a little girl", "a schoolboy", "a schoolgirl", "a teenager", "a
teenage boy", "a 10-year-old". Answer "no" when the words describe an adult, and when they say
nothing about age or fit adults as well: a job, a role, a pastime or a word for anyone (a doctor,
a fisherman, a student, a singer, a cyclist) is an adult, wherever the picture is set.

"A girl" or "a boy" alone is a young adult: "no". They are a child only when other words in the
prompt make them one ("a little girl", "a schoolgirl", "a boy holding his mother's hand", "a girl
at her fifth birthday party"). Being young, small or in a family does not by itself make someone
a child, and nor does doing what people of every age do (skating, a sport, dancing, studying,
playing music, a day at the beach): "a girl on a bicycle" is a young woman.

Reply with only a JSON object: {"under_18": "yes"} or {"under_18": "no"}."""


def under_18_messages(phrase: str, about: str = "", prompt: str = "") -> List[Dict[str, str]]:
    said = f", said of {about.strip()}" if about.strip() else ""
    user = f'The words: "{phrase.strip()}"{said}.'
    if prompt.strip():
        user += f"\n\nThe prompt they are in:\n{prompt.strip()}"
    user += "\n\nDo the prompt's own words make this person a child or a teenager?"
    return [{"role": "system", "content": UNDER_18_SYSTEM}, {"role": "user", "content": user}]


def parse_under_18(reply: str) -> Optional[bool]:
    """The model's yes or no: True for a yes, False for a no, None for anything else (which the
    caller reads as an adult, and doesn't cache)."""
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    for m in re.finditer(r"\{[^{}]*\}", text, re.S):
        try:
            got = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(got, dict) and isinstance(got.get("under_18"), (str, bool)):
            v = got["under_18"]
            v = ("yes" if v else "no") if isinstance(v, bool) else v.strip().lower()
            if v in ("yes", "no"):
                return v == "yes"
    bare = re.sub(r"[^a-z]", "", text.lower())   # a bare answer: "yes", "No."
    return {"yes": True, "no": False}.get(bare)


class NarrowCache:
    """(list, words) → subset, one small JSON file each, keyed by the list's values too."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def key(leaf: Leaf, phrase: str, values: Sequence[str], about: str = "", prompt: str = "") -> str:
        blob = json.dumps([NARROW_VERSION, leaf.id, list(values), _norm(phrase), _norm(about), *([_norm(prompt)] if prompt else [])],
                          ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Optional[List[str]]:
        try:
            got = json.loads(self._path(key).read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return [str(x) for x in got] if isinstance(got, list) else None

    def put(self, key: str, subset: Sequence[str]) -> None:
        self.put_raw(key, list(subset))

    def get_raw(self, key: str) -> Any:
        try:
            return json.loads(self._path(key).read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def put_raw(self, key: str, value: Any) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, p)


def reply_tokens(shown: Sequence[str]) -> int:
    """Room to copy back every item: about four characters a token, and a few for the quoting."""
    return 200 + sum(len(v) for v in shown) // 3 + 6 * len(shown)


def _all(reply: str) -> bool:
    return bool(re.search(r'\[\s*"ALL"\s*\]', reply or ""))


def chunks(values: Sequence[str], size: int = WORDS_CHUNK) -> List[List[str]]:
    """A list in even chunks of at most about `size`, in order."""
    values = list(values)
    if len(values) <= size:
        return [values]
    n = -(-len(values) // size)
    step = -(-len(values) // n)
    return [values[i:i + step] for i in range(0, len(values), step)]


async def subset(leaf: Leaf, phrase: str, cache: Optional[NarrowCache], ask: Optional[Ask],
                 project_id: Optional[int] = None, about: str = "", prompt: str = "",
                 scene: bool = False) -> Optional[List[str]]:
    """The values of `leaf` that fit `phrase` (said of `about`: "young" said of "the woman's age"
    rules out children), from the cache or model calls. None while any chunk has no answer (a
    failed call, an unreadable answer: never cached, worth asking again). `ask=None` reads the
    cache only. The same question asked twice at once is asked once. A long list (not the age
    list, read whole by the minors rules, nor one read by its groups) is asked in chunks side by
    side, each cached on its own."""
    values = [v.text for v in leaf.eligible()]
    # An age is read with the whole prompt (the minors rules), and so is a list narrowed by its
    # scene (`scene`: what a person wears, the light): which items suit who this is and where.
    prompt = prompt if leaf.id == AGE_LIST or scene else ""
    if len(values) <= WORDS_CHUNK or leaf.id == AGE_LIST or grouped(leaf, [_shown(v) for v in values]):
        parts = [values]
    else:
        parts = chunks(values)

    async def one(part: List[str]) -> Optional[List[str]]:
        key = NarrowCache.key(leaf, phrase, part, about, prompt)
        if cache is not None:
            hit = cache.get(key)
            if hit is not None:
                return hit
        if ask is None:
            return None
        flight = (str(getattr(cache, "root", "")), key)
        if flight not in _asking:
            _asking[flight] = asyncio.ensure_future(_ask_subset(leaf, phrase, cache, ask, project_id, about, prompt,
                                                                key, part))
            _asking[flight].add_done_callback(lambda t: _asking.pop(flight, None) if _asking.get(flight) is t else None)
        return await asyncio.shield(_asking[flight])
    got = await asyncio.gather(*(one(p) for p in parts))
    if any(g is None for g in got):
        return None
    keep = {v for g in got for v in g or ()}
    return [v for v in values if v in keep]


_asking: Dict[Tuple[str, str], "asyncio.Future[Optional[List[str]]]"] = {}


async def under_18(phrase: str, cache: Optional[NarrowCache], ask: Optional[Ask], project_id: Optional[int] = None,
                   about: str = "", prompt: str = "") -> Optional[bool]:
    """Whether the prompt's own words make the person these words are said of a child or a
    teenager: the model's explicit answer, from the cache or calls. A yes counts only when a second
    asking says yes too, so one stray yes never makes an adult a minor; a no is a no. None when
    there is no clear answer (a failed call or an unreadable reply, each asked once more): the
    caller treats them as an adult, and it isn't cached. `ask=None` reads the cache only. Never
    raises."""
    blob = json.dumps([UNDER_18_VERSION, _norm(phrase), _norm(about), _norm(prompt)], ensure_ascii=False)
    key = "u" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:31]
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, bool):
            return hit
    if ask is None:
        return None
    first = under_18_messages(phrase, about, prompt)

    async def answer() -> Optional[bool]:
        messages = first
        for attempt in range(2):
            if attempt:   # the retry starts differently, as a narrowing's does (_ask_subset)
                messages = [first[0], {"role": "user", "content": RETRY_LEAD + first[1]["content"]}]
            try:
                reply = await ask(messages, project_id, 40)
            except Exception as e:
                log.warning(f"[prompt-program] under-18 reading of {phrase!r} failed (try {attempt + 1}): {e}")
                continue
            got = parse_under_18(reply)
            if got is not None:
                return got
            log.info(f"[prompt-program] under-18 reading of {phrase!r}: no yes or no in the reply (try {attempt + 1}): "
                     f"{str(reply)[:120]!r}")
        return None
    got = await answer()
    if got is True:
        got = await answer()   # a yes, asked again: both must say so
    if got is not None and cache is not None:
        cache.put_raw(key, got)
    return got
    messages = under_18_messages(phrase, about, prompt)
    for attempt in range(2):
        if attempt:   # the retry starts differently, as a narrowing's does (_ask_subset)
            messages = [messages[0], {"role": "user", "content": RETRY_LEAD + messages[1]["content"]}]
        try:
            reply = await ask(messages, project_id, 40)
        except Exception as e:
            log.warning(f"[prompt-program] under-18 reading of {phrase!r} failed (try {attempt + 1}): {e}")
            continue
        got = parse_under_18(reply)
        if got is not None:
            if cache is not None:
                cache.put_raw(key, got)
            return got
        log.info(f"[prompt-program] under-18 reading of {phrase!r}: no yes or no in the reply (try {attempt + 1}): {str(reply)[:120]!r}")
    return None


async def _ask_subset(leaf: Leaf, phrase: str, cache: Optional[NarrowCache], ask: Ask, project_id: Optional[int],
                      about: str, prompt: str, key: str, values: Sequence[str]) -> Optional[List[str]]:
    shown = [_shown(v) for v in values]
    got = None
    messages = messages_for(leaf, phrase, shown, about, prompt)
    for attempt in range(2):   # one more try for a failed call or an unreadable answer
        if attempt:
            # The retry starts differently: a model that degenerated on this exact request (a run
            # of "!!!!" from one local build's numerics) answers a request that differs at its start.
            messages = [messages[0], {"role": "user", "content": RETRY_LEAD + messages[1]["content"]}]
        try:
            reply = await ask(messages, project_id, reply_tokens(shown))
        except Exception as e:
            log.warning(f"[prompt-program] narrowing {leaf.id} by {phrase!r} failed (try {attempt + 1}): {e}")
            continue
        groups = grouped(leaf, shown)
        named = parse_grouped(reply, groups) if groups else parse_subset(reply, shown)
        if named is not None and len(named) == len(shown) and _all(reply):
            opt_in = {_shown(v.text) for v in leaf.values if v.opt_in}   # kept only when named
            named = [sh for sh in named if sh not in opt_in]
        got = None if named is None else [v for v, sh in zip(values, shown) if sh in set(named)]
        if got is not None:
            break
        log.info(f"[prompt-program] narrowing {leaf.id} by {phrase!r}: no list in the reply (try {attempt + 1})")
    if got is None:
        return None
    if cache is not None:
        cache.put(key, got)
    return got


__all__ = ["ALL", "NarrowCache", "UNDER_18_VERSION", "WORDS_CHUNK", "chunks", "grouped", "messages_for", "parse_grouped",
           "parse_subset", "parse_under_18", "subset", "under_18", "under_18_messages"]

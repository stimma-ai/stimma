"""where=: a bound pick's list narrowed to what the user's words allow.

    age = pick("age", cls="person.age_band", where="young", about="her age", seed=["20–24-year-old"], ...)

"A young woman" doesn't fix her age, it narrows it: the age list should draw only the
young adult ranges. After a program is prepared, two steps find and apply such words:

1. Read: one call per prompt asks which of the user's own words describe each bound
   detail ("young woman" for age, "blonde" for hair colour, nothing for her outfit). Words
   not in the prompt are dropped. A bound smart wildcard uses its own name
   (`{{asian or euro ethnicity}}`); the writer's `where=` is used when the reading finds
   nothing. Writers forget `where=` about half the time, so the reading is what counts.
2. Narrow: each distinct (list, words) pair is resolved once, by asking which of the
   list's values fit the words, cached on disk across prompts: "young woman" on the age
   list is asked once per vocabulary version, ever.

The prepared entry records the subset per pick (`entry["filters"]`). A closed list then
draws only from it; an open list starts from it, and its generated options are told the
words as a rule. When nothing fits, or the model's answer can't be read, the pick keeps
no list at all (an empty subset): it draws as an unbound pick, generated options within
the words, rather than from a list that ignores them.

A narrowing that didn't finish (the reading or a subset call failed, timed out or came back
unreadable, or there was no time to try) is not final: `entry["narrow_pending"]` holds each
such pick's list and options as they were, and prepare.renarrow tries again later.
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
from prompt_programs.vocab import Leaf, vocabulary

log = get_logger(__name__)

NARROW_VERSION = "narrow-1"
NARROW_SECONDS = 20.0   # all of a program's narrowing calls together; past it, unresolved picks go unbound

Ask = Callable[[List[Dict[str, Any]], Optional[int], int], Awaitable[str]]

_SYSTEM = """You choose which items of a list fit a description from an image prompt.

Reply with only a JSON list of the items that fit, each copied exactly as written. Read the
description literally and whole, with what it is said of: a man or a woman is an adult (18 or
over), a boy or a girl is under 18, a "teenage boy" is 13 to 19.
Keep every item the description allows and leave out every item it rules out. When the
description doesn't speak to an item either way, keep it. If no item fits, reply []."""

_READ_SYSTEM = """You read an image prompt and find the words in it that describe certain details.

For each detail, quote the prompt's own words about that detail, exactly as written, with the
person or thing they describe ("young woman", "his dark hair", "a smiling girl"), or null when
the prompt says nothing about it. Don't guess and don't infer: only words the prompt contains.
Reply with only a JSON object mapping each detail's id to those words or null."""


def phrase_of(choice: Dict[str, Any], read: Optional[Dict[str, str]] = None) -> str:
    """The words a bound choice is narrowed by: its wildcard's own name, else the words read
    from the prompt for it, else the writer's where= (when it's words, not a facet filter)."""
    where = choice.get("where")
    return str(choice.get("wildcard") or (read or {}).get(choice.get("id"), "")
               or (where if isinstance(where, str) else "") or "").strip()


def _shown(text: str) -> str:
    """A template as the narrowing model reads it: its colour slots say "(colour)"."""
    return re.sub(r"\{(?:main|accent|neutral)\}", "(colour)", text)


def _in_prompt(words: str, prompt: str) -> bool:
    """Every word of `words` is in the prompt: the reading quotes, it doesn't invent."""
    have = set(re.findall(r"[a-z0-9]+", prompt.lower()))
    want = re.findall(r"[a-z0-9]+", words.lower())
    return bool(want) and all(w in have for w in want)


def read_messages(prompt: str, details: Sequence[Tuple[str, str]]) -> List[Dict[str, str]]:
    lines = "\n".join(f"- {cid}: {what}" for cid, what in details)
    return [{"role": "system", "content": _READ_SYSTEM},
            {"role": "user", "content": f"The prompt:\n{prompt}\n\nThe details:\n{lines}"}]


def parse_read(reply: str, ids: Sequence[str], prompt: str) -> Optional[Dict[str, str]]:
    """{id: words} from the reply's JSON object, keeping only words the prompt contains;
    None when the reply holds no JSON object."""
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(got, dict):
        return None
    return {cid: str(got[cid]).strip() for cid in ids
            if isinstance(got.get(cid), str) and got[cid].strip() and _in_prompt(got[cid], prompt)}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def messages_for(leaf: Leaf, phrase: str, values: Sequence[str], about: str = "") -> List[Dict[str, str]]:
    said = f', said of {about.strip()}' if about.strip() else ""
    user = (f'The list "{leaf.label}" ({leaf.description}):\n{json.dumps(list(values), ensure_ascii=False)}\n\n'
            f'Which of these fit "{phrase}"{said}?')
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def parse_subset(reply: str, values: Sequence[str]) -> Optional[List[str]]:
    """The list's values the reply names, in the list's order; None when the reply holds
    no JSON list. Names that aren't in the list are ignored."""
    for m in re.finditer(r"\[[^\[\]]*\]", reply or "", re.S):
        try:
            got = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(got, list) and all(isinstance(x, str) for x in got):
            named = {_norm(x) for x in got}
            return [v for v in values if _norm(v) in named]
    return None


class NarrowCache:
    """(list, words) → subset, one small JSON file each, keyed by the list's values too."""

    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def key(leaf: Leaf, phrase: str, values: Sequence[str], about: str = "") -> str:
        blob = json.dumps([NARROW_VERSION, leaf.id, list(values), _norm(phrase), _norm(about)], ensure_ascii=False)
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


async def subset(leaf: Leaf, phrase: str, cache: Optional[NarrowCache], ask: Ask,
                 project_id: Optional[int] = None, about: str = "") -> Optional[List[str]]:
    """The values of `leaf` that fit `phrase` (said of `about`, the pick's own description:
    "young" said of "the woman's age" rules out children), from the cache or one model call.
    None when the call fails or its answer can't be read: never cached, worth asking again."""
    values = [v.text for v in leaf.eligible()]
    shown = [_shown(v) for v in values]
    key = NarrowCache.key(leaf, phrase, values, about)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    try:
        reply = await ask(messages_for(leaf, phrase, shown, about), project_id, 2000)
    except Exception as e:  # the writer's endpoint failing here must not fail the prepare
        log.warning(f"[prompt-program] narrowing {leaf.id} by {phrase!r} failed: {e}")
        return None
    named = parse_subset(reply, shown)
    got = None if named is None else [v for v, sh in zip(values, shown) if sh in set(named)]
    if got is None:
        log.info(f"[prompt-program] narrowing {leaf.id} by {phrase!r}: no list in the reply")
        return None
    if cache is not None:
        cache.put(key, got)
    return got


async def read_words(prompt: str, choices: Sequence[Dict[str, Any]], cache: Optional[NarrowCache], ask: Ask,
                     project_id: Optional[int] = None) -> Optional[Dict[str, str]]:
    """The user's own words about each bound choice's detail, from one call per prompt
    (cached by the prompt and the details asked about). None when the call fails or its
    answer can't be read (never cached)."""
    vocab = vocabulary()
    details = [(c["id"], f'{vocab.leaves[c["cls"]].label} ({c.get("about") or vocab.leaves[c["cls"]].description})')
               for c in choices]
    if not details or not prompt.strip():
        return {}
    key = hashlib.sha256(json.dumps(["read", NARROW_VERSION, prompt, details], ensure_ascii=False).encode()).hexdigest()[:32]
    if cache is not None:
        hit = cache.get_raw(key)
        if isinstance(hit, dict):
            return {str(k): str(v) for k, v in hit.items()}
    try:
        reply = await ask(read_messages(prompt, details), project_id, 600)
    except Exception as e:
        log.warning(f"[prompt-program] reading the prompt's words for its lists failed: {e}")
        return None
    got = parse_read(reply, [cid for cid, _ in details], prompt)
    if got is None:
        return None
    if cache is not None:
        cache.put_raw(key, got)
    return got


async def narrow_entry(entry: Dict[str, Any], cache: Optional[NarrowCache], ask: Ask,
                       project_id: Optional[int] = None, seconds: float = NARROW_SECONDS) -> List[str]:
    """Narrow every bound choice to what the user's words allow, in place: `entry["filters"]`
    maps the choice id to its subset, the choice shows only those options, and a choice whose
    subset is empty loses its list. Picks whose narrowing didn't finish are recorded in
    `entry["narrow_pending"]` (see the module docstring). Returns notes for the log."""
    vocab = vocabulary()
    bound = [c for c in entry.get("choices") or [] if vocab.get(c.get("cls")) is not None]
    entry.pop("narrow_pending", None)
    if not bound:
        return []
    before = {c["id"]: {"cls": c["cls"], "options": list(c.get("options") or [])} for c in bound}
    unfinished: set = set()
    by_id = {c["id"]: c for c in entry.get("choices") or []}
    filters: Dict[str, List[str]] = dict(entry.get("filters") or {})
    notes: List[str] = []
    # where={...}: a filter on the list's local facets, applied in code (no model call). Facets
    # of a template's palette ("colour_family") narrow its Colours pick. The pick's own words
    # are still read below and narrow within it ("a Victorian lady" with where={"status": ...}).
    facet: Dict[str, List[str]] = {}
    for c in bound:
        w = c.get("where")
        if not isinstance(w, dict) or not w:
            continue
        leaf = vocab.leaves[c["cls"]]
        palette = vocab.get(leaf.slots) if leaf.slots else None
        own = {f: v for f, v in w.items() if f in leaf.local_facets}
        theirs = {f: v for f, v in w.items() if palette is not None and f in palette.local_facets}
        targets = [(c, leaf, own)]
        comp = by_id.get(f'{c["id"]}.colours')
        if theirs and comp is not None:
            comp["where"] = theirs
            targets.append((comp, palette, theirs))
        for ch, lf, want in targets:
            if not want:
                continue
            got = [v.text for v in lf.matching(want)]
            if got:
                facet[ch["id"]] = got
            else:
                notes.append(f'{ch["id"]}: nothing in {lf.id} has {want}; drawing from the whole list')
    t0 = asyncio.get_running_loop().time()
    readable = [c for c in bound if not c.get("wildcard")]
    try:
        read = await asyncio.wait_for(read_words(str(entry.get("prompt") or ""), readable, cache, ask, project_id),
                                      seconds)
    except asyncio.TimeoutError:
        read = None
    if read is None:  # not read: the words found later may narrow these picks
        unfinished |= {c["id"] for c in readable}
        read = {}
    seconds = max(1.0, seconds - (asyncio.get_running_loop().time() - t0))
    wanted: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}   # (list, words, about) → choices
    for c in bound:
        phrase = phrase_of(c, read)
        if phrase:
            if isinstance(c.get("where"), dict):
                c["where_words"] = phrase   # the facet filter stays; the words narrow within it
            else:
                c["where"] = phrase
            wanted.setdefault((c["cls"], _norm(phrase), _norm(c.get("about") or "")), []).append(c)
    words: Dict[str, List[str]] = {}
    keys = list(wanted)
    if keys:
        jobs = [subset(vocab.leaves[k[0]], phrase_of(wanted[k][0], read), cache, ask, project_id,
                       wanted[k][0].get("about") or "") for k in keys]
        try:
            results = await asyncio.wait_for(asyncio.gather(*jobs), seconds)
        except asyncio.TimeoutError:
            log.warning(f"[prompt-program] narrowing took longer than {seconds:.0f}s: those picks draw unbound for now")
            results = [None for _ in keys]
        for k, got in zip(keys, results):
            for c in wanted[k]:
                words[c["id"]] = list(got or [])
                if got is None:
                    unfinished.add(c["id"])
    for c in bound:
        cid = c["id"]
        if cid not in facet and cid not in words:
            continue
        if cid in facet:  # the facet filter holds; words narrow within it when they leave anything
            within = [x for x in words.get(cid, []) if x in set(facet[cid])]
            got = within or facet[cid]
        else:
            got = words[cid]
        filters[cid] = list(got)
        if got:
            c["options"] = list(got)
        else:  # nothing in the list fits the words: generated options within them instead
            notes.append(f'{cid}: nothing in {c["cls"]} fits {phrase_of(c)!r}; drawing it without the list')
            c.pop("cls", None)
            c["options"] = []
    # A colour asked for a templated look holds only for templates whose main garment takes the
    # palette: fixed-colour looks ("a white dinner jacket") and looks without {main} drop out.
    for c in entry.get("choices") or []:
        cid = c["id"]
        if not cid.endswith(".colours") or not filters.get(cid):
            continue
        parent = by_id.get(cid[: -len(".colours")])
        leaf = vocab.get(parent.get("cls")) if parent is not None else None
        if leaf is None or not leaf.slots:
            continue
        base = filters.get(parent["id"]) or [v.text for v in leaf.eligible()]
        coloured = [t for t in base if "{main}" in t]
        if coloured:
            filters[parent["id"]] = coloured
            parent["options"] = coloured
    entry["filters"] = filters
    if unfinished:
        entry["narrow_pending"] = {cid: before[cid] for cid in before if cid in unfinished}
    return notes


def mark_pending(entry: Dict[str, Any]) -> bool:
    """Record every bound pick as not yet narrowed (narrowing was skipped). False if there
    is nothing to narrow."""
    vocab = vocabulary()
    pending = {c["id"]: {"cls": c["cls"], "options": list(c.get("options") or [])}
               for c in entry.get("choices") or [] if vocab.get(c.get("cls")) is not None}
    if pending:
        entry["narrow_pending"] = {**pending, **(entry.get("narrow_pending") or {})}
    return bool(pending)


def reopen_pending(entry: Dict[str, Any]) -> None:
    """Put the pending picks back as they were before their unfinished narrowing (their list,
    options and no filter), so narrow_entry narrows them afresh."""
    pending = entry.get("narrow_pending") or {}
    filters = dict(entry.get("filters") or {})
    for c in entry.get("choices") or []:
        was = pending.get(c.get("id"))
        if was:
            c["cls"], c["options"] = was["cls"], list(was.get("options") or [])
            filters.pop(c["id"], None)
    entry["filters"] = filters


__all__ = ["NarrowCache", "mark_pending", "narrow_entry", "parse_read", "parse_subset", "phrase_of", "read_words",
           "reopen_pending", "subset", "messages_for"]

"""where=: a bound pick's list narrowed to what the user's words allow.

    age = pick("young_man.age", cls="person.age_band", about="his age", ...)

"A young man" doesn't fix his age, it narrows it: the age list should draw only the young
adult ranges. The slot reader (reader.py) says which of a slot's words state each detail
(`entry["slot_words"]`: choice id -> words copied from the slot or a comment line); then each
distinct (list, words) pair is resolved once, by asking which of the list's values fit the
words, cached on disk across prompts: "young man" on the age list is asked once per
vocabulary version, ever. A pick's where= words, when it has them, narrow it when the slot's
words say nothing of it.

The prepared entry records the subset per pick (`entry["filters"]`). A closed list then
draws only from it; an open list starts from it, and its generated options are told the
words as a rule. When nothing fits, or the model's answer can't be read, the pick keeps
no list at all (an empty subset): it draws as an unbound pick, generated options within
the words, rather than from a list that ignores them.

A narrowing that didn't finish (the reading or a subset call failed, timed out or came back
unreadable, or there was no time to try) is not final: `entry["narrow_pending"]` holds each
such pick's list and options as they were, and program.renarrow tries again later.

Ages. A person is an adult unless asked: the age list's bands under 18 are opt-in (vocab.py),
so an age pick these steps leave unnarrowed (no words, a failed or skipped call) draws adults
only, and the narrowing model is told that "a girl" alone is no child. A person with no age
pick of their own whose details are bound (an age the prompt states as fixed text: "a
10-year-old at the beach") still gets their age read and narrowed, as `entry["ages"]`
({person: subset}, person as draws.person_of names them), so their pools know when they are
under 18. Which words make someone a child is the models' reading, never matched here.
The same goes for an age from the user's own list ("{13-year-old|30-year-old}"): each value of
a user list of a person with bound details and no age pick is narrowed on the age list, and the values that
read under 18 are recorded as `entry["list_ages"]` ({list pick: {value: ages}}), so a draw of
one leaves that person's adult-only values out (draws.py); the list itself is never filtered.
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
from prompt_programs.runtime import COLORS
from prompt_programs.draws import owns, person_of
from prompt_programs.vocab import AGE_LIST, Leaf, minor_ages, vocabulary

log = get_logger(__name__)

NARROW_VERSION = "narrow-7"   # narrow-7: the rule is stated without the cases it was tested on. narrow-6: a girl or a boy is a child or an adult, never a span of both. narrow-5: an age is read with the whole prompt, and "a girl" or "a boy" alone is what the prompt makes them. narrow-4: words narrow by what they imply ("a grandmother", "an old man"); narrow-3: "a girl" alone is 18 to 29, said as ages (narrow-2: under 18 only when asked)
NARROW_SECONDS = 60.0   # all of a program's narrowing calls together; past it, unresolved picks go unbound. A local chat model answers one in 10-20s, longer while it writes options

Ask = Callable[[List[Dict[str, Any]], Optional[int], int], Awaitable[str]]
_MEMBER = re.compile(r"^(.+)\[\d+\]\.(.+)$")   # kids[2].age → ("kids", "age")

_SYSTEM = """You choose which items of a list fit a description from an image prompt.

Reply with only a JSON list of the items that fit, each copied exactly as written. If no item
fits, reply [].

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
A "teenage boy" is 13 to 19.

"A girl" or "a boy" alone says neither: people say it of a child and of a young woman or man
alike. For an age you are also given the whole prompt, and the prompt decides:
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

def phrase_of(choice: Dict[str, Any], read: Optional[Dict[str, str]] = None) -> str:
    """The words a bound choice is narrowed by: the slot's words for it, else the pick's own
    where= (when it's words, not a facet filter)."""
    where = choice.get("where")
    words = where.strip() if isinstance(where, str) else ""
    got = str((read or {}).get(choice.get("id"), "") or "").strip()
    # An age written for the scene beside what the slot says of that person's age: both narrow the list.
    if got and words and choice.get("cls") == AGE_LIST:
        if got.lower() in words.lower():
            return words
        if words.lower() not in got.lower():
            return f"{got}, {words}"
    return str(got or words or "").strip()


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


def messages_for(leaf: Leaf, phrase: str, values: Sequence[str], about: str = "", prompt: str = "") -> List[Dict[str, str]]:
    said = f', said of {about.strip()}' if about.strip() else ""
    user = (f'The list "{leaf.label}" ({leaf.description}):\n{json.dumps(list(values), ensure_ascii=False)}\n\n'
            f'Which of these fit "{phrase}"{said}?')
    if prompt.strip():   # an age is read in the whole prompt (see _SYSTEM)
        user += f"\n\nThe whole prompt:\n{prompt.strip()}"
    shown = set(values)
    asked = [_shown(v.text) for v in leaf.values if v.opt_in and _shown(v.text) in shown]
    if asked:  # opt-in values (vocab.py): never kept by default
        user += ("\n\nThese items are kept only when called for: keep one when the description itself means it (a "
                 "description of a child means the child's ages), never merely because the description doesn't rule "
                 f"it out: {json.dumps(asked, ensure_ascii=False)}")
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


async def subset(leaf: Leaf, phrase: str, cache: Optional[NarrowCache], ask: Ask,
                 project_id: Optional[int] = None, about: str = "", prompt: str = "") -> Optional[List[str]]:
    """The values of `leaf` that fit `phrase` (said of `about`, the pick's own description:
    "young" said of "the woman's age" rules out children), from the cache or one model call.
    None when the call fails or its answer can't be read: never cached, worth asking again."""
    values = [v.text for v in leaf.eligible()]
    shown = [_shown(v) for v in values]
    prompt = prompt if leaf.id == AGE_LIST else ""   # only an age is read with the whole prompt
    key = NarrowCache.key(leaf, phrase, values, about, prompt)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    try:
        reply = await ask(messages_for(leaf, phrase, shown, about, prompt), project_id, 200 + 16 * len(shown))
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


async def narrow_entry(entry: Dict[str, Any], cache: Optional[NarrowCache], ask: Ask,
                       project_id: Optional[int] = None, seconds: float = NARROW_SECONDS) -> List[str]:
    """Narrow every bound choice to what the user's words allow, in place: `entry["filters"]`
    maps the choice id to its subset, the choice shows only those options, and a choice whose
    subset is empty loses its list. Picks whose narrowing didn't finish are recorded in
    `entry["narrow_pending"]` (see the module docstring). The words come from
    `entry["slot_words"]` (choice id -> the slot's words for it). Returns notes for the log."""
    vocab = vocabulary()
    # A pick with said= is the user's own words, not a kind to narrow to: its list holds alternatives.
    bound = [c for c in entry.get("choices") or [] if vocab.get(c.get("cls")) is not None and not c.get("said")]
    # An age the user stated (said=) is still read, so their person's pools know an adult from a minor.
    said_ages = [c for c in entry.get("choices") or [] if c.get("said") and c.get("kind", "pick") == "pick"
                 and getattr(vocab.resolve(c.get("cls")) if c.get("cls") else None, "id", None) == AGE_LIST]
    entry.pop("narrow_pending", None)
    if not bound and not said_ages:
        return []
    before = {c["id"]: {"cls": c["cls"], "options": list(c.get("options") or [])} for c in bound}
    unfinished: set = set()
    by_id = {c["id"]: c for c in entry.get("choices") or []}
    filters: Dict[str, List[str]] = dict(entry.get("filters") or {})
    notes: List[str] = []
    # where={...}: a filter on the list's local facets, applied in code (no model call). Facets
    # of a template's palette ("color_family") narrow its Colors pick. The pick's own words
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
        comp = by_id.get(c["id"] + COLORS)
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
    # The whole prompt, for reading an age. Not when part of it is the user's [exact text]: no
    # model reads that text, so the prompt as a model sees it could show a child's life while the
    # hidden part makes it an adult prompt. Then the age is read from its own words, as before:
    # "a girl" alone is a young adult.
    whole = "" if entry.get("exact") else str(entry.get("prompt") or "")
    stated = stated_ages(entry, bound, said_ages)
    stated_ctx = stated_context(entry, bound)
    listed = list_age_values(entry, bound)
    listed_ctx = list_context_values(entry, bound)
    context_only = {id(c) for c in [*stated_ctx, *listed_ctx]}
    # The narrowings whose words don't come from the slots (a user list's value) start first.
    early: Dict[Tuple[str, str, str], Tuple[str, str, "asyncio.Task[Optional[List[str]]]"]] = {}
    for c in listed + listed_ctx:
        phrase = phrase_of(c)
        k = (c["cls"], _norm(phrase), _norm(c.get("about") or ""))
        if phrase and k not in early:
            early[k] = (phrase, c.get("about") or "", asyncio.ensure_future(
                subset(vocab.leaves[c["cls"]], phrase, cache, ask, project_id, c.get("about") or "", whole)))
    # The slot reader already said which of a slot's words state each detail (slots.build).
    read = {str(k): str(v) for k, v in (entry.get("slot_words") or {}).items() if str(v).strip()}
    seconds = max(1.0, seconds - (asyncio.get_running_loop().time() - t0))
    # The members of one group() ("kids playing football": four of them) are the same words'
    # people. A reading that names the first member's age and stops leaves the others adults:
    # a detail read for one member is read for every member the reading left out. People the
    # prompt describes one by one aren't a group(), and keep each their own words.
    declared = {str(g.get("id")) for g in entry.get("groups") or [] if g.get("id") and not g.get("from_ids")}
    shared: Dict[Tuple[str, str], str] = {}
    members = [(c, m) for c in bound if (m := _MEMBER.match(str(c["id"]))) and m.group(1) in declared]
    for c, m in members:
        if read.get(c["id"]):
            shared.setdefault((m.group(1), m.group(2)), read[c["id"]])
    for c, m in members:
        if not read.get(c["id"]) and (m.group(1), m.group(2)) in shared:
            read[c["id"]] = shared[(m.group(1), m.group(2))]
    wanted: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}   # (list, words, about) → choices
    for c in bound:
        phrase = phrase_of(c, read)
        if phrase:
            if isinstance(c.get("where"), dict):
                c["where_words"] = phrase   # the facet filter stays; the words narrow within it
            else:
                c["where"] = phrase
            wanted.setdefault((c["cls"], _norm(phrase), _norm(c.get("about") or "")), []).append(c)
    # a stated age or context, or a user list's value: narrowed on its list, recorded apart
    for c in [*stated, *listed, *stated_ctx, *listed_ctx]:
        phrase = phrase_of(c, read)
        if phrase:
            wanted.setdefault((c["cls"], _norm(phrase), _norm(c.get("about") or "")), []).append(c)
    words: Dict[str, List[str]] = {}

    def job(k: Tuple[str, str, str]) -> "asyncio.Future[Optional[List[str]]]":
        phrase, about = phrase_of(wanted[k][0], read), wanted[k][0].get("about") or ""
        started = early.pop(k, None)
        if started is not None and (started[0], started[1]) == (phrase, about):
            return started[2]
        if started is not None:  # asked in other words than it is now: ask as it is
            started[2].cancel()
        return asyncio.ensure_future(subset(vocab.leaves[k[0]], phrase, cache, ask, project_id, about, whole))

    async def batch(keys: List[Tuple[str, str, str]]) -> List[Optional[List[str]]]:
        # Each answer that came back in time holds; only the ones still out are pending.
        jobs = [job(k) for k in keys]
        if not jobs:
            return []
        _done, late = await asyncio.wait(jobs, timeout=seconds)
        if late:
            log.warning(f"[prompt-program] narrowing took longer than {seconds:.0f}s: {len(late)} of {len(jobs)} "
                        "picks draw unbound for now")
            for j in late:
                j.cancel()
        return [None if j in late or j.cancelled() or j.exception() is not None else j.result() for j in jobs]

    # The picks' own narrowing and the context readings, side by side, each within the time left.
    batches = [[k for k in wanted if not all(id(c) in context_only for c in wanted[k])],
               [k for k in wanted if all(id(c) in context_only for c in wanted[k])]]
    try:
        done = await asyncio.gather(*(batch(keys) for keys in batches))
    finally:
        for *_, task in early.values():  # started, then not wanted (its words weren't asked after all)
            task.cancel()
    for keys, results in zip(batches, done):
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
        if not got and getattr(vocab.get(c.get("cls")), "strict", False):
            # A list that is never drawn without (ages: generated ones include children; a face or a
            # photo's look: generated ones are praise and blur). Words nothing in it fits weren't about
            # this detail ("a girl" for her age, "selfie" for its framing): the whole list stands.
            filters.pop(cid, None)
            notes.append(f'{cid}: nothing in {c["cls"]} fits {phrase_of(c)!r}; drawing from the whole list')
            continue
        filters[cid] = list(got)
        if got:
            c["options"] = list(got)
        else:  # nothing in the list fits the words: generated options within them instead
            notes.append(f'{cid}: nothing in {c["cls"]} fits {phrase_of(c)!r}; drawing it without the list')
            c.pop("cls", None)
            c["options"] = []
    # A color asked for a templated look holds only for templates whose main garment takes the
    # palette: fixed-color looks ("a white dinner jacket") and looks without {main} drop out.
    for c in entry.get("choices") or []:
        cid = c["id"]
        if not cid.endswith(COLORS) or not filters.get(cid):
            continue
        parent = by_id.get(cid[: -len(COLORS)])
        leaf = vocab.get(parent.get("cls")) if parent is not None else None
        if leaf is None or not leaf.slots:
            continue
        base = filters.get(parent["id"]) or [v.text for v in leaf.eligible()]
        colored = [t for t in base if "{main}" in t]
        if colored:
            filters[parent["id"]] = colored
            parent["options"] = colored
    entry["filters"] = filters
    ages = {c["age_of"]: words[c["id"]] for c in stated if c["id"] in words and words[c["id"]]}
    if ages:
        entry["ages"] = ages
    else:
        entry.pop("ages", None)
    young: Dict[str, Dict[str, List[str]]] = {}
    for c in listed:
        under = minor_ages(words.get(c["id"]) or [])
        if under:
            young.setdefault(c["list_of"], {})[c["where"]] = list(under)
    if young:
        entry["list_ages"] = young
    else:
        entry.pop("list_ages", None)
    said = [{"of": c["context_of"], "cls": c["cls"], "values": list(words[c["id"]])} for c in stated_ctx
            if _informative(vocab.leaves[c["cls"]], words.get(c["id"]) or [])]
    if said:
        entry["stated_context"] = said
    else:
        entry.pop("stated_context", None)
    read_as: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    for c in listed_ctx:
        if _informative(vocab.leaves[c["cls"]], words.get(c["id"]) or []):
            read_as.setdefault(c["list_of"], {}).setdefault(c["value"], {})[c["cls"]] = list(words[c["id"]])
    if read_as:
        entry["list_context"] = read_as
    else:
        entry.pop("list_context", None)
    if unfinished:
        entry["narrow_pending"] = {cid: before[cid] for cid in before if cid in unfinished}
        for c in stated:  # the next try reads it again (reopen_pending passes it by: it isn't a choice)
            if c["id"] in unfinished:
                entry["narrow_pending"][c["id"]] = {"cls": AGE_LIST, "options": [], "age_of": c["age_of"]}
        for c in listed:
            if c["id"] in unfinished:
                entry["narrow_pending"][c["id"]] = {"cls": AGE_LIST, "options": [], "list_of": c["list_of"]}
        for c in [*stated_ctx, *listed_ctx]:   # read again on the next try, like stated ages
            if c["id"] in unfinished:
                entry["narrow_pending"][c["id"]] = {"cls": c["cls"], "options": [], "context": True}
    return notes


def stated_ages(entry: Dict[str, Any], bound: Sequence[Dict[str, Any]],
                said: Sequence[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """For each person with bound details but no age pick (an age pick holding the user's own
    words, `said`, counts as none: their words are read), a detail to read their age by:
    {"id", "cls": the age list, "about", "age_of": the person}. Their stated age ("a
    10-year-old", "a little girl") is then read and narrowed like an age pick's words, so
    their pools know when they are under 18 (options.program_minors)."""
    vocab = vocabulary()
    if vocab.get(AGE_LIST) is None:
        return []
    aged = {person_of(c["id"]) for c in bound if c.get("cls") == AGE_LIST}
    ids = {str(c.get("id")) for c in entry.get("choices") or []}
    named = {person_of(c["id"]) for c in [*bound, *said] if str(c.get("cls") or "").startswith("person.")} - {""}
    out: Dict[str, Dict[str, Any]] = {}
    for c in [*bound, *said]:
        p = person_of(c["id"])
        # an age pick speaks for its person, and one naming no subject for everyone (draws.owns);
        # a shared detail beside named people is read through theirs, not as "the person"
        if any(owns(a, p) for a in aged) or p in out or (p == "" and named) \
                or not str(c.get("cls") or "").startswith("person."):
            continue
        sid = f"{p}.stated_age" if p else "stated_age"
        while sid in ids:
            sid += "_"
        # One wording per person, not per prompt, so a narrowing ("a woman" on ages) is cached for good.
        out[p] = {"id": sid, "cls": AGE_LIST, "about": f"the age of {p.replace('_', ' ') if p else 'the person'}",
                  "age_of": p}
    return list(out.values())


def _context_scopes(entry: Dict[str, Any], bound: Sequence[Dict[str, Any]]) -> List[Tuple[Leaf, Optional[str]]]:
    """(giving list, person or None for the scene) for each scope where a bound pick's list takes
    a context facet a stated-reading list gives (vocab.py: "stated") and no bound pick of that
    scope gives it: the scopes whose stated value, or user list values, are worth reading."""
    vocab = vocabulary()
    out: List[Tuple[Leaf, Optional[str]]] = []
    leaves = [(c, vocab.leaves[c["cls"]]) for c in bound]
    for g in sorted((lf for lf in vocab.leaves.values() if lf.stated and lf.gives), key=lambda lf: lf.id):
        person = vocab.scope(g.gives[0]) == "person"
        takers = {person_of(c["id"]) if person else None for c, lf in leaves if set(lf.takes) & set(g.gives)}
        given = {person_of(c["id"]) if person else None for c, lf in leaves if set(lf.gives) & set(g.gives)}
        if person:  # a detail naming no subject is every subject's (draws.owns): read each named one
            takers -= {""} if takers - {""} else set()
            takers = {who for who in takers if not any(owns(gv, who) for gv in given)}
        else:
            takers -= given
        out += [(g, who) for who in sorted(takers, key=lambda x: x or "")]
    return out


def stated_context(entry: Dict[str, Any], bound: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For each such scope, a detail to read what the prompt states for that list ("a Japanese
    woman" on descent, "at midnight" on the time of day): {"id", "cls", "about", "context_of"}.
    Its subset is recorded as `entry["stated_context"]`; it weights that scope's takers like a
    drawn value would (draws.py) when nothing drawn gives the facet."""
    ids = {str(c.get("id")) for c in entry.get("choices") or []}
    out = []
    for g, who in _context_scopes(entry, bound):
        name = g.id.rsplit(".", 1)[-1]
        sid = f"{who}.stated_{name}" if who else (f"stated_{name}" if who == "" else f"scene.stated_{name}")
        while sid in ids:
            sid += "_"
        ids.add(sid)
        of = (who.replace("_", " ") if who else "the person") if who is not None else "the scene"
        out.append({"id": sid, "cls": g.id, "about": f"the {g.label.lower()} of {of}", "context_of": who})
    return out


def list_context_values(entry: Dict[str, Any], bound: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each value of a user list in such a scope, as a detail narrowed on the giving list (as
    list_age_values does for ages): which values read as, say, a descent is the narrowing
    model's reading of each (cached by its words). Recorded as `entry["list_context"]`; a draw
    of the value then gives its scope context (draws.py). The list itself is never filtered."""
    out: List[Dict[str, Any]] = []
    scopes = _context_scopes(entry, bound)
    for c in entry.get("choices") or []:
        if c.get("source") != "list" or c.get("kind", "pick") != "pick" or c.get("cls"):
            continue
        read: set = set()
        for g, who in scopes:
            if (who is not None and not owns(person_of(str(c.get("id"))), who)) or g.id in read:
                continue
            read.add(g.id)   # a shared list in several people's scopes is read once
            of = (who.replace("_", " ") if who else "the person") if who is not None else "the scene"
            for v in dict.fromkeys(str(o) for o in c.get("options") or [] if str(o).strip()):
                out.append({"id": f'{c["id"]}\x00{g.id}\x00{v}', "cls": g.id, "where": v,
                            "about": f"the {g.label.lower()} of {of}", "list_of": str(c["id"]), "value": v})
    return out


def _informative(leaf: Leaf, got: Sequence[str]) -> bool:
    """A subset that says something: neither empty nor the whole list (words that don't speak to
    the list keep every value)."""
    return bool(got) and set(got) != {v.text for v in leaf.eligible()}


def list_age_values(entry: Dict[str, Any], bound: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each value of a user list of a person with bound details but no age pick (the people
    stated_ages reads), as a detail narrowed on the age list: {"id", "cls", "where": the value,
    "about", "list_of": the list pick}. Which values are an age under 18 is the narrowing
    model's reading of each (cached by its words)."""
    if vocabulary().get(AGE_LIST) is None:
        return []
    aged = {person_of(c["id"]) for c in bound if c.get("cls") == AGE_LIST}
    people = {q for q in (person_of(c["id"]) for c in bound if str(c.get("cls") or "").startswith("person."))
              if not any(owns(a, q) for a in aged)}
    out: List[Dict[str, Any]] = []
    for c in entry.get("choices") or []:
        p = person_of(str(c.get("id")))
        # a user list naming no subject (a twins' shared {8|30}) is read for whoever it speaks for
        if c.get("source") != "list" or c.get("kind", "pick") != "pick" or c.get("cls") \
                or not any(owns(p, q) for q in people):
            continue
        for v in dict.fromkeys(str(o) for o in c.get("options") or [] if str(o).strip()):
            out.append({"id": f'{c["id"]}\x00{v}', "cls": AGE_LIST, "where": v,
                        "about": f"the age of {p.replace('_', ' ') if p else 'the person'}", "list_of": str(c["id"])})
    return out


def mark_pending(entry: Dict[str, Any]) -> bool:
    """Record every bound pick as not yet narrowed (narrowing was skipped). False if there
    is nothing to narrow."""
    vocab = vocabulary()
    pending = {c["id"]: {"cls": c["cls"], "options": list(c.get("options") or [])}
               for c in entry.get("choices") or [] if vocab.get(c.get("cls")) is not None and not c.get("said")}
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


__all__ = ["NarrowCache", "mark_pending", "narrow_entry", "parse_subset", "phrase_of",
           "reopen_pending", "subset", "messages_for"]

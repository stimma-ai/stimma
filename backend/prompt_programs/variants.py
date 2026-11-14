"""The variant writer: a slot's values are variants of the user's words, written by the model.

    <dominant young woman> standing in her living room in <clothing slightly open in the front>

A slot is an area of the prompt where the user wants variety. Its value is one variant: a
specific, concrete take that keeps the slot's words, never a replacement for them. The pool is
written by one chat session per pool, reasoning off: the system prompt, a first user turn (the
whole prompt with the slot marked, the kept words, the rules, that turn's per-variant seed
lines), the model's reply, then "write N more" turns of TURN variants, each with its own seed
lines, so every turn sees what the pool holds. A first write is about 30 variants (40 for a
person); top-ups, picks and More like these are 20 more, each one more turn or two of the same
session. The reply is one JSON object per variant, read from the stream as each object closes
(ObjectReader) and checked at once, so the first variant shows in under a second. A turn joins
the log only with its survivors, and only when it kept at least half (a session copies its own
first mistake into every later turn). The pool is stored and drawn from with no model call per
image (variant_pools.py).

- Words. A variant keeps every word of the slot exactly, except its category word, which the
  reader names ("clothing" in "clothing slightly open in the front") and which the variant may
  replace with a kind of it ("a white cardigan slightly open in the front"). A person has no
  category word. Code checks the kept words verbatim, as runs of words, structurally.
- Seeds. The vocabulary seeds the writer instead of supplying the output: per variant, random
  ideas from the slot's lists on its seed line (the writer may reject one that can't be true or
  doesn't suit), one list value per variant as its core for a slot bound to one list, and for a
  person a descent per variant (drawn by the place mix, places.py: its look is given, its word
  written in where it reads naturally, left out where it can't be true), plus their gender and
  an age. Long lists are never shown to the model; a list of SHORTLIST values or fewer is shown
  whole.
- Checks. A variant that copies the prompt around the slot, another slot's markup or an article
  the prompt already has is repaired; then it must keep the words, add something and stay
  short, and carry a descent the user picked. A variant failing a check is dropped and counted,
  never an error. A variant records its descent seed only when its text carries the word.
- Minors (stimma-plans MINORS_POLICY.md). A person is an adult unless the prompt's own words make
  them a child or teenager. Age seeds come from the age list's pool, which holds no band under 18
  unless narrowing asked for one. A person who may be under 18 gets no adult-only seed and the
  writer is told their age.

This module makes calls and checks replies; it stores nothing. `ask` is injected: the app's chat
model (ask_writer, streamed through stream_writer where the provider can stream, else whole
replies) or a fake in tests. Every streamed turn has a first-token, a stall and an overall
deadline, enforced here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger

log = get_logger(__name__)

VARIANTS_VERSION = "variants-17"   # variants-17: the writer is told each kind's rules from its vocabulary data, in the kinds' order; a heritage may come with its look. variants-16: a couple, a family and a group are written as such (who a couple is drawn by its list, one shared heritage); a third of a person's variants wear what is typical for who and where they are; light is described as light; a camera part is how the picture is taken. variants-15: one streamed session per pool, a turn joins the log only when it kept half; a list too short for cores is shown whole; a fragment cut at markup is dropped; a variant's descent seed may stand inside the kept words. variants-14: a variant cut at the next slot's markup drops its copy of the words up to it ("grandmother with"). variants-13: a variant that is an article or determiner alone is dropped (stored pools hold "a"). variants-12: a free slot's idea lists are narrowed by its words (stored pools hold a tractor for "sports car"); a gender needs only the words that tell it from the others its words allow. variants-11: a descent is written in only where it can be true (a picked one still must be); look ideas come per variant on its seed line. variants-10: a/an set right when stored. variants-9: a person's look ideas fit their age. variants-8: light seeded by ideas, held to the place. variants-7: people vary their shape; age shows only where open. variants-6: worked person examples, fuller people. variants-5: a person is authored, two aspects per variant; gender must be stated; cores the pool has come last. variants-4: a variant drops its article after a determined phrase. variants-3: the writer is shown the words around the slot and continues the phrase. variants-2: an age seed only where the words leave age open; a copied single word is cut
N_PERSON = 40          # the first write for a person
N_OTHER = 30           # the first write for anything else
TOPUP = 20             # a top-up, and More like these
MIN_POOL = 12          # a first write that keeps fewer asks more turns (MORE_TURNS), then once more later
MORE_TURNS = 3         # at most this many turns past a first write's planned ones, while it is under MIN_POOL
TURN = 10              # variants a session's turn asks for: the first 5 in about 2 s, the next turn under 1 s later
COMPACT_AT = 100       # past this many variants in its log, a session sends a compact list of the middle
COMPACT_CHARS = 8000   # at most this much of that list (about 2k tokens)
MAX_ADDED_WORDS = 30   # words a variant may add to the kept words
MAX_ADDED_PEOPLE = 45  # the same for a part that names several people (Seeds.people): a few words each
SHORTLIST = 7          # a list this short is shown to the writer whole
HAVE_SHOWN = 80        # the pool's latest texts a fresh first turn over a pool is told it already has
WRITE_TOKENS = 4500    # the reply budget for 40 variants of about 20 words, with no reasoning
FIRST_TOKEN_SECONDS = 30.0   # a turn's first text, at most (measured: 0.2-0.6 s warm, 4.4 s for a cold 15k-token log)
STALL_SECONDS = 20.0         # between two texts of a streamed turn, at most
TURN_SECONDS = 120.0         # one turn, at most (a turn of 10 takes 3-7 s on a local model, a person ~10 s)
WRITE_TEMPERATURE = 0.8

AGE = "person.age_band"   # the age list (vocab.AGE_LIST): the minors rules read it, so it is the engine's
STAGE = "life_stage"   # the age list's facet the picker browses it by (baby, child, teen, young adult, ...)

# askable chat model: (messages, project_id, max_tokens, temperature) -> reply text. One that can
# stream also has `.stream(messages, project_id, max_tokens, temperature)`: an async iterator of
# text deltas that raises llm_http.StreamUnsupported (before any) where it can't.
Ask = Callable[..., Awaitable[str]]


async def ask_writer(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int,
                     temperature: float = WRITE_TEMPERATURE) -> str:
    """One plain completion from the chat model Fluent reads prompts with, reasoning off."""
    from llm import llm_complete_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("prompt-program"):
        return await llm_complete_text(config=cfg, messages=messages, max_tokens=max_tokens, temperature=temperature,
                                       enable_thinking=False, retry_reasoning=False)


async def stream_writer(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int,
                        temperature: float = WRITE_TEMPERATURE):
    """ask_writer streamed: the reply's text deltas, reasoning off, the log marked cacheable (its
    prefix is the same from turn to turn). Raises llm_http.StreamUnsupported before any delta where
    the configured provider can't stream here."""
    from llm import llm_stream_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("prompt-program"):
        async for delta in llm_stream_text(cfg, messages, max_tokens=max_tokens, temperature=temperature,
                                           enable_thinking=False, cacheable=True):
            yield delta


ask_writer.stream = stream_writer   # type: ignore[attr-defined]


# --------------------------------------------------------------------------- words, structurally

_TOKEN = re.compile(r"[\w']+")


def tokens(text: str) -> List[str]:
    """A text's words, lowercased; a hyphen or any punctuation separates them."""
    return _TOKEN.findall(str(text).replace("’", "'").lower())


def _run_at(hay: Sequence[str], run: Sequence[str]) -> int:
    """Where `run` first stands in `hay` as consecutive words, or -1."""
    n = len(run)
    if not n:
        return 0
    for i in range(len(hay) - n + 1):
        if list(hay[i:i + n]) == list(run):
            return i
    return -1


def has_run(text: str, words: str) -> bool:
    """`words` stand in `text` as consecutive whole words (case, punctuation and hyphens aside)."""
    return _run_at(tokens(text), tokens(words)) >= 0


def valid_category(words: str, category: Any, kind: str = "") -> str:
    """The reader's category word for a slot as the writer takes it: a run of the slot's own
    words, "" for a kind that keeps all its words (a person: its kind file's reader.category) or
    for anything that isn't one. Structure only."""
    from prompt_programs.vocab import vocabulary
    k = vocabulary().kind(kind) if kind else None
    if (k is not None and k.no_category) or not isinstance(category, str) or not tokens(category):
        return ""
    return category.strip() if _run_at(tokens(words), tokens(category)) >= 0 else ""


def kept_chunks(words: str, category: str = "") -> List[str]:
    """The runs of the slot's words a variant must keep: all of them with no category word,
    else what stands before and after it (none when the whole slot is its category)."""
    wt = tokens(words)
    ct = tokens(category)
    at = _run_at(wt, ct) if ct else -1
    if at < 0:
        return [" ".join(wt)] if wt else []
    return [" ".join(x) for x in (wt[:at], wt[at + len(ct):]) if x]


# --------------------------------------------------------------------------- seeds

@dataclass(frozen=True)
class Bank:
    """A list seeds are drawn from: its values with their draw weights."""
    list_id: str
    label: str
    values: Tuple[Tuple[str, float], ...]

    def texts(self) -> List[str]:
        return [t for t, _ in self.values]

    def only(self, keep: Sequence[str]) -> Optional["Bank"]:
        want = set(keep)
        vals = tuple((t, w) for t, w in self.values if t in want)
        return replace(self, values=vals) if vals else None


def bank(list_id: str, narrowed: Optional[Sequence[str]] = None, *, minor: bool = False,
         stated: Optional[Dict[str, Sequence[str]]] = None) -> Optional[Bank]:
    """A vocabulary list as a seed bank: its pool (vocab.Leaf.pool_values: opt-in values only when
    narrowing asked for them, adult-only values left out for a person who may be under 18),
    narrowed to `narrowed` when given, weighted by what the prompt states of the scene (`stated`:
    {context facet: families}, narrow.stated_context). A value held for want of a setting (a light
    that places the scene outdoors: `context.takes.<facet>.unstated: "opt_in"`) is no seed unless
    the prompt states that setting or the slot's words asked for it (narrowing kept it out of a
    smaller subset). None for an unknown list or one nothing is left of."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(list_id)
    if leaf is None or (narrowed is not None and not list(narrowed)):
        return None
    drawn, _ = leaf.pool_values(allowed=list(narrowed) if narrowed is not None else None, minor=minor)
    asked = set(narrowed or ())
    pairs = [(v.text, v.weight) for v in drawn if v.weight > 0 and (not v.marked or v.text in asked)]
    whole = {v.text for v in leaf.eligible()}
    if leaf.takes and not (asked and asked < whole):   # the words didn't pick these values out
        context = [(f, tuple((stated or {}).get(f, ()))) for f in sorted(leaf.takes)]
        pairs = [(t, w) for t, w in leaf.weigh(pairs, context) if w > 0]
    return Bank(leaf.id, leaf.label, tuple(pairs)) if pairs else None


def age_years(text: str) -> int:
    """An age list value's years ("34-year-old": 34, "newborn": 0), for showing a stage's span."""
    m = re.match(r"(\d+)-year-old$", text.strip())
    return int(m.group(1)) if m else 0


def allowed_ages(fits: Optional[Sequence[str]] = None, minor: Sequence[str] = ()) -> List[str]:
    """The ages a person may be seeded with, in list order: what narrowing kept of the age list
    (`fits`; None while it isn't there or when it failed: every adult age) and the ages under 18
    the minors rules allow them (`minor`: Seeds.minor, seeding's record["minor"])."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(AGE)
    if leaf is None:
        return []
    allowed = set(fits) if fits is not None else {v.text for v in leaf.values if not v.opt_in}
    allowed |= set(minor)
    return [v.text for v in leaf.values if v.text in allowed]


def year_ages(years: Sequence[int]) -> List[str]:
    """The age list's values for single years (24: "24-year-old", 0: "newborn"), in list order."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(AGE)
    want = set(years)
    return [v.text for v in leaf.values if age_years(v.text) in want] if leaf is not None else []


def age_stages(fits: Optional[Sequence[str]] = None, minor: Sequence[str] = ()) -> Dict[str, List[str]]:
    """A person's ages by life stage: {stage: the ages in it they may be seeded with}, in the age
    list's stage order, only stages with any. Their ages are what narrowing kept of the age list
    (`fits`; None while it isn't there or when it failed: every adult age) and the ages under 18
    the minors rules allow them (`minor`: Seeds.minor, seeding's record["minor"]). A stage that
    holds an age under 18 (child, teen) is there only when the minors rules already allow them one,
    so a pick never widens who may be under 18 (stimma-plans MINORS_POLICY.md)."""
    from prompt_programs.vocab import minor_ages, vocabulary
    leaf = vocabulary().get(AGE)
    if leaf is None:
        return {}
    allowed = set(allowed_ages(fits, minor))
    may_minor = bool(minor_ages(sorted(allowed)))
    by: Dict[str, List[Any]] = {str(st): [] for st in leaf.local_facets.get(STAGE, ())}
    for v in leaf.values:
        for st in v.tags.get(STAGE) or ():
            by.setdefault(str(st), []).append(v)
    out: Dict[str, List[str]] = {}
    for st, vals in by.items():
        if not may_minor and any(v.minor for v in vals):
            continue
        ages = [v.text for v in vals if v.text in allowed]
        if ages:
            out[st] = ages
    return out


def stages_of(age: Any) -> Tuple[str, ...]:
    """The life stages of one age list value (a variant's recorded age seed); () for none."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(AGE)
    v = leaf.value(age) if leaf is not None and isinstance(age, str) and age else None
    return tuple(str(x) for x in (v.tags.get(STAGE) or ())) if v is not None else ()


@dataclass(frozen=True)
class Pins:
    """Seeds the user picked for a person: descent values, world regions (any descent in them),
    genders, ages as life stages (age_stages) and single years: any of the picked stages or
    years. They restrict the banks of the next writes and filter what is drawn."""
    descent: Tuple[str, ...] = ()
    regions: Tuple[str, ...] = ()
    gender: Tuple[str, ...] = ()
    age: Tuple[str, ...] = ()       # life stages
    years: Tuple[int, ...] = ()     # single years of age (0: a newborn)

    def __bool__(self) -> bool:
        return bool(self.descent or self.regions or self.gender or self.age or self.years)

    def ages(self, fits: Optional[Sequence[str]] = None, minor: Sequence[str] = ()) -> List[str]:
        """The age values picked that a person may be (allowed_ages, age_stages): the picked
        stages' ages and the picked years, in list order; [] when none is picked or none fits."""
        if not (self.age or self.years):
            return []
        stages = age_stages(fits, minor)
        allowed = set(allowed_ages(fits, minor))
        want = {a for st in self.age for a in stages.get(st, ())} | {a for a in year_ages(self.years) if a in allowed}
        return [a for a in allowed_ages(fits, minor) if a in want]

    def descents(self) -> Optional[List[str]]:
        """The heritage values picked (a region as every value in it, of whichever heritage list
        is browsed by it: descent's world regions, a pack's clan lines), or None when none are."""
        if not (self.descent or self.regions):
            return None
        from prompt_programs.vocab import vocabulary
        vocab = vocabulary()
        out = list(self.descent)
        if self.regions:
            want = set(self.regions)
            for lid in vocab.heritage_lists():
                leaf = vocab.get(lid)
                if leaf is not None and leaf.browse:
                    out += [v.text for v in leaf.values if want & {str(x) for x in v.tags.get(leaf.browse) or ()}]
        return list(dict.fromkeys(out))

    def to_dict(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in (("descent", self.descent), ("regions", self.regions),
                                        ("gender", self.gender), ("age", self.age), ("age_years", self.years)) if v}


@dataclass(frozen=True)
class Seeds:
    """What one slot's writes are seeded with, by the roles its kind's draw rules declare
    (kinds.ROLES; vocab/kinds/*.json)."""
    descent: Optional[Bank] = None        # the heritage role: one per variant, its look given, its word where it can be true
    descent_pinned: bool = False          # the heritages are the user's picks: each must appear
    gender: Optional[Bank] = None         # the who role (a gender, who a couple is): one per variant, told
    gender_fits: Optional[Tuple[str, ...]] = None   # what the words allow of it (None: not narrowed); picks don't change it
    age: Optional[Bank] = None            # the age role: one per variant, told, only where the words leave it open
    age_fits: Optional[Tuple[str, ...]] = None   # a person's ages as narrowed by their words (None: not narrowed)
    core: Optional[Bank] = None           # the core role: one value per variant to build on
    spread: Optional[Bank] = None         # a core list too short for cores: shown whole
    ideas: Tuple[Bank, ...] = ()          # lists ideas are drawn from (the writer may reject them)
    each: Tuple[Tuple[str, Bank, str, str], ...] = ()   # the each role: (label, bank, say, show), one value per variant
    minor: Tuple[str, ...] = ()           # the ages under 18 the person may be
    aspects: Optional[Any] = None         # kinds.Aspects: what each variant develops (a person's)
    dropped: Tuple[str, ...] = ()         # aspects this slot leaves out (what they wear, when the prompt says it)
    drop_if_none: Tuple[Tuple[str, str], ...] = ()   # (aspect, role): left out when that role seeds nothing
    typical: bool = False                 # the aspects' typical share applies to this slot
    place: Optional[Tuple[Tuple[str, str], ...]] = None   # the heritage's place context (places.py), as items
    heritage_list: str = ""               # the list the heritage role draws from (picks outside the bank)
    who_list: str = ""                    # the list the who role draws from
    who_label: str = "gender"             # the who role's label on a seed line
    who_say: str = "short"                # "short": the value's short form; "value": the value
    notes: Tuple[str, ...] = ()           # lines for the writer's turn (several people, a light part)
    room: int = 0                         # words a variant may add (0: MAX_ADDED_WORDS)
    second: float = 0.0                   # the share of variants whose second person gets a heritage of their own

    @property
    def person(self) -> bool:
        """A slot whose variants develop aspects of who they are (a person)."""
        return self.aspects is not None

    def pinned(self, pins: Optional[Pins]) -> "Seeds":
        """The seeds with the user's picks: heritage and who drawn only from what was picked
        (what the words allow of it, else what was picked)."""
        if not pins:
            return self
        out = self
        picked = pins.descents()
        if picked is not None and (self.descent is not None or self.heritage_list):
            fits = self.descent.only(picked) if self.descent is not None else None
            if fits is None and self.heritage_list:
                fits = bank(self.heritage_list, picked, minor=bool(self.minor))
                if fits is not None:
                    from prompt_programs.places import weigh
                    fits = replace(fits, values=weigh(fits.values, dict(self.place or ()), self.heritage_list))
            out = replace(out, descent=fits, descent_pinned=True)
        if pins.gender and (self.gender is not None or self.who_list):
            fits = self.gender.only(pins.gender) if self.gender is not None else None
            out = replace(out, gender=fits or bank(self.who_list or self.gender.list_id, pins.gender))
        if (pins.age or pins.years) and self.person:
            # Within what their words allow and the minors rules (age_stages), even where the words
            # state an age and no age is seeded unpinned: a picked age always shows in the variants.
            ages = pins.ages(self.age_fits, self.minor)
            picked = bank(AGE, ages, minor=bool(self.minor)) if ages else None
            if picked is not None:
                out = replace(out, age=picked)
        return out


def kind_seeds(kind: Any, *, heritage: Optional[Tuple[str, Optional[Sequence[str]]]] = None, stated_descent: bool = False,
               who: Optional[Tuple[str, Optional[Sequence[str]]]] = None, ages: Optional[Sequence[str]] = None,
               age_role: bool = False, ideas: Sequence[Tuple[str, Optional[Sequence[str]]]] = (),
               cores: Sequence[Tuple[str, Optional[Sequence[str]]]] = (),
               each: Sequence[Tuple[Dict[str, Any], Optional[Sequence[str]]]] = (),
               stated: Optional[Dict[str, Sequence[str]]] = None, minor: Sequence[str] = (),
               answers: Optional[Dict[str, Any]] = None, place: Optional[Dict[str, str]] = None) -> Seeds:
    """A slot's seeds by its kind (kinds.Kind) from its narrowed lists, role by role:
    `heritage`: (list, the values its words allow, None for the whole list), one per variant drawn
    by its context mix (places.py, `place`); `stated_descent`: the words state it, so a single
    value left needs no seed. `who`: (list, allowed values), one per variant by the list's shares.
    `ages`: the age narrowed by the words, None while that narrowing isn't there (no age is seeded
    then; a picked stage seeds one all the same, Seeds.pinned); `age_role`: the kind draws an age.
    `ideas`, `cores`, `each`: (list or rule, narrowed) per list. `stated`: what the prompt states of
    the scene (bank). `minor`: ages under 18 they may be besides their own. `answers`: the reading's
    answers, for the chosen options' notes, room and second heritage and the aspects' conditions."""
    from prompt_programs.kinds import Kind
    from prompt_programs.vocab import minor_ages, vocabulary
    k: Kind = kind
    answers = dict(answers or {})
    minor = tuple(dict.fromkeys([*(minor_ages(list(ages)) if ages else ()), *minor]))
    # What their age gives the lists of their look (graying, life stage: vocab tags), so a young
    # woman's ideas hold no salt-and-pepper or thinning hair.
    look = dict(stated or {})
    age_leaf = vocabulary().get(AGE)
    if ages and age_leaf is not None:
        for facet in age_leaf.gives:
            fams = sorted({f for a in ages for f in (age_leaf.context_tags(a, facet) or ())})
            if fams:
                look[facet] = fams
    from prompt_programs.places import weigh
    d = bank(heritage[0], heritage[1], minor=bool(minor)) if heritage else None
    if d is not None and stated_descent and len(d.values) == 1:
        d = None   # their words name it already
    if d is not None:
        d = replace(d, values=weigh(d.values, place, heritage[0]))   # the context mix, within what their words allow
    notes, room, second = [], k.room, 0.0
    for q in k.questions:
        o = q.option(str(answers.get(q.key) or q.default)) if q.type == "choice" else None
        if o is not None:
            notes += [o.note] if o.note else []
            room = max(room, o.room)
            second = max(second, o.second_heritage)
    if k.note:
        notes.append(k.note)
    who_rule = next((r for r in k.draws if r.role == "who" and isinstance(r.list, str)
                     and (who is None or r.list == who[0])), None)
    core = spread = None
    idea_banks = [b for b in (bank(lid, n, minor=bool(minor), stated=look) for lid, n in ideas) if b is not None]
    core_banks = [b for b in (bank(lid, n, minor=bool(minor), stated=stated) for lid, n in cores) if b is not None]
    if len(cores) == 1 and core_banks:
        if len(core_banks[0].values) >= k.first_write:
            core = core_banks[0]
        else:
            spread = core_banks[0]
    else:
        idea_banks += core_banks
    each_banks = tuple((str(r.get("label") or ""), b, str(r.get("say") or "value"), str(r.get("show") or ""))
                       for r, n in each for b in [bank(str(r["list"]), n, minor=bool(minor), stated=stated)] if b is not None)
    asp = k.aspects
    dropped: List[str] = []
    drop_if_none: List[Tuple[str, str]] = []
    typical = False
    if asp is not None:
        for name, cond in asp.drop.items():
            if "no_draw" in cond:
                drop_if_none.append((name, str(cond["no_draw"])))
            if any(_answered(answers.get(x)) for x in cond.get("answered") or ()):
                dropped.append(name)
        if asp.typical:
            typical = not any(_answered(answers.get(x)) for x in (asp.typical.get("unless") or {}).get("answered") or ())
    return Seeds(descent=d, place=tuple(sorted(place.items())) if place else None,
                 heritage_list=heritage[0] if heritage else "",
                 gender=bank(who[0], who[1]) if who else None, who_list=who[0] if who else "",
                 who_label=who_rule.label if who_rule else "gender", who_say=who_rule.say if who_rule else "short",
                 gender_fits=tuple(who[1]) if who and who[1] is not None else None,
                 age=bank(AGE, ages, minor=bool(minor)) if age_role and ages is not None and _open_age(ages) else None,
                 age_fits=tuple(ages) if ages is not None else None, minor=minor,
                 core=core, spread=spread, ideas=tuple(idea_banks), each=each_banks,
                 aspects=asp, dropped=tuple(dropped), drop_if_none=tuple(drop_if_none), typical=typical,
                 notes=tuple(notes), room=room, second=second)


def _answered(v: Any) -> bool:
    """Whether a reading's answer is given: words, a part's number, a list's id."""
    if isinstance(v, dict):
        return bool(v)
    return bool(str(v or "").strip()) and v is not False


def person_seeds(*, descent: Optional[Sequence[str]] = None, stated_descent: bool = False,
                 gender: Optional[Sequence[str]] = None,
                 ages: Optional[Sequence[str]] = None, ideas: Sequence[Tuple[str, Optional[Sequence[str]]]] = (),
                 stated: Optional[Dict[str, Sequence[str]]] = None, minor: Sequence[str] = (),
                 clothes_owned: bool = False, place: Optional[Dict[str, str]] = None,
                 people: str = "", gender_list: str = "", heritage: bool = True) -> Seeds:
    """The person kind's seeds (vocab/kinds/person.json) from explicit lists, as one person is
    seeded: the heritage from the human heritage list, the gender from the kind's first who list
    (`gender_list` for another: a couple's), an age. A shorthand over kind_seeds for scripts and
    tests; `clothes_owned`: the prompt says what they wear; `people`: the reading's answer for who
    the part names; `heritage`: False seeds none."""
    from prompt_programs.vocab import vocabulary
    k = vocabulary().kind("person")
    being = k.question("being")
    human = being.option(being.default) if being is not None else None
    who = gender_list or next((r.list for r in k.draws if r.role == "who" and isinstance(r.list, str)), "")
    return kind_seeds(k, heritage=(human.heritage, descent) if heritage and human and human.heritage else None,
                      stated_descent=stated_descent, who=(who, gender) if who else None, ages=ages, age_role=True,
                      ideas=ideas, stated=stated, minor=minor, place=place,
                      answers={**({"clothes": "as stated"} if clothes_owned else {}), **({"people": people} if people else {})})


def _open_age(ages: Sequence[str]) -> bool:
    """Whether a person's words leave their age open: narrowing kept every adult age ("chef",
    "person"). Words that state an age ("young woman", "elderly man", "a little girl") carry it, and
    a number beside them reads awkwardly; their narrowing still says who may be under 18."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(AGE)
    adults = {v.text for v in leaf.values if not v.opt_in} if leaf is not None else set()
    return bool(adults) and adults <= set(ages)


def list_seeds(lists: Sequence[Tuple[str, Optional[Sequence[str]]]], *, single: bool = False,
               minor: Sequence[str] = (), stated: Optional[Dict[str, Sequence[str]]] = None,
               n: int = N_OTHER) -> Seeds:
    """The seeds of a slot that isn't a person: (list, narrowed or None) per list it draws on.
    `single`: the slot is bound to that one list, which gives each variant its core when it holds
    at least `n` values (the pool's first write); a list with fewer is shown whole instead, with
    "spread the variants across these" (cores would repeat, and the writer copies a repeated
    core: 8 selfie angles for 30 variants). `minor`: the ages under 18 of the person it is about,
    if any. `stated`: what the prompt states of the scene (bank)."""
    m = tuple(minor)
    banks = [b for b in (bank(lid, nar, minor=bool(m), stated=stated) for lid, nar in lists) if b is not None]
    if single and len(lists) == 1 and banks:
        if len(banks[0].values) >= n:
            return Seeds(core=banks[0], minor=m)
        return Seeds(spread=banks[0], minor=m)
    return Seeds(ideas=tuple(banks), minor=m)


@dataclass
class Spec:
    """One variant's own seeds."""
    descent: str = ""
    gender: str = ""
    age: str = ""
    core: str = ""
    develop: Tuple[str, ...] = ()   # the aspects this variant describes in particular
    gender_needs: Tuple[str, ...] = ()   # the words of its who value the variant must state (none: the slot's words do)
    descent_required: bool = False  # a heritage the user picked: the variant must carry it
    ideas: Tuple[Tuple[str, str], ...] = ()   # this variant's own ideas: (text, list id)
    descent2: str = ""              # a second person's own heritage (Seeds.second of them)
    pair: bool = False              # the who value is shown whole (a couple's "who"), not its short form
    several: bool = False           # (kept for callers: room is what counts)
    look: str = ""                  # the heritage's look, when its list gives one (an invented people's)
    look2: str = ""
    who_label: str = "gender"
    room: int = 0                   # words it may add (0: MAX_ADDED_WORDS)
    each: Tuple[Tuple[str, str, bool], ...] = ()   # (label, value, must show)
    typical: bool = False           # one of the typical share: no list idea

    def line(self) -> str:
        def quoted(t: str, look: str) -> str:
            return f'"{t}"' + (f" ({look})" if look else "")
        heritage = quoted(self.descent, self.look) + (f" for one, {quoted(self.descent2, self.look2)} for the other"
                                                       if self.descent2 else "")
        who = (f'{self.who_label}: "{self.gender}"' if self.pair else f'{self.who_label}: "{gender_mark(self.gender)}"')
        parts = ([heritage + (" (must appear)" if self.descent_required else "")] if self.descent else []) \
            + ([who] if self.gender_needs else []) \
            + ([f"age: {self.age}"] if self.age else []) + ([f'core: "{self.core}"'] if self.core else []) \
            + [f'{label}: "{value}"' for label, value, _ in self.each] \
            + ([f"develop: {' and '.join(self.develop)}"] if self.develop else []) \
            + (["ideas: " + "; ".join(f'"{t}"' for t, _ in self.ideas)] if self.ideas else [])
        return ", ".join(parts)

    def seeds(self) -> Dict[str, str]:
        return {k: v for k, v in (("descent", self.descent), ("gender", self.gender), ("age", self.age),
                                  ("core", self.core), *((label, value) for label, value, _ in self.each)) if v}


def gender_mark(value: str, list_id: str = "") -> str:
    """What a variant must say of a who value: its list's short form (person.gender: "trans
    woman", "non-binary"; person.couple: "man, woman", "women"), else the value. Without a list,
    the first who list of any kind that holds it."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    lids = [list_id] if list_id else [r.list for k in vocab.ordered_kinds() for r in k.draws
                                      if r.role == "who" and isinstance(r.list, str)]
    for lid in lids:
        leaf = vocab.get(lid)
        if leaf is not None and leaf.value(value) is not None:
            return leaf.short(value)
    return value


def gender_needs(value: str, words: str = "", fits: Optional[Sequence[str]] = None, list_id: str = "") -> Tuple[str, ...]:
    """The words of a drawn who value a variant must state: those of its short form (gender_mark)
    that distinguish it from the others the slot's words allow, and that the words don't state
    already. `fits`: what the words narrowed the list to ("grandmother" keeps woman and trans
    woman), whose short forms' shared words the words already carry, so "woman" needs nothing there
    and "trans woman" needs "trans"; None (the words narrow nothing: "person", "chef"): the whole
    list, which shares no word, so every word of it not in the slot's words. A value the user
    picked outside what the words allow still has its distinguishing words to show."""
    from prompt_programs.vocab import vocabulary
    if not list_id:
        list_id = next((r.list for k in vocabulary().ordered_kinds() for r in k.draws
                        if r.role == "who" and isinstance(r.list, str)), "")
    if fits is None:
        leaf = vocabulary().get(list_id)
        fits = [v.text for v in leaf.values] if leaf is not None else []
    marks = [set(tokens(gender_mark(v, list_id))) for v in fits]
    shared = set.intersection(*marks) if marks else set()
    said = set(tokens(words))
    return tuple(t for t in tokens(gender_mark(value, list_id)) if t not in shared and t not in said)


def _weighted(rng: random.Random, pairs: Sequence[Tuple[str, float]]) -> str:
    total = sum(w for _, w in pairs)
    x = rng.random() * total
    for t, w in pairs:
        x -= w
        if x <= 0:
            return t
    return pairs[-1][0]


def _in_proportion(rng: random.Random, pairs: Sequence[Tuple[str, float]], n: int) -> List[str]:
    """`n` values whose counts follow the weights as closely as whole numbers can (systematic
    sampling: each value about n x its share, never a whole count off), in random order. A pool's
    40 descents drawn one by one can land far from the mix (22 of 40 Vietnamese where the mix
    gives 29); drawn this way they can't."""
    total = sum(w for _, w in pairs)
    if n <= 0 or total <= 0:
        return [_weighted(rng, pairs) for _ in range(max(0, n))]
    step = total / n
    x = rng.random() * step
    out: List[str] = []
    acc = 0.0
    for t, w in pairs:
        acc += w
        while x < acc and len(out) < n:
            out.append(t)
            x += step
    while len(out) < n:   # rounding at the top end
        out.append(pairs[-1][0])
    rng.shuffle(out)
    return out


def _spread(rng: random.Random, b: Bank, n: int, used: Sequence[str] = ()) -> List[str]:
    """n values of a list by its weights, each once before any repeats; values in `used` (the
    pool built on them already) come after the rest."""
    out: List[str] = []
    fresh = [x for x in b.values if x[0] not in set(used)]
    while fresh and len(out) < n:
        t = _weighted(rng, fresh)
        out.append(t)
        fresh = [x for x in fresh if x[0] != t]
    while len(out) < n:
        left = list(b.values)
        while left and len(out) < n:
            t = _weighted(rng, left)
            out.append(t)
            left = [x for x in left if x[0] != t]
    return out


def _palette_fill(text: str, rng: random.Random, list_id: str = "") -> str:
    """A template value ("a {main} coat") with a palette's colors, within the palettes the value
    allows (its `palette` restriction: a tuxedo takes only dark schemes)."""
    from prompt_programs.vocab import fill, is_template, tags_match, vocabulary
    if not is_template(text):
        return text
    vocab = vocabulary()
    leaf = vocab.get(list_id) if list_id else None
    pal = vocab.get(leaf.slots) if leaf is not None and leaf.slots else vocab.get("person.palette")
    if pal is None or not pal.values:
        return fill(text, None)
    v = leaf.value(text) if leaf is not None else None
    want = dict(v.palette) if v is not None and v.palette else {}
    fits = [p for p in pal.values if tags_match(p.tags, want)] or list(pal.values)
    return fill(text, rng.choice(fits).roles)


@dataclass
class Drawn:
    """A batch's seeds: per variant its own (its ideas among them), short lists shown whole."""
    specs: List[Spec]
    short: List[Bank]

    @property
    def ideas(self) -> List[Tuple[str, str]]:
        """Every idea the batch offers, (text, list id), variant by variant."""
        return [x for s in self.specs for x in s.ideas]


def draw_seeds(rng: random.Random, seeds: Seeds, n: int, words: str = "", used_cores: Sequence[str] = ()) -> Drawn:
    """Per variant its heritage (the write's heritages in proportion to the mix), who value and
    age (each by its list's weights), core (each value once before any repeats, the ones the pool
    hasn't built on first), its each-role values and, for a kind with aspects, the aspects to
    develop (every combination in a shuffled cycle, so the set doesn't share one template; the
    typical share instead develops what is typical and takes no list idea); its own 1-2 ideas from
    the long idea lists, on its seed line, no repeats in a batch; short idea lists shown whole.
    `words`: the slot's words (a who value they state, or that every value they allow shares, needs
    no seed line: gender_needs)."""
    import itertools
    from prompt_programs.vocab import vocabulary
    cores = _spread(rng, seeds.core, n, used_cores) if seeds.core is not None else []
    asp = seeds.aspects
    present = {"heritage": seeds.descent, "who": seeds.gender, "age": seeds.age, "core": seeds.core}
    gone = set(seeds.dropped) | {a for a, role in seeds.drop_if_none if present.get(role) is None}
    aspects = [a for a in asp.items if a not in gone] if asp is not None else []
    combos = list(itertools.combinations(aspects, asp.per_variant)) if asp is not None and len(aspects) >= asp.per_variant else []
    rng.shuffle(combos)
    typ = asp.typical if asp is not None and seeds.typical else None
    heritage_leaf = vocabulary().get(seeds.descent.list_id) if seeds.descent is not None else None
    specs: List[Spec] = []
    descents = _in_proportion(rng, seeds.descent.values, n) if seeds.descent is not None else []
    room = seeds.room
    for i in range(n):
        s = Spec(who_label=seeds.who_label, room=room, several=room > MAX_ADDED_WORDS)
        if seeds.descent is not None:
            s.descent = descents[i]
            s.descent_required = seeds.descent_pinned
            if seeds.second and not seeds.descent_pinned and rng.random() < seeds.second:
                s.descent2 = _weighted(rng, [x for x in seeds.descent.values if x[0] != s.descent] or seeds.descent.values)
            if heritage_leaf is not None:
                s.look = heritage_leaf.look(s.descent)
                s.look2 = heritage_leaf.look(s.descent2) if s.descent2 else ""
        if seeds.gender is not None:
            s.gender = _weighted(rng, seeds.gender.values)
            s.gender_needs = gender_needs(s.gender, words, seeds.gender_fits, seeds.gender.list_id)
            s.pair = seeds.who_say == "value"
        if seeds.person and combos:
            s.develop = combos[i % len(combos)]
            if typ is not None and asp.typical_at(i):   # no look ideas: what is typical for who and where they are
                s.develop = (str(typ["text"]), *[a for a in s.develop if a != typ.get("replaces")][:asp.per_variant - 1])
                s.typical = True
        if seeds.age is not None:
            s.age = _weighted(rng, seeds.age.values)
        if cores:
            s.core = _palette_fill(cores[i], rng, seeds.core.list_id)
        if seeds.each:
            s.each = tuple((label, _palette_fill(_weighted(rng, b.values), rng, b.list_id), show == "must")
                           for label, b, say, show in seeds.each)
        specs.append(s)
    short = [b for b in seeds.ideas if len(b.values) <= SHORTLIST] + ([seeds.spread] if seeds.spread is not None else [])
    long_ = [b for b in seeds.ideas if len(b.values) > SHORTLIST]
    seen: set = set()
    if long_:
        for s in specs:
            if s.typical:
                continue
            mine: List[Tuple[str, str]] = []
            for b in rng.sample(long_, min(len(long_), rng.choice([1, 2]))):
                t = ""
                for _ in range(8):   # breadth: no repeats within a batch
                    t = _weighted(rng, b.values)
                    if t not in seen:
                        break
                if t in seen:
                    continue
                seen.add(t)
                mine.append((_palette_fill(t, rng, b.list_id), b.list_id))
            s.ideas = tuple(mine)
    return Drawn(specs, short)


def typical_text(kind: str = "person") -> str:
    """The aspect a kind's typical share develops (person: what someone like them would typically
    wear or carry here); "" for a kind with none."""
    from prompt_programs.vocab import vocabulary
    k = vocabulary().kind(kind)
    return str(((k.aspects.typical if k is not None and k.aspects is not None else None) or {}).get("text") or "")


# --------------------------------------------------------------------------- the writer prompt

SYSTEM_HEAD = """You write variants of one marked part of an image prompt, for a tool that makes many images from one prompt.

The prompt is below. The part to vary is marked ⟦like this⟧. Write {n} variants of it. A variant replaces ONLY the marked part: one specific, concrete take on it. Everything outside the marks stays in the prompt as it is, so never include it in a variant.

Words. Every variant contains the words you are told to keep, exactly, in order, as part of a natural phrase. The category word (if there is one) may be replaced by a specific kind of it, and usually should be:"""

EXAMPLES_FIRST = ('"⟦clothing slightly open in the front⟧" (keep "slightly open in the front"; category "clothing") -> '
                  '"a white cardigan slightly open in the front", "a satin robe slightly open in the front"')
EXAMPLES_LAST = ('"a cozy ⟦room⟧ with a crackling fireplace" (category "room") -> "reading room lined with built-in bookshelves", '
                 'never "a cozy reading room with a crackling fireplace" (the words outside the marks are already in the prompt)')

RULES = (
    "Vary only the thing the marked words name. For a single property (a camera angle, a shot size, a lens, a light, a time of day), say only that property: an angle says where the camera is, a shot size says how much of the subject is in frame, a light says only the light. No grain, style, lens, framing, mood or anything else.",
    'Each variant must read correctly in its exact place in the prompt: read the words right before the marks and right after them. When the words before already begin the phrase the part ends ("a low quality cell phone ⟦type of selfie⟧", "her ⟦outfit⟧", "two ⟦women⟧"), the variant continues that phrase: no article or determiner of its own, and never a word repeated from just before the marks.',
    "Fit the whole prompt: its place, time, medium, framing, number of people, and the notes (lines starting with #). Never move the scene somewhere else.",
    "Other parts in <angle brackets> vary on their own: don't fill them in, and don't repeat what the rest of the prompt already says.",
    "Never add a person or an animal the prompt doesn't have, including through framing: no group selfie, group portrait, two-shot or crowd unless the prompt has that many people.",
    "Visual and concrete: what it looks like, not mood or story.",
    "Make the variants clearly different from each other, across the whole range the words allow, including uncommon but real choices. At most 20 words each beyond the kept words.",
    'Each variant stands alone: never "another", "also", "again" or a reference to other variants.',
)

# The minors policy (stimma-plans MINORS_POLICY.md): the engine's, never a kind's.
MINOR_RULES = (
    'Every person is an adult unless the prompt\'s own words make them a child or teenager; "a girl" or "a boy" alone is a young adult.',
    "If a person may be under 18, nothing sexual or adult-coded.",
)

SEED_RULES = (
    'ideas: random ideas from vocabulary lists for this variant, for breadth and uncommon picks. Use each where it could be true here, adjusting its wording a little if needed, and name the ones used in the variant\'s "idea" field, separated by "; " ("" for none). Reject one that can\'t be true in this prompt or doesn\'t suit this variant, listing it under "rejected", copied exactly.',
    'core: build this variant on that value, adding a few words that place it in this prompt. If it can\'t be true in this prompt, use another value of the same kind and list the core under "rejected".',
)

REPLY = """Reply with one JSON object per line and nothing else: no list around them, no code fence. First, only if some ideas or cores don't fit, one line {"rejected": ["..."]}. Then one line per variant, in order:
{"n": 1, "text": "...", "idea": "..."}"""


def system_text(n: Any = "{n}") -> str:
    """The writer's system prompt: the engine's framing and rules with every kind's writing rules
    (vocab/kinds/*.json writer: examples, rules, seed_rules), in the kinds' order."""
    from prompt_programs.vocab import vocabulary
    kinds = vocabulary().ordered_kinds()
    examples = [EXAMPLES_FIRST, *(x for k in kinds for x in k.writer_examples), EXAMPLES_LAST]
    rules = [*RULES, *(x for k in kinds for x in k.writer_rules), *MINOR_RULES]
    seeds = [*(x for k in kinds for x in k.seed_rules), *SEED_RULES]
    return "\n".join([SYSTEM_HEAD.replace("{n}", str(n)), *(f"- {x}" for x in examples), "", "Rules:",
                      *(f"- {x}" for x in rules), "", "Per-variant seeds, one line per variant when given:",
                      *(f"- {x}" for x in seeds), "", REPLY])


CORE_NOTE = ("The cores are random values of a list, and some won't fit this prompt. A core that would add people (a "
             "two-shot, a group portrait or a group selfie when the prompt has one person), frame a person the prompt "
             "doesn't have, or name another kind of picture than this one (a mirror selfie in a photo that isn't a "
             "selfie), or a thing this place wouldn't have, doesn't fit: put it under \"rejected\" and write that "
             "variant with another value of the same kind that fits.")


def minor_words(ages: Sequence[str]) -> str:
    """A minor person's possible ages, for the writer: "13-year-old" ... -> "13, 14 or 15 years old"."""
    spans = [a[: -len("-year-old")] if a.endswith("-year-old") else a for a in ages]
    return (", ".join(spans[:-1]) + " or " + spans[-1] if len(spans) > 1 else spans[0]) + " years old"


def minor_line(ages: Sequence[str]) -> str:
    """The writer's line for a person who may be under 18 (MINORS_POLICY.md)."""
    return (f"This person is under 18 ({minor_words(ages)}), as the prompt asks: every variant must be what someone "
            "that age would ordinarily wear, do or look like.")


@dataclass(frozen=True)
class Slot:
    """The slot a pool is written for: its words where they stand in the prompt."""
    words: str
    prompt: str                    # the prompt as parsed: comment lines included, [exact text] masked
    span: Tuple[int, int]          # where <words> stands in it, brackets included
    kind: str = "free"             # the reader's kind
    category: str = ""             # checked with valid_category

    @property
    def n(self) -> int:
        """The first write's size: the kind's (vocab/kinds/*.json first_write), else N_OTHER."""
        from prompt_programs.vocab import vocabulary
        k = vocabulary().kind(self.kind)
        return k.first_write if k is not None else N_OTHER

    def marked(self) -> str:
        return self.prompt[:self.span[0]] + f"⟦{self.words}⟧" + self.prompt[self.span[1]:]

    def around(self, n: int = 6) -> Tuple[str, str]:
        """The words right before and right after the slot on its line (up to `n` each), as typed."""
        a, b = self.span
        line_start = self.prompt.rfind("\n", 0, a) + 1
        line_end = self.prompt.find("\n", b)
        line_end = len(self.prompt) if line_end < 0 else line_end
        left = self.prompt[line_start:a].split()
        right = self.prompt[b:line_end].split()
        return " ".join(left[-n:]).strip() or "(start of line)", " ".join(right[:n]).strip() or "(end of line)"

    def keep(self) -> List[str]:
        return kept_chunks(self.words, valid_category(self.words, self.category, self.kind))


def messages(slot: Slot, drawn: Drawn, seeds: Seeds, have: Sequence[str] = ()) -> List[Dict[str, str]]:
    """The writer's request for one batch."""
    n = len(drawn.specs)
    cat = valid_category(slot.words, slot.category, slot.kind)
    keep = kept_chunks(slot.words, cat)
    before, after = slot.around()
    lines = ["Prompt:", '"""', slot.marked(), '"""', "", f'Marked part: "{slot.words}".',
             f'It stands between "{before}" and "{after}": each variant must read correctly there, '
             'as one continuous phrase.']
    if not cat:
        lines.append(f'No category word: every variant contains exactly these words: "{slot.words}".')
    elif keep:
        lines.append(f'Category word: "{cat}" (may become a kind of it). Every variant contains exactly: '
                     + ", ".join(f'"{k}"' for k in keep) + ".")
    else:
        lines.append(f'The whole part is the category "{cat}": every variant is a specific kind of it.')
    if seeds.minor:
        lines.append(minor_line(seeds.minor))
    lines += list(seeds.notes)   # the kind's and its chosen options' notes (several people, a light part)
    lines.append("")
    for b in drawn.short:
        lines.append(f"Spread the variants across these {b.label.lower()} choices where they fit: "
                     + "; ".join(f'"{t}"' for t, _ in b.values) + ".")
    if have:
        lines += ["", "Already written (write different ones; don't repeat or paraphrase these):"]
        lines += [f"- {t}" for t in list(have)[-HAVE_SHOWN:]]
    if any(s.line() for s in drawn.specs):
        lines += ["", "Seeds, one line per variant:"]
        lines += [f"{i}. {s.line()}" for i, s in enumerate(drawn.specs, 1)]
    if any(s.core for s in drawn.specs):
        lines += ["", CORE_NOTE]
    lines += ["", f"Write {n} variants."]
    return [{"role": "system", "content": system_text(n)}, {"role": "user", "content": "\n".join(lines)}]


# --------------------------------------------------------------------------- repair and check

_WS = re.compile(r"\s+")
_ARTICLES = ("a", "an", "the")


def _norm(s: str) -> str:
    return _WS.sub(" ", str(s)).strip()


_DETERMINERS = ("a", "an", "the", "my", "your", "his", "her", "its", "our", "their", "this", "that", "these", "those")


def article_before(prompt: str, span: Tuple[int, int], words: str = "") -> bool:
    """Whether the phrase the slot ends already has its determiner: an article or a possessive in
    the words before it on its line, back to the last punctuation or slot ("a low quality cell
    phone <type of selfie>", "her <outfit>", "a cozy <room>"), when the slot's own words start with
    none. Then a variant's own leading article would read "phone a selfie". Grammar words only;
    nothing else is read. A telegraphic "a man with fedora" is the accepted cost."""
    from prompt_programs.slots import SLOT_RE
    if tokens(words)[:1] and tokens(words)[0] in _ARTICLES:
        return False
    a = span[0]
    before = SLOT_RE.split(prompt[prompt.rfind("\n", 0, a) + 1:a])[-1]
    clause = re.split(r"[,;:.!?()\[\]{}]", before)[-1]
    return any(w in _DETERMINERS for w in tokens(clause))


def context_words(prompt: str, span: Tuple[int, int]) -> Tuple[List[str], List[str]]:
    """The prompt's words just outside the slot on its line, up to the next slot either side."""
    from prompt_programs.slots import SLOT_RE
    a, b = span
    ls, le = prompt.rfind("\n", 0, a) + 1, prompt.find("\n", b)
    le = len(prompt) if le < 0 else le
    left = SLOT_RE.split(prompt[ls:a])[-1]
    right = SLOT_RE.split(prompt[b:le])[0]
    return re.findall(r"[\w'-]+", left), re.findall(r"[\w'-]+", right)


def repair(text: str, left: Sequence[str], right: Sequence[str], *, words: str = "",
           article: Optional[bool] = None, before: str = "") -> Tuple[str, List[str]]:
    """A variant cut back to the slot's part: the slot's own words given as a label before a colon
    ("young woman: a tall ..."), another slot's markup and what follows it, a copied run of the
    prompt's words just before the slot (at its start) or just after it (to its end), and its own
    leading article when the prompt has one for it (`article`, article_before; by default when the
    word right before the slot is one). `before`: the prompt's text before the slot on its line; a
    copy of it that reaches back over another slot's markup ("a <grandmother> with her cat") is cut
    first, so the markup rule doesn't take the variant with it. Structural."""
    did: List[str] = []
    t = _norm(text)
    if words:
        m = re.match(r"^\W*" + r"\W+".join(re.escape(w) for w in tokens(words)) + r"\s*:\s*", t, re.I)
        if m and tokens(words):
            t = t[m.end():]
            did.append("label")
    parts = _norm(before).split()
    for k in range(len(parts), 0, -1):
        run = " ".join(parts[-k:])
        if "<" in run and t.lower().startswith(run.lower() + " "):
            t = t[len(run):].lstrip()
            did.append("left")
            break
    if "<" in t:
        t = t[:t.index("<")]
        did.append("markup")
        # Cut at the next slot's markup, it copied the words between this slot and that one:
        # "grandmother with <her pet>" leaves "grandmother with", and "with" is already in the prompt.
        if right:
            m = re.search(r"(?<![\w'-])" + r"\W+".join(re.escape(w) for w in right) + r"\W*$", t, re.I)
            if m and m.start() > 0:
                t = t[:m.start()]
                did.append("right")
    for k in (len(left), 4, 3, 2, 1):
        lw = list(left[-k:]) if k <= len(left) else []
        if lw and (len(lw) >= 2 or lw[-1].lower() not in _ARTICLES):   # one word too: "two <women>" -> no "two two"
            m = re.match(r"^\W*(?:" + r"\W+".join(re.escape(w) for w in lw) + r")\b\W*", t, re.I)
            if m:
                t = t[m.end():]
                did.append("left")
                break
    for k in (len(right), 4, 3, 2):
        rw = list(right[:k]) if k <= len(right) else []
        if len(rw) >= 2 and not (len(rw) == 2 and rw[-1].lower() in _ARTICLES):
            m = re.search(r"(?<![\w'-])" + r"\W+".join(re.escape(w) for w in rw) + r"(?![\w'-])", t, re.I)
            if m and m.start() > 0:
                t = t[:m.start()]
                did.append("right")
                break
    t = re.sub(r"^[\s,;:.-]+|[\s,;:-]+$", "", t)
    if (article if article is not None else bool(left) and left[-1].lower() in _ARTICLES):
        m = re.match(r"(?i)(a|an|the)\s+(?=\S+\s+\S)", t)
        if m:
            t = t[m.end():]
            did.append("article")
    return t, did


_MARKUP = set("<>⟦⟧{}[]\n")


def check(text: str, words: str, keep: Sequence[str], spec: Spec, *, cut: bool = False) -> str:
    """"" when a repaired variant passes, else why not. `cut`: repair cut it at another slot's
    markup (a reply that copied the prompt), so what is left may be a fragment ("a", "fighting
    a"): it must still end on more than a grammar word. A variant of grammar words alone is never
    one. Structure only: the closed lists of articles and determiners, never content words."""
    if not text:
        return "empty"
    if any(c in _MARKUP for c in text):
        return "markup in text"
    tt = tokens(text)
    if tt and all(t in _DETERMINERS for t in tt):
        return "fragment"
    if cut and (not tt or tt[-1] in _DETERMINERS):
        return "fragment"
    if spec.gender_needs and not all(t in tt for t in spec.gender_needs):
        return "gender missing"
    # The words of a gender may stand inside the user's own run ("young trans woman"), and so may
    # the variant's own descent seed ("dominant young Maori woman"): both are its seeds' words,
    # placed where English puts them. Structure only: the seed's run, taken out once.
    bare = [t for t in tt if t not in spec.gender_needs] if spec.gender_needs else tt
    runs = [tt, bare]
    dt = tokens(spec.descent) if spec.descent else []
    at = _run_at(bare, dt) if dt else -1
    if at >= 0:
        runs.append(bare[:at] + bare[at + len(dt):])
    for k in keep:
        if all(_run_at(r, tokens(k)) < 0 for r in runs):
            return "words not kept"
    if len(tokens(text)) - sum(len(tokens(k)) for k in keep) > (spec.room or (MAX_ADDED_PEOPLE if spec.several else MAX_ADDED_WORDS)):
        return "too long"
    if tokens(text) == tokens(words):
        return "adds nothing"
    if spec.descent and spec.descent_required and not has_run(text, spec.descent):
        return "descent missing"   # a descent the user picked must appear; a seeded one may be left out
    for label, value, must in spec.each:
        if must and not has_run(text, value):
            return f"{label} missing"
    return ""


_DECODER = json.JSONDecoder()


def _objects(s: str) -> List[Dict[str, Any]]:
    """Every complete JSON object in `s`, outermost first, in order: fences, prose and other
    objects around them aside."""
    out: List[Dict[str, Any]] = []
    i = 0
    while True:
        j = s.find("{", i)
        if j < 0:
            return out
        try:
            v, end = _DECODER.raw_decode(s, j)
        except ValueError:
            i = j + 1   # not an object here (prose, a cut-off one): look inside and past it
            continue
        if isinstance(v, dict):
            out.append(v)
        i = end


def _cut_variants(s: str) -> Optional[Dict[str, Any]]:
    """A reply cut off inside its variants list (the token budget ran out): the variants that
    closed before the cut, with the rejected list when it closed; None when none did."""
    k = s.rfind('"variants"')
    j = s.find("[", k) if k >= 0 else -1
    if j < 0:
        return None
    items: List[Any] = []
    i = j + 1
    while True:
        while i < len(s) and s[i] in " \t\r\n,":
            i += 1
        if i >= len(s) or s[i] != "{":
            break
        try:
            v, i = _DECODER.raw_decode(s, i)
        except ValueError:
            break   # the cut
        items.append(v)
    if not items:
        return None
    out: Dict[str, Any] = {"variants": items}
    r = s.rfind('"rejected"', 0, k)
    if r >= 0:
        a = s.find("[", r)
        try:
            got, _ = _DECODER.raw_decode(s, a) if 0 <= a < k else (None, 0)
        except ValueError:
            got = None
        if isinstance(got, list):
            out["rejected"] = got
    return out


def parse_reply(reply: Optional[str]) -> Optional[Dict[str, Any]]:
    """The reply's JSON object however it is fenced or surrounded; None when there is none. A
    model that writes an object, talks, and writes another (each in its own fence) is read by its
    last object with a variants list, its final answer. A reply cut off before any such object
    closed keeps the variants that closed before the cut. With no variants list anywhere, the last
    object."""
    if not reply:
        return None
    s = str(reply)
    objs = _objects(s)
    full = [o for o in objs if isinstance(o.get("variants"), list)]
    if full:
        return full[-1]
    cut = _cut_variants(s)
    if cut is not None:
        return cut
    return objs[-1] if objs else None
# --------------------------------------------------------------------------- a session per pool

class ObjectReader:
    """Streamed text in, each complete top-level JSON object ({...}) out the moment its closing
    brace arrives: whether the model writes one per line, as asked, or spreads one over several
    lines (one local model does). Text outside objects (fences, chatter) is ignored; a broken
    object costs that object only."""

    def __init__(self) -> None:
        self.buf: List[str] = []
        self.depth = 0
        self.in_str = False
        self.esc = False

    def feed(self, delta: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for ch in delta:
            if self.depth == 0:
                if ch == "{":
                    self.depth, self.buf, self.in_str, self.esc = 1, ["{"], False, False
                continue
            self.buf.append(ch)
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif ch == "\\":
                    self.esc = True
                elif ch == '"':
                    self.in_str = False
                continue
            if ch == '"':
                self.in_str = True
            elif ch == "{":
                self.depth += 1
            elif ch == "}":
                self.depth -= 1
                if self.depth == 0:
                    try:
                        obj = json.loads("".join(self.buf).replace("\n", " "))
                    except ValueError:
                        obj = None
                    if isinstance(obj, dict):
                        out.append(obj)
                    self.buf = []
        return out

    def rest(self) -> str:
        """An object still open when the text ended (a reply cut at its token budget)."""
        return "".join(self.buf) if self.depth > 0 else ""


def turn_tokens(n: int) -> int:
    """A turn's reply budget: about WRITE_TOKENS per N_PERSON variants, with room to spare."""
    return max(900, int(WRITE_TOKENS * n / N_PERSON) + 400)


FIRST_NOTE = "Number them from 1; I will ask for more in later turns."


def first_turn(slot: Slot, drawn: Drawn, seeds: Seeds, have: Sequence[str] = ()) -> List[Dict[str, str]]:
    """A session's opening: the system prompt and the first user turn (the prompt with the slot
    marked, the kept words, the rules, this turn's seed lines; `have`: what the pool holds already,
    when a session starts again over a pool)."""
    msgs = messages(slot, drawn, seeds, have)
    msgs[1]["content"] += "\n" + FIRST_NOTE
    return msgs


def more_turn(drawn: Drawn, a: int, seeds: Seeds, *, unseeded_start: bool = False) -> str:
    """A later turn: write n more, numbered on from `a`, with this turn's seed lines. When the
    session opened unseeded (written while the slot's seeds were narrowed), the lists it shows
    whole and the minors line come with the first seeded turn."""
    n = len(drawn.specs)
    lines = [f"Write {n} more variants of the same marked part, numbered {a} to {a + n - 1}, each clearly different "
             "from every variant above: not a repeat, not a paraphrase, not the same idea reworded."]
    if unseeded_start:
        if seeds.minor:
            lines += ["", minor_line(seeds.minor)]
        for b in drawn.short:
            lines += ["", f"Spread the variants across these {b.label.lower()} choices where they fit: "
                      + "; ".join(f'"{t}"' for t, _ in b.values) + "."]
    if any(s.line() for s in drawn.specs):
        lines += ["", "Seeds, one line per variant:"]
        lines += [f"{a + i}. {s.line()}" for i, s in enumerate(drawn.specs)]
    if any(s.core for s in drawn.specs):
        lines += ["", CORE_NOTE if unseeded_start else 'Cores that don\'t fit go under "rejected" as before.']
    lines += ["", "Same reply format: one JSON object per line."]
    return "\n".join(lines)


def reply_text(variants: Sequence[Dict[str, Any]], a: int, rejected: Sequence[str] = ()) -> str:
    """A turn's reply as the log keeps it: only the variants that passed, numbered on from `a`,
    in the reply format, so a later turn never copies a mistake that was dropped."""
    lines = [json.dumps({"rejected": list(rejected)}, ensure_ascii=False)] if rejected else []
    for i, v in enumerate(variants):
        idea = str((v.get("seeds") or {}).get("idea") or "")
        lines.append(json.dumps({"n": a + i, "text": v["text"], "idea": idea}, ensure_ascii=False))
    return "\n".join(lines)


@dataclass
class Session:
    """One pool's chat log: the system prompt, the first user turn, then each logged turn's reply
    (its survivors only) and the next user turn. Stored with the pool (variant_pools.VariantStore)
    so every later write continues it. `texts`: the variants the logged replies hold, in order."""
    messages: List[Dict[str, str]] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)
    seeded: bool = True        # the log has shown the slot's seeds (False: opened unseeded while they were narrowed)
    restarts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"v": 1, "messages": self.messages, "texts": self.texts, "seeded": self.seeded,
                "restarts": self.restarts}

    @classmethod
    def of(cls, obj: Any) -> "Session":
        o = obj if isinstance(obj, dict) and obj.get("v") == 1 else {}
        msgs = [m for m in o.get("messages") or [] if isinstance(m, dict) and isinstance(m.get("content"), str)
                and m.get("role") in ("system", "user", "assistant")]
        if len(msgs) < 3 or msgs[-1]["role"] != "assistant":
            return cls()   # nothing logged (or unreadable): the next turn starts it afresh
        return cls(msgs, [str(t) for t in o.get("texts") or [] if isinstance(t, str)], bool(o.get("seeded", True)),
                   int(o.get("restarts") or 0))

    @property
    def open(self) -> bool:
        return bool(self.messages)

    def sent(self, user: str, removed: Sequence[str] = ()) -> List[Dict[str, str]]:
        """What a turn sends: the whole log and `user`, or past COMPACT_AT variants the system
        prompt, the first user turn and its reply, then the other variants already written as a
        compact list (most recent last, at most COMPACT_CHARS; never a removed one) before `user`.
        A long log is slow to read uncached and slows one local model's writing by half."""
        if len(self.texts) <= COMPACT_AT:
            return [*self.messages, {"role": "user", "content": user}]
        head = self.messages[:3]
        gone = {_norm(t).lower() for t in removed}
        shown = {_norm(json.loads(ln)["text"]).lower() for ln in head[2]["content"].splitlines()
                 if ln.startswith('{"n"')}
        rest = [t for t in self.texts if _norm(t).lower() not in gone and _norm(t).lower() not in shown]
        keep: List[str] = []
        size = 0
        for t in reversed(rest[-HAVE_SHOWN * 2:]):
            size += len(t) + 3
            if size > COMPACT_CHARS:
                break
            keep.append(t)
        listed = "\n".join(f"- {t}" for t in reversed(keep))
        return [*head, {"role": "user", "content": "Also already written (most recent last):\n" + listed + "\n\n" + user}]

    def log(self, sent_user: Dict[str, str], reply: str, texts: Sequence[str]) -> None:
        """Append one turn that passed: its user turn and its survivors' reply."""
        self.messages += [sent_user, {"role": "assistant", "content": reply}]
        self.texts += list(texts)


@dataclass
class Turn:
    """One turn of a session: the variants that passed (each stored as it landed), what was
    dropped and why, and how the call went."""
    asked: int
    variants: List[Dict[str, Any]] = field(default_factory=list)   # {"text", "seeds"}
    dropped: Counter = field(default_factory=Counter)
    rejected: List[str] = field(default_factory=list)
    repairs: int = 0
    ideas: Dict[str, int] = field(default_factory=dict)   # offered, used, rejected
    descents: Counter = field(default_factory=Counter)    # seeded, written (kept variants with a descent seed)
    seconds: float = 0.0
    first: Optional[float] = None                         # seconds to the first text
    streamed: bool = False
    error: str = ""                                       # the call failed, hit a deadline or its reply was unreadable

    @property
    def passed(self) -> bool:
        """Kept at least half of what it asked for: it may join the log."""
        return self.asked > 0 and 2 * len(self.variants) >= self.asked

    def texts(self) -> List[str]:
        return [v["text"] for v in self.variants]


class Deadline(Exception):
    """A streamed call ran past one of its deadlines."""


async def _consume(it: Any, on_text: Callable[[str], None], t0: float) -> Optional[float]:
    """Read a stream of text deltas into `on_text` under three deadlines enforced here, whatever
    the client library does (a measured stream once hung with its connection open and its read
    timeout never fired): FIRST_TOKEN_SECONDS to the first text, STALL_SECONDS between texts, and
    TURN_SECONDS for the whole. Returns the seconds to the first text; raises Deadline."""
    import time
    first: Optional[float] = None
    try:
        while True:
            now = time.monotonic()
            left = TURN_SECONDS - (now - t0)
            wait = min(left, FIRST_TOKEN_SECONDS - (now - t0) if first is None else STALL_SECONDS)
            if left <= 0:
                raise Deadline("overall deadline")
            try:
                async with asyncio.timeout(max(0.0, wait)):
                    delta = await it.__anext__()
            except StopAsyncIteration:
                return first
            except TimeoutError:
                raise Deadline("overall deadline" if wait >= left else
                               "first-token deadline" if first is None else "stall deadline") from None
            if delta:
                if first is None:
                    first = round(time.monotonic() - t0, 3)
                on_text(str(delta))
    finally:
        with contextlib.suppress(Exception):
            await it.aclose()


async def write_turn(slot: Slot, drawn: Drawn, sent: List[Dict[str, Any]], *, ask: Ask, a: int = 1,
                     project_id: Optional[int] = None, seen: Optional[set] = None,
                     landed: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Turn:
    """One turn of a session: `sent` is what goes to the model, `drawn` this turn's seeds
    (numbered from `a`). Streamed where `ask` can stream (`ask.stream`), else the whole reply at
    once. Each variant is repaired and checked the moment its object completes, and handed to
    `landed` (which stores it; False: no room, the variant is dropped), so a picker sees the first
    one in under a second. `seen`: normalized texts the pool holds or removed (updated). Never
    raises: a failed call, a deadline or an unreadable reply keeps what landed before it."""
    import time
    from llm_http import StreamUnsupported
    from prompt_programs.fill import fix_articles
    out = Turn(asked=len(drawn.specs))
    seen = seen if seen is not None else set()
    keep = slot.keep()
    left, right = context_words(slot.prompt, slot.span)
    article = article_before(slot.prompt, slot.span, slot.words)
    before = slot.prompt[slot.prompt.rfind("\n", 0, slot.span[0]) + 1:slot.span[0]]
    taken: set = set()
    used: List[str] = []
    reader = ObjectReader()

    def index(obj: Dict[str, Any]) -> Optional[int]:
        n = obj.get("n")
        if isinstance(n, int) and not isinstance(n, bool) and 0 <= n - a < len(drawn.specs) and n - a not in taken:
            return n - a
        return next((i for i in range(len(drawn.specs)) if i not in taken), None)

    def take(obj: Dict[str, Any]) -> None:
        if isinstance(obj.get("variants"), list):   # the whole reply as one object, as an older format had it
            for it in obj["variants"]:
                if isinstance(it, dict):
                    take(it)
            obj = {"rejected": obj.get("rejected")} if "rejected" in obj else {}
        if "text" not in obj:
            if isinstance(obj.get("rejected"), list):
                out.rejected += [_norm(x) for x in obj["rejected"] if isinstance(x, str) and x.strip()]
            return
        i = index(obj)
        if i is None:
            out.dropped["extra"] += 1
            return
        taken.add(i)
        spec = drawn.specs[i]
        if not isinstance(obj.get("text"), str):
            out.dropped["missing"] += 1
            return
        fixed, did = repair(obj["text"], left, right, words=slot.words, article=article, before=before)
        fixed = fix_articles(fixed)   # "a off-center selfie" is stored as "an off-center selfie"
        out.repairs += bool(did)
        why = check(fixed, slot.words, keep, spec, cut="markup" in did)
        if why:
            out.dropped[why] += 1
            return
        if _norm(fixed).lower() in seen:
            out.dropped["duplicate"] += 1
            return
        got = spec.seeds()
        if spec.descent:
            if has_run(fixed, spec.descent):
                out.descents["written"] += 1
            else:   # left out where it couldn't be true: the picker's matches stay real
                got.pop("descent", None)
        idea = _norm(obj.get("idea") or "") if isinstance(obj.get("idea"), str) else ""
        if idea and idea.lower() != spec.core.lower():
            got["idea"] = idea
        v = {"text": fixed, "seeds": got}
        if landed is not None:
            try:
                if landed(v) is False:
                    out.dropped["no room"] += 1
                    return
            except Exception as e:   # storing one failing never loses the others
                log.warning(f"[variants] keeping a variant of {slot.words!r} failed: {e}")
                out.dropped["not stored"] += 1
                return
        seen.add(_norm(fixed).lower())
        if spec.descent:
            out.descents["seeded"] += 1
        if idea:
            used.extend(x.strip().lower() for x in idea.split(";") if x.strip())
        out.variants.append(v)

    def on_text(delta: str) -> None:
        for obj in reader.feed(delta):
            take(obj)

    def on_whole(reply: str) -> None:
        # A whole reply may be the old shape fenced more than once: an answer, talk, and another
        # answer (its last one counts), or one cut off inside its variants list (the closed ones).
        objs = _objects(reply)
        full = [o for o in objs if isinstance(o.get("variants"), list)]
        cut = None if full else _cut_variants(reply)
        if full or cut is not None:
            for o in objs:
                if "rejected" in o and not isinstance(o.get("variants"), list):
                    take({"rejected": o["rejected"]})
            take(full[-1] if full else cut)
        else:
            on_text(reply)

    def on_end() -> None:
        tail = reader.rest()   # a streamed reply in the old shape, cut off before its object closed
        if tail:
            cut = _cut_variants(tail)
            if cut is not None:
                take(cut)

    t0 = time.monotonic()
    stream = getattr(ask, "stream", None)
    tokens_ = turn_tokens(len(drawn.specs))
    whole = stream is None
    try:
        if stream is not None:
            try:
                it = stream(sent, project_id, tokens_, temperature=WRITE_TEMPERATURE).__aiter__()
                out.first = await _consume(it, on_text, t0)
                out.streamed = True
            except StreamUnsupported:
                whole = True   # this provider answers whole: the same turn, all at once
        if whole:
            async with asyncio.timeout(TURN_SECONDS):
                reply = await ask(sent, project_id, tokens_, temperature=WRITE_TEMPERATURE)
            out.first = round(time.monotonic() - t0, 3)
            on_whole(str(reply or ""))
    except Deadline as e:
        out.error = str(e)
    except TimeoutError:
        out.error = "overall deadline"
    except Exception as e:   # a model slip or an unreachable model degrades: the slot stands as written
        out.error = f"{type(e).__name__}: {e}"[:200] or "call failed"
    if out.streamed or out.error:
        on_end()
    out.seconds = round(time.monotonic() - t0, 2)
    if out.error:
        log.warning(f"[variants] a turn for {slot.words!r} ended early ({out.error}); keeping {len(out.variants)}")
    if not taken and not out.error:
        out.error = "unreadable reply"
    if len(taken) < len(drawn.specs):
        out.dropped["missing"] += len(drawn.specs) - len(taken)
    offered = [t for t, _ in drawn.ideas]
    rejected = {x.lower() for x in out.rejected}
    out.ideas = {"offered": len(offered),
                 "used": sum(1 for t in offered if t.lower() in used or any(has_run(v, t) for v in out.texts())),
                 "rejected": sum(1 for t in offered if _norm(t).lower() in rejected)}
    return out


def split(drawn: Drawn, size: int = TURN) -> List[Drawn]:
    """A write's seeds as turns of at most `size` variants (short lists go with every turn).
    Seeds are drawn once for the whole write, so the turns spread across descents, aspects, cores
    and ideas as one call would."""
    n = len(drawn.specs)
    if n <= size:
        return [drawn]
    k = -(-n // size)
    bounds = [round(i * n / k) for i in range(k + 1)]
    return [Drawn(drawn.specs[a:b], drawn.short) for a, b in zip(bounds, bounds[1:])]


__all__ = ["AGE", "STAGE", "Ask", "Bank", "Deadline", "Drawn", "N_OTHER", "N_PERSON", "MIN_POOL", "MORE_TURNS",
           "ObjectReader", "Pins", "SHORTLIST", "Seeds", "kind_seeds", "system_text", "typical_text", "Session", "Slot", "Spec", "TOPUP", "TURN", "Turn",
           "VARIANTS_VERSION", "age_stages", "age_years", "allowed_ages", "article_before", "ask_writer", "bank",
           "check", "context_words", "draw_seeds", "first_turn", "gender_mark", "gender_needs", "has_run", "kept_chunks", "list_seeds", "messages",
           "minor_line", "minor_words", "more_turn", "parse_reply", "person_seeds", "repair", "reply_text", "split", "stages_of",
           "tokens", "valid_category", "write_turn", "year_ages"]

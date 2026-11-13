"""The variant writer: a slot's values are variants of the user's words, written by the model.

    <dominant young woman> standing in her living room in <clothing slightly open in the front>

A slot is an area of the prompt where the user wants variety. Its value is one variant: a
specific, concrete take that keeps the slot's words, never a replacement for them. One call per
slot, with reasoning off and plain JSON, sees the whole prompt with the slot marked and writes
about 30 variants (40 for a person); top-ups write 20 more. The pool is stored and drawn from
with no model call per image (variant_pools.py).

- Words. A variant keeps every word of the slot exactly, except its category word, which the
  reader names ("clothing" in "clothing slightly open in the front") and which the variant may
  replace with a kind of it ("a white cardigan slightly open in the front"). A person has no
  category word. Code checks the kept words verbatim, as runs of words, structurally.
- Seeds. The vocabulary seeds the writer instead of supplying the output: random ideas from the
  slot's lists (the writer may reject them), one list value per variant as its core for a slot
  bound to one list, and for a person a descent per variant that must appear, drawn from the
  descent list's own distribution, plus their gender and an age. Long lists are never
  shown to the model; a list of SHORTLIST values or fewer is shown whole.
- Checks. A variant that copies the prompt around the slot, another slot's markup or an article
  the prompt already has is repaired; then it must keep the words, carry its descent, add
  something and stay short. A variant failing a check is dropped and counted, never an error.
- Minors (stimma-plans MINORS_POLICY.md). A person is an adult unless the prompt's own words make
  them a child or teenager. Age seeds come from the age list's pool, which holds no band under 18
  unless narrowing asked for one. A person who may be under 18 gets no adult-only seed and the
  writer is told their age.

This module makes calls and checks replies; it stores nothing. `ask` is injected: the app's chat
model (ask_writer) or a fake in tests.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger

log = get_logger(__name__)

VARIANTS_VERSION = "variants-9"   # variants-9: a person's look ideas fit their age. variants-8: light seeded by ideas, held to the place. variants-7: people vary their shape; age shows only where open. variants-6: worked person examples, fuller people. variants-5: a person is authored, two aspects per variant; gender must be stated; cores the pool has come last. variants-4: a variant drops its article after a determined phrase. variants-3: the writer is shown the words around the slot and continues the phrase. variants-2: an age seed only where the words leave age open; a copied single word is cut
N_PERSON = 40          # the first write for a person
N_OTHER = 30           # the first write for anything else
TOPUP = 20             # a top-up, and More like these
MIN_POOL = 12          # fewer survivors than this from the first call asks once more
MAX_ADDED_WORDS = 30   # words a variant may add to the kept words
SHORTLIST = 7          # a list this short is shown to the writer whole
HAVE_SHOWN = 80        # the pool's latest texts a top-up is told it already has
WRITE_TOKENS = 4500    # a write's reply budget: 40 variants of about 20 words, with no reasoning
WRITE_SECONDS = 150.0  # one write call, at most
WRITE_TEMPERATURE = 0.8

DESCENT = "person.ethnicity"
GENDER = "person.gender"
AGE = "person.age_band"

# askable chat model: (messages, project_id, max_tokens, temperature) -> reply text
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
    words, "" for a person or for anything that isn't one. Structure only."""
    if kind == "person" or not isinstance(category, str) or not tokens(category):
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


@dataclass(frozen=True)
class Pins:
    """Seeds the user picked for a person: descent values, world regions (any descent in them),
    genders. They restrict the banks of the next writes and filter what is drawn."""
    descent: Tuple[str, ...] = ()
    regions: Tuple[str, ...] = ()
    gender: Tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.descent or self.regions or self.gender)

    def descents(self) -> Optional[List[str]]:
        """The descent values picked (a region as every value in it), or None when none are."""
        if not (self.descent or self.regions):
            return None
        from prompt_programs.vocab import vocabulary
        leaf = vocabulary().get(DESCENT)
        out = list(self.descent)
        if leaf is not None and leaf.browse and self.regions:
            want = set(self.regions)
            out += [v.text for v in leaf.values if want & {str(x) for x in v.tags.get(leaf.browse) or ()}]
        return list(dict.fromkeys(out))

    def to_dict(self) -> Dict[str, List[str]]:
        return {k: list(v) for k, v in (("descent", self.descent), ("regions", self.regions),
                                        ("gender", self.gender)) if v}


@dataclass(frozen=True)
class Seeds:
    """What one slot's writes are seeded with."""
    descent: Optional[Bank] = None        # a person's descent: one per variant, must appear
    gender: Optional[Bank] = None         # a person's gender: one per variant, told
    age: Optional[Bank] = None            # a person's age: one per variant, told
    core: Optional[Bank] = None           # a slot bound to one list: one value per variant to build on
    ideas: Tuple[Bank, ...] = ()          # lists ideas are drawn from (the writer may reject them)
    minor: Tuple[str, ...] = ()           # the ages under 18 the person may be
    person: bool = False                  # a person: each variant develops its own aspects (ASPECTS)
    clothes_owned: bool = False           # the prompt or another part says what they wear

    def pinned(self, pins: Optional[Pins]) -> "Seeds":
        """The seeds with the user's picks: descent and gender drawn only from what was picked
        (what the words allow of it, else what was picked)."""
        if not pins:
            return self
        out = self
        picked = pins.descents()
        if picked is not None:
            fits = self.descent.only(picked) if self.descent is not None else None
            out = replace(out, descent=fits or bank(DESCENT, picked, minor=bool(self.minor)))
        if pins.gender:
            fits = self.gender.only(pins.gender) if self.gender is not None else None
            out = replace(out, gender=fits or bank(GENDER, pins.gender))
        return out


def person_seeds(*, descent: Optional[Sequence[str]] = None, stated_descent: bool = False,
                 gender: Optional[Sequence[str]] = None,
                 ages: Optional[Sequence[str]] = None, ideas: Sequence[Tuple[str, Optional[Sequence[str]]]] = (),
                 stated: Optional[Dict[str, Sequence[str]]] = None, minor: Sequence[str] = (),
                 clothes_owned: bool = False) -> Seeds:
    """A person's seeds. `descent`: the descent values their words allow (narrowed; None when the
    words state none: the whole list). `stated_descent`: their words state it, so a single value
    left needs no seed. `gender`: the genders their words allow (narrowed: "woman" keeps woman and
    trans woman; None when the words state none: the whole list), one per variant by the list's
    shares. `ages`:
    their age narrowed by their words; None while that narrowing isn't there, which seeds no age
    (an unnarrowed age would fight "young" or "elderly"; the writer keeps them adults). `ideas`:
    (list, narrowed or None) per list whose values may seed their look. `stated`: what the prompt
    states of the scene (bank). `minor`: ages under 18 they may be besides their own (a user list
    of ages on their line). `clothes_owned`: the prompt or another part says what they wear, so no
    variant develops their clothes."""
    from prompt_programs.vocab import minor_ages, vocabulary
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
    d = bank(DESCENT, descent, minor=bool(minor))
    if d is not None and stated_descent and len(d.values) == 1:
        d = None   # their words name it already
    return Seeds(descent=d, gender=bank(GENDER, gender), person=True, clothes_owned=clothes_owned,
                 age=bank(AGE, ages, minor=bool(minor)) if ages is not None and _open_age(ages) else None, minor=minor,
                 ideas=tuple(b for b in (bank(lid, n, minor=bool(minor), stated=look) for lid, n in ideas)
                             if b is not None))


def _open_age(ages: Sequence[str]) -> bool:
    """Whether a person's words leave their age open: narrowing kept every adult age ("chef",
    "person"). Words that state an age ("young woman", "elderly man", "a little girl") carry it, and
    a number beside them reads awkwardly; their narrowing still says who may be under 18."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(AGE)
    adults = {v.text for v in leaf.values if not v.opt_in} if leaf is not None else set()
    return bool(adults) and adults <= set(ages)


def list_seeds(lists: Sequence[Tuple[str, Optional[Sequence[str]]]], *, single: bool = False,
               minor: Sequence[str] = (), stated: Optional[Dict[str, Sequence[str]]] = None) -> Seeds:
    """The seeds of a slot that isn't a person: (list, narrowed or None) per list it draws on.
    `single`: the slot is bound to that one list, which gives each variant its core; a list of
    SHORTLIST values or fewer is shown whole instead (cores would repeat, and the writer copies a
    repeated core). `minor`: the ages under 18 of the person it is about, if any. `stated`: what
    the prompt states of the scene (bank)."""
    m = tuple(minor)
    banks = [b for b in (bank(lid, n, minor=bool(m), stated=stated) for lid, n in lists) if b is not None]
    if single and len(lists) == 1 and banks and len(banks[0].values) > SHORTLIST:
        return Seeds(core=banks[0], minor=m)
    return Seeds(ideas=tuple(banks), minor=m)


@dataclass
class Spec:
    """One variant's own seeds."""
    descent: str = ""
    gender: str = ""
    age: str = ""
    core: str = ""
    develop: Tuple[str, ...] = ()   # a person's aspects this variant describes in particular
    gender_needs: Tuple[str, ...] = ()   # the words of its gender the variant must state (none: the slot's words do)

    def line(self) -> str:
        parts = ([f'"{self.descent}"'] if self.descent else []) \
            + ([f'gender: "{gender_mark(self.gender)}"'] if self.gender_needs else []) \
            + ([f"age: {self.age}"] if self.age else []) + ([f'core: "{self.core}"'] if self.core else []) \
            + ([f"develop: {' and '.join(self.develop)}"] if self.develop else [])
        return ", ".join(parts)

    def seeds(self) -> Dict[str, str]:
        return {k: v for k, v in (("descent", self.descent), ("gender", self.gender), ("age", self.age),
                                  ("core", self.core)) if v}


CLOTHES = "what they wear"
# The aspects of a person the writer is asked to develop, two per variant, rotated (draw_seeds).
AGE_SHOWS = "how their age shows"
ASPECTS = ("bearing and posture", "expression", "styling and grooming", CLOTHES, "build", "face",
           "what they carry or hold", AGE_SHOWS)


def gender_mark(value: str) -> str:
    """What a variant must say of a gender: the gender list's short form (vocab person.gender:
    "trans woman", "non-binary"), else the value."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(GENDER)
    return leaf.short(value) if leaf is not None else value


def _weighted(rng: random.Random, pairs: Sequence[Tuple[str, float]]) -> str:
    total = sum(w for _, w in pairs)
    x = rng.random() * total
    for t, w in pairs:
        x -= w
        if x <= 0:
            return t
    return pairs[-1][0]


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
    """A batch's seeds: per variant its own, ideas for the batch, short lists shown whole."""
    specs: List[Spec]
    ideas: List[Tuple[str, str]]          # (text, list id)
    short: List[Bank]


def draw_seeds(rng: random.Random, seeds: Seeds, n: int, words: str = "", used_cores: Sequence[str] = ()) -> Drawn:
    """Per variant its descent, gender and age (each by its list's weights), core (each value once
    before any repeats, the ones the pool hasn't built on first) and, for a person, two aspects to
    develop (rotated, so the set doesn't share one template); 1-2 ideas per variant from the long
    idea lists, no repeats in a batch; short idea lists shown whole. `words`: the slot's words (a
    gender they state needs no seed line)."""
    cores = _spread(rng, seeds.core, n, used_cores) if seeds.core is not None else []
    aspects = [a for a in ASPECTS if not (seeds.clothes_owned and a == CLOTHES)
               and not (a == AGE_SHOWS and seeds.age is None)]   # words that state an age carry it ("young")
    pairs = [(a, b) for i, a in enumerate(aspects) for b in aspects[i + 1:]]   # every pair, in a shuffled cycle
    rng.shuffle(pairs)
    specs: List[Spec] = []
    for i in range(n):
        s = Spec()
        if seeds.descent is not None:
            s.descent = _weighted(rng, seeds.descent.values)
        if seeds.gender is not None:
            s.gender = _weighted(rng, seeds.gender.values)
            s.gender_needs = tuple(t for t in tokens(gender_mark(s.gender)) if t not in tokens(words))
        if seeds.person and pairs:
            s.develop = pairs[i % len(pairs)]
        if seeds.age is not None:
            s.age = _weighted(rng, seeds.age.values)
        if cores:
            s.core = _palette_fill(cores[i], rng, seeds.core.list_id)
        specs.append(s)
    short = [b for b in seeds.ideas if len(b.values) <= SHORTLIST]
    long_ = [b for b in seeds.ideas if len(b.values) > SHORTLIST]
    ideas: List[Tuple[str, str]] = []
    seen: set = set()
    if long_:
        for _ in range(n):
            for b in rng.sample(long_, min(len(long_), rng.choice([1, 2]))):
                t = ""
                for _ in range(8):   # breadth: no repeats within a batch
                    t = _weighted(rng, b.values)
                    if t not in seen:
                        break
                if t in seen:
                    continue
                seen.add(t)
                ideas.append((_palette_fill(t, rng, b.list_id), b.list_id))
    rng.shuffle(ideas)
    return Drawn(specs, ideas, short)


# --------------------------------------------------------------------------- the writer prompt

SYSTEM = """You write variants of one marked part of an image prompt, for a tool that makes many images from one prompt.

The prompt is below. The part to vary is marked ⟦like this⟧. Write {n} variants of it. A variant replaces ONLY the marked part: one specific, concrete take on it. Everything outside the marks stays in the prompt as it is, so never include it in a variant.

Words. Every variant contains the words you are told to keep, exactly, in order, as part of a natural phrase. The category word (if there is one) may be replaced by a specific kind of it, and usually should be:
- "⟦clothing slightly open in the front⟧" (keep "slightly open in the front"; category "clothing") -> "a white cardigan slightly open in the front", "a satin robe slightly open in the front"
- "lit by ⟦lighting⟧" (keep nothing; category "lighting") -> "warm lamplight from a bedside lamp", "cold blue light from a phone screen"
- "⟦selfie camera angle⟧" (keep "selfie"; category "camera angle") -> "a high-angle selfie, phone held above her head", "a low selfie angle from chest height"
- "a ⟦young woman⟧ in a kitchen" (keep "young woman") -> "freckled young woman with a short black bob"
- "a ⟦dominant young woman⟧ in a living room", three variants with their seed lines ("Tunisian", develop: bearing and posture and expression / "Korean", gender: "trans woman", develop: styling and grooming and what they carry / "Peruvian", develop: build and what they wear) -> "dominant young woman of Tunisian heritage, shoulders squared and chin lifted, giving the camera a cool, level stare that dares it to look away", "dominant young trans woman, Korean, hair slicked straight back, a dark lip, car keys looped around one finger like she owns the room", "tall, broad-shouldered dominant young woman, Peruvian, in a fitted black blazer worn over bare skin, sleeves pushed up"
- "a cozy ⟦room⟧ with a crackling fireplace" (category "room") -> "reading room lined with built-in bookshelves", never "a cozy reading room with a crackling fireplace" (the words outside the marks are already in the prompt)

Rules:
- Vary only the thing the marked words name. For a single property (a camera angle, a shot size, a lens, a light, a time of day), say only that property: an angle says where the camera is, a shot size says how much of the subject is in frame, a light says only the light. No grain, style, lens, framing, mood or anything else.
- Each variant must read correctly in its exact place in the prompt: read the words right before the marks and right after them. When the words before already begin the phrase the part ends ("a low quality cell phone ⟦type of selfie⟧", "her ⟦outfit⟧", "two ⟦women⟧"), the variant continues that phrase: no article or determiner of its own, and never a word repeated from just before the marks.
- Fit the whole prompt: its place, time, medium, framing, number of people, and the notes (lines starting with #). Never move the scene somewhere else.
- Other parts in <angle brackets> vary on their own: don't fill them in, and don't repeat what the rest of the prompt already says.
- Never add a person or an animal the prompt doesn't have, including through framing: no group selfie, group portrait, two-shot or crowd unless the prompt has that many people.
- Light comes only from sources that would ordinarily be in or reach this exact place: a living room has lamps, ceiling lights, a TV or screens, candles, a fireplace and its windows; never stage, shop, office, industrial, bathroom, darkroom, stadium or street fixtures unless the prompt puts them there, and never shade from a tree, dappled leaves, golden-hour sun on a beach or underwater light indoors. With no stated place, ordinary light that could be anywhere. Reject a light idea that this place wouldn't have.
- Visual and concrete: what it looks like, not mood or story.
- Make the variants clearly different from each other, across the whole range the words allow, including uncommon but real choices. At most 20 words each beyond the kept words.
- A person: 12 to 25 words beyond the marked words. Write each variant as an authored take on who this is, leaning into the marked words themselves: for "dominant young woman", how her dominance shows in her bearing, expression, styling and attitude, and in what she wears or carries when the prompt leaves that open. Each variant develops the aspects its seed line names, so the set differs in far more than hair. No shared template: vary how each variant is phrased and where things fall in it (the marked words first in some, after a detail in others: "broad-shouldered Peruvian dominant young woman in a fitted blazer"; the descent before the words, after them, or as "of Tunisian heritage"), and weave its seeds in where they read naturally, never as a list or a prefix. Never describe what another part of the prompt owns (a clothing part elsewhere owns the clothes).
- Each variant stands alone: never "another", "also", "again" or a reference to other variants.
- Every person is an adult unless the prompt's own words make them a child or teenager; "a girl" or "a boy" alone is a young adult.
- If a person may be under 18, nothing sexual or adult-coded.

Ideas. You may get ideas drawn at random from vocabulary lists, for breadth and uncommon picks. Use an idea wherever it could be true here, each at most once, adjusting its wording a little if needed; name it in the variant's "idea" field ("" for none). Reject only an idea that contradicts the prompt or the kept words, listing it under "rejected" first, copied exactly.

Per-variant seeds, one line per variant when given:
- a quoted descent: write that exact word or words into the variant, woven in where it reads naturally, meaning that heritage's look. If the marked words name several people, it applies to one of them.
- gender: write the person as that, with those exact words in the variant ("a trans woman", "a young trans woman"), woven in naturally; the marked words still stay.
- develop: the aspects of the person this variant describes in particular; others lightly or not at all. Hair is one aspect among many, not a must.
- age: about how old the person looks; work it in before their words ("a 34-year-old chef") or say it another natural way ("a chef in her forties"), never as a number tacked on at the end.
- core: build this variant on that value, adding a few words that place it in this prompt. If it can't be true in this prompt, use another value of the same kind and list the core under "rejected".

Reply with JSON only, no other text:
{"rejected": ["..."], "variants": [{"n": 1, "text": "...", "idea": "..."}, ...]}"""


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
        return N_PERSON if self.kind == "person" else N_OTHER

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
    lines.append("")
    for b in drawn.short:
        lines.append(f"Spread the variants across these {b.label.lower()} choices where they fit: "
                     + "; ".join(f'"{t}"' for t, _ in b.values) + ".")
    if drawn.ideas:
        lines.append("Ideas (random; reject the ones that don't fit):")
        lines += [f'- "{t}"' for t, _ in drawn.ideas]
    if have:
        lines += ["", "Already written (write different ones; don't repeat or paraphrase these):"]
        lines += [f"- {t}" for t in list(have)[-HAVE_SHOWN:]]
    if any(s.line() for s in drawn.specs):
        lines += ["", "Seeds, one line per variant:"]
        lines += [f"{i}. {s.line()}" for i, s in enumerate(drawn.specs, 1)]
    if any(s.core for s in drawn.specs):
        lines += ["", CORE_NOTE]
    lines += ["", f"Write {n} variants."]
    return [{"role": "system", "content": SYSTEM.replace("{n}", str(n))}, {"role": "user", "content": "\n".join(lines)}]


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
           article: Optional[bool] = None) -> Tuple[str, List[str]]:
    """A variant cut back to the slot's part: the slot's own words given as a label before a colon
    ("young woman: a tall ..."), another slot's markup and what follows it, a copied run of the
    prompt's words just before the slot (at its start) or just after it (to its end), and its own
    leading article when the prompt has one for it (`article`, article_before; by default when the
    word right before the slot is one). Structural."""
    did: List[str] = []
    t = _norm(text)
    if words:
        m = re.match(r"^\W*" + r"\W+".join(re.escape(w) for w in tokens(words)) + r"\s*:\s*", t, re.I)
        if m and tokens(words):
            t = t[m.end():]
            did.append("label")
    if "<" in t:
        t = t[:t.index("<")]
        did.append("markup")
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


def check(text: str, words: str, keep: Sequence[str], spec: Spec) -> str:
    """"" when a repaired variant passes, else why not."""
    if not text:
        return "empty"
    if any(c in _MARKUP for c in text):
        return "markup in text"
    tt = tokens(text)
    if spec.gender_needs and not all(t in tt for t in spec.gender_needs):
        return "gender missing"
    # The words of a gender may stand inside the user's own run ("young trans woman").
    bare = [t for t in tt if t not in spec.gender_needs] if spec.gender_needs else tt
    for k in keep:
        if _run_at(tt, tokens(k)) < 0 and _run_at(bare, tokens(k)) < 0:
            return "words not kept"
    if len(tokens(text)) - sum(len(tokens(k)) for k in keep) > MAX_ADDED_WORDS:
        return "too long"
    if tokens(text) == tokens(words):
        return "adds nothing"
    if spec.descent and not has_run(text, spec.descent):
        return "descent missing"
    return ""


def parse_reply(reply: Optional[str]) -> Optional[Dict[str, Any]]:
    """The reply's JSON object, fences and chatter around it aside; None when there is none."""
    if not reply:
        return None
    s = re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.M).strip()
    if "{" not in s:
        return None
    s = s[s.find("{"): s.rfind("}") + 1]
    try:
        v = json.loads(s)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


# --------------------------------------------------------------------------- one batch

@dataclass
class Batch:
    """One writer call: the variants that passed, each with its seeds, and what was dropped."""
    variants: List[Dict[str, Any]] = field(default_factory=list)   # {"text", "seeds"}
    dropped: Counter = field(default_factory=Counter)
    repairs: int = 0
    ideas: Dict[str, int] = field(default_factory=dict)   # offered, used, rejected
    seconds: float = 0.0
    error: str = ""                                       # the call failed or its reply was unreadable

    def texts(self) -> List[str]:
        return [v["text"] for v in self.variants]


async def write_batch(slot: Slot, seeds: Seeds, n: int, *, ask: Ask, project_id: Optional[int] = None,
                      have: Sequence[str] = (), rng: Optional[random.Random] = None,
                      used_cores: Sequence[str] = ()) -> Batch:
    """One writer call for `n` variants, checked. Never raises: a failed call or an unreadable
    reply is a batch with nothing in it and its `error`."""
    import time
    rng = rng or random.Random()
    drawn = draw_seeds(rng, seeds, n, slot.words, used_cores)
    out = Batch()
    t0 = time.monotonic()
    try:
        reply = await asyncio.wait_for(ask(messages(slot, drawn, seeds, have), project_id, WRITE_TOKENS,
                                           temperature=WRITE_TEMPERATURE), WRITE_SECONDS)
    except Exception as e:   # a model slip or an unreachable model degrades: the slot stands as written
        out.error = f"{type(e).__name__}: {e}"[:200] or "call failed"
        log.warning(f"[variants] writing {slot.words!r} failed: {out.error}")
        out.seconds = round(time.monotonic() - t0, 2)
        return out
    out.seconds = round(time.monotonic() - t0, 2)
    obj = parse_reply(reply)
    items = obj.get("variants") if obj else None
    if not isinstance(items, list):
        out.error = "unreadable reply"
        log.info(f"[variants] the writer's reply for {slot.words!r} can't be read: {str(reply)[:200]!r}")
        return out
    rejected = {_norm(x).lower() for x in obj.get("rejected") or [] if isinstance(x, str)} \
        if isinstance(obj.get("rejected"), list) else set()
    keep = slot.keep()
    left, right = context_words(slot.prompt, slot.span)
    article = article_before(slot.prompt, slot.span, slot.words)
    seen = {_norm(h).lower() for h in have}
    used: List[str] = []
    for i, spec in enumerate(drawn.specs):
        it = items[i] if i < len(items) else None
        if not isinstance(it, dict) or not isinstance(it.get("text"), str):
            out.dropped["missing"] += 1
            continue
        fixed, did = repair(it["text"], left, right, words=slot.words, article=article)
        out.repairs += bool(did)
        why = check(fixed, slot.words, keep, spec)
        if why:
            out.dropped[why] += 1
            continue
        if fixed.lower() in seen:
            out.dropped["duplicate"] += 1
            continue
        seen.add(fixed.lower())
        got = spec.seeds()
        idea = _norm(it.get("idea") or "") if isinstance(it.get("idea"), str) else ""
        if idea and idea.lower() != spec.core.lower():
            got["idea"] = idea
            used.append(idea.lower())
        out.variants.append({"text": fixed, "seeds": got})
    offered = [t for t, _ in drawn.ideas]
    out.ideas = {"offered": len(offered),
                 "used": sum(1 for t in offered if t.lower() in used or any(has_run(v, t) for v in out.texts())),
                 "rejected": sum(1 for t in offered if _norm(t).lower() in rejected)}
    return out


async def write_first(slot: Slot, seeds: Seeds, *, ask: Ask, project_id: Optional[int] = None,
                      key: str = "") -> List[Batch]:
    """A slot's first pool: one call for Slot.n variants, and once more with fresh seeds when
    fewer than MIN_POOL survive. The batches in order; none kept anything when every one is
    empty, and the slot then stands as written."""
    batches: List[Batch] = []
    have: List[str] = []
    for b in range(2):
        got = await write_batch(slot, seeds, slot.n, ask=ask, project_id=project_id, have=have,
                                rng=random.Random(f"{key}|{b}") if key else None)
        batches.append(got)
        have += got.texts()
        if len(have) >= MIN_POOL:
            break
    return batches


async def top_up(slot: Slot, seeds: Seeds, have: Sequence[str], *, ask: Ask, project_id: Optional[int] = None,
                 n: int = TOPUP, rng: Optional[random.Random] = None, used_cores: Sequence[str] = ()) -> Batch:
    """TOPUP more variants, told what the pool already holds, built on the list values it hasn't
    built on yet first (More like these is the same call)."""
    return await write_batch(slot, seeds, n, ask=ask, project_id=project_id, have=have, rng=rng, used_cores=used_cores)


__all__ = ["AGE", "Ask", "Bank", "Batch", "DESCENT", "Drawn", "MIN_POOL", "N_OTHER", "N_PERSON", "GENDER", "Pins",
           "SHORTLIST", "SYSTEM", "Seeds", "Slot", "Spec", "TOPUP", "VARIANTS_VERSION", "article_before", "ask_writer",
           "bank", "check",
           "context_words", "draw_seeds", "has_run", "kept_chunks", "list_seeds", "messages", "minor_line", "minor_words",
           "parse_reply", "person_seeds", "repair", "tokens", "top_up", "valid_category", "write_batch", "write_first"]

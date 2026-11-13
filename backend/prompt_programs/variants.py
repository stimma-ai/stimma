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

VARIANTS_VERSION = "variants-1"
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
                 stated: Optional[Dict[str, Sequence[str]]] = None, minor: Sequence[str] = ()) -> Seeds:
    """A person's seeds. `descent`: the descent values their words allow (narrowed; None when the
    words state none: the whole list). `stated_descent`: their words state it, so a single value
    left needs no seed. `gender`: the genders their words allow (narrowed: "woman" keeps woman and
    trans woman; None when the words state none: the whole list), one per variant by the list's
    shares. `ages`:
    their age narrowed by their words; None while that narrowing isn't there, which seeds no age
    (an unnarrowed age would fight "young" or "elderly"; the writer keeps them adults). `ideas`:
    (list, narrowed or None) per list whose values may seed their look. `stated`: what the prompt
    states of the scene (bank). `minor`: ages under 18 they may be besides their own (a user list
    of ages on their line)."""
    from prompt_programs.vocab import minor_ages
    minor = tuple(dict.fromkeys([*(minor_ages(list(ages)) if ages else ()), *minor]))
    d = bank(DESCENT, descent, minor=bool(minor))
    if d is not None and stated_descent and len(d.values) == 1:
        d = None   # their words name it already
    return Seeds(descent=d, gender=bank(GENDER, gender),
                 age=bank(AGE, ages, minor=bool(minor)) if ages is not None else None, minor=minor,
                 ideas=tuple(b for b in (bank(lid, n, minor=bool(minor), stated=stated) for lid, n in ideas)
                             if b is not None))


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

    def line(self) -> str:
        parts = ([f'"{self.descent}"'] if self.descent else []) + ([f"gender: {self.gender}"] if self.gender else []) \
            + ([f"age: {self.age}"] if self.age else []) + ([f'core: "{self.core}"'] if self.core else [])
        return ", ".join(parts)

    def seeds(self) -> Dict[str, str]:
        return {k: v for k, v in (("descent", self.descent), ("gender", self.gender), ("age", self.age),
                                  ("core", self.core)) if v}


def _weighted(rng: random.Random, pairs: Sequence[Tuple[str, float]]) -> str:
    total = sum(w for _, w in pairs)
    x = rng.random() * total
    for t, w in pairs:
        x -= w
        if x <= 0:
            return t
    return pairs[-1][0]


def _spread(rng: random.Random, b: Bank, n: int) -> List[str]:
    """n values of a list by its weights, each once before any repeats."""
    out: List[str] = []
    while len(out) < n:
        left = list(b.values)
        while left and len(out) < n:
            t = _weighted(rng, left)
            out.append(t)
            left = [x for x in left if x[0] != t]
    return out


def _palette_fill(text: str, rng: random.Random) -> str:
    from prompt_programs.vocab import fill, is_template, vocabulary
    if not is_template(text):
        return text
    pal = vocabulary().get("person.palette")
    roles = rng.choice(pal.values).roles if pal is not None and pal.values else None
    return fill(text, roles)


@dataclass
class Drawn:
    """A batch's seeds: per variant its own, ideas for the batch, short lists shown whole."""
    specs: List[Spec]
    ideas: List[Tuple[str, str]]          # (text, list id)
    short: List[Bank]


def draw_seeds(rng: random.Random, seeds: Seeds, n: int) -> Drawn:
    """Per variant its descent, gender and age (each by its list's weights) and core (each
    value once before any repeats); 1-2 ideas per variant from the long idea lists, no repeats
    in a batch; short idea lists shown whole."""
    cores = _spread(rng, seeds.core, n) if seeds.core is not None else []
    specs: List[Spec] = []
    for i in range(n):
        s = Spec()
        if seeds.descent is not None:
            s.descent = _weighted(rng, seeds.descent.values)
        if seeds.gender is not None:
            s.gender = _weighted(rng, seeds.gender.values)
        if seeds.age is not None:
            s.age = _weighted(rng, seeds.age.values)
        if cores:
            s.core = _palette_fill(cores[i], rng)
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
                ideas.append((_palette_fill(t, rng), b.list_id))
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
- "a cozy ⟦room⟧ with a crackling fireplace" (category "room") -> "reading room lined with built-in bookshelves", never "a cozy reading room with a crackling fireplace" (the words outside the marks are already in the prompt)

Rules:
- Vary only the thing the marked words name. For a single property (a camera angle, a shot size, a lens, a light, a time of day), say only that property: an angle says where the camera is, a shot size says how much of the subject is in frame, a light says only the light. No grain, style, lens, framing, mood or anything else.
- Each variant must read correctly in its place in the prompt.
- Fit the whole prompt: its place, time, medium, framing, number of people, and the notes (lines starting with #). Never move the scene somewhere else.
- Other parts in <angle brackets> vary on their own: don't fill them in, and don't repeat what the rest of the prompt already says.
- Never add a person or an animal the prompt doesn't have, including through framing: no group selfie, group portrait, two-shot or crowd unless the prompt has that many people.
- Light comes only from sources that exist in or reach this place: an indoor room gets lamps, screens, fire or window light, never shade from a tree, dappled leaves, golden-hour sun on a beach or underwater light. With no stated place, ordinary light that could be anywhere.
- Visual and concrete: what it looks like, not mood or story.
- Make the variants clearly different from each other, across the whole range the words allow, including uncommon but real choices. At most 20 words each beyond the kept words.
- A person: each variant shows them visibly differently, with at least two of age, build, hair, face or clothing beyond any descent, unless the prompt already says them (a clothing part elsewhere in the prompt owns the clothes).
- Each variant stands alone: never "another", "also", "again" or a reference to other variants.
- Every person is an adult unless the prompt's own words make them a child or teenager; "a girl" or "a boy" alone is a young adult.
- If a person may be under 18, nothing sexual or adult-coded.

Ideas. You may get ideas drawn at random from vocabulary lists, for breadth and uncommon picks. Use an idea wherever it could be true here, each at most once, adjusting its wording a little if needed; name it in the variant's "idea" field ("" for none). Reject only an idea that contradicts the prompt or the kept words, listing it under "rejected" first, copied exactly.

Per-variant seeds, one line per variant when given:
- a quoted descent: write that exact word or words into the variant, meaning that heritage's look. If the marked words name several people, it applies to one of them.
- gender: who the person is; write them as that, in words that fit their own words and the picture.
- age: about how old the person is; say it in words that fit their words (a number, or "in her forties"). Their own words about age always hold.
- core: build this variant on that value, adding a few words that place it in this prompt. If it can't be true in this prompt, use another value of the same kind and list the core under "rejected".

Reply with JSON only, no other text:
{"rejected": ["..."], "variants": [{"n": 1, "text": "...", "idea": "..."}, ...]}"""


CORE_NOTE = ("The cores are random values of a list, and some won't fit this prompt. A core that would add people (a "
             "two-shot, a group portrait or a group selfie when the prompt has one person), frame a person the prompt "
             "doesn't have, or name another kind of picture than this one (a mirror selfie in a photo that isn't a "
             "selfie) doesn't fit: put it under \"rejected\" and write that variant with another value of the same kind "
             "that fits.")


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

    def keep(self) -> List[str]:
        return kept_chunks(self.words, valid_category(self.words, self.category, self.kind))


def messages(slot: Slot, drawn: Drawn, seeds: Seeds, have: Sequence[str] = ()) -> List[Dict[str, str]]:
    """The writer's request for one batch."""
    n = len(drawn.specs)
    cat = valid_category(slot.words, slot.category, slot.kind)
    keep = kept_chunks(slot.words, cat)
    lines = ["Prompt:", '"""', slot.marked(), '"""', "", f'Marked part: "{slot.words}".']
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


def article_before(prompt: str, span: Tuple[int, int]) -> bool:
    """Whether the slot heads a phrase the prompt starts with an article: one of the last two
    words before it on its line, with no punctuation or other slot between ("a <couple>", "a cozy
    <room>"). Structural: articles are grammar, and nothing else is read."""
    from prompt_programs.slots import SLOT_RE
    a = span[0]
    before = SLOT_RE.split(prompt[prompt.rfind("\n", 0, a) + 1:a])[-1]
    clause = re.split(r"[,;:.!?()\[\]{}]", before)[-1]
    words = clause.lower().split()
    return any(w in _ARTICLES for w in words[-2:])


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
    for k in (len(left), 4, 3, 2):
        lw = list(left[-k:]) if k <= len(left) else []
        if len(lw) >= 2:
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
    for k in keep:
        if not has_run(text, k):
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
                      have: Sequence[str] = (), rng: Optional[random.Random] = None) -> Batch:
    """One writer call for `n` variants, checked. Never raises: a failed call or an unreadable
    reply is a batch with nothing in it and its `error`."""
    import time
    rng = rng or random.Random()
    drawn = draw_seeds(rng, seeds, n)
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
    article = article_before(slot.prompt, slot.span)
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
                 n: int = TOPUP, rng: Optional[random.Random] = None) -> Batch:
    """TOPUP more variants, told what the pool already holds (More like these is the same call)."""
    return await write_batch(slot, seeds, n, ask=ask, project_id=project_id, have=have, rng=rng)


__all__ = ["AGE", "Ask", "Bank", "Batch", "DESCENT", "Drawn", "MIN_POOL", "N_OTHER", "N_PERSON", "GENDER", "Pins",
           "SHORTLIST", "SYSTEM", "Seeds", "Slot", "Spec", "TOPUP", "VARIANTS_VERSION", "article_before", "ask_writer",
           "bank", "check",
           "context_words", "draw_seeds", "has_run", "kept_chunks", "list_seeds", "messages", "minor_line", "minor_words",
           "parse_reply", "person_seeds", "repair", "tokens", "top_up", "valid_category", "write_batch", "write_first"]

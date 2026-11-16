"""The pool check: one model call per written batch says which values don't fit the user's prompt.

    <black pudding> on a plate      ->  "black rice pudding with coconut cream"   (another dish: dropped)
    a fierce warrior queen, <face>  ->  "a bored half-smile"                       (clashes with "fierce": dropped)

A pool's values are written by the variant writer (variants.py) a turn at a time. Code checks
their structure (the kept words as runs, length, repeats); whether a value is still what the
user named, and whether it can be true with what the user wrote, needs a model. The trained pick
judge misses about half of the real broken draws, and most of what it misses depends only on the
user's prompt and one value: a value that keeps the user's words but swaps what they name ("a
gothic museum wine cellar" for a gothic museum hall), or one that contradicts the user's own
fixed text (a straight-haired woman given loose waves). Those are properties of the pool, so they
are checked once per batch when it is written and cached with it, not once per draw.

- What it is told. The prompt with the part marked (⟦like this⟧) and [exact text] still masked
  as its [EXACT_n] tokens (Slot.prompt is the parsed, masked prompt), the part's words, how the
  part varies (the reader's reading, or the user's choice of mode), and the batch's values,
  numbered. It first says what every value must be and what the fixed text states, then per
  value what it shows, what the fixed text says about the same details, and "yes" or "no".
- How the part varies decides what "still the same thing" means:
  one specific thing (Detail on a named thing): every value is that same thing;
  a kind (Detail or Variety on a kind of thing): every value is a member of that kind, its
  category word made more specific at most;
  another member (Variety on a named thing, `kind_of`): every value is another member of the
  kind, so replacing the named thing is what the user asked for, never a reason to drop it.
- The model decides; code never reads the words for it.
- Degrade, don't fail: a call that fails, times out or replies with nothing readable keeps the
  batch as written; a value with no answer is kept.

This module makes the call and reads the reply; it stores nothing (variant_pools.PoolWriter
stores the verdicts with the pool). `ask` is injected: the app's chat model (ask_check) or a fake.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from core.logging import get_logger

log = get_logger(__name__)

CHECK_VERSION = "check-1"   # check-1: one call per written batch; a value that isn't what the part names, or contradicts the user's fixed text, is dropped
CHECK_SECONDS = 60.0        # one check call, at most; past it the batch stands as written
CHECK_TEMPERATURE = 0.0

HEAD = """You check values written for one marked part of an image prompt. A tool makes many images from one prompt: in each image, the marked part (⟦like this⟧) is replaced by one of the values. Everything outside the marks is fixed text the user wrote, kept in every image. Other parts in <angle brackets> vary on their own. Text shown as [EXACT_1] is the user's exact text, hidden from you. Judge only fit with the user's words; never taste, wording, how much detail a value has, or its content. Unusual people, places and details are welcome, and the prompt's own fantasy or style sets what is possible."""

# Both ways a value breaks the prompt in one call, with two short fields per value (what it shows,
# and what the fixed text says about the same details) that make a model answering with reasoning
# off look before it answers. Measured on the real set (stimma-evals fluent_draws/pool_check): as
# good as asking the two ways in two calls side by side, for half the calls.
SYSTEM = HEAD + """

A value breaks what the user asked for in two ways:
1. It is not what the marked part is meant to be (the part says how it varies, below). Read the marked words as the user means them in this prompt, and each value as what a viewer would see. The slip to catch keeps the user's words but changes what they name: the main word swapped for another thing ("civil rights food drive" for "civil rights protest", "gothic museum wine cellar" for "gothic museum hall", "a coaching-inn yard" for "cobblestone alleyway", "a teapot-shaped globe" for "snowglobe"), the user's words turned into a description of something else ("Tenochtitlan cacao pods" for "Tenochtitlan"), or what the user named dropped, made generic, or replaced ("a central Manhattan park" for "Central Park"; "black rice pudding" for "black pudding", which is a blood sausage). A person must still be who the words say, as the prompt means them: an astronaut is dressed as one, ancient Greek philosophers are not modern people, "1girl" is a young woman or girl, a crew is still a crew.
2. It contradicts the fixed text: anything the fixed text (outside the marks) states about this subject or the picture, in sentences or in tags: sex, age, descent, hair color, length and style, eye color, build, expression or mood, clothing, what they hold or do, how many people or things, the framing (close-up, full body), the era, place, season or style ("slim" for someone with big hips, "a bored half-smile" for a fierce warrior, "wavy hair" when the prompt says straight hair, a full-body description in an extreme close-up of one eye, a man where the prompt says a woman, a White man where it says black men, one plant where it says lots of houseplants).

Most values fit. If a casual viewer would still call it what the user wrote, it fits: a more specific kind, a close variant or a near relative of the thing ("a hospital recovery room" for "hospital bedroom", "an Edwardian tea room" for "cafe", "a crescent bay of fine sand" for "tropical beach", "a conservatory" for "greenhouse", "a Switch Lite" for "Nintendo Switch", "a grotto" for "cave"). A value that only adds what the fixed text doesn't state fits. Otherwise, when a viewer would see a different thing than the one named, or the value contradicts something stated, answer "no".

Reply with JSON objects, one per line and nothing else. First one line: {"part": "what every value must be, in a few words", "fixed": "what the fixed text states that a value could contradict, in a few words"}. Then one line per value, in order, each field a few words: {"n": 1, "is": "what the value shows", "against": "what the fixed text says about the same details, or nothing", "fits": "yes"}, or when it doesn't fit, with a reason of at most 12 words: {"n": 2, "is": "...", "against": "...", "fits": "no", "why": "..."}."""


ONE = ('How it varies: this part names one specific thing, "{words}". Every value must be that same thing, shown '
       "one particular way (its state, condition, angle, moment, details or surroundings). Another thing, another one "
       "of its kind, a generic or merely similar thing, or the user's words used to name something else doesn't fit.")
KIND = ('How it varies: every value is one particular "{words}": a member of what those words name, every word of them '
        "still true of it. A more specific kind of it, or one described its own way, fits; a different thing, even one "
        "that keeps some of the words, doesn't.")
KIND_CAT = ('How it varies: every value is one particular "{words}": a member of what those words name, every word of '
            'them still true of it. The word "{cat}" may become a more specific kind of {cat} that is still a {cat} '
            '(and still everything the other words say). A different thing, even one that keeps some of the words, '
            "doesn't.")
OTHERS = ('How it varies: the user chose to vary "{words}": every value is meant to be ANOTHER {kind_of}, not "{words}" '
          'itself. Replacing "{words}" with a different {kind_of} is exactly what the user asked for and fits. '
          'Answer "no" only when a value is not a {kind_of} at all, or contradicts the fixed text.')


@dataclass
class Checked:
    """One batch's verdicts: the values the check drops, with its reasons, and how the call went."""
    asked: int
    dropped: List[str] = field(default_factory=list)
    why: Dict[str, str] = field(default_factory=dict)
    answered: int = 0
    seconds: float = 0.0
    error: str = ""          # the call failed or its reply was unreadable: nothing is dropped

    def to_dict(self) -> Dict[str, Any]:
        return {"version": CHECK_VERSION, "asked": self.asked, "answered": self.answered, "dropped": self.dropped,
                "why": self.why, "seconds": self.seconds, **({"error": self.error} if self.error else {})}


def how_it_varies(slot: Any) -> str:
    """The part's line: how its values may differ from its words (the reader's reading, or the
    user's mode, as the writer was told)."""
    from prompt_programs.variants import valid_category
    words = slot.words
    if slot.kind_of and not slot.one:
        return OTHERS.replace("{words}", words).replace("{kind_of}", slot.kind_of)
    if slot.one:
        return ONE.replace("{words}", words)
    cat = valid_category(words, slot.category, slot.kind)
    if cat and cat.strip().lower() != words.strip().lower():
        return KIND_CAT.replace("{words}", words).replace("{cat}", cat)
    return KIND.replace("{words}", words)


def messages(slot: Any, texts: Sequence[str]) -> List[Dict[str, str]]:
    """The check's request for one batch. Slot.prompt is the masked prompt: [exact text] is its
    [EXACT_n] token here, as it is for the reader and the writer."""
    lines = ["Prompt:", '"""', slot.marked(), '"""', "", f'Marked part: "{slot.words}".', how_it_varies(slot), "",
             "Values:", *(f"{i}. {t}" for i, t in enumerate(texts, 1))]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


_LINE = re.compile(r"\{[^{}]*\}")


def parse(reply: Optional[str], n: int) -> Dict[int, Dict[str, str]]:
    """{index from 1: {"fits": "yes" | "no", "why"}} from a reply; whatever can't be read is left
    out (kept)."""
    out: Dict[int, Dict[str, str]] = {}
    for m in _LINE.finditer(str(reply or "")):
        try:
            obj = json.loads(m.group(0))
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        k, fits = obj.get("n"), str(obj.get("fits") or "").strip().lower()
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= n or k in out or fits not in ("yes", "no"):
            continue
        out[k] = {"fits": fits, "why": str(obj.get("why") or "")[:200]}
    return out


NUDGE = "\n\nReply in JSON lines as described."


async def check(slot: Any, texts: Sequence[str], *, ask: Any, project_id: Optional[int] = None) -> Checked:
    """Check one batch of a pool. Never raises: a call that fails or a reply that can't be read
    drops nothing. A reply with nothing readable is asked once more with the request nudged (a
    local model sometimes answers one exact request with a run of "!!!!"; another token sequence
    doesn't)."""
    texts = [str(t) for t in texts]
    out = Checked(asked=len(texts))
    if not texts:
        return out
    msgs = messages(slot, texts)
    got: Dict[int, Dict[str, str]] = {}
    t0 = time.monotonic()
    for _ in range(2):
        try:
            async with asyncio.timeout(CHECK_SECONDS):
                reply = await ask(msgs, project_id, 70 * len(texts) + 160, temperature=CHECK_TEMPERATURE)
        except Exception as e:   # a model slip or an unreachable model: the batch stands as written
            out.error = f"{type(e).__name__}: {e}"[:200] or "call failed"
            break
        got = parse(reply, len(texts))
        if got:
            break
        out.error = "unreadable reply"
        msgs = [msgs[0], {"role": "user", "content": msgs[1]["content"] + NUDGE}]
    out.seconds = round(time.monotonic() - t0, 2)
    if got:
        out.error = ""
    else:
        log.warning(f"[pool-check] checking {slot.words!r} failed ({out.error}); keeping the batch")
        return out
    out.answered = len(got)
    for i, t in enumerate(texts, 1):
        a = got.get(i)
        if a and a["fits"] == "no":
            out.dropped.append(t)
            if a["why"]:
                out.why[t] = a["why"]
    return out


async def ask_check(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int,
                    temperature: float = CHECK_TEMPERATURE) -> str:
    """One plain completion from the chat model Fluent writes pools with, reasoning off."""
    from prompt_programs.variants import ask_writer
    return await ask_writer(messages, project_id, max_tokens, temperature=temperature)


__all__ = ["CHECK_VERSION", "Checked", "SYSTEM", "ask_check", "check", "how_it_varies", "messages", "parse"]

"""The pool check (prompt_programs/pool_check.py) and how the pool writer keeps its verdicts.

A fake check model answers "no" for every value it is told to drop; nothing here calls a model.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, Dict, List, Optional

from prompt_programs import pool_check as C
from prompt_programs import variant_pools as P
from prompt_programs import variants as V
from prompt_programs.program import mask_exact
from tests.test_prompt_program_variants import PROMPT, FakeWriter, job_for, slot_of


def run(coro):
    return asyncio.run(coro)


class FakeCheck:
    """A check model: "no" for every value containing one of `bad`, "yes" for the rest. `slip`:
    "raise", "prose" or "bang" (a degenerate "!!!!" reply) for every call."""

    def __init__(self, bad: Optional[List[str]] = None, slip: str = ""):
        self.bad = list(bad or [])
        self.slip = slip
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, messages, project_id, max_tokens, temperature=0.0) -> str:
        self.calls.append({"messages": messages, "max_tokens": max_tokens, "temperature": temperature})
        if self.slip == "raise":
            raise RuntimeError("the model is unreachable")
        if self.slip == "prose":
            return "All of these look fine to me!"
        if self.slip == "bang":
            return "!!!!!!!!!!!!!!!!!!!!"
        values = re.findall(r"^\d+\. (.*)$", messages[1]["content"].split("Values:")[1], re.M)
        return "\n".join(json.dumps({"n": i, "fits": "no", "why": "not it"} if any(b in v for b in self.bad)
                                    else {"n": i, "fits": "yes"}) for i, v in enumerate(values, 1))


# --------------------------------------------------------------------------- the call

def test_the_check_says_how_the_part_varies():
    prompt = "a plate of <black pudding> beside <Central Park> and <the Mona Lisa>"
    kind = slot_of(prompt, "free", "pudding", n=1)
    one = V.Slot(**{**slot_of(prompt, n=2).__dict__, "one": True})
    others = V.Slot(**{**slot_of(prompt, n=3).__dict__, "one": False, "kind_of": "famous painting"})
    assert 'The word "pudding" may become a more specific kind of pudding' in C.how_it_varies(kind)
    assert "names one specific thing, \"Central Park\"" in C.how_it_varies(one)
    line = C.how_it_varies(others)
    assert "ANOTHER famous painting" in line and "exactly what the user asked for" in line   # replacing it is intended
    msgs = C.messages(kind, ["black rice pudding", "black pudding sliced thick"])
    assert "⟦black pudding⟧" in msgs[1]["content"] and "1. black rice pudding" in msgs[1]["content"]


def test_values_the_check_answers_no_are_dropped_and_the_rest_kept():
    sl = slot_of("a plate of <black pudding>", "free", "pudding")
    fake = FakeCheck(["rice"])
    got = run(C.check(sl, ["black rice pudding", "black pudding sliced thick", "black pudding, charred"], ask=fake))
    assert got.dropped == ["black rice pudding"] and got.why == {"black rice pudding": "not it"}
    assert got.answered == 3 and not got.error
    assert len(fake.calls) == 1 and fake.calls[0]["temperature"] == 0.0
    assert fake.calls[0]["messages"][0]["content"] == C.SYSTEM
    assert "How it varies" in fake.calls[0]["messages"][1]["content"]


def test_a_degenerate_reply_is_asked_once_more_nudged():
    sl = slot_of("a plate of <black pudding>", "free", "pudding")
    seen = []

    async def ask(messages, project_id, max_tokens, temperature=0.0):
        seen.append(messages[1]["content"])
        if len(seen) == 1:
            return "!!!!!!!!!!!!!!!!"
        return ('{"part": "a blood sausage", "fixed": "on a plate"}\n'
                '{"n": 1, "is": "a rice pudding", "against": "nothing", "fits": "no", "why": "another dish"}\n'
                '{"n": 2, "is": "black pudding", "against": "nothing", "fits": "yes"}')
    got = run(C.check(sl, ["black rice pudding", "black pudding sliced thick"], ask=ask))
    assert got.dropped == ["black rice pudding"] and not got.error
    assert len(seen) == 2 and seen[1] == seen[0] + C.NUDGE


def test_a_failed_or_unreadable_check_keeps_the_batch():
    sl = slot_of("a plate of <black pudding>", "free", "pudding")
    for slip in ("raise", "prose", "bang"):
        got = run(C.check(sl, ["black rice pudding", "black pudding sliced thick"], ask=FakeCheck(["rice"], slip=slip)))
        assert got.dropped == [] and got.error
    # an answer missing for a value keeps it; numbers out of range and other answers are ignored
    assert C.parse('{"n": 1, "fits": "no"}\n{"n": 7, "fits": "no"}\n{"n": 2, "fits": "maybe"}', 2) == \
        {1: {"fits": "no", "why": ""}}


def test_exact_text_never_reaches_the_check():
    masked, exact = mask_exact("[a secret phrase] beside a <red barn> at dusk")
    assert exact and "secret" not in masked
    start = masked.index("<red barn>")
    sl = V.Slot(words="red barn", prompt=masked, span=(start, start + len("<red barn>")), kind="free", category="barn")
    fake = FakeCheck()
    run(C.check(sl, ["weathered red barn"], ask=fake))
    sent = json.dumps(fake.calls)
    assert "secret" not in sent and "[EXACT_1]" in sent


def test_exact_text_never_reaches_the_check_through_a_prepared_prompt(tmp_path, monkeypatch):
    """The slot the pool writer checks is the one fluent.slot_job builds from a prepared entry,
    whose prompt is masked: the user's [exact text] never reaches the check's prompt."""
    from prompt_programs.fluent import slot_job
    masked, _ = mask_exact("[a secret phrase] beside a <red barn> at dusk")
    start = masked.index("<red barn>")
    entry = {"prompt": masked, "seeds": {"s1": {"banks": []}}, "seeds_pending": []}
    slot = {"id": "s1", "words": "red barn", "pool": "e" * 32, "span": [start, start + len("<red barn>")],
            "kind": "free", "category": "barn"}
    job = slot_job(entry, slot, model="fake")
    fake = FakeCheck()

    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter(), check=fake)
        w.attach()
        w.submit(job)
        await w.drain()
    run(go())
    sent = json.dumps(fake.calls)
    assert fake.calls and "secret" not in sent and "[EXACT_1]" in sent


# --------------------------------------------------------------------------- with the pool writer

def written(tmp_path, check, slot=None, writer=None):
    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=writer or FakeWriter(), check=check)
        w.attach()
        job = job_for(slot or slot_of(PROMPT, "list", "lighting", n=3), V.Seeds())
        w.submit(job)
        await w.drain()
        return w, job
    return run(go())


def test_the_writer_checks_each_turn_and_drops_what_the_check_drops(tmp_path):
    fake = FakeCheck(["tall", "lanky"])   # FakeWriter's adjectives: some of each turn's variants
    w, job = written(tmp_path, fake)
    texts = [v["text"] for v in w.store.variants(job.key)]
    assert texts and not any("tall" in t or "lanky" in t for t in texts)
    assert not any(v.get("unchecked") for v in w.store.variants(job.key))
    checks = [b["check"] for b in w.store.batches(job.key) if "check" in b]
    assert len(checks) == len(fake.calls) >= 3 and all(c["version"] == C.CHECK_VERSION for c in checks)
    dropped = [t for c in checks for t in c["dropped"]]
    assert dropped and all(("tall" in t or "lanky" in t) for t in dropped)
    # the session log holds only what the check kept, so a later turn never copies a dropped value
    log = V.Session.of(w.store.session(job.key))
    assert not any(t in log.texts for t in dropped)
    assert not any(t in m["content"] for m in log.messages if m["role"] == "assistant" for t in dropped)
    # the first write still reaches its size past the drops (more turns while under MIN_POOL)
    assert len(texts) >= V.MIN_POOL


def test_a_failing_check_leaves_the_pool_as_written(tmp_path):
    w, job = written(tmp_path, FakeCheck(["tall"], slip="raise"))
    assert len(w.store.variants(job.key)) == 30
    checks = [b["check"] for b in w.store.batches(job.key) if "check" in b]
    assert checks and all(c["error"] and not c["dropped"] for c in checks)
    assert not any(v.get("unchecked") for v in w.store.variants(job.key))


def test_the_check_never_empties_a_pool(tmp_path):
    fake = FakeCheck(["light"])   # every variant of <lighting> keeps "lighting": all dropped
    w, job = written(tmp_path, fake)
    # it asked more turns while the pool was short, then kept what was written rather than nothing
    assert len(fake.calls) > 3
    pool = w.store.variants(job.key)
    assert pool and w.store.variants(job.key, fallback=False) == []
    assert P.pick(pool, {}, P.Choice(), random.Random(1), job.slot.words).source == "variant"


def test_a_batch_waiting_for_its_check_is_drawn_only_when_nothing_checked_is_there(tmp_path):
    store = P.VariantStore(tmp_path)
    key = "d" * 32
    store.append(key, {"batch": 0, "variants": [{"text": "warm lamp light", "seeds": {}}], "checking": True})
    store.append(key, {"batch": 0, "check": {"version": C.CHECK_VERSION, "dropped": []}})
    store.append(key, {"batch": 1, "variants": [{"text": "cold neon light", "seeds": {}}], "checking": True})
    pool = store.variants(key)
    assert [v.get("unchecked", False) for v in pool] == [False, True]
    assert [v["text"] for v in P.drawable(pool, P.Choice())] == ["warm lamp light"]
    only = P.VariantStore(tmp_path / "x")
    only.append(key, {"batch": 0, "variants": [{"text": "cold neon light", "seeds": {}}], "checking": True})
    assert [v["text"] for v in P.drawable(only.variants(key), P.Choice())] == ["cold neon light"]


def test_the_check_keys_every_pool():
    a = P.pool_key("m", "red barn", "a <red barn>", [])
    assert P.POOL_VERSION == "pool-3"
    was = P.CHECK_VERSION
    try:
        P.CHECK_VERSION = "check-0"
        assert P.pool_key("m", "red barn", "a <red barn>", []) != a   # another check writes its own pools
    finally:
        P.CHECK_VERSION = was

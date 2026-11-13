"""The variant writer and its pools (prompt_programs/variants.py, variant_pools.py), with a fake chat model.

The fake writes what it is asked for: N variants, each the kept words with a few words added and
the variant's quoted descent, unless a test makes it slip. Nothing here calls a model.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections import Counter
from typing import Any, Dict, List, Optional

import pytest

from prompt_programs import variant_pools as P
from prompt_programs import variants as V
from prompt_programs.vocab import vocabulary

# --------------------------------------------------------------------------- the fake writer

ADJ = ["freckled", "tall", "lanky", "stocky", "wiry", "pale", "tanned", "curly-haired", "bald", "bearded", "gaunt",
       "broad", "petite", "silver-haired", "auburn", "dimpled", "angular", "round-faced", "sharp-jawed", "slender"]


def parse_request(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    user = messages[-1]["content"]
    n = int(re.search(r"Write (\d+) variants\.", user).group(1))
    words = re.search(r'Marked part: "(.+)"\.', user).group(1)
    keep = re.search(r"Every variant contains exactly(?: these words)?: (.+)\.$", user, re.M)
    chunks = re.findall(r'"([^"]+)"', keep.group(1)) if keep else []
    seeds: Dict[int, str] = {}
    if "Seeds, one line per variant:" in user:
        for m in re.finditer(r"^(\d+)\. (.*)$", user.split("Seeds, one line per variant:")[1], re.M):
            seeds[int(m.group(1))] = m.group(2)
    return {"n": n, "words": words, "chunks": chunks, "seeds": seeds, "user": user,
            "system": messages[0]["content"]}


class FakeWriter:
    """An `ask` that writes valid variants; `slips` decide per call what goes wrong."""

    def __init__(self, slips: Optional[List[str]] = None, prefix: str = ""):
        self.calls: List[Dict[str, Any]] = []
        self.slips = list(slips or [])
        self.prefix = prefix

    async def __call__(self, messages, project_id, max_tokens, temperature=0.8) -> str:
        req = parse_request(messages)
        self.calls.append({**req, "max_tokens": max_tokens, "temperature": temperature})
        slip = self.slips.pop(0) if self.slips else ""
        if slip == "raise":
            raise RuntimeError("the model is unreachable")
        if slip == "prose":
            return "Sure! Here are some variants you might like."
        if slip == "empty":
            return json.dumps({"rejected": [], "variants": []})
        base = " ".join(req["chunks"]) or req["words"]
        out = []
        for i in range(1, req["n"] + 1):
            line = req["seeds"].get(i, "")
            d = re.match(r'"([^"]+)"', line)
            g = re.search(r'gender: "([^"]+)"', line)
            text = (f"{self.prefix}{ADJ[(i + len(self.calls)) % len(ADJ)]} {d.group(1) + ' ' if d else ''}"
                    f"{g.group(1) + ' ' if g else ''}{base} no{i}c{len(self.calls)}")
            if slip == "drop_words":
                text = f"{ADJ[i % len(ADJ)]} thing no{i}"
            out.append({"n": i, "text": text, "idea": ""})
        return json.dumps({"rejected": [], "variants": out})


def run(coro):
    return asyncio.run(coro)


def slot_of(prompt: str, kind: str = "free", category: str = "", n: int = 1) -> V.Slot:
    spans = [m.span() for m in re.finditer(r"<([^<>]+)>", prompt)]
    a, b = spans[n - 1]
    return V.Slot(words=prompt[a + 1:b - 1], prompt=prompt, span=(a, b), kind=kind, category=category)


# --------------------------------------------------------------------------- words

def test_category_is_a_run_of_the_slots_own_words():
    assert V.valid_category("clothing slightly open in the front", "clothing") == "clothing"
    assert V.valid_category("selfie camera angle", "camera angle") == "camera angle"
    assert V.valid_category("lighting", "lighting") == "lighting"
    assert V.valid_category("selfie camera angle", "angle of the camera") == ""   # not a run of its words
    assert V.valid_category("dog", "animal") == ""
    assert V.valid_category("young woman", "woman", "person") == ""               # a person keeps every word
    assert V.valid_category("dog", None) == "" and V.valid_category("dog", "  ") == ""


def test_kept_chunks():
    assert V.kept_chunks("clothing slightly open in the front", "clothing") == ["slightly open in the front"]
    assert V.kept_chunks("selfie camera angle", "camera angle") == ["selfie"]
    assert V.kept_chunks("body type, slim to avg", "body type") == ["slim to avg"]
    assert V.kept_chunks("lighting", "lighting") == []
    assert V.kept_chunks("dominant young woman", "") == ["dominant young woman"]


def test_has_run_is_structural_with_case_punctuation_and_hyphens_aside():
    assert V.has_run("A Slim-to-avg build", "slim to avg")
    assert V.has_run("tall, dominant young woman with a bob", "dominant young woman")
    assert not V.has_run("young dominant woman", "dominant young woman")
    assert not V.has_run("predominant young woman", "dominant young woman")


# --------------------------------------------------------------------------- repair and check

def test_repair_cuts_copied_context_markup_and_a_doubled_article():
    left, right = V.context_words("a kitchen, lit by <lighting>, phone photo", (18, 28))
    assert V.repair("lit by warm lamplight from a bedside lamp", left, right)[0] == "warm lamplight from a bedside lamp"
    prompt = "a cozy <room> with a crackling fireplace"
    left, right = V.context_words(prompt, (7, 13))
    text, did = V.repair("reading room with a crackling fireplace", left, right)
    assert text == "reading room" and "right" in did
    text, did = V.repair("sunlit room <material> walls", left, right)
    assert text == "sunlit room" and "markup" in did
    prompt = "a <couple> on a bench"
    left, right = V.context_words(prompt, (2, 10))
    text, did = V.repair("a young couple holding hands", left, right)
    assert text == "young couple holding hands" and "article" in did
    prompt = "two <women> kissing in a steamy shower"
    left, right = V.context_words(prompt, (4, 11))
    text, did = V.repair("two Somali women", left, right)   # one copied word before the slot
    assert text == "Somali women" and "left" in did


def test_repair_cuts_a_label_and_the_article_of_a_phrase_the_slot_heads():
    text, did = V.repair("dominant young woman: a tall Welsh woman", [], [], words="dominant young woman")
    assert text == "a tall Welsh woman" and did == ["label"]
    assert V.check(text, "dominant young woman", ["dominant young woman"], V.Spec()) == "words not kept"
    prompt = "a cozy <room> with a crackling fireplace"
    assert V.article_before(prompt, (7, 13))
    assert V.article_before("taking a low quality cell phone <type of selfie>", (32, 48), "type of selfie")
    assert V.article_before("in her <outfit>", (7, 15), "outfit")
    assert not V.article_before("in her <a dress>", (7, 16), "a dress")   # the slot's words bring their own
    assert V.article_before("a man with <hat>", (11, 16), "hat")          # telegraphic, never "phone a selfie"
    assert not V.article_before("a kitchen, lit by <light>", (18, 25))
    left, right = V.context_words(prompt, (7, 13))
    assert V.repair("a living room with rugs", left, right, article=True)[0] == "living room with rugs"
    assert V.repair("a fedora", ["a", "man", "with"], [], article=False)[0] == "a fedora"


def test_check():
    spec = V.Spec(descent="Korean")
    keep = ["dominant young woman"]
    w = "dominant young woman"
    assert V.check("Korean dominant young woman with a bob", w, keep, spec) == ""
    assert V.check("Korean young woman with a bob", w, keep, spec) == "words not kept"
    assert V.check("dominant young woman with a bob", w, keep, spec) == "descent missing"
    assert V.check("Korean dominant young woman " + "very " * 31, w, keep, spec) == "too long"
    assert V.check("Dominant young woman", w, keep, V.Spec()) == "adds nothing"
    assert V.check("dominant young woman {red}", w, keep, V.Spec()) == "markup in text"
    assert V.check("", w, keep, V.Spec()) == "empty"
    # with a category the rest is kept, the category word may go
    assert V.check("a white cardigan slightly open in the front", "clothing slightly open in the front",
                   ["slightly open in the front"], V.Spec()) == ""


# --------------------------------------------------------------------------- seeds

def test_descent_is_drawn_from_the_lists_distribution_and_never_echoed_whole():
    seeds = V.person_seeds()
    leaf = vocabulary().get(V.DESCENT)
    assert seeds.descent is not None and len(seeds.descent.values) == len(leaf.values)
    rng = random.Random(7)
    counts: Counter = Counter()
    for _ in range(500):
        counts.update(s.descent for s in V.draw_seeds(rng, seeds, 40).specs)
    total = sum(counts.values())
    weights = dict(seeds.descent.values)
    wsum = sum(weights.values())
    tv = 0.5 * sum(abs(counts[t] / total - w / wsum) for t, w in weights.items())
    assert tv < 0.04   # 20,000 draws over 105 values: chance alone gives about 0.03
    # the writer sees one descent per variant, not the list
    msg = V.messages(slot_of("a <person> in a kitchen", "person"), V.draw_seeds(random.Random(1), seeds, 10), seeds)
    shown = [v.text for v in leaf.values if f'"{v.text}"' in msg[1]["content"]]
    assert len(shown) <= 10


def test_gender_is_drawn_by_its_shares_and_narrowed_by_the_words():
    leaf = vocabulary().get(V.GENDER)
    assert [v.text for v in leaf.values] == ["woman", "man", "trans woman", "trans man", "non-binary person"]
    assert not leaf.listed   # never a slot's list
    n = 20000
    got = Counter(s.gender for s in V.draw_seeds(random.Random(3), V.person_seeds(), n).specs)
    assert set(got) == set(v.text for v in leaf.values)
    assert abs(got["woman"] / n - 0.46) < 0.015 and abs(got["man"] / n - 0.46) < 0.015
    for t in ("trans woman", "trans man", "non-binary person"):
        assert 0.015 < got[t] / n < 0.04
    # "woman" narrowed to woman and trans woman: drawn by their relative shares
    got = Counter(s.gender for s in V.draw_seeds(random.Random(3), V.person_seeds(gender=["woman", "trans woman"]), n).specs)
    assert set(got) == {"woman", "trans woman"} and abs(got["trans woman"] / n - 0.027 / 0.487) < 0.01
    # the writer is told it per variant
    s = V.person_seeds(gender=["non-binary person"])
    msg = V.messages(slot_of("a <person> in a kitchen", "person"), V.draw_seeds(random.Random(1), s, 3), s)[1]["content"]
    assert 'gender: "non-binary"' in msg


def test_a_stated_single_descent_needs_no_seed_but_a_narrowed_one_does():
    assert V.person_seeds(descent=["Korean"], stated_descent=True).descent is None
    s = V.person_seeds(descent=["Nigerian", "Ghanaian", "Kenyan"], stated_descent=True)
    assert set(s.descent.texts()) == {"Nigerian", "Ghanaian", "Kenyan"}


def test_no_age_under_18_is_seeded_unasked():
    adults = [v.text for v in vocabulary().get(V.AGE).values if not v.opt_in]   # "person" narrowed: every adult
    seeds = V.person_seeds(ages=adults)
    assert seeds.minor == ()
    ages = {s.age for s in V.draw_seeds(random.Random(5), seeds, 4000).specs}
    young = {v.text for v in vocabulary().get(V.AGE).values if v.minor}
    assert ages and not ages & young
    # before the age narrowing lands, no age is seeded at all (an unnarrowed one would fight "young")
    assert V.person_seeds().age is None
    assert {s.age for s in V.draw_seeds(random.Random(5), V.person_seeds(), 50).specs} == {""}


def test_a_person_who_may_be_a_minor_gets_no_adult_only_seed_and_the_writer_is_told():
    makeup = vocabulary().get("person.makeup")
    adult = {v.text for v in makeup.values if v.adult_only}
    assert adult
    seeds = V.person_seeds(ages=["8-year-old", "9-year-old", "10-year-old"], ideas=[("person.makeup", None)])
    assert seeds.minor == ("8-year-old", "9-year-old", "10-year-old")
    assert not set(seeds.ideas[0].texts()) & adult
    assert seeds.age is None   # their words state their age ("little girl"): no number beside them
    msg = V.messages(slot_of("a <little girl> at the beach", "person"), V.draw_seeds(random.Random(1), seeds, 5), seeds)
    assert "under 18 (8, 9 or 10 years old)" in msg[1]["content"]
    # an adult keeps every value; the rule about who is an adult is always said
    adult_seeds = V.person_seeds(ideas=[("person.makeup", None)])
    assert adult <= set(adult_seeds.ideas[0].texts())
    assert '"a girl" or "a boy" alone is a young adult' in V.SYSTEM
    # a list slot about a child: the same
    child_list = V.list_seeds([("person.makeup", None)], minor=("9-year-old",))
    assert not set(child_list.ideas[0].texts()) & adult


def test_values_held_for_a_setting_are_no_seeds_unless_the_prompt_states_it():
    leaf = vocabulary().get("lighting.natural")
    outdoor_only = {v.text for v in leaf.values if "space" in leaf.needs(v.text)}
    assert outdoor_only
    held = V.bank("lighting.natural")
    assert held is not None and not set(held.texts()) & outdoor_only
    stated = V.bank("lighting.natural", stated={"space": ["outdoor"]})
    assert set(stated.texts()) & outdoor_only
    # the slot's words picking them out (a smaller narrowing) ask for them
    asked = V.bank("lighting.natural", ["overcast daylight", "soft natural light"])
    assert "overcast daylight" in asked.texts()


def test_opt_in_values_are_seeds_only_when_narrowing_asks():
    leaf = vocabulary().get("camera.selfie")   # framings for more than one person are opt-in
    opt = [v.text for v in leaf.values if v.opt_in]
    assert "a group selfie" in opt
    assert not set(V.bank(leaf.id).texts()) & set(opt)
    assert not {s.core for s in V.draw_seeds(random.Random(1), V.list_seeds([(leaf.id, None)], single=True), 90).specs} & set(opt)
    assert opt[0] in V.bank(leaf.id, [opt[0]]).texts()


def test_an_empty_narrowing_drops_the_bank_never_the_slot():
    assert V.bank("camera.angle", []) is None
    s = V.list_seeds([("camera.angle", [])], single=True)
    assert s.core is None and s.ideas == ()
    # and the writer still writes for it
    fake = FakeWriter()
    b = run(V.write_batch(slot_of("<selfie camera angle>, phone photo", "list", "camera angle"), s, 5, ask=fake))
    assert len(b.variants) == 5


def test_a_single_list_gives_each_variant_a_core_each_value_once_before_repeats():
    s = V.list_seeds([("camera.angle", None)], single=True)
    assert s.core is not None and s.ideas == ()
    n = len(s.core.values)
    cores = [x.core for x in V.draw_seeds(random.Random(2), s, n + 3).specs]
    assert len(set(cores[:n])) == n
    msg = V.messages(slot_of("<camera angle>, studio photo", "list", "camera angle"),
                     V.draw_seeds(random.Random(2), s, 5), s)[1]["content"]
    assert 'core: "' in msg and "The cores are random values" in msg
    # a short list (the selfie list without its opt-in framings) is shown whole: cores would repeat
    short = V.list_seeds([("camera.selfie", None)], single=True)
    assert short.core is None and [b.list_id for b in short.ideas] == ["camera.selfie"]
    d = V.draw_seeds(random.Random(2), short, 30)
    assert [b.list_id for b in d.short] == ["camera.selfie"] and not any(x.core for x in d.specs)
    # several lists: ideas
    multi = V.list_seeds([("camera.angle", None), ("camera.lens", None)])
    assert multi.core is None and len(multi.ideas) == 2


def test_short_lists_are_shown_whole_long_ones_as_ideas():
    s = V.list_seeds([("person.gender", None), ("person.hairstyle", None)])
    d = V.draw_seeds(random.Random(4), s, 20)
    assert [b.list_id for b in d.short] == ["person.gender"]
    assert d.ideas and all(lid == "person.hairstyle" for _, lid in d.ideas)
    msg = V.messages(slot_of("a <hairdo>, portrait"), d, s)[1]["content"]
    assert '"woman"; "man"; "trans woman"; "trans man"; "non-binary person"' in msg and "Ideas (random" in msg


def test_pins_restrict_descent_within_what_the_words_allow():
    pins = V.Pins(regions=("East Asia",))
    east = set(pins.descents())
    assert "Korean" in east and "Nigerian" not in east
    s = V.person_seeds().pinned(pins)
    assert set(s.descent.texts()) == east
    s = V.person_seeds().pinned(V.Pins(descent=("Korean",), gender=("trans man",)))
    assert s.descent.texts() == ["Korean"] and s.gender.texts() == ["trans man"]
    # a picked gender the words don't allow still holds (the user chose it)
    assert V.person_seeds(gender=["woman", "trans woman"]).pinned(V.Pins(gender=("man",))).gender.texts() == ["man"]
    # the words say African; a pick outside them still holds (the user chose it)
    words = V.person_seeds(descent=["Nigerian", "Ghanaian"], stated_descent=True)
    assert words.pinned(V.Pins(descent=("Ghanaian",))).descent.texts() == ["Ghanaian"]
    assert words.pinned(V.Pins(descent=("Korean",))).descent.texts() == ["Korean"]


# --------------------------------------------------------------------------- the writer

PROMPT = "# phone photo, her own living room\n<dominant young woman> standing in her living room in <clothing slightly open in the front>, lit by <lighting>"


def test_the_writer_sees_the_whole_prompt_marked_with_its_notes_and_reasoning_off_json():
    fake = FakeWriter()
    sl = slot_of(PROMPT, "list", "clothing", n=2)
    b = run(V.write_batch(sl, V.Seeds(), 30, ask=fake))
    req = fake.calls[0]
    assert "⟦clothing slightly open in the front⟧" in req["user"] and "# phone photo" in req["user"]
    assert "<dominant young woman>" in req["user"]
    assert 'Category word: "clothing"' in req["user"] and req["chunks"] == ["slightly open in the front"]
    assert "Reply with JSON only" in req["system"] and req["max_tokens"] == V.WRITE_TOKENS
    assert len(b.variants) == 30 and not b.error


def test_a_person_gets_40_and_its_descent_checked():
    fake = FakeWriter()
    sl = slot_of(PROMPT, "person")
    adults = [v.text for v in vocabulary().get(V.AGE).values if not v.opt_in]   # words that leave age open
    batches = run(V.write_first(sl, V.person_seeds(ages=adults), ask=fake, key="k" * 32))
    assert len(fake.calls) == 1 and fake.calls[0]["n"] == V.N_PERSON
    vs = batches[0].variants
    assert len(vs) == 40
    assert all(V.has_run(v["text"], v["seeds"]["descent"]) and V.has_run(v["text"], "dominant young woman") for v in vs)
    assert all(v["seeds"].get("gender") and v["seeds"]["age"] in adults for v in vs)
    # words that state an age ("young") carry it: no age seed beside them
    assert V.person_seeds(ages=[f"{a}-year-old" for a in range(18, 30)]).age is None


def test_a_slip_degrades_never_raises():
    sl = slot_of(PROMPT, "list", "lighting", n=3)
    for slip in ("raise", "prose", "empty"):
        b = run(V.write_batch(sl, V.Seeds(), 10, ask=FakeWriter([slip])))
        assert b.variants == []
    assert run(V.write_batch(sl, V.Seeds(), 10, ask=FakeWriter(["raise"]))).error
    person = run(V.write_batch(slot_of(PROMPT, "person"), V.person_seeds(), 10, ask=FakeWriter(["drop_words"])))
    assert person.variants == [] and sum(person.dropped.values()) == 10
    assert set(person.dropped) <= {"words not kept", "gender missing"}


def test_a_write_that_times_out_degrades(monkeypatch):
    monkeypatch.setattr(V, "WRITE_SECONDS", 0.05)

    async def slow(*a, **k):
        await asyncio.sleep(1)
        return "{}"
    b = run(V.write_batch(slot_of(PROMPT, "person"), V.person_seeds(), 5, ask=slow))
    assert b.variants == [] and "Timeout" in b.error


def test_under_min_pool_asks_once_more_then_stands_as_written():
    sl = slot_of(PROMPT, "person")
    fake = FakeWriter(["empty"])
    batches = run(V.write_first(sl, V.person_seeds(), ask=fake))
    assert len(fake.calls) == 2 and sum(len(b.variants) for b in batches) == 40
    fake = FakeWriter(["raise", "prose"])
    batches = run(V.write_first(sl, V.person_seeds(), ask=fake))
    assert len(batches) == 2 and not any(b.variants for b in batches)


def test_duplicates_and_what_the_pool_has_are_dropped():
    class Same(FakeWriter):
        async def __call__(self, messages, project_id, max_tokens, temperature=0.8):
            req = parse_request(messages)
            return json.dumps({"variants": [{"n": i, "text": "warm lamplight"} for i in range(1, req["n"] + 1)]})
    sl = slot_of(PROMPT, "list", "lighting", n=3)
    b = run(V.write_batch(sl, V.Seeds(), 5, ask=Same()))
    assert b.texts() == ["warm lamplight"] and b.dropped["duplicate"] == 4
    b = run(V.top_up(sl, V.Seeds(), ["Warm lamplight"], ask=Same(), n=3))
    assert b.variants == [] and b.dropped["duplicate"] == 3


def test_a_top_up_is_told_what_the_pool_holds():
    fake = FakeWriter()
    sl = slot_of(PROMPT, "list", "lighting", n=3)
    have = [f"lamp {i}" for i in range(100)]
    run(V.top_up(sl, V.Seeds(), have, ask=fake))
    user = fake.calls[0]["user"]
    assert fake.calls[0]["n"] == V.TOPUP and "Already written" in user and "- lamp 99" in user and "- lamp 19\n" not in user


# --------------------------------------------------------------------------- pools: keys and the store

def test_pool_key_is_the_slots_words_line_and_notes_only():
    k = P.pool_key("m", "young woman", "a ⟨young woman⟩ in a kitchen", ["# a note"])
    assert k == P.pool_key("m", "young woman", "a ⟨young woman⟩ in a kitchen", ["# a note"])
    assert k != P.pool_key("m", "young woman", "a ⟨young woman⟩ in a garden", ["# a note"])
    assert k != P.pool_key("m", "young woman", "a ⟨young woman⟩ in a kitchen", [])
    assert k != P.pool_key("other", "young woman", "a ⟨young woman⟩ in a kitchen", ["# a note"])
    assert k != P.pool_key("m", "young woman", "a ⟨young woman⟩ in a kitchen", ["# a note"], minor=["9-year-old"])
    assert len(k) == 32


def test_store_appends_dedupes_and_counts(tmp_path):
    s = P.VariantStore(tmp_path)
    key = "a" * 32
    assert s.variants(key) == [] and not s.has(key)
    s.append(key, {"batch": 0, "variants": [{"text": "warm lamplight", "seeds": {"core": "lamp"}}, {"text": "neon"}]})
    s.append(key, {"batch": 1, "variants": [{"text": "Warm  lamplight"}, {"text": "candles"}]})
    assert [v["text"] for v in s.variants(key)] == ["warm lamplight", "neon", "candles"]
    assert s.variants(key)[0]["seeds"] == {"core": "lamp"}
    s.mark_used(key, ["Warm lamplight", "neon"])
    assert s.mark_used(key, ["warm lamplight"]) == {"warm lamplight": 2, "neon": 1}
    with pytest.raises(ValueError):
        s.append("../escape", {})


# --------------------------------------------------------------------------- drawing

POOL = [{"text": f"variant {i}", "seeds": {"descent": d, "gender": g}}
        for i, (d, g) in enumerate([("Korean", "woman"), ("Nigerian", "man"), ("Polish", "woman"),
                                    ("Japanese", "non-binary person"), ("Peruvian", "man")])]


def test_least_used_draws_use_the_pool_before_repeating():
    uses: Dict[str, int] = {}
    rng = random.Random(1)
    got = []
    for _ in range(10):
        p = P.pick(POOL, uses, P.Choice(), rng, "young woman")
        uses[p.text.lower()] = uses.get(p.text.lower(), 0) + 1
        got.append(p.text)
    assert len(set(got[:5])) == 5 and Counter(got) == Counter({v["text"]: 2 for v in POOL})
    # the same seed and counts draw the same
    assert P.pick(POOL, {}, P.Choice(), random.Random(9), "w").text == P.pick(POOL, {}, P.Choice(), random.Random(9), "w").text


def test_a_slot_with_no_pool_goes_in_as_its_own_words_never_dropped():
    for pool in ([], None):
        p = P.pick(pool or [], {}, P.Choice(), random.Random(), "cozy room")
        assert p.text == "cozy room" and p.source == "words" and not p.counted


def test_choices_off_as_written_fixed_and_pinned():
    rng = random.Random()
    assert P.pick(POOL, {}, P.Choice(off=True), rng, "w").text is None
    assert P.pick(POOL, {}, P.Choice(as_written=True), rng, "w").text == "w"
    assert P.pick(POOL, {}, P.Choice(), rng, "w", fixed="kept text").text == "kept text"
    p = P.pick(POOL, {}, P.Choice(values=("variant 3",)), rng, "w")
    assert (p.text, p.source, p.seeds["descent"]) == ("variant 3", "pinned", "Japanese")
    # a pinned text the pool no longer has still holds (Keep from this after a rewrite)
    assert P.pick(POOL, {}, P.Choice(values=("an old draw",)), rng, "w").text == "an old draw"
    # several pinned: least-used among them
    uses = {"variant 1": 3}
    assert P.pick(POOL, uses, P.Choice(values=("variant 1", "variant 2")), rng, "w").text == "variant 2"


def test_the_users_own_variants_draw_with_the_pool():
    c = P.Choice(add=("my own take",))
    uses = {v["text"]: 1 for v in POOL}
    p = P.pick(POOL, uses, c, random.Random(), "w")
    assert (p.text, p.source) == ("my own take", "own")


def test_picked_seeds_filter_the_pool():
    rng = random.Random(2)
    c = P.Choice(pins=V.Pins(regions=("East Asia",)))
    assert {P.pick(POOL, {}, c, rng, "w").seeds["descent"] for _ in range(30)} == {"Korean", "Japanese"}
    c = P.Choice(pins=V.Pins(gender=("man",)))
    assert {P.pick(POOL, {}, c, rng, "w").text for _ in range(30)} == {"variant 1", "variant 4"}
    # nothing matching yet: the words, with a single picked descent before them
    p = P.pick(POOL, {}, P.Choice(pins=V.Pins(descent=("Welsh",))), rng, "young woman")
    assert (p.text, p.source) == ("Welsh young woman", "words")
    assert P.pick(POOL, {}, P.Choice(pins=V.Pins(regions=("Oceania",))), rng, "young woman").text == "young woman"


def test_choice_wire_form():
    c = P.Choice.of({"values": ["a"], "seeds": {"descent": {"values": ["Korean"], "groups": {"region": ["Europe"]}},
                                                 "gender": {"values": ["trans woman"]}}, "add": ["x"]}, add=["y"])
    assert c.values == ("a",) and c.add == ("x", "y")
    assert c.pins == V.Pins(descent=("Korean",), regions=("Europe",), gender=("trans woman",))
    assert c.to_dict()["seeds"]["gender"] == {"values": ["trans woman"]}
    assert c.to_dict()["seeds"]["descent"] == {"values": ["Korean"], "groups": {"region": ["Europe"]}}
    assert P.Choice.of({"off": True}).to_dict() == {"off": True}
    assert P.Choice.of({"as_written": True}).as_written
    assert P.Choice.of({}).to_dict() is None and P.Choice.of({"any": True}).to_dict() is None
    assert P.Choice.of("junk") == P.Choice()


def test_a_top_up_is_due_at_80_percent_of_a_round():
    pool = [{"text": f"v{i}", "seeds": {}} for i in range(10)]
    assert not P.due(pool, {f"v{i}": 1 for i in range(7)}, P.Choice())
    assert P.due(pool, {f"v{i}": 1 for i in range(8)}, P.Choice())
    assert not P.due(pool, {f"v{i}": 1 for i in range(10)}, P.Choice())          # a new round begins
    assert P.due(pool, {**{f"v{i}": 2 for i in range(8)}, "v8": 1, "v9": 1}, P.Choice())
    assert not P.due(pool, {f"v{i}": 1 for i in range(9)}, P.Choice(values=("v1",)))
    assert P.due(POOL, {}, P.Choice(pins=V.Pins(descent=("Welsh",))))            # picked seeds match nothing yet
    assert P.due(POOL, {}, P.Choice(pins=V.Pins(descent=("Korean",))))           # one match: it would repeat
    many = [{"text": f"k{i}", "seeds": {"descent": "Korean"}} for i in range(P.MIN_MATCH)]
    assert not P.due(many, {}, P.Choice(pins=V.Pins(descent=("Korean",))))     # enough to vary
    big = [{"text": f"v{i}", "seeds": {}} for i in range(P.MAX_POOL)]
    assert not P.due(big, {f"v{i}": 1 for i in range(P.MAX_POOL - 1)}, P.Choice())


def test_person_pickers():
    got = P.person_pickers(POOL, P.Choice(pins=V.Pins(regions=("East Asia",))), fits=["Korean", "Japanese"])
    d = got["descent"]
    assert d["browse"] == "region" and d["parts"][0]["id"] == "East Asia" and "Korean" in d["parts"][0]["values"]
    assert sum(len(p["values"]) for p in d["parts"]) == len(vocabulary().get(V.DESCENT).values)
    assert d["fits"] == ["Korean", "Japanese"] and d["picked"]["groups"]["region"] == ["East Asia"]
    assert d["in_pool"]["Korean"] == 1
    g = got["gender"]
    assert g["label"] == "Gender" and g["options"] == ["woman", "man", "trans woman", "trans man", "non-binary person"]
    assert g["in_pool"] == {"woman": 2, "man": 2, "non-binary person": 1} and g["fits"] == g["options"]
    assert P.person_pickers(POOL, P.Choice(), gender_fits=["woman", "trans woman"])["gender"]["fits"] == ["woman", "trans woman"]


# --------------------------------------------------------------------------- writing in the background

def job_for(sl: V.Slot, seeds: V.Seeds, key: str = "b" * 32, **kw) -> P.Job:
    return P.Job(key=key, slot=sl, seeds=seeds, model="fake", **kw)


def test_the_first_pool_is_written_in_the_background_and_stored(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        job = job_for(slot_of(PROMPT, "person"), V.person_seeds())
        assert w.state(job.key) == "writing"
        assert w.submit(job) and not w.submit(job_for(job.slot, job.seeds))   # one write per pool
        assert w.busy(job.key)
        await w.drain()
        assert w.state(job.key) == "ready" and len(w.store.variants(job.key)) == 40
        rec = w.store.batches(job.key)[0]
        assert rec["role"] == "first" and rec["keep"] == ["dominant young woman"] and rec["model"] == "fake"
        assert not w.submit(job_for(job.slot, job.seeds))   # written already
        return fake
    assert len(run(go()).calls) == 1


def test_a_failed_first_write_is_not_stored_and_asked_again(tmp_path):
    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter(["raise", "prose"]))
        w.attach()
        job = job_for(slot_of(PROMPT, "person"), V.person_seeds())
        w.submit(job)
        await w.drain()
        assert w.state(job.key) == "as_written" and w.failed(job.key) and not w.store.has(job.key)
        assert P.pick(w.store.variants(job.key), {}, P.Choice(), random.Random(), job.slot.words).text == job.slot.words
        assert not w.submit(job_for(job.slot, job.seeds))   # not again at once (a picker polling)
        assert w.submit(job_for(job.slot, job.seeds), retry=True)   # an explicit retry asks again
        await w.drain()
        assert w.state(job.key) == "ready" and w.failed(job.key) is None
    run(go())


def test_jobs_queued_before_a_loop_start_on_attach_and_submit_works_from_a_thread(tmp_path):
    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter())
        job = job_for(slot_of(PROMPT, "list", "lighting", n=3), V.Seeds())
        assert w.submit(job) and w.busy(job.key)
        w.attach()
        await w.drain()
        assert w.store.has(job.key)
        other = job_for(slot_of(PROMPT, "list", "clothing", n=2), V.Seeds(), key="c" * 32)
        await asyncio.to_thread(w.submit, other)
        await asyncio.sleep(0.05)
        await w.drain()
        assert w.store.has(other.key)
    run(go())


def test_draws_count_and_top_up_at_80_percent(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        sl = slot_of(PROMPT, "list", "lighting", n=3)
        job = job_for(sl, V.Seeds())
        w.submit(job)
        await w.drain()
        assert len(w.store.variants(job.key)) == 30
        rng = random.Random(3)
        queued_at = None
        for t in range(30):
            pool = w.store.variants(job.key)
            p = P.pick(pool, w.store.uses(job.key), P.Choice(), rng, sl.words)
            if w.drew(job_for(sl, V.Seeds()), p, pool) and queued_at is None:
                queued_at = t + 1
        await w.drain()
        assert queued_at == 24   # 80% of 30
        assert len(w.store.variants(job.key)) == 50
        assert w.store.batches(job.key)[-1]["role"] == "top_up"
        assert "Already written" in fake.calls[-1]["user"]
        # the slot's own words count nothing; a held draw (the judge holds what it doesn't reroll) counts
        before = w.store.uses(job.key)
        w.drew(job_for(sl, V.Seeds()), P.Pick(sl.words, "words"))
        assert w.store.uses(job.key) == before
        held = w.store.variants(job.key)[0]["text"]
        w.drew(job_for(sl, V.Seeds()), P.Pick(held, "fixed"))
        assert w.store.uses(job.key)[held.lower()] == before.get(held.lower(), 0) + 1
    run(go())


def test_picked_seeds_with_nothing_matching_write_a_pinned_batch(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake, paused=lambda: True)   # a pinned batch doesn't wait
        w.attach()
        sl = slot_of(PROMPT, "person")
        w.store.append("d" * 32, {"batch": 0, "variants": POOL})
        choice = P.Choice(pins=V.Pins(descent=("Welsh",)))
        p = P.pick(w.store.variants("d" * 32), {}, choice, random.Random(), sl.words)
        assert p.text == "Welsh dominant young woman"
        assert w.drew(job_for(sl, V.person_seeds(), key="d" * 32), p, choice=choice)
        await asyncio.wait_for(w.drain(), 5)
        rec = w.store.batches("d" * 32)[-1]
        assert rec["pinned"] == {"descent": ["Welsh"]} and all(v["seeds"]["descent"] == "Welsh" for v in rec["variants"])
        assert P.pick(w.store.variants("d" * 32), {}, choice, random.Random(), sl.words).source == "variant"
    run(go())


def test_a_background_top_up_gives_way_to_reading(tmp_path):
    async def go():
        reading = {"on": True}
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter(), paused=lambda: reading["on"])
        w.attach()
        sl = slot_of(PROMPT, "list", "lighting", n=3)
        w.store.append("e" * 32, {"batch": 0, "variants": [{"text": "lamp"}]})
        w.submit(job_for(sl, V.Seeds(), key="e" * 32, role="top_up"))
        await asyncio.sleep(0.6)
        assert len(w.store.variants("e" * 32)) == 1 and w.busy("e" * 32)
        reading["on"] = False
        await asyncio.wait_for(w.drain(), 5)
        assert len(w.store.variants("e" * 32)) == 21
    run(go())


def test_more_like_these_is_the_same_call_awaited(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        sl = slot_of(PROMPT, "list", "lighting", n=3)
        job = job_for(sl, V.Seeds())
        w.submit(job)
        new = await w.more(job_for(sl, V.Seeds()))   # waits for the first write, then writes 20 more
        assert len(new) == 20 and len(w.store.variants(job.key)) == 50
        assert w.store.batches(job.key)[-1]["role"] == "more"
        assert fake.calls[-1]["n"] == V.TOPUP
        failing = P.PoolWriter(P.VariantStore(tmp_path / "x"), ask=FakeWriter(["raise"]))
        failing.attach()
        assert await failing.more(job_for(sl, V.Seeds())) == []
    run(go())


def test_a_full_pool_stops_topping_up(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        w.store.append("f" * 32, {"batch": 0, "variants": [{"text": f"v{i}"} for i in range(P.MAX_POOL)]})
        assert await w.run(job_for(slot_of(PROMPT, "list", "lighting", n=3), V.Seeds(), key="f" * 32, role="top_up")) == []
        assert fake.calls == []
    run(go())


def test_an_idea_that_only_repeats_the_core_is_not_recorded():
    class Echo(FakeWriter):
        async def __call__(self, messages, project_id, max_tokens, temperature=0.8):
            req = parse_request(messages)
            out = []
            for i in range(1, req["n"] + 1):
                core = re.search(r'core: "([^"]+)"', req["seeds"][i]).group(1)
                out.append({"n": i, "text": f"{core}, from below no{i}", "idea": core})
            return json.dumps({"variants": out})
    s = V.list_seeds([("camera.angle", None)], single=True)
    b = run(V.write_batch(slot_of("<camera angle>, studio photo", "list", "camera angle"), s, 5, ask=Echo()))
    assert len(b.variants) == 5 and all("idea" not in v["seeds"] and v["seeds"]["core"] for v in b.variants)


def test_a_pick_nothing_matches_writes_a_pinned_batch_at_once(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake, paused=lambda: True)   # high priority: no waiting
        w.attach()
        sl = slot_of(PROMPT, "person")
        key = "9" * 32
        assert not w.picked(job_for(sl, V.person_seeds(), key=key), P.Choice(pins=V.Pins(descent=("Welsh",))))  # no pool yet
        w.store.append(key, {"batch": 0, "variants": POOL})
        assert not w.picked(job_for(sl, V.person_seeds(), key=key), P.Choice())                                 # nothing picked
        assert w.picked(job_for(sl, V.person_seeds(), key=key), P.Choice(pins=V.Pins(descent=("Korean",))))  # 1 < MIN_MATCH
        await asyncio.wait_for(w.drain(), 5)
        assert len([v for v in w.store.variants(key) if v["seeds"].get("descent") == "Korean"]) >= P.MIN_MATCH
        assert not w.picked(job_for(sl, V.person_seeds(), key=key), P.Choice(pins=V.Pins(descent=("Korean",))))  # enough now
        choice = P.Choice(pins=V.Pins(descent=("Welsh",), gender=("trans woman",)))
        assert w.picked(job_for(sl, V.person_seeds(), key=key), choice)
        await asyncio.wait_for(w.drain(), 5)
        rec = w.store.batches(key)[-1]
        assert rec["pinned"] == {"descent": ["Welsh"], "gender": ["trans woman"]}
        assert all(v["seeds"]["descent"] == "Welsh" and v["seeds"]["gender"] == "trans woman" for v in rec["variants"])
    run(go())


def test_the_writer_is_shown_the_words_around_the_slot():
    sl = slot_of("taking a low quality cell phone <type of selfie>, slim to avg", "list", "type of selfie")
    assert sl.around() == ("taking a low quality cell phone", ", slim to avg")
    assert slot_of("a <couple> on a bench").around() == ("a", "on a bench")
    msg = V.messages(sl, V.draw_seeds(random.Random(1), V.Seeds(), 3), V.Seeds())
    assert 'It stands between "taking a low quality cell phone" and ", slim to avg"' in msg[1]["content"]
    assert "no article or determiner of its own" in msg[0]["content"]
    assert slot_of("<lighting>").around() == ("(start of line)", "(end of line)")


def test_a_top_up_fills_only_the_room_left_and_more_may_pass_the_cap_by_one_batch(tmp_path):
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        sl = slot_of(PROMPT, "list", "lighting", n=3)
        w.store.append("a" * 32, {"batch": 0, "variants": [{"text": f"v{i}"} for i in range(P.MAX_POOL - 5)]})
        new = await w.run(job_for(sl, V.Seeds(), key="a" * 32, role="top_up"))
        assert len(new) == 5 and fake.calls[-1]["n"] == 5 and len(w.store.variants("a" * 32)) == P.MAX_POOL
        assert await w.run(job_for(sl, V.Seeds(), key="a" * 32, role="top_up")) == []
        assert len(await w.more(job_for(sl, V.Seeds(), key="a" * 32))) == V.TOPUP
        assert len(w.store.variants("a" * 32)) == P.MAX_POOL + V.TOPUP
    run(go())


def test_a_person_states_its_gender_and_develops_rotated_aspects():
    sl = slot_of("a <young woman> in a kitchen", "person")
    seeds = V.person_seeds(gender=["woman", "trans woman"], clothes_owned=True)
    d = V.draw_seeds(random.Random(2), seeds, 40, sl.words)
    trans = [x for x in d.specs if x.gender == "trans woman"]
    woman = [x for x in d.specs if x.gender == "woman"]
    assert all(x.gender_needs == ("trans",) for x in trans) and all(x.gender_needs == () for x in woman)
    assert all(len(x.develop) == 2 and V.CLOTHES not in x.develop and V.AGE_SHOWS not in x.develop for x in d.specs)
    assert len({x.develop for x in d.specs}) >= 6                     # no one template
    msg = V.messages(sl, d, seeds)[1]["content"]
    assert 'gender: "trans woman"' not in msg or trans                  # told only where it adds a word
    if woman:
        assert all('gender:' not in ln for ln in msg.splitlines() if ln.startswith(f"{d.specs.index(woman[0]) + 1}. "))
    spec = V.Spec(gender="trans woman", gender_needs=("trans",))
    keep = ["young woman"]
    assert V.check("a young trans woman with a cropped bob", "young woman", keep, spec) == ""
    assert V.check("a young woman with a cropped bob", "young woman", keep, spec) == "gender missing"
    nb = V.Spec(gender="non-binary person", gender_needs=tuple(V.tokens(V.gender_mark("non-binary person"))))
    assert V.check("a non-binary chef in a striped apron", "chef", ["chef"], nb) == ""


def test_top_ups_build_on_the_list_values_the_pool_has_not_used_first():
    b = V.Bank("x", "X", tuple((f"v{i}", 1.0) for i in range(10)))
    got = V._spread(random.Random(1), b, 6, used=[f"v{i}" for i in range(6)])
    assert set(got) == {"v6", "v7", "v8", "v9"} | set(got[4:]) and set(got[:4]) == {"v6", "v7", "v8", "v9"}


def test_a_persons_look_ideas_fit_their_age():
    young = [f"{a}-year-old" for a in range(18, 30)]
    old = [f"{a}-year-old" for a in range(70, 90)]
    ideas = [("person.hair_color", None), ("person.hair_texture", None)]
    y = {b.list_id: set(b.texts()) for b in V.person_seeds(ages=young, ideas=ideas).ideas}
    o = {b.list_id: set(b.texts()) for b in V.person_seeds(ages=old, ideas=ideas).ideas}
    assert "salt-and-pepper" not in y["person.hair_color"] and "gray" not in y["person.hair_color"]
    assert "thinning" not in y["person.hair_texture"] and "thinning" in o["person.hair_texture"]
    assert "gray" in o["person.hair_color"]


def test_a_and_an_are_set_right_when_a_variant_is_stored():
    class Off(FakeWriter):
        async def __call__(self, messages, project_id, max_tokens, temperature=0.8):
            req = parse_request(messages)
            return json.dumps({"variants": [{"n": i, "text": f"a off-center selfie no{i}"} for i in range(1, req["n"] + 1)]})
    b = run(V.write_batch(slot_of("<selfie camera angle>, phone photo", "list", "camera angle"), V.Seeds(), 3, ask=Off()))
    assert b.texts() and all(t.startswith("an off-center selfie") for t in b.texts())

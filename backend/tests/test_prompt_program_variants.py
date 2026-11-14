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
    # a seeded descent may be left out where it can't be true; one the user picked must appear
    assert V.check("dominant young woman with a bob", w, keep, spec) == ""
    assert V.check("dominant young woman with a bob", w, keep, V.Spec(descent="Korean", descent_required=True)) == "descent missing"
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
    s = V.person_seeds().pinned(V.Pins(gender=("non-binary person",)))
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
    assert '"woman"; "man"; "trans woman"; "trans man"; "non-binary person"' in msg and "Ideas (random" not in msg
    # each variant's own ideas are on its seed line
    lines = msg.split("Seeds, one line per variant:")[1]
    for i, spec in enumerate(d.specs, 1):
        for t, _ in spec.ideas:
            assert re.search(rf'^{i}\. .*ideas: .*"{re.escape(t)}"', lines, re.M)


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
    assert [c["n"] for c in fake.calls] == [V.PICK_CHUNK] * (V.N_PERSON // V.PICK_CHUNK)   # side by side
    vs = [v for b in batches for v in b.variants]
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
    chunks = V.N_PERSON // V.PICK_CHUNK
    fake = FakeWriter(["empty"] * chunks)   # every chunk of the first round comes back empty
    batches = run(V.write_first(sl, V.person_seeds(), ask=fake))
    assert len(fake.calls) == 2 * chunks and sum(len(b.variants) for b in batches) == 40
    fake = FakeWriter(["empty"] * (chunks - 2))   # 10 survive across the chunks: under MIN_POOL, once more
    batches = run(V.write_first(sl, V.person_seeds(), ask=fake))
    assert len(fake.calls) == 2 * chunks and sum(len(b.variants) for b in batches) == 10 + 40
    fake = FakeWriter(["empty"] * (chunks - 3))   # 15 survive: enough
    batches = run(V.write_first(sl, V.person_seeds(), ask=fake))
    assert len(fake.calls) == chunks and sum(len(b.variants) for b in batches) == 15
    fake = FakeWriter(["raise", "prose"] * chunks)
    batches = run(V.write_first(sl, V.person_seeds(), ask=fake))
    assert len(batches) == 2 * chunks and not any(b.variants for b in batches)


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


ADULTS = [v.text for v in vocabulary().get(V.AGE).values if not v.opt_in]   # "chef": every adult age
YOUNG_AGES = [f"{a}-year-old" for a in range(18, 30)]                       # "young woman"


def test_age_stages_are_what_the_words_and_the_minors_rules_allow():
    assert list(V.age_stages()) == ["young adult", "middle-aged", "older", "elderly"]   # not narrowed yet: adults
    assert list(V.age_stages(ADULTS)) == ["young adult", "middle-aged", "older", "elderly"]
    # 18 and 19 are tagged teen too, but a stage holding an age under 18 needs the minors rules to allow one
    assert "teen" not in V.age_stages(ADULTS) and "18-year-old" in V.age_stages(ADULTS)["young adult"]
    assert V.age_stages(YOUNG_AGES) == {"young adult": YOUNG_AGES}
    teen = ["14-year-old", "15-year-old", "16-year-old"]
    assert V.age_stages(teen) == {"teen": teen}                                   # "a teenage girl"
    # a user list's age under 18 on their line: that age, never the rest of childhood
    got = V.age_stages(ADULTS, ("9-year-old",))
    assert got["child"] == ["9-year-old"] and "baby" not in got and got["teen"] == ["18-year-old", "19-year-old"]
    assert V.stages_of("35-year-old") == ("young adult", "middle-aged") and V.stages_of("nonsense") == ()
    assert (V.age_years("newborn"), V.age_years("34-year-old")) == (0, 34)


def test_a_picked_life_stage_seeds_ages_within_what_the_words_allow():
    chef = V.person_seeds(ages=ADULTS)
    s = chef.pinned(V.Pins(age=("elderly",)))
    assert s.age.texts() == V.age_stages(ADULTS)["elderly"]
    assert {sp.age for sp in V.draw_seeds(random.Random(2), s, 200).specs} <= set(s.age.texts())
    # words that state an age seed none unpinned; a pick seeds within them, so it shows in the variants
    young = V.person_seeds(ages=YOUNG_AGES)
    assert young.age is None
    s = young.pinned(V.Pins(age=("young adult",)))
    assert set(s.age.texts()) == set(YOUNG_AGES)
    d = V.draw_seeds(random.Random(4), s, 40)
    assert all(sp.age in YOUNG_AGES for sp in d.specs) and any(V.AGE_SHOWS in sp.develop for sp in d.specs)
    # a stage the words rule out, or one under 18 the minors rules don't allow, changes nothing
    assert young.pinned(V.Pins(age=("elderly",))).age is None
    assert chef.pinned(V.Pins(age=("teen", "child", "baby"))).age == chef.age
    # a child the rules allow: only their own ages
    kid = V.person_seeds(ages=["8-year-old", "9-year-old"])
    assert kid.pinned(V.Pins(age=("child",))).age.texts() == ["8-year-old", "9-year-old"]
    # a list slot has no age to pin
    assert V.list_seeds([("person.makeup", None)]).pinned(V.Pins(age=("elderly",))).age is None



def test_picked_years_seed_alongside_stages_within_what_the_person_may_be():
    chef = V.person_seeds(ages=ADULTS)
    pins = V.Pins(age=("elderly",), years=(24, 31))
    assert pins.ages(ADULTS) == ["24-year-old", "31-year-old", *V.age_stages(ADULTS)["elderly"]]
    assert set(chef.pinned(pins).age.texts()) == set(pins.ages(ADULTS))
    # years alone, where the words state an age: only those years the narrowing kept
    young = V.person_seeds(ages=YOUNG_AGES)
    assert young.pinned(V.Pins(years=(24, 50))).age.texts() == ["24-year-old"]
    assert young.pinned(V.Pins(years=(50,))).age is None
    # a year under 18 only where the minors rules allow it
    assert chef.pinned(V.Pins(years=(15,))).age == chef.age
    kid = V.person_seeds(ages=["8-year-old", "9-year-old"])
    assert kid.pinned(V.Pins(years=(9, 12))).age.texts() == ["9-year-old"]
    assert V.year_ages([0, 24]) == ["newborn", "24-year-old"]


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


def test_a_picked_life_stage_filters_the_pool_by_each_variants_recorded_age():
    pool = [{"text": "a", "seeds": {"age": "24-year-old"}}, {"text": "b", "seeds": {"age": "37-year-old"}},
            {"text": "c", "seeds": {"age": "72-year-old"}}, {"text": "d", "seeds": {"descent": "Korean"}}]
    rng = random.Random(3)
    c = P.Choice(pins=V.Pins(age=("middle-aged",)))
    assert {P.pick(pool, {}, c, rng, "w").text for _ in range(20)} == {"b"}
    c = P.Choice(pins=V.Pins(age=("young adult", "elderly")))
    assert {P.pick(pool, {}, c, rng, "w").text for _ in range(30)} == {"a", "b", "c"}
    # nothing recorded in that stage yet: the words, and a top-up is due
    c = P.Choice(pins=V.Pins(age=("older",)))
    assert P.pick(pool, {}, c, rng, "w").text == "w" and P.due(pool, {}, c)
    assert P.in_pool(pool, "age") == {"young adult": 2, "middle-aged": 1, "elderly": 1}
    # any of the picked stages or years
    c = P.Choice(pins=V.Pins(age=("elderly",), years=(24,)))
    assert {P.pick(pool, {}, c, rng, "w").text for _ in range(30)} == {"a", "c"}
    assert {P.pick(pool, {}, P.Choice(pins=V.Pins(years=(37,))), rng, "w").text for _ in range(10)} == {"b"}
    assert P.in_pool_years(pool) == {"24": 1, "37": 1, "72": 1}


def test_choice_wire_form():
    c = P.Choice.of({"values": ["a"], "seeds": {"descent": {"values": ["Korean"], "groups": {"region": ["Europe"]}},
                                                 "gender": {"values": ["trans woman"]}}, "add": ["x"]}, add=["y"])
    assert c.values == ("a",) and c.add == ("x", "y")
    assert c.pins == V.Pins(descent=("Korean",), regions=("Europe",), gender=("trans woman",))
    assert c.to_dict()["seeds"]["gender"] == {"values": ["trans woman"]}
    assert c.to_dict()["seeds"]["descent"] == {"values": ["Korean"], "groups": {"region": ["Europe"]}}
    c = P.Choice.of({"seeds": {"age": {"values": ["young adult", "elderly"]}, "gender": {"values": ["man"]}}})
    assert c.pins == V.Pins(gender=("man",), age=("young adult", "elderly"))
    assert c.to_dict() == {"seeds": {"gender": {"values": ["man"]}, "age": {"values": ["young adult", "elderly"]}}}
    assert c.pins.to_dict() == {"gender": ["man"], "age": ["young adult", "elderly"]}
    c = P.Choice.of({"seeds": {"age": {"values": ["middle-aged"], "years": [24, "31", "x", True, 24]}}})
    assert c.pins == V.Pins(age=("middle-aged",), years=(24, 31))
    assert c.to_dict() == {"seeds": {"age": {"values": ["middle-aged"], "years": [24, 31]}}}
    assert P.Choice.of({"seeds": {"age": {"years": [40]}}}).pins.to_dict() == {"age_years": [40]}
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
    a = got["age"]
    assert a["label"] == "Age" and a["browse"] == "life_stage"
    assert a["options"] == a["fits"] == ["young adult", "middle-aged", "older", "elderly"]   # an adult: no child or teen
    assert a["stages"][0] == {"id": "young adult", "label": "Young adult", "span": [18, 39],
                              "years": list(range(18, 40))}
    assert a["stages"][-1]["span"] == [70, 110] and a["stages"][-1]["label"] == "Elderly"
    assert a["picked"] == {"values": [], "years": []} and a["in_pool_years"] == {}
    young = P.person_pickers(POOL, P.Choice(pins=V.Pins(age=("young adult",))), ages=V.age_stages(YOUNG_AGES))["age"]
    assert young["options"] == ["young adult"] and young["stages"][0]["span"] == [18, 29]
    assert young["picked"] == {"values": ["young adult"], "years": []} and young["in_pool"] == {}


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
    assert len(run(go()).calls) == V.N_PERSON // V.PICK_CHUNK


def test_a_failed_first_write_is_not_stored_and_asked_again(tmp_path):
    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter(["raise", "prose"] * (V.N_PERSON // V.PICK_CHUNK)))
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
        assert [c["n"] for c in fake.calls[-4:]] == [V.PICK_CHUNK] * 4   # 20, written 5 at a time side by side
        failing = P.PoolWriter(P.VariantStore(tmp_path / "x"), ask=FakeWriter(["raise"] * 4))
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


def test_a_picked_life_stage_nothing_matches_writes_a_batch_with_it(tmp_path):
    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter(), paused=lambda: True)
        w.attach()
        sl = slot_of("a <young woman> on a rooftop", "person")
        key = "8" * 32
        young = V.person_seeds(ages=YOUNG_AGES)          # "young" states her age: no age seeded unpinned
        w.store.append(key, {"batch": 0, "variants": POOL})
        choice = P.Choice(pins=V.Pins(age=("young adult",)))
        assert w.picked(job_for(sl, young, key=key), choice)
        await asyncio.wait_for(w.drain(), 5)
        rec = w.store.batches(key)[-1]
        assert rec["pinned"] == {"age": ["young adult"]}
        assert rec["variants"] and all(v["seeds"]["age"] in YOUNG_AGES for v in rec["variants"])
        assert len(P.drawable(w.store.variants(key), choice)) >= P.MIN_MATCH
        assert not w.picked(job_for(sl, young, key=key), choice)   # enough now
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


def test_a_top_up_rechecks_the_room_when_it_lands(tmp_path):
    """Another lane (a pick's batch) may fill the pool while a top-up is out: the top-up keeps
    only what still fits under MAX_POOL."""
    async def go():
        fake = FakeWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        key = "b" * 32
        w.store.append(key, {"batch": 0, "variants": [{"text": f"v{i}"} for i in range(P.MAX_POOL - 5)]})

        async def ask(messages, project_id, max_tokens, temperature=0.8):
            # The other lane lands its 3 while this call is out.
            w.store.append(key, {"batch": 1, "variants": [{"text": f"other{i}"} for i in range(3)]})
            return await fake(messages, project_id, max_tokens, temperature)
        w.ask = ask
        sl = slot_of(PROMPT, "list", "lighting", n=3)
        new = await w.run(job_for(sl, V.Seeds(), key=key, role="top_up"))
        assert len(new) == 2 and len(w.store.variants(key)) == P.MAX_POOL
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


# --------------------------------------------------------------------------- a pick's batch, fast

class GatedWriter(FakeWriter):
    """A FakeWriter whose calls each wait for their own gate, to look at a write mid-flight."""

    def __init__(self, slips: Optional[List[str]] = None):
        super().__init__(slips)
        self.gates: List[asyncio.Event] = []

    async def __call__(self, messages, project_id, max_tokens, temperature=0.8) -> str:
        gate = asyncio.Event()
        self.gates.append(gate)
        try:
            reply = await super().__call__(messages, project_id, max_tokens, temperature)
        except RuntimeError:
            await gate.wait()
            raise
        await gate.wait()
        return reply


async def until(cond, seconds: float = 5.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


async def open_all(fake: GatedWriter, w: P.PoolWriter) -> None:
    """Let every call through, the ones still to come included, until the writer is done."""
    async def keep_opening():
        while True:
            for g in fake.gates:
                g.set()
            await asyncio.sleep(0.005)
    opener = asyncio.ensure_future(keep_opening())
    try:
        await asyncio.wait_for(w.drain(), 5)
    finally:
        opener.cancel()


def test_a_batch_splits_into_chunks_with_seeds_drawn_once():
    seeds = V.person_seeds(ideas=[("person.hair_color", None), ("person.build", None)])
    whole = V.draw_seeds(random.Random(4), seeds, 20, "dominant young woman")
    parts = V.split(whole)
    assert [len(p.specs) for p in parts] == [V.PICK_CHUNK] * 4
    assert [s for p in parts for s in p.specs] == whole.specs            # the one draw, in order
    assert [i for p in parts for i in p.ideas] == whole.ideas            # every idea once, shared out
    assert all(p.short == whole.short for p in parts)
    assert len({s.develop for s in whole.specs}) == 20                   # aspects rotate across chunks
    assert [len(p.specs) for p in V.split(V.draw_seeds(random.Random(1), V.Seeds(), 7))] == [4, 3]
    assert V.split(V.draw_seeds(random.Random(1), V.Seeds(), 5))[0].specs.__len__() == 5


def test_a_pick_shows_its_first_chunk_while_the_rest_are_written(tmp_path):
    async def go():
        fake = GatedWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake, paused=lambda: True)
        w.attach()
        sl = slot_of(PROMPT, "person")
        key = "7" * 32
        w.store.append(key, {"batch": 0, "variants": POOL})
        choice = P.Choice(pins=V.Pins(descent=("Korean",)))
        assert w.picked(job_for(sl, V.person_seeds(), key=key), choice)
        await until(lambda: len(fake.gates) == 4)                        # four calls side by side, at once
        assert [c["n"] for c in fake.calls] == [V.PICK_CHUNK] * 4
        korean = [v["text"] for v in POOL if v["seeds"]["descent"] == "Korean"]
        for c in fake.calls:   # told only what already matches the pick
            shown = c["user"].split("Already written")[1].split("\n\n")[0] if "Already written" in c["user"] else ""
            assert all(t in shown for t in korean) and not any(f"- {v['text']}\n" in shown + "\n"
                                                                for v in POOL if v["text"] not in korean)
        fake.gates[2].set()
        await until(lambda: len(P.drawable(w.store.variants(key), choice)) == len(korean) + V.PICK_CHUNK)
        assert w.busy(key)                                               # /pools: more stays on
        for g in fake.gates:
            g.set()
        await asyncio.wait_for(w.drain(), 5)
        got = P.drawable(w.store.variants(key), choice)
        assert len(got) == len(korean) + V.TOPUP and not w.busy(key)
        assert all(b["pinned"] == {"descent": ["Korean"]} for b in w.store.batches(key)[1:])
        assert len(w.store.batches(key)) == 1 + 4                        # one record per chunk
    run(go())


def test_a_pick_never_waits_behind_background_writes(tmp_path):
    async def go():
        fake = GatedWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake, workers=1)
        w.attach()
        sl = slot_of(PROMPT, "person")
        key = "6" * 32
        w.store.append(key, {"batch": 0, "variants": POOL})
        assert w.submit(job_for(sl, V.person_seeds(), key=key, role="top_up"))   # a background top-up, held
        assert w.submit(job_for(sl, V.person_seeds(), key="5" * 32))             # and another pool's first write
        await until(lambda: len(fake.gates) == 1)
        choice = P.Choice(pins=V.Pins(gender=("trans man",)))
        assert w.picked(job_for(sl, V.person_seeds(), key=key), choice)          # same pool, its own lane
        await until(lambda: len(fake.gates) == 1 + 4)
        for g in fake.gates[1:]:
            g.set()
        await until(lambda: len(P.drawable(w.store.variants(key), choice)) >= V.TOPUP)
        assert w.busy(key)
        await open_all(fake, w)
    run(go())


def test_a_chunk_that_slips_keeps_the_others(tmp_path):
    async def go():
        fake = FakeWriter(["raise", "prose"])
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake, paused=lambda: True)
        w.attach()
        sl = slot_of(PROMPT, "person")
        key = "4" * 32
        w.store.append(key, {"batch": 0, "variants": POOL})
        choice = P.Choice(pins=V.Pins(descent=("Welsh",)))
        assert w.picked(job_for(sl, V.person_seeds(), key=key), choice)
        await asyncio.wait_for(w.drain(), 5)
        assert len(P.drawable(w.store.variants(key), choice)) == 2 * V.PICK_CHUNK
        assert P.pick(w.store.variants(key), {}, choice, random.Random(), sl.words).source == "variant"
    run(go())


def test_the_call_gate_caps_calls_and_grants_by_priority():
    async def go():
        gate = P.CallGate(limit=2, extra=1)
        order: List[str] = []
        release = asyncio.Event()

        async def call(name, prio, urgent=False):
            async with gate.slot(prio, urgent):
                order.append(name)
                await release.wait()
        tasks = [asyncio.ensure_future(call(n, p)) for n, p in (("a0", (1, 0)), ("a1", (1, 1)), ("b1", (1, 1)),
                                                                  ("top", (2, 0)), ("b0", (1, 0)))]
        await until(lambda: len(order) == 2)
        assert order == ["a0", "b0"] and gate.running == 2   # arriving together: first chunks first
        tasks.append(asyncio.ensure_future(call("pick", (0, 0), urgent=True)))   # beyond the cap, at once
        await until(lambda: len(order) == 3)
        assert order[-1] == "pick" and gate.running == 3
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert order == ["a0", "b0", "pick", "a1", "b1", "top"]   # later chunks next, top-ups last
        assert gate.running == 0
    run(go())


def test_a_first_write_shows_its_first_chunks_under_the_cap(tmp_path, monkeypatch):
    async def go():
        fake = GatedWriter()
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        person, room = "1" * 32, "2" * 32
        w.submit(job_for(slot_of(PROMPT, "person"), V.person_seeds(), key=person))
        w.submit(job_for(slot_of(PROMPT, "list", "lighting", n=3), V.Seeds(), key=room))
        await until(lambda: len(fake.gates) == P.CALLS)                    # 8 + 6 chunks, 8 at a time
        await asyncio.sleep(0.05)
        assert len(fake.gates) == P.CALLS
        words = [c["words"] for c in fake.calls]
        assert words.count("lighting") >= 3 and words.count("dominant young woman") >= 3   # both pools' first chunks
        fake.gates[0].set()
        await until(lambda: w.store.has(fake.calls[0]["words"] == "lighting" and room or person))
        assert w.state(person if fake.calls[0]["words"] != "lighting" else room) == "ready"
        assert w.busy(person) and w.busy(room)                             # /pools: ready, more coming
        await open_all(fake, w)
        assert len(w.store.variants(person)) == V.N_PERSON and len(w.store.variants(room)) == V.N_OTHER
        assert len(w.store.batches(person)) == V.N_PERSON // V.PICK_CHUNK  # a record per chunk
    run(go())


# --------------------------------------------------------------------------- descent left out where it can't be true

class Skips(FakeWriter):
    """Writes the descent into even-numbered variants only, as a model leaving it out where it
    can't be true would, listing the others under "rejected"."""

    async def __call__(self, messages, project_id, max_tokens, temperature=0.8):
        req = parse_request(messages)
        self.calls.append(req)
        out, rejected = [], []
        for i in range(1, req["n"] + 1):
            d = re.match(r'"([^"]+)"', req["seeds"].get(i, ""))
            g = re.search(r'gender: "([^"]+)"', req["seeds"].get(i, ""))
            said = d and i % 2 == 0
            if d and not said:
                rejected.append(d.group(1))
            out.append({"n": i, "text": f"{ADJ[i]} {d.group(1) + ' ' if said else ''}{g.group(1) + ' ' if g else ''}"
                                        f"{' '.join(req['chunks']) or req['words']} no{i}", "idea": ""})
        return json.dumps({"rejected": rejected, "variants": out})


def test_a_variant_may_leave_its_descent_out_and_records_it_only_when_written():
    sl = slot_of(PROMPT, "person")
    fake = Skips()
    b = run(V.write_batch(sl, V.person_seeds(), 10, ask=fake, rng=random.Random(3)))
    assert len(b.variants) == 10 and not b.dropped                       # never dropped for leaving it out
    with_d = [v for v in b.variants if "descent" in v["seeds"]]
    assert len(with_d) == 5 and all(V.has_run(v["text"], v["seeds"]["descent"]) for v in with_d)
    assert dict(b.descents) == {"seeded": 10, "written": 5}
    # the writer is told to give the look, write the word where it reads naturally, or reject it
    system = fake.calls[0]["system"]
    assert "give the person that heritage's look" in system and 'list it under "rejected"' in system
    assert "(must appear)" not in fake.calls[0]["user"]


def test_a_picked_descent_must_still_appear():
    sl = slot_of(PROMPT, "person")
    fake = Skips()
    seeds = V.person_seeds().pinned(V.Pins(descent=("Korean", "Thai")))
    assert seeds.descent_pinned
    b = run(V.write_batch(sl, seeds, 10, ask=fake, rng=random.Random(3)))
    assert b.dropped["descent missing"] == 5 and len(b.variants) == 5
    assert all(v["seeds"]["descent"] in ("Korean", "Thai") for v in b.variants)
    assert "(must appear)" in fake.calls[0]["user"]


# --------------------------------------------------------------------------- ideas per variant

def test_each_variant_has_its_own_ideas_no_repeats_in_a_batch_and_chunks_carry_them():
    seeds = V.person_seeds(ideas=[("person.hair_color", None), ("person.build", None), ("person.hairstyle", None)])
    d = V.draw_seeds(random.Random(11), seeds, 20, "dominant young woman")
    assert all(1 <= len(s.ideas) <= 2 for s in d.specs)
    texts = [t for t, _ in d.ideas]
    assert len(texts) == len(set(texts))                                   # no repeats in a batch
    assert not any("{" in t for t in texts)                                # palette slots filled
    for part in V.split(d):                                                # each variant keeps its own
        for s in part.specs:
            assert s in d.specs and part.ideas == [x for sp in part.specs for x in sp.ideas]


def test_idea_counts_are_kept_per_batch_and_a_rejected_idea_counts():
    class Uses(FakeWriter):
        async def __call__(self, messages, project_id, max_tokens, temperature=0.8):
            req = parse_request(messages)
            out, rejected = [], []
            for i in range(1, req["n"] + 1):
                ideas = re.findall(r'"([^"]+)"', req["seeds"][i].split("ideas:")[1]) if "ideas:" in req["seeds"][i] else []
                used = ideas[:1]
                rejected += ideas[1:]
                out.append({"n": i, "text": f"{' '.join(req['chunks']) or req['words']} with {used[0] if used else 'a hat'} no{i}",
                            "idea": "; ".join(used)})
            return json.dumps({"rejected": rejected, "variants": out})
    s = V.list_seeds([("person.hairstyle", None), ("person.hair_color", None)])
    b = run(V.write_batch(slot_of("a woman with <hair>, portrait"), s, 8, ask=Uses(), rng=random.Random(2)))
    offered, used, rejected = b.ideas["offered"], b.ideas["used"], b.ideas["rejected"]
    assert offered >= 8 and used == 8 and rejected == offered - 8


# --------------------------------------------------------------------------- replies as a local model sends them

def _fenced(variants, rejected=()):
    return "```json\n" + json.dumps({"rejected": list(rejected), "variants": variants}, indent=2) + "\n```"


CARS = [{"n": i + 1, "text": t, "idea": "none"} for i, t in enumerate(
    ["a sleek red sports car", "a vintage silver roadster", "a matte black aerodynamic coupe",
     "a bright yellow convertible", "a wide-bodied electric grand tourer"])]


def test_a_reply_that_answers_talks_and_answers_again_is_read_by_its_last_answer():
    # The shape that kept <sports car> at 5 variants: a fenced object, prose arguing with the
    # seeds, then another fenced object. Reading first "{" to last "}" spanned both.
    second = [{**v, "text": v["text"].replace("a ", "a low ", 1)} for v in CARS]
    reply = (_fenced(CARS, ["logging truck", "taxi"]) + "\n\nWait, looking at the prompt instructions again, "
             "the seeds are *not* sports cars. Let's provide 5 variants where I treat {the seeds} as kinds:\n\n"
             + _fenced(second))
    got = V.parse_reply(reply)
    assert [v["text"] for v in got["variants"]] == [v["text"] for v in second] and got["rejected"] == []


def test_a_reply_with_a_fence_per_variant_or_prose_around_it_is_read():
    assert len(V.parse_reply("Here you go:\n" + _fenced(CARS) + "\nHope these help!")["variants"]) == 5
    assert len(V.parse_reply(json.dumps({"variants": CARS}))["variants"]) == 5
    assert V.parse_reply("Sure! Here are some variants you might like.") is None
    assert V.parse_reply('```json\n{"slots": []}\n```') == {"slots": []}


def test_a_reply_cut_at_the_token_budget_keeps_the_variants_before_the_cut():
    full = _fenced(CARS, ["school bus", "tractor"])
    cut = full[:full.index('"text": "a bright yellow')]   # cut inside variant 4
    got = V.parse_reply(cut)
    assert [v["text"] for v in got["variants"]] == [v["text"] for v in CARS[:3]]
    assert got["rejected"] == ["school bus", "tractor"]
    # an answer closed, then talk cut off mid-sentence (finish_reason "length"): the closed answer
    got = V.parse_reply(full + '\nOne last check: "a ⟦sports car⟧ parked in <place>".\nVariant 1: "')
    assert len(got["variants"]) == 5
    assert V.parse_reply('```json\n{\n  "rejected": [],\n  "variants": [\n    {\n      "n": 1,\n      "te') is None


def test_a_cut_reply_is_written_as_the_variants_that_closed():
    sl = slot_of("a <sports car> parked in <place>, low angle, golden hour", "free", "sports car")
    full = _fenced(CARS)

    async def cut(*a, **k):
        return full[:full.index('"text": "a bright yellow')]
    b = run(V.write_batch(sl, V.Seeds(), 5, ask=cut))
    assert len(b.variants) == 3 and b.dropped["missing"] == 2 and not b.error


def test_a_writes_token_budget_follows_the_variants_it_asks_for():
    fake = FakeWriter()
    run(V.write_batch(slot_of(PROMPT, "person"), V.person_seeds(), 5, ask=fake))
    assert fake.calls[0]["max_tokens"] == V.write_tokens(5) < 1500   # a runaway is cut in seconds
    assert V.write_tokens(40) == V.WRITE_TOKENS and V.write_tokens(20) < V.WRITE_TOKENS


# --------------------------------------------------------------------------- a gender the words carry

GRANDMOTHER = "a small apartment on a rainy evening\na <grandmother> with <her pet>, <light>\n# make it look like a 1990s snapshot"


def test_a_gender_needs_only_the_words_that_tell_it_from_the_others_the_words_allow():
    assert V.gender_needs("woman", "grandmother", ["woman", "trans woman"]) == ()
    assert V.gender_needs("trans woman", "grandmother", ["woman", "trans woman"]) == ("trans",)
    assert V.gender_needs("woman", "grandmother", ["woman"]) == ()
    assert V.gender_needs("trans man", "grandfather", ["man", "trans man"]) == ("trans",)
    # words that narrow nothing: every word of it not in the slot's words (today's rule)
    assert V.gender_needs("woman", "chef") == ("woman",)
    assert V.gender_needs("trans woman", "person") == ("trans", "woman")
    assert V.gender_needs("trans woman", "young woman", ["woman", "trans woman"]) == ("trans",)
    assert V.gender_needs("non-binary person", "chef") == ("non", "binary")
    # a pick outside what the words allow still shows
    assert V.gender_needs("man", "grandmother", ["woman", "trans woman"]) == ("man",)


def test_a_grandmother_is_written_with_no_gender_word_and_a_trans_one_says_so():
    # The overnight run: every seed line said gender "woman", the writer wrote "... grandmother ...",
    # and every variant was dropped for "gender missing", so <grandmother> went out as its word.
    sl = slot_of(GRANDMOTHER, "person")
    seeds = V.person_seeds(gender=["woman", "trans woman"])
    drawn = V.draw_seeds(random.Random(2), seeds, 200, sl.words)
    assert {s.gender_needs for s in drawn.specs} == {(), ("trans",)}
    lines = [s.line() for s in drawn.specs]
    assert not any("gender" in ln for s, ln in zip(drawn.specs, lines) if s.gender == "woman")
    assert all('gender: "trans woman"' in ln for s, ln in zip(drawn.specs, lines) if s.gender == "trans woman")
    reply = _fenced([{"n": 1, "text": "a Bangladeshi grandmother wearing a turquoise cotton T-shirt and straight blue jeans", "idea": ""},
                     {"n": 2, "text": "a stocky Peruvian grandmother with ear-length hair and a gentle, weathered expression", "idea": ""},
                     {"n": 3, "text": "a White American grandmother with wavy hair and a kind, smiling face", "idea": ""}])

    async def ask(*a, **k):
        return reply
    woman = V.Drawn([V.Spec(gender="woman", gender_needs=V.gender_needs("woman", sl.words, ["woman"]))] * 3, [])
    b = run(V.write_batch(sl, seeds, 3, ask=ask, drawn=woman))
    assert len(b.variants) == 3 and not b.dropped
    trans = V.Drawn([V.Spec(gender="trans woman", gender_needs=("trans",))] * 3, [])
    assert run(V.write_batch(sl, seeds, 3, ask=ask, drawn=trans)).dropped["gender missing"] == 3


def test_what_the_seed_line_shows_of_a_gender_passes_the_check():
    for words, fits in (("grandmother", ["woman", "trans woman"]), ("chef", None), ("young woman", ["woman", "trans woman"]),
                        ("person", None), ("grandfather", ["man", "trans man"])):
        for g in ("woman", "man", "trans woman", "trans man", "non-binary person"):
            spec = V.Spec(gender=g, gender_needs=V.gender_needs(g, words, fits))
            shown = re.search(r'gender: "([^"]+)"', spec.line())
            text = f"tall {shown.group(1)} {words} in a coat" if shown else f"tall {words} in a coat"
            assert V.check(text, words, [words], spec) == "", (words, g)


def test_a_gender_picked_for_a_grandmother_shows_where_it_tells_her_apart():
    seeds = V.person_seeds(gender=["woman", "trans woman"]).pinned(V.Pins(gender=("trans woman",)))
    assert seeds.gender_fits == ("woman", "trans woman")
    specs = V.draw_seeds(random.Random(1), seeds, 20, "grandmother").specs
    assert {s.gender for s in specs} == {"trans woman"} and {s.gender_needs for s in specs} == {("trans",)}
    seeds = V.person_seeds(gender=["woman", "trans woman"]).pinned(V.Pins(gender=("woman",)))
    assert {s.gender_needs for s in V.draw_seeds(random.Random(1), seeds, 20, "grandmother").specs} == {()}
    # a person whose words narrow nothing shows a picked woman
    seeds = V.person_seeds().pinned(V.Pins(gender=("woman",)))
    assert {s.gender_needs for s in V.draw_seeds(random.Random(1), seeds, 20, "chef").specs} == {("woman",)}


# --------------------------------------------------------------------------- a short first write

def test_a_short_first_write_draws_what_it_has_and_is_asked_again_once(tmp_path, monkeypatch):
    # Overnight, <sports car> kept 5 of 30 (unreadable replies, then timeouts), was stored as its
    # first write, and stayed at 5 for every image.
    chunks = V.N_OTHER // V.PICK_CHUNK
    sl = slot_of("a <sports car> parked in <place>, low angle, golden hour", "free", "sports car")

    async def go():
        fake = FakeWriter(["prose"] * (chunks - 1) + ["prose"] * chunks)   # 5 kept, in two rounds
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=fake)
        w.attach()
        job = job_for(sl, V.Seeds())
        w.submit(job)
        await w.drain()
        assert len(w.store.variants(job.key)) == 5 and w.state(job.key) == "ready"
        assert not w.first_written(job.key)
        first = w.store.variants(job.key)[0]["text"]
        assert not w.submit(job_for(sl, V.Seeds()))   # not at once: after RETRY_AFTER
        monkeypatch.setattr(P, "RETRY_AFTER", 0.0)
        assert w.submit(job_for(sl, V.Seeds()))
        await w.drain()
        assert len(w.store.variants(job.key)) == V.N_OTHER and w.first_written(job.key)
        assert first in fake.calls[-1]["user"]   # told what the pool holds
        assert not w.submit(job_for(sl, V.Seeds()))   # done
        return fake
    run(go())


def test_a_short_first_write_asked_again_and_short_again_is_left_to_top_ups(tmp_path, monkeypatch):
    chunks = V.N_OTHER // V.PICK_CHUNK
    monkeypatch.setattr(P, "RETRY_AFTER", 0.0)
    sl = slot_of("a <sports car> parked in <place>, low angle, golden hour", "free", "sports car")

    async def go():
        w = P.PoolWriter(P.VariantStore(tmp_path), ask=FakeWriter(["prose"] * 100))
        w.attach()
        job = job_for(sl, V.Seeds())
        w.store.append(job.key, {"batch": 0, "role": "first", "variants": [{"text": "sleek red sports car", "seeds": {}}]})
        assert not w.first_written(job.key) and w.submit(job)
        await w.drain()
        assert w.first_written(job.key) and not w.submit(job_for(sl, V.Seeds()))
        assert len(w.store.variants(job.key)) == 1
    run(go())


def test_a_variant_that_copies_the_line_before_it_with_another_slot_is_cut_back_not_lost():
    # Rerun of the grandmother prompt: the writer copied "a <grandmother> with" before each pet,
    # and the markup cut kept only "a", so every variant failed "words not kept".
    prompt = GRANDMOTHER
    sl = slot_of(prompt, "free", "pet", n=2)
    reply = _fenced([{"n": 1, "text": "a <grandmother> with her tabby cat curled in her lap", "idea": "cat"},
                     {"n": 2, "text": "a <grandmother> with her pet guinea pig, <light>", "idea": "guinea pig"},
                     {"n": 3, "text": "her bright orange koi in a glass bowl", "idea": "koi"}])

    async def ask(*a, **k):
        return reply
    b = run(V.write_batch(sl, V.Seeds(), 3, ask=ask))
    assert b.texts() == ["her tabby cat curled in her lap", "her pet guinea pig", "her bright orange koi in a glass bowl"]


def test_a_variant_that_is_an_article_alone_is_dropped():
    # Overnight, <place> stored "a" and porch_dog's light drew "a": "on a porch, a, an overhead shot".
    assert V.check("a", "place", [], V.Spec()) == "empty"
    assert V.check("her", "her pet", ["her"], V.Spec()) == "empty"
    assert V.check("a gravel driveway", "place", [], V.Spec()) == ""


def test_a_variant_that_copies_the_words_up_to_the_next_slot_is_cut_back():
    # Rerun: "short White American grandmother with <her pet>" was stored as "... grandmother with",
    # and the filled prompt read "grandmother with with her cat".
    sl = slot_of(GRANDMOTHER, "person")
    left, right = V.context_words(sl.prompt, sl.span)
    for t in ("short White American grandmother with <her pet>, <light>", "short White American grandmother with"):
        if "<" not in t:
            assert V.repair(t, left, right, words=sl.words)[0] == t   # no markup cut: a variant may end on "with"
            continue
        assert V.repair(t, left, right, words=sl.words)[0] == "short White American grandmother"

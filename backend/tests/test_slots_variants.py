"""Slots drawn from pools of variants, end to end: prepare reads each slot (a fake reader),
narrows its seed lists by its words, writes its pool in the background (a fake writer), and
each image draws a variant. Nothing here calls a model."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from prompt_programs import program as prep
from prompt_programs import slots
from prompt_programs import variant_pools as P
from prompt_programs.choices import expand
from prompt_programs.fill import ProgramError
from prompt_programs.fluent import count_draw, pool_view
from prompt_programs.vocab import vocabulary

from test_prompt_program_variants import FakeWriter

PROMPT = ("# phone photo, her own living room\n"
          "<dominant young woman> standing in her living room in <clothing slightly open in the front>, lit by <lighting>")
READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Young woman", "lead": "", "category": "",
     "person": {"noun": "woman", "presentation": "feminine", "stated": {"age": "young"},
                "vary": ["age", "descent", "build", "hair"], "clothes_part": 2, "clothes": "", "outfit": ""}},
    {"n": 2, "kind": "list", "label": "Clothing", "lead": " in", "category": "clothing",
     "list": {"list": "clothing.top", "about": "her top, slightly open"}},
    {"n": 3, "kind": "light", "label": "Lighting", "lead": ", lit by", "category": "lighting",
     "light": {"list": "lighting.indoor_practical", "examples": ["lamplight", "TV glow", "window light"]}},
], "lists": []}
YOUNG = [f"{a}-year-old" for a in range(18, 30)]


class FakeModel:
    """The reader answers READING (or `reading`); narrowing answers by list: ages for a young
    person (or `ages`), the subset `descent`, "woman" for gender, and every item otherwise."""

    def __init__(self, reading: Dict[str, Any] = READING, ages: List[str] = YOUNG, descent=None, empty: str = ""):
        self.reading, self.ages, self.descent, self.empty = reading, ages, descent, empty
        self.narrowed: List[str] = []

    async def __call__(self, messages, project_id, max_tokens):
        if messages[0]["content"].startswith("You read the parts of an image prompt"):
            return json.dumps(self.reading)
        user = messages[-1]["content"]
        label = user.split('"')[1] if user.startswith("The list") else ""
        self.narrowed.append(label)
        if label == "Age":
            return json.dumps(self.ages)
        if label == "Descent" and self.descent is not None:
            return json.dumps({"groups": [], "items": self.descent})
        if label == "Gender":
            return json.dumps(["woman", "trans woman"])
        if self.empty and label == self.empty:
            return "[]"
        return '["ALL"]'


@pytest.fixture
def profile(tmp_path, monkeypatch):
    import app_dirs
    import prompt_programs.narrow as nw
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda pid="default": tmp_path / str(pid))

    async def fingerprint(project_id):
        return "fake-model"
    monkeypatch.setattr(prep, "model_fingerprint", fingerprint)
    for name in ("_reads", "_settling", "_failed"):
        monkeypatch.setattr(slots, name, {})
    monkeypatch.setattr(slots, "_again", set())
    monkeypatch.setattr(nw, "_asking", {})
    monkeypatch.setattr(P, "_stores", {})
    monkeypatch.setattr(P, "_writers", {})
    monkeypatch.setattr("prompt_pipeline._profile_wildcards_and_segments", lambda profile_id: ([], []))
    return "p"


def use(monkeypatch, model=None, writer=None):
    model = model or FakeModel()
    writer = writer or FakeWriter()
    monkeypatch.setattr(prep, "ask_model", model)
    monkeypatch.setattr(P, "ASK", writer)
    return model, writer


async def settled(prompt: str, profile: str, **kw: Any) -> Dict[str, Any]:
    """Prepare, let reading, narrowing and the pool writes land, and look again."""
    await slots.prepare(prompt, profile_id=profile, **kw)
    await slots.idle()
    await P.writer_for(profile).drain()
    await slots.idle()
    return await slots.prepare(prompt, profile_id=profile, start=False)


def slot(entry, sid):
    return next(s for s in entry["slots"] if s["id"] == sid)


async def test_each_slot_draws_a_variant_of_its_words(monkeypatch, profile):
    model, writer = use(monkeypatch)
    entry = await settled(PROMPT, profile)
    assert [c["kind"] for c in entry["choices"]] == ["variants"] * 3
    assert all(s["state"] == "ready" and s["pool"] for s in entry["slots"])
    store = P.store_for(profile)
    person = slot(entry, "dominant_young_woman")
    assert len(store.variants(person["pool"])) == 40
    seeds = [v["seeds"] for v in store.variants(person["pool"])]
    assert {s["gender"] for s in seeds} <= {"woman", "trans woman"}
    assert not any("age" in s for s in seeds)   # "young" states her age: no number beside it
    # a person whose clothes are another slot gets no outfit ideas
    banks = entry["seeds"]["dominant_young_woman"]["banks"]
    assert not any(b["list"].startswith(("person.outfit", "clothing.")) for b in banks)
    # the light is seeded by its indoor list, the clothing by its list, one value per variant
    light = entry["seeds"]["lighting"]["banks"]
    assert [b["role"] for b in light] == ["idea"]   # light: rejectable ideas, held to the place
    req = next(c for c in writer.calls if "⟦lighting⟧" in c["user"])
    assert 'The whole part is the category "lighting"' in req["user"]
    r = prep.realize(entry, profile_id=profile, seed=3)
    by = {d.id: d for d in r.draws}
    assert "dominant young woman" in by["dominant_young_woman"].value.lower()
    assert "slightly open in the front" in by["clothing_slightly_open_in_the_front"].value.lower()
    assert all(d.source == "variant" for d in r.draws), [(d.id, d.source, d.value) for d in r.draws]
    assert by["lighting"].value in r.prompt and ", lit by " + by["lighting"].value in r.prompt
    assert r.revision["engine"] == "variants-1" and set(r.revision["variants"]) == set(by)
    assert r.more_coming == []


async def test_a_slot_not_read_or_not_written_goes_in_as_its_words(monkeypatch, profile):
    use(monkeypatch)
    prompt = "a cozy <room> with a crackling fireplace"
    first = await slots.prepare(prompt, profile_id=profile, start=False)   # nothing read yet
    r = prep.realize(first, profile_id=profile, seed=1)
    assert r.prompt.lower() == "a cozy room with a crackling fireplace"
    # read, but its pool not written (the write failed): still its words, never dropped
    monkeypatch.setattr(P, "ASK", FakeWriter(["raise", "prose"] * 5))
    reading = {"slots": [{"n": 1, "kind": "free", "label": "Room", "lead": "", "category": "room",
                          "free": {"about": "the room", "kinds": ["den"], "instead": [], "lists": []}}], "lists": []}
    monkeypatch.setattr(prep, "ask_model", FakeModel(reading))
    entry = await settled(prompt, profile)
    assert slot(entry, "room")["state"] == "ready"
    from routes.prompt_programs import public
    monkeypatch.setattr("routes.prompt_programs.get_current_profile", lambda: profile)
    assert public(entry, prompt)["slots"][0]["state"] == "as_written"
    r = prep.realize(entry, profile_id=profile, seed=2)
    assert r.prompt.lower() == "a cozy room with a crackling fireplace" and r.more_coming == ["room"]


async def test_a_narrowing_that_keeps_nothing_drops_its_seeds_never_the_draw(monkeypatch, profile):
    use(monkeypatch, FakeModel(empty="Top"))
    entry = await settled(PROMPT, profile)
    core = entry["seeds"]["clothing_slightly_open_in_the_front"]["banks"][0]
    assert core["narrowed"] == []
    s = slot(entry, "clothing_slightly_open_in_the_front")
    assert P.store_for(profile).has(s["pool"])   # written with no seeds
    for seed in range(5):
        prep.realize(entry, profile_id=profile, seed=seed)


async def test_an_edit_elsewhere_keeps_the_pools(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    edited = PROMPT.replace("<lighting>", "<lighting>\nshot on a phone")
    again = await settled(edited, profile)
    assert slot(again, "dominant_young_woman")["pool"] == slot(entry, "dominant_young_woman")["pool"]


async def test_choices_pins_seeds_off_and_as_written(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    store = P.store_for(profile)
    person = slot(entry, "dominant_young_woman")
    one = store.variants(person["pool"])[5]["text"]
    pins, edits, chosen = expand(entry, {"dominant_young_woman": {"values": [one]}, "lighting": {"off": True},
                                         "clothing_slightly_open_in_the_front": {"as_written": True},
                                         "young_man.age": {"values": ["70-year-old"]}})
    r = prep.realize(entry, profile_id=profile, seed=1, chosen=chosen)
    assert one.lower() in r.prompt.lower() and "lit by" not in r.prompt and "in clothing slightly open in the front" in r.prompt
    # a picked descent nothing matches: the words with it, and a pinned batch written at once
    _, _, chosen = expand(entry, {"dominant_young_woman": {"seeds": {"descent": {"values": ["Welsh"]}}}})
    have = {v["seeds"].get("descent") for v in store.variants(person["pool"])}
    if "Welsh" in have:
        pytest.skip("the first pool happened to draw Welsh")
    r = prep.realize(entry, profile_id=profile, seed=1, chosen=chosen)
    assert "welsh dominant young woman" in r.prompt.lower()
    view = pool_view(entry, chosen, profile_id=profile)
    await P.writer_for(profile).drain()
    assert P.drawable(store.variants(person["pool"]), chosen["dominant_young_woman"])
    r = prep.realize(entry, profile_id=profile, seed=1, chosen=chosen)
    assert "Welsh" in r.prompt and next(d for d in r.draws if d.id == "dominant_young_woman").source == "variant"
    v = view["choices"]["dominant_young_woman"]
    assert v["person"]["descent"]["picked"]["values"] == ["Welsh"] and v["person"]["gender"]["fits"] == ["woman", "trans woman"]


async def test_a_picked_life_stage_steers_a_person_whose_words_state_an_age(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    store = P.store_for(profile)
    person = slot(entry, "dominant_young_woman")
    assert not any("age" in v["seeds"] for v in store.variants(person["pool"]))   # "young": no age seeded
    # only the stages her words allow are offered; a teen, child or ruled-out stage is passed by
    _, _, chosen = expand(entry, {"dominant_young_woman": {"seeds": {"age": {"values": ["teen", "elderly", "young adult"]}}}})
    c = chosen["dominant_young_woman"]
    assert c.pins.age == ("young adult",)
    _, _, none = expand(entry, {"dominant_young_woman": {"seeds": {"age": {"values": ["child"]}}},
                                "lighting": {"seeds": {"age": {"values": ["elderly"]}}}})
    assert none == {}
    r = prep.realize(entry, profile_id=profile, seed=1, chosen=chosen)
    assert "dominant young woman" in r.prompt.lower()   # nothing matches yet: her words
    view = pool_view(entry, chosen, profile_id=profile)
    age = view["choices"]["dominant_young_woman"]["person"]["age"]
    assert age["options"] == ["young adult"] and age["stages"][0]["span"] == [18, 29]
    assert age["picked"] == {"values": ["young adult"]}
    await P.writer_for(profile).drain()
    got = P.drawable(store.variants(person["pool"]), c)
    assert len(got) >= P.MIN_MATCH and all(v["seeds"]["age"] in YOUNG for v in got)
    r = prep.realize(entry, profile_id=profile, seed=1, chosen=chosen)
    d = next(d for d in r.draws if d.id == "dominant_young_woman")
    assert d.source == "variant" and d.seeds["age"] in YOUNG
    # the pin steers draws and writes only: the pool keeps its key
    again = await settled(PROMPT, profile)
    assert slot(again, "dominant_young_woman")["pool"] == person["pool"]


async def test_pool_view_shape(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    _, _, chosen = expand(entry, {"lighting#add": ["candlelight from a jar candle"]})
    view = pool_view(entry, chosen, profile_id=profile)
    light = view["choices"]["lighting"]
    assert light["state"] == "ready" and not light["more"] and light["kind"] == "variants"
    assert light["variants"][-1] == {"text": "candlelight from a jar candle", "seeds": {}, "uses": 0, "own": True}
    assert light["options"] == [v["text"] for v in light["variants"]]
    assert "person" in view["choices"]["dominant_young_woman"] and "person" not in light
    assert view["more"] == []


async def test_shipped_draws_count_and_top_up(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    store = P.store_for(profile)
    light = slot(entry, "lighting")
    for seed in range(24):
        r = prep.realize(entry, profile_id=profile, seed=seed)
        count_draw(entry, r, profile_id=profile)
    await P.writer_for(profile).drain()
    assert len(store.variants(light["pool"])) == 50   # topped up at 80% of 30
    assert sum(store.uses(light["pool"]).values()) == 24 and max(store.uses(light["pool"]).values()) == 1
    # previews count nothing
    before = dict(store.uses(light["pool"]))
    prep.realize(entry, profile_id=profile, seed=99)
    assert store.uses(light["pool"]) == before


async def test_a_batch_of_buffered_draws_takes_different_variants(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    from prompt_programs.fix import realize_and_fix_many
    from prompt_programs.judge import FluentSettings
    got = realize_and_fix_many(entry, seeds=list(range(8)), profile_id=profile, cfg=FluentSettings(fix_model="off"))
    lights = [next(d.value for d in r.draws if d.id == "lighting") for r, _ in got]
    assert len(set(lights)) == 8


async def test_replays_and_keep_from_this(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    r = prep.realize(entry, profile_id=profile, seed=4)
    again = prep.realize(entry, profile_id=profile, seed=77, revision=r.revision)
    assert again.prompt == r.prompt
    kept = {d.id: d.value for d in r.draws}
    assert prep.realize(entry, profile_id=profile, seed=12, fixed=kept).prompt == r.prompt
    with pytest.raises(ProgramError, match="earlier Fluent"):
        prep.realize(entry, profile_id=profile, seed=1, revision={"engine": "fill-1", "pools": {}})
    # Keep from this on one slot: its choice holds the drawn text
    _, _, chosen = expand(entry, {"lighting": {"values": [kept["lighting"]]}})
    assert kept["lighting"] in prep.realize(entry, profile_id=profile, seed=5, chosen=chosen).prompt


async def test_the_judges_reroll_takes_another_variant(monkeypatch, profile):
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    r = prep.realize(entry, profile_id=profile, seed=4)
    light = next(d for d in r.draws if d.id == "lighting")
    held = {d.id: d.value for d in r.draws if d.id != "lighting"}
    again = prep.realize(entry, profile_id=profile, seed=5, fixed=held, edits={"lighting": {"remove": [light.value]}})
    new = next(d for d in again.draws if d.id == "lighting")
    assert new.value != light.value and len(light.options) >= 2


async def test_a_person_who_may_be_a_minor_has_a_pool_of_their_own(monkeypatch, profile):
    prompt = "a <little girl> at a birthday party"
    reading = {"slots": [{"n": 1, "kind": "person", "label": "Little girl", "lead": "a", "category": "",
                          "person": {"noun": "girl", "presentation": "feminine", "stated": {"age": "little"},
                                     "vary": ["age", "hair"], "clothes_part": 0, "clothes": "",
                                     "outfit": "person.outfit.casual"}}], "lists": []}
    model, writer = use(monkeypatch, FakeModel(reading, ages=["5-year-old", "6-year-old", "7-year-old"]))
    entry = await settled(prompt, profile)
    rec = entry["seeds"]["little_girl"]
    assert rec["minor"] == ["5-year-old", "6-year-old", "7-year-old"]
    adult_key = P.pool_key("fake-model", "little girl", slot(entry, "little_girl")["seen"]["marked"],
                           slot(entry, "little_girl")["seen"]["notes"])
    assert slot(entry, "little_girl")["pool"] != adult_key
    req = writer.calls[0]["user"]
    assert "This person is under 18 (5, 6 or 7 years old)" in req
    adult = {v.text for leaf in vocabulary().leaves.values() for v in leaf.values if v.adult_only}
    assert not any(f'"{t}"' in req for t in adult)


async def test_a_user_list_of_ages_on_the_persons_line_may_make_them_a_minor(monkeypatch, profile):
    prompt = "a <woman> at the beach, {9-year-old|30-year-old}"
    reading = {"slots": [{"n": 1, "kind": "person", "label": "Woman", "lead": "a", "category": "",
                          "person": {"noun": "woman", "presentation": "feminine", "stated": {},
                                     "vary": ["age", "hair"], "clothes_part": 0, "clothes": "", "outfit": ""}}],
               "lists": [{"n": 1, "label": "Age"}]}

    class Ages(FakeModel):
        async def __call__(self, messages, project_id, max_tokens):
            user = messages[-1]["content"]
            if user.startswith('The list "Age"') and 'fit "9-year-old"' in user:
                return json.dumps(["9-year-old"])
            if user.startswith('The list "Age"') and 'fit "30-year-old"' in user:
                return json.dumps(["30-year-old"])
            return await super().__call__(messages, project_id, max_tokens)
    use(monkeypatch, Ages(reading, ages=[f"{a}-year-old" for a in range(18, 60)]))
    entry = await settled(prompt, profile)
    assert entry["seeds"]["woman"]["minor"] == ["9-year-old"]
    r = prep.realize(entry, profile_id=profile, seed=1)
    assert r.prompt.endswith(("9-year-old", "30-year-old"))   # the user's list is never filtered


async def test_a_generation_draws_and_counts(monkeypatch, profile):
    import routes.generation as gen
    use(monkeypatch)
    await settled(PROMPT, profile)

    async def no_judge(entry, project_id=None):
        return None
    monkeypatch.setattr("prompt_programs.fix.await_judge", no_judge)
    record, filled, spans = await gen._run_slots(PROMPT, {"choices": {}}, project_id=None, profile_id=profile)
    assert record["version"].startswith("slots") and len(record["draws"]) == 3
    assert all(d["source"] == "variant" for d in record["draws"])
    entry = await slots.prepare(PROMPT, profile_id=profile, start=False)
    used = sum(sum(P.store_for(profile).uses(s["pool"]).values()) for s in entry["slots"])
    assert used == 3
    # every drawn value is a span the improver keeps whole
    assert {sp[2] for sp in spans} == {d["id"] for d in record["draws"]}


async def test_the_routes_answer_the_picker(monkeypatch, profile):
    """/pools with each slot's kept words, and /options as the picker calls it (More like these)."""
    import routes.generation as gen
    import routes.prompt_programs as rp
    _, writer = use(monkeypatch)
    entry = await settled(PROMPT, profile)
    monkeypatch.setattr(rp, "get_current_profile", lambda: profile)
    monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, **k: {"mode": "prose", "program_supported": True})
    base = {"tool_id": "t", "prompt": PROMPT, "key": entry["key"], "cache_only": True}
    got = await rp.pools(rp.PreviewRequest(**base, choices={}))
    assert got["choices"]["clothing_slightly_open_in_the_front"]["keep"] == ["slightly open in the front"]
    assert got["choices"]["dominant_young_woman"]["keep"] == ["dominant young woman"]
    assert got["choices"]["lighting"]["keep"] == []
    before = len(P.store_for(profile).variants(slot(entry, "lighting")["pool"]))
    out = await rp.options(rp.OptionsRequest(**base, choice_id="lighting", choices={"lighting": {"values": []}}))
    assert len(out["options"]) == 20 and writer.calls[-1]["n"] == 20
    assert len(P.store_for(profile).variants(slot(entry, "lighting")["pool"])) == before + 20


async def test_an_adult_pool_never_stands_in_for_a_child_after_an_edit(monkeypatch, profile):
    """`a 30-year-old in <clothing>` edited to `a 10-year-old in <clothing>`: while the new pool is
    written, the adult one doesn't serve (it may hold adult-only clothing); the words stand."""
    reading = {"slots": [{"n": 1, "kind": "list", "label": "Clothing", "lead": " in", "category": "clothing",
                          "list": {"list": "clothing.top", "about": "what they wear"}}], "lists": []}

    class Ages(FakeModel):
        async def __call__(self, messages, project_id, max_tokens):
            user = messages[-1]["content"]
            if user.startswith('The list "Age"'):
                said = user.split('Which of these fit "', 1)[1]
                return json.dumps(["10-year-old"] if said.startswith("a 10") else
                                  ["35-year-old"] if said.startswith("a 35") else ["30-year-old"])
            return await super().__call__(messages, project_id, max_tokens)
    use(monkeypatch, Ages(reading))
    adult = await settled("a 30-year-old in <clothing>", profile)
    old = slot(adult, "clothing")
    assert P.store_for(profile).has(old["pool"]) and "minor" not in adult["seeds"]["clothing"]

    async def hang(*a, **k):   # the new pool isn't written yet
        await asyncio.sleep(3600)
    monkeypatch.setattr(P, "ASK", hang)
    child_prompt = "a 10-year-old in <clothing>"
    await slots.prepare(child_prompt, profile_id=profile, shown=adult["key"])
    await slots.idle()
    child = await slots.prepare(child_prompt, profile_id=profile, start=False, shown=adult["key"])
    s = slot(child, "clothing")
    assert child["seeds"]["clothing"]["minor"] == ["10-year-old"] and s["pool"] != old["pool"]
    assert "stand_in" not in s
    r = prep.realize(child, seed=1, profile_id=profile)
    assert r.prompt.lower() == "a 10-year-old in clothing"
    # an adult edited to another adult keeps drawing from the old pool meanwhile
    other = "a 35-year-old in <clothing>"
    await slots.prepare(other, profile_id=profile, shown=adult["key"])
    await slots.idle()
    again = await slots.prepare(other, profile_id=profile, start=False, shown=adult["key"])
    assert slot(again, "clothing").get("stand_in") == old["pool"]
    for t in list(P.writer_for(profile)._inflight.values()):
        if t is not None:
            t.cancel()


async def test_polling_the_picker_never_asks_a_failing_writer_again(monkeypatch, profile):
    """A pool whose write failed stands as written through /pools polls and prepares; only after a
    while, or an explicit retry, is the model asked again."""
    reading = {"slots": [{"n": 1, "kind": "free", "label": "Room", "lead": "", "category": "room",
                          "free": {"about": "the room", "kinds": ["den"], "instead": [], "lists": []}}], "lists": []}
    failing = FakeWriter(["empty"] * 20)
    use(monkeypatch, FakeModel(reading), failing)
    prompt = "a cozy <room> with a crackling fireplace"
    entry = await settled(prompt, profile)
    assert len(failing.calls) == 2   # the first write, and once more under MIN_POOL
    for _ in range(3):
        pool_view(entry, {}, profile_id=profile)
        await slots.prepare(prompt, profile_id=profile)
        await P.writer_for(profile).drain()
    assert len(failing.calls) == 2
    w = P.writer_for(profile)
    assert w.state(slot(entry, "room")["pool"]) == "as_written"
    await slots.prepare(prompt, profile_id=profile, force=True)   # an explicit retry
    await slots.idle()
    await w.drain()
    assert len(failing.calls) == 4
    monkeypatch.setattr(P, "RETRY_AFTER", 0.0)   # and after a while
    pool_view(entry, {}, profile_id=profile)
    await w.drain()
    assert len(failing.calls) == 6


async def test_a_replay_holds_its_values_though_the_slot_is_not_read_now(monkeypatch, profile):
    """After a reader-cache reset a slot is unread again; a replay's recorded value still holds,
    in the text too."""
    use(monkeypatch)
    entry = await settled(PROMPT, profile)
    kept = {d.id: d.value for d in prep.realize(entry, seed=4, profile_id=profile).draws}
    import copy
    unread = copy.deepcopy(entry)   # as prepare gives it after the reader's cache is reset
    for s in unread["slots"]:
        s["state"] = "reading"
    assert prep.realize(unread, seed=9, profile_id=profile).prompt.lower().startswith("# phone photo")
    r = prep.realize(unread, seed=9, profile_id=profile, fixed=kept)
    for text in kept.values():
        assert text.lower() in r.prompt.lower()
    assert {d.id: d.source for d in r.draws} == {k: "fixed" for k in kept}

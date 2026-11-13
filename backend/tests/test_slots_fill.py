"""Filling slots (fill.py): one image's text drawn segment by segment from the parse, each read
slot taking a variant from its pool (here a pool written straight into a store, no writer) or,
with none, its own words; the user's lists drawn evenly; leads, comment lines, tidying,
articles, [exact text] and the spans of each drawn value."""

import pytest

from prompt_programs import variant_pools as P
from prompt_programs.fill import DrawAborted, fill, tidy_text
from prompt_programs.fluent import Variants
from prompt_programs.slots import compose, parse

PORCH_PROMPT = ("# she is his granddaughter, visiting\n"
                "an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening")
PORCH_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Elderly African man", "lead": "", "category": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "elderly", "descent": "African"},
                "vary": ["age", "descent", "build", "hair", "hair_color", "facial_hair"], "clothes_part": 0,
                "clothes": "", "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "free", "label": "Pet", "lead": " with his", "category": "pet",
     "free": {"about": "his pet, with him on the porch", "kinds": ["ginger tabby cat", "old basset hound", "gray parrot"],
              "instead": ["stack of library books", "mug of coffee", "transistor radio"], "lists": []}},
], "lists": [{"n": 1, "label": "Season"}]}
MEN = ["gaunt elderly African man in a cardigan", "stocky elderly African man with a gray beard",
       "tall elderly African man in reading glasses"]
PETS = ["ginger tabby cat", "old basset hound", "gray parrot", "sleepy tortoise"]

DORM_PROMPT = "dorm room with a <young man>, lit by <light>"
DORM_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Young man", "lead": "", "category": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"},
                "vary": ["age", "descent", "build", "hair", "hair_color"], "clothes_part": 0, "clothes": "",
                "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "light", "label": "Light", "lead": ", lit by", "category": "light",
     "light": {"list": "", "examples": ["warm desk-lamp light", "gray morning light through blinds", "blue screen glow"]}},
]}
LIGHTS = ["amber streetlight through the window", "cold fluorescent tube light", "string lights over the bed"]


def entry_of(prompt, reading, upto=None):
    """The prepared entry for a prompt with these readings (all of them, or the first `upto`)."""
    slots = reading["slots"][:upto] if upto is not None else reading["slots"]
    e = compose(parse(prompt), {r["n"]: r for r in slots}, {r["n"]: r["label"] for r in reading.get("lists") or []})
    e["key"] = "slots-test"
    return e


@pytest.fixture
def store(tmp_path):
    return P.VariantStore(tmp_path / "variants")


def stock(entry, store, pools):
    """Write each slot's pool ({slot id: texts}) into the store, as one first batch."""
    for s in entry["slots"]:
        if s["id"] in pools:
            s["pool"] = P.pool_key("test", s["words"], s["id"], [])
            store.append(s["pool"], {"batch": 0, "role": "first",
                                     "variants": [{"text": t, "seeds": {}} for t in pools[s["id"]]]})
    return entry


def draw(entry, store, seed, *, choices=None, pins=None, edits=None, fixed=None):
    from prompt_programs.choices import expand
    _, _, chosen = expand(entry, choices or {})
    return fill(entry, seed, pins, fixed, edits, options=Variants(store, chosen))


def values(r):
    return {d.id: d.value for d in r.draws}


@pytest.fixture
def porch(store):
    return stock(entry_of(PORCH_PROMPT, PORCH_READING), store, {"elderly_african_man": MEN, "pet": PETS})


@pytest.fixture
def dorm(store):
    return stock(entry_of(DORM_PROMPT, DORM_READING), store, {"light": LIGHTS})


def test_a_slot_is_one_choice_and_a_list_one_pick(porch):
    assert [(c["id"], c["kind"]) for c in porch["choices"]] == [
        ("elderly_african_man", "variants"), ("pet", "variants"), ("list1", "pick")]
    assert porch["choices"][2]["label"] == "Season" and porch["choices"][2]["options"] == ["summer", "autumn"]
    slots = {s["id"]: s for s in porch["slots"]}
    assert slots["pet"]["line"] == 2 and slots["pet"]["state"] == "ready" and slots["pet"]["lead"] == " with his"
    assert PORCH_PROMPT[slots["pet"]["span"][0]:slots["pet"]["span"][1]] == "<pet>"
    assert slots["elderly_african_man"]["stated"] == {"age": "elderly", "descent": "African"}
    assert porch["template"].split("\n")[1] == "An [Elderly African man] reading on a porch with his [Pet], [Season] evening"


def test_each_slot_draws_a_variant_and_each_list_an_item(porch, store):
    results = [draw(porch, store, s) for s in range(12)]
    assert len({r.prompt for r in results}) > 4
    for r in results:
        got = values(r)
        assert got["elderly_african_man"] in MEN and got["pet"] in PETS and got["list1"] in ("summer", "autumn")
        first, second = r.prompt.split("\n")
        assert first == "# she is his granddaughter, visiting"
        assert second == f"A {got['elderly_african_man']} reading on a porch with his {got['pet']}, {got['list1']} evening"
        assert {d.source for d in r.draws} == {"variant", "list"} and not r.more_coming
        assert r.revision["engine"] == "variants-1" and set(r.revision["variants"]) == {"elderly_african_man", "pet", "list1"}


def test_the_same_seed_draws_the_same_text(porch, store):
    assert draw(porch, store, 7).prompt == draw(porch, store, 7).prompt


def test_a_slot_with_no_pool_yet_goes_in_as_its_words(store):
    e = stock(entry_of(PORCH_PROMPT, PORCH_READING), store, {"pet": PETS})
    for s in range(5):
        r = draw(e, store, s)
        man = next(d for d in r.draws if d.id == "elderly_african_man")
        assert man.value == "elderly African man" and man.source == "words" and r.more_coming == ["elderly_african_man"]
        assert r.prompt.split("\n")[1].startswith("An elderly African man reading on a porch with his ")


def test_leaving_a_slot_out_takes_its_lead(dorm, porch, store):
    lit = draw(dorm, store, 3, choices={"light": {"off": True}}).prompt
    assert lit == "Dorm room with a young man" and "light" not in values(draw(dorm, store, 3, edits={"light": {"off": True}}))
    pet = draw(porch, store, 3, choices={"pet": {"off": True}}).prompt
    assert pet.endswith(("reading on a porch, summer evening", "reading on a porch, autumn evening")), pet


def test_a_lead_without_its_comma_leaves_nothing_hanging(store):
    reading = {"slots": [DORM_READING["slots"][0], {**DORM_READING["slots"][1], "lead": "lit by"}]}
    e = stock(entry_of(DORM_PROMPT, reading), store, {"light": LIGHTS})
    got = draw(e, store, 3, choices={"light": {"off": True}}).prompt
    assert got == "Dorm room with a young man" and got == tidy_text([got])


def test_a_lead_that_isnt_in_the_text_stays_text(store):
    reading = {"slots": [{"n": 1, "kind": "camera", "label": "Camera", "lead": ", filmed with", "category": "",
                          "camera": {"vary": ["shot_size", "lens"]}}]}
    e = stock(entry_of("a kitchen, shot on <camera>", reading), store, {"camera": ["a 35mm lens"]})
    assert draw(e, store, 1).prompt == "A kitchen, shot on a 35mm lens"
    assert draw(e, store, 1, choices={"camera": {"off": True}}).prompt == "A kitchen, shot on"


def test_pinned_variants_draw_among_themselves_and_one_not_in_the_pool_holds(porch, store):
    two = PETS[:2]
    for s in range(6):
        d = next(d for d in draw(porch, store, s, choices={"pet": {"values": two}}).draws if d.id == "pet")
        assert d.value in two and d.pinned and d.source == "pinned"
    r = draw(porch, store, 1, choices={"pet": {"values": ["three-legged greyhound"]}})
    assert values(r)["pet"] == "three-legged greyhound" and "with his three-legged greyhound," in r.prompt


def test_the_users_own_variant_is_drawn_with_the_pool(porch, store):
    got = {}
    for s in range(40):
        d = next(d for d in draw(porch, store, s, choices={"pet#add": ["box of kittens"]}).draws if d.id == "pet")
        got[d.value] = d
    assert set(got) == {*PETS, "box of kittens"} and got["box of kittens"].own and got["box of kittens"].source == "own"


def test_as_written_is_the_slots_own_words(porch, store):
    r = draw(porch, store, 2, choices={"elderly_african_man": {"as_written": True}, "pet": {"as_written": True}})
    assert r.prompt.split("\n")[1].startswith("An elderly African man reading on a porch with his pet, ")
    assert {d.id: d.source for d in r.draws if d.id != "list1"} == {"elderly_african_man": "words", "pet": "words"}


def test_a_held_value_comes_back_exactly(porch, store):
    first = values(draw(porch, store, 3))
    again = draw(porch, store, 11, fixed={k: first[k] for k in ("pet", "list1")})
    assert values(again)["pet"] == first["pet"] and values(again)["list1"] == first["list1"]
    assert next(d for d in again.draws if d.id == "pet").source == "fixed"


def test_a_slot_whose_variants_are_all_removed_goes_in_as_its_words(porch, store):
    r = draw(porch, store, 4, edits={"pet": {"remove": PETS}})
    d = next(d for d in r.draws if d.id == "pet")
    assert d.value == "pet" and d.source == "words" and "with his pet," in r.prompt


def test_a_user_list_pins_adds_removes_and_goes_off(porch, store):
    assert {values(draw(porch, store, s, pins={"list1": ["autumn"]}))["list1"] for s in range(6)} == {"autumn"}
    added = {values(draw(porch, store, s, edits={"list1": {"add": ["winter"]}}))["list1"] for s in range(40)}
    assert added == {"summer", "autumn", "winter"}
    assert {values(draw(porch, store, s, edits={"list1": {"remove": ["summer"]}}))["list1"] for s in range(8)} == {"autumn"}
    off = draw(porch, store, 1, edits={"list1": {"off": True}})
    assert "list1" not in values(off) and off.prompt.endswith("evening") and "summer" not in off.prompt
    with pytest.raises(DrawAborted, match="Nothing left to draw for Season"):
        draw(porch, store, 1, edits={"list1": {"remove": ["summer", "autumn"]}})


def test_a_user_list_draws_evenly(porch, store):
    from collections import Counter
    got = Counter(values(draw(porch, store, s))["list1"] for s in range(400))
    assert abs(got["summer"] - got["autumn"]) < 80


def test_the_same_words_twice_are_two_slots_with_two_pools(store):
    r = {"kind": "person", "label": "Friend", "lead": "", "category": "",
         "person": {"noun": "friend", "presentation": "", "stated": {}, "clothes_part": 0, "clothes": "", "outfit": ""}}
    e = entry_of("<friend> laughing with <friend>", {"slots": [{**r, "n": 1}, {**r, "n": 2}]})
    assert [s["id"] for s in e["slots"]] == ["friend", "friend_2"]
    stock(e, store, {"friend": ["tall friend"], "friend_2": ["short friend"]})
    assert draw(e, store, 4).prompt == "Tall friend laughing with short friend"


def test_a_slot_not_read_yet_stands_as_its_words(store):
    e = entry_of(PORCH_PROMPT, PORCH_READING, upto=1)
    stock(e, store, {"elderly_african_man": MEN})
    assert [s["state"] for s in e["slots"]] == ["ready", "reading"] and e["lists"][0]["state"] == "ready"
    for s in range(5):
        r = draw(e, store, s)
        assert "reading on a porch with his pet," in r.prompt and "pet" not in values(r)
    bare = compose(parse(PORCH_PROMPT), {}, {})
    assert bare["lists"][0]["state"] == "reading"
    assert fill(bare, 0).prompt.split("\n")[1] in (
        "An elderly African man reading on a porch with his pet, summer evening",
        "An elderly African man reading on a porch with his pet, autumn evening")


def test_a_reading_read_as_written_stands_as_its_words():
    e = compose(parse("a <pet> on a rug"), {1: {"n": 1, "kind": "free", "label": "pet", "lead": "", "degraded": True,
                                                "free": {"about": "pet", "lists": []}}}, {})
    assert e["slots"][0]["degraded"] and fill(e, 0).prompt == "A pet on a rug" and fill(e, 0).draws == []


def test_a_reading_that_names_a_list_there_isnt_stands_as_its_words():
    e = compose(parse("a <thing>"), {1: {"n": 1, "kind": "list", "label": "Thing", "lead": "",
                                         "list": {"list": "no.such.list", "about": ""}}}, {})
    assert e["slots"][0]["degraded"] and fill(e, 0).prompt == "A thing"


def test_articles_follow_the_variant_and_a_doubled_one_goes(store):
    reading = {"slots": [{"n": 1, "kind": "free", "label": "Coat", "lead": "", "category": "coat",
                          "free": {"about": "her coat", "lists": []}}]}
    e = stock(entry_of("a woman in a <coat>", reading), store, {"coat": ["olive trench coat"]})
    assert draw(e, store, 0).prompt == "A woman in an olive trench coat"
    e = stock(entry_of("a woman in a <coat>", reading), store, {"coat": ["a long wool coat"]})
    assert draw(e, store, 0).prompt == "A woman in a long wool coat"


def test_spans_say_where_each_drawn_value_stands(store):
    from prompt_programs.program import mask_exact, realize
    masked, exact = mask_exact(PORCH_PROMPT.replace("evening", "evening, [Kodak Portra 400]"))
    e = stock(entry_of(masked, PORCH_READING), store, {"elderly_african_man": MEN, "pet": PETS})
    e["exact"] = exact
    for seed in range(8):
        r = realize(e, seed=seed, runtime=Variants(store))
        drawn = {d.id: str(d.value) for d in r.draws}
        ids = [cid for _, _, cid in r.spans]
        assert ids == ["elderly_african_man", "pet", "list1"]
        for start, end, cid in r.spans:
            assert r.prompt[start:end].lower() in (drawn[cid].lower(), tidy_text([drawn[cid]]).lower())
        assert "[Kodak Portra 400]" in r.prompt

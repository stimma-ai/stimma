"""Filling slots straight from their readings (fill.py): the picks a reading makes, and one
image's text drawn segment by segment, through the options service that reads the
vocabulary lists (runtime_for(entry, store=None, mine={}))."""

import json
import re
from typing import Any, Dict, Optional

import pytest

from prompt_programs.fill import fill, tidy_text
from prompt_programs.fluent import runtime_for
from prompt_programs.slots import compose, parse
from prompt_programs.vocab import vocabulary

DORM_PROMPT = "dorm room with a <young man>, lit by <light>"
DORM_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Young man", "lead": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"},
                "vary": ["age", "descent", "build", "hair", "hair_color"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "light", "label": "Light", "lead": ", lit by",
     "light": {"examples": ["warm desk-lamp light", "grey morning light through blinds", "blue screen glow"]}},
]}

PORCH_PROMPT = ("# she is his granddaughter, visiting\n"
                "an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening")
PORCH_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Elderly African man", "lead": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "elderly", "descent": "African"},
                "vary": ["age", "descent", "build", "hair", "hair_color", "facial_hair"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "free", "label": "Pet", "lead": " with his",
     "free": {"about": "his pet, with him on the porch", "kinds": ["ginger tabby cat", "old basset hound", "grey parrot"],
              "instead": ["stack of library books", "mug of coffee", "transistor radio"]}},
], "lists": [{"n": 1, "label": "Season"}]}

CAMERA_PROMPT = "a kitchen, shot on <camera>"
CAMERA_READING = {"slots": [{"n": 1, "kind": "camera", "label": "Camera", "lead": ", filmed with",
                             "camera": {"vary": ["shot_size", "lens"]}}]}

ELDERLY = ["71-year-old", "74-year-old", "79-year-old"]
AFRICAN = ["Kenyan", "Ghanaian"]


def entry_of(prompt: str, reading: Dict[str, Any], filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    e = compose(parse(prompt), {r["n"]: r for r in reading["slots"]},
                {r["n"]: r["label"] for r in reading.get("lists") or []})
    e["key"] = "slots-test"
    if filters:
        e["filters"] = filters
    return e


def draw(entry: Dict[str, Any], seed: int, pins=None, edits: Optional[Dict[str, Any]] = None, zones=None, fixed=None):
    rt = runtime_for(entry, store=None, mine={}, edits=edits, zones=zones)
    return fill(entry, seed, pins, fixed, edits, options=rt.options)


def values(r) -> Dict[str, Any]:
    return {d.id: d.value for d in r.draws}


@pytest.fixture(scope="module")
def dorm():
    return entry_of(DORM_PROMPT, DORM_READING)


@pytest.fixture(scope="module")
def porch():
    return entry_of(PORCH_PROMPT, PORCH_READING, {"elderly_african_man.age": ELDERLY,
                                                   "elderly_african_man.descent": AFRICAN})


def test_a_reading_makes_its_picks_and_choices(dorm, porch):
    assert [c["id"] for c in dorm["choices"]] == [
        "young_man.build", "young_man.age", "young_man.descent", "young_man.hair", "young_man.hair_color",
        "young_man.outfit", "young_man.outfit.colors", "light"]
    assert next(c for c in porch["choices"] if c["id"] == "list1")["label"] == "Season"
    slots = {s["id"]: s for s in porch["slots"]}
    assert slots["pet"]["details"] == ["pet"] and slots["pet"]["line"] == 2 and slots["pet"]["state"] == "ready"
    assert PORCH_PROMPT[slots["pet"]["span"][0]:slots["pet"]["span"][1]] == "<pet>"
    assert slots["elderly_african_man"]["stated"] == {"age": "elderly", "descent": "African"}
    assert porch["slot_words"] == {"elderly_african_man.age": "elderly", "elderly_african_man.descent": "African",
                                   "pet": "pet"}
    assert porch["template"].split("\n")[1] == (
        "An [Build] [Age] [Ethnicity] man with [Hair] [Hair color] hair, [Facial hair], wearing [Outfit], "
        "reading on a porch with his [Pet], [Season] evening")


def test_draws_vary_within_the_narrowed_lists(porch):
    results = [draw(porch, 500 + s) for s in range(20)]
    assert len({r.prompt for r in results}) > 10
    for r in results:
        got = values(r)
        assert got["elderly_african_man.age"] in ELDERLY and got["elderly_african_man.descent"] in AFRICAN
        assert r.prompt.split("\n")[0] == "# she is his granddaughter, visiting"
        assert got["pet"] in PORCH_READING["slots"][1]["free"]["kinds"]
        assert r.prompt.endswith(f"porch with his {got['pet']}, {got['list1']} evening")


def test_the_same_seed_draws_the_same_text(porch):
    assert draw(porch, 7).prompt == draw(porch, 7).prompt


def test_leaving_a_slot_out_takes_its_lead(dorm, porch):
    lit = draw(dorm, 3, edits={"light": {"off": True}}).prompt
    assert "lit by" not in lit and not lit.rstrip(".").endswith(",")
    worn = draw(dorm, 3, edits={"young_man.outfit": {"off": True}}).prompt
    assert "wearing" not in worn and ", lit by" in worn
    pet = draw(porch, 3, edits={"pet": {"off": True}}).prompt
    assert "with his" not in pet and pet.endswith("reading on a porch, summer evening") or \
        pet.endswith("reading on a porch, autumn evening")


def test_a_detail_off_takes_its_joiners(dorm):
    no_hair = draw(dorm, 5, edits={"young_man.hair": {"off": True}, "young_man.hair_color": {"off": True}}).prompt
    assert no_hair.split(" man", 1)[1].startswith(", wearing") and "hair" not in no_hair
    color_only = draw(dorm, 5, edits={"young_man.hair": {"off": True}})
    assert f"man with {values(color_only)['young_man.hair_color']} hair, wearing" in color_only.prompt


def test_a_pin_holds_and_ticks_draw_among_themselves(porch, dorm):
    for s in range(4):
        assert "70-year-old" in draw(porch, 200 + s, pins={"elderly_african_man.age": ["70-year-old"]}).prompt
    ticked = {"short wavy", "long straight"}
    hair = vocabulary().get("person.hair_length_texture").values
    ticked = {v.text for v in hair[:2]}
    for s in range(6):
        assert values(draw(dorm, s, pins={"young_man.hair": sorted(ticked)}))["young_man.hair"] in ticked


def test_a_pin_the_list_doesnt_have_is_drawn_as_the_users_own(dorm):
    r = draw(dorm, 1, pins={"young_man.hair": ["electric blue mohawk"]})
    d = next(d for d in r.draws if d.id == "young_man.hair")
    assert d.value == "electric blue mohawk" and d.pinned and d.own


def test_an_outfit_records_its_template_and_reads_as_the_prompt_shows_it(porch):
    seen = 0
    for s in range(40):
        r = draw(porch, 900 + s)
        for d in r.draws:
            if d.template:
                seen += 1
                assert "{" in d.template and "{" not in d.value and d.value in r.prompt
                assert next(x for x in r.draws if x.id == d.id + ".colors").follows == d.id
    assert seen


def test_colors_off_reads_the_look_without_them(porch):
    for s in range(10):
        r = draw(porch, s, edits={"elderly_african_man.outfit.colors": {"off": True}})
        assert "{" not in r.prompt and "elderly_african_man.outfit.colors" not in values(r)


def test_a_kept_look_comes_back_with_its_colors(porch):
    first = draw(porch, 3)
    look = values(first)["elderly_african_man.outfit"]
    again = draw(porch, 11, fixed={"elderly_african_man.outfit": look})
    assert values(again)["elderly_african_man.outfit"] == look


def test_a_comment_line_keeps_its_line(porch):
    first, second = draw(porch, 9).prompt.split("\n")
    assert first == "# she is his granddaughter, visiting" and second.startswith(("An ", "A "))


def test_a_free_slot_draws_its_kinds_unless_other_zones_are_chosen(porch):
    kinds = set(PORCH_READING["slots"][1]["free"]["kinds"])
    instead = set(PORCH_READING["slots"][1]["free"]["instead"])
    assert {values(draw(porch, s))["pet"] for s in range(12)} <= kinds
    both = {values(draw(porch, s, zones={"pet": ["kinds", "instead"]}))["pet"] for s in range(30)}
    assert both & instead and both & kinds


def test_a_free_slot_as_written_is_a_pin_of_its_words(porch):
    assert "pet" not in {values(draw(porch, s))["pet"] for s in range(12)}
    assert "porch with his pet," in draw(porch, 3, pins={"pet": ["pet"]}).prompt


def test_a_person_as_written_is_the_slots_own_words(porch):
    mine = [c["id"] for c in porch["choices"] if c["id"].startswith("elderly_african_man.")]
    details = [d for d in mine if ".outfit" not in d]
    worn = draw(porch, 2, edits={d: {"off": True} for d in details}).prompt.split("\n")[-1]
    assert worn.startswith("An elderly African man, wearing "), worn
    bare = draw(porch, 2, edits={d: {"off": True} for d in mine}).prompt.split("\n")[-1]
    assert bare.startswith("An elderly African man reading on a porch with his "), bare
    aged = draw(porch, 2, edits={d: {"off": True} for d in details if not d.endswith(".age")}).prompt
    assert re.search(r"An? \d+-year-old man, wearing", aged), aged


def test_the_same_words_twice_are_two_people():
    r = {"kind": "person", "label": "Friend", "lead": "",
         "person": {"noun": "friend", "presentation": "", "stated": {}, "vary": ["age", "hair"], "outfit": ""}}
    e = entry_of("<friend> laughing with <friend>", {"slots": [{**r, "n": 1}, {**r, "n": 2}]})
    assert {"friend.age", "friend.hair", "friend_2.age", "friend_2.hair"} <= {c["id"] for c in e["choices"]}
    assert [s["id"] for s in e["slots"]] == ["friend", "friend_2"]
    got = values(draw(e, 4))
    assert got["friend.age"] and got["friend_2.age"]


def test_a_camera_is_one_group_and_a_lead_that_isnt_there_stays_text():
    e = entry_of(CAMERA_PROMPT, CAMERA_READING)
    off = draw(e, 1, edits={"camera.shot_size": {"off": True}}).prompt
    assert off.startswith("A kitchen, shot on ") and ", ," not in off and "on," not in off
    both = draw(e, 1).prompt
    got = values(draw(e, 1))
    assert both == f"A kitchen, shot on {got['camera.shot_size']}, {got['camera.lens']}"


def test_a_slot_not_read_yet_stands_as_its_words():
    parsed = parse(PORCH_PROMPT)
    e = compose(parsed, {1: PORCH_READING["slots"][0]}, {})
    assert [s["state"] for s in e["slots"]] == ["ready", "reading"] and e["lists"][0]["state"] == "reading"
    for s in range(5):
        r = draw(e, s)
        assert "reading on a porch with his pet," in r.prompt and "pet" not in values(r)
    bare = compose(parsed, {}, {})
    assert draw(bare, 0).prompt.split("\n")[1] in (
        "An elderly African man reading on a porch with his pet, summer evening",
        "An elderly African man reading on a porch with his pet, autumn evening")


def test_a_reading_read_as_written_stands_as_its_words():
    e = compose(parse("a <pet> on a rug"), {1: {"n": 1, "kind": "free", "label": "pet", "lead": "", "degraded": True,
                                                "free": {"about": "pet", "kinds": ["pet"], "instead": []}}}, {})
    assert e["slots"][0]["degraded"] and e["picks"] == []
    assert draw(e, 0).prompt == "A pet on a rug"


def test_a_reading_the_picks_cant_be_made_from_stands_as_its_words():
    e = compose(parse("a <thing>"), {1: {"n": 1, "kind": "list", "label": "Thing", "lead": "",
                                         "list": {"list": "no.such.list", "about": ""}}}, {})
    assert e["slots"][0]["degraded"] and draw(e, 0).prompt == "A thing"


def test_spans_say_where_each_drawn_value_stands():
    from prompt_programs.program import mask_exact, realize
    masked, exact = mask_exact(PORCH_PROMPT.replace("evening", "evening, [Kodak Portra 400]"))
    e = entry_of(masked, PORCH_READING)
    e["exact"] = exact
    for seed in range(8):
        r = realize(e, seed=seed, runtime=runtime_for(e, store=None, mine={}))
        drawn = {d.id: str(d.value) for d in r.draws if d.value is not None}
        ids = [cid for _, _, cid in r.spans]
        assert {"elderly_african_man.age", "elderly_african_man.descent", "pet", "list1"} <= set(ids)
        assert len(ids) == len(set(ids))
        for start, end, cid in r.spans:
            assert r.prompt[start:end].lower() in (drawn[cid].lower(), tidy_text([drawn[cid]]).lower())
        assert "[Kodak Portra 400]" in r.prompt


# --------------------------------------------------------------------------- parity with the old engine

@pytest.mark.parametrize("prompt,reading", [
    (PORCH_PROMPT, PORCH_READING), (DORM_PROMPT, DORM_READING), (CAMERA_PROMPT, CAMERA_READING),
    ("1girl, <hairstyle>, <outfit>, beach", {"slots": [
        {"n": 1, "kind": "list", "label": "Hairstyle", "lead": ",",
         "list": {"list": "person.hairstyle", "about": "the girl's hairstyle"}},
        {"n": 2, "kind": "list", "label": "Outfit", "lead": ",",
         "list": {"list": "person.outfit.summer", "about": "the girl's outfit"}}]}),
])
def test_the_fill_draws_what_the_program_drew(prompt, reading):
    """The same seed, pins and edits draw exactly the text and values the generated program drew."""
    from prompt_programs.draws import draw as program_draw
    from prompt_programs.slots import build
    old = build(parse(prompt), reading)[1]
    new = entry_of(prompt, reading)
    variants = [{}, {"edits": {"light": {"off": True}}}, {"edits": {"pet": {"off": True}}},
                {"pins": {"elderly_african_man.age": ["70-year-old"]}}, {"zones": {"pet": ["kinds", "instead"]}},
                {"edits": {"young_man.hair": {"off": True}}}, {"edits": {"camera.shot_size": {"off": True}}},
                {"edits": {"elderly_african_man.outfit.colors": {"off": True}}}]
    for v in variants:
        for seed in range(10):
            ro = runtime_for(old, store=None, mine={}, edits=v.get("edits"), zones=v.get("zones"))
            a = program_draw(old["program"], seed, v.get("pins"), None, None, None, v.get("edits"), options=ro.options)
            b = draw(new, seed, v.get("pins"), v.get("edits"), v.get("zones"))
            assert b.prompt == a.prompt, (v, seed)
            assert [(d.id, d.value, d.template) for d in b.draws] == [(d.id, d.value, d.template) for d in a.draws]

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
     "light": {"examples": ["warm desk-lamp light", "gray morning light through blinds", "blue screen glow"]}},
]}

PORCH_PROMPT = ("# she is his granddaughter, visiting\n"
                "an <elderly African man> reading on a porch with his <pet>, {summer|autumn} evening")
PORCH_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Elderly African man", "lead": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "elderly", "descent": "African"},
                "vary": ["age", "descent", "build", "hair", "hair_color", "facial_hair"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "free", "label": "Pet", "lead": " with his",
     "free": {"about": "his pet, with him on the porch", "kinds": ["ginger tabby cat", "old basset hound", "gray parrot"],
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
        "young_man.build", "young_man.age", "young_man.descent", "young_man.hair", "young_man.hair_texture",
        "young_man.hair_color", "young_man.hairstyle", "young_man.facial_hair", "young_man.face", "young_man.outfit",
        "young_man.outfit.colors", "light"]
    assert next(c for c in porch["choices"] if c["id"] == "list1")["label"] == "Season"
    slots = {s["id"]: s for s in porch["slots"]}
    assert slots["pet"]["details"] == ["pet"] and slots["pet"]["line"] == 2 and slots["pet"]["state"] == "ready"
    assert PORCH_PROMPT[slots["pet"]["span"][0]:slots["pet"]["span"][1]] == "<pet>"
    assert slots["elderly_african_man"]["stated"] == {"age": "elderly", "descent": "African"}
    assert porch["slot_words"] == {"elderly_african_man.age": "elderly", "elderly_african_man.descent": "African",
                                   "pet": "pet"}
    assert porch["template"].split("\n")[1] == (
        "An [Build] [Age] [Ethnicity] man with [Hair length] [Hair texture] [Hair color] hair and [Facial hair], wearing [Outfit], "
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
    no_hair = draw(dorm, 5, edits={"young_man.hair": {"off": True}, "young_man.hair_texture": {"off": True},
                                   "young_man.hair_color": {"off": True}, "young_man.facial_hair": {"off": True}}).prompt
    assert no_hair.split(" man", 1)[1].startswith(", wearing") and "hair" not in no_hair
    color_only = draw(dorm, 5, edits={"young_man.hair": {"off": True}, "young_man.hair_texture": {"off": True},
                                      "young_man.facial_hair": {"off": True}})
    assert f"man with {values(color_only)['young_man.hair_color']} hair, wearing" in color_only.prompt


def test_a_pin_holds_and_ticks_draw_among_themselves(porch, dorm):
    for s in range(4):
        assert "70-year-old" in draw(porch, 200 + s, pins={"elderly_african_man.age": ["70-year-old"]}).prompt
    hair = vocabulary().get("person.hair_length").values
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


KITCHEN_PROMPT = "A <young woman> in a kitchen at <time of day>"
KITCHEN_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Young woman", "lead": "",
     "person": {"noun": "woman", "presentation": "feminine", "stated": {"age": "young"},
                "vary": ["age", "descent", "build", "skin", "hair", "hair_color", "eyes"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "free", "label": "Time of day", "lead": " at",
     "free": {"about": "the time of day", "kinds": ["dawn", "noon", "dusk"], "instead": []}},
]}
YOUNG = [f"{a}-year-old" for a in range(20, 30)]


def test_face_detail_starts_left_out_and_turns_on_when_chosen():
    e = entry_of(KITCHEN_PROMPT, KITCHEN_READING, {"young_woman.age": YOUNG})
    face = next(c for c in e["choices"] if c["id"] == "young_woman.face")
    assert face["starts_off"] and "young_woman.face" in e["slots"][0]["details"]
    assert all("young_woman.face" not in values(draw(e, s)) for s in range(10))
    on = draw(e, 3, edits={"young_woman.face": {"on": True}})
    assert values(on).get("young_woman.face") and values(on)["young_woman.face"] in on.prompt
    picked = next(iter(face["options"]))
    assert values(draw(e, 3, pins={"young_woman.face": [picked]}))["young_woman.face"] == picked
    asked = {**KITCHEN_READING["slots"][0], "person": {**KITCHEN_READING["slots"][0]["person"],
                                                       "vary": ["age", "hair", "face"]}}
    e2 = entry_of(KITCHEN_PROMPT, {"slots": [asked, KITCHEN_READING["slots"][1]]})
    assert not next(c for c in e2["choices"] if c["id"] == "young_woman.face").get("starts_off")
    assert values(draw(e2, 1)).get("young_woman.face")


def test_an_open_face_is_one_subtle_piece_and_ticked_pieces_of_different_parts_go_in_together():
    e = entry_of(KITCHEN_PROMPT, KITCHEN_READING, {"young_woman.age": YOUNG})
    face = vocabulary().get("person.face")
    for s in range(30):
        got = values(draw(e, s, edits={"young_woman.face": {"on": True}}))["young_woman.face"]
        assert face.value(got) is not None and face.value(got).strength == 1, got
    nose = next(v.text for v in face.values if v.tags["piece"] == ["nose"] and v.strength == 1)
    freckles = next(v.text for v in face.values if v.tags["piece"] == ["skin_marks"] and v.strength == 2)
    r = draw(e, 2, pins={"young_woman.face": [freckles, nose]})
    assert values(r)["young_woman.face"] == f"{nose}, {freckles}" and f"{nose}, {freckles}" in r.prompt
    noses = [v.text for v in face.values if v.tags["piece"] == ["nose"]][:2]
    assert {values(draw(e, s, pins={"young_woman.face": noses}))["young_woman.face"] for s in range(12)} <= set(noses)


def test_a_hairstyle_starts_left_out_and_follows_the_hair_length():
    e = entry_of(KITCHEN_PROMPT, KITCHEN_READING, {"young_woman.age": YOUNG})
    style = next(c for c in e["choices"] if c["id"] == "young_woman.hairstyle")
    assert style["starts_off"] and all("young_woman.hairstyle" not in values(draw(e, s)) for s in range(10))
    leaf = vocabulary().get("person.hairstyle")
    for s in range(40):
        got = values(draw(e, s, pins={"young_woman.hair": ["buzzed"]}, edits={"young_woman.hairstyle": {"on": True}}))
        assert "short" in leaf.value(got["young_woman.hairstyle"]).tags["hair_length"], got


def test_a_young_persons_hair_fits_their_age():
    e = entry_of(KITCHEN_PROMPT, KITCHEN_READING, {"young_woman.age": YOUNG})
    for s in range(300):
        assert values(draw(e, s))["young_woman.hair"] not in ("thinning", "sparse")


def test_the_person_reads_as_one_clean_phrase_whatever_is_on():
    from itertools import product
    from prompt_programs.fill import DETAILS
    reading = {**KITCHEN_READING["slots"][0], "person": {**KITCHEN_READING["slots"][0]["person"],
                                                         "vary": list(DETAILS)}}
    e = entry_of(KITCHEN_PROMPT, {"slots": [reading, KITCHEN_READING["slots"][1]]}, {"young_woman.age": YOUNG})
    ids = [c["id"] for c in e["choices"] if c["id"].startswith("young_woman.") and not c["id"].endswith(".colors")]
    # Values with no joiners of their own, so every joiner in the text is the fill's.
    simple = {"build": "slender", "age": "24-year-old", "descent": "Korean", "skin": "fair", "hair": "short",
              "hair_texture": "straight", "hair_color": "black", "hairstyle": "a pixie cut", "eyes": "hazel",
              "face": "a small nose", "outfit": "a navy coat"}
    hairs = ("hair", "hair_texture", "hair_color", "hairstyle")
    said = {"skin": "fair skin", "hair": "HAIR", "eyes": "hazel eyes", "face": "a small nose"}
    pins = {cid: [simple[cid.split(".", 1)[1]]] for cid in ids}
    for on in product((True, False), repeat=len(ids)):
        off = {cid: {"off": True} for cid, keep in zip(ids, on) if not keep}
        got = draw(e, 1, pins={k: v for k, v in pins.items() if k not in off}, edits=off).prompt
        kept = {cid.split(".", 1)[1] for cid, keep in zip(ids, on) if keep}
        before = " ".join(simple[k] for k in ("build", "age", "descent") if k in kept)
        details = [said[k] for k in ("skin", "hair", "eyes", "face") if k in kept or (k == "hair" and set(hairs) & kept)]
        if set(hairs) & kept:
            hair = " ".join(simple[k] for k in hairs[:3] if k in kept) + " hair"
            hair = hair.strip() + (" in " + simple["hairstyle"] if "hairstyle" in kept else "")
            details[details.index("HAIR")] = hair
        listed = (", ".join(details[:-1]) + " and " + details[-1]) if len(details) > 1 else "".join(details)
        person = " ".join(x for x in (before, "woman" if before or details else "young woman") if x)
        if details:
            person += " with " + listed
        if "outfit" in kept:
            person += ", wearing a navy coat"
        want = f"{person}{',' if details or 'outfit' in kept else ''} in a kitchen at "
        assert got.startswith(("A " + want, "An " + want)), (on, got)
    for s in range(200):
        r = draw(e, s, edits={d: {"on": True} for d in ids})
        got = r.prompt
        for a, b, _ in reversed(r.spans):   # the joiners are checked, not the values' own words
            got = got[:a] + "X" + got[b:]
        assert ", with" not in got and ", and" not in got and "  " not in got and ", ," not in got, got
        assert not re.search(r"\b(with|and|wearing),", got) and not re.search(r"\b(with|and) (with|and)\b", got), got


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


PET = {"n": 1, "kind": "animal", "label": "Pet", "lead": " with his",
       "animal": {"noun": "pet", "vary": ["species", "life_stage"], "breed": "", "stated": {}}}
DOG = {"n": 1, "kind": "animal", "label": "Dog", "lead": "",
       "animal": {"noun": "dog", "vary": ["breed", "life_stage"], "breed": "animal.dog_breed", "stated": {}}}


def test_an_animal_is_its_life_stage_and_its_kind_narrowed_by_the_slots_words():
    pets = ["cat", "dog", "rabbit"]
    e = entry_of("an old man with his <pet> on a porch", {"slots": [PET]}, {"pet.species": pets})
    assert [c["id"] for c in e["choices"]] == ["pet.species", "pet.life_stage"]
    assert e["slot_words"] == {"pet.species": "pet"} and e["slots"][0]["kind"] == "animal"
    stages = {v.text for v in vocabulary().get("animal.life_stage").values}
    assert stages == {"baby", "juvenile", "adult", "elderly"}
    for s in range(12):
        got = values(draw(e, s))
        assert got["pet.species"] in pets and got["pet.life_stage"] in stages
        assert draw(e, s).prompt == f"An old man with his {got['pet.life_stage']} {got['pet.species']} on a porch"
    off = draw(e, 1, edits={"pet.species": {"off": True}, "pet.life_stage": {"off": True}}).prompt
    assert off == "An old man with his pet on a porch"


def test_an_animal_of_one_kind_draws_its_breed():
    e = entry_of("a <dog> in a park", {"slots": [DOG]})
    breeds = {v.text for v in vocabulary().get("animal.dog_breed").values}
    for s in range(8):
        got = values(draw(e, s))
        assert got["dog.breed"] in breeds and draw(e, s).prompt.endswith(f"{got['dog.breed']} in a park")
    no_breed = draw(e, 2, edits={"dog.breed": {"off": True}}).prompt
    assert no_breed.endswith(" dog in a park")


def test_light_is_one_named_look_from_a_lighting_list_or_its_examples():
    bound = {"n": 1, "kind": "light", "label": "Light", "lead": ", lit by",
             "light": {"list": "lighting.studio", "examples": []}}
    e = entry_of("a portrait, lit by <light>", {"slots": [bound]})
    assert [c["id"] for c in e["choices"]] == ["light"] and e["choices"][0]["cls"] == "lighting.studio"
    looks = {v.text for v in vocabulary().get("lighting.studio").values}
    assert {values(draw(e, s))["light"] for s in range(10)} <= looks
    written = entry_of(DORM_PROMPT, DORM_READING)
    assert {values(draw(written, s))["light"] for s in range(10)} <= set(DORM_READING["slots"][1]["light"]["examples"])


async def test_an_age_is_narrowed_by_the_slots_words_and_kept_across_an_edit_elsewhere(tmp_path):
    from prompt_programs.narrow import NarrowCache, narrow_entry
    asked = []

    async def ask(messages, project_id, tokens):
        user = messages[-1]["content"]
        asked.append(user)
        if "the woman's age" in user:
            return json.dumps(YOUNG)
        return '["ALL"]'

    cache = NarrowCache(tmp_path)
    e = entry_of(KITCHEN_PROMPT, KITCHEN_READING)
    await narrow_entry(e, cache, ask)
    ages = [m for m in asked if "the woman's age" in m]
    assert len(ages) == 1 and 'fit "young woman"' in ages[0] and KITCHEN_PROMPT in ages[0]
    assert e["filters"]["young_woman.age"] == YOUNG
    # Another line edited: the age is read in its own line and the notes, so nothing is asked again.
    asked.clear()
    e2 = entry_of(KITCHEN_PROMPT + "\nshe is cooking pasta, steam rising", KITCHEN_READING)
    await narrow_entry(e2, cache, ask)
    assert not [m for m in asked if "the woman's age" in m] and e2["filters"]["young_woman.age"] == YOUNG
    # A note is read with it: a new one asks again.
    e3 = entry_of("# she is a student\n" + KITCHEN_PROMPT, KITCHEN_READING)
    await narrow_entry(e3, cache, ask)
    assert [m for m in asked if "the woman's age" in m and "# she is a student" in m]
    # Cache only (what a generation reads) finds it too.
    e4 = entry_of(KITCHEN_PROMPT + "\nwide shot", KITCHEN_READING)
    await narrow_entry(e4, cache, None)
    assert e4["filters"]["young_woman.age"] == YOUNG and "young_woman.age" not in (e4.get("narrow_pending") or {})


async def test_a_list_about_a_person_follows_how_they_present(tmp_path):
    from prompt_programs.narrow import NarrowCache, narrow_entry

    async def ask(messages, project_id, tokens):
        return '["ALL"]'

    reading = {"slots": [{"n": 1, "kind": "list", "label": "Outfit", "lead": ",",
                          "list": {"list": "person.outfit.casual", "about": "the boy's outfit", "presentation": "masculine"}}]}
    e = entry_of("1boy, <outfit>, city street", reading)
    await narrow_entry(e, NarrowCache(tmp_path), ask)
    leaf = vocabulary().get("person.outfit.casual")
    masculine = {v.text for v in leaf.matching({"presentation": ["masculine"]})}
    assert masculine and set(e["filters"]["outfit"]) <= masculine
    assert len(masculine) < len(leaf.values)
    assert draw(e, 3).prompt.startswith("1boy, ")


def test_a_group_chosen_is_still_drawn_to_fit_the_age_but_one_value_holds(dorm):
    from prompt_programs.choices import expand
    e = {**dorm, "filters": {"young_man.age": ["22-year-old"]}}
    leaf = vocabulary().get("person.hair_color")
    pins, edits, _ = expand(e, {"young_man.hair_color": {"groups": {"shade": ["black"]}}})
    group = set(pins["young_man.hair_color"])
    graying = {v.text for v in leaf.values if set((v.tags or {}).get("graying") or []) - {"none"}}
    assert group & graying
    got = {values(draw(e, s, pins=pins))["young_man.hair_color"] for s in range(60)}
    assert got <= group and not got & graying
    one = next(iter(group & graying))
    assert values(draw(e, 1, pins={"young_man.hair_color": [one]}))["young_man.hair_color"] == one


def test_an_animals_stated_life_stage_narrows_it():
    reading = {"slots": [{"n": 1, "kind": "animal", "label": "Kitten", "lead": "",
                          "animal": {"noun": "kitten", "vary": ["species", "life_stage"], "breed": "",
                                     "stated": {"life_stage": "kitten"}}}]}
    e = entry_of("a <kitten> on a windowsill", reading)
    assert e["slot_words"] == {"kitten.species": "kitten", "kitten.life_stage": "kitten"}


def test_a_lead_without_its_comma_leaves_nothing_hanging():
    reading = json.loads(json.dumps(DORM_READING))
    reading["slots"][1]["lead"] = "lit by"
    got = draw(entry_of(DORM_PROMPT, reading), 3, edits={"light": {"off": True}}).prompt
    assert "lit by" not in got and not got.endswith(",") and got.endswith(tidy_text([got]))


def test_a_coat_goes_before_the_animals_own_word():
    reading = {"slots": [{"n": 1, "kind": "animal", "label": "Kitten", "lead": "",
                          "animal": {"noun": "kitten", "vary": ["breed", "life_stage"], "breed": "animal.cat_coat",
                                     "stated": {}}}]}
    e = entry_of("a <kitten> on a windowsill", reading)
    for s in range(6):
        got = draw(e, s)
        coat = values(got)["kitten.breed"]
        assert f"{coat} kitten on a windowsill" in got.prompt
    dog = {"slots": [{"n": 1, "kind": "animal", "label": "Dog", "lead": "",
                      "animal": {"noun": "dog", "vary": ["breed"], "breed": "animal.dog_breed", "stated": {}}}]}
    got = draw(entry_of("a girl walking her <dog>", dog), 2)
    assert got.prompt.endswith(values(got)["dog.breed"])

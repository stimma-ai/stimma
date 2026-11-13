"""Slot programs on the real runtime: opt(), people's opt() groups, zones, the outfit
template and line breaks; then the same programs built from a slot reading. Drawn through runtime_for(entry, store=None, mine={}), which reads
the vocabulary lists (LiteralOptions would draw each detail's one seed every time)."""

import json
from typing import Any, Dict, List, Optional

import pytest

from prompt_programs.draws import draw
from prompt_programs.fluent import runtime_for
from prompt_programs.narrow import narrow_entry
from prompt_programs.people import expand_people
from prompt_programs.runtime import discover
from prompt_programs.slots import ReadingError, build, parse
from prompt_programs.vocab import vocabulary

DORM = '''
man = person("young_man", noun="man", show=["age", "descent", "build", "hair", "hair_color"], article=False)
outfit = pick("young_man.outfit", cls="person.outfit.casual", about="the young man's outfit", label="Outfit", phase=2)
light = pick("light", about="the light in a dorm room", seed=["warm desk-lamp light", "grey morning light through blinds"], label="Light", phase=1)
emit("dorm room with a", man, opt(", wearing", outfit), opt(", lit by", light))
'''

PORCH = '''
man = person("elderly_african_man", noun="man", presentation="masculine", show=["age", "descent", "build", "hair", "hair_color", "facial_hair"], article=False)
outfit = pick("elderly_african_man.outfit", cls="person.outfit.casual", about="the elderly man's outfit", label="Outfit", phase=2)
pet = pick("pet", about="his pet, with him on the porch", seed=["ginger tabby cat", "old basset hound", "grey parrot"], zones={"kinds": ["ginger tabby cat", "old basset hound", "grey parrot"], "instead": ["stack of library books", "mug of coffee", "transistor radio"]}, label="Pet", phase=2)
emit("# she is his granddaughter, visiting\\n", "an", man, opt(", wearing", outfit), opt(", reading on a porch with his", pet))
'''


def _ages(lo: int, hi: int) -> List[str]:
    out = []
    for v in vocabulary().get("person.age_band").values:
        head = v.text.split("-")[0]
        if head.isdigit() and lo <= int(head) <= hi:
            out.append(v.text)
    return out


def _entry(source: str, filters: Dict[str, List[str]]) -> Dict[str, Any]:
    program = expand_people(source)
    info = discover(program)
    return {"key": "slots-test", "program": program, "choices": info["choices"], "groups": info["groups"],
            "filters": filters, "prompt": "x", "mode": "prose", "example": info["example"]}


def _draw(entry: Dict[str, Any], seed: int, pins=None, edits: Optional[Dict[str, Any]] = None, zones=None):
    rt = runtime_for(entry, store=None, mine={}, edits=edits, zones=zones)
    return draw(entry["program"], seed, pins, None, None, None, edits, options=rt.options)


@pytest.fixture(scope="module")
def dorm():
    return _entry(DORM, {"young_man.age": _ages(18, 26)})


@pytest.fixture(scope="module")
def porch():
    descents = [d for d in ("Nigerian", "Kenyan", "Ghanaian", "Ethiopian")
                if d in {v.text for v in vocabulary().get("person.ethnicity").values}]
    assert descents
    return _entry(PORCH, {"elderly_african_man.age": _ages(68, 120), "elderly_african_man.descent": descents})


def test_draws_vary_within_the_words(dorm, porch):
    for entry, person, ages in ((dorm, "young_man", _ages(18, 26)), (porch, "elderly_african_man", _ages(68, 120))):
        results = [_draw(entry, 100 + s) for s in range(4)]
        assert len({r.prompt for r in results}) == 4
        for r in results:
            assert {d.id: d.value for d in r.draws}[f"{person}.age"] in ages
    assert all(r.prompt.startswith("Dorm room with a ") for r in (_draw(dorm, s) for s in range(4)))


def test_leaving_a_slot_out_takes_its_lead(dorm, porch):
    lit = _draw(dorm, 3, edits={"light": {"off": True}}).prompt
    assert "lit by" not in lit and not lit.rstrip(".").endswith(",")
    worn = _draw(dorm, 3, edits={"young_man.outfit": {"off": True}}).prompt
    assert "wearing" not in worn and ", lit by" in worn
    pet = _draw(porch, 3, edits={"pet": {"off": True}}).prompt
    assert "porch" not in pet and not pet.endswith("his")


def test_a_detail_off_takes_its_joiners(dorm):
    no_hair = _draw(dorm, 5, edits={"young_man.hair": {"off": True}, "young_man.hair_color": {"off": True}}).prompt
    person = no_hair.split(" man", 1)[1].split(", wearing")[0]
    assert person == "" and "hair" not in no_hair
    color_only = _draw(dorm, 5, edits={"young_man.hair": {"off": True}})
    color = {d.id: d.value for d in color_only.draws}["young_man.hair_color"]
    assert f"man with {color} hair, wearing" in color_only.prompt


def test_a_pinned_age_holds(porch):
    for s in range(4):
        r = _draw(porch, 200 + s, pins={"elderly_african_man.age": ["70-year-old"]})
        assert "70-year-old" in r.prompt


def test_an_outfit_draw_records_its_template(dorm):
    for s in range(6):
        d = {x.id: x for x in _draw(dorm, 300 + s).draws}["young_man.outfit"]
        if d.template:
            assert "{" in d.to_dict()["template"] and "{" not in d.value
            return
    pytest.fail("no outfit was drawn from a template")


def test_a_comment_line_keeps_its_line(porch):
    prompt = _draw(porch, 9).prompt
    first, second = prompt.split("\n")
    assert first == "# she is his granddaughter, visiting"
    assert second.startswith("An ") or second.startswith("A ")


def test_a_free_slot_draws_its_kinds_unless_other_zones_are_chosen(porch):
    kinds = {"ginger tabby cat", "old basset hound", "grey parrot"}
    instead = {"stack of library books", "mug of coffee", "transistor radio"}
    drawn = {{d.id: d.value for d in _draw(porch, s).draws}["pet"] for s in range(12)}
    assert drawn <= kinds
    both = {{d.id: d.value for d in _draw(porch, s, zones={"pet": ["kinds", "instead"]}).draws}["pet"] for s in range(30)}
    assert both & instead and both & kinds


# --------------------------------------------------------------------------- the builder

DORM_PROMPT = "dorm room with a <young man>, lit by <light>"
DORM_READING = {"slots": [
    {"n": 1, "kind": "person", "label": "Young man", "lead": "",
     "person": {"noun": "man", "presentation": "masculine", "stated": {"age": "young"},
                "vary": ["age", "descent", "build", "hair", "hair_color"], "outfit": "person.outfit.casual"}},
    {"n": 2, "kind": "light", "label": "Light", "lead": ", lit by",
     "light": {"list": "", "examples": ["warm desk-lamp light", "grey morning light through blinds", "blue screen glow"]}},
]}
DORM_SOURCE = '''slot1 = person('young_man', noun='man', presentation='masculine', show=['age', 'descent', 'build', 'hair', 'hair_color'], article=False)
slot1_outfit = pick('young_man.outfit', cls='person.outfit.casual', where={'presentation': 'masculine'}, about="Young man's outfit", label='Outfit', phase=2)
slot2 = pick('light', about='light', seed=['warm desk-lamp light', 'grey morning light through blinds', 'blue screen glow'], label='Light', phase=1)
emit('dorm room with a ', slot1, opt(', wearing', slot1_outfit), opt(', lit by', slot2))
'''

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
PORCH_SOURCE = '''slot1 = person('elderly_african_man', noun='man', presentation='masculine', show=['age', 'descent', 'build', 'hair', 'hair_color', 'facial_hair'], article=False)
slot1_outfit = pick('elderly_african_man.outfit', cls='person.outfit.casual', where={'presentation': 'masculine'}, about="Elderly African man's outfit", label='Outfit', phase=2)
slot2 = pick('pet', about='his pet, with him on the porch', seed=['ginger tabby cat', 'old basset hound', 'grey parrot'], zones={'kinds': ['ginger tabby cat', 'old basset hound', 'grey parrot'], 'instead': ['stack of library books', 'mug of coffee', 'transistor radio']}, label='Pet', phase=2)
list1 = pick('list1', ['summer', 'autumn'], label='Season', source='list', phase=1, line=2)
emit('# she is his granddaughter, visiting', '\\n', 'an ', slot1, opt(', wearing', slot1_outfit, ','), ' reading on a porch', opt(' with his', slot2), ', ', list1, ' evening')
'''

ELDERLY = ["71-year-old", "74-year-old", "79-year-old"]
AFRICAN = ["Kenyan", "Ghanaian"]


async def _stub_ask(messages, project_id, max_tokens):
    """narrow.subset's model: a fixed subset per list, whatever the words."""
    user = messages[-1]["content"]
    if user.startswith('The list "Age"'):
        return json.dumps(ELDERLY)
    if user.startswith('The list "Descent"'):
        return json.dumps(AFRICAN)
    return "[]"


def test_the_built_source_is_the_expected_source():
    assert build(parse(DORM_PROMPT), DORM_READING)[0] == DORM_SOURCE
    assert build(parse(PORCH_PROMPT), PORCH_READING)[0] == PORCH_SOURCE


def test_discover_lists_the_slots_choices():
    _, dorm = build(parse(DORM_PROMPT), DORM_READING)
    assert [c["id"] for c in dorm["choices"]] == [
        "young_man.build", "young_man.age", "young_man.descent", "young_man.hair", "young_man.hair_color",
        "young_man.outfit", "young_man.outfit.colors", "light"]
    _, porch = build(parse(PORCH_PROMPT), PORCH_READING)
    assert sorted(c["id"] for c in porch["choices"]) == sorted([
        "elderly_african_man.build", "elderly_african_man.age", "elderly_african_man.descent", "elderly_african_man.hair",
        "elderly_african_man.hair_color", "elderly_african_man.facial_hair", "elderly_african_man.outfit",
        "elderly_african_man.outfit.colors", "pet", "list1"])
    assert next(c for c in porch["choices"] if c["id"] == "list1")["label"] == "Season"
    slots = {s["id"]: s for s in porch["slots"]}
    assert slots["pet"]["details"] == ["pet"] and slots["pet"]["line"] == 2
    assert PORCH_PROMPT[slots["pet"]["span"][0]:slots["pet"]["span"][1]] == "<pet>"
    assert slots["elderly_african_man"]["stated"] == {"age": "elderly", "descent": "African"}
    assert porch["slot_words"] == {"elderly_african_man.age": "elderly", "elderly_african_man.descent": "African", "pet": "pet"}


async def test_the_slots_words_narrow_its_details():
    _, entry = build(parse(PORCH_PROMPT), PORCH_READING)
    await narrow_entry(entry, None, _stub_ask)
    assert sorted(entry["filters"]["elderly_african_man.age"]) == sorted(ELDERLY)
    assert sorted(entry["filters"]["elderly_african_man.descent"]) == sorted(AFRICAN)
    for s in range(20):
        r = _draw(entry, 500 + s)
        drawn = {d.id: d.value for d in r.draws}
        assert drawn["elderly_african_man.age"] in ELDERLY and drawn["elderly_african_man.descent"] in AFRICAN
        assert r.prompt.split("\n")[0] == "# she is his granddaughter, visiting"
        assert drawn["pet"] in PORCH_READING["slots"][1]["free"]["kinds"]
        assert r.prompt.endswith(f"porch with his {drawn['pet']}, {drawn['list1']} evening")


async def test_a_slow_narrowing_leaves_the_answers_that_came_back():
    """Past the time limit only the narrowings still out are pending: an age that came back
    in time holds while the descent's late answer is asked again later."""
    import asyncio

    async def slow_descent(messages, project_id, max_tokens):
        if messages[-1]["content"].startswith('The list "Descent"'):
            await asyncio.sleep(5)
        return await _stub_ask(messages, project_id, max_tokens)

    _, entry = build(parse(PORCH_PROMPT), PORCH_READING)
    await narrow_entry(entry, None, slow_descent, seconds=1.0)
    assert sorted(entry["filters"]["elderly_african_man.age"]) == sorted(ELDERLY)
    assert "elderly_african_man.descent" in entry["narrow_pending"]
    assert "elderly_african_man.age" not in entry["narrow_pending"]


def test_the_same_words_twice_are_two_people():
    reading = {"n": 0, "kind": "person", "label": "Friend", "lead": "",
               "person": {"noun": "friend", "presentation": "", "stated": {}, "vary": ["age", "hair"], "outfit": ""}}
    src, entry = build(parse("<friend> laughing with <friend>"),
                       {"slots": [{**reading, "n": 1}, {**reading, "n": 2}]})
    assert "person('friend'," in src and "person('friend_2'," in src
    ids = {c["id"] for c in entry["choices"]}
    assert {"friend.age", "friend.hair", "friend_2.age", "friend_2.hair"} <= ids
    assert [s["id"] for s in entry["slots"]] == ["friend", "friend_2"]


def test_a_camera_slot_is_one_group_and_a_lead_that_isnt_there_stays_text():
    src, entry = build(parse("a kitchen, shot on <camera>"), {"slots": [
        {"n": 1, "kind": "camera", "label": "Camera", "lead": ", filmed with", "camera": {"vary": ["shot_size", "lens"]}}]})
    assert "emit('a kitchen, shot on ', opt(opt(slot1_shot_size), opt(',', slot1_lens)))" in src
    off = _draw(entry, 1, edits={"camera.shot_size": {"off": True}}).prompt
    assert off.startswith("A kitchen, shot on ") and ", ," not in off and "on," not in off


def test_a_reading_the_builder_cant_use_is_refused():
    with pytest.raises(ReadingError):
        build(parse("a <pet>"), {"slots": []})
    with pytest.raises(ReadingError):
        build(parse("a <thing>"), {"slots": [{"n": 1, "kind": "list", "label": "Thing", "lead": "",
                                               "list": {"list": "no.such.list", "stated": ""}}]})


def test_a_free_slot_as_written_is_a_pin_of_its_words():
    _, entry = build(parse(PORCH_PROMPT), PORCH_READING)
    drawn = {{d.id: d.value for d in _draw(entry, s).draws}["pet"] for s in range(12)}
    assert "pet" not in drawn
    r = _draw(entry, 3, pins={"pet": ["pet"]})
    assert "porch with his pet," in r.prompt


def test_a_realized_prompt_says_where_each_drawn_value_stands():
    """IMPROVER task 5: every drawn value's (start, end, id) in the emitted prompt, after the
    user's [exact text] is back; the user's own words are never a span."""
    from prompt_programs.fluent import runtime_for as rt_for
    from prompt_programs.runtime import tidy_text
    from prompt_programs.program import mask_exact, realize

    masked, exact = mask_exact(PORCH_PROMPT.replace("evening", "evening, [Kodak Portra 400]"))
    _, entry = build(parse(masked), PORCH_READING)
    entry["exact"] = exact
    for seed in range(8):
        r = realize(entry, seed=seed, runtime=rt_for(entry, store=None, mine={}))
        drawn = {d.id: str(d.value) for d in r.draws if d.value is not None}
        ids = [cid for _, _, cid in r.spans]
        assert {"elderly_african_man.age", "elderly_african_man.descent", "pet", "list1"} <= set(ids)
        assert len(ids) == len(set(ids))
        for start, end, cid in r.spans:
            assert r.prompt[start:end].lower() in (drawn[cid].lower(), tidy_text([drawn[cid]]).lower())
        assert all(a < b <= c for (a, b, _), (c, _, _) in zip(r.spans, r.spans[1:]))
        assert "[Kodak Portra 400]" in r.prompt and r.prompt.startswith("# she is his granddaughter")

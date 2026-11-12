"""Slot programs on the real runtime: opt(), people's opt() groups, zones, the outfit
template and line breaks. Drawn through runtime_for(entry, store=None, mine={}), which reads
the vocabulary lists (LiteralOptions would draw each detail's one seed every time)."""

from typing import Any, Dict, List, Optional

import pytest

from prompt_programs.draws import draw
from prompt_programs.fluent import runtime_for
from prompt_programs.people import expand_people
from prompt_programs.runtime import discover
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

"""What a slot's variants are seeded from (prompt_programs/seeding.py): the plan a reading makes,
and the writer's seeds from its narrowed plan. Plain data; no model."""

from __future__ import annotations

import pytest

from prompt_programs import variants as V
from prompt_programs.seeding import ReadingError, plan, seeds_of
from prompt_programs.vocab import vocabulary


def roles(p):
    return [(b["role"], b["list"], b["phrase"]) for b in p["banks"]]


def test_a_person_seeds_descent_gender_age_and_their_look():
    p = plan({"kind": "person", "person": {"noun": "man", "presentation": "masculine",
                                           "stated": {"age": "elderly", "descent": "African"},
                                           "outfit": "person.outfit.casual"}}, "elderly African man")
    got = roles(p)
    assert got[:3] == [("descent", V.DESCENT, "African"), ("gender", V.GENDER, "elderly African man"),
                       ("age", V.AGE, "elderly African man")]
    assert next(b for b in p["banks"] if b["role"] == "age")["age"] is True
    ideas = [lid for role, lid, _ in got if role == "idea"]
    assert "person.facial_hair" in ideas and "person.outfit.casual" in ideas
    assert p["stated_descent"] is True


def test_a_person_whose_clothes_are_said_or_another_slot_gets_no_outfit():
    for person in ({"clothes_part": {"n": 2, "words": "kimono"}}, {"clothes": "in a red raincoat"}):
        p = plan({"kind": "person", "person": {"noun": "woman", "presentation": "feminine",
                                               "outfit": "person.outfit.casual", **person}}, "woman")
        assert not any(b["list"].startswith("person.outfit") for b in p["banks"])
    p = plan({"kind": "person", "person": {"noun": "woman", "presentation": "feminine"}}, "woman")
    assert "person.facial_hair" not in [b["list"] for b in p["banks"]]   # facial hair only for a masculine person


def test_a_stated_age_joins_the_words_it_narrows_by():
    p = plan({"kind": "person", "person": {"noun": "woman", "stated": {"age": "in her 40s"}}}, "woman")
    assert next(b for b in p["banks"] if b["role"] == "age")["phrase"] == "in her 40s, woman"
    p = plan({"kind": "person", "person": {"noun": "woman", "stated": {"age": "young"}}}, "young woman")
    assert next(b for b in p["banks"] if b["role"] == "age")["phrase"] == "young woman"


def test_a_list_slot_is_one_list_with_a_core_and_a_light_its_ideas():
    p = plan({"kind": "list", "list": {"list": "camera.angle", "about": "the angle"}}, "selfie camera angle")
    assert roles(p) == [("core", "camera.angle", "selfie camera angle")]
    p = plan({"kind": "light", "light": {"list": "lighting.natural", "examples": []}}, "light")
    assert roles(p) == [("idea", "lighting.natural", "light")]   # ideas the writer may reject, not cores
    assert plan({"kind": "light", "light": {"list": "", "examples": ["lamplight"]}}, "light")["banks"] == []


def test_a_camera_an_animal_and_a_free_slot_seed_ideas():
    p = plan({"kind": "camera", "camera": {"vary": ["shot_size", "lens"]}}, "camera")
    assert roles(p) == [("idea", "camera.shot_size", ""), ("idea", "camera.lens", "")]
    p = plan({"kind": "animal", "animal": {"noun": "pet", "vary": ["species", "life_stage"], "type": "pet",
                                           "stated": {}}}, "pet")
    assert [b["list"] for b in p["banks"]] == ["animal.species", "animal.life_stage"]
    assert p["banks"][0]["where"] == {"kind": "pet"}
    p = plan({"kind": "free", "free": {"kinds": ["den"], "lists": ["interior_space.room", "no.such.list"]}}, "room")
    assert roles(p) == [("idea", "interior_space.room", "room")]   # narrowed by its words like any list
    p = plan({"kind": "free", "free": {"about": "a sports car", "lists": ["vehicle.road_vehicle"]}}, "sports car")
    assert roles(p) == [("idea", "vehicle.road_vehicle", "sports car")] and p["banks"][0]["about"] == "a sports car"


def test_a_reading_naming_no_list_is_an_error():
    with pytest.raises(ReadingError):
        plan({"kind": "list", "list": {"list": "no.such.list"}}, "thing")
    with pytest.raises(ReadingError):
        plan({"kind": "robot"}, "thing")


def test_seeds_from_a_narrowed_plan():
    record = {"kind": "person", "stated_descent": True, "minor": ["9-year-old"],
              "banks": [{"role": "descent", "list": V.DESCENT, "narrowed": ["Nigerian", "Ghanaian"]},
                        {"role": "gender", "list": V.GENDER, "narrowed": ["woman", "trans woman"]},
                        {"role": "age", "list": V.AGE, "narrowed": None, "failed": True},
                        {"role": "idea", "list": "person.makeup", "narrowed": None}]}
    s = seeds_of(record)
    assert s.descent.texts() == ["Nigerian", "Ghanaian"] and s.gender.texts() == ["woman", "trans woman"]
    assert s.age is None and s.minor == ("9-year-old",)   # a failed age seeds nothing; the list's age still counts
    adult = {v.text for v in vocabulary().get("person.makeup").values if v.adult_only}
    assert not set(s.ideas[0].texts()) & adult
    core = seeds_of({"kind": "list", "banks": [{"role": "core", "list": "clothing.top", "narrowed": None}]})
    assert core.core is not None and core.ideas == ()
    dropped = seeds_of({"kind": "list", "banks": [{"role": "core", "list": "camera.angle", "narrowed": []}]})
    assert dropped.core is None and dropped.ideas == ()

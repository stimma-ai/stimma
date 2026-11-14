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
    assert roles(p) == [("core", "lighting.natural", "light")]   # each variant builds on one look of light
    assert p["banks"][0]["scene"] is True   # narrowed in the scene, not by the word "light" alone
    # a light naming no list is the scene list: light described as light, no fixtures
    assert roles(plan({"kind": "light", "light": {"list": ""}}, "light")) == [("core", "lighting.scene", "light")]


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


def person(**kw):
    return {"kind": "person", "person": {"noun": kw.pop("noun", "couple"), "presentation": "", "stated": {},
                                         "vary": ["age", "descent", "build", "hair", "hair_color"],
                                         "outfit": "person.outfit.casual", **kw}}


def test_a_couple_draws_who_they_are_one_heritage_and_one_age():
    p = plan(person(people="couple"), "couple")
    got = roles(p)
    assert ("descent", V.DESCENT, "") in got and ("gender", "person.couple", "couple") in got
    assert ("age", V.AGE, "couple") in got
    assert p["people"] == "couple"
    rec = {"kind": "person", "banks": [{**b, "narrowed": None} for b in p["banks"]], "people": "couple"}
    seeds = seeds_of(rec)
    assert seeds.people == "couple" and seeds.gender.list_id == "person.couple"
    assert dict(seeds.gender.values) == {"a man and a woman": 0.9, "two women": 0.05, "two men": 0.05}


def test_a_family_shares_a_heritage_and_a_group_draws_no_one_look():
    fam = roles(plan(person(noun="family", people="family"), "family"))
    assert [r for r, *_ in fam if r != "idea"] == ["descent"]   # no single gender or age forced on them
    grp = plan(person(noun="friends", people="group"), "three friends")
    assert grp["banks"] == []   # no descent, gender, age or one look for all of them: the writer varies them


def test_a_figure_a_heritage_doesnt_apply_to_draws_no_descent():
    p = plan(person(noun="elf", heritage=False), "elf warrior")
    assert "descent" not in [b["role"] for b in p["banks"]]
    assert "gender" in [b["role"] for b in p["banks"]]


def test_what_a_person_wears_and_their_hairstyle_are_narrowed_in_the_scene():
    p = plan(person(noun="farmer", vary=["age", "descent", "hair", "hairstyle"]), "farmer")
    outfit = next(b for b in p["banks"] if b["list"] == "person.outfit.casual")
    assert outfit["phrase"] == "farmer" and outfit["scene"] is True
    style = next(b for b in p["banks"] if b["list"] == "person.hairstyle")
    assert style["phrase"] == "farmer" and style["scene"] is True
    # only the details the reading varies: no hairstyle unless it says so, no build here
    lists = [b["list"] for b in plan(person(noun="farmer", vary=["age", "descent", "hair"]), "farmer")["banks"]]
    assert "person.hairstyle" not in lists and "person.build" not in lists and "person.hair_length" in lists

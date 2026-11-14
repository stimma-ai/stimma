"""People in numbers and light as light: a couple, a family and a group are read and seeded as
such, a figure a real heritage doesn't fit draws none, a share of a person's variants wear what is
typical for who and where they are, and lists are narrowed in their scene. Plain data and fakes;
no model."""

from __future__ import annotations

import random

from prompt_programs import reader
from prompt_programs import variant_pools as P
from prompt_programs import variants as V
from prompt_programs.narrow import messages_for
from prompt_programs.seeding import plan, seeds_of
from prompt_programs.slots import parse
from prompt_programs.vocab import vocabulary


def _seg(prompt: str, n: int = 1):
    return [seg for seg in parse(prompt).segments if seg.kind == "slot"][n - 1]


def _reading(**person):
    return {"n": 1, "kind": "person", "label": "Couple", "lead": "a", "category": "",
            "person": {"noun": "couple", "presentation": "", "stated": {},
                       "vary": ["age", "descent", "build", "hair"], "outfit": "person.outfit.casual", **person}}


def test_the_reader_keeps_who_a_person_part_names_and_whether_a_heritage_applies():
    seg = _seg("a <couple> at a restaurant")
    got = reader.check_slot(_reading(people="couple"), seg, "a ", [])
    assert got["person"]["people"] == "couple" and "heritage" not in got["person"]
    elf = reader.check_slot(_reading(noun="elf", people="one", heritage=False), _seg("an <elf> in a forest"), "an ", [])
    assert elf["person"]["heritage"] is False and "people" not in elf["person"]   # one person is the default
    odd = reader.check_slot(_reading(people="crowd of two", heritage="no"), seg, "a ", [])
    assert "people" not in odd["person"] and "heritage" not in odd["person"]   # unknown values are dropped
    assert '"people"' in reader.system_text() and '"heritage"' in reader.system_text()


def _seeds(people: str, words: str = "couple") -> V.Seeds:
    p = plan(_reading(people=people), words)
    return seeds_of({"kind": "person", "banks": [{**b, "narrowed": None} for b in p["banks"]],
                     **({"people": p["people"]} if p.get("people") else {})})


def test_a_couple_variant_says_who_they_are_and_needs_both_words():
    seeds = _seeds("couple")
    drawn = V.draw_seeds(random.Random(3), seeds, 40, "couple")
    whos = [s.gender for s in drawn.specs]
    assert set(whos) <= {"a man and a woman", "two women", "two men"}
    assert whos.count("a man and a woman") >= 30   # 90% by the list's shares
    s = next(s for s in drawn.specs if s.gender == "a man and a woman")
    assert s.pair and s.gender_needs == ("man", "woman") and 'who: "a man and a woman"' in s.line()
    assert V.check("young Ugandan couple, the man in a white shirt, the woman in green", "couple", ["couple"], s) == ""
    assert V.check("young Ugandan couple, the man in a white shirt", "couple", ["couple"], s) == "gender missing"
    women = V.Spec(gender="two women", gender_needs=("women",), pair=True)
    assert V.check("couple, two women in their thirties sharing a laugh", "couple", ["couple"], women) == ""
    assert V.gender_mark("two men") == "men" and V.gender_mark("trans woman") == "trans woman"


def test_a_couple_shares_a_heritage_with_a_second_one_now_and_then():
    drawn = V.draw_seeds(random.Random(5), _seeds("couple"), 200, "couple")
    second = [s for s in drawn.specs if s.descent2]
    assert 10 <= len(second) <= 55 and all(s.descent2 != s.descent for s in second)
    assert f'"{second[0].descent}" for one, "{second[0].descent2}" for the other' in second[0].line()


def test_the_writer_is_told_how_several_people_are_written():
    slot = V.Slot("couple", "a <couple> at a restaurant", (2, 10), "person")
    for people in ("couple", "family", "group"):
        seeds = _seeds(people)
        text = V.messages(slot, V.draw_seeds(random.Random(1), seeds, 5, "couple"), seeds)[1]["content"]
        assert V.PEOPLE_NOTES[people] in text
    one = _seeds("one", "chef")
    assert not any(n in V.messages(slot, V.draw_seeds(random.Random(1), one, 5, "chef"), one)[1]["content"]
                   for n in V.PEOPLE_NOTES.values())


def test_a_third_of_a_persons_variants_take_no_look_ideas_and_wear_what_is_typical():
    seeds = _seeds("one", "farmer")
    drawn = V.draw_seeds(random.Random(2), seeds, 30, "farmer")
    typical = [s for s in drawn.specs if V.TYPICAL in s.develop]
    assert len(typical) == 10 and all(not s.ideas for s in typical)
    assert all(V.CLOTHES not in s.develop for s in typical)
    assert any(s.ideas for s in drawn.specs if V.TYPICAL not in s.develop)
    owned = V.replace(seeds, clothes_owned=True)   # the prompt says what they wear: nothing typical to ask for
    assert not any(V.TYPICAL in s.develop for s in V.draw_seeds(random.Random(2), owned, 30, "farmer").specs)


def test_a_list_read_in_its_scene_is_asked_with_the_prompt():
    leaf = vocabulary().get("person.outfit.casual")
    msgs = messages_for(leaf, "farmer", [v.text for v in leaf.values][:5], "what the farmer wears",
                        "a <farmer> in rural Vietnam, <camera>")
    assert "a <farmer> in rural Vietnam" in msgs[1]["content"] and "out of place" in msgs[1]["content"]
    plain = messages_for(leaf, "farmer", [v.text for v in leaf.values][:5], "what the farmer wears")
    assert "The prompt it is said in" not in plain[1]["content"]


def test_the_scene_light_list_describes_light_and_is_the_light_default():
    leaf = vocabulary().get("lighting.scene")
    assert leaf is not None and len(leaf.values) >= 20
    assert "lighting.scene" in reader.system_text()


def test_the_pickers_show_what_several_people_were_seeded_with():
    couple = P.person_pickers([], P.Choice(), gender_list="person.couple", age=True)
    assert couple["gender"]["options"] == ["a man and a woman", "two women", "two men"]
    group = P.person_pickers([], P.Choice(), gender_list=None, descent=False, age=False)
    assert group == {}
    assert set(P.person_pickers([], P.Choice())) == {"descent", "gender", "age"}


def test_seeds_without_a_descent_or_gender_bank_draw_none():
    elf = plan(_reading(noun="elf", heritage=False), "elf")
    seeds = seeds_of({"kind": "person", "banks": [{**b, "narrowed": None} for b in elf["banks"]]})
    assert seeds.descent is None and seeds.gender is not None
    grp = _seeds("group", "three friends")
    assert grp.descent is None and grp.gender is None and grp.age is None
    fam = _seeds("family", "family")
    assert fam.descent is not None and fam.gender is None
    assert not any(s.descent or s.gender for s in V.draw_seeds(random.Random(1), grp, 10, "three friends").specs)


def test_a_place_the_table_lacks_is_asked_again_then_left_out():
    import pytest
    seg = _seg("a <farmer> in rural Vietnam")
    ok = reader.check_slot(_reading(noun="farmer", place="Vietnam"), seg, "a ", [])
    assert ok["person"]["place"] == "Vietnam"
    with pytest.raises(reader._Bad, match="plain common name"):
        reader.check_slot(_reading(noun="farmer", place="rural Vietnam"), seg, "a ", [])
    loose = reader.check_slot(_reading(noun="farmer", place="rural Vietnam"), seg, "a ", [], strict=False)
    assert "place" not in loose["person"]
    assert reader.check_slot(_reading(noun="farmer", place="Scotland"), seg, "a ", [])["person"]["place"] == "Scotland"


def test_several_people_get_more_words_and_a_light_part_its_note():
    long_ = "three friends, " + ", ".join(["a tall man in a gray raincoat with a newspaper"] * 4)
    one = V.Spec()
    assert V.check(long_, "three friends", ["three friends"], one) == "too long"
    assert V.check(long_, "three friends", ["three friends"], V.Spec(several=True)) == ""
    assert all(s.several for s in V.draw_seeds(random.Random(1), _seeds("group", "three friends"), 4, "three friends").specs)
    light = V.Slot("light", "a porch, <light>", (9, 16), "light")
    assert V.LIGHT_NOTE in V.messages(light, V.draw_seeds(random.Random(1), V.Seeds(), 3), V.Seeds())[1]["content"]

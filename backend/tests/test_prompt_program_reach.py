"""How far a list-bound choice reaches (reach.py): the picker's settings "what you said",
"what fits" and "any", sent with the pools, and draws that agree with them."""

import collections

from prompt_programs.draws import draw
from prompt_programs.fluent import pool_options, runtime_for
from prompt_programs.judge import FluentSettings
from prompt_programs.options import OptionStore, program_minors
from prompt_programs.reach import similar_values
from prompt_programs.runtime import discover
from prompt_programs.vocab import vocabulary

OFF = FluentSettings(generate_options=False, fix_model="off")


def entry_of(src, prompt="", **extra):
    return {"key": "k", "program": src, "loras": [], "params": {}, "mode": "prose", "prompt": prompt,
            "choices": discover(src)["choices"], **extra}


def pools(entry, tmp_path, pins=None, mine=None):
    return pool_options(entry, pins, store=OptionStore(tmp_path), cfg=OFF, mine=mine or {})


def values(entry, tmp_path, cid, seeds, pins=None, edits=None):
    rt = runtime_for(entry, store=OptionStore(tmp_path), cfg=OFF, edits=edits, mine={})
    for seed in seeds:
        r = draw(entry["program"], seed, pins, [], None, None, edits, options=rt.options)
        rt.options.reset()
        yield next(d for d in r.draws if d.id == cid).value


IRISH = '''
eth = pick("eth", cls="person.ethnicity", said="Irish", about="her descent", seed=["Scottish"], label="Ethnicity", phase=1, line=1)
emit("An", eth, "woman reading in a pub")
'''

EMERALD = '''
eyes = pick("eyes", cls="person.eye_color", said="emerald", about="her eye color", seed=["hazel"], label="Eyes", phase=1, line=1)
emit("A woman with", eyes, "eyes")
'''

YOUNG = '''
age = pick("age", cls="person.age_band", where="young", about="her age", seed=["20–24-year-old"], label="Age", phase=1, line=1)
expr = pick("expr", cls="person.expression", about="her expression", seed=["a soft smile"], label="Expression", phase=2, line=1)
emit("A", age, "woman with", expr)
'''

HAIR = '''
hair = pick("hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=1, line=1)
emit("A Japanese woman with", hair, "hair")
'''

DRAWN = '''
descent = pick("descent", cls="person.ethnicity", about="her descent", seed=["Korean"], label="Descent", phase=1, line=1)
hair = pick("hair", cls="person.hair_color", about="her hair color", seed=["black"], label="Hair", phase=2, line=1)
emit("A", descent, "woman with", hair, "hair")
'''


def minors(leaf_id):
    return {v.text for v in vocabulary().get(leaf_id).values if v.opt_in}


class TestSimilar:
    def test_a_stated_descent_is_similar_to_its_declared_group(self):
        eth = vocabulary().get("person.ethnicity")
        texts = [v.text for v in eth.values]
        assert similar_values(eth, "Irish", texts) == ["Irish", "Scottish", "Welsh"]

    def test_lists_without_declared_groups_use_their_first_part(self):
        v = vocabulary()
        hair = v.get("person.hair_color")
        got = similar_values(hair, "golden blonde", [x.text for x in hair.values])
        assert got[0] == "golden blonde" and 3 <= len(got) <= 10
        assert all("blonde" in hair.value(x).tags["shade"] for x in got)
        age = v.get("person.age_band")
        adults = [x.text for x in age.values if not x.opt_in]
        old = similar_values(age, "70–74-year-old", adults)
        assert old[0] == "70–74-year-old" and len(old) == 7
        assert all("elderly" in age.value(x).tags["life_stage"] for x in old)

    def test_build_has_its_groups_declared_beside_the_list(self):
        build = vocabulary().get("person.build")
        got = similar_values(build, "stocky", [x.text for x in build.values])
        assert got[0] == "stocky" and "plus-size" in got and "slender" not in got

    def test_no_similar_for_a_value_off_the_list_or_a_list_without_grouping(self):
        v = vocabulary()
        eyes = v.get("person.eye_color")
        assert similar_values(eyes, "emerald", [x.text for x in eyes.values]) == []
        lens = v.get("camera.lens")
        assert similar_values(lens, lens.values[0].text, [x.text for x in lens.values]) == []
        room = v.get("interior_space.bar")   # a room's size says nothing about likeness
        assert similar_values(room, room.values[0].text, [x.text for x in room.values]) == []

    def test_a_group_that_is_most_of_the_list_is_not_similar(self):
        coats = vocabulary().get("person.outfit.cold_weather")
        texts = [x.text for x in coats.pool_values()[0]]
        assert all(len(similar_values(coats, t, texts)) * 2 <= len(texts) for t in texts)


class TestStated:
    def test_a_stated_list_value_has_just_similar_and_any(self, tmp_path):
        out = pools(entry_of(IRISH, "a young Irish woman reading in a pub"), tmp_path)
        reach = out["vocab"]["eth"]["reach"]
        assert reach["said"] == ["Irish"] and reach["fits"] == ["Irish", "Scottish", "Welsh"]
        assert reach["any"][0] == "Irish" and set(reach["any"]) == set(out["options"]["eth"])
        assert len(reach["any"]) == len(set(reach["any"])) > 60

    def test_each_setting_draws_exactly_its_values(self, tmp_path):
        e = entry_of(IRISH)
        reach = pools(e, tmp_path / "p")["vocab"]["eth"]["reach"]
        assert set(values(e, tmp_path, "eth", range(30))) == {"Irish"}   # unticked: their words
        similar = set(values(e, tmp_path, "eth", range(300), pins={"eth": reach["fits"]}))
        assert similar == set(reach["fits"])
        anyone = collections.Counter(values(e, tmp_path, "eth", range(400), pins={"eth": reach["any"]}))
        assert set(anyone) <= set(reach["any"]) and len(anyone) > 40

    def test_a_stated_value_off_the_list_has_no_similar(self, tmp_path):
        reach = pools(entry_of(EMERALD), tmp_path)["vocab"]["eyes"]["reach"]
        assert reach["said"] == ["emerald"] and "fits" not in reach
        assert reach["any"][0] == "emerald" and len(reach["any"]) > 5

    def test_no_said_on_the_choice_is_fine(self, tmp_path):
        src = IRISH.replace('said="Irish", ', "")
        out = pools(entry_of(src), tmp_path)
        assert "reach" not in out["vocab"]["eth"]   # wide open, no context: everything fits


class TestNarrowed:
    def narrowed(self):
        e = entry_of(YOUNG, "a young woman")
        age = vocabulary().get("person.age_band")
        e["filters"] = {"age": [v.text for v in age.values if v.text.startswith(("20", "25", "30"))]}
        return e

    def test_the_subset_fits_and_the_rest_is_offered_unticked(self, tmp_path):
        e = self.narrowed()
        out = pools(e, tmp_path)
        meta, opts = out["vocab"]["age"], out["options"]["age"]
        assert meta["reach"]["fits"] == e["filters"]["age"]
        assert meta["reach"]["words"] == "young"   # the user's words name the setting
        assert [o for o in opts if meta["tiers"][o] != "opt_in"] == e["filters"]["age"]   # the default ticks
        assert len(opts) == len(vocabulary().get("person.age_band").values)

    def test_any_never_holds_values_drawn_only_when_asked(self, tmp_path):
        reach = pools(self.narrowed(), tmp_path)["vocab"]["age"]["reach"]
        assert not set(reach["any"]) & minors("person.age_band")
        assert set(reach["fits"]) < set(reach["any"]) and "70–74-year-old" in reach["any"]

    def test_draws_keep_to_the_subset_until_any_is_ticked(self, tmp_path):
        e = self.narrowed()
        reach = pools(e, tmp_path / "p")["vocab"]["age"]["reach"]
        assert set(values(e, tmp_path, "age", range(200))) <= set(reach["fits"])
        wide = set(values(e, tmp_path, "age", range(400), pins={"age": reach["any"]}))
        assert wide <= set(reach["any"]) and wide - set(reach["fits"])   # the rest is drawn once ticked
        assert not wide & minors("person.age_band")

    def test_the_minors_policy_is_unaffected(self, tmp_path):
        e = entry_of(YOUNG, "a 10-year-old girl")
        e["filters"] = {"age": ["8–10-year-old"]}
        assert program_minors(e)
        reach = pools(e, tmp_path / "p")["vocab"]["age"]["reach"]
        assert reach["fits"] == ["8–10-year-old"]
        adult_only = {v.text for v in vocabulary().get("person.expression").values if v.adult_only}
        assert adult_only   # the policy's adult-coded looks exist on this list
        drawn = set(values(e, tmp_path, "expr", range(300), pins={"age": reach["any"]}))
        assert not drawn & adult_only   # ticking adult ages keeps her pools a minor's
        assert program_minors(e)


class TestOpen:
    def test_a_stated_context_sets_what_fits(self, tmp_path):
        e = entry_of(HAIR, "a Japanese woman", stated_context=[{"of": "", "cls": "person.ethnicity", "values": ["Japanese"]}])
        out = pools(e, tmp_path / "p")
        reach = out["vocab"]["hair"]["reach"]
        assert reach["any"] == [o for o in out["options"]["hair"] if out["vocab"]["hair"]["tiers"][o] != "opt_in"]
        assert "black" in reach["fits"] and "platinum blonde" not in reach["fits"]
        assert set(reach["fits"]) < set(reach["any"])
        # ticked as "what fits" (the rest left out), a run draws only from it
        out_ = [o for o in reach["any"] if o not in reach["fits"]]
        got = set(values(e, tmp_path, "hair", range(300), edits={"hair": {"remove": out_}}))
        assert got <= set(reach["fits"])

    def test_a_context_that_moves_with_another_draw_says_nothing(self, tmp_path):
        assert "reach" not in pools(entry_of(DRAWN), tmp_path)["vocab"]["hair"]

    def test_the_users_own_options_are_in_no_setting(self, tmp_path):
        e = entry_of(IRISH)
        mine = {"person.ethnicity": ["Atlantean"]}
        out = pool_options(e, store=OptionStore(tmp_path), cfg=OFF, mine=mine)
        reach = out["vocab"]["eth"]["reach"]
        assert "Atlantean" in out["options"]["eth"] and "Atlantean" not in reach["any"]

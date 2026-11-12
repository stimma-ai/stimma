"""LoRA names stay out of the prompt, short LoRA names resolve, one user list can fill
several places, and a prepare that runs too long stops (Fluent on canary, 2026-11-08)."""

import pytest

from prompt_programs.draws import draw
from prompt_programs.runtime import LoraInfo, ProgramError, lora_names, run, _lora_key


LORAS = [
    LoraInfo("KREA2 hairshop bobcut v1", "k/bobcut.safetensors", 0.7, ""),
    LoraInfo("StyleMaster Bob cut & Fringe krea2 V1", "k/sm.safetensors", 0.8, ""),
    LoraInfo("KREA2 hairshop pixie v1", "k/pixie.safetensors", 0.6, ""),
    LoraInfo("KREA2 hairshop curly v1", "k/curly.safetensors", 0.6, "curlz"),
    LoraInfo("KREA2 hairshop braids v1", "k/braids.safetensors", 0.6, ""),
]
BY_KEY = {_lora_key(lo.name): lo for lo in LORAS}


class TestLoraNames:
    def test_short_names_resolve_to_the_one_listed_name(self):
        assert lora_names(["bobcut", "pixie", "KREA2 hairshop curly v1"], BY_KEY) == [
            "KREA2 hairshop bobcut v1", "KREA2 hairshop pixie v1", "KREA2 hairshop curly v1"]

    def test_ambiguous_or_unknown_names_are_dropped(self):
        # "hairshop" names four LoRAs; "mohawk" names none
        assert lora_names(["hairshop", "mohawk", "braids"], BY_KEY) == ["KREA2 hairshop braids v1"]

    def test_none_known_still_fails(self):
        with pytest.raises(ProgramError, match="none of"):
            run('b = pick_lora("b", ["mohawk"])\nemit("x")', 1, None, LORAS, set())

    def test_short_names_draw_and_turn_on_the_listed_lora(self):
        src = 'b = pick_lora("hair", ["bobcut", "pixie"], label="Hair")\nemit("Two friends on a sofa.")\n'
        seen = set()
        for s in range(30):
            r = run(src, s, None, LORAS, set())
            seen.add(r.loras[0].name)
            assert r.loras[0].path in ("k/bobcut.safetensors", "k/pixie.safetensors")
        assert seen == {"KREA2 hairshop bobcut v1", "KREA2 hairshop pixie v1"}


SPARK_EMIT = '''b = pick_lora("hair_lora", ["KREA2 hairshop curly v1", "KREA2 hairshop pixie v1"], label="Hair", line=5)
emit("Two friends on a beige sofa, harsh flash.", "\\n", b)
'''


class TestLoraNameNeverEmitted:
    def test_emitting_the_pick_writes_nothing(self):
        for s in range(20):
            r = run(SPARK_EMIT, s, None, LORAS, set())
            assert "hairshop" not in r.prompt.lower()
            assert r.prompt.startswith(("curlz, Two friends", "Two friends"))  # the trigger still goes in
            assert len(r.loras) == 1

    def test_the_value_still_compares_and_looks_up(self):
        src = ('b = pick_lora("b", ["curly", "pixie"])\n'
               'words = {"KREA2 hairshop curly v1": "curly hair"}.get(b, "straight hair")\n'
               'emit("A woman,", words)\n')
        got = {run(src, s, None, LORAS, set()).prompt for s in range(30)}
        assert {p.removeprefix("curlz, ") for p in got} == {"A woman, curly hair", "A woman, straight hair"}

    def test_draw_path_skips_it_too(self):
        src = ('b = pick_lora("b", ["curly", "pixie"], phase=1)\n'
               'emit("Two friends on a beige sofa.", b)\n')
        for s in range(10):
            r = draw(src, s, None, LORAS, set())
            assert "hairshop" not in r.prompt.lower() and r.loras


class TestSubjectsGroup:
    def test_hand_written_people_group_by_label(self):
        from prompt_programs.runtime import discover
        src = ('a = pick("g1_hair", ["a bob", "braids"], label="Girl 1 Hair")\n'
               'b = pick("g1_eyes", ["green eyes", "brown eyes"], label="Girl 1 Eyes")\n'
               'c = pick("g2_hair", ["a bob", "braids"], label="Girl 2 Hair")\n'
               'd = pick("g2_eyes", ["green eyes", "brown eyes"], label="Girl 2 Eyes")\n'
               'e = pick("color1", ["red", "blue"], label="Color 1")\n'
               'emit("One with", a, b, "and one with", c, d, e)\n')
        info = discover(src, [], set(), runs=4)
        by = {c["id"]: c for c in info["choices"]}
        assert by["g2_eyes"]["group"] == "girl" and by["g2_eyes"]["index"] == 2 and by["g2_eyes"]["label"] == "Eyes"
        assert "group" not in by["color1"]
        assert info["groups"] == [{"id": "girl", "count": 2, "label": "Girl", "source": "text", "line": None}]

    def test_bracket_ids_without_group_call_get_a_group(self):
        from prompt_programs.runtime import discover
        src = ('a = pick("girl[1].hair", ["a bob", "braids"], label="Hair")\n'
               'b = pick("girl[2].hair", ["a bob", "braids"], label="Hair")\n'
               'emit(a, b)\n')
        info = discover(src, [], set(), runs=4)
        assert info["groups"][0]["id"] == "girl" and info["groups"][0]["count"] == 2

    def test_one_person_is_not_a_group(self):
        from prompt_programs.runtime import discover
        src = 'a = pick("p_hair", ["a bob", "braids"], label="Person 1 Hair")\nemit(a)\n'
        info = discover(src, [], set(), runs=4)
        assert not info["groups"] and "group" not in info["choices"][0]


class TestSubjectCells:
    def test_alternatives_for_one_cell_stay_flat(self):
        from prompt_programs.runtime import discover
        src = ('w = pick("weather", ["cold", "hot"], source="list", line=1)\n'
               'a = pick("g1_hair", ["a bob", "braids"], label="Girl 1 Hair")\n'
               'if w == "cold":\n    b = pick("g2_hair_cold", ["a beanie", "a hood"], label="Girl 2 Hair")\n'
               'else:\n    b = pick("g2_hair_hot", ["a ponytail", "a bun"], label="Girl 2 Hair")\n'
               'emit(w, a, b)\n')
        info = discover(src, [], set(), runs=24)
        assert not info["groups"] and all("group" not in c for c in info["choices"])


class TestLorasShownToTheModels:

    def test_enhancer_guidance_lists_only_loras_with_something_to_say(self):
        from routes.prompt_enhancement import _lora_guidance
        assert _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""}]) == ""
        g = _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""},
                            {"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": ""}])
        assert "ultra real krea2" not in g and '"wolfcut"' in g and "never write a LoRA's name" in g


class TestArticles:
    def test_an_article_before_a_value_that_has_one_collapses(self):
        from prompt_programs.runtime import tidy_text
        assert tidy_text(["A", "a spontaneous photo of a woman. She has a", "a warm smile."]) == "A spontaneous photo of a woman. She has a warm smile."
        assert tidy_text(["A cat and a dog"]) == "A cat and a dog"

    def test_a_joining_word_before_a_value_that_has_one_collapses(self):
        from prompt_programs.runtime import tidy_text
        assert tidy_text(["A photo of a cat", "with", "with tufted ears", ", in", "in a sunlit garden", "."]) == \
            "A photo of a cat with tufted ears, in a sunlit garden."
        assert tidy_text(["A woman,", "her", "her chestnut hair", "loose."]) == "A woman, her chestnut hair loose."
        # only at a seam after a few joining words: a doubled word inside a part, or after a long part, is as written
        assert tidy_text(["They had had enough."]) == "They had had enough."
        assert tidy_text(["a tall man standing by the old harbor wall in", "in a red coat"]) == \
            "A tall man standing by the old harbor wall in in a red coat"


class TestOptionContinuity:
    def test_a_patched_program_keeps_the_pools_of_picks_it_didnt_touch(self):
        from prompt_programs.draws import PickSpec
        from prompt_programs.options import GeneratedOptions, ProgramContext

        spec = PickSpec("eye_color", "Eye Color", "her eye color", 2, "text", "pick", ["emerald green"], [])
        v1 = ProgramContext(key="p1", signature="a woman with {eyes}", template="a woman with {eyes}", lineage="p1")
        v2 = ProgramContext(key="p2", signature="a tall woman with {eyes}", template="a tall woman with {eyes}", lineage="p1")
        other = ProgramContext(key="p3", signature="a tall woman with {eyes}", template="a tall woman with {eyes}", lineage="p3")
        k1 = GeneratedOptions(None, v1)._where(spec, {})[1]
        assert GeneratedOptions(None, v2)._where(spec, {})[1] == k1      # same lineage: same options
        assert GeneratedOptions(None, other)._where(spec, {})[1] != k1   # a new prompt: its own

    def test_a_wildcard_in_the_users_words_bounds_its_options(self):
        from prompt_programs.draws import PickSpec
        from prompt_programs.options import GeneratedOptions, OptionJob, ProgramContext, generation_messages
        spec = PickSpec("1970s_or_1980s_cars", "Cars", "the parked cars", 1, "text", "pick", ["a Ford Granada"], [])
        prog = ProgramContext(key="p", signature="a street", template="a street of [Cars]", lineage="p",
                              intents=(("1970s_or_1980s_cars", "1970s or 1980s cars"),))
        plain = ProgramContext(key="p", signature="a street", template="a street of [Cars]", lineage="p")
        assert GeneratedOptions(None, prog)._where(spec, {})[1] != GeneratedOptions(None, plain)._where(spec, {})[1]
        job = OptionJob("k", spec, {}, prog, "a street", 0)
        user = generation_messages(job)[1]["content"]
        assert '"1970s or 1980s cars"' in user and "rule, not an example" in user
        assert "nothing added" in user   # a wildcard names its things: "Japan", not a description of Japan
        assert "nothing added" not in generation_messages(OptionJob("k", spec, {}, plain, "a street", 0))[1]["content"]



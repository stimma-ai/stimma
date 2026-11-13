"""What the models are told about LoRAs, the article and joining-word seams, and how options
keep their pools."""

import pytest





SPARK_EMIT = '''b = pick_lora("hair_lora", ["KREA2 hairshop curly v1", "KREA2 hairshop pixie v1"], label="Hair", line=5)
emit("Two friends on a beige sofa, harsh flash.", "\\n", b)
'''








class TestLorasShownToTheModels:

    def test_enhancer_guidance_lists_only_loras_with_something_to_say(self):
        from routes.prompt_enhancement import _lora_guidance
        assert _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""}]) == ""
        g = _lora_guidance([{"name": "ultra real krea2", "trigger_words": [], "notes": ""},
                            {"name": "Wolf cut", "trigger_words": ["wolfcut"], "notes": ""}])
        assert "ultra real krea2" not in g and '"wolfcut"' in g and "never write a LoRA's name" in g


class TestArticles:
    def test_an_article_before_a_value_that_has_one_collapses(self):
        from prompt_programs.fill import tidy_text
        assert tidy_text(["A", "a spontaneous photo of a woman. She has a", "a warm smile."]) == "A spontaneous photo of a woman. She has a warm smile."
        assert tidy_text(["A cat and a dog"]) == "A cat and a dog"

    def test_a_joining_word_before_a_value_that_has_one_collapses(self):
        from prompt_programs.fill import tidy_text
        assert tidy_text(["A photo of a cat", "with", "with tufted ears", ", in", "in a sunlit garden", "."]) == \
            "A photo of a cat with tufted ears, in a sunlit garden."
        assert tidy_text(["A woman,", "her", "her chestnut hair", "loose."]) == "A woman, her chestnut hair loose."
        # only at a seam after a few joining words: a doubled word inside a part, or after a long part, is as written
        assert tidy_text(["They had had enough."]) == "They had had enough."
        assert tidy_text(["a tall man standing by the old harbor wall in", "in a red coat"]) == \
            "A tall man standing by the old harbor wall in in a red coat"


class TestOptionContinuity:
    def test_a_patched_program_keeps_the_pools_of_picks_it_didnt_touch(self):
        from prompt_programs.fill import PickSpec
        from prompt_programs.options import GeneratedOptions, ProgramContext

        spec = PickSpec("eye_color", "Eye Color", "her eye color", 2, "text", "pick", ["emerald green"], [])
        v1 = ProgramContext(key="p1", signature="a woman with {eyes}", template="a woman with {eyes}", lineage="p1")
        v2 = ProgramContext(key="p2", signature="a tall woman with {eyes}", template="a tall woman with {eyes}", lineage="p1")
        other = ProgramContext(key="p3", signature="a tall woman with {eyes}", template="a tall woman with {eyes}", lineage="p3")
        k1 = GeneratedOptions(None, v1)._where(spec, {})[1]
        assert GeneratedOptions(None, v2)._where(spec, {})[1] == k1      # same lineage: same options
        assert GeneratedOptions(None, other)._where(spec, {})[1] != k1   # a new prompt: its own

    def test_a_wildcard_in_the_users_words_bounds_its_options(self):
        from prompt_programs.fill import PickSpec
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



"""What the models are told about LoRAs, and the article and joining-word seams."""


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

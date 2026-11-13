"""The per-image improver's levels: length targets, the token clamp, a long prompt
still improved, and an unchanged answer accepted."""
from unittest.mock import AsyncMock

import pytest

import routes.prompt_enhancement as pe
from routes.prompt_enhancement import (
    ImprovePromptRequest,
    improve_max_tokens,
    improve_needed,
    fitted_target,
    length_target,
    prompt_length,
    style_guide,
)

SHORT = "a woman reading in a laundromat at night"
LONG = " ".join(["word"] * 150)


@pytest.fixture
def llm(monkeypatch):
    import llm_resolver

    async def fake_llm_config(role, project_id=None):
        return {"provider": "test"}

    complete = AsyncMock(return_value="a rewritten prompt")
    monkeypatch.setattr(llm_resolver, "get_effective_llm_config", fake_llm_config)
    monkeypatch.setattr(pe, "llm_complete_text", complete)
    return complete


def test_targets_by_mode_and_level():
    assert length_target("prose", "fill") == (50, 80, "words")
    assert length_target("prose", "expand", "flux-1-dev") == (80, 120, "words")
    assert length_target("krea-2", "expand") == (120, 180, "words")
    assert length_target("keyword", "fill") == (15, 25, "tags")
    assert length_target("ltx-2.5", "fill") == (2, 4, "sentences")
    assert length_target("prose", None) == length_target("prose", "expand")
    assert length_target("prose", "off") is None
    assert length_target("edit", "expand") is None


def test_length_counts_words_tags_and_sentences_without_comments_or_marks():
    assert prompt_length("a ⟦young woman⟧ reads\n# keep it dim", "words") == 4
    assert prompt_length("1girl, red hair, , forest", "tags") == 3
    assert prompt_length("She walks in. The camera holds! Rain falls", "sentences") == 3


def test_short_prose_prompt_is_improved():
    assert improve_needed(SHORT, "prose", "expand")
    assert improve_needed(SHORT, "krea-2", "fill")


def test_a_long_prompt_is_still_improved():
    for mode in ("prose", "krea-2", "qwen-image-2.1", "keyword", "minimax-h3", "edit"):
        assert improve_needed(LONG, mode, "fill") and improve_needed(LONG, mode, "expand")


def test_a_long_prompt_keeps_its_length_and_gets_the_levels_room():
    assert fitted_target((50, 80, "words"), SHORT) == (50, 80, "words")
    assert fitted_target((50, 80, "words"), LONG) == (50, 180, "words")
    assert fitted_target((50, 80, "words"), " ".join(["word"] * 55)) == (50, 85, "words")
    assert fitted_target(None, LONG) is None


def test_off_runs_only_where_the_model_needs_its_format():
    assert not improve_needed(SHORT, "prose", "off")
    assert not improve_needed(SHORT, "keyword", "off")
    assert improve_needed(SHORT, "minimax-h3", "off")


def test_classic_improve_always_runs():
    assert improve_needed(LONG, "prose", None)


def test_max_tokens_follow_the_target():
    assert improve_max_tokens((50, 80, "words")) == 260
    assert improve_max_tokens((30, 45, "tags")) == 450
    assert improve_max_tokens((2, 4, "sentences")) == 350
    assert improve_max_tokens((1, 2, "words")) == 256
    assert improve_max_tokens(None) == 8192


async def test_long_prompt_is_improved_and_told_to_keep_what_it_has(llm):
    result = await pe.improve_prompt(ImprovePromptRequest(prompt=LONG, model="krea-2-turbo", level="fill"), None)
    assert result.improved_prompt == "a rewritten prompt"
    assert llm.await_args.kwargs["max_tokens"] == improve_max_tokens((50, 180, "words"))
    system = llm.await_args.kwargs["messages"][0]["content"]
    assert "Length: at most about 180 words." in system
    assert system.endswith("The prompt is already long: keep every thing it names, make it read as one clear "
                           "description, and add only the concrete things the picture still lacks.")


CEILING = "This is a ceiling, not a target: stop when nothing concrete is left to add, however short the prompt still is."


async def test_short_prompt_is_improved_with_a_clamped_budget(llm):
    result = await pe.improve_prompt(ImprovePromptRequest(prompt=SHORT, model="krea-2-turbo", level="fill"), None)
    assert result.improved_prompt == "a rewritten prompt"
    assert llm.await_args.kwargs["max_tokens"] == improve_max_tokens((50, 80, "words"))
    system = llm.await_args.kwargs["messages"][0]["content"]
    assert system.endswith(f"Length: at most about 80 words. {CEILING} If the prompt already names what the "
                           "picture needs, return it with only the changes this model's format needs.")
    assert "50" not in system.rsplit("Length:", 1)[1]  # the low end is never a quota


async def test_classic_improve_keeps_the_full_budget(llm):
    await pe.improve_prompt(ImprovePromptRequest(prompt=SHORT, model="krea-2-turbo"), None)
    assert llm.await_args.kwargs["max_tokens"] == 8192
    system = llm.await_args.kwargs["messages"][0]["content"]
    assert system.endswith(f"Length: at most about 180 words. {CEILING}")


async def test_unchanged_answer_is_accepted_on_the_late_path(llm):
    prompt = SHORT + "\n# keep it dim"
    llm.return_value = prompt
    result = await pe.improve_prompt(ImprovePromptRequest(prompt=prompt, model="flux1-dev", level="expand"), None)
    assert result.improved_prompt == prompt
    assert llm.await_count == 1


async def test_prose_at_off_makes_no_call(llm):
    result = await pe.improve_prompt(ImprovePromptRequest(prompt=SHORT, model="flux1-dev", level="off"), None)
    assert result.improved_prompt == SHORT
    llm.assert_not_awaited()


async def test_h3_at_off_keeps_the_users_words_in_its_format(llm, monkeypatch):
    seen = []

    async def recording_style_guide(request, session, fill=False, exact_canvas=True):
        seen.append(fill)
        return await style_guide(request, session, fill=fill, exact_canvas=exact_canvas)

    monkeypatch.setattr(pe, "style_guide", recording_style_guide)
    await pe.improve_prompt(ImprovePromptRequest(
        prompt=SHORT, model="minimax-h3", is_video=True, h3_task="t2va", h3_duration=5, level="off"), None)
    assert seen == [True] and llm.await_count == 1
    assert llm.await_args.kwargs["max_tokens"] == 8192
    system = llm.await_args.kwargs["messages"][0]["content"]
    assert "integrated_multimodal_description" in system


def test_level_is_validated():
    with pytest.raises(ValueError):
        ImprovePromptRequest(prompt="x", level="loud")


async def test_marked_values_get_their_rule_only_when_present():
    marked, _images, _mode = await style_guide(ImprovePromptRequest(
        prompt="a ⟦young woman⟧ reading", model="sdxl", marked=True), None)
    plain, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a young woman reading", model="sdxl"), None)
    assert "⟦ ⟧ marks" in marked and "own comma-separated tag" in marked
    assert "Text inside ⟦ ⟧ marks" not in plain


async def test_marked_rule_keeps_the_case_and_a_tag_value_whole():
    prose, _images, _mode = await style_guide(ImprovePromptRequest(
        prompt="a ⟦young woman⟧ reading", model="flux1-dev", marked=True), None)
    tags, _images, _mode = await style_guide(ImprovePromptRequest(
        prompt="a ⟦young woman⟧ reading", model="sdxl", marked=True), None)
    assert "with their capitals and lower case as given" in prose
    assert "kept whole however long it is" in tags and "kept whole however long it is" not in prose


async def test_the_levels_ask_for_different_amounts_of_detail(llm):
    systems = {}
    for model, level in (("flux1-dev", "fill"), ("flux1-dev", "expand"), ("sdxl", "fill"), ("sdxl", "expand")):
        await pe.improve_prompt(ImprovePromptRequest(prompt="a cat on a sofa", model=model, level=level), None)
        systems[model, level] = llm.await_args.kwargs["messages"][0]["content"]
    assert "Detail: Medium. Add the two or three" in systems["flux1-dev", "fill"]
    assert "Detail: High. Give the picture its full set" in systems["flux1-dev", "expand"]
    assert "Detail: Medium. Convert the request, then add the five to eight" in systems["sdxl", "fill"]
    assert "Detail: High. Convert the request, then add ten to twenty" in systems["sdxl", "expand"]
    for text in systems.values():  # the detail line comes before the ceiling, which still closes the guide
        assert text.index("Detail:") < text.index("Length: at most")


async def test_classic_improve_has_no_level_detail_line(llm):
    await pe.improve_prompt(ImprovePromptRequest(prompt="a cat on a sofa", model="flux1-dev"), None)
    assert "Detail:" not in llm.await_args.kwargs["messages"][0]["content"]


async def test_tag_model_request_asks_for_a_tag_list_with_additions(llm):
    await pe.improve_prompt(ImprovePromptRequest(prompt="a cat on a sofa", model="sdxl", level="fill"), None)
    user = llm.await_args.kwargs["messages"][1]["content"]
    assert user.startswith("Rewrite this image request as a tag list") and "light touch" not in user
    assert "add the concrete tags the picture is missing" in user and user.endswith("a cat on a sofa")

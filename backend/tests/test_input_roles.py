"""Edits whose input images are references for a new picture, not pictures to change.

The improver first asks what each input image is for, then writes an edit
instruction (some image changed) or the new picture the request describes (every
image a reference), told what each reference gives.
"""
import json

import pytest

import input_roles
from input_roles import CHANGE, REFERENCE, InputRole, parse_roles
from routes.prompt_enhancement import ImprovePromptRequest


def test_parse_roles_reads_one_role_per_image():
    text = 'Sure: {"images": [{"image": 2, "role": "change", "gives": "the picture being changed"},' \
           ' {"image": 1, "role": "Reference", "gives": "the woman: her face and look"}]}'
    assert parse_roles(text, 2) == [
        InputRole(1, REFERENCE, "the woman: her face and look"),
        InputRole(2, CHANGE, "the picture being changed"),
    ]


@pytest.mark.parametrize("text", [
    "no json here",
    '{"images": [{"image": 1, "role": "reference", "gives": "x"}]}',  # image 2 missing
    '{"images": [{"image": 1, "role": "style", "gives": "x"}, {"image": 2, "role": "change"}]}',
    '{"images": [{"image": 3, "role": "change"}, {"image": 1, "role": "change"}]}',
])
def test_parse_roles_rejects_an_answer_without_a_role_for_every_image(text):
    assert parse_roles(text, 2) is None


@pytest.fixture
def improver(monkeypatch, tmp_path):
    """The improver with a fake chat model: `answer["roles"]` is the classifier's
    reply; the rewrite returns "improved prompt". Records each call's messages."""
    import llm_resolver
    import routes.prompt_enhancement as pe

    calls = {"classify": [], "rewrite": [], "answer": None}

    async def fake_llm_config(role, project_id=None):
        return {"provider": "test"}

    async def fake_llm_complete_text(*, config, messages, max_tokens, temperature):
        if messages[0]["content"].startswith("You decide what each input image is for"):
            calls["classify"].append(messages)
            return calls["answer"]
        calls["rewrite"].append(messages)
        return "improved prompt"

    async def fake_source_image(session, media_id, prepared_path=None):
        return f"image-{media_id}"

    monkeypatch.setattr(llm_resolver, "get_effective_llm_config", fake_llm_config)
    monkeypatch.setattr(pe, "llm_complete_text", fake_llm_complete_text)
    monkeypatch.setattr("llm.llm_complete_text", fake_llm_complete_text)
    monkeypatch.setattr(pe, "_load_source_image_b64", fake_source_image)
    monkeypatch.setattr(input_roles, "_cache_dir", lambda: tmp_path / "input_roles")
    monkeypatch.setattr(input_roles, "_memory", {})
    return calls


def _answer(*roles):
    return json.dumps({"images": [{"image": i + 1, "role": r, "gives": g} for i, (r, g) in enumerate(roles)]})


async def test_all_references_writes_the_new_picture_in_the_models_own_guide(improver):
    import routes.prompt_enhancement as pe

    improver["answer"] = _answer((REFERENCE, "the woman: her face and look"))
    await pe.improve_prompt(ImprovePromptRequest(
        prompt="this woman walking down a rainy Tokyo street at night", model="qwen-image-2.1",
        input_image_count=1, input_media_ids=[11]), session=object())

    # The question is about the words alone; the writer got Qwen's text-to-image guide.
    classify = improver["classify"][0][1]["content"]
    assert isinstance(classify, str) and "this woman walking" in classify and "1 input image" in classify
    system, user = improver["rewrite"][0]
    assert "observer reporting what is in the frame" in system["content"]
    assert "editing instruction" not in system["content"]
    assert "- the image gives the woman: her face and look." in system["content"]
    assert "never the references'" in system["content"]
    # It describes the new picture from the words, not from looking at the reference.
    assert isinstance(user["content"], str)
    assert "reference-guided prompt" in user["content"]


async def test_a_mixed_request_stays_an_edit_and_says_which_image_gives_what(improver):
    import routes.prompt_enhancement as pe

    improver["answer"] = _answer((REFERENCE, "the woman"), (CHANGE, "the picture being changed"))
    await pe.improve_prompt(ImprovePromptRequest(
        prompt="put the woman from image 1 into image 2", model="qwen-image-2.1",
        input_image_count=2, input_media_ids=[11, 22]), session=object())

    system, user = improver["rewrite"][0]
    assert "editing instruction" in system["content"]
    text = user["content"][0]["text"]
    assert ("What each input is for: <image1> is a reference that gives the woman; "
            "<image2> is the picture being changed.") in text
    # Shown each image once, as before, labeled by its tag.
    assert [p["text"] for p in user["content"][1::2]] == ["<image1>:", "<image2>:"]


async def test_a_plain_edit_reads_as_before(improver):
    import routes.prompt_enhancement as pe

    improver["answer"] = _answer((CHANGE, "the picture being changed"))
    await pe.improve_prompt(ImprovePromptRequest(
        prompt="change the shirt to blue", model="nano-banana-pro-edit",
        input_image_count=1, input_media_ids=[11]), session=object())

    system, user = improver["rewrite"][0]
    assert user["content"] == "Refine this image-edit instruction:\n\nchange the shirt to blue"


async def test_generic_edit_models_write_references_as_prose_named_by_ordinal(improver):
    import routes.prompt_enhancement as pe

    improver["answer"] = _answer((REFERENCE, "the man"), (REFERENCE, "the woman"))
    await pe.improve_prompt(ImprovePromptRequest(
        prompt="these two sitting at a campfire", model="nano-banana-pro-edit",
        input_image_count=2, input_media_ids=[11, 22]), session=object())

    system, user = improver["rewrite"][0]
    assert "- the first image gives the man.\n- the second image gives the woman." in system["content"]
    assert user["content"].startswith("Rewrite this image request as a concrete visual description.")
    assert "The image model also receives the reference images the guide lists." in user["content"]


async def test_roles_are_asked_once_per_prompt_whatever_the_images(improver):
    import routes.prompt_enhancement as pe

    improver["answer"] = _answer((REFERENCE, "the woman"))
    request = ImprovePromptRequest(prompt="this woman on a beach", model="flux-3-klein",
                                   input_image_count=1, input_media_ids=[11])
    await pe.improve_prompt(request, session=object())
    await pe.improve_prompt(request, session=object())
    assert len(improver["classify"]) == 1
    assert len(improver["rewrite"]) == 2

    # A different image is not a different question; a different prompt is.
    await pe.improve_prompt(request.model_copy(update={"input_media_ids": [12]}), session=object())
    assert len(improver["classify"]) == 1
    await pe.improve_prompt(request.model_copy(update={"prompt": "make her hair red"}), session=object())
    assert len(improver["classify"]) == 2


async def test_roles_handed_down_from_the_submit_are_not_asked_again(improver):
    import routes.prompt_enhancement as pe

    await pe.improve_prompt(ImprovePromptRequest(
        prompt="this woman, in a red coat, on a beach", model="flux-3-klein", input_image_count=1,
        input_media_ids=[11], input_roles=[{"image": 1, "role": "reference", "gives": "the woman"}]),
        session=object())
    assert improver["classify"] == []
    system, _user = improver["rewrite"][0]
    assert "- the first image gives the woman." in system["content"]


async def test_an_unreadable_answer_degrades_to_an_edit_and_is_not_kept(improver):
    import routes.prompt_enhancement as pe

    improver["answer"] = "I think it's a reference"
    request = ImprovePromptRequest(prompt="this woman on a beach", model="flux-3-klein",
                                   input_image_count=1, input_media_ids=[11])
    await pe.improve_prompt(request, session=object())
    system, _user = improver["rewrite"][0]
    assert "prompt upsampler of an image-editing model" in system["content"]

    improver["answer"] = _answer((REFERENCE, "the woman"))
    await pe.improve_prompt(request, session=object())
    assert len(improver["classify"]) == 2

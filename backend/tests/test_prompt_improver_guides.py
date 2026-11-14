"""The per-model improve guides: fixed rules, a length line, and per-request parts last."""
import re

import pytest

from prompts import get_prompt
from routes.prompt_enhancement import ImprovePromptRequest, style_guide

_SLOT_RE = re.compile(
    r"\{(?:protected_text_guidance|length_target|canvas_guidance|flux3_canvas_guidance|audio_guidance|"
    r"input_images_desc|qwen_image_refs|flux3_image_refs|h3_task_guidance|h3_dialogue_guidance|"
    r"h3_audio_guidance|canvas)\}"
)
_IMPROVE_KEYS = [
    "improve_system_prompt", "improve_krea2_system_prompt", "improve_keyword_system_prompt",
    "improve_cinematography_system_prompt", "improve_cinematography_image_system_prompt",
    "improve_ltx_25_system_prompt", "improve_ltx_25_image_system_prompt",
    "improve_minimax_h3_system_prompt", "improve_qwen_image_21_system_prompt",
    "improve_qwen_image_21_edit_system_prompt", "improve_flux3_klein_system_prompt",
    "improve_flux3_klein_edit_system_prompt", "improve_image_edit_system_prompt",
    "improve_audio_system_prompt", "ideogram_json_system_prompt", "ideogram_json_refine_system_prompt",
]
# The guides that develop a picture: they carry the rules about people and a length line.
_IMAGE_KEYS = [
    "improve_system_prompt", "improve_krea2_system_prompt", "improve_keyword_system_prompt",
    "improve_cinematography_system_prompt", "improve_ltx_25_system_prompt",
    "improve_qwen_image_21_system_prompt", "improve_flux3_klein_system_prompt",
]


def _head(text: str) -> str:
    match = _SLOT_RE.search(text)
    return (text[:match.start()] if match else text).rstrip()


@pytest.mark.parametrize("key", _IMPROVE_KEYS)
def test_per_request_parts_close_every_guide(key):
    text = get_prompt("prompt_enhancement", key)
    assert text and _SLOT_RE.search(text), key
    # Everything after the first slot is short: slots and at most a couple of lines.
    assert len(text) - len(_head(text)) < 400, key


@pytest.mark.parametrize("key", _IMAGE_KEYS)
def test_image_guides_fix_the_people_and_close_on_the_length(key):
    text = get_prompt("prompt_enhancement", key)
    assert "people are fixed" in text.lower()
    assert text.rstrip().endswith("{length_target}")
    assert not re.search(r"\d{2,} ?(?:-|to) ?\d+ words", text), "lengths come from the slot, not the guide"


_MODELS = [
    ("flux1-dev", {}), ("krea2_turbo_fp8_scaled.safetensors", {}), ("sdxl_base_1.0", {}),
    ("qwen-image-2.1", {}), ("flux3-klein", {}), ("qwen-image-2.1", {"input_image_count": 2}),
    ("flux3-klein", {"input_image_count": 2}), ("flux1-dev", {"input_image_count": 1}),
    ("wan-2.2", {"is_video": True}), ("ltx-2.5", {"is_video": True}),
    ("some-audio-model", {"is_audio": True}),
    ("minimax-h3", {"is_video": True, "h3_task": "t2va", "h3_duration": 5}),
]


@pytest.mark.parametrize("model, extra", _MODELS)
async def test_guide_head_is_identical_across_requests(model, extra):
    """The text before the first per-request part is the same whatever the canvas,
    the prompt's protected spans or the LoRAs, so it can be cached as a prefix."""
    first, _images, mode = await style_guide(ImprovePromptRequest(
        prompt="a fox in snow", model=model, width=1920, height=1080, **extra), None)
    second, _images, _mode = await style_guide(ImprovePromptRequest(
        prompt='a fox [in snow]\n# keep it quiet\nshe says "hello"', model=model, width=832, height=1248,
        audio_conditioned=True, lora_context=[{"name": "x", "trigger_words": ["ohwx"], "notes": ""}],
        **{**extra, "h3_generate_audio": False}), None)
    from routes.prompt_enhancement import _IMPROVE_PROMPT_BY_MODE
    head = _head(get_prompt("prompt_enhancement", _IMPROVE_PROMPT_BY_MODE.get(mode, "improve_system_prompt")))
    assert len(head) > 200
    assert first.startswith(head) and second.startswith(head), mode
    assert first != second


async def test_classic_guide_closes_on_the_high_length_without_the_as_is_rule():
    text, _images, mode = await style_guide(ImprovePromptRequest(prompt="a cat", model="qwen-image-2.1"), None)
    assert mode == "qwen-image-2.1"
    assert text.endswith("Length: at most about 350 words. This is a ceiling, not a target: stop when nothing concrete is left to add, however short the prompt still is.")
    text, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a cat", model="ltx-2.5", is_video=True), None)
    assert text.endswith("Length: at most 8 sentences. This is a ceiling, not a target: stop when nothing concrete is left to add, however short the prompt still is.")
    flux, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a cat", model="flux1-dev"), None)
    other, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a cat", model="seedream-4"), None)
    assert "Length: at most about 120 words." in flux and "Length: at most about 160 words." in other


async def test_image_guides_treat_length_as_a_ceiling_and_light_as_given():
    """The image guides never ask the model to pad: length is a ceiling, and light
    is written only when the prompt names it."""
    for model in ("flux1-dev", "seedream-4", "krea-2-turbo", "sd_xl_base_1.0", "qwen-image-2.1", "flux-3-klein"):
        text, _images, mode = await style_guide(ImprovePromptRequest(prompt="a cat", model=model), None)
        assert "This is a ceiling, not a target" in text, mode
        assert "one light that suits" not in text and "a light that suits" not in text, mode


async def test_guides_without_a_length_say_nothing_about_it():
    text, _images, mode = await style_guide(ImprovePromptRequest(prompt="make it blue", model="flux1-dev",
                                                                 input_image_count=1), None)
    assert mode == "edit" and "Length:" not in text and "{" not in text


async def test_prose_guides_write_tags_out_as_words_and_keep_light_and_people_as_given():
    for model in ("flux1-dev", "krea-2-turbo", "qwen-image-2.1", "flux-3-klein"):
        text, _images, mode = await style_guide(ImprovePromptRequest(prompt="1girl, rooftop", model=model), None)
        assert "is written out in plain words" in text or "write each tag as the plain words" in text, mode
        assert "add nothing about the person they do not state" in text, mode
    for model in ("flux1-dev", "krea-2-turbo"):
        text, _images, mode = await style_guide(ImprovePromptRequest(prompt="a porch", model=model), None)
        assert "write no word about light at all" in text, mode
        assert "never write that someone is absent" not in text  # that reminder is in the request, not the guide
        assert "Never write what the picture does not have" in text, mode


async def test_tag_guide_gives_a_peopleless_request_no_humans():
    text, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a lighthouse", model="sdxl"), None)
    assert '"no humans, scenery"' in text


def test_trigger_words_sit_in_a_grammatical_sentence_or_their_own_tag():
    from routes.prompt_enhancement import _lora_guidance
    lora = [{"name": "subject", "trigger_words": ["ohwx"], "notes": ""}]
    prose = _lora_guidance(lora)
    tags = _lora_guidance(lora, keyword_mode=True)
    assert '"ohwx"' in prose and "grammatical sentence" in prose and "own tag" not in prose
    assert '"ohwx"' in tags and "a tag of its own" in tags and "grammatical sentence" not in tags


async def test_image_guides_make_a_picture_a_photo_unless_something_sets_another_look():
    """One rule in every still-image guide: unstyled is a photo; a medium, a made
    thing, anime tags, a note or the model itself sets another look instead."""
    for model in ("flux1-dev", "seedream-4", "krea-2-turbo"):
        text, _images, mode = await style_guide(ImprovePromptRequest(prompt="a dog on a porch", model=model), None)
        assert "A picture is a photo unless something says otherwise" in text, mode
        assert "A fantasy subject" in text and "never anime or an illustration" in text, mode
        assert '"A photo of" in front of another medium or a made thing' in text, mode
        assert "does not make a picture a photo" in text, mode  # a drawn camera angle or light
        assert "neither do you" not in text, mode
    tags, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a dog", model="sdxl"), None)
    assert 'the last tag is "photo"' in tags
    qwen, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a dog", model="qwen-image-2.1"), None)
    assert "is a photograph, a fantasy subject included" in qwen
    klein, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a dog", model="flux-3-klein"), None)
    assert "it is a photograph, a fantasy subject included" in klein


async def test_a_model_made_for_anime_pictures_is_never_called_a_photo():
    from model_family import is_non_photo_model
    assert is_non_photo_model("anima-preview3-base.safetensors") and is_non_photo_model("waiIllustriousSDXL_v150")
    assert not is_non_photo_model("animal-xl") and not is_non_photo_model("krea2_turbo") and not is_non_photo_model(None)
    anime, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a dog on a porch", model="Anima"), None)
    photo, _images, _mode = await style_guide(ImprovePromptRequest(prompt="a dog on a porch", model="flux1-dev"), None)
    assert "This image model draws anime-style illustrations, not photos" in anime
    assert "This image model draws" not in photo
    edit, _images, _mode = await style_guide(ImprovePromptRequest(prompt="make it blue", model="Anima",
                                                                  input_image_count=1), None)
    assert "This image model draws" not in edit


async def test_the_improve_request_says_a_picture_is_a_photo_unless_told_otherwise(monkeypatch):
    import routes.prompt_enhancement as pe
    sent = []

    async def complete(config=None, messages=None, **kw):
        sent.append(messages[-1]["content"])
        return "A photo of a dog on a porch."

    async def cfg(*a, **k):
        return None
    monkeypatch.setattr(pe, "llm_complete_text", complete)
    monkeypatch.setattr("llm_resolver.get_effective_llm_config", cfg)
    for model in ("flux1-dev", "sdxl"):
        await pe.improve_prompt(ImprovePromptRequest(prompt="a dog on a porch", model=model, level="fill"), None)
    assert "Say that it is a photo unless something in it implies another look" in sent[0]
    assert 'End with "photo" unless something in it implies another look' in sent[1]
    await pe.improve_prompt(ImprovePromptRequest(prompt="a dog on a porch", model="Anima", level="fill"), None)
    assert "draws anime-style illustrations, so never call it a photo" in sent[2] and "Say that it is a photo" not in sent[2]

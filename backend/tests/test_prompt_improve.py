"""Unit tests for the /improve protected-text tailoring + placeholder safety net.

Covers the bug where a plain prose prompt (no brackets/wildcards) was enhanced
into one containing a hallucinated ``__VERBATIM_A__`` token, which then reached
the image model and failed the job with 'Invalid params'.
"""
import pytest

from routes.prompt_enhancement import (
    _protected_text_guidance,
    _strip_hallucinated_placeholders,
    _input_images_phrase,
    enhancement_mode,
    ImprovePromptRequest,
)
from model_family import model_family


@pytest.fixture
def prompt_variant_probe(monkeypatch):
    """Capture the actual system prompt key/messages selected by improve_prompt."""
    import llm_resolver
    import routes.prompt_enhancement as pe

    seen = {"prompt_keys": [], "messages": None}

    async def fake_llm_config(role):
        assert role == "agent-fast"
        return {"provider": "test"}

    def fake_get_prompt(namespace, key):
        assert namespace == "prompt_enhancement"
        seen["prompt_keys"].append(key)
        return f"SYSTEM_KEY:{key}\n{{input_images_desc}}\n{{protected_text_guidance}}"

    async def fake_llm_complete_text(*, config, messages, max_tokens, temperature):
        seen["messages"] = messages
        return "improved prompt"

    monkeypatch.setattr(llm_resolver, "get_effective_llm_config", fake_llm_config)
    monkeypatch.setattr(pe, "get_prompt", fake_get_prompt)
    monkeypatch.setattr(pe, "llm_complete_text", fake_llm_complete_text)
    return seen


# --- enhancement_mode: image-edit routing -----------------------------------

def test_edit_mode_for_natural_language_model_with_input_images():
    # nano-banana / gemini / flux-kontext etc. all classify to prose families;
    # input images flip them to the edit style.
    assert enhancement_mode(model_family("nano-banana-pro-edit"), is_image_edit=True) == "edit"
    assert enhancement_mode(model_family("gemini-3-pro-image"), is_image_edit=True) == "edit"


def test_no_input_images_stays_prose():
    assert enhancement_mode(model_family("nano-banana-pro-edit"), is_image_edit=False) == "prose"


def test_video_wins_over_edit():
    assert enhancement_mode(model_family("wan-2.7"), is_video=True, is_image_edit=True) == "cinematography"


def test_audio_mode_is_task_driven():
    # Any audio tool gets the sound-focused style regardless of the model string.
    assert enhancement_mode(model_family("some-tts-model"), is_audio=True) == "audio"
    assert enhancement_mode("unknown", is_audio=True) == "audio"


def test_audio_wins_over_video_and_edit():
    # A tool outputs one media type; if is_audio is set it takes precedence.
    assert enhancement_mode(
        model_family("wan-2.7"), is_video=True, is_image_edit=True, is_audio=True
    ) == "audio"


def test_improve_request_defaults_is_audio_false():
    assert ImprovePromptRequest(prompt="x").is_audio is False


def test_keyword_and_ideogram_keep_style_when_editing():
    # SD img2img describes the target (keyword); Ideogram has its own JSON path —
    # neither switches to the edit instruction style just because images are present.
    assert enhancement_mode(model_family("sdxl"), is_image_edit=True) == "keyword"
    assert enhancement_mode(model_family("ideogram"), is_image_edit=True) == "ideogram"


def test_improve_request_defaults_input_image_count_zero():
    assert ImprovePromptRequest(prompt="x").input_image_count == 0


@pytest.mark.parametrize(
    ("improve_request", "expected_prompt_key", "expected_user_prefix"),
    [
        (
            ImprovePromptRequest(prompt="a beautiful handbag", model="flux1-dev", input_image_count=0),
            "improve_system_prompt",
            "Please improve this prompt with a light touch:",
        ),
        (
            ImprovePromptRequest(prompt="1girl, handbag", model="sdxl_base_1.0.safetensors", input_image_count=0),
            "improve_keyword_system_prompt",
            "Please improve this prompt with a light touch:",
        ),
        (
            ImprovePromptRequest(prompt="put the handbag on the table", model="flux1-dev", input_image_count=1),
            "improve_image_edit_system_prompt",
            "Refine this image-edit instruction:",
        ),
        (
            ImprovePromptRequest(prompt="slow dolly in", model="some-unknown-model", is_video=True, input_image_count=1),
            "improve_cinematography_system_prompt",
            "Please improve this prompt with a light touch:",
        ),
        (
            ImprovePromptRequest(prompt="soft leather rustle", model="some-unknown-model", is_audio=True),
            "improve_audio_system_prompt",
            "Please improve this prompt with a light touch:",
        ),
    ],
)
async def test_improve_prompt_selects_expected_variant_without_source_image(
    improve_request, expected_prompt_key, expected_user_prefix, prompt_variant_probe
):
    import routes.prompt_enhancement as pe

    response = await pe.improve_prompt(improve_request, session=None)

    assert response.improved_prompt == "improved prompt"
    assert prompt_variant_probe["prompt_keys"] == [expected_prompt_key]
    assert prompt_variant_probe["messages"][0]["content"].startswith(f"SYSTEM_KEY:{expected_prompt_key}")
    assert prompt_variant_probe["messages"][1]["content"].startswith(expected_user_prefix)


async def test_improve_prompt_selects_i2v_source_image_variant(prompt_variant_probe, monkeypatch):
    import routes.prompt_enhancement as pe

    async def fake_source_image(session, media_id):
        assert media_id == 123
        return "abc123"

    monkeypatch.setattr(pe, "_load_source_image_b64", fake_source_image)

    response = await pe.improve_prompt(
        ImprovePromptRequest(
            prompt="slow dolly in toward the handbag",
            model="some-unknown-model",
            is_video=True,
            media_id=123,
        ),
        session=object(),
    )

    assert response.improved_prompt == "improved prompt"
    assert prompt_variant_probe["prompt_keys"] == ["improve_cinematography_image_system_prompt"]
    user_content = prompt_variant_probe["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "text"
    assert "first frame" in user_content[0]["text"]
    assert user_content[1]["image_url"]["url"] == "data:image/jpeg;base64,abc123"


# --- _input_images_phrase ----------------------------------------------------

def test_input_images_phrase():
    assert _input_images_phrase(0) == "an input image"
    assert _input_images_phrase(1) == "an input image"
    assert _input_images_phrase(2) == "2 input images"
    assert _input_images_phrase(3) == "3 input images"


# --- _protected_text_guidance: only describe spans that are present ---------

def test_guidance_empty_for_plain_prose():
    # The reported case: no brackets, wildcards, comments, or placeholders.
    prompt = "Show me how this artwork would look in my living room above the couch"
    assert _protected_text_guidance(prompt) == ""


def test_guidance_mentions_only_placeholders_when_only_placeholders():
    g = _protected_text_guidance("a portrait of __VERBATIM_A__ in a garden")
    assert "PRESERVING PROTECTED TEXT" in g
    assert "__VERBATIM_A__" in g
    # No bracket/wildcard/comment bullets — none are present.
    assert "[Bracketed text]" not in g
    assert "wildcards" not in g
    assert "Lines starting with '#'" not in g


def test_guidance_mentions_only_brackets_when_only_brackets():
    g = _protected_text_guidance("a [neon sign] over the door")
    assert "[Bracketed text]" in g
    assert "__VERBATIM_" not in g
    assert "wildcards" not in g


def test_guidance_detects_inline_and_named_wildcards():
    assert "wildcards" in _protected_text_guidance("hair is {red|blue|green}")
    assert "wildcards" in _protected_text_guidance("wearing a {{outfit}}")


def test_guidance_detects_comment_lines():
    g = _protected_text_guidance("a castle\n# keep it gloomy")
    assert "Lines starting with '#'" in g


def test_guidance_combines_present_spans():
    g = _protected_text_guidance("[logo] and __VERBATIM_A__ with {a|b}\n# note")
    for fragment in ("__VERBATIM_A__", "[Bracketed text]", "wildcards", "Lines starting with '#'"):
        assert fragment in g


def test_guidance_keyword_mode_adds_tag_nuance():
    g = _protected_text_guidance("[blue car]", keyword_mode=True)
    assert "each as its own comma-separated tag" in g
    # Prose mode does not add that nuance.
    assert "each as its own comma-separated tag" not in _protected_text_guidance("[blue car]")


# --- _strip_hallucinated_placeholders: drop invented tokens -----------------

def test_strip_removes_token_absent_from_input():
    # The exact failure: input had no placeholder, output invented one.
    src = "Show me how this artwork would look in my living room above the couch"
    out = "Centered on the wall above the couch is __VERBATIM_A__. Soft natural light."
    cleaned = _strip_hallucinated_placeholders(out, src)
    assert "__VERBATIM_A__" not in cleaned
    # Surrounding text survives and whitespace is tidied (no " ." artifact).
    assert "Soft natural light." in cleaned
    assert " ." not in cleaned


def test_strip_preserves_legitimate_token():
    src = "a portrait of __VERBATIM_A__"
    out = "a detailed studio portrait of __VERBATIM_A__"
    assert _strip_hallucinated_placeholders(out, src) == out


def test_strip_keeps_real_drops_invented_when_mixed():
    src = "scene with __VERBATIM_A__"
    out = "scene with __VERBATIM_A__ next to __VERBATIM_B__"
    cleaned = _strip_hallucinated_placeholders(out, src)
    assert "__VERBATIM_A__" in cleaned
    assert "__VERBATIM_B__" not in cleaned


def test_strip_noop_when_no_tokens():
    out = "a perfectly ordinary improved prompt"
    assert _strip_hallucinated_placeholders(out, "an ordinary prompt") == out


def test_strip_does_not_merge_across_newlines():
    src = "a castle"
    out = "a castle __VERBATIM_A__\n# keep it gloomy"
    cleaned = _strip_hallucinated_placeholders(out, src)
    assert "__VERBATIM_A__" not in cleaned
    # The comment line stays on its own line — the token's whitespace cleanup
    # must not pull the next line up.
    assert "\n# keep it gloomy" in cleaned

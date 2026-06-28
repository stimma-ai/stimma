"""Unit tests for the /improve protected-text tailoring + placeholder safety net.

Covers the bug where a plain prose prompt (no brackets/wildcards) was enhanced
into one containing a hallucinated ``__VERBATIM_A__`` token, which then reached
the image model and failed the job with 'Invalid params'.
"""
from routes.prompt_enhancement import (
    _protected_text_guidance,
    _strip_hallucinated_placeholders,
    _input_images_phrase,
    enhancement_mode,
    ImprovePromptRequest,
)
from model_family import model_family


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


def test_keyword_and_ideogram_keep_style_when_editing():
    # SD img2img describes the target (keyword); Ideogram has its own JSON path —
    # neither switches to the edit instruction style just because images are present.
    assert enhancement_mode(model_family("sdxl"), is_image_edit=True) == "keyword"
    assert enhancement_mode(model_family("ideogram"), is_image_edit=True) == "ideogram"


def test_improve_request_defaults_input_image_count_zero():
    assert ImprovePromptRequest(prompt="x").input_image_count == 0


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

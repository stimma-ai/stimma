"""Unit tests for the /improve protected-text tailoring + placeholder safety net.

Covers the bug where a plain prose prompt (no brackets/wildcards) was enhanced
into one containing a hallucinated ``__VERBATIM_A__`` token, which then reached
the image model and failed the job with 'Invalid params'.
"""
import pytest

from routes.prompt_enhancement import (
    _audio_guidance,
    _h3_audio_guidance,
    _h3_dialogue_guidance,
    _h3_input_has_dialogue,
    _h3_task_guidance,
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

    async def fake_llm_config(role, project_id=None):
        assert role == "tool_assistant"
        return {"provider": "test"}

    def fake_get_prompt(namespace, key):
        assert namespace == "prompt_enhancement"
        seen["prompt_keys"].append(key)
        return f"SYSTEM_KEY:{key}\n{{input_images_desc}}\n{{audio_guidance}}\n{{protected_text_guidance}}"

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


def test_minimax_h3_gets_structured_video_mode():
    assert enhancement_mode(model_family("minimax-h3-i2v"), is_video=True) == "minimax-h3"


def test_qwen_image_21_has_its_own_generate_and_edit_modes():
    family = model_family("qwen-image-2.1")
    assert enhancement_mode(family) == "qwen-image-2.1"
    assert enhancement_mode(family, is_image_edit=True) == "qwen-image-2.1-edit"
    # Older Qwen-Image lines keep the generic styles.
    assert enhancement_mode(model_family("qwen-image-2512")) == "prose"


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
        (
            ImprovePromptRequest(
                prompt="a baker opens the shop",
                model="minimax-h3-t2v",
                is_video=True,
                h3_task="t2va",
                h3_duration=5,
            ),
            "improve_minimax_h3_system_prompt",
            "Rewrite this request as MiniMax H3 T2VA Context-IR",
        ),
        (
            ImprovePromptRequest(prompt="a tea shop poster", model="qwen-image-2.1"),
            "improve_qwen_image_21_system_prompt",
            "Rewrite this request as a Qwen-Image-2.1 text-to-image prompt.",
        ),
        (
            ImprovePromptRequest(prompt="make the mug blue", model="qwen-image-2.1", input_image_count=1),
            "improve_qwen_image_21_edit_system_prompt",
            "Rewrite this Qwen-Image-2.1 edit request. The model receives one input image.",
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


async def test_h3_fl2va_attaches_both_frames_in_order(prompt_variant_probe, monkeypatch):
    import routes.prompt_enhancement as pe

    async def fake_source_image(session, media_id):
        return f"image-{media_id}"

    monkeypatch.setattr(pe, "_load_source_image_b64", fake_source_image)
    await pe.improve_prompt(
        ImprovePromptRequest(
            prompt="she opens the umbrella",
            model="minimax-h3-i2v",
            is_video=True,
            h3_task="fl2va",
            h3_duration=8,
            h3_media_ids=[11, 22],
        ),
        session=object(),
    )

    assert prompt_variant_probe["prompt_keys"] == ["improve_minimax_h3_system_prompt"]
    content = prompt_variant_probe["messages"][1]["content"]
    assert "FL2VA Context-IR for a 8.00-second" in content[0]["text"]
    assert [part["text"] for part in content[1::2]] == [
        "Picture 1 (first frame):",
        "Picture 2 (last frame):",
    ]
    assert [part["image_url"]["url"] for part in content[2::2]] == [
        "data:image/jpeg;base64,image-11",
        "data:image/jpeg;base64,image-22",
    ]


def test_h3_task_guidance_uses_exact_alignment_and_duration():
    i2va = _h3_task_guidance("i2va", 5)
    assert "at 0.00 seconds" in i2va
    assert "<Picture 1> (from [Shot 1]) is fully referenced" in i2va
    fl2va = _h3_task_guidance("fl2va", 8)
    assert "Picture 2 (from Shot N)" in fl2va
    assert "8.00-second mark" in fl2va
    l2va = _h3_task_guidance("l2va", 6.5)
    assert "6.50-second mark" in l2va


def test_h3_reference_guidance_preserves_exact_model_order_and_roles():
    manifest = [
        {"label": "Picture 1", "kind": "image", "index": 0},
        {"label": "Audio 1", "kind": "video_audio", "index": 0},
        {"label": "Video 1", "kind": "video", "index": 0},
        {"label": "Audio 2", "kind": "audio", "index": 0},
    ]

    guidance = _h3_task_guidance("ref2va", 8, manifest)

    positions = [guidance.index(f"<{item['label']}>") for item in manifest]
    assert positions == sorted(positions)
    assert "soundtrack extracted from the same-numbered reference video" in guidance
    assert "standalone reference audio" in guidance
    assert "Do not write first-frame, last-frame, or timeline-alignment" in guidance
    assert "Use every listed tag at least once" in guidance


def test_h3_audio_disabled_keeps_schema_but_forces_na():
    guidance = _h3_audio_guidance(False)
    assert "overall_soundscape: N/A" in guidance
    assert "non_diegetic_music: N/A" in guidance


def test_h3_dialogue_guidance_is_conditional():
    silent = _h3_dialogue_guidance('a storefront sign reads "OPEN LATE"')
    assert "NO DIALOGUE" in silent
    assert "Exact words" not in silent
    assert not _h3_input_has_dialogue("a woman with no dialogue waves")
    assert not _h3_input_has_dialogue('a sign says "OPEN LATE"')
    assert not _h3_input_has_dialogue("two people talking across a table")

    spoken = _h3_dialogue_guidance('a woman says "Welcome."')
    assert "PRESERVING DIALOGUE" in spoken
    assert "<d>[Language] ...</d>" in spoken
    assert _h3_input_has_dialogue("WOMAN: Welcome.")


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


# --- audio conditioning: the soundtrack is supplied, not generated -----------

def test_improve_request_defaults_audio_conditioned_false():
    assert ImprovePromptRequest(prompt="x").audio_conditioned is False


def test_audio_guidance_generated_tells_the_model_to_render_the_sound():
    text = _audio_guidance(audio_conditioned=False, image_variant=False)
    assert "render dialogue and audio" in text
    assert "not visible:" in text  # no "in the frame" for the text-only variant


def test_audio_guidance_generated_image_variant_says_in_the_frame():
    text = _audio_guidance(audio_conditioned=True, image_variant=True)
    assert "supplied the soundtrack" in text
    text = _audio_guidance(audio_conditioned=False, image_variant=True)
    assert "not visible in the frame:" in text


def test_audio_guidance_supplied_forbids_inventing_sound():
    text = _audio_guidance(audio_conditioned=True, image_variant=False)
    assert "reproduces that track exactly" in text
    assert "Don't write sound effects" in text
    # It must not still be telling the model it renders audio.
    assert "render dialogue and audio" not in text


async def test_improve_prompt_swaps_audio_guidance_when_track_supplied(prompt_variant_probe):
    import routes.prompt_enhancement as pe

    await pe.improve_prompt(
        ImprovePromptRequest(
            prompt="she turns toward the camera",
            model="ltx-2.3", is_video=True, audio_conditioned=True,
        ),
        session=None,
    )
    system = prompt_variant_probe["messages"][0]["content"]
    assert "supplied the soundtrack" in system
    assert "render dialogue and audio" not in system


async def test_improve_prompt_keeps_generated_audio_guidance_by_default(prompt_variant_probe):
    import routes.prompt_enhancement as pe

    await pe.improve_prompt(
        ImprovePromptRequest(prompt="she turns toward the camera", model="ltx-2.3", is_video=True),
        session=None,
    )
    system = prompt_variant_probe["messages"][0]["content"]
    assert "render dialogue and audio" in system
    assert "supplied the soundtrack" not in system


def test_dialogue_bullet_drops_the_voicing_claim_when_audio_is_supplied():
    prompt = 'she says, "we are closing now"'
    generated = _protected_text_guidance(prompt, cinematography=True)
    supplied = _protected_text_guidance(prompt, cinematography=True, audio_conditioned=True)
    assert "content the video model voices" in generated
    assert "content the video model voices" not in supplied
    # Either way the words themselves must be preserved.
    assert "keep the spoken words exactly as written" in supplied
    assert "supplied audio" in supplied


async def test_qwen_image_21_edit_shows_references_labeled_by_position(prompt_variant_probe, monkeypatch):
    import routes.prompt_enhancement as pe

    async def fake_source_image(session, media_id):
        return f"image-{media_id}"

    monkeypatch.setattr(pe, "_load_source_image_b64", fake_source_image)
    await pe.improve_prompt(
        ImprovePromptRequest(
            prompt="put the jacket from image 3 on the man",
            model="qwen-image-2.1",
            input_image_count=3,
            # A non-library input keeps its slot so numbering holds.
            input_media_ids=[11, None, 33],
        ),
        session=object(),
    )

    assert prompt_variant_probe["prompt_keys"] == ["improve_qwen_image_21_edit_system_prompt"]
    content = prompt_variant_probe["messages"][1]["content"]
    assert "3 input images, <image1>, <image2> and <image3> (attached below, labeled)" in content[0]["text"]
    assert [part["text"] for part in content[1::2]] == ["<image1>:", "<image3>:"]
    assert [part["image_url"]["url"] for part in content[2::2]] == [
        "data:image/jpeg;base64,image-11",
        "data:image/jpeg;base64,image-33",
    ]


def test_qwen_canvas_guidance_names_orientation_only_when_known():
    from routes.prompt_enhancement import _qwen_canvas_guidance

    assert _qwen_canvas_guidance(None, None) == ""
    assert "wide (landscape)" in _qwen_canvas_guidance(2752, 1536)
    assert "vertical (portrait)" in _qwen_canvas_guidance(1696, 2528)
    assert "square" in _qwen_canvas_guidance(2048, 2048)

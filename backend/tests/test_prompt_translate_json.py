"""Unit tests for the translate + Ideogram-JSON prompt endpoints' helpers/models."""
import json

import pytest

from routes.prompt_enhancement import (
    _extract_json_object,
    _canvas_description,
    _looks_like_ideogram_json,
    _load_source_image_b64,
    enhancement_mode,
    ImprovePromptRequest,
    TranslatePromptRequest,
    TranslatePromptResponse,
    IdeogramJsonRequest,
    IdeogramJsonResponse,
)
from model_family import model_family


def test_extract_json_object_plain():
    raw = '{"high_level_description": "a cat", "style_description": {}}'
    out = _extract_json_object(raw)
    assert json.loads(out)["high_level_description"] == "a cat"


def test_extract_json_object_strips_fences():
    raw = 'Here you go:\n```json\n{"a": 1, "b": [1, 2]}\n```\nThanks!'
    out = _extract_json_object(raw)
    assert json.loads(out) == {"a": 1, "b": [1, 2]}


def test_extract_json_object_strips_bare_fences():
    raw = '```\n{"a": 1}\n```'
    assert json.loads(_extract_json_object(raw)) == {"a": 1}


def test_extract_json_object_handles_surrounding_prose():
    raw = 'Sure! {"a": {"nested": true}} hope that helps'
    assert json.loads(_extract_json_object(raw)) == {"a": {"nested": True}}


def test_extract_json_object_preserves_non_ascii():
    raw = '{"text": "一只猫"}'
    out = _extract_json_object(raw)
    # ensure_ascii=False keeps CJK legible rather than \uXXXX-escaped.
    assert "一只猫" in out
    assert json.loads(out)["text"] == "一只猫"


def test_extract_json_object_raises_on_invalid():
    with pytest.raises(json.JSONDecodeError):
        _extract_json_object("this is not json at all")


def test_translate_request_model():
    req = TranslatePromptRequest(prompt="a red car", target_language="Simplified Chinese")
    assert req.prompt == "a red car"
    assert req.target_language == "Simplified Chinese"


def test_translate_response_model():
    assert TranslatePromptResponse(translated_prompt="一辆红色的汽车").translated_prompt == "一辆红色的汽车"


def test_ideogram_json_models():
    assert IdeogramJsonRequest(prompt="a poster").prompt == "a poster"
    assert IdeogramJsonResponse(json_prompt="{}").json_prompt == "{}"
    # Size is optional and threads through for layout-aware bboxes.
    req = IdeogramJsonRequest(prompt="a poster", width=2880, height=1440)
    assert req.width == 2880 and req.height == 1440


def test_canvas_description_landscape_reduces_ratio():
    desc = _canvas_description(2880, 1440)
    assert "2880×1440px" in desc and "landscape" in desc and "2:1" in desc


def test_canvas_description_portrait_and_square():
    assert "portrait" in _canvas_description(1440, 2880)
    sq = _canvas_description(2048, 2048)
    assert "square" in sq and "1:1" in sq


def test_canvas_description_falls_back_when_unknown():
    for w, h in [(None, None), (0, 100), (100, 0)]:
        assert "1:1 square canvas" in _canvas_description(w, h)


# --- Family-aware enhancement routing ---

def test_improve_request_carries_model_and_media_id():
    req = ImprovePromptRequest(prompt="a cat")
    assert req.model is None and req.media_id is None
    req = ImprovePromptRequest(prompt="a cat", model="ltxv-2.3", media_id=42)
    assert req.model == "ltxv-2.3" and req.media_id == 42


class _FakeSession:
    def __init__(self, item):
        self._item = item

    async def get(self, _model, _media_id):
        return self._item


class _FakeMedia:
    def __init__(self, file_path, file_format):
        self.file_path = file_path
        self.file_format = file_format


@pytest.mark.asyncio
async def test_load_source_image_b64_best_effort_guards():
    # Missing media item -> None
    assert await _load_source_image_b64(_FakeSession(None), 1) is None
    # Non-raster / video format -> None (never handed to a VLM)
    assert await _load_source_image_b64(_FakeSession(_FakeMedia("/x.mp4", "mp4")), 1) is None
    # Raster format but file doesn't exist -> None
    assert await _load_source_image_b64(_FakeSession(_FakeMedia("/nope/missing.png", "png")), 1) is None


def test_enhancement_mode_by_family():
    # Keyword (booru) families
    for m in ["sdxl_base_1.0.safetensors", "sd_xl_turbo", "sd-1.5"]:
        assert enhancement_mode(model_family(m)) == "keyword", m
    # Video families -> cinematography even without the task hint. Includes the
    # bare-version LTX ids ("ltx-2.3", no "v") that previously fell to prose.
    for m in ["ltx-2.3", "LTX-2.3", "lightricks/ltx-2.3", "ltxv-2.3", "LTX-Video",
              "wan2.2-i2v", "hunyuan_video", "kling-v2", "seedance"]:
        assert enhancement_mode(model_family(m)) == "cinematography", m
    # Ideogram -> structured JSON
    assert enhancement_mode(model_family("Ideogram 4.0")) == "ideogram"
    # Everything else -> prose (Flux/Klein, SD3.x natural-language encoder, unknown)
    for m in ["flux1-dev", "flux-klein", "sd3.5_large", "some-unknown-model", ""]:
        assert enhancement_mode(model_family(m)) == "prose", m


def test_enhancement_mode_task_is_authoritative_for_video():
    # is_video forces cinematography regardless of whether the model is known —
    # this is the real fix: we know the task, so we don't depend on the model
    # string classifying as a video family.
    for m in ["some-unknown-video-model", "", "flux1-dev", "sdxl"]:
        assert enhancement_mode(model_family(m), is_video=True) == "cinematography", m


def test_looks_like_ideogram_json():
    assert _looks_like_ideogram_json('{"high_level_description": "a cat"}')
    assert _looks_like_ideogram_json('  \n {"a": 1} \n ')
    # Prose / keywords / non-objects are not JSON objects
    assert not _looks_like_ideogram_json("a poster that says 'OPEN'")
    assert not _looks_like_ideogram_json("1girl, long hair, {a|b}, masterpiece")
    assert not _looks_like_ideogram_json("[1, 2, 3]")
    assert not _looks_like_ideogram_json('{"unterminated": ')
    assert not _looks_like_ideogram_json("")

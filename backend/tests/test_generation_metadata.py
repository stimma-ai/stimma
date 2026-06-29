"""Tests for the canonical generation_metadata builder."""

import json

from generation_metadata import (
    CANONICAL_KEYS,
    GENERATION_METADATA_VERSION,
    build_generation_metadata,
    build_parameters,
    dump_generation_metadata,
    validate_generation_metadata,
)


def test_build_parameters_drops_internal_and_none():
    raw = {
        "prompt": "a cat",
        "negative_prompt": "blurry",
        "prompt_metadata": {"original_prompt": "cat"},
        "input_images": ["/x.png"],
        "_run_id": "abc",
        "width": 1024,
        "height": None,
        "cfg": 3.5,
    }
    out = build_parameters(raw, seed=42, generation_time=1.234)
    assert out == {"width": 1024, "cfg": 3.5, "seed": 42, "generation_time": 1.23}
    # internal + None keys are gone
    assert "prompt" not in out and "input_images" not in out and "height" not in out


def test_build_parameters_no_seed_when_unset():
    out = build_parameters({"steps": 20})
    assert out == {"steps": 20}
    assert "seed" not in out


def test_canonical_shape_is_complete_and_uniform():
    meta = build_generation_metadata(task_type="text-to-image")
    # Every canonical key present even with no inputs
    assert CANONICAL_KEYS <= set(meta)
    assert meta["version"] == GENERATION_METADATA_VERSION
    assert meta["prompt"] == "" and meta["parameters"] == {}
    assert meta["source_inputs"] == [] and meta["lineage_trace"] == []
    assert meta["generated_at"].endswith("Z")
    validate_generation_metadata(meta)


def test_video_and_image_share_shape():
    img = build_generation_metadata(
        task_type="text-to-image", tool_id="comfyui:flux",
        generator="comfyui", model="flux", prompt="x",
        parameters=build_parameters({"steps": 4}, seed=7),
    )
    vid = build_generation_metadata(
        task_type="image-to-video", tool_id="comfyui:ltx23-i2v",
        generator="comfyui", model="ltx", prompt="x",
        parameters=build_parameters({"fps": 24}, seed=7),
        source_inputs=[{"media_id": 1, "role": "start_image"}],
        prompt_metadata={"original_prompt": "orig"},
    )
    # Identical key sets -> no producer-specific drift
    assert set(img) == set(vid)
    # generator/model present on BOTH (images used to omit them)
    assert img["generator"] == "comfyui" and img["model"] == "flux"


def test_inspired_by_and_extra():
    meta = build_generation_metadata(
        task_type="document-creation",
        inspired_by={"media_id": 5},
        extra={"format": "markdown"},
    )
    assert meta["inspired_by"] == {"media_id": 5}
    assert meta["format"] == "markdown"


def test_dump_is_json():
    s = dump_generation_metadata(task_type="layout", source="agent_v2_create_layout")
    parsed = json.loads(s)
    assert parsed["task_type"] == "layout"
    assert parsed["source"] == "agent_v2_create_layout"


def test_requires_task_type():
    try:
        build_generation_metadata(task_type="")
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty task_type")

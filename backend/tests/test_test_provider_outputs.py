"""Tests for TestToolProvider's deterministic fake outputs.

Covers the extended task-type coverage and the legible-output contract:
image outputs honor requested/derived dimensions and embed their generation
parameters as a PNG text chunk; video/audio outputs are valid containers.
"""

import io
import json

import pytest
from PIL import Image

from providers.test_provider import (
    TestToolConfig,
    TestToolProvider,
    _AUDIO_TASK_TYPES,
    _VIDEO_TASK_TYPES,
)
from tasks.schemas import validate_tool_schema

pytestmark = pytest.mark.asyncio


async def _execute(provider, tool_id, parameters):
    result = None
    async for event in provider.execute(tool_id, parameters):
        result = event
    return result


@pytest.fixture
async def provider():
    p = TestToolProvider()
    await p.connect()
    return p


async def test_all_media_task_types_covered(provider):
    tools = await provider.list_tools()
    covered = {t.task_type for t in tools}
    expected = {
        "text-to-image", "image-to-image", "filter", "inpaint-image",
        "outpaint-image", "remove-background", "upscale-image",
        "upscale-video", "image-to-video", "text-to-video", "video-stitch",
        "video-extend", "text-to-audio", "text-to-music", "text-to-speech",
    }
    assert expected <= covered


async def test_tool_schemas_valid_for_task_type(provider):
    tools = await provider.list_tools()
    for tool in tools:
        errors = validate_tool_schema(tool.task_type, tool.parameter_schema, tool.output_schema)
        # Legacy tools predate the assets output convention; only enforce on
        # the extended set.
        if tool.id.split(":")[0] in ("text-to-image", "image-to-image", "upscale-image", "inpaint-image", "image-to-video"):
            continue
        assert not errors, f"{tool.id}: {errors}"


async def test_image_output_honors_requested_dimensions(provider):
    result = await _execute(
        provider,
        "text-to-image:test-model",
        {"prompt": "a red fox", "width": 832, "height": 1216, "seed": 3},
    )
    assert result.success
    img = Image.open(io.BytesIO(result.output_data))
    assert img.size == (832, 1216)


async def test_image_output_embeds_params_chunk(provider):
    result = await _execute(
        provider,
        "text-to-image:test-model",
        {"prompt": "a red fox", "width": 256, "height": 256, "seed": 3},
    )
    img = Image.open(io.BytesIO(result.output_data))
    payload = json.loads(img.text["stimma:test_params"])
    assert payload["tool_id"] == "text-to-image:test-model"
    assert payload["seed"] == 3
    assert payload["parameters"]["prompt"] == "a red fox"


async def test_upscale_scales_input_dimensions(provider, tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (100, 60)).save(src)
    result = await _execute(
        provider,
        "upscale-image:test-upscale",
        {"input_images": [str(src)], "scale": 4},
    )
    img = Image.open(io.BytesIO(result.output_data))
    assert img.size == (400, 240)


async def test_outpaint_expands_input_dimensions(provider, tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (100, 60)).save(src)
    result = await _execute(
        provider,
        "outpaint-image:test-outpaint",
        {"input_images": [str(src)], "expand_left": 30, "expand_right": 30, "expand_top": 10, "expand_bottom": 0},
    )
    img = Image.open(io.BytesIO(result.output_data))
    assert img.size == (160, 70)


async def test_video_and_audio_outputs_are_valid_containers(provider):
    video = await _execute(provider, "text-to-video:test-t2v", {"prompt": "waves"})
    assert video.success
    assert video.output_data[4:8] == b"ftyp"

    audio = await _execute(provider, "text-to-speech:test-tts", {"prompt": "hello"})
    assert audio.success
    assert audio.output_data[:4] == b"fLaC"


async def test_result_metadata_carries_parameters(provider):
    params = {"prompt": "chime", "duration": 2.0}
    result = await _execute(provider, "text-to-audio:test-sfx", params)
    assert result.metadata["parameters"] == params


async def test_deterministic_output_for_same_params(provider):
    params = {"prompt": "same", "width": 128, "height": 128, "seed": 9}
    a = await _execute(provider, "text-to-image:test-model", params)
    b = await _execute(provider, "text-to-image:test-model", params)
    assert a.output_data == b.output_data


async def test_failure_injection_still_works(provider):
    provider.configure_tool("text-to-video:test-t2v", TestToolConfig(should_fail=True, fail_message="boom"))
    result = await _execute(provider, "text-to-video:test-t2v", {"prompt": "x"})
    assert not result.success
    assert result.error == "boom"
    provider.reset_configs()


async def test_media_kind_sets_are_disjoint():
    assert not (_VIDEO_TASK_TYPES & _AUDIO_TASK_TYPES)

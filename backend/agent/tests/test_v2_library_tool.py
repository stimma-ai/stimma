import json

import pytest

from agent.v2.tools.library import (
    library,
    _normalize_loras_for_input,
    fetch_generation_params,
    resolve_params_from,
)
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_library_get_prioritizes_prompt_and_includes_history(session):
    media = await create_media_item(
        session,
        vlm_caption="AI caption should not lead",
        extracted_prompt="Fallback prompt",
        generation_metadata=json.dumps({
            "task_type": "text-to-image",
            "tool_id": "builtin:comfyui:text-to-image:z-image-turbo",
            "generator": "ComfyUI",
            "model": "Turbo",
            "prompt": "rendered prompt text",
            "negative_prompt": "blurry",
            "generated_at": "2026-03-10T12:47:44.185375",
            "parameters": {
                "width": 1024,
                "height": 1024,
                "steps": 4,
            },
            "prompt_metadata": {
                "original_prompt": "original user intent prompt",
            },
            "lineage_trace": [{
                "media_id": 111,
                "task_type": "image-to-image",
                "tool_id": "builtin:comfyui:image-to-image:edit",
                "prompt": "ancestor prompt",
                "generated_at": "2026-03-10T11:47:44.185375",
                "parameters": {
                    "denoise": 0.45,
                },
            }],
        }),
    )

    raw = await library(action="get", media_id=media.id, session=session, workspace_dir=None)
    data = json.loads(raw)

    assert data["prompt"] == "original user intent prompt"
    assert data["caption"] == "AI caption should not lead"
    assert data["history"][0]["prompt"] == "rendered prompt text"
    assert data["history"][1]["prompt"] == "ancestor prompt"
    assert raw.index('"prompt"') < raw.index('"caption"')


@pytest.mark.asyncio
async def test_library_lineage_returns_slideshow_history_without_media_lineage_rows(session):
    media = await create_media_item(
        session,
        generation_metadata=json.dumps({
            "task_type": "text-to-image",
            "tool_id": "builtin:comfyui:text-to-image:z-image-turbo",
            "generator": "ComfyUI",
            "model": "Turbo",
            "prompt": "current prompt",
            "generated_at": "2026-03-10T12:47:44.185375",
            "parameters": {
                "width": 1024,
                "height": 1024,
            },
            "lineage_trace": [{
                "media_id": 222,
                "task_type": "image-to-image",
                "tool_id": "builtin:comfyui:image-to-image:edit",
                "prompt": "source prompt",
                "generated_at": "2026-03-10T11:47:44.185375",
                "parameters": {
                    "denoise": 0.55,
                },
            }],
        }),
    )

    raw = await library(action="lineage", media_id=media.id, session=session)
    data = json.loads(raw)

    assert data["media_id"] == media.id
    assert data["history"][0]["prompt"] == "current prompt"
    assert data["history"][1]["prompt"] == "source prompt"
    assert data["sources"] == []
    assert data["derivatives"] == []


@pytest.mark.asyncio
async def test_library_history_hoists_top_level_seed_into_parameters(session):
    media = await create_media_item(
        session,
        generation_metadata=json.dumps({
            "task_type": "agent_edit",
            "tool_id": "builtin:agent:run-code",
            "prompt": "current prompt",
            "parameters": {
                "steps": 4,
            },
            "seed": 12345,
            "generated_at": "2026-03-10T12:47:44.185375",
            "lineage_trace": [{
                "media_id": 333,
                "task_type": "text-to-image",
                "tool_id": "builtin:comfyui:text-to-image:model",
                "prompt": "ancestor prompt",
                "parameters": {
                    "guidance": 1,
                },
                "seed": 67890,
                "generated_at": "2026-03-10T11:47:44.185375",
            }],
        }),
    )

    raw = await library(action="get", media_id=media.id, session=session, workspace_dir=None)
    data = json.loads(raw)

    assert data["history"][0]["parameters"]["seed"] == 12345
    assert data["history"][1]["parameters"]["seed"] == 67890


def test_normalize_loras_for_input_accepts_all_stored_shapes():
    loras = [
        {"path": "a.safetensors", "weight": 0.8},
        {"lora": "/models/b.safetensors", "weight": 0.5},
        {"name": "c", "weight": 1.0},
        {"weight": 1.0},          # no identifier — dropped
        "not-a-dict",             # ignored
    ]
    out = _normalize_loras_for_input(loras)
    assert out == [
        {"path": "a.safetensors", "weight": 0.8},
        {"path": "/models/b.safetensors", "weight": 0.5},
        {"path": "c", "weight": 1.0},
    ]


@pytest.mark.asyncio
async def test_generation_params_returns_call_tool_ready_flow(session):
    media = await create_media_item(
        session,
        width=1152,
        height=896,
        tool_id="builtin:comfyui:text-to-image:z-image-turbo",
        generation_metadata=json.dumps({
            "task_type": "text-to-image",
            "tool_id": "builtin:comfyui:text-to-image:z-image-turbo",
            "prompt": "a knight in a forest",
            "negative_prompt": "blurry",
            "parameters": {
                "steps": 4,
                "cfg": 1.5,
                "sampler": "euler",
                "seed": 999,
                "loras": [{"lora": "/models/style.safetensors", "weight": 0.7}],
            },
            "generated_at": "2026-03-10T12:47:44.185375",
        }),
    )

    params = await fetch_generation_params(session, media.id)

    # tool_id at top level for direct call_tool(**params)
    assert params["tool_id"] == "builtin:comfyui:text-to-image:z-image-turbo"
    assert params["prompt"] == "a knight in a forest"
    assert params["negative_prompt"] == "blurry"
    # seed hoisted to top level (call_tool reads it from inputs, not parameters)
    assert params["seed"] == 999
    # dimensions taken from the item
    assert params["width"] == 1152
    assert params["height"] == 896
    # other generation params carried through faithfully
    assert params["steps"] == 4
    assert params["cfg"] == 1.5
    assert params["sampler"] == "euler"
    # loras normalized from stored {"lora": ...} to input {"path": ...}
    assert params["loras"] == [{"path": "/models/style.safetensors", "weight": 0.7}]


@pytest.mark.asyncio
async def test_generation_params_uses_rendered_prompt_not_original(session):
    # When wildcards/auto-improve ran, generation_metadata["prompt"] holds the
    # final rendered prompt sent to the generator, while prompt_metadata.original_prompt
    # holds the raw pre-processing input. Reproduction (grids, re-runs) must use the
    # rendered prompt so resolved wildcards / auto-improve aren't lost.
    media = await create_media_item(
        session,
        tool_id="builtin:comfyui:text-to-image:z-image-turbo",
        generation_metadata=json.dumps({
            "task_type": "text-to-image",
            "tool_id": "builtin:comfyui:text-to-image:z-image-turbo",
            "prompt": "a regal knight in a snowy pine forest, cinematic lighting",
            "parameters": {"seed": 7},
            "prompt_metadata": {
                "original_prompt": "a knight in a __setting__",
                "auto_improve_enabled": True,
            },
            "generated_at": "2026-03-10T12:47:44.185375",
        }),
    )

    params = await fetch_generation_params(session, media.id)

    assert params["prompt"] == "a regal knight in a snowy pine forest, cinematic lighting"


@pytest.mark.asyncio
async def test_generation_params_falls_back_to_original_when_no_rendered_prompt(session):
    # Older/imported items may lack a rendered prompt; fall back to the original.
    media = await create_media_item(
        session,
        tool_id="builtin:comfyui:text-to-image:z-image-turbo",
        generation_metadata=json.dumps({
            "task_type": "text-to-image",
            "tool_id": "builtin:comfyui:text-to-image:z-image-turbo",
            "parameters": {"seed": 7},
            "prompt_metadata": {"original_prompt": "fallback intent prompt"},
            "generated_at": "2026-03-10T12:47:44.185375",
        }),
    )

    params = await fetch_generation_params(session, media.id)

    assert params["prompt"] == "fallback intent prompt"


@pytest.mark.asyncio
async def test_generation_params_includes_input_images_for_image_to_image(session):
    media = await create_media_item(
        session,
        tool_id="builtin:comfyui:image-to-image:edit",
        generation_metadata=json.dumps({
            "task_type": "image-to-image",
            "tool_id": "builtin:comfyui:image-to-image:edit",
            "prompt": "make it snowy",
            "parameters": {"denoise": 0.5, "seed": 42},
            "source_inputs": [
                {"media_id": 555, "role": "source_image"},
                {"media_id": 777, "role": "mask_image"},
            ],
            "generated_at": "2026-03-10T12:47:44.185375",
        }),
    )

    params = await fetch_generation_params(session, media.id)

    # source_image is reused; mask_image is not folded into input_images
    assert params["input_images"] == [555]
    assert params["seed"] == 42


@pytest.mark.asyncio
async def test_params_from_inherits_omitted_and_explicit_wins(session):
    # The core fix: a knob the caller omits inherits from the source item (not the
    # tool's schema default), while anything the caller passes wins — including
    # seed=None for a fresh seed.
    media = await create_media_item(
        session,
        width=1152,
        height=896,
        tool_id="builtin:comfyui:text-to-image:z-image-turbo",
        generation_metadata=json.dumps({
            "task_type": "text-to-image",
            "tool_id": "builtin:comfyui:text-to-image:z-image-turbo",
            "prompt": "a knight in a forest",
            "parameters": {
                "steps": 4,
                "cfg": 1.5,
                "seed": 999,
                "loras": [{"lora": "/models/style.safetensors", "weight": 0.7}],
            },
            # A recorded source image must NOT bleed in as content via params_from.
            "source_inputs": [{"media_id": 555, "role": "source_image"}],
            "generated_at": "2026-03-10T12:47:44.185375",
        }),
    )

    merged = await resolve_params_from(
        session,
        "builtin:comfyui:text-to-image:z-image-turbo",
        media.id,
        {"prompt": "a knight on a beach", "seed": None},
    )

    # Explicit kwargs win.
    assert merged["prompt"] == "a knight on a beach"
    assert merged["seed"] is None
    # Omitted knobs inherit from the source item.
    assert merged["steps"] == 4
    assert merged["cfg"] == 1.5
    assert merged["loras"] == [{"path": "/models/style.safetensors", "weight": 0.7}]
    assert merged["width"] == 1152
    # Settings only — provenance and the source image's pixels never carry over.
    assert "tool_id" not in merged
    assert "input_images" not in merged


@pytest.mark.asyncio
async def test_params_from_rejects_image_without_recorded_params(session):
    media = await create_media_item(session, extracted_prompt="imported photo", generation_metadata=None)

    with pytest.raises(RuntimeError, match="no recorded generation parameters"):
        await resolve_params_from(session, "builtin:comfyui:text-to-image:z-image-turbo", media.id, {})


@pytest.mark.asyncio
async def test_generation_params_tool_action_flags_imported_images(session):
    media = await create_media_item(
        session,
        extracted_prompt="imported photo",
        generation_metadata=None,
    )

    raw = await library(action="generation_params", media_id=media.id, session=session)
    data = json.loads(raw)

    # No generating tool recorded -> no tool_id, with an explanatory note
    assert "tool_id" not in data["params"]
    assert "note" in data

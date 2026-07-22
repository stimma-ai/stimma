"""Tests for the built-in Darkroom tools (vendored ComfyUI-Darkroom engine)."""

import numpy as np
import pytest
from PIL import Image

from darkroom.tools import (
    COLOR_GRADE_TOOL,
    DARKROOM_TOOLS,
    DEVELOP_TOOL,
    FILM_STOCK_TOOL,
)


def _test_image() -> Image.Image:
    """A gradient with all channels varying — sensitive to any color op."""
    x = np.linspace(0.0, 1.0, 128)
    arr = np.stack(
        [
            np.tile(x, (64, 1)),
            np.tile(x[::-1], (64, 1)),
            np.full((64, 128), 0.5),
        ],
        axis=-1,
    )
    return Image.fromarray((arr * 255).astype(np.uint8))


def _mean_diff(a: Image.Image, b: Image.Image) -> float:
    return float(np.abs(
        np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32)
    ).mean())


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def _iter_constraint_params(expr):
    if "param" in expr:
        yield expr["param"]
    for key in ("all", "any"):
        for sub in expr.get(key, []):
            yield from _iter_constraint_params(sub)
    if "not" in expr:
        yield from _iter_constraint_params(expr["not"])


@pytest.mark.parametrize("tool", DARKROOM_TOOLS, ids=lambda t: t.id)
def test_schema_well_formed(tool):
    schema = tool.parameter_schema
    props = schema["properties"]
    assert "input_images" in props
    assert schema["required"] == ["input_images"]
    for name, prop in props.items():
        if name == "input_images":
            continue
        assert prop["type"] in ("string", "number", "integer", "boolean"), name
        if prop["type"] == "string":
            assert prop["enum"], f"{name}: string params must be enums"
        # every x-constraints reference must name a declared property
        for constraint in prop.get("x-constraints", []):
            for ref in _iter_constraint_params(constraint["when"]):
                assert ref in props, f"{name} references undeclared {ref}"
            assert constraint["effect"] in ("hide", "disable")


def test_all_tools_declare_attribution_description():
    for tool in DARKROOM_TOOLS:
        assert "Louvaert" in tool.description


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def test_develop_neutral_defaults_are_noop():
    img = _test_image()
    out = DEVELOP_TOOL.run({"wb_mode": "off"}, img)
    assert _mean_diff(img, out) < 0.75  # only uint8 round-trip wiggle


def test_film_stock_color_changes_image():
    img = _test_image()
    out = FILM_STOCK_TOOL.run({"stock_type": "color"}, img)
    assert out.size == img.size
    assert _mean_diff(img, out) > 2.0


def test_film_stock_bw_desaturates():
    out = FILM_STOCK_TOOL.run({"stock_type": "bw"}, _test_image())
    arr = np.asarray(out, dtype=np.float32)
    channel_spread = np.abs(arr[..., 0] - arr[..., 1]).mean()
    assert channel_spread < 1.0


def test_film_stock_all_stages_run():
    img = _test_image()
    out = FILM_STOCK_TOOL.run(
        {
            "stock_type": "none",
            "crossprocess_enabled": True,
            "print_enabled": True,
            "halation_enabled": True,
            "vignette_enabled": True,
            "grain_enabled": True,
        },
        img,
    )
    assert _mean_diff(img, out) > 2.0


def test_film_stock_disabled_stages_are_noop():
    img = _test_image()
    out = FILM_STOCK_TOOL.run({"stock_type": "none"}, img)
    assert _mean_diff(img, out) < 0.75


@pytest.mark.parametrize(
    "mode", [v for s in COLOR_GRADE_TOOL.stages for v in [s.mode_value]]
)
def test_color_grade_default_mode_is_noop(mode):
    # Every corrector's defaults are neutral; selecting a mode without
    # touching its sliders must not alter the image.
    img = _test_image()
    out = COLOR_GRADE_TOOL.run({"mode": mode}, img)
    assert _mean_diff(img, out) < 0.75


def test_color_grade_preset_applies():
    img = _test_image()
    out = COLOR_GRADE_TOOL.run(
        {"mode": "tone_curve", "tc_preset": "Matte Film"}, img
    )
    assert _mean_diff(img, out) > 2.0


def test_develop_adjustments_apply():
    img = _test_image()
    out = DEVELOP_TOOL.run(
        {
            "wb_mode": "manual",
            "wb_temperature": 3200,
            "tone_exposure": 0.7,
            "clarity_clarity": 40,
            "vibrance_vibrance": 30,
        },
        img,
    )
    assert _mean_diff(img, out) > 2.0


# ---------------------------------------------------------------------------
# Provider registration + execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_registers_and_executes(tmp_path):
    from providers.base import ExecutionResult
    from providers.lightweight import LightweightProvider

    provider = LightweightProvider()
    await provider.connect()
    try:
        tools = {t.id: t for t in await provider.list_tools()}
        for tool in DARKROOM_TOOLS:
            assert tool.id in tools
            descriptor = tools[tool.id]
            assert descriptor.task_type == "filter"
            assert descriptor.metadata["attribution"]["url"].startswith("https://")

        src = tmp_path / "in.png"
        _test_image().save(src)
        dst = tmp_path / "out.png"

        result = None
        async for event in provider.execute(
            "darkroom-film-stock",
            {"input_images": [str(src)], "stock_type": "color"},
            output_path=str(dst),
        ):
            if isinstance(event, ExecutionResult):
                result = event
        assert result is not None and result.success, result and result.error
        assert dst.exists()
        with Image.open(dst) as out:
            assert out.size == _test_image().size
    finally:
        await provider.disconnect()

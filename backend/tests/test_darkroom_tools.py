"""Tests for the built-in Darkroom tools (vendored ComfyUI-Darkroom engine)."""

import numpy as np
import pytest
from PIL import Image

# Darkroom is rarely-changing vendored/ported code; the CI quality gate
# deselects this marker to keep build turnaround focused on app code.
pytestmark = pytest.mark.darkroom

from darkroom.tools import (
    COLOR_GRADE_TOOL,
    DARKROOM_TOOLS,
    DEVELOP_TOOL,
    FILM_STOCK_TOOL,
    LENS_TOOL,
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
# Ported (ex-torch) nodes: lens optics, color warper, skin tone
# ---------------------------------------------------------------------------

def _checkerboard() -> Image.Image:
    cb = (np.indices((96, 128)).sum(axis=0) // 8 % 2).astype(np.float32)
    return Image.fromarray((np.stack([cb, cb, cb], axis=-1) * 255).astype(np.uint8))


def test_lens_identity_resample_is_exact():
    from darkroom.ports.np_ops import grid_sample_channel, pixel_to_grid_coords

    arr = np.random.RandomState(0).rand(48, 48).astype(np.float32)
    yy, xx = np.meshgrid(
        np.arange(48, dtype=np.float32), np.arange(48, dtype=np.float32), indexing="ij"
    )
    out = grid_sample_channel(arr, pixel_to_grid_coords(yy, xx, 48, 48))
    assert np.abs(out - arr).max() < 1e-6


def test_lens_distortion_warps():
    img = _checkerboard()
    out = LENS_TOOL.run({"mode": "distortion", "distortion_k1": -0.3}, img)
    assert _mean_diff(img, out) > 2.0


def test_chromatic_aberration_fringes_edges():
    img = _checkerboard()
    out = LENS_TOOL.run(
        {"mode": "ca", "ca_strength": 3.0, "ca_shift_r": -4.0, "ca_shift_b": 4.0}, img
    )
    arr = np.asarray(out, dtype=np.float32)
    # CA splits R and B apart at edges; the input had R == B everywhere.
    assert np.abs(arr[..., 0] - arr[..., 2]).mean() > 2.0


def test_lens_profile_add_and_correct_differ():
    img = _checkerboard()
    added = LENS_TOOL.run({"mode": "profile"}, img)
    corrected = LENS_TOOL.run(
        {"mode": "profile", "profile_mode": "Correct Aberrations"}, img
    )
    assert _mean_diff(img, added) > 0.5
    assert _mean_diff(added, corrected) > 0.5


def test_color_warper_default_is_noop_and_shift_applies():
    img = _test_image()
    noop = COLOR_GRADE_TOOL.run({"mode": "color_warper"}, img)
    assert _mean_diff(img, noop) < 0.75
    shifted = COLOR_GRADE_TOOL.run(
        {
            "mode": "color_warper",
            "cw_source_hue": 120,
            "cw_source_hue_width": 120,
            "cw_hue_shift": 60,
        },
        img,
    )
    assert _mean_diff(img, shifted) > 2.0


def test_skin_tone_uniformity_evens_skin_patch():
    rs = np.random.RandomState(1)
    base = np.stack(
        [np.full((96, 128), 0.78), np.full((96, 128), 0.55), np.full((96, 128), 0.42)],
        axis=-1,
    )
    base = np.clip(base + rs.normal(0, 0.05, base.shape), 0, 1)
    img = Image.fromarray((base * 255).astype(np.uint8))

    out = DEVELOP_TOOL.run(
        {"wb_mode": "off", "skin_enabled": True, "skin_amount": 90}, img
    )
    assert _mean_diff(img, out) > 2.0
    # Evening reduces chroma variance across the patch
    def sat_std(im):
        a = np.asarray(im, dtype=np.float32) / 255.0
        return float((a.max(axis=-1) - a.min(axis=-1)).std())
    assert sat_std(out) < sat_std(img)


def test_film_stock_halftone_stage():
    img = _test_image()
    out = FILM_STOCK_TOOL.run(
        {"stock_type": "none", "halftone_enabled": True, "halftone_lines": 40}, img
    )
    arr = np.asarray(out, dtype=np.float32) / 255.0
    assert _mean_diff(img, out) > 2.0
    # mono halftone reproduces tone as ink dots: mostly near-binary pixels
    # (the remainder is supersample anti-aliasing on dot edges, which on a
    # 128px test image is a large fraction of the frame)
    luma = arr.mean(axis=-1)
    assert ((luma < 0.25) | (luma > 0.75)).mean() > 0.5


def test_film_stock_grain_pro_stage():
    img = _test_image()
    out = FILM_STOCK_TOOL.run(
        {
            "stock_type": "none",
            "grainpro_enabled": True,
            "grainpro_monte_carlo_samples": 8,
            "grainpro_strength": 1.0,
        },
        img,
    )
    assert _mean_diff(img, out) > 1.0


def test_film_grain_pro_port_preserves_tone():
    from darkroom.ports.grain_newson import render_film_grain

    img = np.full((96, 128, 3), 0.5, dtype=np.float32)
    out = render_film_grain(
        img, grain_size=1.2, radius_variation=0.0, strength=1.0,
        color_grain=0.0, n_samples=16, filter_sigma=0.8, seed=0,
    )
    # grainy (per-pixel deviation exists) but tone-preserving in the mean
    assert np.abs(out - img).mean() > 0.01
    assert abs(float(out.mean()) - 0.5) < 0.02
    # deterministic per seed
    again = render_film_grain(
        img, grain_size=1.2, radius_variation=0.0, strength=1.0,
        color_grain=0.0, n_samples=16, filter_sigma=0.8, seed=0,
    )
    assert np.array_equal(out, again)


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

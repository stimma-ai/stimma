"""Built-in chain filters: editor↔backend definition parity + filter math.

The editor (packages/image-editor/src/filterDefs.ts + constants.ts) is the
source of truth for filter definitions; backend/postprocessing/filter_defs.py
is a mirror. These tests assert the mirror never drifts, and that the NumPy
ports of the editor's pixel math behave like the Canvas originals.
"""

import math
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from filters import ops as bf
from filters.defs import (
    CHAIN_FILTER_DEFS,
    COLOR_FILTER_IDS,
    FILTER_MATRICES,
    get_filter_defaults,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTANTS_TS = REPO_ROOT / "packages" / "image-editor" / "src" / "constants.ts"
FILTER_DEFS_TS = REPO_ROOT / "packages" / "image-editor" / "src" / "filterDefs.ts"

requires_editor_sources = pytest.mark.skipif(
    not (CONSTANTS_TS.exists() and FILTER_DEFS_TS.exists()),
    reason="image-editor sources not present",
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", src)


def _parse_ts_filter_matrices(src: str) -> dict:
    """Extract FILTER_MATRICES entries from constants.ts."""
    src = _strip_comments(src)
    m = re.search(r"export const FILTER_MATRICES[^=]*=\s*\{(.*?)\n\};", src, re.DOTALL)
    assert m, "FILTER_MATRICES not found in constants.ts"
    body = m.group(1)
    matrices = {}
    for entry in re.finditer(r"['\"]?([\w-]+)['\"]?:\s*\[([^\]]+)\]", body):
        name = entry.group(1)
        values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", entry.group(2))]
        matrices[name] = values
    return matrices


def _parse_ts_chain_filter_defs(src: str) -> list:
    """Extract id + params (name/type/default/min/max/options) from filterDefs.ts."""
    src = _strip_comments(src)
    m = re.search(r"export const CHAIN_FILTER_DEFS[^=]*=\s*\[(.*?)\n\];", src, re.DOTALL)
    assert m, "CHAIN_FILTER_DEFS not found in filterDefs.ts"
    body = m.group(1)

    defs = []
    # Top-level def objects start with an id line.
    for block in re.split(r"\n  \},?", body):
        id_m = re.search(r"id:\s*'([\w-]+)'", block)
        if not id_m:
            continue
        params = []
        for pm in re.finditer(r"\{\s*name:\s*'(\w+)'[^}]*\}", block, re.DOTALL):
            ptxt = pm.group(0)
            param = {"name": pm.group(1)}
            tm = re.search(r"type:\s*'(\w+)'", ptxt)
            param["type"] = tm.group(1)
            dm = re.search(r"default:\s*(-?\d+(?:\.\d+)?|'[\w:-]+')", ptxt)
            dv = dm.group(1)
            param["default"] = dv.strip("'") if dv.startswith("'") else float(dv)
            for bound in ("min", "max"):
                bm = re.search(rf"{bound}:\s*(-?\d+(?:\.\d+)?)", ptxt)
                if bm:
                    param[bound] = float(bm.group(1))
            om = re.search(r"options:\s*(\[.*?\]|\w+)", ptxt, re.DOTALL)
            if om:
                otxt = om.group(1)
                if otxt.startswith("["):
                    param["options"] = re.findall(r"value:\s*'([\w:-]+)'", otxt)
                else:
                    param["options"] = otxt  # identifier (COLOR_FILTER_OPTIONS)
            params.append(param)
        defs.append({"id": id_m.group(1), "params": params})
    return defs


# --- Definition parity ---------------------------------------------------------

@requires_editor_sources
def test_filter_matrices_match_editor():
    ts_matrices = _parse_ts_filter_matrices(CONSTANTS_TS.read_text())
    assert set(ts_matrices) == set(FILTER_MATRICES)
    for name, values in ts_matrices.items():
        assert values == pytest.approx(FILTER_MATRICES[name]), f"matrix drift: {name}"


@requires_editor_sources
def test_chain_filter_defs_match_editor():
    ts_defs = {d["id"]: d for d in _parse_ts_chain_filter_defs(FILTER_DEFS_TS.read_text())}
    py_defs = {d["id"]: d for d in CHAIN_FILTER_DEFS}
    assert set(ts_defs) == set(py_defs)

    for fid, ts_def in ts_defs.items():
        py_params = {p["name"]: p for p in py_defs[fid]["params"]}
        ts_params = {p["name"]: p for p in ts_def["params"]}
        assert set(ts_params) == set(py_params), f"param drift: {fid}"
        for name, tp in ts_params.items():
            pp = py_params[name]
            assert tp["type"] == pp["type"], f"{fid}.{name} type"
            assert tp["default"] == pp["default"], f"{fid}.{name} default"
            for bound in ("min", "max"):
                if bound in tp or bound in pp:
                    assert tp.get(bound) == pp.get(bound), f"{fid}.{name} {bound}"
            if "options" in tp:
                expected = tp["options"]
                if expected == "COLOR_FILTER_OPTIONS":
                    expected = COLOR_FILTER_IDS
                assert expected == pp["options"], f"{fid}.{name} options"


def test_every_def_has_a_handler():
    """Every filter def maps to either a per-frame PIL handler (FILTER_HANDLERS,
    applied identically to stills and video frames) or, for a filter that only
    makes sense on a whole clip (e.g. reverse — there's no single-frame notion
    of "reversed"), a whole-clip handler in video_ops.WHOLE_CLIP_VIDEO_FILTERS.
    The latter must also declare video-only accepts, since it can't run on a
    still."""
    from filters.video_ops import WHOLE_CLIP_VIDEO_FILTERS

    for d in CHAIN_FILTER_DEFS:
        has_frame_handler = d["id"] in bf.FILTER_HANDLERS
        has_whole_clip_handler = d["id"] in WHOLE_CLIP_VIDEO_FILTERS
        assert has_frame_handler or has_whole_clip_handler, f"{d['id']} has no handler at all"
        if has_whole_clip_handler and not has_frame_handler:
            assert d.get("accepts") == ["video"], (
                f"{d['id']} has no per-frame handler so it can't run on a still — "
                "it must declare accepts: ['video']"
            )


async def test_filters_register_as_builtin_tools_with_valid_schemas():
    """Filters are first-class catalog tools on the lightweight provider —
    one per definition, task type 'filter', schema passing task validation."""
    from providers.lightweight import LightweightProvider
    from tasks.schemas import validate_tool_schema

    provider = LightweightProvider()
    await provider.connect()
    try:
        tools = {t.id: t for t in await provider.list_tools()}
        for d in CHAIN_FILTER_DEFS:
            tool = tools.get(d["id"])
            assert tool is not None, f"filter {d['id']} not registered"
            assert tool.task_type == "filter"
            assert tool.name == d["label"]
            errors = validate_tool_schema("filter", tool.parameter_schema, tool.output_schema)
            assert not errors, f"{d['id']}: {errors}"
            # Every def param appears in the schema with its default
            props = tool.parameter_schema["properties"]
            for p in d["params"]:
                assert p["name"] in props, f"{d['id']}.{p['name']} missing from schema"
                assert props[p["name"]].get("default") == p["default"]
            # Not hidden from the catalog — these are app capabilities
            assert not (tool.metadata or {}).get("agent_only")
    finally:
        await provider.disconnect()


# --- Filter math ----------------------------------------------------------------

def _gradient_image(w=64, h=48) -> Image.Image:
    xx, yy = np.meshgrid(np.linspace(0, 255, w), np.linspace(0, 255, h))
    arr = np.stack([xx, yy, (xx + yy) / 2], axis=-1).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def test_color_matrix_application_matches_reference():
    # apply_color_matrix must equal a straight per-pixel matrix multiply.
    rng = np.random.default_rng(42)
    rgba = rng.integers(0, 256, size=(16, 16, 4), dtype=np.uint8)
    matrix = FILTER_MATRICES["sepia"]
    out = bf.apply_color_matrix(rgba, matrix)

    m = np.asarray(matrix, dtype=np.float64).reshape(4, 5)
    ref = rgba.astype(np.float64) @ m[:, :4].T + m[:, 4]
    ref = np.clip(ref, 0, 255).astype(np.uint8)
    assert np.array_equal(out, ref)


def test_mono_filter_is_grayscale():
    out = np.array(bf.apply_builtin_filter("filter", _gradient_image(), {"filter": "mono"}))
    assert np.array_equal(out[..., 0], out[..., 1])
    assert np.array_equal(out[..., 1], out[..., 2])


def test_matrix_composition_matches_editor_semantics():
    # brightness(+50) then contrast(+20), composed exactly like combineAdjustments.
    composed = bf.combine_adjustments({"brightness": 50, "contrast": 20})
    manual = bf.multiply_color_matrices(
        bf.multiply_color_matrices(bf.identity_matrix(), bf.brightness_matrix(50)),
        bf.contrast_matrix(20),
    )
    assert composed == pytest.approx(manual)


def test_levels_neutral_settings_is_identity():
    img = _gradient_image()
    out = bf.apply_builtin_filter("levels", img, get_filter_defaults("levels"))
    assert np.array_equal(np.array(out), np.array(img))


def test_levels_brightness_shifts_up():
    img = _gradient_image()
    out = bf.apply_builtin_filter("levels", img, {"brightness": 50})
    assert np.array(out).astype(int).mean() > np.array(img).astype(int).mean()


def test_blur_reduces_variance():
    img = _gradient_image()
    noisy = np.array(img).astype(np.int16)
    rng = np.random.default_rng(1)
    noisy = np.clip(noisy + rng.integers(-40, 40, noisy.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(noisy)
    out = bf.apply_builtin_filter("blur", img, {"amount": 50})
    assert np.array(out).astype(float).var() < np.array(img).astype(float).var()


def test_sharpen_increases_local_contrast():
    img = _gradient_image()
    out = bf.apply_builtin_filter("sharpen", img, {"amount": 80})
    grad_out = np.abs(np.diff(np.array(out)[..., 0].astype(float), axis=1)).mean()
    grad_in = np.abs(np.diff(np.array(img)[..., 0].astype(float), axis=1)).mean()
    assert grad_out >= grad_in


def test_vignette_darkens_corners_not_center():
    img = Image.new("RGB", (64, 64), (200, 200, 200))
    out = np.array(bf.apply_builtin_filter("vignette", img, {"amount": 80}))
    center = out[32, 32].astype(int).mean()
    corner = out[0, 0].astype(int).mean()
    assert corner < center
    assert center == pytest.approx(200, abs=2)  # inner half stays untouched


@pytest.mark.parametrize("aspect,expected", [
    ("1:1", (48, 48)),
    ("16:9", (64, 36)),
    ("9:16", (27, 48)),
])
def test_crop_center_crops_to_aspect(aspect, expected):
    out = bf.apply_builtin_filter("crop", _gradient_image(64, 48), {"aspect": aspect})
    assert out.size == expected
    ratio = out.size[0] / out.size[1]
    num, den = (float(x) for x in aspect.split(":"))
    assert ratio == pytest.approx(num / den, abs=0.05)


def test_resize_scales_long_edge():
    out = bf.apply_builtin_filter("resize", _gradient_image(64, 48), {"long_edge": 128})
    assert out.size == (128, 96)


def test_alpha_preserved_through_color_filter():
    img = Image.new("RGBA", (8, 8), (100, 150, 200, 128))
    out = bf.apply_builtin_filter("filter", img, {"filter": "warm"})
    assert out.mode == "RGBA"
    assert np.array(out)[..., 3].min() > 0


def test_noise_increases_variance():
    img = Image.new("RGB", (64, 64), (128, 128, 128))
    out = bf.apply_builtin_filter("noise", img, {"amount": 50})
    assert np.array(out).astype(float).var() > 1.0


def test_pixelate_creates_uniform_blocks():
    out = np.array(bf.apply_builtin_filter("pixelate", _gradient_image(), {"amount": 40}))
    # pixel size = 20 → the first 20x20 block is one flat color
    block = out[:20, :20]
    assert (block == block[0, 0]).all()


def test_glow_brightens():
    img = _gradient_image()
    out = bf.apply_builtin_filter("glow", img, {"amount": 60})
    assert np.array(out).astype(int).mean() > np.array(img).astype(int).mean()


def test_chromatic_aberration_offsets_red_and_blue():
    img = _gradient_image()
    out = np.array(bf.apply_builtin_filter("chromatic-aberration", img, {"amount": 50}))
    src = np.array(img)
    # offset = 10: red sampled from the left, blue from the right; green untouched
    assert np.array_equal(out[:, 20, 0], src[:, 10, 0])
    assert np.array_equal(out[:, 20, 2], src[:, 30, 2])
    assert np.array_equal(out[..., 1], src[..., 1])


def test_motion_blur_smears_along_direction():
    # A vertical white stripe blurred horizontally spreads; blurred vertically doesn't.
    arr = np.zeros((40, 40, 3), dtype=np.uint8)
    arr[:, 19:21] = 255
    img = Image.fromarray(arr)
    horizontal = np.array(bf.apply_builtin_filter("motion-blur", img, {"amount": 60, "angle": 0}))
    vertical = np.array(bf.apply_builtin_filter("motion-blur", img, {"amount": 60, "angle": 90}))
    assert (horizontal[..., 0] > 0).sum() > (vertical[..., 0] > 0).sum()


def test_unknown_filter_id_raises():
    with pytest.raises(ValueError):
        bf.apply_builtin_filter("nope", _gradient_image(), {})


def test_reverse_has_no_per_frame_handler():
    """reverse is a whole-clip filter (filters.video_ops.WHOLE_CLIP_VIDEO_FILTERS),
    not a per-frame one — it has no FILTER_HANDLERS entry and can't run on a still."""
    with pytest.raises(ValueError):
        bf.apply_builtin_filter("reverse", _gradient_image(), {})


def test_invalid_aspect_raises():
    with pytest.raises(ValueError):
        bf.apply_builtin_filter("crop", _gradient_image(), {"aspect": "wide"})

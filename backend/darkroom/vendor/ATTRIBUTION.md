# ComfyUI-Darkroom (vendored subset)

Source: https://github.com/jeremieLouvaert/ComfyUI-Darkroom
Author: Jérémie Louvaert (https://jeremielouvaert.com)
License: MIT (declared in upstream README.md and pyproject.toml; see LICENSE
in this directory)
Vendored from: v1.11.0, commit `0f6cce953956a027720be716094df0dfa0c82756`
(2026-07-17)

This directory is a vendored subset of ComfyUI-Darkroom's film emulation,
camera-raw adjustment, and color grading engine. Stimma exposes it as the
built-in Darkroom tools (see `../ops.py` / `../tools.py`, which contain all
Stimma-side adaptation — vendored files stay byte-identical to upstream except
for the patches listed below).

Upstream file paths are preserved (`nodes/`, `utils/`, `data/`) so upgrades
are a re-copy + diff.

## What was vendored

- `nodes/` — 26 of upstream's 54 node modules: the film emulation set
  (film_stock_color, film_stock_bw, film_grain, halation, print_stock,
  cross_process, reciprocity, spectral_bw), the camera-raw set
  (white_balance, auto_white_balance, exposure_tone, hsl_selective,
  clarity_texture_dehaze, vibrance, sharpening_pro, noise_reduction), the
  grading set (tone_curve, lift_gamma_gain, log_wheels,
  three_way_color_balance, oklab_color, hue_vs_hue, hue_vs_sat, lum_vs_sat,
  sat_vs_sat), and vignette.
- `utils/` — color, grading, grain, colorspace, raw, image.
- `data/` — color_stocks, bw_stocks, print_stocks, cross_process_curves,
  grading_presets, ai_mitigation_presets, lens_profiles.

## What was NOT vendored (and why)

- torch-only nodes (film_grain_pro, halftone, color_warper,
  chromatic_aberration, lens_distortion, lens_profile, skin_tone_uniformity,
  and utils/torch_ops.py, utils/grain_newson.py) — Stimma's backend is
  ONNX-only, no PyTorch.
- RAW pipeline (raw_load, raw_metadata_split, utils/raw_loader.py,
  utils/dcp.py, data dcp looks) — needs rawpy/exifread; out of scope.
- CMYK print workflow, scopes (histogram/vectorscope), LUT bake/export
  pipeline, color match, sabattier, adjacency acutance — out of scope for the
  current tools.
- `data/spectral_luts/` (36 MB of baked .cube LUTs) and the
  `third_party/spectral_film_lut` baker — planned to ship via the R2
  model-cache pattern instead of in-tree, together with the Spectral Film
  Stock mode.

## Local patches (keep this list exhaustive)

1. `nodes/__init__.py` — replaced with a comment stub. Upstream imports every
   node module including torch-only ones we don't vendor; node modules are
   imported directly instead.
2. `utils/image.py` — `tensor_to_numpy_batch` / `numpy_batch_to_tensor`
   reimplemented over numpy (an "IMAGE tensor" is a numpy (B, H, W, C)
   float32 array). Upstream versions convert ComfyUI torch tensors. All
   other functions are unmodified; the `import torch` was removed.

(`utils/color.py` keeps its internal guarded `import torch` fast-path
unmodified — it falls back to numpy when torch is absent, which is always
the case here. Likewise `utils/grain.py`'s guarded `opensimplex` import: the
dependency is intentionally NOT installed — its wheel pollutes site-packages
with a top-level `tests` package that shadows our test suite, and upstream
only takes the simplex path for images ≤128 px on the long edge anyway, so
the filtered-gaussian grain fallback is the production path both upstream
and here.)

## Upgrade procedure

1. Clone upstream at the new tag; note the commit hash.
2. Re-copy the file lists above over this directory.
3. Re-apply the two patches (or re-verify they're still needed).
4. Diff `nodes/` glue against `../ops.py` stage table for new/renamed
   parameters (schemas are generated from the nodes' own `INPUT_TYPES`, so
   most parameter changes flow through automatically).
5. Run the darkroom backend tests; update this file's version/commit lines.

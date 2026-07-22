"""Numpy equivalents of upstream utils/torch_ops.py (ComfyUI-Darkroom).

Port of the torch-only helpers used by the nodes in this package. Color math
that already exists in vendor/utils (srgb, HSL, blend, luminance) is
re-exported from there rather than duplicated; only the torch-specific
primitives are implemented here. Grid sampling goes through
scipy.ndimage.map_coordinates with order=3 (bicubic) — which is what
upstream itself used before moving those ops to torch F.grid_sample.
"""

import math

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

from ..vendor.utils.color import (  # noqa: F401  (re-exports for node ports)
    blend,
    linear_to_srgb,
    luminance_rec709,
    srgb_to_linear,
)
from ..vendor.utils.raw import hsl_to_rgb, rgb_to_hsl  # noqa: F401


def gaussian_blur_2d(arr_2d, sigma):
    """Gaussian blur a 2D (H, W) array. Mirrors torch_ops.gaussian_blur_2d."""
    if sigma < 0.5:
        return arr_2d
    return gaussian_filter(arr_2d, sigma=sigma, mode="reflect").astype(np.float32)


def hue_range_mask(hue, center, width=45.0, softness=0.5):
    """
    Raised-cosine feathered hue selection with wraparound at 0/360.
    hue: (H, W) array [0, 360). Returns: (H, W) array [0, 1].
    """
    diff = np.abs(hue - center)
    diff = np.minimum(diff, 360.0 - diff)

    effective_width = width * (0.5 + softness * 0.5)
    mask = np.clip((1.0 + np.cos(math.pi * diff / max(effective_width, 1.0))) * 0.5, 0.0, 1.0)
    mask[diff > effective_width] = 0.0
    return mask.astype(np.float32)


def skin_mask(h, s, l, hue_center, hue_width, sat_min, sat_max, lum_min, lum_max):
    """Soft skin-tone mask from HSL channels. All inputs/outputs (H, W)."""
    diff = np.abs(h - hue_center)
    diff = np.minimum(diff, 360.0 - diff)
    hue_weight = np.clip((1.0 + np.cos(math.pi * diff / hue_width)) * 0.5, 0.0, 1.0)
    hue_weight[diff > hue_width] = 0.0

    sat_feather = 0.08
    sat_weight = np.clip((s - sat_min) / (sat_feather + 1e-10), 0.0, 1.0)
    sat_weight = sat_weight * np.clip((sat_max - s) / (sat_feather + 1e-10), 0.0, 1.0)

    lum_feather = 0.10
    lum_weight = np.clip((l - lum_min) / (lum_feather + 1e-10), 0.0, 1.0)
    lum_weight = lum_weight * np.clip((lum_max - l) / (lum_feather + 1e-10), 0.0, 1.0)

    return (hue_weight * sat_weight * lum_weight).astype(np.float32)


def sat_range_weight(sat, sat_min, sat_max, softness=0.1):
    """Smooth saturation range mask: 1.0 inside [sat_min, sat_max], soft falloff."""
    soft = max(softness, 0.01)
    low_weight = np.clip((sat - sat_min + soft) / (2.0 * soft), 0.0, 1.0)
    high_weight = np.clip((sat_max + soft - sat) / (2.0 * soft), 0.0, 1.0)
    return low_weight * high_weight


# ---------------------------------------------------------------------------
# Grid sampling — numpy stand-ins for torch_ops' F.grid_sample wrappers.
# Here a "grid" is simply the (src_y, src_x) pixel-coordinate pair; the
# normalization to [-1, 1] that grid_sample needs does not apply.
# ---------------------------------------------------------------------------

_PADDING_MODES = {
    # F.grid_sample(align_corners=True) reflects about edge pixel centers,
    # which is scipy's "mirror"; "zeros" pads with 0; "border" clamps.
    "reflection": "mirror",
    "zeros": "constant",
    "border": "nearest",
}


def pixel_to_grid_coords(src_y, src_x, h, w):
    """Identity packing of source pixel coordinates (see module docstring)."""
    return (src_y, src_x)


def grid_sample_channel(channel, grid, padding_mode="reflection"):
    """
    Sample a single (H, W) channel at the grid's source pixel positions,
    bicubic (order=3, matching upstream's mode='bicubic').
    """
    src_y, src_x = grid
    return map_coordinates(
        channel,
        [src_y, src_x],
        order=3,
        mode=_PADDING_MODES[padding_mode],
        cval=0.0,
    ).astype(np.float32)


def grid_sample_hwc(img, grid, padding_mode="zeros"):
    """Sample all channels of an (H, W, C) image with one shared grid."""
    return np.stack(
        [grid_sample_channel(img[..., c], grid, padding_mode) for c in range(img.shape[-1])],
        axis=-1,
    )

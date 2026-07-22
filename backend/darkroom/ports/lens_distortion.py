"""Lens Distortion — Stimma numpy port of upstream nodes/lens_distortion.py.

Brown-Conrady radial distortion (barrel / pincushion / mustache), from a real
lens profile or manual k1/k2. Upstream is torch (F.grid_sample); this port
resamples via np_ops.grid_sample_hwc. Same class API as vendored nodes.
"""

import numpy as np

from ..vendor.data.lens_profiles import LENS_PROFILES_FLAT, LENS_PROFILE_NAMES
from .np_ops import grid_sample_hwc, pixel_to_grid_coords

PRESET_NAMES = ["Custom"] + LENS_PROFILE_NAMES


def _apply_distortion(img, k1, k2):
    """r_distorted = r * (1 + k1*r^2 + k2*r^4). img: (H, W, C) float32."""
    h, w = img.shape[:2]
    cy, cx = h / 2.0, w / 2.0

    yy, xx = np.meshgrid(
        np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij"
    )
    ny = (yy - cy) / cy
    nx = (xx - cx) / cx

    r2 = nx * nx + ny * ny
    r4 = r2 * r2
    distort = 1.0 + k1 * r2 + k2 * r4

    src_x = nx * distort * cx + cx
    src_y = ny * distort * cy + cy

    grid = pixel_to_grid_coords(src_y, src_x, h, w)
    return np.clip(grid_sample_hwc(img, grid, padding_mode="zeros"), 0.0, 1.0)


class LensDistortion:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "lens": (PRESET_NAMES, {
                    "default": "Custom",
                    "tooltip": "Select a real lens or 'Custom' for manual distortion control"
                }),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": -2.0, "max": 2.0, "step": 0.1,
                    "tooltip": "Multiplier. Negative inverts (correct distortion instead of adding it)"
                }),
            },
            "optional": {
                "k1": ("FLOAT", {
                    "default": 0.0, "min": -1.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Primary radial coefficient. Negative=barrel, Positive=pincushion"
                }),
                "k2": ("FLOAT", {
                    "default": 0.0, "min": -0.5, "max": 0.5, "step": 0.01,
                    "tooltip": "Secondary radial coefficient. Creates mustache distortion when opposite sign to k1"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Lens"

    def execute(self, image, lens, strength, k1=0.0, k2=0.0):
        if lens != "Custom" and lens in LENS_PROFILES_FLAT:
            p = LENS_PROFILES_FLAT[lens]
            k1 = p.k1
            k2 = p.k2

        k1 *= strength
        k2 *= strength

        if abs(k1) < 0.001 and abs(k2) < 0.001:
            return (image,)

        print(f"[Darkroom] Lens Distortion: {lens}, k1={k1:.4f}, k2={k2:.4f}")

        results = [_apply_distortion(image[i], k1, k2) for i in range(image.shape[0])]
        return (np.stack(results, axis=0),)

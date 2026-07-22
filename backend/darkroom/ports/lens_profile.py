"""Lens Profile — Stimma numpy port of upstream nodes/lens_profile.py.

Combined distortion + CA + vignette from one of 102 real lens profiles, in
"Add Aberrations" (simulate the lens) or "Correct Aberrations" (invert it)
mode. Distortion and CA compound into a single resample per channel.
"""

import math

import numpy as np

from ..vendor.data.lens_profiles import LENS_PROFILES_FLAT, LENS_PROFILE_NAMES
from .np_ops import grid_sample_channel, pixel_to_grid_coords

PRESET_NAMES = LENS_PROFILE_NAMES  # No "Custom" — use individual nodes for that


def _apply_lens_profile(img, k1, k2, ca_r, ca_b, vignette_strength, vignette_mid, mode):
    """img: (H, W, C) float32."""
    h, w = img.shape[:2]
    cy, cx = h / 2.0, w / 2.0
    scale = min(h, w) / 1024.0

    yy, xx = np.meshgrid(
        np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij"
    )
    ny = (yy - cy) / cy
    nx = (xx - cx) / cx
    r2 = nx * nx + ny * ny
    r4 = r2 * r2
    r = np.sqrt(r2)
    max_r = math.sqrt(cx * cx + cy * cy)

    result = np.empty_like(img)

    # Per-channel: each gets distortion + its own CA shift
    ca_shifts = [ca_r * scale, 0.0, ca_b * scale]

    for c in range(3):
        distort = 1.0 + k1 * r2 + k2 * r4

        ca = ca_shifts[c]
        if abs(ca) > 0.01:
            ca_factor = 1.0 + (ca / max_r) * r
            total_factor = distort * ca_factor
        else:
            total_factor = distort

        src_x = nx * total_factor * cx + cx
        src_y = ny * total_factor * cy + cy

        grid = pixel_to_grid_coords(src_y, src_x, h, w)
        result[..., c] = grid_sample_channel(img[..., c], grid, padding_mode="reflection")

    # Vignette
    if vignette_strength > 0.01:
        cos_theta = 1.0 / np.sqrt(1.0 + r2)
        falloff = cos_theta ** 4
        transition = np.clip((r - vignette_mid * 0.8) / 0.4, 0.0, 1.0)

        if mode == "Add Aberrations":
            # Darken edges
            mask = np.clip(1.0 - transition * (1.0 - falloff) * vignette_strength * 2, 0.0, 1.0)
            result = result * mask[..., np.newaxis]
        else:
            # Brighten edges (correct vignette)
            correction = 1.0 + transition * (1.0 / np.clip(falloff, 0.3, 1.0) - 1.0) * vignette_strength
            result = result * correction[..., np.newaxis]

    return np.clip(result, 0.0, 1.0)


class LensProfile:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "lens": (PRESET_NAMES, {
                    "default": PRESET_NAMES[0],
                    "tooltip": "Select a lens to simulate or correct its optical characteristics"
                }),
                "mode": (["Add Aberrations", "Correct Aberrations"], {
                    "default": "Add Aberrations",
                    "tooltip": "'Add' simulates lens flaws. 'Correct' removes them (inverts the profile)"
                }),
            },
            "optional": {
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.1,
                    "tooltip": "Overall profile strength. 0.5 = half effect"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Lens"

    def execute(self, image, lens, mode, strength=1.0):
        if strength < 0.01 or lens not in LENS_PROFILES_FLAT:
            return (image,)

        p = LENS_PROFILES_FLAT[lens]
        sign = 1.0 if mode == "Add Aberrations" else -1.0

        k1 = p.k1 * strength * sign
        k2 = p.k2 * strength * sign
        ca_r = p.ca_r * strength * sign
        ca_b = p.ca_b * strength * sign
        vig = p.vig_strength * strength
        vig_mid = p.vig_midpoint

        print(f"[Darkroom] Lens Profile: {p.name} ({mode}), strength={strength}")

        results = [
            _apply_lens_profile(image[i], k1, k2, ca_r, ca_b, vig, vig_mid, mode)
            for i in range(image.shape[0])
        ]
        return (np.stack(results, axis=0),)

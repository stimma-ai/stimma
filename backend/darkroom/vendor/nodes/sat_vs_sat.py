"""
Sat vs Sat node for ComfyUI-Darkroom.
Adjust saturation based on existing saturation level with presets and per-zone control.
"""

import numpy as np

from ..utils.color import srgb_to_linear, linear_to_srgb, luminance_rec709, blend
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor
from ..utils.grading import sat_from_rgb, sat_range_mask
from ..data.grading_presets import SAT_VS_SAT_PRESETS, SAT_VS_SAT_PRESET_NAMES


# 4 saturation zones: center and width for Gaussian masks
SAT_ZONES = {
    "low":      (0.125, 0.12),
    "mid_low":  (0.375, 0.12),
    "mid_high": (0.625, 0.12),
    "high":     (0.875, 0.12),
}


class SatVsSat:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "preset": (SAT_VS_SAT_PRESET_NAMES, {
                    "default": "Custom (manual)",
                    "tooltip": "Select a saturation-based saturation preset or use Custom"
                }),
            },
            "optional": {
                "low_sat_adjust": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Adjust nearly-desaturated tones (0-25% saturation)"
                }),
                "mid_low_sat_adjust": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Adjust low-saturation tones (25-50% saturation)"
                }),
                "mid_high_sat_adjust": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Adjust medium-saturation tones (50-75% saturation)"
                }),
                "high_sat_adjust": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Adjust highly-saturated tones (75-100% saturation)"
                }),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Blend between original (0) and adjusted (1)"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Grading"

    def execute(self, image, preset="Custom (manual)", low_sat_adjust=0.0,
                mid_low_sat_adjust=0.0, mid_high_sat_adjust=0.0,
                high_sat_adjust=0.0, strength=1.0):

        if strength <= 0.0:
            return (image,)

        adjustments = {
            "low": low_sat_adjust,
            "mid_low": mid_low_sat_adjust,
            "mid_high": mid_high_sat_adjust,
            "high": high_sat_adjust,
        }

        if preset != "Custom (manual)" and preset in SAT_VS_SAT_PRESETS:
            p = SAT_VS_SAT_PRESETS[preset]
            adjustments["low"] += p.low
            adjustments["mid_low"] += p.mid_low
            adjustments["mid_high"] += p.mid_high
            adjustments["high"] += p.high

        active = [(name, val) for name, val in adjustments.items() if abs(val) > 0.5]
        if not active:
            return (image,)

        print(f"[Darkroom] Sat vs Sat: preset={preset}, {len(active)} active zones, strength={strength}")

        images = tensor_to_numpy_batch(image)
        results = []

        for img in images:
            original = img.copy()
            linear = srgb_to_linear(img)
            lum = luminance_rec709(linear)

            # Compute per-pixel saturation
            sat = sat_from_rgb(linear)

            # Compute combined adjustment factor
            sat_factor = np.ones_like(sat)
            for zone_name, adj_value in active:
                center, width = SAT_ZONES[zone_name]
                mask = sat_range_mask(sat, center, width)
                sat_factor += mask * (adj_value / 100.0)

            # Apply luminance-preserving saturation scaling
            lum_3d = lum[..., np.newaxis]
            result = lum_3d + sat_factor[..., np.newaxis] * (linear - lum_3d)
            result = np.clip(result, 0.0, 1.0).astype(np.float32)

            result = linear_to_srgb(result)
            results.append(blend(original, result, strength))

        return (numpy_batch_to_tensor(results),)


NODE_CLASS_MAPPINGS = {"DarkroomSatVsSat": SatVsSat}
NODE_DISPLAY_NAME_MAPPINGS = {"DarkroomSatVsSat": "Sat vs Sat"}

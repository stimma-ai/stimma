"""
3-Way Color Balance node for ComfyUI-Darkroom.
Preset-first creative color tinting in shadows/midtones/highlights.
"""

import numpy as np

from ..utils.color import srgb_to_linear, linear_to_srgb, luminance_rec709, adjust_saturation, blend
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor
from ..utils.grading import lgg_zone_masks, apply_color_tint_to_zone
from ..data.grading_presets import COLOR_BALANCE_PRESETS, COLOR_BALANCE_PRESET_NAMES


class ThreeWayColorBalance:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "preset": (COLOR_BALANCE_PRESET_NAMES, {
                    "default": "Custom (manual)",
                    "tooltip": "Select a creative color balance look or use Custom"
                }),
            },
            "optional": {
                "shadow_hue": ("FLOAT", {
                    "default": 210.0, "min": 0.0, "max": 360.0, "step": 1.0,
                    "tooltip": "Shadow tint direction (0=red, 60=yellow, 120=green, 180=cyan, 240=blue, 300=magenta)"
                }),
                "shadow_intensity": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Shadow tint intensity"
                }),
                "midtone_hue": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 360.0, "step": 1.0,
                    "tooltip": "Midtone tint direction"
                }),
                "midtone_intensity": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Midtone tint intensity"
                }),
                "highlight_hue": ("FLOAT", {
                    "default": 40.0, "min": 0.0, "max": 360.0, "step": 1.0,
                    "tooltip": "Highlight tint direction"
                }),
                "highlight_intensity": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Highlight tint intensity"
                }),
                "preserve_luminance": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Prevent color tinting from changing overall brightness"
                }),
                "master_saturation": ("FLOAT", {
                    "default": 0.0, "min": -50.0, "max": 50.0, "step": 1.0,
                    "tooltip": "Global saturation adjustment on top of tinting"
                }),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Blend between original (0) and tinted (1)"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Grading"

    def execute(self, image, preset="Custom (manual)",
                shadow_hue=210.0, shadow_intensity=0.0,
                midtone_hue=0.0, midtone_intensity=0.0,
                highlight_hue=40.0, highlight_intensity=0.0,
                preserve_luminance=True, master_saturation=0.0, strength=1.0):

        if strength <= 0.0:
            return (image,)

        # Apply preset values (manual sliders add on top)
        s_hue, s_int = shadow_hue, shadow_intensity
        m_hue, m_int = midtone_hue, midtone_intensity
        h_hue, h_int = highlight_hue, highlight_intensity
        m_sat = master_saturation

        if preset != "Custom (manual)" and preset in COLOR_BALANCE_PRESETS:
            p = COLOR_BALANCE_PRESETS[preset]
            # For hue: use preset hue when manual intensity is 0, otherwise use manual
            if shadow_intensity < 0.5:
                s_hue = p.shadow_hue
            s_int += p.shadow_intensity
            if midtone_intensity < 0.5:
                m_hue = p.midtone_hue
            m_int += p.midtone_intensity
            if highlight_intensity < 0.5:
                h_hue = p.highlight_hue
            h_int += p.highlight_intensity
            m_sat += p.master_saturation

        # Check if anything is active
        if s_int < 0.5 and m_int < 0.5 and h_int < 0.5 and abs(m_sat) < 0.5:
            return (image,)

        print(f"[Darkroom] 3-Way Color Balance: preset={preset}, S={s_hue:.0f}/{s_int:.0f}, "
              f"M={m_hue:.0f}/{m_int:.0f}, H={h_hue:.0f}/{h_int:.0f}, strength={strength}")

        images = tensor_to_numpy_batch(image)
        results = []

        for img in images:
            original = img.copy()
            linear = srgb_to_linear(img)
            lum = luminance_rec709(linear)

            # Build zone masks
            lift_mask, gamma_mask, gain_mask = lgg_zone_masks(lum)

            result = linear.copy()

            # Apply tints per zone
            if s_int >= 0.5:
                result = apply_color_tint_to_zone(result, lift_mask, s_hue, s_int)
            if m_int >= 0.5:
                result = apply_color_tint_to_zone(result, gamma_mask, m_hue, m_int)
            if h_int >= 0.5:
                result = apply_color_tint_to_zone(result, gain_mask, h_hue, h_int)

            # Preserve luminance: restore original luminance channel
            if preserve_luminance:
                new_lum = luminance_rec709(result)
                scale = np.where(new_lum > 1e-6, lum / (new_lum + 1e-10), 1.0)
                result = result * scale[..., np.newaxis]
                result = np.clip(result, 0.0, 1.0).astype(np.float32)

            # Master saturation
            if abs(m_sat) >= 0.5:
                factor = 1.0 + m_sat / 50.0  # -50→0, 0→1, +50→2
                result = adjust_saturation(result, factor)

            result = linear_to_srgb(result)
            results.append(blend(original, result, strength))

        return (numpy_batch_to_tensor(results),)


NODE_CLASS_MAPPINGS = {"DarkroomThreeWayColorBalance": ThreeWayColorBalance}
NODE_DISPLAY_NAME_MAPPINGS = {"DarkroomThreeWayColorBalance": "3-Way Color Balance"}

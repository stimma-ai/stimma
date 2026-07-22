"""
Vibrance node for ComfyUI-Darkroom.
Intelligent saturation that protects already-saturated colors and skin tones.
"""

import numpy as np

from ..utils.color import srgb_to_linear, linear_to_srgb, luminance_rec709, adjust_saturation, blend
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor


def _fast_hue(r, g, b):
    """
    Fast hue extraction from RGB. Returns hue in degrees [0, 360).
    Avoids full HSL conversion for skin tone detection only.
    """
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin

    h = np.zeros_like(r)
    mask = delta > 1e-7

    mask_r = mask & (cmax == r)
    mask_g = mask & (cmax == g) & ~mask_r
    mask_b = mask & ~mask_r & ~mask_g

    h[mask_r] = 60.0 * (((g[mask_r] - b[mask_r]) / (delta[mask_r] + 1e-10)) % 6)
    h[mask_g] = 60.0 * (((b[mask_g] - r[mask_g]) / (delta[mask_g] + 1e-10)) + 2)
    h[mask_b] = 60.0 * (((r[mask_b] - g[mask_b]) / (delta[mask_b] + 1e-10)) + 4)

    return (h % 360.0).astype(np.float32)


class Vibrance:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "vibrance": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Intelligent saturation. Protects skin tones and already-saturated colors"
                }),
            },
            "optional": {
                "saturation": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Uniform saturation boost (no protection). Use vibrance for natural results"
                }),
                "protect_skin": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Reduce vibrance effect on skin-tone hues (oranges/warm yellows)"
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
    CATEGORY = "AKURATE/Darkroom/Raw"

    def execute(self, image, vibrance=0.0, saturation=0.0, protect_skin=True, strength=1.0):
        if strength <= 0.0 or (abs(vibrance) < 0.5 and abs(saturation) < 0.5):
            return (image,)

        images = tensor_to_numpy_batch(image)
        results = []

        for img in images:
            original = img.copy()
            linear = srgb_to_linear(img)
            result = linear.copy()

            # Vibrance: saturation-aware boost
            if abs(vibrance) > 0.5:
                r, g, b = result[..., 0], result[..., 1], result[..., 2]
                lum = luminance_rec709(result)

                # Per-pixel chroma (how saturated each pixel already is)
                cmax = np.maximum(np.maximum(r, g), b)
                cmin = np.minimum(np.minimum(r, g), b)
                chroma = cmax - cmin

                # Weight: less saturated pixels get more boost
                weight = (1.0 - np.clip(chroma * 2.0, 0.0, 1.0)).astype(np.float32)

                # Skin tone protection
                if protect_skin:
                    hue = _fast_hue(r, g, b)
                    # Skin tones: ~15-45 degrees (orange/warm yellow)
                    skin_center = 30.0
                    skin_width = 30.0
                    diff = np.abs(hue - skin_center)
                    diff = np.minimum(diff, 360.0 - diff)
                    skin_mask = np.clip((1.0 + np.cos(np.pi * diff / skin_width)) * 0.5, 0.0, 1.0)
                    skin_mask[diff > skin_width] = 0.0
                    weight *= (1.0 - 0.7 * skin_mask)

                # Apply vibrance
                vib_factor = 1.0 + (vibrance / 100.0) * weight
                result = lum[..., np.newaxis] + vib_factor[..., np.newaxis] * (result - lum[..., np.newaxis])

            # Uniform saturation (no protection)
            if abs(saturation) > 0.5:
                result = adjust_saturation(result, 1.0 + saturation / 100.0)

            result = linear_to_srgb(np.clip(result, 0.0, 1.0))
            results.append(blend(original, result, strength))

        return (numpy_batch_to_tensor(results),)


NODE_CLASS_MAPPINGS = {"DarkroomVibrance": Vibrance}
NODE_DISPLAY_NAME_MAPPINGS = {"DarkroomVibrance": "Vibrance"}

"""
Clarity / Texture / Dehaze node for ComfyUI-Darkroom.
Three mid-frequency contrast tools in one node.
"""

import numpy as np
from scipy.ndimage import gaussian_filter, minimum_filter

from ..utils.color import luminance_rec709, blend
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor
from ..data.ai_mitigation_presets import AI_MITIGATION_CTD, CTD_PRESET_NAMES


class ClarityTextureDehaze:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "clarity": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Large-scale local contrast (midtone punch). Negative = soften"
                }),
                "texture": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Fine detail enhancement without affecting edges. Negative = smooth"
                }),
                "dehaze": ("FLOAT", {
                    "default": 0.0, "min": -100.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Remove atmospheric haze. Negative = add haze effect"
                }),
            },
            "optional": {
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Blend between original (0) and adjusted (1)"
                }),
                "preset": (CTD_PRESET_NAMES, {
                    "default": "Custom (manual)",
                    "tooltip": "AI Mitigation presets stack with HSL Selective preset of the same tier. Manual sliders add on top"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Raw"

    def execute(self, image, clarity=0.0, texture=0.0, dehaze=0.0, strength=1.0,
                preset="Custom (manual)"):
        if preset != "Custom (manual)" and preset in AI_MITIGATION_CTD:
            p = AI_MITIGATION_CTD[preset]
            clarity = clarity + p.clarity
            texture = texture + p.texture
            dehaze = dehaze + p.dehaze

        if strength <= 0.0 or (abs(clarity) < 0.5 and abs(texture) < 0.5 and abs(dehaze) < 0.5):
            return (image,)

        images = tensor_to_numpy_batch(image)
        results = []

        for img in images:
            original = img.copy()
            result = img.copy()
            h, w = img.shape[:2]

            # All three tools operate via luminance to avoid color shifts
            lum = luminance_rec709(img)

            # --- Clarity: large-scale local contrast ---
            if abs(clarity) > 0.5:
                clarity_sigma = max(h, w) * 0.04
                blur = gaussian_filter(lum, sigma=clarity_sigma)
                detail = lum - blur
                amount = clarity / 100.0 * 0.5

                # Apply to RGB proportionally (preserves color ratios)
                lum_safe = lum + 1e-6
                for c in range(3):
                    result[..., c] += detail * amount * (result[..., c] / lum_safe)

            # --- Texture: band-pass fine detail ---
            if abs(texture) > 0.5:
                small_sigma = 1.0
                large_sigma = max(h, w) * 0.01
                small_blur = gaussian_filter(lum, sigma=small_sigma)
                large_blur = gaussian_filter(lum, sigma=large_sigma)
                texture_detail = small_blur - large_blur
                amount = texture / 100.0 * 0.5

                lum_safe = luminance_rec709(result) + 1e-6
                for c in range(3):
                    result[..., c] += texture_detail * amount * (result[..., c] / lum_safe)

            # --- Dehaze: dark channel prior (simplified) ---
            if abs(dehaze) > 0.5:
                dehaze_amount = dehaze / 100.0

                if dehaze_amount > 0:
                    # Dark channel: min across RGB in a local patch
                    min_rgb = np.min(result, axis=-1)
                    patch_size = max(15, max(h, w) // 50)
                    dark_channel = minimum_filter(min_rgb, size=patch_size)

                    # Atmospheric light: mean of brightest 0.1% in dark channel
                    n_bright = max(1, int(h * w * 0.001))
                    flat_dark = dark_channel.ravel()
                    bright_indices = np.argpartition(flat_dark, -n_bright)[-n_bright:]
                    flat_img = result.reshape(-1, 3)
                    atmos = flat_img[bright_indices].mean(axis=0)
                    atmos = np.maximum(atmos, 0.1)

                    # Transmission map
                    transmission = 1.0 - dehaze_amount * (dark_channel / (atmos.max() + 1e-6))
                    transmission = np.clip(transmission, 0.1, 1.0)

                    # Recover scene
                    for c in range(3):
                        result[..., c] = (result[..., c] - atmos[c]) / transmission + atmos[c]
                else:
                    # Negative dehaze: add haze (blend toward mean brightness)
                    mean_val = result.mean()
                    haze_amount = abs(dehaze_amount)
                    result = result * (1.0 - haze_amount * 0.5) + mean_val * haze_amount * 0.5

            result = np.clip(result, 0.0, 1.0).astype(np.float32)
            results.append(blend(original, result, strength))

        return (numpy_batch_to_tensor(results),)


NODE_CLASS_MAPPINGS = {"DarkroomClarityTextureDehaze": ClarityTextureDehaze}
NODE_DISPLAY_NAME_MAPPINGS = {"DarkroomClarityTextureDehaze": "Clarity / Texture / Dehaze"}

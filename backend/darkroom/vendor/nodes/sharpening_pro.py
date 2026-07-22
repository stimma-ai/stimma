"""
Sharpening Pro node for ComfyUI-Darkroom.
Lightroom-style sharpening with Amount, Radius, Detail, and edge-aware Masking.
"""

import numpy as np
from scipy.ndimage import gaussian_filter

from ..utils.color import luminance_rec709, blend
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor
from ..utils.raw import edge_mask


class SharpeningPro:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "amount": ("FLOAT", {
                    "default": 40.0, "min": 0.0, "max": 150.0, "step": 1.0,
                    "tooltip": "Sharpening amount (0-150). How much sharpening to apply"
                }),
                "radius": ("FLOAT", {
                    "default": 1.0, "min": 0.5, "max": 3.0, "step": 0.1,
                    "tooltip": "Sharpening radius. Larger = coarser detail enhancement"
                }),
            },
            "optional": {
                "detail": ("FLOAT", {
                    "default": 25.0, "min": 0.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Fine detail emphasis. Higher = sharpen finer textures more"
                }),
                "masking": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100.0, "step": 1.0,
                    "tooltip": "Edge-aware masking. Higher = sharpen only edges, protect smooth areas"
                }),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Blend between original (0) and sharpened (1)"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Raw"

    def execute(self, image, amount=40.0, radius=1.0, detail=25.0,
                masking=0.0, strength=1.0):
        if strength <= 0.0 or amount < 0.5:
            return (image,)

        images = tensor_to_numpy_batch(image)
        results = []

        for img in images:
            original = img.copy()

            # Sharpen luminance only (preserves color)
            lum = luminance_rec709(img)

            # Primary unsharp mask
            blur = gaussian_filter(lum, sigma=radius)
            detail_layer = lum - blur

            # Fine detail pass (half radius for finer structures)
            if detail > 0.5:
                fine_blur = gaussian_filter(lum, sigma=radius * 0.5)
                fine_detail = lum - fine_blur
                detail_layer = detail_layer + fine_detail * (detail / 100.0) * 0.5

            # Scale by amount
            sharpening = detail_layer * (amount / 100.0)

            # Edge-aware masking
            if masking > 0.5:
                mask = edge_mask(lum, masking / 100.0)
                sharpening *= mask

            # Apply luminance sharpening to RGB (ratio method preserves color)
            sharpened_lum = lum + sharpening
            ratio = sharpened_lum / (lum + 1e-6)
            # Clamp ratio to avoid extreme amplification in very dark areas
            ratio = np.clip(ratio, 0.5, 2.0)

            result = img * ratio[..., np.newaxis]
            result = np.clip(result, 0.0, 1.0).astype(np.float32)
            results.append(blend(original, result, strength))

        return (numpy_batch_to_tensor(results),)


NODE_CLASS_MAPPINGS = {"DarkroomSharpeningPro": SharpeningPro}
NODE_DISPLAY_NAME_MAPPINGS = {"DarkroomSharpeningPro": "Sharpening Pro"}

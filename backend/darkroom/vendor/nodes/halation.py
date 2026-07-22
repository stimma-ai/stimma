"""
Halation node for ComfyUI-Darkroom.
Simulates light bouncing off film base — warm glow around highlights.
"""

import numpy as np

from ..utils.color import luminance_rec709
from ..utils.image import (
    tensor_to_numpy_batch, numpy_batch_to_tensor,
    apply_gaussian_blur, apply_disk_blur
)


# Presets: threshold, radius, strength, tint (R, G, B)
HALATION_PRESETS = {
    "Subtle": {
        "threshold": 0.85, "radius": 15, "strength": 0.15,
        "tint_r": 1.0, "tint_g": 0.3, "tint_b": 0.1,
    },
    "Standard": {
        "threshold": 0.75, "radius": 25, "strength": 0.3,
        "tint_r": 1.0, "tint_g": 0.4, "tint_b": 0.15,
    },
    "Cinestill 800T": {
        "threshold": 0.65, "radius": 40, "strength": 0.5,
        "tint_r": 1.0, "tint_g": 0.2, "tint_b": 0.05,
    },
    "Custom": {
        "threshold": 0.75, "radius": 25, "strength": 0.3,
        "tint_r": 1.0, "tint_g": 0.4, "tint_b": 0.15,
    },
}

PRESET_NAMES = list(HALATION_PRESETS.keys())


class Halation:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "preset": (PRESET_NAMES, {
                    "default": "Standard",
                    "tooltip": "Halation preset. 'Custom' uses the manual controls below"
                }),
                "strength": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Overall halation intensity"
                }),
            },
            "optional": {
                "threshold": ("FLOAT", {
                    "default": 0.75, "min": 0.3, "max": 1.0, "step": 0.05,
                    "tooltip": "Luminance threshold for highlight extraction. Lower = more glow"
                }),
                "radius": ("INT", {
                    "default": 25, "min": 5, "max": 100, "step": 5,
                    "tooltip": "Blur radius (normalized to 1024px). Controls glow spread"
                }),
                "tint_r": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Red component of halation tint"
                }),
                "tint_g": ("FLOAT", {
                    "default": 0.4, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Green component of halation tint"
                }),
                "tint_b": ("FLOAT", {
                    "default": 0.15, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Blue component of halation tint"
                }),
                "blur_type": (["gaussian", "disk"], {
                    "default": "gaussian",
                    "tooltip": "Gaussian is faster. Disk is physically accurate"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Film"

    def execute(self, image, preset, strength,
                threshold=0.75, radius=25, tint_r=1.0, tint_g=0.4, tint_b=0.15,
                blur_type="gaussian"):

        if strength <= 0.0:
            return (image,)

        # Load preset values (Custom uses the manual inputs)
        if preset != "Custom":
            p = HALATION_PRESETS[preset]
            threshold = p["threshold"]
            radius = p["radius"]
            tint_r = p["tint_r"]
            tint_g = p["tint_g"]
            tint_b = p["tint_b"]

        print(f"[Darkroom] Halation: preset={preset}, threshold={threshold}, radius={radius}, strength={strength}")

        tint = np.array([tint_r, tint_g, tint_b], dtype=np.float32)

        arrays = tensor_to_numpy_batch(image)
        processed = []

        for img in arrays:
            h, w = img.shape[:2]

            # Resolution-normalized radius
            effective_radius = max(3, int(radius * min(h, w) / 1024.0))

            # Compute luminance
            lum = luminance_rec709(img)

            # Soft threshold: smooth mask instead of hard cutoff
            ceiling = 1.0 - threshold
            if ceiling < 0.01:
                ceiling = 0.01
            mask = np.clip((lum - threshold) / ceiling, 0.0, 1.0)

            # Extract highlights
            highlights = img * mask[..., np.newaxis]

            # Blur the highlights
            if blur_type == "disk":
                blurred = apply_disk_blur(highlights, effective_radius)
            else:
                blurred = apply_gaussian_blur(highlights, effective_radius)

            # Tint the blurred highlights
            tinted = blurred * tint[np.newaxis, np.newaxis, :]

            # Screen blend: result = 1 - (1-original) * (1-halation*strength)
            halation_layer = tinted * strength
            result = 1.0 - (1.0 - img) * (1.0 - halation_layer)

            result = np.clip(result, 0.0, 1.0).astype(np.float32)
            processed.append(result)

        return (numpy_batch_to_tensor(processed),)


NODE_CLASS_MAPPINGS = {
    "DarkroomHalation": Halation,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DarkroomHalation": "Halation",
}

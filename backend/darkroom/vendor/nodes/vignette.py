"""
Vignette node for ComfyUI-Darkroom.

Physically-based optical vignette simulation using the cos^4 law
(natural light falloff) plus mechanical vignetting from lens barrel.

Select a real lens profile or use Custom for manual control.
"""

import numpy as np

from ..data.lens_profiles import LENS_PROFILES_FLAT, LENS_PROFILE_NAMES
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor


PRESET_NAMES = ["Custom"] + LENS_PROFILE_NAMES


def _build_vignette_mask(h, w, midpoint, roundness, feather, use_cos4):
    """Build a vignette falloff mask."""
    cy, cx = h / 2.0, w / 2.0

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    dy = (yy - cy) / cy
    dx = (xx - cx) / cx

    if roundness != 1.0:
        dy = dy / max(roundness, 0.01)

    r = np.sqrt(dx * dx + dy * dy)

    if use_cos4:
        cos_theta = 1.0 / np.sqrt(1.0 + r * r)
        falloff = cos_theta ** 4
        transition = np.clip((r - midpoint * 0.8) / max(feather, 0.01), 0.0, 1.0)
        mask = 1.0 - transition * (1.0 - falloff)
    else:
        inner = midpoint
        outer = midpoint + feather * (1.414 - midpoint)
        mask = 1.0 - np.clip((r - inner) / max(outer - inner, 0.01), 0.0, 1.0)
        mask = mask ** 1.5

    return mask.astype(np.float32)


class Vignette:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "lens": (PRESET_NAMES, {
                    "default": "Custom",
                    "tooltip": "Select a real lens or 'Custom' for manual vignette control"
                }),
                "intensity": ("FLOAT", {
                    "default": 0.5, "min": -1.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Darkening intensity. Negative = anti-vignette (brighten edges)"
                }),
            },
            "optional": {
                "midpoint": ("FLOAT", {
                    "default": 0.5, "min": 0.1, "max": 1.0, "step": 0.05,
                    "tooltip": "Where falloff begins. 0.1=near center, 1.0=only at corners"
                }),
                "roundness": ("FLOAT", {
                    "default": 1.0, "min": 0.3, "max": 2.0, "step": 0.1,
                    "tooltip": "Shape: 1.0=circular, <1=wide ellipse, >1=tall ellipse"
                }),
                "feather": ("FLOAT", {
                    "default": 0.4, "min": 0.05, "max": 1.0, "step": 0.05,
                    "tooltip": "Transition smoothness. Higher = more gradual falloff"
                }),
                "cos4_falloff": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Use physically-based cos^4 light falloff law"
                }),
                "tint_r": ("FLOAT", {
                    "default": 1.0, "min": 0.5, "max": 1.5, "step": 0.05,
                    "tooltip": "Red tint in vignetted areas. >1 = warm vignette"
                }),
                "tint_g": ("FLOAT", {
                    "default": 1.0, "min": 0.5, "max": 1.5, "step": 0.05,
                    "tooltip": "Green tint in vignetted areas"
                }),
                "tint_b": ("FLOAT", {
                    "default": 1.0, "min": 0.5, "max": 1.5, "step": 0.05,
                    "tooltip": "Blue tint in vignetted areas. >1 = cool vignette"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Lens"

    def execute(self, image, lens, intensity,
                midpoint=0.5, roundness=1.0, feather=0.4, cos4_falloff=True,
                tint_r=1.0, tint_g=1.0, tint_b=1.0):

        if abs(intensity) < 0.01:
            return (image,)

        if lens != "Custom" and lens in LENS_PROFILES_FLAT:
            p = LENS_PROFILES_FLAT[lens]
            midpoint = p.vig_midpoint
            # Use lens vignette strength as the base, modulated by intensity
            intensity = intensity * (p.vig_strength / 0.5) if p.vig_strength > 0 else intensity

        print(f"[Darkroom] Vignette: {lens}, intensity={intensity:.2f}, midpoint={midpoint:.2f}")

        arrays = tensor_to_numpy_batch(image)
        processed = []

        for img in arrays:
            h, w = img.shape[:2]
            mask = _build_vignette_mask(h, w, midpoint, roundness, feather, cos4_falloff)

            if intensity > 0:
                vignette = mask ** (intensity * 2)
            else:
                vignette = 1.0 + (1.0 - mask) * abs(intensity)

            tint = np.array([tint_r, tint_g, tint_b], dtype=np.float32)
            result = img.copy()
            for c in range(3):
                if intensity > 0:
                    channel_vignette = vignette * (1.0 + (tint[c] - 1.0) * (1.0 - mask))
                    result[..., c] = img[..., c] * channel_vignette
                else:
                    result[..., c] = img[..., c] * vignette * tint[c]

            result = np.clip(result, 0.0, 1.0).astype(np.float32)
            processed.append(result)

        return (numpy_batch_to_tensor(processed),)


NODE_CLASS_MAPPINGS = {
    "DarkroomVignette": Vignette,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DarkroomVignette": "Vignette",
}

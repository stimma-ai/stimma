"""
Film Grain node for ComfyUI-Darkroom.
Luminance-dependent, multi-octave grain with ISO-based sizing.
"""

from ..utils.color import luminance_rec709, blend
from ..utils.image import tensor_to_numpy_batch, numpy_batch_to_tensor
from ..utils.grain import generate_grain, apply_grain


class FilmGrain:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "iso": ("INT", {
                    "default": 400, "min": 50, "max": 3200, "step": 50,
                    "tooltip": "Film speed. Higher ISO = coarser, more visible grain"
                }),
                "strength": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Overall grain intensity"
                }),
                "color_grain": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Per-channel grain variation. 0 = luminance only, 1 = full color grain"
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0xFFFFFFFF,
                    "tooltip": "Random seed for reproducible grain pattern"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Film"

    def execute(self, image, iso, strength, color_grain, seed):
        if strength <= 0.0:
            return (image,)

        print(f"[Darkroom] Film Grain: ISO {iso}, strength={strength}, color={color_grain}")

        arrays = tensor_to_numpy_batch(image)
        processed = []

        for idx, img in enumerate(arrays):
            h, w = img.shape[:2]

            # Per-image seed offset for batch variation
            img_seed = seed + idx * 7919

            # Generate grain pattern
            grain = generate_grain(h, w, iso=iso, seed=img_seed)

            # Compute luminance for modulation
            lum = luminance_rec709(img)

            # Apply grain (added in sRGB space — matches film's perceptual grain)
            result = apply_grain(img, grain, lum, strength=strength, color_amount=color_grain)
            processed.append(result)

        return (numpy_batch_to_tensor(processed),)


NODE_CLASS_MAPPINGS = {
    "DarkroomFilmGrain": FilmGrain,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DarkroomFilmGrain": "Film Grain",
}

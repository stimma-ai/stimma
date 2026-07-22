"""Film Grain Pro — Stimma numpy port of upstream nodes/film_grain_pro.py.

Physically-derived, resolution-independent film grain using the Newson et al.
(IPOL 2017) stochastic Boolean-model renderer (see ./grain_newson.py). The
quality tier alongside the fast heuristic Film Grain node. CPU-only here;
Monte-Carlo cost is linear in monte_carlo_samples.
"""

import numpy as np

from .grain_newson import render_film_grain


class FilmGrainPro:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "grain_size": ("FLOAT", {
                    "default": 1.2, "min": 0.7, "max": 4.0, "step": 0.05,
                    "tooltip": "Grain radius in pixels at a 1024px reference. "
                               "Scaled with image size so grain stays a fixed "
                               "fraction of the frame at any resolution."
                }),
                "strength": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Grain intensity. Blends the grainy render with "
                               "the original (tone is preserved either way)."
                }),
                "radius_variation": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 0.5, "step": 0.05,
                    "tooltip": "Grain size variability (sigma/mean). 0 = uniform "
                               "grains, higher = mixed sizes (log-normal)."
                }),
                "color_grain": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "0 = monochrome (luminance) grain, 1 = independent "
                               "per-channel grain (chroma grain, like color film)."
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 0xFFFFFFFF,
                    "tooltip": "Random seed for a reproducible grain pattern."
                }),
            },
            "optional": {
                "monte_carlo_samples": ("INT", {
                    # Port deviation: upstream defaults to 64 (GPU). This CPU
                    # render costs ~10s per megapixel per 16 samples, so the
                    # default is lowered to keep typical images tolerable.
                    "default": 16, "min": 8, "max": 256, "step": 8,
                    "tooltip": "Render quality. Higher = cleaner estimate (grain "
                               "is preserved) but slower — cost is linear: "
                               "roughly 10s per megapixel at 16 samples on CPU."
                }),
                "filter_sigma": ("FLOAT", {
                    "default": 0.8, "min": 0.4, "max": 2.0, "step": 0.1,
                    "tooltip": "Grain softness (Gaussian filter sigma in output "
                               "pixels). 0.8 is the physically-motivated default."
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "execute"
    CATEGORY = "AKURATE/Darkroom/Film"

    def execute(self, image, grain_size, strength, radius_variation, color_grain,
                seed, monte_carlo_samples=64, filter_sigma=0.8):
        if strength <= 0.0:
            return (image,)

        print(f"[Darkroom] Film Grain Pro (Newson): size={grain_size} "
              f"strength={strength} var={radius_variation} color={color_grain} "
              f"N={monte_carlo_samples} on cpu/numpy")

        out = []
        for idx in range(image.shape[0]):
            out.append(render_film_grain(
                image[idx],
                grain_size=grain_size,
                radius_variation=radius_variation,
                strength=strength,
                color_grain=color_grain,
                n_samples=int(monte_carlo_samples),
                filter_sigma=filter_sigma,
                seed=int(seed) + idx * 7919,
            ))

        return (np.stack(out, axis=0),)

"""
Film grain generation engine for ComfyUI-Darkroom.
Multi-octave noise with luminance-dependent intensity.
"""

import numpy as np
from scipy.ndimage import gaussian_filter

try:
    from opensimplex import OpenSimplex
    HAS_OPENSIMPLEX = True
except ImportError:
    HAS_OPENSIMPLEX = False


def _generate_simplex_grain(height, width, iso, seed):
    """Generate multi-octave simplex noise grain. Higher quality, slower."""
    noise_gen = OpenSimplex(seed=seed)

    # Scale grain frequency relative to image size so grain looks consistent
    # across resolutions. Reference: 1024px on the long edge.
    ref_size = 1024.0
    size_scale = max(height, width) / ref_size

    # ISO controls base frequency: higher ISO = coarser grain = lower frequency
    # Lower frequency noise = larger grain structures
    base_freq = (0.8 / (1.0 + (iso / 200.0))) / size_scale

    # 3 octaves with decreasing amplitude
    octave_configs = [
        (base_freq, 0.50),          # Broad grain structure
        (base_freq * 2.0, 0.30),    # Medium detail
        (base_freq * 4.0, 0.20),    # Fine detail
    ]

    grain = np.zeros((height, width), dtype=np.float32)

    for freq, amplitude in octave_configs:
        octave = np.zeros((height, width), dtype=np.float32)
        for y in range(height):
            for x in range(width):
                octave[y, x] = noise_gen.noise2(x * freq, y * freq)
        grain += octave * amplitude

    # Normalize to roughly -1..1
    std = grain.std()
    if std > 0:
        grain = grain / std

    return grain


def _generate_fallback_grain(height, width, iso, seed):
    """Generate grain using numpy random + gaussian blur. Fast fallback."""
    rng = np.random.RandomState(seed)

    # Scale blur sigma relative to image size so grain looks consistent
    # across resolutions. Reference: 1024px on the long edge.
    ref_size = 1024.0
    size_scale = max(height, width) / ref_size

    # ISO affects blur sigma: higher ISO = less blur = larger apparent grain
    # (less blur means more high-frequency noise survives, looking coarser)
    base_sigma = max(0.4, 1.5 * (100.0 / max(iso, 50))) * size_scale

    # 3 octaves
    grain = np.zeros((height, width), dtype=np.float32)
    for i, (amp, sigma_mult) in enumerate([(0.50, 1.0), (0.30, 0.5), (0.20, 0.25)]):
        noise = rng.randn(height, width).astype(np.float32)
        sigma = base_sigma * sigma_mult
        if sigma > 0.3:
            noise = gaussian_filter(noise, sigma=sigma)
        grain += noise * amp

    # Normalize
    std = grain.std()
    if std > 0:
        grain = grain / std

    return grain


def generate_grain(height, width, iso=400, seed=0):
    """
    Generate film grain noise.

    Parameters:
        height, width: image dimensions
        iso: film speed (50-3200). Higher = coarser grain.
        seed: random seed for reproducibility
    """
    # The fallback path (numpy random + scipy gaussian_filter) is fast and
    # produces good organic-looking grain. opensimplex's pure-Python per-pixel
    # loop is too slow for production use, even at reduced resolution.
    # We use the fast path by default and reserve simplex for tiny images only.
    if HAS_OPENSIMPLEX and max(height, width) <= 128:
        return _generate_simplex_grain(height, width, iso, seed)
    else:
        return _generate_fallback_grain(height, width, iso, seed)


def luminance_grain_mask(luminance):
    """
    Bell curve mask: grain peaks in midtones, fades in shadows and highlights.
    Matches real film behavior — developed silver is smoother in highlights,
    fewer activated crystals in deep shadows.

    luminance: (H, W) float32 array, 0-1 range
    Returns: (H, W) float32 mask, 0-1 range
    """
    return (4.0 * luminance * (1.0 - luminance)).astype(np.float32)


def apply_grain(img, grain, luminance, strength=0.5, color_amount=0.3):
    """
    Apply grain to image with luminance-dependent modulation.

    Parameters:
        img: (H, W, 3) float32, 0-1 range
        grain: (H, W) float32, normalized noise
        luminance: (H, W) float32, image luminance
        strength: overall grain intensity (0-1)
        color_amount: how much per-channel variation (0 = pure luminance grain, 1 = full color grain)
    """
    mask = luminance_grain_mask(luminance)

    # Scale grain by strength and luminance mask
    # Strength 1.0 maps to ~0.08 additive noise at midtones (visible but not overwhelming)
    intensity = strength * 0.08
    modulated = grain * mask * intensity

    if color_amount <= 0.01:
        # Pure luminance grain — same value added to all channels
        result = img + modulated[..., np.newaxis]
    else:
        # Per-channel grain variation to simulate emulsion layers
        # Blue-sensitive layer has coarser grain in real film
        result = img.copy()
        r_variation = 1.0 + (np.random.RandomState(42).randn() * 0.1 * color_amount)
        g_variation = 1.0 + (np.random.RandomState(43).randn() * 0.1 * color_amount)
        b_variation = 1.0 + (0.2 * color_amount)  # Blue channel always gets more grain

        result[..., 0] += modulated * r_variation
        result[..., 1] += modulated * g_variation
        result[..., 2] += modulated * b_variation

    return np.clip(result, 0.0, 1.0).astype(np.float32)

"""
Color grading utilities for ComfyUI-Darkroom Wave 3.
Shared math for tone curves, LGG, zone masks, hue selection, and saturation ops.
All functions operate on numpy float32 arrays in 0-1 range.
"""

import numpy as np
from scipy.interpolate import PchipInterpolator


def cubic_spline_curve(x, control_points):
    """
    Evaluate a monotonic cubic spline at the given values.

    Parameters:
        x: numpy array (0-1 range)
        control_points: list of (input, output) tuples, sorted by input.
                        Minimum 2 points required.
    Returns:
        Mapped values clamped to 0-1.
    """
    pts = sorted(control_points, key=lambda p: p[0])
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)

    # PchipInterpolator: monotonic cubic, no overshoot
    interp = PchipInterpolator(xs, ys, extrapolate=True)
    result = interp(x.astype(np.float64))
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def lgg_zone_masks(luminance):
    """
    Hard-boundary zone masks for Lift/Gamma/Gain primary correction.

    Returns (lift_mask, gamma_mask, gain_mask):
        - lift: strongest in shadows, fades toward midtones
        - gamma: bell curve peaking at midtones
        - gain: strongest in highlights, fades toward midtones

    Each mask is (H, W) float32 in 0-1 range.
    """
    lum = np.clip(luminance, 0.0, 1.0)

    # Lift: inverted power curve — strongest at black, zero at white
    lift_mask = np.power(1.0 - lum, 1.5).astype(np.float32)

    # Gain: power curve — strongest at white, zero at black
    gain_mask = np.power(lum, 1.5).astype(np.float32)

    # Gamma: bell curve at midtones (complement of lift+gain)
    gamma_mask = (1.0 - np.abs(2.0 * lum - 1.0) ** 1.5).astype(np.float32)

    return lift_mask, gamma_mask, gain_mask


def log_zone_masks(luminance, shadow_range=0.15, highlight_range=0.85):
    """
    Soft Gaussian zone masks in log2-encoded luminance space.
    Wider, softer transitions than LGG — matches DaVinci Resolve Log mode.

    Parameters:
        luminance: (H, W) float32, 0-1 range
        shadow_range: upper boundary of shadow zone (0-1 in linear)
        highlight_range: lower boundary of highlight zone (0-1 in linear)

    Returns (shadow_mask, midtone_mask, highlight_mask):
        Each (H, W) float32 in 0-1 range.
    """
    # Convert to log2 space (roughly maps to stops of exposure)
    eps = 1e-6
    log_lum = np.log2(np.clip(luminance, eps, 1.0))
    # Normalize: map [-10 stops, 0 stops] to [0, 1]
    log_min = np.log2(eps)
    log_norm = (log_lum - log_min) / (0.0 - log_min)
    log_norm = np.clip(log_norm, 0.0, 1.0)

    # Zone centers and widths in normalized log space
    log_shadow = (np.log2(max(shadow_range, eps)) - log_min) / (0.0 - log_min)
    log_highlight = (np.log2(max(highlight_range, eps)) - log_min) / (0.0 - log_min)
    log_mid = (log_shadow + log_highlight) * 0.5

    # Soft Gaussian masks with generous overlap
    shadow_sigma = max(log_shadow * 0.6, 0.05)
    highlight_sigma = max((1.0 - log_highlight) * 0.6, 0.05)
    mid_sigma = (log_highlight - log_shadow) * 0.4

    shadow_mask = np.exp(-0.5 * ((log_norm - log_shadow * 0.5) / shadow_sigma) ** 2)
    midtone_mask = np.exp(-0.5 * ((log_norm - log_mid) / mid_sigma) ** 2)
    highlight_mask = np.exp(-0.5 * ((log_norm - (1.0 + log_highlight) * 0.5) / highlight_sigma) ** 2)

    return (shadow_mask.astype(np.float32),
            midtone_mask.astype(np.float32),
            highlight_mask.astype(np.float32))


def hue_range_mask(hue, center, width=45.0, softness=0.5):
    """
    Raised-cosine feathered hue selection with wraparound at 0/360.

    Parameters:
        hue: (H, W) float32, [0, 360)
        center: center hue in degrees
        width: half-width of the selection in degrees (before softness)
        softness: 0.0 = hard edge, 1.0 = maximum feathering

    Returns: (H, W) float32 mask, 0-1 range.
    """
    # Angular distance with wraparound
    diff = np.abs(hue - center)
    diff = np.minimum(diff, 360.0 - diff)

    # Effective width: softness widens the falloff
    effective_width = width * (0.5 + softness * 0.5)

    # Raised cosine falloff
    weight = np.clip((1.0 + np.cos(np.pi * diff / max(effective_width, 1.0))) * 0.5, 0.0, 1.0)
    weight[diff > effective_width] = 0.0

    return weight.astype(np.float32)


def apply_lgg(img, lift_rgb, gamma_rgb, gain_rgb, offset_rgb):
    """
    Apply Lift/Gamma/Gain/Offset per channel.

    DaVinci Resolve primary correction formula:
        output = gain * (lift * (1 - input) + input) ^ (1/gamma) + offset

    Parameters:
        img: (H, W, 3) float32, linear light
        lift_rgb: (3,) array — shadow color offset per channel
        gamma_rgb: (3,) array — midtone power per channel (>1 = brighter mids)
        gain_rgb: (3,) array — highlight multiplier per channel
        offset_rgb: (3,) array — global offset per channel

    Returns: (H, W, 3) float32
    """
    result = np.empty_like(img)
    for c in range(3):
        x = img[..., c]
        l = lift_rgb[c]
        g = max(gamma_rgb[c], 0.01)  # prevent division by zero
        gn = gain_rgb[c]
        o = offset_rgb[c]

        # Resolve LGG formula
        lifted = l * (1.0 - x) + x
        lifted = np.clip(lifted, 0.0, None)
        powered = np.power(lifted, 1.0 / g)
        result[..., c] = gn * powered + o

    return np.clip(result, 0.0, 1.0).astype(np.float32)


def apply_color_tint_to_zone(img, zone_mask, hue_angle, intensity):
    """
    Apply a color tint to a luminance zone.

    Converts hue angle to RGB tint vector, applies additively weighted by
    zone_mask and intensity.

    Parameters:
        img: (H, W, 3) float32
        zone_mask: (H, W) float32, 0-1
        hue_angle: float, 0-360 degrees
        intensity: float, 0-100 scale

    Returns: (H, W, 3) float32
    """
    if intensity < 0.5:
        return img

    # Convert hue angle to unit RGB vector
    h_rad = np.radians(hue_angle)
    # Project onto RGB using 120-degree separation
    tint_r = np.cos(h_rad) * 0.5 + 0.5
    tint_g = np.cos(h_rad - 2.094395) * 0.5 + 0.5  # -120 deg
    tint_b = np.cos(h_rad + 2.094395) * 0.5 + 0.5  # +120 deg

    # Normalize so the tint is purely chromatic (sum = 1)
    tint = np.array([tint_r, tint_g, tint_b], dtype=np.float32)
    tint = tint / (tint.sum() + 1e-10)

    # Scale by intensity
    strength = intensity / 100.0 * 0.3  # 0.3 max additive to prevent blowout
    tint_scaled = tint * strength

    # Apply additively weighted by zone mask
    result = img + zone_mask[..., np.newaxis] * tint_scaled[np.newaxis, np.newaxis, :]

    return np.clip(result, 0.0, 1.0).astype(np.float32)


def sat_from_rgb(img):
    """
    Fast saturation extraction: (max - min) / max.
    Returns (H, W) float32 in 0-1 range.
    """
    cmax = np.max(img, axis=-1)
    cmin = np.min(img, axis=-1)
    sat = np.where(cmax > 1e-7, (cmax - cmin) / (cmax + 1e-10), 0.0)
    return sat.astype(np.float32)


def sat_range_mask(saturation, center, width=0.15):
    """
    Gaussian bell-curve mask in saturation space.

    Parameters:
        saturation: (H, W) float32, 0-1
        center: center of the range (0-1)
        width: sigma of the Gaussian

    Returns: (H, W) float32 mask, 0-1 range.
    """
    return np.exp(-0.5 * ((saturation - center) / (width + 1e-10)) ** 2).astype(np.float32)

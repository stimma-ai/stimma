"""
Color math utilities for ComfyUI-Darkroom.
All functions operate on numpy float32 arrays in 0-1 range.
"""

import numpy as np


def srgb_to_linear(img):
    """Remove sRGB gamma — convert display-referred to scene-linear."""
    img = np.clip(img, 0.0, 1.0).astype(np.float32)
    return np.where(
        img <= 0.04045,
        img / 12.92,
        ((img + 0.055) / 1.055) ** 2.4
    ).astype(np.float32)


def linear_to_srgb(img):
    """Apply sRGB gamma — convert scene-linear to display-referred.

    Routes through torch on CUDA when available; the numpy path spends ~4 s
    on a 51 MP image because np.power runs serial on CPU. GPU path is ~20x
    faster. Falls back to numpy when torch/CUDA isn't usable so this stays
    safe to call from any test harness.
    """
    try:
        import torch
        if torch.cuda.is_available():
            t = torch.from_numpy(np.ascontiguousarray(img, dtype=np.float32)).cuda()
            t = torch.clamp(t, 0.0, 1.0)
            lo = t * 12.92
            hi = 1.055 * torch.pow(t, 1.0 / 2.4) - 0.055
            out = torch.where(t <= 0.0031308, lo, hi)
            return out.cpu().numpy().astype(np.float32)
    except Exception:
        pass
    img = np.clip(img, 0.0, 1.0).astype(np.float32)
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(img, 1.0 / 2.4) - 0.055
    ).astype(np.float32)


def characteristic_curve(x, toe_power, shoulder_power, slope, pivot_x=0.18, pivot_y=0.18):
    """
    Attempt to model an H&D film characteristic curve as a parametric sigmoid.

    The curve is piecewise around the pivot point:
    - Below pivot: toe compression (shadow rolloff)
    - Above pivot: shoulder compression (highlight rolloff)

    Parameters:
        x: input values (numpy array, 0-1 range, linear light)
        toe_power: >1 compresses shadows more, <1 expands them
        shoulder_power: >1 gives softer highlight rolloff
        slope: midtone contrast (1.0 = neutral)
        pivot_x: input value of the pivot (typically 0.18 = 18% grey)
        pivot_y: output value at the pivot
    """
    x = np.clip(x, 0.0, 1.0).astype(np.float32)
    result = np.zeros_like(x)

    # Toe region (below pivot)
    mask_toe = x <= pivot_x
    if np.any(mask_toe):
        # Normalized position within toe region [0, 1]
        t = x[mask_toe] / (pivot_x + 1e-10)
        # Power curve for toe shape, scaled by slope
        curved = np.power(t, toe_power)
        result[mask_toe] = pivot_y * curved * slope

    # Shoulder region (above pivot)
    mask_shoulder = x > pivot_x
    if np.any(mask_shoulder):
        # Normalized position within shoulder region [0, 1]
        t = (x[mask_shoulder] - pivot_x) / (1.0 - pivot_x + 1e-10)
        # Inverted power curve for shoulder compression
        curved = 1.0 - np.power(1.0 - t, shoulder_power)
        result[mask_shoulder] = pivot_y * slope + (1.0 - pivot_y * slope) * curved

    return np.clip(result, 0.0, 1.0).astype(np.float32)


def apply_per_channel_curves(img, r_params, g_params, b_params):
    """
    Apply independent characteristic curves to R, G, B channels.
    Each params tuple: (toe_power, shoulder_power, slope, pivot_x, pivot_y)
    """
    result = np.empty_like(img)
    result[..., 0] = characteristic_curve(img[..., 0], *r_params)
    result[..., 1] = characteristic_curve(img[..., 1], *g_params)
    result[..., 2] = characteristic_curve(img[..., 2], *b_params)
    return result


def luminance_rec709(img):
    """Rec.709 luminance from RGB image. Returns (H, W) array."""
    return (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]).astype(np.float32)


def adjust_saturation(img, factor):
    """
    Luminance-preserving saturation adjustment.
    factor: 1.0 = unchanged, >1 = more saturated, <1 = desaturated
    """
    if abs(factor - 1.0) < 0.001:
        return img
    lum = luminance_rec709(img)[..., np.newaxis]
    result = lum + factor * (img - lum)
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def split_tone(img, shadow_tint, highlight_tint, balance=0.5):
    """
    Add color tints to shadows and highlights independently.

    Parameters:
        img: (H, W, 3) float32 array
        shadow_tint: (R, G, B) tuple, additive tint for shadows
        highlight_tint: (R, G, B) tuple, additive tint for highlights
        balance: 0.0 = all shadow, 1.0 = all highlight, 0.5 = neutral split
    """
    lum = luminance_rec709(img)

    # Smooth masks based on luminance
    shadow_weight = np.clip(1.0 - lum / (balance + 1e-10), 0.0, 1.0)
    highlight_weight = np.clip((lum - balance) / (1.0 - balance + 1e-10), 0.0, 1.0)

    shadow_tint = np.array(shadow_tint, dtype=np.float32)
    highlight_tint = np.array(highlight_tint, dtype=np.float32)

    result = img.copy()
    result += shadow_weight[..., np.newaxis] * shadow_tint[np.newaxis, np.newaxis, :]
    result += highlight_weight[..., np.newaxis] * highlight_tint[np.newaxis, np.newaxis, :]

    return np.clip(result, 0.0, 1.0).astype(np.float32)


def blend(original, processed, strength):
    """Linear interpolation between original and processed image."""
    if strength >= 1.0:
        return processed
    if strength <= 0.0:
        return original
    return (original * (1.0 - strength) + processed * strength).astype(np.float32)

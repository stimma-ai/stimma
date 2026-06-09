"""Server-side implementations of the built-in chain filters.

NumPy/PIL ports of the editor's Canvas pixel math (packages/image-editor/
src/utils/colorMatrix.ts and utils/effects.ts). The chain auto-runs server-
side after generation, so the editor's client-side filters are re-implemented
here on the shared definitions in filter_defs.py — golden tests assert the
ported color math visually matches the editor.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List

import numpy as np
from PIL import Image, ImageFilter

from .filter_defs import FILTER_MATRICES, get_filter_def


# --- Color matrix math (port of colorMatrix.ts) ------------------------------

def identity_matrix() -> List[float]:
    return [
        1, 0, 0, 0, 0,
        0, 1, 0, 0, 0,
        0, 0, 1, 0, 0,
        0, 0, 0, 1, 0,
    ]


def multiply_color_matrices(a: List[float], b: List[float]) -> List[float]:
    """Compose two 4x5 color matrices (implicit 5th row [0,0,0,0,1])."""
    result = [0.0] * 20
    for row in range(4):
        for col in range(5):
            total = 0.0
            for i in range(5):
                a_val = a[row * 5 + i] if i < 4 else 0.0
                if i < 4:
                    b_val = b[i * 5 + col]
                else:
                    b_val = 1.0 if col == 4 else 0.0
                total += a_val * b_val
            result[row * 5 + col] = total
    for row in range(4):
        result[row * 5 + 4] += a[row * 5 + 4]
    return result


def brightness_matrix(value: float) -> List[float]:
    b = (value / 100.0) * 255.0
    return [
        1, 0, 0, 0, b,
        0, 1, 0, 0, b,
        0, 0, 1, 0, b,
        0, 0, 0, 1, 0,
    ]


def contrast_matrix(value: float) -> List[float]:
    c = 1.0 + value / 100.0
    o = 128.0 * (1.0 - c)
    return [
        c, 0, 0, 0, o,
        0, c, 0, 0, o,
        0, 0, c, 0, o,
        0, 0, 0, 1, 0,
    ]


def saturation_matrix(value: float) -> List[float]:
    s = 1.0 + value / 100.0
    lr, lg, lb = 0.2126, 0.7152, 0.0722  # ITU-R BT.709
    sr = (1.0 - s) * lr
    sg = (1.0 - s) * lg
    sb = (1.0 - s) * lb
    return [
        sr + s, sg, sb, 0, 0,
        sr, sg + s, sb, 0, 0,
        sr, sg, sb + s, 0, 0,
        0, 0, 0, 1, 0,
    ]


def exposure_matrix(value: float) -> List[float]:
    e = math.pow(2.0, value / 100.0)
    return [
        e, 0, 0, 0, 0,
        0, e, 0, 0, 0,
        0, 0, e, 0, 0,
        0, 0, 0, 1, 0,
    ]


def temperature_matrix(value: float) -> List[float]:
    t = value / 100.0
    r_shift = t * 30.0 if t > 0 else 0.0
    b_shift = -t * 30.0 if t < 0 else 0.0
    return [
        1, 0, 0, 0, r_shift,
        0, 1, 0, 0, 0,
        0, 0, 1, 0, b_shift,
        0, 0, 0, 1, 0,
    ]


def gamma_matrix(value: float) -> List[float]:
    g = 1.0 / value
    o = 128.0 * (1.0 - g)
    return [
        g, 0, 0, 0, o,
        0, g, 0, 0, o,
        0, 0, g, 0, o,
        0, 0, 0, 1, 0,
    ]


def combine_adjustments(adjustments: Dict[str, float]) -> List[float]:
    """Port of combineAdjustments — same composition order as the editor."""
    matrix = identity_matrix()
    b = adjustments.get("brightness")
    if b:
        matrix = multiply_color_matrices(matrix, brightness_matrix(b))
    c = adjustments.get("contrast")
    if c:
        matrix = multiply_color_matrices(matrix, contrast_matrix(c))
    s = adjustments.get("saturation")
    if s:
        matrix = multiply_color_matrices(matrix, saturation_matrix(s))
    e = adjustments.get("exposure")
    if e:
        matrix = multiply_color_matrices(matrix, exposure_matrix(e))
    t = adjustments.get("temperature")
    if t:
        matrix = multiply_color_matrices(matrix, temperature_matrix(t))
    g = adjustments.get("gamma")
    if g is not None and g != 1:
        matrix = multiply_color_matrices(matrix, gamma_matrix(g))
    return matrix


def apply_color_matrix(rgba: np.ndarray, matrix: List[float]) -> np.ndarray:
    """Apply a 4x5 color matrix to an HxWx4 uint8 array (port of applyColorMatrix)."""
    m = np.asarray(matrix, dtype=np.float32).reshape(4, 5)
    src = rgba.astype(np.float32)
    out = src @ m[:, :4].T
    out += m[:, 4]
    return np.clip(out, 0, 255).astype(np.uint8)


# --- Spatial effects (port of effects.ts) -------------------------------------

def _gaussian(img: Image.Image, radius_px: float) -> Image.Image:
    # CSS blur(Npx) is a Gaussian with standard deviation N/2; PIL's
    # GaussianBlur radius is the standard deviation.
    return img.filter(ImageFilter.GaussianBlur(radius=radius_px / 2.0))


def _unsharp(rgba: np.ndarray, blurred: np.ndarray, strength: float) -> np.ndarray:
    src = rgba.astype(np.float32)
    blur = blurred.astype(np.float32)
    out = src.copy()
    out[..., :3] = src[..., :3] + (src[..., :3] - blur[..., :3]) * strength
    return np.clip(out, 0, 255).astype(np.uint8)


def _to_rgba(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGBA"), dtype=np.uint8)


def _from_rgba(arr: np.ndarray, had_alpha: bool) -> Image.Image:
    img = Image.fromarray(arr, mode="RGBA")
    return img if had_alpha else img.convert("RGB")


# --- Filter handlers -----------------------------------------------------------

def _f_filter(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    filter_id = str(settings.get("filter", "chrome"))
    matrix = FILTER_MATRICES.get(filter_id)
    if matrix is None:
        raise ValueError(f"Unknown color filter: {filter_id}")
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    return _from_rgba(apply_color_matrix(_to_rgba(img), matrix), had_alpha)


def _f_levels(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    matrix = combine_adjustments({
        "brightness": float(settings.get("brightness", 0) or 0),
        "contrast": float(settings.get("contrast", 0) or 0),
        "saturation": float(settings.get("saturation", 0) or 0),
        "exposure": float(settings.get("exposure", 0) or 0),
        "temperature": float(settings.get("temperature", 0) or 0),
        "gamma": float(settings.get("gamma", 1) or 1),
    })
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    return _from_rgba(apply_color_matrix(_to_rgba(img), matrix), had_alpha)


def _f_sharpen(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 30) or 0)
    if amount <= 0:
        return img
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    rgba = _to_rgba(img)
    blurred = _to_rgba(_gaussian(img, 1.0))
    return _from_rgba(_unsharp(rgba, blurred, amount / 50.0), had_alpha)


def _f_blur(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 20) or 0)
    if amount <= 0:
        return img
    return _gaussian(img, amount)


def _f_clarity(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 30) or 0)
    if amount <= 0:
        return img
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    rgba = _to_rgba(img)
    blurred = _to_rgba(_gaussian(img, 20.0))
    return _from_rgba(_unsharp(rgba, blurred, amount / 100.0), had_alpha)


def _f_motion_blur(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 30) or 0)
    if amount <= 0:
        return img
    angle = float(settings.get("angle", 0) or 0)
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    src = _to_rgba(img).astype(np.float32)
    h, w = src.shape[:2]

    radians = math.radians(angle)
    dx, dy = math.cos(radians), math.sin(radians)
    samples = max(3, int(amount // 3))
    max_offset = amount / 2.0

    acc = np.zeros_like(src)
    for i in range(samples):
        t = (i / (samples - 1)) - 0.5
        ox = int(round(dx * t * max_offset * 2))
        oy = int(round(dy * t * max_offset * 2))
        xs = np.clip(np.arange(w) - ox, 0, w - 1)
        ys = np.clip(np.arange(h) - oy, 0, h - 1)
        acc += src[ys][:, xs]
    out = np.clip(acc / samples, 0, 255).astype(np.uint8)
    return _from_rgba(out, had_alpha)


def _f_glow(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 30) or 0)
    if amount <= 0:
        return img
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    base = _to_rgba(img).astype(np.float32)
    # Bright pass: blur(amount*2 px) then brightness(1.5), like the editor's
    # CSS filter chain.
    glow = _to_rgba(_gaussian(img, amount * 2.0)).astype(np.float32)
    glow[..., :3] = np.clip(glow[..., :3] * 1.5, 0, 255)
    # Screen blend at alpha amount/100.
    a = amount / 100.0
    screen = 255.0 - (255.0 - base[..., :3]) * (255.0 - glow[..., :3]) / 255.0
    out = base.copy()
    out[..., :3] = base[..., :3] * (1.0 - a) + screen * a
    return _from_rgba(np.clip(out, 0, 255).astype(np.uint8), had_alpha)


def _f_noise(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 20) or 0)
    if amount <= 0:
        return img
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    rgba = _to_rgba(img).astype(np.float32)
    intensity = amount * 2.55
    rng = np.random.default_rng()
    # Same noise value across R/G/B per pixel (monochrome grain, like the editor)
    noise = (rng.random(rgba.shape[:2], dtype=np.float32) - 0.5) * intensity
    rgba[..., :3] += noise[..., None]
    return _from_rgba(np.clip(rgba, 0, 255).astype(np.uint8), had_alpha)


def _f_pixelate(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 20) or 0)
    if amount <= 0:
        return img
    pixel_size = max(2, int(amount // 2))
    w, h = img.size
    small = img.resize(
        (max(1, w // pixel_size), max(1, h // pixel_size)), Image.NEAREST
    )
    return small.resize((w, h), Image.NEAREST)


def _f_chromatic_aberration(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 30) or 0)
    offset = int(amount // 5)
    if offset <= 0:
        return img
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    rgba = _to_rgba(img)
    w = rgba.shape[1]
    out = rgba.copy()
    xs_r = np.clip(np.arange(w) - offset, 0, w - 1)  # red samples from the left
    xs_b = np.clip(np.arange(w) + offset, 0, w - 1)  # blue samples from the right
    out[..., 0] = rgba[:, xs_r, 0]
    out[..., 2] = rgba[:, xs_b, 2]
    return _from_rgba(out, had_alpha)


def _f_vignette(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    amount = float(settings.get("amount", 40) or 0)
    if amount <= 0:
        return img
    had_alpha = img.mode in ("RGBA", "LA", "PA")
    rgba = _to_rgba(img).astype(np.float32)
    h, w = rgba.shape[:2]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / math.sqrt(cx * cx + cy * cy)
    # The editor's radial gradient: transparent to 0.5 of the radius, then a
    # linear ramp to `amount/100` black at the corners.
    alpha = np.clip((dist - 0.5) / 0.5, 0.0, 1.0) * (amount / 100.0)
    rgba[..., :3] *= (1.0 - alpha)[..., None]
    return _from_rgba(np.clip(rgba, 0, 255).astype(np.uint8), had_alpha)


def _f_crop(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    aspect = str(settings.get("aspect", "1:1"))
    try:
        num, den = aspect.split(":")
        target = float(num) / float(den)
    except (ValueError, ZeroDivisionError) as e:
        raise ValueError(f"Invalid aspect ratio: {aspect}") from e
    w, h = img.size
    current = w / h
    if abs(current - target) < 1e-6:
        return img
    if current > target:
        new_w = int(round(h * target))
        x0 = (w - new_w) // 2
        return img.crop((x0, 0, x0 + new_w, h))
    new_h = int(round(w / target))
    y0 = (h - new_h) // 2
    return img.crop((0, y0, w, y0 + new_h))


def _f_resize(img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    long_edge = int(settings.get("long_edge", 2048))
    w, h = img.size
    current_long = max(w, h)
    if current_long == long_edge:
        return img
    scale = long_edge / current_long
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return img.resize(new_size, Image.LANCZOS)


FILTER_HANDLERS: Dict[str, Callable[[Image.Image, Dict[str, Any]], Image.Image]] = {
    "filter": _f_filter,
    "levels": _f_levels,
    "blur": _f_blur,
    "sharpen": _f_sharpen,
    "clarity": _f_clarity,
    "motion-blur": _f_motion_blur,
    "glow": _f_glow,
    "noise": _f_noise,
    "pixelate": _f_pixelate,
    "chromatic-aberration": _f_chromatic_aberration,
    "vignette": _f_vignette,
    "crop": _f_crop,
    "resize": _f_resize,
}


def apply_builtin_filter(filter_id: str, img: Image.Image, settings: Dict[str, Any]) -> Image.Image:
    """Apply one built-in filter to a PIL image. Settings overlay the def defaults."""
    handler = FILTER_HANDLERS.get(filter_id)
    if handler is None:
        raise ValueError(f"Unknown built-in filter: {filter_id}")
    d = get_filter_def(filter_id)
    merged = {p["name"]: p["default"] for p in (d["params"] if d else [])}
    merged.update(settings or {})
    return handler(img, merged)

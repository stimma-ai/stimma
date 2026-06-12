"""Image adjustment and filter pipeline for the Stimma SDK.

Pure functions — no SDK dependencies. Uses numpy for vectorized matrix operations
and PIL for spatial effects. Ports the image editor's TypeScript implementation
to Python.

Color matrices are 4x5 (20 elements), applied as:
  [R', G', B', A'] = matrix x [R, G, B, A, 1]
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------------------
# Filter preset matrices (ported from constants.ts)
# ---------------------------------------------------------------------------

FILTER_MATRICES: dict[str, list[float]] = {
    "chrome": [
        1.2, 0.1, 0.1, 0, -20,
        0.1, 1.1, 0.1, 0, -10,
        0.1, 0.1, 1.3, 0, -20,
        0, 0, 0, 1, 0,
    ],
    "fade": [
        1, 0, 0, 0, 30,
        0, 1, 0, 0, 30,
        0, 0, 1, 0, 30,
        0, 0, 0, 0.9, 0,
    ],
    "cold": [
        0.9, 0, 0.1, 0, 0,
        0, 0.95, 0.1, 0, 0,
        0.1, 0.1, 1.2, 0, 10,
        0, 0, 0, 1, 0,
    ],
    "warm": [
        1.2, 0.1, 0, 0, 10,
        0.1, 1.05, 0, 0, 5,
        0, 0, 0.9, 0, -10,
        0, 0, 0, 1, 0,
    ],
    "pastel": [
        1.1, 0.1, 0.1, 0, 20,
        0.1, 1.1, 0.1, 0, 20,
        0.1, 0.1, 1.1, 0, 20,
        0, 0, 0, 1, 0,
    ],
    "mono": [
        0.33, 0.33, 0.33, 0, 0,
        0.33, 0.33, 0.33, 0, 0,
        0.33, 0.33, 0.33, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "noir": [
        0.4, 0.4, 0.2, 0, -20,
        0.3, 0.4, 0.2, 0, -10,
        0.2, 0.3, 0.4, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "stark": [
        0.5, 0.5, 0.5, 0, -50,
        0.5, 0.5, 0.5, 0, -50,
        0.5, 0.5, 0.5, 0, -50,
        0, 0, 0, 1, 0,
    ],
    "sepia": [
        0.393, 0.769, 0.189, 0, 0,
        0.349, 0.686, 0.168, 0, 0,
        0.272, 0.534, 0.131, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "vintage": [
        0.9, 0.2, 0.1, 0, 20,
        0.1, 0.8, 0.2, 0, 15,
        0.1, 0.1, 0.7, 0, 30,
        0, 0, 0, 1, 0,
    ],
    "vivid": [
        1.3, -0.1, -0.1, 0, 0,
        -0.1, 1.3, -0.1, 0, 0,
        -0.1, -0.1, 1.3, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "dramatic": [
        1.3, -0.1, -0.1, 0, -20,
        -0.1, 1.3, -0.1, 0, -20,
        -0.1, -0.1, 1.3, 0, -20,
        0, 0, 0, 1, 0,
    ],
    "portra_400": [
        1.05, 0.08, 0.02, 0, 8,
        0.02, 1.0, 0.05, 0, 6,
        -0.02, 0.05, 0.92, 0, 15,
        0, 0, 0, 1, 0,
    ],
    "velvia": [
        1.2, -0.05, -0.05, 0, -15,
        -0.05, 1.15, -0.05, 0, -10,
        -0.05, 0.05, 1.3, 0, -20,
        0, 0, 0, 1, 0,
    ],
    "kodachrome": [
        1.15, 0.1, -0.05, 0, 5,
        0.05, 1.05, 0.0, 0, 0,
        -0.05, 0.1, 1.1, 0, 10,
        0, 0, 0, 1, 0,
    ],
    "cinestill_800t": [
        0.95, 0.05, 0.1, 0, 10,
        0.0, 1.0, 0.1, 0, 5,
        0.1, 0.1, 1.15, 0, 0,
        0, 0, 0, 1, 0,
    ],
    "polaroid_600": [
        1.0, 0.05, 0.0, 0, 25,
        0.02, 0.98, 0.05, 0, 20,
        0.0, 0.08, 0.9, 0, 30,
        0, 0, 0, 0.95, 0,
    ],
    "tri_x_400": [
        0.35, 0.45, 0.2, 0, 0,
        0.35, 0.45, 0.2, 0, 0,
        0.35, 0.45, 0.2, 0, 0,
        0, 0, 0, 1, 0,
    ],
}

FILTER_NAMES: list[str] = list(FILTER_MATRICES.keys())

# ---------------------------------------------------------------------------
# Color matrix builders (ported from colorMatrix.ts)
# ---------------------------------------------------------------------------

_IDENTITY = [
    1, 0, 0, 0, 0,
    0, 1, 0, 0, 0,
    0, 0, 1, 0, 0,
    0, 0, 0, 1, 0,
]


def _multiply_matrices(a: list[float], b: list[float]) -> list[float]:
    """Compose two 4x5 color matrices (implicit 5th row [0,0,0,0,1])."""
    result = [0.0] * 20
    for row in range(4):
        for col in range(5):
            s = 0.0
            for i in range(4):
                s += a[row * 5 + i] * b[i * 5 + col]
            result[row * 5 + col] = s
        # Add the offset column from a
        result[row * 5 + 4] += a[row * 5 + 4]
    return result


def _brightness_matrix(value: float) -> list[float]:
    """Brightness: -100 to +100 -> offset -255 to +255."""
    b = (value / 100) * 255
    return [
        1, 0, 0, 0, b,
        0, 1, 0, 0, b,
        0, 0, 1, 0, b,
        0, 0, 0, 1, 0,
    ]


def _contrast_matrix(value: float) -> list[float]:
    """Contrast: -100 to +100 -> scale 0 to 2."""
    c = 1 + value / 100
    o = 128 * (1 - c)
    return [
        c, 0, 0, 0, o,
        0, c, 0, 0, o,
        0, 0, c, 0, o,
        0, 0, 0, 1, 0,
    ]


def _saturation_matrix(value: float) -> list[float]:
    """Saturation: -100 to +100 -> scale 0 to 2."""
    s = 1 + value / 100
    lr, lg, lb = 0.2126, 0.7152, 0.0722
    sr = (1 - s) * lr
    sg = (1 - s) * lg
    sb = (1 - s) * lb
    return [
        sr + s, sg, sb, 0, 0,
        sr, sg + s, sb, 0, 0,
        sr, sg, sb + s, 0, 0,
        0, 0, 0, 1, 0,
    ]


def _exposure_matrix(value: float) -> list[float]:
    """Exposure: -100 to +100 -> multiplier 0.5 to 2."""
    e = 2 ** (value / 100)
    return [
        e, 0, 0, 0, 0,
        0, e, 0, 0, 0,
        0, 0, e, 0, 0,
        0, 0, 0, 1, 0,
    ]


def _temperature_matrix(value: float) -> list[float]:
    """Temperature: -100 (cool) to +100 (warm)."""
    t = value / 100
    r_shift = t * 30 if t > 0 else 0
    b_shift = -t * 30 if t < 0 else 0
    return [
        1, 0, 0, 0, r_shift,
        0, 1, 0, 0, 0,
        0, 0, 1, 0, b_shift,
        0, 0, 0, 1, 0,
    ]


def _combine_adjustments(**kwargs: float) -> list[float] | None:
    """Compose all non-default level adjustments into one matrix."""
    matrix = list(_IDENTITY)
    changed = False

    builders = [
        ("brightness", 0, _brightness_matrix),
        ("contrast", 0, _contrast_matrix),
        ("saturation", 0, _saturation_matrix),
        ("exposure", 0, _exposure_matrix),
        ("temperature", 0, _temperature_matrix),
    ]

    for name, default, builder in builders:
        val = kwargs.get(name, default)
        if val != default:
            matrix = _multiply_matrices(matrix, builder(val))
            changed = True

    return matrix if changed else None


def _apply_color_matrix(img: Image.Image, matrix: list[float]) -> Image.Image:
    """Apply a 4x5 color matrix to a PIL Image using numpy vectorized ops."""
    had_alpha = img.mode == "RGBA"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if had_alpha else "RGB")

    arr = np.array(img, dtype=np.float32)
    h, w = arr.shape[:2]
    channels = arr.shape[2]

    # Build pixel matrix: (N, 5) with ones column
    pixels = arr.reshape(-1, channels)
    if channels == 3:
        ones = np.ones((pixels.shape[0], 1), dtype=np.float32)
        zeros = np.zeros((pixels.shape[0], 1), dtype=np.float32)
        pixels_5 = np.concatenate([pixels, zeros, ones], axis=1)  # R,G,B,0,1
    else:
        ones = np.ones((pixels.shape[0], 1), dtype=np.float32)
        pixels_5 = np.concatenate([pixels, ones], axis=1)  # R,G,B,A,1

    # Matrix is 4x5, we want result = pixels_5 @ matrix.T
    mat = np.array(matrix, dtype=np.float32).reshape(4, 5)
    result = pixels_5 @ mat.T  # (N, 4)

    np.clip(result, 0, 255, out=result)

    if had_alpha:
        out_arr = result.reshape(h, w, 4).astype(np.uint8)
        return Image.fromarray(out_arr, "RGBA")
    else:
        out_arr = result[:, :3].reshape(h, w, 3).astype(np.uint8)
        return Image.fromarray(out_arr, "RGB")


# ---------------------------------------------------------------------------
# Gamma correction (real np.power, not the TS linear approximation)
# ---------------------------------------------------------------------------

def _apply_gamma(img: Image.Image, gamma: float) -> Image.Image:
    """Apply real gamma correction using np.power."""
    had_alpha = img.mode == "RGBA"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if had_alpha else "RGB")

    arr = np.array(img, dtype=np.float32)
    inv_gamma = 1.0 / gamma

    if had_alpha:
        rgb = arr[:, :, :3]
        rgb = np.power(rgb / 255.0, inv_gamma) * 255.0
        arr[:, :, :3] = rgb
    else:
        arr = np.power(arr / 255.0, inv_gamma) * 255.0

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), img.mode)


# ---------------------------------------------------------------------------
# Auto adjustments (ported from FinetuneControls.vue)
# ---------------------------------------------------------------------------

def _analyze_image(img: Image.Image) -> dict[str, Any]:
    """Histogram analysis on downsampled image (256px max)."""
    max_size = 256
    scale = min(1.0, max_size / max(img.width, img.height))
    if scale < 1.0:
        small = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS,
        )
    else:
        small = img

    if small.mode != "RGB":
        small = small.convert("RGB")

    arr = np.array(small, dtype=np.int32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    hist_r = np.bincount(r.ravel(), minlength=256)
    hist_g = np.bincount(g.ravel(), minlength=256)
    hist_b = np.bincount(b.ravel(), minlength=256)

    pixel_count = arr.shape[0] * arr.shape[1]
    total_brightness = float(np.mean((r + g + b) / 3.0))

    threshold = pixel_count * 0.005

    def find_min_max(hist: np.ndarray) -> tuple[int, int]:
        cumsum = np.cumsum(hist)
        min_val = int(np.searchsorted(cumsum, threshold))
        max_val = 255 - int(np.searchsorted(cumsum[::-1], threshold))
        return min_val, max_val

    min_r, max_r = find_min_max(hist_r)
    min_g, max_g = find_min_max(hist_g)
    min_b, max_b = find_min_max(hist_b)

    # Weighted averages per channel
    vals = np.arange(256, dtype=np.float64)
    avg_r = float(np.dot(hist_r, vals) / max(hist_r.sum(), 1))
    avg_b = float(np.dot(hist_b, vals) / max(hist_b.sum(), 1))

    return {
        "avg": total_brightness,
        "min_r": min_r, "max_r": max_r,
        "min_g": min_g, "max_g": max_g,
        "min_b": min_b, "max_b": max_b,
        "avg_r": avg_r, "avg_b": avg_b,
    }


def _auto_levels(img: Image.Image) -> Image.Image:
    """Auto brightness + contrast based on histogram analysis."""
    analysis = _analyze_image(img)
    midpoint = 127.5
    brightness_adj = round((midpoint - analysis["avg"]) / 2.55)
    brightness_adj = max(-50, min(50, brightness_adj))

    avg_min = (analysis["min_r"] + analysis["min_g"] + analysis["min_b"]) / 3
    avg_max = (analysis["max_r"] + analysis["max_g"] + analysis["max_b"]) / 3
    dyn_range = avg_max - avg_min
    contrast_adj = round(((255 - dyn_range) / 255) * 30)
    contrast_adj = max(0, min(50, contrast_adj))

    matrix = list(_IDENTITY)
    if brightness_adj != 0:
        matrix = _multiply_matrices(matrix, _brightness_matrix(brightness_adj))
    if contrast_adj != 0:
        matrix = _multiply_matrices(matrix, _contrast_matrix(contrast_adj))

    return _apply_color_matrix(img, matrix)


def _auto_contrast(img: Image.Image) -> Image.Image:
    """Auto contrast: stretch histogram to full range."""
    analysis = _analyze_image(img)
    dyn_range = max(
        analysis["max_r"] - analysis["min_r"],
        analysis["max_g"] - analysis["min_g"],
        analysis["max_b"] - analysis["min_b"],
    )
    contrast_boost = round(((255 - dyn_range) / 255) * 50)
    contrast_boost = min(50, contrast_boost)

    if contrast_boost == 0:
        return img
    return _apply_color_matrix(img, _contrast_matrix(contrast_boost))


def _auto_white_balance(img: Image.Image) -> Image.Image:
    """Auto white balance: adjust temperature based on R/B channel ratio."""
    analysis = _analyze_image(img)
    temp_adj = round((analysis["avg_b"] - analysis["avg_r"]) / 2.55 * 0.5)
    temp_adj = max(-50, min(50, temp_adj))

    if temp_adj == 0:
        return img
    return _apply_color_matrix(img, _temperature_matrix(temp_adj))


# ---------------------------------------------------------------------------
# Spatial effects (ported from effects.ts)
# ---------------------------------------------------------------------------

def _apply_blur(img: Image.Image, amount: float) -> Image.Image:
    """Gaussian blur."""
    return img.filter(ImageFilter.GaussianBlur(radius=amount))


def _apply_sharpen(img: Image.Image, amount: float) -> Image.Image:
    """Unsharp mask sharpening using PIL's built-in UnsharpMask."""
    # Scale amount (0-100) to UnsharpMask parameters
    radius = 1.0 + (amount / 100) * 2.0  # 1.0 to 3.0
    percent = int(50 + amount * 2.5)      # 50 to 300
    return img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=0))


def _apply_noise(img: Image.Image, amount: float) -> Image.Image:
    """Film grain / noise effect."""
    arr = np.array(img, dtype=np.float32)
    intensity = amount * 2.55
    rng = np.random.default_rng()

    if img.mode == "RGBA":
        noise = (rng.random(arr.shape[:2], dtype=np.float32) - 0.5) * intensity
        for c in range(3):
            arr[:, :, c] += noise
    else:
        noise = (rng.random(arr.shape[:2], dtype=np.float32) - 0.5) * intensity
        for c in range(arr.shape[2]):
            arr[:, :, c] += noise

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), img.mode)


def _apply_vignette(img: Image.Image, amount: float) -> Image.Image:
    """Radial vignette (darken edges)."""
    h, w = img.height, img.width
    cx, cy = w / 2, h / 2
    radius = math.sqrt(cx * cx + cy * cy)

    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    normalized = dist / radius

    strength = amount / 100
    # Same stops as the TS: 0 at center, 0 at 0.5, strength at 1.0
    vignette = np.where(normalized < 0.5, 0.0, (normalized - 0.5) / 0.5 * strength)
    vignette = np.clip(vignette, 0, 1)

    arr = np.array(img, dtype=np.float32)
    if img.mode == "RGBA":
        for c in range(3):
            arr[:, :, c] *= (1 - vignette)
    else:
        for c in range(arr.shape[2]):
            arr[:, :, c] *= (1 - vignette)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), img.mode)


def _apply_clarity(img: Image.Image, amount: float) -> Image.Image:
    """Local contrast enhancement (high-pass added back)."""
    blurred = img.filter(ImageFilter.GaussianBlur(radius=20))
    strength = amount / 100

    arr_orig = np.array(img, dtype=np.float32)
    arr_blur = np.array(blurred, dtype=np.float32)

    if img.mode == "RGBA":
        high_pass = arr_orig[:, :, :3] - arr_blur[:, :, :3]
        arr_orig[:, :, :3] += high_pass * strength
    else:
        high_pass = arr_orig - arr_blur
        arr_orig += high_pass * strength

    return Image.fromarray(np.clip(arr_orig, 0, 255).astype(np.uint8), img.mode)


def _apply_glow(img: Image.Image, amount: float) -> Image.Image:
    """Glow / bloom effect: blur bright areas + screen blend."""
    # Create glow layer: blur + brighten
    glow_img = img.filter(ImageFilter.GaussianBlur(radius=amount * 2))

    arr_orig = np.array(img, dtype=np.float32)
    arr_glow = np.array(glow_img, dtype=np.float32) * 1.5
    np.clip(arr_glow, 0, 255, out=arr_glow)

    alpha = amount / 100
    channels = 3 if img.mode == "RGBA" else arr_orig.shape[2]

    # Screen blend: 1 - (1-a)(1-b)
    a = arr_orig[:, :, :channels] / 255.0
    b = arr_glow[:, :, :channels] / 255.0
    screen = 1.0 - (1.0 - a) * (1.0 - b)
    arr_orig[:, :, :channels] = (
        arr_orig[:, :, :channels] * (1 - alpha) + screen * 255.0 * alpha
    )

    return Image.fromarray(np.clip(arr_orig, 0, 255).astype(np.uint8), img.mode)


def _apply_pixelate(img: Image.Image, amount: float) -> Image.Image:
    """Mosaic / pixelate effect."""
    pixel_size = max(2, int(amount / 2))
    small_w = max(1, img.width // pixel_size)
    small_h = max(1, img.height // pixel_size)
    small = img.resize((small_w, small_h), Image.NEAREST)
    return small.resize((img.width, img.height), Image.NEAREST)


def _apply_chromatic_aberration(img: Image.Image, amount: float) -> Image.Image:
    """RGB channel offset."""
    offset = int(amount / 5)
    if offset == 0:
        return img

    arr = np.array(img)
    result = arr.copy()
    h, w = arr.shape[:2]

    # Red channel - shift left
    result[:, :, 0] = np.roll(arr[:, :, 0], -offset, axis=1)
    # Blue channel - shift right
    result[:, :, 2] = np.roll(arr[:, :, 2], offset, axis=1)

    # Fix wrap-around edges
    if offset > 0:
        result[:, :offset, 0] = arr[:, :offset, 0]
        result[:, -offset:, 2] = arr[:, -offset:, 2]

    return Image.fromarray(result, img.mode)


def _apply_motion_blur(img: Image.Image, amount: float, angle: float) -> Image.Image:
    """Directional motion blur."""
    radians = angle * math.pi / 180
    dx = math.cos(radians)
    dy = math.sin(radians)

    samples = max(3, int(amount / 3))
    max_offset = amount / 2

    arr = np.array(img, dtype=np.float32)
    result = np.zeros_like(arr)

    for i in range(samples):
        t = (i / max(samples - 1, 1)) - 0.5
        offset_x = int(dx * t * max_offset * 2)
        offset_y = int(dy * t * max_offset * 2)

        shifted = np.roll(np.roll(arr, offset_x, axis=1), offset_y, axis=0)
        result += shifted

    result /= samples
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), img.mode)


# ---------------------------------------------------------------------------
# Creative / retro effects (ported from effects.ts)
# ---------------------------------------------------------------------------

def _apply_halftone(img: Image.Image, amount: float, angle: float = 0) -> Image.Image:
    """CMYK-style dot pattern."""
    w, h = img.width, img.height
    dot_size = max(2, int(2 + (amount / 100) * 18))
    half_dot = dot_size / 2

    rad = angle * math.pi / 180
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    if img.mode == "RGBA":
        source = img.convert("RGB")
    else:
        source = img if img.mode == "RGB" else img.convert("RGB")
    arr = np.array(source)

    result = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(result)

    for y in range(-dot_size, h + dot_size, dot_size):
        for x in range(-dot_size, w + dot_size, dot_size):
            cx = x + half_dot
            cy = y + half_dot

            # Rotate coordinates to sample
            rx = int(cos_a * (cx - w / 2) - sin_a * (cy - h / 2) + w / 2)
            ry = int(sin_a * (cx - w / 2) + cos_a * (cy - h / 2) + h / 2)

            if 0 <= rx < w and 0 <= ry < h:
                r, g, b = int(arr[ry, rx, 0]), int(arr[ry, rx, 1]), int(arr[ry, rx, 2])
                lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
                radius = half_dot * (1 - lum) * 0.9

                if radius > 0.5:
                    draw.ellipse(
                        [cx - radius, cy - radius, cx + radius, cy + radius],
                        fill=(r, g, b),
                    )

    if img.mode == "RGBA":
        result = result.convert("RGBA")
        result.putalpha(img.getchannel("A"))
    return result


def _apply_vhs(img: Image.Image, amount: float) -> Image.Image:
    """VHS / analog tape effect: wobble + scanlines + color separation."""
    w, h = img.width, img.height
    intensity = amount / 100

    source_mode = img.mode
    if source_mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
        source_mode = "RGB"

    arr = np.array(img, dtype=np.float32)
    result = np.zeros_like(arr)

    rng = np.random.default_rng()
    scanline_noise = (rng.random(h) - 0.5) * 2

    red_offset = int(intensity * 4)
    blue_offset = -int(intensity * 4)

    for y in range(h):
        wobble = math.sin(y * 0.1 + rng.random() * 0.5) * intensity * 5
        jitter = scanline_noise[y] * intensity * 3

        for x in range(w):
            src_x = int(x + wobble + jitter)
            src_x = max(0, min(w - 1, src_x))

            src_r = max(0, min(w - 1, src_x + red_offset))
            src_b = max(0, min(w - 1, src_x + blue_offset))

            result[y, x, 0] = arr[y, src_r, 0]
            result[y, x, 1] = arr[y, src_x, 1]
            result[y, x, 2] = arr[y, src_b, 2]
            if source_mode == "RGBA":
                result[y, x, 3] = 255

    # Add scanlines
    for y in range(0, h, 2):
        result[y, :, :3] *= (1 - intensity * 0.3 * 0.3)

    # Add tracking glitches
    num_glitches = int(intensity * 5)
    for _ in range(num_glitches):
        gy = rng.integers(0, h)
        gh = rng.integers(2, 12)
        end_y = min(gy + gh, h)
        result[gy:end_y, :, :3] = np.clip(
            result[gy:end_y, :, :3] + 255 * 0.5 * intensity * 0.5,
            0, 255,
        )

    out = Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), source_mode)
    return out


def _apply_glitch(img: Image.Image, amount: float, block_size: int = 16) -> Image.Image:
    """Random RGB block displacement."""
    w, h = img.width, img.height
    intensity = amount / 100

    source_mode = img.mode
    if source_mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
        source_mode = "RGB"

    arr = np.array(img)
    result = arr.copy()
    rng = np.random.default_rng()

    num_blocks = int(intensity * 20) + 1

    for _ in range(num_blocks):
        by = rng.integers(0, h)
        bh = rng.integers(block_size, block_size * 2 + 1)
        bw = rng.integers(int(w * 0.2), int(w * 0.8) + 1)
        bx = rng.integers(0, max(1, w - bw))

        r_off = int((rng.random() - 0.5) * intensity * 30)
        g_off = int((rng.random() - 0.5) * intensity * 30)
        b_off = int((rng.random() - 0.5) * intensity * 30)

        for y in range(by, min(by + bh, h)):
            for x in range(bx, min(bx + bw, w)):
                sr = max(0, min(w - 1, x + r_off))
                sg = max(0, min(w - 1, x + g_off))
                sb = max(0, min(w - 1, x + b_off))
                result[y, x, 0] = arr[y, sr, 0]
                result[y, x, 1] = arr[y, sg, 1]
                result[y, x, 2] = arr[y, sb, 2]

    # Horizontal line shifts
    num_shifts = int(intensity * 10)
    for _ in range(num_shifts):
        sy = rng.integers(0, h)
        sh = rng.integers(1, 6)
        shift = int((rng.random() - 0.5) * intensity * 50)

        for y in range(sy, min(sy + sh, h)):
            result[y] = np.roll(arr[y], shift, axis=0)

    return Image.fromarray(result, source_mode)


# ---------------------------------------------------------------------------
# Dithering (Floyd-Steinberg, ported from effects.ts)
# ---------------------------------------------------------------------------

_DITHER_PALETTES: dict[str, list[tuple[int, int, int]]] = {
    "bw": [(0, 0, 0), (255, 255, 255)],
    "gameboy": [(15, 56, 15), (48, 98, 48), (139, 172, 15), (155, 188, 15)],
    "cga": [(0, 0, 0), (0, 170, 170), (170, 0, 170), (170, 170, 170)],
    "4bit": [
        (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
        (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
        (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
        (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
    ],
}


def _build_8bit_palette() -> list[tuple[int, int, int]]:
    palette = []
    for r in range(6):
        for g in range(6):
            for b in range(6):
                palette.append((r * 51, g * 51, b * 51))
    for i in range(24):
        v = round(i * 10.625)
        palette.append((v, v, v))
    return palette


_DITHER_PALETTES["8bit"] = _build_8bit_palette()


def _apply_dither(img: Image.Image, palette: str) -> Image.Image:
    """Floyd-Steinberg dithering with palette quantization."""
    colors = _DITHER_PALETTES.get(palette, _DITHER_PALETTES["8bit"])

    had_alpha = img.mode == "RGBA"
    alpha_channel = None
    if had_alpha:
        alpha_channel = img.getchannel("A")
        work = img.convert("RGB")
    elif img.mode != "RGB":
        work = img.convert("RGB")
    else:
        work = img

    arr = np.array(work, dtype=np.float64)
    h, w, _ = arr.shape

    # Build palette array for vectorized closest-color lookup
    pal = np.array(colors, dtype=np.float64)

    for y in range(h):
        for x in range(w):
            old_r, old_g, old_b = arr[y, x]

            # Find closest palette color
            diffs = pal - np.array([old_r, old_g, old_b])
            dists = np.sum(diffs ** 2, axis=1)
            idx = np.argmin(dists)
            new_r, new_g, new_b = pal[idx]

            arr[y, x] = [new_r, new_g, new_b]

            err_r = old_r - new_r
            err_g = old_g - new_g
            err_b = old_b - new_b

            if x + 1 < w:
                arr[y, x + 1] += [err_r * 7 / 16, err_g * 7 / 16, err_b * 7 / 16]
            if y + 1 < h and x - 1 >= 0:
                arr[y + 1, x - 1] += [err_r * 3 / 16, err_g * 3 / 16, err_b * 3 / 16]
            if y + 1 < h:
                arr[y + 1, x] += [err_r * 5 / 16, err_g * 5 / 16, err_b * 5 / 16]
            if y + 1 < h and x + 1 < w:
                arr[y + 1, x + 1] += [err_r * 1 / 16, err_g * 1 / 16, err_b * 1 / 16]

    result = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    if had_alpha and alpha_channel is not None:
        result = result.convert("RGBA")
        result.putalpha(alpha_channel)
    return result


# ---------------------------------------------------------------------------
# Color effects (ported from colorMatrix.ts)
# ---------------------------------------------------------------------------

def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """Convert HSL (h: 0-360, s: 0-100, l: 0-100) to RGB (0-255)."""
    h /= 360
    s /= 100
    l /= 100

    if s == 0:
        v = round(l * 255)
        return (v, v, v)

    def hue2rgb(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = round(hue2rgb(p, q, h + 1 / 3) * 255)
    g = round(hue2rgb(p, q, h) * 255)
    b = round(hue2rgb(p, q, h - 1 / 3) * 255)
    return (r, g, b)


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert RGB (0-255) to HSL (h: 0-360, s: 0-100, l: 0-100)."""
    r_n, g_n, b_n = r / 255, g / 255, b / 255
    mx = max(r_n, g_n, b_n)
    mn = min(r_n, g_n, b_n)
    h = 0.0
    s = 0.0
    l = (mx + mn) / 2

    if mx != mn:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r_n:
            h = ((g_n - b_n) / d + (6 if g_n < b_n else 0)) / 6
        elif mx == g_n:
            h = ((b_n - r_n) / d + 2) / 6
        else:
            h = ((r_n - g_n) / d + 4) / 6

    return (h * 360, s * 100, l * 100)


def _apply_split_toning(
    img: Image.Image,
    shadow_hue: float,
    shadow_sat: float,
    highlight_hue: float,
    highlight_sat: float,
    balance: float = 0,
) -> Image.Image:
    """Add color tints to shadows and highlights separately."""
    had_alpha = img.mode == "RGBA"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    arr = np.array(img, dtype=np.float32)

    shadow_rgb = _hsl_to_rgb(shadow_hue, shadow_sat, 50)
    highlight_rgb = _hsl_to_rgb(highlight_hue, highlight_sat, 50)
    shadow_intensity = shadow_sat / 100
    highlight_intensity = highlight_sat / 100
    balance_offset = balance / 200

    rgb = arr[:, :, :3]
    lum = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]) / 255.0
    midpoint = 0.5 + balance_offset

    shadow_weight = np.where(lum < midpoint, 1 - lum / midpoint, 0.0)
    highlight_weight = np.where(lum >= midpoint, (lum - midpoint) / max(1 - midpoint, 0.001), 0.0)

    for c in range(3):
        rgb[:, :, c] += (shadow_rgb[c] - 128) * shadow_weight * shadow_intensity
        rgb[:, :, c] += (highlight_rgb[c] - 128) * highlight_weight * highlight_intensity

    arr[:, :, :3] = rgb
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), img.mode)


def _apply_gradient_map(
    img: Image.Image,
    shadow_color: dict[str, int] | tuple[int, int, int],
    highlight_color: dict[str, int] | tuple[int, int, int],
    intensity: float = 100,
) -> Image.Image:
    """Map luminance to a two-color gradient (duotone)."""
    had_alpha = img.mode == "RGBA"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # Normalize color inputs
    if isinstance(shadow_color, dict):
        sc = (shadow_color["r"], shadow_color["g"], shadow_color["b"])
    else:
        sc = shadow_color
    if isinstance(highlight_color, dict):
        hc = (highlight_color["r"], highlight_color["g"], highlight_color["b"])
    else:
        hc = highlight_color

    arr = np.array(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    blend = intensity / 100

    lum = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]) / 255.0

    for c in range(3):
        mapped = sc[c] + (hc[c] - sc[c]) * lum
        rgb[:, :, c] = rgb[:, :, c] * (1 - blend) + mapped * blend

    arr[:, :, :3] = rgb
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), img.mode)


def _apply_color_isolation(
    img: Image.Image,
    hue: float,
    hue_range: float,
    feather: float = 20,
) -> Image.Image:
    """Desaturate all except selected hue range."""
    had_alpha = img.mode == "RGBA"
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    arr = np.array(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    feather_degrees = (feather / 100) * 60

    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]

    # Vectorized RGB to hue
    r_n, g_n, b_n = r / 255, g / 255, b / 255
    mx = np.maximum(np.maximum(r_n, g_n), b_n)
    mn = np.minimum(np.minimum(r_n, g_n), b_n)
    d = mx - mn

    h = np.zeros_like(r_n)
    mask_r = (mx == r_n) & (d > 0)
    mask_g = (mx == g_n) & (d > 0) & ~mask_r
    mask_b = (mx == b_n) & (d > 0) & ~mask_r & ~mask_g

    h[mask_r] = (((g_n[mask_r] - b_n[mask_r]) / d[mask_r]) % 6) / 6
    h[mask_g] = (((b_n[mask_g] - r_n[mask_g]) / d[mask_g]) + 2) / 6
    h[mask_b] = (((r_n[mask_b] - g_n[mask_b]) / d[mask_b]) + 4) / 6

    h_deg = h * 360

    # Hue distance (wrapping)
    hue_diff = np.abs(h_deg - hue)
    hue_diff = np.where(hue_diff > 180, 360 - hue_diff, hue_diff)

    # Saturation factor
    sat_factor = np.where(
        hue_diff <= hue_range,
        1.0,
        np.where(
            hue_diff <= hue_range + feather_degrees,
            1.0 - (hue_diff - hue_range) / max(feather_degrees, 0.001),
            0.0,
        ),
    )

    gray = 0.2126 * r + 0.7152 * g + 0.0722 * b

    for c in range(3):
        rgb[:, :, c] = rgb[:, :, c] * sat_factor + gray * (1 - sat_factor)

    arr[:, :, :3] = rgb
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), img.mode)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_AUTO_FUNCS = {
    "levels": _auto_levels,
    "contrast": _auto_contrast,
    "white_balance": _auto_white_balance,
}


def adjust(
    image: Image.Image | str | Path,
    *,
    auto: str | None = None,
    # Levels (-100 to 100)
    brightness: float = 0,
    contrast: float = 0,
    saturation: float = 0,
    exposure: float = 0,
    temperature: float = 0,
    gamma: float = 1.0,
    # Filter preset
    filter: str | None = None,
    # Spatial effects (0 to 100)
    blur: float = 0,
    sharpen: float = 0,
    noise: float = 0,
    vignette: float = 0,
    clarity: float = 0,
    glow: float = 0,
    pixelate: float = 0,
    chromatic_aberration: float = 0,
    motion_blur: float = 0,
    motion_blur_angle: float = 0,
    # Creative effects
    halftone: float = 0,
    halftone_angle: float = 0,
    vhs: float = 0,
    glitch: float = 0,
    glitch_block_size: int = 16,
    dither: str | None = None,
    # Color effects
    split_toning: dict[str, Any] | None = None,
    gradient_map: dict[str, Any] | None = None,
    color_isolation: dict[str, Any] | None = None,
) -> Image.Image:
    """Apply image adjustments, filters, and effects.

    Accepts a PIL Image or file path. Returns a PIL Image.
    All parameters are optional and composable.
    """
    # Load image if path
    if isinstance(image, (str, Path)):
        from utils.image_ops import open_oriented
        image = open_oriented(image)
    elif not isinstance(image, Image.Image):
        raise TypeError(f"Expected PIL Image or path, got {type(image).__name__}")

    img = image.copy()

    # --- 1. Auto adjustment ---
    if auto is not None:
        fn = _AUTO_FUNCS.get(auto)
        if fn is None:
            raise ValueError(f"Unknown auto mode '{auto}'. Choose from: {', '.join(_AUTO_FUNCS)}")
        img = fn(img)

    # --- 2. Level adjustments (compose into single matrix) ---
    level_matrix = _combine_adjustments(
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
        exposure=exposure,
        temperature=temperature,
    )

    # --- 3. Filter preset ---
    if filter is not None:
        filter_key = filter.replace("-", "_")
        if filter_key not in FILTER_MATRICES:
            raise ValueError(f"Unknown filter '{filter}'. Available: {', '.join(FILTER_NAMES)}")
        filter_matrix = FILTER_MATRICES[filter_key]
        if level_matrix is not None:
            level_matrix = _multiply_matrices(level_matrix, filter_matrix)
        else:
            level_matrix = filter_matrix

    # Apply composed color matrix
    if level_matrix is not None:
        img = _apply_color_matrix(img, level_matrix)

    # --- Gamma (real correction, not matrix approximation) ---
    if gamma != 1.0:
        img = _apply_gamma(img, gamma)

    # --- 4. Color effects ---
    if split_toning is not None:
        img = _apply_split_toning(
            img,
            shadow_hue=split_toning.get("shadow_hue", 0),
            shadow_sat=split_toning.get("shadow_sat", 0),
            highlight_hue=split_toning.get("highlight_hue", 0),
            highlight_sat=split_toning.get("highlight_sat", 0),
            balance=split_toning.get("balance", 0),
        )
    if gradient_map is not None:
        img = _apply_gradient_map(
            img,
            shadow_color=gradient_map.get("shadow_color", (0, 0, 0)),
            highlight_color=gradient_map.get("highlight_color", (255, 255, 255)),
            intensity=gradient_map.get("intensity", 100),
        )
    if color_isolation is not None:
        img = _apply_color_isolation(
            img,
            hue=color_isolation.get("hue", 0),
            hue_range=color_isolation.get("range", 30),
            feather=color_isolation.get("feather", 20),
        )

    # --- 5. Spatial effects (in pipeline order from TS) ---
    if pixelate > 0:
        img = _apply_pixelate(img, pixelate)
    if clarity != 0:
        img = _apply_clarity(img, clarity)
    if sharpen > 0:
        img = _apply_sharpen(img, sharpen)
    if blur > 0:
        img = _apply_blur(img, blur)
    if motion_blur > 0:
        img = _apply_motion_blur(img, motion_blur, motion_blur_angle)
    if glow > 0:
        img = _apply_glow(img, glow)
    if chromatic_aberration > 0:
        img = _apply_chromatic_aberration(img, chromatic_aberration)
    if noise > 0:
        img = _apply_noise(img, noise)
    if vignette > 0:
        img = _apply_vignette(img, vignette)

    # --- 6. Retro / creative effects ---
    if halftone > 0:
        img = _apply_halftone(img, halftone, halftone_angle)
    if vhs > 0:
        img = _apply_vhs(img, vhs)
    if glitch > 0:
        img = _apply_glitch(img, glitch, glitch_block_size)
    if dither is not None:
        valid = list(_DITHER_PALETTES.keys())
        if dither not in valid:
            raise ValueError(f"Unknown dither palette '{dither}'. Choose from: {', '.join(valid)}")
        img = _apply_dither(img, dither)

    return img

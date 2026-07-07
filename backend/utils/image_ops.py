"""Pillow+NumPy image ops used to replace OpenCV in runtime paths."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps


ResizeMode = Literal["nearest", "bilinear", "bicubic"]


def has_alpha_channel(img: Image.Image) -> bool:
    """Whether the image's format declares an alpha channel.

    Reads only `mode`/`info`, which Pillow already populates from the file
    header on `Image.open()` — never triggers a pixel decode, so this is
    cheap even scanning an entire library. Reports channel *presence* (e.g.
    a PNG saved as RGBA or with a tRNS entry), not whether any pixel is
    actually non-opaque.
    """
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P":
        return "transparency" in img.info
    return False


def open_oriented(path: str | Path) -> Image.Image:
    """Open an image with its EXIF orientation applied.

    Library files keep their original bytes, so the orientation tag must be
    applied at decode time to match how browsers and thumbnails display the
    image. Use this instead of Image.open() whenever pixels or dimensions of
    a library file feed display, ML, or generation paths.
    """
    img = Image.open(path)
    transposed = ImageOps.exif_transpose(img)
    if transposed is not img:
        img.close()
    return transposed


@lru_cache(maxsize=1)
def _optional_skimage() -> dict[str, object]:
    try:
        from skimage.feature import canny
        from skimage.filters import threshold_local
        from skimage.morphology import binary_closing, binary_dilation
        from skimage.restoration import denoise_bilateral
        from skimage.transform import SimilarityTransform
    except Exception:  # pragma: no cover - fallback path if optional deps are unavailable
        return {}
    return {
        "binary_closing": binary_closing,
        "binary_dilation": binary_dilation,
        "canny": canny,
        "denoise_bilateral": denoise_bilateral,
        "SimilarityTransform": SimilarityTransform,
        "threshold_local": threshold_local,
    }


def _skimage_func(name: str):
    return _optional_skimage().get(name)


def imread_bgr(path: str | Path) -> np.ndarray:
    """Load image as BGR uint8 array, honoring EXIF orientation."""
    with open_oriented(path) as img:
        rgb = np.array(img.convert("RGB"), dtype=np.uint8)
    return rgb[:, :, ::-1].copy()


def imwrite_bgr(path: str | Path, image: np.ndarray) -> None:
    """Write BGR uint8 image to disk."""
    rgb = bgr_to_rgb(image)
    Image.fromarray(rgb, mode="RGB").save(path)


def bgr_to_rgb(image: np.ndarray) -> np.ndarray:
    return image[:, :, ::-1].copy()


def rgb_to_bgr(image: np.ndarray) -> np.ndarray:
    return image[:, :, ::-1].copy()


def bgr_to_gray(image: np.ndarray) -> np.ndarray:
    """Convert BGR uint8 image to grayscale uint8."""
    b = image[:, :, 0].astype(np.float32)
    g = image[:, :, 1].astype(np.float32)
    r = image[:, :, 2].astype(np.float32)
    gray = 0.114 * b + 0.587 * g + 0.299 * r
    return np.clip(gray, 0, 255).astype(np.uint8)


def gray_to_bgr(gray: np.ndarray) -> np.ndarray:
    return np.repeat(gray[:, :, np.newaxis], 3, axis=2)


def _pil_resample(mode: ResizeMode) -> int:
    if mode == "nearest":
        return Image.NEAREST
    if mode == "bicubic":
        return Image.BICUBIC
    return Image.BILINEAR


def resize(image: np.ndarray, size: tuple[int, int], mode: ResizeMode = "bilinear") -> np.ndarray:
    """
    Resize image to (width, height).
    Supports uint8/float32, 2D or 3D.
    """
    width, height = size
    resample = _pil_resample(mode)

    if image.ndim == 2:
        if image.dtype == np.uint8:
            pil = Image.fromarray(image, mode="L")
            return np.array(pil.resize((width, height), resample=resample), dtype=np.uint8)
        pil = Image.fromarray(image.astype(np.float32), mode="F")
        return np.array(pil.resize((width, height), resample=resample), dtype=np.float32)

    channels = []
    for c in range(image.shape[2]):
        ch = image[:, :, c]
        channels.append(resize(ch, (width, height), mode=mode))
    stacked = np.stack(channels, axis=2)
    if image.dtype == np.uint8:
        return np.clip(stacked, 0, 255).astype(np.uint8)
    return stacked.astype(image.dtype, copy=False)


def threshold_otsu(gray: np.ndarray) -> int:
    """Compute Otsu threshold for uint8 grayscale image."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = gray.size
    sum_total = np.dot(np.arange(256), hist)

    sum_bg = 0.0
    w_bg = 0.0
    max_var = -1.0
    threshold = 0

    for t in range(256):
        w_bg += hist[t]
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * hist[t]
        m_bg = sum_bg / w_bg
        m_fg = (sum_total - sum_bg) / w_fg
        between = w_bg * w_fg * (m_bg - m_fg) ** 2
        if between > max_var:
            max_var = between
            threshold = t
    return int(threshold)


def threshold_binary(gray: np.ndarray, thresh: int, max_value: int = 255) -> np.ndarray:
    return np.where(gray > thresh, max_value, 0).astype(np.uint8)


def _gaussian_kernel1d(sigma: float, radius: int | None = None) -> np.ndarray:
    if sigma <= 0:
        return np.array([1.0], dtype=np.float32)
    if radius is None:
        radius = max(1, int(round(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    k = np.exp(-(x ** 2) / (2.0 * sigma * sigma))
    k /= np.sum(k)
    return k.astype(np.float32)


def _conv1d_axis(image: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    pad = len(kernel) // 2
    if axis == 0:
        padded = np.pad(image, ((pad, pad), (0, 0)), mode="reflect")
        out = np.zeros_like(image, dtype=np.float32)
        for i, w in enumerate(kernel):
            out += w * padded[i : i + image.shape[0], :]
        return out
    padded = np.pad(image, ((0, 0), (pad, pad)), mode="reflect")
    out = np.zeros_like(image, dtype=np.float32)
    for i, w in enumerate(kernel):
        out += w * padded[:, i : i + image.shape[1]]
    return out


def gaussian_blur(gray: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    src = gray.astype(np.float32)
    k = _gaussian_kernel1d(sigma)
    tmp = _conv1d_axis(src, k, axis=1)
    out = _conv1d_axis(tmp, k, axis=0)
    return out


def bilateral_like_filter(gray: np.ndarray) -> np.ndarray:
    """
    Lightweight bilateral-like smoothing.
    This is intentionally simple but preserves edges better than pure blur.
    """
    sk_denoise_bilateral = _skimage_func("denoise_bilateral")
    if sk_denoise_bilateral is not None:
        out = sk_denoise_bilateral(
            gray.astype(np.float32) / 255.0,
            sigma_color=75.0 / 255.0,
            sigma_spatial=9.0 / 2.5,
            channel_axis=None,
        )
        return np.clip(out * 255.0, 0, 255).astype(np.uint8)

    src = gray.astype(np.float32)
    smooth = gaussian_blur(src, sigma=1.2)
    edge = np.abs(src - smooth)
    alpha = np.clip(edge / 32.0, 0.0, 1.0)
    blended = alpha * src + (1.0 - alpha) * smooth
    return np.clip(blended, 0, 255).astype(np.uint8)


def adaptive_threshold_gaussian(
    gray: np.ndarray, max_value: int = 255, block_size: int = 11, c: float = 2.0
) -> np.ndarray:
    if block_size % 2 == 0:
        raise ValueError("block_size must be odd")
    sk_threshold_local = _skimage_func("threshold_local")
    if sk_threshold_local is not None:
        local = sk_threshold_local(gray.astype(np.float32), block_size=block_size, method="gaussian", offset=c)
        out = np.where(gray.astype(np.float32) > local, max_value, 0)
        return out.astype(np.uint8)

    sigma = max(1.0, block_size / 6.0)
    k = _gaussian_kernel1d(sigma, radius=block_size // 2)
    local = _conv1d_axis(_conv1d_axis(gray.astype(np.float32), k, axis=1), k, axis=0)
    out = np.where(gray.astype(np.float32) > (local - c), max_value, 0)
    return out.astype(np.uint8)


def ellipse_kernel(size: tuple[int, int]) -> np.ndarray:
    h, w = size
    cy = (h - 1) / 2.0
    cx = (w - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    if cy == 0 or cx == 0:
        return np.ones((h, w), dtype=np.uint8)
    mask = (((yy - cy) / cy) ** 2 + ((xx - cx) / cx) ** 2) <= 1.0
    out = mask.astype(np.uint8)
    # Keep morphology operations well-defined for tiny kernels.
    if not out.any():
        out[:, :] = 1
    return out


def _morph_op(image: np.ndarray, kernel: np.ndarray, op: Literal["dilate", "erode"]) -> np.ndarray:
    kh, kw = kernel.shape
    py, px = kh // 2, kw // 2
    padded = np.pad(image, ((py, py), (px, px)), mode="edge")
    out = np.zeros_like(image, dtype=np.uint8)

    for y in range(image.shape[0]):
        for x in range(image.shape[1]):
            window = padded[y : y + kh, x : x + kw]
            vals = window[kernel > 0]
            out[y, x] = np.max(vals) if op == "dilate" else np.min(vals)
    return out


def morphology_dilate(binary: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    sk_binary_dilation = _skimage_func("binary_dilation")
    if sk_binary_dilation is not None:
        out = sk_binary_dilation(binary > 0, footprint=(kernel > 0))
        return np.where(out, 255, 0).astype(np.uint8)
    return _morph_op(binary, kernel, op="dilate")


def morphology_close(binary: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    sk_binary_closing = _skimage_func("binary_closing")
    if sk_binary_closing is not None:
        out = sk_binary_closing(binary > 0, footprint=(kernel > 0))
        return np.where(out, 255, 0).astype(np.uint8)

    dilated = _morph_op(binary, kernel, op="dilate")
    return _morph_op(dilated, kernel, op="erode")


def _sobel(gray_f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # 3x3 Sobel kernels
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
    ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)
    padded = np.pad(gray_f, ((1, 1), (1, 1)), mode="reflect")
    gx = np.zeros_like(gray_f, dtype=np.float32)
    gy = np.zeros_like(gray_f, dtype=np.float32)
    for y in range(gray_f.shape[0]):
        for x in range(gray_f.shape[1]):
            w = padded[y : y + 3, x : x + 3]
            gx[y, x] = np.sum(w * kx)
            gy[y, x] = np.sum(w * ky)
    return gx, gy


def canny(gray: np.ndarray, low_thresh: int, high_thresh: int) -> np.ndarray:
    """Simple NumPy Canny implementation producing uint8 edge map."""
    sk_canny = _skimage_func("canny")
    if sk_canny is not None:
        edges = sk_canny(
            gray.astype(np.float32) / 255.0,
            sigma=1.0,
            low_threshold=float(low_thresh) / 255.0,
            high_threshold=float(high_thresh) / 255.0,
        )
        return np.where(edges, 255, 0).astype(np.uint8)

    blur = gaussian_blur(gray, sigma=1.2)
    gx, gy = _sobel(blur)
    mag = np.hypot(gx, gy)
    angle = (np.rad2deg(np.arctan2(gy, gx)) + 180.0) % 180.0

    # Non-max suppression
    nms = np.zeros_like(mag, dtype=np.float32)
    h, w = mag.shape
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            a = angle[y, x]
            q = 0.0
            r = 0.0
            if (0 <= a < 22.5) or (157.5 <= a <= 180):
                q = mag[y, x + 1]
                r = mag[y, x - 1]
            elif 22.5 <= a < 67.5:
                q = mag[y + 1, x - 1]
                r = mag[y - 1, x + 1]
            elif 67.5 <= a < 112.5:
                q = mag[y + 1, x]
                r = mag[y - 1, x]
            else:
                q = mag[y - 1, x - 1]
                r = mag[y + 1, x + 1]
            if mag[y, x] >= q and mag[y, x] >= r:
                nms[y, x] = mag[y, x]

    strong = nms >= float(high_thresh)
    weak = (nms >= float(low_thresh)) & ~strong

    # Hysteresis
    edges = np.zeros_like(gray, dtype=np.uint8)
    edges[strong] = 255
    changed = True
    while changed:
        changed = False
        ys, xs = np.where(weak)
        for y, x in zip(ys, xs):
            if np.any(edges[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] == 255):
                edges[y, x] = 255
                weak[y, x] = False
                changed = True
    return edges


def _make_inferno_lut() -> np.ndarray:
    # Compact control points approximating inferno in RGB.
    points = np.array(
        [
            [0, 0, 4],
            [31, 12, 72],
            [85, 15, 109],
            [136, 34, 106],
            [186, 73, 74],
            [227, 123, 35],
            [249, 190, 39],
            [252, 255, 164],
        ],
        dtype=np.float32,
    )
    x = np.linspace(0, len(points) - 1, 256, dtype=np.float32)
    x0 = np.floor(x).astype(int)
    x1 = np.clip(x0 + 1, 0, len(points) - 1)
    t = x - x0
    lut = (1.0 - t)[:, None] * points[x0] + t[:, None] * points[x1]
    return np.clip(lut, 0, 255).astype(np.uint8)


_INFERNO_LUT = _make_inferno_lut()


def apply_colormap_inferno(gray: np.ndarray) -> np.ndarray:
    rgb = _INFERNO_LUT[gray]
    return rgb_to_bgr(rgb)


def estimate_affine(src_pts: np.ndarray, dst_pts: np.ndarray) -> np.ndarray | None:
    """
    Estimate 2x3 affine transform mapping src -> dst using least squares.
    Returns None when solve fails.
    """
    if src_pts.shape != dst_pts.shape or src_pts.shape[0] < 3:
        return None

    sk_similarity_transform = _skimage_func("SimilarityTransform")
    if sk_similarity_transform is not None:
        tform = sk_similarity_transform()
        ok = tform.estimate(src_pts.astype(np.float64), dst_pts.astype(np.float64))
        if ok:
            return tform.params[:2, :].astype(np.float32)

    src = src_pts.astype(np.float64)
    dst = dst_pts.astype(np.float64)
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_c = src - src_mean
    dst_c = dst - dst_mean

    cov = (dst_c.T @ src_c) / src.shape[0]
    try:
        u, s, vt = np.linalg.svd(cov)
    except np.linalg.LinAlgError:
        return None

    d = np.ones(2, dtype=np.float64)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        d[-1] = -1.0
    r = u @ np.diag(d) @ vt

    src_var = np.mean(np.sum(src_c * src_c, axis=1))
    if src_var <= 1e-12:
        return None
    scale = float(np.sum(s * d) / src_var)
    t = dst_mean - scale * (r @ src_mean)

    m = np.array(
        [
            [scale * r[0, 0], scale * r[0, 1], t[0]],
            [scale * r[1, 0], scale * r[1, 1], t[1]],
        ],
        dtype=np.float32,
    )
    return m


def warp_affine(image: np.ndarray, matrix: np.ndarray, out_size: tuple[int, int]) -> np.ndarray:
    """
    Warp BGR image with affine matrix mapping src->dst.
    Uses PIL AFFINE transform with inverse mapping.
    out_size: (width, height)
    """
    width, height = out_size
    m = np.vstack([matrix, np.array([0.0, 0.0, 1.0], dtype=np.float32)])
    try:
        inv = np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return resize(image, out_size, mode="bilinear")

    coeffs = (
        float(inv[0, 0]),
        float(inv[0, 1]),
        float(inv[0, 2]),
        float(inv[1, 0]),
        float(inv[1, 1]),
        float(inv[1, 2]),
    )

    rgb = bgr_to_rgb(image)
    pil = Image.fromarray(rgb, mode="RGB")
    warped = pil.transform((width, height), Image.AFFINE, coeffs, resample=Image.BILINEAR)
    out_rgb = np.array(warped, dtype=np.uint8)
    return rgb_to_bgr(out_rgb)

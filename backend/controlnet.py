"""
ControlNet preprocessors for image-to-control-map conversion.

Provides canny edge detection, depth estimation, line art extraction,
and pose estimation. Results are cached by file hash + preprocessor type.
"""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np

import app_dirs
from core.logging import get_logger
from utils import image_ops

log = get_logger(__name__)

# Thread pool for running preprocessing (OpenCV/ONNX are synchronous)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="controlnet")

# Supported preprocessor IDs
PREPROCESSORS = {"canny", "depth", "lineart", "lineart_realistic", "lineart_anime", "pose", "pose_hands"}

# Singleton for Depth Anything V2 ONNX model
_depth_anything_session: Optional[object] = None

# Singleton for DWPose Wholebody model
_dwpose_model: Optional[object] = None

# Singletons for lineart ONNX models
_lineart_realistic_sessions: dict[str, object] = {}  # "fine" and "coarse" keys
_lineart_anime_session: Optional[object] = None

# R2 base URL for hosted ONNX models
_MODELS_BASE_URL = "https://models.stimma.ai"


def _get_cache_dir() -> Path:
    """Get the controlnet preview cache directory."""
    cache_dir = app_dirs.get_cache_dir() / "controlnet-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_models_dir() -> Path:
    """Get the directory for controlnet models (Depth Anything etc.)."""
    models_dir = app_dirs.get_cache_dir() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def _get_depth_anything_config() -> tuple[str, str]:
    """
    Resolve Depth Anything V2 model variant and source URL.

    STIMMA_DEPTH_ANYTHING_MODEL supports: small, base, large.
    """
    variant = os.getenv("STIMMA_DEPTH_ANYTHING_MODEL", "large").strip().lower()
    if variant not in {"small", "base", "large"}:
        log.warning(f"Unknown STIMMA_DEPTH_ANYTHING_MODEL={variant!r}; falling back to 'large'")
        variant = "large"

    filename = f"depth_anything_v2_{variant}.onnx"
    url = f"https://huggingface.co/onnx-community/depth-anything-v2-{variant}/resolve/main/onnx/model.onnx"
    return filename, url


def _file_hash(path: str) -> str:
    """Compute a fast hash of the file for cache key."""
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        # Read first 64KB + file size for speed
        h.update(f.read(65536))
        f.seek(0, 2)
        h.update(str(f.tell()).encode())
    return h.hexdigest()


def _load_image(path: str) -> np.ndarray:
    """Load an image as BGR numpy array."""
    img = image_ops.imread_bgr(path)
    if img is None:
        raise ValueError(f"Could not load image: {path}")
    return img


def _canny(image: np.ndarray, params: dict | None = None) -> np.ndarray:
    """Canny edge detection preprocessor."""
    gray = image_ops.bgr_to_gray(image)
    if params and "low" in params and "high" in params:
        low_thresh = int(params["low"])
        high_thresh = int(params["high"])
    else:
        # Auto-threshold using Otsu's method
        high_thresh = image_ops.threshold_otsu(gray)
        low_thresh = max(1, int(high_thresh * 0.5))
    edges = image_ops.canny(gray, low_thresh, high_thresh)
    # Dilate edges slightly for stronger model conditioning
    kernel = image_ops.ellipse_kernel((3, 3))
    edges = image_ops.morphology_dilate(edges, kernel)
    # Convert to 3-channel for consistency
    return image_ops.gray_to_bgr(edges)


def _get_depth_anything_session():
    """Load Depth Anything V2 ONNX model (singleton)."""
    global _depth_anything_session
    if _depth_anything_session is not None:
        return _depth_anything_session

    import onnxruntime as ort

    filename, url = _get_depth_anything_config()
    model_path = _get_models_dir() / filename

    if not model_path.exists():
        log.info(f"Downloading Depth Anything V2 ONNX model ({filename})...")
        _download_onnx_model(model_path, url)

    log.info(f"Loading Depth Anything V2 model from {model_path}")
    _depth_anything_session = ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )
    return _depth_anything_session


def _download_onnx_model(dest: Path, url: str):
    """Download ONNX model from URL."""
    import urllib.request

    log.info(f"Downloading ONNX model from {url}")

    tmp_path = dest.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(url, str(tmp_path))
        tmp_path.rename(dest)
        log.info(f"Model saved to {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _depth_anything_resize_lower_bound(
    image: np.ndarray, width: int = 518, height: int = 518, multiple_of: int = 14
) -> np.ndarray:
    """
    Resize while preserving aspect ratio using lower-bound strategy.

    This matches Depth Anything style preprocessing:
    - keep aspect ratio
    - scale so both dimensions are >= target
    - round up to multiples of 14 (ViT patch/grid alignment)
    """
    h, w = image.shape[:2]
    scale = max(width / w, height / h)
    new_w = int(np.ceil((w * scale) / multiple_of) * multiple_of)
    new_h = int(np.ceil((h * scale) / multiple_of) * multiple_of)
    return image_ops.resize(image, (new_w, new_h), mode="bicubic")


def _normalize_depth_for_controlnet(depth: np.ndarray) -> np.ndarray:
    """
    Robust depth normalization to preserve subtle gradients.

    Percentile-based normalization avoids outliers flattening most of the map.
    """
    depth = depth.astype(np.float32, copy=False)
    p2 = float(np.percentile(depth, 2.0))
    p98 = float(np.percentile(depth, 98.0))
    if p98 - p2 < 1e-6:
        dmin = float(depth.min())
        dmax = float(depth.max())
        if dmax - dmin < 1e-6:
            norm = np.zeros_like(depth, dtype=np.float32)
        else:
            norm = (depth - dmin) / (dmax - dmin)
    else:
        norm = (depth - p2) / (p98 - p2)
    norm = np.clip(norm, 0.0, 1.0)
    return (norm * 255.0).astype(np.uint8)


def _depth(image: np.ndarray) -> np.ndarray:
    """Depth estimation using Depth Anything V2 ONNX."""
    session = _get_depth_anything_session()

    # Preprocess: keep aspect ratio, 518 target, multiple-of-14
    h, w = image.shape[:2]
    img_rgb = image_ops.bgr_to_rgb(image)
    img_resized = _depth_anything_resize_lower_bound(img_rgb, width=518, height=518, multiple_of=14)
    img_input = img_resized.astype(np.float32) / 255.0

    # Normalize with ImageNet stats used by Depth Anything V2
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    img_input = (img_input - mean) / std
    img_input = img_input.transpose(2, 0, 1)[np.newaxis]  # NCHW

    # Run inference
    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: img_input})[0]

    # Post-process: resize back and robust-normalize to 8-bit control map
    depth = np.squeeze(output)
    if depth.ndim == 3:
        depth = depth[0]
    depth = image_ops.resize(depth.astype(np.float32), (w, h), mode="bicubic")
    depth_uint8 = _normalize_depth_for_controlnet(depth)
    return image_ops.gray_to_bgr(depth_uint8)


def _lineart(image: np.ndarray, params: dict | None = None) -> np.ndarray:
    """Standard lineart extraction using Gaussian blur difference."""
    gaussian_sigma = params.get("sigma", 6.0) if params else 6.0
    intensity_threshold = params.get("threshold", 8) if params else 8

    blurred = np.stack(
        [image_ops.gaussian_blur(image[..., c], sigma=gaussian_sigma) for c in range(image.shape[2])],
        axis=-1,
    )

    # Line extraction: minimum channel difference between blurred and original
    diff = np.min(blurred.astype(np.float32) - image.astype(np.float32), axis=2)

    # Normalize by median of values above threshold
    above = diff[diff > intensity_threshold]
    if len(above) > 0:
        diff = diff / np.median(above) * 127

    result = np.clip(diff, 0, 255).astype(np.uint8)
    return image_ops.gray_to_bgr(result)


def _download_lineart_model(filename: str, dest: Path):
    """Download a lineart ONNX model from R2."""
    import urllib.request

    url = f"{_MODELS_BASE_URL}/{filename}"
    log.info(f"Downloading lineart model from {url}")

    tmp_path = dest.with_suffix(".tmp")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Stimma/1.0"})
        with urllib.request.urlopen(req) as resp, open(tmp_path, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
        tmp_path.rename(dest)
        log.info(f"Lineart model saved to {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _get_lineart_realistic_session(coarse: bool = False):
    """Load lineart realistic ONNX model (singleton per variant)."""
    key = "coarse" if coarse else "fine"
    if key in _lineart_realistic_sessions:
        return _lineart_realistic_sessions[key]

    import onnxruntime as ort

    filename = f"lineart_realistic_{key}.onnx"
    model_path = _get_models_dir() / filename

    if not model_path.exists():
        log.info(f"Downloading lineart realistic ({key}) ONNX model...")
        _download_lineart_model(filename, model_path)

    log.info(f"Loading lineart realistic ({key}) model from {model_path}")
    session = ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )
    _lineart_realistic_sessions[key] = session
    return session


def _get_lineart_anime_session():
    """Load lineart anime ONNX model (singleton)."""
    global _lineart_anime_session
    if _lineart_anime_session is not None:
        return _lineart_anime_session

    import onnxruntime as ort

    filename = "lineart_anime.onnx"
    model_path = _get_models_dir() / filename

    if not model_path.exists():
        log.info("Downloading lineart anime ONNX model...")
        _download_lineart_model(filename, model_path)

    log.info(f"Loading lineart anime model from {model_path}")
    _lineart_anime_session = ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )
    return _lineart_anime_session


def _lineart_realistic(image: np.ndarray, params: dict | None = None) -> np.ndarray:
    """Realistic lineart extraction using neural network (ONNX)."""
    coarse = bool(params.get("coarse", 0)) if params else False
    session = _get_lineart_realistic_session(coarse=coarse)

    h, w = image.shape[:2]

    # Resize shortest edge to 512, dimensions rounded to multiples of 64
    scale = 512 / min(h, w)
    new_h = int(round(h * scale / 64)) * 64
    new_w = int(round(w * scale / 64)) * 64
    img_resized = image_ops.resize(image, (new_w, new_h), mode="bicubic")

    # BGR → RGB, normalize to [0,1], HWC → NCHW
    img_rgb = image_ops.bgr_to_rgb(img_resized)
    img_input = img_rgb.astype(np.float32) / 255.0
    img_input = img_input.transpose(2, 0, 1)[np.newaxis]  # NCHW

    # Run inference
    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: img_input})[0]

    # Post-process: [0,1] → [0,255], invert, resize back
    result = output.squeeze()
    result = np.clip(result * 255.0, 0, 255).astype(np.uint8)
    result = 255 - result  # invert: lines become dark on white → white on dark
    result = image_ops.resize(result, (w, h), mode="bicubic")

    return image_ops.gray_to_bgr(result)


def _lineart_anime(image: np.ndarray) -> np.ndarray:
    """Anime lineart extraction using neural network (ONNX)."""
    session = _get_lineart_anime_session()

    h, w = image.shape[:2]

    # Resize shortest edge to 512, dimensions rounded to multiples of 64
    scale = 512 / min(h, w)
    new_h = int(round(h * scale / 64)) * 64
    new_w = int(round(w * scale / 64)) * 64
    img_resized = image_ops.resize(image, (new_w, new_h), mode="bicubic")

    # Pad to multiples of 256 for the U-Net
    pad_h = (256 - new_h % 256) % 256
    pad_w = (256 - new_w % 256) % 256
    if pad_h > 0 or pad_w > 0:
        img_resized = np.pad(
            img_resized,
            ((0, pad_h), (0, pad_w), (0, 0)),
            mode="reflect",
        )

    # BGR → RGB, normalize to [-1, 1], HWC → NCHW
    img_rgb = image_ops.bgr_to_rgb(img_resized)
    img_input = img_rgb.astype(np.float32) / 127.5 - 1.0
    img_input = img_input.transpose(2, 0, 1)[np.newaxis]  # NCHW

    # Run inference
    input_name = session.get_inputs()[0].name
    output = session.run(None, {input_name: img_input})[0]

    # Post-process: [-1,1] → [0,255], crop padding, invert, resize back
    result = output.squeeze()
    result = result * 127.5 + 127.5
    result = np.clip(result, 0, 255).astype(np.uint8)

    # Remove padding
    if pad_h > 0 or pad_w > 0:
        result = result[:new_h, :new_w]

    result = 255 - result  # invert
    result = image_ops.resize(result, (w, h), mode="bicubic")

    return image_ops.gray_to_bgr(result)


def _get_dwpose():
    """Load DWPose whole-body model (singleton)."""
    global _dwpose_model
    if _dwpose_model is not None:
        return _dwpose_model

    from dwpose import Wholebody

    _dwpose_model = Wholebody(mode="balanced", device="cpu")
    return _dwpose_model


# COCO WholeBody 133 keypoint ranges
_BODY_FEET_RANGE = range(0, 23)   # body (0-16) + feet (17-22)
_FACE_RANGE = range(23, 91)       # face landmarks
_HAND_RANGE = range(91, 133)      # left hand (91-111) + right hand (112-132)


def _pose_dwpose(image: np.ndarray, include_hands: bool = False) -> np.ndarray:
    """Pose estimation using DWPose, rendered as skeleton on black background.

    Args:
        image: BGR input image
        include_hands: If True, draw hand skeletons too (pose_hands mode)
    """
    from dwpose import draw_skeleton

    model = _get_dwpose()
    keypoints, scores = model(image)

    # Black background
    canvas = np.zeros_like(image)

    if keypoints is not None and len(keypoints) > 0:
        # Mask out unwanted keypoints by zeroing their scores
        masked_scores = scores.copy()
        # Always hide face keypoints
        masked_scores[:, list(_FACE_RANGE)] = 0.0
        # Hide hand keypoints unless include_hands is True
        if not include_hands:
            masked_scores[:, list(_HAND_RANGE)] = 0.0

        canvas = draw_skeleton(
            canvas,
            keypoints,
            masked_scores,
            kpt_thr=0.3,
            radius=3,
            line_width=2,
        )

    return canvas


def _pose(image: np.ndarray) -> np.ndarray:
    """Pose estimation (body only, no hands/face)."""
    return _pose_dwpose(image, include_hands=False)


def _pose_hands(image: np.ndarray) -> np.ndarray:
    """Pose estimation with hand skeletons."""
    return _pose_dwpose(image, include_hands=True)


# Dispatcher
_PROCESSORS = {
    "canny": _canny,
    "depth": _depth,
    "lineart": _lineart,
    "lineart_realistic": _lineart_realistic,
    "lineart_anime": _lineart_anime,
    "pose": _pose,
    "pose_hands": _pose_hands,
}


def _preprocess_sync(image_path: str, preprocessor: str, params: dict | None = None) -> tuple[str, int, int]:
    """
    Synchronous preprocessing with caching.

    Returns (output_path, width, height).
    """
    if preprocessor not in _PROCESSORS:
        raise ValueError(f"Unknown preprocessor: {preprocessor}. Available: {sorted(PREPROCESSORS)}")

    # Check cache — include params in key so different settings produce different files
    fhash = _file_hash(image_path)
    cache_dir = _get_cache_dir()
    params_suffix = ""
    if params:
        params_suffix = "_" + "_".join(f"{k}{v}" for k, v in sorted(params.items()))

    if preprocessor == "depth":
        model_filename, _ = _get_depth_anything_config()
        model_tag = Path(model_filename).stem
        params_suffix += f"_{model_tag}"

    cache_path = cache_dir / f"{fhash}_{preprocessor}{params_suffix}_v3.png"

    if cache_path.exists():
        # Read dimensions from cached file
        img = image_ops.imread_bgr(str(cache_path))
        if img is not None:
            h, w = img.shape[:2]
            return str(cache_path), w, h

    # Load and process
    image = _load_image(image_path)
    processor_fn = _PROCESSORS[preprocessor]
    if params and preprocessor in ("canny", "lineart", "lineart_realistic"):
        result = processor_fn(image, params)
    else:
        result = processor_fn(image)

    # Save to cache
    image_ops.imwrite_bgr(str(cache_path), result)
    h, w = result.shape[:2]

    log.info(f"Preprocessed {preprocessor}: {image_path} -> {cache_path} ({w}x{h})")
    return str(cache_path), w, h


async def preprocess(image_path: str, preprocessor: str, params: dict | None = None) -> tuple[str, int, int]:
    """
    Async wrapper for preprocessing. Runs in thread pool.

    Returns (output_path, width, height).
    """
    import asyncio
    from functools import partial

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, partial(_preprocess_sync, image_path, preprocessor, params)
    )

"""Legacy cv2 reference implementations for one-time parity validation."""

from __future__ import annotations

import cv2
import numpy as np


ARCFACE_REF_LANDMARKS = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def canny_bgr(image_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    high_thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    low_thresh = max(1, int(high_thresh * 0.5))
    edges = cv2.Canny(gray, low_thresh, high_thresh)
    return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)


def lineart_bgr(image_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    lines = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, kernel)
    return cv2.cvtColor(lines, cv2.COLOR_GRAY2BGR)


def depth_postprocess_bgr(depth: np.ndarray, width: int, height: int) -> np.ndarray:
    resized = cv2.resize(depth, (width, height), interpolation=cv2.INTER_CUBIC)
    d_min = resized.min()
    d_max = resized.max()
    if d_max - d_min > 0:
        resized = (resized - d_min) / (d_max - d_min)
    else:
        resized = np.zeros_like(resized)
    depth_u8 = (resized * 255).astype(np.uint8)
    return cv2.applyColorMap(depth_u8, cv2.COLORMAP_INFERNO)


def align_face_bgr(image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    src_pts = landmarks.astype(np.float32)
    dst_pts = ARCFACE_REF_LANDMARKS.astype(np.float32)
    transform = estimate_affine_matrix(src_pts, dst_pts)
    if transform is None:
        x1, y1, x2, y2 = (
            int(src_pts[:, 0].min()),
            int(src_pts[:, 1].min()),
            int(src_pts[:, 0].max()),
            int(src_pts[:, 1].max()),
        )
        margin = max(x2 - x1, y2 - y1) // 2
        x1 = max(0, x1 - margin)
        y1 = max(0, y1 - margin)
        x2 = min(image_bgr.shape[1], x2 + margin)
        y2 = min(image_bgr.shape[0], y2 + margin)
        face = image_bgr[y1:y2, x1:x2]
        return cv2.resize(face, (112, 112))
    return cv2.warpAffine(image_bgr, transform, (112, 112))


def estimate_affine_matrix(src_pts: np.ndarray, dst_pts: np.ndarray) -> np.ndarray | None:
    transform, _ = cv2.estimateAffinePartial2D(src_pts.astype(np.float32), dst_pts.astype(np.float32))
    return transform

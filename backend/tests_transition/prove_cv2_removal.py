"""One-shot parity proof: cv2 reference vs runtime image_ops path."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from utils import image_ops

try:
    from tests_transition import cv2_reference
except ModuleNotFoundError as exc:
    raise SystemExit(
        "cv2 parity reference is unavailable. Run with optional extra:\n"
        "  uv run --extra cv2-parity python tests_transition/prove_cv2_removal.py"
    ) from exc


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2)
    if mse == 0:
        return 99.0
    return 20.0 * math.log10(255.0 / math.sqrt(mse))


def binary_iou(a: np.ndarray, b: np.ndarray) -> float:
    a1 = a > 0
    b1 = b > 0
    inter = np.logical_and(a1, b1).sum()
    union = np.logical_or(a1, b1).sum()
    return float(inter / union) if union > 0 else 1.0


def _dilate_binary(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    if radius <= 0:
        return mask.astype(bool)
    h, w = mask.shape
    out = np.zeros_like(mask, dtype=bool)
    padded = np.pad(mask.astype(bool), ((radius, radius), (radius, radius)), mode="constant")
    k = 2 * radius + 1
    for y in range(h):
        for x in range(w):
            out[y, x] = np.any(padded[y : y + k, x : x + k])
    return out


def tolerant_edge_f1(ref: np.ndarray, new: np.ndarray, radius: int = 1) -> float:
    ref_b = ref > 0
    new_b = new > 0
    ref_d = _dilate_binary(ref_b, radius)
    new_d = _dilate_binary(new_b, radius)
    tp_prec = np.logical_and(new_b, ref_d).sum()
    tp_rec = np.logical_and(ref_b, new_d).sum()
    precision = tp_prec / max(1, new_b.sum())
    recall = tp_rec / max(1, ref_b.sum())
    denom = precision + recall
    return float((2.0 * precision * recall) / denom) if denom > 0 else 1.0


def edge_density_delta(ref: np.ndarray, new: np.ndarray) -> float:
    ref_density = float((ref > 0).mean())
    new_density = float((new > 0).mean())
    return abs(new_density - ref_density) / max(ref_density, 1e-6)


def apply_affine_to_points(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    ones = np.ones((points.shape[0], 1), dtype=np.float32)
    homo = np.concatenate([points.astype(np.float32), ones], axis=1)
    return (matrix @ homo.T).T


def synthetic_corpus(n: int = 20) -> list[np.ndarray]:
    rng = np.random.default_rng(1337)
    out = []
    for _ in range(n):
        h = int(rng.integers(256, 640))
        w = int(rng.integers(256, 640))
        img = np.zeros((h, w, 3), dtype=np.uint8)
        gx = np.linspace(0, 255, w, dtype=np.uint8)
        gy = np.linspace(0, 255, h, dtype=np.uint8)
        img[:, :, 2] = gx[np.newaxis, :]
        img[:, :, 1] = gy[:, np.newaxis]
        noise = rng.integers(0, 64, size=(h, w, 3), dtype=np.uint8)
        img = np.clip(img + noise, 0, 255).astype(np.uint8)
        for _ in range(12):
            x1, y1 = int(rng.integers(0, w)), int(rng.integers(0, h))
            x2, y2 = int(rng.integers(0, w)), int(rng.integers(0, h))
            color = rng.integers(0, 255, size=(3,), dtype=np.uint8)
            rr = np.linspace(y1, y2, 300).astype(int).clip(0, h - 1)
            cc = np.linspace(x1, x2, 300).astype(int).clip(0, w - 1)
            img[rr, cc] = color
        out.append(img)
    return out


def new_canny(image: np.ndarray) -> np.ndarray:
    gray = image_ops.bgr_to_gray(image)
    high = image_ops.threshold_otsu(gray)
    low = max(1, int(high * 0.5))
    edges = image_ops.canny(gray, low, high)
    return image_ops.gray_to_bgr(edges)


def new_lineart(image: np.ndarray) -> np.ndarray:
    gray = image_ops.bgr_to_gray(image)
    gray = image_ops.bilateral_like_filter(gray)
    lines = image_ops.adaptive_threshold_gaussian(gray, 255, 11, 2)
    lines = image_ops.morphology_close(lines, image_ops.ellipse_kernel((2, 2)))
    return image_ops.gray_to_bgr(lines)


def new_depth_post(depth: np.ndarray, width: int, height: int) -> np.ndarray:
    d = image_ops.resize(depth.astype(np.float32), (width, height), mode="bicubic")
    d_min = d.min()
    d_max = d.max()
    if d_max - d_min > 0:
        d = (d - d_min) / (d_max - d_min)
    else:
        d = np.zeros_like(d)
    return image_ops.apply_colormap_inferno((d * 255).astype(np.uint8))


def scan_banned_dylibs(main_dist: Path) -> list[str]:
    banned = (
        "cv2",
        "libavcodec",
        "libavformat",
        "libavdevice",
        "libavfilter",
        "libx264",
        "libx265",
        "libvpx",
        "libSvtAv1Enc",
        "librav1e",
        "libbluray",
        "libtheora",
    )
    found: list[str] = []
    for p in main_dist.glob("*.dylib"):
        if any(tag in p.name for tag in banned):
            found.append(p.name)
    for p in main_dist.glob("*.so"):
        if any(tag in p.name for tag in banned):
            found.append(p.name)
    for p in main_dist.rglob("cv2/*"):
        if p.is_file():
            found.append(str(p.relative_to(main_dist)))
    return sorted(set(found))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="tests_transition/reports/cv2_parity_report.json")
    ap.add_argument("--main-dist", default="", help="Optional main.dist path for banned dylib scan.")
    args = ap.parse_args()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    corpus = synthetic_corpus(20)
    rng = np.random.default_rng(2026)

    canny_iou: list[float] = []
    canny_f1_tolerant: list[float] = []
    canny_density_delta: list[float] = []
    line_f1_tolerant: list[float] = []
    line_density_delta: list[float] = []
    depth_psnr: list[float] = []
    align_ref_rmse: list[float] = []
    align_new_rmse: list[float] = []

    for image in corpus:
        ref_c = cv2_reference.canny_bgr(image)
        new_c = new_canny(image)
        canny_iou.append(binary_iou(ref_c[:, :, 0], new_c[:, :, 0]))
        canny_f1_tolerant.append(tolerant_edge_f1(ref_c[:, :, 0], new_c[:, :, 0], radius=3))
        canny_density_delta.append(edge_density_delta(ref_c[:, :, 0], new_c[:, :, 0]))

        ref_l = cv2_reference.lineart_bgr(image)
        new_l = new_lineart(image)
        line_f1_tolerant.append(tolerant_edge_f1(ref_l[:, :, 0], new_l[:, :, 0], radius=1))
        line_density_delta.append(edge_density_delta(ref_l[:, :, 0], new_l[:, :, 0]))

        depth_map = rng.normal(loc=0.0, scale=1.0, size=(64, 64)).astype(np.float32)
        ref_d = cv2_reference.depth_postprocess_bgr(depth_map, image.shape[1], image.shape[0])
        new_d = new_depth_post(depth_map, image.shape[1], image.shape[0])
        depth_psnr.append(psnr(ref_d, new_d))

        h, w = image.shape[:2]
        cx, cy = w / 2.0, h / 2.0
        src = np.array(
            [
                [cx - 30, cy - 20],
                [cx + 30, cy - 20],
                [cx, cy + 0],
                [cx - 20, cy + 25],
                [cx + 20, cy + 25],
            ],
            dtype=np.float32,
        )
        dst = cv2_reference.ARCFACE_REF_LANDMARKS.astype(np.float32)
        ref_m = cv2_reference.estimate_affine_matrix(src, dst)
        new_m = image_ops.estimate_affine(src, dst)
        if ref_m is None or new_m is None:
            align_ref_rmse.append(999.0)
            align_new_rmse.append(999.0)
        else:
            ref_pts = apply_affine_to_points(ref_m.astype(np.float32), src)
            new_pts = apply_affine_to_points(new_m.astype(np.float32), src)
            align_ref_rmse.append(float(np.sqrt(np.mean((ref_pts - dst) ** 2))))
            align_new_rmse.append(float(np.sqrt(np.mean((new_pts - dst) ** 2))))

    summary = {
        "canny_iou_mean": float(np.mean(canny_iou)),
        "canny_f1_tolerant_mean": float(np.mean(canny_f1_tolerant)),
        "canny_density_delta_mean": float(np.mean(canny_density_delta)),
        "lineart_f1_tolerant_mean": float(np.mean(line_f1_tolerant)),
        "lineart_density_delta_mean": float(np.mean(line_density_delta)),
        "depth_psnr_mean": float(np.mean(depth_psnr)),
        "face_landmark_rmse_ref_mean": float(np.mean(align_ref_rmse)),
        "face_landmark_rmse_new_mean": float(np.mean(align_new_rmse)),
        "face_landmark_rmse_delta_mean": float(np.mean(np.array(align_new_rmse) - np.array(align_ref_rmse))),
    }

    thresholds = {
        "canny_iou_mean": 0.12,
        "canny_f1_tolerant_mean": 0.50,
        "canny_density_delta_mean": 0.85,
        "lineart_f1_tolerant_mean": 0.62,
        "lineart_density_delta_mean": 0.70,
        "depth_psnr_mean": 20.0,
        "face_landmark_rmse_new_mean": 6.0,
        "face_landmark_rmse_delta_mean": 2.0,
    }

    failures: list[str] = []
    for key, limit in thresholds.items():
        value = summary[key]
        if key.endswith("_delta_mean") or "_rmse_" in key:
            if value > limit:
                failures.append(f"{key}: got={value:.4f}, max={limit:.4f}")
        elif value < limit:
            failures.append(f"{key}: got={value:.4f}, min={limit:.4f}")

    dylib_hits: list[str] = []
    if args.main_dist:
        dylib_hits = scan_banned_dylibs(Path(args.main_dist))
        if dylib_hits:
            failures.append(f"banned_dylibs_present: {dylib_hits}")

    payload = {
        "summary": summary,
        "thresholds": thresholds,
        "failures": failures,
        "banned_dylibs": dylib_hits,
    }
    report_path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""DWPose runtime: YOLOX person detector + RTMW pose estimator.

Pure-Python port of rtmlib's Wholebody pipeline. Reuses the same upstream
ONNX model files but performs all preprocessing (resize, affine warp) and
postprocessing (NMS, simcc decode) in numpy + PIL — no cv2 dependency.
"""

import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Tuple

import numpy as np
import onnxruntime as ort

import app_dirs
from core.logging import get_logger
from utils import image_ops

log = get_logger(__name__)


_MODES = {
    "performance": {
        "det_url": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip",
        "det_input_size": (640, 640),
        "pose_url": "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-384x288_20231122.zip",
        "pose_input_size": (288, 384),
    },
    "lightweight": {
        "det_url": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_tiny_8xb8-300e_humanart-6f3252f9.zip",
        "det_input_size": (416, 416),
        "pose_url": "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122.zip",
        "pose_input_size": (192, 256),
    },
    "balanced": {
        "det_url": "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip",
        "det_input_size": (640, 640),
        "pose_url": "https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-256x192_20231122.zip",
        "pose_input_size": (192, 256),
    },
}

_RTMLIB_LEGACY_CACHE = Path.home() / ".cache" / "rtmlib" / "hub" / "checkpoints"


def _models_dir() -> Path:
    d = app_dirs.get_cache_dir() / "models" / "dwpose"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_model(url: str) -> Path:
    """Return a local path to the .onnx file referenced by `url`, downloading
    and extracting if needed.

    rtmlib historically caches the same files under ~/.cache/rtmlib/hub/...;
    we honor that path so existing installs don't re-download.
    """
    base = os.path.basename(url)
    stem = base.rsplit(".", 1)[0]  # strip .zip
    onnx_name = f"{stem}.onnx"

    primary = _models_dir() / onnx_name
    if primary.exists():
        return primary

    legacy = _RTMLIB_LEGACY_CACHE / onnx_name
    if legacy.exists():
        return legacy

    log.info(f"Downloading DWPose model: {url}")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / base
        req = urllib.request.Request(url, headers={"User-Agent": "Stimma/1.0"})
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.namelist() if m.endswith("end2end.onnx")]
            if not members:
                raise RuntimeError(f"DWPose archive missing end2end.onnx: {url}")
            with zf.open(members[0]) as src, open(primary, "wb") as dst:
                shutil.copyfileobj(src, dst)

    log.info(f"DWPose model installed at {primary}")
    return primary


def _make_session(onnx_path: Path) -> ort.InferenceSession:
    return ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])


def _nms(boxes: np.ndarray, scores: np.ndarray, nms_thr: float) -> list:
    """Single-class NMS in numpy (matches rtmlib)."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(ovr <= nms_thr)[0]
        order = order[inds + 1]
    return keep


def _multiclass_nms(boxes: np.ndarray, scores: np.ndarray, nms_thr: float, score_thr: float):
    final_dets = []
    num_classes = scores.shape[1]
    for cls_ind in range(num_classes):
        cls_scores = scores[:, cls_ind]
        valid = cls_scores > score_thr
        if not valid.any():
            continue
        valid_scores = cls_scores[valid]
        valid_boxes = boxes[valid]
        keep = _nms(valid_boxes, valid_scores, nms_thr)
        if keep:
            cls_inds = np.ones((len(keep), 1)) * cls_ind
            dets = np.concatenate(
                [valid_boxes[keep], valid_scores[keep, None], cls_inds], axis=1
            )
            final_dets.append(dets)
    if not final_dets:
        return None
    return np.concatenate(final_dets, axis=0)


class _YOLOX:
    def __init__(self, onnx_path: Path, input_size: Tuple[int, int],
                 nms_thr: float = 0.45, score_thr: float = 0.7):
        self.session = _make_session(onnx_path)
        self.input_size = input_size  # (H, W)
        self.nms_thr = nms_thr
        self.score_thr = score_thr

    def __call__(self, image: np.ndarray) -> np.ndarray:
        padded, ratio = self._preprocess(image)
        outputs = self._inference(padded)[0]
        return self._postprocess(outputs, ratio)

    def _preprocess(self, img: np.ndarray) -> Tuple[np.ndarray, float]:
        h_in, w_in = self.input_size
        if img.ndim == 3:
            padded = np.full((h_in, w_in, 3), 114, dtype=np.uint8)
        else:
            padded = np.full((h_in, w_in), 114, dtype=np.uint8)

        ratio = min(h_in / img.shape[0], w_in / img.shape[1])
        new_w = int(img.shape[1] * ratio)
        new_h = int(img.shape[0] * ratio)
        resized = image_ops.resize(img, (new_w, new_h), mode="bilinear").astype(np.uint8)
        padded[:new_h, :new_w] = resized
        return padded, ratio

    def _inference(self, img: np.ndarray):
        chw = img.transpose(2, 0, 1) if img.ndim == 3 else img[None, :, :]
        x = np.ascontiguousarray(chw, dtype=np.float32)[None, ...]
        feed = {self.session.get_inputs()[0].name: x}
        return self.session.run(None, feed)

    def _postprocess(self, outputs: np.ndarray, ratio: float) -> np.ndarray:
        h_in, w_in = self.input_size
        if outputs.shape[-1] == 4:
            grids, expanded_strides = [], []
            strides = [8, 16, 32]
            hsizes = [h_in // s for s in strides]
            wsizes = [w_in // s for s in strides]
            for hsize, wsize, stride in zip(hsizes, wsizes, strides):
                xv, yv = np.meshgrid(np.arange(wsize), np.arange(hsize))
                grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
                grids.append(grid)
                expanded_strides.append(np.full((*grid.shape[:2], 1), stride))

            grids = np.concatenate(grids, axis=1)
            expanded_strides = np.concatenate(expanded_strides, axis=1)
            outputs[..., :2] = (outputs[..., :2] + grids) * expanded_strides
            outputs[..., 2:4] = np.exp(outputs[..., 2:4]) * expanded_strides

            preds = outputs[0]
            boxes = preds[:, :4]
            scores = preds[:, 4:5] * preds[:, 5:]

            boxes_xyxy = np.empty_like(boxes)
            boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
            boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
            boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
            boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
            boxes_xyxy /= ratio

            dets = _multiclass_nms(boxes_xyxy, scores, self.nms_thr, self.score_thr)
            if dets is None:
                return np.zeros((0, 4), dtype=np.float32)

            final_boxes, final_scores, final_cls = dets[:, :4], dets[:, 4], dets[:, 5]
            mask = (final_scores > 0.3) & (final_cls == 0)
            return final_boxes[mask]

        if outputs.shape[-1] == 5:
            final_boxes = outputs[0, :, :4]
            final_scores = outputs[0, :, 4]
            final_boxes = final_boxes / ratio
            return final_boxes[final_scores > 0.3]

        raise RuntimeError(f"Unexpected YOLOX output shape: {outputs.shape}")


# RTMPose normalization constants (ImageNet stats * 255).
_RTMPOSE_MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
_RTMPOSE_STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)


def _affine_3pts(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Equivalent of cv2.getAffineTransform: solves the 2x3 affine M such
    that M @ [x, y, 1].T = [x', y'].T for each row of (src, dst).
    """
    A = np.hstack([src.astype(np.float64), np.ones((3, 1), dtype=np.float64)])
    M_T = np.linalg.solve(A, dst.astype(np.float64))  # (3, 2)
    return M_T.T.astype(np.float32)


def _rotate_point(pt: np.ndarray, angle_rad: float) -> np.ndarray:
    sn, cs = np.sin(angle_rad), np.cos(angle_rad)
    return np.array([cs * pt[0] - sn * pt[1], sn * pt[0] + cs * pt[1]], dtype=np.float32)


def _third_point(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    direction = a - b
    return b + np.array([-direction[1], direction[0]], dtype=np.float32)


def _warp_matrix(center: np.ndarray, scale: np.ndarray, output_size: Tuple[int, int]) -> np.ndarray:
    """Build the affine matrix that warps the bbox region (center, scale) in
    the input image to the model input rectangle.
    """
    src_w = float(scale[0])
    dst_w, dst_h = float(output_size[0]), float(output_size[1])

    src_dir = _rotate_point(np.array([0.0, src_w * -0.5]), 0.0)
    dst_dir = np.array([0.0, dst_w * -0.5], dtype=np.float32)

    src = np.zeros((3, 2), dtype=np.float32)
    src[0] = center
    src[1] = center + src_dir
    src[2] = _third_point(src[0], src[1])

    dst = np.zeros((3, 2), dtype=np.float32)
    dst[0] = [dst_w * 0.5, dst_h * 0.5]
    dst[1] = np.array([dst_w * 0.5, dst_h * 0.5]) + dst_dir
    dst[2] = _third_point(dst[0], dst[1])

    return _affine_3pts(src, dst)


def _bbox_to_center_scale(bbox: np.ndarray, padding: float = 1.25) -> Tuple[np.ndarray, np.ndarray]:
    x1, y1, x2, y2 = bbox
    center = np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float32)
    scale = np.array([(x2 - x1) * padding, (y2 - y1) * padding], dtype=np.float32)
    return center, scale


def _top_down_affine(input_size: Tuple[int, int], scale: np.ndarray, center: np.ndarray,
                     img: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    w, h = input_size
    aspect = w / h
    if scale[0] > scale[1] * aspect:
        scale = np.array([scale[0], scale[0] / aspect], dtype=np.float32)
    else:
        scale = np.array([scale[1] * aspect, scale[1]], dtype=np.float32)

    matrix = _warp_matrix(center, scale, (w, h))
    warped = image_ops.warp_affine(img, matrix, (int(w), int(h)))
    return warped, scale


def _simcc_argmax(simcc_x: np.ndarray, simcc_y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    N, K, _ = simcc_x.shape
    sx = simcc_x.reshape(N * K, -1)
    sy = simcc_y.reshape(N * K, -1)
    x_locs = np.argmax(sx, axis=1)
    y_locs = np.argmax(sy, axis=1)
    locs = np.stack([x_locs, y_locs], axis=-1).astype(np.float32)
    vx = np.amax(sx, axis=1)
    vy = np.amax(sy, axis=1)
    vals = 0.5 * (vx + vy)
    locs[vals <= 0.0] = -1
    return locs.reshape(N, K, 2), vals.reshape(N, K)


class _RTMPose:
    def __init__(self, onnx_path: Path, input_size: Tuple[int, int]):
        self.session = _make_session(onnx_path)
        self.input_size = input_size  # (W, H)

    def __call__(self, image: np.ndarray, bboxes: np.ndarray):
        if len(bboxes) == 0:
            bboxes = np.array([[0, 0, image.shape[1], image.shape[0]]], dtype=np.float32)

        all_kpts, all_scores = [], []
        for bbox in bboxes:
            warped, center, scale = self._preprocess(image, bbox)
            outputs = self._inference(warped)
            kpts, scores = self._postprocess(outputs, center, scale)
            all_kpts.append(kpts)
            all_scores.append(scores)

        return np.concatenate(all_kpts, axis=0), np.concatenate(all_scores, axis=0)

    def _preprocess(self, img: np.ndarray, bbox: np.ndarray):
        center, scale = _bbox_to_center_scale(np.asarray(bbox), padding=1.25)
        warped, scale = _top_down_affine(self.input_size, scale, center, img)
        warped = (warped.astype(np.float32) - _RTMPOSE_MEAN) / _RTMPOSE_STD
        return warped, center, scale

    def _inference(self, img: np.ndarray):
        chw = np.ascontiguousarray(img.transpose(2, 0, 1), dtype=np.float32)
        x = chw[None, ...]
        feed = {self.session.get_inputs()[0].name: x}
        names = [out.name for out in self.session.get_outputs()]
        return self.session.run(names, feed)

    def _postprocess(self, outputs, center: np.ndarray, scale: np.ndarray):
        simcc_x, simcc_y = outputs
        locs, scores = _simcc_argmax(simcc_x, simcc_y)
        keypoints = locs / 2.0  # simcc_split_ratio
        w, h = self.input_size
        keypoints = keypoints / np.array([w, h], dtype=np.float32) * scale
        keypoints = keypoints + center - scale / 2.0
        return keypoints, scores


class Wholebody:
    """Drop-in replacement for rtmlib.Wholebody. Loads YOLOX (person detector)
    and RTMW (133-keypoint pose) ONNX models.
    """

    def __init__(self, mode: str = "balanced", device: str = "cpu", to_openpose: bool = False):
        if to_openpose:
            raise NotImplementedError("openpose-style output not implemented")
        if device != "cpu":
            log.warning(f"Wholebody: ignoring device={device!r}, using onnxruntime defaults")
        if mode not in _MODES:
            raise ValueError(f"Unknown mode {mode!r}; expected one of {list(_MODES)}")

        cfg = _MODES[mode]
        log.info(f"Loading DWPose ({mode})...")
        det_path = _resolve_model(cfg["det_url"])
        pose_path = _resolve_model(cfg["pose_url"])
        self.detector = _YOLOX(det_path, cfg["det_input_size"])
        self.pose = _RTMPose(pose_path, cfg["pose_input_size"])
        log.info("DWPose loaded")

    def __call__(self, image: np.ndarray):
        bboxes = self.detector(image)
        return self.pose(image, bboxes)

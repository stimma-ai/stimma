"""
Lightweight ONNX-based face detection and recognition.

Replaces insightface with direct ONNX inference for:
- SCRFD: Face detection with 5-point landmarks
- AuraFace/ArcFace: Face embedding extraction
"""

import numpy as np
import onnxruntime as ort
from dataclasses import dataclass
from typing import List, Tuple, Optional
from core.logging import get_logger
from utils import image_ops

log = get_logger(__name__)


@dataclass
class Face:
    """Detected face with bbox, landmarks, confidence, and optional embedding."""
    bbox: np.ndarray  # [x1, y1, x2, y2] in pixel coordinates
    landmarks: np.ndarray  # 5 points: [[x, y], ...] in pixel coordinates
    confidence: float
    embedding: Optional[np.ndarray] = None  # 512-dim normalized embedding


# Standard ArcFace alignment reference landmarks (for 112x112 output)
ARCFACE_REF_LANDMARKS = np.array([
    [38.2946, 51.6963],   # left eye
    [73.5318, 51.5014],   # right eye
    [56.0252, 71.7366],   # nose
    [41.5493, 92.3655],   # left mouth corner
    [70.7299, 92.2041],   # right mouth corner
], dtype=np.float32)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float = 0.4) -> List[int]:
    """Non-maximum suppression for face detection."""
    if len(boxes) == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)

    order = scores.argsort()[::-1]
    keep = []

    while len(order) > 0:
        i = order[0]
        keep.append(i)

        if len(order) == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h

        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """Convert distance predictions to bounding boxes."""
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """Convert distance predictions to keypoints."""
    # distance shape: [N, 10] for 5 keypoints * 2 coords
    kps = []
    for i in range(5):
        px = points[:, 0] + distance[:, i * 2]
        py = points[:, 1] + distance[:, i * 2 + 1]
        kps.append(np.stack([px, py], axis=-1))
    return np.stack(kps, axis=1)  # [N, 5, 2]


class SCRFDDetector:
    """SCRFD face detector with 5-point landmarks."""

    def __init__(self, model_path: str, providers: List[str]):
        """
        Initialize SCRFD detector.

        Args:
            model_path: Path to scrfd_10g_bnkps.onnx
            providers: ONNX Runtime execution providers
        """
        log.info(f"Loading SCRFD detector from {model_path}")
        self.session = ort.InferenceSession(model_path, providers=providers)

        # Get model input info
        input_info = self.session.get_inputs()[0]
        self.input_name = input_info.name
        self.input_shape = input_info.shape  # [1, 3, H, W]

        # Detection parameters - SCRFD uses strides 8, 16, 32
        self.strides = [8, 16, 32]
        self.det_size = (640, 640)  # Standard detection size

        log.info(f"SCRFD detector loaded: input={self.input_name}, shape={self.input_shape}")

    def _preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """
        Preprocess image for SCRFD.

        Args:
            image: BGR image (H, W, 3)

        Returns:
            - Preprocessed tensor (1, 3, 640, 640)
            - Scale factor used
            - Original image size (height, width)
        """
        input_height, input_width = self.det_size
        img_height, img_width = image.shape[:2]

        # Calculate scale to fit image in det_size while preserving aspect ratio
        scale = min(input_width / img_width, input_height / img_height)
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        # Resize image
        resized = image_ops.resize(image, (new_width, new_height), mode="bilinear")

        # Create padded image (pad with zeros)
        padded = np.zeros((input_height, input_width, 3), dtype=np.float32)
        padded[:new_height, :new_width, :] = resized

        # Normalize: (x - 127.5) / 128.0
        padded = (padded - 127.5) / 128.0

        # Convert to NCHW format
        tensor = padded.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)

        return tensor, scale, (img_height, img_width)

    def _postprocess(
        self,
        outputs: List[np.ndarray],
        scale: float,
        original_size: Tuple[int, int],
        conf_threshold: float
    ) -> List[Face]:
        """
        Postprocess SCRFD outputs.

        Args:
            outputs: Model outputs grouped by type:
                - outputs[0:3]: scores for stride 8, 16, 32
                - outputs[3:6]: bboxes for stride 8, 16, 32
                - outputs[6:9]: keypoints for stride 8, 16, 32
            scale: Scale factor used in preprocessing
            original_size: Original image size (height, width)
            conf_threshold: Confidence threshold

        Returns:
            List of Face objects
        """
        input_height, input_width = self.det_size
        num_strides = len(self.strides)

        all_scores = []
        all_bboxes = []
        all_kps = []

        for idx, stride in enumerate(self.strides):
            # Calculate feature map size
            fmc_height = input_height // stride
            fmc_width = input_width // stride

            # Get outputs for this stride (grouped by type, not interleaved)
            scores_out = outputs[idx]                    # scores
            bbox_out = outputs[num_strides + idx]        # bboxes
            kps_out = outputs[2 * num_strides + idx]     # keypoints

            # Reshape outputs
            scores = scores_out.reshape(-1)
            bbox_preds = bbox_out.reshape(-1, 4)
            kps_preds = kps_out.reshape(-1, 10)

            # Generate anchor centers
            # SCRFD uses 2 anchors per location
            num_anchors = 2
            anchor_centers = []
            for y in range(fmc_height):
                for x in range(fmc_width):
                    for _ in range(num_anchors):
                        anchor_centers.append([x * stride, y * stride])
            anchor_centers = np.array(anchor_centers, dtype=np.float32)

            # Filter by confidence
            pos_inds = np.where(scores >= conf_threshold)[0]
            if len(pos_inds) == 0:
                continue

            pos_scores = scores[pos_inds]
            pos_bboxes = bbox_preds[pos_inds] * stride
            pos_kps = kps_preds[pos_inds] * stride
            pos_centers = anchor_centers[pos_inds]

            # Convert to absolute coordinates
            bboxes = _distance2bbox(pos_centers, pos_bboxes)
            kps = _distance2kps(pos_centers, pos_kps)

            all_scores.append(pos_scores)
            all_bboxes.append(bboxes)
            all_kps.append(kps)

        if len(all_scores) == 0:
            return []

        # Concatenate all detections
        all_scores = np.concatenate(all_scores)
        all_bboxes = np.concatenate(all_bboxes)
        all_kps = np.concatenate(all_kps)

        # Apply NMS
        keep = _nms(all_bboxes, all_scores, iou_threshold=0.4)

        # Create Face objects
        faces = []
        for idx in keep:
            # Scale back to original image coordinates
            bbox = all_bboxes[idx] / scale
            kps = all_kps[idx] / scale

            # Clip to image bounds
            img_h, img_w = original_size
            bbox[0] = max(0, min(bbox[0], img_w))
            bbox[1] = max(0, min(bbox[1], img_h))
            bbox[2] = max(0, min(bbox[2], img_w))
            bbox[3] = max(0, min(bbox[3], img_h))

            faces.append(Face(
                bbox=bbox,
                landmarks=kps,
                confidence=float(all_scores[idx])
            ))

        return faces

    def detect(self, image: np.ndarray, conf_threshold: float = 0.5) -> List[Face]:
        """
        Detect faces in image.

        Args:
            image: BGR image (H, W, 3)
            conf_threshold: Minimum confidence threshold

        Returns:
            List of Face objects with bbox, landmarks, and confidence
        """
        # Preprocess
        tensor, scale, original_size = self._preprocess(image)

        # Run inference
        outputs = self.session.run(None, {self.input_name: tensor})

        # Postprocess
        faces = self._postprocess(outputs, scale, original_size, conf_threshold)

        return faces


class AuraFaceRecognizer:
    """AuraFace/ArcFace embedding extractor."""

    def __init__(self, model_path: str, providers: List[str]):
        """
        Initialize AuraFace recognizer.

        Args:
            model_path: Path to glintr100.onnx
            providers: ONNX Runtime execution providers
        """
        log.info(f"Loading AuraFace recognizer from {model_path}")
        self.session = ort.InferenceSession(model_path, providers=providers)

        # Get model input info
        input_info = self.session.get_inputs()[0]
        self.input_name = input_info.name
        self.input_shape = input_info.shape  # [1, 3, 112, 112]

        log.info(f"AuraFace recognizer loaded: input={self.input_name}, shape={self.input_shape}")

    def _align_face(self, image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        """
        Align face using 5-point landmarks.

        Args:
            image: BGR image
            landmarks: 5 landmarks [[x, y], ...]

        Returns:
            Aligned face image (112, 112, 3)
        """
        # Compute affine transform from source landmarks to reference
        src_pts = landmarks.astype(np.float32)
        dst_pts = ARCFACE_REF_LANDMARKS.astype(np.float32)

        # Estimate affine transform from landmarks.
        transform = image_ops.estimate_affine(src_pts, dst_pts)

        if transform is None:
            # Fallback: simple crop and resize
            x1, y1, x2, y2 = (
                int(landmarks[:, 0].min()),
                int(landmarks[:, 1].min()),
                int(landmarks[:, 0].max()),
                int(landmarks[:, 1].max())
            )
            # Expand bbox
            margin = max(x2 - x1, y2 - y1) // 2
            x1 = max(0, x1 - margin)
            y1 = max(0, y1 - margin)
            x2 = min(image.shape[1], x2 + margin)
            y2 = min(image.shape[0], y2 + margin)
            face = image[y1:y2, x1:x2]
            return image_ops.resize(face, (112, 112), mode="bilinear")

        # Apply affine transform
        aligned = image_ops.warp_affine(image, transform, (112, 112))
        return aligned

    def _preprocess(self, aligned_face: np.ndarray) -> np.ndarray:
        """
        Preprocess aligned face for embedding extraction.

        Args:
            aligned_face: Aligned face image (112, 112, 3) BGR

        Returns:
            Preprocessed tensor (1, 3, 112, 112)
        """
        # Convert BGR to RGB
        face_rgb = aligned_face[:, :, ::-1].copy()

        # Normalize to [-1, 1] range (standard ArcFace normalization)
        face_norm = (face_rgb.astype(np.float32) - 127.5) / 127.5

        # Convert to NCHW format
        tensor = face_norm.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)

        return tensor

    def get_embedding(self, image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        """
        Extract face embedding.

        Args:
            image: BGR image containing the face
            landmarks: 5-point landmarks [[x, y], ...]

        Returns:
            512-dim normalized embedding
        """
        # Align face
        aligned = self._align_face(image, landmarks)

        # Preprocess
        tensor = self._preprocess(aligned)

        # Run inference
        outputs = self.session.run(None, {self.input_name: tensor})
        embedding = outputs[0][0]  # [512]

        # Normalize embedding
        embedding = embedding / np.linalg.norm(embedding)

        return embedding.astype(np.float32)

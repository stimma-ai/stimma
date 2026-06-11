"""
SAM3 Segmentation Service using ONNX Runtime.

Provides image segmentation using SAM3 (Segment Anything Model 3) via ONNX models,
running directly in-process without PyTorch dependency.

This is an internal service used by agent tools - masks are transient and not
exposed directly to the agent.
"""

import asyncio
import io
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

import model_cache
from core.logging import get_logger

log = get_logger(__name__)

# Thread pool for running inference (ONNX is synchronous)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sam3")

# Models are mirrored to R2 (models.stimma.ai/sam3/) from the upstream
# HuggingFace repo "wkentaro/sam3-onnx-models".

# Model file names
MODEL_FILES = [
    "sam3_image_encoder.onnx",
    "sam3_image_encoder.onnx.data",
    "sam3_language_encoder.onnx",
    "sam3_language_encoder.onnx.data",
    "sam3_decoder.onnx",
    "sam3_decoder.onnx.data",
]


@dataclass
class BBox:
    """Bounding box in pixels."""
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height
        }


@dataclass
class SAM3Detection:
    """A single detection result from SAM3."""
    bbox: BBox
    score: float
    mask_data: bytes | None = None  # PNG mask image data
    area_percent: float = 0.0  # Percentage of image area covered by detection

    def to_dict(self) -> dict:
        return {
            "bbox": self.bbox.to_dict(),
            "score": self.score,
            "area_percent": self.area_percent,
        }


@dataclass
class SAM3Result:
    """Complete result from SAM3 segmentation."""
    detections: List[SAM3Detection] = field(default_factory=list)
    visualization: bytes | None = None  # Preview image with overlaid masks
    original_width: int = 0
    original_height: int = 0
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.detections)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "objects": [d.to_dict() for d in self.detections],
            "original_width": self.original_width,
            "original_height": self.original_height,
        }


def _get_models_dir() -> Path:
    """Get the directory for SAM3 ONNX models in the user cache."""
    return model_cache.models_root() / "sam3"


def _ensure_models_downloaded() -> Path:
    """Download SAM3 ONNX models from R2 on first use (into the user cache)."""
    # Pre-model_cache installs cached these under ~/.cache/stimma/sam3-onnx;
    # adopt those in place so they don't re-download.
    legacy_dir = Path.home() / ".cache" / "stimma" / "sam3-onnx"
    for filename in MODEL_FILES:
        model_cache.ensure_model(f"sam3/{filename}", legacy_paths=[legacy_dir / filename])
    return _get_models_dir()


def _compute_bbox_from_mask(mask_array: np.ndarray, original_width: int, original_height: int) -> tuple[BBox, float] | None:
    """
    Compute bounding box from mask array.

    Args:
        mask_array: Boolean numpy array of the mask
        original_width: Original image width
        original_height: Original image height

    Returns:
        Tuple of (BBox, area_percent) or None if mask is empty
    """
    try:
        # Ensure boolean array
        nonzero = mask_array.astype(bool)

        if not nonzero.any():
            return None

        # Get bounding box
        rows = np.any(nonzero, axis=1)
        cols = np.any(nonzero, axis=0)
        y_indices = np.where(rows)[0]
        x_indices = np.where(cols)[0]

        y_min, y_max = y_indices[0], y_indices[-1]
        x_min, x_max = x_indices[0], x_indices[-1]

        width = int(x_max - x_min + 1)
        height = int(y_max - y_min + 1)

        # Calculate area percent
        image_area = original_width * original_height
        mask_pixel_count = int(nonzero.sum())
        area_percent = (mask_pixel_count / image_area * 100) if image_area > 0 else 0

        return BBox(x=int(x_min), y=int(y_min), width=width, height=height), area_percent

    except Exception as e:
        log.warning(f"Failed to compute bbox from mask: {e}")
        return None


def _mask_to_png(mask_array: np.ndarray) -> bytes:
    """Convert a boolean mask array to PNG bytes."""
    # Convert to 8-bit grayscale (255 for True, 0 for False)
    mask_img = Image.fromarray((mask_array.astype(np.uint8) * 255))
    buf = io.BytesIO()
    mask_img.save(buf, format='PNG')
    return buf.getvalue()


def _create_visualization(image: Image.Image, masks: np.ndarray, scores: np.ndarray, prompt: str) -> bytes:
    """Create a visualization with colored mask overlays."""
    import imgviz

    img_array = np.array(image)

    # Create visualization using imgviz
    # masks shape: (N, 1, H, W) -> (N, H, W)
    masks_2d = masks[:, 0, :, :] if masks.ndim == 4 else masks

    viz = imgviz.instances2rgb(
        image=img_array,
        masks=masks_2d,
        labels=np.arange(len(masks_2d)) + 1,
        captions=[f"{prompt}: {s:.0%}" for s in scores],
        font_size=max(1, min(image.size) // 40),
    )

    # Convert to PNG bytes
    result_image = Image.fromarray(viz)
    buf = io.BytesIO()
    result_image.save(buf, format='PNG')
    return buf.getvalue()


class SAM3Service:
    """
    Service for running SAM3 segmentation in-process using ONNX Runtime.

    Features:
    - Lazy model loading (loads on first use)
    - Internal queueing (one inference at a time)
    - Async interface with sync inference in thread pool
    """

    def __init__(self):
        self._sess_image = None
        self._sess_language = None
        self._sess_decoder = None
        self._models_dir = None
        self._loading = False
        self._load_lock = asyncio.Lock()
        # Semaphore to ensure one inference at a time
        self._inference_semaphore = asyncio.Semaphore(1)

    def _load_model_sync(self):
        """Load the SAM3 ONNX models synchronously. Called in thread pool."""
        import onnxruntime as ort
        import onnx

        log.info("SAM3: Loading ONNX models...")

        # Ensure models are downloaded
        self._models_dir = _ensure_models_downloaded()

        # Load ONNX sessions
        log.info("SAM3: Creating ONNX inference sessions...")

        # Set up session options
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # Determine providers - skip CoreML as it has issues with external data models
        providers = ort.get_available_providers()
        log.info(f"SAM3: Available ONNX providers: {providers}")

        # Use CUDA if available, otherwise CPU (skip CoreML for now)
        if 'CUDAExecutionProvider' in providers:
            exec_providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        else:
            exec_providers = ['CPUExecutionProvider']

        log.info(f"SAM3: Using providers: {exec_providers}")

        # Load models with external data support
        # We need to load the model, convert external data to be embedded, then create session
        def load_model_with_external_data(model_name: str) -> ort.InferenceSession:
            model_path = self._models_dir / model_name
            log.info(f"SAM3: Loading {model_name}...")

            # Load ONNX model with external data
            model = onnx.load(str(model_path), load_external_data=True)

            # Serialize to bytes for inference session
            model_bytes = model.SerializeToString()

            return ort.InferenceSession(
                model_bytes,
                sess_options=sess_options,
                providers=exec_providers,
            )

        self._sess_image = load_model_with_external_data("sam3_image_encoder.onnx")
        self._sess_language = load_model_with_external_data("sam3_language_encoder.onnx")
        self._sess_decoder = load_model_with_external_data("sam3_decoder.onnx")

        log.info("SAM3: ONNX models loaded successfully")

    async def _ensure_loaded(self):
        """Ensure the model is loaded, loading it if necessary."""
        if self._sess_image is not None:
            return

        async with self._load_lock:
            # Double-check after acquiring lock
            if self._sess_image is not None:
                return

            log.info("SAM3: Loading model (first use)...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, self._load_model_sync)

    def _segment_sync(
        self,
        image_path: str,
        prompt: str,
        confidence_threshold: float,
        max_detections: int,
    ) -> SAM3Result:
        """Run segmentation synchronously. Called in thread pool."""
        from osam._models.yoloworld.clip import tokenize

        try:
            # Load image
            image = Image.open(image_path).convert("RGB")
            original_width, original_height = image.size
            log.info(f"SAM3: Segmenting image {original_width}x{original_height} with prompt '{prompt}'")

            # Run image encoder
            log.debug("SAM3: Running image encoder...")
            image_input = np.asarray(image.resize((1008, 1008))).transpose(2, 0, 1)
            image_output = self._sess_image.run(None, {"image": image_input})

            assert len(image_output) == 6
            vision_pos_enc = image_output[:3]
            backbone_fpn = image_output[3:]

            # Run language encoder
            log.debug("SAM3: Running language encoder...")
            tokens = tokenize(texts=[prompt], context_length=32)
            language_output = self._sess_language.run(None, {"tokens": tokens})

            assert len(language_output) == 3
            language_mask = language_output[0]
            language_features = language_output[1]

            # Run decoder (without box prompt - text-only mode)
            log.debug("SAM3: Running decoder...")
            box_coords = np.array([0, 0, 0, 0], dtype=np.float32).reshape(1, 1, 4)
            box_labels = np.array([[1]], dtype=np.int64)
            box_masks = np.array([True], dtype=np.bool_).reshape(1, 1)

            decoder_output = self._sess_decoder.run(
                None,
                {
                    "original_height": np.array(original_height, dtype=np.int64),
                    "original_width": np.array(original_width, dtype=np.int64),
                    "backbone_fpn_0": backbone_fpn[0],
                    "backbone_fpn_1": backbone_fpn[1],
                    "backbone_fpn_2": backbone_fpn[2],
                    "vision_pos_enc_2": vision_pos_enc[2],
                    "language_mask": language_mask,
                    "language_features": language_features,
                    "box_coords": box_coords,
                    "box_labels": box_labels,
                    "box_masks": box_masks,
                },
            )

            assert len(decoder_output) == 3
            boxes = decoder_output[0]  # shape: (N, 4) - y1, x1, y2, x2
            scores = decoder_output[1]  # shape: (N,)
            masks = decoder_output[2]  # shape: (N, 1, H, W)

            log.info(f"SAM3: Found {len(scores)} detection(s)")

            # Build detections
            detections = []
            for i in range(len(scores)):
                score_val = float(scores[i])

                # Filter by confidence
                if score_val < confidence_threshold:
                    continue

                # Get mask
                mask_np = masks[i, 0, :, :]  # (H, W)

                # Compute bbox from mask
                bbox_result = _compute_bbox_from_mask(mask_np, original_width, original_height)
                if bbox_result is None:
                    continue

                bbox, area_percent = bbox_result

                # Convert mask to PNG
                mask_data = _mask_to_png(mask_np)

                detections.append(SAM3Detection(
                    bbox=bbox,
                    score=score_val,
                    mask_data=mask_data,
                    area_percent=area_percent,
                ))

            # Apply max_detections limit
            if max_detections > 0:
                # Sort by score descending, take top N
                detections.sort(key=lambda d: d.score, reverse=True)
                detections = detections[:max_detections]

            # Create visualization
            visualization = None
            if len(masks) > 0:
                # Filter masks by confidence for visualization
                valid_indices = [i for i in range(len(scores)) if scores[i] >= confidence_threshold]
                if valid_indices:
                    valid_masks = masks[valid_indices]
                    valid_scores = scores[valid_indices]
                    visualization = _create_visualization(image, valid_masks, valid_scores, prompt)

            return SAM3Result(
                detections=detections,
                visualization=visualization,
                original_width=original_width,
                original_height=original_height,
            )

        except Exception as e:
            log.error(f"SAM3 segmentation failed: {e}", exc_info=True)
            return SAM3Result(
                error=str(e),
                original_width=0,
                original_height=0,
            )

    async def segment(
        self,
        image_path: str,
        prompt: str,
        confidence_threshold: float = 0.2,
        max_detections: int = -1,
    ) -> SAM3Result:
        """
        Segment an image using a text prompt.

        Args:
            image_path: Path to the image file
            prompt: Text prompt describing what to segment (e.g., "cat", "person")
            confidence_threshold: Minimum confidence score for detections (0-1)
            max_detections: Maximum number of detections (-1 for unlimited)

        Returns:
            SAM3Result with detections, masks, and visualization
        """
        # Ensure model is loaded
        await self._ensure_loaded()

        # Acquire semaphore to ensure one inference at a time
        async with self._inference_semaphore:
            log.info(f"SAM3: Starting segmentation for '{prompt}'")
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                _executor,
                self._segment_sync,
                image_path,
                prompt,
                confidence_threshold,
                max_detections,
            )
            return result


# Singleton instance
_sam3_service: Optional[SAM3Service] = None


def get_sam3_service() -> SAM3Service:
    """Get the singleton SAM3Service instance."""
    global _sam3_service
    if _sam3_service is None:
        _sam3_service = SAM3Service()
    return _sam3_service

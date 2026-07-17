import numpy as np
from PIL import Image
from typing import Optional, Union, List, Dict, Any
from pathlib import Path
from core.logging import get_logger
import json
import threading
import os

import model_cache

log = get_logger(__name__)

# Required AuraFace model files. Mirrored to R2 (models.stimma.ai/face/) from the
# upstream HuggingFace repo "fal/AuraFace-v1".
_FACE_MODEL_FILES = ["scrfd_10g_bnkps.onnx", "glintr100.onnx"]


def _ensure_auraface_models():
    """Download AuraFace models from R2 on first use (into the user cache)."""
    # Pre-model_cache installs cached these under ~/.insightface/models/auraface;
    # adopt those in place so they don't re-download.
    legacy_dir = Path(os.path.expanduser("~/.insightface")) / "models" / "auraface"
    for filename in _FACE_MODEL_FILES:
        model_cache.ensure_model(f"face/{filename}", legacy_paths=[legacy_dir / filename])
    model_dir = str(model_cache.models_root() / "face")
    log.info(f"AuraFace models ready at: {model_dir}")
    return model_dir


class FaceDetectionService:
    def __init__(self, min_confidence: float = 0.5, max_faces: int = 10):
        """
        Initialize Face Detection service.

        Args:
            min_confidence: Minimum confidence threshold for face detection (0-1)
            max_faces: Maximum number of faces to detect per image
        """
        self.min_confidence = min_confidence
        self.max_faces = max_faces
        self.detector = None
        self.recognizer = None
        self.device = None
        self._loading = False
        self._loaded = False
        self._load_lock = threading.Lock()

    def load_model(self, background: bool = False):
        """
        Load the face detection model. Call this once at startup.

        Args:
            background: If True, load the model in a background thread
        """
        if self._loaded:
            log.info("Face detection model already loaded")
            return

        if background:
            log.info("Starting face detection model loading in background thread...")
            thread = threading.Thread(target=self._load_model_sync, daemon=True)
            thread.start()
        else:
            self._load_model_sync()

    def _load_model_sync(self):
        """Load the model, serialized so concurrent callers block until it's ready."""
        import onnxruntime as ort
        from face_onnx import SCRFDDetector, AuraFaceRecognizer

        with self._load_lock:
            if self._loaded:
                return
            self._loading = True
            log.info("Loading face detection models...")
            try:
                self._load_model_locked(ort, SCRFDDetector, AuraFaceRecognizer)
            finally:
                self._loading = False

    def _load_model_locked(self, ort, SCRFDDetector, AuraFaceRecognizer):
        try:
            # Ensure AuraFace models are downloaded/available
            model_dir = _ensure_auraface_models()
            log.info(f"AuraFace model directory: {model_dir}")

            # Check for GPU availability via ONNX Runtime providers
            available_providers = ort.get_available_providers()
            if 'CUDAExecutionProvider' in available_providers:
                self.device = "cuda"
                providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                log.info("CUDA acceleration available - using GPU")
            else:
                self.device = "cpu"
                providers = ['CPUExecutionProvider']
                log.info("Using CPU for face detection")

            # Load SCRFD detector
            scrfd_path = os.path.join(model_dir, "scrfd_10g_bnkps.onnx")
            log.info(f"Loading SCRFD detector from {scrfd_path}")
            self.detector = SCRFDDetector(scrfd_path, providers)

            # Load AuraFace recognizer
            auraface_path = os.path.join(model_dir, "glintr100.onnx")
            log.info(f"Loading AuraFace recognizer from {auraface_path}")
            self.recognizer = AuraFaceRecognizer(auraface_path, providers)

            self._loaded = True
            log.info("Face detection models loaded successfully ✓")

        except Exception as e:
            log.error(f"Failed to load face detection model: {e}", exc_info=True)
            raise

    def is_loaded(self) -> bool:
        """Check if the model is fully loaded and ready."""
        return self._loaded

    def is_loading(self) -> bool:
        """Check if the model is currently loading."""
        return self._loading

    def detect_faces(self, image: Union[str, Path, Image.Image]) -> List[Dict[str, Any]]:
        """
        Detect faces in an image and extract embeddings.

        Args:
            image: Path to image file or PIL Image object

        Returns:
            List of face dictionaries containing:
                - bbox: dict with x, y, width, height (normalized 0-1)
                - confidence: float detection confidence
                - embedding: numpy array of face embedding
                - landmarks: dict with facial landmark coordinates (optional)
        """
        if not self._loaded:
            # Auto-load on first use; blocks on the load lock if another
            # thread is already loading, so we never proceed with detector=None.
            self._load_model_sync()

        # Load image if path provided
        should_close_image = False
        if isinstance(image, (str, Path)):
            log.debug(f"FACE DETECTION: Loading image from path: {image}")
            from utils.image_ops import open_oriented
            image = open_oriented(image).convert("RGB")
            should_close_image = True
            log.debug(f"FACE DETECTION: Image loaded and converted to RGB")
        elif not isinstance(image, Image.Image):
            raise ValueError("image must be a path or PIL Image")

        try:
            # Get image dimensions for normalization
            img_width, img_height = image.size
            log.debug(f"FACE DETECTION: Image size: {img_width}x{img_height}")

            # Convert PIL image to numpy array (BGR format for OpenCV)
            image_np = np.array(image)
            # Convert RGB to BGR
            image_np = image_np[:, :, ::-1].copy()

            # Run face detection
            log.debug("FACE DETECTION: Running detection...")
            detected_faces = self.detector.detect(image_np, conf_threshold=self.min_confidence)

            # Process results
            faces = []
            if detected_faces:
                log.debug(f"FACE DETECTION: Found {len(detected_faces)} faces")

                for i, face in enumerate(detected_faces[:self.max_faces]):
                    confidence = face.confidence

                    # Extract bounding box [x1, y1, x2, y2]
                    x1, y1, x2, y2 = face.bbox

                    # Normalize bbox coordinates
                    bbox_x = x1 / img_width
                    bbox_y = y1 / img_height
                    bbox_width = (x2 - x1) / img_width
                    bbox_height = (y2 - y1) / img_height

                    # Get embedding using face landmarks
                    embedding = None
                    if self.recognizer is not None and face.landmarks is not None:
                        try:
                            embedding = self.recognizer.get_embedding(image_np, face.landmarks)
                        except Exception as e:
                            log.warning(f"Face {i}: Failed to extract embedding: {e}")

                    if embedding is None:
                        log.warning(f"Face {i}: No embedding extracted")

                    # Get landmarks (5 points: left eye, right eye, nose, left mouth, right mouth)
                    landmarks_json = None
                    if face.landmarks is not None:
                        try:
                            # Normalize landmark coordinates
                            normalized_landmarks = []
                            for point in face.landmarks:
                                normalized_landmarks.append({
                                    'x': float(point[0]) / img_width,
                                    'y': float(point[1]) / img_height
                                })
                            landmarks_json = json.dumps(normalized_landmarks)
                        except Exception as e:
                            log.warning(f"Face {i}: Failed to process landmarks: {e}")

                    log.debug(f"Face {i}: bbox=({bbox_x:.3f}, {bbox_y:.3f}, {bbox_width:.3f}, {bbox_height:.3f}), confidence={confidence:.3f}")

                    faces.append({
                        'bbox': {
                            'x': bbox_x,
                            'y': bbox_y,
                            'width': bbox_width,
                            'height': bbox_height,
                        },
                        'confidence': float(confidence),
                        'embedding': embedding,
                        'landmarks': landmarks_json,
                    })
            else:
                log.debug("FACE DETECTION: No faces detected")

            log.debug(f"FACE DETECTION: Returning {len(faces)} faces after filtering")
            return faces

        except Exception as e:
            log.error(f"FACE DETECTION: Error during detection: {e}", exc_info=True)
            raise
        finally:
            # Close image if we opened it
            if should_close_image:
                image.close()

    def compute_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Compute cosine similarity between two face embeddings.

        Args:
            embedding1: First face embedding
            embedding2: Second face embedding

        Returns:
            Cosine similarity score (0-1)
        """
        # Ensure embeddings are normalized
        embedding1 = embedding1 / np.linalg.norm(embedding1)
        embedding2 = embedding2 / np.linalg.norm(embedding2)

        return float(np.dot(embedding1, embedding2))


# Global face detection service instance
_face_detection_service: Optional[FaceDetectionService] = None


def get_face_detection_service(min_confidence: float = 0.5, max_faces: int = 10, auto_load: bool = False, background: bool = False) -> FaceDetectionService:
    """
    Get or create face detection service singleton.

    Args:
        min_confidence: Minimum confidence threshold for face detection
        max_faces: Maximum number of faces to detect per image
        auto_load: If True, immediately load the model. If False, create service but don't load yet.
        background: If True, load the model in a background thread (non-blocking)
    """
    global _face_detection_service
    if _face_detection_service is None:
        log.info(f"FACE DETECTION: Creating new FaceDetectionService instance (first time)")
        _face_detection_service = FaceDetectionService(min_confidence, max_faces)
        if auto_load:
            _face_detection_service.load_model(background=background)
        else:
            log.info(f"FACE DETECTION: Service created but model not loaded yet (lazy loading)")
    else:
        log.info(f"FACE DETECTION: Reusing existing FaceDetectionService instance (singleton)")
    return _face_detection_service

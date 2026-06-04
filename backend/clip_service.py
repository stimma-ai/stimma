"""
CLIP Service for image and text embeddings using ONNX Runtime.

Uses onnx_clip library with ViT-B/32 model for efficient CPU/GPU inference
without PyTorch dependency.
"""

import threading
from PIL import Image
import numpy as np
from typing import Optional, Union
from pathlib import Path
from core.logging import get_logger

log = get_logger(__name__)

# Expected embedding dimension for the current ONNX model (ViT-B/32)
# Old PyTorch model (ViT-g-14) produced 1024-dimensional embeddings
CLIP_EMBEDDING_DIM = 512


class CLIPService:
    def __init__(self):
        """
        Initialize CLIP service with ONNX backend.

        Uses ViT-B/32 model via onnx_clip library.
        Produces 512-dimensional embeddings (vs 1024 for ViT-g-14).
        """
        self.model = None
        self._loading = False
        self._loaded = False
        self._loaded_event = threading.Event()

    def load_model(self):
        """Load the CLIP model. Call this once at startup."""
        # onnx_clip imports cv2 at module level but never uses it (PIL path is
        # hardcoded). Provide a stub so the import succeeds in packaged builds
        # where cv2 isn't bundled.
        import sys, types
        sys.modules.setdefault('cv2', types.ModuleType('cv2'))

        from onnx_clip import OnnxClip

        if self._loaded:
            log.info("CLIP model already loaded")
            return

        if self._loading:
            log.info("CLIP model is currently loading")
            return

        self._loading = True
        log.info("Loading CLIP model (ONNX, ViT-B/32)...")

        try:
            # OnnxClip automatically downloads models on first use
            self.model = OnnxClip(batch_size=16)

            self._loaded = True
            self._loading = False
            self._loaded_event.set()
            log.info("CLIP model loaded successfully (ONNX)")
        except Exception as e:
            self._loading = False
            log.error(f"Failed to load CLIP model: {e}")
            raise

    def is_loaded(self) -> bool:
        """Check if the model is fully loaded and ready."""
        return self._loaded

    def is_loading(self) -> bool:
        """Check if the model is currently loading."""
        return self._loading

    def wait_for_model(self, timeout: float = 60.0) -> bool:
        """
        Wait for the model to finish loading.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if model is ready, False if timeout
        """
        if self._loaded:
            return True
        return self._loaded_event.wait(timeout=timeout)

    def _ensure_loaded(self):
        """Ensure model is loaded, auto-loading if needed."""
        if not self._loaded:
            if self._loading:
                if not self.wait_for_model():
                    raise RuntimeError("Timeout waiting for CLIP model to load")
            else:
                self.load_model()

    def encode_image(self, image: Union[str, Path, Image.Image]) -> np.ndarray:
        """
        Encode an image to a CLIP embedding.

        Args:
            image: Path to image file or PIL Image object

        Returns:
            Normalized embedding as numpy array (512 dimensions)
        """
        self._ensure_loaded()

        # Load image if path provided
        should_close_image = False
        if isinstance(image, (str, Path)):
            log.debug(f"CLIP ENCODE: Loading image from path: {image}")
            image = Image.open(image).convert("RGB")
            should_close_image = True
            log.debug("CLIP ENCODE: Image loaded and converted to RGB")
        elif not isinstance(image, Image.Image):
            raise ValueError("image must be a path or PIL Image")

        try:
            # Get embedding from onnx_clip
            embedding = self.model.get_image_embeddings([image])[0]

            # Normalize embedding (onnx_clip doesn't normalize by default)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            embedding = embedding.astype(np.float32)
            log.debug(f"CLIP ENCODE: Successfully generated embedding (shape: {embedding.shape})")
            return embedding
        finally:
            if should_close_image:
                image.close()

    def encode_text(self, text: str) -> np.ndarray:
        """
        Encode text to a CLIP embedding.

        Args:
            text: Text string to encode

        Returns:
            Normalized embedding as numpy array (512 dimensions)
        """
        self._ensure_loaded()

        # Get embedding from onnx_clip
        embedding = self.model.get_text_embeddings([text])[0]

        # Normalize embedding
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding.astype(np.float32)

    def compute_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Cosine similarity score (0-1)
        """
        # Ensure embeddings are normalized
        embedding1 = embedding1 / np.linalg.norm(embedding1)
        embedding2 = embedding2 / np.linalg.norm(embedding2)

        return float(np.dot(embedding1, embedding2))

    def find_similar(
        self,
        query_embedding: np.ndarray,
        candidate_embeddings: list[np.ndarray],
        top_k: int = 100
    ) -> list[tuple[int, float]]:
        """
        Find most similar embeddings to query.

        Args:
            query_embedding: Query embedding
            candidate_embeddings: List of candidate embeddings
            top_k: Number of top results to return

        Returns:
            List of (index, similarity_score) tuples, sorted by similarity
        """
        # Ensure query is normalized
        query_embedding = query_embedding / np.linalg.norm(query_embedding)

        # Compute similarities
        similarities = []
        for idx, candidate in enumerate(candidate_embeddings):
            candidate = candidate / np.linalg.norm(candidate)
            similarity = float(np.dot(query_embedding, candidate))
            similarities.append((idx, similarity))

        # Sort by similarity (descending) and return top k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]


# Global CLIP service instance
_clip_service: Optional[CLIPService] = None


def get_clip_service(model_name: str = None, pretrained: str = None, auto_load: bool = False) -> CLIPService:
    """
    Get or create CLIP service singleton.

    Args:
        model_name: Ignored (kept for API compatibility, always uses ViT-B/32)
        pretrained: Ignored (kept for API compatibility)
        auto_load: If True, immediately load the model. If False, create service but don't load yet.
    """
    global _clip_service
    if _clip_service is None:
        log.info("CLIP: Creating new CLIPService instance (first time)")
        _clip_service = CLIPService()
        if auto_load:
            _clip_service.load_model()
        else:
            log.info("CLIP: Service created but model not loaded yet (lazy loading)")
    else:
        log.debug("CLIP: Reusing existing CLIPService instance (singleton)")
    return _clip_service

"""
Tests for ML services: CLIP, SAM3, and Face Detection.

These tests verify the ML services work correctly in isolation.
They're designed to:
1. Establish baseline behavior before ONNX migration
2. Verify ONNX versions produce equivalent results after migration

The tests use programmatically generated images to avoid external dependencies.
"""

import pytest

pytest.skip("Temporarily disabled ML service tests.", allow_module_level=True)

import io
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw


# =============================================================================
# Test Image Generation Helpers
# =============================================================================

def create_simple_image(width: int = 224, height: int = 224, color: tuple = (255, 0, 0)) -> Image.Image:
    """Create a simple solid color image."""
    return Image.new("RGB", (width, height), color)


def create_gradient_image(width: int = 224, height: int = 224) -> Image.Image:
    """Create an image with a gradient pattern."""
    img = Image.new("RGB", (width, height))
    for x in range(width):
        for y in range(height):
            r = int(255 * x / width)
            g = int(255 * y / height)
            b = 128
            img.putpixel((x, y), (r, g, b))
    return img


def create_shapes_image(width: int = 512, height: int = 512) -> Image.Image:
    """Create an image with geometric shapes for segmentation testing."""
    img = Image.new("RGB", (width, height), (240, 240, 240))
    draw = ImageDraw.Draw(img)

    # Draw a red circle
    draw.ellipse([100, 100, 250, 250], fill=(255, 0, 0))

    # Draw a blue rectangle
    draw.rectangle([300, 150, 450, 350], fill=(0, 0, 255))

    # Draw a green triangle
    draw.polygon([(256, 380), (150, 480), (362, 480)], fill=(0, 255, 0))

    return img


def create_face_like_image(width: int = 256, height: int = 256) -> Image.Image:
    """Create a simple face-like pattern for testing face detection.

    Note: This is a simplified pattern that may not trigger real face detection.
    For robust face detection tests, consider using a real face image.
    """
    img = Image.new("RGB", (width, height), (255, 220, 185))  # Skin tone background
    draw = ImageDraw.Draw(img)

    # Face oval
    draw.ellipse([48, 32, 208, 224], fill=(255, 200, 170))

    # Eyes
    draw.ellipse([80, 80, 110, 110], fill=(255, 255, 255))  # Left eye white
    draw.ellipse([146, 80, 176, 110], fill=(255, 255, 255))  # Right eye white
    draw.ellipse([88, 88, 102, 102], fill=(50, 30, 20))  # Left pupil
    draw.ellipse([154, 88, 168, 102], fill=(50, 30, 20))  # Right pupil

    # Nose
    draw.polygon([(128, 110), (118, 150), (138, 150)], fill=(230, 180, 150))

    # Mouth
    draw.arc([98, 160, 158, 200], start=0, end=180, fill=(180, 80, 80), width=3)

    return img


def save_temp_image(image: Image.Image, tmp_path: Path, name: str = "test.png") -> Path:
    """Save an image to a temporary path and return the path."""
    path = tmp_path / name
    image.save(path, format="PNG")
    return path


# =============================================================================
# CLIP Service Tests
# =============================================================================

class TestCLIPService:
    """Tests for the CLIP embedding service."""

    @pytest.fixture(scope="class")
    def clip_service(self):
        """Get or create CLIP service instance."""
        from clip_service import get_clip_service
        service = get_clip_service(auto_load=True)
        # Wait for model to load
        assert service.wait_for_model(timeout=120), "CLIP model failed to load"
        return service

    def test_clip_service_loads(self, clip_service):
        """Verify CLIP service loads without error."""
        assert clip_service.is_loaded()
        assert not clip_service.is_loading()

    def test_clip_encode_image_returns_embedding(self, clip_service, tmp_path):
        """Verify encode_image returns a numpy array with correct shape."""
        image = create_gradient_image()
        image_path = save_temp_image(image, tmp_path, "gradient.png")

        embedding = clip_service.encode_image(image_path)

        assert isinstance(embedding, np.ndarray)
        assert embedding.dtype == np.float32
        # ViT-g-14 produces 1024-dimensional embeddings
        # After ONNX migration with ViT-B/32, this will be 512
        assert embedding.shape == (1024,) or embedding.shape == (512,), \
            f"Unexpected embedding shape: {embedding.shape}"

    def test_clip_encode_image_from_pil(self, clip_service):
        """Verify encode_image works with PIL Image directly."""
        image = create_gradient_image()

        embedding = clip_service.encode_image(image)

        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (1024,) or embedding.shape == (512,)

    def test_clip_encode_text_returns_embedding(self, clip_service):
        """Verify encode_text returns a numpy array with correct shape."""
        embedding = clip_service.encode_text("a photo of a cat")

        assert isinstance(embedding, np.ndarray)
        assert embedding.dtype == np.float32
        assert embedding.shape == (1024,) or embedding.shape == (512,)

    def test_clip_embeddings_are_normalized(self, clip_service, tmp_path):
        """Verify embeddings are normalized (unit length)."""
        image = create_simple_image()
        image_path = save_temp_image(image, tmp_path, "simple.png")

        image_embedding = clip_service.encode_image(image_path)
        text_embedding = clip_service.encode_text("a red square")

        # Check embeddings are approximately unit length
        image_norm = np.linalg.norm(image_embedding)
        text_norm = np.linalg.norm(text_embedding)

        assert abs(image_norm - 1.0) < 0.01, f"Image embedding not normalized: {image_norm}"
        assert abs(text_norm - 1.0) < 0.01, f"Text embedding not normalized: {text_norm}"

    def test_clip_similarity_same_image(self, clip_service, tmp_path):
        """Verify same image has high self-similarity."""
        image = create_gradient_image()
        image_path = save_temp_image(image, tmp_path, "gradient.png")

        embedding1 = clip_service.encode_image(image_path)
        embedding2 = clip_service.encode_image(image_path)

        similarity = clip_service.compute_similarity(embedding1, embedding2)

        # Same image should have very high similarity (near 1.0)
        assert similarity > 0.99, f"Self-similarity too low: {similarity}"

    def test_clip_similarity_different_images(self, clip_service, tmp_path):
        """Verify different images have lower similarity than identical ones."""
        red_image = create_simple_image(color=(255, 0, 0))
        blue_image = create_simple_image(color=(0, 0, 255))

        red_path = save_temp_image(red_image, tmp_path, "red.png")
        blue_path = save_temp_image(blue_image, tmp_path, "blue.png")

        red_embedding = clip_service.encode_image(red_path)
        blue_embedding = clip_service.encode_image(blue_path)

        similarity = clip_service.compute_similarity(red_embedding, blue_embedding)

        # Different images should have similarity < 1.0
        # (but could still be high since both are solid color images)
        assert similarity < 0.99, f"Different images too similar: {similarity}"

    def test_clip_text_image_similarity(self, clip_service, tmp_path):
        """Verify text-image similarity works (cross-modal)."""
        red_image = create_simple_image(color=(255, 0, 0))
        red_path = save_temp_image(red_image, tmp_path, "red.png")

        image_embedding = clip_service.encode_image(red_path)
        red_text_embedding = clip_service.encode_text("a solid red image")
        blue_text_embedding = clip_service.encode_text("a solid blue image")

        red_similarity = clip_service.compute_similarity(image_embedding, red_text_embedding)
        blue_similarity = clip_service.compute_similarity(image_embedding, blue_text_embedding)

        # Red text should be more similar to red image than blue text
        assert red_similarity > blue_similarity, \
            f"Expected red text ({red_similarity:.3f}) > blue text ({blue_similarity:.3f}) for red image"

    def test_clip_find_similar(self, clip_service, tmp_path):
        """Verify find_similar returns sorted results."""
        # Create query and candidate embeddings
        query_image = create_simple_image(color=(255, 0, 0))
        query_path = save_temp_image(query_image, tmp_path, "query.png")
        query_embedding = clip_service.encode_image(query_path)

        # Create candidates with varying similarity
        candidates = []
        colors = [(255, 0, 0), (200, 50, 50), (0, 0, 255)]
        for i, color in enumerate(colors):
            img = create_simple_image(color=color)
            path = save_temp_image(img, tmp_path, f"candidate_{i}.png")
            candidates.append(clip_service.encode_image(path))

        results = clip_service.find_similar(query_embedding, candidates, top_k=3)

        # Results should be sorted by similarity (descending)
        assert len(results) == 3
        for i in range(len(results) - 1):
            assert results[i][1] >= results[i + 1][1], "Results not sorted by similarity"

        # First result should be the red image (index 0)
        assert results[0][0] == 0, "Most similar should be the identical red image"


# =============================================================================
# SAM3 Service Tests
# =============================================================================

class TestSAM3Service:
    """Tests for the SAM3 segmentation service."""

    @pytest.fixture(scope="class")
    def sam3_service(self):
        """Get or create SAM3 service instance."""
        import os
        from sam3_service import get_sam3_service, _get_models_dir, MODEL_FILES

        models_dir = _get_models_dir()
        models_present = all((models_dir / f).exists() for f in MODEL_FILES)
        if not models_present and os.getenv("STIMMA_TEST_DOWNLOAD_MODELS") != "1":
            pytest.skip(
                "SAM3 models not present. "
                "Set STIMMA_TEST_DOWNLOAD_MODELS=1 to allow download."
            )
        return get_sam3_service()

    @pytest.mark.asyncio
    async def test_sam3_segment_basic(self, sam3_service, tmp_path):
        """Verify SAM3 can segment an image with a text prompt."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="circle",
            confidence_threshold=0.1,
        )

        assert result.error is None, f"Segmentation failed: {result.error}"
        assert result.original_width == 512
        assert result.original_height == 512

    @pytest.mark.asyncio
    async def test_sam3_segment_returns_detections(self, sam3_service, tmp_path):
        """Verify SAM3 returns detection objects."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="shape",
            confidence_threshold=0.1,
        )

        assert result.error is None
        # Should find at least some detections
        # Note: exact count depends on model behavior
        assert isinstance(result.detections, list)

    @pytest.mark.asyncio
    async def test_sam3_detection_has_bbox(self, sam3_service, tmp_path):
        """Verify detections include bounding boxes."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="red circle",
            confidence_threshold=0.1,
        )

        if result.count > 0:
            detection = result.detections[0]
            bbox = detection.bbox

            assert hasattr(bbox, 'x')
            assert hasattr(bbox, 'y')
            assert hasattr(bbox, 'width')
            assert hasattr(bbox, 'height')

            # Bbox should be within image bounds
            assert 0 <= bbox.x < 512
            assert 0 <= bbox.y < 512
            assert bbox.width > 0
            assert bbox.height > 0

    @pytest.mark.asyncio
    async def test_sam3_detection_has_mask_png(self, sam3_service, tmp_path):
        """Verify detections include mask as PNG bytes."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="rectangle",
            confidence_threshold=0.1,
        )

        if result.count > 0:
            detection = result.detections[0]

            assert detection.mask_data is not None
            assert isinstance(detection.mask_data, bytes)

            # Verify it's valid PNG data
            mask_image = Image.open(io.BytesIO(detection.mask_data))
            assert mask_image.format == "PNG"
            # Mask should match original image dimensions
            assert mask_image.size == (512, 512)

    @pytest.mark.asyncio
    async def test_sam3_detection_has_score(self, sam3_service, tmp_path):
        """Verify detections include confidence scores."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="shape",
            confidence_threshold=0.1,
        )

        if result.count > 0:
            for detection in result.detections:
                assert isinstance(detection.score, float)
                assert 0 <= detection.score <= 1

    @pytest.mark.asyncio
    async def test_sam3_max_detections(self, sam3_service, tmp_path):
        """Verify max_detections parameter limits results."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="shape",
            confidence_threshold=0.1,
            max_detections=1,
        )

        assert result.error is None
        assert result.count <= 1

    @pytest.mark.asyncio
    async def test_sam3_result_to_dict(self, sam3_service, tmp_path):
        """Verify result can be serialized to dict."""
        image = create_shapes_image()
        image_path = save_temp_image(image, tmp_path, "shapes.png")

        result = await sam3_service.segment(
            image_path=str(image_path),
            prompt="circle",
            confidence_threshold=0.1,
        )

        result_dict = result.to_dict()

        assert "count" in result_dict
        assert "objects" in result_dict
        assert "original_width" in result_dict
        assert "original_height" in result_dict


# =============================================================================
# Face Detection Service Tests
# =============================================================================

class TestFaceDetectionService:
    """Tests for the face detection service.

    Note: These tests use programmatically generated face-like images.
    For production, consider adding tests with real face images.
    """

    @pytest.fixture(scope="class")
    def face_service(self):
        """Get or create face detection service instance."""
        import os
        from face_detection_service import get_face_detection_service, _get_insightface_home

        model_dir = Path(_get_insightface_home()) / "models" / "auraface"
        required_files = ["glintr100.onnx", "scrfd_10g_bnkps.onnx"]
        missing_files = [f for f in required_files if not (model_dir / f).exists()]
        if missing_files and os.getenv("STIMMA_TEST_DOWNLOAD_MODELS") != "1":
            pytest.skip(
                "AuraFace models not present. "
                "Set STIMMA_TEST_DOWNLOAD_MODELS=1 to allow download."
            )
        service = get_face_detection_service(auto_load=True)
        return service

    def test_face_service_loads(self, face_service):
        """Verify face detection service loads without error."""
        # Wait for model if loading in background
        import time
        deadline = time.time() + 120
        while face_service.is_loading() and time.time() < deadline:
            time.sleep(0.5)

        assert face_service.is_loaded()

    def test_face_detection_returns_list(self, face_service, tmp_path):
        """Verify detect_faces returns a list."""
        image = create_simple_image()
        image_path = save_temp_image(image, tmp_path, "no_face.png")

        result = face_service.detect_faces(image_path)

        assert isinstance(result, list)

    def test_face_detection_no_faces_in_solid_image(self, face_service, tmp_path):
        """Verify no faces detected in a solid color image."""
        image = create_simple_image(color=(0, 255, 0))
        image_path = save_temp_image(image, tmp_path, "solid_green.png")

        result = face_service.detect_faces(image_path)

        assert len(result) == 0, "Should not detect faces in solid color image"

    def test_face_detection_result_structure(self, face_service, tmp_path):
        """Verify detection result structure when faces are found."""
        # This test documents the expected structure
        # The face_like_image may not trigger detection, but we test structure if it does
        image = create_face_like_image()
        image_path = save_temp_image(image, tmp_path, "face_like.png")

        result = face_service.detect_faces(image_path)

        # If faces were detected, verify structure
        for face in result:
            assert "bbox" in face
            assert "confidence" in face
            assert "embedding" in face

            bbox = face["bbox"]
            assert "x" in bbox
            assert "y" in bbox
            assert "width" in bbox
            assert "height" in bbox

            # Bbox values should be normalized (0-1)
            assert 0 <= bbox["x"] <= 1
            assert 0 <= bbox["y"] <= 1
            assert 0 <= bbox["width"] <= 1
            assert 0 <= bbox["height"] <= 1

            # Confidence should be between 0 and 1
            assert 0 <= face["confidence"] <= 1

            # Embedding should be a numpy array
            if face["embedding"] is not None:
                assert isinstance(face["embedding"], np.ndarray)

    def test_face_embedding_shape(self, face_service, tmp_path):
        """Document expected face embedding shape."""
        # This test verifies embedding dimensions when faces are detected
        image = create_face_like_image()
        image_path = save_temp_image(image, tmp_path, "face_for_embedding.png")

        result = face_service.detect_faces(image_path)

        for face in result:
            if face["embedding"] is not None:
                embedding = face["embedding"]
                # InsightFace/AuraFace typically produces 512-dimensional embeddings
                assert embedding.shape == (512,), f"Unexpected embedding shape: {embedding.shape}"

    def test_face_similarity_computation(self, face_service):
        """Verify similarity computation between embeddings."""
        # Create two random embeddings
        embedding1 = np.random.randn(512).astype(np.float32)
        embedding2 = np.random.randn(512).astype(np.float32)

        similarity = face_service.compute_similarity(embedding1, embedding2)

        assert isinstance(similarity, float)
        assert -1 <= similarity <= 1

    def test_face_self_similarity(self, face_service):
        """Verify same embedding has similarity of 1.0."""
        embedding = np.random.randn(512).astype(np.float32)

        similarity = face_service.compute_similarity(embedding, embedding)

        assert abs(similarity - 1.0) < 0.01, f"Self-similarity should be 1.0, got {similarity}"

    def test_face_detection_from_pil_image(self, face_service):
        """Verify detect_faces works with PIL Image directly."""
        image = create_simple_image()

        result = face_service.detect_faces(image)

        assert isinstance(result, list)

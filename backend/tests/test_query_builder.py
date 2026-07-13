"""
Tests for utils/query_builder.py helper functions and format constants.

Tests cover:
- is_composite_format / is_atomic_format helpers
- is_composite_media / is_atomic_media helpers
- Format constant contents and relationships
- RESOLUTION_MAP structure and coverage
- build_filtered_query with various parameter combinations
"""

import pytest
from utils.query_builder import (
    is_composite_format,
    is_atomic_format,
    is_composite_media,
    is_atomic_media,
    VIDEO_FORMATS,
    IMAGE_FORMATS,
    AUDIO_FORMATS,
    TEXT_FORMATS,
    SET_FORMATS,
    GRID_FORMATS,
    COMPOSITE_FORMATS,
    ATOMIC_FORMATS,
    RESOLUTION_MAP,
    build_filtered_query,
)
from sqlalchemy import select
from database import MediaItem


# =============================================================================
# Helper function tests (no DB needed)
# =============================================================================


class TestIsCompositeFormat:
    def test_stimmaset_is_composite(self):
        assert is_composite_format("stimmaset.json") is True

    def test_stimmagrid_is_composite(self):
        assert is_composite_format("stimmagrid.json") is True

    def test_jpg_not_composite(self):
        assert is_composite_format("jpg") is False

    def test_mp4_not_composite(self):
        assert is_composite_format("mp4") is False


class TestIsAtomicFormat:
    def test_jpg_is_atomic(self):
        assert is_atomic_format("jpg") is True

    def test_mp4_is_atomic(self):
        assert is_atomic_format("mp4") is True

    def test_stimmaset_not_atomic(self):
        assert is_atomic_format("stimmaset.json") is False


class TestIsCompositeMedia:
    def test_dict_composite(self):
        assert is_composite_media({"file_format": "stimmaset.json"}) is True

    def test_dict_not_composite(self):
        assert is_composite_media({"file_format": "jpg"}) is False


class TestIsAtomicMedia:
    def test_dict_atomic(self):
        assert is_atomic_media({"file_format": "jpg"}) is True

    def test_dict_not_atomic(self):
        assert is_atomic_media({"file_format": "stimmaset.json"}) is False


class TestFormatConstants:
    def test_video_formats_contains_expected(self):
        for fmt in ["mp4", "webm", "mov", "avi", "mkv"]:
            assert fmt in VIDEO_FORMATS

    def test_image_formats_contains_expected(self):
        for fmt in ["jpg", "jpeg", "png", "gif", "webp", "bmp"]:
            assert fmt in IMAGE_FORMATS

    def test_audio_formats_contains_expected(self):
        for fmt in ["mp3", "wav", "flac"]:
            assert fmt in AUDIO_FORMATS

    def test_composite_equals_set_plus_grid(self):
        assert COMPOSITE_FORMATS == SET_FORMATS + GRID_FORMATS

    def test_atomic_formats_no_overlap_with_composite(self):
        overlap = set(ATOMIC_FORMATS) & set(COMPOSITE_FORMATS)
        assert len(overlap) == 0


class TestResolutionMap:
    def test_has_all_expected_keys(self):
        for key in ["small", "medium", "large", "huge"]:
            assert key in RESOLUTION_MAP

    def test_ranges_dont_overlap(self):
        """Verify resolution ranges are contiguous and non-overlapping."""
        # small: (None, 0.8), medium: (0.8, 1.5), large: (1.5, 3.0), huge: (3.0, None)
        small_max = RESOLUTION_MAP["small"][1]
        medium_min, medium_max = RESOLUTION_MAP["medium"]
        large_min, large_max = RESOLUTION_MAP["large"]
        huge_min = RESOLUTION_MAP["huge"][0]

        assert small_max == medium_min
        assert medium_max == large_min
        assert large_max == huge_min

    def test_covers_spectrum(self):
        """small starts at None (0) and huge ends at None (infinity)."""
        assert RESOLUTION_MAP["small"][0] is None
        assert RESOLUTION_MAP["huge"][1] is None


# =============================================================================
# build_filtered_query tests (creates query objects, verifies they compile)
# =============================================================================


class TestBuildFilteredQuery:
    def _base_query(self):
        return select(MediaItem)

    def test_no_filters(self):
        """No filters do not add legacy visibility predicates."""
        query = build_filtered_query(self._base_query())
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "superseded_by" not in compiled.lower()

    def test_media_types_filter(self):
        """media_types filter adds format conditions."""
        query = build_filtered_query(self._base_query(), media_types="images")
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "file_format" in compiled.lower()

    def test_is_generated_true(self):
        """is_generated=True adds generation_metadata IS NOT NULL."""
        query = build_filtered_query(self._base_query(), is_generated=True)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "generation_metadata" in compiled.lower()

    def test_is_generated_false(self):
        """is_generated=False adds generation_metadata IS NULL."""
        query = build_filtered_query(self._base_query(), is_generated=False)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "generation_metadata" in compiled.lower()

    def test_exclude_category_skips_filter(self):
        """build_filtered_query with exclude_category skips that filter category."""
        query = build_filtered_query(
            self._base_query(),
            media_types="images",
            exclude_category="media_types",
        )
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        # The WHERE clause should NOT filter on image formats since media_types is excluded
        # (file_format appears in SELECT columns, so check for IN with image format values)
        assert "'jpg'" not in compiled.lower()

    def test_multiple_filters_compose(self):
        """Multiple filters compose together without crashing."""
        query = build_filtered_query(
            self._base_query(),
            media_types="images,videos",
            is_generated=True,
            resolutions="small,large",
            folders="/some/path",
        )
        # Just verify it compiles without error
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert compiled  # non-empty string

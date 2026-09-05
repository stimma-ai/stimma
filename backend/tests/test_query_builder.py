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
    SPRITE_FORMATS,
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
        assert COMPOSITE_FORMATS == SET_FORMATS + GRID_FORMATS + SPRITE_FORMATS

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
# build_filtered_query tests (execute predicates against controlled rows)
# =============================================================================


class TestBuildFilteredQuery:
    def _base_query(self):
        return select(MediaItem)

    def test_no_filters(self):
        """No filters do not add legacy visibility predicates."""
        query = build_filtered_query(self._base_query())
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "superseded_by" not in compiled.lower()

    async def test_media_types_filter_selects_only_requested_format(self, db_session):
        """media_types selects image rows without relying on projected column names."""
        async with db_session() as session:
            image = await self._create_item(session, file_format="png")
            video = await self._create_item(session, file_format="mp4")
            query = build_filtered_query(
                select(MediaItem).where(MediaItem.id.in_([image.id, video.id])),
                media_types="images",
            )
            result = await session.execute(query)

        assert {item.id for item in result.scalars()} == {image.id}

    async def test_is_generated_true_selects_generated_rows(self, db_session):
        """is_generated=True returns rows with generation provenance."""
        async with db_session() as session:
            generated = await self._create_item(
                session, file_format="png", generation_metadata='{"prompt":"sunrise"}'
            )
            imported = await self._create_item(session, file_format="png")
            query = build_filtered_query(
                select(MediaItem).where(MediaItem.id.in_([generated.id, imported.id])),
                is_generated=True,
            )
            result = await session.execute(query)

        assert {item.id for item in result.scalars()} == {generated.id}

    async def test_is_generated_false_selects_rows_without_generation_provenance(self, db_session):
        """is_generated=False returns rows without generation provenance."""
        async with db_session() as session:
            generated = await self._create_item(
                session, file_format="png", generation_metadata='{"prompt":"sunrise"}'
            )
            imported = await self._create_item(session, file_format="png")
            query = build_filtered_query(
                select(MediaItem).where(MediaItem.id.in_([generated.id, imported.id])),
                is_generated=False,
            )
            result = await session.execute(query)

        assert {item.id for item in result.scalars()} == {imported.id}

    async def test_is_imported_uses_lineage_metadata_not_storage(self, db_session):
        """Imported provenance follows generation history metadata, regardless of path."""
        async with db_session() as session:
            plain_import = await self._create_item(
                session, file_format="png", file_path="/managed/looks-generated.png"
            )
            external_import = await self._create_item(
                session,
                file_format="png",
                file_path="/sources/external.png",
                generation_metadata='{"source":"external"}',
            )
            generated = await self._create_item(
                session,
                file_format="png",
                file_path="/sources/generated.png",
                generation_metadata='{"source":"stimma","prompt":"sunrise"}',
            )
            query = build_filtered_query(
                select(MediaItem).where(
                    MediaItem.id.in_([plain_import.id, external_import.id, generated.id])
                ),
                is_imported=True,
            )
            result = await session.execute(query)

        assert {item.id for item in result.scalars()} == {
            plain_import.id,
            external_import.id,
        }

    async def test_exclude_category_skips_media_type_filter(self, db_session):
        """Excluding media_types leaves all controlled formats eligible."""
        async with db_session() as session:
            image = await self._create_item(session, file_format="png")
            video = await self._create_item(session, file_format="mp4")
            query = build_filtered_query(
                select(MediaItem).where(MediaItem.id.in_([image.id, video.id])),
                media_types="images",
                exclude_category="media_types",
            )
            result = await session.execute(query)

        assert {item.id for item in result.scalars()} == {image.id, video.id}

    async def test_multiple_filters_compose_as_intersection(self, db_session):
        """Multiple filter categories select only the row satisfying every predicate."""
        async with db_session() as session:
            matching = await self._create_item(
                session,
                file_format="png",
                file_path="/controlled/one/match.png",
                width=100,
                height=100,
                generation_metadata='{"prompt":"sunrise"}',
            )
            not_generated = await self._create_item(
                session,
                file_format="png",
                file_path="/controlled/one/import.png",
            )
            wrong_resolution = await self._create_item(
                session,
                file_format="png",
                file_path="/controlled/one/medium.png",
                width=1000,
                height=1000,
                generation_metadata='{"prompt":"sunrise"}',
            )
            wrong_folder = await self._create_item(
                session,
                file_format="png",
                file_path="/controlled/two/other.png",
                width=100,
                height=100,
                generation_metadata='{"prompt":"sunrise"}',
            )
            wrong_type = await self._create_item(
                session,
                file_format="mp3",
                file_path="/controlled/one/audio.mp3",
                width=0,
                height=0,
                generation_metadata='{"prompt":"sunrise"}',
            )
            candidates = [matching, not_generated, wrong_resolution, wrong_folder, wrong_type]
            query = build_filtered_query(
                select(MediaItem).where(MediaItem.id.in_([item.id for item in candidates])),
                media_types="images,videos",
                is_generated=True,
                resolutions="small,large",
                folders="/controlled/one",
            )
            result = await session.execute(query)

        assert {item.id for item in result.scalars()} == {matching.id}

    @staticmethod
    async def _create_item(session, **kwargs):
        """Seed one isolated candidate row for an executable predicate check."""
        from tests.helpers.media import create_media_item

        return await create_media_item(session, **kwargs)

"""
Tests for browse/media listing filter functionality.

Tests cover:
- Media type filtering (images, videos, specific formats)
- Resolution filtering (small, medium, large)
- Folder path filtering
- Date range filtering
- Generated image filtering
- Sort options
- Prompt search
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from httpx import AsyncClient

from tests.helpers.media import create_media_item


class TestMediaTypeFiltering:
    """Tests for media_types and excluded_media_types filters."""

    async def test_filter_images_only(self, client: AsyncClient, mixed_media):
        """Test filtering to show only images."""
        response = await client.get("/api/media", params={"media_types": "images"})
        assert response.status_code == 200

        data = response.json()
        # Should only have image formats
        for item in data["items"]:
            assert item["file_format"] in ["png", "jpg", "jpeg", "gif", "webp", "bmp"]

    async def test_filter_videos_only(self, client: AsyncClient, mixed_media):
        """Test filtering to show only videos."""
        response = await client.get("/api/media", params={"media_types": "videos"})
        assert response.status_code == 200

        data = response.json()
        # Should only have video formats
        for item in data["items"]:
            assert item["file_format"] in ["mp4", "webm", "mov", "avi", "mkv", "ogg"]

    async def test_filter_images_and_videos(self, client: AsyncClient, mixed_media):
        """Test filtering for both images and videos explicitly."""
        response = await client.get("/api/media", params={"media_types": "images,videos"})
        assert response.status_code == 200

        data = response.json()
        # Should include both images and videos
        formats = {item["file_format"] for item in data["items"]}
        # Should have at least one image and one video format
        image_formats = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
        video_formats = {"mp4", "webm", "mov", "avi", "mkv", "ogg"}
        assert formats & image_formats  # Has some images
        assert formats & video_formats  # Has some videos

    async def test_exclude_videos(self, client: AsyncClient, mixed_media):
        """Test excluding videos."""
        response = await client.get("/api/media", params={"excluded_media_types": "videos"})
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["file_format"] not in ["mp4", "webm", "mov", "avi", "mkv", "ogg"]

    async def test_exclude_images(self, client: AsyncClient, mixed_media):
        """Test excluding images (only videos should remain)."""
        response = await client.get("/api/media", params={"excluded_media_types": "images"})
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["file_format"] in ["mp4", "webm", "mov", "avi", "mkv", "ogg"]


class TestResolutionFiltering:
    """Tests for resolutions and excluded_resolutions filters."""

    async def test_filter_small_resolution(self, client: AsyncClient, varied_resolution_media):
        """Test filtering for small resolution (<0.8 MP)."""
        response = await client.get("/api/media", params={"resolutions": "small"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["megapixels"] < 0.8

    async def test_filter_medium_resolution(self, client: AsyncClient, varied_resolution_media):
        """Test filtering for medium resolution (0.8-1.5 MP)."""
        response = await client.get("/api/media", params={"resolutions": "medium"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert 0.8 <= item["megapixels"] < 1.5

    async def test_filter_large_resolution(self, client: AsyncClient, varied_resolution_media):
        """Test filtering for large resolution (>=1.5 MP)."""
        response = await client.get("/api/media", params={"resolutions": "large"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["megapixels"] >= 1.5

    async def test_exclude_small_resolution(self, client: AsyncClient, varied_resolution_media):
        """Test excluding small resolution images."""
        response = await client.get("/api/media", params={"excluded_resolutions": "small"})
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["megapixels"] >= 0.8

    async def test_multiple_resolutions(self, client: AsyncClient, varied_resolution_media):
        """Test filtering by multiple resolutions (OR logic)."""
        response = await client.get("/api/media", params={"resolutions": "small,large"})
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            # Should be either small (<0.8) or large (>=1.5)
            assert item["megapixels"] < 0.8 or item["megapixels"] >= 1.5


class TestFolderFiltering:
    """Tests for folders and excluded_folders filters."""

    async def test_filter_by_folder(self, client: AsyncClient, folder_organized_media):
        """Test filtering by folder path."""
        response = await client.get("/api/media", params={"folders": "/photos/vacation"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["file_path"].startswith("/photos/vacation/")

    async def test_filter_multiple_folders(self, client: AsyncClient, folder_organized_media):
        """Test filtering by multiple folders (OR logic)."""
        response = await client.get("/api/media", params={"folders": "/photos/vacation,/photos/work"})
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert (item["file_path"].startswith("/photos/vacation/") or
                    item["file_path"].startswith("/photos/work/"))

    async def test_exclude_folder(self, client: AsyncClient, folder_organized_media):
        """Test excluding a folder."""
        response = await client.get("/api/media", params={"excluded_folders": "/photos/vacation"})
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert not item["file_path"].startswith("/photos/vacation/")


class TestDateFiltering:
    """Tests for created_after and created_before filters."""

    async def test_filter_created_after(self, client: AsyncClient, date_varied_media):
        """Test filtering by created_after date."""
        # Filter for items created in the last 7 days
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        response = await client.get("/api/media", params={"created_after": week_ago})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1

    async def test_filter_created_before(self, client: AsyncClient, date_varied_media):
        """Test filtering by created_before date."""
        # Filter for items created more than 20 days ago
        twenty_days_ago = (datetime.now() - timedelta(days=20)).isoformat()
        response = await client.get("/api/media", params={"created_before": twenty_days_ago})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1

    async def test_filter_date_range(self, client: AsyncClient, date_varied_media):
        """Test filtering by date range (both after and before)."""
        two_weeks_ago = (datetime.now() - timedelta(days=14)).isoformat()
        one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()

        response = await client.get("/api/media", params={
            "created_after": two_weeks_ago,
            "created_before": one_week_ago
        })
        assert response.status_code == 200
        # May have items or not depending on test data


class TestGeneratedImageFiltering:
    """Tests for is_generated filter."""

    async def test_filter_generated_only(self, client: AsyncClient, generated_and_regular_media):
        """Test filtering for generated images only."""
        response = await client.get("/api/media", params={"is_generated": "true"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            # is_generated is computed from generation_metadata being non-null
            assert item["generation_metadata"] is not None

    async def test_filter_non_generated_only(self, client: AsyncClient, generated_and_regular_media):
        """Test filtering for non-generated images only."""
        response = await client.get("/api/media", params={"is_generated": "false"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["generation_metadata"] is None


class TestPromptSearch:
    """Tests for prompt_query search."""

    async def test_search_by_prompt(self, client: AsyncClient, generated_and_regular_media):
        """Test searching by extracted prompt."""
        response = await client.get("/api/media", params={"prompt_query": "sunset"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert "sunset" in item.get("extracted_prompt", "").lower()

    async def test_prompt_search_no_results(self, client: AsyncClient, generated_and_regular_media):
        """Test prompt search with no matching results."""
        response = await client.get("/api/media", params={"prompt_query": "xyznonexistent123"})
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []


class TestSortOptions:
    """Tests for sort_by parameter."""

    async def test_sort_created_desc(self, client: AsyncClient, date_varied_media):
        """Test sorting by creation date descending (default)."""
        response = await client.get("/api/media", params={"sort_by": "created_desc"})
        assert response.status_code == 200

        data = response.json()
        items = data["items"]
        if len(items) >= 2:
            # Items with created_date should be in descending order
            dates = [item.get("created_date") for item in items if item.get("created_date")]
            if len(dates) >= 2:
                assert dates == sorted(dates, reverse=True)

    async def test_sort_created_asc(self, client: AsyncClient, date_varied_media):
        """Test sorting by creation date ascending."""
        response = await client.get("/api/media", params={"sort_by": "created_asc"})
        assert response.status_code == 200

        data = response.json()
        items = data["items"]
        if len(items) >= 2:
            dates = [item.get("created_date") for item in items if item.get("created_date")]
            if len(dates) >= 2:
                assert dates == sorted(dates)

    async def test_sort_indexed_desc(self, client: AsyncClient, seeded_media):
        """Test sorting by indexed date descending."""
        response = await client.get("/api/media", params={"sort_by": "indexed_desc"})
        assert response.status_code == 200

        data = response.json()
        # Just verify it returns successfully
        assert "items" in data

    async def test_sort_random(self, client: AsyncClient, seeded_media):
        """Test random sorting with seed for reproducibility."""
        # Request with same seed should give same order
        response1 = await client.get("/api/media", params={"sort_by": "random", "random_seed": 42})
        assert response1.status_code == 200

        response2 = await client.get("/api/media", params={"sort_by": "random", "random_seed": 42})
        assert response2.status_code == 200

        ids1 = [item["id"] for item in response1.json()["items"]]
        ids2 = [item["id"] for item in response2.json()["items"]]
        assert ids1 == ids2  # Same seed = same order


class TestCombinedFilters:
    """Tests for combining multiple filters."""

    async def test_images_and_large_resolution(self, client: AsyncClient, mixed_media, varied_resolution_media):
        """Test combining media type and resolution filters."""
        response = await client.get("/api/media", params={
            "media_types": "images",
            "resolutions": "large"
        })
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["file_format"] in ["png", "jpg", "jpeg", "gif", "webp", "bmp"]
            assert item["megapixels"] >= 1.5

    async def test_generated_with_prompt_search(self, client: AsyncClient, generated_and_regular_media):
        """Test combining is_generated filter with prompt search."""
        response = await client.get("/api/media", params={
            "is_generated": "true",
            "prompt_query": "sunset"
        })
        assert response.status_code == 200

        data = response.json()
        for item in data["items"]:
            assert item["generation_metadata"] is not None
            assert "sunset" in item.get("extracted_prompt", "").lower()


class TestFilterCounts:
    """Tests for the /api/filter-counts facet endpoint."""

    async def test_filter_counts_with_tags(self, client: AsyncClient, seeded_media):
        """Opening the facet panel must not raise a SQLAlchemy auto-correlation error.

        Regression for the tag-count query joining media_tags into the outer FROM while
        build_filtered_query's auto-delete EXISTS subquery also selects from media_tags:
        auto-correlation stripped every FROM clause from the subquery and the endpoint
        500'd. See media_pending_autodelete() / correlate(MediaItem) in query_builder.py.
        """
        # Assign a tag so the Tag -> media_tags -> media_items join produces rows.
        await client.post("/api/tags", json={"tag_text": "facet-tag"})
        await client.post(
            f"/api/media/{seeded_media[0].id}/tags",
            json={"tags": ["facet-tag"]},
        )

        response = await client.get("/api/filter-counts")
        assert response.status_code == 200

        data = response.json()
        tag_counts = {t["tag"]: t["usage_count"] for t in data.get("tags", [])}
        assert tag_counts.get("facet-tag", 0) >= 1

    async def test_filter_counts_filtered_by_tag(self, client: AsyncClient, seeded_media):
        """The auto-delete EXISTS subqueries must also survive an active tag filter."""
        create = await client.post("/api/tags", json={"tag_text": "active-filter"})
        tag_id = create.json()["id"]
        await client.post(
            f"/api/media/{seeded_media[0].id}/tags",
            json={"tags": ["active-filter"]},
        )

        response = await client.get("/api/filter-counts", params={"tag_ids": str(tag_id)})
        assert response.status_code == 200


# Fixtures specific to this test module

@pytest.fixture
async def seeded_media(db_session):
    """Create basic test media items."""
    async with db_session() as session:
        from tests.helpers.media import create_test_media
        items = await create_test_media(session, count=5)
        yield items


@pytest.fixture
async def mixed_media(db_session):
    """Create media with different formats (images and videos)."""
    import uuid
    prefix = str(uuid.uuid4())[:8]
    async with db_session() as session:
        items = []
        # Images
        items.append(await create_media_item(session, materialize_asset=True, file_format="png", file_path=Path(f"/test/{prefix}/image1.png")))
        items.append(await create_media_item(session, materialize_asset=True, file_format="jpg", file_path=Path(f"/test/{prefix}/image2.jpg")))
        items.append(await create_media_item(session, materialize_asset=True, file_format="gif", file_path=Path(f"/test/{prefix}/image3.gif")))
        # Videos
        items.append(await create_media_item(session, materialize_asset=True, file_format="mp4", file_path=Path(f"/test/{prefix}/video1.mp4")))
        items.append(await create_media_item(session, materialize_asset=True, file_format="webm", file_path=Path(f"/test/{prefix}/video2.webm")))
        yield items


@pytest.fixture
async def varied_resolution_media(db_session):
    """Create media with different resolutions."""
    async with db_session() as session:
        items = []
        # Small: < 0.8 MP (e.g., 800x800 = 0.64 MP)
        items.append(await create_media_item(session, materialize_asset=True, width=800, height=800))
        # Medium: 0.8-1.5 MP (e.g., 1000x1000 = 1.0 MP)
        items.append(await create_media_item(session, materialize_asset=True, width=1000, height=1000))
        # Large: >= 1.5 MP (e.g., 1500x1500 = 2.25 MP)
        items.append(await create_media_item(session, materialize_asset=True, width=1500, height=1500))
        yield items


@pytest.fixture
async def folder_organized_media(db_session):
    """Create media in different folder paths."""
    import uuid
    suffix = str(uuid.uuid4())[:8]
    async with db_session() as session:
        items = []
        items.append(await create_media_item(session, materialize_asset=True, file_path=Path(f"/photos/vacation/beach_{suffix}.jpg")))
        items.append(await create_media_item(session, materialize_asset=True, file_path=Path(f"/photos/vacation/mountain_{suffix}.jpg")))
        items.append(await create_media_item(session, materialize_asset=True, file_path=Path(f"/photos/work/meeting_{suffix}.jpg")))
        items.append(await create_media_item(session, materialize_asset=True, file_path=Path(f"/photos/family/birthday_{suffix}.jpg")))
        yield items


@pytest.fixture
async def date_varied_media(db_session):
    """Create media with different creation dates."""
    async with db_session() as session:
        items = []
        now = datetime.now()
        # Recent (3 days ago)
        items.append(await create_media_item(session, materialize_asset=True, created_date=now - timedelta(days=3)))
        # Week ago
        items.append(await create_media_item(session, materialize_asset=True, created_date=now - timedelta(days=10)))
        # Month ago
        items.append(await create_media_item(session, materialize_asset=True, created_date=now - timedelta(days=30)))
        yield items


@pytest.fixture
async def generated_and_regular_media(db_session):
    """Create mix of generated and regular media."""
    async with db_session() as session:
        items = []
        # Generated images with prompts (generation_metadata marks as generated)
        items.append(await create_media_item(
            session,
            materialize_asset=True,
            generation_metadata='{"model": "test"}',
            extracted_prompt="A beautiful sunset over the ocean",
            vlm_caption="sunset scene"
        ))
        items.append(await create_media_item(
            session,
            materialize_asset=True,
            generation_metadata='{"model": "test"}',
            extracted_prompt="A mountain landscape with snow",
            vlm_caption="mountain scene"
        ))
        # Regular images (no generation_metadata)
        items.append(await create_media_item(session))
        items.append(await create_media_item(session))
        yield items

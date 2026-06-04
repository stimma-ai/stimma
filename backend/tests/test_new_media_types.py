"""
Tests for new media types: audio, text, sets, and grids.

Tests cover:
- Media type filtering for audio, text, sets, grids
- Processing skip behavior for non-visual types
- Content API endpoint for structured types
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from httpx import AsyncClient
from sqlalchemy import select

from database import MediaItem
from tests.helpers.media import create_media_item


# Helper functions for creating new media types

async def create_audio_item(
    session,
    *,
    file_format: str = "mp3",
    duration: float = 60.0,
    audio_sample_rate: int = 44100,
    audio_channels: int = 2,
    audio_bit_depth: int = None,
    audio_bitrate: int = 128000,
    audio_codec: str = None,
    **kwargs
) -> MediaItem:
    """Create an audio media item with metadata."""
    # Default codec based on format
    if audio_codec is None:
        audio_codec = file_format

    return await create_media_item(
        session,
        file_format=file_format,
        width=0,
        height=0,
        duration=duration,
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        audio_bit_depth=audio_bit_depth,
        audio_bitrate=audio_bitrate,
        audio_codec=audio_codec,
        clip_status="skipped",
        vlm_caption_status="skipped",
        face_detection_status="skipped",
        **kwargs
    )


async def create_text_item(
    session,
    *,
    content: str = "Test content",
    title: str = None,
    file_path: Path = None,
    **kwargs
) -> MediaItem:
    """Create a .md (markdown) item.

    If file_path is provided, writes a real markdown file to disk.
    Otherwise creates a DB record with fake path (for filtering tests only).
    """
    # Store only frontmatter in raw_metadata (content is read from disk at display time)
    raw_metadata = json.dumps({
        "frontmatter": {"title": title} if title else {}
    })

    # If a real file path is provided, write the markdown file
    if file_path is not None:
        import frontmatter as fm
        post = fm.Post(content)
        if title:
            post['title'] = title
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(fm.dumps(post))

    return await create_media_item(
        session,
        file_format="md",
        file_path=file_path,
        width=0,
        height=0,
        raw_metadata=raw_metadata,
        clip_status="skipped",
        vlm_caption_status="skipped",
        face_detection_status="skipped",
        **kwargs
    )


async def create_set_item(
    session,
    *,
    items: list[dict],
    title: str = None,
    **kwargs
) -> MediaItem:
    """Create a .stimmaset.json item with references in raw_metadata."""
    raw_metadata = json.dumps({
        "version": 1,
        "title": title,
        "items": items
    })
    return await create_media_item(
        session,
        file_format="stimmaset.json",
        width=0,
        height=0,
        raw_metadata=raw_metadata,
        clip_status="skipped",
        vlm_caption_status="skipped",
        face_detection_status="skipped",
        **kwargs
    )


async def create_grid_item(
    session,
    *,
    rows: int,
    cols: int,
    cells: list[dict],
    title: str = None,
    row_headers: list[str] = None,
    col_headers: list[str] = None,
    **kwargs
) -> MediaItem:
    """Create a .stimmagrid.json item with grid data in raw_metadata."""
    raw_metadata = json.dumps({
        "version": 1,
        "title": title,
        "rows": rows,
        "cols": cols,
        "row_headers": row_headers or [],
        "col_headers": col_headers or [],
        "cells": cells
    })
    return await create_media_item(
        session,
        file_format="stimmagrid.json",
        width=0,
        height=0,
        raw_metadata=raw_metadata,
        clip_status="skipped",
        vlm_caption_status="skipped",
        face_detection_status="skipped",
        **kwargs
    )


# Fixtures

@pytest.fixture
async def mixed_all_types(db_session):
    """Create media of all types for filtering tests."""
    async with db_session() as session:
        items = []

        # Images
        items.append(await create_media_item(session, file_format="png"))
        items.append(await create_media_item(session, file_format="jpg"))

        # Videos
        items.append(await create_media_item(session, file_format="mp4"))

        # Audio
        items.append(await create_audio_item(session, file_format="mp3"))
        items.append(await create_audio_item(session, file_format="wav"))

        # Text
        items.append(await create_text_item(session, content="Hello world"))

        # Sets
        items.append(await create_set_item(session, items=[{"path": "a.png"}]))

        # Grids
        items.append(await create_grid_item(session, rows=2, cols=2, cells=[]))

        yield items


@pytest.fixture
async def audio_items(db_session):
    """Create audio items for testing."""
    async with db_session() as session:
        items = [
            await create_audio_item(session, file_format="mp3", duration=120.0),
            await create_audio_item(session, file_format="wav", duration=30.0),
            await create_audio_item(session, file_format="flac", duration=180.0),
        ]
        yield items


@pytest.fixture
async def text_item(db_session, tmp_path):
    """Create a text item with real file for testing content API."""
    md_file = tmp_path / "test_doc.md"
    async with db_session() as session:
        item = await create_text_item(
            session,
            content="This is test content for the text viewer.",
            title="Test Document",
            file_path=md_file
        )
        yield item


@pytest.fixture
async def set_with_refs(db_session):
    """Create a set that references other media items."""
    import uuid
    prefix = str(uuid.uuid4())[:8]
    async with db_session() as session:
        # First create some image items
        img1 = await create_media_item(
            session,
            file_format="png",
            file_path=Path(f"/test/images/{prefix}_image1.png")
        )
        img2 = await create_media_item(
            session,
            file_format="jpg",
            file_path=Path(f"/test/images/{prefix}_image2.jpg")
        )

        # Create a set that references them
        set_item = await create_set_item(
            session,
            items=[
                {"path": f"/test/images/{prefix}_image1.png"},
                {"path": f"/test/images/{prefix}_image2.jpg"},
                {"path": "/nonexistent/missing.png", "caption": "Missing image"}
            ],
            title="Test Set",
            file_path=Path(f"/test/sets/{prefix}_my-set.stimmaset.json")
        )

        yield set_item, [img1, img2]


@pytest.fixture
async def grid_with_refs(db_session):
    """Create a grid that references other media items."""
    import uuid
    prefix = str(uuid.uuid4())[:8]
    async with db_session() as session:
        # First create some image items
        imgs = []
        for r in range(2):
            for c in range(2):
                img = await create_media_item(
                    session,
                    file_format="png",
                    file_path=Path(f"/test/grid/{prefix}_r{r}c{c}.png")
                )
                imgs.append(img)

        # Create a grid that references them
        grid_item = await create_grid_item(
            session,
            rows=2,
            cols=2,
            cells=[
                {"row": 0, "col": 0, "path": f"/test/grid/{prefix}_r0c0.png"},
                {"row": 0, "col": 1, "path": f"/test/grid/{prefix}_r0c1.png"},
                {"row": 1, "col": 0, "path": f"/test/grid/{prefix}_r1c0.png"},
                {"row": 1, "col": 1, "path": f"/test/grid/{prefix}_r1c1.png"},
            ],
            title="Test Grid",
            row_headers=["Row A", "Row B"],
            col_headers=["Col 1", "Col 2"],
            file_path=Path(f"/test/grids/{prefix}_my-grid.stimmagrid.json")
        )

        yield grid_item, imgs


class TestMediaTypeFiltering:
    """Tests for filtering by new media types."""

    async def test_filter_audio_only(self, client: AsyncClient, mixed_all_types):
        """Filter to show only audio files."""
        response = await client.get("/api/media", params={"media_types": "audio"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 2  # We created 2 audio items
        for item in data["items"]:
            assert item["file_format"] in ["mp3", "wav", "flac", "aac", "m4a", "ogg"]

    async def test_filter_text_only(self, client: AsyncClient, mixed_all_types):
        """Filter to show only text (markdown) files."""
        response = await client.get("/api/media", params={"media_types": "text"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["file_format"] == "md"

    async def test_filter_sets_only(self, client: AsyncClient, mixed_all_types):
        """Filter to show only set files."""
        response = await client.get("/api/media", params={"media_types": "sets"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["file_format"] == "stimmaset.json"

    async def test_filter_grids_only(self, client: AsyncClient, mixed_all_types):
        """Filter to show only grid files."""
        response = await client.get("/api/media", params={"media_types": "grids"})
        assert response.status_code == 200

        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["file_format"] == "stimmagrid.json"

    async def test_filter_structured_all(self, client: AsyncClient, mixed_all_types):
        """Filter for all structured types (text, sets, grids)."""
        response = await client.get("/api/media", params={"media_types": "structured"})
        assert response.status_code == 200

        data = response.json()
        structured_formats = {"md", "stimmaset.json", "stimmagrid.json"}
        for item in data["items"]:
            assert item["file_format"] in structured_formats

    async def test_exclude_audio(self, client: AsyncClient, mixed_all_types):
        """Exclude audio from results."""
        response = await client.get("/api/media", params={"excluded_media_types": "audio"})
        assert response.status_code == 200

        data = response.json()
        audio_formats = {"mp3", "wav", "flac", "aac", "m4a", "ogg"}
        for item in data["items"]:
            assert item["file_format"] not in audio_formats

    async def test_filter_multiple_new_types(self, client: AsyncClient, mixed_all_types):
        """Filter for audio and text together."""
        response = await client.get("/api/media", params={"media_types": "audio,text"})
        assert response.status_code == 200

        data = response.json()
        allowed_formats = {"mp3", "wav", "flac", "aac", "m4a", "ogg", "md"}
        for item in data["items"]:
            assert item["file_format"] in allowed_formats


class TestContentAPI:
    """Tests for /api/media/{id}/content endpoint."""

    async def test_get_text_content(self, client: AsyncClient, text_item):
        """Get parsed content from markdown item."""
        response = await client.get(f"/api/media/{text_item.id}/content")
        assert response.status_code == 200

        data = response.json()
        assert data["format"] == "markdown"
        assert "content" in data
        assert data["content"] == "This is test content for the text viewer."
        assert "frontmatter" in data
        assert data["frontmatter"]["title"] == "Test Document"
        assert "images" in data

    async def test_get_set_content_resolves_references(self, client: AsyncClient, set_with_refs):
        """Set content returns resolved media references."""
        set_item, ref_images = set_with_refs

        response = await client.get(f"/api/media/{set_item.id}/content")
        assert response.status_code == 200

        data = response.json()
        assert "items" in data
        assert len(data["items"]) == 3

        # First two should be resolved
        assert data["items"][0]["resolved"] is not None
        assert data["items"][0]["resolved"]["media_id"] == ref_images[0].id
        assert data["items"][1]["resolved"] is not None
        assert data["items"][1]["resolved"]["media_id"] == ref_images[1].id

        # Third should be unresolved (missing)
        assert data["items"][2]["resolved"] is None
        assert data["items"][2]["caption"] == "Missing image"

    async def test_get_grid_content_resolves_references(self, client: AsyncClient, grid_with_refs):
        """Grid content returns resolved media references."""
        grid_item, ref_images = grid_with_refs

        response = await client.get(f"/api/media/{grid_item.id}/content")
        assert response.status_code == 200

        data = response.json()
        assert data["rows"] == 2
        assert data["cols"] == 2
        assert "cells" in data
        assert len(data["cells"]) == 4

        # All cells should be resolved
        for cell in data["cells"]:
            assert cell["resolved"] is not None

    async def test_content_404_for_image(self, client: AsyncClient, db_session):
        """Content endpoint returns 404 for non-structured types."""
        async with db_session() as session:
            image_item = await create_media_item(session, file_format="png")

        response = await client.get(f"/api/media/{image_item.id}/content")
        assert response.status_code == 404

    async def test_content_404_for_video(self, client: AsyncClient, db_session):
        """Content endpoint returns 404 for video type."""
        async with db_session() as session:
            video_item = await create_media_item(session, file_format="mp4")

        response = await client.get(f"/api/media/{video_item.id}/content")
        assert response.status_code == 404


class TestAudioMetadata:
    """Tests for audio-specific metadata."""

    async def test_audio_has_duration(self, client: AsyncClient, audio_items):
        """Audio items should have duration field."""
        for audio_item in audio_items:
            response = await client.get(f"/api/media/{audio_item.id}")
            assert response.status_code == 200

            data = response.json()
            assert data["duration"] is not None
            assert data["duration"] > 0

    async def test_audio_no_visual_dimensions(self, client: AsyncClient, audio_items):
        """Audio items have zero dimensions."""
        audio_item = audio_items[0]
        response = await client.get(f"/api/media/{audio_item.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["width"] == 0
        assert data["height"] == 0

    async def test_audio_has_sample_rate(self, client: AsyncClient, audio_items):
        """Audio items should have sample_rate field."""
        audio_item = audio_items[0]
        response = await client.get(f"/api/media/{audio_item.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["audio_sample_rate"] == 44100

    async def test_audio_has_channels(self, client: AsyncClient, audio_items):
        """Audio items should have channels field."""
        audio_item = audio_items[0]
        response = await client.get(f"/api/media/{audio_item.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["audio_channels"] == 2  # Stereo

    async def test_audio_has_bitrate(self, client: AsyncClient, audio_items):
        """Audio items should have bitrate field."""
        audio_item = audio_items[0]
        response = await client.get(f"/api/media/{audio_item.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["audio_bitrate"] == 128000

    async def test_audio_has_codec(self, client: AsyncClient, audio_items):
        """Audio items should have codec field."""
        audio_item = audio_items[0]
        response = await client.get(f"/api/media/{audio_item.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["audio_codec"] == "mp3"


class TestProcessingSkip:
    """Tests that non-visual types skip AI processing."""

    async def test_audio_skips_clip(self, db_session, audio_items):
        """Audio should have clip_status = 'skipped'."""
        async with db_session() as session:
            for audio_item in audio_items:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == audio_item.id)
                )
                item = result.scalar_one()
                assert item.clip_status == "skipped"

    async def test_audio_skips_face_detection(self, db_session, audio_items):
        """Audio should have face_detection_status = 'skipped'."""
        async with db_session() as session:
            for audio_item in audio_items:
                result = await session.execute(
                    select(MediaItem).where(MediaItem.id == audio_item.id)
                )
                item = result.scalar_one()
                assert item.face_detection_status == "skipped"

    async def test_text_skips_all_ai_processing(self, db_session, text_item):
        """Text should skip all AI processing phases."""
        async with db_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == text_item.id)
            )
            item = result.scalar_one()
            assert item.clip_status == "skipped"
            assert item.face_detection_status == "skipped"
            assert item.vlm_caption_status == "skipped"

    async def test_set_skips_all_ai_processing(self, db_session, set_with_refs):
        """Set should skip all AI processing phases."""
        set_item, _ = set_with_refs
        async with db_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == set_item.id)
            )
            item = result.scalar_one()
            assert item.clip_status == "skipped"
            assert item.face_detection_status == "skipped"
            assert item.vlm_caption_status == "skipped"

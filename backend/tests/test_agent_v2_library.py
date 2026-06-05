"""Tests for the v2 library tool browse surface."""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from database import Keyword, Marker, MediaKeyword, MediaMarker, MediaTag, MediaToolLineage, Tag
from tests.helpers.media import create_media_item
from agent.v2.tools.library import library


async def test_library_browse_schema_exposes_progressive_facets(db_session):
    async with db_session() as session:
        result = await library(action="browse_schema", session=session)

    data = json.loads(result)
    assert data["action"] == "browse"
    assert "tags" in data["filters"]
    assert "browse_options" in data["filters"]["tags"]["discovery"]
    assert "tools" in data["option_facets"]


async def test_library_browse_supports_structured_filters(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        image_item = await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/hero.png"),
            file_format="png",
            vlm_caption="hero portrait",
            extracted_prompt="cinematic hero portrait",
            generation_metadata=json.dumps({"prompt": "hero portrait"}),
            tool_id="comfyui:turbo-gen",
            created_date=datetime.now() - timedelta(days=1),
        )
        await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/reference.jpg"),
            file_format="jpg",
            vlm_caption="reference portrait",
            extracted_prompt="reference shot",
            created_date=datetime.now() - timedelta(days=2),
        )

        tag = Tag(tag_text=f"portrait-{prefix}")
        session.add(tag)
        await session.flush()
        session.add(MediaTag(media_id=image_item.id, tag_id=tag.id))
        session.add(MediaToolLineage(media_id=image_item.id, full_tool_id="comfyui:turbo-gen"))
        await session.commit()

        result = await library(
            action="browse",
            filters={
                "query": "hero",
                "generated": True,
                "media_types": {"include": ["images"]},
                "tags": {"include": [f"portrait-{prefix}"]},
                "tools": {"include": ["comfyui:turbo-gen"]},
            },
            sort_by="created_desc",
            limit=10,
            offset=0,
            session=session,
        )

    data = json.loads(result)
    assert data["total"] == 1
    assert data["has_more"] is False
    assert data["items"][0]["media_id"] == image_item.id
    assert data["applied_filters"]["generated"] is True
    assert data["sort"]["by"] == "created_desc"


async def test_library_browse_options_returns_dynamic_tag_counts(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        generated_item = await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/generated-one.png"),
            file_format="png",
            generation_metadata=json.dumps({"prompt": "generated"}),
            created_date=datetime.now() - timedelta(days=1),
        )
        imported_item = await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/imported-one.png"),
            file_format="png",
            created_date=datetime.now() - timedelta(days=3),
        )

        portrait = Tag(tag_text=f"portrait-{prefix}")
        landscape = Tag(tag_text=f"landscape-{prefix}")
        session.add_all([portrait, landscape])
        await session.flush()
        session.add_all([
            MediaTag(media_id=generated_item.id, tag_id=portrait.id),
            MediaTag(media_id=imported_item.id, tag_id=landscape.id),
        ])
        await session.commit()

        result = await library(
            action="browse_options",
            facet="tags",
            filters={"generated": True, "media_types": {"include": ["images"]}},
            query=prefix[:4],
            limit=10,
            session=session,
        )

    data = json.loads(result)
    assert data["facet"] == "tags"
    assert data["items"] == [{"id": portrait.id, "label": f"portrait-{prefix}", "count": 1}]
    assert data["next_cursor"] is None


async def test_library_browse_options_supports_folder_pagination(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        for idx in range(3):
            await create_media_item(
                session,
                file_path=Path(f"/library/{prefix}/folder-{idx}/item-{idx}.png"),
                file_format="png",
                created_date=datetime.now() - timedelta(days=idx),
            )

        first_page = await library(
            action="browse_options",
            facet="folders",
            limit=2,
            query=prefix,
            session=session,
        )
        first_data = json.loads(first_page)
        second_page = await library(
            action="browse_options",
            facet="folders",
            limit=2,
            query=prefix,
            cursor=first_data["next_cursor"],
            session=session,
        )

    assert len(first_data["items"]) == 2
    assert first_data["next_cursor"] is not None
    second_data = json.loads(second_page)
    assert len(second_data["items"]) == 1
    assert all(prefix in item["label"] for item in first_data["items"] + second_data["items"])


async def test_library_browse_options_returns_marker_and_keyword_matches(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        item = await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/hero.png"),
            file_format="png",
            generation_metadata=json.dumps({"prompt": "hero"}),
        )
        marker = Marker(name=f"favorite-{prefix}", icon_svg="<svg></svg>", color="#fff")
        keyword = Keyword(keyword_text=f"heroic-{prefix}")
        session.add_all([marker, keyword])
        await session.flush()
        session.add(MediaMarker(media_id=item.id, marker_id=marker.id, source="manual"))
        session.add(MediaKeyword(media_id=item.id, keyword_id=keyword.id))
        await session.commit()

        marker_result = await library(
            action="browse_options",
            facet="markers",
            query=prefix[:4],
            filters={"generated": True},
            session=session,
        )
        keyword_result = await library(
            action="browse_options",
            facet="keywords",
            query=prefix[:4],
            filters={"generated": True},
            session=session,
        )

    marker_data = json.loads(marker_result)
    keyword_data = json.loads(keyword_result)
    assert marker_data["items"] == [{"id": marker.id, "label": f"favorite-{prefix}", "count": 1}]
    assert keyword_data["items"] == [{"id": keyword.id, "label": f"heroic-{prefix}", "count": 1}]

"""Tests for the v2 library tool browse surface."""

import json
import importlib
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from asset_service import commit_revision, create_asset_from_media
from database import (
    AssetMarker,
    AssetTag,
    Board,
    BoardAssetItem,
    BoardSection,
    Keyword,
    Marker,
    MediaKeyword,
    MediaTag,
    MediaToolLineage,
    Project,
    ProjectAsset,
    Tag,
)
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
        reference = await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/reference.jpg"),
            file_format="jpg",
            vlm_caption="reference portrait",
            extracted_prompt="reference shot",
            created_date=datetime.now() - timedelta(days=2),
        )
        image_asset = await create_asset_from_media(session, media_id=image_item.id)
        await create_asset_from_media(session, media_id=reference.id)

        tag = Tag(tag_text=f"portrait-{prefix}")
        session.add(tag)
        await session.flush()
        session.add(AssetTag(asset_id=image_asset.id, tag_id=tag.id))
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
    assert data["items"][0]["asset_id"] == image_asset.id
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
        generated_asset = await create_asset_from_media(
            session, media_id=generated_item.id
        )
        imported_asset = await create_asset_from_media(
            session, media_id=imported_item.id
        )

        portrait = Tag(tag_text=f"portrait-{prefix}")
        landscape = Tag(tag_text=f"landscape-{prefix}")
        session.add_all([portrait, landscape])
        await session.flush()
        session.add_all([
            AssetTag(asset_id=generated_asset.id, tag_id=portrait.id),
            AssetTag(asset_id=imported_asset.id, tag_id=landscape.id),
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
            item = await create_media_item(
                session,
                file_path=Path(f"/library/{prefix}/folder-{idx}/item-{idx}.png"),
                file_format="png",
                created_date=datetime.now() - timedelta(days=idx),
            )
            await create_asset_from_media(session, media_id=item.id)

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
        asset = await create_asset_from_media(session, media_id=item.id)
        marker = Marker(name=f"favorite-{prefix}", icon_svg="<svg></svg>", color="#fff")
        keyword = Keyword(keyword_text=f"heroic-{prefix}")
        session.add_all([marker, keyword])
        await session.flush()
        session.add(AssetMarker(asset_id=asset.id, marker_id=marker.id, source="manual"))
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


async def test_library_organization_actions_target_asset_roots(db_session):
    async with db_session() as session:
        first = await create_media_item(session, file_path=Path("/library/org-first.png"))
        second = await create_media_item(session, file_path=Path("/library/org-second.png"))
        asset = await create_asset_from_media(session, media_id=first.id)
        tagged = json.loads(await library(
            action="tag",
            asset_id=asset.id,
            tags=["agent-kept"],
            operation="add",
            session=session,
        ))
        assert tagged["added"] == 1
        await commit_revision(session, asset_id=asset.id, media_id=second.id)
        board_result = json.loads(await library(
            action="board",
            asset_id=asset.id,
            board_name="Agent Board",
            operation="add",
            session=session,
        ))
        assert board_result["added"] == 1

        assert await session.scalar(
            select(AssetTag.id).where(AssetTag.asset_id == asset.id)
        ) is not None
        assert await session.scalar(
            select(MediaTag.media_id).where(MediaTag.media_id.in_([first.id, second.id]))
        ) is None
        assert await session.scalar(
            select(BoardAssetItem.id).where(BoardAssetItem.asset_id == asset.id)
        ) is not None

        contents = json.loads(await library(
            action="board",
            board_name="Agent Board",
            operation="contents",
            session=session,
        ))
        assert contents["items"][0]["asset_id"] == asset.id
        assert contents["items"][0]["media_id"] == second.id


async def test_library_organization_rejects_mixed_partial_and_trashed_targets(
    db_session
):
    async with db_session() as session:
        first = await create_media_item(session, file_path=Path("/library/ids-first.png"))
        second = await create_media_item(session, file_path=Path("/library/ids-second.png"))
        asset = await create_asset_from_media(session, media_id=first.id)
        await commit_revision(session, asset_id=asset.id, media_id=second.id)
        await session.commit()

        mixed = await library(
            action="tag",
            asset_id=asset.id,
            media_id=second.id,
            tags=["should-not-apply"],
            operation="add",
            session=session,
        )
        assert "Do not mix" in mixed

        partial = await library(
            action="tag",
            asset_ids=[asset.id, 999999999],
            tags=["should-not-apply"],
            operation="add",
            session=session,
        )
        assert "999999999" in partial
        assert await session.scalar(
            select(AssetTag.id).where(AssetTag.asset_id == asset.id)
        ) is None

        # Compatibility fallback accepts an exact old Revision Media ID, but
        # still organizes the stable Asset root.
        old_revision = json.loads(await library(
            action="tag",
            media_id=first.id,
            tags=["old-revision-target"],
            operation="add",
            session=session,
        ))
        assert old_revision["added"] == 1

        asset.state = "trashed"
        asset.deleted_at = datetime.utcnow()
        await session.commit()
        trashed = await library(
            action="tag",
            asset_id=asset.id,
            tags=["nope"],
            operation="add",
            session=session,
        )
        assert "unavailable or trashed" in trashed


async def test_library_board_retains_assets_and_scopes_names_by_project(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path=Path("/library/board-retain.png"))
        asset = await create_asset_from_media(session, media_id=media.id)
        asset.expires_at = datetime.utcnow() + timedelta(hours=1)
        project = Project(name="Agent Board Project")
        session.add(project)
        await session.flush()
        global_board = Board(name="Same Board")
        project_board = Board(name="Same Board", project_id=project.id)
        session.add_all([global_board, project_board])
        await session.commit()

        global_result = json.loads(await library(
            action="board",
            asset_id=asset.id,
            board_name="Same Board",
            operation="add",
            session=session,
        ))
        assert global_result["board"] == "Same Board"
        await session.refresh(asset)
        assert asset.expires_at is None

        asset.expires_at = datetime.utcnow() + timedelta(hours=1)
        project_result = json.loads(await library(
            action="board",
            asset_id=asset.id,
            board_name="Same Board",
            operation="add",
            project_id=project.id,
            session=session,
        ))
        assert project_result["board"] == "Same Board"
        assert await session.scalar(
            select(ProjectAsset.id).where(
                ProjectAsset.project_id == project.id,
                ProjectAsset.asset_id == asset.id,
                ProjectAsset.deleted_at.is_(None),
            )
        ) is not None
        assert asset.expires_at is None

        global_section_board = await session.scalar(
            select(BoardAssetItem)
            .join(BoardSection, BoardSection.id == BoardAssetItem.board_section_id)
            .where(
                BoardSection.board_id == global_board.id,
                BoardAssetItem.asset_id == asset.id,
            )
        )
        assert global_section_board is not None

        duplicate = Board(name="Same Board")
        session.add(duplicate)
        await session.commit()
        ambiguous = await library(
            action="board",
            asset_id=asset.id,
            board_name="Same Board",
            operation="add",
            session=session,
        )
        assert "ambiguous" in ambiguous


async def test_library_save_broadcasts_asset_identity(
    db_session, tmp_path, monkeypatch
):
    library_module = importlib.import_module("agent.v2.tools.library")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "result.md"
    source.write_text("final result")
    output = tmp_path / "managed-output"
    monkeypatch.setattr(
        library_module, "_get_default_folder", lambda workspace_dir=None: str(output)
    )

    events = []

    async def capture(event, payload, *args, **kwargs):
        events.append((event, payload))

    monkeypatch.setattr("utils.websocket.ws_manager.broadcast", capture)
    async with db_session() as session:
        result = json.loads(await library(
            action="save",
            path="result.md",
            workspace_dir=workspace,
            session=session,
        ))

    created = [payload for event, payload in events if event == "asset_created"]
    assert len(created) == 1
    assert created[0]["asset_id"] == result["asset_id"]
    assert created[0]["media_id"] == result["media_id"]
    assert created[0]["revision_id"] is not None

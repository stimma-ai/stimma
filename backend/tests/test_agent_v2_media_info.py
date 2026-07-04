"""Tests for the v2 media_info tool — recorded settings + full ancestor chain."""

import json
import uuid
from pathlib import Path

from database import MediaLineage
from tests.helpers.media import create_media_item
from agent.v2.tools.media_info import media_info


async def _seed_chain(session, prefix):
    """t2i root -> image-to-image edit -> image-to-video using the edit as
    first AND last frame. Returns (root, edit, video)."""
    root = await create_media_item(
        session,
        file_path=Path(f"/library/{prefix}/root.png"),
        file_format="png",
        tool_id="test:text-to-image:alt-model",
        generation_metadata=json.dumps({
            "tool_id": "test:text-to-image:alt-model",
            "task_type": "text-to-image",
            "prompt": "a lighthouse at dusk",
            "parameters": {"steps": 33, "cfg": 5.5, "seed": 987654},
        }),
    )
    edit = await create_media_item(
        session,
        file_path=Path(f"/library/{prefix}/edit.png"),
        file_format="png",
        tool_id="test:image-to-image:editor",
        generation_metadata=json.dumps({
            "tool_id": "test:image-to-image:editor",
            "task_type": "image-to-image",
            "prompt": "make the sky stormy",
            "parameters": {"strength": 0.6, "seed": 1111},
            "source_inputs": [{"media_id": root.id, "role": "source_image"}],
        }),
    )
    session.add(MediaLineage(media_id=edit.id, source_media_id=root.id,
                             source_order=0, task_type="image-to-image"))
    video = await create_media_item(
        session,
        file_path=Path(f"/library/{prefix}/clip.mp4"),
        file_format="mp4",
        tool_id="test:image-to-video:looper",
        generation_metadata=json.dumps({
            "tool_id": "test:image-to-video:looper",
            "task_type": "image-to-video",
            "prompt": "slow clouds roll past",
            "parameters": {"frames": 48, "seed": 2222},
            "source_inputs": [
                {"media_id": edit.id, "role": "first_frame"},
                {"media_id": edit.id, "role": "last_frame"},
            ],
        }),
    )
    session.add(MediaLineage(media_id=video.id, source_media_id=edit.id,
                             source_order=0, task_type="image-to-video"))
    await session.commit()
    return root, edit, video


async def test_media_info_walks_full_ancestor_chain(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        root, edit, video = await _seed_chain(session, prefix)

        result = await media_info(media_id=video.id, session=session)

    data = json.loads(result)
    assert data["media_id"] == video.id
    assert data["tool_id"] == "test:image-to-video:looper"
    assert data["task_type"] == "image-to-video"
    assert data["parameters"]["frames"] == 48

    # Both input roles of the same parent are preserved
    roles = [(s["media_id"], s["role"]) for s in data["sources"] if s.get("media_id")]
    assert (edit.id, "first_frame") in roles
    assert (edit.id, "last_frame") in roles

    # Nearest-first, deduplicated chain all the way to the t2i root
    ancestor_ids = [a["media_id"] for a in data["ancestors"]]
    assert ancestor_ids == [edit.id, root.id]

    by_id = {a["media_id"]: a for a in data["ancestors"]}
    assert by_id[edit.id]["tool_id"] == "test:image-to-image:editor"
    assert by_id[edit.id]["parameters"]["strength"] == 0.6
    assert by_id[root.id]["tool_id"] == "test:text-to-image:alt-model"
    assert by_id[root.id]["parameters"] == {"steps": 33, "cfg": 5.5, "seed": 987654}
    assert by_id[root.id]["sources"] == []


async def test_media_info_root_item_has_no_ancestors(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        root, _edit, _video = await _seed_chain(session, prefix)

        result = await media_info(media_id=root.id, session=session)

    data = json.loads(result)
    assert data["tool_id"] == "test:text-to-image:alt-model"
    assert data["ancestors"] == []


async def test_media_info_imported_item_notes_nothing_to_reuse(db_session):
    async with db_session() as session:
        prefix = str(uuid.uuid4())[:8]
        imported = await create_media_item(
            session,
            file_path=Path(f"/library/{prefix}/scan.jpg"),
            file_format="jpg",
        )
        await session.commit()

        result = await media_info(media_id=imported.id, session=session)

    data = json.loads(result)
    assert data["tool_id"] is None
    assert data["ancestors"] == []
    assert "note" in data


async def test_media_info_missing_media_errors(db_session):
    async with db_session() as session:
        result = await media_info(media_id=99999999, session=session)
    assert result.startswith("Error:")

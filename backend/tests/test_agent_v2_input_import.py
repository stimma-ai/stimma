"""Tests for implicit import of on-disk tool inputs into the library.

When the chat agent passes a workspace/temp file as a generation input,
call_tool promotes it into the library via resolve_or_import_input_file so
the generated asset's lineage references a durable media id instead of an
ephemeral workspace path.
"""

import json

import pytest

from tests.helpers.media import create_media_item, generate_test_image
from agent.v2.tools.library import resolve_or_import_input_file
from database import MediaItem, StorageObject


@pytest.fixture
def output_folder(tmp_path, monkeypatch):
    """Point the library's managed staging helper at a temp dir."""
    folder = tmp_path / "output"
    folder.mkdir()
    monkeypatch.setattr(
        "agent.v2.tools.library._get_default_folder", lambda workspace_dir=None: str(folder)
    )
    return folder


async def test_resolves_existing_library_item_by_path(db_session, tmp_path, output_folder):
    workspace = tmp_path / "workspace"
    file_path = workspace / "existing.png"
    generate_test_image(file_path)

    async with db_session() as session:
        item = await create_media_item(session, file_path=file_path)
        media_id = await resolve_or_import_input_file(session, str(file_path), workspace)

    assert media_id == item.id


async def test_resolves_existing_library_item_by_hash(db_session, tmp_path, output_folder):
    workspace = tmp_path / "workspace"
    file_path = workspace / "copy.png"
    file_hash = generate_test_image(file_path, color=(0, 128, 255))

    async with db_session() as session:
        item = await create_media_item(session, file_hash=file_hash)
        media_id = await resolve_or_import_input_file(session, str(file_path), workspace)

    assert media_id == item.id


async def test_imports_new_workspace_file(db_session, tmp_path, output_folder):
    workspace = tmp_path / "workspace"
    file_path = workspace / "fresh.png"
    generate_test_image(file_path, color=(10, 200, 30))

    async with db_session() as session:
        media_id = await resolve_or_import_input_file(session, str(file_path), workspace)
        assert media_id is not None

        item = await session.get(MediaItem, media_id)
        assert item is not None
        storage = await session.get(StorageObject, item.storage_object_id)
        assert storage is not None
        assert storage.kind == "managed"
        assert storage.object_key
        assert item.file_path.endswith("/fresh.png")
        meta = json.loads(item.generation_metadata)
        assert meta["source"] == "agent_v2_tool_input"
        assert meta["task_type"] == "imported"


async def test_import_is_idempotent(db_session, tmp_path, output_folder):
    workspace = tmp_path / "workspace"
    file_path = workspace / "repeat.png"
    generate_test_image(file_path, color=(200, 10, 30))

    async with db_session() as session:
        first = await resolve_or_import_input_file(session, str(file_path), workspace)
        second = await resolve_or_import_input_file(session, str(file_path), workspace)

    assert first is not None
    assert first == second

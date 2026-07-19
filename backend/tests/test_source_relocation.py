"""Identity-preserving relocation of watched Source folders."""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from config import FolderConfig, reload_settings
from database import (
    Asset,
    AssetRevision,
    MediaItem,
    MediaLineage,
    MediaOwner,
    StorageObject,
)
from ingestion import MediaIngestion
from storage_service import register_external_asset
from tests.helpers.media import create_media_item, generate_test_image


async def _configure_folders(client, folders: list[dict]) -> None:
    response = await client.patch("/api/settings/folders", json={"folders": folders})
    assert response.status_code == 200, response.text
    reload_settings()


async def _counts(session_maker) -> dict[str, int]:
    models = (
        MediaItem,
        Asset,
        AssetRevision,
        StorageObject,
        MediaOwner,
        MediaLineage,
    )
    async with session_maker() as session:
        return {
            model.__tablename__: await session.scalar(
                select(func.count()).select_from(model)
            )
            for model in models
        }


class _StubSettings:
    def __init__(self, root: Path):
        self.folders = [
            FolderConfig(path=str(root), refresh_interval_seconds=300, markers=[])
        ]

    def get_folders_for_profile(self, profile_id):
        return self.folders


class _StubDatabase:
    def __init__(self, session_maker):
        self.async_session_maker = session_maker


def _ingestion_for(session_maker, root: Path) -> MediaIngestion:
    ingestion = MediaIngestion.__new__(MediaIngestion)
    ingestion.settings = _StubSettings(root)

    async def _get_profile_db(profile_id):
        return _StubDatabase(session_maker)

    ingestion._get_profile_db = _get_profile_db
    return ingestion


@pytest.mark.asyncio
async def test_folder_relocation_preserves_identity_and_processing(
    client, db_session, tmp_path
):
    old_root = tmp_path / "source-before"
    old_file = old_root / "nested" / "scene.png"
    digest = generate_test_image(old_file, width=24, height=16)
    stat = old_file.stat()
    old_mtime = datetime.utcfromtimestamp(stat.st_mtime)
    fixed_asset_time = datetime(2025, 2, 3, 4, 5, 6)

    await _configure_folders(
        client,
        [{"path": str(old_root), "refresh_interval_seconds": 300, "markers": []}],
    )

    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=old_file,
            file_hash=digest,
            file_size=stat.st_size,
            width=24,
            height=16,
            metadata_status="completed",
            clip_status="completed",
            face_detection_status="completed",
            vlm_caption_status="completed",
            vlm_caption="unchanged caption",
        )
        media.modified_date = old_mtime
        media.clip_embedding = b"stable-embedding"
        media.metadata_config_version = "metadata-v1"
        media.clip_config_version = "clip-v1"
        media.face_detection_config_version = "faces-v1"
        media.vlm_caption_config_version = "caption-v1"
        storage, asset = await register_external_asset(session, media=media)
        asset.updated_at = fixed_asset_time
        lineage = MediaLineage(
            media_id=media.id,
            source_file_path=str(old_file),
            source_order=0,
            task_type="image-to-image",
        )
        session.add(lineage)
        await session.commit()
        media_id = media.id
        storage_id = storage.id
        asset_id = asset.id
        revision_id = asset.current_revision_id
        lineage_id = lineage.id

    before_counts = await _counts(db_session)
    new_root = tmp_path / "source-after"
    old_root.rename(new_root)
    new_file = new_root / "nested" / "scene.png"
    copied_mtime = new_file.stat().st_mtime + 60
    os.utime(new_file, (copied_mtime, copied_mtime))

    response = await client.patch(
        "/api/settings/folders",
        json={
            "folders": [
                {
                    "path": str(new_root),
                    "refresh_interval_seconds": 300,
                    "markers": [],
                }
            ],
            "relocation": {"old_path": str(old_root), "new_path": str(new_root)},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["relocation"] == {
        "old_path": str(old_root),
        "new_path": str(new_root),
        "media_items_updated": 1,
        "storage_objects_updated": 1,
        "assets_updated": 1,
        "lineage_paths_updated": 1,
    }

    reload_settings()
    assert reload_settings().profiles[0].folders[0].path == str(new_root)
    assert await _counts(db_session) == before_counts

    async with db_session() as session:
        relocated = await session.get(MediaItem, media_id)
        relocated_storage = await session.get(StorageObject, storage_id)
        relocated_asset = await session.get(Asset, asset_id)
        relocated_lineage = await session.get(MediaLineage, lineage_id)

        assert relocated.file_path == str(new_file)
        assert relocated.file_hash == digest
        assert relocated.clip_embedding == b"stable-embedding"
        assert relocated.vlm_caption == "unchanged caption"
        assert relocated.metadata_status == "completed"
        assert relocated.clip_status == "completed"
        assert relocated.face_detection_status == "completed"
        assert relocated.vlm_caption_status == "completed"
        assert relocated.metadata_config_version == "metadata-v1"
        assert relocated.clip_config_version == "clip-v1"
        assert relocated.face_detection_config_version == "faces-v1"
        assert relocated.vlm_caption_config_version == "caption-v1"
        assert relocated_storage.external_path == str(new_file)
        assert relocated_storage.expected_hash == digest
        assert relocated_asset.id == asset_id
        assert relocated_asset.current_revision_id == revision_id
        assert relocated_asset.origin_id == str(new_file)
        assert relocated_asset.updated_at == fixed_asset_time
        assert relocated_lineage.source_file_path == str(new_file)

    ingestion = _ingestion_for(db_session, new_root)
    with patch("app_dirs.get_source_excluded_roots", return_value=[]):
        assert await ingestion._scan_and_sync_profile("default") == 0
    assert await _counts(db_session) == before_counts


@pytest.mark.asyncio
async def test_folder_relocation_rejects_indexed_path_collisions(
    client, db_session, tmp_path
):
    await _configure_folders(client, [])
    old_root = tmp_path / "collision-before"
    new_root = tmp_path / "collision-after"
    old_file = old_root / "same.png"
    new_file = new_root / "same.png"
    old_hash = generate_test_image(old_file, color=(255, 0, 0))
    new_hash = generate_test_image(new_file, color=(0, 0, 255))
    await _configure_folders(
        client,
        [{"path": str(old_root), "refresh_interval_seconds": 300, "markers": []}],
    )

    async with db_session() as session:
        old_media = await create_media_item(
            session,
            file_path=old_file,
            file_hash=old_hash,
            file_size=old_file.stat().st_size,
        )
        new_media = await create_media_item(
            session,
            file_path=new_file,
            file_hash=new_hash,
            file_size=new_file.stat().st_size,
        )
        old_media_id = old_media.id
        new_media_id = new_media.id

    response = await client.patch(
        "/api/settings/folders",
        json={
            "folders": [
                {"path": str(new_root), "refresh_interval_seconds": 300, "markers": []}
            ],
            "relocation": {"old_path": str(old_root), "new_path": str(new_root)},
        },
    )
    assert response.status_code == 409
    assert "collide" in response.json()["detail"]
    reload_settings()
    assert reload_settings().profiles[0].folders[0].path == str(old_root)
    async with db_session() as session:
        assert (await session.get(MediaItem, old_media_id)).file_path == str(old_file)
        assert (await session.get(MediaItem, new_media_id)).file_path == str(new_file)


@pytest.mark.asyncio
async def test_folder_path_replacement_requires_explicit_relocation(
    client, tmp_path
):
    await _configure_folders(client, [])
    old_root = tmp_path / "guard-before"
    new_root = tmp_path / "guard-after"
    old_root.mkdir()
    new_root.mkdir()
    await _configure_folders(
        client,
        [{"path": str(old_root), "refresh_interval_seconds": 300, "markers": []}],
    )

    response = await client.patch(
        "/api/settings/folders",
        json={
            "folders": [
                {"path": str(new_root), "refresh_interval_seconds": 300, "markers": []}
            ]
        },
    )
    assert response.status_code == 409
    assert "relocation metadata" in response.json()["detail"]
    reload_settings()
    assert reload_settings().profiles[0].folders[0].path == str(old_root)

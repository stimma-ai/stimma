from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ingestion


@pytest.mark.asyncio
async def test_discovery_insert_is_committed_in_bounded_batches(monkeypatch):
    created = []

    def make_media_item(**values):
        item = SimpleNamespace(**values)
        created.append(item)
        return item

    monkeypatch.setattr(ingestion, "MediaItem", make_media_item)
    session = SimpleNamespace(
        add=Mock(),
        commit=AsyncMock(),
        expunge_all=Mock(),
    )
    processor = object.__new__(ingestion.MediaIngestion)
    count = ingestion.DISCOVERY_INSERT_BATCH_SIZE * 2 + 1
    metadata = [
        {
            "file_path": f"file-{index}.png",
            "file_hash": "",
            "file_size": index,
            "file_format": "png",
        }
        for index in range(count)
    ]

    await processor._insert_batch(session, metadata)

    assert session.add.call_count == count
    assert session.commit.await_count == 3
    assert session.expunge_all.call_count == 3
    assert all(hasattr(item, "random_sort_value") for item in created)
    assert all("random_sort_value" not in values for values in metadata)


@pytest.mark.asyncio
async def test_config_reload_applies_face_detection_settings_live(monkeypatch):
    import config
    from config_version import ConfigVersionManager

    def settings(min_confidence, max_faces):
        return SimpleNamespace(
            profiles=[],
            clip=SimpleNamespace(model="m", pretrained="p"),
            face_detection=SimpleNamespace(min_confidence=min_confidence, max_faces=max_faces),
        )

    old, new = settings(0.5, 10), settings(0.8, 3)
    monkeypatch.setattr(config, "reload_settings", lambda: new)
    monkeypatch.setattr("config_version.get_settings", lambda: old)
    processor = object.__new__(ingestion.MediaIngestion)
    processor.settings = old
    processor.config_mgr = ConfigVersionManager()
    processor.face_detection_service = SimpleNamespace(min_confidence=0.5, max_faces=10)
    processor.folder_to_profile = {}
    old_version = processor.config_mgr.get_version("face_detection")
    old_clip = processor.config_mgr.get_version("clip")

    await processor._reload_config()

    assert processor.face_detection_service.min_confidence == 0.8
    assert processor.face_detection_service.max_faces == 3
    assert processor.config_mgr.get_version("face_detection") != old_version
    assert processor.config_mgr.get_version("clip") == old_clip

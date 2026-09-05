"""Drag copies must expire and participate in durable permanent deletion."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

import app_dirs
import drag_snapshots
from database import MediaThumbnailCache
from database_registry import get_database_registry
from tests.helpers.media import create_media_item, generate_test_image
from tests.test_trash import wait_for_delete_operation


@pytest.mark.parametrize("file_format", ["png", "jpeg"])
async def test_snapshot_reservation_is_purged_with_trash(
    client, db_session, tmp_path, file_format
):
    source = tmp_path / f"source.{file_format}"
    generate_test_image(source)
    async with db_session() as session:
        item = await create_media_item(
            session,
            file_path=source,
            file_format=file_format,
            materialize_asset=True,
            generation_metadata=json.dumps({"source": "stimma", "tool_id": "test", "inputs": {}}),
        )
        media_id = item.id
        await session.commit()
    guid = get_database_registry().get_db_guid("default")
    url = f"/api/db/{guid}/media/{media_id}/exportable-snapshot"
    response = await client.post(url)
    assert response.status_code == 200, response.text
    destination = Path(response.json()["destination_path"])
    assert destination.parent.is_dir()
    async with db_session() as session:
        assert await session.get(MediaThumbnailCache, (media_id, str(destination)))
    # Simulate both a completed native copy and an interrupted native write.
    destination.write_bytes(b"full-size snapshot")
    destination.with_suffix(destination.suffix + ".tmp").write_bytes(b"partial")
    await client.delete(f"/api/media/{media_id}")
    assert destination.exists(), "soft deletion remains undoable"
    with patch("drag_snapshots.remove_snapshot_directory", side_effect=PermissionError("busy")):
        response = await client.delete(f"/api/trash/{media_id}")
        assert response.status_code == 202, response.text
        operation_id = response.json()["operation"]["id"]
        operation = await wait_for_delete_operation(client, operation_id)
        assert operation["status"] == "failed"
    assert destination.exists()
    response = await client.post(f"/api/delete-operations/{operation_id}/retry")
    assert response.status_code == 202
    assert (await wait_for_delete_operation(client, operation_id))["status"] == "completed"
    assert not destination.parent.exists()
    assert (await client.post(url)).status_code == 404


async def test_reservation_rejects_pending_deletion(db_session, tmp_path):
    async with db_session() as session:
        item = await create_media_item(session, file_path=tmp_path / "pending.png")
        item.deletion_pending_at = datetime.utcnow()
        await session.commit()
        with pytest.raises(ValueError, match="being deleted"):
            await drag_snapshots.reserve_snapshot(session, item.id, "png")
        assert not (await session.scalars(select(MediaThumbnailCache).where(
            MediaThumbnailCache.media_id == item.id,
        ))).all()


def test_cleanup_expires_copies_limits_size_and_preserves_recent_drags(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_cache_dir", lambda: tmp_path / "sandbox")
    monkeypatch.setattr(app_dirs, "get_bundle_cache_root", lambda: tmp_path / "bundle")
    monkeypatch.setattr(drag_snapshots, "MAX_CACHE_BYTES", 15)
    root = drag_snapshots.snapshot_root()
    now = time.time()
    for name, age in [("expired", 7200), ("over-budget", 1200), ("recent", 60)]:
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "snapshot.png").write_bytes(b"0123456789")
        os.utime(directory, (now - age, now - age))
    (root / "legacy.png").write_bytes(b"old copy")
    other = tmp_path / "bundle" / "drag_snapshots" / "other.png"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"outside explicit cache override")
    drag_snapshots.cleanup_snapshots()
    assert not (root / "expired").exists()
    assert not (root / "over-budget").exists()
    assert not (root / "legacy.png").exists()
    assert (root / "recent" / "snapshot.png").exists()
    assert other.exists()


def test_legacy_bundle_cleanup_stays_out_of_other_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_bundle_cache_root", lambda: tmp_path)
    monkeypatch.setattr(app_dirs, "get_cache_dir", lambda: tmp_path / "default")
    monkeypatch.setattr(drag_snapshots, "get_sandbox", lambda: "default")
    legacy = tmp_path / "drag_snapshots" / "old.png"
    legacy.parent.mkdir()
    legacy.write_bytes(b"old")
    unrelated = tmp_path / "default" / "thumbnails" / "thumb.png"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"preview")
    drag_snapshots.purge_legacy_snapshots()
    assert not legacy.exists()
    assert unrelated.exists()

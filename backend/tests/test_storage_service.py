"""Managed object ingest, deduplication, and reference-aware deletion tests."""

import asyncio
import hashlib

import pytest
from sqlalchemy import func, select

from asset_service import create_asset_from_media
from database import Asset, AssetRevision, MediaItem, StorageObject
from storage_service import (
    cleanup_staged_source,
    migrate_legacy_managed_media,
    object_path,
    reconcile_storage,
    register_external_asset,
    register_external_media,
    stage_managed_media,
)
from tests.helpers.media import create_media_item


async def _wait_for_delete(client, operation_id: int):
    for _ in range(100):
        response = await client.get(f"/api/delete-operations/{operation_id}")
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        await asyncio.sleep(0.05)
    raise AssertionError("delete operation did not finish")


async def _delete_asset(client, asset_id: int):
    assert (await client.delete(f"/api/assets/{asset_id}")).status_code == 200
    response = await client.delete(f"/api/assets/{asset_id}/permanent")
    assert response.status_code == 202
    operation = response.json()["operation"]
    if operation:
        result = await _wait_for_delete(client, operation["id"])
        assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_identical_media_share_object_until_last_asset_is_deleted(
    client, db_session, tmp_path
):
    content = b"same managed bytes"
    digest = hashlib.sha256(content).hexdigest()
    first_source = tmp_path / "first.png"
    second_source = tmp_path / "second.png"
    first_source.write_bytes(content)
    second_source.write_bytes(content)

    async with db_session() as session:
        first = await create_media_item(
            session, file_path=first_source, file_hash=digest, file_size=len(content)
        )
        second = await create_media_item(
            session, file_path=second_source, file_hash=digest, file_size=len(content)
        )
        first_storage = await stage_managed_media(
            session, media=first, profile_id="default"
        )
        second_storage = await stage_managed_media(
            session, media=second, profile_id="default"
        )
        first_asset = await create_asset_from_media(session, media_id=first.id)
        second_asset = await create_asset_from_media(session, media_id=second.id)
        object_file = object_path("default", first_storage.object_key)
        await session.commit()
        assert first_storage.id == second_storage.id
        assert first.file_path != second.file_path
        assert object_file.exists()
        await cleanup_staged_source(session, media_id=first.id)
        await cleanup_staged_source(session, media_id=second.id)
        assert not first_source.exists()
        assert not second_source.exists()

    await _delete_asset(client, first_asset.id)
    assert object_file.exists()
    async with db_session() as session:
        assert await session.get(MediaItem, second.id) is not None
        assert await session.get(StorageObject, second_storage.id) is not None

    await _delete_asset(client, second_asset.id)
    assert not object_file.exists()
    async with db_session() as session:
        assert await session.get(StorageObject, second_storage.id) is None


@pytest.mark.asyncio
async def test_external_media_delete_never_deletes_user_owned_file(
    client, db_session, tmp_path
):
    source = tmp_path / "watched.png"
    content = b"external bytes"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    async with db_session() as session:
        media = await create_media_item(
            session, file_path=source, file_hash=digest, file_size=len(content)
        )
        storage = await register_external_media(session, media=media)
        asset = await create_asset_from_media(session, media_id=media.id)
        storage_id = storage.id
        media_id = media.id
        asset_id = asset.id
        await session.commit()

    await _delete_asset(client, asset_id)
    assert source.exists()
    async with db_session() as session:
        assert await session.get(MediaItem, media_id) is None
        assert await session.get(StorageObject, storage_id) is None


@pytest.mark.asyncio
async def test_watched_file_registration_materializes_one_asset(db_session, tmp_path):
    source = tmp_path / "watched-asset.png"
    source.write_bytes(b"watched")
    digest = hashlib.sha256(b"watched").hexdigest()
    async with db_session() as session:
        media = await create_media_item(
            session, file_path=source, file_hash=digest, file_size=7
        )
        storage, asset = await register_external_asset(session, media=media)
        repeated_storage, repeated_asset = await register_external_asset(
            session, media=media
        )
        await session.commit()

        assert storage.kind == "external"
        assert repeated_storage.id == storage.id
        assert repeated_asset.id == asset.id
        assert await session.scalar(select(func.count()).select_from(Asset)) == 1


@pytest.mark.asyncio
async def test_changed_watched_file_advances_same_asset(db_session, tmp_path):
    source = tmp_path / "mutable-watch.png"
    source.write_bytes(b"first")
    async with db_session() as session:
        first = await create_media_item(
            session,
            file_path=source,
            file_hash=hashlib.sha256(b"first").hexdigest(),
            file_size=5,
        )
        _, asset = await register_external_asset(session, media=first)
        first_revision_id = asset.current_revision_id
        await session.commit()

        source.write_bytes(b"second")
        second = await create_media_item(
            session,
            file_path=source,
            file_hash=hashlib.sha256(b"second").hexdigest(),
            file_size=6,
        )
        _, repeated_asset = await register_external_asset(session, media=second)
        await session.commit()

        assert repeated_asset.id == asset.id
        assert repeated_asset.current_revision_id != first_revision_id
        revision = await session.get(AssetRevision, repeated_asset.current_revision_id)
        assert revision.primary_media_id == second.id
        assert revision.parent_revision_id == first_revision_id


@pytest.mark.asyncio
async def test_legacy_migration_only_moves_explicit_managed_roots(db_session, tmp_path):
    managed_root = tmp_path / "legacy-output"
    managed_root.mkdir()
    managed_source = managed_root / "generated.png"
    external_source = tmp_path / "watched.png"
    managed_source.write_bytes(b"generated")
    external_source.write_bytes(b"external")

    async with db_session() as session:
        managed = await create_media_item(
            session,
            file_path=managed_source,
            file_hash=hashlib.sha256(b"generated").hexdigest(),
            file_size=9,
        )
        external = await create_media_item(
            session,
            file_path=external_source,
            file_hash=hashlib.sha256(b"external").hexdigest(),
            file_size=8,
        )
        await session.commit()
        report = await migrate_legacy_managed_media(
            session,
            profile_id="default",
            managed_roots=[managed_root],
        )
        await session.refresh(managed)
        await session.refresh(external)

        assert report["migrated"] == 1
        assert report["skipped_external"] == 1
        assert managed.storage_object_id is not None
        assert external.storage_object_id is None
        assert not managed_source.exists()
        assert external_source.exists()


@pytest.mark.asyncio
async def test_storage_reconciliation_reports_missing_managed_object(db_session, tmp_path):
    source = tmp_path / "managed.png"
    source.write_bytes(b"managed")
    digest = hashlib.sha256(b"managed").hexdigest()
    async with db_session() as session:
        media = await create_media_item(
            session, file_path=source, file_hash=digest, file_size=7
        )
        storage = await stage_managed_media(
            session, media=media, profile_id="default"
        )
        await session.commit()
        await cleanup_staged_source(session, media_id=media.id)
        object_path("default", storage.object_key).unlink()

        report = await reconcile_storage(
            session, profile_id="default", repair_states=True
        )
        await session.refresh(media)
        await session.refresh(storage)
        assert report["missing_managed"] == [media.id]
        assert media.file_unavailable is True
        assert storage.state == "missing"

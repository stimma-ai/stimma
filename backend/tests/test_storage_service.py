"""Managed object ingest, deduplication, and reference-aware deletion tests."""

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from asset_service import create_asset_from_media, create_asset_snapshot
from asset_deletion_service import permanently_delete_asset
from asset_service import trash_asset
from database import (
    Asset,
    AssetRevision,
    DeleteOperation,
    DeleteOperationItem,
    ManagedArtifact,
    MediaItem,
    MediaOwner,
    StorageObject,
)
from delete_operations import _process_profile, retry_delete_operation
from storage_service import (
    StorageServiceError,
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
async def test_structured_directory_is_managed_as_one_verified_payload(
    client, db_session, tmp_path
):
    source = tmp_path / "scene.stimmalayout"
    source.mkdir()
    (source / "index.html").write_text("<main>scene</main>")
    resources = source / "resources"
    resources.mkdir()
    (resources / "texture.bin").write_bytes(b"texture")

    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=source,
            file_format="stimmalayout",
            file_hash=hashlib.sha256(b"legacy-index-only").hexdigest(),
        )
        storage = await stage_managed_media(
            session, media=media, profile_id="default"
        )
        asset = await create_asset_from_media(session, media_id=media.id)
        canonical = object_path("default", storage.object_key)
        media_path = media.file_path
        await session.commit()
        await cleanup_staged_source(session, media_id=media.id)

        assert canonical.is_dir()
        assert (canonical / "index.html").read_text() == "<main>scene</main>"
        assert (canonical / "resources" / "texture.bin").read_bytes() == b"texture"
        assert not source.exists()
        assert Path(media_path).is_dir()

        report = await reconcile_storage(
            session, profile_id="default", verify_hashes=True
        )
        assert report["corrupt_managed"] == []

    await _delete_asset(client, asset.id)
    assert not canonical.exists()


@pytest.mark.asyncio
async def test_external_media_delete_removes_user_owned_file(
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
    assert not source.exists()
    async with db_session() as session:
        assert await session.get(MediaItem, media_id) is None
        assert await session.get(StorageObject, storage_id) is None


@pytest.mark.asyncio
async def test_managed_bytes_unlink_only_after_logical_delete_commit(
    db_session, tmp_path
):
    source = tmp_path / "crash-boundary.png"
    content = b"durable deletion boundary"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=source,
            file_hash=digest,
            file_size=len(content),
        )
        storage = await stage_managed_media(
            session, media=media, profile_id="default"
        )
        asset = await create_asset_from_media(session, media_id=media.id)
        object_file = object_path("default", storage.object_key)
        asset_id = asset.id
        media_id = media.id
        storage_id = storage.id
        await session.commit()

        await trash_asset(session, asset_id=asset_id)
        result = await permanently_delete_asset(
            session,
            asset_id=asset_id,
            profile_id="default",
        )
        operation_id = result.operation.id

    # First worker pass commits logical deletion and its durable manifest. A
    # process crash here leaves bytes present and a resumable deleting object.
    assert await _process_profile("default") is True
    assert object_file.exists()
    async with db_session() as session:
        assert await session.get(MediaItem, media_id) is None
        staged = await session.get(
            DeleteOperationItem, (operation_id, media_id)
        )
        assert staged.state == "media_deleted"
        storage = await session.get(StorageObject, storage_id)
        assert storage.state == "deleting"

    # Deduplicating ingest must not reattach the canonical object while the
    # finalizer owns its last-reference deletion reservation.
    replacement_source = tmp_path / "replacement.png"
    replacement_source.write_bytes(content)
    async with db_session() as session:
        replacement = await create_media_item(
            session,
            file_path=replacement_source,
            file_hash=digest,
            file_size=len(content),
        )
        replacement_id = replacement.id
        with pytest.raises(StorageServiceError, match="deletion is in progress"):
            await stage_managed_media(
                session,
                media=replacement,
                profile_id="default",
            )
        await session.rollback()
        replacement = await session.get(MediaItem, replacement_id)
        await session.delete(replacement)
        await session.commit()
    assert object_file.exists()

    # A later process resumes the idempotent unlink and finalizes metadata.
    assert await _process_profile("default") is True
    assert not object_file.exists()
    async with db_session() as session:
        assert await session.get(StorageObject, storage_id) is None
        assert await session.get(
            DeleteOperationItem, (operation_id, media_id)
        ) is None

    assert await _process_profile("default") is True
    async with db_session() as session:
        operation = await session.get(DeleteOperation, operation_id)
        assert operation.status == "completed"


@pytest.mark.asyncio
async def test_object_store_rejects_deletion_pending_media(db_session, tmp_path):
    source = tmp_path / "pending-object-migration.png"
    source.write_bytes(b"pending")
    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=source,
            file_hash=hashlib.sha256(b"pending").hexdigest(),
            file_size=7,
        )
        media.deletion_pending_at = datetime.utcnow()
        await session.commit()

        with pytest.raises(StorageServiceError, match="Media deletion is in progress"):
            await stage_managed_media(
                session,
                media=media,
                profile_id="default",
            )


@pytest.mark.asyncio
async def test_stale_object_store_reader_fails_before_filesystem_install(
    db_session, tmp_path
):
    source = tmp_path / "stale-object-migration.png"
    content = b"stale reservation"
    source.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    destination = object_path(
        "default",
        f"sha256/{digest[:2]}/{digest[2:4]}/{digest}",
    )

    async with db_session() as stale_session:
        media = await create_media_item(
            stale_session,
            file_path=source,
            file_hash=digest,
            file_size=len(content),
        )
        media_id = media.id
        # Establish a WAL read snapshot before the deletion barrier commits.
        await stale_session.scalar(
            select(MediaItem.id).where(MediaItem.id == media_id)
        )

        async with db_session() as deleting_session:
            deleting = await deleting_session.get(MediaItem, media_id)
            deleting.deletion_pending_at = datetime.utcnow()
            await deleting_session.commit()

        with pytest.raises((OperationalError, StorageServiceError)):
            await stage_managed_media(
                stale_session,
                media=media,
                profile_id="default",
            )
        await stale_session.rollback()

    assert not destination.exists()
    async with db_session() as session:
        media = await session.get(MediaItem, media_id)
        await session.delete(media)
        await session.commit()


@pytest.mark.asyncio
async def test_legacy_duplicate_path_survives_single_media_deletion(
    client, db_session, tmp_path
):
    shared_path = tmp_path / "legacy-shared.png"
    shared_path.write_bytes(b"shared legacy bytes")
    async with db_session() as session:
        first = await create_media_item(session, file_path=shared_path)
        second = await create_media_item(session, file_path=shared_path)
        await create_asset_from_media(session, media_id=first.id)
        await create_asset_from_media(session, media_id=second.id)
        first_id = first.id
        second_id = second.id
        await session.commit()

    await client.delete(f"/api/media/{first_id}")
    response = await client.delete(f"/api/trash/{first_id}")
    result = await _wait_for_delete(client, response.json()["operation"]["id"])
    assert result["status"] == "completed"
    assert shared_path.exists()
    async with db_session() as session:
        assert await session.get(MediaItem, first_id) is None
        assert await session.get(MediaItem, second_id) is not None
    await client.delete(f"/api/media/{second_id}")
    response = await client.delete(f"/api/trash/{second_id}")
    await _wait_for_delete(client, response.json()["operation"]["id"])


@pytest.mark.asyncio
async def test_concurrent_delete_workers_claim_each_media_once(db_session, tmp_path):
    source = tmp_path / "concurrent-delete.png"
    source.write_bytes(b"concurrent")
    async with db_session() as session:
        media = await create_media_item(session, file_path=source)
        asset = await create_asset_from_media(session, media_id=media.id)
        await session.commit()
        await trash_asset(session, asset_id=asset.id)
        result = await permanently_delete_asset(
            session,
            asset_id=asset.id,
            profile_id="default",
        )
        operation_id = result.operation.id

    await asyncio.gather(
        _process_profile("default"),
        _process_profile("default"),
    )
    for _ in range(4):
        await _process_profile("default")

    async with db_session() as session:
        operation = await session.get(DeleteOperation, operation_id)
        assert operation.status == "completed"
        assert operation.total_items == 1
        assert operation.claimed_items == 1
        assert operation.processed_items == 1
        assert operation.deleted_items == 1
        assert operation.failed_items == 0


@pytest.mark.asyncio
async def test_asset_editor_artifacts_retry_without_resurrecting_deleted_root(
    db_session, tmp_path
):
    source_path = tmp_path / "source.png"
    dependent_path = tmp_path / "dependent.png"
    source_path.write_bytes(b"source")
    dependent_path.write_bytes(b"dependent")
    project_path = tmp_path / "source.stimmaedit.json"
    preview_path = tmp_path / "source-preview.webp"
    project_path.write_bytes(b"project")
    preview_path.write_bytes(b"preview")

    async with db_session() as session:
        source_media = await create_media_item(session, file_path=source_path)
        dependent_media = await create_media_item(session, file_path=dependent_path)
        source = await create_asset_from_media(session, media_id=source_media.id)
        dependent = await create_asset_from_media(
            session, media_id=dependent_media.id
        )
        dependent_revision_id = dependent.current_revision_id
        snapshot = await create_asset_snapshot(
            session,
            owner_kind="revision",
            owner_id=dependent_revision_id,
            media_id=source_media.id,
            source_asset_id=source.id,
            source_revision_id=source.current_revision_id,
            role="source",
        )
        session.add_all(
            [
                ManagedArtifact(
                    owner_kind="asset",
                    owner_id=str(source.id),
                    artifact_kind="editor_project",
                    locator=str(project_path),
                ),
                ManagedArtifact(
                    owner_kind="revision",
                    owner_id=str(source.current_revision_id),
                    artifact_kind="editor_preview",
                    locator=str(preview_path),
                ),
            ]
        )
        await session.commit()
        source_id = source.id
        source_media_id = source_media.id
        dependent_id = dependent.id
        snapshot_id = snapshot.id

        await trash_asset(session, asset_id=source_id)
        result = await permanently_delete_asset(
            session,
            asset_id=source_id,
            profile_id="default",
        )
        operation_id = result.operation.id

    # Asset identity deletion commits before its private editor artifacts are
    # unlinked. B's snapshot is a strong Media root and only its weak semantic
    # binding back to A is cleared.
    async with db_session() as session:
        assert await session.get(Asset, source_id) is None
        assert await session.get(MediaItem, source_media_id) is not None
        dependent = await session.get(Asset, dependent_id)
        assert dependent.current_revision_id == dependent_revision_id
        snapshot = await session.get(type(snapshot), snapshot_id)
        assert snapshot.media_id == source_media_id
        assert snapshot.source_asset_id is None
        assert snapshot.source_revision_id is None
        owner = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.root_kind == "asset_snapshot",
                MediaOwner.root_id == str(snapshot_id),
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert owner.media_id == source_media_id

    deleted_once = False

    def fail_after_first_unlink(path):
        nonlocal deleted_once
        if not deleted_once:
            deleted_once = True
            path_obj = path if hasattr(path, "unlink") else type(project_path)(path)
            path_obj.unlink(missing_ok=True)
            return
        raise PermissionError("simulated editor artifact failure")

    with patch(
        "delete_operations.TrashService.permanently_delete",
        side_effect=fail_after_first_unlink,
    ):
        assert await _process_profile("default") is True

    async with db_session() as session:
        operation = await session.get(DeleteOperation, operation_id)
        assert operation.status == "failed"
        assert await session.get(Asset, source_id) is None
        assert await session.get(MediaItem, source_media_id) is not None
        remaining = list(
            await session.scalars(
                select(ManagedArtifact).where(
                    ManagedArtifact.owner_kind == "delete_operation",
                    ManagedArtifact.owner_id == str(operation_id),
                )
            )
        )
        assert len(remaining) == 2
        await retry_delete_operation(session, operation_id)

    assert await _process_profile("default") is True
    assert await _process_profile("default") is True
    assert not project_path.exists()
    assert not preview_path.exists()
    async with db_session() as session:
        operation = await session.get(DeleteOperation, operation_id)
        assert operation.status == "completed"
        assert await session.get(Asset, source_id) is None
        assert await session.get(MediaItem, source_media_id) is not None

        # Module-scoped storage tests share a database. Remove the surviving B
        # root after proving its integrity so later count-based tests remain
        # isolated.
        await trash_asset(session, asset_id=dependent_id)
        cleanup_result = await permanently_delete_asset(
            session,
            asset_id=dependent_id,
            profile_id="default",
        )

    for _ in range(4):
        await _process_profile("default")
    async with db_session() as session:
        cleanup = await session.get(DeleteOperation, cleanup_result.operation.id)
        assert cleanup.status == "completed"


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
async def test_app_owned_payload_never_materializes_watched_asset(db_session, tmp_path):
    source = tmp_path / "staging" / "generated" / "result.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"generated")
    async with db_session() as session:
        asset_count = await session.scalar(select(func.count()).select_from(Asset))
        media = await create_media_item(session, file_path=source)
        with patch(
            "app_dirs.get_all_stimma_owned_roots", return_value=[tmp_path]
        ):
            storage, asset = await register_external_asset(session, media=media)
        await session.commit()

        assert storage is None
        assert asset is None
        assert media.storage_object_id is None
        assert await session.scalar(select(func.count()).select_from(Asset)) == asset_count
        # Module-scoped storage tests share a database; remove this deliberately
        # ownerless row so later migration-count assertions stay isolated.
        await session.delete(media)
        await session.commit()


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
        assert report["skipped_external"] >= 1
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

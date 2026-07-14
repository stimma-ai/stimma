"""Startup cutover guarantees historical Media receives safe Asset identity."""

import json
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from asset_migration import (
    _MIGRATION_MAP_BATCH_SIZE,
    _bulk_insert_migration_maps,
    _supersede_assetized_delete_operations,
    classify_legacy_media,
    ensure_asset_backfill,
)
from core.app import check_and_reset_stale_clip_embeddings
from delete_operations import _process_profile, create_delete_operation
from database import (
    Asset,
    AssetMigrationMap,
    AssetMigrationState,
    AssetRevision,
    ContainerMember,
    DeleteOperation,
    DeleteOperationItem,
    MediaItem,
)
from tests.helpers.media import create_media_item, generate_test_image


@pytest.mark.asyncio
async def test_migration_map_writes_are_batched_without_an_orm_flush():
    session = AsyncMock()
    row_count = _MIGRATION_MAP_BATCH_SIZE * 2 + 17
    rows = [{"legacy_media_id": index} for index in range(row_count)]

    await _bulk_insert_migration_maps(session, rows=rows)

    assert session.execute.await_count == 3
    batch_sizes = [len(call.args[1]) for call in session.execute.await_args_list]
    assert batch_sizes == [
        _MIGRATION_MAP_BATCH_SIZE,
        _MIGRATION_MAP_BATCH_SIZE,
        17,
    ]


@pytest.mark.asyncio
async def test_failed_deletion_reconciliation_does_not_expand_migrated_ids_in_sql():
    matching = SimpleNamespace(id=1, status="failed")
    unrelated = SimpleNamespace(id=2, status="failed")
    session = AsyncMock()
    session.execute.return_value = [
        (matching, 10),
        (matching, 11),
        (unrelated, 50_000),
    ]

    superseded = await _supersede_assetized_delete_operations(
        session,
        assetized_media_ids=set(range(40_000)),
    )

    statement = session.execute.await_args.args[0]
    assert " IN " not in f" {statement} "
    assert len(statement.compile().params) == 1
    assert superseded == 1
    assert matching.status == "superseded"
    assert unrelated.status == "failed"


@pytest.mark.asyncio
async def test_startup_backfill_is_conservative_recoverable_and_constant_time(
    client, db_session, tmp_path
):
    async with db_session() as session:
        ordinary = await create_media_item(session, file_path=tmp_path / "ordinary.png")
        trashed = await create_media_item(session, file_path=tmp_path / "trashed.png")
        trashed.deleted_at = datetime.utcnow()

        member = await create_media_item(session, file_path=tmp_path / "member.png")
        member.deleted_at = datetime.utcnow()
        container = await create_media_item(
            session,
            file_path=tmp_path / "grid.stimmagrid.json",
            file_format="stimmagrid.json",
            raw_metadata=json.dumps({
                "cells": [{"row": 0, "col": 0, "path": "member.png"}]
            }),
        )
        malformed = await create_media_item(
            session,
            file_path=tmp_path / "bad.stimmaset.json",
            file_format="stimmaset.json",
            raw_metadata="{not-json",
        )
        absent_members = await create_media_item(
            session,
            file_path=tmp_path / "empty.stimmaset.json",
            file_format="stimmaset.json",
            raw_metadata=json.dumps({"version": 1}),
        )

        duplicate_a = await create_media_item(session, file_path=tmp_path / "same.png")
        await create_media_item(session, file_path=tmp_path / "same.png")
        duplicate_grid = await create_media_item(
            session,
            file_path=tmp_path / "duplicates.stimmagrid.json",
            file_format="stimmagrid.json",
            raw_metadata=json.dumps({
                "cells": [
                    {"row": 0, "col": 0, "path": "same.png"},
                    {"row": 0, "col": 1, "path": "same.png"},
                    {"row": 0, "col": 2, "path": "missing.png"},
                    "invalid",
                ]
            }),
        )
        deleting_path = tmp_path / "queued-delete.png"
        deleting_hash = generate_test_image(deleting_path)
        deleting = await create_media_item(
            session,
            file_path=deleting_path,
            file_hash=deleting_hash,
        )
        deleting.deleted_at = datetime.utcnow()
        await session.flush()
        delete_operation = await create_delete_operation(
            session,
            profile_id="default",
            kind="single",
            media_items=[deleting],
        )
        failed = await create_media_item(
            session,
            file_path=tmp_path / "historical-failed.png",
        )
        failed.deleted_at = datetime.utcnow()
        await session.flush()
        failed_operation = await create_delete_operation(
            session,
            profile_id="default",
            kind="single",
            media_items=[failed],
        )
        failed_item = await session.get(
            DeleteOperationItem,
            (failed_operation.id, failed.id),
        )
        failed_operation.status = "failed"
        failed_item.state = "failed"
        failed.deletion_pending_at = None
        await session.commit()

        with (
            patch(
                "asset_migration.classify_legacy_media",
                wraps=classify_legacy_media,
            ) as classifier,
            patch("asset_migration.log.info") as progress_log,
        ):
            first = await ensure_asset_backfill(session, profile_id="default")
        assert classifier.await_count == 1
        progress_events = [call.args[0] for call in progress_log.call_args_list]
        assert "asset media backfill classification started" in progress_events
        assert "asset media backfill materialization completed" in progress_events
        assert (
            "asset media backfill deletion reconciliation completed"
            in progress_events
        )
        assert "asset media backfill mapping completed" in progress_events
        assert "asset media backfill committed" in progress_events
        second = await ensure_asset_backfill(session)

        assert first["already_complete"] is False
        assert second["already_complete"] is True
        assert second["assets"] == 0
        ordinary_revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == ordinary.id
            )
        )
        assert ordinary_revision is not None

        trashed_revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == trashed.id
            )
        )
        trashed_asset = await session.get(Asset, trashed_revision.asset_id)
        assert trashed_asset.state == "trashed"
        assert (await session.get(MediaItem, trashed.id)).deleted_at is None

        container_revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == container.id
            )
        )
        container_member = await session.scalar(
            select(ContainerMember).where(
                ContainerMember.container_revision_id == container_revision.id
            )
        )
        assert container_member.embedded_media_id == member.id

        for invalid_container in (malformed, absent_members):
            revision = await session.scalar(
                select(AssetRevision).where(
                    AssetRevision.primary_media_id == invalid_container.id
                )
            )
            assert revision is not None
            migration = await session.scalar(
                select(AssetMigrationMap).where(
                    AssetMigrationMap.legacy_media_id == invalid_container.id
                )
            )
            assert migration.evidence is not None
            assert json.loads(migration.evidence)["conflicts"]

        duplicate_revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == duplicate_grid.id
            )
        )
        placeholders = list(await session.scalars(
            select(ContainerMember)
            .where(ContainerMember.container_revision_id == duplicate_revision.id)
            .order_by(ContainerMember.member_order)
        ))
        assert len(placeholders) == 4
        assert all(item.missing_linked_asset for item in placeholders)
        duplicate_map = await session.scalar(
            select(AssetMigrationMap).where(
                AssetMigrationMap.legacy_media_id == duplicate_grid.id
            )
        )
        assert "duplicate_member_path:0" in json.loads(duplicate_map.evidence)[
            "conflicts"
        ]
        assert duplicate_a.id is not None

        assert await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == deleting.id
            )
        ) is None
        assert (await session.get(MediaItem, deleting.id)).deleted_at is not None
        assert deleting_path.exists()

        failed_revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == failed.id
            )
        )
        assert failed_revision is not None
        assert (await session.get(Asset, failed_revision.asset_id)).state == "trashed"
        await session.refresh(failed_operation)
        assert failed_operation.status == "superseded"
        assert failed_operation.current_phase == "assetized"

        trashed_asset_id = trashed_asset.id
        deleting_id = deleting.id
        delete_operation_id = delete_operation.id

    trash = await client.get("/api/assets", params={"state": "trashed"})
    assert trash.status_code == 200
    assert trashed_asset_id in {
        item["asset"]["id"] for item in trash.json()["items"]
    }
    restored = await client.post(f"/api/assets/{trashed_asset_id}/restore")
    assert restored.status_code == 200
    active = await client.get(f"/api/assets/{trashed_asset_id}")
    assert active.status_code == 200
    assert active.json()["media"]["id"] == trashed.id

    assert (await client.delete(f"/api/assets/{trashed_asset_id}")).status_code == 200
    permanent = await client.delete(f"/api/assets/{trashed_asset_id}/permanent")
    assert permanent.status_code == 202
    operation = permanent.json()["operation"]
    if operation is not None:
        for _ in range(100):
            status = (
                await client.get(f"/api/delete-operations/{operation['id']}")
            ).json()
            if status["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.02)
        assert status["status"] == "completed"
    async with db_session() as session:
        assert await session.get(Asset, trashed_asset_id) is None
        assert await session.get(MediaItem, trashed.id) is None

    for _ in range(20):
        await _process_profile("default")
        async with db_session() as session:
            queued = await session.get(DeleteOperation, delete_operation_id)
            if queued.status in {"completed", "failed"}:
                break
    assert queued.status == "completed"
    assert not deleting_path.exists()
    async with db_session() as session:
        assert await session.get(MediaItem, deleting_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["dual_write", "asset_reads", "object_store", "contracted"])
async def test_startup_backfill_recognizes_every_post_cutover_phase(
    db_session, phase
):
    async with db_session() as session:
        state = await session.scalar(select(AssetMigrationState))
        state.phase = phase
        state.deleted_at = datetime.utcnow()
        await session.commit()

        result = await ensure_asset_backfill(session)

        assert result["already_complete"] is True
        assert result["phase"] == "contracted"


@pytest.mark.asyncio
async def test_clip_compatibility_check_resets_only_wrong_sized_blobs(
    client, db_session
):
    from clip_service import CLIP_EMBEDDING_DIM

    async with db_session() as session:
        compatible = await create_media_item(session, clip_status="completed")
        stale = await create_media_item(session, clip_status="completed")
        compatible.clip_embedding = bytes(CLIP_EMBEDDING_DIM * 4)
        stale.clip_embedding = bytes((CLIP_EMBEDDING_DIM - 1) * 4)
        await session.commit()
        compatible_id = compatible.id
        stale_id = stale.id

    assert await check_and_reset_stale_clip_embeddings("default") == 1

    async with db_session() as session:
        compatible = await session.get(MediaItem, compatible_id)
        stale = await session.get(MediaItem, stale_id)
        assert compatible.clip_embedding is not None
        assert compatible.clip_status == "completed"
        assert stale.clip_embedding is None
        assert stale.clip_status == "pending"

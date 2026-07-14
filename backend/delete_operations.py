import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select, text, update

from core.logging import get_logger
from database import (
    AssetRevision,
    AssetSnapshot,
    BoardItem,
    ChatItem,
    ContainerMember,
    DeleteOperation,
    DeleteOperationItem,
    Face,
    GenerationJob,
    MediaItem,
    MediaKeyword,
    MediaLineage,
    ManagedArtifact,
    MediaMarker,
    MediaOwner,
    MediaTag,
    MediaThumbnailCache,
    MediaToolLineage,
    ProjectMedia,
    StorageObject,
    Tool,
)
from database_registry import get_database_registry
from trash_service import TrashService
from utils.websocket import ws_manager

log = get_logger(__name__)

DELETE_BATCH_SIZE = 500
LEASE_SECONDS = 60
WORKER_IDLE_SECONDS = 1.0
WORKER_BUSY_SECONDS = 0.1

_worker_task: asyncio.Task | None = None
_worker_lock = asyncio.Lock()


class DependentEditorSnapshotError(RuntimeError):
    """Legacy editor state still embeds Media selected for deletion."""


class RetainedMediaError(RuntimeError):
    """Media is still strongly retained by a new-model root."""


def _utcnow() -> datetime:
    return datetime.utcnow()


def _operation_payload(operation: DeleteOperation) -> dict[str, Any]:
    total = operation.total_items or 0
    processed = operation.processed_items or 0
    rate = None
    eta = None
    if operation.started_at and processed > 0:
        elapsed = max((_utcnow() - operation.started_at).total_seconds(), 0.001)
        rate = processed / elapsed
        remaining = max(total - processed, 0)
        eta = remaining / rate if rate else None
    payload = operation.to_dict()
    payload["rate_items_per_sec"] = rate
    payload["eta_seconds"] = eta
    return payload




async def create_delete_operation(
    session,
    *,
    profile_id: str,
    kind: str,
    media_items: list[MediaItem],
    managed_artifacts: list[ManagedArtifact] | None = None,
) -> DeleteOperation:
    media_ids = [item.id for item in media_items]
    await _assert_no_live_media_owners(session, media_ids)
    barrier_at = _utcnow()
    for item in media_items:
        if item.deletion_pending_at is not None:
            raise RetainedMediaError("Selected Media is already being deleted")
        item.deletion_pending_at = barrier_at

    operation = DeleteOperation(
        kind=kind,
        profile_id=profile_id,
        status="queued",
        current_phase="queued",
        total_items=len(media_items),
        claimed_items=0,
        processed_items=0,
        deleted_items=0,
        failed_items=0,
        updated_at=_utcnow(),
    )
    session.add(operation)
    await session.flush()

    for item in media_items:
        session.add(
            DeleteOperationItem(
                operation_id=operation.id,
                media_id=item.id,
                file_path=item.file_path,
                file_hash=item.file_hash,
                state="pending",
                updated_at=_utcnow(),
            )
        )

    # Media-owned artifacts remain attached until the same transaction that
    # logically deletes their Media. Asset/editor artifacts are safe to stage
    # now because their owning identity is removed before this operation commits.
    artifacts = list(managed_artifacts or [])
    seen_artifact_ids: set[int] = set()
    for artifact in artifacts:
        if artifact.id in seen_artifact_ids:
            continue
        seen_artifact_ids.add(artifact.id)
        artifact.owner_kind = "delete_operation"
        artifact.owner_id = str(operation.id)
        artifact.media_id = None
        artifact.state = "deleting"

    await session.commit()
    await session.refresh(operation)
    return operation


async def ensure_delete_worker_started() -> None:
    global _worker_task

    async with _worker_lock:
        current_loop = asyncio.get_running_loop()
        if _worker_task and not _worker_task.done():
            # Test clients and embedded hosts can replace their event loop while
            # the process stays alive. A task owned by the old loop cannot make
            # progress, even though ``done()`` may still be false.
            if _worker_task.get_loop() is current_loop:
                return
            _worker_task.cancel()
        _worker_task = asyncio.create_task(_delete_worker_loop())


async def _delete_worker_loop() -> None:
    log.info("DELETE OPS: worker started")
    try:
        while True:
            did_work = False
            registry = get_database_registry()
            for profile in registry.list_profiles():
                profile_id = profile["id"]
                if not registry.has_profile(profile_id):
                    continue
                try:
                    worked = await _process_profile(profile_id)
                    did_work = did_work or worked
                except Exception as exc:
                    log.error("DELETE OPS: profile processing failed", profile_id=profile_id, error=str(exc), exc_info=True)
            await asyncio.sleep(WORKER_BUSY_SECONDS if did_work else WORKER_IDLE_SECONDS)
    except asyncio.CancelledError:
        log.info("DELETE OPS: worker stopped")
        raise


async def _truncate_privacy_wal(db) -> bool:
    """Remove historical WAL frames before reporting privacy completion."""
    try:
        async with db.async_engine.connect() as connection:
            connection = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            result = await connection.exec_driver_sql(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            )
            row = result.first()
            return row is None or row[0] == 0
    except Exception as exc:
        log.warning(
            "DELETE OPS: privacy WAL checkpoint deferred",
            error_type=type(exc).__name__,
        )
        return False


async def _finalize_staged_deletion(
    db,
    *,
    profile_id: str,
    operation_id: int,
) -> tuple[bool, list[int]]:
    """Unlink durable artifact manifests after logical deletion committed.

    Missing paths are success, so a crash after unlink but before the final DB
    commit resumes idempotently. Any real unlink failure leaves the manifests
    and operation active for an automatic retry.
    """
    async with db.async_session_maker() as session:
        claimed_ids = list(
            (
                await session.execute(
                    update(DeleteOperationItem)
                    .where(
                        DeleteOperationItem.operation_id == operation_id,
                        DeleteOperationItem.state == "media_deleted",
                    )
                    .values(
                        state="unlinking",
                        lease_expires_at=_utcnow()
                        + timedelta(seconds=LEASE_SECONDS),
                        updated_at=_utcnow(),
                    )
                    .returning(DeleteOperationItem.media_id)
                )
            ).scalars()
        )
        staged_items = (
            list(
                await session.scalars(
                    select(DeleteOperationItem).where(
                        DeleteOperationItem.operation_id == operation_id,
                        DeleteOperationItem.media_id.in_(claimed_ids),
                        DeleteOperationItem.state == "unlinking",
                    )
                )
            )
            if claimed_ids
            else []
        )
        has_media_work = await session.scalar(
            select(DeleteOperationItem.media_id)
            .where(DeleteOperationItem.operation_id == operation_id)
            .limit(1)
        )
        if not staged_items and has_media_work is not None:
            await session.commit()
            return False, []
        if has_media_work is None:
            artifact_claim = await session.execute(
                update(DeleteOperation)
                .where(
                    DeleteOperation.id == operation_id,
                    or_(
                        DeleteOperation.current_phase.is_(None),
                        DeleteOperation.current_phase != "artifact_unlinking",
                        DeleteOperation.updated_at
                        < _utcnow() - timedelta(seconds=LEASE_SECONDS),
                    ),
                )
                .values(
                    current_phase="artifact_unlinking",
                    updated_at=_utcnow(),
                )
                .returning(DeleteOperation.id)
            )
            if artifact_claim.scalar_one_or_none() is None:
                await session.rollback()
                return False, []
        artifacts = list(
            await session.scalars(
                select(ManagedArtifact).where(
                    ManagedArtifact.owner_kind == "delete_operation",
                    ManagedArtifact.owner_id == str(operation_id),
                    ManagedArtifact.state == "deleting",
                    ManagedArtifact.deleted_at.is_(None),
                )
            )
        )
        compatibility_paths = [
            item.file_path
            for item in staged_items
            if item.file_path and item.storage_kind != "external"
        ]
        protected_paths = (
            set(
                await session.scalars(
                    select(MediaItem.file_path).where(
                        MediaItem.file_path.in_(compatibility_paths)
                    )
                )
            )
            if compatibility_paths
            else set()
        )
        storage_ids = {
            item.storage_object_id
            for item in staged_items
            if item.storage_object_id is not None
        }
        retained_storage_ids = (
            set(
                await session.scalars(
                    select(MediaItem.storage_object_id).where(
                        MediaItem.storage_object_id.in_(storage_ids)
                    )
                )
            )
            if storage_ids
            else set()
        )
        await session.commit()
    if not staged_items and not artifacts:
        return False, []

    trash_service = TrashService()

    def _unlink_manifests() -> None:
        from storage_service import object_path

        for item in staged_items:
            try:
                thumbnail_paths = json.loads(item.thumbnail_paths or "[]")
            except (json.JSONDecodeError, TypeError):
                thumbnail_paths = []
            for thumbnail_path in thumbnail_paths:
                Path(thumbnail_path).unlink(missing_ok=True)
            if (
                item.file_path
                and item.storage_kind != "external"
                and item.file_path not in protected_paths
            ):
                trash_service.permanently_delete(item.file_path)
            if (
                item.storage_kind == "managed"
                and item.storage_object_key
                and item.storage_object_id not in retained_storage_ids
            ):
                trash_service.permanently_delete(
                    str(object_path(profile_id, item.storage_object_key))
                )
        for artifact in artifacts:
            trash_service.permanently_delete(artifact.locator)

    try:
        await asyncio.to_thread(_unlink_manifests)
    except Exception as exc:
        async with db.async_session_maker() as session:
            operation = await session.get(DeleteOperation, operation_id)
            if operation is not None:
                failure_count = len(staged_items)
                operation.status = "failed"
                operation.failed_items += failure_count
                operation.processed_items += failure_count
                operation.last_error = "permanent deletion failed"
                operation.current_phase = "failed"
                operation.completed_at = _utcnow()
                operation.updated_at = operation.completed_at
            if staged_items:
                await session.execute(
                    update(DeleteOperationItem)
                    .where(
                        DeleteOperationItem.operation_id == operation_id,
                        DeleteOperationItem.media_id.in_(
                            [item.media_id for item in staged_items]
                        ),
                    )
                    .values(
                        state="failed",
                        lease_expires_at=None,
                        last_error="permanent deletion failed",
                        updated_at=_utcnow(),
                    )
                )
            await session.commit()
        log.error(
            "DELETE OPS: durable artifact unlink failed",
            operation_id=operation_id,
            error_type=type(exc).__name__,
        )
        await ws_manager.broadcast(
            "delete_operation_failed",
            _operation_payload(operation),
            include_profile=False,
        )
        return True, []

    completed_ids = [item.media_id for item in staged_items]
    storage_ids = {
        item.storage_object_id
        for item in staged_items
        if item.storage_object_id is not None
    }
    async with db.async_session_maker() as session:
        if storage_ids:
            for storage_id in storage_ids:
                remaining_ref = await session.scalar(
                    select(MediaItem.id).where(
                        MediaItem.storage_object_id == storage_id
                    ).limit(1)
                )
                if remaining_ref is None:
                    storage = await session.get(StorageObject, storage_id)
                    if storage is not None and storage.state == "deleting":
                        await session.delete(storage)
                else:
                    storage = await session.get(StorageObject, storage_id)
                    if storage is not None and storage.state == "deleting":
                        storage.state = "available"
                        storage.deleted_at = None
        if artifacts:
            await session.execute(
                delete(ManagedArtifact).where(
                    ManagedArtifact.id.in_([artifact.id for artifact in artifacts])
                )
            )
        if completed_ids:
            await session.execute(
                delete(DeleteOperationItem).where(
                    DeleteOperationItem.operation_id == operation_id,
                    DeleteOperationItem.media_id.in_(completed_ids),
                    DeleteOperationItem.state == "unlinking",
                )
            )
        operation = await session.get(DeleteOperation, operation_id)
        if operation is not None:
            operation.processed_items += len(completed_ids)
            operation.deleted_items += len(completed_ids)
            operation.last_error = None
            operation.current_phase = "finalizing"
            operation.updated_at = _utcnow()
        await session.commit()

    if completed_ids:
        payload: dict[str, Any] = {"count": len(completed_ids)}
        if len(completed_ids) <= 500:
            payload["media_ids"] = completed_ids
        await ws_manager.broadcast(
            "media_permanently_deleted", payload, include_profile=False
        )
    return True, completed_ids


async def _process_profile(profile_id: str) -> bool:
    registry = get_database_registry()
    db = registry.get_database(profile_id)
    now = _utcnow()

    # Chat deletion has a short Undo tombstone, then joins this same durable
    # privacy-deletion pipeline. Running it here makes restart recovery free:
    # any overdue tombstone is finalized on the next worker pass.
    from chat_deletion_service import finalize_due_chat_deletions

    async with db.async_session_maker() as chat_session:
        chat_result = await finalize_due_chat_deletions(
            chat_session,
            profile_id=profile_id,
            now=now,
        )

    async with db.async_session_maker() as session:
        await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.state.in_(["claimed", "refs_scrubbed", "cache_purged"]),
                DeleteOperationItem.lease_expires_at.is_not(None),
                DeleteOperationItem.lease_expires_at < now,
            )
            .values(state="pending", lease_expires_at=None, updated_at=now)
        )
        await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.state == "unlinking",
                DeleteOperationItem.lease_expires_at.is_not(None),
                DeleteOperationItem.lease_expires_at < now,
            )
            .values(
                state="media_deleted",
                lease_expires_at=None,
                updated_at=now,
            )
        )
        await session.commit()

        result = await session.execute(
            select(DeleteOperation)
            .where(DeleteOperation.profile_id == profile_id, DeleteOperation.status.in_(["queued", "running"]))
            .order_by(DeleteOperation.id.asc())
        )
        operation = result.scalars().first()
        if not operation:
            return chat_result.finalized_chats > 0

        if operation.status == "queued":
            operation.status = "running"
            operation.started_at = now
            operation.current_phase = "claiming"
            operation.updated_at = now
            await session.commit()
            await ws_manager.broadcast("delete_operation_started", _operation_payload(operation), include_profile=False)

        pending_logical_work = await session.scalar(
            select(DeleteOperationItem.media_id).where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.state == "pending",
            ).limit(1)
        )
        if pending_logical_work is None:
            staged_worked, _ = await _finalize_staged_deletion(
                db,
                profile_id=profile_id,
                operation_id=operation.id,
            )
            if staged_worked:
                return True

        claim_result = await session.execute(
            select(DeleteOperationItem.media_id)
            .where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.state == "pending",
            )
            .order_by(DeleteOperationItem.media_id.asc())
            .limit(DELETE_BATCH_SIZE)
        )
        media_ids = list(claim_result.scalars().all())

        if not media_ids:
            unfinished = await session.execute(
                select(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id == operation.id,
                    DeleteOperationItem.state.not_in(["done", "failed"]),
                )
                .limit(1)
            )
            if unfinished.scalars().first():
                return False

            # secure_delete clears freed records in the live pages. A truncate
            # checkpoint also removes older WAL frames before the operation is
            # described as privacy-complete.
            operation_id = operation.id
            operation_kind = operation.kind
            await session.rollback()
            if not await _truncate_privacy_wal(db):
                operation = await session.get(DeleteOperation, operation_id)
                if operation is not None:
                    operation.current_phase = "checkpointing"
                    operation.updated_at = _utcnow()
                    await session.commit()
                return False
            operation = await session.get(DeleteOperation, operation_id)
            if operation is None:
                return False
            operation.current_phase = "completed"
            operation.status = "failed" if operation.failed_items else "completed"
            operation.completed_at = _utcnow()
            operation.updated_at = operation.completed_at
            await session.commit()
            event_name = "delete_operation_failed" if operation.failed_items else "delete_operation_completed"
            await ws_manager.broadcast(event_name, _operation_payload(operation), include_profile=False)
            if operation_kind == "empty_trash" and operation.deleted_items:
                await ws_manager.broadcast("trash_emptied", {"count": operation.deleted_items}, include_profile=False)
            return True

        lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        claimed_result = await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.media_id.in_(media_ids),
                DeleteOperationItem.state == "pending",
            )
            .values(
                state="claimed",
                lease_expires_at=lease_expires_at,
                attempt_count=DeleteOperationItem.attempt_count + 1,
                updated_at=now,
            )
            .returning(DeleteOperationItem.media_id)
        )
        media_ids = list(claimed_result.scalars())
        if not media_ids:
            await session.rollback()
            return False
        operation.claimed_items = min(
            operation.total_items,
            operation.claimed_items + len(media_ids),
        )
        operation.current_phase = "scrubbing_refs"
        operation.updated_at = now
        await session.commit()

    completed_ids: list[int] = []
    failed_ids: list[int] = []

    # Phase 1: Batch scrub all references in a single session
    async with db.async_session_maker() as session:
        try:
            await _batch_scrub_references(session, media_ids)
        except Exception as exc:
            log.error("DELETE OPS: batch scrub failed, falling back to individual", error=str(exc), exc_info=True)
            await session.rollback()
            # Fallback to individual scrubbing
            for media_id in media_ids:
                try:
                    async with db.async_session_maker() as fallback_session:
                        await _scrub_references(fallback_session, media_id)
                        await fallback_session.commit()
                except Exception as exc2:
                    log.error(
                        "DELETE OPS: scrub failed",
                        media_id=media_id,
                        error_type=type(exc2).__name__,
                        exc_info=True,
                    )
                    failed_ids.append(media_id)
        await session.commit()

    # Phase 2: Commit logical deletion and a durable unlink manifest. No bytes
    # are removed until this transaction succeeds.
    active_media_ids = [mid for mid in media_ids if mid not in failed_ids]
    if active_media_ids:
        async with db.async_session_maker() as session:
            try:
                # This is the final retention check in the same write
                # transaction that removes Media. The queue-time barrier blocks
                # all service-mediated owner acquisition after this point.
                await _assert_no_live_media_owners(session, active_media_ids)
                op_items = {
                    item.media_id: item
                    for item in await session.scalars(
                        select(DeleteOperationItem).where(
                            DeleteOperationItem.operation_id == operation.id,
                            DeleteOperationItem.media_id.in_(active_media_ids),
                        )
                    )
                }
                thumbs_by_media: dict[int, list[str]] = {}
                for media_id, cache_path in (
                    await session.execute(
                        select(
                            MediaThumbnailCache.media_id,
                            MediaThumbnailCache.cache_path,
                        ).where(
                            MediaThumbnailCache.media_id.in_(active_media_ids)
                        )
                    )
                ).all():
                    thumbs_by_media.setdefault(media_id, []).append(cache_path)

                media_rows = {
                    media.id: media
                    for media in await session.scalars(
                        select(MediaItem).where(MediaItem.id.in_(active_media_ids))
                    )
                }
                storage_ids = {
                    media.storage_object_id
                    for media in media_rows.values()
                    if media.storage_object_id is not None
                }
                storage_by_id = {
                    storage.id: storage
                    for storage in await session.scalars(
                        select(StorageObject).where(StorageObject.id.in_(storage_ids))
                    )
                } if storage_ids else {}

                for media_id in active_media_ids:
                    item = op_items.get(media_id)
                    if item is None:
                        raise RuntimeError("Delete operation item is missing")
                    media = media_rows.get(media_id)
                    if media is not None:
                        # Refresh queue-time locators in case a pre-barrier
                        # migration moved this legacy Media before the worker
                        # acquired it.
                        item.file_path = media.file_path
                        item.file_hash = media.file_hash
                    item.thumbnail_paths = json.dumps(
                        thumbs_by_media.get(media_id, [])
                    )
                    if media is not None and media.storage_object_id is not None:
                        storage = storage_by_id.get(media.storage_object_id)
                        item.storage_object_id = media.storage_object_id
                        item.storage_kind = storage.kind if storage is not None else None
                        if storage is not None:
                            remaining_ref = await session.scalar(
                                select(MediaItem.id).where(
                                    MediaItem.storage_object_id == storage.id,
                                    MediaItem.id.not_in(active_media_ids),
                                ).limit(1)
                            )
                            if remaining_ref is None:
                                storage.state = "deleting"
                                item.storage_object_key = storage.object_key

                media_artifacts = list(
                    await session.scalars(
                        select(ManagedArtifact).where(
                            ManagedArtifact.owner_kind == "media",
                            ManagedArtifact.owner_id.in_(
                                [str(value) for value in active_media_ids]
                            ),
                            ManagedArtifact.deleted_at.is_(None),
                        )
                    )
                )
                for artifact in media_artifacts:
                    artifact.owner_kind = "delete_operation"
                    artifact.owner_id = str(operation.id)
                    artifact.media_id = None
                    artifact.state = "deleting"

                # Do not rely on SQLite FK cascades: normal application
                # connections historically did not enable foreign keys.
                await session.execute(
                    delete(MediaOwner).where(
                        MediaOwner.media_id.in_(active_media_ids)
                    )
                )
                await session.execute(
                    delete(AssetSnapshot).where(
                        AssetSnapshot.media_id.in_(active_media_ids)
                    )
                )
                await session.execute(
                    delete(ContainerMember).where(
                        ContainerMember.embedded_media_id.in_(active_media_ids),
                        ContainerMember.deleted_at.is_not(None),
                    )
                )
                await session.execute(
                    delete(AssetRevision).where(
                        AssetRevision.primary_media_id.in_(active_media_ids),
                        AssetRevision.deleted_at.is_not(None),
                    )
                )
                await session.execute(
                    delete(MediaThumbnailCache).where(
                        MediaThumbnailCache.media_id.in_(active_media_ids)
                    )
                )
                await session.execute(
                    delete(MediaLineage).where(
                        MediaLineage.media_id.in_(active_media_ids)
                    )
                )
                await session.execute(
                    delete(MediaItem).where(MediaItem.id.in_(active_media_ids))
                )
                await session.execute(
                    update(DeleteOperationItem)
                    .where(
                    DeleteOperationItem.operation_id == operation.id,
                        DeleteOperationItem.media_id.in_(active_media_ids),
                    )
                    .values(
                        state="media_deleted",
                        lease_expires_at=None,
                        updated_at=_utcnow(),
                    )
                )
                op = await session.get(DeleteOperation, operation.id)
                if op is not None:
                    op.current_phase = "unlinking_artifacts"
                    op.updated_at = _utcnow()
                await session.commit()
            except Exception as exc:
                await session.rollback()
                log.error(
                    "DELETE OPS: logical deletion staging failed",
                    operation_id=operation.id,
                    error=str(exc),
                    exc_info=True,
                )
                failed_ids.extend(
                    value for value in active_media_ids if value not in failed_ids
                )

    # Mark failed items
    if failed_ids:
        async with db.async_session_maker() as session:
            await session.execute(
                update(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id == operation.id,
                    DeleteOperationItem.media_id.in_(failed_ids),
                )
                .values(
                    state="failed",
                    lease_expires_at=None,
                    last_error="permanent deletion failed",
                    updated_at=_utcnow(),
                )
            )
            op = await session.get(DeleteOperation, operation.id)
            if op:
                op.processed_items += len(failed_ids)
                op.failed_items += len(failed_ids)
                op.updated_at = _utcnow()
            await session.commit()

    async with db.async_session_maker() as session:
        refreshed = await session.get(DeleteOperation, operation.id)
        if refreshed:
            await ws_manager.broadcast("delete_operation_progress", _operation_payload(refreshed), include_profile=False)

    if completed_ids:
        payload = {"count": len(completed_ids)}
        if len(completed_ids) <= 500:
            payload["media_ids"] = completed_ids
        await ws_manager.broadcast("media_permanently_deleted", payload, include_profile=False)

    return True



async def _batch_scrub_references(session, media_ids: list[int]) -> None:
    """Scrub references for multiple media IDs using batch IN clauses."""
    await _assert_no_live_media_owners(session, media_ids)
    await _assert_no_surviving_legacy_editor_snapshots(session, media_ids)

    # Tombstone lineage data FIRST — before we sever the MediaLineage links
    await _tombstone_descendant_lineage(session, media_ids)

    # Now sever the links
    await session.execute(
        update(Tool).where(Tool.source_media_id.in_(media_ids)).values(source_media_id=None)
    )
    # Permanent delete must leave no trace of the generation: drop the job row
    # entirely (which carries the prompt and other params), and null any sibling
    # batch jobs pointing at a deleted aggregator set so batch UI stays coherent.
    await session.execute(
        update(GenerationJob).where(GenerationJob.batch_output_set_id.in_(media_ids)).values(batch_output_set_id=None)
    )
    await session.execute(
        delete(GenerationJob).where(GenerationJob.result_media_id.in_(media_ids))
    )
    await session.execute(
        update(MediaLineage).where(MediaLineage.source_media_id.in_(media_ids)).values(source_media_id=None, source_file_path=None)
    )
    for model in (Face, MediaKeyword, MediaMarker, MediaTag, MediaToolLineage, ProjectMedia, BoardItem):
        await session.execute(delete(model).where(model.media_id.in_(media_ids)))

    # Null out ChatItem.media_id FK (indexed)
    await session.execute(
        update(ChatItem).where(ChatItem.media_id.in_(media_ids)).values(media_id=None)
    )

    # Rewrite ChatItem JSON blobs in place. The read-time marker in
    # routes/chats.py only decorates the response, which leaves the original
    # attachment / file_path / params text sitting in the DB — that violates
    # "permanent delete leaves no trace." Strip them here.
    await _scrub_chat_item_references(session, media_ids)


async def _scrub_references(session, media_id: int) -> None:
    await _assert_no_live_media_owners(session, [media_id])
    await _assert_no_surviving_legacy_editor_snapshots(session, [media_id])

    # Tombstone lineage data FIRST — before we sever the MediaLineage links
    await _tombstone_descendant_lineage(session, [media_id])

    await session.execute(
        update(Tool).where(Tool.source_media_id == media_id).values(source_media_id=None)
    )
    # Mirror _batch_scrub_references: delete the job row so prompt/params leave
    # no trace, but null sibling batch references so the rest of the batch is sane.
    await session.execute(
        update(GenerationJob).where(GenerationJob.batch_output_set_id == media_id).values(batch_output_set_id=None)
    )
    await session.execute(
        delete(GenerationJob).where(GenerationJob.result_media_id == media_id)
    )
    await session.execute(
        update(MediaLineage).where(MediaLineage.source_media_id == media_id).values(source_media_id=None, source_file_path=None)
    )
    for model in (Face, MediaKeyword, MediaMarker, MediaTag, MediaToolLineage, ProjectMedia, BoardItem):
        await session.execute(delete(model).where(model.media_id == media_id))

    await session.execute(
        update(ChatItem).where(ChatItem.media_id == media_id).values(media_id=None)
    )

    # See _batch_scrub_references — strip ChatItem JSON blobs in place too.
    await _scrub_chat_item_references(session, [media_id])


async def _assert_no_live_media_owners(session, media_ids: list[int]) -> None:
    """Apply the deletion barrier before any locators or files are removed.

    The ownership ledger is the normal authority. Direct Revision/Snapshot
    checks make a ledger discrepancy fail closed, before filesystem deletion.
    Asset-level permanent deletion will release these roots transactionally
    before scheduling Media collection.
    """
    if not media_ids:
        return
    live_owner = await session.scalar(
        select(MediaOwner.id).where(
            MediaOwner.media_id.in_(media_ids),
            MediaOwner.deleted_at.is_(None),
        ).limit(1)
    )
    revision_ref = await session.scalar(
        select(AssetRevision.id).where(
            AssetRevision.primary_media_id.in_(media_ids),
            AssetRevision.deleted_at.is_(None),
        ).limit(1)
    )
    snapshot_ref = await session.scalar(
        select(AssetSnapshot.id).where(
            AssetSnapshot.media_id.in_(media_ids),
            AssetSnapshot.deleted_at.is_(None),
        ).limit(1)
    )
    container_ref = await session.scalar(
        select(ContainerMember.id).where(
            ContainerMember.embedded_media_id.in_(media_ids),
            ContainerMember.deleted_at.is_(None),
        ).limit(1)
    )
    if any(
        value is not None
        for value in (live_owner, revision_ref, snapshot_ref, container_ref)
    ):
        raise RetainedMediaError("Selected Media is retained by a live root")


async def _assert_no_surviving_legacy_editor_snapshots(
    session, media_ids: list[int]
) -> None:
    """Refuse deletion that would strand current sidecar-based editor state.

    Legacy ``.stimmaedit.json`` files embed the source pixels while also storing
    ``source_media_id``. Deleting that source currently makes the surviving edit
    unreopenable and leaves an untracked copy of the source behind. Until Asset
    snapshots make that dependency explicit, fail safely instead of reporting a
    privacy-complete deletion.
    """
    if not media_ids:
        return

    deleted_set = set(media_ids)
    result = await session.execute(
        select(MediaItem.id, MediaItem.file_path).where(
            MediaItem.has_editor_sidecar.is_(True),
            MediaItem.id.not_in(deleted_set),
        )
    )

    dependent_count = 0
    for _media_id, file_path in result.all():
        sidecar_path = Path(f"{file_path}.stimmaedit.json")
        if not sidecar_path.exists():
            continue
        try:
            raw_sidecar = sidecar_path.read_text(encoding="utf-8")
        except OSError:
            dependent_count += 1
            continue
        try:
            sidecar_data = json.loads(raw_sidecar)
        except (json.JSONDecodeError, TypeError):
            # A corrupt legacy project can still embed complete source pixels
            # even when its source ID is truncated. Fail closed rather than
            # certifying deletion around an opaque surviving copy.
            dependent_count += 1
            continue
        if (
            isinstance(sidecar_data, dict)
            and sidecar_data.get("source_media_id") in deleted_set
        ):
            dependent_count += 1

    if dependent_count:
        raise DependentEditorSnapshotError(
            f"{dependent_count} surviving editor snapshot(s) depend on selected Media"
        )





def _tombstone_media_refs(obj: Any, deleted_set: set[int]) -> bool:
    """Walk a parsed JSON structure and tombstone every reference to a
    permanently-deleted media item.

    For any dict whose ``media_id`` is in ``deleted_set``, clear all of its
    contents and replace them with ``{"deleted": True}`` — this preserves the
    dict's position in the surrounding structure (so chat rendering still
    holds together) while dropping file paths, prompts, captions, and any
    other identifying fields. Any integer ID in a ``media_ids`` list is
    filtered out. Returns True if anything was modified.
    """
    changed = False
    if isinstance(obj, dict):
        if any(
            (key == "media_id" or key.endswith("_media_id"))
            and value in deleted_set
            for key, value in obj.items()
        ):
            obj.clear()
            obj["deleted"] = True
            return True
        for key, ids in list(obj.items()):
            if key != "media_ids" and not key.endswith("_media_ids"):
                continue
            if isinstance(ids, list):
                filtered = [
                    item
                    for item in ids
                    if not (isinstance(item, int) and item in deleted_set)
                ]
                if filtered != ids:
                    obj[key] = filtered
                    changed = True
        for value in obj.values():
            if _tombstone_media_refs(value, deleted_set):
                changed = True
    elif isinstance(obj, list):
        for value in obj:
            if _tombstone_media_refs(value, deleted_set):
                changed = True
    return changed


async def _scrub_chat_item_references(session, media_ids: list[int]) -> None:
    """Strip references to permanently-deleted media from ChatItem JSON columns.

    The ``media_id`` FK column is nulled by the surrounding scrub; this rewrites
    ``media_ids`` and the JSON-blob columns (``item_metadata``, ``tool_args``,
    ``tool_result``, ``grid_layout``) so the chat history holds no surviving
    reference — file paths, prompt text inside attachments, etc.

    JSON columns aren't indexed, so we scan rows whose columns are non-null
    and let the walker decide what to rewrite. Chat history is bounded enough
    in practice that a per-batch scan is acceptable.
    """
    if not media_ids:
        return
    deleted_set = set(media_ids)

    result = await session.execute(
        select(ChatItem).where(
            or_(
                ChatItem.media_ids.is_not(None),
                ChatItem.item_metadata.is_not(None),
                ChatItem.tool_args.is_not(None),
                ChatItem.tool_result.is_not(None),
                ChatItem.grid_layout.is_not(None),
            )
        )
    )

    json_fields = ("item_metadata", "tool_args", "tool_result", "grid_layout")
    for item in result.scalars().all():
        if item.media_ids:
            try:
                ids = json.loads(item.media_ids)
            except (json.JSONDecodeError, TypeError):
                item.media_ids = "[]"
                ids = None
            if isinstance(ids, list):
                filtered = [i for i in ids if not (isinstance(i, int) and i in deleted_set)]
                if filtered != ids:
                    item.media_ids = json.dumps(filtered)

        for field in json_fields:
            raw = getattr(item, field)
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                setattr(item, field, None)
                continue
            if _tombstone_media_refs(parsed, deleted_set):
                setattr(item, field, json.dumps(parsed))


async def _tombstone_descendant_lineage(session, deleted_media_ids: list[int]) -> None:
    """
    Find all descendants of deleted media via MediaLineage and rewrite their
    generation_metadata to replace deleted ancestors with tombstones.
    Uses a recursive CTE — no table scans.
    """
    if not deleted_media_ids:
        return

    deleted_set = set(deleted_media_ids)

    # Recursive CTE: walk MediaLineage to find all descendants
    id_list = ",".join(str(int(mid)) for mid in deleted_media_ids)
    result = await session.execute(text(f"""
        WITH RECURSIVE descendants AS (
            SELECT media_id FROM media_lineage WHERE source_media_id IN ({id_list})
            UNION
            SELECT ml.media_id FROM media_lineage ml
            JOIN descendants d ON ml.source_media_id = d.media_id
        )
        SELECT DISTINCT media_id FROM descendants
    """))
    descendant_ids = [row[0] for row in result.all()]

    if not descendant_ids:
        return

    # Exclude any descendants that are themselves being deleted
    descendant_ids = [mid for mid in descendant_ids if mid not in deleted_set]
    if not descendant_ids:
        return

    media_result = await session.execute(
        select(MediaItem).where(
            MediaItem.id.in_(descendant_ids),
            MediaItem.generation_metadata.is_not(None),
        )
    )
    items = media_result.scalars().all()

    for item in items:
        try:
            meta = json.loads(item.generation_metadata)
        except (json.JSONDecodeError, TypeError):
            continue

        changed = False

        # Tombstone lineage_trace entries for deleted ancestors
        if "lineage_trace" in meta and isinstance(meta["lineage_trace"], list):
            new_trace = []
            for entry in meta["lineage_trace"]:
                if isinstance(entry, dict) and entry.get("media_id") in deleted_set:
                    new_trace.append({
                        "deleted": True,
                        "task_type": entry.get("task_type"),
                    })
                    changed = True
                else:
                    new_trace.append(entry)
            meta["lineage_trace"] = new_trace

        # Tombstone source_inputs entries
        if "source_inputs" in meta and isinstance(meta["source_inputs"], list):
            new_inputs = []
            for inp in meta["source_inputs"]:
                if isinstance(inp, dict) and inp.get("media_id") in deleted_set:
                    new_inputs.append({
                        "deleted": True,
                        "role": inp.get("role"),
                    })
                    changed = True
                else:
                    new_inputs.append(inp)
            meta["source_inputs"] = new_inputs

        # Tombstone inspired_by
        inspired = meta.get("inspired_by")
        if isinstance(inspired, dict) and inspired.get("media_id") in deleted_set:
            meta["inspired_by"] = {"deleted": True}
            changed = True

        if changed:
            item.generation_metadata = json.dumps(meta)

    if descendant_ids:
        log.info("DELETE OPS: tombstoned lineage in %d descendants", len(descendant_ids))


async def get_delete_operation(session, operation_id: int) -> DeleteOperation | None:
    return await session.get(DeleteOperation, operation_id)


async def retry_delete_operation(session, operation_id: int) -> DeleteOperation:
    """Resume a failed durable deletion without reconstructing lost roots."""
    operation = await session.get(DeleteOperation, operation_id)
    if operation is None or operation.status != "failed":
        raise ValueError("Delete operation is not retryable")
    failed_items = list(
        await session.scalars(
            select(DeleteOperationItem).where(
                DeleteOperationItem.operation_id == operation_id,
                DeleteOperationItem.state == "failed",
            )
        )
    )
    surviving_media = []
    for item in failed_items:
        media = await session.get(MediaItem, item.media_id)
        if media is not None:
            surviving_media.append(media)
    if operation.kind != "asset" and any(
        media.deleted_at is None for media in surviving_media
    ):
        raise ValueError("Delete operation Media is no longer in Trash")
    await _assert_no_live_media_owners(
        session,
        [media.id for media in surviving_media],
    )
    for item in failed_items:
        media = await session.get(MediaItem, item.media_id)
        item.state = "pending" if media is not None else "media_deleted"
        if media is not None:
            media.deletion_pending_at = media.deletion_pending_at or _utcnow()
        item.lease_expires_at = None
        item.last_error = None
        item.updated_at = _utcnow()
    operation.processed_items = max(
        0, operation.processed_items - operation.failed_items
    )
    operation.failed_items = 0
    operation.status = "queued"
    operation.current_phase = "queued"
    operation.completed_at = None
    operation.last_error = None
    operation.updated_at = _utcnow()
    await session.commit()
    await session.refresh(operation)
    return operation


async def get_active_delete_operation(session, profile_id: str) -> DeleteOperation | None:
    result = await session.execute(
        select(DeleteOperation)
        .where(
            DeleteOperation.profile_id == profile_id,
            DeleteOperation.status.in_(["queued", "running", "failed"]),
        )
        .order_by(DeleteOperation.id.desc())
    )
    return result.scalars().first()

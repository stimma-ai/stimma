import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, delete, exists, func, or_, select, text, update

from core.logging import get_logger
from database import (
    Asset,
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
ASSET_IDENTITY_BATCH_SIZE = 25
ASSET_REFERENCE_BATCH_SIZE = 1000
ASSET_FINALIZE_BATCH_SIZE = 100
LEASE_SECONDS = 60
WORKER_IDLE_SECONDS = 1.0
WORKER_BUSY_YIELD_SECONDS = 0.01
PROGRESS_BROADCAST_INTERVAL_SECONDS = 0.25
LEASE_RECOVERY_INTERVAL_SECONDS = 5.0

_worker_task: asyncio.Task | None = None
_worker_lock = asyncio.Lock()
_last_progress_broadcast_at: dict[str, float] = {}
_last_lease_recovery_at: dict[str, float] = {}


class DependentEditorSnapshotError(RuntimeError):
    """Legacy editor state still embeds Media selected for deletion."""


class SourceOfflineError(OSError):
    """An external file's source root is offline, so its absence proves
    nothing; the unlink must retry after the source returns."""


class RetainedMediaError(RuntimeError):
    """Media is still strongly retained by a new-model root."""


def _media_has_live_root():
    """Return the fail-closed ownership condition for a Media row.

    A historical or tombstoned Media row sharing a locator is not a reason to
    keep the payload. Only a surviving strong root may protect it from unlink.
    """
    return or_(
        exists(
            select(MediaOwner.id).where(
                MediaOwner.media_id == MediaItem.id,
                MediaOwner.deleted_at.is_(None),
            )
        ),
        exists(
            select(AssetRevision.id).where(
                AssetRevision.primary_media_id == MediaItem.id,
                AssetRevision.deleted_at.is_(None),
            )
        ),
        exists(
            select(AssetSnapshot.id).where(
                AssetSnapshot.media_id == MediaItem.id,
                AssetSnapshot.deleted_at.is_(None),
            )
        ),
        exists(
            select(ContainerMember.id).where(
                ContainerMember.embedded_media_id == MediaItem.id,
                ContainerMember.deleted_at.is_(None),
            )
        ),
    )


async def _retained_file_paths(session, paths: list[str]) -> set[str]:
    if not paths:
        return set()
    return set(
        await session.scalars(
            select(MediaItem.file_path)
            .where(
                MediaItem.file_path.in_(paths),
                _media_has_live_root(),
            )
            .distinct()
        )
    )


async def _retained_storage_ids(session, storage_ids: set[int]) -> set[int]:
    if not storage_ids:
        return set()
    return set(
        await session.scalars(
            select(MediaItem.storage_object_id)
            .where(
                MediaItem.storage_object_id.in_(storage_ids),
                _media_has_live_root(),
            )
            .distinct()
        )
    )


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


ASSET_QUEUE_ACTIVE_STATUSES = ("queued", "running", "checkpointing", "failed")
ASSET_QUEUE_VISIBLE_STATUSES = (*ASSET_QUEUE_ACTIVE_STATUSES, "completed")


async def get_delete_progress_summary(session, profile_id: str) -> dict[str, Any] | None:
    """Report the one profile-wide permanent Asset deletion queue.

    Each Asset has one durable operation. Completed operations stay visible
    until the queue drains, so the total never decreases during processing.
    Trigger source and Media payload count are deliberately irrelevant.
    """
    total_assets, processed_assets, failed_assets, earliest_started_at = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                DeleteOperation.status.in_(
                                    ["completed", "checkpointing", "failed"]
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((DeleteOperation.status == "failed", 1), else_=0)
                    ),
                    0,
                ),
                func.min(DeleteOperation.started_at),
            ).where(
                DeleteOperation.profile_id == profile_id,
                DeleteOperation.kind == "asset",
                DeleteOperation.status.in_(ASSET_QUEUE_VISIBLE_STATUSES),
            )
        )
    ).one()
    if not total_assets:
        return None

    statuses = set(
        await session.scalars(
            select(DeleteOperation.status)
            .where(
                DeleteOperation.profile_id == profile_id,
                DeleteOperation.kind == "asset",
                DeleteOperation.status.in_(ASSET_QUEUE_VISIBLE_STATUSES),
            )
            .distinct()
        )
    )
    status = (
        "running"
        if statuses & {"queued", "running", "checkpointing"}
        else "failed"
    )
    if statuses == {"completed"}:
        status = "completed"

    eta = None
    if status == "running" and earliest_started_at is not None:
        if isinstance(earliest_started_at, str):
            earliest_started_at = datetime.fromisoformat(earliest_started_at)
        elapsed = max((_utcnow() - earliest_started_at).total_seconds(), 0.001)
        rate = processed_assets / elapsed
        eta = (total_assets - processed_assets) / rate if rate > 0 else None

    return {
        "status": status,
        "total_assets": total_assets,
        "processed_assets": processed_assets,
        "failed_assets": failed_assets,
        "eta_seconds": eta,
    }


async def _operation_event_payload(session, operation: DeleteOperation) -> dict[str, Any]:
    payload = _operation_payload(operation)
    payload["summary"] = await get_delete_progress_summary(
        session, operation.profile_id
    )
    return payload


async def _broadcast_operation_update(
    session,
    event_name: str,
    operation: DeleteOperation,
    *,
    force: bool = False,
) -> None:
    """Rate-limit expensive queue aggregation and websocket progress events."""
    if not force and event_name in {
        "delete_operation_started",
        "delete_operation_progress",
    }:
        now = time.monotonic()
        previous = _last_progress_broadcast_at.get(operation.profile_id, 0.0)
        if now - previous < PROGRESS_BROADCAST_INTERVAL_SECONDS:
            return
        _last_progress_broadcast_at[operation.profile_id] = now
    await ws_manager.broadcast(
        event_name,
        await _operation_event_payload(session, operation),
        include_profile=False,
    )


async def prepare_asset_delete_queue(session, profile_id: str) -> None:
    """Start a new Asset queue only when the profile is currently idle."""
    active_asset_operation = await session.scalar(
        select(DeleteOperation.id)
        .where(
            DeleteOperation.profile_id == profile_id,
            DeleteOperation.kind == "asset",
            DeleteOperation.status.in_(ASSET_QUEUE_ACTIVE_STATUSES),
        )
        .limit(1)
    )
    if active_asset_operation is not None:
        return
    # Completed rows remain part of a queue until it drains. Retire them once,
    # immediately before the next enqueue request starts.
    await session.execute(
        update(DeleteOperation)
        .where(
            DeleteOperation.profile_id == profile_id,
            DeleteOperation.kind == "asset",
            DeleteOperation.status == "completed",
        )
        .values(status="superseded", updated_at=_utcnow())
    )


async def create_delete_operation(
    session,
    *,
    profile_id: str,
    kind: str,
    media_items: list[MediaItem],
    managed_artifacts: list[ManagedArtifact] | None = None,
    asset_id: int | None = None,
    commit: bool = True,
) -> DeleteOperation:
    operation = DeleteOperation(
        kind=kind,
        profile_id=profile_id,
        asset_id=asset_id,
        status="queued",
        current_phase="queued",
        total_items=0,
        claimed_items=0,
        processed_items=0,
        deleted_items=0,
        failed_items=0,
        updated_at=_utcnow(),
    )
    session.add(operation)
    await session.flush()

    await populate_delete_operation(
        session,
        operation=operation,
        media_items=media_items,
        managed_artifacts=managed_artifacts,
    )

    if commit:
        await session.commit()
        await session.refresh(operation)
    else:
        await session.flush()
    return operation


async def populate_delete_operation(
    session,
    *,
    operation: DeleteOperation,
    media_items: list[MediaItem],
    managed_artifacts: list[ManagedArtifact] | None = None,
) -> None:
    """Attach logical deletion work to an already durable operation."""
    media_ids = [item.id for item in media_items]
    await _assert_no_live_media_owners(session, media_ids)
    barrier_at = _utcnow()
    for item in media_items:
        if item.deletion_pending_at is not None:
            raise RetainedMediaError("Selected Media is already being deleted")
        item.deletion_pending_at = barrier_at

    operation.status = "queued"
    operation.current_phase = "queued"
    operation.total_items = len(media_items)
    operation.claimed_items = 0
    operation.processed_items = 0
    operation.deleted_items = 0
    operation.failed_items = 0
    operation.updated_at = barrier_at

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

    await session.flush()


async def enqueue_asset_delete_operations(
    session,
    *,
    profile_id: str,
    asset_ids: list[int],
) -> list[DeleteOperation]:
    """Durably record Asset targets without deleting identities in the request.

    This transaction intentionally contains only queue bookkeeping. The worker
    performs all reference scrubbing and identity deletion in bounded chunks so
    normal thumbnail and ingestion writes are never blocked behind an entire
    Empty Trash run.
    """
    ordered_ids = list(dict.fromkeys(asset_ids))
    if not ordered_ids:
        return []
    await prepare_asset_delete_queue(session, profile_id)
    existing_operations = list(
        await session.scalars(
            select(DeleteOperation).where(
                DeleteOperation.profile_id == profile_id,
                DeleteOperation.kind == "asset",
                DeleteOperation.asset_id.in_(ordered_ids),
                DeleteOperation.status.in_(ASSET_QUEUE_ACTIVE_STATUSES),
            )
        )
    )
    operation_by_asset = {
        operation.asset_id: operation for operation in existing_operations
    }
    now = _utcnow()
    operations = [
        DeleteOperation(
            kind="asset",
            profile_id=profile_id,
            asset_id=asset_id,
            status="queued",
            current_phase="identity_queued",
            total_items=0,
            claimed_items=0,
            processed_items=0,
            deleted_items=0,
            failed_items=0,
            updated_at=now,
        )
        for asset_id in ordered_ids
        if asset_id not in operation_by_asset
    ]
    session.add_all(operations)
    await session.execute(
        update(Asset)
        .where(
            Asset.id.in_(ordered_ids),
            Asset.state == "trashed",
        )
        .values(state="deleting", updated_at=now)
    )
    await session.commit()
    operation_by_asset.update(
        {operation.asset_id: operation for operation in operations}
    )
    return [operation_by_asset[asset_id] for asset_id in ordered_ids]


async def broadcast_asset_delete_queue_enqueued(
    session,
    operations: list[DeleteOperation],
) -> None:
    """Make newly durable queue progress visible before worker staging."""
    if not operations:
        return
    await _broadcast_operation_update(
        session,
        "delete_operation_started",
        operations[-1],
        force=True,
    )


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


async def stop_delete_worker() -> None:
    """Stop the background delete worker before its database registry closes."""
    global _worker_task

    async with _worker_lock:
        task = _worker_task
        _worker_task = None
        if task is None or task.done():
            return

        task.cancel()
        # Test hosts can replace event loops while the process remains alive.
        # A task from the old loop cannot be awaited here, but clearing the
        # singleton lets the next host start its own worker.
        if task.get_loop() is not asyncio.get_running_loop():
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True), timeout=2.0
            )
        except asyncio.TimeoutError:
            log.warning("DELETE OPS: worker did not stop before shutdown")


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
            # Leave a small writer-fairness window between deletion batches.
            # The ingestion worker lives in another process and otherwise can
            # lose the SQLite writer race indefinitely to this tight loop.
            await asyncio.sleep(
                WORKER_BUSY_YIELD_SECONDS if did_work else WORKER_IDLE_SECONDS
            )
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
            # A TRUNCATE checkpoint needs an exclusive lock. Normal database
            # connections deliberately wait up to 30 seconds for writers, but
            # carrying that timeout into this background worker can stall an
            # otherwise-finished delete operation behind a short-lived reader.
            # Return busy immediately instead; the worker retries on its next
            # pass and still does not report completion until truncation wins.
            await connection.exec_driver_sql("PRAGMA busy_timeout = 0")
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


def _unlink_staged_manifests(
    *,
    profile_id: str,
    staged_items: list[DeleteOperationItem],
    artifacts: list[ManagedArtifact],
    protected_paths: set[str],
    retained_storage_ids: set[int],
) -> None:
    from config import get_settings
    from storage_service import object_path

    trash_service = TrashService()
    offline_roots: list[Path] | None = None

    def _under_offline_source_root(path_str: str) -> Path | None:
        nonlocal offline_roots
        if offline_roots is None:
            offline_roots = []
            for folder in get_settings().get_folders_for_profile(profile_id):
                root = Path(folder.path).expanduser()
                if not root.is_dir():
                    offline_roots.append(root.resolve(strict=False))
        resolved = Path(path_str).expanduser().resolve(strict=False)
        for root in offline_roots:
            if resolved.is_relative_to(root):
                return root
        return None

    for item in staged_items:
        try:
            thumbnail_paths = json.loads(item.thumbnail_paths or "[]")
        except (json.JSONDecodeError, TypeError):
            thumbnail_paths = []
        for thumbnail_path in thumbnail_paths:
            Path(thumbnail_path).unlink(missing_ok=True)
        if item.file_path and item.file_path not in protected_paths:
            target = Path(item.file_path)
            if (
                item.storage_kind == "external"
                and not target.exists()
                and not target.is_symlink()
                and _under_offline_source_root(item.file_path) is not None
            ):
                raise SourceOfflineError()
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
        retry_claimed_ids = list(
            (
                await session.execute(
                    update(DeleteOperationItem)
                    .where(
                        DeleteOperationItem.operation_id == operation_id,
                        DeleteOperationItem.state == "unlink_retry",
                    )
                    .values(
                        state="unlinking_retry",
                        lease_expires_at=_utcnow()
                        + timedelta(seconds=LEASE_SECONDS),
                        updated_at=_utcnow(),
                    )
                    .returning(DeleteOperationItem.media_id)
                )
            ).scalars()
        )
        all_claimed_ids = claimed_ids + retry_claimed_ids
        staged_items = (
            list(
                await session.scalars(
                    select(DeleteOperationItem).where(
                        DeleteOperationItem.operation_id == operation_id,
                        DeleteOperationItem.media_id.in_(all_claimed_ids),
                        DeleteOperationItem.state.in_(
                            ["unlinking", "unlinking_retry"]
                        ),
                    )
                )
            )
            if all_claimed_ids
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
            if item.file_path
        ]
        protected_paths = await _retained_file_paths(
            session,
            compatibility_paths,
        )
        storage_ids = {
            item.storage_object_id
            for item in staged_items
            if item.storage_object_id is not None
        }
        retained_storage_ids = await _retained_storage_ids(
            session,
            storage_ids,
        )
        await session.commit()
    if not staged_items and not artifacts:
        return False, []

    try:
        await asyncio.to_thread(
            _unlink_staged_manifests,
            profile_id=profile_id,
            staged_items=staged_items,
            artifacts=artifacts,
            protected_paths=protected_paths,
            retained_storage_ids=retained_storage_ids,
        )
    except Exception as exc:
        failure_payload = None
        # Never copy exception text into operation records — it can carry
        # filesystem paths. Only the known-safe offline case gets a specific
        # message.
        unlink_error = (
            "source folder offline"
            if isinstance(exc, SourceOfflineError)
            else "permanent deletion failed"
        )
        async with db.async_session_maker() as session:
            operation = await session.get(DeleteOperation, operation_id)
            if operation is not None:
                failure_count = len(staged_items)
                operation.status = "failed"
                operation.failed_items += failure_count
                operation.processed_items += failure_count
                operation.last_error = unlink_error
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
                        # Logical deletion already committed. Preserve that
                        # phase across the retry boundary so a subsequently
                        # reused SQLite Media ID cannot be mistaken for the
                        # row this operation deleted.
                        state="unlink_failed",
                        lease_expires_at=None,
                        last_error=unlink_error,
                        updated_at=_utcnow(),
                    )
                )
            await session.commit()
            if operation is not None:
                failure_payload = await _operation_event_payload(session, operation)
        log.error(
            "DELETE OPS: durable artifact unlink failed",
            operation_id=operation_id,
            error_type=type(exc).__name__,
        )
        if failure_payload is not None:
            await ws_manager.broadcast(
                "delete_operation_failed",
                failure_payload,
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
                    DeleteOperationItem.state.in_(
                        ["unlinking", "unlinking_retry"]
                    ),
                )
            )
        operation = await session.get(DeleteOperation, operation_id)
        if operation is not None:
            operation.processed_items += len(completed_ids)
            operation.deleted_items += len(completed_ids)
            operation.last_error = None
            operation.updated_at = _utcnow()
            remaining_item = await session.scalar(
                select(DeleteOperationItem.media_id)
                .where(
                    DeleteOperationItem.operation_id == operation_id,
                    DeleteOperationItem.state != "failed",
                )
                .limit(1)
            )
            remaining_artifact = await session.scalar(
                select(ManagedArtifact.id)
                .where(
                    ManagedArtifact.owner_kind == "delete_operation",
                    ManagedArtifact.owner_id == str(operation_id),
                    ManagedArtifact.state == "deleting",
                    ManagedArtifact.deleted_at.is_(None),
                )
                .limit(1)
            )
            if (
                operation.kind == "asset"
                and remaining_item is None
                and remaining_artifact is None
            ):
                operation.status = "checkpointing"
                operation.current_phase = "checkpointing"
            else:
                operation.current_phase = "finalizing"
        await session.commit()

    # A delayed unlink retry may run after SQLite has reused the old integer
    # Media ID. The Asset identity was already removed and announced before
    # unlinking, so broadcasting that stale ID now could hide unrelated,
    # newly ingested Media in compatibility clients.
    broadcast_ids = [
        media_id
        for media_id in completed_ids
        if media_id not in set(retry_claimed_ids)
    ]
    if broadcast_ids:
        payload: dict[str, Any] = {"count": len(broadcast_ids)}
        if len(broadcast_ids) <= 500:
            payload["media_ids"] = broadcast_ids
        await ws_manager.broadcast(
            "media_permanently_deleted", payload, include_profile=False
        )
    return True, completed_ids


async def _finalize_staged_asset_batch(
    db,
    *,
    profile_id: str,
    operation_ids: list[int],
) -> tuple[bool, list[int]]:
    """Finalize clean, pre-staged Asset operations with two batch commits."""
    if not operation_ids:
        return False, []
    now = _utcnow()
    async with db.async_session_maker() as session:
        claimed_rows = (
            await session.execute(
                update(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id.in_(operation_ids),
                    DeleteOperationItem.state == "media_deleted",
                )
                .values(
                    state="unlinking",
                    lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                    updated_at=now,
                )
                .returning(
                    DeleteOperationItem.operation_id,
                    DeleteOperationItem.media_id,
                )
            )
        ).all()
        claimed_operation_ids = {row.operation_id for row in claimed_rows}
        staged_items = (
            list(
                await session.scalars(
                    select(DeleteOperationItem).where(
                        DeleteOperationItem.operation_id.in_(
                            claimed_operation_ids
                        ),
                        DeleteOperationItem.state == "unlinking",
                    )
                )
            )
            if claimed_operation_ids
            else []
        )
        artifacts = list(
            await session.scalars(
                select(ManagedArtifact).where(
                    ManagedArtifact.owner_kind == "delete_operation",
                    ManagedArtifact.owner_id.in_(
                        [str(value) for value in operation_ids]
                    ),
                    ManagedArtifact.state == "deleting",
                    ManagedArtifact.deleted_at.is_(None),
                )
            )
        )
        artifact_operation_ids = {
            int(artifact.owner_id) for artifact in artifacts
        }
        operations_with_media_items = set(
            await session.scalars(
                select(DeleteOperationItem.operation_id)
                .where(
                    DeleteOperationItem.operation_id.in_(operation_ids)
                )
                .distinct()
            )
        )
        eligible_operation_ids = (
            claimed_operation_ids
            | (artifact_operation_ids - operations_with_media_items)
        )
        if not eligible_operation_ids:
            await session.rollback()
            return False, []

        compatibility_paths = [
            item.file_path for item in staged_items if item.file_path
        ]
        protected_paths = await _retained_file_paths(
            session,
            compatibility_paths,
        )
        storage_ids = {
            item.storage_object_id
            for item in staged_items
            if item.storage_object_id is not None
        }
        retained_storage_ids = await _retained_storage_ids(
            session,
            storage_ids,
        )
        await session.commit()

    items_by_operation: dict[int, list[DeleteOperationItem]] = {}
    for item in staged_items:
        items_by_operation.setdefault(item.operation_id, []).append(item)
    artifacts_by_operation: dict[int, list[ManagedArtifact]] = {}
    for artifact in artifacts:
        artifacts_by_operation.setdefault(
            int(artifact.owner_id), []
        ).append(artifact)

    def _unlink_operations():
        results = []
        for operation_id in sorted(eligible_operation_ids):
            try:
                _unlink_staged_manifests(
                    profile_id=profile_id,
                    staged_items=items_by_operation.get(operation_id, []),
                    artifacts=artifacts_by_operation.get(operation_id, []),
                    protected_paths=protected_paths,
                    retained_storage_ids=retained_storage_ids,
                )
                results.append((operation_id, None))
            except Exception as exc:
                results.append((operation_id, exc))
        return results

    unlink_results = await asyncio.to_thread(_unlink_operations)
    failures = {
        operation_id: exc
        for operation_id, exc in unlink_results
        if exc is not None
    }
    successful_operation_ids = eligible_operation_ids - set(failures)
    completed_ids = [
        item.media_id
        for item in staged_items
        if item.operation_id in successful_operation_ids
    ]

    async with db.async_session_maker() as session:
        successful_storage_ids = {
            item.storage_object_id
            for item in staged_items
            if item.operation_id in successful_operation_ids
            and item.storage_object_id is not None
        }
        still_retained_storage_ids = await _retained_storage_ids(
            session,
            successful_storage_ids,
        )
        deletable_storage_ids = (
            successful_storage_ids - still_retained_storage_ids
        )
        if deletable_storage_ids:
            await session.execute(
                delete(StorageObject).where(
                    StorageObject.id.in_(deletable_storage_ids),
                    StorageObject.state == "deleting",
                )
            )
        if still_retained_storage_ids:
            await session.execute(
                update(StorageObject)
                .where(
                    StorageObject.id.in_(still_retained_storage_ids),
                    StorageObject.state == "deleting",
                )
                .values(state="available", deleted_at=None)
            )

        successful_artifact_ids = [
            artifact.id
            for artifact in artifacts
            if int(artifact.owner_id) in successful_operation_ids
        ]
        if successful_artifact_ids:
            await session.execute(
                delete(ManagedArtifact).where(
                    ManagedArtifact.id.in_(successful_artifact_ids)
                )
            )
        if successful_operation_ids:
            await session.execute(
                delete(DeleteOperationItem).where(
                    DeleteOperationItem.operation_id.in_(
                        successful_operation_ids
                    ),
                    DeleteOperationItem.state == "unlinking",
                )
            )

        safe_failure_errors: dict[int, str] = {}
        for operation_id, exc in failures.items():
            unlink_error = (
                "source folder offline"
                if isinstance(exc, SourceOfflineError)
                else "permanent deletion failed"
            )
            safe_failure_errors[operation_id] = unlink_error
            await session.execute(
                update(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id == operation_id,
                    DeleteOperationItem.state == "unlinking",
                )
                .values(
                    state="unlink_failed",
                    lease_expires_at=None,
                    last_error=unlink_error,
                    updated_at=_utcnow(),
                )
            )

        operations = list(
            await session.scalars(
                select(DeleteOperation).where(
                    DeleteOperation.id.in_(eligible_operation_ids)
                )
            )
        )
        completed_count_by_operation: dict[int, int] = {}
        for item in staged_items:
            completed_count_by_operation[item.operation_id] = (
                completed_count_by_operation.get(item.operation_id, 0) + 1
            )
        for operation in operations:
            item_count = completed_count_by_operation.get(operation.id, 0)
            operation.processed_items += item_count
            operation.updated_at = _utcnow()
            if operation.id in failures:
                operation.status = "failed"
                operation.failed_items += item_count
                operation.last_error = safe_failure_errors[operation.id]
                operation.current_phase = "failed"
                operation.completed_at = operation.updated_at
            else:
                operation.deleted_items += item_count
                operation.last_error = None
                operation.status = "checkpointing"
                operation.current_phase = "checkpointing"
        await session.commit()

        for operation in operations:
            if operation.id not in failures:
                continue
            log.error(
                "DELETE OPS: durable artifact unlink failed",
                operation_id=operation.id,
                error_type=type(failures[operation.id]).__name__,
            )
            await ws_manager.broadcast(
                "delete_operation_failed",
                await _operation_event_payload(session, operation),
                include_profile=False,
            )

    if completed_ids:
        payload: dict[str, Any] = {"count": len(completed_ids)}
        if len(completed_ids) <= 500:
            payload["media_ids"] = completed_ids
        await ws_manager.broadcast(
            "media_permanently_deleted", payload, include_profile=False
        )
    return True, completed_ids


async def _checkpoint_asset_queue_if_drained(db, profile_id: str) -> bool:
    """Checkpoint once after all queued Asset operations reach the barrier."""
    async with db.async_session_maker() as session:
        remaining = await session.scalar(
            select(DeleteOperation.id)
            .where(
                DeleteOperation.profile_id == profile_id,
                DeleteOperation.kind == "asset",
                DeleteOperation.status.in_(["queued", "running"]),
            )
            .limit(1)
        )
        if remaining is not None:
            return False
        checkpoint_ids = list(
            await session.scalars(
                select(DeleteOperation.id)
                .where(
                    DeleteOperation.profile_id == profile_id,
                    DeleteOperation.kind == "asset",
                    DeleteOperation.status == "checkpointing",
                )
                .order_by(DeleteOperation.id.asc())
            )
        )
    if not checkpoint_ids or not await _truncate_privacy_wal(db):
        return False

    async with db.async_session_maker() as session:
        operations = list(
            await session.scalars(
                select(DeleteOperation)
                .where(
                    DeleteOperation.id.in_(checkpoint_ids),
                    DeleteOperation.status == "checkpointing",
                )
                .order_by(DeleteOperation.id.asc())
            )
        )
        if not operations:
            return False
        completed_at = _utcnow()
        for operation in operations:
            operation.current_phase = "completed"
            operation.status = "failed" if operation.failed_items else "completed"
            operation.completed_at = completed_at
            operation.updated_at = completed_at
        await session.commit()
        representative = operations[-1]
        event_name = (
            "delete_operation_failed"
            if any(operation.failed_items for operation in operations)
            else "delete_operation_completed"
        )
        await _broadcast_operation_update(
            session,
            event_name,
            representative,
            force=True,
        )
    return True


async def _prepare_queued_asset_references(db, profile_id: str) -> bool:
    """Scrub weak Asset references once for a large queue slice.

    Identity staging stays deliberately small to keep SQLite write-lock
    windows short. Reference discovery, especially recursive chat JSON, is
    queue-shaped work and must not be repeated for every identity slice.
    """
    async with db.async_session_maker() as session:
        operations = list(
            await session.scalars(
                select(DeleteOperation)
                .where(
                    DeleteOperation.profile_id == profile_id,
                    DeleteOperation.kind == "asset",
                    DeleteOperation.status == "queued",
                    DeleteOperation.current_phase == "identity_queued",
                )
                .order_by(DeleteOperation.id.asc())
                .limit(ASSET_REFERENCE_BATCH_SIZE)
            )
        )
        if not operations:
            return False

        operation_by_asset = {
            operation.asset_id: operation
            for operation in operations
            if operation.asset_id is not None
        }
        assets = {
            asset.id: asset
            for asset in await session.scalars(
                select(Asset).where(Asset.id.in_(operation_by_asset))
            )
        }
        valid_asset_ids: list[int] = []
        now = _utcnow()
        for asset_id, operation in operation_by_asset.items():
            asset = assets.get(asset_id)
            if asset is None:
                # The identity commit won a crash race; only the shared privacy
                # checkpoint remains.
                operation.status = "checkpointing"
                operation.current_phase = "checkpointing"
                operation.started_at = operation.started_at or now
                operation.updated_at = now
            elif asset.state not in {"trashed", "deleting"}:
                operation.status = "failed"
                operation.current_phase = "failed"
                operation.failed_items = 1
                operation.last_error = "Asset is no longer in Trash"
                operation.started_at = operation.started_at or now
                operation.completed_at = now
                operation.updated_at = now
            else:
                valid_asset_ids.append(asset_id)

        if valid_asset_ids:
            from asset_deletion_service import prepare_asset_reference_deletion

            await prepare_asset_reference_deletion(session, valid_asset_ids)
            for asset_id in valid_asset_ids:
                operation = operation_by_asset[asset_id]
                operation.current_phase = "identity_refs_scrubbed"
                operation.updated_at = now

        await session.commit()
        await _broadcast_operation_update(
            session,
            "delete_operation_progress",
            operations[-1],
        )
    return True


async def _stage_queued_asset_identities(db, profile_id: str) -> bool:
    """Convert a bounded set of durable Asset targets into unlink work."""
    async with db.async_session_maker() as session:
        operations = list(
            await session.scalars(
                select(DeleteOperation)
                .where(
                    DeleteOperation.profile_id == profile_id,
                    DeleteOperation.kind == "asset",
                    DeleteOperation.status == "queued",
                    DeleteOperation.current_phase == "identity_refs_scrubbed",
                )
                .order_by(DeleteOperation.id.asc())
                .limit(ASSET_IDENTITY_BATCH_SIZE)
            )
        )
        if not operations:
            return False

        operation_by_asset = {
            operation.asset_id: operation
            for operation in operations
            if operation.asset_id is not None
        }
        asset_ids = list(operation_by_asset)
        assets = {
            asset.id: asset
            for asset in await session.scalars(
                select(Asset).where(Asset.id.in_(asset_ids))
            )
        }
        valid_asset_ids: list[int] = []
        now = _utcnow()
        for asset_id, operation in operation_by_asset.items():
            asset = assets.get(asset_id)
            if asset is None:
                # Deletion is idempotent across a crash after identity commit.
                operation.status = "checkpointing"
                operation.current_phase = "checkpointing"
                operation.started_at = operation.started_at or now
                operation.updated_at = now
            elif asset.state not in {"trashed", "deleting"}:
                operation.status = "failed"
                operation.current_phase = "failed"
                operation.failed_items = 1
                operation.last_error = "Asset is no longer in Trash"
                operation.started_at = operation.started_at or now
                operation.completed_at = now
                operation.updated_at = now
            else:
                valid_asset_ids.append(asset_id)

        revisions_by_asset: dict[int, list[AssetRevision]] = {
            asset_id: [] for asset_id in valid_asset_ids
        }
        revision_media_ids: list[int] = []
        if valid_asset_ids:
            revisions = list(
                await session.scalars(
                    select(AssetRevision).where(
                        AssetRevision.asset_id.in_(valid_asset_ids)
                    )
                )
            )
            for revision in revisions:
                revisions_by_asset[revision.asset_id].append(revision)
                revision_media_ids.append(revision.primary_media_id)

            from asset_deletion_service import permanently_delete_asset

            for asset_id in valid_asset_ids:
                await permanently_delete_asset(
                    session,
                    asset_id=asset_id,
                    profile_id=profile_id,
                    queue_prepared=True,
                    references_prepared=True,
                    commit=False,
                    known_revisions=revisions_by_asset[asset_id],
                    existing_operation=operation_by_asset[asset_id],
                )

            valid_operation_ids = [
                operation_by_asset[asset_id].id for asset_id in valid_asset_ids
            ]
            await prescrub_delete_operation_items(
                session,
                valid_operation_ids,
            )
            await prestage_delete_operation_items(
                session,
                valid_operation_ids,
            )
            staged_at = _utcnow()
            for asset_id in valid_asset_ids:
                operation = operation_by_asset[asset_id]
                if (
                    operation.total_items == 0
                    and operation.status == "queued"
                    and operation.current_phase == "queued"
                ):
                    # Zero-Media operations can still own Asset/editor
                    # artifacts. Send them through the same batch finalizer.
                    operation.status = "running"
                    operation.current_phase = "unlinking_artifacts"
                    operation.started_at = operation.started_at or staged_at
                    operation.updated_at = staged_at

        await session.commit()
        representative = operations[-1]
        await _broadcast_operation_update(
            session,
            "delete_operation_progress",
            representative,
        )

    if valid_asset_ids:
        event_payload = {
            "asset_ids": valid_asset_ids,
            "media_ids": revision_media_ids,
        }
        await ws_manager.broadcast("asset_identities_deleted", event_payload)
        await ws_manager.broadcast("assets_permanently_deleted", event_payload)
        if len(valid_asset_ids) == 1:
            singular_payload = {
                "asset_id": valid_asset_ids[0],
                "media_ids": revision_media_ids,
            }
            await ws_manager.broadcast(
                "asset_identity_deleted", singular_payload
            )
            await ws_manager.broadcast(
                "asset_permanently_deleted", singular_payload
            )
    return True


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

    identity_staged = await _stage_queued_asset_identities(db, profile_id)
    references_prepared = False
    if not identity_staged:
        references_prepared = await _prepare_queued_asset_references(
            db,
            profile_id,
        )
        if references_prepared:
            identity_staged = await _stage_queued_asset_identities(
                db,
                profile_id,
            )

    async with db.async_session_maker() as session:
        recovery_now = time.monotonic()
        previous_recovery = _last_lease_recovery_at.get(profile_id, 0.0)
        if recovery_now - previous_recovery >= LEASE_RECOVERY_INTERVAL_SECONDS:
            _last_lease_recovery_at[profile_id] = recovery_now
            expired_lease = await session.scalar(
                select(DeleteOperationItem.media_id)
                .where(
                    DeleteOperationItem.state.in_(
                        [
                            "claimed",
                            "refs_scrubbed",
                            "cache_purged",
                            "unlinking",
                            "unlinking_retry",
                        ]
                    ),
                    DeleteOperationItem.lease_expires_at.is_not(None),
                    DeleteOperationItem.lease_expires_at < now,
                )
                .limit(1)
            )
            if expired_lease is not None:
                await session.execute(
                    update(DeleteOperationItem)
                    .where(
                        DeleteOperationItem.state.in_(
                            ["claimed", "refs_scrubbed", "cache_purged"]
                        ),
                        DeleteOperationItem.lease_expires_at.is_not(None),
                        DeleteOperationItem.lease_expires_at < now,
                    )
                    .values(
                        state="pending",
                        lease_expires_at=None,
                        updated_at=now,
                    )
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
                await session.execute(
                    update(DeleteOperationItem)
                    .where(
                        DeleteOperationItem.state == "unlinking_retry",
                        DeleteOperationItem.lease_expires_at.is_not(None),
                        DeleteOperationItem.lease_expires_at < now,
                    )
                    .values(
                        state="unlink_retry",
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                await session.commit()
            else:
                await session.rollback()

        ready_asset_operation_ids = list(
            await session.scalars(
                select(DeleteOperation.id)
                .where(
                    DeleteOperation.profile_id == profile_id,
                    DeleteOperation.kind == "asset",
                    DeleteOperation.status == "running",
                    DeleteOperation.current_phase == "unlinking_artifacts",
                )
                .order_by(DeleteOperation.id.asc())
                .limit(ASSET_FINALIZE_BATCH_SIZE)
            )
        )
        if ready_asset_operation_ids:
            await session.rollback()
            finalized, _ = await _finalize_staged_asset_batch(
                db,
                profile_id=profile_id,
                operation_ids=ready_asset_operation_ids,
            )
            if finalized:
                return True

        result = await session.execute(
            select(DeleteOperation)
            .where(
                DeleteOperation.profile_id == profile_id,
                DeleteOperation.status.in_(["queued", "running"]),
                or_(
                    DeleteOperation.current_phase.is_(None),
                    DeleteOperation.current_phase != "identity_queued",
                ),
            )
            .order_by(DeleteOperation.id.asc())
        )
        operation = result.scalars().first()
        if not operation:
            await session.rollback()
            checkpointed = await _checkpoint_asset_queue_if_drained(
                db,
                profile_id,
            )
            return (
                checkpointed
                or identity_staged
                or references_prepared
                or chat_result.finalized_chats > 0
            )

        if operation.status == "queued":
            operation.status = "running"
            operation.started_at = now
            operation.current_phase = "claiming"
            operation.updated_at = now
            await session.commit()
            await _broadcast_operation_update(
                session,
                "delete_operation_started",
                operation,
            )

        pending_logical_work = await session.scalar(
            select(DeleteOperationItem.media_id).where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.state.in_(["pending", "refs_scrubbed"]),
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
            select(DeleteOperationItem.media_id, DeleteOperationItem.state)
            .where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.state.in_(["pending", "refs_scrubbed"]),
            )
            .order_by(DeleteOperationItem.media_id.asc())
            .limit(DELETE_BATCH_SIZE)
        )
        claim_rows = claim_result.all()
        media_ids = [media_id for media_id, _state in claim_rows]
        prescrubbed_ids = {
            media_id
            for media_id, state in claim_rows
            if state == "refs_scrubbed"
        }

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

            if operation.kind == "asset":
                operation.current_phase = "checkpointing"
                operation.status = "checkpointing"
                operation.updated_at = _utcnow()
                await session.commit()
                await _broadcast_operation_update(
                    session,
                    "delete_operation_progress",
                    operation,
                )
                await session.rollback()
                await _checkpoint_asset_queue_if_drained(db, profile_id)
                return True

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
            await ws_manager.broadcast(event_name, await _operation_event_payload(session, operation), include_profile=False)
            if operation_kind == "empty_trash" and operation.deleted_items:
                await ws_manager.broadcast("trash_emptied", {"count": operation.deleted_items}, include_profile=False)
            return True

        lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        claimed_result = await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.media_id.in_(media_ids),
                DeleteOperationItem.state.in_(["pending", "refs_scrubbed"]),
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
    media_ids_to_scrub = [
        media_id for media_id in media_ids if media_id not in prescrubbed_ids
    ]
    if media_ids_to_scrub:
        async with db.async_session_maker() as session:
            try:
                await _batch_scrub_references(session, media_ids_to_scrub)
            except Exception as exc:
                log.error("DELETE OPS: batch scrub failed, falling back to individual", error=str(exc), exc_info=True)
                await session.rollback()
                # Fallback to individual scrubbing
                for media_id in media_ids_to_scrub:
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
            await _broadcast_operation_update(
                session,
                "delete_operation_progress",
                refreshed,
            )

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


async def prescrub_delete_operation_items(
    session,
    operation_ids: list[int],
) -> int:
    """Scrub one bulk enqueue's Media references in a single database pass.

    A savepoint keeps enqueue semantics unchanged if a legacy dependency or
    another scrub failure requires the normal per-operation retry path.
    """
    if not operation_ids:
        return 0
    media_ids = list(
        await session.scalars(
            select(DeleteOperationItem.media_id).where(
                DeleteOperationItem.operation_id.in_(operation_ids),
                DeleteOperationItem.state == "pending",
            )
        )
    )
    if not media_ids:
        return 0
    try:
        async with session.begin_nested():
            await _batch_scrub_references(session, media_ids)
            await session.execute(
                update(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id.in_(operation_ids),
                    DeleteOperationItem.state == "pending",
                )
                .values(state="refs_scrubbed", updated_at=_utcnow())
            )
    except Exception as exc:
        log.info(
            "DELETE OPS: bulk pre-scrub deferred to worker",
            error_type=type(exc).__name__,
        )
        return 0
    return len(media_ids)


async def prestage_delete_operation_items(
    session,
    operation_ids: list[int],
) -> int:
    """Stage a successfully pre-scrubbed bulk enqueue in set-based SQL."""
    if not operation_ids:
        return 0
    items = list(
        await session.scalars(
            select(DeleteOperationItem).where(
                DeleteOperationItem.operation_id.in_(operation_ids),
                DeleteOperationItem.state == "refs_scrubbed",
            )
        )
    )
    if not items:
        return 0
    media_ids = [item.media_id for item in items]
    await _assert_no_live_media_owners(session, media_ids)

    media_rows = {
        media.id: media
        for media in await session.scalars(
            select(MediaItem).where(MediaItem.id.in_(media_ids))
        )
    }
    thumbs_by_media: dict[int, list[str]] = {}
    for media_id, cache_path in (
        await session.execute(
            select(
                MediaThumbnailCache.media_id,
                MediaThumbnailCache.cache_path,
            ).where(MediaThumbnailCache.media_id.in_(media_ids))
        )
    ).all():
        thumbs_by_media.setdefault(media_id, []).append(cache_path)

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
    retained_storage_ids = await _retained_storage_ids(
        session,
        storage_ids,
    )
    item_by_media = {item.media_id: item for item in items}
    for item in items:
        media = media_rows.get(item.media_id)
        if media is None:
            continue
        item.file_path = media.file_path
        item.file_hash = media.file_hash
        item.thumbnail_paths = json.dumps(thumbs_by_media.get(item.media_id, []))
        if media.storage_object_id is None:
            continue
        storage = storage_by_id.get(media.storage_object_id)
        item.storage_object_id = media.storage_object_id
        item.storage_kind = storage.kind if storage is not None else None
        if storage is not None and storage.id not in retained_storage_ids:
            storage.state = "deleting"
            item.storage_object_key = storage.object_key

    media_artifacts = list(
        await session.scalars(
            select(ManagedArtifact).where(
                ManagedArtifact.owner_kind == "media",
                ManagedArtifact.owner_id.in_([str(value) for value in media_ids]),
                ManagedArtifact.deleted_at.is_(None),
            )
        )
    )
    for artifact in media_artifacts:
        item = item_by_media.get(artifact.media_id)
        if item is None:
            continue
        artifact.owner_kind = "delete_operation"
        artifact.owner_id = str(item.operation_id)
        artifact.media_id = None
        artifact.state = "deleting"

    await session.execute(delete(MediaOwner).where(MediaOwner.media_id.in_(media_ids)))
    await session.execute(
        delete(AssetSnapshot).where(AssetSnapshot.media_id.in_(media_ids))
    )
    await session.execute(
        delete(ContainerMember).where(
            ContainerMember.embedded_media_id.in_(media_ids),
            ContainerMember.deleted_at.is_not(None),
        )
    )
    await session.execute(
        delete(AssetRevision).where(
            AssetRevision.primary_media_id.in_(media_ids),
            AssetRevision.deleted_at.is_not(None),
        )
    )
    await session.execute(
        delete(MediaThumbnailCache).where(
            MediaThumbnailCache.media_id.in_(media_ids)
        )
    )
    await session.execute(
        delete(MediaLineage).where(MediaLineage.media_id.in_(media_ids))
    )
    await session.execute(delete(MediaItem).where(MediaItem.id.in_(media_ids)))
    now = _utcnow()
    await session.execute(
        update(DeleteOperationItem)
        .where(
            DeleteOperationItem.operation_id.in_(operation_ids),
            DeleteOperationItem.state == "refs_scrubbed",
        )
        .values(
            state="media_deleted",
            lease_expires_at=None,
            updated_at=now,
        )
    )
    operations = list(
        await session.scalars(
            select(DeleteOperation).where(DeleteOperation.id.in_(operation_ids))
        )
    )
    for operation in operations:
        if operation.total_items:
            operation.status = "running"
            operation.current_phase = "unlinking_artifacts"
            operation.claimed_items = operation.total_items
            operation.started_at = operation.started_at or now
            operation.updated_at = now
    await session.flush()
    return len(media_ids)


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
                DeleteOperationItem.state.in_(["failed", "unlink_failed"]),
            )
        )
    )
    # Older operations recorded unlink failures as generic ``failed`` rows.
    # ``thumbnail_paths`` was durably populated in the same transaction that
    # deleted the Media row, so it is a safe compatibility discriminator.
    # Never look up these items by Media ID: SQLite may have reused that ID for
    # newly ingested Media while the unlink operation was waiting for retry.
    unlink_failed_items = {
        (item.operation_id, item.media_id)
        for item in failed_items
        if item.state == "unlink_failed"
        or (item.state == "failed" and item.thumbnail_paths is not None)
    }
    surviving_media = []
    for item in failed_items:
        if (item.operation_id, item.media_id) in unlink_failed_items:
            continue
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
        logical_delete_committed = (
            item.operation_id,
            item.media_id,
        ) in unlink_failed_items
        media = (
            None
            if logical_delete_committed
            else await session.get(MediaItem, item.media_id)
        )
        item.state = (
            "unlink_retry"
            if logical_delete_committed or media is None
            else "pending"
        )
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
    target_asset = (
        await session.get(Asset, operation.asset_id)
        if operation.kind == "asset" and operation.asset_id is not None
        else None
    )
    operation.current_phase = (
        "identity_queued"
        if target_asset is not None and not failed_items
        else "queued"
    )
    operation.completed_at = None
    operation.last_error = None
    operation.updated_at = _utcnow()
    await session.commit()
    await session.refresh(operation)
    return operation


async def retry_failed_delete_operations(session, profile_id: str) -> int:
    """Retry every failed Asset deletion for a profile."""
    operation_ids = list(
        await session.scalars(
            select(DeleteOperation.id)
            .where(
                DeleteOperation.profile_id == profile_id,
                DeleteOperation.kind == "asset",
                DeleteOperation.status == "failed",
            )
            .order_by(DeleteOperation.id.asc())
        )
    )
    retried = 0
    for operation_id in operation_ids:
        try:
            await retry_delete_operation(session, operation_id)
            retried += 1
        except (ValueError, RetainedMediaError):
            await session.rollback()
            continue
    return retried


async def get_active_delete_operation(session, profile_id: str) -> DeleteOperation | None:
    result = await session.execute(
        select(DeleteOperation)
        .where(
            DeleteOperation.profile_id == profile_id,
            DeleteOperation.kind == "asset",
            DeleteOperation.status.in_(
                ["queued", "running", "checkpointing", "failed"]
            ),
        )
        .order_by(DeleteOperation.id.desc())
    )
    return result.scalars().first()

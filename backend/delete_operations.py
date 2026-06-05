import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select, text, update

from core.logging import get_logger
from database import (
    BoardItem,
    ChatItem,
    DeleteOperation,
    DeleteOperationItem,
    Face,
    GenerationJob,
    MediaItem,
    MediaKeyword,
    MediaLineage,
    MediaMarker,
    MediaTag,
    MediaThumbnailCache,
    MediaToolLineage,
    ProjectMedia,
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
) -> DeleteOperation:
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

    await session.commit()
    await session.refresh(operation)
    return operation


async def ensure_delete_worker_started() -> None:
    global _worker_task

    async with _worker_lock:
        if _worker_task and not _worker_task.done():
            return
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


async def _process_profile(profile_id: str) -> bool:
    registry = get_database_registry()
    db = registry.get_database(profile_id)
    now = _utcnow()

    async with db.async_session_maker() as session:
        await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.state.in_(["claimed", "refs_scrubbed", "cache_purged", "media_deleted"]),
                DeleteOperationItem.lease_expires_at.is_not(None),
                DeleteOperationItem.lease_expires_at < now,
            )
            .values(state="pending", lease_expires_at=None, updated_at=now)
        )
        await session.commit()

        result = await session.execute(
            select(DeleteOperation)
            .where(DeleteOperation.profile_id == profile_id, DeleteOperation.status.in_(["queued", "running"]))
            .order_by(DeleteOperation.id.asc())
        )
        operation = result.scalars().first()
        if not operation:
            return False

        if operation.status == "queued":
            operation.status = "running"
            operation.started_at = now
            operation.current_phase = "claiming"
            operation.updated_at = now
            await session.commit()
            await ws_manager.broadcast("delete_operation_started", _operation_payload(operation), include_profile=False)

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

            operation.current_phase = "completed"
            operation.status = "failed" if operation.failed_items else "completed"
            operation.completed_at = _utcnow()
            operation.updated_at = operation.completed_at
            await session.commit()
            event_name = "delete_operation_failed" if operation.failed_items else "delete_operation_completed"
            await ws_manager.broadcast(event_name, _operation_payload(operation), include_profile=False)
            if operation.kind == "empty_trash" and operation.deleted_items:
                await ws_manager.broadcast("trash_emptied", {"count": operation.deleted_items}, include_profile=False)
            return True

        lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        await session.execute(
            update(DeleteOperationItem)
            .where(
                DeleteOperationItem.operation_id == operation.id,
                DeleteOperationItem.media_id.in_(media_ids),
            )
            .values(
                state="claimed",
                lease_expires_at=lease_expires_at,
                attempt_count=DeleteOperationItem.attempt_count + 1,
                updated_at=now,
            )
        )
        operation.claimed_items += len(media_ids)
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
                    log.error("DELETE OPS: scrub failed", media_id=media_id, error=str(exc2), exc_info=True)
                    failed_ids.append(media_id)
        await session.commit()

    # Phase 2: Collect file paths and purge artifacts
    file_paths: list[tuple[int, str | None, list[Path]]] = []
    active_media_ids = [mid for mid in media_ids if mid not in failed_ids]
    async with db.async_session_maker() as session:
        # Batch fetch all operation items
        if active_media_ids:
            op_items_result = await session.execute(
                select(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id == operation.id,
                    DeleteOperationItem.media_id.in_(active_media_ids),
                )
            )
            op_items = {item.media_id: item for item in op_items_result.scalars().all()}

            # Batch fetch all thumbnail paths
            thumb_result = await session.execute(
                select(MediaThumbnailCache.media_id, MediaThumbnailCache.cache_path)
                .where(MediaThumbnailCache.media_id.in_(active_media_ids))
            )
            thumbs_by_media: dict[int, list[Path]] = {}
            for mid, cache_path in thumb_result.all():
                thumbs_by_media.setdefault(mid, []).append(Path(cache_path))

            for media_id in active_media_ids:
                item = op_items.get(media_id)
                if not item:
                    completed_ids.append(media_id)
                    continue
                file_paths.append((media_id, item.file_path, thumbs_by_media.get(media_id, [])))

            # Batch delete all thumbnail cache rows
            await session.execute(delete(MediaThumbnailCache).where(MediaThumbnailCache.media_id.in_(active_media_ids)))
        await session.commit()

    # Delete files in a thread to avoid blocking the event loop
    trash_service = TrashService()

    def _delete_files():
        for media_id, file_path, thumbnail_paths in file_paths:
            for thumb_path in thumbnail_paths:
                try:
                    thumb_path.unlink(missing_ok=True)
                except Exception:
                    pass
            if file_path:
                try:
                    trash_service.permanently_delete(file_path)
                except (FileNotFoundError, ValueError):
                    pass

    await asyncio.to_thread(_delete_files)

    # Phase 3: Batch delete DB rows
    successful_media_ids = [mid for mid, _, _ in file_paths]
    if successful_media_ids:
        async with db.async_session_maker() as session:
            await session.execute(delete(MediaLineage).where(MediaLineage.media_id.in_(successful_media_ids)))
            await session.execute(delete(MediaItem).where(MediaItem.id.in_(successful_media_ids)))
            # Mark operation items as done
            await session.execute(
                update(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id == operation.id,
                    DeleteOperationItem.media_id.in_(successful_media_ids),
                )
                .values(state="done", lease_expires_at=None, updated_at=_utcnow())
            )
            # Update operation counters
            op = await session.get(DeleteOperation, operation.id)
            if op:
                op.processed_items += len(successful_media_ids)
                op.deleted_items += len(successful_media_ids)
                op.updated_at = _utcnow()
            await session.commit()
        completed_ids.extend(successful_media_ids)

    # Mark failed items
    if failed_ids:
        async with db.async_session_maker() as session:
            await session.execute(
                update(DeleteOperationItem)
                .where(
                    DeleteOperationItem.operation_id == operation.id,
                    DeleteOperationItem.media_id.in_(failed_ids),
                )
                .values(state="failed", lease_expires_at=None, updated_at=_utcnow())
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
        if obj.get("media_id") in deleted_set:
            obj.clear()
            obj["deleted"] = True
            return True
        ids = obj.get("media_ids")
        if isinstance(ids, list):
            filtered = [i for i in ids if not (isinstance(i, int) and i in deleted_set)]
            if filtered != ids:
                obj["media_ids"] = filtered
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
                        "media_id": entry["media_id"],
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
                        "media_id": inp["media_id"],
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
            meta["inspired_by"] = {"media_id": inspired["media_id"], "deleted": True}
            changed = True

        if changed:
            item.generation_metadata = json.dumps(meta)

    if descendant_ids:
        log.info("DELETE OPS: tombstoned lineage in %d descendants", len(descendant_ids))


async def get_delete_operation(session, operation_id: int) -> DeleteOperation | None:
    return await session.get(DeleteOperation, operation_id)


async def get_active_delete_operation(session, profile_id: str) -> DeleteOperation | None:
    result = await session.execute(
        select(DeleteOperation)
        .where(DeleteOperation.profile_id == profile_id, DeleteOperation.status.in_(["queued", "running"]))
        .order_by(DeleteOperation.id.desc())
    )
    return result.scalars().first()

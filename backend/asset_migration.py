"""Deterministic rehearsal and cutover for the legacy Media library.

Classification is read-only and explainable. Applying a matching report
materializes Asset roots transactionally and records the durable cutover state.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import (
    Asset,
    AssetMigrationMap,
    AssetMigrationState,
    AssetRevision,
    BoardItem,
    ChatItem,
    DeleteOperation,
    DeleteOperationItem,
    MediaItem,
    MediaMarker,
    MediaOwner,
    MediaTag,
    ProjectMedia,
)


log = get_logger(__name__)


_MIGRATION_PHASES = (
    "expanded",
    "shadow",
    "dual_write",
    "asset_reads",
    "object_store",
    "contracted",
)

_MIGRATION_MAP_BATCH_SIZE = 1_000


async def _bulk_insert_migration_maps(
    session: AsyncSession,
    *,
    rows: list[dict[str, Any]],
    profile_id: str | None = None,
) -> None:
    """Insert migration audit rows without an ORM flush per row.

    SQLAlchemy's normal ORM unit of work emits one INSERT/RETURNING statement
    for each added object on SQLite. Large profiles can therefore spend minutes
    in an otherwise invisible final flush. Core executemany batches preserve the
    surrounding transaction while avoiding that pathological write pattern.
    """
    started = time.monotonic()
    total = len(rows)
    if profile_id:
        log.info(
            "asset media backfill mapping started",
            profile=profile_id,
            total=total,
        )

    statement = AssetMigrationMap.__table__.insert()
    for offset in range(0, total, _MIGRATION_MAP_BATCH_SIZE):
        batch = rows[offset : offset + _MIGRATION_MAP_BATCH_SIZE]
        await session.execute(statement, batch)
        completed = offset + len(batch)
        if profile_id:
            log.info(
                "asset media backfill mapping progress",
                profile=profile_id,
                completed=completed,
                total=total,
                percent=round(completed * 100 / max(total, 1), 1),
                elapsed_seconds=round(time.monotonic() - started, 1),
            )

    if profile_id:
        log.info(
            "asset media backfill mapping completed",
            profile=profile_id,
            completed=total,
            elapsed_seconds=round(time.monotonic() - started, 1),
        )


async def _supersede_assetized_delete_operations(
    session: AsyncSession,
    *,
    assetized_media_ids: set[int],
    profile_id: str | None = None,
) -> int:
    """Retire failed legacy deletions whose Media became Asset roots.

    Scan the normally tiny set of failed deletion items and filter it against
    the in-memory migration set. Expanding every migrated Media ID into a SQL
    ``IN`` clause exceeds the packaged SQLite variable limit on large profiles,
    even though development SQLite permits a much higher limit.
    """
    started = time.monotonic()
    if profile_id:
        log.info(
            "asset media backfill deletion reconciliation started",
            profile=profile_id,
        )

    rows = await session.execute(
        select(DeleteOperation, DeleteOperationItem.media_id)
        .join(
            DeleteOperationItem,
            DeleteOperationItem.operation_id == DeleteOperation.id,
        )
        .where(DeleteOperation.status == "failed")
    )
    matched_operations: dict[int, DeleteOperation] = {}
    scanned_items = 0
    for operation, media_id in rows:
        scanned_items += 1
        if media_id in assetized_media_ids:
            matched_operations[operation.id] = operation

    for operation in matched_operations.values():
        operation.status = "superseded"
        operation.current_phase = "assetized"
        operation.last_error = (
            "Historical deletion was replaced by Asset trash state"
        )
        operation.updated_at = datetime.utcnow()

    if profile_id:
        log.info(
            "asset media backfill deletion reconciliation completed",
            profile=profile_id,
            scanned_items=scanned_items,
            superseded=len(matched_operations),
            elapsed_seconds=round(time.monotonic() - started, 1),
        )
    return len(matched_operations)


def _phase_at_least(phase: str, minimum: str) -> bool:
    try:
        return _MIGRATION_PHASES.index(phase) >= _MIGRATION_PHASES.index(minimum)
    except ValueError:
        return False


def _normalized_path(path: str, *, relative_to: str | None = None) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() and relative_to:
        candidate = Path(relative_to).parent / candidate
    return os.path.normcase(os.path.abspath(os.path.normpath(str(candidate))))


def _structured_member_paths(container: MediaItem) -> set[str]:
    if container.file_format not in {"stimmaset.json", "stimmagrid.json"}:
        return set()
    try:
        payload = json.loads(container.raw_metadata or "{}")
    except (json.JSONDecodeError, TypeError):
        return set()
    records = payload.get("items") if container.file_format == "stimmaset.json" else payload.get("cells")
    if not isinstance(records, list):
        return set()
    paths: set[str] = set()
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            paths.add(_normalized_path(record["path"], relative_to=container.file_path))
    return paths


async def classify_legacy_media(
    session: AsyncSession,
    *,
    check_files: bool = False,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic migration rehearsal report without writing data."""
    started = time.monotonic()
    if profile_id:
        log.info("asset media backfill classification started", profile=profile_id)
    media_items = list(await session.scalars(select(MediaItem).order_by(MediaItem.id)))
    existing_revisions = {
        revision.primary_media_id: revision
        for revision in await session.scalars(select(AssetRevision))
    }
    context_owned_ids = set(
        await session.scalars(
            select(MediaOwner.media_id).where(
                MediaOwner.deleted_at.is_(None),
                MediaOwner.root_kind != "asset_revision",
            )
        )
    )
    pending_delete_ids = set(
        await session.scalars(
            select(DeleteOperationItem.media_id)
            .join(
                DeleteOperation,
                DeleteOperation.id == DeleteOperationItem.operation_id,
            )
            .where(
                DeleteOperation.status.in_({"queued", "running"}),
                DeleteOperationItem.state.not_in({"done", "failed"}),
            )
        )
    )

    curated_ids: set[int] = set(
        await session.scalars(
            select(MediaMarker.media_id).where(MediaMarker.source != "suppressed")
        )
    )
    curated_ids.update(await session.scalars(select(MediaTag.media_id)))
    curated_ids.update(await session.scalars(select(ProjectMedia.media_id)))
    curated_ids.update(await session.scalars(select(BoardItem.media_id)))

    chat_ids: set[int] = set(
        await session.scalars(select(ChatItem.media_id).where(ChatItem.media_id.is_not(None)))
    )
    chat_ids.update(item.id for item in media_items if item.chat_item_id is not None)

    container_paths: dict[int, set[str]] = {
        item.id: _structured_member_paths(item)
        for item in media_items
        if item.file_format in {"stimmaset.json", "stimmagrid.json"}
    }
    path_to_media: dict[str, list[int]] = defaultdict(list)
    for item in media_items:
        path_to_media[_normalized_path(item.file_path)].append(item.id)

    structured_memberships: dict[int, set[int]] = defaultdict(set)
    for container_id, member_paths in container_paths.items():
        for member_path in member_paths:
            for media_id in path_to_media.get(member_path, []):
                structured_memberships[media_id].add(container_id)

    records: list[dict[str, Any]] = []
    conflict_count = 0
    missing_count = 0
    for item in media_items:
        evidence: list[str] = []
        conflicts: list[str] = []
        structured_containers = structured_memberships.get(item.id, set())

        if item.file_format in {"stimmaset.json", "stimmagrid.json"}:
            try:
                manifest_records = _container_records(item)
            except ValueError as exc:
                conflicts.append(str(exc))
            else:
                for index, record in enumerate(manifest_records):
                    if not isinstance(record, dict) or not isinstance(
                        record.get("path"), str
                    ):
                        conflicts.append(f"invalid_member:{index}")
                        continue
                    member_path = _normalized_path(
                        record["path"], relative_to=item.file_path
                    )
                    matches = path_to_media.get(member_path, [])
                    if not matches:
                        conflicts.append(f"missing_member_path:{index}")
                    elif len(matches) > 1:
                        conflicts.append(f"duplicate_member_path:{index}")

        if item.id in pending_delete_ids:
            classification = "pending_deletion"
            evidence.append("durable_delete_operation")
        elif item.id in existing_revisions:
            classification = "existing_asset_revision"
            evidence.append(
                f"existing_asset:{existing_revisions[item.id].asset_id}"
            )
        elif item.deleted_at is not None:
            classification = "trashed"
            evidence.append("legacy_soft_delete")
        elif item.id in curated_ids:
            classification = "asset"
            evidence.append("independent_curation")
        elif item.id in context_owned_ids:
            classification = "context_media"
            evidence.append("existing_context_owner")
        elif item.id in chat_ids:
            # Historical chats cannot reliably distinguish final from intermediate.
            # The conservative migration rule makes ambiguous user-visible results Assets.
            classification = "asset"
            evidence.append("historical_chat_reference")
        elif item.file_format in {"stimmaset.json", "stimmagrid.json"}:
            classification = "asset"
            evidence.append("container_root")
        elif item.ephemeral_run_id:
            classification = "context_media"
            evidence.append("ephemeral_run_owner")
        elif structured_containers:
            classification = "embedded_media"
            evidence.append(f"structured_container:{min(structured_containers)}")
        else:
            classification = "asset"
            evidence.append("ambiguous_defaults_to_asset")

        if classification == "asset" and structured_containers:
            conflicts.append("independent_use_overrides_container_ownership")

        file_missing = check_files and not Path(item.file_path).exists()
        if file_missing:
            missing_count += 1
        if conflicts:
            conflict_count += 1
        records.append(
            {
                "media_id": item.id,
                "classification": classification,
                "evidence": sorted(evidence),
                "conflicts": sorted(set(conflicts)),
                "file_missing": file_missing,
            }
        )

    counts = dict(sorted(Counter(record["classification"] for record in records).items()))
    digest_payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
    report = {
        "migration_version": 1,
        "media_count": len(records),
        "classification_counts": counts,
        "conflict_count": conflict_count,
        "missing_file_count": missing_count,
        "records": records,
        "digest": hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
    }
    if profile_id:
        log.info(
            "asset media backfill classification completed",
            profile=profile_id,
            media=report["media_count"],
            assets=counts.get("asset", 0) + counts.get("trashed", 0),
            embedded=counts.get("embedded_media", 0),
            context=counts.get("context_media", 0),
            elapsed_seconds=round(time.monotonic() - started, 1),
        )
    return report


async def _materialize_migrated_asset(
    session: AsyncSession,
    *,
    media: MediaItem,
    trashed: bool,
    check_existing: bool = True,
) -> Asset:
    if check_existing:
        existing_revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == media.id)
        )
        if existing_revision is not None:
            return await session.get(Asset, existing_revision.asset_id)

    from asset_service import acquire_media_owner, infer_asset_type

    now = media.indexed_date
    asset = Asset(
        asset_type=infer_asset_type(media),
        state="trashed" if trashed else "active",
        expires_at=media.auto_delete_at,
        origin_type="legacy_migration",
        origin_id=str(media.id),
        created_at=now,
        updated_at=now,
        deleted_at=media.deleted_at if trashed else None,
    )
    session.add(asset)
    await session.flush()
    revision = AssetRevision(
        asset_id=asset.id,
        primary_media_id=media.id,
        revision_number=1,
        created_at=now,
    )
    session.add(revision)
    await session.flush()
    asset.current_revision_id = revision.id
    await acquire_media_owner(
        session,
        media_id=media.id,
        root_kind="asset_revision",
        root_id=revision.id,
        role="primary",
        idempotency_key=f"legacy-media:{media.id}:asset",
        allow_deleted=trashed,
    )
    if trashed:
        # Asset now owns lifecycle. Keeping the payload soft-deleted would make
        # the migrated Trash item invisible and impossible to restore.
        media.deleted_at = None
    return asset


def _container_records(container: MediaItem) -> list[Any]:
    try:
        payload = json.loads(container.raw_metadata or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid_container_json") from exc
    key = "items" if container.file_format == "stimmaset.json" else "cells"
    records = payload.get(key)
    if not isinstance(records, list):
        raise ValueError(f"missing_{key}")
    return records


async def _migration_container_specs(
    session: AsyncSession,
    *,
    container: MediaItem,
    assets_by_media: dict[int, Asset],
    records_by_media: dict[int, dict[str, Any]],
    media_by_path: dict[str, list[MediaItem]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Preserve every legacy manifest slot without guessing duplicate paths."""
    records = _container_records(container)

    specs: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for index, record in enumerate(records):
        base: dict[str, Any] = {}
        if isinstance(record, dict):
            if container.file_format == "stimmagrid.json":
                base["row_index"] = record.get("row", index)
                base["column_index"] = record.get("col", 0)
            base["title"] = record.get("title")
            base["caption"] = record.get("caption")
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            conflicts.append(f"invalid_member:{index}")
            specs.append({**base, "missing_linked_asset": True})
            continue

        normalized = _normalized_path(
            record["path"], relative_to=container.file_path
        )
        candidates = media_by_path.get(normalized, [])
        if not candidates:
            conflicts.append(f"missing_member_path:{index}")
            specs.append({**base, "missing_linked_asset": True})
            continue
        if len(candidates) != 1:
            conflicts.append(f"duplicate_member_path:{index}")
            specs.append({**base, "missing_linked_asset": True})
            continue

        member_media = candidates[0]
        if records_by_media[member_media.id]["classification"] == "pending_deletion":
            conflicts.append(f"member_pending_deletion:{index}")
            specs.append({**base, "missing_linked_asset": True})
            continue
        member_asset = assets_by_media.get(member_media.id)
        if (
            member_asset is not None
            and member_asset.state == "active"
            and member_asset.deleted_at is None
        ):
            specs.append({**base, "linked_asset_id": member_asset.id})
        else:
            specs.append({**base, "embedded_media_id": member_media.id})
    return specs, conflicts


async def apply_asset_backfill(
    session: AsyncSession,
    *,
    approved_digest: str,
    report: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Apply a rehearsed classifier result transactionally and idempotently.

    The caller must provide the digest from a separately reviewed rehearsal.
    A changed profile fails before any row is written.
    """
    state = await session.scalar(
        select(AssetMigrationState).where(
            AssetMigrationState.migration_key == "asset_media_v1"
        )
    )
    if state is not None and _phase_at_least(state.phase, "dual_write"):
        if state.report_digest != approved_digest:
            raise ValueError("Migration is already applied with a different digest")
        maps = list(
            await session.scalars(
                select(AssetMigrationMap).where(
                    AssetMigrationMap.migration_version == 1,
                    AssetMigrationMap.deleted_at.is_(None),
                )
            )
        )
        return {
            "digest": approved_digest,
            "assets": sum(mapping.asset_id is not None for mapping in maps),
            "records": len(maps),
            "phase": state.phase,
        }

    if report is None:
        report = await classify_legacy_media(session, profile_id=profile_id)
    if report["digest"] != approved_digest:
        raise ValueError("Historical Media changed after rehearsal; generate a new report")

    if state is None:
        if profile_id:
            log.info("asset media backfill acquiring write lock", profile=profile_id)
        state = AssetMigrationState(
            migration_key="asset_media_v1",
            phase="shadow",
            migration_version=1,
            report_digest=approved_digest,
            started_at=datetime.utcnow(),
        )
        session.add(state)
        await session.flush()
        if profile_id:
            log.info("asset media backfill write lock acquired", profile=profile_id)
    elif state.report_digest and state.report_digest != approved_digest:
        raise ValueError("Migration state belongs to a different rehearsal digest")
    else:
        state.deleted_at = None

    assets_by_media: dict[int, Asset] = {}
    records_by_media = {record["media_id"]: record for record in report["records"]}
    media_items = list(await session.scalars(select(MediaItem).order_by(MediaItem.id)))
    media_by_id = {media.id: media for media in media_items}
    association_media_ids = set(
        await session.scalars(
            select(MediaMarker.media_id).where(MediaMarker.source != "suppressed")
        )
    )
    association_media_ids.update(await session.scalars(select(MediaTag.media_id)))
    association_media_ids.update(await session.scalars(select(ProjectMedia.media_id)))
    association_media_ids.update(await session.scalars(select(BoardItem.media_id)))
    total_media = len(media_items)
    phase_started = time.monotonic()
    last_progress = phase_started
    if profile_id:
        log.info(
            "asset media backfill materialization started",
            profile=profile_id,
            total=total_media,
        )
    for index, media in enumerate(media_items, start=1):
        record = records_by_media[media.id]
        classification = record["classification"]
        if classification in {"asset", "trashed"}:
            asset = await _materialize_migrated_asset(
                session,
                media=media,
                trashed=classification == "trashed",
                check_existing=False,
            )
            assets_by_media[media.id] = asset
            if media.id in association_media_ids:
                from asset_association_service import mirror_media_associations_to_asset
                await mirror_media_associations_to_asset(
                    session, media_id=media.id, asset_id=asset.id
                )
        elif classification == "existing_asset_revision":
            revision = await session.scalar(
                select(AssetRevision).where(
                    AssetRevision.primary_media_id == media.id
                )
            )
            if revision is not None:
                asset = await session.get(Asset, revision.asset_id)
                if asset is not None:
                    assets_by_media[media.id] = asset
                    if media.id in association_media_ids:
                        from asset_association_service import mirror_media_associations_to_asset
                        await mirror_media_associations_to_asset(
                            session, media_id=media.id, asset_id=asset.id
                        )
        elif (
            classification == "context_media"
            and media.ephemeral_run_id
        ):
            from asset_service import acquire_media_owner
            await acquire_media_owner(
                session,
                media_id=media.id,
                root_kind="ephemeral_run",
                root_id=media.ephemeral_run_id,
                role="intermediate",
                idempotency_key=f"legacy-ephemeral:{media.id}",
            )

        now = time.monotonic()
        if profile_id and now - last_progress >= 5:
            log.info(
                "asset media backfill materialization progress",
                profile=profile_id,
                completed=index,
                total=total_media,
                percent=round(index * 100 / max(total_media, 1), 1),
                assets=len(assets_by_media),
                elapsed_seconds=round(now - phase_started, 1),
            )
            last_progress = now

    if profile_id:
        log.info(
            "asset media backfill materialization completed",
            profile=profile_id,
            completed=total_media,
            assets=len(assets_by_media),
            elapsed_seconds=round(time.monotonic() - phase_started, 1),
        )

    # A pre-upgrade failed Media deletion is no longer retryable after its
    # trashed Media has become an Asset root. Preserve the audit record but
    # retire the obsolete operation; the user can permanently delete the new
    # Asset identity through the Asset trash workflow.
    if assets_by_media:
        await _supersede_assetized_delete_operations(
            session,
            assetized_media_ids=set(assets_by_media),
            profile_id=profile_id,
        )

    # Populate container structure only after every independent member has its
    # Asset, so the resolver can choose linked versus embedded deterministically.
    from container_service import populate_container_revision_members
    media_by_path: dict[str, list[MediaItem]] = defaultdict(list)
    for media in media_items:
        media_by_path[_normalized_path(media.file_path)].append(media)
    container_assets = [
        (media_id, asset)
        for media_id, asset in assets_by_media.items()
        if media_by_id[media_id].file_format in {"stimmaset.json", "stimmagrid.json"}
        and records_by_media[media_id]["classification"] != "existing_asset_revision"
    ]
    container_started = time.monotonic()
    if profile_id:
        log.info(
            "asset media backfill container normalization started",
            profile=profile_id,
            total=len(container_assets),
        )
    for container_index, (media_id, asset) in enumerate(container_assets, start=1):
        media = media_by_id[media_id]
        try:
            specs, membership_conflicts = await _migration_container_specs(
                session,
                container=media,
                assets_by_media=assets_by_media,
                records_by_media=records_by_media,
                media_by_path=media_by_path,
            )
        except ValueError as exc:
            records_by_media[media_id]["conflicts"].append(str(exc))
            continue
        records_by_media[media_id]["conflicts"].extend(membership_conflicts)
        records_by_media[media_id]["conflicts"] = sorted(
            set(records_by_media[media_id]["conflicts"])
        )
        await populate_container_revision_members(
            session,
            container_asset_id=asset.id,
            revision_id=asset.current_revision_id,
            members=specs,
        )
        if profile_id:
            log.info(
                "asset media backfill container normalization progress",
                profile=profile_id,
                completed=container_index,
                total=len(container_assets),
            )

    if profile_id:
        log.info(
            "asset media backfill container normalization completed",
            profile=profile_id,
            completed=len(container_assets),
            elapsed_seconds=round(time.monotonic() - container_started, 1),
        )

    existing_mapped_ids = set(
        await session.scalars(
            select(AssetMigrationMap.legacy_media_id).where(
                AssetMigrationMap.migration_version == 1,
                AssetMigrationMap.deleted_at.is_(None),
            )
        )
    )
    total_records = len(report["records"])
    mapping_rows: list[dict[str, Any]] = []
    for record in report["records"]:
        if record["media_id"] not in existing_mapped_ids:
            asset = assets_by_media.get(record["media_id"])
            mapping_rows.append({
                "legacy_media_id": record["media_id"],
                "asset_id": asset.id if asset else None,
                "classification": record["classification"],
                "reason": ",".join(record["evidence"]),
                "evidence": json.dumps({
                    "conflicts": record["conflicts"],
                    "file_missing": record["file_missing"],
                }, sort_keys=True),
                "migration_version": 1,
                "status": "applied",
            })
    await _bulk_insert_migration_maps(
        session,
        rows=mapping_rows,
        profile_id=profile_id,
    )

    state.phase = "contracted"
    state.report_digest = approved_digest
    state.completed_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    if profile_id:
        log.info("asset media backfill finalizing transaction", profile=profile_id)
    await session.flush()
    if profile_id:
        log.info(
            "asset media backfill transaction ready to commit",
            profile=profile_id,
            assets=len(assets_by_media),
            records=total_records,
        )
    return {
        "digest": approved_digest,
        "assets": len(assets_by_media),
        "records": len(report["records"]),
        "phase": state.phase,
    }


async def ensure_asset_backfill(
    session: AsyncSession,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Complete the one-time conservative backfill before Asset reads start.

    Classification and materialization run automatically in one transaction.
    Ambiguous historical rows become Assets, so startup never hides previously
    user-visible content while waiting for human migration work.
    """
    if profile_id:
        log.info("asset media backfill checking", profile=profile_id)
    state = await session.scalar(
        select(AssetMigrationState).where(
            AssetMigrationState.migration_key == "asset_media_v1",
        )
    )
    if state is not None and state.phase == "contracted":
        if profile_id:
            log.info("asset media backfill already complete", profile=profile_id)
        return {
            "digest": state.report_digest,
            "assets": 0,
            "records": 0,
            "phase": state.phase,
            "already_complete": True,
        }
    if state is not None and _phase_at_least(state.phase, "dual_write"):
        state.phase = "contracted"
        state.updated_at = datetime.utcnow()
        await session.commit()
        if profile_id:
            log.info("asset media backfill finalized existing cutover", profile=profile_id)
        return {
            "digest": state.report_digest,
            "assets": 0,
            "records": 0,
            "phase": state.phase,
            "already_complete": True,
        }
    report = await classify_legacy_media(session, profile_id=profile_id)
    result = await apply_asset_backfill(
        session,
        approved_digest=report["digest"],
        report=report,
        profile_id=profile_id,
    )
    await session.commit()
    if profile_id:
        log.info(
            "asset media backfill committed",
            profile=profile_id,
            assets=result["assets"],
            records=result["records"],
        )
    return {**result, "already_complete": False}

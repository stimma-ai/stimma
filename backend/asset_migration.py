"""Deterministic rehearsal and cutover for the legacy Media library.

Classification is read-only and explainable. Applying a matching report
materializes Asset roots transactionally and records the durable cutover state.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


_MIGRATION_PHASES = (
    "expanded",
    "shadow",
    "dual_write",
    "asset_reads",
    "object_store",
    "contracted",
)


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
) -> dict[str, Any]:
    """Return a deterministic migration rehearsal report without writing data."""
    media_items = list(await session.scalars(select(MediaItem).order_by(MediaItem.id)))
    by_id = {item.id: item for item in media_items}
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
        superseding = by_id.get(item.superseded_by) if item.superseded_by else None
        proven_container_ids = (
            {item.superseded_by}
            if item.superseded_by is not None and item.superseded_by in structured_containers
            else set()
        )

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
        elif proven_container_ids:
            classification = "embedded_media"
            evidence.append(f"structured_container:{min(proven_container_ids)}")
            evidence.append(f"legacy_superseded_by:{item.superseded_by}")
        else:
            classification = "asset"
            evidence.append("ambiguous_defaults_to_asset")

        if item.superseded_by is not None:
            if superseding is None:
                conflicts.append("dangling_superseded_by")
            elif superseding.file_format not in {"stimmaset.json", "stimmagrid.json"}:
                conflicts.append("superseded_by_non_container")
            elif item.superseded_by not in structured_containers:
                conflicts.append("container_manifest_disagrees_with_superseded_by")
        if structured_containers and item.superseded_by not in structured_containers:
            conflicts.append("structured_membership_without_matching_superseded_by")
        if classification == "asset" and proven_container_ids:
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
    return {
        "migration_version": 1,
        "media_count": len(records),
        "classification_counts": counts,
        "conflict_count": conflict_count,
        "missing_file_count": missing_count,
        "records": records,
        "digest": hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
    }


async def _materialize_migrated_asset(
    session: AsyncSession,
    *,
    media: MediaItem,
    trashed: bool,
) -> Asset:
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
    media_items: list[MediaItem],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Preserve every legacy manifest slot without guessing duplicate paths."""
    records = _container_records(container)
    by_path: dict[str, list[MediaItem]] = defaultdict(list)
    for media in media_items:
        by_path[_normalized_path(media.file_path)].append(media)

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
        candidates = by_path.get(normalized, [])
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
) -> dict[str, Any]:
    """Apply a rehearsed classifier result transactionally and idempotently.

    The caller must provide the digest from a separately reviewed rehearsal.
    A changed profile fails before any row is written.
    """
    from datetime import datetime

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

    report = await classify_legacy_media(session)
    if report["digest"] != approved_digest:
        raise ValueError("Historical Media changed after rehearsal; generate a new report")

    if state is None:
        state = AssetMigrationState(
            migration_key="asset_media_v1",
            phase="shadow",
            migration_version=1,
            report_digest=approved_digest,
            started_at=datetime.utcnow(),
        )
        session.add(state)
        await session.flush()
    elif state.report_digest and state.report_digest != approved_digest:
        raise ValueError("Migration state belongs to a different rehearsal digest")
    else:
        state.deleted_at = None

    assets_by_media: dict[int, Asset] = {}
    records_by_media = {record["media_id"]: record for record in report["records"]}
    media_items = list(await session.scalars(select(MediaItem).order_by(MediaItem.id)))
    for media in media_items:
        record = records_by_media[media.id]
        classification = record["classification"]
        if classification in {"asset", "trashed"}:
            asset = await _materialize_migrated_asset(
                session,
                media=media,
                trashed=classification == "trashed",
            )
            assets_by_media[media.id] = asset
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

    # Populate container structure only after every independent member has its
    # Asset, so the resolver can choose linked versus embedded deterministically.
    from container_service import populate_container_revision_members
    for media_id, asset in assets_by_media.items():
        media = next(item for item in media_items if item.id == media_id)
        if media.file_format not in {"stimmaset.json", "stimmagrid.json"}:
            continue
        if records_by_media[media_id]["classification"] == "existing_asset_revision":
            continue
        try:
            specs, membership_conflicts = await _migration_container_specs(
                session,
                container=media,
                assets_by_media=assets_by_media,
                records_by_media=records_by_media,
                media_items=media_items,
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

    for record in report["records"]:
        existing_map = await session.scalar(
            select(AssetMigrationMap).where(
                AssetMigrationMap.legacy_media_id == record["media_id"],
                AssetMigrationMap.migration_version == 1,
                AssetMigrationMap.deleted_at.is_(None),
            )
        )
        if existing_map is not None:
            continue
        asset = assets_by_media.get(record["media_id"])
        session.add(AssetMigrationMap(
            legacy_media_id=record["media_id"],
            asset_id=asset.id if asset else None,
            classification=record["classification"],
            reason=",".join(record["evidence"]),
            evidence=json.dumps({
                "conflicts": record["conflicts"],
                "file_missing": record["file_missing"],
            }, sort_keys=True),
            migration_version=1,
            status="applied",
        ))

    state.phase = "dual_write"
    state.report_digest = approved_digest
    state.completed_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    await session.flush()
    return {
        "digest": approved_digest,
        "assets": len(assets_by_media),
        "records": len(report["records"]),
        "phase": state.phase,
    }


async def ensure_asset_backfill(session: AsyncSession) -> dict[str, Any]:
    """Complete the one-time conservative backfill before Asset reads start.

    The rehearsal and apply run in the same database transaction, so the
    digest gate still detects any accidental classifier drift while startup
    is preparing the profile. Once the durable migration state is complete,
    later startups are a constant-time no-op.
    """
    state = await session.scalar(
        select(AssetMigrationState).where(
            AssetMigrationState.migration_key == "asset_media_v1",
        )
    )
    if state is not None and _phase_at_least(state.phase, "dual_write"):
        return {
            "digest": state.report_digest,
            "assets": 0,
            "records": 0,
            "phase": state.phase,
            "already_complete": True,
        }
    report = await classify_legacy_media(session)
    result = await apply_asset_backfill(
        session,
        approved_digest=report["digest"],
    )
    await session.commit()
    return {**result, "already_complete": False}

"""Read-only rehearsal classifier for the legacy Media library.

This module deliberately does not create Assets.  It produces deterministic,
explainable decisions which can be reviewed before any profile is backfilled.
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
    MediaItem,
    MediaMarker,
    MediaOwner,
    MediaTag,
    ProjectMedia,
)


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

        if item.deleted_at is not None:
            classification = "trashed"
            evidence.append("legacy_soft_delete")
        elif item.id in curated_ids:
            classification = "asset"
            evidence.append("independent_curation")
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
    return asset


async def apply_asset_backfill(
    session: AsyncSession,
    *,
    approved_digest: str,
) -> dict[str, Any]:
    """Apply a rehearsed classifier result transactionally and idempotently.

    The caller must provide the digest from a separately reviewed rehearsal.
    A changed profile fails before any row is written.
    """
    report = await classify_legacy_media(session)
    if report["digest"] != approved_digest:
        raise ValueError("Historical Media changed after rehearsal; generate a new report")

    from datetime import datetime

    state = await session.scalar(
        select(AssetMigrationState).where(
            AssetMigrationState.migration_key == "asset_media_v1"
        )
    )
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
        elif classification == "context_media" and media.ephemeral_run_id:
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
    from container_service import infer_structured_member_specs, populate_container_revision_members
    for media_id, asset in assets_by_media.items():
        media = next(item for item in media_items if item.id == media_id)
        if media.file_format not in {"stimmaset.json", "stimmagrid.json"}:
            continue
        specs = await infer_structured_member_specs(session, container_media=media)
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

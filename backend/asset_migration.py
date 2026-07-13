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

from database import BoardItem, ChatItem, MediaItem, MediaMarker, MediaTag, ProjectMedia


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

"""Normalize retained Stimma-created Media into managed object storage.

Dry-run is the default.  Applying is deliberately explicit and resumable:
each physical source-path group commits independently, and reruns skip Media
that is already managed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import load_only


INTERNAL_METADATA_SOURCES = frozenset({
    "agent_v2_assemble_grid",
    "agent_v2_assemble_set",
    "agent_v2_create_layout",
    "agent_v2_run_code",
    "batch",
    "flow_create_layout",
    "stimma",
    "stimmer",
    "flow",
})

# These origins create or privately ingest bytes.  Promotion-oriented origins
# are intentionally absent: putting a watched file on a board/tag/project does
# not make Stimma the owner of its payload.
OWNED_ASSET_ORIGINS = frozenset({
    "editor_save_as_new",
    "generation_batch",
    "generation_job",
    "library_save",
    "manual_set",
    "upload",
})


class MigrationUsageError(RuntimeError):
    pass


def _path_key(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _normalized_roots(roots: list[Path] | tuple[Path, ...]) -> list[Path]:
    return list(dict.fromkeys(
        Path(root).expanduser().resolve(strict=False) for root in roots
    ))


def _under_any_root(path_key: str, roots: list[Path]) -> bool:
    path = Path(path_key)
    return any(path == root or root in path.parents for root in roots)


def _internal_metadata_source(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    return source if source in INTERNAL_METADATA_SOURCES else None


async def inspect_profile(
    session,
    *,
    profile_id: str,
    source_roots: list[Path] | tuple[Path, ...] = (),
    legacy_generated_roots: list[Path] | tuple[Path, ...] = (),
    legacy_upload_roots: list[Path] | tuple[Path, ...] = (),
    remove_untracked_legacy_files: bool = False,
) -> dict[str, Any]:
    """Build a hash-verified, explainable normalization plan."""
    from database import (
        Asset,
        AssetRevision,
        AssetSnapshot,
        ContainerMember,
        GenerationJob,
        MediaItem,
        MediaLineage,
        MediaOwner,
        StorageObject,
    )
    from storage_service import _hash_payload

    source_roots = _normalized_roots(source_roots)
    legacy_generated_roots = _normalized_roots(legacy_generated_roots)
    legacy_upload_roots = _normalized_roots(legacy_upload_roots)

    # Some long-lived libraries contain malformed values in unrelated legacy
    # columns (for example, an empty string in a nullable DateTime). Loading a
    # complete MediaItem would make a storage-only audit fail while SQLAlchemy
    # converts those fields. Keep this repair path deliberately narrow.
    rows = list((await session.execute(
        select(MediaItem, StorageObject)
        .outerjoin(StorageObject, StorageObject.id == MediaItem.storage_object_id)
        .options(
            load_only(
                MediaItem.id,
                MediaItem.file_path,
                MediaItem.file_hash,
                MediaItem.file_size,
                MediaItem.original_filename,
                MediaItem.storage_object_id,
                MediaItem.tool_id,
                MediaItem.chat_item_id,
                MediaItem.ephemeral_run_id,
                MediaItem.generation_metadata,
                MediaItem.has_editor_sidecar,
            ),
            load_only(
                StorageObject.id,
                StorageObject.kind,
                StorageObject.external_path,
            ),
        )
        .where(
            MediaItem.deleted_at.is_(None),
            MediaItem.deletion_pending_at.is_(None),
        )
        .order_by(MediaItem.id)
    )).all())

    job_ids = set(await session.scalars(
        select(GenerationJob.result_media_id).where(
            GenerationJob.result_media_id.is_not(None)
        )
    ))
    lineage_ids = set(await session.scalars(
        select(MediaLineage.media_id).distinct()
    ))
    upload_owner_ids = set(await session.scalars(
        select(MediaOwner.media_id).where(
            MediaOwner.root_kind == "upload",
            MediaOwner.deleted_at.is_(None),
        )
    ))
    retained_by: dict[int, set[str]] = defaultdict(set)
    retention_queries = (
        (
            "media_owner",
            select(MediaOwner.media_id).where(MediaOwner.deleted_at.is_(None)),
        ),
        (
            "asset_revision",
            select(AssetRevision.primary_media_id).where(
                AssetRevision.deleted_at.is_(None)
            ),
        ),
        (
            "asset_snapshot",
            select(AssetSnapshot.media_id).where(AssetSnapshot.deleted_at.is_(None)),
        ),
        (
            "container_member",
            select(ContainerMember.embedded_media_id).where(
                ContainerMember.deleted_at.is_(None)
            ),
        ),
    )
    for root_kind, query in retention_queries:
        for media_id in set(await session.scalars(query)):
            retained_by[media_id].add(root_kind)
    owned_origin_rows = list((await session.execute(
        select(AssetRevision.primary_media_id, Asset.origin_type)
        .join(Asset, Asset.id == AssetRevision.asset_id)
        .where(
            AssetRevision.deleted_at.is_(None),
            Asset.origin_type.in_(OWNED_ASSET_ORIGINS),
        )
    )).all())
    owned_origins: dict[int, set[str]] = defaultdict(set)
    for media_id, origin in owned_origin_rows:
        owned_origins[media_id].add(origin)

    records: list[dict[str, Any]] = []
    members_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for media, storage in rows:
        storage_kind = storage.kind if storage is not None else "legacy"
        locator = (
            storage.external_path
            if storage is not None and storage.kind == "external"
            else media.file_path
        )
        locator = locator or media.file_path
        reasons: list[str] = []
        if media.tool_id:
            reasons.append("tool_provenance")
        if media.chat_item_id is not None:
            reasons.append("chat_provenance")
        if media.id in job_ids:
            reasons.append("generation_job_result")
        if media.id in lineage_ids:
            reasons.append("lineage_output")
        if media.id in upload_owner_ids:
            reasons.append("upload_owner")
        reasons.extend(
            f"asset_origin:{origin}" for origin in sorted(owned_origins.get(media.id, set()))
        )
        internal_source = _internal_metadata_source(media.generation_metadata)

        retention_roots = sorted(retained_by.get(media.id, set()))
        path_key = _path_key(locator)
        in_source_root = _under_any_root(path_key, source_roots)
        in_legacy_generated_root = _under_any_root(
            path_key, legacy_generated_roots
        )
        in_legacy_upload_root = _under_any_root(path_key, legacy_upload_roots)
        if in_legacy_upload_root:
            reasons.append("explicit_legacy_upload_root")
        elif in_legacy_generated_root:
            reasons.append("explicit_legacy_generated_root")

        if media.ephemeral_run_id:
            status = "ephemeral"
        elif storage_kind == "managed":
            status = "already_managed"
        elif in_legacy_upload_root and retention_roots:
            # Historical uploads were copied into a Stimma-owned directory.
            # Their provenance may correctly say imported; the explicit root
            # declaration is the ownership proof.
            status = "candidate"
        elif in_legacy_generated_root and retention_roots:
            status = "candidate"
        elif reasons and retention_roots:
            status = "candidate"
        elif (in_legacy_upload_root or in_legacy_generated_root) and not retention_roots:
            status = "unretained_legacy_owned"
        elif storage_kind == "external":
            status = "external_source"
        elif (
            storage_kind == "legacy"
            and media.storage_object_id is None
            and retention_roots
            and in_source_root
        ):
            status = "external_registration_candidate"
        elif reasons:
            status = "unretained_stimma_created"
        elif internal_source:
            # Embedded Stimma metadata can arrive through a watched import from
            # another installation.  It is evidence, but not ownership proof.
            status = "ambiguous_internal_metadata"
        else:
            status = "external_source"

        record = {
            "media_id": media.id,
            "path": locator,
            "path_key": path_key,
            "expected_hash": media.file_hash,
            "storage_kind": storage_kind,
            "status": status,
            "reasons": reasons,
            "retention_roots": retention_roots,
            "internal_metadata_source": internal_source,
            "has_editor_sidecar": bool(media.has_editor_sidecar),
            "in_source_root": in_source_root,
            "in_legacy_generated_root": in_legacy_generated_root,
            "in_legacy_upload_root": in_legacy_upload_root,
            "remove_source": False,
        }
        if storage is None and media.storage_object_id is not None:
            record["status"] = "blocked_dangling_storage"
        if (
            storage is not None
            and storage.kind == "external"
            and _path_key(media.file_path) != _path_key(storage.external_path)
        ):
            record["status"] = "blocked_locator_mismatch"
        records.append(record)
        if storage_kind != "managed":
            members_by_path[record["path_key"]].append(record)

    candidates_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["status"] == "candidate":
            candidates_by_path[record["path_key"]].append(record)

    for path_key, candidates in candidates_by_path.items():
        source = Path(path_key)
        if not source.is_file() and not source.is_dir():
            for record in candidates:
                record["status"] = "blocked_missing"
            continue
        flagged_sidecar_missing = any(
            record["has_editor_sidecar"]
            and not Path(f"{source}.stimmaedit.json").is_file()
            for record in candidates
        )
        if flagged_sidecar_missing:
            for record in candidates:
                record["status"] = "blocked_editor_sidecar_missing"
            continue
        actual_hash = await asyncio.to_thread(_hash_payload, source)
        for record in candidates:
            record["actual_hash"] = actual_hash
        if any(record["expected_hash"] != actual_hash for record in candidates):
            # Multiple immutable revisions may historically share one mutable
            # path.  Never migrate only the newest bytes and silently strand
            # the other revisions.
            for record in candidates:
                record["status"] = "blocked_hash_mismatch"
            continue
        noncandidate_members = [
            member for member in members_by_path[path_key]
            if member["status"] != "candidate"
        ]
        remove_source = not noncandidate_members
        for record in candidates:
            record["status"] = "eligible"
            record["remove_source"] = remove_source

    counts = Counter(record["status"] for record in records)
    eligible = [record for record in records if record["status"] == "eligible"]
    blocked = [
        record for record in records if record["status"].startswith("blocked_")
    ]
    explicit_root_roles: dict[Path, set[str]] = defaultdict(set)
    for root in legacy_generated_roots:
        explicit_root_roles[root].add("generated")
    for root in legacy_upload_roots:
        explicit_root_roles[root].add("uploads")
    removable_sources = [
        Path(record["path_key"])
        for record in eligible
        if record["remove_source"]
    ]
    remaining_files: set[str] = set()
    root_inventory = []
    records_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_path[record["path_key"]].append(record)
    for root, roles in sorted(explicit_root_roles.items(), key=lambda item: str(item[0])):
        files = sorted(
            candidate for candidate in root.rglob("*")
            if candidate.is_file() or candidate.is_symlink()
        ) if root.is_dir() else []

        def planned_for_removal(candidate: Path) -> bool:
            for source in removable_sources:
                if candidate == source or source in candidate.parents:
                    return True
                if candidate == Path(f"{source}.stimmaedit.json"):
                    return True
            return False

        raw_leftovers = [candidate for candidate in files if not planned_for_removal(candidate)]
        remaining_by_status: Counter[str] = Counter()
        untracked_removals: list[Path] = []
        leftovers: list[Path] = []
        for candidate in raw_leftovers:
            candidate_key = _path_key(str(candidate))
            matching_records = records_by_path.get(candidate_key, [])
            if not matching_records and candidate.name.endswith(".stimmaedit.json"):
                primary_key = candidate_key.removesuffix(".stimmaedit.json")
                matching_records = records_by_path.get(primary_key, [])
            status = (
                "+".join(sorted({record["status"] for record in matching_records}))
                if matching_records
                else "untracked_file"
            )
            if status == "untracked_file" and remove_untracked_legacy_files:
                untracked_removals.append(candidate)
                continue
            leftovers.append(candidate)
            remaining_by_status[status] += 1
        remaining_files.update(str(candidate) for candidate in leftovers)
        root_inventory.append({
            "path": str(root),
            "roles": sorted(roles),
            "exists": root.exists(),
            "file_count": len(files),
            "planned_removal_count": len(files) - len(leftovers),
            "untracked_removal_count": len(untracked_removals),
            "untracked_removal_files": [str(candidate) for candidate in untracked_removals],
            "remaining_file_count": len(leftovers),
            "remaining_by_status": dict(sorted(remaining_by_status.items())),
            "remaining_files": [str(candidate) for candidate in leftovers],
        })

    return {
        "profile_id": profile_id,
        "fully_normalizable": not blocked,
        "counts": dict(sorted(counts.items())),
        "eligible_count": len(eligible),
        "eligible_source_removal_count": sum(
            1 for record in eligible if record["remove_source"]
        ),
        "blocked_count": len(blocked),
        "external_registration_count": counts.get(
            "external_registration_candidate", 0
        ),
        "legacy_upload_eligible_count": sum(
            "explicit_legacy_upload_root" in record["reasons"]
            for record in eligible
        ),
        "legacy_generated_eligible_count": sum(
            "explicit_legacy_generated_root" in record["reasons"]
            for record in eligible
        ),
        "legacy_root_remaining_file_count": len(remaining_files),
        "legacy_root_inventory": root_inventory,
        "records": records,
    }


async def apply_profile(
    session_maker,
    *,
    profile_id: str,
    source_roots: list[Path] | tuple[Path, ...] = (),
    legacy_generated_roots: list[Path] | tuple[Path, ...] = (),
    legacy_upload_roots: list[Path] | tuple[Path, ...] = (),
    remove_untracked_legacy_files: bool = False,
) -> dict[str, Any]:
    """Apply every eligible path group, committing each group independently."""
    from database import ManagedArtifact, MediaItem
    from storage_service import (
        cleanup_staged_source,
        register_external_media,
        stage_managed_media,
    )

    # A crash after the Media transaction commits but before source cleanup is
    # represented by a durable ManagedArtifact. Recover those first so reruns
    # finish the previous attempt instead of skipping its now-managed Media.
    cleanup_retried = 0
    errors: list[dict[str, Any]] = []
    async with session_maker() as session:
        staged_media_ids = list(await session.scalars(
            select(ManagedArtifact.media_id)
            .where(
                ManagedArtifact.artifact_kind == "ingest_source",
                ManagedArtifact.deleted_at.is_(None),
                ManagedArtifact.media_id.is_not(None),
            )
            .distinct()
        ))
    for media_id in staged_media_ids:
        try:
            async with session_maker() as session:
                cleanup_retried += await cleanup_staged_source(
                    session, media_id=media_id
                )
        except Exception as exc:
            errors.append({
                "media_ids": [media_id],
                "phase": "staged_source_cleanup",
                "error": type(exc).__name__,
                "message": str(exc),
            })

    async with session_maker() as session:
        plan = await inspect_profile(
            session,
            profile_id=profile_id,
            source_roots=source_roots,
            legacy_generated_roots=legacy_generated_roots,
            legacy_upload_roots=legacy_upload_roots,
            remove_untracked_legacy_files=remove_untracked_legacy_files,
        )

    eligible_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in plan["records"]:
        if record["status"] == "eligible":
            eligible_by_path[record["path_key"]].append(record)

    migrated = 0
    external_registered = 0
    untracked_removed = 0
    source_groups_removed = 0
    for path_key, records in eligible_by_path.items():
        media_ids = [record["media_id"] for record in records]
        remove_source = all(record["remove_source"] for record in records)
        try:
            async with session_maker() as session:
                media_rows = list(await session.scalars(
                    select(MediaItem)
                    .options(load_only(
                        MediaItem.id,
                        MediaItem.file_path,
                        MediaItem.file_hash,
                        MediaItem.file_size,
                        MediaItem.original_filename,
                        MediaItem.storage_object_id,
                        MediaItem.deletion_pending_at,
                        MediaItem.file_unavailable,
                    ))
                    .where(
                        MediaItem.id.in_(media_ids),
                        MediaItem.deleted_at.is_(None),
                        MediaItem.deletion_pending_at.is_(None),
                    )
                    .order_by(MediaItem.id)
                ))
                if len(media_rows) != len(media_ids):
                    raise RuntimeError("candidate set changed after preflight")
                if any(_path_key(media.file_path) != path_key for media in media_rows):
                    raise RuntimeError("candidate locator changed after preflight")
                for media in media_rows:
                    await stage_managed_media(
                        session,
                        media=media,
                        profile_id=profile_id,
                        remove_source=remove_source,
                    )
                    media.file_unavailable = False
                await session.commit()
            migrated += len(media_ids)
        except Exception as exc:
            errors.append({
                "path": path_key,
                "media_ids": media_ids,
                "phase": "managed_storage_commit",
                "error": type(exc).__name__,
                "message": str(exc),
            })
            continue
        if remove_source:
            group_cleanup_ok = True
            for media_id in media_ids:
                try:
                    async with session_maker() as session:
                        await cleanup_staged_source(session, media_id=media_id)
                except Exception as exc:
                    group_cleanup_ok = False
                    errors.append({
                        "path": path_key,
                        "media_ids": [media_id],
                        "phase": "staged_source_cleanup",
                        "error": type(exc).__name__,
                        "message": str(exc),
                    })
            source_groups_removed += int(group_cleanup_ok)

    for record in plan["records"]:
        if record["status"] != "external_registration_candidate":
            continue
        try:
            async with session_maker() as session:
                media = await session.scalar(
                    select(MediaItem)
                    .options(load_only(
                        MediaItem.id,
                        MediaItem.file_path,
                        MediaItem.file_hash,
                        MediaItem.file_size,
                        MediaItem.original_filename,
                        MediaItem.storage_object_id,
                        MediaItem.deleted_at,
                    ))
                    .where(MediaItem.id == record["media_id"])
                )
                if media is None or media.deleted_at is not None:
                    raise RuntimeError("external Media changed after preflight")
                if media.storage_object_id is not None:
                    raise RuntimeError("external Media acquired storage after preflight")
                await register_external_media(session, media=media)
                await session.commit()
            external_registered += 1
        except Exception as exc:
            errors.append({
                "path": record["path_key"],
                "media_ids": [record["media_id"]],
                "phase": "external_storage_registration",
                "error": type(exc).__name__,
                "message": str(exc),
            })

    untracked_paths = {
        path
        for inventory in plan["legacy_root_inventory"]
        for path in inventory["untracked_removal_files"]
    }
    if untracked_paths:
        from trash_service import TrashService

        trash = TrashService()
        for path in sorted(untracked_paths):
            try:
                await asyncio.to_thread(trash.permanently_delete, path)
                untracked_removed += 1
            except Exception as exc:
                errors.append({
                    "path": path,
                    "media_ids": [],
                    "phase": "untracked_legacy_file_cleanup",
                    "error": type(exc).__name__,
                    "message": str(exc),
                })

    async with session_maker() as session:
        remaining = await inspect_profile(
            session,
            profile_id=profile_id,
            source_roots=source_roots,
            legacy_generated_roots=legacy_generated_roots,
            legacy_upload_roots=legacy_upload_roots,
            remove_untracked_legacy_files=remove_untracked_legacy_files,
        )
    return {
        "profile_id": profile_id,
        "migrated": migrated,
        "external_registered": external_registered,
        "untracked_removed": untracked_removed,
        "source_groups_removed": source_groups_removed,
        "cleanup_retried": cleanup_retried,
        "errors": errors,
        "remaining": remaining,
    }


def _configured_profiles(data_dir: Path, selected_profile: str | None) -> list[dict]:
    config_path = data_dir / "config.yaml"
    if not config_path.is_file():
        raise MigrationUsageError("config.yaml does not exist in the selected sandbox")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise MigrationUsageError(
            f"config.yaml could not be read: {type(exc).__name__}"
        ) from exc
    profiles = [
        profile for profile in (config.get("profiles") or [])
        if isinstance(profile, dict) and profile.get("id")
    ]
    if selected_profile:
        selected = [
            profile for profile in profiles if profile["id"] == selected_profile
        ]
        if not selected:
            raise MigrationUsageError(f"profile not found: {selected_profile}")
        return selected
    if not profiles:
        raise MigrationUsageError("the selected sandbox has no configured profiles")
    return profiles


def _render_plan(plan: dict[str, Any]) -> str:
    counts = plan["counts"]
    lines = [f"Profile {plan['profile_id']}:"]
    lines.append(f"  eligible: {plan['eligible_count']:,}")
    if plan["legacy_generated_eligible_count"]:
        lines.append(
            "    from explicit legacy generated roots: "
            f"{plan['legacy_generated_eligible_count']:,}"
        )
    if plan["legacy_upload_eligible_count"]:
        lines.append(
            "    from explicit legacy uploads roots: "
            f"{plan['legacy_upload_eligible_count']:,}"
        )
    lines.append(
        "  eligible sources removable: "
        f"{plan['eligible_source_removal_count']:,}"
    )
    lines.append(f"  already managed: {counts.get('already_managed', 0):,}")
    lines.append(f"  external Source media: {counts.get('external_source', 0):,}")
    lines.append(
        "  legacy external registrations eligible: "
        f"{plan['external_registration_count']:,}"
    )
    lines.append(
        "  unretained Stimma-created media: "
        f"{counts.get('unretained_stimma_created', 0):,}"
    )
    lines.append(f"  ephemeral media: {counts.get('ephemeral', 0):,}")
    lines.append(
        "  ambiguous internal metadata: "
        f"{counts.get('ambiguous_internal_metadata', 0):,}"
    )
    lines.append(f"  blocked: {plan['blocked_count']:,}")
    for status, count in counts.items():
        if status.startswith("blocked_"):
            lines.append(f"    {status}: {count:,}")
    for inventory in plan["legacy_root_inventory"]:
        roles = ", ".join(inventory["roles"])
        lines.append(
            f"  declared legacy root ({roles}): {inventory['file_count']:,} files; "
            f"{inventory['remaining_file_count']:,} would remain"
        )
        if inventory["untracked_removal_count"]:
            lines.append(
                "    untracked files scheduled for removal: "
                f"{inventory['untracked_removal_count']:,}"
            )
        for status, count in inventory["remaining_by_status"].items():
            lines.append(f"    {status}: {count:,}")
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    os.environ["STIMMA_DATA_DIR"] = str(args.data_dir)
    from database import Database

    profiles = _configured_profiles(args.data_dir, args.profile)
    legacy_generated_roots = _normalized_roots(args.legacy_generated_roots)
    legacy_upload_roots = _normalized_roots(args.legacy_upload_roots)
    for root in [*legacy_generated_roots, *legacy_upload_roots]:
        if not root.is_dir():
            raise MigrationUsageError(f"declared legacy root is not a directory: {root}")
    profile_contexts = []
    matched_legacy_roots: set[Path] = set()
    for profile in profiles:
        source_roots = [
            Path(folder["path"] if isinstance(folder, dict) else folder)
            for folder in (profile.get("folders") or [])
            if (isinstance(folder, str) and folder)
            or (isinstance(folder, dict) and folder.get("path"))
        ]
        normalized_source_roots = _normalized_roots(source_roots)

        def belongs_to_profile(root: Path) -> bool:
            return any(
                root == source or source in root.parents
                for source in normalized_source_roots
            )

        profile_generated_roots = [
            root for root in legacy_generated_roots if belongs_to_profile(root)
        ]
        profile_upload_roots = [
            root for root in legacy_upload_roots if belongs_to_profile(root)
        ]
        matched_legacy_roots.update(profile_generated_roots)
        matched_legacy_roots.update(profile_upload_roots)
        profile_contexts.append((
            profile,
            normalized_source_roots,
            profile_generated_roots,
            profile_upload_roots,
        ))
    unmatched = [
        root for root in [*legacy_generated_roots, *legacy_upload_roots]
        if root not in matched_legacy_roots
    ]
    if unmatched:
        raise MigrationUsageError(
            "declared legacy root is not inside a configured Source folder: "
            + ", ".join(str(root) for root in unmatched)
        )

    results = []
    for (
        profile,
        normalized_source_roots,
        profile_generated_roots,
        profile_upload_roots,
    ) in profile_contexts:
        profile_id = profile["id"]
        database_path = args.data_dir / profile_id / "stimma_v1.db"
        if not database_path.is_file():
            raise MigrationUsageError(f"profile database does not exist: {profile_id}")
        database = Database(str(database_path))
        try:
            if args.apply:
                result = await apply_profile(
                    database.async_session_maker,
                    profile_id=profile_id,
                    source_roots=normalized_source_roots,
                    legacy_generated_roots=profile_generated_roots,
                    legacy_upload_roots=profile_upload_roots,
                    remove_untracked_legacy_files=args.delete_untracked_legacy_files,
                )
            else:
                async with database.async_session_maker() as session:
                    result = await inspect_profile(
                        session,
                        profile_id=profile_id,
                        source_roots=normalized_source_roots,
                        legacy_generated_roots=profile_generated_roots,
                        legacy_upload_roots=profile_upload_roots,
                        remove_untracked_legacy_files=args.delete_untracked_legacy_files,
                    )
            results.append(result)
        finally:
            await database.async_engine.dispose()
    return {"applied": args.apply, "profiles": results}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--profile")
    parser.add_argument(
        "--legacy-generated-root",
        dest="legacy_generated_roots",
        action="append",
        default=[],
        type=Path,
        help="repeatable historical Stimma generation root to adopt",
    )
    parser.add_argument(
        "--legacy-uploads-root",
        dest="legacy_upload_roots",
        action="append",
        default=[],
        type=Path,
        help="repeatable historical Stimma-owned uploads root to adopt",
    )
    parser.add_argument(
        "--delete-untracked-legacy-files",
        action="store_true",
        help="remove files in declared legacy roots that have no live Media record",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.yes:
        parser.error("--apply requires --yes after making a backup")
    try:
        report = asyncio.run(_run(args))
    except MigrationUsageError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        if args.apply:
            print("Managed-storage normalization applied")
            for result in report["profiles"]:
                print(
                    f"Profile {result['profile_id']}: migrated {result['migrated']:,}; "
                    f"registered {result['external_registered']:,} external; "
                    f"removed {result['untracked_removed']:,} untracked; "
                    f"removed {result['source_groups_removed']:,} source groups; "
                    f"recovered {result['cleanup_retried']:,} staged cleanups; "
                    f"errors {len(result['errors']):,}"
                )
                print(_render_plan(result["remaining"]))
        else:
            print("Managed-storage normalization dry run (no changes)")
            for plan in report["profiles"]:
                print(_render_plan(plan))
            print("Back up the sandbox, stop Stimma, then add --apply --yes to write.")
    if args.apply and any(
        result["errors"]
        or result["remaining"]["blocked_count"]
        or result["remaining"]["legacy_root_remaining_file_count"]
        for result in report["profiles"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

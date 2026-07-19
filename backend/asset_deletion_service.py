"""Privacy-aware permanent deletion for Asset roots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from asset_service import AssetServiceError, clear_snapshot_source_bindings
from container_service import tombstone_linked_asset_references
from database import (
    Asset,
    AssetMarker,
    AssetMigrationMap,
    AssetRevision,
    AssetSnapshot,
    AssetTag,
    BoardAssetItem,
    ChatItem,
    ContainerMember,
    DeleteOperation,
    GenerationJob,
    ManagedArtifact,
    MediaItem,
    MediaOwner,
    ProjectAsset,
    WorkingDocument,
)
from delete_operations import create_delete_operation


@dataclass
class AssetDeletionResult:
    operation: DeleteOperation | None
    retained_media_ids: list[int]


@dataclass
class AssetDeletionPreview:
    revision_count: int
    candidate_media_ids: list[int]
    collectible_media_ids: list[int]
    retained_media_ids: list[int]
    retained_by_kind: dict[str, int]
    source_file_count: int


async def preview_asset_deletion(
    session: AsyncSession,
    *,
    asset_id: int,
) -> AssetDeletionPreview:
    """Describe permanent deletion without changing identity or retention edges."""
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise AssetServiceError("Asset not found")
    revisions = list(
        await session.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset_id))
    )
    revision_ids = [revision.id for revision in revisions]
    documents = list(
        await session.scalars(select(WorkingDocument).where(WorkingDocument.asset_id == asset_id))
    )
    document_ids = [document.id for document in documents]
    snapshots = list(
        await session.scalars(
            select(AssetSnapshot).where(
                (
                    (AssetSnapshot.owner_kind == "revision")
                    & AssetSnapshot.owner_id.in_([str(value) for value in revision_ids])
                )
                | (
                    (AssetSnapshot.owner_kind == "working_document")
                    & AssetSnapshot.owner_id.in_([str(value) for value in document_ids])
                )
            )
        )
    )
    snapshot_ids = [snapshot.id for snapshot in snapshots]
    candidate_ids = {revision.primary_media_id for revision in revisions}
    candidate_ids.update(snapshot.media_id for snapshot in snapshots)
    if revision_ids:
        candidate_ids.update(
            value
            for value in await session.scalars(
                select(ContainerMember.embedded_media_id).where(
                    ContainerMember.container_revision_id.in_(revision_ids),
                    ContainerMember.embedded_media_id.is_not(None),
                )
            )
            if value is not None
        )

    removed_roots = {
        *(("asset_revision", str(value)) for value in revision_ids),
        *(("container_revision", str(value)) for value in revision_ids),
        *(("working_document", str(value)) for value in document_ids),
        *(("asset_snapshot", str(value)) for value in snapshot_ids),
    }
    collectible: list[int] = []
    retained: list[int] = []
    retained_by_kind: dict[str, int] = {}
    for media_id in sorted(candidate_ids):
        owners = list(
            await session.scalars(
                select(MediaOwner).where(
                    MediaOwner.media_id == media_id,
                    MediaOwner.deleted_at.is_(None),
                )
            )
        )
        surviving = [
            owner for owner in owners
            if (owner.root_kind, owner.root_id) not in removed_roots
        ]
        if surviving:
            retained.append(media_id)
            for kind in {owner.root_kind for owner in surviving}:
                retained_by_kind[kind] = retained_by_kind.get(kind, 0) + 1
        else:
            collectible.append(media_id)
    source_file_count = 0
    if collectible:
        from database import StorageObject

        source_file_count = (
            await session.scalar(
                select(func.count(func.distinct(MediaItem.id)))
                .select_from(MediaItem)
                .join(
                    StorageObject,
                    StorageObject.id == MediaItem.storage_object_id,
                )
                .where(
                    MediaItem.id.in_(collectible),
                    StorageObject.kind == "external",
                )
            )
        ) or 0
    return AssetDeletionPreview(
        revision_count=len(revisions),
        candidate_media_ids=sorted(candidate_ids),
        collectible_media_ids=collectible,
        retained_media_ids=retained,
        retained_by_kind=retained_by_kind,
        source_file_count=source_file_count,
    )


def _scrub_asset_refs(value: Any, asset_id: int) -> bool:
    changed = False
    if isinstance(value, dict):
        matching_keys = [
            key
            for key, child in value.items()
            if (key == "asset_id" or key.endswith("_asset_id"))
            and child == asset_id
        ]
        if matching_keys:
            for key in matching_keys:
                value.pop(key, None)
            value["asset_unavailable"] = True
            changed = True
        for key, asset_ids in list(value.items()):
            if key != "asset_ids" and not key.endswith("_asset_ids"):
                continue
            if isinstance(asset_ids, list):
                filtered = [item for item in asset_ids if item != asset_id]
                if filtered != asset_ids:
                    value[key] = filtered
                    changed = True
        for child in value.values():
            changed = _scrub_asset_refs(child, asset_id) or changed
    elif isinstance(value, list):
        for child in value:
            changed = _scrub_asset_refs(child, asset_id) or changed
    return changed


async def _scrub_chat_asset_references(session: AsyncSession, asset_id: int) -> None:
    items = list(
        await session.scalars(
            select(ChatItem).where(
                (ChatItem.asset_id == asset_id)
                | ChatItem.asset_ids.is_not(None)
                | ChatItem.item_metadata.is_not(None)
                | ChatItem.tool_args.is_not(None)
                | ChatItem.tool_result.is_not(None)
                | ChatItem.grid_layout.is_not(None)
            )
        )
    )
    for item in items:
        if item.asset_id == asset_id:
            item.asset_id = None
        if item.asset_ids:
            try:
                ids = json.loads(item.asset_ids)
            except (json.JSONDecodeError, TypeError):
                item.asset_ids = "[]"
                ids = None
            if isinstance(ids, list):
                item.asset_ids = json.dumps([value for value in ids if value != asset_id])
        for field in ("item_metadata", "tool_args", "tool_result", "grid_layout"):
            raw = getattr(item, field)
            if not raw:
                continue
            try:
                metadata = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                # Opaque malformed state cannot be proven free of the deleted
                # identity, so discard the blob instead of reporting a
                # privacy-complete deletion while retaining it.
                setattr(item, field, None)
                metadata = None
            if metadata is not None and _scrub_asset_refs(metadata, asset_id):
                setattr(item, field, json.dumps(metadata))


async def permanently_delete_asset(
    session: AsyncSession,
    *,
    asset_id: int,
    profile_id: str,
    group_id: str | None = None,
):
    """Destroy an Asset identity and queue only newly-unowned Media collection."""
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise AssetServiceError("Asset not found")
    if asset.state != "trashed":
        raise AssetServiceError("Asset must be in Trash before permanent deletion")
    asset.state = "deleting"
    asset.updated_at = datetime.utcnow()
    await session.flush()

    revisions = list(
        await session.scalars(select(AssetRevision).where(AssetRevision.asset_id == asset_id))
    )
    revision_ids = [revision.id for revision in revisions]
    documents = list(
        await session.scalars(select(WorkingDocument).where(WorkingDocument.asset_id == asset_id))
    )
    document_ids = [document.id for document in documents]

    artifacts = list(await session.scalars(
        select(ManagedArtifact).where(
            ManagedArtifact.deleted_at.is_(None),
            (
                ((ManagedArtifact.owner_kind == "asset") & (ManagedArtifact.owner_id == str(asset_id)))
                | ((ManagedArtifact.owner_kind == "revision") & ManagedArtifact.owner_id.in_([str(v) for v in revision_ids]))
                | ((ManagedArtifact.owner_kind == "working_document") & ManagedArtifact.owner_id.in_([str(v) for v in document_ids]))
            ),
        )
    ))
    snapshots = list(
        await session.scalars(
            select(AssetSnapshot).where(
                (
                    (AssetSnapshot.owner_kind == "revision")
                    & AssetSnapshot.owner_id.in_([str(value) for value in revision_ids])
                )
                | (
                    (AssetSnapshot.owner_kind == "working_document")
                    & AssetSnapshot.owner_id.in_([str(value) for value in document_ids])
                )
            )
        )
    )
    snapshot_ids = [snapshot.id for snapshot in snapshots]
    candidate_media_ids = {revision.primary_media_id for revision in revisions}
    candidate_media_ids.update(snapshot.media_id for snapshot in snapshots)
    candidate_media_ids.update(
        await session.scalars(
            select(ContainerMember.embedded_media_id).where(
                ContainerMember.container_revision_id.in_(revision_ids),
                ContainerMember.embedded_media_id.is_not(None),
            )
        )
    )

    await clear_snapshot_source_bindings(session, source_asset_id=asset_id)
    await tombstone_linked_asset_references(session, asset_id=asset_id)
    await _scrub_chat_asset_references(session, asset_id)
    await session.execute(
        update(Asset)
        .where(
            Asset.origin_type.in_(("editor_save_as_new", "container_explode")),
            Asset.origin_id == str(asset_id),
        )
        .values(origin_id=None)
    )
    await session.execute(
        update(GenerationJob)
        .where(GenerationJob.result_asset_id == asset_id)
        .values(result_asset_id=None)
    )

    root_filters = []
    if revision_ids:
        root_filters.append(
            (MediaOwner.root_kind == "asset_revision")
            & MediaOwner.root_id.in_([str(value) for value in revision_ids])
        )
        root_filters.append(
            (MediaOwner.root_kind == "container_revision")
            & MediaOwner.root_id.in_([str(value) for value in revision_ids])
        )
    if document_ids:
        root_filters.append(
            (MediaOwner.root_kind == "working_document")
            & MediaOwner.root_id.in_([str(value) for value in document_ids])
        )
    if snapshot_ids:
        root_filters.append(
            (MediaOwner.root_kind == "asset_snapshot")
            & MediaOwner.root_id.in_([str(value) for value in snapshot_ids])
        )
    if root_filters:
        from sqlalchemy import or_
        await session.execute(delete(MediaOwner).where(or_(*root_filters)))

    for model in (AssetMarker, AssetTag, ProjectAsset, BoardAssetItem):
        await session.execute(delete(model).where(model.asset_id == asset_id))
    await session.execute(
        update(AssetMigrationMap)
        .where(AssetMigrationMap.asset_id == asset_id)
        .values(asset_id=None, status="asset_deleted")
    )
    if revision_ids:
        await session.execute(
            delete(ContainerMember).where(ContainerMember.container_revision_id.in_(revision_ids))
        )
    if snapshot_ids:
        await session.execute(delete(AssetSnapshot).where(AssetSnapshot.id.in_(snapshot_ids)))
    if document_ids:
        await session.execute(delete(WorkingDocument).where(WorkingDocument.id.in_(document_ids)))
    if revision_ids:
        await session.execute(delete(AssetRevision).where(AssetRevision.id.in_(revision_ids)))
    await session.execute(delete(Asset).where(Asset.id == asset_id))
    await session.flush()

    collectible: list[MediaItem] = []
    for media_id in sorted(candidate_media_ids):
        has_owner = await session.scalar(
            select(MediaOwner.id).where(
                MediaOwner.media_id == media_id,
                MediaOwner.deleted_at.is_(None),
            ).limit(1)
        )
        if has_owner is None:
            media = await session.get(MediaItem, media_id)
            if media is not None:
                collectible.append(media)

    collectible_ids = {media.id for media in collectible}
    retained_media_ids = sorted(candidate_media_ids - collectible_ids)
    if collectible or artifacts:
        operation = await create_delete_operation(
            session,
            profile_id=profile_id,
            kind="asset",
            media_items=collectible,
            managed_artifacts=artifacts,
            group_id=group_id,
        )
        return AssetDeletionResult(
            operation=operation,
            retained_media_ids=retained_media_ids,
        )
    await session.commit()
    return AssetDeletionResult(
        operation=None,
        retained_media_ids=retained_media_ids,
    )

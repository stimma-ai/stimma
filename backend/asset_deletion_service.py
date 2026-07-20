"""Privacy-aware permanent deletion for Asset roots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from asset_service import AssetServiceError
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
from delete_operations import (
    create_delete_operation,
    populate_delete_operation,
    prepare_asset_delete_queue,
)


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


def _scrub_asset_refs(value: Any, deleted_asset_ids: set[int]) -> bool:
    changed = False
    if isinstance(value, dict):
        matching_keys = [
            key
            for key, child in value.items()
            if (key == "asset_id" or key.endswith("_asset_id"))
            and isinstance(child, int)
            and child in deleted_asset_ids
        ]
        if matching_keys:
            for key in matching_keys:
                value.pop(key, None)
            value["asset_unavailable"] = True
            changed = True
        for key, referenced_ids in list(value.items()):
            if key != "asset_ids" and not key.endswith("_asset_ids"):
                continue
            if isinstance(referenced_ids, list):
                filtered = [
                    item for item in referenced_ids
                    if not isinstance(item, int) or item not in deleted_asset_ids
                ]
                if filtered != referenced_ids:
                    value[key] = filtered
                    changed = True
        for child in value.values():
            changed = _scrub_asset_refs(child, deleted_asset_ids) or changed
    elif isinstance(value, list):
        for child in value:
            changed = _scrub_asset_refs(child, deleted_asset_ids) or changed
    return changed


async def _scrub_chat_asset_references(
    session: AsyncSession,
    asset_ids: set[int],
) -> None:
    if not asset_ids:
        return

    target_ids_json = json.dumps(sorted(asset_ids))

    def _json_contains_target(
        column,
        *,
        alias: str,
        root_asset_ids: bool = False,
    ):
        # SQL prefiltering avoids materializing and parsing every historical
        # chat payload in Python for every deletion slice. Invalid JSON remains
        # a candidate so the fail-closed cleanup below keeps its old behavior.
        safe_json = case(
            (func.json_valid(column) == 1, column),
            else_="{}",
        )
        tree = func.json_tree(safe_json).table_valued(
            "key",
            "atom",
            "path",
        ).alias(f"{alias}_tree")
        targets = func.json_each(target_ids_json).table_valued(
            "value"
        ).alias(f"{alias}_targets")
        reference_shape = (
            True
            if root_asset_ids
            else or_(
                tree.c.key == "asset_id",
                tree.c.path.like("%asset_ids"),
            )
        )
        return or_(
            and_(
                column.is_not(None),
                func.json_valid(column) == 0,
            ),
            exists(
                select(1)
                .select_from(tree)
                .where(
                    tree.c.atom.in_(select(targets.c.value)),
                    reference_shape,
                )
            ),
        )

    items = list(
        await session.scalars(
            select(ChatItem).where(
                or_(
                    ChatItem.asset_id.in_(asset_ids),
                    _json_contains_target(
                        ChatItem.asset_ids,
                        alias="chat_asset_ids",
                        root_asset_ids=True,
                    ),
                    _json_contains_target(
                        ChatItem.item_metadata,
                        alias="chat_item_metadata",
                    ),
                    _json_contains_target(
                        ChatItem.tool_args,
                        alias="chat_tool_args",
                    ),
                    _json_contains_target(
                        ChatItem.tool_result,
                        alias="chat_tool_result",
                    ),
                    _json_contains_target(
                        ChatItem.grid_layout,
                        alias="chat_grid_layout",
                    ),
                )
            )
        )
    )
    for item in items:
        if item.asset_id in asset_ids:
            item.asset_id = None
        if item.asset_ids:
            try:
                ids = json.loads(item.asset_ids)
            except (json.JSONDecodeError, TypeError):
                item.asset_ids = "[]"
                ids = None
            if isinstance(ids, list):
                item.asset_ids = json.dumps(
                    [value for value in ids if value not in asset_ids]
                )
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
            if metadata is not None and _scrub_asset_refs(metadata, asset_ids):
                setattr(item, field, json.dumps(metadata))


async def prepare_asset_reference_deletion(
    session: AsyncSession,
    asset_ids: list[int],
) -> None:
    """Scrub weak Asset references once for an entire enqueue request."""
    deleted_asset_ids = set(asset_ids)
    if not deleted_asset_ids:
        return

    await session.execute(
        update(AssetSnapshot)
        .where(AssetSnapshot.source_asset_id.in_(deleted_asset_ids))
        .values(source_asset_id=None, source_revision_id=None)
    )
    await session.execute(
        update(ContainerMember)
        .where(ContainerMember.linked_asset_id.in_(deleted_asset_ids))
        .values(
            linked_asset_id=None,
            missing_linked_asset=True,
            member_metadata=None,
        )
    )
    await _scrub_chat_asset_references(session, deleted_asset_ids)
    await session.execute(
        update(Asset)
        .where(
            Asset.origin_type.in_(("editor_save_as_new", "container_explode")),
            Asset.origin_id.in_([str(value) for value in deleted_asset_ids]),
        )
        .values(origin_id=None)
    )
    await session.execute(
        update(GenerationJob)
        .where(GenerationJob.result_asset_id.in_(deleted_asset_ids))
        .values(result_asset_id=None)
    )
    await session.flush()


async def permanently_delete_asset(
    session: AsyncSession,
    *,
    asset_id: int,
    profile_id: str,
    queue_prepared: bool = False,
    references_prepared: bool = False,
    commit: bool = True,
    known_revisions: list[AssetRevision] | None = None,
    existing_operation: DeleteOperation | None = None,
):
    """Destroy an Asset identity and queue only newly-unowned Media collection."""
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise AssetServiceError("Asset not found")
    allowed_states = (
        {"trashed", "deleting"}
        if existing_operation is not None
        else {"trashed"}
    )
    if asset.state not in allowed_states:
        raise AssetServiceError("Asset must be in Trash before permanent deletion")
    if not queue_prepared:
        await prepare_asset_delete_queue(session, profile_id)
    if not references_prepared:
        await prepare_asset_reference_deletion(session, [asset_id])
    asset.state = "deleting"
    asset.updated_at = datetime.utcnow()
    await session.flush()

    revisions = (
        known_revisions
        if known_revisions is not None
        else list(
            await session.scalars(
                select(AssetRevision).where(AssetRevision.asset_id == asset_id)
            )
        )
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
    if existing_operation is None:
        operation = await create_delete_operation(
            session,
            profile_id=profile_id,
            kind="asset",
            asset_id=asset_id,
            media_items=collectible,
            managed_artifacts=artifacts,
            commit=commit,
        )
    else:
        operation = existing_operation
        await populate_delete_operation(
            session,
            operation=operation,
            media_items=collectible,
            managed_artifacts=artifacts,
        )
    if not collectible and not artifacts:
        # The identity deletion is complete and there is no unlink payload.
        # A durably queued Asset still waits at the shared privacy checkpoint;
        # a direct service call keeps its historical synchronous completion.
        now = datetime.utcnow()
        operation.status = (
            "checkpointing" if existing_operation is not None else "completed"
        )
        operation.current_phase = operation.status
        operation.started_at = now
        operation.completed_at = (
            None if existing_operation is not None else now
        )
        operation.updated_at = now
    if existing_operation is not None or (not collectible and not artifacts):
        if commit:
            await session.commit()
            await session.refresh(operation)
        else:
            await session.flush()
    return AssetDeletionResult(
        operation=operation,
        retained_media_ids=retained_media_ids,
    )

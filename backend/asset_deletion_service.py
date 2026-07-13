"""Privacy-aware permanent deletion for Asset roots."""

from __future__ import annotations

import json
import asyncio
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
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
    GenerationJob,
    ManagedArtifact,
    MediaItem,
    MediaOwner,
    ProjectAsset,
    WorkingDocument,
)
from delete_operations import create_delete_operation


def _scrub_asset_refs(value: Any, asset_id: int) -> bool:
    changed = False
    if isinstance(value, dict):
        if value.get("asset_id") == asset_id:
            value.pop("asset_id", None)
            value["asset_unavailable"] = True
            changed = True
        asset_ids = value.get("asset_ids")
        if isinstance(asset_ids, list):
            filtered = [item for item in asset_ids if item != asset_id]
            if filtered != asset_ids:
                value["asset_ids"] = filtered
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
                ids = []
            if isinstance(ids, list):
                item.asset_ids = json.dumps([value for value in ids if value != asset_id])
        if item.item_metadata:
            try:
                metadata = json.loads(item.item_metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = None
            if metadata is not None and _scrub_asset_refs(metadata, asset_id):
                item.item_metadata = json.dumps(metadata)


async def permanently_delete_asset(
    session: AsyncSession,
    *,
    asset_id: int,
    profile_id: str,
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
    if artifacts:
        from trash_service import TrashService
        for artifact in artifacts:
            try:
                await asyncio.to_thread(
                    TrashService().permanently_delete, artifact.locator
                )
            except Exception as exc:
                raise AssetServiceError(
                    "Managed editor artifact deletion failed"
                ) from exc
            await session.delete(artifact)

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

    if collectible:
        return await create_delete_operation(
            session,
            profile_id=profile_id,
            kind="asset",
            media_items=collectible,
        )
    await session.commit()
    return None

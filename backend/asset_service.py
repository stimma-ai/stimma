"""Transactional primitives for the Asset/Revision/Media model.

The current media APIs do not use these functions yet.  They are intentionally
small and additive so new producers can dual-write without changing legacy
browse behavior during the migration.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import (
    Asset,
    AssetRevision,
    AssetSnapshot,
    MediaItem,
    MediaOwner,
    WorkingDocument,
)


class AssetServiceError(ValueError):
    """The requested Asset operation would violate a model invariant."""


def infer_asset_type(media: MediaItem) -> str:
    """Infer the user-facing Asset type from a legacy Media format."""
    fmt = (media.file_format or "").lower()
    if fmt == "stimmagrid.json":
        return "grid"
    if fmt == "stimmaset.json":
        return "set"
    if fmt in {"mp4", "mov", "mkv", "webm", "avi", "m4v"}:
        return "video"
    if fmt in {"mp3", "wav", "flac", "aac", "m4a", "ogg", "opus"}:
        return "audio"
    if fmt in {"pdf", "doc", "docx", "txt", "md", "rtf"}:
        return "document"
    return "image"


async def _live_media(
    session: AsyncSession, media_id: int, *, allow_deleted: bool = False
) -> MediaItem:
    media = await session.get(MediaItem, media_id)
    if (
        media is None
        or media.deletion_pending_at is not None
        or (media.deleted_at is not None and not allow_deleted)
    ):
        raise AssetServiceError("Media is unavailable")
    return media


async def acquire_media_owner(
    session: AsyncSession,
    *,
    media_id: int,
    root_kind: str,
    root_id: int | str,
    role: str,
    idempotency_key: Optional[str] = None,
    allow_deleted: bool = False,
) -> MediaOwner:
    """Create an idempotent strong-retention edge to Media."""
    await _live_media(session, media_id, allow_deleted=allow_deleted)
    root_id_string = str(root_id)

    if idempotency_key:
        existing_by_key = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.idempotency_key == idempotency_key,
            ).order_by(MediaOwner.id.desc())
        )
        if existing_by_key is not None:
            expected = (media_id, root_kind, root_id_string, role)
            actual = (
                existing_by_key.media_id,
                existing_by_key.root_kind,
                existing_by_key.root_id,
                existing_by_key.role,
            )
            if actual != expected:
                raise AssetServiceError("Idempotency key was already used for another owner")
            if existing_by_key.deleted_at is not None:
                existing_by_key.deleted_at = None
                await session.flush()
            return existing_by_key

    existing = await session.scalar(
        select(MediaOwner).where(
            MediaOwner.media_id == media_id,
            MediaOwner.root_kind == root_kind,
            MediaOwner.root_id == root_id_string,
            MediaOwner.role == role,
            MediaOwner.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing

    owner = MediaOwner(
        media_id=media_id,
        root_kind=root_kind,
        root_id=root_id_string,
        role=role,
        idempotency_key=idempotency_key,
    )
    session.add(owner)
    await session.flush()
    return owner


async def release_media_owner(session: AsyncSession, owner_id: int) -> None:
    """Soft-delete one strong-retention edge. Missing/deleted edges are a no-op."""
    owner = await session.get(MediaOwner, owner_id)
    if owner is not None and owner.deleted_at is None:
        owner.deleted_at = datetime.utcnow()
        await session.flush()


async def create_asset_from_media(
    session: AsyncSession,
    *,
    media_id: int,
    asset_type: Optional[str] = None,
    title: Optional[str] = None,
    origin_type: Optional[str] = None,
    origin_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> Asset:
    """Promote Media into a stable Asset with its first immutable Revision.

    Retrying promotion for the same Media returns the existing Asset. A Media
    object cannot be the primary payload of two Asset identities.
    """
    media = await _live_media(session, media_id)
    existing_revision = await session.scalar(
        select(AssetRevision).where(AssetRevision.primary_media_id == media_id)
    )
    if existing_revision is not None:
        asset = await session.get(Asset, existing_revision.asset_id)
        if asset is None or asset.deleted_at is not None:
            raise AssetServiceError("Media belongs to an unavailable Asset")
        return asset

    asset = Asset(
        asset_type=asset_type or infer_asset_type(media),
        title=title,
        state="active",
        expires_at=expires_at,
        origin_type=origin_type,
        origin_id=origin_id,
    )
    session.add(asset)
    await session.flush()

    revision = AssetRevision(
        asset_id=asset.id,
        primary_media_id=media.id,
        revision_number=1,
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
        idempotency_key=idempotency_key,
    )
    await session.flush()
    return asset


async def commit_revision(
    session: AsyncSession,
    *,
    asset_id: int,
    media_id: int,
    parent_revision_id: Optional[int] = None,
    note: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> AssetRevision:
    """Save Media as a new immutable revision and make it current.

    Passing a non-current parent deliberately creates a branch; the new branch
    becomes current while the old revisions remain addressable.
    """
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.state != "active":
        raise AssetServiceError("Asset is unavailable")
    await _live_media(session, media_id)

    existing = await session.scalar(
        select(AssetRevision).where(AssetRevision.primary_media_id == media_id)
    )
    if existing is not None:
        if existing.asset_id != asset_id:
            raise AssetServiceError("Media is already the primary payload of another Asset")
        return existing

    parent_id = parent_revision_id or asset.current_revision_id
    parent = await session.get(AssetRevision, parent_id) if parent_id else None
    if parent is None or parent.deleted_at is not None or parent.asset_id != asset_id:
        raise AssetServiceError("Parent revision does not belong to this Asset")

    highest_number = await session.scalar(
        select(func.max(AssetRevision.revision_number)).where(
            AssetRevision.asset_id == asset_id
        )
    )
    revision = AssetRevision(
        asset_id=asset_id,
        parent_revision_id=parent.id,
        primary_media_id=media_id,
        revision_number=(highest_number or 0) + 1,
        note=note,
    )
    session.add(revision)
    await session.flush()
    await acquire_media_owner(
        session,
        media_id=media_id,
        root_kind="asset_revision",
        root_id=revision.id,
        role="primary",
        idempotency_key=idempotency_key,
    )
    asset.current_revision_id = revision.id
    asset.updated_at = datetime.utcnow()
    await session.flush()
    return revision


async def restore_revision_as_latest(
    session: AsyncSession,
    *,
    asset_id: int,
    revision_id: int,
) -> AssetRevision:
    """Restore an old saved state by committing a new immutable revision.

    A revision's primary Media can only belong to that revision, so restoring
    creates a new Media identity over the same immutable storage object. This
    preserves history and makes the restore itself undoable.
    """
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.state != "active":
        raise AssetServiceError("Asset is unavailable")
    source_revision = await session.get(AssetRevision, revision_id)
    if (
        source_revision is None
        or source_revision.deleted_at is not None
        or source_revision.asset_id != asset_id
    ):
        raise AssetServiceError("Revision does not belong to this Asset")
    if source_revision.id == asset.current_revision_id:
        return source_revision

    source_media = await _live_media(session, source_revision.primary_media_id)
    excluded = {
        "id",
        "indexed_date",
        "deleted_at",
        "deletion_pending_at",
        "ephemeral_run_id",
        "random_sort_value",
        "auto_delete_at",
    }
    values = {
        column.name: getattr(source_media, column.name)
        for column in MediaItem.__table__.columns
        if column.name not in excluded
    }
    restored_media = MediaItem(**values)
    session.add(restored_media)
    await session.flush()
    return await commit_revision(
        session,
        asset_id=asset_id,
        media_id=restored_media.id,
        parent_revision_id=source_revision.id,
        note=f"Restored version {source_revision.revision_number}",
    )


async def create_working_document(
    session: AsyncSession,
    *,
    asset_id: int,
    editor_type: str,
    base_revision_id: Optional[int] = None,
    branch_key: str = "main",
    state_locator: Optional[str] = None,
) -> WorkingDocument:
    """Create or return an active editor branch for an Asset."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.state != "active":
        raise AssetServiceError("Asset is unavailable")
    base_id = base_revision_id or asset.current_revision_id
    base = await session.get(AssetRevision, base_id) if base_id else None
    if base is None or base.deleted_at is not None or base.asset_id != asset_id:
        raise AssetServiceError("Base revision does not belong to this Asset")

    existing = await session.scalar(
        select(WorkingDocument).where(
            WorkingDocument.asset_id == asset_id,
            WorkingDocument.editor_type == editor_type,
            WorkingDocument.branch_key == branch_key,
            WorkingDocument.deleted_at.is_(None),
        )
    )
    if existing is not None:
        return existing

    document = WorkingDocument(
        asset_id=asset_id,
        editor_type=editor_type,
        branch_key=branch_key,
        base_revision_id=base.id,
        state_locator=state_locator,
    )
    session.add(document)
    await session.flush()
    return document


async def create_asset_snapshot(
    session: AsyncSession,
    *,
    owner_kind: str,
    owner_id: int | str,
    media_id: int,
    role: str,
    position: int = 0,
    source_asset_id: Optional[int] = None,
    source_revision_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> AssetSnapshot:
    """Capture exact Media for editor integrity plus a weak source binding."""
    if owner_kind not in {"revision", "working_document"}:
        raise AssetServiceError("Invalid snapshot owner kind")
    owner_id_string = str(owner_id)
    owner_model = AssetRevision if owner_kind == "revision" else WorkingDocument
    owner_record = await session.get(owner_model, int(owner_id_string))
    if owner_record is None or owner_record.deleted_at is not None:
        raise AssetServiceError("Snapshot owner is unavailable")
    await _live_media(session, media_id)

    if source_asset_id is not None:
        source_asset = await session.get(Asset, source_asset_id)
        if source_asset is None or source_asset.deleted_at is not None:
            raise AssetServiceError("Source Asset is unavailable")
    if source_revision_id is not None:
        source_revision = await session.get(AssetRevision, source_revision_id)
        if source_revision is None or source_revision.deleted_at is not None:
            raise AssetServiceError("Source revision is unavailable")
        if source_asset_id is not None and source_revision.asset_id != source_asset_id:
            raise AssetServiceError("Source revision does not belong to source Asset")

    existing = await session.scalar(
        select(AssetSnapshot).where(
            AssetSnapshot.owner_kind == owner_kind,
            AssetSnapshot.owner_id == owner_id_string,
            AssetSnapshot.role == role,
            AssetSnapshot.position == position,
            AssetSnapshot.deleted_at.is_(None),
        )
    )
    if existing is not None:
        if existing.media_id != media_id:
            raise AssetServiceError("Snapshot slot already captures different Media")
        return existing

    snapshot = AssetSnapshot(
        owner_kind=owner_kind,
        owner_id=owner_id_string,
        media_id=media_id,
        source_asset_id=source_asset_id,
        source_revision_id=source_revision_id,
        role=role,
        position=position,
    )
    session.add(snapshot)
    await session.flush()
    await acquire_media_owner(
        session,
        media_id=media_id,
        root_kind="asset_snapshot",
        root_id=snapshot.id,
        role="snapshot",
        idempotency_key=idempotency_key,
    )
    await session.flush()
    return snapshot


async def clear_snapshot_source_bindings(
    session: AsyncSession,
    *,
    source_asset_id: int,
) -> int:
    """Tombstone weak source bindings without disturbing snapshot Media."""
    snapshots = list(
        await session.scalars(
            select(AssetSnapshot).where(
                AssetSnapshot.source_asset_id == source_asset_id,
            )
        )
    )
    for snapshot in snapshots:
        snapshot.source_asset_id = None
        snapshot.source_revision_id = None
    await session.flush()
    return len(snapshots)


async def trash_asset(session: AsyncSession, *, asset_id: int) -> Asset:
    """Move an Asset root to Trash without releasing any Media ownership."""
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise AssetServiceError("Asset not found")
    if asset.state == "deleting":
        raise AssetServiceError("Asset deletion is already in progress")
    if asset.state != "trashed":
        now = datetime.utcnow()
        asset.state = "trashed"
        asset.deleted_at = now
        asset.updated_at = now
        await session.flush()
    return asset


async def restore_asset(session: AsyncSession, *, asset_id: int) -> Asset:
    """Restore a trashed Asset and clear the expiration that put it there."""
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise AssetServiceError("Asset not found")
    if asset.state != "trashed":
        raise AssetServiceError("Asset is not in Trash")
    asset.state = "active"
    asset.deleted_at = None
    asset.expires_at = None
    asset.updated_at = datetime.utcnow()
    await session.flush()
    return asset

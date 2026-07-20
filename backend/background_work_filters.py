"""Shared eligibility rules for ingestion work and its progress counters."""

from sqlalchemy import and_, exists, or_, select

from database import (
    Asset,
    AssetRevision,
    DeleteOperation,
    DeleteOperationItem,
    MediaItem,
)


ACTIVE_DELETE_STATUSES = ("queued", "running", "checkpointing", "failed")


def media_eligible_for_background_work():
    """Return the canonical filter for Media that background work may process.

    Asset trash state is canonical; ``MediaItem.deleted_at`` is only a legacy
    compatibility tombstone and does not change when an Asset enters Trash.
    Delete-operation items cover the interval after the Asset identity has
    been removed but before its Media row is physically deleted.
    """
    trashed_or_deleting_asset = exists(
        select(AssetRevision.id)
        .join(Asset, Asset.id == AssetRevision.asset_id)
        .where(
            AssetRevision.primary_media_id == MediaItem.id,
            Asset.state.in_(("trashed", "deleting")),
        )
    )
    active_delete_item = exists(
        select(DeleteOperationItem.media_id)
        .join(
            DeleteOperation,
            DeleteOperation.id == DeleteOperationItem.operation_id,
        )
        .where(
            DeleteOperationItem.media_id == MediaItem.id,
            DeleteOperation.status.in_(ACTIVE_DELETE_STATUSES),
        )
    )
    return and_(
        MediaItem.deleted_at.is_(None),
        or_(
            MediaItem.file_unavailable.is_(False),
            MediaItem.file_unavailable.is_(None),
        ),
        ~trashed_or_deleting_asset,
        ~active_delete_item,
    )

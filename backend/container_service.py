"""Normalized container operations for sets and grids."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from asset_service import (
    AssetServiceError,
    acquire_media_owner,
    commit_revision,
    create_asset_from_media,
)
from database import Asset, AssetRevision, ContainerMember, MediaOwner
from database import MediaItem


async def _assert_no_link_cycle(
    session: AsyncSession,
    *,
    container_asset_id: int,
    linked_asset_id: int,
) -> None:
    """Reject direct and transitive live-linked container cycles."""
    pending = [linked_asset_id]
    visited: set[int] = set()
    while pending:
        asset_id = pending.pop()
        if asset_id == container_asset_id:
            raise AssetServiceError("Container link would create a cycle")
        if asset_id in visited:
            continue
        visited.add(asset_id)
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.deleted_at is not None:
            raise AssetServiceError("Linked Asset is unavailable")
        if asset.asset_type not in {"set", "grid"} or asset.current_revision_id is None:
            continue
        child_ids = await session.scalars(
            select(ContainerMember.linked_asset_id).where(
                ContainerMember.container_revision_id == asset.current_revision_id,
                ContainerMember.linked_asset_id.is_not(None),
                ContainerMember.deleted_at.is_(None),
            )
        )
        pending.extend(child_ids)


def _member_target(member: dict[str, Any]) -> tuple[int | None, int | None]:
    linked_asset_id = member.get("linked_asset_id")
    embedded_media_id = member.get("embedded_media_id")
    if (linked_asset_id is None) == (embedded_media_id is None):
        raise AssetServiceError("Container member requires exactly one target")
    return linked_asset_id, embedded_media_id


async def _populate_revision_members(
    session: AsyncSession,
    *,
    container_asset_id: int,
    revision_id: int,
    members: Iterable[dict[str, Any]],
) -> list[ContainerMember]:
    desired = list(members)
    existing = list(
        await session.scalars(
            select(ContainerMember)
            .where(
                ContainerMember.container_revision_id == revision_id,
                ContainerMember.deleted_at.is_(None),
            )
            .order_by(ContainerMember.member_order, ContainerMember.id)
        )
    )
    if existing:
        existing_targets = [
            (member.linked_asset_id, member.embedded_media_id, member.member_order)
            for member in existing
        ]
        desired_targets = [(*_member_target(member), index) for index, member in enumerate(desired)]
        if existing_targets != desired_targets:
            raise AssetServiceError("Immutable container Revision already has different members")
        return existing

    created: list[ContainerMember] = []
    for index, member_data in enumerate(desired):
        linked_asset_id, embedded_media_id = _member_target(member_data)
        if linked_asset_id is not None:
            await _assert_no_link_cycle(
                session,
                container_asset_id=container_asset_id,
                linked_asset_id=int(linked_asset_id),
            )
        member = ContainerMember(
            container_revision_id=revision_id,
            linked_asset_id=linked_asset_id,
            embedded_media_id=embedded_media_id,
            member_order=index,
            row_index=member_data.get("row_index"),
            column_index=member_data.get("column_index"),
            caption=member_data.get("caption"),
            title=member_data.get("title"),
            member_metadata=member_data.get("member_metadata"),
        )
        session.add(member)
        await session.flush()
        if embedded_media_id is not None:
            await acquire_media_owner(
                session,
                media_id=int(embedded_media_id),
                root_kind="container_revision",
                root_id=revision_id,
                role=f"member:{index}",
            )
        created.append(member)
    await session.flush()
    return created


async def populate_container_revision_members(
    session: AsyncSession,
    *,
    container_asset_id: int,
    revision_id: int,
    members: Iterable[dict[str, Any]],
) -> list[ContainerMember]:
    """Idempotently populate a newly created or migrated container Revision."""
    return await _populate_revision_members(
        session,
        container_asset_id=container_asset_id,
        revision_id=revision_id,
        members=members,
    )


async def create_container_asset_from_media(
    session: AsyncSession,
    *,
    media_id: int,
    container_type: str,
    members: Iterable[dict[str, Any]],
    title: str | None = None,
    origin_type: str | None = None,
    origin_id: str | None = None,
    idempotency_key: str | None = None,
) -> Asset:
    """Create one container Asset; embedded cells remain Media, not Assets."""
    if container_type not in {"set", "grid"}:
        raise AssetServiceError("Container type must be set or grid")
    asset = await create_asset_from_media(
        session,
        media_id=media_id,
        asset_type=container_type,
        title=title,
        origin_type=origin_type,
        origin_id=origin_id,
        idempotency_key=idempotency_key,
    )
    if asset.asset_type != container_type:
        raise AssetServiceError("Existing Asset has a different container type")
    await _populate_revision_members(
        session,
        container_asset_id=asset.id,
        revision_id=asset.current_revision_id,
        members=members,
    )
    return asset


async def commit_container_revision(
    session: AsyncSession,
    *,
    asset_id: int,
    media_id: int,
    members: Iterable[dict[str, Any]],
    parent_revision_id: int | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
) -> AssetRevision:
    """Commit an immutable structural snapshot and advance the container head."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.asset_type not in {"set", "grid"}:
        raise AssetServiceError("Asset is not a container")
    revision = await commit_revision(
        session,
        asset_id=asset_id,
        media_id=media_id,
        parent_revision_id=parent_revision_id,
        note=note,
        idempotency_key=idempotency_key,
    )
    await _populate_revision_members(
        session,
        container_asset_id=asset_id,
        revision_id=revision.id,
        members=members,
    )
    return revision


async def resolve_container_members(
    session: AsyncSession,
    *,
    revision_id: int,
) -> list[dict[str, Any]]:
    """Resolve linked members through current heads; embedded members stay exact."""
    members = list(
        await session.scalars(
            select(ContainerMember)
            .where(
                ContainerMember.container_revision_id == revision_id,
                ContainerMember.deleted_at.is_(None),
            )
            .order_by(ContainerMember.member_order, ContainerMember.id)
        )
    )
    resolved: list[dict[str, Any]] = []
    for member in members:
        media_id = member.embedded_media_id
        resolved_revision_id = None
        unavailable = member.missing_linked_asset
        if member.linked_asset_id is not None:
            linked_asset = await session.get(Asset, member.linked_asset_id)
            unavailable = (
                linked_asset is None
                or linked_asset.deleted_at is not None
                or linked_asset.current_revision_id is None
            )
            if not unavailable:
                current = await session.get(AssetRevision, linked_asset.current_revision_id)
                unavailable = current is None or current.deleted_at is not None
                media_id = None if unavailable else current.primary_media_id
                resolved_revision_id = None if unavailable else current.id
        resolved.append(
            {
                "member_id": member.id,
                "linked_asset_id": member.linked_asset_id,
                "media_id": media_id,
                "revision_id": resolved_revision_id,
                "unavailable": unavailable,
                "member_order": member.member_order,
                "row_index": member.row_index,
                "column_index": member.column_index,
                "caption": member.caption,
                "title": member.title,
            }
        )
    return resolved


async def get_normalized_container_content(
    session: AsyncSession,
    *,
    container_media: MediaItem,
) -> dict[str, Any] | None:
    """Project normalized membership into the legacy set/grid content shape."""
    if container_media.file_format not in {"stimmaset.json", "stimmagrid.json"}:
        return None
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == container_media.id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if revision is None:
        return None
    member_count = await session.scalar(
        select(ContainerMember.id).where(
            ContainerMember.container_revision_id == revision.id,
            ContainerMember.deleted_at.is_(None),
        ).limit(1)
    )
    if member_count is None:
        return None
    try:
        base = json.loads(container_media.raw_metadata or "{}")
    except (json.JSONDecodeError, TypeError):
        base = {}
    members = await resolve_container_members(session, revision_id=revision.id)
    media_ids = [entry["media_id"] for entry in members if entry["media_id"] is not None]
    media_by_id = {
        media.id: media
        for media in await session.scalars(
            select(MediaItem).where(MediaItem.id.in_(media_ids))
        )
    }

    def resolved_payload(entry: dict[str, Any]) -> dict[str, Any] | None:
        media = media_by_id.get(entry["media_id"])
        if media is None or media.deleted_at is not None or entry["unavailable"]:
            return None
        return {
            "id": media.id,
            "media_id": media.id,
            "asset_id": entry["linked_asset_id"],
            "revision_id": entry["revision_id"],
            "file_hash": media.file_hash,
            "file_path": media.file_path,
            "file_format": media.file_format,
            "width": media.width,
            "height": media.height,
            "duration": media.duration,
            "vlm_caption": media.vlm_caption,
            "generation_metadata": media.generation_metadata,
            "markers": [],
            "tags": [],
        }

    result = {key: value for key, value in base.items() if key not in {"items", "cells"}}
    result.setdefault("version", 1)
    if container_media.file_format == "stimmaset.json":
        result["items"] = [
            {
                "path": media_by_id[entry["media_id"]].file_path
                if entry["media_id"] in media_by_id
                else None,
                "title": entry["title"],
                "caption": entry["caption"],
                "resolved": resolved_payload(entry),
            }
            for entry in members
        ]
    else:
        result["cells"] = [
            {
                "row": entry["row_index"],
                "col": entry["column_index"],
                "path": media_by_id[entry["media_id"]].file_path
                if entry["media_id"] in media_by_id
                else None,
                "title": entry["title"],
                "caption": entry["caption"],
                "resolved": resolved_payload(entry),
            }
            for entry in members
        ]
    return result


async def explode_container(
    session: AsyncSession,
    *,
    asset_id: int,
) -> list[int]:
    """Promote embedded cells, preserve links, then move the container to Trash."""
    asset = await session.get(Asset, asset_id)
    if (
        asset is None
        or asset.deleted_at is not None
        or asset.asset_type not in {"set", "grid"}
        or asset.current_revision_id is None
    ):
        raise AssetServiceError("Container Asset is unavailable")
    members = list(
        await session.scalars(
            select(ContainerMember).where(
                ContainerMember.container_revision_id == asset.current_revision_id,
                ContainerMember.deleted_at.is_(None),
            )
        )
    )
    promoted_ids: list[int] = []
    for member in members:
        if member.linked_asset_id is not None:
            promoted_ids.append(member.linked_asset_id)
        elif member.embedded_media_id is not None:
            promoted = await create_asset_from_media(
                session,
                media_id=member.embedded_media_id,
                origin_type="container_explode",
                origin_id=str(asset_id),
            )
            promoted_ids.append(promoted.id)
    asset.state = "trashed"
    asset.deleted_at = datetime.utcnow()
    asset.updated_at = datetime.utcnow()
    await session.flush()
    return promoted_ids


async def tombstone_linked_asset_references(
    session: AsyncSession,
    *,
    asset_id: int,
) -> int:
    """Replace links with privacy-safe unavailable structural placeholders."""
    members = list(
        await session.scalars(
            select(ContainerMember).where(
                ContainerMember.linked_asset_id == asset_id,
                ContainerMember.deleted_at.is_(None),
            )
        )
    )
    for member in members:
        member.linked_asset_id = None
        member.missing_linked_asset = True
    await session.flush()
    return len(members)


async def release_container_revision_owners(
    session: AsyncSession,
    *,
    revision_id: int,
) -> int:
    """Release embedded Media only when a container Revision is destroyed."""
    owners = list(
        await session.scalars(
            select(MediaOwner).where(
                MediaOwner.root_kind == "container_revision",
                MediaOwner.root_id == str(revision_id),
                MediaOwner.deleted_at.is_(None),
            )
        )
    )
    now = datetime.utcnow()
    for owner in owners:
        owner.deleted_at = now
    await session.flush()
    return len(owners)


async def infer_structured_member_specs(
    session: AsyncSession,
    *,
    container_media: MediaItem,
) -> list[dict[str, Any]]:
    """Resolve a legacy set/grid manifest into linked or embedded members.

    Existing Assets become live links. Bare Media remains exact embedded
    content, which is the expected shape for newly generated agent grids.
    """
    if container_media.file_format not in {'stimmaset.json', 'stimmagrid.json'}:
        raise AssetServiceError("Media is not a set or grid")
    try:
        payload = json.loads(container_media.raw_metadata or '{}')
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssetServiceError("Container manifest is invalid") from exc
    records = payload.get('items') if container_media.file_format == 'stimmaset.json' else payload.get('cells')
    if not isinstance(records, list):
        raise AssetServiceError("Container manifest has no members")

    all_media = list(
        await session.scalars(
            select(MediaItem).where(
                MediaItem.deleted_at.is_(None),
                MediaItem.ephemeral_run_id.is_(None),
            )
        )
    )
    by_path = {
        os.path.normcase(os.path.abspath(os.path.normpath(item.file_path))): item
        for item in all_media
    }
    base_dir = Path(container_media.file_path).parent
    specs: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get('path'), str):
            continue
        candidate = Path(record['path'])
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        normalized = os.path.normcase(os.path.abspath(os.path.normpath(str(candidate))))
        media = by_path.get(normalized)
        if media is None:
            continue
        revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == media.id,
                AssetRevision.deleted_at.is_(None),
            )
        )
        spec: dict[str, Any]
        if revision is not None:
            spec = {'linked_asset_id': revision.asset_id}
        else:
            spec = {'embedded_media_id': media.id}
        if container_media.file_format == 'stimmagrid.json':
            spec['row_index'] = record.get('row', index)
            spec['column_index'] = record.get('col', 0)
        specs.append(spec)
    return specs

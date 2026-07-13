"""Ownership and Asset finalization for persistent Flow media results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from asset_association_service import (
    attach_asset_to_project,
    mirror_media_associations_to_asset,
)
from asset_service import AssetServiceError, acquire_media_owner, create_asset_from_media
from container_service import create_container_asset_from_media, infer_structured_member_specs
from database import MediaItem, MediaOwner


VALID_FLOW_OUTPUT_DISPOSITIONS = frozenset(
    {"independent", "container", "internal", "ephemeral"}
)


async def finalize_flow_media_result(
    session: AsyncSession,
    *,
    flow_id: int,
    equation_key: str,
    media_ids: list[int],
    disposition: str,
    project_id: int | None = None,
) -> list[int]:
    """Retain equation Media and promote only declared durable outputs.

    Replace the equation's prior ownership set with this result. Surfaced
    independent/container outputs transfer to AssetRevision ownership; internal
    results remain contextual Media and never enter Asset browsers. Ephemeral
    results are retained only until the equation is replaced or the run ends.
    """
    if disposition not in VALID_FLOW_OUTPUT_DISPOSITIONS:
        raise AssetServiceError(f"Invalid Flow output disposition: {disposition}")

    root_id = f"{flow_id}:{equation_key}"
    ordered_ids = list(dict.fromkeys(int(media_id) for media_id in media_ids))
    prior_owners = list(
        await session.scalars(
            select(MediaOwner).where(
                MediaOwner.root_kind == "flow_equation",
                MediaOwner.root_id == root_id,
                MediaOwner.deleted_at.is_(None),
            )
        )
    )
    released_at = datetime.utcnow()
    for owner in prior_owners:
        if owner.media_id not in ordered_ids:
            owner.deleted_at = released_at

    media_items: list[MediaItem] = []
    for media_id in ordered_ids:
        media = await session.get(MediaItem, media_id)
        if media is None or media.deleted_at is not None:
            raise AssetServiceError(f"Flow result Media {media_id} is unavailable")
        media_items.append(media)
        await acquire_media_owner(
            session,
            media_id=media_id,
            root_kind="flow_equation",
            root_id=root_id,
            role="ephemeral" if disposition == "ephemeral" else "result",
            idempotency_key=f"flow:{root_id}:media:{media_id}",
        )

    if disposition in {"internal", "ephemeral"}:
        await session.flush()
        return []
    if disposition == "container" and len(media_items) != 1:
        raise AssetServiceError("Container Flow output requires exactly one Media item")

    asset_ids: list[int] = []
    for media in media_items:
        if media.file_format in {"stimmaset.json", "stimmagrid.json"}:
            members = await infer_structured_member_specs(
                session, container_media=media
            )
            asset = await create_container_asset_from_media(
                session,
                media_id=media.id,
                container_type="set" if media.file_format == "stimmaset.json" else "grid",
                members=members,
                origin_type="flow_output",
                origin_id=root_id,
                idempotency_key=f"flow:{root_id}:media:{media.id}:asset",
            )
        elif disposition == "container":
            raise AssetServiceError("Container Flow output must be a set or grid")
        else:
            asset = await create_asset_from_media(
                session,
                media_id=media.id,
                origin_type="flow_output",
                origin_id=root_id,
                idempotency_key=f"flow:{root_id}:media:{media.id}:asset",
            )
        await mirror_media_associations_to_asset(
            session, media_id=media.id, asset_id=asset.id
        )
        if project_id is not None:
            await attach_asset_to_project(session, project_id, asset.id)
        asset_ids.append(asset.id)

    owners = list(
        await session.scalars(
            select(MediaOwner).where(
                MediaOwner.media_id.in_(ordered_ids),
                MediaOwner.root_kind == "flow_equation",
                MediaOwner.root_id == root_id,
                MediaOwner.deleted_at.is_(None),
            )
        )
    )
    for owner in owners:
        owner.deleted_at = released_at
    await session.flush()
    return asset_ids


async def release_flow_media_results(
    session: AsyncSession,
    *,
    flow_id: int,
    equation_keys: list[str] | None = None,
    ephemeral_only: bool = False,
) -> list[int]:
    """Release strong FlowEquation roots after invalidation or run cleanup."""
    query = select(MediaOwner).where(
        MediaOwner.root_kind == "flow_equation",
        MediaOwner.root_id.like(f"{flow_id}:%"),
        MediaOwner.deleted_at.is_(None),
    )
    if equation_keys is not None:
        root_ids = [f"{flow_id}:{key}" for key in equation_keys]
        if not root_ids:
            return []
        query = query.where(MediaOwner.root_id.in_(root_ids))
    if ephemeral_only:
        query = query.where(MediaOwner.role == "ephemeral")
    owners = list(await session.scalars(query))
    released_at = datetime.utcnow()
    for owner in owners:
        owner.deleted_at = released_at
    await session.flush()
    return [owner.media_id for owner in owners]


async def reconcile_flow_media_results(
    session: AsyncSession,
    *,
    flow_id: int,
    live_equation_keys: set[str],
) -> list[int]:
    """Release owners left by equations removed while a runtime was offline."""
    prefix = f"{flow_id}:"
    owners = list(
        await session.scalars(
            select(MediaOwner).where(
                MediaOwner.root_kind == "flow_equation",
                MediaOwner.root_id.like(f"{prefix}%"),
                MediaOwner.deleted_at.is_(None),
            )
        )
    )
    stale = [
        owner
        for owner in owners
        if owner.root_id[len(prefix):] not in live_equation_keys
    ]
    released_at = datetime.utcnow()
    for owner in stale:
        owner.deleted_at = released_at
    await session.flush()
    return [owner.media_id for owner in stale]

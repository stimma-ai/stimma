"""Normalized container operations for sets, grids, and sprites.

Sets and grids hold members by position; sprites hold members by role (see
``sprite_document``). All three share the revision/member model here.
"""

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
from database import (
    Asset,
    AssetMarker,
    AssetRevision,
    AssetTag,
    ContainerMember,
    Marker,
    MediaOwner,
    Tag,
)
from database import MediaItem
from sprite_document import (
    CONTAINER_FORMATS,
    SPRITE_FORMAT,
    attach_resolved,
    container_type_for_format,
    iter_sprite_refs,
    media_payload,
    parse_sprite_document,
    sprite_member_specs,
)

CONTAINER_TYPES = {"set", "grid", "sprite", "package", "sheet", "element"}


async def _assert_no_link_cycle(
    session: AsyncSession,
    *,
    container_asset_id: int,
    linked_asset_id: int,
    allow_unavailable: bool = False,
) -> None:
    """Reject direct and transitive live-linked container cycles.

    ``allow_unavailable`` skips links to trashed or missing Assets instead of
    refusing them: a restored revision keeps those as holes.
    """
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
            if allow_unavailable:
                continue
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


def _member_target(
    member: dict[str, Any],
) -> tuple[int | None, int | None, bool]:
    linked_asset_id = member.get("linked_asset_id")
    embedded_media_id = member.get("embedded_media_id")
    missing_linked_asset = bool(member.get("missing_linked_asset", False))
    target_count = sum(
        (
            linked_asset_id is not None,
            embedded_media_id is not None,
            missing_linked_asset,
        )
    )
    if target_count != 1:
        raise AssetServiceError("Container member requires exactly one target")
    return linked_asset_id, embedded_media_id, missing_linked_asset


async def _populate_revision_members(
    session: AsyncSession,
    *,
    container_asset_id: int,
    revision_id: int,
    members: Iterable[dict[str, Any]],
    check_links: bool = True,
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
            (
                member.linked_asset_id,
                member.embedded_media_id,
                member.missing_linked_asset,
                member.member_order,
            )
            for member in existing
        ]
        desired_targets = [(*_member_target(member), index) for index, member in enumerate(desired)]
        if existing_targets != desired_targets:
            raise AssetServiceError("Immutable container Revision already has different members")
        from asset_association_service import clear_asset_expiration

        for member in existing:
            if member.linked_asset_id is not None:
                await clear_asset_expiration(session, member.linked_asset_id)
        return existing

    created: list[ContainerMember] = []
    for index, member_data in enumerate(desired):
        linked_asset_id, embedded_media_id, missing_linked_asset = _member_target(
            member_data
        )
        # Members carried over from this container's own history were valid
        # links when made; a trashed one stays a hole, not an error.
        if linked_asset_id is not None and check_links:
            await _assert_no_link_cycle(
                session,
                container_asset_id=container_asset_id,
                linked_asset_id=int(linked_asset_id),
            )
            from asset_association_service import clear_asset_expiration

            await clear_asset_expiration(session, int(linked_asset_id))
        member = ContainerMember(
            container_revision_id=revision_id,
            linked_asset_id=linked_asset_id,
            embedded_media_id=embedded_media_id,
            missing_linked_asset=missing_linked_asset,
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


def payload_title_from_media(media: MediaItem | None) -> str | None:
    """Read the creation-time title seed out of a container Media payload.

    The payload is a write-once seed: Asset.title owns the title from promotion
    onward, so this is only consulted when an Asset is first created.
    """
    if media is None or not media.raw_metadata:
        return None
    try:
        payload = json.loads(media.raw_metadata)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    title = payload.get("title")
    if not isinstance(title, str):
        return None
    return title.strip() or None


async def container_payload_title(
    session: AsyncSession,
    *,
    media_id: int,
) -> str | None:
    """Payload title seed for a container Media id."""
    return payload_title_from_media(await session.get(MediaItem, media_id))


async def container_title_for_media(
    session: AsyncSession,
    *,
    media_id: int,
) -> str | None:
    """Return the owning Asset's title for a container Media, if promoted."""
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if revision is None:
        return None
    asset = await session.get(Asset, revision.asset_id)
    if asset is None or asset.deleted_at is not None:
        return None
    return asset.title


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
    async with session.begin_nested():
        if container_type not in CONTAINER_TYPES:
            raise AssetServiceError("Container type must be set, grid, sprite, or package")
        if title is None:
            title = await container_payload_title(session, media_id=media_id)
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
    async with session.begin_nested():
        asset = await session.get(Asset, asset_id)
        if asset is None or asset.asset_type not in CONTAINER_TYPES:
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


async def _member_organization(
    session: AsyncSession,
    asset_by_media: dict[int, int | None],
) -> tuple[dict[int, list[dict]], dict[int, list[dict]]]:
    """Markers and tags for container members, keyed by member Media id."""
    from implicit_markers import implicit_markers_by_media

    asset_ids = {asset_id for asset_id in asset_by_media.values() if asset_id}
    markers_by_asset: dict[int, list[dict]] = {}
    tags_by_asset: dict[int, list[dict]] = {}
    if asset_ids:
        for association, marker in (
            await session.execute(
                select(AssetMarker, Marker)
                .join(Marker, Marker.id == AssetMarker.marker_id)
                .where(
                    AssetMarker.asset_id.in_(asset_ids),
                    AssetMarker.deleted_at.is_(None),
                    AssetMarker.source != "suppressed",
                )
            )
        ).all():
            markers_by_asset.setdefault(association.asset_id, []).append(
                {**marker.to_dict(), "source": association.source}
            )
        for association, tag in (
            await session.execute(
                select(AssetTag, Tag)
                .join(Tag, Tag.id == AssetTag.tag_id)
                .where(
                    AssetTag.asset_id.in_(asset_ids),
                    AssetTag.deleted_at.is_(None),
                )
            )
        ).all():
            tags_by_asset.setdefault(association.asset_id, []).append(tag.to_dict())
    implicit = await implicit_markers_by_media(session, asset_by_media.keys())
    markers = {
        media_id: [*markers_by_asset.get(asset_id, []), *implicit[media_id]]
        for media_id, asset_id in asset_by_media.items()
    }
    tags = {
        media_id: tags_by_asset.get(asset_id, [])
        for media_id, asset_id in asset_by_media.items()
    }
    return markers, tags


async def get_normalized_container_content(
    session: AsyncSession,
    *,
    container_media: MediaItem,
) -> dict[str, Any] | None:
    """Project normalized membership into the set/grid/sprite content shape."""
    if container_media.file_format not in CONTAINER_FORMATS:
        return None
    if container_media.file_format == "stimmasheet.html":
        from contact_sheet import sheet_content

        return await sheet_content(session, container_media)
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
    # Asset.title owns the title; the payload copy is a stale creation seed.
    base.pop("title", None)
    asset = await session.get(Asset, revision.asset_id)
    if asset is not None:
        base["title"] = asset.title
    members = await resolve_container_members(session, revision_id=revision.id)
    media_ids = [entry["media_id"] for entry in members if entry["media_id"] is not None]
    media_by_id = {
        media.id: media
        for media in await session.scalars(
            select(MediaItem).where(MediaItem.id.in_(media_ids))
        )
    }
    saved_asset_by_media = {
        saved_revision.primary_media_id: saved_revision.asset_id
        for saved_revision in await session.scalars(
            select(AssetRevision)
            .join(Asset, Asset.id == AssetRevision.asset_id)
            .where(
                AssetRevision.primary_media_id.in_(media_ids),
                AssetRevision.deleted_at.is_(None),
                Asset.state == "active",
                Asset.deleted_at.is_(None),
            )
        )
    } if media_ids else {}

    # Members carry their Asset's organization so viewers show real marker and
    # tag state. Linked members use the linked Asset; embedded members use the
    # saved Asset whose revision holds that exact Media, as marker writes do.
    organizing_asset_by_media = {
        entry["media_id"]: entry["linked_asset_id"]
        or saved_asset_by_media.get(entry["media_id"])
        for entry in members
        if entry["media_id"] is not None
    }
    markers_by_media, tags_by_media = await _member_organization(
        session, organizing_asset_by_media
    )

    def resolved_payload(entry: dict[str, Any]) -> dict[str, Any] | None:
        media = media_by_id.get(entry["media_id"])
        if media is None or media.deleted_at is not None or entry["unavailable"]:
            return None
        return {
            "id": media.id,
            "media_id": media.id,
            "asset_id": entry["linked_asset_id"],
            "saved_asset_id": saved_asset_by_media.get(media.id),
            "revision_id": entry["revision_id"],
            "file_hash": media.file_hash,
            "file_path": media.file_path,
            "file_format": media.file_format,
            "width": media.width,
            "height": media.height,
            "duration": media.duration,
            "generation_metadata": media.generation_metadata,
            "markers": markers_by_media.get(media.id, []),
            "tags": tags_by_media.get(media.id, []),
        }

    if container_media.file_format == SPRITE_FORMAT:
        # Sprite members are keyed by role (member.title); project them back onto
        # the document's references so every ref carries a ``resolved`` block.
        by_role: dict[str, dict[str, Any] | None] = {}
        for entry in members:
            media = media_by_id.get(entry["media_id"])
            if media is None or media.deleted_at is not None or entry["unavailable"]:
                by_role[entry["title"] or ""] = None
                continue
            by_role[entry["title"] or ""] = media_payload(
                media,
                asset_id=entry["linked_asset_id"],
                saved_asset_id=saved_asset_by_media.get(media.id),
                revision_id=entry["revision_id"],
            )
        doc = parse_sprite_document(base) or {"type": "sprite", "version": 1, "animations": []}
        doc["title"] = base.get("title")
        result = attach_resolved(doc, by_role)
        result.setdefault("version", 1)
        return result

    if container_media.file_format == "stimmapackage":
        # Package members are keyed by member id (member.title); attach a
        # ``resolved`` block to each manifest member from this revision's rows.
        by_member_id = {entry["title"] or "": entry for entry in members}
        result = json.loads(json.dumps(base))
        for member in result.get("members") or []:
            entry = by_member_id.get(member.get("id"))
            member["resolved"] = resolved_payload(entry) if entry is not None else None
        return result

    if container_media.file_format == "stimmaelement":
        # Element media slots are keyed by member key (member.title).
        # Ids come from the member rows, which privacy deletion scrubs.
        by_key = {entry["title"] or "": entry for entry in members}
        result = json.loads(json.dumps(base))
        for entry_data in result.get("media_menu") or []:
            entry = by_key.get(entry_data.get("key"))
            entry_data["resolved"] = resolved_payload(entry) if entry is not None else None
            if entry is None or (entry["linked_asset_id"] is None and entry_data.get("embedded_media_id") is None):
                entry_data["asset_id"] = None
            elif entry["linked_asset_id"] is not None:
                entry_data["asset_id"] = entry["linked_asset_id"]
        return result

    result = {key: value for key, value in base.items() if key not in {"items", "cells"}}
    result.setdefault("version", 1)
    if container_media.file_format == "stimmaset.json":
        result["items"] = [
            {
                "member_id": entry["member_id"],
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
                "member_id": entry["member_id"],
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


async def save_container_members_as_assets(
    session: AsyncSession,
    *,
    asset_id: int,
    allow_trashed: bool = False,
) -> list[int]:
    """Promote embedded cells while preserving the container and linked Assets."""
    asset = await session.get(Asset, asset_id)
    if (
        asset is None
        or (asset.deleted_at is not None and not allow_trashed)
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
    seen_asset_ids: set[int] = set()
    for member in members:
        if member.linked_asset_id is not None:
            promoted_id = member.linked_asset_id
        elif member.embedded_media_id is not None:
            promoted = await create_asset_from_media(
                session,
                media_id=member.embedded_media_id,
                origin_type="container_explode",
                origin_id=str(asset_id),
            )
            promoted_id = promoted.id
        else:
            continue
        if promoted_id not in seen_asset_ids:
            seen_asset_ids.add(promoted_id)
            promoted_ids.append(promoted_id)
    await session.flush()
    return promoted_ids


async def explode_container(
    session: AsyncSession,
    *,
    asset_id: int,
) -> list[int]:
    """Compatibility operation: save members, then move the container to Trash."""
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.asset_type not in {"set", "grid"}:
        raise AssetServiceError("Container Asset is unavailable")
    promoted_ids = await save_container_members_as_assets(
        session, asset_id=asset_id, allow_trashed=True
    )
    if asset.deleted_at is None:
        asset.state = "trashed"
        asset.deleted_at = datetime.utcnow()
        asset.updated_at = datetime.utcnow()
    await session.flush()
    return promoted_ids


async def get_container_member_summary(
    session: AsyncSession,
    *,
    asset_id: int,
) -> dict[str, int | str | None]:
    """Return exact current-head counts for the explode confirmation."""
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
    embedded_ids = [
        member.embedded_media_id
        for member in members
        if member.embedded_media_id is not None
    ]
    unique_embedded_ids = set(embedded_ids)
    saved_media_ids: set[int] = set()
    if unique_embedded_ids:
        saved_media_ids = set(
            await session.scalars(
                select(AssetRevision.primary_media_id)
                .join(Asset, Asset.id == AssetRevision.asset_id)
                .where(
                    AssetRevision.primary_media_id.in_(unique_embedded_ids),
                    AssetRevision.deleted_at.is_(None),
                    Asset.state == "active",
                    Asset.deleted_at.is_(None),
                )
            )
        )
    embedded = len(embedded_ids)
    linked_asset_ids = {
        member.linked_asset_id
        for member in members
        if member.linked_asset_id is not None
    }
    return {
        "asset_id": asset.id,
        "asset_type": asset.asset_type,
        "title": asset.title,
        "total": len(members),
        "embedded": embedded,
        "to_create": len(unique_embedded_ids - saved_media_ids),
        "already_saved": len(saved_media_ids),
        "linked": len(linked_asset_ids),
        "unavailable": sum(member.missing_linked_asset for member in members),
    }


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
            )
        )
    )
    for member in members:
        member.linked_asset_id = None
        member.missing_linked_asset = True
        member.member_metadata = None
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
    """Resolve a container manifest into linked or embedded members.

    Sets and grids: existing Assets become live links, bare Media remains exact
    embedded content (the expected shape for newly generated agent grids).
    Sprites: every reference is an exact embedded member keyed by role — the
    document is a composition and pins specific artifacts.
    """
    if container_media.file_format not in CONTAINER_FORMATS:
        raise AssetServiceError("Media is not a set, grid, or sprite")
    try:
        payload = json.loads(container_media.raw_metadata or '{}')
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssetServiceError("Container manifest is invalid") from exc
    if container_media.file_format == SPRITE_FORMAT:
        doc = parse_sprite_document(payload)
        if doc is None:
            raise AssetServiceError("Sprite document is invalid")
        return await sprite_member_specs(session, doc)
    if container_media.file_format == "stimmasheet.html":
        from contact_sheet import parse_sheet_metadata, sheet_member_specs

        meta = parse_sheet_metadata(payload)
        if meta is None:
            raise AssetServiceError("Contact sheet document is invalid")
        return await sheet_member_specs(session, meta)
    if container_media.file_format == "stimmapackage":
        from packages.bundle import package_member_specs
        from packages.manifest import parse_manifest

        manifest = parse_manifest(payload)
        if manifest is None:
            raise AssetServiceError("Package manifest is invalid")
        return await package_member_specs(session, manifest)
    if container_media.file_format == "stimmaelement":
        from elements.bundle import element_member_specs
        from elements.manifest import parse_manifest as parse_element_manifest

        manifest = parse_element_manifest(payload)
        if manifest is None:
            raise AssetServiceError("Element manifest is invalid")
        return element_member_specs(manifest)
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


# Member removal --------------------------------------------------------------
#
# Delete acts on the image, never on the layout. Sets and grids take a member
# out by committing a new Revision without it; contact sheets, sprites and
# packages are built documents whose members are parts, so they refuse.

EDITABLE_CONTAINER_TYPES = {"set", "grid"}


class ContainerRevisionConflict(AssetServiceError):
    """The container moved on since the caller looked at it."""


def _carried_member(member: ContainerMember) -> dict[str, Any]:
    return {
        "linked_asset_id": member.linked_asset_id,
        "embedded_media_id": member.embedded_media_id,
        "missing_linked_asset": member.missing_linked_asset,
        "row_index": member.row_index,
        "column_index": member.column_index,
        "caption": member.caption,
        "title": member.title,
        "member_metadata": member.member_metadata,
    }


async def carry_revision_members(
    session: AsyncSession,
    *,
    asset_id: int,
    source_revision_id: int,
    revision_id: int,
) -> list[ContainerMember]:
    """Give ``revision_id`` the same members as ``source_revision_id`` (idempotent).

    Links are checked against what the linked containers hold now, so a
    restore can't make a container contain itself.
    """
    members = await _revision_members(session, source_revision_id)
    for member in members:
        if member.linked_asset_id is not None:
            await _assert_no_link_cycle(
                session,
                container_asset_id=asset_id,
                linked_asset_id=int(member.linked_asset_id),
                allow_unavailable=True,
            )
    return await _populate_revision_members(
        session,
        container_asset_id=asset_id,
        revision_id=revision_id,
        members=[_carried_member(m) for m in members],
        check_links=False,
    )


async def _revision_members(
    session: AsyncSession, revision_id: int
) -> list[ContainerMember]:
    return list(
        await session.scalars(
            select(ContainerMember)
            .where(
                ContainerMember.container_revision_id == revision_id,
                ContainerMember.deleted_at.is_(None),
            )
            .order_by(ContainerMember.member_order, ContainerMember.id)
        )
    )


async def _editable_container(
    session: AsyncSession, *, asset_id: int, expected_revision_id: int | None
) -> Asset:
    asset = await session.get(Asset, asset_id)
    if (
        asset is None
        or asset.deleted_at is not None
        or asset.state != "active"
        or asset.current_revision_id is None
    ):
        raise AssetServiceError("Container Asset is unavailable")
    if asset.asset_type not in CONTAINER_TYPES:
        raise AssetServiceError("Asset is not a container")
    if asset.asset_type not in EDITABLE_CONTAINER_TYPES:
        raise AssetServiceError(
            f"Members of a {asset.asset_type} are part of the built document"
        )
    if expected_revision_id is not None and asset.current_revision_id != expected_revision_id:
        raise ContainerRevisionConflict("The container changed")
    return asset


async def _write_container_manifest(
    session: AsyncSession,
    *,
    source_media: MediaItem,
    manifest: dict[str, Any],
) -> MediaItem:
    """Stage a new manifest payload; the caller commits, then cleans the source."""
    import hashlib
    import uuid

    import app_dirs
    from core.profile_context import get_current_profile
    from storage_service import stage_managed_media

    profile_id = get_current_profile()
    staging = app_dirs.get_managed_staging_dir(profile_id, "generated")
    staging.mkdir(parents=True, exist_ok=True)
    stem = "set" if source_media.file_format == "stimmaset.json" else "grid"
    path = staging / f"{stem}_{uuid.uuid4().hex[:12]}.{source_media.file_format}"
    data = json.dumps(manifest, indent=2).encode("utf-8")
    path.write_bytes(data)
    now = datetime.utcnow()
    media = MediaItem(
        file_path=str(path),
        file_hash=hashlib.sha256(data).hexdigest(),
        file_size=len(data),
        file_format=source_media.file_format,
        original_filename=path.name,
        created_date=now,
        modified_date=now,
        indexed_date=now,
        metadata_status="completed",
        metadata_processed_at=now,
        metadata_config_version=source_media.metadata_config_version,
        width=0,
        height=0,
        megapixels=0,
        raw_metadata=json.dumps(manifest),
        generation_metadata=source_media.generation_metadata,
    )
    session.add(media)
    await session.flush()
    await stage_managed_media(
        session, media=media, profile_id=profile_id, remove_source=True
    )
    return media


def _manifest_without(
    manifest: dict[str, Any],
    *,
    file_format: str,
    members: list[ContainerMember],
    removed: ContainerMember,
) -> dict[str, Any]:
    """Keep the payload manifest in step with normalized membership."""
    result = json.loads(json.dumps(manifest))
    if file_format == "stimmaset.json":
        items = result.get("items")
        # Only an aligned manifest maps index to member; otherwise the
        # normalized rows stay the authority and the manifest is left alone.
        if isinstance(items, list) and len(items) == len(members):
            items.pop(members.index(removed))
    elif removed.row_index is not None and removed.column_index is not None:
        cells = result.get("cells")
        if isinstance(cells, list):
            result["cells"] = [
                cell
                for cell in cells
                if not (
                    isinstance(cell, dict)
                    and cell.get("row") == removed.row_index
                    and cell.get("col") == removed.column_index
                )
            ]
    return result


async def remove_container_member(
    session: AsyncSession,
    *,
    asset_id: int,
    member_id: int,
    expected_revision_id: int | None = None,
) -> tuple[AssetRevision, int, MediaItem]:
    """Commit a set/grid Revision without one member.

    Returns the new Revision, the Revision it replaced (the undo target) and
    its new payload. A grid keeps its rows, columns and headers: the cell is
    simply empty.
    """
    async with session.begin_nested():
        asset = await _editable_container(
            session, asset_id=asset_id, expected_revision_id=expected_revision_id
        )
        head = await session.get(AssetRevision, asset.current_revision_id)
        members = await _revision_members(session, head.id)
        removed = next((member for member in members if member.id == member_id), None)
        if removed is None:
            raise ContainerRevisionConflict("The member is no longer in this container")
        source_media = await session.get(MediaItem, head.primary_media_id)
        if source_media is None:
            raise AssetServiceError("Container payload is unavailable")
        try:
            manifest = json.loads(source_media.raw_metadata or "{}")
        except (json.JSONDecodeError, TypeError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        new_media = await _write_container_manifest(
            session,
            source_media=source_media,
            manifest=_manifest_without(
                manifest,
                file_format=source_media.file_format,
                members=members,
                removed=removed,
            ),
        )
        revision = await commit_revision(
            session,
            asset_id=asset_id,
            media_id=new_media.id,
            parent_revision_id=head.id,
            note="Removed a member",
        )
        await _populate_revision_members(
            session,
            container_asset_id=asset_id,
            revision_id=revision.id,
            members=[_carried_member(m) for m in members if m.id != removed.id],
            check_links=False,
        )
        return revision, head.id, new_media


async def revert_container_members(
    session: AsyncSession,
    *,
    asset_id: int,
    revision_id: int,
    expected_revision_id: int,
) -> AssetRevision:
    """Undo a member removal: bring an earlier Revision's members back as latest."""
    from asset_service import restore_revision_as_latest

    async with session.begin_nested():
        asset = await _editable_container(
            session, asset_id=asset_id, expected_revision_id=expected_revision_id
        )
        source = await session.get(AssetRevision, revision_id)
        if source is None or source.deleted_at is not None or source.asset_id != asset.id:
            raise AssetServiceError("Revision does not belong to this Asset")
        members = await _revision_members(session, source.id)
        revision = await restore_revision_as_latest(
            session, asset_id=asset_id, revision_id=revision_id
        )
        await _populate_revision_members(
            session,
            container_asset_id=asset_id,
            revision_id=revision.id,
            members=[_carried_member(m) for m in members],
            check_links=False,
        )
        return revision

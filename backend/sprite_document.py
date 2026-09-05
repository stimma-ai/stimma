"""Sprite documents (``.stimmasprite.json``): the recipe for one animated character.

A sprite document is one character. It carries a ``production`` block (the
inputs the code path used: style preset, key colour, cleanup profile, frame
budget, target height, direction scheme, tool ids), media references for the
base image, portrait, and every per-move artifact, and per-animation timing.

Media references are ``{"media_id": N, "hash": "<sha256>"}``. The id is the
handle a fresh agent uses to walk lineage; the hash is the integrity check and
the key the preview widget resolves through ``/media/by-hash/{hash}/file``.

Sprites are containers in the asset model: every referenced Media is an exact
embedded member of each revision. That keeps referenced artifacts from being
deleted underneath the document and gives revisions a structural snapshot.
Membership order is deterministic (see :func:`iter_sprite_refs`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem

SPRITE_FORMAT = "stimmasprite.json"
SPRITE_EXTENSION = ".stimmasprite.json"

# Every container format the asset model knows. Sets and grids are members-by-
# position; sprites are members-by-role.
CONTAINER_FORMATS = frozenset({"stimmaset.json", "stimmagrid.json", SPRITE_FORMAT})

DOCUMENT_REF_FIELDS = ("base_image", "base_image_nobg", "portrait")
ANIMATION_REF_FIELDS = ("anchor", "source_video", "animation")

DIRECTIONS = (
    "south", "southwest", "west", "northwest",
    "north", "northeast", "east", "southeast",
)
LOOP_MODES = ("loop", "once", "pingpong")


def is_sprite_format(file_format: Optional[str]) -> bool:
    return (file_format or "").lower() == SPRITE_FORMAT


def is_container_format(file_format: Optional[str]) -> bool:
    return (file_format or "").lower() in CONTAINER_FORMATS


def container_type_for_format(file_format: Optional[str]) -> Optional[str]:
    """Asset ``asset_type`` for a container file format, else None."""
    fmt = (file_format or "").lower()
    if fmt == "stimmaset.json":
        return "set"
    if fmt == "stimmagrid.json":
        return "grid"
    if fmt == SPRITE_FORMAT:
        return "sprite"
    return None


def parse_sprite_document(raw: Any) -> Optional[dict]:
    """Parse a document payload (JSON text or dict). None when it is not a sprite."""
    if isinstance(raw, (str, bytes)):
        try:
            payload = json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return None
    else:
        payload = raw
    if not isinstance(payload, dict) or payload.get("type") != "sprite":
        return None
    return payload


def load_sprite_document(path: str | Path) -> Optional[dict]:
    try:
        return parse_sprite_document(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None


def animation_key(entry: dict) -> str:
    direction = entry.get("direction")
    name = entry.get("name") or "animation"
    return f"{name}_{direction}" if direction else name


def _is_ref(value: Any) -> bool:
    return isinstance(value, dict) and (value.get("media_id") is not None or value.get("hash"))


def iter_sprite_refs(doc: dict) -> Iterator[tuple[str, dict]]:
    """Yield ``(role, ref)`` for every media reference, in a stable order.

    Roles: ``base_image``, ``base_image_nobg``, ``portrait``, then per
    animation ``<key>/anchor``, ``<key>/source_video``, ``<key>/animation``.
    Order defines container member order, so it must not change casually.
    """
    for field in DOCUMENT_REF_FIELDS:
        ref = doc.get(field)
        if _is_ref(ref):
            yield field, ref
    for entry in doc.get("animations") or []:
        if not isinstance(entry, dict):
            continue
        key = animation_key(entry)
        for field in ANIMATION_REF_FIELDS:
            ref = entry.get(field)
            if _is_ref(ref):
                yield f"{key}/{field}", ref


def validate_sprite_document(doc: Any) -> list[str]:
    """Structural checks mirroring the skill lib's validator. Empty list = valid."""
    errors: list[str] = []
    if not isinstance(doc, dict) or doc.get("type") != "sprite":
        return ["type must be 'sprite'"]
    if doc.get("version") != 1:
        errors.append(f"version must be 1, got {doc.get('version')!r}")
    if not doc.get("title"):
        errors.append("title is required")
    anchor = doc.get("anchor") or {}
    try:
        if not (0 <= float(anchor.get("x", -1)) <= 1 and 0 <= float(anchor.get("y", -1)) <= 1):
            errors.append("anchor.x and anchor.y must be in [0,1]")
    except (TypeError, ValueError):
        errors.append("anchor.x and anchor.y must be numbers in [0,1]")
    for role, ref in iter_sprite_refs(doc):
        if not ref.get("hash"):
            errors.append(f"{role}: reference needs a hash")
    seen: set = set()
    for i, entry in enumerate(doc.get("animations") or []):
        where = f"animations[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        key = (entry.get("name"), entry.get("direction"))
        if key in seen:
            errors.append(f"{where}: duplicate (name, direction) {key}")
        seen.add(key)
        if not entry.get("name"):
            errors.append(f"{where}: name is required")
        if entry.get("direction") not in DIRECTIONS + (None,):
            errors.append(f"{where}: bad direction {entry.get('direction')!r}")
        if entry.get("loop") not in LOOP_MODES:
            errors.append(f"{where}: bad loop {entry.get('loop')!r}")
        if not _is_ref(entry.get("animation")):
            errors.append(f"{where}: animation reference is required")
        n = entry.get("frame_count", 0)
        if not isinstance(n, int) or n < 1:
            errors.append(f"{where}: frame_count must be >= 1")
            continue
        frames = entry.get("frames")
        if not isinstance(frames, list) or len(frames) != n:
            errors.append(f"{where}: frames must have {n} entries")
        try:
            if not (0 <= int(entry.get("loop_start", -1)) <= int(entry.get("loop_end", -1)) < n):
                errors.append(f"{where}: need 0 <= loop_start <= loop_end < frame_count")
        except (TypeError, ValueError):
            errors.append(f"{where}: loop_start/loop_end must be integers")
    return errors


async def _media_for_ref(session: AsyncSession, ref: dict) -> Optional[MediaItem]:
    """Resolve one reference: by media id first, hash second (latest live match)."""
    media_id = ref.get("media_id")
    if media_id is not None:
        try:
            media = await session.get(MediaItem, int(media_id))
        except (TypeError, ValueError):
            media = None
        if (
            media is not None
            and media.deleted_at is None
            and media.deletion_pending_at is None
            and media.ephemeral_run_id is None
        ):
            return media
    digest = ref.get("hash")
    if digest:
        return await session.scalar(
            select(MediaItem)
            .where(
                MediaItem.file_hash == digest,
                MediaItem.deleted_at.is_(None),
                MediaItem.deletion_pending_at.is_(None),
                MediaItem.ephemeral_run_id.is_(None),
            )
            .order_by(MediaItem.id.desc())
            .limit(1)
        )
    return None


async def resolve_sprite_refs(
    session: AsyncSession, doc: dict
) -> dict[str, Optional[MediaItem]]:
    """Map every reference role to its MediaItem (None when unresolvable)."""
    resolved: dict[str, Optional[MediaItem]] = {}
    for role, ref in iter_sprite_refs(doc):
        resolved[role] = await _media_for_ref(session, ref)
    return resolved


async def sprite_member_specs(session: AsyncSession, doc: dict) -> list[dict[str, Any]]:
    """Container member specs for a sprite: exact embedded Media, one per role.

    The recipe pins exact artifacts, so members are never live asset links
    even when a referenced image happens to be an Asset's payload. A reference
    that cannot be resolved is skipped: the document still validates, and the
    content endpoint reports it as unresolved.
    """
    specs: list[dict[str, Any]] = []
    for role, media in (await resolve_sprite_refs(session, doc)).items():
        if media is None:
            continue
        specs.append({"embedded_media_id": media.id, "title": role})
    return specs


def sprite_frame_indices(entry: dict, encoded_durations: list[int]) -> list[int]:
    """Map logical document frames onto WebP frames (which can merge holds).

    New documents pin this mapping before timing edits. For older documents,
    recover it from the original timeline only when its boundaries align.
    """
    count = entry["frame_count"]
    mapping = (entry.get("animation") or {}).get("frame_indices")
    if mapping is not None:
        if (not isinstance(mapping, list) or len(mapping) != count
                or any(type(i) is not int or not 0 <= i < len(encoded_durations) for i in mapping)):
            raise ValueError("animation.frame_indices must map every document frame to an encoded frame")
        return mapping
    if len(encoded_durations) == count:
        return list(range(count))
    if len(encoded_durations) == 1:
        return [0] * count
    base = max(1, round(1000 / float(entry.get("fps") or 12)))
    durations = [int(m.get("duration_ms") or base) for m in entry["frames"]]
    mapping = []
    index = 0
    elapsed = 0
    boundary = encoded_durations[0]
    for duration in durations:
        if duration <= 0 or elapsed + duration > boundary:
            raise ValueError("Encoded frame boundaries do not match the document timeline")
        mapping.append(index)
        elapsed += duration
        if elapsed == boundary and index + 1 < len(encoded_durations):
            index += 1
            boundary += encoded_durations[index]
    if elapsed != sum(encoded_durations):
        raise ValueError("Encoded duration does not match the document timeline")
    return mapping


def media_payload(media: MediaItem, **extra: Any) -> dict[str, Any]:
    """The ``resolved`` block attached to a reference (same shape sets/grids use)."""
    payload = {
        "id": media.id,
        "media_id": media.id,
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
    payload.update(extra)
    return payload


def attach_resolved(doc: dict, resolved_by_role: dict[str, Optional[dict]]) -> dict:
    """Return a copy of ``doc`` with a ``resolved`` block on every reference."""
    result = json.loads(json.dumps(doc))
    for field in DOCUMENT_REF_FIELDS:
        ref = result.get(field)
        if _is_ref(ref):
            ref["resolved"] = resolved_by_role.get(field)
    for entry in result.get("animations") or []:
        if not isinstance(entry, dict):
            continue
        key = animation_key(entry)
        for field in ANIMATION_REF_FIELDS:
            ref = entry.get(field)
            if _is_ref(ref):
                ref["resolved"] = resolved_by_role.get(f"{key}/{field}")
    return result


async def resolve_sprite_content(session: AsyncSession, doc: dict) -> dict:
    """Content-endpoint shape for a sprite that has no normalized container.

    Used for scanned or not-yet-materialized documents; materialized sprites
    go through ``container_service.get_normalized_container_content`` so the
    revision's exact members are what gets reported.
    """
    resolved = {
        role: (media_payload(media) if media is not None else None)
        for role, media in (await resolve_sprite_refs(session, doc)).items()
    }
    return attach_resolved(doc, resolved)


async def resolved_sprite_content_for_media(
    session: AsyncSession, media_item: MediaItem
) -> Optional[dict]:
    """The document with ``resolved`` blocks, preferring the materialized revision's members.

    Falls back to id/hash resolution for scanned files and revisions whose
    members were never populated.
    """
    from container_service import get_normalized_container_content
    from structured_media import read_composite_content

    content = await get_normalized_container_content(session, container_media=media_item)
    if content is not None:
        return content
    doc = parse_sprite_document(await read_composite_content(session, media_item) or {})
    if doc is None:
        return None
    return await resolve_sprite_content(session, doc)


def _resolved_path(ref: Any) -> Optional[str]:
    if not isinstance(ref, dict):
        return None
    resolved = ref.get("resolved") or {}
    return resolved.get("file_path") or None


def sprite_thumbnail_sources(content: dict) -> dict[str, Any]:
    """Pick the files a thumbnail is built from, out of resolved content.

    Returns ``{"hero": path|None, "animation": path|None, "pending": bool}``.
    ``hero`` prefers the portrait, then the cut-out base, then the base.
    ``animation`` is the first move's artifact (idle first when present).
    ``pending`` is set when a referenced file is resolved but not on disk yet.
    """
    pending = False
    hero = None
    for field in ("portrait", "base_image_nobg", "base_image"):
        path = _resolved_path(content.get(field))
        if not path:
            continue
        if Path(path).exists():
            hero = path
            break
        pending = True

    animations = [a for a in (content.get("animations") or []) if isinstance(a, dict)]
    animations.sort(key=lambda a: 0 if (a.get("name") or "").lower() == "idle" else 1)
    animation = None
    for entry in animations:
        path = _resolved_path(entry.get("animation"))
        if not path:
            continue
        if Path(path).exists():
            animation = path
            break
        pending = True
    return {"hero": hero, "animation": animation, "pending": pending}

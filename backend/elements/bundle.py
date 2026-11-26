"""Committing and reading element revisions.

``commit_element`` turns a working directory (``element.json``, ``ELEMENT.md``,
``files/``) into an immutable ``.stimmaelement`` bundle, registers it as Media
in managed storage, and creates the ``element`` Asset or advances it by one
revision. Each ``media_menu`` entry becomes one ContainerMember: linked library
Assets by default (never owned by the element), embedded Media when asked.
"""

from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from core.logging import get_logger
from database import Asset, AssetRevision, ContainerMember, MediaItem
from elements import template
from elements.manifest import (
    ELEMENT_ASSET_TYPE,
    ELEMENT_EXTENSION,
    ELEMENT_FORMAT,
    FILES_DIR,
    INSTRUCTIONS_NAME,
    MANIFEST_FORMAT_VERSION,
    MANIFEST_NAME,
    TILE_NAME,
    ElementManifestError,
    check_file_path,
    parse_manifest,
    read_manifest,
    slugify,
    validate_manifest,
    write_manifest,
)

log = get_logger(__name__)

TILE_SIZE = 512
IMAGE_FORMATS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}


class ElementError(ValueError):
    """A save or edit that can't go ahead, in words the agent or user can act on."""


class ElementNotFound(ElementError):
    pass


class ElementConflict(ElementError):
    pass


@dataclass
class SaveResult:
    asset: Asset
    revision: AssetRevision
    media: MediaItem
    created: bool
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


# Reading ----------------------------------------------------------------------

async def element_asset(session: AsyncSession, asset_id: int) -> tuple[Asset, AssetRevision, MediaItem]:
    """The live element Asset, its current revision and that revision's bundle Media."""
    asset = await session.get(Asset, int(asset_id))
    if (
        asset is None
        or asset.asset_type != ELEMENT_ASSET_TYPE
        or asset.deleted_at is not None
        or asset.state != "active"
        or asset.current_revision_id is None
    ):
        raise ElementNotFound(f"There is no element {asset_id}.")
    revision = await session.get(AssetRevision, asset.current_revision_id)
    media = await session.get(MediaItem, revision.primary_media_id) if revision is not None else None
    if revision is None or media is None or not Path(media.file_path).is_dir():
        raise ElementNotFound(f"Element {asset_id} has no saved content.")
    return asset, revision, media


def bundle_manifest(media: MediaItem) -> dict[str, Any]:
    manifest = parse_manifest(media.raw_metadata or "")
    if manifest is None:
        manifest = read_manifest(Path(media.file_path))
    return manifest


def bundle_instructions(media: MediaItem) -> str:
    path = Path(media.file_path) / INSTRUCTIONS_NAME
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return ""


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            after = text.find("\n", end + 4)
            return text[after + 1:] if after != -1 else ""
    return text


def safe_bundle_file(media: MediaItem, rel_path: str) -> Optional[Path]:
    """A companion file inside the bundle, or None. Only ``files/`` is served."""
    try:
        rel = check_file_path(rel_path)
    except ElementManifestError:
        return None
    bundle = Path(media.file_path).resolve()
    target = (bundle / rel).resolve()
    if not target.is_relative_to(bundle) or not target.is_file():
        return None
    return target


async def _member_rows(session: AsyncSession, revision_id: int) -> dict[str, ContainerMember]:
    rows = await session.scalars(
        select(ContainerMember).where(
            ContainerMember.container_revision_id == revision_id,
            ContainerMember.deleted_at.is_(None),
        )
    )
    return {row.title or "": row for row in rows}


async def element_detail(session: AsyncSession, asset_id: int) -> dict[str, Any]:
    """Everything a viewer, the chat card or the agent needs about one element."""
    from container_service import resolve_container_members

    asset, revision, media = await element_asset(session, asset_id)
    manifest = bundle_manifest(media)
    raw = bundle_instructions(media)
    display = template.strip_blocks(strip_frontmatter(raw))
    resolved = {entry["title"] or "": entry for entry in await resolve_container_members(session, revision_id=revision.id)}
    media_ids = [e["media_id"] for e in resolved.values() if e["media_id"] is not None]
    media_by_id = {
        m.id: m for m in await session.scalars(select(MediaItem).where(MediaItem.id.in_(media_ids)))
    } if media_ids else {}
    cover_key = manifest.get("cover_member_key")
    menu_out = []
    cover = None
    for entry in manifest.get("media_menu") or []:
        key = entry.get("key")
        slot = resolved.get(key) or {}
        item = media_by_id.get(slot.get("media_id")) if not slot.get("unavailable") else None
        if item is not None and (item.deleted_at is not None or item.deletion_pending_at is not None):
            item = None
        row = {
            "key": key,
            "title": entry.get("title") or "",
            "labels": list(entry.get("labels") or []),
            "status": entry.get("status") or "canonical",
            "provenance": entry.get("provenance"),
            "conditional": bool(entry.get("conditional", False)),
            "usage_hint": entry.get("usage_hint") or "",
            "asset_id": slot.get("linked_asset_id"),
            "media_id": item.id if item else None,
            "revision_id": slot.get("revision_id"),
            "file_format": item.file_format if item else None,
            "file_hash": item.file_hash if item else None,
            "width": item.width if item else None,
            "height": item.height if item else None,
            "missing": item is None,
            "is_cover": key == cover_key,
        }
        menu_out.append(row)
        if key == cover_key:
            cover = {"key": key, "media_id": row["media_id"], "asset_id": row["asset_id"], "missing": row["missing"]}
    files_out = []
    for entry in manifest.get("files") or []:
        target = safe_bundle_file(media, entry.get("path", ""))
        files_out.append({
            "path": entry.get("path"),
            "name": Path(entry.get("path") or "").name,
            "label": entry.get("label") or "",
            "mime_type": entry.get("mime_type") or mimetypes.guess_type(entry.get("path") or "")[0],
            "size": target.stat().st_size if target else None,
        })
    updated = max(asset.updated_at, revision.created_at)
    return {
        "asset_id": asset.id,
        "revision_id": revision.id,
        "revision_number": revision.revision_number,
        "media_id": media.id,
        "name": asset.title or manifest.get("name") or "Untitled element",
        "slug": manifest.get("slug") or slugify(asset.title or ""),
        "kind": manifest.get("kind") or "",
        "description": manifest.get("description") or "",
        "tags": list(manifest.get("tags") or []),
        "cover": cover,
        "has_tile": (Path(media.file_path) / TILE_NAME).is_file(),
        "instructions": raw,
        "instructions_display": display.text,
        "instructions_valid": display.valid,
        "referenced_vars": sorted(display.referenced_vars),
        "media": menu_out,
        "loras": [dict(entry) for entry in manifest.get("loras") or []],
        "files": files_out,
        "created_at": asset.created_at.isoformat(),
        "updated_at": updated.isoformat(),
    }


async def list_elements(
    session: AsyncSession,
    *,
    kind: Optional[str] = None,
    query: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Live elements, most recently updated first."""
    from database import ProjectAsset

    stmt = (
        select(Asset, AssetRevision, MediaItem)
        .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
        .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
        .where(
            Asset.asset_type == ELEMENT_ASSET_TYPE,
            Asset.deleted_at.is_(None),
            Asset.state == "active",
        )
        .order_by(Asset.updated_at.desc(), Asset.id.desc())
    )
    if project_id is not None:
        stmt = stmt.join(ProjectAsset, ProjectAsset.asset_id == Asset.id).where(
            ProjectAsset.project_id == project_id, ProjectAsset.deleted_at.is_(None)
        )
    out = []
    needle = (query or "").strip().lower()
    for asset, revision, media in (await session.execute(stmt)).all():
        manifest = parse_manifest(media.raw_metadata or "") or {}
        element_kind = (manifest.get("kind") or "").lower()
        if kind and element_kind != kind.strip().lower():
            continue
        name = asset.title or manifest.get("name") or "Untitled element"
        if needle:
            haystack = " ".join([name, element_kind, manifest.get("description") or "", *(manifest.get("tags") or [])]).lower()
            if needle not in haystack:
                continue
        menu = manifest.get("media_menu") or []
        out.append({
            "asset_id": asset.id,
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "media_id": media.id,
            "name": name,
            "slug": manifest.get("slug") or slugify(name),
            "kind": element_kind,
            "description": manifest.get("description") or "",
            "media_count": len(menu),
            "canonical_count": sum(1 for e in menu if (e.get("status") or "canonical") == "canonical"),
            "lora_count": len(manifest.get("loras") or []),
            "file_count": len(manifest.get("files") or []),
            "cover_member_key": manifest.get("cover_member_key"),
            "created_at": asset.created_at.isoformat(),
            "updated_at": max(asset.updated_at, revision.created_at).isoformat(),
        })
        if len(out) >= limit:
            break
    return out


# Membership ---------------------------------------------------------------------

def element_member_specs(manifest: dict[str, Any], missing_keys: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """One container member per media slot, in menu order, keyed by ``title``."""
    specs = []
    for entry in manifest.get("media_menu") or []:
        key = entry.get("key")
        if key in missing_keys:
            spec: dict[str, Any] = {"missing_linked_asset": True}
        elif entry.get("embedded_media_id") is not None:
            spec = {"embedded_media_id": int(entry["embedded_media_id"])}
        else:
            spec = {"linked_asset_id": int(entry["asset_id"])}
        spec["title"] = key
        spec["caption"] = entry.get("usage_hint") or None
        spec["member_metadata"] = json.dumps({
            "key": key,
            "labels": list(entry.get("labels") or []),
            "status": entry.get("status") or "canonical",
            "provenance": entry.get("provenance"),
            "conditional": bool(entry.get("conditional", False)),
        })
        specs.append(spec)
    return specs


async def _live_asset_media(session: AsyncSession, asset_id: int) -> tuple[Optional[Asset], Optional[MediaItem]]:
    asset = await session.get(Asset, int(asset_id))
    if asset is None or asset.deleted_at is not None or asset.state != "active" or asset.current_revision_id is None:
        return asset, None
    revision = await session.get(AssetRevision, asset.current_revision_id)
    if revision is None or revision.deleted_at is not None:
        return asset, None
    media = await session.get(MediaItem, revision.primary_media_id)
    if media is None or media.deleted_at is not None or media.deletion_pending_at is not None:
        return asset, None
    return asset, media


async def slot_media(session: AsyncSession, entry: dict[str, Any]) -> Optional[MediaItem]:
    """The Media a menu slot shows now: the linked Asset's current payload, or the embedded copy."""
    if entry.get("embedded_media_id") is not None:
        media = await session.get(MediaItem, int(entry["embedded_media_id"]))
        if media is None or media.deleted_at is not None or media.deletion_pending_at is not None:
            return None
        return media
    if entry.get("asset_id") is None:
        return None
    _asset, media = await _live_asset_media(session, int(entry["asset_id"]))
    return media


# Committing --------------------------------------------------------------------

def _collect_files(source_dir: Path) -> list[str]:
    root = source_dir / FILES_DIR
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise ElementError("files/ must be a folder")
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ElementError(f"{path.relative_to(source_dir).as_posix()} is a link; companion files must be real files")
        if path.is_file():
            out.append(check_file_path(path.relative_to(source_dir).as_posix()))
    return out


def _tile_png(path: Path) -> Optional[bytes]:
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA")
            img.thumbnail((TILE_SIZE, TILE_SIZE), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.info(f"element tile skipped for {path.name}: {exc}")
        return None


async def commit_element(
    session: AsyncSession,
    *,
    profile_id: str,
    source_dir: Path,
    asset_id: Optional[int] = None,
    base_revision_id: Optional[int] = None,
    force: bool = False,
    note: Optional[str] = None,
    origin_type: str = "element",
    project_id: Optional[int] = None,
) -> SaveResult:
    """Validate ``source_dir`` and commit it as a new immutable element revision.

    With ``asset_id`` this advances that element; ``base_revision_id`` is the
    revision the edits started from, and a newer current revision is a
    conflict unless ``force``. Without it, a new element Asset is created.
    """
    source_dir = Path(source_dir)
    warnings: list[str] = []
    try:
        manifest = read_manifest(source_dir)
    except ElementManifestError as exc:
        raise ElementError(str(exc)) from exc
    errors, manifest_warnings = validate_manifest(manifest)
    warnings += manifest_warnings
    if errors:
        raise ElementError("element.json has problems: " + "; ".join(errors))

    instructions_path = source_dir / INSTRUCTIONS_NAME
    try:
        instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.is_file() else ""
    except UnicodeDecodeError as exc:
        raise ElementError(f"{INSTRUCTIONS_NAME} must be UTF-8 text") from exc
    if not instructions.strip():
        warnings.append(f"{INSTRUCTIONS_NAME} is empty")
    problem = template.check(instructions)
    if problem:
        raise ElementError(f"{INSTRUCTIONS_NAME} has a broken condition block: {problem}")
    unknown = sorted(template.referenced_vars(instructions) - template.STANDARD_VARIABLES)
    if unknown:
        warnings.append(
            f"{INSTRUCTIONS_NAME} uses {', '.join(unknown)}, which no surface sets, so those conditions are always false"
        )

    asset: Optional[Asset] = None
    previous: Optional[dict[str, Any]] = None
    previous_rows: dict[str, ContainerMember] = {}
    if asset_id is not None:
        asset, current, current_media = await element_asset(session, asset_id)
        if not force and base_revision_id is not None and base_revision_id != current.id:
            raise ElementConflict(
                f"'{asset.title}' changed since these edits started (it is now version "
                f"{current.revision_number}). Open it again to get the latest, or save with force to replace it."
            )
        previous = bundle_manifest(current_media)
        previous_rows = await _member_rows(session, current.id)

    # Every media slot must point at something live. A slot carried over from
    # the previous revision whose asset has since left the library stays as an
    # empty slot rather than blocking the save.
    missing_keys: set[str] = set()
    for entry in manifest.get("media_menu") or []:
        key = entry["key"]
        if entry.get("embedded_media_id") is not None:
            if await slot_media(session, entry) is None:
                raise ElementError(f"media '{key}': media {entry['embedded_media_id']} is not in the library")
            continue
        linked, media = await _live_asset_media(session, int(entry["asset_id"]))
        if linked is not None and linked.asset_type == ELEMENT_ASSET_TYPE:
            raise ElementError(f"media '{key}': asset {entry['asset_id']} is an element; elements can't contain other elements")
        if media is None:
            row = previous_rows.get(key)
            carried = row is not None and (
                row.missing_linked_asset or (row.linked_asset_id is not None and int(row.linked_asset_id) == int(entry["asset_id"]))
            )
            if carried:
                missing_keys.add(key)
                warnings.append(f"media '{key}' is no longer in the library; its slot is kept empty")
                continue
            raise ElementError(f"media '{key}': asset {entry['asset_id']} is not in the library")

    file_paths = _collect_files(source_dir)
    listed = {check_file_path(e["path"]): e for e in manifest.get("files") or []}
    files_out = []
    for path in file_paths:
        entry = dict(listed.pop(path, None) or {"path": path})
        entry["path"] = path
        entry.setdefault("mime_type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        files_out.append(entry)
    for path in listed:
        warnings.append(f"{path} is listed in element.json but missing from files/; it was dropped")

    name = manifest["name"].strip()
    clean = dict(manifest)
    clean.update({
        "format": MANIFEST_FORMAT_VERSION,
        "name": name,
        "slug": manifest.get("slug") or slugify(name),
        "kind": (manifest.get("kind") or "").strip().lower(),
        "description": (manifest.get("description") or "").strip(),
        "tags": list(manifest.get("tags") or []),
        "cover_member_key": manifest.get("cover_member_key"),
        "media_menu": [
            {
                **entry,
                "labels": list(entry.get("labels") or []),
                "status": entry.get("status") or "canonical",
                "conditional": bool(entry.get("conditional", False)),
            }
            for entry in manifest.get("media_menu") or []
        ],
        "loras": [dict(e) for e in manifest.get("loras") or []],
        "files": files_out,
    })

    tile: Optional[bytes] = None
    cover_key = clean.get("cover_member_key")
    if cover_key and cover_key not in missing_keys:
        entry = next(e for e in clean["media_menu"] if e["key"] == cover_key)
        cover_media = await slot_media(session, entry)
        if cover_media is not None and (cover_media.file_format or "").lower() in IMAGE_FORMATS:
            tile = await asyncio.to_thread(_tile_png, Path(cover_media.file_path))
        elif cover_media is not None:
            warnings.append(f"cover '{cover_key}' is not a still image, so the library card has no picture")

    staging = app_dirs.get_managed_staging_dir(profile_id, "generated")
    staging.mkdir(parents=True, exist_ok=True)
    bundle = Path(tempfile.mkdtemp(prefix=f"{clean['slug']}-", suffix=ELEMENT_EXTENSION, dir=staging))

    def assemble() -> None:
        write_manifest(bundle, clean)
        (bundle / INSTRUCTIONS_NAME).write_text(instructions, encoding="utf-8")
        for entry in files_out:
            dst = bundle / entry["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_dir / entry["path"], dst)
        if tile:
            (bundle / TILE_NAME).write_bytes(tile)

    try:
        await asyncio.to_thread(assemble)
    except Exception:
        shutil.rmtree(bundle, ignore_errors=True)
        raise

    media = await _register_bundle(session, bundle=bundle, manifest=clean, profile_id=profile_id, origin_type=origin_type)
    from container_service import commit_container_revision, create_container_asset_from_media

    specs = element_member_specs(clean, missing_keys)
    created = asset is None
    if created:
        asset = await create_container_asset_from_media(
            session,
            media_id=media.id,
            container_type=ELEMENT_ASSET_TYPE,
            members=specs,
            title=name,
            origin_type=origin_type,
            idempotency_key=f"element:media:{media.id}",
        )
        if project_id is not None:
            from asset_association_service import attach_asset_to_project

            await attach_asset_to_project(session, project_id, asset.id)
        revision = await session.get(AssetRevision, asset.current_revision_id)
    else:
        revision = await commit_container_revision(
            session,
            asset_id=asset.id,
            media_id=media.id,
            members=specs,
            parent_revision_id=asset.current_revision_id,
            note=note,
            idempotency_key=f"element:revision:{asset.id}:{media.id}",
        )
        # A name edited in element.json is a rename; otherwise the Asset title
        # (which a rename in the library may have changed) stays the authority.
        if previous is not None and name != (previous.get("name") or "").strip():
            asset.title = name
        asset.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(asset)
    from storage_service import cleanup_staged_source

    await cleanup_staged_source(session, media_id=media.id)
    try:
        from utils.websocket import ws_manager

        await ws_manager.broadcast("media_added", {"media_id": media.id, "count": 1})
    except Exception as exc:  # noqa: BLE001
        log.debug(f"element media_added broadcast skipped: {exc}")
    return SaveResult(asset=asset, revision=revision, media=media, created=created, warnings=warnings, manifest=clean)


async def _register_bundle(
    session: AsyncSession, *, bundle: Path, manifest: dict[str, Any], profile_id: str, origin_type: str
) -> MediaItem:
    from config_version import get_config_version_manager
    from generation_metadata import dump_generation_metadata
    from packages.manifest import sha256_file
    from storage_service import stage_managed_media

    now = datetime.utcnow()
    anchor = bundle / MANIFEST_NAME
    media = MediaItem(
        file_path=str(bundle),
        file_hash=sha256_file(anchor),  # replaced by the whole-bundle hash on staging
        file_size=anchor.stat().st_size,
        file_format=ELEMENT_FORMAT,
        original_filename=f"{manifest['slug']}{ELEMENT_EXTENSION}",
        created_date=now,
        modified_date=now,
        indexed_date=now,
        metadata_status="completed",
        metadata_processed_at=now,
        metadata_config_version=get_config_version_manager().get_version("metadata"),
        width=0,
        height=0,
        megapixels=0.0,
        has_alpha=False,
        clip_status="skipped",
        face_detection_status="skipped",
        raw_metadata=json.dumps(manifest),
        generation_metadata=dump_generation_metadata(task_type="element", source=origin_type),
    )
    session.add(media)
    await session.flush()
    await stage_managed_media(session, media=media, profile_id=profile_id, remove_source=True)
    await session.flush()
    return media


async def copy_bundle_to(media: MediaItem, destination: Path) -> None:
    """Copy a revision's editable content (manifest, instructions, files) into ``destination``."""
    src = Path(media.file_path)

    def run() -> None:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / MANIFEST_NAME, destination / MANIFEST_NAME)
        if (src / INSTRUCTIONS_NAME).is_file():
            shutil.copyfile(src / INSTRUCTIONS_NAME, destination / INSTRUCTIONS_NAME)
        else:
            (destination / INSTRUCTIONS_NAME).write_text("", encoding="utf-8")
        files_dst = destination / FILES_DIR
        if files_dst.exists():
            shutil.rmtree(files_dst)
        if (src / FILES_DIR).is_dir():
            shutil.copytree(src / FILES_DIR, files_dst)
        else:
            files_dst.mkdir()
        for path in files_dst.rglob("*"):
            if path.is_file():
                os.chmod(path, 0o644)

    await asyncio.to_thread(run)


async def update_element(
    session: AsyncSession,
    *,
    profile_id: str,
    asset_id: int,
    name: Optional[str] = None,
    cover_member_key: Optional[str] = None,
    base_revision_id: Optional[int] = None,
) -> dict[str, Any]:
    """The viewer's direct edits: rename, and set the cover from the element's own media."""
    asset, revision, media = await element_asset(session, asset_id)
    if base_revision_id is not None and base_revision_id != revision.id:
        raise ElementConflict(f"'{asset.title}' changed since it was opened. Reload it and try again.")
    if name is not None:
        clean = name.strip()
        if not clean:
            raise ElementError("A name can't be empty.")
        asset.title = clean
        asset.updated_at = datetime.utcnow()
        await session.commit()
    if cover_member_key is not None:
        manifest = bundle_manifest(media)
        if cover_member_key == manifest.get("cover_member_key"):
            return await element_detail(session, asset_id)
        keys = {e.get("key") for e in manifest.get("media_menu") or []}
        if cover_member_key not in keys:
            raise ElementError(f"'{cover_member_key}' is not one of this element's media.")
        scratch = Path(tempfile.mkdtemp(prefix="stimma-element-edit-"))
        try:
            await copy_bundle_to(media, scratch)
            edited = read_manifest(scratch)
            edited["cover_member_key"] = cover_member_key
            edited["name"] = asset.title or edited.get("name")
            write_manifest(scratch, edited)
            await commit_element(
                session,
                profile_id=profile_id,
                source_dir=scratch,
                asset_id=asset.id,
                base_revision_id=revision.id,
                note="Set cover",
                origin_type="element_viewer",
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    return await element_detail(session, asset_id)

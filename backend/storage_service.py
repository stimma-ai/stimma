"""Reference-aware managed object storage for Media payloads."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from core.logging import get_logger
from database import ManagedArtifact, MediaItem, StorageObject
from trash_service import TrashService

log = get_logger(__name__)


class StorageServiceError(RuntimeError):
    pass


def managed_object_root(profile_id: str) -> Path:
    return app_dirs.get_profile_dir(profile_id) / "objects"


def object_key_for_hash(file_hash: str) -> str:
    return f"sha256/{file_hash[:2]}/{file_hash[2:4]}/{file_hash}"


def object_path(profile_id: str, object_key: str) -> Path:
    return managed_object_root(profile_id) / object_key


def media_compatibility_path(profile_id: str, media_id: int, filename: str) -> Path:
    safe_name = Path(filename).name or "payload"
    return managed_object_root(profile_id) / "media" / str(media_id) / safe_name


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_files(path: Path) -> list[Path]:
    files = []
    for candidate in path.rglob("*"):
        if candidate.is_symlink():
            raise StorageServiceError("Managed directory payload cannot contain symlinks")
        if candidate.is_file():
            files.append(candidate)
    return sorted(files, key=lambda candidate: candidate.relative_to(path).as_posix())


def _hash_payload(path: Path) -> str:
    if path.is_file():
        return _hash_file(path)
    if not path.is_dir():
        raise StorageServiceError("Managed source payload is unavailable")
    digest = hashlib.sha256()
    # Domain-separate directory bundles from ordinary file hashes. An empty
    # directory must not alias an empty file in the content-addressed store.
    digest.update(b"stimma-directory-v1\0")
    for candidate in _directory_files(path):
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _payload_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(candidate.stat().st_size for candidate in _directory_files(path))


def _install_verified(source: Path, destination: Path, expected_hash: str) -> None:
    if destination.exists():
        if _hash_payload(destination) != expected_hash:
            raise StorageServiceError("Managed object hash mismatch")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_root = destination.parents[3] / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp = temp_root / uuid.uuid4().hex
    try:
        if source.is_dir():
            shutil.copytree(source, temp)
            for copied in _directory_files(temp):
                with copied.open("rb") as handle:
                    os.fsync(handle.fileno())
        else:
            with source.open("rb") as src, temp.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
        if _hash_payload(temp) != expected_hash:
            raise StorageServiceError("Source changed during managed-object ingest")
        os.replace(temp, destination)
    finally:
        if temp.is_dir() and not temp.is_symlink():
            shutil.rmtree(temp, ignore_errors=True)
        else:
            temp.unlink(missing_ok=True)


def _install_media_link(destination: Path, compatibility_path: Path) -> None:
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    if compatibility_path.exists() or compatibility_path.is_symlink():
        if compatibility_path.is_dir() and not compatibility_path.is_symlink():
            shutil.rmtree(compatibility_path)
        else:
            compatibility_path.unlink()
    if destination.is_dir():
        compatibility_path.symlink_to(destination, target_is_directory=True)
        return
    try:
        os.link(destination, compatibility_path)
    except OSError:
        # A symlink still shares the one canonical byte object and works across
        # filesystems where hard links are unavailable.
        compatibility_path.symlink_to(destination)


def _install_editor_sidecar(source: Path, compatibility_path: Path) -> None:
    """Atomically preserve a legacy editor sidecar beside managed Media.

    Editor projects historically lived next to their payload.  The primary
    object is content-addressed, but the mutable project belongs beside the
    per-Media compatibility path and must be installed before the database
    starts pointing there.
    """
    source_sidecar = Path(f"{source}.stimmaedit.json")
    if not source_sidecar.is_file():
        return
    destination = Path(f"{compatibility_path}.stimmaedit.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_hash = _hash_file(source_sidecar)
    if destination.is_file() and _hash_file(destination) == expected_hash:
        return
    temp = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    try:
        with source_sidecar.open("rb") as src, temp.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if _hash_file(temp) != expected_hash:
            raise StorageServiceError("Editor sidecar changed during managed-object ingest")
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


async def stage_managed_media(
    session: AsyncSession,
    *,
    media: MediaItem,
    profile_id: str,
    remove_source: bool = True,
) -> StorageObject:
    """Install bytes before transaction commit and index cleanup work.

    The caller commits the Media/StorageObject/ManagedArtifact transaction, then
    calls ``cleanup_staged_source``. A crash leaves an indexed artifact rather
    than an invisible duplicate.
    """
    if media.deletion_pending_at is not None:
        raise StorageServiceError("Media deletion is in progress")
    # Acquire SQLite's write reservation and re-check the barrier in the
    # database before touching disk. A stale WAL reader now fails before
    # installing an object or compatibility link.
    reservation = await session.execute(
        update(MediaItem)
        .where(
            MediaItem.id == media.id,
            MediaItem.deletion_pending_at.is_(None),
        )
        .values(indexed_date=MediaItem.indexed_date)
        .returning(MediaItem.id)
    )
    if reservation.scalar_one_or_none() is None:
        raise StorageServiceError("Media deletion is in progress")
    if media.storage_object_id is not None:
        storage = await session.get(StorageObject, media.storage_object_id)
        if storage is None:
            raise StorageServiceError("Media has a dangling StorageObject")
        if storage.kind == "managed":
            if storage.state == "deleting":
                raise StorageServiceError("Managed object deletion is in progress")
            return storage
        # Generation may win a race with folder ingestion, which initially
        # classified the just-written output as external. Convert explicitly.
        old_storage_id = storage.id
        media.storage_object_id = None
        await session.flush()
        other_ref = await session.scalar(
            select(MediaItem.id).where(
                MediaItem.storage_object_id == old_storage_id
            ).limit(1)
        )
        if other_ref is None:
            await session.delete(storage)
            await session.flush()
    source = Path(media.file_path)
    if not source.is_file() and not source.is_dir():
        raise StorageServiceError("Managed source file is unavailable")
    actual_hash = await asyncio.to_thread(_hash_payload, source)
    if source.is_dir():
        # Historical layout rows hashed index.html only. Managed identity covers
        # the complete self-contained bundle, including referenced resources.
        media.file_hash = actual_hash
        media.file_size = await asyncio.to_thread(_payload_size, source)
    elif actual_hash != media.file_hash:
        raise StorageServiceError("Media hash does not match source bytes")
    key = object_key_for_hash(actual_hash)
    storage = await session.scalar(
        select(StorageObject).where(
            StorageObject.kind == "managed",
            StorageObject.object_key == key,
        )
    )
    if storage is not None and storage.state == "deleting":
        raise StorageServiceError("Managed object deletion is in progress")

    destination = object_path(profile_id, key)
    await asyncio.to_thread(_install_verified, source, destination, actual_hash)
    if storage is None:
        storage = StorageObject(
            kind="managed",
            object_key=key,
            expected_hash=actual_hash,
            file_size=media.file_size,
            mime_type=mimetypes.guess_type(media.original_filename or source.name)[0],
            state="available",
            verified_at=datetime.utcnow(),
        )
        session.add(storage)
        await session.flush()
    elif storage.deleted_at is not None:
        storage.deleted_at = None
        storage.state = "available"
        storage.verified_at = datetime.utcnow()
    media.original_filename = media.original_filename or source.name
    compatibility_path = media_compatibility_path(
        profile_id, media.id, media.original_filename
    )
    await asyncio.to_thread(_install_media_link, destination, compatibility_path)
    await asyncio.to_thread(_install_editor_sidecar, source, compatibility_path)
    media.storage_object_id = storage.id
    media.file_path = str(compatibility_path)
    if remove_source and source.resolve() not in {
        destination.resolve(), compatibility_path.resolve()
    }:
        session.add(ManagedArtifact(
            owner_kind="media",
            owner_id=str(media.id),
            media_id=media.id,
            artifact_kind="ingest_source",
            locator=str(source),
            state="available",
        ))
    await session.flush()
    return storage


async def register_external_media(
    session: AsyncSession,
    *,
    media: MediaItem,
) -> StorageObject:
    """Record a watched/user-owned locator without moving or owning its bytes."""
    if media.storage_object_id is not None:
        storage = await session.get(StorageObject, media.storage_object_id)
        if storage is None:
            raise StorageServiceError("Media has a dangling StorageObject")
        return storage
    media.original_filename = media.original_filename or Path(media.file_path).name
    storage = StorageObject(
        kind="external",
        external_path=media.file_path,
        expected_hash=media.file_hash,
        file_size=media.file_size,
        mime_type=mimetypes.guess_type(media.original_filename)[0],
        state="available" if Path(media.file_path).exists() else "missing",
        verified_at=datetime.utcnow() if Path(media.file_path).exists() else None,
    )
    session.add(storage)
    await session.flush()
    media.storage_object_id = storage.id
    return storage


async def register_external_asset(
    session: AsyncSession,
    *,
    media: MediaItem,
):
    """Register watched bytes and give the user-addressable item Asset identity."""
    media_path = Path(media.file_path).expanduser().resolve(strict=False)
    if any(
        media_path == root or root in media_path.parents
        for root in app_dirs.get_all_stimma_owned_roots()
    ):
        # Defense in depth against a scanner/generation race. A private payload
        # may become generation-owned moments later, but it must never acquire a
        # second watched-file Asset identity.
        log.warning(
            "Refusing to register app-owned payload as watched Source media: %s",
            media.file_path,
        )
        return None, None

    from sqlalchemy.orm import aliased
    from asset_association_service import mirror_media_associations_to_asset
    from asset_service import commit_revision, create_asset_from_media
    from database import Asset, AssetRevision

    # Match trashed assets too: the user's curation is authoritative. Bytes
    # whose Asset sits in the trash must never resurface as a fresh active
    # Asset just because the scanner saw their file again.
    prior_media = aliased(MediaItem)
    existing = (
        await session.execute(
            select(Asset, prior_media)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .join(prior_media, prior_media.id == AssetRevision.primary_media_id)
            .where(
                # Trashed Assets carry deleted_at but still own their bytes;
                # matching them prevents resurrection as a fresh active Asset.
                or_(
                    (Asset.state == "active") & Asset.deleted_at.is_(None),
                    Asset.state == "trashed",
                ),
                prior_media.file_path == media.file_path,
                prior_media.id != media.id,
            )
            .order_by(Asset.updated_at.desc())
            .limit(1)
        )
    ).first()

    if existing is not None:
        existing_asset, prior_payload = existing
        if media.file_hash and media.file_hash == prior_payload.file_hash:
            # Identical bytes reappeared: this is availability, not history.
            # Restore the original payload in place and drop the duplicate —
            # unchanged files must never grow new revisions.
            prior_payload.file_unavailable = False
            prior_payload.file_unavailable_since = None
            media.deleted_at = datetime.utcnow()
            await session.flush()
            log.info(
                "Watched file reappeared unchanged; restored original media %s for asset %s",
                prior_payload.id,
                existing_asset.id,
            )
            return None, existing_asset

    storage = await register_external_media(session, media=media)
    if existing is not None:
        existing_asset, _prior_payload = existing
        await commit_revision(
            session,
            asset_id=existing_asset.id,
            media_id=media.id,
            note="Watched file changed",
            idempotency_key=f"watched-file:{media.id}:revision",
            allow_inactive=True,
        )
        asset = existing_asset
    else:
        asset = await create_asset_from_media(
            session,
            media_id=media.id,
            origin_type="watched_file",
            origin_id=media.file_path,
            idempotency_key=f"watched-file:{media.id}",
        )
    await mirror_media_associations_to_asset(
        session, media_id=media.id, asset_id=asset.id
    )
    return storage, asset


async def cleanup_staged_source(
    session: AsyncSession,
    *,
    media_id: int,
) -> int:
    """Remove committed ingest sources and scrub their sensitive locators."""
    artifacts = list(
        await session.scalars(
            select(ManagedArtifact).where(
                ManagedArtifact.media_id == media_id,
                ManagedArtifact.artifact_kind == "ingest_source",
                ManagedArtifact.deleted_at.is_(None),
            )
        )
    )
    for artifact in artifacts:
        await asyncio.to_thread(TrashService().permanently_delete, artifact.locator)
        await session.delete(artifact)
    await session.commit()
    return len(artifacts)


async def resolve_media_path(session: AsyncSession, media: MediaItem, profile_id: str) -> Path:
    if media.storage_object_id is None:
        return Path(media.file_path)
    storage = await session.get(StorageObject, media.storage_object_id)
    if storage is None or storage.deleted_at is not None:
        raise StorageServiceError("StorageObject is unavailable")
    if storage.kind == "managed":
        return Path(media.file_path)
    return Path(storage.external_path)


async def ensure_durable_snapshot_media(
    session: AsyncSession,
    *,
    media: MediaItem,
    profile_id: str,
) -> MediaItem:
    """Return managed Media suitable for a durable editor dependency."""
    if media.storage_object_id is not None:
        storage = await session.get(StorageObject, media.storage_object_id)
        if storage is not None and storage.kind == "managed":
            return media
    source = Path(media.file_path)
    if not source.is_file():
        raise StorageServiceError("External snapshot source is unavailable")
    staging = (
        managed_object_root(profile_id)
        / ".snapshot-staging"
        / f"{uuid.uuid4().hex}-{media.original_filename or source.name}"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(shutil.copy2, source, staging)
    clone = MediaItem(
        file_path=str(staging),
        file_hash=media.file_hash,
        file_size=media.file_size,
        file_format=media.file_format,
        original_filename=media.original_filename or source.name,
        width=media.width,
        height=media.height,
        megapixels=media.megapixels,
        duration=media.duration,
        has_alpha=media.has_alpha,
        audio_sample_rate=media.audio_sample_rate,
        audio_channels=media.audio_channels,
        audio_bit_depth=media.audio_bit_depth,
        audio_bitrate=media.audio_bitrate,
        audio_codec=media.audio_codec,
        created_date=media.created_date,
        modified_date=media.modified_date,
        indexed_date=datetime.utcnow(),
        metadata_status="completed",
        clip_status=media.clip_status,
        vlm_caption_status=media.vlm_caption_status,
        face_detection_status=media.face_detection_status,
        raw_metadata=media.raw_metadata,
        extracted_prompt=media.extracted_prompt,
        generation_metadata=media.generation_metadata,
        tool_id=media.tool_id,
        preset_id=media.preset_id,
    )
    session.add(clone)
    await session.flush()
    await stage_managed_media(
        session,
        media=clone,
        profile_id=profile_id,
        remove_source=True,
    )
    return clone


def _under_any_root(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


async def migrate_legacy_managed_media(
    session: AsyncSession,
    *,
    profile_id: str,
    managed_roots: list[Path],
    formats: set[str] | None = None,
    limit: int = 100,
) -> dict:
    """Incrementally move explicitly scoped legacy files into object storage.

    Callers must supply roots owned by Stimma (never watch/user folders). Each
    Media transition commits before its old source is removed, so interruption
    is recoverable and rerunning is idempotent.
    """
    query = select(MediaItem).where(
        MediaItem.storage_object_id.is_(None),
        MediaItem.deleted_at.is_(None),
        MediaItem.deletion_pending_at.is_(None),
    )
    if formats:
        query = query.where(MediaItem.file_format.in_(formats))
    query = query.order_by(MediaItem.id)
    if not formats:
        query = query.limit(limit * 4)
    candidates = list(await session.scalars(query))
    report = {"migrated": 0, "missing": 0, "skipped_external": 0, "errors": []}
    for media in candidates:
        if report["migrated"] >= limit:
            break
        source = Path(media.file_path)
        if not _under_any_root(source, managed_roots):
            report["skipped_external"] += 1
            continue
        if not source.is_file() and not source.is_dir():
            media.file_unavailable = True
            report["missing"] += 1
            await session.commit()
            continue
        try:
            await stage_managed_media(
                session,
                media=media,
                profile_id=profile_id,
                remove_source=True,
            )
            media.file_unavailable = False
            await session.commit()
            await cleanup_staged_source(session, media_id=media.id)
            report["migrated"] += 1
        except Exception as exc:  # one bad legacy file must not stop rehearsal
            await session.rollback()
            report["errors"].append(
                {"media_id": media.id, "error": type(exc).__name__}
            )
    return report


async def reconcile_storage(
    session: AsyncSession,
    *,
    profile_id: str,
    verify_hashes: bool = False,
    repair_states: bool = False,
) -> dict:
    """Compare Media locators, StorageObjects, and disk without inferring ownership."""
    report = {
        "dangling_media": [],
        "missing_managed": [],
        "corrupt_managed": [],
        "missing_external": [],
        "orphan_storage_objects": [],
    }
    media_rows = list(
        await session.scalars(
            select(MediaItem).where(
                MediaItem.storage_object_id.is_not(None),
                MediaItem.deleted_at.is_(None),
            )
        )
    )
    storage_by_id = {
        row.id: row
        for row in await session.scalars(
            select(StorageObject).where(StorageObject.deleted_at.is_(None))
        )
    }
    referenced_ids = set()
    for media in media_rows:
        storage = storage_by_id.get(media.storage_object_id)
        if storage is None:
            report["dangling_media"].append(media.id)
            continue
        referenced_ids.add(storage.id)
        locator = (
            object_path(profile_id, storage.object_key)
            if storage.kind == "managed"
            else Path(storage.external_path)
        )
        if not locator.is_file() and not locator.is_dir():
            key = "missing_managed" if storage.kind == "managed" else "missing_external"
            report[key].append(media.id)
            if repair_states:
                storage.state = "missing"
                media.file_unavailable = True
            continue
        if storage.kind == "managed" and verify_hashes:
            actual = await asyncio.to_thread(_hash_payload, locator)
            if actual != storage.expected_hash:
                report["corrupt_managed"].append(media.id)
                if repair_states:
                    storage.state = "missing"
                    media.file_unavailable = True
                continue
        if repair_states:
            storage.state = "available"
            storage.verified_at = datetime.utcnow()
            media.file_unavailable = False
    report["orphan_storage_objects"] = sorted(set(storage_by_id) - referenced_ids)
    report["counts"] = {
        "media_with_storage": len(media_rows),
        "live_storage_objects": len(storage_by_id),
        "shared_storage_objects": await session.scalar(
            select(func.count()).select_from(
                select(MediaItem.storage_object_id)
                .where(
                    MediaItem.storage_object_id.is_not(None),
                    MediaItem.deleted_at.is_(None),
                )
                .group_by(MediaItem.storage_object_id)
                .having(func.count(MediaItem.id) > 1)
                .subquery()
            )
        ) or 0,
    }
    if repair_states:
        await session.commit()
    return report

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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from database import ManagedArtifact, MediaItem, StorageObject
from trash_service import TrashService


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


def _install_verified(source: Path, destination: Path, expected_hash: str) -> None:
    if destination.exists():
        if _hash_file(destination) != expected_hash:
            raise StorageServiceError("Managed object hash mismatch")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_root = destination.parents[3] / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp = temp_root / uuid.uuid4().hex
    try:
        with source.open("rb") as src, temp.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        if _hash_file(temp) != expected_hash:
            raise StorageServiceError("Source changed during managed-object ingest")
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def _install_media_link(destination: Path, compatibility_path: Path) -> None:
    compatibility_path.parent.mkdir(parents=True, exist_ok=True)
    if compatibility_path.exists() or compatibility_path.is_symlink():
        compatibility_path.unlink()
    try:
        os.link(destination, compatibility_path)
    except OSError:
        # A symlink still shares the one canonical byte object and works across
        # filesystems where hard links are unavailable.
        compatibility_path.symlink_to(destination)


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
    if media.storage_object_id is not None:
        storage = await session.get(StorageObject, media.storage_object_id)
        if storage is None:
            raise StorageServiceError("Media has a dangling StorageObject")
        if storage.kind == "managed":
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
    if media.file_format in {"stimmaset.json", "stimmagrid.json", "stimmalayout"}:
        raise StorageServiceError("Structured compatibility payload is not object-store ready")
    source = Path(media.file_path)
    if not source.is_file():
        raise StorageServiceError("Managed source file is unavailable")
    actual_hash = await asyncio.to_thread(_hash_file, source)
    if actual_hash != media.file_hash:
        raise StorageServiceError("Media hash does not match source bytes")
    key = object_key_for_hash(actual_hash)
    destination = object_path(profile_id, key)
    await asyncio.to_thread(_install_verified, source, destination, actual_hash)

    storage = await session.scalar(
        select(StorageObject).where(
            StorageObject.kind == "managed",
            StorageObject.object_key == key,
        )
    )
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

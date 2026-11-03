"""Opaque companion ownership, portable manifests and generic media edit maps."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from fractions import Fraction

from sqlalchemy import delete, select, update
from database import MediaItem, MediaSidecar, StorageObject
from storage_service import StorageServiceError, object_path, stage_managed_object


async def attach_sidecars(session, *, media, sidecars, profile_id):
    # Acquire the same deletion barrier/write reservation as managed media ingest.
    reserved = await session.scalar(update(MediaItem).where(
        MediaItem.id == media.id, MediaItem.deletion_pending_at.is_(None),
    ).values(indexed_date=MediaItem.indexed_date).returning(MediaItem.id))
    if reserved is None:
        raise ValueError("Media deletion is in progress")
    for item in sidecars:
        record = dict(item.info)
        if not isinstance(record.get("format"), str) or not isinstance(record.get("format_version"), int):
            continue
        storage = None
        if item.data is not None:
            actual_hash = hashlib.sha256(item.data).hexdigest()
            if record.get("sha256") and record["sha256"] != actual_hash:
                record.update(status="unavailable", unavailable_reason="integrity_failed")
            elif record.get("byte_size") is not None and record["byte_size"] != len(item.data):
                record.update(status="unavailable", unavailable_reason="integrity_failed")
            else:
                try:
                    with tempfile.NamedTemporaryFile() as staged:
                        staged.write(item.data)
                        staged.flush()
                        storage = await stage_managed_object(session, source=staged.name, profile_id=profile_id,
                                                             mime_type=record.get("mime_type"), expected_hash=actual_hash)
                    record.update(sha256=actual_hash, byte_size=len(item.data), status="available")
                except (OSError, StorageServiceError):
                    record.update(status="unavailable", unavailable_reason="storage_failed")
        record.pop("asset_id", None)
        record.pop("file", None)
        mapping = record.pop("media_mapping", None)
        descriptor = record.pop("descriptor", {})
        identity = hashlib.sha256(json.dumps([record.get("format"), record.get("format_version"),
                                             record.get("sha256"), mapping, descriptor], sort_keys=True).encode()).hexdigest()
        existing = await session.scalar(select(MediaSidecar).where(MediaSidecar.media_id == media.id, MediaSidecar.identity_key == identity))
        if existing is not None and storage is None and existing.storage_object_id is not None:
            continue  # A transport retry cannot discard an already stored representation.
        if existing is None:
            existing = MediaSidecar(media_id=media.id, identity_key=identity)
            session.add(existing)
        existing.storage_object_id = storage.id if storage else None
        existing.format = record["format"]
        existing.format_version = record["format_version"]
        existing.descriptor_json = json.dumps(descriptor)
        existing.mapping_json = json.dumps(mapping) if mapping else None
        existing.info_json = json.dumps(record)
        existing.deleted_at = None
    await session.flush()


async def companions_for_media(session, media_id, profile_id, *, include_paths=True):
    rows = (await session.execute(select(MediaSidecar, StorageObject).outerjoin(
        StorageObject, StorageObject.id == MediaSidecar.storage_object_id,
    ).where(MediaSidecar.media_id == media_id, MediaSidecar.deleted_at.is_(None)))).all()
    records = []
    for row, storage in rows:
        record = {**json.loads(row.info_json), "format": row.format, "format_version": row.format_version,
                  "descriptor": json.loads(row.descriptor_json)}
        if row.mapping_json:
            record["media_mapping"] = json.loads(row.mapping_json)
        if storage is not None and storage.state == "available" and storage.deleted_at is None:
            path = object_path(profile_id, storage.object_key)
            if path.is_file():
                record["status"] = "available"
                if include_paths:
                    record["file"] = str(path)
            else:
                record.update(status="unavailable", unavailable_reason="local_missing")
        else:
            record.update(status="unavailable", unavailable_reason=record.get("unavailable_reason", "local_missing"))
        records.append(record)
    return records


def trim_mapping(mapping, start_frame, end_frame, fps, *, offset_frames=0, preserved_streams=None):
    try:
        return _trim_mapping(mapping, start_frame, end_frame, fps, offset_frames=offset_frames, preserved_streams=preserved_streams)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _trim_mapping(mapping, start_frame, end_frame, fps, *, offset_frames=0, preserved_streams=None):
    """Compose a pure trim/concat in media time, never in native sample units."""
    if not isinstance(mapping, dict) or mapping.get("version") != 1:
        return None
    rate = Fraction(fps)
    current = Fraction(mapping["media_time_base"]["num"], mapping["media_time_base"]["den"])
    original = Fraction(mapping["source_time_base"]["num"], mapping["source_time_base"]["den"])
    if current <= 0 or original <= 0 or rate <= 0:
        return None
    lo, hi = mapping["source_extent"]
    start, end = Fraction(start_frame) / rate, Fraction(end_frame) / rate
    spans = []
    for span in mapping["spans"]:
        a, b = (Fraction(t) * current for t in span["media"])
        x, y = span["source"]
        if not (0 <= a < b and 0 <= lo <= x < y <= hi):
            continue
        if b - a != (y - x) * original:
            continue
        left, right = max(start, a), min(end, b)
        streams = set(span["preserved_streams"])
        if preserved_streams is not None:
            streams.intersection_update(preserved_streams)
        if left >= right or not streams:
            continue
        ticks = [(left - start) * rate + offset_frames, (right - start) * rate + offset_frames,
                 x + (left - a) / original, x + (right - a) / original]
        if any(t.denominator != 1 for t in ticks):
            continue
        spans.append({"media": [int(ticks[0]), int(ticks[1])], "source": [int(ticks[2]), int(ticks[3])],
                      "preserved_streams": sorted(streams)})
    if not spans:
        return None
    return {**mapping, "media_time_base": {"num": rate.denominator, "den": rate.numerator}, "spans": spans}


async def summaries_by_media(session, media_ids):
    """Cheap library facts; full metadata and file checks are resolved on demand."""
    rows = (await session.execute(select(MediaSidecar, StorageObject).outerjoin(
        StorageObject, StorageObject.id == MediaSidecar.storage_object_id,
    ).where(MediaSidecar.media_id.in_(media_ids), MediaSidecar.deleted_at.is_(None)))).all()
    result = {}
    for row, storage in rows:
        info = json.loads(row.info_json)
        info.update(format=row.format, format_version=row.format_version,
                    status="available" if storage is not None and storage.state == "available" else "unavailable")
        result.setdefault(row.media_id, []).append(info)
    return result


async def purge_ephemeral_sidecars(session, media_ids, profile_id):
    """Remove run-scoped companions while respecting other byte owners."""
    import asyncio
    import shutil
    from database import ManagedArtifact
    storages = list(await session.scalars(select(StorageObject).join(
        MediaSidecar, MediaSidecar.storage_object_id == StorageObject.id,
    ).where(MediaSidecar.media_id.in_(media_ids)).distinct()))
    await session.execute(delete(MediaSidecar).where(MediaSidecar.media_id.in_(media_ids)))
    for storage in storages:
        primary = await session.scalar(select(MediaItem.id).where(MediaItem.storage_object_id == storage.id).limit(1))
        companion = await session.scalar(select(MediaSidecar.id).where(MediaSidecar.storage_object_id == storage.id).limit(1))
        if primary is None and companion is None:
            await asyncio.to_thread(object_path(profile_id, storage.object_key).unlink, missing_ok=True)
            await session.delete(storage)
    artifacts = list(await session.scalars(select(ManagedArtifact).where(
        ManagedArtifact.media_id.in_(media_ids), ManagedArtifact.artifact_kind == "generation_receipt")))
    for artifact in artifacts:
        path = Path(artifact.locator)
        if path.is_dir():
            await asyncio.to_thread(shutil.rmtree, path)
        else:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        await session.delete(artifact)


async def write_portable_manifest(primary, records):
    """Export reusable media with copies of opaque payloads, never writable CAS links."""
    import asyncio
    import shutil
    primary = Path(primary)
    entries = []
    directory = primary.parent / (primary.name + ".sidecars")
    for i, original in enumerate(records):
        entry = {k: v for k, v in original.items() if k not in ("file", "asset_id")}
        if original.get("status") != "unavailable":
            try:
                source = Path(original["file"])
                directory.mkdir(parents=True, exist_ok=True)
                dest = directory / f"state_{i}.bin"
                await asyncio.to_thread(shutil.copyfile, source, dest)
                raw = await asyncio.to_thread(dest.read_bytes)
                digest = hashlib.sha256(raw).hexdigest()
                if original.get("sha256") and original["sha256"] != digest:
                    raise ValueError("integrity_failed")
                entry.update(file=str(dest.relative_to(primary.parent)), sha256=digest, byte_size=len(raw))
            except (OSError, KeyError, ValueError):
                entry.pop("file", None)
                entry.update(status="unavailable", unavailable_reason="export_failed")
        entries.append(entry)
    if entries:
        from providers.result_receipt import atomic_json
        digest = hashlib.sha256(await asyncio.to_thread(primary.read_bytes)).hexdigest()
        atomic_json(str(primary) + ".stimma-sidecars.json", {"version": 1, "primary_sha256": digest, "sidecars": entries})


async def import_portable_manifest(session, *, media, source, profile_id):
    """Import only companions bound to these exact rendered bytes."""
    import asyncio
    from providers.base import OutputSidecar
    source = Path(source)
    manifest = Path(str(source) + ".stimma-sidecars.json")
    if not manifest.is_file():
        return
    try:
        data = json.loads(await asyncio.to_thread(manifest.read_text))
        actual = hashlib.sha256(await asyncio.to_thread(source.read_bytes)).hexdigest()
        if data.get("version") != 1 or data.get("primary_sha256") != actual or actual != media.file_hash:
            return
        parent = source.parent.resolve()
        companions = []
        for entry in data.get("sidecars", []):
            record = dict(entry)
            raw = None
            if record.get("status") != "unavailable":
                try:
                    relative = Path(record["file"])
                    path = (parent / relative).resolve()
                    if relative.is_absolute() or not path.is_relative_to(parent):
                        raise ValueError("invalid_companion_path")
                    raw = await asyncio.to_thread(path.read_bytes)
                except (OSError, KeyError, ValueError):
                    record.update(status="unavailable", unavailable_reason="local_missing")
            companions.append(OutputSidecar(record, raw))
        await attach_sidecars(session, media=media, sidecars=companions, profile_id=profile_id)
    except (OSError, ValueError, TypeError):
        # An optional companion manifest cannot invalidate healthy primary media.
        return

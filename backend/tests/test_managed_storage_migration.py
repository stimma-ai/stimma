"""Proofs for the explicit legacy-to-managed storage normalization."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select, text, update

from database import AssetRevision, MediaItem, StorageObject
from managed_storage_migration import apply_profile, build_parser, inspect_profile
from storage_service import register_external_media
from tests.helpers.media import create_media_item


def _write(path: Path, payload: bytes) -> str:
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_cli_parses_repeatable_legacy_root_flags(tmp_path):
    generated = tmp_path / "generated"
    uploads = generated / "uploads"
    args = build_parser().parse_args([
        "--data-dir",
        str(tmp_path),
        "--legacy-generated-root",
        str(generated),
        "--legacy-generated-root",
        str(tmp_path / "generated-two"),
        "--legacy-uploads-root",
        str(uploads),
    ])
    assert args.legacy_generated_roots == [generated, tmp_path / "generated-two"]
    assert args.legacy_upload_roots == [uploads]


@pytest.mark.asyncio
async def test_plan_only_selects_strong_stimma_owned_provenance(db_session, tmp_path):
    generated_path = tmp_path / "generated.png"
    watched_path = tmp_path / "watched.png"
    ambiguous_path = tmp_path / "from-another-stimma.png"
    generated_hash = _write(generated_path, b"generated")
    watched_hash = _write(watched_path, b"watched")
    ambiguous_hash = _write(ambiguous_path, b"ambiguous")

    async with db_session() as session:
        generated = await create_media_item(
            session,
            file_path=generated_path,
            file_hash=generated_hash,
            file_size=9,
            tool_id="builtin:test:generate",
            materialize_asset=True,
        )
        watched = await create_media_item(
            session,
            file_path=watched_path,
            file_hash=watched_hash,
            file_size=7,
        )
        ambiguous = await create_media_item(
            session,
            file_path=ambiguous_path,
            file_hash=ambiguous_hash,
            file_size=9,
            generation_metadata=json.dumps({
                "source": "stimma",
                "tool_id": "builtin:test:generate",
            }),
        )
        await register_external_media(session, media=generated)
        await register_external_media(session, media=watched)
        await session.commit()

        plan = await inspect_profile(session, profile_id="default")
        status_by_id = {
            record["media_id"]: record["status"] for record in plan["records"]
        }
        assert status_by_id[generated.id] == "eligible"
        assert status_by_id[watched.id] == "external_source"
        assert status_by_id[ambiguous.id] == "ambiguous_internal_metadata"
        # The module-scoped integration database is shared by the following
        # tests; retire this dry-run-only fixture without touching its files.
        await session.execute(
            update(MediaItem)
            .where(MediaItem.id.in_([generated.id, watched.id, ambiguous.id]))
            .values(deleted_at=datetime.utcnow())
        )
        await session.commit()


@pytest.mark.asyncio
async def test_apply_preserves_ids_history_and_editor_sidecar_and_is_resumable(
    db_session, tmp_path
):
    source = tmp_path / "legacy-edit.png"
    digest = _write(source, b"legacy-edit")
    sidecar = Path(f"{source}.stimmaedit.json")
    sidecar.write_text('{"version":1,"project":{"layers":[]}}', encoding="utf-8")

    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=source,
            file_hash=digest,
            file_size=11,
            tool_id="builtin:stimma:image-editor",
            materialize_asset=True,
        )
        media.has_editor_sidecar = True
        storage = await register_external_media(session, media=media)
        media_id = media.id
        external_storage_id = storage.id
        revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == media.id)
        )
        revision_id = revision.id
        asset_id = revision.asset_id
        await session.commit()

    result = await apply_profile(db_session, profile_id="default")
    assert result["migrated"] == 1
    assert result["errors"] == []
    assert not source.exists()
    assert not sidecar.exists()

    async with db_session() as session:
        migrated = await session.get(MediaItem, media_id)
        preserved_revision = await session.get(AssetRevision, revision_id)
        managed = await session.get(StorageObject, migrated.storage_object_id)
        assert migrated.id == media_id
        assert preserved_revision.asset_id == asset_id
        assert preserved_revision.primary_media_id == media_id
        assert managed.kind == "managed"
        assert migrated.storage_object_id != external_storage_id
        assert Path(migrated.file_path).exists()
        migrated_sidecar = Path(f"{migrated.file_path}.stimmaedit.json")
        assert migrated_sidecar.is_file()
        assert json.loads(migrated_sidecar.read_text()) == {
            "version": 1,
            "project": {"layers": []},
        }

    rerun = await apply_profile(db_session, profile_id="default")
    assert rerun["migrated"] == 0
    assert rerun["errors"] == []


@pytest.mark.asyncio
async def test_shared_watched_path_is_copied_but_not_removed(db_session, tmp_path):
    source = tmp_path / "shared.png"
    digest = _write(source, b"shared")

    async with db_session() as session:
        generated = await create_media_item(
            session,
            file_path=source,
            file_hash=digest,
            file_size=6,
            tool_id="builtin:test:generate",
            materialize_asset=True,
        )
        watched = await create_media_item(
            session,
            file_path=source,
            file_hash=digest,
            file_size=6,
        )
        await register_external_media(session, media=generated)
        await register_external_media(session, media=watched)
        generated_id = generated.id
        watched_id = watched.id
        await session.commit()

    result = await apply_profile(db_session, profile_id="default")
    assert result["migrated"] == 1
    assert result["source_groups_removed"] == 0
    assert source.exists()

    async with db_session() as session:
        generated = await session.get(MediaItem, generated_id)
        watched = await session.get(MediaItem, watched_id)
        generated_storage = await session.get(StorageObject, generated.storage_object_id)
        watched_storage = await session.get(StorageObject, watched.storage_object_id)
        assert generated_storage.kind == "managed"
        assert watched_storage.kind == "external"
        assert Path(watched.file_path) == source


@pytest.mark.asyncio
async def test_hash_mismatch_and_missing_sidecar_block_apply(db_session, tmp_path):
    changed = tmp_path / "changed.png"
    _write(changed, b"new bytes")
    missing_sidecar = tmp_path / "missing-sidecar.png"
    sidecar_digest = _write(missing_sidecar, b"edit")

    async with db_session() as session:
        mismatched = await create_media_item(
            session,
            file_path=changed,
            file_hash=hashlib.sha256(b"old bytes").hexdigest(),
            file_size=9,
            tool_id="builtin:test:generate",
            materialize_asset=True,
        )
        flagged = await create_media_item(
            session,
            file_path=missing_sidecar,
            file_hash=sidecar_digest,
            file_size=4,
            tool_id="builtin:stimma:image-editor",
            materialize_asset=True,
        )
        flagged.has_editor_sidecar = True
        await session.commit()

        plan = await inspect_profile(session, profile_id="default")
        status_by_id = {
            record["media_id"]: record["status"] for record in plan["records"]
        }
        assert status_by_id[mismatched.id] == "blocked_hash_mismatch"
        assert status_by_id[flagged.id] == "blocked_editor_sidecar_missing"

    result = await apply_profile(db_session, profile_id="default")
    assert result["migrated"] == 0
    assert changed.exists()
    assert missing_sidecar.exists()


@pytest.mark.asyncio
async def test_plan_ignores_malformed_unrelated_legacy_datetime(db_session, tmp_path):
    source = tmp_path / "legacy-date.png"
    digest = _write(source, b"legacy-date")

    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=source,
            file_hash=digest,
            file_size=11,
            tool_id="builtin:test:generate",
            materialize_asset=True,
        )
        await session.commit()
        media_id = media.id
        await session.execute(
            text("UPDATE media_items SET created_date = '' WHERE id = :media_id"),
            {"media_id": media_id},
        )
        await session.commit()
        session.expunge_all()

        plan = await inspect_profile(session, profile_id="default")
        record = next(
            record for record in plan["records"] if record["media_id"] == media_id
        )
        assert record["status"] == "eligible"

        # Leave the shared module-scoped integration database readable by
        # tests that intentionally hydrate complete MediaItem rows.
        await session.execute(
            text("UPDATE media_items SET created_date = NULL WHERE id = :media_id"),
            {"media_id": media_id},
        )
        await session.execute(
            update(MediaItem)
            .where(MediaItem.id == media_id)
            .values(deleted_at=datetime.utcnow())
        )
        await session.commit()


@pytest.mark.asyncio
async def test_explicit_legacy_roots_adopt_generated_and_imported_uploads(
    db_session, tmp_path
):
    legacy_root = tmp_path / "legacy-owned"
    uploads_root = legacy_root / "uploads"
    uploads_root.mkdir(parents=True)
    generated_path = legacy_root / "generated.png"
    upload_path = uploads_root / "uploaded.png"
    ordinary_source_path = legacy_root / "ordinary-source.png"
    unretained_upload_path = uploads_root / "unretained.png"
    untracked_path = legacy_root / "filesystem-only.tmp"

    generated_hash = _write(generated_path, b"generated")
    upload_hash = _write(upload_path, b"uploaded")
    ordinary_hash = _write(ordinary_source_path, b"ordinary")
    unretained_hash = _write(unretained_upload_path, b"unretained")
    _write(untracked_path, b"untracked")

    async with db_session() as session:
        generated = await create_media_item(
            session,
            file_path=generated_path,
            file_hash=generated_hash,
            file_size=9,
            generation_metadata=json.dumps({"source": "stimma"}),
            materialize_asset=True,
        )
        uploaded = await create_media_item(
            session,
            file_path=upload_path,
            file_hash=upload_hash,
            file_size=8,
            # Upload provenance can legitimately look imported.
            generation_metadata=json.dumps({"source": "external"}),
            materialize_asset=True,
        )
        ordinary = await create_media_item(
            session,
            file_path=ordinary_source_path,
            file_hash=ordinary_hash,
            file_size=8,
            materialize_asset=True,
        )
        unretained = await create_media_item(
            session,
            file_path=unretained_upload_path,
            file_hash=unretained_hash,
            file_size=10,
        )

        plan = await inspect_profile(
            session,
            profile_id="default",
            source_roots=[legacy_root],
            legacy_generated_roots=[legacy_root],
            legacy_upload_roots=[uploads_root],
        )
        status_by_id = {
            record["media_id"]: record["status"] for record in plan["records"]
        }
        assert status_by_id[generated.id] == "eligible"
        assert status_by_id[uploaded.id] == "eligible"
        assert status_by_id[ordinary.id] == "eligible"
        assert status_by_id[unretained.id] == "unretained_legacy_owned"
        assert plan["legacy_generated_eligible_count"] == 2
        assert plan["legacy_upload_eligible_count"] == 1
        assert plan["legacy_root_remaining_file_count"] == 2
        generated_inventory = next(
            item for item in plan["legacy_root_inventory"]
            if item["roles"] == ["generated"]
        )
        assert generated_inventory["remaining_by_status"] == {
            "unretained_legacy_owned": 1,
            "untracked_file": 1,
        }

    result = await apply_profile(
        db_session,
        profile_id="default",
        source_roots=[legacy_root],
        legacy_generated_roots=[legacy_root],
        legacy_upload_roots=[uploads_root],
        remove_untracked_legacy_files=True,
    )
    assert result["migrated"] == 3
    assert result["external_registered"] == 0
    assert result["untracked_removed"] == 1
    assert result["errors"] == []
    assert not generated_path.exists()
    assert not upload_path.exists()
    assert not ordinary_source_path.exists()
    assert unretained_upload_path.exists()
    assert not untracked_path.exists()
    assert result["remaining"]["legacy_root_remaining_file_count"] == 1

    async with db_session() as session:
        migrated_upload = await session.get(MediaItem, uploaded.id)
        upload_storage = await session.get(
            StorageObject, migrated_upload.storage_object_id
        )
        assert upload_storage.kind == "managed"


@pytest.mark.asyncio
async def test_legacy_readonly_source_is_registered_external_without_moving(
    db_session, tmp_path
):
    source_root = tmp_path / "readonly-source"
    source_root.mkdir()
    source = source_root / "imported.png"
    digest = _write(source, b"imported")

    async with db_session() as session:
        media = await create_media_item(
            session,
            file_path=source,
            file_hash=digest,
            file_size=8,
            materialize_asset=True,
        )
        plan = await inspect_profile(
            session,
            profile_id="default",
            source_roots=[source_root],
        )
        record = next(
            record for record in plan["records"] if record["media_id"] == media.id
        )
        assert record["status"] == "external_registration_candidate"

    result = await apply_profile(
        db_session,
        profile_id="default",
        source_roots=[source_root],
    )
    assert result["migrated"] == 0
    assert result["external_registered"] == 1
    assert source.exists()

    async with db_session() as session:
        registered = await session.get(MediaItem, media.id)
        storage = await session.get(StorageObject, registered.storage_object_id)
        assert storage.kind == "external"
        assert Path(storage.external_path) == source

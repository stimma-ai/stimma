"""Read-only Asset doctor regression tests."""

import hashlib

import pytest
from sqlalchemy import delete

from asset_doctor import _is_asset_foreign_key_violation, audit_assets
from asset_migration import ensure_asset_backfill
from asset_service import create_asset_from_media
from database import MediaOwner
from storage_service import object_path, stage_managed_media
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_asset_doctor_passes_a_healthy_profile(
    client, db_session, temp_appdata_dir, tmp_path
):
    source = tmp_path / "healthy.png"
    content = b"healthy"
    source.write_bytes(content)
    async with db_session() as session:
        await create_media_item(
            session,
            file_path=source,
            file_hash=hashlib.sha256(content).hexdigest(),
            file_size=len(content),
        )
        await ensure_asset_backfill(session)

    report = audit_assets(temp_appdata_dir)

    assert report["ok"] is True
    assert report["failure_count"] == 0
    profile = report["profiles"][0]
    assert profile["migration_phase"] == "contracted"
    assert profile["counts"]["assets"] == 1
    assert profile["checks"]["unowned_live_media"] == 0
    assert profile["payloads"]["missing_external"] == 0


@pytest.mark.asyncio
async def test_asset_doctor_can_verify_managed_payload_hashes(
    client, db_session, temp_appdata_dir, tmp_path
):
    source = tmp_path / "managed.png"
    content = b"managed"
    source.write_bytes(content)
    async with db_session() as session:
        await ensure_asset_backfill(session)
        media = await create_media_item(
            session,
            file_path=source,
            file_hash=hashlib.sha256(content).hexdigest(),
            file_size=len(content),
        )
        storage = await stage_managed_media(
            session,
            media=media,
            profile_id="default",
        )
        await create_asset_from_media(session, media_id=media.id)
        await session.commit()

    managed_path = object_path("default", storage.object_key)
    managed_path.write_bytes(b"corrupt")
    try:
        report = audit_assets(temp_appdata_dir, verify_hashes=True)
        codes = {
            finding["code"]
            for finding in report["profiles"][0]["failures"]
        }
        assert "corrupt_managed_payloads" in codes
    finally:
        managed_path.write_bytes(content)


@pytest.mark.asyncio
async def test_asset_doctor_fails_when_revision_ownership_is_broken(
    client, db_session, temp_appdata_dir
):
    async with db_session() as session:
        await ensure_asset_backfill(session)
        media = await create_media_item(session)
        asset = await create_asset_from_media(session, media_id=media.id)
        await session.commit()
        await session.execute(
            delete(MediaOwner).where(
                MediaOwner.root_kind == "asset_revision",
                MediaOwner.root_id == str(asset.current_revision_id),
            )
        )
        await session.commit()

    report = audit_assets(temp_appdata_dir)

    assert report["ok"] is False
    codes = {finding["code"] for finding in report["profiles"][0]["failures"]}
    assert "live_revisions_missing_primary_owner" in codes
    assert "unowned_live_media" in codes


def test_legacy_media_children_are_not_mislabeled_as_asset_corruption():
    assert _is_asset_foreign_key_violation("faces", "media_items") is False
    assert _is_asset_foreign_key_violation("media_lineage", "media_items") is False
    assert _is_asset_foreign_key_violation("asset_revisions", "media_items") is True
    assert _is_asset_foreign_key_violation("media_items", "storage_objects") is True

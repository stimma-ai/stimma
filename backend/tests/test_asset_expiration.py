"""Asset lifecycle exclusively owns expiration."""

import asyncio
from datetime import datetime, timedelta

import pytest

from asset_service import create_asset_from_media
from cleanup_service import CleanupService
from container_service import create_container_asset_from_media
from database import (
    Asset,
    AssetMarker,
    AssetTag,
    Marker,
    MediaItem,
    Project,
    ProjectAsset,
    Tag,
)
from tests.helpers.media import create_media_item
from utils.background_tasks import (
    _wait_for_cleanup_schedule,
    notify_asset_expiration_changed,
)


@pytest.mark.asyncio
async def test_new_expiration_wakes_sleeping_cleanup_scheduler():
    waiter = asyncio.create_task(_wait_for_cleanup_schedule(10))
    await asyncio.sleep(0)
    notify_asset_expiration_changed()
    await asyncio.wait_for(waiter, timeout=0.2)


@pytest.mark.asyncio
async def test_expired_asset_moves_to_trash_without_deleting_media(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/asset-expiry.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        deadline = datetime.utcnow() - timedelta(minutes=1)
        asset.expires_at = deadline
        media.auto_delete_at = deadline
        asset_id = asset.id
        media_id = media.id
        await session.commit()

        asset_ids, media_ids, _ = await CleanupService().cleanup_expired_images(
            session, {}
        )
        assert asset_ids == [asset_id]
        assert media_ids == []
        trashed = await session.get(Asset, asset_id)
        retained_media = await session.get(MediaItem, media_id)
        assert trashed.state == "trashed"
        assert trashed.deleted_at is not None
        assert retained_media.deleted_at is None
        assert retained_media.auto_delete_at is None


@pytest.mark.asyncio
async def test_asset_curation_clears_expiration_in_cleanup_race(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/kept-expiry.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        tag = Tag(tag_text="keep-expired")
        session.add(tag)
        await session.flush()
        session.add(AssetTag(asset_id=asset.id, tag_id=tag.id))
        asset.expires_at = datetime.utcnow() - timedelta(minutes=1)
        media.auto_delete_at = asset.expires_at
        media_id = media.id
        await session.commit()

        asset_ids, media_ids, _ = await CleanupService().cleanup_expired_images(
            session, {}
        )
        assert asset_ids == []
        assert media_ids == []
        kept = await session.get(Asset, asset.id)
        assert kept.state == "active"
        assert kept.expires_at is None
        assert (await session.get(MediaItem, media_id)).auto_delete_at is None


@pytest.mark.asyncio
async def test_cleanup_repairs_future_expiration_on_curated_asset(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/future-kept.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        tag = Tag(tag_text="keep-future")
        session.add(tag)
        await session.flush()
        session.add(AssetTag(asset_id=asset.id, tag_id=tag.id))
        deadline = datetime.utcnow() + timedelta(hours=1)
        asset.expires_at = deadline
        media.auto_delete_at = deadline
        asset_id = asset.id
        media_id = media.id
        await session.commit()

        await CleanupService().cleanup_expired_images(session, {})

        assert (await session.get(Asset, asset_id)).expires_at is None
        assert (await session.get(MediaItem, media_id)).auto_delete_at is None


@pytest.mark.asyncio
async def test_legacy_media_deadline_is_scrubbed_without_deleting_media(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/legacy-expiry.png")
        media.auto_delete_at = datetime.utcnow() - timedelta(minutes=1)
        media_id = media.id
        await session.commit()

        asset_ids, media_ids, _ = await CleanupService().cleanup_expired_images(
            session, {}
        )
        assert asset_ids == []
        assert media_ids == []
        retained = await session.get(MediaItem, media_id)
        assert retained.deleted_at is None
        assert retained.auto_delete_at is None


@pytest.mark.asyncio
async def test_project_membership_repairs_asset_expiration(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/project-kept.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        project = Project(name="Expiration retention")
        session.add(project)
        await session.flush()
        session.add(ProjectAsset(project_id=project.id, asset_id=asset.id))
        deadline = datetime.utcnow() + timedelta(hours=1)
        asset.expires_at = deadline
        media.auto_delete_at = deadline
        asset_id = asset.id
        media_id = media.id
        await session.commit()

        await CleanupService().cleanup_expired_images(session, {})

        assert (await session.get(Asset, asset_id)).expires_at is None
        assert (await session.get(MediaItem, media_id)).auto_delete_at is None


@pytest.mark.asyncio
async def test_suppressed_marker_does_not_retain_expired_asset(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/suppressed-expiry.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        marker = Marker(
            name="suppressed-expiry-marker",
            icon_svg="<svg/>",
            color="#000000",
        )
        session.add(marker)
        await session.flush()
        session.add(
            AssetMarker(asset_id=asset.id, marker_id=marker.id, source="suppressed")
        )
        deadline = datetime.utcnow() - timedelta(minutes=1)
        asset.expires_at = deadline
        asset_id = asset.id
        await session.commit()

        asset_ids, _, _ = await CleanupService().cleanup_expired_images(session, {})

        assert asset_ids == [asset_id]
        assert (await session.get(Asset, asset_id)).state == "trashed"


@pytest.mark.asyncio
async def test_linking_asset_into_container_clears_expiration(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/container-input.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        deadline = datetime.utcnow() + timedelta(minutes=1)
        asset.expires_at = deadline
        media.auto_delete_at = deadline
        container_media = await create_media_item(
            session,
            file_path="/tmp/retaining-set.stimmaset.json",
            file_format="stimmaset.json",
        )
        await create_container_asset_from_media(
            session,
            media_id=container_media.id,
            container_type="set",
            members=[{"linked_asset_id": asset.id}],
        )
        await session.commit()

        assert (await session.get(Asset, asset.id)).expires_at is None
        assert (await session.get(MediaItem, media.id)).auto_delete_at is None


@pytest.mark.asyncio
async def test_media_detail_projects_active_asset_expiration(client, db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/expiry-projection.png")
        asset = await create_asset_from_media(session, media_id=media.id)
        asset.expires_at = datetime.utcnow() + timedelta(minutes=5)
        media_id = media.id
        deadline = asset.expires_at.isoformat()
        await session.commit()

    response = await client.get(f"/api/media/{media_id}")
    assert response.status_code == 200
    assert response.json()["auto_delete_at"] == deadline

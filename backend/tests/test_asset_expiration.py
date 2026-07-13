"""Asset lifecycle owns expiration; legacy unrooted Media remains compatible."""

from datetime import datetime, timedelta

import pytest

from asset_service import create_asset_from_media
from cleanup_service import CleanupService
from database import Asset, AssetTag, MediaItem, Tag
from tests.helpers.media import create_media_item


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
        await session.commit()

        asset_ids, media_ids, _ = await CleanupService().cleanup_expired_images(
            session, {}
        )
        assert asset_ids == []
        assert media_ids == []
        kept = await session.get(Asset, asset.id)
        assert kept.state == "active"
        assert kept.expires_at is None


@pytest.mark.asyncio
async def test_legacy_unrooted_media_still_expires(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_path="/tmp/legacy-expiry.png")
        media.auto_delete_at = datetime.utcnow() - timedelta(minutes=1)
        media_id = media.id
        await session.commit()

        asset_ids, media_ids, _ = await CleanupService().cleanup_expired_images(
            session, {}
        )
        assert asset_ids == []
        assert media_ids == [media_id]
        assert (await session.get(MediaItem, media_id)).deleted_at is not None

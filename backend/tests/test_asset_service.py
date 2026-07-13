"""Integration tests for the additive Asset/Revision/Media foundation."""

import pytest
from sqlalchemy import select

from asset_service import (
    AssetServiceError,
    clear_snapshot_source_bindings,
    commit_revision,
    create_asset_from_media,
    create_asset_snapshot,
    create_working_document,
)
from database import AssetRevision, AssetSnapshot, MediaOwner
from delete_operations import RetainedMediaError, _batch_scrub_references
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_promoting_media_creates_one_asset_revision_and_owner(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_format="png")

        asset = await create_asset_from_media(
            session,
            media_id=media.id,
            origin_type="tool_result",
            origin_id="run-1",
            idempotency_key="promote-run-1",
        )
        await session.commit()

        revision = await session.get(AssetRevision, asset.current_revision_id)
        owner = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.media_id == media.id,
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert asset.asset_type == "image"
        assert revision is not None
        assert revision.revision_number == 1
        assert revision.primary_media_id == media.id
        assert owner is not None
        assert owner.root_kind == "asset_revision"
        assert owner.root_id == str(revision.id)

        retried = await create_asset_from_media(session, media_id=media.id)
        assert retried.id == asset.id


@pytest.mark.asyncio
async def test_saving_from_an_old_revision_creates_a_branch_and_makes_it_current(db_session):
    async with db_session() as session:
        first_media = await create_media_item(session, file_format="png")
        second_media = await create_media_item(session, file_format="png")
        branch_media = await create_media_item(session, file_format="png")
        asset = await create_asset_from_media(session, media_id=first_media.id)
        first_revision_id = asset.current_revision_id

        second = await commit_revision(
            session,
            asset_id=asset.id,
            media_id=second_media.id,
        )
        branch = await commit_revision(
            session,
            asset_id=asset.id,
            media_id=branch_media.id,
            parent_revision_id=first_revision_id,
        )
        await session.commit()

        assert second.parent_revision_id == first_revision_id
        assert branch.parent_revision_id == first_revision_id
        assert branch.revision_number == 3
        assert asset.current_revision_id == branch.id


@pytest.mark.asyncio
async def test_editor_snapshot_survives_source_binding_tombstone(db_session):
    async with db_session() as session:
        source_media = await create_media_item(session, file_format="png")
        document_media = await create_media_item(session, file_format="png")
        source = await create_asset_from_media(session, media_id=source_media.id)
        document_asset = await create_asset_from_media(session, media_id=document_media.id)
        working_document = await create_working_document(
            session,
            asset_id=document_asset.id,
            editor_type="image",
        )

        snapshot = await create_asset_snapshot(
            session,
            owner_kind="working_document",
            owner_id=working_document.id,
            media_id=source_media.id,
            source_asset_id=source.id,
            source_revision_id=source.current_revision_id,
            role="layer",
            position=0,
        )
        await session.commit()

        cleared = await clear_snapshot_source_bindings(
            session,
            source_asset_id=source.id,
        )
        await session.commit()
        await session.refresh(snapshot)

        owner = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.root_kind == "asset_snapshot",
                MediaOwner.root_id == str(snapshot.id),
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert cleared == 1
        assert snapshot.source_asset_id is None
        assert snapshot.source_revision_id is None
        assert snapshot.media_id == source_media.id
        assert owner is not None
        assert owner.media_id == source_media.id


@pytest.mark.asyncio
async def test_snapshot_slot_cannot_silently_change_media(db_session):
    async with db_session() as session:
        base_media = await create_media_item(session, file_format="png")
        other_media = await create_media_item(session, file_format="png")
        asset = await create_asset_from_media(session, media_id=base_media.id)

        await create_asset_snapshot(
            session,
            owner_kind="revision",
            owner_id=asset.current_revision_id,
            media_id=base_media.id,
            role="input",
        )
        with pytest.raises(AssetServiceError, match="different Media"):
            await create_asset_snapshot(
                session,
                owner_kind="revision",
                owner_id=asset.current_revision_id,
                media_id=other_media.id,
                role="input",
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_legacy_delete_worker_fails_closed_for_asset_owned_media(db_session):
    async with db_session() as session:
        media = await create_media_item(session, file_format="png")
        await create_asset_from_media(session, media_id=media.id)
        await session.commit()

        with pytest.raises(RetainedMediaError, match="retained by a live root"):
            await _batch_scrub_references(session, [media.id])
        await session.rollback()

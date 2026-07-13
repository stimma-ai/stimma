"""Recoverable, digest-gated historical Asset backfill tests."""

import json
from datetime import datetime

import pytest
from sqlalchemy import func, select

from asset_migration import apply_asset_backfill, classify_legacy_media
from database import (
    Asset,
    AssetMigrationMap,
    AssetMigrationState,
    AssetRevision,
    ContainerMember,
    MediaOwner,
)
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_backfill_requires_exact_rehearsal_digest(db_session):
    async with db_session() as session:
        await create_media_item(session)
        with pytest.raises(ValueError, match="changed after rehearsal"):
            await apply_asset_backfill(session, approved_digest="wrong")
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(Asset)) == 0


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_preserves_embedded_and_trashed_semantics(
    db_session, tmp_path
):
    async with db_session() as session:
        embedded = await create_media_item(session, file_path=tmp_path / "cell.png")
        container = await create_media_item(
            session,
            file_path=tmp_path / "grid.stimmagrid.json",
            file_format="stimmagrid.json",
            raw_metadata=json.dumps({
                "rows": 1,
                "cols": 1,
                "cells": [{"row": 0, "col": 0, "path": "cell.png"}],
            }),
        )
        embedded.superseded_by = container.id
        trashed = await create_media_item(session, file_path=tmp_path / "trashed.png")
        trashed.deleted_at = datetime.utcnow()
        await session.commit()

        report = await classify_legacy_media(session)
        first = await apply_asset_backfill(session, approved_digest=report["digest"])
        await session.commit()
        second = await apply_asset_backfill(session, approved_digest=report["digest"])
        await session.commit()

        assert first == second
        assert first["phase"] == "dual_write"
        assert await session.scalar(select(func.count()).select_from(AssetMigrationMap)) == len(report["records"])
        state = await session.scalar(select(AssetMigrationState))
        assert state.report_digest == report["digest"]

        container_revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == container.id)
        )
        member = await session.scalar(
            select(ContainerMember).where(
                ContainerMember.container_revision_id == container_revision.id
            )
        )
        assert member.embedded_media_id == embedded.id
        assert member.linked_asset_id is None
        assert await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == embedded.id)
        ) is None

        trashed_revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == trashed.id)
        )
        trashed_asset = await session.get(Asset, trashed_revision.asset_id)
        assert trashed_asset.state == "trashed"
        assert await session.scalar(
            select(MediaOwner).where(
                MediaOwner.media_id == trashed.id,
                MediaOwner.deleted_at.is_(None),
            )
        ) is not None

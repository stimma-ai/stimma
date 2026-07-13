"""Tests for the non-mutating historical migration rehearsal."""

import json

import pytest
from sqlalchemy import func, select

from asset_migration import classify_legacy_media
from database import Asset, AssetMigrationMap, Marker, MediaItem, MediaMarker
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_classifier_is_conservative_explainable_and_read_only(db_session, tmp_path):
    async with db_session() as session:
        embedded_path = tmp_path / "embedded.png"
        curated_path = tmp_path / "curated.png"
        ambiguous_path = tmp_path / "ambiguous.png"
        container_path = tmp_path / "batch.stimmaset.json"

        embedded = await create_media_item(session, file_path=embedded_path)
        curated = await create_media_item(session, file_path=curated_path)
        ambiguous = await create_media_item(session, file_path=ambiguous_path)
        container = await create_media_item(
            session,
            file_path=container_path,
            file_format="stimmaset.json",
            raw_metadata=json.dumps(
                {"version": 1, "items": [{"path": embedded_path.name}, {"path": curated_path.name}]}
            ),
        )
        embedded.superseded_by = container.id
        curated.superseded_by = container.id
        marker = await session.scalar(select(Marker).where(Marker.name == "favorite"))
        session.add(MediaMarker(media_id=curated.id, marker_id=marker.id, source="manual"))
        await session.commit()

        report = await classify_legacy_media(session)
        repeated = await classify_legacy_media(session)
        by_id = {record["media_id"]: record for record in report["records"]}

        assert by_id[embedded.id]["classification"] == "embedded_media"
        assert by_id[curated.id]["classification"] == "asset"
        assert "independent_use_overrides_container_ownership" in by_id[curated.id]["conflicts"]
        assert by_id[container.id]["classification"] == "asset"
        assert by_id[ambiguous.id]["classification"] == "asset"
        assert by_id[ambiguous.id]["evidence"] == ["ambiguous_defaults_to_asset"]
        assert repeated["digest"] == report["digest"]
        assert await session.scalar(select(func.count()).select_from(Asset)) == 0
        assert await session.scalar(select(func.count()).select_from(AssetMigrationMap)) == 0


@pytest.mark.asyncio
async def test_classifier_reports_disagreement_and_missing_files(db_session, tmp_path):
    async with db_session() as session:
        missing = await create_media_item(session, file_path=tmp_path / "missing.png")
        unrelated_container = await create_media_item(
            session,
            file_path=tmp_path / "empty.stimmagrid.json",
            file_format="stimmagrid.json",
            raw_metadata=json.dumps({"version": 1, "cells": []}),
        )
        missing.superseded_by = unrelated_container.id
        await session.commit()

        report = await classify_legacy_media(session, check_files=True)
        record = next(row for row in report["records"] if row["media_id"] == missing.id)

        assert record["classification"] == "asset"
        assert record["file_missing"] is True
        assert "container_manifest_disagrees_with_superseded_by" in record["conflicts"]

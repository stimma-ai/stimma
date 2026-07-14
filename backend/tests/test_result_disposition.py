"""Invocation-specific generated-result disposition tests."""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from asset_service import AssetServiceError, acquire_media_owner
from database import Asset, AssetRevision, ContainerMember, GenerationJob, MediaOwner
from generation_queue import generation_job_payload
from result_disposition_service import (
    finalize_generation_output,
    validate_output_disposition,
)
from agent.v2.tools.show import _apply_show_disposition
from tests.helpers.media import create_media_item


def _job(**overrides) -> GenerationJob:
    values = {
        "status": "processing",
        "task_type": "text-to-image",
        "generator_type": "test",
        "generator_name": "test",
        "model_name": "test",
        "parameters": json.dumps({}),
        "folder_path": "/tmp",
        "output_disposition": "asset",
    }
    values.update(overrides)
    return GenerationJob(**values)


def test_generation_job_payload_projects_asset_expiration():
    deadline = datetime.utcnow() + timedelta(hours=1)
    job = _job(
        auto_delete_at=deadline + timedelta(hours=1), created_at=datetime.utcnow()
    )
    asset = Asset(expires_at=deadline)

    payload = generation_job_payload(job, asset)
    assert payload["expires_at"] == deadline.isoformat()
    assert payload["auto_delete_at"] == deadline.isoformat()
    assert generation_job_payload(job, None)["expires_at"] is None
    assert generation_job_payload(job, None)["auto_delete_at"] is None


@pytest.mark.asyncio
async def test_direct_result_atomically_materializes_one_asset(db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        job = _job()
        session.add(job)
        await session.flush()

        first_asset_id = await finalize_generation_output(session, job=job, media=media)
        retried_asset_id = await finalize_generation_output(session, job=job, media=media)
        await session.commit()

        assert first_asset_id == retried_asset_id == job.result_asset_id
        assert await session.scalar(select(func.count()).select_from(Asset)) == 1
        owners = list(
            await session.scalars(
                select(MediaOwner).where(
                    MediaOwner.media_id == media.id,
                    MediaOwner.deleted_at.is_(None),
                )
            )
        )
        assert len(owners) == 1
        assert owners[0].root_kind == "asset_revision"


@pytest.mark.asyncio
async def test_generation_expiration_is_asset_only(db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        job = _job()
        session.add(job)
        await session.flush()
        deadline = datetime.utcnow() + timedelta(hours=1)

        asset_id = await finalize_generation_output(
            session, job=job, media=media, expires_at=deadline
        )
        await session.commit()

        asset = await session.get(Asset, asset_id)
        assert asset.expires_at == deadline
        assert media.auto_delete_at is None


@pytest.mark.asyncio
async def test_agent_result_is_chat_owned_media_until_show_final(db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        job = _job(
            output_disposition="context",
            output_context_kind="chat",
            output_context_id="42",
        )
        session.add(job)
        await session.flush()

        asset_id = await finalize_generation_output(session, job=job, media=media)
        await session.commit()

        owner = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.media_id == media.id,
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert asset_id is None
        assert job.result_asset_id is None
        assert owner.root_kind == "chat"
        assert owner.root_id == "42"


def test_context_disposition_requires_an_explicit_root():
    with pytest.raises(AssetServiceError, match="requires a context root"):
        validate_output_disposition("context", None, None)


@pytest.mark.asyncio
async def test_show_intermediate_then_final_promotes_and_releases_chat_owner(db_session):
    async with db_session() as session:
        media = await create_media_item(session)

        intermediate_assets = await _apply_show_disposition(
            session=session,
            chat_id=91,
            media_ids=[media.id],
            role="intermediate",
        )
        await session.commit()
        assert intermediate_assets == [None]
        provisional = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.media_id == media.id,
                MediaOwner.root_kind == "chat",
                MediaOwner.root_id == "91",
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert provisional is not None

        final_assets = await _apply_show_disposition(
            session=session,
            chat_id=91,
            media_ids=[media.id],
            role="final",
        )
        await session.commit()
        await session.refresh(provisional)
        assert final_assets[0] is not None
        assert provisional.deleted_at is not None


@pytest.mark.asyncio
async def test_show_final_carries_context_job_expiration_to_new_asset(db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        completed_at = datetime.utcnow()
        job = _job(
            status="completed",
            output_disposition="context",
            output_context_kind="chat",
            output_context_id="93",
            result_media_id=media.id,
            auto_delete_duration="1h",
            completed_at=completed_at,
        )
        session.add(job)
        await acquire_media_owner(
            session,
            media_id=media.id,
            root_kind="chat",
            root_id="93",
            role="result",
        )
        await session.commit()

        asset_ids = await _apply_show_disposition(
            session=session,
            chat_id=93,
            media_ids=[media.id],
            role="final",
        )
        await session.commit()

        asset = await session.get(Asset, asset_ids[0])
        assert asset.expires_at == completed_at + timedelta(hours=1)

        # A repeated show must not resurrect a deadline cleared by later use.
        asset.expires_at = None
        await session.commit()
        await _apply_show_disposition(
            session=session,
            chat_id=93,
            media_ids=[media.id],
            role="final",
        )
        await session.commit()
        assert (await session.get(Asset, asset.id)).expires_at is None


@pytest.mark.asyncio
async def test_show_final_grid_commits_one_asset_with_embedded_cells(
    db_session, tmp_path
):
    async with db_session() as session:
        first = await create_media_item(session, file_path=tmp_path / "one.png")
        second = await create_media_item(session, file_path=tmp_path / "two.png")
        grid = await create_media_item(
            session,
            file_path=tmp_path / "grid.stimmagrid.json",
            file_format="stimmagrid.json",
            raw_metadata=json.dumps({
                "rows": 1,
                "cols": 2,
                "cells": [
                    {"row": 0, "col": 0, "path": "one.png"},
                    {"row": 0, "col": 1, "path": "two.png"},
                ],
            }),
        )
        for media in (first, second, grid):
            await acquire_media_owner(
                session,
                media_id=media.id,
                root_kind="chat",
                root_id="92",
                role="result",
            )
        await session.commit()

        asset_ids = await _apply_show_disposition(
            session=session,
            chat_id=92,
            media_ids=[grid.id],
            role="final",
        )
        await session.commit()

        revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.asset_id == asset_ids[0])
        )
        members = list(await session.scalars(
            select(ContainerMember).where(
                ContainerMember.container_revision_id == revision.id
            )
        ))
        assert {member.embedded_media_id for member in members} == {first.id, second.id}
        live_chat_owners = list(await session.scalars(
            select(MediaOwner).where(
                MediaOwner.root_kind == "chat",
                MediaOwner.root_id == "92",
                MediaOwner.deleted_at.is_(None),
            )
        ))
        assert live_chat_owners == []

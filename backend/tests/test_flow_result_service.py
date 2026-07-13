"""Flow output disposition and ownership integration tests."""

import json

import pytest
from sqlalchemy import select

from database import Asset, AssetRevision, ContainerMember, MediaOwner
from flow_dsl import output
from flow_dsl.errors import DSLMisuseError
from flow_result_service import (
    finalize_flow_media_result,
    reconcile_flow_media_results,
    release_flow_media_results,
)
from tests.helpers.media import create_media_item


def test_output_disposition_vocabulary_is_explicit():
    assert output("media").disposition == "independent"
    assert output("media", disposition="container").disposition == "container"
    assert output("list[media]", disposition="internal").disposition == "internal"
    with pytest.raises(DSLMisuseError):
        output("list[media]", disposition="container")
    with pytest.raises(DSLMisuseError):
        output("media", disposition="mystery")


@pytest.mark.asyncio
async def test_internal_flow_media_is_contextual_not_an_asset(db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        media_id = media.id
        asset_ids = await finalize_flow_media_result(
            session,
            flow_id=41,
            equation_key="r/tool$0",
            media_ids=[media_id],
            disposition="internal",
        )
        await session.commit()

    assert asset_ids == []
    async with db_session() as session:
        assert await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == media_id)
        ) is None
        owner = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.media_id == media_id,
                MediaOwner.root_kind == "flow_equation",
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert owner.root_id == "41:r/tool$0"


@pytest.mark.asyncio
async def test_independent_flow_output_promotes_and_releases_context_owner(db_session):
    async with db_session() as session:
        media = await create_media_item(session)
        media_id = media.id
        asset_ids = await finalize_flow_media_result(
            session,
            flow_id=42,
            equation_key="r/output$0",
            media_ids=[media_id],
            disposition="independent",
        )
        await session.commit()

    assert len(asset_ids) == 1
    async with db_session() as session:
        asset = await session.get(Asset, asset_ids[0])
        revision = await session.get(AssetRevision, asset.current_revision_id)
        assert revision.primary_media_id == media_id
        owner = await session.scalar(
            select(MediaOwner).where(
                MediaOwner.media_id == media_id,
                MediaOwner.root_kind == "flow_equation",
                MediaOwner.deleted_at.is_(None),
            )
        )
        assert owner is None


@pytest.mark.asyncio
async def test_container_flow_output_keeps_bare_cells_embedded(db_session):
    async with db_session() as session:
        first = await create_media_item(session, file_path="/tmp/flow-cell-a.png")
        second = await create_media_item(session, file_path="/tmp/flow-cell-b.png")
        grid = await create_media_item(
            session,
            file_path="/tmp/flow-grid.stimmagrid.json",
            file_format="stimmagrid.json",
        )
        grid.raw_metadata = json.dumps({
            "cells": [
                {"path": "flow-cell-a.png", "row": 0, "col": 0},
                {"path": "flow-cell-b.png", "row": 0, "col": 1},
            ]
        })
        asset_ids = await finalize_flow_media_result(
            session,
            flow_id=43,
            equation_key="r/grid$0",
            media_ids=[grid.id],
            disposition="container",
        )
        await session.commit()

    async with db_session() as session:
        asset = await session.get(Asset, asset_ids[0])
        members = list(
            await session.scalars(
                select(ContainerMember)
                .where(ContainerMember.container_revision_id == asset.current_revision_id)
                .order_by(ContainerMember.member_order)
            )
        )
        assert [member.embedded_media_id for member in members] == [first.id, second.id]
        assert all(member.linked_asset_id is None for member in members)


@pytest.mark.asyncio
async def test_rerun_replaces_equation_media_ownership(db_session):
    async with db_session() as session:
        first = await create_media_item(session, file_path="/tmp/flow-old.png")
        second = await create_media_item(session, file_path="/tmp/flow-new.png")
        await finalize_flow_media_result(
            session,
            flow_id=44,
            equation_key="r/tool$0",
            media_ids=[first.id],
            disposition="internal",
        )
        await finalize_flow_media_result(
            session,
            flow_id=44,
            equation_key="r/tool$0",
            media_ids=[second.id],
            disposition="internal",
        )
        await session.commit()

        live = list(await session.scalars(
            select(MediaOwner).where(
                MediaOwner.root_id == "44:r/tool$0",
                MediaOwner.deleted_at.is_(None),
            )
        ))
        assert [owner.media_id for owner in live] == [second.id]


@pytest.mark.asyncio
async def test_release_and_reconcile_remove_stale_flow_roots(db_session):
    async with db_session() as session:
        keep = await create_media_item(session, file_path="/tmp/flow-keep.png")
        remove = await create_media_item(session, file_path="/tmp/flow-remove.png")
        await finalize_flow_media_result(
            session,
            flow_id=45,
            equation_key="r/keep$0",
            media_ids=[keep.id],
            disposition="internal",
        )
        await finalize_flow_media_result(
            session,
            flow_id=45,
            equation_key="r/remove$0",
            media_ids=[remove.id],
            disposition="internal",
        )
        released = await reconcile_flow_media_results(
            session,
            flow_id=45,
            live_equation_keys={"r/keep$0"},
        )
        assert released == [remove.id]
        explicitly_released = await release_flow_media_results(
            session,
            flow_id=45,
            equation_keys=["r/keep$0"],
        )
        assert explicitly_released == [keep.id]

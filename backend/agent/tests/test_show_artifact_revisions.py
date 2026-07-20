"""Artifact-revision behavior for the `show` tool's `revises`/`artifact` params.

`show` is the single artifact-committing surface — `create_layout` only
renders and saves; the agent revises via a follow-up `show(revises=...)`
call. `revises` is an Asset id (never a Media id fallback — Asset ids and
Media ids are independent integer spaces, so treating an arbitrary int as
"try Asset id, else Media id" risks silently landing a revision on an
unrelated user's asset that happens to share the number). The only Media-id
case honored is a Media that's already a revision's primary payload, which
is unambiguous since no Asset claims that id. See docs/LINEAGE.md for how
this differs from lineage tracking (revises is about identity/versioning,
not derivation).

`artifact=True` marks a single deliverable's first `show(role="final")` call
so the stage opens on it as v1 without waiting for a `revises=` follow-up.
It shares revises's validation posture (role='final', exactly one item, no
sets/grids) and is mutually exclusive with revises.
"""

import pytest
from sqlalchemy import select

from agent.v2.tools.show import show
from asset_service import commit_revision, create_asset_from_media
from database import AssetRevision
from tests.helpers.media import create_media_item
from .helpers.runner import NoOpWebSocketManager


@pytest.mark.asyncio
async def test_show_final_reports_the_created_asset_id(session, test_chat):
    media = await create_media_item(session, file_hash="plain-final")
    await session.commit()

    result = await show(
        role="final",
        media_id=media.id,
        session=session,
        chat_id=test_chat.id,
    )

    revision = await session.scalar(
        select(AssetRevision).where(AssetRevision.primary_media_id == media.id)
    )
    assert revision is not None
    assert f"asset_id={revision.asset_id}" in result


@pytest.mark.asyncio
async def test_show_revises_rejects_an_id_with_no_asset(session, test_chat):
    media = await create_media_item(session, file_hash="unknown-revises-target")
    unclaimed_id = 999999
    await session.commit()

    result = await show(
        role="final",
        media_id=media.id,
        revises=unclaimed_id,
        session=session,
        chat_id=test_chat.id,
    )

    assert result.startswith("Error:")
    assert str(unclaimed_id) in result


@pytest.mark.asyncio
async def test_show_revises_resolves_a_media_id_already_in_a_chain(session, test_chat):
    """Passing a Media id that already belongs to a revision (not an Asset id)
    still resolves — the caller may only have had the media_id from an
    earlier turn's plain show() result, before this artifact flow existed."""
    first = await create_media_item(session, file_hash="chain-v1")
    second = await create_media_item(session, file_hash="chain-v2")
    asset = await create_asset_from_media(session, media_id=first.id)
    await session.commit()

    result = await show(
        role="final",
        media_id=second.id,
        revises=first.id,  # a Media id, not the Asset id
        session=session,
        chat_id=test_chat.id,
    )

    assert f"artifact: asset_id={asset.id} revision=v2" in result
    await session.refresh(asset)
    current = await session.get(AssetRevision, asset.current_revision_id)
    assert current.primary_media_id == second.id


@pytest.mark.asyncio
async def test_show_revises_commits_next_revision_of_existing_asset(session, test_chat):
    first = await create_media_item(session, file_hash="asset-v1")
    second = await create_media_item(session, file_hash="asset-v2")
    asset = await create_asset_from_media(session, media_id=first.id)
    await session.commit()

    result = await show(
        role="final",
        media_id=second.id,
        revises=asset.id,
        revision_note="tightened crop",
        session=session,
        chat_id=test_chat.id,
    )

    assert f"artifact: asset_id={asset.id} revision=v2" in result
    await session.refresh(asset)
    current = await session.get(AssetRevision, asset.current_revision_id)
    assert current.primary_media_id == second.id
    assert current.note == "tightened crop"


@pytest.mark.asyncio
async def test_show_revises_can_branch_from_an_older_parent_revision(session, test_chat):
    v1 = await create_media_item(session, file_hash="branch-v1")
    v2 = await create_media_item(session, file_hash="branch-v2")
    v3_alt = await create_media_item(session, file_hash="branch-v3-alt")
    asset = await create_asset_from_media(session, media_id=v1.id)
    v1_revision_id = asset.current_revision_id
    await commit_revision(session, asset_id=asset.id, media_id=v2.id)
    await session.commit()

    result = await show(
        role="final",
        media_id=v3_alt.id,
        revises=asset.id,
        parent_revision=v1_revision_id,
        session=session,
        chat_id=test_chat.id,
    )

    assert "artifact:" in result
    await session.refresh(asset)
    current = await session.get(AssetRevision, asset.current_revision_id)
    assert current.primary_media_id == v3_alt.id
    assert current.parent_revision_id == v1_revision_id
    assert current.revision_number == 3


@pytest.mark.asyncio
async def test_show_revises_rejects_multi_row_calls(session, test_chat):
    a = await create_media_item(session, file_hash="multi-a")
    b = await create_media_item(session, file_hash="multi-b")
    prior = await create_media_item(session, file_hash="multi-prior")
    asset = await create_asset_from_media(session, media_id=prior.id)
    await session.commit()

    result = await show(
        role="final",
        media_ids=[a.id, b.id],
        revises=asset.id,
        session=session,
        chat_id=test_chat.id,
    )

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_show_revises_requires_role_final(session, test_chat):
    prior = await create_media_item(session, file_hash="intermediate-prior")
    media = await create_media_item(session, file_hash="intermediate-media")
    asset = await create_asset_from_media(session, media_id=prior.id)
    await session.commit()

    result = await show(
        role="intermediate",
        media_id=media.id,
        revises=asset.id,
        session=session,
        chat_id=test_chat.id,
    )

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_show_artifact_marks_first_version_and_reports_v1(session, test_chat, monkeypatch):
    mock_ws = NoOpWebSocketManager()
    monkeypatch.setattr("utils.websocket.ws_manager", mock_ws)

    media = await create_media_item(session, file_hash="artifact-flag-v1")
    await session.commit()

    result = await show(
        role="final",
        media_id=media.id,
        artifact=True,
        revision_note="first pass",
        session=session,
        chat_id=test_chat.id,
    )

    revision = await session.scalar(
        select(AssetRevision).where(AssetRevision.primary_media_id == media.id)
    )
    assert revision is not None
    assert revision.revision_number == 1
    assert f"artifact: asset_id={revision.asset_id} revision=v1 revision_id={revision.id}" in result

    # It IS a new asset, so the broadcast stays asset_created — not the
    # asset_current_revision_changed event used by the revises path.
    events = [event for event, _ in mock_ws.broadcasts]
    assert "asset_created" in events
    assert "asset_current_revision_changed" not in events


@pytest.mark.asyncio
async def test_show_artifact_and_revises_are_mutually_exclusive(session, test_chat):
    prior = await create_media_item(session, file_hash="mutex-prior")
    media = await create_media_item(session, file_hash="mutex-media")
    asset = await create_asset_from_media(session, media_id=prior.id)
    await session.commit()

    result = await show(
        role="final",
        media_id=media.id,
        artifact=True,
        revises=asset.id,
        session=session,
        chat_id=test_chat.id,
    )

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_show_artifact_rejects_multi_row_calls(session, test_chat):
    a = await create_media_item(session, file_hash="artifact-multi-a")
    b = await create_media_item(session, file_hash="artifact-multi-b")
    await session.commit()

    result = await show(
        role="final",
        media_ids=[a.id, b.id],
        artifact=True,
        session=session,
        chat_id=test_chat.id,
    )

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_show_artifact_requires_role_final(session, test_chat):
    media = await create_media_item(session, file_hash="artifact-intermediate")
    await session.commit()

    result = await show(
        role="intermediate",
        media_id=media.id,
        artifact=True,
        session=session,
        chat_id=test_chat.id,
    )

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_show_revises_unavailable_in_flow_scope(session, test_chat):
    prior = await create_media_item(session, file_hash="flow-prior")
    media = await create_media_item(session, file_hash="flow-media")
    asset = await create_asset_from_media(session, media_id=prior.id)
    await session.commit()

    result = await show(
        role="final",
        media_id=media.id,
        revises=asset.id,
        session=session,
        chat_id=test_chat.id,
        _tool_scope="flow",
    )

    assert result.startswith("Error:")

"""Agent timeline tools: op batches with UI parity, per-call revisions."""

import re

import pytest
from sqlalchemy import select

from tests.helpers.media import create_media_item


def get_handler(name):
    from agent.v2 import tools  # noqa: F401  (imports register tools)
    from agent.v2.tools_registry import get_tool

    return get_tool(name).handler


async def make_timeline(session, **kwargs):
    result = await get_handler("create_timeline")(
        title="Agent Cut", fps=24, session=session, chat_id=77, **kwargs
    )
    assert "Error" not in result, result
    return int(re.search(r"timeline_id=(\d+)", result).group(1))


class TestTimelineAgentTools:
    async def test_skeleton_fill_and_revisions(self, generation_db_session):
        async with generation_db_session() as session:
            timeline_id = await make_timeline(session)

            out = await get_handler("add_slot")(
                timeline_id, 5, brief="opening wide shot", session=session, chat_id=77
            )
            assert "slot" in out and "opening wide shot" in out
            slot_id = re.search(r"slot (\w{26})", out).group(1)

            clip_media = await create_media_item(
                session, file_format="mp4", duration=12.0
            )
            out = await get_handler("fill_slot")(
                timeline_id, slot_id, clip_media.id, session=session, chat_id=77
            )
            assert "clip" in out
            # Slot duration capped the default trim
            assert "len 5s" in out

            out = await get_handler("get_timeline")(timeline_id, session=session)
            assert "Agent Cut" in out and slot_id in out

            from database import Asset, AssetRevision

            asset = await session.get(Asset, timeline_id)
            revisions = (
                await session.scalars(
                    select(AssetRevision).where(AssetRevision.asset_id == timeline_id)
                )
            ).all()
            # create + one per write tool call
            assert len(revisions) == 3
            assert asset.current_revision_id == revisions[-1].id

    async def test_track_media_validation(self, generation_db_session):
        async with generation_db_session() as session:
            timeline_id = await make_timeline(session)
            image = await create_media_item(session, file_format="png")

            out = await get_handler("add_clip")(
                timeline_id, image.id, track="audio", session=session, chat_id=77
            )
            assert out.startswith("Error")

            out = await get_handler("add_clip")(
                timeline_id, image.id, session=session, chat_id=77
            )
            # Stills need explicit duration
            assert out.startswith("Error")

            out = await get_handler("add_clip")(
                timeline_id, image.id, duration=3, session=session, chat_id=77
            )
            assert "clip" in out and "len 3s" in out

    async def test_undo_reverts_whole_tool_call(self, generation_db_session):
        from timeline import service as timeline_service
        from timeline.store import run_store

        async with generation_db_session() as session:
            timeline_id = await make_timeline(session)
            await get_handler("add_slot")(
                timeline_id, 4, brief="a", session=session, chat_id=77
            )
            result = await timeline_service.undo(session, asset_id=timeline_id)
            entries = next(
                t for t in result["state"]["tracks"] if t["kind"] == "video"
            )["entries"]
            assert entries == []

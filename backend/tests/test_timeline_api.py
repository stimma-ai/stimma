"""Timeline API integration: create, edit via ops, undo/redo, save revisions.

Uses generation_client / generation_db_session because timelines write
managed .stimmatimeline.json payloads and persist container revisions.
"""

import json

import pytest
from sqlalchemy import select

from tests.helpers.media import create_media_item


async def create_timeline(client, **overrides):
    payload = {"title": "My Cut", "fps": 24, "width": 1280, "height": 720, **overrides}
    resp = await client.post("/api/timelines", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def video_entries(state):
    return next(t for t in state["tracks"] if t["kind"] == "video")["entries"]


class TestTimelineLifecycle:
    async def test_create_returns_asset_and_snapshot_media(
        self, generation_client, generation_db_session
    ):
        created = await create_timeline(generation_client)
        assert created["state"]["title"] == "My Cut"
        assert created["state"]["fps"] == 24

        from database import Asset, MediaItem

        async with generation_db_session() as session:
            asset = await session.get(Asset, created["asset_id"])
            assert asset.asset_type == "timeline"
            media = await session.get(MediaItem, created["media_id"])
            assert media.file_format == "stimmatimeline.json"
            snapshot = json.loads(media.raw_metadata)
            assert snapshot["format"] == "stimmatimeline"
            assert [t["kind"] for t in snapshot["tracks"]] == ["video", "audio"]

    async def test_ops_undo_redo_roundtrip(self, generation_client, generation_db_session):
        created = await create_timeline(generation_client)
        asset_id = created["asset_id"]

        async with generation_db_session() as session:
            clip_media = await create_media_item(session, file_format="mp4")

        resp = await generation_client.post(
            f"/api/timelines/{asset_id}/ops",
            json={
                "ops": [
                    {"op": "add_slot", "args": {"duration": 5, "brief": "opening"}},
                    {
                        "op": "add_clip",
                        "args": {"media_id": clip_media.id, "in": 0, "out": 3},
                    },
                ],
                "label": "Skeleton",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(video_entries(body["state"])) == 2
        assert body["can_undo"] is True
        assert str(clip_media.id) in body["media"]

        resp = await generation_client.post(f"/api/timelines/{asset_id}/undo")
        assert resp.status_code == 200
        assert video_entries(resp.json()["state"]) == []

        resp = await generation_client.post(f"/api/timelines/{asset_id}/redo")
        assert resp.status_code == 200
        assert len(video_entries(resp.json()["state"])) == 2

        resp = await generation_client.get(f"/api/timelines/{asset_id}")
        assert resp.status_code == 200
        assert len(video_entries(resp.json()["state"])) == 2

    async def test_invalid_op_rejected_atomically(self, generation_client):
        created = await create_timeline(generation_client)
        asset_id = created["asset_id"]
        resp = await generation_client.post(
            f"/api/timelines/{asset_id}/ops",
            json={
                "ops": [
                    {"op": "add_slot", "args": {"duration": 5, "brief": "ok"}},
                    {"op": "trim_clip", "args": {"entry_id": "missing", "out": 2}},
                ]
            },
        )
        assert resp.status_code == 400
        resp = await generation_client.get(f"/api/timelines/{asset_id}")
        assert video_entries(resp.json()["state"]) == []

    async def test_save_revision_records_members(
        self, generation_client, generation_db_session
    ):
        created = await create_timeline(generation_client)
        asset_id = created["asset_id"]

        async with generation_db_session() as session:
            clip_media = await create_media_item(session, file_format="mp4")

        resp = await generation_client.post(
            f"/api/timelines/{asset_id}/ops",
            json={
                "ops": [
                    {"op": "add_clip", "args": {"media_id": clip_media.id, "in": 0, "out": 2}},
                    {"op": "add_slot", "args": {"duration": 4, "brief": "b-roll"}},
                ]
            },
        )
        assert resp.status_code == 200

        resp = await generation_client.post(
            f"/api/timelines/{asset_id}/save", json={"note": "first cut"}
        )
        assert resp.status_code == 200, resp.text
        saved = resp.json()
        assert saved["revision_number"] == 2

        from database import AssetRevision, ContainerMember, MediaItem

        async with generation_db_session() as session:
            revision = await session.get(AssetRevision, saved["revision_id"])
            assert revision.note == "first cut"
            members = (
                await session.scalars(
                    select(ContainerMember).where(
                        ContainerMember.container_revision_id == revision.id
                    )
                )
            ).all()
            assert len(members) == 1
            assert members[0].embedded_media_id == clip_media.id

            media = await session.get(MediaItem, saved["media_id"])
            snapshot = json.loads(media.raw_metadata)
            entries = snapshot["tracks"][0]["entries"]
            assert entries[0]["kind"] == "clip"
            assert "path" in entries[0]["media"]
            assert entries[1]["brief"] == "b-roll"
            assert media.duration == 6.0

    async def test_get_missing_timeline_404s(self, generation_client):
        resp = await generation_client.get("/api/timelines/999999")
        assert resp.status_code == 404

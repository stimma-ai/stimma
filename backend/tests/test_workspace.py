"""Tests for the shared workspace API (/api/workspace)."""
import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from database import Chat, Collection, DatabaseMeta, PinnedTool, WorkspaceDoc, WorkspaceMigration
from tests.helpers.ws import MockWebSocketManager

PATCH_TARGET = "routes.workspace.ws_manager"


def tab(tab_id, **fields):
    kind = tab_id.split(":")[0]
    entity = tab_id.split(":", 1)[1]
    return {"id": tab_id, "type": kind, "entityId": entity, "pinned": False, "displayOrder": 0, "displayName": "x", **fields}


async def write(client, *ops, origin="client-a"):
    response = await client.post("/api/workspace/docs", json={"origin": origin, "ops": list(ops)})
    assert response.status_code == 200, response.text
    return response.json()["changes"]


async def docs(client):
    response = await client.get("/api/workspace")
    assert response.status_code == 200
    return {(d["namespace"], d["key"]): d for d in response.json()["docs"]}


@pytest.fixture
async def db(db_session):
    async with db_session() as session:
        yield session


@pytest.fixture(autouse=True)
async def clean_workspace(db):
    await db.execute(delete(WorkspaceDoc))
    await db.execute(delete(WorkspaceMigration))
    await db.execute(delete(PinnedTool))
    await db.execute(delete(DatabaseMeta).where(DatabaseMeta.key == "workspace_pins_seeded"))
    await db.commit()


class TestDocs:
    async def test_value_then_read(self, client: AsyncClient):
        changes = await write(client, {"namespace": "kv", "key": "tool_a_state", "value": {"prompt": "cat"}})
        assert changes == [{"namespace": "kv", "key": "tool_a_state", "rev": 1}]
        doc = (await client.get("/api/workspace/docs/kv/tool_a_state")).json()
        assert doc["value"] == {"prompt": "cat"}

    async def test_different_keys_both_win(self, client: AsyncClient):
        await write(client, {"namespace": "kv", "key": "k", "value": {"prompt": "cat", "steps": 1}})
        await write(client, {"namespace": "kv", "key": "k", "set": {"prompt": "dog"}}, origin="a")
        await write(client, {"namespace": "kv", "key": "k", "set": {"steps": 9}}, origin="b")
        assert (await docs(client))[("kv", "k")]["value"] == {"prompt": "dog", "steps": 9}

    async def test_writes_at_the_same_moment_all_land(self, client: AsyncClient):
        await write(client, {"namespace": "kv", "key": "k", "value": {"start": 0}})
        ws = MockWebSocketManager()
        with patch(PATCH_TARGET, ws):
            await asyncio.gather(*[
                write(client, {"namespace": "kv", "key": "k", "set": {f"field{i}": i}}, origin=f"c{i}")
                for i in range(8)
            ])
        doc = (await docs(client))[("kv", "k")]
        assert doc["value"] == {"start": 0, **{f"field{i}": i for i in range(8)}}
        assert doc["rev"] == 9
        revs = [data["changes"][0]["rev"] for _, data in ws.broadcasts]
        assert revs == sorted(revs), "clients drop events older than what they hold"

    async def test_same_key_last_arrival_wins(self, client: AsyncClient):
        await write(client, {"namespace": "kv", "key": "k", "value": {"prompt": "cat"}})
        await write(client, {"namespace": "kv", "key": "k", "set": {"prompt": "dog"}}, origin="a")
        await write(client, {"namespace": "kv", "key": "k", "set": {"prompt": "bird"}}, origin="b")
        assert (await docs(client))[("kv", "k")]["value"] == {"prompt": "bird"}

    async def test_write_that_changes_nothing_is_silent(self, client: AsyncClient):
        """Two clients applying the same update must settle, not echo."""
        await write(client, {"namespace": "kv", "key": "k", "value": {"prompt": "cat"}})
        ws = MockWebSocketManager()
        with patch(PATCH_TARGET, ws):
            assert await write(client, {"namespace": "kv", "key": "k", "value": {"prompt": "cat"}}) == []
            assert await write(client, {"namespace": "kv", "key": "k", "set": {"prompt": "cat"}}) == []
            assert await write(client, {"namespace": "kv", "key": "k", "unset": ["missing"]}) == []
            assert await write(client, {"namespace": "kv", "key": "gone", "deleted": True}) == []
        assert ws.broadcasts == []
        assert (await docs(client))[("kv", "k")]["rev"] == 1

    async def test_field_update_cannot_resurrect_a_deleted_doc(self, client: AsyncClient):
        await write(client, {"namespace": "tab", "key": "chat:1", "value": tab("chat:1")})
        await write(client, {"namespace": "tab", "key": "chat:1", "deleted": True})
        assert await write(client, {"namespace": "tab", "key": "chat:1", "set": {"lastActivatedAt": 5}}) == []
        assert ("tab", "chat:1") not in await docs(client)

    async def test_value_revives_a_deleted_doc(self, client: AsyncClient):
        await write(client, {"namespace": "tab", "key": "chat:1", "value": tab("chat:1")})
        await write(client, {"namespace": "tab", "key": "chat:1", "deleted": True})
        await write(client, {"namespace": "tab", "key": "chat:1", "value": tab("chat:1")})
        assert (await docs(client))[("tab", "chat:1")]["rev"] == 3

    async def test_scalar_values_round_trip(self, client: AsyncClient):
        await write(client, {"namespace": "kv", "key": "s", "value": "true"})
        await write(client, {"namespace": "kv", "key": "n", "value": None})
        snapshot = await docs(client)
        assert snapshot[("kv", "s")]["value"] == "true"
        assert snapshot[("kv", "n")]["value"] is None

    async def test_bad_names_and_large_docs_are_refused(self, client: AsyncClient):
        bad = await client.post("/api/workspace/docs", json={"ops": [{"namespace": "Bad!", "key": "k", "value": 1}]})
        assert bad.status_code == 422
        big = await client.post(
            "/api/workspace/docs",
            json={"ops": [{"namespace": "kv", "key": "big", "value": "x" * (5 * 1024 * 1024)}]},
        )
        assert big.status_code == 413

    async def test_batch_is_atomic(self, client: AsyncClient):
        response = await client.post("/api/workspace/docs", json={"ops": [
            {"namespace": "kv", "key": "first", "value": 1},
            {"namespace": "Bad!", "key": "k", "value": 1},
        ]})
        assert response.status_code == 422
        assert ("kv", "first") not in await docs(client)

    async def test_closed_tabs_are_reported_newest_first(self, client: AsyncClient):
        for tab_id in ("chat:1", "chat:2"):
            await write(client, {"namespace": "tab", "key": tab_id, "value": tab(tab_id)})
            await write(client, {"namespace": "tab", "key": tab_id, "deleted": True})
        closed = (await client.get("/api/workspace")).json()["closed_tabs"]
        assert {t["id"] for t in closed} == {"chat:1", "chat:2"}


class TestEvents:
    async def test_change_is_broadcast_with_its_origin(self, client: AsyncClient):
        ws = MockWebSocketManager()
        with patch(PATCH_TARGET, ws):
            await write(client, {"namespace": "kv", "key": "k", "value": {"prompt": "cat"}}, origin="client-a")
            await write(client, {"namespace": "kv", "key": "k", "set": {"prompt": "dog"}}, origin="client-b")
        first, second = [data for event, data in ws.broadcasts if event == "workspace_docs_changed"]
        assert first["origin"] == "client-a"
        assert first["changes"][0]["value"] == {"prompt": "cat"}
        assert second["origin"] == "client-b"
        assert second["changes"] == [{"namespace": "kv", "key": "k", "rev": 2, "set": {"prompt": "dog"}, "unset": []}]

    async def test_large_change_is_announced_without_content(self, client: AsyncClient):
        ws = MockWebSocketManager()
        with patch(PATCH_TARGET, ws):
            await write(client, {"namespace": "kv", "key": "k", "value": "x" * (200 * 1024)})
        change = ws.broadcasts[0][1]["changes"][0]
        assert change == {"namespace": "kv", "key": "k", "rev": 1, "refetch": True}


class TestMigrate:
    async def _migrate(self, client, client_id, *docs_):
        response = await client.post(
            "/api/workspace/migrate",
            json={"client_id": client_id, "docs": list(docs_), "meta": {"app": "test"}},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def test_first_upload_claims(self, client: AsyncClient):
        result = await self._migrate(
            client, "desktop-one",
            {"namespace": "tab", "key": "tool:t:i:1", "value": tab("tool:t:i:1", entityId="t", instanceId="1")},
            {"namespace": "kv", "key": "tool_t__i_1_state", "value": {"prompt": "cat"}},
        )
        assert result["applied"] is True
        assert result["stats"]["imported"] == 2
        snapshot = (await client.get("/api/workspace")).json()
        assert snapshot["migration"]["claimed"] is True
        assert {d["key"] for d in snapshot["docs"]} >= {"tool:t:i:1", "tool_t__i_1_state"}

    async def test_second_client_is_archived_not_merged(self, client: AsyncClient, db):
        await self._migrate(client, "desktop-one", {"namespace": "kv", "key": "a", "value": 1})
        result = await self._migrate(client, "desktop-two", {"namespace": "kv", "key": "b", "value": 2})
        assert result["applied"] is False
        assert ("kv", "b") not in await docs(client)
        rows = (await db.execute(select(WorkspaceMigration).order_by(WorkspaceMigration.id))).scalars().all()
        assert [(r.client_id, r.applied) for r in rows] == [("desktop-one", True), ("desktop-two", False)]
        assert '"b"' in rows[1].payload

    async def test_same_moment_exactly_one_claim(self, client: AsyncClient, db):
        results = await asyncio.gather(*[
            self._migrate(client, f"desktop-{i}-{uuid.uuid4().hex}", {"namespace": "kv", "key": f"k{i}", "value": i})
            for i in range(5)
        ])
        assert sum(1 for r in results if r["applied"]) == 1
        rows = (await db.execute(select(WorkspaceMigration))).scalars().all()
        assert len(rows) == 5

    async def test_retry_returns_the_same_result(self, client: AsyncClient, db):
        first = await self._migrate(client, "desktop-one", {"namespace": "kv", "key": "a", "value": 1})
        again = await self._migrate(client, "desktop-one", {"namespace": "kv", "key": "a", "value": 2})
        assert again["applied"] is True and again["repeat"] is True
        assert again["stats"] == first["stats"]
        assert (await docs(client))[("kv", "a")]["value"] == 1

    async def test_import_never_overwrites_server_state(self, client: AsyncClient):
        """A tab made on the phone before the desktop arrives survives."""
        await write(client, {"namespace": "kv", "key": "a", "value": {"from": "phone"}})
        await write(client, {"namespace": "tab", "key": "tool:p:i:x", "value": tab("tool:p:i:x", entityId="p")})
        result = await self._migrate(
            client, "desktop-one",
            {"namespace": "kv", "key": "a", "value": {"from": "desktop"}},
            {"namespace": "kv", "key": "b", "value": {"from": "desktop"}},
        )
        assert result["stats"]["already_present"] == 1
        snapshot = await docs(client)
        assert snapshot[("kv", "a")]["value"] == {"from": "phone"}
        assert snapshot[("kv", "b")]["value"] == {"from": "desktop"}
        assert ("tab", "tool:p:i:x") in snapshot

    async def test_tabs_for_missing_things_are_dropped_and_counted(self, client: AsyncClient, db):
        chat = Chat(name="kept")
        gone = Chat(name="gone", deleted_at=datetime.utcnow())
        db.add_all([chat, gone])
        await db.commit()
        result = await self._migrate(
            client, "desktop-one",
            {"namespace": "tab", "key": f"chat:{chat.id}", "value": tab(f"chat:{chat.id}")},
            {"namespace": "tab", "key": f"chat:{gone.id}", "value": tab(f"chat:{gone.id}")},
            {"namespace": "tab", "key": "chat:999999", "value": tab("chat:999999")},
            {"namespace": "tab", "key": "tool:offline:i:1", "value": tab("tool:offline:i:1", entityId="offline")},
        )
        assert result["stats"]["imported"] == 2
        assert {d["key"] for d in result["stats"]["dropped"]} == {f"chat:{gone.id}", "chat:999999"}
        snapshot = await docs(client)
        assert ("tab", f"chat:{chat.id}") in snapshot
        assert ("tab", "tool:offline:i:1") in snapshot

    async def test_board_tabs_from_before_the_rename_carry_over(self, client: AsyncClient, db):
        collection = Collection(name="Dogs")
        db.add(collection)
        await db.commit()
        old_id = f"board:{collection.id}"
        recents = '[{"type":"board","id":"%d","name":"Dogs"}]' % collection.id
        result = await self._migrate(
            client, "desktop-one",
            {"namespace": "tab", "key": old_id, "value": tab(old_id)},
            {"namespace": "kv", "key": "global_search_recents", "value": recents},
            {"namespace": "kv", "key": "last_route", "value": f"/boards/{collection.id}"},
        )
        assert result["stats"]["dropped"] == []
        snapshot = await docs(client)
        new_id = f"collection:{collection.id}"
        assert snapshot[("tab", new_id)]["value"]["type"] == "collection"
        assert snapshot[("tab", new_id)]["value"]["id"] == new_id
        assert '"type":"collection"' in snapshot[("kv", "global_search_recents")]["value"]
        assert snapshot[("kv", "last_route")]["value"] == f"/collections/{collection.id}"

    async def test_failed_import_leaves_nothing_behind(self, client: AsyncClient, db):
        response = await client.post("/api/workspace/migrate", json={"client_id": "desktop-one", "docs": [
            {"namespace": "kv", "key": "a", "value": 1},
            {"namespace": "Bad!", "key": "b", "value": 2},
        ]})
        assert response.status_code == 422
        assert ("kv", "a") not in await docs(client)
        assert (await db.execute(select(WorkspaceMigration))).scalars().all() == []
        retry = await self._migrate(client, "desktop-one", {"namespace": "kv", "key": "a", "value": 1})
        assert retry["applied"] is True


class TestPins:
    async def _pin(self, db, tool, order=0):
        db.add(PinnedTool(full_tool_id=tool, name=tool.upper(), pin_order=order, task_type="text-to-image"))
        await db.commit()

    async def test_first_read_turns_pins_into_tabs_once(self, client: AsyncClient, db):
        await self._pin(db, "a:tool")
        snapshot = await docs(client)
        doc = snapshot[("tab", "tool:a:tool:i:pin")]["value"]
        assert doc["pinned"] is True and doc["instanceId"] == "pin" and doc["displayName"] == "A:TOOL"
        # Closing it stays closed: seeding happens once.
        await write(client, {"namespace": "tab", "key": "tool:a:tool:i:pin", "deleted": True})
        assert ("tab", "tool:a:tool:i:pin") not in await docs(client)

    async def test_import_replaces_the_stand_in_with_the_real_pinned_tab(self, client: AsyncClient, db):
        await self._pin(db, "a:tool")
        await docs(client)  # Phone connects first; the stand-in appears.
        real = tab("tool:a:tool:i:7", entityId="a:tool", instanceId="7", pinned=True)
        await client.post("/api/workspace/migrate", json={"client_id": "desktop-one", "docs": [
            {"namespace": "tab", "key": real["id"], "value": real},
        ]})
        snapshot = await docs(client)
        assert ("tab", "tool:a:tool:i:7") in snapshot
        assert ("tab", "tool:a:tool:i:pin") not in snapshot
        closed = (await client.get("/api/workspace")).json()["closed_tabs"]
        assert closed == [], "a stand-in was never a tab, so it isn't offered to reopen"

    async def test_import_pins_an_existing_tab_for_a_server_pin(self, client: AsyncClient, db):
        await self._pin(db, "a:tool")
        unpinned = tab("tool:a:tool:i:7", entityId="a:tool", instanceId="7", lastActivatedAt=9)
        await client.post("/api/workspace/migrate", json={"client_id": "desktop-one", "docs": [
            {"namespace": "tab", "key": unpinned["id"], "value": unpinned},
        ]})
        assert (await docs(client))[("tab", "tool:a:tool:i:7")]["value"]["pinned"] is True


class TestBlobs:
    async def test_round_trip_and_replace(self, client: AsyncClient):
        put = await client.put("/api/workspace/blobs/tool_a__i_1_mask", content=b'{"mask":"data"}')
        assert put.status_code == 200
        assert (await client.get("/api/workspace/blobs/tool_a__i_1_mask")).content == b'{"mask":"data"}'
        snapshot = await docs(client)
        assert snapshot[("blob", "tool_a__i_1_mask")]["value"]["size"] == 15
        await client.put("/api/workspace/blobs/tool_a__i_1_mask", content=b"second")
        assert (await client.get("/api/workspace/blobs/tool_a__i_1_mask")).content == b"second"

    async def test_carrying_over_never_replaces_what_is_there(self, client: AsyncClient):
        await client.put("/api/workspace/blobs/edited", content=b"newer")
        await client.put("/api/workspace/blobs/edited", content=b"old", params={"if_absent": True})
        assert (await client.get("/api/workspace/blobs/edited")).content == b"newer"

        await client.put("/api/workspace/blobs/removed", content=b"x")
        await write(client, {"namespace": "blob", "key": "removed", "deleted": True})
        await client.put("/api/workspace/blobs/removed", content=b"old", params={"if_absent": True})
        assert (await client.get("/api/workspace/blobs/removed")).status_code == 404

    async def test_missing_blob_is_404(self, client: AsyncClient):
        assert (await client.get("/api/workspace/blobs/nothing")).status_code == 404

    async def test_writing_the_same_bytes_is_silent(self, client: AsyncClient):
        await client.put("/api/workspace/blobs/k", content=b"same")
        ws = MockWebSocketManager()
        with patch(PATCH_TARGET, ws):
            await client.put("/api/workspace/blobs/k", content=b"same")
        assert ws.broadcasts == []


class TestPurge:
    async def test_expired_tab_takes_its_tool_state_and_files(self, client: AsyncClient, db):
        import workspace_service as service

        await service.purge_expired(db, "default")  # Files left by other tests.
        closed = tab("tool:t:i:old", entityId="t", instanceId="old")
        kept = tab("tool:t:i:live", entityId="t", instanceId="live")
        await write(
            client,
            {"namespace": "tab", "key": closed["id"], "value": closed},
            {"namespace": "tab", "key": kept["id"], "value": kept},
            {"namespace": "kv", "key": "tool_t__i_old_state", "value": {"prompt": "old"}},
            {"namespace": "kv", "key": "tool_t__i_live_state", "value": {"prompt": "live"}},
            {"namespace": "kv", "key": "lorapool_t", "value": {"groups": []}},
        )
        await client.put("/api/workspace/blobs/tool_t__i_old_mask", content=b"old-mask")
        await client.put("/api/workspace/blobs/tool_t__i_live_mask", content=b"live-mask")
        await write(client, {"namespace": "tab", "key": closed["id"], "deleted": True})

        # Recently closed: everything is still there.
        result = await service.purge_expired(db, "default")
        assert result == {"docs": 0, "files": 0}

        later = datetime.utcnow() + service.RETENTION + timedelta(days=1)
        result = await service.purge_expired(db, "default", now=later)
        assert result["docs"] == 3  # the tab, its state, its mask
        assert result["files"] == 1
        snapshot = await docs(client)
        assert ("kv", "tool_t__i_old_state") not in snapshot
        assert ("kv", "tool_t__i_live_state") in snapshot
        assert ("kv", "lorapool_t") in snapshot
        assert (await client.get("/api/workspace/blobs/tool_t__i_live_mask")).content == b"live-mask"


class TestFeedScope:
    async def test_jobs_listed_across_clients_of_one_tab(self, client: AsyncClient, db):
        from database import GenerationJob

        now = datetime.utcnow()
        for gid in (
            "tool-my_tool__i_7@@desktop",
            "tool-my_tool__i_7@@phone",
            "tool-my_tool__i_77@@desktop",
            "tool-myXtool__i_7@@desktop",
        ):
            db.add(GenerationJob(
                status="queued", task_type="text-to-image", generator_type="t", generator_name="t",
                model_name="t", parameters="{}", folder_path="/tmp", output_disposition="asset",
                generator_instance_id=gid, created_at=now,
            ))
        await db.commit()
        response = await client.get("/api/generate/jobs", params={"feed_scope": "my_tool__i_7", "limit": 50})
        assert response.status_code == 200
        owners = {j["generator_instance_id"] for j in response.json()["jobs"]}
        assert owners == {"tool-my_tool__i_7@@desktop", "tool-my_tool__i_7@@phone"}

    def test_job_events_reach_followers_of_the_tab(self):
        from utils.websocket import build_frame

        frame = build_frame("generation_job_started", {
            "job": {"id": 1, "generator_instance_id": "tool-my_tool__i_7@@desktop"},
        })
        assert "feed:my_tool__i_7" in frame.topics
        progress = build_frame("generation_job_progress", {
            "job_id": 1, "generator_instance_id": "tool-my_tool__i_7@@desktop", "preview_b64": "AAAA",
        })
        assert "feed:my_tool__i_7" in progress.topics
        assert "previews-feed:my_tool__i_7" in progress.preview_topics
        unrelated = build_frame("generation_job_started", {"job": {"id": 2, "generator_instance_id": "agent"}})
        assert not any(t.startswith("feed:") for t in unrelated.topics)

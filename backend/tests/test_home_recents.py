"""Tests for Home's compact recents read model (GET /api/home/recents)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

import routes.flows as flow_routes
from asset_service import trash_asset
from database import Asset, AssetRevision, Board, Chat, ChatItem, Flow, MediaItem
from flow_runtime import create_flow_state_db, get_flow_state_db_path, graph_db
from flow_runtime.graph import Equation, EquationStatus, EquationType
from models.api_models import FlowEquationResponse
from tests.helpers.media import create_test_media


BASE = datetime(2026, 1, 1, 12, 0, 0)


async def _project(client, name):
    return (await client.post("/api/projects", json={"name": name})).json()["id"]


async def _touch(db_session, model, entity_id, minutes):
    async with db_session() as session:
        await session.execute(
            update(model).where(model.id == entity_id).values(updated_at=BASE + timedelta(minutes=minutes))
        )
        await session.commit()


async def _board(client, db_session, project_id, name, media_ids=(), minutes=0):
    board = (await client.post("/api/boards", json={"name": name, "project_id": project_id})).json()
    if media_ids:
        added = await client.post(f"/api/boards/{board['id']}/items", json={"media_ids": list(media_ids)})
        assert added.status_code == 200, added.text
    await _touch(db_session, Board, board["id"], minutes)
    return board["id"]


async def _chat(client, db_session, project_id, name="", messages=(), minutes=0):
    chat = (await client.post("/api/chats", json={"name": name, "project_id": project_id})).json()
    async with db_session() as session:
        for text in messages:
            session.add(ChatItem(chat_id=chat["id"], item_type="user_message", message_text=text))
        await session.commit()
    await _touch(db_session, Chat, chat["id"], minutes)
    return chat["id"]


async def _flow(client, db_session, project_id, name, minutes=0):
    flow = (await client.post("/api/flows", json={"name": name, "project_id": project_id})).json()
    await _touch(db_session, Flow, flow["id"], minutes)
    return flow["id"]


def _seed_equations(flow_id, equations):
    db_path = get_flow_state_db_path(flow_id)
    if not db_path.exists():
        create_flow_state_db(db_path)
    for eq in equations:
        graph_db.insert_equation(db_path, eq)


def _tool_eq(key, media_ids, status=EquationStatus.COMPLETED):
    return Equation(
        key=key,
        equation_type=EquationType.TOOL_CALL,
        definition={"tool_id": "p:t", "task_type": "text-to-image", "prompt": "x" * 400},
        status=status,
        result={"media_ids": media_ids, "detail": "y" * 400},
        result_media_ids=list(media_ids),
    )


async def _recents(client, project_id, **params):
    response = await client.get("/api/home/recents", params={"project_id": project_id, **params})
    assert response.status_code == 200, response.text
    return response


class TestHomeRecents:
    async def test_newest_cards_across_kinds_skipping_empty_ones(self, client, db_session):
        project_id = await _project(client, "Home order")
        async with db_session() as session:
            media = await create_test_media(session, count=2)
        board_id = await _board(client, db_session, project_id, "Mood", [m.id for m in media], minutes=1)
        await _board(client, db_session, project_id, "", minutes=9)  # empty, unnamed: skipped
        flow_id = await _flow(client, db_session, project_id, "Pipeline", minutes=3)
        await _flow(client, db_session, project_id, "", minutes=8)  # stray "New flow": skipped
        chat_id = await _chat(client, db_session, project_id, messages=["hello there"], minutes=5)
        await _chat(client, db_session, project_id, minutes=7)  # empty "New chat": skipped
        older_chat = await _chat(client, db_session, project_id, name="Old chat", minutes=0)

        body = (await _recents(client, project_id)).json()
        assert [(item["type"], item[item["type"]]["id"]) for item in body["items"]] == [
            ("chat", chat_id), ("flow", flow_id), ("board", board_id),
        ]
        assert body["has_entities"] is True
        board = body["items"][2]["board"]
        assert board["asset_count"] == 2
        assert [item["media_id"] for item in board["preview_items"]] == [m.id for m in media]
        assert all(item["file_hash"] for item in board["preview_items"])
        chat = body["items"][0]["chat"]
        assert chat["last_message"] == "hello there"
        assert chat["message_count"] == 1

        more = (await _recents(client, project_id, limit=4)).json()
        assert [item[item["type"]]["id"] for item in more["items"]][-1] == older_chat

    async def test_scopes_like_the_list_endpoints(self, client, db_session):
        project_id = await _project(client, "Home scope")
        other_id = await _project(client, "Home other")
        await _board(client, db_session, other_id, "Elsewhere")
        await _chat(client, db_session, None, name="Top-level chat")

        body = (await _recents(client, project_id)).json()
        assert body == {"items": [], "has_entities": False}
        top = (await client.get("/api/home/recents")).json()
        assert all(item[item["type"]]["project_id"] is None for item in top["items"])
        assert (await client.get("/api/home/recents?project_id=none")).json() == top

        # Only too-empty-to-show entities: no cards, but not a first run.
        await _chat(client, db_session, project_id)
        assert (await _recents(client, project_id)).json() == {"items": [], "has_entities": True}

    async def test_size_follows_the_cards_not_the_boards_behind_them(self, client, db_session, monkeypatch):
        project_id = await _project(client, "Home size")
        async with db_session() as session:
            first = await create_test_media(session, count=8)
            bulk = await create_test_media(session, count=400)
        board_id = await _board(client, db_session, project_id, "Big board", [m.id for m in first], minutes=2)
        flow_id = await _flow(client, db_session, project_id, "Big flow", minutes=1)
        _seed_equations(flow_id, [_tool_eq(f"r/tool${i}", [first[i % 8].id]) for i in range(4)])
        output_keys = {"r/tool$0": "out", "r/tool$1": "out2"}
        monkeypatch.setattr(flow_routes, "_output_name_by_key_for_flow", lambda _flow_id: dict(output_keys))
        chat_id = await _chat(client, db_session, project_id, messages=["short", "z" * 20_000], minutes=0)

        small = await _recents(client, project_id)
        legacy_small = await _legacy_home_bytes(client, project_id)

        added = await client.post(f"/api/boards/{board_id}/items", json={"media_ids": [m.id for m in bulk]})
        assert added.status_code == 200, added.text
        await _touch(db_session, Board, board_id, 2)
        _seed_equations(flow_id, [_tool_eq(f"r/more${i}", [bulk[i].id]) for i in range(400)])

        large = await _recents(client, project_id)
        legacy_large = await _legacy_home_bytes(client, project_id)
        print(
            f"\nHome recents bytes: compact {len(small.content)} -> {len(large.content)}; "
            f"legacy {legacy_small} -> {legacy_large}"
        )
        # Only the item count's digits may grow.
        assert len(large.content) - len(small.content) <= 4
        assert len(large.content) < 6_000
        assert legacy_large > 50 * len(large.content)

        body = large.json()
        board = next(item["board"] for item in body["items"] if item["type"] == "board")
        assert board["asset_count"] == 408
        assert [item["media_id"] for item in board["preview_items"]] == [m.id for m in first[:6]]
        flow = next(item["flow"] for item in body["items"] if item["type"] == "flow")
        assert [ref["media_id"] for ref in flow["preview_media"]] == [first[0].id, first[1].id]
        assert all(ref["file_hash"] for ref in flow["preview_media"])
        chat = next(item["chat"] for item in body["items"] if item["type"] == "chat")
        assert chat["id"] == chat_id
        assert len(chat["last_message"]) == 240


async def _legacy_home_bytes(client, project_id):
    """Bytes Home read before the compact model, for the same scope."""
    total = 0
    params = {"project_id": project_id}
    boards = await client.get("/api/boards", params=params)
    total += len(boards.content)
    for board in boards.json()[:6]:
        total += len((await client.get(f"/api/boards/{board['id']}")).content)
    flows = await client.get("/api/flows", params=params)
    total += len(flows.content)
    for flow in flows.json()[:6]:
        total += len((await client.get(f"/api/flows/{flow['id']}/equations")).content)
    chats = await client.get("/api/chats/previews", params={**params, "page": 1, "page_size": 6})
    total += len(chats.content)
    return total


@pytest.fixture
def fresh_flow_caches(monkeypatch):
    """Start with no live runtimes or cached load errors.

    Both caches are process-wide, keyed by (profile, flow id). Earlier test
    modules recreate the database under the same `default` profile and reuse
    flow ids, so their leftovers would make this module's new flows look
    busy. Swap in empty caches for the test; the real accessors still run.
    """
    import flow_lifecycle
    import flow_registry

    monkeypatch.setattr(flow_registry, "_RUNTIMES", {})
    monkeypatch.setattr(flow_lifecycle, "_last_load_errors", {})


class TestHomeFlowCards:
    async def test_flow_previews_skip_media_that_cannot_be_shown(self, client, db_session, monkeypatch):
        project_id = await _project(client, "Home hidden outputs")
        async with db_session() as session:
            media = await create_test_media(session, count=6)
        ids = [m.id for m in media]
        flow_id = await _flow(client, db_session, project_id, "Outputs")
        # Outputs in order: a missing id, then six real media.
        _seed_equations(flow_id, [_tool_eq("r/tool$0", [999_999_999, *ids])])
        monkeypatch.setattr(flow_routes, "_output_name_by_key_for_flow", lambda _flow_id: {"r/tool$0": "out"})
        async with db_session() as session:
            now = datetime.utcnow()
            await session.execute(update(MediaItem).where(MediaItem.id == ids[0]).values(deleted_at=now))
            await session.execute(update(MediaItem).where(MediaItem.id == ids[1]).values(file_unavailable=True))
            await session.execute(update(MediaItem).where(MediaItem.id == ids[2]).values(deletion_pending_at=now))
            asset_id = await session.scalar(
                select(Asset.id)
                .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
                .where(AssetRevision.primary_media_id == ids[3])
            )
            await trash_asset(session, asset_id=asset_id)
            await session.commit()

        flow = (await _recents(client, project_id)).json()["items"][0]["flow"]
        assert [ref["media_id"] for ref in flow["preview_media"]] == [ids[4], ids[5]]
        assert all(ref["file_hash"] for ref in flow["preview_media"])

    async def test_a_named_flow_behind_many_stray_flows_still_shows(self, client, db_session, fresh_flow_caches):
        project_id = await _project(client, "Home stray flows")
        named = await _flow(client, db_session, project_id, "Real work", minutes=0)
        for i in range(60):
            await _flow(client, db_session, project_id, "", minutes=10 + i)
        body = (await _recents(client, project_id)).json()
        assert [(item["type"], item["flow"]["id"]) for item in body["items"]] == [("flow", named)]

    async def test_an_unnamed_flow_with_program_state_outranks_older_named_ones(self, client, db_session, fresh_flow_caches):
        project_id = await _project(client, "Home unnamed flow")
        older = [await _flow(client, db_session, project_id, f"Named {i}", minutes=i) for i in range(3)]
        unnamed = await _flow(client, db_session, project_id, "", minutes=20)
        _seed_equations(unnamed, [_tool_eq("r/tool$0", [])])
        await _flow(client, db_session, project_id, "", minutes=30)  # stray
        body = (await _recents(client, project_id)).json()
        assert [item["flow"]["id"] for item in body["items"]] == [unnamed, older[2], older[1]]


_VECTORS = json.loads((Path(__file__).parent / "fixtures" / "flow_output_vectors.json").read_text())


@pytest.mark.parametrize("vector", _VECTORS["cases"], ids=lambda vector: vector["name"])
def test_flow_outputs_match_the_shared_vectors(vector):
    equations = [
        FlowEquationResponse(status="completed", **eq) for eq in vector["equations"]
    ]
    assert flow_routes.output_media_ids_from_equations(equations) == vector["expected"]

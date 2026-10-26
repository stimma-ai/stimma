"""GET /api/chats/{chat_id}/items?display_limit=N: bounded transcript windows.

A display window holds N visible top-level items (subagent children do not
count) and extends back to a turn start, so a window or page boundary does
not split an activity group. Without display_limit the
endpoint behaves as before, for older clients.
"""

import json

import pytest

from database import ChatItem
from routes.chats import DISPLAY_WINDOW_RAW_CAP, DISPLAY_WINDOW_REACH_CAP

WINDOW = 40


async def _create_chat(client) -> int:
    response = await client.post("/api/chats", json={})
    assert response.status_code == 200
    return response.json()["id"]


def _turn(chat_id: int, n: int, steps: int = 7) -> list[ChatItem]:
    """One agent turn shaped like a real one: question, thinking, tool steps
    with results, a shown image, and an answer."""
    items = [
        ChatItem(chat_id=chat_id, item_type="user_message", message_text=f"Turn {n}: " + "please make it bluer " * 10),
        ChatItem(chat_id=chat_id, item_type="assistant_message", message_text="", item_metadata=json.dumps({
            "thinking_status": "completed", "thinking_duration_seconds": 2.5,
            "thinking_content": "Considering the request. " * 30,
        })),
    ]
    for s in range(steps):
        call_id = f"call-{n}-{s}"
        items.append(ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="run_code", tool_call_id=call_id,
                              tool_args=json.dumps({"code": f"print('step {s}')\n" * 12})))
        items.append(ChatItem(chat_id=chat_id, item_type="tool_result", tool_call_id=call_id,
                              tool_result=json.dumps({"output": "result line\n" * 80, "exit_code": 0})))
    items.append(ChatItem(chat_id=chat_id, item_type="media_display", item_metadata=json.dumps({
        "display_data": {"rows": [{"label": "Result", "output": {"status": "completed"}}]},
    })))
    items.append(ChatItem(chat_id=chat_id, item_type="assistant_message", message_text="Here is the result. " * 30))
    return items


async def _seed(db_session, chat_id: int, items: list[ChatItem]) -> list[int]:
    async with db_session() as session:
        for item in items:
            session.add(item)
            await session.flush()
        await session.commit()
        return [item.id for item in items]


async def _long_chat(client, db_session, total: int = 600) -> tuple[int, list[int]]:
    chat_id = await _create_chat(client)
    items: list[ChatItem] = []
    n = 0
    while len(items) < total:
        items.extend(_turn(chat_id, n))
        n += 1
    return chat_id, await _seed(db_session, chat_id, items[:total])


def _page_boundary_ok(page: list[dict]) -> bool:
    # Newest first: the page's oldest item starts a turn.
    return page[-1]["item_type"] == "user_message"


@pytest.mark.anyio
async def test_long_chat_opens_with_a_bounded_window(client, db_session):
    chat_id, ids = await _long_chat(client, db_session)

    legacy = await client.get(f"/api/chats/{chat_id}/items?visible_limit=500")
    window = await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}&visible_limit=500")
    assert legacy.status_code == window.status_code == 200
    legacy_items = legacy.json()["items"]
    body = window.json()
    print(f"\n600-item chat: visible_limit=500 -> {len(legacy_items)} items, {len(legacy.content)} bytes; "
          f"display_limit={WINDOW} -> {len(body['items'])} items, {len(window.content)} bytes")

    # Today's window returns (nearly) the whole chat; the display window a slice.
    assert len(legacy_items) == 600
    assert len(body["items"]) < 120
    assert len(window.content) < len(legacy.content) / 5
    assert body["has_more"] is True
    # Newest first, contiguous by id, ending at a turn start.
    returned = [item["id"] for item in body["items"]]
    assert returned == sorted(ids, reverse=True)[: len(returned)]
    assert _page_boundary_ok(body["items"])


@pytest.mark.anyio
async def test_pages_cover_everything_once_without_splitting_turns(client, db_session):
    chat_id, ids = await _long_chat(client, db_session)
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}")).json()
    pages = [body["items"]]
    while body["has_more"]:
        before = pages[-1][-1]["id"]
        body = (await client.get(f"/api/chats/{chat_id}/items?limit=50&before_id={before}&display_limit={WINDOW}")).json()
        assert body["items"], "has_more promised another page"
        pages.append(body["items"])
        assert len(pages) < 50
    seen = [item["id"] for page in pages for item in page]
    assert seen == sorted(ids, reverse=True)
    # Every boundary falls on a turn start, so no activity group straddles one.
    # (The very first item of the chat is a user message too.)
    for page in pages:
        assert _page_boundary_ok(page)


@pytest.mark.anyio
async def test_window_extends_to_the_turn_start_and_ignores_subagent_steps(client, db_session):
    chat_id = await _create_chat(client)
    seed = []
    for n in range(4):
        seed.extend(_turn(chat_id, n, steps=1))
    # The newest turn delegates: one parent call with 150 child items, then
    # 50 more steps and an answer.
    seed.append(ChatItem(chat_id=chat_id, item_type="user_message", message_text="delegate it"))
    ids = await _seed(db_session, chat_id, seed)
    parent = ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="delegate", tool_call_id="d1", tool_args="{}")
    [parent_id] = await _seed(db_session, chat_id, [parent])
    children = [
        ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="bash", tool_call_id=f"c{i}",
                 tool_args="{}", parent_item_id=parent_id)
        for i in range(150)
    ]
    await _seed(db_session, chat_id, children)
    steps = [ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="bash", tool_call_id=f"g{i}", tool_args="{}")
             for i in range(50)]
    steps.append(ChatItem(chat_id=chat_id, item_type="assistant_message", message_text="done"))
    await _seed(db_session, chat_id, steps)

    # Five visible items are reached inside the newest activity group; the
    # window still extends to its turn's start, so the group is whole.
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit=5")).json()
    returned = body["items"]
    assert returned[-1]["id"] == ids[-1]
    assert len(returned) == 1 + 1 + 150 + 51
    assert body["has_more"] is True

    # The newest turn has 53 visible top-level items and the previous one 5.
    # Had the 150 children counted, 56 would be reached inside the newest
    # turn; they don't, so the window takes the previous turn too.
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit=56")).json()
    assert body["items"][-1]["message_text"].startswith("Turn 3")


@pytest.mark.anyio
async def test_one_enormous_turn_is_capped(client, db_session):
    chat_id = await _create_chat(client)
    seed = [ChatItem(chat_id=chat_id, item_type="user_message", message_text="go")]
    seed += [ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="bash", tool_call_id=f"t{i}", tool_args="{}")
             for i in range(DISPLAY_WINDOW_RAW_CAP + 50)]
    ids = await _seed(db_session, chat_id, seed)
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}")).json()
    assert len(body["items"]) == DISPLAY_WINDOW_RAW_CAP
    assert body["has_more"] is True
    # The rest of the turn pages in below it.
    rest = (await client.get(
        f"/api/chats/{chat_id}/items?before_id={body['items'][-1]['id']}&display_limit={WINDOW}"
    )).json()
    assert [i["id"] for i in body["items"] + rest["items"]] == sorted(ids, reverse=True)
    assert rest["has_more"] is False


@pytest.mark.anyio
async def test_reach_id_extends_the_window_to_loaded_history(client, db_session):
    chat_id, ids = await _long_chat(client, db_session)
    plain = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}")).json()["items"]
    reach = ids[200]
    assert reach < plain[-1]["id"]
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}&reach_id={reach}")).json()
    returned = [item["id"] for item in body["items"]]
    assert returned == sorted(ids, reverse=True)[: len(returned)]
    assert returned[-1] <= reach
    assert _page_boundary_ok(body["items"])

    # A deleted reach item still yields overlap: the window reaches below it.
    async with db_session() as session:
        await session.delete(await session.get(ChatItem, reach))
        await session.commit()
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}&reach_id={reach}")).json()
    assert body["items"][-1]["id"] < reach


@pytest.mark.anyio
async def test_reach_is_capped_for_long_outages(client, db_session):
    chat_id = await _create_chat(client)
    seed = [ChatItem(chat_id=chat_id, item_type="user_message", message_text=f"m{i}")
            for i in range(DISPLAY_WINDOW_REACH_CAP + 100)]
    ids = await _seed(db_session, chat_id, seed)
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}&reach_id={ids[0]}")).json()
    assert len(body["items"]) == DISPLAY_WINDOW_REACH_CAP
    # The window does not reach the client's history: the client sees a
    # disjoint snapshot and replaces the stale run (no unpageable hole).
    assert body["items"][-1]["id"] > ids[0]
    assert body["has_more"] is True


@pytest.mark.anyio
async def test_window_reports_skills_invoked_outside_it(client, db_session):
    chat_id = await _create_chat(client)
    seed = [ChatItem(chat_id=chat_id, item_type="user_message", message_text="use the skill"),
            ChatItem(chat_id=chat_id, item_type="stimpack_injection", message_text="skill body",
                     item_metadata=json.dumps({"skill_name": "app-icons"})),
            ChatItem(chat_id=chat_id, item_type="stimpack_injection", message_text="legacy",
                     item_metadata=json.dumps({"stimpack_name": "legacy-pack"}))]
    for n in range(20):
        seed.extend(_turn(chat_id, n, steps=1))
    await _seed(db_session, chat_id, seed)
    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit=5")).json()
    assert all(item["item_type"] != "stimpack_injection" for item in body["items"])
    assert body["invoked_skills"] == ["app-icons", "legacy-pack"]


@pytest.mark.anyio
async def test_requests_without_display_limit_keep_their_behavior(client, db_session):
    chat_id, ids = await _long_chat(client, db_session)
    default = (await client.get(f"/api/chats/{chat_id}/items")).json()
    assert [i["id"] for i in default["items"]] == sorted(ids, reverse=True)[:50]
    assert default["has_more"] is True
    assert default.get("invoked_skills") is None
    page = (await client.get(f"/api/chats/{chat_id}/items?limit=50&before_id={ids[100]}")).json()
    assert [i["id"] for i in page["items"]] == sorted(ids[:100], reverse=True)[:50]
    legacy = (await client.get(f"/api/chats/{chat_id}/items?visible_limit=500")).json()
    assert len(legacy["items"]) == 600
    assert legacy.get("invoked_skills") is None


async def _delegated_turn(db_session, chat_id: int, n: int, children: int = 150) -> list[int]:
    """A turn that delegates: question, delegate call, its children, result,
    answer. 4 + children items."""
    [user, call] = await _seed(db_session, chat_id, [
        ChatItem(chat_id=chat_id, item_type="user_message", message_text=f"Delegate {n}"),
        ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="delegate", tool_call_id=f"d{n}", tool_args="{}"),
    ])
    kids = await _seed(db_session, chat_id, [
        ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="bash", tool_call_id=f"d{n}-{i}",
                 tool_args="{}", parent_item_id=call)
        for i in range(children)
    ])
    rest = await _seed(db_session, chat_id, [
        ChatItem(chat_id=chat_id, item_type="tool_result", tool_call_id=f"d{n}", tool_result='{"output": "ok"}'),
        ChatItem(chat_id=chat_id, item_type="assistant_message", message_text=f"Delegated {n}"),
    ])
    return [user, call, *kids, *rest]


@pytest.mark.anyio
async def test_a_capped_window_ends_at_a_complete_turn(client, db_session):
    chat_id = await _create_chat(client)
    turns = [await _delegated_turn(db_session, chat_id, n) for n in range(3)]
    assert all(len(turn) == 154 for turn in turns)

    body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}")).json()
    returned = [item["id"] for item in body["items"]]
    # Two turns would pass the cap; the window keeps the newest turn whole
    # instead of cutting the one before it mid-delegation.
    assert returned == sorted(turns[2], reverse=True)
    present = set(returned)
    assert all(item["parent_item_id"] in present for item in body["items"] if item["parent_item_id"])
    assert body["has_more"] is True

    # Pages below it are whole turns too.
    page = (await client.get(
        f"/api/chats/{chat_id}/items?before_id={returned[-1]}&display_limit={WINDOW}"
    )).json()
    assert [item["id"] for item in page["items"]] == sorted(turns[1], reverse=True)
    # Older pages do not recompute the chat's skill summary.
    assert page["invoked_skills"] is None


@pytest.mark.anyio
async def test_reach_is_one_bounded_read(client, db_session):
    from sqlalchemy import event
    from database_registry import get_database_registry

    chat_id, ids = await _long_chat(client, db_session)
    engine = get_database_registry().get_database("default").async_engine.sync_engine
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM chat_items" in statement and "ORDER BY chat_items.id DESC" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        body = (await client.get(f"/api/chats/{chat_id}/items?display_limit={WINDOW}&reach_id={ids[100]}")).json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert body["items"][-1]["id"] <= ids[100]
    # One read back to reach_id, one more to find the turn start below it.
    assert len(statements) <= 2, statements


@pytest.mark.anyio
async def test_windows_and_pages_use_the_chat_id_index(client, db_session):
    from sqlalchemy import text

    async with db_session() as session:
        indexes = {row[1] for row in (await session.execute(text("PRAGMA index_list('chat_items')"))).all()}
        assert {"idx_chat_items_chat_id", "idx_chat_items_chat_type"} <= indexes
        plan = " ".join(str(row[-1]) for row in (await session.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM chat_items WHERE chat_id = 1 AND id < 500 ORDER BY id DESC LIMIT 100"
        ))).all())
        assert "TEMP B-TREE" not in plan, plan
        plan = " ".join(str(row[-1]) for row in (await session.execute(text(
            "EXPLAIN QUERY PLAN SELECT item_metadata FROM chat_items "
            "WHERE chat_id = 1 AND item_type = 'stimpack_injection'"
        ))).all())
        assert "idx_chat_items_chat_type" in plan, plan


@pytest.mark.anyio
async def test_prompts_and_media_page_on_their_own(client, db_session):
    chat_id, ids = await _long_chat(client, db_session)
    [linked] = await _seed(db_session, chat_id, [
        ChatItem(chat_id=chat_id, item_type="assistant_message", message_text="Here it is: ![result](media:42)"),
    ])

    prompts = []
    before = None
    while True:
        url = f"/api/chats/{chat_id}/items?only=prompts&limit=7" + (f"&before_id={before}" if before else "")
        body = (await client.get(url)).json()
        prompts += body["items"]
        if not body["has_more"]:
            break
        before = body["items"][-1]["id"]
    assert [p["message_text"].split(":")[0] for p in prompts] == [f"Turn {n}" for n in range(33, -1, -1)]
    assert all(p["item_type"] == "user_message" for p in prompts)

    # The fixture's image rows carry no media id, so only the linked
    # message shows media.
    media = (await client.get(f"/api/chats/{chat_id}/items?only=media&limit=5")).json()
    assert [i["id"] for i in media["items"]] == [linked]
    assert media["has_more"] is False


@pytest.mark.anyio
async def test_invoked_skills_endpoint_reflects_deletions(client, db_session):
    chat_id = await _create_chat(client)
    [_, injection] = await _seed(db_session, chat_id, [
        ChatItem(chat_id=chat_id, item_type="user_message", message_text="use it"),
        ChatItem(chat_id=chat_id, item_type="stimpack_injection", message_text="body",
                 item_metadata=json.dumps({"skill_name": "app-icons"})),
    ])
    assert (await client.get(f"/api/chats/{chat_id}/invoked-skills")).json() == {"skills": ["app-icons"]}
    assert (await client.delete(f"/api/chats/items/{injection}")).status_code == 200
    assert (await client.get(f"/api/chats/{chat_id}/invoked-skills")).json() == {"skills": []}


def _image(chat_id: int, media_id: int) -> ChatItem:
    return ChatItem(chat_id=chat_id, item_type="media_display", item_metadata=json.dumps({
        "display_data": {"rows": [{"output": {"media_id": media_id, "status": "completed"}}]},
    }))


def _trashed_image(chat_id: int, media_id: int) -> ChatItem:
    return ChatItem(chat_id=chat_id, item_type="media_display", item_metadata=json.dumps({
        "display_data": {"rows": [{"output": {"media_id": media_id, "status": "trashed"}}]},
    }))


async def _library(db_session, *media_ids: int) -> None:
    """Library media with fixed ids, so served items do not mark them deleted."""
    from database import MediaItem

    async with db_session() as session:
        for media_id in media_ids:
            if await session.get(MediaItem, media_id) is None:
                session.add(MediaItem(
                    id=media_id, file_path=f"m{media_id}.png", file_hash=f"hash-{media_id}", file_size=100,
                    file_format="png", width=64, height=64, megapixels=0.004,
                ))
        await session.commit()


def _cancelled_batch(chat_id: int) -> ChatItem:
    return ChatItem(chat_id=chat_id, item_type="progress_display", item_metadata=json.dumps({
        "display_data": {"status": "cancelled", "preview_slots": [{"status": "pending", "media_ids": []}]},
    }))


@pytest.mark.anyio
async def test_media_pages_skip_records_that_show_nothing(client, db_session):
    await _library(db_session, 870999, 871000)
    chat_id = await _create_chat(client)
    [image] = await _seed(db_session, chat_id, [_image(chat_id, 870999)])
    await _seed(db_session, chat_id, [_cancelled_batch(chat_id) for _ in range(120)])
    [newest] = await _seed(db_session, chat_id, [_image(chat_id, 871000)])
    body = (await client.get(f"/api/chats/{chat_id}/items?only=media&limit=100")).json()
    # The 120 empty batches neither fill the page nor hide the older image.
    assert [item["id"] for item in body["items"]] == [newest, image]
    assert body["has_more"] is False


@pytest.mark.anyio
async def test_media_pages_bound_their_scan_and_hand_back_a_cursor(client, db_session):
    from routes.chats import _MEDIA_SCAN_CAP

    await _library(db_session, 870999)
    chat_id = await _create_chat(client)
    [image] = await _seed(db_session, chat_id, [_image(chat_id, 870999)])
    empty = await _seed(db_session, chat_id, [_cancelled_batch(chat_id) for _ in range(_MEDIA_SCAN_CAP + 20)])
    body = (await client.get(f"/api/chats/{chat_id}/items?only=media&limit=100")).json()
    assert body["items"] == []
    assert body["has_more"] is True
    assert body["next_before_id"] == empty[20]
    body = (await client.get(
        f"/api/chats/{chat_id}/items?only=media&limit=100&before_id={body['next_before_id']}"
    )).json()
    assert [item["id"] for item in body["items"]] == [image]
    assert body["has_more"] is False


@pytest.mark.anyio
async def test_media_pages_skip_trashed_and_deleted_outputs(client, db_session):
    await _library(db_session, 870999, 871001)
    chat_id = await _create_chat(client)
    [image] = await _seed(db_session, chat_id, [_image(chat_id, 870999)])
    # 100 trashed outputs and 100 outputs whose media left the library.
    await _seed(db_session, chat_id, [_trashed_image(chat_id, 871001) for _ in range(100)])
    await _seed(db_session, chat_id, [_image(chat_id, 990000 + i) for i in range(100)])
    body = (await client.get(f"/api/chats/{chat_id}/items?only=media&limit=100")).json()
    assert [item["id"] for item in body["items"]] == [image]
    assert body["has_more"] is False

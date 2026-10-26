"""GET /api/chats/{chat_id}/items orders by id, the key before_id pages on.

The chat view reconciles and paginates by item id. If the endpoint ordered
by created_at while before_id filtered by id, out-of-order timestamps would
make windows and pages overlap or skip items.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from database import ChatItem


async def _create_chat(client) -> int:
    response = await client.post("/api/chats", json={})
    assert response.status_code == 200
    return response.json()["id"]


async def _create_item(client, chat_id: int, text: str) -> int:
    response = await client.post(
        f"/api/chats/{chat_id}/items",
        json={"item_type": "assistant_message", "message_text": text},
    )
    assert response.status_code == 200
    return response.json()["id"]


async def _seed_out_of_order(client, db_session, count: int) -> tuple[int, list[int]]:
    chat_id = await _create_chat(client)
    ids = [await _create_item(client, chat_id, f"m{i}") for i in range(count)]
    # Timestamps run backwards against ids (the newest id is the oldest time).
    base = datetime(2026, 1, 1)
    async with db_session() as session:
        for offset, item_id in enumerate(ids):
            await session.execute(
                update(ChatItem)
                .where(ChatItem.id == item_id)
                .values(created_at=base - timedelta(minutes=offset))
            )
        await session.commit()
    return chat_id, ids


@pytest.mark.anyio
async def test_visible_window_is_newest_ids_first(client, db_session):
    chat_id, ids = await _seed_out_of_order(client, db_session, 6)
    response = await client.get(f"/api/chats/{chat_id}/items?visible_limit=3")
    assert response.status_code == 200
    body = response.json()
    returned = [item["id"] for item in body["items"]]
    assert returned == sorted(returned, reverse=True)
    assert returned[0] == ids[-1]


@pytest.mark.anyio
async def test_pages_are_contiguous_by_id(client, db_session):
    chat_id, ids = await _seed_out_of_order(client, db_session, 7)
    seen = []
    before_id = None
    for _ in range(10):
        url = f"/api/chats/{chat_id}/items?limit=3"
        if before_id is not None:
            url += f"&before_id={before_id}"
        body = (await client.get(url)).json()
        page = [item["id"] for item in body["items"]]
        assert page == sorted(page, reverse=True)
        seen.extend(page)
        if not body["has_more"]:
            break
        before_id = page[-1]
    # Every item exactly once, newest id first, no overlap or gap.
    assert seen == sorted(ids, reverse=True)


@pytest.mark.anyio
async def test_window_then_pages_cover_everything_once(client, db_session):
    chat_id, ids = await _seed_out_of_order(client, db_session, 8)
    body = (await client.get(f"/api/chats/{chat_id}/items?visible_limit=3")).json()
    seen = [item["id"] for item in body["items"]]
    while body["has_more"]:
        body = (await client.get(f"/api/chats/{chat_id}/items?limit=2&before_id={seen[-1]}")).json()
        seen.extend(item["id"] for item in body["items"])
    assert seen == sorted(ids, reverse=True)

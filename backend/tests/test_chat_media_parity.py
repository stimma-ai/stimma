"""The server's media filter (only=media) agrees with the chat view's media
collector on shared vectors (frontend/tests/fixtures/chatMediaVectors.json).

Each vector's record is stored, its served form is checked as the endpoint
returns it (deleted media marked), and only=media must return the record
exactly when the collector finds media in that served form. The frontend's
tests/chatMediaParity.test.mjs runs the collector over the same served items.
"""

import json
from pathlib import Path

import pytest

from database import ChatItem, MediaItem
from routes.chats import _served_media_ids

VECTORS = json.loads(
    (Path(__file__).parents[2] / "frontend/tests/fixtures/chatMediaVectors.json").read_text()
)


async def _seed_vectors(client, db_session) -> tuple[int, dict]:
    async with db_session() as session:
        for media_id in VECTORS["existing_media"]:
            if await session.get(MediaItem, media_id) is None:
                session.add(MediaItem(
                    id=media_id, file_path=f"v{media_id}.png", file_hash=f"vector-{media_id}", file_size=100,
                    file_format="png", width=64, height=64, megapixels=0.004,
                ))
        await session.commit()
    chat_id = (await client.post("/api/chats", json={})).json()["id"]
    ids = {}
    async with db_session() as session:
        delegate = ChatItem(chat_id=chat_id, item_type="tool_call", tool_name="delegate", tool_call_id="d", tool_args="{}")
        session.add(delegate)
        await session.flush()
        for vector in VECTORS["vectors"]:
            record = vector["record"]
            item = ChatItem(
                chat_id=chat_id,
                item_type=record["item_type"],
                message_text=record["message_text"],
                item_metadata=json.dumps(record["item_metadata"]) if record["item_metadata"] is not None else None,
                parent_item_id=delegate.id if vector.get("delegated") else None,
            )
            session.add(item)
            await session.flush()
            ids[vector["name"]] = item.id
        await session.commit()
    return chat_id, ids


@pytest.mark.anyio
async def test_media_filter_matches_the_collector_on_shared_vectors(client, db_session):
    chat_id, ids = await _seed_vectors(client, db_session)

    # Served forms, as the transcript endpoint returns them.
    served = {item["id"]: item for item in (await client.get(f"/api/chats/{chat_id}/items?limit=200")).json()["items"]}
    media = (await client.get(f"/api/chats/{chat_id}/items?only=media&limit=200")).json()
    assert media["has_more"] is False
    returned = {item["id"]: item for item in media["items"]}

    for vector in VECTORS["vectors"]:
        name = vector["name"]
        item = served[ids[name]]
        assert item["item_metadata"] == vector["served_metadata"], name
        assert _served_media_ids(item["item_type"], item["item_metadata"], item["message_text"]) == vector["media_ids"], name
        assert (ids[name] in returned) == bool(vector["media_ids"]), name
        if ids[name] in returned:
            assert returned[ids[name]] == item, name

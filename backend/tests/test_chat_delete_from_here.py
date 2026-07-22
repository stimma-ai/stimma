"""Tests for POST /api/chats/{chat_id}/items/{item_id}/delete-from-here.

The range is computed server-side so it covers items the client never
received (e.g. broadcast while the chat view was deactivated). A
client-computed id list can miss such rows, leaving an orphaned tool_call
that makes providers reject the whole conversation on replay.
"""

import json

import pytest


@pytest.fixture
def agent_spy(monkeypatch):
    """Keep user_message POSTs from running a real agent loop."""
    calls = []

    async def _fake_run(chat_id, user_message, profile_id, selected_media_ids=None, artifact_context=None):
        calls.append({"chat_id": chat_id, "user_message": user_message})

    monkeypatch.setattr("routes.chats._run_agent_background", _fake_run)
    return calls


def _settings_dict(raw) -> dict:
    return raw if isinstance(raw, dict) else json.loads(raw)


async def _create_chat(client) -> int:
    response = await client.post("/api/chats", json={})
    assert response.status_code == 200
    return response.json()["id"]


async def _create_item(client, chat_id: int, item_type: str, **fields) -> int:
    response = await client.post(
        f"/api/chats/{chat_id}/items",
        json={"item_type": item_type, **fields},
    )
    assert response.status_code == 200
    return response.json()["id"]


@pytest.mark.anyio
async def test_deletes_anchor_and_everything_after(client, agent_spy):
    chat_id = await _create_chat(client)
    kept_user = await _create_item(client, chat_id, "user_message", message_text="hello")
    kept_reply = await _create_item(client, chat_id, "assistant_message", message_text="hi")
    anchor = await _create_item(client, chat_id, "user_message", message_text="do the thing")
    doomed_call = await _create_item(
        client, chat_id, "tool_call", tool_name="ask_user", tool_call_id="toolu_orphan"
    )
    doomed_hitl = await _create_item(client, chat_id, "hitl_request", item_metadata="{}")

    response = await client.post(f"/api/chats/{chat_id}/items/{anchor}/delete-from-here")
    assert response.status_code == 200
    deleted = response.json()["deleted_ids"]
    assert set(deleted) == {anchor, doomed_call, doomed_hitl}

    items_response = await client.get(f"/api/chats/{chat_id}/items")
    remaining_ids = {i["id"] for i in items_response.json()["items"]}
    assert remaining_ids == {kept_user, kept_reply}


@pytest.mark.anyio
async def test_clears_pending_hitl_state_for_deleted_tool_call(client, agent_spy):
    chat_id = await _create_chat(client)
    await _create_item(client, chat_id, "user_message", message_text="hello")
    anchor = await _create_item(
        client, chat_id, "tool_call", tool_name="ask_user", tool_call_id="toolu_pending"
    )

    settings = {"_v2_ask_pending": {"tool_call_id": "toolu_pending", "turn": 3}}
    patch = await client.patch(
        f"/api/chats/{chat_id}",
        json={"generation_settings": json.dumps(settings)},
    )
    assert patch.status_code == 200

    response = await client.post(f"/api/chats/{chat_id}/items/{anchor}/delete-from-here")
    assert response.status_code == 200

    chat_response = await client.get(f"/api/chats/{chat_id}")
    remaining_settings = _settings_dict(chat_response.json()["generation_settings"])
    assert "_v2_ask_pending" not in remaining_settings


@pytest.mark.anyio
async def test_keeps_pending_hitl_state_for_surviving_tool_call(client, agent_spy):
    chat_id = await _create_chat(client)
    await _create_item(
        client, chat_id, "tool_call", tool_name="ask_user", tool_call_id="toolu_alive"
    )
    anchor = await _create_item(client, chat_id, "error", message_text="boom")

    settings = {"_v2_ask_pending": {"tool_call_id": "toolu_alive", "turn": 1}}
    patch = await client.patch(
        f"/api/chats/{chat_id}",
        json={"generation_settings": json.dumps(settings)},
    )
    assert patch.status_code == 200

    response = await client.post(f"/api/chats/{chat_id}/items/{anchor}/delete-from-here")
    assert response.status_code == 200

    chat_response = await client.get(f"/api/chats/{chat_id}")
    remaining_settings = _settings_dict(chat_response.json()["generation_settings"])
    assert remaining_settings["_v2_ask_pending"]["tool_call_id"] == "toolu_alive"


@pytest.mark.anyio
async def test_missing_chat_404s_and_empty_range_succeeds(client, agent_spy):
    response = await client.post("/api/chats/999999/items/1/delete-from-here")
    assert response.status_code == 404

    chat_id = await _create_chat(client)
    response = await client.post(f"/api/chats/{chat_id}/items/999999/delete-from-here")
    assert response.status_code == 200
    assert response.json() == {"success": True, "deleted_ids": []}

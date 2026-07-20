"""Tests for POST /api/chats/{chat_id}/retry — clean retry after a transient error."""

import pytest


@pytest.fixture
def agent_spy(monkeypatch):
    """Replace the background agent runner with a recorder.

    Both the user_message POST path and the retry endpoint spawn
    _run_agent_background; tests must not run a real agent loop.
    """
    calls = []

    async def _fake_run(chat_id, user_message, profile_id, selected_media_ids=None, artifact_context=None):
        calls.append({"chat_id": chat_id, "user_message": user_message})

    monkeypatch.setattr("routes.chats._run_agent_background", _fake_run)
    return calls


async def _create_chat(client) -> int:
    response = await client.post("/api/chats", json={})
    assert response.status_code == 200
    return response.json()["id"]


async def _create_item(client, chat_id: int, item_type: str, text: str) -> int:
    response = await client.post(
        f"/api/chats/{chat_id}/items",
        json={"item_type": item_type, "message_text": text},
    )
    assert response.status_code == 200
    return response.json()["id"]


@pytest.mark.anyio
async def test_retry_deletes_trailing_errors_and_reruns_agent(client, agent_spy):
    chat_id = await _create_chat(client)
    user_id = await _create_item(client, chat_id, "user_message", "find my dog photos")
    assistant_id = await _create_item(client, chat_id, "assistant_message", "on it")
    await _create_item(client, chat_id, "error", "LLM connection reset")
    await _create_item(client, chat_id, "error", "LLM connection reset again")
    agent_spy.clear()  # drop the user_message-triggered spawn

    response = await client.post(f"/api/chats/{chat_id}/retry")
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Trailing error items are gone; the conversation itself is intact.
    items_response = await client.get(f"/api/chats/{chat_id}/items")
    items = items_response.json()["items"]
    assert [i["id"] for i in items if i["item_type"] == "error"] == []
    remaining_ids = {i["id"] for i in items}
    assert user_id in remaining_ids
    assert assistant_id in remaining_ids

    # The agent was re-run without appending a new user message.
    assert agent_spy == [{"chat_id": chat_id, "user_message": None}]


@pytest.mark.anyio
async def test_retry_only_deletes_trailing_errors(client, agent_spy):
    chat_id = await _create_chat(client)
    await _create_item(client, chat_id, "user_message", "hello")
    early_error_id = await _create_item(client, chat_id, "error", "old failure")
    await _create_item(client, chat_id, "assistant_message", "recovered")
    trailing_error_id = await _create_item(client, chat_id, "error", "new failure")
    agent_spy.clear()

    response = await client.post(f"/api/chats/{chat_id}/retry")
    assert response.status_code == 200

    items_response = await client.get(f"/api/chats/{chat_id}/items")
    error_ids = [i["id"] for i in items_response.json()["items"] if i["item_type"] == "error"]
    assert error_ids == [early_error_id]
    assert trailing_error_id not in error_ids


@pytest.mark.anyio
async def test_retry_conflicts_while_agent_running(client, agent_spy, monkeypatch):
    chat_id = await _create_chat(client)
    await _create_item(client, chat_id, "user_message", "hello")
    await _create_item(client, chat_id, "error", "boom")
    agent_spy.clear()

    monkeypatch.setattr("agent.v2.service.is_execution_active", lambda _chat_id: True)

    response = await client.post(f"/api/chats/{chat_id}/retry")
    assert response.status_code == 409
    assert agent_spy == []


@pytest.mark.anyio
async def test_retry_missing_chat_returns_404(client, agent_spy):
    response = await client.post("/api/chats/999999/retry")
    assert response.status_code == 404

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from database import Chat
from routes.chats import auto_name_chat
from tests.helpers.ws import MockWebSocketManager


def _make_llm_fixtures(monkeypatch, return_name="Golden Retriever Variations"):
    """Helper to set up LLM mocks. Returns (effective_config, mock_ws)."""
    effective_config = SimpleNamespace(
        get_model=lambda: "agent-fast",
        get_api_base=lambda: "http://llm.test/v1",
        get_api_key=lambda: "test-key",
    )

    async def fake_get_effective_llm_config(role):
        assert role == "agent-fast"
        return effective_config

    async def fake_llm_complete_text(config, messages, *, max_tokens=500, temperature=0.3):
        assert config is effective_config
        return return_name

    mock_ws = MockWebSocketManager()

    monkeypatch.setattr("routes.chats.get_effective_llm_config", fake_get_effective_llm_config)
    monkeypatch.setattr("llm.llm_complete_text", fake_llm_complete_text)

    return effective_config, mock_ws


@pytest.mark.asyncio
async def test_auto_name_chat_uses_effective_agent_fast_config(db_session, monkeypatch):
    async with db_session() as session:
        chat = Chat(name="")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        chat_id = chat.id

    _, mock_ws = _make_llm_fixtures(monkeypatch)

    with patch("routes.chats.ws_manager", mock_ws):
        await auto_name_chat(chat_id, "make 4 dog variations", profile_id="default")

    async with db_session() as session:
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        updated_chat = result.scalar_one()

    assert updated_chat.name == "Golden Retriever Variations"
    mock_ws.assert_broadcast("chat_updated", {"chat_id": chat_id})


@pytest.mark.asyncio
async def test_auto_name_reevaluates_on_later_messages(db_session, monkeypatch):
    """On messages 2-3, auto_name_chat should re-evaluate and potentially replace the title."""
    async with db_session() as session:
        chat = Chat(name="Greetings")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        chat_id = chat.id

    _, mock_ws = _make_llm_fixtures(monkeypatch, return_name="Dog Photo Variations")

    with patch("routes.chats.ws_manager", mock_ws):
        await auto_name_chat(
            chat_id,
            "make 4 golden retriever variations",
            profile_id="default",
            user_messages=["hello", "make 4 golden retriever variations"],
            current_name="Greetings",
        )

    async with db_session() as session:
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        updated_chat = result.scalar_one()

    assert updated_chat.name == "Dog Photo Variations"
    mock_ws.assert_broadcast("chat_updated", {"chat_id": chat_id})


@pytest.mark.asyncio
async def test_auto_name_keeps_title_when_llm_returns_same(db_session, monkeypatch):
    """When LLM decides the existing title is fine, no update or broadcast should happen."""
    async with db_session() as session:
        chat = Chat(name="Dog Photo Variations")
        session.add(chat)
        await session.commit()
        await session.refresh(chat)
        chat_id = chat.id

    _, mock_ws = _make_llm_fixtures(monkeypatch, return_name="Dog Photo Variations")

    with patch("routes.chats.ws_manager", mock_ws):
        await auto_name_chat(
            chat_id,
            "actually make it 6 variations",
            profile_id="default",
            user_messages=["hello", "make 4 golden retriever variations", "actually make it 6 variations"],
            current_name="Dog Photo Variations",
        )

    async with db_session() as session:
        result = await session.execute(select(Chat).where(Chat.id == chat_id))
        updated_chat = result.scalar_one()

    # Name unchanged, no broadcast
    assert updated_chat.name == "Dog Photo Variations"
    assert len(mock_ws.broadcasts) == 0

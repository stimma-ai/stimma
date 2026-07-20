"""Regression test for the agent package wrapper dropping artifact_context.

routes/chats.py calls agent.run_agent (the package wrapper in
agent/__init__.py), not agent.v2.service.run_agent directly. The wrapper's
signature and its call into the v2 loop must both accept/forward
artifact_context — a prior version of the wrapper didn't, so every chat
message errored with a TypeError before the agentic loop started. Fixture-
based tests that monkeypatch _run_agent_background (see test_chat_retry.py)
sit above this wrapper and can't catch that class of bug.
"""

from unittest.mock import AsyncMock

import pytest

import agent
import agent.v2


@pytest.mark.asyncio
async def test_run_agent_wrapper_forwards_artifact_context_to_v2_loop(monkeypatch):
    mock_v2_run_agent = AsyncMock()
    monkeypatch.setattr(agent.v2, "run_agent", mock_v2_run_agent)

    chat = object()
    artifact_context = {"asset_id": 1, "revision_id": 2, "revision_number": 1}

    await agent.run_agent(
        chat,
        "hello",
        session=None,
        ws_manager=None,
        artifact_context=artifact_context,
    )

    mock_v2_run_agent.assert_awaited_once()
    _, kwargs = mock_v2_run_agent.call_args
    assert kwargs.get("artifact_context") == artifact_context


@pytest.mark.asyncio
async def test_run_agent_wrapper_forwards_none_artifact_context_by_default(monkeypatch):
    mock_v2_run_agent = AsyncMock()
    monkeypatch.setattr(agent.v2, "run_agent", mock_v2_run_agent)

    chat = object()
    await agent.run_agent(chat, "hello", session=None, ws_manager=None)

    mock_v2_run_agent.assert_awaited_once()
    _, kwargs = mock_v2_run_agent.call_args
    assert kwargs.get("artifact_context") is None

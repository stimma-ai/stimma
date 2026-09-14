from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.v2 import service
from llm import FinishReason, LLMResponse


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason, expected_calls", [(FinishReason.LENGTH, 2), (FinishReason.STOP, 1)])
async def test_partial_text_continues_only_for_provider_length_stop(
    session, test_chat, mock_ws, tmp_path, monkeypatch, finish_reason, expected_calls,
):
    monkeypatch.setattr(service, "get_workspace_dir", lambda *args: tmp_path)
    monkeypatch.setattr(service, "get_project_workspace", lambda *args: None)
    monkeypatch.setattr(service, "get_chat_llm_config", AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
    messages = AsyncMock(return_value=([{"role": "user", "content": "Do the task"}], 10))
    monkeypatch.setattr(service, "build_messages", messages)
    completion = AsyncMock(side_effect=[
        LLMResponse(content="Let me", finish_reason=finish_reason),
        LLMResponse(content="Done.", finish_reason=FinishReason.STOP),
    ])
    monkeypatch.setattr(service, "llm_completion", completion)
    await service._run_agentic_loop_inner(test_chat, session, mock_ws, max_turns=4)
    assert completion.await_count == expected_calls
    if finish_reason == FinishReason.LENGTH:
        assert "output limit" in "\n".join(messages.call_args.kwargs["system_reminders"])

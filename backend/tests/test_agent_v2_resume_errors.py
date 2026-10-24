"""A failed tool transaction must still produce an error and stop the chat."""
import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from agent.v2 import service
from database import Chat, ChatItem
from tests.helpers.ws import MockWebSocketManager


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["message", "answer", "permission"])
async def test_resume_reports_failed_database_transaction(db_session, tmp_path, monkeypatch, entry):
    telemetry = Mock()
    monkeypatch.setattr("telemetry.get_telemetry_client", lambda: telemetry)
    monkeypatch.setattr(service, "get_workspace_dir", lambda *args: tmp_path)
    monkeypatch.setattr(service, "get_project_workspace", lambda *args: None)
    monkeypatch.setattr(service, "_raise_if_interrupted", lambda *args: None)
    async with db_session() as session:
        pending_key = "_v2_pending" if entry == "permission" else "_v2_ask_pending"
        chat = Chat(name="Export previews", generation_settings=json.dumps({
            pending_key: {"tool_name": "bash", "tool_call_id": "export",
                          "fn_arguments": "{}"},
        }))
        session.add(chat)
        await session.commit()
        chat_id = chat.id

        async def fail_transaction(*args, **kwargs):
            session.add(ChatItem(chat_id=None, item_type="error"))
            await session.flush()

        monkeypatch.setattr(service, "_execute_tool_call", fail_transaction)
        monkeypatch.setattr(service, "_run_agentic_loop", fail_transaction)
        ws = MockWebSocketManager()
        if entry == "message":
            await service.run_agent(chat, "Export the previews", session, ws)
        elif entry == "permission":
            await service.resume_after_hitl(chat, {"approved": True, "scope": "once"}, session, ws)
        else:
            await service.resume_after_ask_user(chat, {"answer": "continue"}, session, ws)

        errors = (await session.scalars(select(ChatItem).where(
            ChatItem.chat_id == chat_id, ChatItem.item_type == "error",
        ))).all()
        assert len(errors) == 1
        assert "NOT NULL constraint failed" in errors[0].message_text
        assert ws.get_broadcasts("agent_stopped")[-1][1]["reason"] == "error"
        assert not service.is_execution_active(chat_id)
        if entry == "message":
            events = {call.args[0]: call.args[1] for call in telemetry.track.call_args_list}
            assert events["agent_error"]["agentContext"] == "main"
            assert events["agent_turn_completed"]["status"] == "failed"

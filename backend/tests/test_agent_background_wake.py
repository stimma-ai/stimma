"""A finished background task reports back to its chat."""
import pytest


@pytest.mark.asyncio
async def test_finished_background_task_wakes_an_idle_chat(db_session, monkeypatch):
    from agent.v2 import service
    from database import Chat, ChatItem
    from sqlalchemy import select
    from tests.helpers.ws import MockWebSocketManager

    started = []

    async def fake_run(chat_id, user_message, profile_id, *args, **kwargs):
        started.append(chat_id)

    monkeypatch.setattr("routes.chats._run_agent_background", fake_run)
    async with db_session() as s:
        chat = Chat(name="Shots")
        s.add(chat)
        await s.commit()
        chat_id = chat.id

    ws = MockWebSocketManager()
    note = {"text": "<task-notification>\nBackground task bg-1 finished.\n</task-notification>",
            "task": {"id": "bg-1", "label": "Generating", "state": "completed"}}
    await service.deliver_background_notification(chat_id, note, ws, wake=True)

    async with db_session() as s:
        items = (await s.execute(select(ChatItem).where(ChatItem.chat_id == chat_id))).scalars().all()
    assert [i.message_text for i in items] == [note["text"]]
    assert started == [chat_id]

    # Without wake (after a Stop) it is recorded but starts nothing.
    await service.deliver_background_notification(chat_id, note, ws, wake=False)
    assert started == [chat_id]


@pytest.mark.asyncio
async def test_a_steer_reaches_the_agent_while_its_code_keeps_running(db_session, tmp_path, monkeypatch):
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    import agent.v2.background as bg
    from agent.v2 import service
    from database import Chat, ChatItem
    from llm import LLMResponse, ToolCall
    from tests.helpers.ws import MockWebSocketManager

    monkeypatch.setattr(bg, "STEER_DETACH_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(service, 'get_workspace_dir', lambda *args: tmp_path)
    monkeypatch.setattr(service, 'get_project_workspace', lambda *args: None)
    monkeypatch.setattr(service, 'resolve_agent_config', AsyncMock(return_value=SimpleNamespace(
        additional_instructions='', global_memory='', project_memory='',
    )))
    monkeypatch.setattr(service, 'get_chat_llm_config', AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
    monkeypatch.setattr(service, 'build_messages', AsyncMock(return_value=([{'role': 'user', 'content': 'Ten videos.'}], 10)))
    monkeypatch.setattr("routes.chats._run_agent_background", AsyncMock())

    code = "import asyncio\nawait asyncio.sleep(1.5)\nprint('ten videos done')"
    states = []

    async def reply(*args, **kwargs):
        n = completion.await_count
        if n == 1:
            return LLMResponse(tool_calls=[ToolCall(id='rc1', name='run_code', arguments=json.dumps({'code': code}))])
        states.append([r.task.done() for r in bg.list_runs(chat.id)])
        return LLMResponse(content='Got it, warmer light from here on.')

    completion = AsyncMock(side_effect=reply)
    monkeypatch.setattr(service, 'llm_completion', completion)

    async with db_session() as session:
        chat = Chat(name='Ten videos')
        session.add(chat)
        await session.commit()
        key = service._chat_key(chat.id)
        service._active_chat_executions.add(key)
        service._mark_running(chat.id)
        ws = MockWebSocketManager()
        loop = asyncio.create_task(service._run_agentic_loop_inner(chat, session, ws, max_turns=5))
        try:
            await asyncio.sleep(0.4)
            assert service.add_steer(chat.id, {'steer_id': 's1', 'message_text': 'warmer light please'})
            await asyncio.wait_for(loop, 3)
        finally:
            service._active_chat_executions.discard(key)
            service._drop_pending_steers(chat.id)
            service._clear_interrupt(chat.id)

        # The agent answered the steer while the code was still running.
        assert states == [[False]]
        result = (await session.execute(select(ChatItem).where(
            ChatItem.chat_id == chat.id, ChatItem.item_type == 'tool_result'))).scalar_one()
        assert 'in the background as task bg-' in result.tool_result

        run = bg.list_runs(chat.id)[0]
        await asyncio.wait_for(run.task, 3)
        for _ in range(100):
            notes = (await session.execute(select(ChatItem).where(
                ChatItem.chat_id == chat.id, ChatItem.message_text.like('<task-notification>%')))).scalars().all()
            if notes:
                break
            await asyncio.sleep(0.02)
        assert len(notes) == 1 and 'ten videos done' in notes[0].message_text


@pytest.mark.asyncio
async def test_a_receipt_arriving_as_the_turn_ends_still_reaches_the_chat(db_session, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from agent.v2 import service
    from database import Chat, ChatItem
    from tests.helpers.ws import MockWebSocketManager

    woke = []

    async def fake_run(chat_id, user_message, profile_id, *args, **kwargs):
        woke.append(chat_id)

    monkeypatch.setattr("routes.chats._run_agent_background", fake_run)
    async with db_session() as session:
        chat = Chat(name="Late receipt")
        session.add(chat)
        await session.commit()
        ws = MockWebSocketManager()
        note = {"text": "<task-notification>\nlate\n</task-notification>",
                "task": {"id": "bg-1", "label": "x", "state": "completed"}}

        async def loop(*args, **kwargs):
            # The task finishes while the turn's last reply is being written.
            await service.deliver_background_notification(chat.id, note, ws, wake=True)

        monkeypatch.setattr(service, "_run_agentic_loop", loop)
        await service.run_agent(chat, None, session, ws)
        for _ in range(100):
            if woke:
                break
            await asyncio.sleep(0.02)
        items = (await session.execute(select(ChatItem).where(ChatItem.chat_id == chat.id))).scalars().all()
        assert [i.message_text for i in items] == [note["text"]]
        assert woke == [chat.id]


@pytest.mark.asyncio
async def test_a_restart_tells_the_agent_its_background_task_is_gone(db_session):
    """A detached run lives in memory. After a restart its tool result still
    says "still running, a notification will follow"; the agent must hear it
    won't, or it waits on nothing forever."""
    import agent.v2.background as bg
    from agent.v2 import service
    from database import Chat, ChatItem
    from sqlalchemy import select
    from tests.helpers.ws import MockWebSocketManager

    claim = bg.describe_detached("bg-2", "Ten videos", [], 3)
    async with db_session() as s:
        chat = Chat(name="Ten videos")
        s.add(chat)
        await s.commit()
        s.add_all([
            ChatItem(chat_id=chat.id, item_type="tool_result",
                     tool_result=bg.describe_detached("bg-1", "Stills", [], 1)),
            ChatItem(chat_id=chat.id, item_type="user_message",
                     message_text="<task-notification>\nBackground task bg-1 finished.\n</task-notification>",
                     item_metadata='{"background_task": {"id": "bg-1", "label": "Stills", "state": "completed"}}'),
            ChatItem(chat_id=chat.id, item_type="tool_result", tool_result=claim),
        ])
        await s.commit()
        chat_id = chat.id

        ws = MockWebSocketManager()
        assert await service._settle_lost_background_runs(chat_id, s, ws)
        # Said once: the next turn sees the notification and stays quiet.
        assert not await service._settle_lost_background_runs(chat_id, s, ws)

        notes = (await s.execute(select(ChatItem).where(
            ChatItem.chat_id == chat_id, ChatItem.item_type == "user_message",
        ).order_by(ChatItem.id))).scalars().all()
    assert len(notes) == 2
    lost = notes[-1]
    assert "bg-2" in lost.message_text and '"Ten videos"' in lost.message_text
    assert "server restarted" in lost.message_text and "no longer running" in lost.message_text
    assert '"state": "interrupted"' in lost.item_metadata

    # A new task in this chat never reuses an id the agent already knows.
    assert bg._next_id[bg._key(chat_id)] == 2


@pytest.mark.asyncio
async def test_a_live_background_task_is_not_reported_lost(db_session):
    import agent.v2.background as bg
    from agent.v2 import service
    from database import Chat, ChatItem
    from tests.helpers.ws import MockWebSocketManager

    async with db_session() as s:
        chat = Chat(name="Live")
        s.add(chat)
        await s.commit()
        s.add(ChatItem(chat_id=chat.id, item_type="tool_result",
                       tool_result=bg.describe_detached("bg-1", "", [], 1)))
        await s.commit()
        bg._started_here.add((*bg._key(chat.id), "bg-1"))
        try:
            assert not await service._settle_lost_background_runs(chat.id, s, MockWebSocketManager())
        finally:
            bg._started_here.discard((*bg._key(chat.id), "bg-1"))


@pytest.mark.asyncio
async def test_the_first_turn_after_a_restart_hears_about_the_lost_task(db_session, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    import agent.v2.background as bg
    from agent.v2 import service
    from database import Chat, ChatItem
    from llm import LLMResponse
    from tests.helpers.ws import MockWebSocketManager

    monkeypatch.setattr(service, 'get_workspace_dir', lambda *args: tmp_path)
    monkeypatch.setattr(service, 'get_project_workspace', lambda *args: None)
    monkeypatch.setattr(service, 'resolve_agent_config', AsyncMock(return_value=SimpleNamespace(
        additional_instructions='', global_memory='', project_memory='',
    )))
    monkeypatch.setattr(service, 'get_chat_llm_config', AsyncMock(return_value=SimpleNamespace(max_context_tokens=32768)))
    monkeypatch.setattr(service, 'build_messages', AsyncMock(return_value=([{'role': 'user', 'content': 'Are they done?'}], 10)))
    seen = []

    async with db_session() as session:
        chat = Chat(name='Ten videos')
        session.add(chat)
        await session.commit()
        session.add_all([
            ChatItem(chat_id=chat.id, item_type='tool_result',
                     tool_result=bg.describe_detached('bg-1', 'Ten videos', [], 10)),
            ChatItem(chat_id=chat.id, item_type='user_message', message_text='You were interrupted, carry on.'),
        ])
        await session.commit()

        async def reply(*args, **kwargs):
            seen.extend((await session.execute(select(ChatItem.item_metadata).where(
                ChatItem.chat_id == chat.id, ChatItem.item_metadata.like('%"background_task"%')))).scalars().all())
            return LLMResponse(content='The restart stopped them; starting again.')

        monkeypatch.setattr(service, 'llm_completion', AsyncMock(side_effect=reply))
        key = service._chat_key(chat.id)
        service._active_chat_executions.add(key)
        service._mark_running(chat.id)
        try:
            await service._run_agentic_loop_inner(chat, session, MockWebSocketManager(), max_turns=2)
        finally:
            service._active_chat_executions.discard(key)
            service._clear_interrupt(chat.id)

    # The notification was in history before the model was first asked.
    assert [json.loads(m)['background_task']['state'] for m in seen] == ['interrupted']

"""The chat agent's sense of time: timers it sets for itself, and the clock in its context."""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select


async def _chat(db_session, name="Overnight"):
    from database import Chat
    async with db_session() as s:
        chat = Chat(name=name)
        s.add(chat)
        await s.commit()
        return chat.id


async def _make_due(db_session, timer_id, minutes_ago=0.1):
    from database import AgentTimer
    async with db_session() as s:
        t = await s.get(AgentTimer, timer_id)
        t.fire_at = datetime.utcnow() - timedelta(minutes=minutes_ago)
        await s.commit()


@pytest.fixture
def fire(monkeypatch, db_session):
    """Run fire_due_timers against the test database; collect delivered notes."""
    import asyncio
    from agent.v2 import timers
    from core.profile_context import get_current_profile

    delivered = []

    async def fake_deliver(chat_id, note, ws, *, wake):
        delivered.append((chat_id, note, wake))

    monkeypatch.setattr("agent.v2.service.deliver_background_notification", fake_deliver)

    class _DB:
        async_session_maker = db_session

    class _Registry:
        def get_database(self, profile_id):
            return _DB()

    monkeypatch.setattr("database_registry.get_database_registry", lambda: _Registry())

    async def run():
        n = await timers.fire_due_timers(get_current_profile())
        for _ in range(3):
            await asyncio.sleep(0)
        return n

    run.delivered = delivered
    return run


@pytest.mark.asyncio
async def test_sdk_sets_lists_and_cancels_timers(db_session, tmp_path):
    from agent.v2.code_runtime import StimmaSDK
    chat_id = await _chat(db_session)
    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        one = await sdk.timers.set(20, "Check the renders.")
        every = await sdk.timers.set(15, "Keep going on the batch until 7 AM.", repeat=True)
        assert one["id"].startswith("timer-") and one["after_minutes"] == 20 and not one["repeats"]
        assert every["every_minutes"] == 15 and every["repeats"] and every["state"] == "active"
        assert [t["id"] for t in await sdk.timers.list()] == [one["id"], every["id"]]

        with pytest.raises(ValueError, match="note"):
            await sdk.timers.set(5, "  ")
        with pytest.raises(ValueError, match="between"):
            await sdk.timers.set(0.1, "too soon")

        assert await sdk.timers.cancel(one["id"]) == [one["id"]]
        with pytest.raises(ValueError, match="No active timer"):
            await sdk.timers.cancel(one["id"])
        assert [t["id"] for t in await sdk.timers.list()] == [every["id"]]
        assert await sdk.timers.cancel() == [every["id"]]
        assert await sdk.timers.list() == []


@pytest.mark.asyncio
async def test_one_shot_timer_fires_once_and_wakes_the_chat(db_session, fire):
    from agent.v2 import timers
    from database import AgentTimer
    chat_id = await _chat(db_session)
    async with db_session() as s:
        t = await timers.create_timer(s, chat_id, minutes=10, note="Look at the first video.", repeat=False)
    assert await fire() == 0  # not due yet

    await _make_due(db_session, t.id)
    assert await fire() == 1
    (cid, note, wake), = fire.delivered
    assert cid == chat_id and wake is True
    assert note["text"].startswith("<timer>") and "Look at the first video." in note["text"]
    assert note["metadata"]["timer"]["id"] == timers.timer_ref(t.id)

    async with db_session() as s:
        t = await s.get(AgentTimer, t.id)
        assert t.ended_at is not None and t.end_reason == "fired" and t.fire_count == 1
    assert await fire() == 0


@pytest.mark.asyncio
async def test_repeating_timer_keeps_firing_and_reports_lateness(db_session, fire):
    from agent.v2 import timers
    from database import AgentTimer, ChatItem
    chat_id = await _chat(db_session)
    async with db_session() as s:
        s.add(ChatItem(chat_id=chat_id, item_type="user_message", message_text="Run all night.",
                       created_at=datetime.utcnow() - timedelta(hours=3)))
        await s.commit()
        t = await timers.create_timer(s, chat_id, minutes=15, note="Next round, until 7 AM.", repeat=True)

    await _make_due(db_session, t.id, minutes_ago=90)  # the server was down
    assert await fire() == 1
    text = fire.delivered[0][1]["text"]
    assert "late" in text and "repeats every 15 min" in text
    assert "The user's last message was 3 h ago." in text

    async with db_session() as s:
        row = await s.get(AgentTimer, t.id)
        assert row.ended_at is None and row.fire_count == 1
        # Missed firings collapse: the next one is a full interval from now.
        assert row.fire_at > datetime.utcnow() + timedelta(minutes=14)

    await _make_due(db_session, t.id)
    assert await fire() == 1
    assert "this is firing 2" in fire.delivered[1][1]["text"]


@pytest.mark.asyncio
async def test_timer_in_a_deleted_chat_ends_without_firing(db_session, fire):
    from agent.v2 import timers
    from database import AgentTimer, Chat
    chat_id = await _chat(db_session)
    async with db_session() as s:
        t = await timers.create_timer(s, chat_id, minutes=5, note="x", repeat=True)
        (await s.get(Chat, chat_id)).deleted_at = datetime.utcnow()
        await s.commit()
    await _make_due(db_session, t.id)
    assert await fire() == 0 and fire.delivered == []
    async with db_session() as s:
        assert (await s.get(AgentTimer, t.id)).end_reason == "chat_deleted"


@pytest.mark.asyncio
async def test_timer_message_is_saved_with_timer_metadata(db_session, monkeypatch):
    from agent.v2 import service
    from database import ChatItem
    from tests.helpers.ws import MockWebSocketManager
    started = []

    async def fake_run(chat_id, user_message, profile_id, *args, **kwargs):
        started.append(chat_id)

    monkeypatch.setattr("routes.chats._run_agent_background", fake_run)
    chat_id = await _chat(db_session)
    note = {"text": "<timer>\nYour timer timer-1 fired.\n</timer>", "task": {"id": "timer-1"},
            "metadata": {"timer": {"id": "timer-1", "note": "n", "repeats": False, "fired": 1}}}
    await service.deliver_background_notification(chat_id, note, MockWebSocketManager(), wake=True)
    async with db_session() as s:
        item = (await s.execute(select(ChatItem).where(ChatItem.chat_id == chat_id))).scalar_one()
    assert json.loads(item.item_metadata) == note["metadata"]
    assert started == [chat_id]


@pytest.mark.asyncio
async def test_timer_routes_list_and_cancel(client, db_session):
    from agent.v2 import timers
    chat_id = await _chat(db_session)
    async with db_session() as s:
        t = await timers.create_timer(s, chat_id, minutes=30, note="Check back.", repeat=False)
    ref = timers.timer_ref(t.id)

    body = (await client.get(f"/api/chats/{chat_id}/timers")).json()
    assert [x["id"] for x in body["timers"]] == [ref] and body["timers"][0]["fire_at_utc"]

    r = await client.post(f"/api/chats/{chat_id}/timers/{ref}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert (await client.post(f"/api/chats/{chat_id}/timers/{ref}/cancel")).status_code == 404
    assert (await client.get(f"/api/chats/{chat_id}/timers")).json()["timers"] == []


@pytest.mark.asyncio
async def test_stop_ends_the_chats_timers(client, db_session, monkeypatch):
    from unittest.mock import AsyncMock
    from agent.v2 import timers
    from database import AgentTimer
    monkeypatch.setattr("agent.abort_plan", AsyncMock())
    chat_id = await _chat(db_session)
    async with db_session() as s:
        t = await timers.create_timer(s, chat_id, minutes=10, note="Keep going.", repeat=True)
    assert (await client.post(f"/api/chats/{chat_id}/stop", json={})).status_code == 200
    async with db_session() as s:
        assert (await s.get(AgentTimer, t.id)).end_reason == "stopped"


def test_long_runs_show_the_clock_on_tool_results():
    from agent.v2.conversation import _items_to_messages
    from database import ChatItem
    t0 = datetime(2026, 11, 20, 2, 0)

    def item(minutes, **kw):
        return ChatItem(created_at=t0 + timedelta(minutes=minutes), **kw)

    items = [
        item(0, item_type="user_message", message_text="Keep going all night."),
        item(0.5, item_type="tool_call", tool_call_id="a", tool_name="run_code", tool_args="{}"),
        item(1, item_type="tool_result", tool_call_id="a", tool_result="first"),
        item(30, item_type="tool_call", tool_call_id="b", tool_name="run_code", tool_args="{}"),
        item(31, item_type="tool_result", tool_call_id="b", tool_result="second"),
        item(32, item_type="tool_call", tool_call_id="c", tool_name="run_code", tool_args="{}"),
        item(33, item_type="tool_result", tool_call_id="c", tool_result="third"),
        # A timer wake is not the user speaking: elapsed keeps counting from 02:00.
        item(150, item_type="user_message", message_text="<timer>...</timer>",
             item_metadata=json.dumps({"timer": {"id": "timer-1"}})),
        item(156, item_type="tool_call", tool_call_id="d", tool_name="run_code", tool_args="{}"),
        item(157, item_type="tool_result", tool_call_id="d", tool_result="fourth"),
    ]
    results = {m["tool_call_id"]: m["content"] for m in _items_to_messages(items, "sys") if m["role"] == "tool"}
    assert results["a"] == "first"  # a minute in: nothing to say
    assert "[Current date/time:" in results["b"] and "31 min since the user's last message" in results["b"]
    assert results["c"] == "third"  # stamped two minutes ago
    assert "2 h 37 min since the user's last message" in results["d"]
    # Same items, same text: the cached prefix holds across rebuilds.
    again = {m["tool_call_id"]: m["content"] for m in _items_to_messages(items, "sys") if m["role"] == "tool"}
    assert again == results


@pytest.mark.asyncio
async def test_stop_after_a_firing_is_claimed_records_it_without_waking(db_session, fire, monkeypatch):
    from agent.v2 import timers
    chat_id = await _chat(db_session)
    async with db_session() as s:
        t = await timers.create_timer(s, chat_id, minutes=10, note="Keep going.", repeat=True)
    await _make_due(db_session, t.id)

    real_create_task = __import__("asyncio").create_task

    def stop_then_deliver(coro):
        timers.note_stop(chat_id)  # the user presses Stop between claim and delivery
        return real_create_task(coro)

    monkeypatch.setattr("agent.v2.timers.asyncio.create_task", stop_then_deliver)
    assert await fire() == 1
    (_, _, wake), = fire.delivered
    assert wake is False


@pytest.mark.asyncio
async def test_code_started_before_stop_cannot_set_a_timer(db_session, tmp_path):
    from agent.v2 import timers
    from agent.v2.code_runtime import StimmaSDK
    chat_id = await _chat(db_session)
    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        timers.note_stop(chat_id)
        with pytest.raises(RuntimeError, match="Stop"):
            await sdk.timers.set(10, "Keep going.", repeat=True)
        later = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                          project_workspace_dir=None, interrupt_checker=lambda: False)
        assert (await later.timers.set(10, "Keep going.", repeat=True))["state"] == "active"
        await later.timers.cancel()


def test_image_results_carry_the_clock_in_their_text_block():
    from agent.v2.conversation import _RunClock
    from database import ChatItem
    t0 = datetime(2026, 11, 20, 2, 0)
    clock = _RunClock()
    clock.observe(ChatItem(item_type="user_message", created_at=t0), {"role": "user", "content": "x"})
    msg = {"role": "tool", "content": [
        {"type": "text", "text": "Image loaded."},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]}
    clock.observe(ChatItem(item_type="tool_result", created_at=t0 + timedelta(minutes=40)), msg)
    assert "40 min since the user's last message" in msg["content"][0]["text"]
    assert msg["content"][1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_stop_that_sweeps_while_set_waits_on_the_database_still_wins(db_session, tmp_path, monkeypatch):
    from agent.v2 import timers
    from agent.v2.code_runtime import StimmaSDK
    from database import AgentTimer
    chat_id = await _chat(db_session)
    real_create = timers.create_timer

    async def slow_create(session, cid, **kw):
        # The check passed; Stop lands while the insert waits for the write lock.
        timers.note_stop(cid)
        return await real_create(session, cid, **kw)

    monkeypatch.setattr(timers, "create_timer", slow_create)
    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        with pytest.raises(RuntimeError, match="Stop"):
            await sdk.timers.set(10, "Keep going.", repeat=True)
    async with db_session() as s:
        rows = (await s.execute(select(AgentTimer).where(AgentTimer.chat_id == chat_id))).scalars().all()
    assert [r.end_reason for r in rows] == ["stopped"]


@pytest.mark.asyncio
async def test_stop_that_cancels_set_right_after_its_commit_still_ends_the_timer(db_session, tmp_path, monkeypatch):
    import asyncio
    from agent.v2 import timers
    from agent.v2.code_runtime import StimmaSDK
    from database import AgentTimer
    chat_id = await _chat(db_session)
    real_create = timers.create_timer

    async def create_then_cancelled(session, cid, **kw):
        timers.note_stop(cid)  # Stop sweeps before the insert commits...
        await real_create(session, cid, **kw)
        raise asyncio.CancelledError  # ...and cancels this code just after it

    monkeypatch.setattr(timers, "create_timer", create_then_cancelled)
    async with db_session() as session:
        sdk = StimmaSDK(session=session, chat_id=chat_id, workspace_dir=tmp_path,
                        project_workspace_dir=None, interrupt_checker=lambda: False)
        with pytest.raises(asyncio.CancelledError):
            await sdk.timers.set(10, "Keep going.", repeat=True)
    for _ in range(20):
        await asyncio.sleep(0.01)
    async with db_session() as s:
        rows = (await s.execute(select(AgentTimer).where(AgentTimer.chat_id == chat_id))).scalars().all()
    assert [r.end_reason for r in rows] == ["stopped"]

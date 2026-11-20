"""Result cards: a run's generations land in one chat card, filled in place.

A gather over N calls is a batch with N slots and a count; a gather of workers
or ``stimma.stream`` is open-ended and has no count; ``stimma.batch(total=N)``
declares the count for calls made in a loop. Showing the results claims the
card instead of making a second one.
"""
import asyncio
import json

import pytest
from sqlalchemy import select

import agent.v2.code_runtime as code_runtime
from agent.v2.background import GenerationCancelled, RunControl
from agent.v2.code_runtime import StimmaSDK
from database import Chat, ChatItem
from tests.helpers.media import create_media_item


@pytest.fixture
def generation(monkeypatch):
    """execute_call_tool stand-in. Calls finish at once unless their prompt is
    in ``held`` (then they wait for its event); prompts in ``failing`` fail."""
    state = {"media": iter(()), "held": {}, "failing": set(), "next_job": iter(range(1, 1000))}

    async def fake_execute_call_tool(*, tool_id, parameters, cancel_checker, on_job_submitted, **kwargs):
        if cancel_checker():
            raise GenerationCancelled("Cancelled before it started")
        on_job_submitted(next(state["next_job"]))
        prompt = parameters.get("prompt")
        if prompt in state["held"]:
            await state["held"][prompt].wait()
        if prompt in state["failing"]:
            raise RuntimeError("out of memory")
        media_id = next(state["media"])
        return {"path": f"out-{media_id}.png", "media_id": media_id, "tool_id": tool_id}

    async def allow(**kwargs):
        return None

    monkeypatch.setattr(code_runtime, "execute_call_tool", fake_execute_call_tool)
    monkeypatch.setattr("agent.v2.tool_permission_gate.ensure_tool_permission", allow)
    monkeypatch.setattr("mcp_server.jobs.check_execution", lambda: None)
    return state


async def _setup(db_session, generation, tmp_path, n_media=8):
    async with db_session() as session:
        chat = Chat(name="Result cards")
        session.add(chat)
        await session.commit()
        media_ids = [(await create_media_item(session)).id for _ in range(n_media)]
        await session.commit()
    generation["media"] = iter(media_ids)
    session = db_session()
    sdk = StimmaSDK(session=session, chat_id=chat.id, workspace_dir=tmp_path,
                    project_workspace_dir=None, interrupt_checker=lambda: False, control=RunControl())
    return sdk, chat.id, media_ids


async def _cards_in_chat(db_session, chat_id):
    async with db_session() as session:
        items = (await session.execute(
            select(ChatItem).where(ChatItem.chat_id == chat_id, ChatItem.item_type.in_(["media_display", "progress_display"]))
        )).scalars().all()
        return [(i.item_type, i.show_role, json.loads(i.item_metadata)["display_data"]) for i in items]


def _statuses(card):
    return [row["output"]["status"] for row in card.display_data()["rows"]]


@pytest.mark.asyncio
async def test_a_gather_is_one_card_whose_slots_fill_in_place(db_session, generation, tmp_path):
    sdk, chat_id, media = await _setup(db_session, generation, tmp_path)
    first = asyncio.Event()
    generation["held"] = {"a": first}
    task = asyncio.create_task(sdk._gather(*[sdk._dispatch_tool("mock:gen", prompt=p) for p in "abc"]))
    for _ in range(50):
        await asyncio.sleep(0)
    (card,) = sdk._cards
    data = card.display_data()
    # Every slot is there from the start; the second and third finished first.
    assert data["mode"] == "batch" and data["total"] == 3
    assert _statuses(card) == ["pending", "complete", "complete"]
    await sdk._flush_cards()
    assert sdk._control.progress == {"title": "3 results", "done": 2, "failed": 0, "total": 3}
    first.set()
    await task
    assert _statuses(card) == ["complete"] * 3
    assert [row["output"]["media_id"] for row in card.display_data()["rows"]] == [media[2], media[0], media[1]]


@pytest.mark.asyncio
async def test_a_failure_keeps_its_slot(db_session, generation, tmp_path):
    sdk, _, _ = await _setup(db_session, generation, tmp_path)
    generation["failing"] = {"b"}
    results = await sdk._gather(*[sdk._dispatch_tool("mock:gen", prompt=p) for p in "abc"], return_exceptions=True)
    assert isinstance(results[1], RuntimeError)
    (card,) = sdk._cards
    assert _statuses(card) == ["complete", "failed", "complete"]
    assert card.summary()["failed"] == 1


@pytest.mark.asyncio
async def test_a_gather_of_workers_is_open_ended(db_session, generation, tmp_path):
    sdk, _, _ = await _setup(db_session, generation, tmp_path)
    prompts = [f"shot {n}" for n in range(5)]

    async def worker():
        while prompts:
            await sdk._dispatch_tool("mock:gen", prompt=prompts.pop())

    await sdk._gather(worker(), worker(), worker())
    (card,) = sdk._cards
    data = card.display_data()
    # Its total would only be the calls started so far, so it has none.
    assert data["mode"] == "stream" and "total" not in data
    assert _statuses(card) == ["complete"] * 5
    assert card.summary() == {"title": "Results", "open": True}


@pytest.mark.asyncio
async def test_a_declared_batch_keeps_its_count_with_workers(db_session, generation, tmp_path):
    sdk, _, _ = await _setup(db_session, generation, tmp_path)
    prompts = [f"shot {n}" for n in range(5)]
    held = asyncio.Event()
    generation["held"] = {"shot 4": held}

    async def worker():
        while prompts:
            await sdk._dispatch_tool("mock:gen", prompt=prompts.pop())

    with sdk.batch("Dance videos", total=5):
        task = asyncio.create_task(sdk._gather(worker(), worker()))
        for _ in range(50):
            await asyncio.sleep(0)
        (card,) = sdk._cards
        assert card.summary() == {"title": "Dance videos", "done": 4, "failed": 0, "total": 5}
        held.set()
        await task
    assert card.display_data()["mode"] == "batch"
    assert card.status == "complete"


@pytest.mark.asyncio
async def test_a_stream_has_no_count(db_session, generation, tmp_path):
    sdk, _, _ = await _setup(db_session, generation, tmp_path)
    with sdk.stream("Market vendors"):
        for n in range(3):
            await sdk._dispatch_tool("mock:gen", prompt=f"vendor {n}")
    (card,) = sdk._cards
    assert card.display_data()["mode"] == "stream"
    assert card.summary() == {"title": "Market vendors", "open": True}


@pytest.mark.asyncio
async def test_batch_after_batch_grows_one_open_ended_card(db_session, generation, tmp_path):
    sdk, _, _ = await _setup(db_session, generation, tmp_path)
    for batch in range(2):
        await sdk._gather(*[sdk._dispatch_tool("mock:gen", prompt=f"{batch}-{n}") for n in range(3)])
    (card,) = sdk._cards
    assert card.display_data()["mode"] == "stream"
    assert len(card.display_data()["rows"]) == 6


@pytest.mark.asyncio
async def test_a_gather_that_generates_nothing_puts_no_card_in_the_chat(db_session, generation, tmp_path):
    sdk, chat_id, _ = await _setup(db_session, generation, tmp_path)

    async def think(n):
        await asyncio.sleep(0)
        return n

    assert await sdk._gather(think(1), think(2)) == [1, 2]
    await sdk._finalize_progress("completed")
    assert await _cards_in_chat(db_session, chat_id) == []


@pytest.mark.asyncio
async def test_showing_the_results_claims_the_card(db_session, generation, tmp_path):
    sdk, chat_id, media = await _setup(db_session, generation, tmp_path)
    results = await sdk._gather(*[sdk._dispatch_tool("mock:gen", prompt=p) for p in "abc"])
    await sdk._flush_cards()
    sdk.show(results, role="final", title="Dance videos")
    await sdk.flush()
    await sdk._finalize_progress("completed")

    # One card, not a progress card plus a results card.
    (kind, role, data), = await _cards_in_chat(db_session, chat_id)
    assert (kind, role, data["title"], data["status"]) == ("media_display", "final", "Dance videos", "complete")
    assert [row["output"]["media_id"] for row in data["rows"]] == media[:3]
    assert all(row["output"].get("asset_id") for row in data["rows"])
    assert sdk._display_receipts and "asset_id=" in sdk._display_receipts[0]


@pytest.mark.asyncio
async def test_shows_as_results_land_grow_the_same_card(db_session, generation, tmp_path):
    sdk, chat_id, media = await _setup(db_session, generation, tmp_path)

    async def make(p):
        r = await sdk._dispatch_tool("mock:gen", prompt=p)
        sdk.show(r, role="final", title="Vendors")
        await sdk._flush_display_live()
        return r

    with sdk.stream("Vendors"):
        await sdk._gather(make("a"), make("b"))
    await sdk.flush()
    await sdk._finalize_progress("completed")
    (_, role, data), = await _cards_in_chat(db_session, chat_id)
    assert role == "final" and data["mode"] == "stream"
    assert sorted(row["output"]["media_id"] for row in data["rows"]) == sorted(media[:2])


@pytest.mark.asyncio
async def test_a_result_landing_during_the_job_check_stays_finished():
    from agent.v2.background import CallItem
    from agent.v2.result_cards import ResultCard

    card = ResultCard(total=1)
    slot = card.begin(None, CallItem(item=1, tool="t", prompt=None, job_id=7), None)

    class _Result:
        def all(self):
            return [(7, "processing")]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, query):
            card.done(slot, 42, "out.png")  # the call finishes while the queue is asked
            return _Result()

    await card.refresh_job_states(lambda: _Session())
    assert slot.status == "complete" and slot.media_id == 42


@pytest.mark.asyncio
async def test_a_failed_slot_offers_retry_only_once_the_run_ends(db_session, generation, tmp_path):
    sdk, _, _ = await _setup(db_session, generation, tmp_path)
    generation["failing"] = {"b"}
    await sdk._gather(*[sdk._dispatch_tool("mock:gen", prompt=p) for p in "ab"], return_exceptions=True)
    (card,) = sdk._cards
    # Between gathers the run still owns the card: a later gather can reopen it.
    assert "job_id" not in card.display_data()["rows"][1]["output"]
    await sdk._finalize_progress("completed")
    assert card.display_data()["rows"][1]["output"]["job_id"]


@pytest.mark.asyncio
async def test_tasks_made_before_the_gather_still_fill_its_card(db_session, generation, tmp_path):
    sdk, _, media = await _setup(db_session, generation, tmp_path)
    tasks = [asyncio.create_task(sdk._dispatch_tool("mock:gen", prompt=p)) for p in "ab"]
    await sdk._gather(*tasks)
    (card,) = sdk._cards
    assert sorted(row["output"]["media_id"] for row in card.display_data()["rows"]) == sorted(media[:2])
    assert card.live

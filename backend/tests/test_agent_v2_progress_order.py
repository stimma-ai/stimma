import asyncio

import pytest

from agent.v2.code_runtime import StimmaSDK


def make_sdk(tmp_path):
    return StimmaSDK(
        session=None, chat_id=None, workspace_dir=tmp_path,
        project_workspace_dir=tmp_path, interrupt_checker=lambda: False,
    )


async def preview(sdk, mid, gate=None):
    if gate is not None:
        await gate.wait()
    for tracker in sdk._progress_trackers:
        if not tracker._completed:
            tracker._add_preview(mid)
    return mid


@pytest.mark.asyncio
async def test_progress_slots_fill_in_request_order_before_batch_finishes(tmp_path):
    sdk = make_sdk(tmp_path)
    first = asyncio.Event()
    batch = asyncio.create_task(sdk._gather(preview(sdk, 10, first), preview(sdk, 20)))
    for _ in range(3):
        await asyncio.sleep(0)
    tracker = sdk._progress_trackers[0]
    partial = tracker._build_state()["display_data"]
    assert partial["previews"] == [20]
    assert partial["preview_slots"] == [
        {"media_ids": [], "status": "pending"},
        {"media_ids": [20], "status": "completed"},
    ]
    first.set()
    assert await batch == [10, 20]
    assert tracker._build_state()["display_data"]["previews"] == [10, 20]
    assert partial["preview_slots"][0]["media_ids"] == []  # published snapshots are immutable


@pytest.mark.asyncio
async def test_concurrent_batches_do_not_mix_previews(tmp_path):
    sdk = make_sdk(tmp_path)
    a, b = await asyncio.gather(
        sdk._gather(preview(sdk, 1), preview(sdk, 2)),
        sdk._gather(preview(sdk, 3), preview(sdk, 4)),
    )
    assert [t._previews for t in sdk._progress_trackers] == [a, b]


@pytest.mark.asyncio
async def test_failed_option_retains_its_slot_and_exception_position(tmp_path):
    sdk = make_sdk(tmp_path)

    async def fail():
        raise ValueError("generation failed")

    results = await sdk._gather(preview(sdk, 1), fail(), preview(sdk, 3), return_exceptions=True)
    assert results[0] == 1 and results[2] == 3
    assert isinstance(results[1], ValueError)
    state = sdk._progress_trackers[0]._build_state()["display_data"]
    assert state["preview_slots"][1] == {"media_ids": [], "status": "error"}
    assert state["previews"] == [1, 3]
    assert state["status"] == "error"
    sdk._progress_trackers[0]._mark_completed("completed")
    assert sdk._progress_trackers[0]._build_state()["display_data"]["status"] == "error"


@pytest.mark.asyncio
async def test_nested_gather_preserves_outer_option_order(tmp_path):
    sdk = make_sdk(tmp_path)
    first = asyncio.Event()
    task = asyncio.create_task(sdk._gather(
        sdk._gather(preview(sdk, 1, first), preview(sdk, 2)),
        preview(sdk, 3),
    ))
    for _ in range(4):
        await asyncio.sleep(0)
    first.set()
    await task
    outer, inner = sdk._progress_trackers
    assert outer._previews == [1, 2, 3]
    assert inner._previews == [1, 2]


@pytest.mark.asyncio
async def test_cancelled_batch_retains_completed_preview_and_slot_identities(tmp_path):
    sdk = make_sdk(tmp_path)
    pending = asyncio.Event()
    task = asyncio.create_task(sdk._gather(preview(sdk, 1), preview(sdk, 2, pending)))
    for _ in range(3):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = sdk._progress_trackers[0]._build_state()["display_data"]
    assert state["status"] == "cancelled"
    assert state["preview_slots"] == [
        {"media_ids": [1], "status": "completed"},
        {"media_ids": [], "status": "cancelled"},
    ]

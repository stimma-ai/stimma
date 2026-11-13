"""A batch's children are queued as soon as each one's prompt is ready.

POST /api/generate/submit-batch with a fake improve model: a slow child doesn't hold up
the others, a child whose improve fails is a failed job of the batch while the rest run,
and a failure every child would share fails the submit before anything is queued.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import routes.prompt_enhancement as pe
from tests.helpers.media import create_media_item


async def _three_item_set(generation_db_session) -> int:
    async with generation_db_session() as session:
        items = [await create_media_item(session, file_format='png') for _ in range(3)]
        set_item = await create_media_item(session, file_format='stimmaset.json', raw_metadata=json.dumps({
            "version": 1,
            "items": [{"path": m.file_path, "resolved": {"id": m.id, "file_format": "png"}} for m in items],
        }))
        return set_item.id


def _queue():
    queue = AsyncMock()
    queued = []
    ready = asyncio.Event()

    async def submit(**kwargs):
        queued.append(kwargs)
        ready.set()
        return 100 + kwargs["parameters"]["_batch_index"]

    queue.submit_batch_job = AsyncMock(side_effect=submit)
    queue.submit_failed_batch_job = AsyncMock(side_effect=lambda **kw: 200 + kw["parameters"]["_batch_index"])
    return queue, queued, ready


def _submit(set_id: int, prompt_options: dict, prompt: str = "paint it"):
    return {
        "tool_id": "test:upscale",
        "folder_path": "/tmp/test",
        "task_type": "upscale",
        "client_ref": "tile-1",
        "parameters": {"input_image": {"set_id": set_id}, "prompt": prompt},
        "prompt_options": prompt_options,
    }


ENHANCE = {"autoImprove": {"enabled": True, "model": "Test Upscale"}}


async def test_a_ready_child_is_queued_while_another_is_still_improving(generation_client, generation_db_session):
    set_id = await _three_item_set(generation_db_session)
    queue, queued, ready = _queue()
    calls = 0

    async def improve(request, session):
        nonlocal calls
        calls += 1
        if calls == 1:
            # The slow child: answers only once another child has been queued.
            await asyncio.wait_for(ready.wait(), timeout=5)
            return pe.ImprovePromptResponse(improved_prompt="slow")
        return pe.ImprovePromptResponse(improved_prompt=f"fast {calls}")

    with (
        patch('generation_queue.get_generation_queue', return_value=queue),
        patch.object(pe, "improve_prompt", side_effect=improve),
    ):
        response = await generation_client.post("/api/generate/submit-batch", json=_submit(set_id, ENHANCE))

    assert response.status_code == 200, response.text
    assert len(queued) == 3
    assert queued[-1]["parameters"]["prompt"] == "slow"
    assert queued[0]["parameters"]["prompt"].startswith("fast")
    # The first job queued carries the batch's total, whichever child it is.
    assert [q["batch_total"] for q in queued] == [3, None, None]
    assert response.json()["job_ids"] == [100, 101, 102]
    queue.submit_failed_batch_job.assert_not_called()


async def test_a_child_whose_improve_raises_fails_alone(generation_client, generation_db_session):
    set_id = await _three_item_set(generation_db_session)
    queue, queued, _ = _queue()
    calls = 0

    async def improve(request, session):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(status_code=502, detail={
                "code": "prompt_enhancement_failed", "message": "The tool assistant returned an empty prompt."})
        return pe.ImprovePromptResponse(improved_prompt=f"improved {calls}")

    with (
        patch('generation_queue.get_generation_queue', return_value=queue),
        patch.object(pe, "improve_prompt", side_effect=improve),
    ):
        response = await generation_client.post("/api/generate/submit-batch", json=_submit(set_id, ENHANCE))

    assert response.status_code == 200, response.text
    assert len(queued) == 2
    failed = queue.submit_failed_batch_job.await_args.kwargs
    assert failed["error"] == "The tool assistant returned an empty prompt."
    assert failed["client_ref"] == "tile-1"
    assert sorted(response.json()["job_ids"]) == sorted([q["parameters"]["_batch_index"] + 100 for q in queued]
                                                        + [failed["parameters"]["_batch_index"] + 200])
    queue.settle_batch.assert_awaited_once()


async def test_a_slot_reading_failure_queues_nothing(generation_client, generation_db_session):
    from prompt_programs.reader import ReaderFailed

    set_id = await _three_item_set(generation_db_session)
    queue, queued, _ = _queue()
    ensure = AsyncMock(side_effect=ReaderFailed("the reading could not be used"))
    pipeline = AsyncMock()
    options = {"program": {"enabled": True}, "autoImprove": {"enabled": True}}
    # A set's image is an edit input, which Fluent doesn't vary; a tool it does (image to
    # video, say) is what this stands for.
    import routes.generation as gen
    real_context = gen.prompt_enhance_context

    def supported(*args, **kwargs):
        return {**real_context(*args, **kwargs), "program_supported": True}

    with (
        patch('generation_queue.get_generation_queue', return_value=queue),
        patch('routes.generation.prompt_enhance_context', side_effect=supported),
        patch('prompt_programs.slots.ensure', new=ensure),
        patch('routes.generation._apply_generation_prompt_pipeline', new=pipeline),
    ):
        response = await generation_client.post(
            "/api/generate/submit-batch", json=_submit(set_id, options, prompt="a <young man> in a cafe"))

    assert response.status_code == 424, response.text
    assert response.json()["detail"]["code"] == "reader_failed"
    ensure.assert_awaited_once()  # once for the batch, before any child
    pipeline.assert_not_called()
    assert queued == []
    queue.submit_failed_batch_job.assert_not_called()


async def test_no_chat_model_queues_nothing(generation_client, generation_db_session):
    set_id = await _three_item_set(generation_db_session)
    queue, queued, _ = _queue()
    improve = AsyncMock(side_effect=HTTPException(status_code=424, detail={
        "code": "llm_not_configured", "message": "No chat model is set up."}))

    with (
        patch('generation_queue.get_generation_queue', return_value=queue),
        patch.object(pe, "improve_prompt", new=improve),
    ):
        response = await generation_client.post("/api/generate/submit-batch", json=_submit(set_id, ENHANCE))

    # Every child fails the same way: the submit fails with it and nothing is queued.
    assert response.status_code == 424, response.text
    assert response.json()["detail"]["code"] == "llm_not_configured"
    assert queued == []
    queue.submit_failed_batch_job.assert_not_called()
    queue.settle_batch.assert_not_called()


async def test_a_failed_child_job_is_announced_like_a_failed_job(generation_app, generation_queue, generation_db_session):
    from sqlalchemy import select

    from database import GenerationJob

    ws = generation_app.state.mock_ws
    ws.broadcasts.clear()
    job_id = await generation_queue.submit_failed_batch_job(
        error="The tool assistant returned an empty prompt.",
        generator_name="test", model_name="test-model", folder_path="/tmp/test",
        parameters={"prompt": "paint it", "_batch_index": 0, "_batch_presentation_only": True},
        generator_instance_id="tool-view-1", backend_name="test", task_type="text-to-image",
        tool_id="test:text-to-image:test-model", batch_id="batch-failed-child", batch_total=1,
        consume_pending_request=False, client_ref="tile-1",
    )

    async with generation_db_session() as session:
        job = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one()
        assert job.status == "failed"
        assert job.error == "The tool assistant returned an empty prompt."
        assert job.completed_at is not None
    events = [event for event, _ in ws.broadcasts]
    assert "generation_job_queued" not in events
    failed = next(data for event, data in ws.broadcasts if event == "generation_job_failed")
    assert failed["job"]["id"] == job_id
    assert failed["client_ref"] == "tile-1"
    assert failed["generator_instance_id"] == "tool-view-1"

    await generation_queue.settle_batch("batch-failed-child")
    closed = next(data for event, data in ws.broadcasts if event == "batch_completed")
    assert closed["status"] == "failed"
    assert closed["total"] == 1

"""Post-processing chain executor: filter-step execution, lineage recording,
media-type validation, pause-on-failure, and Retry."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from database import GenerationJob, MediaItem, MediaLineage, PostProcessingChainRun
from postprocessing.executor import start_chain_for_job, CHAIN_INSTANCE_ID
from tests.helpers.media import create_media_item, generate_test_image


# loop_scope="function": the worker tasks must live on the TEST's event loop
# (the project default puts async fixtures on the module loop, which doesn't
# run while a test is executing — workers would be frozen).
@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def queue_workers(generation_app):
    """Filter steps run as builtin tools through the generation queue, so
    these tests need live queue workers (other modules process jobs manually)."""
    queue = generation_app.state.generation_queue
    await queue.start_workers(num_workers=2)
    yield
    await queue.stop_workers()


def _fake_job(job_id=99001, instance_id="client-test"):
    return SimpleNamespace(id=job_id, project_id=None, generator_instance_id=instance_id)


async def _make_base_media(session_factory, tmp_dir: Path, name: str, size=(96, 64)):
    path = tmp_dir / name
    file_hash = generate_test_image(path, width=size[0], height=size[1], color=(120, 180, 90))
    async with session_factory() as session:
        media = await create_media_item(
            session,
            file_path=path,
            file_hash=file_hash,
            file_format="png",
            width=size[0],
            height=size[1],
        )
        await session.commit()
        return media


async def _wait_for_run(session_factory, run_id: int, statuses=("completed", "paused", "failed"), timeout=15.0):
    run = None
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with session_factory() as session:
            result = await session.execute(
                select(PostProcessingChainRun).where(PostProcessingChainRun.id == run_id)
            )
            run = result.scalar_one_or_none()
        if run and run.status in statuses:
            return run
        await asyncio.sleep(0.05)
    raise TimeoutError(f"Chain run {run_id} did not reach {statuses} in {timeout}s (status={run.status if run else 'missing'})")


async def _wait_for_job_result_media(session_factory, job_id: int, expected_media_id: int, timeout=15.0):
    # The base job is repointed at the chain's final media AFTER the run flips to
    # "completed" (see executor._finalize_base_job), in a separate commit. Poll for
    # that follow-up write instead of racing it.
    deadline = asyncio.get_event_loop().time() + timeout
    refreshed = None
    while asyncio.get_event_loop().time() < deadline:
        async with session_factory() as session:
            result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
            refreshed = result.scalar_one()
        if refreshed.result_media_id == expected_media_id:
            return refreshed
        await asyncio.sleep(0.05)
    return refreshed


class TestChainExecutorFilters:
    async def test_filter_chain_runs_to_completion(self, generation_app, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_base.png")

        steps = [
            {"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 48}},
            {"kind": "filter", "filter_id": "filter", "settings": {"filter": "mono"}},
        ]
        run_id = await start_chain_for_job(
            job=_fake_job(),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        assert run_id is not None

        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "completed"
        assert run.final_media_id and run.final_media_id != base.id

        step_results = json.loads(run.step_results)
        assert [r["status"] for r in step_results] == ["done", "done"]
        assert all(r.get("media_id") for r in step_results)
        assert all(r.get("duration_ms") is not None for r in step_results)

        # Final media: mono (grayscale) and resized to 48px long edge
        async with generation_db_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == run.final_media_id)
            )
            final = result.scalar_one()
        with Image.open(final.file_path) as img:
            assert max(img.size) == 48
            rgb = img.convert("RGB")
            r, g, b = rgb.getpixel((10, 10))
            assert r == g == b  # mono filter output is gray

        # Lineage: final derives from the intermediate, intermediate from base
        intermediate_id = step_results[0]["media_id"]
        async with generation_db_session() as session:
            result = await session.execute(
                select(MediaLineage.source_media_id).where(MediaLineage.media_id == run.final_media_id)
            )
            assert [row[0] for row in result.fetchall()] == [intermediate_id]
            result = await session.execute(
                select(MediaLineage.source_media_id).where(MediaLineage.media_id == intermediate_id)
            )
            assert [row[0] for row in result.fetchall()] == [base.id]

        # The chain record rides each filter output's generation_metadata so
        # Remix from any chained image restores the chain.
        meta = json.loads(final.generation_metadata)
        assert meta["parameters"]["post_processing_chain"] == steps
        assert meta["task_type"] == "filter"
        # Filters are ordinary builtin catalog tools — recorded like any tool
        # invocation, never attributed to the image editor.
        assert "image-editor" not in (final.generation_metadata or "")
        assert meta.get("tool_id") == "builtin:filter"
        assert meta["parameters"].get("filter") == "mono"
        # The trace inherits the input's history: base, then the intermediate.
        trace_ids = [e.get("media_id") for e in meta["lineage_trace"]]
        assert trace_ids == [base.id, intermediate_id]

    async def test_final_media_generation_time_includes_full_chain(self, generation_app, generation_db_session, mock_ws, tmp_path):
        # The result-tile duration must reflect base generation + every
        # executed post-processing step, not just the last step's own
        # (typically tiny) compute time.
        base_generation_time = 4.75
        base = await _make_base_media(generation_db_session, tmp_path, "chain_duration_base.png")
        async with generation_db_session() as session:
            result = await session.execute(select(MediaItem).where(MediaItem.id == base.id))
            media = result.scalar_one()
            media.generation_metadata = json.dumps({"parameters": {"generation_time": base_generation_time}})
            await session.commit()

        steps = [
            {"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 48}},
            {"kind": "filter", "filter_id": "filter", "settings": {"filter": "mono"}},
        ]
        run_id = await start_chain_for_job(
            job=_fake_job(),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "completed"

        step_results = json.loads(run.step_results)
        steps_total_seconds = sum(
            r["duration_ms"] for r in step_results if r["status"] == "done"
        ) / 1000.0

        async with generation_db_session() as session:
            result = await session.execute(select(MediaItem).where(MediaItem.id == run.final_media_id))
            final = result.scalar_one()
        total = json.loads(final.generation_metadata)["parameters"]["generation_time"]

        assert total >= base_generation_time
        assert total == pytest.approx(base_generation_time + steps_total_seconds, abs=0.05)

    async def test_completed_chain_points_base_job_at_final_media(self, generation_app, generation_db_session, mock_ws, tmp_path):
        # The base job IS the result-strip item: when its chain completes, the
        # job's result_media_id becomes the chain's final output.
        base = await _make_base_media(generation_db_session, tmp_path, "chain_jobptr.png")

        async with generation_db_session() as session:
            job = GenerationJob(
                status="completed",
                task_type="text-to-image",
                generator_type="test",
                generator_name="test",
                model_name="Test Tool",
                parameters="{}",
                folder_path=str(tmp_path),
                generator_instance_id="client-test",
                result_media_id=base.id,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        steps = [{"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 32}}]
        run_id = await start_chain_for_job(
            job=_fake_job(job_id=job_id),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "completed"
        assert run.final_media_id != base.id

        refreshed = await _wait_for_job_result_media(generation_db_session, job_id, run.final_media_id)
        assert refreshed.result_media_id == run.final_media_id

    async def test_incompatible_step_is_skipped_not_failed(self, generation_app, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_skip.png")

        # upscale-video needs a video input; chain output is an image → skip + flag
        steps = [
            {"kind": "tool", "tool_id": "test:upscale-video", "task_type": "upscale-video", "settings": {}},
            {"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 32}},
        ]
        run_id = await start_chain_for_job(
            job=_fake_job(job_id=99002),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "completed"
        step_results = json.loads(run.step_results)
        assert step_results[0]["status"] == "skipped_incompatible"
        assert step_results[1]["status"] == "done"
        assert run.final_media_id == step_results[1]["media_id"]

        # Lineage records only steps that actually ran — the skipped step
        # never happened and must not show up in the recorded chain.
        async with generation_db_session() as session:
            result = await session.execute(
                select(MediaItem).where(MediaItem.id == run.final_media_id)
            )
            final = result.scalar_one()
        meta = json.loads(final.generation_metadata)
        assert meta["parameters"]["post_processing_chain"] == [steps[1]]

    async def test_failure_pauses_and_keeps_last_good(self, generation_app, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_fail.png")

        steps = [
            {"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 40}},
            {"kind": "filter", "filter_id": "filter", "settings": {"filter": "not-a-filter"}},
        ]
        run_id = await start_chain_for_job(
            job=_fake_job(job_id=99003),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "paused"
        assert run.error
        assert run.step_index == 1

        step_results = json.loads(run.step_results)
        assert step_results[0]["status"] == "done"
        assert step_results[1]["status"] == "failed"
        # Last good media is the step-0 output, not the base
        assert run.last_good_media_id == step_results[0]["media_id"]

    async def test_retry_resumes_from_failed_step(self, generation_app, generation_client, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_retry.png")

        steps = [{"kind": "filter", "filter_id": "filter", "settings": {"filter": "not-a-filter"}}]
        run_id = await start_chain_for_job(
            job=_fake_job(job_id=99004),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "paused"

        resp = await generation_client.post(f"/api/postprocessing/runs/{run_id}/retry")
        assert resp.status_code == 200
        # Same broken step: the retry machinery re-runs it and pauses again.
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "paused"

    async def test_retry_completed_run_is_rejected(self, generation_app, generation_client, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_done.png")
        steps = [{"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 32}}]
        run_id = await start_chain_for_job(
            job=_fake_job(job_id=99005),
            base_media_id=base.id,
            chain_steps=steps,
            profile_id="default",
            websocket_manager=mock_ws,
        )
        run = await _wait_for_run(generation_db_session, run_id)
        assert run.status == "completed"

        resp = await generation_client.post(f"/api/postprocessing/runs/{run_id}/retry")
        assert resp.status_code == 409

    async def test_runs_listing_endpoint(self, generation_app, generation_client, generation_db_session, mock_ws, tmp_path):
        resp = await generation_client.get("/api/postprocessing/runs?status=paused,running")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert all(r["status"] in ("paused", "running") for r in runs)


class TestChainPromptPipeline:
    """Chain-step prompts run the SAME generate-time pipeline as an interactive
    submit (prompt_pipeline.py — covered in depth by test_prompt_pipeline.py);
    these tests cover the executor's threading of it."""

    async def test_tool_step_sends_rewritten_prompt(self, generation_app, generation_db_session, monkeypatch):
        import agent.v2.tools.call_tool as call_tool_mod
        import postprocessing.executor as executor_mod

        seen = {}

        async def fake_execute_call_tool(**kwargs):
            seen["parameters"] = kwargs["parameters"]
            return {"media_id": 4242}

        async def fake_pipeline(db, prompt, prompt_options, tool_id, task_type, input_media_id,
                                parameters=None, profile_id=None):
            seen["prompt_options"] = prompt_options
            seen["profile_id"] = profile_id
            return prompt + " [ENHANCED]"

        monkeypatch.setattr(call_tool_mod, "execute_call_tool", fake_execute_call_tool)
        monkeypatch.setattr(executor_mod, "_apply_prompt_pipeline", fake_pipeline)

        step = {
            "kind": "tool",
            "tool_id": "test:i2i",
            "task_type": "image-to-image",
            "settings": {"prompt": "make it moody"},
            "promptOptions": {"autoImprove": {"enabled": True, "instructions": ""}},
        }
        media_id = await executor_mod._run_tool_step(
            SimpleNamespace(async_session_maker=generation_db_session),
            step,
            input_media_id=1,
            project_id=None,
            all_steps=[step],
            profile_id="default",
        )
        assert media_id == 4242
        assert seen["parameters"]["prompt"] == "make it moody [ENHANCED]"
        assert seen["prompt_options"] == step["promptOptions"]
        assert seen["profile_id"] == "default"
        # promptOptions must never leak into the STP parameters.
        assert "promptOptions" not in seen["parameters"]

    async def test_pipeline_runs_even_without_prompt_options(self, generation_app, generation_db_session, monkeypatch):
        # Final processing (wildcards/comments/verbatim) applies to EVERY
        # chain-step prompt, exactly like an interactive submit.
        import agent.v2.tools.call_tool as call_tool_mod
        import postprocessing.executor as executor_mod

        seen = {}

        async def fake_execute_call_tool(**kwargs):
            seen["parameters"] = kwargs["parameters"]
            return {"media_id": 4243}

        monkeypatch.setattr(call_tool_mod, "execute_call_tool", fake_execute_call_tool)

        step = {
            "kind": "tool",
            "tool_id": "test:i2i",
            "task_type": "image-to-image",
            "settings": {"prompt": "# note to self\na [red] {dog|dog}"},
        }
        media_id = await executor_mod._run_tool_step(
            SimpleNamespace(async_session_maker=generation_db_session),
            step,
            input_media_id=1,
            project_id=None,
            all_steps=[step],
            profile_id="default",
        )
        assert media_id == 4243
        assert seen["parameters"]["prompt"] == "a red dog"

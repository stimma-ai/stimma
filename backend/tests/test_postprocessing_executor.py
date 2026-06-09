"""Post-processing chain executor: filter-step execution, lineage recording,
media-type validation, pause-on-failure, and Retry."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select

from database import GenerationJob, MediaItem, MediaLineage, PostProcessingChainRun
from postprocessing.executor import start_chain_for_job, CHAIN_INSTANCE_ID
from tests.helpers.media import create_media_item, generate_test_image


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


class TestChainExecutorFilters:
    async def test_filter_chain_runs_to_completion(self, generation_app, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_base.png")

        steps = [
            {"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 48}},
            {"kind": "filter", "filter_id": "color-filter", "settings": {"filter": "mono"}},
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

        async with generation_db_session() as session:
            result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
            refreshed = result.scalar_one()
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

    async def test_failure_pauses_and_keeps_last_good(self, generation_app, generation_db_session, mock_ws, tmp_path):
        base = await _make_base_media(generation_db_session, tmp_path, "chain_fail.png")

        steps = [
            {"kind": "filter", "filter_id": "resize", "settings": {"long_edge": 40}},
            {"kind": "filter", "filter_id": "color-filter", "settings": {"filter": "not-a-filter"}},
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

        steps = [{"kind": "filter", "filter_id": "color-filter", "settings": {"filter": "not-a-filter"}}]
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

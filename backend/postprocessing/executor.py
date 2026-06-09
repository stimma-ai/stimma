"""Post-processing chain executor.

Runs the linear step chain attached to a generation job after the base
generation completes: base image → step 1 → step 2 → … → final. Each step is
either an STP tool invocation (via execute_call_tool — the same path the
agent uses) or a built-in filter applied server-side.

Failure model (MVP): the chain pauses on a failed step, keeps the last good
media, and can be retried from the failed step. There is no Stop.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from core.logging import get_logger
from core.profile_context import set_current_profile
from database import MediaItem, PostProcessingChainRun
from database_registry import get_database_registry

log = get_logger(__name__)

# Generator instance id used for chain-step jobs. The generation-complete
# trigger seam skips jobs with this id, so a chain never re-triggers itself.
CHAIN_INSTANCE_ID = "postproc"

_VIDEO_FORMATS = {"mp4", "webm", "mov", "avi", "mkv", "gif"}

# Task types whose input is a video; everything else consumes an image.
_VIDEO_INPUT_TASKS = {"upscale-video"}
# Task types whose output is a video.
_VIDEO_OUTPUT_TASKS = {"image-to-video", "upscale-video"}

# Track in-flight chain tasks so they aren't garbage collected.
_running_tasks: set[asyncio.Task] = set()


def _step_input_type(step: Dict[str, Any]) -> str:
    if step.get("kind") == "filter":
        return "image"
    return "video" if step.get("task_type") in _VIDEO_INPUT_TASKS else "image"


def _step_output_type(step: Dict[str, Any]) -> str:
    if step.get("kind") == "filter":
        return "image"
    return "video" if step.get("task_type") in _VIDEO_OUTPUT_TASKS else "image"


def _step_label(step: Dict[str, Any]) -> str:
    if step.get("kind") == "filter":
        return step.get("filter_id") or "filter"
    return step.get("tool_name") or step.get("tool_id") or "tool"


async def start_chain_for_job(
    job,
    base_media_id: int,
    chain_steps: List[Dict[str, Any]],
    profile_id: str,
    websocket_manager,
) -> Optional[int]:
    """Create a chain run for a completed base generation and start executing
    it in the background. Returns the chain_run_id (None if nothing to run)."""
    steps = [s for s in (chain_steps or []) if isinstance(s, dict)]
    if not steps:
        return None

    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        run = PostProcessingChainRun(
            job_id=job.id,
            base_media_id=base_media_id,
            project_id=job.project_id,
            chain=json.dumps(steps),
            step_index=0,
            step_count=len(steps),
            step_results=json.dumps([{"status": "queued"} for _ in steps]),
            status="running",
            last_good_media_id=base_media_id,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    log.info(f"[postproc] Job {job.id}: starting chain run {run_id} with {len(steps)} step(s)")
    _spawn(run_id, profile_id, job.generator_instance_id, websocket_manager)
    return run_id


async def retry_chain_run(chain_run_id: int, profile_id: str, websocket_manager) -> bool:
    """Resume a paused chain run from its failed step, using the last good
    media as input. Returns False if the run isn't retryable."""
    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        result = await session.execute(
            select(PostProcessingChainRun).where(
                PostProcessingChainRun.id == chain_run_id,
                PostProcessingChainRun.deleted_at.is_(None),
            )
        )
        run = result.scalar_one_or_none()
        if not run or run.status not in ("paused", "failed"):
            return False
        # Reset the failed step back to queued and resume.
        step_results = json.loads(run.step_results or "[]")
        if run.step_index < len(step_results):
            step_results[run.step_index] = {"status": "queued"}
        await session.execute(
            update(PostProcessingChainRun)
            .where(PostProcessingChainRun.id == chain_run_id)
            .values(status="running", error=None, step_results=json.dumps(step_results))
        )
        await session.commit()
        job_instance_id = await _base_job_instance_id(session, run.job_id)

    log.info(f"[postproc] Retrying chain run {chain_run_id} from step {run.step_index}")
    _spawn(chain_run_id, profile_id, job_instance_id, websocket_manager)
    return True


async def reconcile_interrupted_runs(profile_id: str) -> int:
    """Mark chain runs left 'running' by a previous process as 'paused'.

    A chain run is an in-memory asyncio task; if the backend restarts mid-step
    the task dies but the row stays 'running' forever — a stuck progress bar
    with nothing driving it. Run at startup (like cleanup_stale_jobs for jobs)
    so orphans become paused: they stop reading as in-flight and gain the
    Retry/Dismiss controls. We deliberately do NOT auto-resume — a step costs
    compute, so resumption stays an explicit user action."""
    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        result = await session.execute(
            update(PostProcessingChainRun)
            .where(
                PostProcessingChainRun.status == "running",
                PostProcessingChainRun.deleted_at.is_(None),
            )
            .values(
                status="paused",
                error="Interrupted by server restart",
                updated_at=datetime.utcnow(),
            )
        )
        await session.commit()
        return result.rowcount or 0


async def _base_job_instance_id(session, job_id: int) -> Optional[str]:
    from database import GenerationJob
    result = await session.execute(
        select(GenerationJob.generator_instance_id).where(GenerationJob.id == job_id)
    )
    row = result.first()
    return row[0] if row else None


def _spawn(run_id: int, profile_id: str, job_instance_id: Optional[str], websocket_manager) -> None:
    task = asyncio.create_task(_run_chain(run_id, profile_id, job_instance_id, websocket_manager))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def _run_chain(run_id: int, profile_id: str, job_instance_id: Optional[str], websocket_manager) -> None:
    set_current_profile(profile_id)
    db = get_database_registry().get_database(profile_id)

    try:
        async with db.async_session_maker() as session:
            result = await session.execute(
                select(PostProcessingChainRun).where(PostProcessingChainRun.id == run_id)
            )
            run = result.scalar_one_or_none()
            if not run:
                log.error(f"[postproc] Chain run {run_id} not found")
                return
            steps: List[Dict[str, Any]] = json.loads(run.chain)
            step_results: List[Dict[str, Any]] = json.loads(run.step_results or "[]")
            while len(step_results) < len(steps):
                step_results.append({"status": "queued"})
            start_index = run.step_index
            current_media_id = run.last_good_media_id or run.base_media_id
            project_id = run.project_id
            job_id = run.job_id
            base_media_id = run.base_media_id

        current_type = await _media_type(db, current_media_id)

        for idx in range(start_index, len(steps)):
            step = steps[idx]

            # Media-type transition validation: an incompatible step is
            # skipped and flagged, not a hard failure (§3.4).
            if _step_input_type(step) != current_type:
                log.warning(
                    f"[postproc] Run {run_id} step {idx} ({_step_label(step)}) needs "
                    f"{_step_input_type(step)} input but chain output is {current_type}; skipping"
                )
                step_results[idx] = {"status": "skipped_incompatible"}
                await _save_progress(db, run_id, idx, step_results, "running", current_media_id)
                await _broadcast(websocket_manager, db, run_id, profile_id, job_instance_id)
                continue

            step_results[idx] = {"status": "running"}
            await _save_progress(db, run_id, idx, step_results, "running", current_media_id)
            await _broadcast(websocket_manager, db, run_id, profile_id, job_instance_id)

            started = time.perf_counter()
            try:
                # Built-in filters are catalog tools on the lightweight
                # provider — a filter step is just a tool step spelled
                # compactly (filter_id ↔ builtin:<filter_id>).
                if step.get("kind") == "filter":
                    tool_step = {
                        "tool_id": f"builtin:{step.get('filter_id')}",
                        "task_type": "filter",
                        "settings": step.get("settings"),
                    }
                    out_media_id = await _run_tool_step(
                        db, tool_step, current_media_id, project_id, steps
                    )
                else:
                    out_media_id = await _run_tool_step(
                        db, step, current_media_id, project_id, steps
                    )
            except Exception as e:
                log.error(f"[postproc] Run {run_id} step {idx} ({_step_label(step)}) failed: {e}")
                step_results[idx] = {
                    "status": "failed",
                    "error": str(e),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
                await _save_progress(
                    db, run_id, idx, step_results, "paused", current_media_id, error=str(e)
                )
                await _broadcast(websocket_manager, db, run_id, profile_id, job_instance_id)
                return

            duration_ms = int((time.perf_counter() - started) * 1000)
            step_results[idx] = {
                "status": "done",
                "media_id": out_media_id,
                "duration_ms": duration_ms,
            }
            current_media_id = out_media_id
            current_type = _step_output_type(step)
            await _save_progress(db, run_id, idx, step_results, "running", current_media_id)
            await _broadcast(websocket_manager, db, run_id, profile_id, job_instance_id)
            log.info(
                f"[postproc] Run {run_id} step {idx} ({_step_label(step)}) -> media {out_media_id} "
                f"in {duration_ms}ms"
            )

        # Finalize
        async with db.async_session_maker() as session:
            await session.execute(
                update(PostProcessingChainRun)
                .where(PostProcessingChainRun.id == run_id)
                .values(
                    status="completed",
                    final_media_id=current_media_id,
                    last_good_media_id=current_media_id,
                    step_index=len(steps),
                    step_results=json.dumps(step_results),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()

        # The base job IS the result-strip item: point it at the chain's final
        # output and re-broadcast it, so its tile becomes the final image (the
        # base and intermediates stay reachable via lineage). Do this before
        # the chain-completed broadcast so the tile never flashes the base.
        await _finalize_base_job(db, profile_id, job_id, current_media_id, websocket_manager)

        await _broadcast(websocket_manager, db, run_id, profile_id, job_instance_id)
        log.info(f"[postproc] Run {run_id} completed; final media {current_media_id} (base {base_media_id}, job {job_id})")

    except Exception as e:
        log.error(f"[postproc] Chain run {run_id} crashed: {e}", exc_info=True)
        try:
            async with db.async_session_maker() as session:
                await session.execute(
                    update(PostProcessingChainRun)
                    .where(PostProcessingChainRun.id == run_id)
                    .values(status="paused", error=str(e), updated_at=datetime.utcnow())
                )
                await session.commit()
            await _broadcast(websocket_manager, db, run_id, profile_id, job_instance_id)
        except Exception:
            pass


async def _finalize_base_job(db, profile_id: str, job_id: int, final_media_id: int, websocket_manager) -> None:
    from database import GenerationJob

    try:
        async with db.async_session_maker() as session:
            await session.execute(
                update(GenerationJob)
                .where(GenerationJob.id == job_id)
                .values(result_media_id=final_media_id)
            )
            await session.commit()
        if websocket_manager:
            from generation_queue import get_generation_queue
            job_dict = await get_generation_queue().get_job(job_id, profile_id=profile_id)
            if job_dict:
                await websocket_manager.broadcast("generation_job_completed", {
                    "job": job_dict,
                    "generator_instance_id": job_dict.get("generator_instance_id"),
                })
    except Exception as e:
        log.warning(f"[postproc] Failed to point job {job_id} at final media {final_media_id}: {e}")


async def _save_progress(
    db,
    run_id: int,
    step_index: int,
    step_results: List[Dict[str, Any]],
    status: str,
    last_good_media_id: int,
    error: Optional[str] = None,
) -> None:
    async with db.async_session_maker() as session:
        await session.execute(
            update(PostProcessingChainRun)
            .where(PostProcessingChainRun.id == run_id)
            .values(
                step_index=step_index,
                step_results=json.dumps(step_results),
                status=status,
                last_good_media_id=last_good_media_id,
                error=error,
                updated_at=datetime.utcnow(),
            )
        )
        await session.commit()


async def _broadcast(websocket_manager, db, run_id: int, profile_id: str, job_instance_id: Optional[str]) -> None:
    if not websocket_manager:
        return
    try:
        async with db.async_session_maker() as session:
            result = await session.execute(
                select(PostProcessingChainRun).where(PostProcessingChainRun.id == run_id)
            )
            run = result.scalar_one_or_none()
        if not run:
            return
        await websocket_manager.broadcast(
            "postprocessing_chain_progress",
            {
                "chain_run": run.to_dict(),
                "profile_id": profile_id,
                "generator_instance_id": job_instance_id,
            },
        )
    except Exception as e:
        log.warning(f"[postproc] Failed to broadcast chain progress: {e}")


async def _media_type(db, media_id: int) -> str:
    async with db.async_session_maker() as session:
        result = await session.execute(
            select(MediaItem.file_format).where(MediaItem.id == media_id)
        )
        row = result.first()
    fmt = (row[0] or "").lower() if row else ""
    return "video" if fmt in _VIDEO_FORMATS else "image"


async def _run_tool_step(
    db,
    step: Dict[str, Any],
    input_media_id: int,
    project_id: Optional[int],
    all_steps: List[Dict[str, Any]],
) -> int:
    """Execute one STP tool step via execute_call_tool (media_id → media_id)."""
    from agent.v2.tools.call_tool import execute_call_tool

    tool_id = step.get("tool_id")
    if not tool_id:
        raise ValueError("Tool step has no tool_id")

    parameters: Dict[str, Any] = dict(step.get("settings") or {})
    parameters["input_images"] = [input_media_id]
    # Record the chain on the step output so remixing any chained image
    # restores the chain (lands in generation_metadata.parameters).
    parameters["post_processing_chain"] = all_steps

    # Relative upscale: the step stores scale_factor because the input isn't
    # known at config time. Resolve it against the actual input here — same
    # math as ToolView's picker (short edge × factor → the resolution param).
    if "scale_factor" in parameters and "resolution" not in parameters:
        scale = parameters.pop("scale_factor")
        try:
            from providers.registry import ProviderRegistry
            provider_tool = ProviderRegistry.get_instance().get_tool(tool_id)
            schema_props = (provider_tool[1].parameter_schema or {}).get("properties", {}) if provider_tool else {}
            if "resolution" in schema_props:
                async with db.async_session_maker() as session:
                    result = await session.execute(
                        select(MediaItem.width, MediaItem.height).where(MediaItem.id == input_media_id)
                    )
                    row = result.first()
                if row and row[0] and row[1]:
                    parameters["resolution"] = int(round(min(row[0], row[1]) * float(scale)))
        except Exception as e:
            log.warning(f"[postproc] Could not resolve scale_factor for {tool_id}: {e}")

    async with db.async_session_maker() as session:
        result = await execute_call_tool(
            tool_id=tool_id,
            parameters=parameters,
            task_type_override=step.get("task_type"),
            session=session,
            project_id=project_id,
            generator_instance_id=CHAIN_INSTANCE_ID,
        )
    media_id = result.get("media_id")
    if not media_id:
        raise RuntimeError(f"Tool step {tool_id} produced no media")
    return media_id

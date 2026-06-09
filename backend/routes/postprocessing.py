"""Post-processing chain run endpoints: progress listing + retry."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import get_db_session
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import PostProcessingChainRun
from generation_queue import get_generation_queue

log = get_logger(__name__)

router = APIRouter(prefix="/api/postprocessing", tags=["postprocessing"])


@router.get("/runs")
async def list_chain_runs(
    status: str = Query(None, description="Filter by status (e.g. 'running', 'paused')"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
):
    """List recent chain runs, newest first. The frontend uses this to restore
    in-flight/paused chain bars after a reload."""
    query = (
        select(PostProcessingChainRun)
        .where(PostProcessingChainRun.deleted_at.is_(None))
        .order_by(PostProcessingChainRun.created_at.desc())
        .limit(limit)
    )
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        query = query.where(PostProcessingChainRun.status.in_(statuses))
    result = await session.execute(query)
    runs = result.scalars().all()
    return {"runs": [r.to_dict() for r in runs]}


@router.get("/runs/{chain_run_id}")
async def get_chain_run(
    chain_run_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(PostProcessingChainRun).where(
            PostProcessingChainRun.id == chain_run_id,
            PostProcessingChainRun.deleted_at.is_(None),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Chain run not found")
    return run.to_dict()


@router.delete("/runs/{chain_run_id}")
async def dismiss_chain_run_endpoint(
    chain_run_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Soft-delete a chain run so it stops appearing as an in-flight/paused bar.
    If a step is still running, interrupt it first (fire-and-forget for
    providers that don't support it). Used to clear failed, restart-interrupted,
    or genuinely in-flight runs the user wants gone."""
    from postprocessing.executor import cancel_chain_run

    result = await session.execute(
        select(PostProcessingChainRun).where(
            PostProcessingChainRun.id == chain_run_id,
            PostProcessingChainRun.deleted_at.is_(None),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Chain run not found")

    # Send the interrupt to the in-flight step (if any) before removing the row.
    cancel_chain_run(chain_run_id)
    run.deleted_at = datetime.utcnow()
    await session.commit()
    return {"status": "dismissed", "chain_run_id": chain_run_id}


@router.post("/runs/{chain_run_id}/retry")
async def retry_chain_run_endpoint(chain_run_id: int):
    """Re-run a paused chain from its failed step, using the last good media
    as input. (Skip-step is a designed-for follow-on: same endpoint family.)"""
    from postprocessing.executor import retry_chain_run

    profile_id = get_current_profile()
    ws_manager = get_generation_queue().get_websocket_manager()
    ok = await retry_chain_run(chain_run_id, profile_id, ws_manager)
    if not ok:
        raise HTTPException(status_code=409, detail="Chain run is not retryable")
    return {"status": "running", "chain_run_id": chain_run_id}

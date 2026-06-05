"""Admin routes for system management."""
from core.logging import get_logger
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from database import MediaItem
from config import reload_settings
from core.dependencies import get_db_session
from core.request_metrics import get_request_metrics_collector

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = get_logger(__name__)


class RequestMetricRow(BaseModel):
    method: str
    path: str
    count: int
    avg_ms: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    status_2xx: int
    status_3xx: int
    status_4xx: int
    status_5xx: int


class RequestMetricsResponse(BaseModel):
    generated_at: str
    window_size: int
    total_requests_in_window: int
    endpoint_count: int
    endpoints: list[RequestMetricRow]


@router.post("/reload-config")
async def reload_config():
    """Reload config.yaml without restarting the server."""
    try:
        reload_settings()
        log.info("ADMIN: Config reloaded")
        return {"status": "success"}
    except Exception as e:
        log.error(f"ADMIN: Failed to reload config: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/reset-keywords")
async def reset_keywords(session: AsyncSession = Depends(get_db_session)):
    """
    Reset all keywords to trigger regeneration.
    Useful when switching from NLP to LLM-based keyword extraction.
    """
    result = await session.execute(select(MediaItem))
    items = result.scalars().all()

    count = 0
    for item in items:
        if item.keywords:
            item.keywords = None
            count += 1

    await session.commit()
    log.info(f"ADMIN: Reset keywords for {count} items - they will be regenerated on next ingestion cycle")

    return {
        "status": "success",
        "message": f"Reset keywords for {count} items",
        "items_reset": count
    }


@router.get("/request-metrics", response_model=RequestMetricsResponse)
async def get_request_metrics(
    sort_by: Literal["p95_ms", "p99_ms", "p90_ms", "p50_ms", "avg_ms", "count", "max_ms"] = Query(default="p95_ms"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Get in-memory endpoint latency percentiles and status distribution."""
    collector = get_request_metrics_collector()
    snapshot = collector.snapshot(sort_by=sort_by, limit=limit)
    return RequestMetricsResponse(**snapshot)


@router.post("/request-metrics/reset")
async def reset_request_metrics():
    """Reset in-memory request metrics windows."""
    collector = get_request_metrics_collector()
    collector.reset()
    return {"status": "success"}

"""API route for frontend telemetry events.

Frontend events flow through the sidecar so the backend's single telemetry
client owns consent gating, buffering, and batching.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, Optional

from telemetry import get_telemetry_client

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class TrackEventRequest(BaseModel):
    event: str
    properties: Optional[Dict[str, Any]] = None
    category: Optional[str] = None


@router.post("/track")
async def track_event(req: TrackEventRequest):
    get_telemetry_client().track(
        req.event, req.properties, category=req.category or "app"
    )
    return {"ok": True}

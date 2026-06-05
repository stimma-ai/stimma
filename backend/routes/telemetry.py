"""API route for frontend telemetry events."""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Optional, Union

from telemetry import get_telemetry_client

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class TrackEventRequest(BaseModel):
    event: str
    properties: Optional[Dict[str, Union[str, int, bool]]] = None


@router.post("/track")
async def track_event(req: TrackEventRequest):
    get_telemetry_client().track(req.event, req.properties)
    return {"ok": True}

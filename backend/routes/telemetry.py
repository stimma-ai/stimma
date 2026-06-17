"""API route for frontend telemetry events.

Frontend events flow through the sidecar so the backend's single telemetry
client owns consent gating, buffering, and batching.

Raw-reference resolution: the frontend cannot compute salted hashes or
toolRefs (the salt and the classification helpers live in the backend), so
it sends raw identifiers under reserved ``_``-prefixed keys and this route
replaces them with the telemetry-safe fields before tracking:

    _toolId      -> toolRef (+ toolSource)
    _fromToolId  -> fromToolRef
    _toToolId    -> toToolRef
    _presetId    -> presetHash
    _chatId      -> chatHash
    _boardId     -> boardHash
    _projectId   -> projectHash
    _flowId    -> flowHash

Any other ``_``-prefixed key is dropped, so raw values can never egress
through this funnel.
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


_HASH_KEYS = {
    "_presetId": ("presetHash", "preset"),
    "_chatId": ("chatHash", "chat"),
    "_boardId": ("boardHash", "board"),
    "_projectId": ("projectHash", "project"),
    "_flowId": ("flowHash", "flow"),
}


def _resolve_raw_refs(properties: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not properties:
        return {}
    from object_hash import salted_hash
    from pipeline_telemetry import tool_identity_props

    resolved: Dict[str, Any] = {}
    for key, value in properties.items():
        if not key.startswith("_"):
            resolved[key] = value
            continue
        if value is None:
            continue
        if key == "_toolId":
            identity = tool_identity_props(str(value))
            resolved["toolRef"] = identity.get("toolRef")
            resolved["toolSource"] = identity.get("toolSource")
        elif key == "_fromToolId":
            resolved["fromToolRef"] = tool_identity_props(str(value)).get("toolRef")
        elif key == "_toToolId":
            resolved["toToolRef"] = tool_identity_props(str(value)).get("toolRef")
        elif key in _HASH_KEYS:
            prop_name, prefix = _HASH_KEYS[key]
            resolved[prop_name] = salted_hash(f"{prefix}:{value}")
        # Unknown _-prefixed keys are dropped.
    return resolved


@router.post("/track")
async def track_event(req: TrackEventRequest):
    get_telemetry_client().track(
        req.event, _resolve_raw_refs(req.properties), category=req.category or "app"
    )
    return {"ok": True}

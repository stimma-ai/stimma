"""The single serializer from working state to canonical .stimmatimeline.json.

There is exactly one code path that produces snapshot JSON — this one. The
output is deterministic for a given (state, media_paths): explicit key order,
no timestamps, stable float formatting via json defaults.
"""

from typing import Any

from .ops import TRACK_KINDS, TimelineOpError, track_duration

SNAPSHOT_FORMAT = "stimmatimeline"
SNAPSHOT_VERSION = 1


def _clip_json(entry: dict, media_paths: dict[int, str]) -> dict[str, Any]:
    media_id = entry["media"]["media_id"]
    path = media_paths.get(media_id)
    if path is None:
        raise TimelineOpError(f"No library path for media {media_id}")
    out: dict[str, Any] = {
        "kind": "clip",
        "id": entry["id"],
        "media": {"path": path},
        "in": entry.get("in", 0.0),
    }
    for key in ("out", "duration", "label"):
        if entry.get(key) is not None:
            out[key] = entry[key]
    return out


def _slot_json(entry: dict) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": "slot",
        "id": entry["id"],
        "duration": entry["duration"],
        "brief": entry.get("brief", ""),
    }
    if entry.get("notes"):
        out["notes"] = entry["notes"]
    if entry.get("silence"):
        out["silence"] = True
    return out


def serialize_snapshot(state: dict, media_paths: dict[int, str]) -> dict[str, Any]:
    """Materialize working state into the canonical snapshot dict.

    media_paths maps media_id -> path string to embed (caller computes paths
    relative to where the snapshot file will live, matching sets/grids).
    """
    snapshot: dict[str, Any] = {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "title": state.get("title", ""),
        "fps": state["fps"],
        "width": state["width"],
        "height": state["height"],
        "tracks": [],
    }
    for kind in TRACK_KINDS:
        track = next(t for t in state["tracks"] if t["kind"] == kind)
        entries = [
            _clip_json(e, media_paths) if e["kind"] == "clip" else _slot_json(e)
            for e in track["entries"]
        ]
        snapshot["tracks"].append({"kind": kind, "entries": entries})
    return snapshot


def snapshot_duration(state: dict) -> float:
    """Total timeline length: the longer of the two tracks."""
    return max(track_duration(t) for t in state["tracks"])

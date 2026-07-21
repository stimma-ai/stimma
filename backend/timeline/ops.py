"""Pure timeline op core: apply ops to a document state, compute inverses.

No I/O here. State is a plain dict shaped like the .stimmatimeline.json
snapshot, except clip media is referenced as {"media_id": int} — the
serializer converts ids to library-relative paths at save-point time.

Ops are the unit of editing everywhere: agent tools, sequencer gestures, and
undo all speak this vocabulary. Inverses are computed against the state
*before* the op applies; undo executes inverses transiently (they are never
appended to the log). `_insert_entry` / `_replace_entry` exist only as
inverse targets and must not be issued by callers.

Times are seconds. Entries are strictly sequential per track: no gaps, no
overlaps, no start times — an entry's start is the sum of prior durations.
"""

import copy
import os
import time
from typing import Any, Optional

TRACK_KINDS = ("video", "audio")

# Crockford base32, per ULID spec
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class TimelineOpError(ValueError):
    """An op could not be validated or applied."""


def new_entry_id() -> str:
    """26-char ULID (time-ordered, unique) for entry identity."""
    ts = int(time.time() * 1000)
    chars = []
    for _ in range(10):
        chars.append(_ULID_ALPHABET[ts & 0x1F])
        ts >>= 5
    rand = int.from_bytes(os.urandom(10), "big")
    for _ in range(16):
        chars.append(_ULID_ALPHABET[rand & 0x1F])
        rand >>= 5
    return "".join(reversed(chars))


def empty_state() -> dict:
    return {
        "title": "",
        "fps": 30,
        "width": 1920,
        "height": 1080,
        "tracks": [
            {"kind": "video", "entries": []},
            {"kind": "audio", "entries": []},
        ],
    }


def entry_duration(entry: dict) -> float:
    """Timeline-time length of an entry (the evaluation function's clock)."""
    if entry["kind"] == "slot":
        return float(entry["duration"])
    out = entry.get("out")
    if out is not None:
        return float(out) - float(entry.get("in") or 0.0)
    return float(entry["duration"])


def track_duration(track: dict) -> float:
    return sum(entry_duration(e) for e in track["entries"])


def _track(state: dict, kind: str) -> dict:
    for track in state["tracks"]:
        if track["kind"] == kind:
            return track
    raise TimelineOpError(f"No such track: {kind!r}")


def _find_entry(state: dict, entry_id: str) -> tuple[dict, int]:
    for track in state["tracks"]:
        for index, entry in enumerate(track["entries"]):
            if entry["id"] == entry_id:
                return track, index
    raise TimelineOpError(f"No entry with id {entry_id!r}")


def _clamp_position(track: dict, position: Optional[int]) -> int:
    count = len(track["entries"])
    if position is None:
        return count
    return max(0, min(int(position), count))


def _require_timing(args: dict, context: str) -> None:
    has_out = args.get("out") is not None
    has_duration = args.get("duration") is not None
    if not has_out and not has_duration:
        raise TimelineOpError(
            f"{context} needs either out (timed media, with optional in) or duration (stills)"
        )
    if has_out and float(args["out"]) <= float(args.get("in") or 0.0):
        raise TimelineOpError(f"{context}: out must be greater than in")
    if has_duration and float(args["duration"]) <= 0:
        raise TimelineOpError(f"{context}: duration must be positive")


def _build_clip(args: dict) -> dict:
    entry: dict[str, Any] = {
        "kind": "clip",
        "id": args["id"],
        "media": {"media_id": int(args["media_id"])},
        "in": float(args.get("in") or 0.0),
    }
    if args.get("out") is not None:
        entry["out"] = float(args["out"])
    if args.get("duration") is not None:
        entry["duration"] = float(args["duration"])
    if args.get("label"):
        entry["label"] = str(args["label"])
    return entry


def _build_slot(args: dict) -> dict:
    duration = float(args["duration"])
    if duration <= 0:
        raise TimelineOpError("Slot duration must be positive")
    entry: dict[str, Any] = {
        "kind": "slot",
        "id": args["id"],
        "duration": duration,
        "brief": str(args.get("brief") or ""),
    }
    if args.get("notes"):
        entry["notes"] = str(args["notes"])
    if args.get("silence"):
        entry["silence"] = True
    return entry


# --- apply -------------------------------------------------------------

def apply_op(state: Optional[dict], op: str, args: dict) -> dict:
    """Apply one op, mutating and returning state. Raises TimelineOpError."""
    if op == "create_timeline":
        if state is not None:
            raise TimelineOpError("create_timeline must be the first op")
        state = empty_state()
        for key in ("title", "fps", "width", "height"):
            if args.get(key) is not None:
                state[key] = args[key]
        return state

    if state is None:
        raise TimelineOpError("Timeline has not been created yet")

    if op == "add_clip":
        track = _track(state, args.get("track") or "video")
        _require_timing(args, "add_clip")
        track["entries"].insert(_clamp_position(track, args.get("position")), _build_clip(args))
    elif op == "add_slot":
        track = _track(state, args.get("track") or "video")
        track["entries"].insert(_clamp_position(track, args.get("position")), _build_slot(args))
    elif op == "fill_slot":
        track, index = _find_entry(state, args["slot_id"])
        old = track["entries"][index]
        if old["kind"] != "slot":
            raise TimelineOpError(f"Entry {args['slot_id']!r} is not a slot")
        clip_args = dict(args)
        clip_args["id"] = old["id"]
        if clip_args.get("out") is None and clip_args.get("duration") is None:
            clip_args["duration"] = old["duration"]
        _require_timing(clip_args, "fill_slot")
        clip = _build_clip(clip_args)
        if old.get("brief"):
            clip.setdefault("label", old["brief"])
        track["entries"][index] = clip
    elif op == "move_entry":
        track, index = _find_entry(state, args["entry_id"])
        entry = track["entries"].pop(index)
        track["entries"].insert(_clamp_position(track, args["position"]), entry)
    elif op == "trim_clip":
        track, index = _find_entry(state, args["entry_id"])
        entry = track["entries"][index]
        if entry["kind"] == "slot":
            if args.get("in") is not None or args.get("out") is not None:
                raise TimelineOpError("Slots have no source trim; only duration applies")
            duration = float(args.get("duration") or 0)
            if duration <= 0:
                raise TimelineOpError("Slot duration must be positive")
            entry["duration"] = duration
            return state
        merged = dict(entry)
        for key in ("in", "out", "duration"):
            if key in args:
                if args[key] is None:
                    merged.pop(key, None)
                else:
                    merged[key] = float(args[key])
        _require_timing(merged, "trim_clip")
        track["entries"][index] = merged
    elif op == "remove_entry":
        track, index = _find_entry(state, args["entry_id"])
        track["entries"].pop(index)
    elif op == "set_entry_meta":
        track, index = _find_entry(state, args["entry_id"])
        entry = track["entries"][index]
        slot_keys = ("brief", "notes", "silence") if entry["kind"] == "slot" else ()
        clip_keys = ("label",) if entry["kind"] == "clip" else ()
        for key in ("brief", "notes", "silence", "label"):
            if key not in args:
                continue
            if key not in slot_keys and key not in clip_keys:
                raise TimelineOpError(f"{key!r} does not apply to a {entry['kind']}")
            if args[key] in (None, "", False):
                entry.pop(key, None)
            else:
                entry[key] = args[key]
        if entry["kind"] == "slot" and "brief" not in entry:
            entry["brief"] = ""
    elif op == "set_timeline_meta":
        for key in ("title", "fps", "width", "height"):
            if key in args and args[key] is not None:
                state[key] = args[key]
    elif op == "_insert_entry":
        track = _track(state, args["track"])
        track["entries"].insert(_clamp_position(track, args["position"]), copy.deepcopy(args["entry"]))
    elif op == "_replace_entry":
        track, index = _find_entry(state, args["entry_id"])
        track["entries"][index] = copy.deepcopy(args["entry"])
    else:
        raise TimelineOpError(f"Unknown op: {op!r}")
    return state


# --- inverses ----------------------------------------------------------

def compute_inverse(state: Optional[dict], op: str, args: dict) -> Optional[tuple[str, dict]]:
    """Inverse of applying (op, args) to state. None = not undoable (create)."""
    if op == "create_timeline":
        return None
    if state is None:
        raise TimelineOpError("Timeline has not been created yet")

    if op in ("add_clip", "add_slot"):
        return ("remove_entry", {"entry_id": args["id"]})
    if op in ("fill_slot", "trim_clip", "set_entry_meta"):
        entry_id = args.get("slot_id") or args["entry_id"]
        track, index = _find_entry(state, entry_id)
        return ("_replace_entry", {"entry_id": entry_id, "entry": copy.deepcopy(track["entries"][index])})
    if op == "move_entry":
        track, index = _find_entry(state, args["entry_id"])
        return ("move_entry", {"entry_id": args["entry_id"], "position": index})
    if op == "remove_entry":
        track, index = _find_entry(state, args["entry_id"])
        return (
            "_insert_entry",
            {"track": track["kind"], "position": index, "entry": copy.deepcopy(track["entries"][index])},
        )
    if op == "set_timeline_meta":
        return ("set_timeline_meta", {k: state[k] for k in ("title", "fps", "width", "height") if k in args})
    raise TimelineOpError(f"Unknown op: {op!r}")

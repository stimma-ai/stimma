"""Timeline agent tools — exact parity with the sequencer's op vocabulary.

Each write tool appends one labeled op batch to the timeline's op log (the
user can undo it as a unit) and commits a revision, then returns a text
summary of the resulting timeline so the model tracks state without a
separate read. `timeline_id` is the Asset id returned by create_timeline.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter

from asset_service import AssetServiceError
from core.logging import get_logger
from database import MediaItem
from timeline import TimelineOpError, TimelineStoreError
from timeline import service as timeline_service
from timeline.ops import entry_duration, track_duration
from timeline.store import run_store
from utils.query_builder import AUDIO_FORMATS, IMAGE_FORMATS, VIDEO_FORMATS

log = get_logger(__name__)

_TIMELINE_ERRORS = (TimelineOpError, TimelineStoreError, AssetServiceError)


def _author(kwargs: dict) -> str:
    chat_id = kwargs.get("chat_id")
    return f"agent:chat:{chat_id}" if chat_id is not None else "agent"


def _summarize(state: dict) -> str:
    lines = []
    for track in state["tracks"]:
        total = track_duration(track)
        lines.append(f"{track['kind']} track ({total:g}s):")
        if not track["entries"]:
            lines.append("  (empty)")
        position = 0.0
        for index, entry in enumerate(track["entries"]):
            length = entry_duration(entry)
            if entry["kind"] == "clip":
                media_id = entry["media"]["media_id"]
                trim = (
                    f" trim {entry.get('in', 0):g}-{entry['out']:g}"
                    if entry.get("out") is not None
                    else ""
                )
                label = f" \"{entry['label']}\"" if entry.get("label") else ""
                lines.append(
                    f"  [{index}] clip {entry['id']} media={media_id} "
                    f"at {position:g}s len {length:g}s{trim}{label}"
                )
            else:
                flags = " silence" if entry.get("silence") else ""
                brief = f" \"{entry.get('brief', '')}\"" if entry.get("brief") else ""
                lines.append(
                    f"  [{index}] slot {entry['id']} at {position:g}s "
                    f"len {length:g}s{flags}{brief}"
                )
            position += length
    return "\n".join(lines)


async def _media_for_track(
    session: AsyncSession, media_id: int, track: str
) -> MediaItem:
    media = await session.get(MediaItem, int(media_id))
    if media is None or media.deleted_at is not None:
        raise AssetServiceError(f"No media with id {media_id}")
    fmt = (media.file_format or "").lower()
    if track == "video" and fmt not in VIDEO_FORMATS + IMAGE_FORMATS:
        raise AssetServiceError(
            f"Media {media_id} is {fmt}; the video track takes video or image media"
        )
    if track == "audio" and fmt not in AUDIO_FORMATS:
        raise AssetServiceError(
            f"Media {media_id} is {fmt}; the audio track takes audio media"
        )
    return media


def _default_timing(
    media: MediaItem, in_: Optional[float], out: Optional[float], duration: Optional[float]
) -> dict:
    """Fill clip timing from media metadata when the caller omits it."""
    args: dict = {}
    if in_ is not None:
        args["in"] = float(in_)
    if out is not None:
        args["out"] = float(out)
    if duration is not None:
        args["duration"] = float(duration)
    if out is None and duration is None and media.duration:
        args["out"] = float(media.duration)
    return args


async def _apply(session: AsyncSession, kwargs: dict, timeline_id, op: str, args: dict, label: str) -> str:
    result = await timeline_service.apply_ops(
        session,
        asset_id=int(timeline_id),
        ops=[(op, args)],
        author=_author(kwargs),
        label=label,
    )
    saved = await timeline_service.save_revision(
        session, asset_id=int(timeline_id), note=label
    )
    return (
        f"Done (revision {saved['revision_number']}).\n"
        + _summarize(result["state"])
    )


@tool(
    name="create_timeline",
    description=(
        "Create a new timeline document (one video + one audio track). Entries are "
        "strictly sequential; times are seconds. Returns the timeline id used by the "
        "other timeline tools. Add media with add_clip, or plan holes first with "
        "add_slot and fill them later with fill_slot."
    ),
    parameters=[
        ToolParameter(name="title", type="string", description="Timeline title", required=False),
        ToolParameter(name="fps", type="number", description="Frame rate (default 30)", required=False),
        ToolParameter(name="width", type="integer", description="Frame width (default 1920)", required=False),
        ToolParameter(name="height", type="integer", description="Frame height (default 1080)", required=False),
    ],
)
async def create_timeline(
    title: str = "",
    fps: float = 30,
    width: int = 1920,
    height: int = 1080,
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    chat_id = kwargs.get("chat_id")
    try:
        result = await timeline_service.create_timeline_asset(
            session,
            title=title,
            fps=fps,
            width=int(width),
            height=int(height),
            author=_author(kwargs),
            origin_type="chat" if chat_id is not None else None,
            origin_id=str(chat_id) if chat_id is not None else None,
        )
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"

    project_id = kwargs.get("project_id")
    if project_id is not None:
        from project_service import attach_media_to_project

        await attach_media_to_project(session, project_id, result["media_id"])
        await session.commit()

    from telemetry import get_telemetry_client

    get_telemetry_client().track("timeline_created", {"actor": "agent"}, category="library")
    return (
        f"<result media_id={result['media_id']} />"
        f"Timeline created. timeline_id={result['asset_id']} "
        f"({int(width)}x{int(height)} @ {fps:g}fps)."
    )


@tool(
    name="add_clip",
    description=(
        "Append or insert media as a clip on a timeline track. Timed media defaults "
        "to its full length; trim with in/out (source-time seconds). Still images "
        "need an explicit duration."
    ),
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="media_id", type="integer", description="Library media to place"),
        ToolParameter(name="track", type="string", description="video (default) or audio", required=False, enum=["video", "audio"]),
        ToolParameter(name="in", type="number", description="Source-time trim start, seconds", required=False),
        ToolParameter(name="out", type="number", description="Source-time trim end, seconds", required=False),
        ToolParameter(name="duration", type="number", description="Timeline seconds (stills only)", required=False),
        ToolParameter(name="position", type="integer", description="Insert index; default appends", required=False),
        ToolParameter(name="label", type="string", description="Short label for the clip", required=False),
    ],
)
async def add_clip(timeline_id, media_id, track: str = "video", position=None, label: str = "", **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    try:
        media = await _media_for_track(session, media_id, track)
        args = _default_timing(media, kwargs.get("in"), kwargs.get("out"), kwargs.get("duration"))
        args.update({"track": track, "media_id": int(media_id)})
        if position is not None:
            args["position"] = int(position)
        if label:
            args["label"] = label
        return await _apply(session, kwargs, timeline_id, "add_clip", args, "Add clip")
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="add_slot",
    description=(
        "Add a timed hole to a timeline: a slot with a brief describing what should "
        "fill it. Slots hold the cut's timing before media exists; fill them later "
        "with fill_slot. On the audio track, silence=true makes a silent spacer "
        "instead of a brief-card."
    ),
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="duration", type="number", description="Slot length in seconds"),
        ToolParameter(name="brief", type="string", description="What should fill this hole", required=False),
        ToolParameter(name="track", type="string", description="video (default) or audio", required=False, enum=["video", "audio"]),
        ToolParameter(name="notes", type="string", description="Production notes", required=False),
        ToolParameter(name="position", type="integer", description="Insert index; default appends", required=False),
        ToolParameter(name="silence", type="boolean", description="Audio track: render as silence", required=False),
    ],
)
async def add_slot(timeline_id, duration, brief: str = "", track: str = "video", notes: str = "", position=None, silence: bool = False, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    args = {"track": track, "duration": float(duration), "brief": brief}
    if notes:
        args["notes"] = notes
    if position is not None:
        args["position"] = int(position)
    if silence:
        args["silence"] = True
    try:
        return await _apply(session, kwargs, timeline_id, "add_slot", args, "Add slot")
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="fill_slot",
    description=(
        "Fill a timeline slot with media, converting it to a clip with the same id. "
        "Keeps the slot's duration unless in/out trims are given; the brief becomes "
        "the clip label."
    ),
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="slot_id", type="string", description="Slot entry id"),
        ToolParameter(name="media_id", type="integer", description="Library media to place"),
        ToolParameter(name="in", type="number", description="Source-time trim start, seconds", required=False),
        ToolParameter(name="out", type="number", description="Source-time trim end, seconds", required=False),
    ],
)
async def fill_slot(timeline_id, slot_id: str, media_id, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    try:
        _, project = await timeline_service.get_project_for_asset(session, int(timeline_id))
        state = await run_store(project.state)
        slot = next(
            (e for t in (state or {"tracks": []})["tracks"] for e in t["entries"] if e["id"] == slot_id),
            None,
        )
        track_kind = next(
            (t["kind"] for t in (state or {"tracks": []})["tracks"] for e in t["entries"] if e["id"] == slot_id),
            "video",
        )
        media = await _media_for_track(session, media_id, track_kind)
        args = {"slot_id": slot_id, "media_id": int(media_id)}
        in_, out = kwargs.get("in"), kwargs.get("out")
        if in_ is not None:
            args["in"] = float(in_)
        if out is not None:
            args["out"] = float(out)
        elif media.duration and slot is not None:
            args["out"] = float(min(media.duration, slot["duration"]))
        return await _apply(session, kwargs, timeline_id, "fill_slot", args, "Fill slot")
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="move_entry",
    description="Move a timeline entry to a new index within its track.",
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="entry_id", type="string", description="Entry id to move"),
        ToolParameter(name="position", type="integer", description="Target index in the track"),
    ],
)
async def move_entry(timeline_id, entry_id: str, position, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    try:
        return await _apply(
            session, kwargs, timeline_id, "move_entry",
            {"entry_id": entry_id, "position": int(position)}, "Move entry",
        )
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="trim_clip",
    description=(
        "Change a clip's timing: in/out in source-time seconds for timed media, "
        "duration for stills."
    ),
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="entry_id", type="string", description="Clip entry id"),
        ToolParameter(name="in", type="number", description="Source-time trim start, seconds", required=False),
        ToolParameter(name="out", type="number", description="Source-time trim end, seconds", required=False),
        ToolParameter(name="duration", type="number", description="Timeline seconds (stills only)", required=False),
    ],
)
async def trim_clip(timeline_id, entry_id: str, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    args = {"entry_id": entry_id}
    for key in ("in", "out", "duration"):
        if kwargs.get(key) is not None:
            args[key] = float(kwargs[key])
    if len(args) == 1:
        return "Error: trim_clip needs at least one of in, out, duration"
    try:
        return await _apply(session, kwargs, timeline_id, "trim_clip", args, "Trim clip")
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="remove_entry",
    description="Remove a clip or slot from a timeline.",
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="entry_id", type="string", description="Entry id to remove"),
    ],
)
async def remove_entry(timeline_id, entry_id: str, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    try:
        return await _apply(
            session, kwargs, timeline_id, "remove_entry", {"entry_id": entry_id}, "Remove entry"
        )
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="set_entry_meta",
    description=(
        "Update entry text: brief/notes on a slot, label on a clip. Also "
        "set_timeline_meta-style fields title/fps/width/height when entry_id is "
        "omitted."
    ),
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
        ToolParameter(name="entry_id", type="string", description="Entry id; omit to edit timeline metadata", required=False),
        ToolParameter(name="brief", type="string", description="Slot brief", required=False),
        ToolParameter(name="notes", type="string", description="Slot notes", required=False),
        ToolParameter(name="label", type="string", description="Clip label", required=False),
        ToolParameter(name="title", type="string", description="Timeline title", required=False),
        ToolParameter(name="fps", type="number", description="Timeline fps", required=False),
        ToolParameter(name="width", type="integer", description="Frame width", required=False),
        ToolParameter(name="height", type="integer", description="Frame height", required=False),
    ],
)
async def set_entry_meta(timeline_id, entry_id: str = "", **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    try:
        if entry_id:
            args = {"entry_id": entry_id}
            for key in ("brief", "notes", "label"):
                if key in kwargs and kwargs[key] is not None:
                    args[key] = kwargs[key]
            if len(args) == 1:
                return "Error: set_entry_meta needs at least one of brief, notes, label"
            return await _apply(session, kwargs, timeline_id, "set_entry_meta", args, "Edit entry")
        args = {}
        for key in ("title", "fps", "width", "height"):
            if kwargs.get(key) is not None:
                args[key] = kwargs[key]
        if not args:
            return "Error: set_entry_meta needs fields to change"
        return await _apply(session, kwargs, timeline_id, "set_timeline_meta", args, "Edit timeline settings")
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"


@tool(
    name="get_timeline",
    description="Read a timeline's current entries, ids, and timings.",
    parameters=[
        ToolParameter(name="timeline_id", type="integer", description="Timeline id"),
    ],
)
async def get_timeline(timeline_id, **kwargs) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"
    try:
        _, project = await timeline_service.get_project_for_asset(session, int(timeline_id))
        state = await run_store(project.state)
    except _TIMELINE_ERRORS as error:
        return f"Error: {error}"
    if state is None:
        return "Error: Timeline has no state"
    header = (
        f"\"{state.get('title') or 'Untitled'}\" "
        f"{state['width']}x{state['height']} @ {state['fps']:g}fps"
    )
    return header + "\n" + _summarize(state)

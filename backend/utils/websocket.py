"""WebSocket connection management for real-time updates."""
import asyncio
import functools
import json
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from core.logging import get_logger
from typing import Any, List, Dict, Optional, Callable, Awaitable
from fastapi import WebSocket, WebSocketDisconnect

from core.profile_context import get_current_profile

log = get_logger(__name__)


# A mutation can defer its own broadcasts until its database receipt commits.
# Child tasks use normal delivery instead of inheriting an abandoned buffer.
_broadcast_buffer = ContextVar('broadcast_buffer', default=None)


@asynccontextmanager
async def defer_broadcasts():
    events = []
    token = _broadcast_buffer.set((asyncio.current_task(), events))
    try:
        yield
    except BaseException:
        raise
    else:
        _broadcast_buffer.reset(token)
        token = None
        for manager, event, data, include_profile in events:
            await manager.broadcast(event, data, include_profile)
    finally:
        if token is not None:
            _broadcast_buffer.reset(token)


def _payload_log_metadata(data: dict) -> dict:
    """Return content-free metadata for a WebSocket payload.

    WebSocket events routinely carry chat messages, prompts, tool arguments,
    model output, and media metadata. Logging a serialized preview therefore
    leaks user content even when truncated. Keep only mechanical identifiers
    and the payload shape.
    """
    metadata = {"data_keys": sorted(str(key) for key in data)}
    for key in ("chat_id", "request_id", "profile_id", "flow_id", "project_id"):
        value = data.get(key)
        if isinstance(value, (int, float)) or (
            isinstance(value, str) and value.isascii() and value.replace("-", "").isalnum()
        ):
            metadata[key] = value
    return metadata


# Per-client delivery. Each connection gets its own outbound queue and sender
# task, so one slow or half-open client (typically a phone on a weak cellular
# link) can never delay delivery to the others or the broadcaster.
#
# Frames are either transient or durable:
# - Transient frames (live progress ticks and previews) may be replaced by a
#   newer frame for the same entity, and are shed once a client's backlog
#   passes the soft budget. A newer tick, or the durable terminal event that
#   follows, always carries the state forward.
# - Durable frames (every state change, including terminal and error
#   transitions) are never dropped while the client is connected. Their only
#   bound is a much larger hard cap: a client that far behind, or one whose
#   send misses the deadline, is stalled or dead and is disconnected through
#   the ordinary disconnect path, exactly as if its network had dropped.
CLIENT_SOFT_MAX_FRAMES = 512
CLIENT_SOFT_MAX_BYTES = 8 * 1024 * 1024
CLIENT_HARD_MAX_FRAMES = 50_000
CLIENT_HARD_MAX_BYTES = 128 * 1024 * 1024
# A single send that cannot complete in this window means the socket is
# stalled or half-open. websockets applies write backpressure, so a dead peer
# eventually blocks a send; the deadline turns that into a close instead of an
# ever-growing queue.
CLIENT_SEND_TIMEOUT_SECONDS = 20.0
CLIENT_CLOSE_TIMEOUT_SECONDS = 2.0
# "Try again later": the client should reconnect.
OVERFLOW_CLOSE_CODE = 1013

# Post-processing chain states that are still in motion. Any other status
# (completed, paused with an error, failed, cancelled) is a terminal or error
# transition and therefore durable.
_CHAIN_ACTIVE_STATUSES = frozenset({"running", "pending", "queued"})


@dataclass(frozen=True)
class _Delivery:
    """How a frame may be treated while it waits in a client's queue."""

    # Frames with the same key describe the same entity.
    key: Optional[tuple] = None
    # A newer frame with the same key may replace this one (latest wins).
    replaceable: bool = False
    # This frame may be dropped under pressure.
    sheddable: bool = False


_DURABLE = _Delivery()


def _delivery_policy(event: str, data: dict) -> _Delivery:
    """Classify an event. Anything not listed here is durable.

    Keys include the profile so a later per-client filter can never merge
    frames across profiles.
    """
    profile_id = data.get("profile_id")
    if event == "generation_job_progress":
        job_id = data.get("job_id")
        if job_id is None:
            return _DURABLE
        # Terminal job states are separate durable events. The UI keeps the
        # last preview frame when a tick carries none, so a numeric-only tick
        # must never replace a pending preview frame: they get distinct keys.
        key = (event, profile_id, job_id, bool(data.get("preview_b64")))
        return _Delivery(key, replaceable=True, sheddable=True)
    if event == "postprocessing_chain_progress":
        run = data.get("chain_run")
        run_id = run.get("id") if isinstance(run, dict) else None
        if run_id is None:
            return _DURABLE
        key = (event, profile_id, run_id)
        if run.get("status") in _CHAIN_ACTIVE_STATUSES:
            return _Delivery(key, replaceable=True, sheddable=True)
        # Terminal snapshot: it supersedes a pending running snapshot of the
        # same run, but is never itself replaced or shed.
        return _Delivery(key)
    if event == "delete_operation_progress":
        operation_id = data.get("id")
        if operation_id is None:
            return _DURABLE
        # Full snapshot of the operation: latest wins, but never shed.
        return _Delivery((event, profile_id, operation_id), replaceable=True)
    if event == "processing_stats":
        # Broadcast only on change, so the newest snapshot must arrive.
        return _Delivery((event, profile_id), replaceable=True)
    return _DURABLE


@dataclass(frozen=True, eq=False)
class OutboundFrame:
    """One serialized event, shared by every client it is delivered to."""

    event: str
    text: str
    delivery: _Delivery = _DURABLE
    # Carried for per-client filtering (profile/entity subscriptions).
    profile_id: Optional[str] = None
    # Direct frames only: called if the connection is torn down before this
    # frame was written, so the sender can release what it reserved.
    on_undelivered: Optional[Callable[[], Awaitable[None]]] = None
    # Scoped clients get this frame in full only if they subscribe to one of
    # these topics; None means every client is interested.
    topics: Optional[tuple] = None
    # A preview image rides in this frame; scoped clients get it only if they
    # subscribe to one of these topics and their preview policy allows it.
    preview_topics: Optional[tuple] = None
    preview_bytes: int = 0
    # Lazily built alternatives ("summary" for an uninterested client,
    # "no_preview" for one that declines the image). Each is serialized at
    # most once per broadcast and shared by every client that takes it.
    _variant_factories: Dict[str, Callable[[], "OutboundFrame"]] = field(
        default_factory=dict, repr=False
    )
    _variants: Dict[str, "OutboundFrame"] = field(default_factory=dict, repr=False)

    @property
    def size(self) -> int:
        return len(self.text)

    def variant(self, name: str) -> Optional["OutboundFrame"]:
        built = self._variants.get(name)
        if built is None:
            factory = self._variant_factories.get(name)
            if factory is None:
                return None
            built = self._variants[name] = factory()
        return built

    def seal(self) -> None:
        """Release the variant builders (they retain the source payload)."""
        self._variant_factories.clear()
        for built in self._variants.values():
            built.seal()


# --- Realtime scopes ------------------------------------------------------
#
# A client that declares the realtime capability (``?realtime=1`` on connect,
# or any ``realtime_*`` message) gets a scope: its profile, the entities it
# is looking at (topics) and its preview policy. A client that never declares
# it is a legacy client and receives every broadcast exactly as before.
#
# For a scoped client:
# - Frames tagged with another profile are not delivered. Untagged (global)
#   frames always are.
# - Heavy per-entity detail is delivered only for subscribed topics:
#     chat:<id>            chat items, plan/node progress and usage for one chat
#     generator:<id>       full job detail and progress ticks for one generator
#                          instance (a tool view's job feed)
#     generation           the same for every generator instance
#     previews:<id>        generation preview images for one generator instance
#     previews             preview images for every generator instance
# - Job lifecycle events for a generator instance the client does not follow
#   arrive as small summaries (ids, status, result), so every client still learns
#   that remote work exists, starts and finishes.
REALTIME_PROTOCOL = 1
REALTIME_MAX_TOPICS = 256
REALTIME_MAX_TOPIC_LENGTH = 256
REALTIME_MAX_PROFILE_LENGTH = 128
PREVIEW_MIN_FPS = 0.1
PREVIEW_MAX_FPS = 60.0

_JOB_LIFECYCLE_EVENTS = frozenset({
    "generation_job_queued",
    "generation_job_started",
    "generation_job_completed",
    "generation_job_failed",
    "generation_job_cancelled",
})
# What a client that does not show a job's feed needs to know about it:
# that it exists, whose it is, how it ended and what it produced (activity
# counts, unseen dots, image editor candidates). Parameters, paths, worker
# and timing detail are for the job's own feed.
_JOB_SUMMARY_FIELDS = (
    "id",
    "status",
    "task_type",
    "tool_id",
    "generator_instance_id",
    "profile_id",
    "project_id",
    "batch_id",
    "batch_total",
    "batch_output_set_id",
    "result_media_id",
    "result_asset_id",
    "error",
)
# Per-chat detail that only an open view of that chat renders. Chat list and
# activity summaries (chat_updated, agent_started/stopped, ...) stay global.
_CHAT_DETAIL_EVENTS = frozenset({
    "chat_item_created",
    "chat_item_updated",
    "chat_item_deleted",
    "agent_node_progress",
    "agent_planning",
    "agent_executing",
    "plan_status_changed",
    "plan_node_updated",
    "llm_usage",
})


def _job_summary(data: dict) -> dict:
    job = data["job"]
    return {
        **data,
        "job": {k: job[k] for k in _JOB_SUMMARY_FIELDS if k in job},
        "detail": "summary",
    }


def _without_preview(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in ("preview_b64", "preview_mime")}


def _generator_instance_of(data: dict) -> Optional[str]:
    gid = data.get("generator_instance_id")
    if not gid and isinstance(data.get("job"), dict):
        gid = data["job"].get("generator_instance_id")
    return gid if isinstance(gid, str) and gid else None


def build_frame(event: str, data: dict) -> OutboundFrame:
    """Serialize a broadcast once and attach its interest metadata."""
    profile_id = data.get("profile_id")
    topics = preview_topics = None
    preview_bytes = 0
    factories: Dict[str, Callable[[], OutboundFrame]] = {}
    if event in _JOB_LIFECYCLE_EVENTS:
        gid = _generator_instance_of(data)
        # A job without an instance is shown by any feed; keep it whole.
        if gid and isinstance(data.get("job"), dict):
            topics = ("generation", f"generator:{gid}")
            factories["summary"] = lambda: build_frame(event, _job_summary(data))
    elif event == "generation_job_progress":
        gid = _generator_instance_of(data)
        if gid:
            topics = ("generation", f"generator:{gid}")
        preview = data.get("preview_b64")
        if preview:
            preview_topics = ("previews", f"previews:{gid}") if gid else ("previews",)
            preview_bytes = len(preview) if isinstance(preview, str) else 0
            factories["no_preview"] = lambda: build_frame(event, _without_preview(data))
    elif event in _CHAT_DETAIL_EVENTS:
        chat_id = data.get("chat_id")
        if chat_id is not None:
            topics = (f"chat:{chat_id}",)
    return OutboundFrame(
        event=event,
        text=json.dumps({"event": event, "data": data}),
        delivery=_delivery_policy(event, data),
        profile_id=profile_id if isinstance(profile_id, str) else None,
        topics=topics,
        preview_topics=preview_topics,
        preview_bytes=preview_bytes,
        _variant_factories=factories,
    )


def _parse_topics(value: Any) -> set:
    if not isinstance(value, list):
        raise ValueError("topics must be a list")
    topics = set()
    for topic in value:
        if not isinstance(topic, str) or not topic or len(topic) > REALTIME_MAX_TOPIC_LENGTH:
            raise ValueError("invalid topic")
        topics.add(topic)
    if len(topics) > REALTIME_MAX_TOPICS:
        raise ValueError("too many topics")
    return topics


def _parse_previews(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("previews must be an object")
    parsed = {}
    if "enabled" in value:
        if not isinstance(value["enabled"], bool):
            raise ValueError("previews.enabled must be a boolean")
        parsed["enabled"] = value["enabled"]
    if "max_fps" in value:
        fps = value["max_fps"]
        if fps is not None:
            if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
                raise ValueError("previews.max_fps must be a positive number or null")
            fps = min(max(float(fps), PREVIEW_MIN_FPS), PREVIEW_MAX_FPS)
        parsed["max_fps"] = fps
    for name in ("max_bytes", "max_bytes_per_second"):
        if name in value:
            limit = value[name]
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
                raise ValueError(f"previews.{name} must be a positive integer or null")
            parsed[name] = limit
    return parsed


def _parse_profile(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > REALTIME_MAX_PROFILE_LENGTH:
        raise ValueError("invalid profile_id")
    return value


class RealtimeScope:
    """What one capability-declaring client wants delivered."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.profile_id: Optional[str] = None
        self.topics: set = set()
        self.previews_enabled = True
        # The preview budget is per connection, across every job it follows:
        # at most max_fps images per second, max_bytes_per_second on average
        # (one second of burst), and no single image over max_bytes.
        self.preview_max_fps: Optional[float] = None
        self.preview_max_bytes: Optional[int] = None
        self.preview_max_bytes_per_second: Optional[int] = None
        self._clock = clock
        self._last_preview_at: Optional[float] = None
        self._preview_tokens = 0.0
        self._tokens_at: Optional[float] = None

    def update(self, kind: str, payload: Any) -> None:
        """Apply a scope message atomically; ValueError leaves it unchanged.

        ``scope`` replaces each field it names (profile_id, topics, previews);
        ``subscribe`` / ``unsubscribe`` add or remove topics.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        if kind in ("subscribe", "unsubscribe"):
            changed = _parse_topics(payload.get("topics"))
            topics = self.topics | changed if kind == "subscribe" else self.topics - changed
            if len(topics) > REALTIME_MAX_TOPICS:
                raise ValueError("too many topics")
            self.topics = topics
            return
        if kind != "scope":
            raise ValueError("unknown scope message")
        profile_id = _parse_profile(payload["profile_id"]) if "profile_id" in payload else self.profile_id
        topics = _parse_topics(payload["topics"]) if "topics" in payload else self.topics
        previews = _parse_previews(payload["previews"]) if "previews" in payload else {}
        self.profile_id = profile_id
        self.topics = topics
        self.previews_enabled = previews.get("enabled", self.previews_enabled)
        self.preview_max_fps = previews.get("max_fps", self.preview_max_fps)
        self.preview_max_bytes = previews.get("max_bytes", self.preview_max_bytes)
        self.preview_max_bytes_per_second = previews.get(
            "max_bytes_per_second", self.preview_max_bytes_per_second
        )

    def describe(self) -> dict:
        return {
            "protocol": REALTIME_PROTOCOL,
            "profile_id": self.profile_id,
            "topics": sorted(self.topics),
            "previews": {
                "enabled": self.previews_enabled,
                "max_fps": self.preview_max_fps,
                "max_bytes": self.preview_max_bytes,
                "max_bytes_per_second": self.preview_max_bytes_per_second,
            },
        }

    @property
    def preview_budgeted(self) -> bool:
        return bool(self.preview_max_fps or self.preview_max_bytes_per_second)

    def _allows_preview(self, frame: OutboundFrame) -> bool:
        if not self.previews_enabled:
            return False
        if frame.preview_topics is not None and self.topics.isdisjoint(frame.preview_topics):
            return False
        size = frame.preview_bytes
        if self.preview_max_bytes is not None and size > self.preview_max_bytes:
            return False
        now = self._clock()
        if self.preview_max_fps and self._last_preview_at is not None:
            if now - self._last_preview_at < 1.0 / self.preview_max_fps:
                return False
        rate = self.preview_max_bytes_per_second
        if rate:
            # Token bucket holding at most one second of budget.
            if self._tokens_at is None:
                self._preview_tokens = float(rate)
            else:
                self._preview_tokens = min(
                    float(rate), self._preview_tokens + (now - self._tokens_at) * rate
                )
            self._tokens_at = now
            if size > self._preview_tokens:
                return False
            self._preview_tokens -= size
        self._last_preview_at = now
        return True

    def select(self, frame: OutboundFrame) -> Optional[OutboundFrame]:
        if (
            frame.profile_id is not None
            and self.profile_id is not None
            and frame.profile_id != self.profile_id
        ):
            return None
        if frame.topics is not None and self.topics.isdisjoint(frame.topics):
            # Not following this entity: a summary if the event has one
            # (job lifecycle), otherwise nothing (detail, progress ticks).
            return frame.variant("summary")
        if frame.preview_bytes and not self._allows_preview(frame):
            return frame.variant("no_preview")
        return frame


def scope_from_query(params) -> Optional[RealtimeScope]:
    """Build the initial scope from connect-time query parameters.

    ``/ws?realtime=1&profile=P&topic=T&topic=U&previews=0&preview_fps=2&preview_bytes=N&preview_bps=R``.
    Applying it before the socket is registered closes the gap between
    connecting and subscribing. Returns None for a legacy client.
    """
    if params.get("realtime") != "1":
        return None
    payload: Dict[str, Any] = {"topics": list(params.getlist("topic"))}
    if params.get("profile"):
        payload["profile_id"] = params.get("profile")
    previews: Dict[str, Any] = {}
    if params.get("previews") in ("0", "1"):
        previews["enabled"] = params.get("previews") == "1"
    try:
        if params.get("preview_fps"):
            previews["max_fps"] = float(params.get("preview_fps"))
        if params.get("preview_bytes"):
            previews["max_bytes"] = int(params.get("preview_bytes"))
        if params.get("preview_bps"):
            previews["max_bytes_per_second"] = int(params.get("preview_bps"))
    except ValueError:
        raise ValueError("invalid preview policy")
    if previews:
        payload["previews"] = previews
    scope = RealtimeScope()
    scope.update("scope", payload)
    return scope


class _Entry:
    """A queue slot. Replaced or shed entries become tombstones in place, so
    removing one never scans the queue. A tombstone drops its frame at once,
    so discarded payloads never outlive the byte accounting."""

    __slots__ = ("frame", "alive")

    def __init__(self, frame: Optional[OutboundFrame]):
        self.frame = frame
        self.alive = True


class ClientConnection:
    """A connected client: its socket, bounded outbound queue and sender task.

    Every enqueue costs O(1) amortized, however long the backlog grows.
    """

    def __init__(
        self,
        websocket: WebSocket,
        on_failure: Callable[["ClientConnection", str], None],
        *,
        soft_max_frames: int = CLIENT_SOFT_MAX_FRAMES,
        soft_max_bytes: int = CLIENT_SOFT_MAX_BYTES,
        hard_max_frames: int = CLIENT_HARD_MAX_FRAMES,
        hard_max_bytes: int = CLIENT_HARD_MAX_BYTES,
        send_timeout: float = CLIENT_SEND_TIMEOUT_SECONDS,
    ):
        self.websocket = websocket
        self.soft_max_frames = soft_max_frames
        self.soft_max_bytes = soft_max_bytes
        self.hard_max_frames = hard_max_frames
        self.hard_max_bytes = hard_max_bytes
        self.send_timeout = send_timeout
        self._on_failure = on_failure
        self._queue: deque[_Entry] = deque()
        self._live = 0
        self._tombstones = 0
        self._queued_bytes = 0
        # key -> the pending entry a newer same-key frame may replace
        self._replaceable: Dict[tuple, _Entry] = {}
        # Sheddable entries, oldest first.
        self._sheddable: "OrderedDict[int, _Entry]" = OrderedDict()
        self._in_flight: Optional[OutboundFrame] = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: Optional[asyncio.Task] = None
        self.closed = False
        self.coalesced = 0
        self.shed = 0
        # None until the client declares the realtime capability.
        self.scope: Optional[RealtimeScope] = None
        # A budgeted client holds at most one unsent preview image: a newer
        # image (any job) replaces it, so a slow link never drains a burst.
        self._pending_preview: Optional[_Entry] = None

    @property
    def queued_frames(self) -> int:
        return self._live

    @property
    def queued_bytes(self) -> int:
        return self._queued_bytes

    @property
    def idle(self) -> bool:
        return self._idle.is_set()

    @property
    def sender_task(self) -> Optional[asyncio.Task]:
        return self._task

    def pending_frames(self) -> List[OutboundFrame]:
        return [entry.frame for entry in self._queue if entry.alive]

    def frame_for(self, frame: OutboundFrame) -> Optional[OutboundFrame]:
        """The form of a broadcast frame this client receives, if any.

        A legacy client (no realtime scope) receives every broadcast as is
        and filters by profile itself.
        """
        if self.scope is None:
            return frame
        return self.scope.select(frame)

    def enqueue(self, frame: OutboundFrame) -> bool:
        """Queue a frame without waiting.

        Returns False only when a durable frame would exceed the hard cap; the
        caller then disconnects the client. Shedding a transient frame is not
        a failure.
        """
        if self.closed:
            return False
        delivery = frame.delivery
        if delivery.key is not None:
            previous = self._replaceable.get(delivery.key)
            if previous is not None:
                # Latest wins, at the tail: the new frame keeps its true order
                # relative to everything enqueued in between.
                self._discard(previous)
                self.coalesced += 1
        if delivery.sheddable:
            if not self._make_room(frame.size, self.soft_max_frames, self.soft_max_bytes):
                self.shed += 1
                return True
        else:
            # Transient frames give way first, at the soft budget, so durable
            # frames only ever compete with each other for the hard cap.
            self._make_room(frame.size, self.soft_max_frames, self.soft_max_bytes)
            if not self._make_room(frame.size, self.hard_max_frames, self.hard_max_bytes):
                return False
        latest_preview = (
            frame.preview_bytes > 0
            and frame.preview_topics is not None
            and self.scope is not None
            and self.scope.preview_budgeted
        )
        if latest_preview and self._pending_preview is not None:
            self._discard(self._pending_preview)
            self.coalesced += 1
        entry = _Entry(frame)
        if latest_preview:
            self._pending_preview = entry
        self._queue.append(entry)
        self._live += 1
        self._queued_bytes += frame.size
        if delivery.replaceable:
            self._replaceable[delivery.key] = entry
        if delivery.sheddable:
            self._sheddable[id(entry)] = entry
        self._idle.clear()
        self._wake.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        return True

    def _unindex(self, entry: _Entry) -> None:
        entry.alive = False
        self._live -= 1
        self._queued_bytes -= entry.frame.size
        key = entry.frame.delivery.key
        if key is not None and self._replaceable.get(key) is entry:
            del self._replaceable[key]
        if self._pending_preview is entry:
            self._pending_preview = None
        self._sheddable.pop(id(entry), None)

    def _discard(self, entry: _Entry) -> None:
        """Drop a still-queued entry, leaving a tombstone in place."""
        self._unindex(entry)
        entry.frame = None
        self._tombstones += 1
        if self._tombstones > 64 and self._tombstones > self._live:
            # Amortized compaction keeps tombstones bounded by the live count.
            self._queue = deque(e for e in self._queue if e.alive)
            self._tombstones = 0

    def _fits(self, size: int, max_frames: int, max_bytes: int) -> bool:
        return self._live < max_frames and self._queued_bytes + size <= max_bytes

    def _make_room(self, size: int, max_frames: int, max_bytes: int) -> bool:
        """Shed sheddable entries, oldest first, until ``size`` more fits."""
        while not self._fits(size, max_frames, max_bytes):
            if not self._sheddable:
                return False
            _, entry = self._sheddable.popitem(last=False)
            self._discard(entry)
            self.shed += 1
        return True

    async def _run(self) -> None:
        # A closed client sends nothing more; stop() also wakes this loop, so
        # it exits even if a cancellation were ever swallowed mid-send.
        while not self.closed:
            if not self._live:
                self._queue.clear()
                self._tombstones = 0
                self._idle.set()
                self._wake.clear()
                await self._wake.wait()
                continue
            entry = self._queue.popleft()
            if not entry.alive:
                self._tombstones -= 1
                continue
            self._unindex(entry)
            frame = entry.frame
            self._in_flight = frame
            try:
                # asyncio.timeout, not wait_for: on 3.11 wait_for can swallow
                # a cancellation that races a completing send.
                async with asyncio.timeout(self.send_timeout):
                    await self.websocket.send_text(frame.text)
            except TimeoutError:
                self._fail("send_timeout")
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("WebSocket send failed", error_type=type(e).__name__)
                self._fail("send_error")
                return
            self._in_flight = None

    def _fail(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        self._idle.set()
        self._on_failure(self, reason)

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def stop(self) -> List[OutboundFrame]:
        """Stop the sender and release the queue.

        Returns the frames that were never confirmed written (queued, or in
        flight when the socket failed or was torn down). The queue is
        released even if the caller is cancelled while the sender stops.
        """
        self.closed = True
        self._wake.set()
        task, self._task = self._task, None
        try:
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                # wait() never re-raises the sender's own cancellation.
                await asyncio.wait({task})
        finally:
            undelivered = self.pending_frames()
            if self._in_flight is not None:
                undelivered.insert(0, self._in_flight)
                self._in_flight = None
            self._queue.clear()
            self._replaceable.clear()
            self._sheddable.clear()
            self._pending_preview = None
            self._live = self._tombstones = self._queued_bytes = 0
            self._idle.set()
        return undelivered


class WebSocketManager:
    """Manages WebSocket connections and delivers events to connected clients."""

    def __init__(
        self,
        *,
        soft_max_frames: int = CLIENT_SOFT_MAX_FRAMES,
        soft_max_bytes: int = CLIENT_SOFT_MAX_BYTES,
        hard_max_frames: int = CLIENT_HARD_MAX_FRAMES,
        hard_max_bytes: int = CLIENT_HARD_MAX_BYTES,
        send_timeout: float = CLIENT_SEND_TIMEOUT_SECONDS,
    ):
        self._clients: Dict[int, ClientConnection] = {}
        self._client_limits = dict(
            soft_max_frames=soft_max_frames,
            soft_max_bytes=soft_max_bytes,
            hard_max_frames=hard_max_frames,
            hard_max_bytes=hard_max_bytes,
            send_timeout=send_timeout,
        )
        # Track generator_instance_id -> websocket mapping for cleanup on disconnect
        self._generator_instance_websockets: Dict[str, WebSocket] = {}
        # generator_instance_id -> registration generation (ownership token)
        self._generator_registrations: Dict[str, int] = {}
        self._registration_seq = 0
        # Callback for when a generator instance disconnects
        self._on_generator_disconnect: Optional[Callable[[str], Awaitable[None]]] = None
        # Strong references to in-flight client drops.
        self._dropping: set[asyncio.Task] = set()
        # Strong references to running disconnect teardowns.
        self._teardowns: set[asyncio.Task] = set()
        self._closing = False

    @property
    def active_connections(self) -> List[WebSocket]:
        """Snapshot of connected sockets (read-only; use attach/disconnect)."""
        return [client.websocket for client in self._clients.values()]

    @property
    def clients(self) -> List[ClientConnection]:
        return list(self._clients.values())

    def client_for(self, websocket: WebSocket) -> Optional[ClientConnection]:
        return self._clients.get(id(websocket))

    def set_on_generator_disconnect(self, callback: Callable[..., Awaitable[None]]):
        """Set the cleanup called when a generator instance's socket goes away.

        Called as ``callback(generator_instance_id, still_abandoned=predicate)``;
        the cleanup must stop touching the instance once ``predicate()`` is
        False (the page re-registered it on a newer connection).
        """
        self._on_generator_disconnect = callback

    async def connect(self, websocket: WebSocket, scope: Optional[RealtimeScope] = None):
        """Accept a new WebSocket connection (refused once shutdown began).

        A connect-time ``scope`` is in force before the first broadcast can
        reach this client.
        """
        if self._closing:
            raise WebSocketDisconnect(code=1001)
        await websocket.accept()
        self.attach(websocket, scope)
        log.info(
            f"WebSocket connected. Total connections: {len(self._clients)}",
            scoped=scope is not None,
        )

    def attach(self, websocket: WebSocket, scope: Optional[RealtimeScope] = None) -> ClientConnection:
        """Register an already-accepted socket for delivery."""
        client = self._clients.get(id(websocket))
        if client is None:
            client = ClientConnection(websocket, self._client_failed, **self._client_limits)
            self._clients[id(websocket)] = client
        if scope is not None:
            client.scope = scope
        return client

    def update_scope(self, websocket: WebSocket, kind: str, payload: Any) -> Optional[dict]:
        """Apply a realtime scope message from a client and describe the result.

        The first such message opts a legacy connection in. Takes effect for
        every broadcast after it; nothing already queued is withdrawn. Raises
        ValueError (scope unchanged) for an invalid message; returns None for a
        socket that is no longer attached.
        """
        client = self._clients.get(id(websocket))
        if client is None or client.closed:
            return None
        scope = client.scope if client.scope is not None else RealtimeScope()
        scope.update(kind, payload)
        client.scope = scope
        return scope.describe()

    def register_generator_instance(self, websocket: WebSocket, generator_instance_id: str) -> bool:
        """Associate a generator instance ID with a WebSocket connection.

        Each registration is a new ownership generation: cleanup for an older
        connection must never touch a session that registered after it.
        Returns False, registering nothing, for a socket that is no longer
        attached (its disconnect cleanup may still be running); the page will
        register again on its new connection.
        """
        client = self._clients.get(id(websocket))
        if client is None or client.closed:
            log.info(
                "Ignoring generator registration on a detached WebSocket",
                generator_instance_id=generator_instance_id,
            )
            return False
        self._registration_seq += 1
        self._generator_registrations[generator_instance_id] = self._registration_seq
        self._generator_instance_websockets[generator_instance_id] = websocket
        log.info(f"Registered generator instance {generator_instance_id} with WebSocket")
        return True

    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket, its queue and sender, and its generator instances.

        Every caller (the endpoint's receive loop, a server-initiated drop)
        may race; the first claims the client and its generator instances
        synchronously, so cleanup runs exactly once. The teardown then runs
        in its own task, shielded from the caller: an endpoint that is
        being cancelled (or is cancelled mid-cleanup) still gets its sender
        stopped, its queue released and its undelivered frames reported.
        The caller's cancellation is re-raised after the teardown is handed off.
        """
        client = self._clients.pop(id(websocket), None)
        if client is not None:
            client.closed = True
        disconnected_instances = [
            gid for gid, ws in self._generator_instance_websockets.items()
            if ws == websocket
        ]
        for gid in disconnected_instances:
            del self._generator_instance_websockets[gid]
        owned = {
            gid: self._generator_registrations.get(gid) for gid in disconnected_instances
        }
        if client is None and not owned:
            return

        teardown = asyncio.create_task(self._teardown(client, owned))
        self._teardowns.add(teardown)
        teardown.add_done_callback(self._teardowns.discard)
        await asyncio.shield(teardown)

    async def _teardown(
        self, client: Optional[ClientConnection], owned: Dict[str, Optional[int]]
    ) -> None:
        """Release one claimed connection. Runs exactly once per disconnect.

        If this task is cancelled (shutdown deadline), the bookkeeping in the
        finally block still runs: registrations are released, the sender is
        stopped and unwritten requests are reported.
        """
        try:
            # Instance cleanup first. The cleanup itself awaits, so it is also
            # told whether the instance is still abandoned: a page that
            # re-registers the same ID meanwhile owns it, and an older
            # disconnect must leave it alone.
            for gid, generation in owned.items():
                log.info(f"Generator instance {gid} disconnected")
                if self._on_generator_disconnect:
                    try:
                        await self._on_generator_disconnect(
                            gid,
                            still_abandoned=functools.partial(
                                self._generator_still_abandoned, gid, generation
                            ),
                        )
                    except Exception as e:
                        log.error(f"Error in generator disconnect callback: {e}")
        finally:
            for gid, generation in owned.items():
                if self._generator_still_abandoned(gid, generation):
                    self._generator_registrations.pop(gid, None)
            undelivered = await client.stop() if client is not None else []
            # After instance cleanup, so a released reservation is refilled
            # only by instances that are still connected.
            for frame in undelivered:
                if frame.on_undelivered is not None:
                    try:
                        await frame.on_undelivered()
                    except Exception as e:
                        log.error(f"Error releasing undelivered {frame.event}: {e}")
            if client is not None:
                log.info(f"WebSocket disconnected. Total connections: {len(self._clients)}")

    async def shutdown(self, timeout: float = 5.0) -> None:
        """Disconnect every client and settle teardowns, within ``timeout``.

        Call before the resources teardown uses (generation queue, databases)
        are stopped. New connections are refused from here on. Teardowns
        still running at the deadline are cancelled; their finally blocks
        complete the bookkeeping.
        """
        self._closing = True
        try:
            for client in list(self._clients.values()):
                # Hands each teardown off without waiting on it here.
                task = asyncio.create_task(self.disconnect(client.websocket))
                self._dropping.add(task)
                task.add_done_callback(self._dropping.discard)
            # Let each disconnect claim its client and start its teardown.
            await asyncio.sleep(0)
            pending = {*self._dropping, *self._teardowns}
            if not pending:
                return
            _, still_running = await asyncio.wait(pending, timeout=timeout)
            if still_running:
                log.warning("WebSocket teardowns did not finish in time; cancelling")
                for task in still_running:
                    task.cancel()
                await asyncio.wait(still_running, timeout=CLIENT_CLOSE_TIMEOUT_SECONDS)
        finally:
            # Admission reopens only for an app that starts serving again
            # in the same process (tests); the server has stopped by now.
            self._closing = False

    def _generator_still_abandoned(self, generator_instance_id: str, generation: Optional[int]) -> bool:
        return (
            generator_instance_id not in self._generator_instance_websockets
            and self._generator_registrations.get(generator_instance_id) == generation
        )

    def _client_failed(self, client: ClientConnection, reason: str) -> None:
        """Drop a client that is stalled or dead, as a network drop would."""
        if self._clients.get(id(client.websocket)) is not client:
            return
        client.closed = True
        log.warning(
            "Dropping stalled WebSocket client",
            reason=reason,
            queued_frames=client.queued_frames,
            queued_bytes=client.queued_bytes,
        )
        task = asyncio.create_task(self._drop(client))
        self._dropping.add(task)
        task.add_done_callback(self._dropping.discard)

    async def _drop(self, client: ClientConnection) -> None:
        websocket = client.websocket
        await self.disconnect(websocket)
        try:
            async with asyncio.timeout(CLIENT_CLOSE_TIMEOUT_SECONDS):
                await websocket.close(code=OVERFLOW_CLOSE_CODE)
        except Exception:
            # Already closed or half-open; the transport is torn down anyway.
            pass

    def _deliver(self, client: ClientConnection, frame: OutboundFrame) -> bool:
        if client.enqueue(frame):
            return True
        if not client.closed:
            self._client_failed(client, "queue_overflow")
        return False

    async def drain(self) -> None:
        """Wait until every client's queue is written or dropped."""
        while True:
            busy = [c for c in self._clients.values() if not c.idle]
            if busy:
                await asyncio.gather(*(c.wait_idle() for c in busy))
            elif self._dropping or self._teardowns:
                await asyncio.gather(
                    *list(self._dropping), *list(self._teardowns), return_exceptions=True
                )
            else:
                return

    async def broadcast(self, event: str, data: dict, include_profile: bool = True):
        """Broadcast an event to all connected clients.

        Delivery is queued per client and never waits on a client's socket,
        so a slow client cannot delay others or the broadcasting caller.

        Args:
            event: The event name
            data: The event data
            include_profile: If True, automatically adds profile_id to the data
                            for client-side filtering. Set to False for truly
                            global events (like processing_stats).
        """
        pending = _broadcast_buffer.get()
        if pending is not None and pending[0] is asyncio.current_task():
            pending[1].append((self, event, deepcopy(data), include_profile))
            return
        if not self._clients:
            log.debug(f"No active WebSocket connections to broadcast '{event}' to")
            return

        # Work starting or finishing anywhere changes project activity. One
        # hook here covers jobs, agent runs and flows, whoever broadcasts them.
        from project_activity import ACTIVITY_TRIGGER_EVENTS, schedule_project_activity_broadcast
        if event in ACTIVITY_TRIGGER_EVENTS:
            schedule_project_activity_broadcast()

        # Automatically include profile_id for profile-specific events
        if include_profile and 'profile_id' not in data:
            try:
                data = {**data, 'profile_id': get_current_profile()}
            except Exception:
                # If we can't get profile, send without it (worker threads, etc.)
                pass

        # Serialize once; every client's queue shares the same frame (or the
        # same shared variant of it).
        frame = build_frame(event, data)
        # Log outgoing broadcast (truncate data for readability)
        # Skip noisy high-frequency events
        if event not in ("processing_stats",):
            # For generation job events, log key fields for debugging
            if event.startswith("generation_job_"):
                job_id = data.get('job', {}).get('id')
                gen_inst_id = data.get('generator_instance_id')
                profile_id = data.get('profile_id') or data.get('job', {}).get('profile_id')
                log.info(f"WS OUT (broadcast): {event} - job_id={job_id}, generator_instance_id={gen_inst_id}, profile_id={profile_id}")
            else:
                log.info(
                    "WS OUT (broadcast)",
                    ws_event=event,
                    **_payload_log_metadata(data),
                )

        for client in list(self._clients.values()):
            selected = client.frame_for(frame)
            if selected is not None:
                self._deliver(client, selected)
        frame.seal()
        # Yield once so sender tasks keep pace with a caller that broadcasts in
        # a tight loop; otherwise a burst could fill even a healthy client's
        # queue before its sender ever runs. This never waits on a socket.
        await asyncio.sleep(0)

    async def broadcast_profile_details(self, event: str, data: dict, details: Dict[str, dict]):
        """Broadcast a global event, with per-profile detail only where it belongs.

        Every client receives ``data`` exactly as a global broadcast would
        send it. A client that declared a realtime scope for a profile in
        ``details`` instead receives ``data`` merged with that profile's
        detail and tagged with its ``profile_id``. Legacy clients and scoped
        clients without a profile never see any profile's detail.
        """
        if not self._clients:
            return
        shared = build_frame(event, data)
        tailored: Dict[str, OutboundFrame] = {}
        for client in list(self._clients.values()):
            profile = client.scope.profile_id if client.scope is not None else None
            frame = shared
            if profile is not None and profile in details:
                frame = tailored.get(profile)
                if frame is None:
                    frame = tailored[profile] = build_frame(event, {**data, **details[profile], "profile_id": profile})
            selected = client.frame_for(frame)
            if selected is not None:
                self._deliver(client, selected)
        shared.seal()
        for frame in tailored.values():
            frame.seal()
        await asyncio.sleep(0)

    async def send_to(
        self,
        websocket: WebSocket,
        event: str,
        data: dict,
        *,
        on_undelivered: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> bool:
        """Send an event to a specific client.

        A registered client receives it through its ordered queue, so a direct
        reply never interleaves with, or races, a concurrent broadcast write.
        Returns whether the event was accepted for delivery. If it was, but
        the connection is torn down before it is written, ``on_undelivered``
        runs during disconnect cleanup.
        """
        message = json.dumps({"event": event, "data": data})
        # Log outgoing message shape, never its content.
        if event != "pong":
            log.info(
                "WS OUT (direct)",
                ws_event=event,
                **_payload_log_metadata(data),
            )
        client = self._clients.get(id(websocket))
        if client is not None:
            return self._deliver(
                client,
                OutboundFrame(event=event, text=message, on_undelivered=on_undelivered),
            )
        # Not attached, or already detached by disconnect: never write to it
        # directly. A raw send could block, and its failure would re-enter
        # disconnect cleanup from whatever called us.
        log.debug("Dropping direct WebSocket send to a detached client", ws_event=event)
        return False

    async def send_to_generator_instance(
        self,
        generator_instance_id: str,
        event: str,
        data: dict,
        *,
        on_undelivered: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> bool:
        """Send only to the socket that registered this generator instance.

        True means the message was queued for a live client. If that client
        is torn down before the message is written, ``on_undelivered`` runs
        (after the instance's own disconnect cleanup).
        """
        websocket = self._generator_instance_websockets.get(generator_instance_id)
        if websocket is None:
            log.warning(
                "No WebSocket registered for generator instance",
                generator_instance_id=generator_instance_id,
                ws_event=event,
            )
            return False
        try:
            return await self.send_to(websocket, event, data, on_undelivered=on_undelivered)
        except Exception:
            return False

# Global WebSocket manager instance
ws_manager = WebSocketManager()


async def broadcast_media_updated(media_items, fields: list[str], session=None, include_ephemeral: bool = False):
    """
    Broadcast media_updated event for one or more media items.

    Args:
        media_items: Single MediaItem or list of MediaItems (must have to_dict method)
        fields: List of field names that changed (e.g., ["markers"], ["tags"], ["caption", "prompt"])
        session: Optional database session for refreshing items
        include_ephemeral: When False (default), media tagged with ephemeral_run_id (one-shot
            flow-as-tool run intermediates) are silently skipped so no media_updated event ever
            surfaces them. One guard here covers every caller.
    """
    from sqlalchemy import select

    # Normalize to list
    if not isinstance(media_items, list):
        media_items = [media_items]

    if not media_items:
        return

    # Drop ephemeral one-shot-run intermediates before they can reach any client.
    # getattr guard: callers may pass lightweight objects, but real MediaItems carry the field.
    if not include_ephemeral:
        media_items = [
            item for item in media_items
            if getattr(item, "ephemeral_run_id", None) is None
        ]
        if not media_items:
            return

    # If session provided, refresh items to get latest data with relationships
    if session:
        from database import MediaItem
        from asset_association_service import media_compatibility_projections
        media_ids = [item.id for item in media_items]
        # Use populate_existing=True to force refresh from DB, bypassing identity map cache
        result = await session.execute(
            select(MediaItem)
            .where(MediaItem.id.in_(media_ids))
            .execution_options(populate_existing=True)
        )
        media_items = result.scalars().all()

    projections = (
        await media_compatibility_projections(session, media_items)
        if session
        else [item.to_dict() for item in media_items]
    )

    # Broadcast update for each item
    for item in projections:
        await ws_manager.broadcast("media_updated", {
            "media_id": item.get("media_id", item["id"]),
            "asset_id": item.get("asset_id"),
            "fields": fields,
            "media": item,
        })

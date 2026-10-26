"""WebSocket connection management for real-time updates."""
import asyncio
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from core.logging import get_logger
from typing import List, Dict, Optional, Callable, Awaitable
from fastapi import WebSocket

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
#   send misses the deadline, is stalled or dead and is disconnected, exactly
#   as if its network had dropped.
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
# A client the server disconnects for backpressure did not abandon its work.
# Its generator instances keep their queued jobs for this long so the page can
# reconnect and re-register the same instance; only then is it abandoned.
GENERATOR_REATTACH_GRACE_SECONDS = 120.0

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

    @property
    def size(self) -> int:
        return len(self.text)


class ClientConnection:
    """A connected client: its socket, bounded outbound queue and sender task."""

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
        self._queue: deque[OutboundFrame] = deque()
        # key -> the pending frame a newer same-key frame may replace
        self._replaceable: Dict[tuple, OutboundFrame] = {}
        self._queued_bytes = 0
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: Optional[asyncio.Task] = None
        self.closed = False
        self.coalesced = 0
        self.shed = 0

    @property
    def queued_frames(self) -> int:
        return len(self._queue)

    @property
    def queued_bytes(self) -> int:
        return self._queued_bytes

    @property
    def idle(self) -> bool:
        return self._idle.is_set()

    @property
    def sender_task(self) -> Optional[asyncio.Task]:
        return self._task

    def wants(self, frame: OutboundFrame) -> bool:
        """Whether this client should receive a broadcast frame.

        Every client receives every broadcast today (the UI filters by
        profile). Per-client subscriptions plug in here.
        """
        return True

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
            previous = self._replaceable.pop(delivery.key, None)
            if previous is not None:
                # Latest wins, at the tail: the new frame keeps its true order
                # relative to everything enqueued in between.
                self._remove(previous)
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
        self._queue.append(frame)
        self._queued_bytes += frame.size
        if delivery.replaceable:
            self._replaceable[delivery.key] = frame
        self._idle.clear()
        self._wake.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        return True

    def _remove(self, frame: OutboundFrame) -> None:
        self._queue.remove(frame)
        self._queued_bytes -= frame.size

    def _fits(self, size: int, max_frames: int, max_bytes: int) -> bool:
        return len(self._queue) < max_frames and self._queued_bytes + size <= max_bytes

    def _make_room(self, size: int, max_frames: int, max_bytes: int) -> bool:
        """Shed sheddable frames, oldest first, until ``size`` more fits."""
        if self._fits(size, max_frames, max_bytes):
            return True
        for frame in [f for f in self._queue if f.delivery.sheddable]:
            if self._replaceable.get(frame.delivery.key) is frame:
                del self._replaceable[frame.delivery.key]
            self._remove(frame)
            self.shed += 1
            if self._fits(size, max_frames, max_bytes):
                return True
        return False

    async def _run(self) -> None:
        # A closed client sends nothing more; stop() also wakes this loop, so
        # it exits even if a cancellation were ever swallowed mid-send.
        while not self.closed:
            if not self._queue:
                self._idle.set()
                self._wake.clear()
                await self._wake.wait()
                continue
            frame = self._queue.popleft()
            self._queued_bytes -= frame.size
            key = frame.delivery.key
            if key is not None and self._replaceable.get(key) is frame:
                del self._replaceable[key]
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

    def _fail(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        self._idle.set()
        self._on_failure(self, reason)

    async def wait_idle(self) -> None:
        await self._idle.wait()

    async def stop(self) -> None:
        """Stop the sender and release everything queued."""
        self.closed = True
        self._wake.set()
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception:
                pass
        self._queue.clear()
        self._replaceable.clear()
        self._queued_bytes = 0
        self._idle.set()


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
        generator_reattach_grace: float = GENERATOR_REATTACH_GRACE_SECONDS,
    ):
        self._clients: Dict[int, ClientConnection] = {}
        self._client_limits = dict(
            soft_max_frames=soft_max_frames,
            soft_max_bytes=soft_max_bytes,
            hard_max_frames=hard_max_frames,
            hard_max_bytes=hard_max_bytes,
            send_timeout=send_timeout,
        )
        self._generator_reattach_grace = generator_reattach_grace
        # Track generator_instance_id -> websocket mapping for cleanup on disconnect
        self._generator_instance_websockets: Dict[str, WebSocket] = {}
        # Callback for when a generator instance disconnects
        self._on_generator_disconnect: Optional[Callable[[str], Awaitable[None]]] = None
        # Strong references to in-flight client drops.
        self._dropping: set[asyncio.Task] = set()
        # Generator instances detached by a server-initiated drop, awaiting
        # re-registration before they are treated as abandoned.
        self._generator_grace: Dict[str, asyncio.Task] = {}

    @property
    def active_connections(self) -> List[WebSocket]:
        """Snapshot of connected sockets (read-only; use attach/disconnect)."""
        return [client.websocket for client in self._clients.values()]

    @property
    def clients(self) -> List[ClientConnection]:
        return list(self._clients.values())

    def client_for(self, websocket: WebSocket) -> Optional[ClientConnection]:
        return self._clients.get(id(websocket))

    def set_on_generator_disconnect(self, callback: Callable[[str], Awaitable[None]]):
        """Set callback to be called when a generator instance disconnects."""
        self._on_generator_disconnect = callback

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.attach(websocket)
        log.info(f"WebSocket connected. Total connections: {len(self._clients)}")

    def attach(self, websocket: WebSocket) -> ClientConnection:
        """Register an already-accepted socket for delivery."""
        client = self._clients.get(id(websocket))
        if client is None:
            client = ClientConnection(websocket, self._client_failed, **self._client_limits)
            self._clients[id(websocket)] = client
        return client

    def register_generator_instance(self, websocket: WebSocket, generator_instance_id: str):
        """Associate a generator instance ID with a WebSocket connection."""
        grace = self._generator_grace.pop(generator_instance_id, None)
        if grace is not None:
            grace.cancel()
            log.info(f"Generator instance {generator_instance_id} re-attached within grace window")
        self._generator_instance_websockets[generator_instance_id] = websocket
        log.info(f"Registered generator instance {generator_instance_id} with WebSocket")

    async def disconnect(self, websocket: WebSocket, *, abandoned: bool = True):
        """Remove a disconnected WebSocket, its queue and sender, and its generator instances.

        ``abandoned=False`` is for server-initiated drops (backpressure, send
        deadline): the page did not go away, so its generator instances get a
        grace window to re-register before their queued work is cancelled.
        """
        client = self._clients.pop(id(websocket), None)
        if client is not None:
            await client.stop()

        # Find and clean up any generator instances associated with this websocket
        disconnected_instances = [
            gid for gid, ws in self._generator_instance_websockets.items()
            if ws == websocket
        ]
        for gid in disconnected_instances:
            del self._generator_instance_websockets[gid]
            if not abandoned:
                log.info(f"Generator instance {gid} detached; awaiting re-registration")
                self._generator_grace[gid] = asyncio.create_task(
                    self._expire_generator_grace(gid)
                )
                continue
            log.info(f"Generator instance {gid} disconnected")
            await self._abandon_generator_instance(gid)

        log.info(f"WebSocket disconnected. Total connections: {len(self._clients)}")

    async def _abandon_generator_instance(self, generator_instance_id: str) -> None:
        if self._on_generator_disconnect:
            try:
                await self._on_generator_disconnect(generator_instance_id)
            except Exception as e:
                log.error(f"Error in generator disconnect callback: {e}")

    async def _expire_generator_grace(self, generator_instance_id: str) -> None:
        await asyncio.sleep(self._generator_reattach_grace)
        if self._generator_grace.get(generator_instance_id) is not asyncio.current_task():
            return
        del self._generator_grace[generator_instance_id]
        if generator_instance_id in self._generator_instance_websockets:
            return
        log.info(f"Generator instance {generator_instance_id} did not re-attach; abandoning")
        await self._abandon_generator_instance(generator_instance_id)

    def _client_failed(self, client: ClientConnection, reason: str) -> None:
        """Drop a client that is stalled or dead, as a network drop would."""
        if self._clients.get(id(client.websocket)) is not client:
            return
        client.closed = True
        log.warning(
            "Dropping slow WebSocket client",
            reason=reason,
            queued_frames=client.queued_frames,
            queued_bytes=client.queued_bytes,
        )
        task = asyncio.create_task(self._drop(client))
        self._dropping.add(task)
        task.add_done_callback(self._dropping.discard)

    async def _drop(self, client: ClientConnection) -> None:
        websocket = client.websocket
        await self.disconnect(websocket, abandoned=False)
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
            elif self._dropping:
                await asyncio.gather(*list(self._dropping), return_exceptions=True)
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

        # Serialize once; every client's queue shares the same frame.
        profile_id = data.get('profile_id')
        frame = OutboundFrame(
            event=event,
            text=json.dumps({"event": event, "data": data}),
            delivery=_delivery_policy(event, data),
            profile_id=profile_id if isinstance(profile_id, str) else None,
        )
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
            if client.wants(frame):
                self._deliver(client, frame)
        # Yield once so sender tasks keep pace with a caller that broadcasts in
        # a tight loop; otherwise a burst could fill even a healthy client's
        # queue before its sender ever runs. This never waits on a socket.
        await asyncio.sleep(0)

    async def send_to(self, websocket: WebSocket, event: str, data: dict):
        """Send an event to a specific client.

        A registered client receives it through its ordered queue, so a direct
        reply never interleaves with, or races, a concurrent broadcast write.
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
            self._deliver(client, OutboundFrame(event=event, text=message))
            return
        try:
            async with asyncio.timeout(CLIENT_SEND_TIMEOUT_SECONDS):
                await websocket.send_text(message)
        except Exception as e:
            log.error(f"Error sending to client: {e}")
            await self.disconnect(websocket)

    async def send_to_generator_instance(self, generator_instance_id: str, event: str, data: dict) -> bool:
        """Send only to the socket that registered this generator instance.

        True means the message was queued for a live client. A client that
        later stalls is dropped, which also releases its generator instance.
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
            await self.send_to(websocket, event, data)
            client = self._clients.get(id(websocket))
            return client is not None and not client.closed
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

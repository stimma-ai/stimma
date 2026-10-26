"""WebSocket connection management for real-time updates."""
import asyncio
import functools
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass
from core.logging import get_logger
from typing import List, Dict, Optional, Callable, Awaitable
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

    @property
    def size(self) -> int:
        return len(self.text)


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
        entry = _Entry(frame)
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

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection (refused once shutdown began)."""
        if self._closing:
            raise WebSocketDisconnect(code=1001)
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

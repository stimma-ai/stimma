"""Per-client WebSocket delivery: isolation, bounds, coalescing and cleanup.

Every connected client has its own outbound queue and sender task. A slow or
half-open client (a phone on a weak cellular link) must not delay any other
client and must not grow memory without bound. Only transient progress frames
are ever coalesced or shed; durable state changes (including terminal and
error transitions) are never dropped while the client is connected. A client
past the hard cap, or whose send misses the deadline, is disconnected as a
network drop would, without abandoning its generator work.
"""
import asyncio
import json

from fastapi import FastAPI
from starlette.testclient import TestClient

from utils.websocket import OVERFLOW_CLOSE_CODE, WebSocketManager


class Healthy:
    def __init__(self):
        self.messages = []
        self.closed_with = None

    async def send_text(self, message):
        self.messages.append(json.loads(message))

    async def close(self, code=1000):
        self.closed_with = code

    def events(self):
        return [m["event"] for m in self.messages]


class Gated(Healthy):
    """A client whose socket write blocks until the test opens the gate."""

    def __init__(self):
        super().__init__()
        self.gate = asyncio.Event()
        self.started = asyncio.Event()

    async def send_text(self, message):
        self.started.set()
        await self.gate.wait()
        await super().send_text(message)


class HalfOpen(Healthy):
    """A peer that vanished: writes never complete, and neither does close."""

    async def send_text(self, message):
        await asyncio.Event().wait()

    async def close(self, code=1000):
        self.closed_with = code
        await asyncio.Event().wait()


async def _settle(manager, *sockets):
    for socket in sockets:
        client = manager.client_for(socket)
        if client is not None:
            await asyncio.wait_for(client.wait_idle(), 2)


async def _hold(manager, socket):
    """Put one frame in flight so later frames queue behind the gate."""
    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    await socket.started.wait()


def _chain(run_id, status, **extra):
    return {"chain_run": {"id": run_id, "status": status, **extra}}


async def test_stalled_client_cannot_delay_a_healthy_client():
    manager = WebSocketManager()
    stalled, healthy = Gated(), Healthy()
    manager.attach(stalled)
    manager.attach(healthy)

    # Broadcasting never waits on a socket, even one that is stuck mid-write.
    for i in range(20):
        await asyncio.wait_for(
            manager.broadcast("media_added", {"media_id": i}, include_profile=False), 0.5
        )
    await _settle(manager, healthy)

    assert [m["data"]["media_id"] for m in healthy.messages] == list(range(20))
    assert stalled.started.is_set() and stalled.messages == []
    # The stalled client still has its own backlog, in order, waiting.
    assert manager.client_for(stalled).queued_frames == 19

    stalled.gate.set()
    await _settle(manager, stalled)
    assert [m["data"]["media_id"] for m in stalled.messages] == list(range(20))

    await manager.disconnect(stalled)
    await manager.disconnect(healthy)


async def test_broadcast_is_serialized_once_and_shared_by_every_queue():
    manager = WebSocketManager()
    a, b = Gated(), Gated()
    manager.attach(a)
    manager.attach(b)
    await manager.broadcast("media_added", {"media_id": 1}, include_profile=False)
    await manager.broadcast("media_added", {"media_id": 2}, include_profile=False)

    frame_a = manager.client_for(a).pending_frames()[0]
    frame_b = manager.client_for(b).pending_frames()[0]
    assert frame_a is frame_b

    a.gate.set()
    b.gate.set()
    await manager.drain()
    await manager.disconnect(a)
    await manager.disconnect(b)


async def test_durable_events_are_kept_past_the_soft_budget():
    manager = WebSocketManager(soft_max_frames=4, soft_max_bytes=512)
    slow = Gated()
    client = manager.attach(slow)
    await _hold(manager, slow)

    for i in range(1, 41):
        await manager.broadcast(
            "chat_item_updated", {"chat_id": 1, "n": i, "body": "x" * 50}, include_profile=False
        )
    # Far beyond the soft budget, still connected, nothing dropped.
    assert client.queued_frames == 40
    assert slow in manager.active_connections and not client.closed

    slow.gate.set()
    await _settle(manager, slow)
    assert [m["data"]["n"] for m in slow.messages[1:]] == list(range(1, 41))
    await manager.disconnect(slow)


async def test_hard_cap_disconnects_instead_of_dropping_durable_events():
    manager = WebSocketManager(hard_max_frames=8)
    stalled, healthy = Gated(), Healthy()
    stalled_client = manager.attach(stalled)
    manager.attach(healthy)

    observed_max = 0
    for i in range(50):
        await manager.broadcast("chat_item_created", {"chat_id": 1, "n": i}, include_profile=False)
        observed_max = max(observed_max, stalled_client.queued_frames)
    await manager.drain()

    # Bounded: never more than the hard cap.
    assert observed_max <= 8
    # The stalled client was cut off (as a network drop would) and released,
    # rather than kept connected with a gap in its durable events.
    assert stalled not in manager.active_connections
    assert stalled.closed_with == OVERFLOW_CLOSE_CODE
    assert stalled_client.closed
    assert stalled_client.queued_frames == 0 and stalled_client.queued_bytes == 0
    assert stalled_client.sender_task is None
    # A burst does not overflow a client that keeps up.
    assert [m["data"]["n"] for m in healthy.messages] == list(range(50))
    await manager.broadcast("chat_item_created", {"chat_id": 1, "n": 99}, include_profile=False)
    assert stalled_client.queued_frames == 0

    await manager.disconnect(healthy)


async def test_hard_byte_cap_bounds_the_queue():
    manager = WebSocketManager(hard_max_bytes=4096)
    stalled = Gated()
    client = manager.attach(stalled)
    payload = "x" * 1000
    for i in range(10):
        await manager.broadcast("chat_item_updated", {"n": i, "body": payload}, include_profile=False)
        assert client.queued_bytes <= 4096
    await manager.drain()
    assert stalled not in manager.active_connections
    assert stalled.closed_with == OVERFLOW_CLOSE_CODE


async def test_transient_frames_stay_within_the_soft_budget():
    manager = WebSocketManager(soft_max_frames=4)
    slow = Gated()
    client = manager.attach(slow)
    await _hold(manager, slow)
    for job in range(50):
        await manager.broadcast(
            "generation_job_progress", {"job_id": job, "progress": 0.5}, include_profile=False
        )
        assert client.queued_frames <= 4
    assert slow in manager.active_connections
    slow.gate.set()
    await manager.drain()
    await manager.disconnect(slow)


async def test_progress_frames_coalesce_latest_wins_and_durable_order_is_kept():
    manager = WebSocketManager()
    slow = Gated()
    client = manager.attach(slow)
    await _hold(manager, slow)

    await manager.broadcast("generation_job_started", {"job": {"id": 1}}, include_profile=False)
    for p in range(1, 11):
        await manager.broadcast(
            "generation_job_progress", {"job_id": 1, "progress": p / 10}, include_profile=False
        )
        await manager.broadcast(
            "generation_job_progress", {"job_id": 2, "progress": p / 100}, include_profile=False
        )
    await manager.broadcast("processing_stats", {"phase_stats": {"n": 1}}, include_profile=False)
    await manager.broadcast("processing_stats", {"phase_stats": {"n": 2}}, include_profile=False)
    await manager.broadcast("generation_job_completed", {"job": {"id": 1}}, include_profile=False)

    # One pending frame per job, not one per tick.
    assert client.queued_frames == 5
    assert client.coalesced == 18 + 1

    slow.gate.set()
    await _settle(manager, slow)
    assert slow.events() == [
        "media_added",
        "generation_job_started",
        "generation_job_progress",
        "generation_job_progress",
        "processing_stats",
        "generation_job_completed",
    ]
    progress = [m["data"] for m in slow.messages if m["event"] == "generation_job_progress"]
    assert progress == [{"job_id": 1, "progress": 1.0}, {"job_id": 2, "progress": 0.1}]
    assert slow.messages[4]["data"] == {"phase_stats": {"n": 2}}

    await manager.disconnect(slow)


async def test_numeric_tick_never_replaces_a_pending_preview_frame():
    manager = WebSocketManager()
    slow = Gated()
    manager.attach(slow)
    await _hold(manager, slow)

    await manager.broadcast(
        "generation_job_progress",
        {"job_id": 7, "progress": 0.2, "preview_b64": "AAAA"},
        include_profile=False,
    )
    await manager.broadcast(
        "generation_job_progress",
        {"job_id": 7, "progress": 0.3, "preview_b64": "BBBB"},
        include_profile=False,
    )
    await manager.broadcast("generation_job_progress", {"job_id": 7, "progress": 0.4}, include_profile=False)
    await manager.broadcast("generation_job_progress", {"job_id": 7, "progress": 0.5}, include_profile=False)

    slow.gate.set()
    await _settle(manager, slow)
    progress = [m["data"] for m in slow.messages[1:]]
    # The newest preview replaced the older preview; the newest tick replaced
    # the older tick; the frame the UI will paint is never discarded.
    assert progress == [
        {"job_id": 7, "progress": 0.3, "preview_b64": "BBBB"},
        {"job_id": 7, "progress": 0.5},
    ]
    await manager.disconnect(slow)


async def test_coalescing_never_merges_across_profiles():
    manager = WebSocketManager()
    slow = Gated()
    client = manager.attach(slow)
    await _hold(manager, slow)
    await manager.broadcast("generation_job_progress", {"job_id": 1, "progress": 0.1, "profile_id": "a"})
    await manager.broadcast("generation_job_progress", {"job_id": 1, "progress": 0.2, "profile_id": "b"})
    assert client.queued_frames == 2
    slow.gate.set()
    await manager.drain()
    await manager.disconnect(slow)


async def test_pressure_sheds_stale_progress_before_touching_durable_events():
    manager = WebSocketManager(soft_max_frames=6)
    slow = Gated()
    client = manager.attach(slow)
    await _hold(manager, slow)

    for job in range(4):
        await manager.broadcast(
            "generation_job_progress", {"job_id": job, "progress": 0.5}, include_profile=False
        )
    for i in range(1, 9):
        await manager.broadcast("media_added", {"media_id": i}, include_profile=False)
    assert client.shed == 4
    assert slow in manager.active_connections

    slow.gate.set()
    await _settle(manager, slow)
    durable = [m["data"]["media_id"] for m in slow.messages if m["event"] == "media_added"]
    assert durable == list(range(9))
    await manager.disconnect(slow)


async def test_terminal_chain_state_survives_pressure_and_coalescing():
    manager = WebSocketManager(soft_max_frames=3)
    slow = Gated()
    client = manager.attach(slow)
    await _hold(manager, slow)

    for step in range(5):
        await manager.broadcast(
            "postprocessing_chain_progress", _chain(1, "running", step=step), include_profile=False
        )
    await manager.broadcast(
        "postprocessing_chain_progress", _chain(1, "completed", final_media_id=9), include_profile=False
    )
    await manager.broadcast(
        "postprocessing_chain_progress", _chain(2, "paused", error="boom"), include_profile=False
    )
    # A later running frame must not replace the queued terminal ones, and
    # pressure from transient frames must never shed them.
    await manager.broadcast(
        "postprocessing_chain_progress", _chain(2, "running", step=1), include_profile=False
    )
    for job in range(20):
        await manager.broadcast(
            "generation_job_progress", {"job_id": job, "progress": 0.1}, include_profile=False
        )
    assert slow in manager.active_connections and not client.closed

    slow.gate.set()
    await _settle(manager, slow)
    runs = [m["data"]["chain_run"] for m in slow.messages if m["event"] == "postprocessing_chain_progress"]
    assert {"id": 1, "status": "completed", "final_media_id": 9} in runs
    assert {"id": 2, "status": "paused", "error": "boom"} in runs
    # The stale running snapshot of run 1 was superseded by its terminal one.
    assert [r["status"] for r in runs if r["id"] == 1] == ["completed"]
    await manager.disconnect(slow)


async def test_final_stats_and_delete_progress_are_coalesced_but_never_shed():
    manager = WebSocketManager(soft_max_frames=2)
    slow = Gated()
    manager.attach(slow)
    await _hold(manager, slow)

    await manager.broadcast("processing_stats", {"phase_stats": {"n": 1}}, include_profile=False)
    await manager.broadcast("delete_operation_progress", {"id": 5, "processed": 3}, include_profile=False)
    for job in range(10):
        await manager.broadcast(
            "generation_job_progress", {"job_id": job, "progress": 0.1}, include_profile=False
        )
    await manager.broadcast("processing_stats", {"phase_stats": {"n": 2}}, include_profile=False)

    slow.gate.set()
    await _settle(manager, slow)
    stats = [m["data"] for m in slow.messages if m["event"] == "processing_stats"]
    deletes = [m["data"] for m in slow.messages if m["event"] == "delete_operation_progress"]
    assert stats == [{"phase_stats": {"n": 2}}]
    assert deletes == [{"id": 5, "processed": 3}]
    await manager.disconnect(slow)


async def test_stalled_client_drop_uses_ordinary_disconnect_semantics():
    """A hard-cap or deadline drop is a network drop: the generator instance
    is released once, through the same cleanup as any other disconnect."""
    manager = WebSocketManager(hard_max_frames=4)
    abandoned = []

    async def on_generator_disconnect(generator_instance_id, **_):
        abandoned.append(generator_instance_id)

    manager.set_on_generator_disconnect(on_generator_disconnect)
    phone = Gated()
    manager.attach(phone)
    manager.register_generator_instance(phone, "gen-phone")

    for i in range(10):
        await manager.broadcast("media_added", {"media_id": i}, include_profile=False)
    await manager.drain()

    assert phone not in manager.active_connections
    assert phone.closed_with == OVERFLOW_CLOSE_CODE
    assert abandoned == ["gen-phone"]
    assert await manager.send_to_generator_instance("gen-phone", "generation_request_work", {}) is False


async def test_half_open_socket_is_closed_by_the_send_deadline(monkeypatch):
    import utils.websocket as websocket_module

    monkeypatch.setattr(websocket_module, "CLIENT_CLOSE_TIMEOUT_SECONDS", 0.05)
    manager = WebSocketManager(send_timeout=0.05)
    abandoned = []

    async def on_generator_disconnect(generator_instance_id, **_):
        abandoned.append(generator_instance_id)

    manager.set_on_generator_disconnect(on_generator_disconnect)
    dead, healthy = HalfOpen(), Healthy()
    dead_client = manager.attach(dead)
    manager.attach(healthy)
    manager.register_generator_instance(dead, "gen-dead")

    await manager.broadcast("media_added", {"media_id": 1}, include_profile=False)
    await asyncio.wait_for(manager.drain(), 5)

    assert dead not in manager.active_connections
    assert dead.closed_with == OVERFLOW_CLOSE_CODE
    assert dead_client.sender_task is None and dead_client.queued_frames == 0
    assert healthy.events() == ["media_added"]
    assert abandoned == ["gen-dead"]
    await manager.disconnect(healthy)


async def test_unwritten_direct_frames_report_undelivered_after_instance_cleanup():
    manager = WebSocketManager(send_timeout=0.05)
    order = []

    async def on_generator_disconnect(generator_instance_id, **_):
        order.append(("abandon", generator_instance_id))

    manager.set_on_generator_disconnect(on_generator_disconnect)
    dead = HalfOpen()
    manager.attach(dead)
    manager.register_generator_instance(dead, "gen")

    def undelivered(tag):
        async def callback():
            order.append(("undelivered", tag))
        return callback

    # The first request goes in flight and stalls; the second waits behind it.
    for tag in ("r1", "r2"):
        assert await manager.send_to_generator_instance(
            "gen", "generation_request_work", {"reservation_id": tag},
            on_undelivered=undelivered(tag),
        ) is True
    await asyncio.wait_for(manager.drain(), 5)

    assert order == [("abandon", "gen"), ("undelivered", "r1"), ("undelivered", "r2")]


async def test_request_stranded_on_superseded_socket_is_released():
    """The page re-registered its instance on a new socket; the old socket's
    unwritten request must still release its reservation, without abandoning
    the instance that now lives on the new socket."""
    manager = WebSocketManager()
    events = []

    async def on_generator_disconnect(generator_instance_id, **_):
        events.append(("abandon", generator_instance_id))

    async def released():
        events.append(("undelivered", "r1"))

    manager.set_on_generator_disconnect(on_generator_disconnect)
    old, new = Gated(), Healthy()
    manager.attach(old)
    await _hold(manager, old)
    manager.register_generator_instance(old, "gen")
    assert await manager.send_to_generator_instance(
        "gen", "generation_request_work", {"reservation_id": "r1"}, on_undelivered=released
    )
    manager.attach(new)
    manager.register_generator_instance(new, "gen")

    await manager.disconnect(old)
    assert events == [("undelivered", "r1")]
    await manager.disconnect(new)
    assert events == [("undelivered", "r1"), ("abandon", "gen")]


async def test_racing_disconnects_clean_up_exactly_once():
    """The endpoint's receive loop and a server-initiated drop can both call
    disconnect; the instance cleanup and undelivered release run once."""
    manager = WebSocketManager()
    calls = []

    async def on_generator_disconnect(generator_instance_id, **_):
        calls.append(("abandon", generator_instance_id))
        await asyncio.sleep(0)

    async def released():
        calls.append(("undelivered", "r1"))

    manager.set_on_generator_disconnect(on_generator_disconnect)
    socket = Gated()
    client = manager.attach(socket)
    await _hold(manager, socket)
    manager.register_generator_instance(socket, "gen")
    await manager.send_to_generator_instance(
        "gen", "generation_request_work", {"reservation_id": "r1"}, on_undelivered=released
    )

    # Server-initiated drop and the endpoint's cleanup, interleaved.
    manager._client_failed(client, "queue_overflow")
    await asyncio.gather(manager.disconnect(socket), manager.disconnect(socket))
    await manager.drain()

    assert calls == [("abandon", "gen"), ("undelivered", "r1")]
    assert manager.clients == []


async def test_disconnect_teardown_survives_cancellation_during_generator_cleanup():
    """Cancelling the caller mid-cleanup must not orphan the sender or skip
    the undelivered release; the cancellation still reaches the caller."""
    manager = WebSocketManager()
    gate = asyncio.Event()
    calls = []

    async def on_generator_disconnect(generator_instance_id, **_):
        calls.append("abandon-start")
        await gate.wait()  # e.g. cancelling jobs in the database
        calls.append("abandon-done")

    async def released():
        calls.append("undelivered")

    manager.set_on_generator_disconnect(on_generator_disconnect)
    socket = Gated()
    client = manager.attach(socket)
    await _hold(manager, socket)
    sender = client.sender_task
    manager.register_generator_instance(socket, "gen")
    await manager.send_to_generator_instance(
        "gen", "generation_request_work", {"reservation_id": "r1"}, on_undelivered=released
    )

    caller = asyncio.create_task(manager.disconnect(socket))
    while calls != ["abandon-start"]:
        await asyncio.sleep(0)
    caller.cancel()
    try:
        await caller
        raise AssertionError("the caller's cancellation must be re-raised")
    except asyncio.CancelledError:
        pass

    gate.set()
    await asyncio.wait_for(manager.drain(), 2)
    assert calls == ["abandon-start", "abandon-done", "undelivered"]
    assert sender.done() and client.sender_task is None
    assert client.queued_frames == 0 and client.queued_bytes == 0


async def test_already_cancelled_endpoint_still_tears_down_in_finally():
    """The endpoint's receive loop is cancelled (server shutdown, transport
    torn down) and calls disconnect from its finally block."""
    manager = WebSocketManager()
    calls = []

    async def released():
        calls.append("undelivered")

    old, new = Gated(), Healthy()
    client = manager.attach(old)
    await _hold(manager, old)
    sender = client.sender_task
    manager.register_generator_instance(old, "gen")
    await manager.send_to_generator_instance(
        "gen", "generation_request_work", {"reservation_id": "r1"}, on_undelivered=released
    )
    # The page already re-registered on a new socket: the request is
    # stranded on the old one and must still be released.
    manager.attach(new)
    manager.register_generator_instance(new, "gen")

    async def endpoint():
        try:
            await asyncio.Event().wait()
        finally:
            await manager.disconnect(old)

    task = asyncio.create_task(endpoint())
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    await asyncio.wait_for(manager.drain(), 2)
    assert calls == ["undelivered"]
    assert sender.done() and client.sender_task is None
    assert client.queued_frames == 0
    assert old not in manager.active_connections
    await manager.disconnect(new)


async def test_enqueue_cost_is_bounded_with_a_large_durable_backlog():
    """Past the soft budget with nothing sheddable, each durable enqueue must
    not rescan the backlog (that was quadratic: ~15 s for 50k frames)."""
    manager = WebSocketManager(soft_max_frames=16, hard_max_frames=100_000)
    stalled = Gated()
    client = manager.attach(stalled)
    await _hold(manager, stalled)

    loop = asyncio.get_running_loop()
    started = loop.time()
    for i in range(50_000):
        client.enqueue(manager_frame(i))
    elapsed = loop.time() - started

    assert client.queued_frames == 50_000
    assert elapsed < 2.0, elapsed
    await manager.disconnect(stalled)


async def test_coalescing_on_a_stalled_client_keeps_the_queue_bounded():
    """Replaced frames leave tombstones; they must not accumulate without bound."""
    manager = WebSocketManager()
    stalled = Gated()
    client = manager.attach(stalled)
    await _hold(manager, stalled)

    for i in range(20_000):
        await manager.broadcast(
            "generation_job_progress", {"job_id": i % 3, "progress": i}, include_profile=False
        )
    assert client.queued_frames == 3
    assert len(client._queue) <= 2 * client.queued_frames + 65

    # Shedding is O(1) per frame too: a long run of distinct jobs past the
    # soft budget stays fast and bounded.
    for i in range(20_000):
        await manager.broadcast(
            "generation_job_progress", {"job_id": 100 + i, "progress": 0.1}, include_profile=False
        )
    assert client.queued_frames <= client.soft_max_frames
    assert len(client._queue) <= 2 * client.queued_frames + 65
    await manager.disconnect(stalled)


async def test_tombstones_retain_no_payload():
    """Replaced or shed frames must be released at once, not held by their
    tombstones until compaction: bytes retained must match bytes accounted."""
    import gc
    import weakref

    from utils.websocket import OutboundFrame, _delivery_policy

    manager = WebSocketManager(soft_max_bytes=1024 * 1024)
    stalled = Gated()
    client = manager.attach(stalled)
    await _hold(manager, stalled)
    # A durable backlog keeps the live count high, so count-based compaction
    # would never run for these tombstones.
    for i in range(100):
        client.enqueue(manager_frame(i))

    refs = []
    preview = "P" * 100_000
    for i in range(60):
        data = {"job_id": 1, "progress": i, "preview_b64": preview}
        frame = OutboundFrame(
            event="generation_job_progress",
            text=json.dumps({"event": "generation_job_progress", "data": data}) + str(i),
            delivery=_delivery_policy("generation_job_progress", data),
        )
        refs.append(weakref.ref(frame))
        client.enqueue(frame)
        del frame
    gc.collect()

    alive = [ref for ref in refs if ref() is not None]
    assert len(alive) == 1  # only the newest preview is still queued
    assert client.queued_bytes < 200_000
    await manager.disconnect(stalled)


async def test_re_registration_during_cleanup_keeps_the_new_session():
    """The page re-registers its generator instance on a new socket while the
    old socket's cleanup is still running; the cleanup must see that it no
    longer owns the instance, and the new mapping must survive."""
    manager = WebSocketManager()
    gate = asyncio.Event()
    observed = []

    async def on_generator_disconnect(generator_instance_id, *, still_abandoned):
        observed.append(still_abandoned())
        await gate.wait()  # e.g. cancelling jobs in the database
        observed.append(still_abandoned())

    manager.set_on_generator_disconnect(on_generator_disconnect)
    old, new = Gated(), Healthy()
    manager.attach(old)
    await _hold(manager, old)
    manager.register_generator_instance(old, "gen")

    cleanup = asyncio.create_task(manager.disconnect(old))
    while not observed:  # the old socket's cleanup is under way
        await asyncio.sleep(0)
    manager.attach(new)
    manager.register_generator_instance(new, "gen")
    gate.set()
    await cleanup

    assert observed == [True, False]
    assert await manager.send_to_generator_instance("gen", "generation_request_work", {}) is True
    await manager.drain()
    assert new.events() == ["generation_request_work"]
    await manager.disconnect(new)


def manager_frame(i):
    from utils.websocket import OutboundFrame

    return OutboundFrame(event="media_added", text=json.dumps({"event": "media_added", "data": {"n": i}}))


async def test_disconnect_cancels_sender_and_releases_queue():
    manager = WebSocketManager()
    stalled = Gated()
    client = manager.attach(stalled)
    for i in range(5):
        await manager.broadcast("media_added", {"media_id": i}, include_profile=False)
    await stalled.started.wait()
    task = client.sender_task
    assert task is not None and not task.done()

    await manager.disconnect(stalled)

    assert task.done()
    assert client.sender_task is None
    assert client.queued_frames == 0 and client.queued_bytes == 0
    assert manager.clients == []
    # Disconnect is idempotent (the endpoint's finally may repeat it).
    await manager.disconnect(stalled)


async def test_direct_replies_share_the_client_queue_in_order():
    manager = WebSocketManager()
    slow = Gated()
    manager.attach(slow)
    await manager.broadcast("media_added", {"media_id": 1}, include_profile=False)
    await manager.send_to(slow, "pong", {"timestamp": "t"})
    await manager.broadcast("media_added", {"media_id": 2}, include_profile=False)
    slow.gate.set()
    await _settle(manager, slow)
    assert slow.events() == ["media_added", "pong", "media_added"]
    await manager.disconnect(slow)


def test_realtime_endpoint_delivers_through_the_queue(monkeypatch):
    """The real /ws route: welcome, ping/pong and broadcasts reach two clients."""
    import routes.realtime as realtime

    manager = WebSocketManager()
    monkeypatch.setattr(realtime, "ws_manager", manager)
    app = FastAPI()
    app.include_router(realtime.router)

    with TestClient(app) as test_client:
        with test_client.websocket_connect("/ws") as one, test_client.websocket_connect("/ws") as two:
            assert one.receive_json()["event"] == "connected"
            assert two.receive_json()["event"] == "connected"
            one.send_json({"event": "ping", "data": {}})
            assert one.receive_json()["event"] == "pong"

            test_client.portal.call(
                manager.broadcast, "media_added", {"media_id": 5}, False
            )
            assert one.receive_json() == {"event": "media_added", "data": {"media_id": 5}}
            assert two.receive_json() == {"event": "media_added", "data": {"media_id": 5}}
            assert len(manager.clients) == 2
        for _ in range(100):
            if not manager.clients:
                break
            test_client.portal.call(asyncio.sleep, 0.01)
        assert manager.clients == []

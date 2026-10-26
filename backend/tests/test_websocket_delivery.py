"""Per-client WebSocket delivery: isolation, bounds, coalescing and cleanup.

Every connected client has its own bounded outbound queue and sender task. A
slow or half-open client (a phone on a weak cellular link) must not delay any
other client, must not grow memory without bound, and must not silently lose
durable state-change events: it is disconnected instead, and the UI resyncs on
reconnect.
"""
import asyncio
import json

import pytest
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

    frame_a = manager.client_for(a)._queue[0]
    frame_b = manager.client_for(b)._queue[0]
    assert frame_a is frame_b

    a.gate.set()
    b.gate.set()
    await manager.drain()
    await manager.disconnect(a)
    await manager.disconnect(b)


async def test_overflowing_client_is_disconnected_not_silently_truncated():
    manager = WebSocketManager(max_frames=8)
    stalled, healthy = Gated(), Healthy()
    stalled_client = manager.attach(stalled)
    manager.attach(healthy)

    observed_max = 0
    for i in range(50):
        await manager.broadcast("chat_item_created", {"chat_id": 1, "n": i}, include_profile=False)
        observed_max = max(observed_max, stalled_client.queued_frames)
    await manager.drain()

    # Bounded: never more than the configured backlog.
    assert observed_max <= 8
    # Durable events were not dropped while the client stayed connected: the
    # client was cut off (so it reconnects and resyncs) and fully released.
    assert stalled not in manager.active_connections
    assert stalled.closed_with == OVERFLOW_CLOSE_CODE
    assert stalled_client.closed
    assert stalled_client.queued_frames == 0 and stalled_client.queued_bytes == 0
    assert stalled_client.sender_task is None
    # The healthy client saw everything.
    assert [m["data"]["n"] for m in healthy.messages] == list(range(50))
    # Nothing more is queued for the dropped socket.
    await manager.broadcast("chat_item_created", {"chat_id": 1, "n": 99}, include_profile=False)
    assert stalled_client.queued_frames == 0

    await manager.disconnect(healthy)


async def test_byte_budget_bounds_the_queue():
    manager = WebSocketManager(max_bytes=4096)
    stalled = Gated()
    client = manager.attach(stalled)
    payload = "x" * 1000
    for i in range(10):
        await manager.broadcast("chat_item_updated", {"n": i, "body": payload}, include_profile=False)
        assert client.queued_bytes <= 4096
    await manager.drain()
    assert stalled not in manager.active_connections
    assert stalled.closed_with == OVERFLOW_CLOSE_CODE


async def test_progress_frames_coalesce_latest_wins_and_durable_order_is_kept():
    manager = WebSocketManager()
    slow = Gated()
    client = manager.attach(slow)

    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    await slow.started.wait()  # media_added 0 is in flight; the rest queue up
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

    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    await slow.started.wait()
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
    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    await slow.started.wait()
    await manager.broadcast("generation_job_progress", {"job_id": 1, "progress": 0.1, "profile_id": "a"})
    await manager.broadcast("generation_job_progress", {"job_id": 1, "progress": 0.2, "profile_id": "b"})
    assert client.queued_frames == 2
    slow.gate.set()
    await manager.drain()
    await manager.disconnect(slow)


async def test_pressure_sheds_stale_progress_before_touching_durable_events():
    manager = WebSocketManager(max_frames=6)
    slow = Gated()
    client = manager.attach(slow)

    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    await slow.started.wait()
    for job in range(4):
        await manager.broadcast(
            "generation_job_progress", {"job_id": job, "progress": 0.5}, include_profile=False
        )
    for i in range(1, 5):
        await manager.broadcast("media_added", {"media_id": i}, include_profile=False)
    assert client.queued_frames <= 6
    assert client.shed >= 1
    assert slow in manager.active_connections

    slow.gate.set()
    await _settle(manager, slow)
    durable = [m["data"]["media_id"] for m in slow.messages if m["event"] == "media_added"]
    assert durable == [0, 1, 2, 3, 4]
    await manager.disconnect(slow)


async def test_half_open_socket_is_closed_by_the_send_deadline():
    manager = WebSocketManager(send_timeout=0.05)
    released = []

    async def on_generator_disconnect(generator_instance_id):
        released.append(generator_instance_id)

    manager.set_on_generator_disconnect(on_generator_disconnect)
    dead, healthy = HalfOpen(), Healthy()
    dead_client = manager.attach(dead)
    manager.attach(healthy)
    manager.register_generator_instance(dead, "gen-dead")

    await manager.broadcast("media_added", {"media_id": 1}, include_profile=False)
    # Closing a half-open peer may itself hang; the drop is bounded too.
    await asyncio.wait_for(manager.drain(), 5)

    assert dead not in manager.active_connections
    assert dead.closed_with == OVERFLOW_CLOSE_CODE
    assert dead_client.sender_task is None and dead_client.queued_frames == 0
    assert released == ["gen-dead"]
    assert await manager.send_to_generator_instance("gen-dead", "generation_request_work", {}) is False
    assert healthy.events() == ["media_added"]
    await manager.disconnect(healthy)


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

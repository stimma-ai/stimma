"""Realtime scopes: profile filtering, entity subscriptions and preview policy.

A client that declares the realtime capability gets only its own profile's
events, full detail only for the chats and generator instances it follows,
small job summaries for the rest, and preview images only as its own policy
allows. A client that never declares it (an older UI package) must receive
exactly the stream it received before scopes existed.
"""
import asyncio
import json

from fastapi import FastAPI
from starlette.testclient import TestClient

from utils.websocket import RealtimeScope, WebSocketManager


class Socket:
    def __init__(self):
        self.messages = []

    async def send_text(self, message):
        self.messages.append(json.loads(message))

    async def close(self, code=1000):
        pass

    def events(self):
        return [m["event"] for m in self.messages]

    def of(self, event):
        return [m["data"] for m in self.messages if m["event"] == event]

    def raw_bytes(self):
        return sum(len(json.dumps(m)) for m in self.messages)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def scoped(profile_id, *topics, clock=None, **previews):
    scope = RealtimeScope(clock=clock) if clock else RealtimeScope()
    payload = {"profile_id": profile_id, "topics": list(topics)}
    if previews:
        payload["previews"] = previews
    scope.update("scope", payload)
    return scope


DESKTOP_GENERATOR = "tool-test:text-to-image@@desktop-guid"
PHONE_GENERATOR = "tool-test:text-to-image@@phone-guid"


def job(job_id, status, profile="A", generator=DESKTOP_GENERATOR):
    return {
        "id": job_id,
        "status": status,
        "task_type": "text-to-image",
        "tool_id": "test:text-to-image",
        "generator_instance_id": generator,
        "profile_id": profile,
        "parameters": json.dumps({"prompt": "a long prompt " * 40, "seed": job_id}),
        "folder_path": "/managed/staging/area",
        "result_media_id": 100 + job_id if status == "completed" else None,
        "error": None,
        "batch_id": None,
    }


async def generate(manager, job_id, *, profile="A", generator=DESKTOP_GENERATOR, preview=b"x" * 3000, ticks=4):
    """One job's worth of broadcasts, shaped like the generation queue's."""
    base = {"generator_instance_id": generator, "profile_id": profile}
    await manager.broadcast("generation_job_queued", {"job": job(job_id, "queued", profile, generator), **base})
    await manager.broadcast("generation_job_started", {"job": job(job_id, "processing", profile, generator), **base})
    for tick in range(ticks):
        payload = {"job_id": job_id, "progress": (tick + 1) / ticks, "stage": "sampling", **base}
        if preview is not None:
            import base64
            payload["preview_b64"] = base64.b64encode(preview).decode()
            payload["preview_mime"] = "image/jpeg"
        await manager.broadcast("generation_job_progress", payload)
        await manager.drain()
    await manager.broadcast("generation_job_completed", {"job": job(job_id, "completed", profile, generator), **base})
    await manager.broadcast("media_added", {"media_id": 100 + job_id, "profile_id": profile})
    await manager.broadcast("processing_stats", {"phase_stats": {}}, include_profile=False)
    await manager.drain()


async def chat_turn(manager, chat_id, profile="A"):
    await manager.broadcast("agent_started", {"chat_id": chat_id, "profile_id": profile})
    for i in range(3):
        await manager.broadcast("chat_item_created", {
            "chat_id": chat_id, "profile_id": profile,
            "item": {"id": chat_id * 100 + i, "message_text": "streamed answer " * 30},
        })
        await manager.broadcast("chat_item_updated", {
            "chat_id": chat_id, "profile_id": profile,
            "item": {"id": chat_id * 100 + i, "message_text": "streamed answer, more " * 30},
        })
    await manager.broadcast("llm_usage", {"chat_id": chat_id, "profile_id": profile, "total_tokens": 10})
    await manager.broadcast("agent_stopped", {"chat_id": chat_id, "profile_id": profile, "reason": "completed"})
    await manager.broadcast("chat_updated", {"chat_id": chat_id, "profile_id": profile, "chat": {"id": chat_id}})
    await manager.drain()


async def workload(manager):
    await generate(manager, 1)
    await generate(manager, 2, profile="B", generator="tool-other@@b-guid")
    await chat_turn(manager, 7)
    await chat_turn(manager, 8)
    await chat_turn(manager, 7, profile="B")


async def test_legacy_client_receives_the_unchanged_stream():
    """With scoped clients alongside, a legacy client's stream is byte-for-byte
    what it would be on a server with no scoped clients at all."""
    reference_manager = WebSocketManager()
    reference = Socket()
    reference_manager.attach(reference)
    await workload(reference_manager)

    manager = WebSocketManager()
    legacy, phone, desktop = Socket(), Socket(), Socket()
    manager.attach(legacy)
    manager.attach(phone, scoped("A", max_fps=1))
    manager.attach(desktop, scoped("A", f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}", "chat:7"))
    await workload(manager)

    assert legacy.messages == reference.messages
    # Including other profiles' events and every preview image.
    assert {m["data"].get("profile_id") for m in legacy.messages} >= {"A", "B"}
    assert all("preview_b64" in p for p in legacy.of("generation_job_progress"))


async def test_idle_phone_gets_summaries_but_no_previews_or_foreign_chat_detail():
    manager = WebSocketManager()
    phone, desktop = Socket(), Socket()
    manager.attach(phone, scoped("A"))
    manager.attach(desktop, scoped("A", f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}"))
    await workload(manager)

    # No progress ticks, previews or chat detail for things it is not viewing.
    assert phone.of("generation_job_progress") == []
    for event in ("chat_item_created", "chat_item_updated", "llm_usage"):
        assert phone.of(event) == []
    # Remote work is still visible: every lifecycle event arrives, as a summary.
    lifecycle = [m for m in phone.messages if m["event"].startswith("generation_job_")]
    assert [m["event"] for m in lifecycle] == [
        "generation_job_queued", "generation_job_started", "generation_job_completed",
    ]
    for message in lifecycle:
        data = message["data"]
        assert data["detail"] == "summary"
        assert "parameters" not in data["job"] and "folder_path" not in data["job"]
        assert set(data["job"]) == {
            "id", "status", "task_type", "tool_id", "generator_instance_id", "profile_id",
            "batch_id", "result_media_id", "error",
        }
        assert data["job"]["id"] == 1 and data["job"]["generator_instance_id"] == DESKTOP_GENERATOR
    assert lifecycle[-1]["data"]["job"]["result_media_id"] == 101
    # Activity summaries and global events still arrive.
    assert len(phone.of("agent_started")) == 2 and len(phone.of("agent_stopped")) == 2
    assert len(phone.of("chat_updated")) == 2
    assert phone.of("media_added") == [{"media_id": 101, "profile_id": "A"}]
    assert len(phone.of("processing_stats")) == 2

    # The generating client keeps full detail and every preview.
    progress = desktop.of("generation_job_progress")
    assert len(progress) == 4 and all("preview_b64" in p for p in progress)
    full = desktop.of("generation_job_queued")[0]
    assert "detail" not in full and "parameters" in full["job"]


async def test_other_profiles_events_never_reach_a_scoped_client():
    manager = WebSocketManager()
    phone = Socket()
    # Even following everything, a client in profile A sees nothing of B.
    manager.attach(phone, scoped("A", "generation", "previews", "chat:7", "chat:8"))
    await workload(manager)
    profiles = {m["data"].get("profile_id") for m in phone.messages}
    assert profiles == {"A", None}
    assert phone.of("processing_stats"), "global events still arrive"
    assert not [m for m in phone.messages if m["data"].get("job", {}).get("id") == 2]


async def test_subscribed_chat_gets_full_detail_only_for_that_chat():
    manager = WebSocketManager()
    viewer = Socket()
    manager.attach(viewer, scoped("A", "chat:7"))
    await workload(manager)
    created = viewer.of("chat_item_created")
    assert [c["chat_id"] for c in created] == [7, 7, 7]
    assert len(viewer.of("chat_item_updated")) == 3
    assert [u["chat_id"] for u in viewer.of("llm_usage")] == [7]
    assert created[0]["item"]["message_text"].startswith("streamed answer")


async def test_subscribe_and_unsubscribe_take_effect_for_later_broadcasts():
    manager = WebSocketManager()
    socket = Socket()
    manager.attach(socket, scoped("A"))
    item = {"chat_id": 7, "profile_id": "A", "item": {"id": 1}}
    await manager.broadcast("chat_item_created", item)
    assert manager.update_scope(socket, "subscribe", {"topics": ["chat:7"]})["topics"] == ["chat:7"]
    await manager.broadcast("chat_item_created", {**item, "item": {"id": 2}})
    manager.update_scope(socket, "unsubscribe", {"topics": ["chat:7"]})
    await manager.broadcast("chat_item_created", {**item, "item": {"id": 3}})
    await manager.drain()
    assert [c["item"]["id"] for c in socket.of("chat_item_created")] == [2]


async def test_a_scope_message_opts_a_legacy_connection_in():
    manager = WebSocketManager()
    socket = Socket()
    manager.attach(socket)
    await manager.broadcast("media_added", {"media_id": 1, "profile_id": "B"})
    manager.update_scope(socket, "scope", {"profile_id": "A"})
    await manager.broadcast("media_added", {"media_id": 2, "profile_id": "B"})
    await manager.broadcast("media_added", {"media_id": 3, "profile_id": "A"})
    await manager.drain()
    assert [m["media_id"] for m in socket.of("media_added")] == [1, 3]


async def test_invalid_scope_messages_are_rejected_and_change_nothing():
    manager = WebSocketManager()
    socket = Socket()
    manager.attach(socket, scoped("A", "chat:1"))
    before = manager.client_for(socket).scope.describe()
    for kind, payload in [
        ("scope", {"topics": "chat:1"}),
        ("scope", {"topics": ["chat:2"], "previews": {"max_fps": -1}}),
        ("scope", {"profile_id": 5}),
        ("subscribe", {"topics": [""]}),
        ("subscribe", {"topics": [f"chat:{i}" for i in range(300)]}),
        ("scope", "nope"),
    ]:
        try:
            manager.update_scope(socket, kind, payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {kind} {payload!r}")
    assert manager.client_for(socket).scope.describe() == before


async def test_per_client_preview_cadence_does_not_affect_other_clients():
    clock = Clock()
    manager = WebSocketManager()
    phone, desktop, legacy = Socket(), Socket(), Socket()
    topics = (f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}")
    manager.attach(phone, scoped("A", *topics, clock=clock, max_fps=1))
    manager.attach(desktop, scoped("A", *topics, clock=clock))
    manager.attach(legacy)

    import base64
    frame = base64.b64encode(b"p" * 2000).decode()
    for step in range(7):  # a preview every 0.4 s
        clock.now = 1000.0 + step * 0.4
        await manager.broadcast("generation_job_progress", {
            "job_id": 1, "generator_instance_id": DESKTOP_GENERATOR, "profile_id": "A",
            "progress": step / 6, "preview_b64": frame, "preview_mime": "image/jpeg",
        })
        await manager.drain()

    def previews(socket):
        return ["preview_b64" in p for p in socket.of("generation_job_progress")]

    # At most one image per second: 0.0, 1.2 and 2.4 s carry it; the rest
    # arrive as numeric ticks.
    assert previews(phone) == [True, False, False, True, False, False, True]
    assert previews(desktop) == [True] * 7
    assert previews(legacy) == [True] * 7
    # The image-less variant is built once per broadcast and shared.
    assert all("preview_mime" not in p for p in phone.of("generation_job_progress") if "preview_b64" not in p)


def _progress(job_id, size, generator=DESKTOP_GENERATOR):
    import base64
    return {
        "job_id": job_id, "generator_instance_id": generator, "profile_id": "A",
        "progress": 0.5, "preview_b64": base64.b64encode(b"z" * size).decode(),
    }


async def test_preview_budget_is_per_client_across_concurrent_jobs():
    """Several jobs streaming at once must not multiply a client's budget."""
    clock = Clock()
    manager = WebSocketManager()
    phone, desktop = Socket(), Socket()
    topics = (f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}")
    manager.attach(phone, scoped("A", *topics, clock=clock, max_fps=1))
    manager.attach(desktop, scoped("A", *topics, clock=clock))
    # Three jobs, each sending a frame every 0.3 s, for 3 s.
    for step in range(10):
        clock.now = 1000.0 + step * 0.3
        for job_id in (1, 2, 3):
            await manager.broadcast("generation_job_progress", _progress(job_id, 1500))
            await manager.drain()
    images = [p["job_id"] for p in phone.of("generation_job_progress") if "preview_b64" in p]
    # At most one image per second for the whole socket (t = 0, 1.2, 2.4).
    assert len(images) == 3
    assert len([p for p in desktop.of("generation_job_progress") if "preview_b64" in p]) == 30
    # Every tick still reports progress.
    assert len(phone.of("generation_job_progress")) == 30


async def test_preview_byte_rate_is_per_client():
    clock = Clock()
    manager = WebSocketManager()
    phone = Socket()
    manager.attach(phone, scoped(
        "A", f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}",
        clock=clock, max_bytes_per_second=10_000,
    ))
    sent_bytes = 0
    for step in range(40):  # 4 s, two jobs, ~4 KB base64 frames every 0.1 s
        clock.now = 1000.0 + step * 0.1
        for job_id in (1, 2):
            await manager.broadcast("generation_job_progress", _progress(job_id, 3000))
            await manager.drain()
    for p in phone.of("generation_job_progress"):
        if "preview_b64" in p:
            sent_bytes += len(p["preview_b64"])
    # One second of burst plus the steady rate over the window.
    assert 0 < sent_bytes <= 10_000 + 4 * 10_000


async def test_slow_budgeted_client_holds_only_the_latest_preview():
    """Delayed delivery must not burst queued images, whichever job sent them."""
    clock = Clock()
    manager = WebSocketManager()

    class Held(Socket):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()

        async def send_text(self, message):
            await self.gate.wait()
            await super().send_text(message)

    phone = Held()
    manager.attach(phone, scoped(
        "A", f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}",
        clock=clock, max_fps=1,
    ))
    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    for step in range(6):  # admitted at 0, 1, 2, 3, 4, 5 s, alternating jobs
        clock.now = 1000.0 + step
        await manager.broadcast("generation_job_progress", _progress(1 + step % 2, 1000))
    pending = [f for f in manager.client_for(phone).pending_frames() if f.preview_bytes]
    assert len(pending) == 1 and '"job_id": 2' in pending[0].text
    phone.gate.set()
    await manager.drain()
    assert len([p for p in phone.of("generation_job_progress") if "preview_b64" in p]) == 1


async def test_preview_size_cap_and_offscreen_previews():
    manager = WebSocketManager()
    capped, hidden, offscreen = Socket(), Socket(), Socket()
    topics = (f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}")
    manager.attach(capped, scoped("A", *topics, max_bytes=1000))
    manager.attach(hidden, scoped("A", *topics, enabled=False))
    # Follows the job feed while its view is cached, but not the images.
    manager.attach(offscreen, scoped("A", f"generator:{DESKTOP_GENERATOR}"))
    import base64
    for size in (300, 3000):
        await manager.broadcast("generation_job_progress", {
            "job_id": 1, "generator_instance_id": DESKTOP_GENERATOR, "profile_id": "A",
            "progress": 0.5, "preview_b64": base64.b64encode(b"q" * size).decode(),
        })
    await manager.drain()
    assert ["preview_b64" in p for p in capped.of("generation_job_progress")] == [True, False]
    assert ["preview_b64" in p for p in hidden.of("generation_job_progress")] == [False, False]
    assert ["preview_b64" in p for p in offscreen.of("generation_job_progress")] == [False, False]

    # Turning previews back on applies to later frames only, for this client only.
    manager.update_scope(hidden, "scope", {"previews": {"enabled": True}})
    await manager.broadcast("generation_job_progress", {
        "job_id": 1, "generator_instance_id": DESKTOP_GENERATOR, "profile_id": "A",
        "progress": 0.9, "preview_b64": base64.b64encode(b"r" * 300).decode(),
    })
    await manager.drain()
    assert "preview_b64" in hidden.of("generation_job_progress")[-1]
    assert "preview_b64" not in offscreen.of("generation_job_progress")[-1]


async def test_variants_are_serialized_once_and_shared():
    manager = WebSocketManager()

    class Held(Socket):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()

        async def send_text(self, message):
            await self.gate.wait()
            await super().send_text(message)

    phones = [Held(), Held(), Held()]
    for phone in phones:
        manager.attach(phone, scoped("A"))
    await manager.broadcast("media_added", {"media_id": 0}, include_profile=False)
    await manager.broadcast("generation_job_queued", {
        "job": job(1, "queued"), "generator_instance_id": DESKTOP_GENERATOR, "profile_id": "A",
    })
    summaries = [manager.client_for(p).pending_frames()[-1] for p in phones]
    assert summaries[0] is summaries[1] is summaries[2]
    assert '"detail": "summary"' in summaries[0].text
    for phone in phones:
        phone.gate.set()
    await manager.drain()


async def test_idle_phone_traffic_during_another_clients_generation():
    """Before/after for one idle phone while another client generates.

    Ten jobs (the baseline shape: lifecycle, ticks with previews, media and
    stats). Printed so the numbers can be read from a ``-s`` run.
    """
    manager = WebSocketManager()
    legacy_phone, scoped_phone, desktop = Socket(), Socket(), Socket()
    manager.attach(legacy_phone)
    manager.attach(scoped_phone, scoped("A"))
    manager.attach(desktop, scoped("A", f"generator:{DESKTOP_GENERATOR}", f"previews:{DESKTOP_GENERATOR}"))
    for job_id in range(10):
        await generate(manager, job_id, preview=b"j" * 24_000)
    before = (len(legacy_phone.messages), legacy_phone.raw_bytes())
    after = (len(scoped_phone.messages), scoped_phone.raw_bytes())
    print(f"\nidle phone, 10 jobs: legacy {before[0]} frames / {before[1]} B; scoped {after[0]} frames / {after[1]} B")
    assert after[0] < before[0] and after[1] < before[1] / 10
    assert len(desktop.of("generation_job_progress")) == 40


def test_endpoint_negotiates_scope_and_restores_it_on_reconnect(monkeypatch):
    """The real /ws route: connect-time scope, acks, and reconnect restoration."""
    import routes.realtime as realtime

    manager = WebSocketManager()
    monkeypatch.setattr(realtime, "ws_manager", manager)
    app = FastAPI()
    app.include_router(realtime.router)

    def broadcast(event, data):
        test_client.portal.call(manager.broadcast, event, data, False)

    url = "/ws?realtime=1&profile=A&topic=chat:7&preview_fps=2&previews=1"
    with TestClient(app) as test_client:
        for attempt in range(2):  # the second connection is a reconnect
            with test_client.websocket_connect(url) as phone, test_client.websocket_connect("/ws") as legacy:
                welcome = phone.receive_json()
                assert welcome["event"] == "connected"
                assert welcome["data"]["realtime_protocol"] == 1
                assert welcome["data"]["realtime"]["profile_id"] == "A"
                assert welcome["data"]["realtime"]["topics"] == ["chat:7"]
                assert welcome["data"]["realtime"]["previews"]["max_fps"] == 2.0
                legacy_welcome = legacy.receive_json()
                assert "realtime" not in legacy_welcome["data"]

                # Restored before the first broadcast: chat 7 detail arrives,
                # chat 8 detail and profile B do not.
                broadcast("chat_item_created", {"chat_id": 8, "profile_id": "A", "item": {"id": 1}})
                broadcast("media_added", {"media_id": 1, "profile_id": "B"})
                broadcast("chat_item_created", {"chat_id": 7, "profile_id": "A", "item": {"id": 2}})
                assert phone.receive_json()["data"]["item"]["id"] == 2
                assert [legacy.receive_json()["event"] for _ in range(3)] == [
                    "chat_item_created", "media_added", "chat_item_created",
                ]

                # Subscribing is acknowledged after everything broadcast before it.
                broadcast("media_added", {"media_id": 2, "profile_id": "A"})
                phone.send_json({"event": "realtime_subscribe", "data": {"topics": ["chat:8"], "seq": 3}})
                assert phone.receive_json()["event"] == "media_added"
                ack = phone.receive_json()
                assert ack == {"event": "realtime_scope_applied", "data": {
                    "seq": 3, "protocol": 1, "profile_id": "A", "topics": ["chat:7", "chat:8"],
                    "previews": {"enabled": True, "max_fps": 2.0, "max_bytes": None,
                                 "max_bytes_per_second": None},
                }}
                broadcast("chat_item_created", {"chat_id": 8, "profile_id": "A", "item": {"id": 3}})
                assert phone.receive_json()["data"]["item"]["id"] == 3

                # A full scope replaces topics and profile in one step.
                phone.send_json({"event": "realtime_scope", "data": {"profile_id": "B", "topics": [], "seq": 4}})
                assert phone.receive_json()["data"]["topics"] == []
                phone.send_json({"event": "realtime_unsubscribe", "data": {"topics": 7, "seq": 5}})
                rejected = phone.receive_json()
                assert rejected["event"] == "realtime_scope_rejected" and rejected["data"]["seq"] == 5
                broadcast("media_added", {"media_id": 3, "profile_id": "A"})
                broadcast("media_added", {"media_id": 4, "profile_id": "B"})
                assert phone.receive_json()["data"]["media_id"] == 4
                legacy.receive_json(), legacy.receive_json(), legacy.receive_json()
            # Server-side scope lives with the connection; the reconnect
            # above starts again from what the client sends.
            for _ in range(100):
                if not manager.clients:
                    break
                test_client.portal.call(asyncio.sleep, 0.01)
            assert manager.clients == []


def test_invalid_connect_scope_falls_back_to_the_legacy_stream(monkeypatch):
    import routes.realtime as realtime

    manager = WebSocketManager()
    monkeypatch.setattr(realtime, "ws_manager", manager)
    app = FastAPI()
    app.include_router(realtime.router)
    with TestClient(app) as test_client:
        with test_client.websocket_connect("/ws?realtime=1&preview_fps=fast") as socket:
            assert "realtime" not in socket.receive_json()["data"]
            test_client.portal.call(manager.broadcast, "media_added", {"media_id": 1, "profile_id": "B"}, False)
            assert socket.receive_json()["data"]["media_id"] == 1


async def test_profile_details_reach_only_clients_scoped_to_that_profile():
    """Per-profile detail (processing stats) rides a global event without
    leaking: legacy and profile-less clients get exactly the aggregate."""
    manager = WebSocketManager()
    legacy, unscoped, alpha, beta = Socket(), Socket(), Socket(), Socket()
    manager.attach(legacy)
    manager.attach(unscoped, RealtimeScope())
    manager.attach(alpha, scoped("A"))
    manager.attach(beta, scoped("B"))
    aggregate = {"phase_stats": {"clip": {"pending": 9}}}
    await manager.broadcast_profile_details("processing_stats", aggregate, {
        "A": {"profile_phase_stats": {"clip": {"pending": 4}}},
        "B": {"profile_phase_stats": {"clip": {"pending": 5}}},
    })
    await manager.drain()
    assert legacy.of("processing_stats") == [aggregate]
    assert unscoped.of("processing_stats") == [aggregate]
    assert alpha.of("processing_stats") == [{**aggregate, "profile_phase_stats": {"clip": {"pending": 4}}, "profile_id": "A"}]
    assert beta.of("processing_stats") == [{**aggregate, "profile_phase_stats": {"clip": {"pending": 5}}, "profile_id": "B"}]
    # A profile without detail (its snapshot failed) gets the aggregate, which tells it to re-read.
    gamma = Socket()
    manager.attach(gamma, scoped("C"))
    await manager.broadcast_profile_details("processing_stats", aggregate, {"A": {"profile_phase_stats": {}}})
    await manager.drain()
    assert gamma.of("processing_stats") == [aggregate]
    assert beta.of("processing_stats")[-1] == aggregate

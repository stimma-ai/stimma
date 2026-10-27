"""Profile PINs on the WebSocket.

A frame tagged with a PIN-protected profile reaches only a socket that proved
that profile's PIN, whatever kind of client it is (legacy or scoped) and
whichever form the frame takes (full, summary, preview). Profiles without a
PIN stay open, and untagged frames go to everyone. A proof is bound to the
PIN it was checked against: changing, adding or removing the PIN takes effect
at the next broadcast.
"""
import asyncio
import base64
import json
import logging

import bcrypt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.logging import RedactPinQueryFilter
from utils.websocket import (
    PIN_REJECTED_CLOSE_CODE,
    PinRejected,
    RealtimeScope,
    WebSocketManager,
)


def _hash(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=4)).decode()


class Pins:
    """profile_id -> PIN hash, editable mid-test like the config file."""

    def __init__(self, **pins):
        self.hashes = {profile: _hash(pin) for profile, pin in pins.items()}

    def set(self, profile, pin):
        if pin is None:
            self.hashes.pop(profile, None)
        else:
            self.hashes[profile] = _hash(pin)

    def __call__(self, profile_id):
        return self.hashes.get(profile_id)


class Socket:
    def __init__(self):
        self.messages = []

    async def send_text(self, message):
        self.messages.append(json.loads(message))

    async def close(self, code=1000):
        pass

    def of(self, event):
        return [m["data"] for m in self.messages if m["event"] == event]

    def profiles(self):
        return {m["data"].get("profile_id") for m in self.messages}


def scoped(profile_id, *topics):
    scope = RealtimeScope()
    scope.update("scope", {"profile_id": profile_id, "topics": list(topics)})
    return scope


GENERATOR = "tool-test:text-to-image@@guid"


async def everything(manager, profile):
    """Every frame shape a profile produces: plain, chat detail, job
    lifecycle (full and summary), progress with a preview image."""
    job = {"id": 1, "status": "queued", "generator_instance_id": GENERATOR, "profile_id": profile,
           "parameters": "{}"}
    base = {"generator_instance_id": GENERATOR, "profile_id": profile}
    await manager.broadcast("media_added", {"media_id": 1, "profile_id": profile})
    await manager.broadcast("chat_item_created", {"chat_id": 7, "profile_id": profile, "item": {"id": 1}})
    await manager.broadcast("generation_job_queued", {"job": job, **base})
    await manager.broadcast("generation_job_progress", {
        "job_id": 1, "progress": 0.5, **base,
        "preview_b64": base64.b64encode(b"x" * 100).decode(), "preview_mime": "image/jpeg",
    })
    await manager.drain()


async def test_protected_frames_reach_only_sockets_that_proved_the_pin():
    pins = Pins(locked="1234")
    manager = WebSocketManager(pin_hash_for=pins)
    legacy, phone, intruder, proven_legacy, proven = Socket(), Socket(), Socket(), Socket(), Socket()
    manager.attach(legacy)
    manager.attach(phone, scoped("open", "chat:7", "generation", "previews"))
    manager.attach(intruder, scoped("locked", "chat:7", "generation", "previews"))
    proof = await manager.prove_pin("locked", "1234")
    manager.attach(proven_legacy, None, proof)
    manager.attach(proven, scoped("locked", "chat:7", "generation", "previews"), proof)

    await everything(manager, "locked")
    await everything(manager, "open")
    await manager.broadcast("tools_updated", {}, include_profile=False)
    await manager.drain()

    assert legacy.profiles() == {"open", None}
    assert intruder.profiles() == {None}
    assert phone.profiles() == {"open", None}
    assert proven_legacy.profiles() == {"open", "locked", None}
    assert proven.profiles() == {"locked", None}
    # The proven scoped client gets the full detail, preview included.
    assert [d["chat_id"] for d in proven.of("chat_item_created")] == [7]
    assert proven.of("generation_job_progress")[0]["preview_b64"]
    # Everyone gets the global frame.
    for socket in (legacy, phone, intruder, proven_legacy, proven):
        assert socket.of("tools_updated") == [{}]


async def test_wrong_pin_is_rejected_and_missing_pin_proves_nothing():
    pins = Pins(locked="1234")
    manager = WebSocketManager(pin_hash_for=pins)
    with pytest.raises(PinRejected):
        await manager.prove_pin("locked", "9999")
    with pytest.raises(PinRejected):
        await manager.prove_pin("locked", 1234)
    assert await manager.prove_pin("locked", None) is None
    assert await manager.prove_pin("locked", "") is None
    # Open and unknown profiles have nothing to prove, whatever is offered.
    assert await manager.prove_pin("open", "anything") is None
    assert await manager.prove_pin(None, "1234") is None


async def test_scope_message_pin_switches_profile_or_leaves_scope_unchanged():
    pins = Pins(locked="1234")
    manager = WebSocketManager(pin_hash_for=pins)
    socket = Socket()
    manager.attach(socket, scoped("open", "chat:7"))

    with pytest.raises(PinRejected):
        await manager.apply_scope_message(socket, "scope", {"profile_id": "locked", "topics": [], "pin": "0000"})
    assert manager.client_for(socket).scope.describe()["profile_id"] == "open"
    assert manager.client_for(socket).scope.describe()["topics"] == ["chat:7"]
    assert manager.client_for(socket).pin_proofs == {}

    # Without a PIN the switch applies, but the profile's frames stay withheld.
    applied = await manager.apply_scope_message(socket, "scope", {"profile_id": "locked"})
    assert applied["profile_id"] == "locked" and applied["authorized"] is False
    await everything(manager, "locked")
    assert socket.messages == []

    # A PIN for the current profile, without naming it, proves it.
    applied = await manager.apply_scope_message(socket, "scope", {"pin": "1234"})
    assert applied["authorized"] is True
    await everything(manager, "locked")
    assert socket.profiles() == {"locked"}

    # An invalid scope with a correct PIN records no proof.
    other = Socket()
    manager.attach(other, scoped("open"))
    with pytest.raises(ValueError):
        await manager.apply_scope_message(other, "scope", {"profile_id": "locked", "topics": 7, "pin": "1234"})
    assert manager.client_for(other).pin_proofs == {}


async def test_proof_does_not_outlive_the_pin_it_was_checked_against():
    pins = Pins(locked="1234")
    manager = WebSocketManager(pin_hash_for=pins)
    socket, legacy = Socket(), Socket()
    manager.attach(socket, scoped("locked"), await manager.prove_pin("locked", "1234"))
    manager.attach(legacy)

    await manager.broadcast("media_added", {"media_id": 1, "profile_id": "locked"})
    pins.set("locked", "5678")  # changed elsewhere
    await manager.broadcast("media_added", {"media_id": 2, "profile_id": "locked"})
    pins.set("locked", None)  # removed: the profile is open
    await manager.broadcast("media_added", {"media_id": 3, "profile_id": "locked"})
    pins.set("open", "4321")  # added to a profile that was open
    await manager.broadcast("media_added", {"media_id": 4, "profile_id": "open"})
    await manager.drain()

    assert [d["media_id"] for d in socket.of("media_added")] == [1, 3]
    assert [d["media_id"] for d in legacy.of("media_added")] == [3]
    # Re-proving against the new PIN restores delivery.
    pins.set("locked", "5678")
    applied = await manager.apply_scope_message(socket, "scope", {"pin": "5678"})
    assert applied["authorized"] is True
    await manager.broadcast("media_added", {"media_id": 5, "profile_id": "locked"})
    await manager.drain()
    assert [d["media_id"] for d in socket.of("media_added")] == [1, 3, 5]


async def test_unreadable_pin_requirement_fails_closed():
    def broken(profile_id):
        raise RuntimeError("config unavailable")

    manager = WebSocketManager(pin_hash_for=broken)
    socket = Socket()
    manager.attach(socket)
    await manager.broadcast("media_added", {"media_id": 1, "profile_id": "any"})
    await manager.broadcast("tools_updated", {}, include_profile=False)
    await manager.drain()
    assert [m["event"] for m in socket.messages] == ["tools_updated"]


async def test_profile_detail_needs_the_profile_pin():
    pins = Pins(locked="1234")
    manager = WebSocketManager(pin_hash_for=pins)
    intruder, owner = Socket(), Socket()
    manager.attach(intruder, scoped("locked"))
    manager.attach(owner, scoped("locked"), await manager.prove_pin("locked", "1234"))
    aggregate = {"phase_stats": {"clip": {"pending": 9}}}
    detail = {"profile_phase_stats": {"clip": {"pending": 4}}}
    await manager.broadcast_profile_details("processing_stats", aggregate, {"locked": detail})
    await manager.drain()
    assert intruder.of("processing_stats") == [aggregate]
    assert owner.of("processing_stats") == [{**aggregate, **detail, "profile_id": "locked"}]


@pytest.fixture
def endpoint(monkeypatch):
    import routes.realtime as realtime

    pins = Pins(locked="1234")
    manager = WebSocketManager(pin_hash_for=pins)
    monkeypatch.setattr(realtime, "ws_manager", manager)
    app = FastAPI()
    app.include_router(realtime.router)
    with TestClient(app) as test_client:
        yield test_client, manager


def test_endpoint_wrong_connect_pin_closes_with_the_pin_code(endpoint):
    test_client, manager = endpoint
    with test_client.websocket_connect("/ws?realtime=1&profile=locked&pin=0000") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
    assert closed.value.code == PIN_REJECTED_CLOSE_CODE
    assert manager.clients == []


def test_endpoint_connect_pin_authorizes_and_scope_pin_is_checked(endpoint):
    test_client, manager = endpoint

    def broadcast(event, data):
        test_client.portal.call(manager.broadcast, event, data, False)

    with test_client.websocket_connect("/ws?realtime=1&profile=locked&pin=1234") as owner, \
            test_client.websocket_connect("/ws?realtime=1&profile=locked") as stranger, \
            test_client.websocket_connect("/ws?profile=locked") as legacy:
        assert owner.receive_json()["data"]["realtime"]["authorized"] is True
        assert stranger.receive_json()["data"]["realtime"]["authorized"] is False
        assert "realtime" not in legacy.receive_json()["data"]

        broadcast("media_added", {"media_id": 1, "profile_id": "locked"})
        broadcast("tools_updated", {})
        assert owner.receive_json()["data"]["media_id"] == 1
        assert owner.receive_json()["event"] == "tools_updated"
        assert stranger.receive_json()["event"] == "tools_updated"
        assert legacy.receive_json()["event"] == "tools_updated"

        stranger.send_json({"event": "realtime_scope", "data": {"profile_id": "locked", "pin": "0000", "seq": 1}})
        rejected = stranger.receive_json()
        assert rejected == {"event": "realtime_scope_rejected", "data": {"seq": 1, "reason": "invalid_pin"}}

        stranger.send_json({"event": "realtime_scope", "data": {"profile_id": "locked", "pin": "1234", "seq": 2}})
        applied = stranger.receive_json()
        assert applied["event"] == "realtime_scope_applied"
        assert applied["data"]["authorized"] is True and applied["data"]["seq"] == 2
        broadcast("media_added", {"media_id": 2, "profile_id": "locked"})
        assert stranger.receive_json()["data"]["media_id"] == 2


def test_pins_in_websocket_handshake_logs_are_masked():
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5000", "/ws?realtime=1&profile=locked&pin=1234&topic=chat:7"),
        None,
    )
    assert RedactPinQueryFilter().filter(record) is True
    line = record.getMessage()
    assert "1234" not in line
    assert "pin=[redacted]&topic=chat:7" in line
    assert "profile=locked" in line

"""Negotiated JSON compression on the remote serving listener.

Exercised through the production middleware stack (``create_app()`` with its
BaseHTTPMiddleware layers, real routers and database) behind the real
ServingGate, so the tests cover what a remote device actually receives.
Raw bytes are read with ``aiter_raw`` so httpx's own decoding cannot hide
what went over the wire.
"""
import asyncio
import gzip
import json

import httpx
import pytest
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from multi_device import server
from multi_device.compression import JsonCompression, REMOTE_SCOPE_KEY, accepts_gzip

BIG = {"items": [{"id": i, "role": "assistant", "text": "a repetitive chat body " * 8} for i in range(400)]}
BIG_BYTES = JSONResponse(BIG).body
ETAG = '"catalog-v1"'
FIXTURE = "/api/compression-fixture"
stream_gate = asyncio.Event()


def _fixture_router(tmp_path) -> APIRouter:
    router = APIRouter(prefix=FIXTURE)
    media = tmp_path / "clip.json"
    media.write_bytes(BIG_BYTES)
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG" + bytes(range(256)) * 64)

    @router.api_route("/big", methods=["GET", "HEAD", "POST"])
    async def big():
        return JSONResponse(BIG)

    @router.get("/small")
    async def small():
        return {"ok": True}

    @router.get("/weak")
    async def weak(request: Request):
        headers = {"ETag": 'W/"weak-v1"', "Vary": "Origin"}
        if request.headers.get("if-none-match") == 'W/"weak-v1"':
            return Response(status_code=304, headers=headers)
        return JSONResponse(BIG, headers=headers)

    @router.get("/catalog")
    async def catalog(request: Request):
        headers = {"ETag": ETAG, "Vary": "Origin"}
        if request.headers.get("if-none-match", "").removeprefix("W/") == ETAG:
            return Response(status_code=304, headers=headers)
        return JSONResponse(BIG, headers=headers)

    @router.get("/streamed")
    async def streamed():
        async def chunks():
            yield b'{"items": ['
            for i in range(400):
                yield (b"," if i else b"") + json.dumps(BIG["items"][i]).encode()
            yield b"]}"
        return StreamingResponse(chunks(), media_type="application/json")

    @router.get("/gated")
    async def gated():
        async def chunks():
            yield b'{"first": true'
            await stream_gate.wait()
            yield b"}"
        return StreamingResponse(chunks(), media_type="application/json")

    @router.get("/events")
    async def events():
        async def chunks():
            for i in range(50):
                yield f"data: {json.dumps(BIG['items'][i])}\n\n".encode()
        return StreamingResponse(chunks(), media_type="text/event-stream")

    @router.get("/file.json")
    async def file_json():
        return FileResponse(media, media_type="application/json")

    @router.get("/image")
    async def image_route():
        return FileResponse(image, media_type="image/png")

    @router.get("/encoded")
    async def encoded():
        return Response(gzip.compress(BIG_BYTES), media_type="application/json", headers={"Content-Encoding": "gzip"})

    @router.get("/no-transform")
    async def no_transform():
        return JSONResponse(BIG, headers={"Cache-Control": "no-transform"})

    @router.get("/missing")
    async def missing():
        return JSONResponse({"detail": "x" * 4000}, status_code=404)

    return router


def _secret_router() -> APIRouter:
    # A large response under a credential-bearing prefix, standing in for one
    # that returns API keys or tokens.
    router = APIRouter(prefix="/api/settings")

    @router.get("/compression-fixture-keys")
    async def keys():
        return {"keys": [{"provider": f"p{i}", "api_key": "sk-" + "0123456789" * 4} for i in range(100)]}

    return router


@pytest.fixture(scope="module")
async def gate(test_app, tmp_path_factory):
    test_app.include_router(_fixture_router(tmp_path_factory.mktemp("compression")))
    test_app.include_router(_secret_router())
    return server.ServingGate(test_app, lambda: "server-device")


@pytest.fixture
async def remote(gate, monkeypatch):
    monkeypatch.setattr(server, "verify_session", lambda token: token == "session")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(gate), base_url="https://remote",
                                 headers={"Authorization": "Bearer session", "X-Profile-ID": "default"}) as http:
        yield http


async def _raw(client, method, path, **headers):
    async with client.stream(method, path, headers=headers) as response:
        body = b"".join([chunk async for chunk in response.aiter_raw()])
        return response, body


async def test_a_real_chat_window_is_compressed_through_the_production_stack(remote, db_session):
    from database import Chat, ChatItem
    async with db_session() as session:
        chat = Chat(name="Long chat")
        session.add(chat)
        await session.flush()
        for i in range(300):
            session.add(ChatItem(chat_id=chat.id, item_type="assistant_message",
                                 message_text=f"Reply {i}: here is a long, ordinary assistant answer about images. " * 4))
        await session.commit()
        chat_id = chat.id
    path = f"/api/chats/{chat_id}/items?visible_limit=500"
    identity, plain = await _raw(remote, "GET", path, **{"accept-encoding": "identity"})
    assert identity.status_code == 200 and "content-encoding" not in identity.headers
    response, body = await _raw(remote, "GET", path, **{"accept-encoding": "gzip, deflate, br"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert int(response.headers["content-length"]) == len(body) < len(plain) // 4
    assert "accept-encoding" in response.headers["vary"].lower()
    assert gzip.decompress(body) == plain


async def test_loopback_is_never_compressed(test_app):
    # The same app, reached without the remote gate's mark.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(test_app), base_url="http://test",
                                 headers={"X-Profile-ID": "default"}) as local:
        response, body = await _raw(local, "GET", f"{FIXTURE}/big", **{"accept-encoding": "gzip"})
        assert "content-encoding" not in response.headers and body == BIG_BYTES


async def test_large_json_is_gzipped_when_accepted(remote):
    for method in ("GET", "POST"):
        response, body = await _raw(remote, method, f"{FIXTURE}/big", **{"accept-encoding": "gzip, deflate, br"})
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert int(response.headers["content-length"]) == len(body) < len(BIG_BYTES) // 5
        assert "accept-encoding" in response.headers["vary"].lower()
        assert json.loads(gzip.decompress(body)) == BIG


@pytest.mark.parametrize("accept", ["", "identity", "gzip;q=0", "br", "*;q=0", "gzip;q=0, *"])
async def test_large_json_stays_identity_unless_gzip_is_accepted(remote, accept):
    response, body = await _raw(remote, "GET", f"{FIXTURE}/big", **{"accept-encoding": accept})
    assert "content-encoding" not in response.headers
    assert body == BIG_BYTES
    assert int(response.headers["content-length"]) == len(BIG_BYTES)
    # The representation still depends on the header, so caches must key on it.
    assert "accept-encoding" in response.headers["vary"].lower()


async def test_small_json_is_not_compressed(remote):
    response, body = await _raw(remote, "GET", f"{FIXTURE}/small", **{"accept-encoding": "gzip"})
    assert "content-encoding" not in response.headers
    assert json.loads(body) == {"ok": True}


async def test_streamed_json_and_events_pass_through_uncompressed(remote):
    for path, media_type in ((f"{FIXTURE}/streamed", "application/json"), (f"{FIXTURE}/events", "text/event-stream")):
        response, body = await _raw(remote, "GET", path, **{"accept-encoding": "gzip"})
        assert response.headers["content-type"].startswith(media_type)
        assert "content-encoding" not in response.headers
        assert "accept-encoding" not in response.headers.get("vary", "").lower()
        assert len(body) > 10_000
    response, body = await _raw(remote, "GET", f"{FIXTURE}/streamed", **{"accept-encoding": "gzip"})
    assert json.loads(body)["items"] == BIG["items"]


async def test_a_stream_is_not_buffered(gate, monkeypatch):
    """The first chunk reaches the server's send before the producer finishes."""
    monkeypatch.setattr(server, "verify_session", lambda token: token == "session")
    stream_gate.clear()
    sent = []
    first_chunk = asyncio.Event()

    async def receive():
        await asyncio.Event().wait()  # Never disconnects.

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    scope = {"type": "http", "method": "GET", "path": f"{FIXTURE}/gated", "raw_path": f"{FIXTURE}/gated".encode(),
             "query_string": b"", "scheme": "https", "server": ("remote", 443), "client": ("127.0.0.1", 1),
             "root_path": "", "http_version": "1.1", "asgi": {"version": "3.0"},
             "headers": [(b"authorization", b"Bearer session"), (b"x-profile-id", b"default"), (b"accept-encoding", b"gzip"), (b"host", b"remote")]}
    task = asyncio.create_task(gate(scope, receive, send))
    await asyncio.wait_for(first_chunk.wait(), 5)
    assert not task.done()
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert all(name.lower() != b"content-encoding" for name, _ in start["headers"])
    assert b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body") == b'{"first": true'
    stream_gate.set()
    await asyncio.wait_for(task, 5)
    assert b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body") == b'{"first": true}'


async def test_ranges_and_range_capable_files_are_never_compressed(remote):
    response, body = await _raw(remote, "GET", f"{FIXTURE}/file.json", **{"accept-encoding": "gzip", "range": "bytes=0-99"})
    assert response.status_code == 206
    assert "content-encoding" not in response.headers
    assert body == BIG_BYTES[:100]
    # Even unranged: a file that advertises byte ranges must keep one representation.
    response, body = await _raw(remote, "GET", f"{FIXTURE}/file.json", **{"accept-encoding": "gzip"})
    assert response.status_code == 200 and response.headers["accept-ranges"] == "bytes"
    assert "content-encoding" not in response.headers and body == BIG_BYTES


async def test_head_is_never_compressed(remote):
    response = await remote.head(f"{FIXTURE}/big", headers={"accept-encoding": "gzip"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["content-type"] == "application/json"
    assert int(response.headers["content-length"]) == len(BIG_BYTES)
    # The server drops a HEAD body on the wire; what the app produced was never gzip.
    assert response.content in (b"", BIG_BYTES)


async def test_media_and_already_encoded_responses_are_untouched(remote):
    response, body = await _raw(remote, "GET", f"{FIXTURE}/image", **{"accept-encoding": "gzip"})
    assert response.headers["content-type"] == "image/png" and "content-encoding" not in response.headers
    assert body.startswith(b"\x89PNG")
    response, body = await _raw(remote, "GET", f"{FIXTURE}/encoded", **{"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == BIG_BYTES  # compressed exactly once
    response, body = await _raw(remote, "GET", f"{FIXTURE}/no-transform", **{"accept-encoding": "gzip"})
    assert "content-encoding" not in response.headers and body == BIG_BYTES
    response, body = await _raw(remote, "GET", f"{FIXTURE}/missing", **{"accept-encoding": "gzip"})
    assert response.status_code == 404 and "content-encoding" not in response.headers


async def test_secret_bearing_routes_are_never_compressed(remote):
    # Settings responses can carry API keys; everything under the prefix is excluded.
    response, body = await _raw(remote, "GET", "/api/settings/compression-fixture-keys", **{"accept-encoding": "gzip"})
    assert response.status_code == 200
    assert len(body) >= 1400  # Large enough that it would otherwise be compressed.
    assert "content-encoding" not in response.headers
    assert "accept-encoding" not in response.headers.get("vary", "").lower()
    assert len(json.loads(body)["keys"]) == 100
    response, _ = await _raw(remote, "GET", "/api/settings", **{"accept-encoding": "gzip"})
    assert response.status_code == 200 and "content-encoding" not in response.headers


async def test_conditional_requests_keep_the_negotiated_metadata(remote):
    response, body = await _raw(remote, "GET", f"{FIXTURE}/catalog", **{"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    # The compressed bytes are a different representation: the validator is weakened,
    # and the existing Vary is extended rather than replaced.
    assert response.headers["etag"] == "W/" + ETAG
    vary = [token.strip() for token in response.headers["vary"].split(",")]
    assert vary == ["Origin", "Accept-Encoding"]
    revalidated, body = await _raw(remote, "GET", f"{FIXTURE}/catalog", **{"accept-encoding": "gzip", "if-none-match": response.headers["etag"]})
    assert revalidated.status_code == 304 and body == b""
    assert "content-encoding" not in revalidated.headers
    # The 304 carries the validator and Vary its 200 did.
    assert revalidated.headers["etag"] == "W/" + ETAG
    assert [token.strip() for token in revalidated.headers["vary"].split(",")] == vary
    # A client holding the identity representation revalidates against the strong tag.
    identity, body = await _raw(remote, "GET", f"{FIXTURE}/catalog", **{"accept-encoding": "identity"})
    assert identity.headers["etag"] == ETAG and body == BIG_BYTES
    assert [token.strip() for token in identity.headers["vary"].split(",")] == vary
    strong, _ = await _raw(remote, "GET", f"{FIXTURE}/catalog", **{"accept-encoding": "identity", "if-none-match": ETAG})
    assert strong.status_code == 304 and strong.headers["etag"] == ETAG
    assert [token.strip() for token in strong.headers["vary"].split(",")] == vary


async def test_a_route_with_a_weak_validator_keeps_vary_on_its_304(remote):
    response, _ = await _raw(remote, "GET", f"{FIXTURE}/weak", **{"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["etag"] == 'W/"weak-v1"'
    assert [token.strip() for token in response.headers["vary"].split(",")] == ["Origin", "Accept-Encoding"]
    for accept in ("gzip", "identity"):
        revalidated, body = await _raw(remote, "GET", f"{FIXTURE}/weak", **{"accept-encoding": accept, "if-none-match": 'W/"weak-v1"'})
        assert revalidated.status_code == 304 and body == b""
        assert revalidated.headers["etag"] == 'W/"weak-v1"'
        assert [token.strip() for token in revalidated.headers["vary"].split(",")] == ["Origin", "Accept-Encoding"]


async def test_unauthenticated_responses_are_unchanged(remote):
    response = await remote.get(f"{FIXTURE}/big", headers={"authorization": "Bearer wrong", "accept-encoding": "gzip"})
    assert response.status_code == 401 and "content-encoding" not in response.headers


async def test_websocket_scopes_are_passed_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    await JsonCompression(app)({"type": "websocket", REMOTE_SCOPE_KEY: True, "headers": [(b"accept-encoding", b"gzip")]}, None, None)
    assert seen == ["websocket"]


def test_accept_encoding_parsing_is_conservative():
    assert accepts_gzip("gzip")
    assert accepts_gzip("GZIP;q=0.5")
    assert accepts_gzip("deflate, gzip;q=1.0, br")
    assert accepts_gzip("x-gzip")
    assert accepts_gzip("*")
    assert not accepts_gzip(None)
    assert not accepts_gzip("")
    assert not accepts_gzip("identity")
    assert not accepts_gzip("identity;q=1, *;q=0")  # Chromium media range requests
    assert not accepts_gzip("gzip;q=0")
    assert not accepts_gzip("gzip;q=0, *")
    assert not accepts_gzip("gzip;q=abc")
    assert not accepts_gzip("gzip;q=2")

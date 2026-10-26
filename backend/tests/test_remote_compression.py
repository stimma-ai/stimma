"""Negotiated JSON compression on the remote serving listener.

Exercised through the real ServingGate so the tests cover what a remote
device actually receives. Raw response bytes are read with ``iter_raw`` so
httpx's own transparent decoding cannot hide what went over the wire.
"""
import gzip
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from multi_device import server
from multi_device.compression import JsonCompression, accepts_gzip

BIG = {"items": [{"id": i, "role": "assistant", "text": "a repetitive chat body " * 8} for i in range(400)]}
BIG_BYTES = JSONResponse(BIG).body
ETAG = '"catalog-v1"'


def _app(tmp_path) -> FastAPI:
    app = FastAPI()
    media = tmp_path / "clip.json"
    media.write_bytes(BIG_BYTES)
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG" + bytes(range(256)) * 64)

    @app.get("/api/big")
    async def big():
        return JSONResponse(BIG)

    @app.get("/api/small")
    async def small():
        return {"ok": True}

    @app.post("/api/big")
    async def big_post():
        return JSONResponse(BIG)

    @app.get("/api/catalog")
    async def catalog(request: Request):
        if request.headers.get("if-none-match", "").removeprefix("W/") == ETAG:
            return Response(status_code=304, headers={"ETag": ETAG})
        return JSONResponse(BIG, headers={"ETag": ETAG, "Vary": "Origin"})

    @app.get("/api/streamed")
    async def streamed():
        async def chunks():
            yield b'{"items": ['
            for i in range(400):
                yield (b"," if i else b"") + json.dumps(BIG["items"][i]).encode()
            yield b"]}"
        return StreamingResponse(chunks(), media_type="application/json")

    @app.get("/api/events")
    async def events():
        async def chunks():
            for i in range(50):
                yield f"data: {json.dumps(BIG['items'][i])}\n\n".encode()
        return StreamingResponse(chunks(), media_type="text/event-stream")

    @app.get("/api/file.json")
    async def file_json():
        return FileResponse(media, media_type="application/json")

    @app.get("/api/image")
    async def image_route():
        return FileResponse(image, media_type="image/png")

    @app.get("/api/encoded")
    async def encoded():
        body = gzip.compress(BIG_BYTES)
        return Response(body, media_type="application/json", headers={"Content-Encoding": "gzip"})

    @app.get("/api/no-transform")
    async def no_transform():
        return JSONResponse(BIG, headers={"Cache-Control": "no-transform"})

    @app.get("/api/missing")
    async def missing():
        return JSONResponse({"detail": "x" * 4000}, status_code=404)

    return app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "verify_session", lambda token: token == "session")
    gate = server.ServingGate(_app(tmp_path), lambda: "server-device")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(gate), base_url="https://remote",
                                 headers={"Authorization": "Bearer session"}) as http:
        yield http


async def _raw(client, method, path, **headers):
    async with client.stream(method, path, headers=headers) as response:
        body = b"".join([chunk async for chunk in response.aiter_raw()])
        return response, body


async def test_large_json_is_gzipped_when_accepted(client):
    response, body = await _raw(client, "GET", "/api/big", **{"accept-encoding": "gzip, deflate, br"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert int(response.headers["content-length"]) == len(body) < len(BIG_BYTES) // 5
    assert "accept-encoding" in response.headers["vary"].lower()
    assert json.loads(gzip.decompress(body)) == BIG


async def test_mutation_responses_are_compressed_too(client):
    response, body = await _raw(client, "POST", "/api/big", **{"accept-encoding": "gzip", "content-length": "0"})
    assert response.headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(body)) == BIG


@pytest.mark.parametrize("accept", [None, "identity", "gzip;q=0", "br", "*;q=0", "gzip;q=0, *"])
async def test_large_json_stays_identity_unless_gzip_is_accepted(client, accept):
    headers = {"accept-encoding": accept} if accept is not None else {"accept-encoding": ""}
    response, body = await _raw(client, "GET", "/api/big", **headers)
    assert "content-encoding" not in response.headers
    assert body == BIG_BYTES
    assert int(response.headers["content-length"]) == len(BIG_BYTES)
    # The representation still depends on the header, so caches must key on it.
    assert "accept-encoding" in response.headers["vary"].lower()


async def test_small_json_is_not_compressed(client):
    response, body = await _raw(client, "GET", "/api/small", **{"accept-encoding": "gzip"})
    assert "content-encoding" not in response.headers
    assert json.loads(body) == {"ok": True}


async def test_streamed_json_and_events_pass_through_unbuffered(client):
    for path, media_type in (("/api/streamed", "application/json"), ("/api/events", "text/event-stream")):
        response, body = await _raw(client, "GET", path, **{"accept-encoding": "gzip"})
        assert response.headers["content-type"].startswith(media_type)
        assert "content-encoding" not in response.headers
        assert "accept-encoding" not in response.headers.get("vary", "").lower()
        assert len(body) > 10_000
    response, body = await _raw(client, "GET", "/api/streamed", **{"accept-encoding": "gzip"})
    assert json.loads(body)["items"] == BIG["items"]


async def test_ranges_and_range_capable_files_are_never_compressed(client):
    response, body = await _raw(client, "GET", "/api/file.json", **{"accept-encoding": "gzip", "range": "bytes=0-99"})
    assert response.status_code == 206
    assert "content-encoding" not in response.headers
    assert body == BIG_BYTES[:100]
    # Even unranged: a file that advertises byte ranges must keep one representation.
    response, body = await _raw(client, "GET", "/api/file.json", **{"accept-encoding": "gzip"})
    assert response.status_code == 200 and response.headers["accept-ranges"] == "bytes"
    assert "content-encoding" not in response.headers and body == BIG_BYTES


async def test_media_head_and_already_encoded_responses_are_untouched(client):
    response, body = await _raw(client, "GET", "/api/image", **{"accept-encoding": "gzip"})
    assert response.headers["content-type"] == "image/png" and "content-encoding" not in response.headers
    assert body.startswith(b"\x89PNG")
    response = await client.head("/api/big", headers={"accept-encoding": "gzip"})
    assert "content-encoding" not in response.headers
    response, body = await _raw(client, "GET", "/api/encoded", **{"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert gzip.decompress(body) == BIG_BYTES  # compressed exactly once
    response, body = await _raw(client, "GET", "/api/no-transform", **{"accept-encoding": "gzip"})
    assert "content-encoding" not in response.headers and body == BIG_BYTES
    response, body = await _raw(client, "GET", "/api/missing", **{"accept-encoding": "gzip"})
    assert response.status_code == 404 and "content-encoding" not in response.headers


async def test_conditional_requests_survive_compression(client):
    response, body = await _raw(client, "GET", "/api/catalog", **{"accept-encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    # The compressed bytes are a different representation: the validator is weakened,
    # and the existing Vary is extended rather than replaced.
    assert response.headers["etag"] == "W/" + ETAG
    assert [token.strip() for token in response.headers["vary"].split(",")] == ["Origin", "Accept-Encoding"]
    revalidated, body = await _raw(client, "GET", "/api/catalog", **{"accept-encoding": "gzip", "if-none-match": response.headers["etag"]})
    assert revalidated.status_code == 304 and body == b""
    assert "content-encoding" not in revalidated.headers
    identity, body = await _raw(client, "GET", "/api/catalog", **{"accept-encoding": "identity"})
    assert identity.headers["etag"] == ETAG and body == BIG_BYTES


async def test_unauthenticated_and_bootstrap_responses_are_unchanged(client):
    response = await client.get("/api/big", headers={"authorization": "Bearer wrong", "accept-encoding": "gzip"})
    assert response.status_code == 401 and "content-encoding" not in response.headers


async def test_websocket_scopes_are_passed_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    await JsonCompression(app)({"type": "websocket", "headers": [(b"accept-encoding", b"gzip")]}, None, None)
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

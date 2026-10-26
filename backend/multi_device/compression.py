"""Negotiated gzip for substantial JSON on the remote serving listener.

Remote clients reach this listener over cellular and Wi-Fi links where JSON
bytes dominate: a long chat window or the tool catalog is hundreds of
kilobytes of highly repetitive text that gzip shrinks roughly tenfold. The
loopback listener the local app uses is not wrapped; compressing a localhost
hop only spends CPU.

Deliberately narrow. Only a complete, single-message JSON body with status
200 is a candidate, so anything streamed (SSE, chunked exports, file
downloads), anything ranged, media, HEAD, WebSockets, and responses that
already carry a Content-Encoding pass through untouched. Media is either
already compressed or must stay byte-addressable for range requests.

Every compression-eligible response carries ``Vary: Accept-Encoding`` whether
or not this particular client accepted gzip, so a cache never serves one
encoding to a client that negotiated the other. A strong ETag on a
compressed body is weakened: the bytes differ from the identity
representation, while weak comparison (what If-None-Match uses) still matches
the same validator, so conditional requests and 304s keep working.
"""
from __future__ import annotations

import asyncio
import gzip

# Below roughly one packet there is no round trip to save.
MINIMUM_SIZE = 1400
# Most of the size benefit for a fraction of level 9's CPU.
LEVEL = 6
# Larger bodies are compressed off the event loop.
THREAD_THRESHOLD = 128 * 1024


def accepts_gzip(header: str | None) -> bool:
    """Whether an Accept-Encoding value permits gzip (RFC 9110 12.5.3).

    Parsed conservatively: an explicit ``gzip``/``x-gzip`` entry decides,
    including ``q=0`` refusals; otherwise a ``*`` wildcard does. A missing or
    unparseable header means identity only.
    """
    if not header:
        return False
    explicit: float | None = None
    wildcard: float | None = None
    for item in header.split(","):
        parts = [part.strip() for part in item.split(";")]
        coding = parts[0].lower()
        if not coding:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
                if not 0.0 <= quality <= 1.0:
                    quality = 0.0
        if coding in ("gzip", "x-gzip"):
            explicit = quality if explicit is None else max(explicit, quality)
        elif coding == "*":
            wildcard = quality
    if explicit is not None:
        return explicit > 0
    return wildcard is not None and wildcard > 0


def _is_json(content_type: bytes) -> bool:
    media = content_type.split(b";", 1)[0].strip().lower()
    return media == b"application/json" or (media.startswith(b"application/") and media.endswith(b"+json"))


def _header(headers, name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _eligible(start: dict) -> bool:
    if start.get("status") != 200:
        return False
    headers = start.get("headers", [])
    content_type = _header(headers, b"content-type")
    if content_type is None or not _is_json(content_type):
        return False
    if _header(headers, b"content-encoding") is not None:
        return False
    if _header(headers, b"content-range") is not None or _header(headers, b"accept-ranges") is not None:
        return False
    cache_control = (_header(headers, b"cache-control") or b"").lower()
    return b"no-transform" not in cache_control


def _with_vary(headers: list) -> list:
    """Add Accept-Encoding to Vary, merging with whatever is already there."""
    existing = [value for key, value in headers if key.lower() == b"vary"]
    tokens = [token.strip() for value in existing for token in value.split(b",") if token.strip()]
    if any(token == b"*" or token.lower() == b"accept-encoding" for token in tokens):
        return headers
    rest = [(key, value) for key, value in headers if key.lower() != b"vary"]
    return rest + [(b"vary", b", ".join(tokens + [b"Accept-Encoding"]))]


def _compressed_headers(headers: list, length: int) -> list:
    out = []
    for key, value in headers:
        lower = key.lower()
        if lower == b"content-length":
            continue
        if lower == b"etag" and not value.startswith(b"W/"):
            value = b"W/" + value
        out.append((key, value))
    out.append((b"content-encoding", b"gzip"))
    out.append((b"content-length", str(length).encode()))
    return out


class JsonCompression:
    """ASGI middleware: gzip complete JSON bodies when the client accepts it."""

    def __init__(self, app, minimum_size: int = MINIMUM_SIZE, level: int = LEVEL):
        self.app = app
        self.minimum_size = minimum_size
        self.level = level

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "HEAD":
            await self.app(scope, receive, send)
            return
        request_headers = scope.get("headers", [])
        if _header(request_headers, b"range") is not None:
            await self.app(scope, receive, send)
            return
        gzip_ok = accepts_gzip((_header(request_headers, b"accept-encoding") or b"").decode("latin-1"))

        held: dict | None = None
        passthrough = False

        async def wrapped(message):
            nonlocal held, passthrough
            if passthrough:
                await send(message)
                return
            kind = message["type"]
            if kind == "http.response.start":
                if _eligible(message):
                    held = message
                else:
                    passthrough = True
                    await send(message)
                return
            if held is None:
                await send(message)
                return
            start, held = held, None
            passthrough = True
            if kind != "http.response.body" or message.get("more_body", False):
                # Streamed, or an extension we do not rewrite: leave it alone.
                await send(start)
                await send(message)
                return
            body = message.get("body", b"")
            if len(body) < self.minimum_size:
                await send(start)
                await send(message)
                return
            headers = _with_vary(list(start.get("headers", [])))
            if not gzip_ok:
                await send({**start, "headers": headers})
                await send(message)
                return
            if len(body) >= THREAD_THRESHOLD:
                compressed = await asyncio.to_thread(gzip.compress, body, self.level, mtime=0)
            else:
                compressed = gzip.compress(body, self.level, mtime=0)
            await send({**start, "headers": _compressed_headers(headers, len(compressed))})
            await send({"type": "http.response.body", "body": compressed, "more_body": False})

        await self.app(scope, receive, wrapped)
        if held is not None:
            # The app ended without a body message; deliver what it started.
            await send(held)

"""Streamed chat completions (llm_http.astream_chat, llm.llm_stream_text): text deltas from an
OpenAI-compatible endpoint, and StreamUnsupported where the provider or endpoint answers whole."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import llm_http
from llm_http import StreamUnsupported, astream_chat


_CLIENT = httpx.AsyncClient


def _client(monkeypatch, respond):
    monkeypatch.setattr(llm_http.httpx, "AsyncClient", lambda **kw: _CLIENT(**kw, transport=httpx.MockTransport(respond)))


async def _all(**kw):
    return [d async for d in astream_chat(model="m", messages=[{"role": "user", "content": "x"}], **kw)]


def _sse(*events: dict) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode() + b"data: [DONE]\n\n"


def test_a_stream_yields_its_text_deltas_and_never_reasoning(monkeypatch):
    seen = {}

    def respond(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(
            {"choices": [{"delta": {"reasoning_content": "hmm"}}]},
            {"choices": [{"delta": {"content": '{"n": 1, '}}]},
            {"choices": [{"delta": {"content": '"text": "a"}'}}]},
            {"choices": [], "usage": {"completion_tokens": 9}}))
    _client(monkeypatch, respond)
    got = asyncio.run(_all(api_base="http://local-model:8000/v1", max_tokens=100, temperature=0.8,
                           extra_body={"chat_template_kwargs": {"enable_thinking": False}}))
    assert got == ['{"n": 1, ', '"text": "a"}']
    assert seen["stream"] is True and seen["stream_options"] == {"include_usage": True}
    assert seen["chat_template_kwargs"] == {"enable_thinking": False} and seen["max_tokens"] == 100


def test_an_endpoint_that_refuses_or_ignores_streaming_is_asked_whole_next_time(monkeypatch):
    monkeypatch.setattr(llm_http, "_NO_STREAM", set())
    _client(monkeypatch, lambda request: httpx.Response(400, json={"error": "stream not supported"}))
    with pytest.raises(StreamUnsupported):
        asyncio.run(_all(api_base="http://a/v1"))
    assert ("http://a/v1", "m") in llm_http._NO_STREAM
    # answered whole: its text is taken, and the next call doesn't try to stream
    _client(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "whole"}}]}))
    assert asyncio.run(_all(api_base="http://b/v1")) == ["whole"]
    with pytest.raises(StreamUnsupported):
        asyncio.run(_all(api_base="http://b/v1"))


def test_native_providers_answer_whole(monkeypatch):
    for kind in ("anthropic", "openai", "chatgpt"):
        with pytest.raises(StreamUnsupported):
            asyncio.run(_all(api_base="http://x/v1", provider_kind=kind))


def test_an_error_mid_stream_raises(monkeypatch):
    _client(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                                        content=_sse({"choices": [{"delta": {"content": "a"}}]},
                                                                     {"error": {"message": "overloaded"}})))
    with pytest.raises(llm_http.LLMStreamError):
        asyncio.run(_all(api_base="http://local-model:8000/v1"))

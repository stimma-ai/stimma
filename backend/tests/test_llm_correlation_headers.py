"""Correlation headers on outbound LLM requests.

Stimma Cloud LLM requests carry the mechanical correlation headers
(X-Stimma-Chat-Id / X-Stimma-Run-Id / X-Stimma-Agent-Context) when an agent
execution scope is active; BYOAI / custom endpoints never receive them.
"""
import json

import pytest

import llm_http
from llm_correlation import correlation_headers, llm_correlation_context

CLOUD_BASE = "https://stimma.ai/api/llm/v1"
BYOAI_BASE = "http://localhost:1234/v1"

CORRELATION_HEADER_NAMES = (
    "X-Stimma-Chat-Id",
    "X-Stimma-Run-Id",
    "X-Stimma-Agent-Context",
)


class _FakeResponse:
    status_code = 200
    headers: dict = {}

    def __init__(self, payload: dict):
        self._payload = payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _CapturingClient:
    """Stand-in for httpx.AsyncClient that records the POST it receives."""

    captured: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _CapturingClient.captured = {"url": url, "json": json, "headers": headers}
        return _FakeResponse({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


@pytest.fixture
def captured_post(monkeypatch):
    _CapturingClient.captured = None
    monkeypatch.setattr(llm_http.httpx, "AsyncClient", _CapturingClient)
    yield _CapturingClient


async def _call(api_base: str):
    return await llm_http.acompletion(
        model="agent",
        messages=[{"role": "user", "content": "hi"}],
        api_key="token",
        api_base=api_base,
        session_id="chat-7",
    )


async def test_cloud_request_carries_correlation_headers(captured_post):
    with llm_correlation_context("main", chat_id=7) as run_id:
        await _call(CLOUD_BASE)

    headers = captured_post.captured["headers"]
    assert headers["X-Stimma-Session"] == "chat-7"
    assert headers["X-Stimma-Chat-Id"] == "7"
    assert headers["X-Stimma-Run-Id"] == run_id
    assert headers["X-Stimma-Agent-Context"] == "main"


async def test_byoai_request_never_carries_correlation_headers(captured_post):
    with llm_correlation_context("main", chat_id=7):
        await _call(BYOAI_BASE)

    headers = captured_post.captured["headers"]
    for name in CORRELATION_HEADER_NAMES:
        assert name not in headers


async def test_cloud_request_outside_scope_has_no_correlation_headers(captured_post):
    await _call(CLOUD_BASE)

    headers = captured_post.captured["headers"]
    for name in CORRELATION_HEADER_NAMES:
        assert name not in headers


async def test_chat_id_header_omitted_when_no_chat_in_scope(captured_post):
    with llm_correlation_context("prompt-agent"):
        await _call(CLOUD_BASE)

    headers = captured_post.captured["headers"]
    assert "X-Stimma-Chat-Id" not in headers
    assert headers["X-Stimma-Agent-Context"] == "prompt-agent"
    assert headers["X-Stimma-Run-Id"]


def test_correlation_scope_restores_on_exit():
    assert correlation_headers() == {}
    with llm_correlation_context("main", chat_id=1):
        with llm_correlation_context("delegate", chat_id=1) as delegate_run:
            inner = correlation_headers()
            assert inner["X-Stimma-Agent-Context"] == "delegate"
            assert inner["X-Stimma-Run-Id"] == delegate_run
        outer = correlation_headers()
        assert outer["X-Stimma-Agent-Context"] == "main"
        assert outer["X-Stimma-Run-Id"] != delegate_run
    assert correlation_headers() == {}

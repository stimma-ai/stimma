"""ChatGPT-plan provider wiring: resolution, request shape, and error routing."""
import base64
import json
import time
from types import SimpleNamespace

import httpx
import pytest

import chatgpt_auth
import llm_http
import llm_resolver
from config import LLMProviderConfig
from llm_provider_catalog import (
    CHATGPT_REASONING_LEVELS,
    chatgpt_model,
    is_supported_chatgpt_model,
)


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _access_token(account_id="acct_1", ttl=3600):
    return _jwt({
        "exp": int(time.time()) + ttl,
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_plan_type": "plus",
        },
    })


RESOLVED_TOKEN = None


@pytest.fixture
def chatgpt_provider(monkeypatch):
    """A configured ChatGPT provider with one model, and a live token."""
    global RESOLVED_TOKEN
    RESOLVED_TOKEN = _access_token()
    provider = LLMProviderConfig(
        id="chatgpt-test",
        kind="chatgpt",
        name="ChatGPT",
        base_url=chatgpt_auth.BACKEND_BASE_URL,
        api_key=None,  # deliberately keyless
        models=[chatgpt_model("chatgpt-test", {
            "id": "gpt-5.6-terra",
            "name": "GPT-5.6 Terra",
            "context_length": 272_000,
        })],
        last_test_passed=True,
    )

    settings = SimpleNamespace(
        llm_providers=[provider],
        llm_reasoning_levels={},
        llm_model_prompts={},
    )
    monkeypatch.setattr(llm_resolver, "get_settings", lambda: settings)
    monkeypatch.setattr(
        chatgpt_auth, "get_access_token", _async_return(RESOLVED_TOKEN)
    )
    return provider


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _async_raise(exc):
    async def _inner(*args, **kwargs):
        raise exc
    return _inner


class TestModelConfig:
    def test_catalog_entry_becomes_a_selectable_model(self, chatgpt_provider):
        model = chatgpt_provider.models[0]
        assert model.id == "chatgpt-test:gpt-5.6-terra"
        assert model.model_id == "gpt-5.6-terra"
        assert model.reasoning.levels == CHATGPT_REASONING_LEVELS
        assert model.reasoning.default == "medium"

    def test_only_the_5_6_family_is_exposed(self):
        """Older families are on the plan but deliberately not offered."""
        for slug in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            assert is_supported_chatgpt_model(slug), slug
        for slug in ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"):
            assert not is_supported_chatgpt_model(slug), slug

    def test_ladder_includes_the_max_rung(self):
        """Verified live: the 5.6 family accepts 'max'."""
        model = chatgpt_model("p", {"id": "gpt-5.6-terra"})
        assert model.reasoning.levels == [
            "off", "low", "medium", "high", "xhigh", "max",
        ]

    def test_minimal_is_never_offered(self):
        """In the API's global list, but rejected by every model."""
        assert "minimal" not in chatgpt_model("p", {"id": "gpt-5.6-terra"}).reasoning.levels

    def test_wire_values_are_what_openai_accepts(self):
        model = chatgpt_model("p", {"id": "gpt-5.6-terra"})
        assert model.reasoning.control == "openai_effort"
        # "off" is Stimma's name for the rung; OpenAI calls it "none".
        assert model.reasoning.wire_levels["off"] == "none"
        assert set(model.reasoning.wire_levels.values()) == {
            "none", "low", "medium", "high", "xhigh", "max",
        }

    def test_quick_tasks_use_the_cheapest_rung(self):
        """Quick tasks spend the same plan quota as a chat turn."""
        model = chatgpt_model("p", {"id": "m"})
        assert model.reasoning.quick_task == "off"

    def test_reported_efforts_narrow_the_ladder(self):
        """If OpenAI ever reports efforts, the live list wins."""
        model = chatgpt_model("p", {
            "id": "m",
            "reasoning_efforts": ["low", "high"],
            "default_reasoning_effort": "high",
        })
        assert model.reasoning.levels == ["low", "high"]
        assert model.reasoning.default == "high"
        assert model.reasoning.mode == "required"  # no off rung reported

    def test_unknown_reported_efforts_fall_back_to_the_hardcoded_ladder(self):
        model = chatgpt_model("p", {"id": "gpt-5.6-terra", "reasoning_efforts": ["bogus"]})
        assert model.reasoning.levels == CHATGPT_REASONING_LEVELS

    def test_default_outside_the_ladder_is_corrected(self):
        model = chatgpt_model("p", {
            "id": "m", "reasoning_efforts": ["low", "high"],
            "default_reasoning_effort": "nonsense",
        })
        assert model.reasoning.default in model.reasoning.levels


class TestResolution:
    @pytest.mark.asyncio
    async def test_route_resolves_with_a_minted_token(self, chatgpt_provider):
        config = await llm_resolver.get_chat_llm_config("chatgpt-test:gpt-5.6-terra")

        assert config.provider_kind == "chatgpt"
        assert config.get_api_base() == chatgpt_auth.BACKEND_BASE_URL
        # The token is minted at resolution, never read from stored config.
        assert config.api_key == RESOLVED_TOKEN
        assert chatgpt_provider.api_key is None

    @pytest.mark.asyncio
    async def test_stored_provider_holds_no_key(self, chatgpt_provider):
        assert chatgpt_provider.api_key is None

    @pytest.mark.asyncio
    async def test_all_roles_can_resolve_the_route(self, chatgpt_provider):
        for role in ("agent", "quick_task", "tool_assistant"):
            config = await llm_resolver.get_chat_llm_config(
                "chatgpt-test:gpt-5.6-terra", role=role
            )
            assert config.provider_kind == "chatgpt"

    @pytest.mark.asyncio
    async def test_plan_limit_surfaces_instead_of_failing_over(
        self, chatgpt_provider, monkeypatch
    ):
        """A rate-limited plan must not silently move to a billed provider."""
        monkeypatch.setattr(
            chatgpt_auth, "get_access_token",
            _async_raise(chatgpt_auth.ChatGPTAuthError(
                "Your ChatGPT plan limit has been reached.",
                code="chatgpt_rate_limited", retry_after=120,
            )),
        )
        with pytest.raises(llm_resolver.LLMUnavailableError) as exc:
            await llm_resolver.get_chat_llm_config("chatgpt-test:gpt-5.6-terra")
        assert exc.value.code == "chatgpt_rate_limited"

    @pytest.mark.asyncio
    async def test_signed_out_route_reports_the_auth_reason(
        self, chatgpt_provider, monkeypatch
    ):
        monkeypatch.setattr(
            chatgpt_auth, "get_access_token",
            _async_raise(chatgpt_auth.ChatGPTAuthError(
                "You are not signed in to ChatGPT.",
                code="chatgpt_not_signed_in", relogin_required=True,
            )),
        )
        with pytest.raises(llm_resolver.LLMUnavailableError) as exc:
            await llm_resolver.get_chat_llm_config("chatgpt-test:gpt-5.6-terra")
        assert exc.value.code == "chatgpt_not_signed_in"


def _sse(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def _completed(output=None, usage=None, response_id="resp_1"):
    return {"type": "response.completed", "response": {
        "id": response_id, "output": output or [], "usage": usage or {},
    }}


def _text_reply(text="hi"):
    return _completed(output=[
        {"type": "message", "content": [{"type": "output_text", "text": text}]},
    ])


class _FakeStream:
    """Stand-in for httpx's streamed response context manager."""

    def __init__(self, status, body: bytes, url):
        self.status_code = status
        self._body = body
        self.request = httpx.Request("POST", url)
        self.text = body.decode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._body.decode().splitlines():
            yield line


def _stream_patch(monkeypatch, *, status=200, events=None, body=None, capture=None):
    def fake_stream(self, method, url, json=None, headers=None, **kwargs):
        if capture is not None:
            capture["url"] = url
            capture["body"] = json
            capture["headers"] = headers
            capture.setdefault("calls", []).append(headers.get("Authorization"))
        payload = body if body is not None else _sse(events or [_text_reply()])
        return _FakeStream(status, payload, url)

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)


class TestRequestShape:
    @pytest.mark.asyncio
    async def test_request_targets_the_codex_responses_endpoint(self, monkeypatch):
        seen = {}
        _stream_patch(monkeypatch, capture=seen)
        token = _access_token(account_id="acct_42")

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hello"}],
            api_key=token,
            api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )

        assert seen["url"] == "https://chatgpt.com/backend-api/codex/responses"
        # This backend rejects non-streaming requests outright.
        assert seen["body"]["stream"] is True
        # …and does not store responses, so there is nothing to continue from.
        assert seen["body"]["store"] is False
        assert "previous_response_id" not in seen["body"]
        assert seen["headers"]["ChatGPT-Account-Id"] == "acct_42"
        assert seen["headers"]["originator"] == "stimma"
        assert seen["headers"]["Accept"] == "text/event-stream"
        assert result.choices[0].message.content == "hi"

    @pytest.mark.asyncio
    async def test_tool_calls_survive_the_stream(self, monkeypatch):
        _stream_patch(monkeypatch, events=[
            {"type": "response.output_text.delta", "delta": "ignored"},
            _completed(output=[
                {"type": "function_call", "call_id": "call_1",
                 "name": "do_thing", "arguments": '{"a":1}'},
            ]),
        ])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "go"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )

        calls = result.choices[0].message.tool_calls
        assert len(calls) == 1
        assert calls[0].function.name == "do_thing"
        assert calls[0].function.arguments == '{"a":1}'
        assert result.choices[0].finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_usage_is_carried_through(self, monkeypatch):
        _stream_patch(monkeypatch, events=[_completed(
            output=[{"type": "message", "content": [{"type": "output_text", "text": "x"}]}],
            usage={"input_tokens": 11, "output_tokens": 4, "total_tokens": 15},
        )])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        assert result.usage.prompt_tokens == 11
        assert result.usage.completion_tokens == 4

    @pytest.mark.asyncio
    async def test_truncated_stream_fails_loudly(self, monkeypatch):
        """No terminal event means a cut-off turn, not an empty answer."""
        _stream_patch(monkeypatch, events=[
            {"type": "response.created", "response": {"id": "r", "output": []}},
            {"type": "response.output_text.delta", "delta": "partial"},
        ])

        with pytest.raises(llm_http.LLMStreamError):
            await llm_http.acompletion(
                model="gpt-5.6-terra",
                messages=[{"role": "user", "content": "hi"}],
                api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
                provider_kind="chatgpt",
            )

    @pytest.mark.asyncio
    async def test_stream_error_event_surfaces_its_message(self, monkeypatch):
        _stream_patch(monkeypatch, events=[
            {"type": "error", "error": {"message": "model overloaded"}},
        ])

        with pytest.raises(llm_http.LLMStreamError, match="model overloaded"):
            await llm_http.acompletion(
                model="gpt-5.6-terra",
                messages=[{"role": "user", "content": "hi"}],
                api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
                provider_kind="chatgpt",
            )

    @pytest.mark.asyncio
    async def test_response_failed_surfaces_its_message(self, monkeypatch):
        _stream_patch(monkeypatch, events=[
            {"type": "response.failed",
             "response": {"id": "r", "error": {"message": "content policy"}}},
        ])

        with pytest.raises(llm_http.LLMStreamError, match="content policy"):
            await llm_http.acompletion(
                model="gpt-5.6-terra",
                messages=[{"role": "user", "content": "hi"}],
                api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
                provider_kind="chatgpt",
            )

    @pytest.mark.asyncio
    async def test_done_sentinel_and_blank_lines_are_ignored(self, monkeypatch):
        body = (
            b": keep-alive comment\n\n"
            b"\n"
            + _sse([_text_reply("ok")])
            + b"data: [DONE]\n\n"
        )
        _stream_patch(monkeypatch, body=body)

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        assert result.choices[0].message.content == "ok"

    @pytest.mark.asyncio
    async def test_history_is_replayed_rather_than_continued(self, monkeypatch):
        seen = {}
        _stream_patch(monkeypatch, capture=seen)

        messages = [
            {"role": "user", "content": "call a tool"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": llm_http._encode_responses_tool_call_id("resp_prev", "call_1"),
                "type": "function",
                "function": {"name": "do_thing", "arguments": "{}"},
            }]},
            {
                "role": "tool",
                "tool_call_id": llm_http._encode_responses_tool_call_id("resp_prev", "call_1"),
                "content": "done",
            },
        ]
        await llm_http.acompletion(
            model="gpt-5.6-terra", messages=messages,
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )

        assert "previous_response_id" not in seen["body"]
        kinds = [item.get("type") or item.get("role") for item in seen["body"]["input"]]
        assert "function_call" in kinds and "function_call_output" in kinds
        output = next(i for i in seen["body"]["input"] if i.get("type") == "function_call_output")
        assert output["call_id"] == "call_1"

    @pytest.mark.asyncio
    async def test_401_refreshes_the_token_and_retries_once(self, monkeypatch):
        fresh = _access_token(account_id="acct_new")
        calls = []

        def fake_stream(self, method, url, json=None, headers=None, **kwargs):
            calls.append(headers["Authorization"])
            if len(calls) == 1:
                return _FakeStream(401, b"{}", url)
            return _FakeStream(200, _sse([_text_reply()]), url)

        monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
        monkeypatch.setattr(chatgpt_auth, "get_access_token", _async_return(fresh))

        await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(account_id="acct_stale"),
            api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )

        assert len(calls) == 2
        assert calls[1] == f"Bearer {fresh}"

    @pytest.mark.asyncio
    async def test_repeated_401_stops_after_one_retry(self, monkeypatch):
        calls = []

        def fake_stream(self, method, url, json=None, headers=None, **kwargs):
            calls.append(1)
            return _FakeStream(401, b"{}", url)

        monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
        monkeypatch.setattr(chatgpt_auth, "get_access_token", _async_return(_access_token()))

        with pytest.raises(httpx.HTTPStatusError):
            await llm_http.acompletion(
                model="gpt-5.6-terra",
                messages=[{"role": "user", "content": "hi"}],
                api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
                provider_kind="chatgpt",
            )
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_reasoning_effort_reaches_the_wire(self, monkeypatch):
        seen = {}
        _stream_patch(monkeypatch, capture=seen)
        await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
            extra_body={"reasoning_effort": "high"},
        )
        assert seen["body"]["reasoning"] == {"effort": "high"}


class TestApiKeyPathUnaffected:
    @pytest.mark.asyncio
    async def test_openai_api_key_route_still_stores_responses(self, monkeypatch):
        """The API-key OpenAI provider keeps its existing continuation behavior."""
        seen = {}

        async def fake_post(self, url, json=None, headers=None, **kwargs):
            seen["url"] = url
            seen["body"] = json
            seen["headers"] = headers
            return httpx.Response(
                200, json={"id": "r", "output": [], "usage": {}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test", api_base="https://api.openai.com/v1",
            provider_kind="openai",
        )

        assert seen["url"] == "https://api.openai.com/v1/responses"
        assert seen["body"]["store"] is True
        assert "originator" not in seen["headers"]
        assert "ChatGPT-Account-Id" not in seen["headers"]


class TestToolCallIdEncoding:
    def test_empty_response_id_keeps_the_plain_call_id(self):
        """A zero-length id would encode into something that fails to decode."""
        encoded = llm_http._encode_responses_tool_call_id("", "call_7")
        assert encoded == "call_7"
        assert llm_http._decode_responses_tool_call_id(encoded) is None

    def test_response_id_roundtrips(self):
        encoded = llm_http._encode_responses_tool_call_id("resp_9", "call_7")
        assert llm_http._decode_responses_tool_call_id(encoded) == ("resp_9", "call_7")


class TestErrorCopy:
    """A keyless, plan-funded route must not be described in key/billing terms."""

    def _error(self, status, url):
        response = httpx.Response(status, text="{}", request=httpx.Request("POST", url))
        return httpx.HTTPStatusError("boom", request=response.request, response=response)

    CHATGPT_URL = "https://chatgpt.com/backend-api/codex/responses"
    OPENAI_URL = "https://api.openai.com/v1/responses"

    def test_401_asks_for_sign_in_not_an_api_key(self):
        code, message = llm_http.classify_provider_http_error(
            self._error(401, self.CHATGPT_URL)
        )
        assert code == "chatgpt_not_signed_in"
        assert "API key" not in message

    def test_429_names_the_plan_limit(self):
        code, message = llm_http.classify_provider_http_error(
            self._error(429, self.CHATGPT_URL)
        )
        assert code == "chatgpt_rate_limited"
        assert "plan" in message.lower()

    def test_api_key_route_keeps_its_existing_copy(self):
        code, message = llm_http.classify_provider_http_error(
            self._error(401, self.OPENAI_URL)
        )
        assert code == "provider_invalid_key"
        assert "API key" in message

    def test_only_the_chatgpt_host_matches(self):
        """api.openai.com is the API-key route and must not be reclassified."""
        assert llm_http._is_chatgpt_backend_url(self.CHATGPT_URL)
        assert not llm_http._is_chatgpt_backend_url(self.OPENAI_URL)
        assert not llm_http._is_chatgpt_backend_url("https://evil.test/chatgpt.com")


class TestUnsupportedParams:
    """The Codex backend 400s on Responses fields api.openai.com accepts."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["max_output_tokens", "temperature", "top_p"])
    async def test_rejected_fields_are_stripped(self, monkeypatch, field):
        seen = {}
        _stream_patch(monkeypatch, capture=seen)

        await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
            max_tokens=512,
            extra_body={"temperature": 0.4, "top_p": 0.9},
        )
        assert field not in seen["body"]

    @pytest.mark.asyncio
    async def test_api_key_route_still_sends_max_output_tokens(self, monkeypatch):
        """Only the plan-funded route is restricted; the API-key one is not."""
        seen = {}

        async def fake_post(self, url, json=None, headers=None, **kwargs):
            seen["body"] = json
            return httpx.Response(
                200, json={"id": "r", "output": [], "usage": {}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key="sk-test", api_base="https://api.openai.com/v1",
            provider_kind="openai",
            max_tokens=512,
        )
        assert seen["body"]["max_output_tokens"] == 512


class TestStreamReassembly:
    """The terminal event carries the envelope; items carry the content.

    Live Codex streams send a `response.completed` whose `output` is empty and
    deliver the actual message via `response.output_item.done`. Trusting only
    the terminal event yields a silent empty reply.
    """

    @pytest.mark.asyncio
    async def test_output_items_are_collected_when_terminal_is_empty(self, monkeypatch):
        _stream_patch(monkeypatch, events=[
            {"type": "response.output_item.done", "item": {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello there"}],
            }},
            {"type": "response.completed", "response": {
                "id": "resp_1", "output": [], "usage": {"output_tokens": 6},
            }},
        ])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        assert result.choices[0].message.content == "Hello there"
        assert result.usage.completion_tokens == 6

    @pytest.mark.asyncio
    async def test_streamed_tool_call_items_are_collected(self, monkeypatch):
        _stream_patch(monkeypatch, events=[
            {"type": "response.output_item.done", "item": {
                "type": "function_call", "call_id": "call_9",
                "name": "search", "arguments": '{"q":"x"}',
            }},
            {"type": "response.completed", "response": {"id": "r", "output": [], "usage": {}}},
        ])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "go"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        calls = result.choices[0].message.tool_calls
        assert calls[0].function.name == "search"
        assert result.choices[0].finish_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_populated_terminal_event_wins_over_items(self, monkeypatch):
        """When the envelope does carry output, it is authoritative."""
        _stream_patch(monkeypatch, events=[
            {"type": "response.output_item.done", "item": {
                "type": "message",
                "content": [{"type": "output_text", "text": "partial"}],
            }},
            _completed(output=[
                {"type": "message", "content": [{"type": "output_text", "text": "final"}]},
            ]),
        ])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        assert result.choices[0].message.content == "final"

    @pytest.mark.asyncio
    async def test_text_deltas_are_the_last_resort(self, monkeypatch):
        """Text arrived but no item ever completed."""
        _stream_patch(monkeypatch, events=[
            {"type": "response.output_text.delta", "delta": "par"},
            {"type": "response.output_text.delta", "delta": "tial"},
            {"type": "response.completed", "response": {"id": "r", "output": [], "usage": {}}},
        ])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        assert result.choices[0].message.content == "partial"

    @pytest.mark.asyncio
    async def test_reasoning_item_is_preserved(self, monkeypatch):
        _stream_patch(monkeypatch, events=[
            {"type": "response.output_item.done", "item": {
                "type": "reasoning", "summary": [{"text": "thought about it"}],
            }},
            {"type": "response.output_item.done", "item": {
                "type": "message",
                "content": [{"type": "output_text", "text": "answer"}],
            }},
            {"type": "response.completed", "response": {"id": "r", "output": [], "usage": {}}},
        ])

        result = await llm_http.acompletion(
            model="gpt-5.6-terra",
            messages=[{"role": "user", "content": "hi"}],
            api_key=_access_token(), api_base=chatgpt_auth.BACKEND_BASE_URL,
            provider_kind="chatgpt",
        )
        message = result.choices[0].message
        assert message.content == "answer"
        assert message.reasoning_content == "thought about it"


class TestCatalogFiltering:
    """The plan lists more models than Stimma exposes."""

    @pytest.mark.asyncio
    async def test_sync_keeps_only_supported_models(self, monkeypatch, tmp_path):
        import routes.models as models_route

        live_catalog = [
            {"id": "gpt-5.6-terra", "name": "GPT-5.6-Terra"},
            {"id": "gpt-5.6-sol", "name": "GPT-5.6-Sol"},
            {"id": "gpt-5.5", "name": "GPT-5.5"},
            {"id": "gpt-5.4-mini", "name": "GPT-5.4-Mini"},
            {"id": "gpt-5.3-codex-spark", "name": "GPT-5.3-Codex-Spark"},
        ]
        monkeypatch.setattr(
            chatgpt_auth, "fetch_models", _async_return(live_catalog)
        )
        saved = {}
        settings = SimpleNamespace(llm_providers=[])
        monkeypatch.setattr(models_route, "get_settings", lambda: settings)
        monkeypatch.setattr(
            models_route, "_save_providers",
            lambda providers: saved.update(providers=providers),
        )

        provider = await models_route._sync_chatgpt_provider(_access_token())

        assert [m.model_id for m in provider.models] == ["gpt-5.6-terra", "gpt-5.6-sol"]
        assert saved["providers"] == [provider]

    @pytest.mark.asyncio
    async def test_plan_with_no_supported_models_is_rejected(self, monkeypatch):
        """An older-only plan must not connect with an empty model list."""
        import routes.models as models_route
        from fastapi import HTTPException

        monkeypatch.setattr(
            chatgpt_auth, "fetch_models",
            _async_return([{"id": "gpt-5.4", "name": "GPT-5.4"}]),
        )
        monkeypatch.setattr(
            models_route, "get_settings", lambda: SimpleNamespace(llm_providers=[])
        )

        with pytest.raises(HTTPException) as exc:
            await models_route._sync_chatgpt_provider(_access_token())
        assert exc.value.status_code == 400

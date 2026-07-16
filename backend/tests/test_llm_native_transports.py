"""Wire-contract tests for branded providers that are not Chat Completions."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from agent.v2.conversation import _item_to_message
from agent.hitl import HumanActionRequired
from agent.v2.service import (
    _pause_for_ask_user,
    _pause_for_permission,
    _provider_state_metadata,
)
from llm import (
    _malformed_tool_retry_kwargs,
    _normalize_parallel_tool_history,
    _normalize_response,
)
from llm_http import (
    _Obj,
    _anthropic_to_chat,
    _decode_responses_tool_call_id,
    _encode_responses_tool_call_id,
    _provider_http_error,
    _responses_to_chat,
    _to_anthropic_request,
    _to_responses_request,
)


TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_weather",
        "description": "Look up weather",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]


def test_openai_responses_request_uses_responses_reasoning_and_flat_tools():
    body = _to_responses_request(
        "gpt-5.6-terra",
        [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "Weather?"}],
        {"tools": TOOLS, "max_tokens": 128, "extra_body": {"reasoning_effort": "high"}},
    )

    assert body["model"] == "gpt-5.6-terra"
    assert body["instructions"] == "Be concise."
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 128
    assert body["tools"][0]["name"] == "lookup_weather"
    assert "function" not in body["tools"][0]


def test_openai_responses_tool_id_preserves_stateful_continuation():
    encoded = _encode_responses_tool_call_id("resp_123", "call_456")
    encoded_second = _encode_responses_tool_call_id("resp_123", "call_789")
    assert _decode_responses_tool_call_id(encoded) == ("resp_123", "call_456")

    body = _to_responses_request(
        "gpt-5.6-terra",
        [
            {"role": "user", "content": "Weather?"},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": encoded, "type": "function",
                "function": {"name": "lookup_weather", "arguments": '{"city":"Boston"}'},
            }]},
            {"role": "tool", "tool_call_id": encoded, "content": '{"temperature":72}'},
            {"role": "user", "name": "_stimma_context", "content": "Loaded skill 'Tool Selection'."},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": encoded_second, "type": "function",
                "function": {"name": "lookup_weather", "arguments": '{"city":"Paris"}'},
            }]},
            {"role": "tool", "tool_call_id": encoded_second, "content": '{"temperature":68}'},
            {"role": "user", "name": "_stimma_context", "content": "Loaded skill 'Prompt Engineering'."},
        ],
        {"tools": TOOLS},
    )

    assert body["previous_response_id"] == "resp_123"
    assert body["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_456",
            "output": '{"temperature":72}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_789",
            "output": '{"temperature":68}',
        },
        {"role": "user", "content": "Loaded skill 'Tool Selection'."},
        {"role": "user", "content": "Loaded skill 'Prompt Engineering'."},
    ]


def test_openai_response_normalizes_tool_calls_usage_and_reasoning():
    raw = _responses_to_chat({
        "id": "resp_123",
        "model": "gpt-5.6-terra",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Need weather."}]},
            {"type": "function_call", "call_id": "call_456", "name": "lookup_weather", "arguments": '{"city":"Boston"}'},
        ],
        "usage": {
            "input_tokens": 10, "output_tokens": 7, "total_tokens": 17,
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    }, "gpt-5.6-terra")
    normalized = _normalize_response(raw)

    assert normalized.thinking == "Need weather."
    assert normalized.tool_calls[0].name == "lookup_weather"
    assert normalized.usage.reasoning_tokens == 3
    assert _decode_responses_tool_call_id(normalized.tool_calls[0].id) == ("resp_123", "call_456")


def test_anthropic_native_request_replays_exact_signed_blocks():
    signed_blocks = [
        {"type": "thinking", "thinking": "Need weather.", "signature": "opaque-signature"},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup_weather", "input": {"city": "Boston"}},
    ]
    body = _to_anthropic_request(
        "claude-opus-4-8",
        [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Weather?"},
            {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "toolu_1", "type": "function",
                    "function": {"name": "lookup_weather", "arguments": '{"city":"Boston"}'},
                }],
                "_stimma_provider_state": {"kind": "anthropic_message", "content": signed_blocks},
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": '{"temperature":72}'},
        ],
        {
            "tools": TOOLS,
            "max_tokens": 256,
            "extra_body": {
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": "high"},
            },
        },
    )

    assert body["system"] == [{"type": "text", "text": "Be concise."}]
    assert body["messages"][1]["content"] is signed_blocks
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert body["tools"][0]["input_schema"]["required"] == ["city"]


def test_parallel_native_batch_moves_all_tool_results_before_skill_context():
    calls = [
        {
            "id": call_id, "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }
        for call_id, name in (("call_1", "skill_one"), ("call_2", "skill_two"))
    ]
    state = {"kind": "openai_chat_tool_batch", "tool_calls": calls}
    messages = [
        {"role": "user", "content": "Use both skills."},
        {
            "role": "assistant", "content": None, "tool_calls": [calls[0]],
            "_stimma_provider_state": state,
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":1}'},
        {"role": "user", "name": "_stimma_context", "content": "First skill context."},
        {
            "role": "assistant", "content": None, "tool_calls": [calls[1]],
            "_stimma_provider_state": state,
        },
        {"role": "tool", "tool_call_id": "call_2", "content": '{"ok":2}'},
        {"role": "user", "name": "_stimma_context", "content": "Second skill context."},
    ]

    normalized = _normalize_parallel_tool_history(messages)

    assert normalized[1]["tool_calls"] == calls
    assert [message["role"] for message in normalized[2:]] == ["tool", "tool", "user", "user"]
    assert [message.get("tool_call_id") for message in normalized[2:4]] == ["call_1", "call_2"]


def test_plain_parallel_chat_response_gets_replay_batch_state():
    raw = _Obj({
        "model": "grok-test",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {
                        "id": "call_1", "type": "function",
                        "function": {"name": "one", "arguments": "{}"},
                    },
                    {
                        "id": "call_2", "type": "function",
                        "function": {"name": "two", "arguments": "{}"},
                    },
                ],
            },
        }],
        "usage": {},
    })

    response = _normalize_response(raw)

    assert response.provider_state == {
        "kind": "openai_chat_tool_batch",
        "tool_calls": [
            {
                "id": "call_1", "type": "function",
                "function": {"name": "one", "arguments": "{}"},
            },
            {
                "id": "call_2", "type": "function",
                "function": {"name": "two", "arguments": "{}"},
            },
        ],
    }


@pytest.mark.parametrize(
    ("extra_body", "expected"),
    [
        ({"reasoning_effort": "medium"}, {"reasoning_effort": "low"}),
        ({"reasoning": {"effort": "high"}}, {"reasoning": {"effort": "low"}}),
    ],
)
def test_malformed_tool_call_retry_preserves_tools_and_lowers_effort(extra_body, expected):
    raw = _Obj({
        "choices": [{
            "finish_reason": "function_call_filter: MALFORMED_FUNCTION_CALL",
            "message": {"role": "assistant"},
        }],
    })
    kwargs = {"tools": TOOLS, "extra_body": extra_body, "model": "test-model"}

    retry = _malformed_tool_retry_kwargs(raw, kwargs)

    assert retry is not None
    assert retry["tools"] is TOOLS
    assert retry["extra_body"] == expected
    assert kwargs["extra_body"] == extra_body


def test_anthropic_response_keeps_native_state_for_persistence():
    blocks = [
        {"type": "thinking", "thinking": "Need weather.", "signature": "opaque-signature"},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup_weather", "input": {"city": "Boston"}},
    ]
    normalized = _normalize_response(_anthropic_to_chat({
        "id": "msg_1", "model": "claude-opus-4-8", "content": blocks,
        "stop_reason": "tool_use", "usage": {"input_tokens": 12, "output_tokens": 8},
    }, "claude-opus-4-8"))

    assert normalized.thinking == "Need weather."
    assert normalized.provider_state == {"kind": "anthropic_message", "content": blocks}
    assert normalized.tool_calls[0].arguments == '{"city": "Boston"}'


def test_google_tool_signature_is_preserved_as_opaque_batch_state():
    normalized = _normalize_response(_Obj({
        "model": "gemini-3.5-flash",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "lookup_weather", "arguments": '{"city":"Boston"}'},
                    "extra_content": {"google": {"thought_signature": "opaque-signature"}},
                }],
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }))

    assert normalized.tool_calls[0].extra_content == {
        "google": {"thought_signature": "opaque-signature"}
    }
    assert normalized.provider_state == {
        "kind": "openai_chat_tool_batch",
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "lookup_weather", "arguments": '{"city":"Boston"}'},
            "extra_content": {"google": {"thought_signature": "opaque-signature"}},
        }],
    }


def test_persisted_anthropic_tool_item_reconstructs_whole_provider_batch():
    blocks = [
        {"type": "thinking", "thinking": "Two lookups.", "signature": "opaque"},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup_weather", "input": {"city": "Boston"}},
        {"type": "tool_use", "id": "toolu_2", "name": "lookup_weather", "input": {"city": "Paris"}},
    ]
    item = SimpleNamespace(
        item_type="tool_call", tool_args='{"city":"Boston"}', tool_call_id="toolu_1",
        tool_name="lookup_weather",
        item_metadata=json.dumps({"llm_provider_state": {"kind": "anthropic_message", "content": blocks}}),
    )
    message = _item_to_message(item)

    assert message["_stimma_provider_state"]["content"] == blocks
    assert [call["id"] for call in message["tool_calls"]] == ["toolu_1", "toolu_2"]


def test_provider_http_error_message_never_contains_supplier_details():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "model gpt-secret is unsupported; see provider.example/docs"}},
    )
    error = _provider_http_error(response, provider="OpenAI")

    assert str(error) == "The AI provider rejected the request (HTTP 400)."
    assert "openai.com" not in str(error)
    assert "gpt-secret" not in str(error)


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        item.id = len(self.added) + 1
        item.created_at = datetime.now(timezone.utc)
        self.added.append(item)

    async def commit(self):
        return None


class _FakeWsManager:
    async def broadcast(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_permission_pause_keeps_provider_state_for_resumed_tool_item():
    provider_state = {
        "kind": "anthropic_message",
        "content": [{"type": "thinking", "signature": "opaque"}],
    }
    chat = SimpleNamespace(id=7, generation_settings=None)

    with pytest.raises(HumanActionRequired):
        await _pause_for_permission(
            "bash", '{"command":"pwd"}', "toolu_1", [], 3,
            chat, _FakeSession(), _FakeWsManager(),
            llm_provider_state=provider_state,
        )

    pending = json.loads(chat.generation_settings)["_v2_pending"]
    assert pending["llm_provider_state"] == provider_state
    assert json.loads(_provider_state_metadata(provider_state)) == {
        "llm_provider_state": provider_state,
    }


@pytest.mark.asyncio
async def test_ask_pause_keeps_provider_state_on_remaining_batch_calls():
    provider_state = {"kind": "openai_chat_tool_batch", "tool_calls": []}
    remaining = [{
        "fn_name": "bash",
        "fn_arguments": '{"command":"pwd"}',
        "tool_call_id": "call_2",
        "llm_provider_state": provider_state,
    }]
    chat = SimpleNamespace(id=8, generation_settings=None)

    await _pause_for_ask_user(
        chat, _FakeSession(), _FakeWsManager(), "call_1", 4,
        {"question": "Continue?"}, remaining,
    )

    pending = json.loads(chat.generation_settings)["_v2_ask_pending"]
    assert pending["remaining_tool_calls"][0]["llm_provider_state"] == provider_state

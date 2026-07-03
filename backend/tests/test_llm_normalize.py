"""Tests for llm._normalize_response provider-quirk handling."""

from llm import FinishReason, _normalize_response
from llm_http import _Obj


def test_normalize_tool_call_response_without_content_key():
    # Some providers (e.g. MiniMax M3) omit the `content` key entirely on
    # tool-call turns; _Obj only creates attributes for keys present in the
    # JSON, so normalization must not assume message.content exists.
    raw = _Obj({
        "model": "minimax-m3",
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "run_code", "arguments": "{}"},
                }],
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })

    resp = _normalize_response(raw)

    assert resp.content == ""
    assert resp.finish_reason == FinishReason.TOOL_CALLS
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "run_code"


def test_normalize_reasoning_only_response_without_content_key():
    raw = _Obj({
        "model": "minimax-m3",
        "choices": [{
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "reasoning_content": "thinking about the request",
            },
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })

    resp = _normalize_response(raw)

    assert resp.content == ""
    assert resp.thinking == "thinking about the request"

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


def _response(message, finish_reason="stop"):
    return _normalize_response(_Obj({
        "model": "test-reasoner",
        "choices": [{"finish_reason": finish_reason, "message": message}],
    }))


def test_template_prefilled_reasoning_is_separated_from_answer():
    response = _response({"content": "Let me improve this prompt.</think>A moonlit forest."})
    assert response.content == "A moonlit forest."
    assert response.thinking == "Let me improve this prompt."


def test_unfinished_reasoning_is_not_an_answer():
    response = _response({"content": "<think>Still planning the prompt"}, "length")
    assert response.content == ""
    assert response.thinking == "Still planning the prompt"


def test_nested_and_multiple_reasoning_blocks_are_separated():
    response = _response({"content": "<think>one<analysis>two</analysis>three</think>answer<think>four</think>"})
    assert response.content == "answer"
    assert response.thinking == "onetwothreefour"


def test_split_reasoning_fields_preserve_both_parts():
    response = _response({"reasoning_content": "First thought", "content": "Last thought</think>answer"})
    assert response.content == "answer"
    assert response.thinking == "First thought\nLast thought"


def test_reasoning_formatting_changes_never_promote_it_to_answer():
    response = _response({"reasoning_content": "Plan.\n\n\nMore planning.<|im_end|>"})
    assert response.content == ""


def test_answer_after_explicit_reasoning_boundary_is_recovered():
    response = _response({"reasoning_content": "<think>plan</think>answer"})
    assert response.content == "answer"
    assert response.thinking == "plan"


async def test_text_completion_never_falls_back_to_reasoning(monkeypatch):
    import llm
    from config import LLMEndpointConfig

    async def completion(*args, **kwargs):
        return llm.LLMResponse(thinking="Plan.\n\n\nMore planning.<|im_end|>")

    monkeypatch.setattr(llm, "llm_completion", completion)
    assert await llm.llm_complete_text(LLMEndpointConfig(model="test"), []) == ""


async def test_prompt_text_completion_returns_only_normalized_answer(monkeypatch):
    import llm
    from config import LLMEndpointConfig

    async def completion(*args, **kwargs):
        return _response({"content": "Plan the improvement.</think>A moonlit forest."})

    monkeypatch.setattr(llm, "llm_completion", completion)
    assert await llm.llm_complete_text(LLMEndpointConfig(model="test"), []) == "A moonlit forest."


def test_unclosed_tag_in_reasoning_field_does_not_promote_its_prefix():
    response = _response({"reasoning_content": "Planning first<think>more planning"})
    assert response.content == ""


def test_empty_reasoning_block_can_still_delimit_an_answer():
    response = _response({"reasoning_content": "<think></think>answer"})
    assert response.content == "answer"
    assert response.thinking is None

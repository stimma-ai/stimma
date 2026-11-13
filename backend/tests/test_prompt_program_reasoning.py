"""Every model call Fluent makes asks the endpoint for no reasoning, on the wire.

The calls go through the shared LLM layer with a local OpenAI-compatible model whose
reasoning control is profiled (as Settings records it), and the request each sends is
checked: the model's own off switch is set, nothing turns template thinking on, and the
reply budget is bounded.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from config import LLMEndpointConfig
from llm_http import _Obj


def _config(model: str) -> LLMEndpointConfig:
    return LLMEndpointConfig(
        url="http://local-model:8000/v1", model=model, provider_kind="local",
        content_policy_enabled=False, detected_runtime="vLLM 0.26",
        reasoning_control="openai_effort", reasoning_default="high", reasoning_quick_task="off",
        reasoning_level="high", reasoning_wire_levels={"off": "none", "high": "high"},
    )


@pytest.fixture(params=["glm-5.3-flash", "qwen36-fast"])
def wire(request, monkeypatch):
    """The requests Fluent sends, with the model answering `answer` (set per test)."""
    import llm
    import llm_resolver

    cfg = _config(request.param)
    sent: List[Dict[str, Any]] = []
    state = {"answer": "{}", "tool": None}

    async def raw(**kwargs):
        sent.append(kwargs)
        message: Dict[str, Any] = {"content": state["answer"]}
        if state["tool"] is not None and kwargs.get("tools"):
            message = {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": state["tool"][0], "arguments": json.dumps(state["tool"][1])}}]}
        return _Obj({"model": cfg.model, "choices": [{"finish_reason": "stop", "message": message}]})

    async def effective(role, project_id=None):
        return cfg

    monkeypatch.setattr(llm, "_raw_acompletion", raw)
    monkeypatch.setattr(llm_resolver, "get_effective_llm_config", effective)
    return sent, state


def _asked_for_no_reasoning(call: Dict[str, Any], most: int = 2000) -> None:
    body = call.get("extra_body") or {}
    assert body.get("reasoning_effort") == "none", body
    assert (body.get("chat_template_kwargs") or {}).get("enable_thinking") is not True, body
    assert "thinking" not in call
    assert 0 < call["max_tokens"] <= most


async def test_the_shared_fluent_call_asks_for_no_reasoning(wire):
    from prompt_programs import program as prep

    sent, _ = wire
    assert await prep.ask_model([{"role": "user", "content": "x"}], None) == "{}"
    _asked_for_no_reasoning(sent[-1])


async def test_a_reading_that_reasons_anyway_is_not_asked_again_with_more_room(wire, monkeypatch):
    import llm
    from prompt_programs import program as prep

    sent, _ = wire

    async def reasons(**kwargs):
        sent.append(kwargs)
        return _Obj({"model": "m", "choices": [{"finish_reason": "length", "message": {
            "content": "", "reasoning_content": "a long trace"}}]})

    monkeypatch.setattr(llm, "_raw_acompletion", reasons)
    assert await prep.ask_model([{"role": "user", "content": "x"}], None, 300) == ""
    assert [c["max_tokens"] for c in sent] == [300]


async def test_the_slot_reader_asks_for_no_reasoning(wire):
    from prompt_programs import program as prep
    from prompt_programs import reader
    from prompt_programs.slots import parse

    sent, state = wire
    state["answer"] = json.dumps({"slots": [{"n": 1, "kind": "light", "label": "Light", "lead": ", lit by",
                                             "light": {"list": "", "examples": ["lamp glow", "window light", "dusk"]}}],
                                  "lists": []})
    await reader.read(parse("a kitchen, lit by <light>"), ask=prep.ask_model, project_id=None, model="m", cache=None)
    assert sent
    for call in sent:
        _asked_for_no_reasoning(call)


async def test_narrowing_asks_for_no_reasoning(wire):
    from prompt_programs import program as prep
    from prompt_programs.narrow import subset
    from prompt_programs.vocab import AGE_LIST, vocabulary

    sent, state = wire
    leaf = vocabulary().leaves[AGE_LIST]
    state["answer"] = json.dumps([leaf.eligible()[-1].text])
    assert await subset(leaf, "elderly", None, prep.ask_model, None, "his age") is not None
    _asked_for_no_reasoning(sent[-1])


async def test_suggest_and_add_ask_for_no_reasoning(wire):
    from prompt_programs import suggest as sg

    sent, state = wire
    state["answer"] = json.dumps({"vary": [], "add": []})
    await sg.suggest("dorm room with a young man")
    _asked_for_no_reasoning(sent[-1])
    state["answer"] = json.dumps({"prompt": "dorm room with a young man, lit by <light>"})
    await sg.add("dorm room with a young man", "light")
    _asked_for_no_reasoning(sent[-1])


async def test_the_variant_writer_asks_for_no_reasoning(wire):
    from prompt_programs import variants as V

    sent, state = wire
    state["answer"] = json.dumps({"rejected": [], "variants": [{"n": 1, "text": "lamplight from a brass lamp", "idea": ""}]})
    slot = V.Slot(words="lighting", prompt="a kitchen, lit by <lighting>", span=(18, 28), kind="light", category="lighting")
    batches = await V.write_first(slot, V.list_seeds([]), ask=V.ask_writer)
    assert batches and sent
    for call in sent:
        _asked_for_no_reasoning(call, V.WRITE_TOKENS)


async def test_the_judge_asks_for_no_reasoning(wire):
    import asyncio

    from prompt_programs.llm_judge import LlmJudge

    sent, state = wire
    state["answer"] = "1. ok"
    import llm_resolver
    judge = LlmJudge(asyncio.get_running_loop(), await llm_resolver.get_effective_llm_config("tool_assistant"))
    await judge._call(("a man", "a 70-year-old man"), [("a man", "a [Age] man", "Age", "his age", "70-year-old")])
    _asked_for_no_reasoning(sent[-1])

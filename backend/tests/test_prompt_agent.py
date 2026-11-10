"""Tests for the prompt-editor mini-agent endpoint and tool schemas."""
import json
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch, AsyncMock

import httpx

from prompt_agent_tools import TOOL_SCHEMAS, TOOL_NAMES


# --- Tool schema shape ------------------------------------------------------

def test_tool_schemas_are_wellformed():
    assert len(TOOL_SCHEMAS) == len(TOOL_NAMES)  # no duplicate names
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] and isinstance(fn["name"], str)
        assert fn["description"]
        params = fn["parameters"]
        assert params["type"] == "object"
        assert isinstance(params["properties"], dict)
        # every required key must be a declared property
        for req in params.get("required", []):
            assert req in params["properties"], f"{fn['name']}: required '{req}' not in properties"
        # Strict function-calling endpoints reject array-valued or missing types.
        # Every property must declare a single string "type".
        for pname, p in params["properties"].items():
            assert "type" in p, f"{fn['name']}.{pname} has no type"
            assert isinstance(p["type"], str), f"{fn['name']}.{pname} type must be a string, got {p['type']!r}"
            if "enum" in p:
                assert p["type"] == "string", f"{fn['name']}.{pname} enum must be typed string"


def test_core_tools_present():
    for name in ("set_prompt", "edit_prompt", "set_parameter", "search_loras",
                 "set_auto_markers", "flip_image", "generate"):
        assert name in TOOL_NAMES


def test_notes_tools_present():
    # Per-tool Instructions write tools (TOOLVIEW_INTELLIGENCE #1). Memory was
    # folded into Instructions for this feature — those tools must NOT exist here.
    for name in ("set_instructions", "edit_instructions"):
        assert name in TOOL_NAMES
    for name in ("set_memory", "edit_memory"):
        assert name not in TOOL_NAMES


def test_prompting_tools_mirror_the_prompt_menu():
    # The person's controls: how the prompt is read, Detail level, a card's ticks. The
    # old toggle (with its no-op vary_prompt) is gone, and no schema names the feature.
    assert {"set_prompting", "set_choice"} <= TOOL_NAMES
    assert "set_prompt_option" not in TOOL_NAMES
    by_name = {t["function"]["name"]: t["function"] for t in TOOL_SCHEMAS}
    props = by_name["set_prompting"]["parameters"]["properties"]
    assert props["mode"]["enum"] == ["vary", "direct", "raw"]
    assert props["detail"]["enum"] == ["yours", "medium", "high"]
    assert "fluent" not in json.dumps(TOOL_SCHEMAS).lower()
    from prompts import get_prompt
    sp = get_prompt("prompt_enhancement", "agent_system_prompt")
    assert "{{name}}" in sp and "set_choice" in sp and "prompt_choices" in sp


def test_agent_system_prompt_has_notes_principle():
    from prompts import get_prompt
    sp = get_prompt("prompt_enhancement", "agent_system_prompt")
    assert sp, "agent_system_prompt must be configured"
    assert "INSTRUCTIONS" in sp
    assert "set_instructions" in sp


# --- Endpoint wiring (LLM mocked) ------------------------------------------

@dataclass
class _FakeToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class _FakeResponse:
    content: str = ""
    tool_calls: List[_FakeToolCall] = field(default_factory=list)
    thinking: str | None = None


class _FakeConfig:
    max_context_tokens = 200_000

    def get_model(self):
        return "fake-model"

    def get_api_base(self):
        return "http://fake-endpoint/v1"


async def test_agent_step_returns_tool_calls():
    from routes.prompt_enhancement import agent_step, AgentStepRequest
    fake = _FakeResponse(content="", tool_calls=[_FakeToolCall("c1", "set_parameter",
                                                               '{"name": "guidance", "value": 2.0}')])
    with patch("llm_resolver.get_effective_llm_config", new=AsyncMock(return_value=_FakeConfig())), \
         patch("agent.v2.llm_options.agent_llm_options", return_value={}), \
         patch("llm.llm_completion", new=AsyncMock(return_value=fake)) as mock_llm:
        result = await agent_step(AgentStepRequest(
            conversation_history=[{"role": "user", "content": "set guidance to 2.0"}],
            state_context={"parameters": {"guidance": 3.5},
                           "parameter_schema": {"guidance": {"type": "number", "min": 1, "max": 10}}},
        ))
    assert [(tc.id, tc.name, tc.arguments) for tc in result.tool_calls] == [
        ("c1", "set_parameter", '{"name": "guidance", "value": 2.0}')]
    # Tools were advertised to the model.
    assert mock_llm.call_args.kwargs["tools"] is TOOL_SCHEMAS
    sent = mock_llm.call_args.kwargs["messages"]
    # Exactly one system message (the stable prompt) — endpoints reject a second.
    assert sent[0]["role"] == "system"
    assert sum(1 for m in sent if m.get("role") == "system") == 1
    # Live state rides as a <system-reminder> on the last user message (cache-stable).
    last_user = [m for m in sent if m.get("role") == "user"][-1]
    assert "<system-reminder>" in last_user["content"]
    assert "guidance" in last_user["content"]


async def test_agent_step_returns_text_reply():
    from routes.prompt_enhancement import agent_step, AgentStepRequest
    fake = _FakeResponse(content="Done — made the lighting more dramatic.", tool_calls=[])
    with patch("llm_resolver.get_effective_llm_config", new=AsyncMock(return_value=_FakeConfig())), \
         patch("agent.v2.llm_options.agent_llm_options", return_value={}), \
         patch("llm.llm_completion", new=AsyncMock(return_value=fake)):
        result = await agent_step(AgentStepRequest(
            conversation_history=[{"role": "user", "content": "make it more cinematic"}],
            state_context={"prompt": "a cabin"},
        ))
    assert result.tool_calls == []
    assert "dramatic" in result.message


def test_prompt_agent_budget_counts_tools_and_compacts_short_window():
    from agent.v2.conversation import _estimate_tokens
    from prompts import get_prompt
    from routes.prompt_enhancement import _prepare_prompt_agent_request

    history = []
    for turn in range(8):
        history.extend([
            {"role": "user", "content": f"turn-{turn} " + "u" * 4000},
            {"role": "assistant", "content": "a" * 2000},
        ])

    messages, max_tokens = _prepare_prompt_agent_request(
        conversation_history=history,
        system_prompt=get_prompt("prompt_enhancement", "agent_system_prompt"),
        reminders=["<system-reminder>{\"seed\": 1}</system-reminder>"],
        tools=TOOL_SCHEMAS,
        max_context_tokens=32_768,
    )

    estimated = _estimate_tokens(messages)["total"]
    tools_overhead = len(json.dumps(TOOL_SCHEMAS)) // 4
    # Allow a small margin for the timestamp injected after budgeting.
    assert estimated + tools_overhead + max_tokens <= int(32_768 * 0.80) + 100
    assert max_tokens == 8_192
    assert any("Earlier turns were omitted" in str(m.get("content")) for m in messages)
    assert "turn-7" in messages[-2]["content"] or "turn-7" in messages[-1]["content"]


def test_prompt_agent_volatile_state_stays_on_final_user_message():
    from prompts import get_prompt
    from routes.prompt_enhancement import _prepare_prompt_agent_request

    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "second"},
    ]
    common = {
        "conversation_history": history,
        "system_prompt": get_prompt("prompt_enhancement", "agent_system_prompt"),
        "tools": TOOL_SCHEMAS,
        "max_context_tokens": 128_000,
    }
    first, first_max = _prepare_prompt_agent_request(
        **common,
        reminders=["<system-reminder>{\"seed\": 1}</system-reminder>"],
    )
    second, second_max = _prepare_prompt_agent_request(
        **common,
        reminders=["<system-reminder>{\"seed\": 2}</system-reminder>"],
    )

    assert first_max == second_max
    assert first[:-1] == second[:-1]
    assert '"seed": 1' in first[-1]["content"]
    assert '"seed": 2' in second[-1]["content"]


def _prepared_history(history):
    from prompts import get_prompt
    from routes.prompt_enhancement import _prepare_prompt_agent_request

    messages, _ = _prepare_prompt_agent_request(
        conversation_history=history,
        system_prompt=get_prompt("prompt_enhancement", "agent_system_prompt"),
        reminders=["<system-reminder>{}</system-reminder>"],
        tools=TOOL_SCHEMAS,
        max_context_tokens=128_000,
    )
    return messages[1:]


def test_hand_edit_is_written_into_the_turn_it_preceded():
    sent = _prepared_history([
        {"role": "user", "content": "write a lighthouse"},
        {"role": "assistant", "content": "wrote prompt"},
        {
            "role": "user",
            "content": "make it dramatic",
            "screen_edits": [{"field": "prompt", "before": "a lighthouse", "after": "a cat"}],
        },
    ])

    last = sent[-1]["content"]
    assert 'Before: "a lighthouse"' in last
    assert 'Now: "a cat"' in last
    assert last.endswith("make it dramatic")
    # Providers reject unknown message fields.
    assert all("screen_edits" not in message for message in sent)


def test_clearing_the_prompt_tells_the_model_not_to_restore_it():
    sent = _prepared_history([
        {
            "role": "user",
            "content": "use soft morning light",
            "screen_edits": [{"field": "prompt", "before": "a lighthouse", "after": ""}],
        },
    ])

    note = sent[-1]["content"]
    assert "emptied the prompt" in note
    assert "Write only what this message asks for" in note
    # Quoting the old text back would hand the model what it must not restore.
    assert "a lighthouse" not in note


def test_hand_edit_note_stays_on_its_turn_and_keeps_the_prefix_stable():
    edited_turn = {
        "role": "user",
        "content": "second",
        "screen_edits": [{"field": "instructions", "before": "warm", "after": "cold"}],
    }
    # The note was rendered under the live state on its own turn, so compare
    # the two requests after that turn stops being the last one.
    later = _prepared_history([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "done"},
        edited_turn,
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "third"},
    ])
    latest = _prepared_history([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "done"},
        edited_turn,
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "third"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "fourth"},
    ])

    assert later[:-1] == latest[:4]
    assert 'Now: "cold"' in later[2]["content"]
    assert "the Instructions" in later[2]["content"]
    assert "<system-reminder>{}" not in later[2]["content"]


async def test_agent_step_learns_provider_context_limit_and_retries():
    from routes.prompt_enhancement import (
        AgentStepRequest,
        _PROMPT_AGENT_CONTEXT_CAPS,
        agent_step,
    )

    config = _FakeConfig()
    config.max_context_tokens = 128_000
    request = httpx.Request("POST", "http://fake-endpoint/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "message": (
                    "This model's maximum context length is 32768 tokens. "
                    "However, the request is larger."
                )
            }
        },
    )
    overflow = httpx.HTTPStatusError("rejected", request=request, response=response)
    payload = AgentStepRequest(
        conversation_history=[{"role": "user", "content": "set seed to 7"}],
        state_context={"seed": 0},
        session_id="context-retry-test",
    )

    _PROMPT_AGENT_CONTEXT_CAPS.clear()
    try:
        with patch(
            "llm_resolver.get_effective_llm_config",
            new=AsyncMock(return_value=config),
        ), patch(
            "agent.v2.llm_options.agent_llm_options", return_value={}
        ), patch(
            "llm.llm_completion",
            new=AsyncMock(side_effect=[overflow, _FakeResponse(content="Done")]),
        ) as mock_llm:
            result = await agent_step(payload)

        assert result.message == "Done"
        assert mock_llm.await_count == 2
        assert mock_llm.await_args_list[0].kwargs["max_tokens"] == 16_384
        assert mock_llm.await_args_list[1].kwargs["max_tokens"] == 8_192
        assert _PROMPT_AGENT_CONTEXT_CAPS[
            (config.get_api_base(), config.get_model())
        ] == 32_768

        # The learned cap applies before the next request, avoiding another 400.
        with patch(
            "llm_resolver.get_effective_llm_config",
            new=AsyncMock(return_value=config),
        ), patch(
            "agent.v2.llm_options.agent_llm_options", return_value={}
        ), patch(
            "llm.llm_completion",
            new=AsyncMock(return_value=_FakeResponse(content="Again")),
        ) as learned_llm:
            result = await agent_step(payload)

        assert result.message == "Again"
        assert learned_llm.await_count == 1
        assert learned_llm.await_args.kwargs["max_tokens"] == 8_192
    finally:
        _PROMPT_AGENT_CONTEXT_CAPS.clear()


def test_tool_schemas_match_frontend_command_surface():
    """Every tool the prompt agent advertises must have a frontend handler.

    The prompt-editor mini-agent's tool calls are executed by ToolView.vue's
    command dispatcher (and mirrored by the eval harness's simulated screen).
    A schema without a handler silently no-ops for users; a renamed handler
    silently orphans the schema. Pin the contract.
    """
    import re
    from pathlib import Path

    from prompt_agent_tools import TOOL_SCHEMAS

    vue = Path(__file__).resolve().parents[2] / "frontend" / "src" / "views" / "ToolView.vue"
    source = vue.read_text()
    handler_names = set(re.findall(r"case '([a-z_]+)':", source))

    schema_names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    missing_handlers = schema_names - handler_names
    assert not missing_handlers, (
        f"prompt_agent_tools.py advertises tools with no ToolView.vue handler: {sorted(missing_handlers)}"
    )

"""Tests for the prompt-editor mini-agent endpoint and tool schemas.

History compaction reuses the shared v2 `_apply_token_budget` (covered by the
agent test suite), so it isn't re-tested here.
"""
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch, AsyncMock

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

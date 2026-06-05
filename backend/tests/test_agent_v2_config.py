import pytest

from agent.v2.agent_config import merge_tool_configs
from agent.v2.prompts import get_system_prompt
from agent.v2.tools.discover import _tool_sort_key
from config import AgentToolConfig


def test_v2_merge_tool_configs_matches_expected_precedence():
    global_cfg = AgentToolConfig(
        allowed_tools=["global-allowed"],
        denied_tools=["global-denied"],
        v2_permissions={"bash": "allow"},
    )
    chat_cfg = {
        "allowed_tools": ["chat-allowed"],
        "v2_permissions": {"web_search": "deny"},
    }

    merged = merge_tool_configs(global_cfg, None, chat_cfg)

    assert merged.allowed_tools == ["chat-allowed"]
    assert merged.denied_tools == ["global-denied"]
    assert merged.v2_permissions == {"web_search": "deny"}


def test_v2_system_prompt_includes_instructions():
    prompt = get_system_prompt(
        additional_instructions="Prefer landscape outputs.",
    )

    assert "## User Instructions" in prompt
    assert "Prefer landscape outputs." in prompt


def test_v2_system_prompt_mentions_host_shell(monkeypatch):
    monkeypatch.setattr("agent.v2.prompts.is_windows_host", lambda: False)
    monkeypatch.setattr("agent.v2.prompts.get_shell_runtime_name", lambda: "bash")
    prompt = get_system_prompt()
    assert "Use bash syntax" in prompt

    monkeypatch.setattr("agent.v2.prompts.is_windows_host", lambda: True)
    monkeypatch.setattr("agent.v2.prompts.get_shell_runtime_name", lambda: "PowerShell")
    prompt = get_system_prompt()
    assert "Use PowerShell syntax" in prompt


def test_v2_discover_sort_prefers_recent_then_approved():
    approved = {"provider:approved", "provider:recent"}
    tool_ids = [
        "provider:other",
        "provider:approved",
        "provider:recent",
    ]

    ranked = sorted(
        tool_ids,
        key=lambda tool_id: _tool_sort_key(
            tool_id,
            recent_tool_id="provider:recent",
            approved_tools=approved,
        ),
    )

    assert ranked == [
        "provider:recent",
        "provider:approved",
        "provider:other",
    ]

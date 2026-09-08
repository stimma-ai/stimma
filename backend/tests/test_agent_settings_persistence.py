"""Agent-side writes must preserve explicit local model choices on disk."""

from copy import deepcopy

import pytest
import yaml

import app_dirs
import config
import config_writer
from agent.v2.permissions import _add_to_global_stp_permission
from agent.v2.tools.save_memory import save_memory
from core.profile_context import ProfileScope
from llm_resolver import resolve_chat_model_slug


@pytest.mark.parametrize("operation", ["allow", "deny", "memory"])
async def test_agent_writes_preserve_local_models(tmp_path, monkeypatch, operation):
    path = tmp_path / "config.yaml"
    agent = {
        "additional_instructions": "Keep my preferences.",
        "memory": "Existing memory",
        "models": {
            role: {"model": f"local:test-{role}", "effort": "high"}
            for role in ("quick_task", "tool_assistant", "chat", "flow")
        },
        "tool_config": {
            "allowed_tools": ["test:allowed", "test:target"],
            "denied_tools": ["test:denied"],
            "v2_permissions": {"bash": "deny"},
        },
    }
    if operation == "allow":
        agent["tool_config"]["allowed_tools"].remove("test:target")
        agent["tool_config"]["denied_tools"].append("test:target")
    other = {"id": "other", "name": "Other", "agent": deepcopy(agent)}
    path.write_text(yaml.safe_dump({
        "profiles": [{"id": "test-profile", "name": "Test", "agent": agent}, other],
        "llms": {},
        "clip": {"model": "ViT-g-14", "pretrained": "laion2b_s12b_b42k"},
        "face_detection": {"enabled": False},
        "server": {"port": 0},
    }))
    monkeypatch.setattr(app_dirs, "get_config_path", lambda: path)
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda profile_id=None: tmp_path / (profile_id or "test-profile"))
    monkeypatch.setattr(config, "settings", None)
    monkeypatch.setattr(config_writer, "_app_initiated_write", False)
    expected = deepcopy(agent)

    with ProfileScope("test-profile"):
        config.reload_settings()
        assert resolve_chat_model_slug(None, None) == "local:test-chat"
        if operation == "memory":
            result = await save_memory(scope="global", content="Updated memory")
            assert result.startswith("Global memory saved")
            expected["memory"] = "Updated memory"
        else:
            approved = operation == "allow"
            await _add_to_global_stp_permission("test:target", approved)
            chosen, opposite = ("allowed_tools", "denied_tools") if approved else ("denied_tools", "allowed_tools")
            expected["tool_config"][chosen].append("test:target")
            expected["tool_config"][opposite].remove("test:target")

        persisted = yaml.safe_load(path.read_text())
        assert persisted["profiles"][0]["agent"] == expected
        assert persisted["profiles"][1] == other
        assert config.get_settings().get_agent_for_profile("test-profile").model_dump() == expected
        assert resolve_chat_model_slug(None, None) == "local:test-chat"
        config.reload_settings()
        assert config.get_settings().get_agent_for_profile("test-profile").model_dump() == expected
        assert resolve_chat_model_slug(None, None) == "local:test-chat"

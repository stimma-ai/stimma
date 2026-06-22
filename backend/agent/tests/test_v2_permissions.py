import json

import pytest

from agent.v2.permissions import check_permission_for_call, is_auto_approved_tool_call
from database import Chat


class _FakeToolConfig:
    v2_permissions = {}


class _FakeAgentConfig:
    tool_config = _FakeToolConfig()


class _FakeSettings:
    def get_agent_for_profile(self, _profile_id):
        return _FakeAgentConfig()


@pytest.mark.parametrize(
    "command",
    [
        "pwd",
        "ls -la .stimma/tools/",
        "find .stimma/tools -maxdepth 2 -type f",
        "rg upscale .stimma/tools",
        "grep -R prompt .stimma/tools",
        "sed -n '1,120p' .stimma/tools/text-to-image/example.py",
        "cat .stimma/tools/text-to-image/example.py",
    ],
)
def test_bash_workspace_discovery_commands_are_auto_approved(command):
    assert is_auto_approved_tool_call("bash", {"command": command}) is True


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf .stimma/tools",
        "ls .stimma/tools && rm -rf .",
        "cat /etc/passwd",
        "cat ../config.yaml",
        "find . -delete",
        "find . -exec rm {} ;",
        "grep prompt .stimma/tools > matches.txt",
        "python -c 'print(1)'",
    ],
)
def test_bash_workspace_discovery_auto_approval_rejects_risky_commands(command):
    assert is_auto_approved_tool_call("bash", {"command": command}) is False


@pytest.mark.asyncio
async def test_default_ask_policy_allows_discovery_command_without_prompt(monkeypatch):
    monkeypatch.setattr("config.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("core.profile_context.get_current_profile", lambda: "default")

    chat = Chat(agent_tool_config=None)

    assert await check_permission_for_call(
        "bash",
        {"command": "ls -la .stimma/tools/"},
        chat,
        None,
    ) is True


@pytest.mark.asyncio
async def test_configured_bash_deny_overrides_discovery_auto_approval():
    chat = Chat(
        agent_tool_config=json.dumps({
            "v2_permissions": {
                "bash": "deny",
            },
        })
    )

    assert await check_permission_for_call(
        "bash",
        {"command": "ls -la .stimma/tools/"},
        chat,
        None,
    ) is False

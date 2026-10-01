"""Lightweight helpers must not initialize agent execution or its catalog."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["agent.v2.workspace", "agent.v2.code_runtime"])
def test_helpers_can_be_imported_before_agent_execution(module):
    subprocess.run(
        [sys.executable, "-c", f"import sys; import {module}; "
         'assert "agent.v2.service" not in sys.modules; '
         'assert "agent.v2.tools.delegate" not in sys.modules; '
         'from agent.v2.tools_registry import get_tool, get_tools_schema; '
         'assert get_tool("ask_user"); assert get_tools_schema(); '
         'from agent.v2 import run_agent, interrupt_execution; '
         'assert callable(run_agent) and callable(interrupt_execution)'],
        check=True, capture_output=True, text=True,
    )

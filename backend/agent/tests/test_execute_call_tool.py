"""Regression tests for execute_call_tool job-params construction.

The integration tests in test_run_code_v2.py mock execute_call_tool away, so
they cannot catch bugs inside it. These exercise the real function and assert
that explicitly-provided parameter values (prompt, width, height, seed)
reach the provider intact — and are NOT clobbered by the tool's schema defaults.
"""

from dataclasses import dataclass, field

import pytest
from unittest.mock import patch

import agent.v2.tools.call_tool as ct


@dataclass
class _Desc:
    name: str = "Mock Tool"
    task_types: list = field(default_factory=lambda: ["text-to-image"])
    task_type: str = "text-to-image"
    subtitle: str = ""
    # Schema gives prompt/width/height DEFAULTS — the exact shape that triggered
    # the "unconditional generations" bug (empty prompt, default 1024 dims).
    parameter_schema: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "default": ""},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "seed": {"type": "integer"},
            "steps": {"type": "integer", "default": 4},
            "guidance": {"type": "number", "default": 1},
            "sampler": {"type": "string", "default": "euler"},
            "loras": {"type": "array"},
        },
        "required": ["prompt"],
    })


class _Prov:
    provider_id = "comfyui"
    provider_type = "external"


class _Reg:
    @staticmethod
    def get_instance():
        return _Reg()

    def get_tool(self, tool_id):
        return (_Prov(), _Desc())


@pytest.mark.asyncio
async def test_input_values_not_clobbered_by_schema_defaults():
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            captured["task_type"] = kw.get("task_type")
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    with patch.object(ct, "ProviderRegistry", _Reg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock",
                parameters={
                    "prompt": "a vivid prompt", "width": 896, "height": 1152,
                    "steps": 12, "guidance": 1, "sampler": "euler", "loras": [],
                },
                task_type_override="text-to-image",
                session=object(),
            )

    p = captured["params"]
    # The explicit input values must survive — schema defaults ("" / 1024) must
    # NOT overwrite them.
    assert p["prompt"] == "a vivid prompt"
    assert p["width"] == 896
    assert p["height"] == 1152
    # And the generation params still come through.
    assert p["steps"] == 12
    assert p["guidance"] == 1
    assert captured["task_type"] == "text-to-image"


@pytest.mark.asyncio
async def test_omitted_generation_knobs_are_not_sent_when_schema_hides_them():
    captured = {}

    @dataclass
    class _NoStepsDesc:
        name: str = "Mock Tool"
        task_types: list = field(default_factory=lambda: ["text-to-image"])
        task_type: str = "text-to-image"
        subtitle: str = ""
        parameter_schema: dict = field(default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "width": {"type": "integer", "default": 1024},
                "height": {"type": "integer", "default": 1024},
                "seed": {"type": "integer"},
            },
            "required": ["prompt"],
        })

    class _NoStepsReg:
        @staticmethod
        def get_instance():
            return _NoStepsReg()

        def get_tool(self, tool_id):
            return (_Prov(), _NoStepsDesc())

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    with patch.object(ct, "ProviderRegistry", _NoStepsReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="stimma-cloud:flux2-klein-9b",
                parameters={"prompt": "a dog"},
                task_type_override="text-to-image",
                session=object(),
            )

    p = captured["params"]
    assert p["prompt"] == "a dog"
    assert p["width"] == 1024
    assert p["height"] == 1024
    assert "seed" in p
    for key in ("steps", "cfg", "guidance", "sampler", "scheduler", "loras", "negative_prompt"):
        assert key not in p

"""Unit tests for the .stimma/ filesystem tool-surface generator."""

from __future__ import annotations

import ast
import pytest
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.v2 import tool_fs


@dataclass
class FakeDescriptor:
    name: str
    description: str
    task_types: list[str]
    parameter_schema: dict[str, Any]
    subtitle: str = ""
    task_type: str | None = None


@dataclass
class FakeRegistry:
    tools: list[tuple[str, Any, FakeDescriptor]]

    def list_all_tools(self):
        return list(self.tools)


def _t2i_schema(extra_loras: int = 0):
    schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The text prompt."},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "seed": {"type": "integer"},
            "sampler": {
                "type": "string",
                "default": "euler",
                "enum": ["euler", "euler_a", "dpmpp_2m", "ddim"],
            },
            "steps": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
        },
        "required": ["prompt"],
    }
    if extra_loras:
        schema["properties"]["loras"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "enum": [f"lora_{i}" for i in range(extra_loras)]},
                    "weight": {"type": "number", "default": 1.0},
                },
            },
        }
    return schema


def _registry():
    return FakeRegistry(
        tools=[
            (
                "comfyui:flux-klein-9b",
                None,
                FakeDescriptor(
                    name="Flux (Klein 9B)",
                    description="Fast text to image.",
                    task_types=["text-to-image"],
                    parameter_schema=_t2i_schema(),
                ),
            ),
            (
                "comfyui:big-lora-model",
                None,
                FakeDescriptor(
                    name="Big Lora Model",
                    description="Model with a huge lora catalog.",
                    task_types=["text-to-image", "image-to-image"],
                    parameter_schema=_t2i_schema(extra_loras=5000),
                ),
            ),
            (
                "replicate:flux-klein-9b",  # name collision with comfyui in same task
                None,
                FakeDescriptor(
                    name="Flux Klein (Replicate)",
                    description="Same local name, different provider.",
                    task_types=["text-to-image"],
                    parameter_schema=_t2i_schema(),
                ),
            ),
        ]
    )


def test_manifest_modules_and_collision():
    m = tool_fs.build_manifest(_registry())
    assert "text_to_image" in m.by_module
    assert "image_to_image" in m.by_module  # from the multi-task tool

    t2i = m.by_module["text_to_image"]
    # comfyui:flux-klein-9b -> flux_klein_9b
    assert "flux_klein_9b" in t2i
    assert t2i["flux_klein_9b"].tool_id == "comfyui:flux-klein-9b"
    # collision disambiguated, never silently dropped
    assert any(b.tool_id == "replicate:flux-klein-9b" for b in t2i.values())
    assert len({b.tool_id for b in t2i.values()}) == len(t2i)


def test_stub_is_valid_python_and_typed():
    m = tool_fs.build_manifest(_registry())
    binding = m.by_module["text_to_image"]["flux_klein_9b"]
    text, spills = tool_fs.render_tool_stub(binding)
    # Must parse as Python (it's body-less docs but must be syntactically real).
    tree = ast.parse(text)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef))
    assert fn.name == "flux_klein_9b"
    # required param has no default; keyword-only
    kwonly = {a.arg for a in fn.args.kwonlyargs}
    assert "prompt" in kwonly
    # small enum inlined as Literal
    assert "Literal['euler'" in text
    # tool_id + task_type discoverable in the docstring for recipe authors
    assert '"comfyui:flux-klein-9b"' in text
    assert '"text-to-image"' in text
    assert not spills  # no large enums here


def test_large_enum_spills_to_file_not_signature():
    m = tool_fs.build_manifest(_registry())
    binding = m.by_module["text_to_image"]["big_lora_model"]
    text, spills = tool_fs.render_tool_stub(binding, enum_threshold=100)
    # 5000-entry enum must NOT be inlined
    assert "lora_4999" not in text
    assert spills, "expected an enum spill file"
    stem, values = next(iter(spills.items()))
    assert len(values) == 5000
    # The docstring's grep hint must point at the file that actually gets written.
    assert f".stimma/enums/{stem}.txt" in text


def test_materialize_writes_tree_and_is_idempotent(tmp_path: Path):
    reg = _registry()
    root = tool_fs.materialize_tool_fs(reg, tmp_path, enum_threshold=100)
    assert (root / "README.md").exists()
    assert (root / "tools" / "text-to-image" / "flux_klein_9b.py").exists()
    assert (root / "tools" / "image-to-image").exists()
    assert (root / ".manifest.json").exists()
    enums = list((root / "enums").glob("*.txt"))
    assert enums, "large lora enum should have spilled to a file"

    # Second call with unchanged catalog must be a cheap no-op (fingerprint hit).
    fp1 = (root / ".fingerprint").read_text()
    tool_fs.materialize_tool_fs(reg, tmp_path, enum_threshold=100)
    fp2 = (root / ".fingerprint").read_text()
    assert fp1 == fp2


def test_materialize_prunes_removed_tools(tmp_path: Path):
    reg = _registry()
    tool_fs.materialize_tool_fs(reg, tmp_path, enum_threshold=100)
    t2i = tmp_path / ".stimma" / "tools" / "text-to-image"
    # The colliding replicate tool got a disambiguated stub name.
    disambiguated = next(p for p in t2i.glob("flux_klein_9b_*.py"))
    assert disambiguated.exists()
    # Remove the replicate tool and regenerate — its stale stub should be pruned,
    # while the un-collided comfyui stub remains.
    reg.tools = [t for t in reg.tools if t[0] != "replicate:flux-klein-9b"]
    tool_fs.materialize_tool_fs(reg, tmp_path, enum_threshold=100)
    assert not disambiguated.exists()
    assert (t2i / "flux_klein_9b.py").exists()


def test_runtime_namespace_binds_to_sdk():
    m = tool_fs.build_manifest(_registry())

    calls: list[tuple] = []

    class FakeSDK:
        async def _dispatch_tool(self, tool_id, _task_type=None, **kwargs):
            calls.append((tool_id, _task_type, kwargs))
            return {"ok": True}

    extra = tool_fs.build_tools_namespace(FakeSDK(), m)
    assert "stimma.tools.text_to_image" in extra
    mod = extra["stimma.tools.text_to_image"]
    fn = getattr(mod, "flux_klein_9b")

    asyncio.get_event_loop().run_until_complete(fn(prompt="a cat", width=512))
    assert calls == [("comfyui:flux-klein-9b", "text-to-image", {"prompt": "a cat", "width": 512})]

    # The multi-task tool dispatches with the task_type of the namespace used.
    i2i = extra["stimma.tools.image_to_image"]
    calls.clear()
    asyncio.get_event_loop().run_until_complete(getattr(i2i, "big_lora_model")(prompt="x"))
    assert calls[0][1] == "image-to-image"


def test_import_statement_resolves_through_custom_import():
    """Mirror the sandbox: a `from stimma.tools.x import y` statement must resolve
    via a custom __import__ that returns our synthesized modules."""
    m = tool_fs.build_manifest(_registry())

    class FakeSDK:
        async def _dispatch_tool(self, tool_id, _task_type=None, **kwargs):
            return {"tool_id": tool_id}

    extra = tool_fs.build_tools_namespace(FakeSDK(), m)

    def _safe_import(name, g=None, l=None, fromlist=(), level=0):
        if name in extra:
            return extra[name]
        raise ImportError(f"not allowed: {name}")

    g: dict = {"__builtins__": {"__import__": _safe_import}}
    exec("from stimma.tools.text_to_image import flux_klein_9b", g)
    assert "flux_klein_9b" in g and callable(g["flux_klein_9b"])
    # And the package form: `from stimma.tools import text_to_image`
    g2: dict = {"__builtins__": {"__import__": _safe_import}}
    exec("from stimma.tools import text_to_image", g2)
    assert hasattr(g2["text_to_image"], "flux_klein_9b")


def test_importing_unknown_tool_lists_real_names():
    """A placeholder import (e.g. `gen`) must fail with the real tool names,
    so the model self-corrects instead of guessing the same fake name."""
    m = tool_fs.build_manifest(_registry())

    class FakeSDK:
        async def _dispatch_tool(self, *a, **k):
            return {}

    extra = tool_fs.build_tools_namespace(FakeSDK(), m)
    mod = extra["stimma.tools.text_to_image"]
    with pytest.raises(ImportError) as exc:
        getattr(mod, "gen")
    msg = str(exc.value)
    assert "not a tool" in msg
    # lists actual catalog names
    assert "flux_klein_9b" in msg
    # dunders still raise AttributeError so import machinery isn't broken
    with pytest.raises(AttributeError):
        getattr(mod, "__path__")

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


@dataclass
class _I2IDesc:
    name: str = "Mock Edit"
    task_types: list = field(default_factory=lambda: ["image-to-image"])
    task_type: str = "image-to-image"
    subtitle: str = ""
    parameter_schema: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "default": ""},
            "input_images": {"type": "array"},
        },
        "required": ["prompt"],
    })


class _I2IReg:
    @staticmethod
    def get_instance():
        return _I2IReg()

    def get_tool(self, tool_id):
        return (_Prov(), _I2IDesc())


@pytest.mark.asyncio
async def test_media_prefix_input_image_resolves_to_id_without_db():
    """A `media:<id>` reference resolves to the numeric id directly — no DB
    filename lookup, no silent drop that surfaces as "No input media provided"."""
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="builtin:filter",
                parameters={"prompt": "warm", "input_images": ["media:384"]},
                task_type_override="image-to-image",
                session=object(),
            )

    assert captured["params"]["input_media_ids"] == [384]


@pytest.mark.asyncio
async def test_unresolvable_input_image_raises_naming_the_value():
    """An unresolved string must fail loudly (naming the value) instead of being
    dropped into an empty list that the provider reports as "No input media"."""
    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: object()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(ValueError, match="media:not-a-real-id"):
            await ct.execute_call_tool(
                tool_id="builtin:filter",
                parameters={"prompt": "warm", "input_images": ["media:not-a-real-id"]},
                task_type_override="image-to-image",
                session=object(),
            )


@pytest.mark.asyncio
async def test_workspace_file_input_passes_through_without_library(tmp_path):
    """A file the agent just wrote to the workspace is a valid input as-is —
    no library.save roundtrip required. The entry is rewritten to an absolute
    path and carries no lineage media id."""
    crop = tmp_path / "middle_crop.png"
    crop.write_bytes(b"\x89PNG fake")
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock-edit",
                parameters={"prompt": "warm", "input_images": ["middle_crop.png"]},
                task_type_override="image-to-image",
                session=object(),
                workspace_dir=str(tmp_path),
            )

    p = captured["params"]
    assert p["input_images"] == [str(crop)]
    assert "input_media_ids" not in p


@pytest.mark.asyncio
async def test_absolute_path_input_passes_through(tmp_path):
    """An absolute path to an existing file is accepted directly."""
    crop = tmp_path / "crop_abs.png"
    crop.write_bytes(b"\x89PNG fake")
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock-edit",
                parameters={"prompt": "warm", "input_images": [str(crop)]},
                task_type_override="image-to-image",
                session=object(),
            )

    assert captured["params"]["input_images"] == [str(crop)]


@pytest.mark.asyncio
async def test_metadata_only_builtin_tool_executes_in_process(tmp_path):
    """A builtin tool flagged metadata_only (detect-objects) never touches the
    generation queue — it executes directly and returns the provider's result
    metadata as a plain dict."""
    from providers.base import ExecutionResult

    img_file = tmp_path / "photo.png"
    img_file.write_bytes(b"\x89PNG fake")

    detections = [{"label": "person", "bbox": {"x": 10, "y": 20, "width": 30, "height": 40}, "score": 0.9}]

    class _BuiltinProv:
        provider_id = "builtin"
        provider_type = "builtin"

        async def execute(self, tool_id, parameters, **kw):
            assert parameters["input_images"] == [str(img_file)]
            assert parameters["subject"] == "person"
            yield ExecutionResult(
                success=True,
                metadata={"count": 1, "detections": detections, "image_size": {"width": 451, "height": 679}},
            )

    @dataclass
    class _DetectDesc:
        id: str = "detect-objects"
        name: str = "Detect Objects"
        task_types: list = field(default_factory=lambda: ["detect-objects"])
        task_type: str = "detect-objects"
        subtitle: str = ""
        metadata: dict = field(default_factory=lambda: {"agent_only": True, "metadata_only": True})
        parameter_schema: dict = field(default_factory=lambda: {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "confidence_threshold": {"type": "number", "default": 0.3},
                "input_images": {"type": "array"},
            },
            "required": ["subject", "input_images"],
        })

    class _DetectReg:
        @staticmethod
        def get_instance():
            return _DetectReg()

        def get_tool(self, tool_id):
            return (_BuiltinProv(), _DetectDesc())

    class _NeverQueue:
        async def submit_job(self, **kw):
            raise AssertionError("metadata-only tool must not reach the generation queue")

    with patch.object(ct, "ProviderRegistry", _DetectReg), \
         patch.object(ct, "get_generation_queue", lambda: _NeverQueue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        result = await ct.execute_call_tool(
            tool_id="builtin:detect-objects",
            parameters={"subject": "person", "input_images": [str(img_file)]},
            task_type_override="detect-objects",
            session=object(),
        )

    assert result["metadata_only"] is True
    assert result["detections"] == detections
    assert result["count"] == 1
    assert result["image_size"] == {"width": 451, "height": 679}
    assert "media_id" not in result

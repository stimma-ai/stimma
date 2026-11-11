"""Regression tests for execute_call_tool job-params construction.

The integration tests in test_run_code_v2.py mock execute_call_tool away, so
they cannot catch bugs inside it. These exercise the real function and assert
that explicitly-provided parameter values (prompt, width, height, seed)
reach the provider intact — and are NOT clobbered by the tool's schema defaults.
"""

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, patch

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


class _AsyncSessionContext:
    """Minimal async session context for deterministic import-boundary tests."""

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


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
async def test_chat_generation_auto_delete_preference_reaches_queue():
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured.update(kw)
            raise RuntimeError("__stop__")

    class _SettingsSession:
        async def get(self, model, chat_id):
            return SimpleNamespace(
                generation_settings='{"auto_delete_duration":"1m"}'
            )

    class _SettingsContext:
        async def __aenter__(self):
            return _SettingsSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_db = SimpleNamespace(async_session_maker=lambda: _SettingsContext())
    fake_registry = SimpleNamespace(get_database=lambda profile_id: fake_db)

    with patch.object(ct, "ProviderRegistry", _Reg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"), \
         patch("database_registry.get_database_registry", lambda: fake_registry):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock",
                parameters={"prompt": "short-lived"},
                task_type_override="text-to-image",
                session=object(),
                chat_id=17,
            )

    assert captured["auto_delete_duration"] == "1m"
    assert captured["output_disposition"] == "context"


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
@pytest.mark.parametrize("images", [["middle_crop.png"], "middle_crop.png"])
async def test_workspace_file_input_is_imported_for_durable_lineage(tmp_path, images):
    """A workspace file is imported and submitted by media id.

    Mock the import boundary explicitly so this test cannot change behavior
    based on whether another test initialized the process-wide DB registry.
    """
    crop = tmp_path / "middle_crop.png"
    crop.write_bytes(b"\x89PNG fake")
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    import_input = AsyncMock(return_value=731)
    db = type("_DB", (), {"async_session_maker": lambda self: _AsyncSessionContext()})()
    registry = type("_Registry", (), {"get_database": lambda self, _profile: db})()

    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"), \
         patch("database_registry.get_database_registry", return_value=registry), \
         patch("agent.v2.tools.library.resolve_or_import_input_file", import_input):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock-edit",
                parameters={"prompt": "warm", "input_images": images},
                task_type_override="image-to-image",
                session=object(),
                workspace_dir=str(tmp_path),
            )

    p = captured["params"]
    assert p["input_images"] == [731]
    assert p["input_media_ids"] == [731]
    assert import_input.await_count == 1
    assert import_input.await_args.args[1] == str(crop)
    assert import_input.await_args.args[2] == tmp_path


@pytest.mark.asyncio
async def test_absolute_path_input_is_imported_for_durable_lineage(tmp_path):
    """An absolute input path uses the same deterministic import path."""
    crop = tmp_path / "crop_abs.png"
    crop.write_bytes(b"\x89PNG fake")
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    import_input = AsyncMock(return_value=732)
    db = type("_DB", (), {"async_session_maker": lambda self: _AsyncSessionContext()})()
    registry = type("_Registry", (), {"get_database": lambda self, _profile: db})()

    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"), \
         patch("database_registry.get_database_registry", return_value=registry), \
         patch("agent.v2.tools.library.resolve_or_import_input_file", import_input):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock-edit",
                parameters={"prompt": "warm", "input_images": [str(crop)]},
                task_type_override="image-to-image",
                session=object(),
            )

    p = captured["params"]
    assert p["input_images"] == [732]
    assert p["input_media_ids"] == [732]
    assert import_input.await_count == 1
    assert import_input.await_args.args[1] == str(crop)
    assert import_input.await_args.args[2] is None


@pytest.mark.asyncio
async def test_pathlike_input_is_imported_and_resolved_to_media_id(tmp_path):
    """A pathlib path follows the same durable-lineage resolver as a string path."""
    crop = tmp_path / "crop_pathlib.png"
    crop.write_bytes(b"\x89PNG fake")
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    import_input = AsyncMock(return_value=733)
    db = type("_DB", (), {"async_session_maker": lambda self: _AsyncSessionContext()})()
    registry = type("_Registry", (), {"get_database": lambda self, _profile: db})()

    with patch.object(ct, "ProviderRegistry", _I2IReg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"), \
         patch("database_registry.get_database_registry", return_value=registry), \
         patch("agent.v2.tools.library.resolve_or_import_input_file", import_input):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock-edit",
                parameters={"prompt": "warm", "input_images": [Path(crop)]},
                task_type_override="image-to-image",
                session=object(),
                workspace_dir=str(tmp_path),
            )

    p = captured["params"]
    assert p["input_images"] == [733]
    assert p["input_media_ids"] == [733]
    assert import_input.await_args.args[1] == str(crop)


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
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"), \
         patch("database_registry.get_database_registry", side_effect=AssertionError(
             "metadata-only path inputs must not touch the library"
         )):
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


# ── output size follows the frame input ──────────────────────────────────────

_VIDEO_DIMS = [[1344, 768], [768, 1344], [1024, 768], [768, 1024], [768, 768], [960, 544], [544, 960]]


def _video_reg(extra_props=None, task_types=("image-to-video",)):
    props = {
        "prompt": {"type": "string", "default": ""},
        "input_images": {"type": "array"},
        "width": {"type": "integer", "default": 1344, "x-allowed-dimensions": _VIDEO_DIMS},
        "height": {"type": "integer", "default": 768},
        "keyframes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"media": {"type": "string", "x-media": ["image", "video"]},
                               "at": {"type": "number"}},
            },
        },
    }
    props.update(extra_props or {})
    desc = _Desc(
        name="Mock I2V",
        task_types=list(task_types),
        task_type="image-to-video",
        parameter_schema={"type": "object", "properties": props, "required": ["prompt"]},
    )

    class _Reg2:
        @staticmethod
        def get_instance():
            return _Reg2()

        def get_tool(self, tool_id):
            return (_Prov(), desc)

    return _Reg2


async def _no_crop(*a, **k):
    return "/tmp/cropped.png"


async def _submit(reg, parameters, dims_by_id, task_type="image-to-video", crop=None):
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

        async def cancel_job(self, *a, **k):
            pass

    async def _dims(media_id):
        return dims_by_id.get(int(media_id))

    with patch.object(ct, "ProviderRegistry", reg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"), \
         patch.object(ct, "_media_dims", _dims), \
         patch.object(ct, "_crop_to_shape", crop or _no_crop):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock-i2v",
                parameters=parameters,
                task_type_override=task_type,
                session=object(),
            )
    return captured["params"]


@pytest.mark.asyncio
async def test_omitted_size_follows_portrait_start_frame():
    """A portrait start frame on a tool whose default is landscape gets the
    portrait pair at the default's size, not the landscape default."""
    p = await _submit(_video_reg(), {"prompt": "walks", "input_images": [11]}, {11: (896, 1152)})
    assert (p["width"], p["height"]) == (768, 1024)


@pytest.mark.asyncio
async def test_omitted_size_follows_earliest_keyframe_over_reference_images():
    """Pinned keyframes are frames of the output; reference images are not."""
    p = await _submit(
        _video_reg(),
        {"prompt": "walks", "input_images": [5],
         "keyframes": [{"media": 22, "at": -1}, {"media": 21, "at": 0}]},
        {5: (1024, 1024), 21: (768, 1344), 22: (1344, 768)},
    )
    assert (p["width"], p["height"]) == (768, 1344)


@pytest.mark.asyncio
async def test_explicit_size_takes_the_start_frame_shape():
    """A start frame is the video's first frame: an explicit size of another
    shape would stretch it, so the frame's shape wins at the asked size tier."""
    p = await _submit(
        _video_reg(),
        {"prompt": "walks", "input_images": [11], "width": 1344, "height": 768},
        {11: (896, 1152)},
    )
    assert (p["width"], p["height"]) == (768, 1024)


@pytest.mark.asyncio
async def test_explicit_size_on_freeform_tool_keeps_frame_shape_and_pixel_count():
    reg = _video_reg({
        "width": {"type": "integer", "default": 1280, "minimum": 256, "maximum": 2048, "x-step": 32},
        "height": {"type": "integer", "default": 720, "minimum": 256, "maximum": 2048, "x-step": 32},
    })
    p = await _submit(
        reg,
        {"prompt": "walks", "input_images": [11], "width": 1280, "height": 720},
        {11: (1000, 1500)},
    )
    w, h = p["width"], p["height"]
    assert abs(w / h - 1000 / 1500) < 0.03
    assert abs(w * h - 1280 * 720) / (1280 * 720) < 0.1


@pytest.mark.asyncio
async def test_explicit_size_keeps_its_tier_when_shapes_repeat():
    reg = _video_reg({"width": {"type": "integer", "default": 1280, "x-allowed-dimensions":
                                [[1280, 720], [640, 360], [720, 1280], [360, 640]]},
                      "height": {"type": "integer", "default": 720}})
    p = await _submit(
        reg, {"prompt": "walks", "input_images": [11], "width": 640, "height": 360}, {11: (720, 1280)})
    assert (p["width"], p["height"]) == (360, 640)
    p = await _submit(
        reg, {"prompt": "walks", "input_images": [11], "width": 360, "height": 640}, {11: (720, 1280)})
    assert (p["width"], p["height"]) == (360, 640)


@pytest.mark.asyncio
async def test_matching_explicit_size_is_kept():
    p = await _submit(
        _video_reg(),
        {"prompt": "walks", "input_images": [11], "width": 960, "height": 544},
        {11: (1920, 1088)},
    )
    assert (p["width"], p["height"]) == (960, 544)


@pytest.mark.asyncio
async def test_explicit_aspect_ratio_takes_the_start_frame_shape():
    reg = _video_reg({"aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1"], "default": "16:9"}})
    p = await _submit(
        reg, {"prompt": "walks", "input_images": [11], "aspect_ratio": "16:9"}, {11: (720, 1280)})
    assert p["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_start_frame_no_fixed_shape_fits_is_cropped_not_stretched():
    calls = []

    async def _crop(media_id, w, h, workspace_dir):
        calls.append((media_id, w, h))
        return "/tmp/cropped.png"

    reg = _video_reg({"aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"], "default": "16:9"}})
    p = await _submit(
        reg, {"prompt": "walks", "input_images": [11]}, {11: (1000, 1000)}, crop=_crop)
    assert calls and calls[0][0] == 11
    assert p["input_images"][0] == "/tmp/cropped.png"
    assert p["input_media_ids"][0] == 11


@pytest.mark.asyncio
async def test_image_edit_keeps_an_explicit_size_of_another_shape():
    """An edit source is not a pinned frame; a deliberate new shape stands."""
    p = await _submit(
        _video_reg(task_types=("image-to-video", "image-to-image")),
        {"prompt": "banner", "input_images": [11], "width": 1344, "height": 768},
        {11: (896, 1152)},
        task_type="image-to-image",
    )
    assert (p["width"], p["height"]) == (1344, 768)


@pytest.mark.asyncio
async def test_omitted_aspect_ratio_follows_start_frame():
    reg = _video_reg({"aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1"], "default": "16:9"}})
    p = await _submit(reg, {"prompt": "walks", "input_images": [11]}, {11: (720, 1280)})
    assert p["aspect_ratio"] == "9:16"


@pytest.mark.asyncio
async def test_without_a_frame_input_schema_default_size_stands():
    p = await _submit(_video_reg(), {"prompt": "walks"}, {})
    assert (p["width"], p["height"]) == (1344, 768)


def test_follow_input_dims_freeform_scales_into_bounds():
    from agent.tools.stp_utils import follow_input_dims

    desc = SimpleNamespace(parameter_schema={"properties": {
        "width": {"type": "integer", "default": 1024, "minimum": 256, "maximum": 2048, "x-step": 16},
        "height": {"type": "integer", "default": 1024, "minimum": 256, "maximum": 2048, "x-step": 16},
    }})
    # Too large: scaled uniformly, aspect kept (not clamped per axis to a square).
    assert follow_input_dims(desc, 4000, 3000) == (2048, 1536)
    # In range: the input's own size.
    assert follow_input_dims(desc, 896, 1152) == (896, 1152)


def test_follow_input_dims_list_tool_keeps_default_short_edge():
    """A square default on a multi-tier list keeps its short edge at the
    input's shape (ToolView's tier), rather than its pixel area."""
    from agent.tools.stp_utils import follow_input_dims

    desc = SimpleNamespace(parameter_schema={"properties": {
        "width": {"type": "integer", "default": 1536,
                  "x-allowed-dimensions": [[1536, 1536], [1080, 1920], [1440, 2560], [2048, 2048]]},
        "height": {"type": "integer", "default": 1536},
    }})
    assert follow_input_dims(desc, 720, 1280) == (1440, 2560)


@pytest.mark.asyncio
async def test_a_prompt_its_caller_already_processed_goes_out_as_given():
    """A chain step runs its own prompt pipeline (a Raw step sends its words exactly as
    typed, for a later stage to fill): the call doesn't handle the prompt again."""
    captured = {}

    class _Queue:
        async def submit_job(self, **kw):
            captured["params"] = kw["parameters"]
            raise RuntimeError("__stop__")

    raw = "a {red|blue} car on {{downstream_list}}"
    with patch.object(ct, "ProviderRegistry", _Reg), \
         patch.object(ct, "get_generation_queue", lambda: _Queue()), \
         patch.object(ct, "_get_default_folder", lambda *a, **k: "/tmp"):
        with pytest.raises(RuntimeError, match="__stop__"):
            await ct.execute_call_tool(
                tool_id="comfyui:mock",
                parameters={"prompt": raw},
                task_type_override="text-to-image",
                session=object(),
                prompt_processed=True,
            )
    assert captured["params"]["prompt"] == raw


def test_center_crop_file_keeps_the_middle_at_the_output_shape(tmp_path):
    from PIL import Image

    src = tmp_path / "square.png"
    im = Image.new("RGB", (1000, 1000), "red")
    im.paste((0, 0, 255), (0, 0, 1000, 100))  # a band the crop should remove
    im.save(src)
    out = ct._center_crop_file(str(src), 16, 9, str(tmp_path), "frame_1")
    with Image.open(out) as c:
        assert c.size == (1000, 562)
        assert c.getpixel((500, 0)) == (255, 0, 0)

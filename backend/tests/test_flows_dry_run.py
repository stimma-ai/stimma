from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from flow_runtime.dry_run import DryRunConfig, dry_run_flow


def _write_program(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "program.py"
    path.write_text(source)
    return path


class _FakeDescriptor:
    def __init__(self, input_schema=None, parameter_schema=None):
        # Single parameter_schema now holds everything — merge any legacy
        # input_schema (prompt, images, ...) into it for test convenience.
        merged = dict(parameter_schema or {})
        if input_schema:
            props = {**(input_schema.get("properties") or {}), **(merged.get("properties") or {})}
            required = list(dict.fromkeys(
                (input_schema.get("required") or []) + (merged.get("required") or [])
            ))
            merged = {**input_schema, **merged, "properties": props}
            if required:
                merged["required"] = required
        self.parameter_schema = merged
        self.output_schema = {
            "type": "object",
            "properties": {
                "image_data": {"type": "string", "format": "binary"},
            },
        }


class _FakeRegistry:
    def __init__(self, tools: dict):
        self._tools = tools

    def get_tool(self, tool_id):
        desc = self._tools.get(tool_id)
        if desc is None:
            return None
        return ("fake-provider", desc)

    def subscribe_tools_changed(self, callback):
        return None

    def unsubscribe_tools_changed(self, callback):
        return None


def _with_fake_registry(tools: dict):
    return patch(
        "providers.registry.ProviderRegistry.get_instance",
        return_value=_FakeRegistry(tools),
    )


@pytest.mark.asyncio
async def test_dry_run_success_samples_flow_input_collection(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, input, output, foreach, hitl, phase, tool

@flow(
    name="sampled",
    inputs={"artists": input("list[str]")},
    outputs={"picked": output("media")},
)
def sampled(artists):
    with phase("Generate"):
        cands = foreach(artists, lambda artist: tool("stub:image", task_type="text-to-image", prompt=artist))
        return hitl.select(cands, instructions="pick one", count=1)
''',
    )

    report = await dry_run_flow(
        flow_id=1,
        program_path=program,
        inputs={"artists": ["A", "B", "C", "D"]},
        config=DryRunConfig(max_items_per_collection=2),
    )

    assert report.ok, report.to_dict()
    assert report.sampled_collections == {"input:artists": 4}
    assert not [
        issue for issue in report.issues if issue.status in {"failed", "awaiting_input"}
    ]


@pytest.mark.asyncio
async def test_dry_run_catches_deferred_tool_parameter_shape_error(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, hitl, tool, phase

@flow(name="bad_tool_params", outputs={"out": output("list[media]")})
def bad_tool_params():
    with phase("Generate"):
        return hitl.approve(
            2,
            lambda i: tool(
                "fake:gen", task_type="text-to-image",
                prompt="p",
                guidance=1,
            ),
            instructions="keep?",
        )
''',
    )

    with _with_fake_registry({
        "fake:gen": _FakeDescriptor(
            input_schema={
                "type": "object",
                "required": ["prompt"],
                "properties": {"prompt": {"type": "string"}},
            },
            parameter_schema={
                "type": "object",
                "properties": {
                    "guidance": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                },
            },
        ),
    }):
        report = await dry_run_flow(flow_id=4, program_path=program)

    assert not report.ok
    assert any(
        "parameter 'guidance' shape mismatch" in issue.message
        for issue in report.issues
    ), report.to_dict()


@pytest.mark.asyncio
async def test_dry_run_executes_create_image_callable(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, create_image, phase

@flow(name="bad_create_image", outputs={"out": output("media")})
def bad_create_image():
    with phase("Compose"):
        return create_image(_windowpane, inputs={"faces": [None]})

def _windowpane(faces):
    imgs = [f.pil for f in faces]
    return imgs[0]
''',
    )

    report = await dry_run_flow(flow_id=5, program_path=program)

    assert not report.ok
    assert any(
        issue.equation_type == "create_image"
        and "AttributeError" in issue.message
        and "'NoneType' object has no attribute 'pil'" in issue.message
        for issue in report.issues
    ), report.to_dict()


@pytest.mark.asyncio
async def test_dry_run_does_not_sample_internal_approve_before_create_image(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, hitl, tool, create_image, phase
from PIL import Image

@flow(name="six_panel", outputs={"out": output("media")})
def six_panel():
    with phase("Generate"):
        faces = hitl.approve(
            6,
            lambda i: tool("stub:image", task_type="text-to-image", prompt=str(i)),
            instructions="keep?",
        )
    with phase("Compose"):
        return create_image(_windowpane, inputs={"faces": faces})

def _windowpane(faces):
    imgs = [f.pil for f in faces]
    assert len(imgs) == 6, f"expected 6, got {len(imgs)}"
    canvas = Image.new("RGB", (3, 2))
    for i, m in enumerate(imgs):
        r, c = divmod(i, 3)
        canvas.paste(m.resize((1, 1)), (c, r))
    return canvas
''',
    )

    report = await dry_run_flow(
        flow_id=9,
        program_path=program,
        config=DryRunConfig(max_items_per_collection=2),
    )

    assert report.ok, report.to_dict()
    assert report.sampled_collections == {}


@pytest.mark.asyncio
async def test_dry_run_executes_create_layout_callable(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, create_layout, phase

@flow(name="bad_layout", outputs={"out": output("media")})
def bad_layout():
    with phase("Compose"):
        return create_layout(lambda: {"not": "html"})
''',
    )

    report = await dry_run_flow(flow_id=6, program_path=program)

    assert not report.ok
    assert any(
        issue.equation_type == "create_layout"
        and "callable must return an HTML string" in issue.message
        for issue in report.issues
    ), report.to_dict()


@pytest.mark.asyncio
async def test_dry_run_validates_create_grid_runtime_item_count(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, create_grid, code, phase

@flow(name="bad_grid", outputs={"out": output("media")})
def bad_grid():
    with phase("Compose"):
        items = code(lambda: [1, 2, 3], output_type="list[media]")
        return create_grid(
            items,
            rows=2,
            cols=2,
            row_headers=["a", "b"],
            col_headers=["c", "d"],
        )
''',
    )

    report = await dry_run_flow(flow_id=7, program_path=program)

    assert not report.ok
    assert any(
        issue.equation_type == "create_grid"
        and "expected 4 items" in issue.message
        for issue in report.issues
    ), report.to_dict()


@pytest.mark.asyncio
async def test_dry_run_catches_deferred_callback_noderef_misuse(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, foreach, code, phase

@flow(name="bad_callback", outputs={"out": output("list[int]")})
def bad_callback():
    with phase("Build"):
        xs = code(lambda: [1, 2], output_type="list[int]")
        ys = code(lambda: [10, 20], output_type="list[int]")
        return foreach(
            xs,
            lambda x, ys: code(lambda n: n, inputs={"n": len(ys)}, output_type="int"),
            ys=ys,
        )
''',
    )

    report = await dry_run_flow(flow_id=8, program_path=program)

    assert not report.ok
    assert any(
        issue.equation_type == "control"
        and "callback error" in issue.message
        and "len(node)" in issue.message
        for issue in report.issues
    ), report.to_dict()


@pytest.mark.asyncio
async def test_dry_run_catches_foreach_extra_kwarg_signature_mismatch(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, foreach, code, phase

@flow(name="bad_callback_signature", outputs={"out": output("list[int]")})
def bad_callback_signature():
    with phase("Build"):
        xs = code(lambda: [1, 2], output_type="list[int]")
        ys = code(lambda: [10, 20], output_type="list[int]")
        return foreach(
            xs,
            lambda x, y: code(lambda n: n, inputs={"n": x}, output_type="int"),
            ys=ys,
        )
''',
    )

    report = await dry_run_flow(flow_id=10, program_path=program)

    assert not report.ok
    assert any(
        issue.equation_key == "<program>"
        and "extra kwarg(s) ['ys']" in issue.message
        for issue in report.issues
    ), report.to_dict()


@pytest.mark.asyncio
async def test_dry_run_catches_runtime_code_shape_error(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, llm, code, phase

@flow(name="bad", outputs={"items": output("list[str]")})
def bad():
    with phase("Check"):
        data = llm("return some prose")
        return code("data['items']", inputs={"data": data}, output_type="list[str]")
''',
    )

    report = await dry_run_flow(flow_id=2, program_path=program)

    assert not report.ok
    assert any(
        issue.equation_type == "code" and "TypeError" in issue.message
        for issue in report.issues
    )


@pytest.mark.asyncio
async def test_dry_run_llm_response_format_flows_through_code_and_hitl(tmp_path):
    program = _write_program(
        tmp_path,
        '''
from stimma.flow import flow, output, llm, code, hitl, phase

@flow(name="structured", outputs={"item": output("str")})
def structured():
    with phase("Check"):
        data = llm(
            "return json",
            response_format={"schema": {"items": "list[str]"}},
        )
        items = code("data['items']", inputs={"data": data}, output_type="list[str]")
        return hitl.select(items, instructions="pick", count=1)
''',
    )

    report = await dry_run_flow(flow_id=3, program_path=program)

    assert report.ok, report.to_dict()

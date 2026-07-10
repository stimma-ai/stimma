import json
from pathlib import Path

import pytest
from sqlalchemy import select

from dataclasses import dataclass, field

from agent.v2.permissions import GATED_TOOLS
from agent.v2.prompts import get_system_prompt
from agent.v2.tools.run_code import run_code
from agent.v2.tools_registry import get_tool, get_tools_schema
from database import ChatItem, MediaItem, MediaLineage
from tests.helpers.media import create_media_item, generate_test_image


@dataclass
class _MockDescriptor:
    name: str = "Mock Tool"
    description: str = "A mock generation tool."
    task_types: list = field(default_factory=lambda: ["text-to-image"])
    parameter_schema: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "input_images": {"type": "array", "items": {"type": "integer"}},
            "steps": {"type": "integer", "default": 20},
        },
        "required": ["prompt"],
    })
    task_type: str = None
    subtitle: str = ""


def _patch_mock_registry(monkeypatch, *, tool_id="mock:gen", task_types=("text-to-image",)):
    """Expose a single mock tool so `from stimma.tools.<task> import gen` resolves
    in the run_code sandbox (the import binding is built from the live registry)."""
    desc = _MockDescriptor(task_types=list(task_types))

    class _Reg:
        def list_all_tools(self):
            return [(tool_id, None, desc)]

    monkeypatch.setattr(
        "providers.registry.ProviderRegistry.get_instance",
        lambda *a, **k: _Reg(),
    )


@pytest.mark.asyncio
async def test_run_code_tool_registered_and_prompt_documented():
    tool = get_tool("run_code")
    assert tool is not None
    assert any(t["function"]["name"] == "run_code" for t in get_tools_schema())
    assert "run_code" in get_system_prompt()
    # run_code is intentionally NOT gated: it's confined to its workspace + Stimma APIs,
    # so the approval prompt added only friction. Shell is the sole gated capability.
    assert "run_code" not in GATED_TOOLS


@pytest.mark.asyncio
async def test_create_layout_tool_registered_and_prompt_documents_workspace_images():
    tool_def = get_tool("create_layout")
    assert tool_def is not None
    schema = [t for t in get_tools_schema() if t["function"]["name"] == "create_layout"]
    assert len(schema) == 1

    description = schema[0]["function"]["description"]
    assert "library(action='get', media_id=...)" in description
    assert "guessed filenames" in description or "Do not" in description
    assert "absolute filesystem paths" in description


@pytest.mark.asyncio
async def test_run_code_captures_stdout_and_blocks_unsafe_imports(session, test_chat, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    ok = await run_code(
        code="import math\nprint(math.ceil(1.2))",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    blocked = await run_code(
        code="import subprocess",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert ok == "2"
    assert "ImportError" in blocked
    assert "subprocess" in blocked


@pytest.mark.asyncio
async def test_run_code_show_and_library_save_create_records(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    workspace.mkdir()
    output_dir.mkdir()

    events = []

    class _FakeWsManager:
        async def broadcast(self, event, payload):
            events.append((event, payload))

    monkeypatch.setattr("utils.websocket.ws_manager", _FakeWsManager())
    monkeypatch.setattr("agent.v2.tools.library._get_default_folder", lambda _=None: str(output_dir))

    result = await run_code(
        code=(
            "img = Image.new('RGB', (32, 24), color=(12, 34, 56))\n"
            "img.save('made.png')\n"
            "stimma.show('made.png')\n"
            "saved = await stimma.library.save('made.png', tags=['generated'])\n"
            "print(saved['media_id'])\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    # run_code appends "Already displayed N items..." after stdout
    saved_media_id = int(result.strip().split()[0])
    assert saved_media_id > 0

    display_items = (
        await session.execute(
            select(ChatItem).where(
                ChatItem.chat_id == test_chat.id,
                ChatItem.item_type == "media_display",
            )
        )
    ).scalars().all()
    assert len(display_items) == 1
    assert any(event == "chat_item_created" for event, _payload in events)

    saved_media = await session.get(MediaItem, saved_media_id)
    assert saved_media is not None
    assert saved_media.file_path.startswith(str(output_dir))
    assert saved_media.file_hash
    assert saved_media.width == 32
    assert saved_media.height == 24


@pytest.mark.asyncio
async def test_run_code_library_get_copies_media_to_workspace(session, test_chat, tmp_path):
    source_dir = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source_dir.mkdir()
    workspace.mkdir()
    image_path = source_dir / "source.png"
    file_hash = generate_test_image(image_path, width=20, height=10)
    media = await create_media_item(
        session,
        file_path=image_path,
        file_hash=file_hash,
        width=20,
        height=10,
    )

    result = await run_code(
        code=f"info = await stimma.library.get(media_id={media.id})\nprint(info['filename'])",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert result.strip() == "source.png"
    assert (workspace / "source.png").exists()


@pytest.mark.asyncio
async def test_run_code_sdk_call_tool_and_save_preserves_lineage(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    source_dir = tmp_path / "source"
    workspace.mkdir()
    output_dir.mkdir()
    source_dir.mkdir()

    parent_path = source_dir / "parent.png"
    parent_hash = generate_test_image(parent_path, width=18, height=12)
    parent = await create_media_item(
        session,
        file_path=parent_path,
        file_hash=parent_hash,
        width=18,
        height=12,
    )

    tool_output = workspace / "tool-output.png"
    generate_test_image(tool_output, width=64, height=48, color=(90, 10, 220))

    async def _fake_execute_call_tool(*, tool_id, parameters=None, **kwargs):
        params = parameters or {}
        return {
            "media_id": 999,
            "path": str(tool_output),
            "width": 64,
            "height": 48,
            "seed": 1234,
            "tool_id": tool_id,
            "tool_name": "Mock Tool",
            "task_type": "image-to-image",
            "parameters": params,
            "input_media_ids": list(params.get("input_images") or []),
            "duration_ms": 12,
        }

    monkeypatch.setattr("agent.v2.code_runtime.execute_call_tool", _fake_execute_call_tool)
    monkeypatch.setattr("agent.v2.tools.library._get_default_folder", lambda _=None: str(output_dir))
    _patch_mock_registry(monkeypatch, task_types=("image-to-image",))

    # Pre-allow the mock tool at chat level so the in-run permission gate doesn't
    # raise a card and park waiting for a user that doesn't exist in tests.
    test_chat.agent_tool_config = json.dumps({"allowed_tools": ["mock:gen"]})
    await session.commit()

    async def _noop_validate(*args, **kwargs):
        return []
    monkeypatch.setattr("agent.v2.code_lint.validate_hardcoded_refs", _noop_validate)

    result = await run_code(
        code=(
            "from stimma.tools.image_to_image import gen\n"
            f"generated = await gen(prompt='edit', input_images=[{parent.id}], steps=6)\n"
            "saved = await stimma.library.save(generated)\n"
            "print(json.dumps(saved))\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    json_text = result.split("\n\n<system-reminder>", 1)[0].strip()
    saved = json.loads(json_text)
    saved_media = await session.get(MediaItem, saved["media_id"])
    assert saved_media is not None
    assert saved_media.tool_id == "mock:gen"

    lineage_rows = (
        await session.execute(
            select(MediaLineage).where(MediaLineage.media_id == saved["media_id"])
        )
    ).scalars().all()
    assert len(lineage_rows) == 1
    assert lineage_rows[0].source_media_id == parent.id
    assert lineage_rows[0].relationship_type == "derived"


@pytest.mark.asyncio
async def test_run_code_show_tool_result_prefers_media_id(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    source_dir = tmp_path / "source"
    workspace.mkdir()
    source_dir.mkdir()

    external_output = source_dir / "generated.png"
    file_hash = generate_test_image(external_output, width=40, height=30, color=(10, 140, 220))

    media = await create_media_item(
        session,
        file_path=external_output,
        file_hash=file_hash,
        width=40,
        height=30,
    )

    class _FakeWsManager:
        async def broadcast(self, event, payload):
            return None

    async def _fake_execute_call_tool(*, tool_id, parameters=None, **kwargs):
        return {
            "media_id": media.id,
            "path": str(external_output),
            "width": 40,
            "height": 30,
            "seed": 5,
            "tool_id": tool_id,
            "tool_name": "Mock Tool",
            "task_type": "text-to-image",
            "parameters": parameters or {},
            "input_media_ids": [],
            "duration_ms": 7,
        }

    monkeypatch.setattr("agent.v2.code_runtime.execute_call_tool", _fake_execute_call_tool)
    monkeypatch.setattr("utils.websocket.ws_manager", _FakeWsManager())
    _patch_mock_registry(monkeypatch, task_types=("text-to-image",))

    # Pre-allow the mock tool at chat level so the in-run permission gate doesn't
    # raise a card and park waiting for a user that doesn't exist in tests.
    test_chat.agent_tool_config = json.dumps({"allowed_tools": ["mock:gen"]})
    await session.commit()

    async def _noop_validate(*args, **kwargs):
        return []
    monkeypatch.setattr("agent.v2.code_lint.validate_hardcoded_refs", _noop_validate)

    await run_code(
        code=(
            "from stimma.tools.text_to_image import gen\n"
            "generated = await gen(prompt='cat')\n"
            "stimma.show(generated)\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    display_item = (
        await session.execute(
            select(ChatItem).where(
                ChatItem.chat_id == test_chat.id,
                ChatItem.item_type == "media_display",
            )
        )
    ).scalars().one()
    display_data = json.loads(display_item.item_metadata)["display_data"]
    row = display_data["rows"][0]
    assert row["output"]["media_id"] == media.id
    assert "workspace_url" not in row["output"]


@pytest.mark.asyncio
async def test_run_code_show_auto_saves_external_paths_to_library(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    source_dir = tmp_path / "source"
    workspace.mkdir()
    output_dir.mkdir()
    source_dir.mkdir()

    external = source_dir / "outside.png"
    generate_test_image(external, width=22, height=14)

    class _FakeWsManager:
        async def broadcast(self, event, payload):
            return None

    monkeypatch.setattr("utils.websocket.ws_manager", _FakeWsManager())
    monkeypatch.setattr("agent.v2.tools.library._get_default_folder", lambda _=None: str(output_dir))

    await run_code(
        code=f"stimma.show(r'{external}')",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    display_item = (
        await session.execute(
            select(ChatItem).where(
                ChatItem.chat_id == test_chat.id,
                ChatItem.item_type == "media_display",
            )
        )
    ).scalars().one()
    display_data = json.loads(display_item.item_metadata)["display_data"]
    row = display_data["rows"][0]
    # show() now auto-saves paths to library, so we get a media_id not a workspace_url
    assert "media_id" in row["output"]
    assert row["output"]["media_id"] > 0


@pytest.mark.asyncio
async def test_run_code_llm_uses_sdk_helper(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    from dataclasses import dataclass, field
    from llm import LLMResponse, Usage

    class _FakeConfig:
        def get_model(self):
            return "mock-model"

        def get_api_base(self):
            return "http://fake"

        def get_api_key(self):
            return "dummy"

    async def _fake_get_chat_llm_config(_model_slug, role="agent"):
        return _FakeConfig()

    async def _fake_llm_completion(config, messages, **kwargs):
        assert config.get_model() == "mock-model"
        return LLMResponse(
            content="LLM output",
            usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setattr("agent.v2.code_runtime.get_chat_llm_config", _fake_get_chat_llm_config)
    monkeypatch.setattr("agent.v2.code_runtime.llm_completion", _fake_llm_completion)

    result = await run_code(
        code=(
            "reply = await stimma.llm('say hi')\n"
            "print(reply)\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert result == "LLM output"

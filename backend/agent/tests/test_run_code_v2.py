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
    # The denial points at the sanctioned ffmpeg surface instead of dead-ending.
    assert "stimma.ffmpeg" in blocked


@pytest.mark.asyncio
@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed")
async def test_run_code_ffmpeg_and_ffprobe_in_workspace(session, test_chat, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await run_code(
        code=(
            "r = await stimma.ffmpeg('-y', '-f', 'lavfi', '-i', 'color=c=red:s=64x64:d=1', "
            "'-pix_fmt', 'yuv420p', 'out.mp4')\n"
            "print(r.returncode)\n"
            "p = await stimma.ffprobe('-v', 'error', '-show_entries', 'format=duration', "
            "'-of', 'csv=p=0', 'out.mp4')\n"
            "print(round(float(p.stdout.strip())))\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert result.splitlines()[:2] == ["0", "1"]
    assert (workspace / "out.mp4").exists()


@pytest.mark.asyncio
async def test_run_code_ffmpeg_rejects_paths_outside_workspace(session, test_chat, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await run_code(
        code="await stimma.ffmpeg('-i', '/etc/passwd', 'out.mp4')",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert "PermissionError" in result
    assert "workspace" in result


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
            "stimma.show('made.png', role='final')\n"
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
    assert saved_media.storage_object_id is not None
    assert not saved_media.file_path.startswith(str(output_dir))
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
async def test_run_code_library_queries_and_graph_discovery(session, test_chat, tmp_path):
    result = await run_code(
        code=(
            "schema = await stimma.library.schema()\n"
            "assert 'loras' in schema['filters']\n"
            "page = await stimma.library.query(filters={'models': 'nonexistent-library-query-model'}, scope='media')\n"
            "assert page['total'] == 0\n"
            "options = await stimma.library.options('loras', query='nonexistent-library-query-lora')\n"
            "assert options['items'] == []\n"
            "graph = await stimma.library.lineage(media_ids=[99999999], direction='ancestors')\n"
            "assert graph['edges'] == []\n"
            "details = await stimma.library.inspect([99999999])\n"
            "assert details['items'][0]['status'] == 'missing'\n"
            "print('library query SDK works')"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=tmp_path,
    )
    assert result.strip() == "library query SDK works"


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
async def test_run_code_tool_result_path_can_feed_next_tool(session, test_chat, tmp_path, monkeypatch):
    """ToolResult.path is a Path, but chained STP calls cross JSON boundaries."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = []

    async def _fake_execute_call_tool(*, tool_id, parameters=None, **kwargs):
        calls.append(parameters or {})
        index = len(calls)
        return {
            "media_id": 900 + index,
            "path": str(workspace / f"result-{index}.png"),
            "width": 64,
            "height": 64,
            "seed": index,
            "tool_id": tool_id,
            "tool_name": "Mock Tool",
            "task_type": "image-to-image",
            "parameters": parameters or {},
            "input_media_ids": [],
            "duration_ms": 1,
        }

    monkeypatch.setattr("agent.v2.code_runtime.execute_call_tool", _fake_execute_call_tool)
    _patch_mock_registry(monkeypatch, task_types=("image-to-image",))
    test_chat.agent_tool_config = json.dumps({"allowed_tools": ["mock:gen"]})
    await session.commit()

    async def _noop_validate(*args, **kwargs):
        return []
    monkeypatch.setattr("agent.v2.code_lint.validate_hardcoded_refs", _noop_validate)

    result = await run_code(
        code=(
            "from stimma.tools.image_to_image import gen\n"
            "first = await gen(prompt='first')\n"
            "second = await gen(prompt='second', input_images=[first.path])\n"
            "print(second.media_id)\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert result.split("\n\n<system-reminder>", 1)[0].strip() == "902"
    assert calls[1]["input_images"] == [str(workspace / "result-1.png")]


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
            "stimma.show(generated, role='final')\n"
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
        code=f"stimma.show(r'{external}', role='final')",
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


@pytest.mark.asyncio
async def test_run_code_common_builtins_available(session, test_chat, tmp_path):
    """The introspection builtins and exception classes agents reach for
    reflexively (type, dir, repr, except ValueError, class definitions) must
    work — each missing name costs the agent a failed round-trip that reads
    as a bug, not a boundary."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = await run_code(
        code=(
            "print(type([]).__name__)\n"
            "print('upper' in dir(''))\n"
            "print(repr('x'))\n"
            "try:\n"
            "    int('nope')\n"
            "except ValueError:\n"
            "    print('caught')\n"
            "class Point:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "print(Point(7).x)\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert result.splitlines() == ["list", "True", "'x'", "caught", "7"]


@pytest.mark.asyncio
async def test_run_code_os_is_workspace_scoped(session, test_chat, tmp_path):
    """``os`` provides the common filesystem ops jailed to the workspace, and
    names the boundary clearly for anything it doesn't provide."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("hello")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    result = await run_code(
        code=(
            "import os\n"
            "print(os.getcwd() == str(__import__('pathlib').Path.cwd()))\n"
            "print(sorted(os.listdir('.')))\n"
            "print(os.path.exists('a.txt'))\n"
            "os.remove('a.txt')\n"
            "print(os.path.exists('a.txt'))\n"
            "print([f for _, _, files in os.walk('.') for f in files])\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    lines = result.splitlines()
    assert lines[1] == "['a.txt']"
    assert lines[2] == "True"
    assert lines[3] == "False"
    assert lines[4] == "[]"

    denied = await run_code(
        code=f"import os\nos.remove({str(outside)!r})\n",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    assert "PermissionError" in denied
    assert outside.exists()

    unavailable = await run_code(
        code="import os\nos.system('true')\n",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    assert "os.system is not available in run_code" in unavailable


@pytest.mark.asyncio
async def test_run_code_glob_is_workspace_scoped(session, test_chat, tmp_path):
    """``glob`` matches inside the workspace (relative patterns, recursive
    ``**``) and refuses patterns whose base escapes the jail."""
    workspace = tmp_path / "workspace"
    (workspace / "sub").mkdir(parents=True)
    (workspace / "a.png").touch()
    (workspace / "b.txt").touch()
    (workspace / "sub" / "c.png").touch()
    (tmp_path / "outside.png").touch()

    result = await run_code(
        code=(
            "import glob\n"
            "from glob import glob as g\n"
            "print(sorted(glob.glob('*.png')))\n"
            "print(sorted(g('**/*.png', recursive=True)))\n"
            "print(sorted(glob.iglob('*.txt')))\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    assert result.splitlines() == [
        "['a.png']",
        "['a.png', 'sub/c.png']",
        "['b.txt']",
    ]

    denied = await run_code(
        code="import glob\nglob.glob('../*')\n",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    assert "PermissionError" in denied

    unavailable = await run_code(
        code="import glob\nglob.glob0('.', 'x')\n",
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )
    assert "glob.glob0 is not available in run_code" in unavailable


@pytest.mark.asyncio
async def test_library_sdk_ergonomics(session, test_chat, tmp_path, monkeypatch):
    """The library SDK accepts the shapes agents naturally produce: save() takes
    a PIL Image or path= alias, and get() results support attribute access
    (info.path) alongside dict access — mirroring ToolResult."""
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    workspace.mkdir()
    output_dir.mkdir()

    class _FakeWsManager:
        async def broadcast(self, event, payload):
            pass

    monkeypatch.setattr("utils.websocket.ws_manager", _FakeWsManager())
    monkeypatch.setattr("agent.v2.tools.library._get_default_folder", lambda _=None: str(output_dir))

    result = await run_code(
        code=(
            "canvas = Image.new('RGB', (20, 20), (255, 255, 255))\n"
            "saved = await stimma.library.save(item=canvas, tags=['composite'])\n"
            "info = await stimma.library.get(saved['media_id'])\n"
            "print(info.media_id == saved['media_id'])\n"
            "print(info['media_id'] == saved['media_id'])\n"
            "img2 = Image.new('RGB', (10, 10), (0, 0, 0))\n"
            "img2.save('via_path.png')\n"
            "saved2 = await stimma.library.save(path='via_path.png')\n"
            "print(saved2['media_id'] > 0)\n"
        ),
        session=session,
        chat_id=test_chat.id,
        workspace_dir=workspace,
    )

    assert result.splitlines() == ["True", "True", "True"], result


@pytest.mark.asyncio
async def test_dotted_package_imports_follow_python_semantics(session, test_chat, tmp_path):
    result = await run_code(
        code="""import PIL.Image as Image
import PIL.Image
from PIL.Image import new
import numpy.linalg as linalg
image = Image.new('RGB', (8, 9))
image.save('image.png')
print(PIL.Image.open('image.png').size, new('RGB', (2, 3)).size)
print(round(linalg.norm([3, 4])))
import urllib.parse
import urllib.parse as parse
import os.path as path
print(urllib.parse.quote('a b'), parse.quote('c d'), path.basename('a/b'))
""",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    )
    assert result == "(8, 9) (2, 3)\n5\na%20b c%20d b"


@pytest.mark.asyncio
async def test_await_sync_value_hint(session, test_chat, tmp_path):
    result = await run_code(
        code="def setter(): pass\nawait setter()",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    )
    assert "returned a synchronous value" in result
    assert "remove `await`" in result


@pytest.mark.asyncio
async def test_workspace_file_checksums_need_no_shell(session, test_chat, tmp_path):
    (tmp_path / "asset.bin").write_bytes(b"abc")
    result = await run_code(
        code="import hashlib\nprint(hashlib.sha256(open('asset.bin', 'rb').read()).hexdigest())",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    )
    assert result == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.asyncio
async def test_python_reads_registered_skill_resources_without_write_access(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pack = tmp_path / "pack"
    (pack / "references").mkdir(parents=True)
    cover = pack / "references/cover.html"
    cover.write_text("<p>Cover</p>")
    monkeypatch.setattr("agent.v2.tools._workspace_files.skill_resource_roots", lambda: {"test": pack})
    # No symlink is needed: the virtual mount also works on Windows.
    result = await run_code(
        code="""import glob, os
path = '.stimma/skills/test/references/cover.html'
print(open(path).read())
print(glob.glob('.stimma/skills/test/references/*.html'))
print(os.listdir('.stimma/skills/test/references'))
for operation in (lambda: open(path, 'w'), lambda: os.remove(path)):
    try:
        operation()
    except PermissionError:
        print('read-only')
""",
        session=session, chat_id=test_chat.id, workspace_dir=workspace,
    )
    assert result.splitlines() == [
        '<p>Cover</p>', "['.stimma/skills/test/references/cover.html']",
        "['cover.html']", 'read-only', 'read-only',
    ], result
    assert cover.read_text() == '<p>Cover</p>'


@pytest.mark.asyncio
async def test_preloaded_sdk_can_be_used_before_redundant_import(session, test_chat, tmp_path):
    result = await run_code(
        code="before = stimma\nimport stimma\nprint(before is stimma)",
        session=session, chat_id=test_chat.id, workspace_dir=tmp_path,
    )
    assert result == "True"


@pytest.mark.asyncio
async def test_concurrent_code_keeps_relative_image_paths_in_its_workspace(session, test_chat, tmp_path):
    import asyncio
    import os
    from PIL import Image

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(first / "image.png")
    Image.new("RGB", (2, 2), (0, 255, 0)).save(second / "image.png")
    original = Path.cwd()
    try:
        results = await asyncio.gather(*[
            run_code(
                code="import asyncio\nfrom PIL import Image\nawait asyncio.sleep(0.02)\nprint(Image.open('image.png').getpixel((0, 0)))",
                session=session, chat_id=test_chat.id, workspace_dir=workspace,
            )
            for workspace in (first, second)
        ])
        assert results == ["(255, 0, 0)", "(0, 255, 0)"]
        assert Path.cwd() == original
    finally:
        os.chdir(original)


@pytest.mark.asyncio
async def test_code_workspace_restores_after_cancellation_and_allows_nested_calls(tmp_path):
    import asyncio
    from agent.v2.code_runtime import _code_workspace

    original = Path.cwd()
    entered = asyncio.Event()

    async def cancelled_code():
        async with _code_workspace(tmp_path):
            async with _code_workspace(tmp_path):
                assert Path.cwd() == tmp_path
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(cancelled_code())
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert Path.cwd() == original
    async with _code_workspace(tmp_path):
        assert Path.cwd() == tmp_path
    assert Path.cwd() == original


@pytest.mark.asyncio
async def test_copy_files_and_skill_resources_stays_in_workspace(session, test_chat, tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    pack = tmp_path / 'pack'
    pack.mkdir()
    (pack / 'cover.html').write_text('<p>Cover</p>')
    outside = tmp_path / 'private.txt'
    outside.write_text('private')
    monkeypatch.setattr('agent.v2.tools._workspace_files.skill_resource_roots', lambda: {'test': pack})
    result = await run_code(
        code="""import shutil, os
shutil.copyfile('.stimma/skills/test/cover.html', 'cover.html')
os.mkdir('copies')
shutil.copy2('cover.html', 'copies')
print(open('copies/cover.html').read())
for source, destination in [('cover.html', '../outside.html'), ('../private.txt', 'private.txt'), ('cover.html', '.stimma/skills/test/cover.html')]:
    try:
        shutil.copy(source, destination)
    except PermissionError:
        print('blocked')
""",
        session=session, chat_id=test_chat.id, workspace_dir=workspace,
    )
    assert result.splitlines() == ['<p>Cover</p>', 'blocked', 'blocked', 'blocked']
    assert not (tmp_path / 'outside.html').exists()
    assert not (workspace / 'private.txt').exists()


def test_glob_preserves_explicit_project_workspace_paths(tmp_path):
    from agent.v2.code_runtime import _SafeGlob

    workspace, project = tmp_path / 'chat', tmp_path / 'project'
    workspace.mkdir()
    project.mkdir()
    (project / 'notes.txt').write_text('Notes')
    assert _SafeGlob(workspace, project).glob('../project/*.txt') == ['../project/notes.txt']


def test_tool_receipt_identifies_existing_workspace_file(tmp_path):
    from agent.v2.code_runtime import ToolResult, _format_run_code_receipt

    result = ToolResult(path=tmp_path / 'generated.png', media_id=7)
    receipt = _format_run_code_receipt([result], [], workspace_dir=tmp_path)
    assert "workspace_file='generated.png'" in receipt
    assert 'already exist in this chat' in receipt
    assert str(tmp_path) not in receipt

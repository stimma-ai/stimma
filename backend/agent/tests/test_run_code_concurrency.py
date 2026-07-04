"""Regression test for the run_code / asyncio.gather() concurrent-session bug.

The run_code sandbox (system prompt + the parameter-grid skill) teaches
`asyncio.gather()` over sequential `stimma.tools.*` calls for speed. Every
such call goes through `StimmaSDK._dispatch_tool` -> `execute_call_tool`,
which used to touch the database through the SDK's single shared
`AsyncSession` (`self.session`) in a few spots. SQLAlchemy's `AsyncSession`
is not safe for concurrent use — overlapping operations from gather()
branches raise:

    sqlalchemy.exc.InvalidRequestError: This session is provisioning a new
    connection; concurrent operations are not permitted

...mid-batch, after some generations had already saved, and the agent would
then retry, leaving duplicate media in the library.

Three call sites used to run DB work directly on that shared session instead
of a fresh, per-call one:
  - agent/v2/tools/call_tool.py: `wait_for_jobs(..., session, ...)` — the
    job-status polling loop, the single biggest collision window since every
    generation goes through it.
  - agent/v2/tools/call_tool.py: `_resolve_media_path(session, ...)` — the
    controlnet preprocessing branch (covered by
    ``test_execute_call_tool_concurrent_controlnet_no_session_conflict``
    below).
  - agent/v2/code_runtime.py: `resolve_params_from(self.session, ...)` — run
    whenever a gather() branch passes `params_from=`.

This test drives the real `run_code` -> `gen()` -> `execute_call_tool` path
with three concurrent generations (`asyncio.gather`, all using
`params_from=`) and a concurrency-hostile fake `wait_for_jobs` that performs
real `session.execute()` calls interleaved with `asyncio.sleep()` — exactly
reproducing the crash if the session it receives is the shared SDK session
rather than a fresh one per call. Reverting either the `wait_for_jobs` fix or
the `resolve_params_from` fix should make this test fail with the
"concurrent operations are not permitted" error; with both fixes in place it
should pass.

IMPORTANT: SQLAlchemy's AsyncSession only races on a *fresh* (never-yet-used)
session — once a session has executed+committed once, the connection is
already provisioned and a second concurrent access does not reliably
reproduce the crash (verified empirically). So all test *setup* (chat,
library rows) is done through a separate, throwaway session; the `session`
fixture handed to `run_code` is never touched before the gather() runs.
"""

import asyncio
import json
from dataclasses import dataclass, field

import pytest
from sqlalchemy import text

import agent.v2.code_runtime as code_runtime
import agent.v2.tools.call_tool as ct
from agent.v2.tools.run_code import run_code
from database import Chat
from tests.helpers.media import create_media_item, generate_test_image

_CONCURRENCY_ERROR_SNIPPET = "concurrent operations are not permitted"


@dataclass
class _MockDescriptor:
    name: str = "Mock Tool"
    description: str = "A mock generation tool."
    task_types: list = field(default_factory=lambda: ["text-to-image"])
    parameter_schema: dict = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "steps": {"type": "integer", "default": 20},
        },
        "required": ["prompt"],
    })
    task_type: str = None
    subtitle: str = ""


class _FakeProvider:
    provider_id = "test-provider"


class _FakeRegistry:
    """Stands in for ProviderRegistry.get_instance(). Supports both
    list_all_tools() (used by tool_fs to build the `stimma.tools.*` import
    namespace) and get_tool() (used by execute_call_tool's real dispatch and
    by resolve_params_from's cross-tool key filtering)."""

    def __init__(self, tool_id, descriptor):
        self._tool_id = tool_id
        self._descriptor = descriptor

    def list_all_tools(self):
        return [(self._tool_id, None, self._descriptor)]

    def get_tool(self, tool_id):
        if tool_id == self._tool_id:
            return (_FakeProvider(), self._descriptor)
        return None


class _FakeQueue:
    def __init__(self):
        self._next_job_id = 0

    async def submit_job(self, **kwargs):
        self._next_job_id += 1
        return self._next_job_id

    def _resolve_backend_info(self, tool_id, _override, _provider_id):
        return ("test-backend", None)

    async def cancel_job(self, job_id):
        pass


class _FakeDb:
    def __init__(self, maker):
        self.async_session_maker = maker


class _FakeDbRegistry:
    def __init__(self, maker):
        self._db = _FakeDb(maker)

    def get_database(self, profile_id):
        return self._db


@pytest.mark.asyncio
async def test_run_code_gather_concurrent_generations_no_session_conflict(
    session, session_factory, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    source_dir = tmp_path / "source"
    workspace.mkdir()
    output_dir.mkdir()
    source_dir.mkdir()

    tool_id = "mock:gen"
    descriptor = _MockDescriptor()

    # Do ALL setup (chat + library rows) through a throwaway session — never
    # the `session` fixture that will become the SDK's shared session, so it
    # stays in its pristine, never-yet-provisioned state going into the
    # concurrent gather() below (see module docstring).
    async with session_factory() as setup_session:
        chat = Chat(name="Concurrency Test Chat")
        setup_session.add(chat)
        await setup_session.commit()
        await setup_session.refresh(chat)
        chat_id = chat.id

        parent_path = source_dir / "parent.png"
        parent_hash = generate_test_image(parent_path, width=16, height=16)
        parent = await create_media_item(
            setup_session,
            file_path=parent_path,
            file_hash=parent_hash,
            width=16,
            height=16,
            tool_id=tool_id,
            generation_metadata=json.dumps({
                "tool_id": tool_id,
                "parameters": {"prompt": "source prompt", "steps": 8},
            }),
        )
        parent_id = parent.id

        output_media_ids = []
        for i in range(3):
            out_path = output_dir / f"out-{i}.png"
            out_hash = generate_test_image(out_path, width=32, height=32)
            media = await create_media_item(
                setup_session,
                file_path=out_path,
                file_hash=out_hash,
                width=32,
                height=32,
            )
            output_media_ids.append(media.id)

    # Fresh sessions created by the fix all route through
    # get_database_registry().get_database(get_current_profile()). Point
    # that at the same underlying test database via session_factory instead
    # of a real, registered profile (agent/tests/conftest.py has no profile
    # registry set up at all).
    monkeypatch.setattr(
        "database_registry.get_database_registry",
        lambda: _FakeDbRegistry(session_factory),
    )
    monkeypatch.setattr(ct, "get_current_profile", lambda: "test-profile")
    monkeypatch.setattr(code_runtime, "get_current_profile", lambda: "test-profile")

    fake_registry = _FakeRegistry(tool_id, descriptor)
    monkeypatch.setattr(
        "providers.registry.ProviderRegistry.get_instance",
        staticmethod(lambda: fake_registry),
    )

    fake_queue = _FakeQueue()
    monkeypatch.setattr(ct, "get_generation_queue", lambda: fake_queue)
    monkeypatch.setattr(ct, "_get_default_folder", lambda *_a, **_k: str(output_dir))

    call_counter = {"n": 0}

    async def _fake_wait_for_jobs(job_ids, wf_session, status_checker=None, **kwargs):
        """Mimics wait_for_jobs's real polling loop: several DB touches on
        the received session, interleaved with awaits, for the entire
        generation duration. Reproduces the crash if `wf_session` is the
        shared SDK session instead of a fresh one per call."""
        idx = call_counter["n"]
        call_counter["n"] += 1
        for _ in range(6):
            await wf_session.execute(text("SELECT 1"))
            await asyncio.sleep(0.005)
        media_id = output_media_ids[idx % len(output_media_ids)]
        return [media_id], [], 0, {job_ids[0]: media_id}

    monkeypatch.setattr(ct, "wait_for_jobs", _fake_wait_for_jobs)

    code = (
        "from stimma.tools.text_to_image import gen\n"
        "results = await asyncio.gather(*[\n"
        f"    gen(prompt=f'variant {{i}}', params_from={parent_id}) for i in range(3)\n"
        "])\n"
        "print(len(results))\n"
    )

    result = await run_code(
        code=code,
        session=session,
        chat_id=chat_id,
        workspace_dir=workspace,
    )

    assert _CONCURRENCY_ERROR_SNIPPET not in result, result
    assert not result.startswith("Error"), result
    assert result.strip().splitlines()[0] == "3", result


@pytest.mark.asyncio
async def test_execute_call_tool_concurrent_controlnet_no_session_conflict(
    session, session_factory, tmp_path, monkeypatch
):
    """Same failure mode, isolated to the controlnet preprocessing branch's
    `_resolve_media_path(session, media_id_val)` call (call_tool.py ~line
    348)."""
    workspace = tmp_path / "workspace"
    source_dir = tmp_path / "source"
    workspace.mkdir()
    source_dir.mkdir()

    tool_id = "mock:cn-gen"

    @dataclass
    class _CnDescriptor:
        name: str = "Mock CN Tool"
        description: str = "A mock controlnet-capable tool."
        task_types: list = field(default_factory=lambda: ["image-to-image"])
        parameter_schema: dict = field(default_factory=lambda: {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "input_images": {
                    "type": "array",
                    "x-controlnet": ["canny"],
                },
            },
            "required": ["prompt"],
        })
        task_type: str = None
        subtitle: str = ""

    descriptor = _CnDescriptor()

    media_id_to_path = {}
    async with session_factory() as setup_session:
        input_images = []
        for i in range(3):
            img_path = source_dir / f"input-{i}.png"
            img_hash = generate_test_image(img_path, width=24, height=24)
            media = await create_media_item(
                setup_session,
                file_path=img_path,
                file_hash=img_hash,
                width=24,
                height=24,
            )
            input_images.append(media.id)
            media_id_to_path[media.id] = str(img_path)

    monkeypatch.setattr(
        "database_registry.get_database_registry",
        lambda: _FakeDbRegistry(session_factory),
    )
    monkeypatch.setattr(ct, "get_current_profile", lambda: "test-profile")

    fake_registry = _FakeRegistry(tool_id, descriptor)
    monkeypatch.setattr(
        "providers.registry.ProviderRegistry.get_instance",
        staticmethod(lambda: fake_registry),
    )

    fake_queue = _FakeQueue()
    monkeypatch.setattr(ct, "get_generation_queue", lambda: fake_queue)
    monkeypatch.setattr(ct, "_get_default_folder", lambda *_a, **_k: str(workspace))

    async def _fake_wait_for_jobs(job_ids, wf_session, status_checker=None, **kwargs):
        # Not the subject of this test — resolve instantly, no media found.
        return [], ["no-op"], 0, {}

    async def _fake_resolve_media_path(rp_session, media_id_val):
        """Mimics _resolve_media_path's real DB read, interleaved with
        awaits, on whatever session it's handed."""
        for _ in range(6):
            await rp_session.execute(text("SELECT 1"))
            await asyncio.sleep(0.005)
        return media_id_to_path[media_id_val]

    async def _fake_preprocess(source_path, preprocessor, params):
        return source_path, 24, 24

    monkeypatch.setattr(ct, "wait_for_jobs", _fake_wait_for_jobs)
    monkeypatch.setattr(
        "agent.v2.tools.preprocess_controlnet._resolve_media_path",
        _fake_resolve_media_path,
    )
    monkeypatch.setattr("controlnet.preprocess", _fake_preprocess)

    async def _run_one(image_id):
        try:
            return await ct.execute_call_tool(
                tool_id=tool_id,
                parameters={
                    "prompt": "edit it",
                    "input_images": [image_id],
                    "controlnet": "canny",
                },
                session=session,
                chat_id=1,
                workspace_dir=str(workspace),
                interrupt_checker=None,
            )
        except RuntimeError as e:
            # The fake wait_for_jobs above always reports failure — that's
            # fine, we only care whether the concurrent _resolve_media_path
            # calls raced on the shared session before getting there.
            return str(e)

    results = await asyncio.gather(*[_run_one(i) for i in input_images])

    for r in results:
        text_repr = r if isinstance(r, str) else json.dumps(r)
        assert _CONCURRENCY_ERROR_SNIPPET not in text_repr, text_repr

"""Unit tests for the user-tools provider + flow freezer.

No GPU / no flow execution — these cover descriptor building from ``UserTool``
rows and the freeze gate (validate + persist + reject invalid task/schema).
"""

import json

import pytest
from sqlalchemy import select

from core.profile_context import ProfileScope
from database import Flow, UserTool
from flow_runtime.paths import get_flow_program_path
from providers.user_tools import UserToolsProvider
from user_tools_service import (
    freeze_flow_to_tool,
    infer_freeze_defaults,
    list_backing_tools_with_drift,
    update_user_tool,
)


_T2I_PARAM_SCHEMA = {
    "type": "object",
    "properties": {"prompt": {"type": "string"}},
    "required": ["prompt"],
}
_ASSETS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"assets": {"type": "array", "description": "assets"}},
}

_PROGRAM_TEXT = "# frozen flow program\noutput = 1\n"


async def _seed_user_tool(session, **overrides) -> UserTool:
    flow_id = overrides.get("flow_id")
    if "flow_id" not in overrides:
        flow = Flow(name=f"{overrides.get('name', 'Frozen')} source")
        session.add(flow)
        await session.flush()
        flow_id = flow.id
    row = UserTool(
        name=overrides.get("name", "My Frozen Tool"),
        description=overrides.get("description", "a frozen flow"),
        flow_id=flow_id,
        program_text=overrides.get("program_text", _PROGRAM_TEXT),
        task_types=json.dumps(overrides.get("task_types", ["text-to-image"])),
        parameter_schema=json.dumps(overrides.get("parameter_schema", _T2I_PARAM_SCHEMA)),
        output_schema=json.dumps(overrides.get("output_schema", _ASSETS_OUTPUT_SCHEMA)),
        hitl_policies=json.dumps(overrides.get("hitl_policies", {})),
        output_map=json.dumps(overrides.get("output_map", {"assets": "output"})),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Provider descriptor building
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_builds_descriptors_from_rows(db_session):
    async with db_session() as session:
        row = await _seed_user_tool(session, name="Stylize")

    provider = UserToolsProvider()
    with ProfileScope("default"):
        await provider.connect()
        tools = await provider.list_tools()

    by_name = {t.name: t for t in tools}
    assert "Stylize" in by_name

    desc = by_name["Stylize"]
    assert desc.id == f"stylize-{row.id}"  # readable slug + id
    assert desc.name == "Stylize"
    assert desc.task_type == "text-to-image"
    assert desc.task_types == ["text-to-image"]
    assert desc.parameter_schema == _T2I_PARAM_SCHEMA
    assert desc.output_schema == _ASSETS_OUTPUT_SCHEMA
    assert desc.metadata["flow_id"] == row.flow_id
    assert desc.metadata["user_tool_id"] == row.id
    assert desc.metadata["provenance"] == "user-flow"


@pytest.mark.asyncio
async def test_provider_excludes_soft_deleted_rows(db_session):
    from datetime import datetime

    async with db_session() as session:
        live = await _seed_user_tool(session, name="LiveTool")
        gone = await _seed_user_tool(session, name="DeadTool")
        gone.deleted_at = datetime.utcnow()
        await session.commit()
        gone_id = gone.id
        live_id = live.id

    provider = UserToolsProvider()
    with ProfileScope("default"):
        await provider.connect()
        tools = await provider.list_tools()

    names = {t.name for t in tools}
    assert "LiveTool" in names
    assert "DeadTool" not in names


@pytest.mark.asyncio
async def test_provider_caches_program_text_for_execution(db_session):
    """Regression: the cached row must carry ``program_text`` so ``execute`` can run
    the flow. ``UserTool.to_dict()`` omits it (kept out of API responses), which
    previously caused a ``KeyError('program_text')`` at run time."""
    async with db_session() as session:
        row = await _seed_user_tool(session, name="Runnable")

    provider = UserToolsProvider()
    with ProfileScope("default"):
        await provider.connect()

    # tool_id is now a readable slug ("runnable-<id>"); look it up by name.
    tool_id = next(
        tid for tid, d in provider._descriptors.items() if d.name == "Runnable"
    )
    cached = provider._rows[tool_id]
    assert cached.get("program_text") == _PROGRAM_TEXT


# ---------------------------------------------------------------------------
# Freezer: validate + persist + reject
# ---------------------------------------------------------------------------


async def _make_flow_with_program(session, *, input_schema, output_schema, program=_PROGRAM_TEXT):
    flow = Flow(
        name="Source Flow",
        input_schema=json.dumps(input_schema),
        output_schema=json.dumps(output_schema),
        execution_state="idle",
    )
    session.add(flow)
    await session.commit()
    await session.refresh(flow)

    program_path = get_flow_program_path(flow.id)
    program_path.parent.mkdir(parents=True, exist_ok=True)
    program_path.write_text(program)
    return flow


@pytest.mark.asyncio
async def test_freeze_flow_to_tool_validates_and_persists(db_session):
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str", "lines": 2}},
                output_schema={"output": {"type": "image"}},
            )

        async with db_session() as session:
            tool = await freeze_flow_to_tool(
                session,
                flow_id=flow.id,
                name="T2I From Flow",
                description="frozen",
                task_types=["text-to-image"],
                output_map={"assets": "output"},
                hitl_policies={},
            )
            tool_id = tool.id

        # Persisted with derived STP interface + program snapshot.
        async with db_session() as session:
            row = (
                await session.execute(select(UserTool).where(UserTool.id == tool_id))
            ).scalar_one()
            assert row.name == "T2I From Flow"
            assert row.flow_id == flow.id
            assert row.program_text == _PROGRAM_TEXT
            param_schema = json.loads(row.parameter_schema)
            assert param_schema["required"] == ["prompt"]
            assert "prompt" in param_schema["properties"]
            out_schema = json.loads(row.output_schema)
            assert "assets" in out_schema["properties"]
            assert json.loads(row.task_types) == ["text-to-image"]
            assert json.loads(row.output_map) == {"assets": "output"}


@pytest.mark.asyncio
async def test_freeze_rejects_invalid_task_schema_combo(db_session):
    """image-to-image requires input_images; a prompt-only flow must be rejected."""
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str"}},  # no input_images
                output_schema={"output": {"type": "image"}},
            )

        async with db_session() as session:
            with pytest.raises(ValueError) as excinfo:
                await freeze_flow_to_tool(
                    session,
                    flow_id=flow.id,
                    name="Bad I2I",
                    task_types=["image-to-image"],
                    output_map={"assets": "output"},
                    hitl_policies={},
                )
            assert "input_images" in str(excinfo.value)


@pytest.mark.asyncio
async def test_freeze_rejects_output_map_to_unknown_flow_output(db_session):
    """An output_map binding to an output the flow doesn't declare is rejected."""
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str"}},
                output_schema={"hero": {"type": "image"}},  # declares "hero", not "final"
            )

        async with db_session() as session:
            with pytest.raises(ValueError) as excinfo:
                await freeze_flow_to_tool(
                    session,
                    flow_id=flow.id,
                    name="Bad Output Map",
                    task_types=["text-to-image"],
                    output_map={"assets": "final"},  # "final" isn't declared
                    hitl_policies={},
                )
            assert "final" in str(excinfo.value)

        # A correct mapping to the declared output still succeeds.
        async with db_session() as session:
            tool = await freeze_flow_to_tool(
                session,
                flow_id=flow.id,
                name="Good Output Map",
                task_types=["text-to-image"],
                output_map={"assets": "hero"},
                hitl_policies={},
            )
            assert json.loads(tool.output_map) == {"assets": "hero"}


# ---------------------------------------------------------------------------
# Update: settings-edit vs resync-from-flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_resnapshots_program_and_schema(db_session):
    """resync_from_flow re-captures the *current* flow program + inputs so logic
    and input changes made in the flow propagate into the frozen tool."""
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str"}},
                output_schema={"output": {"type": "image"}},
                program="# v1 program\noutput = 1\n",
            )

        async with db_session() as session:
            tool = await freeze_flow_to_tool(
                session,
                flow_id=flow.id,
                name="Resyncable",
                task_types=["text-to-image"],
                output_map={"assets": "output"},
                hitl_policies={},
            )
            tool_id = tool.id

        # The flow changes: new program body + a new declared input.
        program_path = get_flow_program_path(flow.id)
        program_path.write_text("# v2 program\noutput = 2\n")
        async with db_session() as session:
            row = (
                await session.execute(select(Flow).where(Flow.id == flow.id))
            ).scalar_one()
            row.input_schema = json.dumps(
                {"prompt": {"type": "str"}, "strength": {"type": "float"}}
            )
            await session.commit()

        async with db_session() as session:
            await update_user_tool(
                session, user_tool_id=tool_id, resync_from_flow=True
            )

        async with db_session() as session:
            row = (
                await session.execute(select(UserTool).where(UserTool.id == tool_id))
            ).scalar_one()
            assert "v2 program" in row.program_text  # program re-snapshotted
            params = json.loads(row.parameter_schema)
            assert "strength" in params["properties"]  # new input picked up


@pytest.mark.asyncio
async def test_settings_edit_keeps_snapshot(db_session):
    """A plain settings edit must NOT pull in flow drift — the frozen snapshot
    (program + parameter_schema) is left exactly as captured."""
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str"}},
                output_schema={"output": {"type": "image"}},
                program="# v1 program\noutput = 1\n",
            )

        async with db_session() as session:
            tool = await freeze_flow_to_tool(
                session,
                flow_id=flow.id,
                name="Stable",
                task_types=["text-to-image"],
                output_map={"assets": "output"},
                hitl_policies={},
            )
            tool_id = tool.id

        # Flow drifts after freeze.
        get_flow_program_path(flow.id).write_text("# v2 DRIFT\noutput = 2\n")

        # Settings-only edit (rename) — no resync.
        async with db_session() as session:
            await update_user_tool(
                session, user_tool_id=tool_id, name="Stable (renamed)"
            )

        async with db_session() as session:
            row = (
                await session.execute(select(UserTool).where(UserTool.id == tool_id))
            ).scalar_one()
            assert row.name == "Stable (renamed)"
            assert "v1 program" in row.program_text  # snapshot untouched
            assert "DRIFT" not in row.program_text


@pytest.mark.asyncio
async def test_backing_tools_drift_flag(db_session):
    """list_backing_tools_with_drift reports has_changes only once the flow's
    program/inputs diverge from the frozen snapshot, and clears it after resync."""
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str"}},
                output_schema={"output": {"type": "image"}},
                program="# v1\noutput = 1\n",
            )

        async with db_session() as session:
            await freeze_flow_to_tool(
                session,
                flow_id=flow.id,
                name="Drifter",
                task_types=["text-to-image"],
                output_map={"assets": "output"},
                hitl_policies={},
            )

        # Fresh freeze: no drift.
        async with db_session() as session:
            tools = await list_backing_tools_with_drift(session, flow.id)
            assert len(tools) == 1
            assert tools[0]["has_changes"] is False

        # Flow program changes -> drift.
        get_flow_program_path(flow.id).write_text("# v2 changed\noutput = 2\n")
        async with db_session() as session:
            tools = await list_backing_tools_with_drift(session, flow.id)
            assert tools[0]["has_changes"] is True

        # Resync clears drift.
        async with db_session() as session:
            await update_user_tool(
                session, user_tool_id=tools[0]["id"], resync_from_flow=True
            )
        async with db_session() as session:
            tools = await list_backing_tools_with_drift(session, flow.id)
            assert tools[0]["has_changes"] is False


@pytest.mark.asyncio
async def test_slug_frozen_at_creation_survives_rename(db_session):
    """The tool id is {slug}-{id}; the slug is frozen at freeze time so a rename
    does NOT change the id (keeps pins / presets / open tabs valid)."""
    with ProfileScope("default"):
        async with db_session() as session:
            flow = await _make_flow_with_program(
                session,
                input_schema={"prompt": {"type": "str"}},
                output_schema={"output": {"type": "image"}},
            )

        async with db_session() as session:
            tool = await freeze_flow_to_tool(
                session,
                flow_id=flow.id,
                name="Sunset Maker",
                task_types=["text-to-image"],
                output_map={"assets": "output"},
                hitl_policies={},
            )
            tool_id = tool.id
            assert tool.slug == "sunset-maker"

        # Rename → slug must stay put.
        async with db_session() as session:
            await update_user_tool(
                session, user_tool_id=tool_id, name="Totally Different Name"
            )

        async with db_session() as session:
            row = (
                await session.execute(select(UserTool).where(UserTool.id == tool_id))
            ).scalar_one()
            assert row.name == "Totally Different Name"
            assert row.slug == "sunset-maker"  # frozen


@pytest.mark.asyncio
async def test_resync_without_backing_flow_raises(db_session):
    with ProfileScope("default"):
        async with db_session() as session:
            row = await _seed_user_tool(session, name="Orphan", flow_id=None)
            tool_id = row.id

        async with db_session() as session:
            with pytest.raises(ValueError) as excinfo:
                await update_user_tool(
                    session, user_tool_id=tool_id, resync_from_flow=True
                )
            assert "backing flow" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Freeze defaults inference
# ---------------------------------------------------------------------------


def test_infer_freeze_defaults_image_to_image():
    flow_dict = {
        "input_schema": {
            "prompt": {"type": "str"},
            "input_images": {"type": "list[media]"},
        },
        "output_schema": {"result": {"type": "image"}},
    }
    defaults = infer_freeze_defaults(flow_dict)
    assert defaults["task_types"] == ["image-to-image"]
    assert defaults["output_map"] == {"assets": "result"}
    assert set(defaults["exposed_inputs"]) == {"prompt", "input_images"}


def test_infer_freeze_defaults_text_to_image():
    flow_dict = {
        "input_schema": {"prompt": {"type": "str"}},
        "output_schema": {},
    }
    defaults = infer_freeze_defaults(flow_dict)
    assert defaults["task_types"] == ["text-to-image"]
    assert defaults["output_map"] == {"assets": "output"}

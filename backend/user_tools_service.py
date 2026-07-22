"""Freezer — turn a flow into a first-class tool (a ``UserTool`` row).

Freezing snapshots a flow's program text and derives a canonical STP interface
from its declared ``input_schema``, validates that interface against the
declared task type(s), and persists it. The resulting tool runs unattended via
``flow_runtime.oneshot.run_flow_once`` even if the source flow is later deleted.

See plans/FLOW_TO_TOOL.md §2/§7.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Flow, UserTool
from flow_runtime.paths import get_flow_program_path
from tasks.schemas import validate_tool_schema
from user_tools_schema import (
    build_output_schema,
    flow_input_schema_to_parameter_schema,
)

log = logging.getLogger(__name__)


def slugify_tool_name(name: str) -> str:
    """Stable URL slug for a tool name. Frozen at creation (see FLOW_TO_TOOL §10.8)
    so the tool id (``{slug}-{id}``) survives renames."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-") or "tool"


def infer_freeze_defaults(flow_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort freeze defaults derived from a flow's declared shape.

    Returns ``{"task_types": [...], "output_map": {required_output: flow_output}}``.

    Task type is inferred from the input shape:
    - ``input_images`` + ``prompt`` → image-to-image
    - ``input_images`` only        → upscale-image (deterministic image transform)
    - ``prompt`` only / fallback   → text-to-image

    The required output for those tasks is ``assets``; it is bound to the flow's
    first declared output name (or ``"output"`` if none is declared).
    """
    input_schema = flow_dict.get("input_schema") or {}
    output_schema = flow_dict.get("output_schema") or {}

    input_names = set(input_schema.keys())
    has_prompt = "prompt" in input_names
    has_images = "input_images" in input_names

    if has_images and has_prompt:
        task_type = "image-to-image"
    elif has_images:
        task_type = "upscale-image"
    else:
        task_type = "text-to-image"

    required_output = "assets"

    # Bind the task's required output to the flow's first declared output.
    output_names = list(output_schema.keys())
    flow_output_name = output_names[0] if output_names else "output"

    return {
        "task_types": [task_type],
        "output_map": {required_output: flow_output_name},
        # The inputs the flow exposes (STP param names), so the freeze dialog can
        # validate that the chosen task type's required inputs are present.
        "exposed_inputs": list(input_schema.keys()),
    }


async def list_backing_tools_with_drift(
    session: AsyncSession, flow_id: int
) -> List[Dict[str, Any]]:
    """List the tools this flow backs, each annotated with ``has_changes``.

    ``has_changes`` is True when re-freezing the flow *now* would produce a
    different snapshot than the tool currently holds — i.e. the flow's program
    or input interface has drifted since this tool was frozen. That is the only
    condition under which an "Update" is meaningful; an up-to-date tool has
    nothing to pull. Best-effort: if the flow has no readable program, every
    tool is reported as not-drifted (there's nothing to resync to).
    """
    rows = (
        await session.execute(
            select(UserTool)
            .where(UserTool.flow_id == flow_id, UserTool.deleted_at.is_(None))
            .order_by(UserTool.created_at.asc())
        )
    ).scalars().all()

    snapshot: Optional[tuple[str, Dict[str, Any]]] = None
    try:
        snapshot = await _snapshot_flow(session, flow_id)
    except ValueError:
        snapshot = None

    out: List[Dict[str, Any]] = []
    for row in rows:
        d = row.to_dict()
        if snapshot is None:
            d["has_changes"] = False
        else:
            cur_program, cur_params = snapshot
            stored_params = json.loads(row.parameter_schema) if row.parameter_schema else {}
            d["has_changes"] = (
                cur_program != row.program_text or cur_params != stored_params
            )
        out.append(d)
    return out


async def _snapshot_flow(session: AsyncSession, flow_id: int) -> tuple[str, Dict[str, Any]]:
    """Capture a flow's runnable body + canonical STP interface at this instant.

    Returns ``(program_text, parameter_schema)``. The two are a coherent unit:
    the snapshotted program expects exactly the inputs the snapshotted
    ``parameter_schema`` declares, so they must always be captured together (a
    tool whose schema was re-derived without re-snapshotting the program — or
    vice versa — would mismatch at run time).

    Raises ValueError if the flow is missing or has no program to freeze.
    """
    from flow_service import get_flow_or_404

    flow = await get_flow_or_404(session, flow_id)

    program_path = get_flow_program_path(flow_id)
    if not program_path.exists():
        raise ValueError(f"Flow {flow_id} has no program to freeze")
    program_text = program_path.read_text()

    flow_input_schema = json.loads(flow.input_schema) if flow.input_schema else {}
    parameter_schema = flow_input_schema_to_parameter_schema(flow_input_schema)
    return program_text, parameter_schema


async def _validate_output_map(
    session: AsyncSession, flow_id: Optional[int], output_map: Optional[Dict[str, str]]
) -> None:
    """Reject an ``output_map`` that binds to a flow output that doesn't exist.

    Only enforced when the backing flow is present *and* declares outputs — a
    flow with no declared outputs degrades gracefully (the runner falls back to
    its single/first output), and a missing flow can't be checked. This catches
    the footgun of a stale/typo'd mapping that would otherwise only surface at
    execute time as "produced no output media".
    """
    if not output_map or flow_id is None:
        return
    flow = (
        await session.execute(
            select(Flow).where(Flow.id == flow_id, Flow.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if flow is None:
        return
    declared = json.loads(flow.output_schema) if flow.output_schema else {}
    if not declared:
        return
    output_names = set(declared.keys())
    bad = [v for v in output_map.values() if v not in output_names]
    if bad:
        raise ValueError(
            "Output mapping refers to flow output(s) that don't exist: "
            + ", ".join(sorted(bad))
            + f". The flow declares: {', '.join(sorted(output_names))}."
        )


async def freeze_flow_to_tool(
    session: AsyncSession,
    *,
    flow_id: int,
    name: str,
    description: Optional[str] = None,
    task_types: List[str],
    output_map: Dict[str, str],
    hitl_policies: Optional[Dict[str, Any]] = None,
) -> UserTool:
    """Freeze a flow into a ``UserTool`` and register it as a tool.

    Reads the flow's ``input_schema`` + program text, derives the STP
    ``parameter_schema`` / ``output_schema``, validates the interface against
    each declared task type, persists the tool (snapshotting program text), and
    refreshes the provider so the tool registers immediately.

    Raises:
        ValueError: if the flow is missing, has no program, or the derived
            interface fails validation for any declared task type.
    """
    # Snapshot the flow's runnable body + interface together (coherent unit).
    program_text, parameter_schema = await _snapshot_flow(session, flow_id)
    await _validate_output_map(session, flow_id, output_map)
    output_schema = build_output_schema(task_types)

    # Capture the LLM the flow's chat is using (chat -> project -> global) so
    # the frozen tool's `agent` steps run on that model rather than whatever
    # the global default happens to be at run time. NULL = fall back to global.
    from flow_runtime.production_evaluators import _resolve_flow_chat_model_slug

    project_id = (
        await session.execute(select(Flow.project_id).where(Flow.id == flow_id))
    ).scalar_one_or_none()
    model_slug = await _resolve_flow_chat_model_slug(flow_id, project_id)

    # Validation gate: the derived interface must satisfy every task type.
    errors: List[str] = []
    for task_type in task_types:
        for err in validate_tool_schema(task_type, parameter_schema, output_schema):
            errors.append(f"[{task_type}] {err}")
    if errors:
        raise ValueError("; ".join(errors))

    tool = UserTool(
        name=name,
        slug=slugify_tool_name(name),  # frozen here; never recomputed on rename
        description=description,
        flow_id=flow_id,
        program_text=program_text,
        task_types=json.dumps(task_types),
        parameter_schema=json.dumps(parameter_schema),
        output_schema=json.dumps(output_schema),
        hitl_policies=json.dumps(hitl_policies or {}),
        output_map=json.dumps(output_map or {}),
        model_slug=model_slug,
    )
    session.add(tool)
    await session.commit()
    await session.refresh(tool)

    await _refresh_provider("freeze")
    return tool


async def update_user_tool(
    session: AsyncSession,
    *,
    user_tool_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    task_types: Optional[List[str]] = None,
    output_map: Optional[Dict[str, str]] = None,
    hitl_policies: Optional[Dict[str, Any]] = None,
    resync_from_flow: bool = False,
) -> UserTool:
    """Update an existing tool's freeze settings **in place** (stable id).

    Two distinct operations live here:

    - **Settings edit** (default): name / description / task type / output
      binding / HITL policy change, but the frozen snapshot (``program_text`` +
      ``parameter_schema``) is left untouched. This is deliberate — editing a
      tool's settings must not silently pull in unfinished changes from a flow
      that has drifted since freeze.
    - **Resync** (``resync_from_flow=True``): re-capture the backing flow's
      program + input interface, so logic/input changes made in the flow
      propagate into the tool. Keeps the tool's stable id (and therefore its
      pins / saved presets). Requires a backing flow.

    ``output_schema`` is always rebuilt from the (possibly new) task type(s),
    and the resulting interface is re-validated.

    Raises ValueError if the tool is missing, has no backing flow to resync
    from, or the resulting interface is invalid for any task type.
    """
    tool = (
        await session.execute(
            select(UserTool).where(
                UserTool.id == user_tool_id, UserTool.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if tool is None:
        raise ValueError(f"User tool {user_tool_id} not found")

    new_task_types = (
        task_types if task_types is not None
        else (json.loads(tool.task_types) if tool.task_types else [])
    )

    # Default: keep the existing frozen snapshot. Resync re-captures it from the
    # backing flow (program + interface together, never one without the other).
    program_text = tool.program_text
    parameter_schema = json.loads(tool.parameter_schema) if tool.parameter_schema else {
        "type": "object", "properties": {}
    }
    if resync_from_flow:
        if tool.flow_id is None:
            raise ValueError("This tool has no backing flow to resync from")
        flow = (
            await session.execute(
                select(Flow).where(Flow.id == tool.flow_id, Flow.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if flow is None:
            raise ValueError("Backing flow no longer exists; cannot resync")
        program_text, parameter_schema = await _snapshot_flow(session, tool.flow_id)

    if output_map is not None:
        await _validate_output_map(session, tool.flow_id, output_map)

    output_schema = build_output_schema(new_task_types)

    errors: List[str] = []
    for task_type in new_task_types:
        for err in validate_tool_schema(task_type, parameter_schema, output_schema):
            errors.append(f"[{task_type}] {err}")
    if errors:
        raise ValueError("; ".join(errors))

    if name is not None:
        tool.name = name
    if description is not None:
        tool.description = description
    tool.task_types = json.dumps(new_task_types)
    tool.parameter_schema = json.dumps(parameter_schema)
    tool.program_text = program_text
    tool.output_schema = json.dumps(output_schema)
    if output_map is not None:
        tool.output_map = json.dumps(output_map)
    if hitl_policies is not None:
        tool.hitl_policies = json.dumps(hitl_policies)

    await session.commit()
    await session.refresh(tool)
    await _refresh_provider("resync" if resync_from_flow else "update")
    return tool


async def _refresh_provider(reason: str) -> None:
    try:
        from providers import user_tools as user_tools_provider

        await user_tools_provider.refresh()
    except Exception as e:  # noqa: BLE001 — provider refresh is best-effort
        log.warning(f"UserToolsProvider refresh after {reason} skipped: {e}")

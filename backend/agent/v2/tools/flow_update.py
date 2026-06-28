"""flow_update — update flow metadata from inside a flow chat.

The flow agent uses this tool to update ``name`` and ``description``.
Input/output schemas are NOT set here — ``program.py`` is the single
source of truth for those: the graph builder reads ``@flow(inputs=...,
outputs=...)`` and ``flow_lifecycle`` mirrors the serialized specs into
``Flow.input_schema`` / ``Flow.output_schema`` after every build.

Input values are normally supplied by the user through the inputs form in
the UI, which starts execution — the agent only passes ``inputs`` when
the user explicitly hands it values. When ``inputs`` is set on an idle
flow, execution auto-starts.

Only usable inside a chat whose ``flow_id`` is set. Used outside a
flow chat it returns an informative error rather than silently no-op'ing.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

import flow_lifecycle
import flow_registry
from database import Chat, Flow
from utils.websocket import ws_manager

from ..tools_registry import tool, ToolParameter


@tool(
    name="flow_update",
    description=(
        "Update this flow's name or description. Input/output schemas are "
        "declared inside program.py via @flow(inputs=..., outputs=...) "
        "and sync automatically — don't set them here. Only available in "
        "flow chats. The `inputs` field is for the user — they fill the "
        "inputs form in the UI. Only pass `inputs` here if the user "
        "explicitly hands you values to set."
    ),
    parameters=[
        ToolParameter(
            name="name",
            type="string",
            description="Display name for the flow.",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="One-paragraph description of what the flow produces.",
            required=False,
        ),
        ToolParameter(
            name="inputs",
            type="object",
            description=(
                "Input values keyed by input name. The user fills these in "
                "through the inputs form in the UI — pass this field only "
                "when the user explicitly gives you values to set."
            ),
            required=False,
        ),
    ],
    scope="flow",
)
async def flow_update(
    name: str | None = None,
    description: str | None = None,
    inputs: dict | None = None,
    **kwargs,
) -> str:
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")
    if session is None or chat_id is None:
        return "Error: flow_update requires an active chat session."

    chat_row = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = chat_row.scalar_one_or_none()
    if chat is None:
        return f"Error: chat {chat_id} not found."
    if chat.flow_id is None:
        return (
            "Error: this chat is not attached to a flow. flow_update is only "
            "usable in flow chats. Create a flow first via POST /api/flows "
            "and open its chat."
        )

    flow_row = await session.execute(
        select(Flow).where(Flow.id == chat.flow_id, Flow.deleted_at.is_(None))
    )
    flow = flow_row.scalar_one_or_none()
    if flow is None:
        return f"Error: flow {chat.flow_id} not found or deleted."

    changed: list[str] = []
    if name is not None:
        flow.name = name.strip()
        changed.append("name")
    if description is not None:
        flow.description = description
        changed.append("description")
    if inputs is not None:
        flow.inputs = json.dumps(inputs)
        changed.append("inputs")

    if not changed:
        return (
            "No fields provided. Pass at least one of: name, description, "
            "inputs. (Input/output schemas come from program.py.)"
        )

    await session.commit()
    await session.refresh(flow)

    await ws_manager.broadcast(
        "flow_updated",
        {"flow": flow.to_dict(), "fields_changed": changed},
    )

    started = False
    refreshed = False
    start_error: str | None = None
    if "inputs" in changed:
        # Push the new inputs into a live runtime so the running graph
        # recomputes against the real values. The common sequence is: the
        # agent writes program.py first (which auto-starts the runtime with
        # placeholder Nones), THEN sets inputs here — at which point the flow
        # is already "running", so the idle auto-start below won't fire.
        # Without this, the runtime keeps its build-time inputs and never
        # recomputes, so the flow sits in "running" doing nothing until the
        # user perturbs the inputs form (PATCH /flows/{id}, which does push
        # them in). Mirror that path and get_or_create_runtime here.
        runtime = flow_registry.get_runtime(flow.id)
        if runtime is not None:
            new_inputs = json.loads(flow.inputs) if flow.inputs else {}
            if runtime.inputs != new_inputs:
                runtime.inputs = dict(new_inputs)
                try:
                    _, reload_err = runtime.try_reload_program()
                    if reload_err is None:
                        refreshed = True
                    else:
                        start_error = str(reload_err)
                except Exception as exc:  # noqa: BLE001 — best-effort
                    start_error = str(exc)

    if "inputs" in changed and flow.execution_state == "idle":
        # Auto-start when inputs are set on an idle flow so the runtime can
        # validate the graph and surface progress without a manual /start.
        try:
            runtime = flow_lifecycle.get_or_create_runtime(flow)
            await runtime.start()
            flow.execution_state = "running"
            flow.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(flow)
            await ws_manager.broadcast(
                "flow_updated",
                {"flow": flow.to_dict(), "fields_changed": ["execution_state"]},
            )
            started = True
        except Exception as exc:  # noqa: BLE001
            start_error = str(exc)

    suffix = ""
    if "inputs" in changed:
        if started:
            suffix = (
                " Flow started — progress and HITL tasks will surface in the "
                "flow UI."
            )
        elif refreshed:
            suffix = (
                " Inputs applied to the running flow — affected steps will "
                "recompute in the flow UI."
            )
        elif start_error:
            suffix = (
                f" Inputs stored but could not be applied to the live "
                f"runtime: {start_error}"
            )
        else:
            suffix = " Inputs stored."

    return f"Flow {flow.id} updated ({', '.join(changed)}).{suffix}"

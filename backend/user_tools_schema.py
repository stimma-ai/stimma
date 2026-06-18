"""Assemble a flow's (already-STP) input schema into a tool parameter_schema.

The flow's ``input_schema`` is canonical STP per-property — produced at the
source by ``flow_dsl.loader._input_spec_to_stp_property``. There is **no
vocabulary translation here** (that was the bug). This is pure structural
assembly: wrap the per-name STP properties into one STP object schema and hoist
the per-property ``optional`` marker into the object-level ``required`` array.
See plans/FLOW_TO_TOOL.md §2.1.
"""

from __future__ import annotations

from typing import Any


def flow_input_schema_to_parameter_schema(
    flow_input_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """STP per-property map (``Flow.input_schema``) -> STP ``parameter_schema``.

    Every flow input is an exposed tool parameter (flows have no locked inputs —
    constraints live in the flow). ``required`` = inputs not marked ``optional``.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, prop in (flow_input_schema or {}).items():
        prop = dict(prop or {})
        optional = bool(prop.pop("optional", False))  # map-level marker -> required array
        properties[name] = prop
        if not optional:
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def build_output_schema(task_types: list[str] | None) -> dict[str, Any]:
    """STP ``output_schema`` for the declared task type(s): ``assets`` / ``detections``."""
    out_keys: set[str] = set()
    for tt in task_types or []:
        if "detect" in (tt or ""):
            out_keys.add("detections")
        else:
            out_keys.add("assets")
    if not out_keys:
        out_keys = {"assets"}
    return {
        "type": "object",
        "properties": {k: {"type": "array", "description": k} for k in sorted(out_keys)},
    }

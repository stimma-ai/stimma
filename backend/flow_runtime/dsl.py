"""Compatibility shim — the DSL lives in ``backend/flow_dsl/`` as of Phase 3.

This module preserves the Phase 2 import paths (``flow_runtime.dsl.tool``
etc.) so existing tests and earlier code keep working. New code should
import from ``flow_dsl`` directly.
"""

from __future__ import annotations

from flow_dsl.context import (  # noqa: F401
    BuildContext,
    BuildFrame,
    activate_context,
    current_context,
    push_frame,
)
from flow_dsl.primitives import (  # noqa: F401
    InputSpec,
    OutputSpec,
    FlowDecorated,
    code,
    filter,
    filter_items,
    foreach,
    foreach_range,
    gate,
    hitl,
    input,  # noqa: A004 — matches DSL surface
    lift_flow_input,
    llm,
    output,
    phase,
    partition,
    flow,
    switch,
    take,
    tool,
    when,
    zip_nodes,
    # helpers kept for Phase 2 tests that poke at internals
    _collect_noderefs,
    _register_literal_collection,
    _register_nested_equation,
    _split_static_dynamic,
    _template_of,
)

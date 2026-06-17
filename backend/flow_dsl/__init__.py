"""Stimma flow DSL — the Python surface the flow agent writes against.

See docs/FLOWS_DSL.md for the full design. In short:

- ``@flow(name=..., inputs=..., outputs=...)`` decorates the top-level
  flow function. The function body builds an equation graph.
- ``input()`` / ``output()`` declare the flow's interface.
- ``phase("name")`` is a context manager that tags equations for the phase
  tree. Purely organizational — does not constrain execution order.
- ``foreach(items, callback, **extra)`` registers a loop. Iteration keys
  are derived by the runtime (FLOWS_EQUATION_KEYS §6); no ``key=``.
- ``tool(tool_id, **params)`` — STP tool invocation. Always returns a
  single-call NodeRef; wrap in ``foreach`` for N candidates.
- ``llm(prompt, *, model, response_format=None, system=None)`` — LLM call.
- ``code(source, *, inputs, output_type="json")`` — sandboxed Python block.
- ``hitl.select / hitl.approve`` — human
  task gates.
- ``switch`` / ``when`` / ``gate`` / ``filter`` / ``partition`` / ``take`` —
  branchless data-flow routing. Graph shape stays static; values decide what
  data flows downstream.
- ``zip_nodes(a, b, c, ...)`` — inner-join keyed collections.

All primitives return opaque ``NodeRef`` handles. Build-time inspection
(attribute access, iteration, arithmetic, comparison, f-string
interpolation) raises ``NodeUsageError`` with a message that teaches the
fix.
"""

from __future__ import annotations

from .context import (
    BuildContext,
    BuildFrame,
    activate_context,
    current_context,
    push_frame,
)
from .errors import (
    DSLError,
    DSLMisuseError,
    NodeUsageError,
    ProgramLoadError,
    validate_output_type,
)
from .loader import (
    build_graph_from_callable,
    build_graph_from_program_file,
    build_graph_from_source,
    load_program_with_error_classification,
)
from .primitives import (
    InputSpec,
    OutputSpec,
    FlowDecorated,
    code,
    create_document,
    create_grid,
    create_image,
    create_layout,
    create_set,
    fetch_media,
    filter,
    filter_items,
    foreach,
    gate,
    hitl,
    info,
    input,
    lift_flow_input,
    llm,
    output,
    phase,
    partition,
    rasterize_layout,
    flow,
    switch,
    take,
    tool,
    when,
    web_search,
    zip_nodes,
)
from .versions import (
    ProgramVersionRecord,
    ProgramVersionStore,
    get_version_store,
)

__all__ = [
    # context / infrastructure
    "BuildContext",
    "BuildFrame",
    "activate_context",
    "current_context",
    "push_frame",
    # errors
    "DSLError",
    "DSLMisuseError",
    "NodeUsageError",
    "ProgramLoadError",
    "validate_output_type",
    # primitives (user-facing DSL)
    "InputSpec",
    "OutputSpec",
    "FlowDecorated",
    "code",
    "create_document",
    "create_grid",
    "create_image",
    "create_layout",
    "create_set",
    "fetch_media",
    "filter",
    "filter_items",
    "foreach",
    "gate",
    "hitl",
    "info",
    "input",
    "llm",
    "output",
    "phase",
    "partition",
    "rasterize_layout",
    "flow",
    "switch",
    "take",
    "tool",
    "when",
    "web_search",
    "zip_nodes",
    # loader
    "build_graph_from_callable",
    "build_graph_from_program_file",
    "build_graph_from_source",
    "load_program_with_error_classification",
    # internals useful to the runtime
    "lift_flow_input",
    # versioning
    "ProgramVersionRecord",
    "ProgramVersionStore",
    "get_version_store",
]

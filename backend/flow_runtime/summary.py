"""Root-phase status summary computation.

Used by the engine's WS broadcasts and the phase-tree route so every surface
derives the same `Running / Done / Your Turn / Error` label from the same
scaffolding filter. Completed scaffolding equations (flow inputs and
control-only wrappers like foreach/zip) are omitted from the summary,
but non-terminal scaffolding is counted. Otherwise a graph with only pending
inputs/control wrappers appears as "Done".
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .graph import Equation


SCAFFOLDING_CONTROL_KINDS = {
    "flow_input",
    "approve",
    "slot",
    "foreach",
    "foreach_iteration",
    "zip_nodes",
    "literal_list",
    "llm_gather",
}


def is_scaffolding_equation(
    equation_type: str, definition: Optional[dict[str, Any]]
) -> bool:
    if equation_type == "flow_input":
        return True
    if equation_type == "control":
        kind = (definition or {}).get("control_kind", "")
        return kind in SCAFFOLDING_CONTROL_KINDS
    return False


def include_equation_in_status_summary(
    equation_type: str,
    definition: Optional[dict[str, Any]],
    status: str,
) -> bool:
    if not is_scaffolding_equation(equation_type, definition):
        return True
    return status not in {"completed", "skipped"}


def compute_root_summary_from_equations(
    equations: Iterable[Equation],
) -> dict[str, int]:
    """Root status_summary from an in-memory equation graph."""
    summary: dict[str, int] = {}
    for eq in equations:
        status = eq.status.value
        if not include_equation_in_status_summary(
            eq.equation_type.value,
            eq.definition,
            status,
        ):
            continue
        summary[status] = summary.get(status, 0) + 1
    return summary


def compute_root_summary_from_rows(
    rows: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Root status_summary from state.db rows (dicts with keys
    equation_type / definition / status)."""
    summary: dict[str, int] = {}
    for row in rows:
        status = row["status"]
        if not include_equation_in_status_summary(
            row["equation_type"],
            row.get("definition"),
            status,
        ):
            continue
        summary[status] = summary.get(status, 0) + 1
    return summary

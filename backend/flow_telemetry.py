"""
Flow runtime telemetry.

The flow engine is a reactive scheduler with no single terminal
transition, so run-outcome telemetry hooks the one seam every runtime
event flows through (``flow_lifecycle._broadcast``):

- ``flow_task_resolved`` broadcasts -> the HITL telemetry event
  (taskKind + waitDurationMs from the durable task row).
- ``flow_equation_updated`` broadcasts -> ``flow_failed`` on the first
  equation failure of a started run (stepKind = the closed node-type enum)
  and ``flow_completed`` when the root status summary settles to done.

Per-run once-only state is in-memory and reset by ``note_started`` (the
start/resume routes call it) — telemetry-only state, nothing durable.

All events carry ``flowHash`` (install-salted, irreversible). Names,
program content, and raw error text never egress (errors classify into
errorType + errorHash).
"""
import time
from typing import Any, Dict, Optional

from core.logging import get_logger

log = get_logger(__name__)

# flow_id -> {"started_monotonic": float, "failed_emitted": bool,
#               "completed_emitted": bool}
_run_state: Dict[int, Dict[str, Any]] = {}

# Statuses that count as "settled work" for the done check.
_DONE_STATUSES = {"completed", "skipped"}


def _flow_hash(flow_id: int) -> str:
    from object_hash import salted_hash
    return salted_hash(f"flow:{flow_id}")


def note_started(flow_id: int) -> None:
    """Record a run start/resume — resets the once-per-run outcome flags."""
    _run_state[flow_id] = {
        "started_monotonic": time.monotonic(),
        "failed_emitted": False,
        "completed_emitted": False,
    }


def note_stopped(flow_id: int) -> None:
    _run_state.pop(flow_id, None)


def _counts_from_runtime(flow_id: int) -> Dict[str, int]:
    """taskCount / llmCallCount / toolCallCount from the live graph."""
    counts = {"taskCount": 0, "llmCallCount": 0, "toolCallCount": 0}
    try:
        import flow_registry
        runtime = flow_registry.get_runtime(flow_id)
        graph = getattr(runtime, "graph", None)
        if graph is None:
            return counts
        for eq in graph.all_equations():
            eq_type = eq.equation_type.value
            if eq_type in ("llm_call", "llm_batch", "llm_slot"):
                counts["llmCallCount"] += 1
            elif eq_type == "tool_call":
                counts["toolCallCount"] += 1
            elif eq_type == "hitl":
                counts["taskCount"] += 1
    except Exception:
        pass
    return counts


def _task_wait_ms(flow_id: int, task_id: Optional[int]) -> Optional[int]:
    """Task raised -> resolved, from the durable task row timestamps."""
    if task_id is None:
        return None
    try:
        from datetime import datetime
        from flow_runtime import get_flow_state_db_path, graph_db
        row = graph_db.get_task(get_flow_state_db_path(flow_id), task_id)
        if not row or not row.get("created_at") or not row.get("resolved_at"):
            return None
        created = datetime.fromisoformat(str(row["created_at"]))
        resolved = datetime.fromisoformat(str(row["resolved_at"]))
        return max(0, int((resolved - created).total_seconds() * 1000))
    except Exception:
        return None


def on_runtime_broadcast(event: str, payload: Dict[str, Any]) -> None:
    """Telemetry tap on the flow runtime's WS broadcast seam."""
    try:
        flow_id = payload.get("flow_id")
        if not isinstance(flow_id, int):
            return

        from telemetry import get_telemetry_client
        client = get_telemetry_client()

        if event == "flow_task_resolved":
            props: Dict[str, Any] = {
                "flowHash": _flow_hash(flow_id),
                "taskKind": payload.get("task_type") or "unknown",
            }
            wait_ms = _task_wait_ms(flow_id, payload.get("task_id"))
            if wait_ms is not None:
                props["waitDurationMs"] = wait_ms
            client.track("flow_task_resolved", props, category="flow")
            return

        if event != "flow_equation_updated":
            return

        state = _run_state.get(flow_id)
        if state is None:
            return  # not a run this process started/resumed — no outcome to attribute

        if payload.get("status") == "failed" and not state["failed_emitted"]:
            state["failed_emitted"] = True
            from telemetry_props import classify_tool_error, error_hash
            error_text = payload.get("error") or ""
            client.track("flow_failed", {
                "flowHash": _flow_hash(flow_id),
                "errorType": classify_tool_error(error_text),
                "errorHash": error_hash(error_text),
                "stepKind": payload.get("equation_type") or "unknown",
            }, category="flow")
            return

        summary = payload.get("root_status_summary") or {}
        if (
            not state["completed_emitted"]
            and not state["failed_emitted"]
            and summary
            and sum(summary.values()) > 0
            and all(status in _DONE_STATUSES for status in summary)
        ):
            state["completed_emitted"] = True
            duration_ms = int((time.monotonic() - state["started_monotonic"]) * 1000)
            client.track("flow_completed", {
                "flowHash": _flow_hash(flow_id),
                "durationMs": duration_ms,
                **_counts_from_runtime(flow_id),
            }, category="flow")
    except Exception:
        log.debug("flow telemetry broadcast hook failed", exc_info=True)

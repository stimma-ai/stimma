"""
Recipe runtime telemetry.

The recipe engine is a reactive scheduler with no single terminal
transition, so run-outcome telemetry hooks the one seam every runtime
event flows through (``recipe_lifecycle._broadcast``):

- ``recipe_task_resolved`` broadcasts -> the HITL telemetry event
  (taskKind + waitDurationMs from the durable task row).
- ``recipe_equation_updated`` broadcasts -> ``recipe_failed`` on the first
  equation failure of a started run (stepKind = the closed node-type enum)
  and ``recipe_completed`` when the root status summary settles to done.

Per-run once-only state is in-memory and reset by ``note_started`` (the
start/resume routes call it) — telemetry-only state, nothing durable.

All events carry ``recipeHash`` (install-salted, irreversible). Names,
program content, and raw error text never egress (errors classify into
errorType + errorHash).
"""
import time
from typing import Any, Dict, Optional

from core.logging import get_logger

log = get_logger(__name__)

# recipe_id -> {"started_monotonic": float, "failed_emitted": bool,
#               "completed_emitted": bool}
_run_state: Dict[int, Dict[str, Any]] = {}

# Statuses that count as "settled work" for the done check.
_DONE_STATUSES = {"completed", "skipped"}


def _recipe_hash(recipe_id: int) -> str:
    from object_hash import salted_hash
    return salted_hash(f"recipe:{recipe_id}")


def note_started(recipe_id: int) -> None:
    """Record a run start/resume — resets the once-per-run outcome flags."""
    _run_state[recipe_id] = {
        "started_monotonic": time.monotonic(),
        "failed_emitted": False,
        "completed_emitted": False,
    }


def note_stopped(recipe_id: int) -> None:
    _run_state.pop(recipe_id, None)


def _counts_from_runtime(recipe_id: int) -> Dict[str, int]:
    """taskCount / llmCallCount / toolCallCount from the live graph."""
    counts = {"taskCount": 0, "llmCallCount": 0, "toolCallCount": 0}
    try:
        import recipe_registry
        runtime = recipe_registry.get_runtime(recipe_id)
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


def _task_wait_ms(recipe_id: int, task_id: Optional[int]) -> Optional[int]:
    """Task raised -> resolved, from the durable task row timestamps."""
    if task_id is None:
        return None
    try:
        from datetime import datetime
        from recipe_runtime import get_recipe_state_db_path, graph_db
        row = graph_db.get_task(get_recipe_state_db_path(recipe_id), task_id)
        if not row or not row.get("created_at") or not row.get("resolved_at"):
            return None
        created = datetime.fromisoformat(str(row["created_at"]))
        resolved = datetime.fromisoformat(str(row["resolved_at"]))
        return max(0, int((resolved - created).total_seconds() * 1000))
    except Exception:
        return None


def on_runtime_broadcast(event: str, payload: Dict[str, Any]) -> None:
    """Telemetry tap on the recipe runtime's WS broadcast seam."""
    try:
        recipe_id = payload.get("recipe_id")
        if not isinstance(recipe_id, int):
            return

        from telemetry import get_telemetry_client
        client = get_telemetry_client()

        if event == "recipe_task_resolved":
            props: Dict[str, Any] = {
                "recipeHash": _recipe_hash(recipe_id),
                "taskKind": payload.get("task_type") or "unknown",
            }
            wait_ms = _task_wait_ms(recipe_id, payload.get("task_id"))
            if wait_ms is not None:
                props["waitDurationMs"] = wait_ms
            client.track("recipe_task_resolved", props, category="recipe")
            return

        if event != "recipe_equation_updated":
            return

        state = _run_state.get(recipe_id)
        if state is None:
            return  # not a run this process started/resumed — no outcome to attribute

        if payload.get("status") == "failed" and not state["failed_emitted"]:
            state["failed_emitted"] = True
            from telemetry_props import classify_tool_error, error_hash
            error_text = payload.get("error") or ""
            client.track("recipe_failed", {
                "recipeHash": _recipe_hash(recipe_id),
                "errorType": classify_tool_error(error_text),
                "errorHash": error_hash(error_text),
                "stepKind": payload.get("equation_type") or "unknown",
            }, category="recipe")
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
            client.track("recipe_completed", {
                "recipeHash": _recipe_hash(recipe_id),
                "durationMs": duration_ms,
                **_counts_from_runtime(recipe_id),
            }, category="recipe")
    except Exception:
        log.debug("recipe telemetry broadcast hook failed", exc_info=True)

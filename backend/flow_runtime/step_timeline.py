"""Server-side flow phase step timeline.

The phase UI should not reverse-engineer a user-facing step order from raw
equation rows. This module turns enriched equation response dictionaries into
phase-local step items, ordered by data dependencies and with iteration-like
primitives transposed into "step × N" rows.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Optional


Row = dict[str, Any]


def build_phase_steps(rows: list[Row]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    """Return server-authored step items keyed by exact phase path."""
    rows_by_key = {r["equation_key"]: r for r in rows}
    order_index = {r["equation_key"]: i for i, r in enumerate(rows)}
    paths = {tuple(r.get("phase_path") or []) for r in rows}
    out: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for path in paths:
        out[path] = _build_steps_for_phase(path, rows, rows_by_key, order_index)
    return out


def _build_steps_for_phase(
    phase_path: tuple[str, ...],
    rows: list[Row],
    rows_by_key: dict[str, Row],
    order_index: dict[str, int],
) -> list[dict[str, Any]]:
    phase_rows = [
        r for r in rows if tuple(r.get("phase_path") or []) == phase_path
    ]
    primitive_rows = [
        r for r in phase_rows
        if _is_iteration_primitive(r)
    ]
    primitive_rows.sort(key=lambda r: order_index.get(r["equation_key"], 10**9))

    claimed: set[str] = set()
    steps: list[dict[str, Any]] = []

    for primitive in primitive_rows:
        primitive_key = primitive["equation_key"]
        if primitive_key in claimed:
            continue
        child_wrappers = _direct_iteration_wrappers(primitive_key, rows_by_key)
        if not child_wrappers:
            continue
        group_steps = _build_transposed_group_steps(
            primitive,
            child_wrappers,
            rows_by_key,
            order_index,
        )
        if not group_steps:
            continue
        for key in _subtree_keys(primitive_key, rows_by_key):
            claimed.add(key)
        steps.extend(group_steps)

    for row in phase_rows:
        key = row["equation_key"]
        if key in claimed:
            continue
        if not _equation_is_renderable(row):
            continue
        steps.append(_equation_step(row, order_index))

    return _toposort_steps(steps, rows_by_key)


def _build_transposed_group_steps(
    primitive: Row,
    wrappers: list[Row],
    rows_by_key: dict[str, Row],
    order_index: dict[str, int],
) -> list[dict[str, Any]]:
    if primitive.get("equation_type") == "llm_batch":
        return _build_leaf_batch_step(primitive, wrappers, rows_by_key, order_index)
    if primitive.get("control_kind") == "foreach":
        nested = _nested_singleton_approve_slots(wrappers, rows_by_key)
        if nested is not None:
            return _build_nested_approve_each_steps(
                primitive,
                wrappers,
                nested,
                rows_by_key,
                order_index,
            )

    iterations = [
        _grouped_iteration(w, _renderable_children(w["equation_key"], rows_by_key), rows_by_key)
        for w in wrappers
    ]
    if not any(i["equations"] or i["wrapper"]["status"] == "failed" for i in iterations):
        return []

    substeps = _transpose_direct_children(wrappers, rows_by_key, order_index)
    if not substeps:
        return []

    primitive_key = primitive["equation_key"]
    out: list[dict[str, Any]] = []
    last_idx = len(substeps) - 1
    for idx, sub in enumerate(substeps):
        sub_iterations: list[dict[str, Any]] = []
        represented_keys: list[str] = []
        concrete_equations = [e for e in sub["equations"] if e is not None]
        for slot_idx, wrapper in enumerate(wrappers):
            eq = sub["equations"][slot_idx]
            sub_iterations.append(
                _substep_iteration(wrapper, eq, rows_by_key)
            )
            if eq is not None:
                represented_keys.append(eq["equation_key"])

        if idx == last_idx:
            represented_keys.append(primitive_key)
            represented_keys.extend(w["equation_key"] for w in wrappers)

        aggregate = _aggregate_iterations(sub_iterations)
        group_key = f"{primitive_key}/{sub['relativePath']}"
        is_hitl_approve = sub["kind"] == "hitl-approve"
        item: dict[str, Any] = {
            "kind": "group",
            "groupKey": group_key,
            "foreach": primitive,
            "iterations": sub_iterations,
            "aggregate": {
                **aggregate,
                "queued": sum(1 for i in sub_iterations if i.get("isQueued")),
            },
            "totalDurationMs": _aggregate_duration(concrete_equations),
            "displayName": _substep_display_name(sub, primitive),
            "cellMode": "hitl-approve" if is_hitl_approve else "tile",
            "instructions": (
                "Approve each — reject to regenerate that slot."
                if is_hitl_approve else None
            ),
            "parentSlots": iterations if is_hitl_approve else None,
            "contentKind": _classify_group_content_kind(
                [
                    _candidate_producer_for_slot(i)
                    for i in iterations
                ] if is_hitl_approve else [i.get("primary") for i in sub_iterations]
            ),
            "_representedKeys": represented_keys,
            "_stepId": f"group:{group_key}",
            "_order": min(
                [order_index.get(k, 10**9) for k in represented_keys] or [10**9]
            ),
        }
        out.append(item)
    return out


def _nested_singleton_approve_slots(
    wrappers: list[Row],
    rows_by_key: dict[str, Row],
) -> Optional[list[tuple[Row, Row]]]:
    """Detect ``foreach`` bodies that are exactly ``hitl.approve(1, ...)``.

    ``hitl.approve_each`` composes this way. The user-facing shape should be
    transposed across the outer foreach items, not emitted as N independent
    ``tool -> approve`` pairs.
    """
    if not wrappers:
        return None
    out: list[tuple[Row, Row]] = []
    for wrapper in wrappers:
        approve_children = [
            child for child in _direct_children(wrapper["equation_key"], rows_by_key)
            if child.get("equation_type") == "control"
            and child.get("control_kind") == "approve"
        ]
        if len(approve_children) != 1:
            return None
        approve = approve_children[0]
        slots = _direct_iteration_wrappers(approve["equation_key"], rows_by_key)
        if len(slots) != 1:
            return None
        out.append((approve, slots[0]))
    return out


def _build_nested_approve_each_steps(
    primitive: Row,
    outer_wrappers: list[Row],
    nested: list[tuple[Row, Row]],
    rows_by_key: dict[str, Row],
    order_index: dict[str, int],
) -> list[dict[str, Any]]:
    approve_primitives = [a for a, _slot in nested]
    slot_wrappers = [slot for _a, slot in nested]
    slot_iterations = [
        _grouped_iteration(w, _renderable_children(w["equation_key"], rows_by_key), rows_by_key)
        for w in slot_wrappers
    ]
    if not any(i["equations"] or i["wrapper"]["status"] == "failed" for i in slot_iterations):
        return []

    substeps = _transpose_direct_children(slot_wrappers, rows_by_key, order_index)
    if not substeps:
        return []

    primitive_key = primitive["equation_key"]
    out: list[dict[str, Any]] = []
    last_idx = len(substeps) - 1
    wrapper_keys = [w["equation_key"] for w in outer_wrappers]
    approve_keys = [a["equation_key"] for a in approve_primitives]
    slot_keys = [s["equation_key"] for s in slot_wrappers]

    for idx, sub in enumerate(substeps):
        sub_iterations: list[dict[str, Any]] = []
        represented_keys: list[str] = []
        concrete_equations = [e for e in sub["equations"] if e is not None]
        for slot_idx, slot_wrapper in enumerate(slot_wrappers):
            eq = sub["equations"][slot_idx]
            sub_iterations.append(_substep_iteration(slot_wrapper, eq, rows_by_key))
            if eq is not None:
                represented_keys.append(eq["equation_key"])

        if idx == last_idx:
            represented_keys.append(primitive_key)
            represented_keys.extend(wrapper_keys)
            represented_keys.extend(approve_keys)
            represented_keys.extend(slot_keys)

        aggregate = _aggregate_iterations(sub_iterations)
        group_key = f"{primitive_key}/approve_each/{sub['relativePath']}"
        is_hitl_approve = sub["kind"] == "hitl-approve"
        out.append({
            "kind": "group",
            "groupKey": group_key,
            "foreach": primitive,
            "iterations": sub_iterations,
            "aggregate": {
                **aggregate,
                "queued": sum(1 for i in sub_iterations if i.get("isQueued")),
            },
            "totalDurationMs": _aggregate_duration(concrete_equations),
            "displayName": _substep_display_name(sub, primitive),
            "cellMode": "hitl-approve" if is_hitl_approve else "tile",
            "instructions": (
                "Approve each — reject to regenerate that slot."
                if is_hitl_approve else None
            ),
            "parentSlots": slot_iterations if is_hitl_approve else None,
            "contentKind": _classify_group_content_kind(
                [_candidate_producer_for_slot(i) for i in slot_iterations]
                if is_hitl_approve
                else [i.get("primary") for i in sub_iterations]
            ),
            "_representedKeys": represented_keys,
            "_stepId": f"group:{group_key}",
            "_order": min(
                [order_index.get(k, 10**9) for k in represented_keys] or [10**9]
            ),
        })
    return out


def _build_leaf_batch_step(
    primitive: Row,
    slots: list[Row],
    rows_by_key: dict[str, Row],
    order_index: dict[str, int],
) -> list[dict[str, Any]]:
    iterations = [
        _substep_iteration(slot, slot, rows_by_key)
        for slot in slots
    ]
    represented_keys = [slot["equation_key"] for slot in slots]
    represented_keys.append(primitive["equation_key"])
    group_key = f"{primitive['equation_key']}/slot"
    aggregate = {
        **_aggregate_iterations(iterations),
        "queued": sum(1 for i in iterations if i.get("isQueued")),
    }
    # A single llm(n=N) batch is ONE upstream call that fills every slot at
    # once. While that call is in flight the slots all sit "pending", so the
    # rolled-up "LLM ×N" row would read as idle (a grid of clock glyphs) even
    # though work is actively happening — the "flow says Running but shows no
    # feedback" report. Fold the batch equation's own status into the rollup
    # so the row shows a spinner while generating, and surfaces the failure if
    # the batch call errors out (e.g. an LLM timeout). Only applies before any
    # slot has reached a terminal state — once slots resolve, their own
    # statuses are the truth.
    batch_status = primitive.get("status")
    if aggregate["completed"] == 0 and aggregate["failed"] == 0:
        unstarted = aggregate["total"] - aggregate["computing"]
        if batch_status == "computing" and aggregate["computing"] == 0 and unstarted > 0:
            aggregate["computing"] = unstarted
            aggregate["pending"] = 0
        elif batch_status == "failed" and unstarted > 0:
            aggregate["failed"] = unstarted
            aggregate["computing"] = 0
            aggregate["pending"] = 0
    return [{
        "kind": "group",
        "groupKey": group_key,
        "foreach": primitive,
        "iterations": iterations,
        "aggregate": aggregate,
        "totalDurationMs": _aggregate_duration(slots),
        "displayName": primitive.get("display_name") or "LLM",
        "cellMode": "tile",
        "instructions": None,
        "parentSlots": None,
        "contentKind": _classify_group_content_kind(slots),
        "_representedKeys": represented_keys,
        "_stepId": f"group:{group_key}",
        "_order": min(order_index.get(k, 10**9) for k in represented_keys),
    }]


def _transpose_direct_children(
    wrappers: list[Row],
    rows_by_key: dict[str, Row],
    order_index: dict[str, int],
) -> list[dict[str, Any]]:
    by_path: dict[str, list[Optional[Row]]] = {}
    first_order: dict[str, int] = {}
    for slot_idx, wrapper in enumerate(wrappers):
        prefix = wrapper["equation_key"] + "/"
        for row in _direct_children(wrapper["equation_key"], rows_by_key):
            if not _equation_is_renderable(row):
                continue
            rel = row["equation_key"][len(prefix):]
            if rel not in by_path:
                by_path[rel] = [None] * len(wrappers)
                first_order[rel] = order_index.get(row["equation_key"], 10**9)
            by_path[rel][slot_idx] = row

    rel_paths = _toposort_relative_paths(by_path, first_order, rows_by_key)
    out: list[dict[str, Any]] = []
    for rel in rel_paths:
        equations = by_path[rel]
        rep = next((e for e in equations if e is not None), None)
        out.append({
            "relativePath": rel,
            "kind": _substep_kind(rep),
            "equationType": rep.get("equation_type") if rep else "unknown",
            "hitlKind": rep.get("hitl_kind") if rep else None,
            "toolId": rep.get("tool_id") if rep else None,
            "taskType": rep.get("task_type") if rep else None,
            "displayName": (rep.get("display_name") if rep else None) or rel,
            "equations": equations,
        })
    return out


def _toposort_relative_paths(
    by_path: dict[str, list[Optional[Row]]],
    first_order: dict[str, int],
    rows_by_key: dict[str, Row],
) -> list[str]:
    path_by_key: dict[str, str] = {}
    for rel, equations in by_path.items():
        for eq in equations:
            if eq is not None:
                path_by_key[eq["equation_key"]] = rel

    indegree = {rel: 0 for rel in by_path}
    out_edges: dict[str, set[str]] = {rel: set() for rel in by_path}
    for rel, equations in by_path.items():
        for eq in equations:
            if eq is None:
                continue
            for dep in eq.get("dependencies") or []:
                for dep_rel in _upstream_relative_paths(dep, path_by_key, rows_by_key):
                    if dep_rel == rel:
                        continue
                    if rel not in out_edges[dep_rel]:
                        out_edges[dep_rel].add(rel)
                        indegree[rel] += 1

    ready = sorted(
        [rel for rel, degree in indegree.items() if degree == 0],
        key=lambda rel: first_order.get(rel, 10**9),
    )
    ordered: list[str] = []
    while ready:
        rel = ready.pop(0)
        ordered.append(rel)
        for nxt in sorted(out_edges[rel], key=lambda r: first_order.get(r, 10**9)):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=lambda r: first_order.get(r, 10**9))
    if len(ordered) < len(by_path):
        for rel in sorted(by_path, key=lambda r: first_order.get(r, 10**9)):
            if rel not in ordered:
                ordered.append(rel)
    return ordered


def _upstream_relative_paths(
    dep_key: str,
    path_by_key: dict[str, str],
    rows_by_key: dict[str, Row],
) -> set[str]:
    direct = path_by_key.get(dep_key)
    if direct is not None:
        return {direct}
    out: set[str] = set()
    stack = [dep_key]
    seen: set[str] = set()
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        rel = path_by_key.get(key)
        if rel is not None:
            out.add(rel)
            continue
        row = rows_by_key.get(key)
        if row is not None:
            stack.extend(row.get("dependencies") or [])
    return out


def _toposort_steps(
    steps: list[dict[str, Any]],
    rows_by_key: dict[str, Row],
) -> list[dict[str, Any]]:
    if len(steps) <= 1:
        return [_public_step(s) for s in steps]

    owner_by_key: dict[str, str] = {}
    for step in steps:
        for key in step.get("_representedKeys") or []:
            owner_by_key[key] = step["_stepId"]

    indegree = {s["_stepId"]: 0 for s in steps}
    out_edges: dict[str, set[str]] = {s["_stepId"]: set() for s in steps}
    step_by_id = {s["_stepId"]: s for s in steps}

    for step in steps:
        target = step["_stepId"]
        represented = step.get("_representedKeys") or []
        for key in represented:
            row = rows_by_key.get(key)
            if row is None:
                continue
            for dep in row.get("dependencies") or []:
                for src in _upstream_step_owners(dep, owner_by_key, rows_by_key):
                    if src == target:
                        continue
                    if target not in out_edges[src]:
                        out_edges[src].add(target)
                        indegree[target] += 1

    ready = sorted(
        [sid for sid, degree in indegree.items() if degree == 0],
        key=lambda sid: step_by_id[sid].get("_order", 10**9),
    )
    ordered: list[dict[str, Any]] = []
    while ready:
        sid = ready.pop(0)
        ordered.append(step_by_id[sid])
        for nxt in sorted(out_edges[sid], key=lambda s: step_by_id[s].get("_order", 10**9)):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=lambda s: step_by_id[s].get("_order", 10**9))
    if len(ordered) < len(steps):
        seen = {s["_stepId"] for s in ordered}
        for step in sorted(steps, key=lambda s: s.get("_order", 10**9)):
            if step["_stepId"] not in seen:
                ordered.append(step)
    return [_public_step(s) for s in ordered]


def _upstream_step_owners(
    dep_key: str,
    owner_by_key: dict[str, str],
    rows_by_key: dict[str, Row],
) -> set[str]:
    direct = owner_by_key.get(dep_key)
    if direct is not None:
        return {direct}
    out: set[str] = set()
    stack = [dep_key]
    seen: set[str] = set()
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        owner = owner_by_key.get(key)
        if owner is not None:
            out.add(owner)
            continue
        row = rows_by_key.get(key)
        if row is not None:
            stack.extend(row.get("dependencies") or [])
    return out


def _equation_step(row: Row, order_index: dict[str, int]) -> dict[str, Any]:
    key = row["equation_key"]
    return {
        "kind": "equation",
        "eq": row,
        "_stepId": f"eq:{key}",
        "_representedKeys": [key],
        "_order": order_index.get(key, 10**9),
    }


def _public_step(step: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in step.items() if not k.startswith("_")}


def _is_iteration_primitive(row: Row) -> bool:
    if row.get("equation_type") == "control":
        return row.get("control_kind") in {"foreach", "approve"}
    if row.get("equation_type") == "llm_batch":
        return True
    return False


def _is_iteration_wrapper(row: Row) -> bool:
    if row.get("equation_type") == "control":
        return row.get("control_kind") in {"foreach_iteration", "slot"}
    if row.get("equation_type") == "llm_slot":
        return True
    return False


def _direct_iteration_wrappers(primitive_key: str, rows_by_key: dict[str, Row]) -> list[Row]:
    prefix = primitive_key + "/"
    wrappers = [
        row for row in rows_by_key.values()
        if _is_iteration_wrapper(row)
        and row["equation_key"].startswith(prefix)
        and "/" not in row["equation_key"][len(prefix):]
    ]
    wrappers.sort(key=lambda r: _iteration_sort_key(r["equation_key"]))
    return wrappers


def _iteration_sort_key(key: str) -> tuple[int, str]:
    tail = key.rsplit("/", 1)[-1]
    raw = tail.split(":", 1)[1] if ":" in tail else tail
    try:
        return (0, f"{int(raw):012d}")
    except ValueError:
        return (1, raw)


def _direct_children(wrapper_key: str, rows_by_key: dict[str, Row]) -> list[Row]:
    prefix = wrapper_key + "/"
    out = [
        row for row in rows_by_key.values()
        if row["equation_key"].startswith(prefix)
        and "/" not in row["equation_key"][len(prefix):]
    ]
    return out


def _subtree_keys(prefix_key: str, rows_by_key: dict[str, Row]) -> set[str]:
    prefix = prefix_key + "/"
    return {
        key for key in rows_by_key
        if key == prefix_key or key.startswith(prefix)
    }


def _renderable_children(wrapper_key: str, rows_by_key: dict[str, Row]) -> list[Row]:
    prefix = wrapper_key + "/"
    return [
        row for row in rows_by_key.values()
        if row["equation_key"].startswith(prefix)
        and _equation_is_renderable(row)
    ]


def _equation_is_renderable(row: Row) -> bool:
    status = row.get("status")
    if row.get("is_scaffolding") and status != "failed":
        return False
    if row.get("equation_type") == "code" and status != "failed":
        return False
    if row.get("equation_type") == "info" and status != "completed":
        return False
    return True


def _grouped_iteration(
    wrapper: Row,
    equations: list[Row],
    rows_by_key: dict[str, Row],
) -> dict[str, Any]:
    primary = _pick_primary(equations)
    status = _rollup_status(wrapper, equations)
    block_reason = (
        _classify_iteration_block(status, wrapper, equations, rows_by_key)
        if status == "pending" else None
    )
    return {
        "wrapperKey": wrapper["equation_key"],
        "iterKey": _iter_key_from_wrapper(wrapper["equation_key"]),
        "wrapper": wrapper,
        "equations": equations,
        "primary": primary,
        "status": status,
        "hasMedia": bool(primary and primary.get("result_media_ids")),
        "hasHitl": any(e.get("equation_type") == "hitl" for e in equations),
        "hasError": status == "failed",
        "isActionable": any(
            e.get("equation_type") == "hitl"
            and e.get("status") != "completed"
            and _equation_is_actionable(e, rows_by_key)
            for e in equations
        ),
        "isQueued": block_reason == "cap",
        "blockReason": block_reason,
    }


def _substep_iteration(
    wrapper: Row,
    eq: Optional[Row],
    rows_by_key: dict[str, Row],
) -> dict[str, Any]:
    status = eq.get("status") if eq is not None else "pending"
    block_reason = (
        _classify_equation_block(eq, rows_by_key, set())
        if eq is not None and status == "pending" else None
    )
    return {
        "wrapperKey": wrapper["equation_key"],
        "iterKey": _iter_key_from_wrapper(wrapper["equation_key"]),
        "wrapper": wrapper,
        "equations": [eq] if eq is not None else [],
        "primary": eq,
        "status": status,
        "hasMedia": bool(eq and eq.get("result_media_ids")),
        "hasHitl": bool(eq and eq.get("equation_type") == "hitl"),
        "hasError": status == "failed",
        "isActionable": bool(
            eq
            and eq.get("equation_type") == "hitl"
            and eq.get("status") != "completed"
            and _equation_is_actionable(eq, rows_by_key)
        ),
        "isQueued": block_reason == "cap",
        "blockReason": block_reason,
    }


def _iter_key_from_wrapper(key: str) -> str:
    tail = key.rsplit("/", 1)[-1]
    return tail.split(":", 1)[1] if ":" in tail else tail


def _pick_primary(equations: list[Row]) -> Optional[Row]:
    media = [
        e for e in equations
        if e.get("status") == "completed" and e.get("result_media_ids")
    ]
    if media:
        return media[-1]
    completed = [e for e in equations if e.get("status") == "completed"]
    if completed:
        return completed[-1]
    failed = next((e for e in equations if e.get("status") == "failed"), None)
    if failed:
        return failed
    return equations[0] if equations else None


def _rollup_status(wrapper: Row, equations: list[Row]) -> str:
    if any(e.get("status") == "failed" for e in equations):
        return "failed"
    if any(e.get("status") == "computing" for e in equations):
        return "computing"
    if equations and all(e.get("status") in {"completed", "skipped"} for e in equations):
        return "completed"
    if any(e.get("status") == "awaiting_input" for e in equations):
        return "awaiting_input"
    return wrapper.get("status") or "pending"


def _substep_kind(eq: Optional[Row]) -> str:
    if eq is None:
        return "other"
    if eq.get("equation_type") == "hitl" and eq.get("hitl_kind") == "approve":
        return "hitl-approve"
    if eq.get("equation_type") in {
        "tool_call",
        "llm_call",
        "llm_slot",
        "code",
        "create_image",
        "create_layout",
        "create_grid",
        "create_set",
        "create_document",
        "web_search",
        "fetch_media",
    }:
        return "producer"
    return "other"


def _substep_display_name(sub: dict[str, Any], primitive: Row) -> str:
    if sub["kind"] == "hitl-approve":
        return "Your Turn"
    display = sub.get("displayName")
    if display and display != sub.get("relativePath"):
        return display
    return primitive.get("display_name") or sub.get("relativePath") or "Step"


def _aggregate_iterations(iterations: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(iterations),
        "completed": sum(1 for i in iterations if i.get("status") in {"completed", "skipped"}),
        "failed": sum(1 for i in iterations if i.get("status") == "failed"),
        "computing": sum(1 for i in iterations if i.get("status") == "computing"),
        "pending": sum(1 for i in iterations if i.get("status") == "pending"),
        "actionable": sum(1 for i in iterations if i.get("isActionable")),
    }


def _aggregate_duration(equations: list[Row]) -> Optional[int]:
    min_start = float("inf")
    max_end = float("-inf")
    wall_any = False
    sum_total = 0
    sum_any = False
    for eq in equations:
        d = eq.get("execution_duration_ms")
        if not isinstance(d, (int, float)) or d < 0:
            continue
        sum_total += int(d)
        sum_any = True
        completed = eq.get("completed_at")
        if not completed:
            continue
        try:
            from datetime import datetime
            end = datetime.fromisoformat(str(completed)).timestamp() * 1000
        except ValueError:
            continue
        start = end - d
        min_start = min(min_start, start)
        max_end = max(max_end, end)
        wall_any = True
    if wall_any:
        return int(max(0, max_end - min_start))
    return sum_total if sum_any else None


def _candidate_producer_for_slot(slot: dict[str, Any]) -> Optional[Row]:
    equations = slot.get("equations") or []
    by_key = {
        e.get("equation_key"): e
        for e in equations
        if e.get("equation_key")
    }
    approve = next(
        (
            e for e in equations
            if e.get("equation_type") == "hitl"
            and e.get("hitl_kind") == "approve"
        ),
        None,
    )
    if approve is not None:
        for dep_key in approve.get("dependencies") or []:
            candidate = by_key.get(dep_key)
            if candidate is not None and candidate.get("equation_type") != "hitl":
                return candidate
    with_media = next(
        (
            e for e in equations
            if e.get("equation_type") != "hitl" and e.get("result_media_ids")
        ),
        None,
    )
    if with_media:
        return with_media
    return next((e for e in equations if e.get("equation_type") != "hitl"), None)


def _classify_group_content_kind(primaries: Iterable[Optional[Row]]) -> str:
    values = [p for p in primaries if p is not None]
    if any(p.get("result_media_ids") for p in values):
        return "media"
    types = {p.get("equation_type") for p in values}
    if len(types) == 1 and "llm_call" in types:
        return "text"
    if values and all(p.get("equation_type") == "code" and p.get("status") == "completed" for p in values):
        return "text"
    return "media"


def _equation_is_actionable(eq: Row, rows_by_key: dict[str, Row]) -> bool:
    for dep_key in eq.get("dependencies") or []:
        dep = rows_by_key.get(dep_key)
        if dep is None:
            continue
        if dep.get("status") not in {"completed", "skipped"}:
            return False
    return True


def _classify_iteration_block(
    status: str,
    wrapper: Row,
    children: list[Row],
    rows_by_key: dict[str, Row],
) -> Optional[str]:
    if status != "pending":
        return None
    if wrapper.get("status") == "pending":
        return _classify_equation_block(wrapper, rows_by_key, set())
    for child in children:
        if child.get("status") == "pending":
            return _classify_equation_block(child, rows_by_key, set())
    return _classify_equation_block(wrapper, rows_by_key, set())


def _classify_equation_block(
    eq: Row,
    rows_by_key: dict[str, Row],
    visited: set[str],
) -> str:
    key = eq["equation_key"]
    if key in visited:
        return "compute"
    visited.add(key)
    status = eq.get("status")
    if status == "waiting_for_tool":
        return "tool"
    if status == "awaiting_input":
        return "human"

    found = defaultdict(bool)
    for dep_key in eq.get("dependencies") or []:
        dep = rows_by_key.get(dep_key)
        if dep is None or dep.get("status") in {"completed", "skipped"}:
            continue
        dep_status = dep.get("status")
        if dep_status == "failed":
            found["error"] = True
        elif dep_status == "awaiting_input":
            found["human"] = True
        elif dep_status == "waiting_for_tool":
            found["tool"] = True
        elif dep_status == "computing":
            found["compute"] = True
        elif dep_status == "pending":
            found[_classify_equation_block(dep, rows_by_key, visited)] = True
        else:
            found["compute"] = True

    if found["error"]:
        return "error"
    if found["human"]:
        return "human"
    if found["tool"]:
        return "tool"
    if found["compute"]:
        return "compute"
    return "cap"

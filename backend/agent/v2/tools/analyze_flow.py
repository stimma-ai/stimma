"""analyze_flow — read the current flow's runtime state.

Mirrors the data the frontend gets from /flows/{id}/phases, /equations, and
/tasks, rendered as compact agent-friendly text with drill-down hints.

Progressive disclosure:
- scope="overview" (default): phase summary + failure list + open-task count.
- scope="phase"   + name=<phase>: equations in one phase, with status/errors.
- scope="equation"+ name=<key>:   full detail for one equation.
- scope="tasks":                  all open user tasks.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select

from database import Chat, Flow

from ..tools_registry import ToolParameter, tool


_VALID_SCOPES = {"overview", "phase", "equation", "tasks"}


@tool(
    name="analyze_flow",
    description=(
        "Read the current state of this flow — phase progress, errors, "
        "stuck steps, and open human tasks. Call with no arguments for a "
        "compact overview; the output tells you exactly how to drill into "
        "a phase or equation for more detail. Use this BEFORE editing "
        "program.py on a 'please fix' request so you can tell build "
        "failures apart from runtime step failures. Only available in "
        "flow chats."
    ),
    parameters=[
        ToolParameter(
            name="scope",
            type="string",
            description=(
                "What to show. 'overview' (default) — phase summary with "
                "failures and open-task count. 'phase' — equations in one "
                "phase (pass the phase name or slash-separated path as "
                "`name`). 'equation' — full detail for one equation (pass "
                "the equation key as `name`), including the source, the "
                "input wiring, the resolved values of its upstream "
                "dependencies, and the full error traceback. 'tasks' — "
                "all pending user tasks (HITL + error)."
            ),
            required=False,
            enum=["overview", "phase", "equation", "tasks"],
        ),
        ToolParameter(
            name="name",
            type="string",
            description=(
                "Phase path (for scope='phase') or equation key (for "
                "scope='equation'). Phase paths are slash-separated: "
                "'Generate poses' or 'Outer/Inner'. Ignored for other scopes."
            ),
            required=False,
        ),
    ],
    scope="flow",
)
async def analyze_flow(
    scope: str = "overview",
    name: str | None = None,
    **kwargs,
) -> str:
    session = kwargs.get("session")
    chat_id = kwargs.get("chat_id")
    if session is None or chat_id is None:
        return "Error: analyze_flow requires an active chat session."

    chat_row = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = chat_row.scalar_one_or_none()
    if chat is None:
        return f"Error: chat {chat_id} not found."
    if chat.flow_id is None:
        return (
            "Error: this chat is not attached to a flow. analyze_flow is "
            "only usable in flow chats."
        )

    flow_row = await session.execute(
        select(Flow).where(Flow.id == chat.flow_id, Flow.deleted_at.is_(None))
    )
    flow = flow_row.scalar_one_or_none()
    if flow is None:
        return f"Error: flow {chat.flow_id} not found or deleted."

    if scope not in _VALID_SCOPES:
        return (
            f"Error: unknown scope {scope!r}. Valid scopes: "
            f"{', '.join(sorted(_VALID_SCOPES))}."
        )

    # Late imports: routes.flows pulls in FastAPI + many backend modules,
    # and the agent's flow_runtime deps want to initialise lazily.
    from routes.flows import (
        _apply_runtime_overlay,
        _definition_from_runtime,
        _display_name_for_equation,
        _load_equations_for_flow,
    )

    rows = _apply_runtime_overlay(
        _load_equations_for_flow(flow.id), flow.id,
    )
    for row in rows:
        row["definition"] = _definition_from_runtime(flow.id, row["equation_key"])
        row["display_name"] = _display_name_for_equation(
            row["equation_type"], row["definition"],
        )

    if scope == "overview":
        return _format_overview(flow, rows)
    if scope == "phase":
        if not name:
            return (
                "Error: scope='phase' requires `name` (the phase path). "
                "Call analyze_flow() with no arguments to see available phases."
            )
        return _format_phase(rows, name)
    if scope == "equation":
        if not name:
            return (
                "Error: scope='equation' requires `name` (the equation key). "
                "Call analyze_flow() with no arguments to see failed keys."
            )
        return _format_equation(rows, name, flow_id=flow.id)
    if scope == "tasks":
        return _format_tasks(flow)
    return "Error: unreachable"


# ---------- overview --------------------------------------------------------


def _format_overview(flow: Flow, rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f'Flow: "{flow.name}"  — state: {flow.execution_state}')
    lines.append(f"Inputs: {_fmt_inputs(flow)}")
    lines.append("")

    # Surface a build failure up front. The UI shows users a jargon-free
    # "ask the assistant" card without the error text, so this is how the
    # agent actually sees what broke after a fresh "please fix" request.
    load_err = _current_load_error(flow.id)
    if load_err is not None:
        lines.append(
            "Failure mode: BUILD ERROR — program.py doesn't compile or "
            "build a valid graph. Fix this first; equation-level data below "
            "is stale until the build passes."
        )
        lines.append(f"  category: {load_err.get('category', 'error')}")
        msg = str(load_err.get("message") or "unknown error")
        for raw_line in msg.splitlines()[:20]:
            lines.append(f"  {raw_line}")
        suggestion = load_err.get("suggestion")
        if suggestion:
            lines.append(f"  hint: {suggestion}")
        ctx = _program_context_for_traceback(flow.id, msg)
        if ctx:
            lines.append("")
            lines.append("Program.py context around the failure:")
            lines.extend(ctx)
        lines.append("")
        lines.append(
            "Next step: read the error above, then read_file/edit_file/"
            "write_file program.py until 'Graph built successfully' comes back."
        )
        lines.append("")

    if not rows:
        lines.append(
            "(No compiled graph yet — write program.py first, the build hook "
            "will populate the phase tree.)"
        )
        return "\n".join(lines)

    # Group equations by top-level phase for the summary. Skip the synthetic
    # "(root)" bucket when it only holds flow_input scaffolding — those are
    # already summarised in the "Inputs:" line above.
    by_top: dict[str, list[dict[str, Any]]] = {}
    top_order: list[str] = []
    for row in rows:
        path = row.get("phase_path") or []
        top = path[0] if path else "(root)"
        if top not in by_top:
            by_top[top] = []
            top_order.append(top)
        by_top[top].append(row)

    def is_input_only(phase_rows: list[dict[str, Any]]) -> bool:
        return all(r["equation_type"] == "flow_input" for r in phase_rows)

    visible_tops = [
        name for name in top_order
        if not (name == "(root)" and is_input_only(by_top[name]))
    ]

    lines.append("Phases:")
    if not visible_tops:
        lines.append("  (none yet)")
    else:
        name_w = max(len(p) for p in visible_tops)
        for phase_name in visible_tops:
            phase_rows = by_top[phase_name]
            summary = _status_summary(phase_rows)
            glyph = _phase_glyph(summary)
            counts = _compact_counts(summary)
            lines.append(f"  {glyph} {phase_name:<{name_w}}  — {counts}")
    lines.append("")

    fails = [r for r in rows if r["status"] == "failed"]
    if fails and load_err is None:
        lines.append(
            f"Failure mode: RUNTIME STEP FAILURE — build passed, "
            f"{len(fails)} equation(s) failed during evaluation."
        )
        lines.append(
            "Next step: drill into each with analyze_flow(scope='equation', "
            "name=<key>). That view gives you the full source, the resolved "
            "input values the step actually saw, and the full traceback — "
            "enough to tell a program-logic bug (edit program.py) from a "
            "transient tool failure (the user retries in the UI; don't "
            "retry for them)."
        )
        for r in fails[:10]:
            phase = "/".join(r.get("phase_path") or []) or "(root)"
            label = r.get("display_name") or r["equation_type"]
            err = _first_line(r.get("error") or "", 160)
            lines.append(f"  [{phase}] {r['equation_key']} · {label} · {err}")
            lines.append(
                f"    → analyze_flow(scope='equation', name={r['equation_key']!r})"
            )
        if len(fails) > 10:
            lines.append(f"  …and {len(fails) - 10} more")
        lines.append("")
    elif fails:
        # Build failed; equation rows are stale. Mention the count but point
        # back at the build error as the thing to fix first.
        lines.append(
            f"(Also {len(fails)} equation(s) show FAILED status, but these are "
            "stale — fix the build error above first; the graph will rebuild.)"
        )
        lines.append("")

    # Stuck steps: pending equations whose upstream includes a failure. These
    # are the blockers — not themselves broken, but they can't make progress
    # until the failure above is resolved. Surfacing them tells the agent
    # which user-visible phases will unstick when it fixes the root cause.
    stuck = _find_stuck_pending(rows)
    if stuck and load_err is None:
        lines.append(
            f"Blocked by failures ({len(stuck)}): these steps can't run "
            "until the failures above are fixed."
        )
        for r in stuck[:5]:
            phase = "/".join(r.get("phase_path") or []) or "(root)"
            label = r.get("display_name") or r["equation_type"]
            upstream_fails = _upstream_failures(r, rows)
            upstream = ", ".join(upstream_fails[:3])
            if len(upstream_fails) > 3:
                upstream += f" (+{len(upstream_fails) - 3} more)"
            lines.append(f"  [{phase}] {r['equation_key']} · {label} — waiting on {upstream}")
        if len(stuck) > 5:
            lines.append(f"  …and {len(stuck) - 5} more")
        lines.append("")

    awaiting = [r for r in rows if r["status"] == "awaiting_input"]
    if awaiting:
        lines.append(f"Open user tasks ({len(awaiting)}):")
        for r in awaiting[:5]:
            phase = "/".join(r.get("phase_path") or []) or "(root)"
            label = r.get("display_name") or r["equation_type"]
            lines.append(f"  [{phase}] {r['equation_key']} · {label}")
        if len(awaiting) > 5:
            lines.append(f"  …and {len(awaiting) - 5} more")
        lines.append("  → analyze_flow(scope='tasks')")
        lines.append("")

    lines.append("Drill in:")
    lines.append("  analyze_flow(scope='phase',    name='<phase-name>')")
    lines.append("  analyze_flow(scope='equation', name='<equation-key>')")
    lines.append("  analyze_flow(scope='tasks')")
    return "\n".join(lines)


# ---------- phase -----------------------------------------------------------


def _format_phase(rows: list[dict[str, Any]], phase_arg: str) -> str:
    target = _parse_phase_path(phase_arg)
    if not target:
        return "Error: empty phase path. Pass the phase name as `name`."

    def prefix_matches(path: list[str], t: list[str]) -> bool:
        if len(path) < len(t):
            return False
        return [p.lower() for p in path[: len(t)]] == [p.lower() for p in t]

    matching = [r for r in rows if prefix_matches(r.get("phase_path") or [], target)]
    if not matching:
        available = sorted(
            {"/".join(r.get("phase_path") or []) for r in rows if r.get("phase_path")}
        )
        msg = [f"Error: no phase matching {phase_arg!r}."]
        if available:
            msg.append("Available phases:")
            for p in available:
                msg.append(f"  {p}")
        return "\n".join(msg)

    lines: list[str] = []
    lines.append(f"Phase: {'/'.join(target)}")
    lines.append(f"Status: {_compact_counts(_status_summary(matching))}")
    lines.append("")
    lines.append("Equations (in build order):")
    for r in matching:
        label = r.get("display_name") or r["equation_type"]
        status = r["status"]
        suffix = ""
        if status == "failed" and r.get("error"):
            suffix = f" — {_first_line(r['error'], 120)}"
        elif status == "pending":
            blockers = _unresolved_deps(r, rows)
            if blockers:
                suffix = f" — waiting on {', '.join(blockers[:3])}"
                if len(blockers) > 3:
                    suffix += f" (+{len(blockers) - 3} more)"
        lines.append(f"  {r['equation_key']} · {label} · {status.upper()}{suffix}")

    failed_keys = [r["equation_key"] for r in matching if r["status"] == "failed"]
    if failed_keys:
        lines.append("")
        lines.append("For failure details:")
        for k in failed_keys[:3]:
            lines.append(f"  analyze_flow(scope='equation', name={k!r})")
    return "\n".join(lines)


# ---------- equation --------------------------------------------------------


def _format_equation(
    rows: list[dict[str, Any]], key: str, flow_id: int | None = None,
) -> str:
    row = next((r for r in rows if r["equation_key"] == key), None)
    if row is None:
        return (
            f"Error: no equation with key {key!r}. Call analyze_flow() with "
            "no arguments to see valid keys."
        )
    phase = "/".join(row.get("phase_path") or []) or "(root)"
    etype = row["equation_type"]
    status = row["status"]
    lines: list[str] = []
    lines.append(f"Equation: {key}  (phase: {phase})")
    lines.append(f"Type: {etype}   Status: {status}")
    if row.get("display_name"):
        lines.append(f"Display name: {row['display_name']}")
    if row.get("attempt", 1) > 1:
        lines.append(f"Attempt: {row['attempt']}")

    definition = row.get("definition") or {}
    if definition:
        _append_definition_block(lines, etype, definition)

    _append_input_wiring(lines, row, rows)

    if row.get("error"):
        lines.append("")
        lines.append("Error:")
        err_text = str(row["error"])
        err_lines = err_text.splitlines()
        for raw_line in err_lines[:60]:
            lines.append(f"  {raw_line}")
        remaining = len(err_lines) - 60
        if remaining > 0:
            lines.append(f"  …({remaining} more lines truncated)")

        # Expand each program.py frame referenced in the traceback with a
        # few lines of surrounding source. The traceback itself only shows
        # the single failing line; the ±2 context helps the agent see the
        # enclosing lambda / call / statement without a separate read_file.
        if flow_id is not None:
            ctx = _program_context_for_traceback(flow_id, err_text)
            if ctx:
                lines.append("")
                lines.append("Program.py context around the failure:")
                lines.extend(ctx)

    res = row.get("result")
    if res is not None:
        lines.append("")
        lines.append(f"Result: {_value_preview(res, 400)}")
    media = row.get("result_media_ids") or []
    if media:
        lines.append(f"Result media ids: {media}")
    return "\n".join(lines)


def _append_definition_block(
    lines: list[str], etype: str, d: dict[str, Any],
) -> None:
    """Render a compact static definition: output type, tool id, model, etc.

    We intentionally do NOT dump the full source of a code() callable or
    the full text of an llm() prompt — those already live in program.py,
    which the agent can read_file on demand. Dumping them here bloats the
    tool output without adding information. A one-line preview is enough
    to jog the agent's memory about which step this is."""
    if etype == "code":
        lines.append("")
        source = d.get("source") or ""
        if source:
            lines.append(f"Source preview: {_first_line(str(source), 140)}")
        if d.get("output_type"):
            lines.append(f"Output type: {d['output_type']}")
        if d.get("description"):
            lines.append(f"Description: {d['description']}")
        return

    if etype == "llm_call":
        lines.append("")
        if d.get("model"):
            lines.append(f"Model: {d['model']}")
        prompt = d.get("prompt")
        if isinstance(prompt, str) and prompt:
            lines.append(f"Prompt preview: {_first_line(prompt, 200)}")
        elif prompt is not None:
            lines.append("Prompt: (built from upstream node at runtime)")
        if d.get("response_format"):
            lines.append(
                f"Response format: {_value_preview(d.get('response_format'), 200)}"
            )
        return

    if etype == "tool_call":
        lines.append("")
        if d.get("tool_id"):
            lines.append(f"Tool id: {d['tool_id']}")
        if "n" in d:
            lines.append(f"n: {d['n']}")
        params = d.get("params") or d.get("static_params") or {}
        if params:
            lines.append("Static params:")
            for k, v in params.items():
                lines.append(f"  {k}: {_value_preview(v, 160)}")
        return

    # Fallback: compact key/value summary for hitl / info / flow_input /
    # control / create_* types.
    summary = _summarize_definition(etype, d)
    if summary:
        lines.append("")
        lines.append("Definition:")
        for k, v in summary.items():
            lines.append(f"  {k}: {v}")


_TRACEBACK_FRAME_RE = re.compile(
    r'^\s*File "(?P<path>[^"]+)", line (?P<lineno>\d+)',
)


def _program_context_for_traceback(
    flow_id: int, error_text: str,
) -> list[str]:
    """Emit a few lines of program.py context around each traceback frame.

    The runtime's traceback formatter filters to user frames, so any
    ``File "…/program.py"`` line in the error text is a step the agent's
    code is implicated in. We don't re-print the caret/source line the
    traceback already rendered; instead we pull ±2 lines from the file
    so multi-line lambdas / dict literals / comprehensions are visible in
    context.
    """
    try:
        from flow_runtime.paths import get_flow_program_path
    except ImportError:
        return []
    program_path = get_flow_program_path(flow_id)
    if not program_path.exists():
        return []
    try:
        source_lines = program_path.read_text().splitlines()
    except OSError:
        return []
    out: list[str] = []
    shown: set[int] = set()
    for raw in error_text.splitlines():
        m = _TRACEBACK_FRAME_RE.match(raw)
        if not m:
            continue
        path = m.group("path")
        if not path.endswith("program.py"):
            continue
        try:
            lineno = int(m.group("lineno"))
        except (TypeError, ValueError):
            continue
        if lineno in shown:
            continue
        shown.add(lineno)
        start = max(1, lineno - 2)
        end = min(len(source_lines), lineno + 2)
        out.append(f"  near line {lineno}:")
        lineno_w = len(str(end))
        for i in range(start, end + 1):
            marker = ">" if i == lineno else " "
            text = source_lines[i - 1]
            out.append(f"    {marker} {str(i).rjust(lineno_w)} | {text}")
    return out


def _append_input_wiring(
    lines: list[str], row: dict[str, Any], rows: list[dict[str, Any]],
) -> None:
    """Show input names → upstream equations and the dependency results.

    This is the single highest-value section for debugging: when a code or
    llm step fails with a shape mismatch, the agent needs to see the actual
    resolved values that were handed in. We reconstruct them from the
    upstream equations' persisted results (they survive restarts)."""
    by_key = {r["equation_key"]: r for r in rows}
    etype = row["equation_type"]
    definition = row.get("definition") or {}

    # Map input name → upstream equation key, when the runtime recorded one.
    # code/info/llm store this as ``_dynamic.inputs`` (or ``_dynamic.prompt``
    # for llm); other types keep dynamic refs at the top level of _dynamic.
    input_map: dict[str, str] = {}
    dynamic = definition.get("_dynamic") or {}
    if etype in ("code", "info", "create_image", "create_layout"):
        dynamic_inputs = dynamic.get("inputs") or {}
        for k, v in dynamic_inputs.items():
            dep_key = _extract_noderef_key(v)
            if dep_key is not None:
                input_map[k] = dep_key
    elif etype == "llm_call":
        # prompt / system / images can each be a NodeRef
        for slot in ("prompt", "system", "images"):
            v = dynamic.get(slot)
            if v is None:
                continue
            dep_key = _extract_noderef_key(v)
            if dep_key is not None:
                input_map[slot] = dep_key
    elif etype == "tool_call":
        # The runtime stores every NodeRef param under _dynamic directly.
        for k, v in dynamic.items():
            dep_key = _extract_noderef_key(v)
            if dep_key is not None:
                input_map[k] = dep_key

    deps: list[str] = row.get("dependencies") or []
    if not deps and not input_map:
        return

    lines.append("")
    if input_map:
        lines.append("Inputs (resolved):")
        shown_dep_keys: set[str] = set()
        for input_name, dep_key in input_map.items():
            dep = by_key.get(dep_key)
            shown_dep_keys.add(dep_key)
            if dep is None:
                lines.append(
                    f"  {input_name} ← {dep_key} (not in current graph)"
                )
                continue
            dep_label = dep.get("display_name") or dep["equation_type"]
            lines.append(
                f"  {input_name} ← {dep_key} · {dep_label} · {dep['status']}"
            )
            if dep["status"] == "completed":
                preview = _value_preview(dep.get("result"), 300)
                if preview:
                    lines.append(f"    value: {preview}")
            elif dep.get("error"):
                lines.append(
                    f"    error: {_first_line(str(dep['error']), 120)}"
                )
        # Any remaining dependencies that weren't named inputs (shouldn't
        # happen often, but tool_call equations sometimes include derived
        # deps) — list them plainly so the agent knows the full upstream.
        extra = [k for k in deps if k not in shown_dep_keys]
        if extra:
            lines.append("Additional dependencies:")
            for dep_key in extra:
                dep = by_key.get(dep_key)
                if dep is None:
                    lines.append(f"  {dep_key} — (not in current graph)")
                    continue
                dep_label = dep.get("display_name") or dep["equation_type"]
                lines.append(
                    f"  {dep_key} · {dep_label} · {dep['status']}"
                )
    else:
        lines.append("Dependencies:")
        for dep_key in deps:
            dep = by_key.get(dep_key)
            if dep is None:
                lines.append(f"  {dep_key} — (not in current graph)")
                continue
            dep_label = dep.get("display_name") or dep["equation_type"]
            lines.append(
                f"  {dep_key} · {dep_label} · {dep['status']}"
            )
            if dep["status"] == "completed":
                preview = _value_preview(dep.get("result"), 300)
                if preview:
                    lines.append(f"    value: {preview}")


def _extract_noderef_key(v: Any) -> str | None:
    """Return the equation_key when ``v`` is (or contains) a NodeRef.

    The live graph's ``definition["_dynamic"]`` holds raw ``NodeRef``
    instances — not JSON-serialised dicts, because ``_dynamic`` is the
    one part of the definition that isn't persisted. We walk lists /
    tuples / dicts looking for a ``NodeRef`` or its equation_key. A
    single pointer is enough for labelling the input."""
    try:
        from flow_runtime.graph import NodeRef  # lazy — runtime module
    except ImportError:
        NodeRef = None  # type: ignore[assignment]
    if NodeRef is not None and isinstance(v, NodeRef):
        return v.equation_key
    # Some persisted/serialised paths may round-trip a NodeRef as a dict;
    # tolerate that shape too.
    if isinstance(v, dict):
        k = v.get("equation_key")
        if isinstance(k, str) and (
            "__stimma_noderef__" in v or v.get("__noderef__") is True
        ):
            return k
        for sub in v.values():
            found = _extract_noderef_key(sub)
            if found:
                return found
        return None
    if isinstance(v, (list, tuple)):
        for sub in v:
            found = _extract_noderef_key(sub)
            if found:
                return found
    return None


# ---------- tasks -----------------------------------------------------------


def _format_tasks(flow: Flow) -> str:
    import flow_registry
    from flow_runtime import graph_db
    from flow_runtime.paths import get_flow_state_db_path

    runtime = flow_registry.get_runtime(flow.id)
    if runtime is not None:
        rows = runtime.list_tasks(status="pending")
    else:
        state_db = get_flow_state_db_path(flow.id)
        rows = graph_db.list_tasks(state_db, status="pending")

    if not rows:
        return "No pending user tasks."

    lines: list[str] = [f"Pending tasks ({len(rows)}):"]
    for r in rows:
        phase = "/".join(r.get("phase_path") or []) or "(root)"
        ttype = r.get("task_type", "?")
        instr = _value_preview(r.get("instructions"), 100)
        lines.append(f"  [{phase}] task {r['task_id']} · {ttype} · eq {r['equation_key']}")
        if instr:
            lines.append(f"    instructions: {instr}")
        if r.get("error"):
            lines.append(f"    error: {_first_line(str(r['error']), 120)}")
    lines.append("")
    lines.append(
        "User-facing tasks resolve when the user acts in the UI — don't try to "
        "resolve them yourself. Error tasks usually mean an equation failed and "
        "is waiting for a retry / skip decision."
    )
    return "\n".join(lines)


# ---------- helpers ---------------------------------------------------------


def _current_load_error(flow_id: int) -> dict[str, Any] | None:
    """Return the most recent program-load error for this flow, or None.

    Prefers the live runtime's ``last_load_error`` (truth) and falls back
    to the lifecycle cache (used when no runtime is registered yet).
    """
    try:
        import flow_registry
        import flow_lifecycle
    except ImportError:
        return None
    runtime = flow_registry.get_runtime(flow_id)
    if runtime is not None and runtime.last_load_error is not None:
        exc = runtime.last_load_error
        return {
            "category": getattr(exc, "category", "error"),
            "message": str(exc),
            "suggestion": getattr(exc, "suggestion", ""),
        }
    cached = flow_lifecycle.get_cached_load_error(flow_id)
    return cached


_STATUS_ORDER = (
    "completed",
    "computing",
    "failed",
    "awaiting_input",
    "pending",
    "invalidated",
    "skipped",
)


def _status_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    s: dict[str, int] = {}
    for r in rows:
        s[r["status"]] = s.get(r["status"], 0) + 1
    return s


def _compact_counts(summary: dict[str, int]) -> str:
    parts: list[str] = []
    total = sum(summary.values())
    completed = summary.get("completed", 0)
    parts.append(f"{completed}/{total} done")
    for status in _STATUS_ORDER:
        if status == "completed":
            continue
        n = summary.get(status, 0)
        if n:
            parts.append(f"{n} {status.replace('_', ' ')}")
    return " · ".join(parts) if parts else "empty"


def _phase_glyph(summary: dict[str, int]) -> str:
    if summary.get("failed"):
        return "✗"
    if summary.get("awaiting_input"):
        return "?"
    if summary.get("computing"):
        return "…"
    total = sum(summary.values())
    if total and summary.get("completed", 0) == total:
        return "✓"
    return "·"


def _parse_phase_path(raw: str) -> list[str]:
    return [p.strip() for p in raw.split("/") if p.strip()]


def _unresolved_deps(
    row: dict[str, Any], rows: list[dict[str, Any]],
) -> list[str]:
    by_key = {r["equation_key"]: r for r in rows}
    out: list[str] = []
    for dep_key in row.get("dependencies") or []:
        dep = by_key.get(dep_key)
        if dep is None or dep["status"] != "completed":
            out.append(dep_key)
    return out


def _upstream_failures(
    row: dict[str, Any], rows: list[dict[str, Any]],
) -> list[str]:
    """Walk transitive dependencies and return the keys that are FAILED."""
    by_key = {r["equation_key"]: r for r in rows}
    seen: set[str] = set()
    failed: list[str] = []
    stack: list[str] = list(row.get("dependencies") or [])
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        dep = by_key.get(k)
        if dep is None:
            continue
        if dep["status"] == "failed":
            failed.append(k)
            continue  # don't walk past failures — their upstream is irrelevant
        stack.extend(dep.get("dependencies") or [])
    return failed


def _find_stuck_pending(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return pending equations blocked by at least one failed upstream."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["status"] != "pending":
            continue
        if _upstream_failures(r, rows):
            out.append(r)
    return out


def _fmt_inputs(flow: Flow) -> str:
    schema = _loads_or_empty(flow.input_schema)
    values = _loads_or_empty(flow.inputs)
    if not schema:
        return "(no inputs declared)"
    parts: list[str] = []
    for k in schema:
        if k not in values or values[k] in (None, ""):
            parts.append(f"{k}=⚠ unset")
            continue
        parts.append(f"{k}={_value_preview(values[k], 40)}")
    return ", ".join(parts)


def _loads_or_empty(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def _summarize_definition(etype: str, d: dict[str, Any]) -> dict[str, str]:
    """Compact key/value summary for phase/overview rendering.

    ``_append_definition_block`` handles code/llm/tool equations in the
    equation scope with a fuller treatment; this summary is the fallback
    for everything else (hitl, info, flow_input, control, create_*).
    """
    out: dict[str, str] = {}
    if etype == "tool_call":
        out["tool_id"] = str(d.get("tool_id", ""))
        if "n" in d:
            out["n"] = str(d.get("n"))
        params = d.get("params") or d.get("static_params") or {}
        if params:
            out["params"] = ", ".join(
                f"{k}={_value_preview(v, 40)}" for k, v in params.items()
            )
    elif etype == "llm_call":
        if "model" in d:
            out["model"] = str(d.get("model"))
        if "prompt" in d:
            out["prompt"] = _value_preview(d.get("prompt"), 160)
    elif etype == "code":
        out["source"] = _value_preview(d.get("source"), 200)
        if d.get("output_type"):
            out["output_type"] = str(d["output_type"])
        if d.get("description"):
            out["description"] = str(d["description"])
    elif etype == "hitl":
        if d.get("hitl_type"):
            out["hitl_type"] = str(d["hitl_type"])
        if "count" in d:
            out["count"] = str(d.get("count"))
        if d.get("instructions"):
            out["instructions"] = _value_preview(d["instructions"], 160)
    elif etype == "flow_input":
        if d.get("input_name"):
            out["input_name"] = str(d["input_name"])
    elif etype == "control":
        if d.get("control_kind"):
            out["control_kind"] = str(d["control_kind"])
        # hitl.approve wrappers carry their `count` and `instructions` on
        # the primitive itself (not on each per-slot HITL task). Surfacing
        # them here lets the agent distinguish a hitl.approve row from a
        # generic foreach without spelunking the slot subtree.
        if d.get("control_kind") == "approve":
            if "count" in d:
                out["count"] = str(d.get("count"))
            if d.get("instructions"):
                out["instructions"] = _value_preview(d["instructions"], 160)
    return out


def _value_preview(v: Any, max_len: int = 120) -> str:
    """Compact textual preview that keeps shape information.

    Unlike ``repr``, this surfaces length/keys for lists and dicts so the
    agent can tell 'got a list of 12 strings' from 'got a dict with 3
    keys' without us dumping the full value. Strings longer than
    ``max_len`` get truncated mid-repr with a marker."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return repr(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        if len(v) <= max_len:
            return repr(v)
        head = v[: max_len - 1]
        return repr(head) + f"… ({len(v)} chars total)"
    if isinstance(v, list):
        if not v:
            return "[]  (empty list)"
        # Render a short prefix so the agent sees element shape.
        prefix = ", ".join(_value_preview(x, 60) for x in v[:4])
        suffix = f", …" if len(v) > 4 else ""
        inner = f"[{prefix}{suffix}]"
        if len(inner) > max_len:
            inner = inner[: max_len - 1] + "…"
        return f"{inner}  ({len(v)} items, {_element_shape_hint(v)})"
    if isinstance(v, dict):
        if not v:
            return "{}  (empty dict)"
        keys = list(v.keys())
        keys_preview = ", ".join(repr(k) for k in keys[:6])
        if len(keys) > 6:
            keys_preview += f", … (+{len(keys) - 6} more)"
        return f"dict with keys: {keys_preview}"
    s = repr(v)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _element_shape_hint(xs: list[Any]) -> str:
    """Describe the element type of a list in a couple of words."""
    if not xs:
        return "empty"
    types = {type(x).__name__ for x in xs[:20]}
    if len(types) == 1:
        only = next(iter(types))
        return f"all {only}"
    return f"mixed: {', '.join(sorted(types))}"


def _first_line(text: str, max_len: int = 120) -> str:
    first = text.splitlines()[0] if text else ""
    return first[:max_len] + ("…" if len(first) > max_len else "")

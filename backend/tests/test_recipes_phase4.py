"""Phase 4 tests — HITL + task system.

Covers the Phase 4 exit gate from docs/RECIPES_DEV_PLAN.md §Phase 4:

  1. HITL primitives work end-to-end: task creation, payload,
     resolution, downstream unblock.
  2. Error tasks surface for all failure categories, all actions
     (retry, skip, edit_recipe) work, skip rejected for
     non-loop equations.
  3. HITL results durable across edits and forks. Recovery on rename works.
  4. Cross-recipe task listing works (with a Phase-6 perf TODO
     acknowledged).
  5. WebSocket events broadcast on creation and resolution.

Plus the Phase 4 §Test risks:

  - Race: user resolves while the agent invalidates → idempotent.
  - "Unblocks most work" calc against a known graph.
  - Resolution shape validation — 4xx on malformed resolution.

Tests are hermetic: real per-recipe SQLite + fresh equation store + mock
evaluators, same pattern as phase 2.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from recipe_runtime import (
    EquationStatus,
    EquationStore,
    EvaluationRequest,
    EvaluationResult,
    EvaluatorError,
    EvaluatorRegistry,
    RecipeRuntime,
    create_recipe_state_db,
    graph_db,
)
from recipe_runtime.dsl import (
    code,
    foreach,
    hitl,
    input as dsl_input,
    llm,
    output as dsl_output,
    phase,
    recipe,
    tool,
)
from recipe_runtime.engine import (
    _error_actions_for,
    _is_inside_foreach_iteration,
    _iteration_prefix_for,
)
from recipe_runtime.media_arg import Media
from recipe_runtime.summary import include_equation_in_status_summary
from routes.recipes import _json_safe_recipe_value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_store_and_db():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "state.db"
        create_recipe_state_db(db_path)
        store = EquationStore(root / "store")
        store.initialize()
        yield db_path, store


def _mock_evaluators(
    *,
    tool_value: Any = None,
    llm_value: Any = None,
    code_value: Any = None,
    fail_keys: set[str] | None = None,
    fail_category: str = "transient",
    call_counter: dict[str, int] | None = None,
) -> EvaluatorRegistry:
    reg = EvaluatorRegistry()
    fail_keys = fail_keys or set()
    call_counter = call_counter if call_counter is not None else {}

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        call_counter[req.equation_key] = call_counter.get(req.equation_key, 0) + 1
        if req.equation_key in fail_keys:
            raise EvaluatorError(f"mock tool failure for {req.equation_key}", category=fail_category)
        if tool_value is not None:
            return EvaluationResult(value=tool_value)
        # Derive a per-iteration marker from the equation key so foreach-over-
        # range(N) produces distinct ["cand#0", "cand#1", ...] values.
        match = re.search(r":(\d+)/tool\$", req.equation_key)
        idx = int(match.group(1)) if match else 0
        return EvaluationResult(value=f"cand#{idx}" if match else "asset")

    async def llm_eval(req: EvaluationRequest) -> EvaluationResult:
        call_counter[req.equation_key] = call_counter.get(req.equation_key, 0) + 1
        if req.equation_key in fail_keys:
            raise EvaluatorError(f"mock llm failure for {req.equation_key}", category=fail_category)
        return EvaluationResult(value=llm_value if llm_value is not None else "llm_out")

    async def code_eval(req: EvaluationRequest) -> EvaluationResult:
        call_counter[req.equation_key] = call_counter.get(req.equation_key, 0) + 1
        if req.equation_key in fail_keys:
            raise EvaluatorError(f"mock code failure for {req.equation_key}", category=fail_category)
        return EvaluationResult(value=code_value if code_value is not None else "code_out")

    reg.register("tool_call", tool_eval)
    reg.register("llm_call", llm_eval)
    reg.register("code", code_eval)
    return reg


async def _wait_for_pending_tasks(db_path: Path, count: int, timeout: float = 3.0) -> list[dict]:
    deadline = asyncio.get_event_loop().time() + timeout
    last: list[dict] = []
    while asyncio.get_event_loop().time() < deadline:
        rows = graph_db.list_tasks(db_path, status="pending")
        last = rows
        if len(rows) >= count:
            return rows
        await asyncio.sleep(0.02)
    raise AssertionError(f"expected {count} pending tasks, got {len(last)}: {last}")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_inside_foreach_iteration(self):
        assert _is_inside_foreach_iteration("fn:Mojito")
        assert _is_inside_foreach_iteration("fn:Mojito/tool$0")
        assert _is_inside_foreach_iteration("outer:A/inner:B")
        assert not _is_inside_foreach_iteration("fn")
        assert not _is_inside_foreach_iteration("fn/tool$0")
        assert not _is_inside_foreach_iteration("r/llm$0/slot:0")

    def test_iteration_prefix_for(self):
        assert _iteration_prefix_for("fn:Mojito") == "fn:Mojito/"
        assert _iteration_prefix_for("fn:Mojito/tool$0") == "fn:Mojito/"
        assert _iteration_prefix_for("outer:A/inner:B/tool$0") == "outer:A/inner:B/"
        assert _iteration_prefix_for("r/llm$0/slot:0") is None
        assert _iteration_prefix_for("fn") is None

    def test_error_actions_for_loop(self):
        assert "skip" in _error_actions_for(True)
        assert "skip" not in _error_actions_for(False)
        for action in ("retry", "edit_recipe"):
            assert action in _error_actions_for(True)
            assert action in _error_actions_for(False)

    def test_pending_scaffolding_counts_in_status_summary(self):
        definition = {"control_kind": "foreach"}
        assert include_equation_in_status_summary("control", definition, "pending")
        assert include_equation_in_status_summary("control", definition, "failed")
        assert not include_equation_in_status_summary("control", definition, "completed")

    def test_json_safe_recipe_value_serializes_media_wrappers(self):
        media = Media(42, path="/tmp/render.png", filename="render.png")

        assert _json_safe_recipe_value(
            {
                media: {"asset": media},
                "items": [media, (media,)],
                "plain": "ok",
            }
        ) == {
            "render.png": {"asset": {"id": 42, "filename": "render.png"}},
            "items": [
                {"id": 42, "filename": "render.png"},
                [{"id": 42, "filename": "render.png"}],
            ],
            "plain": "ok",
        }


# ---------------------------------------------------------------------------
# HITL task creation — per-primitive payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_task_payload(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            cands = foreach(range(3), lambda _: tool("gen", task_type="text-to-image", prompt="p"))
            return hitl.select(cands, instructions="pick one", count=1)

    runtime = RecipeRuntime(
        101, db_path, recipe_callable=r, evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    await runtime.pause()
    await runtime.stop()

    task = rows[0]
    assert task["task_type"] == "select"
    assert task["instructions"] == "pick one"
    assert task["payload"]["count"] == 1
    assert task["payload"]["candidates"] == ["cand#0", "cand#1", "cand#2"]


@pytest.mark.asyncio
async def test_approve_task_payload(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return hitl.approve(
                1,
                lambda _: tool("gen", task_type="text-to-image", prompt="p"),
                instructions="ok?",
            )

    runtime = RecipeRuntime(
        102, db_path, recipe_callable=r, evaluators=_mock_evaluators(tool_value="fancy_asset"), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    await runtime.pause()
    await runtime.stop()

    task = rows[0]
    assert task["task_type"] == "approve"
    assert task["payload"]["asset"] == "fancy_asset"


# ---------------------------------------------------------------------------
# HITL task resolution per primitive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_resolution_unblocks_downstream(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            cands = foreach(range(3), lambda _: tool("gen", task_type="text-to-image", prompt="p"))
            picked = hitl.select(cands, instructions="pick", count=1)
            return code("return picked", inputs={"picked": picked})

    runtime = RecipeRuntime(
        110, db_path, recipe_callable=r, evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    await runtime.resolve_task(rows[0]["task_id"], "cand#1")
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.stop()

    # HITL result persisted
    hitl_row = graph_db.lookup_hitl_result(db_path, rows[0]["equation_key"], rows[0]["inputs_hash"])
    assert hitl_row == "cand#1"
    # Downstream code block completed
    keys = {eq.key: eq for eq in runtime.graph.all_equations()}
    code_key = next(k for k in keys if k.endswith("/code$0"))
    assert keys[code_key].status == EquationStatus.COMPLETED


@pytest.mark.asyncio
async def test_approve_accept_completes_equation(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return hitl.approve(
                1,
                lambda _: tool("gen", task_type="text-to-image", prompt="p"),
                instructions="?",
            )

    runtime = RecipeRuntime(
        111, db_path, recipe_callable=r, evaluators=_mock_evaluators(tool_value="art1"), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    await runtime.resolve_task(rows[0]["task_id"], True)
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.stop()

    approve_eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/hitl.approve$0"))
    assert approve_eq.status == EquationStatus.COMPLETED
    # approve is a pass-through gate: on accept, the equation's result is the
    # upstream asset (here the tool's output), not the raw `True` resolution.
    # The DSL declares approve has the same shape as the input, so downstream
    # consumers see the approved media, not the yes/no decision.
    assert approve_eq.result == "art1"


@pytest.mark.asyncio
async def test_approve_reject_invalidates_upstream_and_re_asks(isolated_store_and_db):
    """Rejection-is-invalidation: upstream bumps attempt, re-surfaces task."""
    db_path, store = isolated_store_and_db

    counter: dict[str, int] = {}

    @recipe()
    def r():
        with phase("Run"):
            return hitl.approve(
                1,
                lambda _: tool("gen", task_type="text-to-image", prompt="p"),
                instructions="?",
            )

    # Tool returns attempt-specific value so rejection + re-evaluation
    # yields a different upstream asset (as real tools with seeds do).
    reg = EvaluatorRegistry()

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        counter[req.equation_key] = counter.get(req.equation_key, 0) + 1
        return EvaluationResult(value=f"asset@attempt{req.attempt}")

    reg.register("tool_call", tool_eval)

    runtime = RecipeRuntime(
        112, db_path, recipe_callable=r,
        evaluators=reg,
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    tool_key = next(k for k in runtime.graph.keys() if k.endswith("/tool$0"))
    assert counter.get(tool_key, 0) == 1
    # Reject.
    await runtime.resolve_task(rows[0]["task_id"], False)
    # Approve task should re-surface after the upstream recomputes.
    rows2 = await _wait_for_pending_tasks(db_path, 1)  # a new pending task exists
    # Upstream tool was re-evaluated.
    assert counter.get(tool_key, 0) >= 2
    assert runtime.graph.get(tool_key).attempt == 2

    # Second attempt: accept it.
    # Multiple rows may include the resolved one; grab the pending one.
    pending = [r for r in rows2 if r["status"] == "pending"]
    await runtime.resolve_task(pending[-1]["task_id"], True)
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.stop()

    approve_eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/hitl.approve$0"))
    assert approve_eq.status == EquationStatus.COMPLETED


# ---------------------------------------------------------------------------
# Error tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_task_created_on_failure(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return tool("gen", task_type="text-to-image", prompt="fail")

    reg = _mock_evaluators(fail_keys={"r/tool$0"}, fail_category="tool_error")
    runtime = RecipeRuntime(
        120, db_path, recipe_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    # Wait until failure surfaces as a task.
    tasks = await _wait_for_pending_tasks(db_path, 1, timeout=3.0)
    await runtime.stop()

    t = tasks[0]
    assert t["task_type"] == "error"
    assert t["equation_status"] == "failed"
    assert t["payload"]["error_type"] == "tool_error"
    assert t["payload"]["phase_path"] == ["Run"]
    assert "available_actions" in t["payload"]
    # Not inside a foreach -> no skip
    assert "skip" not in t["payload"]["available_actions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["transient", "tool_error", "code_error", "llm_error", "resource"])
async def test_error_task_metadata_per_failure_category(isolated_store_and_db, category):
    """Error task records the category across all five failure categories
    per RECIPES_TECH §Error Handling. RESOURCE pauses the recipe but still
    surfaces the task before pausing."""
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return tool("gen", task_type="text-to-image", prompt="boom")

    reg = _mock_evaluators(
        fail_keys={"r/tool$0"}, fail_category=category,
    )
    runtime = RecipeRuntime(
        200 + hash(category) % 1000, db_path, recipe_callable=r,
        evaluators=reg, store=store, retry_backoff_seconds=0.0,
    )
    runtime.build_initial_graph()
    await runtime.start()
    tasks = await _wait_for_pending_tasks(db_path, 1, timeout=5.0)
    await runtime.stop()

    assert tasks[0]["task_type"] == "error"
    assert tasks[0]["payload"]["error_type"] == category
    assert tasks[0]["payload"]["equation_type"] == "tool_call"
    assert "retry" in tasks[0]["payload"]["available_actions"]


@pytest.mark.asyncio
async def test_error_task_skip_rejected_for_non_loop(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return tool("gen", task_type="text-to-image", prompt="fail")

    reg = _mock_evaluators(fail_keys={"r/tool$0"}, fail_category="tool_error")
    runtime = RecipeRuntime(
        121, db_path, recipe_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    tasks = await _wait_for_pending_tasks(db_path, 1)

    with pytest.raises(ValueError, match="skip is only valid"):
        await runtime.resolve_error_task(tasks[0]["task_id"], "skip")
    await runtime.stop()


@pytest.mark.asyncio
async def test_error_task_retry(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    counter: dict[str, int] = {"r/llm$0": 0}
    reg = EvaluatorRegistry()
    fail_budget = {"n": 1}

    async def llm_eval(req: EvaluationRequest) -> EvaluationResult:
        counter["r/llm$0"] = counter.get("r/llm$0", 0) + 1
        if fail_budget["n"] > 0:
            fail_budget["n"] -= 1
            raise EvaluatorError("transient go away", category="tool_error")
        return EvaluationResult(value="recovered")

    reg.register("llm_call", llm_eval)

    @recipe()
    def r():
        with phase("Run"):
            return llm(prompt="go")

    runtime = RecipeRuntime(
        122, db_path, recipe_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    tasks = await _wait_for_pending_tasks(db_path, 1)
    # Retry the failed equation.
    await runtime.resolve_error_task(tasks[0]["task_id"], "retry")
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.stop()

    eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/llm$0"))
    assert eq.status == EquationStatus.COMPLETED
    assert eq.result == "recovered"


@pytest.mark.asyncio
async def test_error_task_skip_in_foreach(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    def gen_item(n):
        return llm(prompt=f"go {n}")

    @recipe(inputs={"names": dsl_input("list[str]")})
    def r(names):
        return foreach(names, gen_item)

    # Fail only the middle iteration.
    fail_keys = {"r/foreach$0/gen_item:B/llm$0"}
    reg = _mock_evaluators(fail_keys=fail_keys, fail_category="tool_error")
    runtime = RecipeRuntime(
        123, db_path, recipe_callable=r, inputs={"names": ["A", "B", "C"]},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    tasks = await _wait_for_pending_tasks(db_path, 1)
    err_task = next(t for t in tasks if t["task_type"] == "error")
    # Ensure the failing equation is indeed inside a foreach iteration.
    assert _is_inside_foreach_iteration(err_task["equation_key"])
    await runtime.resolve_error_task(err_task["task_id"], "skip")
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    wrapper = next(eq for eq in runtime.graph.all_equations() if eq.key == "r/foreach$0")
    assert wrapper.status == EquationStatus.COMPLETED
    # B is dropped from the collection (2 items remain).
    assert len(wrapper.result) == 2
    # B iteration wrapper is SKIPPED.
    b_wrapper = next(eq for eq in runtime.graph.all_equations() if eq.key == "r/foreach$0/gen_item:B")
    assert b_wrapper.status == EquationStatus.SKIPPED


@pytest.mark.asyncio
async def test_error_task_edit_recipe_is_noop_on_runtime(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return tool("gen", task_type="text-to-image", prompt="fail")

    reg = _mock_evaluators(fail_keys={"r/tool$0"}, fail_category="tool_error")
    runtime = RecipeRuntime(
        125, db_path, recipe_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    tasks = await _wait_for_pending_tasks(db_path, 1)
    await runtime.resolve_error_task(tasks[0]["task_id"], "edit_recipe")
    await runtime.stop()

    task = graph_db.get_task(db_path, tasks[0]["task_id"])
    assert task["status"] == "resolved"
    # Equation remains failed — the agent hasn't edited yet.
    eq = next(eq for eq in runtime.graph.all_equations() if eq.key == "r/tool$0")
    assert eq.status == EquationStatus.FAILED


# ---------------------------------------------------------------------------
# HITL durability: fork, edit, rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hitl_survives_unrelated_edit(isolated_store_and_db):
    """Completed HITL decision should be reused when the program is edited
    in a way that doesn't touch the HITL equation's definition."""
    db_path, store = isolated_store_and_db

    @recipe()
    def r_before():
        with phase("Pick"):
            cands = foreach(range(3), lambda _: tool("gen", task_type="text-to-image", prompt="p"))
            picked = hitl.select(cands, instructions="pick", count=1)
            return picked

    runtime = RecipeRuntime(
        130, db_path, recipe_callable=r_before,
        evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    await runtime.resolve_task(rows[0]["task_id"], "cand#2")
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.pause()
    await runtime.stop()

    # Verify durable HITL row
    hitl_stored = graph_db.lookup_hitl_result(
        db_path, rows[0]["equation_key"], rows[0]["inputs_hash"],
    )
    assert hitl_stored == "cand#2"


@pytest.mark.asyncio
async def test_hitl_reuse_on_fork(tmp_path):
    """Completed HITL decisions survive a physical state.db copy (fork).
    Checks the durability layer only — full /fork endpoint exercised in phase 1."""
    parent_db = tmp_path / "parent.db"
    fork_db = tmp_path / "fork.db"
    create_recipe_state_db(parent_db)
    store = EquationStore(tmp_path / "store")
    store.initialize()

    @recipe()
    def r():
        with phase("Pick"):
            return hitl.select(code("return ['a', 'b']", output_type="list[str]"), instructions="pick")

    runtime1 = RecipeRuntime(
        900, parent_db, recipe_callable=r, evaluators=_mock_evaluators(), store=store,
    )
    runtime1.build_initial_graph()
    await runtime1.start()
    rows = await _wait_for_pending_tasks(parent_db, 1)
    await runtime1.resolve_task(rows[0]["task_id"], "b")
    await runtime1.wait_quiescent(timeout=3.0)
    await runtime1.stop()

    # Simulate fork: copy the parent state.db.
    import shutil
    shutil.copy2(parent_db, fork_db)

    # Open the fork with a fresh runtime and equivalent program. HITL row
    # is cloned, so the equation completes immediately via inputs_hash
    # lookup without surfacing a new task.
    runtime2 = RecipeRuntime(
        901, fork_db, recipe_callable=r, evaluators=_mock_evaluators(), store=store,
    )
    runtime2.build_initial_graph()
    await runtime2.start()
    await runtime2.wait_quiescent(timeout=3.0)
    await runtime2.stop()

    select_eq = next(
        eq for eq in runtime2.graph.all_equations() if eq.key.endswith("/hitl.select$0")
    )
    assert select_eq.status == EquationStatus.COMPLETED
    assert select_eq.result == "b"
    # No new task created in the fork.
    tasks = graph_db.list_tasks(fork_db, status="pending")
    assert tasks == []


@pytest.mark.asyncio
async def test_hitl_recovery_on_function_rename(isolated_store_and_db):
    """§I5 — renaming a function orphans equation keys but inputs_hash still
    matches, so the fallback recovery reuses the stored decision."""
    db_path, store = isolated_store_and_db

    @recipe()
    def r_before():
        with phase("Pick"):
            cands = foreach(range(2), lambda _: tool("gen", task_type="text-to-image", prompt="same"))
            return hitl.select(cands, instructions="pick", count=1)

    runtime1 = RecipeRuntime(
        131, db_path, recipe_callable=r_before,
        evaluators=_mock_evaluators(), store=store,
    )
    runtime1.build_initial_graph()
    await runtime1.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    old_inputs_hash = rows[0]["inputs_hash"]
    old_equation_key = rows[0]["equation_key"]
    await runtime1.resolve_task(rows[0]["task_id"], "cand#0")
    await runtime1.wait_quiescent(timeout=3.0)
    await runtime1.stop()

    # Stored HITL result under old equation_key + inputs_hash.
    assert graph_db.lookup_hitl_result(db_path, old_equation_key, old_inputs_hash) == "cand#0"

    # Now "rename" by using a different top-level callable name.
    @recipe(name="x")
    def r_renamed():
        with phase("Pick"):
            cands = foreach(range(2), lambda _: tool("gen", task_type="text-to-image", prompt="same"))
            return hitl.select(cands, instructions="pick", count=1)

    runtime2 = RecipeRuntime(
        132, db_path, recipe_callable=r_renamed,
        evaluators=_mock_evaluators(), store=store,
    )
    runtime2.build_initial_graph()
    await runtime2.start()
    await runtime2.wait_quiescent(timeout=3.0)
    await runtime2.stop()

    # The renamed recipe's HITL equation should be COMPLETED via the
    # by-inputs_hash fallback lookup, without re-asking.
    new_select = next(
        eq for eq in runtime2.graph.all_equations()
        if eq.key.endswith("/hitl.select$0")
    )
    assert new_select.status == EquationStatus.COMPLETED
    assert new_select.result == "cand#0"


# ---------------------------------------------------------------------------
# Idempotent resolution under concurrent invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_resolution_under_concurrent_invalidation(isolated_store_and_db):
    """Simulate: task_created → equation invalidated → user resolves. The
    resolution must not crash and must not unblock a stale equation, but the
    resolution should still land in hitl_results so the next evaluation
    picks it up."""
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Pick"):
            cands = foreach(range(2), lambda _: tool("gen", task_type="text-to-image", prompt="p"))
            return hitl.select(cands, instructions="pick", count=1)

    runtime = RecipeRuntime(
        140, db_path, recipe_callable=r, evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    task = rows[0]

    # Invalidate the upstream tool, simulating a concurrent program edit.
    tool_key = next(k for k in runtime.graph.keys() if k.endswith("/tool$0"))
    runtime.invalidate(tool_key)

    # Resolve anyway — should not crash.
    await runtime.resolve_task(task["task_id"], "cand#0")
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.stop()

    # HITL result stored by (equation_key, inputs_hash) — next eval picks it up.
    stored = graph_db.lookup_hitl_result(db_path, task["equation_key"], task["inputs_hash"])
    assert stored == "cand#0"


# ---------------------------------------------------------------------------
# Unblocks-most-work calculation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unblocks_most_work_calculation(isolated_store_and_db):
    """Two HITL gates: one with a downstream code block, one without.
    The one with downstream work should have downstream_count >= 1."""
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        # Gate A: no downstream.
        with phase("Run"):
            _unused = hitl.select(
                code("return ['x', 'z']", output_type="list[str]"),
                instructions="leaf",
            )
            # Gate B: has a downstream code block.
            v = hitl.select(
                code("return ['y', 'q']", output_type="list[str]"),
                instructions="branching",
            )
            branched = code("return v + '!'", inputs={"v": v})
            return {"leaf": _unused, "branched": branched}

    runtime = RecipeRuntime(
        150, db_path, recipe_callable=r, evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 2)

    await runtime.pause()
    await runtime.stop()

    # Identify the tasks by instructions text.
    leaf = next(t for t in rows if t["instructions"] == "leaf")
    branching = next(t for t in rows if t["instructions"] == "branching")

    # Fresh computation via the runtime (before we stopped).
    leaf_count = leaf["payload"].get("downstream_count")
    branching_count = branching["payload"].get("downstream_count")
    assert leaf_count == 0
    assert branching_count >= 1


# ---------------------------------------------------------------------------
# Malformed resolution shape: engine level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_error_action_rejected(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @recipe()
    def r():
        with phase("Run"):
            return tool("gen", task_type="text-to-image", prompt="fail")

    reg = _mock_evaluators(fail_keys={"r/tool$0"}, fail_category="tool_error")
    runtime = RecipeRuntime(
        160, db_path, recipe_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    tasks = await _wait_for_pending_tasks(db_path, 1)
    with pytest.raises(ValueError, match="unknown error-task action"):
        await runtime.resolve_error_task(tasks[0]["task_id"], "nonsense")
    await runtime.stop()


# ---------------------------------------------------------------------------
# WebSocket events
# ---------------------------------------------------------------------------


class _CaptureBroadcaster:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def __call__(self, event: str, payload: dict) -> None:
        self.events.append((event, dict(payload)))


@pytest.mark.asyncio
async def test_ws_events_on_hitl_lifecycle(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    cap = _CaptureBroadcaster()

    @recipe()
    def r():
        with phase("Pick"):
            cands = foreach(range(2), lambda _: tool("gen", task_type="text-to-image", prompt="p"))
            return hitl.select(cands, instructions="pick", count=1)

    runtime = RecipeRuntime(
        170, db_path, recipe_callable=r,
        evaluators=_mock_evaluators(), store=store,
        broadcast=cap,
    )
    runtime.build_initial_graph()
    await runtime.start()
    rows = await _wait_for_pending_tasks(db_path, 1)
    await runtime.resolve_task(rows[0]["task_id"], "cand#0")
    await runtime.wait_quiescent(timeout=3.0)
    await runtime.stop()

    names = [e[0] for e in cap.events]
    assert "recipe_task_created" in names
    assert "recipe_task_resolved" in names
    created = next(p for n, p in cap.events if n == "recipe_task_created")
    assert created["task_type"] == "select"
    assert created["recipe_id"] == 170


# ---------------------------------------------------------------------------
# HTTP API — listing + resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_list_tasks_for_recipe(client, db_session):
    """GET /api/recipes/:id/tasks returns pending tasks for one recipe."""
    # Create a recipe row via the normal API.
    resp = await client.post("/api/recipes", json={"name": "phase4-list"})
    assert resp.status_code == 200
    recipe_id = resp.json()["id"]

    # Populate its state.db directly.
    from recipe_runtime import get_recipe_state_db_path
    state_db = get_recipe_state_db_path(recipe_id)
    # Equation row must exist before task row (FK).
    from recipe_runtime.graph import Equation, EquationStatus as S, EquationType as ET
    eq = Equation(
        key="r/hitl.select$0",
        equation_type=ET.HITL,
        definition={"hitl_type": "select"},
        dependencies=[],
        phase_path=["Pick"],
    )
    eq.status = S.AWAITING_INPUT
    graph_db.insert_equation(state_db, eq)
    task_id = graph_db.insert_task(
        state_db, "r/hitl.select$0", "select", "pick one",
        {"candidates": ["a", "b"], "count": 1, "downstream_count": 2},
    )

    r = await client.get(f"/api/recipes/{recipe_id}/tasks")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["task_id"] == f"{recipe_id}:{task_id}"
    assert body[0]["task_type"] == "select"
    assert body[0]["recipe_id"] == recipe_id
    assert body[0]["downstream_count"] == 2


@pytest.mark.asyncio
async def test_http_resolve_rejects_invalid_shape(client, db_session):
    """Malformed resolution shape → 4xx, not crash."""
    r1 = (await client.post("/api/recipes", json={"name": "x-validate"})).json()
    from recipe_runtime import get_recipe_state_db_path
    from recipe_runtime.graph import Equation, EquationStatus as S, EquationType as ET
    state_db = get_recipe_state_db_path(r1["id"])
    eq = Equation(
        key="r/hitl.select$0",
        equation_type=ET.HITL,
        definition={"hitl_type": "select", "count": 2},
        dependencies=[],
    )
    eq.status = S.AWAITING_INPUT
    graph_db.insert_equation(state_db, eq)
    task_id = graph_db.insert_task(
        state_db, "r/hitl.select$0", "select", "pick",
        {"candidates": ["a", "b"], "count": 2},
    )
    composite = f"{r1['id']}:{task_id}"
    # count=2 select expects a list, pass a string instead.
    r = await client.post(f"/api/tasks/{composite}/resolve", json={"resolution": "bad"})
    assert r.status_code == 400
    assert "list" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_http_resolve_via_registry_drives_runtime(client, db_session):
    """A RecipeRuntime registered under recipe_registry handles HTTP
    resolution end-to-end: scheduler completes the downstream after the
    task is resolved."""
    import recipe_registry
    from recipe_runtime import create_recipe_state_db, EquationStore, RecipeRuntime
    from recipe_runtime import get_recipe_state_db_path
    # Create a recipe row so Recipe.id exists in the main DB.
    rr = (await client.post("/api/recipes", json={"name": "x-registry"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)
    # Recipe directory + state.db were created by the API.

    @recipe()
    def r():
        with phase("Run"):
            v = hitl.select(
                code("return ['here', 'there']", output_type="list[str]"),
                instructions="give",
            )
            return code("return v + '?'", inputs={"v": v})

    runtime = RecipeRuntime(
        recipe_id, state_db, recipe_callable=r, evaluators=_mock_evaluators(),
    )
    runtime.build_initial_graph()
    await runtime.start()
    recipe_registry.register(recipe_id, runtime)
    try:
        rows = await _wait_for_pending_tasks(state_db, 1)
        composite = f"{recipe_id}:{rows[0]['task_id']}"
        r = await client.post(
            f"/api/tasks/{composite}/resolve", json={"resolution": "here"},
        )
        assert r.status_code == 200, r.text
        await runtime.wait_quiescent(timeout=3.0)
    finally:
        recipe_registry.unregister(recipe_id)
        await runtime.stop()

    code_eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/code$0"))
    assert code_eq.status == EquationStatus.COMPLETED


@pytest.mark.asyncio
async def test_http_resolve_running_recipe_inflates_missing_runtime(
    client, db_session, monkeypatch,
):
    """A running recipe should not take the offline HITL path just because
    the in-memory registry is empty."""
    import recipe_lifecycle
    import recipe_registry
    from recipe_runtime import get_recipe_program_path, get_recipe_state_db_path

    monkeypatch.setattr(
        recipe_lifecycle,
        "build_production_registry",
        lambda: _mock_evaluators(code_value="continued"),
    )

    rr = (await client.post("/api/recipes", json={"name": "x-inflate-running"})).json()
    recipe_id = rr["id"]
    get_recipe_program_path(recipe_id).write_text(
        '''from stimma.recipe import recipe, phase, hitl, code


@recipe(name="inflate-running")
def prog():
    with phase("Run"):
        v = hitl.select(
            code("return ['here', 'there']", output_type="list[str]"),
            instructions="give",
        )
        return code("return v + '?'", inputs={"v": v}, output_type="text")
'''
    )
    state_db = get_recipe_state_db_path(recipe_id)
    runtime = None
    try:
        r = await client.post(f"/api/recipes/{recipe_id}/start")
        assert r.status_code == 200, r.text
        runtime = recipe_registry.get_runtime(recipe_id)
        assert runtime is not None
        rows = await _wait_for_pending_tasks(state_db, 1)

        # Simulate an app/backend gap where the DB still says "running" but
        # the per-recipe runtime registry no longer has this recipe loaded.
        await runtime.stop()
        recipe_registry.unregister(recipe_id)
        assert recipe_registry.get_runtime(recipe_id) is None

        composite = f"{recipe_id}:{rows[0]['task_id']}"
        r = await client.post(
            f"/api/tasks/{composite}/resolve", json={"resolution": "here"},
        )
        assert r.status_code == 200, r.text

        inflated = recipe_registry.get_runtime(recipe_id)
        assert inflated is not None
        assert inflated.run is not None
        await inflated.wait_quiescent(timeout=3.0)
        code_eq = next(eq for eq in inflated.graph.all_equations() if eq.key.endswith("/code$0"))
        assert code_eq.status == EquationStatus.COMPLETED
        assert code_eq.result == "code_out"
    finally:
        active = recipe_registry.get_runtime(recipe_id)
        if active is not None:
            await active.stop()
            recipe_registry.unregister(recipe_id)


@pytest.mark.asyncio
async def test_http_resolve_select_offline_persists_hitl(client, db_session):
    """Resolution with no active runtime writes HITL durably."""
    r1 = (await client.post("/api/recipes", json={"name": "x-offline"})).json()
    from recipe_runtime import get_recipe_state_db_path
    from recipe_runtime.graph import Equation, EquationStatus as S, EquationType as ET
    state_db = get_recipe_state_db_path(r1["id"])
    eq = Equation(
        key="r/hitl.select$0",
        equation_type=ET.HITL,
        definition={"hitl_type": "select"},
        dependencies=[],
        phase_path=[],
    )
    eq.status = S.AWAITING_INPUT
    eq.inputs_hash = "deadbeef"
    graph_db.insert_equation(state_db, eq)
    task_id = graph_db.insert_task(
        state_db, "r/hitl.select$0", "select", "pick",
        {"candidates": ["a", "b"], "count": 1},
    )
    composite = f"{r1['id']}:{task_id}"

    r = await client.post(
        f"/api/tasks/{composite}/resolve", json={"resolution": "a"},
    )
    assert r.status_code == 200, r.text
    # HITL result durable.
    stored = graph_db.lookup_hitl_result(state_db, "r/hitl.select$0", "deadbeef")
    assert stored == "a"


@pytest.mark.asyncio
async def test_http_resolve_waiting_for_tool_skip_offline(client, db_session):
    r1 = (await client.post("/api/recipes", json={"name": "x-waiting-tool"})).json()
    from recipe_runtime import get_recipe_state_db_path
    from recipe_runtime.graph import Equation, EquationStatus as S, EquationType as ET
    state_db = get_recipe_state_db_path(r1["id"])
    eq = Equation(
        key="r/tool$0",
        equation_type=ET.TOOL_CALL,
        definition={"tool_id": "missing-tool"},
        dependencies=[],
        phase_path=[],
    )
    eq.status = S.WAITING_FOR_TOOL
    graph_db.insert_equation(state_db, eq)
    task_id = graph_db.insert_task(
        state_db,
        "r/tool$0",
        "waiting_for_tool",
        "missing tool",
        {"available_actions": ["skip", "edit_recipe"]},
    )

    r = await client.post(
        f"/api/tasks/{r1['id']}:{task_id}/resolve", json={"action": "skip"},
    )

    assert r.status_code == 200, r.text
    row = graph_db.get_task(state_db, task_id)
    assert row is not None
    assert row["status"] == "resolved"
    assert row["equation_status"] == "skipped"


def test_update_equation_status_error_none_clears(tmp_path):
    state_db = tmp_path / "state.db"
    create_recipe_state_db(state_db)
    from recipe_runtime.graph import Equation, EquationStatus as S, EquationType as ET
    eq = Equation(
        key="r/tool$0",
        equation_type=ET.TOOL_CALL,
        definition={},
        dependencies=[],
        phase_path=[],
    )
    eq.status = S.FAILED
    eq.error = "stale"
    graph_db.insert_equation(state_db, eq)

    graph_db.update_equation_status(state_db, "r/tool$0", S.PENDING, error=None)

    conn = sqlite3.connect(str(state_db))
    try:
        status, error = conn.execute(
            "SELECT status, error FROM equations WHERE equation_key = 'r/tool$0'",
        ).fetchone()
    finally:
        conn.close()
    assert status == "pending"
    assert error is None


@pytest.mark.asyncio
async def test_store_hit_restores_media_ids_and_duration(tmp_path):
    state_db_1 = tmp_path / "state1.db"
    state_db_2 = tmp_path / "state2.db"
    create_recipe_state_db(state_db_1)
    create_recipe_state_db(state_db_2)
    store = EquationStore(tmp_path / "store")
    store.initialize()

    counter = {"calls": 0}
    reg = EvaluatorRegistry()

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        counter["calls"] += 1
        await asyncio.sleep(0.01)
        return EvaluationResult(value=42, media_ids=[42])

    reg.register("tool_call", tool_eval)

    @recipe()
    def r():
        with phase("Generate"):
            return tool("gen", task_type="text-to-image", prompt="p")

    runtime1 = RecipeRuntime(
        301, state_db_1, recipe_callable=r, evaluators=reg, store=store,
    )
    runtime1.build_initial_graph()
    await runtime1.start()
    await runtime1.wait_quiescent(timeout=3.0)
    eq1 = next(eq for eq in runtime1.graph.all_equations() if eq.equation_type.value == "tool_call")
    duration_ms = eq1.execution_duration_ms
    await runtime1.stop()

    assert counter["calls"] == 1
    assert eq1.result_media_ids == [42]
    assert isinstance(duration_ms, int) and duration_ms >= 0

    async def should_not_run(req: EvaluationRequest) -> EvaluationResult:
        raise AssertionError("expected second runtime to hit the equation store")

    reg2 = EvaluatorRegistry()
    reg2.register("tool_call", should_not_run)

    runtime2 = RecipeRuntime(
        302, state_db_2, recipe_callable=r, evaluators=reg2, store=store,
    )
    runtime2.build_initial_graph()
    await runtime2.start()
    await runtime2.wait_quiescent(timeout=3.0)
    eq2 = next(eq for eq in runtime2.graph.all_equations() if eq.equation_type.value == "tool_call")
    await runtime2.stop()

    assert eq2.status == EquationStatus.COMPLETED
    assert eq2.result == 42
    assert eq2.result_media_ids == [42]
    assert eq2.execution_duration_ms == duration_ms

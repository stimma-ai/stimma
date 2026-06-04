"""Phase 5 gap tests — execution control, phase tree, equations, invalidation.

These endpoints wrap RecipeRuntime for the frontend. Phase 4 shipped the
HITL + task API but left these missing, which blocked Phase 5. Tests here
cover the HTTP surface; the underlying runtime behavior is exercised in
test_recipes_phase2/3/4.

Scope: the API contract. Happy-path start/pause/resume, phase-tree shape
from a populated state.db, equation listing + filtering, and invalidation
semantics (attempt bump + cascade) via the HTTP layer.
"""

from __future__ import annotations

import re

import pytest

import recipe_registry
from recipe_runtime import (
    EquationStore,
    EvaluatorRegistry,
    RecipeRuntime,
    create_recipe_state_db,
    get_recipe_program_path,
    get_recipe_state_db_path,
    graph_db,
    is_empty_recipe_program,
)
from recipe_runtime.dsl import code, foreach, hitl, input as dsl_input, phase, recipe, tool
from recipe_runtime.evaluators import EvaluationRequest, EvaluationResult
from recipe_runtime.graph import Equation, EquationStatus, EquationType


_MINIMAL_PROGRAM = '''"""Minimal test recipe — one tool call."""
from stimma.recipe import phase, recipe, tool


@recipe(name="p5-min")
def prog():
    with phase("Generate"):
        return tool("noop", task_type="text-to-image", prompt="p")
'''


def _seed_program(recipe_id: int, source: str = _MINIMAL_PROGRAM) -> None:
    """Overwrite program.py for a recipe with a valid DSL program.

    New recipes ship with an empty placeholder that fails graph-build; tests
    that call /start need something loadable.
    """
    get_recipe_program_path(recipe_id).write_text(source)


# ---------------------------------------------------------------------------
# Helpers — small mock evaluator registry, matches the phase4 pattern
# ---------------------------------------------------------------------------


def _mock_evaluators() -> EvaluatorRegistry:
    reg = EvaluatorRegistry()

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        match = re.search(r":(\d+)/tool\$", req.equation_key)
        if match:
            return EvaluationResult(value=f"c{match.group(1)}")
        return EvaluationResult(value="asset")

    async def code_eval(req: EvaluationRequest) -> EvaluationResult:
        source = req.definition.get("source", "")
        if "'seed'" in source:
            return EvaluationResult(value=["c0", "c1"])
        return EvaluationResult(value="code_out")

    reg.register("tool_call", tool_eval)
    reg.register("code", code_eval)
    return reg


# ---------------------------------------------------------------------------
# Execution control — start/pause/resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_transitions_execution_state_and_runtime(client, db_session):
    """POST /start sets execution_state=running and spins up a runtime."""
    rr = (await client.post("/api/recipes", json={"name": "p5-start"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    try:
        r = await client.post(f"/api/recipes/{recipe_id}/start")
        assert r.status_code == 200, r.text
        assert r.json()["execution_state"] == "running"
        # Registry has the runtime now.
        assert recipe_registry.get_runtime(recipe_id) is not None
    finally:
        runtime = recipe_registry.get_runtime(recipe_id)
        if runtime is not None:
            await runtime.stop()
            recipe_registry.unregister(recipe_id)


@pytest.mark.asyncio
async def test_pause_and_resume_roundtrip(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-pr"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    try:
        assert (await client.post(f"/api/recipes/{recipe_id}/start")).status_code == 200
        p = await client.post(f"/api/recipes/{recipe_id}/pause")
        assert p.status_code == 200
        assert p.json()["execution_state"] == "paused"

        rz = await client.post(f"/api/recipes/{recipe_id}/resume")
        assert rz.status_code == 200
        assert rz.json()["execution_state"] == "running"
    finally:
        runtime = recipe_registry.get_runtime(recipe_id)
        if runtime is not None:
            await runtime.stop()
            recipe_registry.unregister(recipe_id)


@pytest.mark.asyncio
async def test_start_idempotent(client, db_session):
    """Hitting /start twice is a no-op, not an error."""
    rr = (await client.post("/api/recipes", json={"name": "p5-idem"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    try:
        assert (await client.post(f"/api/recipes/{recipe_id}/start")).status_code == 200
        assert (await client.post(f"/api/recipes/{recipe_id}/start")).status_code == 200
        assert recipe_registry.get_runtime(recipe_id) is not None
    finally:
        runtime = recipe_registry.get_runtime(recipe_id)
        if runtime is not None:
            await runtime.stop()
            recipe_registry.unregister(recipe_id)


@pytest.mark.asyncio
async def test_start_on_missing_recipe_404(client, db_session):
    r = await client.post("/api/recipes/999999/start")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_start_on_empty_program_400(client, db_session):
    """A recipe whose program.py has no @recipe can't start."""
    rr = (await client.post("/api/recipes", json={"name": "p5-empty"})).json()
    r = await client.post(f"/api/recipes/{rr['id']}/start")
    assert r.status_code == 400
    assert "program" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_phase_tree_for_new_recipe_has_no_program_load_error(client, db_session):
    """A fresh recipe's placeholder program is an expected empty state."""
    rr = (await client.post("/api/recipes", json={"name": "p5-new"})).json()
    r = await client.get(f"/api/recipes/{rr['id']}/phases")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["load_error"] is None
    assert body["root"]["equation_keys"] == []
    assert body["root"]["children"] == []


@pytest.mark.asyncio
async def test_reparse_builds_graph_without_start(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-reparse"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    try:
        r = await client.post(f"/api/recipes/{recipe_id}/reparse")
        assert r.status_code == 200, r.text
        eqs = await client.get(f"/api/recipes/{recipe_id}/equations")
        assert eqs.status_code == 200, eqs.text
        assert len(eqs.json()) == 1
    finally:
        runtime = recipe_registry.get_runtime(recipe_id)
        if runtime is not None:
            await runtime.stop()
            recipe_registry.unregister(recipe_id)


@pytest.mark.asyncio
async def test_clear_recipe_resets_program_runtime_and_state(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-clear"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    try:
        started = await client.post(f"/api/recipes/{recipe_id}/start")
        assert started.status_code == 200, started.text
        cleared = await client.post(f"/api/recipes/{recipe_id}/clear")
        assert cleared.status_code == 200, cleared.text
        body = cleared.json()
        assert body["execution_state"] == "idle"
        assert body["input_schema"] is None
        assert recipe_registry.get_runtime(recipe_id) is None
        assert is_empty_recipe_program(get_recipe_program_path(recipe_id).read_text())
        eqs = await client.get(f"/api/recipes/{recipe_id}/equations")
        assert eqs.status_code == 200, eqs.text
        assert eqs.json() == []
    finally:
        runtime = recipe_registry.get_runtime(recipe_id)
        if runtime is not None:
            await runtime.stop()
            recipe_registry.unregister(recipe_id)


# ---------------------------------------------------------------------------
# Phase tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_tree_from_state_db(client, db_session):
    """GET /phases builds a recursive tree from equation phase_paths.

    Populates state.db directly with equations in two phases and verifies
    the tree rolls up status counts.
    """
    rr = (await client.post("/api/recipes", json={"name": "p5-phases"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)

    # Three equations: two in ["Research"], one in ["Generate", "Illustrations"].
    for i, (key, phase, status) in enumerate([
        ("r/research$0", ["Research"], EquationStatus.COMPLETED),
        ("r/research$1", ["Research"], EquationStatus.PENDING),
        ("r/gen$0", ["Generate", "Illustrations"], EquationStatus.COMPUTING),
    ]):
        eq = Equation(
            key=key,
            equation_type=EquationType.TOOL_CALL,
            definition={"tool": "x"},
            dependencies=[],
            phase_path=phase,
        )
        eq.status = status
        graph_db.insert_equation(state_db, eq)

    r = await client.get(f"/api/recipes/{recipe_id}/phases")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipe_id"] == recipe_id
    assert body["execution_state"] == "idle"
    root = body["root"]
    # Root is implicit "" — two children: "Research", "Generate".
    child_names = {c["name"] for c in root["children"]}
    assert child_names == {"Research", "Generate"}
    research = next(c for c in root["children"] if c["name"] == "Research")
    assert research["status_summary"] == {"completed": 1, "pending": 1}
    generate = next(c for c in root["children"] if c["name"] == "Generate")
    # Generate has one child: Illustrations.
    assert len(generate["children"]) == 1
    illustrations = generate["children"][0]
    assert illustrations["name"] == "Illustrations"
    assert illustrations["status_summary"] == {"computing": 1}
    # Root rolls up everything.
    assert root["status_summary"] == {
        "completed": 1, "pending": 1, "computing": 1,
    }


@pytest.mark.asyncio
async def test_phase_tree_sorts_sibling_phases_by_dependency(client, db_session):
    """Sibling phases should render in dependency order, including hidden wrappers."""
    rr = (await client.post("/api/recipes", json={"name": "p5-phase-order"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)

    generate_poses = Equation(
        key="r/generate_poses$0",
        equation_type=EquationType.TOOL_CALL,
        definition={"tool": "x"},
        dependencies=["r/generate_model_options/foreach$0"],
        phase_path=["Generate poses"],
    )
    generate_poses.status = EquationStatus.COMPLETED
    graph_db.insert_equation(state_db, generate_poses)

    gather_model_options = Equation(
        key="r/generate_model_options/foreach$0",
        equation_type=EquationType.CONTROL,
        definition={"control_kind": "foreach"},
        dependencies=["r/generate_model_options$0"],
        phase_path=["Generate model options"],
    )
    gather_model_options.status = EquationStatus.COMPLETED
    graph_db.insert_equation(state_db, gather_model_options)

    generate_model_options = Equation(
        key="r/generate_model_options$0",
        equation_type=EquationType.TOOL_CALL,
        definition={"tool": "x"},
        dependencies=[],
        phase_path=["Generate model options"],
    )
    generate_model_options.status = EquationStatus.COMPLETED
    graph_db.insert_equation(state_db, generate_model_options)

    r = await client.get(f"/api/recipes/{recipe_id}/phases")
    assert r.status_code == 200, r.text
    body = r.json()
    root_children = body["root"]["children"]
    assert [child["name"] for child in root_children] == [
        "Generate model options",
        "Generate poses",
    ]


@pytest.mark.asyncio
async def test_list_equations_labels_foreach_as_loop(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-foreach-label"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)

    wrapper = Equation(
        key="r/generate/foreach$0",
        equation_type=EquationType.CONTROL,
        definition={"control_kind": "foreach"},
        dependencies=[],
        phase_path=["Generate"],
    )
    wrapper.status = EquationStatus.COMPLETED
    graph_db.insert_equation(state_db, wrapper)

    r = await client.get(f"/api/recipes/{recipe_id}/equations")
    assert r.status_code == 200, r.text
    rows = r.json()
    foreach_row = next(row for row in rows if row["equation_key"] == "r/generate/foreach$0")
    assert foreach_row["display_name"] == "Loop"


@pytest.mark.asyncio
async def test_phase_tree_counts_pending_tasks(client, db_session):
    """pending_task_count rolls up per node."""
    rr = (await client.post("/api/recipes", json={"name": "p5-phases-tasks"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)

    eq = Equation(
        key="r/hitl$0",
        equation_type=EquationType.HITL,
        definition={"hitl_type": "select"},
        dependencies=[],
        phase_path=["Pick"],
    )
    eq.status = EquationStatus.AWAITING_INPUT
    graph_db.insert_equation(state_db, eq)
    graph_db.insert_task(
        state_db, "r/hitl$0", "select", "pick",
        {"candidates": ["a", "b"], "count": 1},
    )

    r = await client.get(f"/api/recipes/{recipe_id}/phases")
    body = r.json()
    pick = next(c for c in body["root"]["children"] if c["name"] == "Pick")
    assert pick["pending_task_count"] == 1
    assert body["root"]["pending_task_count"] == 1


# ---------------------------------------------------------------------------
# Equations listing + detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_equations_filters_by_status(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-eq"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)
    for key, status in [
        ("a", EquationStatus.COMPLETED),
        ("b", EquationStatus.PENDING),
        ("c", EquationStatus.COMPLETED),
    ]:
        eq = Equation(
            key=key,
            equation_type=EquationType.TOOL_CALL,
            definition={},
            dependencies=[],
        )
        eq.status = status
        graph_db.insert_equation(state_db, eq)

    r = await client.get(
        f"/api/recipes/{recipe_id}/equations", params={"status": "completed"},
    )
    assert r.status_code == 200
    keys = {row["equation_key"] for row in r.json()}
    assert keys == {"a", "c"}


@pytest.mark.asyncio
async def test_get_equation_detail_404_on_unknown(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-eq-detail"})).json()
    recipe_id = rr["id"]
    r = await client.get(f"/api/recipes/{recipe_id}/equations/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_equation_detail_ok(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-eq-ok"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)
    eq = Equation(
        key="r/tool$0",
        equation_type=EquationType.TOOL_CALL,
        definition={"tool": "x"},
        dependencies=[],
        phase_path=["X"],
    )
    eq.status = EquationStatus.COMPLETED
    graph_db.insert_equation(state_db, eq)

    r = await client.get(f"/api/recipes/{recipe_id}/equations/r/tool$0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["equation_key"] == "r/tool$0"
    assert body["status"] == "completed"
    assert body["phase_path"] == ["X"]


@pytest.mark.asyncio
async def test_get_equation_trace_falls_back_to_serialized_definition(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-trace-serialized"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)
    eq = Equation(
        key="r/llm$0",
        equation_type=EquationType.LLM_CALL,
        definition={
            "prompt_template": "Analyze {product}",
            "system_template": "You are concise.",
            "model": "agent",
        },
        dependencies=[],
    )
    eq.status = EquationStatus.COMPLETED
    eq.result = {"summary": "ok"}
    graph_db.insert_equation(state_db, eq)

    r = await client.get(f"/api/recipes/{recipe_id}/equations/r/llm$0/trace")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detail_availability"] == "serialized"
    assert body["prompt"] == "Analyze {product}"
    assert body["system"] == "You are concise."
    assert body["result"] == {"summary": "ok"}


@pytest.mark.asyncio
async def test_get_equation_trace_inflates_runtime_for_live_rendering(client, db_session):
    rr = (
        await client.post(
            "/api/recipes",
            json={"name": "p5-trace-inflate"},
        )
    ).json()
    recipe_id = rr["id"]
    _seed_program(
        recipe_id,
        '''from stimma.recipe import recipe, phase, code


@recipe(name="trace")
def prog():
    with phase("Trace"):
        product = code("return 'camera'", inputs={}, output_type="text")
        return code("return product.upper()", inputs={"product": product}, output_type="text")
''',
    )
    runtime = None
    try:
        started = await client.post(f"/api/recipes/{recipe_id}/start")
        assert started.status_code == 200, started.text
        runtime = recipe_registry.get_runtime(recipe_id)
        assert runtime is not None
        await runtime.wait_quiescent(timeout=3.0)
        await runtime.stop()
        recipe_registry.unregister(recipe_id)

        assert recipe_registry.get_runtime(recipe_id) is None
        r = await client.get(f"/api/recipes/{recipe_id}/equations/prog/code$1/trace")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["detail_availability"] == "live"
        assert body["inputs"] == {"product": "camera"}
        assert recipe_registry.get_runtime(recipe_id) is not None
    finally:
        runtime = recipe_registry.get_runtime(recipe_id)
        if runtime is not None:
            await runtime.stop()
            recipe_registry.unregister(recipe_id)


@pytest.mark.asyncio
async def test_get_hitl_trace_uses_serialized_task_payload_when_runtime_inactive(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-hitl-trace"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)
    eq = Equation(
        key="r/hitl$0",
        equation_type=EquationType.HITL,
        definition={
            "hitl_type": "select",
            "instructions": "Pick one",
            "count": 1,
        },
        dependencies=[],
    )
    eq.status = EquationStatus.COMPLETED
    eq.result = 42
    graph_db.insert_equation(state_db, eq)
    graph_db.insert_task(
        state_db,
        "r/hitl$0",
        "select",
        "Pick one",
        {"candidates": [42, 99], "count": 1},
    )

    r = await client.get(f"/api/recipes/{recipe_id}/equations/r/hitl$0/trace")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["detail_availability"] == "serialized"
    assert body["candidates"] == [42, 99]
    assert body["count"] == 1
    assert body["result"] == 42


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_equation_requires_running_runtime(client, db_session):
    """Without an active runtime (no /start), invalidate returns 409."""
    rr = (await client.post("/api/recipes", json={"name": "p5-inv-409"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    r = await client.post(
        f"/api/recipes/{recipe_id}/equations/some-key/invalidate"
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_invalidate_equation_bumps_attempt_and_cascades(
    client, db_session, tmp_path,
):
    """A registered runtime with a completed graph: invalidate bumps attempt
    and resets the target + downstream."""
    rr = (await client.post("/api/recipes", json={"name": "p5-inv"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)

    @recipe()
    def prog():
        with phase("Generate"):
            a = tool("gen", task_type="text-to-image", prompt="p")
        with phase("Finish"):
            return code("return a + '!'", inputs={"a": a})

    store = EquationStore(tmp_path / "store")
    store.initialize()
    runtime = RecipeRuntime(
        recipe_id, state_db,
        recipe_callable=prog, evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    recipe_registry.register(recipe_id, runtime)
    try:
        await runtime.wait_quiescent(timeout=3.0)
        # Both equations completed.
        tool_key = next(k for k in runtime.graph.keys() if "tool$0" in k)
        code_key = next(k for k in runtime.graph.keys() if "code$0" in k)
        assert runtime.graph.get(tool_key).status == EquationStatus.COMPLETED
        assert runtime.graph.get(code_key).status == EquationStatus.COMPLETED
        tool_attempt_before = runtime.graph.get(tool_key).attempt

        # Invalidate the tool equation.
        r = await client.post(
            f"/api/recipes/{recipe_id}/equations/{tool_key}/invalidate"
        )
        assert r.status_code == 200, r.text
        # Direct target attempt bumped.
        assert runtime.graph.get(tool_key).attempt == tool_attempt_before + 1
        # Downstream code eq is pending (scheduler hasn't rerun yet) or
        # will have re-run by now — either way it's not COMPLETED with the
        # same attempt. Wait for quiescence and assert re-ran.
        await runtime.wait_quiescent(timeout=3.0)
        assert runtime.graph.get(code_key).status == EquationStatus.COMPLETED
    finally:
        recipe_registry.unregister(recipe_id)
        await runtime.stop()


@pytest.mark.asyncio
async def test_invalidate_dynamic_foreach_descendants_reset_to_pending(tmp_path):
    """Invalidating inside a dynamic foreach must reset wrapper descendants too."""
    recipe_id = 999001
    state_db = get_recipe_state_db_path(recipe_id)
    state_db.parent.mkdir(parents=True, exist_ok=True)
    create_recipe_state_db(state_db)

    @recipe()
    def prog():
        with phase("Generate"):
            seeds = code(
                "return ['seed', 'seed']", inputs={}, output_type="list[str]",
            )
            generated = foreach(seeds, lambda item: tool("gen", task_type="text-to-image", prompt=item))
        with phase("Finish"):
            return code("return generated", inputs={"generated": generated})

    store = EquationStore(tmp_path / "store-dynamic-invalidate")
    store.initialize()
    runtime = RecipeRuntime(
        recipe_id,
        state_db,
        recipe_callable=prog,
        evaluators=_mock_evaluators(),
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=3.0)
        await runtime.pause()

        inner_tool_key = next(
            k for k in runtime.graph.keys()
            if k.count("/") >= 2 and k.endswith("/tool$0")
        )
        iteration_wrapper_key = inner_tool_key.rsplit("/", 1)[0]
        foreach_wrapper_key = next(
            k for k in runtime.graph.keys() if k.endswith("/foreach$0")
        )
        code_key = next(
            k for k in runtime.graph.keys()
            if k.endswith("/code$1") and not k.startswith(f"{foreach_wrapper_key}/")
        )

        reset = runtime.invalidate(inner_tool_key)
        assert reset >= 4
        assert runtime.graph.get(inner_tool_key).status == EquationStatus.PENDING
        assert runtime.graph.get(iteration_wrapper_key).status == EquationStatus.PENDING
        assert runtime.graph.get(foreach_wrapper_key).status == EquationStatus.PENDING
        assert runtime.graph.get(code_key).status == EquationStatus.PENDING
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_invalidate_populated_recipe_input_recompletes_while_paused(tmp_path):
    """A provided recipe input should not stay pending after invalidation."""
    recipe_id = 999002
    state_db = get_recipe_state_db_path(recipe_id)
    state_db.parent.mkdir(parents=True, exist_ok=True)
    create_recipe_state_db(state_db)

    @recipe(inputs={"n": dsl_input("str")})
    def prog(n):
        with phase("Generate"):
            return code("return n", inputs={"n": n})

    store = EquationStore(tmp_path / "store-input-invalidate")
    store.initialize()
    runtime = RecipeRuntime(
        recipe_id,
        state_db,
        recipe_callable=prog,
        inputs={"n": "alice"},
        evaluators=_mock_evaluators(),
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=3.0)
        await runtime.pause()

        input_key = next(
            k for k in runtime.graph.keys() if "recipe_input" in k
        )

        runtime.invalidate(input_key)

        input_eq = runtime.graph.get(input_key)
        assert input_eq.status == EquationStatus.COMPLETED
        assert input_eq.result == "alice"
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_invalidate_phase_matches_by_prefix(client, db_session, tmp_path):
    """POST /phases/invalidate resets every equation whose phase_path matches."""
    rr = (await client.post("/api/recipes", json={"name": "p5-phinv"})).json()
    recipe_id = rr["id"]
    state_db = get_recipe_state_db_path(recipe_id)

    @recipe()
    def prog():
        from recipe_runtime.dsl import phase
        with phase("A"):
            a = tool("gen", task_type="text-to-image", prompt="x")
        with phase("B"):
            b = tool("gen", task_type="text-to-image", prompt="y")
        with phase("Combine"):
            return code("return a + b", inputs={"a": a, "b": b})

    store = EquationStore(tmp_path / "store")
    store.initialize()
    runtime = RecipeRuntime(
        recipe_id, state_db,
        recipe_callable=prog, evaluators=_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    recipe_registry.register(recipe_id, runtime)
    try:
        await runtime.wait_quiescent(timeout=3.0)
        # Invalidate only phase A.
        r = await client.post(
            f"/api/recipes/{recipe_id}/phases/invalidate",
            json={"phase_path": ["A"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["matched"] >= 1
        assert body["reset"] >= 1
        # Phase B's equation wasn't matched.
        b_key = next(
            k for k in runtime.graph.keys()
            if runtime.graph.get(k).phase_path == ["B"]
        )
        # B completed and still completed (or re-running if downstream
        # of A — since B isn't, it stays completed).
        assert runtime.graph.get(b_key).status == EquationStatus.COMPLETED
    finally:
        recipe_registry.unregister(recipe_id)
        await runtime.stop()


# ---------------------------------------------------------------------------
# Recipe deletion stops the scheduler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_recipe_stops_runtime(client, db_session):
    rr = (await client.post("/api/recipes", json={"name": "p5-delete"})).json()
    recipe_id = rr["id"]
    _seed_program(recipe_id)
    assert (await client.post(f"/api/recipes/{recipe_id}/start")).status_code == 200
    assert recipe_registry.get_runtime(recipe_id) is not None
    r = await client.delete(f"/api/recipes/{recipe_id}")
    assert r.status_code == 200
    assert recipe_registry.get_runtime(recipe_id) is None

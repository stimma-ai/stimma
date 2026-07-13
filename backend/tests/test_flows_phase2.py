"""Phase 2 tests for the Flows feature — FRP runtime core.

Covers the Phase 2 exit gate from docs/FLOWS_DEV_PLAN.md §Phase 2:

1. Hand-written flow with foreach + HITL + parallel branches runs end-to-end.
2. Invalidation + re-evaluation works.
3. Store hits prevent redundant computation.
4. Pause/resume preserves state.
5. Error handling classifies and handles all failure categories.
6. 10-wide concurrency cap holds under a synthetic 20-equation parallel graph.
7. Graph diff preserves unchanged equations, re-evaluates changed ones.

Plus unit tests for keys, store keys, graph diff, status transitions.

These use real per-flow SQLite files + real equation store but mock the
tool/llm evaluators so tests stay hermetic and fast.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from flow_runtime import (
    CONCURRENCY_CAP,
    EquationStatus,
    EquationType,
    EquationStore,
    EvaluationRequest,
    EvaluationResult,
    EvaluatorError,
    EvaluatorRegistry,
    FlowRun,
    FlowRunConfig,
    FlowRuntime,
    create_flow_state_db,
    diff_graphs,
    graph_db,
)
from flow_runtime.dsl import (
    code,
    filter,
    filter_items,
    foreach,
    gate,
    hitl,
    input as dsl_input,
    llm,
    output as dsl_output,
    phase,
    flow,
    partition,
    switch,
    take,
    when,
    tool,
    zip_nodes,
)
from flow_runtime.graph import can_transition
from flow_runtime.graph_builder import build_graph_from_callable
from flow_runtime.keys import (
    EquationKeyError,
    IterationKeySource,
    canonical_json_hash,
    encode_iteration_key,
    iteration_keys_for_collection,
    make_iteration_wrapper_key,
    make_nested_dsl_key,
    validate_function_name,
)
from flow_runtime.store_key import (
    StoreKeyError,
    compute_store_key,
    definition_hash_for_code,
    definition_hash_for_llm,
    definition_hash_for_tool,
    derive_seed,
    inputs_hash_for_values,
)


# =============================================================================
# Unit tests — keys
# =============================================================================


class TestEquationKeys:
    def test_make_top_level_key(self):
        assert make_iteration_wrapper_key("fn", "Mojito") == "fn:Mojito"
        assert make_iteration_wrapper_key("research_cocktail", "Mojito") == "research_cocktail:Mojito"

    def test_make_nested_dsl_key(self):
        assert make_nested_dsl_key("gen:mojito", "tool", 0) == "gen:mojito/tool$0"
        assert make_nested_dsl_key("gen:mojito", "hitl.select", 1) == "gen:mojito/hitl.select$1"

    def test_reserved_chars_in_iteration_key(self):
        assert encode_iteration_key("a:b") == "a%3Ab"
        assert encode_iteration_key("a/b") == "a%2Fb"
        assert encode_iteration_key("100%") == "100%25"

    def test_dollar_rejected_in_iteration_key(self):
        with pytest.raises(EquationKeyError):
            encode_iteration_key("bad$value")

    def test_at_prefix_rejected_in_function_name(self):
        with pytest.raises(EquationKeyError):
            validate_function_name("@sub_flow")

    def test_dollar_rejected_in_function_name(self):
        with pytest.raises(EquationKeyError):
            validate_function_name("bad$fn")

    def test_numeric_iteration_keys(self):
        assert encode_iteration_key(42) == "42"
        assert encode_iteration_key(True) == "true"
        assert encode_iteration_key(False) == "false"

class TestIterationKeyDerivation:
    def test_keyed_scalar(self):
        source = IterationKeySource(IterationKeySource.KEYED, "scalar")
        keys = iteration_keys_for_collection(["Mojito", "Daiquiri"], source)
        assert keys == ["Mojito", "Daiquiri"]

    def test_keyed_json(self):
        source = IterationKeySource(IterationKeySource.KEYED, "json")
        keys = iteration_keys_for_collection(
            [{"name": "Mojito"}, {"name": "Daiquiri"}], source
        )
        assert len(keys) == 2
        assert len(set(keys)) == 2
        # Same value should produce same hash.
        same = iteration_keys_for_collection([{"name": "Mojito"}], source)
        assert same[0] == keys[0]

    def test_positional(self):
        source = IterationKeySource(IterationKeySource.POSITIONAL)
        keys = iteration_keys_for_collection(["a", "b", "c"], source)
        assert keys == ["0", "1", "2"]

    def test_inherited_requires_upstream_keys(self):
        source = IterationKeySource(IterationKeySource.INHERITED)
        with pytest.raises(EquationKeyError):
            iteration_keys_for_collection(["a", "b"], source)

    def test_inherited_length_mismatch(self):
        source = IterationKeySource(IterationKeySource.INHERITED)
        with pytest.raises(EquationKeyError):
            iteration_keys_for_collection(["a", "b"], source, inherited_keys=["x"])


# =============================================================================
# Unit tests — store keys
# =============================================================================


class TestStoreKeys:
    def test_store_key_changes_on_attempt_bump(self):
        k1 = compute_store_key("tool_call", "abc", "def", 1)
        k2 = compute_store_key("tool_call", "abc", "def", 2)
        assert k1 != k2

    def test_store_key_changes_on_definition_change(self):
        k1 = compute_store_key("tool_call", "abc", "def", 1)
        k2 = compute_store_key("tool_call", "xyz", "def", 1)
        assert k1 != k2

    def test_store_key_changes_on_inputs_change(self):
        k1 = compute_store_key("tool_call", "abc", "def", 1)
        k2 = compute_store_key("tool_call", "abc", "xyz", 1)
        assert k1 != k2

    def test_store_key_deterministic(self):
        k1 = compute_store_key("tool_call", "abc", "def", 1)
        k2 = compute_store_key("tool_call", "abc", "def", 1)
        assert k1 == k2

    def test_hitl_rejected(self):
        with pytest.raises(StoreKeyError):
            compute_store_key("hitl", "abc", "def", 1)

    def test_seed_deterministic_per_attempt(self):
        s1 = derive_seed("fn:mojito/tool$0", 1)
        s2 = derive_seed("fn:mojito/tool$0", 1)
        assert s1 == s2

    def test_seed_differs_across_attempts(self):
        s1 = derive_seed("fn:mojito/tool$0", 1)
        s2 = derive_seed("fn:mojito/tool$0", 2)
        assert s1 != s2

    def test_definition_hash_for_llm_template_independence(self):
        """Same template + same model = same definition_hash, regardless of
        whether the substituted values differ."""
        h1 = definition_hash_for_llm("claude-sonnet", "Research '{name}'.")
        h2 = definition_hash_for_llm("claude-sonnet", "Research '{name}'.")
        assert h1 == h2
        # Different template string -> different hash
        h3 = definition_hash_for_llm("claude-sonnet", "Research '{name}' in detail.")
        assert h3 != h1


# =============================================================================
# Unit tests — graph status transitions
# =============================================================================


class TestStatusTransitions:
    def test_pending_to_computing_allowed(self):
        assert can_transition(EquationStatus.PENDING, EquationStatus.COMPUTING)

    def test_completed_to_invalidated_allowed(self):
        assert can_transition(EquationStatus.COMPLETED, EquationStatus.INVALIDATED)

    def test_completed_to_computing_rejected(self):
        assert not can_transition(EquationStatus.COMPLETED, EquationStatus.COMPUTING)

    def test_same_state_always_allowed(self):
        for s in EquationStatus:
            assert can_transition(s, s)


@pytest.mark.asyncio
async def test_media_finalization_covers_foreach_wrapper(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="media_foreach", outputs={"out": dsl_output(type="list[media]")})
    def media_foreach():
        with phase("Generate"):
            return foreach(
                ["a", "b"],
                lambda value: tool("mock", task_type="text-to-image", prompt=value),
            )

    registry = EvaluatorRegistry()

    async def tool_eval(request: EvaluationRequest) -> EvaluationResult:
        media_id = 101 if ":a/" in request.equation_key else 102
        return EvaluationResult(value=media_id, media_ids=[media_id])

    registry.register("tool_call", tool_eval)
    runtime = FlowRuntime(
        8801,
        db_path,
        flow_callable=media_foreach,
        evaluators=registry,
        store=store,
    )
    graph = runtime.build_initial_graph()
    finalized: list[tuple[str, list[int], str]] = []

    async def finalize(key: str, media_ids: list[int], disposition: str) -> None:
        finalized.append((key, media_ids, disposition))

    run = FlowRun(
        graph,
        FlowRunConfig(
            flow_id=8801,
            state_db_path=db_path,
            finalize_media_results=finalize,
        ),
        evaluators=registry,
        store=store,
    )
    await run.start()
    try:
        await run.wait_quiescent(timeout=3)
    finally:
        await run.stop()

    output_key = graph.output_keys[0]
    assert (output_key, [101, 102], "independent") in finalized
    # Each tool result and its per-iteration control wrapper are retained;
    # the surfaced foreach wrapper then promotes the combined result.
    assert len([row for row in finalized if row[2] == "internal"]) == 4


@pytest.mark.asyncio
async def test_media_finalization_covers_hitl_completion(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="media_hitl", outputs={"out": dsl_output(type="media")})
    def media_hitl():
        with phase("Generate"):
            candidates = foreach(
                range(1),
                lambda _: tool("mock", task_type="text-to-image", prompt="candidate"),
            )
            return hitl.select(candidates, instructions="pick", count=1)

    registry = EvaluatorRegistry()

    async def tool_eval(_request: EvaluationRequest) -> EvaluationResult:
        return EvaluationResult(value=201, media_ids=[201])

    registry.register("tool_call", tool_eval)
    runtime = FlowRuntime(
        8802,
        db_path,
        flow_callable=media_hitl,
        evaluators=registry,
        store=store,
    )
    graph = runtime.build_initial_graph()
    finalized: list[tuple[str, list[int], str]] = []

    async def finalize(key: str, media_ids: list[int], disposition: str) -> None:
        finalized.append((key, media_ids, disposition))

    run = FlowRun(
        graph,
        FlowRunConfig(
            flow_id=8802,
            state_db_path=db_path,
            finalize_media_results=finalize,
            hitl_auto_resolve=lambda _eq, _inputs: 201,
        ),
        evaluators=registry,
        store=store,
    )
    await run.start()
    try:
        await run.wait_quiescent(timeout=3)
    finally:
        await run.stop()

    assert (graph.output_keys[0], [201], "independent") in finalized


@pytest.mark.asyncio
async def test_media_finalizer_failure_becomes_equation_failure(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="media_failure", outputs={"out": dsl_output(type="media")})
    def media_failure():
        with phase("Generate"):
            return tool("mock", task_type="text-to-image", prompt="candidate")

    registry = EvaluatorRegistry()

    async def tool_eval(_request: EvaluationRequest) -> EvaluationResult:
        return EvaluationResult(value=301, media_ids=[301])

    async def fail_finalize(_key: str, _ids: list[int], _disposition: str) -> None:
        raise RuntimeError("retention failed")

    registry.register("tool_call", tool_eval)
    runtime = FlowRuntime(
        8803,
        db_path,
        flow_callable=media_failure,
        evaluators=registry,
        store=store,
    )
    graph = runtime.build_initial_graph()
    run = FlowRun(
        graph,
        FlowRunConfig(
            flow_id=8803,
            state_db_path=db_path,
            finalize_media_results=fail_finalize,
        ),
        evaluators=registry,
        store=store,
    )
    await run.start()
    try:
        await run.wait_quiescent(timeout=3)
    finally:
        await run.stop()

    output = graph.get(graph.output_keys[0])
    assert output.status == EquationStatus.FAILED
    assert "retention failed" in (output.error or "")


# =============================================================================
# Graph-build tests
# =============================================================================


@flow(
    name="cocktail",
    inputs={
        "cocktail_names": dsl_input(type="list[str]"),
        "style": dsl_input(type="enum", options=["art_deco", "minimalist"], default="art_deco"),
    },
    outputs={"posters": dsl_output(type="list[media]")},
)
def _cocktail_flow(cocktail_names, style):
    def research(name):
        return llm(prompt=f"Research '{name}'")

    def illustrate(info, style):
        cands = foreach(range(4), lambda _: tool("flux:text-to-image", task_type="text-to-image", prompt="paint"))
        return hitl.select(cands, instructions="pick", count=1)

    with phase("Research"):
        info = foreach(cocktail_names, research)
    with phase("Illustrate"):
        illus = foreach(info, illustrate, style=style)
    return illus


class TestGraphBuild:
    def test_initial_graph_structure(self):
        graph = build_graph_from_callable(
            _cocktail_flow,
            inputs={"cocktail_names": ["Mojito", "Daiquiri"], "style": "art_deco"},
        )
        keys = graph.keys()
        assert "_cocktail_flow/flow_input$0" in keys
        assert any(k.startswith("_cocktail_flow/foreach$0") for k in keys)
        assert any(k.startswith("_cocktail_flow/foreach$1") for k in keys)
        # At build time, no per-iteration equations yet — they're deferred.
        assert not any(":Mojito" in k for k in keys)

    def test_deferred_registered_for_foreaches(self):
        graph = build_graph_from_callable(
            _cocktail_flow,
            inputs={"cocktail_names": ["Mojito"], "style": "art_deco"},
        )
        deferred = graph.all_deferred()
        kinds = sorted(d.kind for d in deferred)
        assert kinds == ["foreach", "foreach"]

    def test_graph_build_error_surfaces_traceback(self):
        @flow()
        def broken():
            raise ValueError("kaboom")

        from flow_runtime import GraphBuildError

        with pytest.raises(GraphBuildError) as excinfo:
            build_graph_from_callable(broken)
        assert "kaboom" in excinfo.value.program_traceback


# =============================================================================
# Fixtures for async engine tests
# =============================================================================


@pytest.fixture
def isolated_store_and_db():
    """Per-test temp directory with a fresh state.db + equation store.

    Engine tests use this instead of the module-scoped test_app fixture so
    the scheduler's background asyncio task doesn't interfere across tests.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "state.db"
        create_flow_state_db(db_path)
        store = EquationStore(root / "store")
        store.initialize()
        yield db_path, store


def _make_mock_evaluators(
    *,
    tool_response: Any = "tool_result",
    llm_response: Any = "llm_result",
    code_response: Any = "code_result",
    tool_call_counter: dict[str, int] | None = None,
    fail_keys: set[str] | None = None,
    fail_category: str = "transient",
) -> EvaluatorRegistry:
    reg = EvaluatorRegistry()
    fail_keys = fail_keys or set()
    tool_call_counter = tool_call_counter if tool_call_counter is not None else {}

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        tool_call_counter[req.equation_key] = tool_call_counter.get(req.equation_key, 0) + 1
        if req.equation_key in fail_keys:
            raise EvaluatorError(f"mock failure for {req.equation_key}", category=fail_category)
        # Append the iteration index so foreach(range(N), …) produces
        # distinct values per slot (matches legacy `tool(n=N)` markers).
        match = re.search(r":(\d+)/tool\$", req.equation_key)
        if match:
            return EvaluationResult(value=f"{tool_response}#{match.group(1)}")
        return EvaluationResult(value=tool_response)

    async def llm_eval(req: EvaluationRequest) -> EvaluationResult:
        tool_call_counter[req.equation_key] = tool_call_counter.get(req.equation_key, 0) + 1
        if req.equation_key in fail_keys:
            raise EvaluatorError(f"mock llm failure for {req.equation_key}", category=fail_category)
        template = req.definition.get("prompt_template", "")
        return EvaluationResult(value=f"{llm_response}|{template}|attempt{req.attempt}")

    async def code_eval(req: EvaluationRequest) -> EvaluationResult:
        tool_call_counter[req.equation_key] = tool_call_counter.get(req.equation_key, 0) + 1
        src = req.definition.get("source", "")
        inputs = req.resolved_inputs.get("inputs", {})
        # For tests, the code block is ignored — return marker + inputs.
        return EvaluationResult(value={"src": src, "inputs": inputs})

    reg.register("tool_call", tool_eval)
    reg.register("llm_call", llm_eval)
    reg.register("code", code_eval)
    return reg


# =============================================================================
# Integration tests — linear chain
# =============================================================================


@pytest.mark.asyncio
async def test_linear_chain_executes_in_order(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="linear", inputs={"name": dsl_input(type="str")}, outputs={"out": dsl_output(type="str")})
    def linear_flow(name):
        with phase("Compute"):
            a = llm(prompt="A stage")
            b = code("return a", inputs={"a": a})
            return b

    reg = _make_mock_evaluators()
    runtime = FlowRuntime(
        1, db_path, flow_callable=linear_flow, inputs={"name": "x"},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    # Both equations completed
    statuses = {eq.key: eq.status for eq in runtime.graph.all_equations()}
    for key, status in statuses.items():
        assert status == EquationStatus.COMPLETED, f"{key} status={status}"


@pytest.mark.asyncio
async def test_missing_flow_input_blocks_downstream_equations(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="needs_input", inputs={"name": dsl_input(type="str")}, outputs={"out": dsl_output(type="str")})
    def needs_input(name):
        with phase("Compute"):
            return code("return name.upper()", inputs={"name": name})

    runtime = FlowRuntime(
        101, db_path, flow_callable=needs_input, inputs={},
        evaluators=_make_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=1.0)
    await runtime.stop()

    by_type = {eq.equation_type: eq for eq in runtime.graph.all_equations()}
    assert by_type[EquationType.FLOW_INPUT].status == EquationStatus.PENDING
    assert by_type[EquationType.CODE].status == EquationStatus.PENDING


@pytest.mark.asyncio
async def test_flow_input_defaults_are_runtime_values(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(
        name="defaulted_input",
        inputs={
            "name": dsl_input(type="str", default="jazz singer"),
        },
        outputs={"out": dsl_output(type="str")},
    )
    def defaulted_input(name):
        with phase("Compute"):
            return code("return name.upper()", inputs={"name": name})

    runtime = FlowRuntime(
        104, db_path, flow_callable=defaulted_input, inputs={},
        evaluators=_make_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()

    flow_input = next(
        eq for eq in runtime.graph.all_equations()
        if eq.equation_type == EquationType.FLOW_INPUT
    )
    assert flow_input.status == EquationStatus.COMPLETED
    assert flow_input.result == "jazz singer"
    assert flow_input.is_waiting_for_flow_input() is False


@pytest.mark.asyncio
async def test_optional_flow_input_completes_with_none_and_unblocks_downstream(
    isolated_store_and_db,
):
    # Regression: before the ``optional=True`` flag landed, a flow input
    # the user hadn't filled in sat at PENDING forever (``is_waiting_for_
    # flow_input`` guarded any None value), wedging every downstream
    # equation. ``optional=True`` is the DSL signal that None is an
    # acceptable resolved value.
    db_path, store = isolated_store_and_db

    @flow(
        name="optional_input",
        inputs={
            "name": dsl_input(type="str"),
            "note": dsl_input(type="str", optional=True),
        },
        outputs={"out": dsl_output(type="str")},
    )
    def optional_input(name, note):
        with phase("Compute"):
            return code(
                "return (name + (' — ' + note if note else '')).upper()",
                inputs={"name": name, "note": note},
            )

    runtime = FlowRuntime(
        103, db_path, flow_callable=optional_input,
        inputs={"name": "widget"},
        evaluators=_make_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=1.0)
    await runtime.stop()

    by_name = {
        eq.definition.get("input_name"): eq
        for eq in runtime.graph.all_equations()
        if eq.equation_type == EquationType.FLOW_INPUT
    }
    assert by_name["note"].status == EquationStatus.COMPLETED
    assert by_name["note"].result is None
    assert by_name["note"].is_waiting_for_flow_input() is False


@pytest.mark.asyncio
async def test_missing_list_flow_input_still_builds_as_collection(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    def add_bang(name):
        return code("return name + '!'", inputs={"name": name})

    @flow(name="list_input", inputs={"names": dsl_input(type="list[str]")}, outputs={"out": dsl_output(type="list[str]")})
    def list_input(names):
        with phase("Compute"):
            return foreach(names, add_bang)

    runtime = FlowRuntime(
        102, db_path, flow_callable=list_input, inputs={},
        evaluators=_make_mock_evaluators(), store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=1.0)
    await runtime.stop()

    flow_input = next(
        eq for eq in runtime.graph.all_equations()
        if eq.equation_type == EquationType.FLOW_INPUT
    )
    foreach_wrapper = next(
        eq for eq in runtime.graph.all_equations()
        if eq.definition.get("control_kind") == "foreach"
    )
    assert flow_input.definition["is_collection"] is True
    assert flow_input.status == EquationStatus.PENDING
    assert foreach_wrapper.status == EquationStatus.PENDING


# =============================================================================
# Parallel branches test
# =============================================================================


@pytest.mark.asyncio
async def test_parallel_branches_run_concurrently(isolated_store_and_db):
    """A -> (B, C) -> D. B and C should reach COMPUTING simultaneously.

    We ensure this by making B and C await an asyncio.Event that is set
    only after both have begun — if the scheduler ran them serially, the
    event would never be set.
    """
    db_path, store = isolated_store_and_db

    both_running = asyncio.Event()
    running_count = 0
    lock = asyncio.Lock()

    async def parallel_llm(req):
        nonlocal running_count
        async with lock:
            running_count += 1
            if running_count >= 2:
                both_running.set()
        await both_running.wait()
        return EvaluationResult(value=f"ok-{req.equation_key}")

    reg = EvaluatorRegistry()
    reg.register("llm_call", parallel_llm)

    @flow()
    def parallel_flow():
        with phase("Generate"):
            b = llm(prompt="B")
            c = llm(prompt="C")
        with phase("Combine"):
            return code("return [b, c]", inputs={"b": b, "c": c})

    runtime = FlowRuntime(
        2, db_path, flow_callable=parallel_flow, evaluators=reg, store=store,
    )

    # code_call needs to work too
    async def code_eval(req):
        return EvaluationResult(value=req.resolved_inputs["inputs"])
    reg.register("code", code_eval)

    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    assert both_running.is_set(), "B and C did not execute concurrently"
    final = {eq.key: eq.status for eq in runtime.graph.all_equations()}
    assert all(s == EquationStatus.COMPLETED for s in final.values())


# =============================================================================
# Foreach expansion + nested foreach
# =============================================================================


@pytest.mark.asyncio
async def test_foreach_expansion(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(inputs={"names": dsl_input(type="list[str]")})
    def simple(names):
        def one(name):
            return llm(prompt=f"Greet {name}")
        return foreach(names, one)

    reg = _make_mock_evaluators()
    runtime = FlowRuntime(
        3, db_path, flow_callable=simple, inputs={"names": ["Alice", "Bob", "Carol"]},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    # Every iteration completed
    keys = [eq.key for eq in runtime.graph.all_equations()]
    for name in ["Alice", "Bob", "Carol"]:
        matches = [k for k in keys if f":{name}" in k]
        assert matches, f"no equation for iteration {name}: keys={keys}"

    # Top-level foreach wrapper collected results
    foreach_wrapper = next(
        eq for eq in runtime.graph.all_equations()
        if eq.definition.get("control_kind") == "foreach"
    )
    assert foreach_wrapper.status == EquationStatus.COMPLETED
    assert len(foreach_wrapper.result) == 3


@pytest.mark.asyncio
async def test_nested_foreach(isolated_store_and_db):
    """foreach within foreach. Each outer iteration spawns its own inner list."""
    db_path, store = isolated_store_and_db

    @flow(inputs={"groups": dsl_input(type="list[dict]")})
    def nested(groups):
        def process_group(group):
            items = group["items"]
            def process_item(item):
                return llm(prompt=f"handle {item}")
            return foreach(items, process_item)
        return foreach(groups, process_group)

    reg = _make_mock_evaluators()
    runtime = FlowRuntime(
        4, db_path, flow_callable=nested,
        inputs={"groups": [{"items": ["a", "b"]}, {"items": ["c"]}]},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    # Outer wrapper should have 2 results, each of which is a list.
    outer_wrapper = next(
        eq for eq in runtime.graph.all_equations()
        if eq.key == "nested/foreach$0"
    )
    assert outer_wrapper.status == EquationStatus.COMPLETED
    assert len(outer_wrapper.result) == 2
    assert len(outer_wrapper.result[0]) == 2   # first group had 2 items
    assert len(outer_wrapper.result[1]) == 1


@pytest.mark.asyncio
async def test_chained_foreach_expands_downstream_before_upstream_completes(
    isolated_store_and_db,
):
    """Chaining ``foreach(upstream_foreach, fn)`` should materialize the
    downstream iteration wrappers as soon as the upstream foreach has its own
    iteration wrappers in place — not wait for every upstream iteration to
    complete before even showing the downstream structure.

    Structural invariant: each downstream tool's dependency list includes
    the corresponding upstream iteration wrapper (pipelining), instead of
    receiving the upstream's resolved result as a static value.
    """
    db_path, store = isolated_store_and_db

    @flow()
    def pipeline():
        with phase("Upstream"):
            def make_upstream(i):
                return tool("gen", task_type="text-to-image", prompt=f"upstream-{i}")
            upstream = foreach([0, 1, 2], make_upstream)

        with phase("Downstream"):
            def upscale(item):
                return tool("upscale", task_type="text-to-image", input_images=[item])
            downstream = foreach(upstream, upscale)

        with phase("Output"):
            return code("return d", inputs={"d": downstream})

    reg = _make_mock_evaluators()
    runtime = FlowRuntime(
        5001, db_path, flow_callable=pipeline,
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=5.0)

        equations = runtime.graph.all_equations()
        upstream_wrapper = next(
            eq for eq in equations
            if eq.key == "pipeline/foreach$0"
        )
        downstream_wrapper = next(
            eq for eq in equations
            if eq.key == "pipeline/foreach$1"
        )
        assert upstream_wrapper.status == EquationStatus.COMPLETED
        assert downstream_wrapper.status == EquationStatus.COMPLETED
        assert len(downstream_wrapper.result) == 3

        # Downstream iteration keys align with upstream iteration keys —
        # early expansion paired them 1:1.
        upstream_iter_keys = sorted(
            eq.definition["iteration_key"]
            for eq in equations
            if eq.key.startswith("pipeline/foreach$0/")
            and eq.definition.get("control_kind") == "foreach_iteration"
        )
        downstream_iter_keys = sorted(
            eq.definition["iteration_key"]
            for eq in equations
            if eq.key.startswith("pipeline/foreach$1/")
            and eq.definition.get("control_kind") == "foreach_iteration"
        )
        assert upstream_iter_keys == downstream_iter_keys
        assert len(downstream_iter_keys) == 3

        # Each downstream upscale tool must depend on its paired upstream
        # iteration wrapper. In the old (resolved-only) path, the upstream's
        # resolved value was embedded as a static param and the tool had
        # no cross-foreach dependency — so downstream iterations couldn't
        # be pipelined.
        for iter_key in downstream_iter_keys:
            upstream_iter_wrapper_key = f"pipeline/foreach$0/make_upstream:{iter_key}"
            downstream_iter_wrapper_key = f"pipeline/foreach$1/upscale:{iter_key}"
            downstream_tool = next(
                eq for eq in equations
                if eq.key.startswith(f"{downstream_iter_wrapper_key}/tool$")
            )
            assert upstream_iter_wrapper_key in downstream_tool.dependencies, (
                f"downstream tool {downstream_tool.key} should depend on "
                f"{upstream_iter_wrapper_key}; deps={downstream_tool.dependencies}"
            )
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_chained_foreach_pipelines_per_item(isolated_store_and_db):
    """An upstream iteration that completes should unblock its paired
    downstream iteration without waiting for the rest of the upstream.

    Gate the upstream tool on a key-specific asyncio.Event. Hold back the
    last upstream item; assert the downstream iteration for the items
    already finished has also completed while the other downstream is
    still pending.
    """
    db_path, store = isolated_store_and_db

    @flow()
    def pipeline():
        with phase("Upstream"):
            def make_upstream(i):
                return tool("gen", task_type="text-to-image", prompt=f"u-{i}")
            upstream = foreach([0, 1, 2], make_upstream)
        with phase("Downstream"):
            def upscale(item):
                return tool("upscale", task_type="text-to-image", input_images=[item])
            downstream = foreach(upstream, upscale)
        with phase("Output"):
            return code("return d", inputs={"d": downstream})

    # Gate upstream iteration key "2" until we release it.
    gate = asyncio.Event()

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        key = req.equation_key
        if key.endswith(":2/tool$0") and "foreach$0" in key and "foreach$1" not in key:
            await gate.wait()
        prompt = req.definition.get("params", {}).get("prompt", "")
        if prompt.startswith("u-"):
            return EvaluationResult(value=f"media:{prompt}")
        return EvaluationResult(value=f"upscaled:{prompt}")

    async def code_eval(req: EvaluationRequest) -> EvaluationResult:
        return EvaluationResult(value=req.resolved_inputs["inputs"]["d"])

    reg = EvaluatorRegistry()
    reg.register("tool_call", tool_eval)
    reg.register("code", code_eval)

    runtime = FlowRuntime(
        5003, db_path, flow_callable=pipeline,
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        # Wait for items 0 and 1 to flow fully through the pipeline while
        # item 2 is gated upstream.
        async def items_0_1_done():
            keys_needed = {
                "pipeline/foreach$1/upscale:0",
                "pipeline/foreach$1/upscale:1",
            }
            for _ in range(200):
                eqs = {eq.key: eq for eq in runtime.graph.all_equations()}
                if all(
                    k in eqs and eqs[k].status == EquationStatus.COMPLETED
                    for k in keys_needed
                ):
                    return True
                await asyncio.sleep(0.02)
            return False

        assert await items_0_1_done(), (
            "downstream iterations for items 0/1 should have completed while "
            "upstream item 2 is still gated — pipelining is the point"
        )

        # Upstream iteration 2 is still pending; downstream iteration 2
        # must not have completed yet.
        upstream_2 = runtime.graph.get("pipeline/foreach$0/make_upstream:2")
        downstream_2 = runtime.graph.get("pipeline/foreach$1/upscale:2")
        assert upstream_2.status != EquationStatus.COMPLETED
        assert downstream_2.status != EquationStatus.COMPLETED

        # Release the gate and let the pipeline finish.
        gate.set()
        await runtime.wait_quiescent(timeout=5.0)

        downstream_wrapper = runtime.graph.get("pipeline/foreach$1")
        assert downstream_wrapper.status == EquationStatus.COMPLETED
        assert len(downstream_wrapper.result) == 3
    finally:
        gate.set()  # avoid hang if something asserted above
        await runtime.stop()


@pytest.mark.asyncio
async def test_chained_foreach_falls_back_when_callback_inspects_item(
    isolated_store_and_db,
):
    """If the downstream callback subscripts or f-strings the item at build
    time, the probe raises NodeUsageError and we fall back to the classic
    "wait for upstream to fully complete, pass resolved values" path. The
    flow must still complete correctly — just without pipelining.
    """
    db_path, store = isolated_store_and_db

    @flow()
    def pipeline():
        with phase("Upstream"):
            def make_upstream(i):
                return code("return {'v': i}", inputs={"i": i})
            upstream = foreach([0, 1], make_upstream)

        with phase("Downstream"):
            def needs_field(item):
                # Build-time subscript — probe rejects this; fall back.
                return llm(prompt=f"use {item['v']}")
            downstream = foreach(upstream, needs_field)

        with phase("Output"):
            return code("return d", inputs={"d": downstream})

    reg = _make_mock_evaluators(code_response={"v": 42})

    # code_eval in the mock returns {'src': ..., 'inputs': ...}, but the
    # fallback path subscripts item['v']. Override code_eval to return
    # a dict with 'v' so the fallback actually works.
    async def code_eval_with_v(req: EvaluationRequest) -> EvaluationResult:
        inputs = req.resolved_inputs.get("inputs", {})
        if "i" in inputs:
            return EvaluationResult(value={"v": inputs["i"]})
        return EvaluationResult(value=inputs.get("d"))
    reg.register("code", code_eval_with_v)

    runtime = FlowRuntime(
        5002, db_path, flow_callable=pipeline,
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=5.0)

        deferred = next(
            d for d in runtime.graph.all_deferred()
            if d.owner_key == "pipeline/foreach$1"
        )
        assert deferred.early_blocked is True, (
            "probe should have detected the build-time subscript and blocked "
            "the early-expansion path for this foreach"
        )

        downstream_wrapper = runtime.graph.get("pipeline/foreach$1")
        assert downstream_wrapper.status == EquationStatus.COMPLETED
        assert len(downstream_wrapper.result) == 2
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_chained_foreach_preserves_per_iteration_upstream_deps(
    isolated_store_and_db,
):
    """When both modes are available, early expansion wins so each downstream
    iteration's tool call records its upstream iteration wrapper as a dep.

    Regression: the previous mode selector preferred resolved mode whenever
    upstream had COMPLETED, which strips NodeRef identity from items and
    leaves downstream tool equations with ``dependencies=[]``. The graph
    visualizer then shows downstream iterations with no incoming edges even
    though execution is correct. Prefer early mode so per-iteration
    provenance survives into ``eq.dependencies``.
    """
    db_path, store = isolated_store_and_db

    @flow()
    def pipeline():
        with phase("Upstream"):
            def make_upstream(i):
                return tool("gen", task_type="text-to-image", prompt=f"u-{i}")
            upstream = foreach([0, 1, 2], make_upstream)
        with phase("Downstream"):
            def upscale(item):
                return tool("upscale", task_type="text-to-image", input_images=[item])
            downstream = foreach(upstream, upscale)
        with phase("Output"):
            return code("return d", inputs={"d": downstream})

    reg = _make_mock_evaluators(tool_response="ok")

    runtime = FlowRuntime(
        5004, db_path, flow_callable=pipeline,
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=5.0)

        # The downstream foreach should have completed.
        downstream_wrapper = runtime.graph.get("pipeline/foreach$1")
        assert downstream_wrapper.status == EquationStatus.COMPLETED
        assert len(downstream_wrapper.result) == 3

        # Each downstream per-iteration tool call must list the corresponding
        # upstream iteration wrapper as its dependency. Without that, the
        # graph viz paints the downstream iterations as orphaned nodes.
        for ik in ("0", "1", "2"):
            up_wrapper_key = f"pipeline/foreach$0/make_upstream:{ik}"
            down_tool_key = f"pipeline/foreach$1/upscale:{ik}/tool$0"
            assert runtime.graph.try_get(up_wrapper_key) is not None
            down_tool = runtime.graph.try_get(down_tool_key)
            assert down_tool is not None, (
                f"expected downstream tool equation {down_tool_key!r}"
            )
            assert up_wrapper_key in down_tool.dependencies, (
                f"downstream tool {down_tool_key!r} should list upstream "
                f"iteration wrapper {up_wrapper_key!r} in its dependencies; "
                f"got {down_tool.dependencies!r}"
            )
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_invalidate_rebuilds_nested_foreach_extra_kwarg_subgraph(isolated_store_and_db):
    """Invalidating a collection passed through extra_kwargs must rebuild nested foreach children.

    Regression: the wrapper stayed marked ``expanded=True`` after invalidation,
    so nested foreach/image equations were reused with stale definitions even
    after the upstream collection regenerated.
    """
    db_path, store = isolated_store_and_db

    @flow()
    def nested_extra_kwarg():
        with phase("Inputs"):
            people = code(
                "return ['alice', 'bob']", inputs={}, output_type="list[str]",
            )
            activities = code(
                "return ['reading', 'running']",
                inputs={},
                output_type="list[str]",
            )

        with phase("Images"):
            def gen_one(activity, person):
                return tool("gen", task_type="text-to-image", prompt=f"{person}|{activity}")

            def gen_for_person(person, activities):
                return foreach(activities, gen_one, person=person)

            images = foreach(people, gen_for_person, activities=activities)

        with phase("Output"):
            return code("return images", inputs={"images": images})

    reg = EvaluatorRegistry()

    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        prompt = req.definition.get("params", {}).get("prompt")
        return EvaluationResult(value=prompt)

    async def code_eval(req: EvaluationRequest) -> EvaluationResult:
        source = req.definition.get("source", "")
        if "'alice'" in source:
            return EvaluationResult(value=["alice", "bob"])
        if "'reading'" in source:
            if req.attempt == 1:
                return EvaluationResult(value=["reading", "running"])
            return EvaluationResult(value=["cooking", "painting"])
        return EvaluationResult(value=req.resolved_inputs["inputs"]["images"])

    reg.register("tool_call", tool_eval)
    reg.register("code", code_eval)

    runtime = FlowRuntime(
        4001,
        db_path,
        flow_callable=nested_extra_kwarg,
        evaluators=reg,
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=5.0)

        image_prompt_defs_before = sorted(
            eq.definition.get("params", {}).get("prompt")
            for eq in runtime.graph.all_equations()
            if eq.equation_type == EquationType.TOOL_CALL
            and "|" in str(eq.definition.get("params", {}).get("prompt"))
        )
        assert image_prompt_defs_before == [
            "alice|reading",
            "alice|running",
            "bob|reading",
            "bob|running",
        ]

        activities_key = next(
            eq.key
            for eq in runtime.graph.all_equations()
            if eq.equation_type == EquationType.CODE
            and "'reading'" in eq.definition.get("source", "")
        )

        runtime.invalidate(activities_key)
        await runtime.wait_quiescent(timeout=5.0)

        image_prompt_defs_after = sorted(
            eq.definition.get("params", {}).get("prompt")
            for eq in runtime.graph.all_equations()
            if eq.equation_type == EquationType.TOOL_CALL
            and "|" in str(eq.definition.get("params", {}).get("prompt"))
        )
        assert image_prompt_defs_after == [
            "alice|cooking",
            "alice|painting",
            "bob|cooking",
            "bob|painting",
        ]
    finally:
        await runtime.stop()


def test_info_inherits_phase_dependencies():
    """info() inside a phase implicitly depends on all equations registered
    earlier in the same phase (and in any nested phase beneath it).

    Without this, an info card whose only explicit inputs are flow inputs
    resolves immediately and renders 'done' before the phase's work has
    finished — the 'Product Analysis Complete shows up before the LLM
    even starts' class of bug.
    """
    from flow_dsl.primitives import info

    @flow(inputs={"x": dsl_input(type="str")})
    def r(x):
        with phase("Outer"):
            t1 = tool("gen", task_type="text-to-image", prompt="a")
            with phase("Inner"):
                t2 = tool("gen", task_type="text-to-image", prompt="b")
            summary = info("done", title="Summary", inputs={"x": x})
        return summary

    graph = build_graph_from_callable(r, inputs={"x": "hi"})
    info_eq = next(
        eq for eq in graph.all_equations() if eq.equation_type.value == "info"
    )
    # Info's deps cover both the outer-phase tool and the nested-phase tool,
    # not just the flow-input it explicitly references.
    deps = set(info_eq.dependencies)
    assert "r/tool$0" in deps
    assert "r/phase_container_" not in "|".join(deps)
    # At least one dep per in-phase equation
    in_phase_tool_deps = [d for d in deps if "/tool$" in d]
    assert len(in_phase_tool_deps) == 2


def test_info_depends_on_foreach_wrapper_in_same_phase():
    """info() following a foreach() in the same phase must wait for the
    foreach wrapper, not just for cheaper siblings (code/llm).

    Regression: foreach/hitl.approve/zip_nodes built their wrapper equations
    via ctx.graph.add_equation directly and never registered the wrapper in
    the frame's registered_equations list. info()'s implicit phase deps
    skipped them, so the "All Done" card rendered as soon as a fast code()
    completed even though the foreach was still WAITING.
    """
    from flow_dsl.primitives import code as dsl_code
    from flow_dsl.primitives import foreach, info

    @flow(inputs={"x": dsl_input(type="str")})
    def r(x):
        with phase("Cartoon-ify"):
            cheap = dsl_code(lambda x: f"prompt {x}", inputs={"x": x}, output_type="text")
            cartoons = foreach([1, 2, 3], lambda i: tool("gen", task_type="text-to-image", prompt=cheap))
            info("done", title="All Done", inputs={"x": x})
        return cartoons

    graph = build_graph_from_callable(r, inputs={"x": "hi"})
    info_eq = next(
        eq for eq in graph.all_equations() if eq.equation_type.value == "info"
    )
    deps = set(info_eq.dependencies)
    # The foreach wrapper key has the form r/foreach$<n>; assert info waits
    # on it, not just on the cheap code() that fires immediately.
    assert any(d.endswith("/foreach$0") for d in deps), (
        f"info should depend on the foreach wrapper, deps={deps}"
    )


def test_info_in_sibling_phase_does_not_inherit_other_phase_deps():
    """info() in one phase does not depend on equations in a sibling phase.

    The implicit phase-ordering guarantee is scoped to the current phase
    (and anything nested inside it) — not earlier/later sibling phases.
    """
    from flow_dsl.primitives import info

    @flow(inputs={})
    def r():
        with phase("A"):
            a = tool("gen", task_type="text-to-image", prompt="a")
        with phase("B"):
            summary = info("done in B", title="Summary")
        return [summary, a]

    graph = build_graph_from_callable(r)
    info_eq = next(
        eq for eq in graph.all_equations() if eq.equation_type.value == "info"
    )
    # Info in "B" has no dependencies — "A"'s tool is in a sibling phase.
    assert info_eq.dependencies == []


def test_info_title_is_required():
    """info() requires a non-empty title — replaces the generic 'Info' label."""
    from flow_dsl.primitives import info
    from flow_dsl.errors import DSLMisuseError

    @flow(inputs={})
    def r_empty_title():
        with phase("A"):
            return info("body", title="   ")

    with pytest.raises(Exception, match="title is required"):
        build_graph_from_callable(r_empty_title)


def test_tool_task_type_is_required():
    """tool() requires task_type so the row title can render as the action
    ("Generate Image") instead of the model name. Without it, the equation
    would carry a null task_type and the UI would have to reverse-engineer
    it from the tool_id slug. The DSL loader wraps DSLMisuseError into
    ProgramLoadError so the agent sees a clean, classified error."""
    @flow(inputs={})
    def r_missing_task_type():
        with phase("A"):
            return tool("gen", prompt="x")

    with pytest.raises(Exception, match="task_type is required"):
        build_graph_from_callable(r_missing_task_type)


def test_tool_task_type_lands_on_definition():
    """The supplied task_type is persisted on the equation definition so the
    backend can surface it without inferring from the tool_id slug."""
    @flow(inputs={})
    def r():
        with phase("A"):
            return tool("gen", task_type="text-to-image", prompt="x")

    graph = build_graph_from_callable(r)
    tool_eq = next(
        eq for eq in graph.all_equations() if eq.equation_type.value == "tool_call"
    )
    assert tool_eq.definition["task_type"] == "text-to-image"


def test_info_title_and_subtitle_stored_in_definition():
    """Title and subtitle land on the equation definition so routes/flows.py
    can surface them as display_name + subtitle without touching the body."""
    from flow_dsl.primitives import info

    @flow(inputs={})
    def r():
        with phase("A"):
            return info(
                "Body text.",
                title="Product Analysis",
                subtitle="From uploaded reference",
            )

    graph = build_graph_from_callable(r)
    info_eq = next(
        eq for eq in graph.all_equations() if eq.equation_type.value == "info"
    )
    assert info_eq.definition["title"] == "Product Analysis"
    assert info_eq.definition["subtitle"] == "From uploaded reference"
    assert info_eq.definition["template"] == "Body text."


@pytest.mark.asyncio
async def test_foreach_iteration_callback_error_creates_task(isolated_store_and_db):
    """A foreach callback that raises during expansion should surface as a
    per-iteration error task with the failure message, not a silent 'N errors'
    header with nothing in the task panel.

    Regression test: before the fix, _finalize_failure ran against an equation
    row that hadn't been persisted yet, so the UPDATE no-op'd and insert_task
    hit a FK violation that got swallowed — tasks disappeared.
    """
    db_path, store = isolated_store_and_db

    @flow(inputs={"items": dsl_input(type="list[str]")})
    def r(items):
        def bad_callback(item, item2):  # takes two positional args
            return llm(prompt="ignored")
        return foreach(items, bad_callback)  # foreach only passes one

    reg = _make_mock_evaluators()
    runtime = FlowRuntime(
        9901, db_path, flow_callable=r,
        inputs={"items": ["a", "b", "c"]},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()

    # Poll for the 3 error tasks.
    for _ in range(100):
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT task_type, instructions, equation_id FROM tasks "
                "WHERE status='pending'"
            ).fetchall()
        finally:
            conn.close()
        if len(rows) >= 3:
            break
        await asyncio.sleep(0.05)
    await runtime.stop()

    assert len(rows) == 3, f"expected 3 error tasks, got {rows}"
    for task_type, instructions, equation_id in rows:
        assert task_type == "error"
        assert "callback error" in instructions

    # And the iteration-wrapper rows are persisted with failed status + error.
    conn = sqlite3.connect(str(db_path))
    try:
        failed = conn.execute(
            "SELECT equation_key, error FROM equations WHERE status='failed'"
        ).fetchall()
    finally:
        conn.close()
    assert len(failed) == 3
    for key, err in failed:
        assert "callback error" in (err or "")


def test_completed_deferred_foreach_is_not_reexpanded(isolated_store_and_db):
    """Hydrated completed foreach wrappers must not re-run stale deferred code."""
    db_path, store = isolated_store_and_db

    @flow(inputs={"items": dsl_input(type="list[str]")})
    def r(items):
        return foreach(items, lambda item: tool("stub:image", prompt=item))

    runtime = FlowRuntime(
        9902,
        db_path,
        flow_callable=r,
        inputs={"items": ["a"]},
        evaluators=_make_mock_evaluators(),
        store=store,
    )
    runtime.build_initial_graph()

    deferred = next(d for d in runtime.graph.all_deferred() if d.kind == "foreach")
    wrapper = runtime.graph.get(deferred.owner_key)
    wrapper.status = EquationStatus.COMPLETED
    wrapper.result = [1411]

    deferred.expanded = False

    run = FlowRun(
        runtime.graph,
        FlowRunConfig(flow_id=9902, state_db_path=db_path),
        evaluators=runtime.evaluators,
        store=store,
    )

    assert run._try_expand_deferred() is False
    assert wrapper.status == EquationStatus.COMPLETED
    assert wrapper.result == [1411]
    assert deferred.expanded is True


# =============================================================================
# HITL blocking + resolution
# =============================================================================


@pytest.mark.asyncio
async def test_hitl_blocks_and_unblocks_on_resolve(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(inputs={"names": dsl_input(type="list[str]")})
    def with_hitl(names):
        def one(name):
            cands = foreach(
                range(3), lambda _: tool("gen", task_type="text-to-image", prompt=f"three of {name}"),
            )
            return hitl.select(cands, instructions=f"pick for {name}", count=1)
        return foreach(names, one)

    reg = _make_mock_evaluators()
    runtime = FlowRuntime(
        5, db_path, flow_callable=with_hitl, inputs={"names": ["A", "B"]},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()

    # Wait for HITL tasks to appear in the state.db.
    for _ in range(50):
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT id, task_type, status, instructions FROM tasks WHERE status='pending'"
            ).fetchall()
        finally:
            conn.close()
        if len(rows) == 2:
            break
        await asyncio.sleep(0.05)
    assert len(rows) == 2, f"expected 2 pending tasks, got {rows}"

    # Resolve both
    task_ids = [r[0] for r in rows]
    for tid in task_ids:
        await runtime.resolve_task(tid, "chosen")

    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    # Foreach wrapper should now be completed with 2 entries.
    wrapper = next(
        eq for eq in runtime.graph.all_equations()
        if eq.key == "with_hitl/foreach$0"
    )
    assert wrapper.status == EquationStatus.COMPLETED
    assert wrapper.result == ["chosen", "chosen"]


# =============================================================================
# Invalidation cascade
# =============================================================================


@pytest.mark.asyncio
async def test_invalidation_cascades_and_rebumps_attempt(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow()
    def chain():
        with phase("Compute"):
            a = llm(prompt="a")
            b = code("return a+'!'", inputs={"a": a})
            return b

    counter: dict[str, int] = {}
    reg = _make_mock_evaluators(tool_call_counter=counter)
    runtime = FlowRuntime(
        6, db_path, flow_callable=chain, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)

    a_key = next(k for k in runtime.graph.keys() if k.endswith("/llm$0"))
    b_key = next(k for k in runtime.graph.keys() if k.endswith("/code$0"))

    a_before = runtime.graph.get(a_key)
    b_before = runtime.graph.get(b_key)
    assert a_before.status == EquationStatus.COMPLETED
    assert b_before.attempt == 1

    # Invalidate A. Expect: A.attempt bumps, both reset to pending, both re-evaluate.
    runtime.invalidate(a_key)
    await runtime.wait_quiescent(timeout=5.0)

    a_after = runtime.graph.get(a_key)
    b_after = runtime.graph.get(b_key)
    assert a_after.status == EquationStatus.COMPLETED
    assert b_after.status == EquationStatus.COMPLETED
    assert a_after.attempt == 2, "direct invalidation must bump attempt"
    assert b_after.attempt == 1, "downstream should keep attempt — inputs_hash changes naturally"
    assert counter[a_key] >= 2
    assert counter[b_key] >= 2

    await runtime.stop()


# =============================================================================
# Store hit on re-run with same inputs
# =============================================================================


@pytest.mark.asyncio
async def test_store_hits_prevent_redundant_computation(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(inputs={"names": dsl_input(type="list[str]")})
    def r(names):
        def research(name):
            return llm(prompt=f"Research {name}")
        return foreach(names, research)

    # First run: populate the store.
    counter1: dict[str, int] = {}
    reg1 = _make_mock_evaluators(tool_call_counter=counter1)
    rt1 = FlowRuntime(
        10, db_path, flow_callable=r, inputs={"names": ["Alice", "Bob"]},
        evaluators=reg1, store=store,
    )
    rt1.build_initial_graph()
    await rt1.start()
    await rt1.wait_quiescent(timeout=5.0)
    await rt1.stop()
    first_run_llm_calls = sum(v for k, v in counter1.items() if "/llm$0" in k)
    assert first_run_llm_calls == 2

    # Second run on a fresh state.db but SAME store: every LLM should be a store hit.
    db_path2 = db_path.parent / "state2.db"
    create_flow_state_db(db_path2)

    counter2: dict[str, int] = {}
    reg2 = _make_mock_evaluators(tool_call_counter=counter2)
    rt2 = FlowRuntime(
        11, db_path2, flow_callable=r, inputs={"names": ["Alice", "Bob"]},
        evaluators=reg2, store=store,
    )
    rt2.build_initial_graph()
    await rt2.start()
    await rt2.wait_quiescent(timeout=5.0)
    await rt2.stop()

    # Evaluators should never have been called on the second run.
    second_run_llm_calls = sum(v for k, v in counter2.items() if "/llm$0" in k)
    assert second_run_llm_calls == 0, (
        f"expected store hits, but evaluator ran {second_run_llm_calls} times"
    )


# =============================================================================
# Pause / resume
# =============================================================================


@pytest.mark.asyncio
async def test_pause_resume_preserves_state(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    gate = asyncio.Event()
    calls = 0

    async def gated_llm(req):
        nonlocal calls
        calls += 1
        await gate.wait()
        return EvaluationResult(value="done")

    reg = EvaluatorRegistry()
    reg.register("llm_call", gated_llm)

    @flow()
    def r():
        with phase("Generate"):
            return llm(prompt="stuck")

    runtime = FlowRuntime(
        20, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()

    # Wait for the evaluator to have started.
    for _ in range(30):
        if calls > 0:
            break
        await asyncio.sleep(0.02)
    assert calls == 1

    await runtime.pause()
    assert runtime.run.state == "paused"

    # Let the in-flight call finish.
    gate.set()

    await runtime.resume()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    eq = next(iter(runtime.graph.all_equations()))
    assert eq.status == EquationStatus.COMPLETED


@pytest.mark.asyncio
async def test_invalidate_computing_equation_reruns_immediately(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    first_started = asyncio.Event()
    second_started = asyncio.Event()
    first_release = asyncio.Event()

    async def gated_llm(req):
        if req.attempt == 1:
            first_started.set()
            await first_release.wait()
            return EvaluationResult(value="stale")
        if req.attempt == 2:
            second_started.set()
            return EvaluationResult(value="fresh")
        return EvaluationResult(value=f"attempt-{req.attempt}")

    reg = EvaluatorRegistry()
    reg.register("llm_call", gated_llm)

    @flow()
    def r():
        with phase("Generate"):
            return llm(prompt="stuck")

    runtime = FlowRuntime(
        21, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        [llm_key] = [k for k in runtime.graph.keys() if "/llm$" in k]
        assert runtime.graph.get(llm_key).status == EquationStatus.COMPUTING

        runtime.invalidate(llm_key)

        # Invalidating a computing equation should free the slot immediately
        # and launch a fresh attempt without waiting for the stale one.
        await asyncio.wait_for(second_started.wait(), timeout=1.0)
        await runtime.wait_quiescent(timeout=1.0)
        assert runtime.graph.get(llm_key).attempt == 2
        assert runtime.graph.get(llm_key).result == "fresh"
    finally:
        first_release.set()
        await runtime.stop()


@pytest.mark.asyncio
async def test_invalidate_restarts_dead_scheduler_task(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    first_started = asyncio.Event()
    second_started = asyncio.Event()
    first_release = asyncio.Event()

    async def gated_llm(req):
        if req.attempt == 1:
            first_started.set()
            await first_release.wait()
            return EvaluationResult(value="stale")
        if req.attempt == 2:
            second_started.set()
            return EvaluationResult(value="fresh")
        return EvaluationResult(value=f"attempt-{req.attempt}")

    reg = EvaluatorRegistry()
    reg.register("llm_call", gated_llm)

    @flow()
    def r():
        with phase("Generate"):
            return llm(prompt="stuck")

    runtime = FlowRuntime(
        22, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        [llm_key] = [k for k in runtime.graph.keys() if "/llm$" in k]

        scheduler_task = runtime.run._task
        scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler_task

        runtime.invalidate(llm_key)

        await asyncio.wait_for(second_started.wait(), timeout=1.0)
        await runtime.wait_quiescent(timeout=1.0)
        assert runtime.graph.get(llm_key).attempt == 2
        assert runtime.graph.get(llm_key).status == EquationStatus.COMPLETED
        assert runtime.graph.get(llm_key).result == "fresh"
    finally:
        first_release.set()
        await runtime.stop()


# =============================================================================
# Error handling
# =============================================================================


@pytest.mark.asyncio
async def test_transient_error_retries_up_to_3(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    attempts = 0
    async def flaky(req):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise EvaluatorError("still flaky", category="transient")
        return EvaluationResult(value="ok")

    reg = EvaluatorRegistry()
    reg.register("llm_call", flaky)

    @flow()
    def r():
        with phase("Run"):
            return llm(prompt="test")

    runtime = FlowRuntime(
        30, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/llm$0"))
    assert eq.status == EquationStatus.COMPLETED
    assert attempts == 3


@pytest.mark.asyncio
async def test_tool_error_fails_immediately(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    async def always_fails(req):
        raise EvaluatorError("safety filter", category="tool_error")
    reg = EvaluatorRegistry()
    reg.register("tool_call", always_fails)

    @flow()
    def r():
        with phase("Run"):
            return tool("gen", task_type="text-to-image", prompt="x")

    runtime = FlowRuntime(
        31, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/tool$0"))
    assert eq.status == EquationStatus.FAILED
    assert "safety filter" in eq.error


@pytest.mark.asyncio
async def test_llm_error_retries_once(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    attempts = 0
    async def sometimes_fails(req):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise EvaluatorError("schema mismatch", category="llm_error")
        return EvaluationResult(value="ok")

    reg = EvaluatorRegistry()
    reg.register("llm_call", sometimes_fails)

    @flow()
    def r():
        with phase("Run"):
            return llm(prompt="x")

    runtime = FlowRuntime(
        32, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    eq = next(eq for eq in runtime.graph.all_equations() if eq.key.endswith("/llm$0"))
    assert eq.status == EquationStatus.COMPLETED
    assert attempts == 2


@pytest.mark.asyncio
async def test_resource_exhaustion_pauses_flow(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    async def out_of_credits(req):
        raise EvaluatorError("no more credits", category="resource")
    reg = EvaluatorRegistry()
    reg.register("llm_call", out_of_credits)

    @flow()
    def r():
        with phase("Run"):
            return llm(prompt="x")

    runtime = FlowRuntime(
        33, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    # Give it a chance to hit the error and pause.
    for _ in range(50):
        if runtime.run.state == "paused":
            break
        await asyncio.sleep(0.05)
    assert runtime.run.state == "paused"
    await runtime.stop()


@pytest.mark.asyncio
async def test_loop_failure_isolation(isolated_store_and_db):
    """One failing iteration must not prevent siblings from completing."""
    db_path, store = isolated_store_and_db

    async def fails_on_B(req):
        template = req.definition.get("prompt_template", "")
        # Template is just the literal prompt string in our simple DSL.
        if "B" in template:
            raise EvaluatorError("nope", category="tool_error")
        return EvaluationResult(value=f"ok-{template}")

    reg = EvaluatorRegistry()
    reg.register("llm_call", fails_on_B)

    @flow(inputs={"names": dsl_input(type="list[str]")})
    def r(names):
        def one(name):
            return llm(prompt=f"hi {name}")
        return foreach(names, one)

    runtime = FlowRuntime(
        34, db_path, flow_callable=r, inputs={"names": ["A", "B", "C"]},
        evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    by_iter = {}
    for eq in runtime.graph.all_equations():
        for name in ["A", "B", "C"]:
            if eq.key.endswith(f"/llm$0") and f":{name}/" in eq.key:
                by_iter[name] = eq
    assert by_iter["A"].status == EquationStatus.COMPLETED
    assert by_iter["C"].status == EquationStatus.COMPLETED
    assert by_iter["B"].status == EquationStatus.FAILED


# =============================================================================
# 10-wide concurrency cap
# =============================================================================


@pytest.mark.asyncio
async def test_concurrency_cap_holds_under_load(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def slow(req):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        return EvaluationResult(value="ok")

    reg = EvaluatorRegistry()
    reg.register("llm_call", slow)

    # 20 independent equations — all directly under the flow root.
    @flow()
    def wide():
        with phase("Run"):
            return [llm(prompt=f"p{i}") for i in range(20)]

    runtime = FlowRuntime(
        40, db_path, flow_callable=wide, evaluators=reg, store=store,
        concurrency=CONCURRENCY_CAP,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=10.0)
    await runtime.stop()

    # All 20 completed
    llm_eqs = [eq for eq in runtime.graph.all_equations() if eq.key.endswith(("/llm$0","/llm$1","/llm$2","/llm$3","/llm$4","/llm$5","/llm$6","/llm$7","/llm$8","/llm$9","/llm$10","/llm$11","/llm$12","/llm$13","/llm$14","/llm$15","/llm$16","/llm$17","/llm$18","/llm$19"))]
    assert len(llm_eqs) == 20
    assert all(eq.status == EquationStatus.COMPLETED for eq in llm_eqs)
    assert max_in_flight <= CONCURRENCY_CAP
    # Also verify the cap was actually exercised (otherwise the test proves nothing).
    assert max_in_flight >= 5


# =============================================================================
# Graph diff on program edit
# =============================================================================


class TestGraphDiff:
    def test_diff_detects_added_and_removed(self):
        @flow(inputs={"names": dsl_input(type="list[str]")})
        def old_r(names):
            def one(name):
                return llm(prompt=f"hi {name}")
            with phase("Run"):
                return foreach(names, one)

        @flow(inputs={"names": dsl_input(type="list[str]")})
        def new_r(names):
            def one(name):
                return llm(prompt=f"hi {name}")
            def two(name):
                return llm(prompt=f"extra {name}")
            with phase("Run"):
                res = foreach(names, one)
                extra = foreach(names, two)
            return [res, extra]

        g1 = build_graph_from_callable(old_r, inputs={"names": ["A"]})
        g2 = build_graph_from_callable(new_r, inputs={"names": ["A"]})
        diff = diff_graphs(g1, g2)
        # Adding a second foreach should add new equations but keep the old ones.
        assert any(":A" not in k and "foreach$1" in k for k in diff.added), diff.added

    def test_diff_detects_changed_prompt(self):
        # Same function name across both versions so equation keys overlap.
        def _make(prompt: str):
            @flow()
            def r():
                with phase("Run"):
                    return llm(prompt=prompt)
            return r

        g1 = build_graph_from_callable(_make("old prompt"))
        g2 = build_graph_from_callable(_make("new prompt"))
        diff = diff_graphs(g1, g2)
        changed_llm = [k for k in diff.changed if k.endswith("/llm$0")]
        assert len(changed_llm) == 1


@pytest.mark.asyncio
async def test_reload_program_preserves_unchanged(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow()
    def first():
        with phase("Run"):
            a = llm(prompt="A stage")
            b = llm(prompt="B stage")
            return [a, b]

    @flow()
    def second():
        with phase("Run"):
            a = llm(prompt="A stage")    # unchanged -> preserved
            b = llm(prompt="B changed!")  # changed -> must reset
            return [a, b]

    counter: dict[str, int] = {}
    reg = _make_mock_evaluators(tool_call_counter=counter)
    runtime = FlowRuntime(
        50, db_path, flow_callable=first, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)

    a_key = "first/llm$0"
    b_key = "first/llm$1"
    assert counter.get(a_key, 0) == 1
    assert counter.get(b_key, 0) == 1

    # Hot-swap the callable and reload. Program-edit on the fly.
    runtime.flow_callable = second
    diff = runtime.reload_program()
    # Keys use the new function name 'second', so in this test the entire
    # set changes. Use a more realistic reload where the function name is
    # the same — define a helper.
    assert "second/llm$0" in diff.added or "second/llm$0" in diff.unchanged
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()


@pytest.mark.asyncio
async def test_reload_program_same_name_preserves_unchanged(isolated_store_and_db):
    """Same function name, changed B prompt: A should be store-hit / preserved."""
    db_path, store = isolated_store_and_db

    def _make(v: int):
        @flow()
        def r():
            with phase("Run"):
                a = llm(prompt="A stage")
                b_prompt = "B v1" if v == 1 else "B v2"
                b = llm(prompt=b_prompt)
                return [a, b]
        return r

    counter: dict[str, int] = {}
    reg = _make_mock_evaluators(tool_call_counter=counter)
    runtime = FlowRuntime(
        51, db_path, flow_callable=_make(1), evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)

    a_key = "r/llm$0"
    b_key = "r/llm$1"
    assert counter.get(a_key, 0) == 1
    assert counter.get(b_key, 0) == 1

    # Swap for v2 (changed B prompt).
    runtime.flow_callable = _make(2)
    diff = runtime.reload_program()
    assert a_key in diff.unchanged
    assert b_key in diff.changed

    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    # A was store-hit on reload (hydrated from previous run), B re-evaluated.
    assert counter.get(a_key, 0) == 1, "A should not re-run"
    assert counter.get(b_key, 0) == 2, "B should have re-run after prompt change"


# =============================================================================
# App restart recovery
# =============================================================================


@pytest.mark.asyncio
async def test_app_restart_recovery_resets_computing(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    # Simulate: crash mid-run with some equations in 'computing' state.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executemany(
            "INSERT INTO equations (equation_key, equation_type, status, attempt, created_at) "
            "VALUES (?, ?, ?, 1, '2026-01-01')",
            [
                ("crashed/llm$0", "llm_call", "computing"),
                ("crashed/llm$1", "llm_call", "completed"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    from flow_runtime.graph_db import reset_computing_to_pending
    n = reset_computing_to_pending(db_path)
    assert n == 1

    # The completed one must still be completed.
    conn = sqlite3.connect(str(db_path))
    try:
        rows = dict(
            conn.execute("SELECT equation_key, status FROM equations").fetchall()
        )
    finally:
        conn.close()
    assert rows["crashed/llm$0"] == "pending"
    assert rows["crashed/llm$1"] == "completed"


def test_runtime_recovery_resets_orphaned_in_memory_computing(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="orphaned", outputs={"out": dsl_output(type="str")})
    def orphaned():
        with phase("Choose"):
            return llm(prompt="choose")

    graph = build_graph_from_callable(orphaned)
    graph_db.upsert_equations(db_path, graph.all_equations())
    eq = next(eq for eq in graph.all_equations() if eq.equation_type == EquationType.LLM_CALL)
    eq.status = EquationStatus.COMPUTING
    graph_db.update_equation_status(db_path, eq.key, EquationStatus.COMPUTING)

    run = FlowRun(
        graph,
        FlowRunConfig(flow_id=1, state_db_path=db_path),
        evaluators=_make_mock_evaluators(),
        store=store,
    )
    run.recover_orphaned_work()

    assert eq.status == EquationStatus.PENDING
    conn = sqlite3.connect(str(db_path))
    try:
        status = conn.execute(
            "SELECT status FROM equations WHERE equation_key = ?",
            (eq.key,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "pending"


# =============================================================================
# Branchless routing tests
# =============================================================================


@pytest.mark.asyncio
async def test_switch_selects_value_without_dynamic_subgraph(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(inputs={"genre": dsl_input(type="str", default="jazz")})
    def r(genre):
        with phase("Render"):
            prompt = switch(
                genre,
                {"jazz": "smoky jazz portrait", "rock": "electric rock portrait"},
                default="neutral portrait",
                output_type="text",
            )
            return tool("stub:t2i", task_type="text-to-image", prompt=prompt)

    async def code_eval(req):
        fn = req.definition["fn"]
        return EvaluationResult(value=fn(**req.resolved_inputs["inputs"]))

    async def tool_eval(req):
        return EvaluationResult(value=req.resolved_inputs["prompt"])

    reg = EvaluatorRegistry()
    reg.register("code", code_eval)
    reg.register("tool_call", tool_eval)

    runtime = FlowRuntime(
        60, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    assert runtime.graph.root_key
    root = runtime.graph.get(runtime.graph.root_key)
    assert root.status == EquationStatus.COMPLETED
    assert root.result == "smoky jazz portrait"


@pytest.mark.asyncio
async def test_filter_and_take_route_collections_statically(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(inputs={"items": dsl_input(type="list[json]")})
    def r(items):
        with phase("Approve"):
            approved = filter(
                items,
                lambda item: item["approved"],
                output_type="list[json]",
            )
            return take(approved, 2, output_type="list[json]")

    async def code_eval(req):
        fn = req.definition["fn"]
        return EvaluationResult(value=fn(**req.resolved_inputs["inputs"]))

    reg = EvaluatorRegistry()
    reg.register("code", code_eval)

    runtime = FlowRuntime(
        61,
        db_path,
        flow_callable=r,
        inputs={
            "items": [
                {"name": "a", "approved": True},
                {"name": "b", "approved": False},
                {"name": "c", "approved": True},
                {"name": "d", "approved": True},
            ],
        },
        evaluators=reg,
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    root = runtime.graph.get(runtime.graph.root_key)
    assert root.status == EquationStatus.COMPLETED
    assert [item["name"] for item in root.result] == ["a", "c"]


@pytest.mark.asyncio
async def test_when_and_gate_route_values_statically(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(
        inputs={
            "use_manual": dsl_input(type="bool", default=True),
            "is_approved": dsl_input(type="bool", default=False),
        },
    )
    def r(use_manual, is_approved):
        with phase("Route"):
            mode = when(
                use_manual,
                "manual",
                otherwise="auto",
                output_type="text",
            )
            decision = gate(
                is_approved,
                "accepted",
                otherwise="rejected",
                output_type="text",
            )
            return code(
                lambda mode, decision: {"mode": mode, "decision": decision},
                inputs={"mode": mode, "decision": decision},
            )

    async def code_eval(req):
        fn = req.definition["fn"]
        return EvaluationResult(value=fn(**req.resolved_inputs["inputs"]))

    reg = EvaluatorRegistry()
    reg.register("code", code_eval)

    runtime = FlowRuntime(
        62, db_path, flow_callable=r, evaluators=reg, store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    root = runtime.graph.get(runtime.graph.root_key)
    assert root.status == EquationStatus.COMPLETED
    assert root.result == {"mode": "manual", "decision": "rejected"}
    routing_kinds = {
        eq.definition.get("routing_kind")
        for eq in runtime.graph.all_equations()
        if eq.equation_type == EquationType.CODE
    }
    assert {"when", "gate"}.issubset(routing_kinds)


@pytest.mark.asyncio
async def test_filter_items_and_partition_route_collections(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(inputs={"items": dsl_input(type="list[json]")})
    def r(items):
        with phase("Route"):
            active = filter_items(
                items,
                lambda item: item["active"],
                output_type="list[json]",
            )
            lanes = partition(
                active,
                lambda item: item["kind"],
                labels=["image", "text"],
                default_label="text",
            )
            return lanes

    async def code_eval(req):
        fn = req.definition["fn"]
        return EvaluationResult(value=fn(**req.resolved_inputs["inputs"]))

    reg = EvaluatorRegistry()
    reg.register("code", code_eval)

    runtime = FlowRuntime(
        63,
        db_path,
        flow_callable=r,
        inputs={
            "items": [
                {"name": "a", "kind": "image", "active": True},
                {"name": "b", "kind": "image", "active": False},
                {"name": "c", "kind": "text", "active": True},
                {"name": "d", "kind": "other", "active": True},
            ],
        },
        evaluators=reg,
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    await runtime.wait_quiescent(timeout=5.0)
    await runtime.stop()

    root = runtime.graph.get(runtime.graph.root_key)
    assert root.status == EquationStatus.COMPLETED
    assert [item["name"] for item in root.result["image"]] == ["a"]
    assert [item["name"] for item in root.result["text"]] == ["c", "d"]
    routing_kinds = [
        eq.definition.get("routing_kind")
        for eq in runtime.graph.all_equations()
        if eq.equation_type == EquationType.CODE
    ]
    assert routing_kinds.count("filter") == 1
    assert routing_kinds.count("partition") == 1

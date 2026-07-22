"""Integration tests for llm(n=N) — seed-planned diverse LLM generation with
per-slot expansion and invalidation.

Covers:

- Build-time shape: one LLM_BATCH equation + N LLM_SLOT equations keyed
  `{batch.key}/slot:{i}` with positional iteration keys, plus one hidden
  llm_gather control equation assembling the final list.
- First-run: the batch evaluator makes one fast seed-planning call; each
  slot then expands its seed with its own LLM call (N+1 calls total),
  completing incrementally and failing in isolation.
- Seed miscounts never fail the batch: short lists pad with None and the
  seedless slots still expand.
- Per-slot invalidation: slot attempt > 1 triggers peer-aware solo-gen.
  Only the invalidated slot re-rolls; peers unchanged.
- Batch invalidation: cascade resets slot attempts to 1 so slots re-expand
  from the fresh seeds.
- Foreach over llm(n=N) iterates per-slot: each iteration depends on its
  specific slot equation (via early-expansion), so invalidating one slot
  only re-fires that iteration's downstream.

The LLM is mocked so the tests are hermetic.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest

from flow_runtime import (
    EquationStatus,
    EquationType,
    EquationStore,
    EvaluationRequest,
    EvaluationResult,
    EvaluatorRegistry,
    FlowRuntime,
    create_flow_state_db,
)
from flow_runtime.dsl import (
    foreach,
    llm,
    phase,
    flow,
    tool,
)
from flow_runtime.production_evaluators import (
    LLMBatchEvaluator,
    LLMSlotEvaluator,
)


# =============================================================================
# Fixtures + helpers
# =============================================================================


@pytest.fixture
def isolated_store_and_db():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "state.db"
        create_flow_state_db(db_path)
        store = EquationStore(root / "store")
        store.initialize()
        yield db_path, store


class MockLLMCompletion:
    """A callable mock that tracks every call and returns scripted responses.

    Three call kinds, decided by prompt contents:

    - Seed-planning (batch): prompt contains "numbered list" from the seed
      instruction. Returns the next ``seed_lists`` entry as a numbered list.
    - Expansion (slot attempt 1): prompt contains "You are producing item".
      Slots run in parallel with nondeterministic order, so the response is
      derived from the seed named in the prompt — ``{"prompt": "X-<seed>"}``
      where the batch number ``X`` counts seed calls so far (so re-expanded
      slots after a batch re-roll are distinguishable). Seedless expansions
      (padded None seeds) derive from the slot index line instead.
    - Solo-gen (slot attempt > 1): prompt contains "already exist". Returns
      a 1-item JSON array of the next ``solo_values``.
    """

    def __init__(
        self,
        seed_lists: list[list[str]],
        solo_values: list[Any] | None = None,
        fail_expansion_seeds: set[str] | None = None,
    ) -> None:
        self.seed_lists = list(seed_lists)
        self.solo_values = list(solo_values or [])
        self.fail_expansion_seeds = set(fail_expansion_seeds or ())
        self.seed_calls = 0
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config, messages, **kwargs):
        import json
        import re as _re

        user = messages[-1]["content"]
        if isinstance(user, list):
            text = user[0]["text"]
        else:
            text = user
        self.calls.append({"text": text, "messages": list(messages)})

        if "already exist" in text:
            if not self.solo_values:
                raise AssertionError("mock ran out of solo_values")
            val = self.solo_values.pop(0)
            return _Resp(json.dumps([val]))

        if "You are producing item" in text:
            m = _re.search(r"direction for your item: (\S+)", text, _re.IGNORECASE)
            if m:
                seed = m.group(1)
            else:
                # Seedless (padded) expansion — key off the item index.
                idx = _re.search(r"item (\d+) of", text).group(1)
                seed = f"noseed{idx}"
            if seed in self.fail_expansion_seeds:
                raise RuntimeError(f"scripted expansion failure for {seed}")
            return _Resp(json.dumps([{"prompt": f"{self.seed_calls}-{seed}"}]))

        # Seed-planning call.
        if not self.seed_lists:
            raise AssertionError("mock ran out of seed_lists")
        seeds = self.seed_lists.pop(0)
        self.seed_calls += 1
        return _Resp("\n".join(f"{i + 1}. {s}" for i, s in enumerate(seeds)))


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


async def _resolve_config(role: str) -> Any:
    return {"role": role}


def _make_n_evaluators(mock: MockLLMCompletion) -> EvaluatorRegistry:
    reg = EvaluatorRegistry()
    reg.register(
        "llm_batch",
        LLMBatchEvaluator(completion=mock, resolve_config=_resolve_config),
    )
    reg.register(
        "llm_slot",
        LLMSlotEvaluator(completion=mock, resolve_config=_resolve_config),
    )
    # tool_call stub for the foreach-downstream test.
    async def tool_eval(req: EvaluationRequest) -> EvaluationResult:
        prompt = req.resolved_inputs.get("prompt", "")
        return EvaluationResult(value=f"img({prompt})")
    reg.register("tool_call", tool_eval)
    return reg


# =============================================================================
# Build-time shape
# =============================================================================


def test_llm_n_builds_batch_plus_slot_equations(isolated_store_and_db):
    db_path, store = isolated_store_and_db

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Generate 3 diverse image prompts.",
                n=3,
                response_format={"schema": {"prompt": "str"}},
            )
        return prompts

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=EvaluatorRegistry(), store=store,
    )
    rt.build_initial_graph()

    batches = [
        eq for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_BATCH
    ]
    slots = [
        eq for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    ]
    gathers = [
        eq for eq in rt.graph.all_equations()
        if eq.definition.get("control_kind") == "llm_gather"
    ]
    assert len(batches) == 1, f"expected 1 batch, got {len(batches)}"
    assert len(slots) == 3, f"expected 3 slots, got {len(slots)}"
    assert len(gathers) == 1, f"expected 1 gather, got {len(gathers)}"

    batch = batches[0]
    assert batch.definition["n"] == 3
    assert getattr(batch, "_iteration_keys_cache", None) == ["0", "1", "2"]

    for slot in slots:
        assert slot.dependencies == [batch.key]
        assert slot.definition["control_kind"] == "llm_slot"
        assert slot.definition["batch_key"] == batch.key
        assert 0 <= slot.definition["slot_index"] < 3
        # Slot key format: {batch.key}/slot:{i}
        assert slot.key == f"{batch.key}/slot:{slot.definition['slot_index']}"

    gather = gathers[0]
    assert gather.key == f"{batch.key}/gather"
    assert sorted(gather.dependencies) == sorted(s.key for s in slots)
    assert getattr(gather, "_iteration_keys_cache", None) == ["0", "1", "2"]


# =============================================================================
# First-run end-to-end
# =============================================================================


@pytest.mark.asyncio
async def test_first_run_seed_call_plus_per_slot_expansions(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(seed_lists=[["A", "B", "C"]])

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Give 3 items.",
                n=3,
                response_format={"schema": {"prompt": "str"}},
            )
        return prompts

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=_make_n_evaluators(mock), store=store,
    )
    rt.build_initial_graph()
    await rt.start()
    await rt.wait_quiescent(timeout=5.0)
    await rt.stop()

    # 1 seed-planning call + 3 per-slot expansion calls, no solo-gens.
    assert len(mock.calls) == 4
    assert all("already exist" not in c["text"] for c in mock.calls)
    expansions = [c for c in mock.calls if "You are producing item" in c["text"]]
    assert len(expansions) == 3

    # Batch + all slots + gather COMPLETED.
    by_type: dict[EquationType, list] = {}
    for eq in rt.graph.all_equations():
        by_type.setdefault(eq.equation_type, []).append(eq)
        assert eq.status == EquationStatus.COMPLETED, (eq.key, eq.status)

    slots = sorted(
        by_type[EquationType.LLM_SLOT], key=lambda e: e.definition["slot_index"]
    )
    assert slots[0].result == {"prompt": "1-A"}
    assert slots[1].result == {"prompt": "1-B"}
    assert slots[2].result == {"prompt": "1-C"}

    # The hidden gather assembled the slots' values in order.
    gather = next(
        eq for eq in rt.graph.all_equations()
        if eq.definition.get("control_kind") == "llm_gather"
    )
    assert gather.result == [
        {"prompt": "1-A"}, {"prompt": "1-B"}, {"prompt": "1-C"},
    ]


@pytest.mark.asyncio
async def test_seed_shortfall_pads_and_still_completes(isolated_store_and_db):
    """A miscounted seed list (2 of 3) must not fail the batch — the
    seedless slot expands without a direction and the run completes."""
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(seed_lists=[["A", "B"]])

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Give 3 items.",
                n=3,
                response_format={"schema": {"prompt": "str"}},
            )
        return prompts

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=_make_n_evaluators(mock), store=store,
    )
    rt.build_initial_graph()
    await rt.start()
    await rt.wait_quiescent(timeout=5.0)
    await rt.stop()

    for eq in rt.graph.all_equations():
        assert eq.status == EquationStatus.COMPLETED, (eq.key, eq.status)

    by_index = {
        eq.definition["slot_index"]: eq
        for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    }
    assert by_index[0].result == {"prompt": "1-A"}
    assert by_index[1].result == {"prompt": "1-B"}
    # Slot 2 had no seed (padded None) but still produced an item.
    assert by_index[2].result == {"prompt": "1-noseed3"}


@pytest.mark.asyncio
async def test_expansion_failure_is_isolated_to_its_slot(isolated_store_and_db):
    """One slot's expansion call failing must not take down its peers."""
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        seed_lists=[["A", "B", "C"]],
        fail_expansion_seeds={"B"},
    )

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Give 3 items.",
                n=3,
                response_format={"schema": {"prompt": "str"}},
            )
        return prompts

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=_make_n_evaluators(mock), store=store,
    )
    rt.build_initial_graph()
    await rt.start()
    await rt.wait_quiescent(timeout=5.0)
    await rt.stop()

    by_index = {
        eq.definition["slot_index"]: eq
        for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    }
    assert by_index[0].status == EquationStatus.COMPLETED
    assert by_index[0].result == {"prompt": "1-A"}
    assert by_index[1].status == EquationStatus.FAILED
    assert by_index[2].status == EquationStatus.COMPLETED
    assert by_index[2].result == {"prompt": "1-C"}


# =============================================================================
# Per-slot invalidation triggers peer-aware solo-gen
# =============================================================================


@pytest.mark.asyncio
async def test_slot_invalidation_solo_gens_only_that_slot(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        seed_lists=[["A", "B", "C"]],
        solo_values=[{"prompt": "B-NEW"}],
    )

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Give 3.",
                n=3,
                response_format={"schema": {"prompt": "str"}},
            )
        return prompts

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=_make_n_evaluators(mock), store=store,
    )
    rt.build_initial_graph()
    await rt.start()
    await rt.wait_quiescent(timeout=5.0)

    # Find slot 1 and invalidate it.
    slot_keys = sorted(
        eq.key for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    )
    target = slot_keys[1]  # slot:1
    rt.run.invalidate(target)
    await rt.wait_quiescent(timeout=5.0)
    await rt.stop()

    # 5 calls total: 1 seed + 3 expansions + 1 solo-gen.
    assert len(mock.calls) == 5
    assert "already exist" in mock.calls[4]["text"]
    # Peer context in the solo-gen prompt references peers' current values.
    assert "1-A" in mock.calls[4]["text"]
    assert "1-C" in mock.calls[4]["text"]

    # Slot 0 and 2 unchanged; slot 1 has the new value.
    by_index = {
        eq.definition["slot_index"]: eq
        for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    }
    assert by_index[0].result == {"prompt": "1-A"}
    assert by_index[1].result == {"prompt": "B-NEW"}
    assert by_index[2].result == {"prompt": "1-C"}

    # The gather reflects the re-rolled slot, so direct consumers see it.
    gather = next(
        eq for eq in rt.graph.all_equations()
        if eq.definition.get("control_kind") == "llm_gather"
    )
    assert gather.result == [
        {"prompt": "1-A"}, {"prompt": "B-NEW"}, {"prompt": "1-C"},
    ]


# =============================================================================
# Batch invalidation cascades + resets slot attempts
# =============================================================================


@pytest.mark.asyncio
async def test_batch_invalidation_rerolls_all_slots(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        seed_lists=[["A", "B", "C"], ["A", "B", "C"]],
    )

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Give 3.",
                n=3,
                response_format={"schema": {"prompt": "str"}},
            )
        return prompts

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=_make_n_evaluators(mock), store=store,
    )
    rt.build_initial_graph()
    await rt.start()
    await rt.wait_quiescent(timeout=5.0)

    batch_key = next(
        eq.key for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_BATCH
    )
    rt.run.invalidate(batch_key)
    await rt.wait_quiescent(timeout=5.0)
    await rt.stop()

    # 8 calls: (1 seed + 3 expansions) × 2, no solo-gens — because
    # cascade-reset put slot attempts back at 1 so they re-expand from the
    # fresh seeds.
    assert len(mock.calls) == 8
    assert all("already exist" not in c["text"] for c in mock.calls)

    by_index = {
        eq.definition["slot_index"]: eq
        for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    }
    # "2-" prefix = expanded after the second seed call.
    assert by_index[0].result == {"prompt": "2-A"}
    assert by_index[1].result == {"prompt": "2-B"}
    assert by_index[2].result == {"prompt": "2-C"}
    # All slot attempts should be back at 1.
    for eq in by_index.values():
        assert eq.attempt == 1, (eq.key, eq.attempt)


# =============================================================================
# Foreach over llm(n=N) — early expansion iterates per-slot
# =============================================================================


@pytest.mark.asyncio
async def test_foreach_over_llm_n_iterates_per_slot(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        seed_lists=[["P0", "P1"]],
        solo_values=[{"prompt": "P0-NEW"}],
    )

    @flow(name="r")
    def r():
        with phase("Generate"):
            prompts = llm(
                "Give 2.",
                n=2,
                response_format={"schema": {"prompt": "str"}},
            )
        with phase("Images"):
            return foreach(
                prompts,
                lambda p: tool("flux:text-to-image", task_type="text-to-image", prompt=p),
            )

    rt = FlowRuntime(
        1, db_path, flow_callable=r,
        evaluators=_make_n_evaluators(mock), store=store,
    )
    rt.build_initial_graph()
    await rt.start()
    await rt.wait_quiescent(timeout=5.0)

    # Two downstream tool calls — one per slot.
    tool_eqs = [
        eq for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.TOOL_CALL
    ]
    assert len(tool_eqs) == 2
    for eq in tool_eqs:
        assert eq.status == EquationStatus.COMPLETED
        # Each tool eq's dependencies should include its specific slot
        # (via foreach early-expansion).
        slot_deps = [
            d for d in eq.dependencies
            if rt.graph.try_get(d) is not None
            and rt.graph.get(d).equation_type == EquationType.LLM_SLOT
        ]
        assert len(slot_deps) == 1

    # Invalidate slot 0 — only its downstream tool call should re-fire.
    slot_0 = next(
        eq for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
        and eq.definition["slot_index"] == 0
    )
    before_tool_results = {
        eq.key: eq.result for eq in tool_eqs
    }
    rt.run.invalidate(slot_0.key)
    await rt.wait_quiescent(timeout=5.0)
    await rt.stop()

    # The slot and its dependent tool re-completed with new values.
    after_tool_results = {
        eq.key: eq.result for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.TOOL_CALL
    }
    changed_tools = [
        k for k, v in after_tool_results.items()
        if before_tool_results.get(k) != v
    ]
    unchanged_tools = [
        k for k, v in after_tool_results.items()
        if before_tool_results.get(k) == v
    ]
    assert len(changed_tools) == 1, (before_tool_results, after_tool_results)
    assert len(unchanged_tools) == 1


# =============================================================================
# Batch timeout scaling (llm(n=N) is one call whose output grows with N)
# =============================================================================


from flow_runtime.production_evaluators import (  # noqa: E402
    LLM_BATCH_TIMEOUT_MAX_SECONDS,
    LLM_CALL_TIMEOUT_SECONDS,
    llm_batch_timeout_seconds,
)


def test_batch_timeout_scales_with_n():
    # n=1 is a single item — no more time than a plain llm() call.
    assert llm_batch_timeout_seconds(1) == LLM_CALL_TIMEOUT_SECONDS
    # A 50-item batch (the case that hung at 0/50) gets substantially more.
    assert llm_batch_timeout_seconds(50) > LLM_CALL_TIMEOUT_SECONDS
    assert llm_batch_timeout_seconds(10) < llm_batch_timeout_seconds(50)
    # But never more than the hard ceiling, so a runaway batch still fails
    # in bounded time.
    assert llm_batch_timeout_seconds(100_000) == LLM_BATCH_TIMEOUT_MAX_SECONDS


@pytest.mark.asyncio
async def test_batch_call_passes_scaled_timeout(monkeypatch):
    """The batch evaluator wraps its LLM call in the N-scaled timeout, not
    the flat 60s cap that made llm(n=50) time out every attempt."""
    import json

    captured: dict[str, Any] = {}
    real_wait_for = asyncio.wait_for

    async def spy_wait_for(aw, timeout):
        captured["timeout"] = timeout
        return await real_wait_for(aw, timeout)

    monkeypatch.setattr(
        "flow_runtime.production_evaluators.asyncio.wait_for", spy_wait_for
    )

    async def completion(config, messages, **kwargs):
        return _Resp(json.dumps([{"prompt": f"p{i}"} for i in range(50)]))

    ev = LLMBatchEvaluator(completion=completion, resolve_config=_resolve_config)
    req = EvaluationRequest(
        equation_key="r/llm$0",
        equation_type="llm_batch",
        attempt=1,
        definition={
            "n": 50,
            "prompt_template": "give 50",
            "response_format": {"schema": {"prompt": "str"}},
        },
        resolved_inputs={},
    )

    await ev(req)

    assert captured["timeout"] == llm_batch_timeout_seconds(50)
    assert captured["timeout"] > LLM_CALL_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_batch_timeout_is_single_retry_not_transient(monkeypatch):
    """A size-driven batch timeout surfaces as LLM_ERROR (one retry), not
    TRANSIENT (three) — re-running the identical oversized call won't help."""
    from flow_runtime.evaluators import EvaluatorError, LLM_ERROR

    # Shrink the budget so the test doesn't actually wait.
    monkeypatch.setattr(
        "flow_runtime.production_evaluators.LLM_CALL_TIMEOUT_SECONDS", 0.05
    )
    monkeypatch.setattr(
        "flow_runtime.production_evaluators.LLM_BATCH_TIMEOUT_PER_ITEM_SECONDS", 0.0
    )

    async def slow_completion(config, messages, **kwargs):
        await asyncio.sleep(5.0)
        return _Resp("[]")

    ev = LLMBatchEvaluator(
        completion=slow_completion, resolve_config=_resolve_config
    )
    req = EvaluationRequest(
        equation_key="r/llm$0",
        equation_type="llm_batch",
        attempt=1,
        definition={"n": 3, "prompt_template": "x", "response_format": None},
        resolved_inputs={},
    )

    with pytest.raises(EvaluatorError) as excinfo:
        await ev(req)

    assert excinfo.value.category == LLM_ERROR
    assert "timed out" in str(excinfo.value)

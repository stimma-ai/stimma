"""Integration tests for llm(n=N) — batched diverse LLM generation with
per-slot invalidation.

Covers:

- Build-time shape: one LLM_BATCH equation + N LLM_SLOT equations keyed
  `{batch.key}/slot:{i}` with positional iteration keys.
- First-run: batch evaluator fires once, slots copy from the batch list.
  Exactly one LLM call is issued for N slots.
- Per-slot invalidation: slot attempt > 1 triggers peer-aware solo-gen.
  Only the invalidated slot re-rolls; peers unchanged.
- Batch invalidation: cascade resets slot attempts to 1 so slots re-copy
  from the fresh batch.
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

    Supports two modes per call, decided by prompt contents:

    - Batch: if "already exist" is NOT in the prompt, returns a JSON array
      of ``batch_values`` items. Each call can return a different list so
      tests can verify fresh batches after invalidation.
    - Solo-gen: if "already exist" IS in the prompt, returns a 1-item JSON
      array of the next ``solo_values``.
    """

    def __init__(
        self,
        batch_lists: list[list[Any]],
        solo_values: list[Any],
    ) -> None:
        self.batch_lists = list(batch_lists)
        self.solo_values = list(solo_values)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, config, messages, **kwargs):
        user = messages[-1]["content"]
        if isinstance(user, list):
            text = user[0]["text"]
        else:
            text = user
        self.calls.append({"text": text, "messages": list(messages)})
        is_solo = "already exist" in text
        if is_solo:
            if not self.solo_values:
                raise AssertionError("mock ran out of solo_values")
            val = self.solo_values.pop(0)
            import json
            return _Resp(json.dumps([val]))
        if not self.batch_lists:
            raise AssertionError("mock ran out of batch_lists")
        items = self.batch_lists.pop(0)
        import json
        return _Resp(json.dumps(items))


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
    assert len(batches) == 1, f"expected 1 batch, got {len(batches)}"
    assert len(slots) == 3, f"expected 3 slots, got {len(slots)}"

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


# =============================================================================
# First-run end-to-end
# =============================================================================


@pytest.mark.asyncio
async def test_first_run_one_llm_call_fills_all_slots(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        batch_lists=[[{"prompt": "A"}, {"prompt": "B"}, {"prompt": "C"}]],
        solo_values=[],
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

    # Exactly one LLM call was made (batch-only — no solo-gens on first run).
    assert len(mock.calls) == 1
    assert "already exist" not in mock.calls[0]["text"]

    # Batch + all slots COMPLETED.
    by_type: dict[EquationType, list] = {}
    for eq in rt.graph.all_equations():
        by_type.setdefault(eq.equation_type, []).append(eq)
        assert eq.status == EquationStatus.COMPLETED, (eq.key, eq.status)

    slots = sorted(
        by_type[EquationType.LLM_SLOT], key=lambda e: e.definition["slot_index"]
    )
    assert slots[0].result == {"prompt": "A"}
    assert slots[1].result == {"prompt": "B"}
    assert slots[2].result == {"prompt": "C"}


# =============================================================================
# Per-slot invalidation triggers peer-aware solo-gen
# =============================================================================


@pytest.mark.asyncio
async def test_slot_invalidation_solo_gens_only_that_slot(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        batch_lists=[[{"prompt": "A"}, {"prompt": "B"}, {"prompt": "C"}]],
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

    # 2 calls total: 1 batch + 1 solo-gen.
    assert len(mock.calls) == 2
    assert "already exist" in mock.calls[1]["text"]
    # Peer context in the solo-gen prompt references peers A and C.
    assert "A" in mock.calls[1]["text"]
    assert "C" in mock.calls[1]["text"]

    # Slot 0 and 2 unchanged; slot 1 has the new value.
    by_index = {
        eq.definition["slot_index"]: eq
        for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    }
    assert by_index[0].result == {"prompt": "A"}
    assert by_index[1].result == {"prompt": "B-NEW"}
    assert by_index[2].result == {"prompt": "C"}


# =============================================================================
# Batch invalidation cascades + resets slot attempts
# =============================================================================


@pytest.mark.asyncio
async def test_batch_invalidation_rerolls_all_slots(isolated_store_and_db):
    db_path, store = isolated_store_and_db
    mock = MockLLMCompletion(
        batch_lists=[
            [{"prompt": "A1"}, {"prompt": "B1"}, {"prompt": "C1"}],
            [{"prompt": "A2"}, {"prompt": "B2"}, {"prompt": "C2"}],
        ],
        solo_values=[],
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

    # Exactly 2 batch LLM calls, no solo-gens — because cascade-reset put
    # slot attempts back at 1 so they take from the fresh batch.
    assert len(mock.calls) == 2
    assert all("already exist" not in c["text"] for c in mock.calls)

    by_index = {
        eq.definition["slot_index"]: eq
        for eq in rt.graph.all_equations()
        if eq.equation_type == EquationType.LLM_SLOT
    }
    assert by_index[0].result == {"prompt": "A2"}
    assert by_index[1].result == {"prompt": "B2"}
    assert by_index[2].result == {"prompt": "C2"}
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
        batch_lists=[[{"prompt": "P0"}, {"prompt": "P1"}]],
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

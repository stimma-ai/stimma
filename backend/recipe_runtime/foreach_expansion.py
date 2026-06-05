"""Foreach / hitl.approve expansion — runtime-agnostic core.

The DSL records a ``DeferredExpansion`` for every ``foreach`` and
``hitl.approve`` call. Materializing the per-iteration sub-graph means:

  1. resolving the iteration count + per-item values (or NodeRefs in
     "early" mode);
  2. running the user callback once per item inside a ``BuildContext``
     so its DSL calls register under ``<wrapper>/<fn>:<iter_key>``;
  3. wiring the wrapper's dependencies to the resulting children.

Step (2) is pure graph construction. The two callers — the engine
scheduler (lazy expansion at evaluation time) and the loader (eager
expansion at graph-build time when the iteration count is statically
knowable) — differ only in side effects: the engine writes each row
to ``state.db`` as it goes and routes callback failures to the task
panel; the loader expands into an in-memory graph and lets the recipe
load fail loud if any callback raises.

The helpers here take an optional :class:`ExpansionPersistor`. Passing
``None`` selects build-time semantics (no DB writes, callback failures
re-raise). Passing one in selects scheduler semantics (the engine wires
in its own ``_persist_status`` / ``_finalize_failure`` / ``upsert_equations``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from recipe_dsl.context import BuildContext, activate_context, push_frame
from recipe_dsl.errors import NodeUsageError

from .graph import (
    DeferredExpansion,
    Equation,
    EquationGraph,
    EquationStatus,
    EquationType,
    NodeRef,
)
from .keys import (
    IterationKeySource,
    canonical_json_hash,
    encode_iteration_key,
    iteration_keys_for_collection,
)


class EarlyExpansionUnsupported(Exception):
    """Raised when a foreach callback can't run against NodeRef items.

    Caught by the engine's ``_try_expand_deferred``, which then flags the
    deferred as early-blocked and waits for the upstream to fully COMPLETE
    instead. Build-time eager expansion catches it the same way.
    """


@dataclass
class ExpansionPersistor:
    """Optional scheduler hooks for persisting expansion results.

    The engine wires these to ``graph_db.upsert_equations``,
    ``RecipeRun._persist_status``, and ``RecipeRun._finalize_failure``.
    Build-time eager expansion passes ``None`` — the loader persists the
    full graph in one shot afterward, and callback failures abort the load.
    """
    bulk_upsert_new: Callable[[list[Equation]], None]
    persist_wrapper_update: Callable[[Equation], None]
    finalize_failure: Callable[[Equation, str], None]


# ---------------------------------------------------------------------------
# Iteration-key derivation helpers


def iteration_keys_from_upstream(
    graph: EquationGraph, upstream: Equation,
) -> Optional[list[str]]:
    """Read iteration keys cached on upstream wrappers or derive from values."""
    cached = getattr(upstream, "_iteration_keys_cache", None)
    if cached is not None:
        return list(cached)
    kind = upstream.definition.get("control_kind")
    if kind in ("recipe_input", "literal_list"):
        element_kind = upstream.definition.get("element_kind", "")
        values = upstream.result or upstream.definition.get("values") or []
        if not values:
            return []
        if element_kind == "scalar":
            return [encode_iteration_key(v) for v in values]
        if element_kind in ("json", "dict"):
            return [encode_iteration_key(canonical_json_hash(v)) for v in values]
        return [str(i) for i in range(len(values))]
    return None


def early_expansion_items(
    graph: EquationGraph,
    deferred: DeferredExpansion,
    input_eq: Equation,
) -> tuple[list[str], list[NodeRef]]:
    """Build (iter_keys, items) for an early-mode foreach expansion.

    Each item is a NodeRef targeting the corresponding upstream iteration
    wrapper. The upstream's iteration-key cache defines order.
    """
    upstream_iter_keys = list(input_eq._iteration_keys_cache)
    prefix = f"{input_eq.key}/"
    upstream_children: dict[str, str] = {}
    for k in graph.keys():
        if not k.startswith(prefix):
            continue
        if "/" in k[len(prefix):]:
            continue
        child = graph.get(k)
        kind = child.definition.get("control_kind")
        if kind not in _ITERATION_CHILD_KINDS:
            continue
        ik = child.definition.get("iteration_key")
        if ik is not None:
            upstream_children[ik] = k

    iter_keys: list[str] = []
    items: list[NodeRef] = []
    for ik in upstream_iter_keys:
        child_key = upstream_children.get(ik)
        if child_key is None:
            raise EarlyExpansionUnsupported(
                f"upstream iteration {ik!r} not materialized yet"
            )
        iter_keys.append(ik)
        items.append(NodeRef(equation_key=child_key))
    return iter_keys, items


# Children kinds that carry an iteration_key and can serve as upstream items
# during early-mode expansion. Includes ``slot`` so a foreach can iterate over
# a hitl.approve result without waiting for the whole list to resolve.
_ITERATION_CHILD_KINDS = frozenset({"foreach_iteration", "llm_slot", "slot"})


def probe_early_callback(
    deferred: DeferredExpansion,
    items: list[NodeRef],
) -> None:
    """Dry-run the callback with a NodeRef item on a throwaway graph.

    If the callback accesses the item's value at build time (subscript,
    f-string, arithmetic), NodeRef raises NodeUsageError — we convert
    that to EarlyExpansionUnsupported so the caller can fall back to
    waiting for upstream completion. Other exceptions propagate.
    """
    if not items:
        return
    probe_graph = EquationGraph()
    probe_ctx = BuildContext(graph=probe_graph)
    with activate_context(probe_ctx):
        with push_frame(
            probe_ctx,
            parent_key=f"{deferred.owner_key}/__probe__",
            function_name=deferred.function_name,
        ):
            try:
                deferred.callback(items[0], **deferred.extra_kwargs)
            except NodeUsageError as exc:
                raise EarlyExpansionUnsupported(str(exc)) from exc


# ---------------------------------------------------------------------------
# Core expansion


def resolve_items_and_keys(
    graph: EquationGraph,
    deferred: DeferredExpansion,
    input_eq: Equation,
    *,
    mode: str,
) -> tuple[list[Any], list[str]]:
    """Compute (items, iter_keys) for a foreach expansion in either mode.

    For ``early`` mode, also probes the callback against a NodeRef item;
    raises ``EarlyExpansionUnsupported`` if the callback can't run that way.
    """
    if mode == "early":
        iter_keys, items = early_expansion_items(graph, deferred, input_eq)
        probe_early_callback(deferred, items)
        return items, iter_keys

    items = input_eq.result
    if items is None:
        raise TypeError(
            f"foreach source {input_eq.key!r} resolved to None — "
            "the upstream code() or tool() returned no value"
        )
    if not isinstance(items, list):
        raise TypeError(
            f"foreach source {input_eq.key!r} must resolve to a list; "
            f"got {type(items).__name__}"
        )

    source = deferred.iteration_key_source or IterationKeySource(
        IterationKeySource.POSITIONAL
    )
    if source.mode == IterationKeySource.INHERITED:
        upstream_keys = getattr(input_eq, "_iteration_keys_cache", None)
        if upstream_keys is None:
            upstream_keys = iteration_keys_from_upstream(graph, input_eq)
        if upstream_keys is not None and len(upstream_keys) == len(items):
            iter_keys = upstream_keys
        else:
            iter_keys = [str(i) for i in range(len(items))]
    else:
        iter_keys = iteration_keys_for_collection(items, source)
    return items, iter_keys


def find_eager_expansion(
    graph: EquationGraph, deferred: DeferredExpansion,
) -> Optional[tuple[str, list[Any], list[str]]]:
    """Decide whether ``deferred`` can be expanded at graph-build time.

    Returns ``(mode, items, iter_keys)`` for callers to feed straight into
    :func:`expand_foreach`, or ``None`` if expansion has to wait for
    runtime (upstream is a tool/code whose result list is computed live,
    upstream is a recipe input that hasn't settled, etc.).

    Eligible cases:
      - ``hitl.approve`` — input is the synthetic ``literal_list`` of slot
        indices; values are statically known.
      - ``foreach`` over a literal collection (recipe-input list, literal
        list, ``range(N)``) — values come from ``definition["values"]``.
      - ``foreach`` over a previously-expanded foreach / LLM_BATCH — the
        upstream iteration wrappers already exist in the graph, so we can
        early-expand against them. The fixed-point loop in the loader
        re-runs after each expansion so cascades unblock automatically.
    """
    if deferred.expanded or deferred.early_blocked:
        return None
    input_eq = graph.try_get(deferred.input_equation_key)
    if input_eq is None:
        return None

    # Early mode: upstream is a foreach/approve/LLM_BATCH whose iteration
    # wrappers already exist. Items are NodeRefs to those wrappers — the
    # downstream foreach iterates over them without waiting for the upstream
    # list to fully resolve.
    if (
        deferred.kind == "foreach"
        and (
            input_eq.definition.get("control_kind") in ("foreach", "approve")
            or input_eq.equation_type == EquationType.LLM_BATCH
        )
        and getattr(input_eq, "_iteration_keys_cache", None) is not None
    ):
        try:
            iter_keys, items = early_expansion_items(graph, deferred, input_eq)
            probe_early_callback(deferred, items)
        except EarlyExpansionUnsupported:
            deferred.early_blocked = True
            return None
        return "early", items, iter_keys

    # Resolved mode at build time: input is a literal_list whose values are
    # statically knowable. The engine's runtime resolved path waits for the
    # upstream's status to flip to COMPLETED; for literal collections we can
    # just read ``definition["values"]`` directly.
    if input_eq.definition.get("control_kind") == "literal_list":
        items = list(input_eq.definition.get("values", []))
        source = deferred.iteration_key_source or IterationKeySource(
            IterationKeySource.POSITIONAL
        )
        if source.mode == IterationKeySource.INHERITED:
            iter_keys = [str(i) for i in range(len(items))]
        else:
            iter_keys = iteration_keys_for_collection(items, source)
        return "resolved", items, iter_keys

    return None


def expand_foreach(
    graph: EquationGraph,
    deferred: DeferredExpansion,
    *,
    items: list[Any],
    iter_keys: list[str],
    persistor: Optional[ExpansionPersistor] = None,
) -> None:
    """Materialize the per-iteration sub-graph for a foreach/approve wrapper.

    For each item we run the callback inside a fresh BuildFrame whose
    parent_key is ``<wrapper_key>/<fn_name>:<iter_key>``. That frame is
    the one the callback's DSL calls register equations under, which
    gives the full-nested key format from RECIPES_EQUATION_KEYS §3.

    When ``persistor`` is None (build-time path), no DB writes happen and
    callback failures re-raise so the loader aborts. When supplied, every
    new equation row is upserted, the wrapper's status/deps/definition are
    persisted, and per-iteration callback failures are routed through the
    persistor's ``finalize_failure`` (which the engine wires to its task
    machinery) instead of aborting the whole expansion.
    """
    wrapper = graph.get(deferred.owner_key)

    # Cache iteration keys on the wrapper itself so downstream nested
    # foreach expansions can inherit them.
    setattr(wrapper, "_iteration_keys_cache", list(iter_keys))

    is_approve = deferred.kind == "approve"
    slot_instructions = (
        wrapper.definition.get("instructions", "") if is_approve else ""
    )
    child_kind = "slot" if is_approve else "foreach_iteration"

    build_ctx = BuildContext(graph=graph)
    with activate_context(build_ctx):
        # Outer frame mirrors the wrapper's position — we don't add
        # equations here, just use it as a parent scope.
        with push_frame(
            build_ctx,
            parent_key=wrapper.key,
            function_name=deferred.function_name,
            phase_stack=list(wrapper.phase_path),
        ):
            for iter_key, item in zip(iter_keys, items):
                child_wrapper_key = (
                    f"{wrapper.key}/{deferred.function_name}:{iter_key}"
                )
                child_wrapper = Equation(
                    key=child_wrapper_key,
                    equation_type=EquationType.CONTROL,
                    definition={
                        "control_kind": child_kind,
                        "iteration_key": iter_key,
                    },
                    dependencies=[],
                    phase_path=list(wrapper.phase_path),
                )
                graph.add_equation(child_wrapper)
                # Persist the row *now* so a callback failure has a target
                # to write to. Build-time mode has no persistor — failures
                # raise instead.
                if persistor is not None:
                    persistor.bulk_upsert_new([child_wrapper])

                # Push a frame for the callback body. DSL calls inside
                # will register under the child_wrapper_key.
                with push_frame(
                    build_ctx,
                    parent_key=child_wrapper_key,
                    function_name=deferred.function_name,
                    phase_stack=list(wrapper.phase_path),
                ):
                    try:
                        ret_node_or_value = deferred.callback(
                            item, **deferred.extra_kwargs
                        )
                    except Exception as exc:
                        if persistor is None:
                            raise
                        persistor.finalize_failure(
                            child_wrapper, f"callback error: {exc}",
                        )
                        continue

                    # hitl.approve: auto-wrap the candidate in a single-
                    # asset approval gate so each slot has a real terminal
                    # equation. The public hitl.approve is the multi-slot
                    # factory; the per-slot gate is an internal helper.
                    if is_approve and isinstance(ret_node_or_value, NodeRef):
                        from recipe_dsl.primitives import _register_per_slot_approve
                        ret_node_or_value = _register_per_slot_approve(
                            ret_node_or_value,
                            instructions=slot_instructions,
                        )

                _finalize_iteration_wrapper(
                    graph, child_wrapper, ret_node_or_value, persistor=persistor,
                )

    # After expansion, the foreach wrapper depends on all child wrappers.
    child_keys = sorted(
        k for k in graph.keys()
        if k.startswith(f"{wrapper.key}/")
        and "/" not in k[len(wrapper.key) + 1:]
    )
    graph.replace_dependencies(
        wrapper.key,
        list(set(wrapper.dependencies) | set(child_keys)),
    )
    if persistor is not None:
        persistor.persist_wrapper_update(wrapper)
        new_rows = [
            eq for eq in graph.all_equations()
            if eq.key == wrapper.key or eq.key.startswith(f"{wrapper.key}/")
        ]
        persistor.bulk_upsert_new(new_rows)


def _finalize_iteration_wrapper(
    graph: EquationGraph,
    wrapper: Equation,
    ret_node_or_value: Any,
    *,
    persistor: Optional[ExpansionPersistor] = None,
) -> None:
    """Wire dep edges and mark how to produce the result.

    If the callback returned a NodeRef, the wrapper depends on that node
    and mirrors its result at completion. If it returned a resolved
    value, complete the wrapper immediately.
    """
    if isinstance(ret_node_or_value, NodeRef):
        graph.replace_dependencies(
            wrapper.key, [ret_node_or_value.equation_key],
        )
        wrapper.definition["_result_from"] = ret_node_or_value.equation_key
        # Leave all children registered during the callback as additional
        # dependencies — their completion is required for the wrapper to
        # complete.
        child_keys = [
            eq.key for eq in graph.all_equations()
            if eq.key != wrapper.key
            and eq.key.startswith(f"{wrapper.key}/")
        ]
        graph.replace_dependencies(
            wrapper.key,
            sorted(set(wrapper.dependencies) | set(child_keys)),
        )
        # The row was inserted before the callback ran so a failure has
        # somewhere to write its error. The bulk upsert at the end of
        # expand_foreach uses INSERT OR IGNORE, so the deps and
        # `_result_from` we just computed never reach the DB without an
        # explicit UPDATE here — leaving iteration nodes orphaned in the
        # graph viz and the runtime unable to recover its result pointer
        # across restarts.
        if persistor is not None:
            persistor.persist_wrapper_update(wrapper)
    else:
        wrapper.result = ret_node_or_value
        wrapper.transition_to(EquationStatus.COMPLETED)
        if persistor is not None:
            persistor.persist_wrapper_update(wrapper)

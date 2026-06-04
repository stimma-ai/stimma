"""Graph diff — compare two EquationGraphs by equation key.

Used when program.py changes: we rebuild the new graph, diff against the
previous graph (or the state.db-persisted rows), and:

  - equations with matching keys and unchanged definition_hash keep their
    stored results and HITL decisions
  - equations with matching keys but changed definition are marked pending
  - new equations are marked pending
  - removed equations are deleted from the per-recipe state.db

This module is pure: it returns a `GraphDiff` describing the changes.
`apply_graph_diff` in engine.py / runtime.py is where side effects happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import Equation, EquationGraph


@dataclass
class GraphDiff:
    # keys present in both, definition unchanged (preserve status + result)
    unchanged: list[str] = field(default_factory=list)
    # keys present in both, definition_hash changed (reset to pending)
    changed: list[str] = field(default_factory=list)
    # keys only in the new graph
    added: list[str] = field(default_factory=list)
    # keys only in the old graph (delete from state.db)
    removed: list[str] = field(default_factory=list)


def _def_hash(eq: Equation) -> str:
    """Return the canonical definition hash for comparison.

    For computational equations we use the equation's `definition_hash`
    field. For control equations (foreach wrappers etc.) we compare a
    stable subset of the definition (kind + callback_name + sources), which
    captures structural changes that should cause a re-expansion.
    """
    d = eq.definition or {}
    if "definition_hash" in d:
        return str(d["definition_hash"])
    # Control / recipe_input equations.
    parts = [
        d.get("control_kind", ""),
        d.get("callback_name", ""),
        d.get("input_name", ""),
        repr(d.get("sources", "")),
        d.get("element_kind", ""),
        repr(d.get("values", "")),
        # Scalar recipe_input stores its value in "value" (singular). Without
        # this, changing a scalar input (product_image, num_poses) looks
        # identical to the old equation, the diff marks it unchanged, and
        # downstream stays COMPLETED with stale results.
        repr(d.get("value", "")),
        # Flipping optional=True changes whether a missing value blocks the
        # downstream graph; treat it as a definition change so the diff
        # cascades invalidation and rewrites the persisted row.
        repr(bool(d.get("optional", False))),
        # Body hash for foreach callbacks. Without this, editing a
        # tool prompt inside `foreach(range(4), lambda _: tool(...))` leaves
        # the wrapper in diff.unchanged, inheriting the old COMPLETED result
        # — downstream hitl.select reads stale candidates.
        d.get("callback_fingerprint", ""),
    ]
    return "|".join(str(p) for p in parts)


def diff_graphs(old: EquationGraph, new: EquationGraph) -> GraphDiff:
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    diff = GraphDiff()
    for key in sorted(new_keys & old_keys):
        old_eq = old.get(key)
        new_eq = new.get(key)
        if _def_hash(old_eq) == _def_hash(new_eq):
            diff.unchanged.append(key)
        else:
            diff.changed.append(key)
    diff.added = sorted(new_keys - old_keys)
    diff.removed = sorted(old_keys - new_keys)
    return diff

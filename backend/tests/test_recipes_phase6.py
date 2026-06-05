"""Phase 6 tests — denormalized pending_task_count wiring + reconciliation.

Phase 6 adds a `pending_task_count` column on the main `recipes` table so
landing cards and sidebar badges can read a single counter without
opening every per-recipe state.db. Two mechanisms keep it correct:

1. The `_broadcast` wrapper in `recipe_lifecycle` increments on
   `recipe_task_created` and decrements on `recipe_task_resolved` before
   forwarding the event.
2. `reconcile_pending_task_counts` recomputes every recipe's count from
   its state.db at startup, catching drift from any missed event (e.g.,
   an ungraceful shutdown between task insert and broadcast).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

import recipe_lifecycle
import recipe_registry
from core.profile_context import ProfileScope
from database import Recipe
from recipe_runtime import get_recipe_program_path, get_recipe_state_db_path, graph_db
from recipe_runtime.graph import Equation, EquationStatus as S, EquationType as ET


async def _make_recipe(client, name: str) -> int:
    resp = await client.post("/api/recipes", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _seed_pending_task(recipe_id: int, key: str = "r/hitl.select$0") -> int:
    """Insert a pending equation + task directly into the per-recipe state.db."""
    state_db = get_recipe_state_db_path(recipe_id)
    eq = Equation(
        key=key,
        equation_type=ET.HITL,
        definition={"hitl_type": "select"},
        dependencies=[],
    )
    eq.status = S.AWAITING_INPUT
    graph_db.insert_equation(state_db, eq)
    return graph_db.insert_task(state_db, key, "select", "pick", {"candidates": ["a"], "count": 1})


async def _count(session_maker, recipe_id: int) -> int:
    async with session_maker() as s:
        row = await s.execute(
            select(Recipe.pending_task_count).where(Recipe.id == recipe_id)
        )
        return row.scalar_one()


@pytest.mark.asyncio
async def test_pending_task_count_column_defaults_to_zero(client, db_session):
    """Fresh recipes start at zero so the UI has something valid to read."""
    rid = await _make_recipe(client, "p6-default")
    assert await _count(db_session, rid) == 0


@pytest.mark.asyncio
async def test_broadcast_created_increments_count(client, db_session):
    """recipe_task_created → counter +1, and payload carries the new count."""
    rid = await _make_recipe(client, "p6-created")
    payload = {"recipe_id": rid, "task_id": 1, "task_type": "select"}
    with ProfileScope("default"):
        await recipe_lifecycle._broadcast("recipe_task_created", payload)
    assert await _count(db_session, rid) == 1
    assert payload["pending_task_count"] == 1


@pytest.mark.asyncio
async def test_broadcast_resolved_decrements_count(client, db_session):
    """recipe_task_resolved → counter -1."""
    rid = await _make_recipe(client, "p6-resolved")
    with ProfileScope("default"):
        for i in range(2):
            await recipe_lifecycle._broadcast(
                "recipe_task_created", {"recipe_id": rid, "task_id": i},
            )
        await recipe_lifecycle._broadcast(
            "recipe_task_resolved", {"recipe_id": rid, "task_id": 0},
        )
    assert await _count(db_session, rid) == 1


@pytest.mark.asyncio
async def test_broadcast_resolved_clamps_at_zero(client, db_session):
    """An orphan resolved event (no matching created) must not go negative."""
    rid = await _make_recipe(client, "p6-clamp")
    with ProfileScope("default"):
        await recipe_lifecycle._broadcast(
            "recipe_task_resolved", {"recipe_id": rid, "task_id": 99},
        )
    assert await _count(db_session, rid) == 0


@pytest.mark.asyncio
async def test_reconcile_syncs_counts_to_state_db(client, db_session):
    """Reconciliation overwrites any drift with the authoritative task count."""
    rid_two = await _make_recipe(client, "p6-reconcile-2")
    rid_zero = await _make_recipe(client, "p6-reconcile-0")

    _seed_pending_task(rid_two, key="r/hitl.select$0")
    _seed_pending_task(rid_two, key="r/hitl.select$1")

    # Drift: overstate the denormalized counter so reconcile has to correct it.
    async with db_session() as s:
        await s.execute(
            update(Recipe).where(Recipe.id == rid_two).values(pending_task_count=99)
        )
        await s.commit()

    async with db_session() as s:
        reconciled = await recipe_lifecycle.reconcile_pending_task_counts(s)

    assert reconciled[rid_two] == 2
    assert reconciled[rid_zero] == 0
    assert await _count(db_session, rid_two) == 2
    assert await _count(db_session, rid_zero) == 0


@pytest.mark.asyncio
async def test_recover_running_recipes_restarts_scheduler(client, db_session):
    """Startup recovery should recreate runtimes for recipes marked running."""
    rid = await _make_recipe(client, "p6-recover-running")
    get_recipe_program_path(rid).write_text(
        """
from stimma.recipe import recipe

@recipe(name="recover")
def recover():
    return None
""".strip()
        + "\n",
        encoding="utf-8",
    )

    # Put the recipe into the persisted "running" state, then tear down the
    # in-memory runtime to simulate a backend restart.
    resp = await client.post(f"/api/recipes/{rid}/start")
    assert resp.status_code == 200, resp.text
    await recipe_lifecycle.stop_and_unregister(rid)
    assert recipe_registry.get_runtime(rid) is None

    async with db_session() as s:
        with ProfileScope("default"):
            recovered = await recipe_lifecycle.recover_running_recipes(s)

    assert rid in recovered
    runtime = recipe_registry.get_runtime(rid)
    assert runtime is not None
    assert runtime.run is not None
    assert runtime.run.state == "running"

    await recipe_lifecycle.stop_and_unregister(rid)

"""Production lifecycle helpers for RecipeRuntime instances.

Phase 4 closed the HITL / task API but left runtime creation implicit —
tests construct `RecipeRuntime` directly, and nothing in the production
HTTP layer spins one up. Phase 5's UI needs start / pause / resume /
invalidate, so this module gives the routes a single entry point to:

  - lazily instantiate a RecipeRuntime for a recipe_id
  - wire `ws_manager.broadcast` as the runtime's event sink
  - register / unregister with `recipe_registry`
  - tear the runtime down when stopping

The registry already caches the runtime per recipe_id (so task resolution
can find the active scheduler). We layer lifecycle on top of it.

Evaluators come from ``recipe_runtime.production_evaluators`` — the single
wiring point for the generation-queue / LLM / code-sandbox paths. Tests
still construct ``RecipeRuntime`` directly with stub evaluators, so that
seam is preserved.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select, update

import recipe_registry
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import Recipe
from database_registry import get_database_registry
from recipe_dsl.errors import ProgramLoadError
from recipe_runtime import (
    DryRunReport,
    RecipeRuntime,
    dry_run_recipe,
    get_equation_store,
    get_recipe_program_path,
    get_recipe_state_db_path,
    graph_db,
)
from recipe_runtime.production_evaluators import build_production_registry
from utils.websocket import ws_manager


log = get_logger(__name__)


# Transient cache of the most recent program-load failure per recipe. Populated
# by apply_program_edit when a rebuild raises ProgramLoadError, consumed by
# routes/recipes.py::get_phase_tree so the error surfaces on plain GETs (not
# just on the immediate recipe_updated broadcast). Cleared on any successful
# build. In-memory is fine — the error reconstructs deterministically from the
# program file, so a backend restart just needs the next edit or GET to re-raise.
_last_load_errors: dict[int, dict[str, Any]] = {}


def get_cached_load_error(recipe_id: int) -> Optional[dict[str, Any]]:
    """Return the last cached program-load error for this recipe, if any."""
    return _last_load_errors.get(recipe_id)


def clear_cached_load_error(recipe_id: int) -> None:
    _last_load_errors.pop(recipe_id, None)


def _recipe_inputs(recipe: Recipe) -> dict[str, Any]:
    if not recipe.inputs:
        return {}
    try:
        parsed = json.loads(recipe.inputs)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _apply_task_count_delta(recipe_id: int, delta: int) -> Optional[int]:
    """Apply a signed delta to recipes.pending_task_count atomically.

    Runs in whatever profile context the broadcast was fired under (the
    engine is started from a profile-scoped request, and contextvars
    propagate through loop.create_task). Returns the new count, or None
    when we couldn't resolve a DB session.

    Clamps at zero so an out-of-order resolved event can't push the
    counter negative if the corresponding created event hasn't committed
    yet. The reconciliation pass will correct any drift regardless.
    """
    try:
        profile_id = get_current_profile()
        registry = get_database_registry()
        db = registry.get_database(profile_id)
    except Exception:  # noqa: BLE001
        log.debug("task count delta skipped; no DB context", recipe_id=recipe_id)
        return None

    async with db.async_session_maker() as session:
        # UPDATE with arithmetic keeps this race-free across concurrent
        # increments. The clamp is applied after-the-fact via a second
        # read because SQLite lacks a portable GREATEST on UPDATE ... SET.
        await session.execute(
            update(Recipe)
            .where(Recipe.id == recipe_id)
            .values(pending_task_count=Recipe.pending_task_count + delta)
        )
        if delta < 0:
            # Clamp any negative value back to zero in the same tx.
            await session.execute(
                update(Recipe)
                .where(Recipe.id == recipe_id, Recipe.pending_task_count < 0)
                .values(pending_task_count=0)
            )
        await session.commit()
        result = await session.execute(
            select(Recipe.pending_task_count).where(Recipe.id == recipe_id)
        )
        return result.scalar_one_or_none()


async def _broadcast(event: str, payload: dict[str, Any]) -> None:
    # Maintain the denormalized counter before broadcasting so listeners
    # that refetch on the event see the updated number.
    recipe_id = payload.get("recipe_id") if isinstance(payload, dict) else None
    if isinstance(recipe_id, int):
        if event == "recipe_task_created":
            new_count = await _apply_task_count_delta(recipe_id, +1)
            if new_count is not None:
                payload["pending_task_count"] = new_count
        elif event == "recipe_task_resolved":
            new_count = await _apply_task_count_delta(recipe_id, -1)
            if new_count is not None:
                payload["pending_task_count"] = new_count
    await ws_manager.broadcast(event, payload)


async def reconcile_pending_task_counts(session) -> dict[int, int]:
    """Recompute pending_task_count for every non-deleted recipe.

    Reads each recipe's per-recipe state.db (the authoritative source of
    tasks) and overwrites the denormalized column on the main DB. Called
    at backend startup so any drift from missed WebSocket events — e.g.,
    an ungraceful shutdown between task creation and event broadcast — is
    corrected before the UI consults the counter.

    Returns a map of {recipe_id: reconciled_count} for logging.
    """
    result = await session.execute(
        select(Recipe).where(Recipe.deleted_at.is_(None))
    )
    reconciled: dict[int, int] = {}
    for recipe in result.scalars().all():
        db_path = get_recipe_state_db_path(recipe.id)
        if not db_path.exists():
            count = 0
        else:
            try:
                rows = graph_db.list_tasks(db_path, status="pending")
                count = len(rows)
            except Exception:  # noqa: BLE001 — never let one bad DB block startup
                log.exception("reconcile: failed to read state.db", recipe_id=recipe.id)
                continue
        if (recipe.pending_task_count or 0) != count:
            await session.execute(
                update(Recipe).where(Recipe.id == recipe.id).values(pending_task_count=count)
            )
        reconciled[recipe.id] = count
    await session.commit()
    return reconciled


async def recover_running_recipes(session) -> list[int]:
    """Recreate + restart runtimes for recipes marked running in the DB.

    Backend restart clears the in-memory recipe_registry, but the main DB still
    records which recipes were running. Rebuild those runtimes and re-enter the
    scheduler loop so interrupted work resumes without a manual pause/resume.
    Returns the recovered recipe ids for logging.
    """
    result = await session.execute(
        select(Recipe).where(
            Recipe.deleted_at.is_(None),
            Recipe.execution_state == "running",
        )
    )
    recovered: list[int] = []
    for recipe in result.scalars().all():
        try:
            runtime = get_or_create_runtime(recipe)
            await runtime.start()
            recovered.append(recipe.id)
        except Exception:  # noqa: BLE001 — startup should keep going
            log.exception("failed to recover running recipe %s", recipe.id)
    return recovered


def _build_runtime(recipe: Recipe) -> RecipeRuntime:
    """Construct a RecipeRuntime for a recipe row, wired to ws_manager."""
    program_path = get_recipe_program_path(recipe.id)
    state_db_path = get_recipe_state_db_path(recipe.id)
    return RecipeRuntime(
        recipe.id,
        state_db_path,
        program_path=program_path,
        inputs=_recipe_inputs(recipe),
        evaluators=build_production_registry(),
        store=get_equation_store(),
        broadcast=_broadcast,
        project_id=recipe.project_id,
    )


def get_or_create_runtime(recipe: Recipe) -> RecipeRuntime:
    """Return the active runtime for this recipe, creating one if needed.

    The returned runtime always has its initial graph built so callers can
    inspect phases/equations without starting the scheduler. Graph-build
    errors surface as HTTP 400 with the DSL error's classification.

    If a runtime is already registered but the recipe's ``inputs`` have
    changed since the graph was built (common flow: the agent writes
    program.py before the user fills the form, so the first graph was built
    with placeholder Nones), refresh the runtime's inputs and diff-rebuild
    via ``try_reload_program`` so the RECIPE_INPUT equations complete with
    the real values. Without this, a ``code()`` block reading ``num_poses``
    sees ``None`` and the user gets an opaque TypeError.
    """
    current_inputs = _recipe_inputs(recipe)
    runtime = recipe_registry.get_runtime(recipe.id)
    if runtime is not None:
        if runtime.inputs != current_inputs:
            runtime.inputs = dict(current_inputs)
            try:
                runtime.try_reload_program()
            except Exception:  # noqa: BLE001 — best-effort; keep the runtime
                log.exception("input-change rebuild failed for recipe %s", recipe.id)
        return runtime
    runtime = _build_runtime(recipe)
    try:
        runtime.build_initial_graph()
    except Exception as exc:  # noqa: BLE001 — surface as 400 with context
        log.exception("failed to build graph for recipe %s", recipe.id)
        raise HTTPException(
            status_code=400,
            detail=f"failed to load recipe program: {exc}",
        ) from exc
    recipe_registry.register(recipe.id, runtime)
    # A successful build supersedes any stale error from an earlier
    # write-hook attempt that couldn't build (e.g. before inputs were set).
    _last_load_errors.pop(recipe.id, None)
    return runtime


async def apply_program_edit(
    session, recipe_id: int, *, auto_start: bool = False,
) -> Optional[dict[str, Any]]:
    """Sync the compiled graph after an external writer (the agent's
    ``write_file`` / ``edit_file`` tools) modifies ``program.py`` for this recipe.

    Without this step the agent's edits stay on disk until the user hits
    Start, because ``GET /recipes/{id}/phases`` reads from ``state.db``
    which is only populated at graph-build time. That produces the
    "recipe says it was created but the phase tree is empty" UX bug.

    Steps:
      1. Rehash ``program.py`` and persist ``Recipe.program_hash``.
      2. If a runtime is already registered (user started the recipe
         earlier), call ``try_reload_program`` so the live graph diffs
         against the new program; it broadcasts its own
         ``recipe_updated`` + ``recipe_phase_updated`` events.
      3. Otherwise build an initial graph and register it, so the phase
         tree endpoint has equations to return.
      4. Broadcast a final ``recipe_updated`` carrying the refreshed
         Recipe row (with the new ``program_hash``) so clients whose
         handlers key off ``program_hash`` refresh the tree.

    Load errors are captured and surfaced via ``recipe_updated`` so the
    frontend can render them inline rather than silently showing an
    empty tree.
    """
    program_path = get_recipe_program_path(recipe_id)
    if not program_path.exists():
        return

    result = await session.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.deleted_at.is_(None))
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        return

    try:
        program_bytes = program_path.read_bytes()
    except OSError:
        log.exception("apply_program_edit: could not read program.py", recipe_id=recipe_id)
        return

    new_hash = hashlib.sha256(program_bytes).hexdigest()
    if recipe.program_hash != new_hash:
        recipe.program_hash = new_hash
        recipe.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(recipe)

    load_error: Optional[dict[str, Any]] = None
    runtime = recipe_registry.get_runtime(recipe_id)
    if runtime is None:
        try:
            runtime = _build_runtime(recipe)
            runtime.build_initial_graph()
            recipe_registry.register(recipe_id, runtime)
        except ProgramLoadError as exc:
            load_error = {
                "category": exc.category,
                "message": str(exc),
                "suggestion": exc.suggestion,
                "program_traceback": exc.program_traceback or None,
            }
        except Exception as exc:  # noqa: BLE001 — surface as a soft error
            log.exception("apply_program_edit: build_initial_graph failed", recipe_id=recipe_id)
            load_error = {"category": "build_error", "message": str(exc), "suggestion": None}
    else:
        # Refresh runtime.inputs before the diff-rebuild so changed input
        # values propagate into the new graph's RECIPE_INPUT equations.
        runtime.inputs = dict(_recipe_inputs(recipe))
        _, err = runtime.try_reload_program()
        if err is not None:
            load_error = {
                "category": err.category,
                "message": str(err),
                "suggestion": err.suggestion,
                "program_traceback": err.program_traceback or None,
            }

    # Mirror the program's @recipe(inputs=..., outputs=...) declarations into
    # Recipe.input_schema / Recipe.output_schema so the UI stays in sync with
    # program.py. program.py is the single source of truth; the DB columns
    # are denormalized copies the frontend reads. Run this before the dry-run
    # preflight so even a recipe with deferred-callback bugs still has its
    # input/output schema reflected in the UI.
    if load_error is None and runtime is not None and runtime.graph is not None:
        await _sync_schemas_from_graph(session, recipe, runtime.graph)

    # Preflight dry-run after a successful build. The graph builder only
    # exercises eagerly-bound code; deferred callbacks inside foreach /
    # hitl.approve (and tool() schema mismatches inside them) don't surface
    # until evaluation. Running dry-run here means the agent's edit cycle
    # gets the same structural errors the user would otherwise see only
    # after clicking Start. Best-effort: if dry-run itself crashes, log
    # and let the build pass — never block an edit on preflight infra.
    if load_error is None and runtime is not None and runtime.graph is not None:
        try:
            report = await dry_run_recipe(
                recipe_id=recipe_id,
                program_path=program_path,
                inputs=_recipe_inputs(recipe),
                project_id=recipe.project_id,
            )
            dry_run_error = _dry_run_load_error(report)
            if dry_run_error is not None:
                load_error = dry_run_error
        except Exception:  # noqa: BLE001 — preflight must never block edits
            log.exception(
                "apply_program_edit: dry-run preflight crashed",
                extra={"recipe_id": recipe_id},
            )

    # Cache/clear the load_error so a subsequent plain GET /phases (e.g. after
    # a browser reload with no websocket event in hand) still surfaces it.
    # Done after dry-run so a preflight failure participates in the cache.
    if load_error is not None:
        _last_load_errors[recipe_id] = load_error
    else:
        _last_load_errors.pop(recipe_id, None)

    # Auto-start the scheduler after a successful agent-authored edit. Recipes
    # should run by default — requiring a manual "play" click every time the
    # agent ships a program is a papercut, and a recipe that builds but sits
    # idle is confusing. Respect an explicit "paused" state (user paused on
    # purpose) and don't stomp on a runtime that's already running.
    # Gated by `auto_start` so manual reparse doesn't surprise the user.
    if (
        auto_start
        and load_error is None
        and runtime is not None
        and runtime.graph is not None
        and recipe.execution_state == "idle"
    ):
        try:
            await runtime.start()
            recipe.execution_state = "running"
            recipe.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(recipe)
        except Exception:  # noqa: BLE001 — best-effort auto-start
            log.exception("auto-start after program edit failed", extra={"recipe_id": recipe_id})

    recipe_payload = recipe.to_dict()
    # Surface the load_error flag on the recipe blob so the sidebar / recipes
    # landing's status pill flips to Error without having to open the recipe
    # to hydrate the phase tree.
    recipe_payload["has_load_error"] = load_error is not None
    payload: dict[str, Any] = {"recipe": recipe_payload, "recipe_id": recipe_id}
    if load_error is not None:
        payload["load_error"] = load_error
    await ws_manager.broadcast("recipe_updated", payload)
    return load_error


def _dry_run_load_error(report: DryRunReport) -> Optional[dict[str, Any]]:
    """Translate a DryRunReport into the load_error dict shape, or None.

    Truncation alone (timeout / equation budget exceeded) is not a recipe
    bug — preflight ran out of room to fully exercise the graph, but the
    code we did exercise was clean. Don't block edits on that.
    """
    if report.ok:
        return None
    hard = [issue for issue in report.issues if issue.category != "truncated"]
    if not hard:
        return None
    primary = hard[0]
    extra = f" (+{len(hard) - 1} more)" if len(hard) > 1 else ""
    return {
        "category": primary.category or "dry_run_error",
        "message": f"dry-run: {primary.message}{extra}",
        "suggestion": None,
        "issues": [
            {
                "equation_key": issue.equation_key,
                "equation_type": issue.equation_type,
                "status": issue.status,
                "message": issue.message,
                "category": issue.category,
                "phase_path": list(issue.phase_path),
            }
            for issue in hard
        ],
    }


async def _sync_schemas_from_graph(session, recipe: Recipe, graph) -> None:
    """Persist ``graph.input_specs`` / ``graph.output_specs`` into the DB.

    The graph builder serializes the @recipe(inputs=..., outputs=...)
    declarations in the shape the frontend expects. We compare against the
    stored JSON and only write+commit when something differs, so identity
    round-trips don't churn the DB or broadcast spurious diffs.
    """
    new_inputs = graph.input_specs or {}
    new_outputs = graph.output_specs or {}

    def _loads(raw):
        try:
            return json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            return {}

    current_inputs = _loads(recipe.input_schema)
    current_outputs = _loads(recipe.output_schema)

    inputs_changed = current_inputs != new_inputs
    outputs_changed = current_outputs != new_outputs
    if not (inputs_changed or outputs_changed):
        return
    if inputs_changed:
        recipe.input_schema = json.dumps(new_inputs) if new_inputs else None
    if outputs_changed:
        recipe.output_schema = json.dumps(new_outputs) if new_outputs else None
    recipe.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(recipe)


async def stop_and_unregister(recipe_id: int) -> None:
    """Tear down the scheduler for a recipe (pause → stop → drop from registry)."""
    runtime = recipe_registry.get_runtime(recipe_id)
    if runtime is None:
        return
    try:
        await runtime.stop()
    finally:
        recipe_registry.unregister(recipe_id)

"""Recipe runtime: per-recipe SQLite state, equation store, and FRP engine.

Phase 1 (done): data model, directory lifecycle, equation store skeleton,
forking, per-recipe state.db schema.

Phase 2 (this release): FRP runtime core — equation keys, graph builder,
DSL primitives, evaluation loop with 10-wide cap, invalidation, graph
diff, pause/resume, app-restart recovery, error handling.

HITL task API and frontend are Phase 4+.
"""

from .paths import (
    get_recipe_dir,
    get_recipe_state_db_path,
    get_recipe_program_path,
    get_recipe_program_base_path,
    get_recipe_resources_dir,
    get_recipe_metadata_path,
    get_recipes_root,
    get_equation_store_dir,
    get_equation_store_db_path,
    get_equation_store_blobs_dir,
)
from .state_db import (
    create_recipe_state_db,
    delete_pending_tasks,
    verify_state_db_schema,
    reset_transient_equation_states,
)
from .equation_store import (
    EquationStore,
    get_equation_store,
    blob_path_for_hash,
    reset_equation_store_singleton,
)
from .directory import (
    consume_user_program_edit_marker,
    create_recipe_directory,
    delete_recipe_directory,
    fork_recipe_directory,
    get_empty_recipe_program,
    has_user_program_edit_marker,
    is_empty_recipe_program,
    mark_user_program_edit,
    write_empty_recipe_program,
)

# Phase 2 surface
from .graph import (
    Equation,
    EquationGraph,
    EquationStatus,
    EquationType,
    NodeRef,
)
# graph_builder / recipe_dsl.loader have a circular dependency with this
# __init__ (recipe_dsl imports recipe_runtime.graph, which triggers this
# __init__). We resolve it via PEP 562 lazy attribute access so the builder
# names are still available on the package but resolved on first use.
from .graph_diff import GraphDiff, diff_graphs


from .evaluators import (
    CODE_ERROR,
    EvaluationRequest,
    EvaluationResult,
    Evaluator,
    EvaluatorError,
    EvaluatorRegistry,
    LLM_ERROR,
    RESOURCE_ERROR,
    TOOL_ERROR,
    TRANSIENT,
)
from .engine import CONCURRENCY_CAP, RecipeRun, RecipeRunConfig, RunState


# Names that live in modules which import recipe_dsl (runtime.py,
# graph_builder shim). Those modules transitively require recipe_dsl, and
# recipe_dsl imports recipe_runtime.graph. Loading them eagerly during this
# __init__ creates a cycle. PEP 562 lazy __getattr__ resolves each name on
# first access, by which point recipe_dsl has finished initializing.
_LAZY_NAMES = {
    "GraphBuildError": ("recipe_runtime.graph_builder", "GraphBuildError"),
    "build_graph_from_callable": ("recipe_runtime.graph_builder", "build_graph_from_callable"),
    "build_graph_from_program_file": ("recipe_runtime.graph_builder", "build_graph_from_program_file"),
    "RecipeRuntime": ("recipe_runtime.runtime", "RecipeRuntime"),
    "recover_all_running_recipes": ("recipe_runtime.runtime", "recover_all_running_recipes"),
    "DryRunConfig": ("recipe_runtime.dry_run", "DryRunConfig"),
    "DryRunIssue": ("recipe_runtime.dry_run", "DryRunIssue"),
    "DryRunReport": ("recipe_runtime.dry_run", "DryRunReport"),
    "dry_run_recipe": ("recipe_runtime.dry_run", "dry_run_recipe"),
}


def __getattr__(name):
    if name in _LAZY_NAMES:
        import importlib
        module_name, attr = _LAZY_NAMES[name]
        mod = importlib.import_module(module_name)
        value = getattr(mod, attr)
        globals()[name] = value  # cache so future lookups bypass __getattr__
        return value
    raise AttributeError(f"module 'recipe_runtime' has no attribute {name!r}")

__all__ = [
    # paths
    "get_recipe_dir",
    "get_recipe_state_db_path",
    "get_recipe_program_path",
    "get_recipe_program_base_path",
    "get_recipe_resources_dir",
    "get_recipe_metadata_path",
    "get_recipes_root",
    "get_equation_store_dir",
    "get_equation_store_db_path",
    "get_equation_store_blobs_dir",
    # state db
    "create_recipe_state_db",
    "delete_pending_tasks",
    "verify_state_db_schema",
    "reset_transient_equation_states",
    # equation store
    "EquationStore",
    "get_equation_store",
    "blob_path_for_hash",
    "reset_equation_store_singleton",
    # directory
    "consume_user_program_edit_marker",
    "create_recipe_directory",
    "delete_recipe_directory",
    "fork_recipe_directory",
    "get_empty_recipe_program",
    "has_user_program_edit_marker",
    "is_empty_recipe_program",
    "mark_user_program_edit",
    "write_empty_recipe_program",
    # graph
    "Equation",
    "EquationGraph",
    "EquationStatus",
    "EquationType",
    "NodeRef",
    # builder / diff (lazy — see __getattr__ above)
    "GraphBuildError",
    "build_graph_from_callable",
    "build_graph_from_program_file",
    "GraphDiff",
    "diff_graphs",
    # evaluators
    "EvaluationRequest",
    "EvaluationResult",
    "Evaluator",
    "EvaluatorError",
    "EvaluatorRegistry",
    "CODE_ERROR",
    "LLM_ERROR",
    "RESOURCE_ERROR",
    "TOOL_ERROR",
    "TRANSIENT",
    # engine
    "CONCURRENCY_CAP",
    "RecipeRun",
    "RecipeRunConfig",
    "RunState",
    # runtime
    "RecipeRuntime",
    "recover_all_running_recipes",
    "DryRunConfig",
    "DryRunIssue",
    "DryRunReport",
    "dry_run_recipe",
]

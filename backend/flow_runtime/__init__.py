"""Flow runtime: per-flow SQLite state, equation store, and FRP engine.

Phase 1 (done): data model, directory lifecycle, equation store skeleton,
forking, per-flow state.db schema.

Phase 2 (this release): FRP runtime core — equation keys, graph builder,
DSL primitives, evaluation loop with 10-wide cap, invalidation, graph
diff, pause/resume, app-restart recovery, error handling.

HITL task API and frontend are Phase 4+.
"""

from .paths import (
    get_flow_dir,
    get_flow_state_db_path,
    get_flow_program_path,
    get_flow_program_base_path,
    get_flow_resources_dir,
    get_flow_metadata_path,
    get_flows_root,
    get_equation_store_dir,
    get_equation_store_db_path,
    get_equation_store_blobs_dir,
)
from .state_db import (
    create_flow_state_db,
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
    create_flow_directory,
    delete_flow_directory,
    fork_flow_directory,
    get_empty_flow_program,
    has_user_program_edit_marker,
    is_empty_flow_program,
    mark_user_program_edit,
    write_empty_flow_program,
)

# Phase 2 surface
from .graph import (
    Equation,
    EquationGraph,
    EquationStatus,
    EquationType,
    NodeRef,
)
# graph_builder / flow_dsl.loader have a circular dependency with this
# __init__ (flow_dsl imports flow_runtime.graph, which triggers this
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
from .engine import CONCURRENCY_CAP, FlowRun, FlowRunConfig, RunState


# Names that live in modules which import flow_dsl (runtime.py,
# graph_builder shim). Those modules transitively require flow_dsl, and
# flow_dsl imports flow_runtime.graph. Loading them eagerly during this
# __init__ creates a cycle. PEP 562 lazy __getattr__ resolves each name on
# first access, by which point flow_dsl has finished initializing.
_LAZY_NAMES = {
    "GraphBuildError": ("flow_runtime.graph_builder", "GraphBuildError"),
    "build_graph_from_callable": ("flow_runtime.graph_builder", "build_graph_from_callable"),
    "build_graph_from_program_file": ("flow_runtime.graph_builder", "build_graph_from_program_file"),
    "FlowRuntime": ("flow_runtime.runtime", "FlowRuntime"),
    "recover_all_running_flows": ("flow_runtime.runtime", "recover_all_running_flows"),
    "DryRunConfig": ("flow_runtime.dry_run", "DryRunConfig"),
    "DryRunIssue": ("flow_runtime.dry_run", "DryRunIssue"),
    "DryRunReport": ("flow_runtime.dry_run", "DryRunReport"),
    "dry_run_flow": ("flow_runtime.dry_run", "dry_run_flow"),
}


def __getattr__(name):
    if name in _LAZY_NAMES:
        import importlib
        module_name, attr = _LAZY_NAMES[name]
        mod = importlib.import_module(module_name)
        value = getattr(mod, attr)
        globals()[name] = value  # cache so future lookups bypass __getattr__
        return value
    raise AttributeError(f"module 'flow_runtime' has no attribute {name!r}")

__all__ = [
    # paths
    "get_flow_dir",
    "get_flow_state_db_path",
    "get_flow_program_path",
    "get_flow_program_base_path",
    "get_flow_resources_dir",
    "get_flow_metadata_path",
    "get_flows_root",
    "get_equation_store_dir",
    "get_equation_store_db_path",
    "get_equation_store_blobs_dir",
    # state db
    "create_flow_state_db",
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
    "create_flow_directory",
    "delete_flow_directory",
    "fork_flow_directory",
    "get_empty_flow_program",
    "has_user_program_edit_marker",
    "is_empty_flow_program",
    "mark_user_program_edit",
    "write_empty_flow_program",
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
    "FlowRun",
    "FlowRunConfig",
    "RunState",
    # runtime
    "FlowRuntime",
    "recover_all_running_flows",
    "DryRunConfig",
    "DryRunIssue",
    "DryRunReport",
    "dry_run_flow",
]

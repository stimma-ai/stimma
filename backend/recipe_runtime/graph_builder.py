"""Compatibility shim — the graph builder lives in ``backend/recipe_dsl/loader.py``.

Older code imports ``recipe_runtime.graph_builder.build_graph_from_*`` and
``GraphBuildError``. Both are aliased through here.

``GraphBuildError`` used to be a thin ``RuntimeError`` subclass; Phase 3
upgrades it to ``ProgramLoadError`` (from ``recipe_dsl.errors``) which
carries error classification and agent-friendly suggestions. Callers that
catch ``GraphBuildError`` keep working via the alias.
"""

from __future__ import annotations

from recipe_dsl.errors import ProgramLoadError as GraphBuildError  # noqa: F401
from recipe_dsl.loader import (  # noqa: F401
    build_graph_from_callable,
    build_graph_from_program_file,
    build_graph_from_source,
    load_program_with_error_classification,
)

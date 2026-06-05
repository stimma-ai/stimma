"""Compatibility shim — the DSL lives in ``backend/recipe_dsl/`` as of Phase 3.

This module preserves the Phase 2 import paths (``recipe_runtime.dsl.tool``
etc.) so existing tests and earlier code keep working. New code should
import from ``recipe_dsl`` directly.
"""

from __future__ import annotations

from recipe_dsl.context import (  # noqa: F401
    BuildContext,
    BuildFrame,
    activate_context,
    current_context,
    push_frame,
)
from recipe_dsl.primitives import (  # noqa: F401
    InputSpec,
    OutputSpec,
    RecipeDecorated,
    code,
    filter,
    filter_items,
    foreach,
    foreach_range,
    gate,
    hitl,
    input,  # noqa: A004 — matches DSL surface
    lift_recipe_input,
    llm,
    output,
    phase,
    partition,
    recipe,
    switch,
    take,
    tool,
    when,
    zip_nodes,
    # helpers kept for Phase 2 tests that poke at internals
    _collect_noderefs,
    _register_literal_collection,
    _register_nested_equation,
    _split_static_dynamic,
    _template_of,
)

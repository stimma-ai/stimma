"""Program loader — executes ``program.py`` and produces an EquationGraph.

Exposes three entry points:

- ``build_graph_from_callable(fn, inputs)`` — direct callable path, used by
  tests that hold the decorated function.
- ``build_graph_from_source(source, inputs)`` — exec a source string in a
  restricted DSL-injected namespace.
- ``build_graph_from_program_file(path, inputs)`` — read a file and delegate
  to the source builder.

Errors are classified so the recipe UI and the agent can act appropriately:

- ``syntax``   — Python parse error
- ``import``   — unresolved import (usually the agent tried to import
  something outside the DSL namespace)
- ``name``     — reference to an undefined name
- ``type``     — wrong argument shape to a DSL primitive (raised as TypeError)
- ``dsl``      — DSL-level misuse (NodeUsageError, DSLMisuseError, ...)
- ``other``    — anything else

Each ``ProgramLoadError`` carries ``category``, a short ``suggestion``, and
the original program traceback.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import tempfile
import types
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from recipe_runtime.graph import EquationGraph, EquationType, NodeRef

from .context import BuildContext, activate_context, push_frame
from .errors import DSLError, DSLMisuseError, NodeUsageError, ProgramLoadError
from .primitives import (
    InputSpec,
    OutputSpec,
    RecipeDecorated,
    code,
    create_document,
    create_grid,
    create_image,
    create_layout,
    create_set,
    fetch_media,
    filter as dsl_filter,
    filter_items,
    foreach,
    foreach_range,
    gate,
    hitl,
    info,
    input as dsl_input,
    lift_recipe_input,
    llm,
    output as dsl_output,
    phase,
    partition,
    rasterize_layout,
    recipe,
    switch,
    take,
    tool,
    web_search,
    when,
    zip_nodes,
)


log = logging.getLogger(__name__)


# DSL namespace injected into every program's module globals. This matches
# the import shape recipes declare at the top of ``program.py``:
#
#     from stimma.recipe import recipe, foreach, tool, llm, code, hitl, ...
def _dsl_namespace() -> dict[str, Any]:
    return {
        "recipe": recipe,
        "input": dsl_input,
        "output": dsl_output,
        "phase": phase,
        "foreach": foreach,
        "foreach_range": foreach_range,
        "switch": switch,
        "when": when,
        "gate": gate,
        "filter": dsl_filter,
        "filter_items": filter_items,
        "partition": partition,
        "take": take,
        "zip_nodes": zip_nodes,
        "tool": tool,
        "llm": llm,
        "code": code,
        "hitl": hitl,
        "info": info,
        "create_set": create_set,
        "create_grid": create_grid,
        "create_document": create_document,
        "create_image": create_image,
        "create_layout": create_layout,
        "rasterize_layout": rasterize_layout,
        "web_search": web_search,
        "fetch_media": fetch_media,
    }


def _ensure_stimma_recipe_module_registered() -> tuple[types.ModuleType, types.ModuleType]:
    """Create a virtual ``stimma.recipe`` module that re-exports the DSL.

    This lets recipe programs use the canonical import shape the docs and
    system prompt show:

        from stimma.recipe import recipe, foreach, tool, ...

    We install it in ``sys.modules`` so the first ``import stimma.recipe``
    hits this virtual module instead of failing. Idempotent. Returns the
    ``(stimma, stimma.recipe)`` module pair so callers can expose them to
    the sandboxed ``__import__``.
    """
    stimma_pkg = sys.modules.get("stimma")
    if stimma_pkg is None:
        stimma_pkg = types.ModuleType("stimma")
        stimma_pkg.__path__ = []  # mark as package
        sys.modules["stimma"] = stimma_pkg

    recipe_module = sys.modules.get("stimma.recipe")
    if recipe_module is None:
        recipe_module = types.ModuleType("stimma.recipe")
        sys.modules["stimma.recipe"] = recipe_module
        setattr(stimma_pkg, "recipe", recipe_module)
    namespace = _dsl_namespace()
    for name, value in namespace.items():
        setattr(recipe_module, name, value)

    return stimma_pkg, recipe_module


def _recipe_sandbox_workspace() -> Path:
    """A writable scratch dir for the recipe build-time sandbox.

    ``build_safe_builtins`` requires a workspace path for its ``open()``
    guard, even though recipe programs aren't expected to open files during
    graph construction. Using the same temp root as the code() evaluator
    keeps both sandboxes rooted in one place.
    """
    root = Path(tempfile.gettempdir()) / "stimma_recipe_code"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _noop_print(*args, **kwargs) -> None:
    return None


# ----- Callable path --------------------------------------------------------


def build_graph_from_callable(
    fn: Callable[..., Any] | RecipeDecorated,
    inputs: Optional[dict[str, Any]] = None,
) -> EquationGraph:
    """Build the graph for a decorated recipe function.

    Used by tests and by the file-based loader after it finds the @recipe
    function inside program.py.
    """
    if isinstance(fn, RecipeDecorated):
        recipe_fn = fn.fn
        declared_inputs: dict[str, Any] = dict(fn.inputs_schema or {})
        declared_outputs: dict[str, Any] = dict(fn.outputs_schema or {})
    else:
        recipe_fn = fn
        declared_inputs = {}
        declared_outputs = {}
    recipe_name = getattr(recipe_fn, "__name__", "recipe")

    inputs = dict(inputs or {})

    # Inputs the recipe declares but the caller didn't supply still get lifted
    # so the graph builds for structural introspection. If the declaration has
    # a default, that default is a real runtime value; the UI also seeds the
    # form from it, so leaving the backend value as None makes the graph show
    # "waiting" while the form visibly contains a value.
    for declared_name, spec in declared_inputs.items():
        if declared_name in inputs:
            continue
        default = spec.default if isinstance(spec, InputSpec) else None
        inputs[declared_name] = default if default is not None else None

    graph = EquationGraph()
    ctx = BuildContext(graph=graph)

    with activate_context(ctx):
        with push_frame(ctx, parent_key=recipe_name, function_name=recipe_name):
            call_kwargs: dict[str, Any] = {}
            for name, value in inputs.items():
                spec = declared_inputs.get(name)
                type_str = (
                    spec.type if isinstance(spec, InputSpec) else None
                )
                optional = (
                    bool(spec.optional) if isinstance(spec, InputSpec) else False
                )
                display_name = (
                    spec.display_name if isinstance(spec, InputSpec) else ""
                )
                call_kwargs[name] = lift_recipe_input(
                    ctx,
                    name,
                    value,
                    type_str=type_str,
                    optional=optional,
                    display_name=display_name,
                )

            try:
                result = recipe_fn(**call_kwargs)
            except DSLError as exc:
                raise ProgramLoadError(
                    f"recipe {recipe_name!r} failed during graph construction: {exc}",
                    category="dsl",
                    program_traceback=traceback.format_exc(),
                    suggestion=getattr(exc, "suggestion", ""),
                ) from exc
            except Exception as exc:
                raise _classify_exception(exc, traceback.format_exc()) from exc

    # Eager-expand any deferred whose iteration count is statically knowable.
    # Without this pass the foreach/hitl.approve wrappers stay as opaque
    # placeholders in the graph viz until the scheduler reaches them; the
    # frontend renders per-iteration tiles only off real iteration wrappers.
    # Expanding one collection can unblock another (a foreach over a
    # hitl.approve becomes early-eligible once the approve is expanded),
    # so loop until we hit a fixed point.
    _eagerly_expand_static_deferreds(graph, recipe_name)

    output_bindings = _collect_return_output_bindings(
        result,
        declared_outputs=declared_outputs,
        recipe_name=recipe_name,
    )
    output_keys = list(output_bindings.values())
    graph.output_keys = output_keys
    graph.output_name_by_key = {
        equation_key: output_name
        for output_name, equation_key in output_bindings.items()
    }
    graph.root_key = output_keys[0] if output_keys else None

    graph.input_specs = _serialize_input_specs(declared_inputs)
    graph.output_specs = _serialize_output_specs(declared_outputs)

    _validate_all_equations_have_phase(graph, recipe_name)
    _validate_no_dangling_equations(graph, recipe_name)
    return graph


def _collect_return_output_bindings(
    result: Any,
    *,
    declared_outputs: dict[str, Any],
    recipe_name: str,
) -> dict[str, str]:
    """Map declared output name -> surfaced equation key.

    When a recipe declares outputs, the return contract is explicit:

    - one declared output: return either a bare NodeRef or `{name: node}`
    - multiple declared outputs: return `{name: node, ...}` matching the
      declared output names exactly

    Recipes without declared outputs keep the older permissive behavior so
    legacy tests and internal helpers can still return a bare node / list /
    dict without a schema.
    """
    declared_names = list(declared_outputs.keys())
    if not declared_names:
        return _collect_legacy_return_output_bindings(result)

    def _single_binding(name: str, value: Any) -> dict[str, str]:
        if not isinstance(value, NodeRef):
            raise ProgramLoadError(
                f"{recipe_name}: output {name!r} must be a NodeRef, got {type(value).__name__}",
                category="dsl",
                suggestion=(
                    "Return the node produced by tool()/llm()/code()/hitl.*()/foreach(). "
                    "If you need multiple named outputs, return a dict that maps each "
                    "declared output name to a NodeRef."
                ),
            )
        return {name: value.equation_key}

    if len(declared_names) == 1:
        name = declared_names[0]
        if isinstance(result, NodeRef):
            return _single_binding(name, result)
        if isinstance(result, dict):
            actual_names = set(result.keys())
            expected_names = {name}
            if actual_names != expected_names:
                missing = sorted(expected_names - actual_names)
                extra = sorted(actual_names - expected_names)
                details: list[str] = []
                if missing:
                    details.append(f"missing {missing}")
                if extra:
                    details.append(f"unexpected {extra}")
                detail_text = ", ".join(details) if details else "wrong keys"
                raise ProgramLoadError(
                    f"{recipe_name}: return dict must match declared outputs exactly ({detail_text})",
                    category="dsl",
                    suggestion=(
                        f"For this recipe, either `return {name}` directly or "
                        f"`return {{\"{name}\": {name}}}` with the declared output name."
                    ),
                )
            return _single_binding(name, result.get(name))
        raise ProgramLoadError(
            f"{recipe_name}: single-output recipes must return a NodeRef or a one-key dict",
            category="dsl",
            suggestion=(
                f"Return the final node directly (for `{name}`), or return "
                f"`{{\"{name}\": node}}`."
            ),
        )

    if not isinstance(result, dict):
        raise ProgramLoadError(
            f"{recipe_name}: recipes with multiple declared outputs must return a dict",
            category="dsl",
            suggestion=(
                "Return a dict that maps each declared output name to the "
                "NodeRef that produces it, e.g. "
                "`return {\"images\": images, \"caption\": caption}`."
            ),
        )

    actual_names = set(result.keys())
    expected_names = set(declared_names)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        detail_text = ", ".join(details) if details else "wrong keys"
        raise ProgramLoadError(
            f"{recipe_name}: return dict must match declared outputs exactly ({detail_text})",
            category="dsl",
            suggestion=(
                "Return a dict whose keys exactly match the names declared in "
                "@recipe(outputs={...})."
            ),
        )

    bindings: dict[str, str] = {}
    seen_equation_keys: dict[str, str] = {}
    for name in declared_names:
        value = result.get(name)
        if not isinstance(value, NodeRef):
            raise ProgramLoadError(
                f"{recipe_name}: output {name!r} must be a NodeRef, got {type(value).__name__}",
                category="dsl",
                suggestion=(
                    "Each declared output must map to a node produced by the DSL, "
                    "not a resolved Python value."
                ),
            )
        existing = seen_equation_keys.get(value.equation_key)
        if existing is not None:
            raise ProgramLoadError(
                f"{recipe_name}: outputs {existing!r} and {name!r} both return the same node",
                category="dsl",
                suggestion=(
                    "Return distinct nodes for distinct declared outputs. If you only "
                    "have one output, declare one output."
                ),
            )
        seen_equation_keys[value.equation_key] = name
        bindings[name] = value.equation_key
    return bindings


def _collect_legacy_return_output_bindings(result: Any) -> dict[str, str]:
    """Legacy fallback for recipes/tests that declare no outputs."""
    seen: set[str] = set()
    bindings: dict[str, str] = {}

    def add(name: str, ref: NodeRef) -> None:
        if ref.equation_key in seen:
            return
        seen.add(ref.equation_key)
        bindings[name] = ref.equation_key

    if isinstance(result, NodeRef):
        add("output", result)
    elif isinstance(result, (list, tuple)):
        for idx, item in enumerate(result):
            if isinstance(item, NodeRef):
                add(f"output_{idx}", item)
    elif isinstance(result, dict):
        for name, value in result.items():
            if isinstance(value, NodeRef):
                add(str(name), value)
    return bindings


def _serialize_input_specs(specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Turn the @recipe(inputs={...}) declaration into a UI-facing schema dict.

    Matches the shape RecipeInputForm.vue reads: ``{name: {type, description?,
    default?, options?, lines?}}``. recipe_lifecycle mirrors this into
    Recipe.input_schema so declaring an input in program.py is all the agent
    needs to do — the form updates automatically.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, spec in specs.items():
        if not isinstance(spec, InputSpec):
            continue
        entry: dict[str, Any] = {"type": spec.type}
        if spec.description:
            entry["description"] = spec.description
        if spec.default is not None:
            entry["default"] = spec.default
        if spec.options is not None:
            entry["options"] = list(spec.options)
        if spec.lines and int(spec.lines) > 1:
            entry["lines"] = int(spec.lines)
        if spec.optional:
            entry["optional"] = True
        if spec.display_name:
            entry["display_name"] = spec.display_name
        if spec.ui:
            entry["ui"] = dict(spec.ui)
        if spec.validation:
            entry["validation"] = dict(spec.validation)
        if spec.item:
            entry["item"] = dict(spec.item)
        if spec.fields:
            entry["fields"] = dict(spec.fields)
        out[name] = entry
    return out


def _serialize_output_specs(specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Turn the @recipe(outputs={...}) declaration into a UI-facing schema dict.

    Mirrored into Recipe.output_schema by recipe_lifecycle so program.py is
    the single source of truth for both inputs and outputs.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, spec in specs.items():
        if not isinstance(spec, OutputSpec):
            continue
        entry: dict[str, Any] = {"type": spec.type}
        if spec.description:
            entry["description"] = spec.description
        out[name] = entry
    return out


def _eagerly_expand_static_deferreds(
    graph: EquationGraph, recipe_name: str,
) -> None:
    """Materialize any deferred whose iteration count is statically knowable.

    Runs at the end of graph build, after the recipe function has returned
    and registered all deferreds. Loops until no more progress is possible
    so cascades unblock each other (a foreach over a hitl.approve becomes
    early-eligible the moment the approve itself is expanded).

    Build-time callbacks have no scheduler context — failures abort the
    load with a classified ``ProgramLoadError`` instead of being routed
    through the engine's task panel.
    """
    # Imported lazily — recipe_runtime.foreach_expansion imports
    # recipe_dsl.context at module load, which would create a cycle if the
    # entry point starts from recipe_runtime.engine (engine → expansion →
    # recipe_dsl/__init__ → loader → expansion-still-loading).
    from recipe_runtime.foreach_expansion import (
        expand_foreach,
        find_eager_expansion,
    )

    while True:
        progressed = False
        for deferred in graph.all_deferred():
            plan = find_eager_expansion(graph, deferred)
            if plan is None:
                continue
            mode, items, iter_keys = plan
            try:
                expand_foreach(
                    graph,
                    deferred,
                    items=items,
                    iter_keys=iter_keys,
                    persistor=None,
                )
            except DSLError as exc:
                raise ProgramLoadError(
                    f"{recipe_name}: foreach/hitl.approve {deferred.owner_key!r} "
                    f"failed during eager expansion: {exc}",
                    category="dsl",
                    program_traceback=traceback.format_exc(),
                    suggestion=getattr(exc, "suggestion", ""),
                ) from exc
            except Exception as exc:
                raise _classify_exception(exc, traceback.format_exc()) from exc
            deferred.expanded = True
            progressed = True
        if not progressed:
            return


# Equation types that represent user-visible operations and must live inside
# a `with phase(...):` block. CONTROL (wrappers, foreach, zip) and
# RECIPE_INPUT are structural/declarative and are exempt.
_PHASE_REQUIRED_TYPES = frozenset({
    EquationType.TOOL_CALL,
    EquationType.LLM_CALL,
    EquationType.CODE,
    EquationType.HITL,
    EquationType.INFO,
})


# Equation types that must either feed another equation or be part of the
# recipe's ``return``. ``info`` is narrative commentary and is intentionally
# terminal; ``recipe_input`` may be declared while the agent is iterating and
# isn't yet wired up — both are exempt.
_TERMINAL_REQUIRED_TYPES = frozenset({
    EquationType.TOOL_CALL,
    EquationType.LLM_CALL,
    EquationType.CODE,
    EquationType.HITL,
    EquationType.CONTROL,
    EquationType.CREATE_SET,
    EquationType.CREATE_GRID,
    EquationType.CREATE_DOCUMENT,
    EquationType.CREATE_IMAGE,
    EquationType.CREATE_LAYOUT,
    EquationType.RASTERIZE_LAYOUT,
})


def _validate_all_equations_have_phase(graph: EquationGraph, recipe_name: str) -> None:
    """Fail the build if any user-visible equation sits outside a phase.

    Orphaned equations render above the phase list in the UI and their
    failures never bubble into a phase header — the tree wedges in
    "Waiting" with no signal. Requiring a phase keeps the tree honest.
    """
    orphans = [
        eq for eq in graph.all_equations()
        if eq.equation_type in _PHASE_REQUIRED_TYPES and not eq.phase_path
    ]
    if not orphans:
        return
    sample = ", ".join(eq.key for eq in orphans[:5])
    more = "" if len(orphans) <= 5 else f" (+{len(orphans) - 5} more)"
    raise ProgramLoadError(
        f"{recipe_name}: {len(orphans)} equation(s) are outside any phase: {sample}{more}",
        category="dsl",
        suggestion=(
            "Every tool(), llm(), code(), and hitl.*() call must be inside a "
            "`with phase(\"Phase name\"):` block. Wrap the orphaned calls in "
            "a phase so the UI can group and surface their status."
        ),
    )


def _validate_no_dangling_equations(graph: EquationGraph, recipe_name: str) -> None:
    """Fail the build if any user-visible equation is a dead end.

    A dead end is an equation whose result is neither consumed by another
    equation nor surfaced through the recipe's ``return``. Typical causes:
    the recipe forgot to ``return`` the final node; a call was assigned to a
    variable that nothing else references; a ``hitl.approve(x)`` gate was
    written as a side-effect but its return value (the approved asset) was
    never passed on.

    ``info`` nodes are exempt because they're narrative cards — being
    terminal is the whole point. ``recipe_input`` is exempt so declaring an
    input while iterating isn't a hard error.
    """
    output_set = set(graph.output_keys or [])
    dangling = [
        eq for eq in graph.all_equations()
        if eq.equation_type in _TERMINAL_REQUIRED_TYPES
        and not graph.dependents_of(eq.key)
        and eq.key not in output_set
    ]
    if not dangling:
        return
    sample = ", ".join(eq.key for eq in dangling[:5])
    more = "" if len(dangling) <= 5 else f" (+{len(dangling) - 5} more)"
    raise ProgramLoadError(
        f"{recipe_name}: {len(dangling)} equation(s) produce a value nothing uses: {sample}{more}",
        category="dsl",
        suggestion=(
            "Every tool()/llm()/code()/hitl.*()/foreach()/create_* call must "
            "either feed another DSL call or be reachable from the recipe's "
            "return value. Either wire the result into a downstream call, "
            "include it in the returned tuple/dict, or delete the call. If "
            "the step is pure narration, use info() instead — info nodes are "
            "allowed to be terminal."
        ),
    )


# ----- Source path ----------------------------------------------------------


def build_graph_from_source(
    source: str,
    inputs: Optional[dict[str, Any]] = None,
    *,
    filename: str = "<program>",
) -> EquationGraph:
    """Parse and execute a recipe source string, build its graph.

    This is the entry point the file-based loader and unit tests share.
    Syntax errors, name errors, imports, and DSL misuse all surface as
    ``ProgramLoadError`` with a classified ``category``.
    """
    # Imported lazily to avoid a circular import: agent.v2 → recipe_lifecycle
    # → recipe_runtime → recipe_dsl.loader.
    from agent.v2.code_runtime import ALLOWED_MODULES, build_safe_builtins

    stimma_pkg, recipe_module = _ensure_stimma_recipe_module_registered()

    try:
        compiled = compile(source, filename, "exec")
    except SyntaxError as exc:
        raise ProgramLoadError(
            f"{filename}: syntax error: {exc.msg} (line {exc.lineno})",
            category="syntax",
            program_traceback=traceback.format_exc(),
            suggestion=(
                "Check the program source for missing colons, mismatched "
                "parentheses, or indentation errors."
            ),
        ) from exc

    # The builder runs agent-authored code — hand it the same restricted
    # builtins the code() evaluator uses so both environments share one
    # allow-list. ``stimma`` and ``stimma.recipe`` are exposed via
    # ``extra_modules`` so ``from stimma.recipe import …`` resolves.
    safe_builtins = build_safe_builtins(
        _recipe_sandbox_workspace(),
        _noop_print,
        extra_modules={
            "stimma": stimma_pkg,
            "stimma.recipe": recipe_module,
        },
    )
    module_globals: dict[str, Any] = {
        "__name__": "_stimma_recipe_program",
        "__file__": filename,
        "__builtins__": safe_builtins,
    }
    # Callable-form code(), create_image(), and create_layout() execute later
    # using the function object's original globals. Pre-bind the sandbox's
    # allowed modules so a lambda can safely reference json/math/re/etc. even
    # if the generated program omitted an explicit import. Imports still work
    # via safe_builtins; this just removes a common runtime-only NameError.
    module_globals.update(ALLOWED_MODULES)
    module_globals.update(_dsl_namespace())

    try:
        exec(compiled, module_globals)
    except ProgramLoadError:
        raise
    except DSLError as exc:
        raise ProgramLoadError(
            f"{filename}: DSL misuse: {exc}",
            category="dsl",
            program_traceback=traceback.format_exc(),
            suggestion=getattr(exc, "suggestion", ""),
        ) from exc
    except Exception as exc:
        raise _classify_exception(exc, traceback.format_exc()) from exc

    recipe_fn = _find_recipe_function(module_globals)
    if recipe_fn is None:
        raise ProgramLoadError(
            f"{filename}: no @recipe-decorated function found",
            category="dsl",
            suggestion=(
                "Define the recipe entry point with @recipe(...) — the agent "
                "needs exactly one decorated function per program."
            ),
        )
    return build_graph_from_callable(recipe_fn, inputs=inputs)


# ----- File path ------------------------------------------------------------


def build_graph_from_program_file(
    program_path: Path,
    inputs: Optional[dict[str, Any]] = None,
) -> EquationGraph:
    """Read ``program.py`` from disk and build its graph.

    A fresh module namespace is used each call so re-parses are
    deterministic (invariant I2 — see RECIPES_EQUATION_KEYS.md §8). The
    module is NOT placed in ``sys.modules`` to avoid caching.
    """
    program_path = Path(program_path)
    if not program_path.exists():
        raise ProgramLoadError(
            f"program file does not exist: {program_path}",
            category="other",
        )
    try:
        source = program_path.read_text()
    except OSError as exc:
        raise ProgramLoadError(
            f"cannot read program file {program_path}: {exc}",
            category="other",
        ) from exc

    return build_graph_from_source(source, inputs=inputs, filename=str(program_path))


# ----- Wrapper that never raises -------------------------------------------


def load_program_with_error_classification(
    program_path: Path,
    inputs: Optional[dict[str, Any]] = None,
) -> tuple[Optional[EquationGraph], Optional[ProgramLoadError]]:
    """Load a program, returning (graph, None) on success or (None, error).

    Callers that want to preserve the previous valid graph on failure use
    this wrapper — if ``error`` is non-None, they surface the error and
    leave the running graph untouched. If ``graph`` is non-None, they
    proceed with the diff.
    """
    try:
        graph = build_graph_from_program_file(program_path, inputs=inputs)
        return graph, None
    except ProgramLoadError as exc:
        return None, exc
    except Exception as exc:
        # Belt-and-suspenders: anything that isn't a ProgramLoadError is
        # converted into one so callers have a single error type to handle.
        return None, ProgramLoadError(
            f"unexpected error loading program: {exc}",
            category="other",
            program_traceback=traceback.format_exc(),
        )


# ----- Error classification -------------------------------------------------


def _classify_exception(exc: Exception, tb: str) -> ProgramLoadError:
    """Map a raw Python exception into a classified ProgramLoadError.

    We lean on the exception class hierarchy rather than string matching so
    the classification is stable across Python versions.
    """
    if isinstance(exc, SyntaxError):
        return ProgramLoadError(
            f"syntax error: {exc}",
            category="syntax",
            program_traceback=tb,
        )
    if isinstance(exc, ImportError):
        return ProgramLoadError(
            f"import error: {exc}",
            category="import",
            program_traceback=tb,
            suggestion=(
                "Recipe programs only have access to the DSL surface "
                "(recipe, input, output, phase, foreach, tool, llm, code, "
                "hitl, switch, when, gate, filter, partition, take, "
                "zip_nodes, info, create_set, create_grid, create_document). "
                "Stimma's runtime resolves tool "
                "IDs via tool() — don't import Stimma modules directly."
            ),
        )
    if isinstance(exc, NameError):
        return ProgramLoadError(
            f"undefined name: {exc}",
            category="name",
            program_traceback=tb,
            suggestion=(
                "If this is a helper function, define it at module level "
                "before @recipe. If it's a DSL primitive, check the spelling."
            ),
        )
    if isinstance(exc, DSLError):
        return ProgramLoadError(
            f"DSL misuse: {exc}",
            category="dsl",
            program_traceback=tb,
            suggestion=getattr(exc, "suggestion", ""),
        )
    if isinstance(exc, TypeError):
        return ProgramLoadError(
            f"type error in DSL call: {exc}",
            category="type",
            program_traceback=tb,
            suggestion=(
                "Check that you're passing the right types to DSL primitives. "
                "Common causes: passing a node where a literal was expected, "
                "or forgetting a required keyword argument."
            ),
        )
    return ProgramLoadError(
        f"error during graph construction: {exc}",
        category="other",
        program_traceback=tb,
    )


def _find_recipe_function(namespace: dict[str, Any]) -> Optional[RecipeDecorated]:
    recipes = [
        value for value in namespace.values()
        if isinstance(value, RecipeDecorated)
    ]
    if len(recipes) > 1:
        names = ", ".join(r.__name__ for r in recipes)
        raise ProgramLoadError(
            f"program.py defines multiple @recipe functions: {names}",
            category="dsl",
            suggestion=(
                "A recipe program must define exactly one @recipe(...) entry "
                "point. Split smoke tests into separate recipes/files, or keep "
                "only the recipe you want to run."
            ),
        )
    return recipes[0] if recipes else None

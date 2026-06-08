"""DSL primitives — @recipe, phase, foreach, tool, llm, code, hitl.*, zip_nodes.

This is the Python surface the recipe agent imports. Each primitive
registers an equation in the graph and returns a NodeRef (a value
reference). No DSL call performs its operation at build time.

The design is grounded in docs/RECIPES_DSL.md. In particular:

- Nodes are opaque: inspection, arithmetic, iteration, comparisons, and
  f-string interpolation at graph-build time all raise DSLError
  (``NodeUsageError``) with a message that teaches the fix. See the
  guards on ``recipe_runtime.graph.NodeRef``.
- Iteration keys are derived by the runtime from the source collection
  (RECIPES_EQUATION_KEYS.md §6). foreach takes no ``key=`` / ``label=``.
- Every callback body emits a wrapper + one nested equation per DSL call
  (RECIPES_EQUATION_KEYS.md §3, "No single-call collapse").
- Tool IDs are validated against the STP registry when available; the
  check is best-effort (tests and authoring may run without a registry).
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import inspect
import logging
import textwrap
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional

from recipe_runtime.graph import (
    DeferredExpansion,
    Equation,
    EquationType,
    NodeRef,
)
from recipe_runtime.keys import (
    IterationKeySource,
    canonical_json_hash,
    encode_iteration_key,
    make_nested_dsl_key,
    make_nested_foreach_iteration_key,
    validate_function_name,
)
from recipe_runtime.store_key import (
    definition_hash_for_code,
    definition_hash_for_create_document,
    definition_hash_for_create_grid,
    definition_hash_for_create_image,
    definition_hash_for_create_layout,
    definition_hash_for_create_set,
    definition_hash_for_fetch_media,
    definition_hash_for_info,
    definition_hash_for_llm,
    definition_hash_for_llm_batch,
    definition_hash_for_llm_slot,
    definition_hash_for_rasterize_layout,
    definition_hash_for_tool,
    definition_hash_for_web_search,
)

from .context import BuildContext, activate_context, current_context, push_frame
from .errors import DSLMisuseError, NodeUsageError, validate_output_type
from .shapes import (
    DictShape,
    ListShape,
    Scalar,
    Shape,
    ToolParamExpectation,
    TupleShape,
    UNKNOWN,
    RESERVED_TOOL_KWARGS,
    describe as describe_shape,
    find_bad_subscripts,
    parse_tool_param_expectations,
    shape_from_code_output_type,
    shape_from_literal,
    shape_from_response_format,
    shape_from_type_string,
    shape_matches_array,
    shape_matches_scalar_kind,
    web_search_result_shape,
)


log = logging.getLogger(__name__)


# ----- @recipe decorator + input/output specs -------------------------------


@dataclass
class InputSpec:
    type: str
    description: str = ""
    default: Any = None
    options: Optional[list[Any]] = None
    # Render hint for the recipe UI. Only meaningful for ``type="str"``:
    # >1 renders a textarea with that many visible rows; 1 renders a
    # single-line input.
    lines: int = 1
    # When True, the runtime treats a missing/``None`` value as a completed
    # equation carrying ``None`` (rather than blocking forever waiting for the
    # user to fill the input). Downstream code() must handle ``None``.
    optional: bool = False
    # Human-readable label shown in the recipe UI (steps/graph/input form)
    # when present. The Python identifier stays snake_case; this is how the
    # input is named to the end user. Empty string falls back to a
    # humanized version of the identifier.
    display_name: str = ""
    # Optional UI hints for the recipe input form. Keep this small and
    # declarative: {"control": "chips"|"list"|"table"|"slider", ...}.
    ui: Optional[dict[str, Any]] = None
    # Optional validation hints enforced by the UI before applying values.
    validation: Optional[dict[str, Any]] = None
    # Optional item schema for list inputs, especially list[json].
    item: Optional[dict[str, Any]] = None
    # Optional object field schema for json/dict inputs.
    fields: Optional[dict[str, Any]] = None


@dataclass
class OutputSpec:
    type: str
    description: str = ""


def input(  # noqa: A002 — shadowing `input` matches the docs' DSL surface
    type: str,
    description: str = "",
    default: Any = None,
    options: Optional[list[Any]] = None,
    lines: int = 1,
    optional: bool = False,
    display_name: str = "",
    ui: Optional[dict[str, Any]] = None,
    validation: Optional[dict[str, Any]] = None,
    item: Optional[dict[str, Any]] = None,
    fields: Optional[dict[str, Any]] = None,
) -> InputSpec:
    return InputSpec(
        type=type,
        description=description,
        default=default,
        options=options,
        lines=lines,
        optional=optional,
        display_name=display_name,
        ui=ui,
        validation=validation,
        item=item,
        fields=fields,
    )


def output(type: str, description: str = "") -> OutputSpec:  # noqa: A002
    hint = validate_output_type(type)
    if hint is not None:
        # Surface the specific error class that the program loader catches
        # so we get a clean agent-visible message on import.
        raise DSLMisuseError(
            f"invalid output type {type!r}",
            suggestion=hint,
        )
    return OutputSpec(type=type, description=description)


class RecipeDecorated:
    """Wraps the user's recipe function with its schema metadata."""

    __slots__ = ("fn", "name", "inputs_schema", "outputs_schema")

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str,
        inputs_schema: dict[str, InputSpec],
        outputs_schema: dict[str, OutputSpec],
    ) -> None:
        self.fn = fn
        self.name = name
        self.inputs_schema = inputs_schema
        self.outputs_schema = outputs_schema

    def __call__(self, *args, **kwargs):  # allow direct invocation during tests
        return self.fn(*args, **kwargs)

    @property
    def __name__(self) -> str:
        return self.fn.__name__


def recipe(
    *,
    name: str = "",
    inputs: Optional[dict[str, InputSpec]] = None,
    outputs: Optional[dict[str, OutputSpec]] = None,
):
    inputs = inputs or {}
    outputs = outputs or {}

    def wrap(fn: Callable[..., Any]) -> RecipeDecorated:
        return RecipeDecorated(
            fn,
            name=name or fn.__name__,
            inputs_schema=dict(inputs),
            outputs_schema=dict(outputs),
        )

    return wrap


# ----- phase() context manager ----------------------------------------------


@contextlib.contextmanager
def phase(name: str):
    ctx = current_context()
    frame = ctx.current_frame
    frame.phase_stack.append(name)
    try:
        yield
    finally:
        popped = frame.phase_stack.pop()
        assert popped == name, "phase stack corruption"


# ----- Static / dynamic param split ----------------------------------------


def _callback_fingerprint(callback: Callable) -> str:
    """Hash a callback's body + captured state so lambda edits bust the diff.

    Why: ``graph_diff._def_hash`` has no signal for what a ``foreach``
    wrapper's callback actually does — every ``lambda`` hashes on
    ``callback_name="lambda"`` alone. Editing ``prompt="fox"`` to
    ``prompt="duck"`` inside a foreach body leaves the wrapper in
    ``diff.unchanged`` with its pre-edit COMPLETED result, and downstream
    ``hitl.select`` reads stale candidates.

    Covers co_code (logic), co_consts (string/number literals), co_freevars
    (closure names) and closure cell contents (values captured from the
    enclosing scope). Falls back to ``repr(callback)`` for C-implemented
    callables that lack ``__code__``.
    """
    h = hashlib.sha256()
    code = getattr(callback, "__code__", None)
    if code is None:
        h.update(repr(callback).encode())
        return h.hexdigest()
    h.update(code.co_code)
    try:
        h.update(repr(code.co_consts).encode())
    except Exception:
        pass
    h.update(repr(code.co_freevars).encode())
    for cell in getattr(callback, "__closure__", None) or ():
        try:
            h.update(repr(cell.cell_contents).encode())
        except ValueError:
            h.update(b"<empty-cell>")
    return h.hexdigest()


def _collect_noderefs(value: Any) -> list[NodeRef]:
    out: list[NodeRef] = []
    if isinstance(value, NodeRef):
        out.append(value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_collect_noderefs(item))
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_collect_noderefs(v))
    return out


def _split_static_dynamic(params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate literal (static) params from upstream NodeRefs (dynamic).

    Values that are plain Python (scalars, literal lists/dicts of scalars)
    count as static and contribute to definition_hash. Values that contain
    any NodeRef are dynamic — the whole parameter binding is kept and the
    evaluator resolves upstream values at runtime.
    """
    static: dict[str, Any] = {}
    dynamic: dict[str, Any] = {}
    for k, v in params.items():
        if _collect_noderefs(v):
            dynamic[k] = v
        else:
            static[k] = v
    return static, dynamic


def _register_nested_equation(
    ctx: BuildContext,
    kind: str,
    equation_type: EquationType,
    definition: dict[str, Any],
    dynamic_bindings: dict[str, Any],
    collection: bool = False,
    iteration_key_source: Optional[IterationKeySource] = None,
    shape: Optional[Shape] = None,
    extra_deps: Optional[Iterable[str]] = None,
) -> NodeRef:
    frame = ctx.current_frame
    pos = frame.next_positional(kind)
    key = make_nested_dsl_key(frame.parent_key, kind, pos)

    dep_set = {
        ref.equation_key
        for ref in _collect_noderefs(list(dynamic_bindings.values()))
    }
    if extra_deps:
        dep_set.update(extra_deps)
    deps = sorted(dep_set)
    eq = Equation(
        key=key,
        equation_type=equation_type,
        definition=definition,
        dependencies=deps,
        phase_path=list(frame.phase_stack),
    )
    eq.definition.setdefault("_dynamic", dynamic_bindings)
    ctx.graph.add_equation(eq)
    frame.registered_equations.append((tuple(frame.phase_stack), key))
    return NodeRef(
        equation_key=key,
        collection=collection,
        iteration_key_source=iteration_key_source,
        shape=shape,
    )


# ----- Tool registry validation --------------------------------------------


def _tool_id_is_known(tool_id: str) -> Optional[bool]:
    """Best-effort STP registry lookup for tool_id.

    Returns True/False when the registry has at least one provider loaded,
    None otherwise. An empty registry means tests (no providers registered)
    or a half-initialized app — neither case should fail graph construction.
    """
    try:
        from providers.registry import ProviderRegistry
    except Exception:
        return None
    try:
        registry = ProviderRegistry.get_instance()
        all_tools = registry.list_all_tools()
        if not all_tools:
            # Empty registry — we can't tell whether the id is valid; defer.
            return None
        return registry.get_tool(tool_id) is not None
    except Exception:
        return None


def _get_tool_schema(tool_id: str) -> Optional[dict]:
    """Best-effort STP registry lookup for a tool's single parameter_schema.

    Returns None when the registry is unavailable or the tool isn't
    registered — callers must treat that as "can't validate" and move on.
    """
    try:
        from providers.registry import ProviderRegistry
    except Exception:
        return None
    try:
        registry = ProviderRegistry.get_instance()
        pair = registry.get_tool(tool_id)
    except Exception:
        return None
    if pair is None:
        return None
    _, descriptor = pair
    param_schema = getattr(descriptor, "parameter_schema", None) or {}
    return param_schema if isinstance(param_schema, dict) else {}


def _validate_tool_call_shapes(
    tool_id: str,
    params: dict[str, Any],
) -> None:
    """Cross-check a ``tool(tool_id, **params)`` call against its schema.

    The DSL's ``tool()`` takes one flat kwargs space, matching the tool's
    single ``parameter_schema`` (which holds everything — prompt, images,
    cfg, ...). We validate the call against that one schema.

    Raises ``DSLMisuseError`` on positively-detected mismatches:

    - unknown kwarg (not declared in parameter_schema)
    - required input missing or ``None``
    - static literal type disagrees with the declared type
    - dynamic NodeRef shape disagrees with the declared type (scalar vs
      array is the high-leverage case)

    ``Unknown`` shapes always pass — this validator is additive, it never
    trips on opaque upstreams.
    """
    # `params_from` is a synthesized cross-tool convenience (reuse a prior
    # result's recorded parameters), not part of any tool's parameter_schema —
    # validate it as a single media id and exempt it from the schema checks.
    pf = params.get("params_from")
    if pf is not None and not isinstance(pf, (int, NodeRef)):
        raise DSLMisuseError(
            f"tool({tool_id!r}): params_from must be a single media id (int)",
            suggestion=(
                "Pass params_from=<media_id> to start from that image's recorded "
                "generation parameters, then override only the kwargs you want to change."
            ),
        )

    param_schema = _get_tool_schema(tool_id)
    if param_schema is None:
        return
    expectations = parse_tool_param_expectations(param_schema)
    if not expectations:
        return

    # Reject kwargs that don't appear in either schema. This is how we catch
    # e.g. ``parameters={...}`` (a kwarg literally named "parameters") — the
    # agent was treating tool() like call_tool's nested API.
    unknown = [name for name in params if name not in expectations and name not in RESERVED_TOOL_KWARGS]
    if unknown:
        names = ", ".join(repr(n) for n in sorted(unknown))
        known = sorted(expectations.keys())
        raise DSLMisuseError(
            f"tool({tool_id!r}): unknown kwarg(s) {names}",
            suggestion=(
                f"tool() takes a flat kwargs space — pass each input or "
                f"parameter directly (e.g. resolution=3200), NOT nested "
                f"inside a parameters={{...}} dict. "
                f"The tool declares these kwargs: {known}. "
                f"Run get_schema(tool_id={tool_id!r}) to confirm the names."
            ),
        )

    # Required inputs must be present with a non-None binding.
    missing: list[str] = []
    for name, exp in expectations.items():
        if not exp.required:
            continue
        if name not in params or params[name] is None:
            missing.append(name)
    if missing:
        names = ", ".join(repr(n) for n in missing)
        raise DSLMisuseError(
            f"tool({tool_id!r}): required input(s) {names} missing",
            suggestion=(
                f"The tool declares these required inputs: "
                f"{sorted(n for n, e in expectations.items() if e.required)}. "
                "Pass them as keyword arguments to tool()."
            ),
        )

    # Shape conformance for provided params.
    for name, value in params.items():
        exp = expectations.get(name)
        if exp is None or exp.kind == "unknown":
            continue
        shape = _shape_of_param_value(value)
        if not _shape_matches_expectation(shape, exp):
            raise DSLMisuseError(
                f"tool({tool_id!r}): parameter {name!r} shape mismatch",
                suggestion=_tool_param_suggestion(name, shape, exp),
            )


def _shape_of_param_value(value: Any) -> Shape:
    if isinstance(value, NodeRef):
        return value.shape if value.shape is not None else UNKNOWN
    if isinstance(value, list) and all(isinstance(x, NodeRef) for x in value):
        elements = [x.shape if x.shape is not None else UNKNOWN for x in value]
        first = elements[0] if elements else UNKNOWN
        return ListShape(element=first)
    return shape_from_literal(value)


def _shape_matches_expectation(shape: Shape, exp: ToolParamExpectation) -> bool:
    if exp.kind == "scalar":
        assert exp.scalar_kind is not None
        return shape_matches_scalar_kind(shape, exp.scalar_kind)
    if exp.kind == "array":
        return shape_matches_array(shape, exp.array_element_kind)
    return True


def _tool_param_suggestion(
    name: str,
    shape: Shape,
    exp: ToolParamExpectation,
) -> str:
    got = describe_shape(shape)
    if exp.kind == "array":
        elem = exp.array_element_kind or "value"
        if isinstance(shape, Scalar):
            return (
                f"tool param {name!r} expects a list of {elem}; got a single "
                f"{got}. Wrap the node in a list literal "
                f"({name}=[single_node]) or pass a collection from "
                "foreach/hitl.select(count>1)."
            )
        return (
            f"tool param {name!r} expects a list of {elem}; got {got}. "
            "Extract or construct a list before passing it."
        )
    # scalar
    want = exp.scalar_kind or "value"
    if isinstance(shape, ListShape):
        return (
            f"tool param {name!r} expects a single {want}; got a list. "
            "If the upstream is a foreach output or hitl.select(count>1), "
            "pick one element via hitl.select(count=1) or code(\"xs[0]\", ...)."
        )
    return (
        f"tool param {name!r} expects {want}; got {got}. "
        "Check get_schema(tool_id=...) for the right type."
    )


# ----- Core primitives: tool / llm / code -----------------------------------


_TASK_TYPE_MISSING = object()


def tool(tool_id: str, *, task_type: Any = _TASK_TYPE_MISSING, **params) -> NodeRef:
    """Registers a tool_call equation. Returns a NodeRef for a single call.

    ``task_type`` is required and must be one of the tool's declared task
    types (e.g. ``"text-to-image"``, ``"image-to-image"``). It pins what the
    call is doing so the recipe row can render as the action ("Generate
    Image") instead of the model name, and so we don't have to reverse-
    engineer it from the tool_id slug. Use ``get_schema(tool_id=...)`` to see
    the tool's declared ``task_types``.

    To produce N outputs, wrap the call in a foreach — each iteration is its
    own equation and can be invalidated independently.
    """
    if not isinstance(tool_id, str) or not tool_id:
        raise DSLMisuseError(
            "tool(): tool_id must be a non-empty string",
            suggestion="Use a full STP tool id like 'comfyui:flux-klein-9b'.",
        )
    # Sentinel default lets us raise DSLMisuseError (with a helpful agent-
    # facing suggestion) instead of Python's bare TypeError when the agent
    # forgets the kwarg.
    if task_type is _TASK_TYPE_MISSING or not isinstance(task_type, str) or not task_type:
        raise DSLMisuseError(
            "tool(): task_type is required and must be a non-empty string",
            suggestion=(
                "Pass task_type=<one of the tool's declared task_types>, e.g. "
                "tool('comfyui:flux-klein-9b', task_type='text-to-image', prompt=...). "
                "Run get_schema(tool_id=...) to see the tool's declared task_types."
            ),
        )

    # Validate task_type against the tool's declared task_types when the
    # registry has the tool. We keep tool_id validation itself deferred (the
    # registry may still be discovering providers at parse time), but if the
    # tool *is* known, the agent gave us enough to fail loud on a bogus
    # task_type rather than letting it land in the equation and mislabel the
    # row downstream.
    declared = _tool_declared_task_types(tool_id)
    if declared is not None and task_type not in declared:
        raise DSLMisuseError(
            f"tool(): task_type {task_type!r} is not declared by {tool_id!r}",
            suggestion=(
                f"Use one of: {', '.join(sorted(declared))}. "
                "Run get_schema(tool_id=...) to confirm."
            ),
        )

    # Tool-id validation is deferred to runtime. A registry that happens to
    # have some providers loaded but is still discovering others (common at
    # boot, when providers come online asynchronously) would otherwise fail
    # the recipe at parse time. The engine treats an unknown tool at
    # execution time as "waiting" and self-heals when the tool appears.
    _validate_tool_call_shapes(tool_id, params)

    ctx = current_context()
    static, dynamic = _split_static_dynamic(params)
    definition = {
        "tool_id": tool_id,
        "task_type": task_type,
        "params": dict(static),
        "definition_hash": definition_hash_for_tool(tool_id, dict(static)),
    }
    node_shape = _tool_output_element_shape(tool_id)
    return _register_nested_equation(
        ctx,
        "tool",
        EquationType.TOOL_CALL,
        definition,
        dynamic,
        shape=node_shape,
    )


def _tool_declared_task_types(tool_id: str) -> Optional[List[str]]:
    """Best-effort lookup of a tool's declared task_types from the registry.

    Returns ``None`` when the registry is unavailable or doesn't know the
    tool — in that case task_type validation is deferred (same rationale as
    tool_id validation in ``tool()``). Returns a list when the tool is known
    so the caller can check membership.
    """
    try:
        from providers.registry import ProviderRegistry
    except Exception:
        return None
    try:
        registry = ProviderRegistry.get_instance()
        pair = registry.get_tool(tool_id)
    except Exception:
        return None
    if pair is None:
        return None
    _, descriptor = pair
    declared = list(getattr(descriptor, "task_types", []) or [])
    if not declared:
        # Some descriptors only set the legacy single task_type field.
        legacy = getattr(descriptor, "task_type", None)
        if isinstance(legacy, str) and legacy:
            declared = [legacy]
    return declared if declared else None


def _tool_output_element_shape(tool_id: str) -> Shape:
    """Infer a single tool invocation's output shape from its registry entry.

    Best-effort — an STP descriptor that doesn't declare output_schema,
    or a registry that isn't available, returns ``Scalar(media)`` because
    the overwhelming majority of tools in the DSL's intended space are
    image/video/audio generators. Wrong-but-permissive is fine here;
    shape_matches_scalar_kind's media↔int rule absorbs the minority case.
    """
    try:
        from providers.registry import ProviderRegistry
    except Exception:
        return Scalar(kind="media")
    try:
        registry = ProviderRegistry.get_instance()
        pair = registry.get_tool(tool_id)
    except Exception:
        return Scalar(kind="media")
    if pair is None:
        return Scalar(kind="media")
    _, descriptor = pair
    schema = getattr(descriptor, "output_schema", None)
    if not isinstance(schema, dict):
        return Scalar(kind="media")
    props = schema.get("properties") or {}
    if not isinstance(props, dict):
        return Scalar(kind="media")
    # Heuristic: any property whose format hints at a media blob → media.
    for prop in props.values():
        if not isinstance(prop, dict):
            continue
        if (
            prop.get("type") == "string"
            and prop.get("format") in {"binary", "file-path", "media"}
        ):
            return Scalar(kind="media")
    return Scalar(kind="media")


_LLM_VALID_MODELS = ("agent", "agent-fast")


def llm(
    prompt: Any,
    *,
    model: str = "agent",
    think: bool = False,
    response_format: Any = None,
    system: Optional[str] = None,
    images: Any = None,
    n: int = 1,
) -> NodeRef:
    ctx = current_context()

    if model not in _LLM_VALID_MODELS:
        raise DSLMisuseError(
            f"llm(): model must be one of {list(_LLM_VALID_MODELS)}; got {model!r}",
            suggestion=(
                "Use model='agent' (default) for anything requiring reasoning, "
                "structured output, nuance, or careful prose. Use model='agent-fast' "
                "only for simple, high-volume classification, extraction, or boilerplate "
                "generation where latency matters more than quality. Stimma resolves "
                "these aliases to the user's configured LLMs — do not pass concrete "
                "model names like 'claude-sonnet' or 'gpt-4o'."
            ),
        )

    if not isinstance(think, bool):
        raise DSLMisuseError(
            f"llm(): think must be True or False; got {think!r}",
        )

    if not isinstance(n, int) or n < 1:
        raise DSLMisuseError(
            f"llm(n={n!r}): n must be a positive integer",
            suggestion=(
                "Omit n= (default 1) for a single call. Pass n=N for N diverse "
                "outputs produced by a single batched LLM call; each slot is "
                "independently invalidatable and solo-regenerated with peer "
                "context. Use n=N only when you want slot-level re-roll."
            ),
        )

    images_binding = _validate_llm_images(images)

    prompt_template, prompt_dynamic = _template_of(prompt)
    system_template, system_dynamic = _template_of(system) if system is not None else ("", {})

    dynamic: dict[str, Any] = {}
    if prompt_dynamic:
        dynamic["prompt"] = prompt_dynamic
    if isinstance(prompt, NodeRef):
        dynamic["prompt_value"] = prompt
    if system_dynamic:
        dynamic["system"] = system_dynamic
    if images_binding is not None:
        dynamic["images"] = images_binding

    if n == 1:
        definition = {
            "model": model,
            "think": think,
            "prompt_template": prompt_template,
            "system_template": system_template,
            "response_format": response_format,
            "definition_hash": definition_hash_for_llm(
                model,
                prompt_template,
                system_template=system_template,
                response_format=response_format,
                think=think,
            ),
        }
        return _register_nested_equation(
            ctx,
            "llm",
            EquationType.LLM_CALL,
            definition,
            dynamic,
            shape=shape_from_response_format(response_format),
        )

    # n > 1: batched generation with per-slot invalidation.
    # Register 1 LLM_BATCH equation (runs once, produces N items) and N
    # LLM_SLOT equations (one per index, depend on batch, carry the user-
    # visible value). The returned NodeRef points at the batch and is
    # marked collection=True with positional iteration keys "0".."N-1"
    # so foreach() over it iterates in slot order, with each iteration
    # depending on its specific slot equation (via foreach early-expansion
    # in engine._early_expansion_items). That path is what makes per-slot
    # invalidation cascade to the downstream items a user actually cares
    # about — e.g. re-rolling one prompt re-fires only the image group
    # that prompt feeds into, not all N.
    batch_definition = {
        "model": model,
        "think": think,
        "prompt_template": prompt_template,
        "system_template": system_template,
        "response_format": response_format,
        "n": n,
        "definition_hash": definition_hash_for_llm_batch(
            model,
            prompt_template,
            n,
            system_template=system_template,
            response_format=response_format,
            think=think,
        ),
    }
    slot_shape = shape_from_response_format(response_format)
    batch_node = _register_nested_equation(
        ctx,
        "llm",
        EquationType.LLM_BATCH,
        batch_definition,
        dynamic,
        collection=True,
        iteration_key_source=IterationKeySource(
            IterationKeySource.POSITIONAL, "llm_slot"
        ),
        shape=ListShape(element=slot_shape),
    )
    batch_key = batch_node.equation_key

    # Set the batch's iteration-keys cache so foreach early-expansion can
    # fire before the batch evaluates. Matches the pattern used by foreach
    # wrappers themselves (engine.py _expand_foreach sets it there).
    batch_eq = ctx.graph.get(batch_key)
    setattr(batch_eq, "_iteration_keys_cache", [str(i) for i in range(n)])

    for i in range(n):
        slot_key = make_nested_foreach_iteration_key(batch_key, "slot", str(i))
        slot_definition = {
            "control_kind": "llm_slot",
            "batch_key": batch_key,
            "slot_index": i,
            "iteration_key": str(i),
            "response_format": response_format,
            "definition_hash": definition_hash_for_llm_slot(batch_key, i),
        }
        # Slot carries the same prompt/system/images bindings as the batch
        # so the solo-gen path (attempt > 1) can re-render the user's
        # template without going back to the batch's resolved_inputs —
        # which aren't persisted. "batch" is an extra binding that
        # resolves to the batch equation's list result.
        slot_dynamic: dict[str, Any] = dict(dynamic)
        slot_dynamic["batch"] = NodeRef(equation_key=batch_key)
        slot_deps = sorted({
            ref.equation_key for ref in _collect_noderefs(list(slot_dynamic.values()))
        })
        slot_eq = Equation(
            key=slot_key,
            equation_type=EquationType.LLM_SLOT,
            definition=slot_definition,
            dependencies=slot_deps,
            phase_path=list(ctx.current_frame.phase_stack),
        )
        slot_eq.definition.setdefault("_dynamic", slot_dynamic)
        ctx.graph.add_equation(slot_eq)
        ctx.current_frame.registered_equations.append(
            (tuple(ctx.current_frame.phase_stack), slot_key)
        )

    batch_node.known_iteration_keys = [str(i) for i in range(n)]
    return batch_node


def _validate_llm_images(images: Any) -> Any:
    """Validate the ``images=`` argument to ``llm()``.

    Returns the binding to register in ``_dynamic['images']`` (either a single
    NodeRef or a list of NodeRefs), or ``None`` when no images were passed.
    Rejects non-media shapes and non-NodeRef literals at build time so vision
    failures surface with a clear message before evaluation.
    """
    if images is None:
        return None

    def _is_media_scalar(shape: Any) -> bool:
        if shape is None or shape is UNKNOWN:
            return True
        if isinstance(shape, Scalar):
            return shape.kind in ("media", "int", "any")
        if isinstance(shape, DictShape):
            fields = shape.field_map
            return "media_id" in fields or "media" in fields
        return False

    def _is_media_list(shape: Any) -> bool:
        return isinstance(shape, ListShape) and _is_media_scalar(shape.element)

    if isinstance(images, NodeRef):
        shape = images.shape
        if _is_media_scalar(shape) or _is_media_list(shape):
            return images
        raise DSLMisuseError(
            f"llm(images=...): expected a media node or list of media nodes, "
            f"got shape {describe_shape(shape)}",
            suggestion=(
                "images= must be a media node (produced by tool() with image "
                "output, passed in via a recipe input of type='media', or a "
                "selected web_search image row that will carry media_id after "
                "URL-media promotion), or a collection of them. If the "
                "upstream is plain text, pass it through the prompt instead."
            ),
        )

    if isinstance(images, (list, tuple)):
        if not images:
            raise DSLMisuseError(
                "llm(images=[]): empty list",
                suggestion="Omit images= entirely when no image is available.",
            )
        items = list(images)
        for item in items:
            if not isinstance(item, NodeRef):
                raise DSLMisuseError(
                    f"llm(images=[...]): every element must be a media node; "
                    f"got {type(item).__name__}",
                    suggestion=(
                        "Build the list from media nodes only — either tool() "
                        "results or recipe inputs of type='media'. Plain strings, "
                        "paths, or ints are not accepted."
                    ),
                )
            if not _is_media_node(item):
                raise DSLMisuseError(
                    f"llm(images=[...]): list element has non-media shape "
                    f"{describe_shape(item.shape)}",
                    suggestion=(
                        "Every element of images= must resolve to a media id. "
                        "Check the upstream equation's output type."
                    ),
                )
        return items

    raise DSLMisuseError(
        f"llm(images=...): expected a media node or a list of media nodes; "
        f"got {type(images).__name__}",
        suggestion=(
            "Pass the NodeRef returned by tool() (for a single image) or a "
            "list of NodeRefs (e.g. the result of a foreach over tool() "
            "calls). Do not pass raw paths, bytes, or strings."
        ),
    )


_CODE_SCALAR_OUTPUT_TYPES = ("json", "media", "text", "markdown")
_CODE_LIST_OUTPUT_TYPES = (
    "list[json]",
    "list[str]",
    "list[int]",
    "list[float]",
    "list[bool]",
    "list[media]",
    "list[markdown]",
)
_CODE_VALID_OUTPUT_TYPES = _CODE_SCALAR_OUTPUT_TYPES + _CODE_LIST_OUTPUT_TYPES


def code(
    fn_or_source: Callable | str,
    *,
    inputs: Optional[dict[str, Any]] = None,
    output_type: str = "json",
    description: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> NodeRef:
    """Register a ``code`` equation.

    The canonical form passes a Python callable — lambda or ``def`` — that
    takes resolved values from ``inputs`` and returns the computed value::

        prompt = code(lambda n: f"photo of {n}", inputs={"n": name}, output_type="text")

    The string form is accepted for back-compat: ``code("name.upper()",
    inputs={"name": name})``. It's executed the same way, but the callable
    form avoids the double-escaping class of bugs that comes from writing
    Python-inside-Python-inside-a-string.
    """
    inputs = inputs or {}

    if isinstance(fn_or_source, str):
        fn: Optional[Callable] = None
        source = fn_or_source
    elif callable(fn_or_source):
        fn = fn_or_source
        _validate_callable_closure(fn)
        _validate_callable_params(fn, inputs)
        source = _extract_canonical_source(fn)
    else:
        raise DSLMisuseError(
            f"code(): expected a callable or a source string, got "
            f"{type(fn_or_source).__name__}",
            suggestion=(
                "Pass a lambda or a named function: "
                "code(lambda x: x.upper(), inputs={'x': upstream_node}, output_type='text')"
            ),
        )

    if output_type not in _CODE_VALID_OUTPUT_TYPES:
        raise DSLMisuseError(
            f"code(): output_type must be one of "
            f"{list(_CODE_VALID_OUTPUT_TYPES)}; got {output_type!r}",
            suggestion=(
                "For a single value: 'json' (dict/scalar), 'text' (string), "
                "'media' (media id). For an iterable result the agent will "
                "foreach over: 'list[json]', 'list[str]', 'list[int]', "
                "'list[float]', 'list[bool]', 'list[media]'."
            ),
        )
    is_collection = output_type.startswith("list[")
    ctx = current_context()
    static_inputs: dict[str, Any] = {}
    dynamic_inputs: dict[str, Any] = {}
    for k, v in inputs.items():
        if _collect_noderefs(v):
            dynamic_inputs[k] = v
        else:
            static_inputs[k] = v

    _validate_code_subscripts(source, inputs)

    clean_description: Optional[str] = None
    if description is not None:
        if not isinstance(description, str):
            raise DSLMisuseError(
                f"code(): description must be a string, got "
                f"{type(description).__name__}",
                suggestion="Pass a short human-readable phrase, e.g. description=\"Build Prompt\".",
            )
        clean_description = description.strip() or None

    clean_subtitle: Optional[str] = None
    if subtitle is not None:
        if not isinstance(subtitle, str):
            raise DSLMisuseError(
                f"code(): subtitle must be a string, got "
                f"{type(subtitle).__name__}",
                suggestion="Pass subtitle as a plain string or omit it.",
            )
        clean_subtitle = subtitle.strip() or None

    definition = {
        "source": source,
        "fn": fn,
        "output_type": output_type,
        "static_inputs": static_inputs,
        "description": clean_description,
        "subtitle": clean_subtitle,
        "definition_hash": definition_hash_for_code(source, output_type=output_type),
    }
    ik_source = (
        IterationKeySource(IterationKeySource.POSITIONAL, "code_item")
        if is_collection
        else None
    )
    return _register_nested_equation(
        ctx,
        "code",
        EquationType.CODE,
        definition,
        {"inputs": dynamic_inputs} if dynamic_inputs else {},
        collection=is_collection,
        iteration_key_source=ik_source,
        shape=shape_from_code_output_type(output_type),
    )


def _extract_canonical_source(fn: Callable) -> str:
    """Return a canonical, deterministic source form of ``fn``.

    Used both to populate the ``code()`` equation's ``source`` (so the
    subscript validator can introspect it) and to feed ``definition_hash_for_code``
    (so whitespace/formatting differences don't bust the cache).

    ``inspect.getsource`` returns the *line(s)* containing the callable,
    which for an inline lambda can be a fragment like ``lambda n: …,``.
    ``ast.parse`` still accepts that (as a tuple expression), and
    ``ast.walk`` finds the Lambda/FunctionDef node. ``ast.unparse`` then
    produces a normalized form.
    """
    try:
        raw = inspect.getsource(fn)
    except (OSError, TypeError) as exc:
        raise DSLMisuseError(
            f"code(): could not read the source of "
            f"{getattr(fn, '__name__', fn)!r}: {exc}",
            suggestion=(
                "Pass a lambda or define the helper at module level. "
                "Functions built dynamically or inside an interactive shell "
                "can't be hashed reliably."
            ),
        )
    src = textwrap.dedent(raw).strip()
    tree = None
    for attempt in (src, src.rstrip(",").rstrip()):
        try:
            tree = ast.parse(attempt)
            break
        except SyntaxError:
            continue
    if tree is None:
        raise DSLMisuseError(
            f"code(): could not parse source of "
            f"{getattr(fn, '__name__', fn)!r}: {src!r}",
            suggestion=(
                "Move the function to module level or rewrite it as a "
                "simpler lambda."
            ),
        )
    for node in ast.walk(tree):
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.unparse(node)
    raise DSLMisuseError(
        f"code(): no function or lambda found in source of "
        f"{getattr(fn, '__name__', fn)!r}",
        suggestion="Pass a lambda or a named `def` — not a method or class.",
    )


def _validate_callable_params(fn: Callable, inputs: dict[str, Any]) -> None:
    """Ensure the callable's parameter names line up with ``inputs`` keys."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return  # Builtins / C-implemented callables — skip; exec still works.
    param_names: list[str] = []
    has_var_kw = False
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            has_var_kw = True
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise DSLMisuseError(
                "code(): callable uses *args — parameters must be named "
                "to match the inputs dict.",
                suggestion="Use explicit parameter names that match each inputs key.",
            )
        param_names.append(name)
    input_keys = set(inputs.keys())
    param_set = set(param_names)
    missing = input_keys - param_set
    extra = param_set - input_keys
    if missing and not has_var_kw:
        raise DSLMisuseError(
            f"code(): inputs contains {sorted(missing)!r} but the callable "
            f"doesn't accept "
            f"{'those parameters' if len(missing) > 1 else 'that parameter'}.",
            suggestion=(
                f"Add {', '.join(sorted(missing))} to the callable's parameters "
                "so the runtime can pass the resolved values."
            ),
        )
    if extra:
        raise DSLMisuseError(
            f"code(): callable declares parameters {sorted(extra)!r} with "
            "no matching inputs entry.",
            suggestion=(
                f"Add entries for {', '.join(sorted(extra))} to inputs={{}}, "
                "or remove them from the callable's parameters."
            ),
        )


def _validate_deferred_callback_params(
    primitive: str,
    fn: Callable,
    extra_kwargs: dict[str, Any],
) -> None:
    """Ensure foreach/hitl.approve callbacks can accept runtime arguments."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return

    params = list(sig.parameters.values())
    has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    positional = [
        p for p in params
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if not positional and not has_var_pos:
        raise DSLMisuseError(
            f"{primitive}(): callback must accept the item/index as its first argument",
            suggestion=(
                f"Use a callback like lambda item: ... or "
                f"lambda item, extra_name: ... when passing extra kwargs."
            ),
        )

    consumed_first = positional[0].name if positional else None
    extra_keys = set(extra_kwargs.keys())
    accepted_kw_names = {
        p.name for p in params
        if p.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    unexpected = sorted(extra_keys - accepted_kw_names) if not has_var_kw else []
    if unexpected:
        raise DSLMisuseError(
            f"{primitive}(): extra kwarg(s) {unexpected!r} are passed to the "
            "callback, but the callback does not accept them.",
            suggestion=(
                f"Make the {primitive} kwarg name match the callback parameter "
                "name. For example, foreach(items, lambda item, prompts: ..., "
                "prompts=prompt_list) or hitl.approve(4, lambda i, prompts: ..., "
                "prompts=prompt_list, instructions='...')."
            ),
        )


def _validate_forwarded_callback_kwargs(
    primitive: str,
    fn: Callable,
    extra_kwargs: dict[str, Any],
) -> None:
    """Ensure a callback can be called as ``fn(**extra_kwargs)``."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return

    params = list(sig.parameters.values())
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    accepted_kw_names = {
        p.name
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    extra_keys = set(extra_kwargs.keys())
    unexpected = sorted(extra_keys - accepted_kw_names) if not has_var_kw else []
    if unexpected:
        raise DSLMisuseError(
            f"{primitive}(): extra kwarg(s) {unexpected!r} are passed to the "
            "callback, but the callback does not accept them.",
            suggestion=(
                f"Make the {primitive} kwarg name match the callback parameter "
                "name. For example, hitl.approve_one(lambda prompt: tool(...), "
                "prompt=headshot_prompt, instructions='...')."
            ),
        )

    missing_required: list[str] = []
    positional_only: list[str] = []
    for param in params:
        if param.default is not inspect.Parameter.empty:
            continue
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            positional_only.append(param.name)
            continue
        if param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ) and param.name not in extra_keys:
            missing_required.append(param.name)

    if positional_only:
        raise DSLMisuseError(
            f"{primitive}(): callback parameter(s) {positional_only!r} are "
            "positional-only, but this primitive forwards named kwargs.",
            suggestion="Use normal named parameters in the callback.",
        )
    if missing_required:
        raise DSLMisuseError(
            f"{primitive}(): callback requires parameter(s) "
            f"{missing_required!r} with no matching kwarg.",
            suggestion=(
                f"Pass each required callback parameter as a {primitive} kwarg, "
                "or remove it from the callback."
            ),
        )


def _validate_item_callback_kwargs(
    primitive: str,
    fn: Callable,
    extra_kwargs: dict[str, Any],
) -> None:
    """Ensure a callback can be called as ``fn(item, **extra_kwargs)``."""
    _validate_deferred_callback_params(primitive, fn, extra_kwargs)
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return

    params = list(sig.parameters.values())
    positional = [
        p for p in params
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if not positional:
        return

    extra_keys = set(extra_kwargs.keys())
    missing_required: list[str] = []
    positional_only: list[str] = []
    for param in params:
        if param.name == positional[0].name:
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            positional_only.append(param.name)
            continue
        if param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ) and param.name not in extra_keys:
            missing_required.append(param.name)

    if positional_only:
        raise DSLMisuseError(
            f"{primitive}(): callback parameter(s) {positional_only!r} after "
            "the item are positional-only, but this primitive forwards named kwargs.",
            suggestion="Use normal named parameters after the item parameter.",
        )
    if missing_required:
        raise DSLMisuseError(
            f"{primitive}(): callback requires parameter(s) "
            f"{missing_required!r} with no matching kwarg.",
            suggestion=(
                f"Pass each required callback parameter as a {primitive} kwarg, "
                "or remove it from the callback."
            ),
        )


def _validate_callable_closure(fn: Callable) -> None:
    """Reject callables that capture a NodeRef from an enclosing scope.

    Closures over NodeRefs don't work at evaluation time — the runtime has
    no way to resolve a captured node through a closure cell. Values must
    flow in through ``inputs=`` so the runtime can wait for them.
    """
    if fn.__closure__ is None:
        return
    freevars = fn.__code__.co_freevars
    for name, cell in zip(freevars, fn.__closure__):
        try:
            val = cell.cell_contents
        except ValueError:
            continue  # empty cell — can happen during module init.
        if _contains_noderef(val):
            raise DSLMisuseError(
                f"code(): the callable captured {name!r} from the outer "
                "scope, and that value is (or contains) a value reference "
                "(NodeRef). Nodes only resolve when passed via inputs=.",
                suggestion=(
                    f"Pass {name} through the inputs dict: "
                    f"code(lambda {name}: ..., "
                    f"inputs={{'{name}': {name}}}, output_type='...')"
                ),
            )


def _contains_noderef(val: Any) -> bool:
    """True if ``val`` is a NodeRef or shallowly contains one."""
    if isinstance(val, NodeRef):
        return True
    if isinstance(val, (list, tuple)):
        return any(_contains_noderef(x) for x in val)
    if isinstance(val, dict):
        return any(_contains_noderef(x) for x in val.values())
    return False


def _validate_code_subscripts(source: str, inputs: dict[str, Any]) -> None:
    """Flag ``code("data['foo']")`` when ``foo`` isn't in the upstream's
    declared shape. Only triggers on closed DictShape upstreams — unknown
    or open shapes pass through silently.
    """
    binding_shapes: dict[str, Shape] = {}
    for k, v in inputs.items():
        if isinstance(v, NodeRef):
            binding_shapes[k] = v.shape if v.shape is not None else UNKNOWN
        else:
            binding_shapes[k] = shape_from_literal(v)
    bad = find_bad_subscripts(source, binding_shapes)
    if not bad:
        return
    first = bad[0]
    available = ", ".join(repr(k) for k in first.available)
    raise DSLMisuseError(
        f"code(): {first.binding_name}[{first.key!r}] — key not in "
        f"upstream's declared shape",
        suggestion=(
            f"{first.binding_name!r} has keys: {available}. If the field "
            "name is different in your llm() response_format schema, "
            "match the spelling. If the schema is wrong, fix the llm() "
            "call instead of the code() access."
        ),
    )


# ----- info() primitive -----------------------------------------------------


def info(
    body: str,
    *,
    title: str,
    subtitle: str = "",
    inputs: Optional[dict[str, Any]] = None,
) -> NodeRef:
    """Register an ``info`` equation — a narrative card that tells the user
    something worth knowing about the run.

    ``title`` is the short label shown on the collapsed row (replaces the
    generic word "Info"). ``subtitle`` is an optional second line of
    context. Both are static strings — no placeholder substitution.

    ``body`` is a markdown string with ``{name}`` placeholders. Each
    placeholder is substituted with the resolved value of the matching
    ``inputs`` entry. Lists/tuples render as markdown bullet lists, dicts
    render as ``**key:** value`` lines, and other types use ``str(value)``.
    Inputs may be literals or NodeRefs.

    Any NodeRef input that produces media automatically contributes its
    ``result_media_ids`` to this info node, so the card renders the
    upstream thumbnails alongside the rendered markdown.

    The node stays hidden in the steps view until the body is emitted —
    empty info has no value — and auto-expands once visible.
    """
    if not isinstance(body, str):
        raise DSLMisuseError(
            f"info(): body must be a str, got {type(body).__name__}",
            suggestion="Pass a markdown string literal with {name} placeholders.",
        )
    if not isinstance(title, str) or not title.strip():
        raise DSLMisuseError(
            "info(): title is required and must be a non-empty string",
            suggestion='Pass title="Short Label" — this replaces the word "Info".',
        )
    if not isinstance(subtitle, str):
        raise DSLMisuseError(
            f"info(): subtitle must be a str, got {type(subtitle).__name__}",
            suggestion="Pass subtitle as a plain string or omit it.",
        )

    ctx = current_context()
    inputs = inputs or {}
    static_inputs: dict[str, Any] = {}
    dynamic_inputs: dict[str, Any] = {}
    for k, v in inputs.items():
        if _collect_noderefs(v):
            dynamic_inputs[k] = v
        else:
            static_inputs[k] = v

    definition = {
        "template": body,
        "title": title.strip(),
        "subtitle": subtitle.strip(),
        "static_inputs": static_inputs,
        "definition_hash": definition_hash_for_info(body, static_inputs),
    }
    # An info card placed inside a phase is a narrative summary of that
    # phase — "here's what the recipe just did". Make it implicitly depend
    # on every equation already registered in this phase (or any nested
    # phase beneath it), so it renders only once that work is complete.
    # Without this, an info whose only explicit inputs are recipe inputs
    # resolves immediately and shows "done" before the phase's LLM/tool/
    # foreach work has even started.
    frame = ctx.current_frame
    implicit_deps = frame.equations_in_phase(frame.phase_stack)
    return _register_nested_equation(
        ctx,
        "info",
        EquationType.INFO,
        definition,
        {"inputs": dynamic_inputs} if dynamic_inputs else {},
        shape=Scalar(kind="str"),
        extra_deps=implicit_deps,
    )


# ----- Library-assembly primitives (set / grid / document) -----------------


def _validate_items_list_of_media(primitive: str, items: Any) -> Any:
    """Coerce `items` into a dynamic-binding value that resolves to list[media].

    Accepted forms:
      - A collection NodeRef whose shape is list[media] (from foreach output,
        hitl.select(count=N>1), etc.)
      - A Python list of media NodeRefs
    """
    if isinstance(items, NodeRef):
        if not items.collection:
            raise DSLMisuseError(
                f"{primitive}(): items node {items.equation_key!r} is not a collection",
                suggestion=(
                    "items must resolve to a list of media ids. Pass the node "
                    "returned by foreach(...) or hitl.select(count=N>1)."
                ),
            )
        shape = items.shape
        if shape is not None and not shape_matches_array(shape, "media"):
            raise DSLMisuseError(
                f"{primitive}(): items shape is {describe_shape(shape)}, "
                "expected list[media]",
                suggestion=(
                    "items must resolve to a list of media ids. If the upstream "
                    "is an llm() result, extract the list field with code() and "
                    "ensure the elements are media nodes."
                ),
            )
        return items
    if isinstance(items, (list, tuple)):
        if not items:
            raise DSLMisuseError(
                f"{primitive}(items=[]): items list must not be empty",
            )
        for idx, it in enumerate(items):
            if not isinstance(it, NodeRef):
                raise DSLMisuseError(
                    f"{primitive}(items=[...][{idx}]): each element must be a "
                    f"media NodeRef, got {type(it).__name__}",
                    suggestion=(
                        "Build the list from media nodes only — results of "
                        "tool() calls or media recipe inputs. Plain ints, "
                        "paths, and strings are not accepted."
                    ),
                )
            shape = it.shape
            if shape is not None and not shape_matches_scalar_kind(shape, "media"):
                raise DSLMisuseError(
                    f"{primitive}(items=[...][{idx}]): element shape is "
                    f"{describe_shape(shape)}, expected media",
                )
        return list(items)
    raise DSLMisuseError(
        f"{primitive}(): items must be a list NodeRef or a list of media nodes; "
        f"got {type(items).__name__}",
        suggestion=(
            "Pass a collection node (foreach result, hitl.select(count>1)) "
            "or a Python list of media NodeRefs."
        ),
    )


def create_set(
    items: Any,
    *,
    title: str = "",
    description: str = "",
) -> NodeRef:
    """Group media items into a ``.stimmaset.json`` library asset.

    ``items`` is either a collection NodeRef resolving to ``list[media]`` or
    a plain Python list of media NodeRefs. Member media are superseded on
    save (hidden from browse, visible inside the set).
    """
    if not isinstance(title, str):
        raise DSLMisuseError(
            f"create_set(): title must be a string, got {type(title).__name__}",
        )
    if not isinstance(description, str):
        raise DSLMisuseError(
            f"create_set(): description must be a string, got {type(description).__name__}",
        )
    items_binding = _validate_items_list_of_media("create_set", items)
    ctx = current_context()
    definition = {
        "title": title,
        "description": description,
        "definition_hash": definition_hash_for_create_set(title, description),
    }
    return _register_nested_equation(
        ctx,
        "create_set",
        EquationType.CREATE_SET,
        definition,
        {"items": items_binding},
        shape=Scalar(kind="media"),
    )


def create_grid(
    items: Any,
    *,
    rows: int,
    cols: int,
    row_headers: Optional[list[str]] = None,
    col_headers: Optional[list[str]] = None,
    title: str = "",
    description: str = "",
) -> NodeRef:
    """Group media items into a ``.stimmagrid.json`` parameter-sweep asset.

    ``items`` is the cells in row-major order (length must equal rows×cols).
    Both ``row_headers`` and ``col_headers`` are required for a meaningful
    grid (matches the agent-tool contract).
    """
    if not isinstance(rows, int) or rows < 1:
        raise DSLMisuseError(
            f"create_grid(rows={rows!r}): rows must be a positive integer",
        )
    if not isinstance(cols, int) or cols < 1:
        raise DSLMisuseError(
            f"create_grid(cols={cols!r}): cols must be a positive integer",
        )
    if not isinstance(title, str):
        raise DSLMisuseError(
            f"create_grid(): title must be a string, got {type(title).__name__}",
        )
    if not isinstance(description, str):
        raise DSLMisuseError(
            f"create_grid(): description must be a string, got {type(description).__name__}",
        )
    row_headers = list(row_headers or [])
    col_headers = list(col_headers or [])
    if len(row_headers) != rows:
        raise DSLMisuseError(
            f"create_grid(): expected {rows} row_headers, got {len(row_headers)}",
            suggestion=(
                "row_headers must have exactly one short label per row — the "
                "value being varied along that row (e.g., LoRA strength, seed)."
            ),
        )
    if len(col_headers) != cols:
        raise DSLMisuseError(
            f"create_grid(): expected {cols} col_headers, got {len(col_headers)}",
            suggestion=(
                "col_headers must have exactly one short label per column — "
                "the value being varied along that column."
            ),
        )
    for h in row_headers + col_headers:
        if not isinstance(h, str):
            raise DSLMisuseError(
                f"create_grid(): headers must be strings, got {type(h).__name__}",
            )
    items_binding = _validate_items_list_of_media("create_grid", items)
    # Best-effort length check when the items is a fully-known literal list.
    expected = rows * cols
    if isinstance(items_binding, list) and len(items_binding) != expected:
        raise DSLMisuseError(
            f"create_grid(): expected {expected} items ({rows}x{cols}), "
            f"got {len(items_binding)}",
        )
    ctx = current_context()
    definition = {
        "rows": rows,
        "cols": cols,
        "row_headers": row_headers,
        "col_headers": col_headers,
        "title": title,
        "description": description,
        "definition_hash": definition_hash_for_create_grid(
            rows, cols, row_headers, col_headers, title,
        ),
    }
    return _register_nested_equation(
        ctx,
        "create_grid",
        EquationType.CREATE_GRID,
        definition,
        {"items": items_binding},
        shape=Scalar(kind="media"),
    )


def create_document(
    content: Any,
    *,
    title: str = "",
    format: str = "markdown",  # noqa: A002 — matches DSL surface
) -> NodeRef:
    """Save rendered text content as a library document MediaItem.

    ``content`` is a str (static) or a NodeRef[str] (typically the output of
    ``llm()`` or ``code(output_type='text')``). ``format`` is currently
    ``"markdown"`` only — the file is saved with a matching extension.
    """
    if not isinstance(title, str):
        raise DSLMisuseError(
            f"create_document(): title must be a string, got {type(title).__name__}",
        )
    if format != "markdown":
        raise DSLMisuseError(
            f"create_document(format={format!r}): only 'markdown' is supported",
            suggestion="Omit format= or pass format='markdown'.",
        )
    if isinstance(content, NodeRef):
        shape = content.shape
        if shape is not None and not shape_matches_scalar_kind(shape, "str"):
            raise DSLMisuseError(
                f"create_document(): content shape is {describe_shape(shape)}, "
                "expected str",
                suggestion=(
                    "content must resolve to a string. Use llm() (returns a "
                    "string by default) or code(output_type='text')."
                ),
            )
        dynamic: dict[str, Any] = {"content": content}
        static_content: Optional[str] = None
    elif isinstance(content, str):
        dynamic = {}
        static_content = content
    else:
        raise DSLMisuseError(
            f"create_document(): content must be a string or a NodeRef[str]; "
            f"got {type(content).__name__}",
            suggestion=(
                "Pass an llm()/code(output_type='text') result or a literal "
                "string."
            ),
        )
    ctx = current_context()
    # When content is a static literal, fold it into the definition hash so
    # two calls with different literal content get distinct store keys.
    # NodeRef content flows through inputs_hash at evaluation time instead.
    if static_content is not None:
        def_hash = canonical_json_hash({
            "title": title,
            "format": format,
            "static_content": static_content,
        })
    else:
        def_hash = definition_hash_for_create_document(title, format)
    definition = {
        "title": title,
        "format": format,
        "static_content": static_content,
        "definition_hash": def_hash,
    }
    return _register_nested_equation(
        ctx,
        "create_document",
        EquationType.CREATE_DOCUMENT,
        definition,
        dynamic,
        shape=Scalar(kind="media"),
    )


_CREATE_IMAGE_VALID_FORMATS = ("png", "jpeg", "webp")


def create_image(
    fn: Callable,
    *,
    inputs: Optional[dict[str, Any]] = None,
    title: str = "",
    description: str = "",
    format: str = "png",  # noqa: A002 — matches DSL surface
) -> NodeRef:
    """Render a PIL image inside the recipe sandbox and save it to the library.

    This is the primitive for recipe steps that compose a single image from
    upstream media — windowpane grids, contact sheets, side-by-side
    comparisons, any custom layout a tool doesn't provide. The callable runs
    in the same sandbox as ``code()`` (PIL, numpy, etc. available) and
    returns a ``PIL.Image.Image``; the evaluator saves the result as a
    library MediaItem and returns its id.

    ``fn`` is a Python callable (lambda or ``def``) that takes the keys of
    ``inputs`` as its parameters and returns a ``PIL.Image.Image``.

    Media-typed inputs (upstream shape ``media`` or ``list[media]``) are
    pre-resolved to ``PIL.Image.Image`` / ``list[PIL.Image.Image]`` so the
    callable can paste / composite directly. Other inputs pass through as
    resolved values (same semantics as ``code()``).
    """
    inputs = inputs or {}

    if not callable(fn):
        raise DSLMisuseError(
            f"create_image(): fn must be a callable, got {type(fn).__name__}",
            suggestion=(
                "Pass a lambda or named function that takes the keys of "
                "inputs and returns a PIL.Image.Image."
            ),
        )
    _validate_callable_closure(fn)
    _validate_callable_params(fn, inputs)
    source = _extract_canonical_source(fn)

    if not isinstance(title, str):
        raise DSLMisuseError(
            f"create_image(): title must be a string, got {type(title).__name__}",
        )
    if not isinstance(description, str):
        raise DSLMisuseError(
            f"create_image(): description must be a string, "
            f"got {type(description).__name__}",
        )
    fmt = format.lower() if isinstance(format, str) else format
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in _CREATE_IMAGE_VALID_FORMATS:
        raise DSLMisuseError(
            f"create_image(format={format!r}): format must be one of "
            f"{list(_CREATE_IMAGE_VALID_FORMATS)}",
        )

    static_inputs: dict[str, Any] = {}
    dynamic_inputs: dict[str, Any] = {}
    for k, v in inputs.items():
        if _collect_noderefs(v):
            dynamic_inputs[k] = v
        else:
            static_inputs[k] = v

    ctx = current_context()
    definition = {
        "source": source,
        "fn": fn,
        "title": title,
        "description": description,
        "format": fmt,
        "static_inputs": static_inputs,
        "definition_hash": definition_hash_for_create_image(title, fmt, source),
    }
    return _register_nested_equation(
        ctx,
        "create_image",
        EquationType.CREATE_IMAGE,
        definition,
        {"inputs": dynamic_inputs} if dynamic_inputs else {},
        shape=Scalar(kind="media"),
    )


def create_layout(
    fn: Callable,
    *,
    inputs: Optional[dict[str, Any]] = None,
    title: str = "",
    description: str = "",
    width: int = 1200,
    height: Optional[int] = None,
) -> NodeRef:
    """Render an HTML/CSS layout and save it as a ``.stimmalayout`` library asset.

    Use this when the recipe's output is a designed composition — product
    cards, social posts, posters, briefs, annotated sheets — anything where
    typography and layout matter. The callable returns an HTML string; the
    evaluator stages referenced media, wraps the HTML into a self-contained
    bundle, and persists it as a MediaItem.

    ``fn`` takes the keys of ``inputs`` as parameters and returns a ``str``.
    Media-typed inputs (shape ``media`` or ``list[media]``) are pre-resolved
    to **local filename strings** — reference them from HTML as
    ``<img src="{key}.png">`` (or ``url({key}.png)`` in CSS). Other inputs
    pass through as resolved values.

    ``width`` and ``height`` define the canvas. ``height=None`` means
    content-measured — the layout renders tall enough to fit its content.
    """
    inputs = inputs or {}

    if not callable(fn):
        raise DSLMisuseError(
            f"create_layout(): fn must be a callable, got {type(fn).__name__}",
            suggestion=(
                "Pass a lambda or named function that takes the keys of "
                "inputs and returns an HTML string."
            ),
        )
    _validate_callable_closure(fn)
    _validate_callable_params(fn, inputs)
    source = _extract_canonical_source(fn)

    if not isinstance(title, str):
        raise DSLMisuseError(
            f"create_layout(): title must be a string, got {type(title).__name__}",
        )
    if not isinstance(description, str):
        raise DSLMisuseError(
            f"create_layout(): description must be a string, "
            f"got {type(description).__name__}",
        )
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        raise DSLMisuseError(
            f"create_layout(width={width!r}): width must be a positive int",
        )
    if height is not None and (
        not isinstance(height, int) or isinstance(height, bool) or height <= 0
    ):
        raise DSLMisuseError(
            f"create_layout(height={height!r}): height must be a positive int or None",
        )

    static_inputs: dict[str, Any] = {}
    dynamic_inputs: dict[str, Any] = {}
    for k, v in inputs.items():
        if _collect_noderefs(v):
            dynamic_inputs[k] = v
        else:
            static_inputs[k] = v

    ctx = current_context()
    definition = {
        "source": source,
        "fn": fn,
        "title": title,
        "description": description,
        "width": width,
        "height": height,
        "static_inputs": static_inputs,
        "definition_hash": definition_hash_for_create_layout(
            title, width, height, source,
        ),
    }
    return _register_nested_equation(
        ctx,
        "create_layout",
        EquationType.CREATE_LAYOUT,
        definition,
        {"inputs": dynamic_inputs} if dynamic_inputs else {},
        shape=Scalar(kind="media"),
    )


def rasterize_layout(
    layout: NodeRef,
    *,
    width: Optional[int] = None,
) -> NodeRef:
    """Rasterize a layout bundle into a PNG MediaItem.

    Use sparingly — layouts are usually the terminal output of a recipe. Reach
    for this only when a downstream tool needs pixels (e.g. feeding the
    rasterized layout into an image-to-image model).
    """
    if not isinstance(layout, NodeRef):
        raise DSLMisuseError(
            "rasterize_layout(): layout must be a NodeRef produced by create_layout()",
        )
    if width is not None and (
        not isinstance(width, int) or isinstance(width, bool) or width <= 0
    ):
        raise DSLMisuseError(
            f"rasterize_layout(width={width!r}): width must be a positive int or None",
        )

    ctx = current_context()
    definition = {
        "width": width,
        "definition_hash": definition_hash_for_rasterize_layout(width),
    }
    return _register_nested_equation(
        ctx,
        "rasterize_layout",
        EquationType.RASTERIZE_LAYOUT,
        definition,
        {"layout": layout},
        shape=Scalar(kind="media"),
    )


# ----- Web search / fetch primitives ----------------------------------------


_WEB_SEARCH_KINDS = ("text", "images")


def web_search(
    query: Any,
    *,
    kind: str = "text",
    n: int = 10,
) -> NodeRef:
    """Run a web search and return a list of structured result dicts.

    ``kind="images"`` items expose
    ``{title, image_url, source, width, height, media}``; ``media`` is a URL
    media descriptor that the UI can preview without adding anything to the
    asset library. When a URL media descriptor is selected by ``hitl.select``
    or otherwise used as the HITL result, the runtime promotes just that item
    to a library media id for downstream flow/lineage use. ``kind="text"``
    items expose ``{title, url, snippet}``. ``query`` is either a literal
    string or a single NodeRef (e.g. a recipe input or ``code()`` result).
    Use ``fetch_media(result["image_url"])`` only when you intentionally want
    to import every fetched result into the library.
    """
    if kind not in _WEB_SEARCH_KINDS:
        raise DSLMisuseError(
            f"web_search(kind={kind!r}): kind must be one of {list(_WEB_SEARCH_KINDS)}",
        )
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise DSLMisuseError(
            f"web_search(n={n!r}): n must be a positive integer",
        )

    query_template, query_dynamic = _template_of(query)
    if not query_template.strip() and not query_dynamic:
        raise DSLMisuseError(
            "web_search(): query must be a non-empty string or NodeRef",
            suggestion=(
                "Pass a literal query (web_search('miles davis')) or wire a "
                "recipe input/code() result through (web_search(input.query))."
            ),
        )

    dynamic: dict[str, Any] = {}
    if query_dynamic:
        dynamic["query"] = query_dynamic
    if isinstance(query, NodeRef):
        dynamic["query_value"] = query

    ctx = current_context()
    definition = {
        "query_template": query_template,
        "kind": kind,
        "n": n,
        "definition_hash": definition_hash_for_web_search(query_template, kind, n),
    }
    element_shape = web_search_result_shape(kind)
    return _register_nested_equation(
        ctx,
        "web_search",
        EquationType.WEB_SEARCH,
        definition,
        dynamic,
        collection=True,
        iteration_key_source=IterationKeySource(
            IterationKeySource.POSITIONAL, "web_result"
        ),
        shape=ListShape(element=element_shape),
    )


def fetch_media(url: Any, *, max_size_mb: int = 10) -> NodeRef:
    """Download ``url`` and save the bytes as a library media item.

    Sniffs content-type from bytes (HTTP ``Content-Type`` is unreliable),
    enforces ``max_size_mb`` cap, and tags the produced ``MediaItem`` with
    its ``source_url`` for lineage. Wrap in ``foreach`` for batch download.
    Raises a per-iteration error on 404 / oversize / non-image content;
    sibling iterations stay green.
    """
    if not isinstance(max_size_mb, int) or isinstance(max_size_mb, bool) or max_size_mb < 1:
        raise DSLMisuseError(
            f"fetch_media(max_size_mb={max_size_mb!r}): must be a positive integer",
        )

    if isinstance(url, NodeRef):
        shape = url.shape
        if shape is not None and not shape_matches_scalar_kind(shape, "str"):
            raise DSLMisuseError(
                f"fetch_media(url=...): url shape is {describe_shape(shape)}, "
                "expected str",
                suggestion=(
                    "url must resolve to a string. Pass a web_search() result "
                    "field via foreach (lambda r: fetch_media(r['image_url'])) "
                    "or build it with code(output_type='text')."
                ),
            )
        dynamic: dict[str, Any] = {"url": url}
    elif isinstance(url, str):
        if not url.strip():
            raise DSLMisuseError(
                "fetch_media(url=''): url must be a non-empty string",
            )
        dynamic = {"url": url}
    else:
        raise DSLMisuseError(
            f"fetch_media(): url must be a string or NodeRef[str]; got "
            f"{type(url).__name__}",
        )

    ctx = current_context()
    definition = {
        "max_size_mb": max_size_mb,
        "definition_hash": definition_hash_for_fetch_media(max_size_mb),
    }
    return _register_nested_equation(
        ctx,
        "fetch_media",
        EquationType.FETCH_MEDIA,
        definition,
        dynamic,
        shape=Scalar(kind="media"),
    )


# ----- HITL primitives ------------------------------------------------------


def _register_per_slot_approve(asset: NodeRef, *, instructions: str) -> NodeRef:
    """Internal: build a single-asset HITL approve equation for one slot.

    Used by ``foreach_expansion`` to auto-wrap each ``hitl.approve(N, ...)``
    slot's generator output in an approval gate. Not exposed on the DSL
    surface — the public ``hitl.approve`` is the multi-slot factory and
    must own the slot/regen contract; the per-slot terminal gate is an
    implementation detail of expansion.
    """
    ctx = current_context()
    definition = {
        "hitl_type": "approve",
        "instructions": instructions,
    }
    return _register_nested_equation(
        ctx,
        "hitl.approve",
        EquationType.HITL,
        definition,
        {"asset": asset},
        shape=asset.shape if asset.shape is not None else UNKNOWN,
    )


class _Hitl:
    @staticmethod
    def select(candidates: NodeRef, *, instructions: str, count: int = 1) -> NodeRef:
        ctx = current_context()
        if not isinstance(candidates, NodeRef):
            raise DSLMisuseError(
                "hitl.select(): candidates must be a NodeRef that resolves to a list",
                suggestion=(
                    "If you have a structured LLM result, extract the list first "
                    "with code(): code(\"data['items']\", inputs={\"data\": node})."
                ),
            )
        if not candidates.collection:
            raise DSLMisuseError(
                "hitl.select(): candidates node is not a collection",
                suggestion=(
                    "hitl.select expects a list node. foreach(...) produces "
                    "list nodes. If you have a structured LLM response (a "
                    "dict), extract the list field with code()."
                ),
            )
        definition = {
            "hitl_type": "select",
            "instructions": instructions,
            "count": count,
        }
        ik_source = (
            IterationKeySource(IterationKeySource.POSITIONAL, "hitl_select")
            if count > 1
            else None
        )
        # Element shape is whatever the candidates list holds.
        element_shape: Shape = UNKNOWN
        cand_shape = candidates.shape
        if isinstance(cand_shape, ListShape):
            element_shape = cand_shape.element
        output_shape: Shape = (
            ListShape(element=element_shape) if count > 1 else element_shape
        )
        return _register_nested_equation(
            ctx,
            "hitl.select",
            EquationType.HITL,
            definition,
            {"candidates": candidates},
            collection=count > 1,
            iteration_key_source=ik_source,
            shape=output_shape,
        )

    @staticmethod
    def approve_one(
        generate: Callable[..., NodeRef],
        *,
        instructions: str,
        **extra_kwargs: Any,
    ) -> NodeRef:
        """Generate one candidate and gate it with user approval.

        This is the scalar form of ``hitl.approve`` without the unused slot
        index. Extra kwargs are explicit dependencies forwarded to
        ``generate(**kwargs)``.
        """
        if not callable(generate):
            raise DSLMisuseError(
                "hitl.approve_one(generate=...): must be a callable",
                suggestion=(
                    "Pass a function or lambda that builds one candidate: "
                    "hitl.approve_one(lambda prompt: tool(...), "
                    "prompt=headshot_prompt, instructions='...')."
                ),
            )
        _validate_forwarded_callback_kwargs(
            "hitl.approve_one", generate, extra_kwargs,
        )

        def generate_one(_slot_index: int, **kwargs: Any) -> NodeRef:
            return generate(**kwargs)

        generate_one.__name__ = getattr(generate, "__name__", "generate_one")
        return _Hitl.approve(
            1,
            generate_one,
            instructions=instructions,
            **extra_kwargs,
        )

    @staticmethod
    def approve_each(
        items: Any,
        generate: Callable[..., NodeRef],
        *,
        instructions: str,
        **extra_kwargs: Any,
    ) -> NodeRef:
        """Approve one regenerable candidate per item.

        ``generate(item, **kwargs)`` runs inside the per-item approval gate, so
        replacing one item re-runs only that item's candidate generator.
        """
        if not callable(generate):
            raise DSLMisuseError(
                "hitl.approve_each(generate=...): must be a callable",
                suggestion=(
                    "Pass a function or lambda that builds one candidate per "
                    "item: hitl.approve_each(items, lambda item: tool(...), "
                    "instructions='...')."
                ),
            )
        _validate_item_callback_kwargs("hitl.approve_each", generate, extra_kwargs)

        def approve_item(item: Any, **kwargs: Any) -> NodeRef:
            return _Hitl.approve(
                1,
                lambda _slot_index: generate(item, **kwargs),
                instructions=instructions,
            )

        approve_item.__name__ = getattr(generate, "__name__", "approve_item")
        return foreach(items, approve_item, **extra_kwargs)

    @staticmethod
    def approve(
        count: int,
        generate: Callable[[int], NodeRef],
        *,
        instructions: str,
        **extra_kwargs: Any,
    ) -> NodeRef:
        """Generate ``count`` candidates, each gated by user approval.

        Each slot calls ``generate(slot_index, **extra_kwargs)`` to produce a
        candidate; the user is then prompted to approve or reject. Reject
        re-runs that slot's generator (and only that slot) — the lambda body
        defines the regen scope. Extra kwargs are forwarded like foreach kwargs:
        use them for locked context/dependencies that should not be regenerated
        on reject.

        Returns a scalar NodeRef when ``count == 1`` and ``list[T]`` when
        ``count > 1``, where T is the element shape produced by
        ``generate``.

        Examples
        --------
        Single approve — re-runs the tool on reject, persona stays fixed::

            approved_headshot = hitl.approve(
                1,
                lambda _: tool("flux", prompt=headshot_prompt),
                instructions="Approve if face is right. Reject to redraw.",
            )

        N approves — each slot re-runs only its own generator::

            approved_refs = hitl.approve(
                4,
                lambda i, seed: tool("flux", prompt=ref_prompts[i], seed=seed),
                seed=seed,
                instructions="Approve all 4 references. Reject to regen.",
            )
        """
        ctx = current_context()
        frame = ctx.current_frame

        if not isinstance(count, int) or isinstance(count, bool):
            raise DSLMisuseError(
                f"hitl.approve(count=...): must be an int literal, got {type(count).__name__}",
                suggestion="Pass a positive int. Dynamic counts aren't supported in v1 — use foreach for that.",
            )
        if count < 1:
            raise DSLMisuseError(
                f"hitl.approve(count=...): must be >= 1, got {count}",
            )
        if not callable(generate):
            raise DSLMisuseError(
                "hitl.approve(generate=...): must be a callable",
                suggestion=(
                    "Pass a function or lambda that builds one candidate per slot: "
                    "hitl.approve(N, lambda i, ctx: tool(...), ctx=context, "
                    "instructions='...')."
                ),
            )
        if not isinstance(instructions, str) or not instructions.strip():
            raise DSLMisuseError(
                "hitl.approve(instructions=...): must be a non-empty string",
                suggestion=(
                    "instructions is shown to the user above the slot grid — "
                    "describe what 'approve' / 'reject' means in this context."
                ),
            )

        fn_name = getattr(generate, "__name__", "generate")
        if fn_name == "<lambda>":
            fn_name = "lambda"
        try:
            validate_function_name(fn_name)
        except Exception as exc:
            raise DSLMisuseError(
                f"hitl.approve(): generator has an invalid name {fn_name!r}: {exc}",
                suggestion=(
                    "Define generators as module-level functions with valid "
                    "Python identifiers — the function name becomes part of "
                    "the equation key."
                ),
            )
        _validate_deferred_callback_params("hitl.approve", generate, extra_kwargs)

        # Dry-run the generator to (a) infer element shape and (b) reject
        # passthrough returns. The lambda body is the regen scope on
        # reject — closing over an existing NodeRef and returning it bare
        # leaves the slot with nothing of its own to regenerate.
        element_shape: Shape = _validate_approve_generator(generate, extra_kwargs)

        pos = frame.next_positional("hitl.approve")
        wrapper_key = make_nested_dsl_key(frame.parent_key, "hitl.approve", pos)

        # Back the wrapper with a literal list of slot indices so the engine's
        # uniform deferred-expansion path can drive it. The literal list is
        # the input dependency; the wrapper depends on it (and on the
        # per-slot children, after expansion).
        literal_ref = _register_literal_collection(ctx, list(range(count)))

        deps = [literal_ref.equation_key]
        for ref in _collect_noderefs(list(extra_kwargs.values())):
            if ref.equation_key not in deps:
                deps.append(ref.equation_key)

        wrapper = Equation(
            key=wrapper_key,
            equation_type=EquationType.CONTROL,
            definition={
                "control_kind": "approve",
                "count": count,
                "instructions": instructions,
                "callback_name": fn_name,
                "callback_fingerprint": _callback_fingerprint(generate),
                "extra_kwargs": extra_kwargs,
            },
            dependencies=deps,
            phase_path=list(frame.phase_stack),
        )
        ctx.graph.add_equation(wrapper)
        frame.registered_equations.append((tuple(frame.phase_stack), wrapper_key))
        ctx.graph.register_deferred(
            DeferredExpansion(
                kind="approve",
                owner_key=wrapper_key,
                parent_key=wrapper_key,
                input_equation_key=literal_ref.equation_key,
                callback=generate,
                extra_kwargs=dict(extra_kwargs),
                positional_index=pos,
                function_name=fn_name,
                iteration_key_source=literal_ref.iteration_key_source,
            )
        )

        if count == 1:
            # Scalar return — engine unwraps the 1-element list at result-
            # collection time. iteration_key_source stays None: nothing
            # downstream iterates a scalar.
            return NodeRef(
                equation_key=wrapper_key,
                collection=False,
                shape=element_shape,
            )

        ik_source = literal_ref.iteration_key_source
        known_keys = (
            list(literal_ref.known_iteration_keys)
            if literal_ref.known_iteration_keys
            else None
        )
        return NodeRef(
            equation_key=wrapper_key,
            collection=True,
            iteration_key_source=IterationKeySource(
                IterationKeySource.INHERITED,
                ik_source.element_kind if ik_source else "",
            ),
            known_iteration_keys=known_keys,
            shape=ListShape(element=element_shape),
        )

hitl = _Hitl()


# ----- data-flow routing ----------------------------------------------------


def _routing_code(
    routing_kind: str,
    fn_or_source: Callable | str,
    *,
    inputs: dict[str, Any],
    output_type: str,
    description: str,
) -> NodeRef:
    ref = code(
        fn_or_source,
        inputs=inputs,
        output_type=output_type,
        description=description,
    )
    current_context().graph.get(ref.equation_key).definition["routing_kind"] = routing_kind
    return ref


def switch(
    value: Any,
    cases: dict[Any, Any],
    *,
    default: Any = None,
    output_type: str = "json",
    description: Optional[str] = None,
) -> NodeRef:
    """Select a resolved value from static cases without changing graph shape.

    ``switch`` is for choosing prompts, model names, parameters, or other
    values. It is not a graph-shaping conditional: all NodeRef values passed
    in ``cases``/``default`` are normal upstream dependencies.
    """
    if not isinstance(cases, dict) or not cases:
        raise DSLMisuseError(
            "switch(): cases must be a non-empty dict",
            suggestion=(
                "Pass a mapping from resolved labels to values, e.g. "
                "switch(genre, {'jazz': jazz_prompt}, default=neutral_prompt)."
            ),
        )

    def _switch_value(value, cases, default):
        return cases.get(value, default)

    return _routing_code(
        "switch",
        _switch_value,
        inputs={"value": value, "cases": cases, "default": default},
        output_type=output_type,
        description=description or "select value",
    )


def when(
    condition: Any,
    value: Any,
    *,
    otherwise: Any = None,
    output_type: str = "json",
    description: Optional[str] = None,
) -> NodeRef:
    """Return ``value`` when ``condition`` is truthy, otherwise ``otherwise``.

    This is a value gate. If ``value`` is produced by an expensive upstream
    node, that upstream node still exists and can still run. Use ``filter()``
    before ``foreach()`` when you need to avoid per-item work.
    """

    def _when_value(condition, value, otherwise):
        return value if bool(condition) else otherwise

    return _routing_code(
        "when",
        _when_value,
        inputs={"condition": condition, "value": value, "otherwise": otherwise},
        output_type=output_type,
        description=description or "gate value",
    )


def gate(
    condition: Any,
    value: Any,
    *,
    otherwise: Any = None,
    output_type: str = "json",
    description: Optional[str] = None,
) -> NodeRef:
    """Alias for ``when``; reads better for approval/filtering recipes."""

    def _gate_value(condition, value, otherwise):
        return value if bool(condition) else otherwise

    return _routing_code(
        "gate",
        _gate_value,
        inputs={"condition": condition, "value": value, "otherwise": otherwise},
        output_type=output_type,
        description=description or "gate value",
    )


def _validate_one_arg_callable(name: str, fn: Callable[..., Any]) -> None:
    if not callable(fn):
        raise DSLMisuseError(f"{name}(): predicate/classifier must be callable")
    _validate_callable_closure(fn)
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return
    positional = [
        p for p in sig.parameters.values()
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    has_varargs = any(
        p.kind == inspect.Parameter.VAR_POSITIONAL
        for p in sig.parameters.values()
    )
    required_kw_only = [
        p.name for p in sig.parameters.values()
        if p.kind == inspect.Parameter.KEYWORD_ONLY
        and p.default is inspect.Parameter.empty
    ]
    if required_kw_only or (not has_varargs and len(positional) != 1):
        raise DSLMisuseError(
            f"{name}(): callable must accept exactly one item argument",
            suggestion="Use lambda item: ... or a def predicate(item): ... helper.",
        )


def filter_items(
    items: Any,
    predicate: Callable[[Any], bool],
    *,
    output_type: str = "list[json]",
    description: Optional[str] = None,
) -> NodeRef:
    """Keep items whose resolved value satisfies ``predicate``.

    This is the branchless routing primitive to put before ``foreach``.
    Empty outputs are valid and simply produce zero downstream iterations.
    """
    _validate_one_arg_callable("filter", predicate)

    def _filter_items(items):
        return [item for item in items if predicate(item)]

    return _routing_code(
        "filter",
        _filter_items,
        inputs={"items": items},
        output_type=output_type,
        description=description or "filter items",
    )


def filter(  # noqa: A001 - intentionally part of the recipe DSL surface
    items: Any,
    predicate: Callable[[Any], bool],
    *,
    output_type: str = "list[json]",
    description: Optional[str] = None,
) -> NodeRef:
    return filter_items(
        items,
        predicate,
        output_type=output_type,
        description=description,
    )


def partition(
    items: Any,
    classifier: Callable[[Any], Any],
    *,
    labels: list[Any],
    default_label: Optional[Any] = None,
    description: Optional[str] = None,
) -> NodeRef:
    """Group items into labeled lists using a resolved-value classifier.

    Returns a ``json`` dict shaped like ``{label: [items...]}``. Extract a
    specific lane with ``code(lambda p: p['jazz'], inputs={'p': lanes},
    output_type='list[json]')`` before feeding it to ``foreach``.
    """
    _validate_one_arg_callable("partition", classifier)
    if not isinstance(labels, list) or not labels:
        raise DSLMisuseError("partition(): labels must be a non-empty list")

    def _partition_items(items):
        out = {label: [] for label in labels}
        if default_label is not None and default_label not in out:
            out[default_label] = []
        for item in items:
            label = classifier(item)
            if label not in out:
                if default_label is None:
                    continue
                label = default_label
            out[label].append(item)
        return out

    return _routing_code(
        "partition",
        _partition_items,
        inputs={"items": items},
        output_type="json",
        description=description or "partition items",
    )


def take(
    items: Any,
    n: Any,
    *,
    output_type: str = "list[json]",
    description: Optional[str] = None,
) -> NodeRef:
    """Return the first ``n`` items from a resolved collection."""

    def _take_items(items, n):
        return list(items)[: int(n)]

    return _routing_code(
        "take",
        _take_items,
        inputs={"items": items, "n": n},
        output_type=output_type,
        description=description or "take first items",
    )


# ----- foreach / zip_nodes --------------------------------------------------


def foreach(items: Any, callback: Callable[..., Any], **extra_kwargs) -> NodeRef:
    """Registers a foreach wrapper equation.

    The ``callback`` is captured for deferred expansion at evaluation time.
    Iteration keys are derived by the runtime from the source (§6) —
    the DSL does not accept ``key=`` or ``label=``.
    """
    # A literal ``range`` is materialized into a list so the runtime sees a
    # concrete positional collection. Use ``foreach_range`` when ``n`` itself
    # is a node (resolved at eval time).
    if isinstance(items, range):
        items = list(items)

    ctx = current_context()
    frame = ctx.current_frame
    pos = frame.next_positional("foreach")
    wrapper_key = make_nested_dsl_key(frame.parent_key, "foreach", pos)

    fn_name = getattr(callback, "__name__", "callback")
    # Python lambdas are ``<lambda>`` which isn't a legal equation-key
    # segment; normalize to ``lambda``. Two sibling lambdas live under
    # different parent ``foreach$N`` keys, so they don't collide.
    if fn_name == "<lambda>":
        fn_name = "lambda"
    try:
        validate_function_name(fn_name)
    except Exception as exc:
        raise DSLMisuseError(
            f"foreach(): callback has an invalid name {fn_name!r}: {exc}",
            suggestion=(
                "Define callbacks as module-level functions with valid Python "
                "identifiers — the function name becomes part of the equation key."
            ),
        )
    _validate_deferred_callback_params("foreach", callback, extra_kwargs)

    if isinstance(items, NodeRef):
        if not items.collection:
            raise DSLMisuseError(
                f"foreach(): items node {items.equation_key!r} is not a collection",
                suggestion=(
                    "foreach needs a node that resolves to a list. Another "
                    "foreach, llm(..., n=N), or a code() with list[...] "
                    "output produces one; an llm() result with "
                    "response_format is a dict, not a list — extract the "
                    "list first with code()."
                ),
            )
        ik_source = items.iteration_key_source or IterationKeySource(
            IterationKeySource.POSITIONAL
        )
        input_equation_key = items.equation_key
        deps = [items.equation_key]
        known_keys = (
            list(items.known_iteration_keys) if items.known_iteration_keys else None
        )
        literal_values: Optional[list[Any]] = None
    elif isinstance(items, (list, tuple)):
        literal_ref = _register_literal_collection(ctx, items)
        ik_source = literal_ref.iteration_key_source
        input_equation_key = literal_ref.equation_key
        deps = [literal_ref.equation_key]
        known_keys = (
            list(literal_ref.known_iteration_keys)
            if literal_ref.known_iteration_keys
            else None
        )
        literal_values = list(items)
    else:
        raise DSLMisuseError(
            f"foreach(): items must be a NodeRef or list, got {type(items).__name__}",
            suggestion=(
                "Pass a recipe input list, a node returned by foreach or "
                "llm(n=N), or a Python list (range works too)."
            ),
        )

    for ref in _collect_noderefs(list(extra_kwargs.values())):
        if ref.equation_key not in deps:
            deps.append(ref.equation_key)

    wrapper = Equation(
        key=wrapper_key,
        equation_type=EquationType.CONTROL,
        definition={
            "control_kind": "foreach",
            "callback_name": fn_name,
            "callback_fingerprint": _callback_fingerprint(callback),
            "literal_values": literal_values,
            "extra_kwargs": extra_kwargs,
        },
        dependencies=deps,
        phase_path=list(frame.phase_stack),
    )
    ctx.graph.add_equation(wrapper)
    # Track the wrapper as a phase equation so a later info() in the same
    # phase picks it up as an implicit dependency. Without this, info() fires
    # as soon as the cheaper siblings (code/llm) complete, even though the
    # foreach hasn't finished.
    frame.registered_equations.append((tuple(frame.phase_stack), wrapper_key))
    ctx.graph.register_deferred(
        DeferredExpansion(
            kind="foreach",
            owner_key=wrapper_key,
            parent_key=wrapper_key,
            input_equation_key=input_equation_key,
            callback=callback,
            extra_kwargs=dict(extra_kwargs),
            positional_index=pos,
            function_name=fn_name,
            iteration_key_source=ik_source,
        )
    )

    # Best-effort element-shape inference: dry-run the callback in a scratch
    # context using the first literal value. This makes shape info survive
    # downstream primitives (notably ``hitl.select(count=1)``, whose output
    # shape is whatever the list's element shape is — without this we return
    # Unknown and media inputs silently arrive as raw ints in create_image /
    # code callables). Skip the dry-run when items is a NodeRef (we don't
    # have a representative element value) or when the callback raises —
    # falling back to Unknown keeps legacy behaviour instead of failing the
    # build.
    element_shape: Shape = UNKNOWN
    if literal_values:
        sample = literal_values[0]
        try:
            element_shape = _infer_foreach_element_shape(
                callback, sample, extra_kwargs,
            )
        except Exception:  # noqa: BLE001 — best-effort, never fail the build
            element_shape = UNKNOWN

    return NodeRef(
        equation_key=wrapper_key,
        collection=True,
        iteration_key_source=IterationKeySource(
            IterationKeySource.INHERITED,
            ik_source.element_kind if ik_source else "",
        ),
        known_iteration_keys=known_keys,
        shape=ListShape(element=element_shape),
    )


def _infer_foreach_element_shape(
    callback: Callable[..., Any],
    sample_item: Any,
    extra_kwargs: dict[str, Any],
) -> Shape:
    """Dry-run ``callback(sample_item, **extra_kwargs)`` in a scratch graph.

    Returns the shape of the NodeRef the callback produces, or ``UNKNOWN``
    if the callback returns a non-NodeRef value. The callback's DSL calls
    register equations in a throwaway ``EquationGraph`` which is discarded
    on return — the real deferred expansion still happens later in the
    live graph, unchanged.

    Any exception from the dry-run (closure over a NodeRef the scratch
    frame doesn't know about, tool-id validation, etc.) is the caller's
    problem to catch — this function does not silence errors.
    """
    from recipe_runtime.graph import EquationGraph as _Graph

    scratch_graph = _Graph()
    scratch_ctx = BuildContext(graph=scratch_graph)
    with activate_context(scratch_ctx):
        with push_frame(scratch_ctx, parent_key="_scratch", function_name="_scratch"):
            result = callback(sample_item, **extra_kwargs)
    if isinstance(result, NodeRef):
        return result.shape if result.shape is not None else UNKNOWN
    return UNKNOWN


def _validate_approve_generator(
    callback: Callable[[int], Any],
    extra_kwargs: Optional[dict[str, Any]] = None,
) -> Shape:
    """Dry-run an approve generator and reject passthrough returns.

    The generator must register at least one new equation and return that
    equation's NodeRef. Returning a NodeRef the callback closed over from
    outside means the slot has no body of its own to regenerate on
    reject — the lambda body IS the regen scope. We surface that as a
    build-time error so the recipe can't silently behave as a no-op
    reject.

    Returns the element shape of the candidate (UNKNOWN if shape inference
    fails for an unrelated reason).
    """
    from recipe_runtime.graph import EquationGraph as _Graph

    extra_kwargs = dict(extra_kwargs or {})
    scratch_graph = _Graph()
    scratch_ctx = BuildContext(graph=scratch_graph)
    try:
        with activate_context(scratch_ctx):
            with push_frame(scratch_ctx, parent_key="_scratch", function_name="_scratch"):
                result = callback(0, **extra_kwargs)
    except DSLMisuseError:
        raise
    except Exception:  # noqa: BLE001 — non-DSL errors don't fail the build
        return UNKNOWN

    if not isinstance(result, NodeRef):
        raise DSLMisuseError(
            "hitl.approve(generate=...): generator must return a NodeRef "
            f"(got {type(result).__name__})",
            suggestion=(
                "Build the candidate with tool(), llm(), or code() inside the "
                "lambda and return that node. Returning a literal value or "
                "None is not supported."
            ),
        )
    if result.equation_key not in scratch_graph:
        raise DSLMisuseError(
            "hitl.approve(generate=...): generator returned a pre-existing "
            "node — the lambda must build its own candidate",
            suggestion=(
                "The lambda body is the regen scope on reject. Move the "
                "generative call inside the lambda; close over upstream "
                "nodes as inputs. Example: "
                "hitl.approve(1, lambda _: tool('flux', input=upstream), "
                "instructions='...')."
            ),
        )
    result_eq = scratch_graph.get(result.equation_key)
    if _is_media_selector_code_for_approve(result_eq):
        raise DSLMisuseError(
            "hitl.approve(generate=...): generator returned a media selector, "
            "not a regenerable candidate",
            suggestion=(
                "The approve lambda defines what Replace regenerates. Put the "
                "media-producing tool()/create_image() call inside the lambda. "
                "For fixed slots, branch on the slot index and build that "
                "slot's prompt and tool call inside generate(i), instead of "
                "generating a list first and selecting photos[i] with code()."
            ),
        )
    return result.shape if result.shape is not None else UNKNOWN


def _is_media_selector_code_for_approve(eq: Equation) -> bool:
    """True when an approve generator returns code() that selects existing media.

    A code(output_type="media") node is technically fresh, but if it depends on
    an existing collection node it behaves as a selector over already-produced
    assets. Rejecting that approve slot would only re-run the selector and hand
    the user the same image again. The regenerable unit must be a media producer
    inside the approve lambda.
    """
    if eq.equation_type != EquationType.CODE:
        return False
    if eq.definition.get("output_type") not in ("media", "list[media]"):
        return False
    dynamic = eq.definition.get("_dynamic") or {}
    inputs = dynamic.get("inputs") if isinstance(dynamic, dict) else None
    if not isinstance(inputs, dict):
        return False
    return any(
        ref.collection
        for ref in _collect_noderefs(list(inputs.values()))
    )


def foreach_range(
    n: Any,
    callback: Callable[..., Any],
    **extra_kwargs: Any,
) -> NodeRef:
    """Iterate ``callback`` ``n`` times, passing the resolved 0..n-1 index.

    Use when the iteration count is itself a value (a recipe int input, a
    count computed by code(), etc.) and you just need N invocations. The
    callback's first parameter receives the index as a resolved int;
    ``extra_kwargs`` are forwarded unchanged to every invocation, the same
    way ``foreach``'s extras work.

        foreach_range(
            num_poses, make_pose, subject=subject_node, product=product_node,
        )

    If you already have the collection you want to iterate, call
    ``foreach(items, callback)`` directly — don't route through this.
    """
    if isinstance(n, bool) or not isinstance(n, (int, NodeRef)):
        raise DSLMisuseError(
            f"foreach_range(): n must be an int NodeRef or int literal, got "
            f"{type(n).__name__}",
            suggestion=(
                "Pass a recipe input of type='int', a code() node with "
                "output_type='int'/'json', or an int literal. To iterate an "
                "existing collection instead, use foreach(items, callback)."
            ),
        )
    if isinstance(n, int):
        if n < 0:
            raise DSLMisuseError(
                f"foreach_range(): n must be non-negative, got {n}",
                suggestion="Pass 0 to skip iteration, or a positive int.",
            )
        indices_node: Any = list(range(n))
    else:
        indices_node = code(
            lambda n: list(range(n)),
            inputs={"n": n},
            output_type="list[int]",
            description="iteration indices",
        )
    return foreach(indices_node, callback, **extra_kwargs)


def zip_nodes(*collections: NodeRef) -> NodeRef:
    """Aligns keyed collections by iteration key (inner join) at eval time."""
    ctx = current_context()
    if not collections:
        raise DSLMisuseError("zip_nodes(): at least one collection is required")
    for c in collections:
        if not isinstance(c, NodeRef):
            raise DSLMisuseError(
                "zip_nodes(): all arguments must be NodeRefs",
                suggestion=(
                    "zip_nodes joins collection nodes — pass nodes returned "
                    "by foreach or llm(n=N), not literal lists."
                ),
            )
        if not c.collection:
            raise DSLMisuseError(
                f"zip_nodes(): {c.equation_key!r} is not a collection node",
            )

    known_sets: list[list[str]] = []
    for c in collections:
        if c.known_iteration_keys is None:
            known_sets = []
            break
        known_sets.append(list(c.known_iteration_keys))
    if known_sets:
        base = set(known_sets[0])
        for ks in known_sets[1:]:
            if set(ks) != base:
                raise DSLMisuseError(
                    "zip_nodes(): input collections have mismatched iteration keys",
                    suggestion=(
                        "zip_nodes aligns by key, not position. Both collections "
                        "must come from the same upstream foreach (so they share "
                        "iteration keys)."
                    ),
                )

    frame = ctx.current_frame
    pos = frame.next_positional("zip_nodes")
    wrapper_key = make_nested_dsl_key(frame.parent_key, "zip_nodes", pos)

    # ``sources`` MUST preserve the user's positional order — pair[i] reads
    # the i-th input collection. ``dependencies`` is a set used by the
    # scheduler and may be sorted/deduped for stability, but the per-tuple
    # construction in _collect_zip_result iterates ``sources`` directly, so
    # any reordering here silently swaps element positions in the output.
    sources = [c.equation_key for c in collections]
    deps = sorted(set(sources))
    definition = {
        "control_kind": "zip_nodes",
        "sources": sources,
    }
    eq = Equation(
        key=wrapper_key,
        equation_type=EquationType.CONTROL,
        definition=definition,
        dependencies=deps,
        phase_path=list(frame.phase_stack),
    )
    ctx.graph.add_equation(eq)
    frame.registered_equations.append((tuple(frame.phase_stack), wrapper_key))

    keyed_source = next(
        (c.iteration_key_source for c in collections if c.iteration_key_source is not None),
        None,
    )

    # Each per-iteration item is a tuple aligning the input collections by
    # position. Carry that through as a TupleShape so downstream consumers
    # (foreach element-shape inference, future dry-run validators) can read
    # the per-position element shape instead of getting an opaque Unknown.
    element_shapes: list[Shape] = []
    for c in collections:
        c_shape = getattr(c, "shape", None)
        if isinstance(c_shape, ListShape):
            element_shapes.append(c_shape.element)
        else:
            element_shapes.append(UNKNOWN)
    tuple_shape: Shape = TupleShape(elements=tuple(element_shapes))

    return NodeRef(
        equation_key=wrapper_key,
        collection=True,
        iteration_key_source=IterationKeySource(IterationKeySource.INHERITED)
        if keyed_source is not None
        else IterationKeySource(IterationKeySource.POSITIONAL),
        known_iteration_keys=known_sets[0] if known_sets else None,
        shape=ListShape(element=tuple_shape),
    )


def _register_literal_collection(ctx: BuildContext, values: Iterable[Any]) -> NodeRef:
    """Create a synthetic 'literal_list' equation for a build-time list."""
    values = list(values)
    digest = hashlib.sha256(str(values).encode("utf-8")).hexdigest()[:12]
    frame = ctx.current_frame
    pos = frame.next_positional("literal_list")
    key = make_nested_dsl_key(frame.parent_key, "literal_list", pos)
    if all(isinstance(v, (str, int, float, bool)) for v in values):
        element_kind = "scalar"
        ik_source = IterationKeySource(IterationKeySource.KEYED, element_kind)
        known = [encode_iteration_key(v) for v in values]
    elif all(isinstance(v, dict) for v in values):
        element_kind = "json"
        ik_source = IterationKeySource(IterationKeySource.KEYED, element_kind)
        known = [encode_iteration_key(canonical_json_hash(v)) for v in values]
    else:
        element_kind = ""
        ik_source = IterationKeySource(IterationKeySource.POSITIONAL, element_kind)
        known = [str(i) for i in range(len(values))]

    eq = Equation(
        key=key,
        equation_type=EquationType.RECIPE_INPUT,
        definition={
            "control_kind": "literal_list",
            "values": values,
            "digest": digest,
            "element_kind": element_kind,
        },
        dependencies=[],
        phase_path=list(frame.phase_stack),
    )
    ctx.graph.add_equation(eq)
    element_shape: Shape = UNKNOWN
    if values:
        first = values[0]
        element_shape = shape_from_literal(first)
    return NodeRef(
        equation_key=key,
        collection=True,
        iteration_key_source=ik_source,
        known_iteration_keys=known,
        shape=ListShape(element=element_shape),
    )


# ----- Recipe-input lift ----------------------------------------------------


def lift_recipe_input(
    ctx: BuildContext,
    name: str,
    value: Any,
    *,
    type_str: Optional[str] = None,
    optional: bool = False,
    display_name: str = "",
) -> NodeRef:
    """Materialize a recipe input as a RECIPE_INPUT equation node.

    Every input — scalar, list, media, None — becomes an equation in the
    graph so the graph structure is preserved even when the caller hasn't
    provided all input values yet (authoring-time introspection). Scalar
    inputs no longer "pass through" as raw Python values; the recipe
    function receives NodeRefs for every input. Using an input as a raw
    scalar (``if x == "foo"``, ``f"{x}"``, ``range(x)``) raises
    ``NodeUsageError`` at graph-build time, which is the correct signal —
    scalar-dependent value selection must go through ``switch()``/``when()``
    or ``code()``.

    Design note: ``value`` can be ``None`` when an input hasn't been set
    yet. The equation is built regardless; it just can't complete at run
    time without a real value. Build-time introspection only needs the
    structure.
    """
    pos = ctx.current_frame.next_positional("recipe_input")
    key = make_nested_dsl_key(ctx.current_frame.parent_key, "recipe_input", pos)

    declared_shape: Shape = (
        shape_from_type_string(type_str) if type_str else UNKNOWN
    )

    if isinstance(value, list) or (
        value is None and isinstance(declared_shape, ListShape)
    ):
        values = list(value) if isinstance(value, list) else None
        if values is None:
            element_kind = ""
            ik_source = IterationKeySource(IterationKeySource.POSITIONAL, element_kind)
            known = None
        elif all(isinstance(v, (str, int, float, bool)) for v in values):
            element_kind = "scalar"
            ik_source = IterationKeySource(IterationKeySource.KEYED, element_kind)
            known = [encode_iteration_key(v) for v in values]
        elif all(isinstance(v, dict) for v in values):
            element_kind = "json"
            ik_source = IterationKeySource(IterationKeySource.KEYED, element_kind)
            known = [encode_iteration_key(canonical_json_hash(v)) for v in values]
        else:
            element_kind = ""
            ik_source = IterationKeySource(IterationKeySource.POSITIONAL, element_kind)
            known = [str(i) for i in range(len(values))]

        eq = Equation(
            key=key,
            equation_type=EquationType.RECIPE_INPUT,
            definition={
                "control_kind": "recipe_input",
                "input_name": name,
                "input_display_name": display_name or "",
                "is_collection": True,
                "values": values,
                "element_kind": element_kind,
                "optional": bool(optional),
            },
            dependencies=[],
            phase_path=list(ctx.current_frame.phase_stack),
        )
        ctx.graph.add_equation(eq)
        # Prefer declared shape; if none, infer element shape from the
        # literal values (which matches what _register_literal_collection
        # does).
        list_shape: Shape
        if isinstance(declared_shape, ListShape):
            list_shape = declared_shape
        elif values:
            list_shape = ListShape(element=shape_from_literal(values[0]))
        else:
            list_shape = ListShape(element=UNKNOWN)
        return NodeRef(
            equation_key=key,
            collection=True,
            iteration_key_source=ik_source,
            known_iteration_keys=known,
            shape=list_shape,
        )

    # Scalar / media / None — opaque node. Downstream DSL calls consume it
    # via dynamic bindings; trying to use it as a raw scalar at build time
    # raises NodeUsageError with a teaching hint (see NodeRef guards).
    eq = Equation(
        key=key,
        equation_type=EquationType.RECIPE_INPUT,
        definition={
            "control_kind": "recipe_input",
            "input_name": name,
            "input_display_name": display_name or "",
            "is_collection": False,
            "value": value,
            "optional": bool(optional),
        },
        dependencies=[],
        phase_path=list(ctx.current_frame.phase_stack),
    )
    ctx.graph.add_equation(eq)
    # Declared shape wins when given. Otherwise infer from the value itself
    # (so scalar inputs with concrete test values get meaningful shapes).
    scalar_shape: Shape
    if isinstance(declared_shape, (Scalar, ListShape, DictShape)):
        scalar_shape = declared_shape
    elif value is not None:
        scalar_shape = shape_from_literal(value)
    else:
        scalar_shape = UNKNOWN
    return NodeRef(equation_key=key, collection=False, shape=scalar_shape)


# ----- f-string template extraction -----------------------------------------


def _template_of(value: Any) -> tuple[str, dict[str, NodeRef]]:
    """Extract a template string + dynamic bindings from a prompt value.

    Accepts a plain string (no dynamic bindings) or a single NodeRef
    (template ``"{0}"``). f-strings that mix literal text with nodes are
    rejected by ``NodeRef.__format__`` before control reaches here, with a
    helpful error pointing at code() / foreach-callback alternatives.

    A plain string is forwarded to the LLM verbatim at evaluation time, so
    any ``{name}`` or ``{0}`` left in it reaches the model literally. That's
    almost never what the agent intended — it's a sign they wanted to inject
    a resolved value and reached for Python's f-string syntax by habit. We
    detect that here and point at ``code()`` as the correct path.
    """
    if value is None:
        return "", {}
    if isinstance(value, str):
        try:
            value.format()
        except (IndexError, KeyError) as exc:
            placeholder = exc.args[0] if exc.args else "?"
            raise DSLMisuseError(
                f"prompt contains unbound placeholder {{{placeholder}}} — "
                f"llm() prompts are plain strings or a single NodeRef; there is "
                f"no multi-variable template form.",
                suggestion=(
                    "Build the prompt with code() first, then pass the result to "
                    "llm():\n"
                    "  prompt = code(\"f'Describe {x} using {y}'\", "
                    "inputs={'x': node_x, 'y': node_y}, output_type='text')\n"
                    "  result = llm(prompt)\n"
                    "If you meant literal braces, escape them: {{text}}."
                ),
            ) from None
        return value, {}
    if isinstance(value, NodeRef):
        return "{0}", {"0": value}
    raise DSLMisuseError(
        f"llm/hitl prompt must be str or NodeRef at build time; got {type(value).__name__}",
    )

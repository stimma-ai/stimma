"""Equation graph data model.

The in-memory representation the DSL layer produces and the evaluation loop
consumes. Each `Equation` has a stable key (see keys.py), a definition
payload, a list of upstream equation keys it depends on, and a status.

The graph also tracks deferred expansions: `foreach` registers
`DeferredExpansion` entries that are materialized into sub-graphs at
evaluation time, once their input collection or condition resolves.

Persistence to the per-flow state.db is handled by graph_db.py. This
module is pure data + helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class EquationStatus(str, Enum):
    PENDING = "pending"
    COMPUTING = "computing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_INPUT = "awaiting_input"
    # Tool referenced by a tool_call equation isn't registered yet. Not a
    # failure: when the tool's provider comes online, the engine resets the
    # equation to PENDING and it re-evaluates. See engine._finalize_failure
    # and engine._on_tool_available.
    WAITING_FOR_TOOL = "waiting_for_tool"
    INVALIDATED = "invalidated"


class EquationType(str, Enum):
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    LLM_BATCH = "llm_batch"
    LLM_SLOT = "llm_slot"
    CODE = "code"
    HITL = "hitl"
    CONTROL = "control"  # wrapper / foreach / zip / flow_input
    FLOW_INPUT = "flow_input"
    INFO = "info"
    CREATE_SET = "create_set"
    CREATE_GRID = "create_grid"
    CREATE_DOCUMENT = "create_document"
    CREATE_IMAGE = "create_image"
    CREATE_LAYOUT = "create_layout"
    RASTERIZE_LAYOUT = "rasterize_layout"
    WEB_SEARCH = "web_search"
    FETCH_MEDIA = "fetch_media"


# Transitions allowed on an equation's status. Any transition not listed is
# a bug. See FLOWS_TECH.md §FRP Runtime for the lifecycle.
_STATUS_TRANSITIONS = {
    EquationStatus.PENDING: {
        EquationStatus.COMPUTING,
        EquationStatus.AWAITING_INPUT,
        EquationStatus.WAITING_FOR_TOOL,
        EquationStatus.COMPLETED,  # store hit / hitl reuse (short-circuit)
        EquationStatus.FAILED,      # immediate fail
        EquationStatus.SKIPPED,     # user skip in a foreach
        EquationStatus.INVALIDATED, # transient state during invalidation
    },
    EquationStatus.COMPUTING: {
        EquationStatus.COMPLETED,
        EquationStatus.FAILED,
        EquationStatus.AWAITING_INPUT,
        EquationStatus.WAITING_FOR_TOOL,
        EquationStatus.INVALIDATED,
        EquationStatus.PENDING,  # retry / recovery
    },
    EquationStatus.COMPLETED: {
        EquationStatus.INVALIDATED,
    },
    EquationStatus.FAILED: {
        EquationStatus.PENDING,      # user triggers retry
        EquationStatus.SKIPPED,      # user skips a failing iteration
        EquationStatus.COMPLETED,    # user provides value manually
        EquationStatus.INVALIDATED,
    },
    EquationStatus.AWAITING_INPUT: {
        EquationStatus.COMPLETED,    # task resolved
        EquationStatus.INVALIDATED,
        EquationStatus.PENDING,      # program edit removed the hitl gate
    },
    EquationStatus.WAITING_FOR_TOOL: {
        EquationStatus.PENDING,      # tool registered — retry
        EquationStatus.SKIPPED,      # user skip
        EquationStatus.COMPLETED,    # user provides value manually
        EquationStatus.INVALIDATED,
    },
    EquationStatus.SKIPPED: {
        EquationStatus.INVALIDATED,
        EquationStatus.PENDING,
    },
    EquationStatus.INVALIDATED: {
        EquationStatus.PENDING,
    },
}


def can_transition(old: EquationStatus, new: EquationStatus) -> bool:
    if old == new:
        return True
    return new in _STATUS_TRANSITIONS.get(old, set())


@dataclass
class NodeRef:
    """A reference to an equation's output node, produced by a DSL primitive.

    DSL code treats this as an opaque handle. Inside the runtime we use it
    to discover upstream dependencies when one NodeRef is passed as a
    parameter to another DSL call.

    `equation_key` is always set (to the equation whose output this node
    represents). `collection` is True when the node resolves to a list
    (from foreach, tool n>1, hand-built lists of nodes, etc.); downstream
    foreach expansions use this to decide whether to iterate.

    Build-time inspection is rejected. Attribute access, iteration,
    subscript access, arithmetic, comparison, boolean coercion, and
    f-string interpolation all raise NodeUsageError. This matches FLOWS_DSL
    §8 ("you tried to use a value reference as a resolved value") — the
    single most common agent mistake per the authoring experiment.
    """
    equation_key: str
    collection: bool = False
    # Advisory iteration-key source — populated by the DSL layer for
    # collection nodes so foreach expansion can key the iterations.
    # For scalar nodes this is None.
    iteration_key_source: Any = None
    # When a collection node is known at build time to have a fixed set of
    # iteration keys (e.g. a scalar flow-input list), those keys are
    # stored here. Evaluation-time-resolved collections populate this after
    # their producer completes.
    known_iteration_keys: list[str] | None = None
    # Shape the node will resolve to (flow_dsl.shapes.Shape). Populated by
    # the DSL layer for cross-equation validation. Default None means
    # "unknown" — validators treat it permissively (no false positives on
    # nodes we can't reason about).
    shape: Any = None

    def __hash__(self) -> int:
        return hash(self.equation_key)

    # ----- build-time inspection guards -------------------------------------

    def _reject(self, op: str, *, hint: str = "") -> "None":
        # Deferred import: flow_dsl depends on flow_runtime, not the
        # other way around.
        from flow_dsl.errors import NodeUsageError
        raise NodeUsageError(op, hint=hint)

    def __iter__(self):
        self._reject(
            "iteration / spread (*node / for x in node / [*node])",
            hint=(
                "Nodes are opaque handles, not iterables. Use foreach() to "
                "loop over a collection node, or pass the node directly to "
                "another DSL call."
            ),
        )

    def __getitem__(self, key):
        self._reject(
            "subscript access (node[...])",
            hint=(
                "To extract a field from a structured node, use code(): "
                "code(\"data['field']\", inputs={\"data\": node}). "
                "Inside a foreach callback, items are resolved and support "
                "subscript access directly."
            ),
        )

    def __len__(self):
        self._reject("len(node)", hint="Node length is not known at graph-build time.")

    def __bool__(self):
        self._reject(
            "boolean coercion (if node: ...)",
            hint=(
                "Conditionals on computed values must be expressed as data "
                "flow: use switch()/when() for scalar values, filter() or "
                "partition() for collections, or code() for custom transforms."
            ),
        )

    def __int__(self):
        self._reject(
            "numeric coercion (int(node) / range(node) / len-like uses)",
            hint=(
                "Scalar inputs and DSL results are nodes at build time. "
                "Use code() to compute over them — e.g. "
                "code('list(range(n))', inputs={'n': node}) — then foreach "
                "over the resulting list."
            ),
        )

    def __index__(self):
        # Called by range(), slice, bin(), etc. when a non-int gets passed
        # to something expecting an integer position. Same hint as __int__.
        self.__int__()

    def __float__(self):
        self._reject(
            "numeric coercion (float(node))",
            hint="Use code() to compute on resolved values.",
        )

    def __format__(self, spec: str):
        self._reject(
            "f-string interpolation (f\"...{node}...\")",
            hint=(
                "Node values aren't available at graph-build time. "
                "Inside a foreach callback, items are resolved — use f-strings "
                "on those. Otherwise build the string with code(): "
                "code(\"f'...{data}...'\", inputs={\"data\": node})."
            ),
        )

    def __getattr__(self, name: str):
        # `equation_key`, `collection`, etc. are set by dataclass __init__,
        # so they resolve before __getattr__ fires. __getattr__ only runs for
        # missing attributes, which for a NodeRef means the agent tried to
        # access a field of the resolved value (.name, .title, etc.). Dunder
        # lookups bypass __getattr__, so this never fires for magic methods.
        # Private attrs (`_reject`, etc.) are ignored to avoid interfering
        # with internal use and with frameworks (copy, pickle) that probe.
        if name.startswith("_"):
            raise AttributeError(name)
        self._reject(
            f"attribute access (.{name})",
            hint=(
                "Nodes don't expose resolved fields at graph-build time. "
                "Inside a foreach callback, items are resolved — use .name/"
                "['key'] on those. Or extract with code()."
            ),
        )

    def _reject_op(self, op_name: str):
        def _rejector(self_, *args, **kwargs):
            self_._reject(
                f"arithmetic/comparison ({op_name})",
                hint=(
                    "Nodes are opaque — you can't combine them with Python "
                    "operators. If you need to compute on resolved values, "
                    "use code()."
                ),
            )
        return _rejector

    # Rejected arithmetic / comparison operators. These make common mistakes
    # like `if node > 3` or `node + "foo"` surface a clear DSL error rather
    # than a cryptic AttributeError.
    def __add__(self, other): self._reject("arithmetic (node + other)")
    def __radd__(self, other): self._reject("arithmetic (other + node)")
    def __sub__(self, other): self._reject("arithmetic (node - other)")
    def __mul__(self, other): self._reject("arithmetic (node * other)")
    def __rmul__(self, other): self._reject("arithmetic (other * node)")
    def __truediv__(self, other): self._reject("arithmetic (node / other)")
    def __mod__(self, other): self._reject("arithmetic (node % other)")
    def __lt__(self, other): self._reject("comparison (node < other)")
    def __le__(self, other): self._reject("comparison (node <= other)")
    def __gt__(self, other): self._reject("comparison (node > other)")
    def __ge__(self, other): self._reject("comparison (node >= other)")
    # Note: __eq__ / __ne__ are intentionally left as the dataclass default.
    # The graph layer compares NodeRefs by equation_key when building
    # dependency sets, so equality must work.


@dataclass
class DeferredExpansion:
    """A foreach waiting for its input to resolve.

    `kind` is 'foreach'. `owner_key` is the equation_key of the
    wrapper equation the expansion will attach its sub-graph under.
    `input_equation_key` is the upstream collection. `callback` is the
    Python callable the DSL handed us, to be invoked per item at expansion time.
    `extra_kwargs` are the resolved-or-node kwargs captured by the DSL —
    resolved values flow through as data, NodeRefs as dependencies.
    `positional_index` is the positional index among DSL calls of the same
    kind in the enclosing callback body — used in the child keys.
    """
    kind: str
    owner_key: str
    parent_key: str
    input_equation_key: str
    callback: Optional[Callable[..., Any]] = None
    extra_kwargs: dict[str, Any] = field(default_factory=dict)
    positional_index: int = 0
    function_name: str = ""  # agent-supplied callable __name__
    expanded: bool = False
    # When the collection is a keyed upstream, we carry its IterationKeySource
    # so we can produce the right iteration keys at expansion time.
    iteration_key_source: Any = None
    # Set when a callback can't run with an unresolved item (probe raised
    # NodeUsageError). Blocks the early-expansion path so we fall back to
    # waiting for the upstream to COMPLETE.
    early_blocked: bool = False


@dataclass
class Equation:
    """Single graph node. Stable identity = `key`; state = `status` + `result`."""
    key: str
    equation_type: EquationType
    definition: dict[str, Any]
    dependencies: list[str] = field(default_factory=list)
    phase_path: list[str] = field(default_factory=list)
    status: EquationStatus = EquationStatus.PENDING
    inputs_hash: Optional[str] = None
    attempt: int = 1
    result: Any = None
    result_media_ids: list[int] = field(default_factory=list)
    execution_duration_ms: Optional[int] = None
    # Pure compute time reported by the tool (generation_time from media
    # metadata), excluding time spent waiting in the tool's own queue. For
    # tool_call equations that produce media; None otherwise. Used in the UI
    # anywhere "how long did this take to generate" should exclude queue wait.
    compute_duration_ms: Optional[int] = None
    error: Optional[str] = None

    def transition_to(self, new_status: EquationStatus) -> None:
        if not can_transition(self.status, new_status):
            raise ValueError(
                f"illegal status transition for {self.key!r}: {self.status} -> {new_status}"
            )
        self.status = new_status

    def is_waiting_for_flow_input(self) -> bool:
        """True when this flow input node has not been provided yet.

        Inputs declared with ``optional=True`` never block — the runtime
        completes them with ``None`` (scalars) or ``[]`` (collections) so
        downstream code() can handle the absence of a value.
        """
        if self.equation_type != EquationType.FLOW_INPUT:
            return False
        if self.definition.get("control_kind") != "flow_input":
            return False
        if self.definition.get("optional"):
            return False
        if self.definition.get("is_collection", True):
            return self.definition.get("values") is None
        return self.definition.get("value") is None


class EquationGraph:
    """Mutable in-memory graph. Thread-unsafe — callers serialize access."""

    def __init__(self) -> None:
        self._equations: dict[str, Equation] = {}
        self._dependents: dict[str, set[str]] = {}
        self._deferred: dict[str, DeferredExpansion] = {}
        # Root equation key (what the flow function returned), set by the
        # graph builder. None for flows that don't return anything. For
        # multi-output returns (tuple/dict of NodeRefs), this holds the first
        # key; ``output_keys`` holds the full set.
        self.root_key: Optional[str] = None
        # All equations the flow's ``return`` statement surfaces as outputs.
        # Derived by the builder from the return value: a single NodeRef
        # contributes one key; a tuple/list/dict of NodeRefs contributes one
        # per NodeRef. Empty when the flow returns nothing (or a non-node
        # value). The flow UI uses this to decide which equations get a
        # synthetic "Output" node in the graph viz — a dangling side-effect
        # call (e.g. ``hitl.approve(x, ...)`` whose result isn't used) is not
        # an output even though it has no downstream consumer.
        self.output_keys: list[str] = []
        # Reverse lookup for named outputs declared via @flow(outputs=...).
        # Maps surfaced equation key -> declared output name. Single-output
        # flows that return a bare NodeRef still populate this mapping with
        # that lone declared name.
        self.output_name_by_key: dict[str, str] = {}
        # UI-serialized mirror of the @flow(inputs={...}) declaration, set
        # by the graph builder. Shape: {name: {type, description?, default?,
        # options?, lines?}}. flow_lifecycle writes this into
        # Flow.input_schema so the input form stays in sync with program.py.
        self.input_specs: dict[str, Any] = {}
        # Same idea for @flow(outputs={...}); shape: {name: {type,
        # description?}}. Mirrored into Flow.output_schema.
        self.output_specs: dict[str, Any] = {}

    # ----- basic accessors -----

    def __contains__(self, key: str) -> bool:
        return key in self._equations

    def get(self, key: str) -> Equation:
        return self._equations[key]

    def try_get(self, key: str) -> Optional[Equation]:
        return self._equations.get(key)

    def all_equations(self) -> list[Equation]:
        return list(self._equations.values())

    def keys(self) -> list[str]:
        return list(self._equations.keys())

    def dependents_of(self, key: str) -> set[str]:
        """Equations that depend on `key` (direct downstream set)."""
        return set(self._dependents.get(key, set()))

    # ----- mutation -----

    def add_equation(self, eq: Equation) -> Equation:
        if eq.key in self._equations:
            raise KeyError(f"equation {eq.key!r} already in graph")
        self._equations[eq.key] = eq
        for dep in eq.dependencies:
            self._dependents.setdefault(dep, set()).add(eq.key)
        return eq

    def replace_dependencies(self, key: str, dependencies: list[str]) -> None:
        """Replace an equation's upstream edges and keep the reverse index in sync."""
        eq = self._equations.get(key)
        if eq is None:
            raise KeyError(f"equation {key!r} not in graph")

        old_deps = set(eq.dependencies)
        new_deps = set(dependencies)

        for dep in old_deps - new_deps:
            dependents = self._dependents.get(dep)
            if dependents is None:
                continue
            dependents.discard(key)
            if not dependents:
                del self._dependents[dep]

        for dep in new_deps - old_deps:
            self._dependents.setdefault(dep, set()).add(key)

        eq.dependencies = list(dependencies)

    def remove_equation(self, key: str) -> None:
        eq = self._equations.pop(key, None)
        if eq is None:
            return
        for dep in eq.dependencies:
            deps = self._dependents.get(dep)
            if deps is not None:
                deps.discard(key)
                if not deps:
                    del self._dependents[dep]
        # Drop the dependent-set anchored at `key` — orphan downstream
        # equations are handled by the caller (graph diff removes them
        # explicitly).
        self._dependents.pop(key, None)

    def register_deferred(self, expansion: DeferredExpansion) -> None:
        if expansion.owner_key in self._deferred:
            raise KeyError(
                f"deferred expansion for {expansion.owner_key!r} already registered"
            )
        self._deferred[expansion.owner_key] = expansion

    def deferred(self, owner_key: str) -> Optional[DeferredExpansion]:
        return self._deferred.get(owner_key)

    def all_deferred(self) -> list[DeferredExpansion]:
        return list(self._deferred.values())

    def pop_deferred(self, owner_key: str) -> Optional[DeferredExpansion]:
        return self._deferred.pop(owner_key, None)

    # ----- scheduler helpers -----

    def ready_equations(self) -> list[Equation]:
        """Equations eligible to evaluate: status=pending, deps terminal.

        A dep is "satisfied" if it is COMPLETED (has a result to pass
        through) or SKIPPED (the iteration's output is dropped from the
        parent foreach's collection; see FLOWS_TECH §Failure Isolation).

        Control wrappers with an unexpanded deferred (foreach) are
        skipped: their real dependencies are the per-iteration children
        that only exist after expansion. Without this filter, a foreach
        registered inside another foreach's callback body sees only its
        source deps — which are already completed — and the scheduler
        completes it with an empty collection before the next tick's
        ``_try_expand_deferred`` pass materializes its children.
        """
        out: list[Equation] = []
        for eq in self._equations.values():
            if eq.status != EquationStatus.PENDING:
                continue
            if eq.is_waiting_for_flow_input():
                continue
            deferred = self._deferred.get(eq.key)
            if deferred is not None and not deferred.expanded:
                continue
            if not all(
                self._equations.get(dep) is not None
                and self._equations[dep].status in (
                    EquationStatus.COMPLETED,
                    EquationStatus.SKIPPED,
                )
                for dep in eq.dependencies
            ):
                continue
            out.append(eq)
        return out

    def descendants(self, key: str) -> set[str]:
        """Transitive closure of `dependents_of(key)` excluding `key` itself."""
        out: set[str] = set()
        stack = list(self._dependents.get(key, set()))
        while stack:
            cur = stack.pop()
            if cur in out:
                continue
            out.add(cur)
            stack.extend(self._dependents.get(cur, set()))
        return out

"""BuildContext — thread-local ambient state for DSL graph construction.

Each DSL primitive (tool, llm, code, hitl.*, foreach, ...) consults the
current BuildContext to know which graph to add equations to and what
positional-index to use for equation keys. The context is pushed by the
graph builder before executing the flow function; foreach callbacks push
a fresh frame so their nested DSL calls get keys
relative to the callback.

Kept in its own module so both flow_runtime internals and the user-facing
DSL primitives can import without circular references.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    # Type-only import — avoids a circular dep at module load time since
    # flow_runtime/__init__.py re-exports the DSL shim.
    from flow_runtime.graph import EquationGraph  # pragma: no cover


@dataclass
class BuildFrame:
    """One scope of equation construction.

    Holds the equation-key prefix for nested DSL calls, the positional-index
    counters per primitive kind, and the phase stack for ``with phase(...)``
    blocks inside this frame.
    """

    parent_key: str
    function_name: str
    phase_stack: list[str] = field(default_factory=list)
    kind_counters: dict[str, int] = field(default_factory=dict)
    # (phase_stack_at_registration, equation_key) in registration order.
    # Used by info() to establish implicit phase ordering: an info card at
    # the end of a phase waits for work registered earlier in that phase
    # (or in any phase nested beneath it).
    registered_equations: list[tuple[tuple[str, ...], str]] = field(default_factory=list)

    def next_positional(self, kind: str) -> int:
        i = self.kind_counters.get(kind, 0)
        self.kind_counters[kind] = i + 1
        return i

    def equations_in_phase(self, phase_stack: list[str]) -> list[str]:
        """Return keys registered within ``phase_stack`` or any nested phase.

        Empty ``phase_stack`` means "root" and returns [] — root-level info
        cards don't implicitly depend on the whole flow.
        """
        if not phase_stack:
            return []
        prefix = tuple(phase_stack)
        n = len(prefix)
        return [
            key
            for (ppath, key) in self.registered_equations
            if len(ppath) >= n and ppath[:n] == prefix
        ]


@dataclass
class BuildContext:
    """Ambient state for DSL calls during graph construction."""

    # Typed as Any rather than EquationGraph to avoid a runtime import of
    # flow_runtime.graph here — see the TYPE_CHECKING guard above.
    graph: Any
    frames: list[BuildFrame] = field(default_factory=list)

    @property
    def current_frame(self) -> BuildFrame:
        if not self.frames:
            raise RuntimeError(
                "no active BuildFrame — DSL call made outside a build context"
            )
        return self.frames[-1]

    @property
    def current_phase_path(self) -> list[str]:
        # Phase stacks are per-frame so a foreach callback's inner phases
        # nest under the callback, not under the parent.
        return list(self.current_frame.phase_stack)


_CURRENT_CONTEXT: contextvars.ContextVar[Optional[BuildContext]] = (
    contextvars.ContextVar("stimma_flow_build_context", default=None)
)


def current_context() -> BuildContext:
    ctx = _CURRENT_CONTEXT.get()
    if ctx is None:
        raise RuntimeError(
            "no active BuildContext — flow DSL called outside graph construction"
        )
    return ctx


@contextlib.contextmanager
def activate_context(ctx: BuildContext):
    token = _CURRENT_CONTEXT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT_CONTEXT.reset(token)


@contextlib.contextmanager
def push_frame(
    ctx: BuildContext,
    parent_key: str,
    function_name: str,
    phase_stack: Optional[list[str]] = None,
):
    # Inherit the caller's phase stack for foreach expansion so DSL
    # calls inside the callback register under the same phase as the wrapper.
    # Top-level frames pass nothing and start with an empty stack.
    frame = BuildFrame(
        parent_key=parent_key,
        function_name=function_name,
        phase_stack=list(phase_stack) if phase_stack else [],
    )
    ctx.frames.append(frame)
    try:
        yield frame
    finally:
        popped = ctx.frames.pop()
        assert popped is frame, "BuildFrame stack corruption"

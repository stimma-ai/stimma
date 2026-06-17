"""DSL-specific exceptions and agent-friendly error formatting.

The goal of this module is to produce error messages that an LLM agent can
fix by reading. Each error category points at the mistake and suggests the
correct pattern, matching the failure modes observed in the DSL authoring
experiment (see stimma-cloud/docs/dsl_experiment/REPORT.md).

Categories:

- ``NodeUsageError`` — the agent tried to inspect a value reference at
  graph-build time (e.g. ``node.name``, ``if node:``, ``len(node)``,
  ``*node``, ``f"{node}"``). This is the single most common mistake per the
  experiment's R-category errors.
- ``DSLMisuseError`` — the agent misused a DSL primitive (passed a dict to
  hitl.select, used ``"list[Node]"`` as an output type, etc.).
- ``ProgramLoadError`` — import/exec of program.py failed. Wraps the
  underlying traceback so the agent can see the exact line.
"""

from __future__ import annotations

from typing import Optional


class DSLError(Exception):
    """Base for any error surfaced from the flow DSL layer.

    All subclasses carry a ``suggestion`` field — a one-liner the agent can
    use to fix the program without needing to re-read the docs.
    """

    def __init__(self, message: str, *, suggestion: str = "") -> None:
        super().__init__(message)
        self.suggestion = suggestion

    def format_for_agent(self) -> str:
        if self.suggestion:
            return f"{self.args[0]}\n\nSuggestion: {self.suggestion}"
        return str(self.args[0])


class NodeUsageError(DSLError):
    """Raised when the agent treats a value reference as a resolved value.

    This includes: attribute access on a Node, iteration/unpacking, arithmetic,
    comparisons, boolean coercion, subscript access, and f-string interpolation.
    The agent sees ``"you tried to use a value reference as a resolved value"``
    as the leading phrase, which matches the language in FLOWS_DSL.md §8.
    """

    def __init__(self, operation: str, *, hint: str = "") -> None:
        suggestion = hint or (
            "Value references (nodes) are opaque handles — use them as "
            "parameters to other DSL calls, not as Python values. If you need "
            "the resolved value, use a foreach callback (where items are "
            "resolved) or pass the node to code()."
        )
        super().__init__(
            "you tried to use a value reference as a resolved value "
            f"({operation})",
            suggestion=suggestion,
        )


class DSLMisuseError(DSLError):
    """Raised when a DSL primitive is called with invalid arguments.

    Not for Python TypeErrors (those pass through as-is) — this is for
    semantic misuse: wrong type passed to hitl.select, unknown tool ID,
    ``"list[Node]"`` output type, etc.
    """


class ProgramLoadError(DSLError):
    """Raised when program.py cannot be imported/executed.

    ``category`` is one of ``"syntax"``, ``"import"``, ``"name"``, ``"type"``,
    ``"dsl"``, or ``"other"`` — the loader classifies the underlying exception
    so the UI can show the right action (edit flow vs. retry).
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "other",
        program_traceback: str = "",
        suggestion: str = "",
    ) -> None:
        super().__init__(message, suggestion=suggestion)
        self.category = category
        self.program_traceback = program_traceback


_VALID_OUTPUT_TYPES = frozenset({
    "str",
    "int",
    "float",
    "bool",
    "text",
    "markdown",
    "json",
    "dict",
    "media",
    "any",
    "list[str]",
    "list[int]",
    "list[float]",
    "list[bool]",
    "list[text]",
    "list[markdown]",
    "list[json]",
    "list[dict]",
    "list[media]",
    "enum",
})


def validate_output_type(type_str: str) -> Optional[str]:
    """Return a suggestion string if ``type_str`` is invalid, else None.

    Targets the #1 observed mistake: ``"list[Node]"`` / ``"Node"`` as output
    type. Intentionally permissive for future types; we only flag things we
    are confident are wrong.
    """
    if not isinstance(type_str, str) or not type_str:
        return "output type must be a non-empty string"
    if "Node" in type_str:
        return (
            f"output type {type_str!r} uses 'Node' — 'Node' is the DSL's "
            "reference system, not a value type. Use a concrete type like "
            "'str', 'media', 'list[media]', 'json', or 'list[json]'."
        )
    if type_str.lower() in _VALID_OUTPUT_TYPES:
        return None
    # Unknown but not obviously wrong; accept with no suggestion.
    return None

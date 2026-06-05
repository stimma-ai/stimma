"""Pluggable evaluator protocol for the FRP runtime.

The runtime's scheduler hands each ready equation to the appropriate
evaluator. For Phase 2 we keep this indirection small and testable:

  - tests supply a dict of evaluators (tool -> lambda, llm -> lambda,
    code -> lambda) so integration tests can drive the scheduler without
    hitting real providers.
  - production wiring (done in Phase 3 when we wire the recipe agent) will
    provide concrete evaluators that call the existing `generation_queue`,
    `llm_completion`, and `run_code_in_sandbox`.

The protocol is intentionally async. Evaluators return `EvaluatorResult`
which the runtime uses to update equation state and fire store writes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol


class EvaluatorError(RuntimeError):
    """Base class for evaluator-surfaced errors, classified by category.

    Categories follow RECIPES_TECH.md §Error Handling:

      - transient      (retryable — network, rate limit, 5xx)
      - tool_error     (no retry — safety filter, bad input)
      - code_error     (no retry — exception in code())
      - llm_error      (retry once — schema mismatch, refusal)
      - resource       (pause recipe — out of credits, disk)
    """

    def __init__(self, message: str, *, category: str = "tool_error") -> None:
        super().__init__(message)
        self.category = category


TRANSIENT = "transient"
TOOL_ERROR = "tool_error"
CODE_ERROR = "code_error"
LLM_ERROR = "llm_error"
RESOURCE_ERROR = "resource"
# Tool referenced by a tool_call equation isn't registered. Not treated as
# a failure — engine parks the equation in WAITING_FOR_TOOL and resets it
# when the tool's provider comes online.
TOOL_UNAVAILABLE = "tool_unavailable"


@dataclass
class EvaluationRequest:
    """Context passed to an evaluator when the scheduler dispatches an equation."""
    equation_key: str
    equation_type: str
    attempt: int
    definition: dict[str, Any]
    resolved_inputs: dict[str, Any]
    seed: Optional[int] = None
    # hitl-specific fields
    hitl_type: Optional[str] = None
    instructions: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    # Populated by the engine so production evaluators can tag produced
    # artifacts back to the recipe that made them (RECIPES_TECH §Media
    # Integration). Optional / empty for older tests that construct a
    # request by hand.
    recipe_id: Optional[int] = None
    project_id: Optional[int] = None
    phase_path: list[str] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Outcome of a single equation evaluation."""
    value: Any = None
    media_ids: list[int] = field(default_factory=list)
    # When this equation is HITL and no stored decision exists, the
    # evaluator returns awaiting_input=True and the scheduler creates a
    # task row and marks the equation awaiting_input.
    awaiting_input: bool = False
    # Tool-reported pure compute time in ms (derived from the produced
    # media's ``generation_metadata.generation_time``). Present only for
    # tool_call evaluations; the engine surfaces it on the equation so the
    # per-iteration UI can display compute time instead of the queue-inclusive
    # wall-clock.
    compute_duration_ms: Optional[int] = None


class Evaluator(Protocol):
    async def __call__(self, request: EvaluationRequest) -> EvaluationResult: ...


@dataclass
class EvaluatorRegistry:
    """Maps equation_type (str) to an async callable.

    Keys used:
      - 'tool_call'
      - 'llm_call'
      - 'code'
      - 'hitl.select', 'hitl.approve'
    """
    evaluators: dict[str, Evaluator] = field(default_factory=dict)

    def register(self, key: str, fn: Evaluator) -> None:
        self.evaluators[key] = fn

    def resolve(self, equation_type: str, hitl_type: Optional[str] = None) -> Evaluator:
        if equation_type == "hitl" and hitl_type:
            lookup_key = f"hitl.{hitl_type}"
            if lookup_key in self.evaluators:
                return self.evaluators[lookup_key]
            if "hitl" in self.evaluators:
                return self.evaluators["hitl"]
        if equation_type in self.evaluators:
            return self.evaluators[equation_type]
        raise KeyError(
            f"no evaluator registered for equation_type={equation_type!r} "
            f"(hitl_type={hitl_type!r})"
        )


# ----- Error classification helper ------------------------------------------


def classify_exception(exc: BaseException) -> str:
    """Best-effort classification of exceptions raised by evaluators.

    Evaluators should raise `EvaluatorError(category=...)` when possible;
    this function falls back for plain exceptions.
    """
    if isinstance(exc, EvaluatorError):
        return exc.category
    # Asyncio cancellation / timeout — transient.
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError)):
        return TRANSIENT
    # Default is tool_error (no retry). Safer than silently retrying.
    return TOOL_ERROR


# ----- Retry policy ---------------------------------------------------------


RETRY_POLICY = {
    TRANSIENT: 3,    # 3 retries with exponential backoff
    LLM_ERROR: 1,    # single retry
    TOOL_ERROR: 0,   # no retry
    CODE_ERROR: 0,   # no retry
    RESOURCE_ERROR: 0,  # pause the recipe (handled by runtime)
    TOOL_UNAVAILABLE: 0,  # park in WAITING_FOR_TOOL; no retry loop
}


def retry_budget(category: str) -> int:
    return RETRY_POLICY.get(category, 0)

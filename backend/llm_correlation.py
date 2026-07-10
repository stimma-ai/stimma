"""Correlation IDs for outbound Stimma Cloud LLM requests.

Mechanical headers that let Stimma Cloud group requests server-side:

    X-Stimma-Chat-Id        conversation (when a chat is in scope)
    X-Stimma-Run-Id         one agent-loop execution
    X-Stimma-Agent-Context  main | flow | prompt-agent | delegate | title

(`X-Stimma-Session` already flows separately via llm_http's ``session_id``
parameter and is unchanged.)

Scoped via contextvars so nested helpers (run_code's ``llm()``, specialists,
flow equation evaluations) inherit the enclosing execution's IDs without
explicit threading. ``llm_http.acompletion`` attaches the headers only on
requests to Stimma Cloud — BYOAI / custom endpoints never see them.
"""
from __future__ import annotations

import contextlib
import contextvars
import uuid
from typing import Dict, Iterator, Optional, Union

AGENT_CONTEXTS = ("main", "flow", "prompt-agent", "delegate", "title")

_agent_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "llm_agent_context", default=None
)
_chat_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "llm_chat_id", default=None
)
_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "llm_run_id", default=None
)


@contextlib.contextmanager
def llm_correlation_context(
    agent_context: str,
    *,
    chat_id: Optional[Union[int, str]] = None,
    run_id: Optional[str] = None,
) -> Iterator[str]:
    """Scope one agent-loop execution. Mints a fresh run id unless given.

    Yields the run id so callers can log or reuse it.
    """
    rid = run_id or str(uuid.uuid4())
    ctx_token = _agent_context.set(agent_context)
    chat_token = _chat_id.set(str(chat_id) if chat_id is not None else None)
    run_token = _run_id.set(rid)
    try:
        yield rid
    finally:
        _run_id.reset(run_token)
        _chat_id.reset(chat_token)
        _agent_context.reset(ctx_token)


def correlation_headers() -> Dict[str, str]:
    """Headers for the current correlation scope (empty outside any scope)."""
    headers: Dict[str, str] = {}
    agent_context = _agent_context.get()
    if agent_context:
        headers["X-Stimma-Agent-Context"] = agent_context
    chat_id = _chat_id.get()
    if chat_id:
        headers["X-Stimma-Chat-Id"] = chat_id
    run_id = _run_id.get()
    if run_id:
        headers["X-Stimma-Run-Id"] = run_id
    return headers

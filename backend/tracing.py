"""Langfuse LLM tracing for Stimma's agentic flows.

Gated on the existing Session Recording opt-in (Developer settings). When
that toggle is on, agent runs / prompt enhancement / recipe runs emit
traces to Langfuse. Designed so any failure here is fire-and-forget —
tracing must never break the app. All public helpers return no-op context
managers when disabled.

Routing (default): traces flow through the Stimma Cloud worker proxy at
`{cloud.base_url}/api/langfuse-ingest` so the Langfuse credentials never
leave the cloud. Local dev installs can override with LANGFUSE_BASE_URL +
LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY env vars to talk direct.

Usage:
    from tracing import init_tracing, agent_trace, generation, flush

    # Once at startup:
    init_tracing()

    # Wrap an agent run:
    async with agent_trace("agent-run", input=user_msg, session_id=str(chat.id),
                           tags=["recipe"] if chat.recipe_id else ["main"]) as span:
        ...
        span.update(output=final_message)

    # Wrap an LLM call (auto-nested under any active parent span):
    with generation("llm-completion", model=model, input=messages) as gen:
        resp = await call_llm(...)
        gen.update(output=resp.content, usage_details={
            "input": resp.usage.prompt_tokens,
            "output": resp.usage.completion_tokens,
            "total": resp.usage.total_tokens,
        })
"""
from __future__ import annotations

import contextlib
import os
import random
import sys
import threading
from typing import Any, Dict, Iterator, List, Optional

from core.logging import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_client = None  # langfuse.Langfuse client (or None when host not resolvable)
_client_init_attempted = False
_sample_rate = 1.0
_install_id: Optional[str] = None  # forwarded as default user_id

# Placeholder keys used when routing through the Stimma Cloud proxy. The
# Langfuse Python SDK requires non-empty values; the proxy strips and
# replaces the Authorization header with the real Basic Auth before
# forwarding to the upstream Langfuse host.
_PROXY_PLACEHOLDER_PUBLIC_KEY = "pk-stimma-proxy"
_PROXY_PLACEHOLDER_SECRET_KEY = "sk-stimma-proxy"


def _gate_open() -> bool:
    """Live read of the Session Recording opt-in. Cheap; called per trace."""
    try:
        from config import get_settings
        return bool(getattr(get_settings(), "posthog_session_recording", False))
    except Exception:
        return False


def _resolve_user_id() -> Optional[str]:
    """Pick the best user identifier for Langfuse: signed-in email, else install_id.

    Read live (not cached) so login/logout takes effect without a restart.
    Email is preferred because Langfuse's Users view shows the raw user_id
    string — UUIDs are unreadable, emails are not.
    """
    try:
        from auth_storage import load_auth_state
        state = load_auth_state()
        if state:
            email = (state.get("user") or {}).get("email")
            if email:
                return email
    except Exception:
        pass
    return _install_id


def _resolve_host_and_keys() -> Optional[tuple[str, str, str, bool]]:
    """Return (host, public_key, secret_key, via_proxy) or None if not configurable.

    Resolution order:
      1. LANGFUSE_BASE_URL / LANGFUSE_HOST env var (direct mode, dev only).
      2. Explicit `tracing.langfuse_host` in config (direct mode, dev only).
      3. Stimma Cloud proxy at `{cloud.base_url}/api/langfuse-ingest` (default).

    In proxy mode the keys are placeholders; the Cloudflare worker attaches
    the real Basic Auth before forwarding upstream.
    """
    try:
        from config import get_settings
        settings = get_settings()
        cfg = settings.tracing
    except Exception as e:
        log.info(f"tracing: config load failed ({e})")
        return None

    direct_host = (
        os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or cfg.langfuse_host
    )
    if direct_host:
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY") or cfg.langfuse_public_key
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY") or cfg.langfuse_secret_key
        if not (public_key and secret_key):
            log.info("tracing: direct host set but keys missing; not sending")
            return None
        return (direct_host.rstrip("/"), public_key, secret_key, False)

    # Default: route through Stimma Cloud proxy.
    cloud_base = (settings.cloud.base_url or "").rstrip("/")
    if not cloud_base:
        return None
    proxy_host = f"{cloud_base}/api/langfuse-ingest"
    return (proxy_host, _PROXY_PLACEHOLDER_PUBLIC_KEY, _PROXY_PLACEHOLDER_SECRET_KEY, True)


def _ensure_client() -> bool:
    """Lazily build the Langfuse client from config + env. Returns True if usable."""
    global _client, _client_init_attempted, _sample_rate, _install_id

    if _client is not None:
        return True
    with _lock:
        if _client is not None:
            return True
        if _client_init_attempted:
            # We tried before and failed — don't keep retrying every call.
            return False
        _client_init_attempted = True

        resolved = _resolve_host_and_keys()
        if resolved is None:
            return False
        host, public_key, secret_key, via_proxy = resolved

        try:
            from config import get_settings
            settings = get_settings()
            _install_id = settings.telemetry.install_id
            _sample_rate = max(0.0, min(1.0, float(settings.tracing.sample_rate)))
        except Exception:
            _sample_rate = 1.0

        try:
            from langfuse import Langfuse  # noqa: WPS433
        except ImportError:
            log.warning("tracing: langfuse package not installed")
            return False

        try:
            _client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            mode = "proxy" if via_proxy else "direct"
            log.info(f"tracing: client ready ({mode} host={host}, sample_rate={_sample_rate})")
            return True
        except Exception as e:
            log.warning(f"tracing: client init failed ({e})")
            _client = None
            return False


def init_tracing() -> bool:
    """Eagerly try to build the Langfuse client at startup.

    Always called at startup; will only build the client if keys are
    configured. The gate (Session Recording) is checked live per trace,
    so toggling it does not require a restart.
    """
    if not _ensure_client():
        return False
    if not _gate_open():
        log.info("tracing: client ready but Session Recording is off (gated)")
    return True


def is_enabled() -> bool:
    """True iff tracing should send a span right now (gate + client ready)."""
    return _gate_open() and _ensure_client()


def _sample() -> bool:
    if _sample_rate >= 1.0:
        return True
    if _sample_rate <= 0.0:
        return False
    return random.random() < _sample_rate


class _NoopSpan:
    """No-op stand-in used when tracing is disabled or sampling rejects a run."""

    def update(self, **_: Any) -> None:
        return None

    def update_trace(self, **_: Any) -> None:
        return None

    def score(self, *_: Any, **__: Any) -> None:
        return None

    @property
    def trace_id(self) -> Optional[str]:
        return None

    @property
    def id(self) -> Optional[str]:
        return None


@contextlib.contextmanager
def agent_trace(
    name: str,
    *,
    input: Any = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    sampled: bool = True,
) -> Iterator[Any]:
    """Open a parent span representing one agent run / one user-facing flow.

    The returned object exposes `.update(output=..., metadata=...)` and is the
    OTel-active span — any nested `generation()` calls (or other Langfuse SDK
    spans created in the same context) will be children of this span and
    share its trace id.

    `sampled=False` forces a no-op (used by callers that have already decided
    to skip — e.g. internal subagents that shouldn't double-trace).
    """
    if not is_enabled() or not sampled or not _sample():
        yield _NoopSpan()
        return

    try:
        from langfuse import propagate_attributes  # noqa: WPS433
    except Exception as e:
        log.debug(f"tracing: import failed ({e})")
        yield _NoopSpan()
        return

    # propagate_attributes wants metadata values to be strings.
    str_metadata: Optional[Dict[str, str]] = None
    if metadata:
        str_metadata = {k: str(v) for k, v in metadata.items() if v is not None}

    # Open the span/propagation context. Setup failures must never fail the
    # caller — fall back to a no-op span.
    stack = contextlib.ExitStack()
    try:
        span = stack.enter_context(
            _client.start_as_current_observation(
                as_type="span",
                name=name,
                input=input,
            )
        )
        propagate_kwargs: Dict[str, Any] = {"trace_name": name}
        # Prefer the signed-in cloud account email; fall back to anonymous
        # install_id so unsigned installs are still attributable.
        propagate_user = user_id or _resolve_user_id()
        if propagate_user:
            propagate_kwargs["user_id"] = propagate_user
        if session_id:
            propagate_kwargs["session_id"] = session_id
        if tags:
            propagate_kwargs["tags"] = tags
        if str_metadata:
            propagate_kwargs["metadata"] = str_metadata
        stack.enter_context(propagate_attributes(**propagate_kwargs))
    except Exception as e:
        log.debug(f"tracing: span context error ({e})")
        stack.close()
        yield _NoopSpan()
        return

    # Setup succeeded. Run the caller's body and close the span. Body exceptions
    # MUST propagate (they get recorded by __exit__) — never yield again here, or
    # contextlib raises "generator didn't stop after throw()".
    try:
        yield span
    except BaseException:
        if not stack.__exit__(*sys.exc_info()):
            raise
    else:
        stack.__exit__(None, None, None)


@contextlib.contextmanager
def generation(
    name: str,
    *,
    model: Optional[str] = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[Any]:
    """Open a generation observation around a single LLM call.

    Auto-nests under any currently active span (incl. an `agent_trace`).
    The returned object accepts `.update(output=..., usage_details=...,
    model=..., metadata=...)`.
    """
    if not is_enabled():
        yield _NoopSpan()
        return

    kwargs: Dict[str, Any] = {"as_type": "generation", "name": name}
    if model:
        kwargs["model"] = model
    if input is not None:
        kwargs["input"] = input
    if metadata:
        kwargs["metadata"] = metadata

    try:
        cm = _client.start_as_current_observation(**kwargs)
        gen = cm.__enter__()
    except Exception as e:
        log.debug(f"tracing: failed to open generation ({e})")
        yield _NoopSpan()
        return

    # Body exceptions MUST propagate (recorded via __exit__) — never yield again.
    try:
        yield gen
    except BaseException:
        if not cm.__exit__(*sys.exc_info()):
            raise
    else:
        cm.__exit__(None, None, None)


def flush() -> None:
    """Flush buffered traces to Langfuse. Safe to call at shutdown."""
    if _client is None:
        return
    try:
        _client.flush()
    except Exception as e:
        log.debug(f"tracing: flush error ({e})")


def shutdown() -> None:
    """Flush and shut down the client."""
    global _client
    if _client is None:
        return
    try:
        _client.flush()
    except Exception:
        pass
    try:
        _client.shutdown()
    except Exception:
        pass
    with _lock:
        _client = None

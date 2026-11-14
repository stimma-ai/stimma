"""A prepared prompt's shared pieces: the prompt as the reader sees it ([exact text] masked,
saved wildcards inlined), the store, the chat model the reader and the option writer ask, and
realize(): one generation's prompt drawn from its slots (fill.py), with no model call.

slots.prepare prepares a prompt; this module is what preparing, drawing and the routes share.
"""

from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger
from prompt_programs.fill import DrawAborted, ProgramError, RunResult, tidy_text
from prompt_programs.store import ProgramStore

log = get_logger(__name__)


class PromptTooLong(ProgramError):
    """A prompt (with its lists and segments expanded) too long to read."""

    code = "prompt_too_long"


# A prompt past this never reaches the reader: a pasted essay would overflow its context.
MAX_PROMPT_CHARS = 8000


class ModelRefused(ProgramError):
    """The provider's content filter refused the reader's or the option writer's request."""

    code = "program_failed"


def model_failure(e: BaseException) -> Optional[Exception]:
    """The error to report when the chat model itself failed to answer (unreachable, a
    provider rejection or 5xx, a broken stream, out of quota or balance), else None. Those
    are the chat model being unavailable, not a bug: the client offers Try again or Direct."""
    import httpx
    from llm_http import (ContentFilteredError, EntitlementError, LLMConnectionError, LLMStreamError,
                          QuotaExceededError)
    from llm_resolver import LLMInsufficientBalanceError, LLMUnavailableError

    if isinstance(e, ContentFilteredError):
        return ModelRefused(f"The provider's content filter declined: {e}"[:300])
    if isinstance(e, EntitlementError):
        return LLMInsufficientBalanceError(str(e)[:300] or "No balance left for the chat model.")
    if isinstance(e, (LLMConnectionError, LLMStreamError, QuotaExceededError, httpx.HTTPError)):
        return LLMUnavailableError(str(e)[:300] or "The chat model didn't answer.")
    return None


# --------------------------------------------------------------------------- the prompt as read

def expand_named_lists(prompt: str, wildcards: List[Dict[str, Any]], segments: List[Dict[str, Any]]) -> str:
    """{{name}} → the segment's text, or the wildcard's values as an inline {a|b|c} list,
    so the program sees the user's full list instead of one random value."""
    if not wildcards and not segments:
        return prompt
    lists = {str(w["name"]).lower(): [str(v) for v in (w.get("values") or [])] for w in wildcards}
    texts = {str(s["name"]).lower(): s.get("content", "") for s in segments}

    def repl(m: re.Match) -> str:
        key = m.group(1).strip().lower()
        if key in texts:
            return texts[key]
        values = lists.get(key)
        return "{" + "|".join(values) + "}" if values else m.group(0)

    return re.sub(r"\{\{([^{}]+)\}\}", repl, prompt)


_EXACT = re.compile(r"\[([^\[\]{}][^\[\]]*)\]")
_VERBATIM = re.compile(r"\[([^\[\]]+)\]")


def mask_exact(prompt: str) -> Tuple[str, Dict[str, str]]:
    """[exact text] is the user's, untouched: no model ever reads it. Each becomes a
    token like [EXACT_1] for every model step, and realize() puts the text back."""
    exact: Dict[str, str] = {}

    def repl(m: re.Match) -> str:
        token = f"EXACT_{len(exact) + 1}"
        exact[token] = m.group(1)
        return f"[{token}]"

    return _EXACT.sub(repl, prompt), exact


def unmask_exact(text: str, exact: Dict[str, str]) -> str:
    """Put the user's text back, still in [brackets]: later steps (Improve, Translate) keep
    bracketed text untouched, and the final cleanup removes the brackets."""
    for token, original in sorted((exact or {}).items(), key=lambda kv: -len(kv[0])):  # EXACT_10 before EXACT_1
        text = text.replace(f"[{token}]", token).replace(token, f"[{original}]")
    return text


def realized_text(prompt: str) -> str:
    """What the image model would see (protected text unwrapped)."""
    return re.sub(r"\s+", " ", _VERBATIM.sub(lambda m: m.group(1), prompt)).strip()


def emitted_as(value: str, text: str) -> Optional[str]:
    """A drawn value as it stands in the emitted prompt (any case): as written, or as the
    prompt's tidy writes it: a filled "a {main} coat" reads "an olive coat" there
    (runtime.tidy_text). None when it's in the text neither way."""
    low = text.lower()
    return next((v for v in (value, tidy_text([value])) if v.lower() in low), None)


# --------------------------------------------------------------------------- the store and the model

def store_for(profile_id: Optional[str]) -> ProgramStore:
    import app_dirs
    from core.profile_context import get_current_profile
    return ProgramStore(app_dirs.get_profile_dir(profile_id or get_current_profile()) / "prompt_programs")


async def ask_model(messages: List[Dict[str, Any]], project_id: Optional[int], max_tokens: int = 1500) -> str:
    """One plain completion from the chat model Fluent reads prompts with."""
    from llm import llm_complete_text
    from llm_correlation import llm_correlation_context
    from llm_resolver import get_effective_llm_config

    cfg = await get_effective_llm_config("tool_assistant", project_id)
    with llm_correlation_context("prompt-program"):
        # Nothing Fluent asks needs reasoning: ask for none, and never retry with room for it.
        return await llm_complete_text(config=cfg, messages=messages, max_tokens=max_tokens, temperature=0.3,
                                       enable_thinking=False, retry_reasoning=False)


# Whether an endpoint's model makes tool calls, learned on first contact: (api base, model) →
# "tools" or "text". The option writer offers its tool only to endpoints that take one.
PROTOCOL: Dict[Tuple[str, str], str] = {}


def endpoint_id(cfg: Any) -> Tuple[str, str]:
    return (str(cfg.get_api_base() or ""), str(cfg.get_model() or ""))


async def model_endpoint(project_id: Optional[int]) -> Tuple[Any, str]:
    """The chat model's LLM config and the protocol it speaks ("tools", or "text")."""
    from llm_resolver import get_effective_llm_config
    cfg = await get_effective_llm_config("tool_assistant", project_id)
    return cfg, PROTOCOL.get(endpoint_id(cfg), "tools")


async def model_fingerprint(project_id: Optional[int]) -> Optional[str]:
    """The chat model (never its credentials): part of a program's key."""
    try:
        cfg, _ = await model_endpoint(project_id)
        return cfg.get_model() if cfg is not None else None
    except Exception:  # no chat model configured: cached programs can still be looked up
        return None


def no_tools_error(e: Exception) -> bool:
    """A request rejected because the endpoint doesn't take tools (vLLM without a tool parser:
    400 '"auto" tool choice requires --enable-auto-tool-choice'). The provider's own message
    rides on the exception (LLMProviderHTTPError.upstream_message), not in its summary."""
    status = getattr(e, "upstream_status", None)
    msg = f"{e} {getattr(e, 'upstream_message', '') or ''}".lower()
    rejected = status in (400, 404, 422, 501) or any(x in msg for x in ("400", "bad request", "unsupported"))
    return rejected and any(x in msg for x in ("tool", "function call", "function_call"))


# --------------------------------------------------------------------------- after a prepare

def on_prepared(entry: Dict[str, Any], *, project_id: Optional[int], profile_id: Optional[str],
                retry: bool = False) -> None:
    """Called once a program is stored: start writing its pools in the background.
    Never blocks, never fails the prepare."""
    try:
        from prompt_programs.events import prompt_changed
        from prompt_programs.fluent import start_pools
        prompt_changed(entry.get("key"), profile_id)
        start_pools(entry, profile_id=profile_id, project_id=project_id, retry=retry)
    except Exception as e:
        log.warning(f"[prompt-program] starting the pools failed for {entry.get('key')}: {e}")


# --------------------------------------------------------------------------- one generation's draw

def draw_seed(seed: Any = None) -> int:
    """The seed for a run's draws. It is its own seed, never the image's: the same
    image seed with new draws, or the same draws with a new image seed, are both
    useful. Missing or negative means fresh draws."""
    try:
        s = int(seed)
    except (TypeError, ValueError):
        s = -1
    return s % (2**31) if s >= 0 else random.randrange(0, 2**31)


def realize(entry: Dict[str, Any], *, seed: int, pins: Optional[Dict[str, Any]] = None,
            fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None,
            profile_id: Optional[str] = None, project_id: Optional[int] = None,
            revision: Optional[Dict[str, Any]] = None, runtime: Any = None, unmask: bool = True,
            chosen: Optional[Dict[str, Any]] = None) -> RunResult:
    """One generation's prompt from a prepared entry (slots.prepare), each slot drawn from its
    pool of variants (prompt_programs.fluent). `chosen`: each slot's Choice (choices.expand);
    `pins` and `edits`: the user lists' (and the judge's removals). Pass a recorded `revision` to
    replay its texts, or a `runtime` to draw with a given Variants (a batch, evaluations,
    tests). unmask=False leaves [exact text] as its [EXACT_n] tokens, for steps a model reads (the
    judge); put it back with unmask_exact(prompt, entry["exact"]). The result's `spans` say where
    each drawn value stands."""
    from prompt_programs.fill import fill
    from prompt_programs.fluent import runtime_for
    clean_pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    clean_edits = {str(k): v for k, v in (edits or {}).items() if isinstance(v, dict)}
    rt = runtime or runtime_for(entry, chosen=chosen, profile_id=profile_id, project_id=project_id, revision=revision)
    held = {**getattr(rt, "fixed", {}), **(fixed or {})}
    result = fill(entry, seed, clean_pins, held or None, clean_edits or None, options=rt)
    if unmask and entry.get("exact"):  # the user's [exact text], straight to the image model
        result.prompt = unmask_exact(result.prompt, entry["exact"])
    return result


def spans_of(result: Any) -> List[Tuple[int, int, str]]:
    """Where each drawn value stands in the result's prompt."""
    return list(getattr(result, "spans", None) or [])


__all__ = ["DrawAborted", "MAX_PROMPT_CHARS", "ModelRefused", "PROTOCOL", "ProgramError", "PromptTooLong", "ask_model",
           "draw_seed", "emitted_as", "endpoint_id", "expand_named_lists", "mask_exact", "model_endpoint",
           "model_failure", "model_fingerprint", "no_tools_error", "on_prepared", "realize", "realized_text",
           "spans_of", "store_for", "unmask_exact"]

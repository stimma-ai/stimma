"""
Unified LLM abstraction layer.

Single entry point for all LLM calls. Normalizes responses from any
OpenAI-compatible provider (vLLM, Together, DashScope, OpenRouter, OpenAI, etc.)
into a consistent LLMResponse shape.

Usage:
    from llm import llm_completion, llm_complete_text, llm_complete_vision, LLMResponse

    # Full response (agent, tools, thinking)
    resp = await llm_completion(config, messages=messages, tools=tools)
    resp.content      # clean text, thinking stripped
    resp.thinking     # reasoning/thinking if present
    resp.tool_calls   # normalized tool calls
    resp.finish_reason

    # Simple text (prompt enhancement, captioning, etc.)
    text = await llm_complete_text(config, messages=messages, max_tokens=500)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from config import LLMConfig
from core.logging import get_logger
from llm_http import (
    acompletion as _raw_acompletion,
    QuotaExceededError,
    ContentFilteredError,
    is_auto_tool_choice_unsupported_error,
)

log = get_logger(__name__)

# Re-export for callers that need these
__all__ = [
    "LLMResponse",
    "ToolCall",
    "FinishReason",
    "Usage",
    "QuotaExceededError",
    "ContentFilteredError",
    "is_auto_tool_choice_unsupported_error",
    "llm_completion",
    "llm_complete_text",
    "llm_complete_vision",
    "llm_complete_batch",
]


# ──────────────────────────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────────────────────────

class FinishReason(str, Enum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string

    def parsed_arguments(self) -> Any:
        return json.loads(self.arguments)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class Quota:
    """Stimma Cloud quota usage, piggybacked on LLM responses."""
    session_percent: Optional[float] = None
    weekly_percent: Optional[float] = None


@dataclass
class LLMResponse:
    """Normalized response from any OpenAI-compatible endpoint."""
    content: str = ""
    thinking: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: FinishReason = FinishReason.STOP
    usage: Usage = field(default_factory=Usage)
    quota: Optional[Quota] = None
    model: str = ""
    elapsed_seconds: float = 0.0
    tokens_per_second: float = 0.0
    _raw: object = field(default=None, repr=False)


# ──────────────────────────────────────────────────────────────────────
# Normalization
# ──────────────────────────────────────────────────────────────────────

_THINKING_TAGS = ['think', 'thinking', 'thought', 'analysis', 'reasoning']

_SPECIAL_TOKENS_RE = re.compile(
    r'<\|(?:begin_of_box|end_of_box|user|assistant|system|endoftext|call|response|im_start|im_end|im_sep)\|>',
    re.IGNORECASE,
)


def strip_thinking_tags(text: str) -> str:
    """Strip thinking tags and special tokens from content."""
    if not text:
        return text
    text = _SPECIAL_TOKENS_RE.sub('', text)
    for tag in _THINKING_TAGS:
        text = re.sub(rf'<{tag}>.*?</{tag}>', '', text, flags=re.IGNORECASE | re.DOTALL)
        # Handle malformed/nested tags
        lower = text.lower()
        first_open = lower.find(f'<{tag}>')
        last_close = lower.rfind(f'</{tag}>')
        if first_open != -1 and last_close > first_open:
            text = text[:first_open] + text[last_close + len(f'</{tag}>'):]
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    return text.strip()


def _extract_thinking_from_content(text: str) -> Optional[str]:
    """Extract thinking content from tags if present."""
    if not text:
        return None
    for tag in _THINKING_TAGS:
        m = re.search(rf'<{tag}>(.*?)</{tag}>', text, flags=re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _extract_reasoning_field(message) -> Optional[str]:
    """Extract reasoning from provider-specific response fields."""
    for attr in ('reasoning_content', 'reasoning', 'thinking'):
        val = getattr(message, attr, None)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _normalize_finish_reason(raw: str | None) -> FinishReason:
    if not raw:
        return FinishReason.UNKNOWN
    mapping = {
        "stop": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "max_tokens": FinishReason.LENGTH,
        "tool_calls": FinishReason.TOOL_CALLS,
        "function_call": FinishReason.TOOL_CALLS,
        "content_filter": FinishReason.CONTENT_FILTER,
    }
    return mapping.get(raw.lower(), FinishReason.UNKNOWN)


def _normalize_response(raw_response) -> LLMResponse:
    """Normalize an _Obj response from acompletion into LLMResponse.

    Handles all provider quirks:
    - reasoning_content / reasoning / thinking fields
    - Thinking tags in content
    - Minimax duplicate content/reasoning
    - Tool calls normalization
    - Usage with reasoning_tokens
    """
    choice = raw_response.choices[0]
    message = choice.message

    # --- Content & thinking ---
    raw_content = message.content or ""
    thinking = _extract_reasoning_field(message) or _extract_thinking_from_content(raw_content)
    content = strip_thinking_tags(raw_content)

    # Some providers put everything in 'reasoning' with <think> tags wrapping
    # thinking and actual content after. Only use reasoning as content if it has tags.
    if not raw_content and thinking and '<think>' in thinking.lower():
        content = strip_thinking_tags(thinking)

    # Minimax duplicates thinking into both content and reasoning fields.
    # If content matches reasoning, it's thinking — not a real response.
    if content and thinking and content.strip() == thinking.strip():
        content = ""

    # Fallback: if content is empty but we have thinking, try to extract
    # from the reasoning field (broken provider behavior)
    if not content and thinking:
        extracted = strip_thinking_tags(thinking)
        if extracted and extracted != thinking:
            content = extracted

    # --- Tool calls ---
    tool_calls = []
    raw_tool_calls = getattr(message, 'tool_calls', None)
    if raw_tool_calls:
        for tc in raw_tool_calls:
            fn = getattr(tc, 'function', None)
            if fn:
                tool_calls.append(ToolCall(
                    id=getattr(tc, 'id', ''),
                    name=getattr(fn, 'name', ''),
                    arguments=getattr(fn, 'arguments', '{}'),
                ))

    # --- Usage ---
    raw_usage = getattr(raw_response, 'usage', None)
    usage = Usage()
    if raw_usage:
        usage.prompt_tokens = getattr(raw_usage, 'prompt_tokens', 0) or 0
        usage.completion_tokens = getattr(raw_usage, 'completion_tokens', 0) or 0
        usage.total_tokens = getattr(raw_usage, 'total_tokens', 0) or 0
        details = getattr(raw_usage, 'completion_tokens_details', None)
        if details:
            usage.reasoning_tokens = getattr(details, 'reasoning_tokens', 0) or 0
        # Prompt caching fields (Anthropic via Stimma Cloud proxy, or OpenAI)
        usage.cache_creation_input_tokens = getattr(raw_usage, 'cache_creation_input_tokens', 0) or 0
        usage.cache_read_input_tokens = getattr(raw_usage, 'cache_read_input_tokens', 0) or 0

    # Extract Stimma Cloud quota if present (injected by llm_http from response headers)
    quota = None
    raw_quota = getattr(raw_response, '_stimma_quota', None)
    if raw_quota:
        quota = Quota(
            session_percent=getattr(raw_quota, 'session_percent', None),
            weekly_percent=getattr(raw_quota, 'weekly_percent', None),
        )

    return LLMResponse(
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
        finish_reason=_normalize_finish_reason(getattr(choice, 'finish_reason', None)),
        usage=usage,
        quota=quota,
        model=getattr(raw_response, 'model', ''),
        _raw=raw_response,
    )


# ──────────────────────────────────────────────────────────────────────
# Local-endpoint extras (content policy, extra system prompt, reasoning method)
# ──────────────────────────────────────────────────────────────────────

# Stimma Cloud injects its own content policy server-side and resolves these
# extras itself; only self-hosted (BYOAI) endpoints get them applied here.
_CLOUD_HOSTS = ("stimma.ai",)


def _is_local_endpoint(api_base: Optional[str]) -> bool:
    if not api_base:
        return False
    return not any(h in api_base for h in _CLOUD_HOSTS)


def _reasoning_wire_params(method: Optional[str], enabled: bool) -> Dict[str, Any]:
    """Request params that toggle thinking for a given reasoning-control method."""
    if not method or method == "none":
        return {}
    if method == "reasoning_effort":
        # "none" is a real off on vLLM / LM Studio (not just dialed-down "low");
        # always-on reasoners ignore it without erroring.
        return {"reasoning_effort": "high" if enabled else "none"}
    if method == "openrouter":
        # OpenRouter's unified reasoning param has a real off-switch (unlike
        # reasoning_effort, whose floor is "low"). Use it so plain calls truly
        # skip reasoning instead of just dialing it down.
        return {"reasoning": {"effort": "high"}} if enabled else {"reasoning": {"enabled": False}}
    if method == "enable_thinking":
        return {"chat_template_kwargs": {"enable_thinking": enabled}}
    if method == "think":
        return {"think": enabled}
    if method == "reasoning_budget":
        return {"reasoning_budget": -1 if enabled else 0}
    return {}


def _merge_extra_body(base: Optional[Dict], override: Optional[Dict]) -> Optional[Dict]:
    """Shallow-merge, with one level of dict-merge for nested dicts (e.g.
    chat_template_kwargs). ``override`` wins on conflicts."""
    if not base and not override:
        return None
    result: Dict[str, Any] = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in (base or {}).items()
    }
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            merged = dict(result[k])
            merged.update(v)
            result[k] = merged
        else:
            result[k] = v
    return result or None


def _apply_endpoint_reasoning(
    config: LLMConfig, extra_body: Optional[Dict], thinking: Optional[Dict]
) -> Optional[Dict]:
    """Merge the endpoint's fixed extra_body with caller params, and translate the
    caller's thinking intent into this model's reasoning-control dialect.

    The agent expresses thinking on/off via ``chat_template_kwargs.enable_thinking``
    (from ``agent_llm_options``) or the Anthropic ``thinking`` param. When the
    endpoint has a detected/configured reasoning method, swap that generic signal
    for the method-specific param so the model actually honors it.
    """
    effective = _merge_extra_body(getattr(config, "extra_body", None), extra_body)

    method = getattr(config, "reasoning_method", None)
    if not method or method == "none":
        return effective

    # Derive intent: explicit Anthropic thinking, or the enable_thinking flag.
    intent: Optional[bool] = True if thinking else None
    ctk = (effective or {}).get("chat_template_kwargs")
    if isinstance(ctk, dict) and "enable_thinking" in ctk:
        intent = bool(ctk["enable_thinking"])
    if intent is None:
        return effective

    # Drop the generic enable_thinking flag in favor of the method-specific param.
    if method != "enable_thinking" and isinstance(effective, dict):
        ctk = effective.get("chat_template_kwargs")
        if isinstance(ctk, dict):
            ctk.pop("enable_thinking", None)
            if not ctk:
                effective.pop("chat_template_kwargs", None)

    return _merge_extra_body(effective, _reasoning_wire_params(method, intent))


async def _inject_local_system(
    config: LLMConfig, messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Fold Stimma's content policy (if enabled) and any extra system prompt
    into a single leading system message. Stable text at the front keeps prompt
    caching intact.

    These extras are merged into the conversation's existing system message
    rather than prepended as additional system messages: some chat templates
    (e.g. stricter Qwen builds) permit only one system message at index 0 and
    return 400 "System message must be at the beginning" on a second one. One
    merged system message is accepted everywhere."""
    extras: List[str] = []
    if getattr(config, "content_policy_enabled", True):
        try:
            from content_policy import get_content_policy
            policy = await get_content_policy()
            if policy:
                extras.append(policy)
        except Exception as e:
            log.warning(f"content policy injection skipped: {e}")
    extra_prompt = (getattr(config, "extra_system_prompt", "") or "").strip()
    if extra_prompt:
        extras.append(extra_prompt)
    if not extras:
        return messages

    merged_extra = "\n\n".join(extras)
    msgs = list(messages)
    # Merge into the leading system message if there is one; otherwise add a
    # single system message at the front.
    if msgs and msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
        head = dict(msgs[0])
        head["content"] = f"{merged_extra}\n\n{head['content']}"
        return [head] + msgs[1:]
    return [{"role": "system", "content": merged_extra}] + msgs


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

async def llm_completion(
    config: LLMConfig,
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict]] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    thinking: Optional[Dict] = None,
    extra_body: Optional[Dict] = None,
    cacheable: bool = False,
    session_id: Optional[str] = None,
    apply_endpoint_extras: bool = True,
) -> LLMResponse:
    """Make an LLM call and return a normalized response.

    This is the primary entry point for callers that need the full response
    (agent loop, tool calling, thinking extraction).

    Args:
        cacheable: Signal that this request is part of a multi-turn conversation
            with a stable message prefix. Enables prompt caching on supported
            providers (Anthropic explicit caching, OpenAI automatic prefix caching).
    """
    model = config.get_model()
    api_key = config.get_api_key()
    api_base = config.get_api_base()

    # Self-hosted endpoints: apply content policy, extra system prompt, fixed
    # extra_body, and reasoning-method translation. Cloud handles its own.
    if apply_endpoint_extras and _is_local_endpoint(api_base):
        extra_body = _apply_endpoint_reasoning(config, extra_body, thinking)
        messages = await _inject_local_system(config, messages)
        # Reasoning is controlled via extra_body for local endpoints; the
        # Anthropic-style `thinking` param is meaningless here and some gateways
        # (OpenRouter) 400 when it's sent alongside their reasoning param.
        thinking = None

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "api_key": api_key,
        "api_base": api_base,
        "cacheable": cacheable,
    }
    if session_id:
        kwargs["session_id"] = session_id
    if tools:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if temperature is not None:
        kwargs["temperature"] = temperature
    if thinking:
        kwargs["thinking"] = thinking
    if extra_body:
        kwargs["extra_body"] = extra_body

    start = time.time()
    raw = await _raw_acompletion(**kwargs)
    elapsed = time.time() - start

    resp = _normalize_response(raw)

    # Attach timing
    resp.elapsed_seconds = elapsed
    if resp.usage.completion_tokens and elapsed > 0:
        resp.tokens_per_second = resp.usage.completion_tokens / elapsed
    log.debug(
        f"LLM: {resp.model} {elapsed:.2f}s — "
        f"{resp.usage.prompt_tokens}in {resp.usage.completion_tokens}out ({resp.tokens_per_second:.0f} tok/s)"
    )

    return resp


async def llm_complete_text(
    config: LLMConfig,
    messages: List[Dict[str, Any]],
    *,
    max_tokens: int = 500,
    temperature: float = 0.3,
    enable_thinking: bool = False,
) -> str:
    """Make a completion call and return just the text content.

    Thinking is OFF by default (prompt enhancement, captioning, etc.); pass
    enable_thinking=True for callers that want the model to reason first — slower,
    but can improve quality on weaker models. Strips tags either way. Uses the
    shared agent_llm_options so the thinking dialect matches the agent loop.
    """
    from agent.v2.llm_options import agent_llm_options
    resp = await llm_completion(
        config, messages,
        max_tokens=max_tokens,
        temperature=temperature,
        **agent_llm_options(enable_thinking=enable_thinking),
    )
    if resp.content:
        return resp.content

    # Fallback: try to extract from thinking
    if resp.thinking:
        extracted = strip_thinking_tags(resp.thinking)
        if extracted and extracted != resp.thinking:
            return extracted

    budget_exhausted = resp.finish_reason == FinishReason.LENGTH and bool(resp.thinking)
    log.warning(
        "LLM: no text content in response",
        model=resp.model,
        finish_reason=str(resp.finish_reason),
        max_tokens=max_tokens,
        completion_tokens=resp.usage.completion_tokens,
        reasoning_chars=len(resp.thinking or ""),
        cause=(
            "reasoning consumed the entire token budget before any answer — this "
            "model reasons even when asked not to (reasoning can't be disabled on "
            "it); raise max_tokens or use a model whose reasoning is controllable"
            if budget_exhausted
            else "model returned neither content nor reasoning"
        ),
    )
    return ""


async def llm_complete_vision(
    config: LLMConfig,
    prompt: str,
    image_b64: str,
    *,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> tuple[Optional[str], Optional[str]]:
    """Make a vision completion call with an image.

    Returns (result, error) tuple.
    """
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        }
    ]
    try:
        text = await llm_complete_text(config, messages, max_tokens=max_tokens, temperature=temperature)
        return text, None
    except asyncio.TimeoutError:
        return None, "Request timeout"
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        log.error(f"LLM Vision: {error_msg}")
        return None, error_msg


async def llm_complete_batch(
    config: LLMConfig,
    prompts: List[str],
    *,
    max_tokens: int = 500,
    temperature: float = 0.3,
    max_concurrency: int = 50,
) -> List[tuple[Optional[str], Optional[str]]]:
    """Make multiple text completion calls in parallel.

    Returns list of (result, error) tuples in same order as input.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def complete_one(prompt: str) -> tuple[Optional[str], Optional[str]]:
        async with semaphore:
            try:
                messages = [{"role": "user", "content": prompt}]
                result = await llm_complete_text(
                    config, messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return result, None
            except asyncio.TimeoutError:
                return None, "Request timeout"
            except Exception as e:
                return None, f"{type(e).__name__}: {str(e)}"

    tasks = [complete_one(p) for p in prompts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [
        (None, f"{type(r).__name__}: {r}") if isinstance(r, Exception) else r
        for r in results
    ]

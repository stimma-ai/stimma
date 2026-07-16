"""
Low-level HTTP client for OpenAI-compatible chat completion endpoints.

Handles the raw HTTP POST to /chat/completions, auth headers, token refresh,
and error detection. All response normalization lives in llm.py.
"""
import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

from core.logging import get_logger
from llm_correlation import correlation_headers

log = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Debug dump (off by default). Set STIMMA_LLM_DUMP=1 to dump every
# outbound request + raw response body under
# `<cache_dir>/llm_dumps/<ts>_<rand>_<model>_<session>/{request,response}.json`.
# Useful for diagnosing provider-side tool-call parser failures where the
# smoking gun is what bytes we actually put on the wire.
# ──────────────────────────────────────────────────────────────────────

def _dump_enabled() -> bool:
    v = os.environ.get("STIMMA_LLM_DUMP", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _slug(s: str, limit: int = 60) -> str:
    s = s or "unknown"
    out = "".join(c if c.isalnum() or c in "-_." else "_" for c in s)
    return out[:limit]


def _dump_dir_for(model: str, session_id: Optional[str]) -> Optional[Path]:
    if not _dump_enabled():
        return None
    try:
        from app_dirs import get_cache_dir
        base = get_cache_dir() / "llm_dumps"
        ts = time.strftime("%Y%m%dT%H%M%S")
        name = f"{ts}_{uuid.uuid4().hex[:6]}_{_slug(model)}_{_slug(session_id or 'nosession', 40)}"
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception as e:
        log.warning(f"llm dump: failed to create dump dir: {e}")
        return None


def _dump_request(d: Path, url: str, body: dict, headers: dict,
                   cacheable: bool, session_id: Optional[str]):
    try:
        from cloud_runtime import redact_sensitive_headers
        safe_headers = redact_sensitive_headers(headers)
        payload = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": url,
            "headers": safe_headers,
            "cacheable": cacheable,
            "session_id": session_id,
            "body": body,
        }
        (d / "request.json").write_text(json.dumps(payload, indent=2, default=str))
        log.info(f"llm dump: wrote {d}")
    except Exception as e:
        log.warning(f"llm dump: request write failed: {e}")


def _dump_response(d: Path, resp: httpx.Response, label: str = "response"):
    try:
        raw_text = resp.text
    except Exception:
        raw_text = "<could not read body>"
    parsed = None
    try:
        parsed = resp.json()
    except Exception:
        pass
    try:
        payload = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "text": raw_text,
            "parsed": parsed,
        }
        (d / f"{label}.json").write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        log.warning(f"llm dump: response write failed: {e}")


class QuotaExceededError(Exception):
    """Raised when Stimma Cloud returns 429 with quota_exceeded error."""

    def __init__(
        self,
        message: str,
        session: dict | None = None,
        weekly: dict | None = None,
        upstream_message: str | None = None,
        upstream_metadata: object | None = None,
        upstream_status: int | None = None,
    ):
        super().__init__(message)
        self.session = session  # {"percentUsed": float, "resetsAt": str}
        self.weekly = weekly    # {"percentUsed": float, "resetsAt": str}
        # Raw upstream provider detail, surfaced behind a "Details" disclosure
        # in the chat UI. None on errors we ourselves synthesized.
        self.upstream_message = upstream_message
        self.upstream_metadata = upstream_metadata
        self.upstream_status = upstream_status


class ContentFilteredError(Exception):
    """Raised when the AI provider rejects a request due to content guidelines."""

    def __init__(
        self,
        message: str,
        upstream_message: str | None = None,
        upstream_metadata: object | None = None,
        upstream_status: int | None = None,
    ):
        super().__init__(message)
        self.upstream_message = upstream_message
        self.upstream_metadata = upstream_metadata
        self.upstream_status = upstream_status


class EntitlementError(Exception):
    """Raised when Stimma Cloud rejects an LLM request with type
    'insufficient_balance' (403) — the account has no spendable balance
    ('subscription_error' is the legacy pre-PAYG type, still recognized).

    Distinct from QuotaExceededError (abuse throttle) and from
    LLMUnavailableError/LLMInsufficientBalanceError in llm_resolver.py
    (raised before any request goes out, from locally cached balance state).
    This one is raised from the live response, so it also catches the case
    where the local balance cache is stale."""

    def __init__(self, message: str, upstream_status: int | None = None):
        super().__init__(message)
        self.upstream_status = upstream_status


class LLMConnectionError(Exception):
    """Raised when we can't reach the LLM endpoint at the transport level.

    Wraps httpx transport errors (ConnectError, ConnectTimeout, ReadTimeout, …)
    so the message names *what* we were trying to reach — "Stimma Cloud" or the
    user-configured local endpoint URL — instead of httpx's bare "All connection
    attempts failed", which gives no clue which machine is down.
    """

    def __init__(self, message: str, endpoint: str | None = None, is_cloud: bool = False):
        super().__init__(message)
        self.endpoint = endpoint
        self.is_cloud = is_cloud


def classify_provider_http_error(exc: Exception) -> tuple[str, str] | None:
    """Turn common BYO-provider failures into short, actionable UI copy."""
    if isinstance(exc, LLMConnectionError):
        if exc.is_cloud:
            return None
        return "provider_connection_failed", "Could not reach this service."
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        from privacy_lockdown import is_stimma_service_url
        if is_stimma_service_url(str(response.request.url)):
            return None
    except Exception:
        pass
    status = response.status_code
    try:
        detail = (response.text or "").lower()
    except Exception:
        detail = str(exc).lower()
    if status == 401:
        return "provider_invalid_key", "The provider rejected this API key."
    if status == 402 or (
        status == 403
        and any(term in detail for term in ("balance", "billing", "credit", "fund", "quota"))
    ):
        return "provider_insufficient_funds", "The provider declined this request for insufficient funds."
    if status == 404 and "model" in detail:
        return "provider_model_missing", "This model is no longer available from the provider."
    if status == 403:
        return "provider_access_denied", "The provider denied access to this model."
    if status == 429:
        return "provider_rate_limited", "The provider rate limit was reached."
    return None


def is_auto_tool_choice_unsupported_error(exc: Exception) -> bool:
    """Return True when provider rejects implicit/explicit auto tool choice."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False

    response = getattr(exc, "response", None)
    if response is None or response.status_code != 400:
        return False

    try:
        error_text = response.text or ""
    except Exception:
        return False

    normalized = error_text.lower()
    return (
        "\"auto\" tool choice" in normalized
        and "--enable-auto-tool-choice" in normalized
        and "--tool-call-parser" in normalized
    )


class _Obj:
    """Lightweight dict-to-attribute wrapper for API responses."""
    def __init__(self, data: dict):
        for k, v in data.items():
            if isinstance(v, dict):
                setattr(self, k, _Obj(v))
            elif isinstance(v, list):
                setattr(self, k, [_Obj(i) if isinstance(i, dict) else i for i in v])
            else:
                setattr(self, k, v)

    def __repr__(self):
        return f"_Obj({vars(self)})"


_RESPONSES_TOOL_CALL_PREFIX = "sr_"


def _encode_responses_tool_call_id(response_id: str, call_id: str) -> str:
    """Carry the Responses continuation id through Stimma's persisted tool id."""
    return f"{_RESPONSES_TOOL_CALL_PREFIX}{len(response_id)}_{response_id}{call_id}"


def _decode_responses_tool_call_id(value: str | None) -> tuple[str, str] | None:
    if not value or not value.startswith(_RESPONSES_TOOL_CALL_PREFIX):
        return None
    length_end = value.find("_", len(_RESPONSES_TOOL_CALL_PREFIX))
    if length_end < 0:
        return None
    try:
        response_length = int(value[len(_RESPONSES_TOOL_CALL_PREFIX):length_end])
    except ValueError:
        return None
    response_start = length_end + 1
    response_end = response_start + response_length
    if response_length <= 0 or response_end >= len(value):
        return None
    return value[response_start:response_end], value[response_end:]


def _provider_http_error(resp: httpx.Response, *, provider: str) -> httpx.HTTPStatusError:
    """Log supplier diagnostics, but keep URLs/models/body out of UI exceptions."""
    try:
        detail = resp.text
    except Exception:
        detail = "(could not read response body)"
    log.error(f"{provider} API error {resp.status_code}: {detail[:2000]}")
    return httpx.HTTPStatusError(
        f"The AI provider rejected the request (HTTP {resp.status_code}).",
        request=resp.request,
        response=resp,
    )


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _responses_input_content(content, *, assistant: bool = False):
    if isinstance(content, str):
        return content
    result = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image_url" and isinstance(block.get("image_url"), dict):
            result.append({"type": "input_image", "image_url": block["image_url"].get("url", "")})
        else:
            result.append({
                "type": "output_text" if assistant else "input_text",
                "text": block.get("text", ""),
            })
    return result


def _responses_continuation(messages: list[dict]) -> tuple[str, int] | None:
    response_id: str | None = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if (
            message.get("role") == "user"
            and message.get("name") != "_stimma_context"
        ):
            break
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            decoded = _decode_responses_tool_call_id(call.get("id"))
            if decoded:
                response_id = decoded[0]
                break
        if response_id:
            break
    if not response_id:
        return None

    # One Responses output can contain several parallel function calls. The
    # app persists them call/result/call/result and can interleave user-shaped
    # skill injections between results. Find the first call from the same
    # response across that whole persisted batch; stopping at an injected user
    # message drops earlier outstanding calls and makes Responses reject the
    # continuation as incomplete.
    matching_indexes = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and any(
            (decoded := _decode_responses_tool_call_id(call.get("id"))) is not None
            and decoded[0] == response_id
            for call in message.get("tool_calls") or []
        )
    ]
    return response_id, min(matching_indexes)


def _to_responses_request(model: str, messages: list[dict], kwargs: dict) -> dict:
    continuation = _responses_continuation(messages)
    source = messages[continuation[1]:] if continuation else messages
    if continuation:
        # Responses requires every outstanding function_call_output before
        # accepting new user content. Skill injections are represented as user
        # messages in history, so preserve them after the complete output set.
        source = (
            [message for message in source if message.get("role") == "tool"]
            + [message for message in source if message.get("role") != "tool"]
        )
    input_items: list[dict] = []
    for message in source:
        role = message.get("role")
        if role == "system":
            continue
        if role == "tool":
            decoded = _decode_responses_tool_call_id(message.get("tool_call_id"))
            input_items.append({
                "type": "function_call_output",
                "call_id": decoded[1] if decoded else message.get("tool_call_id", ""),
                "output": _responses_input_content(message.get("content")),
            })
            continue
        calls = message.get("tool_calls") or []
        if role == "assistant" and calls:
            if not continuation:
                text = _message_text(message.get("content"))
                if text:
                    input_items.append({"role": "assistant", "content": text})
                for call in calls:
                    decoded = _decode_responses_tool_call_id(call.get("id"))
                    fn = call.get("function") or {}
                    input_items.append({
                        "type": "function_call",
                        "call_id": decoded[1] if decoded else call.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    })
            continue
        input_items.append({
            "role": role,
            "content": _responses_input_content(message.get("content"), assistant=role == "assistant"),
        })

    body: dict = {"model": model, "input": input_items, "store": True}
    instructions = "\n\n".join(
        _message_text(message.get("content"))
        for message in messages
        if message.get("role") == "system" and _message_text(message.get("content"))
    )
    if instructions:
        body["instructions"] = instructions
    if continuation:
        body["previous_response_id"] = continuation[0]
    if kwargs.get("max_tokens") is not None:
        body["max_output_tokens"] = kwargs["max_tokens"]
    extra = dict(kwargs.get("extra_body") or {})
    effort = extra.pop("reasoning_effort", None)
    if effort is not None:
        body["reasoning"] = {"effort": effort}
    body.update(extra)
    if kwargs.get("tools"):
        body["tools"] = [
            {
                "type": "function",
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get("parameters", {"type": "object", "properties": {}}),
                "strict": False,
            }
            for tool in kwargs["tools"]
        ]
    if kwargs.get("tool_choice"):
        choice = kwargs["tool_choice"]
        body["tool_choice"] = (
            choice if isinstance(choice, str)
            else {"type": "function", "name": choice["function"]["name"]}
        )
    return body


def _responses_to_chat(data: dict, requested_model: str) -> _Obj:
    output = data.get("output") or []
    text = "".join(
        part.get("text", "")
        for item in output if item.get("type") == "message"
        for part in item.get("content") or [] if part.get("type") == "output_text"
    )
    calls = [item for item in output if item.get("type") == "function_call"]
    reasoning = "\n".join(
        part.get("text", "")
        for item in output if item.get("type") == "reasoning"
        for part in item.get("summary") or [] if part.get("text")
    )
    message: dict = {"role": "assistant", "content": text or None}
    if calls:
        message["tool_calls"] = [{
            "id": _encode_responses_tool_call_id(data.get("id", ""), call.get("call_id") or call.get("id", "")),
            "type": "function",
            "function": {"name": call.get("name", ""), "arguments": call.get("arguments", "{}")},
        } for call in calls]
    if reasoning:
        message["reasoning_content"] = reasoning
    usage = data.get("usage") or {}
    output_details = usage.get("output_tokens_details") or {}
    chat_usage = {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "completion_tokens_details": {"reasoning_tokens": output_details.get("reasoning_tokens", 0)},
        "prompt_tokens_details": {"cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)},
    }
    finish = "tool_calls" if calls else "stop"
    if data.get("status") == "incomplete" and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
        finish = "length"
    return _Obj({
        "id": data.get("id", ""), "model": requested_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": chat_usage,
    })


async def _acompletion_openai_responses(*, model, messages, api_key, api_base, **kwargs) -> _Obj:
    url = f"{api_base.rstrip('/')}/responses"
    body = _to_responses_request(model, messages, kwargs)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
    if resp.status_code >= 400:
        raise _provider_http_error(resp, provider="OpenAI")
    return _responses_to_chat(resp.json(), model)


def _anthropic_content_blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    result: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image_url" and isinstance(block.get("image_url"), dict):
            url = block["image_url"].get("url", "")
            if url.startswith("data:") and ";base64," in url:
                header, data = url.split(",", 1)
                result.append({"type": "image", "source": {
                    "type": "base64", "media_type": header[5:].split(";", 1)[0], "data": data,
                }})
            else:
                result.append({"type": "image", "source": {"type": "url", "url": url}})
        else:
            result.append({"type": "text", "text": block.get("text", "")})
    return result


def _to_anthropic_request(model: str, messages: list[dict], kwargs: dict) -> dict:
    system = []
    converted: list[dict] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system.extend(_anthropic_content_blocks(message.get("content")))
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.get("tool_call_id", ""),
                "content": _anthropic_content_blocks(message.get("content")),
            }
            if converted and converted[-1]["role"] == "user" and all(
                part.get("type") == "tool_result" for part in converted[-1]["content"]
            ):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            state = message.get("_stimma_provider_state")
            if isinstance(state, dict) and state.get("kind") == "anthropic_message" and isinstance(state.get("content"), list):
                content = state["content"]
            else:
                content = _anthropic_content_blocks(message.get("content"))
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    try:
                        call_input = json.loads(fn.get("arguments") or "{}")
                    except (TypeError, ValueError):
                        call_input = {"_malformed_arguments": str(fn.get("arguments"))[:2000]}
                    content.append({
                        "type": "tool_use", "id": call.get("id", ""),
                        "name": fn.get("name", ""), "input": call_input,
                    })
            converted.append({"role": "assistant", "content": content})
        else:
            converted.append({"role": "user", "content": _anthropic_content_blocks(message.get("content"))})

    body: dict = {"model": model, "messages": converted, "max_tokens": kwargs.get("max_tokens") or 4096}
    if system:
        body["system"] = system
    if kwargs.get("tools"):
        body["tools"] = [{
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "input_schema": tool["function"].get("parameters", {"type": "object", "properties": {}}),
        } for tool in kwargs["tools"]]
    extra = dict(kwargs.get("extra_body") or {})
    body.update(extra)
    thinking_config = body.get("thinking")
    if isinstance(thinking_config, dict) and thinking_config.get("type") == "enabled":
        budget = int(thinking_config.get("budget_tokens") or 0)
        if budget > 0:
            body["max_tokens"] = max(int(body.get("max_tokens") or 0), budget + 256)
    if kwargs.get("temperature") is not None and "thinking" not in body:
        body["temperature"] = kwargs["temperature"]
    return body


def _anthropic_to_chat(data: dict, requested_model: str) -> _Obj:
    blocks = data.get("content") or []
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    thinking = "\n".join(block.get("thinking", "") for block in blocks if block.get("type") == "thinking")
    calls = [block for block in blocks if block.get("type") == "tool_use"]
    message: dict = {
        "role": "assistant", "content": text or None,
        "_stimma_provider_state": {"kind": "anthropic_message", "content": blocks},
    }
    if thinking:
        message["reasoning_content"] = thinking
    if calls:
        message["tool_calls"] = [{
            "id": call.get("id", ""), "type": "function",
            "function": {"name": call.get("name", ""), "arguments": json.dumps(call.get("input") or {})},
        } for call in calls]
    usage = data.get("usage") or {}
    stop_reason = data.get("stop_reason")
    finish = {"tool_use": "tool_calls", "max_tokens": "length"}.get(stop_reason, "stop")
    return _Obj({
        "id": data.get("id", ""), "model": requested_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
    })


async def _acompletion_anthropic(*, model, messages, api_key, api_base, **kwargs) -> _Obj:
    url = f"{api_base.rstrip('/')}/messages"
    body = _to_anthropic_request(model, messages, kwargs)
    headers = {
        "Content-Type": "application/json", "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        resp = await client.post(url, json=body, headers=headers)
    if resp.status_code >= 400:
        raise _provider_http_error(resp, provider="Anthropic")
    return _anthropic_to_chat(resp.json(), model)


async def acompletion(*, model, messages, api_key=None, api_base=None,
                       thinking=None, cacheable=False, session_id=None,
                       provider_kind=None, **kwargs) -> _Obj:
    """Make a raw HTTP POST to an OpenAI-compatible /chat/completions endpoint.

    Returns an _Obj with the same attribute shape as the openai SDK response:
    response.choices[0].message.content, .tool_calls, response.usage, etc.

    Args:
        cacheable: Signal that this request is part of a multi-turn conversation
            whose message prefix is stable across calls. Downstream providers
            (Stimma Cloud -> Anthropic/OpenAI) use this to enable prompt caching.
        session_id: Stable identifier for the conversation. Forwarded to Stimma
            Cloud as X-Stimma-Session so the proxy can pin routing for prefix
            caching (e.g. Cloudflare Workers AI's x-session-affinity).
    """
    if provider_kind == "openai":
        return await _acompletion_openai_responses(
            model=model, messages=messages, api_key=api_key, api_base=api_base,
            thinking=thinking, cacheable=cacheable, session_id=session_id, **kwargs,
        )
    if provider_kind == "anthropic":
        return await _acompletion_anthropic(
            model=model, messages=messages, api_key=api_key, api_base=api_base,
            thinking=thinking, cacheable=cacheable, session_id=session_id, **kwargs,
        )

    body: dict = {
        "model": model,
        # Namespaced continuation state is for Stimma's adapters, never an
        # OpenAI-compatible provider wire field.
        "messages": [
            {key: value for key, value in message.items() if key != "_stimma_provider_state"}
            for message in messages
        ],
    }

    # Merge extra_body keys into the top-level body (OpenAI-compatible endpoints
    # accept them as top-level keys)
    extra_body = kwargs.pop("extra_body", None)
    if thinking:
        if extra_body is None:
            extra_body = {}
        extra_body["thinking"] = thinking
    if extra_body:
        body.update(extra_body)

    # Standard OpenAI params
    for key in ("temperature", "tools", "tool_choice",
                "response_format", "stop", "top_p", "n", "seed"):
        if key in kwargs:
            body[key] = kwargs.pop(key)

    # Output-token cap naming varies by provider: OpenAI's newer models
    # require max_completion_tokens, most others (vLLM, OpenRouter,
    # Fireworks) use max_tokens, and Anthropic's OpenAI-compat endpoint
    # REJECTS requests that set both. Pick one by host.
    if "max_tokens" in kwargs:
        val = kwargs.pop("max_tokens")
        if "api.openai.com" in (api_base or ""):
            body["max_completion_tokens"] = val
        else:
            body["max_tokens"] = val

    # Claude 5 models reject `temperature` outright on the Anthropic
    # OpenAI-compat endpoint ("deprecated for this model").
    if "api.anthropic.com" in (api_base or ""):
        body.pop("temperature", None)

    # Build URL — base_url is like "http://host/v1"
    if not api_base:
        raise ValueError("No LLM endpoint configured (api_base is empty)")
    url = f"{api_base.rstrip('/')}/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "dummy":
        headers["Authorization"] = f"Bearer {api_key}"
    if cacheable:
        headers["X-Stimma-Cacheable"] = "true"
    if session_id:
        headers["X-Stimma-Session"] = str(session_id)

    # Detect if this is a Stimma Cloud endpoint (for 401 retry logic)
    from privacy_lockdown import is_stimma_service_url
    is_stimma_cloud = is_stimma_service_url(api_base)
    if is_stimma_cloud:
        from privacy_lockdown import raise_if_enabled
        raise_if_enabled("Stimma Cloud")

    # Mechanical correlation IDs (chat/run/agent-context) for Stimma Cloud's
    # server-side request grouping, plus the Stimma User-Agent (the single
    # sanctioned install-id egress). Cloud only — never sent to BYOAI/custom
    # endpoints.
    if is_stimma_cloud:
        headers.update(correlation_headers())
        try:
            from cloud_runtime import with_cloud_access_headers
            headers = with_cloud_access_headers(headers)
        except Exception:
            pass
        try:
            from user_agent import user_agent
            headers["User-Agent"] = user_agent()
        except Exception:
            pass

    dump_dir = _dump_dir_for(model, session_id)
    if dump_dir is not None:
        _dump_request(dump_dir, url, body, headers, cacheable, session_id)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = await client.post(url, json=body, headers=headers)
            if dump_dir is not None:
                _dump_response(dump_dir, resp, label="response")

            # On 401 from Stimma Cloud, force-refresh Firebase token and retry once
            if resp.status_code == 401 and is_stimma_cloud:
                log.warning("got 401 from stimma cloud, attempting token refresh and retry")
                try:
                    from firebase_auth import force_refresh_id_token
                    fresh_token = await force_refresh_id_token()
                    if fresh_token:
                        headers["Authorization"] = f"Bearer {fresh_token}"
                        resp = await client.post(url, json=body, headers=headers)
                        if dump_dir is not None:
                            _dump_response(dump_dir, resp, label="response_retry")
                        if resp.status_code != 401:
                            log.info("retry after token refresh succeeded")
                        else:
                            log.error("retry after token refresh still got 401")
                except Exception as e:
                    log.error(f"token refresh retry failed: {e}")

            if resp.status_code >= 400:
                try:
                    error_body = resp.text
                except Exception:
                    error_body = "(could not read response body)"
                log.error(f"LLM API error {resp.status_code}: {error_body[:2000]}")

                # Extract the upstream provider's message for whichever error
                # path we end up taking. Shapes we handle:
                #   {"error": {"message": "...", "type": "..."}}  — OpenAI / Stimma Cloud
                #   {"error": "..."}                              — LM Studio, llama.cpp
                #   {"detail": "..."}                             — FastAPI-style
                #   plain text                                    — anything else
                upstream_msg = ""
                err_data: dict = {}
                err_type = ""
                try:
                    err_json = resp.json()
                except ValueError:
                    err_json = None
                if isinstance(err_json, dict):
                    raw_err = err_json.get("error")
                    if isinstance(raw_err, dict):
                        err_data = raw_err
                        err_type = err_data.get("type", "") or ""
                        upstream_msg = err_data.get("message") or err_data.get("detail") or ""
                    elif isinstance(raw_err, str):
                        upstream_msg = raw_err
                    if not upstream_msg:
                        detail = err_json.get("detail") or err_json.get("message")
                        if isinstance(detail, str):
                            upstream_msg = detail
                if not upstream_msg:
                    upstream_msg = (error_body or "").strip()

                # Stimma Cloud passes upstream provider detail through alongside
                # the friendly summary so we can surface it in the disclosure UI.
                upstream_msg_passthrough = err_data.get("upstream_message") if isinstance(err_data, dict) else None
                upstream_meta_passthrough = err_data.get("upstream_metadata") if isinstance(err_data, dict) else None
                upstream_status_passthrough = err_data.get("upstream_status") if isinstance(err_data, dict) else None

                # Stimma Cloud structured errors (type-tagged).
                if resp.status_code == 429 and err_type == "quota_exceeded":
                    raise QuotaExceededError(
                        message=err_data.get("message", "Usage quota exceeded"),
                        session=err_data.get("session"),
                        weekly=err_data.get("weekly"),
                        upstream_message=upstream_msg_passthrough,
                        upstream_metadata=upstream_meta_passthrough,
                        upstream_status=upstream_status_passthrough,
                    )

                if err_type == "content_filtered":
                    raise ContentFilteredError(
                        err_data.get("message", "Your message was flagged by content guidelines. Try rephrasing your request."),
                        upstream_message=upstream_msg_passthrough,
                        upstream_metadata=upstream_meta_passthrough,
                        upstream_status=upstream_status_passthrough,
                    )

                if err_type in ("insufficient_balance", "subscription_error"):
                    raise EntitlementError(
                        err_data.get("message", "Your Stimma account has no credits."),
                        upstream_status=resp.status_code,
                    )

                # Raw supplier diagnostics stay in logs/response for internal
                # classification, never in the customer-visible exception.
                raise _provider_http_error(resp, provider="LLM")

            resp.raise_for_status()
            data = resp.json()
            msg = data.get('choices', [{}])[0].get('message', {})
            reasoning_fields = [k for k in ('reasoning_content', 'reasoning', 'thinking') if k in msg and msg[k]]
            if reasoning_fields:
                log.debug(f"LLM response has reasoning fields: {reasoning_fields}")

            # Extract Stimma Cloud quota headers if present and inject into response
            # so they flow through the normal usage pipeline to the frontend.
            quota_session = resp.headers.get("X-Stimma-Quota-Session")
            quota_weekly = resp.headers.get("X-Stimma-Quota-Weekly")
            if quota_session or quota_weekly:
                data["_stimma_quota"] = {}
                if quota_session:
                    data["_stimma_quota"]["session_percent"] = float(quota_session)
                if quota_weekly:
                    data["_stimma_quota"]["weekly_percent"] = float(quota_weekly)

            return _Obj(data)
    except httpx.RequestError as e:
        # Transport-level failure: we never got an HTTP response back (DNS,
        # refused connection, TLS, connect/read timeout, …). httpx's own
        # message ("All connection attempts failed") names neither the host
        # nor whether it was Stimma Cloud or a local endpoint, so wrap it with
        # the target so the chat "Details" disclosure tells the user exactly
        # what was unreachable. (HTTPStatusError is not a RequestError, so the
        # 4xx/5xx paths above pass through untouched.)
        target = "Stimma Cloud" if is_stimma_cloud else f"the LLM endpoint at {api_base}"
        reason = str(e).strip() or type(e).__name__
        log.error(f"LLM connection error reaching {url}: {type(e).__name__}: {reason}")
        raise LLMConnectionError(
            f"Couldn't connect to {target}: {reason}",
            endpoint=api_base,
            is_cloud=bool(is_stimma_cloud),
        ) from e

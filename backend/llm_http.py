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


async def acompletion(*, model, messages, api_key=None, api_base=None,
                       thinking=None, cacheable=False, session_id=None,
                       **kwargs) -> _Obj:
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
    body: dict = {"model": model, "messages": messages}

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

    # Send both max_tokens and max_completion_tokens for maximum compatibility.
    # OpenAI endpoints use max_completion_tokens, vLLM accepts both,
    # OpenRouter uses max_tokens.
    if "max_tokens" in kwargs:
        val = kwargs.pop("max_tokens")
        body["max_tokens"] = val
        body["max_completion_tokens"] = val

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

                # Generic upstream failure — raise HTTPStatusError ourselves so
                # the exception text carries the provider's actual message,
                # not just httpx's "Client error 'NNN ...' for url ..." boilerplate.
                # Keeping the class as HTTPStatusError preserves downstream
                # isinstance checks (e.g. is_auto_tool_choice_unsupported_error).
                trimmed = upstream_msg.strip()
                if len(trimmed) > 1000:
                    trimmed = trimmed[:1000] + "…"
                message = f"HTTP {resp.status_code} from {url}: {trimmed}" if trimmed else f"HTTP {resp.status_code} from {url}"
                raise httpx.HTTPStatusError(message, request=resp.request, response=resp)

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

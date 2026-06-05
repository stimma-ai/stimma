#!/usr/bin/env python3
"""
LLM Abstraction Layer — Validation Script

Standalone script that tests the proposed LLMResponse normalization logic
against real OpenAI-compatible endpoints. Run scenarios (text, thinking,
tools, vision) and compare raw vs normalized output.

Usage:
    uv run python tools/validate_llm.py --endpoint https://openrouter.ai/api/v1 --model qwen/qwen3-235b-a22b --api-key sk-...
    uv run python tools/validate_llm.py --all
    uv run python tools/validate_llm.py --endpoint http://llm-host:8000/v1 --model gpt-oss-120b --scenario text
    uv run python tools/validate_llm.py --endpoint https://api.together.xyz/v1 --model Qwen/Qwen3.5-397B-A53B --api-key ... --scenario thinking
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx


# ──────────────────────────────────────────────────────────────────────
# Proposed LLMResponse types — these will become llm.py
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


@dataclass
class LLMResponse:
    """Normalized response from any OpenAI-compatible endpoint."""
    content: str = ""
    thinking: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: FinishReason = FinishReason.STOP
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: dict = field(default_factory=dict, repr=False)


# ──────────────────────────────────────────────────────────────────────
# Normalization logic — the core of what we're validating
# ──────────────────────────────────────────────────────────────────────

# Thinking tag patterns (same as llm.py)
import re

_THINKING_TAGS = ['think', 'thinking', 'thought', 'analysis', 'reasoning']

_SPECIAL_TOKENS = [
    r'<\|begin_of_box\|>', r'<\|end_of_box\|>',
    r'<\|user\|>', r'<\|assistant\|>', r'<\|system\|>',
    r'<\|endoftext\|>', r'<\|call\|>', r'<\|response\|>',
    r'<\|im_start\|>', r'<\|im_end\|>', r'<\|im_sep\|>',
]


def _strip_thinking_tags(text: str) -> str:
    """Strip thinking tags and special tokens from content."""
    if not text:
        return text
    for pat in _SPECIAL_TOKENS:
        text = re.sub(pat, '', text, flags=re.IGNORECASE)
    for tag in _THINKING_TAGS:
        text = re.sub(rf'<{tag}>.*?</{tag}>', '', text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r'\n\s*\n\s*\n+', '\n\n', text).strip()


def _extract_thinking_from_content(text: str) -> Optional[str]:
    """Extract thinking content from tags if present."""
    if not text:
        return None
    for tag in _THINKING_TAGS:
        m = re.search(rf'<{tag}>(.*?)</{tag}>', text, flags=re.IGNORECASE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
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


def normalize_response(data: dict) -> LLMResponse:
    """Normalize a raw OpenAI-compatible chat completion response.

    Handles provider-specific quirks:
    - reasoning_content / reasoning / thinking fields → LLMResponse.thinking
    - Thinking tags in content → extracted to .thinking, stripped from .content
    - Tool calls normalization
    - Usage with reasoning_tokens
    """
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}

    # --- Content & thinking ---
    raw_content = msg.get("content") or ""

    # Check structured reasoning fields (vLLM, DeepSeek, Together, etc.)
    thinking = None
    for attr in ("reasoning_content", "reasoning", "thinking"):
        val = msg.get(attr)
        if val and isinstance(val, str) and val.strip():
            thinking = val.strip()
            break

    # Check for thinking tags embedded in content
    if not thinking:
        thinking = _extract_thinking_from_content(raw_content)

    # Strip thinking tags from content to get clean answer
    content = _strip_thinking_tags(raw_content)

    # Fallback: if content is empty but we have thinking, the model may have
    # put everything in the reasoning field (broken provider behavior)
    if not content and thinking:
        # Try stripping thinking tags from the reasoning itself
        extracted = _strip_thinking_tags(thinking)
        if extracted and extracted != thinking:
            content = extracted

    # --- Tool calls ---
    tool_calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        tool_calls.append(ToolCall(
            id=tc.get("id", ""),
            name=fn.get("name", ""),
            arguments=fn.get("arguments", "{}"),
        ))

    # --- Usage ---
    raw_usage = data.get("usage") or {}
    usage = Usage(
        prompt_tokens=raw_usage.get("prompt_tokens", 0),
        completion_tokens=raw_usage.get("completion_tokens", 0),
        total_tokens=raw_usage.get("total_tokens", 0),
        reasoning_tokens=(
            raw_usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
            if raw_usage.get("completion_tokens_details") else 0
        ),
    )

    return LLMResponse(
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
        finish_reason=_normalize_finish_reason(choice.get("finish_reason")),
        usage=usage,
        model=data.get("model", ""),
        raw=data,
    )


# ──────────────────────────────────────────────────────────────────────
# HTTP client for hitting endpoints
# ──────────────────────────────────────────────────────────────────────

async def call_endpoint(
    url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    thinking: dict | None = None,
    extra_body: dict | None = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> dict:
    """Make a raw chat completion call, return the response dict."""
    # Provider-specific body adjustments:
    # - OpenAI rejects max_tokens + max_completion_tokens together
    # - OpenAI rejects chat_template_kwargs (vLLM-only param)
    # - OpenRouter silently ignores chat_template_kwargs but it's harmless
    is_openai_native = "api.openai.com" in url
    is_deepseek = "deepseek.com" in url
    is_gemini = "googleapis.com" in url
    is_strict_provider = is_openai_native or is_deepseek or is_gemini

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if is_openai_native or is_deepseek:
        body["max_completion_tokens"] = max_tokens
    elif is_gemini:
        body["max_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens
        body["max_completion_tokens"] = max_tokens
    if tools:
        body["tools"] = tools
    if thinking:
        body["thinking"] = thinking
    if extra_body:
        # Strip vLLM-specific params for providers that reject unknown fields
        if is_strict_provider:
            extra_body = {k: v for k, v in extra_body.items() if k != "chat_template_kwargs"}
        body.update(extra_body)

    endpoint = f"{url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "dummy":
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        resp = await client.post(endpoint, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ──────────────────────────────────────────────────────────────────────
# Test scenarios
# ──────────────────────────────────────────────────────────────────────

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["location"],
        },
    },
}


async def scenario_text(url: str, model: str, api_key: str | None) -> tuple[dict, list[str]]:
    """Plain text completion — no thinking, no tools."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Reply concisely."},
        {"role": "user", "content": "What is the capital of France? Reply in one sentence."},
    ]
    # Disable thinking for providers that support it
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    raw = await call_endpoint(url, model, messages, api_key, extra_body=extra)
    resp = normalize_response(raw)

    issues = []
    if not resp.content:
        issues.append("content is empty")
    if resp.thinking:
        issues.append(f"unexpected thinking field ({len(resp.thinking)} chars) — enable_thinking=False was ignored")
    if "paris" not in resp.content.lower() and resp.content:
        issues.append(f"answer doesn't mention Paris: {resp.content[:100]}")
    if resp.finish_reason == FinishReason.UNKNOWN:
        issues.append(f"unknown finish_reason (raw: {raw.get('choices', [{}])[0].get('finish_reason')})")
    return raw, issues


async def scenario_thinking(url: str, model: str, api_key: str | None) -> tuple[dict, list[str]]:
    """Thinking/reasoning enabled — verify we extract thinking separately."""
    messages = [
        {"role": "user", "content": "Think step by step: what is 17 * 23?"},
    ]
    is_openai_native = "api.openai.com" in url
    is_deepseek = "deepseek.com" in (url or "")
    is_gemini = "googleapis.com" in (url or "")

    if is_openai_native or is_deepseek or is_gemini:
        # These providers handle thinking internally — just send a plain request.
        # DeepSeek returns reasoning_content natively for deepseek-reasoner.
        # Gemini returns thinking in its own format.
        # OpenAI thinking models reason internally (not always exposed).
        raw = await call_endpoint(url, model, messages, api_key, max_tokens=16384)
    else:
        # vLLM/Together/OpenRouter: use thinking param + chat_template_kwargs
        thinking = {"type": "enabled", "budget_tokens": 2048}
        extra = {"chat_template_kwargs": {"enable_thinking": True}}
        try:
            raw = await call_endpoint(url, model, messages, api_key, thinking=thinking, extra_body=extra, max_tokens=4096)
        except httpx.HTTPStatusError:
            # Some providers don't support the thinking parameter — try without it
            raw = await call_endpoint(url, model, messages, api_key, extra_body=extra, max_tokens=4096)

    resp = normalize_response(raw)
    issues = []
    if not resp.content:
        issues.append("content is empty (all in thinking?)")
    if not resp.thinking:
        issues.append("no thinking extracted — model may not support reasoning, or tags not detected")
    if resp.content and "391" not in resp.content:
        issues.append(f"answer doesn't contain 391: {resp.content[:100]}")
    return raw, issues


async def scenario_tools(url: str, model: str, api_key: str | None) -> tuple[dict, list[str]]:
    """Tool calling — verify tool_calls are normalized."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the provided tools when appropriate."},
        {"role": "user", "content": "What's the weather in Tokyo?"},
    ]
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    try:
        raw = await call_endpoint(url, model, messages, api_key, tools=[WEATHER_TOOL], extra_body=extra)
    except httpx.HTTPStatusError as e:
        # Some providers (vLLM without --enable-auto-tool-choice) reject tool_choice=auto
        return {"error": str(e), "status": e.response.status_code, "body": e.response.text[:500]}, [
            f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        ]

    resp = normalize_response(raw)
    issues = []
    if not resp.tool_calls:
        if resp.content:
            issues.append(f"no tool_calls — model responded with text instead: {resp.content[:100]}")
        else:
            issues.append("no tool_calls and no content")
    else:
        tc = resp.tool_calls[0]
        if tc.name != "get_weather":
            issues.append(f"unexpected tool name: {tc.name}")
        try:
            args = tc.parsed_arguments()
            if "tokyo" not in json.dumps(args).lower():
                issues.append(f"tool args don't mention tokyo: {args}")
        except json.JSONDecodeError as e:
            issues.append(f"tool arguments not valid JSON: {e}")
        if resp.finish_reason != FinishReason.TOOL_CALLS:
            issues.append(f"finish_reason is {resp.finish_reason.value}, expected tool_calls")
    return raw, issues


async def scenario_vision(
    url: str, model: str, api_key: str | None, image_path: str | None
) -> tuple[dict, list[str]]:
    """Vision — send an image, verify we get a description back."""
    if image_path:
        img_data = Path(image_path).read_bytes()
        b64 = base64.b64encode(img_data).decode()
        mime = "image/png" if image_path.endswith(".png") else "image/jpeg"
    else:
        # Generate a tiny 8x8 red square PNG as a test image
        b64 = _make_test_image_b64()
        mime = "image/png"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image in one sentence."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }
    ]
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    try:
        raw = await call_endpoint(url, model, messages, api_key, extra_body=extra)
    except httpx.HTTPStatusError as e:
        return {"error": str(e), "status": e.response.status_code, "body": e.response.text[:500]}, [
            f"HTTP {e.response.status_code} — model may not support vision: {e.response.text[:200]}"
        ]

    resp = normalize_response(raw)
    issues = []
    if not resp.content:
        issues.append("content is empty")
    elif len(resp.content) < 10:
        issues.append(f"suspiciously short response: {resp.content}")
    return raw, issues


def _make_test_image_b64() -> str:
    """Create a minimal valid PNG (8x8 red square) without PIL."""
    import struct
    import zlib

    width, height = 16, 16
    # Raw pixels: each row has a filter byte (0) + RGB pixels
    raw_data = b""
    for _ in range(height):
        raw_data += b"\x00"  # filter byte
        raw_data += b"\xff\x00\x00" * width  # red pixels

    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    compressed = zlib.compress(raw_data)

    png = b"\x89PNG\r\n\x1a\n"
    png += png_chunk(b"IHDR", ihdr)
    png += png_chunk(b"IDAT", compressed)
    png += png_chunk(b"IEND", b"")

    return base64.b64encode(png).decode()


# ──────────────────────────────────────────────────────────────────────
# Output formatting
# ──────────────────────────────────────────────────────────────────────

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


def _trunc(s: str | None, n: int = 200) -> str:
    if not s:
        return "(empty)"
    s = s.replace("\n", "\\n")
    return s[:n] + "..." if len(s) > n else s


def print_result(scenario_name: str, raw: dict, resp: LLMResponse, issues: list[str], elapsed: float):
    status = f"{GREEN}PASS{RESET}" if not issues else f"{RED}FAIL{RESET}"
    print(f"\n{'─' * 60}")
    print(f"{BOLD}{scenario_name}{RESET}  {status}  {DIM}({elapsed:.1f}s){RESET}")
    print(f"{'─' * 60}")

    # Raw fields
    if "error" in raw:
        print(f"  {RED}Error:{RESET} {raw.get('error', '')}")
        print(f"  {DIM}Body: {raw.get('body', '')}{RESET}")
    else:
        msg = (raw.get("choices") or [{}])[0].get("message") or {}
        print(f"  {CYAN}Raw response:{RESET}")
        print(f"    model:            {raw.get('model', '?')}")
        print(f"    finish_reason:    {(raw.get('choices') or [{}])[0].get('finish_reason', '?')}")
        print(f"    content:          {_trunc(msg.get('content'))}")
        for rfield in ("reasoning_content", "reasoning", "thinking"):
            val = msg.get(rfield)
            if val:
                print(f"    {rfield}: {_trunc(val)}")
        if msg.get("tool_calls"):
            for i, tc in enumerate(msg["tool_calls"]):
                fn = tc.get("function", {})
                print(f"    tool_call[{i}]:     {fn.get('name')}({_trunc(fn.get('arguments', ''), 100)})")
        usage = raw.get("usage", {})
        if usage:
            parts = [f"{k}={v}" for k, v in usage.items() if isinstance(v, int)]
            print(f"    usage:            {', '.join(parts)}")

    # Normalized
    print(f"  {CYAN}Normalized:{RESET}")
    print(f"    content:          {_trunc(resp.content)}")
    if resp.thinking:
        print(f"    thinking:         {_trunc(resp.thinking)}")
    if resp.tool_calls:
        for i, tc in enumerate(resp.tool_calls):
            print(f"    tool_call[{i}]:     {tc.name}({_trunc(tc.arguments, 100)})")
    print(f"    finish_reason:    {resp.finish_reason.value}")
    print(f"    usage:            prompt={resp.usage.prompt_tokens} completion={resp.usage.completion_tokens} total={resp.usage.total_tokens}")
    if resp.usage.reasoning_tokens:
        print(f"    reasoning_tokens: {resp.usage.reasoning_tokens}")

    if issues:
        print(f"  {YELLOW}Issues:{RESET}")
        for issue in issues:
            print(f"    • {issue}")


# ──────────────────────────────────────────────────────────────────────
# Config-based endpoint discovery
# ──────────────────────────────────────────────────────────────────────

def _resolve_api_key(url: str, explicit_key: str | None = None) -> str | None:
    """Resolve API key from explicit value or environment variables.

    Checks env vars based on the endpoint URL:
    - openrouter.ai → OPENROUTER_API_KEY
    - api.together.xyz → TOGETHER_API_KEY
    - api.openai.com → OPENAI_API_KEY
    """
    if explicit_key:
        return explicit_key

    import os
    url_lower = url.lower()
    if "openrouter" in url_lower:
        return os.environ.get("OPENROUTER_API_KEY")
    if "together" in url_lower:
        return os.environ.get("TOGETHER_API_KEY")
    if "openai.com" in url_lower:
        return os.environ.get("OPENAI_API_KEY")
    if "deepseek" in url_lower:
        return os.environ.get("DEEPSEEK_API_KEY")
    if "generativelanguage.googleapis.com" in url_lower:
        return os.environ.get("GEMINI_API_KEY")
    return None


def load_configured_endpoints() -> list[dict]:
    """Load endpoints from config.yaml + env vars for --all mode."""
    import os
    endpoints = []

    # Try to find and parse config.yaml
    config_paths = [
        Path.home() / "Library/Application Support/ai.stimma.stimma.debug/default/config.yaml",
        Path.home() / "Library/Application Support/ai.stimma.stimma/default/config.yaml",
    ]

    for config_path in config_paths:
        if not config_path.exists():
            continue
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            print(f"{YELLOW}Warning: could not parse {config_path}: {e}{RESET}")
            continue

        llms = cfg.get("llms", {})
        for role, role_cfg in llms.items():
            ep = role_cfg.get("endpoint")
            if ep and ep.get("url"):
                endpoints.append({
                    "name": f"config:{role}",
                    "url": ep["url"],
                    "model": ep.get("model", ""),
                    "api_key": _resolve_api_key(ep["url"], ep.get("api_key")),
                })
        break  # Use first found config

    # Endpoints discoverable from env vars
    env_endpoints = []
    if os.environ.get("OPENROUTER_API_KEY"):
        env_endpoints.append({
            "name": "OpenRouter",
            "url": "https://openrouter.ai/api/v1",
            "model": "qwen/qwen3-235b-a22b",
            "api_key": os.environ["OPENROUTER_API_KEY"],
        })
    if os.environ.get("TOGETHER_API_KEY"):
        env_endpoints.append({
            "name": "Together AI",
            "url": "https://api.together.xyz/v1",
            "model": "Qwen/Qwen3.5-397B-A17B",
            "api_key": os.environ["TOGETHER_API_KEY"],
        })
    if os.environ.get("OPENAI_API_KEY"):
        env_endpoints.append({
            "name": "OpenAI",
            "url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "api_key": os.environ["OPENAI_API_KEY"],
        })
    if os.environ.get("DEEPSEEK_API_KEY"):
        env_endpoints.append({
            "name": "DeepSeek",
            "url": "https://api.deepseek.com/v1",
            "model": "deepseek-reasoner",
            "api_key": os.environ["DEEPSEEK_API_KEY"],
        })
    if os.environ.get("GEMINI_API_KEY"):
        env_endpoints.append({
            "name": "Gemini",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash",
            "api_key": os.environ["GEMINI_API_KEY"],
        })

    for ep in env_endpoints:
        if not any(e["url"] == ep["url"] for e in endpoints):
            endpoints.append(ep)

    # Well-known local endpoints
    well_known = [
        {"name": "vLLM (llm-host)", "url": "http://llm-host:8000/v1", "model": "gpt-oss-120b", "api_key": None},
        {"name": "Stimma Cloud", "url": "http://localhost:8787/api/llm/v1", "model": "agent", "api_key": None},
    ]

    for ep in well_known:
        if not any(e["url"] == ep["url"] for e in endpoints):
            endpoints.append(ep)

    return endpoints


async def check_reachable(url: str, api_key: str | None = None) -> bool:
    """Quick check if an endpoint is reachable."""
    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            # Try /models endpoint
            resp = await client.get(f"{url.rstrip('/')}/models", headers=headers)
            return resp.status_code < 500
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

SCENARIOS = {
    "text": scenario_text,
    "thinking": scenario_thinking,
    "tools": scenario_tools,
    "vision": scenario_vision,
}


async def run_scenarios(
    url: str, model: str, api_key: str | None,
    scenarios: list[str], image_path: str | None = None, name: str = "",
):
    label = name or url
    print(f"\n{'═' * 60}")
    print(f"{BOLD}Endpoint: {label}{RESET}")
    print(f"  URL:   {url}")
    print(f"  Model: {model}")
    print(f"{'═' * 60}")

    total_issues = 0
    for scenario_name in scenarios:
        t0 = time.time()
        try:
            if scenario_name == "vision":
                raw, issues = await scenario_vision(url, model, api_key, image_path)
            else:
                raw, issues = await SCENARIOS[scenario_name](url, model, api_key)
            elapsed = time.time() - t0
            resp = normalize_response(raw) if "error" not in raw else LLMResponse()
            print_result(scenario_name, raw, resp, issues, elapsed)
            total_issues += len(issues)
        except Exception as e:
            elapsed = time.time() - t0
            print_result(scenario_name, {"error": str(e)}, LLMResponse(), [str(e)], elapsed)
            total_issues += 1

    return total_issues


async def main():
    parser = argparse.ArgumentParser(
        description="Validate LLM normalization against real endpoints"
    )
    parser.add_argument("--endpoint", help="Endpoint URL (e.g. https://openrouter.ai/api/v1)")
    parser.add_argument("--model", help="Model to test")
    parser.add_argument("--api-key", help="API key")
    parser.add_argument("--all", action="store_true", help="Test all configured endpoints")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()), help="Run only one scenario")
    parser.add_argument("--image", help="Image file path for vision test")
    args = parser.parse_args()

    scenarios = [args.scenario] if args.scenario else list(SCENARIOS.keys())

    if args.all:
        endpoints = load_configured_endpoints()
        if not endpoints:
            print(f"{RED}No endpoints found in config.yaml{RESET}")
            sys.exit(1)

        total_issues = 0
        for ep in endpoints:
            reachable = await check_reachable(ep["url"], ep.get("api_key"))
            if not reachable:
                print(f"\n{YELLOW}Skipping {ep['name']} ({ep['url']}) — not reachable{RESET}")
                continue
            issues = await run_scenarios(
                ep["url"], ep["model"], ep.get("api_key"),
                scenarios, args.image, name=ep["name"],
            )
            total_issues += issues

        print(f"\n{'═' * 60}")
        if total_issues:
            print(f"{RED}{BOLD}Total issues: {total_issues}{RESET}")
        else:
            print(f"{GREEN}{BOLD}All scenarios passed!{RESET}")
        sys.exit(1 if total_issues else 0)

    elif args.endpoint:
        if not args.model:
            print(f"{RED}--model is required with --endpoint{RESET}")
            sys.exit(1)
        api_key = _resolve_api_key(args.endpoint, args.api_key)
        issues = await run_scenarios(
            args.endpoint, args.model, api_key,
            scenarios, args.image,
        )
        sys.exit(1 if issues else 0)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

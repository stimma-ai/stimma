"""Shared LLM call options for agent loops."""

from typing import Any

# Budget for structured extended thinking (Anthropic-style). Hardcoded — not a
# user-configurable knob. Each agent entry point decides whether thinking is on
# at its call site; budget is uniform when it is.
_THINKING_BUDGET_TOKENS = 10000


def agent_llm_options(*, enable_thinking: bool) -> dict[str, Any]:
    """Return agent LLM options that keep model scratchpad out of content.

    Some OpenAI-compatible endpoints default template-level thinking on, and
    then put scratchpad text in ``message.content`` instead of a structured
    reasoning field. We make the app-level agent setting explicit on every
    agent call so the provider cannot silently choose the unsafe default.

    ``enable_thinking`` is required and is set per call site, not via config —
    interactive agent loops (chat, recipe, delegate, prompt-improver mini-agent)
    pass ``True``; tiny one-off tasks (auto-name, captioning) bypass this
    helper and go through ``llm_complete_text`` which hardcodes thinking off.
    """
    options: dict[str, Any] = {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}},
    }
    if enable_thinking:
        options["thinking"] = {"type": "enabled", "budget_tokens": _THINKING_BUDGET_TOKENS}
    return options

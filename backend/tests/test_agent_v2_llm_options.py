from agent.v2.llm_options import agent_llm_options


def test_agent_llm_options_disable_template_thinking():
    """Explicit False suppresses template-level thinking and omits the
    structured-thinking field, so OpenAI-compatible servers can't silently
    leak scratchpad into message.content."""
    assert agent_llm_options(enable_thinking=False) == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }


def test_agent_llm_options_enable_structured_thinking():
    """When thinking is on we send both the template kwarg and the structured
    ``thinking`` budget field — providers that honor either path get the
    intended behavior."""
    assert agent_llm_options(enable_thinking=True) == {
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
        "thinking": {"type": "enabled", "budget_tokens": 10000},
    }

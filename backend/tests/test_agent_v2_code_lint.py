"""Tests for the run_code pre-execution linter (agent/v2/code_lint.py)."""

import pytest

from agent.v2.code_lint import lint_code


TOOL_IMPORT = "from stimma.tools.text_to_image import flux_klein_9b\n"


def _messages(code: str) -> list[str]:
    return [w.message for w in lint_code(code)]


# ── unawaited tool calls: real bugs still flagged ────────────────────

def test_bare_tool_call_statement_warns():
    code = TOOL_IMPORT + 'flux_klein_9b(prompt="a cat")\n'
    assert any("must await" in m for m in _messages(code))


def test_assigned_but_never_used_warns():
    code = TOOL_IMPORT + 'r = flux_klein_9b(prompt="a cat")\n'
    assert any("must await" in m for m in _messages(code))


def test_assigned_then_attribute_access_warns():
    code = TOOL_IMPORT + (
        'r = flux_klein_9b(prompt="a cat")\n'
        "stimma.show(r.media_id, role='final')\n"
    )
    assert any("must await" in m for m in _messages(code))


def test_awaited_tool_call_is_clean():
    code = TOOL_IMPORT + 'r = await flux_klein_9b(prompt="a cat")\n'
    assert not any("must await" in m for m in _messages(code))


# ── coroutine collection for gather: must NOT be flagged ─────────────

def test_gather_via_appended_tuple_is_clean():
    # The parameter-grid skill's canonical pattern.
    code = TOOL_IMPORT + (
        "import asyncio\n"
        "indexed_coros = []\n"
        "for col in range(5):\n"
        "    for row in range(5):\n"
        '        coro = flux_klein_9b(prompt="a cat", steps=col)\n'
        "        indexed_coros.append((row, col, coro))\n"
        "results = await asyncio.gather(*[c for _, _, c in indexed_coros])\n"
    )
    assert not any("must await" in m for m in _messages(code))


def test_gather_via_list_literal_is_clean():
    code = TOOL_IMPORT + (
        "import asyncio\n"
        'a = flux_klein_9b(prompt="a cat")\n'
        'b = flux_klein_9b(prompt="a dog")\n'
        "results = await asyncio.gather(*[a, b])\n"
    )
    assert not any("must await" in m for m in _messages(code))


def test_coroutine_passed_directly_to_gather_is_clean():
    code = TOOL_IMPORT + (
        "import asyncio\n"
        'coro = flux_klein_9b(prompt="a cat")\n'
        "results = await asyncio.gather(coro)\n"
    )
    assert not any("must await" in m for m in _messages(code))


def test_variable_awaited_later_is_clean():
    code = TOOL_IMPORT + (
        'coro = flux_klein_9b(prompt="a cat")\n'
        "r = await coro\n"
    )
    assert not any("must await" in m for m in _messages(code))


def test_unpack_target_does_not_count_as_consumption():
    # `for a, b, c in ...` unpacking reuses the name `coro`; that store-context
    # tuple must not suppress the warning for the dead assignment below.
    code = TOOL_IMPORT + (
        'coro = flux_klein_9b(prompt="a cat")\n'
        "for x, y, coro2 in []:\n"
        "    pass\n"
    )
    assert any("must await" in m for m in _messages(code))


# ── unawaited async stimma SDK methods get the same treatment ────────

def test_stimma_async_method_unused_warns():
    code = 'r = stimma.llm("hello")\n'
    msgs = _messages(code)
    assert any("is async" in m and "await" in m for m in msgs)


def test_stimma_async_method_gathered_is_clean():
    code = (
        "import asyncio\n"
        'a = stimma.llm("hello")\n'
        'b = stimma.llm("world")\n'
        "results = await asyncio.gather(a, b)\n"
    )
    assert not any("is async" in m for m in _messages(code))

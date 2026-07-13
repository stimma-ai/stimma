"""Tests for the pre-execution code linter."""

import pytest
from agent.v2.code_lint import lint_code, format_lint_errors


class TestInvalidAttributes:
    def test_invalid_stimma_method(self):
        warnings = lint_code("stimma.generate('a cat')")
        assert len(warnings) == 1
        assert "stimma.generate" in warnings[0].message
        assert "does not exist" in warnings[0].message

    def test_invalid_stimma_library_method(self):
        warnings = lint_code("await stimma.library.find('cats')")
        assert len(warnings) == 1
        assert "stimma.library.find" in warnings[0].message

    def test_valid_stimma_methods_no_warnings(self):
        code = """
from stimma.tools.text_to_image import gen
result = await gen(prompt="cat")
stimma.show(result, role="final")
"""
        warnings = lint_code(code)
        assert warnings == []

    def test_call_tool_removed_redirects_to_import(self):
        warnings = lint_code('await stimma.call_tool("comfyui:flux", prompt="cat")')
        assert len(warnings) == 1
        assert "removed" in warnings[0].message
        assert "stimma.tools" in warnings[0].suggestion

    def test_valid_library_methods_no_warnings(self):
        code = """
items = await stimma.library.search("cats")
info = await stimma.library.get(123)
await stimma.library.save(result, tags=["cat"])
"""
        warnings = lint_code(code)
        assert warnings == []

    def test_library_attribute_is_allowed(self):
        warnings = lint_code("x = stimma.library")
        assert warnings == []

    def test_filters_property_is_valid(self):
        warnings = lint_code("print(stimma.filters)")
        assert warnings == []

    def test_multiple_invalid_attrs(self):
        code = """
stimma.generate("cat")
stimma.library.find("dog")
"""
        warnings = lint_code(code)
        assert len(warnings) == 2


class TestAwaitLinting:
    def test_await_on_sync_method(self):
        warnings = lint_code("await stimma.show(result, role='final')")
        assert len(warnings) == 1
        assert "sync" in warnings[0].message
        assert "do not await" in warnings[0].message.lower()

    def test_await_on_sync_show_grid(self):
        warnings = lint_code("await stimma.show_grid(results, role='final')")
        assert len(warnings) == 1
        assert "sync" in warnings[0].message

    def test_await_on_sync_adjust(self):
        warnings = lint_code("img = await stimma.adjust(img, brightness=10)")
        assert len(warnings) == 1
        assert "sync" in warnings[0].message

    def test_missing_await_on_async_method(self):
        warnings = lint_code("result = stimma.llm('describe a cat')")
        assert len(warnings) == 1
        assert "async" in warnings[0].message
        assert "must await" in warnings[0].message

    def test_missing_await_on_library_method(self):
        warnings = lint_code("items = stimma.library.search('cats')")
        assert len(warnings) == 1
        assert "must await" in warnings[0].message

    def test_proper_await_no_warning(self):
        warnings = lint_code("result = await stimma.llm('describe a cat')")
        assert warnings == []

    def test_unawaited_expression_statement(self):
        warnings = lint_code("stimma.llm('describe a cat')")
        assert len(warnings) == 1
        assert "must await" in warnings[0].message


class TestAntiPatterns:
    def test_asyncio_run(self):
        warnings = lint_code("asyncio.run(main())")
        assert len(warnings) == 1
        assert "asyncio.run()" in warnings[0].message

    def test_async_def_main(self):
        code = """
async def main():
    result = await stimma.llm("describe a cat")
    stimma.show(result, role="final")
"""
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "async def main()" in warnings[0].message

    def test_regular_async_def_is_fine(self):
        code = """
async def process_item(item):
    return await stimma.llm(item)
"""
        warnings = lint_code(code)
        assert warnings == []


class TestEdgeCases:
    def test_syntax_error_returns_empty(self):
        warnings = lint_code("def foo(:")
        assert warnings == []

    def test_empty_code(self):
        warnings = lint_code("")
        assert warnings == []

    def test_private_attrs_ignored(self):
        warnings = lint_code("stimma._internal_thing()")
        assert warnings == []

    def test_non_stimma_code_ignored(self):
        code = """
x = some_lib.generate()
y = other.library.find()
"""
        warnings = lint_code(code)
        assert warnings == []

    def test_suggestions_for_close_names(self):
        warnings = lint_code("stimma.search('cats')")
        assert len(warnings) == 1
        # Should not crash — suggestion content is best-effort

    def test_gather_in_comprehension(self):
        code = """
results = await asyncio.gather(
    *[stimma.call_tool("flux", prompt=p) for p in prompts]
)
"""
        # The stimma.call_tool inside list comp is intentionally unawaited
        # (it's a coroutine being passed to gather). This is tricky to
        # distinguish statically, so we accept a false positive here
        # or the lint should handle it. Let's see what happens.
        warnings = lint_code(code)
        # The call_tool inside the list comp is inside a starred arg to gather,
        # not a direct Assign/Expr statement, so it shouldn't trigger
        assert not any("call_tool" in w.message and "must await" in w.message for w in warnings)


class TestBareImports:
    """Tests for `from stimma import X` followed by bare X() calls."""

    def test_await_on_sync_bare_import(self):
        code = """
from stimma import show
await show(results, role="final")
"""
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "sync" in warnings[0].message
        assert "do not await" in warnings[0].message.lower()

    def test_missing_await_on_async_bare_import(self):
        code = """
from stimma import llm
result = llm("describe a cat")
"""
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "async" in warnings[0].message
        assert "must await" in warnings[0].message

    def test_bare_import_correct_usage_no_warnings(self):
        code = """
from stimma import llm, show
result = await llm("describe a cat")
show(result, role="final")
"""
        warnings = lint_code(code)
        assert warnings == []

    def test_tool_import_missing_await(self):
        """Tools imported from stimma.tools.<task> are async — catch missing await."""
        code = """
from stimma.tools.text_to_image import gen
result = gen(prompt="cat")
"""
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "must await" in warnings[0].message

    def test_tool_import_proper_await_no_warning(self):
        code = """
from stimma.tools.text_to_image import gen
result = await gen(prompt="cat")
"""
        warnings = lint_code(code)
        assert warnings == []

    def test_gather_with_unawaited_coroutines(self):
        """Coroutines passed as args to asyncio.gather should not warn must-await."""
        code = """
results = await asyncio.gather(
    stimma.llm("a"),
    stimma.llm("b"),
)
"""
        warnings = lint_code(code)
        assert not any("must await" in w.message for w in warnings)

    def test_bare_import_aliased(self):
        code = """
from stimma import llm as describe
result = describe("a cat")
"""
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "must await" in warnings[0].message

    def test_bare_import_mixed_with_stimma_dot(self):
        """Both styles in the same code should both be linted."""
        code = """
from stimma import show
await show(result, role="final")
await stimma.show(result2, role="final")
"""
        warnings = lint_code(code)
        assert len(warnings) == 2
        assert all("sync" in w.message for w in warnings)


class TestLibraryCallable:
    """Tests for catching stimma.library(...) direct calls."""

    def test_stimma_library_called_directly(self):
        code = "await stimma.library(action='board', board_name='x')"
        warnings = lint_code(code)
        assert any("not callable" in w.message for w in warnings)

    def test_stimma_library_methods_are_fine(self):
        code = 'items = await stimma.library.search("cats")'
        warnings = lint_code(code)
        assert not any("not callable" in w.message for w in warnings)


class TestAwaitNonAwaitable:
    """Tests for catching await on non-awaitable types (lists, comprehensions)."""

    def test_await_list_literal(self):
        code = "results = await [coro1, coro2]"
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "Cannot await a list" in warnings[0].message
        assert "asyncio.gather" in warnings[0].suggestion

    def test_await_list_comprehension(self):
        code = 'results = await [stimma.llm(p) for p in prompts]'
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "Cannot await a list" in warnings[0].message
        assert "asyncio.gather" in warnings[0].suggestion

    def test_await_generator_expression(self):
        code = 'results = await (stimma.llm(p) for p in prompts)'
        warnings = lint_code(code)
        assert len(warnings) == 1
        assert "Cannot await a generator" in warnings[0].message
        assert "asyncio.gather" in warnings[0].suggestion

    def test_await_asyncio_gather_no_warning(self):
        """asyncio.gather is correct — should not warn."""
        code = """
results = await asyncio.gather(*[stimma.call_tool("flux", prompt=p) for p in prompts])
"""
        warnings = lint_code(code)
        assert not any("Cannot await" in w.message for w in warnings)

    def test_stimma_gather_warns_does_not_exist(self):
        """stimma.gather was removed — lint should flag it."""
        code = """
results = await stimma.gather(*[stimma.call_tool("flux", prompt=p) for p in prompts])
"""
        warnings = lint_code(code)
        assert any("does not exist" in w.message for w in warnings)


class TestKwargsValidation:
    """Tests for keyword argument validation on stimma methods and asyncio.gather."""

    def test_create_set_legacy_kwargs_ok(self):
        code = 'await stimma.create_set(results, title="My Set", description="foo")'
        warnings = lint_code(code)
        assert not any("unexpected keyword" in w.message for w in warnings)

        code = 'await stimma.create_set(media_ids=results, title="My Set")'
        warnings = lint_code(code)
        assert not any("unexpected keyword" in w.message for w in warnings)

    def test_create_set_valid_kwargs(self):
        code = 'await stimma.create_set(results, title="My Set")'
        warnings = lint_code(code)
        assert not any("unexpected keyword" in w.message for w in warnings)

    def test_asyncio_gather_invalid_kwarg(self):
        code = """
results = await asyncio.gather(
    *[stimma.call_tool("flux", prompt=p) for p in prompts],
    desc="Generating"
)
"""
        warnings = lint_code(code)
        assert any("unexpected keyword argument 'desc'" in w.message for w in warnings)

    def test_asyncio_gather_return_exceptions_ok(self):
        code = """
results = await asyncio.gather(
    *[stimma.call_tool("flux", prompt=p) for p in prompts],
    return_exceptions=True
)
"""
        warnings = lint_code(code)
        assert not any("unexpected keyword" in w.message for w in warnings)

    def test_asyncio_gather_no_kwargs_ok(self):
        code = """
results = await asyncio.gather(*[stimma.call_tool("flux", prompt=p) for p in prompts])
"""
        warnings = lint_code(code)
        assert not any("unexpected keyword" in w.message for w in warnings)

    def test_call_tool_kwargs_not_checked(self):
        """call_tool accepts **kwargs (pass-through to tools), so any kwarg is fine."""
        code = 'await stimma.call_tool("flux", prompt="cat", weird_param=42)'
        warnings = lint_code(code)
        assert not any("unexpected keyword" in w.message for w in warnings)


class TestFormatting:
    def test_format_lint_errors(self):
        warnings = lint_code("stimma.generate('cat')")
        output = format_lint_errors(warnings)
        assert "Line" in output
        assert "stimma.generate" in output
        assert "Fix the code" in output
        assert ".stimma/tools/" in output

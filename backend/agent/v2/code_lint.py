"""Pre-execution AST linter for agent-generated Python code.

Catches common SDK misuse *before* running code so the agent gets fast,
actionable feedback without burning user balance on doomed executions.

Method tables are derived from the actual StimmaSDK and StimmaLibraryAPI
classes via introspection — no manual sync needed when the SDK changes.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from dataclasses import dataclass
from typing import Any

# Agent-level tools that have NO SDK equivalent inside run_code.
# Used to give specific "use this outside run_code" guidance instead of
# a generic "method doesn't exist" error.
AGENT_ONLY_TOOLS = frozenset({
    "create_layout", "bash", "view_image", "ask_user",
    "browse_web",
    "skill", "notepad",
})


def _build_method_table(cls) -> dict[str, bool]:
    """Build {method_name: is_async} from a class's public interface.

    Includes methods and properties. Skips private/dunder names.
    """
    table: dict[str, bool] = {}
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name, None)
        if attr is None:
            continue
        if isinstance(attr, property):
            table[name] = False
        elif callable(attr):
            table[name] = asyncio.iscoroutinefunction(attr)
    return table


def _build_kwargs_table(cls) -> dict[str, set[str]]:
    """Build {method_name: {valid_kwarg_names}} from a class's public interface.

    Only includes methods with inspectable signatures. VAR_KEYWORD (**kwargs)
    methods are excluded (they accept anything).
    """
    table: dict[str, set[str]] = {}
    for name in dir(cls):
        if name.startswith("_"):
            continue
        attr = getattr(cls, name, None)
        if attr is None or not callable(attr):
            continue
        try:
            sig = inspect.signature(attr)
        except (ValueError, TypeError):
            continue
        # If the method accepts **kwargs, skip — it allows anything
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            continue
        params = set()
        for pname, p in sig.parameters.items():
            if pname == "self":
                continue
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                          inspect.Parameter.KEYWORD_ONLY):
                params.add(pname)
        if params:
            table[name] = params
    return table


# Lazy-init to avoid circular imports (code_runtime imports us)
_stimma_methods: dict[str, bool] | None = None
_library_methods: dict[str, bool] | None = None
_stimma_kwargs: dict[str, set[str]] | None = None
_library_kwargs: dict[str, set[str]] | None = None


def _ensure_tables():
    global _stimma_methods, _library_methods, _stimma_kwargs, _library_kwargs
    if _stimma_methods is not None:
        return
    from .code_runtime import StimmaSDK, StimmaLibraryAPI
    _stimma_methods = _build_method_table(StimmaSDK)
    _library_methods = _build_method_table(StimmaLibraryAPI)
    _stimma_kwargs = _build_kwargs_table(StimmaSDK)
    _library_kwargs = _build_kwargs_table(StimmaLibraryAPI)


@dataclass
class LintWarning:
    line: int  # 1-based, relative to user code (not the wrapper)
    message: str
    suggestion: str = ""


def lint_code(code: str) -> list[LintWarning]:
    """Lint agent-generated code and return warnings.

    Returns an empty list if code looks fine. Does NOT raise on syntax
    errors — those are left for compile() to report naturally.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return []  # let compile() handle it

    _ensure_tables()
    warnings: list[LintWarning] = []
    _LintVisitor(warnings, _stimma_methods, _library_methods, _stimma_kwargs, _library_kwargs).visit(tree)
    return warnings


class _LintVisitor(ast.NodeVisitor):
    def __init__(
        self,
        warnings: list[LintWarning],
        stimma_methods: dict[str, bool],
        library_methods: dict[str, bool],
        stimma_kwargs: dict[str, set[str]],
        library_kwargs: dict[str, set[str]],
    ):
        self.warnings = warnings
        self.stimma_methods = stimma_methods
        self.library_methods = library_methods
        self.stimma_kwargs = stimma_kwargs
        self.library_kwargs = library_kwargs
        # Track bare imports: from stimma import X → {local_name: stimma_method_name}
        self.bare_imports: dict[str, str] = {}
        # Track tool imports: from stimma.tools.<task> import gen → {local_name}.
        # These are async tool functions; used to catch a missing `await`.
        self.tool_imports: set[str] = set()

    # ── from stimma import X ──────────────────────────────────────

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "stimma" and node.names:
            for alias in node.names:
                local = alias.asname or alias.name
                self.bare_imports[local] = alias.name
        elif node.module and node.module.startswith("stimma.tools") and node.names:
            for alias in node.names:
                self.tool_imports.add(alias.asname or alias.name)
        self.generic_visit(node)

    # ── stimma.foo / stimma.library.foo attribute access ────────────

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # stimma.library.X
        if (
            isinstance(node.value, ast.Attribute)
            and node.value.attr == "library"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "stimma"
        ):
            method = node.attr
            if method not in self.library_methods and not method.startswith("_"):
                suggestion = _suggest(method, self.library_methods)
                self.warnings.append(LintWarning(
                    line=node.lineno,
                    message=f"stimma.library.{method}() does not exist.",
                    suggestion=suggestion,
                ))

        # stimma.X (direct attribute)
        elif isinstance(node.value, ast.Name) and node.value.id == "stimma":
            attr = node.attr
            if attr == "call_tool":
                self.warnings.append(LintWarning(
                    line=node.lineno,
                    message="stimma.call_tool() was removed — call tools by importing them.",
                    suggestion=(
                        "Browse .stimma/tools/, then: "
                        "`from stimma.tools.<task> import <tool>; r = await <tool>(...)`"
                    ),
                ))
            elif (
                attr not in self.stimma_methods
                and attr != "library"
                and not attr.startswith("_")
            ):
                if attr in AGENT_ONLY_TOOLS:
                    self.warnings.append(LintWarning(
                        line=node.lineno,
                        message=f"'{attr}' is an agent-level tool, not a stimma SDK method.",
                        suggestion=(
                            f"'{attr}' cannot be called inside run_code. "
                            f"Return from run_code and use the {attr} tool directly."
                        ),
                    ))
                else:
                    suggestion = _suggest(attr, self.stimma_methods)
                    self.warnings.append(LintWarning(
                        line=node.lineno,
                        message=f"stimma.{attr} does not exist.",
                        suggestion=suggestion,
                    ))

        self.generic_visit(node)

    # ── resolve call to stimma method ────────────────────────────────

    def _resolve_call(self, call: ast.Call) -> tuple[str | None, bool]:
        """Resolve a Call node to (stimma_method_name, is_library).

        Handles both ``stimma.foo()`` and bare ``foo()`` where foo was
        imported via ``from stimma import foo``.
        """
        name, is_library = _get_stimma_call_name(call)
        if name is not None:
            return name, is_library
        # Check bare imported names: from stimma import show → show()
        if isinstance(call.func, ast.Name) and call.func.id in self.bare_imports:
            return self.bare_imports[call.func.id], False
        return None, False

    # ── await on sync methods / missing await on async ──────────────

    def visit_Await(self, node: ast.Await) -> None:
        val = node.value
        if isinstance(val, ast.Call):
            name, is_library = self._resolve_call(val)
            if name is not None:
                lookup = self.library_methods if is_library else self.stimma_methods
                if name in lookup and not lookup[name]:
                    prefix = "stimma.library." if is_library else "stimma."
                    self.warnings.append(LintWarning(
                        line=node.lineno,
                        message=f"{prefix}{name}() is sync — do not await it.",
                        suggestion=f"Remove `await`: `{prefix}{name}(...)`",
                    ))
        elif isinstance(val, (ast.List, ast.ListComp)):
            self.warnings.append(LintWarning(
                line=node.lineno,
                message="Cannot await a list. Use asyncio.gather() to run multiple coroutines.",
                suggestion="Use: `results = await asyncio.gather(*[coro for x in items])`",
            ))
        elif isinstance(val, ast.GeneratorExp):
            self.warnings.append(LintWarning(
                line=node.lineno,
                message="Cannot await a generator expression. Use asyncio.gather() to run multiple coroutines.",
                suggestion="Use: `results = await asyncio.gather(*[coro for x in items])`",
            ))
        self.generic_visit(node)

    # ── asyncio.run() ───────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        # stimma.library(...) — library is an object, not callable
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "library"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "stimma"
        ):
            self.warnings.append(LintWarning(
                line=node.lineno,
                message="stimma.library is not callable. It has methods like .search(), .get(), .save().",
                suggestion="Use: `await stimma.library.search(query)`, `await stimma.library.get(media_id)`, etc.",
            ))

        # asyncio.run()
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
        ):
            self.warnings.append(LintWarning(
                line=node.lineno,
                message="Do not use asyncio.run() — code already runs inside async def.",
                suggestion="Use `await` directly at the top level.",
            ))

        name, is_library = self._resolve_call(node)

        # stimma.method(**kwargs) — validate kwargs against actual signatures
        if name is not None:
            kwargs_table = self.library_kwargs if is_library else self.stimma_kwargs
            if name in kwargs_table:
                valid = kwargs_table[name]
                for kw in node.keywords:
                    if kw.arg is not None and kw.arg not in valid:
                        prefix = "stimma.library." if is_library else "stimma."
                        self.warnings.append(LintWarning(
                            line=node.lineno,
                            message=f"{prefix}{name}() got unexpected keyword argument '{kw.arg}'.",
                            suggestion=f"Valid keyword arguments: {', '.join(sorted(valid))}",
                        ))

        # asyncio.gather() — only accepts return_exceptions
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "gather"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
        ):
            for kw in node.keywords:
                if kw.arg is not None and kw.arg != "return_exceptions":
                    self.warnings.append(LintWarning(
                        line=node.lineno,
                        message=f"asyncio.gather() got unexpected keyword argument '{kw.arg}'.",
                        suggestion="asyncio.gather() only accepts return_exceptions=True/False.",
                    ))

        # bare agent-tool-name function call: create_layout(...), bash(...), etc.
        if isinstance(node.func, ast.Name) and node.func.id in AGENT_ONLY_TOOLS:
            tool_name = node.func.id
            self.warnings.append(LintWarning(
                line=node.lineno,
                message=f"'{tool_name}' is an agent-level tool — not available inside run_code.",
                suggestion=(
                    f"Return from run_code and use the {tool_name} tool directly in the next turn."
                ),
            ))

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_unawaited(node.value, node.lineno)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        self._check_unawaited(node.value, node.lineno)
        self.generic_visit(node)

    def _check_unawaited(self, node: ast.AST, lineno: int) -> None:
        """Warn if an async stimma call is used without await."""
        if isinstance(node, ast.Await):
            return  # properly awaited
        if not isinstance(node, ast.Call):
            return
        # Tool functions imported from stimma.tools.<task> are async.
        if isinstance(node.func, ast.Name) and node.func.id in self.tool_imports:
            self.warnings.append(LintWarning(
                line=lineno,
                message=f"{node.func.id}() is an async tool — you must await it.",
                suggestion=f"Add `await`: `r = await {node.func.id}(...)`",
            ))
            return
        name, is_library = self._resolve_call(node)
        if name is None:
            return
        lookup = self.library_methods if is_library else self.stimma_methods
        if name in lookup and lookup[name]:
            prefix = "stimma.library." if is_library else "stimma."
            self.warnings.append(LintWarning(
                line=lineno,
                message=f"{prefix}{name}() is async — you must await it.",
                suggestion=f"Add `await`: `await {prefix}{name}(...)`",
            ))

    # ── async def main() wrapper (unnecessary) ──────────────────────

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name in ("main", "__main__"):
            self.warnings.append(LintWarning(
                line=node.lineno,
                message="Do not wrap code in `async def main()` — code already runs inside async def.",
                suggestion="Write code at the top level. Use `await` directly.",
            ))
        self.generic_visit(node)


# ── Helpers ─────────────────────────────────────────────────────────

def _get_stimma_call_name(call: ast.Call) -> tuple[str | None, bool]:
    """Extract method name from stimma.foo() or stimma.library.foo() calls.

    Returns (method_name, is_library) or (None, False).
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None, False

    # stimma.library.X()
    if (
        isinstance(func.value, ast.Attribute)
        and func.value.attr == "library"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "stimma"
    ):
        return func.attr, True

    # stimma.X()
    if isinstance(func.value, ast.Name) and func.value.id == "stimma":
        return func.attr, False

    return None, False


def _suggest(name: str, known: dict[str, bool]) -> str:
    """Find the closest matching method name for a typo/guess."""
    # Check simple prefix matches first
    if len(name) >= 3:
        candidates = [k for k in known if k.startswith(name[:3])]
        if len(candidates) == 1:
            return f"Did you mean `{candidates[0]}`?"

    # Substring match
    candidates = [k for k in known if name.lower() in k.lower() or k.lower() in name.lower()]
    if candidates:
        return f"Available methods: {', '.join(sorted(candidates))}"

    return f"Available: {', '.join(sorted(known.keys()))}"


def format_lint_errors(warnings: list[LintWarning]) -> str:
    """Format lint warnings into an error string for the agent."""
    lines = ["Code has issues that will cause errors at runtime:\n"]
    for w in warnings:
        lines.append(f"  Line {w.line}: {w.message}")
        if w.suggestion:
            lines.append(f"    → {w.suggestion}")
    lines.append("\nFix the code and try again. Browse .stimma/tools/ for tool signatures if unsure about the API.")
    return "\n".join(lines)


# ── Pre-flight validation (async, DB-backed) ──────────────────────

def _extract_hardcoded_values(code: str) -> list[tuple[int, str, str, Any]]:
    """Extract hardcoded arguments from stimma.* calls for validation.

    Returns list of (line, call_type, param_name, value) tuples.
    call_type is one of: "call_tool", "library.get", "library.lineage".
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError:
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        name, is_library = _get_stimma_call_name(node)
        if name is None:
            continue

        # stimma.call_tool("tool_id", ...) — validate tool_id
        if name == "call_tool" and not is_library and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                results.append((node.lineno, "call_tool", "tool_id", arg.value))

        # stimma.library.get(media_id) — validate media_id exists
        if name == "get" and is_library and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                results.append((node.lineno, "library.get", "media_id", arg.value))
            # Also check keyword: stimma.library.get(media_id=123)
        for kw in node.keywords:
            if name == "get" and is_library and kw.arg == "media_id":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                    results.append((node.lineno, "library.get", "media_id", kw.value.value))

        # stimma.library.lineage(media_id) — same check
        if name == "lineage" and is_library and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                results.append((node.lineno, "library.lineage", "media_id", arg.value))

    return results


async def validate_hardcoded_refs(code: str, session) -> list[LintWarning]:
    """Async pre-flight: validate hardcoded tool IDs and media IDs exist.

    Runs after lint_code() passes. Catches references that would fail
    at runtime *after* expensive work (e.g., generation) has already happened.
    """
    refs = _extract_hardcoded_values(code)
    if not refs:
        return []

    warnings = []

    for line, call_type, param, value in refs:
        if call_type == "call_tool":
            try:
                from providers.registry import ProviderRegistry
                registry = ProviderRegistry.get_instance()
                if not registry.get_tool(value):
                    warnings.append(LintWarning(
                        line=line,
                        message=f"Tool '{value}' not found.",
                        suggestion='Use list_tools() or get_schema() to find valid tool IDs.',
                    ))
            except Exception:
                pass  # registry not available, skip

        elif call_type in ("library.get", "library.lineage"):
            try:
                from models.media import MediaItem
                from sqlalchemy import select
                result = await session.execute(
                    select(MediaItem.id).where(MediaItem.id == value)
                )
                if result.scalar_one_or_none() is None:
                    warnings.append(LintWarning(
                        line=line,
                        message=f"Media item {value} not found in library.",
                        suggestion="Use stimma.library.search() or stimma.library.browse() to find valid media IDs.",
                    ))
            except Exception:
                pass  # DB not available, skip

    return warnings

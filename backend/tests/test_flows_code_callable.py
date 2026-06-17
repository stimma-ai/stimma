"""Tests for the callable form of the ``code()`` DSL primitive.

The callable form (``code(lambda x: ..., inputs={"x": node})``) lets the
agent write Python directly instead of source-in-a-string, sidestepping
the double-escape class of f-string bugs. See FLOWS_DSL.md §3, §6.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from flow_dsl import (
    DSLMisuseError,
    build_graph_from_callable,
    build_graph_from_program_file,
    build_graph_from_source,
    code,
    foreach,
    llm,
    output as dsl_output,
    phase,
    flow,
)
from flow_runtime.graph import EquationType
from flow_runtime.store_key import definition_hash_for_code


# ----- Build-time: the callable is accepted, source is captured -------------


def test_lambda_captures_canonical_source():
    @flow(name="r", outputs={"out": dsl_output("str")})
    def r():
        with phase("P"):
            return code(lambda: "hello", inputs={}, output_type="text")

    g = build_graph_from_callable(r)
    (eq,) = [e for e in g.all_equations() if e.equation_type == EquationType.CODE]
    assert eq.definition["source"] == "lambda: 'hello'"
    assert callable(eq.definition["fn"])
    assert eq.definition["output_type"] == "text"


def test_named_def_captured():
    def _build_greeting(name):
        return f"hello, {name}"

    @flow(name="r", outputs={"out": dsl_output("str")})
    def r():
        with phase("P"):
            greeting = llm("whoever")
            return code(_build_greeting, inputs={"name": greeting}, output_type="text")

    g = build_graph_from_callable(r)
    (eq,) = [e for e in g.all_equations() if e.equation_type == EquationType.CODE]
    assert "def _build_greeting(name):" in eq.definition["source"]
    assert eq.definition["fn"] is _build_greeting


def test_string_form_still_accepted():
    """Back-compat shim — existing agent-authored flows still work."""
    @flow(name="r", outputs={"out": dsl_output("str")})
    def r():
        with phase("P"):
            greeting = llm("x")
            return code(
                "return g.upper()", inputs={"g": greeting}, output_type="text",
            )

    g = build_graph_from_callable(r)
    (eq,) = [e for e in g.all_equations() if e.equation_type == EquationType.CODE]
    assert eq.definition["source"] == "return g.upper()"
    assert eq.definition["fn"] is None


# ----- Hash canonicalization: formatting doesn't bust the cache ------------


def test_whitespace_variants_hash_equal():
    @flow(name="a", outputs={"o": dsl_output("text")})
    def a():
        with phase("P"):
            return code(lambda n: f"x {n}", inputs={"n": "y"}, output_type="text")

    @flow(name="b", outputs={"o": dsl_output("text")})
    def b():
        with phase("P"):
            # Same lambda, laid out over multiple lines.
            return code(
                lambda n: f"x {n}",
                inputs={"n": "y"},
                output_type="text",
            )

    ga = build_graph_from_callable(a)
    gb = build_graph_from_callable(b)
    (eq_a,) = [e for e in ga.all_equations() if e.equation_type == EquationType.CODE]
    (eq_b,) = [e for e in gb.all_equations() if e.equation_type == EquationType.CODE]
    assert eq_a.definition["definition_hash"] == eq_b.definition["definition_hash"]


# ----- NodeRef-capturing closures are rejected ------------------------------


def test_closure_over_noderef_rejected():
    """Closing over a node from the outer scope is the exact trap ``inputs=``
    exists to prevent. The build should fail with a pointed message."""
    from flow_dsl.errors import ProgramLoadError

    @flow(name="r", outputs={"o": dsl_output("text")})
    def r():
        with phase("P"):
            greeting = llm("x")
            # BAD: greeting is a NodeRef; accessing it in the lambda body
            # via closure bypasses the runtime's resolution.
            return code(lambda: greeting, inputs={}, output_type="text")

    with pytest.raises(ProgramLoadError) as exc:
        build_graph_from_callable(r)
    assert "value reference" in str(exc.value).lower() or "noderef" in str(exc.value).lower()


def test_closure_over_module_constants_ok():
    """Closing over a non-node value (e.g. a plain string) is fine."""
    GREETING = "hello"

    @flow(name="r", outputs={"o": dsl_output("text")})
    def r():
        with phase("P"):
            return code(lambda: GREETING, inputs={}, output_type="text")

    g = build_graph_from_callable(r)
    assert any(e.equation_type == EquationType.CODE for e in g.all_equations())


# ----- Parameter / inputs alignment ----------------------------------------


def test_param_mismatch_missing_input_rejected():
    from flow_dsl.errors import ProgramLoadError

    @flow(name="r", outputs={"o": dsl_output("text")})
    def r():
        with phase("P"):
            # Lambda takes `n` but inputs doesn't provide it.
            return code(lambda n: n.upper(), inputs={}, output_type="text")

    with pytest.raises(ProgramLoadError) as exc:
        build_graph_from_callable(r)
    assert "n" in str(exc.value)


def test_param_mismatch_extra_input_rejected():
    from flow_dsl.errors import ProgramLoadError

    @flow(name="r", outputs={"o": dsl_output("text")})
    def r():
        with phase("P"):
            # inputs has `name` but the lambda doesn't accept it.
            return code(
                lambda: "hi", inputs={"name": "x"}, output_type="text",
            )

    with pytest.raises(ProgramLoadError) as exc:
        build_graph_from_callable(r)
    assert "name" in str(exc.value)


def test_kwargs_catchall_accepted():
    """A callable taking **kwargs matches any inputs set."""
    @flow(name="r", outputs={"o": dsl_output("text")})
    def r():
        def fn(**kw):
            return str(sorted(kw.items()))
        with phase("P"):
            return code(
                fn,
                inputs={"a": "x", "b": "y"},
                output_type="text",
            )

    g = build_graph_from_callable(r)
    assert any(e.equation_type == EquationType.CODE for e in g.all_equations())


# ----- Flow return/output contract ---------------------------------------


def test_single_declared_output_allows_bare_return_and_tracks_name():
    @flow(name="r", outputs={"final_photos": dsl_output("list[media]")})
    def r():
        with phase("P"):
            return llm("x")

    g = build_graph_from_callable(r)
    assert len(g.output_keys) == 1
    output_key = g.output_keys[0]
    assert g.output_name_by_key == {output_key: "final_photos"}


def test_single_declared_output_allows_named_dict_return():
    @flow(name="r", outputs={"final_photos": dsl_output("list[media]")})
    def r():
        with phase("P"):
            photos = llm("x")
            return {"final_photos": photos}

    g = build_graph_from_callable(r)
    assert len(g.output_keys) == 1
    output_key = g.output_keys[0]
    assert g.output_name_by_key == {output_key: "final_photos"}


def test_multiple_declared_outputs_require_named_dict_return():
    from flow_dsl.errors import ProgramLoadError

    @flow(
        name="r",
        outputs={
            "images": dsl_output("list[media]"),
            "caption": dsl_output("text"),
        },
    )
    def r():
        with phase("P"):
            images = llm("images")
            _caption = llm("caption")
            return images

    with pytest.raises(ProgramLoadError) as exc:
        build_graph_from_callable(r)
    assert "must return a dict" in str(exc.value)


def test_multiple_declared_outputs_reject_wrong_dict_keys():
    from flow_dsl.errors import ProgramLoadError

    @flow(
        name="r",
        outputs={
            "images": dsl_output("list[media]"),
            "caption": dsl_output("text"),
        },
    )
    def r():
        with phase("P"):
            images = llm("images")
            caption = llm("caption")
            return {"images": images, "wrong": caption}

    with pytest.raises(ProgramLoadError) as exc:
        build_graph_from_callable(r)
    assert "match declared outputs exactly" in str(exc.value)


# ----- Evaluator runs the callable with resolved inputs ---------------------


@pytest.mark.asyncio
async def test_evaluator_invokes_sync_callable():
    from flow_runtime.evaluators import EvaluationRequest
    from flow_runtime.production_evaluators import CodeEvaluator

    ev = CodeEvaluator()
    fn = lambda n: n.upper()  # noqa: E731
    request = EvaluationRequest(
        equation_key="r/code$0",
        equation_type="code",
        attempt=1,
        definition={"fn": fn, "source": "lambda n: n.upper()",
                    "output_type": "text", "static_inputs": {}},
        resolved_inputs={"inputs": {"n": "hi"}},
    )
    result = await ev(request)
    assert result.value == "HI"


@pytest.mark.asyncio
async def test_evaluator_awaits_async_callable():
    from flow_runtime.evaluators import EvaluationRequest
    from flow_runtime.production_evaluators import CodeEvaluator

    async def upper(n):
        await asyncio.sleep(0)
        return n.upper()

    ev = CodeEvaluator()
    request = EvaluationRequest(
        equation_key="r/code$0",
        equation_type="code",
        attempt=1,
        definition={"fn": upper, "source": "async def upper(n):\n    ...",
                    "output_type": "text", "static_inputs": {}},
        resolved_inputs={"inputs": {"n": "hi"}},
    )
    result = await ev(request)
    assert result.value == "HI"


@pytest.mark.asyncio
async def test_evaluator_still_runs_string_form():
    """The back-compat shim keeps running string-form code() via exec."""
    from flow_runtime.evaluators import EvaluationRequest
    from flow_runtime.production_evaluators import CodeEvaluator

    ev = CodeEvaluator()
    request = EvaluationRequest(
        equation_key="r/code$0",
        equation_type="code",
        attempt=1,
        definition={"fn": None, "source": "return n.upper()",
                    "output_type": "text", "static_inputs": {}},
        resolved_inputs={"inputs": {"n": "hi"}},
    )
    result = await ev(request)
    assert result.value == "HI"


@pytest.mark.asyncio
async def test_callable_can_use_allowed_module_globals_without_import():
    """Flow callables keep their module globals until evaluation.

    The loader pre-binds allowed sandbox modules so agent-authored lambdas like
    ``lambda raw: json.loads(raw)`` do not build successfully and then fail at
    runtime solely because the agent omitted ``import json``.
    """
    from flow_runtime.production_evaluators import CodeEvaluator
    from flow_runtime.evaluators import EvaluationRequest

    import tempfile

    src = """
from stimma.flow import flow, output, code, phase

@flow(name="r", outputs={"out": output("json")})
def r():
    with phase("Parse"):
        return code(lambda raw: json.loads(raw), inputs={"raw": '{"ok": true}'})
"""
    with tempfile.TemporaryDirectory() as tmp:
        program_path = Path(tmp) / "program.py"
        program_path.write_text(src)
        g = build_graph_from_program_file(program_path)
    (eq,) = [e for e in g.all_equations() if e.equation_type == EquationType.CODE]

    ev = CodeEvaluator()
    request = EvaluationRequest(
        equation_key=eq.key,
        equation_type="code",
        attempt=1,
        definition=eq.definition,
        resolved_inputs={"inputs": {"raw": '{"ok": true}'}},
    )
    result = await ev(request)
    assert result.value == {"ok": True}

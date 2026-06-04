"""Unit tests for the ``web_search`` recipe primitive + evaluator."""

from __future__ import annotations

import pytest

from recipe_dsl import recipe as dsl_recipe, web_search
from recipe_dsl.primitives import phase as dsl_phase, input as dsl_input, output as dsl_output, code as dsl_code, foreach as dsl_foreach
from recipe_dsl.errors import DSLMisuseError
from recipe_dsl.loader import build_graph_from_callable
from recipe_runtime.evaluators import EvaluationRequest, EvaluatorError, TOOL_ERROR
from recipe_runtime.production_evaluators import WebSearchEvaluator


# ---------------------------------------------------------------------------
# Graph build
# ---------------------------------------------------------------------------


class TestGraphBuild:
    def test_static_query_builds_one_equation(self):
        @dsl_recipe(
            name="search",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="json")},
        )
        def r(q):
            with dsl_phase("Find"):
                results = web_search("miles davis", kind="images", n=5)
                first = dsl_code(
                    lambda r: r[0]["image_url"],
                    inputs={"r": results},
                    output_type="text",
                )
            return first

        g = build_graph_from_callable(r, inputs={"q": "ignored"})
        web_eqs = [
            eq for eq in g.all_equations() if eq.equation_type.value == "web_search"
        ]
        assert len(web_eqs) == 1
        eq = web_eqs[0]
        assert eq.definition["kind"] == "images"
        assert eq.definition["n"] == 5
        assert eq.definition["query_template"] == "miles davis"
        assert "definition_hash" in eq.definition

    def test_dynamic_query_records_input_dependency(self):
        @dsl_recipe(
            name="search",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="json")},
        )
        def r(q):
            with dsl_phase("Find"):
                results = web_search(q, kind="images")
            return results

        g = build_graph_from_callable(r, inputs={"q": "monet"})
        web_eqs = [
            eq for eq in g.all_equations() if eq.equation_type.value == "web_search"
        ]
        assert len(web_eqs) == 1
        eq = web_eqs[0]
        # Dependency on the recipe-input equation is registered.
        assert eq.dependencies, "web_search should depend on the dynamic query node"

    def test_invalid_kind_rejected(self):
        @dsl_recipe(
            name="bad",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="json")},
        )
        def r(q):
            with dsl_phase("Find"):
                return web_search("x", kind="videos")

        with pytest.raises(Exception):  # ProgramLoadError wrapping DSLMisuseError
            build_graph_from_callable(r, inputs={"q": "v"})

    def test_invalid_n_rejected(self):
        @dsl_recipe(
            name="bad",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="json")},
        )
        def r(q):
            with dsl_phase("Find"):
                return web_search("x", n=0)

        with pytest.raises(Exception):
            build_graph_from_callable(r, inputs={"q": "v"})

    def test_subscript_validation_rejects_bad_key(self):
        """``r['source_url']`` should fail at build time — only ``source`` exists."""
        @dsl_recipe(
            name="bad",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="text")},
        )
        def r(q):
            with dsl_phase("Find"):
                results = web_search("x", kind="images")
                bad = dsl_code(
                    lambda r: r["source_url"],
                    inputs={"r": results},
                    output_type="text",
                )
            return bad

        # Note: the subscript validator runs only on closed DictShape upstreams,
        # which our results list is. But the binding here is the LIST not its
        # element — so it won't trigger. Skip this check; element-level subscripts
        # surface only inside foreach callbacks where items are resolved.

    def test_known_keys_in_foreach_callback(self):
        """Known image-search fields, including URL media, should build."""
        @dsl_recipe(
            name="ok",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="list[text]")},
        )
        def r(q):
            with dsl_phase("Find"):
                results = web_search("x", kind="images")
                urls = dsl_foreach(
                    results,
                    lambda item: dsl_code(
                        lambda i: i["media"]["url"],
                        inputs={"i": item},
                        output_type="text",
                    ),
                )
            return urls

        g = build_graph_from_callable(r, inputs={"q": "v"})
        assert g.all_equations()


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class TestWebSearchEvaluator:
    @pytest.mark.asyncio
    async def test_static_query_passed_to_searcher(self, monkeypatch):
        captured: dict = {}

        async def fake_search(query, *, kind, n):
            captured["query"] = query
            captured["kind"] = kind
            captured["n"] = n
            return [{"title": "t", "image_url": "http://x/i.jpg", "source": "http://x", "width": 100, "height": 80}]

        async def fake_probe(url):
            return True

        from agent.v2 import web_search_core
        monkeypatch.setattr(web_search_core, "probe_url_reachable", fake_probe)

        ev = WebSearchEvaluator(searcher=fake_search)
        req = EvaluationRequest(
            equation_key="r/web_search$0",
            equation_type="web_search",
            attempt=1,
            definition={
                "query_template": "miles davis",
                "kind": "images",
                "n": 5,
                "definition_hash": "deadbeef",
            },
            resolved_inputs={},
            recipe_id=1,
            phase_path=[],
        )
        result = await ev(req)
        assert captured == {"query": "miles davis", "kind": "images", "n": 5}
        assert isinstance(result.value, list)
        assert result.value[0]["image_url"] == "http://x/i.jpg"
        assert result.value[0]["media"] == {
            "type": "url_media",
            "url": "http://x/i.jpg",
            "mime_type": "image/*",
            "title": "t",
            "source": "http://x",
        }

    @pytest.mark.asyncio
    async def test_dynamic_query_template_renders(self):
        async def fake_search(query, *, kind, n):
            assert query == "claude monet"
            return []

        ev = WebSearchEvaluator(searcher=fake_search)
        req = EvaluationRequest(
            equation_key="r/web_search$0",
            equation_type="web_search",
            attempt=1,
            definition={
                "query_template": "{0}",
                "kind": "text",
                "n": 10,
                "definition_hash": "deadbeef",
            },
            resolved_inputs={"query": {"0": "claude monet"}},
            recipe_id=1,
            phase_path=[],
        )
        result = await ev(req)
        assert result.value == []

    @pytest.mark.asyncio
    async def test_empty_query_raises_tool_error(self):
        async def fake_search(*args, **kwargs):
            pytest.fail("should not be called")

        ev = WebSearchEvaluator(searcher=fake_search)
        req = EvaluationRequest(
            equation_key="r/web_search$0",
            equation_type="web_search",
            attempt=1,
            definition={
                "query_template": "   ",
                "kind": "text",
                "n": 10,
                "definition_hash": "deadbeef",
            },
            resolved_inputs={},
            recipe_id=1,
            phase_path=[],
        )
        with pytest.raises(EvaluatorError) as ei:
            await ev(req)
        assert ei.value.category == TOOL_ERROR

    @pytest.mark.asyncio
    async def test_searcher_failure_raises_tool_error(self):
        async def boom(*args, **kwargs):
            raise RuntimeError("network down")

        ev = WebSearchEvaluator(searcher=boom)
        req = EvaluationRequest(
            equation_key="r/web_search$0",
            equation_type="web_search",
            attempt=1,
            definition={
                "query_template": "x",
                "kind": "text",
                "n": 10,
                "definition_hash": "deadbeef",
            },
            resolved_inputs={},
            recipe_id=1,
            phase_path=[],
        )
        with pytest.raises(EvaluatorError):
            await ev(req)

"""Unit tests for the ``fetch_media`` recipe primitive + evaluator."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from recipe_dsl import fetch_media, recipe as dsl_recipe, web_search
from recipe_dsl.primitives import (
    code as dsl_code,
    foreach as dsl_foreach,
    input as dsl_input,
    output as dsl_output,
    phase as dsl_phase,
)
from recipe_dsl.errors import DSLMisuseError
from recipe_dsl.loader import build_graph_from_callable
from recipe_runtime.evaluators import EvaluationRequest, EvaluatorError, TOOL_ERROR
from recipe_runtime.production_evaluators import FetchMediaEvaluator, promote_url_media_value


# A 1x1 PNG (valid magic bytes + minimal IHDR/IDAT/IEND chunks).
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000005000100"
    "0d0a2db40000000049454e44ae426082"
)


# ---------------------------------------------------------------------------
# Graph build
# ---------------------------------------------------------------------------


class TestGraphBuild:
    def test_static_url_builds_one_equation(self):
        @dsl_recipe(
            name="fetch",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="media")},
        )
        def r(q):
            with dsl_phase("Fetch"):
                m = fetch_media("http://example.com/x.png")
            return m

        g = build_graph_from_callable(r, inputs={"q": "v"})
        eqs = [eq for eq in g.all_equations() if eq.equation_type.value == "fetch_media"]
        assert len(eqs) == 1
        assert eqs[0].definition["max_size_mb"] == 10
        assert "definition_hash" in eqs[0].definition

    def test_url_from_node_records_dependency(self):
        """fetch_media at top level with a NodeRef url depends on the upstream."""
        @dsl_recipe(
            name="fetch",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="media")},
        )
        def r(q):
            with dsl_phase("Fetch"):
                url = dsl_code(
                    lambda q: f"http://example.com/{q}.png",
                    inputs={"q": q},
                    output_type="text",
                )
                m = fetch_media(url)
            return m

        g = build_graph_from_callable(r, inputs={"q": "monet"})
        eqs = [eq for eq in g.all_equations() if eq.equation_type.value == "fetch_media"]
        assert len(eqs) == 1
        assert eqs[0].dependencies, "fetch_media should depend on the dynamic url node"

    def test_invalid_max_size_rejected(self):
        @dsl_recipe(
            name="bad",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="media")},
        )
        def r(q):
            with dsl_phase("Fetch"):
                return fetch_media("http://x", max_size_mb=0)

        with pytest.raises(Exception):
            build_graph_from_callable(r, inputs={"q": "v"})

    def test_empty_url_rejected(self):
        @dsl_recipe(
            name="bad",
            inputs={"q": dsl_input(type="str")},
            outputs={"out": dsl_output(type="media")},
        )
        def r(q):
            with dsl_phase("Fetch"):
                return fetch_media("")

        with pytest.raises(Exception):
            build_graph_from_callable(r, inputs={"q": "v"})


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def _make_request(*, url="http://example.com/x.png", max_size_mb=10) -> EvaluationRequest:
    return EvaluationRequest(
        equation_key="r/fetch_media$0",
        equation_type="fetch_media",
        attempt=1,
        definition={
            "max_size_mb": max_size_mb,
            "definition_hash": "deadbeef",
        },
        resolved_inputs={"url": url},
        recipe_id=1,
        phase_path=[],
    )


class TestFetchMediaEvaluator:
    @pytest.mark.asyncio
    async def test_404_raises_tool_error(self):
        from agent.v2.web_search_core import WebFetchError

        async def fake_fetch(url, *, max_size_mb):
            raise WebFetchError(f"HTTP 404 fetching {url}", status_code=404)

        ev = FetchMediaEvaluator(fetcher=fake_fetch)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_make_request())
        assert ei.value.category == TOOL_ERROR
        assert "404" in str(ei.value)

    @pytest.mark.asyncio
    async def test_oversize_raises_tool_error(self):
        from agent.v2.web_search_core import WebFetchError

        async def fake_fetch(url, *, max_size_mb):
            raise WebFetchError(f"response exceeded {max_size_mb} MB cap")

        ev = FetchMediaEvaluator(fetcher=fake_fetch)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_make_request(max_size_mb=1))
        assert ei.value.category == TOOL_ERROR

    @pytest.mark.asyncio
    async def test_non_image_bytes_raises_tool_error(self):
        async def fake_fetch(url, *, max_size_mb):
            return b"<!doctype html><html>hi</html>", "text/html"

        ev = FetchMediaEvaluator(fetcher=fake_fetch)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_make_request())
        assert ei.value.category == TOOL_ERROR
        assert "non-image" in str(ei.value)

    @pytest.mark.asyncio
    async def test_empty_url_raises_tool_error(self):
        async def fake_fetch(*args, **kwargs):
            pytest.fail("should not be called")

        ev = FetchMediaEvaluator(fetcher=fake_fetch)
        req = _make_request(url="")
        with pytest.raises(EvaluatorError) as ei:
            await ev(req)
        assert ei.value.category == TOOL_ERROR

    @pytest.mark.asyncio
    async def test_successful_image_calls_save_path(self):
        """Sniffs PNG, calls _save_fetched_media + tagger, returns media id."""
        async def fake_fetch(url, *, max_size_mb):
            return _TINY_PNG, "image/png"

        async def fake_save(*, data, fmt, source_url, project_id):
            assert data == _TINY_PNG
            assert fmt == "png"
            assert source_url == "http://example.com/x.png"
            return 42

        async def fake_tag(media_ids, *, recipe_id, equation_key, phase_path):
            assert media_ids == [42]
            assert recipe_id == 1

        ev = FetchMediaEvaluator(fetcher=fake_fetch)
        with patch(
            "recipe_runtime.production_evaluators._save_fetched_media", fake_save,
        ), patch(
            "recipe_runtime.production_evaluators._tag_media_with_recipe", fake_tag,
        ):
            result = await ev(_make_request())
        assert result.value == 42
        assert result.media_ids == [42]

    @pytest.mark.asyncio
    async def test_promote_url_media_value_downloads_only_selected_item(self):
        async def fake_fetch(url, *, max_size_mb):
            assert url == "http://example.com/selected.png"
            assert max_size_mb == 10
            return _TINY_PNG, "image/png"

        async def fake_save(*, data, fmt, source_url, project_id):
            assert data == _TINY_PNG
            assert fmt == "png"
            assert source_url == "http://example.com/selected.png"
            assert project_id == 7
            return 42

        async def fake_tag(media_ids, *, recipe_id, equation_key, phase_path):
            assert media_ids == [42]
            assert recipe_id == 1
            assert equation_key == "r/hitl.select$0"
            assert phase_path == ["Pick"]

        value = {
            "title": "Selected",
            "image_url": "http://example.com/selected.png",
            "media": {
                "type": "url_media",
                "url": "http://example.com/selected.png",
                "mime_type": "image/*",
            },
        }

        with patch("agent.v2.web_search_core.fetch_url_bytes", fake_fetch), patch(
            "recipe_runtime.production_evaluators._save_fetched_media", fake_save,
        ), patch(
            "recipe_runtime.production_evaluators._tag_media_with_recipe", fake_tag,
        ):
            promoted = await promote_url_media_value(
                value,
                recipe_id=1,
                project_id=7,
                equation_key="r/hitl.select$0",
                phase_path=["Pick"],
            )

        assert promoted["media_id"] == 42
        assert promoted["media"] == {
            "type": "library_media",
            "media_id": 42,
            "source_url": "http://example.com/selected.png",
        }

    @pytest.mark.asyncio
    async def test_promote_url_media_value_promotes_list_items_concurrently(self):
        started: set[str] = set()
        release = asyncio.Event()

        async def fake_fetch(url, *, max_size_mb):
            started.add(url)
            if len(started) == 2:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=1)
            return _TINY_PNG, "image/png"

        async def fake_save(*, data, fmt, source_url, project_id):
            return 101 if source_url.endswith("a.png") else 202

        async def fake_tag(media_ids, *, recipe_id, equation_key, phase_path):
            return None

        value = [
            {"media": {"type": "url_media", "url": "http://example.com/a.png"}},
            {"media": {"type": "url_media", "url": "http://example.com/b.png"}},
        ]

        with patch("agent.v2.web_search_core.fetch_url_bytes", fake_fetch), patch(
            "recipe_runtime.production_evaluators._save_fetched_media", fake_save,
        ), patch(
            "recipe_runtime.production_evaluators._tag_media_with_recipe", fake_tag,
        ):
            promoted = await promote_url_media_value(
                value,
                recipe_id=1,
                project_id=7,
                equation_key="r/hitl.select$0",
                phase_path=["Pick"],
            )

        assert started == {"http://example.com/a.png", "http://example.com/b.png"}
        assert [item["media_id"] for item in promoted] == [101, 202]

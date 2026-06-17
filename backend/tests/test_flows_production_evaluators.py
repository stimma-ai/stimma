"""Tests for the production evaluator registry (Phase 5.5 gap filler).

Covers the three production evaluators in ``flow_runtime.production_evaluators``:

  - ``ToolCallEvaluator`` submits through the generation path and tags
    produced media with a flow marker.
  - ``LLMEvaluator`` renders the DSL prompt template and parses structured
    output when ``response_format`` is set.
  - ``CodeEvaluator`` executes ``code()`` snippets via the agent's sandbox
    primitives with ``resolved_inputs`` bound as globals.

Plus the registry wiring + exception-to-category mapping + an integration
test that runs a ``tool() → code()`` flow through a real ``FlowRuntime``
with mocked providers. External services (generation queue, LLM, library
DB) are mocked in every unit test — the goal is to verify the flow
runtime's contract with the evaluator surface, not re-test the agent's
generation path.
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from flow_dsl import code as dsl_code, flow as dsl_flow, tool as dsl_tool
from flow_dsl.primitives import phase as dsl_phase
from flow_runtime import (
    EquationStore,
    EvaluationRequest,
    EvaluationResult,
    FlowRuntime,
    create_flow_state_db,
    graph_db,
)
from flow_runtime.evaluators import (
    CODE_ERROR,
    LLM_ERROR,
    RESOURCE_ERROR,
    TOOL_ERROR,
    TRANSIENT,
    EvaluatorError,
)
from flow_runtime.production_evaluators import (
    CodeEvaluator,
    CreateDocumentEvaluator,
    CreateGridEvaluator,
    CreateSetEvaluator,
    InfoEvaluator,
    LLMEvaluator,
    ToolCallEvaluator,
    _classify_tool_error,
    _format_info_value,
    _parse_structured_response,
    build_production_registry,
)


class _NullSessionCtx:
    """Stand-in for ``_open_session()`` in unit tests that mock the tool body."""
    async def __aenter__(self): return None
    async def __aexit__(self, exc_type, exc, tb): return False


def _null_open_session():
    return _NullSessionCtx()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_request(
    *,
    tool_id: str = "stub:x",
    flow_id: int = 7,
    equation_key: str = "r/tool$0",
    phase_path: list[str] | None = None,
    resolved_inputs: dict | None = None,
    params: dict | None = None,
    seed: int | None = 42,
) -> EvaluationRequest:
    return EvaluationRequest(
        equation_key=equation_key,
        equation_type="tool_call",
        attempt=1,
        definition={
            "tool_id": tool_id,
            "params": params or {},
            "definition_hash": "deadbeef",
        },
        resolved_inputs=resolved_inputs or {"prompt": "a kitten"},
        seed=seed,
        flow_id=flow_id,
        phase_path=list(phase_path or ["Stage 1"]),
    )


def _llm_request(
    *,
    prompt_template: str,
    prompt_bindings: dict | None = None,
    response_format=None,
    system_template: str = "",
    images: Any = None,
) -> EvaluationRequest:
    resolved: dict = {}
    if prompt_bindings:
        resolved["prompt"] = prompt_bindings
    if images is not None:
        resolved["images"] = images
    return EvaluationRequest(
        equation_key="r/llm$0",
        equation_type="llm_call",
        attempt=1,
        definition={
            "model": "stub",
            "prompt_template": prompt_template,
            "system_template": system_template,
            "response_format": response_format,
            "definition_hash": "deadbeef",
        },
        resolved_inputs=resolved,
        flow_id=1,
        phase_path=[],
    )


def _code_request(source: str, inputs: dict | None = None) -> EvaluationRequest:
    return EvaluationRequest(
        equation_key="r/code$0",
        equation_type="code",
        attempt=1,
        definition={
            "source": source,
            "output_type": "json",
            "static_inputs": {},
            "definition_hash": "deadbeef",
        },
        resolved_inputs={"inputs": inputs or {}},
        flow_id=1,
        phase_path=[],
    )


# ---------------------------------------------------------------------------
# Tool call evaluator
# ---------------------------------------------------------------------------


class TestToolCallEvaluator:
    @pytest.mark.asyncio
    async def test_single_generation_returns_media_id_and_tags(self):
        captured: dict = {"tag_args": None}

        async def fake_run(tool_id, inputs, *, seed, project_id=None):
            assert tool_id == "stub:x"
            assert inputs["prompt"] == "a kitten"
            assert inputs["width"] == 768  # merged static param
            assert seed == 42
            return {"media_id": 101, "path": "/tmp/x.png"}

        async def fake_tag(media_ids, *, flow_id, equation_key, phase_path):
            captured["tag_args"] = {
                "media_ids": media_ids,
                "flow_id": flow_id,
                "equation_key": equation_key,
                "phase_path": phase_path,
            }

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=fake_tag)
        result = await ev(_tool_request(params={"width": 768}))

        assert result.value == 101
        assert result.media_ids == [101]
        assert captured["tag_args"] == {
            "media_ids": [101],
            "flow_id": 7,
            "equation_key": "r/tool$0",
            "phase_path": ["Stage 1"],
        }

    @pytest.mark.asyncio
    async def test_missing_tool_id_raises_tool_error(self):
        async def fake_run(*args, **kwargs):
            pytest.fail("should not be called")

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        req = _tool_request()
        req.definition.pop("tool_id")

        with pytest.raises(EvaluatorError) as ei:
            await ev(req)
        assert ei.value.category == TOOL_ERROR

    @pytest.mark.asyncio
    async def test_tag_failure_does_not_fail_equation(self):
        async def fake_run(tool_id, inputs, *, seed, project_id=None):
            return {"media_id": 5, "path": "/x"}

        async def boom_tag(*args, **kwargs):
            raise RuntimeError("library DB fell over")

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=boom_tag)
        result = await ev(_tool_request())
        # The generation succeeded; tagging is best-effort.
        assert result.media_ids == [5]

    @pytest.mark.asyncio
    async def test_transient_network_error_reraises_as_transient(self):
        async def fake_run(*args, **kwargs):
            raise ConnectionError("connection reset")

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_tool_request())
        assert ei.value.category == TRANSIENT

    @pytest.mark.asyncio
    async def test_rate_limit_string_classified_transient(self):
        async def fake_run(*args, **kwargs):
            raise RuntimeError("Rate limit exceeded, try again")

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_tool_request())
        assert ei.value.category == TRANSIENT

    @pytest.mark.asyncio
    async def test_resource_error_classified_resource(self):
        async def fake_run(*args, **kwargs):
            raise RuntimeError("Insufficient funds / credits exhausted")

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_tool_request())
        assert ei.value.category == RESOURCE_ERROR

    @pytest.mark.asyncio
    async def test_safety_filter_classified_tool_error(self):
        async def fake_run(*args, **kwargs):
            raise RuntimeError("Content filter: prompt refused by safety policy")

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        with pytest.raises(EvaluatorError) as ei:
            await ev(_tool_request())
        assert ei.value.category == TOOL_ERROR

    @pytest.mark.asyncio
    async def test_project_id_from_request_reaches_run_tool(self):
        captured: list[int | None] = []

        async def fake_run(tool_id, inputs, *, seed, project_id=None):
            captured.append(project_id)
            return {"media_id": 1, "path": "/tmp/x.png"}

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        req = _tool_request()
        req.project_id = 77
        await ev(req)
        assert captured == [77]

    @pytest.mark.asyncio
    async def test_promoted_search_rows_are_unwrapped_for_tool_media_inputs(self):
        captured: dict[str, Any] = {}

        async def fake_run(tool_id, inputs, *, seed, project_id=None):
            captured.update(inputs)
            return {"media_id": 9, "path": "/tmp/out.png"}

        ev = ToolCallEvaluator(run_tool=fake_run, tag_media=_noop_tag)
        await ev(_tool_request(
            resolved_inputs={
                "prompt": "cartoon dog",
                "input_images": [
                    {
                        "title": "Selected",
                        "image_url": "https://example.com/dog.jpg",
                        "media_id": 42,
                        "media": {
                            "type": "library_media",
                            "media_id": 42,
                            "source_url": "https://example.com/dog.jpg",
                        },
                    }
                ],
            },
        ))

        assert captured["input_images"] == [42]


class TestRunSingleToolJob:
    """_run_single_tool_job hands the flat DSL kwargs straight through as a
    single ``parameters`` namespace — there is no input/parameters split.
    """

    @pytest.mark.asyncio
    async def test_flat_kwargs_pass_through_as_parameters(self, monkeypatch):
        from contextlib import asynccontextmanager
        import flow_runtime.production_evaluators as pe

        captured: dict[str, Any] = {}

        async def fake_execute(tool_id, parameters=None, **kwargs):
            captured["tool_id"] = tool_id
            captured["parameters"] = parameters
            captured["kwargs"] = kwargs
            return {"media_id": 1, "path": "/tmp/x.png"}

        @asynccontextmanager
        async def fake_session():
            yield object()

        monkeypatch.setattr("agent.v2.tools.call_tool.execute_call_tool", fake_execute)
        monkeypatch.setattr(pe, "_open_session", fake_session)

        await pe._run_single_tool_job(
            "fake:upscaler",
            {"input_image": 42, "resolution": 3200, "color_correction": "lab"},
            seed=7,
            project_id=99,
        )

        assert captured["tool_id"] == "fake:upscaler"
        assert captured["parameters"] == {
            "input_image": 42, "resolution": 3200, "color_correction": "lab", "seed": 7,
        }
        assert captured["kwargs"]["project_id"] == 99

    @pytest.mark.asyncio
    async def test_explicit_seed_is_not_overwritten(self, monkeypatch):
        from contextlib import asynccontextmanager
        import flow_runtime.production_evaluators as pe

        captured: dict[str, Any] = {}

        async def fake_execute(tool_id, parameters=None, **kwargs):
            captured["parameters"] = parameters
            return {"media_id": 1, "path": "/tmp/x.png"}

        @asynccontextmanager
        async def fake_session():
            yield object()

        monkeypatch.setattr("agent.v2.tools.call_tool.execute_call_tool", fake_execute)
        monkeypatch.setattr(pe, "_open_session", fake_session)

        await pe._run_single_tool_job(
            "fake:tool", {"prompt": "x", "seed": 123}, seed=999,
        )
        # a seed already in the kwargs wins over the derived per-job seed
        assert captured["parameters"]["seed"] == 123


async def _noop_tag(*args, **kwargs):
    return None


# ---------------------------------------------------------------------------
# LLM evaluator
# ---------------------------------------------------------------------------


class TestLLMEvaluator:
    @pytest.mark.asyncio
    async def test_plain_text_returns_raw_content(self):
        async def fake_resolve_config(role):
            return SimpleNamespace(model=role)

        async def fake_completion(config, messages, **kwargs):
            # Echo the prompt back — we only care about the render here.
            assert messages[0]["role"] == "user"
            return SimpleNamespace(content="hello world")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        result = await ev(_llm_request(prompt_template="say hi"))
        assert result.value == "hello world"

    @pytest.mark.asyncio
    async def test_template_renders_bindings(self):
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured["user"] = messages[-1]["content"]
            return SimpleNamespace(content='{"x": 1}')

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        await ev(
            _llm_request(
                prompt_template="hello {0}",
                prompt_bindings={"0": "world"},
            )
        )
        assert captured["user"] == "hello world"

    @pytest.mark.asyncio
    async def test_response_format_parses_json(self):
        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            return SimpleNamespace(content='{"title": "ok", "items": [1, 2]}')

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        result = await ev(
            _llm_request(
                prompt_template="give me json",
                response_format={"type": "object"},
            )
        )
        assert result.value == {"title": "ok", "items": [1, 2]}

    @pytest.mark.asyncio
    async def test_response_format_adds_json_instruction_to_prompt(self):
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured["messages"] = messages
            return SimpleNamespace(content='{"prompt": "ok"}')

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        result = await ev(
            _llm_request(
                prompt_template="generate a prompt",
                response_format={"schema": {"prompt": "str"}},
            )
        )

        user_content = captured["messages"][-1]["content"]
        assert "Return ONLY valid JSON" in user_content
        assert '"prompt": "str"' in user_content
        assert result.value == {"prompt": "ok"}

    @pytest.mark.asyncio
    async def test_response_format_rejects_invalid_json_as_llm_error(self):
        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            return SimpleNamespace(content="not json at all")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        with pytest.raises(EvaluatorError) as ei:
            await ev(
                _llm_request(
                    prompt_template="",
                    response_format={"type": "object"},
                )
            )
        assert ei.value.category == LLM_ERROR

    @pytest.mark.asyncio
    async def test_fenced_json_is_accepted(self):
        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            return SimpleNamespace(content="```json\n{\"k\": 1}\n```")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        result = await ev(
            _llm_request(prompt_template="", response_format="object")
        )
        assert result.value == {"k": 1}

    @pytest.mark.asyncio
    async def test_think_default_disables_thinking(self):
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content="ok")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        await ev(_llm_request(prompt_template="hi"))
        assert captured["extra_body"] == {
            "chat_template_kwargs": {"enable_thinking": False},
        }
        assert "thinking" not in captured

    @pytest.mark.asyncio
    async def test_think_true_enables_thinking(self):
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content="ok")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        req = _llm_request(prompt_template="hi")
        req.definition["think"] = True
        await ev(req)
        assert captured["extra_body"] == {
            "chat_template_kwargs": {"enable_thinking": True},
        }
        assert captured["thinking"] == {"type": "enabled", "budget_tokens": 1024}

    @pytest.mark.asyncio
    async def test_images_single_media_id_builds_vision_content(self):
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured["messages"] = messages
            return SimpleNamespace(content="it's a cat")

        async def fake_resolve_image(media_id: int):
            assert media_id == 101
            return b"\x89PNG\r\n\x1a\nfake", "image/png"

        ev = LLMEvaluator(
            completion=fake_completion,
            resolve_config=fake_resolve_config,
            resolve_image=fake_resolve_image,
        )
        result = await ev(_llm_request(prompt_template="describe", images=101))
        assert result.value == "it's a cat"

        # User message is a content-block list with text + one image_url.
        user = captured["messages"][-1]
        assert user["role"] == "user"
        assert isinstance(user["content"], list)
        assert user["content"][0] == {"type": "text", "text": "describe"}
        assert user["content"][1]["type"] == "image_url"
        expected_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
        assert user["content"][1]["image_url"]["url"] == (
            f"data:image/png;base64,{expected_b64}"
        )

    @pytest.mark.asyncio
    async def test_images_list_attaches_every_block_in_order(self):
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured["messages"] = messages
            return SimpleNamespace(content="candidate 2")

        seen: list[int] = []

        async def fake_resolve_image(media_id: int):
            seen.append(media_id)
            return f"bytes-{media_id}".encode(), "image/jpeg"

        ev = LLMEvaluator(
            completion=fake_completion,
            resolve_config=fake_resolve_config,
            resolve_image=fake_resolve_image,
        )
        await ev(_llm_request(prompt_template="pick one", images=[7, 8, 9]))
        # Order preserved — important for "best of N" prompts referring to
        # candidates by index.
        assert seen == [7, 8, 9]
        user = captured["messages"][-1]
        blocks = user["content"][1:]
        assert [b["type"] for b in blocks] == ["image_url"] * 3

    @pytest.mark.asyncio
    async def test_images_none_sends_plain_text_user_message(self):
        """No images= → content stays a bare string, matching text-only path."""
        captured: dict = {}

        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            captured["messages"] = messages
            return SimpleNamespace(content="ok")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        await ev(_llm_request(prompt_template="hi"))
        user = captured["messages"][-1]
        assert user["content"] == "hi"

    @pytest.mark.asyncio
    async def test_image_load_failure_raises_resource_error(self):
        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            raise AssertionError("should not reach completion when load fails")

        async def fake_resolve_image(media_id: int):
            raise FileNotFoundError(f"media {media_id} missing")

        ev = LLMEvaluator(
            completion=fake_completion,
            resolve_config=fake_resolve_config,
            resolve_image=fake_resolve_image,
        )
        with pytest.raises(EvaluatorError) as ei:
            await ev(_llm_request(prompt_template="describe", images=999))
        assert ei.value.category == RESOURCE_ERROR

    @pytest.mark.asyncio
    async def test_non_int_image_binding_raises_llm_error(self):
        """Defense in depth: evaluator rejects a malformed binding even if
        the DSL layer was bypassed. Media IDs are ints at this layer."""
        async def fake_resolve_config(role):
            return object()

        async def fake_completion(config, messages, **kwargs):
            raise AssertionError("should not reach completion")

        ev = LLMEvaluator(
            completion=fake_completion, resolve_config=fake_resolve_config,
        )
        with pytest.raises(EvaluatorError) as ei:
            await ev(_llm_request(prompt_template="x", images="/tmp/c.png"))
        assert ei.value.category == LLM_ERROR


class TestParseStructuredResponse:
    """Unit-level coverage for the JSON parser so category mapping stays tight."""

    def test_none_format_returns_raw(self):
        assert _parse_structured_response("hello", None) == "hello"

    def test_empty_content_errors_as_llm_error(self):
        with pytest.raises(EvaluatorError) as ei:
            _parse_structured_response("", {"type": "object"})
        assert ei.value.category == LLM_ERROR


# ---------------------------------------------------------------------------
# Code evaluator
# ---------------------------------------------------------------------------


class TestCodeEvaluator:
    @pytest.mark.asyncio
    async def test_runs_snippet_with_bound_inputs(self):
        ev = CodeEvaluator()
        result = await ev(_code_request("return a + b", inputs={"a": 2, "b": 5}))
        assert result.value == 7

    @pytest.mark.asyncio
    async def test_snippet_exception_maps_to_code_error(self):
        # Exception is in the agent-sandbox safe builtins; user code can
        # raise it directly. Specialised exception classes (ValueError, etc.)
        # are not — the snippet would fail with NameError instead, which is
        # still categorised as CODE_ERROR.
        ev = CodeEvaluator()
        with pytest.raises(EvaluatorError) as ei:
            await ev(_code_request("raise Exception('boom')"))
        assert ei.value.category == CODE_ERROR
        assert "boom" in str(ei.value)

    @pytest.mark.asyncio
    async def test_name_error_classified_code_error(self):
        ev = CodeEvaluator()
        with pytest.raises(EvaluatorError) as ei:
            await ev(_code_request("return undefined_name"))
        assert ei.value.category == CODE_ERROR

    @pytest.mark.asyncio
    async def test_injected_run_snippet_is_used(self):
        async def fake_snippet(source, inputs, *, workspace_dir=None):
            return {"source_len": len(source), "inputs_keys": sorted(inputs)}

        ev = CodeEvaluator(run_snippet=fake_snippet)
        result = await ev(_code_request("x+1", inputs={"x": 10}))
        assert result.value == {"source_len": 3, "inputs_keys": ["x"]}


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


class TestClassifyToolError:
    def test_network_to_transient(self):
        assert _classify_tool_error("Network is unreachable") == TRANSIENT

    def test_http_502_to_transient(self):
        assert _classify_tool_error("upstream 502 Bad Gateway") == TRANSIENT

    def test_credits_to_resource(self):
        assert _classify_tool_error("quota exceeded for workspace") == RESOURCE_ERROR

    def test_safety_to_tool_error(self):
        assert _classify_tool_error("blocked by content filter") == TOOL_ERROR

    def test_unknown_defaults_to_tool_error(self):
        assert _classify_tool_error("something weird happened") == TOOL_ERROR


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestBuildProductionRegistry:
    def test_resolves_all_three_keys(self):
        reg = build_production_registry()
        assert reg.resolve("tool_call") is not None
        assert reg.resolve("llm_call") is not None
        assert reg.resolve("code") is not None

    def test_overrides_are_respected(self):
        async def stub_tool(req):
            return EvaluationResult(value="stub")

        reg = build_production_registry(tool_evaluator=stub_tool)
        assert reg.resolve("tool_call") is stub_tool
        # Others still default.
        assert reg.resolve("code") is not stub_tool

    def test_unregistered_hitl_lookup_raises(self):
        reg = build_production_registry()
        # HITL is the engine's responsibility, not the registry's — so the
        # registry deliberately does not have an entry. Resolving hitl
        # should raise KeyError (consistent with the base registry contract).
        with pytest.raises(KeyError):
            reg.resolve("hitl", hitl_type="select")


# ---------------------------------------------------------------------------
# Integration — runtime runs a flow end-to-end with mocked tool provider
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_store_and_db():
    """Mirrors the Phase 3 test fixture — fresh state.db + equation store."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "state.db"
        create_flow_state_db(db_path)
        store = EquationStore(root / "store")
        store.initialize()
        yield root, db_path, store


@pytest.mark.asyncio
async def test_runtime_runs_tool_then_code_via_production_registry(
    isolated_store_and_db, monkeypatch,
):
    """A flow with tool() + code() runs through FlowRuntime wired with
    the production registry, with provider + sandbox mocked.

    Catches the registry-wiring regression: the engine's EvaluationRequest
    shape, the tool-id resolution path, and the code-sandbox glue all have
    to agree. The only things mocked are the external services the user
    isn't asking us to re-test (generation queue, sandbox entry).
    """
    _root, state_db, store = isolated_store_and_db

    # The DSL validates tool IDs against the STP registry when available —
    # short-circuit that lookup so `tool("stub:gen", task_type="text-to-image", ...)` is accepted.
    import flow_dsl.primitives as primitives
    monkeypatch.setattr(primitives, "_tool_id_is_known", lambda tid: True)

    # The CodeEvaluator's media-input resolver hits the library DB to wrap
    # media-shape inputs in Media() objects; the integration test isn't a
    # library setup so stub the loader to a fake row, and skip the duration
    # lookup that also touches the DB.
    import flow_runtime.production_evaluators as prod_evals
    async def fake_load_media_row(media_id):
        return ("png", f"/tmp/{media_id}.png")
    async def fake_compute_duration_ms(media_ids):
        return None
    monkeypatch.setattr(prod_evals, "_load_media_row", fake_load_media_row)
    monkeypatch.setattr(prod_evals, "_extract_compute_duration_ms", fake_compute_duration_ms)

    async def fake_run(tool_id, inputs, *, seed, project_id=None):
        # The integration test cares that the flow_id-bound inputs flow
        # through unchanged, not that the provider works correctly.
        return {"media_id": 42, "path": "/tmp/42.png"}

    tag_calls: list[dict] = []

    async def fake_tag(media_ids, *, flow_id, equation_key, phase_path):
        tag_calls.append(
            {
                "media_ids": list(media_ids),
                "flow_id": flow_id,
                "equation_key": equation_key,
                "phase_path": list(phase_path),
            }
        )

    registry = build_production_registry(
        tool_evaluator=ToolCallEvaluator(run_tool=fake_run, tag_media=fake_tag),
        # Keep the real CodeEvaluator — it's the one we're exercising.
    )

    @dsl_flow(name="integration")
    def prog():
        with dsl_phase("Run"):
            m = dsl_tool("stub:gen", task_type="text-to-image", prompt="p")
            # `media_id` arrives wrapped as a Media object since the tool's
            # output shape is media — unwrap with int() before the math.
            return dsl_code("return int(media_id) + 1", inputs={"media_id": m})

    runtime = FlowRuntime(
        flow_id=999,
        state_db_path=state_db,
        flow_callable=prog,
        evaluators=registry,
        store=store,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=5.0)

        rows = {r["equation_key"]: r for r in graph_db.load_equation_rows(state_db)}
        tool_key = next(k for k in rows if "tool$0" in k)
        code_key = next(k for k in rows if "code$0" in k)
        assert rows[tool_key]["status"] == "completed"
        assert rows[code_key]["status"] == "completed"

        # code() read media_id=42, returned 43 (proves the input binding
        # reached the sandbox + the value flowed downstream).
        code_result = json.loads(rows[code_key]["result"]) if rows[code_key]["result"] else None
        assert code_result == 43

        # Tagging fired once for the tool equation, with flow_id=999 piped
        # through from the runtime config.
        assert len(tag_calls) == 1
        call = tag_calls[0]
        assert call["media_ids"] == [42]
        assert call["flow_id"] == 999
        assert "tool$0" in call["equation_key"]
    finally:
        await runtime.stop()


# ---------------------------------------------------------------------------
# Integration — _tag_media_with_flow writes to the real library DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tag_media_with_flow_writes_expected_metadata(
    test_app, db_session,
):
    """End-to-end write of the flow tag onto a MediaItem row.

    Uses the standard test app fixture (which sets up the library DB, profile
    context, etc.) so ``_open_session()`` resolves to the test database.
    """
    from tests.helpers.media import create_media_item, generate_test_image
    from flow_runtime.production_evaluators import _tag_media_with_flow

    # Seed one media item with pre-existing generation_metadata so we can
    # verify the merge (we keep old keys) rather than overwrite.
    async with db_session() as session:
        img_path = Path(tempfile.gettempdir()) / "flow_tag_test.png"
        generate_test_image(img_path)
        media = await create_media_item(
            session,
            file_path=img_path,
            generation_metadata=json.dumps(
                {"source": "stimma", "tool_id": "stub:x", "prompt": "p"}
            ),
        )
        await session.commit()
        media_id = media.id

    await _tag_media_with_flow(
        [media_id],
        flow_id=123,
        equation_key="r/tool$0",
        phase_path=["Stage 1", "Sub"],
    )

    async with db_session() as session:
        from database import MediaItem
        from sqlalchemy import select

        row = (
            await session.execute(
                select(MediaItem).where(MediaItem.id == media_id)
            )
        ).scalar_one()
        meta = json.loads(row.generation_metadata)
        assert meta["source"] == "flow"
        assert meta["flow_id"] == 123
        assert meta["equation_key"] == "r/tool$0"
        assert meta["phase_path"] == ["Stage 1", "Sub"]
        # Prior keys preserved.
        assert meta["tool_id"] == "stub:x"
        assert meta["prompt"] == "p"


# ---------------------------------------------------------------------------
# FlowRuntime threads project_id into the evaluator pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_threads_project_id_into_tool_evaluator(
    isolated_store_and_db, monkeypatch,
):
    """``FlowRuntime(project_id=...)`` must land in the EvaluationRequest so
    the tool evaluator can pass it down to the generation job, which is how
    flow-generated media gets attached to the owning project.
    """
    _root, state_db, store = isolated_store_and_db

    import flow_dsl.primitives as primitives
    monkeypatch.setattr(primitives, "_tool_id_is_known", lambda tid: True)

    captured_project_ids: list[int | None] = []

    async def fake_run(tool_id, inputs, *, seed, project_id=None):
        captured_project_ids.append(project_id)
        return {"media_id": 7, "path": "/tmp/7.png"}

    async def fake_tag(*args, **kwargs):
        return None

    registry = build_production_registry(
        tool_evaluator=ToolCallEvaluator(run_tool=fake_run, tag_media=fake_tag),
    )

    @dsl_flow(name="proj-threaded")
    def prog():
        with dsl_phase("Generate"):
            return dsl_tool("stub:gen", task_type="text-to-image", prompt="p")

    runtime = FlowRuntime(
        flow_id=1234,
        state_db_path=state_db,
        flow_callable=prog,
        evaluators=registry,
        store=store,
        project_id=555,
    )
    runtime.build_initial_graph()
    await runtime.start()
    try:
        await runtime.wait_quiescent(timeout=5.0)
    finally:
        await runtime.stop()

    assert captured_project_ids == [555]


# ---------------------------------------------------------------------------
# Assembly evaluators propagate project_id to their agent-tool wrappers
# ---------------------------------------------------------------------------


class TestCreateSetEvaluator:
    @pytest.mark.asyncio
    async def test_passes_project_id_to_assemble_set(self, monkeypatch):
        captured: dict = {}

        async def fake_assemble_set(**kwargs):
            captured.update(kwargs)
            return "Created set <result media_id=501 />"

        import agent.v2.tools.assemble_set as assemble_set_mod
        monkeypatch.setattr(assemble_set_mod, "assemble_set", fake_assemble_set)
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            _null_open_session,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        req = EvaluationRequest(
            equation_key="r/create_set$0",
            equation_type="create_set",
            attempt=1,
            definition={"title": "my set", "description": ""},
            resolved_inputs={"items": [1, 2, 3]},
            flow_id=None,  # skips the explode-prior-assembly DB path
            project_id=900,
        )
        result = await CreateSetEvaluator()(req)

        assert result.value == 501
        assert captured["project_id"] == 900
        assert captured["media_ids"] == [1, 2, 3]


class TestCreateGridEvaluator:
    @pytest.mark.asyncio
    async def test_passes_project_id_to_create_parameter_sweep(self, monkeypatch):
        captured: dict = {}

        async def fake_sweep(**kwargs):
            captured.update(kwargs)
            return "Created grid <result media_id=601 />"

        import agent.v2.tools.assemble_grid as assemble_grid_mod
        monkeypatch.setattr(assemble_grid_mod, "create_parameter_sweep", fake_sweep)
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            _null_open_session,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        req = EvaluationRequest(
            equation_key="r/create_grid$0",
            equation_type="create_grid",
            attempt=1,
            definition={
                "title": "g",
                "description": "",
                "rows": 2,
                "cols": 2,
                "row_headers": ["r1", "r2"],
                "col_headers": ["c1", "c2"],
            },
            resolved_inputs={"items": [1, 2, 3, 4]},
            flow_id=None,
            project_id=901,
        )
        result = await CreateGridEvaluator()(req)

        assert result.value == 601
        assert captured["project_id"] == 901
        assert captured["rows"] == 2
        assert captured["cols"] == 2


class TestCreateDocumentEvaluator:
    @pytest.mark.asyncio
    async def test_passes_project_id_to_save_document_media(self, monkeypatch):
        captured: dict = {}

        async def fake_save(*, title, content, fmt, project_id=None):
            captured["title"] = title
            captured["content"] = content
            captured["fmt"] = fmt
            captured["project_id"] = project_id
            return 702

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_document_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        req = EvaluationRequest(
            equation_key="r/create_document$0",
            equation_type="create_document",
            attempt=1,
            definition={
                "title": "notes",
                "format": "markdown",
                "static_content": "# hi",
            },
            resolved_inputs={},
            flow_id=None,
            project_id=902,
        )
        result = await CreateDocumentEvaluator()(req)

        assert result.value == 702
        assert captured["project_id"] == 902
        assert captured["title"] == "notes"
        assert captured["content"] == "# hi"
        assert captured["fmt"] == "markdown"


class TestCreateImageEvaluator:
    @pytest.mark.asyncio
    async def test_invokes_callable_with_pil_inputs_and_saves(self, monkeypatch, tmp_path):
        from PIL import Image as _Image

        from flow_dsl.shapes import ListShape, Scalar
        from flow_runtime.graph import NodeRef
        from flow_runtime.media_arg import Media
        from flow_runtime.production_evaluators import (
            CreateImageEvaluator,
        )

        captured: dict = {}

        # Stage real PNGs on disk so Media.pil can open them.
        file_paths = {}
        for mid in (11, 22):
            p = tmp_path / f"{mid}.png"
            _Image.new("RGB", (4, 4), color=(mid, 0, 0)).save(p, format="PNG")
            file_paths[mid] = str(p)

        async def fake_row(media_id: int):
            captured.setdefault("looked_up", []).append(media_id)
            return ("png", file_paths[media_id])

        async def fake_save(*, img, title, fmt, project_id=None, source_media_ids=None):
            captured["img_size"] = img.size
            captured["title"] = title
            captured["fmt"] = fmt
            captured["project_id"] = project_id
            captured["source_media_ids"] = list(source_media_ids or [])
            return 801

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._load_media_row",
            fake_row,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_pil_image_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def compose(imgs):
            # imgs arrives as list[Media]. Access .pil for pixels, .id for
            # the library id, .filename for an HTML-safe name.
            assert all(isinstance(m, Media) for m in imgs)
            w, h = imgs[0].pil.size
            canvas = _Image.new("RGB", (w * 2, h))
            canvas.paste(imgs[0].pil, (0, 0))
            canvas.paste(imgs[1].pil, (w, 0))
            return canvas

        upstream_ref = NodeRef(
            equation_key="r/up$0",
            collection=True,
            shape=ListShape(element=Scalar(kind="media")),
        )

        req = EvaluationRequest(
            equation_key="r/create_image$0",
            equation_type="create_image",
            attempt=1,
            definition={
                "fn": compose,
                "source": "compose",
                "title": "pane",
                "description": "",
                "format": "png",
                "_dynamic": {"inputs": {"imgs": upstream_ref}},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {"imgs": [11, 22]}},
            flow_id=None,
            project_id=903,
        )
        result = await CreateImageEvaluator()(req)

        assert result.value == 801
        assert captured["looked_up"] == [11, 22]
        assert captured["img_size"] == (8, 4)
        assert captured["title"] == "pane"
        assert captured["fmt"] == "png"
        assert captured["project_id"] == 903
        assert captured["source_media_ids"] == [11, 22]

    @pytest.mark.asyncio
    async def test_rejects_non_pil_return(self, monkeypatch):
        from flow_runtime.production_evaluators import (
            CreateImageEvaluator,
        )
        from flow_runtime.evaluators import EvaluatorError

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def bad_fn():
            return "not a PIL image"

        req = EvaluationRequest(
            equation_key="r/create_image$0",
            equation_type="create_image",
            attempt=1,
            definition={
                "fn": bad_fn,
                "source": "bad_fn",
                "title": "",
                "description": "",
                "format": "png",
                "_dynamic": {},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {}},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError):
            await CreateImageEvaluator()(req)

    @pytest.mark.asyncio
    async def test_callable_exception_includes_line_numbered_traceback(
        self, monkeypatch, tmp_path
    ):
        """Agent-facing CODE_ERROR must carry a traceback with user line numbers.

        Before the fix the evaluator captured only ``type(exc).__name__: exc``,
        which gives the agent an error like
        ``AttributeError: 'int' object has no attribute 'resize'`` with no
        indication of *which* line raised — and nothing to debug against.

        The callable is compiled from a throwaway source file outside the
        backend tree so its frame survives the traceback filter (which drops
        stimma internals, stdlib, and site-packages noise).
        """
        from flow_runtime.production_evaluators import CreateImageEvaluator

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        program = tmp_path / "program.py"
        program.write_text(
            "def make_windowpane(imgs):\n"
            "    return imgs[0].resize((1, 1))\n"
        )
        ns: dict = {}
        exec(compile(program.read_text(), str(program), "exec"), ns)
        fn = ns["make_windowpane"]

        req = EvaluationRequest(
            equation_key="r/create_image$0",
            equation_type="create_image",
            attempt=1,
            definition={
                "fn": fn,
                "source": "make_windowpane",
                "title": "",
                "description": "",
                "format": "png",
                "_dynamic": {},
                "static_inputs": {},
            },
            # Passing raw ints (no dynamic binding, so no auto-resolve)
            # reproduces the user's ``'int' object has no attribute 'resize'``.
            resolved_inputs={"inputs": {"imgs": [11, 22]}},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError) as ei:
            await CreateImageEvaluator()(req)
        assert ei.value.category == CODE_ERROR
        msg = str(ei.value)
        assert "Traceback (most recent call last):" in msg
        assert "make_windowpane" in msg
        assert "program.py" in msg
        assert "line 2" in msg  # the .resize() line in the fake program
        assert "AttributeError" in msg

    @pytest.mark.asyncio
    async def test_unknown_element_list_with_int_values_loads_as_media(
        self, monkeypatch, tmp_path
    ):
        """Regression: foreach(...) returns list[UNKNOWN]; when the runtime
        values are media ids, ``create_image`` must still wrap them as Media
        objects so ``.pil`` resolves to a PIL image rather than leaving a
        raw int in user code.
        """
        from PIL import Image as _Image

        from flow_dsl.shapes import ListShape, UNKNOWN
        from flow_runtime.graph import NodeRef
        from flow_runtime.media_arg import Media
        from flow_runtime.production_evaluators import CreateImageEvaluator

        captured: dict = {}

        file_paths = {}
        for mid in (11, 22, 33, 44):
            p = tmp_path / f"{mid}.png"
            _Image.new("RGB", (4, 4), color=(mid, 0, 0)).save(p, format="PNG")
            file_paths[mid] = str(p)

        async def fake_row(media_id: int):
            captured.setdefault("looked_up", []).append(media_id)
            return ("png", file_paths[media_id])

        async def fake_save(*, img, title, fmt, project_id=None, source_media_ids=None):
            captured["img_count"] = len(img.getbands())
            captured["source_media_ids"] = list(source_media_ids or [])
            return 999

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._load_media_row",
            fake_row,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_pil_image_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def compose(imgs):
            # Every item must be a Media for this to succeed.
            assert all(isinstance(m, Media) for m in imgs), \
                f"auto-wrap didn't happen; got {[type(m).__name__ for m in imgs]}"
            return imgs[0].pil

        upstream_ref = NodeRef(
            equation_key="r/foreach$0",
            collection=True,
            shape=ListShape(element=UNKNOWN),
        )

        req = EvaluationRequest(
            equation_key="r/create_image$0",
            equation_type="create_image",
            attempt=1,
            definition={
                "fn": compose,
                "source": "compose",
                "title": "",
                "description": "",
                "format": "png",
                "_dynamic": {"inputs": {"imgs": upstream_ref}},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {"imgs": [11, 22, 33, 44]}},
            flow_id=None,
            project_id=None,
        )
        result = await CreateImageEvaluator()(req)
        assert result.value == 999
        assert captured["looked_up"] == [11, 22, 33, 44]
        assert captured["source_media_ids"] == [11, 22, 33, 44]

    @pytest.mark.asyncio
    async def test_unknown_element_list_with_non_int_values_passes_through(
        self, monkeypatch
    ):
        """The auto-wrap fallback only triggers when every value is an int
        (or ``{media_id: int}``) — a genuine list of strings/other data must
        pass through untouched so legitimate foreach-of-code() usage works.
        """
        from flow_dsl.shapes import ListShape, UNKNOWN
        from flow_runtime.graph import NodeRef
        from flow_runtime.production_evaluators import (
            _resolve_media_inputs_to_objects,
        )

        upstream_ref = NodeRef(
            equation_key="r/foreach$0",
            collection=True,
            shape=ListShape(element=UNKNOWN),
        )
        out, source_ids, staged = await _resolve_media_inputs_to_objects(
            resolved_inputs={"tags": ["a", "b", "c"]},
            dynamic_bindings={"tags": upstream_ref},
        )
        assert out == {"tags": ["a", "b", "c"]}
        assert staged == {}
        assert source_ids == []


class TestCreateLayoutEvaluator:
    @pytest.mark.asyncio
    async def test_callable_receives_staged_filenames_and_saves(
        self, monkeypatch, tmp_path
    ):
        from flow_dsl.shapes import Scalar
        from flow_runtime.graph import NodeRef
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        captured: dict = {}

        async def fake_stage(media_id: int, dest_path):
            dest_path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
            captured.setdefault("staged", []).append((media_id, dest_path.name))

        async def fake_lookup(media_id: int):
            # Simulate the DB lookup in _resolve_media_inputs_to_filenames.
            return ("png", f"/fake/path/{media_id}.png")

        async def fake_save(*, bundle_dir, title, description, project_id=None,
                            source_media_ids=None):
            captured["bundle_dir"] = bundle_dir
            captured["title"] = title
            captured["description"] = description
            captured["project_id"] = project_id
            captured["source_media_ids"] = list(source_media_ids or [])
            captured["index_html"] = (bundle_dir / "index.html").read_text()
            captured["staged_files"] = sorted(p.name for p in bundle_dir.iterdir())
            return 5000

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._stage_media_file_for_layout",
            fake_stage,
        )
        # Patch the _lookup_fmt closure by monkey-patching _open_session at a
        # higher level: since _resolve_media_inputs_to_filenames uses
        # _open_session directly, simulate via replacing MediaItem SELECT.
        # Easiest: patch _resolve_media_inputs_to_filenames's helper by
        # replacing select execution.
        from sqlalchemy.engine import Row

        class _FakeResult:
            def __init__(self, fmt, path):
                self._row = (fmt, path)
            def first(self):
                return self._row
            def scalar_one_or_none(self):
                return None

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def execute(self, stmt):
                # Return format + path for the media id lookup.
                return _FakeResult("png", "/fake/path.png")

        def _fake_open_session():
            return _FakeSession()

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            _fake_open_session,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_layout_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        from flow_runtime.media_arg import Media

        def render(title, hero):
            assert isinstance(hero, Media), f"hero should be Media, got {type(hero).__name__}"
            return f'<h1>{title}</h1><img src="{hero.filename}">'

        upstream_ref = NodeRef(
            equation_key="r/up$0",
            shape=Scalar(kind="media"),
        )

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": render,
                "source": "render",
                "title": "Product card",
                "description": "",
                "width": 1200,
                "height": 630,
                "_dynamic": {"inputs": {"hero": upstream_ref}},
                "static_inputs": {"title": "Summer sale"},
            },
            resolved_inputs={"inputs": {"title": "Summer sale", "hero": 42}},
            flow_id=None,
            project_id=707,
        )
        result = await CreateLayoutEvaluator()(req)

        assert result.value == 5000
        assert captured["title"] == "Product card"
        assert captured["project_id"] == 707
        assert captured["source_media_ids"] == [42]
        assert "hero.png" in captured["staged_files"]
        assert "index.html" in captured["staged_files"]
        assert 'data-stimma-width="1200"' in captured["index_html"]
        assert 'data-stimma-height="630"' in captured["index_html"]
        assert '<h1>Summer sale</h1>' in captured["index_html"]
        assert '<img src="hero.png">' in captured["index_html"]

    @pytest.mark.asyncio
    async def test_list_media_input_resolves_to_indexed_filenames(
        self, monkeypatch
    ):
        from flow_dsl.shapes import ListShape, Scalar
        from flow_runtime.graph import NodeRef
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        captured: dict = {}

        async def fake_stage(media_id: int, dest_path):
            dest_path.write_bytes(b"data")
            captured.setdefault("staged", []).append((media_id, dest_path.name))

        class _FakeResult:
            def first(self):
                return ("jpg", "/fake/x.jpg")

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def execute(self, stmt):
                return _FakeResult()

        async def fake_save(*, bundle_dir, title, description, project_id=None,
                            source_media_ids=None):
            captured["source_media_ids"] = list(source_media_ids or [])
            return 6000

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._stage_media_file_for_layout",
            fake_stage,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            lambda: _FakeSession(),
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_layout_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        from flow_runtime.media_arg import Media

        def render(panels):
            assert all(isinstance(p, Media) for p in panels)
            assert [p.filename for p in panels] == ["panels_0.jpg", "panels_1.jpg", "panels_2.jpg"]
            return "<div>" + "".join(f'<img src="{p.filename}">' for p in panels) + "</div>"

        upstream_ref = NodeRef(
            equation_key="r/up$0",
            collection=True,
            shape=ListShape(element=Scalar(kind="media")),
        )

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": render,
                "source": "render",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {"inputs": {"panels": upstream_ref}},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {"panels": [100, 200, 300]}},
            flow_id=None,
            project_id=None,
        )
        result = await CreateLayoutEvaluator()(req)
        assert result.value == 6000
        staged_names = [name for _, name in captured["staged"]]
        assert staged_names == ["panels_0.jpg", "panels_1.jpg", "panels_2.jpg"]
        assert captured["source_media_ids"] == [100, 200, 300]

    @pytest.mark.asyncio
    async def test_height_none_emits_auto(self, monkeypatch):
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        captured: dict = {}

        async def fake_save(*, bundle_dir, title, description, project_id=None,
                            source_media_ids=None):
            captured["index_html"] = (bundle_dir / "index.html").read_text()
            return 7000

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_layout_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def render():
            return "<p>auto height</p>"

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": render,
                "source": "render",
                "title": "",
                "description": "",
                "width": 1200,
                "height": None,
                "_dynamic": {},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {}},
            flow_id=None,
            project_id=None,
        )
        result = await CreateLayoutEvaluator()(req)
        assert result.value == 7000
        assert 'data-stimma-height="auto"' in captured["index_html"]
        assert 'data-stimma-width="1200"' in captured["index_html"]

    @pytest.mark.asyncio
    async def test_rejects_non_str_return(self, monkeypatch):
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def bad_fn():
            return {"not": "html"}

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": bad_fn,
                "source": "bad_fn",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {}},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError) as ei:
            await CreateLayoutEvaluator()(req)
        assert ei.value.category == CODE_ERROR

    @pytest.mark.asyncio
    async def test_rejects_oversized_html(self, monkeypatch):
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def huge():
            return "x" * (3 * 1024 * 1024)  # 3 MB, over the 2 MB cap

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": huge,
                "source": "huge",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {}},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError) as ei:
            await CreateLayoutEvaluator()(req)
        assert ei.value.category == CODE_ERROR
        assert "MB" in str(ei.value)

    @pytest.mark.asyncio
    async def test_callable_exception_includes_traceback(
        self, monkeypatch, tmp_path
    ):
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        program = tmp_path / "layout_program.py"
        program.write_text(
            "def render_card():\n"
            "    return 'prefix' + 42  # TypeError: can only concatenate str (not \"int\") to str\n"
        )
        ns: dict = {}
        exec(compile(program.read_text(), str(program), "exec"), ns)
        fn = ns["render_card"]

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": fn,
                "source": "render_card",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {}},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError) as ei:
            await CreateLayoutEvaluator()(req)
        assert ei.value.category == CODE_ERROR
        msg = str(ei.value)
        assert "Traceback" in msg
        assert "render_card" in msg
        assert "layout_program.py" in msg

    @pytest.mark.asyncio
    async def test_rejects_html_with_unstaged_image_refs(self, monkeypatch):
        """Regression: agent interpolated a list[media] input as ``{avatar}``,
        which Python stringifies to ``"['avatar_0.jpg', ...]"`` and produced a
        broken <img src>. The evaluator must fail loudly with an actionable
        message instead of shipping a broken bundle.
        """
        from flow_dsl.shapes import ListShape, Scalar
        from flow_runtime.graph import NodeRef
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        async def fake_stage(media_id, dest_path):
            dest_path.write_bytes(b"data")

        class _FakeResult:
            def first(self):
                return ("png", "/fake/x.png")

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def execute(self, stmt):
                return _FakeResult()

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._stage_media_file_for_layout",
            fake_stage,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            lambda: _FakeSession(),
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def render(avatar):
            # avatar is a list of filenames; interpolating it stringifies the
            # whole list, producing a bogus src.
            return f'<img src="{avatar}">'

        upstream_ref = NodeRef(
            equation_key="r/up$0",
            collection=True,
            shape=ListShape(element=Scalar(kind="media")),
        )

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": render,
                "source": "render",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {"inputs": {"avatar": upstream_ref}},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {"avatar": [100, 200, 300]}},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError) as ei:
            await CreateLayoutEvaluator()(req)
        assert ei.value.category == CODE_ERROR
        msg = str(ei.value)
        assert "couldn't be resolved" in msg
        # The message should surface staged filenames so the agent can see
        # what it *should* reference.
        assert "avatar_0.png" in msg
        # And call out the list[media] pitfall + pairing pattern.
        assert "list[media]" in msg

    @pytest.mark.asyncio
    async def test_rescues_bare_int_ref_as_media_id(self, monkeypatch):
        """Regression: per-iteration ``foreach`` items reach the callable as
        raw ints (no shape info), so ``inputs={"avatar": 42}`` goes to
        static_inputs and the callable sees the int. Interpolating it as
        ``<img src="42">`` was an outright broken ref until the evaluator
        learned to look up bare-int refs post-hoc and stage the matching
        MediaItem.
        """
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        captured: dict = {}

        async def fake_stage(media_id, dest_path):
            dest_path.write_bytes(b"pngbytes")
            captured.setdefault("staged", []).append((media_id, dest_path.name))

        async def fake_lookup_info(media_id):
            return ("png", f"/fake/{media_id}.png")

        async def fake_save(*, bundle_dir, title, description, project_id=None,
                            source_media_ids=None):
            captured["index_html"] = (bundle_dir / "index.html").read_text()
            captured["source_media_ids"] = list(source_media_ids or [])
            captured["staged_files"] = sorted(p.name for p in bundle_dir.iterdir())
            return 6100

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._stage_media_file_for_layout",
            fake_stage,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._lookup_media_info",
            fake_lookup_info,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_layout_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def render(name, avatar):
            # avatar is a raw int (per-iteration foreach item, no shape info
            # on the binding). Interpolating it produces src="42".
            return f'<div><h1>{name}</h1><img src="{avatar}"></div>'

        # All inputs go through as static (no NodeRefs), which simulates the
        # common case of a foreach callback passing resolved values through
        # to create_layout.
        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": render,
                "source": "render",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {},
                "static_inputs": {"name": "Rian", "avatar": 42},
            },
            resolved_inputs={"inputs": {"name": "Rian", "avatar": 42}},
            flow_id=None,
            project_id=None,
        )
        result = await CreateLayoutEvaluator()(req)
        assert result.value == 6100
        # The bare-int ref ``42`` must be staged as ``media_42.png`` and the
        # HTML rewritten to reference it.
        assert "media_42.png" in captured["staged_files"]
        assert 'src="media_42.png"' in captured["index_html"]
        assert 'src="42"' not in captured["index_html"]
        # Lineage reflects the rescued media id.
        assert captured["source_media_ids"] == [42]

    @pytest.mark.asyncio
    async def test_lineage_only_includes_media_referenced_in_html(
        self, monkeypatch
    ):
        """Regression: a list[media] input with 3 files where the callable
        only references one must produce lineage with exactly that one media,
        not all three. The Lineage panel otherwise shows misleading inputs.
        """
        from flow_dsl.shapes import ListShape, Scalar
        from flow_runtime.graph import NodeRef
        from flow_runtime.production_evaluators import CreateLayoutEvaluator

        captured: dict = {}

        async def fake_stage(media_id, dest_path):
            dest_path.write_bytes(b"data")

        class _FakeResult:
            def first(self):
                return ("png", "/fake/x.png")

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def execute(self, stmt):
                return _FakeResult()

        async def fake_save(*, bundle_dir, title, description, project_id=None,
                            source_media_ids=None):
            captured["source_media_ids"] = list(source_media_ids or [])
            return 5500

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._stage_media_file_for_layout",
            fake_stage,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            lambda: _FakeSession(),
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_layout_media",
            fake_save,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        def render(panels):
            # All three files staged, but HTML only references the middle one.
            return f'<div><img src="{panels[1]}"></div>'

        upstream_ref = NodeRef(
            equation_key="r/up$0",
            collection=True,
            shape=ListShape(element=Scalar(kind="media")),
        )

        req = EvaluationRequest(
            equation_key="r/create_layout$0",
            equation_type="create_layout",
            attempt=1,
            definition={
                "fn": render,
                "source": "render",
                "title": "",
                "description": "",
                "width": 800,
                "height": 600,
                "_dynamic": {"inputs": {"panels": upstream_ref}},
                "static_inputs": {},
            },
            resolved_inputs={"inputs": {"panels": [100, 200, 300]}},
            flow_id=None,
            project_id=None,
        )
        result = await CreateLayoutEvaluator()(req)
        assert result.value == 5500
        # Only the media whose staged filename appears in the HTML should be
        # counted in lineage — not every file that got staged.
        assert captured["source_media_ids"] == [200]


class TestRasterizeLayoutEvaluator:
    @pytest.mark.asyncio
    async def test_rasterizes_layout_bundle_and_saves_png(self, monkeypatch):
        from PIL import Image as _Image
        from flow_runtime.production_evaluators import RasterizeLayoutEvaluator

        captured: dict = {}

        class _FakeMedia:
            id = 111
            file_path = "/tmp/fake.stimmalayout"
            file_format = "stimmalayout"
            raw_metadata = '{"title": "Card"}'

        class _FakeResult:
            def scalar_one_or_none(self):
                return _FakeMedia()

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def execute(self, stmt):
                return _FakeResult()

        async def fake_preview(path, size, *a, **kw):
            captured["path"] = path
            captured["size"] = size
            return _Image.new("RGB", (800, 600))

        async def fake_save_pil(*, img, title, fmt, project_id=None, source_media_ids=None):
            captured["img_size"] = img.size
            captured["title"] = title
            captured["fmt"] = fmt
            captured["project_id"] = project_id
            captured["source_media_ids"] = list(source_media_ids or [])
            return 9999

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            lambda: _FakeSession(),
        )
        monkeypatch.setattr(
            "routes.media_files._generate_layout_preview",
            fake_preview,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._save_pil_image_media",
            fake_save_pil,
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        req = EvaluationRequest(
            equation_key="r/rasterize_layout$0",
            equation_type="rasterize_layout",
            attempt=1,
            definition={"width": 1200, "_dynamic": {"layout": None}},
            resolved_inputs={"layout": 111},
            flow_id=None,
            project_id=808,
        )
        result = await RasterizeLayoutEvaluator()(req)
        assert result.value == 9999
        assert captured["path"] == "/tmp/fake.stimmalayout"
        assert captured["size"] == 1200
        assert captured["fmt"] == "png"
        assert captured["project_id"] == 808
        assert captured["source_media_ids"] == [111]
        assert captured["title"] == "Card"

    @pytest.mark.asyncio
    async def test_rejects_non_layout_input(self, monkeypatch):
        from flow_runtime.production_evaluators import RasterizeLayoutEvaluator

        class _FakeMedia:
            id = 222
            file_path = "/tmp/fake.png"
            file_format = "png"
            raw_metadata = None

        class _FakeResult:
            def scalar_one_or_none(self):
                return _FakeMedia()

        class _FakeSession:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return None
            async def execute(self, stmt):
                return _FakeResult()

        async def _noop_tag(*args, **kwargs):
            return None

        monkeypatch.setattr(
            "flow_runtime.production_evaluators._open_session",
            lambda: _FakeSession(),
        )
        monkeypatch.setattr(
            "flow_runtime.production_evaluators._tag_media_with_flow",
            _noop_tag,
        )

        req = EvaluationRequest(
            equation_key="r/rasterize_layout$0",
            equation_type="rasterize_layout",
            attempt=1,
            definition={"width": None, "_dynamic": {"layout": None}},
            resolved_inputs={"layout": 222},
            flow_id=None,
            project_id=None,
        )
        with pytest.raises(EvaluatorError) as ei:
            await RasterizeLayoutEvaluator()(req)
        assert "not a layout bundle" in str(ei.value) or "stimmalayout" in str(ei.value)


# ---------------------------------------------------------------------------
# InfoEvaluator
# ---------------------------------------------------------------------------


class TestFormatInfoValue:
    """Placeholder substitution must produce human-readable markdown — never
    Python repr (the bug that put ``['a', 'b']`` on a flow card).
    """

    def test_scalar_passes_through(self):
        assert _format_info_value("hello") == "hello"
        assert _format_info_value(42) == "42"
        assert _format_info_value(3.14) == "3.14"
        assert _format_info_value(None) == "None"

    def test_list_renders_as_bullets(self):
        out = _format_info_value(["a blue dog", "a green dog", "a pink dog"])
        assert out == "- a blue dog\n- a green dog\n- a pink dog"
        # No Python repr leakage
        assert "[" not in out
        assert "'" not in out

    def test_tuple_renders_as_bullets(self):
        out = _format_info_value(("first", "second"))
        assert out == "- first\n- second"

    def test_empty_list_renders_placeholder(self):
        assert _format_info_value([]) == "_(empty)_"

    def test_dict_renders_as_key_value_bullets(self):
        out = _format_info_value({"width": 1024, "height": 768})
        assert out == "- **width:** 1024\n- **height:** 768"

    def test_empty_dict_renders_placeholder(self):
        assert _format_info_value({}) == "_(empty)_"


class TestInfoEvaluator:
    def _info_request(
        self, *, template: str, inputs: dict[str, Any] | None = None
    ) -> EvaluationRequest:
        return EvaluationRequest(
            equation_key="r/info$0",
            equation_type="info",
            attempt=1,
            definition={"template": template},
            resolved_inputs={"inputs": inputs or {}},
            flow_id=None,
            project_id=None,
        )

    @pytest.mark.asyncio
    async def test_list_input_renders_as_markdown_bullets(self):
        req = self._info_request(
            template="Prompts ({n}):\n{prompts}",
            inputs={
                "n": 3,
                "prompts": [
                    "A blue dog is depicted in a cartoon style.",
                    "A green dog is depicted in a cartoon style.",
                    "A pink dog is depicted in a cartoon style.",
                ],
            },
        )
        result = await InfoEvaluator()(req)
        assert "[" not in result.value
        assert "'" not in result.value
        assert result.value == (
            "Prompts (3):\n"
            "- A blue dog is depicted in a cartoon style.\n"
            "- A green dog is depicted in a cartoon style.\n"
            "- A pink dog is depicted in a cartoon style."
        )

    @pytest.mark.asyncio
    async def test_scalar_input_unchanged(self):
        req = self._info_request(
            template="Mood: **{mood}**",
            inputs={"mood": "melancholic"},
        )
        result = await InfoEvaluator()(req)
        assert result.value == "Mood: **melancholic**"

    @pytest.mark.asyncio
    async def test_dict_input_renders_as_key_value(self):
        req = self._info_request(
            template="Settings:\n{settings}",
            inputs={"settings": {"width": 1024, "seed": 42}},
        )
        result = await InfoEvaluator()(req)
        assert result.value == (
            "Settings:\n- **width:** 1024\n- **seed:** 42"
        )

    @pytest.mark.asyncio
    async def test_missing_placeholder_raises_code_error(self):
        req = self._info_request(template="hi {missing}", inputs={})
        with pytest.raises(EvaluatorError) as ei:
            await InfoEvaluator()(req)
        assert ei.value.category == CODE_ERROR

    @pytest.mark.asyncio
    async def test_upstream_media_ids_propagate(self):
        req = EvaluationRequest(
            equation_key="r/info$0",
            equation_type="info",
            attempt=1,
            definition={"template": "done"},
            resolved_inputs={"inputs": {}, "__upstream_media_ids": [11, 22]},
            flow_id=None,
            project_id=None,
        )
        result = await InfoEvaluator()(req)
        assert result.value == "done"
        assert result.media_ids == [11, 22]

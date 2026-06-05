"""Shape-propagation validator tests.

Covers the v1 build-time checks from docs/RECIPES_SHAPE_VALIDATION.md:

- ``code()`` subscript access against an upstream ``llm(response_format=…)``
  dict: invalid keys flagged, valid keys pass through.
- Tool input-schema conformance: required missing, scalar-vs-array mismatch,
  well-formed calls pass.

These are the two highest-leverage runtime failures in agent-authored
programs — both are now caught at graph build time.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from recipe_dsl.errors import ProgramLoadError
from recipe_dsl.loader import build_graph_from_callable
from recipe_dsl.primitives import (
    code,
    foreach,
    hitl,
    input as dsl_input,
    llm,
    output as dsl_output,
    phase,
    recipe,
    tool,
)
from recipe_dsl.shapes import (
    DictShape,
    ListShape,
    Scalar,
    TupleShape,
    UNKNOWN,
    describe,
    find_bad_subscripts,
    parse_tool_param_expectations,
    shape_from_literal,
    shape_from_response_format,
    shape_from_type_string,
)


# =============================================================================
# Unit tests — shape inference
# =============================================================================


class TestShapeFromTypeString:
    def test_scalar(self):
        assert shape_from_type_string("str") == Scalar(kind="str")
        assert shape_from_type_string("media") == Scalar(kind="media")
        assert shape_from_type_string("int") == Scalar(kind="int")

    def test_list(self):
        assert shape_from_type_string("list[media]") == ListShape(
            element=Scalar(kind="media"),
        )
        assert shape_from_type_string("list[str]") == ListShape(
            element=Scalar(kind="str"),
        )

    def test_unknown_permissive(self):
        # Unknown types yield Unknown — never raises.
        s = shape_from_type_string("something-weird")
        assert s is UNKNOWN or s.__class__.__name__ == "Unknown"


class TestShapeFromResponseFormat:
    def test_no_format_is_string(self):
        assert shape_from_response_format(None) == Scalar(kind="str")

    def test_simplified_schema(self):
        shape = shape_from_response_format(
            {"type": "json", "schema": {"a": "str", "items": "list[str]"}},
        )
        assert isinstance(shape, DictShape)
        assert shape.closed is True
        fields = shape.field_map
        assert fields["a"] == Scalar(kind="str")
        assert fields["items"] == ListShape(element=Scalar(kind="str"))

    def test_jsonschema_properties(self):
        shape = shape_from_response_format(
            {
                "type": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            }
        )
        assert isinstance(shape, DictShape)
        fields = shape.field_map
        assert fields["name"] == Scalar(kind="str")
        assert fields["tags"] == ListShape(element=Scalar(kind="str"))


class TestTupleShape:
    def test_shape_from_literal_recognizes_tuple(self):
        shape = shape_from_literal((42, "hello"))
        assert isinstance(shape, TupleShape)
        assert shape.elements == (Scalar(kind="int"), Scalar(kind="str"))

    def test_describe_renders_tuple(self):
        shape = TupleShape(
            elements=(Scalar(kind="media"), Scalar(kind="str")),
        )
        assert describe(shape) == "tuple[media, str]"

    def test_zip_nodes_preserves_positional_source_order(self):
        # Regression: zip_nodes used to ``sorted({c.equation_key ...})`` for
        # its definition['sources'], which silently swapped per-tuple element
        # positions when the user-passed order didn't match alphabetical key
        # order. That meant zip_nodes(faces, prompts) would emit tuples
        # ordered (prompt, face) when 'code$0' sorted before 'hitl.approve$0',
        # and pair[0]/pair[1] readers got the wrong values.
        from recipe_dsl.context import BuildContext, activate_context, push_frame
        from recipe_dsl.primitives import zip_nodes
        from recipe_runtime.graph import EquationGraph

        def _faces():
            return [10, 11, 12]

        def _prompts():
            return ["x", "y", "z"]

        g = EquationGraph()
        ctx = BuildContext(g)
        with activate_context(ctx):
            with push_frame(
                ctx, parent_key="r", function_name="r", phase_stack=[],
            ):
                # 'code$0' is the prompts node; the second code() lands at
                # 'code$1'. Both sort before any later primitive, but their
                # mutual order matches what we passed — so we explicitly
                # pass them in REVERSE alphabetical order here to prove the
                # zip preserves positional order rather than re-sorting.
                prompts = code(
                    _prompts, inputs={}, output_type="list[str]",
                )
                faces = code(
                    _faces, inputs={}, output_type="list[int]",
                )
                # User-passed order: faces FIRST (code$1), prompts SECOND
                # (code$0). A sorted source list would put code$0 first,
                # silently swapping the per-tuple element order.
                pair_node = zip_nodes(faces, prompts)

        zip_eq = g.get(pair_node.equation_key)
        assert zip_eq.definition["sources"] == [
            faces.equation_key,
            prompts.equation_key,
        ], (
            "zip_nodes must preserve user-passed positional order; "
            "got sources={} but expected {}".format(
                zip_eq.definition["sources"],
                [faces.equation_key, prompts.equation_key],
            )
        )

    def test_zip_nodes_node_carries_tuple_element_shape(self):
        # zip_nodes' element shape should reflect each input collection's
        # element shape so downstream readers can reason about pair[i].
        from recipe_dsl.context import BuildContext, activate_context, push_frame
        from recipe_dsl.primitives import zip_nodes
        from recipe_runtime.graph import EquationGraph

        def _ints():
            return [1, 2, 3]

        def _strs():
            return ["a", "b", "c"]

        g = EquationGraph()
        ctx = BuildContext(g)
        with activate_context(ctx):
            with push_frame(
                ctx, parent_key="r", function_name="r", phase_stack=[],
            ):
                a = code(_ints, inputs={}, output_type="list[int]")
                b = code(_strs, inputs={}, output_type="list[str]")
                pair_node = zip_nodes(a, b)

        assert isinstance(pair_node.shape, ListShape)
        assert isinstance(pair_node.shape.element, TupleShape)
        assert pair_node.shape.element.elements == (
            Scalar(kind="int"),
            Scalar(kind="str"),
        )


class TestFindBadSubscripts:
    def test_missing_key_flagged(self):
        shape = DictShape(
            fields=(("briefs", ListShape(element=Scalar(kind="str"))),),
            closed=True,
        )
        bad = find_bad_subscripts("data['items']", {"data": shape})
        assert len(bad) == 1
        assert bad[0].binding_name == "data"
        assert bad[0].key == "items"
        assert bad[0].available == ("briefs",)

    def test_known_key_ok(self):
        shape = DictShape(
            fields=(("briefs", ListShape(element=Scalar(kind="str"))),),
            closed=True,
        )
        assert find_bad_subscripts("data['briefs']", {"data": shape}) == []

    def test_open_dict_skipped(self):
        shape = DictShape(fields=(("x", Scalar(kind="str")),), closed=False)
        assert find_bad_subscripts("data['y']", {"data": shape}) == []

    def test_unknown_binding_skipped(self):
        assert find_bad_subscripts("data['y']", {"data": UNKNOWN}) == []

    def test_non_expression_source_skipped(self):
        # Multi-line statement sources aren't walked in v1.
        shape = DictShape(fields=(("a", Scalar(kind="str")),), closed=True)
        src = "x = data['a']\nreturn x"
        assert find_bad_subscripts(src, {"data": shape}) == []

    def test_dynamic_key_skipped(self):
        # data[var] — can't check non-literal keys.
        shape = DictShape(fields=(("a", Scalar(kind="str")),), closed=True)
        assert find_bad_subscripts("data[some_var]", {"data": shape}) == []


class TestParseToolParamExpectations:
    def test_required_params(self):
        schema = {
            "type": "object",
            "required": ["prompt"],
            "properties": {
                "prompt": {"type": "string"},
                "negative": {"type": "string"},
            },
        }
        exp = parse_tool_param_expectations(schema)
        assert exp["prompt"].required is True
        assert exp["negative"].required is False
        assert exp["prompt"].kind == "scalar"
        assert exp["prompt"].scalar_kind == "str"

    def test_file_path_array_is_media_array(self):
        schema = {
            "type": "object",
            "required": ["input_images"],
            "properties": {
                "input_images": {
                    "type": "array",
                    "items": {"type": "string", "format": "file-path"},
                },
            },
        }
        exp = parse_tool_param_expectations(schema)
        assert exp["input_images"].kind == "array"
        assert exp["input_images"].array_element_kind == "media"

    def test_image_picker_control_is_media_array(self):
        # Real-world schemas (e.g. comfyui:flux-klein-9b) declare array items
        # as plain strings and signal "media picker" only via x-control. The
        # wire layer resolves media → path at dispatch, so the shape validator
        # must recognize the control or reject otherwise-valid calls.
        schema = {
            "type": "object",
            "properties": {
                "input_images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "x-control": "image_picker",
                },
                "frames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "x-control": "video_frame_picker",
                },
            },
        }
        exp = parse_tool_param_expectations(schema)
        assert exp["input_images"].array_element_kind == "media"
        assert exp["frames"].array_element_kind == "media"

    def test_malformed_schema_returns_empty(self):
        assert parse_tool_param_expectations(None) == {}
        assert parse_tool_param_expectations("not a dict") == {}


# =============================================================================
# Integration tests — end-to-end graph builds
# =============================================================================


class TestCodeSubscriptValidator:
    def test_bad_key_from_llm_response_format_is_caught(self):
        @recipe(
            name="bad",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="list[str]")},
        )
        def r(x):
            with phase("p"):
                info = llm(
                    "hi",
                    response_format={"schema": {"briefs": "list[str]"}},
                )
                # 'items' not in declared schema
                wrong = code(
                    "data['items']",
                    inputs={"data": info},
                    output_type="list[str]",
                )
            return wrong

        with pytest.raises(ProgramLoadError) as excinfo:
            build_graph_from_callable(r, inputs={"x": "v"})
        assert "items" in str(excinfo.value)
        assert "briefs" in excinfo.value.suggestion

    def test_valid_key_accepted(self):
        @recipe(
            name="ok",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="list[str]")},
        )
        def r(x):
            with phase("p"):
                info = llm(
                    "hi",
                    response_format={"schema": {"briefs": "list[str]"}},
                )
                ok = code(
                    "data['briefs']",
                    inputs={"data": info},
                    output_type="list[str]",
                )
            return ok

        g = build_graph_from_callable(r, inputs={"x": "v"})
        assert g.all_equations()  # builds without raising

    def test_unknown_upstream_shape_permissive(self):
        # llm() without response_format → Scalar(str), not a dict. code()
        # subscript access never triggers the dict-key check in that case.
        @recipe(
            name="perm",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(x):
            with phase("p"):
                text = llm("hi")
                # Fabricated dict access on a string node — we don't flag
                # this; it'll fail at runtime if it's really wrong, but the
                # validator is not smart enough to know the upstream is a
                # string, only that its shape isn't a DictShape(closed).
                parsed = code(
                    "str(data)",
                    inputs={"data": text},
                    output_type="text",
                )
            return parsed

        build_graph_from_callable(r, inputs={"x": "v"})  # no raise


# ---- Tool-input validator needs a real-looking registry ------------------


class _FakeDescriptor:
    def __init__(self, input_schema, output_schema=None, parameter_schema=None):
        # Single parameter_schema now holds everything — merge any legacy
        # input_schema (prompt, images, ...) into it for test convenience.
        merged = dict(parameter_schema or {})
        if input_schema:
            props = {**(input_schema.get("properties") or {}), **(merged.get("properties") or {})}
            required = list(dict.fromkeys(
                (input_schema.get("required") or []) + (merged.get("required") or [])
            ))
            merged = {**input_schema, **merged, "properties": props}
            if required:
                merged["required"] = required
        self.parameter_schema = merged
        self.output_schema = output_schema or {
            "type": "object",
            "properties": {
                "image_data": {"type": "string", "format": "binary"},
            },
        }


class _FakeRegistry:
    def __init__(self, tools: dict):
        self._tools = tools

    def list_all_tools(self):
        return list(self._tools.keys())

    def get_tool(self, tool_id):
        desc = self._tools.get(tool_id)
        if desc is None:
            return None
        return ("fake-provider", desc)


def _with_fake_registry(tools: dict):
    registry = _FakeRegistry(tools)
    return patch(
        "providers.registry.ProviderRegistry.get_instance",
        return_value=registry,
    )


class TestToolInputValidator:
    def test_required_missing_is_caught(self):
        tools = {
            "fake:gen": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string"},
                    },
                },
            )
        }
        with _with_fake_registry(tools):
            @recipe(
                name="r",
                inputs={"x": dsl_input(type="str")},
                outputs={"out": dsl_output(type="media")},
            )
            def r(x):
                with phase("p"):
                    # Missing required 'prompt'
                    return tool("fake:gen", task_type="text-to-image")

            with pytest.raises(ProgramLoadError) as excinfo:
                build_graph_from_callable(r, inputs={"x": "v"})
            assert "prompt" in str(excinfo.value)

    def test_scalar_where_array_expected_is_caught(self):
        tools = {
            "fake:edit": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt", "input_images"],
                    "properties": {
                        "prompt": {"type": "string"},
                        "input_images": {
                            "type": "array",
                            "items": {"type": "string", "format": "file-path"},
                        },
                    },
                },
            ),
            "fake:gen": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string"},
                    },
                },
            ),
        }
        with _with_fake_registry(tools):
            @recipe(
                name="r",
                inputs={"x": dsl_input(type="str")},
                outputs={"out": dsl_output(type="media")},
            )
            def r(x):
                with phase("p"):
                    photo = tool("fake:gen", task_type="text-to-image", prompt="a")  # scalar media
                    # BUG: passing scalar where list[media] expected.
                    return tool("fake:edit", task_type="text-to-image", prompt="b", input_images=photo)

            with pytest.raises(ProgramLoadError) as excinfo:
                build_graph_from_callable(r, inputs={"x": "v"})
            assert "input_images" in str(excinfo.value)
            assert (
                "list" in str(excinfo.value).lower()
                or "list" in excinfo.value.suggestion.lower()
            )

    def test_well_formed_tool_call_accepted(self):
        tools = {
            "fake:edit": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt", "input_images"],
                    "properties": {
                        "prompt": {"type": "string"},
                        "input_images": {
                            "type": "array",
                            "items": {"type": "string", "format": "file-path"},
                        },
                    },
                },
            ),
            "fake:gen": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string"},
                    },
                },
            ),
        }
        with _with_fake_registry(tools):
            @recipe(
                name="r",
                inputs={"x": dsl_input(type="str")},
                outputs={"out": dsl_output(type="media")},
            )
            def r(x):
                with phase("p"):
                    photo = tool("fake:gen", task_type="text-to-image", prompt="a")  # scalar media
                    # Wrap the scalar into a single-item list — valid.
                    return tool(
                        "fake:edit", task_type="text-to-image",
                        prompt="b",
                        input_images=[photo],
                    )

            g = build_graph_from_callable(r, inputs={"x": "v"})
            assert len(g.all_equations()) >= 3

    def test_foreach_over_tool_output_is_list_of_media(self):
        """foreach(range(N), lambda _: tool(...)) produces a ListShape that
        satisfies an array input."""
        tools = {
            "fake:edit": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["input_images"],
                    "properties": {
                        "input_images": {
                            "type": "array",
                            "items": {"type": "string", "format": "file-path"},
                        },
                    },
                },
            ),
            "fake:gen": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string"},
                    },
                },
            ),
        }
        with _with_fake_registry(tools):
            @recipe(
                name="r",
                inputs={"x": dsl_input(type="str")},
                outputs={"out": dsl_output(type="media")},
            )
            def r(x):
                with phase("p"):
                    cands = foreach(
                        range(3), lambda _: tool("fake:gen", task_type="text-to-image", prompt="a"),
                    )
                    return tool("fake:edit", task_type="text-to-image", input_images=cands)

            g = build_graph_from_callable(r, inputs={"x": "v"})
            assert g.all_equations()

    def test_unknown_kwarg_is_rejected(self):
        """Guard against the ``parameters={...}`` mistake: the agent was
        treating DSL ``tool()`` like the agent-level call_tool (which has
        explicit nested inputs/parameters), so it wrote
        ``tool(id, parameters={"resolution": 3200})``. The flat kwarg
        ``parameters`` matches neither schema — validation must catch it.
        """
        tools = {
            "fake:upscale": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["input_image"],
                    "properties": {
                        "input_image": {"type": "string", "format": "file-path"},
                        "seed": {"type": "integer"},
                    },
                },
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "resolution": {"type": "integer", "default": 1080},
                    },
                },
            ),
            "fake:gen": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {"prompt": {"type": "string"}},
                },
            ),
        }
        with _with_fake_registry(tools):
            @recipe(
                name="r",
                inputs={"x": dsl_input(type="str")},
                outputs={"out": dsl_output(type="media")},
            )
            def r(x):
                with phase("p"):
                    photo = tool("fake:gen", task_type="text-to-image", prompt="a")
                    return tool(
                        "fake:upscale", task_type="text-to-image",
                        input_image=photo,
                        parameters={"resolution": 3200},
                    )

            with pytest.raises(ProgramLoadError) as excinfo:
                build_graph_from_callable(r, inputs={"x": "v"})
            assert "parameters" in str(excinfo.value)
            assert "unknown" in str(excinfo.value).lower()

    def test_parameter_schema_kwarg_is_accepted(self):
        """Flat kwargs matching parameter_schema (not input_schema) must
        validate. Otherwise the right way to set a tool parameter (passing
        ``resolution=3200`` directly) would be rejected too.
        """
        tools = {
            "fake:upscale": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["input_image"],
                    "properties": {
                        "input_image": {"type": "string", "format": "file-path"},
                    },
                },
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "resolution": {"type": "integer", "default": 1080},
                    },
                },
            ),
            "fake:gen": _FakeDescriptor(
                input_schema={
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {"prompt": {"type": "string"}},
                },
            ),
        }
        with _with_fake_registry(tools):
            @recipe(
                name="r",
                inputs={"x": dsl_input(type="str")},
                outputs={"out": dsl_output(type="media")},
            )
            def r(x):
                with phase("p"):
                    photo = tool("fake:gen", task_type="text-to-image", prompt="a")
                    return tool("fake:upscale", task_type="text-to-image", input_image=photo, resolution=3200)

            g = build_graph_from_callable(r, inputs={"x": "v"})
            assert g.all_equations()

    def test_no_registry_is_permissive(self):
        """Without a provider registry available, validation is skipped."""
        @recipe(
            name="r",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(x):
            with phase("p"):
                return llm("hi")

        # No registry patching; empty registry path is exercised.
        g = build_graph_from_callable(r, inputs={"x": "v"})
        assert g.all_equations()


# =============================================================================
# Regression: code() inside foreach must see its resolved inputs
# =============================================================================


class TestCodeInputsInsideForeach:
    """Regression for a bug where ``code()`` inputs that were all *resolved*
    (e.g., the loop item inside a foreach callback) got dropped at
    evaluation time because the engine only merged static_inputs when at
    least one input was a NodeRef. Symptom: NameError in the sandbox.
    """

    @pytest.mark.asyncio
    async def test_static_only_code_inputs_are_passed_to_sandbox(self):
        # Import here to avoid pulling runtime setup into unrelated tests.
        from recipe_runtime.production_evaluators import CodeEvaluator
        from recipe_runtime.evaluators import EvaluationRequest
        from recipe_runtime.graph import Equation, EquationType

        # Simulate what the engine hands the evaluator after resolution:
        # a code() with only static inputs should still get them in
        # resolved_inputs['inputs'].
        eq = Equation(
            key="r/foreach$0/make_pose:0/code$0",
            equation_type=EquationType.CODE,
            definition={
                "source": "f'variation {i+1}'",
                "output_type": "text",
                "static_inputs": {"i": 0},
                "_dynamic": {},  # no NodeRef inputs — the all-resolved case
            },
        )
        # What _resolve_dynamic_bindings now returns for this shape:
        resolved_inputs = {"inputs": {"i": 0}}

        req = EvaluationRequest(
            equation_key=eq.key,
            equation_type="code",
            attempt=1,
            definition=eq.definition,
            resolved_inputs=resolved_inputs,
            recipe_id=None,
            phase_path=[],
            seed=None,
        )
        result = await CodeEvaluator()(req)
        assert result.value == "variation 1"

    @pytest.mark.asyncio
    async def test_engine_merges_static_inputs_when_no_dynamic(self):
        """End-to-end check: the engine's _resolve_dynamic_bindings now
        threads static_inputs into the sandbox even when dynamic is empty.
        """
        from recipe_runtime.engine import RecipeRun
        from recipe_runtime.graph import Equation, EquationGraph, EquationType

        graph = EquationGraph()
        eq = Equation(
            key="test/code$0",
            equation_type=EquationType.CODE,
            definition={
                "source": "f'pose {i+1}'",
                "output_type": "text",
                "static_inputs": {"i": 2},
                "_dynamic": {},
            },
        )
        graph.add_equation(eq)

        # Minimal RecipeRun stub: _resolve_dynamic_bindings only reads
        # self.graph, which we populated above.
        class _Stub:
            def __init__(self, g):
                self.graph = g

            _resolve_dynamic_bindings = RecipeRun._resolve_dynamic_bindings
            _resolve_value = RecipeRun._resolve_value

        resolved = _Stub(graph)._resolve_dynamic_bindings(eq)
        assert resolved == {"inputs": {"i": 2}}


# =============================================================================
# llm(images=) validation
# =============================================================================


class TestLLMImagesValidation:
    """Build-time checks on the images= argument to llm().

    The DSL must accept media nodes and lists of them, and reject anything
    else before evaluation — non-media shapes, raw strings, empty lists.
    """

    def test_accepts_single_media_node(self):
        @recipe(
            name="ok1",
            inputs={"photo": dsl_input(type="media")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(photo):
            with phase("p"):
                return llm("describe this", images=photo)

        g = build_graph_from_callable(r, inputs={"photo": 42})
        # llm equation registered with images in _dynamic
        llm_eqs = [e for e in g.all_equations() if e.equation_type.value == "llm_call"]
        assert len(llm_eqs) == 1
        assert "images" in llm_eqs[0].definition["_dynamic"]

    def test_accepts_list_of_media_nodes(self):
        with patch("recipe_dsl.primitives._tool_id_is_known", return_value=True):
            with patch("recipe_dsl.primitives._get_tool_schema", return_value=None):
                @recipe(
                    name="ok2",
                    inputs={"x": dsl_input(type="str")},
                    outputs={"out": dsl_output(type="str")},
                )
                def r(x):
                    with phase("p"):
                        cands = foreach(
                            range(3), lambda _: tool("fake:gen", task_type="text-to-image", prompt="a"),
                        )
                        return llm("pick one", images=cands)

                g = build_graph_from_callable(r, inputs={"x": "v"})
                llm_eqs = [
                    e for e in g.all_equations() if e.equation_type.value == "llm_call"
                ]
                assert len(llm_eqs) == 1
                assert "images" in llm_eqs[0].definition["_dynamic"]

    def test_rejects_non_media_noderef(self):
        # llm() without response_format is Scalar(str) — not a media.
        @recipe(
            name="bad",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(x):
            with phase("p"):
                text = llm("first, summarize")  # Scalar(str)
                return llm("now classify", images=text)

        with pytest.raises(ProgramLoadError) as ei:
            build_graph_from_callable(r, inputs={"x": "v"})
        msg = str(ei.value)
        assert "images" in msg
        assert "media" in msg.lower()

    def test_rejects_plain_string(self):
        @recipe(
            name="bad",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(x):
            with phase("p"):
                return llm("describe", images="/tmp/cat.png")

        with pytest.raises(ProgramLoadError) as ei:
            build_graph_from_callable(r, inputs={"x": "v"})
        assert "images" in str(ei.value)

    def test_rejects_empty_list(self):
        @recipe(
            name="bad",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(x):
            with phase("p"):
                return llm("describe", images=[])

        with pytest.raises(ProgramLoadError) as ei:
            build_graph_from_callable(r, inputs={"x": "v"})
        assert "images" in str(ei.value)

    def test_none_is_accepted_and_no_binding_registered(self):
        @recipe(
            name="ok3",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def r(x):
            with phase("p"):
                return llm("describe", images=None)

        g = build_graph_from_callable(r, inputs={"x": "v"})
        llm_eqs = [e for e in g.all_equations() if e.equation_type.value == "llm_call"]
        assert "images" not in llm_eqs[0].definition["_dynamic"]

    def test_images_do_not_affect_definition_hash(self):
        """images= is a dynamic binding — it goes into inputs_hash, not
        definition_hash. Two llm() calls with identical static params but
        different images should share the same definition_hash.
        """
        @recipe(
            name="a",
            inputs={"p": dsl_input(type="media")},
            outputs={"out": dsl_output(type="str")},
        )
        def with_images(p):
            with phase("p"):
                return llm("describe", images=p)

        @recipe(
            name="b",
            inputs={"x": dsl_input(type="str")},
            outputs={"out": dsl_output(type="str")},
        )
        def without(x):
            with phase("p"):
                return llm("describe")

        g1 = build_graph_from_callable(with_images, inputs={"p": 1})
        g2 = build_graph_from_callable(without, inputs={"x": "v"})
        llm1 = next(e for e in g1.all_equations() if e.equation_type.value == "llm_call")
        llm2 = next(e for e in g2.all_equations() if e.equation_type.value == "llm_call")
        assert llm1.definition["definition_hash"] == llm2.definition["definition_hash"]

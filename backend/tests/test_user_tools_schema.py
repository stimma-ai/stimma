"""Native flow→STP convergence: a flow's input schema IS canonical STP.

These tests prove there is NO freeze-time translator — a DSL ``input()`` spec
serializes to STP at the source (`_serialize_input_specs`), and the freezer only
*assembles* (wrap + hoist `optional`→`required`), with the result accepted by the
real task-type validator.
"""

from flow_dsl.loader import _serialize_input_specs
from flow_dsl.primitives import input as flow_input
from tasks.schemas import validate_tool_schema
from user_tools_schema import build_output_schema, flow_input_schema_to_parameter_schema


def test_input_spec_serializes_to_stp_vocabulary():
    specs = {
        "prompt": flow_input(type="str", lines=2, description="the prompt"),
        "steps": flow_input(type="int", default=10, validation={"min": 8, "max": 12, "step": 1}),
        "sampler": flow_input(
            type="enum", options=["euler", "dpmpp_2m"], default="euler", display_name="Sampler"
        ),
        "input_images": flow_input(type="list[media]", validation={"min_items": 1, "max_items": 3}),
        "strength": flow_input(
            type="float", default=0.6, validation={"min": 0.0, "max": 1.0}, optional=True
        ),
    }
    schema = _serialize_input_specs(specs)

    assert schema["prompt"] == {"type": "string", "description": "the prompt", "x-control": "textarea"}
    assert schema["steps"] == {"type": "integer", "minimum": 8, "maximum": 12, "x-step": 1, "default": 10}
    assert schema["sampler"]["type"] == "string"
    assert schema["sampler"]["enum"] == ["euler", "dpmpp_2m"]
    assert schema["sampler"]["x-label"] == "Sampler"
    assert schema["input_images"] == {
        "type": "array",
        "items": {"type": "string", "format": "file-path"},
        "x-control": "image_picker",
        "minItems": 1,
        "maxItems": 3,
    }
    assert schema["strength"]["optional"] is True  # the one map-level marker


def test_seed_input_serializes_to_seed_control():
    # type="seed" and ui control="seed" both produce the canonical seed control.
    from_type = _serialize_input_specs({"seed": flow_input(type="seed", display_name="Seed")})
    assert from_type["seed"]["type"] == "integer"
    assert from_type["seed"]["x-control"] == "seed"
    assert from_type["seed"]["minimum"] == 0
    assert from_type["seed"]["maximum"] == 2**31 - 1
    assert from_type["seed"]["x-label"] == "Seed"

    from_ui = _serialize_input_specs({"seed": flow_input(type="int", ui={"control": "seed"})})
    assert from_ui["seed"]["x-control"] == "seed"
    assert from_ui["seed"]["type"] == "integer"

    # An explicit range is preserved (not overwritten by the defaults).
    ranged = _serialize_input_specs(
        {"seed": flow_input(type="seed", validation={"min": 1, "max": 1000})}
    )
    assert ranged["seed"]["minimum"] == 1
    assert ranged["seed"]["maximum"] == 1000


def test_prompt_input_serializes_to_prompt_control():
    # type="prompt" produces the dedicated prompt control (AIPromptEditor),
    # not a plain textarea — even when lines>1 would otherwise claim it.
    from_type = _serialize_input_specs(
        {"prompt": flow_input(type="prompt", display_name="Prompt", lines=4)}
    )
    assert from_type["prompt"]["type"] == "string"
    assert from_type["prompt"]["x-control"] == "prompt"

    # ui control="prompt" stays equivalent to the type= shorthand.
    from_ui = _serialize_input_specs({"prompt": flow_input(type="str", ui={"control": "prompt"})})
    assert from_ui["prompt"]["x-control"] == "prompt"


def test_upscale_resolution_control_passes_through():
    schema = _serialize_input_specs(
        {"scale_factor": flow_input(type="float", ui={"control": "upscale_resolution"})}
    )
    assert schema["scale_factor"]["x-control"] == "upscale_resolution"


def test_allowed_dimensions_emitted_for_constrained_picker():
    schema = _serialize_input_specs(
        {
            "width": flow_input(
                type="int", ui={"allowed_dimensions": [[1024, 1024], [1024, 1536]]}
            ),
        }
    )
    assert schema["width"]["x-allowed-dimensions"] == [[1024, 1024], [1024, 1536]]


def test_native_stp_passes_task_validator_without_translation():
    # text-to-image needs a `prompt`
    flow_schema = _serialize_input_specs({"prompt": flow_input(type="str", lines=2)})
    pschema = flow_input_schema_to_parameter_schema(flow_schema)  # pure assembly
    assert pschema["required"] == ["prompt"]
    oschema = build_output_schema(["text-to-image"])
    assert validate_tool_schema("text-to-image", pschema, oschema) == []

    # image-to-image needs prompt + input_images
    pschema2 = flow_input_schema_to_parameter_schema(
        _serialize_input_specs(
            {"prompt": flow_input(type="str"), "input_images": flow_input(type="list[media]")}
        )
    )
    assert validate_tool_schema("image-to-image", pschema2, oschema) == []

    # missing input_images -> invalid
    pschema3 = flow_input_schema_to_parameter_schema(
        _serialize_input_specs({"prompt": flow_input(type="str")})
    )
    assert validate_tool_schema("image-to-image", pschema3, oschema)


def test_optional_marker_hoisted_to_required_array():
    pschema = flow_input_schema_to_parameter_schema(
        _serialize_input_specs(
            {"a": flow_input(type="str"), "b": flow_input(type="str", optional=True)}
        )
    )
    assert pschema["required"] == ["a"]
    assert "optional" not in pschema["properties"]["b"]  # marker stripped, not leaked into STP

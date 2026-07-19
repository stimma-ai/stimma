"""
Task schema requirements for STP tool validation.

Tools that declare a task_type must match the expected input/output schema
for that task. Tools without task_type are "utilities" with freeform schemas.
"""

from typing import Dict, List, Any

from .types import TaskType


# Backward-compatible aliases for task type strings
TASK_TYPE_ALIASES: Dict[str, str] = {
    "image-edit": "image-to-image",
}


def normalize_task_type(task_type: str) -> str:
    """Normalize a task type string, resolving backward-compat aliases."""
    return TASK_TYPE_ALIASES.get(task_type, task_type)


# Required and optional input/output fields for each task type.
# Tools declaring a task_type must include all required fields in their schemas.
TASK_SCHEMA_REQUIREMENTS: Dict[str, Dict[str, List[str]]] = {
    TaskType.TEXT_TO_IMAGE.value: {
        "required_input": ["prompt"],
        "optional_input": ["negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.IMAGE_TO_IMAGE.value: {
        "required_input": ["prompt", "input_images"],
        "optional_input": ["negative_prompt"],
        "required_output": ["assets"],
    },
    # Deterministic image→image transforms (no prompt): provider-shipped
    # filters that slot into post-processing chains. Tool-specific knobs are
    # free-form parameters.
    TaskType.FILTER.value: {
        "required_input": ["input_images"],
        "optional_input": [],
        "required_output": ["assets"],
    },
    TaskType.IMAGE_TO_VIDEO.value: {
        "required_input": ["input_images"],
        "optional_input": ["prompt", "negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.TEXT_TO_VIDEO.value: {
        "required_input": ["prompt"],
        "optional_input": ["negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.VIDEO_TO_VIDEO.value: {
        "required_input": ["input_videos"],
        "optional_input": ["prompt", "negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.UPSCALE_IMAGE.value: {
        "required_input": ["input_images"],
        "optional_input": [],
        "required_output": ["assets"],
    },
    TaskType.UPSCALE_VIDEO.value: {
        "required_input": ["input_videos"],
        "optional_input": [],
        "required_output": ["assets"],
    },
    TaskType.INPAINT_IMAGE.value: {
        "required_input": ["input_images", "mask"],
        "optional_input": ["prompt", "negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.OUTPAINT_IMAGE.value: {
        "required_input": ["input_images"],
        "optional_input": ["prompt", "negative_prompt", "expand_left", "expand_right", "expand_top", "expand_bottom"],
        "required_output": ["assets"],
    },
    TaskType.REMOVE_BACKGROUND.value: {
        "required_input": ["input_images"],
        "optional_input": [],
        "required_output": ["assets"],
    },
    TaskType.DETECT_OBJECTS.value: {
        "required_input": ["input_images"],
        "optional_input": [],
        "required_output": ["detections"],
    },
    TaskType.VIDEO_STITCH.value: {
        "required_input": ["input_videos"],
        "optional_input": ["prompt", "negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.VIDEO_EXTEND.value: {
        "required_input": ["input_videos"],
        "optional_input": ["prompt", "negative_prompt"],
        "required_output": ["assets"],
    },
    TaskType.LIP_SYNC.value: {
        "required_input": ["input_videos", "input_audios"],
        "optional_input": ["original_audio_volume", "sound_volume"],
        "required_output": ["assets"],
    },
    TaskType.TEXT_TO_MUSIC.value: {
        "required_input": ["prompt"],
        "optional_input": ["lyrics", "instrumental", "duration"],
        "required_output": ["assets"],
    },
    TaskType.TEXT_TO_SPEECH.value: {
        "required_input": ["prompt"],
        "optional_input": ["voice", "language", "speed", "input_audios"],
        "required_output": ["assets"],
    },
    # Lower-level audio generation: sound effects / ambience (e.g. Mirelo SFX).
    TaskType.TEXT_TO_AUDIO.value: {
        "required_input": ["prompt"],
        "optional_input": ["duration"],
        "required_output": ["assets"],
    },
    TaskType.AUDIO_TO_AUDIO.value: {
        "required_input": ["input_audios"],
        "optional_input": [],
        "required_output": ["assets"],
    },
    TaskType.SPEECH_TO_TEXT.value: {
        "required_input": ["input_audios"],
        "optional_input": ["language_code", "diarize", "tag_audio_events", "keyterms"],
        "required_output": ["assets"],
    },
}


def validate_tool_schema(
    task_type: str,
    parameter_schema: Dict[str, Any],
    output_schema: Dict[str, Any],
) -> List[str]:
    """
    Validate that a tool's schemas match the requirements for its declared task_type.

    Args:
        task_type: The task type string (e.g., "text-to-image")
        parameter_schema: The tool's single parameter_schema (JSON Schema format)
        output_schema: The tool's output_schema (JSON Schema format)

    Returns:
        List of error messages. Empty list means validation passed.
    """
    errors = []

    task_type = normalize_task_type(task_type)
    requirements = TASK_SCHEMA_REQUIREMENTS.get(task_type)
    if not requirements:
        errors.append(f"Unknown task_type: {task_type}")
        return errors

    # Get properties from schemas
    input_props = set(parameter_schema.get("properties", {}).keys())
    output_props = set(output_schema.get("properties", {}).keys())

    # Check required input fields
    if "required_input" in requirements:
        for field in requirements["required_input"]:
            if field not in input_props:
                errors.append(f"Missing required input field: {field}")

    # Check required output fields
    if "required_output" in requirements:
        for field in requirements["required_output"]:
            if field not in output_props:
                errors.append(f"Missing required output field: {field}")

    return errors


def is_known_task_type(task_type: str) -> bool:
    """Check if a task_type string is in the known set (including aliases)."""
    return normalize_task_type(task_type) in TASK_SCHEMA_REQUIREMENTS


def validate_tool_schema_multi(
    task_types: List[str],
    parameter_schema: Dict[str, Any],
    output_schema: Dict[str, Any],
) -> List[str]:
    """
    Validate that a tool's schemas match the requirements for ALL declared task_types.

    Tools declaring multiple task types must satisfy the schema requirements of each.
    For example, a tool declaring ["text-to-image", "image-to-image"] must have:
    - prompt (required by both)
    - input_images (required by image-to-image)
    - assets in output (required by both)

    Args:
        task_types: List of task type strings (e.g., ["text-to-image", "image-to-image"])
        parameter_schema: The tool's single parameter_schema (JSON Schema format)
        output_schema: The tool's output_schema (JSON Schema format)

    Returns:
        List of error messages prefixed with task type. Empty list means validation passed.
    """
    all_errors = []

    for task_type in task_types:
        errors = validate_tool_schema(task_type, parameter_schema, output_schema)
        # Prefix each error with the task type for clarity
        all_errors.extend([f"[{task_type}] {e}" for e in errors])

    return all_errors

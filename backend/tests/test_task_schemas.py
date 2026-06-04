"""Tests for tasks/schemas.py — task type normalization and schema validation."""

import pytest

from tasks.schemas import (
    normalize_task_type,
    TASK_TYPE_ALIASES,
    TASK_SCHEMA_REQUIREMENTS,
    validate_tool_schema,
    is_known_task_type,
    validate_tool_schema_multi,
)
from tasks.types import TaskType


# ---------------------------------------------------------------------------
# normalize_task_type
# ---------------------------------------------------------------------------

class TestNormalizeTaskType:
    def test_alias_resolves(self):
        assert normalize_task_type("image-edit") == "image-to-image"

    def test_non_alias_passes_through(self):
        assert normalize_task_type("text-to-image") == "text-to-image"

    def test_unknown_passes_through(self):
        assert normalize_task_type("totally-made-up") == "totally-made-up"


# ---------------------------------------------------------------------------
# Schema requirements coverage
# ---------------------------------------------------------------------------

class TestSchemaRequirementsCoverage:
    def test_every_task_type_has_entry(self):
        for tt in TaskType:
            assert tt.value in TASK_SCHEMA_REQUIREMENTS, (
                f"TaskType.{tt.name} ({tt.value}) missing from TASK_SCHEMA_REQUIREMENTS"
            )

    def test_all_entries_have_required_output(self):
        for task_type, reqs in TASK_SCHEMA_REQUIREMENTS.items():
            assert "required_output" in reqs, (
                f"{task_type} is missing required_output"
            )


# ---------------------------------------------------------------------------
# validate_tool_schema
# ---------------------------------------------------------------------------

class TestValidateToolSchema:
    def test_valid_schema_passes(self):
        inp = {"properties": {"prompt": {}, "negative_prompt": {}}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema("text-to-image", inp, out)
        assert errors == []

    def test_missing_required_input_fails(self):
        inp = {"properties": {}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema("text-to-image", inp, out)
        assert any("prompt" in e for e in errors)

    def test_missing_required_output_fails(self):
        inp = {"properties": {"prompt": {}}}
        out = {"properties": {}}
        errors = validate_tool_schema("text-to-image", inp, out)
        assert any("assets" in e for e in errors)

    def test_unknown_task_type_fails(self):
        errors = validate_tool_schema("does-not-exist", {}, {})
        assert any("Unknown" in e for e in errors)

    def test_image_to_video_requires_input_images(self):
        # image-to-video requires input_images
        inp = {"properties": {"input_images": {}}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema("image-to-video", inp, out)
        assert not any("required input" in e.lower() for e in errors)

    def test_image_to_video_missing_input_images_fails(self):
        inp = {"properties": {"prompt": {}}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema("image-to-video", inp, out)
        assert any("input_images" in e for e in errors)

    def test_alias_resolves_in_validation(self):
        inp = {"properties": {"prompt": {}, "input_images": {}}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema("image-edit", inp, out)
        assert errors == []


# ---------------------------------------------------------------------------
# is_known_task_type
# ---------------------------------------------------------------------------

class TestIsKnownTaskType:
    def test_known_type(self):
        assert is_known_task_type("text-to-image") is True

    def test_alias_is_known(self):
        assert is_known_task_type("image-edit") is True

    def test_unknown_is_not_known(self):
        assert is_known_task_type("banana-generator") is False


# ---------------------------------------------------------------------------
# validate_tool_schema_multi
# ---------------------------------------------------------------------------

class TestValidateToolSchemaMulti:
    def test_multiple_types_all_pass(self):
        inp = {"properties": {"prompt": {}, "input_images": {}, "negative_prompt": {}}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema_multi(["text-to-image", "image-to-image"], inp, out)
        assert errors == []

    def test_errors_prefixed_with_task_type(self):
        inp = {"properties": {"prompt": {}}}
        out = {"properties": {"assets": {}}}
        errors = validate_tool_schema_multi(["text-to-image", "image-to-image"], inp, out)
        # text-to-image should pass, image-to-image should fail (missing input_images)
        assert any(e.startswith("[image-to-image]") for e in errors)

"""Tests for tasks/parameters.py — ParameterSpec.validate() and to_json_schema()."""

import pytest

from tasks.parameters import ParameterSpec, ParamType, COMMON_PARAMETERS


# ---------------------------------------------------------------------------
# INT validation
# ---------------------------------------------------------------------------

class TestIntValidation:
    def _spec(self, **kw):
        return ParameterSpec(name="x", param_type=ParamType.INT, default=0, **kw)

    def test_valid_int(self):
        assert self._spec().validate(42) == (True, None)

    def test_reject_bool(self):
        ok, _ = self._spec().validate(True)
        assert not ok

    def test_reject_float(self):
        ok, _ = self._spec().validate(3.14)
        assert not ok

    def test_reject_string(self):
        ok, _ = self._spec().validate("10")
        assert not ok

    def test_min_bound_pass(self):
        assert self._spec(min_value=5).validate(5) == (True, None)

    def test_min_bound_fail(self):
        ok, _ = self._spec(min_value=5).validate(4)
        assert not ok

    def test_max_bound_pass(self):
        assert self._spec(max_value=10).validate(10) == (True, None)

    def test_max_bound_fail(self):
        ok, _ = self._spec(max_value=10).validate(11)
        assert not ok


# ---------------------------------------------------------------------------
# FLOAT validation
# ---------------------------------------------------------------------------

class TestFloatValidation:
    def _spec(self, **kw):
        return ParameterSpec(name="x", param_type=ParamType.FLOAT, default=0.0, **kw)

    def test_valid_float(self):
        assert self._spec().validate(3.14) == (True, None)

    def test_accept_int_as_float(self):
        assert self._spec().validate(5) == (True, None)

    def test_reject_bool(self):
        ok, _ = self._spec().validate(False)
        assert not ok

    def test_reject_string(self):
        ok, _ = self._spec().validate("1.5")
        assert not ok

    def test_min_bound_fail(self):
        ok, _ = self._spec(min_value=0.0).validate(-0.1)
        assert not ok

    def test_max_bound_fail(self):
        ok, _ = self._spec(max_value=1.0).validate(1.01)
        assert not ok


# ---------------------------------------------------------------------------
# STRING validation
# ---------------------------------------------------------------------------

class TestStringValidation:
    def _spec(self):
        return ParameterSpec(name="x", param_type=ParamType.STRING, default="")

    def test_valid_string(self):
        assert self._spec().validate("hello") == (True, None)

    def test_reject_non_string(self):
        ok, _ = self._spec().validate(123)
        assert not ok


# ---------------------------------------------------------------------------
# BOOL validation
# ---------------------------------------------------------------------------

class TestBoolValidation:
    def _spec(self):
        return ParameterSpec(name="x", param_type=ParamType.BOOL, default=False)

    def test_valid_bool(self):
        assert self._spec().validate(True) == (True, None)

    def test_reject_int(self):
        ok, _ = self._spec().validate(1)
        assert not ok

    def test_reject_string(self):
        ok, _ = self._spec().validate("true")
        assert not ok


# ---------------------------------------------------------------------------
# ENUM validation
# ---------------------------------------------------------------------------

class TestEnumValidation:
    def _spec(self):
        return ParameterSpec(
            name="x", param_type=ParamType.ENUM, default="a", choices=["a", "b", "c"]
        )

    def test_valid_choice(self):
        assert self._spec().validate("b") == (True, None)

    def test_reject_invalid_choice(self):
        ok, _ = self._spec().validate("z")
        assert not ok


# ---------------------------------------------------------------------------
# LORA_LIST validation
# ---------------------------------------------------------------------------

class TestLoraListValidation:
    def _spec(self):
        return ParameterSpec(name="x", param_type=ParamType.LORA_LIST, default=[])

    def test_valid_list(self):
        assert self._spec().validate([{"lora": "my_lora", "weight": 1.0}]) == (True, None)

    def test_reject_non_list(self):
        ok, _ = self._spec().validate("not a list")
        assert not ok

    def test_reject_items_without_lora(self):
        ok, _ = self._spec().validate([{"weight": 1.0}])
        assert not ok

    def test_reject_non_dict_items(self):
        ok, _ = self._spec().validate(["string_item"])
        assert not ok


# ---------------------------------------------------------------------------
# LORA_PAIR validation
# ---------------------------------------------------------------------------

class TestLoraPairValidation:
    def _spec(self):
        return ParameterSpec(name="x", param_type=ParamType.LORA_PAIR, default=None)

    def test_valid_pair(self):
        val = {"high_noise_path": "/a", "low_noise_path": "/b"}
        assert self._spec().validate(val) == (True, None)

    def test_reject_missing_fields(self):
        ok, _ = self._spec().validate({"high_noise_path": "/a"})
        assert not ok

    def test_reject_non_dict(self):
        ok, _ = self._spec().validate("nope")
        assert not ok

    def test_accept_none(self):
        assert self._spec().validate(None) == (True, None)


# ---------------------------------------------------------------------------
# None always valid
# ---------------------------------------------------------------------------

def test_none_valid_for_any_type():
    for pt in ParamType:
        spec = ParameterSpec(name="x", param_type=pt, default=None)
        assert spec.validate(None) == (True, None), f"None should be valid for {pt}"


# ---------------------------------------------------------------------------
# to_json_schema
# ---------------------------------------------------------------------------

class TestToJsonSchema:
    def test_int_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.INT, default=10, min_value=0, max_value=100)
        schema = spec.to_json_schema()
        assert schema["type"] == "integer"
        assert schema["minimum"] == 0
        assert schema["maximum"] == 100

    def test_float_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.FLOAT, default=1.0)
        assert spec.to_json_schema()["type"] == "number"

    def test_string_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.STRING, default="")
        assert spec.to_json_schema()["type"] == "string"

    def test_bool_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.BOOL, default=False)
        assert spec.to_json_schema()["type"] == "boolean"

    def test_enum_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.ENUM, default="a", choices=["a", "b"])
        schema = spec.to_json_schema()
        assert schema["type"] == "string"
        assert schema["enum"] == ["a", "b"]

    def test_lora_list_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.LORA_LIST, default=[])
        schema = spec.to_json_schema()
        assert schema["type"] == "array"
        assert "items" in schema

    def test_lora_pair_schema(self):
        spec = ParameterSpec(name="x", param_type=ParamType.LORA_PAIR, default=None)
        schema = spec.to_json_schema()
        assert schema["type"] == "object"
        assert schema["nullable"] is True


# ---------------------------------------------------------------------------
# COMMON_PARAMETERS spot checks
# ---------------------------------------------------------------------------

class TestCommonParameters:
    def test_has_prompt(self):
        assert "prompt" in COMMON_PARAMETERS

    def test_has_steps(self):
        assert "steps" in COMMON_PARAMETERS

    def test_has_loras(self):
        assert "loras" in COMMON_PARAMETERS

    def test_prompt_is_string_type(self):
        assert COMMON_PARAMETERS["prompt"].param_type == ParamType.STRING

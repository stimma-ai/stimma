"""Tests for config_writer.py validation functions."""

import pytest

from config_writer import (
    validate_folder_path,
    validate_marker,
    validate_markers,
    validate_parallelism,
    validate_captioning_parallelism,
    validate_confidence,
    validate_max_faces,
    validate_folders,
    _is_valid_hex_color,
    _is_valid_icon,
    ValidationError,
)


# ---------------------------------------------------------------------------
# _is_valid_hex_color
# ---------------------------------------------------------------------------

class TestIsValidHexColor:
    def test_valid(self):
        assert _is_valid_hex_color("#ff0000") is True

    def test_uppercase_valid(self):
        assert _is_valid_hex_color("#FF00AA") is True

    def test_invalid_chars(self):
        assert _is_valid_hex_color("#xyzxyz") is False

    def test_empty(self):
        assert _is_valid_hex_color("") is False

    def test_missing_hash(self):
        assert _is_valid_hex_color("ff0000") is False

    def test_too_short(self):
        assert _is_valid_hex_color("#fff") is False

    def test_too_long(self):
        assert _is_valid_hex_color("#ff00001") is False


# ---------------------------------------------------------------------------
# _is_valid_icon
# ---------------------------------------------------------------------------

class TestIsValidIcon:
    def test_heroicons_valid(self):
        assert _is_valid_icon("heroicons:heart") is True

    def test_svg_valid(self):
        assert _is_valid_icon('<svg viewBox="0 0 24 24"></svg>') is True

    def test_empty(self):
        assert _is_valid_icon("") is False

    def test_random_string(self):
        assert _is_valid_icon("just-a-string") is False

    def test_heroicons_empty_name(self):
        assert _is_valid_icon("heroicons:") is False


# ---------------------------------------------------------------------------
# validate_parallelism
# ---------------------------------------------------------------------------

class TestValidateParallelism:
    def test_valid_min(self):
        validate_parallelism(1)  # should not raise

    def test_valid_max(self):
        validate_parallelism(8)

    def test_zero_fails(self):
        with pytest.raises(ValidationError):
            validate_parallelism(0)

    def test_nine_fails(self):
        with pytest.raises(ValidationError):
            validate_parallelism(9)

    def test_non_int_fails(self):
        with pytest.raises(ValidationError):
            validate_parallelism("4")

    def test_float_fails(self):
        with pytest.raises(ValidationError):
            validate_parallelism(3.5)


# ---------------------------------------------------------------------------
# validate_captioning_parallelism
# ---------------------------------------------------------------------------

class TestValidateCaptioningParallelism:
    def test_valid_min(self):
        validate_captioning_parallelism(1)

    def test_valid_max(self):
        validate_captioning_parallelism(50)

    def test_zero_fails(self):
        with pytest.raises(ValidationError):
            validate_captioning_parallelism(0)

    def test_over_max_fails(self):
        with pytest.raises(ValidationError):
            validate_captioning_parallelism(51)

    def test_non_int_fails(self):
        with pytest.raises(ValidationError):
            validate_captioning_parallelism(10.0)


# ---------------------------------------------------------------------------
# validate_confidence
# ---------------------------------------------------------------------------

class TestValidateConfidence:
    def test_valid_zero(self):
        validate_confidence(0.0)

    def test_valid_one(self):
        validate_confidence(1.0)

    def test_valid_mid(self):
        validate_confidence(0.5)

    def test_negative_fails(self):
        with pytest.raises(ValidationError):
            validate_confidence(-0.1)

    def test_over_one_fails(self):
        with pytest.raises(ValidationError):
            validate_confidence(1.1)

    def test_non_number_fails(self):
        with pytest.raises(ValidationError):
            validate_confidence("high")

    def test_int_accepted(self):
        validate_confidence(1)  # int 1 is within [0.0, 1.0]


# ---------------------------------------------------------------------------
# validate_max_faces
# ---------------------------------------------------------------------------

class TestValidateMaxFaces:
    def test_valid_min(self):
        validate_max_faces(1)

    def test_valid_max(self):
        validate_max_faces(50)

    def test_zero_fails(self):
        with pytest.raises(ValidationError):
            validate_max_faces(0)

    def test_over_max_fails(self):
        with pytest.raises(ValidationError):
            validate_max_faces(51)

    def test_non_int_fails(self):
        with pytest.raises(ValidationError):
            validate_max_faces(10.0)


# ---------------------------------------------------------------------------
# validate_marker
# ---------------------------------------------------------------------------

class TestValidateMarker:
    def test_valid_marker(self):
        validate_marker({"name": "favorite", "color": "#ef4444", "icon_svg": "heroicons:heart"})

    def test_empty_name_fails(self):
        with pytest.raises(ValidationError):
            validate_marker({"name": "", "color": "#ef4444", "icon_svg": "heroicons:heart"})

    def test_invalid_color_fails(self):
        with pytest.raises(ValidationError):
            validate_marker({"name": "test", "color": "red", "icon_svg": "heroicons:heart"})

    def test_invalid_icon_fails(self):
        with pytest.raises(ValidationError):
            validate_marker({"name": "test", "color": "#ef4444", "icon_svg": "nope"})


# ---------------------------------------------------------------------------
# validate_markers
# ---------------------------------------------------------------------------

class TestValidateMarkers:
    def test_valid_list(self):
        markers = [
            {"name": "favorite", "color": "#ef4444", "icon_svg": "heroicons:heart"},
            {"name": "library", "color": "#3b82f6", "icon_svg": "heroicons:bookmark"},
        ]
        validate_markers(markers)

    def test_non_list_fails(self):
        with pytest.raises(ValidationError):
            validate_markers("not a list")

    def test_duplicate_names_fail(self):
        markers = [
            {"name": "Favorite", "color": "#ef4444", "icon_svg": "heroicons:heart"},
            {"name": "favorite", "color": "#3b82f6", "icon_svg": "heroicons:bookmark"},
        ]
        with pytest.raises(ValidationError, match="duplicate"):
            validate_markers(markers)


# ---------------------------------------------------------------------------
# validate_folder_path (uses tmp_path fixture)
# ---------------------------------------------------------------------------

class TestValidateFolderPath:
    def test_valid_dir(self, tmp_path):
        validate_folder_path(str(tmp_path))

    def test_nonexistent_fails(self):
        with pytest.raises(ValidationError):
            validate_folder_path("/nonexistent/path/that/does/not/exist")

    def test_file_not_dir_fails(self, tmp_path):
        f = tmp_path / "afile.txt"
        f.write_text("hello")
        with pytest.raises(ValidationError):
            validate_folder_path(str(f))


# ---------------------------------------------------------------------------
# validate_folders
# ---------------------------------------------------------------------------

class TestValidateFolders:
    def test_valid_list(self, tmp_path):
        folders = [{"path": str(tmp_path)}]
        validate_folders(folders)

    def test_non_list_fails(self):
        with pytest.raises(ValidationError):
            validate_folders("not a list")

    def test_empty_path_fails(self):
        with pytest.raises(ValidationError):
            validate_folders([{"path": ""}])

"""Tests for LoRA name normalization and matching in unified.py."""

import pytest
from agent.tools.stp_utils import _normalize_lora_name, _find_lora_match
from collections import defaultdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_index(available: list[str]) -> dict[str, list[str]]:
    """Build the normalized_name -> [paths] index used by _find_lora_match."""
    idx: dict[str, list[str]] = defaultdict(list)
    for path in available:
        idx[_normalize_lora_name(path)].append(path)
    return idx


def _match(query: str, available: list[str]):
    """Shortcut: run _find_lora_match and return (path, tier) or None."""
    return _find_lora_match(query, available, _build_index(available))


# ---------------------------------------------------------------------------
# _normalize_lora_name
# ---------------------------------------------------------------------------

class TestNormalizeLoraName:
    def test_strips_directory_and_extension(self):
        assert _normalize_lora_name("styles/Anime_V2.safetensors") == "anime v2"

    def test_strips_ckpt_extension(self):
        assert _normalize_lora_name("Realistic_Vision-v2.1.ckpt") == "realistic vision v2 1"

    def test_strips_pt_extension(self):
        assert _normalize_lora_name("MY-MODEL.pt") == "my model"

    def test_collapses_mixed_separators(self):
        assert _normalize_lora_name("a___b--c  d") == "a b c d"

    def test_underscores_become_spaces(self):
        assert _normalize_lora_name("already_clean") == "already clean"


# ---------------------------------------------------------------------------
# _find_lora_match — tier 1 (exact endswith + extension fallback)
# ---------------------------------------------------------------------------

class TestTier1Exact:
    def test_exact_endswith(self):
        path, tier = _match("anime.safetensors", ["styles/anime.safetensors"])
        assert path == "styles/anime.safetensors"
        assert tier == 1

    def test_extension_fallback(self):
        path, tier = _match("anime", ["styles/anime.safetensors"])
        assert path == "styles/anime.safetensors"
        assert tier == 1


# ---------------------------------------------------------------------------
# _find_lora_match — tier 2 (normalized exact)
# ---------------------------------------------------------------------------

class TestTier2Normalized:
    def test_case_insensitive(self):
        path, tier = _match("Anime", ["styles/anime.safetensors"])
        assert path == "styles/anime.safetensors"
        assert tier == 2

    def test_punctuation_swap(self):
        path, tier = _match("anime_v2", ["styles/anime-v2.safetensors"])
        assert path == "styles/anime-v2.safetensors"
        assert tier == 2

    def test_case_and_punctuation(self):
        path, tier = _match("Anime V2", ["styles/anime_v2.safetensors"])
        assert path == "styles/anime_v2.safetensors"
        assert tier == 2


# ---------------------------------------------------------------------------
# _find_lora_match — tier 3 (normalized substring)
# ---------------------------------------------------------------------------

class TestTier3Substring:
    def test_query_subset_of_name(self):
        path, tier = _match("anime", ["styles/anime_v2.safetensors"])
        assert path == "styles/anime_v2.safetensors"
        assert tier == 3

    def test_short_query_in_long_name(self):
        path, tier = _match("realistic", ["models/realistic_vision_v5.safetensors"])
        assert path == "models/realistic_vision_v5.safetensors"
        assert tier == 3


# ---------------------------------------------------------------------------
# _find_lora_match — tier 4 (fuzzy)
# ---------------------------------------------------------------------------

class TestTier4Fuzzy:
    def test_fuzzy_close_match(self):
        path, tier = _match("anim_style", ["styles/anime_style_v2.safetensors"])
        assert path == "styles/anime_style_v2.safetensors"
        assert tier == 4


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_match(self):
        result = _match("nonexistent", ["styles/anime.safetensors"])
        assert result is None

    def test_multi_match_picks_best_fuzzy(self):
        """When multiple matches exist at substring tier, fuzzy picks the best one."""
        available = ["styles/anime_v1.safetensors", "styles/anime_v2.safetensors"]
        result = _match("anime", available)
        assert result is not None
        path, tier = result
        # Both are equally good substring matches, so tier 3 has 2 results
        # and it falls through to tier 4 (fuzzy) which picks one
        assert path in available

    def test_identical_names_different_dirs(self):
        """Two loras with identical normalized names in different dirs still resolve."""
        available = ["a/style.safetensors", "b/style.safetensors"]
        result = _match("style", available)
        assert result is not None
        path, tier = result
        assert path in available

    def test_verbatim_path_passthrough(self):
        """A full path that exists verbatim should match at tier 1."""
        available = ["styles/anime.safetensors", "models/other.safetensors"]
        path, tier = _match("styles/anime.safetensors", available)
        assert path == "styles/anime.safetensors"
        assert tier == 1

    def test_path_with_slash_not_in_available_falls_through(self):
        """A path with '/' that doesn't exist verbatim should still cascade."""
        available = ["loras/anime_v2.safetensors"]
        path, tier = _match("styles/anime_v2", available)
        assert path == "loras/anime_v2.safetensors"

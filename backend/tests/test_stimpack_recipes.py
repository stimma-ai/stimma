"""Stimpack recipes load from a pack directory and may import the pack's lib/."""
from pathlib import Path

import pytest

from packages.recipes import _pack_lib_dirs, get_recipe, list_recipes, load_recipe_module

FIXTURES = Path(__file__).parent / "fixtures" / "stimpacks"


def test_pack_lib_dirs_cover_every_skill_lib():
    dirs = _pack_lib_dirs(FIXTURES / "test-tiles" / "recipes" / "tiles.py")
    assert dirs == [FIXTURES / "test-tiles" / "skills" / "tiles" / "lib"]


def test_recipe_module_imports_its_pack_lib():
    (spec,) = load_recipe_module(FIXTURES / "test-tiles" / "recipes" / "tiles.py", source="test-tiles")
    assert spec.id == "tiles" and spec.source == "test-tiles"


def test_lib_dir_does_not_linger_on_sys_path():
    import sys
    load_recipe_module(FIXTURES / "test-tiles" / "recipes" / "tiles.py", source="test-tiles")
    assert not any(p.endswith("skills/tiles/lib") for p in sys.path)


def test_broken_recipe_module_is_skipped_not_fatal(tmp_path, caplog):
    pack = tmp_path / "broken-pack" / "recipes"
    pack.mkdir(parents=True)
    (pack / "bad.py").write_text("import module_that_does_not_exist\n")
    assert load_recipe_module(pack / "bad.py", source="broken-pack") == []
    assert "broken-pack" in caplog.text and "failed to import" in caplog.text


def test_dev_stimpacks_dir_discovers_pack_recipes(monkeypatch):
    """The real discovery path: a dev stimpacks dir that shadows profile packs."""
    from agent.v2 import stimpacks as stimpacks_mod
    from config import get_settings

    monkeypatch.undo()  # drop the session-wide fixture patch for this test
    monkeypatch.setattr(get_settings(), "dev_stimpacks_dir", str(FIXTURES))
    found = dict(stimpacks_mod.list_stimpack_recipe_files())
    assert found["test-tiles"].name == "tiles.py"
    assert get_recipe("tiles").source == "test-tiles"
    assert "tiles" in {r.id for r in list_recipes()}

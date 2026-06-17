"""Legacy recipes/ -> flows/ on-disk data-dir migration.

The recipe→flow rename moved the DB table (alembic) but not the on-disk flow
data. ``flow_runtime.paths`` migrates ``<data_dir>/recipes`` to ``flows`` so
existing flows find their ``program.py`` / ``state.db`` after the rename.
"""

from __future__ import annotations

import app_dirs
from flow_runtime.paths import get_flows_root, migrate_legacy_flow_dirs


def _seed_recipes(data_dir, *flow_ids):
    recipes = data_dir / "recipes"
    for fid in flow_ids:
        d = recipes / str(fid)
        d.mkdir(parents=True)
        (d / "program.py").write_text(f"# flow {fid}\n")
    return recipes


def test_renames_recipes_to_flows_when_flows_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    _seed_recipes(tmp_path, 23, 25, 28)

    migrate_legacy_flow_dirs()

    assert not (tmp_path / "recipes").exists()
    for fid in (23, 25, 28):
        assert (tmp_path / "flows" / str(fid) / "program.py").is_file()


def test_get_flows_root_triggers_migration_lazily(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    _seed_recipes(tmp_path, 7)

    root = get_flows_root()

    assert root == tmp_path / "flows"
    assert (tmp_path / "flows" / "7" / "program.py").is_file()
    assert not (tmp_path / "recipes").exists()


def test_merges_into_empty_flows_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    _seed_recipes(tmp_path, 1)
    (tmp_path / "flows").mkdir()  # pre-existing but empty

    migrate_legacy_flow_dirs()

    assert (tmp_path / "flows" / "1" / "program.py").is_file()
    assert not (tmp_path / "recipes").exists()


def test_idempotent_and_nondestructive_when_both_populated(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    # Already-migrated flows present + a leftover recipes dir with other data:
    # do not clobber flows, leave recipes untouched.
    (tmp_path / "flows" / "1").mkdir(parents=True)
    (tmp_path / "flows" / "1" / "program.py").write_text("# migrated\n")
    _seed_recipes(tmp_path, 1)

    migrate_legacy_flow_dirs()

    assert (tmp_path / "flows" / "1" / "program.py").read_text() == "# migrated\n"
    assert (tmp_path / "recipes").exists()  # left as-is, no data loss

    # No recipes at all -> clean no-op.
    import shutil
    shutil.rmtree(tmp_path / "recipes")
    migrate_legacy_flow_dirs()
    assert not (tmp_path / "recipes").exists()

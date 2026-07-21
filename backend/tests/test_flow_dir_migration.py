"""Profile-scoped flow paths and legacy on-disk migration."""

from __future__ import annotations

import app_dirs
from core.profile_context import ProfileScope
from flow_runtime.paths import get_flows_root, migrate_legacy_flow_dirs


def _seed_legacy_root(data_dir, name, *flow_ids):
    root = data_dir / name
    for fid in flow_ids:
        flow_dir = root / str(fid)
        flow_dir.mkdir(parents=True)
        (flow_dir / "program.py").write_text(f"# flow {fid}\n")
    return root


def test_flow_roots_are_profile_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)

    with ProfileScope("alpha"):
        alpha_root = get_flows_root()
    with ProfileScope("beta"):
        beta_root = get_flows_root()

    assert alpha_root == tmp_path / "alpha" / "flows"
    assert beta_root == tmp_path / "beta" / "flows"
    assert alpha_root != beta_root


def test_moves_legacy_flows_into_selected_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    _seed_legacy_root(tmp_path, "flows", 23, 25, 28)

    migrate_legacy_flow_dirs("asset-majority")

    assert not (tmp_path / "flows").exists()
    for fid in (23, 25, 28):
        assert (
            tmp_path / "asset-majority" / "flows" / str(fid) / "program.py"
        ).is_file()


def test_moves_legacy_recipes_into_selected_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    _seed_legacy_root(tmp_path, "recipes", 7)

    migrate_legacy_flow_dirs("primary")

    assert (tmp_path / "primary" / "flows" / "7" / "program.py").is_file()
    assert not (tmp_path / "recipes").exists()


def test_merges_both_legacy_roots_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    target = tmp_path / "primary" / "flows"
    (target / "1").mkdir(parents=True)
    (target / "1" / "program.py").write_text("# profile copy\n")
    _seed_legacy_root(tmp_path, "flows", 1, 2)
    _seed_legacy_root(tmp_path, "recipes", 3)

    migrate_legacy_flow_dirs("primary")

    # The profile-owned collision wins and the legacy copy remains recoverable.
    assert (target / "1" / "program.py").read_text() == "# profile copy\n"
    assert (tmp_path / "flows" / "1" / "program.py").is_file()
    assert (target / "2" / "program.py").is_file()
    assert (target / "3" / "program.py").is_file()
    assert not (tmp_path / "recipes").exists()

    # Repeating the startup migration does not overwrite either copy.
    migrate_legacy_flow_dirs("primary")
    assert (target / "1" / "program.py").read_text() == "# profile copy\n"
    assert (tmp_path / "flows" / "1" / "program.py").is_file()


def test_conflict_retry_keeps_first_migration_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: tmp_path)
    first_target = tmp_path / "first-majority" / "flows"
    (first_target / "1").mkdir(parents=True)
    (first_target / "1" / "program.py").write_text("# existing\n")
    _seed_legacy_root(tmp_path, "flows", 1)

    assert migrate_legacy_flow_dirs("first-majority") == "first-majority"
    assert (tmp_path / "flows" / "1").is_dir()

    # Asset counts can change, but a partial retry must retain its first owner.
    _seed_legacy_root(tmp_path, "flows", 2)
    assert migrate_legacy_flow_dirs("new-majority") == "first-majority"
    assert (first_target / "2" / "program.py").is_file()
    assert not (tmp_path / "new-majority" / "flows").exists()
    assert (tmp_path / "flow_dir_migration_owner").read_text().strip() == "first-majority"

    # Once the global leftovers are gone, an owner-scoped recipes retry still
    # follows the marker rather than the newly requested majority profile.
    (tmp_path / "flows" / "1" / "program.py").unlink()
    (tmp_path / "flows" / "1").rmdir()
    (tmp_path / "flows").rmdir()
    _seed_legacy_root(tmp_path / "first-majority", "recipes", 3)
    assert migrate_legacy_flow_dirs("new-majority") == "first-majority"
    assert (first_target / "3" / "program.py").is_file()
    assert not (tmp_path / "first-majority" / "recipes").exists()

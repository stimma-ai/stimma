from pathlib import Path

import portable_path


def test_profile_path_is_scoped_below_data_root(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    profile_dir = data_dir / "profile-a"
    monkeypatch.setattr("app_dirs.get_data_dir", lambda: data_dir)
    monkeypatch.setattr(portable_path, "_profile_dir", lambda: profile_dir)

    stored = portable_path.contract_profile_path(
        str(profile_dir / "objects" / "media" / "1" / "image.png")
    )

    assert stored == "@data/profile-a/objects/media/1/image.png"
    assert portable_path.expand_profile_path(stored) == str(
        profile_dir / "objects" / "media" / "1" / "image.png"
    )


def test_relative_input_is_scoped_to_current_profile(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    profile_dir = data_dir / "profile-b"
    monkeypatch.setattr("app_dirs.get_data_dir", lambda: data_dir)
    monkeypatch.setattr(portable_path, "_profile_dir", lambda: profile_dir)

    assert portable_path.contract_profile_path("objects/payload") == (
        "@data/profile-b/objects/payload"
    )

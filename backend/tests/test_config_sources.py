"""Configuration contraction for external Sources and managed staging."""

import app_dirs
import yaml
from config import Settings, ensure_config_exists
from config_writer import remove_profile_section


def test_legacy_destination_roles_become_hidden_migration_roots(tmp_path, monkeypatch):
    legacy_root = tmp_path / "old-output"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
profiles:
  - id: default
    name: Default
    folders:
      - path: {legacy_root}
        readonly: false
        allow_generate: true
        is_uploads_folder: true
        uploads_subfolder: uploads
    markers: []
llms: {{}}
clip:
  model: ViT-g-14
  pretrained: laion2b_s12b_b42k
face_detection:
  enabled: false
server:
  host: 127.0.0.1
  port: 8000
"""
    )

    settings = Settings.load_config(str(config_path))
    profile = settings.get_profile("default")

    assert profile is not None
    assert profile.legacy_managed_roots == [str(legacy_root)]
    assert profile.folders[0].path == str(legacy_root)
    assert "readonly" not in profile.folders[0].model_dump()
    assert "allow_generate" not in profile.folders[0].model_dump()
    assert "is_uploads_folder" not in profile.folders[0].model_dump()
    assert "uploads_subfolder" not in profile.folders[0].model_dump()

    persisted = yaml.safe_load(config_path.read_text())
    persisted_profile = persisted["profiles"][0]
    assert persisted_profile["legacy_managed_roots"] == [str(legacy_root)]
    assert persisted_profile["folders"] == [{"path": str(legacy_root)}]

    monkeypatch.setattr(app_dirs, "get_config_path", lambda: config_path)
    assert remove_profile_section("default", "legacy_managed_roots") is True
    persisted = yaml.safe_load(config_path.read_text())
    assert "legacy_managed_roots" not in persisted["profiles"][0]


def test_new_style_profile_needs_no_sources(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
profiles:
  - id: default
    name: Default
    folders: []
    markers: []
llms: {}
clip:
  model: ViT-g-14
  pretrained: laion2b_s12b_b42k
face_detection:
  enabled: false
server:
  host: 127.0.0.1
  port: 8000
"""
    )

    profile = Settings.load_config(str(config_path)).get_profile("default")

    assert profile is not None
    assert profile.folders == []
    assert profile.legacy_managed_roots == []


def test_fresh_install_config_starts_without_sources(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    config_path = data_dir / "config.yaml"

    monkeypatch.setattr(app_dirs, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(app_dirs, "get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(app_dirs, "get_config_path", lambda: config_path)
    monkeypatch.setattr(
        app_dirs,
        "get_profile_dir",
        lambda profile_id=None: data_dir / "profiles" / (profile_id or "default"),
    )

    created_path = ensure_config_exists()
    profile = Settings.load_config(str(created_path)).profiles[0]

    assert created_path == config_path
    assert profile.folders == []
    assert not (tmp_path / "Documents" / "Stimma").exists()


async def test_settings_exposes_only_external_source_fields(client, tmp_path):
    before = await client.get("/api/settings")
    assert before.status_code == 200
    assert before.json()["folders"] == []

    source = tmp_path / "external-media"
    source.mkdir()
    updated = await client.patch(
        "/api/settings/folders",
        json={
            "folders": [
                {
                    "path": str(source),
                    "refresh_interval_seconds": 300,
                    "markers": [],
                }
            ]
        },
    )
    assert updated.status_code == 200

    from config import reload_settings
    reload_settings()
    response = await client.get("/api/settings")
    folder = response.json()["folders"][0]
    assert folder["path"] == str(source)
    assert "readonly" not in folder
    assert "allow_generate" not in folder
    assert "is_uploads_folder" not in folder
    assert "uploads_subfolder" not in folder

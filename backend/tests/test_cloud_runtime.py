from pathlib import Path

from cloud_runtime import cloud_access_headers, effective_cloud_base_url, env_cloud_base_url, redact_sensitive_headers
from config import Settings


def test_env_cloud_base_url_overrides_config(monkeypatch):
    monkeypatch.setenv("STIMMA_CLOUD_BASE_URL", "https://cloud.example.test/")

    assert env_cloud_base_url() == "https://cloud.example.test"
    assert effective_cloud_base_url("https://stimma.ai") == "https://cloud.example.test"


def test_cloud_access_headers_support_stimma_and_cloudflare_names(monkeypatch):
    monkeypatch.setenv("STIMMA_CLOUD_ACCESS_CLIENT_ID", "client-id")
    monkeypatch.setenv("STIMMA_CLOUD_ACCESS_CLIENT_SECRET", "client-secret")

    assert cloud_access_headers() == {
        "CF-Access-Client-Id": "client-id",
        "CF-Access-Client-Secret": "client-secret",
    }


def test_redacts_cloud_access_headers():
    assert redact_sensitive_headers({
        "Authorization": "Bearer token",
        "CF-Access-Client-Id": "client-id",
        "CF-Access-Client-Secret": "client-secret",
        "Content-Type": "application/json",
    }) == {
        "Authorization": "<redacted>",
        "CF-Access-Client-Id": "<redacted>",
        "CF-Access-Client-Secret": "<redacted>",
        "Content-Type": "application/json",
    }


def test_settings_load_config_applies_runtime_cloud_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("STIMMA_CLOUD_BASE_URL", "https://cloud.example.test")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
profiles:
  - id: default
    name: Default
    folders: []
    markers: []
llms:
  agent:
    source: auto
  agent-fast:
    source: auto
clip:
  model: ViT-g-14
  pretrained: laion2b_s12b_b42k
face_detection:
  enabled: false
server:
  host: 127.0.0.1
  port: 8000
cloud:
  base_url: https://stimma.ai
"""
    )

    settings = Settings.load_config(str(config_path))

    assert settings.cloud.base_url == "https://cloud.example.test"

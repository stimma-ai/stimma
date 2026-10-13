"""App version metadata works without the retired desktop config."""

import json
from types import SimpleNamespace

import pytest

import app_context
import user_agent


@pytest.fixture
def version_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    (repo / "electron").mkdir(parents=True)
    (repo / "electron" / "package.json").write_text(json.dumps({"version": "1.2.3"}))
    monkeypatch.setattr(user_agent, "__file__", str(repo / "backend" / "user_agent.py"))
    monkeypatch.setattr(user_agent, "_app_version", None)
    monkeypatch.delenv("STIMMA_APP_VERSION", raising=False)
    monkeypatch.setattr(app_context, "get_bundle_id", lambda: app_context.BUNDLE_ID_STABLE)
    return repo


def test_source_version_uses_electron_metadata(version_checkout):
    assert user_agent.get_app_version() == "1.2.3"


def test_packaged_version_environment_precedes_source_metadata(version_checkout, monkeypatch):
    monkeypatch.setenv("STIMMA_APP_VERSION", " 4.5.6 ")
    assert user_agent.get_app_version() == "4.5.6"


def test_dev_version_retains_git_identity(version_checkout, monkeypatch):
    monkeypatch.setattr(app_context, "get_bundle_id", lambda: "ai.stimma.stimma.debug")
    monkeypatch.setattr(user_agent.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="abcdef\n"))
    assert user_agent.get_app_version() == "0.0.0-abcdef"


def test_dev_without_git_uses_source_metadata(version_checkout, monkeypatch):
    monkeypatch.setattr(app_context, "get_bundle_id", lambda: "ai.stimma.stimma.debug")
    monkeypatch.setattr(user_agent.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=""))
    assert user_agent.get_app_version() == "1.2.3"


def test_absent_metadata_still_has_a_safe_fallback(version_checkout):
    (version_checkout / "electron" / "package.json").unlink()
    assert user_agent.get_app_version() == "0.0.0"

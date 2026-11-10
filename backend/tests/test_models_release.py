"""`stimma models` (tools/models_release.py): pack builds a release dir from an allowlist
only, verify checks it, publish refuses what it can't verify, pin writes the app's pin."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_prompt_program_fix import tiny_model

spec = importlib.util.spec_from_file_location(
    "models_release", Path(__file__).resolve().parents[2] / "tools" / "models_release.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)

VERSION = "2026-01-02.1"


def source(tmp_path):
    """A model dir as training leaves it: the runtime files plus things that must never ship."""
    d = tiny_model(tmp_path)
    (d / "tokenizer_config.json").write_text(json.dumps({"pad_token": "[PAD]"}))
    (d / "io.json").write_text(json.dumps({"kind": "enc", "inputs": ["input_ids", "attention_mask"],
                                           "output": "probs [fine, odd, wrong]", "maxlen": 128, "cut": 0.2,
                                           "template": "internal.md", "rubric": "p1", "cut_fitted_on": "dev"}))
    (d / "README.md").write_text("internal eval notes")
    (d / "latency_somehost.json").write_text("{}")
    (d / "LICENSE").write_text("Apache-2.0 text")
    return d


def pack(tmp_path, **kw):
    out = tmp_path / "rel" / VERSION
    a = argparse.Namespace(model_dir=str(source(tmp_path)), version=VERSION, model=None, license=None, cut=None,
                           out=str(out), base_model="base/model", license_id="Apache-2.0", metrics=None)
    a.model = str(Path(a.model_dir) / "model.onnx")
    for k, v in kw.items():
        setattr(a, k, v)
    mr.pack(a)
    return out


def test_pack_ships_only_the_allowlist_with_a_trimmed_io_json(tmp_path):
    out = pack(tmp_path, cut=0.3)
    assert sorted(p.name for p in out.iterdir()) == sorted([*mr.ALLOWED, "manifest.json"])
    io = json.loads((out / "io.json").read_text())
    assert set(io) == {"kind", "inputs", "output", "maxlen", "cut"} and io["cut"] == 0.3
    m = json.loads((out / "manifest.json").read_text())
    assert m["name"] == "pick-judge" and m["version"] == VERSION and m["contract"] == 1 and m["cut"] == 0.3
    for f in m["files"]:
        assert f["size"] == (out / f["path"]).stat().st_size
        assert f["sha256"] == hashlib.sha256((out / f["path"]).read_bytes()).hexdigest()
    assert len(m["selftest"]["p_wrong"]) == len(mr.SELFTEST)
    assert "source" not in m and "README" not in json.dumps(m)


def test_verify_refuses_extra_missing_or_altered_files(tmp_path):
    out = pack(tmp_path)
    mr.check_release(out, selftest=True)
    (out / "README.md").write_text("x")
    with pytest.raises(SystemExit):
        mr.check_release(out)
    (out / "README.md").unlink()
    (out / "io.json").write_text("{}")
    with pytest.raises(SystemExit):
        mr.check_release(out)


def test_pack_refuses_local_paths_bad_versions_and_a_used_out_dir(tmp_path):
    with pytest.raises(SystemExit):
        pack(tmp_path, version="v1")
    src = source(tmp_path)
    (src / "tokenizer_config.json").write_text(json.dumps({"pad_token": "[PAD]", "name_or_path": "/home/someone/x"}))
    a = argparse.Namespace(model_dir=str(src), version=VERSION, model=str(src / "model.onnx"), license=None, cut=None,
                           out=str(tmp_path / "r2" / VERSION), base_model="b", license_id="x", metrics=None)
    with pytest.raises(SystemExit):
        mr.pack(a)
    (tmp_path / "again").mkdir()
    out = pack(tmp_path / "again")
    with pytest.raises(SystemExit):
        pack(tmp_path / "again")  # out isn't empty
    assert out.is_dir()


def test_publish_needs_credentials_from_the_environment(tmp_path, monkeypatch):
    out = pack(tmp_path)
    for k in ("R2_S3_ENDPOINT", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "STIMMA_MODELS_R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit):
        mr.publish(argparse.Namespace(release=str(out), bucket=None, base_url=None, dry_run=False))
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://example.com")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    with pytest.raises(SystemExit):  # not an R2 endpoint
        mr.publish(argparse.Namespace(release=str(out), bucket="models", base_url=None, dry_run=False))


def test_verify_against_a_mirror(tmp_path, local_model_mirror):
    out = pack(tmp_path)
    m = json.loads((out / "manifest.json").read_text())
    dest = local_model_mirror.root / "pick-judge" / VERSION
    dest.mkdir(parents=True)
    for p in out.iterdir():
        (dest / p.name).write_bytes(p.read_bytes())
    mr.check_remote(m, local_model_mirror.url)
    (dest / "io.json").write_text("{}")
    with pytest.raises(SystemExit):
        mr.check_remote(m, local_model_mirror.url)


def test_publish_dry_run_output(tmp_path, capsys):
    out = pack(tmp_path)
    capsys.readouterr()
    mr.publish(argparse.Namespace(release=str(out), bucket="models", base_url=None, dry_run=True))
    plan = json.loads(capsys.readouterr().out)
    assert plan["prefix"] == f"pick-judge/{VERSION}" and plan["upload"][-1] == "manifest.json"
    assert set(plan["upload"]) == {*mr.ALLOWED, "manifest.json"}


def test_pin_copies_the_manifest_verbatim(tmp_path, monkeypatch):
    out = pack(tmp_path)
    monkeypatch.setattr(mr, "PINS", tmp_path / "pins")
    monkeypatch.setattr(mr, "REPO", tmp_path)
    pin = mr.write_pin(out)
    assert pin.read_bytes() == (out / "manifest.json").read_bytes()

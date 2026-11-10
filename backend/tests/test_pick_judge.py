"""The pinned pick judge: on by default, downloaded in the background on first use,
never blocking a draw, degrading to unjudged draws on any failure, and recorded by
version in every judged draw."""

import argparse
import json
import threading
import time
from pathlib import Path

import pytest

import model_cache
from prompt_programs import pick_judge
from prompt_programs.fix import fix_mode, judge_identity, realize_and_fix
from prompt_programs.judge import FluentSettings
from tests.test_models_release import mr
from tests.test_prompt_program_fix import draw, entry_for, no_profile, seed_where, tiny_model, values  # noqa: F401

VERSION = "2026-01-02.1"
DEFAULT = FluentSettings(generate_options=False)  # fix_model: default


def build_release(tmp_path, version=VERSION, **manifest_overrides):
    """A real release dir (the tiny ONNX judge: "moonlight" is wrong), packed by `stimma models pack`."""
    (tmp_path / f"src-{version}").mkdir(parents=True, exist_ok=True)
    src = tiny_model(tmp_path / f"src-{version}", probs=True)
    (src / "tokenizer_config.json").write_text(json.dumps({"pad_token": "[PAD]"}))
    (src / "io.json").write_text(json.dumps({"kind": "enc", "output": "probs", "maxlen": 128, "cut": 0.5}))
    (src / "LICENSE").write_text("Apache-2.0")
    out = tmp_path / "releases" / version
    mr.pack(argparse.Namespace(model_dir=str(src), version=version, model=str(src / "model.onnx"), license=None,
                               cut=None, out=str(out), base_model="b", license_id="Apache-2.0", metrics=None))
    if manifest_overrides:
        m = json.loads((out / "manifest.json").read_text())
        m.update(manifest_overrides)
        (out / "manifest.json").write_text(json.dumps(m))
    return out


@pytest.fixture
def release(tmp_path, local_model_mirror, monkeypatch):
    """The tiny judge published to the loopback mirror and pinned."""
    out = build_release(tmp_path)
    dest = local_model_mirror.root / "pick-judge" / VERSION
    dest.mkdir(parents=True)
    for p in out.iterdir():
        (dest / p.name).write_bytes(p.read_bytes())
    pin = tmp_path / "pick-judge.json"
    pin.write_bytes((out / "manifest.json").read_bytes())
    monkeypatch.setattr(pick_judge, "MANIFEST_PATH", pin)
    pick_judge.reset()
    local_model_mirror.manifest = json.loads(pin.read_text())
    local_model_mirror.pin = pin
    yield local_model_mirror
    pick_judge.reset()


def model_hits(mirror):
    return [h for h in mirror.hits if h.endswith(".onnx")]


def moonlit(entry):
    s, _ = seed_where(entry, lambda v: v["light"] == "moonlight")
    return s


# --------------------------------------------------------------------------- on by default

def test_the_judge_is_on_by_default(monkeypatch):
    import config
    from prompt_programs.judge import settings
    assert config.FluentConfig().fix_model == "default" and FluentSettings().fix_model == "default"
    monkeypatch.delenv("STIMMA_FLUENT_FIX_MODEL", raising=False)
    monkeypatch.setattr(config, "get_settings", lambda: type("S", (), {"fluent": config.FluentConfig()})())
    assert settings().fix_model == "default"
    assert [fix_mode(x) for x in ("default", " Default ", "", "off", "OFF", "none", "/models/j")] == \
        ["default", "default", "off", "off", "off", "off", "dir"]


def test_the_committed_pin_is_a_v1_release():
    pick_judge.reset()
    m = pick_judge.manifest()
    assert m["name"] == "pick-judge" and m["contract"] in pick_judge.CONTRACTS
    assert {f["path"] for f in m["files"]} == set(mr.ALLOWED) and m["model"] == "model.int8.onnx"
    assert pick_judge.version_of(m) == f"pick-judge/{m['version']}@{pick_judge.model_file(m)['sha256'][:12]}"
    assert 0 < m["cut"] < 1 and len(m["selftest"]["p_wrong"]) == len(m["selftest"]["items"])


# --------------------------------------------------------------------------- first use

def test_first_use_never_blocks_then_judges_and_records_the_version(release):
    entry = entry_for()
    s = moonlit(entry)
    gate = threading.Event()

    def hold(h, path):
        if path.endswith(".onnx"):
            gate.wait(10)
        return False

    release.handler = hold
    started = time.monotonic()
    out, rec = realize_and_fix(entry, seed=s, cfg=DEFAULT)
    assert time.monotonic() - started < 2  # the draw didn't wait for the download
    assert rec == {"judge": f"pick-judge/{VERSION}", "skipped": "downloading"}
    assert values(out)["light"] == "moonlight" and out.prompt == draw(entry, s).prompt  # shipped unjudged
    assert pick_judge.status()["status"] == "downloading"
    assert judge_identity(DEFAULT) == f"pick-judge/{VERSION}:downloading"
    gate.set()
    assert pick_judge.wait(20)
    st = pick_judge.status()
    assert st["status"] == "ready" and st["version"] == pick_judge.version_of(release.manifest)
    out, rec = realize_and_fix(entry, seed=s, cfg=DEFAULT)
    assert rec["judge"] == pick_judge.version_of(release.manifest) and rec["judge"].startswith(f"pick-judge/{VERSION}@")
    assert rec["rerolls"] >= 1 and values(out)["light"] != "moonlight" and rec["cut"] == 0.5
    assert judge_identity(DEFAULT) == f"{rec['judge']}:ready"
    assert len(model_hits(release)) == 1


def test_a_cached_judge_loads_with_zero_network(release):
    pick_judge.kick()
    assert pick_judge.wait(20)
    hits = list(release.hits)
    pick_judge.reset()  # a new process: nothing loaded, the cache on disk
    j = pick_judge.ready()
    assert j is not None and j.version == pick_judge.version_of(release.manifest)
    entry = entry_for()
    out, rec = realize_and_fix(entry, seed=moonlit(entry), cfg=DEFAULT)
    assert rec["rerolls"] >= 1 and release.hits == hits


def test_prepare_starts_the_download(release):
    from prompt_programs.fluent import start_options
    start_options(entry_for(), cfg=DEFAULT)
    assert pick_judge.wait(20) and model_hits(release)


def test_other_versions_are_removed_once_the_pin_verifies(release):
    old = model_cache.models_root() / "pick-judge" / "2025-12-01.1"
    old.mkdir(parents=True)
    (old / "model.int8.onnx").write_bytes(b"old")
    pick_judge.kick()
    assert pick_judge.wait(20)
    assert not old.exists() and (model_cache.models_root() / "pick-judge" / VERSION / ".verified").exists()


# --------------------------------------------------------------------------- failures

def test_offline_ships_unjudged_logs_once_and_retries_later(release, monkeypatch, caplog):
    release.handler = lambda h, path: (h.send_error(503), True)[1]
    entry = entry_for()
    realize_and_fix(entry, seed=1, cfg=DEFAULT)
    pick_judge.wait(20)
    r, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert rec["skipped"] == "unavailable" and "503" in rec["error"] and r.prompt == draw(entry, 1).prompt
    tries = len(model_hits(release))
    for s in range(2, 6):  # within RETRY_SECONDS: no new attempts, whatever the draws
        realize_and_fix(entry, seed=s, cfg=DEFAULT)
    assert len(model_hits(release)) == tries
    monkeypatch.setattr(pick_judge, "RETRY_SECONDS", 0.0)
    release.handler = None
    realize_and_fix(entry, seed=7, cfg=DEFAULT)
    assert pick_judge.wait(20) and len(model_hits(release)) == tries + 1


def test_lockdown_with_nothing_cached_fetches_nothing(release, monkeypatch):
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    monkeypatch.setenv("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai")
    entry = entry_for()
    realize_and_fix(entry, seed=1, cfg=DEFAULT)
    pick_judge.wait(20)
    _, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert rec["skipped"] == "lockdown" and release.hits == []
    assert pick_judge.status()["status"] == "lockdown"


def test_a_hash_mismatch_degrades_to_unjudged(release):
    f = release.root / "pick-judge" / VERSION / "tokenizer.json"
    data = bytearray(f.read_bytes())
    data[5] ^= 1
    f.write_bytes(bytes(data))
    entry = entry_for()
    realize_and_fix(entry, seed=1, cfg=DEFAULT)
    pick_judge.wait(30)
    r, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert rec["skipped"] == "unavailable" and "sha256" in rec["error"]
    assert not (model_cache.models_root() / "pick-judge" / VERSION / ".verified").exists()


def test_a_model_onnxruntime_cant_load_is_an_error_for_the_session(release, tmp_path, monkeypatch):
    bad = b"not an onnx model"
    dest = release.root / "pick-judge" / VERSION / "model.int8.onnx"
    dest.write_bytes(bad)
    m = dict(release.manifest)
    m["files"] = [dict(f, size=len(bad), sha256=__import__("hashlib").sha256(bad).hexdigest())
                  if f["path"] == "model.int8.onnx" else f for f in m["files"]]
    release.pin.write_text(json.dumps(m))
    pick_judge.reset()
    entry = entry_for()
    realize_and_fix(entry, seed=1, cfg=DEFAULT)
    pick_judge.wait(20)
    r, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert rec["skipped"] == "error" and "didn't load" in rec["error"] and r.prompt == draw(entry, 1).prompt
    monkeypatch.setattr(pick_judge, "RETRY_SECONDS", 0.0)
    hits = len(release.hits)
    realize_and_fix(entry, seed=2, cfg=DEFAULT)
    assert len(release.hits) == hits  # not retried: an app update fixes it


def test_an_unknown_contract_downloads_nothing(release):
    m = dict(release.manifest, contract=99)
    release.pin.write_text(json.dumps(m))
    pick_judge.reset()
    entry = entry_for()
    realize_and_fix(entry, seed=1, cfg=DEFAULT)
    pick_judge.wait(20)
    _, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert rec["skipped"] == "error" and "contract 99" in rec["error"] and release.hits == []


def test_off_and_a_local_directory_still_work(release, tmp_path):
    entry = entry_for()
    s = moonlit(entry)
    assert realize_and_fix(entry, seed=s, cfg=FluentSettings(generate_options=False, fix_model="off"))[1] is None
    assert realize_and_fix(entry, seed=s, cfg=FluentSettings(generate_options=False, fix_model=""))[1] is None
    (tmp_path / "dev").mkdir()
    d = tiny_model(tmp_path / "dev")
    _, rec = realize_and_fix(entry, seed=s, cfg=FluentSettings(generate_options=False, fix_model=str(d)))
    assert rec["judge"].startswith("onnx:") and rec["rerolls"] >= 1
    assert release.hits == []


# --------------------------------------------------------------------------- reuse and status

def test_the_hot_draw_signature_changes_when_the_judge_becomes_ready(release, monkeypatch):
    from routes.generation import hot_draw_signature
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    entry = entry_for()
    sig = lambda: hot_draw_signature(entry, {}, triggers=True, profile_id=None, project_id=None)  # noqa: E731
    before = sig()
    pick_judge.kick()
    assert pick_judge.wait(20)
    assert sig() != before
    ready = sig()
    pick_judge.reset()  # unloaded, still on disk: the next draw is judged, so the same signature
    assert sig() == ready


async def test_the_settings_route_reports_the_pinned_judge(release, monkeypatch):
    import httpx
    from fastapi import FastAPI
    import config
    from routes import prompt_programs as route
    runtime = type("S", (), {"fluent": config.FluentConfig()})()
    monkeypatch.setattr(config, "get_settings", lambda: runtime)
    monkeypatch.delenv("STIMMA_FLUENT_FIX_MODEL", raising=False)
    app = FastAPI()
    app.include_router(route.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = (await c.get("/api/prompt-programs/fix-judge")).json()
        assert r == {"model": "default", "status": "idle", "version": f"pick-judge/{VERSION}"}
        assert release.hits == []  # reading the status never starts the download
        pick_judge.kick()
        assert pick_judge.wait(20)
        r = (await c.get("/api/prompt-programs/fix-judge")).json()
        assert r["status"] == "ready" and r["version"] == pick_judge.version_of(release.manifest) and r["cut"] == 0.5

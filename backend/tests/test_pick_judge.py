"""The pinned pick judge: on by default, downloaded in the background; a draw never waits
for it. Until it's loaded, or when it can't be had, the Tool View model stands in, and a draw
ships unjudged only when neither is there. Recorded by version in every judged draw."""

import argparse
import json
import threading
import time

import pytest

import model_cache
from prompt_programs import llm_judge, pick_judge
from prompt_programs.fix import await_judge, fix_mode, judge_identity, realize_and_fix
from prompt_programs.judge import FluentSettings
from tests.test_models_release import mr
from tests.test_prompt_program_fix import PROFILE, draw, entry_for, seed_where, tiny_model, values

VERSION = "2026-01-02.1"
DEFAULT = FluentSettings()  # fix_model: default


def build_release(tmp_path, version=VERSION, **manifest_overrides):
    """A real release dir (the tiny ONNX judge: "moonlight" is wrong), packed by `stimma models pack`."""
    (tmp_path / f"src-{version}").mkdir(parents=True, exist_ok=True)
    src = tiny_model(tmp_path / f"src-{version}", probs=True)
    (src / "tokenizer_config.json").write_text(json.dumps({"pad_token": "[PAD]"}))
    (src / "io.json").write_text(json.dumps({"kind": "enc", "output": "probs", "maxlen": 128, "cut": 0.5}))
    (src / "LICENSE").write_text("MIT")
    out = tmp_path / "releases" / version
    mr.pack(argparse.Namespace(model_dir=str(src), version=version, model=str(src / "model.onnx"), license=None,
                               cut=None, out=str(out), base_model="b", license_id="MIT", metrics=None))
    if manifest_overrides:
        m = json.loads((out / "manifest.json").read_text())
        m.update(manifest_overrides)
        (out / "manifest.json").write_text(json.dumps(m))
    return out


@pytest.fixture
def release(tmp_path, local_model_mirror, monkeypatch):
    """The tiny judge published to the loopback mirror and pinned; no stand-in judge."""
    out = build_release(tmp_path)
    dest = local_model_mirror.root / "pick-judge" / VERSION
    dest.mkdir(parents=True)
    for p in out.iterdir():
        (dest / p.name).write_bytes(p.read_bytes())
    pin = tmp_path / "pick-judge.json"
    pin.write_bytes((out / "manifest.json").read_bytes())
    monkeypatch.setattr(pick_judge, "MANIFEST_PATH", pin)
    monkeypatch.setattr(pick_judge, "ENABLED", True)
    monkeypatch.setattr(llm_judge, "_judges", {})
    pick_judge.reset()
    local_model_mirror.manifest = json.loads(pin.read_text())
    local_model_mirror.pin = pin
    yield local_model_mirror
    pick_judge.reset()


class StandIn:
    """The Tool View model as llm_judge gives it: every pick fits; counts what it was asked."""
    version = "llm:stand-in/r2"
    cut = 0.5
    reroll_all = True

    def __init__(self):
        self.asked = []

    def p_wrong(self, items):
        self.asked.append(list(items))
        return [0.0] * len(items)


@pytest.fixture
def stand_in(monkeypatch):
    j = StandIn()
    monkeypatch.setitem(llm_judge._judges, None, j)
    return j


def judged(entry, seed, cfg=DEFAULT):
    return realize_and_fix(entry, seed=seed, cfg=cfg, profile_id=PROFILE)


def model_hits(mirror):
    return [h for h in mirror.hits if h.endswith(".onnx")]


def moonlit(entry):
    s, _ = seed_where(entry, lambda v: v["light"] == "moonlight")
    return s


def hold_file(name, gate):
    """A mirror handler holding `name`'s request until `gate` is set."""
    def handler(h, path):
        if path.endswith(name):
            gate.wait(20)
        return False
    return handler


def until(pred, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


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


def test_the_committed_pin_is_the_trained_judge():
    pick_judge.reset()
    m = pick_judge.manifest()
    assert m["name"] == "pick-judge" and m["contract"] in pick_judge.CONTRACTS and m["version"] == "2026-11-17.1"
    assert {f["path"] for f in m["files"]} == set(mr.ALLOWED) and m["model"] == "model.int8.onnx"
    assert m["kind"] == "enc" and m["maxlen"] == 512 and m["labels"] == ["fine", "odd", "wrong"]
    assert m["cut"] == 0.4677 and m["base_model"] == "microsoft/deberta-v3-large"
    assert pick_judge.version_of(m) == f"pick-judge/{m['version']}@{pick_judge.model_file(m)['sha256'][:12]}"
    assert len(m["selftest"]["p_wrong"]) == len(m["selftest"]["items"])


@pytest.mark.parametrize("branch", ["dev", "canary", "beta", "production"])
def test_preload_judge_kicks_on_all_branches(branch, monkeypatch):
    import user_agent
    from prompt_programs import fix
    monkeypatch.setattr(user_agent, "_app_branch", branch)
    kicked = []
    monkeypatch.setattr(fix, "kick_judge", lambda cfg=None: kicked.append(branch))
    fix.preload_judge()
    assert kicked == [branch]


# --------------------------------------------------------------------------- first use never waits

def test_while_it_downloads_the_stand_in_judges_and_then_the_pinned_judge_does(release, stand_in):
    entry = entry_for()
    s = moonlit(entry)
    gate = threading.Event()
    release.handler = hold_file("tokenizer.json", gate)  # the model is in, the tokenizer is held
    started = time.monotonic()
    r, rec = judged(entry, s)
    assert time.monotonic() - started < 3   # the draw didn't wait for the download
    assert rec["judge"] == stand_in.version and stand_in.asked and values(r)["light"] == "moonlight"
    assert pick_judge.status()["status"] == "downloading"
    assert judge_identity(DEFAULT).startswith(f"pick-judge/{VERSION}:downloading|")
    gate.set()
    assert pick_judge.wait(20)
    r, rec = judged(entry, s)
    assert rec["judge"] == pick_judge.version_of(release.manifest) and rec["judge"].startswith(f"pick-judge/{VERSION}@")
    assert rec["rerolls"] >= 1 and values(r)["light"] != "moonlight" and rec["cut"] == 0.5
    assert judge_identity(DEFAULT) == f"{rec['judge']}:ready"
    assert len(model_hits(release)) == 1


def test_without_either_judge_the_draw_ships_unjudged_and_says_so(release):
    gate = threading.Event()
    release.handler = hold_file(".onnx", gate)
    entry = entry_for()
    r, rec = judged(entry, 1)
    assert rec == {"judge": f"pick-judge/{VERSION}", "skipped": "unavailable"}
    assert r.prompt == draw(entry, 1).prompt
    gate.set()
    assert pick_judge.wait(20)


async def test_await_judge_readies_the_stand_in_only_while_the_judge_isnt_loaded(release, monkeypatch):
    readied = []

    async def ready(project_id=None):
        readied.append(project_id)
    monkeypatch.setattr(llm_judge, "ready", ready)
    entry = entry_for()
    await await_judge(entry, DEFAULT, project_id=3)
    assert readied == [3]   # and the download started
    assert pick_judge.wait(20)
    await await_judge(entry, DEFAULT, project_id=3)
    assert readied == [3]


def test_a_cached_judge_loads_with_zero_network(release, stand_in):
    pick_judge.kick()
    assert pick_judge.wait(20)
    hits = list(release.hits)
    pick_judge.reset()  # a new process: nothing loaded, the cache on disk
    entry = entry_for()
    out, rec = judged(entry, moonlit(entry))   # the first draw after a restart: the pinned judge
    assert rec["judge"].startswith(f"pick-judge/{VERSION}@") and rec["rerolls"] >= 1
    assert release.hits == hits and not stand_in.asked


def test_other_versions_are_removed_once_the_pin_verifies(release):
    old = model_cache.models_root() / "pick-judge" / "2025-01-01.1"
    old.mkdir(parents=True)
    (old / "model.int8.onnx").write_bytes(b"x")
    pick_judge.kick()
    assert pick_judge.wait(20)
    assert not old.exists() and (model_cache.models_root() / "pick-judge" / VERSION).is_dir()


# --------------------------------------------------------------------------- degrade, don't fail

def test_offline_falls_back_logs_once_and_retries_in_the_background(release, stand_in, monkeypatch, caplog):
    monkeypatch.setattr(pick_judge, "FIRST_RETRY_SECONDS", 0.3)
    release.handler = lambda h, path: (h.send_error(503), True)[1]
    entry = entry_for()
    for s in range(1, 5):
        _, rec = judged(entry, s)
        assert rec["judge"] == stand_in.version
    assert until(lambda: len(model_hits(release)) >= 2 * model_cache.BUNDLE_TRIES)   # retried by itself
    warnings = [r for r in caplog.records if "isn't available" in r.getMessage() and r.levelname == "WARNING"]
    assert len(warnings) == 1
    release.handler = None  # back online: the next retry gets it, no draw needed
    assert until(lambda: pick_judge.status()["status"] == "ready")
    _, rec = judged(entry, moonlit(entry))
    assert rec["judge"].startswith(f"pick-judge/{VERSION}@") and rec["rerolls"] >= 1


def test_lockdown_with_nothing_cached_fetches_nothing(release, stand_in, monkeypatch):
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    monkeypatch.setenv("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai")
    entry = entry_for()
    _, rec = judged(entry, 1)
    assert until(lambda: pick_judge.status()["status"] == "lockdown")
    _, rec = judged(entry, 2)
    assert rec["judge"] == stand_in.version and release.hits == []


def test_a_lockdown_with_the_judge_cached_judges(release, monkeypatch):
    pick_judge.kick()
    assert pick_judge.wait(20)
    pick_judge.reset()
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    monkeypatch.setenv("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai")
    entry = entry_for()
    _, rec = judged(entry, moonlit(entry))
    assert rec["rerolls"] >= 1 and rec["judge"].startswith("pick-judge/")


def test_a_hash_mismatch_falls_back(release, stand_in):
    f = release.root / "pick-judge" / VERSION / "tokenizer.json"
    data = bytearray(f.read_bytes())
    data[5] ^= 1
    f.write_bytes(bytes(data))
    pick_judge.kick()
    assert until(lambda: pick_judge.status()["status"] == "unavailable")
    assert "sha256" in pick_judge.status()["error"]
    _, rec = judged(entry_for(), 1)
    assert rec["judge"] == stand_in.version
    assert not (model_cache.models_root() / "pick-judge" / VERSION / ".verified").exists()


def test_a_model_onnxruntime_cant_load_is_an_error_for_the_session(release, stand_in, monkeypatch):
    bad = b"not an onnx model"
    (release.root / "pick-judge" / VERSION / "model.int8.onnx").write_bytes(bad)
    m = dict(release.manifest)
    m["files"] = [dict(f, size=len(bad), sha256=__import__("hashlib").sha256(bad).hexdigest())
                  if f["path"] == "model.int8.onnx" else f for f in m["files"]]
    release.pin.write_text(json.dumps(m))
    pick_judge.reset()
    pick_judge.kick()
    assert until(lambda: pick_judge.status()["status"] == "error")
    assert "didn't load" in pick_judge.status()["error"]
    entry = entry_for()
    r, rec = judged(entry, 1)
    assert rec["judge"] == stand_in.version
    monkeypatch.setattr(pick_judge, "RETRY_SECONDS", 0.0)
    hits = len(release.hits)
    pick_judge.kick(retry=True)
    judged(entry, 2)
    assert len(release.hits) == hits  # not retried: an app update fixes it


def test_an_unknown_contract_downloads_nothing(release, stand_in):
    release.pin.write_text(json.dumps(dict(release.manifest, contract=99)))
    pick_judge.reset()
    _, rec = judged(entry_for(), 1)
    assert until(lambda: pick_judge.status()["status"] == "error")
    assert "contract 99" in pick_judge.status()["error"] and release.hits == [] and rec["judge"] == stand_in.version


def test_off_and_a_local_directory_still_work(release, tmp_path):
    entry = entry_for()
    s = moonlit(entry)
    assert judged(entry, s, cfg=FluentSettings(fix_model="off"))[1] is None
    assert judged(entry, s, cfg=FluentSettings(fix_model=""))[1] is None
    (tmp_path / "dev").mkdir()
    d = tiny_model(tmp_path / "dev")
    _, rec = judged(entry, s, cfg=FluentSettings(fix_model=str(d)))
    assert rec["judge"].startswith("onnx:") and rec["rerolls"] >= 1
    assert release.hits == []


# --------------------------------------------------------------------------- reuse and status

def test_the_hot_draw_signature_changes_when_the_judge_becomes_ready(release, monkeypatch):
    from routes.generation import hot_draw_signature
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    entry = entry_for()

    def sig():
        return hot_draw_signature(entry, pins={}, edits={}, chosen={}, profile_id=None, project_id=None)
    before = sig()
    pick_judge.kick()
    assert pick_judge.wait(20)
    assert sig() != before
    ready = sig()
    pick_judge.reset()  # unloaded, still on disk: the next draw is judged by it, so the same signature
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
        gate = threading.Event()
        release.handler = hold_file(".onnx", gate)
        r = (await c.get("/api/prompt-programs/fix-judge", params={"start": 1})).json()
        assert r["status"] == "downloading"
        gate.set()
        assert pick_judge.wait(20)
        r = (await c.get("/api/prompt-programs/fix-judge")).json()
        assert r["status"] == "ready" and r["version"] == pick_judge.version_of(release.manifest) and r["cut"] == 0.5


def test_an_agents_result_mentions_unchecked_choices_only_when_it_happened():
    from agent.v2.prompt_handling import UNCHECKED_NOTE, unchecked_note
    assert unchecked_note({"fix": {"judge": "pick-judge/x", "skipped": "unavailable"}}) == UNCHECKED_NOTE
    assert unchecked_note({"fix": {"judge": "pick-judge/x", "rerolls": 0}}) is None
    assert unchecked_note({"fix": {"judge": "pick-judge/x", "skipped": "one part"}}) is None
    assert "chat model" not in UNCHECKED_NOTE

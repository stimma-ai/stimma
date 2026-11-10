"""The pinned pick judge: on by default, downloaded in the background from launch; a
draw that needs it waits for it while the download makes progress, and ships
unjudged, with the reason in its record, only when it can't be had. Recorded by
version in every judged draw."""

import argparse
import asyncio
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

def hold_file(name, gate):
    """A mirror handler holding `name`'s request until `gate` is set."""
    def handler(h, path):
        if path.endswith(name):
            gate.wait(20)
        return False
    return handler


def test_first_use_waits_with_progress_then_judges_and_records_the_version(release):
    entry = entry_for()
    s = moonlit(entry)
    gate = threading.Event()
    release.handler = hold_file("tokenizer.json", gate)  # the model is in, the tokenizer is held
    out = {}
    t = threading.Thread(target=lambda: out.update(r=realize_and_fix(entry, seed=s, cfg=DEFAULT)))
    t.start()
    for _ in range(200):
        st = pick_judge.status()
        if st.get("percent", 0) > 0:
            break
        time.sleep(0.02)
    assert st["status"] == "downloading" and st["waiting"] and 0 < st["percent"] < 100
    assert "unjudged" not in st and t.is_alive()  # the draw is waiting, not shipped unjudged
    assert judge_identity(DEFAULT) == f"pick-judge/{VERSION}:downloading"
    gate.set()
    t.join(20)
    r, rec = out["r"]
    assert rec["judge"] == pick_judge.version_of(release.manifest) and rec["judge"].startswith(f"pick-judge/{VERSION}@")
    assert rec["rerolls"] >= 1 and values(r)["light"] != "moonlight" and rec["cut"] == 0.5
    assert pick_judge.status()["status"] == "ready" and not pick_judge.status()["waiting"]
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


def test_a_draw_right_after_launch_waits_for_a_cached_load_not_the_network(release):
    pick_judge.kick()
    assert pick_judge.wait(20)
    pick_judge.reset()  # restart: cached on disk
    pick_judge.kick()   # launch starts loading it on the background thread
    entry = entry_for()
    _, rec = realize_and_fix(entry, seed=moonlit(entry), cfg=DEFAULT)
    assert rec["judge"] == pick_judge.version_of(release.manifest) and rec["rerolls"] >= 1


def test_launch_starts_the_download_in_builds_with_fluent(release, monkeypatch):
    import user_agent
    from prompt_programs.fix import preload_judge
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    monkeypatch.setattr(user_agent, "get_app_branch", lambda: "production")
    preload_judge()
    assert pick_judge.status()["status"] == "idle" and release.hits == []
    monkeypatch.setattr(user_agent, "get_app_branch", lambda: "canary")
    preload_judge()
    assert pick_judge.wait(20) and model_hits(release)  # before any prepare or draw
    pick_judge.reset()
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "off")
    preload_judge()
    assert pick_judge.status()["status"] == "idle"


def test_prepare_starts_the_download(release):
    from prompt_programs.fluent import start_options
    start_options(entry_for(), cfg=DEFAULT)
    assert pick_judge.wait(20) and model_hits(release)


async def test_the_prepare_runs_while_the_judge_downloads(release, monkeypatch):
    """Launch starts the download; the prompt's prepare (the chat model) runs meanwhile,
    so a first image waits for the longer of the two, not both."""
    import asyncio
    from prompt_programs.fix import await_judge
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    gate = threading.Event()
    release.handler = hold_file(".onnx", gate)
    threading.Timer(0.8, gate.set).start()
    pick_judge.kick()  # launch
    started = time.monotonic()

    async def prepare():  # the chat model reading the prompt
        await asyncio.sleep(0.8)
        return entry_for()

    entry = await prepare()
    await await_judge(entry)
    assert pick_judge.status()["status"] == "ready"
    assert time.monotonic() - started < 1.5


async def test_a_waiting_generation_can_be_cancelled_and_the_download_carries_on(release, monkeypatch):
    import asyncio
    from prompt_programs.fix import await_judge
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    gate = threading.Event()
    release.handler = hold_file(".onnx", gate)
    task = asyncio.ensure_future(await_judge(entry_for()))
    await asyncio.sleep(0.3)
    assert not task.done() and pick_judge.waiting()
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 0.5
    # a thread waiting in get() stops too
    assert pick_judge.get(cancelled=lambda: True) is None
    gate.set()
    assert pick_judge.wait(20) and pick_judge.status()["status"] == "ready"


def test_other_versions_are_removed_once_the_pin_verifies(release):
    old = model_cache.models_root() / "pick-judge" / "2025-12-01.1"
    old.mkdir(parents=True)
    (old / "model.int8.onnx").write_bytes(b"old")
    pick_judge.kick()
    assert pick_judge.wait(20)
    assert not old.exists() and (model_cache.models_root() / "pick-judge" / VERSION / ".verified").exists()


def test_shutdown_stops_the_download_and_its_bytes_resume_next_launch(release):
    data = (release.root / "pick-judge" / VERSION / "model.int8.onnx").read_bytes()
    gate = threading.Event()

    def trickle(h, path):  # the model in two halves, the second held
        if not path.endswith(".onnx") or h.headers.get("Range"):
            return False
        h.send_response(200)
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data[:len(data) // 2])
        h.wfile.flush()
        gate.wait(5)
        return True

    release.handler = trickle
    pick_judge.kick()
    time.sleep(0.3)
    pick_judge.shutdown()
    gate.set()
    pick_judge._state.worker.join(10)
    assert pick_judge.status()["status"] != "ready"
    pick_judge.reset()  # the next launch
    release.handler = None
    pick_judge.kick()
    assert pick_judge.wait(20)
    assert release.ranges and release.ranges[0][0].endswith(".onnx")  # only the rest was fetched


# --------------------------------------------------------------------------- when it can't be had

def test_a_stalled_download_stops_the_wait_and_records_why(release, monkeypatch):
    monkeypatch.setattr(pick_judge, "STALL_SECONDS", 0.5)
    gate = threading.Event()
    release.handler = hold_file(".onnx", gate)
    entry = entry_for()
    started = time.monotonic()
    r, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert 0.4 < time.monotonic() - started < 3
    assert rec["skipped"] == "stalled" and "progress" in rec["error"] and r.prompt == draw(entry, 1).prompt
    st = pick_judge.status()
    assert st["unjudged"] == "stalled" and not st["waiting"]
    gate.set()  # the download carries on in the background; later draws are judged
    assert pick_judge.wait(20)
    _, rec = realize_and_fix(entry, seed=moonlit(entry), cfg=DEFAULT)
    assert rec["rerolls"] >= 1 and "skipped" not in rec


def test_offline_ships_unjudged_logs_once_and_retries_in_the_background(release, monkeypatch, caplog):
    monkeypatch.setattr(pick_judge, "FIRST_RETRY_SECONDS", 0.3)
    release.handler = lambda h, path: (h.send_error(503), True)[1]
    entry = entry_for()
    started = time.monotonic()
    r, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert time.monotonic() - started < 3  # a failure stops the wait at once
    assert rec["skipped"] == "unavailable" and "503" in rec["error"] and r.prompt == draw(entry, 1).prompt
    assert pick_judge.status()["unjudged"] == "unavailable"
    for s in range(2, 5):  # meanwhile draws don't wait or start downloads of their own
        realize_and_fix(entry, seed=s, cfg=DEFAULT)
    time.sleep(0.8)
    assert len(model_hits(release)) >= 2 * model_cache.BUNDLE_TRIES  # the worker retried by itself
    warnings = [r for r in caplog.records if "isn't available" in r.getMessage() and r.levelname == "WARNING"]
    assert len(warnings) == 1
    release.handler = None  # back online: the next retry gets it, no draw needed
    for _ in range(100):
        if pick_judge.status()["status"] == "ready":
            break
        time.sleep(0.05)
    _, rec = realize_and_fix(entry, seed=moonlit(entry), cfg=DEFAULT)
    assert rec["rerolls"] >= 1 and "skipped" not in rec


def test_try_again_ends_the_pause_between_retries(release, monkeypatch):
    monkeypatch.setattr(pick_judge, "FIRST_RETRY_SECONDS", 60.0)
    release.handler = lambda h, path: (h.send_error(503), True)[1]
    pick_judge.kick()
    for _ in range(100):
        if pick_judge.status()["status"] == "unavailable":
            break
        time.sleep(0.02)
    release.handler = None
    pick_judge.kick(retry=True)
    assert pick_judge.wait(20)


def test_lockdown_with_nothing_cached_fetches_nothing_and_never_waits(release, monkeypatch):
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    monkeypatch.setenv("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai")
    entry = entry_for()
    started = time.monotonic()
    _, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert time.monotonic() - started < 2
    assert rec["skipped"] == "lockdown" and release.hits == []
    st = pick_judge.status()
    assert st["status"] == "lockdown" and st["unjudged"] == "lockdown" and not st["waiting"]
    realize_and_fix(entry, seed=2, cfg=DEFAULT)
    assert pick_judge._state.worker is None or not pick_judge._state.worker.is_alive()  # no retry loop


def test_a_lockdown_with_the_judge_cached_judges(release, monkeypatch):
    pick_judge.kick()
    assert pick_judge.wait(20)
    pick_judge.reset()
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    monkeypatch.setenv("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai")
    entry = entry_for()
    _, rec = realize_and_fix(entry, seed=moonlit(entry), cfg=DEFAULT)
    assert rec["rerolls"] >= 1


def test_a_hash_mismatch_degrades_to_unjudged(release):
    f = release.root / "pick-judge" / VERSION / "tokenizer.json"
    data = bytearray(f.read_bytes())
    data[5] ^= 1
    f.write_bytes(bytes(data))
    entry = entry_for()
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
    r, rec = realize_and_fix(entry, seed=1, cfg=DEFAULT)
    assert rec["skipped"] == "error" and "didn't load" in rec["error"] and r.prompt == draw(entry, 1).prompt
    monkeypatch.setattr(pick_judge, "RETRY_SECONDS", 0.0)
    hits = len(release.hits)
    realize_and_fix(entry, seed=2, cfg=DEFAULT)
    pick_judge.kick(retry=True)
    assert len(release.hits) == hits  # not retried: an app update fixes it


def test_an_unknown_contract_downloads_nothing(release):
    m = dict(release.manifest, contract=99)
    release.pin.write_text(json.dumps(m))
    pick_judge.reset()
    entry = entry_for()
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
        assert r == {"model": "default", "status": "idle", "version": f"pick-judge/{VERSION}", "waiting": False}
        assert release.hits == []  # reading the status never starts the download
        gate = threading.Event()
        release.handler = hold_file(".onnx", gate)
        r = (await c.get("/api/prompt-programs/fix-judge", params={"start": 1})).json()
        assert r["status"] == "downloading" and r["waiting"] and "unjudged" not in r  # Tool View waits
        gate.set()
        assert pick_judge.wait(20)
        r = (await c.get("/api/prompt-programs/fix-judge")).json()
        assert r["status"] == "ready" and r["version"] == pick_judge.version_of(release.manifest) and r["cut"] == 0.5
        assert not r["waiting"]


async def test_the_route_says_why_a_run_would_go_unjudged_and_try_again_retries(release, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from routes import prompt_programs as route
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    monkeypatch.setattr(pick_judge, "FIRST_RETRY_SECONDS", 60.0)
    release.handler = lambda h, path: (h.send_error(503), True)[1]
    app = FastAPI()
    app.include_router(route.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/api/prompt-programs/fix-judge", params={"start": 1})
        for _ in range(100):
            r = (await c.get("/api/prompt-programs/fix-judge")).json()
            if r["status"] == "unavailable":
                break
            await asyncio.sleep(0.02)
        assert r["unjudged"] == "unavailable" and not r["waiting"]
        release.handler = None
        await c.get("/api/prompt-programs/fix-judge", params={"retry": 1})
        assert pick_judge.wait(20)


# --------------------------------------------------------------------------- who waits

async def test_a_generate_forever_pool_waits_for_the_judge_and_fills_judged(release, monkeypatch):
    from generation_queue import GenerationQueue
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")
    monkeypatch.setenv("STIMMA_FLUENT_GENERATE", "0")
    gate = threading.Event()
    release.handler = hold_file(".onnx", gate)
    q = GenerationQueue()
    q._forever_mode_clients = {"backend-a": {"gen-1": 2}}
    entry = entry_for()
    spec = lambda: {"entry": entry, "pins": None, "fixed": None, "edits": None, "triggers": True,  # noqa: E731
                    "profile_id": None, "project_id": None}
    assert q.take_fluent_draw("gen-1", "sig", spec) is None
    await asyncio.sleep(0.3)
    assert q._prompt_warm_ready["gen-1"] == []  # nothing drawn unjudged while it downloads
    gate.set()
    for _ in range(200):
        tasks = list(q._prompt_warm_tasks.get("gen-1", ()))
        if not tasks:
            break
        await asyncio.gather(*tasks, return_exceptions=True)
    ready = q._prompt_warm_ready["gen-1"]
    assert len(ready) == 2 and all(h["fix"]["judge"] == pick_judge.version_of(release.manifest) for h in ready)


async def test_raw_direct_and_tools_without_programs_never_wait(release, monkeypatch):
    import routes.generation as gen
    from prompt_programs import fix as fx
    monkeypatch.setenv("STIMMA_FLUENT_FIX_MODEL", "default")

    def boom(*a, **k):
        raise AssertionError("waited for the judge")

    monkeypatch.setattr(fx, "await_judge", boom)
    monkeypatch.setattr(pick_judge, "get", boom)

    async def fake_pipeline(db, prompt, options, **kw):
        return prompt

    async def no_context(*a, **k):
        return []

    monkeypatch.setattr("prompt_pipeline.run_prompt_pipeline", fake_pipeline)
    monkeypatch.setattr("lora_notes.lora_context_for", no_context)
    monkeypatch.setattr(gen, "get_database_registry", lambda: type("R", (), {"get_database": lambda self, p: None})())
    monkeypatch.setattr(gen, "get_current_profile", lambda: "p")
    for supported in (True, False):
        monkeypatch.setattr(gen, "prompt_enhance_context", lambda *a, s=supported, **k: {
            "model": "m", "model_vendor": None, "schema_props": {}, "mode": "prose", "program_supported": s,
            "enhance": {}})
        for options in ({"raw": True, "program": {"enabled": True}},  # Raw
                        {"autoImprove": {"enabled": False}},          # Direct, no chat model: no program
                        {"program": {"enabled": True}} if not supported else {}):  # a tool without programs
            out = await gen._apply_generation_prompt_pipeline(
                {"prompt": "a woman"}, tool_id="t", task_type=None, prompt_options=options, prompt_preload=None)
            assert out["prompt"] == "a woman"
    # a program with no draws, and a judge that's off or a model directory, don't wait either
    assert not fx.needs_judge({"program": ""}, DEFAULT)
    assert not fx.needs_judge(entry_for(), FluentSettings(generate_options=False, fix_model="off"))
    assert not fx.needs_judge(entry_for(), FluentSettings(generate_options=False, fix_model="/models/j"))
    assert fx.needs_judge(entry_for(), DEFAULT)
    assert release.hits == []


def test_an_agents_result_mentions_unchecked_choices_only_when_it_happened():
    from agent.v2.prompt_handling import UNCHECKED_LOCKDOWN_NOTE, UNCHECKED_NOTE, unchecked_note
    assert unchecked_note({"fix": {"judge": "pick-judge/x@y", "rerolls": 0, "rounds": []}}) is None
    assert unchecked_note({"draws": []}) is None and unchecked_note(None) is None
    assert unchecked_note({"fix": {"judge": "pick-judge/x", "skipped": "unavailable"}}) == UNCHECKED_NOTE
    assert unchecked_note({"fix": {"judge": "pick-judge/x", "skipped": "stalled"}}) == UNCHECKED_NOTE
    assert unchecked_note({"fix": {"judge": "pick-judge/x", "skipped": "lockdown"}}) == UNCHECKED_LOCKDOWN_NOTE
    for note in (UNCHECKED_NOTE, UNCHECKED_LOCKDOWN_NOTE):  # model-facing: no internal names
        assert "judge" not in note.lower() and "fluent" not in note.lower()

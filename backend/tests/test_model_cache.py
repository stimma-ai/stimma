"""model_cache bundles: versioned multi-file models fetched from a mirror, checked by
size and sha256 as they stream, verified once, then used with no network at all."""

import hashlib
import os
import threading
import time

import pytest

import model_cache
from privacy_lockdown import PrivacyLockdownError

PREFIX = "pick-judge/2026-01-02.1"


def publish(mirror, files, prefix=PREFIX):
    """Write `files` ({path: bytes}) into the mirror under `prefix`; return their manifest."""
    entries = []
    for path, data in files.items():
        p = mirror.root / prefix / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        entries.append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return {"name": "pick-judge", "version": prefix.split("/")[-1], "files": entries}


FILES = {"model.onnx": os.urandom(3 << 20), "tokenizer.json": b'{"t": 1}', "io.json": b'{"cut": 0.1}'}


def test_downloads_verifies_and_then_never_touches_the_network(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    seen = []
    d = model_cache.ensure_bundle(PREFIX, m, progress=lambda done, total: seen.append((done, total)))
    assert d == model_cache.models_root() / PREFIX
    for path, data in FILES.items():
        assert (d / path).read_bytes() == data
    assert (d / ".verified").read_text() == model_cache.manifest_digest(m)
    assert (d / "manifest.json").exists() and not list(d.rglob("*.part"))
    total = sum(len(v) for v in FILES.values())
    assert seen[-1] == (total, total) and all(a <= b for (a, _), (b, _) in zip(seen, seen[1:]))
    assert len(seen) > 3  # byte progress while the big file streams
    assert model_cache.bundle_is_present(PREFIX, m)
    hits = list(local_model_mirror.hits)
    assert sorted(hits) == sorted(f"{PREFIX}/{p}" for p in FILES)
    assert model_cache.ensure_bundle(PREFIX, m) == d
    assert local_model_mirror.hits == hits  # cached: zero requests


def test_an_interrupted_download_resumes_where_it_stopped(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    cuts = {"n": 0}

    def truncate_once(h, path):
        if path.endswith("model.onnx") and cuts["n"] == 0:
            cuts["n"] += 1
            h.send_response(200)
            h.send_header("Content-Length", str(len(FILES["model.onnx"])))
            h.end_headers()
            h.wfile.write(FILES["model.onnx"][:1000])
            h.wfile.flush()
            h.connection.close()
            return True
        return False

    local_model_mirror.handler = truncate_once
    d = model_cache.ensure_bundle(PREFIX, m)
    assert cuts["n"] == 1 and (d / "model.onnx").read_bytes() == FILES["model.onnx"]
    assert local_model_mirror.hits.count(f"{PREFIX}/model.onnx") == 2
    assert local_model_mirror.ranges == [(f"{PREFIX}/model.onnx", 1000)]  # only the rest was fetched
    assert not list(d.glob("*" + model_cache.PARTIAL))


def test_a_partial_file_left_by_an_earlier_launch_is_resumed(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    d = model_cache.models_root() / PREFIX
    d.mkdir(parents=True)
    (d / ("model.onnx" + model_cache.PARTIAL)).write_bytes(FILES["model.onnx"][:5000])
    seen = []
    model_cache.ensure_bundle(PREFIX, m, progress=lambda done, total: seen.append(done))
    assert (d / "model.onnx").read_bytes() == FILES["model.onnx"]
    assert (f"{PREFIX}/model.onnx", 5000) in local_model_mirror.ranges
    assert seen[0] == 0 and max(seen) == sum(len(v) for v in FILES.values())


def test_a_server_that_ignores_range_sends_the_whole_file_again(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    d = model_cache.models_root() / PREFIX
    d.mkdir(parents=True)
    (d / ("model.onnx" + model_cache.PARTIAL)).write_bytes(b"\0" * 5000)  # not even the right bytes

    def no_ranges(h, path):
        data = (local_model_mirror.root / path).read_bytes()
        h.send_response(200)
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return True

    local_model_mirror.handler = no_ranges
    model_cache.ensure_bundle(PREFIX, m)
    assert (d / "model.onnx").read_bytes() == FILES["model.onnx"]


def test_a_corrupt_partial_file_is_dropped_and_fetched_fresh(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    d = model_cache.models_root() / PREFIX
    d.mkdir(parents=True)
    (d / ("model.onnx" + model_cache.PARTIAL)).write_bytes(b"\0" * 5000)  # resumes onto bad bytes
    model_cache.ensure_bundle(PREFIX, m)  # the first try fails its hash, the next starts over
    assert (d / "model.onnx").read_bytes() == FILES["model.onnx"]
    assert local_model_mirror.hits.count(f"{PREFIX}/model.onnx") == 2


def test_cancelled_stops_at_once_and_keeps_the_bytes(local_model_mirror):
    m = publish(local_model_mirror, FILES)

    def progress(done, total):
        if done > 1 << 20:
            raise model_cache.Cancelled()

    with pytest.raises(model_cache.Cancelled):
        model_cache.ensure_bundle(PREFIX, m, progress=progress)
    d = model_cache.models_root() / PREFIX
    assert local_model_mirror.hits.count(f"{PREFIX}/model.onnx") == 1  # not retried
    assert (d / ("model.onnx" + model_cache.PARTIAL)).stat().st_size > 0
    model_cache.ensure_bundle(PREFIX, m)
    assert (d / "model.onnx").read_bytes() == FILES["model.onnx"] and local_model_mirror.ranges


def test_a_second_process_waits_for_the_first_and_reports_its_bytes(local_model_mirror, tmp_path):
    """Another process holding the bundle's lock: this one waits, showing the bytes
    on disk, then finds the bundle verified and fetches nothing."""
    import subprocess
    import sys
    m = publish(local_model_mirror, FILES)
    d = model_cache.models_root() / PREFIX
    d.mkdir(parents=True)
    lock = d.parent / f"{d.name}.lock"
    script = (
        "import sys, time\n"
        "from filelock import FileLock\n"
        "with FileLock(sys.argv[1]):\n"
        "    print('held', flush=True)\n"
        "    time.sleep(2.5)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script, str(lock)], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "held"
    (d / ("model.onnx" + model_cache.PARTIAL)).write_bytes(FILES["model.onnx"][:4096])
    seen = []
    model_cache.ensure_bundle(PREFIX, m, progress=lambda done, total: seen.append(done))
    child.wait(10)
    assert 4096 in seen  # the other process's bytes, while it held the lock
    assert (d / "model.onnx").read_bytes() == FILES["model.onnx"]


def test_a_download_that_keeps_failing_raises_and_leaves_no_partial_files(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    (local_model_mirror.root / PREFIX / "model.onnx").unlink()  # 404
    with pytest.raises(Exception):
        model_cache.ensure_bundle(PREFIX, m)
    d = model_cache.models_root() / PREFIX
    assert not (d / ".verified").exists() and not (d / "model.onnx").exists() and not list(d.rglob("*.part"))
    assert not list(d.glob("*" + model_cache.PARTIAL))  # a 404 writes nothing
    assert local_model_mirror.hits.count(f"{PREFIX}/model.onnx") == model_cache.BUNDLE_TRIES
    assert not model_cache.bundle_is_present(PREFIX, m)


def test_a_hash_mismatch_is_never_moved_into_place(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    bad = bytearray(FILES["model.onnx"])
    bad[100] ^= 0xFF
    (local_model_mirror.root / PREFIX / "model.onnx").write_bytes(bytes(bad))  # same size, other bytes
    with pytest.raises(model_cache.BundleError, match="sha256"):
        model_cache.ensure_bundle(PREFIX, m)
    assert not (model_cache.models_root() / PREFIX / "model.onnx").exists()


def test_the_wrong_size_from_the_server_fails(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    (local_model_mirror.root / PREFIX / "io.json").write_bytes(b'{"cut": 0.1, "x": 2}')
    with pytest.raises(model_cache.BundleError, match="larger|bytes"):
        model_cache.ensure_bundle(PREFIX, m)


def test_a_cached_file_of_the_wrong_size_is_fetched_again(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    d = model_cache.ensure_bundle(PREFIX, m)
    (d / "tokenizer.json").write_bytes(b"truncated")
    assert not model_cache.bundle_is_present(PREFIX, m)
    before = len(local_model_mirror.hits)
    model_cache.ensure_bundle(PREFIX, m)
    assert (d / "tokenizer.json").read_bytes() == FILES["tokenizer.json"]
    assert local_model_mirror.hits[before:] == [f"{PREFIX}/tokenizer.json"]  # the rest kept


def test_a_stalled_server_times_out(local_model_mirror, monkeypatch):
    monkeypatch.setattr(model_cache, "STALL_TIMEOUT", 0.3)
    m = publish(local_model_mirror, FILES)
    release = threading.Event()

    def stall(h, path):
        if path.endswith("model.onnx"):
            h.send_response(200)
            h.send_header("Content-Length", str(len(FILES["model.onnx"])))
            h.end_headers()
            h.wfile.write(FILES["model.onnx"][:10])
            h.wfile.flush()
            release.wait(5)
            return True
        return False

    local_model_mirror.handler = stall
    started = time.monotonic()
    with pytest.raises(Exception) as e:
        model_cache.ensure_bundle(PREFIX, m, tries=1)
    release.set()
    assert "timed out" in str(e.value).lower() or isinstance(e.value, TimeoutError)
    assert time.monotonic() - started < 4


def test_lockdown_blocks_stimma_hosts_but_a_verified_bundle_still_loads(local_model_mirror, monkeypatch):
    m = publish(local_model_mirror, FILES)
    d = model_cache.ensure_bundle(PREFIX, m)  # cached from the mirror first
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    monkeypatch.setenv("STIMMA_MODELS_BASE_URL", "https://models.stimma.ai")
    hits = list(local_model_mirror.hits)
    assert model_cache.ensure_bundle(PREFIX, m) == d
    other = publish(local_model_mirror, {"model.onnx": b"v2"}, prefix="pick-judge/2026-01-03.1")
    with pytest.raises(PrivacyLockdownError):
        model_cache.ensure_bundle("pick-judge/2026-01-03.1", other)
    assert local_model_mirror.hits == hits


def test_lockdown_still_allows_a_custom_mirror(local_model_mirror, monkeypatch):
    monkeypatch.setenv("STIMMA_PRIVACY_LOCKDOWN", "1")
    m = publish(local_model_mirror, FILES)
    assert model_cache.bundle_is_present(PREFIX, m) is False
    assert (model_cache.ensure_bundle(PREFIX, m) / "io.json").exists()


def test_prune_keeps_only_the_pinned_version(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    keep = model_cache.ensure_bundle(PREFIX, m)
    root = model_cache.models_root() / "pick-judge"
    (root / "2025-12-31.4").mkdir()
    (root / "2025-12-31.4" / "model.onnx").write_bytes(b"old")
    (root / "notes").mkdir()  # not a version: never touched
    assert model_cache.prune_bundles("pick-judge", keep.name) == ["2025-12-31.4"]
    assert keep.is_dir() and (root / "notes").is_dir() and not (root / "2025-12-31.4").exists()


def test_stale_part_files_are_swept(local_model_mirror):
    m = publish(local_model_mirror, FILES)
    d = model_cache.models_root() / PREFIX
    d.mkdir(parents=True)
    old, fresh = d / "model.onnx.1.2.part", d / "model.onnx.3.4.part"
    old.write_bytes(b"x")
    fresh.write_bytes(b"y")
    os.utime(old, (time.time() - 3 * 86400,) * 2)
    model_cache.ensure_bundle(PREFIX, m)
    assert not old.exists() and fresh.exists()


@pytest.mark.parametrize("files", [
    [], [{"path": "../x", "size": 1, "sha256": "0" * 64}], [{"path": "/etc/x", "size": 1, "sha256": "0" * 64}],
    [{"path": "a", "size": -1, "sha256": "0" * 64}], [{"path": "a", "size": 1, "sha256": "nope"}],
    [{"path": ".verified", "size": 1, "sha256": "0" * 64}],
])
def test_malformed_manifests_are_refused(local_model_mirror, files):
    with pytest.raises(model_cache.BundleError):
        model_cache.ensure_bundle(PREFIX, {"files": files})
    assert local_model_mirror.hits == []


def test_single_file_downloads_have_a_stall_timeout(monkeypatch, tmp_path):
    import urllib.request
    got = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b""

    def urlopen(req, timeout=None):
        got["timeout"] = timeout
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    from conftest import _REAL_MODEL_DOWNLOAD
    _REAL_MODEL_DOWNLOAD[0]("https://example.invalid/x", tmp_path / "x")
    assert got["timeout"] == model_cache.STALL_TIMEOUT

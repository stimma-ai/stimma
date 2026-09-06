"""Package reproducibility, publication safety, and authenticated delivery."""
import gzip
import hashlib
import io
import json
import os
import tarfile

from fastapi import FastAPI
import httpx
import pytest

import mobile_ui_package as packaging
from mobile_ui_package import build_ui_package
from routes.mobile_ui import router


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "frontend"
    source.mkdir()
    (source / "index.html").write_text('<script src="assets/app.js"></script>')
    (source / "mobile.html").write_text("bundled shell only")
    (source / "assets").mkdir()
    (source / "assets" / "app.js").write_text("console.log('stimma')")
    return source


def test_deterministic_regular_file_archive(source, tmp_path):
    first = build_ui_package(source, tmp_path / "first")
    os.utime(source / "index.html", (100, 100))
    (source / "index.html").chmod(0o700)
    second = build_ui_package(source, tmp_path / "second")
    assert first == second
    data = (tmp_path / "first/packages" / f"{first['hash']}.tar.gz").read_bytes()
    assert hashlib.sha256(data).hexdigest() == first["hash"]
    assert len(data) == first["bytes"]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        entries = archive.getmembers()
        assert [entry.name for entry in entries] == ["assets/app.js", "index.html"]
        assert all(entry.isfile() and entry.uid == 0 and entry.gid == 0 and entry.mtime == 0 for entry in entries)
        assert sum(entry.size for entry in entries) == first["unpackedBytes"]
    assert gzip.decompress(data)[257:263] == b"ustar\x00"


def test_publish_keeps_old_hash_and_failure_preserves_manifest(source, tmp_path):
    output = tmp_path / "published"
    first = build_ui_package(source, output)
    (source / "assets/app.js").write_text("new version")
    second = build_ui_package(source, output)
    assert first["hash"] != second["hash"]
    assert (output / "packages" / f"{first['hash']}.tar.gz").is_file()
    assert json.loads((output / "manifest.json").read_text()) == second
    (source / "bad-link").symlink_to(source / "index.html")
    with pytest.raises(ValueError, match="symbolic"):
        build_ui_package(source, output)
    assert json.loads((output / "manifest.json").read_text()) == second


@pytest.mark.parametrize("kind", ["missing-entry", "symlink-dir", "oversize", "too-many"])
def test_reject_invalid_build(source, tmp_path, monkeypatch, kind):
    if kind == "missing-entry":
        (source / "index.html").unlink()
    elif kind == "symlink-dir":
        (source / "linked").symlink_to(source / "assets", target_is_directory=True)
    elif kind == "oversize":
        monkeypatch.setattr(packaging, "MAX_UNPACKED_BYTES", 1)
    else:
        monkeypatch.setattr(packaging, "MAX_FILES", 1)
    with pytest.raises(ValueError):
        build_ui_package(source, tmp_path / "out")
    assert not (tmp_path / "out/manifest.json").exists()


def test_compressed_limit_never_publishes(source, tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "MAX_COMPRESSED_BYTES", 1)
    with pytest.raises(ValueError, match="Compressed"):
        build_ui_package(source, tmp_path / "out")
    assert not (tmp_path / "out/manifest.json").exists()
    assert list((tmp_path / "out/packages").iterdir()) == []


@pytest.mark.asyncio
async def test_delivery_etags_missing_and_hash_snapshot(source, tmp_path, monkeypatch):
    output = tmp_path / "published"
    monkeypatch.setenv("STIMMA_UI_PACKAGE_DIR", str(output))
    app = FastAPI()
    app.include_router(router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test")
    assert (await client.get("/api/mobile-ui/manifest")).status_code == 503
    first = build_ui_package(source, output)
    response = await client.get("/api/mobile-ui/manifest")
    assert response.json() == first
    etag = response.headers["etag"]
    assert (await client.get("/api/mobile-ui/manifest", headers={"If-None-Match": f'"other", W/{etag}'})).status_code == 304
    (source / "index.html").write_text("version two")
    build_ui_package(source, output)
    assert (await client.get("/api/mobile-ui/manifest", headers={"If-None-Match": etag})).status_code == 200
    package_url = f"/api/mobile-ui/packages/{first['hash']}.tar.gz"
    archive = await client.get(package_url)
    assert archive.status_code == 200
    assert hashlib.sha256(archive.content).hexdigest() == first["hash"]
    assert "immutable" in archive.headers["cache-control"]
    assert (await client.get(package_url, headers={"If-None-Match": etag})).status_code == 304
    assert (await client.get("/api/mobile-ui/packages/not-a-hash.tar.gz")).status_code == 404
    assert (await client.get(f"/api/mobile-ui/packages/{'0' * 64}.tar.gz")).status_code == 404

    await client.aclose()


@pytest.mark.asyncio
async def test_remote_gate_protects_both_routes(source, tmp_path, monkeypatch):
    from multi_device.server import ServingGate
    output = tmp_path / "published"
    package = build_ui_package(source, output)
    monkeypatch.setenv("STIMMA_UI_PACKAGE_DIR", str(output))
    monkeypatch.setattr("multi_device.server.verify_session", lambda token: token == "valid-session")
    app = FastAPI()
    app.include_router(router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(ServingGate(app, lambda: "test-device")), base_url="http://test")
    for path in ("/api/mobile-ui/manifest", f"/api/mobile-ui/packages/{package['hash']}.tar.gz"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers={"Authorization": "Bearer wrong"})).status_code == 401
        assert (await client.get(path, headers={"Authorization": "Bearer valid-session"})).status_code == 200
    await client.aclose()


def test_build_without_posix_nofollow(source, tmp_path, monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    manifest = build_ui_package(source, tmp_path / "out")
    assert manifest["entrypoint"] == "index.html"
    (source / "link").symlink_to(source / "index.html")
    with pytest.raises(ValueError, match="symbolic"):
        build_ui_package(source, tmp_path / "out")


def test_replaced_symlink_rejected_without_nofollow(source, tmp_path, monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    original_open = os.open
    target = source / "assets/app.js"
    replacement = tmp_path / "replacement.js"
    replacement.write_text("replacement")

    def replace_before_open(path, flags, *args, **kwargs):
        if path == target:
            target.unlink()
            target.symlink_to(replacement)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    with pytest.raises(ValueError, match="changed during packaging"):
        build_ui_package(source, tmp_path / "out")
    assert not (tmp_path / "out/manifest.json").exists()


@pytest.mark.parametrize("names", [
    ["index.html", "assets/App.js", "assets/app.js"],
    ["index.html", "assets/caf\u00e9.js", "assets/cafe\u0301.js"],
    ["index.html", "ASSETS", "assets/app.js"],
    ["index.html", "/".join(["a"] * 32 + ["app.js"])],
    ["index.html", "assets/bad\nname.js"],
])
def test_reject_names_that_native_cache_cannot_extract(names):
    # Direct names exercise collisions even on a case-insensitive test host,
    # where constructing both source files on disk would alias the same file.
    with pytest.raises(ValueError):
        packaging._validate_package_names(names)


def test_deep_source_fails_before_publication(source, tmp_path):
    directory = source.joinpath(*(["a"] * 32))
    directory.mkdir(parents=True)
    (directory / "app.js").write_text("too deep")
    with pytest.raises(ValueError, match="filename"):
        build_ui_package(source, tmp_path / "out")
    assert not (tmp_path / "out/manifest.json").exists()

"""Bundled sidecar engines: resolution and process lifecycle."""

import asyncio
import os
import stat
import sys
from pathlib import Path

import pytest

from providers import sidecars


def _fake_sidecar(tmp_path: Path, script: str) -> Path:
    path = tmp_path / "stimma-drawthings"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_resolve_prefers_explicit_override(tmp_path, monkeypatch):
    fake = _fake_sidecar(tmp_path, "exit 0\n")
    monkeypatch.setenv("STIMMA_SIDECAR_STIMMA_DRAWTHINGS", str(fake))
    monkeypatch.setattr(sidecars.sys, "platform", "darwin")
    assert sidecars.resolve_sidecar("drawthings") == fake
    assert sidecars.available_sidecars() == ["drawthings"]


def test_resolve_is_macos_only(tmp_path, monkeypatch):
    fake = _fake_sidecar(tmp_path, "exit 0\n")
    monkeypatch.setenv("STIMMA_SIDECAR_STIMMA_DRAWTHINGS", str(fake))
    monkeypatch.setattr(sidecars.sys, "platform", "win32")
    assert sidecars.resolve_sidecar("drawthings") is None
    assert sidecars.available_sidecars() == []


def test_unknown_sidecar_is_unavailable():
    assert sidecars.resolve_sidecar("nope") is None


@pytest.mark.skipif(sys.platform != "darwin", reason="sidecars ship on macOS")
def test_process_reports_url_and_streams_logs(tmp_path, monkeypatch):
    fake = _fake_sidecar(
        tmp_path,
        'echo "warming up" >&2\n'
        'echo "Draw Things STP listening on 127.0.0.1:$((40000 + $$ % 1000))" >&2\n'
        'echo "later line" >&2\n'
        "exec sleep 30\n",
    )
    monkeypatch.setenv("STIMMA_SIDECAR_STIMMA_DRAWTHINGS", str(fake))
    lines = []

    async def run():
        process = sidecars.SidecarProcess("drawthings", on_log=lines.append)
        url = await process.start()
        assert url.startswith("ws://127.0.0.1:") and url.endswith("/stp-v1")
        assert process.running
        await asyncio.sleep(0.2)
        await process.stop()
        assert not process.running
        assert process.url is None

    asyncio.run(run())
    assert any("warming up" in line for line in lines)
    assert any("later line" in line for line in lines)


@pytest.mark.skipif(sys.platform != "darwin", reason="sidecars ship on macOS")
def test_process_failure_during_startup_raises(tmp_path, monkeypatch):
    fake = _fake_sidecar(tmp_path, 'echo "no engine" >&2\nexit 3\n')
    monkeypatch.setenv("STIMMA_SIDECAR_STIMMA_DRAWTHINGS", str(fake))

    async def run():
        process = sidecars.SidecarProcess("drawthings")
        with pytest.raises(RuntimeError, match="code 3"):
            await process.start()
        assert not process.running

    asyncio.run(run())


@pytest.mark.skipif(
    sys.platform != "darwin" or not sidecars.resolve_sidecar("drawthings"),
    reason="needs the real stimma-drawthings executable",
)
def test_real_adapter_binds_an_ephemeral_port(tmp_path, monkeypatch):
    """The bundled adapter must announce the port it actually bound."""
    monkeypatch.setenv("STIMMA_DATA_DIR", str(tmp_path))

    async def run():
        process = sidecars.SidecarProcess("drawthings")
        url = await process.start()
        port = int(url.rsplit(":", 1)[1].split("/")[0])
        assert port > 0
        await process.stop()

    asyncio.run(run())

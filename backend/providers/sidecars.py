"""Bundled local generation engines that Stimma launches itself.

A sidecar is a standalone STP provider executable shipped inside the app
bundle (today: ``stimma-drawthings`` on macOS). The provider config stores
``sidecar: <name>`` instead of a URL; the manager starts the executable on a
loopback port, reads the port it bound, and connects to it over WebSocket
like any other provider. The process lives as long as the provider is
enabled and is restarted through the normal provider retry path.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import structlog

log = structlog.get_logger(__name__)

DRAWTHINGS = "drawthings"

# name -> (executable basename, platforms it ships on)
SIDECARS: dict[str, tuple[str, tuple[str, ...]]] = {
    DRAWTHINGS: ("stimma-drawthings", ("darwin",)),
}

_LISTENING = re.compile(r"listening on \S+?:(\d+)\s*$")
STARTUP_TIMEOUT_SECONDS = 20.0


def _candidates(executable: str) -> list[Path]:
    """Places the executable may live, most specific first."""
    override = os.environ.get(f"STIMMA_SIDECAR_{executable.upper().replace('-', '_')}")
    here = Path(__file__).resolve()
    # Packaged: <Resources>/stimma-backend/backend/providers/sidecars.py and
    # the sidecar sits next to the backend folder at <Resources>/<executable>.
    packaged = here.parents[3] / executable if len(here.parents) > 3 else None
    # Source checkout: the app build stages binaries under src-tauri/binaries.
    repo = here.parents[2]
    staged = sorted(repo.glob(f"src-tauri/binaries/{executable}-*"))
    found = shutil.which(executable)
    out: list[Path] = []
    if override:
        out.append(Path(override))
    if packaged:
        out.append(packaged)
    out.extend(staged)
    if found:
        out.append(Path(found))
    return out


def resolve_sidecar(name: str) -> Optional[Path]:
    """Path to a runnable sidecar executable, or None when unavailable here."""
    spec = SIDECARS.get(name)
    if not spec:
        return None
    executable, platforms = spec
    if sys.platform not in platforms:
        return None
    for candidate in _candidates(executable):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def available_sidecars() -> list[str]:
    return [name for name in SIDECARS if resolve_sidecar(name) is not None]


def sidecar_state_dir(name: str) -> Optional[Path]:
    try:
        import app_dirs

        return app_dirs.get_data_dir() / "sidecars" / name
    except Exception:
        return None


def installed_sidecars() -> list[str]:
    """Available sidecars whose engine runtime has already been fetched here."""
    out = []
    for name in available_sidecars():
        state = sidecar_state_dir(name)
        runtime = state / "runtime" if state else None
        if runtime and runtime.is_dir() and any(runtime.rglob("*")):
            out.append(name)
    return out


class SidecarProcess:
    """One running sidecar executable and the loopback URL it serves."""

    def __init__(self, name: str, on_log: Optional[Callable[[str], None]] = None):
        self.name = name
        self.url: Optional[str] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._on_log = on_log
        self._pump: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    def _log(self, line: str) -> None:
        if self._on_log:
            try:
                self._on_log(line)
            except Exception:
                pass

    async def start(self) -> str:
        """Launch the executable and return its STP WebSocket URL."""
        path = resolve_sidecar(self.name)
        if path is None:
            raise FileNotFoundError(f"The {self.name} engine is not included in this build")
        await self.stop()
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log(f"[{stamp}] Starting: {path.name} --websocket --bind 127.0.0.1:0")
        env = os.environ.copy()
        # Keep provider state out of the user's home-level defaults so several
        # Stimma installs (sandboxes) do not share a download/registry folder.
        state = sidecar_state_dir(self.name)
        if state:
            env.setdefault("STIMMA_DRAWTHINGS_STATE", str(state))
        self._process = await asyncio.create_subprocess_exec(
            str(path),
            "--websocket",
            "--bind",
            "127.0.0.1:0",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        log.info("sidecar started", sidecar=self.name, pid=self._process.pid)
        assert self._process.stderr is not None
        deadline = asyncio.get_event_loop().time() + STARTUP_TIMEOUT_SECONDS
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                await self.stop()
                raise TimeoutError(f"The {self.name} engine did not start in time")
            try:
                raw = await asyncio.wait_for(self._process.stderr.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                continue
            if not raw:
                code = await self._process.wait()
                self._process = None
                raise RuntimeError(f"The {self.name} engine exited during startup (code {code})")
            line = raw.decode("utf-8", errors="replace").rstrip()
            self._log(line)
            match = _LISTENING.search(line)
            if match:
                self.url = f"ws://127.0.0.1:{match.group(1)}/stp-v1"
                break
        self._pump = asyncio.create_task(self._drain())
        return self.url

    async def _drain(self) -> None:
        process = self._process
        if not process or not process.stderr:
            return
        try:
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                self._log(raw.decode("utf-8", errors="replace").rstrip())
        except Exception:
            pass
        code = process.returncode
        if code is None:
            try:
                code = await process.wait()
            except Exception:
                code = None
        self._log(f"[{datetime.now().strftime('%H:%M:%S')}] Process exited with code {code}")

    async def stop(self) -> None:
        process = self._process
        self._process = None
        self.url = None
        pump, self._pump = self._pump, None
        if pump:
            pump.cancel()
            try:
                await pump
            except (asyncio.CancelledError, Exception):
                pass
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except ProcessLookupError:
            pass
        log.info("sidecar stopped", sidecar=self.name)

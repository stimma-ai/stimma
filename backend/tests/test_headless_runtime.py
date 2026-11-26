from unittest.mock import Mock
import httpx
import pytest
from fastapi import FastAPI
import headless_runtime as runtime


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(runtime.router)
    return app


@pytest.mark.asyncio
async def test_desktop_capability_and_unsupported_commands(app, monkeypatch):
    monkeypatch.setattr(runtime, 'ENABLED', False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.get('/api/headless/status')).json() == {'headless': False}
        assert (await client.post('/api/headless/restart')).status_code == 409
        assert (await client.post('/api/headless/arbitrary')).status_code == 404


@pytest.mark.asyncio
async def test_management_targets_supervisor_but_internal_routes_require_secret(app, monkeypatch):
    monkeypatch.setattr(runtime, 'ENABLED', True)
    monkeypatch.setenv('STIMMA_SUPERVISOR_TOKEN', 'private')
    command = Mock(return_value={'headless': True, 'status': 'ready'})
    monkeypatch.setattr(runtime, 'supervisor_command', command)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.post('/api/headless/restart')).status_code == 200
        command.assert_called_once_with('restart')
        assert (await client.get('/api/headless/ready')).status_code == 403
        assert (await client.post('/api/headless/login')).status_code == 403
        assert (await client.post('/api/headless/mcp', json={'command': 'status'})).status_code == 403
        assert (await client.post('/api/headless/maintenance', json={'enabled': True})).status_code == 403
        assert (await client.get('/api/headless/ready', headers={'X-Stimma-Supervisor': 'private'})).status_code == 200


@pytest.mark.asyncio
async def test_maintenance_blocks_new_writes_and_allows_status(monkeypatch):
    app = FastAPI()
    @app.post('/work')
    async def work():
        return {'started': True}
    @app.get('/status')
    async def status():
        return {'ok': True}
    app.add_middleware(runtime.MaintenanceGate)
    monkeypatch.setattr(runtime, '_maintenance', True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.post('/work')).status_code == 503
        assert (await client.get('/status')).status_code == 200
    assert runtime._active_requests == 0


@pytest.mark.asyncio
async def test_flow_drain_waits_for_evaluations_not_running_labels(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import flow_registry

    def flow(state, active):
        run = Mock(state=state, active_evaluation_count=active)
        async def pause():
            run.state = 'paused'
        async def resume():
            run.state = 'running'
        run.pause = AsyncMock(side_effect=pause)
        run.resume = AsyncMock(side_effect=resume)
        return SimpleNamespace(run=run)

    waiting = flow('running', 0)
    working = flow('running', 1)
    user_paused = flow('paused', 0)
    monkeypatch.setattr(flow_registry, 'all_runtimes', lambda: [waiting, working, user_paused])
    monkeypatch.setattr(runtime, '_paused_flow_runs', set())
    assert await runtime.drain_flows(True) == 1
    working.run.active_evaluation_count = 0
    assert await runtime.drain_flows(True) == 0
    assert waiting.run.state == 'paused'
    assert working.run.state == 'paused'
    await runtime.drain_flows(False)
    assert waiting.run.state == working.run.state == 'running'
    user_paused.run.resume.assert_not_called()


@pytest.mark.asyncio
async def test_read_side_flow_recovery_cannot_restart_during_maintenance(monkeypatch):
    from flow_runtime.runtime import FlowRuntime
    monkeypatch.setattr(runtime, 'ENABLED', True)
    monkeypatch.setattr(runtime, '_maintenance', True)
    flow = Mock()
    await FlowRuntime.start(flow)
    flow.build_initial_graph.assert_not_called()


def _kill_group(proc):
    """Kill and reap a test server and whatever is left of its process group."""
    import os
    import signal
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.kill()
    proc.wait(timeout=20)


def test_headless_exit_stops_helpers_holding_the_database(tmp_path):
    """The server outlives every process it started, so an old supervisor's
    wait for the server alone is enough before the next release migrates."""
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path
    db, ready = tmp_path / 'stimma_v1.db', tmp_path / 'helper-ready'
    server = f'''
import os, subprocess, sys, time
sys.path.insert(0, {str(Path(runtime.__file__).parent)!r})
helper = subprocess.Popen([sys.executable, '-c', """
import signal, sqlite3, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
db = sqlite3.connect({str(db)!r})
db.execute('PRAGMA journal_mode=WAL')
db.execute('CREATE TABLE IF NOT EXISTS t (x)')
db.execute('BEGIN')
db.execute('INSERT INTO t VALUES (1)')
open({str(ready)!r}, 'w').close()
time.sleep(600)
"""])
while not os.path.exists({str(ready)!r}):
    time.sleep(0.05)
import headless_runtime
headless_runtime.stop_helper_processes(grace=0.2)
'''
    proc = subprocess.Popen([sys.executable, '-c', server], env={**__import__('os').environ, 'STIMMA_HEADLESS': '1'},
                            process_group=0)
    try:
        assert proc.wait(timeout=60) == 0
        with sqlite3.connect(db, timeout=0.2) as connection:
            connection.execute('PRAGMA locking_mode=EXCLUSIVE')
            connection.execute('BEGIN EXCLUSIVE')
            connection.rollback()
    finally:
        _kill_group(proc)


def test_stop_signal_to_the_server_alone_stops_its_helpers(tmp_path):
    """A supervisor that signals and waits for only the server pid (installed
    supervisors do) must find every database free once that pid exits. Uvicorn
    re-raises the stop signal before run() returns, so this runs the real
    Uvicorn with the lifespan's headless shutdown step."""
    import os
    import signal
    import socket
    import sqlite3
    import subprocess
    import sys
    import time
    from pathlib import Path
    db, ready = tmp_path / 'stimma_v1.db', tmp_path / 'helper-ready'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = f'''
import contextlib, os, subprocess, sys
os.setpgrp()  # as backend/main.py does
sys.path.insert(0, {str(Path(runtime.__file__).parent)!r})
import uvicorn
from fastapi import FastAPI
import headless_runtime

@contextlib.asynccontextmanager
async def lifespan(app):
    subprocess.Popen([sys.executable, '-c', """
import signal, sqlite3, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
db = sqlite3.connect({str(db)!r})
db.execute('PRAGMA journal_mode=WAL')
db.execute('CREATE TABLE IF NOT EXISTS t (x)')
db.execute('BEGIN')
db.execute('INSERT INTO t VALUES (1)')
open({str(ready)!r}, 'w').close()
time.sleep(600)
"""])
    yield
    await headless_runtime.shutdown()

uvicorn.run(FastAPI(lifespan=lifespan), host='127.0.0.1', port={port}, log_config=None, timeout_graceful_shutdown=0)
'''
    # The server makes itself a group leader; owning the group here as well
    # means a failed run can always be cleaned up.
    proc = subprocess.Popen([sys.executable, '-c', server], env={**os.environ, 'STIMMA_HEADLESS': '1'},
                            process_group=0)
    try:
        deadline = time.monotonic() + 60
        while not ready.exists():
            assert proc.poll() is None and time.monotonic() < deadline, 'server did not start'
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)
        with sqlite3.connect(db, timeout=0.2) as connection:
            connection.execute('PRAGMA locking_mode=EXCLUSIVE')
            connection.execute('BEGIN EXCLUSIVE')
            connection.rollback()
    finally:
        _kill_group(proc)

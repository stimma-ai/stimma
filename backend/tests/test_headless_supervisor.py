import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location('headless_supervisor', Path(__file__).parents[2] / 'packaging/headless/supervisor.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)


@pytest.mark.parametrize('args,body', [
    (['mcp', 'configure', '--host', '100.64.0.10', '--port', '19294'],
     {'command': 'configure', 'profile': None, 'name': 'Assistant',
      'direct': {'enabled': True, 'host': '100.64.0.10', 'port': 19294}}),
    (['mcp', 'configure', '--off'],
     {'command': 'configure', 'profile': None, 'name': 'Assistant',
      'direct': {'enabled': False, 'host': '127.0.0.1', 'port': 9194}}),
    (['mcp', 'connect', '--profile', 'work', '--name', 'Remote agent'],
     {'command': 'connect', 'profile': 'work', 'name': 'Remote agent'}),
])
def test_mcp_cli_forwards_owner_command(monkeypatch, capsys, args, body):
    control = Mock(return_value={'status': 'listening'})
    monkeypatch.setattr(supervisor, 'control', control)
    monkeypatch.setattr(supervisor.sys, 'argv', ['stimma-server', *args])
    supervisor.main()
    control.assert_called_once_with('mcp', body=body)
    assert json.loads(capsys.readouterr().out)['status'] == 'listening'


def test_update_window_spans_midnight_and_rejects_bad_input():
    now = dt.datetime(2026, 9, 5, 1, 30)
    assert supervisor.window_key('23:00-02:00', 'UTC', now) == '2026-09-04'
    assert supervisor.window_key('03:00-05:00', 'UTC', now) is None
    for value in ('25:00-26:00', '03:00-03:00', 'nightly'):
        with pytest.raises(ValueError):
            supervisor.window_key(value, 'UTC')


@pytest.mark.parametrize('name,link', [('../outside', None), ('/tmp/escape', None), ('python/bin/python', '../../../../outside')])
def test_package_rejects_traversal(tmp_path, name, link):
    archive = tmp_path / 'bad.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        item = tarfile.TarInfo(name)
        if link:
            item.type = tarfile.SYMTYPE
            item.linkname = link
        bundle.addfile(item, io.BytesIO())
    destination = tmp_path / 'stage'
    destination.mkdir()
    with pytest.raises(ValueError):
        supervisor.unpack(archive, destination)


def test_package_accepts_internal_symlink(tmp_path):
    archive = tmp_path / 'good.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in ('run.sh', 'python/bin/python3'):
            item = tarfile.TarInfo(name)
            item.size = 2
            bundle.addfile(item, io.BytesIO(b'#!'))
        item = tarfile.TarInfo('python/bin/python')
        item.type, item.linkname = tarfile.SYMTYPE, 'python3'
        bundle.addfile(item)
    destination = tmp_path / 'stage'
    destination.mkdir()
    supervisor.unpack(archive, destination)
    assert (destination / 'python/bin/python').read_bytes() == b'#!'


def test_incompatible_bootstrap_never_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    instance = supervisor.Supervisor()
    instance.manifest = {'version': '2.0.0'}
    instance.state['bootstrapUpdateRequired'] = True
    fetch = Mock()
    monkeypatch.setattr(supervisor, 'fetch', fetch)
    with pytest.raises(RuntimeError, match='Docker base'):
        instance.stage()
    fetch.assert_not_called()


def test_activation_failure_retains_recovery_record(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    release = tmp_path / 'releases/new'
    release.mkdir(parents=True)
    instance = supervisor.Supervisor()
    monkeypatch.setattr(instance, 'current', lambda: None)
    monkeypatch.setattr(instance, 'start_child', Mock(side_effect=RuntimeError('migration failed')))
    with pytest.raises(RuntimeError, match='migration failed'):
        instance.activate(release)
    record = json.loads((tmp_path / 'activation.json').read_text())
    assert record['candidate'] == str(release)
    assert (tmp_path / 'current').resolve() == release


def test_branch_change_does_not_use_other_branch_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    monkeypatch.setattr(supervisor, 'BRANCH', 'beta')
    release = tmp_path / 'release'
    release.mkdir()
    (release / 'release.json').write_text(json.dumps({'branch': 'production'}))
    (tmp_path / 'current').symlink_to(release)
    with pytest.raises(RuntimeError, match='another BRANCH'):
        supervisor.Supervisor().current()


def test_private_backend_uses_available_loopback_port(monkeypatch):
    import socket
    monkeypatch.setattr(supervisor, 'LOCAL_PORT', 0)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = supervisor.local_port()
        assert port != occupied.getsockname()[1]
        with socket.socket() as available:
            available.bind(('127.0.0.1', port))


def test_private_backend_explicit_port_is_preserved(monkeypatch):
    monkeypatch.setattr(supervisor, 'LOCAL_PORT', 49123)
    assert supervisor.local_port() == 49123


@pytest.mark.parametrize('scheduled,idle,activates', [(False, False, True), (True, False, False), (True, True, True)])
def test_only_scheduled_updates_wait_for_idle(monkeypatch, scheduled, idle, activates):
    instance = supervisor.Supervisor()
    instance.child = Mock()
    for name, result in [('check', None), ('stage', 'new'), ('current', 'old'), ('drain', idle), ('activate', None), ('status', None)]:
        monkeypatch.setattr(instance, name, Mock(return_value=result))
    instance.perform('update', scheduled=scheduled)
    assert instance.activate.called is activates
    assert instance.drain.called is scheduled
    if scheduled:
        instance.drain.assert_called_once_with(scheduled=True)


def test_manual_restart_starts_without_waiting_for_idle(monkeypatch):
    instance = supervisor.Supervisor()
    for name, result in [('current', 'release'), ('drain', False), ('stop_child', None), ('start_child', None), ('status', None)]:
        monkeypatch.setattr(instance, name, Mock(return_value=result))
    instance.perform('restart')
    instance.drain.assert_not_called()
    instance.stop_child.assert_called_once()
    instance.start_child.assert_called_once_with('release')


def test_manual_action_interrupts_scheduled_wait_and_resumes_scheduling(monkeypatch):
    instance = supervisor.Supervisor()
    instance.commands.put('update')
    monkeypatch.setattr(instance, 'status', Mock())
    monkeypatch.setattr(instance, 'local', Mock())
    assert instance.drain(scheduled=True) is False
    instance.local.assert_called_once_with('maintenance', {'enabled': False})
    assert instance.commands.get_nowait() == 'update'


def test_snapshot_keeps_databases_and_settings_but_skips_bulk_data(monkeypatch, tmp_path):
    import sqlite3
    state = tmp_path / 'state'
    files = {
        'config.yaml': 'a: 1',
        'cloud_auth.json': '{}',
        'work/settings.json': '{}',
        'work/flows/1/notes.json': '{}',
        'work/staging/generated/.stp-receipts/x/result.json': '{}',
        'work/prompt_programs/narrow/abc.json': '{}',
        'chats/3/workspace/data.json': '{}',
        'work.backup/settings.json': '{}',
    }
    for name, text in files.items():
        (state / name).parent.mkdir(parents=True, exist_ok=True)
        (state / name).write_text(text)
    for name in ('work/stimma_v1.db', 'work/flows/1/state.db', 'work.backup/stimma_v1.db',
                 'work/media/cache.db', 'objects/stimma_v1.db'):
        (state / name).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(state / name) as connection:
            connection.execute('CREATE TABLE t (v TEXT)')
            connection.execute("INSERT INTO t VALUES ('kept')")
    monkeypatch.setenv('STIMMA_DATA_DIR', str(state))
    monkeypatch.setattr(supervisor, 'ROOT', tmp_path)
    dest = supervisor.Supervisor().snapshot()
    copied = sorted(str(p.relative_to(dest)) for p in dest.rglob('*') if p.is_file())
    assert copied == ['cloud_auth.json', 'config.yaml', 'objects/stimma_v1.db', 'work/flows/1/state.db',
                      'work/settings.json', 'work/stimma_v1.db']
    with sqlite3.connect(dest / 'work/stimma_v1.db') as connection:
        assert connection.execute('SELECT v FROM t').fetchall() == [('kept',)]


def test_failed_snapshot_restarts_previous_release(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    previous, release = tmp_path / 'releases/old', tmp_path / 'releases/new'
    release.mkdir(parents=True)
    instance = supervisor.Supervisor()
    instance.child = Mock(poll=Mock(return_value=None))
    monkeypatch.setattr(instance, 'current', lambda: previous)
    monkeypatch.setattr(instance, 'stop_child', Mock())
    monkeypatch.setattr(instance, 'snapshot', Mock(side_effect=PermissionError('unreadable')))
    start = Mock()
    monkeypatch.setattr(instance, 'start_child', start)
    with pytest.raises(PermissionError):
        instance.activate(release)
    start.assert_called_once_with(previous)
    assert not (tmp_path / 'activation.json').exists()


class _FakeChild:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


def _fake_release(tmp_path, name):
    release = tmp_path / 'releases' / 'production' / name
    release.mkdir(parents=True)
    (release / 'release.json').write_text(json.dumps({'version': name, 'branch': 'production'}))
    return release


def test_shutdown_during_activation_waits_for_readiness_and_clears_record(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    monkeypatch.setattr(supervisor, 'BRANCH', 'production')
    monkeypatch.setattr(supervisor.time, 'sleep', lambda _: None)
    release = _fake_release(tmp_path, 'new')
    instance = supervisor.Supervisor()
    monkeypatch.setattr(instance, 'current', lambda: None)
    monkeypatch.setattr(supervisor.subprocess, 'Popen', Mock(return_value=_FakeChild()))
    calls = []

    def ready(action, body=None):
        calls.append(action)
        if len(calls) == 2:
            instance.stopping = True  # SIGTERM arrives mid-migration
        if len(calls) < 5:
            raise ConnectionRefusedError()
        return {}

    monkeypatch.setattr(instance, 'local', ready)
    instance.activate(release)
    assert len(calls) == 5
    assert instance.state['status'] == 'ready'
    assert not (tmp_path / 'activation.json').exists()


def test_shutdown_before_switch_skips_activation(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    release = _fake_release(tmp_path, 'new')
    instance = supervisor.Supervisor()
    monkeypatch.setattr(instance, 'current', lambda: None)
    monkeypatch.setattr(instance, 'stop_child', Mock(side_effect=lambda: setattr(instance, 'stopping', True)))
    start = Mock()
    monkeypatch.setattr(instance, 'start_child', start)
    instance.activate(release)
    start.assert_not_called()
    assert not (tmp_path / 'activation.json').exists()
    assert not (tmp_path / 'current').exists()


def test_slow_startup_has_no_deadline_while_server_is_alive(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    release = _fake_release(tmp_path, 'slow')
    clock = [0.0]
    monkeypatch.setattr(supervisor.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(supervisor.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + 60))
    monkeypatch.setattr(supervisor.subprocess, 'Popen', Mock(return_value=_FakeChild()))
    instance = supervisor.Supervisor()

    def ready(action, body=None):
        if clock[0] < 20 * 60:  # a long migration before the server listens
            raise ConnectionRefusedError()
        return {}

    monkeypatch.setattr(instance, 'local', ready)
    instance.start_child(release)
    assert instance.state['status'] == 'ready'
    assert 'still starting' in capsys.readouterr().out


def test_startup_wait_ends_when_server_exits(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, 'APP', tmp_path)
    release = _fake_release(tmp_path, 'broken')
    child = _FakeChild()
    monkeypatch.setattr(supervisor.subprocess, 'Popen', Mock(return_value=child))
    monkeypatch.setattr(supervisor.time, 'sleep', lambda _: setattr(child, 'returncode', 1))
    instance = supervisor.Supervisor()
    monkeypatch.setattr(instance, 'local', Mock(side_effect=ConnectionRefusedError()))
    with pytest.raises(RuntimeError, match='startup failed'):
        instance.start_child(release)


# A server whose helper (a tool, sidecar or agent shell command) outlives it
# and keeps the profile database open: the next release then refuses to migrate.
_LEAKY_SERVER = '''
import signal, sqlite3, subprocess, sys, time
db, ready, term = sys.argv[1:4]
helper = subprocess.Popen([sys.executable, '-c', f"""
import signal, sqlite3, time
signal.signal(signal.SIGTERM, signal.{term})
db = sqlite3.connect({db!r})
db.execute('PRAGMA journal_mode=WAL')
db.execute('CREATE TABLE IF NOT EXISTS t (x)')
db.execute('BEGIN')
db.execute('INSERT INTO t VALUES (1)')
open({ready!r}, 'w').close()
time.sleep(600)
"""])
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
time.sleep(600)
'''


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


@pytest.fixture
def leaky_server(tmp_path):
    import subprocess
    import sys
    import time
    started = []

    def start(term='SIG_DFL'):
        db, ready = tmp_path / 'stimma_v1.db', tmp_path / 'helper-ready'
        script = tmp_path / 'server.py'
        script.write_text(_LEAKY_SERVER)
        child = subprocess.Popen([sys.executable, str(script), str(db), str(ready), term], process_group=0)
        started.append(child)
        deadline = time.monotonic() + 20
        while not ready.exists():
            assert time.monotonic() < deadline and child.poll() is None
            time.sleep(0.05)
        return child, db

    yield start
    for child in started:
        _kill_group(child)


def test_stop_child_waits_for_helpers_that_hold_the_database(leaky_server):
    child, db = leaky_server()
    with pytest.raises(RuntimeError, match='still in use'):
        supervisor.require_exclusive(db, timeout=0.2)
    instance = supervisor.Supervisor()
    instance.child = child
    instance.stop_child()
    assert child.returncode is not None
    assert supervisor.group_members(child.pid) == []
    supervisor.require_exclusive(db, timeout=0.2)


def test_stop_group_kills_helpers_that_ignore_sigterm(leaky_server):
    import os
    import signal
    child, db = leaky_server(term='SIG_IGN')
    os.kill(child.pid, signal.SIGTERM)
    child.wait(timeout=20)
    assert supervisor.group_members(child.pid)
    supervisor.stop_group(child.pid, grace=0.2)
    assert supervisor.group_members(child.pid) == []
    supervisor.require_exclusive(db, timeout=0.2)


def test_snapshot_refuses_a_database_still_in_use(monkeypatch, tmp_path):
    import sqlite3
    monkeypatch.setattr(supervisor, 'ROOT', tmp_path)
    state = tmp_path / 'state'
    (state / 'profile-a').mkdir(parents=True)
    db = state / 'profile-a' / 'stimma_v1.db'
    holder = sqlite3.connect(db)
    holder.execute('PRAGMA locking_mode=EXCLUSIVE')
    holder.execute('CREATE TABLE t (x)')
    holder.execute('BEGIN EXCLUSIVE')
    monkeypatch.setenv('STIMMA_DATA_DIR', str(state))
    monkeypatch.setattr(supervisor, 'require_exclusive',
                        lambda path, timeout=10.0, check=supervisor.require_exclusive: check(path, timeout=0.2))
    try:
        with pytest.raises(RuntimeError, match='stimma_v1.db'):
            supervisor.Supervisor().snapshot()
    finally:
        holder.close()
    supervisor.Supervisor().snapshot()

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

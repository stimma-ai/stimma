"""Stimma's headless launcher/update supervisor. Python standard library only."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import secrets
import shutil
import signal
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get('STIMMA_HEADLESS_ROOT', '/data'))
APP = ROOT / 'app'
SOCKET = ROOT / 'control.sock'
BOOTSTRAP = Path('/opt/stimma/bootstrap-version')
PUBLIC_KEY = Path(os.environ.get('STIMMA_UPDATE_PUBLIC_KEY', '/opt/stimma/updater.pub'))
BRANCH = os.environ.get('BRANCH', 'production')
ARCH = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine(), platform.machine())
TARGET = f'headless-linux-{ARCH}'
BASE_URL = os.environ.get('STIMMA_UPDATE_BASE_URL', 'https://updates.stimma.ai').rstrip('/')
LOCAL_PORT = int(os.environ.get('STIMMA_LOCAL_PORT', '9191'))


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def version_tuple(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Invalid bootstrap version')
    return tuple(map(int, value.split('.')))


def window_key(window: str, timezone: str, now=None):
    """One attempt per local window, including windows spanning midnight/DST."""
    if not window:
        return None
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d', window):
        raise ValueError('UPDATE_WINDOW must be HH:MM-HH:MM')
    start, end = [int(v[:2]) * 60 + int(v[3:]) for v in window.split('-')]
    if start == end:
        raise ValueError('Update window must have different start and end times')
    now = now or dt.datetime.now(ZoneInfo(timezone))
    minute = now.hour * 60 + now.minute
    inside = start <= minute < end if start < end else minute >= start or minute < end
    if not inside:
        return None
    day = now.date() - dt.timedelta(days=int(start > end and minute < end))
    return day.isoformat()


def fetch(url: str, destination: Path, limit=4 * 1024**3):
    if not url.startswith('https://'):
        raise ValueError('Updates require HTTPS')
    with urllib.request.urlopen(url, timeout=30) as response, destination.open('wb') as out:
        if not response.url.startswith('https://'):
            raise ValueError('Insecure update redirect')
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError('Update exceeds download limit')
            out.write(chunk)


def verify(path: Path, signature: str):
    signature_path = path.with_suffix(path.suffix + '.minisig')
    signature_path.write_bytes(base64.b64decode(signature, validate=True))
    subprocess.run(['minisign', '-Vm', str(path), '-x', str(signature_path), '-p', str(PUBLIC_KEY)],
                   check=True, capture_output=True, timeout=30)


def unpack(archive: Path, destination: Path):
    """Permit internal relative symlinks (portable Python), never traversal/devices."""
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if sum(m.size for m in members) > 12 * 1024**3:
            raise ValueError('Unpacked update exceeds size limit')
        for member in members:
            path = (destination / member.name).resolve()
            if not path.is_relative_to(destination.resolve()) or member.isdev() or member.isfifo():
                raise ValueError('Unsafe package entry')
            if member.islnk() or member.issym():
                target = (path.parent if member.issym() else destination) / member.linkname
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError('Unsafe package link')
        # Debian's Python may predate tarfile's extraction filters. Extract only
        # these four types ourselves and recheck paths after each created link.
        for member in members:
            path = destination / member.name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Package link traverses outside installation')
            path.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                path.mkdir(exist_ok=True)
            elif member.isfile():
                with bundle.extractfile(member) as source, path.open('wb') as out:
                    shutil.copyfileobj(source, out)
                path.chmod(member.mode & 0o755)
            elif member.issym():
                path.symlink_to(member.linkname)
            elif member.islnk():
                target = destination / member.linkname
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError('Unsafe hard link')
                os.link(target, path)
            else:
                raise ValueError('Unsupported package entry')
    if not (destination / 'run.sh').is_file():
        raise ValueError('Package has no server launcher')


def control(action: str):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(SOCKET))
        client.sendall((json.dumps({'action': action}) + '\n').encode())
        with client.makefile('r') as stream:
            result = json.loads(stream.readline(1024 * 1024))
        if result.get('error') and not result.get('headless'):
            raise RuntimeError(result['error'])
        return result


class Supervisor:
    def __init__(self):
        if BRANCH not in ('production', 'beta', 'canary'):
            raise ValueError('Unknown BRANCH')
        if ARCH not in ('x86_64', 'aarch64'):
            raise ValueError('Unsupported architecture')
        self.window = os.environ.get('UPDATE_WINDOW', '')
        self.timezone = os.environ.get('TZ', 'UTC')
        ZoneInfo(self.timezone)
        window_key(self.window, self.timezone)
        self.base_version = BOOTSTRAP.read_text().strip() if BOOTSTRAP.exists() else '0.0.0'
        self.commands = queue.Queue(maxsize=1)
        self.child = None
        self.stopping = False
        self.token = secrets.token_urlsafe(32)
        self.manifest = None
        self.state = {'headless': True, 'status': 'starting', 'version': None,
                      'branch': BRANCH, 'bootstrapVersion': self.base_version,
                      'availableVersion': None, 'bootstrapUpdateRequired': False,
                      'bootstrapUpdateAvailable': False, 'updateWindow': self.window or None,
                      'timezone': self.timezone, 'error': None, 'lastCheckedAt': None}

    def status(self, **values):
        self.state.update(values)
        atomic_json(APP / 'status.json', self.state)
        return dict(self.state)

    def local(self, action: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f'http://127.0.0.1:{LOCAL_PORT}/api/headless/{action}', data=data,
                                     headers={'Content-Type': 'application/json',
                                              'X-Stimma-Supervisor': self.token})
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    def check(self):
        if os.environ.get('STIMMA_PRIVACY_LOCKDOWN', '').lower() in ('1', 'true', 'yes', 'on'):
            raise RuntimeError('Updates are paused by Privacy Lockdown')
        self.status(status='checking', error=None)
        with tempfile.TemporaryDirectory(dir=APP) as tmp:
            path = Path(tmp) / 'manifest.json'
            fetch(f'{BASE_URL}/stimma/{BRANCH}/{TARGET}/latest.json', path, 1024 * 1024)
            envelope = json.loads(path.read_text())
            # The signature covers all metadata, including branch, digest and base requirements.
            path.write_bytes(base64.b64decode(envelope['payload'], validate=True))
            verify(path, envelope['signature'])
            manifest = json.loads(path.read_text())
        if manifest['branch'] != BRANCH or manifest['target'] != TARGET:
            raise ValueError('Update feed identity mismatch')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,99}', manifest['version']):
            raise ValueError('Invalid package version')
        if not re.fullmatch(r'[a-f0-9]{64}', manifest['sha256']):
            raise ValueError('Invalid package digest')
        required = version_tuple(manifest['minimumBootstrapVersion']) > version_tuple(self.base_version)
        latest = manifest.get('latestBootstrapVersion', manifest['minimumBootstrapVersion'])
        self.manifest = manifest
        self.status(status='ready' if self.child else 'starting', availableVersion=manifest['version'],
                    bootstrapUpdateRequired=required,
                    bootstrapUpdateAvailable=version_tuple(latest) > version_tuple(self.base_version),
                    latestBootstrapVersion=latest, lastCheckedAt=dt.datetime.now(dt.timezone.utc).isoformat())
        return manifest

    def stage(self):
        m = self.manifest
        if self.state['bootstrapUpdateRequired']:
            raise RuntimeError('Update the Docker base image: docker compose pull && docker compose up -d')
        destination = APP / 'releases' / BRANCH / (m['version'] + '-' + m['sha256'][:12])
        if destination.exists():
            return destination
        self.status(status='downloading')
        with tempfile.TemporaryDirectory(dir=APP) as tmp:
            archive = Path(tmp) / 'server.tar.gz'
            fetch(m['url'], archive)
            with archive.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != m['sha256']:
                raise ValueError('Package digest mismatch')
            stage = Path(tmp) / 'release'
            stage.mkdir()
            unpack(archive, stage)
            atomic_json(stage / 'release.json', m)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stage, destination)
        return destination

    def current(self):
        link = APP / 'current'
        if not link.exists():
            return None
        path = link.resolve()
        metadata = json.loads((path / 'release.json').read_text())
        if metadata['branch'] != BRANCH:
            raise RuntimeError('Cached app belongs to another BRANCH; choose the original branch or a new data volume')
        return path

    def stop_child(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=110)
            except subprocess.TimeoutExpired:
                # Never activate a new package while old workers may still be writing.
                raise RuntimeError('Server did not stop cleanly; update was not applied')
        self.child = None

    def snapshot(self):
        """Backend is stopped. Copy databases/config only; media remains in place."""
        state = Path(os.environ.get('STIMMA_DATA_DIR', str(ROOT / 'state')))
        dest = ROOT / 'backups' / str(time.time_ns())
        for source in state.rglob('*'):
            if source.is_file() and source.suffix in ('.db', '.sqlite', '.sqlite3', '.yaml', '.json'):
                # Managed payloads and model caches are not configuration.
                if any(part in ('storage', 'managed', 'cache', 'media') for part in source.relative_to(state).parts):
                    continue
                target = dest / source.relative_to(state)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix in ('.db', '.sqlite', '.sqlite3'):
                    # SQLite's backup API includes any retained WAL transactions.
                    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
                        src.backup(dst)
                else:
                    shutil.copy2(source, target)
        return dest

    def start_child(self, release):
        metadata = json.loads((release / 'release.json').read_text())
        env = dict(os.environ, STIMMA_HEADLESS='1', STIMMA_SUPERVISOR_TOKEN=self.token,
                   STIMMA_APP_VERSION=metadata['version'], STIMMA_RELEASE_CHANNEL=BRANCH,
                   STIMMA_DISTRIBUTION='official', STIMMA_DATA_DIR=str(ROOT / 'state'),
                   STIMMA_CACHE_DIR=str(ROOT / 'cache'))
        # Agent shell commands use the same fully provisioned Python as the server.
        env['PATH'] = f"{release}/python/bin:" + env.get('PATH', '')
        bundle = 'ai.stimma.stimma' + (f'.{BRANCH}' if BRANCH != 'production' else '')
        self.child = subprocess.Popen([str(release / 'run.sh'), '--bundle-id', bundle,
                                       '--port', str(LOCAL_PORT)], env=env, cwd=release)
        self.status(status='starting', version=metadata['version'])
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not self.stopping:
            if self.child.poll() is not None:
                raise RuntimeError('Server startup failed; retained package and data for recovery')
            try:
                self.local('ready')
                self.status(status='ready')
                return
            except Exception:
                time.sleep(1)
        raise RuntimeError('Server readiness timed out')

    def activate(self, release):
        previous = self.current()
        if previous == release:
            return
        self.stop_child()
        backup = self.snapshot() if previous else None
        # Persist before switching: after interrupted migrations, fail closed on next startup.
        atomic_json(APP / 'activation.json', {'previous': str(previous) if previous else None,
                                            'candidate': str(release), 'backup': str(backup) if backup else None})
        link = APP / 'current.new'
        link.unlink(missing_ok=True)
        link.symlink_to(release.relative_to(APP))
        os.replace(link, APP / 'current')
        self.start_child(release)
        (APP / 'activation.json').unlink()
        retained = {release, previous}
        for candidate in (APP / 'releases' / BRANCH).iterdir():
            if candidate.is_dir() and candidate not in retained:
                shutil.rmtree(candidate)
        backups = sorted((ROOT / 'backups').glob('*'), key=lambda p: p.name, reverse=True)
        for backup in backups[3:]:
            if backup.is_dir():
                shutil.rmtree(backup)

    def drain(self, scheduled=False):
        self.status(status='waiting_for_idle')
        deadline = time.monotonic() + 3600
        try:
            while not self.stopping and time.monotonic() < deadline:
                if scheduled and not window_key(self.window, self.timezone):
                    return False
                state = self.local('maintenance', {'enabled': True})
                if state['idle']:
                    return True
                time.sleep(2)
            return False
        finally:
            # The caller stops the backend immediately after a successful drain.
            if self.stopping or time.monotonic() >= deadline or (scheduled and not window_key(self.window, self.timezone)):
                self.local('maintenance', {'enabled': False})

    def perform(self, action, scheduled=False):
        if action in ('check', 'update'):
            self.check()
        if action == 'update':
            release = self.stage()
            if release != self.current() and (not self.child or self.drain(scheduled)):
                self.activate(release)
        elif action == 'restart':
            if self.drain():
                self.status(status='restarting')
                self.stop_child()
                self.start_child(self.current())
        elif action == 'login':
            self.local('login', {})
        elif action == 'logout':
            self.local('logout', {})
        self.status(status='ready' if self.child else 'starting')

    def run(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        APP.mkdir(parents=True, exist_ok=True)
        lock = (APP / 'supervisor.lock').open('w')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        supervisor = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(5)
                try:
                    action = json.loads(self.rfile.readline(4096))['action']
                    if action not in ('status', 'check', 'update', 'restart', 'login', 'logout'):
                        raise ValueError('Unknown command')
                    if action != 'status':
                        if supervisor.state['status'] not in ('ready', 'error'):
                            raise ValueError('Another server operation is in progress')
                        supervisor.commands.put_nowait(action)
                    result = dict(supervisor.state, serverRunning=bool(supervisor.child and supervisor.child.poll() is None))
                except Exception as exc:
                    result = {'error': str(exc)}
                self.wfile.write((json.dumps(result) + '\n').encode())

        SOCKET.unlink(missing_ok=True)
        server = socketserver.ThreadingUnixStreamServer(str(SOCKET), Handler)
        server.daemon_threads = True
        os.chmod(SOCKET, 0o600)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: setattr(self, 'stopping', True))
        try:
            if (APP / 'activation.json').exists():
                raise RuntimeError('Interrupted or failed activation: inspect app/activation.json and restore its backup before restarting')
            try:
                self.check()
                self.activate(self.stage())
            except Exception as exc:
                self.status(error=str(exc))
                print(f'[stimma] Startup update unavailable: {exc}', flush=True)
                if (APP / 'activation.json').exists():
                    raise
            if not self.child:
                current = self.current()
                if current is None:
                    raise RuntimeError('No cached server package; retry when the update service is available')
                self.start_child(current)
            attempted = None
            while not self.stopping:
                if self.child.poll() is not None:
                    raise RuntimeError('Server exited unexpectedly')
                scheduled = False
                try:
                    action = self.commands.get(timeout=2)
                except queue.Empty:
                    key = window_key(self.window, self.timezone)
                    if not key or key == attempted:
                        continue
                    attempted, action, scheduled = key, 'update', True
                try:
                    self.perform(action, scheduled)
                except Exception as exc:
                    self.status(status='error', error=str(exc))
                    print(f'[stimma] {exc}', flush=True)
                    if (APP / 'activation.json').exists():
                        raise
                    if self.child and self.child.poll() is None:
                        self.local('maintenance', {'enabled': False})
        finally:
            self.stop_child()
            server.shutdown()
            server.server_close()
            SOCKET.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='Stimma headless server')
    parser.add_argument('action', nargs='?', default='serve',
                        choices=['serve', 'status', 'health', 'check', 'update', 'restart', 'login', 'logout'])
    action = parser.parse_args().action
    if action == 'serve':
        Supervisor().run()
    else:
        result = control('status' if action == 'health' else action)
        if action == 'health':
            if not result.get('serverRunning') and result['status'] not in ('starting', 'downloading', 'checking'):
                sys.exit(1)
        else:
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'[stimma] {error}', file=sys.stderr, flush=True)
        sys.exit(1)

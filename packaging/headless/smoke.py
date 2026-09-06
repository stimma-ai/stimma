"""Real Docker/package smoke: signed startup, in-place update, restart and cache recovery."""
import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='stimma-server:test')
    args = parser.parse_args()
    image = args.image
    base_version = (ROOT / 'packaging/headless/VERSION').read_text().strip()
    # Bind-mounted fixtures belong to the runner (GitHub uses UID 1001).
    fixture_user = f'{os.getuid()}:{os.getgid()}'
    archives = list((ROOT / 'dist-headless').glob('*.tar.gz'))
    if len(archives) != 1:
        raise RuntimeError('Build one headless package before running smoke')
    archive = archives[0]
    manifest = json.loads((ROOT / 'dist-headless/manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='stimma-server-smoke-') as tmp:
        root = Path(tmp)
        os.chmod(root, 0o755)
        cert = root / 'cert.pem'
        key = root / 'tls.key'
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cert),
            '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run('docker', 'run', '--rm', '--user', fixture_user, '-v', f'{root}:/fixture', '--entrypoint', 'minisign', image,
            '-G', '-W', '-p', '/fixture/test.pub', '-s', '/fixture/test.key', stdout=subprocess.DEVNULL)
        # Only serve fixture files. Never serve the ephemeral private signing key.
        public = root / 'public'
        public.mkdir()
        shutil.copy2(archive, public / 'server.tar.gz')
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(public), **kwargs)
            def log_message(self, *_):
                pass
            def do_POST(self):
                self.send_error(503, 'Cloud disabled in packaging smoke')
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'https://localhost:{server.server_port}'
        manifest['url'] = f'{base}/server.tar.gz'
        manifest['sha256'] = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
        feed = public / 'stimma' / manifest['branch'] / manifest['target']
        feed.mkdir(parents=True)
        def publish(version, minimum=base_version):
            manifest.update(version=version, minimumBootstrapVersion=minimum)
            payload = root / 'manifest.json'
            payload.write_text(json.dumps(manifest))
            run('docker', 'run', '--rm', '--user', fixture_user, '-v', f'{root}:/fixture', '--entrypoint', 'minisign', image,
                '-Sm', '/fixture/manifest.json', '-s', '/fixture/test.key', stdout=subprocess.DEVNULL)
            envelope = {'payload': base64.b64encode(payload.read_bytes()).decode(),
                        'signature': base64.b64encode((root / 'manifest.json.minisig').read_bytes()).decode()}
            (feed / 'latest.json').write_text(json.dumps(envelope))
        publish('0.0.0-smoke.1')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = str(probe.getsockname()[1])
        name = 'stimma-server-smoke-' + str(os.getpid())
        # Keep Unix control sockets on the Linux filesystem, including when
        # smoke runs against Docker Desktop's macOS shared directories. The
        # image's own user (uid 1000) owns the volume, so the server container
        # runs as itself; only the bind-mounted fixtures need the runner's uid.
        volume = name + '-data'
        def docker(*command):
            return run('docker', *command, capture_output=True).stdout.strip()
        def status():
            return json.loads(docker('exec', name, 'stimma-server', 'status'))
        def check_ui_package():
            # Exercise the packaged routes from the container's loopback interface;
            # no account credentials or external cloud service are needed.
            script = '''
import hashlib, io, json, os, tarfile, urllib.request
base = 'http://127.0.0.1:' + os.environ['STIMMA_LOCAL_PORT']
with urllib.request.urlopen(base + '/api/mobile-ui/manifest', timeout=10) as response:
    manifest = json.load(response)
assert manifest['formatVersion'] == manifest['bridgeVersion'] == manifest['apiVersion'] == 1
assert manifest['entrypoint'] == 'index.html'
with urllib.request.urlopen(base + '/api/mobile-ui/packages/' + manifest['hash'] + '.tar.gz', timeout=10) as response:
    archive = response.read()
assert len(archive) == manifest['bytes']
assert hashlib.sha256(archive).hexdigest() == manifest['hash']
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as package:
    members = package.getmembers()
    names = [member.name for member in members]
    assert 'index.html' in names and 'mobile.html' not in names
    assert any(name.endswith('.js') for name in names)
    assert sum(member.size for member in members) == manifest['unpackedBytes']
'''
            docker('exec', name, 'python3', '-c', script)
        def wait(version):
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                try:
                    state = status()
                    if state['version'] == version and state['status'] == 'ready':
                        return state
                    if state['status'] == 'error':
                        raise RuntimeError(state['error'])
                except subprocess.CalledProcessError:
                    if docker('inspect', name, '--format', '{{.State.Running}}') != 'true':
                        raise RuntimeError('Container exited before readiness')
                time.sleep(2)
            raise RuntimeError('Container did not become ready')
        try:
            docker('volume', 'create', volume)
            docker('run', '-d', '--name', name, '--network', 'host', '-v', f'{volume}:/data',
                   '-v', f'{root}/test.pub:/opt/stimma/updater.pub:ro', '-v', f'{cert}:/opt/stimma/test-ca.pem:ro',
                   '-e', 'SSL_CERT_FILE=/opt/stimma/test-ca.pem', '-e', f'STIMMA_UPDATE_BASE_URL={base}',
                   '-e', f'STIMMA_CLOUD_BASE_URL={base}', '-e', f'STIMMA_LOCAL_PORT={port}', '-e', f"BRANCH={manifest['branch']}", image)
            state = wait('0.0.0-smoke.1')
            assert state['bootstrapVersion'] == base_version
            check_ui_package()
            docker('exec', name, 'bash', '-c', 'ffmpeg -version >/dev/null && python3 --version && git --version && rg --version && jq --version')
            image_id = docker('inspect', name, '--format', '{{.Image}}')
            publish('0.0.0-smoke.2')
            docker('exec', name, 'stimma-server', 'update')
            wait('0.0.0-smoke.2')
            check_ui_package()
            assert docker('inspect', name, '--format', '{{.Image}}') == image_id
            docker('exec', name, 'stimma-server', 'restart')
            time.sleep(5)
            wait('0.0.0-smoke.2')
            publish('0.0.0-smoke.3', minimum='99.0.0')
            docker('exec', name, 'stimma-server', 'check')
            time.sleep(4)
            assert status()['bootstrapUpdateRequired'] is True
            assert status()['version'] == '0.0.0-smoke.2'
            server.shutdown()
            server.server_close()
            docker('restart', '--time', '120', name)
            wait('0.0.0-smoke.2')
            check_ui_package()
            print('PASS: signed real-package startup, UI package integrity, unchanged-image update, restart, base requirement, cached offline boot')
        except Exception:
            print(docker('inspect', name, '--format', '{{json .State}}'))
            logs = run('docker', 'logs', '--tail', '100', name, capture_output=True)
            print(logs.stdout)
            print(logs.stderr)
            raise
        finally:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['docker', 'volume', 'rm', volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

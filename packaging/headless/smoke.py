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
    parser.add_argument('--image', default='stimma-headless:test')
    args = parser.parse_args()
    image = args.image
    archives = list((ROOT / 'dist-headless').glob('*.tar.gz'))
    if len(archives) != 1:
        raise RuntimeError('Build one headless package before running smoke')
    archive = archives[0]
    manifest = json.loads((ROOT / 'dist-headless/manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='stimma-headless-smoke-') as tmp:
        root = Path(tmp)
        os.chmod(root, 0o755)
        data = root / 'data'
        data.mkdir()
        cert = root / 'cert.pem'
        key = root / 'tls.key'
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cert),
            '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run('docker', 'run', '--rm', '-v', f'{root}:/fixture', '--entrypoint', 'minisign', image,
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
        def publish(version, minimum='1.0.0'):
            manifest.update(version=version, minimumBootstrapVersion=minimum)
            payload = root / 'manifest.json'
            payload.write_text(json.dumps(manifest))
            run('docker', 'run', '--rm', '-v', f'{root}:/fixture', '--entrypoint', 'minisign', image,
                '-Sm', '/fixture/manifest.json', '-s', '/fixture/test.key', stdout=subprocess.DEVNULL)
            envelope = {'payload': base64.b64encode(payload.read_bytes()).decode(),
                        'signature': base64.b64encode((root / 'manifest.json.minisig').read_bytes()).decode()}
            (feed / 'latest.json').write_text(json.dumps(envelope))
        publish('0.0.0-smoke.1')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = str(probe.getsockname()[1])
        name = 'stimma-headless-smoke-' + str(os.getpid())
        def docker(*command):
            return run('docker', *command, capture_output=True).stdout.strip()
        def status():
            return json.loads(docker('exec', name, 'stimma-server', 'status'))
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
            docker('run', '-d', '--name', name, '--network', 'host', '-v', f'{data}:/data',
                   '-v', f'{root}/test.pub:/opt/stimma/updater.pub:ro', '-v', f'{cert}:/opt/stimma/test-ca.pem:ro',
                   '-e', 'SSL_CERT_FILE=/opt/stimma/test-ca.pem', '-e', f'STIMMA_UPDATE_BASE_URL={base}',
                   '-e', f'STIMMA_CLOUD_BASE_URL={base}', '-e', f'STIMMA_LOCAL_PORT={port}', '-e', f"BRANCH={manifest['branch']}", image)
            state = wait('0.0.0-smoke.1')
            assert state['bootstrapVersion'] == '1.0.0'
            docker('exec', name, 'bash', '-c', 'ffmpeg -version >/dev/null && python3 --version && git --version && rg --version && jq --version')
            image_id = docker('inspect', name, '--format', '{{.Image}}')
            publish('0.0.0-smoke.2')
            docker('exec', name, 'stimma-server', 'update')
            wait('0.0.0-smoke.2')
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
            print('PASS: signed real-package startup, unchanged-image update, restart, base requirement, cached offline boot')
        except Exception:
            logs = docker('logs', '--tail', '100', name)
            print(logs)
            raise
        finally:
            subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

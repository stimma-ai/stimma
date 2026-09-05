#!/usr/bin/env python3
"""First-party headless build and publication commands (invoked by tools/stimma)."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import tempfile
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / 'packaging/headless'


def run(*args, **kwargs):
    subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def package(version, branch):
    if platform.system() != 'Linux':
        raise SystemExit('Build headless packages on Linux')
    target = subprocess.check_output(['rustc', '-Vv'], text=True).split('host: ')[1].splitlines()[0]
    run('bash', 'scripts/build-portable-backend.sh', env=dict(os.environ, STIMMA_DISTRIBUTION='official'))
    source = ROOT / 'src-tauri/binaries' / f'stimma-backend-{target}'
    import shutil
    for name in ('config.default.yaml', 'ATTRIBUTION.md', 'LICENSE'):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, source / name)
    shutil.copy2(PACKAGING / 'supervisor.py', source / 'supervisor.py')
    arch = target.split('-')[0]
    output = ROOT / 'dist-headless'
    output.mkdir(exist_ok=True)
    name = f'stimma-headless-{version}-linux-{arch}.tar.gz'
    run('tar', '--sort=name', '--owner=0', '--group=0', '--numeric-owner', '-czf', str(output / name), '-C', str(source), '.')
    # The build host can use Python 3.10 (Ubuntu 22.04); the bundled runtime is 3.11.
    digest = hashlib.sha256()
    with (output / name).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    base = os.environ.get('STIMMA_UPDATE_BASE_URL', 'https://updates.stimma.ai').rstrip('/')
    metadata = {'version': version, 'branch': branch, 'target': f'headless-linux-{arch}',
                'sha256': digest.hexdigest(), 'url': f'{base}/stimma/{branch}/headless-linux-{arch}/{version}/{name}',
                'minimumBootstrapVersion': '1.0.0', 'latestBootstrapVersion': (PACKAGING / 'VERSION').read_text().strip(),
                'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    (output / 'manifest.json').write_text(json.dumps(metadata, sort_keys=True))
    print(f'Built {name}')


def publish():
    output = ROOT / 'dist-headless'
    manifest = output / 'manifest.json'
    m = json.loads(manifest.read_text())
    # Tauri signs the complete manifest, not just the archive, protecting compatibility metadata.
    signer = ROOT / 'frontend/node_modules/.bin/tauri'
    run(str(signer), 'signer', 'sign', str(manifest), stdout=subprocess.DEVNULL,
        env=dict(os.environ, TAURI_PRIVATE_KEY=os.environ['TAURI_SIGNING_PRIVATE_KEY'],
                 TAURI_PRIVATE_KEY_PASSWORD=os.environ.get('TAURI_SIGNING_PRIVATE_KEY_PASSWORD', '')))
    signature = manifest.with_suffix('.json.sig').read_text().strip()
    envelope = {'payload': base64.b64encode(manifest.read_bytes()).decode(), 'signature': signature}
    (output / 'latest.json').write_text(json.dumps(envelope))
    prefix = f"stimma/{m['branch']}/{m['target']}"
    def version_key(value):
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?(?:\+[A-Za-z0-9.-]+)?', value)
        if not match:
            raise ValueError('Invalid release version')
        major, minor, patch, prerelease = match.groups()
        parts = tuple((0, int(p)) if p.isdigit() else (1, p) for p in (prerelease or '').split('.'))
        return int(major), int(minor), int(patch), prerelease is None, parts
    version_key(m['version'])

    bucket = os.environ['R2_BUCKET']
    endpoint = os.environ['R2_S3_ENDPOINT']
    with tempfile.TemporaryDirectory() as tmp:
        previous = Path(tmp) / 'latest.json'
        existing = subprocess.run(['uvx', '--from', 'awscli', 'aws', 's3', 'cp',
            f's3://{bucket}/{prefix}/latest.json', str(previous), '--endpoint-url', endpoint],
            capture_output=True, text=True)
        if existing.returncode == 0:
            old = json.loads(base64.b64decode(json.loads(previous.read_text())['payload']))
            if version_key(m['version']) < version_key(old['version']):
                raise RuntimeError('Refusing to move headless feed backwards')
            if m['version'] == old['version'] and m['sha256'] != old['sha256']:
                raise RuntimeError('Release version already published with different package contents')
        elif '404' not in existing.stderr and 'NoSuchKey' not in existing.stderr:
            raise RuntimeError('Could not verify current release feed; publication stopped')
    for file, key, cache in (
        (output / m['url'].rsplit('/', 1)[-1], f"{prefix}/{m['version']}/{m['url'].rsplit('/', 1)[-1]}", 'public,max-age=31536000,immutable'),
        (output / 'latest.json', f'{prefix}/latest.json', 'no-cache'),
    ):
        run('uvx', '--from', 'awscli', 'aws', 's3', 'cp', str(file), f's3://{bucket}/{key}',
            '--endpoint-url', endpoint, '--cache-control', cache)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['package', 'image', 'test', 'publish', 'smoke'])
    parser.add_argument('--version', default='0.0.0-test')
    parser.add_argument('--branch', choices=['canary', 'beta', 'production'], default='production')
    parser.add_argument('--tag', default='stimma-headless:test')
    args = parser.parse_args()
    if args.command == 'package':
        package(args.version, args.branch)
    elif args.command == 'image':
        run('docker', 'build', '-f', 'packaging/headless/Dockerfile', '--build-arg',
            'BOOTSTRAP_VERSION=' + (PACKAGING / 'VERSION').read_text().strip(), '-t', args.tag, '.')
    elif args.command == 'test':
        run('uv', 'run', '--project', 'backend', 'pytest', 'backend/tests/test_headless_supervisor.py', 'backend/tests/test_headless_runtime.py')
    elif args.command == 'smoke':
        run('uv', 'run', '--project', 'backend', 'python', 'packaging/headless/smoke.py', '--image', args.tag)
    else:
        publish()


if __name__ == '__main__':
    main()

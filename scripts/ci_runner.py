#!/usr/bin/env python3
"""Prepared Linux runner checks and bounded, immutable action-archive caching."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request


ACTION = re.compile(
    r"^\[[^\]]+ INFO ActionManager\] Check if action archive "
    r"'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([a-f0-9]{40})'"
)
WORKFLOW_ACTION = re.compile(
    r'^\s*(?:-\s*)?uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([a-f0-9]{40})(?:\s+#.*)?$',
    re.MULTILINE,
)


def check_runner(temporary, cache):
    """Test the filesystem's execution policy with a native binary, not a shell."""
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stimma-runner-check-', dir=temporary) as tmp:
        executable = Path(tmp) / 'check'
        shutil.copyfile(shutil.which('true') or '/bin/true', executable)
        executable.chmod(0o700)
        try:
            subprocess.run([str(executable)], check=True, timeout=5, capture_output=True)
        except PermissionError as error:
            raise RuntimeError('Runner temporary filesystem must allow execution (mount with exec)') from error
    paths = {cache}
    uv_cache = Path(os.environ.get('UV_CACHE_DIR', cache / 'uv')).resolve()
    for key in ('UV_PYTHON_INSTALL_DIR', 'UV_TOOL_DIR', 'UV_TOOL_BIN_DIR'):
        if os.environ.get(key):
            installed = Path(os.environ[key]).resolve()
            if installed == uv_cache or uv_cache in installed.parents:
                raise RuntimeError('Persistent uv Python/tool directories must be outside UV_CACHE_DIR; '
                                   'uv cache prune removes them')
    for key in ('RUNNER_TOOL_CACHE', 'UV_PYTHON_INSTALL_DIR', 'UV_TOOL_DIR',
                'UV_TOOL_BIN_DIR', 'DENO_INSTALL', 'NPM_CONFIG_CACHE'):
        if os.environ.get(key):
            paths.add(Path(os.environ[key]))
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b'prepared-runner-check')
    return {'temporary_executables': True, 'cache_writable': True}


def resolved_actions(log):
    """Only ActionManager records count; ignore strings printed by job steps."""
    actions = set()
    with log.open(errors='replace') as source:
        for line in source:
            match = ACTION.match(line)
            if match:
                repo, commit = match.groups()
                if all(part not in ('.', '..') for part in repo.split('/')):
                    actions.add((repo, commit))
    return sorted(actions)


def workflow_actions(root):
    actions = set()
    for path in root.rglob('*.yml'):
        for repo, commit in WORKFLOW_ACTION.findall(path.read_text()):
            if all(part not in ('.', '..') for part in repo.split('/')):
                actions.add((repo, commit))
    return sorted(actions)


def validate_archive(path):
    with tarfile.open(path, 'r:gz') as archive:
        found = False
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe action archive member')
            found = True
        if not found:
            raise ValueError('Empty action archive')


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def download_action(repo, commit, destination, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Action-cache maintenance budget exhausted')
    request = urllib.request.Request(
        f'https://codeload.github.com/{repo}/tar.gz/{commit}',
        headers={'User-Agent': 'Stimma-CI-action-cache'},
    )
    with urllib.request.urlopen(request, timeout=min(5, remaining)) as response, destination.open('wb') as target:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Action-cache maintenance budget exhausted')
            block = response.read(64 * 1024)
            if not block:
                break
            target.write(block)


def warm_actions(actions, cache, budget=20, download=download_action):
    deadline = time.monotonic() + budget
    result = {'reused': 0, 'downloaded': 0}
    for repo, commit in actions:
        folder = cache / repo.replace('/', '_')
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / f'{commit}.tar.gz'
        metadata = archive.with_suffix('.json')
        if archive.exists() and metadata.exists():
            try:
                if digest(archive) == json.loads(metadata.read_text())['sha256']:
                    result['reused'] += 1
                    continue
            except (ValueError, KeyError):
                pass
        if time.monotonic() >= deadline:
            raise TimeoutError('Action-cache maintenance budget exhausted')
        with tempfile.TemporaryDirectory(prefix='.action-cache-', dir=folder) as tmp:
            partial = Path(tmp) / 'archive.tar.gz'
            download(repo, commit, partial, deadline)
            validate_archive(partial)
            summary = {'repository': repo, 'commit': commit, 'sha256': digest(partial)}
            sidecar = Path(tmp) / 'metadata.json'
            sidecar.write_text(json.dumps(summary, indent=2) + '\n')
            # The runner only reads the final archive name. Never expose a
            # partial download, even if maintenance is interrupted.
            partial.replace(archive)
            sidecar.replace(metadata)
        result['downloaded'] += 1
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check')
    check.add_argument('--temp', type=Path, default=Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir())))
    check.add_argument('--cache', type=Path, default=Path.home() / '.cache')
    cache = commands.add_parser('cache-actions')
    source = cache.add_mutually_exclusive_group(required=True)
    source.add_argument('--logs', type=Path)
    source.add_argument('--workflows', type=Path)
    cache.add_argument('--cache', type=Path, default=os.environ.get('ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE'))
    cache.add_argument('--budget', type=float, default=20)
    args = parser.parse_args(argv)
    if args.command == 'check':
        print(json.dumps(check_runner(args.temp, args.cache)))
        return 0
    # This is maintenance after the job's real checks. A cache miss or network
    # outage must never turn successful tests/publication into a failed job.
    try:
        if args.cache is None:
            print('Action archive cache is not configured; maintenance skipped')
            return 0
        if args.workflows:
            actions = workflow_actions(args.workflows)
        else:
            logs = list(args.logs.glob('Worker_*.log'))
            if not logs:
                print('No runner action-resolution log; maintenance skipped')
                return 0
            latest = max(logs, key=lambda path: path.stat().st_mtime)
            actions = resolved_actions(latest)
        print(json.dumps(warm_actions(actions, args.cache, args.budget)))
    except (OSError, ValueError, tarfile.TarError, TimeoutError) as error:
        print(f'::warning::Action-cache maintenance skipped: {type(error).__name__}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Reuse completed same-repository PR quality checks for an identical Git tree."""
import io
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile


def tree():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], text=True).strip()


def matches(proof, expected_tree, suite, run_id):
    return proof == {'schema': 1, 'tree': expected_tree, 'suite': suite, 'run_id': str(run_id)}


def eligible(run, repository):
    return (run.get('event') == 'pull_request' and run.get('status') == 'completed'
            and run.get('conclusion') == 'success'
            and run.get('head_repository', {}).get('full_name') == repository
            and run.get('repository', {}).get('full_name') == repository)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(path, archive=False):
    base = os.environ.get('GITHUB_API_URL', 'https://api.github.com')
    request = urllib.request.Request(f'{base}/repos/{os.environ["GITHUB_REPOSITORY"]}/{path}', headers={
        'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN'],
        'Accept': 'application/vnd.github+json',
    })
    # Artifact storage redirects must never receive the API credential.
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=10)
    except urllib.error.HTTPError as error:
        if not archive or error.code != 302:
            raise
        location = error.headers['Location']
        if not location.startswith('https://'):
            raise ValueError('Artifact download must use HTTPS')
        response = urllib.request.urlopen(location, timeout=10)
    with response:
        data = response.read(65537 if archive else 2_000_000)
    if archive:
        if len(data) > 65536:
            raise ValueError('Oversized quality proof archive')
        with zipfile.ZipFile(io.BytesIO(data)) as zipped:
            info = zipped.getinfo('quality-proof.json')
            if info.file_size > 4096:
                raise ValueError('Oversized quality proof')
            return json.loads(zipped.read(info))
    return json.loads(data)


def lookup(expected_tree, suite, get=api):
    repository = os.environ['GITHUB_REPOSITORY']
    runs = get('actions/workflows/ci.yml/runs?event=pull_request&status=success&per_page=10')['workflow_runs']
    for run in runs:
        if not eligible(run, repository):
            continue
        artifacts = get(f'actions/runs/{run["id"]}/artifacts?per_page=100')['artifacts']
        for artifact in artifacts:
            if (artifact['name'] != f'quality-proof-{suite}' or artifact['expired']
                    or artifact['size_in_bytes'] > 65536):
                continue
            proof = get(f'actions/artifacts/{artifact["id"]}/zip', archive=True)
            if matches(proof, expected_tree, suite, run['id']):
                print(f'Reusing identical source tested by {run["html_url"]}')
                return True
    return False


def main():
    suite = os.environ.get('ACCEPTANCE_SUITE', 'smoke')
    if sys.argv[1] == 'record':
        proof = {'schema': 1, 'tree': tree(), 'suite': suite, 'run_id': os.environ['GITHUB_RUN_ID']}
        (Path(os.environ['RUNNER_TEMP']) / 'quality-proof.json').write_text(json.dumps(proof) + '\n')
        return
    reused = False
    def timed_out(*_):
        raise TimeoutError('Quality proof lookup exceeded 20 seconds')
    signal.signal(signal.SIGALRM, timed_out)
    if os.environ.get('REUSE_CI') == 'true':
        try:
            signal.alarm(20)
            reused = lookup(tree(), suite)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
            # A cache miss or unavailable API always runs the actual checks.
            print(f'::notice::Quality proof unavailable ({type(error).__name__}); running checks')
        finally:
            signal.alarm(0)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'reused={str(reused).lower()}\n')
        output.write('ref=' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() + '\n')


if __name__ == '__main__':
    main()
